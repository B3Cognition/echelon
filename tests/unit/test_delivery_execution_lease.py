"""Native Delivery excludes overlapping commands for one target root."""

from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from harness.paths import current_build_marker


def test_same_target_contends_while_different_target_remains_available(tmp_path):
    from harness.delivery_execution_lease import (
        DeliveryExecutionLocked, target_delivery_execution_lease,
    )

    first, second = tmp_path / "first", tmp_path / "second"
    with target_delivery_execution_lease(first):
        with pytest.raises(DeliveryExecutionLocked):
            with target_delivery_execution_lease(first):
                pass
        with target_delivery_execution_lease(second):
            pass
    with target_delivery_execution_lease(first):
        pass


def test_lease_releases_after_exception_and_process_death(tmp_path):
    from harness.delivery_execution_lease import (
        DeliveryExecutionLocked, target_delivery_execution_lease,
    )

    target = tmp_path / "target"
    with pytest.raises(RuntimeError, match="controller failed"):
        with target_delivery_execution_lease(target):
            raise RuntimeError("controller failed")
    with target_delivery_execution_lease(target):
        pass

    code = "\n".join((
        "import sys",
        "from pathlib import Path",
        "from harness.delivery_execution_lease import target_delivery_execution_lease",
        "with target_delivery_execution_lease(Path(sys.argv[1])):",
        "    print('held', flush=True)",
        "    sys.stdin.read(1)",
    ))
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(target)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=Path(__file__).resolve().parents[2],
    )
    try:
        assert child.stdout.readline().strip() == "held", child.stderr.read()
        with pytest.raises(DeliveryExecutionLocked):
            with target_delivery_execution_lease(target):
                pass
        child.kill()
        child.wait(timeout=10)
        with target_delivery_execution_lease(target):
            pass
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


@pytest.mark.parametrize("resume", [False, True])
def test_native_adapter_contends_before_admission_or_marker(tmp_path, monkeypatch, resume):
    from harness.skills import run_skill

    entered = threading.Event()
    release = threading.Event()
    calls = []

    class StopAfterAdmission(Exception):
        pass

    def admission(**_kwargs):
        calls.append("admission")
        if len(calls) == 1:
            entered.set()
            assert release.wait(timeout=10)
        raise StopAfterAdmission

    monkeypatch.setattr(run_skill, "_fresh_delivery_baseline", lambda *_: None)
    monkeypatch.setattr(run_skill, "_amended_delivery_completed_tasks", admission)
    target = tmp_path / "target"
    arguments = dict(
        intent=SimpleNamespace(spec_id="001-test", resume=resume),
        provider=object(), gitops=object(), harness_root=target,
        workspace_root=tmp_path, spec_dir=None, config=object(),
        resume_build_id=None, summary_command="echelon delivery run",
    )
    first_result = []

    def first_command():
        try:
            run_skill._execute_delivery_run(**arguments)
        except StopAfterAdmission:
            first_result.append("stopped")

    worker = threading.Thread(target=first_command)
    worker.start()
    try:
        assert entered.wait(timeout=10)
        with pytest.raises(run_skill.RunContextError, match="delivery already running for this target"):
            run_skill._execute_delivery_run(**arguments)
        assert calls == ["admission"]
        assert not current_build_marker(target, "001-test").exists()
    finally:
        release.set()
        worker.join(timeout=10)
    assert first_result == ["stopped"]
    assert not worker.is_alive()


def test_unsafe_symlink_cannot_be_used_as_execution_lease(tmp_path):
    from harness.delivery_execution_lease import target_delivery_execution_lease

    target = tmp_path / "target"
    lock = target / "runs/.delivery-execution.lock"
    lock.parent.mkdir(parents=True)
    destination = tmp_path / "other-file"
    destination.write_text("not a lock")
    lock.symlink_to(destination)
    with pytest.raises(OSError):
        with target_delivery_execution_lease(target):
            pass
    assert destination.read_text() == "not a lock"
