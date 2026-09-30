"""Current-version admission for durable Phase A run state."""

from __future__ import annotations

import pytest

from harness.phase_a_state_version import (
    CURRENT_PHASE_A_STATE_VERSION,
    UnsupportedPhaseAStateError,
    require_current_phase_a_state,
)


def test_current_phase_a_state_is_accepted() -> None:
    require_current_phase_a_state(
        {"phase_a_state_version": CURRENT_PHASE_A_STATE_VERSION}
    )


@pytest.mark.parametrize("version", [None, 0, 2, "1", True])
def test_non_current_phase_a_state_is_rejected(version: object) -> None:
    state = {} if version is None else {"phase_a_state_version": version}

    with pytest.raises(UnsupportedPhaseAStateError) as error:
        require_current_phase_a_state(state)

    assert error.value.version is version
    assert "echelon spec run --reset" in str(error.value)
