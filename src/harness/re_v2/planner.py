"""Deterministic artifact-DAG planning and shadow explanations for RE v2."""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Iterable, Literal, Mapping

from .budget import BudgetDecision
from .canonical import content_digest
from .ledger import LedgerView
from .model import ArtifactKey, ArtifactReceipt, CertificationReceipt, WorkItem, WorkTemplate


_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_GLOBAL_GENERATION_DIMENSIONS = ("tokens", "active_ms")


class ReV2PlanError(ValueError):
    """Raised when a work graph or planning authority is invalid."""


@dataclass(frozen=True, slots=True)
class WorkGraph:
    """One canonical validated graph bound to source, partitions, and goals."""

    templates: tuple[WorkTemplate, ...]
    requested_goals: tuple[str, ...]
    source_snapshot_id: str | None
    partition_manifest_id: str | None


@dataclass(frozen=True, slots=True)
class PlanExplanation:
    """One stable shadow-planning outcome for a graph template."""

    work_item_id: str
    action: Literal[
        "reuse",
        "generate",
        "blocked_dependency",
        "blocked_budget",
        "reject_incompatible",
    ]
    reason_code: str
    reason: str


@dataclass(frozen=True, slots=True)
class PlanDecision:
    """Immutable ready queue plus exactly one explanation per template."""

    ready: tuple[WorkItem, ...]
    explanations: Mapping[str, PlanExplanation]

    def __post_init__(self) -> None:
        object.__setattr__(self, "ready", tuple(self.ready))
        object.__setattr__(
            self,
            "explanations",
            MappingProxyType(dict(sorted(self.explanations.items()))),
        )


def validate_work_graph(
    templates: Iterable[WorkTemplate],
    requested_goals: Iterable[str] | None = None,
    *,
    source_snapshot_id: str | None = None,
    partition_manifest_id: str | None = None,
) -> WorkGraph:
    """Validate and canonicalize templates independently of their input order."""
    try:
        supplied = tuple(templates)
    except TypeError as exc:
        raise ReV2PlanError("templates must be an iterable of WorkTemplate instances") from exc
    if any(type(item) is not WorkTemplate for item in supplied):
        raise ReV2PlanError("every graph node must be a canonical WorkTemplate instance")

    by_id: dict[str, WorkTemplate] = {}
    logical_outputs: dict[tuple[str, str], str] = {}
    for item in supplied:
        template_id = item.template_id
        if template_id in by_id:
            raise ReV2PlanError(f"duplicate template ID: {template_id}")
        by_id[template_id] = item
        logical_output = (item.artifact_kind, item.layer)
        previous = logical_outputs.get(logical_output)
        if previous is not None:
            raise ReV2PlanError(
                "duplicate logical output tuple: "
                f"{item.artifact_kind}/{item.layer}"
            )
        logical_outputs[logical_output] = template_id

    for template_id, item in sorted(by_id.items()):
        for required_id in item.required_template_ids:
            if required_id == template_id:
                raise ReV2PlanError(f"template {template_id} has a self dependency")
            if required_id not in by_id:
                raise ReV2PlanError(
                    f"template {template_id} has missing dependency {required_id}"
                )
    _topological_order(by_id, frozenset(by_id))

    available_goals = {item.goal_id for item in supplied}
    selected_goals = available_goals if requested_goals is None else set(
        _goals(requested_goals)
    )
    unknown = selected_goals - available_goals
    if unknown:
        raise ReV2PlanError(
            f"unknown requested goal: {', '.join(sorted(unknown))}"
        )
    canonical_goals = tuple(sorted(selected_goals))
    if source_snapshot_id is not None:
        _digest(source_snapshot_id, "source_snapshot_id")
    if partition_manifest_id is not None:
        _digest(partition_manifest_id, "partition_manifest_id")
    if (source_snapshot_id is None) != (partition_manifest_id is None):
        raise ReV2PlanError(
            "source_snapshot_id and partition_manifest_id must be supplied together"
        )
    return WorkGraph(
        templates=tuple(by_id[key] for key in sorted(by_id)),
        requested_goals=canonical_goals,
        source_snapshot_id=source_snapshot_id,
        partition_manifest_id=partition_manifest_id,
    )


def plan_next(
    graph: WorkGraph,
    ledger: LedgerView,
    budget: BudgetDecision,
    requested_goals: Iterable[str] | None = None,
) -> PlanDecision:
    """Derive the exact dependency-complete delta without mutating authority."""
    if type(graph) is not WorkGraph:
        raise ReV2PlanError("graph must be a validated WorkGraph")
    if type(ledger) is not LedgerView:
        raise ReV2PlanError("ledger must be a replayed LedgerView")
    if type(budget) is not BudgetDecision:
        raise ReV2PlanError("budget must be a BudgetDecision")
    source_snapshot_id, partition_manifest_id = _planning_context(graph, ledger)
    by_id = {item.template_id: item for item in graph.templates}
    selected_goals = graph.requested_goals
    if requested_goals is not None:
        selected_goals = tuple(sorted(_goals(requested_goals)))
        unknown = set(selected_goals) - set(graph.requested_goals)
        if unknown:
            raise ReV2PlanError(
                "planning goal is outside the validated requested goals: "
                f"{', '.join(sorted(unknown))}"
            )
    active = _goal_closure(by_id, selected_goals)
    accepted_hashes: dict[str, str] = {}
    ready: list[WorkItem] = []
    explanations: dict[str, PlanExplanation] = {}

    for template_id in sorted(by_id):
        if template_id not in active:
            explanations[template_id] = PlanExplanation(
                work_item_id=template_id,
                action="blocked_dependency",
                reason_code="goal_not_requested",
                reason="Template is outside the requested-goal dependency closure.",
            )

    for template_id in _topological_order(by_id, active):
        template = by_id[template_id]
        unavailable = tuple(
            dependency_id
            for dependency_id in template.required_template_ids
            if dependency_id not in accepted_hashes
        )
        if unavailable:
            explanations[template_id] = PlanExplanation(
                work_item_id=template_id,
                action="blocked_dependency",
                reason_code="prerequisite_artifact_unavailable",
                reason=(
                    "Exact accepted prerequisite artifacts are unavailable: "
                    + ", ".join(unavailable)
                    + "."
                ),
            )
            continue

        dependency_hashes = tuple(
            sorted(accepted_hashes[dependency_id] for dependency_id in template.required_template_ids)
        )
        item = _instantiate(
            template,
            source_snapshot_id=source_snapshot_id,
            partition_manifest_id=partition_manifest_id,
            dependency_hashes=dependency_hashes,
        )
        receipt, incompatibility = _resolve_receipt(item, ledger)
        if incompatibility is not None:
            explanations[template_id] = PlanExplanation(
                work_item_id=item.work_item_id,
                action="reject_incompatible",
                reason_code=incompatibility,
                reason=(
                    "An accepted receipt for this logical output does not match "
                    "the exact artifact key and certification required by this work item."
                ),
            )
            continue
        if receipt is not None:
            accepted_hashes[template_id] = receipt.artifact_hash
            explanations[template_id] = PlanExplanation(
                work_item_id=item.work_item_id,
                action="reuse",
                reason_code="accepted_exact_artifact",
                reason="A replay-validated accepted artifact exactly matches the expected key.",
            )
            continue

        exhausted = _generation_budget_exhaustion(item, budget)
        if exhausted is not None:
            explanations[template_id] = PlanExplanation(
                work_item_id=item.work_item_id,
                action="blocked_budget",
                reason_code=f"{exhausted}_exhausted",
                reason=f"The relevant {exhausted} budget is exhausted for this generation.",
            )
            continue

        ready.append(item)
        explanations[template_id] = PlanExplanation(
            work_item_id=item.work_item_id,
            action="generate",
            reason_code="dependency_complete_uncertified",
            reason="All exact prerequisites are accepted and no matching artifact is certified.",
        )

    if set(explanations) != set(by_id):
        raise ReV2PlanError("planner failed to explain every template exactly once")
    return PlanDecision(
        ready=tuple(sorted(ready, key=lambda item: (item.template_id, item.work_item_id))),
        explanations=explanations,
    )


def build_initial_inventory_graph(
    source_snapshot_id: str,
    partition_manifest_id: str,
) -> WorkGraph:
    """Register only EGR-164's deterministic source and partition L0 work."""
    source_inventory = WorkTemplate(
        goal_id="inventory",
        artifact_kind="source-inventory",
        layer="L0",
        producer_id="deterministic-source-inventory",
        producer_protocol_version="re-v2-l0-v1",
        layer_policy_hash=content_digest(
            {"artifact_kind": "source-inventory", "policy_version": "egr-164-v1"}
        ),
        required_template_ids=(),
        verifier_id="deterministic-inventory-verifier",
        verifier_version="v1",
        result_contract_id="deterministic-inventory-v1",
        max_provider_attempts=1,
        max_generation_attempts=1,
        max_semantic_rounds=0,
        max_result_contract_retries=0,
    )
    partition_inventory = WorkTemplate(
        goal_id="inventory",
        artifact_kind="partition-inventory",
        layer="L0",
        producer_id="deterministic-partition-inventory",
        producer_protocol_version="re-v2-l0-v1",
        layer_policy_hash=content_digest(
            {"artifact_kind": "partition-inventory", "policy_version": "egr-164-v1"}
        ),
        required_template_ids=(source_inventory.template_id,),
        verifier_id="deterministic-inventory-verifier",
        verifier_version="v1",
        result_contract_id="deterministic-inventory-v1",
        max_provider_attempts=1,
        max_generation_attempts=1,
        max_semantic_rounds=0,
        max_result_contract_retries=0,
    )
    return validate_work_graph(
        (source_inventory, partition_inventory),
        requested_goals=("inventory",),
        source_snapshot_id=source_snapshot_id,
        partition_manifest_id=partition_manifest_id,
    )


def _goal_closure(
    by_id: Mapping[str, WorkTemplate], requested_goals: tuple[str, ...]
) -> frozenset[str]:
    active = {
        template_id
        for template_id, item in by_id.items()
        if item.goal_id in requested_goals
    }
    pending = list(active)
    while pending:
        template_id = pending.pop()
        for required_id in by_id[template_id].required_template_ids:
            if required_id not in active:
                active.add(required_id)
                pending.append(required_id)
    return frozenset(active)


def _topological_order(
    by_id: Mapping[str, WorkTemplate], active: frozenset[str]
) -> tuple[str, ...]:
    ordered: list[str] = []
    state: dict[str, Literal["visiting", "visited"]] = {}
    for root_id in sorted(active):
        if root_id in state:
            continue
        state[root_id] = "visiting"
        stack: list[tuple[str, int]] = [(root_id, 0)]
        while stack:
            template_id, dependency_index = stack[-1]
            dependencies = by_id[template_id].required_template_ids
            while (
                dependency_index < len(dependencies)
                and dependencies[dependency_index] not in active
            ):
                dependency_index += 1
            if dependency_index == len(dependencies):
                stack.pop()
                state[template_id] = "visited"
                ordered.append(template_id)
                continue

            dependency_id = dependencies[dependency_index]
            stack[-1] = (template_id, dependency_index + 1)
            dependency_state = state.get(dependency_id)
            if dependency_state == "visiting":
                raise ReV2PlanError(
                    f"work graph contains a cycle at {dependency_id}"
                )
            if dependency_state == "visited":
                continue
            state[dependency_id] = "visiting"
            stack.append((dependency_id, 0))
    return tuple(ordered)


def _instantiate(
    template: WorkTemplate,
    *,
    source_snapshot_id: str,
    partition_manifest_id: str,
    dependency_hashes: tuple[str, ...],
) -> WorkItem:
    output_key = ArtifactKey(
        source_snapshot_id=source_snapshot_id,
        partition_manifest_id=partition_manifest_id,
        artifact_kind=template.artifact_kind,
        layer=template.layer,
        producer_protocol_version=template.producer_protocol_version,
        layer_policy_hash=template.layer_policy_hash,
        dependency_hashes=dependency_hashes,
    )
    return WorkItem(
        template_id=template.template_id,
        goal_id=template.goal_id,
        output_key=output_key,
        required_artifact_hashes=dependency_hashes,
        producer_id=template.producer_id,
        producer_protocol_version=template.producer_protocol_version,
        verifier_id=template.verifier_id,
        verifier_version=template.verifier_version,
        result_contract_id=template.result_contract_id,
        max_provider_attempts=template.max_provider_attempts,
        max_generation_attempts=template.max_generation_attempts,
        max_semantic_rounds=template.max_semantic_rounds,
        max_result_contract_retries=template.max_result_contract_retries,
    )


def _resolve_receipt(
    item: WorkItem, ledger: LedgerView
) -> tuple[ArtifactReceipt | None, str | None]:
    receipts = _accepted_receipts(ledger)
    exact = ledger.accepted_artifacts.get(item.output_key.identity)
    if exact is not None:
        if type(exact) is not ArtifactReceipt or exact.artifact_key != item.output_key:
            return None, "artifact_key_incompatible"
        if not _certification_matches(exact, item, ledger):
            return None, "certification_incompatible"
        return exact, None
    if any(_same_logical_output(receipt.artifact_key, item.output_key) for receipt in receipts):
        return None, "artifact_key_incompatible"
    return None, None


def _accepted_receipts(ledger: LedgerView) -> tuple[ArtifactReceipt, ...]:
    receipts: list[ArtifactReceipt] = []
    for key_id, receipt in sorted(ledger.accepted_artifacts.items()):
        if type(key_id) is not str or type(receipt) is not ArtifactReceipt:
            raise ReV2PlanError("LedgerView accepted_artifacts must contain ArtifactReceipts")
        if key_id != receipt.artifact_key.identity:
            raise ReV2PlanError("LedgerView artifact index does not match its full ArtifactKey")
        receipts.append(receipt)
    return tuple(receipts)


def _certification_matches(
    receipt: ArtifactReceipt, item: WorkItem, ledger: LedgerView
) -> bool:
    certification = ledger.certifications.get(receipt.certification_id)
    return (
        type(certification) is CertificationReceipt
        and certification.identity == receipt.certification_id
        and certification.verdict == "accepted"
        and certification.scope_verified
        and certification.candidate_id == receipt.candidate_id
        and certification.work_item_id == receipt.work_item_id
        and certification.certification_key.artifact_hash == receipt.artifact_hash
        and certification.certification_key.source_snapshot_id
        == item.output_key.source_snapshot_id
        and certification.certification_key.verifier_id == item.verifier_id
        and certification.certification_key.verifier_version == item.verifier_version
    )


def _same_logical_output(left: ArtifactKey, right: ArtifactKey) -> bool:
    return left.artifact_kind == right.artifact_kind and left.layer == right.layer


def _generation_budget_exhaustion(
    item: WorkItem, budget: BudgetDecision
) -> str | None:
    for dimension in _GLOBAL_GENERATION_DIMENSIONS:
        if dimension in budget.exhausted_dimensions:
            return dimension
    item_id = item.work_item_id
    if (
        f"provider_attempts:{item_id}" in budget.exhausted_dimensions
        or budget.provider_attempts.get(item_id, 0)
        >= min(item.max_provider_attempts, budget.provider_attempt_limit)
    ):
        return "provider_attempts"
    if (
        f"generation_attempts:{item_id}" in budget.exhausted_dimensions
        or budget.generation_attempts.get(item_id, 0)
        >= min(item.max_generation_attempts, budget.generation_attempt_limit)
    ):
        return "generation_attempts"
    return None


def _planning_context(graph: WorkGraph, ledger: LedgerView) -> tuple[str, str]:
    if graph.source_snapshot_id is not None and graph.partition_manifest_id is not None:
        return graph.source_snapshot_id, graph.partition_manifest_id
    contexts = {
        (
            receipt.artifact_key.source_snapshot_id,
            receipt.artifact_key.partition_manifest_id,
        )
        for receipt in _accepted_receipts(ledger)
    }
    if len(contexts) != 1:
        raise ReV2PlanError(
            "planning requires explicit source_snapshot_id and partition_manifest_id"
        )
    return next(iter(contexts))


def _goals(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ReV2PlanError("requested goals must be an iterable of safe IDs")
    try:
        goals = tuple(values)
    except TypeError as exc:
        raise ReV2PlanError("requested goals must be an iterable of safe IDs") from exc
    for goal in goals:
        if not isinstance(goal, str) or not _SAFE_ID_RE.fullmatch(goal):
            raise ReV2PlanError("requested goal must be a nonempty safe ID")
    if len(goals) != len(set(goals)):
        raise ReV2PlanError("requested goals must be unique")
    return goals


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ReV2PlanError(f"{field} must be a lowercase sha256 digest")
    return value


__all__ = (
    "PlanDecision",
    "PlanExplanation",
    "ReV2PlanError",
    "WorkGraph",
    "build_initial_inventory_graph",
    "plan_next",
    "validate_work_graph",
)
