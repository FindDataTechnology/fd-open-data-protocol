"""Tests for the registry entry model and the naming quality gate."""
import pytest
from pydantic import ValidationError

from fd_open_data_protocol.schema import (
    NAMING_GATE_FIELDS,
    RegistryEntry,
    naming_gate_passed,
)


def _entry(**overrides) -> RegistryEntry:
    base = dict(
        source_db="world_bank",
        source_table="indicator",
        source_column="indicator_code",
        native_code="NY.GDP.MKTP.CD",
        semantic_code="NY.GDP.MKTP.CD",
        name_zh="GDP（现价美元）",
        name_en="GDP (current US$)",
    )
    base.update(overrides)
    return RegistryEntry(**base)


# --- anchor identity ---------------------------------------------------------

def test_anchor_fields_required():
    with pytest.raises(ValidationError):
        RegistryEntry(source_db="", source_table="indicator", native_code="X")
    with pytest.raises(ValidationError):
        RegistryEntry(source_db="wb", source_table=" ", native_code="X")
    with pytest.raises(ValidationError):
        RegistryEntry(source_db="wb", source_table="indicator", native_code="")


def test_source_column_defaults_to_empty_and_is_trimmed():
    e = _entry(source_column=None)
    assert e.source_column == ""
    assert e.anchor() == ("world_bank", "indicator", "", "NY.GDP.MKTP.CD")


# --- semantic_code shape -----------------------------------------------------

def test_semantic_code_accepts_known_shapes():
    for code in ("price.open", "NY.GDP.MKTP.CD", "CPI_YOY", "city-resident-power", "a1"):
        assert _entry(semantic_code=code).semantic_code == code


def test_semantic_code_rejects_unreadable_shapes():
    for bad in ("23072", "1GDP", "has space", "带中文"):
        with pytest.raises(ValidationError):
            _entry(semantic_code=bad)


def test_semantic_code_blank_becomes_none():
    assert _entry(semantic_code="   ").semantic_code is None


# --- naming gate -------------------------------------------------------------

def test_gate_fields_are_exactly_the_naming_layer():
    assert NAMING_GATE_FIELDS == ("semantic_code", "name_zh", "name_en")


def test_gate_fails_on_any_missing_naming_element():
    complete = _entry()
    assert naming_gate_passed(complete)
    for field in NAMING_GATE_FIELDS:
        assert not naming_gate_passed(_entry(**{field: None}))


def test_metadata_fields_do_not_gate():
    # unit/frequency/domain unknown (None) does not block the gate
    assert naming_gate_passed(_entry(unit=None, frequency=None, domain=None))


def test_verified_entry_cannot_fail_the_gate():
    with pytest.raises(ValidationError, match="naming gate"):
        _entry(verified=True, name_en=None)


def test_unverified_with_complete_naming_is_allowed():
    # gate passes but no verification record yet -> stored unverified, auditable
    e = _entry(verified=False)
    assert naming_gate_passed(e) and e.verified is False


def test_names_are_trimmed():
    e = _entry(name_zh="  GDP  ", name_en=" GDP ")
    assert (e.name_zh, e.name_en) == ("GDP", "GDP")
