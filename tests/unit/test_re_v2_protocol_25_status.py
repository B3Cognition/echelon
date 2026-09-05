from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.model import ExecutionCaptureV1
from harness.re_v2.protocol_25.controller import plan_next_protocol_25
from harness.re_v2.protocol_25.preflight import AuditContextPreflightFailureV1
from harness.re_v2.protocol_25.recovery import (
    _accepted_prerequisites,
    recover_protocol_25_run,
)
from harness.re_v2.protocol_25.status import (
    _authority,
    _document,
    _next_action,
    _render_human,
    protocol_25_status_document,
    render_protocol_25_status,
)
from tests.integration.test_re_v2_protocol_25_recovery import (
    _accept_every_audit,
    _accept_every_prerequisite,
    _context,
)


@pytest.mark.unit
def test_projection_blocker_recommends_a_fresh_l3_successor(tmp_path: Path) -> None:
    context = _context(tmp_path)

    assert _next_action(
        "blocked_incomplete",
        context.semantic_graph.manifest,
        {},
        projection_failed=True,
    ) == (
        "run `echelon re deepen --to L3 --source api "
        f"--domain {context.semantic_graph.manifest.selection.domain_keys[0]} "
        "--from-run re-parent`"
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
    assert document["telemetry"]["zero_call_reuse"] is True
    assert document["telemetry"]["successor_adoption"] is False
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
    assert document["next_action"] == "run `echelon re resume --recommended`"
    assert document["guidance"]["recommended_eligible"] is True
    assert document["guidance"]["banzai_eligible"] is False
    assert [
        item["command"]
        for item in document["guidance"]["actions"]
        if item["enabled"]
    ] == [
        "echelon re resume --recommended",
        'echelon re resume "<your guidance>"',
    ]


@pytest.mark.unit
def test_preflight_blocker_reports_bytes_zero_dispatch_and_fresh_child_command(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    _accept_every_prerequisite(context)
    accepted = _accepted_prerequisites(context, context.ledger.replay())
    target = context.semantic_graph.ready_audit_targets(accepted)[0]
    template = context.semantic_graph.audit_templates[0]
    item = context.semantic_graph.instantiate_audit_item(
        template,
        target,
        {
            template_id: accepted[template_id]
            for template_id in template.required_template_ids
        },
    )
    failure = AuditContextPreflightFailureV1(
        schema_version=1,
        audit_target_id=target.audit_target_id,
        work_item_id=item.work_item_id,
        scope_kind="domain",
        source_id=target.scope.source_id,
        domain_key=target.scope.domain_key,
        reason_code="semantic_context_byte_ceiling_exceeded",
        projection_class="semantic-audit-context",
        measured_canonical_json_bytes=2701823,
        max_canonical_json_bytes=196608,
        provider_dispatch_count=0,
    )
    context.ledger.record_audit_context_preflight_failure(failure)
    context.event_store.append(
        "audit_context_preflight_failed",
        {
            "audit_target_id": failure.audit_target_id,
            "work_item_id": failure.work_item_id,
            "failure_receipt_id": failure.identity,
            "reason_code": failure.reason_code,
            "measured_canonical_json_bytes": failure.measured_canonical_json_bytes,
            "max_canonical_json_bytes": failure.max_canonical_json_bytes,
            "provider_dispatch_count": 0,
        },
        occurred_at=context.clock(),
    )
    context.event_store.append(
        "run_failed",
        {"reason": "semantic audit context preflight failed"},
        occurred_at=context.clock(),
    )

    document = protocol_25_status_document(
        context.paths.root.parent,
        context=context,
    )
    human = render_protocol_25_status(
        context.paths.root.parent,
        context=context,
    )

    assert document["layer_protocol_version"] == "2.5"
    assert document["preflight"] == {
        "state": "failed",
        "checked_target_count": 1,
        "selected_target_count": len(context.semantic_graph.audit_target_plans),
        "max_measured_canonical_json_bytes": 2701823,
        "max_canonical_json_bytes": 196608,
        "provider_dispatch_count": 0,
        "failure": {
            "audit_target_id": failure.audit_target_id,
            "scope_kind": "domain",
            "source_id": target.scope.source_id,
            "domain_key": target.scope.domain_key,
            "reason_code": "semantic_context_byte_ceiling_exceeded",
        },
    }
    assert document["telemetry"]["provider_dispatches_avoided_by_preflight"] == len(
        context.semantic_graph.audit_target_plans
    )
    assert document["next_action"] == (
        "run `echelon re deepen --to L3 --source api "
        f"--domain {context.semantic_graph.manifest.selection.domain_keys[0]} "
        "--from-run re-parent`"
    )
    assert "preflight: failed after 1/2 target(s)" in human
    assert "2701823 bytes exceeds 196608" in human
    assert "provider calls made by preflight: 0" in human


@pytest.mark.unit
def test_paused_l3_status_prints_copy_pasteable_absolute_ceiling_command(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    _accept_every_prerequisite(context)
    context.event_store.append(
        "run_paused",
        {
            "reason": "next dispatch exceeds resource authorization",
            "reason_code": "budget_authorization_required",
        },
        occurred_at=context.clock(),
    )
    authority = _authority(context.paths.root.parent, context)
    catalog = authority.inputs.executor_contract
    inputs = replace(
        authority.inputs,
        executor_contract=replace(
            catalog,
            semantic_entries=tuple(
                replace(
                    entry,
                    limits=replace(
                        entry.limits,
                        max_active_ms_per_dispatch=43_200_000,
                    ),
                )
                for entry in catalog.semantic_entries
            ),
        ),
    )
    document = _document(replace(authority, inputs=inputs))
    human = _render_human(document)

    assert document["next_action"] == (
        "run `echelon re continue re-l3-child --re-time-limit-minutes 780 "
        "--re-semantic-token-limit 1286432 "
        "--re-semantic-time-limit-minutes 750`"
    )
    assert document["authorization_required"] == {
        "run_wide": {"active_ms": 43_200_000},
        "semantic": {"tokens": 786_432, "active_ms": 43_200_000},
    }
    assert document["authorization_recommended"] == {
        "run_wide": {"active_ms": 46_800_000},
        "semantic": {"tokens": 1_286_432, "active_ms": 45_000_000},
    }
    assert "authorization required (absolute totals):" in human
    assert "run active time=720 min (currently 60)" in human
    assert "semantic active time=720 min (currently 30)" in human
    assert "recommended continuation ceiling:" in human
    assert "run active time=780 min" in human
    assert "semantic tokens=1286432" in human
    assert "semantic active time=750 min" in human


@pytest.mark.unit
def test_paused_l3_status_surfaces_latest_provider_failure(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_25 import status as status_module

    context = _context(tmp_path)
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    empty_hash = content_digest(b"")
    capture = ExecutionCaptureV1(
        schema_version=1,
        dispatch_id="dispatch-auth-failure",
        work_item_id="sha256:" + "1" * 64,
        execution_input_hash="sha256:" + "2" * 64,
        executor_contract_hash="sha256:" + "3" * 64,
        execution_mode="cli",
        result_kind="provider_candidate",
        candidate_inventory_hash="sha256:" + "4" * 64,
        deterministic_artifact_hash=None,
        stdout_digest=empty_hash,
        stdout_blob_hash=empty_hash,
        stdout_byte_count=0,
        stdout_retained_byte_count=0,
        stdout_capture="complete",
        stderr_digest="sha256:" + "5" * 64,
        provider_usage_blob_hash=None,
        started_at="2026-09-01T07:41:20Z",
        ended_at="2026-09-01T07:41:22Z",
        duration_ms=2_352,
        exit_code=1,
        timed_out=False,
        output_truncated=False,
        provider_name="claude",
        resolved_model_revision="synthetic",
    )
    capture_hash = context.object_store.put_blob(
        canonical_json_bytes(capture.to_json_dict())
    )
    events = (
        SimpleNamespace(
            type="dispatch_observed",
            payload={"execution_capture_hash": capture_hash},
        ),
    )

    failure = status_module._latest_provider_failure(
        events,
        context.object_store,
        required_provider="codex",
    )
    assert failure == {
        "dispatch_id": "dispatch-auth-failure",
        "exit_code": 1,
        "provider": "claude",
        "provider_contract_mismatch": True,
        "reason": "nonzero_exit",
        "required_provider": "codex",
        "timed_out": False,
        "work_item_id": "sha256:" + "1" * 64,
    }

    authority = _authority(context.paths.root.parent, context)
    document = _document(authority)
    document["last_provider_failure"] = failure
    human = _render_human(document)
    assert (
        "last provider failure: claude CLI exited with code 1; "
        "frozen run provider is codex" in human
    )
    assert "configure/authenticate codex before retrying" in human

    successful_capture = replace(
        capture,
        dispatch_id="dispatch-codex-success",
        exit_code=0,
        provider_name="codex",
        stderr_digest=None,
    )
    successful_hash = context.object_store.put_blob(
        canonical_json_bytes(successful_capture.to_json_dict())
    )
    later_success = SimpleNamespace(
        type="dispatch_observed",
        payload={"execution_capture_hash": successful_hash},
    )
    assert status_module._latest_provider_failure(
        (*events, later_success),
        context.object_store,
        required_provider="codex",
    ) is None
