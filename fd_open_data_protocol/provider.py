"""The DataProvider interface (optional companion to a manifest).

A manifest is the *declarative* catalog. A datasource that also ships fetch
code implements ``DataProvider`` (or subclasses ``BaseDataProvider``) so the
consumer can call ``run()``. The manifest's ``fetch`` field references the
runner (a built-in name or a module path); the class is for providers that
prefer to bundle catalog + code.
"""
from __future__ import annotations

from typing import Any, Optional


class DataProvider:
    """Structural interface (duck-typed). A provider has ``name``,
    ``registry()``, and ``run(command, params)``."""

    name: str

    def registry(self) -> dict:
        raise NotImplementedError

    def run(self, command: str, params: dict) -> Any:
        raise NotImplementedError


class BaseDataProvider:
    """Base class with empty defaults for optional facets. Subclass and
    override ``registry`` + ``run``; the rest are no-ops by default."""

    name: str = ""

    def registry(self) -> dict:
        raise NotImplementedError

    def run(self, command: str, params: dict) -> Any:
        raise NotImplementedError

    def introspect(self) -> list[dict]:
        return []

    def seed_entities(self, session: Any) -> dict:
        return {}

    def concept_rules(self) -> list:
        return []

    def build_params(self, fn: Any, identifier: str, date: str, binding: Any = None) -> dict:
        return {}
