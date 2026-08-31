from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.events import EventStore, ReV2EventError
from harness.re_v2.protocol_28.events import (
    PROTOCOL_28_EVENTS,
    Protocol28ReplayState,
    project_protocol_28,
)
from tests.re_v2_protocol_28_fixtures import digest


NOW = "2026-08-31T12:00:00Z"


def _store(tmp_path: Path) -> EventStore:
    return EventStore(tmp_path / "events.jsonl", protocol=PROTOCOL_28_EVENTS)


def _activate(store: EventStore, *, plan_entries: tuple[str, ...] = ()) -> None:
    store.append(
        "l4_run_created", {"run_manifest_id": digest("manifest")}, occurred_at=NOW
    )
    store.append(
        "l4_inputs_staged",
        {
            "coverage_proof_id": digest("coverage"),
            "exhaustive_plan_id": digest("plan"),
            "parent_authority_bundle_id": digest("parent"),
            "snapshot_evidence_catalog_id": digest("evidence"),
            "target_projection_catalog_id": digest("projections"),
        },
        occurred_at=NOW,
    )
    store.append(
        "l4_activated",
        {
            "activation_id": digest("activation"),
            "planned_entry_ids": list(plan_entries),
        },
        occurred_at=NOW,
    )


def _accept_one(store: EventStore) -> tuple[str, str, str]:
    plan_entry_id = digest("entry")
    slice_spec_id = digest("slice")
    output_key_id = digest("output")
    _activate(store, plan_entries=(plan_entry_id,))
    store.append(
        "slice_realized",
        {
            "output_artifact_key_id": output_key_id,
            "plan_entry_id": plan_entry_id,
            "slice_spec_id": slice_spec_id,
        },
        occurred_at=NOW,
    )
    store.append(
        "certification_recorded",
        {
            "certification_receipt_id": digest("certification"),
            "output_artifact_key_id": output_key_id,
            "slice_spec_id": slice_spec_id,
        },
        occurred_at=NOW,
    )
    store.append(
        "acceptance_recorded",
        {
            "acceptance_receipt_id": digest("acceptance"),
            "certification_receipt_id": digest("certification"),
            "output_artifact_key_id": output_key_id,
            "slice_spec_id": slice_spec_id,
        },
        occurred_at=NOW,
    )
    store.append(
        "accepted_slice_recorded",
        {
            "accepted_slice_id": digest("accepted"),
            "acceptance_receipt_id": digest("acceptance"),
            "output_artifact_key_id": output_key_id,
            "slice_spec_id": slice_spec_id,
        },
        occurred_at=NOW,
    )
    return plan_entry_id, output_key_id, digest("accepted")


@pytest.mark.unit
def test_event_protocol_is_closed_and_content_free(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ReV2EventError, match="unknown fields"):
        store.append(
            "l4_run_created",
            {
                "run_manifest_id": digest("manifest"),
                "source_excerpt": "secret source text",
            },
            occurred_at=NOW,
        )
    with pytest.raises(ReV2EventError, match="unknown protocol-2.8 event"):
        store.append("invented", {}, occurred_at=NOW)


@pytest.mark.unit
def test_captured_verifier_contract_failure_closes_dispatch(tmp_path: Path) -> None:
    store = _store(tmp_path)
    entry_id = digest("entry")
    slice_id = digest("slice")
    output_id = digest("output")
    _activate(store, plan_entries=(entry_id,))
    store.append(
        "slice_realized",
        {
            "output_artifact_key_id": output_id,
            "plan_entry_id": entry_id,
            "slice_spec_id": slice_id,
        },
        occurred_at=NOW,
    )
    store.append(
        "dispatch_reserved",
        {
            "dispatch_id": "verifier-1",
            "output_artifact_key_id": output_id,
            "reservation_id": digest("reservation"),
            "role": "verifier",
        },
        occurred_at=NOW,
    )
    store.append(
        "dispatch_leased",
        {
            "dispatch_id": "verifier-1",
            "lease_id": digest("lease"),
            "owner_id": "controller",
            "role": "verifier",
        },
        occurred_at=NOW,
    )
    store.append(
        "provider_started",
        {"dispatch_id": "verifier-1", "role": "verifier"},
        occurred_at=NOW,
    )
    store.append(
        "provider_capture_recorded",
        {
            "dispatch_id": "verifier-1",
            "execution_capture_id": digest("capture"),
            "raw_result_id": digest("raw"),
            "role": "verifier",
        },
        occurred_at=NOW,
    )
    store.append(
        "verification_rejected",
        {
            "dispatch_id": "verifier-1",
            "output_artifact_key_id": output_id,
            "reason_code": "malformed-result-contract",
        },
        occurred_at=NOW,
    )

    projection = project_protocol_28(store.replay())

    assert projection.active_dispatch_ids == ()


@pytest.mark.unit
def test_replay_enforces_exact_root_order_and_terminal_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _plan_entry, output_key_id, accepted_id = _accept_one(store)
    target_root_id = digest("target-root")
    source_root_id = digest("source-root")
    run_root_id = digest("run-root")
    store.append(
        "root_recorded",
        {
            "required_accepted_slice_ids": [accepted_id],
            "required_root_ids": [],
            "root_id": target_root_id,
            "root_kind": "target",
        },
        occurred_at=NOW,
    )
    store.append(
        "root_recorded",
        {
            "required_accepted_slice_ids": [],
            "required_root_ids": [target_root_id],
            "root_id": source_root_id,
            "root_kind": "source",
        },
        occurred_at=NOW,
    )
    store.append(
        "root_recorded",
        {
            "required_accepted_slice_ids": [accepted_id],
            "required_root_ids": sorted((source_root_id, target_root_id)),
            "root_id": run_root_id,
            "root_kind": "run",
        },
        occurred_at=NOW,
    )
    store.append(
        "materialization_completed",
        {"root_id": run_root_id},
        occurred_at=NOW,
    )
    store.append(
        "run_completed",
        {"completion_kind": "evidence_only", "run_root_id": run_root_id},
        occurred_at=NOW,
    )

    projection = project_protocol_28(store.replay())

    assert projection.lifecycle_state == "complete"
    assert projection.accepted_output_artifact_key_ids == (output_key_id,)
    assert projection.run_root_id == run_root_id
    assert projection.materialized_root_ids == (run_root_id,)


@pytest.mark.unit
def test_run_root_is_rejected_before_exact_slice_closure(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _activate(store, plan_entries=(digest("entry"),))

    with pytest.raises(ReV2EventError, match="exact accepted slice closure"):
        store.append(
            "root_recorded",
            {
                "required_accepted_slice_ids": [],
                "required_root_ids": [],
                "root_id": digest("run-root"),
                "root_kind": "run",
            },
            occurred_at=NOW,
        )


@pytest.mark.unit
def test_event_and_projection_replay_are_byte_deterministic(tmp_path: Path) -> None:
    first = _store(tmp_path / "first")
    second = _store(tmp_path / "second")
    for root in (tmp_path / "first", tmp_path / "second"):
        root.mkdir()
    _activate(first)
    _activate(second)

    first_projection = project_protocol_28(first.replay())
    second_projection = project_protocol_28(second.replay())

    assert first.path.read_bytes() == second.path.read_bytes()
    assert first_projection.to_json_dict() == second_projection.to_json_dict()
    assert isinstance(PROTOCOL_28_EVENTS.new_state(), Protocol28ReplayState)
