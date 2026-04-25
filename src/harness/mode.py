"""ModeController — run mode management for banzai/semi/guided.

Per ralph-controller.md contract + FR-MODE-001/FR-MODE-002:
- banzai: fully autonomous, only escalates on hard failures (infra, budget)
- semi: autonomous with pause on blockers
- guided: pause at every phase boundary, escalate on everything
- Mode is immutable once set (FR-MODE-002)
"""

from __future__ import annotations


VALID_MODES = {"banzai", "semi", "guided"}

# Categories that are "hard" failures (banzai always escalates on these)
HARD_FAILURE_CATEGORIES = {"infra_failure", "budget_exhaustion"}

# Categories that semi mode escalates on (in addition to hard failures)
SEMI_ESCALATION_CATEGORIES = HARD_FAILURE_CATEGORIES | {
    "same_failure_repeat",
    "spec_guard_violation",
    "why_quality_regression",
}


class ModeValidationError(Exception):
    """Raised when mode validation fails."""


class ModeController:
    """Controls run mode behavior.

    Modes (FR-MODE-001):
    - banzai: fully autonomous, no pauses, only hard-failure escalation
    - semi: autonomous with pause on blockers (default)
    - guided: pause at every phase boundary, escalate on everything

    Immutable for run duration (FR-MODE-002).
    """

    def __init__(self, mode: str) -> None:
        """Initialize with a valid mode.

        Args:
            mode: One of 'banzai', 'semi', 'guided'.

        Raises:
            ModeValidationError: If mode is not valid.
        """
        if mode not in VALID_MODES:
            raise ModeValidationError(
                f"Invalid mode '{mode}'. Must be one of: {sorted(VALID_MODES)}"
            )
        self._mode = mode

    @property
    def mode(self) -> str:
        """Current mode (read-only)."""
        return self._mode

    def should_pause_at_boundary(self, phase: str) -> bool:
        """Check if loop should pause at this phase boundary.

        Per FR-MODE-001:
        - guided: always True
        - semi: False
        - banzai: False

        Args:
            phase: Phase boundary name (e.g., 'after_build', 'after_verify').

        Returns:
            True if the loop should pause.
        """
        return self._mode == "guided"

    def should_escalate(self, category: str) -> bool:
        """Check if an issue should trigger escalation in this mode.

        Per FR-MODE-001:
        - banzai: only hard failures (infra_failure, budget_exhaustion)
        - semi: blockers (same_failure_repeat, spec_guard_violation,
                 why_quality_regression, budget_exhaustion, infra_failure)
        - guided: everything

        Args:
            category: Escalation category.

        Returns:
            True if escalation should be triggered.
        """
        if self._mode == "guided":
            return True
        if self._mode == "semi":
            return category in SEMI_ESCALATION_CATEGORIES
        # banzai
        return category in HARD_FAILURE_CATEGORIES

    def validate_mode_change(self, new_mode: str = "") -> None:
        """Validate that mode change is allowed (it isn't -- FR-MODE-002).

        Always raises ModeValidationError regardless of arguments.

        Raises:
            ModeValidationError: Always.
        """
        raise ModeValidationError(
            f"Mode is immutable after initialization (FR-MODE-002). "
            f"Current mode: '{self._mode}'. Mode changes are not allowed."
        )
