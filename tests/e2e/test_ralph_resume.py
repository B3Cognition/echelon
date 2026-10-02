"""Restart through DeliveryController, with real pending role receipts."""
import json
from pathlib import Path

import pytest

from harness.escalation import EscalationHandler
from harness.run_intent import RunIntent


def intent(*, mode="semi", resume=False):
    return RunIntent("test-spec", mode=mode, resume=resume, token_budget=100_000,
                     max_outer=5, max_inner=5, auto_merge=mode != "guided")


@pytest.mark.e2e
class TestRalphResume:
    def test_block_answer_restart_and_converge(self, controlled_ralph, monkeypatch):
        run = controlled_ralph(wrong_builds=100, mode="semi")
        first = run.delivery(monkeypatch)
        blocked = first.run(intent())
        assert blocked.status == "blocked"
        assert blocked.termination_reason == "blocker_escalation", (blocked, first.state())
        state = first.state()
        escalation = Path(state["escalation_file"])
        assert escalation.is_file()
        operation = state["delivery_slice_operation"]["id"]
        before_usage = state["tokens_used"]
        handler = EscalationHandler(str(escalation.parent.parent))
        handler.resume(str(escalation), "Fix divide without changing the assertion.")
        assert "Fix divide without changing the assertion." in handler.check_resume(str(escalation))
        run.executor.wrong_builds = 0
        second = run.delivery(monkeypatch)
        result = second.run(intent(resume=True))
        assert result.status == "converged", (result, second.state())
        assert second.state()["tokens_used"] > before_usage
        assert second.state()["delivery_slice_operation"]["id"] != operation
        assert len(run.gitops.worktrees_created) == 1
        assert "return a / b" in (run.gitops.source / "app.py").read_text()
        assert run.gitops.pr_promoted

    def test_pending_unanswered_escalation_blocks_implicit_restart(self, controlled_ralph, monkeypatch):
        run = controlled_ralph(wrong_builds=100, mode="semi")
        first = run.delivery(monkeypatch)
        assert first.run(intent()).termination_reason == "blocker_escalation"
        state_path = first._state_store.state_file
        before = state_path.read_bytes()
        calls = len(run.executor.calls)
        second = run.delivery(monkeypatch)
        with pytest.raises(RuntimeError, match="escalation pending"):
            second.run(intent())
        assert state_path.read_bytes() == before
        assert len(run.executor.calls) == calls
        assert not run.gitops.pr_promoted and not run.gitops.local_merges

    def test_explicit_continue_without_answer_is_not_an_implicit_restart(self, controlled_ralph, monkeypatch):
        run = controlled_ralph(wrong_builds=100, mode="semi")
        first = run.delivery(monkeypatch)
        assert first.run(intent()).termination_reason == "blocker_escalation"
        escalation = Path(first.state()["escalation_file"])
        assert "## Answer" not in escalation.read_text()
        run.executor.wrong_builds = 0
        second = run.delivery(monkeypatch)
        result = second.run(intent(resume=True))
        assert result.status == "converged", (result, second.state())
        assert "## Answer" not in escalation.read_text()
        assert second.state()["status"] == "converged"
        assert second.state()["blocked_phase"] is None
        assert len(run.gitops.worktrees_created) == 1

    def test_guided_restart_preserves_receipts_and_mode(self, controlled_ralph, monkeypatch):
        run = controlled_ralph(mode="guided")
        first = run.delivery(monkeypatch)
        blocked = first.run(intent(mode="guided"))
        assert blocked.status == "blocked"
        state = first.state()
        assert state["blocked_phase"] == "implementation"
        assert state["build"]["completed_tasks"] == 1
        assert not run.provider.executions, "The guided build boundary precedes verification"
        assert run.executor.build_count == 1
        journals = {path: path.read_bytes() for path in first._state_dir.rglob("journal.json")}
        assert journals
        second = run.delivery(monkeypatch)
        resumed = second.run(intent(mode="guided", resume=True))
        assert resumed.status == "blocked", (resumed, second.state())
        assert second.state()["mode"] == "guided"
        assert run.executor.build_count == 1, "Accepted implementation must not be replayed"
        assert all(path.read_bytes() == raw for path, raw in journals.items())
        assert not run.gitops.local_merges and not run.gitops.pr_promoted

    def test_explicit_budget_increase_replays_known_roles_without_double_charging(self, controlled_ralph, monkeypatch):
        run = controlled_ralph(tokens=2000, mode="semi")
        small = RunIntent("test-spec", mode="semi", token_budget=5000, max_outer=5, max_inner=5)
        first = run.delivery(monkeypatch)
        blocked = first.run(small)
        assert blocked.status == "blocked" and blocked.termination_reason == "budget_exhausted"
        assert run.steps == ["implementer", "spec_guard", "code_reviewer"]
        assert first.state()["tokens_used"] == 6000
        journal_path, = first._state_dir.rglob("journal.json")
        initial = json.loads(journal_path.read_text())["records"]
        second = run.delivery(monkeypatch)
        result = second.run(intent(resume=True))
        assert result.status == "converged", (result, second.state())
        final = json.loads(journal_path.read_text())["records"]
        assert final[:3] == initial
        assert len(final) == 4 and final[3]["assignment"]["step"] == "test_guardian"
        assert run.executor.build_count == 1
        assert second.state()["token_budget"] == 100_000
        expected = 2000 * (len(run.executor.calls) + len(run.executor.inspections))
        expected += sum((len(stdout) + len(stderr)) // 4 for _, _, stdout, stderr in run.provider.executions)
        assert result.tokens_used == second.state()["tokens_used"] == expected
