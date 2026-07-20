from __future__ import annotations

import pytest

from harness.re_budget import evaluate_re_budget


pytestmark = pytest.mark.unit


def _state(*, tokens: int = 0, active_ms: int = 0) -> dict[str, object]:
    return {
        "re_execution_profile": {
            "name": "balanced",
            "hard_token_limit": 5_000_000,
            "hard_active_minutes": 180,
        },
        "re_token_usage": tokens,
        "re_active_duration_ms": active_ms,
    }


def test_no_dispatch_starts_at_token_ceiling() -> None:
    decision = evaluate_re_budget(_state(tokens=5_000_000))

    assert decision.allowed is False
    assert decision.reason == "re_token_budget_exhausted"


def test_no_dispatch_starts_at_active_time_ceiling() -> None:
    decision = evaluate_re_budget(_state(active_ms=180 * 60_000))

    assert decision.allowed is False
    assert decision.reason == "re_time_budget_exhausted"


def test_legacy_unknown_limits_remain_allowed() -> None:
    state = {
        "re_execution_profile": {
            "name": "legacy",
            "hard_token_limit": None,
            "hard_active_minutes": None,
        },
        "re_token_usage": 99_000_000,
        "re_active_duration_ms": 99_000_000,
    }

    assert evaluate_re_budget(state).allowed is True


def test_elapsed_current_invocation_counts_before_next_dispatch() -> None:
    state = _state(active_ms=(180 * 60_000) - 1_000)

    decision = evaluate_re_budget(state, current_invocation_ms=1_000)

    assert decision.allowed is False
    assert decision.consumed == 180 * 60_000
