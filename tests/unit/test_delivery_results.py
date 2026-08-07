"""Contracts for phase and delivery result values."""

from __future__ import annotations

import pytest

from harness.delivery_results import (
    DELIVERY_STATUSES,
    IMPLEMENTATION_STATUSES,
    LANDING_STATUSES,
    REVIEW_STATUSES,
    VISUAL_STATUSES,
    DeliveryResult,
    ImplementationResult,
    LandingOutcome,
    ReviewResult,
    VisualResult,
)


@pytest.mark.unit
def test_phase_and_delivery_statuses_do_not_overlap() -> None:
    assert "converged" not in IMPLEMENTATION_STATUSES
    assert "converged" not in VISUAL_STATUSES
    assert "converged" not in REVIEW_STATUSES
    assert DELIVERY_STATUSES == {
        "converged", "blocked", "interrupted", "failed", "cancelled"
    }


@pytest.mark.unit
def test_delivery_result_serializes_common_evidence() -> None:
    result = DeliveryResult(
        status="converged",
        termination_reason="converged",
        outer_iterations=2,
        inner_iterations=3,
        pr_url="https://github.com/acme/api/pull/7",
        tokens_used=40,
        final_verify=None,
        blocked_phase=None,
        branch="delivery/042",
    )
    assert result.to_dict()["status"] == "converged"
    assert result.to_dict()["branch"] == "delivery/042"


@pytest.mark.unit
@pytest.mark.parametrize(
    "result_factory",
    [
        lambda status: ImplementationResult(status, "", 0, 0, None, 0, None),
        lambda status: VisualResult(status, "", 0, 0, None),
        lambda status: ReviewResult(status, "", 0, "https://example.test/pr/1", 0),
        lambda status: DeliveryResult(status, "", 0, 0, None, 0, None, None),
        lambda status: LandingOutcome(status),
    ],
)
def test_result_types_reject_unknown_statuses(result_factory) -> None:
    with pytest.raises(ValueError, match="Invalid status"):
        result_factory("invalid")


@pytest.mark.unit
def test_phase_and_delivery_results_reject_negative_counters() -> None:
    with pytest.raises(ValueError, match="outer_iterations"):
        ImplementationResult("verified", "", -1, 0, None, 0, None)
    with pytest.raises(ValueError, match="iterations"):
        VisualResult("passed", "", -1, 0, None)
    with pytest.raises(ValueError, match="iterations"):
        ReviewResult("completed", "", -1, "https://example.test/pr/1", 0)
    with pytest.raises(ValueError, match="tokens_used"):
        DeliveryResult("converged", "", 0, 0, None, -1, None, None)


@pytest.mark.unit
def test_landing_statuses_are_exact() -> None:
    assert LANDING_STATUSES == {"not_requested", "landed", "blocked", "skipped"}


@pytest.mark.unit
def test_delivery_blocked_status_requires_an_exact_phase() -> None:
    common = dict(
        termination_reason="outer_cap",
        outer_iterations=1,
        inner_iterations=0,
        pr_url=None,
        tokens_used=1,
        final_verify=None,
    )
    for phase in ("implementation", "visual", "review", "finalization"):
        assert DeliveryResult(status="blocked", blocked_phase=phase, **common).blocked_phase == phase
    with pytest.raises(ValueError, match="blocked_phase"):
        DeliveryResult(status="blocked", blocked_phase=None, **common)
    with pytest.raises(ValueError, match="blocked_phase"):
        DeliveryResult(status="blocked", blocked_phase="unknown", **common)
    with pytest.raises(ValueError, match="blocked_phase"):
        DeliveryResult(status="converged", blocked_phase="implementation", **common)
