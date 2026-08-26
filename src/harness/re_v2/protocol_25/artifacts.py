"""Immutable L3 audit, resolution, assessment, receipt, and root authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.model import ArtifactKeyV2
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    nonnegative_int,
    one_of,
    optional_digest,
    positive_int,
    safe_id,
    sorted_unique_digests,
)

from .findings import AuditTargetV1, DeferredObservationV1, SemanticFindingV1
from .model import Protocol25SchemaError
from .policies import SEMANTIC_PRODUCER_PROTOCOL_BY_ARTIFACT


_AUDIT_VERDICTS = frozenset({"PASS", "REPAIR"})
_RESOLUTION_DISPOSITIONS = frozenset(
    {"resolved", "qualified", "deferred", "human_decision"}
)
_ASSESSMENT_VERDICTS = frozenset({"closed", "open"})
_SOURCE_OUTCOMES = frozenset({"passed", "failed"})
_ROOT_STATES = frozenset({"complete", "next_epoch_required", "blocked"})


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol25SchemaError:
        raise
    except Protocol22SchemaError as exc:
        raise Protocol25SchemaError(str(exc)) from exc


def _identity(value: object) -> str:
    return content_digest(value.to_json_dict())  # type: ignore[attr-defined]


def _digests(
    values: object,
    field: str,
    *,
    nonempty: bool = False,
) -> tuple[str, ...]:
    result = _schema(sorted_unique_digests, values, field)
    if nonempty and not result:
        raise Protocol25SchemaError(f"{field} must be nonempty")
    return result


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


def _text(value: object, field: str, maximum_bytes: int = 4096) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise Protocol25SchemaError(f"{field} must be nonempty normalized text")
    if "\r" in value or "\x00" in value or len(value.encode("utf-8")) > maximum_bytes:
        raise Protocol25SchemaError(f"{field} must be bounded normalized text")
    return value


def _decode_tuple(value: object, field: str, decoder):  # type: ignore[no-untyped-def]
    if not isinstance(value, (list, tuple)):
        raise Protocol25SchemaError(f"{field} must be an array")
    return tuple(decoder(item) for item in value)


class _Authority:
    __slots__ = ()

    @property
    def identity(self) -> str:
        return _identity(self)


@dataclass(frozen=True, slots=True)
class AuditCandidateV1(_Authority):
    schema_version: int
    audit_target: AuditTargetV1
    artifact_key: ArtifactKeyV2
    audit_epoch_id: None
    verdict: str
    findings: tuple[SemanticFindingV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "audit_target",
        "artifact_key",
        "audit_epoch_id",
        "verdict",
        "findings",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "AuditCandidateV1.schema_version")
        if not isinstance(self.audit_target, AuditTargetV1):
            raise Protocol25SchemaError("AuditCandidateV1 audit target is invalid")
        if not isinstance(self.artifact_key, ArtifactKeyV2):
            raise Protocol25SchemaError("AuditCandidateV1 artifact key is invalid")
        if self.audit_epoch_id is not None:
            raise Protocol25SchemaError("audit candidate requires a null epoch reference")
        if (
            self.artifact_key.artifact_kind != "semantic-audit-findings"
            or self.artifact_key.layer != "L3"
            or self.artifact_key.producer_protocol_version
            != SEMANTIC_PRODUCER_PROTOCOL_BY_ARTIFACT["semantic-audit-findings"]
            or self.artifact_key.scope != self.audit_target.scope
        ):
            raise Protocol25SchemaError("audit candidate artifact key is invalid")
        if self.artifact_key.dependency_hashes != (self.audit_target.identity,):
            raise Protocol25SchemaError(
                "audit candidate dependency authority does not equal its target"
            )
        _schema(one_of, self.verdict, _AUDIT_VERDICTS, "AuditCandidateV1.verdict")
        if not isinstance(self.findings, (list, tuple)) or any(
            not isinstance(item, SemanticFindingV1) for item in self.findings
        ):
            raise Protocol25SchemaError("AuditCandidateV1 findings are invalid")
        findings = tuple(self.findings)
        keys = tuple(item.finding_key_id for item in findings)
        if keys != tuple(sorted(set(keys))):
            raise Protocol25SchemaError(
                "AuditCandidateV1 findings must be sorted and unique"
            )
        if any(
            item.finding_key.audit_target_id != self.audit_target.identity
            for item in findings
        ):
            raise Protocol25SchemaError("audit finding is outside its audit target")
        if (self.verdict == "PASS") != (not findings):
            raise Protocol25SchemaError("audit candidate verdict disagrees with findings")
        object.__setattr__(self, "findings", findings)

    @property
    def audit_target_id(self) -> str:
        return self.audit_target.identity

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "audit_target": self.audit_target.to_json_dict(),
            "artifact_key": self.artifact_key.to_json_dict(),
            "audit_epoch_id": self.audit_epoch_id,
            "verdict": self.verdict,
            "findings": [item.to_json_dict() for item in self.findings],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "AuditCandidateV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            schema_version=raw["schema_version"],
            audit_target=AuditTargetV1.from_json_dict(raw["audit_target"]),
            artifact_key=ArtifactKeyV2.from_json_dict(raw["artifact_key"]),
            audit_epoch_id=raw["audit_epoch_id"],
            verdict=raw["verdict"],
            findings=_decode_tuple(
                raw["findings"], cls.__name__ + ".findings", SemanticFindingV1.from_json_dict
            ),
        )


@dataclass(frozen=True, slots=True)
class AuditTargetCandidateAuthorityV1(_Authority):
    schema_version: int
    audit_target_id: str
    candidate_hash: str
    certification_receipt_id: str
    acceptance_receipt_id: str
    finding_key_ids: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "audit_target_id",
        "candidate_hash",
        "certification_receipt_id",
        "acceptance_receipt_id",
        "finding_key_ids",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "audit target candidate schema_version")
        for field in self.FIELDS[1:5]:
            _schema(digest_value, getattr(self, field), f"AuditTargetCandidateAuthorityV1.{field}")
        object.__setattr__(
            self,
            "finding_key_ids",
            _digests(
                self.finding_key_ids,
                "AuditTargetCandidateAuthorityV1.finding_key_ids",
            ),
        )

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        result["finding_key_ids"] = list(self.finding_key_ids)
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "AuditTargetCandidateAuthorityV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class AuditEpochV1(_Authority):
    schema_version: int
    selection_id: str
    audit_policy_hash: str
    target_candidate_authorities: tuple[AuditTargetCandidateAuthorityV1, ...]
    auditor_authority_hash: str
    executor_authority_hash: str
    verifier_authority_hash: str
    finding_key_ids: tuple[str, ...]
    audited_l2_root_hashes: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "selection_id",
        "audit_policy_hash",
        "target_candidate_authorities",
        "auditor_authority_hash",
        "executor_authority_hash",
        "verifier_authority_hash",
        "finding_key_ids",
        "audited_l2_root_hashes",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "AuditEpochV1.schema_version")
        for field in (
            "selection_id",
            "audit_policy_hash",
            "auditor_authority_hash",
            "executor_authority_hash",
            "verifier_authority_hash",
        ):
            _schema(digest_value, getattr(self, field), f"AuditEpochV1.{field}")
        if not isinstance(self.target_candidate_authorities, (list, tuple)) or any(
            not isinstance(item, AuditTargetCandidateAuthorityV1)
            for item in self.target_candidate_authorities
        ):
            raise Protocol25SchemaError("AuditEpochV1 target authority is invalid")
        targets = tuple(self.target_candidate_authorities)
        target_ids = tuple(item.audit_target_id for item in targets)
        if not targets or target_ids != tuple(sorted(set(target_ids))):
            raise Protocol25SchemaError(
                "AuditEpochV1 target authorities must be nonempty, sorted and unique"
            )
        object.__setattr__(self, "target_candidate_authorities", targets)
        object.__setattr__(
            self,
            "finding_key_ids",
            _digests(self.finding_key_ids, "AuditEpochV1.finding_key_ids"),
        )
        candidate_findings = tuple(
            sorted(
                finding_id
                for authority in targets
                for finding_id in authority.finding_key_ids
            )
        )
        if len(candidate_findings) != len(set(candidate_findings)):
            raise Protocol25SchemaError(
                "AuditEpochV1 candidate authorities repeat a finding"
            )
        if self.finding_key_ids != candidate_findings:
            raise Protocol25SchemaError(
                "AuditEpochV1 finding set does not equal candidate authority"
            )
        object.__setattr__(
            self,
            "audited_l2_root_hashes",
            _digests(
                self.audited_l2_root_hashes,
                "AuditEpochV1.audited_l2_root_hashes",
                nonempty=True,
            ),
        )

    @property
    def audit_target_ids(self) -> tuple[str, ...]:
        return tuple(item.audit_target_id for item in self.target_candidate_authorities)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "selection_id": self.selection_id,
            "audit_policy_hash": self.audit_policy_hash,
            "target_candidate_authorities": [
                item.to_json_dict() for item in self.target_candidate_authorities
            ],
            "auditor_authority_hash": self.auditor_authority_hash,
            "executor_authority_hash": self.executor_authority_hash,
            "verifier_authority_hash": self.verifier_authority_hash,
            "finding_key_ids": list(self.finding_key_ids),
            "audited_l2_root_hashes": list(self.audited_l2_root_hashes),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "AuditEpochV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            schema_version=raw["schema_version"],
            selection_id=raw["selection_id"],
            audit_policy_hash=raw["audit_policy_hash"],
            target_candidate_authorities=_decode_tuple(
                raw["target_candidate_authorities"],
                cls.__name__ + ".target_candidate_authorities",
                AuditTargetCandidateAuthorityV1.from_json_dict,
            ),
            auditor_authority_hash=raw["auditor_authority_hash"],
            executor_authority_hash=raw["executor_authority_hash"],
            verifier_authority_hash=raw["verifier_authority_hash"],
            finding_key_ids=raw["finding_key_ids"],
            audited_l2_root_hashes=raw["audited_l2_root_hashes"],
        )


@dataclass(frozen=True, slots=True)
class ResolutionEntryV1(_Authority):
    schema_version: int
    finding_key_ids: tuple[str, ...]
    disposition: str
    semantic_claims: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
    supersedes_claim_anchor_ids: tuple[str, ...]
    refines_subject_refs: tuple[str, ...]
    unresolved: bool

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "finding_key_ids",
        "disposition",
        "semantic_claims",
        "evidence_anchor_ids",
        "supersedes_claim_anchor_ids",
        "refines_subject_refs",
        "unresolved",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "ResolutionEntryV1.schema_version")
        object.__setattr__(
            self,
            "finding_key_ids",
            _digests(
                self.finding_key_ids,
                "ResolutionEntryV1.finding_key_ids",
                nonempty=True,
            ),
        )
        _schema(one_of, self.disposition, _RESOLUTION_DISPOSITIONS, "resolution disposition")
        if not isinstance(self.semantic_claims, (list, tuple)):
            raise Protocol25SchemaError("resolution semantic claims must be an array")
        claims = tuple(
            _text(item, "ResolutionEntryV1.semantic_claims", 4096)
            for item in self.semantic_claims
        )
        if claims != tuple(sorted(set(claims))) or not claims:
            raise Protocol25SchemaError(
                "resolution semantic claims must be nonempty, sorted and unique"
            )
        object.__setattr__(self, "semantic_claims", claims)
        object.__setattr__(
            self,
            "evidence_anchor_ids",
            _safe_ids(
                self.evidence_anchor_ids,
                "ResolutionEntryV1.evidence_anchor_ids",
                nonempty=True,
            ),
        )
        object.__setattr__(
            self,
            "supersedes_claim_anchor_ids",
            _safe_ids(
                self.supersedes_claim_anchor_ids,
                "ResolutionEntryV1.supersedes_claim_anchor_ids",
            ),
        )
        object.__setattr__(
            self,
            "refines_subject_refs",
            _safe_ids(
                self.refines_subject_refs,
                "ResolutionEntryV1.refines_subject_refs",
            ),
        )
        if not isinstance(self.unresolved, bool):
            raise Protocol25SchemaError("resolution unresolved must be boolean")
        if self.disposition == "resolved":
            if self.unresolved:
                raise Protocol25SchemaError("resolved disposition cannot remain unresolved")
        elif self.disposition in {"deferred", "human_decision"} and not self.unresolved:
            raise Protocol25SchemaError(
                "deferred disposition must preserve honest unresolved state"
            )
        if not self.supersedes_claim_anchor_ids and not self.refines_subject_refs:
            raise Protocol25SchemaError(
                "resolution requires an explicit supersession or refinement reference"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "finding_key_ids": list(self.finding_key_ids),
            "disposition": self.disposition,
            "semantic_claims": list(self.semantic_claims),
            "evidence_anchor_ids": list(self.evidence_anchor_ids),
            "supersedes_claim_anchor_ids": list(self.supersedes_claim_anchor_ids),
            "refines_subject_refs": list(self.refines_subject_refs),
            "unresolved": self.unresolved,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ResolutionEntryV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SemanticResolutionOverlayV1(_Authority):
    schema_version: int
    artifact_key: ArtifactKeyV2
    audit_epoch_id: str
    audit_target_id: str
    semantic_round: int
    prior_overlay_hashes: tuple[str, ...]
    guidance_hash: str | None
    entries: tuple[ResolutionEntryV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact_key",
        "audit_epoch_id",
        "audit_target_id",
        "semantic_round",
        "prior_overlay_hashes",
        "guidance_hash",
        "entries",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "SemanticResolutionOverlayV1.schema_version")
        if not isinstance(self.artifact_key, ArtifactKeyV2):
            raise Protocol25SchemaError("semantic resolution artifact key is invalid")
        if (
            self.artifact_key.artifact_kind != "semantic-resolution-overlay"
            or self.artifact_key.layer != "L3"
            or self.artifact_key.producer_protocol_version
            != SEMANTIC_PRODUCER_PROTOCOL_BY_ARTIFACT[
                "semantic-resolution-overlay"
            ]
        ):
            raise Protocol25SchemaError("semantic resolution artifact key is invalid")
        _schema(digest_value, self.audit_epoch_id, "semantic resolution audit_epoch_id")
        _schema(digest_value, self.audit_target_id, "semantic resolution audit_target_id")
        _schema(positive_int, self.semantic_round, "semantic resolution round")
        prior = _digests(
            self.prior_overlay_hashes,
            "SemanticResolutionOverlayV1.prior_overlay_hashes",
        )
        if self.semantic_round == 1 and prior:
            raise Protocol25SchemaError("first semantic round cannot have prior overlays")
        if self.semantic_round > 1 and not prior:
            raise Protocol25SchemaError("later semantic round requires prior overlays")
        object.__setattr__(self, "prior_overlay_hashes", prior)
        _schema(optional_digest, self.guidance_hash, "semantic resolution guidance_hash")
        if not isinstance(self.entries, (list, tuple)) or any(
            not isinstance(item, ResolutionEntryV1) for item in self.entries
        ):
            raise Protocol25SchemaError("semantic resolution entries are invalid")
        entries = tuple(self.entries)
        if not entries:
            raise Protocol25SchemaError("semantic resolution entries must be nonempty")
        finding_ids = tuple(
            finding_id for entry in entries for finding_id in entry.finding_key_ids
        )
        if len(finding_ids) != len(set(finding_ids)):
            raise Protocol25SchemaError("semantic resolution repeats a finding")
        if entries != tuple(sorted(entries, key=lambda item: item.finding_key_ids)):
            raise Protocol25SchemaError("semantic resolution entries must be sorted")
        expected_dependencies = tuple(
            sorted(
                (
                    self.audit_epoch_id,
                    self.audit_target_id,
                    *prior,
                    *((self.guidance_hash,) if self.guidance_hash is not None else ()),
                )
            )
        )
        if self.artifact_key.dependency_hashes != expected_dependencies:
            raise Protocol25SchemaError(
                "semantic resolution dependency authority is not exact"
            )
        object.__setattr__(self, "entries", entries)

    @property
    def finding_key_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                finding_id
                for entry in self.entries
                for finding_id in entry.finding_key_ids
            )
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_key": self.artifact_key.to_json_dict(),
            "audit_epoch_id": self.audit_epoch_id,
            "audit_target_id": self.audit_target_id,
            "semantic_round": self.semantic_round,
            "prior_overlay_hashes": list(self.prior_overlay_hashes),
            "guidance_hash": self.guidance_hash,
            "entries": [item.to_json_dict() for item in self.entries],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SemanticResolutionOverlayV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            schema_version=raw["schema_version"],
            artifact_key=ArtifactKeyV2.from_json_dict(raw["artifact_key"]),
            audit_epoch_id=raw["audit_epoch_id"],
            audit_target_id=raw["audit_target_id"],
            semantic_round=raw["semantic_round"],
            prior_overlay_hashes=raw["prior_overlay_hashes"],
            guidance_hash=raw["guidance_hash"],
            entries=_decode_tuple(
                raw["entries"], cls.__name__ + ".entries", ResolutionEntryV1.from_json_dict
            ),
        )


def build_semantic_resolution_overlay(
    *,
    epoch: AuditEpochV1,
    schema_version: int,
    artifact_key: ArtifactKeyV2,
    audit_target_id: str,
    semantic_round: int,
    prior_overlay_hashes: tuple[str, ...],
    guidance_hash: str | None,
    entries: tuple[ResolutionEntryV1, ...],
) -> SemanticResolutionOverlayV1:
    if not isinstance(epoch, AuditEpochV1):
        raise Protocol25SchemaError("semantic resolution requires audit epoch authority")
    if audit_target_id not in epoch.audit_target_ids:
        raise Protocol25SchemaError("semantic resolution target is outside audit epoch")
    finding_ids = {
        finding_id for entry in entries for finding_id in entry.finding_key_ids
    }
    if not finding_ids.issubset(set(epoch.finding_key_ids)):
        raise Protocol25SchemaError("semantic resolution finding is outside audit epoch")
    return SemanticResolutionOverlayV1(
        schema_version=schema_version,
        artifact_key=artifact_key,
        audit_epoch_id=epoch.identity,
        audit_target_id=audit_target_id,
        semantic_round=semantic_round,
        prior_overlay_hashes=prior_overlay_hashes,
        guidance_hash=guidance_hash,
        entries=entries,
    )


@dataclass(frozen=True, slots=True)
class FindingAssessmentV1(_Authority):
    schema_version: int
    finding_key_id: str
    verdict: str
    reason_code: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "finding_key_id",
        "verdict",
        "reason_code",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "FindingAssessmentV1.schema_version")
        _schema(digest_value, self.finding_key_id, "FindingAssessmentV1.finding_key_id")
        _schema(one_of, self.verdict, _ASSESSMENT_VERDICTS, "finding assessment verdict")
        _schema(safe_id, self.reason_code, "finding assessment reason_code")

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "FindingAssessmentV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class TargetClosureAssessmentV1(_Authority):
    schema_version: int
    audit_epoch_id: str
    audit_target_id: str
    assessed_finding_ids: tuple[str, ...]
    verdicts: tuple[FindingAssessmentV1, ...]
    resolution_overlay_hash: str
    verifier_authority_hash: str
    context_authority_hash: str
    deferred_observations: tuple[DeferredObservationV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "audit_epoch_id",
        "audit_target_id",
        "assessed_finding_ids",
        "verdicts",
        "resolution_overlay_hash",
        "verifier_authority_hash",
        "context_authority_hash",
        "deferred_observations",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "TargetClosureAssessmentV1.schema_version")
        for field in (
            "audit_epoch_id",
            "audit_target_id",
            "resolution_overlay_hash",
            "verifier_authority_hash",
            "context_authority_hash",
        ):
            _schema(digest_value, getattr(self, field), f"TargetClosureAssessmentV1.{field}")
        assessed = _digests(
            self.assessed_finding_ids,
            "TargetClosureAssessmentV1.assessed_finding_ids",
            nonempty=True,
        )
        if not isinstance(self.verdicts, (list, tuple)) or any(
            not isinstance(item, FindingAssessmentV1) for item in self.verdicts
        ):
            raise Protocol25SchemaError("target closure verdicts are invalid")
        verdicts = tuple(self.verdicts)
        verdict_ids = tuple(item.finding_key_id for item in verdicts)
        if verdict_ids != assessed:
            raise Protocol25SchemaError(
                "target closure must assess each finding exactly once"
            )
        if not isinstance(self.deferred_observations, (list, tuple)) or any(
            not isinstance(item, DeferredObservationV1)
            for item in self.deferred_observations
        ):
            raise Protocol25SchemaError("target closure deferred observations are invalid")
        deferred = tuple(self.deferred_observations)
        ids = tuple(item.observation_id for item in deferred)
        if ids != tuple(sorted(set(ids))):
            raise Protocol25SchemaError(
                "target closure deferred observations must be sorted and unique"
            )
        object.__setattr__(self, "assessed_finding_ids", assessed)
        object.__setattr__(self, "verdicts", verdicts)
        object.__setattr__(self, "deferred_observations", deferred)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "audit_epoch_id": self.audit_epoch_id,
            "audit_target_id": self.audit_target_id,
            "assessed_finding_ids": list(self.assessed_finding_ids),
            "verdicts": [item.to_json_dict() for item in self.verdicts],
            "resolution_overlay_hash": self.resolution_overlay_hash,
            "verifier_authority_hash": self.verifier_authority_hash,
            "context_authority_hash": self.context_authority_hash,
            "deferred_observations": [
                item.to_json_dict() for item in self.deferred_observations
            ],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "TargetClosureAssessmentV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            schema_version=raw["schema_version"],
            audit_epoch_id=raw["audit_epoch_id"],
            audit_target_id=raw["audit_target_id"],
            assessed_finding_ids=raw["assessed_finding_ids"],
            verdicts=_decode_tuple(
                raw["verdicts"], cls.__name__ + ".verdicts", FindingAssessmentV1.from_json_dict
            ),
            resolution_overlay_hash=raw["resolution_overlay_hash"],
            verifier_authority_hash=raw["verifier_authority_hash"],
            context_authority_hash=raw["context_authority_hash"],
            deferred_observations=_decode_tuple(
                raw["deferred_observations"],
                cls.__name__ + ".deferred_observations",
                DeferredObservationV1.from_json_dict,
            ),
        )


@dataclass(frozen=True, slots=True)
class SourceCompositionAssessmentV1(_Authority):
    schema_version: int
    audit_epoch_id: str
    source_id: str
    overlay_hashes: tuple[str, ...]
    target_assessment_hashes: tuple[str, ...]
    composed_authority_hash: str
    implicated_finding_ids: tuple[str, ...]
    deferred_observations: tuple[DeferredObservationV1, ...]
    outcome: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "audit_epoch_id",
        "source_id",
        "overlay_hashes",
        "target_assessment_hashes",
        "composed_authority_hash",
        "implicated_finding_ids",
        "deferred_observations",
        "outcome",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "SourceCompositionAssessmentV1.schema_version")
        _schema(digest_value, self.audit_epoch_id, "source composition audit_epoch_id")
        _schema(safe_id, self.source_id, "source composition source_id")
        for field in ("overlay_hashes", "target_assessment_hashes"):
            object.__setattr__(
                self,
                field,
                _digests(
                    getattr(self, field),
                    f"SourceCompositionAssessmentV1.{field}",
                    nonempty=True,
                ),
            )
        _schema(digest_value, self.composed_authority_hash, "source composition authority")
        object.__setattr__(
            self,
            "implicated_finding_ids",
            _digests(
                self.implicated_finding_ids,
                "SourceCompositionAssessmentV1.implicated_finding_ids",
            ),
        )
        if not isinstance(self.deferred_observations, (list, tuple)) or any(
            not isinstance(item, DeferredObservationV1)
            for item in self.deferred_observations
        ):
            raise Protocol25SchemaError("source composition deferred observations are invalid")
        deferred = tuple(self.deferred_observations)
        ids = tuple(item.observation_id for item in deferred)
        if ids != tuple(sorted(set(ids))):
            raise Protocol25SchemaError(
                "source composition deferred observations must be sorted and unique"
            )
        object.__setattr__(self, "deferred_observations", deferred)
        _schema(one_of, self.outcome, _SOURCE_OUTCOMES, "source composition outcome")
        if self.outcome == "passed" and (self.implicated_finding_ids or deferred):
            raise Protocol25SchemaError(
                "passing source composition cannot retain findings or deferred observations"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "audit_epoch_id": self.audit_epoch_id,
            "source_id": self.source_id,
            "overlay_hashes": list(self.overlay_hashes),
            "target_assessment_hashes": list(self.target_assessment_hashes),
            "composed_authority_hash": self.composed_authority_hash,
            "implicated_finding_ids": list(self.implicated_finding_ids),
            "deferred_observations": [
                item.to_json_dict() for item in self.deferred_observations
            ],
            "outcome": self.outcome,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SourceCompositionAssessmentV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            schema_version=raw["schema_version"],
            audit_epoch_id=raw["audit_epoch_id"],
            source_id=raw["source_id"],
            overlay_hashes=raw["overlay_hashes"],
            target_assessment_hashes=raw["target_assessment_hashes"],
            composed_authority_hash=raw["composed_authority_hash"],
            implicated_finding_ids=raw["implicated_finding_ids"],
            deferred_observations=_decode_tuple(
                raw["deferred_observations"],
                cls.__name__ + ".deferred_observations",
                DeferredObservationV1.from_json_dict,
            ),
            outcome=raw["outcome"],
        )


def build_source_composition_assessment(
    *,
    epoch: AuditEpochV1,
    schema_version: int,
    source_id: str,
    overlay_hashes: tuple[str, ...],
    target_assessment_hashes: tuple[str, ...],
    composed_authority_hash: str,
    implicated_finding_ids: tuple[str, ...],
    deferred_observations: tuple[DeferredObservationV1, ...],
    outcome: str,
) -> SourceCompositionAssessmentV1:
    if not isinstance(epoch, AuditEpochV1):
        raise Protocol25SchemaError("source composition requires audit epoch authority")
    if not set(implicated_finding_ids).issubset(set(epoch.finding_key_ids)):
        raise Protocol25SchemaError("source composition finding is outside audit epoch")
    return SourceCompositionAssessmentV1(
        schema_version=schema_version,
        audit_epoch_id=epoch.identity,
        source_id=source_id,
        overlay_hashes=overlay_hashes,
        target_assessment_hashes=target_assessment_hashes,
        composed_authority_hash=composed_authority_hash,
        implicated_finding_ids=implicated_finding_ids,
        deferred_observations=deferred_observations,
        outcome=outcome,
    )


@dataclass(frozen=True, slots=True)
class SemanticCertificationReceiptV1(_Authority):
    schema_version: int
    artifact_key_id: str
    artifact_hash: str
    verifier_authority_hash: str
    audit_epoch_id: str | None
    audit_target_id: str
    evidence_scope_hash: str
    verdict: str
    normalized_diagnostics: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact_key_id",
        "artifact_hash",
        "verifier_authority_hash",
        "audit_epoch_id",
        "audit_target_id",
        "evidence_scope_hash",
        "verdict",
        "normalized_diagnostics",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "SemanticCertificationReceiptV1.schema_version")
        for field in (
            "artifact_key_id",
            "artifact_hash",
            "verifier_authority_hash",
            "audit_target_id",
            "evidence_scope_hash",
        ):
            _schema(digest_value, getattr(self, field), f"SemanticCertificationReceiptV1.{field}")
        _schema(optional_digest, self.audit_epoch_id, "semantic certification audit_epoch_id")
        _schema(one_of, self.verdict, frozenset({"accepted", "rejected"}), "semantic certification verdict")
        if not isinstance(self.normalized_diagnostics, (list, tuple)):
            raise Protocol25SchemaError("semantic certification diagnostics must be an array")
        diagnostics = tuple(
            _text(item, "SemanticCertificationReceiptV1.normalized_diagnostics", 1024)
            for item in self.normalized_diagnostics
        )
        if diagnostics != tuple(sorted(set(diagnostics))):
            raise Protocol25SchemaError("semantic certification diagnostics must be sorted and unique")
        if (self.verdict == "accepted") != (not diagnostics):
            raise Protocol25SchemaError("semantic certification verdict disagrees with diagnostics")
        object.__setattr__(self, "normalized_diagnostics", diagnostics)

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        result["normalized_diagnostics"] = list(self.normalized_diagnostics)
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "SemanticCertificationReceiptV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class FindingClosureReceiptV1(_Authority):
    schema_version: int
    audit_epoch_id: str
    finding_key_id: str
    audit_target_id: str
    resolution_overlay_hash: str
    closure_verifier_authority_hash: str
    target_closure_assessment_hash: str
    source_composition_assessment_hash: str
    context_authority_hash: str
    semantic_round: int
    verdict: str
    reason_code: str
    diagnostic: str
    previous_closure_receipt_id: str | None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "audit_epoch_id",
        "finding_key_id",
        "audit_target_id",
        "resolution_overlay_hash",
        "closure_verifier_authority_hash",
        "target_closure_assessment_hash",
        "source_composition_assessment_hash",
        "context_authority_hash",
        "semantic_round",
        "verdict",
        "reason_code",
        "diagnostic",
        "previous_closure_receipt_id",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "FindingClosureReceiptV1.schema_version")
        for field in self.FIELDS[1:9]:
            _schema(digest_value, getattr(self, field), f"FindingClosureReceiptV1.{field}")
        _schema(positive_int, self.semantic_round, "finding closure semantic_round")
        _schema(one_of, self.verdict, _ASSESSMENT_VERDICTS, "finding closure verdict")
        _schema(safe_id, self.reason_code, "finding closure reason_code")
        _text(self.diagnostic, "FindingClosureReceiptV1.diagnostic", 4096)
        _schema(optional_digest, self.previous_closure_receipt_id, "previous closure receipt")
        if self.semantic_round == 1 and self.previous_closure_receipt_id is not None:
            raise Protocol25SchemaError("first closure receipt cannot have previous authority")
        if self.semantic_round > 1 and self.previous_closure_receipt_id is None:
            raise Protocol25SchemaError("later closure receipt requires previous authority")

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "FindingClosureReceiptV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


def build_finding_closure_receipt(
    *,
    epoch: AuditEpochV1,
    target_assessment: TargetClosureAssessmentV1,
    source_assessment: SourceCompositionAssessmentV1,
    schema_version: int,
    finding_key_id: str,
    audit_target_id: str,
    resolution_overlay_hash: str,
    closure_verifier_authority_hash: str,
    context_authority_hash: str,
    semantic_round: int,
    verdict: str,
    reason_code: str,
    diagnostic: str,
    previous_closure_receipt_id: str | None,
) -> FindingClosureReceiptV1:
    if not isinstance(epoch, AuditEpochV1) or finding_key_id not in epoch.finding_key_ids:
        raise Protocol25SchemaError("closure receipt finding is outside audit epoch")
    if (
        target_assessment.audit_epoch_id != epoch.identity
        or target_assessment.audit_target_id != audit_target_id
        or target_assessment.resolution_overlay_hash != resolution_overlay_hash
        or finding_key_id not in target_assessment.assessed_finding_ids
    ):
        raise Protocol25SchemaError("closure receipt target assessment does not bind the finding")
    target_verdict = next(
        item.verdict
        for item in target_assessment.verdicts
        if item.finding_key_id == finding_key_id
    )
    if target_verdict != verdict:
        raise Protocol25SchemaError("closure receipt verdict disagrees with target assessment")
    if (
        source_assessment.audit_epoch_id != epoch.identity
        or source_assessment.outcome != "passed"
        or target_assessment.identity not in source_assessment.target_assessment_hashes
        or resolution_overlay_hash not in source_assessment.overlay_hashes
    ):
        raise Protocol25SchemaError(
            "closure receipt requires a passing source composition assessment"
        )
    return FindingClosureReceiptV1(
        schema_version=schema_version,
        audit_epoch_id=epoch.identity,
        finding_key_id=finding_key_id,
        audit_target_id=audit_target_id,
        resolution_overlay_hash=resolution_overlay_hash,
        closure_verifier_authority_hash=closure_verifier_authority_hash,
        target_closure_assessment_hash=target_assessment.identity,
        source_composition_assessment_hash=source_assessment.identity,
        context_authority_hash=context_authority_hash,
        semantic_round=semantic_round,
        verdict=verdict,
        reason_code=reason_code,
        diagnostic=diagnostic,
        previous_closure_receipt_id=previous_closure_receipt_id,
    )


def _counter_rows(values: object, field: str) -> tuple[tuple[str, int], ...]:
    if not isinstance(values, (list, tuple)):
        raise Protocol25SchemaError(f"{field} must be an array")
    result: list[tuple[str, int]] = []
    for item in values:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise Protocol25SchemaError(f"{field} row is invalid")
        authority_id = _schema(digest_value, item[0], field)
        count = _schema(nonnegative_int, item[1], field)
        result.append((authority_id, count))
    normalized = tuple(result)
    authority_ids = tuple(item[0] for item in normalized)
    if (
        normalized != tuple(sorted(normalized))
        or authority_ids != tuple(sorted(set(authority_ids)))
    ):
        raise Protocol25SchemaError(f"{field} must be sorted and unique")
    return normalized


@dataclass(frozen=True, slots=True)
class AuditClosureRootV1(_Authority):
    schema_version: int
    audit_epoch_id: str
    frozen_finding_ids: tuple[str, ...]
    latest_closure_receipts: tuple[FindingClosureReceiptV1, ...]
    unresolved_finding_ids: tuple[str, ...]
    target_rounds: tuple[tuple[str, int], ...]
    plateau_counts: tuple[tuple[str, int], ...]
    deferred_observations: tuple[DeferredObservationV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "audit_epoch_id",
        "frozen_finding_ids",
        "latest_closure_receipts",
        "unresolved_finding_ids",
        "target_rounds",
        "plateau_counts",
        "deferred_observations",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "AuditClosureRootV1.schema_version")
        _schema(digest_value, self.audit_epoch_id, "AuditClosureRootV1.audit_epoch_id")
        frozen = _digests(self.frozen_finding_ids, "AuditClosureRootV1.frozen_finding_ids")
        if not isinstance(self.latest_closure_receipts, (list, tuple)) or any(
            not isinstance(item, FindingClosureReceiptV1)
            for item in self.latest_closure_receipts
        ):
            raise Protocol25SchemaError("audit closure receipts are invalid")
        receipts = tuple(self.latest_closure_receipts)
        receipt_ids = tuple(item.finding_key_id for item in receipts)
        if receipt_ids != frozen:
            raise Protocol25SchemaError(
                "audit closure must contain one latest receipt for every frozen finding"
            )
        if any(item.audit_epoch_id != self.audit_epoch_id for item in receipts):
            raise Protocol25SchemaError("audit closure receipt is outside its epoch")
        expected_unresolved = tuple(
            item.finding_key_id for item in receipts if item.verdict == "open"
        )
        unresolved = _digests(
            self.unresolved_finding_ids,
            "AuditClosureRootV1.unresolved_finding_ids",
        )
        if unresolved != expected_unresolved:
            raise Protocol25SchemaError(
                "audit closure unresolved set disagrees with latest receipts"
            )
        rounds = _counter_rows(self.target_rounds, "AuditClosureRootV1.target_rounds")
        plateaus = _counter_rows(self.plateau_counts, "AuditClosureRootV1.plateau_counts")
        if tuple(row[0] for row in rounds) != tuple(row[0] for row in plateaus):
            raise Protocol25SchemaError("audit closure target counters disagree")
        if not isinstance(self.deferred_observations, (list, tuple)) or any(
            not isinstance(item, DeferredObservationV1)
            for item in self.deferred_observations
        ):
            raise Protocol25SchemaError("audit closure deferred observations are invalid")
        deferred = tuple(self.deferred_observations)
        deferred_ids = tuple(item.observation_id for item in deferred)
        if deferred_ids != tuple(sorted(set(deferred_ids))):
            raise Protocol25SchemaError("audit closure deferred observations must be sorted and unique")
        object.__setattr__(self, "frozen_finding_ids", frozen)
        object.__setattr__(self, "latest_closure_receipts", receipts)
        object.__setattr__(self, "unresolved_finding_ids", unresolved)
        object.__setattr__(self, "target_rounds", rounds)
        object.__setattr__(self, "plateau_counts", plateaus)
        object.__setattr__(self, "deferred_observations", deferred)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "audit_epoch_id": self.audit_epoch_id,
            "frozen_finding_ids": list(self.frozen_finding_ids),
            "latest_closure_receipts": [
                item.to_json_dict() for item in self.latest_closure_receipts
            ],
            "unresolved_finding_ids": list(self.unresolved_finding_ids),
            "target_rounds": [list(item) for item in self.target_rounds],
            "plateau_counts": [list(item) for item in self.plateau_counts],
            "deferred_observations": [
                item.to_json_dict() for item in self.deferred_observations
            ],
        }

    @property
    def state(self) -> str:
        """Derive closure state without storing mutable routing authority."""
        if self.unresolved_finding_ids:
            return "open"
        if self.deferred_observations:
            return "next_epoch_required"
        return "closed"

    @classmethod
    def from_json_dict(cls, value: object) -> "AuditClosureRootV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            schema_version=raw["schema_version"],
            audit_epoch_id=raw["audit_epoch_id"],
            frozen_finding_ids=raw["frozen_finding_ids"],
            latest_closure_receipts=_decode_tuple(
                raw["latest_closure_receipts"],
                cls.__name__ + ".latest_closure_receipts",
                FindingClosureReceiptV1.from_json_dict,
            ),
            unresolved_finding_ids=raw["unresolved_finding_ids"],
            target_rounds=raw["target_rounds"],
            plateau_counts=raw["plateau_counts"],
            deferred_observations=_decode_tuple(
                raw["deferred_observations"],
                cls.__name__ + ".deferred_observations",
                DeferredObservationV1.from_json_dict,
            ),
        )


@dataclass(frozen=True, slots=True)
class L3SourceRootV1(_Authority):
    schema_version: int
    source_id: str
    selected_domain_keys: tuple[str, ...]
    full_source_coverage: bool
    audit_target_ids: tuple[str, ...]
    closure_root_hashes: tuple[str, ...]
    adopted_l2_root_hash: str
    unresolved_finding_ids: tuple[str, ...]
    deferred_observation_ids: tuple[str, ...]
    state: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "source_id",
        "selected_domain_keys",
        "full_source_coverage",
        "audit_target_ids",
        "closure_root_hashes",
        "adopted_l2_root_hash",
        "unresolved_finding_ids",
        "deferred_observation_ids",
        "state",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "L3SourceRootV1.schema_version")
        _schema(safe_id, self.source_id, "L3SourceRootV1.source_id")
        object.__setattr__(
            self,
            "selected_domain_keys",
            _digests(
                self.selected_domain_keys,
                "L3SourceRootV1.selected_domain_keys",
                nonempty=True,
            ),
        )
        if not isinstance(self.full_source_coverage, bool):
            raise Protocol25SchemaError("L3 source root coverage flag must be boolean")
        for field in (
            "audit_target_ids",
            "closure_root_hashes",
        ):
            object.__setattr__(
                self,
                field,
                _digests(
                    getattr(self, field),
                    f"L3SourceRootV1.{field}",
                    nonempty=True,
                ),
            )
        _schema(digest_value, self.adopted_l2_root_hash, "L3 source adopted L2 root")
        for field in ("unresolved_finding_ids", "deferred_observation_ids"):
            object.__setattr__(
                self,
                field,
                _digests(getattr(self, field), f"L3SourceRootV1.{field}"),
            )
        _schema(one_of, self.state, _ROOT_STATES, "L3 source root state")
        if self.state == "complete" and (
            self.unresolved_finding_ids or self.deferred_observation_ids
        ):
            raise Protocol25SchemaError(
                "complete L3 source root cannot retain unresolved or deferred authority"
            )
        if self.state == "next_epoch_required" and not self.deferred_observation_ids:
            raise Protocol25SchemaError(
                "next_epoch_required L3 source root requires deferred authority"
            )

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        for field in (
            "selected_domain_keys",
            "audit_target_ids",
            "closure_root_hashes",
            "unresolved_finding_ids",
            "deferred_observation_ids",
        ):
            result[field] = list(getattr(self, field))
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "L3SourceRootV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


__all__ = (
    "AuditCandidateV1",
    "AuditClosureRootV1",
    "AuditEpochV1",
    "AuditTargetCandidateAuthorityV1",
    "FindingAssessmentV1",
    "FindingClosureReceiptV1",
    "L3SourceRootV1",
    "ResolutionEntryV1",
    "SemanticCertificationReceiptV1",
    "SemanticResolutionOverlayV1",
    "SourceCompositionAssessmentV1",
    "TargetClosureAssessmentV1",
    "build_finding_closure_receipt",
    "build_semantic_resolution_overlay",
    "build_source_composition_assessment",
)
