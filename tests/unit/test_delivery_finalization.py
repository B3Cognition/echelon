"""Completed task scopes still owe Ralph's authoritative finalization gates."""
from pathlib import Path
import subprocess

import pytest

from harness.task_progress import update_task_progress_markdown
from tests.unit.test_delivery_controller import _initialize_git_worktree
from tests.unit.test_delivery_controller_integration import _build, _controller, _reconstruct
from tests.unit.test_delivery_slice_recovery import ProcessLost, _crash_after_receipt
from tests.unit.test_delivery_slice_runner import ScriptedExecutor, _run, slice_project


pytestmark = pytest.mark.unit


def _complete(spec: Path, ids=("T-001", "T-002")):
    path = spec / "tasks.md"
    text = path.read_text()
    for task_id in ids:
        text = update_task_progress_markdown(text, task_id, "DONE")
    path.write_text(text)
    return text


def test_completed_scope_hands_off_without_provider_or_fake_task(slice_project):
    before = _complete(slice_project[1])
    executor = ScriptedExecutor()
    result = _run(slice_project, executor)
    assert result.succeeded, result.reason
    assert result.reason == "delivery_tasks_complete_verification_required"
    assert result.task_ids == [] and result.token_usage == 0
    assert not executor.calls
    assert (slice_project[1] / "tasks.md").read_text() == before
    assert not list(slice_project[2].rglob("journal.json"))


def test_completed_target_does_not_implement_another_targets_task(slice_project):
    _complete(slice_project[1], ("T-001",))
    executor = ScriptedExecutor()
    result = _run(slice_project, executor, allowed_task_ids={"T-001"})
    assert result.succeeded and result.task_ids == [], result.reason
    assert not executor.calls
    assert "- [ ] T-002" in (slice_project[1] / "tasks.md").read_text()


def test_cancelled_completed_scope_does_not_advance_to_verification(slice_project):
    _complete(slice_project[1])
    executor = ScriptedExecutor()
    result = _run(slice_project, executor, stop_requested=lambda: True)
    assert not result.succeeded and result.reason == "delivery_slice_cancelled"
    assert not executor.calls


@pytest.mark.parametrize("status", ["DEGRADED", "DEFERRED", "BLOCKED", "PENDING"])
def test_unfinished_dependency_is_not_finalization(slice_project, status):
    _complete(slice_project[1])
    path = slice_project[1] / "tasks.md"
    path.write_text(update_task_progress_markdown(path.read_text(), "T-001", status))
    executor = ScriptedExecutor()
    result = _run(slice_project, executor, allowed_task_ids={"T-002"})
    assert not result.succeeded and not executor.calls


def test_fresh_completed_scope_is_repeatable_without_slice_pointer(slice_project, tmp_path):
    _complete(slice_project[1])
    executor = ScriptedExecutor()
    controller, store = _controller(slice_project, tmp_path, executor)
    for _ in range(2):
        result = _build(controller, slice_project)
        assert result["passed"] and result["task_ids"] == [], result
        assert result["tokens"] == 0
        assert "delivery_slice_operation" not in store.read()
        assert "delivery_slice_task_id" not in store.read()
        controller = _reconstruct(controller, store, executor)
    assert not executor.calls


def test_finalization_after_last_review_retires_only_applied_operation(slice_project, tmp_path):
    _complete(slice_project[1], ("T-001",))
    executor = ScriptedExecutor()
    controller, store = _controller(slice_project, tmp_path, executor)
    built = _build(controller, slice_project)
    assert built["passed"] and built["task_ids"] == ["T-002"], built
    controller._apply_build_task_progress(worktree_path=str(slice_project[0]), task_ids=built["task_ids"])
    # Before the outer boundary, the accepted operation must still replay.
    assert _build(controller, slice_project)["task_ids"] == ["T-002"]
    state = store.read()
    state["outer_iter"] += 1
    store.write(state)
    resumed = ScriptedExecutor()
    result = _build(_reconstruct(controller, store, resumed), slice_project)
    assert result["passed"] and result["task_ids"] == [], result
    assert "delivery_slice_operation" not in store.read()
    assert store.read()["delivery_slice_task_id"] == "T-002"  # Explicit repairs retain their target.
    assert store.read()["tokens_used"] == 28 and not resumed.calls
    assert len(list(store.state_dir.rglob("journal.json"))) == 1  # Retain evidence.


def test_task_checkboxes_cannot_bypass_unresolved_operation(slice_project, tmp_path, monkeypatch):
    controller, store = _controller(slice_project, tmp_path, ScriptedExecutor())
    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, 1)
        with pytest.raises(ProcessLost):
            _build(controller, slice_project)
    _complete(slice_project[1])
    executor = ScriptedExecutor()
    result = _build(_reconstruct(controller, store, executor), slice_project)
    assert not result["passed"] and not executor.calls
    assert "reconciliation_required" in result["build_reason"]


@pytest.mark.parametrize("docs_valid", [False, True])
def test_completed_build_reaches_real_documentation_gate_before_publication(
    slice_project, tmp_path, monkeypatch, docs_valid,
):
    _complete(slice_project[1])
    _initialize_git_worktree(slice_project[0])
    report = slice_project[1] / "documentation-impact-report.md"
    report.write_text(
        "---\ndocs_required: false\nnot_applicable_reason: Internal-only change.\n---\n"
        if docs_valid else "---\ndocs_required: invalid\n---\n"
    )
    if docs_valid:
        from tests.unit.test_delivery_documentation import review_report
        (slice_project[1] / "docs-verification-report.md").write_text(review_report())
    for args in (["add", "."], ["commit", "-m", "completed fixture"]):
        subprocess.run(["git", *args], cwd=slice_project[0], capture_output=True, check=True)
    executor = ScriptedExecutor()
    controller, store = _controller(slice_project, tmp_path, executor, "banzai")
    controller._config.verify_command = "python -m unittest"
    # This routing fixture has no Phase-A verification service. Keep the real
    # post-verify chain and documentation validator; no model fulfillment call.
    controller._fulfillment_runner = None
    observed = []
    real_post_verify = controller._apply_post_verify_gates

    def stop_after_gates(verify_result, worktree_path, **kwargs):
        observed.append(real_post_verify(verify_result, worktree_path, **kwargs))
        raise ProcessLost()  # Observe routing before any commit/publication.

    monkeypatch.setattr(controller, "_apply_post_verify_gates", stop_after_gates)
    with pytest.raises(ProcessLost):
        controller.run_loop(max_outer=1, max_inner=1, build_prompt="build")
    assert len(observed) == 1
    assert observed[0].passed is docs_valid, observed[0]
    if not docs_valid:
        assert observed[0].failures[0].id == "documentation-impact-report-invalid"
    assert not executor.calls
    assert not controller._gitops.push.called
