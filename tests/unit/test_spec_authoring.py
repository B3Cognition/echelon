from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from echelon.spec_authoring import (
    PERFECTIONIST_MODE,
    PROPORTIONAL_MODE,
    SpecAuthoringModeError,
    normalize_spec_authoring_mode,
    resolve_spec_authoring_mode,
)


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("value", [None, ""])
def test_normalize_missing_mode_defaults_to_proportional(value: object) -> None:
    assert normalize_spec_authoring_mode(value) == PROPORTIONAL_MODE


@pytest.mark.parametrize("mode", [PROPORTIONAL_MODE, PERFECTIONIST_MODE])
def test_normalize_accepts_canonical_modes(mode: str) -> None:
    assert normalize_spec_authoring_mode(mode) == mode


@pytest.mark.parametrize("value", ["exhaustive", "PERFECTIONIST", 1, True])
def test_normalize_rejects_noncanonical_modes(value: object) -> None:
    with pytest.raises(SpecAuthoringModeError, match="proportional or perfectionist"):
        normalize_spec_authoring_mode(value)


def test_resolve_fresh_perfectionist_request() -> None:
    assert resolve_spec_authoring_mode(
        {},
        is_fresh=True,
        perfectionist_requested=True,
    ) == PERFECTIONIST_MODE


def test_resolve_fresh_default_request_is_proportional() -> None:
    assert resolve_spec_authoring_mode(
        {},
        is_fresh=True,
        perfectionist_requested=False,
    ) == PROPORTIONAL_MODE


def test_resolve_prepared_retry_preserves_perfectionist_without_repeated_flag() -> None:
    assert resolve_spec_authoring_mode(
        {"spec_authoring_mode": PERFECTIONIST_MODE},
        is_fresh=True,
        perfectionist_requested=False,
    ) == PERFECTIONIST_MODE


def test_resolve_active_perfectionist_accepts_repeated_flag() -> None:
    assert resolve_spec_authoring_mode(
        {"spec_authoring_mode": PERFECTIONIST_MODE},
        is_fresh=False,
        perfectionist_requested=True,
    ) == PERFECTIONIST_MODE


@pytest.mark.parametrize(
    "state",
    [{}, {"spec_authoring_mode": PROPORTIONAL_MODE}],
)
def test_active_proportional_run_rejects_late_perfectionist_switch(
    state: dict[str, object],
) -> None:
    with pytest.raises(SpecAuthoringModeError, match="--reset --perfectionist"):
        resolve_spec_authoring_mode(
            state,
            is_fresh=False,
            perfectionist_requested=True,
        )


def test_state_schema_declares_spec_authoring_mode_enum() -> None:
    schema = json.loads((ROOT / "templates/state-schema.json").read_text())
    property_schema = schema["properties"]["spec_authoring_mode"]

    Draft7Validator(property_schema).validate(PROPORTIONAL_MODE)
    Draft7Validator(property_schema).validate(PERFECTIONIST_MODE)
    with pytest.raises(Exception):
        Draft7Validator(property_schema).validate("exhaustive")

    assert property_schema["default"] == PROPORTIONAL_MODE
