from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.events import EventStore, ReV2EventError
from tests.re_v2_protocol_27_fixtures import digest
from tests.unit.test_re_v2_protocol_27_context import _source_item, _validated_inputs


NOW = "2026-08-29T08:00:00Z"


def _event_store(tmp_path: Path):
    from harness.re_v2.protocol_27.events import PROTOCOL_27_EVENTS

    inputs = _validated_inputs(tmp_path)
    store = EventStore(inputs.paths, protocol=PROTOCOL_27_EVENTS)
    store.append(
        "run_created",
        {"run_manifest_id": inputs.manifest.run_manifest_id},
        occurred_at=NOW,
    )
    store.append(
        "synthesis_request_frozen",
        {"request_id": inputs.manifest.request_id},
        occurred_at=NOW,
    )
    for receipt in inputs.manifest.partial_acceptances:
        store.append(
            "partial_source_accepted",
            {
                "receipt_id": receipt.receipt_id,
                "request_id": receipt.operation_id,
                "source_id": receipt.source_id,
            },
            occurred_at=NOW,
        )
    return inputs, store


def _planned_source(tmp_path: Path):
    inputs, store = _event_store(tmp_path)
    item = _source_item(inputs)
    store.append(
        "work_planned",
        {"work_item_ids": [item.work_item_id]},
        occurred_at=NOW,
    )
    return inputs, item, store


def append_dispatch_cycle(store: EventStore, item, index: int, kind: str) -> str:
    dispatch_id = f"dispatch-{index}"
    store.append(
        "dispatch_started",
        {
            "active_ms_reservation": 100,
            "attempt_index": index,
            "attempt_kind": kind,
            "billable_token_reservation": 1000,
            "dispatch_id": dispatch_id,
            "execution_input_hash": digest(f"execution-{index}"),
            "executor_contract_hash": item.executor_contract_hash,
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    return dispatch_id


def append_generated_acceptance(
    store: EventStore,
    item,
    *,
    index: int = 1,
    generated_dependency_key_ids: tuple[str, ...] = (),
) -> tuple[str, str]:
    dispatch_id = append_dispatch_cycle(store, item, index, "initial_generation")
    capture_id = digest(f"capture-{index}")
    candidate_id = digest(f"candidate-{index}")
    certification_id = digest(f"certification-{index}")
    artifact_hash = digest(f"artifact-{index}")
    store.append(
        "dispatch_observed",
        {
            "active_usage_status": "trusted_exact",
            "dispatch_id": dispatch_id,
            "execution_capture_hash": capture_id,
            "observed_active_ms": 25,
            "raw_result_contract_status": "valid",
            "reported_token_usage": 400,
            "token_usage_status": "trusted_exact",
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    store.append(
        "candidate_persisted",
        {
            "candidate_id": candidate_id,
            "candidate_inventory_hash": digest(f"inventory-{index}"),
            "dispatch_id": dispatch_id,
            "execution_capture_hash": capture_id,
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    store.append(
        "synthesis_candidate_certified",
        {
            "artifact_hash": artifact_hash,
            "artifact_key_id": item.output_key.artifact_key_id,
            "candidate_assessment_id": digest(f"assessment-{index}"),
            "candidate_id": candidate_id,
            "certification_id": certification_id,
            "generated_dependency_key_ids": list(generated_dependency_key_ids),
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    store.append(
        "synthesis_artifact_accepted",
        {
            "acceptance_receipt_id": digest(f"acceptance-{index}"),
            "adopted": False,
            "artifact_hash": artifact_hash,
            "artifact_key_id": item.output_key.artifact_key_id,
            "certification_id": certification_id,
            "generated_dependency_key_ids": list(generated_dependency_key_ids),
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    return item.output_key.artifact_key_id, artifact_hash


@pytest.mark.unit
def test_artifact_acceptance_requires_certification_and_dependencies(
    tmp_path: Path,
) -> None:
    _inputs, item, store = _planned_source(tmp_path)

    with pytest.raises(ReV2EventError, match="certification"):
        store.append(
            "synthesis_artifact_accepted",
            {
                "acceptance_receipt_id": digest("acceptance"),
                "adopted": False,
                "artifact_hash": digest("artifact"),
                "artifact_key_id": item.output_key.artifact_key_id,
                "certification_id": digest("certification"),
                "generated_dependency_key_ids": [],
                "work_item_id": item.work_item_id,
            },
            occurred_at=NOW,
        )


@pytest.mark.unit
def test_materialization_requires_root_and_publication_requires_materialization(
    tmp_path: Path,
) -> None:
    _inputs, _item, store = _planned_source(tmp_path)

    with pytest.raises(ReV2EventError, match="root"):
        store.append(
            "synthesis_materialized",
            {
                "materialization_manifest_id": digest("materialization"),
                "synthesis_root_id": digest("root"),
            },
            occurred_at=NOW,
        )
    with pytest.raises(ReV2EventError, match="materialization"):
        store.append(
            "synthesis_published",
            {
                "materialization_manifest_id": digest("materialization"),
                "publication_descriptor_id": digest("publication"),
                "synthesis_root_id": digest("root"),
            },
            occurred_at=NOW,
        )


@pytest.mark.unit
def test_request_must_precede_partial_acceptance(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.events import PROTOCOL_27_EVENTS

    inputs = _validated_inputs(tmp_path)
    store = EventStore(inputs.paths, protocol=PROTOCOL_27_EVENTS)
    store.append(
        "run_created",
        {"run_manifest_id": inputs.manifest.run_manifest_id},
        occurred_at=NOW,
    )
    receipt = inputs.manifest.partial_acceptances[0]

    with pytest.raises(ReV2EventError, match="request"):
        store.append(
            "partial_source_accepted",
            {
                "receipt_id": receipt.receipt_id,
                "request_id": receipt.operation_id,
                "source_id": receipt.source_id,
            },
            occurred_at=NOW,
        )


@pytest.mark.unit
def test_event_payloads_are_closed(tmp_path: Path) -> None:
    _inputs, item, store = _planned_source(tmp_path)

    with pytest.raises(ReV2EventError, match="unknown fields"):
        store.append(
            "checkpoint_adopted",
            {
                "acceptance_receipt_id": digest("acceptance"),
                "adoption_receipt_id": digest("adoption"),
                "artifact_hash": digest("artifact"),
                "artifact_key_id": item.output_key.artifact_key_id,
                "certification_id": digest("certification"),
                "extra": True,
                "work_item_id": item.work_item_id,
            },
            occurred_at=NOW,
        )


@pytest.mark.unit
def test_complete_synthesis_event_order_replays_to_publication(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.events import Protocol27ReplayState

    _inputs, item, store = _planned_source(tmp_path)
    artifact_key_id, _artifact_hash = append_generated_acceptance(store, item)
    root_id = digest("root")
    materialization_id = digest("materialization")
    store.append(
        "synthesis_root_accepted",
        {
            "required_artifact_key_ids": [artifact_key_id],
            "synthesis_root_id": root_id,
        },
        occurred_at=NOW,
    )
    store.append(
        "synthesis_materialized",
        {
            "materialization_manifest_id": materialization_id,
            "synthesis_root_id": root_id,
        },
        occurred_at=NOW,
    )
    store.append(
        "synthesis_published",
        {
            "materialization_manifest_id": materialization_id,
            "publication_descriptor_id": digest("publication"),
            "synthesis_root_id": root_id,
        },
        occurred_at=NOW,
    )
    store.append("run_completed", {"reason": "complete"}, occurred_at=NOW)

    state = Protocol27ReplayState()
    for event in store.replay():
        state.consume(event)

    assert state.terminal is True
    assert state.synthesis_root_id == root_id
    assert state.materialization_manifest_id == materialization_id
    assert state.publication_descriptor_id == digest("publication")
