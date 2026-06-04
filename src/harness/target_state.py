from __future__ import annotations

from pathlib import Path


def target_state_updates(
    *,
    polyrepo_root: Path,
    target_repo: Path,
    target_branch: str | None,
    target_commit: str | None,
) -> dict[str, str | None]:
    return {
        "polyrepo_root": str(polyrepo_root),
        "target_repo_path": str(target_repo),
        "target_repo_name": target_repo.name,
        "target_branch": target_branch,
        "target_commit": target_commit,
    }
