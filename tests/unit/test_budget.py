"""Tests for budget slicing.

Per T039 task specification:
- Equal split with remainder
- Custom proportional split
- Unlimited budget passthrough
- N=0 error
- Over-allocated custom split error
"""

from __future__ import annotations

import pytest

from harness.budget import BudgetError, slice_budget


@pytest.mark.unit
class TestEqualSplit:
    """Test equal budget splitting."""

    def test_equal_split_no_remainder(self) -> None:
        result = slice_budget(90000, 3, strategy_ids=["a", "b", "c"])
        assert result == {"a": 30000, "b": 30000, "c": 30000}

    def test_equal_split_with_remainder(self) -> None:
        result = slice_budget(100000, 3, strategy_ids=["a", "b", "c"])
        # Remainder distributed to first strategies
        assert result["a"] == 33334
        assert result["b"] == 33333
        assert result["c"] == 33333
        assert sum(v for v in result.values()) == 100000

    def test_single_strategy(self) -> None:
        result = slice_budget(100000, 1, strategy_ids=["default"])
        assert result == {"default": 100000}


@pytest.mark.unit
class TestCustomSplit:
    """Test custom proportional splitting."""

    def test_custom_proportions(self) -> None:
        result = slice_budget(
            100000, 2,
            strategy_ids=["fast", "safe"],
            custom_splits={"fast": 0.7, "safe": 0.3},
        )
        assert result["fast"] == 70000
        assert result["safe"] == 30000

    def test_over_allocated_raises(self) -> None:
        with pytest.raises(BudgetError, match="exceeds 1.0"):
            slice_budget(
                100000, 2,
                strategy_ids=["a", "b"],
                custom_splits={"a": 0.6, "b": 0.5},
            )


@pytest.mark.unit
class TestUnlimited:
    """Test unlimited budget."""

    def test_none_budget_returns_none(self) -> None:
        result = slice_budget(None, 3, strategy_ids=["a", "b", "c"])
        assert result == {"a": None, "b": None, "c": None}


@pytest.mark.unit
class TestErrors:
    """Test error cases."""

    def test_zero_strategies_raises(self) -> None:
        with pytest.raises(BudgetError, match="strategy_count"):
            slice_budget(100000, 0)

    def test_negative_strategies_raises(self) -> None:
        with pytest.raises(BudgetError, match="strategy_count"):
            slice_budget(100000, -1)
