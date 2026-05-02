"""state_loader.py — Load and validate state.json.

Loads state.json from disk, passes through schema_validator.validate,
returns typed dict on success or structured error on failure.

Budget: <= 1s on 20-field fixture.
Blocks dispatch on validation failure (FR-STATE-001).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Union

from kernel.schema_validator import (
    SchemaViolation,
    SchemaTierExceeded,
    load_schema,
    validate,
)


# ---------------------------------------------------------------------------
# Structured error type
# ---------------------------------------------------------------------------


class StateLoadError:
    """Structured error returned when state.json fails to load or validate."""

    def __init__(
        self,
        code: str,
        message: str,
        field_path: str = "$",
        detail: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.field_path = field_path
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "error_code": self.code,
            "message": self.message,
            "field_path": self.field_path,
        }
        if self.detail:
            result["detail"] = self.detail
        return result

    def __repr__(self) -> str:
        return f"StateLoadError(code={self.code!r}, field={self.field_path!r}, msg={self.message!r})"


# ---------------------------------------------------------------------------
# Default Tier-1 schema (lazy-loaded from state-schema.json if available)
# ---------------------------------------------------------------------------

_DEFAULT_SCHEMA: dict | None = None


def _get_default_schema() -> dict:
    """Load the default Tier-1 schema from state-schema.json, or return a minimal inline schema."""
    global _DEFAULT_SCHEMA
    if _DEFAULT_SCHEMA is not None:
        return _DEFAULT_SCHEMA

    # Try to load from the canonical path relative to this module
    module_dir = Path(__file__).resolve().parent
    schema_path = module_dir.parent / "state-schema.json"
    if schema_path.exists():
        try:
            raw = json.loads(schema_path.read_text(encoding="utf-8"))
            _DEFAULT_SCHEMA = load_schema(raw)
            return _DEFAULT_SCHEMA
        except Exception:
            pass  # fall through to inline

    # Minimal inline fallback schema (T001 required fields only)
    _DEFAULT_SCHEMA = {
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
    return _DEFAULT_SCHEMA


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load(
    state_path: str | Path,
    schema: dict | None = None,
    strict: bool = True,
) -> Union[dict[str, Any], StateLoadError]:
    """Load and validate state.json.

    Args:
        state_path: Path to state.json.
        schema:     Optional pre-loaded Tier-1 schema dict.
                    Defaults to the canonical state-schema.json.
        strict:     If True, reject undeclared additional properties
                    where schema says additionalProperties: false.

    Returns:
        dict on success (the parsed + validated state).
        StateLoadError on any failure (file not found, JSON error, schema violation).

    Time budget: <= 1s (FR-STATE-001).
    """
    t_start = time.monotonic()

    path = Path(state_path)

    # --- File existence ---
    if not path.exists():
        return StateLoadError(
            code="file_not_found",
            message=f"state.json not found at {path}",
            field_path="$",
        )

    # --- JSON parse ---
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return StateLoadError(
            code="io_error",
            message=f"Could not read {path}: {exc}",
            field_path="$",
        )

    try:
        state: dict = json.loads(raw)
    except json.JSONDecodeError as exc:
        return StateLoadError(
            code="json_parse_error",
            message=f"JSON parse error: {exc.msg} at line {exc.lineno}",
            field_path="$",
            detail=str(exc),
        )

    if not isinstance(state, dict):
        return StateLoadError(
            code="not_an_object",
            message="state.json must be a JSON object",
            field_path="$",
        )

    # --- Schema validation ---
    effective_schema = schema if schema is not None else _get_default_schema()

    try:
        validate(state, effective_schema, strict=strict)
    except SchemaViolation as exc:
        return StateLoadError(
            code="schema_violation",
            message=str(exc),
            field_path=exc.field_path,
        )
    except SchemaTierExceeded as exc:
        return StateLoadError(
            code="schema_tier_exceeded",
            message=str(exc),
            field_path=exc.path,
        )

    # --- Budget check ---
    elapsed = time.monotonic() - t_start
    if elapsed > 1.0:
        # Log as warning but do not fail — return the valid state
        state["_loader_budget_exceeded_s"] = round(elapsed, 3)

    return state


def load_or_raise(
    state_path: str | Path,
    schema: dict | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """Like load() but raises StateLoadError instead of returning it."""
    result = load(state_path, schema, strict)
    if isinstance(result, StateLoadError):
        raise result
    return result
