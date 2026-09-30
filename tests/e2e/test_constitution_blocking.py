"""Constitution rejection through the current controlled Delivery review loop.

Controlled review findings live in assignment-bound journals. They do not use
the legacy command verifier's Markdown escalation file or banzai bypass.
Ralph, prompt construction, gates and journals are real. Shared fixtures replace
the external agent, GitOps, sandbox provider and Prosaic inspection command.
"""

import pytest

from harness.delivery_slice_journal import DeliverySliceJournal
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
