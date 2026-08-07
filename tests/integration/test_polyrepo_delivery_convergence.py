"""Three-root regression for converged delivery and blocked auto-land."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from harness.config import HarnessConfig, ReviewLoopConfig, VisualTestsConfig
from harness.delivery_results import ImplementationResult, ReviewResult, VisualResult
from harness.paths import current_build_marker
from harness.review_artifacts import ReviewArtifactPublisher
from harness.run_intent import RunIntent
from harness.skills.run_skill import run
from harness.spec_frontmatter import read_frontmatter
from harness.state import StateStore


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _target_checkout(tmp_path: Path) -> tuple[Path, str]:
    target = tmp_path / "target-repository"
    target.mkdir()
    _git(target, "init", "-b", "main")
    _git(target, "config", "user.name", "Integration Test")
    _git(target, "config", "user.email", "integration@example.invalid")
    (target / "README.md").write_text("target\n", encoding="utf-8")
    _git(target, "add", "README.md")
    _git(target, "commit", "-m", "initial target")
    return target, _git(target, "rev-parse", "HEAD")


def _review_append(task_ids: tuple[str, ...]) -> str:
    return "\n".join(
        "- [ ] "
        f"{task_id} complexity=standard phase=review-fix req=UNMAPPED depends=none\n\n"
        f"  **Title:** RF1-T{index} - Review follow-up\n"
        for index, task_id in enumerate(task_ids, start=1)
    )


class _PublishingReviewController:
    """Deterministic Phase 3 fake that retains real staged publication."""

    staged_write_paths: list[Path] = []

    def __init__(
        self,
        *,
        config: HarnessConfig,
        strategy_id: str,
        base_dir: str,
        build_id: str,
        spec_dir: Path,
        **_: object,
    ) -> None:
        self._strategy_id = strategy_id
        self._state_dir = Path(base_dir) / "runs" / build_id / "state"
        self._spec_dir = spec_dir
        self._config = config
        self.queued_task_ids: tuple[str, ...] = ()
        self.published_artifacts: tuple[Path, ...] = ()
        self.pending_batch_attempt_id: str | None = None

    def run_loop(
        self, *, pr_url: str, worktree_path: str, token_budget: int | None
    ) -> ReviewResult:
        assert Path(worktree_path).is_dir()
        with ReviewArtifactPublisher(
            self._spec_dir, self._state_dir, self._strategy_id
        ) as publisher:
            allocation = publisher.allocate(("review-1",))
            artifact = allocation.attempt_dir / allocation.artifact_names[0]
            append = allocation.attempt_dir / "tasks-append.md"
            artifact.write_text("# Review fix\n", encoding="utf-8")
            append.write_text(_review_append(allocation.task_ids), encoding="utf-8")
            allocation.status_file.write_text(
                json.dumps(
                    {
                        "status": "review_fix_queued",
                        "groups": 1,
                        "artifacts": [allocation.artifact_names[0]],
                        "tasks": [
                            {
                                "task_id": task_id,
                                "review_task_id": f"RF1-T{index}",
                                "artifact": allocation.artifact_names[0],
                            }
                            for index, task_id in enumerate(allocation.task_ids, start=1)
                        ],
                        "tasks_append": "tasks-append.md",
                    }
                ),
                encoding="utf-8",
            )
            batch = publisher.accept_manifest(allocation.status_file)
            publisher.mark_consumed(batch.attempt_id)
            self.staged_write_paths.extend((artifact, append, allocation.status_file))
        return ReviewResult("completed", "converged", 1, pr_url, 3)


def test_three_root_delivery_converges_before_blocked_auto_land(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Target state and review staging stay local while canonical lifecycle converges."""
    workspace = tmp_path / "workspace"
    harness_root = workspace / "runs" / "targets" / "api"
    spec_dir = workspace / "specs" / "911-three-root-delivery"
    harness_root.mkdir(parents=True)
    spec_dir.mkdir(parents=True)
    target, verified_commit = _target_checkout(tmp_path)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: planned\ntargets:\n  - sources/api\n---\n# Three-root delivery\n",
        encoding="utf-8",
    )
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-001 depends=none "
        "target=sources/api\n",
        encoding="utf-8",
    )
    (spec_dir / "fulfillment-report.md").write_text(
        f"---\nverified_commit: {verified_commit}\n---\n# Fulfillment\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("ECHELON_TARGET_REPO_NAME", "api")
    monkeypatch.setenv("ECHELON_TARGET_REPO_PATH", str(target))
    monkeypatch.setenv("ECHELON_IMPLEMENTATION_TARGET", "sources/api")
    monkeypatch.setenv("ECHELON_DECLARED_TARGETS", "sources/api")
    monkeypatch.delenv("ECHELON_TARGET_TASK_IDS", raising=False)
    _PublishingReviewController.staged_write_paths = []

    config = HarnessConfig(
        target_repo="git@example.invalid:example/api.git",
        target_default_branch="main",
        provider="docker",
        pr_host="github",
        visual_tests=VisualTestsConfig(enabled=True, max_iterations=1),
        review_loop=ReviewLoopConfig(enabled=True, max_fix_iterations=1),
    )
    gitops = MagicMock()
    gitops.get_latest_worktree.return_value = str(target)
    intent = RunIntent(
        spec_id="911", mode="semi", max_outer=1, max_inner=1, auto_merge=True
    )
    implementation = ImplementationResult(
        "verified", "verified", 1, 0,
        "https://github.com/example/api/pull/911", 5, None,
    )
    visual = VisualResult("passed", "passed", 1, 2, None)
    transitions: list[str] = []
    original_transition = StateStore.transition

    def record_transition(
        store: StateStore, status: str, *, updates: dict[str, object] | None = None
    ) -> None:
        transitions.append(status)
        original_transition(store, status, updates=updates)

    monkeypatch.setattr(StateStore, "transition", record_transition)

    with patch("harness.skills.run_skill.parse_intent", return_value=intent), \
         patch("harness.skills.run_skill.run_gc"), \
         patch("harness.land.land", return_value=False) as land, \
         patch("harness.coordinator.RalphController") as ralph, \
         patch("harness.coordinator.VisualRalphController") as visual_controller, \
         patch("harness.coordinator.ReviewLoopController", _PublishingReviewController), \
         patch("harness.coordinator.subprocess.run", wraps=subprocess.run) as git_run:
        ralph.return_value.run_loop.return_value = implementation
        visual_controller.return_value.run_loop.return_value = visual
        outcome = run(
            "run 911", provider=MagicMock(), gitops=gitops,
            base_dir=harness_root, config=config, orchestration_root=workspace,
        )

    build_id = current_build_marker(harness_root, "911").read_text(encoding="utf-8")
    state = StateStore(harness_root / "runs" / build_id / "state", "911", "default").read()
    assert outcome.results[0].status == "converged"
    assert outcome.landing.status == "blocked"
    assert read_frontmatter(spec_dir)["status"] == "ready_to_land"
    assert state["status"] == "converged"
    assert state["last_completed_phase"] == "visual"
    checkpoints = [
        status for index, status in enumerate(transitions)
        if index == 0 or status != transitions[index - 1]
    ]
    assert checkpoints == [
        "running", "verified", "validating", "reviewing", "finalizing", "converged"
    ]
    assert all(path.is_relative_to(harness_root / "runs" / build_id / "state")
               for path in _PublishingReviewController.staged_write_paths)
    land.assert_called_once_with(
        "911", project_dir=workspace.resolve(), gitops=gitops,
        harness_root=harness_root.resolve(),
    )
    git_commands = [
        call.args[0] for call in git_run.call_args_list
        if call.args and call.args[0] and call.args[0][0] == "git"
    ]
    assert git_commands
    assert all(command[2] != str(harness_root.resolve()) for command in git_commands)
