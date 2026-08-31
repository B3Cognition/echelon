"""Three-root regression for converged delivery and blocked auto-land."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from harness.build_result import BuildResult
from harness.config import HarnessConfig, ReviewLoopConfig, VisualTestsConfig
from harness.coordinator import StrategyCoordinator
from harness.delivery_results import ImplementationResult, ReviewResult, VisualResult
from harness.escalation import EscalationHandler
from harness.fulfillment_runner import FulfillmentRunner
from harness.llm_build_runner import LlmBuildRunner
from harness.llm_provider import AICodingCliProvider
from harness.mode import ModeController
from harness.paths import current_build_marker
from harness.provider import SandboxHandle, SandboxProvider
from harness.ralph import RalphController
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


def _commit_worktree_changes(worktree_path: str, _message: str) -> str:
    _git(Path(worktree_path), "add", "-A")
    if subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=worktree_path
    ).returncode != 0:
        _git(Path(worktree_path), "commit", "-m", "checkpoint candidate")
    return _git(Path(worktree_path), "rev-parse", "HEAD")


def _real_ralph_for_target(
    tmp_path: Path,
    target: Path,
    build_runner: MagicMock,
) -> tuple[RalphController, AICodingCliProvider, StateStore, Path]:
    workspace = tmp_path / "workspace"
    spec_dir = workspace / "specs" / "spec-001-browser"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: planned\ntargets:\n  - sources/web\n---\n"
        "# Browser journey\n\n## Functional Requirements\n\n"
        "- FR-001: Run the complete browser verification journey.\n",
        encoding="utf-8",
    )
    (spec_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text(
        "- [x] T-001 complexity=standard phase=build req=FR-001 "
        "depends=none target=sources/web\n",
        encoding="utf-8",
    )
    _git(workspace, "init", "-b", "main")
    _git(workspace, "config", "user.name", "Integration Test")
    _git(workspace, "config", "user.email", "integration@example.invalid")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-m", "add browser spec")
    skill_dir = target / ".echelon" / "prosaic" / "commands"
    skill_dir.mkdir(parents=True)
    (skill_dir / "echelon.verify-spec.md").write_text(
        "---\nname: echelon.verify-spec\ndescription: Verify spec\n---\n"
        "verify {{args}}\n",
        encoding="utf-8",
    )
    _git(target, "add", ".")
    _git(target, "commit", "-m", "add fulfillment workflow")

    fulfillment_provider = object.__new__(AICodingCliProvider)
    fulfillment_provider._cli = "codex"
    fulfillment_provider.last_stdout = ""
    fulfillment_provider.last_stderr = ""

    def write_fulfillment(
        _worktree_path: str, _prompt: str, **kwargs: object
    ) -> MagicMock:
        metadata = kwargs["request_metadata"]
        assert isinstance(metadata, dict)
        prompt_metadata = metadata["prompt_metadata"]
        assert isinstance(prompt_metadata, dict)
        verify_run_dir = Path(prompt_metadata["tool_write_paths"][-1])
        (verify_run_dir / "requirement-audit.md").write_text(
            "| ID | Category | Source | Requirement | Acceptance Signal |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | FR | spec.md | Complete browser journey | verify passes |\n",
            encoding="utf-8",
        )
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | package.json | high | host verified |\n",
            encoding="utf-8",
        )
        return MagicMock(exit_code=0)

    fulfillment_provider.run_prompt_result = MagicMock(
        side_effect=write_fulfillment
    )
    fulfillment = FulfillmentRunner(fulfillment_provider)

    harness_root = tmp_path / "target-runtime"
    state_store = StateStore(
        harness_root / "runs" / "build-1" / "state", "spec-001", "default"
    )
    state_store.initialize(
        "build-1",
        "banzai",
        target_repo="web",
        target_path=str(target),
        spec_dir=str(spec_dir),
        spec_file=str(spec_dir / "spec.md"),
        tasks_file=str(spec_dir / "tasks.md"),
        workspace_root=str(workspace),
        source_root=str(target),
        source_id="web",
        implementation_target="sources/web",
        declared_targets=["sources/web"],
        target_task_ids=["T-001"],
    )
    state_store.transition("running")

    sandbox = MagicMock(spec=SandboxProvider)
    sandbox.create.return_value = SandboxHandle("integration", "integration")
    gitops = MagicMock()
    gitops.base_dir = harness_root
    gitops.create_worktree.return_value = str(target)
    gitops.commit.side_effect = _commit_worktree_changes
    gitops.push.return_value = None
    gitops.get_default_branch.return_value = "main"
    gitops.local_merge.return_value = {"pushed": True}
    gitops.create_draft_pr.return_value = "https://example.invalid/pr/1"
    gitops.promote_pr_ready.return_value = None

    controller = RalphController(
        provider=sandbox,
        gitops=gitops,
        state_store=state_store,
        mode_controller=ModeController("banzai"),
        escalation_handler=EscalationHandler(str(harness_root)),
        spec_id="spec-001",
        strategy_id="default",
        config=HarnessConfig(
            target_repo=str(target),
            target_default_branch="main",
            provider="docker",
        ),
        llm_provider=fulfillment_provider,
        llm_build_runner=build_runner,
        fulfillment_runner=fulfillment,
        build_id="build-1",
    )
    return controller, fulfillment_provider, state_store, spec_dir


def test_provider_verification_environment_deferral_converges_via_ralph(
    tmp_path: Path,
) -> None:
    target, _initial_commit = _target_checkout(tmp_path)
    (target / "package.json").write_text(
        json.dumps(
            {
                "name": "browser-journey",
                "version": "1.0.0",
                "scripts": {
                    "test": "python -c 'raise SystemExit(9)'",
                    "verify": "python scripts/verify_journey.py",
                },
            }
        ),
        encoding="utf-8",
    )
    (target / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "browser-journey",
                "version": "1.0.0",
                "lockfileVersion": 3,
                "requires": True,
                "packages": {
                    "": {"name": "browser-journey", "version": "1.0.0"}
                },
            }
        ),
        encoding="utf-8",
    )
    (target / "scripts").mkdir()
    (target / "scripts" / "verify_journey.py").write_text(
        "print('five-stage journey passed')\n", encoding="utf-8"
    )
    _git(target, "add", ".")
    _git(target, "commit", "-m", "add browser journey")

    build_runner = MagicMock(spec=LlmBuildRunner)
    build_runner.exec_build.return_value = BuildResult(
        exit_code=0,
        status="blocked",
        blocker_kind="verification_environment",
        reason="Chromium unavailable in coding sandbox",
        impasse_file=None,
        stdout="",
        stderr="",
        duration_ms=1,
    )
    controller, fulfillment_provider, state_store, _spec_dir = (
        _real_ralph_for_target(tmp_path, target, build_runner)
    )

    result = controller.run_loop(
        max_outer=1, max_inner=1, build_prompt="finish"
    )

    assert result.status == "verified", (result, result.final_verify)
    assert result.termination_reason == "converged"
    evidence_root = (
        state_store.state_dir.parent
        / "evidence"
        / "default"
        / "host-verification"
    )
    latest_pointer = json.loads(
        (evidence_root / "latest.json").read_text(encoding="utf-8")
    )
    receipt = json.loads(
        (evidence_root / latest_pointer["path"]).read_text(encoding="utf-8")
    )
    assert receipt["status"] == "passed"
    assert [stage["command"] for stage in receipt["stages"]] == [
        ["npm", "ci"],
        ["npm", "run", "verify"],
    ]
    assert fulfillment_provider.run_prompt_result.call_count == 1
    prompt_metadata = fulfillment_provider.run_prompt_result.call_args.kwargs[
        "request_metadata"
    ]["prompt_metadata"]
    assert str(evidence_root) in prompt_metadata["tool_read_roots"]
    assert str(evidence_root) not in prompt_metadata["tool_write_paths"]
    assert str(tmp_path / "workspace" / "runs") not in prompt_metadata[
        "tool_write_paths"
    ]


def _review_append(task_ids: tuple[str, ...]) -> str:
    return "\n".join(
        "- [ ] "
        f"{task_id} complexity=standard phase=review-fix req=UNMAPPED depends=none\n\n"
        f"  **Title:** RF1-T{index} - Review follow-up\n"
        for index, task_id in enumerate(task_ids, start=1)
    )


class _PublishingReviewController:
    """Deterministic Phase 3 fake that retains real queued publication."""

    staged_write_paths: list[Path] = []
    completion_calls: list[tuple[str, str]] = []
    phase1_calls_at_consumption: list[int] = []

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
        self._calls = 0

    def run_loop(
        self, *, pr_url: str, worktree_path: str, token_budget: int | None
    ) -> ReviewResult:
        assert Path(worktree_path).is_dir()
        self._calls += 1
        if self._calls > 1:
            return ReviewResult("completed", "converged", 1, pr_url, 3)
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
            self.staged_write_paths.extend((artifact, append, allocation.status_file))
            self.queued_task_ids = batch.task_ids
            self.published_artifacts = batch.artifact_paths
            self.pending_batch_attempt_id = batch.attempt_id
        return ReviewResult("review_fix_queued", "review_fix_queued", 1, pr_url, 3)

    def complete_published_batch(self, pr_url: str, attempt_id: str) -> bool:
        self.completion_calls.append((pr_url, attempt_id))
        self.phase1_calls_at_consumption.append(len(_RecordingRalph.calls))
        with ReviewArtifactPublisher(
            self._spec_dir, self._state_dir, self._strategy_id
        ) as publisher:
            batch = publisher.recover_publication(set())
            assert batch is not None
            assert batch.attempt_id == attempt_id
            publisher.mark_consumed(batch.attempt_id)
        return True


class _RecordingRalph:
    """Deterministic Phase 1 fake that captures durable re-entry context."""

    calls: list[dict[str, object]] = []

    def __init__(self, *, state_store: StateStore, **_: object) -> None:
        self._state_store = state_store

    def run_loop(self, **kwargs: object) -> ImplementationResult:
        self.calls.append(
            {
                "target_task_ids": self._state_store.read()["target_task_ids"],
                "pending_review_reentry": self._state_store.read().get(
                    "pending_review_reentry"
                ),
                "build_prompt": kwargs["build_prompt"],
            }
        )
        return ImplementationResult(
            "verified", "verified", 1, 0,
            "https://github.com/example/api/pull/911", 5, None,
        )


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
    _PublishingReviewController.completion_calls = []
    _PublishingReviewController.phase1_calls_at_consumption = []
    _RecordingRalph.calls = []

    config = HarnessConfig(
        target_repo="git@example.invalid:example/api.git",
        target_default_branch="main",
        provider="docker",
        pr_host="github",
        visual_tests=VisualTestsConfig(enabled=True, max_iterations=1),
        review_loop=ReviewLoopConfig(enabled=True, max_fix_iterations=2),
    )
    gitops = MagicMock()
    gitops.get_latest_worktree.return_value = str(target)
    intent = RunIntent(
        spec_id="911", mode="semi", max_outer=1, max_inner=1, auto_merge=True
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
         patch("harness.coordinator.RalphController", _RecordingRalph), \
         patch("harness.coordinator.VisualRalphController") as visual_controller, \
         patch("harness.coordinator.ReviewLoopController", _PublishingReviewController), \
         patch("harness.coordinator.subprocess.run", wraps=subprocess.run) as git_run:
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
    assert state["last_completed_phase"] == "review"
    checkpoints = [
        status for index, status in enumerate(transitions)
        if index == 0 or status != transitions[index - 1]
    ]
    assert checkpoints == [
        "running", "verified", "validating", "reviewing", "running", "verified",
        "validating", "reviewing", "finalizing", "converged",
    ]
    assert all(path.is_relative_to(harness_root / "runs" / build_id / "state")
               for path in _PublishingReviewController.staged_write_paths)
    assert len(_RecordingRalph.calls) == 2
    batch_task_ids = ("T-002", "T-003", "T-004")
    assert _RecordingRalph.calls[0]["target_task_ids"] == ["T-001"]
    assert _RecordingRalph.calls[1]["target_task_ids"] == ["T-001", *batch_task_ids]
    assert _RecordingRalph.calls[1]["pending_review_reentry"] == {
        "attempt_id": _PublishingReviewController.completion_calls[0][1],
        "task_ids": list(batch_task_ids),
        "artifact_paths": [str(spec_dir / "review-fix-1.md")],
        "phase1_verified": False,
    }
    assert _PublishingReviewController.phase1_calls_at_consumption == [2]
    journal = json.loads(
        (harness_root / "runs" / build_id / "state" / "default-review-publication.json").read_text(
            encoding="utf-8"
        )
    )
    assert journal["consumed"] is True
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


def test_delivery_provisioning_gate_is_scoped_to_each_polyrepo_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _delivery_provisioning_blockers

    workspace = tmp_path / "workspace"
    config_file = workspace / ".echelon" / "config.yml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        "stacks:\n"
        "  selected:\n"
        "    - game-persistence-postgres\n",
        encoding="utf-8",
    )
    missing_target = workspace / "sources" / "api"
    prepared_target = workspace / "sources" / "worker"
    missing_target.mkdir(parents=True)
    prepared_target.mkdir(parents=True)
    (prepared_target / "docker-compose.echelon-verify.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )
    (prepared_target / ".env.echelon-verify.example").write_text(
        "DATABASE_URL=\n", encoding="utf-8"
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)

    missing = _delivery_provisioning_blockers(workspace, missing_target)
    prepared = _delivery_provisioning_blockers(workspace, prepared_target)

    assert len(missing) == 1
    assert "STACK_PROVISIONING_MISSING" in missing[0]
    assert f"echelon stack provision --target {missing_target.resolve()}" in missing[0]
    assert len(prepared) == 1
    assert "STACK_PROVISIONING_PREPARED" in prepared[0]
    assert "start the prepared service manually" in prepared[0].lower()
    assert "DATABASE_URL" in prepared[0]

    monkeypatch.setenv("DATABASE_URL", "postgresql://isolated")

    assert _delivery_provisioning_blockers(workspace, missing_target) == []
    assert _delivery_provisioning_blockers(workspace, prepared_target) == []


def test_multi_target_delivery_runs_ready_target_after_independent_provisioning_block(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.orchestrator import run_multi_target

    workspace = tmp_path / "workspace"
    blocked = workspace / "sources" / "a-blocked"
    ready = workspace / "sources" / "b-ready"
    blocked.mkdir(parents=True)
    ready.mkdir(parents=True)
    spec_dir = workspace / "specs" / "001-provisioning-isolation"
    spec_dir.mkdir(parents=True)
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=api req=FR-001 "
        "depends=none target=sources/a-blocked\n"
        "- [ ] T-002 complexity=standard phase=worker req=FR-002 "
        "depends=none target=sources/b-ready\n",
        encoding="utf-8",
    )
    child = tmp_path / "echelon-child"
    child.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "from pathlib import Path\n"
        "target = Path(os.environ['ECHELON_TARGET_REPO_PATH'])\n"
        "if target.name == 'a-blocked':\n"
        "    print('STACK_PROVISIONING_MISSING: postgres verification is missing')\n"
        "    raise SystemExit(1)\n"
        "(target / 'delivery-ran').write_text('ready target executed\\n')\n",
        encoding="utf-8",
    )
    child.chmod(0o755)

    result = run_multi_target(
        "001-provisioning-isolation",
        [ready, blocked],
        [],
        echelon_bin=str(child),
        workspace_root=workspace,
    )

    assert result == 1
    assert not (blocked / "delivery-ran").exists()
    assert (ready / "delivery-ran").read_text(encoding="utf-8") == (
        "ready target executed\n"
    )
    out = capsys.readouterr().out
    assert "[a-blocked] STACK_PROVISIONING_MISSING" in out
    assert "✗ [a-blocked]: exit 1" in out
    assert "✓ [b-ready]: exit 0" in out


def test_resume_after_completed_review_checkpoint_skips_review_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash between completed review and finalization resumes at finalization."""
    workspace = tmp_path / "workspace"
    harness_root = workspace / "runs" / "targets" / "api"
    spec_dir = workspace / "specs" / "912-review-checkpoint"
    harness_root.mkdir(parents=True)
    spec_dir.mkdir(parents=True)
    target, verified_commit = _target_checkout(tmp_path)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: planned\ntargets:\n  - sources/api\n---\n# Review checkpoint\n",
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

    config = HarnessConfig(
        target_repo="git@example.invalid:example/api.git",
        target_default_branch="main",
        provider="docker",
        pr_host="github",
        review_loop=ReviewLoopConfig(enabled=True, max_fix_iterations=1),
    )
    gitops = MagicMock()
    gitops.get_latest_worktree.return_value = str(target)
    intent = RunIntent(spec_id="912", mode="semi", max_outer=1, max_inner=1)
    implementation = ImplementationResult(
        "verified", "verified", 1, 0,
        "https://github.com/example/api/pull/912", 5, None,
    )
    completed_review = ReviewResult(
        "completed", "converged", 1,
        "https://github.com/example/api/pull/912", 3,
    )
    first = StrategyCoordinator(
        provider=MagicMock(), gitops=gitops, config=config,
        base_dir=harness_root, build_id="build-912", orchestration_root=workspace,
    )

    with patch("harness.coordinator.RalphController") as ralph, \
         patch("harness.coordinator.ReviewLoopController") as review, \
         patch.object(first, "_finalize_delivery", side_effect=RuntimeError("crash")):
        ralph.return_value.run_loop.return_value = implementation
        review.return_value.run_loop.return_value = completed_review
        with pytest.raises(RuntimeError, match="crash"):
            first.start(intent)

        state_store = StateStore(
            harness_root / "runs" / "build-912" / "state", "912", "default"
        )
        checkpoint = state_store.read()
        assert checkpoint["status"] == "finalizing"
        assert checkpoint["last_completed_phase"] == "review"

        resumed = StrategyCoordinator(
            provider=MagicMock(), gitops=gitops, config=config,
            base_dir=harness_root, build_id="build-912", orchestration_root=workspace,
        )
        result = resumed.start(intent)[0]

    assert result.status == "converged"
    assert review.return_value.run_loop.call_count == 1
    assert ralph.return_value.run_loop.call_count == 1
    assert state_store.read()["status"] == "converged"
