"""Deterministic L1 context composition and source-root assembly."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping, TypeVar

from harness.re_v2.canonical import canonical_json_bytes, content_digest

from .artifacts import (
    AcceptedDependencySetV2,
    ArtifactDependencyV1,
    ArtifactEnvelopeV1,
    ClaimV1,
    ContextBundleV1,
    DepthDebtV1,
    DomainDepthDebtRollupV1,
    DomainProjectionV1,
    EvidenceExcerptV1,
    EvidencePackV1,
    EvidenceReferenceV1,
    OmittedDomainDescriptorV1,
    OmittedProjectedClaimDescriptorV1,
    ProjectedClaimV1,
    SourceBaselineDomainV1,
    SourceBaselineRootV1,
)
from .evidence import EvidenceAuthorityDescriptorV1, evidence_authority_id
from .inventory import InventoryArtifactV1, SourcePartitionArtifactV1
from .model import ArtifactScope, WorkItemV2
from .partition import WorkspacePartitionCatalogV1
from .policies import (
    DOMAIN_SURFACES,
    ArtifactPolicyCatalogV1,
    ArtifactPolicyEntryV1,
    ContextBundlePolicyParametersV1,
    ProjectionPolicyV1,
    Protocol22PolicyError,
    layer_policy_hash,
    policy_for,
)
from .schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    load_canonical_object,
    one_of,
    sorted_unique_digests,
)


class Protocol22ContextError(Protocol22SchemaError):
    """Raised when accepted dependency closure cannot form a canonical context."""


_DecodedT = TypeVar("_DecodedT")


@dataclass(frozen=True, slots=True)
class _SurfaceView:
    status: str
    items: tuple[ClaimV1, ...]
    not_established_reason_code: str | None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "items": [item.to_json_dict() for item in self.items],
            "not_established_reason_code": self.not_established_reason_code,
        }


@dataclass(frozen=True, slots=True)
class _DomainBaselineView:
    schema_version: int
    scope: ArtifactScope
    partition_id: str
    layer_policy_hash: str
    dependency_hashes: tuple[str, ...]
    context_bundle_hash: str
    surfaces: Mapping[str, _SurfaceView]
    unknowns: tuple[object, ...]
    depth_debt: DepthDebtV1

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact": {
                "artifact_kind": "domain-baseline",
                "layer": "L1",
                "scope": self.scope.to_json_dict(),
                "partition_id": self.partition_id,
                "layer_policy_hash": self.layer_policy_hash,
                "dependency_hashes": list(self.dependency_hashes),
                "context_bundle_hash": self.context_bundle_hash,
            },
            "surfaces": {
                surface: self.surfaces[surface].to_json_dict()
                for surface in DOMAIN_SURFACES
            },
            "unknowns": list(self.unknowns),
            "depth_debt": self.depth_debt.to_json_dict(),
        }


@dataclass(frozen=True, slots=True)
class _ProjectionClaim:
    surface: str
    claim_index: int
    original: ClaimV1
    projected: ProjectedClaimV1
    evidence: tuple[EvidenceExcerptV1, ...]
    omission: OmittedProjectedClaimDescriptorV1

    @property
    def key(self) -> tuple[str, int]:
        return self.surface, self.claim_index


def build_domain_context_bundle(
    work_item: WorkItemV2,
    accepted_inputs: AcceptedDependencySetV2,
    policies: ArtifactPolicyCatalogV1,
) -> bytes:
    """Compose one domain-local bundle from exact inventory and evidence bytes."""
    context_policy, target_policy = _validate_context_work_item(
        work_item,
        accepted_inputs,
        policies,
        "domain-context-bundle",
        frozenset({"domain_inventory", "domain_evidence_pack"}),
    )
    inventory = _payload_for_role(
        accepted_inputs,
        "domain_inventory",
        InventoryArtifactV1.from_json_dict,
    )
    evidence = _payload_for_role(
        accepted_inputs,
        "domain_evidence_pack",
        EvidencePackV1.from_json_dict,
    )
    if not isinstance(inventory, InventoryArtifactV1) or not isinstance(
        evidence, EvidencePackV1
    ):
        raise Protocol22ContextError("domain dependency decoders returned wrong types")
    if (
        inventory.artifact_kind != "domain-inventory"
        or inventory.scope != work_item.output_key.scope
        or inventory.partition_id != work_item.output_key.partition_id
    ):
        raise Protocol22ContextError(
            "domain inventory does not match context scope and partition"
        )
    inventory_hash = accepted_inputs.by_role["domain_inventory"].artifact_hash
    evidence_hash = accepted_inputs.by_role["domain_evidence_pack"].artifact_hash
    if (
        evidence.artifact_kind != "domain-evidence-pack"
        or evidence.scope != work_item.output_key.scope
        or evidence.inventory_artifact_hash != inventory_hash
        or evidence.layer_policy_hash
        != layer_policy_hash(
            policy_for(policies, "L0", "domain-evidence-pack")
        )
    ):
        raise Protocol22ContextError(
            "domain evidence pack does not match accepted inventory and policy"
        )
    bundle = ContextBundleV1(
        schema_version=1,
        artifact_kind="domain-context-bundle",
        target_artifact_kind="domain-baseline",
        scope=work_item.output_key.scope,
        context_policy_hash=work_item.output_key.layer_policy_hash,
        target_policy_hash=layer_policy_hash(target_policy),
        target_artifact_policy=target_policy,
        dependencies=_dependencies(
            (
                ("domain-inventory", inventory_hash),
                ("domain-evidence-pack", evidence_hash),
            )
        ),
        evidence_pack_hash=evidence_hash,
        evidence=evidence.excerpts,
        domain_projections=(),
        depth_debt=evidence.depth_debt,
    )
    return _bounded_context_payload(bundle, context_policy)


def build_source_overview_context_bundle(
    work_item: WorkItemV2,
    accepted_inputs: AcceptedDependencySetV2,
    policies: ArtifactPolicyCatalogV1,
) -> bytes:
    """Compose bounded source evidence plus stable per-domain projections."""
    _require_types(work_item, accepted_inputs, policies)
    base_roles = frozenset(
        {"source_inventory", "source_partition", "source_evidence_pack"}
    )
    if not base_roles.issubset(accepted_inputs.by_role):
        raise Protocol22ContextError(
            "source context dependency roles are missing required source inputs"
        )
    partition = _payload_for_role(
        accepted_inputs,
        "source_partition",
        SourcePartitionArtifactV1.from_json_dict,
    )
    if not isinstance(partition, SourcePartitionArtifactV1):
        raise Protocol22ContextError("source partition decoder returned wrong type")
    expected_roles = frozenset(
        {
            *base_roles,
            *(f"domain:{domain.domain_key}" for domain in partition.domains),
        }
    )
    context_policy, target_policy = _validate_context_work_item(
        work_item,
        accepted_inputs,
        policies,
        "source-overview-context-bundle",
        expected_roles,
    )
    if (
        partition.source_scope.source_id != work_item.output_key.scope.source_id
        or partition.source_scope.content_id is not None
        or partition.source_partition_id != work_item.output_key.partition_id
    ):
        raise Protocol22ContextError(
            "source partition does not match context scope and partition"
        )
    inventory = _payload_for_role(
        accepted_inputs,
        "source_inventory",
        InventoryArtifactV1.from_json_dict,
    )
    evidence = _payload_for_role(
        accepted_inputs,
        "source_evidence_pack",
        EvidencePackV1.from_json_dict,
    )
    if not isinstance(inventory, InventoryArtifactV1) or not isinstance(
        evidence, EvidencePackV1
    ):
        raise Protocol22ContextError("source dependency decoders returned wrong types")
    inventory_hash = accepted_inputs.by_role["source_inventory"].artifact_hash
    partition_hash = accepted_inputs.by_role["source_partition"].artifact_hash
    evidence_hash = accepted_inputs.by_role["source_evidence_pack"].artifact_hash
    if (
        inventory.artifact_kind != "source-inventory"
        or inventory.scope != work_item.output_key.scope
        or inventory.partition_id is not None
    ):
        raise Protocol22ContextError("source inventory does not match context scope")
    if (
        evidence.artifact_kind != "source-evidence-pack"
        or evidence.scope != work_item.output_key.scope
        or evidence.inventory_artifact_hash != inventory_hash
        or evidence.layer_policy_hash
        != layer_policy_hash(
            policy_for(policies, "L0", "source-evidence-pack")
        )
    ):
        raise Protocol22ContextError(
            "source evidence pack does not match accepted inventory and policy"
        )
    parameters = context_policy.policy_parameters
    if not isinstance(parameters, ContextBundlePolicyParametersV1) or not isinstance(
        parameters.projection, ProjectionPolicyV1
    ):
        raise Protocol22ContextError(
            "source context policy lacks its closed projection contract"
        )

    target_domain_policy = policy_for(policies, "L1", "domain-baseline")
    projections: list[DomainProjectionV1] = []
    all_domain_debt: list[tuple[str, DepthDebtV1, str]] = []
    omitted_domains: list[OmittedDomainDescriptorV1] = []
    omitted_claims: list[OmittedProjectedClaimDescriptorV1] = []
    total_projection_claims = 0
    dependency_rows: list[tuple[str, str]] = [
        ("source-inventory", inventory_hash),
        ("source-partition", partition_hash),
        ("source-evidence-pack", evidence_hash),
    ]

    for domain in partition.domains:
        role = f"domain:{domain.domain_key}"
        accepted = accepted_inputs.by_role[role]
        baseline = _payload_for_role(
            accepted_inputs,
            role,
            _decode_domain_baseline,
        )
        if not isinstance(baseline, _DomainBaselineView):
            raise Protocol22ContextError("domain baseline decoder returned wrong type")
        if (
            baseline.scope.source_id != work_item.output_key.scope.source_id
            or baseline.scope.domain_key != domain.domain_key
            or baseline.partition_id != domain.domain_partition_id
            or baseline.layer_policy_hash != layer_policy_hash(target_domain_policy)
        ):
            raise Protocol22ContextError(
                "accepted domain baseline does not match source partition and policy"
            )
        domain_context = _payload_for_hash(
            accepted_inputs,
            baseline.context_bundle_hash,
            ContextBundleV1.from_json_dict,
        )
        if not isinstance(domain_context, ContextBundleV1):
            raise Protocol22ContextError("domain context decoder returned wrong type")
        if (
            domain_context.artifact_kind != "domain-context-bundle"
            or domain_context.target_artifact_kind != "domain-baseline"
            or domain_context.scope != baseline.scope
            or domain_context.context_policy_hash
            != layer_policy_hash(
                policy_for(policies, "L1", "domain-context-bundle")
            )
            or domain_context.target_policy_hash != baseline.layer_policy_hash
            or domain_context.target_artifact_policy != target_domain_policy
            or domain_context.depth_debt != baseline.depth_debt
            or domain_context.domain_projections
        ):
            raise Protocol22ContextError(
                "domain baseline context closure is inconsistent"
            )
        baseline_hash = accepted.artifact_hash
        debt_hash = content_digest(baseline.depth_debt.to_json_dict())
        all_domain_debt.append((domain.domain_key, baseline.depth_debt, debt_hash))
        candidates = _projection_claims(
            baseline,
            domain_context,
            domain.domain_key,
            parameters.projection,
        )
        total_projection_claims += len(candidates)
        projection, omitted = _allocate_domain_projection(
            domain.domain_key,
            domain.presentation_domain_id,
            baseline_hash,
            baseline.depth_debt,
            debt_hash,
            candidates,
            tuple(projections),
            parameters.projection,
        )
        dependency_rows.append(("domain-baseline", baseline_hash))
        if projection is None:
            omitted_domains.append(
                OmittedDomainDescriptorV1(
                    domain_key=domain.domain_key,
                    baseline_artifact_hash=baseline_hash,
                    reason_code="capacity_exhausted",
                )
            )
            omitted_claims.extend(candidate.omission for candidate in candidates)
        else:
            projections.append(projection)
            omitted_claims.extend(omitted)

    debt = _source_depth_debt(
        evidence.depth_debt,
        tuple(all_domain_debt),
        tuple(omitted_domains),
        tuple(omitted_claims),
        retained_claim_count=sum(item.retained_claim_count for item in projections),
        total_projection_claims=total_projection_claims,
    )
    bundle = ContextBundleV1(
        schema_version=1,
        artifact_kind="source-overview-context-bundle",
        target_artifact_kind="source-overview",
        scope=work_item.output_key.scope,
        context_policy_hash=work_item.output_key.layer_policy_hash,
        target_policy_hash=layer_policy_hash(target_policy),
        target_artifact_policy=target_policy,
        dependencies=_dependencies(tuple(dependency_rows)),
        evidence_pack_hash=evidence_hash,
        evidence=evidence.excerpts,
        domain_projections=tuple(projections),
        depth_debt=debt,
    )
    return _bounded_context_payload(bundle, context_policy)


def build_source_baseline_root(
    work_item: WorkItemV2,
    accepted_inputs: AcceptedDependencySetV2,
    partition: WorkspacePartitionCatalogV1,
) -> bytes:
    """Assemble the candidate-free source root from exact accepted hashes."""
    if not isinstance(work_item, WorkItemV2):
        raise Protocol22ContextError(
            "source root requires schema-2 WorkItemV2"
        )
    if not isinstance(accepted_inputs, AcceptedDependencySetV2):
        raise Protocol22ContextError(
            "source root requires AcceptedDependencySetV2"
        )
    if not isinstance(partition, WorkspacePartitionCatalogV1):
        raise Protocol22ContextError(
            "source root requires a workspace partition catalog"
        )
    if (
        work_item.output_key.artifact_kind != "source-baseline-root"
        or work_item.output_key.layer != "L1"
        or work_item.producer_id != "source-baseline-root-producer-v1"
        or work_item.producer_family != "source-baseline-root"
        or work_item.producer_protocol_version != "source-baseline-root-v1"
        or work_item.output_key.producer_protocol_version
        != "source-baseline-root-v1"
        or work_item.result_contract_id != "deterministic-artifact-v1"
    ):
        raise Protocol22ContextError("source root work item contract is invalid")
    sources = [
        source
        for source in partition.sources
        if source.source_id == work_item.output_key.scope.source_id
    ]
    if len(sources) != 1:
        raise Protocol22ContextError("source root scope is not uniquely partitioned")
    source = sources[0]
    expected_scope = ArtifactScope(
        source_id=source.source_id,
        domain_key=None,
        content_id=source.source_content_id,
    )
    if (
        work_item.output_key.scope != expected_scope
        or work_item.output_key.partition_id != source.source_partition_id
    ):
        raise Protocol22ContextError(
            "source root scope or partition does not match catalog authority"
        )
    expected_roles = {
        "source_overview",
        *(f"domain:{domain.domain_key}" for domain in source.domains),
    }
    _validate_dependency_roles(work_item, accepted_inputs, frozenset(expected_roles))
    domains = tuple(
        SourceBaselineDomainV1(
            domain_key=domain.domain_key,
            presentation_domain_id=domain.presentation_domain_id,
            baseline_artifact_hash=accepted_inputs.by_role[
                f"domain:{domain.domain_key}"
            ].artifact_hash,
        )
        for domain in source.domains
    )
    root = SourceBaselineRootV1(
        schema_version=1,
        artifact=ArtifactEnvelopeV1(
            artifact_kind="source-baseline-root",
            layer="L1",
            scope=work_item.output_key.scope,
            partition_id=source.source_partition_id,
            layer_policy_hash=work_item.output_key.layer_policy_hash,
            dependency_hashes=work_item.output_key.dependency_hashes,
        ),
        overview_artifact_hash=accepted_inputs.by_role[
            "source_overview"
        ].artifact_hash,
        domains=domains,
    )
    payload = canonical_json_bytes(root.to_json_dict())
    if len(payload) > 4 * 1024 * 1024:
        raise Protocol22ContextError("source baseline root exceeds its closed byte cap")
    return payload


def _require_types(
    work_item: WorkItemV2,
    accepted_inputs: AcceptedDependencySetV2,
    policies: ArtifactPolicyCatalogV1,
) -> None:
    if not isinstance(work_item, WorkItemV2):
        raise Protocol22ContextError("context producer requires schema-2 WorkItemV2")
    if not isinstance(accepted_inputs, AcceptedDependencySetV2):
        raise Protocol22ContextError(
            "context producer requires AcceptedDependencySetV2"
        )
    if not isinstance(policies, ArtifactPolicyCatalogV1):
        raise Protocol22ContextError(
            "context producer requires a closed artifact policy catalog"
        )


def _validate_context_work_item(
    work_item: WorkItemV2,
    accepted_inputs: AcceptedDependencySetV2,
    policies: ArtifactPolicyCatalogV1,
    expected_kind: str,
    expected_roles: frozenset[str],
) -> tuple[ArtifactPolicyEntryV1, ArtifactPolicyEntryV1]:
    _require_types(work_item, accepted_inputs, policies)
    if work_item.output_key.artifact_kind != expected_kind:
        raise Protocol22ContextError(
            f"context work item artifact kind must be {expected_kind}"
        )
    try:
        context_policy = policy_for(policies, "L1", expected_kind)
    except Protocol22PolicyError as exc:
        raise Protocol22ContextError(str(exc)) from exc
    parameters = context_policy.policy_parameters
    if not isinstance(parameters, ContextBundlePolicyParametersV1):
        raise Protocol22ContextError("context policy parameters are invalid")
    try:
        target_policy = policy_for(
            policies,
            "L1",
            parameters.target_artifact_kind,
        )
    except Protocol22PolicyError as exc:
        raise Protocol22ContextError(str(exc)) from exc
    expected_contract = {
        "producer_id": "context-bundle-producer-v1",
        "producer_family": "context-bundle",
        "producer_protocol_version": context_policy.producer_protocol_version,
        "result_contract_id": context_policy.result_contract_id,
    }
    for field, expected in expected_contract.items():
        if getattr(work_item, field) != expected:
            raise Protocol22ContextError(
                f"context work item {field} does not match pinned policy"
            )
    if (
        work_item.output_key.layer != "L1"
        or work_item.output_key.layer_policy_hash != layer_policy_hash(context_policy)
        or work_item.output_key.producer_protocol_version
        != context_policy.producer_protocol_version
        or parameters.target_policy_hash != layer_policy_hash(target_policy)
    ):
        raise Protocol22ContextError(
            "context work item policy identity does not match pinned policy catalog"
        )
    _validate_dependency_roles(work_item, accepted_inputs, expected_roles)
    return context_policy, target_policy


def _validate_dependency_roles(
    work_item: WorkItemV2,
    accepted_inputs: AcceptedDependencySetV2,
    expected_roles: frozenset[str],
) -> None:
    if frozenset(accepted_inputs.by_role) != expected_roles:
        raise Protocol22ContextError(
            "accepted dependency roles do not equal the producer contract"
        )
    hashes = tuple(
        sorted(artifact.artifact_hash for artifact in accepted_inputs.by_role.values())
    )
    if (
        len(hashes) != len(set(hashes))
        or hashes != work_item.output_key.dependency_hashes
        or hashes != work_item.required_artifact_hashes
    ):
        raise Protocol22ContextError(
            "accepted dependency hashes do not equal work item closure"
        )


def _payload_for_role(
    accepted_inputs: AcceptedDependencySetV2,
    role: str,
    decoder: Callable[[object], _DecodedT],
) -> _DecodedT:
    try:
        payload = accepted_inputs.payload_for_role(role)
        return load_canonical_object(payload, decoder)
    except Protocol22SchemaError as exc:
        raise Protocol22ContextError(
            f"invalid accepted payload for role {role}: {exc}"
        ) from exc


def _payload_for_hash(
    accepted_inputs: AcceptedDependencySetV2,
    artifact_hash: str,
    decoder: Callable[[object], _DecodedT],
) -> _DecodedT:
    try:
        payload = accepted_inputs.payload_for_hash(artifact_hash)
        return load_canonical_object(payload, decoder)
    except Protocol22SchemaError as exc:
        raise Protocol22ContextError(
            f"invalid accepted closure payload {artifact_hash}: {exc}"
        ) from exc


def _dependencies(
    values: tuple[tuple[str, str], ...],
) -> tuple[ArtifactDependencyV1, ...]:
    return tuple(
        sorted(
            (ArtifactDependencyV1(kind, artifact_hash) for kind, artifact_hash in values),
            key=lambda item: (item.artifact_kind, item.artifact_hash),
        )
    )


def _bounded_context_payload(
    bundle: ContextBundleV1,
    context_policy: ArtifactPolicyEntryV1,
) -> bytes:
    payload = canonical_json_bytes(bundle.to_json_dict())
    caps = [context_policy.max_canonical_json_bytes]
    if context_policy.max_context_bundle_bytes is not None:
        caps.append(context_policy.max_context_bundle_bytes)
    if context_policy.max_conservative_input_tokens is not None:
        caps.append(context_policy.max_conservative_input_tokens)
    if len(payload) > min(caps):
        raise Protocol22ContextError(
            f"{bundle.artifact_kind} exceeds its closed context byte cap"
        )
    return payload


def _decode_domain_baseline(value: object) -> _DomainBaselineView:
    try:
        raw = exact_object(
            value,
            frozenset({"schema_version", "artifact", "surfaces", "unknowns", "depth_debt"}),
            "DomainBaselineProjectionInputV1",
        )
        literal(raw["schema_version"], 1, "domain baseline schema_version")
        artifact = exact_object(
            raw["artifact"],
            frozenset(
                {
                    "artifact_kind",
                    "layer",
                    "scope",
                    "partition_id",
                    "layer_policy_hash",
                    "dependency_hashes",
                    "context_bundle_hash",
                }
            ),
            "DomainBaselineProjectionInputV1.artifact",
        )
        literal(
            artifact["artifact_kind"],
            "domain-baseline",
            "domain baseline artifact_kind",
        )
        literal(artifact["layer"], "L1", "domain baseline layer")
        scope = ArtifactScope.from_json_dict(artifact["scope"])
        if not scope.is_domain or scope.content_id is None:
            raise Protocol22ContextError(
                "domain baseline projection input requires content-bearing domain scope"
            )
        partition_id = digest_value(
            artifact["partition_id"],
            "domain baseline partition_id",
        )
        policy_hash = digest_value(
            artifact["layer_policy_hash"],
            "domain baseline layer_policy_hash",
        )
        dependency_hashes = sorted_unique_digests(
            artifact["dependency_hashes"],
            "domain baseline dependency_hashes",
        )
        context_hash = digest_value(
            artifact["context_bundle_hash"],
            "domain baseline context_bundle_hash",
        )
        if dependency_hashes != (context_hash,):
            raise Protocol22ContextError(
                "domain baseline must depend only on its context bundle"
            )
        surface_values = exact_object(
            raw["surfaces"],
            frozenset(DOMAIN_SURFACES),
            "domain baseline surfaces",
        )
        surfaces = {
            surface: _decode_surface(surface_values[surface], surface)
            for surface in DOMAIN_SURFACES
        }
        unknowns = raw["unknowns"]
        if not isinstance(unknowns, (list, tuple)):
            raise Protocol22ContextError("domain baseline unknowns must be an array")
        debt = DepthDebtV1.from_json_dict(raw["depth_debt"])
        return _DomainBaselineView(
            schema_version=1,
            scope=scope,
            partition_id=partition_id,
            layer_policy_hash=policy_hash,
            dependency_hashes=dependency_hashes,
            context_bundle_hash=context_hash,
            surfaces=MappingProxyType(surfaces),
            unknowns=tuple(unknowns),
            depth_debt=debt,
        )
    except Protocol22ContextError:
        raise
    except Protocol22SchemaError as exc:
        raise Protocol22ContextError(str(exc)) from exc


def _decode_surface(value: object, surface: str) -> _SurfaceView:
    raw = exact_object(
        value,
        frozenset({"status", "items", "not_established_reason_code"}),
        f"domain baseline surface {surface}",
    )
    status = one_of(
        raw["status"],
        frozenset({"observed", "not_established"}),
        f"domain baseline surface {surface}.status",
    )
    items = raw["items"]
    if not isinstance(items, (list, tuple)):
        raise Protocol22ContextError(
            f"domain baseline surface {surface}.items must be an array"
        )
    claims = tuple(ClaimV1.from_json_dict(item) for item in items)
    reason = raw["not_established_reason_code"]
    if status == "observed":
        if not claims or reason is not None:
            raise Protocol22ContextError(
                f"observed domain surface {surface} requires claims and null reason"
            )
    else:
        if claims:
            raise Protocol22ContextError(
                f"not-established domain surface {surface} must have no claims"
            )
        one_of(
            reason,
            frozenset({"not_in_bounded_context", "requires_deeper_analysis"}),
            f"domain baseline surface {surface}.reason",
        )
    return _SurfaceView(status, claims, reason)


def _projection_claims(
    baseline: _DomainBaselineView,
    context: ContextBundleV1,
    domain_key: str,
    policy: ProjectionPolicyV1,
) -> tuple[_ProjectionClaim, ...]:
    by_authority: dict[str, EvidenceExcerptV1] = {}
    for excerpt in context.evidence:
        if excerpt.evidence_authority_id in by_authority:
            raise Protocol22ContextError(
                "domain context has duplicate evidence authority"
            )
        by_authority[excerpt.evidence_authority_id] = excerpt
    candidates: list[_ProjectionClaim] = []
    for surface in policy.surface_priority:
        for index, claim in enumerate(baseline.surfaces[surface].items):
            projected_refs: list[EvidenceReferenceV1] = []
            projected_excerpts: dict[str, EvidenceExcerptV1] = {}
            for reference in claim.evidence:
                excerpt = by_authority.get(reference.evidence_authority_id)
                if excerpt is None:
                    raise Protocol22ContextError(
                        "projected claim evidence authority does not resolve"
                    )
                if (
                    reference.path != excerpt.source_relative_path
                    or reference.start_line < excerpt.start_line
                    or reference.end_line > excerpt.end_line
                    or excerpt.origin_domain_key != domain_key
                    or excerpt.ownership not in {"owned", "shared_supporting"}
                ):
                    raise Protocol22ContextError(
                        "projected claim evidence is outside the accepted domain excerpt"
                    )
                projected_excerpt = _project_excerpt(
                    excerpt,
                    context.scope.source_id,
                    domain_key,
                )
                projected_excerpts[
                    projected_excerpt.evidence_authority_id
                ] = projected_excerpt
                projected_refs.append(
                    EvidenceReferenceV1(
                        evidence_authority_id=projected_excerpt.evidence_authority_id,
                        path=reference.path,
                        start_line=reference.start_line,
                        end_line=reference.end_line,
                    )
                )
            rewritten = ClaimV1(
                statement=claim.statement,
                evidence=tuple(sorted(projected_refs, key=lambda item: item.sort_key)),
            )
            omission = OmittedProjectedClaimDescriptorV1(
                domain_key=domain_key,
                surface=surface,
                claim_index=index,
                claim_hash=content_digest(claim.to_json_dict()),
                reason_code="capacity_exhausted",
            )
            candidates.append(
                _ProjectionClaim(
                    surface=surface,
                    claim_index=index,
                    original=claim,
                    projected=ProjectedClaimV1(surface=surface, claim=rewritten),
                    evidence=tuple(
                        sorted(
                            projected_excerpts.values(),
                            key=lambda item: item.sort_key,
                        )
                    ),
                    omission=omission,
                )
            )
    return tuple(candidates)


def _project_excerpt(
    excerpt: EvidenceExcerptV1,
    source_id: str,
    domain_key: str,
) -> EvidenceExcerptV1:
    descriptor = EvidenceAuthorityDescriptorV1(
        source_id=source_id,
        source_relative_path=excerpt.source_relative_path,
        authority_kind="domain_projection",
        origin_domain_key=domain_key,
    )
    return EvidenceExcerptV1(
        evidence_authority_id=evidence_authority_id(descriptor),
        source_relative_path=excerpt.source_relative_path,
        ownership="domain_projection",
        origin_domain_key=domain_key,
        mode=excerpt.mode,
        source_blob_hash=excerpt.source_blob_hash,
        start_line=excerpt.start_line,
        end_line=excerpt.end_line,
        raw_excerpt_hash=excerpt.raw_excerpt_hash,
        text_lf=excerpt.text_lf,
        complete_file=excerpt.complete_file,
    )


def _allocate_domain_projection(
    domain_key: str,
    presentation_domain_id: str,
    baseline_hash: str,
    debt: DepthDebtV1,
    debt_hash: str,
    candidates: tuple[_ProjectionClaim, ...],
    existing: tuple[DomainProjectionV1, ...],
    policy: ProjectionPolicyV1,
) -> tuple[
    DomainProjectionV1 | None,
    tuple[OmittedProjectedClaimDescriptorV1, ...],
]:
    retained: list[_ProjectionClaim] = []
    for candidate in candidates:
        proposal = tuple((*retained, candidate))
        projection = _projection_value(
            domain_key,
            presentation_domain_id,
            baseline_hash,
            debt,
            debt_hash,
            proposal,
            tuple(item for item in candidates if item not in proposal),
        )
        if _projection_fits(projection, existing, policy):
            retained.append(candidate)
    omitted = tuple(item for item in candidates if item not in retained)
    projection = _projection_value(
        domain_key,
        presentation_domain_id,
        baseline_hash,
        debt,
        debt_hash,
        tuple(retained),
        omitted,
    )
    if not _projection_fits(projection, existing, policy):
        return None, tuple(item.omission for item in candidates)
    return projection, tuple(item.omission for item in omitted)


def _projection_value(
    domain_key: str,
    presentation_domain_id: str,
    baseline_hash: str,
    debt: DepthDebtV1,
    debt_hash: str,
    retained: tuple[_ProjectionClaim, ...],
    omitted: tuple[_ProjectionClaim, ...],
) -> DomainProjectionV1:
    evidence: dict[str, EvidenceExcerptV1] = {}
    for item in retained:
        for excerpt in item.evidence:
            evidence[excerpt.evidence_authority_id] = excerpt
    omissions = tuple(sorted((item.omission for item in omitted), key=_claim_omission_key))
    return DomainProjectionV1(
        domain_key=domain_key,
        presentation_domain_id=presentation_domain_id,
        baseline_artifact_hash=baseline_hash,
        baseline_depth_debt=debt,
        baseline_depth_debt_hash=debt_hash,
        claims=tuple(item.projected for item in retained),
        evidence=tuple(sorted(evidence.values(), key=lambda item: item.sort_key)),
        retained_claim_count=len(retained),
        omitted_claim_count=len(omissions),
        omitted_claim_descriptor_hash=(
            None
            if not omissions
            else content_digest([item.to_json_dict() for item in omissions])
        ),
    )


def _projection_fits(
    projection: DomainProjectionV1,
    existing: tuple[DomainProjectionV1, ...],
    policy: ProjectionPolicyV1,
) -> bool:
    if (
        len(canonical_json_bytes(projection.to_json_dict()))
        > policy.max_canonical_bytes_per_domain
    ):
        return False
    combined = tuple((*existing, projection))
    return (
        len(canonical_json_bytes([item.to_json_dict() for item in combined]))
        <= policy.max_total_canonical_bytes
    )


def _source_depth_debt(
    direct: DepthDebtV1,
    domains: tuple[tuple[str, DepthDebtV1, str], ...],
    omitted_domains: tuple[OmittedDomainDescriptorV1, ...],
    omitted_claims: tuple[OmittedProjectedClaimDescriptorV1, ...],
    *,
    retained_claim_count: int,
    total_projection_claims: int,
) -> DepthDebtV1:
    debt_descriptors = tuple(
        {"domain_key": domain_key, "baseline_depth_debt_hash": debt_hash}
        for domain_key, _debt, debt_hash in sorted(domains)
    )
    rollup = DomainDepthDebtRollupV1(
        domain_count=len(domains),
        inventory_read_set_entry_count=sum(
            debt.inventory_file_count for _key, debt, _hash in domains
        ),
        fully_selected_read_set_entry_count=sum(
            debt.fully_selected_file_count for _key, debt, _hash in domains
        ),
        partially_selected_read_set_entry_count=sum(
            debt.partially_selected_file_count for _key, debt, _hash in domains
        ),
        omitted_read_set_entry_count=sum(
            debt.omitted_file_count for _key, debt, _hash in domains
        ),
        omitted_range_count=sum(
            debt.omitted_range_count for _key, debt, _hash in domains
        ),
        domain_debt_descriptor_hash=(
            None if not debt_descriptors else content_digest(debt_descriptors)
        ),
    )
    ordered_domains = tuple(sorted(omitted_domains, key=_domain_omission_key))
    ordered_claims = tuple(sorted(omitted_claims, key=_claim_omission_key))
    if retained_claim_count + len(ordered_claims) != total_projection_claims:
        raise Protocol22ContextError(
            "retained and omitted projected claim counts do not balance"
        )
    return DepthDebtV1(
        inventory_file_count=direct.inventory_file_count,
        fully_selected_file_count=direct.fully_selected_file_count,
        partially_selected_file_count=direct.partially_selected_file_count,
        omitted_file_count=direct.omitted_file_count,
        omitted_range_count=direct.omitted_range_count,
        omitted_descriptor_hash=direct.omitted_descriptor_hash,
        domain_depth_debt_rollup=rollup,
        omitted_domain_summary_count=len(ordered_domains),
        omitted_domain_descriptor_hash=(
            None
            if not ordered_domains
            else content_digest([item.to_json_dict() for item in ordered_domains])
        ),
        retained_projected_claim_count=retained_claim_count,
        omitted_projected_claim_count=len(ordered_claims),
        omitted_projected_claim_descriptor_hash=(
            None
            if not ordered_claims
            else content_digest([item.to_json_dict() for item in ordered_claims])
        ),
    )


def _claim_omission_key(
    value: OmittedProjectedClaimDescriptorV1,
) -> tuple[object, ...]:
    return (
        value.domain_key,
        value.surface,
        value.claim_index,
        value.claim_hash,
        value.reason_code,
    )


def _domain_omission_key(
    value: OmittedDomainDescriptorV1,
) -> tuple[str, str, str]:
    return value.domain_key, value.baseline_artifact_hash, value.reason_code


__all__ = (
    "Protocol22ContextError",
    "build_domain_context_bundle",
    "build_source_baseline_root",
    "build_source_overview_context_bundle",
)
