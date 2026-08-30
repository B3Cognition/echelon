"""L2 artifact production over the existing RE v2 values and executor substrate."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import ClassVar, Literal, Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.artifacts import (
    AcceptedDependencySetV2,
    ArtifactDependencyV1,
    ContextBundleV1,
    DepthDebtV1,
    EvidenceExcerptV1,
    EvidencePackV1,
    OmittedEvidenceDescriptorV1,
    SourceBaselineDomainV1,
)
from harness.re_v2.protocol_22.baseline import (
    CandidateAssessmentReceiptV1,
    CertificationReceiptV2,
    CompactBaselineArtifactV1,
    CompactCandidateInputV1,
    CompactCertificationAssessmentV2,
    CompactCertificationResultV2,
    NormalizedAuthorialPayloadV1,
    Protocol22CertificationError,
    SurfaceV1,
    UnknownV1,
    _certification_key,
    _coverage_assessment,
    _domain_descriptor,
    _minimum_utility,
    _referenced_authority_keys,
    _source_descriptor,
    _validate_context_and_references,
    _validate_verifier,
    parse_authorial_candidate,
)
from harness.re_v2.protocol_22.executors import (
    ExecutorContractCatalogV1,
    Protocol22ExecutorError,
)
from harness.re_v2.protocol_22.evidence import (
    EvidenceAuthorityDescriptorV1,
    _verify_payload,
    evidence_authority_id,
)
from harness.re_v2.protocol_22.inventory import InventoryArtifactV1, InventoryFileV1
from harness.re_v2.protocol_22.inventory import SourcePartitionArtifactV1
from harness.re_v2.protocol_22.model import ArtifactScope, WorkItemV2
from harness.re_v2.protocol_22.partition import (
    FileRecordV1,
    WorkspacePartitionCatalogV1,
)
from harness.re_v2.protocol_22.policies import (
    ArtifactPolicyCatalogV1,
    ContextBundlePolicyParametersV1,
    DomainEvidencePackPolicyParametersV1,
    ProjectionPolicyV1,
    classify_path_role,
    layer_policy_hash,
    policy_for,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    load_canonical_object,
    sorted_unique_digests,
)


DEEPENER_AGENT_ID = "echelon.re-deepener"
DEEPENING_PRODUCER_FAMILY = "compact-deepening"
DEEPENING_IN_PROCESS_ADAPTER_ID = "re-v2-in-process-deepening-v1"
DEEPENING_VERIFIER_ID = "deepening-verifier-v1"
L2_EVIDENCE_PRODUCER_FAMILY = "targeted-evidence-pack"
L2_CONTEXT_PRODUCER_FAMILY = "deepening-context-bundle"
L2_ROOT_PRODUCER_FAMILY = "deepening-source-root"
_BASELINE_KINDS = frozenset({"domain-baseline", "source-overview"})


@dataclass(frozen=True, slots=True)
class L2SourceRootEnvelopeV1:
    artifact_kind: Literal["source-baseline-root"]
    layer: Literal["L2"]
    scope: ArtifactScope
    partition_id: str
    layer_policy_hash: str
    dependency_hashes: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "artifact_kind",
        "layer",
        "scope",
        "partition_id",
        "layer_policy_hash",
        "dependency_hashes",
    )

    def __post_init__(self) -> None:
        if self.artifact_kind != "source-baseline-root" or self.layer != "L2":
            raise Protocol22SchemaError("L2 source root envelope is invalid")
        if not isinstance(self.scope, ArtifactScope) or self.scope.is_domain:
            raise Protocol22SchemaError("L2 source root requires source scope")
        digest_value(self.partition_id, "L2 source root partition_id")
        digest_value(self.layer_policy_hash, "L2 source root policy hash")
        object.__setattr__(
            self,
            "dependency_hashes",
            sorted_unique_digests(
                self.dependency_hashes,
                "L2 source root dependency hashes",
            ),
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "artifact_kind": self.artifact_kind,
            "layer": self.layer,
            "scope": self.scope.to_json_dict(),
            "partition_id": self.partition_id,
            "layer_policy_hash": self.layer_policy_hash,
            "dependency_hashes": list(self.dependency_hashes),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "L2SourceRootEnvelopeV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            artifact_kind=raw["artifact_kind"],
            layer=raw["layer"],
            scope=ArtifactScope.from_json_dict(raw["scope"]),
            partition_id=raw["partition_id"],
            layer_policy_hash=raw["layer_policy_hash"],
            dependency_hashes=raw["dependency_hashes"],
        )


@dataclass(frozen=True, slots=True)
class L2SourceBaselineRootV1:
    schema_version: int
    artifact: L2SourceRootEnvelopeV1
    overview_artifact_hash: str
    domains: tuple[SourceBaselineDomainV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact",
        "overview_artifact_hash",
        "domains",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol22SchemaError("L2 source root schema_version must be 1")
        if not isinstance(self.artifact, L2SourceRootEnvelopeV1):
            raise Protocol22SchemaError("L2 source root envelope is invalid")
        digest_value(self.overview_artifact_hash, "L2 source root overview hash")
        if not isinstance(self.domains, (list, tuple)) or any(
            not isinstance(item, SourceBaselineDomainV1) for item in self.domains
        ):
            raise Protocol22SchemaError("L2 source root domains are invalid")
        domains = tuple(self.domains)
        keys = tuple(item.domain_key for item in domains)
        if keys != tuple(sorted(set(keys))) or not domains:
            raise Protocol22SchemaError(
                "L2 source root domains must be nonempty, sorted, and unique"
            )
        expected = tuple(
            sorted(
                (
                    self.overview_artifact_hash,
                    *(item.baseline_artifact_hash for item in domains),
                )
            )
        )
        if self.artifact.dependency_hashes != expected:
            raise Protocol22SchemaError(
                "L2 source root dependency hashes do not equal selected outputs"
            )
        object.__setattr__(self, "domains", domains)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact": self.artifact.to_json_dict(),
            "overview_artifact_hash": self.overview_artifact_hash,
            "domains": [item.to_json_dict() for item in self.domains],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "L2SourceBaselineRootV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        domains = raw["domains"]
        if not isinstance(domains, (list, tuple)):
            raise Protocol22SchemaError("L2 source root domains must be an array")
        return cls(
            schema_version=raw["schema_version"],
            artifact=L2SourceRootEnvelopeV1.from_json_dict(raw["artifact"]),
            overview_artifact_hash=raw["overview_artifact_hash"],
            domains=tuple(SourceBaselineDomainV1.from_json_dict(item) for item in domains),
        )


@dataclass(frozen=True, slots=True)
class L2CompactArtifactEnvelopeV1:
    artifact_kind: Literal["domain-baseline", "source-overview"]
    layer: Literal["L2"]
    scope: ArtifactScope
    partition_id: str
    layer_policy_hash: str
    dependency_hashes: tuple[str, ...]
    context_bundle_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "artifact_kind",
        "layer",
        "scope",
        "partition_id",
        "layer_policy_hash",
        "dependency_hashes",
        "context_bundle_hash",
    )

    def __post_init__(self) -> None:
        if self.artifact_kind not in _BASELINE_KINDS:
            raise Protocol22SchemaError("L2 compact artifact kind is unsupported")
        if self.layer != "L2":
            raise Protocol22SchemaError("L2 compact artifact layer must be L2")
        if not isinstance(self.scope, ArtifactScope) or self.scope.content_id is None:
            raise Protocol22SchemaError("L2 compact artifact requires content scope")
        if (self.artifact_kind == "domain-baseline") != self.scope.is_domain:
            raise Protocol22SchemaError("L2 compact artifact scope is invalid")
        digest_value(self.partition_id, "L2 compact artifact partition_id")
        digest_value(self.layer_policy_hash, "L2 compact artifact policy hash")
        dependencies = sorted_unique_digests(
            self.dependency_hashes,
            "L2 compact artifact dependency hashes",
        )
        digest_value(self.context_bundle_hash, "L2 compact artifact context hash")
        if dependencies != (self.context_bundle_hash,):
            raise Protocol22SchemaError(
                "L2 compact artifact must depend only on its context bundle"
            )
        object.__setattr__(self, "dependency_hashes", dependencies)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "artifact_kind": self.artifact_kind,
            "layer": self.layer,
            "scope": self.scope.to_json_dict(),
            "partition_id": self.partition_id,
            "layer_policy_hash": self.layer_policy_hash,
            "dependency_hashes": list(self.dependency_hashes),
            "context_bundle_hash": self.context_bundle_hash,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "L2CompactArtifactEnvelopeV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            artifact_kind=raw["artifact_kind"],
            layer=raw["layer"],
            scope=ArtifactScope.from_json_dict(raw["scope"]),
            partition_id=raw["partition_id"],
            layer_policy_hash=raw["layer_policy_hash"],
            dependency_hashes=raw["dependency_hashes"],
            context_bundle_hash=raw["context_bundle_hash"],
        )


@dataclass(frozen=True, slots=True)
class L2CompactBaselineArtifactV1:
    schema_version: int
    artifact: L2CompactArtifactEnvelopeV1
    surfaces: Mapping[str, SurfaceV1]
    unknowns: tuple[UnknownV1, ...]
    depth_debt: DepthDebtV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact",
        "surfaces",
        "unknowns",
        "depth_debt",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol22SchemaError("L2 compact artifact schema_version must be 1")
        if not isinstance(self.artifact, L2CompactArtifactEnvelopeV1):
            raise Protocol22SchemaError("L2 compact artifact envelope is invalid")
        normalized = NormalizedAuthorialPayloadV1(
            schema_version=1,
            artifact_kind=self.artifact.artifact_kind,
            surfaces=self.surfaces,
            unknowns=self.unknowns,
        )
        if not isinstance(self.depth_debt, DepthDebtV1):
            raise Protocol22SchemaError("L2 compact depth debt is invalid")
        object.__setattr__(self, "surfaces", normalized.surfaces)
        object.__setattr__(self, "unknowns", normalized.unknowns)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact": self.artifact.to_json_dict(),
            "surfaces": {
                name: value.to_json_dict() for name, value in self.surfaces.items()
            },
            "unknowns": [value.to_json_dict() for value in self.unknowns],
            "depth_debt": self.depth_debt.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "L2CompactBaselineArtifactV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        envelope = L2CompactArtifactEnvelopeV1.from_json_dict(raw["artifact"])
        surfaces = raw["surfaces"]
        unknowns = raw["unknowns"]
        if not isinstance(surfaces, Mapping) or not isinstance(unknowns, (list, tuple)):
            raise Protocol22SchemaError("L2 compact payload collections are invalid")
        return cls(
            schema_version=raw["schema_version"],
            artifact=envelope,
            surfaces={name: SurfaceV1.from_json_dict(item) for name, item in surfaces.items()},
            unknowns=tuple(UnknownV1.from_json_dict(item) for item in unknowns),
            depth_debt=DepthDebtV1.from_json_dict(raw["depth_debt"]),
        )


def build_deepening_executor_catalog(
    inherited: ExecutorContractCatalogV1,
    deepener_agent_hash: str,
    deepening_implementation_digest: str,
) -> ExecutorContractCatalogV1:
    """Add one L2 role binding while preserving the shared provider contract."""
    if not isinstance(inherited, ExecutorContractCatalogV1):
        raise Protocol22ExecutorError(
            "deepening executor construction requires an executor catalog"
        )
    digest_value(deepener_agent_hash, "deepener_agent_hash")
    implementation_digest = digest_value(
        deepening_implementation_digest,
        "deepening_implementation_digest",
    )
    baseline = inherited.entry_for("compact-baseline")
    if baseline.request_renderer is None:
        raise Protocol22ExecutorError(
            "compact baseline executor has no shared request renderer"
        )
    verifier = replace(
        baseline.verifier,
        verifier_id=DEEPENING_VERIFIER_ID,
        verifier_version="v1",
        implementation_digest=implementation_digest,
    )
    deepening = replace(
        baseline,
        producer_family=DEEPENING_PRODUCER_FAMILY,
        verifier=verifier,
        request_renderer=replace(
            baseline.request_renderer,
            agent_contract_hash=deepener_agent_hash,
        ),
    )
    deterministic = []
    for inherited_family, l2_family in (
        ("evidence-pack", L2_EVIDENCE_PRODUCER_FAMILY),
        ("context-bundle", L2_CONTEXT_PRODUCER_FAMILY),
        ("source-baseline-root", L2_ROOT_PRODUCER_FAMILY),
    ):
        deterministic.append(
            replace(
                inherited.entry_for(inherited_family),
                producer_family=l2_family,
                adapter_id=DEEPENING_IN_PROCESS_ADAPTER_ID,
                executor_implementation_digest=implementation_digest,
                verifier=verifier,
            )
        )
    replaced_families = {
        DEEPENING_PRODUCER_FAMILY,
        L2_EVIDENCE_PRODUCER_FAMILY,
        L2_CONTEXT_PRODUCER_FAMILY,
        L2_ROOT_PRODUCER_FAMILY,
    }
    retained = tuple(
        entry
        for entry in inherited.entries
        if entry.producer_family not in replaced_families
    )
    return ExecutorContractCatalogV1(
        schema_version=1,
        entries=tuple(
            sorted(
                (*retained, *deterministic, deepening),
                key=lambda entry: entry.producer_family,
            )
        ),
    )


def build_l2_domain_evidence_pack(
    work_item: WorkItemV2,
    accepted_inputs: AcceptedDependencySetV2,
    policies: ArtifactPolicyCatalogV1,
    snapshot: object,
    adopted_authority: Mapping[tuple[str, str | None, str, str], bytes],
) -> bytes:
    """Select the deterministic complement of adopted L0 domain evidence."""
    _validate_l2_deterministic_item(
        work_item,
        accepted_inputs,
        policies,
        "domain-evidence-pack",
        frozenset({"domain_inventory"}),
    )
    policy = policy_for(policies, "L2", "domain-evidence-pack")
    parameters = policy.policy_parameters
    if not isinstance(parameters, DomainEvidencePackPolicyParametersV1):
        raise Protocol22CertificationError(
            "L2 domain evidence policy parameters are invalid"
        )
    inventory_bytes = accepted_inputs.payload_for_role("domain_inventory")
    authority_prefix = (
        work_item.output_key.scope.source_id,
        work_item.output_key.scope.domain_key,
    )
    try:
        l0_bytes = adopted_authority[(*authority_prefix, "L0", "domain-evidence-pack")]
        context_bytes = adopted_authority[
            (*authority_prefix, "L1", "domain-context-bundle")
        ]
        baseline_bytes = adopted_authority[
            (*authority_prefix, "L1", "domain-baseline")
        ]
    except KeyError as exc:
        raise Protocol22CertificationError(
            "adopted parent authority lacks the L2 domain selection closure"
        ) from exc
    inventory = load_canonical_object(
        inventory_bytes,
        InventoryArtifactV1.from_json_dict,
    )
    l0 = load_canonical_object(l0_bytes, EvidencePackV1.from_json_dict)
    l1_context = load_canonical_object(context_bytes, ContextBundleV1.from_json_dict)
    l1_baseline = load_canonical_object(
        baseline_bytes,
        CompactBaselineArtifactV1.from_json_dict,
    )
    l0_policy = policy_for(policies, "L0", "domain-evidence-pack")
    if (
        inventory.artifact_kind != "domain-inventory"
        or inventory.scope != work_item.output_key.scope
        or inventory.partition_id != work_item.output_key.partition_id
        or l0.artifact_kind != "domain-evidence-pack"
        or l0.scope != work_item.output_key.scope
        or l0.inventory_artifact_hash != content_digest(inventory_bytes)
        or l0.layer_policy_hash != layer_policy_hash(l0_policy)
        or l1_context.artifact_kind != "domain-context-bundle"
        or l1_context.scope != work_item.output_key.scope
        or l1_baseline.artifact.scope != work_item.output_key.scope
        or l1_baseline.artifact.context_bundle_hash != content_digest(context_bytes)
    ):
        raise Protocol22CertificationError(
            "adopted domain authority does not match L2 evidence scope"
        )
    cited_paths = {
        reference.path
        for surface in l1_baseline.surfaces.values()
        for claim in surface.items
        for reference in claim.evidence
    }
    cited_paths.update(
        reference.path
        for unknown in l1_baseline.unknowns
        for reference in unknown.inspected_evidence
    )
    covered_end: dict[str, int] = {}
    for excerpt in l0.excerpts:
        covered_end[excerpt.source_relative_path] = max(
            covered_end.get(excerpt.source_relative_path, 0),
            excerpt.end_line,
        )
    candidates: list[tuple[InventoryFileV1, tuple[bytes, ...], int]] = []
    ineligible: list[OmittedEvidenceDescriptorV1] = []
    for row in inventory.files:
        if (
            row.object_kind != "regular"
            or row.text_status != "eligible_utf8"
            or classify_path_role(row.source_relative_path, parameters.path_classifiers)
            is None
        ):
            ineligible.append(_l2_file_omission(row, work_item, "policy_ineligible"))
            continue
        payload = snapshot.read_file(
            work_item.output_key.scope.source_id,
            row.source_relative_path,
            _inventory_record(row),
        )
        _verify_payload(_inventory_record(row), payload)
        lines = _raw_lines(payload)
        start = min(len(lines), covered_end.get(row.source_relative_path, 0))
        candidates.append((row, lines, start))
    candidates.sort(
        key=lambda value: (
            value[0].source_relative_path not in cited_paths,
            value[0].sort_key,
        )
    )
    selected = {row.source_relative_path: 0 for row, _lines, _start in candidates}
    while True:
        progressed = False
        for row, lines, start in candidates:
            chosen = selected[row.source_relative_path]
            if start + chosen >= len(lines):
                continue
            proposal = dict(selected)
            proposal[row.source_relative_path] = chosen + 1
            candidate = _l2_evidence_value(
                work_item,
                policy,
                inventory,
                candidates,
                proposal,
                tuple(ineligible),
            )
            if len(canonical_json_bytes(candidate)) <= _policy_cap(policy):
                selected = proposal
                progressed = True
        if not progressed:
            break
    value = _l2_evidence_value(
        work_item,
        policy,
        inventory,
        candidates,
        selected,
        tuple(ineligible),
    )
    return canonical_json_bytes(EvidencePackV1.from_json_dict(value).to_json_dict())


def build_l2_domain_context_bundle(
    work_item: WorkItemV2,
    accepted_inputs: AcceptedDependencySetV2,
    policies: ArtifactPolicyCatalogV1,
) -> bytes:
    """Bind one targeted L2 evidence pack to the shared context schema."""
    context_policy = _validate_l2_deterministic_item(
        work_item,
        accepted_inputs,
        policies,
        "domain-context-bundle",
        frozenset({"domain_inventory", "domain_evidence_pack"}),
    )
    target_policy = policy_for(policies, "L2", "domain-baseline")
    evidence_bytes = accepted_inputs.payload_for_role("domain_evidence_pack")
    inventory_bytes = accepted_inputs.payload_for_role("domain_inventory")
    evidence = load_canonical_object(evidence_bytes, EvidencePackV1.from_json_dict)
    evidence_hash = content_digest(evidence_bytes)
    if (
        evidence.artifact_kind != "domain-evidence-pack"
        or evidence.scope != work_item.output_key.scope
        or evidence.inventory_artifact_hash != content_digest(inventory_bytes)
        or evidence.layer_policy_hash
        != layer_policy_hash(policy_for(policies, "L2", "domain-evidence-pack"))
    ):
        raise Protocol22CertificationError(
            "targeted evidence does not match L2 domain context"
        )
    bundle = ContextBundleV1(
        schema_version=1,
        artifact_kind="domain-context-bundle",
        target_artifact_kind="domain-baseline",
        scope=work_item.output_key.scope,
        context_policy_hash=work_item.output_key.layer_policy_hash,
        target_policy_hash=layer_policy_hash(target_policy),
        target_artifact_policy=target_policy,
        dependencies=tuple(
            sorted(
                (
                    ArtifactDependencyV1(
                        "domain-evidence-pack",
                        evidence_hash,
                    ),
                    ArtifactDependencyV1(
                        "domain-inventory",
                        content_digest(inventory_bytes),
                    ),
                ),
                key=lambda value: (value.artifact_kind, value.artifact_hash),
            )
        ),
        evidence_pack_hash=evidence_hash,
        evidence=evidence.excerpts,
        domain_projections=(),
        depth_debt=evidence.depth_debt,
    )
    return _bounded_payload(bundle.to_json_dict(), context_policy)


def build_l2_source_overview_context_bundle(
    work_item: WorkItemV2,
    accepted_inputs: AcceptedDependencySetV2,
    policies: ArtifactPolicyCatalogV1,
) -> bytes:
    """Compose source evidence with projections from only selected L2 domains."""
    from harness.re_v2.protocol_22.context import (
        _DomainBaselineView,
        _SurfaceView,
        _allocate_domain_projection,
        _projection_claims,
        _source_depth_debt,
    )

    domain_roles = tuple(
        sorted(role for role in accepted_inputs.by_role if role.startswith("domain:"))
    )
    expected_roles = frozenset(
        {
            "source_inventory",
            "source_partition",
            "source_evidence_pack",
            *domain_roles,
        }
    )
    context_policy = _validate_l2_deterministic_item(
        work_item,
        accepted_inputs,
        policies,
        "source-overview-context-bundle",
        expected_roles,
    )
    if not domain_roles:
        raise Protocol22CertificationError(
            "L2 source context requires at least one selected domain"
        )
    parameters = context_policy.policy_parameters
    if not isinstance(parameters, ContextBundlePolicyParametersV1) or not isinstance(
        parameters.projection,
        ProjectionPolicyV1,
    ):
        raise Protocol22CertificationError(
            "L2 source context has no projection policy"
        )
    target_policy = policy_for(policies, "L2", "source-overview")
    inventory_bytes = accepted_inputs.payload_for_role("source_inventory")
    partition_bytes = accepted_inputs.payload_for_role("source_partition")
    evidence_bytes = accepted_inputs.payload_for_role("source_evidence_pack")
    inventory = load_canonical_object(
        inventory_bytes,
        InventoryArtifactV1.from_json_dict,
    )
    partition = load_canonical_object(
        partition_bytes,
        SourcePartitionArtifactV1.from_json_dict,
    )
    evidence = load_canonical_object(evidence_bytes, EvidencePackV1.from_json_dict)
    source_id = work_item.output_key.scope.source_id
    if (
        inventory.artifact_kind != "source-inventory"
        or inventory.scope.source_id != source_id
        or inventory.scope.domain_key is not None
        or partition.source_scope.source_id != source_id
        or partition.source_partition_id != work_item.output_key.partition_id
        or evidence.artifact_kind != "source-evidence-pack"
        or evidence.scope != inventory.scope
        or evidence.inventory_artifact_hash != content_digest(inventory_bytes)
        or evidence.layer_policy_hash
        != layer_policy_hash(policy_for(policies, "L0", "source-evidence-pack"))
    ):
        raise Protocol22CertificationError(
            "adopted source authority does not match L2 source context"
        )
    descriptors = {domain.domain_key: domain for domain in partition.domains}
    target_domain_policy = policy_for(policies, "L2", "domain-baseline")
    projections = []
    domain_debt = []
    omitted_domains = []
    omitted_claims = []
    total_projection_claims = 0
    dependency_rows = [
        ("source-inventory", content_digest(inventory_bytes)),
        ("source-partition", content_digest(partition_bytes)),
        ("source-evidence-pack", content_digest(evidence_bytes)),
    ]
    for role in domain_roles:
        domain_key = role.removeprefix("domain:")
        descriptor = descriptors.get(domain_key)
        if descriptor is None:
            raise Protocol22CertificationError(
                "selected L2 domain is outside the source partition"
            )
        baseline_bytes = accepted_inputs.payload_for_role(role)
        baseline = load_canonical_object(
            baseline_bytes,
            L2CompactBaselineArtifactV1.from_json_dict,
        )
        domain_context = load_canonical_object(
            accepted_inputs.payload_for_hash(baseline.artifact.context_bundle_hash),
            ContextBundleV1.from_json_dict,
        )
        if (
            baseline.artifact.artifact_kind != "domain-baseline"
            or baseline.artifact.scope.source_id != source_id
            or baseline.artifact.scope.domain_key != domain_key
            or baseline.artifact.partition_id != descriptor.domain_partition_id
            or baseline.artifact.layer_policy_hash
            != layer_policy_hash(target_domain_policy)
            or domain_context.target_artifact_policy != target_domain_policy
            or domain_context.scope != baseline.artifact.scope
            or domain_context.depth_debt != baseline.depth_debt
        ):
            raise Protocol22CertificationError(
                "selected L2 domain closure is inconsistent"
            )
        view = _DomainBaselineView(
            schema_version=1,
            scope=baseline.artifact.scope,
            partition_id=baseline.artifact.partition_id,
            layer_policy_hash=baseline.artifact.layer_policy_hash,
            dependency_hashes=baseline.artifact.dependency_hashes,
            context_bundle_hash=baseline.artifact.context_bundle_hash,
            surfaces={
                name: _SurfaceView(
                    value.status,
                    value.items,
                    value.not_established_reason_code,
                )
                for name, value in baseline.surfaces.items()
            },
            unknowns=baseline.unknowns,
            depth_debt=baseline.depth_debt,
        )
        baseline_hash = content_digest(baseline_bytes)
        debt_hash = content_digest(baseline.depth_debt.to_json_dict())
        domain_debt.append((domain_key, baseline.depth_debt, debt_hash))
        candidates = _projection_claims(
            view,
            domain_context,
            domain_key,
            parameters.projection,
        )
        total_projection_claims += len(candidates)
        projection, omitted = _allocate_domain_projection(
            domain_key,
            descriptor.presentation_domain_id,
            baseline_hash,
            baseline.depth_debt,
            debt_hash,
            candidates,
            tuple(projections),
            parameters.projection,
        )
        dependency_rows.append(("domain-baseline", baseline_hash))
        if projection is None:
            from harness.re_v2.protocol_22.artifacts import OmittedDomainDescriptorV1

            omitted_domains.append(
                OmittedDomainDescriptorV1(
                    domain_key=domain_key,
                    baseline_artifact_hash=baseline_hash,
                    reason_code="capacity_exhausted",
                )
            )
            omitted_claims.extend(value.omission for value in candidates)
        else:
            projections.append(projection)
            omitted_claims.extend(omitted)
    debt = _source_depth_debt(
        evidence.depth_debt,
        tuple(domain_debt),
        tuple(omitted_domains),
        tuple(omitted_claims),
        retained_claim_count=sum(value.retained_claim_count for value in projections),
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
        dependencies=tuple(
            sorted(
                (
                    ArtifactDependencyV1(kind, artifact_hash)
                    for kind, artifact_hash in dependency_rows
                ),
                key=lambda value: (value.artifact_kind, value.artifact_hash),
            )
        ),
        evidence_pack_hash=content_digest(evidence_bytes),
        evidence=evidence.excerpts,
        domain_projections=tuple(projections),
        depth_debt=debt,
    )
    return _bounded_payload(bundle.to_json_dict(), context_policy)


def build_l2_source_baseline_root(
    work_item: WorkItemV2,
    accepted_inputs: AcceptedDependencySetV2,
    partition: WorkspacePartitionCatalogV1,
) -> bytes:
    """Bind the L2 overview and exactly the selected L2 domain outputs."""
    if (
        not isinstance(work_item, WorkItemV2)
        or work_item.output_key.artifact_kind != "source-baseline-root"
        or work_item.output_key.layer != "L2"
        or work_item.goal_id != "selective-deepening"
        or work_item.producer_family != L2_ROOT_PRODUCER_FAMILY
        or not isinstance(accepted_inputs, AcceptedDependencySetV2)
        or not isinstance(partition, WorkspacePartitionCatalogV1)
    ):
        raise Protocol22CertificationError("L2 source root invocation is invalid")
    source = next(
        (
            value
            for value in partition.sources
            if value.source_id == work_item.output_key.scope.source_id
        ),
        None,
    )
    if source is None or work_item.output_key.partition_id != source.source_partition_id:
        raise Protocol22CertificationError("L2 source root scope is not partitioned")
    domain_roles = tuple(sorted(role for role in accepted_inputs.by_role if role.startswith("domain:")))
    if frozenset(accepted_inputs.by_role) != frozenset(
        {"source_overview", *domain_roles}
    ) or not domain_roles:
        raise Protocol22CertificationError("L2 source root dependency roles are invalid")
    _validate_dependency_hashes(work_item, accepted_inputs)
    by_domain = {domain.domain_key: domain for domain in source.domains}
    domains: list[SourceBaselineDomainV1] = []
    for role in domain_roles:
        domain_key = role.removeprefix("domain:")
        descriptor = by_domain.get(domain_key)
        if descriptor is None:
            raise Protocol22CertificationError(
                "L2 source root contains an unpartitioned domain"
            )
        domains.append(
            SourceBaselineDomainV1(
                domain_key=domain_key,
                presentation_domain_id=descriptor.presentation_domain_id,
                baseline_artifact_hash=accepted_inputs.by_role[role].artifact_hash,
            )
        )
    root = L2SourceBaselineRootV1(
        schema_version=1,
        artifact=L2SourceRootEnvelopeV1(
            artifact_kind="source-baseline-root",
            layer="L2",
            scope=work_item.output_key.scope,
            partition_id=work_item.output_key.partition_id,
            layer_policy_hash=work_item.output_key.layer_policy_hash,
            dependency_hashes=work_item.output_key.dependency_hashes,
        ),
        overview_artifact_hash=accepted_inputs.by_role["source_overview"].artifact_hash,
        domains=tuple(sorted(domains, key=lambda value: value.domain_key)),
    )
    return canonical_json_bytes(root.to_json_dict())


def _validate_l2_deterministic_item(
    work_item: WorkItemV2,
    accepted_inputs: AcceptedDependencySetV2,
    policies: ArtifactPolicyCatalogV1,
    artifact_kind: str,
    expected_roles: frozenset[str],
):
    if (
        not isinstance(work_item, WorkItemV2)
        or not isinstance(accepted_inputs, AcceptedDependencySetV2)
        or not isinstance(policies, ArtifactPolicyCatalogV1)
        or work_item.goal_id != "selective-deepening"
        or work_item.output_key.layer != "L2"
        or work_item.output_key.artifact_kind != artifact_kind
    ):
        raise Protocol22CertificationError("L2 deterministic invocation is invalid")
    policy = policy_for(policies, "L2", artifact_kind)
    expected_family = {
        "domain-evidence-pack": L2_EVIDENCE_PRODUCER_FAMILY,
        "domain-context-bundle": L2_CONTEXT_PRODUCER_FAMILY,
        "source-overview-context-bundle": L2_CONTEXT_PRODUCER_FAMILY,
    }[artifact_kind]
    if (
        work_item.producer_family != expected_family
        or work_item.output_key.layer_policy_hash != layer_policy_hash(policy)
        or work_item.producer_protocol_version != policy.producer_protocol_version
        or work_item.result_contract_id != policy.result_contract_id
        or frozenset(accepted_inputs.by_role) != expected_roles
    ):
        raise Protocol22CertificationError("L2 deterministic authority mismatch")
    _validate_dependency_hashes(work_item, accepted_inputs)
    return policy


def _validate_dependency_hashes(
    work_item: WorkItemV2,
    accepted_inputs: AcceptedDependencySetV2,
) -> None:
    hashes = tuple(
        sorted(value.artifact_hash for value in accepted_inputs.by_role.values())
    )
    if (
        len(hashes) != len(set(hashes))
        or hashes != work_item.required_artifact_hashes
        or hashes != work_item.output_key.dependency_hashes
    ):
        raise Protocol22CertificationError(
            "L2 accepted dependency hashes do not equal work item closure"
        )


def _inventory_record(row: InventoryFileV1) -> FileRecordV1:
    return FileRecordV1(
        **{field: getattr(row, field) for field in FileRecordV1.FIELDS}
    )


def _raw_lines(payload: bytes) -> tuple[bytes, ...]:
    if not payload:
        return ()
    return tuple(payload.splitlines(keepends=True))


def _l2_file_omission(
    row: InventoryFileV1,
    work_item: WorkItemV2,
    reason: Literal["policy_ineligible", "capacity_exhausted", "non_text"],
) -> OmittedEvidenceDescriptorV1:
    return OmittedEvidenceDescriptorV1(
        descriptor_kind="file",
        source_relative_path=row.source_relative_path,
        ownership=row.ownership,
        origin_domain_key=work_item.output_key.scope.domain_key,
        start_line=None,
        end_line=None,
        reason_code=reason,
    )


def _l2_evidence_value(
    work_item: WorkItemV2,
    policy: object,
    inventory: InventoryArtifactV1,
    candidates: list[tuple[InventoryFileV1, tuple[bytes, ...], int]],
    selected: Mapping[str, int],
    ineligible: tuple[OmittedEvidenceDescriptorV1, ...],
) -> dict[str, object]:
    excerpts: list[EvidenceExcerptV1] = []
    omissions = list(ineligible)
    fully_selected = 0
    partially_selected = 0
    omitted_files = len(ineligible)
    omitted_ranges = 0
    for row, lines, covered in candidates:
        count = selected[row.source_relative_path]
        combined = covered + count
        if combined:
            start_line = 1
            end_line = combined
            raw = b"".join(lines[:combined])
            descriptor = EvidenceAuthorityDescriptorV1(
                source_id=work_item.output_key.scope.source_id,
                source_relative_path=row.source_relative_path,
                authority_kind="direct",
                origin_domain_key=work_item.output_key.scope.domain_key,
            )
            excerpts.append(
                EvidenceExcerptV1(
                    evidence_authority_id=evidence_authority_id(descriptor),
                    source_relative_path=row.source_relative_path,
                    ownership=row.ownership,
                    origin_domain_key=work_item.output_key.scope.domain_key,
                    mode=row.mode,
                    source_blob_hash=row.content_hash,
                    start_line=start_line,
                    end_line=end_line,
                    raw_excerpt_hash=content_digest(raw),
                    text_lf=raw.decode("utf-8", errors="strict").replace("\r\n", "\n"),
                    complete_file=start_line == 1 and end_line == len(lines),
                )
            )
        if combined >= len(lines):
            fully_selected += 1
        elif combined == 0:
            omitted_files += 1
            omissions.append(_l2_file_omission(row, work_item, "capacity_exhausted"))
        else:
            partially_selected += 1
            omitted_ranges += 1
            omissions.append(
                OmittedEvidenceDescriptorV1(
                    descriptor_kind="line_range",
                    source_relative_path=row.source_relative_path,
                    ownership=row.ownership,
                    origin_domain_key=work_item.output_key.scope.domain_key,
                    start_line=combined + 1,
                    end_line=len(lines),
                    reason_code="capacity_exhausted",
                )
            )
    omissions.sort(
        key=lambda value: (
            value.source_relative_path.encode("utf-8"),
            value.ownership,
            "" if value.origin_domain_key is None else value.origin_domain_key,
            value.descriptor_kind,
            0 if value.start_line is None else value.start_line,
            0 if value.end_line is None else value.end_line,
            value.reason_code,
        )
    )
    debt = DepthDebtV1(
        inventory_file_count=len(inventory.files),
        fully_selected_file_count=fully_selected,
        partially_selected_file_count=partially_selected,
        omitted_file_count=omitted_files,
        omitted_range_count=omitted_ranges,
        omitted_descriptor_hash=(
            None
            if not omissions
            else content_digest([value.to_json_dict() for value in omissions])
        ),
        domain_depth_debt_rollup=None,
        omitted_domain_summary_count=0,
        omitted_domain_descriptor_hash=None,
        retained_projected_claim_count=0,
        omitted_projected_claim_count=0,
        omitted_projected_claim_descriptor_hash=None,
    )
    return {
        "schema_version": 1,
        "artifact_kind": "domain-evidence-pack",
        "scope": work_item.output_key.scope.to_json_dict(),
        "layer_policy_hash": work_item.output_key.layer_policy_hash,
        "inventory_artifact_hash": content_digest(inventory.to_json_dict()),
        "byte_estimator_id": policy.byte_estimator_id,
        "max_canonical_json_bytes": policy.max_canonical_json_bytes,
        "max_conservative_input_tokens": policy.max_conservative_input_tokens,
        "excerpts": [
            value.to_json_dict()
            for value in sorted(excerpts, key=lambda value: value.sort_key)
        ],
        "depth_debt": debt.to_json_dict(),
    }


def _policy_cap(policy: object) -> int:
    token_cap = getattr(policy, "max_conservative_input_tokens", None)
    json_cap = getattr(policy, "max_canonical_json_bytes", None)
    if not isinstance(token_cap, int) or not isinstance(json_cap, int):
        raise Protocol22CertificationError("L2 policy has no closed byte cap")
    return min(token_cap, json_cap)


def _bounded_payload(value: object, policy: object) -> bytes:
    payload = canonical_json_bytes(value)
    caps = [getattr(policy, "max_canonical_json_bytes")]
    for field in ("max_context_bundle_bytes", "max_conservative_input_tokens"):
        candidate = getattr(policy, field)
        if candidate is not None:
            caps.append(candidate)
    if len(payload) > min(caps):
        raise Protocol22CertificationError("L2 deterministic payload exceeds policy")
    return payload


def certify_l2_compact_candidate(
    candidate: CompactCandidateInputV1,
    work_item: WorkItemV2,
    context: ContextBundleV1,
    snapshot: object,
    verifier: object,
    *,
    adopted_l1_artifacts: tuple[bytes, ...] = (),
) -> CompactCertificationResultV2:
    """Certify one L2 candidate with the shared compact assessment receipts."""
    _validate_l2_invocation(candidate, work_item, context, snapshot, verifier)
    policy = context.target_artifact_policy
    context_hash = content_digest(context.to_json_dict())
    artifact = L2CompactBaselineArtifactV1(
        schema_version=1,
        artifact=L2CompactArtifactEnvelopeV1(
            artifact_kind=work_item.output_key.artifact_kind,
            layer="L2",
            scope=work_item.output_key.scope,
            partition_id=work_item.output_key.partition_id,
            layer_policy_hash=work_item.output_key.layer_policy_hash,
            dependency_hashes=work_item.output_key.dependency_hashes,
            context_bundle_hash=context_hash,
        ),
        surfaces=candidate.authorial_payload.surfaces,
        unknowns=candidate.authorial_payload.unknowns,
        depth_debt=context.depth_debt,
    )
    artifact_bytes = canonical_json_bytes(artifact.to_json_dict())
    authorities, evidence_diagnostics = _validate_context_and_references(
        candidate.authorial_payload,
        context,
        snapshot,
    )
    referenced_keys = _referenced_authority_keys(
        candidate.authorial_payload,
        authorities,
    )
    coverage = _coverage_assessment(context, referenced_keys)
    required_surfaces, minimum_utility = _minimum_utility(
        candidate.authorial_payload,
        context,
        snapshot,
        bool(referenced_keys),
    )
    diagnostics: list[str] = []
    if len(artifact_bytes) > policy.max_canonical_json_bytes:
        diagnostics.append("artifact_bound_exceeded")
    if evidence_diagnostics:
        diagnostics.append("evidence_contract_invalid")
        diagnostics.extend(evidence_diagnostics)
    if not minimum_utility.passed:
        diagnostics.append("minimum_utility_not_met")
    if _duplicates_lower_layer_claim(candidate.authorial_payload, adopted_l1_artifacts):
        diagnostics.append("lower_layer_exact_duplicate")
    normalized_diagnostics = tuple(sorted(diagnostics))
    assessment = CompactCertificationAssessmentV2(
        assessment_kind="compact_baseline",
        coverage=coverage,
        depth_debt=context.depth_debt,
        required_surfaces=required_surfaces,
        minimum_utility=minimum_utility,
        normalized_diagnostics=normalized_diagnostics,
        semantic_status="unaudited",
    )
    artifact_hash = content_digest(artifact_bytes)
    certification = CertificationReceiptV2(
        schema_version=2,
        certification_key=_certification_key(work_item, artifact_hash, verifier),
        verdict="accepted" if not normalized_diagnostics else "rejected",
        assessment=assessment,
    )
    candidate_assessment = CandidateAssessmentReceiptV1(
        schema_version=1,
        candidate_id=candidate.candidate_id,
        work_item_id=work_item.work_item_id,
        execution_capture_hash=candidate.execution_capture_hash,
        normalized_authorial_payload_hash=content_digest(
            candidate.authorial_payload.to_json_dict()
        ),
        artifact_hash=artifact_hash,
        certification_receipt_id=certification.identity,
        outcome=(
            "certified"
            if certification.verdict == "accepted"
            else "rejected_after_artifact"
        ),
        normalized_diagnostics=normalized_diagnostics,
    )
    return CompactCertificationResultV2(
        artifact_bytes=artifact_bytes,
        certification=certification,
        candidate_assessment=candidate_assessment,
    )


def parse_l2_authorial_candidate(
    raw: bytes,
    artifact_kind: str,
    policy: object,
) -> NormalizedAuthorialPayloadV1:
    """Reuse the compact parser with the layer-neutral L1 policy shape."""
    if (
        getattr(policy, "layer", None) != "L2"
        or getattr(policy, "artifact_kind", None) != artifact_kind
    ):
        raise Protocol22CertificationError(
            "L2 candidate parsing requires its exact L2 artifact policy"
        )
    return parse_authorial_candidate(
        raw,
        artifact_kind,
        replace(policy, layer="L1"),
    )


def _validate_l2_invocation(
    candidate: CompactCandidateInputV1,
    work_item: WorkItemV2,
    context: ContextBundleV1,
    snapshot: object,
    verifier: object,
) -> None:
    if not isinstance(candidate, CompactCandidateInputV1):
        raise Protocol22CertificationError(
            "L2 certification requires CompactCandidateInputV1"
        )
    if not isinstance(work_item, WorkItemV2) or not isinstance(context, ContextBundleV1):
        raise Protocol22CertificationError(
            "L2 certification requires shared work and context values"
        )
    if not callable(getattr(snapshot, "read_file", None)) or not hasattr(
        snapshot, "partition"
    ):
        raise Protocol22CertificationError(
            "L2 certification requires a partition-bound snapshot reader"
        )
    policy = context.target_artifact_policy
    kind = work_item.output_key.artifact_kind
    if (
        candidate.authorial_payload.artifact_kind != kind
        or kind not in _BASELINE_KINDS
        or policy.layer != "L2"
        or policy.artifact_kind != kind
        or work_item.goal_id != "selective-deepening"
        or work_item.producer_id != "compact-deepening-producer-v1"
        or work_item.producer_family != DEEPENING_PRODUCER_FAMILY
        or work_item.producer_protocol_version != policy.producer_protocol_version
        or work_item.result_contract_id != policy.result_contract_id
        or work_item.output_key.layer != "L2"
        or work_item.output_key.scope != context.scope
        or work_item.output_key.partition_id is None
        or work_item.output_key.layer_policy_hash != context.target_policy_hash
        or work_item.output_key.layer_policy_hash != layer_policy_hash(policy)
        or work_item.required_artifact_hashes
        != (content_digest(context.to_json_dict()),)
        or context.target_artifact_kind != kind
    ):
        raise Protocol22CertificationError(
            "context authority does not match selective L2 work item"
        )
    _validate_verifier(work_item, verifier)
    source = _source_descriptor(snapshot.partition, context.scope.source_id)
    expected_partition = (
        _domain_descriptor(source, context.scope.domain_key).domain_partition_id
        if context.scope.is_domain
        else source.source_partition_id
    )
    expected_content = (
        _domain_descriptor(source, context.scope.domain_key).domain_content_id
        if context.scope.is_domain
        else source.source_content_id
    )
    if (
        work_item.output_key.partition_id != expected_partition
        or context.scope.content_id != expected_content
    ):
        raise Protocol22CertificationError(
            "selective L2 scope does not match snapshot authority"
        )


def _duplicates_lower_layer_claim(
    payload: NormalizedAuthorialPayloadV1,
    artifacts: tuple[bytes, ...],
) -> bool:
    lower_claims: set[tuple[str, object]] = set()
    for artifact_bytes in artifacts:
        if not isinstance(artifact_bytes, bytes):
            raise Protocol22CertificationError(
                "adopted L1 artifact authority must be canonical bytes"
            )
        try:
            from harness.re_v2.protocol_22.schema import load_canonical_object

            artifact = load_canonical_object(
                artifact_bytes,
                CompactBaselineArtifactV1.from_json_dict,
            )
        except (Protocol22SchemaError, ValueError) as exc:
            raise Protocol22CertificationError(
                f"adopted L1 artifact authority is invalid: {exc}"
            ) from exc
        if (
            artifact.artifact.artifact_kind != payload.artifact_kind
            or artifact.artifact.scope.source_id == ""
        ):
            continue
        for surface, value in artifact.surfaces.items():
            for claim in value.items:
                lower_claims.add((surface, claim))
    return any(
        (surface, claim) in lower_claims
        for surface, value in payload.surfaces.items()
        for claim in value.items
    )


def render_l2_baseline_markdown(artifact_bytes: bytes) -> bytes:
    """Render an L2 compact artifact without adding semantic authority."""
    try:
        artifact = load_canonical_object(
            artifact_bytes,
            L2CompactBaselineArtifactV1.from_json_dict,
        )
    except Protocol22SchemaError as exc:
        raise Protocol22CertificationError(
            f"invalid L2 compact artifact: {exc}"
        ) from exc
    title = (
        "Domain L2 Deepening"
        if artifact.artifact.artifact_kind == "domain-baseline"
        else "Source L2 Overview"
    )
    lines = [f"# {title}", ""]
    for name, surface in artifact.surfaces.items():
        lines.extend((f"## {name.replace('_', ' ').title()}", ""))
        if surface.status == "not_established":
            lines.extend(
                (
                    f"Not established: `{surface.not_established_reason_code}`.",
                    "",
                )
            )
            continue
        for claim in surface.items:
            statement_lines = claim.statement.split("\n")
            lines.append(f"- {statement_lines[0]}")
            lines.extend(f"  {line}" for line in statement_lines[1:])
            for reference in claim.evidence:
                lines.append(
                    "  - Evidence: "
                    f"`{reference.path}:{reference.start_line}-{reference.end_line}` "
                    f"(`{reference.evidence_authority_id}`)"
                )
        lines.append("")
    lines.extend(("## Unknowns", ""))
    if artifact.unknowns:
        for unknown in artifact.unknowns:
            question_lines = unknown.question.split("\n")
            lines.append(f"- {question_lines[0]} (`{unknown.reason_code}`)")
            lines.extend(f"  {line}" for line in question_lines[1:])
    else:
        lines.append("- None recorded.")
    debt = artifact.depth_debt
    lines.extend(
        (
            "",
            "## Depth debt",
            "",
            f"- Inventory files: {debt.inventory_file_count}",
            f"- Fully selected files: {debt.fully_selected_file_count}",
            f"- Partially selected files: {debt.partially_selected_file_count}",
            f"- Omitted files: {debt.omitted_file_count}",
            f"- Omitted ranges: {debt.omitted_range_count}",
            "",
            "Semantic audit: not run.",
            "",
        )
    )
    rendered = "\n".join(lines).encode("utf-8")
    if len(rendered) > 96 * 1024:
        raise Protocol22CertificationError(
            "rendered L2 compact baseline exceeds 96 KiB"
        )
    return rendered


__all__ = (
    "DEEPENER_AGENT_ID",
    "DEEPENING_PRODUCER_FAMILY",
    "DEEPENING_IN_PROCESS_ADAPTER_ID",
    "DEEPENING_VERIFIER_ID",
    "L2_CONTEXT_PRODUCER_FAMILY",
    "L2_EVIDENCE_PRODUCER_FAMILY",
    "L2_ROOT_PRODUCER_FAMILY",
    "L2CompactArtifactEnvelopeV1",
    "L2CompactBaselineArtifactV1",
    "L2SourceBaselineRootV1",
    "L2SourceRootEnvelopeV1",
    "build_deepening_executor_catalog",
    "build_l2_domain_context_bundle",
    "build_l2_domain_evidence_pack",
    "build_l2_source_baseline_root",
    "build_l2_source_overview_context_bundle",
    "certify_l2_compact_candidate",
    "parse_l2_authorial_candidate",
    "render_l2_baseline_markdown",
)
