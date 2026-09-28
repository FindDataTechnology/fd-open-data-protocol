"""Registry stores: where ``RegistryEntry`` rows live.

The physical table (``fd_open_data.registry_entries`` on the Windows data
machine) is created from :data:`REGISTRY_ENTRIES_DDL`. Two stores implement
the same semantics:

- ``MemoryRegistryStore`` - exact in-memory twin used by tests and dry runs;
- ``PostgresRegistryStore`` - psycopg3-backed, the real one.

Upsert semantics (identical in both, computed by :func:`compute_upsert_stats`):

- anchor ``(source_db, source_table, source_column, native_code)`` is the
  identity; re-registering an unchanged source row updates in place, never
  duplicates;
- naming drift (``semantic_code``/``name_zh``/``name_en`` changed on an
  already-verified entry) demotes it to unverified - naming changes go
  through re-verification;
- upsert never sets ``verified``; that is :meth:`BaseRegistryStore.set_verified`,
  which refuses entries failing the naming gate.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Optional, Sequence

from fd_open_data_protocol.schema import (
    NAMING_GATE_FIELDS,
    RegistryEntry,
    naming_gate_passed,
)

REGISTRY_ENTRIES_DDL = """
CREATE TABLE IF NOT EXISTS registry_entries (
    id            BIGSERIAL PRIMARY KEY,
    source_db     TEXT NOT NULL,
    source_table  TEXT NOT NULL,
    source_column TEXT NOT NULL DEFAULT '',
    native_code   TEXT NOT NULL,
    semantic_code TEXT,
    name_zh       TEXT,
    name_en       TEXT,
    unit          TEXT,
    frequency     TEXT,
    domain        TEXT,
    provenance    JSONB,
    verified      BOOLEAN NOT NULL DEFAULT FALSE,
    verified_at   TIMESTAMPTZ,
    verified_by   TEXT,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_registry_anchor UNIQUE (source_db, source_table, source_column, native_code)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_registry_semantic_code
    ON registry_entries (semantic_code)
    WHERE semantic_code IS NOT NULL;
"""

NamingState = tuple[Optional[str], Optional[str], Optional[str]]


def naming_state(entry: RegistryEntry) -> NamingState:
    """The fields whose change counts as naming drift."""
    return (entry.semantic_code, entry.name_zh, entry.name_en)


@dataclass
class UpsertStats:
    new: int = 0        # anchors not seen before
    updated: int = 0    # existing anchors with changed content
    unchanged: int = 0  # existing anchors with identical content
    demoted: int = 0    # verified entries demoted by naming drift

    @property
    def total(self) -> int:
        return self.new + self.updated + self.unchanged

    def as_dict(self) -> dict:
        return {
            "new": self.new,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "demoted": self.demoted,
            "total_anchors": self.total,
        }


@dataclass
class _ExistingRow:
    naming: NamingState
    content_hash: tuple
    verified: bool


def compute_upsert_stats(
    existing: dict[tuple, _ExistingRow], incoming: Sequence[RegistryEntry]
) -> tuple[UpsertStats, dict[tuple, RegistryEntry]]:
    """Diff an incoming batch against existing rows.

    Returns per-anchor stats plus the merged view of what each anchor should
    look like after the upsert (existing verified state wins unless naming
    drifted). Both stores drive their writes off this so tests exercise the
    same transition rules as Postgres.
    """
    stats = UpsertStats()
    merged: dict[tuple, RegistryEntry] = {}
    # in-batch duplicate anchors (same source row twice, or a table whose rows
    # share a code) count once; last occurrence wins
    deduped: dict[tuple, RegistryEntry] = {}
    for entry in incoming:
        deduped[entry.anchor()] = entry
    for entry in deduped.values():
        anchor = entry.anchor()
        prev = existing.get(anchor)
        if prev is None:
            stats.new += 1
            merged[anchor] = entry.model_copy(update={"verified": False})
            continue
        if prev.content_hash == _content_hash(entry):
            stats.unchanged += 1
            merged[anchor] = entry.model_copy(
                update={"verified": prev.verified}
            )
        else:
            stats.updated += 1
            demoted = prev.verified and prev.naming != naming_state(entry)
            if demoted:
                stats.demoted += 1
            merged[anchor] = entry.model_copy(update={"verified": False if demoted else prev.verified})
    return stats, merged


def _content_hash(entry: RegistryEntry) -> tuple:
    return (
        entry.semantic_code,
        entry.name_zh,
        entry.name_en,
        entry.unit,
        entry.frequency,
        entry.domain,
        json.dumps(entry.provenance, sort_keys=True, ensure_ascii=False)
        if entry.provenance
        else None,
    )


class BaseRegistryStore(ABC):
    """Storage contract for the unified registry."""

    @abstractmethod
    def init_schema(self) -> None: ...

    @abstractmethod
    def upsert_entries(self, entries: Sequence[RegistryEntry]) -> UpsertStats: ...

    @abstractmethod
    def set_verified(
        self,
        anchors: Optional[Iterable[tuple]] = None,
        verified_by: str = "rule:naming-gate",
        source_db: Optional[str] = None,
    ) -> int:
        """Mark entries verified. Refuses (skips) entries failing the naming gate."""

    @abstractmethod
    def count_by_source(self) -> dict[tuple[str, str], dict[str, int]]:
        """{（source_db, source_table): {"registered": n, "verified": m}}"""

    @abstractmethod
    def iter_entries(
        self, verified_only: bool = False, source_db: Optional[str] = None
    ) -> Iterator[RegistryEntry]: ...


class MemoryRegistryStore(BaseRegistryStore):
    """In-memory twin of the Postgres store; used by tests and dry runs."""

    def __init__(self) -> None:
        self.rows: dict[tuple, RegistryEntry] = {}

    def init_schema(self) -> None:  # nothing to create
        return None

    def _existing_view(self, entries: Sequence[RegistryEntry]) -> dict[tuple, _ExistingRow]:
        view: dict[tuple, _ExistingRow] = {}
        for anchor, row in self.rows.items():
            view[anchor] = _ExistingRow(naming_state(row), _content_hash(row), row.verified)
        return view

    def upsert_entries(self, entries: Sequence[RegistryEntry]) -> UpsertStats:
        stats, merged = compute_upsert_stats(self._existing_view(entries), entries)
        for anchor, entry in merged.items():
            self.rows[anchor] = entry
        return stats

    def set_verified(
        self,
        anchors: Optional[Iterable[tuple]] = None,
        verified_by: str = "rule:naming-gate",
        source_db: Optional[str] = None,
    ) -> int:
        targets = list(anchors) if anchors is not None else list(self.rows)
        count = 0
        for anchor in targets:
            row = self.rows.get(anchor)
            if row is None:
                continue
            if source_db is not None and row.source_db != source_db:
                continue
            if not naming_gate_passed(row) or row.verified:
                continue
            self.rows[anchor] = row.model_copy(
                update={
                    "verified": True,
                    "verified_at": "1970-01-01T00:00:00+00:00",  # placeholder; PG sets now()
                    "verified_by": verified_by,
                }
            )
            count += 1
        return count

    def count_by_source(self) -> dict[tuple[str, str], dict[str, int]]:
        out: dict[tuple[str, str], dict[str, int]] = {}
        for row in self.rows.values():
            key = (row.source_db, row.source_table)
            bucket = out.setdefault(key, {"registered": 0, "verified": 0})
            bucket["registered"] += 1
            bucket["verified"] += 1 if row.verified else 0
        return out

    def iter_entries(
        self, verified_only: bool = False, source_db: Optional[str] = None
    ) -> Iterator[RegistryEntry]:
        for row in sorted(self.rows.values(), key=lambda r: r.anchor()):
            if verified_only and not row.verified:
                continue
            if source_db is not None and row.source_db != source_db:
                continue
            yield row


# The column list shared by INSERT and SELECT paths.
_ENTRY_COLUMNS = (
    "source_db", "source_table", "source_column", "native_code",
    "semantic_code", "name_zh", "name_en", "unit", "frequency", "domain",
    "provenance",
)


class PostgresRegistryStore(BaseRegistryStore):
    """psycopg3-backed store. Import psycopg lazily; extra: ``[registry]``."""

    def __init__(self, dsn: str) -> None:
        try:
            import psycopg  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "PostgresRegistryStore needs psycopg; install fd-open-data-protocol[registry]"
            ) from e
        self.dsn = dsn

    def _connect(self):
        import psycopg

        return psycopg.connect(self.dsn)

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(REGISTRY_ENTRIES_DDL)
            conn.commit()

    def upsert_entries(self, entries: Sequence[RegistryEntry]) -> UpsertStats:
        if not entries:
            return UpsertStats()
        with self._connect() as conn:
            anchors = [e.anchor() for e in entries]
            existing: dict[tuple, _ExistingRow] = {}
            with conn.cursor() as cur:
                # per-column ANY prefilter (psycopg cannot bind lists of tuples
                # into an anonymous-composite ANY), exact match client-side
                cur.execute(
                    """
                    SELECT source_db, source_table, source_column, native_code,
                           semantic_code, name_zh, name_en, unit, frequency, domain,
                           provenance, verified
                    FROM registry_entries
                    WHERE source_db = ANY (%s) AND source_table = ANY (%s)
                      AND source_column = ANY (%s) AND native_code = ANY (%s)
                    """,
                    (
                        sorted({a[0] for a in anchors}),
                        sorted({a[1] for a in anchors}),
                        sorted({a[2] for a in anchors}),
                        sorted({a[3] for a in anchors}),
                    ),
                )
                wanted = set(anchors)
                for r in cur.fetchall():
                    anchor = (r[0], r[1], r[2], r[3])
                    if anchor not in wanted:
                        continue
                    existing[anchor] = _ExistingRow(
                        naming=(r[4], r[5], r[6]),
                        content_hash=(
                            r[4], r[5], r[6], r[7], r[8], r[9],
                            json.dumps(r[10], sort_keys=True, ensure_ascii=False)
                            if r[10] is not None
                            else None,
                        ),
                        verified=r[11],
                    )
            stats, merged = compute_upsert_stats(existing, entries)

            demoted = [
                a
                for a, e in merged.items()
                if a in existing and existing[a].verified and not e.verified
            ]
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO registry_entries
                        (source_db, source_table, source_column, native_code,
                         semantic_code, name_zh, name_en, unit, frequency, domain, provenance)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_db, source_table, source_column, native_code)
                    DO UPDATE SET
                        semantic_code = EXCLUDED.semantic_code,
                        name_zh = EXCLUDED.name_zh,
                        name_en = EXCLUDED.name_en,
                        unit = EXCLUDED.unit,
                        frequency = EXCLUDED.frequency,
                        domain = EXCLUDED.domain,
                        provenance = EXCLUDED.provenance,
                        verified = CASE
                            WHEN registry_entries.verified AND (
                                registry_entries.semantic_code IS DISTINCT FROM EXCLUDED.semantic_code
                                OR registry_entries.name_zh IS DISTINCT FROM EXCLUDED.name_zh
                                OR registry_entries.name_en IS DISTINCT FROM EXCLUDED.name_en
                            ) THEN FALSE
                            ELSE registry_entries.verified END,
                        verified_at = CASE
                            WHEN registry_entries.verified AND (
                                registry_entries.semantic_code IS DISTINCT FROM EXCLUDED.semantic_code
                                OR registry_entries.name_zh IS DISTINCT FROM EXCLUDED.name_zh
                                OR registry_entries.name_en IS DISTINCT FROM EXCLUDED.name_en
                            ) THEN NULL
                            ELSE registry_entries.verified_at END,
                        verified_by = CASE
                            WHEN registry_entries.verified AND (
                                registry_entries.semantic_code IS DISTINCT FROM EXCLUDED.semantic_code
                                OR registry_entries.name_zh IS DISTINCT FROM EXCLUDED.name_zh
                                OR registry_entries.name_en IS DISTINCT FROM EXCLUDED.name_en
                            ) THEN NULL
                            ELSE registry_entries.verified_by END,
                        updated_at = now()
                    """,
                    [
                        (
                            e.source_db, e.source_table, e.source_column, e.native_code,
                            e.semantic_code, e.name_zh, e.name_en, e.unit, e.frequency,
                            e.domain, json.dumps(e.provenance, ensure_ascii=False)
                            if e.provenance else None,
                        )
                        for e in merged.values()
                    ],
                )
                assert len(demoted) == stats.demoted  # SQL and stats must agree
            conn.commit()
            return stats

    def set_verified(
        self,
        anchors: Optional[Iterable[tuple]] = None,
        verified_by: str = "rule:naming-gate",
        source_db: Optional[str] = None,
    ) -> int:
        gate_sql = " AND ".join(f"{f} IS NOT NULL AND {f} <> ''" for f in NAMING_GATE_FIELDS)
        with self._connect() as conn:
            with conn.cursor() as cur:
                if anchors is not None:
                    anchor_list = list(anchors)
                    cur.execute(
                        f"""
                        UPDATE registry_entries
                        SET verified = TRUE, verified_at = now(), verified_by = %s
                        WHERE source_db = ANY (%s) AND source_table = ANY (%s)
                          AND source_column = ANY (%s) AND native_code = ANY (%s)
                          AND NOT verified AND ({gate_sql})
                        """,
                        (
                            verified_by,
                            sorted({a[0] for a in anchor_list}),
                            sorted({a[1] for a in anchor_list}),
                            sorted({a[2] for a in anchor_list}),
                            sorted({a[3] for a in anchor_list}),
                        ),
                    )
                else:
                    cur.execute(
                        f"""
                        UPDATE registry_entries
                        SET verified = TRUE, verified_at = now(), verified_by = %s
                        WHERE NOT verified{f" AND source_db = %s" if source_db else ""}
                          AND ({gate_sql})
                        """,
                        ((verified_by,) if source_db is None else (verified_by, source_db)),
                    )
                count = cur.rowcount
            conn.commit()
            return count

    def count_by_source(self) -> dict[tuple[str, str], dict[str, int]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT source_db, source_table,
                           count(*) AS registered,
                           count(*) FILTER (WHERE verified) AS verified
                    FROM registry_entries
                    GROUP BY source_db, source_table
                    ORDER BY source_db, source_table
                    """
                )
                return {
                    (r[0], r[1]): {"registered": r[2], "verified": r[3]} for r in cur.fetchall()
                }

    def iter_entries(
        self, verified_only: bool = False, source_db: Optional[str] = None
    ) -> Iterator[RegistryEntry]:
        where = []
        params: list = []
        if verified_only:
            where.append("verified")
        if source_db:
            where.append("source_db = %s")
            params.append(source_db)
        sql = (
            "SELECT " + ", ".join(_ENTRY_COLUMNS) + ", verified, verified_at, verified_by "
            "FROM registry_entries"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY source_db, source_table, native_code"
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                for r in cur.fetchall():
                    yield RegistryEntry(
                        **dict(zip(_ENTRY_COLUMNS, r[: len(_ENTRY_COLUMNS)])),
                        verified=r[len(_ENTRY_COLUMNS)],
                        verified_at=str(r[len(_ENTRY_COLUMNS) + 1])
                        if r[len(_ENTRY_COLUMNS) + 1] is not None
                        else None,
                        verified_by=r[len(_ENTRY_COLUMNS) + 2],
                    )
