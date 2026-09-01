from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.build_prompt import BuildPromptBuilder
from harness.config import HarnessConfig, StacksConfig
from harness.coordinator import StrategyCoordinator
from harness.delivery_results import ImplementationResult
from harness.run_intent import RunIntent
from harness.stacks.errors import StackResolutionError
from harness.stacks.paths import find_stack_extension_root
from harness.stacks.preflight import StackPreflightResult


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def mock_stack_preflight(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Keep prompt-context unit tests independent of registry availability."""
    preflight = MagicMock(return_value=StackPreflightResult(findings=[]))
    monkeypatch.setattr("harness.stacks.context.run_stack_preflight", preflight)
    return preflight


def _coordinator_with_stacks(
    selected: list[str],
    base_dir: Path,
    *,
    target_archetypes: list[str] | None = None,
) -> StrategyCoordinator:
    config = HarnessConfig(
        target_repo="git@example.com:t/r.git",
        target_default_branch="main",
        provider="docker",
        stacks=StacksConfig(
            selected=selected,
            target_archetypes=target_archetypes or [],
        ),
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
        build_skill="echelon.build",
        stack_context="# Resolved Echelon Stacks\n\n- statsperform-playbook\n",
    )

    assert "## Echelon Stack Context" in prompt
    assert "# Resolved Echelon Stacks" in prompt
    assert "statsperform-playbook" in prompt


@pytest.mark.unit
def test_browser_stack_context_explains_candidate_owned_runnability_contract() -> None:
    coord = _coordinator_with_stacks(
        ["browser-3d-game", "game-persistence-postgres"],
        ROOT,
        target_archetypes=["browser_3d_game"],
    )

    stack_context = coord._build_stack_context()

    assert ".echelon/runnability.yml" in stack_context
    assert "browser_dom" in stack_context
    assert "postgres_query" in stack_context
    assert "echelon delivery status" in stack_context
    assert "echelon spec defer-runnability" in stack_context
    assert "## Candidate Runnability Contract Schema" in stack_context
    assert "schema_version: 1" in stack_context
    assert "install_commands:" in stack_context
    assert "real_services_required: [web, api, postgres]" in stack_context
    assert "kind: http" in stack_context
    assert "expectation: status_200" in stack_context
    assert "persistence_probe:" in stack_context
    assert "invent aliases such as `runtime`, `provision`" in stack_context


@pytest.mark.unit
def test_ios_runnability_stack_context_names_future_runner_without_claiming_pass() -> None:
    coord = _coordinator_with_stacks(
        ["ios-ar-game"],
        ROOT,
        target_archetypes=["ios_ar_game"],
    )

    stack_context = coord._build_stack_context()

    assert "macOS simulator runner" in stack_context
    assert "cannot be represented as a pass" in stack_context


@pytest.mark.unit
def test_no_selected_stacks_preserves_original_strategy_context() -> None:
    coord = _coordinator_with_stacks([], ROOT)

    stack_context = coord._build_stack_context()
    combined = coord._combine_strategy_context("Use the existing strategy", stack_context)

    assert stack_context == ""
    assert combined == "Use the existing strategy"


@pytest.mark.unit
def test_selected_stark_stack_context_resolves_playbook_dependency_first(
    mock_stack_preflight: MagicMock,
) -> None:
    coord = _coordinator_with_stacks(["statsperform-stark-webapp"], ROOT)

    stack_context = coord._build_stack_context()

    assert "# Resolved Echelon Stacks" in stack_context
    assert "## Stack Preflight" in stack_context
    playbook_index = stack_context.index("- statsperform-playbook")
    stark_index = stack_context.index("- statsperform-stark-webapp")
    assert playbook_index < stark_index
    assert "## Stack Guidance" in stack_context
    assert "Use Playbook for UI components" in stack_context
    assert "Use the Opta Stark Nx/Next.js archetype" in stack_context
    mock_stack_preflight.assert_called_once()


@pytest.mark.unit
def test_deployed_runtime_stack_layout_is_supported(tmp_path: Path) -> None:
    installed_stacks = tmp_path / ".echelon" / "runtime" / "stacks"
    for stack_id in ("statsperform-playbook", "statsperform-stark-webapp"):
        source = ROOT / "runtime" / "stacks" / stack_id
        target = installed_stacks / stack_id
        target.mkdir(parents=True)
        for path in source.iterdir():
            if path.is_file():
                (target / path.name).write_text(
                    path.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )

    coord = _coordinator_with_stacks(["statsperform-stark-webapp"], tmp_path)

    stack_context = coord._build_stack_context()

    assert find_stack_extension_root(tmp_path) == tmp_path / ".echelon" / "runtime"
    assert "statsperform-playbook" in stack_context
    assert "statsperform-stark-webapp" in stack_context
    assert "Use the Opta Stark Nx/Next.js archetype" in stack_context


@pytest.mark.unit
def test_configured_target_archetypes_are_enforced() -> None:
    coord = _coordinator_with_stacks(
        ["statsperform-msa-service"],
        ROOT,
        target_archetypes=["web_app"],
    )

    with pytest.raises(StackResolutionError, match="statsperform-msa-service"):
        coord._build_stack_context()


@pytest.mark.unit
def test_spec_frontmatter_target_archetypes_are_enforced(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "spec-001"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\n"
        "target_archetypes:\n"
        "  - service\n"
        "---\n"
        "# Spec\n",
        encoding="utf-8",
    )
    coord = _coordinator_with_stacks(["statsperform-stark-webapp"], ROOT)

    with pytest.raises(StackResolutionError, match="statsperform-playbook|statsperform-stark-webapp"):
        coord._build_stack_context(spec_dir)


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
        source = ROOT / "runtime" / "stacks" / stack_id
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
        mock_controller.run_loop.return_value = ImplementationResult(
            status="verified",
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
