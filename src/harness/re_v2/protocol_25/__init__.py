"""Closed protocol-2.5 contracts for RE v2 L3 semantic closure."""

PROTOCOL_VERSION = "2.5"
RUN_MANIFEST_SCHEMA_VERSION = 4

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

__all__ = (
    "PROTOCOL_VERSION",
    "RUN_MANIFEST_SCHEMA_VERSION",
    "AuditTargetV1",
    "AuditedArtifactAuthorityV1",
    "DeferredObservationV1",
    "EvidenceAnchorAuthorityV1",
    "FINDING_CLASSES",
    "FindingAuthorityVocabularyV1",
    "FindingKeyV1",
    "Protocol25SchemaError",
    "RunManifestV4",
    "RunModeV1",
    "SUBJECT_KINDS",
    "SemanticFindingV1",
    "SemanticClosurePolicyV1",
    "normalize_finding_key",
)
