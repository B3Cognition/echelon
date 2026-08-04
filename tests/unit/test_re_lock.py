from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import harness.re_lock as re_lock
from harness.re_lock import (
    ReExtractLocked,
    ReExtractionLock,
    RePublicationActiveRun,
    RePublishLock,
    RePublishLocked,
    RePublishRecoveryRequired,
    claim_orphan_publish_recovery,
    find_other_active_runs,
    recover_stale_publish_lock,
)
from harness.re_registry import ensure_re_layout


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_run(
    root: Path,
    run_id: str,
    status: str,
    *,
    run_kind: str | None = None,
) -> Path:
    run_dir = root / "runs" / run_id
    state: dict[str, object] = {"run_id": run_id, "status": status}
    if run_kind is not None:
        state["run_kind"] = run_kind
    _write_json(run_dir / "state.json", state)
    return run_dir


def _write_lock(
    root: Path,
    *,
    run_id: str = "run-old",
    pid: int = 999_999_999,
    hostname: str | None = None,
    age_seconds: int = 7200,
) -> Path:
    paths = ensure_re_layout(root)
    lock_dir = paths.locks / "publish.lock"
    lock_dir.mkdir()
    acquired_at = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    _write_json(
        lock_dir / "owner.json",
        {
            "run_id": run_id,
            "run_dir": str(root / "runs" / run_id),
            "pid": pid,
            "hostname": hostname or socket.gethostname(),
            "acquired_at": acquired_at.isoformat(),
        },
    )
    return lock_dir


@pytest.mark.unit
def test_second_live_publisher_cannot_acquire(tmp_path: Path) -> None:
    with RePublishLock.acquire(tmp_path, "run-a", None):
        with pytest.raises(RePublishLocked, match="run-a"):
            RePublishLock.acquire(tmp_path, "run-b", None)


@pytest.mark.unit
def test_second_live_extractor_cannot_acquire(tmp_path: Path) -> None:
    owner = _write_run(tmp_path, "run-a", "running")

    with ReExtractionLock.acquire(tmp_path, "run-a", owner):
        with pytest.raises(ReExtractLocked, match="run-a"):
            ReExtractionLock.acquire(tmp_path, "run-b", _write_run(tmp_path, "run-b", "running"))

    with ReExtractionLock.acquire(tmp_path, "run-b", _write_run(tmp_path, "run-b", "running")):
        pass


@pytest.mark.unit
def test_extractor_reclaims_dead_local_owner(tmp_path: Path) -> None:
    paths = ensure_re_layout(tmp_path)
    lock_dir = paths.locks / "extract.lock"
    lock_dir.mkdir()
    _write_json(
        lock_dir / "owner.json",
        {
            "run_id": "run-dead",
            "run_dir": str(tmp_path / "runs" / "run-dead"),
            "pid": 999_999_999,
            "hostname": socket.gethostname(),
            "acquired_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    with ReExtractionLock.acquire(
        tmp_path, "run-next", _write_run(tmp_path, "run-next", "running")
    ) as lock:
        owner = json.loads((lock.path / "owner.json").read_text(encoding="utf-8"))
        assert owner["run_id"] == "run-next"
        assert owner["pid"] == os.getpid()


@pytest.mark.unit
def test_owner_run_is_excluded_but_another_active_run_blocks(tmp_path: Path) -> None:
    owner = _write_run(tmp_path, "re-a", "running", run_kind="re")
    other = _write_run(tmp_path, "re-b", "in_progress", run_kind="re")
    _write_run(tmp_path, "run-done", "done")

    assert find_other_active_runs(tmp_path, owner) == (other.resolve(),)
    with pytest.raises(RePublicationActiveRun, match="re-b"):
        RePublishLock.acquire(tmp_path, "re-a", owner)


@pytest.mark.unit
def test_active_spec_run_does_not_block_re_publication(tmp_path: Path) -> None:
    owner = _write_run(tmp_path, "re-a", "running", run_kind="re")
    _write_run(tmp_path, "spec-a", "in_progress")

    assert find_other_active_runs(tmp_path, owner) == ()
    with RePublishLock.acquire(tmp_path, "re-a", owner):
        pass


@pytest.mark.unit
def test_owner_run_may_acquire_when_it_is_the_only_active_run(tmp_path: Path) -> None:
    owner = _write_run(tmp_path, "run-a", "running")

    with RePublishLock.acquire(tmp_path, "run-a", owner) as lock:
        metadata = json.loads((lock.path / "owner.json").read_text(encoding="utf-8"))
        assert metadata["run_id"] == "run-a"
        assert metadata["run_dir"] == str(owner.resolve())
        assert metadata["pid"] == os.getpid()

    assert not lock.path.exists()


@pytest.mark.unit
def test_stale_lock_recovery_requires_dead_owner_and_inactive_run(tmp_path: Path) -> None:
    lock_dir = _write_lock(tmp_path)

    assert recover_stale_publish_lock(tmp_path, stale_after_seconds=3600)
    assert not lock_dir.exists()


@pytest.mark.unit
def test_stale_lock_recovery_refuses_live_local_process(tmp_path: Path) -> None:
    lock_dir = _write_lock(tmp_path, pid=os.getpid())

    assert not recover_stale_publish_lock(tmp_path, stale_after_seconds=0)
    assert lock_dir.exists()


@pytest.mark.unit
def test_stale_lock_recovery_refuses_active_owner_run(tmp_path: Path) -> None:
    _write_run(tmp_path, "run-old", "running")
    lock_dir = _write_lock(tmp_path)

    assert not recover_stale_publish_lock(tmp_path, stale_after_seconds=0)
    assert lock_dir.exists()


@pytest.mark.unit
def test_stale_lock_recovery_refuses_unfinished_rollback(tmp_path: Path) -> None:
    lock_dir = _write_lock(tmp_path)
    _write_json(
        tmp_path / "re" / ".staging" / "run-old" / "rollback-journal.json",
        {"status": "replacing", "completed_operations": []},
    )

    with pytest.raises(RePublishRecoveryRequired, match="rollback"):
        recover_stale_publish_lock(tmp_path, stale_after_seconds=0)
    assert lock_dir.exists()


@pytest.mark.unit
@pytest.mark.parametrize("status", ("replacing", "rolling_back"))
def test_pending_journal_keeps_owner_lock_and_blocks_a_second_publisher(
    tmp_path: Path, status: str
) -> None:
    with RePublishLock.acquire(tmp_path, "run-a", None) as lock:
        _write_json(
            tmp_path / "re/.staging/run-a/rollback-journal.json",
            {"schema_version": 1, "status": status, "operations": []},
        )
    assert lock.path.exists()
    with pytest.raises(RePublishLocked, match="run-a"):
        RePublishLock.acquire(tmp_path, "run-b", None)


@pytest.mark.unit
def test_orphan_pending_journal_blocks_new_publication(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "re/.staging/orphan/rollback-journal.json",
        {"schema_version": 1, "status": "replacing", "operations": []},
    )
    with pytest.raises(RePublishRecoveryRequired, match="rollback journal"):
        RePublishLock.acquire(tmp_path, "run-next", None)


@pytest.mark.unit
def test_orphan_claim_error_does_not_leave_a_publish_lock(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "re/.staging/first/rollback-journal.json",
        {"schema_version": 1, "status": "replacing", "operations": []},
    )
    _write_json(
        tmp_path / "re/.staging/second/rollback-journal.json",
        {"schema_version": 1, "status": "rolling_back", "operations": []},
    )

    with pytest.raises(RePublishRecoveryRequired, match="multiple orphan"):
        claim_orphan_publish_recovery(tmp_path)
    assert not (tmp_path / "re/.locks/publish.lock").exists()


@pytest.mark.unit
def test_orphan_claim_recheck_no_work_cleans_its_temporary_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = tmp_path / "re/.staging/orphan/rollback-journal.json"
    observations = [(journal,), ()]

    def observed_pending(_staging: Path) -> tuple[Path, ...]:
        return observations.pop(0)

    monkeypatch.setattr(re_lock, "_pending_publication_journals", observed_pending)
    assert claim_orphan_publish_recovery(tmp_path) is None
    assert not (tmp_path / "re/.locks/publish.lock").exists()


@pytest.mark.unit
def test_recovery_claim_never_replaces_an_empty_or_nonempty_publish_lock(
    tmp_path: Path,
) -> None:
    paths = ensure_re_layout(tmp_path)
    _write_json(
        paths.staging / "orphan/rollback-journal.json",
        {"schema_version": 1, "status": "replacing", "operations": []},
    )
    lock = paths.locks / "publish.lock"
    lock.mkdir()

    assert claim_orphan_publish_recovery(tmp_path) is None
    assert lock.exists()
    assert not (lock / "owner.json").exists()

    _write_json(
        lock / "owner.json",
        {
            "run_id": "publisher",
            "run_dir": None,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "acquired_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert claim_orphan_publish_recovery(tmp_path) is None
    with pytest.raises(RePublishLocked, match="publisher"):
        RePublishLock.acquire(tmp_path, "next", None)


@pytest.mark.unit
def test_two_orphan_recovery_claimants_have_one_exclusive_owner(tmp_path: Path) -> None:
    paths = ensure_re_layout(tmp_path)
    _write_json(
        paths.staging / "orphan/rollback-journal.json",
        {"schema_version": 1, "status": "replacing", "operations": []},
    )

    first = claim_orphan_publish_recovery(tmp_path)
    second = claim_orphan_publish_recovery(tmp_path)

    assert first is not None
    assert second is None
    assert json.loads((first.path / "owner.json").read_text(encoding="utf-8"))["run_id"] == "orphan"
    _write_json(
        paths.staging / "orphan/rollback-journal.json",
        {"schema_version": 1, "status": "rolled_back", "operations": []},
    )
    first.release()


@pytest.mark.unit
@pytest.mark.parametrize("failure", ("lock_mkdir", "lock_fsync", "owner_write", "claim_remove"))
def test_normal_claim_acquisition_errors_leave_no_permanent_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    paths = ensure_re_layout(tmp_path)
    lock = paths.locks / "publish.lock"
    original_mkdir = Path.mkdir
    original_fsync = re_lock._fsync_directory
    original_write = re_lock._write_json_atomic
    original_release = re_lock._release_publication_claim
    release_calls = 0

    if failure == "lock_mkdir":
        def fail_mkdir(path: Path, *args: object, **kwargs: object) -> None:
            if path == lock:
                raise OSError("lock mkdir failed")
            original_mkdir(path, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", fail_mkdir)
    elif failure == "lock_fsync":
        def fail_fsync(path: Path) -> None:
            if path == paths.locks and lock.exists():
                raise OSError("lock fsync failed")
            original_fsync(path)

        monkeypatch.setattr(re_lock, "_fsync_directory", fail_fsync)
    elif failure == "owner_write":
        def fail_owner_write(path: Path, *args: object, **kwargs: object) -> None:
            if path == lock / "owner.json":
                raise OSError("owner write failed")
            original_write(path, *args, **kwargs)

        monkeypatch.setattr(re_lock, "_write_json_atomic", fail_owner_write)
    else:
        def fail_first_claim_remove(*args: object, **kwargs: object) -> None:
            nonlocal release_calls
            release_calls += 1
            if release_calls == 1:
                raise OSError("claim remove failed")
            original_release(*args, **kwargs)

        monkeypatch.setattr(re_lock, "_release_publication_claim", fail_first_claim_remove)

    with pytest.raises(OSError):
        RePublishLock.acquire(tmp_path, "run-a", None)
    assert not lock.exists()
    assert not (paths.locks / ".publish-claim.json").exists()


@pytest.mark.unit
def test_claim_publication_error_leaves_only_an_ignored_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = ensure_re_layout(tmp_path)

    def fail_link(*_args: object, **_kwargs: object) -> None:
        raise OSError("claim publication failed")

    monkeypatch.setattr(re_lock.os, "link", fail_link)
    with pytest.raises(OSError, match="claim publication failed"):
        RePublishLock.acquire(tmp_path, "run-a", None)

    assert not (paths.locks / "publish.lock").exists()
    assert not (paths.locks / ".publish-claim.json").exists()


@pytest.mark.unit
def test_dead_fixed_claim_is_taken_over_without_leaving_an_orphan(tmp_path: Path) -> None:
    paths = ensure_re_layout(tmp_path)
    _write_json(
        paths.locks / ".publish-claim.json",
        {
            "run_id": "dead",
            "run_dir": None,
            "pid": 999_999_999,
            "hostname": socket.gethostname(),
            "acquired_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            "claim_kind": "publisher",
        },
    )

    with RePublishLock.acquire(tmp_path, "next", None):
        assert (paths.locks / "publish.lock/owner.json").is_file()
        assert not (paths.locks / ".publish-claim.json").exists()

    assert not (paths.locks / "publish.lock").exists()
    assert not (paths.locks / ".publish-claim.json").exists()


@pytest.mark.unit
def test_normal_and_recovery_share_one_fixed_claim(tmp_path: Path) -> None:
    paths = ensure_re_layout(tmp_path)
    _write_json(
        paths.staging / "orphan/rollback-journal.json",
        {"schema_version": 1, "status": "replacing", "operations": []},
    )
    metadata = re_lock._owner_metadata("publisher", None, claim_kind="publisher")
    claim = re_lock._acquire_publication_claim(paths, tmp_path, metadata)
    assert claim is not None

    assert claim_orphan_publish_recovery(tmp_path) is None
    re_lock._release_publication_claim(paths, claim)
    assert not (paths.locks / ".publish-claim.json").exists()


@pytest.mark.unit
def test_different_host_lock_must_exceed_stale_threshold(tmp_path: Path) -> None:
    lock_dir = _write_lock(
        tmp_path,
        hostname="another-host",
        age_seconds=30,
    )

    assert not recover_stale_publish_lock(tmp_path, stale_after_seconds=3600)
    assert lock_dir.exists()


@pytest.mark.unit
def test_stale_lock_recovery_rejects_unsafe_owner_run_id(tmp_path: Path) -> None:
    _write_lock(tmp_path, run_id="../../outside")

    with pytest.raises(RePublishRecoveryRequired, match="run ID"):
        recover_stale_publish_lock(tmp_path, stale_after_seconds=0)
