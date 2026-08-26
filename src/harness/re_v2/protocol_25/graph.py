"""Ascending L2 prerequisite composition and deterministic L3 audit targets."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar, Mapping

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.graph import (
    AcceptedArtifactV2,
    Protocol22GraphError,
    instantiate_ready_item,
    normalize_graph_templates_v2,
)
from harness.re_v2.protocol_22.inputs import ValidatedProtocol22Inputs
from harness.re_v2.protocol_22.model import (
    ArtifactScope,
    BudgetPolicyV2,
    CatalogReferenceV1,
    WorkTemplateV2,
)
from harness.re_v2.protocol_22.partition import (
    DomainDescriptorV1,
    SourceDescriptorV1,
    WorkspacePartitionCatalogV1,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    one_of,
    sorted_unique_digests,
)
from harness.re_v2.protocol_24.graph import (
    AcceptedParentClosureV2,
    Protocol24Graph,
    Protocol24GraphError,
    build_protocol_24_graph,
)
from harness.re_v2.protocol_24.model import RunManifestV3

from .findings import AuditTargetV1, AuditedArtifactAuthorityV1
from .model import Protocol25SchemaError, RunManifestV4
from .policies import (
    AuditTaxonomyV1,
    SemanticArtifactPolicyCatalogV1,
    SemanticExecutorContractCatalogV1,
)


_TARGET_KINDS = frozenset({"domain", "source"})
_COVERAGE_STATES = frozenset({"selected-domain", "selected-domains", "full-source"})


class Protocol25GraphError(Protocol25SchemaError):
    """Raised when protocol-2.5 selection or layered graph authority is invalid."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol25GraphError:
        raise
    except (Protocol22SchemaError, Protocol22GraphError) as exc:
        raise Protocol25GraphError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class Protocol25GraphInputsV1:
    workspace_partition: WorkspacePartitionCatalogV1
    artifact_policy: SemanticArtifactPolicyCatalogV1
    executor_contract: SemanticExecutorContractCatalogV1
    audit_policy: AuditTaxonomyV1
    immutable_objects: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_partition, WorkspacePartitionCatalogV1):
            raise Protocol25GraphError("protocol-2.5 graph workspace partition is invalid")
        if not isinstance(self.artifact_policy, SemanticArtifactPolicyCatalogV1):
            raise Protocol25GraphError("protocol-2.5 graph artifact policy is invalid")
        if not isinstance(self.executor_contract, SemanticExecutorContractCatalogV1):
            raise Protocol25GraphError("protocol-2.5 graph executor catalog is invalid")
        if not isinstance(self.audit_policy, AuditTaxonomyV1):
            raise Protocol25GraphError("protocol-2.5 graph audit policy is invalid")
        if self.audit_policy != self.artifact_policy.audit_taxonomy:
            raise Protocol25GraphError(
                "protocol-2.5 graph artifact and audit policies disagree"
            )
        if not isinstance(self.immutable_objects, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, bytes)
            for key, value in self.immutable_objects.items()
        ):
            raise Protocol25GraphError("protocol-2.5 graph immutable objects are invalid")
        for key, payload in self.immutable_objects.items():
            _schema(digest_value, key, "protocol-2.5 immutable object hash")
            if content_digest(payload) != key:
                raise Protocol25GraphError("protocol-2.5 immutable object hash mismatch")
        object.__setattr__(
            self,
            "immutable_objects",
            MappingProxyType(dict(sorted(self.immutable_objects.items()))),
        )

    @property
    def l2_inputs(self) -> ValidatedProtocol22Inputs:
        return ValidatedProtocol22Inputs(
            workspace_partition=self.workspace_partition,
            artifact_policy=self.artifact_policy.inherited_catalog,
            executor_contract=self.executor_contract.inherited_catalog,
            immutable_objects=self.immutable_objects,
        )


@dataclass(frozen=True, slots=True)
class AuditTargetPlanV1:
    schema_version: int
    target_kind: str
    scope: ArtifactScope
    coverage: str
    audited_template_ids: tuple[str, ...]
    required_template_ids: tuple[str, ...]
    not_requested_domain_keys: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "target_kind",
        "scope",
        "coverage",
        "audited_template_ids",
        "required_template_ids",
        "not_requested_domain_keys",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "AuditTargetPlanV1.schema_version")
        _schema(one_of, self.target_kind, _TARGET_KINDS, "audit target plan kind")
        if not isinstance(self.scope, ArtifactScope) or self.scope.content_id is None:
            raise Protocol25GraphError("audit target plan requires content-bound scope")
        if (self.target_kind == "domain") != self.scope.is_domain:
            raise Protocol25GraphError("audit target plan kind does not match scope")
        _schema(one_of, self.coverage, _COVERAGE_STATES, "audit target plan coverage")
        if self.target_kind == "domain" and self.coverage != "selected-domain":
            raise Protocol25GraphError("domain audit target coverage is invalid")
        if self.target_kind == "source" and self.coverage == "selected-domain":
            raise Protocol25GraphError("source audit target coverage is invalid")
        audited = _schema(
            sorted_unique_digests,
            self.audited_template_ids,
            "AuditTargetPlanV1.audited_template_ids",
        )
        required = _schema(
            sorted_unique_digests,
            self.required_template_ids,
            "AuditTargetPlanV1.required_template_ids",
        )
        not_requested = _schema(
            sorted_unique_digests,
            self.not_requested_domain_keys,
            "AuditTargetPlanV1.not_requested_domain_keys",
        )
        if not audited or not required or not set(audited).issubset(set(required)):
            raise Protocol25GraphError(
                "audit target plan audited templates must belong to required closure"
            )
        if self.target_kind == "domain" and not_requested:
            raise Protocol25GraphError("domain audit target cannot carry source omissions")
        object.__setattr__(self, "audited_template_ids", audited)
        object.__setattr__(self, "required_template_ids", required)
        object.__setattr__(self, "not_requested_domain_keys", not_requested)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    @property
    def audit_target_id(self) -> str:
        return self.identity

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "target_kind": self.target_kind,
            "scope": self.scope.to_json_dict(),
            "coverage": self.coverage,
            "audited_template_ids": list(self.audited_template_ids),
            "required_template_ids": list(self.required_template_ids),
            "not_requested_domain_keys": list(self.not_requested_domain_keys),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "AuditTargetPlanV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            schema_version=raw["schema_version"],
            target_kind=raw["target_kind"],
            scope=ArtifactScope.from_json_dict(raw["scope"]),
            coverage=raw["coverage"],
            audited_template_ids=raw["audited_template_ids"],
            required_template_ids=raw["required_template_ids"],
            not_requested_domain_keys=raw["not_requested_domain_keys"],
        )


@dataclass(frozen=True, slots=True)
class Protocol25Graph:
    manifest: RunManifestV4
    prerequisite_graph: Protocol24Graph
    audit_target_plans: tuple[AuditTargetPlanV1, ...]
    audit_templates: tuple[WorkTemplateV2, ...]
    selected_source_ids: tuple[str, ...]
    selected_domain_keys: tuple[str, ...]
    not_requested_domain_keys: tuple[str, ...]
    _inputs: Protocol25GraphInputsV1 = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, RunManifestV4):
            raise Protocol25GraphError("Protocol25Graph manifest is invalid")
        if not isinstance(self.prerequisite_graph, Protocol24Graph):
            raise Protocol25GraphError("Protocol25Graph prerequisite graph is invalid")
        if not isinstance(self._inputs, Protocol25GraphInputsV1):
            raise Protocol25GraphError("Protocol25Graph inputs are invalid")
        if not isinstance(self.audit_target_plans, (list, tuple)) or any(
            not isinstance(item, AuditTargetPlanV1)
            for item in self.audit_target_plans
        ):
            raise Protocol25GraphError("Protocol25Graph audit target plans are invalid")
        plans = tuple(self.audit_target_plans)
        plan_keys = tuple(
            (
                item.scope.source_id,
                0 if item.target_kind == "domain" else 1,
                item.scope.domain_key or "",
            )
            for item in plans
        )
        if not plans or plan_keys != tuple(sorted(set(plan_keys))):
            raise Protocol25GraphError(
                "Protocol25Graph audit target plans must be sorted and unique"
            )
        if not isinstance(self.audit_templates, (list, tuple)) or any(
            not isinstance(item, WorkTemplateV2) for item in self.audit_templates
        ):
            raise Protocol25GraphError("Protocol25Graph audit templates are invalid")
        templates = tuple(self.audit_templates)
        if len(templates) != len(plans):
            raise Protocol25GraphError("Protocol25Graph audit template count is invalid")
        if any(
            template.layer != "L3"
            or template.producer_family != "semantic-audit"
            or template.scope != plan.scope
            or template.required_template_ids != plan.required_template_ids
            for template, plan in zip(templates, plans, strict=True)
        ):
            raise Protocol25GraphError("Protocol25Graph audit templates disagree with plans")
        try:
            normalize_graph_templates_v2(
                (*self.prerequisite_graph.templates, *templates),
                label="Protocol25Graph",
            )
        except Protocol22GraphError as exc:
            raise Protocol25GraphError(str(exc)) from exc
        selected_sources = tuple(self.selected_source_ids)
        selected_domains = _schema(
            sorted_unique_digests,
            self.selected_domain_keys,
            "Protocol25Graph.selected_domain_keys",
        )
        not_requested = _schema(
            sorted_unique_digests,
            self.not_requested_domain_keys,
            "Protocol25Graph.not_requested_domain_keys",
        )
        if selected_sources != tuple(sorted(set(selected_sources))) or not selected_sources:
            raise Protocol25GraphError("Protocol25Graph selected sources are invalid")
        if not selected_domains or set(selected_domains) & set(not_requested):
            raise Protocol25GraphError("Protocol25Graph domain selection is invalid")
        object.__setattr__(self, "audit_target_plans", plans)
        object.__setattr__(self, "audit_templates", templates)
        object.__setattr__(self, "selected_source_ids", selected_sources)
        object.__setattr__(self, "selected_domain_keys", selected_domains)
        object.__setattr__(self, "not_requested_domain_keys", not_requested)

    @property
    def templates(self) -> tuple[WorkTemplateV2, ...]:
        """Expose only the protocol-2.4 prerequisite graph to ``plan_next_v2``."""
        return self.prerequisite_graph.templates

    @property
    def inputs(self) -> ValidatedProtocol22Inputs:
        return self._inputs.l2_inputs

    @property
    def template_by_id(self) -> Mapping[str, WorkTemplateV2]:
        return MappingProxyType(
            {
                item.template_id: item
                for item in (*self.prerequisite_graph.templates, *self.audit_templates)
            }
        )

    def source_target(self, source_id: str) -> AuditTargetPlanV1:
        matching = [
            item
            for item in self.audit_target_plans
            if item.target_kind == "source" and item.scope.source_id == source_id
        ]
        if len(matching) != 1:
            raise Protocol25GraphError(
                f"Protocol25Graph has no unique source target for {source_id!r}"
            )
        return matching[0]

    def ready_audit_targets(
        self,
        accepted_by_template: Mapping[str, AcceptedArtifactV2],
    ) -> tuple[AuditTargetV1, ...]:
        if not isinstance(accepted_by_template, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, AcceptedArtifactV2)
            for key, value in accepted_by_template.items()
        ):
            raise Protocol25GraphError("accepted audit prerequisites are invalid")
        ready = []
        for plan in self.audit_target_plans:
            if not set(plan.required_template_ids).issubset(accepted_by_template):
                continue
            self._validate_accepted_closure(plan, accepted_by_template)
            ready.append(self._materialize_target(plan, accepted_by_template))
        return tuple(ready)

    def _validate_accepted_closure(
        self,
        plan: AuditTargetPlanV1,
        accepted: Mapping[str, AcceptedArtifactV2],
    ) -> None:
        by_id = self.template_by_id
        remaining = set(plan.required_template_ids)
        validated: dict[str, AcceptedArtifactV2] = {}
        while remaining:
            progressed = False
            for template_id in sorted(tuple(remaining)):
                template = by_id[template_id]
                if any(item not in validated for item in template.required_template_ids):
                    continue
                dependencies = {
                    item: validated[item] for item in template.required_template_ids
                }
                try:
                    work_item = instantiate_ready_item(
                        template,
                        dependencies,
                        self.inputs,
                    )
                except Protocol22GraphError as exc:
                    raise Protocol25GraphError(str(exc)) from exc
                artifact = accepted[template_id]
                if artifact.artifact_key_id != work_item.output_key.identity:
                    raise Protocol25GraphError(
                        "accepted audit prerequisite artifact key is not exact"
                    )
                validated[template_id] = artifact
                remaining.remove(template_id)
                progressed = True
            if not progressed:
                raise Protocol25GraphError(
                    "accepted audit prerequisite closure cannot be resolved"
                )

    def _materialize_target(
        self,
        plan: AuditTargetPlanV1,
        accepted: Mapping[str, AcceptedArtifactV2],
    ) -> AuditTargetV1:
        templates = self.template_by_id
        audited = []
        for template_id in plan.audited_template_ids:
            template = templates[template_id]
            artifact = accepted[template_id]
            dependencies = tuple(
                sorted(
                    accepted[item].artifact_hash
                    for item in template.required_template_ids
                )
            )
            audited.append(
                AuditedArtifactAuthorityV1(
                    schema_version=1,
                    artifact_key_id=artifact.artifact_key_id,
                    artifact_hash=artifact.artifact_hash,
                    dependency_hashes=dependencies,
                )
            )
        lower_hashes = tuple(
            sorted(accepted[item].artifact_hash for item in plan.required_template_ids)
        )
        context_hashes = tuple(
            sorted(
                accepted[item].artifact_hash
                for item in plan.required_template_ids
                if "context" in templates[item].artifact_kind
            )
        )
        evidence_hashes = tuple(
            sorted(
                accepted[item].artifact_hash
                for item in plan.required_template_ids
                if "evidence" in templates[item].artifact_kind
            )
        )
        executor = self._inputs.executor_contract.entry_for("semantic-audit")
        renderer = executor.request_renderer
        if renderer is None or len(renderer.response_schemas) != 1:
            raise Protocol25GraphError("semantic audit renderer authority is invalid")
        return AuditTargetV1(
            schema_version=1,
            target_kind=plan.target_kind,
            scope=plan.scope,
            audited_artifacts=tuple(
                sorted(audited, key=lambda item: item.artifact_key_id)
            ),
            lower_dependency_hashes=lower_hashes,
            context_object_hashes=context_hashes,
            evidence_object_hashes=evidence_hashes,
            audit_policy_hash=self._inputs.audit_policy.identity,
            auditor_authority_hash=renderer.agent_contract_hash,
            response_schema_hash=renderer.response_schemas[0].schema_hash,
        )


def build_protocol_25_graph(
    manifest: RunManifestV4,
    inputs: Protocol25GraphInputsV1,
    accepted_parent: AcceptedParentClosureV2,
) -> Protocol25Graph:
    if not isinstance(manifest, RunManifestV4):
        raise Protocol25GraphError("graph building requires RunManifestV4")
    if not isinstance(inputs, Protocol25GraphInputsV1):
        raise Protocol25GraphError("graph building requires protocol-2.5 inputs")
    _validate_manifest_inputs(manifest, inputs)
    selected = _resolve_selection(manifest, inputs.workspace_partition)
    l2_manifest = _protocol_24_adapter(manifest, inputs)
    try:
        prerequisite_graph = build_protocol_24_graph(
            l2_manifest,
            inputs.l2_inputs,
            accepted_parent,
        )
    except Protocol24GraphError as exc:
        raise Protocol25GraphError(str(exc)) from exc

    by_slot = {
        (
            item.scope.source_id,
            item.scope.domain_key,
            item.layer,
            item.artifact_kind,
        ): item
        for item in prerequisite_graph.templates
    }
    by_id = {item.template_id: item for item in prerequisite_graph.templates}
    plans: list[AuditTargetPlanV1] = []
    not_requested_all: set[str] = set()
    for source, domains in selected:
        selected_keys = {item.domain_key for item in domains}
        not_requested = tuple(
            sorted(
                item.domain_key
                for item in source.domains
                if item.domain_key not in selected_keys
            )
        )
        not_requested_all.update(not_requested)
        domain_baselines = []
        for domain in domains:
            baseline = _slot(
                by_slot,
                source.source_id,
                domain.domain_key,
                "L2",
                "domain-baseline",
            )
            domain_baselines.append(baseline)
            required = _template_closure(by_id, (baseline.template_id,))
            required.update(
                _lower_domain_authority_ids(
                    by_slot,
                    source.source_id,
                    domain.domain_key,
                )
            )
            required = _template_closure(by_id, tuple(required))
            plans.append(
                AuditTargetPlanV1(
                    schema_version=1,
                    target_kind="domain",
                    scope=baseline.scope,
                    coverage="selected-domain",
                    audited_template_ids=(baseline.template_id,),
                    required_template_ids=tuple(sorted(required)),
                    not_requested_domain_keys=(),
                )
            )
        source_overview = _slot(
            by_slot,
            source.source_id,
            None,
            "L2",
            "source-overview",
        )
        source_root = _slot(
            by_slot,
            source.source_id,
            None,
            "L2",
            "source-baseline-root",
        )
        source_required = _template_closure(by_id, (source_root.template_id,))
        for domain in domains:
            source_required.update(
                _lower_domain_authority_ids(
                    by_slot,
                    source.source_id,
                    domain.domain_key,
                )
            )
        for kind in ("source-overview", "source-baseline-root"):
            source_required.add(
                _slot(by_slot, source.source_id, None, "L1", kind).template_id
            )
        source_required = _template_closure(by_id, tuple(source_required))
        plans.append(
            AuditTargetPlanV1(
                schema_version=1,
                target_kind="source",
                scope=source_overview.scope,
                coverage=("full-source" if not not_requested else "selected-domains"),
                audited_template_ids=tuple(
                    sorted(
                        (
                            source_overview.template_id,
                            *(item.template_id for item in domain_baselines),
                        )
                    )
                ),
                required_template_ids=tuple(sorted(source_required)),
                not_requested_domain_keys=not_requested,
            )
        )
    plans.sort(
        key=lambda item: (
            item.scope.source_id,
            0 if item.target_kind == "domain" else 1,
            item.scope.domain_key or "",
        )
    )
    templates = tuple(_audit_template(manifest, inputs, item) for item in plans)
    return Protocol25Graph(
        manifest=manifest,
        prerequisite_graph=prerequisite_graph,
        audit_target_plans=tuple(plans),
        audit_templates=templates,
        selected_source_ids=tuple(sorted(source.source_id for source, _ in selected)),
        selected_domain_keys=tuple(
            sorted(domain.domain_key for _source, domains in selected for domain in domains)
        ),
        not_requested_domain_keys=tuple(sorted(not_requested_all)),
        _inputs=inputs,
    )


def _validate_manifest_inputs(
    manifest: RunManifestV4,
    inputs: Protocol25GraphInputsV1,
) -> None:
    expected = (
        (manifest.source_snapshot_id, inputs.workspace_partition.snapshot_id),
        (manifest.workspace_partition_catalog.object_hash, inputs.workspace_partition.identity),
        (manifest.artifact_policy_catalog.object_hash, inputs.artifact_policy.identity),
        (manifest.executor_contract_catalog.object_hash, inputs.executor_contract.identity),
        (manifest.audit_policy_catalog.object_hash, inputs.audit_policy.identity),
    )
    if any(left != right for left, right in expected):
        raise Protocol25GraphError("protocol-2.5 graph catalog or snapshot mismatch")


def _protocol_24_adapter(
    manifest: RunManifestV4,
    inputs: Protocol25GraphInputsV1,
) -> RunManifestV3:
    return RunManifestV3(
        schema_version=3,
        engine="re-v2",
        engine_protocol_version="2.4",
        run_id=manifest.run_id,
        created_at=manifest.created_at,
        source_snapshot_id=manifest.source_snapshot_id,
        source_snapshot_kind=manifest.source_snapshot_kind,
        partition_manifest_id=manifest.partition_manifest_id,
        workspace_partition_catalog=CatalogReferenceV1(
            inputs.workspace_partition.identity,
            manifest.workspace_partition_catalog.relative_path,
        ),
        artifact_policy_catalog=CatalogReferenceV1(
            inputs.artifact_policy.inherited_catalog.identity,
            manifest.artifact_policy_catalog.relative_path,
        ),
        executor_contract_catalog=CatalogReferenceV1(
            inputs.executor_contract.inherited_catalog.identity,
            manifest.executor_contract_catalog.relative_path,
        ),
        parent_authority_bundle=manifest.parent_authority_bundle,
        parent_lineage=manifest.parent_lineage,
        requested_goals=("selective-deepening",),
        target_layer="L2",
        selection=manifest.selection,
        semantic_request_id=manifest.semantic_request_id,
        initial_budget_policy=BudgetPolicyV2.for_goal(
            "selective-deepening",
            manifest.initial_budget_policy.token_limit,
            manifest.initial_budget_policy.active_ms_limit,
        ),
    )


def _resolve_selection(
    manifest: RunManifestV4,
    workspace: WorkspacePartitionCatalogV1,
) -> tuple[tuple[SourceDescriptorV1, tuple[DomainDescriptorV1, ...]], ...]:
    by_source = {item.source_id: item for item in workspace.sources}
    source_ids = (
        tuple(sorted(by_source))
        if manifest.selection.all_sources
        else manifest.selection.source_ids
    )
    if any(item not in by_source for item in source_ids):
        raise Protocol25GraphError("selection references an unknown source")
    requested = set(manifest.selection.domain_keys)
    available = {
        domain.domain_key
        for source_id in source_ids
        for domain in by_source[source_id].domains
    }
    if requested - available:
        raise Protocol25GraphError("selection references an unknown domain")
    result = []
    resolved: set[str] = set()
    for source_id in source_ids:
        source = by_source[source_id]
        domains = tuple(
            item for item in source.domains if not requested or item.domain_key in requested
        )
        if not domains:
            raise Protocol25GraphError("selection resolves to no nonempty domains")
        resolved.update(item.domain_key for item in domains)
        result.append((source, domains))
    if requested - resolved:
        raise Protocol25GraphError("selection references an unknown domain")
    return tuple(result)


def _slot(
    by_slot: Mapping[tuple[str, str | None, str, str], WorkTemplateV2],
    source_id: str,
    domain_key: str | None,
    layer: str,
    artifact_kind: str,
) -> WorkTemplateV2:
    try:
        return by_slot[(source_id, domain_key, layer, artifact_kind)]
    except KeyError as exc:
        raise Protocol25GraphError(
            f"layered graph is missing {(source_id, domain_key, layer, artifact_kind)!r}"
        ) from exc


def _template_closure(
    by_id: Mapping[str, WorkTemplateV2],
    roots: tuple[str, ...],
) -> set[str]:
    pending = list(roots)
    result: set[str] = set()
    while pending:
        template_id = pending.pop()
        if template_id in result:
            continue
        try:
            template = by_id[template_id]
        except KeyError as exc:
            raise Protocol25GraphError("template dependency is outside layered graph") from exc
        result.add(template_id)
        pending.extend(template.required_template_ids)
    return result


def _lower_domain_authority_ids(
    by_slot: Mapping[tuple[str, str | None, str, str], WorkTemplateV2],
    source_id: str,
    domain_key: str,
) -> set[str]:
    result = set()
    for layer, kind in (
        ("L0", "domain-inventory"),
        ("L0", "domain-evidence-pack"),
        ("L1", "domain-context-bundle"),
        ("L1", "domain-baseline"),
    ):
        result.add(_slot(by_slot, source_id, domain_key, layer, kind).template_id)
    return result


def _audit_template(
    manifest: RunManifestV4,
    inputs: Protocol25GraphInputsV1,
    plan: AuditTargetPlanV1,
) -> WorkTemplateV2:
    policy = inputs.artifact_policy.entry_for("L3", "semantic-audit-findings")
    executor = inputs.executor_contract.entry_for("semantic-audit")
    budget = manifest.initial_budget_policy
    return WorkTemplateV2(
        identity_schema_version=2,
        goal_id="semantic-audit-closure",
        scope=plan.scope,
        artifact_kind="semantic-audit-findings",
        layer="L3",
        producer_id="echelon.re-validator",
        producer_family="semantic-audit",
        producer_protocol_version=executor.producer_protocol_version,
        layer_policy_hash=policy.identity,
        required_template_ids=plan.required_template_ids,
        executor_contract_hash=executor.executor_contract_hash,
        verifier_id=executor.verifier.verifier_id,
        verifier_version=executor.verifier.verifier_version,
        verifier_implementation_digest=executor.verifier.implementation_digest,
        result_contract_id=executor.result_contract_id,
        max_provider_attempts=budget.provider_attempt_limit,
        max_generation_attempts=budget.artifact_generation_attempt_limit,
        max_semantic_rounds=budget.semantic_repair_round_limit,
        max_result_contract_retries=budget.result_contract_retry_limit,
        max_shared_retries=budget.shared_retry_limit,
        max_artifact_contract_retries=budget.artifact_contract_retry_limit,
    )


__all__ = (
    "AuditTargetPlanV1",
    "Protocol25Graph",
    "Protocol25GraphError",
    "Protocol25GraphInputsV1",
    "build_protocol_25_graph",
)
