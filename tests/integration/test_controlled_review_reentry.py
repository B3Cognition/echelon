"""Production PR triage/publisher/coordinator/Ralph handoff; external services scripted."""
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import MagicMock

import pytest
import yaml

from harness.ai_cli_backend import CliRunResult
from harness.config import HarnessConfig
from harness.delivery_controller import DeliveryController, _delivery_stack_snapshot
from harness.escalation import EscalationHandler
from harness.llm_provider import AICodingCliProvider
from harness.mode import ModeController
from harness.phase_a_readiness import REQUIRED_PHASE_A_BUILD_INPUTS
from harness.ralph import RalphController
from harness.review_loop import ApprovalState, ReviewComment, ReviewLoopController
from harness.run_intent import RunIntent
from harness.state import StateStore
from harness.verification_stack_runtime import apply_verification_stacks
from tests.unit.test_delivery_controller import MockProvider, _initialize_git_worktree
from tests.unit.test_delivery_slice_recovery import ProcessLost, _crash_after_receipt
from tests.unit.test_delivery_slice_runner import ScriptedExecutor, slice_project


@pytest.fixture
def review_handoff(slice_project, monkeypatch, request):
    root, spec, _ = slice_project
    # This fixture exercises review reentry, not final product verification. It
    # still needs a published Phase A contract for Delivery resume admission.
    for name in REQUIRED_PHASE_A_BUILD_INPUTS:
        path = spec / name
        if not path.exists():
            path.write_text(f"# {name}\n")
    (spec / "plan-conformance.json").write_text(json.dumps({
        "status": "pass", "findings": [], "sources": ["spec.md", "tasks.md"],
    }))
    (spec / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "|---|---|---|---|---|---|---|\n"
        "| FR-1 | TC-1 | unit | deferred-automation | planned | none | Review-only fixture; verification is out of scope. |\n"
        "| FR-2 | TC-2 | unit | deferred-automation | planned | none | Pending task outside the review slice. |\n"
    )
    stack = root / ".echelon/stacks/review-unit"
    stack.mkdir(parents=True)
    (stack / "stack.yml").write_text(yaml.safe_dump({
        "schema_version": "1.4",
        "stack": {"id": "review-unit", "name": "Review fixture unit tests",
                  "version": "1", "kind": "capability"},
        "applies_to": {"archetypes": ["custom"]},
        "provides": {"x.test.observer": "review-unit"},
        "context": {"files": ["context.md"]},
        "runnability": {"classification": "non_runnable", "policy": "not_applicable"},
        "coverage_observers": [{
            "id": "review-unit", "test_types": ["unit"],
            "command": 'python -B tests/emit_coverage_json.py "$ECHELON_COVERAGE_REPORT"',
            "report_path": ".echelon/coverage-reports/unit.json",
            "adapter": "vitest-json", "mode": "isolated", "required": True,
        }],
    }))
    (stack / "context.md").write_text("# Review fixture unit observer\n")
    (root / ".echelon/config.yml").write_text(
        "stacks:\n  selected:\n    - review-unit\n"
    )
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text(
        "import unittest\nfrom app import hello\n"
        "class GreetingTest(unittest.TestCase):\n"
        "    def test_greeting(self):\n"
        "        \"\"\"[echelon:TC-1] returns a greeting\"\"\"\n"
        "        self.assertTrue(hello().startswith('hello '))\n"
    )
    (tests / "emit_coverage_json.py").write_text(
        "import json\nimport sys\nimport unittest\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        "class RecordingResult(unittest.TextTestResult):\n"
        "    def __init__(self, *args, **kwargs):\n"
        "        super().__init__(*args, **kwargs)\n"
        "        self.passed_ids = []\n"
        "    def addSuccess(self, test):\n"
        "        super().addSuccess(test)\n"
        "        self.passed_ids.append(test.id())\n"
        "suite = unittest.defaultTestLoader.discover('tests')\n"
        "result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2, "
        "resultclass=RecordingResult).run(suite)\n"
        "passed = (result.wasSuccessful() and result.testsRun == 1 and "
        "result.passed_ids == ['test_app.GreetingTest.test_greeting'])\n"
        "report = {'testResults': [{'name': 'tests/test_app.py', 'assertionResults': ["
        "{'title': 'test_greeting [echelon:TC-1]', 'status': 'passed' if passed else 'failed', "
        "'failureMessages': [str(error) for _, error in result.failures + result.errors] "
        "or ([] if passed else ['TC-1 was not executed'])}]}]}\n"
        "path = Path(sys.argv[1])\npath.parent.mkdir(parents=True, exist_ok=True)\n"
        "path.write_text(json.dumps(report))\n"
        "raise SystemExit(0 if passed else 1)\n"
    )
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
    apply_verification_stacks(config, project_root=root, target_root=root)
    gitops = MagicMock()
    gitops.base_dir = str(root)
    gitops.get_latest_worktree.return_value = str(root)
    gitops.create_worktree.return_value = str(root)
    gitops.find_feature_branch.return_value = None
    triage_calls = []
    executor = ScriptedExecutor()

    class ExternalBackend:
        exclusive_write_scope_contract_id = "echelon.exclusive-write-scope.v1"

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

    store = StateStore(coordinator()._state_dir, "001")
    mode = getattr(getattr(request.node, "callspec", None), "params", {}).get("mode", "banzai")
    store.initialize("review-acceptance", mode, enabled_phases=["implementation", "review", "finalization"],
                     target_task_ids=["T-001"], spec_dir=str(spec), tasks_file=str(tasks), spec_file=str(spec / "spec.md"),
                     delivery_stack_snapshot=_delivery_stack_snapshot(config.resolved_stacks))
    store.transition("running")
    initial = RalphController(
        provider=MockProvider(), gitops=gitops, state_store=store,
        mode_controller=ModeController(mode), escalation_handler=EscalationHandler(str(root.parent / "escalations")),
        spec_id="001", config=config, llm_provider=provider(config),
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


@pytest.mark.parametrize("rename_case", [False, True])
def test_review_fixture_observer_reports_only_the_owned_case(review_handoff, tmp_path, rename_case):
    _, _, _, _, _, spec, _ = review_handoff
    root = spec.parents[1]
    test_file = root / "tests/test_app.py"
    if rename_case:
        test_file.write_text(test_file.read_text().replace("def test_greeting", "def test_other"))
    report = tmp_path / "coverage.json"

    result = subprocess.run(
        [sys.executable, "-B", "tests/emit_coverage_json.py", str(report)],
        cwd=root, capture_output=True, text=True, check=False,
    )

    assert (result.returncode == 0) is not rename_case
    status = json.loads(report.read_text())["testResults"][0]["assertionResults"][0]["status"]
    assert status == ("failed" if rename_case else "passed")


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
