"""Scoped protocol-2.2 production graph and replay-derived delta planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar, Literal, Mapping, Protocol

from .executors import (
    ExecutorContractEntryV1,
    Protocol22ExecutorError,
)
from .inputs import Protocol22InputSet, ValidatedProtocol22Inputs
from .model import (
    ArtifactKeyV2,
    ArtifactScope,
    BudgetPolicyV2,
    RunManifestV2,
    WorkItemV2,
    WorkTemplateV2,
    instantiate_work_item_v2,
)
from .partition import DomainDescriptorV1, SourceDescriptorV1
from .policies import (
    ArtifactPolicyEntryV1,
    Protocol22PolicyError,
    layer_policy_hash,
    policy_for,
)
from .schema import Protocol22SchemaError, digest_value, safe_id


_CATALOG_HASH_KEYS = frozenset(
    {
        "artifact_policy_catalog",
        "executor_contract_catalog",
        "workspace_partition_catalog",
    }
)
_PRODUCER_FAMILY = {
    "source-inventory": "inventory",
    "source-partition": "partition",
    "domain-inventory": "inventory",
    "source-evidence-pack": "evidence-pack",
    "domain-evidence-pack": "evidence-pack",
    "domain-context-bundle": "context-bundle",
    "source-overview-context-bundle": "context-bundle",
    "domain-baseline": "compact-baseline",
    "source-overview": "compact-baseline",
    "source-baseline-root": "source-baseline-root",
}
_PRODUCER_ID = {
    family: f"{family}-producer-v1" for family in frozenset(_PRODUCER_FAMILY.values())
}
_PRODUCER_ID["compact-deepening"] = "compact-deepening-producer-v1"
_PRODUCER_ID["targeted-evidence-pack"] = "targeted-evidence-pack-producer-v1"
_PRODUCER_ID["deepening-context-bundle"] = "deepening-context-bundle-producer-v1"
_PRODUCER_ID["deepening-source-root"] = "deepening-source-root-producer-v1"
_BASELINE_KINDS = frozenset(_PRODUCER_FAMILY)
_INVENTORY_KINDS = frozenset(
    {
        "source-inventory",
        "source-partition",
        "domain-inventory",
        "source-evidence-pack",
        "domain-evidence-pack",
    }
)
_CONTENT_FREE_KINDS = frozenset({"source-partition"})
_PARTITION_FREE_KINDS = frozenset({"source-inventory"})
_TERMINAL_DEPENDENCY_STATES = frozenset(
    {"failed", "executor_blocked", "failed_dependency"}
)


class Protocol22GraphError(Protocol22SchemaError):
    """Raised when a protocol-2.2 graph or planning projection is incoherent."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol22GraphError:
        raise
    except Protocol22SchemaError as exc:
        raise Protocol22GraphError(str(exc)) from exc


def _digest(value: object, field: str) -> str:
    return _schema(digest_value, value, field)


def _reason(value: object, field: str) -> str:
    return _schema(safe_id, value, field)


@dataclass(frozen=True, slots=True)
class AcceptedArtifactV2:
    artifact_key_id: str
    artifact_hash: str

    def __post_init__(self) -> None:
        _digest(self.artifact_key_id, "AcceptedArtifactV2.artifact_key_id")
        _digest(self.artifact_hash, "AcceptedArtifactV2.artifact_hash")


@dataclass(frozen=True, slots=True)
class WorkFailureStateV2:
    work_item_id: str
    reason_code: str
    failure_receipt_id: str

    def __post_init__(self) -> None:
        _digest(self.work_item_id, "WorkFailureStateV2.work_item_id")
        _reason(self.reason_code, "WorkFailureStateV2.reason_code")
        _digest(self.failure_receipt_id, "WorkFailureStateV2.failure_receipt_id")


@dataclass(frozen=True, slots=True)
class ExecutorFailureStateV2:
    executor_contract_hash: str
    reason_code: str
    executor_failure_receipt_id: str

    def __post_init__(self) -> None:
        _digest(
            self.executor_contract_hash,
            "ExecutorFailureStateV2.executor_contract_hash",
        )
        _reason(self.reason_code, "ExecutorFailureStateV2.reason_code")
        _digest(
            self.executor_failure_receipt_id,
            "ExecutorFailureStateV2.executor_failure_receipt_id",
        )


class PlanningAuthorityV2(Protocol):
    def artifact_for_key(self, artifact_key_id: str) -> AcceptedArtifactV2 | None:
        raise NotImplementedError

    def work_failure(self, work_item_id: str) -> WorkFailureStateV2 | None:
        raise NotImplementedError

    def executor_failure(
        self, executor_contract_hash: str
    ) -> ExecutorFailureStateV2 | None:
        raise NotImplementedError


class PlanningBudgetV2(Protocol):
    def item_attempt_available(self, work_item: WorkItemV2) -> bool:
        raise NotImplementedError


class PlanningGraphV2(Protocol):
    @property
    def templates(self) -> tuple[WorkTemplateV2, ...]:
        raise NotImplementedError

    @property
    def inputs(self) -> ValidatedProtocol22Inputs | Protocol22InputSet:
        raise NotImplementedError


PlanActionV2 = Literal[
    "reuse",
    "generate",
    "blocked_dependency",
    "failed",
    "blocked_executor",
    "blocked_attempts",
    "blocked_budget",
    "blocked_authority",
]
_PLAN_ACTIONS = frozenset(
    {
        "reuse",
        "generate",
        "blocked_dependency",
        "failed",
        "blocked_executor",
        "blocked_attempts",
        "blocked_budget",
        "blocked_authority",
    }
)


@dataclass(frozen=True, slots=True)
class PlanExplanationV2:
    template_id: str
    work_item_id: str | None
    action: PlanActionV2
    reason_code: str
    receipt_id: str | None = None

    def __post_init__(self) -> None:
        _digest(self.template_id, "PlanExplanationV2.template_id")
        if self.work_item_id is not None:
            _digest(self.work_item_id, "PlanExplanationV2.work_item_id")
        if self.action not in _PLAN_ACTIONS:
            raise Protocol22GraphError("PlanExplanationV2.action is unsupported")
        _reason(self.reason_code, "PlanExplanationV2.reason_code")
        if self.receipt_id is not None:
            _digest(self.receipt_id, "PlanExplanationV2.receipt_id")


@dataclass(frozen=True, slots=True)
class PlanDecisionV2:
    ready: tuple[WorkItemV2, ...]
    explanations: Mapping[str, PlanExplanationV2]

    def __post_init__(self) -> None:
        if not isinstance(self.ready, (list, tuple)) or any(
            not isinstance(item, WorkItemV2) for item in self.ready
        ):
            raise Protocol22GraphError(
                "PlanDecisionV2.ready must contain schema-2 WorkItemV2 values"
            )
        ready = tuple(self.ready)
        ready_ids = tuple(item.work_item_id for item in ready)
        if len(ready_ids) != len(set(ready_ids)):
            raise Protocol22GraphError("PlanDecisionV2.ready contains duplicate work")
        if not isinstance(self.explanations, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, PlanExplanationV2)
            for key, value in self.explanations.items()
        ):
            raise Protocol22GraphError(
                "PlanDecisionV2.explanations must contain closed explanations"
            )
        copied = dict(sorted(self.explanations.items()))
        if any(key != value.template_id for key, value in copied.items()):
            raise Protocol22GraphError(
                "PlanDecisionV2 explanation keys must equal template IDs"
            )
        object.__setattr__(self, "ready", ready)
        object.__setattr__(self, "explanations", MappingProxyType(copied))


@dataclass(frozen=True, slots=True)
class Protocol22Graph:
    templates: tuple[WorkTemplateV2, ...]
    requested_goals: tuple[str, ...]
    catalog_hashes: Mapping[str, str]
    _inputs: ValidatedProtocol22Inputs | Protocol22InputSet | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    CATALOG_HASH_KEYS: ClassVar[frozenset[str]] = _CATALOG_HASH_KEYS

    def __post_init__(self) -> None:
        templates = normalize_graph_templates_v2(
            self.templates,
            label="Protocol22Graph",
        )
        if not isinstance(self.requested_goals, (list, tuple)) or tuple(
            self.requested_goals
        ) not in {("baseline",), ("inventory",)}:
            raise Protocol22GraphError(
                "Protocol22Graph requested_goals must be exactly baseline or inventory"
            )
        goals = tuple(self.requested_goals)
        if any(item.goal_id != goals[0] for item in templates):
            raise Protocol22GraphError(
                "every graph template must use the immutable requested goal"
            )
        if not isinstance(self.catalog_hashes, Mapping) or set(
            self.catalog_hashes
        ) != _CATALOG_HASH_KEYS:
            raise Protocol22GraphError(
                "Protocol22Graph.catalog_hashes must contain the three immutable catalogs"
            )
        hashes = {
            key: _digest(value, f"Protocol22Graph.catalog_hashes[{key}]")
            for key, value in self.catalog_hashes.items()
        }
        if self._inputs is not None and not isinstance(
            self._inputs, (ValidatedProtocol22Inputs, Protocol22InputSet)
        ):
            raise Protocol22GraphError(
                "Protocol22Graph private inputs must be authenticated protocol-2.2 inputs"
            )
        if self._inputs is not None:
            private_hashes = {
                "workspace_partition_catalog": self._inputs.workspace_partition.identity,
                "artifact_policy_catalog": self._inputs.artifact_policy.identity,
                "executor_contract_catalog": self._inputs.executor_contract.identity,
            }
            for key, actual in private_hashes.items():
                if actual != hashes[key]:
                    label = key.removesuffix("_catalog").replace("_", " ")
                    raise Protocol22GraphError(
                        f"private inputs {label} catalog hash does not match graph authority"
                    )

        object.__setattr__(self, "templates", templates)
        object.__setattr__(self, "requested_goals", goals)
        object.__setattr__(
            self,
            "catalog_hashes",
            MappingProxyType(dict(sorted(hashes.items()))),
        )

    @property
    def inputs(self) -> ValidatedProtocol22Inputs | Protocol22InputSet:
        if self._inputs is None:
            raise Protocol22GraphError(
                "graph has no authenticated immutable inputs for item instantiation"
            )
        return self._inputs


def build_protocol_22_graph(
    manifest: RunManifestV2,
    inputs: ValidatedProtocol22Inputs | Protocol22InputSet,
) -> Protocol22Graph:
    """Reconstruct the complete selected graph from immutable run inputs."""
    if not isinstance(manifest, RunManifestV2):
        raise Protocol22GraphError("graph building requires RunManifestV2")
    if not isinstance(inputs, (ValidatedProtocol22Inputs, Protocol22InputSet)):
        raise Protocol22GraphError(
            "graph building requires validated protocol-2.2 inputs"
        )
    workspace = inputs.workspace_partition
    policy_catalog = inputs.artifact_policy
    executor_catalog = inputs.executor_contract
    if workspace.snapshot_id != manifest.source_snapshot_id:
        raise Protocol22GraphError(
            "workspace partition snapshot does not match the run manifest"
        )
    references = (
        (
            "workspace partition",
            workspace.identity,
            manifest.workspace_partition_catalog.object_hash,
        ),
        (
            "artifact policy",
            policy_catalog.identity,
            manifest.artifact_policy_catalog.object_hash,
        ),
        (
            "executor contract",
            executor_catalog.identity,
            manifest.executor_contract_catalog.object_hash,
        ),
    )
    for label, actual, expected in references:
        if actual != expected:
            raise Protocol22GraphError(f"{label} catalog hash mismatch")

    goal = manifest.requested_goals[0]
    selected_kinds = _BASELINE_KINDS if goal == "baseline" else _INVENTORY_KINDS
    expected_families = {_PRODUCER_FAMILY[kind] for kind in selected_kinds}
    actual_families = {entry.producer_family for entry in executor_catalog.entries}
    if actual_families != expected_families:
        raise Protocol22GraphError(
            "executor catalog producer families do not equal the selected graph closure"
        )
    entries = {entry.producer_family: entry for entry in executor_catalog.entries}
    for kind in selected_kinds:
        _resolve_contract(kind, policy_catalog, entries[_PRODUCER_FAMILY[kind]])

    templates: list[WorkTemplateV2] = []
    for source in workspace.sources:
        source_nodes: dict[str, WorkTemplateV2] = {}
        domain_nodes: dict[str, dict[str, WorkTemplateV2]] = {}

        source_nodes["source-inventory"] = _build_template(
            manifest,
            inputs,
            source,
            None,
            "source-inventory",
            (),
        )
        source_nodes["source-partition"] = _build_template(
            manifest,
            inputs,
            source,
            None,
            "source-partition",
            (),
        )
        source_nodes["source-evidence-pack"] = _build_template(
            manifest,
            inputs,
            source,
            None,
            "source-evidence-pack",
            (
                source_nodes["source-inventory"].template_id,
                source_nodes["source-partition"].template_id,
            ),
        )
        templates.extend(source_nodes.values())

        for domain in source.domains:
            nodes: dict[str, WorkTemplateV2] = {}
            nodes["domain-inventory"] = _build_template(
                manifest,
                inputs,
                source,
                domain,
                "domain-inventory",
                (),
            )
            nodes["domain-evidence-pack"] = _build_template(
                manifest,
                inputs,
                source,
                domain,
                "domain-evidence-pack",
                (nodes["domain-inventory"].template_id,),
            )
            if goal == "baseline":
                nodes["domain-context-bundle"] = _build_template(
                    manifest,
                    inputs,
                    source,
                    domain,
                    "domain-context-bundle",
                    (
                        nodes["domain-inventory"].template_id,
                        nodes["domain-evidence-pack"].template_id,
                    ),
                )
                nodes["domain-baseline"] = _build_template(
                    manifest,
                    inputs,
                    source,
                    domain,
                    "domain-baseline",
                    (nodes["domain-context-bundle"].template_id,),
                )
            templates.extend(nodes.values())
            domain_nodes[domain.domain_key] = nodes

        if goal == "baseline":
            domain_baselines = tuple(
                domain_nodes[key]["domain-baseline"].template_id
                for key in sorted(domain_nodes)
            )
            source_nodes["source-overview-context-bundle"] = _build_template(
                manifest,
                inputs,
                source,
                None,
                "source-overview-context-bundle",
                (
                    source_nodes["source-inventory"].template_id,
                    source_nodes["source-partition"].template_id,
                    source_nodes["source-evidence-pack"].template_id,
                    *domain_baselines,
                ),
            )
            source_nodes["source-overview"] = _build_template(
                manifest,
                inputs,
                source,
                None,
                "source-overview",
                (source_nodes["source-overview-context-bundle"].template_id,),
            )
            source_nodes["source-baseline-root"] = _build_template(
                manifest,
                inputs,
                source,
                None,
                "source-baseline-root",
                (source_nodes["source-overview"].template_id, *domain_baselines),
            )
            templates.extend(
                (
                    source_nodes["source-overview-context-bundle"],
                    source_nodes["source-overview"],
                    source_nodes["source-baseline-root"],
                )
            )

    return Protocol22Graph(
        templates=tuple(templates),
        requested_goals=manifest.requested_goals,
        catalog_hashes={
            "workspace_partition_catalog": manifest.workspace_partition_catalog.object_hash,
            "artifact_policy_catalog": manifest.artifact_policy_catalog.object_hash,
            "executor_contract_catalog": manifest.executor_contract_catalog.object_hash,
        },
        _inputs=inputs,
    )


def instantiate_ready_item(
    template: WorkTemplateV2,
    accepted_dependencies: Mapping[str, AcceptedArtifactV2],
    inputs: ValidatedProtocol22Inputs | Protocol22InputSet,
) -> WorkItemV2:
    """Bind a template to the exact replay-accepted dependency hashes."""
    if not isinstance(template, WorkTemplateV2):
        raise Protocol22GraphError(
            "ready-item instantiation requires schema-2 WorkTemplateV2"
        )
    if not isinstance(inputs, (ValidatedProtocol22Inputs, Protocol22InputSet)):
        raise Protocol22GraphError(
            "ready-item instantiation requires validated protocol-2.2 inputs"
        )
    if not isinstance(accepted_dependencies, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, AcceptedArtifactV2)
        for key, value in accepted_dependencies.items()
    ):
        raise Protocol22GraphError(
            "accepted dependencies must map template IDs to AcceptedArtifactV2 values"
        )
    if set(accepted_dependencies) != set(template.required_template_ids):
        raise Protocol22GraphError(
            "accepted dependencies must exactly match required_template_ids"
        )
    source, domain = _descriptor_for_scope(template.scope, inputs)
    expected_scope, partition_id = _identity_for_kind(
        source,
        domain,
        template.artifact_kind,
    )
    if template.scope != expected_scope:
        raise Protocol22GraphError(
            "template scope does not match immutable workspace partition identity"
        )
    policy, executor = _contracts_for_template(template, inputs)
    _validate_template_contract(template, policy, executor)
    dependency_hashes = tuple(
        sorted(value.artifact_hash for value in accepted_dependencies.values())
    )
    try:
        output_key = ArtifactKeyV2(
            identity_schema_version=2,
            scope=template.scope,
            partition_id=partition_id,
            artifact_kind=template.artifact_kind,
            layer=template.layer,
            producer_protocol_version=template.producer_protocol_version,
            layer_policy_hash=template.layer_policy_hash,
            dependency_hashes=dependency_hashes,
        )
        return instantiate_work_item_v2(template, output_key, dependency_hashes)
    except Protocol22SchemaError as exc:
        raise Protocol22GraphError(str(exc)) from exc


def plan_next_v22(
    graph: Protocol22Graph,
    authority: PlanningAuthorityV2,
    budget: PlanningBudgetV2,
) -> PlanDecisionV2:
    """Compatibility facade retaining protocol-2.2 nominal validation."""
    if not is_shared_planning_graph_v2(graph):
        raise Protocol22GraphError("planning requires Protocol22Graph")
    return plan_next_v2(graph, authority, budget)


def is_shared_planning_graph_v2(graph: object) -> bool:
    """Recognize only the two closed graphs that use the shared v2 planner."""
    if isinstance(graph, Protocol22Graph):
        return True
    try:
        from harness.re_v2.protocol_24.graph import Protocol24Graph
    except ImportError:
        return False
    return isinstance(graph, Protocol24Graph)


def plan_next_v2(
    graph: PlanningGraphV2,
    authority: PlanningAuthorityV2,
    budget: PlanningBudgetV2,
) -> PlanDecisionV2:
    """Compute a safe unresolved delta over shared schema-2 graph primitives."""
    templates = normalize_graph_templates_v2(
        getattr(graph, "templates", None),
        label="planning graph",
    )
    for method in ("artifact_for_key", "work_failure", "executor_failure"):
        if not callable(getattr(authority, method, None)):
            raise Protocol22GraphError(
                f"planning authority is missing required method {method}"
            )
    attempt_available = getattr(budget, "item_attempt_available", None)
    if not callable(attempt_available):
        raise Protocol22GraphError(
            "planning budget is missing item_attempt_available"
        )

    by_id = {item.template_id: item for item in templates}
    accepted: dict[str, AcceptedArtifactV2] = {}
    states: dict[str, str] = {}
    ready: list[WorkItemV2] = []
    explanations: dict[str, PlanExplanationV2] = {}

    for template_id in _topological_order(by_id):
        template = by_id[template_id]
        executor_failure = authority.executor_failure(
            template.executor_contract_hash
        )
        if executor_failure is not None:
            if not isinstance(executor_failure, ExecutorFailureStateV2):
                raise Protocol22GraphError(
                    "planning authority returned an invalid executor failure"
                )
            if (
                executor_failure.executor_contract_hash
                != template.executor_contract_hash
            ):
                raise Protocol22GraphError(
                    "executor failure does not match the requested contract"
                )

        failed_dependencies = tuple(
            dependency_id
            for dependency_id in template.required_template_ids
            if states.get(dependency_id) in _TERMINAL_DEPENDENCY_STATES
        )
        missing_dependencies = tuple(
            dependency_id
            for dependency_id in template.required_template_ids
            if dependency_id not in accepted
        )
        if executor_failure is not None and missing_dependencies:
            states[template_id] = "executor_blocked"
            explanations[template_id] = _explanation(
                template,
                None,
                "blocked_executor",
                "blocked_by_executor_failure",
                executor_failure.executor_failure_receipt_id,
            )
            continue
        if failed_dependencies:
            states[template_id] = "failed_dependency"
            explanations[template_id] = _explanation(
                template,
                None,
                "blocked_dependency",
                "blocked_by_failed_dependency",
            )
            continue
        if missing_dependencies:
            states[template_id] = "pending"
            explanations[template_id] = _explanation(
                template,
                None,
                "blocked_dependency",
                "prerequisite_artifact_unavailable",
            )
            continue

        dependencies = {
            dependency_id: accepted[dependency_id]
            for dependency_id in template.required_template_ids
        }
        try:
            graph_inputs = graph.inputs
        except (AttributeError, Protocol22GraphError) as exc:
            raise Protocol22GraphError(
                "graph has no authenticated immutable inputs for item instantiation"
            ) from exc
        item = instantiate_ready_item(template, dependencies, graph_inputs)
        artifact = authority.artifact_for_key(item.output_key.identity)
        if artifact is not None:
            if not isinstance(artifact, AcceptedArtifactV2):
                raise Protocol22GraphError(
                    "planning authority returned an invalid accepted artifact"
                )
            if artifact.artifact_key_id != item.output_key.identity:
                raise Protocol22GraphError(
                    "accepted artifact projection does not match the requested key"
                )
            accepted[template_id] = artifact
            states[template_id] = "accepted"
            explanations[template_id] = _explanation(
                template,
                item,
                "reuse",
                "accepted_exact_artifact",
            )
            continue

        work_failure = authority.work_failure(item.work_item_id)
        if work_failure is not None:
            if not isinstance(work_failure, WorkFailureStateV2):
                raise Protocol22GraphError(
                    "planning authority returned an invalid work failure"
                )
            if work_failure.work_item_id != item.work_item_id:
                raise Protocol22GraphError(
                    "work failure does not match the requested work item"
                )
            states[template_id] = "failed"
            explanations[template_id] = _explanation(
                template,
                item,
                "failed",
                work_failure.reason_code,
                work_failure.failure_receipt_id,
            )
            continue
        if executor_failure is not None:
            states[template_id] = "executor_blocked"
            explanations[template_id] = _explanation(
                template,
                item,
                "blocked_executor",
                "blocked_by_executor_failure",
                executor_failure.executor_failure_receipt_id,
            )
            continue

        pinned_available = getattr(authority, "pinned_authority_available", None)
        if callable(pinned_available):
            available = pinned_available(template.executor_contract_hash)
            if not isinstance(available, bool):
                raise Protocol22GraphError(
                    "pinned_authority_available must return a boolean"
                )
            if not available:
                states[template_id] = "authority_unavailable"
                explanations[template_id] = _explanation(
                    template,
                    item,
                    "blocked_authority",
                    "pinned_authority_unavailable",
                )
                continue

        has_attempt = attempt_available(item)
        if not isinstance(has_attempt, bool):
            raise Protocol22GraphError(
                "item_attempt_available must return a boolean"
            )
        if not has_attempt:
            states[template_id] = "attempts_exhausted"
            explanations[template_id] = _explanation(
                template,
                item,
                "blocked_attempts",
                "item_attempts_exhausted",
            )
            continue

        run_available = getattr(budget, "run_budget_available", None)
        if callable(run_available):
            has_run_budget = run_available(item)
            if not isinstance(has_run_budget, bool):
                raise Protocol22GraphError(
                    "run_budget_available must return a boolean"
                )
            if not has_run_budget:
                states[template_id] = "budget_paused"
                explanations[template_id] = _explanation(
                    template,
                    item,
                    "blocked_budget",
                    "run_budget_exhausted",
                )
                continue

        states[template_id] = "ready"
        ready.append(item)
        explanations[template_id] = _explanation(
            template,
            item,
            "generate",
            "dependency_complete_uncertified",
        )

    if set(explanations) != set(by_id):
        raise Protocol22GraphError(
            "protocol-2.2 planner did not explain every graph template"
        )
    order = {item.template_id: index for index, item in enumerate(templates)}
    return PlanDecisionV2(
        ready=tuple(sorted(ready, key=lambda item: order[item.template_id])),
        explanations=explanations,
    )


def _build_template(
    manifest: RunManifestV2,
    inputs: ValidatedProtocol22Inputs | Protocol22InputSet,
    source: SourceDescriptorV1,
    domain: DomainDescriptorV1 | None,
    artifact_kind: str,
    required_template_ids: tuple[str, ...],
) -> WorkTemplateV2:
    return build_work_template_v2(
        goal_id=manifest.requested_goals[0],
        budget=manifest.initial_budget_policy,
        inputs=inputs,
        source=source,
        domain=domain,
        artifact_kind=artifact_kind,
        layer="L0" if artifact_kind in _INVENTORY_KINDS else "L1",
        required_template_ids=required_template_ids,
    )


def build_work_template_v2(
    *,
    goal_id: str,
    budget: BudgetPolicyV2,
    inputs: ValidatedProtocol22Inputs | Protocol22InputSet,
    source: SourceDescriptorV1,
    domain: DomainDescriptorV1 | None,
    artifact_kind: str,
    layer: str,
    required_template_ids: tuple[str, ...],
) -> WorkTemplateV2:
    """Build one template from the existing catalog and executor authorities."""
    scope, _partition_id = _identity_for_kind(source, domain, artifact_kind)
    family = _producer_family(layer, artifact_kind)
    policy = policy_for(inputs.artifact_policy, layer, artifact_kind)
    try:
        executor = inputs.executor_contract.entry_for(family)
    except Protocol22ExecutorError as exc:
        raise Protocol22GraphError(str(exc)) from exc
    _resolve_contract(
        artifact_kind,
        inputs.artifact_policy,
        executor,
        layer=layer,
    )
    return WorkTemplateV2(
        identity_schema_version=2,
        goal_id=goal_id,
        scope=scope,
        artifact_kind=artifact_kind,
        layer=policy.layer,
        producer_id=_PRODUCER_ID[family],
        producer_family=family,
        producer_protocol_version=policy.producer_protocol_version,
        layer_policy_hash=layer_policy_hash(policy),
        required_template_ids=tuple(sorted(required_template_ids)),
        executor_contract_hash=executor.executor_contract_hash,
        verifier_id=executor.verifier.verifier_id,
        verifier_version=executor.verifier.verifier_version,
        verifier_implementation_digest=executor.verifier.implementation_digest,
        result_contract_id=policy.result_contract_id,
        max_provider_attempts=budget.provider_attempt_limit,
        max_generation_attempts=budget.artifact_generation_attempt_limit,
        max_semantic_rounds=budget.semantic_repair_round_limit,
        max_result_contract_retries=budget.result_contract_retry_limit,
        max_shared_retries=budget.shared_retry_limit,
        max_artifact_contract_retries=budget.artifact_contract_retry_limit,
    )


def _identity_for_kind(
    source: SourceDescriptorV1,
    domain: DomainDescriptorV1 | None,
    artifact_kind: str,
) -> tuple[ArtifactScope, str | None]:
    if artifact_kind.startswith("domain-"):
        if domain is None:
            raise Protocol22GraphError(f"{artifact_kind} requires a domain descriptor")
        scope = ArtifactScope(
            source_id=source.source_id,
            domain_key=domain.domain_key,
            content_id=(
                None
                if artifact_kind in _CONTENT_FREE_KINDS
                else domain.domain_content_id
            ),
        )
        partition_id = (
            None
            if artifact_kind in _PARTITION_FREE_KINDS
            else domain.domain_partition_id
        )
        return scope, partition_id
    if domain is not None:
        raise Protocol22GraphError(f"{artifact_kind} requires source scope")
    scope = ArtifactScope(
        source_id=source.source_id,
        domain_key=None,
        content_id=(
            None if artifact_kind in _CONTENT_FREE_KINDS else source.source_content_id
        ),
    )
    partition_id = (
        None
        if artifact_kind in _PARTITION_FREE_KINDS
        else source.source_partition_id
    )
    return scope, partition_id


def _resolve_contract(
    artifact_kind: str,
    policy_catalog: object,
    executor: ExecutorContractEntryV1,
    *,
    layer: str | None = None,
) -> ArtifactPolicyEntryV1:
    selected_layer = layer or (
        "L0" if artifact_kind in _INVENTORY_KINDS else "L1"
    )
    try:
        policy = policy_for(policy_catalog, selected_layer, artifact_kind)
    except (Protocol22PolicyError, AttributeError) as exc:
        raise Protocol22GraphError(str(exc)) from exc
    family = _producer_family(selected_layer, artifact_kind)
    if executor.producer_family != family:
        raise Protocol22GraphError(
            f"executor producer family does not match {artifact_kind}"
        )
    if executor.producer_protocol_version != policy.producer_protocol_version:
        raise Protocol22GraphError(
            f"executor producer protocol does not match {artifact_kind} policy"
        )
    if executor.result_contract_id != policy.result_contract_id:
        raise Protocol22GraphError(
            f"executor result contract does not match {artifact_kind} policy"
        )
    expected_modes = (
        {"api", "cli"}
        if family in {"compact-baseline", "compact-deepening"}
        else {"in_process"}
    )
    if executor.execution_mode not in expected_modes:
        raise Protocol22GraphError(
            f"executor mode does not match {artifact_kind} producer family"
        )
    return policy


def _producer_family(layer: str, artifact_kind: str) -> str:
    if layer == "L2":
        if artifact_kind in {"domain-baseline", "source-overview"}:
            return "compact-deepening"
        if artifact_kind == "domain-evidence-pack":
            return "targeted-evidence-pack"
        if artifact_kind in {
            "domain-context-bundle",
            "source-overview-context-bundle",
        }:
            return "deepening-context-bundle"
        if artifact_kind == "source-baseline-root":
            return "deepening-source-root"
    return _PRODUCER_FAMILY[artifact_kind]


def _contracts_for_template(
    template: WorkTemplateV2,
    inputs: ValidatedProtocol22Inputs | Protocol22InputSet,
) -> tuple[ArtifactPolicyEntryV1, ExecutorContractEntryV1]:
    try:
        policy = policy_for(
            inputs.artifact_policy,
            template.layer,
            template.artifact_kind,
        )
        executor = inputs.executor_contract.entry_for(template.producer_family)
    except (Protocol22PolicyError, Protocol22ExecutorError) as exc:
        raise Protocol22GraphError(str(exc)) from exc
    return policy, executor


def _validate_template_contract(
    template: WorkTemplateV2,
    policy: ArtifactPolicyEntryV1,
    executor: ExecutorContractEntryV1,
) -> None:
    expected = {
        "producer_family": _producer_family(
            template.layer,
            template.artifact_kind,
        ),
        "producer_protocol_version": policy.producer_protocol_version,
        "layer_policy_hash": layer_policy_hash(policy),
        "executor_contract_hash": executor.executor_contract_hash,
        "verifier_id": executor.verifier.verifier_id,
        "verifier_version": executor.verifier.verifier_version,
        "verifier_implementation_digest": executor.verifier.implementation_digest,
        "result_contract_id": policy.result_contract_id,
    }
    for field, value in expected.items():
        if getattr(template, field) != value:
            raise Protocol22GraphError(
                f"template {field} does not match immutable catalog authority"
            )


def _descriptor_for_scope(
    scope: ArtifactScope,
    inputs: ValidatedProtocol22Inputs | Protocol22InputSet,
) -> tuple[SourceDescriptorV1, DomainDescriptorV1 | None]:
    sources = [
        source
        for source in inputs.workspace_partition.sources
        if source.source_id == scope.source_id
    ]
    if len(sources) != 1:
        raise Protocol22GraphError("template scope source is not uniquely declared")
    source = sources[0]
    if scope.domain_key is None:
        return source, None
    domains = [
        domain for domain in source.domains if domain.domain_key == scope.domain_key
    ]
    if len(domains) != 1:
        raise Protocol22GraphError("template scope domain is not uniquely declared")
    return source, domains[0]


def _template_order_key(item: WorkTemplateV2) -> tuple[object, ...]:
    return (
        item.scope.source_id.encode("utf-8"),
        0 if item.scope.domain_key is None else 1,
        "" if item.scope.domain_key is None else item.scope.domain_key,
        item.artifact_kind,
        item.layer,
    )


def normalize_graph_templates_v2(
    templates: object,
    *,
    label: str,
) -> tuple[WorkTemplateV2, ...]:
    """Validate and canonicalize the shared schema-2 template graph."""
    if not isinstance(templates, (list, tuple)) or any(
        not isinstance(item, WorkTemplateV2) for item in templates
    ):
        raise Protocol22GraphError(
            f"{label} templates must be schema-2 WorkTemplateV2 values"
        )
    values = tuple(templates)
    if not values:
        raise Protocol22GraphError(f"{label} templates must be nonempty")
    by_id: dict[str, WorkTemplateV2] = {}
    logical_outputs: dict[tuple[str, str, str], str] = {}
    for item in values:
        template_id = item.template_id
        if template_id in by_id:
            raise Protocol22GraphError(f"duplicate template ID: {template_id}")
        by_id[template_id] = item
        slot = (item.scope.identity, item.artifact_kind, item.layer)
        if slot in logical_outputs:
            raise Protocol22GraphError(
                "duplicate logical output (scope, artifact_kind, layer)"
            )
        logical_outputs[slot] = template_id
    for template_id, item in by_id.items():
        for dependency_id in item.required_template_ids:
            if dependency_id not in by_id:
                raise Protocol22GraphError(
                    f"template {template_id} has missing dependency {dependency_id}"
                )
    _topological_order(by_id)
    return tuple(sorted(values, key=_template_order_key))


def _topological_order(
    by_id: Mapping[str, WorkTemplateV2],
) -> tuple[str, ...]:
    ordered: list[str] = []
    state: dict[str, Literal["visiting", "visited"]] = {}

    def visit(template_id: str) -> None:
        current = state.get(template_id)
        if current == "visiting":
            raise Protocol22GraphError(
                f"protocol-2.2 graph contains a cycle at {template_id}"
            )
        if current == "visited":
            return
        state[template_id] = "visiting"
        for dependency_id in by_id[template_id].required_template_ids:
            visit(dependency_id)
        state[template_id] = "visited"
        ordered.append(template_id)

    for template_id in sorted(by_id):
        visit(template_id)
    return tuple(ordered)


def _explanation(
    template: WorkTemplateV2,
    item: WorkItemV2 | None,
    action: PlanActionV2,
    reason_code: str,
    receipt_id: str | None = None,
) -> PlanExplanationV2:
    return PlanExplanationV2(
        template_id=template.template_id,
        work_item_id=None if item is None else item.work_item_id,
        action=action,
        reason_code=reason_code,
        receipt_id=receipt_id,
    )


__all__ = (
    "AcceptedArtifactV2",
    "ExecutorFailureStateV2",
    "PlanDecisionV2",
    "PlanExplanationV2",
    "PlanningAuthorityV2",
    "PlanningBudgetV2",
    "PlanningGraphV2",
    "Protocol22Graph",
    "Protocol22GraphError",
    "is_shared_planning_graph_v2",
    "WorkFailureStateV2",
    "build_protocol_22_graph",
    "build_work_template_v2",
    "instantiate_ready_item",
    "normalize_graph_templates_v2",
    "plan_next_v2",
    "plan_next_v22",
)
