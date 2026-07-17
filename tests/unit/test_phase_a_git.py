from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from echelon.phase_a_git import (
    PhaseAGitError,
    create_phase_a_spec_branch,
    plan_phase_a_spec,
    resolve_phase_a_default_branch,
    slugify_spec_description,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(tmp_path: Path, *, initial_branch: str = "main") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", initial_branch)
    _git(repo, "config", "user.name", "Echelon Tests")
    _git(repo, "config", "user.email", "echelon@example.test")
    (repo / "README.md").write_text("# Test repository\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


def _git_position(repo: Path) -> tuple[str, str]:
    return _git(repo, "branch", "--show-current"), _git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("I want to add user authentication", "add-user-authentication"),
        ("Create an OAuth2 API dashboard now", "create-oauth2-api-dashboard"),
        ("Caching", "spec-caching"),
    ],
)
def test_slugify_spec_description(description: str, expected: str) -> None:
    assert slugify_spec_description(description) == expected


def test_slugify_spec_description_rejects_only_filler() -> None:
    with pytest.raises(PhaseAGitError, match="meaningful"):
        slugify_spec_description("I need to, please")


def test_resolve_default_branch_prefers_explicit_configuration(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "master")

    branch, commit = resolve_phase_a_default_branch(repo, "master")

    assert branch == "master"
    assert commit == _git(repo, "rev-parse", "refs/heads/master^{commit}")


def test_resolve_default_branch_prefers_main_without_configuration(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "master")

    branch, commit = resolve_phase_a_default_branch(repo)

    assert branch == "main"
    assert commit == _git(repo, "rev-parse", "refs/heads/main^{commit}")


def test_resolve_default_branch_falls_back_to_master(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, initial_branch="master")

    branch, commit = resolve_phase_a_default_branch(repo)

    assert branch == "master"
    assert commit == _git(repo, "rev-parse", "refs/heads/master^{commit}")


def test_resolve_default_branch_falls_back_to_master_when_default_main_is_missing(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path, initial_branch="master")

    branch, commit = resolve_phase_a_default_branch(repo, "main")

    assert branch == "master"
    assert commit == _git(repo, "rev-parse", "refs/heads/master^{commit}")


def test_resolve_default_branch_falls_back_to_origin_head(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, initial_branch="trunk")
    _git(repo, "update-ref", "refs/remotes/origin/trunk", "HEAD")
    _git(
        repo,
        "symbolic-ref",
        "refs/remotes/origin/HEAD",
        "refs/remotes/origin/trunk",
    )

    branch, commit = resolve_phase_a_default_branch(repo)

    assert branch == "trunk"
    assert commit == _git(repo, "rev-parse", "refs/heads/trunk^{commit}")


def test_resolve_default_branch_rejects_missing_explicit_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    with pytest.raises(PhaseAGitError, match="configured default branch.*missing"):
        resolve_phase_a_default_branch(repo, "trunk")


def test_plan_phase_a_spec_allocates_across_all_identity_sources(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "specs" / "003-old").mkdir(parents=True)
    (repo / "runs" / "old" / "specs" / "007-draft").mkdir(parents=True)
    run_dir = repo / "runs" / "current"
    run_dir.mkdir(parents=True)
    _git(repo, "branch", "005-local")
    _git(repo, "update-ref", "refs/remotes/origin/009-remote", "HEAD")
    status_before = _git(repo, "status", "--short")

    bootstrap = plan_phase_a_spec(repo, run_dir, "Add audit logging")

    assert bootstrap.spec_id == "010-add-audit-logging"
    assert bootstrap.spec_number == "010"
    assert bootstrap.slug == "add-audit-logging"
    assert bootstrap.feature_branch == bootstrap.spec_id
    assert bootstrap.spec_dir == "runs/current/specs/010-add-audit-logging"
    assert bootstrap.published_spec_dir == "specs/010-add-audit-logging"
    assert bootstrap.default_branch == "main"
    assert bootstrap.default_commit == _git(repo, "rev-parse", "refs/heads/main^{commit}")
    assert bootstrap.state_updates() == {
        "spec_id": bootstrap.spec_id,
        "spec_number": bootstrap.spec_number,
        "spec_dir": bootstrap.spec_dir,
        "published_spec_dir": bootstrap.published_spec_dir,
        "feature_branch": bootstrap.feature_branch,
        "phase_a_default_branch": bootstrap.default_branch,
        "phase_a_base_commit": bootstrap.default_commit,
        "specify_feature_directory": bootstrap.spec_dir,
    }
    assert _git(repo, "status", "--short") == status_before
    assert _git(repo, "branch", "--show-current") == "main"


def test_plan_phase_a_spec_starts_at_001(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    bootstrap = plan_phase_a_spec(repo, repo / "runs" / "new", "Search")

    assert bootstrap.spec_id == "001-spec-search"
    assert bootstrap.spec_dir == "runs/new/specs/001-spec-search"


def test_plan_phase_a_spec_requires_run_directory_inside_project(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    with pytest.raises(PhaseAGitError, match="run directory.*inside"):
        plan_phase_a_spec(repo, tmp_path / "outside", "Search")


def test_create_phase_a_spec_branch_creates_sibling_at_recorded_default_commit(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    bootstrap = plan_phase_a_spec(repo, repo / "runs" / "new", "Search")

    result = create_phase_a_spec_branch(repo, bootstrap)

    assert result is bootstrap
    assert _git(repo, "branch", "--show-current") == bootstrap.feature_branch
    assert _git(repo, "rev-parse", "HEAD") == bootstrap.default_commit
    assert (
        subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                bootstrap.default_commit,
                bootstrap.feature_branch,
            ],
            cwd=repo,
            check=False,
        ).returncode
        == 0
    )


@pytest.mark.parametrize("dirty_kind", ["tracked", "staged", "untracked"])
def test_create_phase_a_spec_branch_refuses_dirty_worktree_without_moving_head(
    tmp_path: Path,
    dirty_kind: str,
) -> None:
    repo = _init_repo(tmp_path)
    bootstrap = plan_phase_a_spec(repo, repo / "runs" / "new", "Search")
    if dirty_kind == "tracked":
        (repo / "README.md").write_text("changed\n")
    elif dirty_kind == "staged":
        (repo / "README.md").write_text("staged\n")
        _git(repo, "add", "README.md")
    else:
        (repo / "untracked.txt").write_text("untracked\n")
    position_before = _git_position(repo)

    with pytest.raises(PhaseAGitError, match="clean worktree"):
        create_phase_a_spec_branch(repo, bootstrap)

    assert _git_position(repo) == position_before
    assert (
        subprocess.run(
            [
                "git",
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{bootstrap.feature_branch}",
            ],
            cwd=repo,
            check=False,
        ).returncode
        != 0
    )


def test_create_phase_a_spec_branch_refuses_non_default_current_branch(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    bootstrap = plan_phase_a_spec(repo, repo / "runs" / "new", "Search")
    _git(repo, "switch", "-c", "other-work")
    position_before = _git_position(repo)

    with pytest.raises(PhaseAGitError, match="current branch.*default branch"):
        create_phase_a_spec_branch(repo, bootstrap)

    assert _git_position(repo) == position_before


def test_create_phase_a_spec_branch_refuses_moved_default_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    bootstrap = plan_phase_a_spec(repo, repo / "runs" / "new", "Search")
    (repo / "next.txt").write_text("next\n")
    _git(repo, "add", "next.txt")
    _git(repo, "commit", "-m", "move default")
    position_before = _git_position(repo)

    with pytest.raises(PhaseAGitError, match="default branch.*moved"):
        create_phase_a_spec_branch(repo, bootstrap)

    assert _git_position(repo) == position_before


def test_create_phase_a_spec_branch_refuses_existing_target_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    bootstrap = plan_phase_a_spec(repo, repo / "runs" / "new", "Search")
    _git(repo, "branch", bootstrap.feature_branch)
    position_before = _git_position(repo)

    with pytest.raises(PhaseAGitError, match="target branch.*already exists"):
        create_phase_a_spec_branch(repo, bootstrap)

    assert _git_position(repo) == position_before
