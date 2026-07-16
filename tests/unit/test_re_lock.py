from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness.re_lock import (
    ReExtractLocked,
    ReExtractionLock,
    RePublicationActiveRun,
    RePublishLock,
    RePublishLocked,
    RePublishRecoveryRequired,
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
