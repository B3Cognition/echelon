"""Controller-owned specification authoring mode semantics."""

from __future__ import annotations

from collections.abc import Mapping


PROPORTIONAL_MODE = "proportional"
PERFECTIONIST_MODE = "perfectionist"
SPEC_AUTHORING_MODES = frozenset({PROPORTIONAL_MODE, PERFECTIONIST_MODE})


class SpecAuthoringModeError(ValueError):
    """Raised when a spec run requests or persists an invalid authoring mode."""


def normalize_spec_authoring_mode(value: object) -> str:
    """Return one canonical mode, defaulting absent legacy state."""
    if value is None or value == "":
        return PROPORTIONAL_MODE
    if type(value) is not str or value not in SPEC_AUTHORING_MODES:
        raise SpecAuthoringModeError(
            "spec authoring mode must be proportional or perfectionist"
        )
    return value


def resolve_spec_authoring_mode(
    state: Mapping[str, object],
    *,
    is_fresh: bool,
    perfectionist_requested: bool,
) -> str:
    """Resolve fresh CLI intent without changing an active run's mode."""
    has_persisted_mode = "spec_authoring_mode" in state and state.get(
        "spec_authoring_mode"
    ) not in {None, ""}
    persisted_mode = normalize_spec_authoring_mode(
        state.get("spec_authoring_mode")
    )

    if not perfectionist_requested:
        return persisted_mode
    if has_persisted_mode:
        if persisted_mode == PERFECTIONIST_MODE:
            return persisted_mode
        raise SpecAuthoringModeError(
            "the active spec run uses proportional authoring; start a new run "
            "with --reset --perfectionist"
        )
    if not is_fresh:
        raise SpecAuthoringModeError(
            "the active legacy spec run uses proportional authoring; start a "
            "new run with --reset --perfectionist"
        )
    return PERFECTIONIST_MODE
