"""Real-Git safety checks for published Spec runnability promotion."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_runnability_amendment import _git, _repo
from echelon.runnability_amendment import prepare_runnability_owner
from echelon.runnability_amendment_transaction import (
    promote_runnability_owner,
    recover_runnability_promotion,
)


def _prepared(tmp_path: Path) -> tuple[Path, dict[str, object], bytes, str, str]:
    repo = _repo(tmp_path)
    tasks = repo / "specs/004-demo/tasks.md"
    tasks.write_text(tasks.read_text().replace("- [ ] T-001", "- [x] T-001")
                     .replace("**Status:** PENDING", "**Status:** DONE"))
    old_progress = tasks.read_bytes()
    old_ref = _git(repo, "rev-parse", "HEAD")
    old_index = _git(repo, "rev-parse", ":specs/004-demo/tasks.md")
    prepared = prepare_runnability_owner(repo, "004-demo")
    return repo, prepared, old_progress, old_ref, old_index


def test_promotion_preserves_dirty_progress_and_unrelated_staged_file(tmp_path: Path) -> None:
    repo, prepared, old_progress, old_ref, old_index = _prepared(tmp_path)
    unrelated = repo / "unrelated.txt"
    unrelated.write_text("keep staged\n")
    _git(repo, "add", "unrelated.txt")
    staged_blob = _git(repo, "rev-parse", ":unrelated.txt")

    result = promote_runnability_owner(repo, str(prepared["amendment_id"]))

    assert result["status"] == "promoted"
    assert _git(repo, "rev-parse", "HEAD") == prepared["proposed_commit"]
    assert _git(repo, "rev-parse", ":specs/004-demo/tasks.md") != old_index
    assert _git(repo, "rev-parse", ":unrelated.txt") == staged_blob
    assert unrelated.read_bytes() == b"keep staged\n"
    working = (repo / "specs/004-demo/tasks.md").read_bytes()
    assert b"- [x] T-001" in working and b"- [ ] T-002" in working
    assert old_progress != working and old_ref != prepared["proposed_commit"]


@pytest.mark.parametrize("cut,expected", [
    ("before_file", "rolled_back"),
    ("after_file", "rolled_back"),
    ("after_index", "rolled_back"),
    ("after_ref", "promoted"),
])
def test_recovery_follows_ref_after_each_fault_cut(
    tmp_path: Path, cut: str, expected: str,
) -> None:
    repo, prepared, old_progress, old_ref, old_index = _prepared(tmp_path)
    unrelated = repo / "unrelated.txt"
    unrelated.write_text("keep staged\n")
    _git(repo, "add", "unrelated.txt")
    staged_blob = _git(repo, "rev-parse", ":unrelated.txt")

    def fault(phase: str) -> None:
        if phase == cut:
            raise RuntimeError(f"injected {cut}")

    with pytest.raises(RuntimeError, match=f"injected {cut}"):
        promote_runnability_owner(repo, str(prepared["amendment_id"]), fault_hook=fault)

    assert recover_runnability_promotion(repo, str(prepared["amendment_id"])) == expected
    assert recover_runnability_promotion(repo, str(prepared["amendment_id"])) == expected
    assert _git(repo, "rev-parse", ":unrelated.txt") == staged_blob
    assert unrelated.read_bytes() == b"keep staged\n"
    if expected == "rolled_back":
        assert _git(repo, "rev-parse", "HEAD") == old_ref
        assert _git(repo, "rev-parse", ":specs/004-demo/tasks.md") == old_index
        assert (repo / "specs/004-demo/tasks.md").read_bytes() == old_progress
    else:
        assert _git(repo, "rev-parse", "HEAD") == prepared["proposed_commit"]
        assert b"- [ ] T-002" in (repo / "specs/004-demo/tasks.md").read_bytes()


def test_promotion_rejects_staged_tasks_without_touching_it(tmp_path: Path) -> None:
    repo, prepared, old_progress, old_ref, _ = _prepared(tmp_path)
    _git(repo, "add", "specs/004-demo/tasks.md")
    staged_blob = _git(repo, "rev-parse", ":specs/004-demo/tasks.md")

    with pytest.raises(ValueError, match="index"):
        promote_runnability_owner(repo, str(prepared["amendment_id"]))

    assert _git(repo, "rev-parse", "HEAD") == old_ref
    assert _git(repo, "rev-parse", ":specs/004-demo/tasks.md") == staged_blob
    assert (repo / "specs/004-demo/tasks.md").read_bytes() == old_progress


def test_promotion_rejects_ref_race(tmp_path: Path) -> None:
    repo, prepared, old_progress, _, old_index = _prepared(tmp_path)
    _git(repo, "commit", "--allow-empty", "-m", "other publication")
    raced_ref = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(ValueError, match="branch"):
        promote_runnability_owner(repo, str(prepared["amendment_id"]))

    assert _git(repo, "rev-parse", "HEAD") == raced_ref
    assert _git(repo, "rev-parse", ":specs/004-demo/tasks.md") == old_index
    assert (repo / "specs/004-demo/tasks.md").read_bytes() == old_progress


def test_recovery_does_not_overwrite_user_edit_after_install(tmp_path: Path) -> None:
    repo, prepared, _, old_ref, old_index = _prepared(tmp_path)
    tasks = repo / "specs/004-demo/tasks.md"

    def fault(phase: str) -> None:
        if phase == "after_file":
            tasks.write_bytes(tasks.read_bytes() + b"\nuser edit\n")
            raise RuntimeError("injected edit")

    with pytest.raises(RuntimeError, match="injected edit"):
        promote_runnability_owner(repo, str(prepared["amendment_id"]), fault_hook=fault)
    user_bytes = tasks.read_bytes()

    assert recover_runnability_promotion(repo, str(prepared["amendment_id"])) == "needs_attention"
    assert tasks.read_bytes() == user_bytes
    assert _git(repo, "rev-parse", "HEAD") == old_ref
    assert _git(repo, "rev-parse", ":specs/004-demo/tasks.md") == old_index


def test_promotion_does_not_overwrite_edit_at_file_boundary(tmp_path: Path) -> None:
    repo, prepared, _, old_ref, old_index = _prepared(tmp_path)
    tasks = repo / "specs/004-demo/tasks.md"

    def edit_before_install(phase: str) -> None:
        if phase == "before_file":
            tasks.write_bytes(tasks.read_bytes() + b"\nlate user edit\n")

    with pytest.raises(ValueError, match="working tasks.md changed"):
        promote_runnability_owner(
            repo, str(prepared["amendment_id"]), fault_hook=edit_before_install,
        )

    assert tasks.read_bytes().endswith(b"late user edit\n")
    assert _git(repo, "rev-parse", "HEAD") == old_ref
    assert _git(repo, "rev-parse", ":specs/004-demo/tasks.md") == old_index


def test_promotion_does_not_overwrite_index_race_after_file(tmp_path: Path) -> None:
    repo, prepared, _, old_ref, _ = _prepared(tmp_path)
    tasks = repo / "specs/004-demo/tasks.md"
    staged_blob: str | None = None

    def stage_other_tasks(phase: str) -> None:
        nonlocal staged_blob
        if phase == "after_file":
            tasks.write_bytes(tasks.read_bytes() + b"\nlate user edit\n")
            _git(repo, "add", "specs/004-demo/tasks.md")
            staged_blob = _git(repo, "rev-parse", ":specs/004-demo/tasks.md")

    with pytest.raises(ValueError, match="index entry changed"):
        promote_runnability_owner(
            repo, str(prepared["amendment_id"]), fault_hook=stage_other_tasks,
        )

    assert staged_blob is not None
    assert _git(repo, "rev-parse", ":specs/004-demo/tasks.md") == staged_blob
    assert tasks.read_bytes().endswith(b"late user edit\n")
    assert _git(repo, "rev-parse", "HEAD") == old_ref
