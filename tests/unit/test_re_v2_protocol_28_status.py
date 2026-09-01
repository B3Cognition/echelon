from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from harness.re_v2.protocol_28.lifecycle import (
    create_or_reuse_protocol_28_child,
    run_protocol_28_exhaustive,
)
from tests.unit.test_re_v2_protocol_28_inputs import _fixture
from tests.unit.test_re_v2_protocol_28_lifecycle import _PassingBackend
from tests.unit.test_re_v2_protocol_28_lifecycle import (
    _AlwaysMalformedProducerBackend,
    _MalformedFirstProducerBackend,
    _RepairThenPassBackend,
)


@pytest.mark.unit
def test_terminal_failed_slice_status_does_not_recommend_continue(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_28.status import protocol_28_status_document

    manifest, inputs = _fixture("re-l4-status-terminal-failure")
    inputs = replace(
        inputs,
        manifest=replace(
            manifest,
            budget_policy=replace(
                manifest.budget_policy, active_ms_limit=1_200_000
            ),
        ),
    )
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    run_protocol_28_exhaustive(
        run_dir, lambda: _AlwaysMalformedProducerBackend()
    )

    document = protocol_28_status_document(run_dir)

    assert "cannot continue" in document["next_action"]
    assert "new L4 child" in document["next_action"]


class _ContextPassingBackend:
    def execute(self, role, _agent, context, _schema, _reservation):  # type: ignore[no-untyped-def]
        from harness.re_v2.canonical import canonical_json_bytes
        from harness.re_v2.protocol_28.artifacts import (
            EvidenceAnchorV1,
            ExhaustiveEvidenceSliceV1,
            ExhaustiveObservationV1,
            ExhaustiveVerificationV1,
        )
        from harness.re_v2.protocol_28.lifecycle import L4DispatchResultV1

        payload = json.loads(context)
        entry = payload["plan_entry"]
        spec = payload["slice_spec"]
        if role == "producer":
            evidence_by_id = {
                _identity(item): item
                for item in payload["snapshot_evidence"]
            }
            anchors = []
            for evidence_id in entry["primary_snapshot_evidence_ids"]:
                item = evidence_by_id[evidence_id]
                anchors.append(
                    EvidenceAnchorV1(
                        1,
                        evidence_id,
                        item["source_id"],
                        item["source_relative_path"],
                        item.get("byte_start", 0),
                        item.get("byte_end", item.get("byte_count", 0)),
                        item.get("raw_hash", item["file_content_hash"]),
                    )
                )
            candidate = ExhaustiveEvidenceSliceV1(
                1,
                _identity(spec),
                _identity(entry),
                entry["target_kind"],
                entry["source_id"],
                entry["target_id"],
                entry["category_id"],
                tuple(entry["primary_subject_ids"]),
                tuple(entry["primary_source_record_ids"]),
                tuple(entry["primary_snapshot_evidence_ids"]),
                tuple(sorted(anchors, key=lambda item: item.identity)),
                (),
                (
                    ExhaustiveObservationV1(
                        1,
                        "applicable",
                        entry["category_id"],
                        tuple(entry["primary_subject_ids"]),
                        tuple(entry["primary_snapshot_evidence_ids"]),
                        tuple(entry["assigned_finding_ids"]),
                        "Exact planned evidence was reviewed.",
                    ),
                ),
                tuple(entry["assigned_finding_ids"]),
                (),
                "# Exhaustive evidence\n\nExact planned evidence was reviewed.\n",
            )
            value = candidate.to_json_dict()
        else:
            candidate = ExhaustiveEvidenceSliceV1.from_json_dict(payload["candidate"])
            value = ExhaustiveVerificationV1(
                1,
                _identity(spec),
                candidate.identity,
                entry["verifier_contract_hash"],
                "PASS",
                (),
                candidate.covered_primary_evidence_ids,
                candidate.addressed_finding_ids,
            ).to_json_dict()
        return L4DispatchResultV1(
            canonical_json_bytes(value),
            "test-provider",
            "test-model",
            "2026-08-31T12:00:00Z",
            "2026-08-31T12:00:01Z",
            1000,
            token_status="trusted_exact",
            billable_tokens=5,
            active_status="trusted_exact",
            active_ms=1000,
        )


def _identity(value: object) -> str:
    from harness.re_v2.canonical import content_digest

    return content_digest(value)


@pytest.mark.unit
def test_planned_status_is_manifest_first_and_ends_in_blocked_banner(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_28.status import render_protocol_28_status

    _manifest, inputs = _fixture("re-l4-status-planned")
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)

    output = render_protocol_28_status(run_dir)

    assert output.startswith("RE V2 — PROTOCOL 2.8\n")
    assert "protocol: 2.8" in output
    assert "planned slices: 1" in output
    assert "workspace synthesis: not run" in output
    assert output.rstrip().endswith(
        "L4 BLOCKED — REQUESTED EVIDENCE INCOMPLETE"
    )


@pytest.mark.unit
def test_complete_selected_scope_status_reports_usage_and_final_banner(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_28.context import load_protocol_28_run_context
    from harness.re_v2.protocol_28.materialization import materialize_l4_closure
    from harness.re_v2.protocol_28.status import (
        protocol_28_status_document,
        render_protocol_28_status,
    )

    _manifest, inputs = _fixture("re-l4-status-complete")
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    result = run_protocol_28_exhaustive(run_dir, lambda: _PassingBackend())
    context = load_protocol_28_run_context(run_dir)
    materialize_l4_closure(context)
    context.controller.complete_run(result.run_root_id, closure_required=False)

    document = protocol_28_status_document(run_dir)
    output = render_protocol_28_status(run_dir)

    assert document["engine_protocol_version"] == "2.8"
    assert document["slice_counts"]["accepted"] == 1
    assert document["slice_counts"]["generated"] == 1
    assert document["slice_counts"]["verified"] == 1
    assert document["dispatch_counts"] == {
        "producer": 1,
        "verifier": 1,
        "avoided_dispatches": 0,
    }
    assert document["targets"][0]["accepted"] == 1
    assert document["resources"]["charged_tokens"] == 10
    assert document["resources"]["avoided_tokens"] == 0
    assert document["post_l4"]["synthesis"] == "not run"
    assert document["next_action"].startswith("deepen remaining")
    assert output.rstrip().endswith("L4 SELECTED SCOPE COMPLETE")


@pytest.mark.unit
def test_durable_root_without_materialized_completion_does_not_overclaim(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_28.status import render_protocol_28_status

    _manifest, inputs = _fixture("re-l4-status-evidence-only")
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    run_protocol_28_exhaustive(run_dir, lambda: _PassingBackend())

    assert render_protocol_28_status(run_dir).rstrip().endswith(
        "L4 BLOCKED — REQUESTED EVIDENCE INCOMPLETE"
    )


@pytest.mark.unit
def test_status_json_contains_same_banner_and_no_quality_overclaim(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_28.status import render_protocol_28_status

    _manifest, inputs = _fixture("re-l4-status-json")
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)

    document = json.loads(render_protocol_28_status(run_dir, as_json=True))

    assert document["banner"] == "L4 BLOCKED — REQUESTED EVIDENCE INCOMPLETE"
    assert document["reason_code"] == "requested_evidence_incomplete"
    assert "full quality" not in json.dumps(document).lower()
    assert "published complete" not in json.dumps(document).lower()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("backend", "expected_repaired", "expected_rejected"),
    (
        (_RepairThenPassBackend, 1, 0),
        (_MalformedFirstProducerBackend, 0, 1),
    ),
)
def test_status_separates_repairs_from_historical_contract_rejections(
    tmp_path: Path,
    backend,
    expected_repaired: int,
    expected_rejected: int,
) -> None:  # type: ignore[no-untyped-def]
    from harness.re_v2.protocol_28.status import protocol_28_status_document

    _manifest, inputs = _fixture(
        f"re-l4-status-history-{expected_repaired}-{expected_rejected}"
    )
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    run_protocol_28_exhaustive(run_dir, backend)

    document = protocol_28_status_document(run_dir)

    assert document["slice_counts"]["repaired"] == expected_repaired
    assert document["historical_rejected_attempts"] == expected_rejected


@pytest.mark.unit
def test_all_scope_completion_requires_later_synthesis(tmp_path: Path) -> None:
    from harness.re_v2.protocol_24.model import SelectionScopeV1
    from harness.re_v2.protocol_28.lifecycle import (
        create_or_reuse_protocol_28_child,
        run_protocol_28_exhaustive,
    )
    from harness.re_v2.protocol_28.materialization import materialize_l4_closure
    from harness.re_v2.protocol_28.preparation import prepare_protocol_28_request
    from harness.re_v2.protocol_28.context import load_protocol_28_run_context
    from harness.re_v2.protocol_28.status import protocol_28_status_document
    from tests.unit.test_re_v2_protocol_28_preparation import _preparation_fixture

    workspace, intent, parent, options = _preparation_fixture(tmp_path)
    options = replace(
        options,
        token_limit=10_000_000,
        active_ms_limit=10_000_000,
    )
    selection = SelectionScopeV1(1, True, (), ())
    intent = replace(intent, selection=selection)
    parent = replace(parent, selection_id=selection.identity)
    inputs = prepare_protocol_28_request(workspace, intent, parent, options)
    run_dir = create_or_reuse_protocol_28_child(workspace, inputs)
    result = run_protocol_28_exhaustive(run_dir, lambda: _ContextPassingBackend())
    context = load_protocol_28_run_context(run_dir)
    materialize_l4_closure(context)
    assert result.run_root_id is not None
    context.controller.complete_run(result.run_root_id, closure_required=False)

    document = protocol_28_status_document(run_dir)

    assert document["selection"]["scope"] == "all-scope"
    assert document["reason_code"] == "all_scope_synthesis_required"
    assert document["banner"] == (
        "L4 ALL-SCOPE EVIDENCE COMPLETE — SYNTHESIS REQUIRED"
    )


@pytest.mark.unit
def test_shared_status_router_uses_manifest_protocol_not_old_header(
    tmp_path: Path,
) -> None:
    from harness.re_v2.status import render_v2_status

    _manifest, inputs = _fixture("re-l4-status-router")
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)

    output = render_v2_status(run_dir)

    assert output.startswith("RE V2 — PROTOCOL 2.8\n")
    assert "PROTOCOL 2.4" not in output


@pytest.mark.unit
@pytest.mark.parametrize(
    ("setup", "banner"),
    (
        ("l3-resource", "L4 PENDING — L3 PREREQUISITE RESOURCE BLOCKED"),
        ("l3-ineligible", "L4 NOT STARTED — L3 PREREQUISITE INELIGIBLE"),
        ("pre-activation", "L4 NOT STARTED — PRE-ACTIVATION BLOCKED"),
        ("closure", "L4 EVIDENCE COMPLETE — CLOSURE INTEGRITY BLOCKED"),
    ),
)
def test_orchestration_status_uses_exact_pre_child_banner(
    tmp_path: Path,
    setup: str,
    banner: str,
) -> None:
    from harness.re_v2.protocol_28.orchestration import (
        DeepenOrchestrationController,
        create_or_load_orchestration,
    )
    from harness.re_v2.protocol_28.status import (
        render_protocol_28_orchestration_status,
    )
    from tests.unit.test_re_v2_protocol_28_orchestration import NOW, _request
    from tests.re_v2_protocol_28_fixtures import digest

    intent = create_or_load_orchestration(tmp_path, _request(), clock=lambda: NOW)
    controller = DeepenOrchestrationController(intent, clock=lambda: NOW)
    controller.bind_l3_child("re-l3", digest("l3-manifest"))
    if setup.startswith("l3-"):
        controller.block(
            "l3",
            "l3_prerequisite_resource_blocked"
            if setup == "l3-resource"
            else "l3_prerequisite_ineligible",
        )
    else:
        controller.satisfy_l3("re-l3", digest("l3-terminal"))
        if setup == "pre-activation":
            controller.block("l4", "snapshot_authority_unavailable")
        else:
            controller.bind_l4_child("re-l4", digest("l4-manifest"))
            controller.complete_l4(
                "re-l4", digest("l4-terminal"), closure_required=True
            )
            controller.block("closure", "closure_authority_mismatch")

    output = render_protocol_28_orchestration_status(intent.paths.root)

    assert output.rstrip().endswith(banner)
