"""Tests for GitOpsManager.get_latest_worktree."""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

from harness.config import HarnessConfig
from harness.errors import GitOpsError
from harness.gitops import GitOpsManager, _clean_branch_listing


def _make_gitops(tmp_path):
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
    )
    return GitOpsManager(config=config, base_dir=str(tmp_path))


def test_get_latest_worktree_returns_most_recent(tmp_path):
    """get_latest_worktree returns highest-mtime worktree dir for strategy."""
    gitops = _make_gitops(tmp_path)

    wt_base = tmp_path / "runs" / "build-test" / "worktrees" / "default"
    iter1 = wt_base / "iter-1"
    iter2 = wt_base / "iter-2"
    iter1.mkdir(parents=True)
    time.sleep(0.02)
    iter2.mkdir(parents=True)

    result = gitops.get_latest_worktree("001", "default")
    assert result == str(iter2)


def test_get_latest_worktree_returns_none_when_no_dir(tmp_path):
    """get_latest_worktree returns None when strategy directory does not exist."""
    gitops = _make_gitops(tmp_path)
    result = gitops.get_latest_worktree("001", "default")
    assert result is None


def test_get_latest_worktree_returns_none_when_empty(tmp_path):
    """get_latest_worktree returns None when strategy dir exists but has no children."""
    gitops = _make_gitops(tmp_path)
    wt_base = tmp_path / "runs" / "build-test" / "worktrees" / "default"
    wt_base.mkdir(parents=True)

    result = gitops.get_latest_worktree("001", "default")
    assert result is None


def test_sync_runtime_extension_copies_untracked_project_extension(tmp_path):
    """Harness worktrees get the local Echelon extension even when it is untracked."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "agents" / "control" / "commander.md").write_text("commander\n", encoding="utf-8")
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    assert (
        worktree
        / ".specify"
        / "extensions"
        / "echelon"
        / "agents"
        / "control"
        / "commander.md"
    ).read_text(encoding="utf-8") == "commander\n"
    assert ".specify/extensions/echelon/" in exclude.read_text(encoding="utf-8")


def test_sync_runtime_extension_copies_codegraph_node_runtime_deps(tmp_path):
    """Harness worktrees keep CodeGraph Node deps required by the vendored bridge."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "scripts" / "node" / "re" / "node_modules" / "picomatch").mkdir(parents=True)
    (source / "agents" / "control" / "commander.md").write_text("commander\n", encoding="utf-8")
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (
        source
        / "scripts"
        / "node"
        / "re"
        / "node_modules"
        / "picomatch"
        / "package.json"
    ).write_text('{"name":"picomatch"}\n', encoding="utf-8")

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    copied = (
        worktree
        / ".specify"
        / "extensions"
        / "echelon"
        / "scripts"
        / "node"
        / "re"
        / "node_modules"
        / "picomatch"
        / "package.json"
    )
    assert copied.read_text(encoding="utf-8") == '{"name":"picomatch"}\n'


def test_sync_runtime_extension_materializes_claude_command_skills(tmp_path):
    """Harness worktrees get ignored Claude skill wrappers from runtime commands."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "commands").mkdir()
    (source / "agents" / "control" / "commander.md").write_text("commander\n", encoding="utf-8")
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")
    (source / "commands" / "echelon.verify-spec.md").write_text(
        "---\n"
        "name: speckit.echelon.verify-spec\n"
        "description: Verify spec\n"
        "---\n\n"
        "Read `agents/control/commander.md` and `workflow/definition.yaml`.\n\n"
        "$ARGUMENTS\n",
        encoding="utf-8",
    )

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    skill = worktree / ".claude" / "skills" / "speckit-echelon-verify-spec" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert "name: speckit-echelon-verify-spec" in text
    assert "Read `.specify/extensions/echelon/agents/control/commander.md`" in text
    assert "`.specify/extensions/echelon/workflow/definition.yaml`" in text
    assert "$ARGUMENTS" in text
    assert ".claude/skills/speckit-echelon-verify-spec/" in exclude.read_text(encoding="utf-8")


def test_sync_runtime_extension_materializes_claude_agents(tmp_path):
    """Harness worktrees get ignored Claude agent registry files from runtime agents."""
    source = tmp_path / ".specify" / "extensions" / "echelon"
    (source / "agents" / "control").mkdir(parents=True)
    (source / "agents" / "build").mkdir(parents=True)
    (source / "workflow").mkdir()
    (source / "agents" / "control" / "commander.md").write_text("commander\n", encoding="utf-8")
    (source / "agents" / "build" / "spec-guard.md").write_text("guard\n", encoding="utf-8")
    (source / "workflow" / "definition.yaml").write_text("workflow\n", encoding="utf-8")

    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    exclude = tmp_path / "git-exclude"

    gitops = _make_gitops(tmp_path)
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=str(exclude) + "\n")
        gitops.sync_runtime_extension(worktree)

    commander = worktree / ".claude" / "agents" / "speckit-echelon-commander.md"
    spec_guard = worktree / ".claude" / "agents" / "speckit-echelon-spec-guard.md"
    assert commander.read_text(encoding="utf-8") == "commander\n"
    assert spec_guard.read_text(encoding="utf-8") == "guard\n"
    assert ".claude/agents/" in exclude.read_text(encoding="utf-8")


def test_sync_runtime_extension_fails_before_llm_when_extension_missing(tmp_path):
    """Missing runtime prompts fail deterministically instead of inviting global search."""
    worktree = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)

    gitops = _make_gitops(tmp_path)

    try:
        gitops.sync_runtime_extension(worktree)
    except Exception as exc:
        assert ".specify/extensions/echelon" in str(exc)
        assert "Run `echelon init`" in str(exc)
    else:
        raise AssertionError("expected missing runtime extension to fail")


def test_create_worktree_removes_stale_runs_checkout_before_retry(tmp_path):
    """Feature-branch mode must not reuse old harness worktrees from prior builds."""
    mirror = tmp_path / "runs" / "mirror.git"
    mirror.mkdir(parents=True)
    stale = tmp_path / "runs" / "build-old" / "worktrees" / "default" / "iter-0"
    stale.mkdir(parents=True)

    gitops = _make_gitops(tmp_path)

    add_error = GitOpsError(
        f"fatal: '001-feature' is already used by worktree at '{stale}'",
        command="git worktree add",
    )

    calls: list[tuple[list[str], str | None]] = []

    def fake_run_git(args, cwd=None, **_kwargs):
        calls.append((args, cwd))
        if args[:2] == ["worktree", "add"] and len(
            [call for call in calls if call[0][:2] == ["worktree", "add"]]
        ) == 1:
            raise add_error
        return SimpleNamespace(stdout="")

    with patch("harness.gitops._run_git", side_effect=fake_run_git), patch.object(
        gitops, "sync_runtime_extension"
    ) as sync_runtime:
        result = gitops.create_worktree(
            "001-feature",
            "default",
            0,
            base_branch="001-feature",
            build_id="build-new",
        )

    expected = tmp_path / "runs" / "build-new" / "worktrees" / "default" / "iter-0"
    assert result == str(expected)
    assert (
        ["worktree", "remove", "--force", str(stale)],
        str(mirror),
    ) in calls
    assert (
        ["worktree", "add", str(expected), "001-feature"],
        str(mirror),
    ) in calls
    sync_runtime.assert_called_once_with(expected)


def test_clean_branch_listing_strips_git_worktree_marker():
    """`git branch --list` prefixes branches checked out in worktrees with `+`."""
    assert _clean_branch_listing("+ 001-feature") == "001-feature"
    assert _clean_branch_listing("* main") == "main"
    assert _clean_branch_listing("  002-other") == "002-other"
