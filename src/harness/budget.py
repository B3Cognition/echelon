"""Budget slicing logic -- distribute token budget across strategies.

Per T039 / FR-STRATEGY-003:
  slice_budget(total, N, custom_splits) -> dict[str, int]
  Equal split by default. Custom proportional splits supported.
  None budget -> None per strategy (unlimited).
"""

from __future__ import annotations

from typing import Dict, List, Optional


class BudgetError(Exception):
    """Raised when budget slicing fails."""


def slice_budget(
    total_budget: Optional[int],
    strategy_count: int,
    strategy_ids: Optional[List[str]] = None,
    custom_splits: Optional[Dict[str, float]] = None,
) -> Dict[str, Optional[int]]:
    """Slice token budget across strategies.

    Args:
        total_budget: Total token budget. None = unlimited.
        strategy_count: Number of strategies.
        strategy_ids: List of strategy IDs (for custom splits).
        custom_splits: Dict of strategy_id -> proportion (0.0-1.0).

    Returns:
        Dict of strategy_id -> budget (None if unlimited).

    Raises:
        BudgetError: On invalid input.
    """
    if strategy_count <= 0:
        raise BudgetError("strategy_count must be > 0")

    # Generate default IDs if not provided
    if strategy_ids is None:
        strategy_ids = [f"strategy-{i}" for i in range(strategy_count)]

    if len(strategy_ids) != strategy_count:
        raise BudgetError(
            f"strategy_ids length ({len(strategy_ids)}) != "
            f"strategy_count ({strategy_count})"
        )

    # Unlimited budget
    if total_budget is None:
        return {sid: None for sid in strategy_ids}

    # Custom proportional splits
    if custom_splits is not None:
        total_proportion = sum(custom_splits.values())
        if total_proportion > 1.0 + 1e-9:
            raise BudgetError(
                f"Custom splits sum to {total_proportion:.3f}, "
                f"which exceeds 1.0"
            )
        result: Dict[str, Optional[int]] = {}
        for sid in strategy_ids:
            proportion = custom_splits.get(sid, 0.0)
            result[sid] = int(total_budget * proportion)
        return result

    # Equal split (remainder to first)
    per_strategy = total_budget // strategy_count
    remainder = total_budget - (per_strategy * strategy_count)

    result_equal: Dict[str, Optional[int]] = {}
    for i, sid in enumerate(strategy_ids):
        budget = per_strategy + (1 if i == 0 and remainder > 0 else 0)
        # Distribute remainder more evenly
        if i < remainder:
            budget = per_strategy + 1
        else:
            budget = per_strategy
        result_equal[sid] = budget

    return result_equal
