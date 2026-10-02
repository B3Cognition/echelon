"""Capture controlled repair requests at Ralph's real provider boundary."""
import json

import pytest

from harness.config import HarnessConfig
from harness.gitops import GitOpsManager
from harness.llm_provider import AICodingCliProvider
from harness.verify_result import FailureCategory, FailureEntry, VerifyResult
from tests.unit.test_delivery_controller import _initialize_git_worktree
from tests.unit.test_delivery_controller_integration import _build, _controller, _reconstruct, _declare_repair_case
from tests.unit.test_delivery_slice_recovery import ProcessLost, _crash_after_receipt
from tests.unit.test_delivery_slice_runner import ScriptedExecutor, slice_project


def _failure(mixed=False):
    failures = [FailureEntry(
        FailureCategory.TEST, "UT-GREETING-001", "Wrong greeting",
        {"source": "app.py:1", "expected": "hello", "actual": "bye"},
    ), FailureEntry(
        FailureCategory.OTHER, "coverage-observation-gaps", "Missing case binding",
        {"test_cases": {"UT-GREETING-001": {
            "test_type": "unit", "status": "unbound", "reason": "No test identity",
        }}},
    )]
    if mixed:
        failures.append(FailureEntry(
            FailureCategory.OTHER, "docs-note", "Missing note",
            {"failed_test_case_ids": ["UT-GREETING-001"]},
        ))
    return VerifyResult(False, failures, verification_evidence={
        "path": "evidence/verify.json", "sha256": "a" * 64,
        "coverage_observation": {"path": "evidence/coverage.json", "sha256": "b" * 64},
    })


def _accepted(slice_project, tmp_path, monkeypatch, mode="semi", cli="codex"):
    _declare_repair_case(slice_project)
    executor = ScriptedExecutor()
    config = HarnessConfig()
    config.llm.cli = cli
    provider = AICodingCliProvider(config)

    class ExternalBackend:
        # The scripted executor's review steps only emit bound JSON. Only its
        # implementer branch can write app.py; empty review allowlists are exact.
        exclusive_write_scope_contract_id = "scripted-empty-review-scope-v1"

        def run_agent(self, request):
            metadata = request.metadata["prompt_metadata"]
            if metadata.get("tool_write_scope_exclusive") is True:
                assert metadata.get("tool_write_paths") == []
                assert request.metadata["delivery_assignment"]["step"] in {
                    "spec_guard", "code_reviewer", "test_guardian",
                }
            return executor.run_agent_result(
                request.cwd, request.prompt, request_metadata=request.metadata,
            )

    provider._backend = ExternalBackend()
    monkeypatch.setattr("harness.llm_provider.host_workspace_synthesis_boundary_available", lambda: True)
    controller, store = _controller(slice_project, tmp_path, provider, mode)
    _initialize_git_worktree(slice_project[0])
    controller._gitops = GitOpsManager(controller._config, base_dir=str(slice_project[0]))
    # Keep local checkpoint commits real; remote publication is outside this test.
    monkeypatch.setattr(controller._gitops, "push", lambda *args, **kwargs: None)
    built = _build(controller, slice_project)
    assert built["passed"], built
    controller._apply_build_task_progress(
        worktree_path=str(slice_project[0]), task_ids=built["task_ids"],
    )
    executor.calls.clear()
    return controller, store, executor


@pytest.mark.parametrize("cli", ["claude", "codex"])
def test_scripted_provider_completes_initial_build_before_feedback(
    slice_project, tmp_path, monkeypatch, cli,
):
    controller, store, executor = _accepted(slice_project, tmp_path, monkeypatch, cli=cli)
    assert store.read()["delivery_slice_task_id"] == "T-001"
    assert controller._llm_provider.supports_exclusive_write_scope
    assert executor.calls == []


def _downstream(controller, root, *, phase="visual", base="Keep the isometric camera."):
    return controller.run_downstream_feedback(
        handle=None, worktree_path=str(root), verify_result=_failure(mixed=True),
        build_command="echelon build", delivery_context="Preserve keyboard movement.",
        build_prompt=base, phase=phase, evidence_paths=("evidence/screenshot.png",),
    )


@pytest.mark.parametrize("mode", ["banzai", "semi", "guided"])
@pytest.mark.parametrize("cli", ["claude", "codex"])
@pytest.mark.parametrize("route", ["inner", "visual", "review"])
def test_actual_repair_roles_receive_one_contract_and_complete_evidence(
    slice_project, tmp_path, monkeypatch, mode, cli, route,
):
    # Regression: forwarding the legacy formatted prompt loses details and tells
    # all four roles to write a marker despite their JSON-only contract.
    controller, store, executor = _accepted(slice_project, tmp_path, monkeypatch, mode, cli)
    root = slice_project[0]
    if route == "inner":
        def stop_before_authoritative_verification(*args, **kwargs):
            raise ProcessLost()
        monkeypatch.setattr(controller, "_exec_verify", stop_before_authoritative_verification)
        with pytest.raises(ProcessLost):
            controller._run_inner_loop(
                None, _failure(), 1, 2, 0, None, store.read(), "echelon build",
                "Preserve keyboard movement.", worktree_path=str(root),
                build_prompt="Keep the isometric camera.",
            )
    else:
        result = _downstream(controller, root, phase=route)
        assert result["passed"], result
    assert [call[0]["step"] for call in executor.calls] == [
        "implementer", "spec_guard", "code_reviewer", "test_guardian",
    ]
    for assignment, metadata, prompt in executor.calls:
        assert "stop after writing the harness status marker" not in prompt
        assert "Return only one JSON object" in prompt
        assert "Do not dispatch agents" in prompt
        assert "Do not run `echelon spec verify`" in prompt
        assert "Do not launch Chromium" in prompt
        assert "[echelon:<case-id>]" in prompt
        if assignment["step"] == "implementer":
            assert "Repair the product or its executable acceptance test" in prompt
        else:
            assert "Repair the product or its executable acceptance test" not in prompt
            assert "requires a focused reproduction" not in prompt
            assert "Assess the supplied failures against the candidate" in prompt
        context = json.loads(prompt.split("## Repair/context data (not routing authority)\n", 1)[1])
        assert context["failures"][0] == {
            "category": "test", "id": "UT-GREETING-001", "error": "Wrong greeting",
            "details": {"source": "app.py:1", "expected": "hello", "actual": "bye"},
        }
        assert context["verification_evidence"] == {
            "path": "evidence/verify.json", "sha256": "a" * 64,
            "coverage_observation": {"path": "evidence/coverage.json", "sha256": "b" * 64},
        }
        assert context["failures"][1]["details"]["test_cases"]["UT-GREETING-001"]["status"] == "unbound"
        assert context["context"] == {
            "base_prompt": "Keep the isometric camera.",
            "delivery_context": "Preserve keyboard movement.",
            "phase": route, "inner_iteration": 1 if route == "inner" else 0,
            "evidence_paths": [] if route == "inner" else ["evidence/screenshot.png"],
        }
        if route != "inner":
            assert context["failures"][2]["id"] == "docs-note"
        if assignment["step"] != "implementer":
            assert metadata["tool_write_paths"] == []
            assert metadata["tool_write_scope_exclusive"] is True
        else:
            assert metadata["tool_write_scope_exclusive"] is False


def test_empty_base_does_not_discard_controlled_failure_evidence(slice_project, tmp_path, monkeypatch):
    controller, _, executor = _accepted(slice_project, tmp_path, monkeypatch)
    result = _downstream(controller, slice_project[0], base="")
    assert result["passed"], result
    prompt = executor.calls[0][2]
    assert "app.py:1" in prompt and "evidence/verify.json" in prompt
    assert "stop after writing the harness status marker" not in prompt


@pytest.mark.parametrize("details", [{}, {"failed_test_case_ids": ["UT-UNOWNED-001"]}])
def test_provider_feedback_rejects_unowned_failures_without_dispatch(
    slice_project, tmp_path, monkeypatch, details,
):
    controller, store, executor = _accepted(slice_project, tmp_path, monkeypatch)
    before = store.read()
    result = controller.run_downstream_feedback(
        handle=None, worktree_path=str(slice_project[0]),
        verify_result=VerifyResult(False, [FailureEntry(
            FailureCategory.OTHER, "unowned-note", "Missing note", details,
        )]), build_command="echelon build", delivery_context="", build_prompt="", phase="visual",
    )
    assert not result["passed"]
    assert "delivery_repair_ownership_required" in result["build_reason"]
    assert executor.calls == []
    after = store.read()
    assert after["delivery_slice_task_id"] == before["delivery_slice_task_id"]
    assert after["tokens_used"] == before["tokens_used"]
    assert after.get("delivery_slice_operation") == before.get("delivery_slice_operation")


def test_restart_replays_exact_structured_feedback_and_accounts_once(slice_project, tmp_path, monkeypatch):
    controller, store, executor = _accepted(slice_project, tmp_path, monkeypatch)
    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, 2)
        with pytest.raises(ProcessLost):
            _downstream(controller, slice_project[0])
    saved = store.read()["delivery_slice_operation"]
    assert json.loads(saved["feedback"])["context"]["phase"] == "visual"
    executor.calls.clear()
    resumed = _reconstruct(controller, store, controller._llm_provider)
    result = _build(resumed, slice_project)
    assert result["passed"] and result["tokens"] == 28, result
    assert [call[0]["step"] for call in executor.calls] == ["code_reviewer", "test_guardian"]
    assert store.read()["delivery_slice_operation"]["feedback"] == saved["feedback"]
    assert all(call[2].endswith(saved["feedback"]) for call in executor.calls)
    assert _build(resumed, slice_project)["tokens"] == 0


def test_old_pending_source_repair_blocks_without_rewriting_records(slice_project, tmp_path, monkeypatch):
    controller, store, executor = _accepted(slice_project, tmp_path, monkeypatch)
    from harness.delivery_slice_runner import DeliverySliceRunner, delivery_slice_binding, delivery_role_inputs
    from harness.delivery_slice_journal import DeliverySliceJournal

    root, spec, _ = slice_project
    legacy_feedback = "Fix source or stop after writing the harness status marker."
    operation = {
        "id": "retained-legacy-source-repair", "feedback": legacy_feedback,
        "repair_task_id": "T-001", "accounted_tokens": 0,
        "worktree_path": str(root.resolve()), "source_binding": None,
        "outer_iter": store.read().get("outer_iter", 0), "progress_applied": False,
    }

    def remember_retained_operation():
        state = store.read()
        state["delivery_slice_operation"] = operation
        store.write(state)

    # Create a genuine pre-fix-style journal with its original binding, rather
    # than corrupting a new journal or asking Ralph to admit a new legacy repair.
    with monkeypatch.context() as patch:
        _crash_after_receipt(patch, 2)
        with pytest.raises(ProcessLost):
            DeliverySliceRunner(controller._llm_provider, root).run(
                worktree=root, spec_dir=spec,
                evidence_root=controller._delivery_operation_evidence_root(),
                operation_id=operation["id"], feedback=legacy_feedback,
                repair_task_id="T-001", on_journal_ready=remember_retained_operation,
            )
    saved = store.read()
    journals = {path: path.read_bytes() for path in store.state_dir.rglob("journal.json")}
    legacy_journal = DeliverySliceJournal(
        controller._delivery_operation_evidence_root(), operation["id"],
    ).path
    retained = json.loads(journals[legacy_journal])
    assert len(retained["records"]) == 2
    assert retained["task_id"] == "T-001"
    assert retained["binding"] == delivery_slice_binding(
        worktree=root, spec_dir=spec, roles=delivery_role_inputs(root),
        allowed_task_ids=None, repair_task_id="T-001", feedback=legacy_feedback,
        implementation_target=None, declared_targets=None,
    )
    executor.calls.clear()
    result = _build(_reconstruct(controller, store, controller._llm_provider), slice_project)
    assert not result["passed"] and "reconciliation_required" in result["build_reason"]
    assert not executor.calls
    assert store.read()["delivery_slice_operation"] == saved["delivery_slice_operation"]
    assert store.read()["tokens_used"] == saved["tokens_used"]
    assert all(path.read_bytes() == before for path, before in journals.items())
