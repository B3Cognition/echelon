"""Real controlled-role admission and durable token accounting (no live LLM)."""
import pytest

from tests.e2e.controlled_ralph import CHAIN


@pytest.mark.e2e
class TestRalphBudget:
    def test_budget_exhaustion_terminates_loop(self, controlled_ralph):
        run = controlled_ralph(tokens=2000, reject_reviews=True)
        run.initialize(budget=5000)
        result = run.run(budget=5000)
        assert result.status == "blocked"
        assert result.termination_reason == "budget_exhausted"
        assert run.steps == ["implementer", "spec_guard", "code_reviewer"]
        assert result.tokens_used == 6000
        assert result.outer_iterations == 1

    def test_tokens_tracked_in_state_and_receipts(self, controlled_ralph):
        run = controlled_ralph(tokens=2000, reject_reviews=True)
        run.initialize(budget=5000)
        result = run.run(budget=5000)
        assert result.termination_reason == "budget_exhausted"
        assert run.store.read()["tokens_used"] == result.tokens_used == 6000
        journal, = run.journals()
        assert [record["token_usage"] for record in journal["records"]] == [2000, 2000, 2000]
        assert run.store.read()["delivery_slice_operation"]["accounted_tokens"] == 6000

    def test_no_progress_or_publication_on_mid_gate_budget_exhaustion(self, controlled_ralph):
        run = controlled_ralph(tokens=2000, reject_reviews=True)
        run.initialize(budget=5000)
        result = run.run(budget=5000)
        assert result.termination_reason == "budget_exhausted"
        assert len(run.executor.calls) == 3
        assert "accepted_task_id" not in run.store.read()["delivery_slice_operation"]
        assert not run.gitops.pr_created and not run.gitops.pr_promoted
        assert not run.gitops.pushes and not run.gitops.local_merges
        assert run.legacy_stub.call_count == 0

    def test_unlimited_budget_still_enforces_gate_repair_limit(self, controlled_ralph):
        run = controlled_ralph(tokens=10000, reject_reviews=True)
        run.initialize(budget=None)
        result = run.run(budget=None)
        assert result.status == "blocked"
        assert result.termination_reason == "build_blocked"
        assert "delivery_gate_repair_limit" in run.store.read()["build_reason"]
        assert run.steps == CHAIN * 5
        assert result.tokens_used == 200000
        assert not run.gitops.pr_created
