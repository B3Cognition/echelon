"""Typed outcomes for harness phases and the overall delivery run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from harness.verify_result import VerifyResult


IMPLEMENTATION_STATUSES = {"verified", "blocked", "interrupted", "failed", "cancelled"}
VISUAL_STATUSES = {"passed", "fix_applied", "blocked"}
REVIEW_STATUSES = {"completed", "review_fix_queued", "blocked"}
DELIVERY_STATUSES = {"converged", "blocked", "interrupted", "failed", "cancelled"}
LANDING_STATUSES = {"not_requested", "landed", "blocked", "skipped"}


def _validate_result(
    *,
    status: str,
    valid_statuses: set[str],
    counters: dict[str, int],
) -> None:
    if status not in valid_statuses:
        raise ValueError(
            f"Invalid status '{status}'. Must be one of: {sorted(valid_statuses)}"
        )
    for name, value in counters.items():
        if value < 0:
            raise ValueError(f"{name} must be >= 0, got {value}")


@dataclass(frozen=True)
class ImplementationResult:
    status: str
    termination_reason: str
    outer_iterations: int
    inner_iterations: int
    pr_url: str | None
    tokens_used: int
    final_verify: VerifyResult | None
    branch: str | None = None

    def __post_init__(self) -> None:
        _validate_result(
            status=self.status,
            valid_statuses=IMPLEMENTATION_STATUSES,
            counters={
                "outer_iterations": self.outer_iterations,
                "inner_iterations": self.inner_iterations,
                "tokens_used": self.tokens_used,
            },
        )


@dataclass(frozen=True)
class VisualResult:
    status: str
    termination_reason: str
    iterations: int
    tokens_used: int
    final_verify: VerifyResult | None

    def __post_init__(self) -> None:
        _validate_result(
            status=self.status,
            valid_statuses=VISUAL_STATUSES,
            counters={"iterations": self.iterations, "tokens_used": self.tokens_used},
        )


@dataclass(frozen=True)
class ReviewResult:
    status: str
    termination_reason: str
    iterations: int
    pr_url: str
    tokens_used: int

    def __post_init__(self) -> None:
        _validate_result(
            status=self.status,
            valid_statuses=REVIEW_STATUSES,
            counters={"iterations": self.iterations, "tokens_used": self.tokens_used},
        )


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    termination_reason: str
    outer_iterations: int
    inner_iterations: int
    pr_url: str | None
    tokens_used: int
    final_verify: VerifyResult | None
    branch: str | None = None

    def __post_init__(self) -> None:
        _validate_result(
            status=self.status,
            valid_statuses=DELIVERY_STATUSES,
            counters={
                "outer_iterations": self.outer_iterations,
                "inner_iterations": self.inner_iterations,
                "tokens_used": self.tokens_used,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "termination_reason": self.termination_reason,
            "outer_iterations": self.outer_iterations,
            "inner_iterations": self.inner_iterations,
            "pr_url": self.pr_url,
            "tokens_used": self.tokens_used,
            "final_verify": None,
            "branch": self.branch,
        }
        if self.final_verify is not None:
            result["final_verify"] = {
                "passed": self.final_verify.passed,
                "failures": [
                    {
                        "category": failure.category.value,
                        "id": failure.id,
                        "error": failure.error,
                    }
                    for failure in self.final_verify.failures
                ],
                "duration_s": self.final_verify.duration_s,
                "token_usage": self.final_verify.token_usage,
            }
        return result


@dataclass(frozen=True)
class LandingOutcome:
    status: str
    reason: str = ""

    def __post_init__(self) -> None:
        _validate_result(status=self.status, valid_statuses=LANDING_STATUSES, counters={})


@dataclass(frozen=True)
class DeliveryRunOutcome:
    results: tuple[DeliveryResult, ...]
    landing: LandingOutcome
