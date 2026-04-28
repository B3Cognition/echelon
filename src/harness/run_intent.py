"""RunIntent — parsed representation of /speckit-harness-run arguments.

Per data-model RunIntent entity:
  spec_id, mode, max_outer, max_inner, token_budget, auto_merge, kill_losers, strategies.

Per FR-CLI-001: parse_intent completes within 2 seconds.
Per FR-MERGE-001: auto_merge=true + mode=guided is rejected.
Per FR-CLI-001: missing spec_id raises with single clarifying question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


VALID_MODES = {"banzai", "semi", "guided"}


class IntentValidationError(Exception):
    """Raised when RunIntent validation fails."""


@dataclass
class RunIntent:
    """Parsed representation of a harness run request.

    Matches data-model.md RunIntent entity exactly.
    """
    spec_id: str
    mode: str = "semi"
    max_outer: int = 5
    max_inner: int = 3
    token_budget: Optional[int] = None
    auto_merge: bool = False
    kill_losers: bool = False
    strategies: List[str] = field(default_factory=lambda: ["default"])
    task_description: str = ""

    def __post_init__(self) -> None:
        """Validate all fields after construction."""
        self.validate()

    def validate(self) -> None:
        """Validate RunIntent invariants.

        Raises:
            IntentValidationError: On any validation failure.
        """
        # spec_id required
        if not self.spec_id or not self.spec_id.strip():
            raise IntentValidationError(
                "Missing spec_id. Which spec would you like to run? "
                "Provide a spec ID (e.g., '012')."
            )

        # mode must be valid enum
        if self.mode not in VALID_MODES:
            raise IntentValidationError(
                f"Invalid mode '{self.mode}'. Must be one of: {sorted(VALID_MODES)}"
            )

        # max_outer must be positive
        if self.max_outer <= 0:
            raise IntentValidationError(
                f"max_outer must be > 0, got {self.max_outer}"
            )

        # max_inner must be positive
        if self.max_inner <= 0:
            raise IntentValidationError(
                f"max_inner must be > 0, got {self.max_inner}"
            )

        # token_budget must be positive if set
        if self.token_budget is not None and self.token_budget <= 0:
            raise IntentValidationError(
                f"token_budget must be > 0 or None (unlimited), got {self.token_budget}"
            )

        # strategies must be non-empty
        if not self.strategies:
            raise IntentValidationError(
                "strategies must be non-empty. Provide at least one strategy ID."
            )

        # FR-MERGE-001: auto_merge + guided is forbidden
        if self.auto_merge and self.mode == "guided":
            raise IntentValidationError(
                "auto_merge=true is not allowed with mode=guided (FR-MERGE-001). "
                "Guided mode requires human review before merge."
            )


# --- Natural language parsing ---

# Patterns for extracting fields from natural language
_SPEC_PATTERN = re.compile(
    r"(?:spec\s+|spec_id\s*[=:]\s*)(\w[\w-]*)",
    re.IGNORECASE,
)
_MODE_PATTERN = re.compile(
    r"(?:in\s+)?(\bbanzai\b|\bsemi\b|\bguided\b)\s*(?:mode)?",
    re.IGNORECASE,
)
_MAX_OUTER_PATTERN = re.compile(
    r"(?:max\s+)?(\d+)\s+outer\s+(?:iteration|iter)",
    re.IGNORECASE,
)
_MAX_INNER_PATTERN = re.compile(
    r"(?:max\s+)?(\d+)\s+inner\s+(?:iteration|iter)",
    re.IGNORECASE,
)
_BUDGET_PATTERN = re.compile(
    r"(?:budget|token_budget)\s*[=:]\s*(\d+)",
    re.IGNORECASE,
)
_AUTO_MERGE_PATTERN = re.compile(
    r"\bauto[_\s]?merge\b",
    re.IGNORECASE,
)
_KILL_LOSERS_PATTERN = re.compile(
    r"\bkill[_\s]?losers\b",
    re.IGNORECASE,
)
_STRATEGIES_PATTERN = re.compile(
    r"(?:strateg(?:y|ies)\s*[=:]\s*)([\w-]+(?:\s*,\s*[\w-]+)*)",
    re.IGNORECASE,
)
_TASK_PATTERN = re.compile(
    r"task:\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)


def parse_intent(text: str) -> RunIntent:
    """Parse a RunIntent from natural-language text.

    Per FR-CLI-001: raises IntentValidationError with a single
    clarifying question when spec_id is missing.

    Args:
        text: Natural-language run request.

    Returns:
        Validated RunIntent.

    Raises:
        IntentValidationError: On missing required fields or invalid values.
    """
    # Extract spec_id
    spec_match = _SPEC_PATTERN.search(text)
    spec_id = spec_match.group(1) if spec_match else ""

    # Extract mode
    mode = "semi"
    mode_match = _MODE_PATTERN.search(text)
    if mode_match:
        mode = mode_match.group(1).lower()

    # Extract max_outer
    max_outer = 5
    outer_match = _MAX_OUTER_PATTERN.search(text)
    if outer_match:
        max_outer = int(outer_match.group(1))

    # Extract max_inner
    max_inner = 3
    inner_match = _MAX_INNER_PATTERN.search(text)
    if inner_match:
        max_inner = int(inner_match.group(1))

    # Extract token_budget
    token_budget: Optional[int] = None
    budget_match = _BUDGET_PATTERN.search(text)
    if budget_match:
        token_budget = int(budget_match.group(1))

    # Extract auto_merge
    auto_merge = bool(_AUTO_MERGE_PATTERN.search(text))

    # Extract kill_losers
    kill_losers = bool(_KILL_LOSERS_PATTERN.search(text))

    # Extract strategies
    strategies = ["default"]
    strat_match = _STRATEGIES_PATTERN.search(text)
    if strat_match:
        raw = strat_match.group(1)
        strategies = [s.strip() for s in raw.split(",") if s.strip()]

    # Extract free-text task description (everything after "task: ")
    task_description = ""
    task_match = _TASK_PATTERN.search(text)
    if task_match:
        task_description = task_match.group(1).strip()

    return RunIntent(
        spec_id=spec_id,
        mode=mode,
        max_outer=max_outer,
        max_inner=max_inner,
        token_budget=token_budget,
        auto_merge=auto_merge,
        kill_losers=kill_losers,
        strategies=strategies,
        task_description=task_description,
    )
