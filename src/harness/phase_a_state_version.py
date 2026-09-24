"""Admission boundary for durable Phase A run state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final


CURRENT_PHASE_A_STATE_VERSION: Final[int] = 1


class UnsupportedPhaseAStateError(ValueError):
    """Raised when a persisted Phase A run cannot be resumed directly."""

    def __init__(self, version: object) -> None:
        self.version = version
        super().__init__(
            "unsupported Phase A run state; restart with echelon spec run --reset"
        )


def require_current_phase_a_state(state: Mapping[str, object]) -> None:
    """Require the one durable state contract supported by this executable."""
    version = state.get("phase_a_state_version")
    if type(version) is not int or version != CURRENT_PHASE_A_STATE_VERSION:
        raise UnsupportedPhaseAStateError(version)
