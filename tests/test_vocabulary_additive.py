"""The additive-release rule, applied to this library's YAML vocabulary.

A vocabulary release may add entries and retire them with ``superseded_by``, but
it may not delete one or change an id: a deletion silently orphans every manifest,
variable and downstream query that used the value, and there is no way back
because the old meaning is gone.

The rule itself lives in the shared ontology kernel; these tests prove this
library actually applies it, and that the URI construction agrees with the kernel
byte for byte.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from fd_open_data_protocol.vocabulary import (
    SCHEMA_BASE_URI,
    VocabularyError,
    assert_additive,
    build_uri,
    default_vocabulary_dir,
    load_vocabulary,
)


@pytest.fixture()
def releases(tmp_path: Path) -> tuple[Path, Path]:
    """Two copies of the shipped vocabulary: baseline and the next release."""
    baseline = tmp_path / "baseline"
    current = tmp_path / "current"
    shutil.copytree(default_vocabulary_dir(), baseline)
    shutil.copytree(default_vocabulary_dir(), current)
    return baseline, current


def _edit(path: Path, mutate) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")


def _bump_release(directory: Path, suffix: str = "+next") -> None:
    """Every file in a release carries the same version; bump them together."""
    for path in sorted(directory.glob("*.yaml")) + sorted((directory / "crosswalks").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["version"] = str(data["version"]) + suffix
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")


def test_an_unchanged_release_is_additive(releases) -> None:
    baseline, current = releases
    load_vocabulary(current, baseline=baseline)  # must not raise
    assert_additive(current, baseline)


def test_removing_an_entry_fails_and_names_it(releases) -> None:
    baseline, current = releases
    entity_types = current / "entity_types.yaml"

    def drop_first(data):
        removed = data["entries"].pop(0)["id"]
        data["_dropped"] = removed  # carried only for the assertion below

    _edit(entity_types, drop_first)
    _bump_release(current)
    dropped = yaml.safe_load(entity_types.read_text(encoding="utf-8"))["_dropped"]

    with pytest.raises(VocabularyError) as caught:
        load_vocabulary(current, baseline=baseline)
    message = str(caught.value)
    assert "not additive" in message
    assert dropped in message


def test_renaming_an_id_is_a_removal(releases) -> None:
    baseline, current = releases
    entity_types = current / "entity_types.yaml"

    def rename_first(data):
        data["entries"][0]["id"] = "renamed-by-accident"

    _edit(entity_types, rename_first)
    _bump_release(current)
    original = yaml.safe_load((baseline / "entity_types.yaml").read_text(encoding="utf-8"))["entries"][0]["id"]

    with pytest.raises(VocabularyError) as caught:
        load_vocabulary(current, baseline=baseline)
    assert original in str(caught.value)


def test_adding_an_entry_is_accepted(releases) -> None:
    baseline, current = releases
    entity_types = current / "entity_types.yaml"

    def add_one(data):
        data["entries"].append({
            "id": "test-only-type",
            "label_en": "Test Only Type",
            "label_zh": "仅测试类型",
            "description": "Added by the additive-release test.",
        })

    _edit(entity_types, add_one)
    _bump_release(current)
    registry = load_vocabulary(current, baseline=baseline)
    assert "test-only-type" in registry.ids("entity-type")


def test_retiring_with_a_successor_is_accepted(releases) -> None:
    baseline, current = releases
    entity_types = current / "entity_types.yaml"

    def retire_first(data):
        data["entries"][0]["superseded_by"] = data["entries"][1]["id"]

    _edit(entity_types, retire_first)
    _bump_release(current)
    registry = load_vocabulary(current, baseline=baseline)
    retired = registry.get("entity-type", yaml.safe_load(
        (baseline / "entity_types.yaml").read_text(encoding="utf-8"))["entries"][0]["id"])
    assert retired is not None and retired.deprecated


def test_first_release_needs_no_baseline() -> None:
    registry = load_vocabulary()  # the shipped release, no comparison
    assert registry.version


def test_uri_construction_matches_the_kernel() -> None:
    kernel = pytest.importorskip("fd_ontology_kernel.vocab")
    assert build_uri("unit", "usd") == kernel.uri_for("unit", "usd")
    assert build_uri("concept", "GDP") == f"{SCHEMA_BASE_URI}/concept/GDP"


# --- the CI entry point ------------------------------------------------------
#
# scripts/check_vocabulary_additive.py is what CI actually runs, so its verdicts
# are tested here too: a gate whose "red" has never been observed is not a gate.

def _ci_gate():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "check_vocabulary_additive.py"
    spec = importlib.util.spec_from_file_location("check_vocabulary_additive", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_ci_gate_passes_on_the_shipped_vocabulary(releases, capsys) -> None:
    baseline, _current = releases
    code = _ci_gate().main(["--baseline", str(baseline)])
    assert code == 0
    assert "PASS" in capsys.readouterr().out


def test_ci_gate_fails_and_names_the_dropped_entry(releases, capsys) -> None:
    baseline, current = releases
    units = current / "units.yaml"

    def drop_one(data):
        data["_dropped"] = data["entries"].pop(0)["id"]

    _edit(units, drop_one)
    dropped = yaml.safe_load(units.read_text(encoding="utf-8"))["_dropped"]

    code = _ci_gate().main(["--baseline", str(baseline), "--vocabulary", str(current)])
    out = capsys.readouterr().out
    assert code == 1, out
    assert "只增不减" in out and dropped in out


def test_ci_gate_cannot_run_without_a_usable_baseline(tmp_path: Path) -> None:
    """Exit 2, not 1: 'never compared' must not look like 'is not additive'."""
    code = _ci_gate().main(["--baseline", str(tmp_path / "no-such-release")])
    assert code == 2
