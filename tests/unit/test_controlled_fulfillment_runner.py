"""Real runner/controller/publication acceptance; only external processes are scripted."""
import json
import subprocess

import pytest

from harness.fulfillment_runner import FulfillmentRunner
from kernel.fulfillment import read_fulfillment_metadata, fulfillment_table_ids
from tests.unit.test_controlled_fulfillment import (
    preparation_context, scripted_graph_tools, installed_roles, SemanticExecutor,
)


@pytest.fixture
def runner_context(preparation_context):
    context = preparation_context
    for args in (("init",), ("add", "app.py"),
                 ("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial")):
        subprocess.run(["git", *args], cwd=context.project_root, check=True, capture_output=True)
    return context


def refresh(context, executor, **kwargs):
    defaults = dict(spec_dir=context.spec_dir, orchestration_root=context.workspace_root,
                    source_id=context.source_id, source_root=context.source_root,
                    verify_run_dir=context.verify_run_dir)
    defaults.update(kwargs)
    return FulfillmentRunner(executor, controlled=True).refresh(str(context.project_root), context.spec_id, **defaults)


def test_full_publishes_completes_and_reuses_exact_operation(runner_context):
    context = runner_context
    executor = SemanticExecutor()
    first = refresh(context, executor)
    assert first.ok, first.reason
    assert first.token_usage == 7
    assert first.operation_id
    report = context.spec_dir / "fulfillment-report.md"
    original = report.read_bytes()
    assert fulfillment_table_ids(report.read_text()) >= {"FR-000001", "FR-002", "FR-1000000"}
    assert read_fulfillment_metadata(report)["verify_scope"] == "full"
    assert json.loads((context.verify_run_dir / "state.json").read_text())["status"] == "complete"
    assert (context.spec_dir / "verified-fulfillment-ledger.json").is_file()
    second = refresh(context, executor, token_budget=0)
    assert second.ok, second.reason
    assert second.used_cache
    assert second.token_usage == 7
    assert second.operation_id == first.operation_id
    assert executor.dispatch_count == 1
    assert report.read_bytes() == original


def test_failed_semantics_keeps_previous_canonical_outputs(runner_context):
    context = runner_context
    report = context.spec_dir / "fulfillment-report.md"
    report.write_text("previous report\n")
    executor = SemanticExecutor(bad="malformed")
    result = refresh(context, executor)
    assert not result.ok
    assert result.token_usage == 7
    assert report.read_text() == "previous report\n"
    again = refresh(context, executor)
    assert not again.ok
    assert again.token_usage == 7
    assert executor.dispatch_count == 1


def test_scoped_without_base_falls_back_to_controlled_full(runner_context):
    executor = SemanticExecutor()
    result = refresh(runner_context, executor, scope="scoped", completed_task_ids=["T-000001"])
    assert result.ok, result.reason
    assert result.scope == "full"
    assert executor.dispatches[0]["assignment"]["assigned_ids"] == ["FR-000001", "FR-002", "FR-1000000"]


def test_changed_source_never_resets_explicit_run(runner_context):
    executor = SemanticExecutor()
    assert refresh(runner_context, executor).ok
    state = (runner_context.verify_run_dir / "state.json").read_bytes()
    (runner_context.project_root / "app.py").write_text("changed\n")
    result = refresh(runner_context, executor)
    assert not result.ok
    assert executor.dispatch_count == 1
    assert (runner_context.verify_run_dir / "state.json").read_bytes() == state


@pytest.mark.parametrize("crash_at", ["report", "gaps", "completion"])
def test_interrupted_publication_resumes_without_new_calls(runner_context, monkeypatch, crash_at):
    import harness.fulfillment_recovery as recovery
    import harness.controlled_fulfillment_refresh as controlled
    class Crash(BaseException):
        pass
    original_write = recovery.write_text_atomic
    original_complete = controlled.complete_verify_spec_run
    def write(path, *args, **kwargs):
        original_write(path, *args, **kwargs)
        if path.name == f"fulfillment-{crash_at}.md":
            raise Crash()
    def complete(*args, **kwargs):
        original_complete(*args, **kwargs)
        if crash_at == "completion":
            raise Crash()
    monkeypatch.setattr(recovery, "write_text_atomic", write)
    monkeypatch.setattr(controlled, "complete_verify_spec_run", complete)
    executor = SemanticExecutor()
    with pytest.raises(Crash):
        refresh(runner_context, executor)
    monkeypatch.setattr(recovery, "write_text_atomic", original_write)
    monkeypatch.setattr(controlled, "complete_verify_spec_run", original_complete)
    result = refresh(runner_context, executor, token_budget=0)
    assert result.ok, result.reason
    assert result.token_usage == 7
    assert executor.dispatch_count == 1


@pytest.mark.parametrize("dry_run", [False, True])
def test_requested_reconciliation_uses_existing_host_helpers(runner_context, dry_run):
    state_path = runner_context.verify_run_dir / "state.json"
    state = json.loads(state_path.read_text())
    state.update(reconcile=True, dry_run=dry_run)
    state_path.write_text(json.dumps(state))
    executor = SemanticExecutor()
    result = refresh(runner_context, executor, reconcile=True, dry_run=dry_run)
    assert result.ok, result.reason
    state = json.loads(state_path.read_text())
    assert state["progress_reconciliation"] == ("dry_run" if dry_run else "applied")
    assert state["status"] == "complete"
    result = refresh(runner_context, executor, reconcile=True, dry_run=dry_run)
    assert result.ok, result.reason
    assert executor.dispatch_count == 1


def seed_controlled_report(context, *, legacy=False, unresolved=False):
    from harness import fulfillment_runner as shared
    from harness.controlled_fulfillment_refresh import CONTRACT, _semantic_configuration, _report_body_hash
    from kernel.fulfillment import stamp_fulfillment_report
    report = context.spec_dir / "fulfillment-report.md"
    report.write_text("# Fulfillment Report\n\n| ID | Status | Evidence |\n| --- | --- | --- |\n" +
        "| FR-000001 | IMPLEMENTED | greeting accepted |\n" +
        f"| FR-002 | {'MISSING' if unresolved else 'IMPLEMENTED'} | legacy preserved |\n" +
        "| FR-1000000 | IMPLEMENTED | large identity preserved |\n")
    spec_hash = shared._spec_input_hash(context.spec_dir)
    product_hash = shared._implementation_input_hash(context.project_root)
    _, profile = _semantic_configuration(SemanticExecutor(), context.workspace_root)
    stamp_fulfillment_report(report, spec_id=context.spec_id, commit=shared._current_git_commit(context.project_root),
        extra_metadata=dict(verify_scope="full", fulfillment_contract=CONTRACT,
                            fulfillment_body_sha256=_report_body_hash(report),
                            fulfillment_semantic_profile=profile,
                            spec_input_hash=spec_hash, implementation_input_hash=product_hash))
    shared._write_verified_fulfillment_ledger(context.project_root, spec_dir=context.spec_dir,
        report=report, spec_input_hash=spec_hash, implementation_input_hash=product_hash,
        contract_version=shared.FULFILLMENT_VERIFIER_VERSION if legacy else f"{CONTRACT}:{profile}")
    return report


def test_scoped_merge_preserves_unaffected_rows_and_base_provenance(runner_context):
    from kernel.fulfillment import read_fulfillment_metadata
    report = seed_controlled_report(runner_context)
    original_commit = read_fulfillment_metadata(report)["verified_commit"]
    executor = SemanticExecutor()
    result = refresh(runner_context, executor, verify_run_dir=None,
                     scope="scoped", completed_task_ids=["T-000001"])
    assert result.ok, result.reason
    assert result.scope == "scoped"
    assert executor.dispatches[0]["assignment"]["assigned_ids"] == ["FR-000001"]
    assert "| FR-002 | IMPLEMENTED | legacy preserved |" in report.read_text()
    assert "| FR-1000000 | IMPLEMENTED | large identity preserved |" in report.read_text()
    assert read_fulfillment_metadata(report)["base_full_verify_commit"] == original_commit


def test_legacy_ledger_is_not_reused_as_controlled_evidence(runner_context):
    seed_controlled_report(runner_context, legacy=True)
    executor = SemanticExecutor()
    result = refresh(runner_context, executor, verify_run_dir=None,
                     scope="scoped", completed_task_ids=["T-000001"])
    assert result.ok, result.reason
    assert set(executor.dispatches[0]["assignment"]["assigned_ids"]) == {"FR-000001", "FR-002", "FR-1000000"}


def test_scoped_no_impact_uses_current_controlled_ledger(runner_context):
    report = seed_controlled_report(runner_context)
    before = report.read_bytes()
    executor = SemanticExecutor()
    result = refresh(runner_context, executor, verify_run_dir=None, scope="scoped")
    assert result.ok and result.used_cache, result.reason
    assert executor.dispatch_count == 0
    assert report.read_bytes() == before


def test_automatically_selected_run_is_reused_not_initialized_again(runner_context):
    executor = SemanticExecutor()
    first = refresh(runner_context, executor, verify_run_dir=None)
    second = refresh(runner_context, executor, verify_run_dir=None)
    assert first.ok and second.ok, second.reason
    assert first.operation_id == second.operation_id
    assert second.used_cache
    assert executor.dispatch_count == 1


def test_scoped_never_assigns_host_task_progress_to_mapper(runner_context):
    first = refresh(runner_context, SemanticExecutor())
    assert first.ok
    executor = SemanticExecutor()
    result = refresh(runner_context, executor, verify_run_dir=None,
                     scope="scoped", completed_task_ids=["T-000001"])
    assert result.ok, result.reason
    assert "TASK-PROGRESS" not in executor.dispatches[0]["assignment"]["assigned_ids"]


@pytest.mark.parametrize("alias", ["symlink", "hardlink"])
def test_unsafe_ledger_destination_is_not_overwritten(runner_context, tmp_path, alias):
    import os
    target = tmp_path / "outside.json"
    target.write_text("private external data")
    ledger = runner_context.spec_dir / "verified-fulfillment-ledger.json"
    if alias == "symlink":
        ledger.symlink_to(target)
    else:
        os.link(target, ledger)
    result = refresh(runner_context, SemanticExecutor())
    assert not result.ok
    assert target.read_text() == "private external data"


def test_canonical_edit_during_semantics_blocks_publication(runner_context):
    report = runner_context.spec_dir / "fulfillment-report.md"
    report.write_text("before")
    class EditingExecutor(SemanticExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            report.write_text("external edit")
            return super().run_inspection_turn(*args, **kwargs)
    result = refresh(runner_context, EditingExecutor())
    assert not result.ok
    assert report.read_text() == "external edit"


@pytest.mark.parametrize("missing", ["controlled-refresh.json", "controlled-fulfillment.json"])
def test_lost_runner_receipt_never_restarts(runner_context, missing):
    executor = SemanticExecutor()
    assert refresh(runner_context, executor).ok
    (runner_context.verify_run_dir / missing).unlink()
    result = refresh(runner_context, executor)
    assert not result.ok
    assert executor.dispatch_count == 1


@pytest.mark.parametrize("failure", ["role", "provider"])
def test_runner_admission_keeps_cumulative_usage(runner_context, failure):
    executor = SemanticExecutor()
    assert refresh(runner_context, executor).ok
    if failure == "provider":
        executor.supports_inspection_turn = False
    else:
        (runner_context.workspace_root / ".echelon/prosaic/subagents/echelon.fulfillment-mapper.md").unlink()
    result = refresh(runner_context, executor)
    assert not result.ok
    assert result.token_usage == 7


@pytest.mark.parametrize("change", ["source", "report", "reconcile"])
def test_no_impact_cannot_bypass_admission_or_reconciliation(runner_context, change):
    report = seed_controlled_report(runner_context)
    kwargs = dict(verify_run_dir=None, scope="scoped")
    if change == "source":
        kwargs["source_id"] = "unrelated"
    elif change == "report":
        report.write_text(report.read_text().replace("FR-002", "FR-999999"))
    else:
        kwargs["reconcile"] = True
    executor = SemanticExecutor()
    result = refresh(runner_context, executor, **kwargs)
    if change == "source":
        assert not result.ok
        assert executor.dispatch_count == 0
    else:
        assert not result.used_cache
        assert result.ok, result.reason
        if change == "report":
            assert "FR-999999" not in report.read_text()
        else:
            from pathlib import Path
            state = json.loads((Path(result.operation_id) / "state.json").read_text())
            assert state["progress_reconciliation"] == "applied"


@pytest.mark.parametrize("field,value", [("spec_id", "different"), ("scoped_ids", ["FR-002"]),
    ("project_root", "/wrong"), ("verify_scope", "scoped"), ("reconcile", True)])
def test_completed_run_identity_cannot_drift(runner_context, field, value):
    executor = SemanticExecutor()
    assert refresh(runner_context, executor).ok
    path = runner_context.verify_run_dir / "state.json"
    state = json.loads(path.read_text())
    state[field] = value
    path.write_text(json.dumps(state))
    result = refresh(runner_context, executor)
    assert not result.ok
    assert result.token_usage == 7
    assert executor.dispatch_count == 1


def test_automatic_reconciliation_keeps_operation_after_changing_tasks(runner_context):
    from dataclasses import replace
    (runner_context.spec_dir / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "|---|---|---|---|---|---|---|\n"
        "| FR-000001 | TC-000001 | unit | automated | automated | tests/test_app.py | none |\n")
    class ImplementedExecutor(SemanticExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            payload = json.loads(result.stdout)
            if payload["step"] == "judge" and payload["action"] == "final":
                payload["rows"][0]["status"] = "IMPLEMENTED"
                return replace(result, stdout=json.dumps(payload))
            return result
    executor = ImplementedExecutor(inspect_source=True)
    first = refresh(runner_context, executor, verify_run_dir=None, reconcile=True)
    assert first.ok, first.reason
    assert "DONE" in (runner_context.spec_dir / "tasks.md").read_text()
    second = refresh(runner_context, executor, verify_run_dir=None, reconcile=True)
    assert second.ok, second.reason
    assert second.operation_id == first.operation_id
    assert executor.dispatch_count == 3


@pytest.mark.parametrize("change", ["status", "profile", "duplicate", "evidence"])
def test_no_impact_requires_matching_report_and_semantic_profile(runner_context, change):
    report = seed_controlled_report(runner_context)
    if change == "status":
        report.write_text(report.read_text().replace("FR-002 | IMPLEMENTED", "FR-002 | MISSING"))
    elif change == "duplicate":
        report.write_text(report.read_text() + "| FR-002 | IMPLEMENTED | duplicated |\n")
    elif change == "evidence":
        report.write_text(report.read_text().replace("greeting accepted", "implementation absent; old evidence was mistaken"))
    else:
        role = runner_context.workspace_root / ".echelon/prosaic/subagents/echelon.fulfillment-mapper.md"
        role.write_text(role.read_text() + "\nUpdated semantic rules.\n")
    executor = SemanticExecutor()
    result = refresh(runner_context, executor, verify_run_dir=None, scope="scoped")
    assert result.ok, result.reason
    assert not result.used_cache
    assert executor.dispatch_count > 0


def test_no_impact_explicit_run_cannot_bypass_state_validation(runner_context):
    seed_controlled_report(runner_context)
    path = runner_context.verify_run_dir / "state.json"
    state = json.loads(path.read_text())
    state.update(spec_id="different", status="blocked")
    path.write_text(json.dumps(state))
    executor = SemanticExecutor()
    result = refresh(runner_context, executor, scope="scoped")
    assert not result.ok
    assert executor.dispatch_count == 0
