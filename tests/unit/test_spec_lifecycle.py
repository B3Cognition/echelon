from __future__ import annotations

import json
import os
from pathlib import Path
import socket
from threading import Event, Thread

import pytest

from echelon.spec_lifecycle import (
    SpecLifecycleError,
    SpecLifecycleLock,
    SpecLifecycleLocked,
    SpecLifecycleRecoveryRequired,
    SpecMutationLock,
    SpecRunExecutionLock,
    SpecRunAmbiguous,
    SpecRunNotFound,
    begin_spec_switch,
    commit_spec_switch_pointer,
    discover_spec_runs,
    load_spec_switch_intent,
    mark_spec_switch_checked_out,
    recover_spec_switch,
    resolve_active_spec_run,
    resolve_spec_run,
)


def _write_run(
    root: Path,
    run_dir_name: str,
    *,
    base: str = "runs",
    run_id: str | None = None,
    spec_id: str = "001-spec-a",
    feature_branch: str | None = None,
    spec_dir: str | None = None,
) -> Path:
    run_dir = root / base / run_dir_name
    active_spec_dir = spec_dir or f"{base}/{run_dir_name}/specs/{spec_id}"
    (root / active_spec_dir).mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_id or f"runtime-{run_dir_name}",
                "spec_id": spec_id,
                "feature_branch": feature_branch or spec_id,
                "spec_dir": active_spec_dir,
                "published_spec_dir": f"specs/{spec_id}",
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def test_discover_spec_runs_reads_runs_and_legacy_squad_in_stable_order(
    tmp_path: Path,
) -> None:
    legacy = _write_run(tmp_path, "legacy-z", base="squad", spec_id="003-legacy")
    current = _write_run(tmp_path, "spec-a", spec_id="001-spec-a")

    runs = discover_spec_runs(tmp_path)

    assert [run.run_dir_name for run in runs] == ["legacy-z", "spec-a"]
    assert [run.run_dir for run in runs] == [legacy.resolve(), current.resolve()]
    assert runs[0].spec_dir == (legacy / "specs" / "003-legacy").resolve()


def test_resolve_spec_run_uses_each_exact_identity(tmp_path: Path) -> None:
    _write_run(
        tmp_path,
        "spec-run-a",
        run_id="runtime-id-a",
        spec_id="001-spec-a",
        feature_branch="feature/001-spec-a",
    )

    assert resolve_spec_run(tmp_path, "spec-run-a").run_dir_name == "spec-run-a"
    assert resolve_spec_run(tmp_path, "runtime-id-a").run_id == "runtime-id-a"
    assert resolve_spec_run(tmp_path, "001-spec-a").spec_id == "001-spec-a"
    assert (
        resolve_spec_run(tmp_path, "feature/001-spec-a").feature_branch
        == "feature/001-spec-a"
    )


def test_resolve_spec_run_prioritizes_exact_run_directory_name(tmp_path: Path) -> None:
    _write_run(tmp_path, "chosen", run_id="runtime-chosen", spec_id="001-chosen")
    _write_run(tmp_path, "other", run_id="chosen", spec_id="002-other")

    assert resolve_spec_run(tmp_path, "chosen").run_dir_name == "chosen"


def test_discover_spec_runs_skips_malformed_and_incomplete_states(tmp_path: Path) -> None:
    valid = _write_run(tmp_path, "valid", spec_id="004-valid")
    malformed = tmp_path / "runs" / "malformed"
    malformed.mkdir(parents=True)
    (malformed / "state.json").write_text("{not-json", encoding="utf-8")
    non_object = tmp_path / "runs" / "non-object"
    non_object.mkdir(parents=True)
    (non_object / "state.json").write_text("[]", encoding="utf-8")
    incomplete = tmp_path / "runs" / "incomplete"
    incomplete.mkdir(parents=True)
    (incomplete / "state.json").write_text(
        json.dumps({"run_id": "incomplete", "spec_id": "005-incomplete"}),
        encoding="utf-8",
    )
    outside = tmp_path / "runs" / "outside"
    outside.mkdir(parents=True)
    (outside / "state.json").write_text(
        json.dumps(
            {
                "run_id": "outside",
                "spec_id": "006-outside",
                "feature_branch": "006-outside",
                "spec_dir": "../outside-project",
            }
        ),
        encoding="utf-8",
    )

    assert [run.run_dir for run in discover_spec_runs(tmp_path)] == [valid.resolve()]
    with pytest.raises(SpecRunNotFound):
        resolve_spec_run(tmp_path, "malformed")


def test_discover_spec_runs_skips_run_directory_symlink_outside_project(
    tmp_path: Path,
) -> None:
    external = tmp_path.parent / f"{tmp_path.name}-external-run"
    external.mkdir()
    spec_dir = tmp_path / "specs" / "007-linked"
    spec_dir.mkdir(parents=True)
    (external / "state.json").write_text(
        json.dumps(
            {
                "run_id": "linked-external",
                "spec_id": "007-linked",
                "feature_branch": "007-linked",
                "spec_dir": "specs/007-linked",
            }
        ),
        encoding="utf-8",
    )
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "linked-run").symlink_to(external, target_is_directory=True)

    assert discover_spec_runs(tmp_path) == ()


def test_resolve_spec_run_accepts_unique_numeric_prefix(tmp_path: Path) -> None:
    _write_run(tmp_path, "spec-run-a", spec_id="001-spec-a")
    _write_run(tmp_path, "spec-run-b", spec_id="002-spec-b")

    assert resolve_spec_run(tmp_path, "001").spec_id == "001-spec-a"


def test_resolve_spec_run_rejects_ambiguous_numeric_prefix(tmp_path: Path) -> None:
    _write_run(tmp_path, "spec-run-a", spec_id="001-spec-a")
    _write_run(tmp_path, "spec-run-a2", spec_id="001-spec-a-retry")

    with pytest.raises(SpecRunAmbiguous) as error:
        resolve_spec_run(tmp_path, "001")

    assert [match.run_dir_name for match in error.value.matches] == [
        "spec-run-a",
        "spec-run-a2",
    ]


def test_resolve_active_spec_run_requires_exact_run_directory_pointer(
    tmp_path: Path,
) -> None:
    _write_run(tmp_path, "spec-run-a", spec_id="001-spec-a")
    (tmp_path / "runs" / ".current").write_text("spec-run-a\n", encoding="utf-8")

    assert resolve_active_spec_run(tmp_path).run_dir_name == "spec-run-a"


@pytest.mark.parametrize("pointer", [None, "", "unknown-run", "001-spec-a"])
def test_resolve_active_spec_run_rejects_invalid_pointer(
    tmp_path: Path,
    pointer: str | None,
) -> None:
    _write_run(tmp_path, "spec-run-a", spec_id="001-spec-a")
    if pointer is not None:
        (tmp_path / "runs" / ".current").write_text(f"{pointer}\n", encoding="utf-8")

    with pytest.raises(SpecRunNotFound):
        resolve_active_spec_run(tmp_path)


def _lock_dir(root: Path) -> Path:
    return root / ".echelon" / "runtime" / "spec-lifecycle.lock"


def _write_lock_owner(root: Path, payload: dict[str, object]) -> Path:
    lock_dir = _lock_dir(root)
    lock_dir.mkdir(parents=True)
    (lock_dir / "owner.json").write_text(json.dumps(payload), encoding="utf-8")
    return lock_dir


def test_lifecycle_lock_records_owner_and_releases_on_context_exit(tmp_path: Path) -> None:
    with SpecLifecycleLock.acquire(tmp_path, "switch-001") as lock:
        owner = json.loads((lock.path / "owner.json").read_text(encoding="utf-8"))
        assert owner["operation_id"] == "switch-001"
        assert owner["pid"] == os.getpid()
        assert owner["hostname"] == socket.gethostname()
        assert owner["acquired_at"]
        assert lock.path == _lock_dir(tmp_path)

    assert not lock.path.exists()


def test_lifecycle_lock_rejects_second_live_owner(tmp_path: Path) -> None:
    with SpecLifecycleLock.acquire(tmp_path, "switch-001"):
        with pytest.raises(SpecLifecycleLocked, match="switch-001"):
            SpecLifecycleLock.acquire(tmp_path, "switch-002")


def test_spec_mutation_lock_serializes_one_spec_but_not_siblings(
    tmp_path: Path,
) -> None:
    first = SpecMutationLock.acquire(tmp_path, "001-demo", "retarget-a")
    try:
        with pytest.raises(SpecLifecycleLocked, match="retarget-a"):
            SpecMutationLock.acquire(tmp_path, "001-demo", "delivery-b")
        sibling = SpecMutationLock.acquire(tmp_path, "002-other", "amend-c")
        sibling.release()
    finally:
        first.release()


def test_spec_mutation_lock_rejects_unsafe_spec_identity(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe spec identity"):
        SpecMutationLock.acquire(tmp_path, "../outside", "retarget-a")


def test_run_execution_lock_refuses_a_second_owner_without_blocking_sibling_run(
    tmp_path: Path,
) -> None:
    run_a = tmp_path / "runs" / "run-a"
    run_b = tmp_path / "runs" / "run-b"
    sibling_acquired = Event()
    release_sibling = Event()
    sibling_errors: list[BaseException] = []

    def hold_sibling() -> None:
        try:
            with SpecRunExecutionLock.acquire(
                run_b,
                "run-b-owner",
            ) as sibling:
                assert (
                    sibling.path
                    == run_b
                    / ".echelon"
                    / "runtime"
                    / "execution.lock"
                )
                sibling_acquired.set()
                assert release_sibling.wait(timeout=5)
        except BaseException as error:
            sibling_errors.append(error)
            sibling_acquired.set()

    with SpecRunExecutionLock.acquire(run_a, "run-a-owner") as first:
        assert first.path == run_a / ".echelon" / "runtime" / "execution.lock"
        with pytest.raises(SpecLifecycleLocked, match="run-a-owner"):
            SpecRunExecutionLock.acquire(run_a, "run-a-second")
        sibling_thread = Thread(target=hold_sibling)
        sibling_thread.start()
        assert sibling_acquired.wait(timeout=5)
        release_sibling.set()
        sibling_thread.join(timeout=5)

    assert not sibling_errors
    assert not sibling_thread.is_alive()


def test_lifecycle_lock_release_does_not_remove_different_owner(tmp_path: Path) -> None:
    lock = SpecLifecycleLock.acquire(tmp_path, "switch-001")
    owner_path = lock.path / "owner.json"
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    owner["operation_id"] = "switch-other"
    owner_path.write_text(json.dumps(owner), encoding="utf-8")

    with pytest.raises(SpecLifecycleLocked, match="switch-other"):
        lock.release()

    assert lock.path.exists()


def test_lifecycle_lock_reclaims_dead_local_owner(tmp_path: Path) -> None:
    _write_lock_owner(
        tmp_path,
        {
            "operation_id": "switch-dead",
            "pid": 999_999_999,
            "hostname": socket.gethostname(),
            "acquired_at": "2026-07-17T12:00:00+00:00",
        },
    )

    with SpecLifecycleLock.acquire(tmp_path, "switch-next") as lock:
        owner = json.loads((lock.path / "owner.json").read_text(encoding="utf-8"))
        assert owner["operation_id"] == "switch-next"


@pytest.mark.parametrize(
    "owner_text",
    [
        "{not-json",
        json.dumps(
            {
                "operation_id": "../../unsafe",
                "pid": 999_999_999,
                "hostname": socket.gethostname(),
                "acquired_at": "2026-07-17T12:00:00+00:00",
            }
        ),
        json.dumps(
            {
                "operation_id": "switch-invalid-pid",
                "pid": True,
                "hostname": socket.gethostname(),
                "acquired_at": "2026-07-17T12:00:00+00:00",
            }
        ),
        json.dumps(
            {
                "operation_id": "switch-remote",
                "pid": 999_999_999,
                "hostname": "another-host",
                "acquired_at": "2026-07-17T12:00:00+00:00",
            }
        ),
    ],
)
def test_lifecycle_lock_rejects_unprovable_stale_owner(
    tmp_path: Path,
    owner_text: str,
) -> None:
    lock_dir = _lock_dir(tmp_path)
    lock_dir.mkdir(parents=True)
    (lock_dir / "owner.json").write_text(owner_text, encoding="utf-8")

    with pytest.raises(SpecLifecycleRecoveryRequired):
        SpecLifecycleLock.acquire(tmp_path, "switch-next")

    assert lock_dir.exists()


def test_lifecycle_lock_rejects_unsafe_new_operation_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe lifecycle operation ID"):
        SpecLifecycleLock.acquire(tmp_path, "../../unsafe")


def _switch_runs(tmp_path: Path):
    _write_run(
        tmp_path,
        "spec-run-a",
        run_id="runtime-a",
        spec_id="001-spec-a",
        feature_branch="001-spec-a",
    )
    _write_run(
        tmp_path,
        "spec-run-b",
        run_id="runtime-b",
        spec_id="002-spec-b",
        feature_branch="002-spec-b",
    )
    (tmp_path / "runs" / ".current").write_text("spec-run-a\n", encoding="utf-8")
    return (
        resolve_spec_run(tmp_path, "spec-run-a"),
        resolve_spec_run(tmp_path, "spec-run-b"),
    )


def test_switch_intent_begin_and_mark_checked_out(tmp_path: Path) -> None:
    source, target = _switch_runs(tmp_path)

    intent = begin_spec_switch(
        tmp_path,
        source,
        target,
        observed_branch="001-spec-a",
        operation_id="switch-a-b",
    )

    assert intent.operation_id == "switch-a-b"
    assert intent.source_run == "spec-run-a"
    assert intent.target_run == "spec-run-b"
    assert intent.source_branch == "001-spec-a"
    assert intent.target_branch == "002-spec-b"
    assert intent.stage == "prepared"
    assert load_spec_switch_intent(tmp_path) == intent

    checked_out = mark_spec_switch_checked_out(
        tmp_path,
        "switch-a-b",
        observed_branch="002-spec-b",
    )

    assert checked_out.stage == "checked_out"
    assert load_spec_switch_intent(tmp_path) == checked_out


def test_switch_intent_refuses_overwrite_and_wrong_observed_branch(tmp_path: Path) -> None:
    source, target = _switch_runs(tmp_path)
    begin_spec_switch(
        tmp_path,
        source,
        target,
        observed_branch="001-spec-a",
        operation_id="switch-a-b",
    )

    with pytest.raises(SpecLifecycleRecoveryRequired, match="already exists"):
        begin_spec_switch(
            tmp_path,
            source,
            target,
            observed_branch="001-spec-a",
            operation_id="switch-second",
        )
    with pytest.raises(SpecLifecycleError, match="target branch"):
        mark_spec_switch_checked_out(
            tmp_path,
            "switch-a-b",
            observed_branch="001-spec-a",
        )

    assert load_spec_switch_intent(tmp_path).stage == "prepared"


def test_switch_intent_strictly_rejects_malformed_runtime_state(tmp_path: Path) -> None:
    intent_path = tmp_path / ".echelon" / "runtime" / "spec-switch-intent.json"
    intent_path.parent.mkdir(parents=True)
    intent_path.write_text(json.dumps({"stage": "unknown"}), encoding="utf-8")

    with pytest.raises(SpecLifecycleRecoveryRequired, match="switch intent"):
        load_spec_switch_intent(tmp_path)


def test_commit_switch_pointer_is_atomic_and_resolves_target(tmp_path: Path) -> None:
    source, target = _switch_runs(tmp_path)
    begin_spec_switch(
        tmp_path,
        source,
        target,
        observed_branch=source.feature_branch,
        operation_id="switch-a-b",
    )
    mark_spec_switch_checked_out(
        tmp_path,
        "switch-a-b",
        observed_branch=target.feature_branch,
    )

    result = commit_spec_switch_pointer(
        tmp_path,
        "switch-a-b",
        observed_branch=target.feature_branch,
    )

    assert result == target
    assert (tmp_path / "runs" / ".current").read_text(encoding="utf-8") == "spec-run-b\n"
    assert resolve_active_spec_run(tmp_path) == target
    assert load_spec_switch_intent(tmp_path) is None


def test_commit_switch_pointer_failure_preserves_old_pointer_and_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target = _switch_runs(tmp_path)
    begin_spec_switch(
        tmp_path,
        source,
        target,
        observed_branch=source.feature_branch,
        operation_id="switch-a-b",
    )
    mark_spec_switch_checked_out(
        tmp_path,
        "switch-a-b",
        observed_branch=target.feature_branch,
    )
    pointer = tmp_path / "runs" / ".current"
    original_replace = Path.replace

    def fail_pointer_replace(path: Path, destination: Path):
        if Path(destination) == pointer:
            raise OSError("simulated pointer replacement failure")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_pointer_replace)

    with pytest.raises(OSError, match="simulated pointer"):
        commit_spec_switch_pointer(
            tmp_path,
            "switch-a-b",
            observed_branch=target.feature_branch,
        )

    assert pointer.read_text(encoding="utf-8") == "spec-run-a\n"
    assert load_spec_switch_intent(tmp_path).stage == "checked_out"
    assert list((tmp_path / "runs").glob(".current-*.tmp")) == []


@pytest.mark.parametrize(
    ("stage", "pointer_run", "observed_branch", "expected_action"),
    [
        ("prepared", "spec-run-a", "001-spec-a", "aborted_before_checkout"),
        ("prepared", "spec-run-a", "002-spec-b", "completed_after_checkout"),
        ("checked_out", "spec-run-a", "002-spec-b", "completed_after_checkout"),
        ("checked_out", "spec-run-b", "002-spec-b", "cleared_completed_intent"),
    ],
)
def test_recover_spec_switch_handles_known_crash_windows(
    tmp_path: Path,
    stage: str,
    pointer_run: str,
    observed_branch: str,
    expected_action: str,
) -> None:
    source, target = _switch_runs(tmp_path)
    begin_spec_switch(
        tmp_path,
        source,
        target,
        observed_branch=source.feature_branch,
        operation_id="switch-a-b",
    )
    if stage == "checked_out":
        mark_spec_switch_checked_out(
            tmp_path,
            "switch-a-b",
            observed_branch=target.feature_branch,
        )
    (tmp_path / "runs" / ".current").write_text(f"{pointer_run}\n", encoding="utf-8")

    recovery = recover_spec_switch(tmp_path, observed_branch=observed_branch)

    assert recovery.action == expected_action
    assert recovery.source == source
    assert recovery.target == target
    expected_pointer = "spec-run-a" if expected_action == "aborted_before_checkout" else "spec-run-b"
    assert (tmp_path / "runs" / ".current").read_text(encoding="utf-8") == f"{expected_pointer}\n"
    assert load_spec_switch_intent(tmp_path) is None


def test_recover_spec_switch_refuses_inconsistent_branch_and_pointer(
    tmp_path: Path,
) -> None:
    source, target = _switch_runs(tmp_path)
    intent = begin_spec_switch(
        tmp_path,
        source,
        target,
        observed_branch=source.feature_branch,
        operation_id="switch-a-b",
    )
    pointer = tmp_path / "runs" / ".current"
    pointer.write_text("spec-run-b\n", encoding="utf-8")

    with pytest.raises(SpecLifecycleRecoveryRequired, match="inconsistent"):
        recover_spec_switch(tmp_path, observed_branch="unrelated-branch")

    assert pointer.read_text(encoding="utf-8") == "spec-run-b\n"
    assert load_spec_switch_intent(tmp_path) == intent


def test_recover_spec_switch_refuses_unrecorded_target_pointer_transition(
    tmp_path: Path,
) -> None:
    source, target = _switch_runs(tmp_path)
    intent = begin_spec_switch(
        tmp_path,
        source,
        target,
        observed_branch=source.feature_branch,
        operation_id="switch-a-b",
    )
    pointer = tmp_path / "runs" / ".current"
    pointer.write_text("spec-run-b\n", encoding="utf-8")

    with pytest.raises(SpecLifecycleRecoveryRequired, match="inconsistent"):
        recover_spec_switch(tmp_path, observed_branch=target.feature_branch)

    assert pointer.read_text(encoding="utf-8") == "spec-run-b\n"
    assert load_spec_switch_intent(tmp_path) == intent
