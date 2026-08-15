"""Small Git primitives shared by Echelon recovery flows."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import overload


class GitHelperError(RuntimeError):
    pass


def run_git(
    repo: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise GitHelperError("could not execute git: git is not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitHelperError(f"git {' '.join(args)} timed out in {repo}") from exc
    if check and result.returncode != 0:
        raise GitHelperError(
            f"git {' '.join(args)} failed in {repo}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


@overload
def run_git_hardened(
    repo: Path,
    *args: str,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str]: ...


@overload
def run_git_hardened(
    repo: Path,
    *args: str,
    check: bool = True,
    text: bool = False,
) -> subprocess.CompletedProcess[bytes]: ...


def run_git_hardened(
    repo: Path,
    *args: str,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    """Run an authority-sensitive Git read without ambient rewrites/config."""

    process_env = os.environ.copy()
    for name in (
        "GIT_CONFIG_PARAMETERS",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
    ):
        process_env.pop(name, None)
    process_env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_COUNT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            env=process_env,
            check=False,
            capture_output=True,
            text=text,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise GitHelperError("could not execute git: git is not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitHelperError(f"git {' '.join(args)} timed out in {repo}") from exc
    if check and result.returncode != 0:
        stdout = result.stdout
        stderr = result.stderr
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise GitHelperError(
            f"git {' '.join(args)} failed in {repo}\n"
            f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        )
    return result


def current_branch(repo: Path) -> str:
    return run_git(repo, "branch", "--show-current").stdout.strip()


def is_worktree_dirty(repo: Path, *, include_untracked: bool = True) -> bool:
    args = ["status", "--porcelain"]
    if not include_untracked:
        args.append("--untracked-files=no")
    return bool(run_git(repo, *args, check=False).stdout.strip())


def worktree_dirty_paths(repo: Path) -> set[str]:
    """Return every changed path, including staged and untracked files."""
    paths: set[str] = set()
    for args in (
        ("diff", "--name-only", "-z"),
        ("diff", "--cached", "--name-only", "-z"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        output = run_git(repo, *args).stdout
        paths.update(path for path in output.split("\0") if path)
    return paths


def commit_exists(repo: Path, commit: str) -> bool:
    if not commit.strip():
        return False
    result = run_git(repo, "cat-file", "-e", f"{commit}^{{commit}}", check=False)
    return result.returncode == 0


def ref_contains_commit(repo: Path, ref: str, commit: str) -> bool:
    if not ref.strip() or not commit_exists(repo, commit):
        return False
    result = run_git(repo, "merge-base", "--is-ancestor", commit, ref, check=False)
    return result.returncode == 0


def create_backup_ref(repo: Path, ref_name: str, target: str = "HEAD") -> str:
    cleaned = ref_name.strip().removeprefix("refs/heads/")
    if not cleaned.startswith("echelon/backup/"):
        raise ValueError("backup refs must live under echelon/backup/")
    run_git(repo, "branch", "--force", cleaned, target)
    return cleaned


def reset_branch_to_commit(
    repo: Path,
    commit: str,
    *,
    preserve_worktree: bool = False,
) -> None:
    if not commit_exists(repo, commit):
        raise GitHelperError(f"checkpoint commit does not exist: {commit}")
    mode = "--keep" if preserve_worktree else "--hard"
    run_git(repo, "reset", mode, commit)
