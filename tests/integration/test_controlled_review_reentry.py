"""Production PR triage/publisher/coordinator/Ralph handoff; external services scripted."""
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
from unittest.mock import MagicMock

import pytest

from harness.ai_cli_backend import CliRunResult
from harness.config import HarnessConfig
from harness.delivery_controller import DeliveryController
from harness.escalation import EscalationHandler
from harness.llm_provider import AICodingCliProvider
from harness.mode import ModeController
from harness.ralph import RalphController
from harness.review_loop import ApprovalState, ReviewComment, ReviewLoopController
from harness.run_intent import RunIntent
from harness.state import StateStore
from tests.unit.test_delivery_controller import MockProvider, _initialize_git_worktree
from tests.unit.test_delivery_slice_recovery import ProcessLost, _crash_after_receipt
from tests.unit.test_delivery_slice_runner import ScriptedExecutor, slice_project


@pytest.fixture
def review_handoff(slice_project, monkeypatch, request):
    root, spec, _ = slice_project
    inspect_subagent = subprocess.run
    def inspect(argv, **kwargs):
        result = inspect_subagent(argv, **kwargs)
        if argv[:2] == ["prosaic", "inspect"] and argv[2].startswith("commands/"):
            payload = json.loads(result.stdout)
            payload["type"] = "command"
            result.stdout = json.dumps(payload)
        return result
    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", inspect)
    tasks = spec / "tasks.md"
    (spec / "review-fix-1.md").write_text("HISTORICAL-REVIEW-EVIDENCE")
    source = Path(__file__).resolve().parents[2] / "prosaic"
    for relative in ["commands/echelon.review.md", *[
        f"subagents/echelon.review-{role}.md" for role in ("debugger", "sentinel", "spec-guard")
    ]]:
        destination = root / ".echelon/prosaic" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, destination)
    _initialize_git_worktree(root)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "verified candidate"], cwd=root, check=True, capture_output=True)
    config = HarnessConfig()
    config.llm.enabled = True
    config.llm.features["delivery_gate_controller"] = True
    config.review_loop.enabled = True
    config.pr_host = "github"
    gitops = MagicMock()
    gitops.base_dir = str(root)
    gitops.get_latest_worktree.return_value = str(root)
    gitops.create_worktree.return_value = str(root)
    gitops.find_feature_branch.return_value = None
    triage_calls = []
    executor = ScriptedExecutor()

    class ExternalBackend:
        def run_agent(self, request):
            return executor.run_agent_result(request.cwd, request.prompt, request_metadata=request.metadata)

        def run_review_triage_turn(self, request):
            name = request.metadata["prompt_metadata"]["name"]
            triage_calls.append((name, request.prompt))
            if name != "echelon.review":
                response = {"action": "result", "analysis": "FR-1: app.py:1 must preserve the greeting."}
            else:
                framed = request.prompt.split("## Host assignment\n", 1)[1].split("```json\n", 1)[1].split("\n```", 1)[0]
                assignment = json.loads(framed)["assignment"]
                rows = assignment["tasks_append_contract"]["required_rows"]
                response = {
                    "manifest": assignment["required_manifest"],
                    "artifacts": {name: "# Current review\nCURRENT-REVIEW-EVIDENCE app.py:1 preserve greeting.\n"
                                  for name in assignment["allocated_artifact_names"]},
                    "tasks_append": "\n\n".join(
                        f"- [ ] {row['task_id']} complexity=standard phase=review-fix req=FR-1 depends={row['depends']}\n\n"
                        f"  **Title:** {row['review_task_id']} - Preserve greeting at app.py:1"
                        for row in rows) + "\n",
                }
            return CliRunResult(0, json.dumps(response), "", token_usage=2)

    def provider(selected):
        result = AICodingCliProvider(selected)
        result._backend = ExternalBackend()
        return result

    monkeypatch.setattr("harness.delivery_controller.AICodingCliProvider", provider)
    monkeypatch.setattr("harness.review_loop.AICodingCliProvider", provider)
    monkeypatch.setattr("harness.llm_provider.host_workspace_synthesis_boundary_available", lambda: True)
    comment = ReviewComment("c1", "app.py", 1, "Must preserve greeting", "reviewer", datetime.now(timezone.utc), True)
    monkeypatch.setattr(ReviewLoopController, "_fetch_unresolved_comments", lambda *args: [comment])
    monkeypatch.setattr(ReviewLoopController, "_fetch_approval_state", lambda *args: ApprovalState.CHANGES_REQUESTED)
    effects = []
    monkeypatch.setattr(ReviewLoopController, "_resolve_thread", lambda *args: effects.append("resolve"))
    monkeypatch.setattr(ReviewLoopController, "_request_review", lambda *args: effects.append("request"))

    def coordinator():
        return DeliveryController(MockProvider(), gitops, config, base_dir=str(root.parent / "control"),
                                   orchestration_root=root, build_id="review-acceptance")

    store = StateStore(coordinator()._state_dir, "001", "default")
    mode = request.node.callspec.params.get("mode", "banzai")
    store.initialize("review-acceptance", mode, enabled_phases=["implementation", "review", "finalization"],
                     target_task_ids=["T-001"], spec_dir=str(spec), tasks_file=str(tasks), spec_file=str(spec / "spec.md"))
    store.transition("running")
    initial = RalphController(
        provider=MockProvider(), gitops=gitops, state_store=store,
        mode_controller=ModeController(mode), escalation_handler=EscalationHandler(str(root.parent / "escalations")),
        spec_id="001", strategy_id="default", config=config, llm_provider=provider(config),
    )
    built = initial._exec_build(None, "echelon build", "", worktree_path=str(root), prompt="Initial candidate")
    assert built["passed"] and built["task_ids"] == ["T-001"], built
    initial._apply_build_task_progress(worktree_path=str(root), task_ids=built["task_ids"])
    assert store.read()["delivery_slice_operation"]["progress_applied"] is True
    executor.calls.clear()
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "accepted initial slice"], cwd=root, check=True, capture_output=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    # Seed only the preceding authoritative verification checkpoint. The retained
    # operation, receipts and canonical task progress above are produced by Ralph.
    store.transition("verified", updates={"last_completed_phase": "implementation", "registered_worktree": str(root),
                     "verified_commit": head, "outer_iter": 1,
                     "pr_url": "https://github.com/example/game/pull/1", "tokens_used": 100})
    store.transition("reviewing")
    return coordinator, store, executor, triage_calls, effects, spec, config


@pytest.mark.parametrize("cli", ["claude", "codex"])
@pytest.mark.parametrize("mode", ["banzai", "semi", "guided"])
@pytest.mark.parametrize("interrupt", [False, True])
def test_published_review_reentry_resumes_real_gates_without_widening_scope(review_handoff, monkeypatch, cli, mode, interrupt):
    coordinator, store, executor, triage_calls, effects, spec, config = review_handoff
    config.llm.cli = cli
    intent = RunIntent("001", mode=mode, max_outer=4, resume=True, auto_merge=False)
    def reject(assignment, payload, root):
        if assignment["step"] == "code_reviewer":
            payload.update(verdict="BLOCKED", findings=["Review repair needs human confirmation"])
    executor.script = reject
    if interrupt:
        with monkeypatch.context() as patch:
            _crash_after_receipt(patch, 2)
            with pytest.raises(ProcessLost):
                coordinator()._run_delivery(intent, budget=10000)
        assert [call[0]["step"] for call in executor.calls] == ["implementer", "spec_guard"]
        assert store.read()["tokens_used"] == 108
        assert not effects
    result = coordinator()._run_delivery(intent, budget=10000)
    pending = store.read()["pending_review_reentry"]
    assert pending["artifact_paths"] == [str(spec / "review-fix-2.md")]
    assert len(pending["task_ids"]) == 3
    assert not pending["phase1_verified"] and not effects
    assert len(triage_calls) == 4
    assert result.status == "blocked", result
    assert [call[0]["step"] for call in executor.calls] == ["implementer", "spec_guard", "code_reviewer"]
    assert {call[0]["task_id"] for call in executor.calls} == {pending["task_ids"][0]}
    for _, _, prompt in executor.calls:
        assert "CURRENT-REVIEW-EVIDENCE" in prompt
        assert "HISTORICAL-REVIEW-EVIDENCE" not in prompt
    assert len(triage_calls) == 4 and not effects
    assert "- [ ] T-002" in (spec / "tasks.md").read_text()
    assert store.read()["pending_review_reentry"] == pending
    assert store.read()["tokens_used"] == result.tokens_used == 129


@pytest.mark.parametrize("cli", ["claude", "codex"])
def test_accepted_review_slice_reaches_verification_and_replays_without_dispatch(review_handoff, monkeypatch, cli):
    coordinator, store, executor, triage_calls, effects, spec, config = review_handoff
    config.llm.cli = cli
    intent = RunIntent("001", mode="banzai", max_outer=4, resume=True)
    verification_calls = []
    def stop_at_verification(self, handle, worktree_path=""):
        verification_calls.append(worktree_path)
        raise ProcessLost()
    # This acceptance checkpoint ends at authoritative verification, not final
    # product acceptance. No verifier result, fulfillment or merge is fabricated.
    monkeypatch.setattr(RalphController, "_exec_verify", stop_at_verification)
    for _ in range(2):
        with pytest.raises(ProcessLost):
            coordinator()._run_delivery(intent, budget=10000)
    pending = store.read()["pending_review_reentry"]
    assert len(verification_calls) == 2
    assert len(triage_calls) == 4
    assert [call[0]["step"] for call in executor.calls] == ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert {call[0]["task_id"] for call in executor.calls} == {pending["task_ids"][0]}
    assert store.read()["tokens_used"] == 136
    assert not pending["phase1_verified"] and not effects
    tasks = (spec / "tasks.md").read_text()
    assert f"- [x] {pending['task_ids'][0]}" in tasks
    assert all(f"- [ ] {task}" in tasks for task in ["T-002", *pending["task_ids"][1:]])


@pytest.mark.parametrize("cli", ["claude", "codex"])
def test_review_usage_counts_toward_repair_admission_budget(review_handoff, cli):
    coordinator, store, executor, triage_calls, effects, spec, config = review_handoff
    config.llm.cli = cli
    result = coordinator()._run_delivery(
        RunIntent("001", mode="banzai", max_outer=4, resume=True), budget=110,
    )
    assert result.status == "blocked" and result.termination_reason == "budget_exhausted"
    assert result.tokens_used == store.read()["tokens_used"] == 108
    assert len(triage_calls) == 4 and not executor.calls and not effects
    assert not store.read()["pending_review_reentry"]["phase1_verified"]
