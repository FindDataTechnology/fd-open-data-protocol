"""Pydantic schema for the datasource manifest (the protocol contract).

A manifest declares a datasource's identity, functions, columns, concept
hints, and fetch reference. Column-level ``frequency``/``datasource`` come from
``enrich-concept-identity``; ``measure``/``entity_type`` are concept-level
(via ``ConceptHint``).

Entity definitions are optional - when provided, they register canonical
entity metadata (names, attributes, relationships) in the ontology database.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterable, Optional

from pydantic import BaseModel, Field, field_validator


@lru_cache(maxsize=1)
def _concept_family_ids() -> frozenset[str]:
    """Concept family ids from the shipped vocabulary (loaded once per process)."""
    from fd_open_data_protocol.vocabulary import load_vocabulary

    return frozenset(load_vocabulary().ids("concept"))


class _EntityTypeVocabulary:
    """Lazy, file-sourced view of ``vocabulary/entity_types.yaml``.

    Replaces the hardcoded tuple of entity types while keeping the public name
    and the operations callers use (membership, iteration, ``len``, ``join``).
    The file is read on first use, not at import time. An override can be
    pinned for tests via :func:`set_entity_type_vocabulary`.
    """

    def __init__(self) -> None:
        self._override: Optional[tuple[str, ...]] = None
        self._cache: Optional[tuple[str, ...]] = None

    def _values(self) -> tuple[str, ...]:
        if self._override is not None:
            return self._override
        if self._cache is None:
            from fd_open_data_protocol.vocabulary import load_vocabulary

            self._cache = load_vocabulary().entity_type_ids()
        return self._cache

    def set(self, values: Optional[Iterable[str]] = None) -> None:
        """Pin the vocabulary to ``values``, or reset to file-sourced when None."""
        self._override = tuple(values) if values is not None else None

    def __contains__(self, item: object) -> bool:
        return item in self._values()

    def __iter__(self):
        return iter(self._values())

    def __len__(self) -> int:
        return len(self._values())

    def __getitem__(self, index):
        return self._values()[index]

    def __repr__(self) -> str:
        return repr(self._values())


# Canonical entity type vocabulary - all entity_type values must be in this set.
# Sourced from the shipped vocabulary file; see fd_open_data_protocol.vocabulary.
ENTITY_TYPE_VOCABULARY = _EntityTypeVocabulary()


def set_entity_type_vocabulary(values: Optional[Iterable[str]] = None) -> None:
    """Test escape hatch: pin the entity-type vocabulary, or reset to file-sourced."""
    ENTITY_TYPE_VOCABULARY.set(values)


class EntityRelationship(BaseModel):
    """Bidirectional relationship between entities.

    Examples:
    - stock -> industry: "belongs_to"
    - company -> sector: "has_sector"
    - city -> country: "located_in"
    """
    target_entity_type: str
    target_code: str  # canonical identifier of target entity
    relation_type: str        # e.g., "belongs_to", "has_sector", "located_in", "traded_on"
    confidence: float = 0.9
    metadata: Optional[dict[str, Any]] = None  # optional relationship metadata (temporal validity, etc.)

    @field_validator("target_entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        if v not in ENTITY_TYPE_VOCABULARY:
            raise ValueError(
                f"Invalid target_entity_type '{v}'. Must be one of: {', '.join(ENTITY_TYPE_VOCABULARY)}"
            )
        return v


class Entity(BaseModel):
    """Canonical entity definition with metadata and relationships.

    When included in a manifest, entities are registered in the ontology database
    during register_datasource(). This allows:
    - Standardized entity metadata (names, attributes)
    - Relationship queries (stock -> industry, company -> sector)
    - Better concept validation (entity_type must exist in registry)

    Example:
    ```yaml
    entities:
      - entity_type: country
        code: CN
        name_en: China
        name_zh: 中国
        metadata:
          region: Asia
      - entity_type: industry
        code: shenwan_1_01
        name_zh: 银行
        metadata:
          classification_system: shenwan
          level: 1
    ```
    """
    entity_type: str
    code: str  # canonical identifier (ISO code, ticker, classification code, etc.)
    name_en: Optional[str] = None
    name_zh: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None  # flexible metadata (sector, region, exchange, etc.)
    relationships: Optional[list[EntityRelationship]] = None

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        if v not in ENTITY_TYPE_VOCABULARY:
            raise ValueError(
                f"Invalid entity_type '{v}'. Must be one of: {', '.join(ENTITY_TYPE_VOCABULARY)}"
            )
        return v


class ParamSpec(BaseModel):
    name: str
    type: Optional[str] = None
    required: bool = False
    description: Optional[str] = None


class ColumnSpec(BaseModel):
    name: str
    type: Optional[str] = None
    description: Optional[str] = None
    meaning: Optional[str] = None
    semantic_type: Optional[str] = None
    frequency: Optional[str] = None   # column-level cadence (defaults to the function's)
    datasource: Optional[str] = None  # column-level source (defaults to the manifest's)


class RealSourceSpec(BaseModel):
    """Real data source declaration (actual data provider, not library).

    A function may call multiple real data sources (e.g., akshare calls eastmoney,
    tencent, sina). This spec declares which real sources are used, with priority
    for failover ordering.

    Example:
    ```yaml
    real_sources:
      - name: eastmoney
        priority: 0  # primary source
      - name: tencent
        priority: 1  # failover if eastmoney is banned
    ```
    """
    name: str  # canonical real source name (e.g., "eastmoney", "tencent", "sina", "yahoo_finance")
    priority: int = 0  # failover order: 0 = primary, 1+ = failover
    endpoint: Optional[str] = None  # optional: specific method or URL


class FunctionSpec(BaseModel):
    command: str
    category: Optional[str] = None
    description: Optional[str] = None
    parameters: list[ParamSpec] = Field(default_factory=list)
    columns: list[ColumnSpec] = Field(default_factory=list)
    frequency: Optional[str] = None
    verified: bool = True
    real_sources: Optional[list[RealSourceSpec]] = None  # real data sources this function calls


class ConceptHint(BaseModel):
    column: str
    concept: str
    entity_type: str
    measure: Optional[str] = None
    unit: Optional[str] = None
    frequency: Optional[str] = None
    confidence: float = 0.9
    # Optional reference to a concept family in vocabulary/concepts.yaml, tying
    # this concept to the two-level semantic model. Omitted = no family check.
    concept_family: Optional[str] = None

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        if v not in ENTITY_TYPE_VOCABULARY:
            raise ValueError(
                f"Invalid entity_type '{v}'. Must be one of: {', '.join(ENTITY_TYPE_VOCABULARY)}"
            )
        return v

    @field_validator("concept_family")
    @classmethod
    def validate_concept_family(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in _concept_family_ids():
            raise ValueError(
                f"Unknown concept family '{v}'. Must be one of: "
                f"{', '.join(sorted(_concept_family_ids()))}"
            )
        return v


class FetchRef(BaseModel):
    runner: Optional[str] = None   # built-in runner name
    module: Optional[str] = None   # "pkg.mod:func" import path


class EntitySpec(BaseModel):
    """Entity coverage declaration.

    Tells the consumer which entity types this datasource covers.
    - coverage="universe": datasource can fetch data for all entities of this type
    - coverage="explicit": datasource only covers the listed codes
    """
    entity_type: str
    coverage: str = "universe"  # "universe" or "explicit"
    codes: Optional[list[str]] = None  # required if coverage="explicit"

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        if v not in ENTITY_TYPE_VOCABULARY:
            raise ValueError(
                f"Invalid entity_type '{v}'. Must be one of: {', '.join(ENTITY_TYPE_VOCABULARY)}"
            )
        return v


class RelationshipSpec(BaseModel):
    """Relationship resolution declaration.

    Tells the consumer how to resolve relationships for this datasource.
    - relation_type: e.g., "listed_as", "operates_in", "located_in"
    - resolver_module: optional Python module path "pkg.mod:func" that returns
      [(source_code, target_code), ...] tuples
    """
    relation_type: str
    source_entity_type: str
    target_entity_type: str
    resolver_module: Optional[str] = None


class DatasourceManifest(BaseModel):
    version: str = "1"
    name: str
    label: str
    source_url: Optional[str] = None
    scanner_mode: str = "upstream-curated"
    requires: list[str] = Field(default_factory=list)
    ranking_seed: list[float] = Field(default_factory=lambda: [0.5, 0.5])
    functions: list[FunctionSpec]
    concepts: list[ConceptHint] = Field(default_factory=list)
    # Entity coverage declarations (which entity types this datasource covers)
    entities: list[EntitySpec] = Field(default_factory=list)
    # Optional: canonical entity definitions with metadata and relationships
    entity_definitions: list[Entity] = Field(default_factory=list)
    relationships: list[RelationshipSpec] = Field(default_factory=list)
    fetch: Optional[FetchRef] = None
