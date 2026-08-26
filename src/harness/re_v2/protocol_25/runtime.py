"""Deterministic protocol-2.5 candidate schemas, normalization, and certification."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Mapping
import unicodedata

from jsonschema import Draft202012Validator, ValidationError

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.baseline import (
    ArtifactAcceptanceReceiptV2,
    CandidateAssessmentReceiptV1,
)
from harness.re_v2.protocol_22.artifacts import ContextBundleV1
from harness.re_v2.protocol_22.execution import CandidateInventoryV1
from harness.re_v2.protocol_22.evidence import SnapshotReaderV1
from harness.re_v2.protocol_22.model import ArtifactKeyV2
from harness.re_v2.protocol_22.partition import (
    FileRecordV1,
    WorkspacePartitionCatalogV1,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    load_canonical_object,
    positive_int,
    safe_id,
    safe_relative_path,
    sorted_unique_digests,
)
from harness.re_v2.protocol_24.artifacts import L2CompactBaselineArtifactV1

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
    build_semantic_resolution_overlay,
    build_source_composition_assessment,
)
from .findings import (
    AuditTargetV1,
    DeferredObservationV1,
    EvidenceAnchorAuthorityV1,
    FindingAuthorityVocabularyV1,
    SemanticFindingV1,
    normalize_finding_key,
)
from .model import Protocol25SchemaError
from .policies import (
    SEMANTIC_PRODUCER_PROTOCOL_BY_ARTIFACT,
    SemanticArtifactPolicyCatalogV1,
    build_semantic_v1_policy_catalog,
)


_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
_MODES = frozenset(
    {
        "AUDIT_EPOCH_TARGET",
        "SEMANTIC_RESOLUTION",
        "CLOSURE_RECHECK",
        "SOURCE_COMPOSITION_GUARD",
    }
)
_MAX_FINDINGS = 64
_MAX_ENTRIES = 64
_MAX_DEFERRED = 64


class Protocol25RuntimeError(Protocol25SchemaError):
    """Raised when bounded L3 candidate authority is invalid."""


def _closed(required: tuple[str, ...], properties: Mapping[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(required),
        "properties": dict(properties),
    }


def _digest_schema() -> dict[str, object]:
    return {"type": "string", "pattern": _DIGEST_PATTERN}


def _safe_id_schema() -> dict[str, object]:
    return {"type": "string", "pattern": _SAFE_ID_PATTERN, "maxLength": 512}


def _text_schema(maximum: int = 4096) -> dict[str, object]:
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def _evidence_schema() -> dict[str, object]:
    return _closed(
        ("reference", "path", "start_line", "end_line"),
        {
            "reference": _safe_id_schema(),
            "path": {"type": "string", "minLength": 1, "maxLength": 4096},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
    )


def _finding_schema(*, deferred: bool = False) -> dict[str, object]:
    properties: dict[str, object] = {
        "rule_id": _safe_id_schema(),
        "finding_class": _safe_id_schema(),
        "subject_kind": _safe_id_schema(),
        "subject_ref": _safe_id_schema(),
        "claim_anchor_ids": {
            "type": "array",
            "uniqueItems": True,
            "maxItems": 32,
            "items": _safe_id_schema(),
        },
        "evidence": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "uniqueItems": True,
            "items": _evidence_schema(),
        },
    }
    if deferred:
        properties["diagnostic"] = _text_schema()
        required = tuple(properties)
    else:
        properties.update(
            {
                "title": _text_schema(256),
                "explanation": _text_schema(),
                "recommendation": _text_schema(),
                "repair_context": _text_schema(),
            }
        )
        required = tuple(properties)
    return _closed(required, properties)


def _audit_schema() -> dict[str, object]:
    schema = _closed(
        ("schema_version", "audit_target_id", "verdict", "findings"),
        {
            "schema_version": {"const": 1},
            "audit_target_id": _digest_schema(),
            "verdict": {"enum": ["PASS", "REPAIR"]},
            "findings": {
                "type": "array",
                "maxItems": _MAX_FINDINGS,
                "items": _finding_schema(),
            },
        },
    )
    schema["allOf"] = [
        {
            "if": {
                "properties": {"verdict": {"const": "PASS"}},
                "required": ["verdict"],
            },
            "then": {"properties": {"findings": {"maxItems": 0}}},
            "else": {"properties": {"findings": {"minItems": 1}}},
        }
    ]
    return schema


def _resolution_schema() -> dict[str, object]:
    entry = _closed(
        (
            "finding_key_ids",
            "disposition",
            "semantic_claims",
            "evidence",
            "supersedes_claim_anchor_ids",
            "refines_subject_refs",
            "unresolved",
        ),
        {
            "finding_key_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": _MAX_FINDINGS,
                "uniqueItems": True,
                "items": _digest_schema(),
            },
            "disposition": {
                "enum": ["resolved", "qualified", "deferred", "human_decision"]
            },
            "semantic_claims": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": _text_schema(),
            },
            "evidence": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "uniqueItems": True,
                "items": _evidence_schema(),
            },
            "supersedes_claim_anchor_ids": {
                "type": "array",
                "maxItems": 32,
                "uniqueItems": True,
                "items": _safe_id_schema(),
            },
            "refines_subject_refs": {
                "type": "array",
                "maxItems": 32,
                "uniqueItems": True,
                "items": _safe_id_schema(),
            },
            "unresolved": {"type": "boolean"},
        },
    )
    return _closed(
        (
            "schema_version",
            "audit_epoch_id",
            "audit_target_id",
            "semantic_round",
            "entries",
        ),
        {
            "schema_version": {"const": 1},
            "audit_epoch_id": _digest_schema(),
            "audit_target_id": _digest_schema(),
            "semantic_round": {"type": "integer", "minimum": 1, "maximum": 3},
            "entries": {
                "type": "array",
                "minItems": 1,
                "maxItems": _MAX_ENTRIES,
                "items": entry,
            },
        },
    )


def _closure_schema() -> dict[str, object]:
    common = {
        "schema_version": {"const": 1},
        "assessment_kind": {"enum": ["target", "source-composition"]},
        "audit_epoch_id": _digest_schema(),
        "deferred_observations": {
            "type": "array",
            "maxItems": _MAX_DEFERRED,
            "items": _finding_schema(deferred=True),
        },
    }
    target = _closed(
        (
            "schema_version",
            "assessment_kind",
            "audit_epoch_id",
            "audit_target_id",
            "resolution_overlay_hash",
            "verdicts",
            "deferred_observations",
        ),
        {
            **common,
            "assessment_kind": {"const": "target"},
            "audit_target_id": _digest_schema(),
            "resolution_overlay_hash": _digest_schema(),
            "verdicts": {
                "type": "array",
                "maxItems": _MAX_FINDINGS,
                "items": _closed(
                    ("finding_key_id", "verdict", "reason_code"),
                    {
                        "finding_key_id": _digest_schema(),
                        "verdict": {"enum": ["closed", "open"]},
                        "reason_code": _safe_id_schema(),
                    },
                ),
            },
        },
    )
    source = _closed(
        (
            "schema_version",
            "assessment_kind",
            "audit_epoch_id",
            "source_id",
            "overlay_hashes",
            "target_assessment_hashes",
            "outcome",
            "implicated_finding_ids",
            "deferred_observations",
        ),
        {
            **common,
            "assessment_kind": {"const": "source-composition"},
            "source_id": _safe_id_schema(),
            "overlay_hashes": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": _digest_schema(),
            },
            "target_assessment_hashes": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": _digest_schema(),
            },
            "outcome": {"enum": ["passed", "failed"]},
            "implicated_finding_ids": {
                "type": "array",
                "uniqueItems": True,
                "items": _digest_schema(),
            },
        },
    )
    return {"oneOf": [target, source]}


def semantic_response_schema(artifact_kind: str) -> dict[str, object]:
    """Return one closed schema without modifying protocol-2.2 registrations."""
    schemas = {
        "semantic-audit-findings": _audit_schema,
        "semantic-resolution-overlay": _resolution_schema,
        "semantic-closure-assessment": _closure_schema,
    }
    builder = schemas.get(artifact_kind)
    if builder is None:
        raise Protocol25RuntimeError(
            f"unsupported protocol-2.5 response schema: {artifact_kind!r}"
        )
    schema = builder()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **schema,
    }


@dataclass(frozen=True, slots=True)
class AuthorizedEvidenceRangeV1:
    schema_version: int
    canonical_anchor_id: str
    aliases: tuple[str, ...]
    source_id: str
    source_relative_path: str
    start_line: int
    end_line: int
    source_blob_hash: str
    file_record: FileRecordV1

    def __post_init__(self) -> None:
        try:
            if self.schema_version != 1 or isinstance(self.schema_version, bool):
                raise Protocol25RuntimeError("authorized evidence schema_version must be 1")
            safe_id(self.canonical_anchor_id, "authorized evidence anchor")
            safe_id(self.source_id, "authorized evidence source")
            safe_relative_path(self.source_relative_path, "authorized evidence path")
            start = positive_int(self.start_line, "authorized evidence start_line")
            end = positive_int(self.end_line, "authorized evidence end_line")
            digest_value(self.source_blob_hash, "authorized evidence source_blob_hash")
        except Protocol22SchemaError as exc:
            raise Protocol25RuntimeError(str(exc)) from exc
        if start > end:
            raise Protocol25RuntimeError("authorized evidence line range is reversed")
        aliases = tuple(sorted(self.aliases))
        if (
            aliases != tuple(sorted(set(aliases)))
            or self.canonical_anchor_id in aliases
        ):
            raise Protocol25RuntimeError("authorized evidence aliases are invalid")
        for alias in aliases:
            try:
                safe_id(alias, "authorized evidence alias")
            except Protocol22SchemaError as exc:
                raise Protocol25RuntimeError(str(exc)) from exc
        if (
            not isinstance(self.file_record, FileRecordV1)
            or self.file_record.source_relative_path != self.source_relative_path
            or self.file_record.content_hash != self.source_blob_hash
            or self.file_record.object_kind != "regular"
            or self.end_line > self.file_record.line_count
        ):
            raise Protocol25RuntimeError(
                "authorized evidence file record does not bind the range"
            )
        object.__setattr__(self, "aliases", aliases)

    @property
    def references(self) -> tuple[str, ...]:
        return (self.canonical_anchor_id, *self.aliases)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "canonical_anchor_id": self.canonical_anchor_id,
            "aliases": list(self.aliases),
            "source_id": self.source_id,
            "source_relative_path": self.source_relative_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "source_blob_hash": self.source_blob_hash,
            "file_record": self.file_record.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "AuthorizedEvidenceRangeV1":
        fields = frozenset(
            {
                "schema_version",
                "canonical_anchor_id",
                "aliases",
                "source_id",
                "source_relative_path",
                "start_line",
                "end_line",
                "source_blob_hash",
                "file_record",
            }
        )
        try:
            raw = exact_object(value, fields, cls.__name__)
            aliases = raw["aliases"]
            if not isinstance(aliases, (list, tuple)):
                raise Protocol22SchemaError(
                    "AuthorizedEvidenceRangeV1.aliases must be an array"
                )
            return cls(
                schema_version=raw["schema_version"],
                canonical_anchor_id=raw["canonical_anchor_id"],
                aliases=tuple(aliases),
                source_id=raw["source_id"],
                source_relative_path=raw["source_relative_path"],
                start_line=raw["start_line"],
                end_line=raw["end_line"],
                source_blob_hash=raw["source_blob_hash"],
                file_record=FileRecordV1.from_json_dict(raw["file_record"]),
            )
        except Protocol22SchemaError as exc:
            raise Protocol25RuntimeError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class BoundedAuthorityObjectV1:
    """Exact content-addressed authority bytes included in a provider context."""

    object_hash: str
    payload_text: str

    def __post_init__(self) -> None:
        try:
            digest_value(self.object_hash, "bounded authority object hash")
        except Protocol22SchemaError as exc:
            raise Protocol25RuntimeError(str(exc)) from exc
        if not isinstance(self.payload_text, str) or "\x00" in self.payload_text:
            raise Protocol25RuntimeError(
                "bounded authority object must be NUL-free UTF-8 text"
            )
        try:
            payload = self.payload_text.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise Protocol25RuntimeError(
                "bounded authority object must be NUL-free UTF-8 text"
            ) from exc
        if content_digest(payload) != self.object_hash:
            raise Protocol25RuntimeError(
                "bounded authority object does not match its content address"
            )

    @property
    def payload_bytes(self) -> bytes:
        return self.payload_text.encode("utf-8", errors="strict")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "object_hash": self.object_hash,
            "payload_text": self.payload_text,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "BoundedAuthorityObjectV1":
        try:
            raw = exact_object(
                value,
                frozenset({"object_hash", "payload_text"}),
                cls.__name__,
            )
            return cls(
                object_hash=raw["object_hash"],
                payload_text=raw["payload_text"],
            )
        except Protocol22SchemaError as exc:
            raise Protocol25RuntimeError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class SemanticContextV1:
    schema_version: int
    mode: str
    audit_target: AuditTargetV1
    vocabulary: FindingAuthorityVocabularyV1
    authorized_evidence: tuple[AuthorizedEvidenceRangeV1, ...]
    authority_objects: tuple[BoundedAuthorityObjectV1, ...]
    lower_authority_hashes: tuple[str, ...]
    unresolved_findings: tuple[SemanticFindingV1, ...]
    overlay_hashes: tuple[str, ...]
    target_assessment_hashes: tuple[str, ...]
    active_sibling_authority_hashes: tuple[str, ...]
    response_schema_hash: str
    max_canonical_json_bytes: int

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.mode not in _MODES:
            raise Protocol25RuntimeError("semantic context mode/schema is invalid")
        try:
            digest_value(self.response_schema_hash, "semantic context response schema")
        except Protocol22SchemaError as exc:
            raise Protocol25RuntimeError(str(exc)) from exc
        if not isinstance(self.audit_target, AuditTargetV1) or not isinstance(
            self.vocabulary, FindingAuthorityVocabularyV1
        ):
            raise Protocol25RuntimeError("semantic context target/vocabulary is invalid")
        if self.vocabulary.audit_target_id != self.audit_target.identity:
            raise Protocol25RuntimeError("semantic context vocabulary targets another audit")
        evidence = tuple(self.authorized_evidence)
        if not evidence or any(
            not isinstance(item, AuthorizedEvidenceRangeV1) for item in evidence
        ):
            raise Protocol25RuntimeError("semantic context requires authorized evidence")
        evidence_authority = tuple(
            (item.canonical_anchor_id, item.aliases) for item in evidence
        )
        expected_authority = tuple(
            (item.anchor_id, item.aliases)
            for item in self.vocabulary.evidence_anchors
        )
        if evidence_authority != expected_authority:
            raise Protocol25RuntimeError(
                "semantic context evidence does not equal controller vocabulary"
            )
        if any(
            item.source_id != self.audit_target.scope.source_id
            for item in evidence
        ):
            raise Protocol25RuntimeError(
                "semantic context evidence is outside its target source"
            )
        names = [name for item in evidence for name in item.references]
        if len(names) != len(set(names)):
            raise Protocol25RuntimeError("semantic context evidence references collide")
        objects = tuple(self.authority_objects)
        if not objects or any(
            not isinstance(item, BoundedAuthorityObjectV1) for item in objects
        ):
            raise Protocol25RuntimeError("semantic context authority objects are invalid")
        object_hashes = tuple(item.object_hash for item in objects)
        if object_hashes != tuple(sorted(set(object_hashes))):
            raise Protocol25RuntimeError(
                "semantic context authority objects must be sorted and unique"
            )
        findings = tuple(self.unresolved_findings)
        finding_ids = tuple(item.finding_key_id for item in findings)
        if finding_ids != tuple(sorted(set(finding_ids))):
            raise Protocol25RuntimeError("semantic context unresolved findings are invalid")
        if self.mode != "SOURCE_COMPOSITION_GUARD" and any(
            item.finding_key.audit_target_id != self.audit_target.identity
            for item in findings
        ):
            raise Protocol25RuntimeError(
                "semantic context finding is outside its audit target"
            )
        for field_name in (
            "lower_authority_hashes",
            "overlay_hashes",
            "target_assessment_hashes",
            "active_sibling_authority_hashes",
        ):
            try:
                values = sorted_unique_digests(
                    getattr(self, field_name), f"SemanticContextV1.{field_name}"
                )
            except Protocol22SchemaError as exc:
                raise Protocol25RuntimeError(str(exc)) from exc
            object.__setattr__(self, field_name, values)
        if not self.lower_authority_hashes:
            raise Protocol25RuntimeError("semantic context lower authority is empty")
        target_authority = {
            *(item.artifact_hash for item in self.audit_target.audited_artifacts),
            *self.audit_target.lower_dependency_hashes,
            *self.audit_target.context_object_hashes,
            *self.audit_target.evidence_object_hashes,
        }
        if target_authority != set(self.lower_authority_hashes):
            raise Protocol25RuntimeError(
                "semantic context lower authority is not the exact audit-target closure"
            )
        expected_object_hashes = tuple(
            sorted(
                {
                    *self.lower_authority_hashes,
                    *self.overlay_hashes,
                    *self.target_assessment_hashes,
                    *self.active_sibling_authority_hashes,
                }
            )
        )
        if object_hashes != expected_object_hashes:
            raise Protocol25RuntimeError(
                "semantic context authority bytes do not equal declared authority"
            )
        if not isinstance(self.max_canonical_json_bytes, int) or self.max_canonical_json_bytes <= 0:
            raise Protocol25RuntimeError("semantic context byte ceiling is invalid")
        object.__setattr__(self, "authorized_evidence", evidence)
        object.__setattr__(self, "authority_objects", objects)
        object.__setattr__(self, "unresolved_findings", findings)
        if len(canonical_json_bytes(self.to_json_dict())) > self.max_canonical_json_bytes:
            raise Protocol25RuntimeError("semantic context exceeds its byte ceiling")

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "audit_target": self.audit_target.to_json_dict(),
            "vocabulary": self.vocabulary.to_json_dict(),
            "authorized_evidence": [
                item.to_json_dict() for item in self.authorized_evidence
            ],
            "authority_objects": [
                item.to_json_dict() for item in self.authority_objects
            ],
            "lower_authority_hashes": list(self.lower_authority_hashes),
            "unresolved_findings": [
                item.to_json_dict() for item in self.unresolved_findings
            ],
            "overlay_hashes": list(self.overlay_hashes),
            "target_assessment_hashes": list(self.target_assessment_hashes),
            "active_sibling_authority_hashes": list(
                self.active_sibling_authority_hashes
            ),
            "response_schema_hash": self.response_schema_hash,
            "max_canonical_json_bytes": self.max_canonical_json_bytes,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SemanticContextV1":
        fields = frozenset(
            {
                "schema_version",
                "mode",
                "audit_target",
                "vocabulary",
                "authorized_evidence",
                "authority_objects",
                "lower_authority_hashes",
                "unresolved_findings",
                "overlay_hashes",
                "target_assessment_hashes",
                "active_sibling_authority_hashes",
                "response_schema_hash",
                "max_canonical_json_bytes",
            }
        )
        try:
            raw = exact_object(value, fields, cls.__name__)
            arrays = (
                "authorized_evidence",
                "authority_objects",
                "lower_authority_hashes",
                "unresolved_findings",
                "overlay_hashes",
                "target_assessment_hashes",
                "active_sibling_authority_hashes",
            )
            if any(not isinstance(raw[field], (list, tuple)) for field in arrays):
                raise Protocol22SchemaError(
                    "SemanticContextV1 collection fields must be arrays"
                )
            return cls(
                schema_version=raw["schema_version"],
                mode=raw["mode"],
                audit_target=AuditTargetV1.from_json_dict(raw["audit_target"]),
                vocabulary=FindingAuthorityVocabularyV1.from_json_dict(
                    raw["vocabulary"]
                ),
                authorized_evidence=tuple(
                    AuthorizedEvidenceRangeV1.from_json_dict(item)
                    for item in raw["authorized_evidence"]
                ),
                authority_objects=tuple(
                    BoundedAuthorityObjectV1.from_json_dict(item)
                    for item in raw["authority_objects"]
                ),
                lower_authority_hashes=tuple(raw["lower_authority_hashes"]),
                unresolved_findings=tuple(
                    SemanticFindingV1.from_json_dict(item)
                    for item in raw["unresolved_findings"]
                ),
                overlay_hashes=tuple(raw["overlay_hashes"]),
                target_assessment_hashes=tuple(raw["target_assessment_hashes"]),
                active_sibling_authority_hashes=tuple(
                    raw["active_sibling_authority_hashes"]
                ),
                response_schema_hash=raw["response_schema_hash"],
                max_canonical_json_bytes=raw["max_canonical_json_bytes"],
            )
        except Protocol22SchemaError as exc:
            raise Protocol25RuntimeError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class SemanticCandidateInputV1:
    candidate_id: str
    execution_capture_hash: str
    inventory: CandidateInventoryV1
    candidate_bytes: bytes

    def __post_init__(self) -> None:
        try:
            digest_value(self.candidate_id, "semantic candidate_id")
            digest_value(self.execution_capture_hash, "semantic execution_capture_hash")
        except Protocol22SchemaError as exc:
            raise Protocol25RuntimeError(str(exc)) from exc
        if not isinstance(self.inventory, CandidateInventoryV1):
            raise Protocol25RuntimeError("semantic candidate inventory is invalid")
        if not isinstance(self.candidate_bytes, bytes):
            raise Protocol25RuntimeError("semantic candidate bytes are invalid")


@dataclass(frozen=True, slots=True)
class SemanticCertificationResultV1:
    artifact: object
    artifact_bytes: bytes
    normalized_authorial_payload_bytes: bytes
    certification: SemanticCertificationReceiptV1
    candidate_assessment: CandidateAssessmentReceiptV1
    acceptance: ArtifactAcceptanceReceiptV2

    @property
    def normalized_findings(self) -> tuple[SemanticFindingV1, ...]:
        if isinstance(self.artifact, AuditCandidateV1):
            return self.artifact.findings
        return ()


@dataclass(frozen=True, slots=True)
class ComposedSemanticViewV1:
    """Deterministic source view presented to the composition guard."""

    schema_version: int
    audit_epoch_id: str
    source_id: str
    lower_authority_hashes: tuple[str, ...]
    active_sibling_authority_hashes: tuple[str, ...]
    overlays: tuple[SemanticResolutionOverlayV1, ...]
    target_assessments: tuple[TargetClosureAssessmentV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol25RuntimeError("composed view schema_version must be 1")
        try:
            digest_value(self.audit_epoch_id, "composed view audit_epoch_id")
            safe_id(self.source_id, "composed view source_id")
            lower = sorted_unique_digests(
                self.lower_authority_hashes, "composed view lower authority"
            )
            siblings = sorted_unique_digests(
                self.active_sibling_authority_hashes,
                "composed view active sibling authority",
            )
        except Protocol22SchemaError as exc:
            raise Protocol25RuntimeError(str(exc)) from exc
        if not lower:
            raise Protocol25RuntimeError(
                "composed view requires lower authority"
            )
        overlays = tuple(self.overlays)
        if not overlays or any(
            not isinstance(item, SemanticResolutionOverlayV1) for item in overlays
        ):
            raise Protocol25RuntimeError("composed view overlays are invalid")
        overlay_keys = tuple(
            (item.audit_target_id, item.semantic_round, item.identity)
            for item in overlays
        )
        if overlay_keys != tuple(sorted(set(overlay_keys))):
            raise Protocol25RuntimeError(
                "composed view overlays must be sorted and unique"
            )
        if any(
            item.audit_epoch_id != self.audit_epoch_id
            or item.artifact_key.scope.source_id != self.source_id
            for item in overlays
        ):
            raise Protocol25RuntimeError(
                "composed view overlay is outside its source or epoch"
            )
        assessments = tuple(self.target_assessments)
        if not assessments or any(
            not isinstance(item, TargetClosureAssessmentV1)
            for item in assessments
        ):
            raise Protocol25RuntimeError(
                "composed view target assessments are invalid"
            )
        assessment_keys = tuple(
            (
                item.audit_target_id,
                item.resolution_overlay_hash,
                item.identity,
            )
            for item in assessments
        )
        if assessment_keys != tuple(sorted(set(assessment_keys))):
            raise Protocol25RuntimeError(
                "composed view target assessments must be sorted and unique"
            )
        if any(item.audit_epoch_id != self.audit_epoch_id for item in assessments):
            raise Protocol25RuntimeError(
                "composed view target assessment is outside its epoch"
            )
        object.__setattr__(self, "lower_authority_hashes", lower)
        object.__setattr__(self, "active_sibling_authority_hashes", siblings)
        object.__setattr__(self, "overlays", overlays)
        object.__setattr__(self, "target_assessments", assessments)

    @property
    def overlay_hashes(self) -> tuple[str, ...]:
        return tuple(sorted(item.identity for item in self.overlays))

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    @property
    def target_assessment_hashes(self) -> tuple[str, ...]:
        return tuple(sorted(item.identity for item in self.target_assessments))

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "audit_epoch_id": self.audit_epoch_id,
            "source_id": self.source_id,
            "lower_authority_hashes": list(self.lower_authority_hashes),
            "active_sibling_authority_hashes": list(
                self.active_sibling_authority_hashes
            ),
            "overlays": [item.to_json_dict() for item in self.overlays],
            "target_assessments": [
                item.to_json_dict() for item in self.target_assessments
            ],
        }


@dataclass(frozen=True, slots=True)
class Protocol25DeterministicRuntime:
    verifier_authority_hash: str
    snapshot_reader: SnapshotReaderV1
    artifact_policy: SemanticArtifactPolicyCatalogV1 = field(
        default_factory=build_semantic_v1_policy_catalog
    )

    def __post_init__(self) -> None:
        try:
            digest_value(self.verifier_authority_hash, "semantic verifier authority")
        except Protocol22SchemaError as exc:
            raise Protocol25RuntimeError(str(exc)) from exc
        if not isinstance(self.artifact_policy, SemanticArtifactPolicyCatalogV1):
            raise Protocol25RuntimeError("semantic artifact policy is invalid")
        if not callable(getattr(self.snapshot_reader, "read_file", None)):
            raise Protocol25RuntimeError("snapshot reader lacks the shared read_file seam")

    def build_audit_context(
        self,
        *,
        audit_target: AuditTargetV1,
        workspace_partition: WorkspacePartitionCatalogV1,
        authority_payloads: Mapping[str, bytes],
    ) -> SemanticContextV1:
        """Derive one closed audit vocabulary from accepted L2 authority."""
        if not isinstance(audit_target, AuditTargetV1):
            raise Protocol25RuntimeError("audit context target is invalid")
        if not isinstance(workspace_partition, WorkspacePartitionCatalogV1):
            raise Protocol25RuntimeError("audit context workspace partition is invalid")
        expected_hashes = tuple(
            sorted(
                {
                    *(item.artifact_hash for item in audit_target.audited_artifacts),
                    *audit_target.lower_dependency_hashes,
                    *audit_target.context_object_hashes,
                    *audit_target.evidence_object_hashes,
                }
            )
        )
        if set(authority_payloads) != set(expected_hashes):
            raise Protocol25RuntimeError(
                "audit context payloads do not equal the target authority closure"
            )
        for object_hash, payload in authority_payloads.items():
            if not isinstance(payload, bytes) or content_digest(payload) != object_hash:
                raise Protocol25RuntimeError(
                    "audit context payload differs from its content address"
                )

        source = next(
            (
                item
                for item in workspace_partition.sources
                if item.source_id == audit_target.scope.source_id
            ),
            None,
        )
        if source is None:
            raise Protocol25RuntimeError(
                "audit context source is absent from the workspace partition"
            )
        files = {item.source_relative_path: item for item in source.files}

        try:
            contexts = tuple(
                load_canonical_object(
                    authority_payloads[object_hash], ContextBundleV1.from_json_dict
                )
                for object_hash in audit_target.context_object_hashes
            )
            audited = tuple(
                (
                    authority,
                    load_canonical_object(
                        authority_payloads[authority.artifact_hash],
                        L2CompactBaselineArtifactV1.from_json_dict,
                    ),
                )
                for authority in audit_target.audited_artifacts
            )
        except Protocol22SchemaError as exc:
            raise Protocol25RuntimeError(
                "audit context lower authority is not a closed L2 object"
            ) from exc

        for authority, artifact in audited:
            if (
                artifact.artifact.scope != audit_target.scope
                or artifact.artifact.context_bundle_hash
                not in audit_target.context_object_hashes
                or artifact.artifact.dependency_hashes
                != authority.dependency_hashes
            ):
                raise Protocol25RuntimeError(
                    "audited L2 artifact does not match its target authority"
                )
        for context in contexts:
            if (
                context.scope != audit_target.scope
                or context.evidence_pack_hash not in audit_target.evidence_object_hashes
            ):
                raise Protocol25RuntimeError(
                    "L2 context bundle does not match its audit target"
                )

        subject_refs = {f"source:{audit_target.scope.source_id}"}
        if audit_target.scope.domain_key is not None:
            subject_refs.add(
                f"domain:{audit_target.scope.domain_key.removeprefix('sha256:')}"
            )
        claim_anchor_ids: set[str] = set()
        for authority, artifact in sorted(
            audited, key=lambda item: item[0].artifact_hash
        ):
            artifact_id = authority.artifact_hash.removeprefix("sha256:")
            for surface_name, surface in artifact.surfaces.items():
                subject_refs.add(f"surface:{artifact_id}:{surface_name}")
                for index, _claim in enumerate(surface.items):
                    claim_id = f"claim:{artifact_id}:{surface_name}:{index}"
                    subject_refs.add(claim_id)
                    claim_anchor_ids.add(claim_id)

        excerpts = {}
        for context in contexts:
            for excerpt in context.evidence:
                existing = excerpts.get(excerpt.evidence_authority_id)
                if existing is not None and existing != excerpt:
                    raise Protocol25RuntimeError(
                        "audit context evidence authority is ambiguous"
                    )
                excerpts[excerpt.evidence_authority_id] = excerpt

        authorized_evidence = []
        evidence_anchors = []
        for evidence_id, excerpt in sorted(excerpts.items()):
            record = files.get(excerpt.source_relative_path)
            if record is None:
                raise Protocol25RuntimeError(
                    "audit context evidence is absent from the workspace partition"
                )
            canonical_anchor = f"evidence:{evidence_id.removeprefix('sha256:')}"
            aliases = (evidence_id,)
            authorized_evidence.append(
                AuthorizedEvidenceRangeV1(
                    schema_version=1,
                    canonical_anchor_id=canonical_anchor,
                    aliases=aliases,
                    source_id=audit_target.scope.source_id,
                    source_relative_path=excerpt.source_relative_path,
                    start_line=excerpt.start_line,
                    end_line=excerpt.end_line,
                    source_blob_hash=excerpt.source_blob_hash,
                    file_record=record,
                )
            )
            evidence_anchors.append(
                EvidenceAnchorAuthorityV1(
                    schema_version=1,
                    anchor_id=canonical_anchor,
                    aliases=aliases,
                )
            )
        vocabulary = FindingAuthorityVocabularyV1(
            schema_version=1,
            audit_target_id=audit_target.identity,
            rule_ids=self.artifact_policy.audit_taxonomy.rule_ids,
            subject_refs=tuple(sorted(subject_refs)),
            claim_anchor_ids=tuple(sorted(claim_anchor_ids)),
            evidence_anchors=tuple(
                sorted(evidence_anchors, key=lambda item: item.anchor_id)
            ),
        )
        return self.build_context(
            mode="AUDIT_EPOCH_TARGET",
            audit_target=audit_target,
            vocabulary=vocabulary,
            authorized_evidence=tuple(
                sorted(
                    authorized_evidence,
                    key=lambda item: item.canonical_anchor_id,
                )
            ),
            authority_payloads=authority_payloads,
            lower_authority_hashes=expected_hashes,
            unresolved_findings=(),
            overlay_hashes=(),
            target_assessment_hashes=(),
            active_sibling_authority_hashes=(),
        )

    def build_context(
        self,
        *,
        mode: str,
        audit_target: AuditTargetV1,
        vocabulary: FindingAuthorityVocabularyV1,
        authorized_evidence: tuple[AuthorizedEvidenceRangeV1, ...],
        authority_payloads: Mapping[str, bytes],
        lower_authority_hashes: tuple[str, ...],
        unresolved_findings: tuple[SemanticFindingV1, ...],
        overlay_hashes: tuple[str, ...],
        target_assessment_hashes: tuple[str, ...],
        active_sibling_authority_hashes: tuple[str, ...],
        ) -> SemanticContextV1:
        if not isinstance(authority_payloads, Mapping):
            raise Protocol25RuntimeError("semantic context authority payloads are invalid")
        authority_objects: list[BoundedAuthorityObjectV1] = []
        for object_hash, payload in sorted(authority_payloads.items()):
            if not isinstance(object_hash, str) or not isinstance(payload, bytes):
                raise Protocol25RuntimeError(
                    "semantic context authority payloads are invalid"
                )
            try:
                payload_text = payload.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise Protocol25RuntimeError(
                    "semantic context authority payload is not UTF-8"
                ) from exc
            authority_objects.append(
                BoundedAuthorityObjectV1(
                    object_hash=object_hash,
                    payload_text=payload_text,
                )
            )
        for item in authorized_evidence:
            try:
                payload = self.snapshot_reader.read_file(
                    item.source_id,
                    item.source_relative_path,
                    item.file_record,
                )
            except Exception as exc:
                raise Protocol25RuntimeError(
                    "authorized evidence does not match the pinned snapshot"
                ) from exc
            if content_digest(payload) != item.source_blob_hash:
                raise Protocol25RuntimeError(
                    "authorized evidence blob differs from pinned snapshot"
                )
        kind_by_mode = {
            "AUDIT_EPOCH_TARGET": "semantic-audit-findings",
            "SEMANTIC_RESOLUTION": "semantic-resolution-overlay",
            "CLOSURE_RECHECK": "target-closure-assessment",
            "SOURCE_COMPOSITION_GUARD": "source-composition-assessment",
        }
        if mode not in kind_by_mode:
            raise Protocol25RuntimeError("semantic context mode is unsupported")
        policy = self.artifact_policy.entry_for("L3", kind_by_mode[mode])
        response_schema_kind = (
            "semantic-closure-assessment"
            if mode in {"CLOSURE_RECHECK", "SOURCE_COMPOSITION_GUARD"}
            else (
                "semantic-resolution-overlay"
                if mode == "SEMANTIC_RESOLUTION"
                else "semantic-audit-findings"
            )
        )
        response_schema_hash = content_digest(
            semantic_response_schema(response_schema_kind)
        )
        if (
            mode == "AUDIT_EPOCH_TARGET"
            and audit_target.response_schema_hash != response_schema_hash
        ):
            raise Protocol25RuntimeError(
                "audit target response schema differs from runtime authority"
            )
        return SemanticContextV1(
            schema_version=1,
            mode=mode,
            audit_target=audit_target,
            vocabulary=vocabulary,
            authorized_evidence=authorized_evidence,
            authority_objects=tuple(authority_objects),
            lower_authority_hashes=lower_authority_hashes,
            unresolved_findings=unresolved_findings,
            overlay_hashes=overlay_hashes,
            target_assessment_hashes=target_assessment_hashes,
            active_sibling_authority_hashes=active_sibling_authority_hashes,
            response_schema_hash=response_schema_hash,
            max_canonical_json_bytes=policy.max_context_bundle_bytes,
        )

    def certify_audit(
        self,
        candidate: SemanticCandidateInputV1,
        *,
        artifact_key: ArtifactKeyV2,
        context: SemanticContextV1,
    ) -> SemanticCertificationResultV1:
        self._require_context(context, "AUDIT_EPOCH_TARGET")
        raw, normalized_payload = self._candidate_payload(
            candidate, "audit.json", "semantic-audit-findings"
        )
        if raw["audit_target_id"] != context.audit_target.identity:
            raise Protocol25RuntimeError("audit target does not match bounded context")
        normalized: dict[str, SemanticFindingV1] = {}
        for value in raw["findings"]:
            finding = self._normalize_finding(value, context)
            existing = normalized.get(finding.finding_key_id)
            if existing is None or canonical_json_bytes(
                finding.to_json_dict()
            ) < canonical_json_bytes(existing.to_json_dict()):
                normalized[finding.finding_key_id] = finding
        findings = tuple(normalized[key] for key in sorted(normalized))
        artifact = AuditCandidateV1(
            schema_version=1,
            audit_target=context.audit_target,
            artifact_key=artifact_key,
            audit_epoch_id=None,
            verdict=str(raw["verdict"]),
            findings=findings,
        )
        return self._certification_result(
            candidate,
            artifact_key,
            context,
            artifact,
            None,
            normalized_payload,
        )

    def certify_resolution(
        self,
        candidate: SemanticCandidateInputV1,
        *,
        artifact_key: ArtifactKeyV2,
        context: SemanticContextV1,
        epoch: AuditEpochV1,
        semantic_round: int,
        prior_overlay_hashes: tuple[str, ...],
        guidance_hash: str | None,
    ) -> SemanticCertificationResultV1:
        self._require_context(context, "SEMANTIC_RESOLUTION")
        raw, normalized_payload = self._candidate_payload(
            candidate, "resolution.json", "semantic-resolution-overlay"
        )
        if (
            raw["audit_epoch_id"] != epoch.identity
            or raw["audit_target_id"] != context.audit_target.identity
            or raw["semantic_round"] != semantic_round
        ):
            raise Protocol25RuntimeError(
                "resolution epoch, audit target, or semantic round is not exact"
            )
        expected = {item.finding_key_id for item in context.unresolved_findings}
        if not expected:
            raise Protocol25RuntimeError("resolution must not run without unresolved findings")
        entries: list[ResolutionEntryV1] = []
        observed: list[str] = []
        for value in raw["entries"]:
            finding_ids = tuple(sorted(value["finding_key_ids"]))
            observed.extend(finding_ids)
            evidence = self._evidence_anchor_ids(value["evidence"], context)
            supersedes = self._issued_ids(
                value["supersedes_claim_anchor_ids"],
                set(context.vocabulary.claim_anchor_ids),
                "supersession claim anchor",
            )
            refines = self._issued_ids(
                value["refines_subject_refs"],
                set(context.vocabulary.subject_refs),
                "refinement subject",
            )
            entries.append(
                ResolutionEntryV1(
                    schema_version=1,
                    finding_key_ids=finding_ids,
                    disposition=str(value["disposition"]),
                    semantic_claims=tuple(
                        sorted(
                            {
                                self._prose(item, "resolution semantic claim", 4096)
                                for item in value["semantic_claims"]
                            }
                        )
                    ),
                    evidence_anchor_ids=evidence,
                    supersedes_claim_anchor_ids=supersedes,
                    refines_subject_refs=refines,
                    unresolved=bool(value["unresolved"]),
                )
            )
        if len(observed) != len(set(observed)) or set(observed) != expected:
            raise Protocol25RuntimeError(
                "resolution must cover every unresolved finding exactly once"
            )
        artifact = build_semantic_resolution_overlay(
            epoch=epoch,
            schema_version=1,
            artifact_key=artifact_key,
            audit_target_id=context.audit_target.identity,
            semantic_round=semantic_round,
            prior_overlay_hashes=prior_overlay_hashes,
            guidance_hash=guidance_hash,
            entries=tuple(sorted(entries, key=lambda item: item.finding_key_ids)),
        )
        return self._certification_result(
            candidate,
            artifact_key,
            context,
            artifact,
            epoch.identity,
            normalized_payload,
        )

    def certify_target_closure(
        self,
        candidate: SemanticCandidateInputV1,
        *,
        artifact_key: ArtifactKeyV2,
        context: SemanticContextV1,
        epoch: AuditEpochV1,
        overlay: SemanticResolutionOverlayV1,
    ) -> SemanticCertificationResultV1:
        self._require_context(context, "CLOSURE_RECHECK")
        raw, normalized_payload = self._candidate_payload(
            candidate, "closure.json", "semantic-closure-assessment"
        )
        if raw["assessment_kind"] != "target":
            raise Protocol25RuntimeError("closure candidate is not a target assessment")
        if raw["audit_epoch_id"] != epoch.identity:
            raise Protocol25RuntimeError("closure audit epoch is not exact")
        if raw["audit_target_id"] != context.audit_target.identity:
            raise Protocol25RuntimeError("closure audit target is not exact")
        if raw["resolution_overlay_hash"] != overlay.identity:
            raise Protocol25RuntimeError("closure overlay hash is not exact")
        expected = tuple(item.finding_key_id for item in context.unresolved_findings)
        verdicts = tuple(
            sorted(
                (
                    FindingAssessmentV1(
                        schema_version=1,
                        finding_key_id=str(item["finding_key_id"]),
                        verdict=str(item["verdict"]),
                        reason_code=str(item["reason_code"]),
                    )
                    for item in raw["verdicts"]
                ),
                key=lambda item: item.finding_key_id,
            )
        )
        if tuple(item.finding_key_id for item in verdicts) != expected:
            raise Protocol25RuntimeError(
                "closure must assess every input finding exactly once"
            )
        artifact = TargetClosureAssessmentV1(
            schema_version=1,
            audit_epoch_id=epoch.identity,
            audit_target_id=context.audit_target.identity,
            assessed_finding_ids=expected,
            verdicts=verdicts,
            resolution_overlay_hash=overlay.identity,
            verifier_authority_hash=self.verifier_authority_hash,
            context_authority_hash=context.identity,
            deferred_observations=self._deferred_observations(
                raw["deferred_observations"], context
            ),
        )
        self._require_artifact_key(
            artifact_key,
            "target-closure-assessment",
            context,
            (epoch.identity, overlay.identity),
        )
        return self._certification_result(
            candidate,
            artifact_key,
            context,
            artifact,
            epoch.identity,
            normalized_payload,
        )

    def build_composed_view(
        self,
        *,
        context: SemanticContextV1,
        epoch: AuditEpochV1,
        source_id: str,
        overlays: tuple[SemanticResolutionOverlayV1, ...],
        target_assessments: tuple[TargetClosureAssessmentV1, ...],
    ) -> ComposedSemanticViewV1:
        """Bind lower authority, current overlays, and closed sibling authority."""
        self._require_context(context, "SOURCE_COMPOSITION_GUARD")
        if (
            context.audit_target.target_kind != "source"
            or context.audit_target.scope.source_id != source_id
        ):
            raise Protocol25RuntimeError(
                "source guard context requires its exact source audit target"
            )
        overlay_hashes = tuple(sorted(item.identity for item in overlays))
        assessment_hashes = tuple(
            sorted(item.identity for item in target_assessments)
        )
        if (
            overlay_hashes != context.overlay_hashes
            or assessment_hashes != context.target_assessment_hashes
        ):
            raise Protocol25RuntimeError(
                "composed view does not equal the current overlay/assessment set"
            )
        if any(
            item.audit_epoch_id != epoch.identity
            for item in target_assessments
        ):
            raise Protocol25RuntimeError(
                "composed view target assessment is outside the epoch"
            )
        overlay_findings = {
            finding_id for item in overlays for finding_id in item.finding_key_ids
        }
        context_findings = {
            item.finding_key_id for item in context.unresolved_findings
        }
        if overlay_findings != context_findings or any(
            item.finding_key.audit_target_id not in epoch.audit_target_ids
            for item in context.unresolved_findings
        ):
            raise Protocol25RuntimeError(
                "composed view finding authority is not the exact source cycle"
            )
        assessment_by_overlay = {
            item.resolution_overlay_hash: item for item in target_assessments
        }
        if set(assessment_by_overlay) != set(overlay_hashes) or any(
            set(assessment_by_overlay[item.identity].assessed_finding_ids)
            != set(item.finding_key_ids)
            or assessment_by_overlay[item.identity].audit_target_id
            != item.audit_target_id
            for item in overlays
        ):
            raise Protocol25RuntimeError(
                "composed view target assessments do not exactly bind overlays"
            )
        return ComposedSemanticViewV1(
            schema_version=1,
            audit_epoch_id=epoch.identity,
            source_id=source_id,
            lower_authority_hashes=context.lower_authority_hashes,
            active_sibling_authority_hashes=(
                context.active_sibling_authority_hashes
            ),
            overlays=tuple(
                sorted(
                    overlays,
                    key=lambda item: (
                        item.audit_target_id,
                        item.semantic_round,
                        item.identity,
                    ),
                )
            ),
            target_assessments=tuple(
                sorted(
                    target_assessments,
                    key=lambda item: (
                        item.audit_target_id,
                        item.resolution_overlay_hash,
                        item.identity,
                    ),
                )
            ),
        )

    def certify_source_guard(
        self,
        candidate: SemanticCandidateInputV1,
        *,
        artifact_key: ArtifactKeyV2,
        context: SemanticContextV1,
        epoch: AuditEpochV1,
        source_id: str,
        overlays: tuple[SemanticResolutionOverlayV1, ...],
        target_assessments: tuple[TargetClosureAssessmentV1, ...],
        composed_view: ComposedSemanticViewV1,
    ) -> SemanticCertificationResultV1:
        self._require_context(context, "SOURCE_COMPOSITION_GUARD")
        raw, normalized_payload = self._candidate_payload(
            candidate, "closure.json", "semantic-closure-assessment"
        )
        overlay_hashes = tuple(sorted(item.identity for item in overlays))
        assessment_hashes = tuple(sorted(item.identity for item in target_assessments))
        if (
            raw["assessment_kind"] != "source-composition"
            or raw["audit_epoch_id"] != epoch.identity
            or raw["source_id"] != source_id
            or tuple(sorted(raw["overlay_hashes"])) != overlay_hashes
            or tuple(sorted(raw["target_assessment_hashes"])) != assessment_hashes
        ):
            raise Protocol25RuntimeError("source guard input authority is not exact")
        if (
            not isinstance(composed_view, ComposedSemanticViewV1)
            or composed_view.audit_epoch_id != epoch.identity
            or composed_view.source_id != source_id
            or composed_view.overlay_hashes != overlay_hashes
            or composed_view.target_assessment_hashes != assessment_hashes
            or composed_view.lower_authority_hashes != context.lower_authority_hashes
            or composed_view.active_sibling_authority_hashes
            != context.active_sibling_authority_hashes
        ):
            raise Protocol25RuntimeError(
                "source guard composed authority is not exact"
            )
        implicated = tuple(sorted(raw["implicated_finding_ids"]))
        authorizing_findings = {
            finding_id for overlay in overlays for finding_id in overlay.finding_key_ids
        }
        if not set(implicated) <= authorizing_findings:
            raise Protocol25RuntimeError(
                "source guard implicated finding lacks an authorizing overlay"
            )
        if raw["outcome"] == "failed" and not implicated:
            raise Protocol25RuntimeError(
                "failed source guard must retain an authorizing finding open"
            )
        artifact = build_source_composition_assessment(
            epoch=epoch,
            schema_version=1,
            source_id=source_id,
            overlay_hashes=overlay_hashes,
            target_assessment_hashes=assessment_hashes,
            composed_authority_hash=composed_view.identity,
            implicated_finding_ids=implicated,
            deferred_observations=self._deferred_observations(
                raw["deferred_observations"], context
            ),
            outcome=str(raw["outcome"]),
        )
        self._require_artifact_key(
            artifact_key,
            "source-composition-assessment",
            context,
            (epoch.identity, *overlay_hashes, *assessment_hashes),
        )
        return self._certification_result(
            candidate,
            artifact_key,
            context,
            artifact,
            epoch.identity,
            normalized_payload,
        )

    def freeze_epoch(
        self,
        candidates: tuple[SemanticCertificationResultV1, ...],
        *,
        selection_id: str,
        audit_policy_hash: str,
        auditor_authority_hash: str,
        executor_authority_hash: str,
        verifier_authority_hash: str,
        audited_l2_root_hashes: tuple[str, ...],
    ) -> AuditEpochV1:
        if not candidates:
            raise Protocol25RuntimeError("audit epoch requires accepted candidates")
        if verifier_authority_hash != self.verifier_authority_hash:
            raise Protocol25RuntimeError(
                "audit epoch verifier authority differs from certified candidates"
            )
        artifacts = []
        authorities = []
        for result in candidates:
            if (
                not isinstance(result, SemanticCertificationResultV1)
                or not isinstance(result.artifact, AuditCandidateV1)
                or result.certification.verdict != "accepted"
            ):
                raise Protocol25RuntimeError("audit epoch requires certified audit candidates")
            artifact = result.artifact
            artifact_hash = content_digest(result.artifact_bytes)
            if (
                result.artifact_bytes
                != canonical_json_bytes(artifact.to_json_dict())
                or result.certification.artifact_hash != artifact_hash
                or result.certification.artifact_key_id
                != artifact.artifact_key.identity
                or result.certification.verifier_authority_hash
                != verifier_authority_hash
                or result.certification.audit_target_id
                != artifact.audit_target_id
                or result.acceptance.artifact_key != artifact.artifact_key
                or result.acceptance.artifact_hash != artifact_hash
                or result.acceptance.certification_receipt_id
                != result.certification.identity
                or result.candidate_assessment.artifact_hash != artifact_hash
                or result.candidate_assessment.certification_receipt_id
                != result.certification.identity
                or result.candidate_assessment.outcome != "certified"
                or result.candidate_assessment.normalized_authorial_payload_hash
                != content_digest(result.normalized_authorial_payload_bytes)
                or artifact.audit_target.audit_policy_hash != audit_policy_hash
                or artifact.audit_target.auditor_authority_hash
                != auditor_authority_hash
            ):
                raise Protocol25RuntimeError(
                    "audit candidate receipt chain is not exact"
                )
            artifacts.append(artifact)
            authorities.append(
                AuditTargetCandidateAuthorityV1(
                    schema_version=1,
                    audit_target_id=artifact.audit_target_id,
                    candidate_hash=artifact.identity,
                    certification_receipt_id=result.certification.identity,
                    acceptance_receipt_id=result.acceptance.identity,
                    finding_key_ids=tuple(
                        item.finding_key_id for item in artifact.findings
                    ),
                )
            )
        authorities = sorted(authorities, key=lambda item: item.audit_target_id)
        finding_ids = tuple(
            sorted(
                finding.finding_key_id
                for artifact in artifacts
                for finding in artifact.findings
            )
        )
        return AuditEpochV1(
            schema_version=1,
            selection_id=selection_id,
            audit_policy_hash=audit_policy_hash,
            target_candidate_authorities=tuple(authorities),
            auditor_authority_hash=auditor_authority_hash,
            executor_authority_hash=executor_authority_hash,
            verifier_authority_hash=verifier_authority_hash,
            finding_key_ids=finding_ids,
            audited_l2_root_hashes=audited_l2_root_hashes,
        )

    def build_closure_root(
        self,
        epoch: AuditEpochV1,
        *,
        latest_receipts: tuple[FindingClosureReceiptV1, ...],
        target_rounds: tuple[tuple[str, int], ...],
        plateau_counts: tuple[tuple[str, int], ...],
        deferred_observations: tuple[DeferredObservationV1, ...],
    ) -> AuditClosureRootV1:
        receipts = tuple(sorted(latest_receipts, key=lambda item: item.finding_key_id))
        return AuditClosureRootV1(
            schema_version=1,
            audit_epoch_id=epoch.identity,
            frozen_finding_ids=epoch.finding_key_ids,
            latest_closure_receipts=receipts,
            unresolved_finding_ids=tuple(
                item.finding_key_id for item in receipts if item.verdict == "open"
            ),
            target_rounds=target_rounds,
            plateau_counts=plateau_counts,
            deferred_observations=tuple(
                sorted(deferred_observations, key=lambda item: item.observation_id)
            ),
        )

    def build_source_root(
        self,
        *,
        source_id: str,
        selected_domain_keys: tuple[str, ...],
        full_source_coverage: bool,
        audit_target_ids: tuple[str, ...],
        closure_roots: tuple[AuditClosureRootV1, ...],
        adopted_l2_root_hash: str,
    ) -> L3SourceRootV1:
        unresolved = tuple(
            sorted(
                {
                    finding
                    for root in closure_roots
                    for finding in root.unresolved_finding_ids
                }
            )
        )
        deferred = tuple(
            sorted(
                {
                    observation.observation_id
                    for root in closure_roots
                    for observation in root.deferred_observations
                }
            )
        )
        state = "blocked" if unresolved else "next_epoch_required" if deferred else "complete"
        return L3SourceRootV1(
            schema_version=1,
            source_id=source_id,
            selected_domain_keys=selected_domain_keys,
            full_source_coverage=full_source_coverage,
            audit_target_ids=audit_target_ids,
            closure_root_hashes=tuple(sorted(root.identity for root in closure_roots)),
            adopted_l2_root_hash=adopted_l2_root_hash,
            unresolved_finding_ids=unresolved,
            deferred_observation_ids=deferred,
            state=state,
        )

    def _candidate_payload(
        self,
        candidate: SemanticCandidateInputV1,
        filename: str,
        schema_kind: str,
    ) -> tuple[Mapping[str, object], bytes]:
        if not isinstance(candidate, SemanticCandidateInputV1):
            raise Protocol25RuntimeError("semantic certification requires candidate input")
        entries = candidate.inventory.entries
        if (
            len(entries) != 1
            or entries[0].relative_path != filename
            or entries[0].object_kind != "regular"
            or entries[0].mode & 0o111
        ):
            raise Protocol25RuntimeError(
                f"candidate inventory must contain exactly one regular {filename}"
            )
        entry = entries[0]
        if (
            entry.byte_count != len(candidate.candidate_bytes)
            or entry.content_hash != content_digest(candidate.candidate_bytes)
        ):
            raise Protocol25RuntimeError("candidate inventory does not bind candidate bytes")
        policy_kind = {
            "semantic-audit-findings": "semantic-audit-findings",
            "semantic-resolution-overlay": "semantic-resolution-overlay",
            "semantic-closure-assessment": "target-closure-assessment",
        }[schema_kind]
        policy = self.artifact_policy.entry_for("L3", policy_kind)
        if len(candidate.candidate_bytes) > policy.max_canonical_json_bytes:
            raise Protocol25RuntimeError("semantic candidate exceeds its byte ceiling")
        try:
            raw = _strict_json(candidate.candidate_bytes)
            Draft202012Validator(semantic_response_schema(schema_kind)).validate(raw)
        except (ValueError, ValidationError) as exc:
            raise Protocol25RuntimeError(f"{filename} violates its closed response schema") from exc
        if not isinstance(raw, Mapping):  # pragma: no cover - schemas require object
            raise Protocol25RuntimeError(f"{filename} must contain a JSON object")
        normalized = canonical_json_bytes(raw)
        if len(normalized) > policy.max_canonical_json_bytes:
            raise Protocol25RuntimeError("semantic candidate exceeds its byte ceiling")
        return raw, normalized

    def _normalize_finding(
        self, value: Mapping[str, object], context: SemanticContextV1
    ) -> SemanticFindingV1:
        key = normalize_finding_key(
            vocabulary=context.vocabulary,
            audit_target=context.audit_target,
            rule_id=str(value["rule_id"]),
            finding_class=str(value["finding_class"]),
            subject_kind=str(value["subject_kind"]),
            subject_ref=str(value["subject_ref"]),
            claim_anchor_ids=value["claim_anchor_ids"],
            evidence_refs=self._evidence_anchor_ids(value["evidence"], context),
        )
        return SemanticFindingV1(
            schema_version=1,
            finding_key=key,
            title=self._prose(value["title"], "finding title", 256),
            explanation=self._prose(value["explanation"], "finding explanation", 4096),
            recommendation=self._prose(
                value["recommendation"], "finding recommendation", 4096
            ),
            repair_context=self._prose(
                value["repair_context"], "finding repair_context", 4096
            ),
        )

    def _deferred_observations(
        self, values: object, context: SemanticContextV1
    ) -> tuple[DeferredObservationV1, ...]:
        observations: dict[str, DeferredObservationV1] = {}
        for value in values:  # type: ignore[union-attr]
            key = normalize_finding_key(
                vocabulary=context.vocabulary,
                audit_target=context.audit_target,
                rule_id=str(value["rule_id"]),
                finding_class=str(value["finding_class"]),
                subject_kind=str(value["subject_kind"]),
                subject_ref=str(value["subject_ref"]),
                claim_anchor_ids=value["claim_anchor_ids"],
                evidence_refs=self._evidence_anchor_ids(value["evidence"], context),
            )
            observation = DeferredObservationV1(
                schema_version=1,
                audit_target_id=key.audit_target_id,
                authority_vocabulary_id=key.authority_vocabulary_id,
                rule_id=key.rule_id,
                finding_class=key.finding_class,
                subject_kind=key.subject_kind,
                subject_ref=key.subject_ref,
                claim_anchor_ids=key.claim_anchor_ids,
                evidence_anchor_ids=key.evidence_anchor_ids,
                audited_artifact_hashes=key.audited_artifact_hashes,
                diagnostic=self._prose(value["diagnostic"], "deferred diagnostic", 4096),
            )
            existing = observations.get(observation.observation_id)
            if existing is None or observation.payload_hash < existing.payload_hash:
                observations[observation.observation_id] = observation
        return tuple(observations[key] for key in sorted(observations))

    def _evidence_anchor_ids(
        self, values: object, context: SemanticContextV1
    ) -> tuple[str, ...]:
        ranges = {
            reference: item
            for item in context.authorized_evidence
            for reference in item.references
        }
        anchors: set[str] = set()
        for value in values:  # type: ignore[union-attr]
            reference = str(value["reference"])
            authority = ranges.get(reference)
            if authority is None or (
                value["path"] != authority.source_relative_path
                or int(value["start_line"]) < authority.start_line
                or int(value["end_line"]) > authority.end_line
                or int(value["start_line"]) > int(value["end_line"])
            ):
                raise Protocol25RuntimeError(
                    "candidate evidence is outside authorized evidence ranges"
                )
            anchors.add(authority.canonical_anchor_id)
        if not anchors:
            raise Protocol25RuntimeError("candidate requires authorized evidence")
        return tuple(sorted(anchors))

    @staticmethod
    def _issued_ids(values: object, allowed: set[str], label: str) -> tuple[str, ...]:
        result = tuple(sorted(values))  # type: ignore[arg-type]
        if len(result) != len(set(result)) or not set(result) <= allowed:
            raise Protocol25RuntimeError(f"{label} is not controller-issued")
        return result

    @staticmethod
    def _prose(value: object, field_name: str, maximum: int) -> str:
        if not isinstance(value, str):
            raise Protocol25RuntimeError(f"{field_name} must be text")
        text = unicodedata.normalize(
            "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
        ).strip()
        if (
            not text
            or len(text.encode("utf-8", errors="strict")) > maximum
            or any(
                unicodedata.category(character) == "Cc" and character != "\n"
                for character in text
            )
        ):
            raise Protocol25RuntimeError(f"{field_name} is not bounded normalized prose")
        return text

    def _certification_result(
        self,
        candidate: SemanticCandidateInputV1,
        artifact_key: ArtifactKeyV2,
        context: SemanticContextV1,
        artifact: object,
        audit_epoch_id: str | None,
        normalized_authorial_payload_bytes: bytes,
    ) -> SemanticCertificationResultV1:
        self._require_artifact_key(
            artifact_key,
            artifact_key.artifact_kind,
            context,
            artifact_key.dependency_hashes,
            exact_dependencies=False,
        )
        artifact_bytes = canonical_json_bytes(artifact.to_json_dict())  # type: ignore[attr-defined]
        policy = self.artifact_policy.entry_for("L3", artifact_key.artifact_kind)
        if len(artifact_bytes) > policy.max_canonical_json_bytes:
            raise Protocol25RuntimeError("semantic artifact exceeds its byte ceiling")
        artifact_hash = content_digest(artifact_bytes)
        certification = SemanticCertificationReceiptV1(
            schema_version=1,
            artifact_key_id=artifact_key.identity,
            artifact_hash=artifact_hash,
            verifier_authority_hash=self.verifier_authority_hash,
            audit_epoch_id=audit_epoch_id,
            audit_target_id=context.audit_target.identity,
            evidence_scope_hash=context.identity,
            verdict="accepted",
            normalized_diagnostics=(),
        )
        assessment = CandidateAssessmentReceiptV1(
            schema_version=1,
            candidate_id=candidate.candidate_id,
            work_item_id=candidate.inventory.work_item_id,
            execution_capture_hash=candidate.execution_capture_hash,
            normalized_authorial_payload_hash=content_digest(
                normalized_authorial_payload_bytes
            ),
            artifact_hash=artifact_hash,
            certification_receipt_id=certification.identity,
            outcome="certified",
            normalized_diagnostics=(),
        )
        acceptance = ArtifactAcceptanceReceiptV2(
            schema_version=2,
            artifact_key=artifact_key,
            artifact_hash=artifact_hash,
            certification_receipt_id=certification.identity,
        )
        return SemanticCertificationResultV1(
            artifact=artifact,
            artifact_bytes=artifact_bytes,
            normalized_authorial_payload_bytes=normalized_authorial_payload_bytes,
            certification=certification,
            candidate_assessment=assessment,
            acceptance=acceptance,
        )

    @staticmethod
    def _require_context(context: SemanticContextV1, mode: str) -> None:
        if not isinstance(context, SemanticContextV1) or context.mode != mode:
            raise Protocol25RuntimeError(f"semantic certification requires {mode} context")

    @staticmethod
    def _require_artifact_key(
        artifact_key: ArtifactKeyV2,
        artifact_kind: str,
        context: SemanticContextV1,
        dependencies: tuple[str, ...],
        *,
        exact_dependencies: bool = True,
    ) -> None:
        if (
            not isinstance(artifact_key, ArtifactKeyV2)
            or artifact_key.artifact_kind != artifact_kind
            or artifact_key.layer != "L3"
            or artifact_key.producer_protocol_version
            != SEMANTIC_PRODUCER_PROTOCOL_BY_ARTIFACT[artifact_kind]
            or artifact_key.scope != context.audit_target.scope
        ):
            raise Protocol25RuntimeError("semantic artifact key is invalid")
        if exact_dependencies and artifact_key.dependency_hashes != tuple(
            sorted(dependencies)
        ):
            raise Protocol25RuntimeError("semantic artifact dependency authority is not exact")


def _strict_json(payload: bytes) -> object:
    def pairs(values):  # type: ignore[no-untyped-def]
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        text = payload.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON value: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("candidate is not strict UTF-8 JSON") from exc


__all__ = (
    "AuthorizedEvidenceRangeV1",
    "BoundedAuthorityObjectV1",
    "ComposedSemanticViewV1",
    "Protocol25DeterministicRuntime",
    "Protocol25RuntimeError",
    "SemanticCandidateInputV1",
    "SemanticCertificationResultV1",
    "SemanticContextV1",
    "semantic_response_schema",
)
