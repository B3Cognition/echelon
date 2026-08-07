"""Transactional publication of staged review artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from harness.review_artifacts import ReviewArtifactError, ReviewArtifactPublisher


def _task(task_id: str) -> str:
    return f"- [ ] {task_id} complexity=standard phase=review req=UNMAPPED depends=none\n"


def _write_manifest(allocation, *, artifacts: list[str], tasks: list[dict[str, str]]) -> None:
    allocation.status_file.write_text(
        json.dumps(
            {
                "status": "review_fix_queued",
                "groups": len(artifacts),
                "artifacts": artifacts,
                "tasks": tasks,
                "tasks_append": "tasks-append.md",
            }
        ),
        encoding="utf-8",
    )


def test_allocate_uses_numeric_max_and_three_task_ids_per_possible_group(tmp_path: Path) -> None:
    """Changing allocation to count files would reuse a high existing suffix."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    (spec_dir / "tasks.md").write_text(_task("T-40"), encoding="utf-8")
    (spec_dir / "review-fix-7.md").write_text("old", encoding="utf-8")
    (spec_dir / "review-fix-nope.md").write_text("ignored", encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = publisher.allocate(("c1", "c2"))

    assert allocation.artifact_names == ("review-fix-8.md", "review-fix-9.md")
    assert allocation.task_ids == ("T-41", "T-42", "T-43", "T-44", "T-45", "T-46")
    assert allocation.attempt_dir.parent == state_dir / "review-staging"


def test_no_blocking_manifest_requires_no_staged_output(tmp_path: Path) -> None:
    """Accepting any staged output for zero groups could publish provider debris."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    (spec_dir / "tasks.md").write_text(_task("T-1"), encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = publisher.allocate(("c1",))
        allocation.status_file.write_text(
            json.dumps(
                {"status": "no_blocking_comments", "groups": 0, "artifacts": [], "tasks": []}
            ),
            encoding="utf-8",
        )
        (allocation.attempt_dir / "review-fix-1.md").write_text("debris", encoding="utf-8")

        with pytest.raises(ReviewArtifactError, match="empty"):
            publisher.accept_manifest(allocation.status_file)

    assert not (spec_dir / "review-fix-1.md").exists()


@pytest.mark.parametrize("reported", ["../outside.md", "/tmp/outside.md", "other.md"])
def test_manifest_rejects_unallocated_or_escaping_artifact_paths(tmp_path: Path, reported: str) -> None:
    """Accepting a provider-selected path would escape the allocated staging contract."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    (spec_dir / "tasks.md").write_text(_task("T-1"), encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = publisher.allocate(("c1",))
        _write_manifest(
            allocation,
            artifacts=[reported],
            tasks=[{"task_id": "T-2", "review_task_id": "RF1-T1", "artifact": reported}],
        )
        (allocation.attempt_dir / "tasks-append.md").write_text(_task("T-2"), encoding="utf-8")

        with pytest.raises(ReviewArtifactError):
            publisher.accept_manifest(allocation.status_file)

    assert (spec_dir / "tasks.md").read_text(encoding="utf-8") == _task("T-1")


def test_manifest_rejects_duplicate_ids_and_missing_staged_files(tmp_path: Path) -> None:
    """Skipping uniqueness or regular-file checks would permit incomplete canonical batches."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    (spec_dir / "tasks.md").write_text(_task("T-1"), encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = publisher.allocate(("c1",))
        _write_manifest(
            allocation,
            artifacts=["review-fix-1.md"],
            tasks=[
                {"task_id": "T-2", "review_task_id": "RF1-T1", "artifact": "review-fix-1.md"},
                {"task_id": "T-2", "review_task_id": "RF1-T2", "artifact": "review-fix-1.md"},
                {"task_id": "T-4", "review_task_id": "RF1-T3", "artifact": "review-fix-1.md"},
            ],
        )
        (allocation.attempt_dir / "tasks-append.md").write_text(
            _task("T-2") + _task("T-4"), encoding="utf-8"
        )

        with pytest.raises(ReviewArtifactError):
            publisher.accept_manifest(allocation.status_file)

    assert not (spec_dir / "review-fix-1.md").exists()


def test_lock_contention_blocks_live_pid_and_reclaims_stale_lock(tmp_path: Path) -> None:
    """Ignoring a live lock would let two review cycles choose the same names."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    (spec_dir / "tasks.md").write_text(_task("T-1"), encoding="utf-8")
    lock = spec_dir / ".echelon-review.lock"
    lock.write_text(f"pid={os.getpid()}\ncreated_at=now\nstrategy=default\n", encoding="utf-8")

    with pytest.raises(ReviewArtifactError, match="lock"):
        with ReviewArtifactPublisher(spec_dir, state_dir, "default"):
            pass

    lock.write_text("pid=999999999\ncreated_at=then\nstrategy=default\n", encoding="utf-8")
    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        assert publisher.allocate(()).artifact_names == ()


def test_recovery_completes_partial_publication_without_duplicate_tasks(tmp_path: Path) -> None:
    """Replaying a journal after one artifact write must finish once, not append twice."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    (spec_dir / "tasks.md").write_text(_task("T-1"), encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = publisher.allocate(("c1",))
        (allocation.attempt_dir / "review-fix-1.md").write_text("# Fix\n", encoding="utf-8")
        (allocation.attempt_dir / "tasks-append.md").write_text(
            _task("T-2") + _task("T-3") + _task("T-4"), encoding="utf-8"
        )
        _write_manifest(
            allocation,
            artifacts=["review-fix-1.md"],
            tasks=[
                {"task_id": f"T-{number}", "review_task_id": f"RF1-T{number - 1}", "artifact": "review-fix-1.md"}
                for number in (2, 3, 4)
            ],
        )
        publisher._after_publication_boundary = lambda boundary: (_ for _ in ()).throw(RuntimeError("crash")) if boundary == "artifact:review-fix-1.md" else None
        with pytest.raises(RuntimeError, match="crash"):
            publisher.accept_manifest(allocation.status_file)

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        result = publisher.recover_publication(set())

    assert result is not None
    assert result.task_ids == ("T-2", "T-3", "T-4")
    assert (spec_dir / "tasks.md").read_text(encoding="utf-8").count("T-2") == 1


def test_publication_rejects_canonical_tasks_changed_after_allocation(tmp_path: Path) -> None:
    """Re-snapshotting tasks at publication would silently append to user changes."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    tasks_path = spec_dir / "tasks.md"
    tasks_path.write_text(_task("T-1"), encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = publisher.allocate(("c1",))
        tasks_path.write_text(_task("T-1") + _task("T-99"), encoding="utf-8")
        (allocation.attempt_dir / "review-fix-1.md").write_text("# Fix\n", encoding="utf-8")
        (allocation.attempt_dir / "tasks-append.md").write_text(
            _task("T-2") + _task("T-3") + _task("T-4"), encoding="utf-8"
        )
        _write_manifest(
            allocation,
            artifacts=["review-fix-1.md"],
            tasks=[
                {"task_id": f"T-{number}", "review_task_id": f"RF1-T{number - 1}", "artifact": "review-fix-1.md"}
                for number in (2, 3, 4)
            ],
        )

        with pytest.raises(ReviewArtifactError, match="changed"):
            publisher.accept_manifest(allocation.status_file)

    assert not (spec_dir / "review-fix-1.md").exists()


def test_manifest_rejects_task_numbers_assigned_to_the_wrong_artifact(tmp_path: Path) -> None:
    """Allowing cross-group task numbers would break deterministic group ownership."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    (spec_dir / "tasks.md").write_text(_task("T-1"), encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = publisher.allocate(("c1", "c2"))
        for artifact in allocation.artifact_names:
            (allocation.attempt_dir / artifact).write_text("# Fix\n", encoding="utf-8")
        (allocation.attempt_dir / "tasks-append.md").write_text(
            "".join(_task(f"T-{number}") for number in range(2, 8)), encoding="utf-8"
        )
        _write_manifest(
            allocation,
            artifacts=list(allocation.artifact_names),
            tasks=[
                {"task_id": "T-2", "review_task_id": "RF1-T1", "artifact": "review-fix-1.md"},
                {"task_id": "T-3", "review_task_id": "RF2-T1", "artifact": "review-fix-2.md"},
                {"task_id": "T-4", "review_task_id": "RF2-T2", "artifact": "review-fix-2.md"},
                {"task_id": "T-5", "review_task_id": "RF2-T3", "artifact": "review-fix-2.md"},
                {"task_id": "T-6", "review_task_id": "RF1-T2", "artifact": "review-fix-1.md"},
                {"task_id": "T-7", "review_task_id": "RF1-T3", "artifact": "review-fix-1.md"},
            ],
        )

        with pytest.raises(ReviewArtifactError, match="per artifact"):
            publisher.accept_manifest(allocation.status_file)
