from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.events import EventStore, ReV2EventError
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.ledger import Protocol22Ledger
from harness.re_v2.protocol_26.adoption import import_frozen_checkpoint_closure
from harness.re_v2.protocol_26.events import (
    append_missing_checkpoint_events,
    protocol_26_events_for,
)
from harness.re_v2.protocol_26.inputs import (
    create_protocol_26_run_store,
    load_protocol_26_inputs,
)
from tests.re_v2_protocol_22_fixtures import digest
from tests.unit.test_re_v2_protocol_26_inputs import _protocol26_input_fixture


NOW = "2026-08-28T10:00:00Z"


def _store(tmp_path: Path, target_layer: str) -> EventStore:
    return EventStore(
        tmp_path / f"{target_layer}-events.jsonl",
        protocol=protocol_26_events_for(target_layer),
    )


def _start_run(store: EventStore) -> None:
    store.append(
        "run_created",
        {"run_manifest_id": digest("manifest")},
        occurred_at=NOW,
    )


def _checkpoint_payload(
    *,
    work_item_id: str | None = None,
    receipt_id: str | None = None,
) -> dict[str, object]:
    return {
        "adopted_artifact_authority": {
            "artifact_acceptance_receipt_id": receipt_id or digest("acceptance"),
            "artifact_hash": digest(f"artifact:{work_item_id or 'work'}"),
            "artifact_key_id": digest(f"key:{work_item_id or 'work'}"),
            "candidate_assessment_id": None,
            "certification_receipt_id": digest(f"cert:{work_item_id or 'work'}"),
            "dependency_hashes": [],
            "schema_version": 1,
            "source_ledger_entry_hash": digest("origin-ledger"),
            "source_run_id": "re-origin-001",
        },
        "checkpoint_manifest_id": digest(f"checkpoint:{work_item_id or 'work'}"),
        "checkpoint_selection_bundle_id": digest("selection"),
        "origin_run_id": "re-origin-001",
        "selection_reason": "checkpoint_rank_winner",
        "work_item_id": work_item_id or digest("work"),
    }


@pytest.mark.unit
@pytest.mark.parametrize("target_layer", ("L1", "L2", "L3"))
def test_checkpoint_event_delegates_existing_layer_events(
    tmp_path: Path,
    target_layer: str,
) -> None:
    store = _store(tmp_path, target_layer)

    _start_run(store)

    assert store.replay()[0].type == "run_created"


@pytest.mark.unit
def test_checkpoint_adoption_has_exact_canonical_payload(tmp_path: Path) -> None:
    store = _store(tmp_path, "L1")
    _start_run(store)
    payload = _checkpoint_payload()

    event = store.append("checkpoint_artifact_adopted", payload, occurred_at=NOW)

    assert canonical_json_bytes(
        event.to_json_dict()["payload"]
    ) == canonical_json_bytes(payload)
    unexpected = dict(payload)
    unexpected["surprise"] = True
    with pytest.raises(ReV2EventError, match="unknown fields"):
        store.append("checkpoint_artifact_adopted", unexpected, occurred_at=NOW)


@pytest.mark.unit
def test_checkpoint_adoption_must_precede_dispatch(tmp_path: Path) -> None:
    store = _store(tmp_path, "L1")
    _start_run(store)
    work = digest("work")
    store.append(
        "dispatch_leased",
        {"dispatch_id": "dispatch-1", "work_item_id": work},
        occurred_at=NOW,
    )

    with pytest.raises(ReV2EventError, match="precede"):
        store.append(
            "checkpoint_artifact_adopted",
            _checkpoint_payload(work_item_id=work),
            occurred_at=NOW,
        )


@pytest.mark.unit
def test_checkpoint_adoption_rejects_duplicate_receipt(tmp_path: Path) -> None:
    store = _store(tmp_path, "L2")
    _start_run(store)
    receipt = digest("same-receipt")
    store.append(
        "checkpoint_artifact_adopted",
        _checkpoint_payload(work_item_id=digest("work-1"), receipt_id=receipt),
        occurred_at=NOW,
    )

    with pytest.raises(ReV2EventError, match="duplicate acceptance receipt"):
        store.append(
            "checkpoint_artifact_adopted",
            _checkpoint_payload(work_item_id=digest("work-2"), receipt_id=receipt),
            occurred_at=NOW,
        )


@pytest.mark.unit
def test_checkpoint_adoption_is_invalid_during_any_active_dispatch(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, "L3")
    _start_run(store)
    work = digest("other-work")
    store.append(
        "dispatch_leased",
        {"dispatch_id": "dispatch-1", "work_item_id": work},
        occurred_at=NOW,
    )
    store.append(
        "dispatch_started",
        {
            "active_ms_reservation": 1_000,
            "attempt_index": 1,
            "attempt_kind": "initial_generation",
            "billable_token_reservation": 100,
            "dispatch_id": "dispatch-1",
            "execution_input_hash": digest("execution-input"),
            "executor_contract_hash": digest("executor"),
            "work_item_id": work,
        },
        occurred_at=NOW,
    )

    with pytest.raises(ReV2EventError, match="active dispatch"):
        store.append(
            "checkpoint_artifact_adopted",
            _checkpoint_payload(work_item_id=digest("checkpoint-work")),
            occurred_at=NOW,
        )


@pytest.mark.unit
def test_checkpoint_events_require_imported_typed_receipts_and_are_idempotent(
    tmp_path: Path,
) -> None:
    supplied = _protocol26_input_fixture()
    paths = create_protocol_26_run_store(
        tmp_path / "runs" / supplied.manifest.run_id,
        supplied.manifest,
        supplied,
    )
    inputs = load_protocol_26_inputs(paths, supplied.manifest)
    objects = ObjectStore(paths.objects)
    ledger = Protocol22Ledger(paths.ledger, objects)
    events = EventStore(paths, protocol=protocol_26_events_for("L1"))
    events.append(
        "run_created",
        {"run_manifest_id": supplied.manifest.run_manifest_id},
        occurred_at=NOW,
    )

    with pytest.raises(Exception, match="receipt|ledger|import"):
        append_missing_checkpoint_events(inputs, events, ledger, lambda: NOW)

    imported = import_frozen_checkpoint_closure(inputs, objects, ledger)
    first = append_missing_checkpoint_events(inputs, events, ledger, lambda: NOW)
    bytes_after_first = paths.events.read_bytes()
    second = append_missing_checkpoint_events(inputs, events, ledger, lambda: NOW)

    assert first == imported
    assert second == first
    assert paths.events.read_bytes() == bytes_after_first
    assert [event.type for event in events.replay()].count(
        "checkpoint_artifact_adopted"
    ) == len(imported.imports)
