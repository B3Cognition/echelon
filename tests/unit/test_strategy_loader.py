"""Tests for strategy file loader.

Per T038 task specification:
- Load single default strategy (no file)
- Load named strategy from file
- Missing strategy error with suggestions
- Load multiple strategies
- Frontmatter command override
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.strategy_loader import BUILTIN_STRATEGIES, StrategyNotFoundError, StrategySpec, load_strategies


@pytest.mark.unit
class TestStrategyLoader:
    """Test strategy loading."""

    def test_default_strategy_no_file(self, tmp_path: Path) -> None:
        """Default strategy returns StrategySpec with defaults when no file exists."""
        result = load_strategies("spec-001", ["default"], base_dir=str(tmp_path))
        assert result == {"default": StrategySpec(build_command="echelon build", context="")}

    def test_load_named_strategy(self, tmp_path: Path) -> None:
        """Named strategy loads file content as context (no frontmatter)."""
        strat_dir = tmp_path / "spec-001"
        strat_dir.mkdir(parents=True)
        (strat_dir / "aggressive.md").write_text("Be aggressive", encoding="utf-8")

        result = load_strategies("spec-001", ["aggressive"], base_dir=str(tmp_path))
        assert result == {
            "aggressive": StrategySpec(build_command="echelon build", context="Be aggressive"),
        }

    def test_missing_non_default_raises(self, tmp_path: Path) -> None:
        """Missing non-default strategy raises with available list."""
        strat_dir = tmp_path / "spec-001"
        strat_dir.mkdir(parents=True)
        (strat_dir / "conservative.md").write_text("Go slow", encoding="utf-8")

        with pytest.raises(StrategyNotFoundError, match="aggressive"):
            load_strategies("spec-001", ["aggressive"], base_dir=str(tmp_path))

    def test_load_multiple_strategies(self, tmp_path: Path) -> None:
        """Load multiple strategy files without frontmatter."""
        strat_dir = tmp_path / "spec-001"
        strat_dir.mkdir(parents=True)
        (strat_dir / "fast.md").write_text("Go fast", encoding="utf-8")
        (strat_dir / "safe.md").write_text("Go safe", encoding="utf-8")

        result = load_strategies("spec-001", ["fast", "safe"], base_dir=str(tmp_path))
        assert result == {
            "fast": StrategySpec(build_command="echelon build", context="Go fast"),
            "safe": StrategySpec(build_command="echelon build", context="Go safe"),
        }

    def test_default_with_file(self, tmp_path: Path) -> None:
        """Default strategy with file uses file content as context."""
        strat_dir = tmp_path / "spec-001"
        strat_dir.mkdir(parents=True)
        (strat_dir / "default.md").write_text("Default approach", encoding="utf-8")

        result = load_strategies("spec-001", ["default"], base_dir=str(tmp_path))
        assert result == {
            "default": StrategySpec(build_command="echelon build", context="Default approach"),
        }

    def test_frontmatter_command_override(self, tmp_path: Path) -> None:
        """Strategy file with command frontmatter overrides build_command."""
        strat_dir = tmp_path / "spec-001"
        strat_dir.mkdir(parents=True)
        (strat_dir / "codegen.md").write_text(
            "---\ncommand: echelon codegen\n---\n# Codegen Strategy\nContext here.",
            encoding="utf-8",
        )

        result = load_strategies("spec-001", ["codegen"], base_dir=str(tmp_path))
        assert result == {
            "codegen": StrategySpec(
                build_command="echelon codegen",
                context="# Codegen Strategy\nContext here.",
            ),
        }

    def test_frontmatter_no_command_key(self, tmp_path: Path) -> None:
        """Frontmatter without command key falls back to default build command."""
        strat_dir = tmp_path / "spec-001"
        strat_dir.mkdir(parents=True)
        (strat_dir / "annotated.md").write_text(
            "---\nauthor: alice\n---\nSome context.",
            encoding="utf-8",
        )

        result = load_strategies("spec-001", ["annotated"], base_dir=str(tmp_path))
        assert result == {
            "annotated": StrategySpec(build_command="echelon build", context="Some context."),
        }

    def test_frontmatter_not_closed(self, tmp_path: Path) -> None:
        """Unclosed frontmatter delimiter treats entire content as context."""
        strat_dir = tmp_path / "spec-001"
        strat_dir.mkdir(parents=True)
        (strat_dir / "broken.md").write_text(
            "---\ncommand: echelon codegen\nno closing delimiter",
            encoding="utf-8",
        )

        result = load_strategies("spec-001", ["broken"], base_dir=str(tmp_path))
        spec = result["broken"]
        assert spec.build_command == "echelon build"
        assert "command: echelon codegen" in spec.context

    def test_codegen_builtin_no_file(self, tmp_path: Path) -> None:
        """codegen is a built-in strategy — no file required."""
        result = load_strategies("spec-001", ["codegen"], base_dir=str(tmp_path))
        assert result == {"codegen": StrategySpec(build_command="echelon codegen", context="")}

    def test_codegen_file_overrides_builtin(self, tmp_path: Path) -> None:
        """Per-spec codegen.md wins over the built-in when present."""
        strat_dir = tmp_path / "spec-001"
        strat_dir.mkdir(parents=True)
        (strat_dir / "codegen.md").write_text("Extra context for this spec.", encoding="utf-8")

        result = load_strategies("spec-001", ["codegen"], base_dir=str(tmp_path))
        assert result == {
            "codegen": StrategySpec(build_command="echelon build", context="Extra context for this spec."),
        }

    def test_unknown_strategy_error_lists_builtins(self, tmp_path: Path) -> None:
        """Error for unknown strategy names built-in strategies as alternatives."""
        with pytest.raises(StrategyNotFoundError, match="Built-in strategies"):
            load_strategies("spec-001", ["nonexistent"], base_dir=str(tmp_path))

    def test_builtin_strategies_table(self) -> None:
        """BUILTIN_STRATEGIES contains the expected entries."""
        assert "default" in BUILTIN_STRATEGIES
        assert BUILTIN_STRATEGIES["default"].build_command == "echelon build"
        assert "codegen" in BUILTIN_STRATEGIES
        assert BUILTIN_STRATEGIES["codegen"].build_command == "echelon codegen"
