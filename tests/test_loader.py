"""Tests for fd-open-data-protocol: the catalog loader + schema."""
import json
from pathlib import Path

import pytest

from fd_open_data_protocol.loader import load_catalog
from fd_open_data_protocol.schema import DatasourceManifest, RealSourceSpec, FunctionSpec

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


def test_real_source_spec_minimal():
    """Test minimal RealSourceSpec with just name."""
    rs = RealSourceSpec(name="eastmoney")
    assert rs.name == "eastmoney"
    assert rs.priority == 0  # default
    assert rs.endpoint is None  # default


def test_real_source_spec_with_priority():
    """Test RealSourceSpec with priority."""
    rs = RealSourceSpec(name="tencent", priority=1)
    assert rs.name == "tencent"
    assert rs.priority == 1
    assert rs.endpoint is None


def test_real_source_spec_with_endpoint():
    """Test RealSourceSpec with endpoint."""
    rs = RealSourceSpec(name="eastmoney", endpoint="stock_zh_a_hist")
    assert rs.name == "eastmoney"
    assert rs.priority == 0
    assert rs.endpoint == "stock_zh_a_hist"


def test_real_source_spec_missing_name():
    """Test RealSourceSpec without name raises error."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RealSourceSpec()  # missing required name


def test_function_spec_without_real_sources():
    """Test FunctionSpec without real_sources (backward compatibility)."""
    fs = FunctionSpec(command="test")
    assert fs.command == "test"
    assert fs.real_sources is None


def test_function_spec_with_real_sources():
    """Test FunctionSpec with real_sources."""
    fs = FunctionSpec(
        command="stock_zh_a_hist",
        real_sources=[
            RealSourceSpec(name="eastmoney", priority=0),
            RealSourceSpec(name="tencent", priority=1),
        ]
    )
    assert fs.command == "stock_zh_a_hist"
    assert len(fs.real_sources) == 2
    assert fs.real_sources[0].name == "eastmoney"
    assert fs.real_sources[0].priority == 0
    assert fs.real_sources[1].name == "tencent"
    assert fs.real_sources[1].priority == 1


def test_manifest_with_real_sources(tmp_path):
    """Test manifest with real_sources validates."""
    f = tmp_path / "m.yaml"
    f.write_text("""
name: test
label: Test
functions:
  - command: get_data
    columns:
      - {name: value}
    real_sources:
      - name: eastmoney
        priority: 0
      - name: tencent
        priority: 1
""")
    m = load_catalog(str(f))
    assert m.functions[0].real_sources is not None
    assert len(m.functions[0].real_sources) == 2
    assert m.functions[0].real_sources[0].name == "eastmoney"
    assert m.functions[0].real_sources[1].name == "tencent"


def test_example_stock_has_real_sources():
    """Test example_stock.yaml has real_sources declared."""
    m = load_catalog(str(EXAMPLES / "example_stock.yaml"))
    assert m.functions[0].real_sources is not None
    assert len(m.functions[0].real_sources) == 2
    assert m.functions[0].real_sources[0].name == "yahoo_finance"
    assert m.functions[0].real_sources[1].name == "alpha_vantage"
