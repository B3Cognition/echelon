from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.controller import Protocol22Controller
from harness.re_v2.protocol_24.controller import Protocol24Controller
from harness.re_v2.protocol_25.controller import (
    Protocol25Controller,
    Protocol25ControllerActionV1,
    Protocol25ControllerStateV1,
    SemanticSourceCycleStateV1,
    SemanticTargetControllerStateV1,
    plan_next_protocol_25,
)


SOURCE = content_digest("source")
DOMAIN_TARGET = content_digest("domain-target")
SOURCE_TARGET = content_digest("source-target")
DOMAIN_FINDING = content_digest("domain-finding")
SOURCE_FINDING = content_digest("source-finding")
EPOCH = content_digest("epoch")


def _cycle_id(semantic_round: int) -> str:
    value = content_digest(
        {
            "audit_epoch_id": EPOCH,
            "semantic_round": semantic_round,
            "source_id": SOURCE,
        }
    )
    return f"cycle-{value.removeprefix('sha256:')}"


def _target(
    target_id: str,
    *,
    audit_state: str = "accepted",
    findings: tuple[str, ...] = (),
    unresolved: tuple[str, ...] | None = None,
    semantic_round: int = 0,
    no_reduction: int = 0,
    stage: str = "idle",
) -> SemanticTargetControllerStateV1:
    return SemanticTargetControllerStateV1(
        audit_target_id=target_id,
        source_id=SOURCE,
        audit_state=audit_state,  # type: ignore[arg-type]
        frozen_finding_ids=findings,
        unresolved_finding_ids=(findings if unresolved is None else unresolved),
        semantic_round=semantic_round,
        no_reduction_rounds=no_reduction,
        stage=stage,  # type: ignore[arg-type]
    )


def _state(
    *targets: SemanticTargetControllerStateV1,
    prerequisites_complete: bool = True,
    prerequisites_failed: bool = False,
    paused: bool = False,
    epoch: str | None = EPOCH,
    cycles: tuple[SemanticSourceCycleStateV1, ...] = (),
    roots: tuple[str, ...] = (),
    deferred: tuple[str, ...] = (),
    terminal: str | None = None,
    indeterminate: bool = False,
) -> Protocol25ControllerStateV1:
    return Protocol25ControllerStateV1(
        prerequisites_complete=prerequisites_complete,
        prerequisites_failed=prerequisites_failed,
        paused_resource=paused,
        audit_epoch_id=epoch,
        targets=tuple(sorted(targets, key=lambda item: item.audit_target_id)),
        source_cycles=cycles,
        rooted_source_ids=roots,
        deferred_observation_ids=deferred,
        terminal_state=terminal,  # type: ignore[arg-type]
        indeterminate_execution=indeterminate,
    )


def _cycle(
    *targets: str,
    guard: str = "pending",
    semantic_round: int = 1,
) -> SemanticSourceCycleStateV1:
    return SemanticSourceCycleStateV1(
        source_id=SOURCE,
        source_cycle_id=_cycle_id(semantic_round),
        semantic_round=semantic_round,
        participating_target_ids=tuple(sorted(targets)),
        guard_stage=guard,  # type: ignore[arg-type]
    )


class _ScriptedBackend:
    def __init__(
        self,
        states: tuple[Protocol25ControllerStateV1, ...],
        actions: tuple[Protocol25ControllerActionV1, ...],
    ) -> None:
        assert len(states) == len(actions) + 1
        self.states = states
        self.actions = actions
        self.index = 0
        self.provider_actions: list[str] = []

    def recover_controller_state(self) -> Protocol25ControllerStateV1:
        return self.states[self.index]

    def apply_controller_action(self, action: Protocol25ControllerActionV1) -> None:
        assert action == self.actions[self.index]
        if action.kind in {
            "audit_target",
            "resolve_target",
            "recheck_target",
            "guard_source",
        }:
            self.provider_actions.append(action.kind)
        self.index += 1


@pytest.mark.integration
def test_protocol_25_controller_is_a_narrow_protocol_24_extension() -> None:
    assert issubclass(Protocol25Controller, Protocol24Controller)
    assert Protocol25Controller._execute_one is Protocol22Controller._execute_one
    assert Protocol25Controller._execute_provider is Protocol22Controller._execute_provider
    assert (
        Protocol25Controller._certify_provider_candidate
        is not Protocol24Controller._certify_provider_candidate
    )


@pytest.mark.integration
def test_prerequisite_state_does_not_invent_unmaterialized_audit_target_ids() -> None:
    state = Protocol25ControllerStateV1(
        prerequisites_complete=False,
        prerequisites_failed=False,
        paused_resource=False,
        audit_epoch_id=None,
        targets=(),
    )

    assert plan_next_protocol_25(state) == Protocol25ControllerActionV1(
        kind="run_prerequisite"
    )


@pytest.mark.integration
def test_controller_freezes_then_closes_one_source() -> None:
    pending = _state(
        _target(DOMAIN_TARGET, audit_state="pending"),
        _target(SOURCE_TARGET, audit_state="pending"),
        epoch=None,
    )
    first_audited = _state(
        _target(DOMAIN_TARGET, audit_state="pending"),
        _target(SOURCE_TARGET),
        epoch=None,
    )
    audited = _state(
        _target(DOMAIN_TARGET, findings=(DOMAIN_FINDING,)),
        _target(SOURCE_TARGET),
        epoch=None,
    )
    frozen = replace(audited, audit_epoch_id=EPOCH)
    resolved = replace(
        frozen,
        source_cycles=(_cycle(DOMAIN_TARGET),),
        targets=tuple(
            sorted(
                (
                    _target(
                        DOMAIN_TARGET,
                        findings=(DOMAIN_FINDING,),
                        stage="resolution_accepted",
                    ),
                    _target(SOURCE_TARGET),
                ),
                key=lambda item: item.audit_target_id,
            )
        ),
    )
    assessed = replace(
        resolved,
        targets=tuple(
            sorted(
                (
                    _target(
                        DOMAIN_TARGET,
                        findings=(DOMAIN_FINDING,),
                        stage="assessment_accepted",
                    ),
                    _target(SOURCE_TARGET),
                ),
                key=lambda item: item.audit_target_id,
            )
        ),
    )
    guarded = replace(assessed, source_cycles=(_cycle(DOMAIN_TARGET, guard="passed"),))
    receipts = replace(
        assessed,
        source_cycles=(_cycle(DOMAIN_TARGET, guard="receipts_recorded"),),
    )
    progressed = _state(
        _target(
            DOMAIN_TARGET,
            findings=(DOMAIN_FINDING,),
            unresolved=(),
            semantic_round=1,
        ),
        _target(SOURCE_TARGET),
    )
    rooted = replace(progressed, rooted_source_ids=(SOURCE,))
    terminal = replace(rooted, terminal_state="complete")
    actions = (
        Protocol25ControllerActionV1(kind="audit_target", audit_target_id=SOURCE_TARGET),
        Protocol25ControllerActionV1(kind="audit_target", audit_target_id=DOMAIN_TARGET),
        Protocol25ControllerActionV1(kind="freeze_epoch"),
        Protocol25ControllerActionV1(
            kind="resolve_target",
            audit_target_id=DOMAIN_TARGET,
            source_id=SOURCE,
            source_cycle_id=_cycle_id(1),
            semantic_round=1,
            participating_target_ids=(DOMAIN_TARGET,),
        ),
        Protocol25ControllerActionV1(
            kind="recheck_target",
            audit_target_id=DOMAIN_TARGET,
            source_id=SOURCE,
            source_cycle_id=_cycle_id(1),
            semantic_round=1,
            participating_target_ids=(DOMAIN_TARGET,),
        ),
        Protocol25ControllerActionV1(
            kind="guard_source",
            source_id=SOURCE,
            source_cycle_id=_cycle_id(1),
            semantic_round=1,
            participating_target_ids=(DOMAIN_TARGET,),
        ),
        Protocol25ControllerActionV1(
            kind="record_finding_receipts",
            source_id=SOURCE,
            source_cycle_id=_cycle_id(1),
            semantic_round=1,
            participating_target_ids=(DOMAIN_TARGET,),
        ),
        Protocol25ControllerActionV1(
            kind="record_progress",
            source_id=SOURCE,
            source_cycle_id=_cycle_id(1),
            semantic_round=1,
            participating_target_ids=(DOMAIN_TARGET,),
        ),
        Protocol25ControllerActionV1(kind="accept_roots", source_id=SOURCE),
        Protocol25ControllerActionV1(kind="terminal_complete"),
    )
    backend = _ScriptedBackend(
        (
            pending,
            first_audited,
            audited,
            frozen,
            resolved,
            assessed,
            guarded,
            receipts,
            progressed,
            rooted,
            terminal,
        ),
        actions,
    )

    result = Protocol25Controller(backend).run_until_stopped()

    assert result.status == "completed"
    assert backend.provider_actions == [
        "audit_target",
        "audit_target",
        "resolve_target",
        "recheck_target",
        "guard_source",
    ]
    assert backend.provider_actions.count("resolve_target") == 1
    assert backend.provider_actions.count("guard_source") == 1


@pytest.mark.integration
def test_all_pass_audit_closes_without_semantic_provider_calls() -> None:
    frozen = _state(_target(DOMAIN_TARGET), _target(SOURCE_TARGET))
    rooted = replace(frozen, rooted_source_ids=(SOURCE,))
    terminal = replace(rooted, terminal_state="complete")
    backend = _ScriptedBackend(
        (frozen, rooted, terminal),
        (
            Protocol25ControllerActionV1(kind="accept_roots", source_id=SOURCE),
            Protocol25ControllerActionV1(kind="terminal_complete"),
        ),
    )

    assert Protocol25Controller(backend).run_until_stopped().status == "completed"
    assert backend.provider_actions == []


@pytest.mark.integration
def test_failed_audit_does_not_prevent_pending_sibling_audit() -> None:
    state = _state(
        _target(DOMAIN_TARGET, audit_state="failed"),
        _target(SOURCE_TARGET, audit_state="pending"),
        epoch=None,
    )

    action = plan_next_protocol_25(state)

    assert action == Protocol25ControllerActionV1(
        kind="audit_target", audit_target_id=SOURCE_TARGET
    )


@pytest.mark.integration
def test_closed_sibling_skips_resolution_but_remains_in_selected_source() -> None:
    state = _state(
        _target(DOMAIN_TARGET),
        _target(SOURCE_TARGET, findings=(SOURCE_FINDING,)),
    )

    action = plan_next_protocol_25(state)

    assert action is not None
    assert action.kind == "resolve_target"
    assert action.audit_target_id == SOURCE_TARGET
    assert action.participating_target_ids == (SOURCE_TARGET,)
    assert state.source_ids == (SOURCE,)


@pytest.mark.integration
def test_guard_regression_records_no_closure_receipts() -> None:
    state = _state(
        _target(
            DOMAIN_TARGET,
            findings=(DOMAIN_FINDING,),
            stage="assessment_accepted",
        ),
        cycles=(_cycle(DOMAIN_TARGET, guard="failed"),),
    )

    action = plan_next_protocol_25(state)

    assert action is not None
    assert action.kind == "record_progress"


@pytest.mark.integration
def test_deferred_observation_requires_next_epoch_terminal() -> None:
    state = _state(
        _target(DOMAIN_TARGET),
        roots=(SOURCE,),
        deferred=(content_digest("deferred"),),
    )

    assert plan_next_protocol_25(state) == Protocol25ControllerActionV1(
        kind="terminal_next_epoch"
    )


@pytest.mark.integration
def test_reduction_reset_allows_next_round() -> None:
    state = _state(
        _target(
            DOMAIN_TARGET,
            findings=(DOMAIN_FINDING, SOURCE_FINDING),
            unresolved=(SOURCE_FINDING,),
            semantic_round=1,
            no_reduction=0,
        )
    )

    action = plan_next_protocol_25(state)

    assert action is not None
    assert action.kind == "resolve_target"
    assert action.semantic_round == 2


@pytest.mark.integration
def test_two_unchanged_rounds_record_plateau_then_block() -> None:
    unresolved = _target(
        DOMAIN_TARGET,
        findings=(DOMAIN_FINDING,),
        semantic_round=2,
        no_reduction=2,
    )
    action = plan_next_protocol_25(_state(unresolved))
    assert action is not None
    assert action.kind == "record_plateau"

    recorded = replace(unresolved, stage="plateau_recorded")
    assert plan_next_protocol_25(_state(recorded)) == Protocol25ControllerActionV1(
        kind="accept_roots", source_id=SOURCE
    )
    assert plan_next_protocol_25(_state(recorded, roots=(SOURCE,))) == Protocol25ControllerActionV1(
        kind="terminal_blocked_plateau"
    )


@pytest.mark.integration
def test_plateaued_target_does_not_stop_independent_sibling() -> None:
    plateaued = _target(
        DOMAIN_TARGET,
        findings=(DOMAIN_FINDING,),
        semantic_round=2,
        no_reduction=2,
        stage="plateau_recorded",
    )
    runnable = _target(SOURCE_TARGET, findings=(SOURCE_FINDING,))

    action = plan_next_protocol_25(_state(plateaued, runnable))

    assert action is not None
    assert action.kind == "resolve_target"
    assert action.participating_target_ids == (SOURCE_TARGET,)


@pytest.mark.integration
def test_third_round_ceiling_blocks_without_fabricating_plateau() -> None:
    state = _state(
        _target(
            DOMAIN_TARGET,
            findings=(DOMAIN_FINDING, SOURCE_FINDING),
            unresolved=(SOURCE_FINDING,),
            semantic_round=3,
            no_reduction=0,
        )
    )

    assert plan_next_protocol_25(state) == Protocol25ControllerActionV1(
        kind="accept_roots", source_id=SOURCE
    )
    assert plan_next_protocol_25(replace(state, rooted_source_ids=(SOURCE,))) == Protocol25ControllerActionV1(
        kind="terminal_blocked_incomplete"
    )


@pytest.mark.integration
def test_audit_contract_exhaustion_blocks_incomplete() -> None:
    state = _state(
        _target(DOMAIN_TARGET, audit_state="failed"),
        epoch=None,
    )
    assert plan_next_protocol_25(state) == Protocol25ControllerActionV1(
        kind="terminal_blocked_incomplete"
    )


@pytest.mark.integration
def test_resource_exhaustion_pauses_without_action() -> None:
    state = _state(
        _target(DOMAIN_TARGET, findings=(DOMAIN_FINDING,)),
        paused=True,
    )
    backend = _ScriptedBackend((state,), ())

    result = Protocol25Controller(backend).run_until_stopped()

    assert result.status == "paused"
    assert result.steps == 0


@pytest.mark.integration
def test_indeterminate_execution_is_not_redispatched() -> None:
    state = _state(
        _target(DOMAIN_TARGET, findings=(DOMAIN_FINDING,)),
        indeterminate=True,
    )
    terminal = replace(
        state,
        indeterminate_execution=False,
        terminal_state="blocked_incomplete",
    )
    backend = _ScriptedBackend(
        (state, terminal),
        (Protocol25ControllerActionV1(kind="terminal_blocked_incomplete"),),
    )

    result = Protocol25Controller(backend).run_until_stopped()

    assert result.status == "failed"
    assert backend.provider_actions == []
