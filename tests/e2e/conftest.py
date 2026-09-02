"""E2E test fixtures and configuration.

Provides shared fixtures for ralph-loop E2E tests:
- Stub LLM setup
- Temp directories for state/escalation/git
- Mock gitops manager
- Pre-configured RalphController and StrategyCoordinator factories
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from harness.config import HarnessConfig, NetworkConfig, ResourceLimits
from harness.escalation import EscalationHandler
from harness.mode import ModeController
from harness.state import StateStore

from tests.e2e.stub_llm import StubLLM, StubSandboxProvider


# === Fixtures ===


@pytest.fixture
def tmp_harness_dir(tmp_path: Path) -> Path:
    """Create a temporary harness directory structure."""
    (tmp_path / "runs" / "state").mkdir(parents=True)
    (tmp_path / "runs" / "escalations").mkdir(parents=True)
    (tmp_path / "runs" / "strategies").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def harness_config() -> HarnessConfig:
    """Create a minimal valid HarnessConfig."""
    return HarnessConfig(
        target_repo="git@example.com:test/repo.git",
        target_default_branch="main",
        provider="docker",
        resource_limits=ResourceLimits(),
        network=NetworkConfig(),
        base_image="python:3.9-slim",
    )


@pytest.fixture
def stub_llm() -> StubLLM:
    """Create a fresh StubLLM in converge_on_first mode."""
    return StubLLM(mode="converge_on_first", tokens_per_call=500)


@pytest.fixture
def stub_provider(stub_llm: StubLLM) -> StubSandboxProvider:
    """Create a StubSandboxProvider wrapping the stub LLM."""
    return StubSandboxProvider(stub_llm)


class MockGitOps:
    """Mock GitOpsManager for E2E tests.

    Tracks calls for assertion while using temporary git repositories where
    delivery provenance needs a real committed HEAD.
    """

    def __init__(self, tmp_dir: Path) -> None:
        self._tmp_dir = tmp_dir
        self.base_dir = tmp_dir
        self.worktrees_created: list = []
        self.worktrees_destroyed: list = []
        self.commits: list = []
        self.pushes: list = []
        self.local_merges: list = []
        self.pr_created = False
        self.pr_promoted = False
        self.pr_merged = False
        self.pr_url: Optional[str] = None
        self._default_branch = "main"
        self._latest_worktrees: dict[tuple[str, str, str], str] = {}

    def create_worktree(
        self, spec_id: str, strategy_id: str, outer_iter: int,
        base_branch: str | None = None, build_id: str = "",
        prepare_codegraph: bool = False,
        fresh_branch: bool = False,
        fresh_branch_base: str | None = None,
    ) -> str:
        """Create a fake worktree directory with a real git repo so that
        _has_file_changes works correctly (avoids false no-progress escalation).
        """
        import subprocess as _sp
        wt_path = self._tmp_dir / "runs" / "worktrees" / f"{spec_id}-{strategy_id}-{outer_iter}"
        wt_path.mkdir(parents=True, exist_ok=True)
        # Initialize a real committed checkout so coordinator provenance reads
        # a valid HEAD exactly as it would from a delivery worktree.
        try:
            _sp.run(["git", "init"], cwd=str(wt_path), capture_output=True, check=False)
            _sp.run(["git", "config", "user.email", "test@test.com"], cwd=str(wt_path), capture_output=True, check=False)
            _sp.run(["git", "config", "user.name", "Test"], cwd=str(wt_path), capture_output=True, check=False)
            (wt_path / "README.md").write_text("initial test worktree\n")
            _sp.run(["git", "add", "README.md"], cwd=str(wt_path), capture_output=True, check=False)
            _sp.run(
                ["git", "commit", "--allow-empty", "-m", "initial test worktree"],
                cwd=str(wt_path), capture_output=True, check=False,
            )
            # Keep a change until Ralph commits it, exercising the real
            # commit/provenance path without triggering no-progress first.
            (wt_path / "stub_change.txt").write_text(f"iter-{outer_iter}")
        except Exception:
            pass
        self.worktrees_created.append(str(wt_path))
        self._latest_worktrees[(spec_id, strategy_id, build_id)] = str(wt_path)
        return str(wt_path)

    def find_feature_branch(self, spec_id: str) -> None:
        """Model a new target repository with no pre-existing feature branch."""
        return None

    def destroy_worktree(self, worktree_path: str, keep_branch: bool = False) -> None:
        """Record worktree destruction."""
        self.worktrees_destroyed.append(worktree_path)

    def commit(
        self,
        worktree_path: str,
        message: str,
        *,
        exclude_paths: tuple[str, ...] = (),
    ) -> None:
        """Record and create a real worktree commit for provenance checks."""
        self.commits.append({"path": worktree_path, "message": message})
        subprocess.run(["git", "add", "-A"], cwd=worktree_path, capture_output=True, check=False)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", message],
            cwd=worktree_path, capture_output=True, check=False,
        )

    def get_latest_worktree(
        self, spec_id: str, strategy_id: str, *, build_id: str = ""
    ) -> str | None:
        """Return the exact latest worktree registered for delivery provenance."""
        exact = self._latest_worktrees.get((spec_id, strategy_id, build_id))
        if exact is not None:
            return exact
        matches = [
            path for (known_spec, known_strategy, _), path in self._latest_worktrees.items()
            if known_spec == spec_id and known_strategy == strategy_id
        ]
        return matches[-1] if matches else None

    def push(self, worktree_path: str, branch: str) -> None:
        """Record push."""
        self.pushes.append({"path": worktree_path, "branch": branch})

    def local_merge(self, branch: str, spec_id: str, spec_name: str = "") -> None:
        """Record target default-branch landing."""
        self.local_merges.append({
            "branch": branch,
            "spec_id": spec_id,
            "spec_name": spec_name,
            "default_branch": self._default_branch,
        })

    def create_draft_pr(
        self, branch: str, spec_id: str, strategy_id: str,
    ) -> Optional[str]:
        """Create a fake draft PR."""
        self.pr_created = True
        self.pr_url = f"https://github.com/test/repo/pull/1"
        return self.pr_url

    def promote_pr_ready(self, pr_url: str) -> None:
        """Record PR promotion."""
        self.pr_promoted = True

    def merge_pr(self, pr_url: str) -> bool:
        """Record PR merge."""
        self.pr_merged = True
        return True

    def get_default_branch(self) -> str:
        """Return default branch."""
        return self._default_branch


@pytest.fixture
def mock_gitops(tmp_harness_dir: Path) -> MockGitOps:
    """Create a MockGitOps instance."""
    return MockGitOps(tmp_harness_dir)


def make_ralph_controller(
    *,
    stub_llm: StubLLM,
    tmp_dir: Path,
    harness_config: HarnessConfig,
    mode: str = "semi",
    spec_id: str = "test-spec",
    strategy_id: str = "default",
    mock_gitops: Optional[MockGitOps] = None,
) -> tuple:
    """Factory for creating a configured RalphController with all dependencies.

    Returns (controller, state_store, mock_gitops, stub_provider, escalation_handler).
    """
    from harness.ralph import RalphController

    state_dir = tmp_dir / "runs" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    state_store = StateStore(state_dir, spec_id, strategy_id)
    mode_controller = ModeController(mode)
    escalation_handler = EscalationHandler(str(tmp_dir / "runs"))
    stub_provider = StubSandboxProvider(stub_llm)

    if mock_gitops is None:
        mock_gitops = MockGitOps(tmp_dir)

    controller = RalphController(
        provider=stub_provider,
        gitops=mock_gitops,
        state_store=state_store,
        mode_controller=mode_controller,
        escalation_handler=escalation_handler,
        spec_id=spec_id,
        strategy_id=strategy_id,
        config=harness_config,
    )

    return controller, state_store, mock_gitops, stub_provider, escalation_handler
