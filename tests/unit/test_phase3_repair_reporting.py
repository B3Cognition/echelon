import pytest

from echelon.cli import _classify_run_recovery


@pytest.mark.parametrize("reason", ["repair_no_progress", "repair_action_unclassified", "repair_review_stale", "repair_context_incomplete", "repair_external_prerequisite", "repair_human_decision"])
def test_repair_block_explains_current_work_without_blind_continue(reason):
    from harness.recovery_instruction import trusted_executor_block_recovery, RecoveryKind
    assert trusted_executor_block_recovery("phase3-consensus", reason).kind == RecoveryKind.MANUAL_DIAGNOSIS
    state = {"status": "blocked", "phase": "terminal-blocked", "blocked_reason": reason,
        "selected_issue_resolution": "ISS-002", "issue_resolution_ledger": {"ISS-002": {
            "title": "Observation missing", "repair_phase": "phase3-how", "submission_count": 2,
            "repair_action": {"action": "Define the observation protocol"},
            "last_review_dispatch_id": "review"}},
        "phase3_issue_reviews": {"review": {"rationale": "No reproducible fixture provided."}}}
    action = _classify_run_recovery(state)
    assert action.kind == "manual_recovery"
    assert action.command != "echelon spec continue"
    assert "ISS-002" in action.note
    assert "phase3-how" in action.note
    assert "No reproducible fixture provided" in action.note


def test_technical_work_prompt_is_not_presented_as_user_approval():
    from harness.squad_executors import _render_issue_resolution_context
    state = {"phase": "phase3-how", "selected_issue_resolution": "ISS-002",
        "issue_resolution_ledger": {"ISS-002": {"status": "selected", "repair_phase": "phase3-how",
            "title": "Observation missing", "repair_action": {"action": "Derive a fixture",
                "affected_artifacts": ["contracts/api.md"], "evidence_refs": ["spec.md#FR-001"],
                "constraints": ["Do not weaken FR-001"]}}}}
    prompt = _render_issue_resolution_context(state)
    assert "Derive a fixture" in prompt
    assert "Do not weaken FR-001" in prompt
    assert "User decision" not in prompt
    assert "Amend spec.md" not in prompt
