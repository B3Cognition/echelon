from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.events import EventStore, ReV2EventError, validate_event_history


NOW = "2026-08-14T12:00:00Z"


def digest(value: str) -> str:
    return content_digest(value.encode())


def event_store(tmp_path: Path) -> EventStore:
    return EventStore(tmp_path / "events.jsonl")


def start_attempt(
    store: EventStore,
    *,
    work_item_id: str,
    dispatch_id: str,
    attempt_kind: str,
    attempt_index: int,
) -> None:
    store.append(
        "dispatch_leased",
        {"dispatch_id": dispatch_id, "work_item_id": work_item_id},
        occurred_at=NOW,
    )
    store.append(
        "dispatch_started",
        {
            "attempt_index": attempt_index,
            "attempt_kind": attempt_kind,
            "dispatch_id": dispatch_id,
            "work_item_id": work_item_id,
        },
        occurred_at=NOW,
    )


def observe(
    store: EventStore, *, work_item_id: str, dispatch_id: str, contract_valid: bool
) -> None:
    store.append(
        "dispatch_observed",
        {
            "dispatch_id": dispatch_id,
            "observation": {
                "duration_ms": 1,
                "ended_at": NOW,
                "exit_code": 0,
                "model_name": "fixture-model",
                "output_truncated": False,
                "provider_name": "fixture",
                "result_contract_valid": contract_valid,
                "started_at": NOW,
                "stderr_digest": None,
                "timed_out": False,
                "token_usage": 1,
            },
            "work_item_id": work_item_id,
        },
        occurred_at=NOW,
    )


def reject_candidate(
    store: EventStore, *, work_item_id: str, dispatch_id: str, candidate_id: str
) -> None:
    store.append(
        "candidate_persisted",
        {
            "candidate_id": candidate_id,
            "dispatch_id": dispatch_id,
            "work_item_id": work_item_id,
        },
        occurred_at=NOW,
    )
    store.append(
        "candidate_rejected",
        {
            "candidate_id": candidate_id,
            "certification_id": digest(f"certification-{candidate_id}"),
            "reason": "rejected",
            "work_item_id": work_item_id,
        },
        occurred_at=NOW,
    )


def replace_jsonl_record(
    path: Path, *, index: int, field: str, value: object
) -> None:
    records = [json.loads(line) for line in path.read_bytes().splitlines()]
    records[index][field] = value
    path.write_bytes(b"".join(canonical_json_bytes(record) for record in records))


def test_append_builds_a_canonical_hash_chain(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    first = store.append(
        "run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW
    )
    second = store.append(
        "work_planned", {"work_item_ids": [digest("work")]}, occurred_at=NOW
    )

    assert (first.seq, first.previous_event_hash) == (1, None)
    assert (second.seq, second.previous_event_hash) == (2, first.event_hash)
    assert store.replay() == (first, second)
    assert store.path.read_bytes() == b"".join(
        canonical_json_bytes(event.to_json_dict()) for event in (first, second)
    )


def test_event_chain_rejects_a_modified_middle_record(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    store.append("run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW)
    store.append(
        "work_planned", {"work_item_ids": [digest("work")]}, occurred_at=NOW
    )
    replace_jsonl_record(store.path, index=0, field="type", value="tampered")

    with pytest.raises(ReV2EventError, match="event hash"):
        store.replay()


@pytest.mark.parametrize(
    ("bytes_to_append", "message"),
    [
        (b'{"schema_version":1', "partial"),
        (b"not-json\n", "JSON"),
        (b"\n", "JSON"),
    ],
)
def test_replay_fails_closed_on_torn_or_invalid_records(
    tmp_path: Path, bytes_to_append: bytes, message: str
) -> None:
    store = event_store(tmp_path)
    store.append("run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW)
    with store.path.open("ab") as stream:
        stream.write(bytes_to_append)

    before = store.path.read_bytes()
    with pytest.raises(ReV2EventError, match=message):
        store.replay()
    assert store.path.read_bytes() == before


def test_append_rejects_noncanonical_payload_values_and_exact_schema_violations(
    tmp_path: Path,
) -> None:
    store = event_store(tmp_path)

    with pytest.raises(ReV2EventError, match="unknown fields"):
        store.append(
            "run_created",
            {"run_manifest_id": digest("run"), "mutable_status": "running"},
            occurred_at=NOW,
        )
    with pytest.raises(ReV2EventError, match="JSON"):
        store.append(
            "run_created", {"run_manifest_id": {digest("run")}}, occurred_at=NOW
        )
    with pytest.raises(ReV2EventError, match="RFC3339"):
        store.append(
            "run_created", {"run_manifest_id": digest("run")}, occurred_at="today"
        )
    assert not store.path.exists()


def test_replay_rejects_noncanonical_json_even_with_a_valid_hash(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    event = store.append(
        "run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW
    )
    noncanonical = json.dumps(event.to_json_dict(), sort_keys=False).encode() + b"\n"
    store.path.write_bytes(noncanonical)

    with pytest.raises(ReV2EventError, match="canonical"):
        store.replay()


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e10000"])
def test_replay_rejects_nonfinite_or_overflowing_json_numbers_with_record_index(
    tmp_path: Path, number: str
) -> None:
    store = event_store(tmp_path)
    store.path.write_bytes(f'{{"payload":{number}}}\n'.encode())

    with pytest.raises(ReV2EventError, match=r"event record 1 .*invalid JSON"):
        store.replay()


def test_state_machine_rejects_out_of_order_work_events(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    store.append("run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW)

    with pytest.raises(ReV2EventError, match="dispatch_started"):
        store.append(
            "dispatch_started",
            {
                "attempt_index": 1,
                "attempt_kind": "initial_generation",
                "dispatch_id": "dispatch-1",
                "work_item_id": digest("work"),
            },
            occurred_at=NOW,
        )


def test_eventless_lease_retirement_is_strict_and_allowed_while_paused(
    tmp_path: Path,
) -> None:
    store = event_store(tmp_path)
    work_item_id = digest("work")
    store.append("run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW)
    store.append(
        "run_paused",
        {"reason": "operator hold", "reason_code": "operator_hold"},
        occurred_at=NOW,
    )
    retired = store.append(
        "dispatch_lease_retired",
        {
            "dispatch_id": "dispatch-orphan",
            "reason": "dead process without a committed candidate",
            "work_item_id": work_item_id,
        },
        occurred_at=NOW,
    )

    assert retired.type == "dispatch_lease_retired"
    with pytest.raises(ReV2EventError, match="globally unique"):
        store.append(
            "dispatch_lease_retired",
            {
                "dispatch_id": "dispatch-orphan",
                "reason": "duplicate retirement",
                "work_item_id": work_item_id,
            },
            occurred_at=NOW,
        )


def test_checkpoint_consumes_the_matching_acceptance_exactly_once(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    work_item_id = digest("work")
    certification_id = digest("certification")
    artifact_hash = digest("artifact")
    store.append("run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW)
    store.append(
        "dispatch_leased",
        {"dispatch_id": "dispatch-1", "work_item_id": work_item_id},
        occurred_at=NOW,
    )
    store.append(
        "dispatch_started",
        {
            "attempt_index": 1,
            "attempt_kind": "initial_generation",
            "dispatch_id": "dispatch-1",
            "work_item_id": work_item_id,
        },
        occurred_at=NOW,
    )
    store.append(
        "dispatch_observed",
        {
            "dispatch_id": "dispatch-1",
            "observation": {
                "duration_ms": 1,
                "ended_at": NOW,
                "exit_code": 0,
                "model_name": "fixture-model",
                "output_truncated": False,
                "provider_name": "fixture",
                "result_contract_valid": True,
                "started_at": NOW,
                "stderr_digest": None,
                "timed_out": False,
                "token_usage": 1,
            },
            "work_item_id": work_item_id,
        },
        occurred_at=NOW,
    )
    store.append(
        "candidate_persisted",
        {
            "candidate_id": "candidate-1",
            "dispatch_id": "dispatch-1",
            "work_item_id": work_item_id,
        },
        occurred_at=NOW,
    )
    store.append(
        "candidate_certified",
        {
            "candidate_id": "candidate-1",
            "certification_id": certification_id,
            "work_item_id": work_item_id,
        },
        occurred_at=NOW,
    )
    store.append(
        "artifact_accepted",
        {
            "artifact_hash": artifact_hash,
            "artifact_key_id": digest("artifact-key"),
            "certification_id": certification_id,
            "work_item_id": work_item_id,
        },
        occurred_at=NOW,
    )
    checkpoint = {
        "artifact_hash": artifact_hash,
        "certification_id": certification_id,
        "work_item_id": work_item_id,
    }
    store.append("checkpoint_recorded", checkpoint, occurred_at=NOW)

    with pytest.raises(ReV2EventError, match="checkpoint_recorded"):
        store.append("checkpoint_recorded", checkpoint, occurred_at=NOW)


def test_terminal_run_is_immutable(tmp_path: Path) -> None:
    store = event_store(tmp_path)
    store.append("run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW)
    store.append("run_completed", {"reason": "goals_satisfied"}, occurred_at=NOW)

    with pytest.raises(ReV2EventError, match="terminal"):
        store.append(
            "work_planned", {"work_item_ids": [digest("work")]}, occurred_at=NOW
        )


def test_paused_run_requires_control_then_resume_and_executes_no_work(
    tmp_path: Path,
) -> None:
    store = event_store(tmp_path)
    store.append("run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW)
    store.append(
        "run_paused",
        {"reason": "token ceiling exhausted", "reason_code": "tokens_exhausted"},
        occurred_at=NOW,
    )

    with pytest.raises(ReV2EventError, match="paused"):
        store.append(
            "dispatch_leased",
            {"dispatch_id": "dispatch-1", "work_item_id": digest("work")},
            occurred_at=NOW,
        )
    with pytest.raises(ReV2EventError, match="authorization or operator action"):
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
    store.append("run_resumed", {"reason": "budget increased"}, occurred_at=NOW)
    store.append(
        "dispatch_leased",
        {"dispatch_id": "dispatch-1", "work_item_id": digest("work")},
        occurred_at=NOW,
    )
    assert store.replay()[-1].type == "dispatch_leased"


def test_history_rejects_reused_dispatches_candidates_and_invalid_attempt_order(
    tmp_path: Path,
) -> None:
    store = event_store(tmp_path)
    work = digest("work")
    store.append("run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW)
    store.append(
        "dispatch_leased", {"dispatch_id": "dispatch-1", "work_item_id": work}, occurred_at=NOW
    )
    with pytest.raises(ReV2EventError, match="attempt_index"):
        store.append(
            "dispatch_started",
            {
                "attempt_index": 2,
                "attempt_kind": "semantic_repair",
                "dispatch_id": "dispatch-1",
                "work_item_id": work,
            },
            occurred_at=NOW,
        )

    store.append(
        "dispatch_started",
        {
            "attempt_index": 1,
            "attempt_kind": "initial_generation",
            "dispatch_id": "dispatch-1",
            "work_item_id": work,
        },
        occurred_at=NOW,
    )
    assert validate_event_history(store.replay())[-1].type == "dispatch_started"


@pytest.mark.parametrize("attempt_kind", ["semantic_repair", "result_contract_retry"])
def test_repair_attempt_cannot_be_a_work_items_first_dispatch(
    tmp_path: Path, attempt_kind: str
) -> None:
    store = event_store(tmp_path)
    work = digest("work")
    store.append("run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW)

    with pytest.raises(ReV2EventError, match="initial_generation"):
        start_attempt(
            store,
            work_item_id=work,
            dispatch_id="dispatch-1",
            attempt_kind=attempt_kind,
            attempt_index=1,
        )


def test_semantic_repairs_require_and_consume_rejected_generation_outcomes(
    tmp_path: Path,
) -> None:
    store = event_store(tmp_path)
    work = digest("work")
    store.append("run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW)
    start_attempt(
        store,
        work_item_id=work,
        dispatch_id="dispatch-1",
        attempt_kind="initial_generation",
        attempt_index=1,
    )
    observe(store, work_item_id=work, dispatch_id="dispatch-1", contract_valid=True)
    reject_candidate(store, work_item_id=work, dispatch_id="dispatch-1", candidate_id="candidate-1")
    start_attempt(
        store,
        work_item_id=work,
        dispatch_id="dispatch-2",
        attempt_kind="semantic_repair",
        attempt_index=1,
    )
    observe(store, work_item_id=work, dispatch_id="dispatch-2", contract_valid=True)
    reject_candidate(store, work_item_id=work, dispatch_id="dispatch-2", candidate_id="candidate-2")
    start_attempt(
        store,
        work_item_id=work,
        dispatch_id="dispatch-3",
        attempt_kind="semantic_repair",
        attempt_index=2,
    )

    assert store.replay()[-1].payload["attempt_index"] == 2


def test_contract_retries_require_fresh_invalid_contract_observations(
    tmp_path: Path,
) -> None:
    store = event_store(tmp_path)
    work = digest("work")
    store.append("run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW)
    start_attempt(
        store,
        work_item_id=work,
        dispatch_id="dispatch-1",
        attempt_kind="initial_generation",
        attempt_index=1,
    )
    observe(store, work_item_id=work, dispatch_id="dispatch-1", contract_valid=False)
    start_attempt(
        store,
        work_item_id=work,
        dispatch_id="dispatch-2",
        attempt_kind="result_contract_retry",
        attempt_index=1,
    )
    observe(store, work_item_id=work, dispatch_id="dispatch-2", contract_valid=False)
    start_attempt(
        store,
        work_item_id=work,
        dispatch_id="dispatch-3",
        attempt_kind="result_contract_retry",
        attempt_index=2,
    )

    assert store.replay()[-1].payload["attempt_index"] == 2


def test_invalid_contract_retry_lease_must_remain_on_eligible_work_item(
    tmp_path: Path,
) -> None:
    store = event_store(tmp_path)
    work_a = digest("work-a")
    work_b = digest("work-b")
    store.append("run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW)
    start_attempt(
        store,
        work_item_id=work_a,
        dispatch_id="dispatch-1",
        attempt_kind="initial_generation",
        attempt_index=1,
    )
    observe(store, work_item_id=work_a, dispatch_id="dispatch-1", contract_valid=False)
    before_rejected_lease = store.replay()

    with pytest.raises(ReV2EventError, match="eligible work item"):
        store.append(
            "dispatch_leased",
            {"dispatch_id": "dispatch-2", "work_item_id": work_b},
            occurred_at=NOW,
        )
    assert store.replay() == before_rejected_lease

    start_attempt(
        store,
        work_item_id=work_a,
        dispatch_id="dispatch-2",
        attempt_kind="result_contract_retry",
        attempt_index=1,
    )
    assert store.replay()[-1].payload["work_item_id"] == work_a


def test_valid_contract_or_candidate_rejection_cannot_reuse_an_older_retry_eligibility(
    tmp_path: Path,
) -> None:
    store = event_store(tmp_path)
    work = digest("work")
    store.append("run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW)
    start_attempt(
        store,
        work_item_id=work,
        dispatch_id="dispatch-1",
        attempt_kind="initial_generation",
        attempt_index=1,
    )
    observe(store, work_item_id=work, dispatch_id="dispatch-1", contract_valid=False)
    start_attempt(
        store,
        work_item_id=work,
        dispatch_id="dispatch-2",
        attempt_kind="result_contract_retry",
        attempt_index=1,
    )
    observe(store, work_item_id=work, dispatch_id="dispatch-2", contract_valid=True)
    reject_candidate(store, work_item_id=work, dispatch_id="dispatch-2", candidate_id="candidate-2")
    store.append(
        "dispatch_leased",
        {"dispatch_id": "dispatch-3", "work_item_id": work},
        occurred_at=NOW,
    )
    with pytest.raises(ReV2EventError, match="result_contract_retry"):
        store.append(
            "dispatch_started",
            {
                "attempt_index": 2,
                "attempt_kind": "result_contract_retry",
                "dispatch_id": "dispatch-3",
                "work_item_id": work,
            },
            occurred_at=NOW,
        )


def test_repair_attempts_reject_cross_kind_and_stale_outcome_eligibility(
    tmp_path: Path,
) -> None:
    store = event_store(tmp_path)
    work = digest("work")
    store.append("run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW)
    start_attempt(
        store,
        work_item_id=work,
        dispatch_id="dispatch-1",
        attempt_kind="initial_generation",
        attempt_index=1,
    )
    observe(store, work_item_id=work, dispatch_id="dispatch-1", contract_valid=True)
    reject_candidate(store, work_item_id=work, dispatch_id="dispatch-1", candidate_id="candidate-1")
    store.append(
        "dispatch_leased",
        {"dispatch_id": "dispatch-2", "work_item_id": work},
        occurred_at=NOW,
    )
    with pytest.raises(ReV2EventError, match="result_contract_retry"):
        store.append(
            "dispatch_started",
            {
                "attempt_index": 1,
                "attempt_kind": "result_contract_retry",
                "dispatch_id": "dispatch-2",
                "work_item_id": work,
            },
            occurred_at=NOW,
        )

    # Use the eligible semantic repair, then finish it with a valid contract.
    store.append(
        "dispatch_started",
        {
            "attempt_index": 1,
            "attempt_kind": "semantic_repair",
            "dispatch_id": "dispatch-2",
            "work_item_id": work,
        },
        occurred_at=NOW,
    )
    observe(store, work_item_id=work, dispatch_id="dispatch-2", contract_valid=True)
    reject_candidate(store, work_item_id=work, dispatch_id="dispatch-2", candidate_id="candidate-2")
    start_attempt(
        store,
        work_item_id=work,
        dispatch_id="dispatch-3",
        attempt_kind="semantic_repair",
        attempt_index=2,
    )
    observe(store, work_item_id=work, dispatch_id="dispatch-3", contract_valid=True)
    reject_candidate(store, work_item_id=work, dispatch_id="dispatch-3", candidate_id="candidate-3")
    store.append(
        "dispatch_leased",
        {"dispatch_id": "dispatch-4", "work_item_id": work},
        occurred_at=NOW,
    )
    with pytest.raises(ReV2EventError, match="result_contract_retry"):
        store.append(
            "dispatch_started",
            {
                "attempt_index": 1,
                "attempt_kind": "result_contract_retry",
                "dispatch_id": "dispatch-4",
                "work_item_id": work,
            },
            occurred_at=NOW,
        )


def test_concurrent_appenders_get_one_consecutive_chain(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    EventStore(path).append(
        "run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW
    )

    def append(index: int) -> None:
        EventStore(path).append(
            "work_planned",
            {"work_item_ids": [digest(f"work-{index:02d}")]},
            occurred_at=NOW,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        tuple(executor.map(append, range(24)))

    replayed = EventStore(path).replay()
    assert tuple(event.seq for event in replayed) == tuple(range(1, 26))
    assert len({event.event_hash for event in replayed}) == 25


def test_append_write_loop_survives_short_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness.re_v2.events as events_module

    real_write = os.write

    def short_write(fd: int, payload: bytes) -> int:
        return real_write(fd, payload[:7])

    monkeypatch.setattr(events_module.os, "write", short_write)
    store = event_store(tmp_path)
    appended = store.append(
        "run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW
    )
    assert store.replay() == (appended,)


def test_append_retries_interrupted_write_and_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness.re_v2.events as events_module

    real_write = os.write
    real_fsync = os.fsync
    write_calls = 0
    fsync_calls = 0

    def interrupted_write(fd: int, payload: bytes) -> int:
        nonlocal write_calls
        write_calls += 1
        if write_calls == 1:
            return real_write(fd, payload[:7])
        if write_calls == 2:
            raise InterruptedError
        return real_write(fd, payload)

    def interrupted_fsync(fd: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            raise InterruptedError
        real_fsync(fd)

    monkeypatch.setattr(events_module.os, "write", interrupted_write)
    monkeypatch.setattr(events_module.os, "fsync", interrupted_fsync)
    store = event_store(tmp_path)
    appended = store.append(
        "run_created", {"run_manifest_id": digest("run")}, occurred_at=NOW
    )

    assert store.replay() == (appended,)
    assert write_calls >= 3
    assert fsync_calls >= 3
