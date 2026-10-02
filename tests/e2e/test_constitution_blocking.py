"""Controlled-delivery constitution gates with real specs and bound receipts.

The deterministic executor models a SPEC GUARD rejection, not LLM judgment.
These tests exercise Ralph, role loading, gate sequencing, journals and progress.
They do not claim to measure a live model's ability to detect violations.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from harness.ai_cli_backend import CliRunResult
from tests.e2e.conftest import MockGitOps, make_ralph_controller
from tests.e2e.stub_llm import StubLLM


CONSTITUTION = "# Constitution\nP1: Product code must never execute shell commands.\n"
FINDING = "app.py:2 Constitution P1 violation: product code executes a shell command"
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
                verdict, findings = "FAIL", [FINDING]
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
            assert record["result"]["findings"] == [FINDING]
            for key, value in record["assignment"].items():
                assert record["result"][key] == value
        assert FINDING in executor.calls[4][1], "The first repair must receive the rejection"

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
