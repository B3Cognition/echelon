"""Controlled Delivery constitution rejection with bound review receipts.

The network and shell fixtures exercise Ralph, gates, journals, and progress
without claiming to measure a live model's judgment.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from harness.ai_cli_backend import CliRunResult
from harness.delivery_slice_journal import DeliverySliceJournal
from tests.e2e.conftest import MockGitOps, make_ralph_controller
from tests.e2e.stub_llm import StubLLM
from tests.unit.test_delivery_controller import _initialize_git_worktree
from tests.unit.test_delivery_controller_integration import _controller
from tests.unit.test_delivery_slice_runner import slice_project, ScriptedExecutor, _steps


RULE = "CONST-001: Production code must not access the network."
FINDING = "app.py:1 imports urllib.request, violating CONST-001 (no network access)."


def _constitution_case(fixture, tmp_path, mode, *, repair=False):
    project, _, _ = fixture
    (project / ".echelon/constitution.md").write_text("# Constitution\n" + RULE + "\n")
    _initialize_git_worktree(project)
    implementations = 0

    def agent(assignment, payload, root):
        nonlocal implementations
        if assignment["step"] == "implementer":
            implementations += 1
            if not repair or implementations == 1:
                (root / "app.py").write_text(
                    "import urllib.request\ndef hello(): return 'hello'\n",
                )
        if assignment["step"] == "spec_guard":
            # Exercise the rendered constitution context, not a fixture-only claim.
            assert RULE in executor.calls[-1][2]
            if "urllib.request" in (root / "app.py").read_text():
                payload.update(verdict="FAIL", summary="Constitution violation", findings=[FINDING])

    executor = ScriptedExecutor(agent)
    controller, store = _controller(fixture, tmp_path, executor, mode)
    return controller, store, executor


def _journal(controller, store):
    with DeliverySliceJournal(
        controller._delivery_operation_evidence_root(),
        store.read()["delivery_slice_operation"]["id"],
    ) as journal:
        return journal.load(required=True)
CONSTITUTION = "# Constitution\nP1: Product code must never execute shell commands.\n"
SHELL_FINDING = "app.py:2 Constitution P1 violation: product code executes a shell command"
CHAIN = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]


class ConstitutionGitOps(MockGitOps):
    def create_worktree(self, *args, **kwargs):
        root = Path(super().create_worktree(*args, **kwargs))
        spec = root / "specs/test-spec"
        spec.mkdir(parents=True)
        (spec / "spec.md").write_text("# Spec\nFR-1: Return a greeting without shell execution.\n")
        (spec / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=build req=FR-1 depends=none\n"
            "  **Files:**\n  - `app.py` - Greeting implementation.\n"
            "  **Acceptance Criteria:**\n  - [ ] Return hello without a shell.\n"
        )
        (root / ".echelon").mkdir(exist_ok=True)
        (root / ".echelon/constitution.md").write_text(CONSTITUTION)
        (root / "app.py").write_text("def hello(): return None\n")
        return str(root)


class ConstitutionExecutor:
    supports_read_only_review = True

    def __init__(self):
        self.calls = []

    def run_agent_result(self, cwd, prompt, *, request_metadata, **kwargs):
        assignment = request_metadata["delivery_assignment"]
        root = Path(cwd)
        self.calls.append((dict(assignment), prompt))
        step = assignment["step"]
        verdict = {"implementer": "DONE", "spec_guard": "PASS",
                   "code_reviewer": "APPROVED", "test_guardian": "PASS"}[step]
        findings = []
        if step == "implementer":
            # Each repair creates a fresh, still-invalid candidate.
            (root / "app.py").write_text(
                "import subprocess\n"
                f"def hello(): subprocess.run(['echo', 'hello-{len(self.calls)}'])\n"
            )
        elif step == "spec_guard":
            assert json.dumps(CONSTITUTION) in prompt
            assert (root / ".echelon/constitution.md").read_text() == CONSTITUTION
            if "subprocess.run" in (root / "app.py").read_text():
                verdict, findings = "FAIL", [SHELL_FINDING]
        return CliRunResult(0, json.dumps({
            **assignment, "verdict": verdict,
            "summary": "Reviewed the assigned task against constitution P1",
            "findings": findings,
        }), "", token_usage=50)


@pytest.fixture
def constitution_run(tmp_harness_dir, harness_config):
    def run(mode="semi"):
        agents = tmp_harness_dir / ".echelon/prosaic/subagents"
        agents.mkdir(parents=True)
        source = Path(__file__).resolve().parents[2] / "prosaic/subagents"
        for role in ("implementer", "spec-guard", "code-reviewer", "test-guardian"):
            name = f"echelon.delivery-{role}.md"
            shutil.copyfile(source / name, agents / name)
        (tmp_harness_dir / ".echelon/constitution.md").write_text(CONSTITUTION)
        executor = ConstitutionExecutor()
        legacy_stub = StubLLM(mode="spec_guard_fail")
        controller, store, gitops, provider, _ = make_ralph_controller(
            stub_llm=legacy_stub, tmp_dir=tmp_harness_dir,
            harness_config=harness_config, mode=mode,
            mock_gitops=ConstitutionGitOps(tmp_harness_dir), llm_provider=executor,
        )
        store.acquire_lock("test-run")
        try:
            store.initialize(run_id="test-run", mode=mode, max_outer=3, max_inner=5,
                             token_budget=500_000)
            result = controller.run_loop(max_outer=3, max_inner=5, token_budget=500_000)
            state = store.read()
            journals = list(store.state_dir.rglob("journal.json"))
            assert len(journals) == 1, "A real controlled operation must retain its journal"
            journal = json.loads(journals[0].read_text())
        finally:
            store.release_lock()
        return result, state, journal, executor, gitops, legacy_stub
    return run


@pytest.mark.e2e
@pytest.mark.parametrize("mode", ["semi", "guided", "banzai"])
def test_spec_guard_violation_is_retained_and_blocks_delivery(slice_project, tmp_path, monkeypatch, mode):
    controller, store, executor = _constitution_case(slice_project, tmp_path, mode)

    def unexpected_verification(**kwargs):
        pytest.fail("A constitution-rejected slice must not reach candidate verification")

    monkeypatch.setattr(controller, "_verify_candidate_checkpoint", unexpected_verification)
    result = controller.run_loop(max_outer=3, max_inner=5, token_budget=500_000)

    assert result.status == "blocked"
    assert result.termination_reason == ("blocker_escalation" if mode == "guided" else "build_blocked")
    assert result.outer_iterations == 1
    assert result.final_verify is None
    state = store.read()
    if mode == "guided":
        # Guided mode pauses at the after-build boundary before finalizing the
        # build blocker. Its rejected receipts must still survive below.
        assert state["status"] == "blocked"
        assert state["blocked_phase"] == "implementation"
    else:
        assert state["build_status"] == "blocked"
        assert "delivery_gate_repair_limit" in state["build_reason"]
    assert state.get("build", {}).get("completed_tasks", 0) == 0
    assert "- [ ] T-001" in (slice_project[1] / "tasks.md").read_text()
    assert "delivery_slice_task_id" not in state
    assert not controller._gitops.push.called
    assert not controller._gitops.create_draft_pr.called

    # Initial implementation plus four bounded repairs; no mode skips a gate.
    chain = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    assert _steps(executor) == chain * 5
    receipts = _journal(controller, store)["records"]
    guards = [row for row in receipts if row["assignment"]["step"] == "spec_guard"]
    assert [row["repair_attempt"] for row in guards] == [0, 1, 2, 3, 4]
    for row in guards:
        assert row["result"]["verdict"] == "FAIL"
        assert row["result"]["findings"] == [FINDING]
        assert row["result"]["task_id"] == "T-001"
        assert row["result"]["candidate_fingerprint"] == row["assignment"]["candidate_fingerprint"]
    for assignment, _, prompt in executor.calls[4:]:
        if assignment["step"] == "implementer":
            assert FINDING in prompt  # The next repair receives the actual rejection.


@pytest.mark.e2e
def test_constitution_repair_requires_fresh_passing_reviews(slice_project, tmp_path):
    controller, store, executor = _constitution_case(slice_project, tmp_path, "semi", repair=True)
    result = controller._exec_build(
        None, "echelon build", "", worktree_path=str(slice_project[0]), prompt="build",
    )

    assert result["passed"] is True
    assert result["task_ids"] == ["T-001"]
    assert _steps(executor) == ["implementer", "spec_guard", "code_reviewer", "test_guardian"] * 2
    receipts = _journal(controller, store)["records"]
    assert receipts[1]["result"]["verdict"] == "FAIL"
    assert receipts[1]["result"]["findings"] == [FINDING]
    assert [row["result"]["verdict"] for row in receipts[-4:]] == ["DONE", "PASS", "APPROVED", "PASS"]
    assert receipts[1]["assignment"]["candidate_fingerprint"] != receipts[5]["assignment"]["candidate_fingerprint"]
    assert "urllib.request" not in (slice_project[0] / "app.py").read_text()
    # Slice review is not final Delivery acceptance or publication.
    assert "- [ ] T-001" in (slice_project[1] / "tasks.md").read_text()
    assert not controller._gitops.push.called


@pytest.mark.e2e
class TestConstitutionBlocking:
    def test_spec_guard_violation_blocks_after_bounded_repairs(self, constitution_run):
        result, state, journal, executor, _, _ = constitution_run()
        assert [call[0]["step"] for call in executor.calls] == CHAIN * 5
        assert result.status == "blocked"
        assert result.termination_reason == "build_blocked"
        assert "delivery_gate_repair_limit" in state["build_reason"]
        assert result.tokens_used == 1000
        assert {record["repair_attempt"] for record in journal["records"]} == {0, 1, 2, 3, 4}

    def test_constitution_rejections_retain_assignment_bound_receipts(self, constitution_run):
        _, _, journal, executor, _, _ = constitution_run()
        guards = [record for record in journal["records"]
                  if record["assignment"]["step"] == "spec_guard"]
        assert len(guards) == 5
        for record in guards:
            assert record["error"] is None
            assert record["result"]["verdict"] == "FAIL"
            assert record["result"]["findings"] == [SHELL_FINDING]
            for key, value in record["assignment"].items():
                assert record["result"][key] == value
        assert SHELL_FINDING in executor.calls[4][1], "The first repair must receive the rejection"

    def test_rejection_never_marks_progress_or_publishes(self, constitution_run):
        result, state, _, executor, gitops, legacy_stub = constitution_run()
        assert len(executor.calls) == 20
        assert result.outer_iterations == 1
        assert "accepted_task_id" not in state["delivery_slice_operation"]
        assert "delivery_slice_task_id" not in state
        tasks = Path(gitops.worktrees_created[0]) / "specs/test-spec/tasks.md"
        assert "- [ ] T-001" in tasks.read_text()
        assert legacy_stub.call_count == 0, "Do not verify/publish a gate-rejected candidate"
        assert not gitops.pushes and not gitops.local_merges and not gitops.pr_created

    def test_banzai_mode_cannot_bypass_constitution_gate(self, constitution_run):
        result, state, _, executor, gitops, _ = constitution_run("banzai")
        assert [call[0]["step"] for call in executor.calls] == CHAIN * 5
        assert result.status == "blocked"
        assert result.termination_reason == "build_blocked"
        assert "delivery_gate_repair_limit" in state["build_reason"]
        assert result.outer_iterations == 1
        assert not gitops.pr_created
