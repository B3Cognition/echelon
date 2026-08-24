"""L2 artifact production over the existing RE v2 values and executor substrate."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import ClassVar, Literal, Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.artifacts import ContextBundleV1, DepthDebtV1
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
from harness.re_v2.protocol_22.model import ArtifactScope, WorkItemV2
from harness.re_v2.protocol_22.policies import layer_policy_hash
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    sorted_unique_digests,
)


DEEPENER_AGENT_ID = "echelon.re-deepener"
DEEPENING_PRODUCER_FAMILY = "compact-deepening"
_BASELINE_KINDS = frozenset({"domain-baseline", "source-overview"})


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
) -> ExecutorContractCatalogV1:
    """Add one L2 role binding while preserving the shared provider contract."""
    if not isinstance(inherited, ExecutorContractCatalogV1):
        raise Protocol22ExecutorError(
            "deepening executor construction requires an executor catalog"
        )
    digest_value(deepener_agent_hash, "deepener_agent_hash")
    baseline = inherited.entry_for("compact-baseline")
    if baseline.request_renderer is None:
        raise Protocol22ExecutorError(
            "compact baseline executor has no shared request renderer"
        )
    deepening = replace(
        baseline,
        producer_family=DEEPENING_PRODUCER_FAMILY,
        request_renderer=replace(
            baseline.request_renderer,
            agent_contract_hash=deepener_agent_hash,
        ),
    )
    return ExecutorContractCatalogV1(
        schema_version=1,
        entries=tuple(
            sorted(
                (*inherited.entries, deepening),
                key=lambda entry: entry.producer_family,
            )
        ),
    )


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
    authorities, invalid_evidence = _validate_context_and_references(
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
        bool(referenced_keys),
    )
    diagnostics: list[str] = []
    if len(artifact_bytes) > policy.max_canonical_json_bytes:
        diagnostics.append("artifact_bound_exceeded")
    if invalid_evidence:
        diagnostics.append("evidence_contract_invalid")
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


__all__ = (
    "DEEPENER_AGENT_ID",
    "DEEPENING_PRODUCER_FAMILY",
    "L2CompactArtifactEnvelopeV1",
    "L2CompactBaselineArtifactV1",
    "build_deepening_executor_catalog",
    "certify_l2_compact_candidate",
    "parse_l2_authorial_candidate",
)
