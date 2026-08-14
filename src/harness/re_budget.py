"""Pure end-to-end budget decisions for reverse-engineering dispatches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ReBudgetDecision:
    allowed: bool
    reason: str = ""
    limit: int | None = None
    consumed: int | None = None


def evaluate_re_budget(
    state: Mapping[str, object],
    *,
    current_invocation_ms: int = 0,
    minimum_dispatch_tokens: int = 0,
) -> ReBudgetDecision:
    raw_profile = state.get("re_execution_profile")
    profile = raw_profile if isinstance(raw_profile, Mapping) else {}
    token_limit = _optional_positive(profile.get("hard_token_limit"))
    tokens = _nonnegative(state.get("re_token_usage"))
    if token_limit is not None and tokens >= token_limit:
        return ReBudgetDecision(
            False, "re_token_budget_exhausted", token_limit, tokens
        )
    required = max(0, int(minimum_dispatch_tokens))
    if (
        token_limit is not None
        and required > 0
        and token_limit - tokens < required
    ):
        return ReBudgetDecision(
            False, "re_token_budget_exhausted", token_limit, tokens
        )
    minute_limit = _optional_positive(profile.get("hard_active_minutes"))
    active_ms = _nonnegative(state.get("re_active_duration_ms")) + max(
        0, int(current_invocation_ms)
    )
    if minute_limit is not None:
        time_limit_ms = minute_limit * 60_000
        if active_ms >= time_limit_ms:
            return ReBudgetDecision(
                False, "re_time_budget_exhausted", time_limit_ms, active_ms
            )
    return ReBudgetDecision(True)


def remaining_re_tokens(state: Mapping[str, object]) -> int | None:
    raw_profile = state.get("re_execution_profile")
    profile = raw_profile if isinstance(raw_profile, Mapping) else {}
    token_limit = _optional_positive(profile.get("hard_token_limit"))
    if token_limit is None:
        return None
    return max(0, token_limit - _nonnegative(state.get("re_token_usage")))


def _optional_positive(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _nonnegative(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))
