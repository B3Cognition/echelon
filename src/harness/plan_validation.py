"""Harness-facing plan.md validation helpers."""

from __future__ import annotations

from pathlib import Path

from kernel.plan_contract import PlanValidationResult, validate_plan_markdown


class PlanValidationError(RuntimeError):
    """Raised when a plan.md file does not satisfy the harness plan contract."""


def validate_plan_file(plan_path: Path) -> PlanValidationResult:
    result = validate_plan_markdown(
        plan_path.read_text(encoding="utf-8", errors="replace")
    )
    if not result.valid:
        raise PlanValidationError("; ".join(result.errors))
    return result
