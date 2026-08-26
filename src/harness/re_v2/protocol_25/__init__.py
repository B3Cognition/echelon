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
    "AuthorizedEvidenceRangeV1",
    "BoundedAuthorityObjectV1",
    "AuditedArtifactAuthorityV1",
    "DeferredObservationV1",
    "ComposedSemanticViewV1",
    "EvidenceAnchorAuthorityV1",
    "FINDING_CLASSES",
    "FindingAuthorityVocabularyV1",
    "FindingAssessmentV1",
    "FindingClosureReceiptV1",
    "FindingKeyV1",
    "L3SourceRootV1",
    "ParentAuthorityBundleV2",
    "ParentSemanticAuthorityV1",
    "PROTOCOL_25_EVENTS",
    "Protocol25InputSet",
    "Protocol25InputStoreError",
    "Protocol25Controller",
    "Protocol25ControllerActionV1",
    "Protocol25ControllerBackend",
    "Protocol25ControllerError",
    "Protocol25ControllerResult",
    "Protocol25ControllerStateV1",
    "Protocol25Ledger",
    "Protocol25LedgerProtocol",
    "Protocol25LedgerView",
    "Protocol25ReplayState",
    "Protocol25RecoveryError",
    "Protocol25RecoveryResult",
    "Protocol25RunContext",
    "Protocol25DeterministicRuntime",
    "Protocol25RuntimeError",
    "Protocol25SchemaError",
    "Protocol25Graph",
    "Protocol25GraphError",
    "Protocol25GraphInputsV1",
    "Protocol25AdoptionError",
    "Protocol25ParentCandidateV1",
    "RunManifestV4",
    "RunModeV1",
    "ResolutionEntryV1",
    "SUBJECT_KINDS",
    "SemanticFindingV1",
    "SemanticCandidateInputV1",
    "SemanticCertificationResultV1",
    "SemanticContextV1",
    "SemanticCertificationReceiptV1",
    "SemanticArtifactPolicyCatalogV1",
    "SemanticArtifactPolicyEntryV1",
    "SemanticBudgetDecisionV1",
    "SemanticClosurePolicyV1",
    "SemanticResolutionOverlayV1",
    "SemanticExecutorAuthorityV1",
    "SemanticExecutorContractCatalogV1",
    "SemanticRequestRendererAuthorityV1",
    "SemanticResponseSchemaReferenceV1",
    "SourceCompositionAssessmentV1",
    "TargetClosureAssessmentV1",
    "TargetProgressReplayV1",
    "SemanticSourceCycleStateV1",
    "SemanticTargetControllerStateV1",
    "build_finding_closure_receipt",
    "build_parent_authority_bundle_v2",
    "build_protocol_25_graph",
    "build_semantic_resolution_overlay",
    "build_source_composition_assessment",
    "build_semantic_executor_catalog",
    "build_semantic_v1_policy_catalog",
    "evaluate_semantic_budget",
    "initial_semantic_pool_reservation",
    "normalize_finding_key",
    "plan_next_protocol_25",
    "publish_audit_epoch",
    "semantic_response_schema",
    "import_protocol_25_parent_closure",
    "create_protocol_25_run_store",
    "load_protocol_25_inputs",
    "replay_target_progress",
    "recover_protocol_25_run",
    "validate_protocol_25_parent",
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
_LAZY_ADOPTION_EXPORTS = frozenset(
    {
        "ParentAuthorityBundleV2",
        "ParentSemanticAuthorityV1",
        "Protocol25AdoptionError",
        "Protocol25ParentCandidateV1",
        "build_parent_authority_bundle_v2",
        "import_protocol_25_parent_closure",
        "validate_protocol_25_parent",
    }
)
_LAZY_INPUT_EXPORTS = frozenset(
    {
        "Protocol25InputSet",
        "Protocol25InputStoreError",
        "create_protocol_25_run_store",
        "load_protocol_25_inputs",
    }
)
_LAZY_LEDGER_EXPORTS = frozenset(
    {
        "Protocol25Ledger",
        "Protocol25LedgerProtocol",
        "Protocol25LedgerView",
    }
)
_LAZY_EVENT_EXPORTS = frozenset(
    {
        "PROTOCOL_25_EVENTS",
        "Protocol25ReplayState",
    }
)
_LAZY_BUDGET_EXPORTS = frozenset(
    {
        "SemanticBudgetDecisionV1",
        "TargetProgressReplayV1",
        "evaluate_semantic_budget",
        "initial_semantic_pool_reservation",
        "replay_target_progress",
    }
)
_LAZY_RUNTIME_EXPORTS = frozenset(
    {
        "AuthorizedEvidenceRangeV1",
        "BoundedAuthorityObjectV1",
        "ComposedSemanticViewV1",
        "Protocol25DeterministicRuntime",
        "Protocol25RuntimeError",
        "SemanticCandidateInputV1",
        "SemanticCertificationResultV1",
        "SemanticContextV1",
        "semantic_response_schema",
    }
)
_LAZY_CONTROLLER_EXPORTS = frozenset(
    {
        "Protocol25Controller",
        "Protocol25ControllerActionV1",
        "Protocol25ControllerBackend",
        "Protocol25ControllerError",
        "Protocol25ControllerResult",
        "Protocol25ControllerStateV1",
        "SemanticSourceCycleStateV1",
        "SemanticTargetControllerStateV1",
        "plan_next_protocol_25",
    }
)
_LAZY_RECOVERY_EXPORTS = frozenset(
    {
        "Protocol25RecoveryError",
        "Protocol25RecoveryResult",
        "Protocol25RunContext",
        "publish_audit_epoch",
        "recover_protocol_25_run",
    }
)


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name in _LAZY_GRAPH_EXPORTS:
        from . import graph as module
    elif name in _LAZY_ADOPTION_EXPORTS:
        from . import adoption as module
    elif name in _LAZY_INPUT_EXPORTS:
        from . import inputs as module
    elif name in _LAZY_LEDGER_EXPORTS:
        from . import ledger as module
    elif name in _LAZY_EVENT_EXPORTS:
        from . import events as module
    elif name in _LAZY_BUDGET_EXPORTS:
        from . import budget as module
    elif name in _LAZY_RUNTIME_EXPORTS:
        from . import runtime as module
    elif name in _LAZY_CONTROLLER_EXPORTS:
        from . import controller as module
    elif name in _LAZY_RECOVERY_EXPORTS:
        from . import recovery as module
    else:
        raise AttributeError(name)
    value = getattr(module, name)
    globals()[name] = value
    return value
