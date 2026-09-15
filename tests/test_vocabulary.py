"""Tests for the versioned semantic vocabulary: loader + structural validator."""
import shutil
from pathlib import Path

import pytest
import yaml

from fd_open_data_protocol.vocabulary import (
    RELATION_TYPES,
    VocabularyError,
    build_uri,
    load_vocabulary,
    validate_vocabulary,
)

SHIPPED = Path(__file__).resolve().parents[1] / "fd_open_data_protocol" / "vocabulary"

# The entity-type set that predates the vocabulary (hardcoded tuple in schema.py).
LEGACY_ENTITY_TYPES = (
    "country", "city", "stock", "fund", "bond", "index", "future", "crypto",
    "organization", "industry", "exchange", "company", "commodity", "person",
)


@pytest.fixture
def vocab_dir(tmp_path):
    """A mutable copy of the shipped vocabulary directory."""
    d = tmp_path / "vocabulary"
    shutil.copytree(SHIPPED, d)
    return d


def _rewrite(path: Path, mutate) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


# --- loading -----------------------------------------------------------------

def test_load_shipped_vocabulary():
    v = load_vocabulary()
    assert v.version.strip()
    assert v.kind("entity-type")
    assert v.concept_families()
    assert v.kind("qualifier")
    assert v.kind("unit")
    assert v.kind("relation-type")
    assert v.kind("event-type") == []  # valid, deliberately empty this release


def test_entity_types_cover_legacy_vocabulary():
    assert set(LEGACY_ENTITY_TYPES) <= set(load_vocabulary().entity_type_ids())


def test_load_from_explicit_directory(vocab_dir):
    """An explicit dir is loaded instead of the shipped defaults."""
    _rewrite(vocab_dir / "qualifiers.yaml",
             lambda d: d["entries"].append({"id": "seasonally_adjusted",
                                            "label_en": "Seasonally Adjusted",
                                            "label_zh": "季调"}))

    assert "seasonally_adjusted" in load_vocabulary(vocab_dir).ids("qualifier")
    assert "seasonally_adjusted" not in load_vocabulary().ids("qualifier")


def test_missing_file_rejected(vocab_dir):
    (vocab_dir / "units.yaml").unlink()
    errs = validate_vocabulary(vocab_dir)
    assert any("units.yaml" in e and "missing vocabulary file" in e for e in errs)
    with pytest.raises(VocabularyError):
        load_vocabulary(vocab_dir)


# --- structural validation ---------------------------------------------------

def test_missing_required_field_rejected(vocab_dir):
    _rewrite(vocab_dir / "concepts.yaml", lambda d: d["entries"][0].pop("id"))
    errs = validate_vocabulary(vocab_dir)
    assert any("concepts.yaml" in e and "'id'" in e for e in errs)


def test_missing_label_rejected(vocab_dir):
    _rewrite(vocab_dir / "entity_types.yaml", lambda d: d["entries"][0].pop("label_zh"))
    errs = validate_vocabulary(vocab_dir)
    assert any("entity_types.yaml" in e and "'label_zh'" in e for e in errs)


def test_duplicate_id_rejected(vocab_dir):
    def dup(d):
        d["entries"][1]["id"] = d["entries"][0]["id"]
    _rewrite(vocab_dir / "units.yaml", dup)
    errs = validate_vocabulary(vocab_dir)
    assert any("duplicate id" in e for e in errs)
    assert any("units.yaml" in e for e in errs)


def test_version_disagreement_rejected(vocab_dir):
    _rewrite(vocab_dir / "units.yaml", lambda d: d.update(version="1999.01"))
    errs = validate_vocabulary(vocab_dir)
    assert any("disagrees" in e and "units.yaml" in e for e in errs)


def test_missing_version_rejected(vocab_dir):
    _rewrite(vocab_dir / "qualifiers.yaml", lambda d: d.pop("version"))
    errs = validate_vocabulary(vocab_dir)
    assert any("qualifiers.yaml" in e and "'version'" in e for e in errs)


def test_bad_iso4217_rejected(vocab_dir):
    def bad(d):
        d["entries"][1]["iso4217"] = "us$"
    _rewrite(vocab_dir / "units.yaml", bad)
    errs = validate_vocabulary(vocab_dir)
    assert any("iso4217" in e for e in errs)


def test_invalid_relation_rejected(vocab_dir):
    def bad(d):
        d["mappings"][0]["relation"] = "equivalent_to"
    _rewrite(vocab_dir / "crosswalks" / "datacommons-worldbank.yaml", bad)
    errs = validate_vocabulary(vocab_dir)
    assert any("unknown relation" in e for e in errs)


def test_out_of_range_confidence_rejected(vocab_dir):
    def bad(d):
        d["mappings"][0]["confidence"] = 1.5
    _rewrite(vocab_dir / "crosswalks" / "datacommons-worldbank.yaml", bad)
    errs = validate_vocabulary(vocab_dir)
    assert any("confidence" in e for e in errs)


# --- URIs and deprecation ----------------------------------------------------

def test_uri_construction():
    v = load_vocabulary()
    assert v.get("concept", "GDP").uri == "https://schema.finddata.tech/concept/GDP"
    assert v.get("entity-type", "country").uri == "https://schema.finddata.tech/entity-type/country"
    assert build_uri("unit", "usd") == "https://schema.finddata.tech/unit/usd"
    for kind in ("concept", "entity-type", "qualifier", "unit", "relation-type"):
        for entry in v.kind(kind):
            assert entry.uri == f"https://schema.finddata.tech/{kind}/{entry.id}"


def test_deprecation_without_deletion(vocab_dir):
    """A retired entry stays, marked deprecated, pointing at its successor."""

    def retire(d):
        gdp = next(e for e in d["entries"] if e["id"] == "GDP")
        gdp["superseded_by"] = "Population"

    _rewrite(vocab_dir / "concepts.yaml", retire)
    v = load_vocabulary(vocab_dir)

    retired = v.get("concept", "GDP")
    assert retired is not None
    assert retired.deprecated and retired.superseded_by == "Population"
    assert v.get("concept", "Population") is not None  # successor still resolves


def test_unknown_superseded_by_rejected(vocab_dir):
    def bad(d):
        d["entries"][0]["superseded_by"] = "NoSuchEntry"
    _rewrite(vocab_dir / "concepts.yaml", bad)
    errs = validate_vocabulary(vocab_dir)
    assert any("superseded_by" in e and "NoSuchEntry" in e for e in errs)


# --- crosswalk seed content --------------------------------------------------

def test_flagship_crosswalks_present():
    """Population and GDP crosswalk assertions ship and are ingestible."""
    v = load_vocabulary()
    pairs = {(m["vocabulary"], m["term"]) for m in v.mappings}
    assert ("datacommons", "Count_Person") in pairs
    assert ("worldbank", "SP.POP.TOTL") in pairs
    assert ("worldbank", "NY.GDP.MKTP.CD") in pairs
    assert {m["relation"] for m in v.mappings} <= set(RELATION_TYPES)


def test_seeded_variables_carry_family():
    v = load_vocabulary()
    by_code = {(s.code, s.measure): s for s in v.seeded_variables()}
    assert by_code[("gdp", "nominal_current")].family_id == "GDP"
    assert by_code[("population.total", "")].family_id == "Population"
