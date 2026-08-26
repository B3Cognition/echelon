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

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.controller import (
    Protocol22ControllerError,
    _fault,
)
from harness.re_v2.protocol_22.budget import evaluate_budget_v22
from harness.re_v2.protocol_22.execution import Committed
from harness.re_v2.protocol_22.ledger import WorkItemFailureReceiptV1
from harness.re_v2.protocol_22.model import WorkItemV2
from harness.re_v2.protocol_22.recovery import Protocol22RunContext
from harness.re_v2.protocol_22.schema import Protocol22SchemaError, load_canonical_object
from harness.re_v2.protocol_24.controller import Protocol24Controller
from harness.re_v2.run_store import load_run_manifest

from .artifacts import (
    AuditCandidateV1,
    SemanticResolutionOverlayV1,
    SourceCompositionAssessmentV1,
    TargetClosureAssessmentV1,
)
from .events import PROTOCOL_25_EVENTS, Protocol25ReplayState
from .runtime import (
    Protocol25RuntimeError,
    SemanticCandidateInputV1,
    SemanticCertificationResultV1,
    SemanticContextV1,
)


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

    missing_roots = tuple(
        source for source in state.source_ids if source not in state.rooted_source_ids
    )
    if missing_roots:
        return Protocol25ControllerActionV1(
            kind="accept_roots", source_id=missing_roots[0]
        )
    if blocked_incomplete:
        return Protocol25ControllerActionV1(kind="terminal_blocked_incomplete")
    if blocked_plateau:
        return Protocol25ControllerActionV1(kind="terminal_blocked_plateau")
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
            def protocol_25_fault(boundary: str) -> None:
                if fault_hook is not None:
                    fault_hook(boundary)
                prefix = "dispatch_started:"
                if not boundary.startswith(prefix):
                    return
                bind = getattr(context, "bind_semantic_dispatch", None)
                if callable(bind):
                    bind(boundary.removeprefix(prefix))

            super().__init__(context, protocol_25_fault)
        elif isinstance(context, Protocol25ControllerBackend):
            if fault_hook is not None and not callable(fault_hook):
                raise TypeError("Protocol25Controller fault_hook must be callable or null")
            self.context = context  # type: ignore[assignment]
            self.fault_hook = fault_hook
        else:
            raise TypeError(
                "Protocol25Controller requires a shared run context or protocol-2.5 backend"
            )

    def _certify_provider_candidate(
        self,
        item: WorkItemV2,
        committed: Committed,
        candidate_id: str,
    ) -> None:
        semantic_kind = item.output_key.artifact_kind
        if semantic_kind not in {
            "semantic-audit-findings",
            "semantic-resolution-overlay",
            "source-composition-assessment",
            "target-closure-assessment",
        }:
            super()._certify_provider_candidate(item, committed, candidate_id)
            return
        inventory = committed.closure.candidate_inventory
        entry = (
            inventory.entries[0]
            if inventory is not None and len(inventory.entries) == 1
            else None
        )
        if (
            entry is None
            or entry.relative_path
            != {
                "semantic-audit-findings": "audit.json",
                "semantic-resolution-overlay": "resolution.json",
                "source-composition-assessment": "closure.json",
                "target-closure-assessment": "closure.json",
            }[semantic_kind]
            or entry.object_kind != "regular"
            or entry.content_hash is None
        ):
            self._reject_candidate_before_artifact(
                item,
                committed,
                candidate_id,
                "candidate_tree_invalid",
            )
            return
        context_hash = committed.closure.execution_input.context_bundle_hash
        if context_hash is None:
            raise Protocol25ControllerError(
                "semantic audit candidate has no pinned context bundle"
            )
        try:
            context = load_canonical_object(
                self.context.object_store.read_blob(context_hash),
                SemanticContextV1.from_json_dict,
            )
            candidate = SemanticCandidateInputV1(
                candidate_id=candidate_id,
                execution_capture_hash=committed.closure.capture.identity,
                inventory=inventory,
                candidate_bytes=self.context.object_store.read_blob(entry.content_hash),
            )
            if semantic_kind == "semantic-audit-findings":
                result = self.context.semantic_runtime.certify_audit(  # type: ignore[attr-defined]
                    candidate,
                    artifact_key=item.output_key,
                    context=context,
                )
            elif semantic_kind == "semantic-resolution-overlay":
                ledger = self.context.ledger.replay()
                epochs = tuple(ledger.audit_epochs.values())  # type: ignore[attr-defined]
                if len(epochs) != 1:
                    raise Protocol25RuntimeError(
                        "resolution candidate has no unique frozen epoch"
                    )
                epoch = epochs[0]
                manifest = self.context.semantic_graph.manifest  # type: ignore[attr-defined]
                guidance_hash = (
                    None
                    if manifest.human_guidance is None
                    else manifest.human_guidance.object_hash
                )
                excluded = {
                    epoch.identity,
                    context.audit_target.identity,
                    *(
                        (guidance_hash,)
                        if guidance_hash is not None
                        else ()
                    ),
                }
                prior_overlay_hashes = tuple(
                    value
                    for value in item.output_key.dependency_hashes
                    if value not in excluded
                )
                result = self.context.semantic_runtime.certify_resolution(  # type: ignore[attr-defined]
                    candidate,
                    artifact_key=item.output_key,
                    context=context,
                    epoch=epoch,
                    semantic_round=len(prior_overlay_hashes) + 1,
                    prior_overlay_hashes=prior_overlay_hashes,
                    guidance_hash=guidance_hash,
                )
            elif semantic_kind == "target-closure-assessment":
                ledger = self.context.ledger.replay()
                epochs = tuple(ledger.audit_epochs.values())  # type: ignore[attr-defined]
                if len(epochs) != 1:
                    raise Protocol25RuntimeError(
                        "closure recheck candidate has no unique frozen epoch"
                    )
                epoch = epochs[0]
                overlay_hashes = tuple(
                    value
                    for value in item.output_key.dependency_hashes
                    if value != epoch.identity
                )
                if len(overlay_hashes) != 1:
                    raise Protocol25RuntimeError(
                        "closure recheck candidate has no unique resolution overlay"
                    )
                overlay = load_canonical_object(
                    self.context.object_store.read_blob(overlay_hashes[0]),
                    SemanticResolutionOverlayV1.from_json_dict,
                )
                result = self.context.semantic_runtime.certify_target_closure(  # type: ignore[attr-defined]
                    candidate,
                    artifact_key=item.output_key,
                    context=context,
                    epoch=epoch,
                    overlay=overlay,
                )
            else:
                ledger = self.context.ledger.replay()
                epochs = tuple(ledger.audit_epochs.values())  # type: ignore[attr-defined]
                if len(epochs) != 1:
                    raise Protocol25RuntimeError(
                        "source guard candidate has no unique frozen epoch"
                    )
                epoch = epochs[0]
                dependency_ids = set(item.output_key.dependency_hashes)
                target_assessments = tuple(
                    sorted(
                        (
                            assessment
                            for identity, assessment in ledger.target_closure_assessments.items()  # type: ignore[attr-defined]
                            if identity in dependency_ids
                        ),
                        key=lambda assessment: (
                            assessment.audit_target_id,
                            assessment.identity,
                        ),
                    )
                )
                overlay_hashes = {
                    assessment.resolution_overlay_hash
                    for assessment in target_assessments
                }
                overlays = tuple(
                    sorted(
                        (
                            load_canonical_object(
                                self.context.object_store.read_blob(overlay_hash),
                                SemanticResolutionOverlayV1.from_json_dict,
                            )
                            for overlay_hash in overlay_hashes
                        ),
                        key=lambda overlay: (
                            overlay.audit_target_id,
                            overlay.identity,
                        ),
                    )
                )
                expected_dependencies = {
                    epoch.identity,
                    *(item.identity for item in overlays),
                    *(item.identity for item in target_assessments),
                }
                if dependency_ids != expected_dependencies:
                    raise Protocol25RuntimeError(
                        "source guard dependency authority is not exact"
                    )
                source_id = context.audit_target.scope.source_id
                composed = self.context.semantic_runtime.build_composed_view(  # type: ignore[attr-defined]
                    context=context,
                    epoch=epoch,
                    source_id=source_id,
                    overlays=overlays,
                    target_assessments=target_assessments,
                )
                self.context.object_store.put_blob(
                    canonical_json_bytes(composed.to_json_dict())
                )
                result = self.context.semantic_runtime.certify_source_guard(  # type: ignore[attr-defined]
                    candidate,
                    artifact_key=item.output_key,
                    context=context,
                    epoch=epoch,
                    source_id=source_id,
                    overlays=overlays,
                    target_assessments=target_assessments,
                    composed_view=composed,
                )
        except (Protocol22SchemaError, Protocol25RuntimeError):
            self._reject_candidate_before_artifact(
                item,
                committed,
                candidate_id,
                "authorial_schema_invalid",
            )
            return
        self._record_semantic_result(item, candidate_id, result)

    def _record_semantic_result(
        self,
        item: WorkItemV2,
        candidate_id: str,
        result: SemanticCertificationResultV1,
    ) -> None:
        if (
            result.candidate_assessment.candidate_id != candidate_id
            or result.candidate_assessment.work_item_id != item.work_item_id
            or result.acceptance.artifact_key != item.output_key
        ):
            raise Protocol25ControllerError(
                "semantic certification result differs from dispatch authority"
            )
        normalized_hash = self.context.object_store.put_blob(
            result.normalized_authorial_payload_bytes
        )
        if (
            result.candidate_assessment.normalized_authorial_payload_hash
            != normalized_hash
        ):
            raise Protocol25ControllerError(
                "semantic candidate normalized payload authority mismatch"
            )
        artifact_hash = self.context.object_store.put_blob(result.artifact_bytes)
        if (
            artifact_hash != result.certification.artifact_hash
            or result.acceptance.artifact_hash != artifact_hash
            or result.acceptance.certification_receipt_id
            != result.certification.identity
        ):
            raise Protocol25ControllerError(
                "semantic certification artifact authority mismatch"
            )
        ledger = self.context.ledger
        record_semantic = getattr(ledger, "record_semantic_certification", None)
        if not callable(record_semantic):
            raise Protocol25ControllerError(
                "semantic run has no protocol-2.5 ledger"
            )
        record_semantic(result.certification)
        _fault(self.fault_hook, f"semantic_certification:{result.certification.identity}")
        ledger.record_candidate_assessment(result.candidate_assessment)
        _fault(
            self.fault_hook,
            f"candidate_assessment:{result.candidate_assessment.identity}",
        )
        self.context.event_store.append(
            "candidate_certified",
            {
                "candidate_assessment_id": result.candidate_assessment.identity,
                "candidate_id": candidate_id,
                "certification_receipt_id": result.certification.identity,
                "work_item_id": item.work_item_id,
            },
            occurred_at=self.context.clock(),
        )
        _fault(
            self.fault_hook,
            f"candidate_certified:{result.candidate_assessment.identity}",
        )
        ledger.record_artifact_acceptance(result.acceptance)
        _fault(
            self.fault_hook,
            f"artifact_acceptance_receipt:{result.acceptance.identity}",
        )
        self.context.event_store.append(
            "artifact_accepted",
            {
                "artifact_acceptance_receipt_id": result.acceptance.identity,
                "artifact_hash": result.acceptance.artifact_hash,
                "artifact_key_id": result.acceptance.artifact_key.identity,
                "candidate_assessment_id": result.candidate_assessment.identity,
                "certification_receipt_id": result.certification.identity,
                "work_item_id": item.work_item_id,
            },
            occurred_at=self.context.clock(),
        )
        _fault(self.fault_hook, f"artifact_accepted:{item.work_item_id}")
        self._publish_semantic_artifact_event(item, result)

    def _publish_semantic_artifact_event(
        self,
        item: WorkItemV2,
        result: SemanticCertificationResultV1,
    ) -> None:
        """Publish the typed semantic transition immediately after acceptance."""
        artifact = result.artifact
        if isinstance(artifact, AuditCandidateV1):
            event_type = "audit_candidate_accepted"
            payload = {
                "audit_candidate_authority_id": artifact.identity,
                "audit_target_id": artifact.audit_target_id,
            }
        else:
            replay = Protocol25ReplayState()
            for event in self.context.event_store.replay():
                replay.consume(event)
            operation = replay.semantic_operation
            if operation is None or operation.work_item_id != item.work_item_id:
                raise Protocol25ControllerError(
                    "accepted semantic artifact has no matching active operation"
                )
            common = {
                "semantic_round": operation.semantic_round,
                "source_cycle_id": operation.source_cycle_id,
                "source_id": operation.source_id,
                "work_item_id": item.work_item_id,
            }
            if isinstance(artifact, SemanticResolutionOverlayV1):
                if operation.event_type != "semantic_resolution_started":
                    raise Protocol25ControllerError(
                        "resolution artifact differs from active semantic operation"
                    )
                event_type = "semantic_resolution_accepted"
                payload = {
                    **common,
                    "audit_target_id": artifact.audit_target_id,
                    "resolution_overlay_id": artifact.identity,
                }
            elif isinstance(artifact, TargetClosureAssessmentV1):
                if operation.event_type != "closure_recheck_started":
                    raise Protocol25ControllerError(
                        "target assessment differs from active semantic operation"
                    )
                for observation in artifact.deferred_observations:
                    self.context.object_store.put_blob(
                        canonical_json_bytes(observation.to_json_dict())
                    )
                self.context.ledger.record_target_closure_assessment(artifact)
                event_type = "target_closure_assessed"
                payload = {
                    **common,
                    "audit_target_id": artifact.audit_target_id,
                    "target_closure_assessment_id": artifact.identity,
                }
            elif isinstance(artifact, SourceCompositionAssessmentV1):
                if operation.event_type != "source_composition_guard_started":
                    raise Protocol25ControllerError(
                        "source assessment differs from active semantic operation"
                    )
                for observation in artifact.deferred_observations:
                    self.context.object_store.put_blob(
                        canonical_json_bytes(observation.to_json_dict())
                    )
                self.context.ledger.record_source_composition_assessment(artifact)
                event_type = "source_composition_assessed"
                payload = {
                    **common,
                    "implicated_finding_ids": list(
                        artifact.implicated_finding_ids
                    ),
                    "passed": artifact.outcome == "passed",
                    "source_composition_assessment_id": artifact.identity,
                }
            else:
                raise Protocol25ControllerError(
                    "semantic certification produced an unsupported artifact"
                )
        self.context.event_store.append(
            event_type,
            payload,
            occurred_at=self.context.clock(),
        )
        _fault(self.fault_hook, f"{event_type}:{artifact.identity}")

    def _retry_or_fail_work_item(
        self,
        item: WorkItemV2,
        committed: Committed,
        *,
        candidate_id: str | None,
        candidate_assessment_id: str | None,
        failure_class: Literal[
            "result_contract", "artifact_contract", "minimum_utility"
        ],
        reason_code: str,
        diagnostics: tuple[str, ...],
    ) -> None:
        """Account a semantic retry against the protocol-2.5 event vocabulary."""
        events = self.context.event_store.replay()
        manifest = load_run_manifest(self.context.paths.root.parent)
        budget = evaluate_budget_v22(
            manifest.initial_budget_policy,
            events,
            (),
            self.context.clock(),
            event_protocol=PROTOCOL_25_EVENTS,
        )
        if budget.item_attempt_available(item):
            return
        receipt = WorkItemFailureReceiptV1(
            schema_version=1,
            work_item_id=item.work_item_id,
            dispatch_id=committed.dispatch_id,
            candidate_id=candidate_id,
            candidate_assessment_id=candidate_assessment_id,
            execution_capture_hash=committed.closure.capture.identity,
            dispatch_abandonment_event_hash=None,
            failure_class=failure_class,
            reason_code=reason_code,
            normalized_diagnostics=diagnostics,
        )
        self.context.ledger.record_work_item_failure(receipt)
        _fault(self.fault_hook, f"work_item_failure_receipt:{receipt.identity}")
        self.context.event_store.append(
            "work_item_failed",
            {
                "failure_class": receipt.failure_class,
                "failure_receipt_id": receipt.identity,
                "reason_code": receipt.reason_code,
                "work_item_id": receipt.work_item_id,
            },
            occurred_at=self.context.clock(),
        )
        _fault(self.fault_hook, f"work_item_failed:{receipt.identity}")

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
