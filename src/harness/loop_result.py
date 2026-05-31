"""LoopResult dataclass — structured return from RalphController.run_loop().

Per ralph-controller.md contract:
  status: converged | failed | blocked | interrupted | cancelled
  termination_reason: per FR-LOOP-004
  outer_iterations, inner_iterations, pr_url, tokens_used, final_verify
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from harness.verify_result import VerifyResult


VALID_STATUSES = {"converged", "failed", "blocked", "interrupted", "cancelled", "review_fix_queued"}

VALID_TERMINATION_REASONS = {
    "converged",
    "outer_cap",
    "inner_cap_no_progress",
    "same_failure_threshold",
    "budget_exhausted",
    "build_incomplete",
    "blocker_escalation",
    "user_cancel",
    "killed_by_coordinator",
    "visual_failed",
    "review_fix_queued",
    "no_progress",
    "publish_failed",
    "verify_command_needed",
}


class LoopResultError(Exception):
    """Raised when LoopResult validation fails."""


@dataclass
class LoopResult:
    """Structured result from a ralph-loop execution.

    Matches ralph-controller.md contract exactly.
    """
    status: str
    termination_reason: str
    outer_iterations: int
    inner_iterations: int
    pr_url: Optional[str]
    tokens_used: int
    final_verify: Optional[VerifyResult]
    branch: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate fields after construction."""
        if self.status not in VALID_STATUSES:
            raise LoopResultError(
                f"Invalid status '{self.status}'. "
                f"Must be one of: {sorted(VALID_STATUSES)}"
            )
        if self.termination_reason not in VALID_TERMINATION_REASONS:
            raise LoopResultError(
                f"Invalid termination_reason '{self.termination_reason}'. "
                f"Must be one of: {sorted(VALID_TERMINATION_REASONS)}"
            )
        if self.outer_iterations < 0:
            raise LoopResultError(
                f"outer_iterations must be >= 0, got {self.outer_iterations}"
            )
        if self.inner_iterations < 0:
            raise LoopResultError(
                f"inner_iterations must be >= 0, got {self.inner_iterations}"
            )
        if self.tokens_used < 0:
            raise LoopResultError(
                f"tokens_used must be >= 0, got {self.tokens_used}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for state persistence."""
        result: Dict[str, Any] = {
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
                        "category": f.category.value,
                        "id": f.id,
                        "error": f.error,
                    }
                    for f in self.final_verify.failures
                ],
                "duration_s": self.final_verify.duration_s,
                "token_usage": self.final_verify.token_usage,
            }
        return result
