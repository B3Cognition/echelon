"""Transactional publication of staged review artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from kernel.task_contract import parse_task_rows
from harness.review_artifacts import ReviewArtifactError, ReviewArtifactPublisher


def _task(task_id: str) -> str:
    suffix = task_id.removeprefix("T-")
    label = task_id if len(suffix) >= 3 else f"T-{int(suffix):03d}"
    return f"- [ ] {label} complexity=standard phase=review-fix req=UNMAPPED depends=none\n"


def _append(*entries: tuple[str, str]) -> str:
    return "\n".join(
        _task(task_id) + f"\n  **Title:** {review_id} - Review follow-up\n"
        for task_id, review_id in entries
    )


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


def _stage_one_group(publisher: ReviewArtifactPublisher):
    allocation = publisher.allocate(("c1",))
    first, second, third = allocation.task_ids[:3]
    (allocation.attempt_dir / "review-fix-1.md").write_text("# Fix\n", encoding="utf-8")
    (allocation.attempt_dir / "tasks-append.md").write_text(
        _append((first, "RF1-T1"), (second, "RF1-T2"), (third, "RF1-T3")),
        encoding="utf-8",
    )
    _write_manifest(
        allocation,
        artifacts=["review-fix-1.md"],
        tasks=[
            {
                "task_id": task_id,
                "review_task_id": f"RF1-T{index}",
                "artifact": "review-fix-1.md",
            }
            for index, task_id in enumerate((first, second, third), start=1)
        ],
    )
    return allocation


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
    assert allocation.task_ids == (
        "T-000041",
        "T-000042",
        "T-000043",
        "T-000044",
        "T-000045",
        "T-000046",
    )
    assert allocation.attempt_dir.parent == state_dir / "review-staging"


def test_fresh_allocation_uses_six_digit_minimum(tmp_path: Path) -> None:
    """Fresh task producers must not emit the legacy three-digit width."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = publisher.allocate(("c1",))

    assert allocation.task_ids == ("T-000001", "T-000002", "T-000003")


def test_wide_allocation_publishes_and_round_trips_without_a_numeric_cap(
    tmp_path: Path,
) -> None:
    """A task after 999999 must allocate, publish, and remain fully parseable."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    tasks_path = spec_dir / "tasks.md"
    tasks_path.write_text(
        "- [ ] T-999999 complexity=standard phase=review-fix "
        "req=FR-999999 depends=none\n",
        encoding="utf-8",
    )

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = publisher.allocate(("c1",))
        assert allocation.task_ids == ("T-1000000", "T-1000001", "T-1000002")
        (allocation.attempt_dir / "review-fix-1.md").write_text(
            "# Review Fix 1\n", encoding="utf-8"
        )
        (allocation.attempt_dir / "tasks-append.md").write_text(
            _append(
                ("T-1000000", "RF1-T1"),
                ("T-1000001", "RF1-T2"),
                ("T-1000002", "RF1-T3"),
            ),
            encoding="utf-8",
        )
        _write_manifest(
            allocation,
            artifacts=["review-fix-1.md"],
            tasks=[
                {
                    "task_id": "T-1000000",
                    "review_task_id": "RF1-T1",
                    "artifact": "review-fix-1.md",
                },
                {
                    "task_id": "T-1000001",
                    "review_task_id": "RF1-T2",
                    "artifact": "review-fix-1.md",
                },
                {
                    "task_id": "T-1000002",
                    "review_task_id": "RF1-T3",
                    "artifact": "review-fix-1.md",
                },
            ],
        )
        result = publisher.accept_manifest(allocation.status_file)

    assert result.task_ids == ("T-1000000", "T-1000001", "T-1000002")
    assert [row.task_id for row in parse_task_rows(tasks_path.read_text())] == [
        "T-999999",
        "T-1000000",
        "T-1000001",
        "T-1000002",
    ]


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
        allocation = _stage_one_group(publisher)
        publisher._after_publication_boundary = lambda boundary: (_ for _ in ()).throw(RuntimeError("crash")) if boundary == "artifact-write:review-fix-1.md" else None
        with pytest.raises(RuntimeError, match="crash"):
            publisher.accept_manifest(allocation.status_file)

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        result = publisher.recover_publication(set())

    assert result is not None
    assert result.task_ids == ("T-000002", "T-000003", "T-000004")
    assert (spec_dir / "tasks.md").read_text(encoding="utf-8").count("T-000002") == 1


def test_publication_rejects_canonical_tasks_changed_after_allocation(tmp_path: Path) -> None:
    """Re-snapshotting tasks at publication would silently append to user changes."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    tasks_path = spec_dir / "tasks.md"
    tasks_path.write_text(_task("T-1"), encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = _stage_one_group(publisher)
        tasks_path.write_text(_task("T-1") + _task("T-99"), encoding="utf-8")

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
        first, second, third, fourth, fifth, sixth = allocation.task_ids
        for artifact in allocation.artifact_names:
            (allocation.attempt_dir / artifact).write_text("# Fix\n", encoding="utf-8")
        (allocation.attempt_dir / "tasks-append.md").write_text(
            _append(
                (first, "RF1-T1"), (second, "RF2-T1"), (third, "RF2-T2"),
                (fourth, "RF2-T3"), (fifth, "RF1-T2"), (sixth, "RF1-T3"),
            ), encoding="utf-8"
        )
        _write_manifest(
            allocation,
            artifacts=list(allocation.artifact_names),
            tasks=[
                {"task_id": first, "review_task_id": "RF1-T1", "artifact": "review-fix-1.md"},
                {"task_id": second, "review_task_id": "RF2-T1", "artifact": "review-fix-2.md"},
                {"task_id": third, "review_task_id": "RF2-T2", "artifact": "review-fix-2.md"},
                {"task_id": fourth, "review_task_id": "RF2-T3", "artifact": "review-fix-2.md"},
                {"task_id": fifth, "review_task_id": "RF1-T2", "artifact": "review-fix-1.md"},
                {"task_id": sixth, "review_task_id": "RF1-T3", "artifact": "review-fix-1.md"},
            ],
        )

        with pytest.raises(ReviewArtifactError, match="per artifact"):
            publisher.accept_manifest(allocation.status_file)


def test_allocation_and_append_round_trip_through_canonical_task_parser(tmp_path: Path) -> None:
    """Short numeric IDs would produce rows the Phase 1 parser cannot consume."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    (spec_dir / "tasks.md").write_text(_task("T-009"), encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = publisher.allocate(("c1",))

    assert allocation.task_ids == ("T-000010", "T-000011", "T-000012")


def test_lock_release_preserves_a_replacement_lock(tmp_path: Path) -> None:
    """Unlinking by path on exit must not delete a contender's replacement lock."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    publisher = ReviewArtifactPublisher(spec_dir, state_dir, "default")
    publisher.__enter__()
    replacement = spec_dir / "replacement"
    replacement.write_text("pid=999999999\ncreated_at=now\nstrategy=other\n", encoding="utf-8")
    os.replace(replacement, spec_dir / ".echelon-review.lock")

    publisher.__exit__(None, None, None)

    assert (spec_dir / ".echelon-review.lock").exists()


def test_failed_lock_metadata_write_cleans_up_its_new_lock(tmp_path: Path) -> None:
    """A failed acquire must not strand an empty lock that blocks later review work."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    with patch("harness.review_artifacts.os.fsync", side_effect=OSError("disk failure")):
        with pytest.raises(ReviewArtifactError):
            ReviewArtifactPublisher(spec_dir, state_dir, "default").__enter__()

    assert not (spec_dir / ".echelon-review.lock").exists()


def test_live_os_lock_contender_cannot_acquire_during_metadata_install(tmp_path: Path) -> None:
    """A concurrent allocator must contend on the same owned lock inode."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    first = ReviewArtifactPublisher(spec_dir, state_dir, "default")
    first.__enter__()
    try:
        with pytest.raises(ReviewArtifactError, match="lock"):
            ReviewArtifactPublisher(spec_dir, state_dir, "default").__enter__()
    finally:
        first.__exit__(None, None, None)


def test_manifest_append_requires_canonical_rows_and_review_title_details(tmp_path: Path) -> None:
    """Text merely resembling tasks must not bypass the canonical Phase 1 parser."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    (spec_dir / "tasks.md").write_text(_task("T-001"), encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = publisher.allocate(("c1",))
        first, second, third = allocation.task_ids
        (allocation.attempt_dir / "review-fix-1.md").write_text("# Fix\n", encoding="utf-8")
        (allocation.attempt_dir / "tasks-append.md").write_text(
            _task(first) + _task(second) + _task(third) + "untrusted prose\n",
            encoding="utf-8",
        )
        _write_manifest(
            allocation,
            artifacts=["review-fix-1.md"],
            tasks=[
                {
                    "task_id": task_id,
                    "review_task_id": f"RF1-T{index}",
                    "artifact": "review-fix-1.md",
                }
                for index, task_id in enumerate((first, second, third), start=1)
            ],
        )
        with pytest.raises(ReviewArtifactError, match="review title|malformed"):
            publisher.accept_manifest(allocation.status_file)


def test_recovery_rejects_corrupt_journal_before_canonical_mutation(tmp_path: Path) -> None:
    """Recovery must validate journal content/digests before replaying any writes."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    original = _task("T-001")
    (spec_dir / "tasks.md").write_text(original, encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = _stage_one_group(publisher)
        publisher._after_publication_boundary = lambda boundary: (_ for _ in ()).throw(RuntimeError("crash")) if boundary == "journal-created" else None
        with pytest.raises(RuntimeError, match="crash"):
            publisher.accept_manifest(allocation.status_file)

    journal_path = state_dir / "default-review-publication.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["artifacts"][0]["digest"] = "0" * 64
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        with pytest.raises(ReviewArtifactError, match="digest"):
            publisher.recover_publication(set())

    assert (spec_dir / "tasks.md").read_text(encoding="utf-8") == original
    assert not (spec_dir / "review-fix-1.md").exists()


@pytest.mark.parametrize(
    "boundary",
    ["journal-created", "artifact-write:review-fix-1.md", "artifact-flag:review-fix-1.md", "tasks-write", "tasks-flag", "complete-write"],
)
def test_recovery_is_idempotent_after_each_publication_write_boundary(tmp_path: Path, boundary: str) -> None:
    """Each durable boundary must recover to one complete batch with one task append."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    (spec_dir / "tasks.md").write_text(_task("T-001"), encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = _stage_one_group(publisher)
        publisher._after_publication_boundary = lambda actual: (_ for _ in ()).throw(RuntimeError("crash")) if actual == boundary else None
        with pytest.raises(RuntimeError, match="crash"):
            publisher.accept_manifest(allocation.status_file)

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        first = publisher.recover_publication(set())
        second = publisher.recover_publication(set())

    assert first is not None and second == first
    tasks = (spec_dir / "tasks.md").read_text(encoding="utf-8")
    assert [row.task_id for row in parse_task_rows(tasks)] == [
        "T-001",
        "T-000002",
        "T-000003",
        "T-000004",
    ]


def test_recovery_preserves_conflicting_artifact_after_crash(tmp_path: Path) -> None:
    """A changed canonical artifact after a crash is a blocker, never an overwrite target."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    original = _task("T-001")
    (spec_dir / "tasks.md").write_text(original, encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = _stage_one_group(publisher)
        publisher._after_publication_boundary = lambda actual: (_ for _ in ()).throw(RuntimeError("crash")) if actual == "artifact-write:review-fix-1.md" else None
        with pytest.raises(RuntimeError, match="crash"):
            publisher.accept_manifest(allocation.status_file)

    artifact = spec_dir / "review-fix-1.md"
    artifact.write_text("user conflict", encoding="utf-8")
    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        with pytest.raises(ReviewArtifactError, match="conflicts"):
            publisher.recover_publication(set())

    assert artifact.read_text(encoding="utf-8") == "user conflict"
    assert (spec_dir / "tasks.md").read_text(encoding="utf-8") == original


@pytest.mark.parametrize("mutation", ["version", "extra", "duplicate_comment", "task_relationship", "append_digest"])
def test_recovery_validates_each_journal_contract_before_replaying(tmp_path: Path, mutation: str) -> None:
    """Journal shape, IDs, and bytes are proof; any inconsistency blocks replay."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    original = _task("T-001")
    (spec_dir / "tasks.md").write_text(original, encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = _stage_one_group(publisher)
        publisher._after_publication_boundary = lambda actual: (_ for _ in ()).throw(RuntimeError("crash")) if actual == "journal-created" else None
        with pytest.raises(RuntimeError, match="crash"):
            publisher.accept_manifest(allocation.status_file)

    journal_path = state_dir / "default-review-publication.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if mutation == "version":
        journal["version"] = 2
    elif mutation == "extra":
        journal["unexpected"] = True
    elif mutation == "duplicate_comment":
        journal["comment_ids"] *= 2
    elif mutation == "task_relationship":
        journal["task_ids"][1] = "T-000005"
    else:
        journal["tasks_append"]["content"] = "eA=="
    journal_path.write_text(json.dumps(journal), encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        with pytest.raises(ReviewArtifactError):
            publisher.recover_publication(set())

    assert (spec_dir / "tasks.md").read_text(encoding="utf-8") == original
    assert not (spec_dir / "review-fix-1.md").exists()


def test_consumed_journal_removal_boundary_never_replays_published_work(tmp_path: Path) -> None:
    """A crash after rotating a consumed journal must leave the completed batch intact."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    (spec_dir / "tasks.md").write_text(_task("T-001"), encoding="utf-8")

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        allocation = _stage_one_group(publisher)
        result = publisher.accept_manifest(allocation.status_file)
        publisher.mark_consumed(result.attempt_id)

    with ReviewArtifactPublisher(spec_dir, state_dir, "default") as publisher:
        publisher._after_publication_boundary = lambda actual: (_ for _ in ()).throw(RuntimeError("crash")) if actual == "journal-removed" else None
        with pytest.raises(RuntimeError, match="crash"):
            publisher.allocate(())

    assert not (state_dir / "default-review-publication.json").exists()
    assert [
        row.task_id
        for row in parse_task_rows((spec_dir / "tasks.md").read_text(encoding="utf-8"))
    ] == ["T-001", "T-000002", "T-000003", "T-000004"]


def test_repeated_lock_contention_resets_contender_ownership_state(tmp_path: Path) -> None:
    """Every failed flock acquisition must close its fd and leave no claimed owner state."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    owner = ReviewArtifactPublisher(spec_dir, state_dir, "default")
    owner.__enter__()
    try:
        contender = ReviewArtifactPublisher(spec_dir, state_dir, "default")
        original_close = os.close
        closed: list[int] = []

        def record_close(fd: int) -> None:
            closed.append(fd)
            original_close(fd)

        with patch("harness.review_artifacts.os.close", side_effect=record_close):
            for _ in range(2):
                with pytest.raises(ReviewArtifactError, match="lock"):
                    contender.__enter__()
                assert contender._lock_fd is None
                assert contender._lock_token is None
                assert contender._lock_identity is None
                assert contender._locked is False
        assert len(closed) == 2
    finally:
        owner.__exit__(None, None, None)


@pytest.mark.parametrize("failure", ["write", "fsync"])
def test_release_metadata_failure_fails_closed_without_unlocking_live_metadata(
    tmp_path: Path, failure: str
) -> None:
    """A failed release marker cannot be unlocked while it still claims ownership."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    publisher = ReviewArtifactPublisher(spec_dir, state_dir, "default")
    publisher.__enter__()

    if failure == "write":
        original_write = os.write

        def fail_release_write(fd: int, data: bytes) -> int:
            if fd == publisher._lock_fd and b"released=true" in bytes(data):
                raise OSError("write failed")
            return original_write(fd, data)

        context = patch("harness.review_artifacts.os.write", side_effect=fail_release_write)
    else:
        context = patch("harness.review_artifacts.os.fsync", side_effect=OSError("fsync failed"))

    with context:
        with pytest.raises(ReviewArtifactError, match="release"):
            publisher.__exit__(None, None, None)

    assert publisher._lock_fd is not None
    assert publisher._locked is True
    contender = ReviewArtifactPublisher(spec_dir, state_dir, "default")
    with pytest.raises(ReviewArtifactError, match="lock"):
        contender.__enter__()

    # Simulate process termination after the deliberately fail-closed release.
    import fcntl

    fcntl.flock(publisher._lock_fd, fcntl.LOCK_UN)
    os.close(publisher._lock_fd)
    publisher._clear_lock_state()


def test_release_failure_never_deletes_replacement_installed_during_failure(tmp_path: Path) -> None:
    """No release fallback may turn an inode check into deletion of a new owner."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    publisher = ReviewArtifactPublisher(spec_dir, state_dir, "default")
    publisher.__enter__()
    replacement = spec_dir / "replacement"
    replacement_payload = "pid=999999999\ncreated_at=replacement\nstrategy=other\n"
    replacement.write_text(replacement_payload, encoding="utf-8")
    original_write = os.write

    def replace_then_fail(fd: int, data: bytes) -> int:
        if fd == publisher._lock_fd and b"released=true" in bytes(data):
            os.replace(replacement, spec_dir / ".echelon-review.lock")
            raise OSError("release write failed")
        return original_write(fd, data)

    with patch("harness.review_artifacts.os.write", side_effect=replace_then_fail):
        with pytest.raises(ReviewArtifactError, match="release"):
            publisher.__exit__(None, None, None)

    assert (spec_dir / ".echelon-review.lock").read_text(encoding="utf-8") == replacement_payload
    assert publisher._locked is True
    import fcntl

    fcntl.flock(publisher._lock_fd, fcntl.LOCK_UN)
    os.close(publisher._lock_fd)
    publisher._clear_lock_state()


def test_normal_release_does_not_depend_on_directory_fsync_for_path_removal(tmp_path: Path) -> None:
    """Release persists `released=true` in-place, so no unlink durability window exists."""
    spec_dir = tmp_path / "spec"
    state_dir = tmp_path / "state"
    spec_dir.mkdir()
    publisher = ReviewArtifactPublisher(spec_dir, state_dir, "default")
    publisher.__enter__()

    with patch("harness.review_artifacts._fsync_directory", side_effect=OSError("directory fsync failed")) as sync:
        publisher.__exit__(None, None, None)

    sync.assert_not_called()
    assert "released=true" in (spec_dir / ".echelon-review.lock").read_text(encoding="utf-8")
    with ReviewArtifactPublisher(spec_dir, state_dir, "default"):
        pass
