from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.protocol_28.events import Protocol28ReplayState, _DispatchStateV1
from harness.re_v2.protocol_28.recovery import (
    DurableRootV1,
    ParsedResultSeamV1,
    Protocol28RecoveryError,
    Protocol28RecoveryFactsV1,
    plan_protocol_28_recovery,
)
from tests.re_v2_protocol_28_fixtures import digest


def _active_state(*, stage: str, role: str = "producer") -> Protocol28ReplayState:
    state = Protocol28ReplayState(
        run_manifest_id=digest("manifest"),
        inputs_staged=True,
        activated=True,
        planned_entry_ids=(digest("entry"),),
        realized_by_entry={digest("entry"): (digest("slice"), digest("output"))},
    )
    dispatch = _DispatchStateV1("dispatch-1", role, digest("output"), stage, "owner-1")
    state.dispatches[dispatch.dispatch_id] = dispatch
    return state


def _facts(**changes: object) -> Protocol28RecoveryFactsV1:
    value = Protocol28RecoveryFactsV1(
        schema_version=1,
        snapshot_authority_state="intact",
        live_owner_dispatch_ids=(),
        durable_capture_dispatch_ids=(),
        parsed_results=(),
        durable_object_ids=(),
        candidate_output_ids=(),
        verification_pass_output_ids=(),
        certified_output_ids=(),
        accepted_output_ids=(),
        accepted_slice_output_ids=(),
        checkpoint_exported_output_ids=(),
        durable_roots=(),
        materialized_root_ids=(),
        closure_required=False,
        closure_integrity_valid=True,
        projection_present=True,
    )
    normalized = dict(changes)
    accepted_slices = normalized.get("accepted_slice_output_ids", ())
    accepted = normalized.get("accepted_output_ids", accepted_slices)
    certified = normalized.get("certified_output_ids", accepted)
    verified = normalized.get("verification_pass_output_ids", certified)
    normalized.setdefault("accepted_output_ids", accepted)
    normalized.setdefault("certified_output_ids", certified)
    normalized.setdefault("verification_pass_output_ids", verified)
    return replace(value, **normalized)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("live", "expected"),
    [
        (("dispatch-1",), "wait_for_live_owner"),
        ((), "abandon_dispatch"),
    ],
)
def test_started_provider_is_never_duplicated_and_dead_owner_is_abandoned(
    live: tuple[str, ...], expected: str
) -> None:
    action = plan_protocol_28_recovery(
        _active_state(stage="started"),
        _facts(live_owner_dispatch_ids=live),
    )

    assert action.kind == expected
    assert action.dispatch_id == "dispatch-1"


@pytest.mark.unit
def test_durable_raw_result_is_parsed_before_replacement_dispatch() -> None:
    action = plan_protocol_28_recovery(
        _active_state(stage="started"),
        _facts(durable_capture_dispatch_ids=("dispatch-1",)),
    )

    assert action.kind == "parse_durable_capture"
    assert action.requires_provider_call is False


@pytest.mark.unit
def test_capture_event_without_durable_ledger_capture_is_corruption() -> None:
    with pytest.raises(Protocol28RecoveryError, match="durable execution capture"):
        plan_protocol_28_recovery(
            _active_state(stage="captured"),
            _facts(),
        )


@pytest.mark.unit
def test_parsed_result_is_persisted_then_appended_to_ledger() -> None:
    parsed = ParsedResultSeamV1(
        1, "dispatch-1", "candidate", digest("candidate"), digest("output")
    )
    before_object = plan_protocol_28_recovery(
        _active_state(stage="captured"),
        _facts(
            durable_capture_dispatch_ids=("dispatch-1",),
            parsed_results=(parsed,),
        ),
    )
    after_object = plan_protocol_28_recovery(
        _active_state(stage="captured"),
        _facts(
            durable_capture_dispatch_ids=("dispatch-1",),
            parsed_results=(parsed,),
            durable_object_ids=(parsed.result_object_id,),
        ),
    )

    assert before_object.kind == "persist_parsed_result"
    assert after_object.kind == "append_candidate_receipt"


@pytest.mark.unit
def test_durable_verifier_result_resumes_without_regenerating_candidate() -> None:
    parsed = ParsedResultSeamV1(
        1, "dispatch-1", "verification", digest("verification"), digest("output")
    )

    action = plan_protocol_28_recovery(
        _active_state(stage="captured", role="verifier"),
        _facts(
            durable_capture_dispatch_ids=("dispatch-1",),
            parsed_results=(parsed,),
            durable_object_ids=(parsed.result_object_id,),
        ),
    )

    assert action.kind == "append_verification_receipt"
    assert action.requires_provider_call is False


@pytest.mark.unit
@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        ({"certified_output_ids": (digest("output"),)}, "append_acceptance"),
        ({"accepted_output_ids": (digest("output"),)}, "append_accepted_slice"),
        (
            {"accepted_slice_output_ids": (digest("output"),)},
            "export_checkpoint",
        ),
    ],
)
def test_acceptance_and_checkpoint_crash_seams_are_authority_first(
    facts: dict[str, object], expected: str
) -> None:
    state = Protocol28ReplayState(
        run_manifest_id=digest("manifest"),
        inputs_staged=True,
        activated=True,
        planned_entry_ids=(digest("entry"),),
        realized_by_entry={digest("entry"): (digest("slice"), digest("output"))},
    )
    output_id = digest("output")
    if expected in {"append_acceptance", "append_accepted_slice", "export_checkpoint"}:
        state.certifications[output_id] = (digest("slice"), digest("certification"))
    if expected in {"append_accepted_slice", "export_checkpoint"}:
        state.acceptances[output_id] = (digest("slice"), digest("acceptance"))
    if expected == "export_checkpoint":
        state.accepted_slices[output_id] = digest("accepted")

    action = plan_protocol_28_recovery(state, _facts(**facts))

    assert action.kind == expected
    assert action.output_artifact_key_id == digest("output")


@pytest.mark.unit
def test_root_object_precedes_event_and_materialization() -> None:
    target_root = DurableRootV1(1, digest("target-root"), "target", (), ())
    source_root = DurableRootV1(
        1, digest("source-root"), "source", (), (digest("target-root"),)
    )
    run_root = DurableRootV1(
        1,
        digest("run-root"),
        "run",
        (digest("accepted"),),
        tuple(sorted((digest("source-root"), digest("target-root")))),
    )
    state = Protocol28ReplayState(
        run_manifest_id=digest("manifest"),
        inputs_staged=True,
        activated=True,
        planned_entry_ids=(digest("entry"),),
        realized_by_entry={digest("entry"): (digest("slice"), digest("output"))},
        accepted_slices={digest("output"): digest("accepted")},
        target_root_ids={digest("target-root")},
        source_root_ids={digest("source-root")},
    )
    roots = tuple(
        sorted(
            (target_root, source_root, run_root),
            key=lambda item: (item.root_kind, item.root_id),
        )
    )
    authority_facts = {
        "accepted_slice_output_ids": (digest("output"),),
        "checkpoint_exported_output_ids": (digest("output"),),
        "durable_roots": roots,
    }
    record = plan_protocol_28_recovery(state, _facts(**authority_facts))
    state.run_root_id = run_root.root_id
    materialize = plan_protocol_28_recovery(
        state,
        _facts(**authority_facts),
    )

    assert record.kind == "record_root_event"
    assert materialize.kind == "materialize_root"


@pytest.mark.unit
def test_projection_loss_rebuilds_without_reopening_accepted_work() -> None:
    state = Protocol28ReplayState(
        run_manifest_id=digest("manifest"),
        inputs_staged=True,
        activated=True,
        planned_entry_ids=(digest("entry"),),
        realized_by_entry={digest("entry"): (digest("slice"), digest("output"))},
        accepted_slices={digest("output"): digest("accepted")},
    )

    action = plan_protocol_28_recovery(
        state,
        _facts(
            accepted_slice_output_ids=(digest("output"),),
            checkpoint_exported_output_ids=(digest("output"),),
            projection_present=False,
        ),
    )

    assert action.kind == "rebuild_projection"
    assert action.output_artifact_key_id is None


@pytest.mark.unit
@pytest.mark.parametrize("authority_state", ["mismatched", "missing"])
def test_changed_or_missing_staged_snapshot_is_blocked_without_source_reread(
    authority_state: str,
) -> None:
    action = plan_protocol_28_recovery(
        _active_state(stage="reserved"),
        _facts(snapshot_authority_state=authority_state),
    )

    assert action.kind == "block_snapshot_integrity"
    assert action.requires_provider_call is False
    assert action.reason_code == f"snapshot_authority_{authority_state}"


@pytest.mark.unit
def test_closure_handoff_is_zero_call_and_mismatch_is_integrity_blocked() -> None:
    state = Protocol28ReplayState(
        run_manifest_id=digest("manifest"),
        inputs_staged=True,
        activated=True,
        run_root_id=digest("run-root"),
        materialized_root_ids={digest("run-root")},
    )
    durable_run_root = DurableRootV1(1, digest("run-root"), "run", (), ())
    link = plan_protocol_28_recovery(
        state,
        _facts(
            closure_required=True,
            durable_roots=(durable_run_root,),
            materialized_root_ids=(digest("run-root"),),
        ),
    )
    blocked = plan_protocol_28_recovery(
        state,
        _facts(
            closure_required=True,
            closure_integrity_valid=False,
            durable_roots=(durable_run_root,),
            materialized_root_ids=(digest("run-root"),),
        ),
    )

    assert link.kind == "link_closure_successor"
    assert link.requires_provider_call is False
    assert blocked.kind == "block_closure_integrity"
