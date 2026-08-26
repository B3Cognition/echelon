from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.protocol_25.controller import plan_next_protocol_25
from harness.re_v2.protocol_25.recovery import recover_protocol_25_run
from harness.re_v2.protocol_25.status import (
    protocol_25_status_document,
    render_protocol_25_status,
)
from tests.integration.test_re_v2_protocol_25_recovery import (
    _accept_every_audit,
    _accept_every_prerequisite,
    _context,
)


@pytest.mark.unit
def test_complete_l3_status_limits_its_quality_claim_to_selected_scope(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    _accept_every_prerequisite(context)
    _accept_every_audit(context)
    for expected in ("freeze_epoch", "accept_roots", "terminal_complete"):
        action = plan_next_protocol_25(
            recover_protocol_25_run(context).controller_state
        )
        assert action is not None and action.kind == expected
        context.apply_controller_action(action)

    document = protocol_25_status_document(
        context.paths.root.parent,
        context=context,
    )
    human = render_protocol_25_status(
        context.paths.root.parent,
        context=context,
    )

    assert document["status"] == "complete"
    assert document["banner"] == "L3 SELECTED SCOPE COMPLETE"
    assert document["semantic"]["frozen_findings"] == 0
    assert document["semantic"]["unresolved_findings"] == 0
    assert document["semantic"]["deferred_observations"] == 0
    assert document["not_run"] == {
        "exhaustive_re_l4": "not run",
        "workspace_synthesis": "not run",
    }
    assert document["completion_scope"] == "selected L3 scope only"
    assert document["next_action"] == "none — selected L3 scope is complete"
    assert human.endswith("L3 SELECTED SCOPE COMPLETE\n")
    assert "workspace synthesis: not run" in human


@pytest.mark.unit
def test_blocked_pre_epoch_status_preserves_retained_candidates_and_resume_action(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    _accept_every_prerequisite(context)
    _accept_every_audit(context, limit=1)
    context.event_store.append(
        "executor_failed",
        {
            "executor_contract_hash": "sha256:" + "1" * 64,
            "executor_failure_receipt_id": "sha256:" + "2" * 64,
            "trigger_work_item_id": "sha256:" + "3" * 64,
        },
        occurred_at=context.clock(),
    )
    context.event_store.append(
        "run_failed",
        {"reason": "semantic closure is incomplete"},
        occurred_at=context.clock(),
    )

    document = protocol_25_status_document(
        context.paths.root.parent,
        context=context,
    )

    assert document["status"] == "blocked_incomplete"
    assert document["artifact_counts"]["retained_audit_candidates"] == 1
    assert document["semantic"]["unresolved_audit_targets"] == 1
    assert document["continuable"] is False
    assert document["next_action"] == (
        "run `echelon re resume \"<guidance>\"`; identical guidance reuses "
        "the existing successor with zero provider calls"
    )
