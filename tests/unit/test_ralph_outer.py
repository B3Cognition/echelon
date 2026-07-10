"""Tests for RalphController outer loop.

Per T032 task specification:
- Outer loop converges on first iteration
- Outer loop hits cap
- Budget exhaustion terminates loop
- SIGTERM sets interrupted status
- cancel_requested terminates between iterations
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from unittest.mock import MagicMock, patch

import pytest

from harness.config import HarnessConfig, ResourceLimits, NetworkConfig
from harness.documentation_gate import DocumentationGateResult
from harness.escalation import EscalationHandler
from harness.exec_result import ExecResult
from harness.fulfillment_runner import FulfillmentRefreshResult
from harness.loop_result import LoopResult
from harness.mode import ModeController
from harness.provider import (
    Capability,
    SandboxHandle,
    SandboxProvider,
    SandboxSpec,
)
from harness.ralph import RalphController
from harness.state import StateStore
from harness.verify_result import VerifyResult


# === Mock SandboxProvider ===


class MockProvider(SandboxProvider):
    """Mock sandbox provider for testing."""

    def __init__(
        self,
        verify_results: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._exec_count = 0
        self._verify_results = verify_results or []
        self._verify_idx = 0
        self.created = False
        self.destroyed = False

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        self.created = True
        return SandboxHandle(id="mock-sandbox-1", session_id="sess-1")

    def exec(
        self,
        handle: SandboxHandle,
        cmd: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_ms: int = 1_200_000,
    ) -> ExecResult:
        self._exec_count += 1

        # If cmd is verify, return from verify_results
        if "verify" in cmd:
            if self._verify_idx < len(self._verify_results):
                data = self._verify_results[self._verify_idx]
                self._verify_idx += 1
                return ExecResult(
                    exit_code=0 if data.get("passed", False) else 1,
                    stdout=json.dumps(data),
                    stderr="",
                    duration_ms=1000,
                    resource_stats=None,
                )
            return ExecResult(
                exit_code=1,
                stdout=json.dumps({"passed": False, "failures": []}),
                stderr="",
                duration_ms=1000,
                resource_stats=None,
            )

        # Default: build/feedback succeeds
        return ExecResult(
            exit_code=0,
            stdout="ok",
            stderr="",
            duration_ms=1000,
            resource_stats=None,
        )

    def write_file(self, handle: SandboxHandle, path: str, content: bytes) -> None:
        pass

    def read_file(self, handle: SandboxHandle, path: str) -> bytes:
        return b""

    def destroy(self, handle: SandboxHandle) -> None:
        self.destroyed = True


# === Fixtures ===


def _make_config() -> HarnessConfig:
    return HarnessConfig(
        target_repo="git@github.com:test/repo.git",
        target_default_branch="main",
        provider="docker",
    )


def _make_gitops() -> MagicMock:
    gitops = MagicMock()
    gitops.create_worktree.return_value = "/tmp/worktree"
    gitops.destroy_worktree.return_value = None
    gitops.commit.return_value = "abc123"
    gitops.push.return_value = None
    gitops.create_draft_pr.return_value = "https://github.com/test/repo/pull/1"
    gitops.promote_pr_ready.return_value = None
    gitops.base_dir = Path("/tmp/project")
    return gitops


def _make_controller(
    tmp_path: Path,
    verify_results: Optional[List[Dict[str, Any]]] = None,
    mode: str = "semi",
    llm_provider: Optional[Any] = None,
    llm_build_runner: Optional[Any] = None,
    fulfillment_runner: Optional[Any] = None,
) -> tuple:
    config = _make_config()
    provider = MockProvider(verify_results=verify_results)
    gitops = _make_gitops()
    state_store = StateStore(tmp_path, "spec-001", "default")
    mode_controller = ModeController(mode)
    escalation_handler = EscalationHandler(str(tmp_path / "harness"))

    state_store.initialize("run-1", mode)
    state_store.transition("running")

    controller = RalphController(
        provider=provider,
        gitops=gitops,
        state_store=state_store,
        mode_controller=mode_controller,
        escalation_handler=escalation_handler,
        spec_id="spec-001",
        strategy_id="default",
        config=config,
        llm_provider=llm_provider,
        llm_build_runner=llm_build_runner,
        fulfillment_runner=fulfillment_runner,
    )
    return controller, provider, gitops, state_store


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


def _commit_all(path: Path, message: str = "base") -> None:
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=path, check=True, capture_output=True)


def _write_no_impact_documentation_report(spec_dir: Path) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "documentation-impact-report.md").write_text(
        "---\n"
        "docs_required: false\n"
        "readme_updated: false\n"
        "changelog_updated: false\n"
        "changelog_format: not_required\n"
        'not_applicable_reason: "Fixture build has no user-visible documentation impact."\n'
        "---\n"
        "# Documentation Impact Report\n",
        encoding="utf-8",
    )


@pytest.mark.unit
class TestOuterLoopConvergence:
    """Test outer loop converges on first iteration."""

    def test_sync_phase_a_inputs_overwrites_stale_worktree_constitution(
        self, tmp_path: Path
    ) -> None:
        controller, _provider, gitops, state_store = _make_controller(tmp_path)
        project = tmp_path / "project"
        gitops.base_dir = project
        source = project / "specs" / "spec-001-demo"
        source.mkdir(parents=True)
        for name in ("spec.md", "plan.md", "research.md", "data-model.md"):
            (source / name).write_text(f"# {name}\n", encoding="utf-8")
        (source / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=build req=FR-001 depends=none\n",
            encoding="utf-8",
        )
        (source / "constitution.md").write_text(
            "# Real Constitution\n\nProject-specific governance.\n",
            encoding="utf-8",
        )
        canonical = project / ".specify" / "memory" / "constitution.md"
        canonical.parent.mkdir(parents=True)
        canonical.write_text("# Real Constitution\n", encoding="utf-8")

        worktree = tmp_path / "worktree"
        stale = worktree / "specs" / "spec-001-demo"
        stale.mkdir(parents=True)
        (stale / "constitution.md").write_text(
            "# [PROJECT_NAME] Constitution\n\n[PRINCIPLE_1_NAME]\n",
            encoding="utf-8",
        )
        stale_canonical = worktree / ".specify" / "memory" / "constitution.md"
        stale_canonical.parent.mkdir(parents=True)
        stale_canonical.write_text("# [PROJECT_NAME] Constitution\n", encoding="utf-8")

        state = state_store.read()
        state["spec_dir"] = str(source)
        state_store.write(state)

        blockers = controller._sync_phase_a_inputs_into_worktree(worktree)

        assert blockers == []
        assert "[PROJECT_NAME]" not in (stale / "constitution.md").read_text(encoding="utf-8")
        assert "Real Constitution" in (stale / "constitution.md").read_text(encoding="utf-8")
        assert "[PROJECT_NAME]" not in stale_canonical.read_text(encoding="utf-8")

    def test_sync_phase_a_inputs_reconciles_state_task_progress(
        self, tmp_path: Path
    ) -> None:
        controller, _provider, gitops, state_store = _make_controller(tmp_path)
        project = tmp_path / "project"
        gitops.base_dir = project
        source = project / "specs" / "spec-001-demo"
        source.mkdir(parents=True)
        for name in ("spec.md", "plan.md", "research.md", "data-model.md"):
            (source / name).write_text(f"# {name}\n", encoding="utf-8")
        (source / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n"
            "\n"
            "  **Acceptance Criteria:**\n"
            "  - [ ] Gate passes\n"
            "\n"
            "- [ ] T-002 complexity=standard phase=core req=FR-001 depends=T-001\n",
            encoding="utf-8",
        )
        (source / "constitution.md").write_text(
            "# Real Constitution\n\nProject-specific governance.\n",
            encoding="utf-8",
        )
        canonical = project / ".specify" / "memory" / "constitution.md"
        canonical.parent.mkdir(parents=True)
        canonical.write_text("# Real Constitution\n", encoding="utf-8")

        state = state_store.read()
        state["spec_dir"] = str(source)
        state["build"] = {
            "total_tasks": 2,
            "completed_tasks": 1,
            "tasks_completed_pct": 50,
            "task_results": {
                "T-001": {"status": "DONE"},
                "T-002": {"status": "PENDING"},
            },
        }
        state_store.write(state)

        worktree = tmp_path / "worktree"
        blockers = controller._sync_phase_a_inputs_into_worktree(worktree)

        assert blockers == []
        synced_tasks = worktree / "specs" / "spec-001-demo" / "tasks.md"
        text = synced_tasks.read_text(encoding="utf-8")
        assert "- [x] T-001 complexity=standard phase=foundation req=INFRA depends=none" in text
        assert "  **Status:** DONE" in text
        assert "  - [x] Gate passes" in text
        assert "- [ ] T-002 complexity=standard phase=core req=FR-001 depends=T-001" in text

    def test_sync_phase_a_inputs_blocks_invalid_worktree_copy(
        self, tmp_path: Path
    ) -> None:
        controller, _provider, gitops, state_store = _make_controller(tmp_path)
        project = tmp_path / "project"
        gitops.base_dir = project
        source = project / "specs" / "spec-001-demo"
        source.mkdir(parents=True)
        for name in ("spec.md", "plan.md", "research.md", "data-model.md", "tasks.md"):
            (source / name).write_text(f"# {name}\n", encoding="utf-8")
        (source / "constitution.md").write_text(
            "# [PROJECT_NAME] Constitution\n",
            encoding="utf-8",
        )

        state = state_store.read()
        state["spec_dir"] = str(source)
        state_store.write(state)

        blockers = controller._sync_phase_a_inputs_into_worktree(tmp_path / "worktree")

        assert any("constitution.md contains unresolved template markers" in blocker for blocker in blockers)

    def test_harness_context_uses_worktree_spec_paths_for_single_repo_runs(
        self, tmp_path: Path
    ) -> None:
        """Single-repo builds must not leak spec edits into the live project."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        live_spec_dir = tmp_path / "live-project" / "specs" / "spec-001-demo"
        live_spec_dir.mkdir(parents=True)
        (live_spec_dir / "spec.md").write_text("# Live Spec\n", encoding="utf-8")
        (live_spec_dir / "tasks.md").write_text("# Live Tasks\n", encoding="utf-8")

        worktree = tmp_path / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        worktree_spec_dir = worktree / "specs" / "spec-001-demo"
        worktree_spec_dir.mkdir(parents=True)
        (worktree_spec_dir / "spec.md").write_text("# Worktree Spec\n", encoding="utf-8")
        (worktree_spec_dir / "tasks.md").write_text("# Worktree Tasks\n", encoding="utf-8")

        state = state_store.read()
        state["spec_dir"] = str(live_spec_dir)
        state["spec_file"] = str(live_spec_dir / "spec.md")
        state["tasks_file"] = str(live_spec_dir / "tasks.md")
        state_store.write(state)

        prompt = controller._with_harness_context("body", str(worktree))

        assert "spec_artifacts_mode: worktree" in prompt
        assert f"spec_dir: {worktree_spec_dir}" in prompt
        assert f"spec_file: {worktree_spec_dir / 'spec.md'}" in prompt
        assert f"tasks_file: {worktree_spec_dir / 'tasks.md'}" in prompt
        assert str(live_spec_dir) not in prompt

    def test_harness_context_materializes_state_spec_in_worktree_mode(
        self, tmp_path: Path
    ) -> None:
        """Worktree-mode prompts materialize Python-owned specs into the worktree."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        live_spec_dir = tmp_path / "live-project" / "specs" / "spec-001-demo"
        live_spec_dir.mkdir(parents=True)
        (live_spec_dir / "spec.md").write_text("# Live Spec\n", encoding="utf-8")
        (live_spec_dir / "tasks.md").write_text("# Live Tasks\n", encoding="utf-8")
        worktree = tmp_path / "live-project" / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        worktree.mkdir(parents=True)

        state = state_store.read()
        state["spec_dir"] = str(live_spec_dir)
        state["spec_file"] = str(live_spec_dir / "spec.md")
        state["tasks_file"] = str(live_spec_dir / "tasks.md")
        state_store.write(state)

        prompt = controller._with_harness_context("body", str(worktree))
        worktree_spec_dir = worktree / "specs" / "spec-001-demo"

        assert "spec_artifacts_mode: worktree" in prompt
        assert f"spec_dir: {worktree_spec_dir}" in prompt
        assert f"spec_file: {worktree_spec_dir / 'spec.md'}" in prompt
        assert f"tasks_file: {worktree_spec_dir / 'tasks.md'}" in prompt
        assert (worktree_spec_dir / "tasks.md").read_text(encoding="utf-8") == "# Live Tasks\n"
        assert str(live_spec_dir) not in prompt

    def test_harness_context_does_not_expose_harness_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        controller, _provider, _gitops, _state_store = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        harness_source = tmp_path / "echelon" / "src" / "harness"
        monkeypatch.setenv("HARNESS_SOURCE_DIR", str(harness_source))

        prompt = controller._with_harness_context("body", str(worktree))

        assert str(harness_source) not in prompt
        assert "harness_source_dir" not in prompt
        assert "Do not inspect, read, or search for harness source" in prompt
        assert "Ralph owns harness decisions" in prompt

    def test_harness_context_labels_dirty_verify_owned_artifacts(
        self, tmp_path: Path
    ) -> None:
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=worktree,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=worktree,
            check=True,
        )
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
        (spec_dir / "fulfillment-report.md").write_text("old\n", encoding="utf-8")
        (worktree / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)
        (spec_dir / "fulfillment-report.md").write_text("new\n", encoding="utf-8")
        (spec_dir / "fulfillment-gaps.md").write_text("gap\n", encoding="utf-8")

        prompt = controller._with_harness_context("body", str(worktree))

        assert "dirty_verify_artifacts:" in prompt
        assert "specs/spec-001-demo/fulfillment-report.md" in prompt
        assert "specs/spec-001-demo/fulfillment-gaps.md" in prompt
        assert "Treat these as inherited verify-spec outputs" in prompt
        state = state_store.read()
        assert state["dirty_verify_artifacts"]["count"] == 2
        assert "specs/spec-001-demo/fulfillment-report.md" in state[
            "dirty_verify_artifacts"
        ]["paths"]

    def test_harness_context_does_not_label_source_changes_as_verify_artifacts(
        self, tmp_path: Path
    ) -> None:
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=worktree,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=worktree,
            check=True,
        )
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
        source_dir = worktree / "src"
        source_dir.mkdir()
        (source_dir / "feature.swift").write_text("new\n", encoding="utf-8")

        prompt = controller._with_harness_context("body", str(worktree))

        assert "dirty_verify_artifacts:" not in prompt
        assert "dirty_verify_artifacts" not in state_store.read()

    def test_harness_context_uses_state_owned_spec_paths(self, tmp_path: Path) -> None:
        """Polyrepo builds may keep spec artifacts outside the target worktree."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        spec_dir = tmp_path / "orchestration-root" / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        spec_file = spec_dir / "spec.md"
        tasks_file = spec_dir / "tasks.md"
        spec_file.write_text("# Spec\n", encoding="utf-8")
        tasks_file.write_text("# Tasks\n", encoding="utf-8")
        state = state_store.read()
        state["spec_dir"] = str(spec_dir)
        state["spec_file"] = str(spec_file)
        state["tasks_file"] = str(tasks_file)
        state["target_repo"] = "target-app"
        state["target_path"] = str(tmp_path / "target-root")
        state_store.write(state)

        prompt = controller._with_harness_context(
            "body",
            str(tmp_path / "target-root" / "worktree-without-specs"),
        )

        assert "spec_artifacts_mode: external" in prompt
        assert f"spec_dir: {spec_dir}" in prompt
        assert f"spec_file: {spec_file}" in prompt
        assert f"tasks_file: {tasks_file}" in prompt
        assert "spec_dir: MISSING" not in prompt

    def test_external_harness_context_keeps_spec_artifacts_read_only(
        self, tmp_path: Path
    ) -> None:
        """Target builds must report task IDs instead of editing external tasks.md."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        spec_dir = tmp_path / "workspace" / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text("- [ ] T-001 req=FR-001\n", encoding="utf-8")
        state = state_store.read()
        state["target_repo"] = "target-app"
        state["target_path"] = str(tmp_path / "workspace" / "sources" / "target-app")
        state["spec_dir"] = str(spec_dir)
        state["spec_file"] = str(spec_dir / "spec.md")
        state["tasks_file"] = str(spec_dir / "tasks.md")
        state_store.write(state)

        prompt = controller._with_harness_context(
            "body",
            str(tmp_path / "workspace" / "runs" / "targets" / "target-app" / "worktree"),
        )

        assert "spec_artifacts_mode: external" in prompt
        assert "read-only inputs" in prompt
        assert "Do not edit `tasks_file`" in prompt
        assert "completed_task_ids" in prompt
        assert "progress/report updates" not in prompt
        assert "external `spec_dir` path" not in prompt

    def test_harness_context_names_workspace_and_source_roots(self, tmp_path: Path) -> None:
        """Build prompts must distinguish orchestration workspace from source root."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        source = workspace / "og-platform"
        source.mkdir(parents=True)

        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["workspace_git_role"] = "orchestration"
        state["source_root"] = str(source)
        state["source_id"] = "og-platform"
        state["source_git_role"] = "source"
        state_store.write(state)

        prompt = controller._with_harness_context("body", str(source))

        assert f"workspace_root: {workspace}" in prompt
        assert "workspace_git_role: orchestration" in prompt
        assert f"source_root: {source}" in prompt
        assert "source_id: og-platform" in prompt
        assert "source_git_role: source" in prompt
        assert "forbidden_source_roots:" not in prompt

    def test_harness_context_reports_forbidden_sibling_source_roots(
        self, tmp_path: Path
    ) -> None:
        """Targeted delivery prompts must identify sibling sources as off-limits."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        target = workspace / "sources" / "prosaic"
        sibling_a = workspace / "sources" / "ruler"
        sibling_b = workspace / "sources" / "spec-kit-skills-agents"
        worktree = (
            tmp_path
            / "runs"
            / "targets"
            / "prosaic"
            / "runs"
            / "build-1"
            / "worktrees"
            / "default"
            / "iter-0"
        )
        for path in (target, sibling_a, sibling_b, worktree):
            path.mkdir(parents=True)

        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["workspace_git_role"] = "workspace"
        state["source_root"] = str(target)
        state["target_path"] = str(target)
        state["source_id"] = "prosaic"
        state["source_git_role"] = "source"
        state_store.write(state)

        prompt = controller._with_harness_context("body", str(worktree))

        assert "forbidden_source_roots:" in prompt
        assert f"- {sibling_a}" in prompt
        assert f"- {sibling_b}" in prompt
        forbidden_block = prompt.split("forbidden_source_roots:", 1)[1].split(
            "Use `worktree`",
            1,
        )[0]
        assert str(target) not in forbidden_block
        assert "Do not inspect, read, list, grep, or search sibling source roots" in prompt

    def test_harness_context_writes_delivery_containment_policy(
        self, tmp_path: Path
    ) -> None:
        """Targeted delivery must expose roots as a Python-owned policy artifact."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        target = workspace / "sources" / "prosaic"
        sibling = workspace / "sources" / "ruler"
        spec_dir = workspace / "specs" / "001-prosaic"
        worktree = (
            tmp_path
            / "runs"
            / "targets"
            / "prosaic"
            / "runs"
            / "build-1"
            / "worktrees"
            / "default"
            / "iter-0"
        )
        for path in (target, sibling, spec_dir, worktree):
            path.mkdir(parents=True)

        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["workspace_git_role"] = "workspace"
        state["source_root"] = str(target)
        state["target_path"] = str(target)
        state["source_id"] = "prosaic"
        state["source_git_role"] = "source"
        state["spec_dir"] = str(spec_dir)
        state_store.write(state)

        prompt = controller._with_harness_context("body", str(worktree))

        policy_file = state_store.state_dir / "delivery-containment-policy.json"
        policy = json.loads(policy_file.read_text(encoding="utf-8"))
        assert f"containment_policy_file: {policy_file}" in prompt
        assert policy["workspace_root"] == str(workspace)
        assert policy["source_root"] == str(target)
        assert policy["worktree"] == str(worktree)
        assert policy["allowed_roots"]["implementation"] == [str(worktree)]
        assert str(spec_dir) in policy["allowed_roots"]["spec_inputs"]
        assert str(state_store.state_dir) in policy["allowed_roots"]["harness_state"]
        assert policy["allowed_roots"]["orchestration"] == []
        assert policy["forbidden_source_roots"] == [str(sibling)]

    def test_harness_context_includes_delivery_progress_ledger(
        self, tmp_path: Path
    ) -> None:
        """Resumed build prompts must not force agents to rediscover completed work."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        state = state_store.read()
        state["build"] = {
            "total_tasks": 157,
            "completed_tasks": 20,
            "tasks_completed_pct": 13,
            "task_results": {
                "T-095": {"status": "DONE"},
                "T-096": {"status": "DONE"},
                "T-104": {"status": "DONE"},
                "T-105": {"status": "DONE"},
            },
        }
        state["checkpoint_commits"] = [
            {
                "commit": "7ba6d73cb75e22c93378fa56fc04c6bc241b6326",
                "outer_iter": 0,
                "phase": "build",
                "task_ids": ["T-095", "T-096"],
            },
            {
                "commit": "452ab3d5727b9eea9aa2080eaf65235e3229538e",
                "outer_iter": 2,
                "phase": "build",
                "task_ids": ["T-104", "T-105"],
            },
        ]
        state_store.write(state)

        prompt = controller._with_harness_context("body", str(worktree))

        assert "## Delivery Progress Ledger" in prompt
        assert "completed_tasks: 20/157 (13%)" in prompt
        assert "completed_task_ids: T-095, T-096, T-104, T-105" in prompt
        assert "checkpoint_commits:" in prompt
        assert "- 7ba6d73cb75e outer=0 phase=build tasks=T-095,T-096" in prompt
        assert "- 452ab3d5727b outer=2 phase=build tasks=T-104,T-105" in prompt
        assert "Do not redo completed_task_ids" in prompt
        assert "Select only unchecked/open canonical tasks" in prompt
        assert "Stale or scoped fulfillment reports are Ralph-owned evidence refresh context" in prompt

    def test_harness_context_writes_build_slice_context_artifact(
        self, tmp_path: Path
    ) -> None:
        """Build agents should receive a prepared context artifact, not reassemble it."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        worktree = workspace / "sources" / "prosaic"
        spec_dir = workspace / "specs" / "001-prosaic"
        worktree.mkdir(parents=True)
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [x] T-001 complexity=standard phase=base req=FR-001 depends=none\n"
            "- [ ] T-002 complexity=standard phase=ui req=FR-002 depends=T-001\n",
            encoding="utf-8",
        )
        (spec_dir / "spec.md").write_text(
            "## Requirements\n\n"
            "- **FR-001**: Already implemented.\n"
            "- **FR-002**: Render the deployment preview.\n",
            encoding="utf-8",
        )

        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["workspace_git_role"] = "workspace"
        state["source_root"] = str(worktree)
        state["target_path"] = str(worktree)
        state["source_id"] = "prosaic"
        state["source_git_role"] = "source"
        state["spec_dir"] = str(spec_dir)
        state["build"] = {
            "total_tasks": 2,
            "completed_tasks": 1,
            "current_task": "T-002",
            "current_phase_group": "phase-ui",
            "task_results": {"T-001": {"status": "DONE"}},
        }
        state_store.write(state)

        prompt = controller._with_harness_context("body", str(worktree))

        context_file = state_store.state_dir.parent / "context" / "default-build-slice-context.md"
        context_index_file = (
            state_store.state_dir.parent / "context" / "default-build-slice-context.json"
        )
        assert f"build_slice_context_file: {context_file}" in prompt
        assert f"build_slice_context_index_file: {context_index_file}" in prompt
        implementer_context_file = (
            state_store.state_dir.parent / "context" / "default-implementer-context.md"
        )
        assert f"build_implementer_context_file: {implementer_context_file}" in prompt
        assert "Read `build_implementer_context_file` before implementation" in prompt
        assert "Read `build_slice_context_file` before implementation" in prompt
        context = context_file.read_text(encoding="utf-8")
        assert "# Build Slice Context" in context
        assert "## Current Build Slice" in context
        assert "- current_task_ids: T-002" in context
        assert "- current_phase_group: phase-ui" in context
        assert (
            "- current_task_row: - [ ] T-002 complexity=standard phase=ui req=FR-002 depends=T-001"
            in context
        )
        assert "- current_requirements: FR-002" in context
        assert "## Current Requirement Excerpts" in context
        assert "- FR-002 (spec.md:4): - **FR-002**: Render the deployment preview." in context
        assert "FR-001 (spec.md" not in context
        assert f"- worktree: `{worktree}`" in context
        assert f"- spec_dir: `{spec_dir}`" in context
        assert "completed_tasks: 1/2" in context
        assert "completed_task_ids: T-001" in context
        context_index = json.loads(context_index_file.read_text(encoding="utf-8"))
        assert context_index["version"] == 1
        assert context_index["markdown_path"] == str(context_file)
        assert context_index["spec_dir"] == str(spec_dir)
        assert "Current Build Slice" in context_index["sections"]
        assert "Current Requirement Excerpts" in context_index["sections"]
        assert (
            "- current_task_ids: T-002"
            in context_index["section_blocks"]["Current Build Slice"]
        )
        assert (
            "- FR-002 (spec.md:4): - **FR-002**: Render the deployment preview."
            in context_index["section_blocks"]["Current Requirement Excerpts"]
        )
        assert context_index["agent_sections"]["IMPLEMENTER"] == [
            "Roots",
            "Spec Inputs",
            "Current Build Slice",
            "Current Requirement Excerpts",
            "Candidate Open Task Rows",
            "Referenced Requirement Excerpts",
            "Build Rules",
        ]
        assert context_index["agent_context_files"]["IMPLEMENTER"] == str(
            implementer_context_file
        )
        implementer_context = implementer_context_file.read_text(encoding="utf-8")
        assert "# IMPLEMENTER Context Pack" in implementer_context
        assert "## Current Build Slice" in implementer_context
        assert "- current_task_ids: T-002" in implementer_context
        assert "## Current Requirement Excerpts" in implementer_context
        assert "## Build Rules" in implementer_context
        for agent_name, filename in (
            ("SPEC_GUARD", "default-spec-guard-context.md"),
            ("CODE_REVIEWER", "default-code-reviewer-context.md"),
            ("TEST_GUARDIAN", "default-test-guardian-context.md"),
            ("TECH_WRITER", "default-tech-writer-context.md"),
            ("DOCS_VERIFIER", "default-docs-verifier-context.md"),
            ("PROGRESS_TRACKER", "default-progress-tracker-context.md"),
            ("INTEGRATOR", "default-integrator-context.md"),
            ("VISUAL_VALIDATOR", "default-visual-validator-context.md"),
            ("ENGINEERING_MANAGER", "default-engineering-manager-context.md"),
            ("VERIFICATION", "default-verification-context.md"),
        ):
            agent_context_file = state_store.state_dir.parent / "context" / filename
            assert context_index["agent_context_files"][agent_name] == str(
                agent_context_file
            )
            agent_context = agent_context_file.read_text(encoding="utf-8")
            assert f"# {agent_name} Context Pack" in agent_context
            assert "## Current Build Slice" in agent_context
            assert "## Current Requirement Excerpts" in agent_context
            assert "## Build Rules" in agent_context
        assert "Do not search for the application repo" in prompt

    def test_build_slice_context_includes_bounded_open_task_rows(
        self, tmp_path: Path
    ) -> None:
        """Prepared context should name candidate task rows without scanning all tasks."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        worktree = workspace / "sources" / "prosaic"
        spec_dir = workspace / "specs" / "001-prosaic"
        worktree.mkdir(parents=True)
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [x] T-001 complexity=standard phase=base req=FR-001 depends=none\n"
            "- [ ] T-002 [P] complexity=standard phase=base req=FR-002 depends=T-001\n"
            "- [ ] T-003 complexity=complex phase=ui req=FR-003,FR-004 depends=T-002\n",
            encoding="utf-8",
        )

        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["source_root"] = str(worktree)
        state["target_path"] = str(worktree)
        state["spec_dir"] = str(spec_dir)
        state_store.write(state)

        controller._with_harness_context("body", str(worktree))

        context_file = state_store.state_dir.parent / "context" / "default-build-slice-context.md"
        context = context_file.read_text(encoding="utf-8")
        assert "## Candidate Open Task Rows" in context
        assert "- [ ] T-002 [P] complexity=standard phase=base req=FR-002 depends=T-001" in context
        assert "- [ ] T-003 complexity=complex phase=ui req=FR-003,FR-004 depends=T-002" in context
        assert "- [x] T-001" not in context

    def test_build_slice_context_includes_referenced_requirement_excerpts(
        self, tmp_path: Path
    ) -> None:
        """Prepared context should include requirement lines referenced by open tasks."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        worktree = workspace / "sources" / "prosaic"
        spec_dir = workspace / "specs" / "001-prosaic"
        worktree.mkdir(parents=True)
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "## Requirements\n\n"
            "- **FR-001**: Already delivered behavior.\n"
            "- **FR-002**: Deploy markdown agents to Codex.\n"
            "- **FR-003**: Rewrite frontmatter for target tools.\n",
            encoding="utf-8",
        )
        (spec_dir / "tasks.md").write_text(
            "- [x] T-001 complexity=standard phase=base req=FR-001 depends=none\n"
            "- [ ] T-002 complexity=standard phase=base req=FR-002,FR-003 depends=T-001\n",
            encoding="utf-8",
        )

        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["source_root"] = str(worktree)
        state["target_path"] = str(worktree)
        state["spec_dir"] = str(spec_dir)
        state_store.write(state)

        controller._with_harness_context("body", str(worktree))

        context_file = state_store.state_dir.parent / "context" / "default-build-slice-context.md"
        context = context_file.read_text(encoding="utf-8")
        assert "## Referenced Requirement Excerpts" in context
        assert "- FR-002 (spec.md:4): - **FR-002**: Deploy markdown agents to Codex." in context
        assert "- FR-003 (spec.md:5): - **FR-003**: Rewrite frontmatter for target tools." in context
        assert "FR-001 (spec.md" not in context

    def test_build_slice_context_includes_spec_adjacent_artifact_excerpts(
        self, tmp_path: Path
    ) -> None:
        """Prepared context should list bounded spec-adjacent artifacts to read."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        worktree = workspace / "sources" / "prosaic"
        spec_dir = workspace / "specs" / "001-prosaic"
        contracts_dir = spec_dir / "contracts"
        adrs_dir = spec_dir / "adrs"
        constitution_path = workspace / ".specify" / "memory" / "constitution.md"
        worktree.mkdir(parents=True)
        contracts_dir.mkdir(parents=True)
        adrs_dir.mkdir(parents=True)
        constitution_path.parent.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-002 complexity=standard phase=base req=FR-002 depends=none\n",
            encoding="utf-8",
        )
        (spec_dir / "plan.md").write_text(
            "# Plan\n\nUse a TypeScript CLI with file-system adapters.\n",
            encoding="utf-8",
        )
        (spec_dir / "test-strategy.md").write_text(
            "# Testing Strategy\n\nRun unit tests before package builds.\n",
            encoding="utf-8",
        )
        (spec_dir / "data-model.md").write_text(
            "# Data Model\n\nArtifactMapping stores source and target paths.\n",
            encoding="utf-8",
        )
        (contracts_dir / "cli.md").write_text(
            "# CLI Contract\n\n`prosaic deploy --dry-run` reports planned writes.\n",
            encoding="utf-8",
        )
        (adrs_dir / "001-transformer-boundaries.md").write_text(
            "# ADR-001: Transformer Boundaries\n\nKeep target adapters isolated.\n",
            encoding="utf-8",
        )
        constitution_path.write_text(
            "# Constitution\n\nPrefer deterministic orchestration over model-owned discovery.\n",
            encoding="utf-8",
        )

        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["source_root"] = str(worktree)
        state["target_path"] = str(worktree)
        state["spec_dir"] = str(spec_dir)
        state_store.write(state)

        controller._with_harness_context("body", str(worktree))

        context_file = state_store.state_dir.parent / "context" / "default-build-slice-context.md"
        context = context_file.read_text(encoding="utf-8")
        assert "## Spec-Adjacent Artifact Excerpts" in context
        assert f"- plan.md: `{spec_dir / 'plan.md'}`" in context
        assert "  - Use a TypeScript CLI with file-system adapters." in context
        assert f"- test-strategy.md: `{spec_dir / 'test-strategy.md'}`" in context
        assert "  - Run unit tests before package builds." in context
        assert f"- data-model.md: `{spec_dir / 'data-model.md'}`" in context
        assert "  - ArtifactMapping stores source and target paths." in context
        assert f"- contracts/cli.md: `{contracts_dir / 'cli.md'}`" in context
        assert "  - `prosaic deploy --dry-run` reports planned writes." in context
        assert (
            f"- adrs/001-transformer-boundaries.md: "
            f"`{adrs_dir / '001-transformer-boundaries.md'}`"
            in context
        )
        assert "  - Keep target adapters isolated." in context
        assert f"- .specify/memory/constitution.md: `{constitution_path}`" in context
        assert (
            "  - Prefer deterministic orchestration over model-owned discovery."
            in context
        )

    def test_build_slice_context_includes_quality_commands(
        self, tmp_path: Path
    ) -> None:
        """Prepared context should name the deterministic verification command."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        worktree = workspace / "sources" / "prosaic"
        spec_dir = workspace / "specs" / "001-prosaic"
        worktree.mkdir(parents=True)
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-002 complexity=standard phase=base req=FR-002 depends=none\n",
            encoding="utf-8",
        )
        controller._config.verify_command = "npm test && npm run build"

        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["source_root"] = str(worktree)
        state["target_path"] = str(worktree)
        state["spec_dir"] = str(spec_dir)
        state_store.write(state)

        controller._with_harness_context("body", str(worktree))

        context_file = state_store.state_dir.parent / "context" / "default-build-slice-context.md"
        context = context_file.read_text(encoding="utf-8")
        assert "## Quality Commands" in context
        assert "- verify_command: `npm test && npm run build`" in context
        assert "Run this from `worktree` before reporting completed_task_ids" in context

    def test_build_slice_context_includes_last_verify_failures(
        self, tmp_path: Path
    ) -> None:
        """Prepared context should carry Ralph-owned verify failures forward."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        worktree = workspace / "sources" / "prosaic"
        spec_dir = workspace / "specs" / "001-prosaic"
        worktree.mkdir(parents=True)
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-002 complexity=standard phase=base req=FR-002 depends=none\n",
            encoding="utf-8",
        )

        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["source_root"] = str(worktree)
        state["target_path"] = str(worktree)
        state["spec_dir"] = str(spec_dir)
        state["last_verify_result"] = {
            "passed": False,
            "failures": [
                {
                    "category": "test",
                    "id": "unit-tests",
                    "error": "npm test failed: expected 3 writes, got 2",
                },
                {
                    "category": "other",
                    "id": "fulfillment-report-stale",
                    "error": "Ralph must refresh fulfillment evidence before convergence.",
                },
            ],
        }
        state_store.write(state)

        controller._with_harness_context("body", str(worktree))

        context_file = state_store.state_dir.parent / "context" / "default-build-slice-context.md"
        context = context_file.read_text(encoding="utf-8")
        assert "## Last Verify Failures" in context
        assert "- [test] unit-tests: npm test failed: expected 3 writes, got 2" in context
        assert (
            "- [other] fulfillment-report-stale: Ralph must refresh fulfillment evidence before convergence."
            in context
        )

    def test_build_slice_context_includes_target_git_state(
        self, tmp_path: Path
    ) -> None:
        """Prepared context should summarize target git state without agent discovery."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        worktree = workspace / "sources" / "prosaic"
        spec_dir = workspace / "specs" / "001-prosaic"
        worktree.mkdir(parents=True)
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-002 complexity=standard phase=base req=FR-002 depends=none\n",
            encoding="utf-8",
        )
        (worktree / "src").mkdir()
        (worktree / "src" / "index.ts").write_text("export const x = 1\n", encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True, capture_output=True)
        subprocess.run(["git", "add", "src/index.ts"], cwd=worktree, check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Echelon Test",
                "-c",
                "user.email=echelon@example.invalid",
                "commit",
                "-m",
                "initial",
            ],
            cwd=worktree,
            check=True,
            capture_output=True,
        )
        head = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=worktree,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        (worktree / "src" / "index.ts").write_text("export const x = 2\n", encoding="utf-8")

        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["source_root"] = str(worktree)
        state["target_path"] = str(worktree)
        state["spec_dir"] = str(spec_dir)
        state_store.write(state)

        controller._with_harness_context("body", str(worktree))

        context_file = state_store.state_dir.parent / "context" / "default-build-slice-context.md"
        context = context_file.read_text(encoding="utf-8")
        assert "## Target Git State" in context
        assert "- branch: `main`" in context
        assert f"- head: `{head}`" in context
        assert "- recent commits:" in context
        assert f"  - {head} initial" in context
        assert "- status: dirty (1 path)" in context
        assert "  - M src/index.ts" in context

    def test_build_slice_context_includes_target_package_manifest(
        self, tmp_path: Path
    ) -> None:
        """Prepared context should summarize target package scripts deterministically."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        worktree = workspace / "sources" / "prosaic"
        spec_dir = workspace / "specs" / "001-prosaic"
        worktree.mkdir(parents=True)
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-002 complexity=standard phase=base req=FR-002 depends=none\n",
            encoding="utf-8",
        )
        (worktree / "package.json").write_text(
            json.dumps(
                {
                    "name": "prosaic",
                    "version": "0.1.0",
                    "main": "dist/index.js",
                    "types": "dist/index.d.ts",
                    "bin": {
                        "prosaic": "dist/cli.js",
                    },
                    "dependencies": {
                        "commander": "^12.0.0",
                        "yaml": "^2.5.0",
                    },
                    "devDependencies": {
                        "typescript": "^5.5.0",
                        "jest": "^29.0.0",
                    },
                    "scripts": {
                        "build": "tsc -p tsconfig.json",
                        "test": "jest",
                    },
                }
            ),
            encoding="utf-8",
        )
        (worktree / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["source_root"] = str(worktree)
        state["target_path"] = str(worktree)
        state["spec_dir"] = str(spec_dir)
        state_store.write(state)

        controller._with_harness_context("body", str(worktree))

        context_file = state_store.state_dir.parent / "context" / "default-build-slice-context.md"
        context = context_file.read_text(encoding="utf-8")
        assert "## Target Manifest Excerpts" in context
        assert "- package.json: name=`prosaic`, version=`0.1.0`" in context
        assert "  - package_manager: `pnpm` (lockfile: `pnpm-lock.yaml`)" in context
        assert "  - main: `dist/index.js`" in context
        assert "  - types: `dist/index.d.ts`" in context
        assert "  - bin prosaic: `dist/cli.js`" in context
        assert "  - dependencies: commander, yaml" in context
        assert "  - dev_dependencies: jest, typescript" in context
        assert "  - script build: `tsc -p tsconfig.json`" in context
        assert "  - script test: `jest`" in context

    def test_build_slice_context_includes_target_pyproject_manifest(
        self, tmp_path: Path
    ) -> None:
        """Prepared context should summarize Python project metadata deterministically."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        worktree = workspace / "sources" / "tooling"
        spec_dir = workspace / "specs" / "001-tooling"
        worktree.mkdir(parents=True)
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-002 complexity=standard phase=base req=FR-002 depends=none\n",
            encoding="utf-8",
        )
        (worktree / "pyproject.toml").write_text(
            "[project]\n"
            "name = \"tooling\"\n"
            "version = \"0.2.0\"\n"
            "dependencies = [\"click>=8\", \"pydantic>=2\"]\n"
            "\n"
            "[project.scripts]\n"
            "tooling = \"tooling.cli:main\"\n"
            "\n"
            "[project.gui-scripts]\n"
            "tooling-gui = \"tooling.gui:main\"\n"
            "\n"
            "[project.optional-dependencies]\n"
            "dev = [\"pytest\", \"ruff\"]\n"
            "docs = [\"mkdocs\"]\n"
            "\n"
            "[tool.pytest.ini_options]\n"
            "testpaths = [\"tests\"]\n"
            "\n"
            "[tool.ruff]\n"
            "line-length = 100\n",
            encoding="utf-8",
        )
        (worktree / "uv.lock").write_text("version = 1\n", encoding="utf-8")

        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["source_root"] = str(worktree)
        state["target_path"] = str(worktree)
        state["spec_dir"] = str(spec_dir)
        state_store.write(state)

        controller._with_harness_context("body", str(worktree))

        context_file = state_store.state_dir.parent / "context" / "default-build-slice-context.md"
        context = context_file.read_text(encoding="utf-8")
        assert "## Target Manifest Excerpts" in context
        assert "- pyproject.toml: name=`tooling`, version=`0.2.0`" in context
        assert "  - python_package_manager: `uv` (lockfile: `uv.lock`)" in context
        assert "  - dependencies: click, pydantic" in context
        assert "  - optional_dependency_groups: dev, docs" in context
        assert "  - script tooling: `tooling.cli:main`" in context
        assert "  - gui-script tooling-gui: `tooling.gui:main`" in context
        assert "  - tool sections: pytest, ruff" in context

    def test_build_slice_context_includes_target_layout_excerpts(
        self, tmp_path: Path
    ) -> None:
        """Prepared context should summarize target layout without broad discovery."""
        controller, _provider, _gitops, state_store = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        worktree = workspace / "sources" / "prosaic"
        spec_dir = workspace / "specs" / "001-prosaic"
        worktree.mkdir(parents=True)
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-002 complexity=standard phase=base req=FR-002 depends=none\n",
            encoding="utf-8",
        )
        (worktree / "README.md").write_text("# Prosaic\n", encoding="utf-8")
        (worktree / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
        (worktree / "LICENSE").write_text("MIT\n", encoding="utf-8")
        (worktree / "docs").mkdir()
        (worktree / "docs" / "usage.md").write_text("# Usage\n", encoding="utf-8")
        (worktree / "jest.config.ts").write_text("export default {}\n", encoding="utf-8")
        (worktree / "tsconfig.json").write_text("{}\n", encoding="utf-8")
        (worktree / "src").mkdir()
        (worktree / "src" / "index.ts").write_text("export {}\n", encoding="utf-8")
        (worktree / "src" / "config.ts").write_text("export const x = 1\n", encoding="utf-8")
        (worktree / "tests").mkdir()
        (worktree / "tests" / "cli.test.ts").write_text("test('x', () => {})\n", encoding="utf-8")
        (worktree / "tests" / "fixtures").mkdir()
        (worktree / "tests" / "fixtures" / "sample.json").write_text("{}\n", encoding="utf-8")
        (worktree / "node_modules").mkdir()
        (worktree / "dist").mkdir()

        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["source_root"] = str(worktree)
        state["target_path"] = str(worktree)
        state["spec_dir"] = str(spec_dir)
        state_store.write(state)

        controller._with_harness_context("body", str(worktree))

        context_file = state_store.state_dir.parent / "context" / "default-build-slice-context.md"
        context = context_file.read_text(encoding="utf-8")
        assert "## Target Layout Excerpts" in context
        assert "- top-level: CHANGELOG.md, docs/, jest.config.ts, LICENSE, README.md, src/, tests/, tsconfig.json" in context
        assert "- docs: CHANGELOG.md, docs/, LICENSE, README.md" in context
        assert "- source dirs: src/" in context
        assert "- test dirs: tests/" in context
        assert "- config files: jest.config.ts, tsconfig.json" in context
        assert "- file counts: source=2, test=1" in context
        assert "- source files: src/config.ts, src/index.ts" in context
        assert "- test files: tests/cli.test.ts" in context
        assert "tests/fixtures/sample.json" not in context
        assert "node_modules" not in context
        assert "dist/" not in context

    def test_fulfillment_gap_turns_passing_verify_into_failure(self, tmp_path: Path) -> None:
        """Passing tests are not enough when verify-spec found blocking gaps."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | MISSING | none | high | absent |\n",
            encoding="utf-8",
        )
        verify = VerifyResult(passed=True, failures=[])

        result = controller._apply_fulfillment_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "fulfillment-gaps"
        assert "echelon spec reopen spec-001" in result.failures[0].error

    def test_fulfillment_gate_treats_unverified_as_blocking_for_harness(
        self, tmp_path: Path
    ) -> None:
        """Harness convergence requires strict fulfillment, including UNVERIFIED."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-002 complexity=standard phase=build req=FR-001 depends=none\n",
            encoding="utf-8",
        )
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | UNVERIFIED | src/a.py | medium | no executable proof |\n",
            encoding="utf-8",
        )
        verify = VerifyResult(passed=True, failures=[])

        result = controller._apply_fulfillment_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "fulfillment-gaps"
        assert "UNVERIFIED" in result.failures[0].error

    def test_fulfillment_gate_blocks_stale_report_for_current_head(
        self, tmp_path: Path
    ) -> None:
        """Harness must not trust a fulfillment report stamped for an older commit."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "---\n"
            "spec_id: spec-001\n"
            "verified_commit: old123\n"
            "---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
            encoding="utf-8",
        )
        verify = VerifyResult(passed=True, failures=[])

        with patch("harness.ralph._current_git_commit", return_value="new456"):
            result = controller._apply_fulfillment_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "fulfillment-report-stale"
        assert "old123" in result.failures[0].error
        assert "new456" in result.failures[0].error

    def test_fulfillment_gate_rejects_scoped_report_as_convergence_evidence(
        self, tmp_path: Path
    ) -> None:
        """Scoped fulfillment reports are incremental evidence, not final proof."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "---\n"
            "spec_id: spec-001\n"
            "verified_commit: head456\n"
            "verify_scope: scoped\n"
            "base_full_verify_commit: base123\n"
            "---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
            encoding="utf-8",
        )
        verify = VerifyResult(passed=True, failures=[])

        with patch("harness.ralph._current_git_commit", return_value="head456"):
            result = controller._apply_fulfillment_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "fulfillment-report-scoped"
        assert "Do not regenerate fulfillment artifacts in a build slice" in result.failures[0].error
        assert "Ralph must run a full fulfillment refresh before convergence" in result.failures[0].error

    def test_fulfillment_gate_reads_orchestration_spec_dir_for_polyrepo(
        self, tmp_path: Path
    ) -> None:
        """Fulfillment gate uses orchestration spec artifacts, not target worktree discovery."""
        controller, _, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "target" / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        worktree.mkdir(parents=True)
        orchestration_root = tmp_path / "polyrepo"
        spec_dir = orchestration_root / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | MISSING | none | high | absent |\n",
            encoding="utf-8",
        )
        gitops.base_dir = orchestration_root
        state = state_store.read()
        state["target_repo"] = "target"
        state["target_path"] = str(tmp_path / "target")
        state["spec_dir"] = str(spec_dir)
        state["spec_file"] = str(spec_dir / "spec.md")
        state["tasks_file"] = str(spec_dir / "tasks.md")
        state_store.write(state)
        verify = VerifyResult(passed=True, failures=[])

        result = controller._apply_fulfillment_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "fulfillment-gaps"
        assert str(spec_dir / "fulfillment-report.md") in result.failures[0].error

    def test_documentation_gate_blocks_convergence_when_required_docs_missing(
        self, tmp_path: Path
    ) -> None:
        controller, *_ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        _init_git_repo(worktree)
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (worktree / "README.md").write_text("# Demo\n", encoding="utf-8")
        (worktree / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
        (spec_dir / "documentation-impact-report.md").write_text(
            "---\n"
            "docs_required: true\n"
            "readme_updated: true\n"
            "changelog_updated: true\n"
            "changelog_format: keep_a_changelog\n"
            'not_applicable_reason: ""\n'
            "---\n"
            "# Documentation Impact Report\n",
            encoding="utf-8",
        )
        _commit_all(worktree)
        verify = VerifyResult(passed=True, failures=[], duration_s=0.1, token_usage=0)

        result = controller._apply_documentation_gate(verify, str(worktree))

        assert not result.passed
        assert result.failures[0].id == "documentation-required-without-doc-changes"

    def test_documentation_gate_accepts_not_applicable_report_in_ralph(
        self, tmp_path: Path
    ) -> None:
        controller, *_ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "documentation-impact-report.md").write_text(
            "---\n"
            "docs_required: false\n"
            "readme_updated: false\n"
            "changelog_updated: false\n"
            "changelog_format: not_required\n"
            'not_applicable_reason: "No user-visible, API, setup, config, operations, or significant performance changes."\n'
            "---\n"
            "# Documentation Impact Report\n",
            encoding="utf-8",
        )
        verify = VerifyResult(passed=True, failures=[], duration_s=0.1, token_usage=0)

        result = controller._apply_documentation_gate(verify, str(worktree))

        assert result.passed

    def test_documentation_gate_receives_delivery_slice_changed_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        controller, *_ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        verify = VerifyResult(passed=True, failures=[], duration_s=0.1, token_usage=0)
        seen: dict[str, object] = {}

        def fake_gate(worktree_path: Path, resolved_spec_dir: Path, *, changed_files=None):
            seen["worktree_path"] = worktree_path
            seen["spec_dir"] = resolved_spec_dir
            seen["changed_files"] = changed_files
            return DocumentationGateResult(passed=True)

        monkeypatch.setattr("harness.ralph.evaluate_documentation_gate", fake_gate)

        result = controller._apply_documentation_gate(
            verify,
            str(worktree),
            changed_files=["README.md", "CHANGELOG.md"],
        )

        assert result.passed
        assert seen["worktree_path"] == worktree
        assert seen["spec_dir"] == spec_dir
        assert seen["changed_files"] == ["README.md", "CHANGELOG.md"]

    def test_external_missing_documentation_report_blocks_without_inner_fix(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """External spec artifacts are Ralph-owned, not target build fixes."""
        from harness.build_result import BuildResult

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="",
            stderr="",
            duration_ms=100,
            task_ids=["T-001"],
        )
        llm_build_runner.exec_feedback.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="",
            stderr="",
            duration_ms=100,
        )
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        workspace = tmp_path / "workspace"
        worktree = workspace / "runs" / "targets" / "target" / "worktree"
        _init_git_repo(worktree)
        (worktree / "README.md").write_text("# Target\n", encoding="utf-8")
        _commit_all(worktree)
        spec_dir = workspace / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=FR-001 depends=none\n",
            encoding="utf-8",
        )
        state = state_store.read()
        state["target_repo"] = "target"
        state["target_path"] = str(workspace / "sources" / "target")
        state["spec_dir"] = str(spec_dir)
        state["spec_file"] = str(spec_dir / "spec.md")
        state["tasks_file"] = str(spec_dir / "tasks.md")
        state_store.write(state)
        gitops.base_dir = workspace
        gitops.create_worktree.return_value = str(worktree)
        controller._config.verify_command = f"{sys.executable} -c pass"
        controller._fulfillment_runner = None

        result = controller.run_loop(
            max_outer=1,
            max_inner=3,
            build_prompt="implement T-001",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "external_spec_artifact_missing"
        llm_build_runner.exec_feedback.assert_not_called()
        captured = capsys.readouterr()
        assert "Ralph-owned external spec artifact" in captured.err

    def test_task_progress_gap_turns_passing_verify_into_failure(self, tmp_path: Path) -> None:
        """Ralph does not converge when state progress disagrees with tasks.md."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        state = state_store.read()
        state["build"] = {
            "total_tasks": 1,
            "completed_tasks": 1,
            "tasks_completed_pct": 100,
            "task_results": {"T-001": {"status": "DONE"}},
        }
        state_store.write(state)

        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )
        verify = VerifyResult(passed=True, failures=[])

        result = controller._apply_task_progress_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "task-progress-mismatch"
        assert "state completed_tasks=1 but tasks.md has 0 checked task rows" in result.failures[0].error

    def test_build_reported_task_ids_mark_canonical_tasks_done(
        self, tmp_path: Path
    ) -> None:
        """Ralph applies build status marker task IDs to tasks.md before verify."""
        controller, _, _, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        tasks_path = spec_dir / "tasks.md"
        tasks_path.write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n"
            "\n"
            "  **Acceptance Criteria:**\n"
            "  - [ ] Gate passes\n"
            "\n"
            "- [ ] T-002 complexity=standard phase=core req=FR-001 depends=T-001\n",
            encoding="utf-8",
        )

        applied = controller._apply_build_task_progress(
            worktree_path=str(worktree),
            task_ids=["T-001"],
        )

        assert applied == ["T-001"]
        text = tasks_path.read_text(encoding="utf-8")
        assert "- [x] T-001 complexity=standard phase=foundation req=INFRA depends=none" in text
        assert "  **Status:** DONE" in text
        assert "  - [x] Gate passes" in text
        assert "- [ ] T-002 complexity=standard phase=core req=FR-001 depends=T-001" in text
        build = state_store.read()["build"]
        assert build["completed_tasks"] == 1
        assert build["task_results"]["T-001"]["status"] == "DONE"

    def test_build_reported_unknown_task_ids_are_not_silently_applied(
        self, tmp_path: Path
    ) -> None:
        """Ralph exposes failed task-ledger updates for the build loop to block."""
        controller, _, _, _ = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        tasks_path = spec_dir / "tasks.md"
        tasks_path.write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )

        applied = controller._apply_build_task_progress(
            worktree_path=str(worktree),
            task_ids=["T-999"],
        )

        assert applied == []
        assert "- [ ] T-001" in tasks_path.read_text(encoding="utf-8")

    def test_task_progress_gate_reads_orchestration_tasks_for_polyrepo(
        self, tmp_path: Path
    ) -> None:
        """Task-progress gate uses orchestration tasks.md when target worktree has no specs."""
        controller, _, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        state = state_store.read()
        state["build"] = {
            "total_tasks": 1,
            "completed_tasks": 1,
            "tasks_completed_pct": 100,
            "task_results": {"T-001": {"status": "DONE"}},
        }
        state_store.write(state)

        worktree = tmp_path / "target" / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        worktree.mkdir(parents=True)
        orchestration_root = tmp_path / "polyrepo"
        spec_dir = orchestration_root / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )
        gitops.base_dir = orchestration_root
        state = state_store.read()
        state["target_repo"] = "target"
        state["target_path"] = str(tmp_path / "target")
        state["spec_dir"] = str(spec_dir)
        state["spec_file"] = str(spec_dir / "spec.md")
        state["tasks_file"] = str(spec_dir / "tasks.md")
        state_store.write(state)
        verify = VerifyResult(passed=True, failures=[])

        result = controller._apply_task_progress_gate(verify, str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "task-progress-mismatch"

    def test_converges_first_iteration(self, tmp_path: Path) -> None:
        """Verify passes on first try -> converged."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )

        result = controller.run_loop(max_outer=5, max_inner=3)

        assert result.status == "converged"
        assert result.termination_reason == "converged"
        assert result.outer_iterations == 1
        assert result.pr_url is not None
        assert provider.created is True
        assert provider.destroyed is True
        gitops.create_worktree.assert_called_once()
        gitops.promote_pr_ready.assert_called_once()

    def test_convergence_writes_ready_to_land_status(self, tmp_path: Path) -> None:
        """Ralph owns the implemented-but-not-landed status transition."""
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: In Progress\n---\n\n**Status**: In Progress\n",
            encoding="utf-8",
        )
        _write_no_impact_documentation_report(spec_dir)
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.create_worktree.return_value = str(worktree)

        result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "converged"
        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "ready_to_land"
        assert "**Status**: ready_to_land" in (spec_dir / "spec.md").read_text(
            encoding="utf-8"
        )
        history = json.loads((spec_dir / "run-history.json").read_text(encoding="utf-8"))
        assert history["authoritative_run"] == "run-1"
        assert history["runs"][-1]["phase"] == "B"
        assert history["runs"][-1]["status"] == "ready_to_land"
        assert history["runs"][-1]["verification_result"] == "PASS"
        artifacts = spec_dir / "ARTIFACTS.md"
        assert artifacts.exists()
        text = artifacts.read_text(encoding="utf-8")
        assert "Lifecycle stage: verified" in text
        assert "`run-history.json`" in text

    def test_ready_to_land_status_is_committed_before_publish(
        self, tmp_path: Path
    ) -> None:
        """The pushed convergence commit must include the ready_to_land marker."""
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: In Progress\n---\n\n**Status**: In Progress\n",
            encoding="utf-8",
        )
        _write_no_impact_documentation_report(spec_dir)
        controller, _provider, gitops, _state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.create_worktree.return_value = str(worktree)

        def assert_ready_marker_committed(path: str, message: str) -> str:
            del message
            from harness.spec_frontmatter import read_frontmatter

            committed_spec_dir = Path(path) / "specs" / "spec-001-demo"
            assert read_frontmatter(committed_spec_dir)["status"] == "ready_to_land"
            assert "**Status**: ready_to_land" in (
                committed_spec_dir / "spec.md"
            ).read_text(encoding="utf-8")
            return "abc123"

        gitops.commit.side_effect = assert_ready_marker_committed

        result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "converged"
        gitops.push.assert_called_once()
        gitops.promote_pr_ready.assert_called_once()

    def test_convergence_writes_ready_status_to_orchestration_spec_dir(
        self, tmp_path: Path
    ) -> None:
        """Polyrepo harness convergence updates the orchestration spec, not target worktree."""
        worktree = tmp_path / "target" / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        worktree.mkdir(parents=True)
        orchestration_root = tmp_path / "polyrepo"
        _init_git_repo(orchestration_root)
        spec_dir = orchestration_root / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: In Progress\n---\n\n**Status**: In Progress\n",
            encoding="utf-8",
        )
        _write_no_impact_documentation_report(spec_dir)
        _commit_all(orchestration_root, "initial spec")
        controller, _, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.create_worktree.return_value = str(worktree)
        gitops.base_dir = orchestration_root
        state = state_store.read()
        state["target_repo"] = "target"
        state["target_path"] = str(tmp_path / "target")
        state["spec_dir"] = str(spec_dir)
        state["spec_file"] = str(spec_dir / "spec.md")
        state["tasks_file"] = str(spec_dir / "tasks.md")
        state_store.write(state)

        result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "converged"
        from harness.spec_frontmatter import read_frontmatter

        assert read_frontmatter(spec_dir)["status"] == "ready_to_land"
        assert (spec_dir / "run-history.json").exists()
        assert (spec_dir / "ARTIFACTS.md").exists()

    def test_convergence_commits_orchestration_spec_artifacts_for_polyrepo(
        self, tmp_path: Path
    ) -> None:
        """Polyrepo convergence commits workspace spec state separately from target output."""
        worktree = tmp_path / "target" / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        worktree.mkdir(parents=True)
        orchestration_root = tmp_path / "polyrepo"
        _init_git_repo(orchestration_root)
        spec_dir = orchestration_root / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: In Progress\n---\n\n**Status**: In Progress\n",
            encoding="utf-8",
        )
        _write_no_impact_documentation_report(spec_dir)
        _commit_all(orchestration_root, "initial spec")
        controller, _, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.create_worktree.return_value = str(worktree)
        gitops.base_dir = orchestration_root
        state = state_store.read()
        state["target_repo"] = "target"
        state["target_path"] = str(tmp_path / "target")
        state["spec_dir"] = str(spec_dir)
        state["spec_file"] = str(spec_dir / "spec.md")
        state_store.write(state)

        result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "converged"
        committed_spec = subprocess.run(
            ["git", "show", f"HEAD:{spec_dir.relative_to(orchestration_root) / 'spec.md'}"],
            cwd=orchestration_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "status: ready_to_land" in committed_spec
        assert "**Status**: ready_to_land" in committed_spec
        assert "run-history.json" in subprocess.run(
            ["git", "show", "--name-only", "--format=", "HEAD"],
            cwd=orchestration_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def test_does_not_converge_when_fulfillment_report_has_gaps(
        self, tmp_path: Path
    ) -> None:
        """Fulfillment gaps keep Ralph iterating even when sandbox verification passes."""
        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | PARTIAL | src/a.py | high | missing edge case |\n",
            encoding="utf-8",
        )
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.create_worktree.return_value = str(worktree)

        result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "failed"
        assert result.termination_reason == "outer_cap"
        assert result.final_verify is not None
        assert result.final_verify.passed is False
        assert result.final_verify.failures[0].id == "fulfillment-gaps"
        gitops.promote_pr_ready.assert_not_called()

    def test_runs_verify_spec_before_fulfillment_gate_when_runner_available(
        self, tmp_path: Path
    ) -> None:
        """Ralph refreshes fulfillment evidence after sandbox verification passes."""
        from harness.build_result import BuildResult
        from harness.llm_build_runner import LlmBuildRunner

        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)

        llm_build_runner = MagicMock(spec=LlmBuildRunner)
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="",
            stderr="",
            duration_ms=100,
        )

        def write_fulfillment_gap(
            worktree_path: str,
            spec_id: str,
            *,
            spec_dir: Path | str | None = None,
            orchestration_root: Path | str | None = None,
        ) -> int:
            (spec_dir / "fulfillment-report.md").write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "|---|---|---|---|---|\n"
                "| FR-001 | MISSING | none | high | absent |\n",
                encoding="utf-8",
            )
            return 0

        fulfillment_runner = MagicMock()
        fulfillment_runner.refresh.side_effect = write_fulfillment_gap
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
            fulfillment_runner=fulfillment_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.create_worktree.return_value = str(worktree)
        gitops.base_dir = str(worktree)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        fulfillment_runner.refresh.assert_called_once_with(
            str(worktree),
            "spec-001",
            spec_dir=spec_dir,
            orchestration_root=None,
        )
        assert result.status == "failed"
        assert result.final_verify is not None
        assert result.final_verify.failures[0].id == "fulfillment-gaps"

    def test_cached_verify_spec_refresh_is_accepted_before_fulfillment_gate(
        self, tmp_path: Path
    ) -> None:
        """Ralph treats a valid cached full verify-spec report as refreshed evidence."""
        from harness.build_result import BuildResult
        from harness.llm_build_runner import LlmBuildRunner

        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
            encoding="utf-8",
        )
        (spec_dir / "documentation-impact-report.md").write_text(
            "---\n"
            "docs_required: false\n"
            "readme_updated: false\n"
            "changelog_updated: false\n"
            "changelog_format: not_required\n"
            'not_applicable_reason: "Fixture build has no user-visible documentation impact."\n'
            "---\n"
            "# Documentation Impact Report\n",
            encoding="utf-8",
        )

        llm_build_runner = MagicMock(spec=LlmBuildRunner)
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="",
            stderr="",
            duration_ms=100,
        )
        fulfillment_runner = MagicMock()
        fulfillment_runner.refresh.return_value = FulfillmentRefreshResult(
            status="cached",
            exit_code=0,
            used_cache=True,
        )
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
            fulfillment_runner=fulfillment_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.create_worktree.return_value = str(worktree)
        gitops.base_dir = str(worktree)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "converged"
        assert result.final_verify is not None
        assert result.final_verify.passed is True
        fulfillment_runner.refresh.assert_called_once()

    def test_scoped_fulfillment_policy_passes_task_ids_and_changed_files(
        self, tmp_path: Path
    ) -> None:
        """Scoped policy gives verify-spec a deterministic impacted slice."""
        from harness.build_result import BuildResult
        from harness.llm_build_runner import LlmBuildRunner

        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-002 complexity=standard phase=build req=FR-001 depends=none\n"
            "- [ ] T-003 complexity=standard phase=build req=FR-002 depends=T-002\n",
            encoding="utf-8",
        )
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
            encoding="utf-8",
        )

        llm_build_runner = MagicMock(spec=LlmBuildRunner)
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="",
            stderr="",
            duration_ms=100,
            task_ids=["T-002"],
        )
        fulfillment_runner = MagicMock()
        fulfillment_runner.refresh.return_value = FulfillmentRefreshResult(
            status="refreshed",
            exit_code=0,
            scope="scoped",
            reason="scoped verify-spec completed",
        )
        controller, _provider, gitops, _state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
            fulfillment_runner=fulfillment_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        controller._config.fulfillment.refresh_policy = "scoped"
        gitops.create_worktree.return_value = str(worktree)
        gitops.base_dir = str(worktree)
        controller._changed_files_since_head = MagicMock(
            return_value=["src/a.py", "tests/test_a.py"]
        )

        controller.run_loop(max_outer=1, max_inner=0, build_prompt="implement")

        fulfillment_runner.refresh.assert_called_once_with(
            str(worktree),
            "spec-001",
            spec_dir=spec_dir,
            orchestration_root=None,
            scope="scoped",
            completed_task_ids=["T-002"],
            changed_files=["src/a.py", "tests/test_a.py"],
        )

    def test_scoped_fulfillment_policy_defers_full_refresh_without_feedback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Scoped evidence is useful progress, not an inner-fix failure."""
        from harness.build_result import BuildResult
        from harness.llm_build_runner import LlmBuildRunner

        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [x] T-001 complexity=standard phase=demo req=FR-001 depends=none\n"
            "- [ ] T-002 complexity=standard phase=demo req=FR-002 depends=none\n",
            encoding="utf-8",
        )
        (spec_dir / "fulfillment-report.md").write_text(
            "---\n"
            "spec_id: spec-001\n"
            "verified_commit: head456\n"
            "verify_scope: scoped\n"
            "base_full_verify_commit: base123\n"
            "---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
            encoding="utf-8",
        )

        build_runner = MagicMock(spec=LlmBuildRunner)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="",
            stderr="",
            duration_ms=100,
            task_ids=["T-001"],
        )
        build_runner.exec_feedback.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="",
            stderr="",
            duration_ms=100,
            task_ids=[],
            reason="nothing source-level to fix",
        )
        fulfillment_runner = MagicMock()
        fulfillment_runner.refresh.return_value = FulfillmentRefreshResult(
            status="refreshed",
            exit_code=0,
            scope="scoped",
            reason="scoped verify-spec completed",
        )
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            mode="banzai",
            llm_build_runner=build_runner,
            fulfillment_runner=fulfillment_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        controller._config.fulfillment.refresh_policy = "scoped"
        gitops.create_worktree.return_value = str(worktree)
        gitops.base_dir = worktree
        controller._changed_files_since_head = MagicMock(return_value=["src/a.py"])

        result = controller.run_loop(max_outer=2, max_inner=3, build_prompt="build")

        assert result.status == "blocked"
        assert result.termination_reason == "checkpoint_outer_cap"
        assert result.outer_iterations == 2
        assert result.final_verify is not None
        assert result.final_verify.failures[0].id == "fulfillment-refresh-deferred"
        build_runner.exec_feedback.assert_not_called()
        assert build_runner.exec_build.call_count == 2
        assert fulfillment_runner.refresh.call_count == 2
        refresh = state_store.read()["fulfillment_refresh"]
        assert refresh["status"] == "deferred"
        assert refresh["scope"] == "full"
        assert refresh["reason"] == "scoped fulfillment refresh completed"
        captured = capsys.readouterr()
        assert "fulfillment refresh: deferred" in captured.err
        assert "scoped fulfillment refresh completed" in captured.err

    def test_convergence_only_fulfillment_policy_skips_failed_slice_refresh(
        self, tmp_path: Path
    ) -> None:
        """Incomplete task slices should not pay for full verify-spec refresh."""
        controller, _provider, _gitops, _state_store = _make_controller(
            tmp_path,
            verify_results=[
                {"passed": True, "failures": []},
            ],
            fulfillment_runner=MagicMock(),
        )
        controller._config.fulfillment.refresh_policy = "convergence_only"
        state = _state_store.read()
        state["build"] = {
            "total_tasks": 2,
            "completed_tasks": 1,
            "tasks_completed_pct": 50,
        }
        _state_store.write(state)

        result = controller.run_loop(max_outer=1, max_inner=0)

        assert result.status == "failed"
        assert result.final_verify is not None
        assert result.final_verify.failures[0].id == "fulfillment-refresh-deferred"
        controller._fulfillment_runner.refresh.assert_not_called()

    def test_banzai_milestone_defers_full_fulfillment_without_feedback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Banzai milestone slices should keep building without full verify-spec cost."""
        from harness.build_result import BuildResult
        from harness.llm_build_runner import LlmBuildRunner

        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [x] T-001 complexity=standard phase=demo req=FR-001 depends=none\n"
            "- [ ] T-002 complexity=standard phase=demo req=FR-002 depends=none\n",
            encoding="utf-8",
        )

        build_runner = MagicMock(spec=LlmBuildRunner)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="",
            stderr="",
            duration_ms=100,
            task_ids=["T-001"],
        )
        fulfillment_runner = MagicMock()
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            mode="banzai",
            llm_build_runner=build_runner,
            fulfillment_runner=fulfillment_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.create_worktree.return_value = str(worktree)
        gitops.base_dir = worktree

        result = controller.run_loop(max_outer=2, max_inner=3, build_prompt="build")

        assert result.status == "blocked"
        assert result.termination_reason == "checkpoint_outer_cap"
        assert result.outer_iterations == 2
        assert result.final_verify is not None
        assert result.final_verify.failures[0].id == "fulfillment-refresh-deferred"
        build_runner.exec_feedback.assert_not_called()
        assert build_runner.exec_build.call_count == 2
        fulfillment_runner.refresh.assert_not_called()
        assert not state_store.read().get("escalation_file")
        refresh = state_store.read()["fulfillment_refresh"]
        assert refresh["status"] == "deferred"
        assert (
            refresh["reason"]
            == "banzai milestone defers full verify until task completion"
        )
        captured = capsys.readouterr()
        assert "fulfillment refresh: deferred" in captured.err
        assert "banzai milestone defers full verify until task completion" in captured.err

    def test_semi_milestone_runs_full_fulfillment_and_records_decision(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Semi milestone remains conservative but records cache/full refresh metadata."""
        from harness.build_result import BuildResult
        from harness.llm_build_runner import LlmBuildRunner

        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [x] T-001 complexity=standard phase=demo req=FR-001 depends=none\n"
            "- [ ] T-002 complexity=standard phase=demo req=FR-002 depends=none\n",
            encoding="utf-8",
        )
        report = spec_dir / "fulfillment-report.md"
        report.write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
            encoding="utf-8",
        )

        build_runner = MagicMock(spec=LlmBuildRunner)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="",
            stderr="",
            duration_ms=100,
            task_ids=["T-001"],
        )
        fulfillment_runner = MagicMock()
        fulfillment_runner.refresh.return_value = FulfillmentRefreshResult(
            status="cached",
            exit_code=0,
            used_cache=True,
            scope="full",
            reason="full verify-spec cache hit",
            cache_key="cache123",
            report_path=str(report),
        )
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            mode="semi",
            llm_build_runner=build_runner,
            fulfillment_runner=fulfillment_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.create_worktree.return_value = str(worktree)
        gitops.base_dir = worktree

        controller.run_loop(max_outer=1, max_inner=0, build_prompt="build")

        fulfillment_runner.refresh.assert_called_once()
        refresh = state_store.read()["fulfillment_refresh"]
        assert refresh["status"] == "cached"
        assert refresh["reason"] == "full verify-spec cache hit"
        assert refresh["scope"] == "full"
        assert refresh["cache_key"] == "cache123"
        assert refresh["report_path"] == str(report)
        captured = capsys.readouterr()
        assert "fulfillment refresh: cached" in captured.err
        assert "full verify-spec cache hit" in captured.err

    def test_refreshed_equals_style_fulfillment_report_blocks_convergence(
        self, tmp_path: Path
    ) -> None:
        """Fresh verify-spec summaries using STATUS=count syntax must block convergence."""
        from harness.build_result import BuildResult
        from harness.llm_build_runner import LlmBuildRunner

        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)

        llm_build_runner = MagicMock(spec=LlmBuildRunner)
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="",
            stderr="",
            duration_ms=100,
        )

        def write_realistic_summary(
            worktree_path: str,
            spec_id: str,
            *,
            spec_dir: Path | str | None = None,
            orchestration_root: Path | str | None = None,
        ) -> int:
            (spec_dir / "fulfillment-report.md").write_text(
                "**Fulfillment status (170 checklist items)**: "
                "IMPLEMENTED=80, PARTIAL=31, UNVERIFIED=5, MISSING=53, "
                "DEVIATED=1, OBSOLETE_SPEC=0\n",
                encoding="utf-8",
            )
            return 0

        fulfillment_runner = MagicMock()
        fulfillment_runner.refresh.side_effect = write_realistic_summary
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
            fulfillment_runner=fulfillment_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.create_worktree.return_value = str(worktree)
        gitops.base_dir = str(worktree)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "failed"
        assert result.termination_reason == "outer_cap"
        assert result.final_verify is not None
        assert result.final_verify.passed is False
        assert result.final_verify.failures[0].id == "fulfillment-gaps"
        gitops.promote_pr_ready.assert_not_called()

    def test_fulfillment_refresh_uses_orchestration_root_for_polyrepo_target(
        self, tmp_path: Path
    ) -> None:
        """Targeted polyrepo builds refresh fulfillment in the orchestration spec dir."""
        from harness.build_result import BuildResult
        from harness.llm_build_runner import LlmBuildRunner

        orchestration_root = tmp_path / "polyrepo"
        target_root = tmp_path / "target"
        worktree = target_root / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        spec_dir = orchestration_root / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        worktree.mkdir(parents=True)

        llm_build_runner = MagicMock(spec=LlmBuildRunner)
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="",
            stderr="",
            duration_ms=100,
        )
        fulfillment_runner = MagicMock()
        fulfillment_runner.refresh.return_value = 0
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
            fulfillment_runner=fulfillment_runner,
        )
        state = state_store.read()
        state["target_repo"] = "target"
        state["target_path"] = str(target_root)
        state["spec_dir"] = str(spec_dir)
        state["spec_file"] = str(spec_dir / "spec.md")
        state["tasks_file"] = str(spec_dir / "tasks.md")
        state_store.write(state)
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.create_worktree.return_value = str(worktree)
        gitops.base_dir = orchestration_root

        controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        fulfillment_runner.refresh.assert_called_once_with(
            str(worktree),
            "spec-001",
            orchestration_root=orchestration_root,
            spec_dir=spec_dir,
        )

    def test_publish_failure_blocks_and_preserves_worktree(self, tmp_path: Path) -> None:
        """Verified work must not be reported converged when commit/push fails."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.push.side_effect = Exception("network error")

        result = controller.run_loop(max_outer=5, max_inner=3)

        assert result.status == "blocked"
        assert result.termination_reason == "publish_failed"
        assert result.branch == "harness/spec-001-default-iter-0"
        gitops.promote_pr_ready.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

        state = state_store.read()
        assert state["status"] == "blocked"
        assert state["termination_reason"] == "publish_failed"
        assert state["branch"] == "harness/spec-001-default-iter-0"

    def test_llm_build_incomplete_returns_blocked_result(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Missing build status should block gracefully instead of raising."""
        from harness.build_result import BuildResult

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="unknown",
            impasse_file=None,
            stdout="done without status file",
            stderr="",
            duration_ms=1000,
        )
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "build_incomplete"
        captured = capsys.readouterr()
        assert "missing build status marker" in captured.err
        assert ".harness-build-status.json" in captured.err
        assert "echelon delivery continue spec-001" in captured.err
        assert "missing Phase A artifacts" not in captured.err
        assert provider.destroyed is True
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_missing_marker_continues_when_all_tasks_already_done(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A complete task ledger does not need a second LLM run to write marker."""
        from harness.build_result import BuildResult

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=worktree,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=worktree,
            check=True,
        )
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [x] T-001 complexity=standard phase=foundation req=FR-001 depends=none\n",
            encoding="utf-8",
        )
        _write_no_impact_documentation_report(spec_dir)
        (worktree / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="unknown",
            impasse_file=None,
            stdout="all tasks already complete; no changes",
            stderr="",
            duration_ms=1000,
        )
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = worktree
        gitops.create_worktree.return_value = str(worktree)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="continue",
        )

        assert result.status == "converged"
        captured = capsys.readouterr()
        assert "missing build status marker" not in captured.err
        recoveries = state_store.read()["missing_marker_recoveries"]
        assert recoveries[-1]["all_tasks_complete"] is True
        llm_build_runner.exec_build.assert_called_once()
        gitops.commit.assert_called()

    def test_llm_build_recovers_completed_task_ids_from_final_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Final JSON completed_task_ids can recover a missing status marker."""
        from harness.llm_build_runner import LlmBuildRunner

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=worktree,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=worktree,
            check=True,
        )
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        tasks_path = spec_dir / "tasks.md"
        tasks_path.write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=FR-001 depends=none\n",
            encoding="utf-8",
        )
        _write_no_impact_documentation_report(spec_dir)
        (worktree / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)

        class FinalJsonExecutor:
            last_stdout = ""
            last_stderr = ""
            last_token_usage = 123

            def exec_prompt(self, worktree_path: str, prompt: str, *, extra_env=None):
                Path(worktree_path, "generated.txt").write_text(
                    "verified implementation\n",
                    encoding="utf-8",
                )
                self.last_stdout = (
                    "Build slice complete.\n"
                    "```json\n"
                    '{"status":"complete","state_updates":{"completed_task_ids":["T-001"]}}\n'
                    "```\n"
                )
                return 0

        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=LlmBuildRunner(FinalJsonExecutor()),
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = worktree
        gitops.create_worktree.return_value = str(worktree)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement T-001",
        )

        assert result.status == "converged"
        assert "- [x] T-001" in tasks_path.read_text(encoding="utf-8")
        captured = capsys.readouterr()
        assert "missing build status marker" not in captured.err
        assert state_store.read()["build"]["task_results"]["T-001"]["status"] == "DONE"
        gitops.commit.assert_called()
        gitops.push.assert_called_once_with(str(worktree), "main")

    def test_llm_build_permission_denied_reports_host_tool_policy_blocker(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Host AI CLI permission denials must not be misreported as verify gaps."""
        from harness.build_result import BuildResult

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="unknown",
            impasse_file=None,
            stdout=(
                "The first Write to pyproject.toml returned permission not granted. "
                "This session's permission mode is denying file writes and python "
                "execution inside the worktree."
            ),
            stderr="",
            duration_ms=1000,
        )
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        provider.destroy = MagicMock(side_effect=RuntimeError("podman rm timed out"))

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "build_incomplete"
        captured = capsys.readouterr()
        assert "host LLM tool permissions blocked the build" in captured.err
        assert "allow_unsafe_host_execution: true" in captured.err
        assert "verify_command" not in captured.err
        state = state_store.read()
        assert state["termination_reason"] == "build_incomplete"
        assert state["build_status"] == "host_tool_permission_denied"
        assert "allow_unsafe_host_execution" in state["build_reason"]
        assert state["cleanup_warnings"][0]["operation"] == "sandbox_destroy"
        assert "podman rm timed out" in state["cleanup_warnings"][0]["error"]
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_impasse_reports_marker_status(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Explicit impasse marker must not be reported as a missing marker."""
        from harness.build_result import BuildResult

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="impasse",
            impasse_file=None,
            reason="scope exceeds build budget",
            stdout="",
            stderr="",
            duration_ms=1000,
        )
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "build_incomplete"
        captured = capsys.readouterr()
        assert "build reported status 'impasse'" in captured.err
        assert "scope exceeds build budget" in captured.err
        assert "missing build status marker" not in captured.err
        state = state_store.read()
        assert state["build_status"] == "impasse"
        assert state["build_reason"] == "scope exceeds build budget"
        assert provider.destroyed is True
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_done_without_task_ids_blocks_for_task_backed_spec(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A done marker must name completed task IDs when tasks.md has task rows."""
        from harness.build_result import BuildResult

        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            reason="implemented verified slice",
            stdout="",
            stderr="",
            duration_ms=1000,
            task_ids=[],
        )
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        gitops.create_worktree.return_value = str(worktree)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "build_incomplete"
        captured = capsys.readouterr()
        assert "build completion marker omitted completed_task_ids" in captured.err
        assert "canonical tasks Ralph must mark DONE" in captured.err
        state = state_store.read()
        assert state["build_status"] == "missing_task_ids"
        assert "completed_task_ids" in state["build_reason"]
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_timeout_reports_timeout_not_marker_status(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Timeouts are process failures, not explicit COMMANDER marker statuses."""
        from harness.build_result import BuildResult

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=-1,
            status="timeout",
            impasse_file=None,
            reason=None,
            stdout="",
            stderr="",
            duration_ms=1_200_000,
        )
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "build_incomplete"
        captured = capsys.readouterr()
        assert "build invocation timed out before COMMANDER finalized" in captured.err
        assert "COMMANDER wrote the harness completion marker" not in captured.err
        state = state_store.read()
        assert state["build_status"] == "timeout"
        assert provider.destroyed is True
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_nonzero_unknown_reports_session_limit_not_marker_status(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Provider session limits should be explicit, not blamed on COMMANDER."""
        from harness.build_result import BuildResult

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=1,
            status="unknown",
            impasse_file=None,
            stdout="You've hit your session limit · resets 9:10pm",
            stderr="",
            duration_ms=1000,
        )
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "build_incomplete"
        captured = capsys.readouterr()
        assert "HARNESS — PROVIDER SESSION LIMIT" in captured.err
        assert "LLM provider session limit reached before COMMANDER finalized" in captured.err
        assert "You've hit your session limit" in captured.err
        assert "9:10pm" in captured.err
        assert "retry after" in captured.err
        assert "echelon delivery continue spec-001" in captured.err
        assert "missing build status marker" not in captured.err
        assert "COMMANDER may have changed files, but did not write" not in captured.err
        state = state_store.read()
        assert state["build_status"] == "provider_session_limit"
        assert state["build_exit_code"] == 1
        assert state["provider_reset_hint"] == "9:10pm"
        assert state["provider_limit_message"] == "You've hit your session limit · resets 9:10pm"
        assert provider.destroyed is True
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_tokens_are_counted_for_provider_backed_builds(
        self, tmp_path: Path
    ) -> None:
        from harness.build_result import BuildResult

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="done",
            stderr="",
            duration_ms=1000,
            token_usage=4321,
            task_ids=["T-001"],
        )
        controller, _provider, gitops, _state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )

        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=base req=FR-001 depends=none\n",
            encoding="utf-8",
        )
        gitops.create_worktree.return_value = str(worktree)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.tokens_used == 4321

    def test_allows_empty_completed_task_ids_for_zero_change_slice(
        self, tmp_path: Path
    ) -> None:
        """A no-op fix slice may hand control back to Ralph without fake task IDs."""
        build_result = {
            "passed": True,
            "build_status": "done",
            "task_ids": [],
            "reason": "Ralph must refresh fulfillment evidence before convergence.",
        }
        controller, _provider, _gitops, _state_store = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"], cwd=worktree, check=True
        )
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=base req=FR-001 depends=none\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)

        controller._enforce_completed_task_ids(build_result, str(worktree))

        assert build_result["passed"] is True
        assert build_result["build_status"] == "done"

    def test_rejects_empty_completed_task_ids_when_non_verify_files_changed(
        self, tmp_path: Path
    ) -> None:
        """A successful slice with real file edits must name the completed tasks."""
        build_result = {
            "passed": True,
            "build_status": "done",
            "task_ids": [],
        }
        controller, _provider, _gitops, _state_store = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"], cwd=worktree, check=True
        )
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=base req=FR-001 depends=none\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)
        (worktree / "app.py").write_text("print('changed')\n", encoding="utf-8")

        controller._enforce_completed_task_ids(build_result, str(worktree))

        assert build_result["passed"] is False
        assert build_result["build_status"] == "missing_task_ids"

    def test_llm_build_blocks_when_real_repo_gets_dirty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Harness detects when the LLM writes outside the isolated worktree."""
        from harness.build_result import BuildResult

        project = tmp_path / "project"
        project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project, check=True)
        (project / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=project, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=project, check=True)

        worktree = project / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        worktree.mkdir(parents=True)

        llm_build_runner = MagicMock()

        def dirty_real_repo(_worktree_path: str, _prompt: str, **_kwargs):
            (project / "escaped.txt").write_text("wrong root\n", encoding="utf-8")
            return BuildResult(
                exit_code=0,
                status="done",
                impasse_file=None,
                stdout="",
                stderr="",
                duration_ms=1000,
            )

        llm_build_runner.exec_build.side_effect = dirty_real_repo
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        gitops.base_dir = project
        gitops.create_worktree.return_value = str(worktree)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "containment_violation"
        captured = capsys.readouterr()
        assert "CONTAINMENT VIOLATION" in captured.err
        assert "escaped.txt" in captured.err
        assert "outside the isolated worktree" in captured.err
        assert "real target repo" not in captured.err
        assert state_store.read()["termination_reason"] == "containment_violation"
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_blocks_when_transcript_touches_forbidden_source_root(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Harness detects transcript evidence of sibling source-root access."""
        from harness.build_result import BuildResult

        workspace = tmp_path / "workspace"
        target = workspace / "sources" / "prosaic"
        sibling = workspace / "sources" / "ruler"
        worktree = (
            tmp_path
            / "runs"
            / "targets"
            / "prosaic"
            / "runs"
            / "build-1"
            / "worktrees"
            / "default"
            / "iter-0"
        )
        for path in (target, sibling, worktree):
            path.mkdir(parents=True)

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout=f"  ▷ Read: {sibling / 'README.md'}\n",
            stderr="",
            duration_ms=1000,
        )
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = target
        gitops.create_worktree.return_value = str(worktree)
        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["workspace_git_role"] = "workspace"
        state["source_root"] = str(target)
        state["source_id"] = "prosaic"
        state["source_git_role"] = "source"
        state_store.write(state)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "containment_violation"
        captured = capsys.readouterr()
        assert "SOURCE ROOT CONTAINMENT VIOLATION" in captured.err
        assert str(sibling) in captured.err
        state = state_store.read()
        assert state["termination_reason"] == "containment_violation"
        violation = state["source_root_containment_violation"]
        assert violation["forbidden_root"] == str(sibling)
        assert "README.md" in violation["matched_line"]
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_blocks_when_transcript_writes_forbidden_source_root(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Harness detects write/edit transcript evidence for sibling source roots."""
        from harness.build_result import BuildResult

        workspace = tmp_path / "workspace"
        target = workspace / "sources" / "prosaic"
        sibling = workspace / "sources" / "ruler"
        worktree = (
            tmp_path
            / "runs"
            / "targets"
            / "prosaic"
            / "runs"
            / "build-1"
            / "worktrees"
            / "default"
            / "iter-0"
        )
        for path in (target, sibling, worktree):
            path.mkdir(parents=True)

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout=f"  ▷ Write: {sibling / 'README.md'}\n",
            stderr="",
            duration_ms=1000,
        )
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = target
        gitops.create_worktree.return_value = str(worktree)
        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["workspace_git_role"] = "workspace"
        state["source_root"] = str(target)
        state["source_id"] = "prosaic"
        state["source_git_role"] = "source"
        state_store.write(state)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "containment_violation"
        captured = capsys.readouterr()
        assert "SOURCE ROOT CONTAINMENT VIOLATION" in captured.err
        state = state_store.read()
        violation = state["source_root_containment_violation"]
        assert violation["forbidden_root"] == str(sibling)
        assert "README.md" in violation["matched_line"]
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_blocks_when_tool_output_contains_forbidden_source_root(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Harness detects sibling source roots in tool output blocks."""
        from harness.build_result import BuildResult

        workspace = tmp_path / "workspace"
        target = workspace / "sources" / "prosaic"
        sibling = workspace / "sources" / "spec-kit-skills-agents"
        worktree = (
            tmp_path
            / "runs"
            / "targets"
            / "prosaic"
            / "runs"
            / "build-1"
            / "worktrees"
            / "default"
            / "iter-0"
        )
        for path in (target, sibling, worktree):
            path.mkdir(parents=True)

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout=(
                "  ▷ Bash: Inspect sources directory\n"
                "  ⎿  /tmp/other/path\n"
                f"     {sibling / 'package.json'}\n"
            ),
            stderr="",
            duration_ms=1000,
        )
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = target
        gitops.create_worktree.return_value = str(worktree)
        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["workspace_git_role"] = "workspace"
        state["source_root"] = str(target)
        state["source_id"] = "prosaic"
        state["source_git_role"] = "source"
        state_store.write(state)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "containment_violation"
        captured = capsys.readouterr()
        assert "SOURCE ROOT CONTAINMENT VIOLATION" in captured.err
        assert str(sibling) in captured.err
        state = state_store.read()
        violation = state["source_root_containment_violation"]
        assert violation["forbidden_root"] == str(sibling)
        assert "package.json" in violation["matched_line"]
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_blocks_when_tool_output_contains_relative_forbidden_source_root(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Harness detects sibling source-root access reported as workspace-relative paths."""
        from harness.build_result import BuildResult

        workspace = tmp_path / "workspace"
        target = workspace / "sources" / "prosaic"
        sibling = workspace / "sources" / "spec-kit-skills-agents"
        worktree = (
            tmp_path
            / "runs"
            / "targets"
            / "prosaic"
            / "runs"
            / "build-1"
            / "worktrees"
            / "default"
            / "iter-0"
        )
        for path in (target, sibling, worktree):
            path.mkdir(parents=True)

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout=(
                "  ▷ Bash: Inspect sources directory\n"
                "  ⎿  sources/prosaic\n"
                "     sources/spec-kit-skills-agents/package.json\n"
            ),
            stderr="",
            duration_ms=1000,
        )
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = target
        gitops.create_worktree.return_value = str(worktree)
        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["workspace_git_role"] = "workspace"
        state["source_root"] = str(target)
        state["source_id"] = "prosaic"
        state["source_git_role"] = "source"
        state_store.write(state)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "containment_violation"
        captured = capsys.readouterr()
        assert "SOURCE ROOT CONTAINMENT VIOLATION" in captured.err
        assert str(sibling) in captured.err
        state = state_store.read()
        violation = state["source_root_containment_violation"]
        assert violation["forbidden_root"] == str(sibling)
        assert "sources/spec-kit-skills-agents/package.json" in violation["matched_line"]
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_blocks_when_transcript_touches_host_harness_source(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Harness detects transcript evidence of host Echelon source inspection."""
        from harness.build_result import BuildResult
        import harness.ralph as ralph_module

        project = tmp_path / "project"
        worktree = tmp_path / "worktree"
        for path in (project, worktree):
            _init_git_repo(path)
            (path / "README.md").write_text("# Demo\n", encoding="utf-8")
            _commit_all(path)

        host_harness_root = Path(ralph_module.__file__).resolve().parents[2]
        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout=f"  ▷ Read: {host_harness_root / 'src' / 'harness' / 'ralph.py'}\n",
            stderr="",
            duration_ms=1000,
        )
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = project
        gitops.create_worktree.return_value = str(worktree)
        state = state_store.read()
        state["workspace_root"] = str(project)
        state["source_root"] = str(project)
        state_store.write(state)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "containment_violation"
        captured = capsys.readouterr()
        assert "HARNESS SOURCE CONTAINMENT VIOLATION" in captured.err
        assert str(host_harness_root) in captured.err
        state = state_store.read()
        assert state["termination_reason"] == "containment_violation"
        violation = state["harness_source_containment_violation"]
        assert violation["forbidden_root"] == str(host_harness_root)
        assert "ralph.py" in violation["matched_line"]
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_blocks_when_transcript_touches_relative_host_harness_source(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Harness detects relative transcript evidence of host Echelon source inspection."""
        from harness.build_result import BuildResult

        project = tmp_path / "project"
        worktree = tmp_path / "worktree"
        for path in (project, worktree):
            _init_git_repo(path)
            (path / "README.md").write_text("# Demo\n", encoding="utf-8")
            _commit_all(path)

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="  ▷ Read: src/harness/ralph.py\n",
            stderr="",
            duration_ms=1000,
        )
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = project
        gitops.create_worktree.return_value = str(worktree)
        state = state_store.read()
        state["workspace_root"] = str(project)
        state["source_root"] = str(project)
        state_store.write(state)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "containment_violation"
        captured = capsys.readouterr()
        assert "HARNESS SOURCE CONTAINMENT VIOLATION" in captured.err
        state = state_store.read()
        assert state["termination_reason"] == "containment_violation"
        violation = state["harness_source_containment_violation"]
        assert "host Echelon source outside worktree" in violation["forbidden_root"]
        assert "src/harness/ralph.py" in violation["matched_line"]
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_blocks_when_transcript_touches_unknown_relative_host_harness_source(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Harness detects any relative src/harness/*.py host source inspection."""
        from harness.build_result import BuildResult

        project = tmp_path / "project"
        worktree = tmp_path / "worktree"
        for path in (project, worktree):
            _init_git_repo(path)
            (path / "README.md").write_text("# Demo\n", encoding="utf-8")
            _commit_all(path)

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="  ▷ Read: src/harness/land.py\n",
            stderr="",
            duration_ms=1000,
        )
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = project
        gitops.create_worktree.return_value = str(worktree)
        state = state_store.read()
        state["workspace_root"] = str(project)
        state["source_root"] = str(project)
        state_store.write(state)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "containment_violation"
        captured = capsys.readouterr()
        assert "HARNESS SOURCE CONTAINMENT VIOLATION" in captured.err
        state = state_store.read()
        violation = state["harness_source_containment_violation"]
        assert "host Echelon source outside worktree" in violation["forbidden_root"]
        assert "src/harness/land.py" in violation["matched_line"]
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_blocks_when_transcript_touches_relative_host_kernel_source(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Harness detects relative transcript evidence of host Echelon kernel inspection."""
        from harness.build_result import BuildResult

        project = tmp_path / "project"
        worktree = tmp_path / "worktree"
        for path in (project, worktree):
            _init_git_repo(path)
            (path / "README.md").write_text("# Demo\n", encoding="utf-8")
            _commit_all(path)

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="  ▷ Read: src/kernel/fulfillment.py\n",
            stderr="",
            duration_ms=1000,
        )
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = project
        gitops.create_worktree.return_value = str(worktree)
        state = state_store.read()
        state["workspace_root"] = str(project)
        state["source_root"] = str(project)
        state_store.write(state)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "containment_violation"
        captured = capsys.readouterr()
        assert "HARNESS SOURCE CONTAINMENT VIOLATION" in captured.err
        state = state_store.read()
        violation = state["harness_source_containment_violation"]
        assert "host Echelon source outside worktree" in violation["forbidden_root"]
        assert "src/kernel/fulfillment.py" in violation["matched_line"]
        gitops.commit.assert_not_called()
        gitops.destroy_worktree.assert_not_called()

    def test_llm_build_allows_relative_harness_source_when_file_is_inside_worktree(
        self, tmp_path: Path
    ) -> None:
        """Relative Echelon source reads are allowed when they resolve inside the target worktree."""
        from harness.build_result import BuildResult

        project = tmp_path / "echelon-target"
        worktree = tmp_path / "worktree"
        for path in (project, worktree):
            _init_git_repo(path)
            (path / "README.md").write_text("# Demo\n", encoding="utf-8")
            (path / "src" / "harness").mkdir(parents=True)
            (path / "src" / "harness" / "ralph.py").write_text("# local\n", encoding="utf-8")
            _commit_all(path)

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="  ▷ Read: src/harness/ralph.py\n",
            stderr="",
            duration_ms=1000,
        )
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = project
        gitops.create_worktree.return_value = str(worktree)
        state = state_store.read()
        state["workspace_root"] = str(project)
        state["source_root"] = str(project)
        state_store.write(state)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "converged"
        state = state_store.read()
        assert "harness_source_containment_violation" not in state

    def test_forbidden_source_root_list_echo_does_not_block_build(
        self, tmp_path: Path
    ) -> None:
        """Prompt echoes of forbidden roots are not treated as tool access."""
        from harness.build_result import BuildResult

        workspace = tmp_path / "workspace"
        target = workspace / "sources" / "prosaic"
        sibling = workspace / "sources" / "ruler"
        worktree = tmp_path / "worktree"
        for path in (target, sibling, worktree):
            path.mkdir(parents=True)

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout=f"forbidden_source_roots:\n- {sibling}\n",
            stderr="",
            duration_ms=1000,
        )
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = target
        gitops.create_worktree.return_value = str(worktree)
        state = state_store.read()
        state["workspace_root"] = str(workspace)
        state["source_root"] = str(target)
        state_store.write(state)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "converged"

    def test_build_incomplete_salvages_dirty_worktree_to_commit(
        self, tmp_path: Path
    ) -> None:
        """Failed markerless build output is committed before blocking."""
        from harness.build_result import BuildResult

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=worktree,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=worktree,
            check=True,
        )
        (worktree / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)
        (worktree / "generated.txt").write_text("salvaged\n", encoding="utf-8")
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "generated\n", encoding="utf-8"
        )

        llm_build_runner = MagicMock()

        def markerless_failed_build(*_args: Any, **_kwargs: Any) -> BuildResult:
            (worktree / ".harness-build-status.json").write_text(
                '{"status":"done","completed_task_ids":[]}\n',
                encoding="utf-8",
            )
            return BuildResult(
                exit_code=1,
                status="unknown",
                impasse_file=None,
                stdout="done without usable status file",
                stderr="",
                duration_ms=1000,
            )

        llm_build_runner.exec_build.side_effect = markerless_failed_build
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = worktree
        gitops.create_worktree.return_value = str(worktree)

        result = controller.run_loop(
            max_outer=5,
            max_inner=3,
            build_prompt="implement something",
        )

        assert result.status == "blocked"
        state = state_store.read()
        salvage_commit = state["salvage_commit"]
        assert len(salvage_commit) == 40
        assert state["salvage_branch"] == "main"
        assert state["salvage_verified"] == "not_run"
        assert state["branch"] == "main"
        assert (
            subprocess.run(
                ["git", "show", f"{salvage_commit}:generated.txt"],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            == "salvaged\n"
        )
        assert (
            subprocess.run(
                [
                    "git",
                    "show",
                    f"{salvage_commit}:specs/spec-001-demo/fulfillment-report.md",
                ],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            == "generated\n"
        )
        marker = subprocess.run(
            ["git", "show", f"{salvage_commit}:.harness-build-status.json"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        assert marker.returncode != 0
        assert subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=True,
        ).stdout == ""

    def test_clean_markerless_build_with_dirty_worktree_continues_to_verify(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Clean exit + missing marker + worktree changes is verifiable progress."""
        from harness.build_result import BuildResult

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=worktree, check=True)
        (worktree / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)

        llm_build_runner = MagicMock()

        def write_without_marker(_worktree_path: str, _prompt: str, **_kwargs):
            (worktree / "generated.txt").write_text("usable output\n", encoding="utf-8")
            return BuildResult(
                exit_code=0,
                status="unknown",
                impasse_file=None,
                stdout="done without status file",
                stderr="",
                duration_ms=1000,
            )

        llm_build_runner.exec_build.side_effect = write_without_marker
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = worktree
        gitops.create_worktree.return_value = str(worktree)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "converged"
        assert result.termination_reason == "converged"
        captured = capsys.readouterr()
        assert "BUILD DID NOT COMPLETE" not in captured.err
        state = state_store.read()
        assert state["missing_marker_recoveries"][0]["exit_code"] == 0
        assert state["missing_marker_recoveries"][0]["checkpoint_commit"] is None
        gitops.commit.assert_called_once()
        gitops.push.assert_called_once_with(str(worktree), "main")

    def test_clean_markerless_build_with_head_advance_continues_to_verify(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Clean exit + missing marker + new commit is verifiable progress."""
        from harness.build_result import BuildResult

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=worktree, check=True)
        (worktree / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)

        llm_build_runner = MagicMock()

        def commit_without_marker(_worktree_path: str, _prompt: str, **_kwargs):
            (worktree / "generated.txt").write_text("committed output\n", encoding="utf-8")
            subprocess.run(["git", "add", "generated.txt"], cwd=worktree, check=True)
            subprocess.run(["git", "commit", "-m", "feat: generated output"], cwd=worktree, check=True)
            return BuildResult(
                exit_code=0,
                status="unknown",
                impasse_file=None,
                stdout="done without status file",
                stderr="",
                duration_ms=1000,
            )

        llm_build_runner.exec_build.side_effect = commit_without_marker
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = worktree
        gitops.create_worktree.return_value = str(worktree)

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement something",
        )

        assert result.status == "converged"
        assert result.termination_reason == "converged"
        captured = capsys.readouterr()
        assert "BUILD DID NOT COMPLETE" not in captured.err
        assert subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=True,
        ).stdout == ""
        state = state_store.read()
        recovery = state["missing_marker_recoveries"][0]
        assert recovery["exit_code"] == 0
        assert recovery["head_advanced"] is True
        gitops.push.assert_called_once_with(str(worktree), "main")

    def test_checkpoint_commit_records_task_progress_delta(self, tmp_path: Path) -> None:
        """Ralph commits a dirty worktree when build state shows task progress."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "generated.txt").write_text("new code\n", encoding="utf-8")
        gitops.commit.return_value = "abc123def456"

        before = {
            "build": {
                "completed_tasks": 1,
                "current_phase_group": "phase-2-foundation",
                "task_results": {"T-001": {"status": "DONE"}},
            }
        }
        after = {
            "build": {
                "completed_tasks": 2,
                "current_phase_group": "phase-2-foundation",
                "task_results": {
                    "T-001": {"status": "DONE"},
                    "T-002": {"status": "DONE"},
                },
            }
        }

        with patch.object(controller, "_has_file_changes", return_value=True):
            checkpoint = controller._checkpoint_progress_commit(
                worktree_path=str(worktree),
                before_state=before,
                after_state=after,
                outer_iter=0,
                inner_iter=0,
                phase="build",
            )

        assert checkpoint is not None
        gitops.commit.assert_called_once()
        message = gitops.commit.call_args.args[1]
        assert "harness-checkpoint:" in message
        assert "T-002" in message
        assert "phase-2-foundation" in message
        state = state_store.read()
        assert state["checkpoint_commits"][0]["commit"] == "abc123def456"
        assert state["checkpoint_commits"][0]["task_ids"] == ["T-002"]

    def test_checkpoint_commit_uses_phase_when_task_ids_unknown(self, tmp_path: Path) -> None:
        """Stage 1 records truthful phase/wave metadata instead of fake task IDs."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )
        gitops.commit.return_value = "feedface"
        before = {"build": {"completed_tasks": 0}}
        after = {
            "build": {
                "completed_tasks": 1,
                "current_phase_group": "phase-3-play-loop",
                "task_results": {},
            }
        }

        with patch.object(controller, "_has_file_changes", return_value=True):
            checkpoint = controller._checkpoint_progress_commit(
                worktree_path="/tmp/worktree",
                before_state=before,
                after_state=after,
                outer_iter=1,
                inner_iter=2,
                phase="fix",
            )

        assert checkpoint is not None
        message = gitops.commit.call_args.args[1]
        assert "phase-3-play-loop" in message
        assert "tasks-unknown" in message
        state = state_store.read()
        assert state["checkpoint_commits"][0]["task_ids"] == []
        assert state["checkpoint_commits"][0]["phase_group"] == "phase-3-play-loop"

    def test_checkpoint_commit_skips_when_no_file_changes(self, tmp_path: Path) -> None:
        """Progress metadata alone does not create empty checkpoint commits."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
        )

        with patch.object(controller, "_has_file_changes", return_value=False):
            checkpoint = controller._checkpoint_progress_commit(
                worktree_path="/tmp/worktree",
                before_state={"build": {"completed_tasks": 0}},
                after_state={"build": {"completed_tasks": 1}},
                outer_iter=0,
                inner_iter=0,
                phase="build",
            )

        assert checkpoint is None
        gitops.commit.assert_not_called()
        assert "checkpoint_commits" not in state_store.read()

    def test_run_loop_checkpoints_after_successful_build_progress(
        self, tmp_path: Path
    ) -> None:
        """Ralph checkpoints progress after a build invocation before verification."""
        from harness.build_result import BuildResult

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=worktree, check=True)
        (worktree / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)

        llm_build_runner = MagicMock()

        def complete_one_task(_worktree_path: str, _prompt: str, **_kwargs):
            state = state_store.read()
            state["build"] = {
                "completed_tasks": 1,
                "current_phase_group": "phase-2-foundation",
                "task_results": {"T-001": {"status": "DONE"}},
            }
            state_store.write(state)
            (worktree / "generated.txt").write_text("task output\n", encoding="utf-8")
            (worktree / ".harness-build-status.json").write_text(
                '{"status":"done"}\n',
                encoding="utf-8",
            )
            return BuildResult(
                exit_code=0,
                status="done",
                impasse_file=None,
                stdout="",
                stderr="",
                duration_ms=1000,
            )

        llm_build_runner.exec_build.side_effect = complete_one_task
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = worktree
        gitops.create_worktree.return_value = str(worktree)

        def commit_worktree(_path: str, message: str) -> str:
            subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Echelon Harness",
                    "-c",
                    "user.email=echelon-harness@example.invalid",
                    "commit",
                    "-m",
                    message,
                    "--allow-empty",
                ],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            return subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

        gitops.commit.side_effect = commit_worktree

        with patch.object(
            controller,
            "_exec_verify",
            return_value=VerifyResult(passed=True, failures=[]),
        ):
            result = controller.run_loop(
                max_outer=1,
                max_inner=0,
                build_prompt="implement one task",
            )

        assert result.status == "converged"
        state = state_store.read()
        assert state["checkpoint_commits"][0]["task_ids"] == ["T-001"]

    def test_verify_spec_session_limit_blocks_without_feedback_loop(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Provider limits during verify-spec are checkpoint blocks, not fix prompts."""
        from harness.build_result import BuildResult

        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=worktree, check=True)
        (worktree / "README.md").write_text("base\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=base req=FR-001 depends=none\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)

        llm_build_runner = MagicMock()

        def complete_one_task(_worktree_path: str, _prompt: str, **_kwargs):
            (worktree / "src").mkdir(exist_ok=True)
            (worktree / "src" / "generated.py").write_text("print('ok')\n", encoding="utf-8")
            return BuildResult(
                exit_code=0,
                status="done",
                impasse_file=None,
                stdout="",
                stderr="",
                duration_ms=1000,
                task_ids=["T-001"],
            )

        llm_build_runner.exec_build.side_effect = complete_one_task
        llm_build_runner.exec_feedback = MagicMock()
        fulfillment_runner = MagicMock()
        fulfillment_runner.refresh.return_value = FulfillmentRefreshResult(
            status="provider_session_limit",
            exit_code=1,
            scope="full",
            reason=(
                "You've hit your session limit · resets 1:30pm; existing "
                "fulfillment report was verified at old123, current HEAD is new456"
            ),
            report_path=str(spec_dir / "fulfillment-report.md"),
        )
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
            fulfillment_runner=fulfillment_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = worktree
        gitops.create_worktree.return_value = str(worktree)

        def commit_worktree(_path: str, message: str) -> str:
            subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Echelon Harness",
                    "-c",
                    "user.email=echelon-harness@example.invalid",
                    "commit",
                    "-m",
                    message,
                    "--allow-empty",
                ],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            return subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

        gitops.commit.side_effect = commit_worktree

        result = controller.run_loop(
            max_outer=1,
            max_inner=3,
            build_prompt="implement one task",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "build_incomplete"
        state = state_store.read()
        assert state["build_status"] == "provider_session_limit"
        assert state["build_reason"] == "verify-spec provider session limit"
        assert state["fulfillment_refresh"]["status"] == "provider_session_limit"
        assert state["checkpoint_commits"][0]["task_ids"] == ["T-001"]
        assert "salvage_commit" not in state
        llm_build_runner.exec_feedback.assert_not_called()
        captured = capsys.readouterr()
        assert "HARNESS — PROVIDER SESSION LIMIT" in captured.err
        assert "verify-spec fulfillment refresh" in captured.err

    def test_clean_markerless_build_keeps_checkpoint_then_verifies(
        self, tmp_path: Path
    ) -> None:
        """If a clean markerless build advances progress, verify the checkpoint."""
        from harness.build_result import BuildResult

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=worktree, check=True)
        (worktree / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)

        llm_build_runner = MagicMock()

        def advance_progress_without_marker(_worktree_path: str, _prompt: str, **_kwargs):
            state = state_store.read()
            state["build"] = {
                "completed_tasks": 1,
                "current_phase_group": "phase-2-foundation",
                "task_results": {"T-001": {"status": "DONE"}},
            }
            state_store.write(state)
            (worktree / "generated.txt").write_text("partial task output\n", encoding="utf-8")
            return BuildResult(
                exit_code=0,
                status="unknown",
                impasse_file=None,
                stdout="missing marker",
                stderr="",
                duration_ms=1000,
            )

        llm_build_runner.exec_build.side_effect = advance_progress_without_marker
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[{"passed": True, "failures": []}],
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = worktree
        gitops.create_worktree.return_value = str(worktree)

        def commit_worktree(_path: str, message: str) -> str:
            subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Echelon Harness",
                    "-c",
                    "user.email=echelon-harness@example.invalid",
                    "commit",
                    "-m",
                    message,
                    "--allow-empty",
                ],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            return subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

        gitops.commit.side_effect = commit_worktree

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_prompt="implement one task",
        )

        assert result.status == "converged"
        assert result.termination_reason == "converged"
        state = state_store.read()
        checkpoint = state["checkpoint_commits"][0]
        assert checkpoint["task_ids"] == ["T-001"]
        assert checkpoint["commit"]
        assert state["missing_marker_recoveries"][0]["checkpoint_commit"] == checkpoint["commit"]
        assert "salvage_commit" not in state
        assert subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=True,
        ).stdout == ""

    def test_inner_task_progress_with_remaining_fulfillment_gaps_checkpoints_outer_cap(
        self, tmp_path: Path
    ) -> None:
        """Task progress plus aggregate gaps is continuation, not failed convergence."""
        from harness.build_result import BuildResult
        from harness.verify_result import FailureCategory, FailureEntry

        worktree = tmp_path / "worktree"
        spec_dir = worktree / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "- [x] T-001 complexity=standard phase=demo req=FR-001 depends=none\n"
            "- [ ] T-002 complexity=standard phase=demo req=FR-002 depends=none\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=worktree, check=True)
        subprocess.run(["git", "add", "."], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True)

        llm_build_runner = MagicMock()
        llm_build_runner.exec_build.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            stdout="",
            stderr="",
            duration_ms=100,
            task_ids=[],
        )
        llm_build_runner.exec_feedback.return_value = BuildResult(
            exit_code=0,
            status="done",
            impasse_file=None,
            reason="implemented T-002",
            stdout="",
            stderr="",
            duration_ms=100,
            task_ids=["T-002"],
        )
        controller, _provider, gitops, state_store = _make_controller(
            tmp_path,
            llm_build_runner=llm_build_runner,
        )
        controller._config.verify_command = f"{sys.executable} -c pass"
        gitops.base_dir = worktree
        gitops.create_worktree.return_value = str(worktree)

        def commit_worktree(_path: str, message: str) -> str:
            subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Echelon Harness",
                    "-c",
                    "user.email=echelon-harness@example.invalid",
                    "commit",
                    "-m",
                    message,
                    "--allow-empty",
                ],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            return subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

        gitops.commit.side_effect = commit_worktree
        gaps = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    FailureCategory.OTHER,
                    "fulfillment-gaps",
                    "full spec still has unresolved gaps",
                )
            ],
        )

        with patch.object(
            controller,
            "_exec_verify",
            return_value=VerifyResult(passed=True, failures=[]),
        ), patch.object(
            controller,
            "_refresh_fulfillment_report",
            return_value=gaps,
        ), patch.object(
            controller,
            "_apply_fulfillment_gate",
            side_effect=lambda verify, _worktree: verify,
        ):
            result = controller.run_loop(
                max_outer=1,
                max_inner=3,
                build_prompt="continue implementation",
            )

        assert result.status == "blocked"
        assert result.termination_reason == "checkpoint_outer_cap"
        assert result.final_verify is gaps
        state = state_store.read()
        assert state["build"]["task_results"]["T-002"]["status"] == "DONE"
        assert state["checkpoint_commits"][0]["task_ids"] == ["T-002"]
        assert not state.get("escalation_file")

    def test_converges_second_outer_iteration(self, tmp_path: Path) -> None:
        """Verify fails first outer, passes on second outer -> converged."""
        # First outer: verify fails, inner loop fails (different errors to avoid same-failure)
        # Second outer: verify passes immediately
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[
                # Outer 0: initial verify fails
                {"passed": False, "failures": [{"category": "test", "id": "t1", "error": "fail-a"}]},
                # Outer 0, inner 1: re-verify fails (different error)
                {"passed": False, "failures": [{"category": "test", "id": "t2", "error": "fail-b"}]},
                # Outer 1: initial verify passes
                {"passed": True, "failures": []},
            ],
        )

        result = controller.run_loop(max_outer=5, max_inner=1)

        assert result.status == "converged"
        assert result.termination_reason == "converged"
        assert result.outer_iterations == 2


@pytest.mark.unit
class TestOuterLoopCap:
    """Test outer loop hits cap."""

    def test_outer_cap_reached(self, tmp_path: Path) -> None:
        """All verifications fail -> outer_cap."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[
                {"passed": False, "failures": [{"category": "test", "id": f"t{i}", "error": f"fail-{i}"}]}
                for i in range(100)  # More than enough for all iterations
            ],
        )

        result = controller.run_loop(max_outer=2, max_inner=1)

        assert result.status == "failed"
        assert result.termination_reason == "outer_cap"
        assert result.outer_iterations == 2


@pytest.mark.unit
class TestBudgetExhaustion:
    """Test budget exhaustion terminates loop."""

    def test_budget_exhaustion(self, tmp_path: Path) -> None:
        """Token budget hit -> budget_exhausted."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[
                {"passed": False, "failures": [], "token_usage": 100000}
                for _ in range(20)
            ],
        )

        # Very tight budget
        result = controller.run_loop(max_outer=10, max_inner=3, token_budget=100)

        assert result.status == "blocked"
        assert result.termination_reason == "budget_exhausted"


@pytest.mark.unit
class TestCancelRequested:
    """Test cancel_requested terminates between iterations."""

    def test_cancel_terminates(self, tmp_path: Path) -> None:
        """cancel_requested flag -> killed_by_coordinator."""
        controller, provider, gitops, state_store = _make_controller(
            tmp_path,
            verify_results=[
                {"passed": False, "failures": [{"category": "test", "id": "t1", "error": "fail"}]}
                for _ in range(20)
            ],
        )

        # Set cancel_requested after first exec
        original_exec = provider.exec

        def cancelling_exec(handle, cmd, **kwargs):
            result = original_exec(handle, cmd, **kwargs)
            if provider._exec_count >= 2:
                state = state_store.read()
                state["cancel_requested"] = True
                state_store.write(state)
            return result

        provider.exec = cancelling_exec

        result = controller.run_loop(max_outer=5, max_inner=3)

        assert result.status == "cancelled"
        assert result.termination_reason == "killed_by_coordinator"


@pytest.mark.unit
class TestSignalHandling:
    """Test SIGTERM handling."""

    def test_interrupt_flag_set(self, tmp_path: Path) -> None:
        """SIGTERM sets _interrupted flag."""
        controller, _, _, _ = _make_controller(
            tmp_path,
            verify_results=[{"passed": False, "failures": []}],
        )
        controller._interrupted = False
        controller._handle_signal(signal.SIGTERM, None)
        assert controller._interrupted is True


@pytest.mark.unit
class TestLlmProviderDispatch:
    def test_exec_build_uses_llm_build_runner_when_set(self, tmp_path: Path) -> None:
        """When llm_build_runner is set, _exec_build delegates to it."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=100,
        )

        controller, provider, _, _ = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )
        result = controller._exec_build(
            handle=MagicMock(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(tmp_path),
            prompt="build this",
        )

        build_runner.exec_build.assert_called_once()
        assert build_runner.exec_build.call_args.args[0] == str(tmp_path)
        assert "build this" in build_runner.exec_build.call_args.args[1]
        assert result["passed"] is True

    def test_exec_build_hides_mutable_harness_state_from_build_prompt(
        self, tmp_path: Path
    ) -> None:
        """LLM build prompts receive bounded facts, not Ralph's mutable state path."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=100,
        )

        controller, _, _, state_store = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )
        worktree = tmp_path / "worktree"

        controller._exec_build(
            handle=MagicMock(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(worktree),
            prompt="build this",
        )

        sent_prompt = build_runner.exec_build.call_args.args[1]
        assert f"state_file: {state_store.state_file}" not in sent_prompt
        assert f"state_dir: {state_store.state_dir}" not in sent_prompt
        assert "Ralph state is not a build input" in sent_prompt
        assert "Do not search for state.json" in sent_prompt
        assert "build this" in sent_prompt

    def test_exec_build_passes_containment_policy_file_to_runner(
        self, tmp_path: Path
    ) -> None:
        """Provider backends receive the same containment policy named in prompt."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=100,
        )

        controller, _, _, state_store = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )
        worktree = tmp_path / "worktree"

        controller._exec_build(
            handle=MagicMock(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(worktree),
            prompt="build this",
        )

        policy_file = state_store.state_dir / "delivery-containment-policy.json"
        assert build_runner.exec_build.call_args.kwargs[
            "containment_policy_file"
        ] == str(policy_file)
        assert policy_file.exists()

    def test_exec_build_injects_external_spec_paths_for_polyrepo_target(
        self, tmp_path: Path
    ) -> None:
        """Polyrepo target prompts receive external spec paths from harness state."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=100,
        )

        controller, _, gitops, state_store = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )
        project_root = tmp_path / "polyrepo"
        spec_dir = project_root / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text("- [ ] T-001 req=FR-001\n", encoding="utf-8")
        gitops.base_dir = project_root
        state = state_store.read()
        state["target_repo"] = "target-app"
        state["target_path"] = str(project_root / "target-app")
        state["spec_dir"] = str(spec_dir)
        state["spec_file"] = str(spec_dir / "spec.md")
        state["tasks_file"] = str(spec_dir / "tasks.md")
        state_store.write(state)
        worktree = tmp_path / "polyrepo" / "runs" / "build-1" / "worktrees" / "default" / "iter-0"

        controller._exec_build(
            handle=MagicMock(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(worktree),
            prompt="build this",
        )

        sent_prompt = build_runner.exec_build.call_args.args[1]
        assert "spec_artifacts_mode: external" in sent_prompt
        assert f"spec_dir: {spec_dir}" in sent_prompt
        assert f"tasks_file: {spec_dir / 'tasks.md'}" in sent_prompt
        assert f"spec_file: {spec_dir / 'spec.md'}" in sent_prompt
        assert "Do not discover spec artifacts with `find`, `ls`, globbing" in sent_prompt

    def test_exec_build_falls_back_to_sandbox_when_no_llm_build_runner(self, tmp_path: Path) -> None:
        """When llm_build_runner is None, _exec_build uses provider.exec() even with args."""
        controller, provider, _, _ = _make_controller(tmp_path, llm_build_runner=None)

        result = controller._exec_build(
            handle=MagicMock(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(tmp_path),
            prompt="build this",
        )

        assert provider._exec_count == 1
        assert result["passed"] is True

    def test_exec_feedback_uses_llm_build_runner_when_set(self, tmp_path):
        """When llm_build_runner is set, _exec_feedback delegates to it."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult
        from harness.verify_result import VerifyResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        build_runner.exec_feedback.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=100,
        )

        controller, _, _, state_store = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )
        verify = VerifyResult(passed=False, failures=[], duration_s=1.0, token_usage=0)

        result = controller._exec_feedback(
            handle=MagicMock(),
            verify_result=verify,
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(tmp_path),
            prompt="fix this",
        )

        build_runner.exec_feedback.assert_called_once()
        assert build_runner.exec_feedback.call_args.args[0] == str(tmp_path)
        assert "fix this" in build_runner.exec_feedback.call_args.args[1]
        policy_file = state_store.state_dir / "delivery-containment-policy.json"
        assert build_runner.exec_feedback.call_args.kwargs[
            "containment_policy_file"
        ] == str(policy_file)
        assert policy_file.exists()
        assert result["passed"] is True
        assert result["impasse"] is False

    def test_exec_build_falls_back_when_prompt_empty(self, tmp_path: Path) -> None:
        """When prompt is empty, _exec_build falls back to sandbox even if build runner set."""
        from harness.llm_build_runner import LlmBuildRunner

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, provider, _, _ = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        result = controller._exec_build(
            handle=MagicMock(),
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(tmp_path),
            prompt="",  # empty → fallback
        )

        build_runner.exec_build.assert_not_called()
        assert provider._exec_count == 1


@pytest.mark.unit
class TestPromptHelpers:
    def test_make_iter_prompt_iter0_returns_base(self, tmp_path: Path) -> None:
        controller, *_ = _make_controller(tmp_path)
        result = controller._make_iter_prompt("spec 001", outer_iter=0, last_failures="")
        assert result == "spec 001"

    def test_make_iter_prompt_iter1_appends_failures(self, tmp_path: Path) -> None:
        controller, *_ = _make_controller(tmp_path)
        result = controller._make_iter_prompt("spec 001", outer_iter=1, last_failures="[lint] f1: error")
        assert "iteration 1" in result
        assert "[lint] f1: error" in result
        assert "spec 001" in result

    def test_make_iter_prompt_empty_base_returns_empty(self, tmp_path: Path) -> None:
        controller, *_ = _make_controller(tmp_path)
        result = controller._make_iter_prompt("", outer_iter=1, last_failures="error")
        assert result == ""

    def test_make_feedback_prompt_contains_failures(self, tmp_path: Path) -> None:
        from harness.verify_result import FailureEntry, FailureCategory, VerifyResult
        controller, *_ = _make_controller(tmp_path)
        verify = VerifyResult(
            passed=False,
            failures=[FailureEntry(category=FailureCategory.TEST, id="t1", error="AssertionError")],
            duration_s=1.0,
            token_usage=0,
        )
        result = controller._make_feedback_prompt("spec 001", verify, inner_iter=1)
        assert "AssertionError" in result
        assert "spec 001" in result
        assert "re-running" in result

    def test_make_feedback_prompt_overrides_manual_verify_spec_repair(
        self, tmp_path: Path
    ) -> None:
        from harness.verify_result import FailureCategory, FailureEntry, VerifyResult

        controller, *_ = _make_controller(tmp_path)
        verify = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id="fulfillment-report-stale",
                    error=(
                        "fulfillment report is stale for current HEAD abc123: "
                        "/tmp/specs/001/fulfillment-report.md was verified at old456. "
                        "Run `echelon spec verify spec-001` before convergence."
                    ),
                )
            ],
            duration_s=1.0,
            token_usage=0,
        )

        result = controller._make_feedback_prompt("spec 001", verify, inner_iter=1)

        assert "Do not run `echelon spec verify`" in result
        assert "Ralph owns fulfillment refresh" in result
        assert "Run `echelon spec verify spec-001` before convergence." in result

    @pytest.mark.parametrize(
        "failure_id",
        ["fulfillment-report-stale", "fulfillment-report-scoped"],
    )
    def test_inner_loop_does_not_dispatch_llm_for_fulfillment_freshness_failure(
        self, tmp_path: Path, failure_id: str
    ) -> None:
        from harness.verify_result import FailureCategory, FailureEntry, VerifyResult

        controller, *_ = _make_controller(tmp_path)
        controller._exec_feedback = MagicMock()
        verify = VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id=failure_id,
                    error=f"{failure_id} is Ralph-owned fulfillment evidence",
                )
            ],
            duration_s=1.0,
            token_usage=0,
        )

        result = controller._run_inner_loop(
            handle=SandboxHandle(id="mock-sandbox-1", session_id="sess-1"),
            verify_result=verify,
            outer_iter=0,
            max_inner=3,
            tokens_used=0,
            token_budget=None,
            state={},
            build_command="echelon build",
            strategy_context="",
            worktree_path=str(tmp_path),
            build_prompt="spec 001",
        )

        controller._exec_feedback.assert_not_called()
        assert result["inner_count"] == 0
        assert result["final_verify"] is verify


@pytest.mark.unit
class TestSignalDuringBuild:
    """SIGINT during build must set interrupted status without running verify."""

    def test_sigint_during_build_yields_interrupted_status(self, tmp_path: Path) -> None:
        """_interrupted set inside exec_build → status=interrupted, final_verify=None."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, provider, gitops, _ = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        def build_sets_interrupted(
            worktree_path: str, prompt: str, **_kwargs
        ) -> BuildResult:
            controller._interrupted = True
            return BuildResult(
                exit_code=1, status="unknown", impasse_file=None,
                stdout="", stderr="", duration_ms=500,
            )

        build_runner.exec_build.side_effect = build_sets_interrupted

        result = controller.run_loop(
            max_outer=2,
            build_command="echelon codegen",
            build_prompt="build a hello world",
        )

        assert result.status == "interrupted"
        assert result.termination_reason == "user_cancel"
        # Verify must not have run — an interrupted build has no verified output
        assert result.final_verify is None


@pytest.mark.unit
class TestVerifyLocallyUnknownProjectType:
    """Unknown project type must fail verification, not silently pass."""

    def test_unknown_project_type_returns_failed_verify(self, tmp_path: Path) -> None:
        """Empty worktree → VerifyResult(passed=False) with id='local-verify-skipped'."""
        from harness.verify_result import FailureCategory

        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        result = controller._exec_verify_locally(str(worktree))

        assert result.passed is False
        assert len(result.failures) == 1
        assert result.failures[0].id == "local-verify-skipped"
        assert result.failures[0].category == FailureCategory.BUILD

    def test_unknown_project_type_blocks_with_verify_command_needed(self, tmp_path: Path) -> None:
        """Build succeeds + unknown project type → status=blocked, reason=verify_command_needed."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, _, gitops, _ = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)

        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=500,
        )

        result = controller.run_loop(
            max_outer=1,
            max_inner=0,
            build_command="echelon codegen",
            build_prompt="build a hello world",
        )

        assert result.status == "blocked"
        assert result.termination_reason == "verify_command_needed"
        assert result.final_verify is not None
        assert result.final_verify.passed is False
        assert any(f.id == "local-verify-skipped" for f in result.final_verify.failures)


@pytest.mark.unit
class TestVerifyCommandNeeded:
    """local-verify-skipped escalates to blocked, not silent failure."""

    def test_verify_command_runs_from_worktree_not_workspace_root(
        self, tmp_path: Path
    ) -> None:
        """Configured verification must exercise the candidate worktree."""
        controller, _, gitops, _ = _make_controller(tmp_path)
        workspace = tmp_path / "workspace"
        worktree = tmp_path / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        workspace.mkdir()
        script = worktree / "scripts" / "verify-cwd.sh"
        script.parent.mkdir(parents=True)
        marker = tmp_path / "verify-cwd.txt"
        script.write_text(f"pwd > {marker}\n", encoding="utf-8")
        script.chmod(0o755)
        gitops.base_dir = workspace
        controller._config = HarnessConfig(
            **{
                **controller._config.__dict__,
                "verify_command": "bash scripts/verify-cwd.sh",
            }
        )

        result = controller._exec_verify_locally(str(worktree))

        assert result.passed is True
        assert marker.read_text(encoding="utf-8").strip() == str(worktree)

    def test_banner_printed_to_stderr(self, tmp_path: Path, capsys) -> None:
        """Unknown project type → escalation banner printed to stderr."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, _, gitops, _ = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=500,
        )

        controller.run_loop(max_outer=1, max_inner=0,
                            build_command="echelon codegen", build_prompt="x")
        err = capsys.readouterr().err
        assert "TEST RUNNER MISSING" in err
        assert "verify_command" in err
        assert "echelon delivery continue" in err

    def test_state_written_as_blocked(self, tmp_path: Path) -> None:
        """Unknown project type → StateStore reflects blocked + verify_command_needed."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, _, gitops, state_store = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=500,
        )

        controller.run_loop(max_outer=1, max_inner=0,
                            build_command="echelon codegen", build_prompt="x")
        state = state_store.read()
        assert state["status"] == "blocked"
        assert state["termination_reason"] == "verify_command_needed"

    def test_does_not_iterate_build_loop(self, tmp_path: Path) -> None:
        """Hard-stop after first verify_command_needed — LLM not called again."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, _, gitops, _ = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=500,
        )

        controller.run_loop(max_outer=5, max_inner=3,
                            build_command="echelon codegen", build_prompt="x")
        # Build must only have been called once (hard stop, no retries)
        assert build_runner.exec_build.call_count == 1

    def test_resume_with_verify_command_configured_reruns(self, tmp_path: Path) -> None:
        """After blocking, resume with verify_command set → loop re-enters."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult
        from harness.config import HarnessConfig

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, _, gitops, state_store = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=500,
        )

        # First run: blocks
        controller.run_loop(max_outer=1, max_inner=0,
                            build_command="echelon codegen", build_prompt="x")
        assert state_store.read()["termination_reason"] == "verify_command_needed"

        # Now configure verify_command on the controller's config
        controller._config = HarnessConfig(
            **{**controller._config.__dict__, "verify_command": "pytest"}
        )
        build_runner.exec_build.reset_mock()
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=500,
        )

        with patch("subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            result = controller.run_loop(max_outer=1, max_inner=0,
                                         build_command="echelon codegen", build_prompt="x")

        # Loop re-entered: build was called again
        assert build_runner.exec_build.call_count == 1

    def test_resume_without_verify_command_still_blocked(self, tmp_path: Path) -> None:
        """Resume without configuring verify_command → still blocked, banner printed."""
        from harness.llm_build_runner import LlmBuildRunner
        from harness.build_result import BuildResult

        build_runner = MagicMock(spec=LlmBuildRunner)
        controller, _, gitops, state_store = _make_controller(
            tmp_path, llm_build_runner=build_runner
        )

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        gitops.create_worktree.return_value = str(worktree)
        build_runner.exec_build.return_value = BuildResult(
            exit_code=0, status="done", impasse_file=None,
            stdout="", stderr="", duration_ms=500,
        )

        # First run blocks
        controller.run_loop(max_outer=1, max_inner=0,
                            build_command="echelon codegen", build_prompt="x")

        # Resume without adding verify_command → still blocked
        result = controller.run_loop(max_outer=1, max_inner=0,
                                     build_command="echelon codegen", build_prompt="x")
        assert result.status == "blocked"
        assert result.termination_reason == "verify_command_needed"


@pytest.mark.unit
class TestVerifyLocallySwift:
    """Swift project detection and verification."""

    def test_root_package_swift_detected(self, tmp_path: Path) -> None:
        """Package.swift at worktree root → swift build + swift test."""
        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "Package.swift").write_text('// swift-tools-version:5.9\n')

        with patch("subprocess.run") as mock_run, \
             patch("shutil.which", return_value="/usr/bin/swift"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = controller._exec_verify_locally(str(worktree))

        assert result.passed is True
        calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["swift", "build"] in calls
        assert ["swift", "test"] in calls

    def test_nested_package_swift_detected(self, tmp_path: Path) -> None:
        """Package.swift in a subdirectory → detected and used as package dir."""
        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        pkg_dir = worktree / "Packages" / "MyLib"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "Package.swift").write_text('// swift-tools-version:5.9\n')

        with patch("subprocess.run") as mock_run, \
             patch("shutil.which", return_value="/usr/bin/swift"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = controller._exec_verify_locally(str(worktree))

        assert result.passed is True
        assert mock_run.call_args_list[0].kwargs.get("cwd") == str(pkg_dir) or \
               mock_run.call_args_list[0].args[1] == str(pkg_dir) or \
               all(c.kwargs.get("cwd") == str(pkg_dir) for c in mock_run.call_args_list)

    def test_swift_build_failure_reported(self, tmp_path: Path) -> None:
        """swift build non-zero exit → failure with id='swift-build', test not run."""
        from harness.verify_result import FailureCategory

        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "Package.swift").write_text('// swift-tools-version:5.9\n')

        def _side_effect(cmd, **kwargs):
            if cmd == ["swift", "build"]:
                return MagicMock(returncode=1, stdout="error: compile error", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_side_effect), \
             patch("shutil.which", return_value="/usr/bin/swift"):
            result = controller._exec_verify_locally(str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "swift-build"
        assert result.failures[0].category == FailureCategory.BUILD

    def test_swift_test_failure_reported(self, tmp_path: Path) -> None:
        """swift test non-zero exit → failure with id='swift-test'."""
        from harness.verify_result import FailureCategory

        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "Package.swift").write_text('// swift-tools-version:5.9\n')

        def _side_effect(cmd, **kwargs):
            if cmd == ["swift", "test"]:
                return MagicMock(returncode=1, stdout="", stderr="Test failed: assertion error")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_side_effect), \
             patch("shutil.which", return_value="/usr/bin/swift"):
            result = controller._exec_verify_locally(str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "swift-test"
        assert result.failures[0].category == FailureCategory.TEST

    def test_swift_not_on_path_returns_clear_error(self, tmp_path: Path) -> None:
        """swift toolchain absent → passed=False, id='swift-not-found'."""
        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "Package.swift").write_text('// swift-tools-version:5.9\n')

        with patch("shutil.which", return_value=None):
            result = controller._exec_verify_locally(str(worktree))

        assert result.passed is False
        assert result.failures[0].id == "swift-not-found"
        assert "swift" in result.failures[0].error.lower()

    def test_python_takes_priority_over_swift(self, tmp_path: Path) -> None:
        """pyproject.toml + Package.swift → Python path taken, not Swift."""
        controller, _, _, _ = _make_controller(tmp_path)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "Package.swift").write_text('// swift-tools-version:5.9\n')
        (worktree / "pyproject.toml").write_text('[project]\nname = "x"\n')

        with patch.object(controller, "_exec_verify_python") as mock_py, \
             patch.object(controller, "_exec_verify_swift") as mock_sw:
            mock_py.return_value = MagicMock(passed=True, failures=[])
            result = controller._exec_verify_locally(str(worktree))

        mock_py.assert_called_once()
        mock_sw.assert_not_called()
