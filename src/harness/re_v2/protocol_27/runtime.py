"""Deterministic validation and certification of synthesis candidates."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import ClassVar

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    one_of,
    safe_id,
)

from .context import SynthesisContextV1
from .model import SynthesisArtifactKeyV1, SynthesisScopeV1, SynthesisWorkItemV1
from .policies import SYNTHESIS_GENERATED_KINDS
from .schemas import synthesis_response_schema


_INPUT_QUALITIES = frozenset({"complete", "partial"})
_EVIDENCE_KINDS = frozenset({"authority-object", "dependency-artifact"})
MAX_SYNTHESIS_CANDIDATE_BYTES = 1_048_576


class Protocol27RuntimeError(RuntimeError):
    """Raised when synthesis output cannot become accepted authority."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol27RuntimeError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol27RuntimeError(str(exc)) from exc


def _text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise Protocol27RuntimeError(f"{field} must be nonempty text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise Protocol27RuntimeError(f"{field} must be UTF-8") from exc
    if len(encoded) > limit:
        raise Protocol27RuntimeError(f"{field} exceeds its byte ceiling")
    return value


def _digests(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise Protocol27RuntimeError(f"{field} must be an array")
    result = tuple(_schema(digest_value, item, field) for item in value)
    if result != tuple(sorted(set(result))):
        raise Protocol27RuntimeError(f"{field} must be sorted and unique")
    return result


@dataclass(frozen=True, slots=True)
class SynthesisSectionV1:
    section_id: str
    heading: str
    claim_ids: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = ("section_id", "heading", "claim_ids")

    def __post_init__(self) -> None:
        _schema(safe_id, self.section_id, "synthesis section ID")
        _text(self.heading, "synthesis section heading", 160)
        if not isinstance(self.claim_ids, (list, tuple)):
            raise Protocol27RuntimeError("synthesis section claim IDs must be an array")
        claims = tuple(
            _schema(safe_id, item, "synthesis section claim ID")
            for item in self.claim_ids
        )
        if not claims or len(claims) != len(set(claims)):
            raise Protocol27RuntimeError(
                "synthesis section claim IDs must be nonempty and unique"
            )
        object.__setattr__(self, "claim_ids", claims)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "heading": self.heading,
            "claim_ids": list(self.claim_ids),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisSectionV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        claims = raw["claim_ids"]
        if not isinstance(claims, (list, tuple)):
            raise Protocol27RuntimeError("synthesis section claim IDs must be an array")
        return cls(raw["section_id"], raw["heading"], tuple(claims))


@dataclass(frozen=True, slots=True)
class SynthesisEvidenceReferenceV1:
    authority_kind: str
    authority_id: str
    source_id: str | None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "authority_kind",
        "authority_id",
        "source_id",
    )

    def __post_init__(self) -> None:
        _schema(one_of, self.authority_kind, _EVIDENCE_KINDS, "evidence authority kind")
        _schema(digest_value, self.authority_id, "evidence authority ID")
        if self.source_id is not None:
            _schema(safe_id, self.source_id, "evidence source ID")

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisEvidenceReferenceV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SynthesisClaimV1:
    claim_id: str
    statement: str
    evidence: tuple[SynthesisEvidenceReferenceV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = ("claim_id", "statement", "evidence")

    def __post_init__(self) -> None:
        _schema(safe_id, self.claim_id, "synthesis claim ID")
        _text(self.statement, "synthesis claim statement", 4096)
        if not isinstance(self.evidence, (list, tuple)) or any(
            not isinstance(item, SynthesisEvidenceReferenceV1)
            for item in self.evidence
        ):
            raise Protocol27RuntimeError("synthesis claim evidence is invalid")
        evidence = tuple(sorted(self.evidence, key=lambda item: item.identity))
        if not evidence or len(evidence) != len({item.identity for item in evidence}):
            raise Protocol27RuntimeError("synthesis claim evidence must be nonempty and unique")
        object.__setattr__(self, "evidence", evidence)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "evidence": [item.to_json_dict() for item in self.evidence],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisClaimV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        evidence = raw["evidence"]
        if not isinstance(evidence, (list, tuple)):
            raise Protocol27RuntimeError("synthesis claim evidence must be an array")
        return cls(
            raw["claim_id"],
            raw["statement"],
            tuple(SynthesisEvidenceReferenceV1.from_json_dict(item) for item in evidence),
        )


@dataclass(frozen=True, slots=True)
class SynthesisCandidateV1:
    schema_version: int
    artifact_kind: str
    scope: SynthesisScopeV1
    sections: tuple[SynthesisSectionV1, ...]
    claims: tuple[SynthesisClaimV1, ...]
    input_quality: str
    debt_refs: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact_kind",
        "scope",
        "sections",
        "claims",
        "input_quality",
        "debt_refs",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "synthesis candidate schema")
        _schema(one_of, self.artifact_kind, SYNTHESIS_GENERATED_KINDS, "artifact kind")
        if not isinstance(self.scope, SynthesisScopeV1):
            raise Protocol27RuntimeError("synthesis candidate scope is invalid")
        if not isinstance(self.sections, (list, tuple)) or any(
            not isinstance(item, SynthesisSectionV1) for item in self.sections
        ):
            raise Protocol27RuntimeError("synthesis candidate sections are invalid")
        if not isinstance(self.claims, (list, tuple)) or any(
            not isinstance(item, SynthesisClaimV1) for item in self.claims
        ):
            raise Protocol27RuntimeError("synthesis candidate claims are invalid")
        sections = tuple(self.sections)
        claims = tuple(self.claims)
        section_ids = tuple(item.section_id for item in sections)
        claim_ids = tuple(item.claim_id for item in claims)
        if not sections or len(section_ids) != len(set(section_ids)):
            raise Protocol27RuntimeError("synthesis sections must be nonempty and unique")
        if not claims or len(claim_ids) != len(set(claim_ids)):
            raise Protocol27RuntimeError("synthesis claim IDs must be nonempty and unique")
        referenced_claims = {
            claim_id for section in sections for claim_id in section.claim_ids
        }
        if referenced_claims != set(claim_ids):
            raise Protocol27RuntimeError(
                "synthesis sections must collectively reference every candidate claim by ID"
            )
        _schema(one_of, self.input_quality, _INPUT_QUALITIES, "candidate input quality")
        object.__setattr__(self, "sections", sections)
        object.__setattr__(self, "claims", claims)
        object.__setattr__(
            self,
            "debt_refs",
            _digests(self.debt_refs, "candidate debt references"),
        )

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_kind": self.artifact_kind,
            "scope": self.scope.to_json_dict(),
            "sections": [item.to_json_dict() for item in self.sections],
            "claims": [item.to_json_dict() for item in self.claims],
            "input_quality": self.input_quality,
            "debt_refs": list(self.debt_refs),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisCandidateV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        if not isinstance(raw["sections"], (list, tuple)) or not isinstance(
            raw["claims"], (list, tuple)
        ):
            raise Protocol27RuntimeError("candidate sections/claims must be arrays")
        return cls(
            schema_version=raw["schema_version"],
            artifact_kind=raw["artifact_kind"],
            scope=SynthesisScopeV1.from_json_dict(raw["scope"]),
            sections=tuple(
                SynthesisSectionV1.from_json_dict(item) for item in raw["sections"]
            ),
            claims=tuple(SynthesisClaimV1.from_json_dict(item) for item in raw["claims"]),
            input_quality=raw["input_quality"],
            debt_refs=tuple(raw["debt_refs"]),
        )


@dataclass(frozen=True, slots=True)
class SynthesisAssessmentV1:
    schema_version: int
    candidate_hash: str
    work_item_id: str
    context_id: str
    outcome: str
    normalized_diagnostics: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "candidate_hash",
        "work_item_id",
        "context_id",
        "outcome",
        "normalized_diagnostics",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "synthesis assessment schema")
        for field in ("candidate_hash", "work_item_id", "context_id"):
            _schema(digest_value, getattr(self, field), f"synthesis assessment {field}")
        _schema(literal, self.outcome, "certified", "synthesis assessment outcome")
        diagnostics = tuple(self.normalized_diagnostics)
        if diagnostics:
            raise Protocol27RuntimeError("certified synthesis assessment has diagnostics")
        object.__setattr__(self, "normalized_diagnostics", diagnostics)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_hash": self.candidate_hash,
            "work_item_id": self.work_item_id,
            "context_id": self.context_id,
            "outcome": self.outcome,
            "normalized_diagnostics": list(self.normalized_diagnostics),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisAssessmentV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        diagnostics = raw["normalized_diagnostics"]
        if not isinstance(diagnostics, (list, tuple)):
            raise Protocol27RuntimeError("synthesis assessment diagnostics must be an array")
        return cls(
            raw["schema_version"],
            raw["candidate_hash"],
            raw["work_item_id"],
            raw["context_id"],
            raw["outcome"],
            tuple(diagnostics),
        )


@dataclass(frozen=True, slots=True)
class SynthesisCertificationV1:
    schema_version: int
    artifact_key_id: str
    artifact_hash: str
    candidate_hash: str
    context_id: str
    verifier_id: str
    verifier_version: str
    verifier_authority_hash: str
    verdict: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact_key_id",
        "artifact_hash",
        "candidate_hash",
        "context_id",
        "verifier_id",
        "verifier_version",
        "verifier_authority_hash",
        "verdict",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "synthesis certification schema")
        for field in (
            "artifact_key_id",
            "artifact_hash",
            "candidate_hash",
            "context_id",
            "verifier_authority_hash",
        ):
            _schema(digest_value, getattr(self, field), f"synthesis certification {field}")
        _schema(safe_id, self.verifier_id, "synthesis certification verifier")
        _schema(safe_id, self.verifier_version, "synthesis certification version")
        _schema(literal, self.verdict, "accepted", "synthesis certification verdict")

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_key_id": self.artifact_key_id,
            "artifact_hash": self.artifact_hash,
            "candidate_hash": self.candidate_hash,
            "context_id": self.context_id,
            "verifier_id": self.verifier_id,
            "verifier_version": self.verifier_version,
            "verifier_authority_hash": self.verifier_authority_hash,
            "verdict": self.verdict,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisCertificationV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SynthesisArtifactAcceptanceV1:
    schema_version: int
    work_item_id: str
    artifact_key: SynthesisArtifactKeyV1
    artifact_hash: str
    certification_id: str
    input_quality: str
    debt_refs: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "work_item_id",
        "artifact_key",
        "artifact_hash",
        "certification_id",
        "input_quality",
        "debt_refs",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "synthesis acceptance schema")
        _schema(digest_value, self.work_item_id, "synthesis acceptance work item")
        if not isinstance(self.artifact_key, SynthesisArtifactKeyV1):
            raise Protocol27RuntimeError("synthesis acceptance artifact key is invalid")
        _schema(digest_value, self.artifact_hash, "synthesis acceptance artifact hash")
        _schema(digest_value, self.certification_id, "synthesis acceptance certification")
        debts = _digests(self.debt_refs, "synthesis acceptance debt references")
        if debts != self.artifact_key.debt_manifest_hashes:
            raise Protocol27RuntimeError("synthesis acceptance debt authority mismatch")
        expected_quality = "partial" if debts else "complete"
        if self.input_quality != expected_quality:
            raise Protocol27RuntimeError("synthesis acceptance input quality mismatch")
        object.__setattr__(self, "debt_refs", debts)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "work_item_id": self.work_item_id,
            "artifact_key": self.artifact_key.to_json_dict(),
            "artifact_hash": self.artifact_hash,
            "certification_id": self.certification_id,
            "input_quality": self.input_quality,
            "debt_refs": list(self.debt_refs),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisArtifactAcceptanceV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        debts = raw["debt_refs"]
        if not isinstance(debts, (list, tuple)):
            raise Protocol27RuntimeError("synthesis acceptance debts must be an array")
        return cls(
            schema_version=raw["schema_version"],
            work_item_id=raw["work_item_id"],
            artifact_key=SynthesisArtifactKeyV1.from_json_dict(raw["artifact_key"]),
            artifact_hash=raw["artifact_hash"],
            certification_id=raw["certification_id"],
            input_quality=raw["input_quality"],
            debt_refs=tuple(debts),
        )


@dataclass(frozen=True, slots=True)
class SynthesisCertificationResultV1:
    candidate: SynthesisCandidateV1
    artifact_bytes: bytes
    assessment: SynthesisAssessmentV1
    certification: SynthesisCertificationV1
    acceptance: SynthesisArtifactAcceptanceV1


class Protocol27DeterministicRuntime:
    def __init__(self, object_store: ObjectStore) -> None:
        if not isinstance(object_store, ObjectStore):
            raise Protocol27RuntimeError("synthesis runtime requires an object store")
        self.object_store = object_store

    def certify_candidate(
        self,
        work_item: SynthesisWorkItemV1,
        context: SynthesisContextV1,
        payload: bytes,
    ) -> SynthesisCertificationResultV1:
        self._validate_authority(work_item, context)
        if not isinstance(payload, bytes):
            raise Protocol27RuntimeError("synthesis candidate payload must be bytes")
        if len(payload) > MAX_SYNTHESIS_CANDIDATE_BYTES:
            raise Protocol27RuntimeError("synthesis candidate exceeds its byte ceiling")
        candidate_hash = content_digest(payload)
        raw = _strict_json(payload)
        try:
            Draft202012Validator(
                synthesis_response_schema(work_item.output_key.artifact_kind)
            ).validate(raw)
        except ValidationError as exc:
            field = ".".join(str(item) for item in exc.absolute_path)
            label = f" at {field}" if field else ""
            raise Protocol27RuntimeError(
                f"synthesis candidate violates response schema{label}: {exc.message}"
            ) from exc
        candidate = SynthesisCandidateV1.from_json_dict(raw)
        self._validate_candidate(work_item, context, candidate)
        artifact_bytes = canonical_json_bytes(candidate.to_json_dict())
        artifact_hash = self.object_store.put_blob(artifact_bytes)
        if artifact_hash != content_digest(artifact_bytes):
            raise Protocol27RuntimeError("stored synthesis artifact identity changed")
        assessment = SynthesisAssessmentV1(
            1,
            candidate_hash,
            work_item.work_item_id,
            context.identity,
            "certified",
            (),
        )
        certification = SynthesisCertificationV1(
            1,
            work_item.output_key.artifact_key_id,
            artifact_hash,
            candidate_hash,
            context.identity,
            work_item.verifier_id,
            work_item.verifier_version,
            work_item.verifier_authority_hash,
            "accepted",
        )
        acceptance = SynthesisArtifactAcceptanceV1(
            1,
            work_item.work_item_id,
            work_item.output_key,
            artifact_hash,
            certification.identity,
            context.input_quality,
            context.debt_refs,
        )
        return SynthesisCertificationResultV1(
            candidate,
            artifact_bytes,
            assessment,
            certification,
            acceptance,
        )

    @staticmethod
    def _validate_authority(
        work_item: SynthesisWorkItemV1,
        context: SynthesisContextV1,
    ) -> None:
        if not isinstance(work_item, SynthesisWorkItemV1) or not isinstance(
            context, SynthesisContextV1
        ):
            raise Protocol27RuntimeError("synthesis runtime authority is invalid")
        key = work_item.output_key
        if (
            context.work_item_id != work_item.work_item_id
            or context.artifact_key_id != key.artifact_key_id
            or context.artifact_kind != key.artifact_kind
            or context.scope != key.scope
            or context.response_schema_hash != key.response_schema_hash
            or context.context_policy_hash != key.context_policy_hash
            or tuple(item.artifact_key_id for item in context.dependency_artifacts)
            != work_item.dependency_key_ids
        ):
            raise Protocol27RuntimeError("synthesis context and work item authority disagree")

    @staticmethod
    def _validate_candidate(
        work_item: SynthesisWorkItemV1,
        context: SynthesisContextV1,
        candidate: SynthesisCandidateV1,
    ) -> None:
        if candidate.artifact_kind != work_item.output_key.artifact_kind:
            raise Protocol27RuntimeError("synthesis candidate artifact kind mismatch")
        if candidate.scope != work_item.output_key.scope:
            raise Protocol27RuntimeError("synthesis candidate scope mismatch")
        if tuple(item.section_id for item in candidate.sections) != (
            context.public_contract.required_section_ids
        ):
            raise Protocol27RuntimeError("synthesis candidate sections mismatch")
        if candidate.input_quality != context.input_quality:
            if context.input_quality == "partial" and candidate.input_quality == "complete":
                raise Protocol27RuntimeError(
                    "synthesis candidate cannot claim full quality over partial input"
                )
            raise Protocol27RuntimeError("synthesis candidate input quality mismatch")
        if candidate.debt_refs != context.debt_refs:
            raise Protocol27RuntimeError("synthesis candidate debt references mismatch")
        authority = {
            ("authority-object", item.object_hash): set(item.source_ids)
            for item in context.authorized_objects
        }
        authority.update(
            {
                ("dependency-artifact", item.artifact_hash): set(item.source_ids)
                for item in context.dependency_artifacts
            }
        )
        for claim in candidate.claims:
            for reference in claim.evidence:
                sources = authority.get((reference.authority_kind, reference.authority_id))
                if sources is None:
                    raise Protocol27RuntimeError(
                        f"synthesis candidate citation is unauthorized: {reference.authority_id}"
                    )
                if reference.source_id is not None and reference.source_id not in sources:
                    raise Protocol27RuntimeError(
                        "synthesis candidate citation source is unauthorized"
                    )


def _strict_json(payload: bytes) -> object:
    def pairs(values):  # type: ignore[no-untyped-def]
        result = {}
        for key, value in values:
            if key in result:
                raise Protocol27RuntimeError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        text = payload.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                Protocol27RuntimeError(f"non-finite JSON value: {value}")
            ),
        )
    except Protocol27RuntimeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Protocol27RuntimeError("candidate is not strict UTF-8 JSON") from exc


__all__ = (
    "MAX_SYNTHESIS_CANDIDATE_BYTES",
    "Protocol27DeterministicRuntime",
    "Protocol27RuntimeError",
    "SynthesisArtifactAcceptanceV1",
    "SynthesisAssessmentV1",
    "SynthesisCandidateV1",
    "SynthesisCertificationResultV1",
    "SynthesisCertificationV1",
    "SynthesisClaimV1",
    "SynthesisEvidenceReferenceV1",
    "SynthesisSectionV1",
)
