"""Escalation from real verification failures, distinct from controlled gate blocks."""
import time
import pytest

from tests.e2e.controlled_ralph import CHAIN, FINDING


@pytest.mark.e2e
class TestRalphEscalation:
    def test_escalation_triggers_after_3x_same_failure(self, controlled_ralph):
        run = controlled_ralph(wrong_builds=100, mode="semi")
        run.initialize(budget=100_000)
        result = run.run(budget=100_000)
        assert result.status == "blocked"
        assert result.termination_reason == "blocker_escalation", (result, run.store.read())
        assert len(run.provider.executions) == 3
        assert all(call[1] != 0 and "20 != 5" in call[3] for call in run.provider.executions)
        assert run.steps == CHAIN * 3
        assert not run.gitops.pr_promoted and not run.gitops.local_merges
        assert not run.executor.inspections, "Failed tests must not enter fulfillment"

    def test_state_keeps_delivery_status_after_phase_escalation(self, controlled_ralph):
        run = controlled_ralph(wrong_builds=100, mode="semi")
        run.initialize()
        result = run.run()
        assert result.termination_reason == "blocker_escalation"
        state = run.store.read()
        assert state["status"] == "running"
        assert state["termination_reason"] == "blocker_escalation"
        assert state["last_verify_result"]["passed"] is False
        assert state["tokens_used"] == result.tokens_used

    def test_escalation_file_has_actual_failure_and_no_answer(self, controlled_ralph):
        run = controlled_ralph(wrong_builds=100, mode="semi")
        run.initialize()
        assert run.run().termination_reason == "blocker_escalation"
        files = list(run.escalation.escalations_dir.glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "# Escalation:" in content
        assert "same_failure_repeat" in content
        assert "## Question" in content and "## Context" in content
        assert "20 != 5" in content
        assert run.escalation.check_resume(str(files[0])) is None
        assert run.store.read()["escalation_file"] == str(files[0])

    def test_escalation_and_cleanup_within_timeout(self, controlled_ralph):
        run = controlled_ralph(wrong_builds=100, mode="semi")
        run.initialize()
        start = time.monotonic()
        result = run.run()
        assert result.termination_reason == "blocker_escalation"
        assert time.monotonic() - start < 60
        assert len(run.provider.created) == 3
        assert set(run.provider.created) == set(run.provider.destroyed)

    def test_banzai_skips_optional_escalation_not_authoritative_verification(self, controlled_ralph):
        run = controlled_ralph(wrong_builds=100, mode="banzai")
        run.initialize(max_outer=2, max_inner=3)
        result = run.run(max_outer=2, max_inner=3)
        assert result.status == "blocked"
        assert result.termination_reason == "outer_cap", (result, run.store.read())
        assert len(run.provider.executions) >= 3
        assert all(call[1] != 0 for call in run.provider.executions)
        assert not list(run.escalation.escalations_dir.glob("*.md"))
        assert not run.gitops.local_merges and not run.gitops.pr_promoted

    @pytest.mark.parametrize("mode", ["semi", "banzai"])
    def test_controlled_gate_repair_limit_cannot_be_skipped(self, controlled_ralph, mode):
        run = controlled_ralph(reject_reviews=True, mode=mode)
        run.initialize()
        result = run.run()
        assert result.status == "blocked" and result.termination_reason == "build_blocked"
        assert run.steps == CHAIN * 5
        assert "delivery_gate_repair_limit" in run.store.read()["build_reason"]
        assert all(FINDING in record["result"]["findings"]
                   for journal in run.journals() for record in journal["records"]
                   if record["assignment"]["step"] == "spec_guard")
        assert not run.provider.executions
        assert not run.gitops.pr_created
        assert not list(run.escalation.escalations_dir.glob("*.md"))
