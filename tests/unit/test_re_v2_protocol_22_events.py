from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.events import EventStore, ReV2EventError, validate_event_history
from harness.re_v2.protocol_22.events import PROTOCOL_22_EVENTS
from tests.re_v2_protocol_22_fixtures import digest


NOW = "2026-08-22T10:00:00Z"
WORK = digest("work")


def event_store_v22(tmp_path: Path) -> EventStore:
    return EventStore(tmp_path / "events.jsonl", protocol=PROTOCOL_22_EVENTS)


def _run(store: EventStore) -> None:
    store.append(
        "run_created",
        {"run_manifest_id": digest("run")},
        occurred_at=NOW,
    )


def _start(
    store: EventStore,
    dispatch_id: str,
    *,
    work_item_id: str = WORK,
    kind: str = "initial_generation",
    index: int = 1,
    token_reservation: int = 100,
    active_reservation: int = 1_000,
) -> None:
    store.append(
        "dispatch_leased",
        {"dispatch_id": dispatch_id, "work_item_id": work_item_id},
        occurred_at=NOW,
    )
    store.append(
        "dispatch_started",
        {
            "active_ms_reservation": active_reservation,
            "attempt_index": index,
            "attempt_kind": kind,
            "billable_token_reservation": token_reservation,
            "dispatch_id": dispatch_id,
            "execution_input_hash": digest(f"input:{dispatch_id}"),
            "executor_contract_hash": digest("executor"),
            "work_item_id": work_item_id,
        },
        occurred_at=NOW,
    )


def _observe(
    store: EventStore,
    dispatch_id: str,
    *,
    work_item_id: str = WORK,
    raw_status: str = "valid",
    token_usage: int | None = 25,
    token_status: str = "trusted_exact",
    active_ms: int | None = 250,
    active_status: str = "trusted_exact",
) -> None:
    store.append(
        "dispatch_observed",
        {
            "active_usage_status": active_status,
            "dispatch_id": dispatch_id,
            "execution_capture_hash": digest(f"capture:{dispatch_id}"),
            "observed_active_ms": active_ms,
            "raw_result_contract_status": raw_status,
            "reported_token_usage": token_usage,
            "token_usage_status": token_status,
            "work_item_id": work_item_id,
        },
        occurred_at=NOW,
    )


def _persist(store: EventStore, dispatch_id: str, candidate: str = "candidate") -> str:
    candidate_id = digest(candidate)
    store.append(
        "candidate_persisted",
        {
            "candidate_id": candidate_id,
            "candidate_inventory_hash": digest(f"inventory:{candidate}"),
            "dispatch_id": dispatch_id,
            "execution_capture_hash": digest(f"capture:{dispatch_id}"),
            "work_item_id": WORK,
        },
        occurred_at=NOW,
    )
    return candidate_id


def _certify(store: EventStore, candidate_id: str) -> tuple[str, str]:
    assessment = digest(f"assessment:{candidate_id}")
    certification = digest(f"certification:{candidate_id}")
    store.append(
        "candidate_certified",
        {
            "candidate_assessment_id": assessment,
            "candidate_id": candidate_id,
            "certification_receipt_id": certification,
            "work_item_id": WORK,
        },
        occurred_at=NOW,
    )
    return assessment, certification


def _accept(
    store: EventStore,
    *,
    assessment: str | None,
    certification: str,
) -> None:
    store.append(
        "artifact_accepted",
        {
            "artifact_acceptance_receipt_id": digest("acceptance"),
            "artifact_hash": digest("artifact"),
            "artifact_key_id": digest("artifact-key"),
            "candidate_assessment_id": assessment,
            "certification_receipt_id": certification,
            "work_item_id": WORK,
        },
        occurred_at=NOW,
    )


@pytest.mark.unit
def test_protocol_22_dispatch_started_requires_execution_authority(
    tmp_path: Path,
) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    store.append(
        "dispatch_leased",
        {"dispatch_id": "d1", "work_item_id": WORK},
        occurred_at=NOW,
    )

    with pytest.raises(ReV2EventError, match="execution_input_hash"):
        store.append(
            "dispatch_started",
            {
                "attempt_index": 1,
                "attempt_kind": "initial_generation",
                "dispatch_id": "d1",
                "work_item_id": WORK,
            },
            occurred_at=NOW,
        )


@pytest.mark.unit
def test_legacy_protocol_rejects_protocol_22_dispatch_fields(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "legacy.jsonl")
    _run(store)
    store.append(
        "dispatch_leased",
        {"dispatch_id": "d1", "work_item_id": WORK},
        occurred_at=NOW,
    )

    with pytest.raises(ReV2EventError, match="unknown fields"):
        store.append(
            "dispatch_started",
            {
                "active_ms_reservation": 1_000,
                "attempt_index": 1,
                "attempt_kind": "initial_generation",
                "billable_token_reservation": 100,
                "dispatch_id": "d1",
                "execution_input_hash": digest("input:d1"),
                "executor_contract_hash": digest("executor"),
                "work_item_id": WORK,
            },
            occurred_at=NOW,
        )


@pytest.mark.unit
def test_event_log_replay_uses_explicit_protocol_not_payload_guessing(
    tmp_path: Path,
) -> None:
    protocol_22 = event_store_v22(tmp_path)
    _run(protocol_22)
    _start(protocol_22, "d1")

    legacy = EventStore(protocol_22.path)
    with pytest.raises(ReV2EventError, match="unknown fields"):
        legacy.replay()
    assert protocol_22.replay()[-1].type == "dispatch_started"


@pytest.mark.unit
def test_result_reconstruction_is_ordered_and_closes_result_retry(
    tmp_path: Path,
) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    _start(store, "d1")
    _observe(store, "d1", raw_status="invalid")
    candidate = _persist(store, "d1")

    with pytest.raises(ReV2EventError, match="candidate_persisted|persisted"):
        other = event_store_v22(tmp_path / "other")
        other.path.parent.mkdir()
        _run(other)
        _start(other, "d2")
        _observe(other, "d2", raw_status="invalid")
        other.append(
            "result_contract_reconstructed",
            {
                "candidate_id": digest("missing"),
                "dispatch_id": "d2",
                "result_contract_id": "candidate-ready-v1",
                "work_item_id": WORK,
            },
            occurred_at=NOW,
        )

    store.append(
        "result_contract_reconstructed",
        {
            "candidate_id": candidate,
            "dispatch_id": "d1",
            "result_contract_id": "candidate-ready-v1",
            "work_item_id": WORK,
        },
        occurred_at=NOW,
    )
    assessment, certification = _certify(store, candidate)
    _accept(store, assessment=assessment, certification=certification)

    assert validate_event_history(
        store.replay(), protocol=PROTOCOL_22_EVENTS
    )[-1].type == "artifact_accepted"


@pytest.mark.unit
def test_one_item_cannot_consume_both_retry_kinds(tmp_path: Path) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    _start(store, "d1")
    _observe(store, "d1", raw_status="invalid")
    _start(store, "d2", kind="result_contract_retry")
    _observe(store, "d2")
    candidate = _persist(store, "d2", "retry-candidate")
    store.append(
        "candidate_rejected",
        {
            "candidate_assessment_id": digest("assessment"),
            "candidate_id": candidate,
            "certification_receipt_id": digest("rejected-certification"),
            "work_item_id": WORK,
        },
        occurred_at=NOW,
    )
    store.append(
        "dispatch_leased",
        {"dispatch_id": "d3", "work_item_id": WORK},
        occurred_at=NOW,
    )

    with pytest.raises(ReV2EventError, match="shared retry|both retry"):
        store.append(
            "dispatch_started",
            {
                "active_ms_reservation": 1_000,
                "attempt_index": 1,
                "attempt_kind": "artifact_contract_retry",
                "billable_token_reservation": 100,
                "dispatch_id": "d3",
                "execution_input_hash": digest("input:d3"),
                "executor_contract_hash": digest("executor"),
                "work_item_id": WORK,
            },
            occurred_at=NOW,
        )


@pytest.mark.unit
def test_deterministic_path_forbids_candidates_and_accepts_directly(
    tmp_path: Path,
) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    _start(store, "deterministic", token_reservation=0)
    _observe(
        store,
        "deterministic",
        raw_status="not_applicable",
        token_usage=0,
    )

    with pytest.raises(ReV2EventError, match="deterministic"):
        _persist(store, "deterministic")

    _accept(
        store,
        assessment=None,
        certification=digest("deterministic-certification"),
    )
    assert store.replay()[-1].type == "artifact_accepted"


@pytest.mark.unit
def test_abandonment_closes_dispatch_and_authorizes_only_result_retry(
    tmp_path: Path,
) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    _start(store, "d1")
    store.append(
        "dispatch_abandoned",
        {
            "dispatch_id": "d1",
            "execution_input_hash": digest("input:d1"),
            "executor_contract_hash": digest("executor"),
            "reason_code": "execution_outcome_indeterminate",
            "work_item_id": WORK,
        },
        occurred_at=NOW,
    )
    _start(store, "d2", kind="result_contract_retry")

    with pytest.raises(ReV2EventError, match="started|active"):
        store.append(
            "dispatch_abandoned",
            {
                "dispatch_id": "d1",
                "execution_input_hash": digest("input:d1"),
                "executor_contract_hash": digest("executor"),
                "reason_code": "execution_outcome_indeterminate",
                "work_item_id": WORK,
            },
            occurred_at=NOW,
        )


@pytest.mark.unit
def test_candidate_and_acceptance_events_require_exact_predecessors(
    tmp_path: Path,
) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    _start(store, "d1")
    _observe(store, "d1")
    candidate = digest("candidate")

    with pytest.raises(ReV2EventError, match="persisted"):
        _certify(store, candidate)

    candidate = _persist(store, "d1")
    with pytest.raises(ReV2EventError, match="certified"):
        _accept(
            store,
            assessment=digest("assessment"),
            certification=digest("certification"),
        )

    assessment, certification = _certify(store, candidate)
    with pytest.raises(ReV2EventError, match="candidate assessment|certification"):
        _accept(
            store,
            assessment=digest("wrong-assessment"),
            certification=certification,
        )
    _accept(store, assessment=assessment, certification=certification)


@pytest.mark.unit
def test_work_failure_requires_attempt_authority_but_is_not_run_terminal(
    tmp_path: Path,
) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    failure = {
        "failure_class": "execution_indeterminate",
        "failure_receipt_id": digest("failure"),
        "reason_code": "execution_outcome_indeterminate",
        "work_item_id": WORK,
    }
    with pytest.raises(ReV2EventError, match="attempt|eligible"):
        store.append("work_item_failed", failure, occurred_at=NOW)

    _start(store, "d1", token_reservation=0)
    store.append(
        "dispatch_abandoned",
        {
            "dispatch_id": "d1",
            "execution_input_hash": digest("input:d1"),
            "executor_contract_hash": digest("executor"),
            "reason_code": "execution_outcome_indeterminate",
            "work_item_id": WORK,
        },
        occurred_at=NOW,
    )
    store.append("work_item_failed", failure, occurred_at=NOW)
    store.append(
        "work_planned",
        {"work_item_ids": [digest("independent-work")]},
        occurred_at=NOW,
    )
    assert store.replay()[-1].type == "work_planned"


@pytest.mark.unit
def test_executor_failure_is_unique_and_prevents_trigger_acceptance(
    tmp_path: Path,
) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    payload = {
        "executor_contract_hash": digest("executor"),
        "executor_failure_receipt_id": digest("executor-failure"),
        "trigger_work_item_id": WORK,
    }
    store.append("executor_failed", payload, occurred_at=NOW)

    with pytest.raises(ReV2EventError, match="executor.*already failed|unique"):
        store.append("executor_failed", payload, occurred_at=NOW)

    with pytest.raises(ReV2EventError, match="failed executor"):
        _start(
            store,
            "d2",
            work_item_id=digest("sibling-on-same-executor"),
        )


@pytest.mark.unit
def test_pause_resume_and_terminal_ordering_is_closed(tmp_path: Path) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    store.append(
        "run_paused",
        {"reason": "token reservation unavailable", "reason_code": "tokens_exhausted"},
        occurred_at=NOW,
    )
    with pytest.raises(ReV2EventError, match="authorization|operator"):
        store.append("run_resumed", {"reason": "retry"}, occurred_at=NOW)
    store.append(
        "budget_authorized",
        {
            "authorized_by": "operator",
            "dimension": "tokens",
            "new_value": 200,
            "old_value": 100,
            "reason": "continue pinned run",
        },
        occurred_at=NOW,
    )
    store.append("run_resumed", {"reason": "authorized"}, occurred_at=NOW)
    store.append("run_completed", {"reason": "goals_satisfied"}, occurred_at=NOW)
    with pytest.raises(ReV2EventError, match="terminal"):
        store.append(
            "work_planned",
            {"work_item_ids": [WORK]},
            occurred_at=NOW,
        )


@pytest.mark.unit
def test_protocol_22_rejects_legacy_or_unknown_payload_fields(tmp_path: Path) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    _start(store, "d1")

    with pytest.raises(ReV2EventError, match="unknown fields"):
        store.append(
            "dispatch_observed",
            {
                "dispatch_id": "d1",
                "observation": {},
                "work_item_id": WORK,
            },
            occurred_at=NOW,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"reported_token_usage": None}, "trusted_exact"),
        (
            {"reported_token_usage": 1, "token_usage_status": "unavailable"},
            "unavailable",
        ),
        ({"observed_active_ms": None}, "trusted_exact"),
        (
            {"active_usage_status": "unavailable", "observed_active_ms": 1},
            "unavailable",
        ),
    ),
)
def test_observation_usage_status_and_value_are_coherent(
    tmp_path: Path,
    changes: dict[str, object],
    message: str,
) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    _start(store, "d1")
    payload = {
        "active_usage_status": "trusted_exact",
        "dispatch_id": "d1",
        "execution_capture_hash": digest("capture:d1"),
        "observed_active_ms": 250,
        "raw_result_contract_status": "valid",
        "reported_token_usage": 25,
        "token_usage_status": "trusted_exact",
        "work_item_id": WORK,
    }
    payload.update(changes)

    with pytest.raises(ReV2EventError, match=message):
        store.append("dispatch_observed", payload, occurred_at=NOW)


@pytest.mark.unit
def test_deterministic_observation_requires_not_applicable_and_zero_tokens(
    tmp_path: Path,
) -> None:
    store = event_store_v22(tmp_path)
    _run(store)
    _start(store, "d1", token_reservation=0)

    with pytest.raises(ReV2EventError, match="deterministic"):
        _observe(store, "d1", raw_status="valid", token_usage=1)
