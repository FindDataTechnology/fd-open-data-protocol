"""Tests for the file-sourced entity-type registry and the ConceptHint family ref."""
import pytest
from pydantic import ValidationError

from fd_open_data_protocol.loader import load_catalog
from fd_open_data_protocol.schema import (
    ConceptHint,
    Entity,
    EntityRelationship,
    set_entity_type_vocabulary,
)

LEGACY_ENTITY_TYPES = (
    "country", "city", "stock", "fund", "bond", "index", "future", "crypto",
    "organization", "industry", "exchange", "company", "commodity", "person",
)


# --- entity-type registry is file-sourced ------------------------------------

def test_legacy_entity_types_still_valid():
    """Existing manifests using the previous hardcoded vocabulary stay valid."""
    for entity_type in LEGACY_ENTITY_TYPES:
        assert Entity(entity_type=entity_type, code="X").entity_type == entity_type


def test_unknown_entity_type_rejected():
    with pytest.raises(ValidationError):
        Entity(entity_type="widget", code="W1")


def test_relationship_target_uses_file_registry():
    with pytest.raises(ValidationError):
        EntityRelationship(target_entity_type="widget", target_code="W1", relation_type="belongs_to")
    rel = EntityRelationship(target_entity_type="industry", target_code="gics_10", relation_type="belongs_to")
    assert rel.target_code == "gics_10"


def test_set_entity_type_vocabulary_escape_hatch():
    set_entity_type_vocabulary(["widget"])
    try:
        assert Entity(entity_type="widget", code="W1").entity_type == "widget"
        with pytest.raises(ValidationError):
            Entity(entity_type="country", code="CN")
    finally:
        set_entity_type_vocabulary()  # reset to file-sourced

    assert Entity(entity_type="country", code="CN").entity_type == "country"


# --- ConceptHint concept-family reference ------------------------------------

def test_concept_hint_family_reference_preserved():
    hint = ConceptHint(column="c", concept="gdp", entity_type="country", concept_family="GDP")
    assert hint.concept_family == "GDP"


def test_concept_hint_unknown_family_rejected():
    with pytest.raises(ValidationError) as excinfo:
        ConceptHint(column="c", concept="x", entity_type="country", concept_family="NotAFamily")
    assert "NotAFamily" in str(excinfo.value)


def test_concept_hint_omitted_family_behaves_as_before():
    hint = ConceptHint(
        column="close", concept="price.close", entity_type="stock",
        unit="currency", frequency="daily",
    )
    assert hint.concept_family is None

    dumped = hint.model_dump()
    dumped.pop("concept_family")  # the only field this change adds
    assert dumped == {
        "column": "close", "concept": "price.close", "entity_type": "stock",
        "measure": None, "unit": "currency", "frequency": "daily", "confidence": 0.9,
    }


def test_manifest_with_family_reference_loads():
    manifest = load_catalog({
        "name": "s", "label": "S",
        "functions": [{"command": "f", "columns": [{"name": "pop"}]}],
        "concepts": [{"column": "pop", "concept": "population.total",
                      "entity_type": "country", "concept_family": "Population"}],
    })
    assert manifest.concepts[0].concept_family == "Population"
