"""Versioned semantic vocabulary: loader + structural validator.

The vocabulary is the publishable semantic core of the protocol — machine
readable YAML shipped in ``fd_open_data_protocol/vocabulary/`` covering entity
types, concept families, qualifiers, units, relation types and event types,
plus external crosswalk assertions under ``crosswalks/``.

Every entry carries a stable, versionless URI
(``https://schema.finddata.tech/<kind>/<Id>``). URIs are never reassigned and
entries are never deleted: retirement is a ``superseded_by`` pointer.

Usage::

    from fd_open_data_protocol.vocabulary import load_vocabulary

    vocab = load_vocabulary()                     # shipped files
    vocab = load_vocabulary("/path/to/vocabulary")  # explicit directory
    vocab.get("concept", "GDP").uri
    vocab.entity_type_ids()

``validate_vocabulary(dir)`` returns a list of human-readable problems instead
of raising, for CLI/reporting use.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

import yaml

SCHEMA_BASE_URI = "https://schema.finddata.tech"

# Registry kind -> shipped filename. The kind is also the URI path segment.
FILES: dict[str, str] = {
    "entity-type": "entity_types.yaml",
    "concept": "concepts.yaml",
    "qualifier": "qualifiers.yaml",
    "unit": "units.yaml",
    "relation-type": "relation_types.yaml",
    "event-type": "event_types.yaml",
}

# SKOS mapping properties: skos:exactMatch / closeMatch / broadMatch /
# narrowMatch / relatedMatch. Shared with consumers so crosswalk ingestion and
# recording agree on the allowed set.
RELATION_TYPES: tuple[str, ...] = ("exact", "close", "broader", "narrower", "related")

_REQUIRED_ENTRY_FIELDS = ("id", "label_en", "label_zh")
_ISO4217 = re.compile(r"^[A-Z]{3}$")


class VocabularyError(ValueError):
    """Raised when a vocabulary file set fails structural validation."""


def build_uri(kind: str, entry_id: str) -> str:
    """Return the stable URI for a vocabulary entry."""
    return f"{SCHEMA_BASE_URI}/{kind}/{entry_id}"


def default_vocabulary_dir() -> Path:
    """The vocabulary directory shipped inside the installed package."""
    return Path(__file__).resolve().parent / "vocabulary"


@dataclass(frozen=True)
class VocabularyEntry:
    """One vocabulary entry, with its stable URI and kind-specific fields."""

    kind: str
    id: str
    label_en: str
    label_zh: str = ""
    description: Optional[str] = None
    superseded_by: Optional[str] = None
    fields: dict[str, Any] = field(default_factory=dict)

    @property
    def uri(self) -> str:
        return build_uri(self.kind, self.id)

    @property
    def deprecated(self) -> bool:
        return bool(self.superseded_by)

    def get(self, key: str, default: Any = None) -> Any:
        return self.fields.get(key, default)


@dataclass(frozen=True)
class SeededVariable:
    """A Variable identity a concept family declares as initial seed content."""

    family_id: str
    code: str
    entity_type: str
    measure: str
    unit: str
    frequency: str


@dataclass
class VocabularyRegistry:
    """A loaded vocabulary file set."""

    version: str
    entries: dict[str, list[VocabularyEntry]]
    mappings: list[dict[str, Any]]
    source_dir: Optional[Path] = None

    def kind(self, kind: str) -> list[VocabularyEntry]:
        """Entries of one kind (``concept``, ``unit``, ...)."""
        return list(self.entries.get(kind, []))

    def get(self, kind: str, entry_id: str) -> Optional[VocabularyEntry]:
        """One entry by id, or None."""
        for e in self.entries.get(kind, []):
            if e.id == entry_id:
                return e
        return None

    def ids(self, kind: str) -> list[str]:
        return [e.id for e in self.entries.get(kind, [])]

    def entity_type_ids(self) -> tuple[str, ...]:
        return tuple(self.ids("entity-type"))

    def concept_families(self) -> list[VocabularyEntry]:
        return self.kind("concept")

    def seeded_variables(self) -> list[SeededVariable]:
        """Every Variable identity declared under a family's ``variables:`` block."""
        out: list[SeededVariable] = []
        for e in self.kind("concept"):
            for v in e.get("variables") or []:
                out.append(SeededVariable(
                    family_id=e.id,
                    code=v.get("code", ""),
                    entity_type=v.get("entity_type", ""),
                    measure=v.get("measure") or "",
                    unit=v.get("unit") or "",
                    frequency=v.get("frequency") or "unknown",
                ))
        return out


# --- validation -------------------------------------------------------------

def _read_yaml(path: Path, errors: list[str]) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as e:  # noqa: BLE001 - surfaced verbatim
        errors.append(f"{path.name}: cannot read/parse: {e}")
        return None


def _validate_entries(filename: str, entries: Any, errors: list[str]) -> list[dict]:
    """Validate the entry list of one registry file. Returns the valid entries."""
    if not isinstance(entries, list):
        errors.append(f"{filename}: 'entries' must be a list")
        return []

    valid: list[dict] = []
    seen: dict[str, int] = {}
    for i, entry in enumerate(entries):
        where = f"{filename}[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: entry must be a mapping")
            continue
        ok = True
        for key in _REQUIRED_ENTRY_FIELDS:
            val = entry.get(key)
            if not isinstance(val, str) or not val.strip():
                errors.append(f"{where}: missing required field '{key}'")
                ok = False
        eid = entry.get("id")
        if isinstance(eid, str) and eid.strip():
            if eid in seen:
                errors.append(
                    f"{filename}: duplicate id '{eid}' (entries {seen[eid]} and {i})"
                )
            else:
                seen[eid] = i
        pattern = entry.get("pattern")
        if pattern is not None:
            try:
                matched = re.fullmatch(str(pattern), str(eid))
            except re.error as e:
                errors.append(f"{where}: invalid 'pattern' regex: {e}")
                matched = True
            if not matched:
                errors.append(f"{where}: id '{eid}' does not match pattern '{pattern}'")
        iso = entry.get("iso4217")
        if iso is not None and not _ISO4217.match(str(iso)):
            errors.append(f"{where}: 'iso4217' must be a 3-letter alpha code, got '{iso}'")
        variables = entry.get("variables")
        if variables is not None:
            if not isinstance(variables, list):
                errors.append(f"{where}: 'variables' must be a list")
            else:
                for j, v in enumerate(variables):
                    if not isinstance(v, dict):
                        errors.append(f"{where}.variables[{j}]: must be a mapping")
                    elif not v.get("code"):
                        errors.append(f"{where}.variables[{j}]: missing required field 'code'")
        if ok:
            valid.append(entry)

    # superseded_by pointers must resolve within the same registry.
    ids = set(seen)
    for entry in valid:
        target = entry.get("superseded_by")
        if target and target not in ids:
            errors.append(
                f"{filename}: '{entry.get('id')}' has superseded_by '{target}' "
                f"which is not an entry in this file"
            )
    return valid


def _validate_mappings(filename: str, mappings: Any, errors: list[str]) -> None:
    if not isinstance(mappings, list):
        errors.append(f"{filename}: 'mappings' must be a list")
        return
    for i, m in enumerate(mappings):
        where = f"{filename}[{i}]"
        if not isinstance(m, dict):
            errors.append(f"{where}: mapping must be a mapping")
            continue
        for key in ("code", "entity_type", "vocabulary", "term", "relation"):
            if not m.get(key):
                errors.append(f"{where}: missing required field '{key}'")
        relation = m.get("relation")
        if relation and relation not in RELATION_TYPES:
            errors.append(
                f"{where}: unknown relation '{relation}'; "
                f"expected one of {', '.join(RELATION_TYPES)}"
            )
        confidence = m.get("confidence")
        if confidence is not None and not (isinstance(confidence, (int, float))
                                           and 0.0 <= float(confidence) <= 1.0):
            errors.append(f"{where}: 'confidence' must be between 0 and 1, got '{confidence}'")


def validate_vocabulary(dir: Optional[Union[str, Path]] = None) -> list[str]:
    """Return structural problems with a vocabulary directory (empty list = valid)."""
    d = Path(dir) if dir is not None else default_vocabulary_dir()
    errors: list[str] = []
    if not d.is_dir():
        return [f"{d}: vocabulary directory not found"]

    versions: list[tuple[str, str]] = []

    for filename in FILES.values():
        path = d / filename
        if not path.exists():
            errors.append(f"{filename}: missing vocabulary file")
            continue
        data = _read_yaml(path, errors)
        if data is None:
            continue
        if not isinstance(data, dict):
            errors.append(f"{filename}: expected a mapping at the top level")
            continue
        version = data.get("version")
        if not isinstance(version, str) or not version.strip():
            errors.append(f"{filename}: missing required top-level 'version'")
        else:
            versions.append((filename, version))
        if "entries" not in data:
            errors.append(f"{filename}: missing required top-level 'entries'")
        else:
            _validate_entries(filename, data["entries"], errors)

    cw_dir = d / "crosswalks"
    if cw_dir.is_dir():
        for path in sorted(cw_dir.glob("*.yaml")):
            data = _read_yaml(path, errors)
            if data is None:
                continue
            if not isinstance(data, dict):
                errors.append(f"{path.name}: expected a mapping at the top level")
                continue
            version = data.get("version")
            if not isinstance(version, str) or not version.strip():
                errors.append(f"{path.name}: missing required top-level 'version'")
            else:
                versions.append((path.name, version))
            if "mappings" not in data:
                errors.append(f"{path.name}: missing required top-level 'mappings'")
            else:
                _validate_mappings(path.name, data["mappings"], errors)

    if versions:
        first_file, first_version = versions[0]
        for filename, version in versions[1:]:
            if version != first_version:
                errors.append(
                    f"{filename}: version '{version}' disagrees with "
                    f"{first_file} version '{first_version}'"
                )
    return errors


# --- loading ----------------------------------------------------------------

def load_vocabulary(dir: Optional[Union[str, Path]] = None) -> VocabularyRegistry:
    """Load and validate the vocabulary, raising ``VocabularyError`` if invalid."""
    errors = validate_vocabulary(dir)
    if errors:
        raise VocabularyError(
            "invalid vocabulary: " + "; ".join(errors)
        )

    d = Path(dir) if dir is not None else default_vocabulary_dir()
    entries: dict[str, list[VocabularyEntry]] = {}
    version = ""

    for kind, filename in FILES.items():
        data = yaml.safe_load((d / filename).read_text(encoding="utf-8"))
        version = version or data["version"]
        loaded: list[VocabularyEntry] = []
        for raw in data["entries"]:
            extra = {
                k: v for k, v in raw.items()
                if k not in ("id", "label_en", "label_zh", "description", "superseded_by")
            }
            loaded.append(VocabularyEntry(
                kind=kind,
                id=raw["id"],
                label_en=raw["label_en"],
                label_zh=raw["label_zh"],
                description=raw.get("description"),
                superseded_by=raw.get("superseded_by"),
                fields=extra,
            ))
        entries[kind] = loaded

    mappings: list[dict[str, Any]] = []
    cw_dir = d / "crosswalks"
    if cw_dir.is_dir():
        for path in sorted(cw_dir.glob("*.yaml")):
            mappings.extend(yaml.safe_load(path.read_text(encoding="utf-8"))["mappings"])

    return VocabularyRegistry(
        version=version, entries=entries, mappings=mappings, source_dir=d,
    )
