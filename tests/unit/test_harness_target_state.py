from pathlib import Path

import pytest

from harness.target_state import target_state_updates


@pytest.mark.unit
def test_target_state_updates_include_repo_branch_and_commit(tmp_path: Path) -> None:
    target = tmp_path / "rbf-opta-points"
    target.mkdir()

    updates = target_state_updates(
        polyrepo_root=tmp_path,
        target_repo=target,
        target_branch="001-opta-points-perf-fix",
        target_commit="6132709363bb9f23da5ab9c711638f201885d7d1",
    )

    assert updates == {
        "polyrepo_root": str(tmp_path),
        "target_repo_path": str(target),
        "target_repo_name": "rbf-opta-points",
        "target_branch": "001-opta-points-perf-fix",
        "target_commit": "6132709363bb9f23da5ab9c711638f201885d7d1",
    }
