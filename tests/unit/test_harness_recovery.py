"""Tests for harness blocked-run recovery."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.config import HarnessConfig
from harness.gitops import GitOpsManager
from harness.recovery import recover_blocked_run


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip()


def _commit_file(repo: Path, relpath: str, content: str, message: str) -> str:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", relpath)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")


def _make_gitops(project: Path) -> GitOpsManager:
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
    )
    return GitOpsManager(config, base_dir=str(project))


@pytest.mark.unit
def test_recover_blocked_run_cherry_picks_last_strategy_commit_from_mirror(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _init_repo(project)
    _commit_file(project, "README.md", "base\n", "base")
    _git(project, "checkout", "-b", "001-feature")
    _commit_file(project, "spec.md", "spec\n", "spec scaffold")
    scaffold = _git(project, "rev-parse", "HEAD")

    mirror = project / "runs" / "mirror.git"
    mirror.parent.mkdir()
    _git(project, "clone", "--mirror", str(project), str(mirror))

    producer = tmp_path / "producer"
    _git(tmp_path, "clone", str(mirror), str(producer))
    _git(producer, "config", "user.email", "test@example.com")
    _git(producer, "config", "user.name", "Test User")
    _git(producer, "checkout", "001-feature")
    recovered = _commit_file(
        producer,
        "src/generated.txt",
        "generated\n",
        "codegen iter-0: generated work",
    )
    _git(producer, "push", "origin", "001-feature")

    _git(project, "checkout", "001-feature")
    assert _git(project, "rev-parse", "HEAD") == scaffold

    result = recover_blocked_run(
        project_dir=project,
        spec_id="001-feature",
        strategy_id="default",
        state={"termination_reason": "build_incomplete"},
        gitops=_make_gitops(project),
    )

    assert result.source == "mirror"
    assert result.commit == recovered
    assert result.applied is True
    assert _git(project, "rev-parse", "HEAD") != scaffold
    assert (project / "src" / "generated.txt").read_text(encoding="utf-8") == "generated\n"


@pytest.mark.unit
def test_recover_blocked_run_prefers_preserved_worktree(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _init_repo(project)
    _commit_file(project, "README.md", "base\n", "base")
    _git(project, "checkout", "-b", "001-feature")
    _commit_file(project, "spec.md", "spec\n", "spec scaffold")

    mirror = project / "runs" / "mirror.git"
    mirror.parent.mkdir()
    _git(project, "clone", "--mirror", str(project), str(mirror))

    worktree = project / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    _git(tmp_path, "clone", str(project), str(worktree))
    _git(worktree, "config", "user.email", "test@example.com")
    _git(worktree, "config", "user.name", "Test User")
    _git(worktree, "checkout", "001-feature")
    recovered = _commit_file(
        worktree,
        "src/from-worktree.txt",
        "worktree\n",
        "codegen iter-0: preserved worktree work",
    )

    _git(project, "checkout", "001-feature")
    result = recover_blocked_run(
        project_dir=project,
        spec_id="001-feature",
        strategy_id="default",
        state={"termination_reason": "publish_failed"},
        gitops=_make_gitops(project),
        build_id="build-test",
    )

    assert result.source == "worktree"
    assert result.commit == recovered
    assert result.applied is True
    assert (project / "src" / "from-worktree.txt").read_text(encoding="utf-8") == "worktree\n"


@pytest.mark.unit
def test_recover_blocked_run_treats_empty_cherry_pick_as_already_applied(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _init_repo(project)
    _commit_file(project, "README.md", "base\n", "base")
    _git(project, "checkout", "-b", "001-feature")
    _commit_file(project, "spec.md", "spec\n", "spec scaffold")

    mirror = project / "runs" / "mirror.git"
    mirror.parent.mkdir()
    _git(project, "clone", "--mirror", str(project), str(mirror))

    producer = tmp_path / "producer"
    _git(tmp_path, "clone", str(mirror), str(producer))
    _git(producer, "config", "user.email", "test@example.com")
    _git(producer, "config", "user.name", "Test User")
    _git(producer, "checkout", "001-feature")
    recovered = _commit_file(
        producer,
        "src/generated.txt",
        "generated\n",
        "codegen iter-0: generated work",
    )
    _git(producer, "push", "origin", "001-feature")

    _commit_file(
        project,
        "src/generated.txt",
        "generated\n",
        "manual recovery of generated work",
    )
    applied_once = _git(project, "rev-parse", "HEAD")

    result = recover_blocked_run(
        project_dir=project,
        spec_id="001-feature",
        strategy_id="default",
        state={"termination_reason": "build_incomplete"},
        gitops=_make_gitops(project),
    )

    assert result.source == "mirror"
    assert result.commit == recovered
    assert result.applied is False
    assert _git(project, "rev-parse", "HEAD") == applied_once
    assert _git(project, "status", "--porcelain", "--untracked-files=no") == ""


@pytest.mark.unit
def test_recover_blocked_run_reports_existing_target_repo_commit(
    tmp_path: Path,
) -> None:
    wrapper = tmp_path / "wrapper"
    _init_repo(wrapper)
    _commit_file(wrapper, "README.md", "wrapper\n", "wrapper base")

    target = wrapper / "rbf-opta-points"
    _init_repo(target)
    _commit_file(target, "README.md", "target\n", "target base")
    _git(target, "checkout", "-b", "001-opta-points-perf-fix")
    recovered = _commit_file(
        target,
        "src/fix.ts",
        "fix\n",
        "fix(perf): OptaPoints performance stabilization",
    )

    result = recover_blocked_run(
        project_dir=wrapper,
        spec_id="001-opta-points-perf-fix",
        strategy_id="default",
        state={
            "termination_reason": "build_incomplete",
            "target_repo_path": str(target),
            "target_branch": "001-opta-points-perf-fix",
            "target_commit": recovered,
        },
        gitops=_make_gitops(wrapper),
    )

    assert result.source == "target_repo"
    assert result.commit == recovered
    assert result.applied is False
