from __future__ import annotations

from pathlib import Path


def target_state_updates(
    *,
    polyrepo_root: Path,
    target_repo: Path,
    target_branch: str | None,
    target_commit: str | None,
    workspace_root: Path | None = None,
    workspace_git_role: str | None = None,
    source_root: Path | None = None,
    source_id: str | None = None,
    source_git_role: str | None = None,
) -> dict[str, str | None]:
    return {
        "polyrepo_root": str(polyrepo_root),
        "target_repo_path": str(target_repo),
        "target_repo_name": target_repo.name,
        "target_branch": target_branch,
        "target_commit": target_commit,
        "workspace_root": str(workspace_root or polyrepo_root),
        "workspace_git_role": workspace_git_role,
        "source_root": str(source_root or target_repo),
        "source_id": source_id or target_repo.name,
        "source_git_role": source_git_role,
    }
