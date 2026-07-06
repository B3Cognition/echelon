from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.build_prompt import BuildPromptBuilder
from harness.config import HarnessConfig, StacksConfig
from harness.coordinator import StrategyCoordinator
from harness.loop_result import LoopResult
from harness.run_intent import RunIntent


ROOT = Path(__file__).resolve().parents[2]


def _coordinator_with_stacks(selected: list[str], base_dir: Path) -> StrategyCoordinator:
    config = HarnessConfig(
        target_repo="git@example.com:t/r.git",
        target_default_branch="main",
        provider="docker",
        stacks=StacksConfig(selected=selected),
    )
    return StrategyCoordinator(
        provider=MagicMock(),
        gitops=MagicMock(),
        config=config,
        base_dir=str(base_dir),
    )


@pytest.mark.unit
def test_build_prompt_includes_dedicated_stack_context_section() -> None:
    prompt = BuildPromptBuilder().build_prompt(
        worktree_path="/wt/001",
        spec_content="spec",
        tasks_content="tasks",
        build_skill="speckit.echelon.build",
        stack_context="# Resolved Echelon Stacks\n\n- statsperform-playbook\n",
    )

    assert "## Echelon Stack Context" in prompt
    assert "# Resolved Echelon Stacks" in prompt
    assert "statsperform-playbook" in prompt


@pytest.mark.unit
def test_no_selected_stacks_preserves_original_strategy_context() -> None:
    coord = _coordinator_with_stacks([], ROOT)

    stack_context = coord._build_stack_context()
    combined = coord._combine_strategy_context("Use the existing strategy", stack_context)

    assert stack_context == ""
    assert combined == "Use the existing strategy"


@pytest.mark.unit
def test_selected_stark_stack_context_resolves_playbook_dependency_first() -> None:
    coord = _coordinator_with_stacks(["statsperform-stark-webapp"], ROOT)

    stack_context = coord._build_stack_context()

    assert "# Resolved Echelon Stacks" in stack_context
    playbook_index = stack_context.index("- statsperform-playbook")
    stark_index = stack_context.index("- statsperform-stark-webapp")
    assert playbook_index < stark_index


@pytest.mark.unit
def test_strategy_context_is_preserved_before_generated_stack_context() -> None:
    coord = _coordinator_with_stacks(["statsperform-stark-webapp"], ROOT)

    combined = coord._combine_strategy_context(
        "Use the existing strategy file context",
        coord._build_stack_context(),
    )

    strategy_index = combined.index("Use the existing strategy file context")
    stack_index = combined.index("# Resolved Echelon Stacks")
    assert strategy_index < stack_index
    assert "statsperform-playbook" in combined
    assert "statsperform-stark-webapp" in combined


@pytest.mark.unit
def test_coordinator_passes_combined_stack_context_to_ralph_and_build_prompt(
    tmp_path: Path,
) -> None:
    strategy_dir = tmp_path / "runs" / "strategies" / "spec-001"
    strategy_dir.mkdir(parents=True)
    (strategy_dir / "default.md").write_text(
        "Use the existing strategy file context",
        encoding="utf-8",
    )

    extension_stacks = tmp_path / "extension" / "stacks"
    for stack_id in ("statsperform-playbook", "statsperform-stark-webapp"):
        source = ROOT / "extension" / "stacks" / stack_id
        target = extension_stacks / stack_id
        target.mkdir(parents=True)
        for path in source.iterdir():
            if path.is_file():
                (target / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    captured: dict[str, str] = {}
    coord = _coordinator_with_stacks(["statsperform-stark-webapp"], tmp_path)

    with pytest.MonkeyPatch.context() as monkeypatch:
        mock_ralph = MagicMock()
        mock_controller = MagicMock()
        mock_controller.run_loop.return_value = LoopResult(
            status="converged",
            termination_reason="converged",
            outer_iterations=1,
            inner_iterations=1,
            pr_url=None,
            tokens_used=0,
            final_verify=None,
        )

        def capture_run_loop(**kwargs):
            captured["strategy_context"] = kwargs.get("strategy_context", "")
            captured["build_prompt"] = kwargs.get("build_prompt", "")
            return mock_controller.run_loop.return_value

        mock_controller.run_loop.side_effect = capture_run_loop
        mock_ralph.return_value = mock_controller
        monkeypatch.setattr("harness.coordinator.RalphController", mock_ralph)

        coord.start(RunIntent(spec_id="spec-001", max_outer=1, max_inner=1))

    assert "Use the existing strategy file context" in captured["strategy_context"]
    assert "# Resolved Echelon Stacks" in captured["strategy_context"]
    assert "statsperform-playbook" in captured["strategy_context"]
    assert "statsperform-stark-webapp" in captured["strategy_context"]
    assert captured["strategy_context"] in captured["build_prompt"]
