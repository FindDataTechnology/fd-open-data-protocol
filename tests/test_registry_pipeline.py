"""End-to-end registry pipeline tests on the in-memory store.

Covers the spec scenarios: idempotent re-registration (no duplicates,
unchanged counts), incremental re-runs (only new rows counted), the naming
gate keeping incomplete entries out of verified-only exports, coverage with
asset denominators and phase-2 visibility, and the shipped mini example
running from the template path alone (no database).
"""
import json
from pathlib import Path

import pytest

from fd_open_data_protocol.registry import (
    coverage_report,
    load_adapter,
    map_rows,
    read_rows_csv,
)
from fd_open_data_protocol.registry_cli import main as cli_main
from fd_open_data_protocol.registry_store import MemoryRegistryStore

REPO = Path(__file__).resolve().parents[1]


def _adapter_dict(**overrides) -> dict:
    base = dict(
        source_db="test_db",
        source_table="indicator",
        native_code_column="code",
        fields={
            "semantic_code": {"from": "column", "value": "code"},
            "name_en": {"from": "column", "value": "name_en"},
            "name_zh": {"from": "column", "value": "name_zh"},
            "domain": {"from": "literal", "value": "macro"},
        },
        provenance_columns=["topic"],
    )
    base.update(overrides)
    return base


def _rows(n: int = 3) -> list[dict]:
    return [
        {"code": f"IND.{i}", "name_en": f"Indicator {i}", "name_zh": f"指标{i}", "topic": f"t{i}"}
        for i in range(1, n + 1)
    ]


# --- idempotency and increment ------------------------------------------------

def test_rerun_is_idempotent_counts_unchanged():
    store = MemoryRegistryStore()
    entries = map_rows(load_adapter(_adapter_dict()), _rows(3))
    first = store.upsert_entries(entries)
    assert (first.new, first.updated, first.unchanged) == (3, 0, 0)
    assert len(store.rows) == 3

    second = store.upsert_entries(entries)
    assert (second.new, second.updated, second.unchanged) == (0, 0, 3)
    assert len(store.rows) == 3  # no duplicates


def test_in_batch_duplicate_anchor_counts_once():
    store = MemoryRegistryStore()
    adapter = load_adapter(_adapter_dict())
    rows = [
        {"code": "DUP", "name_en": "First", "name_zh": "甲"},
        {"code": "DUP", "name_en": "Second", "name_zh": "乙"},  # same anchor
    ]
    stats = store.upsert_entries(map_rows(adapter, rows))
    assert stats.new == 1  # one anchor, not two
    assert len(store.rows) == 1
    assert next(iter(store.rows.values())).name_en == "Second"  # last wins


def test_incremental_rerun_counts_only_new_rows():
    store = MemoryRegistryStore()
    adapter = load_adapter(_adapter_dict())
    store.upsert_entries(map_rows(adapter, _rows(3)))

    grown = _rows(3) + [
        {"code": "IND.4", "name_en": "Indicator 4", "name_zh": "指标4", "topic": "t4"}
    ]
    stats = store.upsert_entries(map_rows(adapter, grown))
    assert (stats.new, stats.updated, stats.unchanged) == (1, 0, 3)
    assert len(store.rows) == 4


def test_naming_drift_demotes_verified_entry():
    store = MemoryRegistryStore()
    adapter = load_adapter(_adapter_dict())
    rows = _rows(1)
    store.upsert_entries(map_rows(adapter, rows))
    assert store.set_verified() == 1
    assert store.set_verified() == 0  # already verified; no double count

    changed = [dict(rows[0], name_en="Indicator 1 (revised)")]
    stats = store.upsert_entries(map_rows(adapter, changed))
    assert stats.demoted == 1
    entry = next(iter(store.rows.values()))
    assert entry.verified is False  # naming change requires re-verification


# --- naming gate vs verification ---------------------------------------------

def test_verify_refuses_gate_failures_and_export_excludes_unverified():
    store = MemoryRegistryStore()
    adapter = load_adapter(
        _adapter_dict(fields={"name_en": {"from": "column", "value": "missing_col"}})
    )
    store.upsert_entries(map_rows(adapter, _rows(2)))
    assert store.set_verified() == 0  # gate fails (no name_en) -> stays unverified

    exported = list(store.iter_entries(verified_only=True))
    assert exported == []  # unverified MUST NOT surface on public catalog faces
    assert len(list(store.iter_entries())) == 2  # but stays auditable in the registry


# --- adapter mapping ----------------------------------------------------------

def test_map_file_enriches_names(tmp_path: Path):
    mapping = tmp_path / "names.json"
    mapping.write_text(json.dumps({"IND.1": "指标一（官方）"}), encoding="utf-8")
    adapter = load_adapter(
        _adapter_dict(
            fields={
                "semantic_code": {"from": "column", "value": "code"},
                "name_en": {"from": "column", "value": "name_en"},
                "name_zh": {"from": "map_file", "value": "names.json"},
            }
        )
    )
    adapter._base_dir = tmp_path
    entries = map_rows(adapter, _rows(1))
    assert entries[0].name_zh == "指标一（官方）"


def test_in_batch_semantic_code_collision_suffixed_and_flagged():
    adapter = load_adapter(
        _adapter_dict(fields={
            "semantic_code": {"from": "column", "value": "slug"},
            "name_en": {"from": "column", "value": "name_en"},
            "name_zh": {"from": "column", "value": "name_zh"},
        })
    )
    # two distinct native codes whose mapped slugs collide
    rows = [
        {"code": "A1", "slug": "DUP.CODE", "name_en": "A", "name_zh": "甲"},
        {"code": "B2", "slug": "DUP.CODE", "name_en": "B", "name_zh": "乙"},
    ]
    entries = map_rows(adapter, rows)
    assert entries[0].semantic_code == "DUP.CODE"
    assert entries[1].semantic_code == "DUP.CODE-2"
    assert entries[1].provenance.get("needs_review") is True
    assert not (entries[0].provenance or {}).get("needs_review")


def test_unknown_adapter_field_rejected():
    with pytest.raises(Exception):
        load_adapter(_adapter_dict(fields={"bogus": {"from": "literal", "value": "x"}}))


# --- coverage ------------------------------------------------------------------

def test_coverage_asset_denominator_and_phase2_visibility():
    store = MemoryRegistryStore()
    store.upsert_entries(map_rows(load_adapter(_adapter_dict()), _rows(3)))
    store.set_verified()

    report = coverage_report(store, actual_counts={"test_db": 6})
    by_db = {s["source_db"]: s for s in report["sources"]}
    assert by_db["test_db"]["registered"] == 3
    assert by_db["test_db"]["actual_in_source"] == 6
    assert by_db["test_db"]["coverage"] == 0.5
    # phase-2 sources must appear explicitly, not vanish
    assert by_db["ia35"]["phase"] == 2 and by_db["ia35"]["registered"] == 0
    assert by_db["wenshu_db"]["phase"] == 2 and by_db["wenshu_db"]["registered"] == 0


def test_unmapped_by_module_audit():
    store = MemoryRegistryStore()
    store.upsert_entries(map_rows(load_adapter(_adapter_dict()), _rows(2)))
    module_map = {"macro": {"source_dbs": ["world_bank"]}}
    report = coverage_report(store, module_map=module_map)
    assert report["unmapped_count"] == 2  # test_db is covered by no module rule
    assert report["unmapped_sample"][0]["native_code"] == "IND.1"


# --- shipped mini example: template copy runs the full pipeline ---------------

def test_mini_example_full_pipeline_dry_run(tmp_path: Path, capsys):
    adapter_path = REPO / "examples" / "registry_mini" / "adapter.yaml"
    rows_path = REPO / "examples" / "registry_mini" / "mini_source.csv"
    rc = cli_main([
        "register", "--dry-run",
        "--adapter", str(adapter_path),
        "--rows", str(rows_path),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "source_rows=3" in out
    assert '"new": 3' in out

    # CSV rows load cleanly and gate statuses come out as expected
    rows = read_rows_csv(rows_path)
    entries = map_rows(load_adapter(adapter_path), rows)
    verified_eligible = [e for e in entries if e.semantic_code and e.name_zh and e.name_en]
    assert len(entries) == 3 and len(verified_eligible) == 2  # one row lacks name_en
