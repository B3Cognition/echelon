"""Token limits through the current controlled Delivery loop.

Ralph, prompts, receipts and accounting are real; shared fixtures substitute
external agents, GitOps, sandbox execution and Prosaic inspection.
"""
import json

import pytest

from harness.ai_cli_backend import CliRunResult
from harness.delivery_slice_journal import DeliverySliceJournal
from tests.unit.test_delivery_controller import _initialize_git_worktree
from tests.unit.test_delivery_controller_integration import _controller, _reconstruct
from tests.unit.test_delivery_slice_runner import slice_project, ScriptedExecutor, _steps


def _budget_case(fixture, tmp_path, usages, *, budget, reject=False):
    _initialize_git_worktree(fixture[0])

    def agent(assignment, payload, root):
        if reject and assignment["step"] == "spec_guard":
            payload.update(verdict="FAIL", findings=["app.py:1 returns the wrong greeting"])
        index = min(len(executor.calls) - 1, len(usages) - 1)
        return CliRunResult(0, json.dumps(payload), "", token_usage=usages[index])

    executor = ScriptedExecutor(agent)
    controller, store = _controller(fixture, tmp_path, executor, "banzai")
    state = store.read()
    state["token_budget"] = budget
    store.write(state)
    return controller, store, executor


def _journal(controller, store):
    journal = DeliverySliceJournal(
        controller._delivery_operation_evidence_root(),
        store.read()["delivery_slice_operation"]["id"],
    )
    with journal:
        return journal, journal.load(required=True)


def _forbid_verification(monkeypatch, controller):
    def unexpected_verification(**kwargs):
        pytest.fail("A budget-exhausted or review-rejected slice cannot reach verification")
    monkeypatch.setattr(controller, "_verify_candidate_checkpoint", unexpected_verification)


@pytest.mark.e2e
@pytest.mark.parametrize("usages,steps,total", [
    ([19], ["implementer"], 19),  # Stop at 95%, not 100%.
    ([18, 1], ["implementer", "spec_guard"], 19),  # Below 95% may dispatch once more.
    ([25], ["implementer"], 25),  # An in-flight response can overshoot; bill it in full.
])
def test_budget_exhaustion_terminates_loop(slice_project, tmp_path, monkeypatch, usages, steps, total):
    controller, store, executor = _budget_case(slice_project, tmp_path, usages, budget=20)
    _forbid_verification(monkeypatch, controller)

    result = controller.run_loop(max_outer=10, max_inner=5, token_budget=20)

    assert result.status == "blocked"
    assert result.termination_reason == "budget_exhausted"
    assert result.tokens_used == total
    assert result.outer_iterations == 1
    assert _steps(executor) == steps
    state = store.read()
    assert state["tokens_used"] == total
    assert state["delivery_slice_operation"]["accounted_tokens"] == total
    assert state["delivery_slice_operation"]["progress_applied"] is False
    assert "delivery_slice_task_id" not in state
    assert "- [ ] T-001" in (slice_project[1] / "tasks.md").read_text()
    assert not controller._gitops.push.called
    assert not controller._gitops.create_draft_pr.called
    assert not controller._gitops.promote_pr_ready.called

    journal, data = _journal(controller, store)
    assert data["budget_limit"] == 19
    assert [row["token_usage"] for row in data["records"]] == usages
    assert all(row["result"] is not None for row in data["records"])
    before = journal.path.read_bytes()

    # A fresh controller with the unchanged limit must not spend again or
    # rewrite the retained receipts merely because the process restarted.
    restarted_executor = ScriptedExecutor()
    restarted = _reconstruct(controller, store, restarted_executor)
    _forbid_verification(monkeypatch, restarted)
    again = restarted.run_loop(max_outer=10, max_inner=5, token_budget=20)
    assert again.status == "blocked"
    assert again.termination_reason == "budget_exhausted"
    assert again.tokens_used == total
    assert store.read()["tokens_used"] == total
    assert not restarted_executor.calls
    assert journal.path.read_bytes() == before


@pytest.mark.e2e
def test_unlimited_budget_still_honors_review_repair_cap(slice_project, tmp_path, monkeypatch):
    controller, store, executor = _budget_case(
        slice_project, tmp_path, [10_000], budget=0, reject=True,
    )
    _forbid_verification(monkeypatch, controller)

    result = controller.run_loop(max_outer=2, max_inner=2, token_budget=None)

    assert result.status == "blocked"
    assert result.termination_reason == "build_blocked"
    assert "delivery_gate_repair_limit" in store.read()["build_reason"]
    assert _steps(executor) == ["implementer", "spec_guard", "code_reviewer", "test_guardian"] * 5
    assert result.tokens_used == 200_000
    assert store.read()["tokens_used"] == 200_000
    _, data = _journal(controller, store)
    assert data["budget_limit"] is None
    assert len(data["records"]) == 20
    assert all(row["token_usage"] == 10_000 for row in data["records"])
    assert "- [ ] T-001" in (slice_project[1] / "tasks.md").read_text()
    assert not controller._gitops.push.called
    assert not controller._gitops.create_draft_pr.called
