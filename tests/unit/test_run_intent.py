"""Tests for RunIntent parsing and validation.

Per T028 task specification:
- 8 parse_intent golden-file tests (valid inputs)
- 5 validation rejection tests
"""

from __future__ import annotations

import pytest

from harness.run_intent import IntentValidationError, RunIntent, parse_intent


@pytest.mark.unit
class TestRunIntentConstruction:
    """Test direct RunIntent construction and validation."""

    def test_defaults(self) -> None:
        intent = RunIntent(spec_id="012")
        assert intent.spec_id == "012"
        assert intent.mode == "semi"
        assert intent.max_outer == 5
        assert intent.max_inner == 3
        assert intent.token_budget is None
        assert intent.auto_merge is False
        assert intent.kill_losers is False
        assert intent.strategies == ["default"]

    def test_all_fields(self) -> None:
        intent = RunIntent(
            spec_id="042",
            mode="banzai",
            max_outer=10,
            max_inner=5,
            token_budget=500000,
            auto_merge=True,
            kill_losers=True,
            strategies=["aggressive", "conservative"],
        )
        assert intent.spec_id == "042"
        assert intent.mode == "banzai"
        assert intent.max_outer == 10
        assert intent.max_inner == 5
        assert intent.token_budget == 500000
        assert intent.auto_merge is True
        assert intent.kill_losers is True
        assert intent.strategies == ["aggressive", "conservative"]


@pytest.mark.unit
class TestRunIntentValidation:
    """Test validation rejection cases."""

    def test_missing_spec_id_raises(self) -> None:
        with pytest.raises(IntentValidationError, match="spec_id"):
            RunIntent(spec_id="")

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(IntentValidationError, match="Invalid mode"):
            RunIntent(spec_id="012", mode="turbo")

    def test_guided_auto_merge_rejected(self) -> None:
        """FR-MERGE-001: auto_merge + guided is forbidden."""
        with pytest.raises(IntentValidationError, match="FR-MERGE-001"):
            RunIntent(spec_id="012", mode="guided", auto_merge=True)

    def test_empty_strategies_rejected(self) -> None:
        with pytest.raises(IntentValidationError, match="non-empty"):
            RunIntent(spec_id="012", strategies=[])

    def test_zero_budget_rejected(self) -> None:
        with pytest.raises(IntentValidationError, match="token_budget"):
            RunIntent(spec_id="012", token_budget=0)

    def test_zero_max_outer_rejected(self) -> None:
        with pytest.raises(IntentValidationError, match="max_outer"):
            RunIntent(spec_id="012", max_outer=0)

    def test_zero_max_inner_rejected(self) -> None:
        with pytest.raises(IntentValidationError, match="max_inner"):
            RunIntent(spec_id="012", max_inner=0)


@pytest.mark.unit
class TestParseIntent:
    """Test natural-language parsing of run intents (golden-file tests)."""

    def test_basic_spec_id(self) -> None:
        intent = parse_intent("spec 012 in semi mode, max 5 outer iterations")
        assert intent.spec_id == "012"
        assert intent.mode == "semi"
        assert intent.max_outer == 5

    def test_banzai_mode(self) -> None:
        intent = parse_intent("spec 042 banzai mode")
        assert intent.spec_id == "042"
        assert intent.mode == "banzai"

    def test_guided_mode(self) -> None:
        intent = parse_intent("spec 001 in guided mode")
        assert intent.spec_id == "001"
        assert intent.mode == "guided"

    def test_with_budget(self) -> None:
        intent = parse_intent("spec 012 budget=100000")
        assert intent.spec_id == "012"
        assert intent.token_budget == 100000

    def test_with_auto_merge(self) -> None:
        intent = parse_intent("spec 012 banzai auto_merge")
        assert intent.spec_id == "012"
        assert intent.auto_merge is True

    def test_with_kill_losers(self) -> None:
        intent = parse_intent("spec 012 kill_losers strategies=aggressive,conservative")
        assert intent.spec_id == "012"
        assert intent.kill_losers is True
        assert intent.strategies == ["aggressive", "conservative"]

    def test_with_inner_outer(self) -> None:
        intent = parse_intent("spec 012 max 10 outer iterations, max 5 inner iterations")
        assert intent.spec_id == "012"
        assert intent.max_outer == 10
        assert intent.max_inner == 5

    def test_defaults_when_minimal(self) -> None:
        intent = parse_intent("spec 012")
        assert intent.spec_id == "012"
        assert intent.mode == "semi"
        assert intent.max_outer == 5
        assert intent.max_inner == 3
        assert intent.token_budget is None
        assert intent.auto_merge is False
        assert intent.kill_losers is False
        assert intent.strategies == ["default"]

    def test_missing_spec_id_raises(self) -> None:
        """FR-CLI-001: missing spec_id raises with clarifying question."""
        with pytest.raises(IntentValidationError, match="spec_id"):
            parse_intent("just run it in banzai mode")

    def test_parse_completes_fast(self) -> None:
        """FR-CLI-001: parsing completes within 2 seconds."""
        import time
        start = time.monotonic()
        parse_intent("spec 012 in semi mode, max 5 outer iterations")
        elapsed = time.monotonic() - start
        assert elapsed < 2.0
