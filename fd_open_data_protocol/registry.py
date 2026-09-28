"""Declarative registry adapters and coverage computation.

An adapter is a small YAML file mapping a source table's rows onto
:class:`~fd_open_data_protocol.schema.RegistryEntry` fields - no core code
changes when a new source database is onboarded. The recipe (see REGISTRY.md):

    写适配器 → 批量登记（register）→ 概念绑定（bind）→ 命名门核验（verify）

Row sources are independent of mapping: rows can come from a Postgres source
DSN or a CSV file (tests, dry runs, the shipped template example), so the
whole pipeline is exercisable without a database.

Coverage is asset-denominated: per source "registered / actual in source",
with the denominator taken from the source database (or supplied counts) -
never from an MCP concept dictionary.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import yaml
from pydantic import BaseModel, Field, field_validator

from fd_open_data_protocol.schema import RegistryEntry

#: registry fields an adapter may map; anchors come from dedicated keys.
MAPPABLE_FIELDS = ("semantic_code", "name_zh", "name_en", "unit", "frequency", "domain")

#: sources known to the fleet but NOT in the first registration batch; the
#: coverage view must show them explicitly instead of silently omitting them.
DEFAULT_SCOPE: dict[str, dict[str, Any]] = {
    "world_bank": {"phase": 1, "label": "世界银行 WDI（含宏观数据链路）"},
    "yearbook_catalog": {"phase": 1, "label": "国家统计年鉴"},
    "gta_panel": {"phase": 1, "label": "GTA 治理面板"},
    "china_city_panel": {"phase": 1, "label": "中国城市面板"},
    "law_db": {
        "phase": 1,
        "label": "法律库·文档域（法条/切片/指导案例为文档资产，非指标口径；登记 0 属预期，经 business-mcp 可查）",
    },
    "fd_open_data": {"phase": 1, "label": "fd_open_data 镜像概念字典"},
    "ia35": {"phase": 2, "label": "工商注册 161G（实体为主，二期）"},
    "wenshu_db": {"phase": 2, "label": "裁判文书（增量暂停，二期）"},
}


class FieldSource(BaseModel):
    """Where one registry field's value comes from.

    ``from: column``  - a column of the source row (or CSV header)
    ``from: literal`` - a constant (e.g. ``domain: macro``)
    ``from: map_file``- a JSON ``{native_code: value}`` lookup, typically a
                        curated/LLM-drafted naming map (name translations,
                        semantic codes); misses fall back to ``missing``
    """

    from_: str = Field(alias="from")
    value: str
    missing: Optional[str] = None  # value to store on a miss; default None = absent
    uppercase: bool = False

    @field_validator("from_")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in ("column", "literal", "map_file"):
            raise ValueError(f"unknown field source kind: {v!r} (column|literal|map_file)")
        return v

    model_config = {"populate_by_name": True}


class AdapterConfig(BaseModel):
    """Declarative source-table → registry mapping."""

    source_db: str
    source_table: str
    source_column: str = ""  # anchor label: the column the native code was read from
    native_code_column: str
    fields: dict[str, FieldSource]
    provenance_columns: list[str] = Field(default_factory=list)
    source_query: Optional[str] = None  # default: SELECT * FROM <source_table>
    semantic_code_dedupe_suffix: str = "-%d"  # in-batch collision suffix (marked needs_review)

    @field_validator("fields")
    @classmethod
    def _fields_known(cls, v: dict[str, FieldSource]) -> dict[str, FieldSource]:
        unknown = set(v) - set(MAPPABLE_FIELDS)
        if unknown:
            raise ValueError(f"unknown mappable field(s): {sorted(unknown)}")
        return v


def load_adapter(source: str | Path | dict) -> AdapterConfig:
    """Load an adapter from a YAML/JSON file path or an already-parsed dict."""
    if isinstance(source, dict):
        return AdapterConfig(**source)
    p = Path(source)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"adapter file did not parse to a mapping: {p}")
    adapter = AdapterConfig(**data)
    adapter._base_dir = p.parent  # type: ignore[attr-defined]  # resolve relative map_files
    return adapter


def _lookup(
    spec: FieldSource, row: dict, native_code: str, base_dir: Path
) -> Optional[str]:
    value: Any
    if spec.from_ == "literal":
        value = spec.value
    elif spec.from_ == "column":
        value = row.get(spec.value)
    else:  # map_file
        map_path = (base_dir / spec.value) if not Path(spec.value).is_absolute() else Path(spec.value)
        try:
            mapping = json.loads(map_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            value = spec.missing
            mapping = None
        else:
            value = mapping.get(native_code, spec.missing)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.upper() if spec.uppercase else text


def map_rows(
    adapter: AdapterConfig, rows: Iterable[dict[str, Any]]
) -> list[RegistryEntry]:
    """Map source rows to registry entries (pure; no store access).

    In-batch semantic_code collisions get a numeric suffix and a
    ``needs_review: true`` provenance flag - never a silent merge.
    """
    base_dir = getattr(adapter, "_base_dir", Path("."))
    seen_codes: dict[str, int] = {}
    entries: list[RegistryEntry] = []
    for row in rows:
        native_code = str(row.get(adapter.native_code_column, "") or "").strip()
        if not native_code:
            raise ValueError(
                f"row has empty {adapter.native_code_column!r}; adapter={adapter.source_db}.{adapter.source_table}"
            )
        fields: dict[str, Optional[str]] = {}
        needs_review = False
        for name, spec in adapter.fields.items():
            value = _lookup(spec, row, native_code, base_dir)
            if name == "semantic_code" and value is not None:
                base = value
                n = seen_codes.get(base, 0)
                if n:
                    value = base + (adapter.semantic_code_dedupe_suffix % (n + 1))
                    needs_review = True
                seen_codes[base] = n + 1
            fields[name] = value
        provenance = {c: row.get(c) for c in adapter.provenance_columns if c in row}
        if needs_review:
            provenance["needs_review"] = True
        entries.append(
            RegistryEntry(
                source_db=adapter.source_db,
                source_table=adapter.source_table,
                source_column=adapter.source_column or adapter.native_code_column,
                native_code=native_code,
                provenance=provenance or None,
                **fields,
            )
        )
    return entries


def fetch_rows(adapter: AdapterConfig, source_dsn: str) -> list[dict[str, Any]]:
    """Read all source rows via Postgres (psycopg3, dict rows)."""
    import psycopg

    sql = adapter.source_query or f"SELECT * FROM {adapter.source_table}"
    with psycopg.connect(source_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def read_rows_csv(path: str | Path) -> list[dict[str, Any]]:
    """Read source rows from a CSV (headers = column names). DB-free path."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return [{k: v for k, v in row.items() if k is not None} for row in csv.DictReader(fh)]


# ---------------------------------------------------------------------------
# Coverage (asset-denominated)


def count_source_rows(adapter: AdapterConfig, source_dsn: str) -> int:
    """Actual indicator rows in the source table - the coverage denominator."""
    import psycopg

    table = adapter.source_table
    with psycopg.connect(source_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {table}")
            return cur.fetchone()[0]


def coverage_report(
    store,
    actual_counts: Optional[dict[str, int]] = None,
    scope: Optional[dict[str, dict[str, Any]]] = None,
    module_map: Optional[dict[str, dict[str, list[str]]]] = None,
) -> dict[str, Any]:
    """Per-source registered/actual coverage + phase-2 visibility + unmapped audit.

    ``actual_counts``: {source_db: actual rows} - from the source databases
    themselves (``count_source_rows``) or supplied by the caller.
    ``module_map``: {"module": {"source_dbs": [...]}} - registered entries not
    matched by any module rule are listed as unmapped.
    """
    actual_counts = actual_counts or {}
    scope = scope or DEFAULT_SCOPE
    registered_by_db: dict[str, dict[str, int]] = {}
    for (source_db, _source_table), counts in store.count_by_source().items():
        bucket = registered_by_db.setdefault(source_db, {"registered": 0, "verified": 0})
        bucket["registered"] += counts["registered"]
        bucket["verified"] += counts["verified"]

    sources: list[dict[str, Any]] = []
    visible = (
        set(registered_by_db)
        | set(actual_counts)
        | {s for s, v in scope.items() if v.get("phase") == 2}
    )
    for source_db in sorted(visible):
        reg = registered_by_db.get(source_db, {"registered": 0, "verified": 0})
        actual = actual_counts.get(source_db)
        info = scope.get(source_db, {})
        sources.append(
            {
                "source_db": source_db,
                "label": info.get("label", ""),
                "phase": info.get("phase", 1),
                "registered": reg["registered"],
                "verified": reg["verified"],
                "unverified": reg["registered"] - reg["verified"],
                "actual_in_source": actual,
                "coverage": (
                    round(reg["registered"] / actual, 4) if actual else None
                ),
            }
        )

    report: dict[str, Any] = {"sources": sources}
    if module_map:
        unmapped = []
        covered_dbs = {db for m in module_map.values() for db in m.get("source_dbs", [])}
        for entry in store.iter_entries():
            if entry.source_db not in covered_dbs:
                unmapped.append(
                    {
                        "source_db": entry.source_db,
                        "native_code": entry.native_code,
                        "semantic_code": entry.semantic_code,
                        "name_zh": entry.name_zh,
                    }
                )
        report["module_map"] = module_map
        report["unmapped_count"] = len(unmapped)
        report["unmapped_sample"] = unmapped[:200]
    return report
