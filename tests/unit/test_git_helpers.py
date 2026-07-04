from pathlib import Path
import subprocess

from echelon.git_helpers import (
    commit_exists,
    create_backup_ref,
    current_branch,
    is_worktree_dirty,
    ref_contains_commit,
    reset_branch_to_commit,
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


def _init_repo(repo: Path) -> str:
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    return _git(repo, "rev-parse", "HEAD")


def test_git_helpers_detect_branch_dirty_and_commit_containment(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base = _init_repo(repo)

    assert current_branch(repo) == "main"
    assert commit_exists(repo, base)
    assert ref_contains_commit(repo, "main", base)
    assert not is_worktree_dirty(repo)

    (repo / "README.md").write_text("dirty\n", encoding="utf-8")
    assert is_worktree_dirty(repo)


def test_backup_ref_and_reset_branch_to_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base = _init_repo(repo)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "feature")
    head = _git(repo, "rev-parse", "HEAD")

    backup = create_backup_ref(repo, "echelon/backup/test", head)
    reset_branch_to_commit(repo, base)

    assert _git(repo, "rev-parse", "HEAD") == base
    assert _git(repo, "rev-parse", backup) == head
