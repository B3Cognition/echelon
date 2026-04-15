"""T013: Unit test pack — schema_validator.py

Tests per test-strategy § schema validator.
One test per supported keyword positive + negative.
Boundary cases. Strict vs permissive. Round-trip.

Requirement: >= 20 tests pass. All 5 valid + 10 invalid fixtures exercised.
"""

import json
import sys
from pathlib import Path

import pytest

# Make sure the extension root is on the path
EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from kernel.schema_validator import (
    SchemaTierExceeded,
    SchemaViolation,
    load_schema,
    validate,
)

FIXTURES_VALID = EXT_ROOT / "tests" / "fixtures" / "state" / "valid"
FIXTURES_INVALID = EXT_ROOT / "tests" / "fixtures" / "state" / "invalid"


# ---------------------------------------------------------------------------
# load_schema — Tier-1 rejection
# ---------------------------------------------------------------------------


class TestLoadSchema:
    def test_pass_minimal_schema(self):
        schema = {"type": "object", "properties": {}}
        result = load_schema(schema)
        assert result is schema

    def test_reject_ref(self):
        with pytest.raises(SchemaTierExceeded) as exc_info:
            load_schema({"$ref": "#/defs/foo"})
        assert exc_info.value.keyword == "$ref"

    def test_reject_allof(self):
        with pytest.raises(SchemaTierExceeded) as exc_info:
            load_schema({"allOf": [{"type": "string"}]})
        assert exc_info.value.keyword == "allOf"

    def test_reject_oneof(self):
        with pytest.raises(SchemaTierExceeded) as exc_info:
            load_schema({"oneOf": [{"type": "string"}, {"type": "integer"}]})
        assert exc_info.value.keyword == "oneOf"

    def test_reject_anyof(self):
        with pytest.raises(SchemaTierExceeded) as exc_info:
            load_schema({"anyOf": []})
        assert exc_info.value.keyword == "anyOf"

    def test_reject_format(self):
        with pytest.raises(SchemaTierExceeded) as exc_info:
            load_schema({"type": "string", "format": "email"})
        assert exc_info.value.keyword == "format"

    def test_reject_nested_ref(self):
        """$ref nested inside properties should also be caught."""
        with pytest.raises(SchemaTierExceeded):
            load_schema({"properties": {"x": {"$ref": "#/defs/x"}}})


# ---------------------------------------------------------------------------
# type keyword
# ---------------------------------------------------------------------------


class TestTypeKeyword:
    def test_string_pass(self):
        validate("hello", {"type": "string"})

    def test_string_fail(self):
        with pytest.raises(SchemaViolation) as exc_info:
            validate(42, {"type": "string"})
        assert "string" in str(exc_info.value)

    def test_integer_pass(self):
        validate(42, {"type": "integer"})

    def test_integer_fail_on_bool(self):
        with pytest.raises(SchemaViolation):
            validate(True, {"type": "integer"})

    def test_number_pass_int(self):
        validate(3, {"type": "number"})

    def test_number_pass_float(self):
        validate(3.14, {"type": "number"})

    def test_object_pass(self):
        validate({}, {"type": "object"})

    def test_array_pass(self):
        validate([], {"type": "array"})

    def test_boolean_pass(self):
        validate(True, {"type": "boolean"})

    def test_null_pass(self):
        validate(None, {"type": "null"})


# ---------------------------------------------------------------------------
# required keyword
# ---------------------------------------------------------------------------


class TestRequiredKeyword:
    def test_required_present(self):
        schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
        validate({"a": "x"}, schema)

    def test_required_missing(self):
        schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
        with pytest.raises(SchemaViolation) as exc_info:
            validate({}, schema)
        assert "$.a" in exc_info.value.field_path

    def test_multiple_required_one_missing(self):
        schema = {"type": "object", "required": ["a", "b"], "properties": {
            "a": {"type": "string"},
            "b": {"type": "string"},
        }}
        with pytest.raises(SchemaViolation):
            validate({"a": "x"}, schema)


# ---------------------------------------------------------------------------
# enum keyword
# ---------------------------------------------------------------------------


class TestEnumKeyword:
    def test_enum_pass(self):
        validate("a", {"enum": ["a", "b", "c"]})

    def test_enum_fail(self):
        with pytest.raises(SchemaViolation):
            validate("d", {"enum": ["a", "b", "c"]})

    def test_enum_with_none(self):
        validate(None, {"enum": [None, "x"]})


# ---------------------------------------------------------------------------
# pattern keyword
# ---------------------------------------------------------------------------


class TestPatternKeyword:
    def test_pattern_pass(self):
        validate("squad-123", {"type": "string", "pattern": "^squad-[0-9]+$"})

    def test_pattern_fail(self):
        with pytest.raises(SchemaViolation):
            validate("run-123", {"type": "string", "pattern": "^squad-[0-9]+$"})


# ---------------------------------------------------------------------------
# minLength / maxLength keywords
# ---------------------------------------------------------------------------


class TestLengthKeywords:
    def test_min_length_pass(self):
        validate("ab", {"type": "string", "minLength": 2})

    def test_min_length_fail(self):
        with pytest.raises(SchemaViolation):
            validate("a", {"type": "string", "minLength": 2})

    def test_max_length_pass(self):
        validate("abc", {"type": "string", "maxLength": 5})

    def test_max_length_fail(self):
        with pytest.raises(SchemaViolation):
            validate("abcdef", {"type": "string", "maxLength": 5})


# ---------------------------------------------------------------------------
# properties keyword
# ---------------------------------------------------------------------------


class TestPropertiesKeyword:
    def test_properties_nested_type(self):
        schema = {"type": "object", "properties": {"age": {"type": "integer"}}}
        validate({"age": 25}, schema)

    def test_properties_nested_fail(self):
        schema = {"type": "object", "properties": {"age": {"type": "integer"}}}
        with pytest.raises(SchemaViolation) as exc_info:
            validate({"age": "twenty-five"}, schema)
        assert "age" in exc_info.value.field_path


# ---------------------------------------------------------------------------
# additionalProperties keyword
# ---------------------------------------------------------------------------


class TestAdditionalPropertiesKeyword:
    def test_additional_properties_false_strict(self):
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "additionalProperties": False,
        }
        with pytest.raises(SchemaViolation):
            validate({"a": "x", "extra": "y"}, schema, strict=True)

    def test_additional_properties_false_not_strict(self):
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "additionalProperties": False,
        }
        # Non-strict mode should not fail
        validate({"a": "x", "extra": "y"}, schema, strict=False)

    def test_additional_properties_schema(self):
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "additionalProperties": {"type": "integer"},
        }
        validate({"a": "x", "b": 42}, schema)

    def test_additional_properties_schema_fail(self):
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "additionalProperties": {"type": "integer"},
        }
        with pytest.raises(SchemaViolation):
            validate({"a": "x", "b": "not-an-int"}, schema)


# ---------------------------------------------------------------------------
# Boundary cases
# ---------------------------------------------------------------------------


class TestBoundary:
    def test_empty_object_passes_no_required(self):
        validate({}, {"type": "object"})

    def test_deeply_nested(self):
        schema = {
            "type": "object",
            "properties": {
                "a": {
                    "type": "object",
                    "properties": {
                        "b": {
                            "type": "object",
                            "properties": {
                                "c": {"type": "string"}
                            }
                        }
                    }
                }
            }
        }
        validate({"a": {"b": {"c": "deep"}}}, schema)

    def test_error_path_for_nested_required(self):
        schema = {
            "type": "object",
            "properties": {
                "dispatch": {
                    "type": "object",
                    "required": ["agent"],
                    "properties": {"agent": {"type": "string"}}
                }
            }
        }
        with pytest.raises(SchemaViolation) as exc_info:
            validate({"dispatch": {}}, schema)
        assert "agent" in exc_info.value.field_path


# ---------------------------------------------------------------------------
# Fixture-based tests (5 valid + 10 invalid)
# ---------------------------------------------------------------------------


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _get_minimal_schema() -> dict:
    """Return a minimal but sufficient schema for the state fixtures."""
    return {
        "type": "object",
        "required": [
            "run_id", "phase", "mode", "meta_run", "iteration",
            "degraded_mode_stack", "issues_log", "dependency_checks",
            "last_dispatch", "dispatch_counters", "defer_count",
            "autonomy_mode", "updated_at",
        ],
        "additionalProperties": True,
        "properties": {
            "run_id": {"type": "string"},
            "phase": {"type": "string"},
            "mode": {"type": "string", "enum": ["greenfield", "brownfield", "self_analysis"]},
            "meta_run": {"type": "boolean"},
            "iteration": {"type": "integer"},
            "defer_count": {"type": "integer"},
            "autonomy_mode": {"type": "string", "enum": ["guided", "semi", "banzai"]},
            "updated_at": {"type": "string"},
            "degraded_mode_stack": {"type": "array"},
            "issues_log": {"type": "array"},
            "dependency_checks": {"type": "object"},
            "last_dispatch": {"type": "object"},
            "dispatch_counters": {"type": "object"},
        },
    }


@pytest.mark.parametrize("fixture_file", sorted((FIXTURES_VALID).glob("*.json")))
def test_valid_fixture_passes(fixture_file: Path):
    """Each valid fixture must pass schema validation."""
    data = _load_fixture(fixture_file)
    if not isinstance(data, dict):
        pytest.skip(f"{fixture_file.name} is not an object — skip")
    schema = _get_minimal_schema()
    validate(data, schema)  # should not raise


@pytest.mark.parametrize("fixture_file", sorted((FIXTURES_INVALID).glob("*.json")))
def test_invalid_fixture_fails(fixture_file: Path):
    """Each invalid fixture must fail schema validation."""
    data = _load_fixture(fixture_file)
    schema = _get_minimal_schema()

    if not isinstance(data, dict):
        # Non-dict data should fail type check
        with pytest.raises(SchemaViolation):
            validate(data, schema)
        return

    with pytest.raises(SchemaViolation):
        validate(data, schema)
