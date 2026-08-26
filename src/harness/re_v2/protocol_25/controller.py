"""Narrow protocol-2.5 semantic controller over the shared RE v2 kernel.

The controller owns routing, never semantic authority.  Each call to the
backend returns a fresh state derived from the durable event/ledger chains;
``apply_controller_action`` is responsible for publishing exactly one durable
transition through the shared dispatch/capture/commit machinery.  Protocol
2.5 recovery supplies that backend.  Keeping the planner here pure makes the
closed transition system independently testable without a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, ClassVar, Literal, Protocol, runtime_checkable

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.controller import Protocol22ControllerError
from harness.re_v2.protocol_22.recovery import Protocol22RunContext
from harness.re_v2.protocol_24.controller import Protocol24Controller


AuditStateV1 = Literal["pending", "accepted", "failed"]
TargetStageV1 = Literal[
    "idle",
    "resolution_accepted",
    "assessment_accepted",
    "plateau_recorded",
]
GuardStageV1 = Literal[
    "pending",
    "passed",
    "failed",
    "receipts_recorded",
]
TerminalStateV1 = Literal[
    "complete",
    "next_epoch_required",
    "blocked_incomplete",
    "blocked_plateau",
]
ActionKindV1 = Literal[
    "run_prerequisite",
    "audit_target",
    "freeze_epoch",
    "resolve_target",
    "recheck_target",
    "guard_source",
    "record_finding_receipts",
    "record_progress",
    "record_plateau",
    "accept_roots",
    "terminal_complete",
    "terminal_next_epoch",
    "terminal_blocked_incomplete",
    "terminal_blocked_plateau",
]


class Protocol25ControllerError(Protocol22ControllerError):
    """Raised when durable protocol-2.5 authority has no legal next action."""


def _ordered_unique(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if any(not isinstance(value, str) or not value for value in values):
        raise Protocol25ControllerError(f"{field} must contain nonempty IDs")
    if values != tuple(sorted(set(values))):
        raise Protocol25ControllerError(f"{field} must be sorted and unique")
    return values


@dataclass(frozen=True, slots=True)
class SemanticTargetControllerStateV1:
    audit_target_id: str
    source_id: str
    audit_state: AuditStateV1
    frozen_finding_ids: tuple[str, ...] = ()
    unresolved_finding_ids: tuple[str, ...] = ()
    semantic_round: int = 0
    no_reduction_rounds: int = 0
    stage: TargetStageV1 = "idle"

    def __post_init__(self) -> None:
        if not self.audit_target_id or not self.source_id:
            raise Protocol25ControllerError("semantic target IDs must be nonempty")
        if self.audit_state not in {"pending", "accepted", "failed"}:
            raise Protocol25ControllerError("semantic target audit state is invalid")
        frozen = _ordered_unique(self.frozen_finding_ids, "frozen finding IDs")
        unresolved = _ordered_unique(
            self.unresolved_finding_ids, "unresolved finding IDs"
        )
        if not set(unresolved).issubset(frozen):
            raise Protocol25ControllerError(
                "unresolved findings must belong to the frozen target set"
            )
        if self.audit_state != "accepted" and (frozen or unresolved):
            raise Protocol25ControllerError(
                "unaccepted audit target cannot expose frozen findings"
            )
        if (
            not isinstance(self.semantic_round, int)
            or isinstance(self.semantic_round, bool)
            or self.semantic_round < 0
            or not isinstance(self.no_reduction_rounds, int)
            or isinstance(self.no_reduction_rounds, bool)
            or self.no_reduction_rounds < 0
        ):
            raise Protocol25ControllerError("semantic counters must be nonnegative")
        if self.stage not in {
            "idle",
            "resolution_accepted",
            "assessment_accepted",
            "plateau_recorded",
        }:
            raise Protocol25ControllerError("semantic target stage is invalid")
        if not unresolved and self.stage in {
            "resolution_accepted",
            "assessment_accepted",
        }:
            raise Protocol25ControllerError(
                "closed target cannot retain an active resolution stage"
            )
        object.__setattr__(self, "frozen_finding_ids", frozen)
        object.__setattr__(self, "unresolved_finding_ids", unresolved)


@dataclass(frozen=True, slots=True)
class SemanticSourceCycleStateV1:
    source_id: str
    source_cycle_id: str
    semantic_round: int
    participating_target_ids: tuple[str, ...]
    guard_stage: GuardStageV1 = "pending"

    def __post_init__(self) -> None:
        if not self.source_id or not self.source_cycle_id:
            raise Protocol25ControllerError("source cycle IDs must be nonempty")
        if (
            not isinstance(self.semantic_round, int)
            or isinstance(self.semantic_round, bool)
            or self.semantic_round <= 0
        ):
            raise Protocol25ControllerError("source cycle round must be positive")
        participants = _ordered_unique(
            self.participating_target_ids, "source-cycle target IDs"
        )
        if not participants:
            raise Protocol25ControllerError("source cycle requires a target")
        if self.guard_stage not in {"pending", "passed", "failed", "receipts_recorded"}:
            raise Protocol25ControllerError("source guard stage is invalid")
        object.__setattr__(self, "participating_target_ids", participants)


@dataclass(frozen=True, slots=True)
class Protocol25ControllerStateV1:
    prerequisites_complete: bool
    prerequisites_failed: bool
    paused_resource: bool
    audit_epoch_id: str | None
    targets: tuple[SemanticTargetControllerStateV1, ...]
    source_cycles: tuple[SemanticSourceCycleStateV1, ...] = ()
    rooted_source_ids: tuple[str, ...] = ()
    deferred_observation_ids: tuple[str, ...] = ()
    terminal_state: TerminalStateV1 | None = None
    indeterminate_execution: bool = False

    def __post_init__(self) -> None:
        for field in (
            "prerequisites_complete",
            "prerequisites_failed",
            "paused_resource",
            "indeterminate_execution",
        ):
            if not isinstance(getattr(self, field), bool):
                raise Protocol25ControllerError(f"{field} must be boolean")
        if self.prerequisites_complete and self.prerequisites_failed:
            raise Protocol25ControllerError(
                "prerequisites cannot be complete and failed"
            )
        if any(
            not isinstance(item, SemanticTargetControllerStateV1)
            for item in self.targets
        ):
            raise Protocol25ControllerError("controller state semantic targets are invalid")
        if self.prerequisites_complete and not self.targets:
            raise Protocol25ControllerError(
                "completed prerequisites require materialized semantic targets"
            )
        target_keys = tuple(item.audit_target_id for item in self.targets)
        if target_keys != tuple(sorted(set(target_keys))):
            raise Protocol25ControllerError("semantic targets must be sorted and unique")
        if any(
            not isinstance(item, SemanticSourceCycleStateV1)
            for item in self.source_cycles
        ):
            raise Protocol25ControllerError("source cycles are invalid")
        cycle_sources = tuple(item.source_id for item in self.source_cycles)
        if cycle_sources != tuple(sorted(set(cycle_sources))):
            raise Protocol25ControllerError(
                "at most one active source cycle is allowed per source"
            )
        by_target = {item.audit_target_id: item for item in self.targets}
        for cycle in self.source_cycles:
            participants = tuple(by_target[item] for item in cycle.participating_target_ids)
            if any(item.source_id != cycle.source_id for item in participants):
                raise Protocol25ControllerError(
                    "source cycle contains a target from another source"
                )
            if any(item.semantic_round + 1 != cycle.semantic_round for item in participants):
                raise Protocol25ControllerError(
                    "source cycle round must be the next round for every target"
                )
        rooted = _ordered_unique(self.rooted_source_ids, "rooted source IDs")
        deferred = _ordered_unique(
            self.deferred_observation_ids, "deferred observation IDs"
        )
        source_ids = {item.source_id for item in self.targets}
        if not set(rooted).issubset(source_ids):
            raise Protocol25ControllerError("rooted source is outside selected scope")
        if self.audit_epoch_id is None and any(
            item.audit_state == "accepted" and item.frozen_finding_ids
            for item in self.targets
        ):
            # Findings are certified before epoch freeze, so this is legal.  Active
            # cycles and roots, however, never are.
            pass
        if self.audit_epoch_id is None and (self.source_cycles or rooted):
            raise Protocol25ControllerError(
                "semantic cycles and roots require a frozen audit epoch"
            )
        if self.terminal_state is not None and self.source_cycles:
            raise Protocol25ControllerError("terminal state cannot retain active cycles")
        object.__setattr__(self, "rooted_source_ids", rooted)
        object.__setattr__(self, "deferred_observation_ids", deferred)

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.source_id for item in self.targets}))


@dataclass(frozen=True, slots=True)
class Protocol25ControllerActionV1:
    kind: ActionKindV1
    audit_target_id: str | None = None
    source_id: str | None = None
    source_cycle_id: str | None = None
    semantic_round: int | None = None
    participating_target_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in self.KINDS:
            raise Protocol25ControllerError("controller action kind is invalid")
        participants = _ordered_unique(
            self.participating_target_ids, "action target IDs"
        )
        object.__setattr__(self, "participating_target_ids", participants)
        if self.semantic_round is not None and (
            not isinstance(self.semantic_round, int)
            or isinstance(self.semantic_round, bool)
            or self.semantic_round <= 0
        ):
            raise Protocol25ControllerError("action semantic round must be positive")
        target_operation = self.kind in {"resolve_target", "recheck_target"}
        source_operation = self.kind in {
            "guard_source",
            "record_finding_receipts",
            "record_progress",
        }
        if target_operation or source_operation:
            if (
                not self.source_id
                or not self.source_cycle_id
                or self.semantic_round is None
                or not participants
            ):
                raise Protocol25ControllerError(
                    "semantic operation action is missing its closed routing fields"
                )
            if target_operation != (self.audit_target_id is not None):
                raise Protocol25ControllerError(
                    "semantic target operation has inconsistent target identity"
                )
            return
        if self.kind == "audit_target":
            valid = self.audit_target_id is not None
        elif self.kind == "record_plateau":
            valid = (
                self.audit_target_id is not None
                and self.source_id is not None
                and self.semantic_round is not None
            )
        elif self.kind == "accept_roots":
            valid = self.source_id is not None
        else:
            valid = True
        allowed_values = {
            "audit_target_id": (
                self.kind in {"audit_target", "record_plateau"}
            ),
            "source_id": self.kind in {"record_plateau", "accept_roots"},
            "source_cycle_id": False,
            "semantic_round": self.kind == "record_plateau",
            "participating_target_ids": False,
        }
        actual_values = {
            "audit_target_id": self.audit_target_id is not None,
            "source_id": self.source_id is not None,
            "source_cycle_id": self.source_cycle_id is not None,
            "semantic_round": self.semantic_round is not None,
            "participating_target_ids": bool(participants),
        }
        if not valid or actual_values != allowed_values:
            raise Protocol25ControllerError(
                "controller action fields do not match its closed action kind"
            )

    KINDS: ClassVar[frozenset[str]] = frozenset(
        {
            "run_prerequisite",
            "audit_target",
            "freeze_epoch",
            "resolve_target",
            "recheck_target",
            "guard_source",
            "record_finding_receipts",
            "record_progress",
            "record_plateau",
            "accept_roots",
            "terminal_complete",
            "terminal_next_epoch",
            "terminal_blocked_incomplete",
            "terminal_blocked_plateau",
        }
    )


@dataclass(frozen=True, slots=True)
class Protocol25ControllerResult:
    status: Literal["completed", "failed", "paused"]
    state: Protocol25ControllerStateV1
    steps: int


@runtime_checkable
class Protocol25ControllerBackend(Protocol):
    """Fresh durable replay and one-transition publication seam.

    The production implementation is protocol-2.5 recovery.  It must derive
    every returned state from authenticated ledger/events and execute provider
    actions through the inherited shared dispatch path.
    """

    def recover_controller_state(self) -> Protocol25ControllerStateV1: ...

    def apply_controller_action(self, action: Protocol25ControllerActionV1) -> None: ...


def plan_next_protocol_25(
    state: Protocol25ControllerStateV1,
) -> Protocol25ControllerActionV1 | None:
    """Return the one legal next L3 action from fresh replay authority."""
    if not isinstance(state, Protocol25ControllerStateV1):
        raise Protocol25ControllerError("planner requires Protocol25ControllerStateV1")
    if state.terminal_state is not None or state.paused_resource:
        return None
    if state.indeterminate_execution:
        return Protocol25ControllerActionV1(kind="terminal_blocked_incomplete")
    if state.prerequisites_failed:
        return Protocol25ControllerActionV1(kind="terminal_blocked_incomplete")
    if not state.prerequisites_complete:
        return Protocol25ControllerActionV1(kind="run_prerequisite")

    if state.audit_epoch_id is None:
        pending = [item for item in state.targets if item.audit_state == "pending"]
        if pending:
            return Protocol25ControllerActionV1(
                kind="audit_target", audit_target_id=pending[0].audit_target_id
            )
        if any(item.audit_state == "failed" for item in state.targets):
            return Protocol25ControllerActionV1(kind="terminal_blocked_incomplete")
        return Protocol25ControllerActionV1(kind="freeze_epoch")

    by_target = {item.audit_target_id: item for item in state.targets}
    active_by_source: dict[str, SemanticSourceCycleStateV1] = {
        item.source_id: item for item in state.source_cycles
    }
    blocked_plateau = False
    blocked_incomplete = False
    for source_id in state.source_ids:
        cycle = active_by_source.get(source_id)
        if cycle is None:
            unresolved = tuple(
                item
                for item in state.targets
                if item.source_id == source_id and item.unresolved_finding_ids
            )
            plateau = tuple(
                item
                for item in unresolved
                if item.no_reduction_rounds >= 2 or item.semantic_round >= 3
            )
            unrecorded_plateau = tuple(
                item for item in plateau if item.stage != "plateau_recorded"
            )
            if unrecorded_plateau:
                target = unrecorded_plateau[0]
                # The event protocol permits semantic_plateau only after two
                # unchanged rounds.  A pure three-round ceiling with reductions
                # is blocked incomplete without fabricating plateau authority.
                if target.no_reduction_rounds >= 2:
                    return Protocol25ControllerActionV1(
                        kind="record_plateau",
                        audit_target_id=target.audit_target_id,
                        source_id=source_id,
                        semantic_round=target.semantic_round,
                    )
            blocked_plateau = blocked_plateau or any(
                item.no_reduction_rounds >= 2 for item in plateau
            )
            blocked_incomplete = blocked_incomplete or any(
                item.semantic_round >= 3 and item.no_reduction_rounds < 2
                for item in plateau
            )
            runnable = tuple(item for item in unresolved if item not in plateau)
            if runnable:
                next_rounds = {item.semantic_round + 1 for item in runnable}
                if len(next_rounds) != 1:
                    raise Protocol25ControllerError(
                        "source targets disagree on the next semantic round"
                    )
                participants = tuple(
                    sorted(item.audit_target_id for item in runnable)
                )
                first = min(runnable, key=lambda item: item.audit_target_id)
                return Protocol25ControllerActionV1(
                    kind="resolve_target",
                    audit_target_id=first.audit_target_id,
                    source_id=source_id,
                    source_cycle_id=_source_cycle_id(
                        state.audit_epoch_id,
                        source_id,
                        next(iter(next_rounds)),
                    ),
                    semantic_round=next(iter(next_rounds)),
                    participating_target_ids=participants,
                )
            continue

        targets = tuple(by_target[item] for item in cycle.participating_target_ids)
        for target in targets:
            if target.stage == "idle":
                return _target_action("resolve_target", target, cycle)
            if target.stage == "resolution_accepted":
                return _target_action("recheck_target", target, cycle)
        if any(item.stage != "assessment_accepted" for item in targets):
            raise Protocol25ControllerError(
                "active source cycle has no legal target transition"
            )
        if cycle.guard_stage == "pending":
            return Protocol25ControllerActionV1(
                kind="guard_source",
                source_id=cycle.source_id,
                source_cycle_id=cycle.source_cycle_id,
                semantic_round=cycle.semantic_round,
                participating_target_ids=cycle.participating_target_ids,
            )
        if cycle.guard_stage == "passed":
            return Protocol25ControllerActionV1(
                kind="record_finding_receipts",
                source_id=cycle.source_id,
                source_cycle_id=cycle.source_cycle_id,
                semantic_round=cycle.semantic_round,
                participating_target_ids=cycle.participating_target_ids,
            )
        return Protocol25ControllerActionV1(
            kind="record_progress",
            source_id=cycle.source_id,
            source_cycle_id=cycle.source_cycle_id,
            semantic_round=cycle.semantic_round,
            participating_target_ids=cycle.participating_target_ids,
        )

    if blocked_incomplete:
        return Protocol25ControllerActionV1(kind="terminal_blocked_incomplete")
    if blocked_plateau:
        return Protocol25ControllerActionV1(kind="terminal_blocked_plateau")
    missing_roots = tuple(
        source for source in state.source_ids if source not in state.rooted_source_ids
    )
    if missing_roots:
        return Protocol25ControllerActionV1(
            kind="accept_roots", source_id=missing_roots[0]
        )
    return Protocol25ControllerActionV1(
        kind=(
            "terminal_next_epoch"
            if state.deferred_observation_ids
            else "terminal_complete"
        )
    )


def _target_action(
    kind: Literal["resolve_target", "recheck_target"],
    target: SemanticTargetControllerStateV1,
    cycle: SemanticSourceCycleStateV1,
) -> Protocol25ControllerActionV1:
    return Protocol25ControllerActionV1(
        kind=kind,
        audit_target_id=target.audit_target_id,
        source_id=cycle.source_id,
        source_cycle_id=cycle.source_cycle_id,
        semantic_round=cycle.semantic_round,
        participating_target_ids=cycle.participating_target_ids,
    )


def _source_cycle_id(epoch_id: str, source_id: str, semantic_round: int) -> str:
    digest = content_digest(
        {
            "audit_epoch_id": epoch_id,
            "semantic_round": semantic_round,
            "source_id": source_id,
        }
    )
    return f"cycle-{digest.removeprefix('sha256:')}"


class Protocol25Controller(Protocol24Controller):
    """Drive one durable semantic transition at a time until a closed stop."""

    def __init__(
        self,
        context: Protocol22RunContext | Protocol25ControllerBackend,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        if isinstance(context, Protocol22RunContext):
            super().__init__(context, fault_hook)
        elif isinstance(context, Protocol25ControllerBackend):
            if fault_hook is not None and not callable(fault_hook):
                raise TypeError("Protocol25Controller fault_hook must be callable or null")
            self.context = context  # type: ignore[assignment]
            self.fault_hook = fault_hook
        else:
            raise TypeError(
                "Protocol25Controller requires a shared run context or protocol-2.5 backend"
            )

    def run_until_stopped(self) -> Protocol25ControllerResult:
        backend = self.context
        if not isinstance(backend, Protocol25ControllerBackend):
            raise Protocol25ControllerError(
                "protocol-2.5 run context has no durable controller backend"
            )
        initial = backend.recover_controller_state()
        maximum_steps = max(32, len(initial.targets) * 32 + len(initial.source_ids) * 8)
        for step in range(maximum_steps + 1):
            state = backend.recover_controller_state()
            action = plan_next_protocol_25(state)
            if action is None:
                if state.paused_resource:
                    return Protocol25ControllerResult("paused", state, step)
                if state.terminal_state in {"complete", "next_epoch_required"}:
                    return Protocol25ControllerResult("completed", state, step)
                if state.terminal_state in {"blocked_incomplete", "blocked_plateau"}:
                    return Protocol25ControllerResult("failed", state, step)
                raise Protocol25ControllerError(
                    "semantic planner stopped without durable terminal authority"
                )
            backend.apply_controller_action(action)
        raise Protocol25ControllerError(
            "protocol-2.5 controller exceeded its bounded transition count"
        )


__all__ = (
    "Protocol25Controller",
    "Protocol25ControllerActionV1",
    "Protocol25ControllerBackend",
    "Protocol25ControllerError",
    "Protocol25ControllerResult",
    "Protocol25ControllerStateV1",
    "SemanticSourceCycleStateV1",
    "SemanticTargetControllerStateV1",
    "plan_next_protocol_25",
)
