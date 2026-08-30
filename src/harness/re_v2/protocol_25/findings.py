"""Stable controller-owned audit and finding authority for protocol 2.5."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar
import unicodedata

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.model import ArtifactScope
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    one_of,
    safe_id,
    sorted_unique_digests,
)

from .model import Protocol25SchemaError


FINDING_CLASSES = frozenset(
    {
        "missing_behavior",
        "incorrect_behavior",
        "contradictory_claim",
        "unsupported_claim",
        "evidence_scope_gap",
        "cross_domain_inconsistency",
        "requires_deeper_evidence",
        "requires_human_decision",
    }
)
SUBJECT_KINDS = frozenset(
    {"surface", "operation", "boundary", "claim", "evidence-fact", "source"}
)
TARGET_KINDS = frozenset({"domain", "source"})


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol25SchemaError:
        raise
    except Protocol22SchemaError as exc:
        raise Protocol25SchemaError(str(exc)) from exc


def _safe_ids(
    values: object,
    field: str,
    *,
    nonempty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise Protocol25SchemaError(f"{field} must be an array")
    result = tuple(_schema(safe_id, value, field) for value in values)
    if result != tuple(sorted(set(result))):
        raise Protocol25SchemaError(f"{field} must be sorted and unique")
    if nonempty and not result:
        raise Protocol25SchemaError(f"{field} must be nonempty")
    return result


def _bounded_text(value: object, field: str, maximum_bytes: int) -> str:
    if not isinstance(value, str) or not value:
        raise Protocol25SchemaError(f"{field} must be nonempty normalized text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise Protocol25SchemaError(f"{field} must be normalized UTF-8 text") from exc
    if (
        value.strip() != value
        or "\r" in value
        or "\x00" in value
        or unicodedata.normalize("NFC", value) != value
    ):
        raise Protocol25SchemaError(f"{field} must be normalized text")
    if len(encoded) > maximum_bytes:
        raise Protocol25SchemaError(
            f"{field} must be bounded to {maximum_bytes} UTF-8 bytes"
        )
    return value


@dataclass(frozen=True, slots=True)
class AuditedArtifactAuthorityV1:
    schema_version: int
    artifact_key_id: str
    artifact_hash: str
    dependency_hashes: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact_key_id",
        "artifact_hash",
        "dependency_hashes",
    )

    def __post_init__(self) -> None:
        _schema(
            literal,
            self.schema_version,
            1,
            "AuditedArtifactAuthorityV1.schema_version",
        )
        _schema(
            digest_value,
            self.artifact_key_id,
            "AuditedArtifactAuthorityV1.artifact_key_id",
        )
        _schema(
            digest_value,
            self.artifact_hash,
            "AuditedArtifactAuthorityV1.artifact_hash",
        )
        dependencies = _schema(
            sorted_unique_digests,
            self.dependency_hashes,
            "AuditedArtifactAuthorityV1.dependency_hashes",
        )
        object.__setattr__(self, "dependency_hashes", dependencies)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_key_id": self.artifact_key_id,
            "artifact_hash": self.artifact_hash,
            "dependency_hashes": list(self.dependency_hashes),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "AuditedArtifactAuthorityV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class AuditTargetV1:
    schema_version: int
    target_kind: str
    scope: ArtifactScope
    audited_artifacts: tuple[AuditedArtifactAuthorityV1, ...]
    lower_dependency_hashes: tuple[str, ...]
    context_object_hashes: tuple[str, ...]
    evidence_object_hashes: tuple[str, ...]
    audit_policy_hash: str
    auditor_authority_hash: str
    response_schema_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "target_kind",
        "scope",
        "audited_artifacts",
        "lower_dependency_hashes",
        "context_object_hashes",
        "evidence_object_hashes",
        "audit_policy_hash",
        "auditor_authority_hash",
        "response_schema_hash",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "AuditTargetV1.schema_version")
        kind = _schema(one_of, self.target_kind, TARGET_KINDS, "AuditTargetV1.target_kind")
        if not isinstance(self.scope, ArtifactScope) or self.scope.content_id is None:
            raise Protocol25SchemaError(
                "AuditTargetV1.scope must be a content-bound ArtifactScope"
            )
        if kind == "domain" and self.scope.domain_key is None:
            raise Protocol25SchemaError("domain target requires a domain scope")
        if kind == "source" and self.scope.domain_key is not None:
            raise Protocol25SchemaError("source target requires a source scope")
        if not isinstance(self.audited_artifacts, (list, tuple)) or any(
            not isinstance(item, AuditedArtifactAuthorityV1)
            for item in self.audited_artifacts
        ):
            raise Protocol25SchemaError(
                "AuditTargetV1.audited_artifacts must contain audited artifact authority"
            )
        artifacts = tuple(self.audited_artifacts)
        keys = tuple(item.artifact_key_id for item in artifacts)
        if not artifacts or keys != tuple(sorted(set(keys))):
            raise Protocol25SchemaError(
                "AuditTargetV1.audited_artifacts must be nonempty, sorted and unique"
            )
        for field in (
            "lower_dependency_hashes",
            "context_object_hashes",
            "evidence_object_hashes",
        ):
            values = _schema(
                sorted_unique_digests,
                getattr(self, field),
                f"AuditTargetV1.{field}",
            )
            if not values:
                raise Protocol25SchemaError(f"AuditTargetV1.{field} must be nonempty")
            object.__setattr__(self, field, values)
        for field in (
            "audit_policy_hash",
            "auditor_authority_hash",
            "response_schema_hash",
        ):
            _schema(digest_value, getattr(self, field), f"AuditTargetV1.{field}")
        object.__setattr__(self, "audited_artifacts", artifacts)

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
            "audited_artifacts": [item.to_json_dict() for item in self.audited_artifacts],
            "lower_dependency_hashes": list(self.lower_dependency_hashes),
            "context_object_hashes": list(self.context_object_hashes),
            "evidence_object_hashes": list(self.evidence_object_hashes),
            "audit_policy_hash": self.audit_policy_hash,
            "auditor_authority_hash": self.auditor_authority_hash,
            "response_schema_hash": self.response_schema_hash,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "AuditTargetV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        artifacts = raw["audited_artifacts"]
        if not isinstance(artifacts, (list, tuple)):
            raise Protocol25SchemaError("AuditTargetV1.audited_artifacts must be an array")
        try:
            return cls(
                schema_version=raw["schema_version"],
                target_kind=raw["target_kind"],
                scope=ArtifactScope.from_json_dict(raw["scope"]),
                audited_artifacts=tuple(
                    AuditedArtifactAuthorityV1.from_json_dict(item)
                    for item in artifacts
                ),
                lower_dependency_hashes=raw["lower_dependency_hashes"],
                context_object_hashes=raw["context_object_hashes"],
                evidence_object_hashes=raw["evidence_object_hashes"],
                audit_policy_hash=raw["audit_policy_hash"],
                auditor_authority_hash=raw["auditor_authority_hash"],
                response_schema_hash=raw["response_schema_hash"],
            )
        except Protocol25SchemaError:
            raise
        except Protocol22SchemaError as exc:
            raise Protocol25SchemaError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class EvidenceAnchorAuthorityV1:
    schema_version: int
    anchor_id: str
    aliases: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = ("schema_version", "anchor_id", "aliases")

    def __post_init__(self) -> None:
        _schema(
            literal,
            self.schema_version,
            1,
            "EvidenceAnchorAuthorityV1.schema_version",
        )
        _schema(safe_id, self.anchor_id, "EvidenceAnchorAuthorityV1.anchor_id")
        aliases = _safe_ids(
            self.aliases,
            "EvidenceAnchorAuthorityV1.aliases",
            nonempty=True,
        )
        if self.anchor_id in aliases:
            raise Protocol25SchemaError(
                "EvidenceAnchorAuthorityV1 aliases must not repeat anchor_id"
            )
        object.__setattr__(self, "aliases", aliases)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "anchor_id": self.anchor_id,
            "aliases": list(self.aliases),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "EvidenceAnchorAuthorityV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class FindingAuthorityVocabularyV1:
    schema_version: int
    audit_target_id: str
    rule_ids: tuple[str, ...]
    subject_refs: tuple[str, ...]
    claim_anchor_ids: tuple[str, ...]
    evidence_anchors: tuple[EvidenceAnchorAuthorityV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "audit_target_id",
        "rule_ids",
        "subject_refs",
        "claim_anchor_ids",
        "evidence_anchors",
    )

    def __post_init__(self) -> None:
        _schema(
            literal,
            self.schema_version,
            1,
            "FindingAuthorityVocabularyV1.schema_version",
        )
        _schema(
            digest_value,
            self.audit_target_id,
            "FindingAuthorityVocabularyV1.audit_target_id",
        )
        for field in ("rule_ids", "subject_refs"):
            object.__setattr__(
                self,
                field,
                _safe_ids(
                    getattr(self, field),
                    f"FindingAuthorityVocabularyV1.{field}",
                    nonempty=True,
                ),
            )
        object.__setattr__(
            self,
            "claim_anchor_ids",
            _safe_ids(
                self.claim_anchor_ids,
                "FindingAuthorityVocabularyV1.claim_anchor_ids",
            ),
        )
        if not isinstance(self.evidence_anchors, (list, tuple)) or any(
            not isinstance(item, EvidenceAnchorAuthorityV1)
            for item in self.evidence_anchors
        ):
            raise Protocol25SchemaError(
                "FindingAuthorityVocabularyV1.evidence_anchors must contain evidence authority"
            )
        evidence = tuple(self.evidence_anchors)
        keys = tuple(item.anchor_id for item in evidence)
        if not evidence or keys != tuple(sorted(set(keys))):
            raise Protocol25SchemaError(
                "FindingAuthorityVocabularyV1.evidence_anchors must be nonempty, sorted and unique"
            )
        names = [name for item in evidence for name in (item.anchor_id, *item.aliases)]
        if len(names) != len(set(names)):
            raise Protocol25SchemaError(
                "FindingAuthorityVocabularyV1 evidence IDs and aliases must be unique"
            )
        object.__setattr__(self, "evidence_anchors", evidence)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def canonical_evidence_anchor(self, reference: str) -> str:
        _schema(safe_id, reference, "evidence reference")
        for authority in self.evidence_anchors:
            if reference == authority.anchor_id or reference in authority.aliases:
                return authority.anchor_id
        raise Protocol25SchemaError(
            f"evidence reference {reference!r} is not controller-issued"
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "audit_target_id": self.audit_target_id,
            "rule_ids": list(self.rule_ids),
            "subject_refs": list(self.subject_refs),
            "claim_anchor_ids": list(self.claim_anchor_ids),
            "evidence_anchors": [item.to_json_dict() for item in self.evidence_anchors],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "FindingAuthorityVocabularyV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        evidence = raw["evidence_anchors"]
        if not isinstance(evidence, (list, tuple)):
            raise Protocol25SchemaError(
                "FindingAuthorityVocabularyV1.evidence_anchors must be an array"
            )
        return cls(
            schema_version=raw["schema_version"],
            audit_target_id=raw["audit_target_id"],
            rule_ids=raw["rule_ids"],
            subject_refs=raw["subject_refs"],
            claim_anchor_ids=raw["claim_anchor_ids"],
            evidence_anchors=tuple(
                EvidenceAnchorAuthorityV1.from_json_dict(item) for item in evidence
            ),
        )


@dataclass(frozen=True, slots=True)
class FindingKeyV1:
    schema_version: int
    audit_target_id: str
    authority_vocabulary_id: str
    rule_id: str
    finding_class: str
    subject_kind: str
    subject_ref: str
    claim_anchor_ids: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
    audited_artifact_hashes: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "audit_target_id",
        "authority_vocabulary_id",
        "rule_id",
        "finding_class",
        "subject_kind",
        "subject_ref",
        "claim_anchor_ids",
        "evidence_anchor_ids",
        "audited_artifact_hashes",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "FindingKeyV1.schema_version")
        for field in ("audit_target_id", "authority_vocabulary_id"):
            _schema(digest_value, getattr(self, field), f"FindingKeyV1.{field}")
        _schema(safe_id, self.rule_id, "FindingKeyV1.rule_id")
        _schema(
            one_of,
            self.finding_class,
            FINDING_CLASSES,
            "FindingKeyV1.finding_class",
        )
        _schema(
            one_of,
            self.subject_kind,
            SUBJECT_KINDS,
            "FindingKeyV1.subject_kind",
        )
        _schema(safe_id, self.subject_ref, "FindingKeyV1.subject_ref")
        object.__setattr__(
            self,
            "claim_anchor_ids",
            _safe_ids(self.claim_anchor_ids, "FindingKeyV1.claim_anchor_ids"),
        )
        object.__setattr__(
            self,
            "evidence_anchor_ids",
            _safe_ids(
                self.evidence_anchor_ids,
                "FindingKeyV1.evidence_anchor_ids",
                nonempty=True,
            ),
        )
        artifacts = _schema(
            sorted_unique_digests,
            self.audited_artifact_hashes,
            "FindingKeyV1.audited_artifact_hashes",
        )
        if not artifacts:
            raise Protocol25SchemaError(
                "FindingKeyV1.audited_artifact_hashes must be nonempty"
            )
        object.__setattr__(self, "audited_artifact_hashes", artifacts)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    @property
    def finding_key_id(self) -> str:
        return self.identity

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "audit_target_id": self.audit_target_id,
            "authority_vocabulary_id": self.authority_vocabulary_id,
            "rule_id": self.rule_id,
            "finding_class": self.finding_class,
            "subject_kind": self.subject_kind,
            "subject_ref": self.subject_ref,
            "claim_anchor_ids": list(self.claim_anchor_ids),
            "evidence_anchor_ids": list(self.evidence_anchor_ids),
            "audited_artifact_hashes": list(self.audited_artifact_hashes),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "FindingKeyV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


def normalize_finding_key(
    *,
    vocabulary: FindingAuthorityVocabularyV1,
    audit_target: AuditTargetV1,
    rule_id: str,
    finding_class: str,
    subject_kind: str,
    subject_ref: str,
    claim_anchor_ids: object,
    evidence_refs: object,
) -> FindingKeyV1:
    if not isinstance(vocabulary, FindingAuthorityVocabularyV1):
        raise Protocol25SchemaError("finding vocabulary authority is invalid")
    if not isinstance(audit_target, AuditTargetV1):
        raise Protocol25SchemaError("audit target authority is invalid")
    if vocabulary.audit_target_id != audit_target.identity:
        raise Protocol25SchemaError(
            "finding vocabulary does not bind the audit target"
        )
    _schema(safe_id, rule_id, "finding rule_id")
    if rule_id not in vocabulary.rule_ids:
        raise Protocol25SchemaError(f"rule_id {rule_id!r} is not controller-issued")
    _schema(safe_id, subject_ref, "finding subject_ref")
    if subject_ref not in vocabulary.subject_refs:
        raise Protocol25SchemaError(
            f"subject_ref {subject_ref!r} is not controller-issued"
        )
    _schema(one_of, subject_kind, SUBJECT_KINDS, "finding subject_kind")
    if subject_ref.partition(":")[0] != subject_kind:
        raise Protocol25SchemaError(
            "finding subject_kind does not match the controller-issued subject_ref"
        )
    if not isinstance(claim_anchor_ids, (list, tuple)):
        raise Protocol25SchemaError("claim_anchor_ids must be an array")
    provider_claims = tuple(
        _schema(safe_id, item, "finding claim_anchor_ids")
        for item in claim_anchor_ids
    )
    if len(provider_claims) != len(set(provider_claims)):
        raise Protocol25SchemaError("finding claim_anchor_ids contain a duplicate")
    normalized_claims = tuple(sorted(provider_claims))
    if any(item not in vocabulary.claim_anchor_ids for item in normalized_claims):
        raise Protocol25SchemaError("claim anchor is not controller-issued")
    if not isinstance(evidence_refs, (list, tuple)) or not evidence_refs:
        raise Protocol25SchemaError("evidence_refs must be a nonempty array")
    normalized_evidence = tuple(
        sorted(
            {
                vocabulary.canonical_evidence_anchor(item)
                for item in evidence_refs
                if isinstance(item, str)
            }
        )
    )
    if len(normalized_evidence) == 0 or any(
        not isinstance(item, str) for item in evidence_refs
    ):
        raise Protocol25SchemaError("evidence reference is not controller-issued")
    return FindingKeyV1(
        schema_version=1,
        audit_target_id=audit_target.identity,
        authority_vocabulary_id=vocabulary.identity,
        rule_id=rule_id,
        finding_class=finding_class,
        subject_kind=subject_kind,
        subject_ref=subject_ref,
        claim_anchor_ids=normalized_claims,
        evidence_anchor_ids=normalized_evidence,
        audited_artifact_hashes=tuple(
            sorted(item.artifact_hash for item in audit_target.audited_artifacts)
        ),
    )


@dataclass(frozen=True, slots=True)
class SemanticFindingV1:
    schema_version: int
    finding_key: FindingKeyV1
    title: str
    explanation: str
    recommendation: str
    repair_context: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "finding_key",
        "title",
        "explanation",
        "recommendation",
        "repair_context",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "SemanticFindingV1.schema_version")
        if not isinstance(self.finding_key, FindingKeyV1):
            raise Protocol25SchemaError(
                "SemanticFindingV1.finding_key must be FindingKeyV1"
            )
        _bounded_text(self.title, "SemanticFindingV1.title", 256)
        for field in ("explanation", "recommendation", "repair_context"):
            _bounded_text(
                getattr(self, field),
                f"SemanticFindingV1.{field}",
                4096,
            )

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    @property
    def finding_key_id(self) -> str:
        return self.finding_key.identity

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "finding_key": self.finding_key.to_json_dict(),
            "title": self.title,
            "explanation": self.explanation,
            "recommendation": self.recommendation,
            "repair_context": self.repair_context,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SemanticFindingV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            schema_version=raw["schema_version"],
            finding_key=FindingKeyV1.from_json_dict(raw["finding_key"]),
            title=raw["title"],
            explanation=raw["explanation"],
            recommendation=raw["recommendation"],
            repair_context=raw["repair_context"],
        )


@dataclass(frozen=True, slots=True)
class DeferredObservationV1:
    schema_version: int
    audit_target_id: str
    authority_vocabulary_id: str
    rule_id: str
    finding_class: str
    subject_kind: str
    subject_ref: str
    claim_anchor_ids: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
    audited_artifact_hashes: tuple[str, ...]
    diagnostic: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "audit_target_id",
        "authority_vocabulary_id",
        "rule_id",
        "finding_class",
        "subject_kind",
        "subject_ref",
        "claim_anchor_ids",
        "evidence_anchor_ids",
        "audited_artifact_hashes",
        "diagnostic",
    )

    def __post_init__(self) -> None:
        normalized_key = FindingKeyV1(
            schema_version=self.schema_version,
            audit_target_id=self.audit_target_id,
            authority_vocabulary_id=self.authority_vocabulary_id,
            rule_id=self.rule_id,
            finding_class=self.finding_class,
            subject_kind=self.subject_kind,
            subject_ref=self.subject_ref,
            claim_anchor_ids=self.claim_anchor_ids,
            evidence_anchor_ids=self.evidence_anchor_ids,
            audited_artifact_hashes=self.audited_artifact_hashes,
        )
        for field in (
            "claim_anchor_ids",
            "evidence_anchor_ids",
            "audited_artifact_hashes",
        ):
            object.__setattr__(self, field, getattr(normalized_key, field))
        _bounded_text(self.diagnostic, "DeferredObservationV1.diagnostic", 4096)

    @property
    def observation_id(self) -> str:
        structured = self.to_json_dict()
        del structured["diagnostic"]
        return content_digest(structured)

    @property
    def identity(self) -> str:
        return self.observation_id

    @property
    def payload_hash(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "audit_target_id": self.audit_target_id,
            "authority_vocabulary_id": self.authority_vocabulary_id,
            "rule_id": self.rule_id,
            "finding_class": self.finding_class,
            "subject_kind": self.subject_kind,
            "subject_ref": self.subject_ref,
            "claim_anchor_ids": list(self.claim_anchor_ids),
            "evidence_anchor_ids": list(self.evidence_anchor_ids),
            "audited_artifact_hashes": list(self.audited_artifact_hashes),
            "diagnostic": self.diagnostic,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "DeferredObservationV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


__all__ = (
    "AuditTargetV1",
    "AuditedArtifactAuthorityV1",
    "DeferredObservationV1",
    "EvidenceAnchorAuthorityV1",
    "FINDING_CLASSES",
    "FindingAuthorityVocabularyV1",
    "FindingKeyV1",
    "SemanticFindingV1",
    "SUBJECT_KINDS",
    "normalize_finding_key",
)
