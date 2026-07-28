"""Pydantic schema for the datasource manifest (the protocol contract).

A manifest declares a datasource's identity, functions, columns, concept
hints, and fetch reference. Column-level ``frequency``/``datasource`` come from
``enrich-concept-identity``; ``measure``/``entity_type`` are concept-level
(via ``ConceptHint``).
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


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


class FunctionSpec(BaseModel):
    command: str
    category: Optional[str] = None
    description: Optional[str] = None
    parameters: list[ParamSpec] = Field(default_factory=list)
    columns: list[ColumnSpec] = Field(default_factory=list)
    frequency: Optional[str] = None
    verified: bool = True


class ConceptHint(BaseModel):
    column: str
    concept: str
    entity_type: str
    measure: Optional[str] = None
    unit: Optional[str] = None
    frequency: Optional[str] = None
    confidence: float = 0.9


class FetchRef(BaseModel):
    runner: Optional[str] = None   # built-in runner name
    module: Optional[str] = None   # "pkg.mod:func" import path


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
    fetch: Optional[FetchRef] = None
