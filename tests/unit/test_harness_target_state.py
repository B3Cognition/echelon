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

    assert updates["polyrepo_root"] == str(tmp_path)
    assert updates["target_repo_path"] == str(target)
    assert updates["target_repo_name"] == "rbf-opta-points"
    assert updates["target_branch"] == "001-opta-points-perf-fix"
    assert updates["target_commit"] == "6132709363bb9f23da5ab9c711638f201885d7d1"
    assert updates["workspace_root"] == str(tmp_path)
    assert updates["source_root"] == str(target)
    assert updates["source_id"] == "rbf-opta-points"


@pytest.mark.unit
def test_target_state_updates_include_workspace_and_source_metadata(tmp_path: Path) -> None:
    target = tmp_path / "og-platform"
    target.mkdir()

    updates = target_state_updates(
        polyrepo_root=tmp_path,
        target_repo=target,
        target_branch="001-demo",
        target_commit="abc123",
        workspace_root=tmp_path,
        workspace_git_role="orchestration",
        source_root=target,
        source_id="og-platform",
        source_git_role="source",
    )

    assert updates["workspace_root"] == str(tmp_path)
    assert updates["workspace_git_role"] == "orchestration"
    assert updates["source_root"] == str(target)
    assert updates["source_id"] == "og-platform"
    assert updates["source_git_role"] == "source"
