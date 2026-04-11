"""schema_validator.py — Tier-1 JSON Schema subset validator.

Supports ONLY the following keywords (ADR-006 Tier-1 contract):
    type, required, enum, pattern, properties, additionalProperties,
    minLength, maxLength, $schema

Explicitly REJECTS at schema-load time (schema_tier_exceeded):
    $ref, allOf, oneOf, anyOf, not, format, if, then, else,
    definitions, $defs

Returns structured errors naming the first failing dotted field path.
Budget: <= 1s per validation call.
Pure function: no I/O, no side effects.
< 200 LoC (excluding docstrings and blank lines).
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SchemaTierExceeded(Exception):
    """Raised at schema-load time when a Tier-1-exceeding keyword is used."""

    def __init__(self, keyword: str, path: str = "$") -> None:
        self.keyword = keyword
        self.path = path
        super().__init__(f"schema_tier_exceeded: keyword '{keyword}' at '{path}' is not in Tier-1 subset")


class SchemaViolation(Exception):
    """Raised when a value fails schema validation."""

    def __init__(self, message: str, field_path: str = "$") -> None:
        self.field_path = field_path
        super().__init__(f"schema_violation at '{field_path}': {message}")


# ---------------------------------------------------------------------------
# Forbidden keywords (Tier-1 rejection list)
# ---------------------------------------------------------------------------

_FORBIDDEN_KEYWORDS = frozenset({
    "$ref", "allOf", "oneOf", "anyOf", "not",
    "format", "if", "then", "else",
    "definitions", "$defs",
})

_ALLOWED_KEYWORDS = frozenset({
    "$schema", "title", "description", "type", "required",
    "enum", "pattern", "properties", "additionalProperties",
    "minLength", "maxLength",
    # structural metadata (not enforced but not forbidden)
    "items",
})

# ---------------------------------------------------------------------------
# Schema loading + Tier-1 check
# ---------------------------------------------------------------------------


def _check_tier(schema: Any, path: str = "$") -> None:
    """Walk schema dict and raise SchemaTierExceeded on any forbidden keyword."""
    if not isinstance(schema, dict):
        return
    for key in schema:
        if key in _FORBIDDEN_KEYWORDS:
            raise SchemaTierExceeded(key, path)
    for key, value in schema.items():
        subpath = f"{path}.{key}"
        if isinstance(value, dict):
            _check_tier(value, subpath)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                _check_tier(item, f"{subpath}[{i}]")


def load_schema(schema: dict) -> dict:
    """Load and validate a schema dict for Tier-1 compliance.

    Returns the schema unchanged on success.
    Raises SchemaTierExceeded if any forbidden keyword is present.
    """
    if not isinstance(schema, dict):
        raise SchemaViolation("schema must be a dict", "$")
    _check_tier(schema, "$")
    return schema


# ---------------------------------------------------------------------------
# Type validation
# ---------------------------------------------------------------------------

_TYPE_CHECKS: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _check_type(value: Any, expected: str | list, path: str) -> None:
    if isinstance(expected, list):
        for t in expected:
            try:
                _check_type(value, t, path)
                return
            except SchemaViolation:
                pass
        raise SchemaViolation(f"expected one of types {expected}, got {type(value).__name__}", path)

    if expected == "integer" and isinstance(value, bool):
        raise SchemaViolation(f"expected integer, got bool (bool is not integer in Tier-1)", path)
    if expected == "number" and isinstance(value, bool):
        raise SchemaViolation(f"expected number, got bool", path)

    check = _TYPE_CHECKS.get(expected)
    if check is None:
        raise SchemaViolation(f"unknown type '{expected}'", path)
    if not isinstance(value, check):
        raise SchemaViolation(f"expected {expected}, got {type(value).__name__}", path)


# ---------------------------------------------------------------------------
# Core validator
# ---------------------------------------------------------------------------


def _validate_node(value: Any, schema: dict, path: str, strict: bool) -> None:
    """Validate a single value against a schema node. Raises SchemaViolation on first failure."""
    if not isinstance(schema, dict):
        return

    # type check
    if "type" in schema:
        _check_type(value, schema["type"], path)

    # enum check
    if "enum" in schema:
        if value not in schema["enum"]:
            raise SchemaViolation(
                f"value {value!r} not in enum {schema['enum']}", path
            )

    # string-specific checks
    if isinstance(value, str):
        if "pattern" in schema:
            if not re.fullmatch(schema["pattern"], value):
                raise SchemaViolation(
                    f"value {value!r} does not match pattern {schema['pattern']!r}", path
                )
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise SchemaViolation(
                f"string length {len(value)} < minLength {schema['minLength']}", path
            )
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise SchemaViolation(
                f"string length {len(value)} > maxLength {schema['maxLength']}", path
            )

    # object-specific checks
    if isinstance(value, dict):
        if "required" in schema:
            for req_key in schema["required"]:
                if req_key not in value:
                    raise SchemaViolation(f"missing required field '{req_key}'", f"{path}.{req_key}")

        if "properties" in schema:
            for prop_key, prop_schema in schema["properties"].items():
                if prop_key in value:
                    _validate_node(value[prop_key], prop_schema, f"{path}.{prop_key}", strict)

        if "additionalProperties" in schema:
            ap = schema["additionalProperties"]
            if ap is False and strict:
                defined_keys = set(schema.get("properties", {}).keys())
                for key in value:
                    if key not in defined_keys:
                        raise SchemaViolation(
                            f"additional property '{key}' not allowed (additionalProperties: false)", path
                        )
            elif isinstance(ap, dict):
                defined_keys = set(schema.get("properties", {}).keys())
                for key, val in value.items():
                    if key not in defined_keys:
                        _validate_node(val, ap, f"{path}.{key}", strict)

    # array-specific checks
    if isinstance(value, list) and "items" in schema:
        items_schema = schema["items"]
        for i, item in enumerate(value):
            _validate_node(item, items_schema, f"{path}[{i}]", strict)


def validate(
    value: Any,
    schema: dict,
    strict: bool = True,
    path: str = "$",
) -> None:
    """Validate *value* against *schema*.

    Args:
        value:  The data to validate (typically a parsed JSON object).
        schema: A Tier-1 JSON Schema dict (pre-loaded via load_schema).
        strict: If True, reject additional properties when schema says so.
        path:   Root path for error messages (default '$').

    Raises:
        SchemaViolation: on first failing constraint, naming the full dotted path.
        SchemaTierExceeded: if schema contains forbidden Tier-1-exceeding keywords.
    """
    _check_tier(schema, path)
    _validate_node(value, schema, path, strict)
