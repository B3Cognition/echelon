from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.events import EventStore, ReV2EventError, validate_event_history
from harness.re_v2.protocol_22.budget import evaluate_budget_v22
from harness.re_v2.protocol_22.events import PROTOCOL_22_EVENTS
from harness.re_v2.protocol_22.model import BudgetPolicyV2
from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS
from tests.re_v2_protocol_22_fixtures import digest


NOW = "2026-08-24T10:00:00Z"
WORK = digest("imported-work")


def _store(tmp_path: Path) -> EventStore:
    return EventStore(tmp_path / "events.jsonl", protocol=PROTOCOL_24_EVENTS)


def _start_run(store: EventStore) -> None:
    store.append(
        "run_created",
        {"run_manifest_id": digest("child-run")},
        occurred_at=NOW,
    )


def _adoption_payload(*, work_item_id: str = WORK) -> dict[str, object]:
    return {
        "adopted_artifact_authority": {
            "artifact_acceptance_receipt_id": digest("acceptance"),
            "artifact_hash": digest("artifact"),
            "artifact_key_id": digest("artifact-key"),
            "candidate_assessment_id": None,
            "certification_receipt_id": digest("certification"),
            "dependency_hashes": [],
            "schema_version": 1,
            "source_ledger_entry_hash": digest("parent-ledger-entry"),
            "source_run_id": "re-parent-001",
        },
        "parent_authority_bundle_hash": digest("parent-bundle"),
        "work_item_id": work_item_id,
    }


@pytest.mark.unit
def test_artifact_adopted_has_exact_canonical_payload(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _start_run(store)
    payload = _adoption_payload()

    event = store.append("artifact_adopted", payload, occurred_at=NOW)

    assert canonical_json_bytes(event.to_json_dict()["payload"]) == canonical_json_bytes(
        payload
    )
    assert store.replay()[-1] == event


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.pop("parent_authority_bundle_hash"), "missing fields"),
        (lambda value: value.__setitem__("surprise", True), "unknown fields"),
        (
            lambda value: value.__setitem__(
                "parent_authority_bundle_hash", "not-a-digest"
            ),
            "lowercase sha256 digest",
        ),
    ],
)
def test_artifact_adopted_rejects_nonexact_payload(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    store = _store(tmp_path)
    _start_run(store)
    payload = _adoption_payload()
    mutation(payload)  # type: ignore[operator]

    with pytest.raises(ReV2EventError, match=message):
        store.append("artifact_adopted", payload, occurred_at=NOW)


@pytest.mark.unit
def test_artifact_adopted_rejects_duplicate_work_or_authority(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _start_run(store)
    store.append("artifact_adopted", _adoption_payload(), occurred_at=NOW)

    with pytest.raises(ReV2EventError, match="already adopted|duplicate"):
        store.append("artifact_adopted", _adoption_payload(), occurred_at=NOW)


@pytest.mark.unit
def test_artifact_adopted_rejects_work_after_dispatch(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _start_run(store)
    store.append(
        "dispatch_leased",
        {"dispatch_id": "dispatch-1", "work_item_id": WORK},
        occurred_at=NOW,
    )

    with pytest.raises(ReV2EventError, match="dispatch|lease"):
        store.append("artifact_adopted", _adoption_payload(), occurred_at=NOW)


@pytest.mark.unit
def test_artifact_adopted_cannot_follow_terminal_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _start_run(store)
    store.append(
        "run_completed",
        {"reason": "selected L2 closure accepted"},
        occurred_at=NOW,
    )

    with pytest.raises(ReV2EventError, match="after terminal"):
        store.append("artifact_adopted", _adoption_payload(), occurred_at=NOW)


@pytest.mark.unit
def test_protocol_22_rejects_protocol_24_adoption_history(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _start_run(store)
    store.append("artifact_adopted", _adoption_payload(), occurred_at=NOW)

    with pytest.raises(ReV2EventError, match="unknown protocol-2.2 event"):
        validate_event_history(store.replay(), protocol=PROTOCOL_22_EVENTS)


@pytest.mark.unit
def test_budget_replay_ignores_adoption_with_explicit_or_inferred_protocol(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _start_run(store)
    store.append("artifact_adopted", _adoption_payload(), occurred_at=NOW)
    policy = BudgetPolicyV2.for_goal(
        "selective-deepening",
        token_limit=1_000,
        active_ms_limit=1_000,
    )

    explicit = evaluate_budget_v22(
        policy,
        store.replay(),
        (),
        NOW,
        event_protocol=PROTOCOL_24_EVENTS,
    )
    inferred = evaluate_budget_v22(policy, store.replay(), (), NOW)

    assert explicit == inferred
    assert explicit.charged_tokens == 0
    assert explicit.terminal_work_item_ids == frozenset({WORK})
