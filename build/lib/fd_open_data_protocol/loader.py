"""Catalog loader: parse a manifest from YAML, JSON, a Python file/module, or a dict.

``load_catalog(source)`` returns a validated ``DatasourceManifest``. This is
the consumer entry point: a consumer (fd-open-data-mcp's ``register_datasource``,
or any other) calls ``load_catalog`` then ingests.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Union

import yaml

from fd_open_data_protocol.schema import DatasourceManifest

ManifestSource = Union[str, Path, dict, DatasourceManifest]


def _manifest_from_catalog(catalog: Any) -> DatasourceManifest:
    if isinstance(catalog, DatasourceManifest):
        return catalog
    if isinstance(catalog, dict):
        return DatasourceManifest(**catalog)
    raise ValueError(f"CATALOG is {type(catalog).__name__}, expected dict or DatasourceManifest")


def load_catalog(source: ManifestSource) -> DatasourceManifest:
    """Load + validate a ``DatasourceManifest`` from a path, module, dict, or manifest."""
    if isinstance(source, DatasourceManifest):
        return source
    if isinstance(source, dict):
        return DatasourceManifest(**source)
    if isinstance(source, (str, Path)):
        s = str(source)
        p = Path(s)
        if p.is_file():
            suffix = p.suffix.lower()
            if suffix in (".yaml", ".yml"):
                data = yaml.safe_load(p.read_text())
                if not isinstance(data, dict):
                    raise ValueError(f"YAML manifest did not parse to a dict: {s}")
                return DatasourceManifest(**data)
            if suffix == ".json":
                return DatasourceManifest(**json.loads(p.read_text()))
            if suffix == ".py":
                # exec the file, read CATALOG
                spec = importlib.util.spec_from_file_location("_fd_odp_manifest", p)
                if spec is None or spec.loader is None:
                    raise ValueError(f"cannot create module spec for {s}")
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                catalog = getattr(mod, "CATALOG", None)
                if catalog is None:
                    raise ValueError(f"{s} has no CATALOG attribute")
                return _manifest_from_catalog(catalog)
            raise ValueError(f"unsupported manifest file type: {suffix} ({s})")
        # treat as a Python module path "pkg.mod" exposing CATALOG
        try:
            mod = importlib.import_module(s)
        except ImportError as e:
            raise ValueError(f"neither a file nor an importable module: {s}") from e
        catalog = getattr(mod, "CATALOG", None)
        if catalog is None:
            raise ValueError(f"module {s} has no CATALOG attribute")
        return _manifest_from_catalog(catalog)
    raise TypeError(f"unsupported source type: {type(source).__name__}")
