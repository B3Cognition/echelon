"""Closed protocol-2.5 contracts for RE v2 L3 semantic closure."""

PROTOCOL_VERSION = "2.5"
RUN_MANIFEST_SCHEMA_VERSION = 4

from .artifacts import (
    AuditCandidateV1,
    AuditClosureRootV1,
    AuditEpochV1,
    AuditTargetCandidateAuthorityV1,
    FindingAssessmentV1,
    FindingClosureReceiptV1,
    L3SourceRootV1,
    ResolutionEntryV1,
    SemanticCertificationReceiptV1,
    SemanticResolutionOverlayV1,
    SourceCompositionAssessmentV1,
    TargetClosureAssessmentV1,
    build_finding_closure_receipt,
    build_semantic_resolution_overlay,
    build_source_composition_assessment,
)
from .findings import (
    AuditTargetV1,
    AuditedArtifactAuthorityV1,
    DeferredObservationV1,
    EvidenceAnchorAuthorityV1,
    FINDING_CLASSES,
    FindingAuthorityVocabularyV1,
    FindingKeyV1,
    SemanticFindingV1,
    SUBJECT_KINDS,
    normalize_finding_key,
)
from .model import (
    Protocol25SchemaError,
    RunManifestV4,
    RunModeV1,
    SemanticClosurePolicyV1,
)
from .policies import (
    AuditTaxonomyV1,
    SemanticArtifactPolicyCatalogV1,
    SemanticArtifactPolicyEntryV1,
    SemanticExecutorAuthorityV1,
    SemanticExecutorContractCatalogV1,
    SemanticRequestRendererAuthorityV1,
    SemanticResponseSchemaReferenceV1,
    build_semantic_executor_catalog,
    build_semantic_v1_policy_catalog,
)

__all__ = (
    "PROTOCOL_VERSION",
    "RUN_MANIFEST_SCHEMA_VERSION",
    "AuditCandidateV1",
    "AuditClosureRootV1",
    "AuditEpochV1",
    "AuditTargetV1",
    "AuditTargetPlanV1",
    "AuditTargetCandidateAuthorityV1",
    "AuditTaxonomyV1",
    "AuditedArtifactAuthorityV1",
    "DeferredObservationV1",
    "EvidenceAnchorAuthorityV1",
    "FINDING_CLASSES",
    "FindingAuthorityVocabularyV1",
    "FindingAssessmentV1",
    "FindingClosureReceiptV1",
    "FindingKeyV1",
    "L3SourceRootV1",
    "Protocol25SchemaError",
    "Protocol25Graph",
    "Protocol25GraphError",
    "Protocol25GraphInputsV1",
    "RunManifestV4",
    "RunModeV1",
    "ResolutionEntryV1",
    "SUBJECT_KINDS",
    "SemanticFindingV1",
    "SemanticCertificationReceiptV1",
    "SemanticArtifactPolicyCatalogV1",
    "SemanticArtifactPolicyEntryV1",
    "SemanticClosurePolicyV1",
    "SemanticResolutionOverlayV1",
    "SemanticExecutorAuthorityV1",
    "SemanticExecutorContractCatalogV1",
    "SemanticRequestRendererAuthorityV1",
    "SemanticResponseSchemaReferenceV1",
    "SourceCompositionAssessmentV1",
    "TargetClosureAssessmentV1",
    "build_finding_closure_receipt",
    "build_protocol_25_graph",
    "build_semantic_resolution_overlay",
    "build_source_composition_assessment",
    "build_semantic_executor_catalog",
    "build_semantic_v1_policy_catalog",
    "normalize_finding_key",
)


_LAZY_GRAPH_EXPORTS = frozenset(
    {
        "AuditTargetPlanV1",
        "Protocol25Graph",
        "Protocol25GraphError",
        "Protocol25GraphInputsV1",
        "build_protocol_25_graph",
    }
)


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name not in _LAZY_GRAPH_EXPORTS:
        raise AttributeError(name)
    from . import graph

    value = getattr(graph, name)
    globals()[name] = value
    return value
