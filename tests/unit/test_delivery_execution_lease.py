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
        with pytest.raises(DeliveryExecutionLocked):
            with target_delivery_execution_lease(first, adapter_reentry=True):
                pass
        with target_delivery_execution_lease(second):
            pass

    with target_delivery_execution_lease(first, allow_adapter_reentry=True):
        with target_delivery_execution_lease(first, adapter_reentry=True):
            with pytest.raises(DeliveryExecutionLocked):
                with target_delivery_execution_lease(first, adapter_reentry=True):
                    pass
        with target_delivery_execution_lease(first, adapter_reentry=True):
            pass
        result = []

        def competing_command():
            try:
                with target_delivery_execution_lease(first):
                    result.append("overlapped")
            except DeliveryExecutionLocked:
                result.append("contended")

        worker = threading.Thread(target=competing_command)
        worker.start()
        worker.join(timeout=10)
        assert not worker.is_alive()
        assert result == ["contended"]
    with target_delivery_execution_lease(first):
        pass


@pytest.mark.parametrize("command", ["run", "resume"])
@pytest.mark.parametrize(
    "targets", [["sources/api"], ["sources/api", "sources/web"]],
)
def test_polyrepo_parent_does_not_hold_workspace_lease_across_target_dispatch(
    tmp_path, monkeypatch, command, targets,
):
    from echelon import delivery_service
    from harness.delivery_execution_lease import target_delivery_execution_lease

    workspace = tmp_path / "workspace"
    spec = workspace / "specs/001-test"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text(
        "---\ntargets:\n" + "".join(f"  - {target}\n" for target in targets) + "---\n"
    )
    reached = []

    def delegated(*_args, **_kwargs):
        reached.append("orchestrator")

    inner = (
        "_run_delivery_under_lease"
        if command == "run" else "_run_delivery_resume_under_lease"
    )
    monkeypatch.setattr(delivery_service, inner, delegated)
    with target_delivery_execution_lease(workspace):
        if command == "run":
            delivery_service._run_delivery(workspace, ["001-test"])
        else:
            delivery_service._run_delivery_resume(workspace, ["001-test", "answer"])
    assert reached == ["orchestrator"]


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


@pytest.mark.parametrize("command", ["run", "resume"])
@pytest.mark.parametrize("polyrepo", [False, True])
def test_native_cli_contends_before_preparation_or_recovery_effects(
    tmp_path, monkeypatch, command, polyrepo,
):
    from echelon import delivery_service
    from echelon import cli
    from harness.delivery_execution_lease import target_delivery_execution_lease

    project = tmp_path / "workspace"
    project.mkdir()
    spec = project / "specs/001-test"
    spec.mkdir(parents=True)
    spec_file = spec / "spec.md"
    spec_file.write_text("# Test\n\n**Status**: Planned\n")
    harness_root = project
    if polyrepo:
        harness_root = project / "runs/targets/demo"
        monkeypatch.setenv("ECHELON_POLYREPO_ROOT", str(project))
        monkeypatch.setenv("ECHELON_TARGET_REPO_PATH", str(project / "sources/demo"))
        monkeypatch.setenv("ECHELON_TARGET_REPO_NAME", "demo")
    reached = []

    def preflight(*_args, **_kwargs):
        reached.append("provider preflight")
        raise AssertionError("native effects began before lease admission")

    monkeypatch.setattr(cli, "_require_provider_capability", preflight)
    entered = threading.Event()
    release = threading.Event()

    def hold_lease():
        with target_delivery_execution_lease(harness_root):
            entered.set()
            assert release.wait(timeout=10)

    worker = threading.Thread(target=hold_lease)
    worker.start()
    try:
        assert entered.wait(timeout=10)
        with pytest.raises(SystemExit) as exc_info:
            if command == "run":
                delivery_service._run_delivery(project, ["001-test"])
            else:
                delivery_service._run_delivery_resume(
                    project, ["001-test", "answer"],
                )
        assert exc_info.value.code == 1
        assert reached == []
        assert spec_file.read_text() == "# Test\n\n**Status**: Planned\n"
        assert not list(project.glob("runs/build-*"))
    finally:
        release.set()
        worker.join(timeout=10)
    assert not worker.is_alive()


def test_native_cli_lease_allows_its_own_adapter_and_releases_on_error(
    tmp_path, monkeypatch,
):
    from echelon import delivery_service
    from harness.skills import run_skill

    class StopAfterAdmission(Exception):
        pass

    reached = []

    def admission(**_kwargs):
        reached.append("adapter admission")
        raise StopAfterAdmission

    monkeypatch.setattr(run_skill, "_fresh_delivery_baseline", lambda *_: None)
    monkeypatch.setattr(run_skill, "_amended_delivery_completed_tasks", admission)

    def enter_adapter(*_args, **_kwargs):
        return run_skill._execute_delivery_run(
            intent=SimpleNamespace(spec_id="001-test", resume=False),
            provider=object(), gitops=object(), harness_root=tmp_path,
            workspace_root=tmp_path, spec_dir=None, config=object(),
            resume_build_id=None, summary_command="echelon delivery run",
        )

    monkeypatch.setattr(delivery_service, "_run_delivery_under_lease", enter_adapter)
    with pytest.raises(StopAfterAdmission):
        delivery_service._run_delivery(tmp_path, ["001-test"])
    assert reached == ["adapter admission"]
    with pytest.raises(StopAfterAdmission):
        delivery_service._run_delivery(tmp_path, ["001-test"])
    assert reached == ["adapter admission", "adapter admission"]
