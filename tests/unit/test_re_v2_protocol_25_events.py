from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.events import EventStore, ReV2EventError
from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS
from harness.re_v2.protocol_25.events import PROTOCOL_25_EVENTS, Protocol25ReplayState
from tests.re_v2_protocol_22_fixtures import digest


NOW = "2026-08-26T12:00:00Z"
TARGET_A = digest("target:a")
TARGET_B = digest("target:b")
SOURCE = "api"
EPOCH = digest("epoch")


def _store(tmp_path: Path, name: str = "events.jsonl") -> EventStore:
    return EventStore(tmp_path / name, protocol=PROTOCOL_25_EVENTS)


def _append(store: EventStore, event_type: str, payload: dict[str, object]) -> None:
    store.append(event_type, payload, occurred_at=NOW)


def _run(store: EventStore) -> None:
    _append(store, "run_created", {"run_manifest_id": digest("run")})


def _freeze(store: EventStore, targets: tuple[str, ...] = (TARGET_A, TARGET_B)) -> None:
    for target in targets:
        _append(
            store,
            "audit_candidate_accepted",
            {
                "audit_candidate_authority_id": digest(f"candidate:{target}"),
                "audit_target_id": target,
            },
        )
    _append(
        store,
        "audit_epoch_frozen",
        {"audit_epoch_id": EPOCH, "audit_target_ids": sorted(targets)},
    )


def _start_shared(
    store: EventStore,
    *,
    dispatch_id: str,
    work: str,
    tokens: int = 100,
    active_ms: int = 1_000,
) -> None:
    _append(store, "dispatch_leased", {"dispatch_id": dispatch_id, "work_item_id": work})
    _append(
        store,
        "dispatch_started",
        {
            "active_ms_reservation": active_ms,
            "attempt_index": 1,
            "attempt_kind": "initial_generation",
            "billable_token_reservation": tokens,
            "dispatch_id": dispatch_id,
            "execution_input_hash": digest(f"input:{dispatch_id}"),
            "executor_contract_hash": digest("executor"),
            "work_item_id": work,
        },
    )


def _finish_shared(store: EventStore, *, dispatch_id: str, work: str) -> None:
    candidate = digest(f"candidate:{dispatch_id}")
    assessment = digest(f"assessment:{dispatch_id}")
    certification = digest(f"certification:{dispatch_id}")
    _append(
        store,
        "dispatch_observed",
        {
            "active_usage_status": "trusted_exact",
            "dispatch_id": dispatch_id,
            "execution_capture_hash": digest(f"capture:{dispatch_id}"),
            "observed_active_ms": 200,
            "raw_result_contract_status": "valid",
            "reported_token_usage": 20,
            "token_usage_status": "trusted_exact",
            "work_item_id": work,
        },
    )
    _append(
        store,
        "candidate_persisted",
        {
            "candidate_id": candidate,
            "candidate_inventory_hash": digest(f"inventory:{dispatch_id}"),
            "dispatch_id": dispatch_id,
            "execution_capture_hash": digest(f"capture:{dispatch_id}"),
            "work_item_id": work,
        },
    )
    _append(
        store,
        "candidate_certified",
        {
            "candidate_assessment_id": assessment,
            "candidate_id": candidate,
            "certification_receipt_id": certification,
            "work_item_id": work,
        },
    )
    _append(
        store,
        "artifact_accepted",
        {
            "artifact_acceptance_receipt_id": digest(f"acceptance:{dispatch_id}"),
            "artifact_hash": digest(f"artifact:{dispatch_id}"),
            "artifact_key_id": digest(f"key:{dispatch_id}"),
            "candidate_assessment_id": assessment,
            "certification_receipt_id": certification,
            "work_item_id": work,
        },
    )


def _semantic_start_payload(
    *,
    dispatch_id: str,
    work: str,
    target: str | None = TARGET_A,
    cycle_id: str = "cycle-1",
    round_index: int = 1,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "dispatch_id": dispatch_id,
        "semantic_round": round_index,
        "source_cycle_id": cycle_id,
        "source_id": SOURCE,
        "work_item_id": work,
    }
    if target is not None:
        payload["audit_target_id"] = target
    return payload


def _resolution(
    store: EventStore,
    target: str,
    suffix: str,
    *,
    cycle_id: str = "cycle-1",
    round_index: int = 1,
) -> None:
    work = digest(f"resolution:{cycle_id}:{suffix}")
    dispatch = f"resolution-{cycle_id}-{suffix}"
    _start_shared(store, dispatch_id=dispatch, work=work)
    _append(
        store,
        "semantic_resolution_started",
        _semantic_start_payload(
            dispatch_id=dispatch,
            work=work,
            target=target,
            cycle_id=cycle_id,
            round_index=round_index,
        ),
    )
    _finish_shared(store, dispatch_id=dispatch, work=work)
    _append(
        store,
        "semantic_resolution_accepted",
        {
            "audit_target_id": target,
            "resolution_overlay_id": digest(f"overlay:{cycle_id}:{suffix}"),
            "semantic_round": round_index,
            "source_cycle_id": cycle_id,
            "source_id": SOURCE,
            "work_item_id": work,
        },
    )


def _recheck(
    store: EventStore,
    target: str,
    suffix: str,
    *,
    cycle_id: str = "cycle-1",
    round_index: int = 1,
) -> None:
    work = digest(f"recheck:{cycle_id}:{suffix}")
    dispatch = f"recheck-{cycle_id}-{suffix}"
    _start_shared(store, dispatch_id=dispatch, work=work)
    _append(
        store,
        "closure_recheck_started",
        _semantic_start_payload(
            dispatch_id=dispatch,
            work=work,
            target=target,
            cycle_id=cycle_id,
            round_index=round_index,
        ),
    )
    _finish_shared(store, dispatch_id=dispatch, work=work)
    _append(
        store,
        "target_closure_assessed",
        {
            "audit_target_id": target,
            "semantic_round": round_index,
            "source_cycle_id": cycle_id,
            "source_id": SOURCE,
            "target_closure_assessment_id": digest(
                f"target-assessment:{cycle_id}:{suffix}"
            ),
            "work_item_id": work,
        },
    )


def _guard(
    store: EventStore,
    targets: tuple[str, ...],
    *,
    passed: bool = True,
    cycle_id: str = "cycle-1",
    round_index: int = 1,
) -> str:
    work = digest(f"guard:{cycle_id}")
    dispatch = f"guard-{cycle_id}"
    _start_shared(store, dispatch_id=dispatch, work=work)
    payload = _semantic_start_payload(
        dispatch_id=dispatch,
        work=work,
        target=None,
        cycle_id=cycle_id,
        round_index=round_index,
    )
    payload["participating_target_ids"] = sorted(targets)
    _append(store, "source_composition_guard_started", payload)
    _finish_shared(store, dispatch_id=dispatch, work=work)
    assessment = digest(f"source-assessment:{cycle_id}")
    _append(
        store,
        "source_composition_assessed",
        {
            "implicated_finding_ids": [],
            "passed": passed,
            "semantic_round": round_index,
            "source_composition_assessment_id": assessment,
            "source_cycle_id": cycle_id,
            "source_id": SOURCE,
            "work_item_id": work,
        },
    )
    return assessment


@pytest.mark.unit
def test_audit_candidates_must_be_complete_before_epoch_freeze(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store)
    _append(
        store,
        "audit_candidate_accepted",
        {
            "audit_candidate_authority_id": digest("candidate:a"),
            "audit_target_id": TARGET_A,
        },
    )

    with pytest.raises(ReV2EventError, match="accepted audit targets"):
        _append(
            store,
            "audit_epoch_frozen",
            {"audit_epoch_id": EPOCH, "audit_target_ids": sorted([TARGET_A, TARGET_B])},
        )

    _append(
        store,
        "audit_epoch_frozen",
        {"audit_epoch_id": EPOCH, "audit_target_ids": [TARGET_A]},
    )
    with pytest.raises(ReV2EventError, match="only once"):
        _append(
            store,
            "audit_epoch_frozen",
            {"audit_epoch_id": digest("epoch:2"), "audit_target_ids": [TARGET_A]},
        )


@pytest.mark.unit
def test_protocol_24_rejects_l3_events(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "legacy.jsonl", protocol=PROTOCOL_24_EVENTS)
    _run(store)
    with pytest.raises(ReV2EventError, match="unknown protocol-2.2 event type"):
        _append(
            store,
            "audit_candidate_accepted",
            {
                "audit_candidate_authority_id": digest("candidate:a"),
                "audit_target_id": TARGET_A,
            },
        )


@pytest.mark.unit
def test_audit_dispatch_cannot_start_after_epoch_freeze(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store)
    _freeze(store, (TARGET_A,))
    work = digest("late-audit")
    _start_shared(store, dispatch_id="late-audit", work=work)

    with pytest.raises(ReV2EventError, match="semantic operation"):
        _append(
            store,
            "dispatch_observed",
            {
                "active_usage_status": "trusted_exact",
                "dispatch_id": "late-audit",
                "execution_capture_hash": digest("late-capture"),
                "observed_active_ms": 1,
                "raw_result_contract_status": "valid",
                "reported_token_usage": 1,
                "token_usage_status": "trusted_exact",
                "work_item_id": work,
            },
        )


@pytest.mark.unit
def test_resolution_recheck_guard_receipts_and_progress_are_ordered(
    tmp_path: Path,
) -> None:
    premature = _store(tmp_path, "premature.jsonl")
    _run(premature)
    _freeze(premature)
    _resolution(premature, TARGET_A, "a")
    _resolution(premature, TARGET_B, "b")
    _recheck(premature, TARGET_A, "a")

    with pytest.raises(ReV2EventError, match="every participating target"):
        _guard(premature, (TARGET_A, TARGET_B))

    store = _store(tmp_path)
    _run(store)
    _freeze(store)
    _resolution(store, TARGET_A, "a")
    _resolution(store, TARGET_B, "b")
    _recheck(store, TARGET_A, "a")
    _recheck(store, TARGET_B, "b")
    assessment = _guard(store, (TARGET_A, TARGET_B))

    finding_a = digest("finding:a")
    finding_b = digest("finding:b")
    for target, finding in ((TARGET_A, finding_a), (TARGET_B, finding_b)):
        _append(
            store,
            "finding_closure_recorded",
            {
                "audit_target_id": target,
                "finding_closure_receipt_id": digest(f"receipt:{finding}"),
                "finding_key_id": finding,
                "semantic_round": 1,
                "source_composition_assessment_id": assessment,
                "source_cycle_id": "cycle-1",
                "verdict": "closed",
            },
        )
        _append(
            store,
            "semantic_progress_recorded",
            {
                "audit_target_id": target,
                "semantic_round": 1,
                "source_cycle_id": "cycle-1",
                "unresolved_after_ids": [],
                "unresolved_before_ids": [finding],
            },
        )

    state = PROTOCOL_25_EVENTS.new_state()
    assert isinstance(state, Protocol25ReplayState)
    for event in store.replay():
        state.consume(event)
    assert state.rounds_by_target == {TARGET_A: 1, TARGET_B: 1}
    assert state.unresolved_by_target == {TARGET_A: frozenset(), TARGET_B: frozenset()}


@pytest.mark.unit
def test_closure_receipt_requires_passing_source_guard(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store)
    _freeze(store, (TARGET_A,))
    _resolution(store, TARGET_A, "a")
    _recheck(store, TARGET_A, "a")
    assessment = _guard(store, (TARGET_A,), passed=False)

    with pytest.raises(ReV2EventError, match="passing source composition"):
        _append(
            store,
            "finding_closure_recorded",
            {
                "audit_target_id": TARGET_A,
                "finding_closure_receipt_id": digest("receipt"),
                "finding_key_id": digest("finding"),
                "semantic_round": 1,
                "source_composition_assessment_id": assessment,
                "source_cycle_id": "cycle-1",
                "verdict": "closed",
            },
        )


@pytest.mark.unit
def test_roots_precede_terminal_and_terminal_is_immutable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store)
    _freeze(store, (TARGET_A,))

    with pytest.raises(ReV2EventError, match="closure root"):
        _append(store, "run_completed", {"reason": "done"})

    _append(
        store,
        "audit_closure_root_accepted",
        {
            "audit_closure_root_id": digest("closure-root"),
            "audit_epoch_id": EPOCH,
            "deferred_observation_ids": [],
            "unresolved_finding_ids": [],
        },
    )
    _append(
        store,
        "l3_source_root_accepted",
        {
            "l3_source_root_id": digest("source-root"),
            "scope_state": "complete",
            "source_id": SOURCE,
        },
    )
    _append(store, "run_completed", {"reason": "done"})

    with pytest.raises(ReV2EventError, match="after terminal"):
        _append(
            store,
            "l3_source_root_accepted",
            {
                "l3_source_root_id": digest("late-root"),
                "scope_state": "complete",
                "source_id": digest("late-source"),
            },
        )


@pytest.mark.unit
def test_semantic_state_is_derived_from_replay_and_prerequisite_authority(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _run(store)
    state = PROTOCOL_25_EVENTS.new_state()
    assert isinstance(state, Protocol25ReplayState)
    for event in store.replay():
        state.consume(event)
    assert state.semantic_state(prerequisites_complete=False) == "running_prerequisites"
    assert state.semantic_state(prerequisites_complete=True) == "running_audit"

    _freeze(store, (TARGET_A,))
    state = PROTOCOL_25_EVENTS.new_state()
    for event in store.replay():
        state.consume(event)
    assert state.semantic_state(prerequisites_complete=True) == "epoch_frozen"

    work = digest("resolution:state")
    _start_shared(store, dispatch_id="resolution-state", work=work)
    _append(
        store,
        "semantic_resolution_started",
        _semantic_start_payload(dispatch_id="resolution-state", work=work),
    )
    state = PROTOCOL_25_EVENTS.new_state()
    for event in store.replay():
        state.consume(event)
    assert state.semantic_state(prerequisites_complete=True) == "running_resolution"


@pytest.mark.unit
def test_semantic_resource_pause_is_nonterminal_and_resumable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store)
    _append(
        store,
        "run_paused",
        {"reason": "semantic tokens", "reason_code": "semantic_tokens_exhausted"},
    )
    _append(
        store,
        "semantic_budget_authorized",
        {
            "authorized_by": "operator",
            "dimension": "tokens",
            "new_value": 200,
            "old_value": 100,
            "reason": "continue",
        },
    )
    state = PROTOCOL_25_EVENTS.new_state()
    for event in store.replay():
        state.consume(event)
    assert isinstance(state, Protocol25ReplayState)
    assert state.semantic_state(prerequisites_complete=True) == "paused_resource"

    _append(store, "run_resumed", {"reason": "semantic budget raised"})
    state = PROTOCOL_25_EVENTS.new_state()
    for event in store.replay():
        state.consume(event)
    assert state.semantic_state(prerequisites_complete=True) == "running_audit"


@pytest.mark.unit
def test_semantic_plateau_is_terminal_without_inventing_shared_work_failure(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _run(store)
    _freeze(store, (TARGET_A,))
    finding = digest("finding")
    from tests.unit.test_re_v2_protocol_25_budget import _record_cycle

    for round_index in (1, 2):
        _record_cycle(
            store,
            cycle_id=f"cycle-{round_index}",
            round_index=round_index,
            before=(finding,),
            after=(finding,),
            passed=False,
        )
    _append(
        store,
        "semantic_plateau_reached",
        {
            "audit_target_id": TARGET_A,
            "semantic_round": 2,
            "unresolved_finding_ids": [finding],
        },
    )
    _append(store, "run_failed", {"reason": "semantic plateau"})

    replayed = PROTOCOL_25_EVENTS.new_state()
    assert isinstance(replayed, Protocol25ReplayState)
    for event in store.replay():
        replayed.consume(event)
    assert replayed.semantic_state(prerequisites_complete=True) == "blocked_plateau"


@pytest.mark.unit
def test_three_round_ceiling_is_terminal_without_fabricating_plateau(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _run(store)
    _freeze(store, (TARGET_A,))
    first = digest("finding:first")
    second = digest("finding:second")
    third = digest("finding:third")
    from tests.unit.test_re_v2_protocol_25_budget import _record_cycle

    _record_cycle(
        store,
        cycle_id="cycle-1",
        round_index=1,
        before=tuple(sorted((first, second, third))),
        after=tuple(sorted((second, third))),
        passed=True,
    )
    _record_cycle(
        store,
        cycle_id="cycle-2",
        round_index=2,
        before=tuple(sorted((second, third))),
        after=(third,),
        passed=True,
    )
    _record_cycle(
        store,
        cycle_id="cycle-3",
        round_index=3,
        before=(third,),
        after=(third,),
        passed=False,
    )

    _append(store, "run_failed", {"reason": "three-round semantic ceiling"})

    state = PROTOCOL_25_EVENTS.new_state()
    assert isinstance(state, Protocol25ReplayState)
    for event in store.replay():
        state.consume(event)
    assert state.semantic_state(prerequisites_complete=True) == "blocked_incomplete"


@pytest.mark.unit
def test_deferred_source_root_derives_next_epoch_required(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store)
    _freeze(store, (TARGET_A,))
    _append(
        store,
        "audit_closure_root_accepted",
        {
            "audit_closure_root_id": digest("closure-root"),
            "audit_epoch_id": EPOCH,
            "deferred_observation_ids": [digest("observation")],
            "unresolved_finding_ids": [],
        },
    )
    _append(
        store,
        "l3_source_root_accepted",
        {
            "l3_source_root_id": digest("source-root"),
            "scope_state": "next_epoch_required",
            "source_id": SOURCE,
        },
    )
    _append(store, "run_completed", {"reason": "epoch closed with deferred work"})

    state = PROTOCOL_25_EVENTS.new_state()
    assert isinstance(state, Protocol25ReplayState)
    for event in store.replay():
        state.consume(event)
    assert state.semantic_state(prerequisites_complete=True) == "next_epoch_required"
