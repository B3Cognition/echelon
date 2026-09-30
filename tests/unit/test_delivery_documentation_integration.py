"""Documentation repair at Ralph's real feedback, recovery and verification boundaries."""
import shutil
from types import SimpleNamespace

import pytest

from harness.verify_result import FailureCategory, FailureEntry, VerifyResult
from tests.unit.test_delivery_controller_integration import _controller, _reconstruct, _build
from tests.unit.test_delivery_documentation import (
    documentation_project, IMPACT, review_report, ProcessLost,
)
from tests.unit.test_delivery_slice_runner import slice_project, ScriptedExecutor
from tests.unit.test_delivery_controller import _initialize_git_worktree


def _failure(*ids):
    return VerifyResult(False, [FailureEntry(FailureCategory.OTHER, name, "Repair this actual finding") for name in ids])


def _feedback(controller, root, failure=None):
    return controller._exec_feedback(None, failure or _failure("documentation-impact-report-missing"),
                                    "echelon build", "", worktree_path=str(root),
                                    prompt="You are MANAGER. Legacy routing must not reach documentation roles.")


def _setup(documentation_project, tmp_path, mode="semi", complete=False, **options):
    _, executor, paths = documentation_project(**options)
    root, spec = paths["worktree"], paths["spec_dir"]
    if complete:
        task_file = spec / "tasks.md"
        task_file.write_text(task_file.read_text().replace("- [ ] T-", "- [x] T-"))
    controller, store = _controller((root, spec, paths["evidence_root"]), tmp_path, executor, mode)
    state = store.read()
    state["target_task_ids"] = ["T-001"]
    store.write(state)
    return controller, store, executor, root, spec


@pytest.mark.parametrize("mode", ["banzai", "semi", "guided"])
@pytest.mark.parametrize("prefix", ["documentation-", "docs-", "readme-", "changelog-"])
def test_completed_tasks_route_actual_docs_failure_without_implementation_pointer(documentation_project, tmp_path, mode, prefix):
    controller, store, executor, root, spec = _setup(documentation_project, tmp_path, mode, complete=True)
    result = _feedback(controller, root, _failure(prefix + "broken"))
    assert result["passed"] and result["task_ids"] == [], result
    assert executor.steps == ["tech_writer", "docs_verifier"]
    assert "You are MANAGER" not in executor.calls[0][2]
    assert prefix + "broken" in executor.calls[0][2]
    assert store.read()["delivery_slice_operation"]["kind"] == "documentation"
    assert store.read()["delivery_slice_operation"]["progress_applied"] is True
    assert "delivery_slice_task_id" not in store.read()
    assert controller._apply_documentation_gate(VerifyResult(True), str(root)).passed
    assert (spec / "docs-verification-report.md").read_text() == review_report()


@pytest.mark.parametrize("review", [None, True, False])
def test_controlled_no_impact_requires_independent_pass(documentation_project, tmp_path, review):
    controller, _, _, root, spec = _setup(documentation_project, tmp_path)
    (spec / "documentation-impact-report.md").write_text(IMPACT)
    if review is not None:
        (spec / "docs-verification-report.md").write_text(review_report(fail=not review))
    result = controller._apply_documentation_gate(VerifyResult(True), str(root))
    assert result.passed is (review is True)
    if review is None:
        assert result.failures[0].id == "docs-verification-report-missing"


def test_docs_after_accepted_task_retains_source_repair_target_and_empty_id_exemption(documentation_project, tmp_path):
    controller, store, docs, root, spec = _setup(documentation_project, tmp_path)
    impl = ScriptedExecutor()
    controller._llm_provider = impl
    built = _build(controller, (root, spec, None))
    assert built["passed"], built
    controller._apply_build_task_progress(worktree_path=str(root), task_ids=built["task_ids"])
    # Partial delivery must not demand another completed task from docs.
    state = store.read()
    state.pop("target_task_ids")
    store.write(state)
    controller._llm_provider = docs
    # The report covers the selected inventory, including the remaining task.
    def inventory(assignment, payload, cwd):
        if assignment["step"] == "tech_writer":
            payload["report_markdown"] = IMPACT.replace("delivery_change_ids: [T-001]", "delivery_change_ids: [T-001, T-002]")
            payload["report_markdown"] = payload["report_markdown"].replace("---\n# Documentation", "  - change_id: T-002\n    disposition: not_applicable\n    reason: Internal work.\n    evidence_paths: [app.py]\n---\n# Documentation")
        else:
            payload["report_markdown"] = review_report().replace("- T-001", "- T-001\n- T-002")
    docs.script = inventory
    _initialize_git_worktree(root)
    fixed = _feedback(controller, root)
    assert fixed["passed"], fixed
    controller._enforce_completed_task_ids(fixed, str(root))
    assert fixed["passed"] and fixed["task_ids"] == []
    assert store.read()["delivery_slice_task_id"] == "T-001"
    forged = {"passed": True, "build_status": "done", "task_ids": [],
              "provider_invocation": fixed["provider_invocation"]}
    controller._enforce_completed_task_ids(forged, str(root))
    assert not forged["passed"]
    controller._llm_provider = impl
    repaired = _feedback(controller, root, _failure("test-greeting"))
    assert repaired["passed"] and repaired["task_ids"] == ["T-001"], repaired


@pytest.mark.parametrize("ids", [("test-source",), ("documentation-broken", "test-source"), ()])
def test_source_mixed_and_empty_failures_keep_implementation_route(documentation_project, tmp_path, ids):
    controller, _, _, root, spec = _setup(documentation_project, tmp_path)
    impl = ScriptedExecutor()
    controller._llm_provider = impl
    built = _build(controller, (root, spec, None))
    controller._apply_build_task_progress(worktree_path=str(root), task_ids=built["task_ids"])
    fixed = _feedback(controller, root, _failure(*ids))
    assert fixed["passed"] and fixed["task_ids"] == ["T-001"], fixed
    assert [call[0]["step"] for call in impl.calls] == ["implementer", "spec_guard", "code_reviewer", "test_guardian"] * 2


@pytest.mark.parametrize("point", ["intent", "completion", "publication", "progress"])
def test_build_restart_recovers_docs_and_only_unseen_usage(documentation_project, tmp_path, monkeypatch, point):
    from harness.delivery_slice_journal import DeliverySliceJournal
    from harness import delivery_documentation as module
    controller, store, executor, root, spec = _setup(documentation_project, tmp_path)
    original_save, original_write, original_state = DeliverySliceJournal.save, module.write_text_atomic, store.write
    _initialize_git_worktree(root)
    def save(self, data):
        original_save(self, data)
        records = data["records"]
        if len(records) == 1 and ((point == "intent" and records[0]["result"] is None) or (point == "completion" and records[0]["result"] is not None)):
            assert store.read()["delivery_slice_operation"]["kind"] == "documentation"
            raise ProcessLost()
    def write(path, text, **kwargs):
        original_write(path, text, **kwargs)
        if point == "publication" and path == spec / "documentation-impact-report.md":
            assert not store.read()["delivery_slice_operation"]["progress_applied"]
            raise ProcessLost()
    def state_write(data):
        original_state(data)
        if point == "progress" and data.get("delivery_slice_operation", {}).get("progress_applied"):
            raise ProcessLost()
    with monkeypatch.context() as patch:
        patch.setattr(DeliverySliceJournal, "save", save)
        patch.setattr(module, "write_text_atomic", write)
        patch.setattr(store, "write", state_write)
        with pytest.raises(ProcessLost):
            _feedback(controller, root)
    operation = store.read()["delivery_slice_operation"]["id"]
    resumed = _reconstruct(controller, store, executor)
    result = _build(resumed, (root, spec, None))
    assert store.read()["delivery_slice_operation"]["id"] == operation
    if point == "intent":
        assert not result["passed"] and "unknown" in result["build_reason"]
        assert executor.steps == []
    else:
        assert result["passed"] and result["task_ids"] == [], result
        assert result["tokens"] == (0 if point == "progress" else 14)
        assert executor.steps == ["tech_writer", "docs_verifier"]
        assert _build(resumed, (root, spec, None))["tokens"] == 0
        assert store.read()["tokens_used"] == 14


@pytest.mark.parametrize("rejected", [False, True])
def test_repeated_docs_feedback_cannot_reset_or_reuse_disagreed_approval(documentation_project, tmp_path, rejected):
    controller, store, executor, root, _ = _setup(documentation_project, tmp_path, always_reject=rejected)
    first = _feedback(controller, root)
    assert first["passed"] is not rejected, first
    operation = store.read()["delivery_slice_operation"]["id"]
    again = _feedback(_reconstruct(controller, store, executor), root)
    assert not again["passed"], again
    assert store.read()["delivery_slice_operation"]["id"] == operation
    assert executor.steps == ["tech_writer", "docs_verifier"] * (3 if rejected else 1)
    assert again["tokens"] == 0


@pytest.mark.parametrize("fault", ["required", "malformed", "stack"])
def test_docs_runnability_preflight_fails_closed(documentation_project, tmp_path, fault):
    controller, store, executor, root, _ = _setup(documentation_project, tmp_path)
    if fault == "required":
        controller._config.resolved_runnability = SimpleNamespace(policy="required")
    else:
        report = str(tmp_path / "missing.json")
        if fault == "stack":
            from tests.unit.test_runnability_evidence import _write_report
            from harness.product_inventory import product_evidence_fingerprint
            report = str(_write_report(tmp_path / "run", candidate_fingerprint=product_evidence_fingerprint(root), contract_hash="").path)
        state = store.read()
        state["user_runnability"] = {"status": "runnable", "report": report}
        store.write(state)
    result = _feedback(controller, root)
    assert not result["passed"] and "runnability" in result["build_reason"], result
    assert executor.steps == []


def test_external_source_binding_survives_docs_publication_and_rejects_source_change(documentation_project, tmp_path):
    controller, store, executor, root, spec = _setup(documentation_project, tmp_path)
    source = tmp_path / "source"
    shutil.copytree(root, source)
    controller._gitops.base_dir = str(source)
    result = _feedback(controller, root)
    assert result["passed"], result
    assert _build(_reconstruct(controller, store, executor), (root, spec, None))["passed"]
    (source / "specs/001-slice/spec.md").write_text("Changed requirements")
    blocked = _build(_reconstruct(controller, store, executor), (root, spec, None))
    assert not blocked["passed"] and "reconciliation" in blocked["build_reason"]
    assert executor.steps == ["tech_writer", "docs_verifier"]


def test_inner_loop_repairs_docs_and_validates_independent_report(documentation_project, tmp_path):
    controller, store, executor, root, _ = _setup(documentation_project, tmp_path, complete=True)
    _initialize_git_worktree(root)
    controller._config.verify_command = "python -m unittest"
    controller._fulfillment_runner = None
    initial = controller._apply_documentation_gate(VerifyResult(True), str(root))
    assert not initial.passed
    result = controller._run_inner_loop(None, initial, 1, 2, 0, None, store.read(),
                                       "echelon build", "", worktree_path=str(root), build_prompt="build")
    assert result["converged"], result
    assert result["tokens_used"] == 14
    assert executor.steps == ["tech_writer", "docs_verifier"]


def test_pending_docs_rejects_changed_failure_evidence(documentation_project, tmp_path):
    controller, store, executor, root, _ = _setup(documentation_project, tmp_path, always_reject=True)
    assert not _feedback(controller, root)["passed"]
    operation = store.read()["delivery_slice_operation"]["id"]
    result = _feedback(controller, root, _failure("readme-new-finding"))
    assert not result["passed"] and "reconciliation" in result["build_reason"], result
    assert store.read()["delivery_slice_operation"]["id"] == operation
    assert len(executor.calls) == 6


@pytest.mark.parametrize("fault", ["kind", "missing_journal", "source_repair"])
def test_unresolved_docs_operation_cannot_be_replaced(documentation_project, tmp_path, fault):
    controller, store, executor, root, spec = _setup(documentation_project, tmp_path, always_reject=True)
    assert not _feedback(controller, root)["passed"]
    operation = store.read()["delivery_slice_operation"]["id"]
    if fault == "kind":
        state = store.read()
        state["delivery_slice_operation"]["kind"] = "unknown"
        store.write(state)
    elif fault == "missing_journal":
        journal = next(store.state_dir.rglob("journal.json"))
        journal.rename(journal.with_name("quarantined.json"))
    result = (_feedback(controller, root, _failure("test-source")) if fault == "source_repair"
              else _build(_reconstruct(controller, store, executor), (root, spec, None)))
    assert not result["passed"]
    assert store.read()["delivery_slice_operation"]["id"] == operation
    assert len(executor.calls) == 6


def test_next_outer_iteration_advances_completed_docs_to_next_task(documentation_project, tmp_path):
    controller, store, executor, root, spec = _setup(documentation_project, tmp_path)
    assert _feedback(controller, root)["passed"]
    state = store.read()
    state["outer_iter"] += 1
    store.write(state)
    impl = ScriptedExecutor()
    result = _build(_reconstruct(controller, store, impl), (root, spec, None))
    assert result["passed"] and result["task_ids"] == ["T-001"], result
    assert [call[0]["step"] for call in impl.calls] == ["implementer", "spec_guard", "code_reviewer", "test_guardian"]


def test_external_spec_receives_reports_without_copying_into_candidate(documentation_project, tmp_path):
    controller, store, executor, root, spec = _setup(documentation_project, tmp_path)
    external = tmp_path / "external-spec"
    shutil.move(spec, external)
    executor.spec = external
    state = store.read()
    state.update(target_path=str(root), spec_dir=str(external))
    store.write(state)
    result = _feedback(controller, root)
    assert result["passed"], result
    assert not spec.exists()
    assert (external / "docs-verification-report.md").read_text() == review_report()
    assert controller._apply_documentation_gate(VerifyResult(True), str(root)).passed
    assert _build(_reconstruct(controller, store, executor), (root, external, None))["passed"]
    assert len(executor.calls) == 2


def test_controlled_gate_preserves_reviewed_report_bytes_with_runnability(documentation_project, tmp_path):
    from tests.unit.test_runnability_evidence import _write_report
    from harness.product_inventory import product_evidence_fingerprint
    controller, store, _, root, spec = _setup(documentation_project, tmp_path)
    (spec / "documentation-impact-report.md").write_text(IMPACT)
    reviewed = review_report(True) + "\nIndependent semantic finding must survive.\n"
    report = spec / "docs-verification-report.md"
    report.write_text(reviewed)
    ref = _write_report(tmp_path / "runnability", candidate_fingerprint=product_evidence_fingerprint(root),
                        contract_hash="", stack_hash="")
    state = store.read()
    state["user_runnability"] = {"status": "runnable", "report": str(ref.path)}
    store.write(state)
    result = controller._apply_documentation_gate(VerifyResult(True), str(root))
    assert not result.passed
    assert report.read_text() == reviewed


def test_controlled_gate_does_not_author_no_impact_report(documentation_project, tmp_path):
    controller, _, _, root, spec = _setup(documentation_project, tmp_path, complete=True)
    _initialize_git_worktree(root)
    result = controller._apply_documentation_gate(VerifyResult(True), str(root), changed_files=[])
    assert not result.passed and result.failures[0].id == "documentation-impact-report-missing"
    assert not (spec / "documentation-impact-report.md").exists()


@pytest.mark.parametrize("used,dispatches", [(95, 0), (88, 1)])
def test_documentation_downstream_feedback_respects_current_budget(documentation_project, tmp_path, used, dispatches):
    controller, store, executor, root, spec = _setup(documentation_project, tmp_path)
    controller._controlled_slice_budget = 95
    state = store.read()
    state.update(token_budget=100, tokens_used=used)
    store.write(state)
    result = controller.run_downstream_feedback(
        handle=None, worktree_path=str(root), verify_result=_failure("docs-missing"),
        build_command="echelon build", delivery_context="", build_prompt="build", phase="visual")
    assert not result["passed"] and result["build_reason"] == "delivery_documentation_budget_exhausted", result
    assert len(executor.calls) == dispatches
    assert store.read()["tokens_used"] == used + dispatches * 7
    resumed = _build(_reconstruct(controller, store, executor), (root, spec, None))
    assert not resumed["passed"] and resumed["tokens"] == 0
    assert len(executor.calls) == dispatches


def test_runnability_receipt_survives_recovery_of_writer_owned_edits(documentation_project, tmp_path, monkeypatch):
    from harness.delivery_slice_journal import DeliverySliceJournal
    from tests.unit.test_delivery_documentation_checkpoint import _runnable_project
    controller, store, executor, sandbox, root, spec, initial, ref = _runnable_project(documentation_project, tmp_path)
    original = DeliverySliceJournal.save
    def save(self, data):
        original(self, data)
        if len(data["records"]) == 1 and data["records"][0]["result"] is not None:
            raise ProcessLost()
    with monkeypatch.context() as patch:
        patch.setattr(DeliverySliceJournal, "save", save)
        with pytest.raises(ProcessLost):
            _feedback(controller, root, initial)
    result = _build(_reconstruct(controller, store, executor), (root, spec, None))
    assert result["passed"], result
    assert executor.steps == ["tech_writer", "docs_verifier"]
    assert result["tokens"] == 14 and store.read()["tokens_used"] == 14
    assert len(sandbox.created) == 2  # Initial receipt and the recovered post-author checkpoint.
