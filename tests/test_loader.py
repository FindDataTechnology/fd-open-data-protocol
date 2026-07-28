"""Tests for fd-open-data-protocol: the catalog loader + schema."""
import json
from pathlib import Path

import pytest

from fd_open_data_protocol.loader import load_catalog
from fd_open_data_protocol.schema import DatasourceManifest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_load_yaml(tmp_path):
    f = tmp_path / "m.yaml"
    f.write_text("name: s\nlabel: S\nfunctions:\n  - command: f\n    columns:\n      - {name: c}\n")
    m = load_catalog(str(f))
    assert isinstance(m, DatasourceManifest)
    assert m.name == "s" and m.functions[0].command == "f"


def test_load_json(tmp_path):
    f = tmp_path / "m.json"
    f.write_text(json.dumps({"name": "s", "label": "S", "functions": [{"command": "f", "columns": []}]}))
    assert load_catalog(str(f)).name == "s"


def test_load_py_file(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("CATALOG = {'name':'s','label':'S','functions':[{'command':'f','columns':[]}]}\n")
    assert load_catalog(str(f)).name == "s"


def test_load_dict():
    m = load_catalog({"name": "s", "label": "S", "functions": []})
    assert m.name == "s" and m.ranking_seed == [0.5, 0.5]


def test_invalid_manifest_raises():
    with pytest.raises(Exception):
        load_catalog({"name": "s"})  # missing required label + functions


def test_examples_load():
    assert load_catalog(str(EXAMPLES / "example_stock.yaml")).name == "example-stock"
    assert load_catalog(str(EXAMPLES / "example_macro.py")).name == "example-macro"
