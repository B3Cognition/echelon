"""Controlled fulfillment through real Ralph policy, runner and provider facades."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from harness.verify_result import VerifyResult
from tests.unit.test_controlled_fulfillment_runner import (
    runner_context, preparation_context, scripted_graph_tools, installed_roles, SemanticExecutor,
)
from tests.unit.test_delivery_controller_integration import _controller, _reconstruct


def setup_delivery(context, tmp_path, executor, mode="semi", *, enabled=True):
    controller, store = _controller((context.project_root, context.spec_dir, None), tmp_path, executor, mode)
    controller._config.llm.features["delivery_gate_controller"] = enabled
    controller._config.fulfillment.refresh_policy = "every_slice"
    state = store.read()
    state.update(workspace_root=str(context.workspace_root), source_id=context.source_id,
                 source_root=str(context.source_root), target_repo=context.source_id,
                 tokens_used=0, token_budget=1000)
    store.write(state)
    controller._write_delivery_containment_policy(worktree_path=str(context.project_root),
        workspace_root=context.workspace_root, workspace_git_role="orchestration",
        source_root=context.source_root, source_id=context.source_id, source_git_role="source",
        spec_dir=context.spec_dir, allowed_context_roots=[], forbidden_source_roots=[])
    return controller, store


@pytest.mark.parametrize("mode", ["banzai", "semi", "guided"])
def test_existing_opt_in_runs_full_fulfillment_and_accounts_once(runner_context, tmp_path, mode):
    executor = SemanticExecutor()
    controller, store = setup_delivery(runner_context, tmp_path, executor, mode)
    first = controller._refresh_fulfillment_report(VerifyResult(True), str(runner_context.project_root))
    assert first.passed, first.failures
    assert first.token_usage == 7
    assert store.read()["tokens_used"] == 7
    resumed = _reconstruct(controller, store, executor)
    second = resumed._refresh_fulfillment_report(VerifyResult(True), str(runner_context.project_root))
    assert second.passed, second.failures
    assert second.token_usage == 0
    assert store.read()["tokens_used"] == 7
    assert executor.dispatch_count == 1


def test_feature_off_keeps_legacy_runner(runner_context, tmp_path):
    from harness.fulfillment_runner import FulfillmentRunner
    controller, _ = setup_delivery(runner_context, tmp_path, SemanticExecutor())
    controller._config.llm.features["delivery_gate_controller"] = False
    # Constructor selection, not a mid-run mode switch.
    controller = _reconstruct(controller, controller._state_store, controller._llm_provider)
    assert isinstance(controller._fulfillment_runner, FulfillmentRunner)
    assert controller._fulfillment_runner._controlled is False


@pytest.mark.parametrize("point", ["before_accounting", "after_accounting"])
def test_restart_between_completion_and_accounting_never_double_charges(runner_context, tmp_path, monkeypatch, point):
    class Crash(BaseException):
        pass
    executor = SemanticExecutor()
    controller, store = setup_delivery(runner_context, tmp_path, executor)
    original = store.write
    def write(state):
        charged = state.get("tokens_used") == 7
        if charged and point == "before_accounting":
            raise Crash()
        original(state)
        if charged and point == "after_accounting":
            raise Crash()
    with monkeypatch.context() as patch:
        patch.setattr(store, "write", write)
        with pytest.raises(Crash):
            controller._refresh_fulfillment_report(VerifyResult(True), str(runner_context.project_root))
    resumed = _reconstruct(controller, store, executor)
    result = resumed._refresh_fulfillment_report(VerifyResult(True), str(runner_context.project_root))
    assert result.passed, result.failures
    assert result.token_usage == (7 if point == "before_accounting" else 0)
    assert store.read()["tokens_used"] == 7
    assert executor.dispatch_count == 1


@pytest.mark.parametrize("missing", ["state.json", "spec.md"])
def test_lost_admission_input_after_completion_keeps_unaccounted_usage(runner_context, tmp_path, monkeypatch, missing):
    class Crash(BaseException):
        pass
    executor = SemanticExecutor()
    controller, store = setup_delivery(runner_context, tmp_path, executor)
    with monkeypatch.context() as patch:
        def crash(*args):
            raise Crash()
        patch.setattr(controller, "_account_fulfillment_usage", crash)
        with pytest.raises(Crash):
            controller._refresh_fulfillment_report(VerifyResult(True), str(runner_context.project_root))
    selected = Path(store.read()["fulfillment_operation"]["id"])
    ((selected if missing == "state.json" else runner_context.spec_dir) / missing).unlink()
    result = _reconstruct(controller, store, executor)._refresh_fulfillment_report(
        VerifyResult(True), str(runner_context.project_root))
    assert not result.passed
    assert result.token_usage == 7
    assert store.read()["tokens_used"] == 7
    assert executor.dispatch_count == 1


@pytest.mark.parametrize("usage", [7, None])
def test_failed_call_usage_is_durable_and_unknown_is_explicit(runner_context, tmp_path, usage):
    executor = SemanticExecutor(bad="provider", usage=usage)
    controller, store = setup_delivery(runner_context, tmp_path, executor)
    first = controller._refresh_fulfillment_report(VerifyResult(True), str(runner_context.project_root))
    assert not first.passed
    assert first.token_usage == (usage or 0)
    second = _reconstruct(controller, store, executor)._refresh_fulfillment_report(VerifyResult(True), str(runner_context.project_root))
    assert not second.passed
    assert second.token_usage == 0
    assert executor.dispatch_count == 1
    if usage is None:
        assert store.read()["fulfillment_usage_unknown"] is True
    else:
        assert store.read()["tokens_used"] == 7


def test_exhausted_remaining_budget_prevents_dispatch(runner_context, tmp_path):
    executor = SemanticExecutor()
    controller, store = setup_delivery(runner_context, tmp_path, executor)
    state = store.read()
    state.update(tokens_used=950, token_budget=1000)
    store.write(state)
    result = controller._refresh_fulfillment_report(VerifyResult(True), str(runner_context.project_root))
    assert not result.passed
    assert executor.dispatch_count == 0


@pytest.mark.parametrize("fault", ["missing", "wrong_source"])
def test_containment_is_required_before_fulfillment_dispatch(runner_context, tmp_path, fault):
    executor = SemanticExecutor()
    controller, store = setup_delivery(runner_context, tmp_path, executor)
    policy = store.state_dir / "delivery-containment-policy.json"
    if fault == "missing":
        policy.unlink()
    else:
        value = json.loads(policy.read_text())
        value["source_id"] = "other"
        policy.write_text(json.dumps(value))
    result = controller._refresh_fulfillment_report(VerifyResult(True), str(runner_context.project_root))
    assert not result.passed
    assert executor.dispatch_count == 0


def test_scoped_no_impact_does_not_leave_uninitialized_pending_operation(runner_context, tmp_path):
    from tests.unit.test_controlled_fulfillment_runner import seed_controlled_report
    seed_controlled_report(runner_context)
    executor = SemanticExecutor()
    controller, store = setup_delivery(runner_context, tmp_path, executor)
    controller._config.fulfillment.refresh_policy = "scoped"
    state = store.read()
    state["build"] = {"total_tasks": 2, "completed_tasks": 1}
    store.write(state)
    first = controller._refresh_fulfillment_report(VerifyResult(True), str(runner_context.project_root))
    assert first.failures[0].id == "fulfillment-refresh-deferred"
    assert "fulfillment_operation" not in store.read()
    second = controller._refresh_fulfillment_report(VerifyResult(True), str(runner_context.project_root))
    assert second.failures[0].id == "fulfillment-refresh-deferred"
    assert executor.dispatch_count == 0


@pytest.mark.parametrize("mode", ["banzai", "semi", "guided"])
def test_actual_post_verification_gates_keep_nonpassing_fulfillment_blocked(runner_context, tmp_path, mode):
    executor = SemanticExecutor()
    controller, store = setup_delivery(runner_context, tmp_path, executor, mode)
    result = controller._apply_post_verify_gates(VerifyResult(True, token_usage=2), str(runner_context.project_root))
    assert not result.passed
    assert result.failures[0].id == "fulfillment-gaps"
    assert result.token_usage == 9
    assert store.read()["tokens_used"] == 7
    again = _reconstruct(controller, store, executor)._apply_post_verify_gates(
        VerifyResult(True, token_usage=2), str(runner_context.project_root))
    assert not again.passed
    assert again.failures[0].id == "fulfillment-gaps"
    assert again.token_usage == 2
    assert executor.dispatch_count == 1


def test_banzai_milestone_deferral_does_not_dispatch(runner_context, tmp_path):
    executor = SemanticExecutor()
    controller, store = setup_delivery(runner_context, tmp_path, executor, "banzai")
    controller._config.fulfillment.refresh_policy = "milestone"
    state = store.read()
    state["build"] = {"total_tasks": 2, "completed_tasks": 1}
    store.write(state)
    result = controller._refresh_fulfillment_report(VerifyResult(True), str(runner_context.project_root))
    assert result.failures[0].id == "fulfillment-refresh-deferred"
    assert executor.dispatch_count == 0


def test_scoped_target_refresh_preserves_target_policy_and_charges(runner_context, tmp_path):
    from tests.unit.test_controlled_fulfillment_runner import seed_controlled_report
    seed_controlled_report(runner_context)
    executor = SemanticExecutor()
    controller, store = setup_delivery(runner_context, tmp_path, executor)
    state = store.read()
    state.update(target_task_ids=["T-000001"], declared_targets=["api", "web"],
                 build={"total_tasks": 2, "completed_tasks": 1})
    store.write(state)
    result = controller._refresh_fulfillment_report(VerifyResult(True), str(runner_context.project_root),
                                                  completed_task_ids=["T-000001"])
    assert result.passed, result.failures
    assert result.token_usage == 7
    assert executor.dispatches[0]["assignment"]["assigned_ids"] == ["FR-000001"]
    gated = controller._apply_fulfillment_gate(result, str(runner_context.project_root))
    assert not gated.passed
    assert gated.failures[0].id == "fulfillment-gaps"


def test_verified_checkpoint_does_not_relabel_controlled_ledger_as_legacy(runner_context, tmp_path):
    from harness.coordinator import StrategyCoordinator
    from harness.delivery_results import ImplementationResult
    from harness.fulfillment_runner import _current_git_commit
    from harness.verification_evidence import write_verification_receipt, VerificationStage
    from harness.product_inventory import product_evidence_fingerprint
    from harness.verified_fulfillment_ledger import read_verified_ledger
    context = runner_context
    executor = SemanticExecutor()
    controller, store = setup_delivery(context, tmp_path, executor)
    fingerprint = product_evidence_fingerprint(context.project_root)
    ref = write_verification_receipt(evidence_dir=tmp_path / "receipts", spec_id=context.spec_id,
        strategy_id="default", build_id="test-run", candidate_commit=_current_git_commit(context.project_root),
        fingerprint_before=fingerprint, fingerprint_after=fingerprint, verifier_source="configured",
        stages=[VerificationStage(name="verify", command=("python", "-m", "pytest"), exit_code=0,
            duration_ms=1, stdout=b"passed", stderr=b"")], attempt_sequence=1, sensitive_environment={})
    result = controller._refresh_fulfillment_report(VerifyResult(True, verification_evidence=ref.as_mapping()),
                                                  str(context.project_root))
    assert result.passed, result.failures
    implementation = ImplementationResult("verified", "converged", 1, 0, None, 7, result)
    coordinator = StrategyCoordinator(provider=controller._provider, gitops=controller._gitops,
        config=controller._config, base_dir=str(context.workspace_root), orchestration_root=context.workspace_root)
    updates = coordinator._verified_evidence_updates(spec_id=context.spec_id, implementation=implementation,
        worktree_path=context.project_root, verified_commit=_current_git_commit(context.project_root))
    ledger = read_verified_ledger(context.spec_dir / "verified-fulfillment-ledger.json")
    assert updates["verified_contract_hash"] == ledger.rows[0].contract_hash


@pytest.mark.parametrize("mode", ["banzai", "semi", "guided"])
@pytest.mark.parametrize("passing", [True, False])
def test_completed_review_batch_reaches_real_verification_and_durable_effects(
    runner_context, tmp_path, monkeypatch, mode, passing,
):
    from dataclasses import replace
    import yaml
    from harness.coordinator import StrategyCoordinator
    from harness.review_loop import ReviewLoopController
    from harness.review_artifacts import ReviewArtifactPublisher
    from tests.unit.test_review_artifacts import _stage_one_group
    from tests.unit.test_delivery_documentation import review_report
    context = runner_context
    class ReviewedExecutor(SemanticExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            payload = json.loads(result.stdout)
            if payload["action"] == "final":
                for row in payload["rows"]:
                    if payload["step"] == "mapper":
                        row["verified_implementation_evidence"] = "worktree:app.py:1"
                    else:
                        row["status"] = "IMPLEMENTED" if passing else "MISSING"
                return replace(result, stdout=json.dumps(payload))
            return result
    executor = ReviewedExecutor(inspect_source=True)
    controller, store = setup_delivery(context, tmp_path, executor, mode)
    controller._config.verify_command = "python -m pytest"
    review = ReviewLoopController(controller._gitops, controller._config, "001", "default",
        base_dir=str(context.workspace_root), build_id="review-acceptance", spec_dir=context.spec_dir)
    tasks = context.spec_dir / "tasks.md"
    tasks.write_text(tasks.read_text().replace("- [ ]", "- [x]"))
    with ReviewArtifactPublisher(context.spec_dir, review._state_file.parent, "default") as publisher:
        allocation = _stage_one_group(publisher)
        append = allocation.attempt_dir / "tasks-append.md"
        append.write_text(append.read_text().replace("req=UNMAPPED", "req=FR-000001"))
        batch = publisher.accept_manifest(allocation.status_file)
    # Start at a completed repair batch, the explicit acceptance boundary. The
    # provider-owned verifier below is scripted; gates and publication are real.
    all_task_ids = ["T-000001", *batch.task_ids]
    pending = dict(attempt_id=batch.attempt_id, task_ids=list(batch.task_ids),
        artifact_paths=[str(path) for path in batch.artifact_paths], phase1_verified=False)
    state = store.read()
    state.update(pending_review_reentry=pending, target_task_ids=list(batch.task_ids), declared_targets=["api"])
    store.write(state)
    assert controller._apply_build_task_progress(worktree_path=str(context.project_root),
        task_ids=list(batch.task_ids)) == list(batch.task_ids)
    (context.spec_dir / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "|---|---|---|---|---|---|---|\n" + "".join(
            f"| {item} | TC-{index:06d} | unit | automated | automated | tests/test_app.py | none |\n"
            for index, item in enumerate(("FR-000001", "FR-002", "FR-1000000"), 1)))
    impact = dict(schema_version=2, docs_required=False, readme_updated=False, changelog_updated=False,
        changelog_format="not_required", not_applicable_reason="Internal test maintenance.",
        delivery_change_ids=all_task_ids, documented_changes=[dict(change_id=item, disposition="not_applicable",
            reason="Internal test maintenance.", evidence_paths=["app.py"]) for item in all_task_ids])
    (context.spec_dir / "documentation-impact-report.md").write_text("---\n" + yaml.safe_dump(impact) + "---\n# Documentation\n")
    docs = review_report()
    docs = docs.replace("- T-001", "\n".join(f"- {item}" for item in all_task_ids))
    (context.spec_dir / "docs-verification-report.md").write_text(docs)
    effects = []
    monkeypatch.setattr(review, "_resolve_thread", lambda *args: effects.append("resolve") or True)
    monkeypatch.setattr(review, "_request_review", lambda *args: effects.append("request") or True)
    ordinary = controller._exec_verify(None, worktree_path=str(context.project_root))
    assert ordinary.passed, ordinary.failures
    result = controller._apply_post_verify_gates(ordinary, str(context.project_root))
    assert result.passed is passing, result.failures
    assert executor.dispatch_count == 3
    if passing:
        StrategyCoordinator._mark_review_reentry_phase_verified(store, pending)
        pending = store.read()["pending_review_reentry"]
    completed = StrategyCoordinator._complete_verified_review_reentry(store, review,
        pr_url="https://github.com/example/game/pull/1", pending_reentry=pending)
    assert completed is passing
    assert effects == (["resolve", "request"] if passing else [])
    if passing:
        assert store.read()["pending_review_reentry"] is None
        assert StrategyCoordinator._complete_verified_review_reentry(store, review,
            pr_url="https://github.com/example/game/pull/1", pending_reentry=pending)
        assert effects == ["resolve", "request"]
    else:
        assert result.failures[0].id == "fulfillment-gaps"


@pytest.mark.parametrize("mode", ["banzai", "semi", "guided"])
@pytest.mark.parametrize("cli", ["claude", "codex"])
def test_real_provider_facades_reach_ralph_with_no_tools(runner_context, tmp_path, monkeypatch, mode, cli):
    from harness.llm_provider import AICodingCliProvider
    from tests.unit.test_review_triage_provider import _config, _codex_wire, _claude_wire
    from tests.unit.test_inspection_turn import assert_no_tools_command
    monkeypatch.setattr("harness.ai_cli_backends.claude.host_workspace_synthesis_boundary_available", lambda: True)
    monkeypatch.setattr("harness.ai_cli_backends.claude_triage._sandbox_exec_path", lambda: "/usr/bin/sandbox-exec")
    monkeypatch.setattr("harness.ai_cli_backends.claude_triage.sys.platform", "darwin")
    wire = (_codex_wire("__RESULT__") if cli == "codex" else _claude_wire("__RESULT__")).decode()
    script = '''import json, sys
data = json.loads(sys.stdin.read().split("\\nHOST_INPUT_JSON\\n", 1)[1])
rows = [{"id": item, "verified_implementation_evidence": "", "verified_test_evidence": "",
         "codegraph_candidates": "", "candidate_disposition": "none", "evidence_kind": "missing",
         "evidence_strength": "none", "runtime_threshold": False, "confidence": "none", "notes": "No evidence"}
        for item in data["assignment"]["assigned_ids"]]
answer = json.dumps({**data["assignment"], "action": "final", "rows": rows, "unmapped_candidates": []})
'''
    script += f"sys.stdout.write({wire!r}.replace(json.dumps('__RESULT__'), json.dumps(answer)))\n"
    real_popen, commands = subprocess.Popen, []
    def launch(command, **kwargs):
        if Path(command[0]).name not in {"codex", "sandbox-exec"}:
            return real_popen(command, **kwargs)
        commands.append(command)
        return real_popen([sys.executable, "-c", script], **kwargs)
    monkeypatch.setattr(subprocess, "Popen", launch)
    provider = AICodingCliProvider(_config(cli, unsafe=True))
    controller, store = setup_delivery(runner_context, tmp_path, provider, mode)
    result = controller._refresh_fulfillment_report(VerifyResult(True), str(runner_context.project_root))
    assert result.passed, result.failures
    assert result.token_usage == (11 if cli == "codex" else 13)
    assert store.read()["tokens_used"] == result.token_usage
    assert len(commands) == 1
    assert_no_tools_command(cli, commands[0])
