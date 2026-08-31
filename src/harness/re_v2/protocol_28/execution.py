"""Durable L4 provider captures and controller-owned acceptance authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Callable, ClassVar, Literal, Protocol, TypeVar

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    boolean,
    digest_value,
    exact_object,
    literal,
    one_of,
    optional_digest,
    optional_text,
    positive_int,
    safe_id,
    text_value,
    utc_timestamp,
)
from harness.re_v2.protocol_28.artifacts import (
    ExhaustiveEvidenceSliceV1,
    ExhaustiveVerificationV1,
    validate_candidate,
    validate_verification,
)
from harness.re_v2.protocol_28.evidence import SnapshotEvidenceCatalogV1
from harness.re_v2.protocol_28.graph import AcceptedExhaustiveSliceV1
from harness.re_v2.protocol_28.planning import SlicePlanEntryV1, SliceSpecV1
from harness.re_v2.protocol_28.policies import ExhaustivePolicyV1


_ROLES = frozenset({"producer", "verifier"})
_RESULT_KINDS = frozenset({"provider_result", "provider_failure"})
_T = TypeVar("_T")


class Protocol28ExecutionError(Protocol22SchemaError):
    """Raised when provider evidence cannot become trusted L4 authority."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol28ExecutionError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol28ExecutionError(str(exc)) from exc


def _identity(value: object) -> str:
    return content_digest(canonical_json_bytes(value))


class _L4Ledger(Protocol):
    def record_execution_capture(
        self, envelope: "L4ExecutionEnvelopeV1", capture: "L4ExecutionCaptureV1"
    ) -> object: ...

    def record_candidate(self, receipt: "L4CandidateReceiptV1") -> object: ...

    def record_verification(self, receipt: "L4VerificationReceiptV1") -> object: ...

    def record_certification(self, receipt: "L4CertificationReceiptV1") -> object: ...

    def record_acceptance(self, receipt: "L4AcceptanceReceiptV1") -> object: ...

    def record_accepted_slice(self, accepted: AcceptedExhaustiveSliceV1) -> object: ...


@dataclass(frozen=True, slots=True)
class L4ExecutionEnvelopeV1:
    schema_version: int
    dispatch_id: str
    role: Literal["producer", "verifier"]
    slice_spec_id: str
    plan_entry_id: str
    attempt_number: int
    agent_contract_hash: str
    context_bundle_hash: str
    provider_request_hash: str
    candidate_id: str | None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "dispatch_id",
        "role",
        "slice_spec_id",
        "plan_entry_id",
        "attempt_number",
        "agent_contract_hash",
        "context_bundle_hash",
        "provider_request_hash",
        "candidate_id",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "L4ExecutionEnvelopeV1.schema_version")
        _schema(safe_id, self.dispatch_id, "L4ExecutionEnvelopeV1.dispatch_id")
        _schema(one_of, self.role, _ROLES, "L4ExecutionEnvelopeV1.role")
        for field in (
            "slice_spec_id",
            "plan_entry_id",
            "agent_contract_hash",
            "context_bundle_hash",
            "provider_request_hash",
        ):
            _schema(digest_value, getattr(self, field), f"L4ExecutionEnvelopeV1.{field}")
        _schema(positive_int, self.attempt_number, "L4ExecutionEnvelopeV1.attempt_number")
        _schema(optional_digest, self.candidate_id, "L4ExecutionEnvelopeV1.candidate_id")
        if self.role == "producer" and self.candidate_id is not None:
            raise Protocol28ExecutionError("producer envelope cannot claim a candidate")
        if self.role == "verifier" and self.candidate_id is None:
            raise Protocol28ExecutionError("verifier envelope requires a candidate")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "L4ExecutionEnvelopeV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class L4ExecutionCaptureV1:
    schema_version: int
    execution_envelope_id: str
    dispatch_id: str
    role: Literal["producer", "verifier"]
    raw_result_hash: str
    raw_byte_count: int
    result_kind: Literal["provider_result", "provider_failure"]
    provider_name: str
    model_revision: str | None
    started_at: str
    ended_at: str
    duration_ms: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "execution_envelope_id",
        "dispatch_id",
        "role",
        "raw_result_hash",
        "raw_byte_count",
        "result_kind",
        "provider_name",
        "model_revision",
        "started_at",
        "ended_at",
        "duration_ms",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "L4ExecutionCaptureV1.schema_version")
        _schema(digest_value, self.execution_envelope_id, "L4ExecutionCaptureV1.execution_envelope_id")
        _schema(safe_id, self.dispatch_id, "L4ExecutionCaptureV1.dispatch_id")
        _schema(one_of, self.role, _ROLES, "L4ExecutionCaptureV1.role")
        _schema(digest_value, self.raw_result_hash, "L4ExecutionCaptureV1.raw_result_hash")
        if not isinstance(self.raw_byte_count, int) or isinstance(self.raw_byte_count, bool) or self.raw_byte_count < 0:
            raise Protocol28ExecutionError("L4ExecutionCaptureV1.raw_byte_count must be nonnegative")
        _schema(one_of, self.result_kind, _RESULT_KINDS, "L4ExecutionCaptureV1.result_kind")
        _schema(text_value, self.provider_name, "L4ExecutionCaptureV1.provider_name")
        _schema(optional_text, self.model_revision, "L4ExecutionCaptureV1.model_revision")
        _schema(utc_timestamp, self.started_at, "L4ExecutionCaptureV1.started_at")
        _schema(utc_timestamp, self.ended_at, "L4ExecutionCaptureV1.ended_at")
        started = datetime.fromisoformat(self.started_at[:-1] + "+00:00")
        ended = datetime.fromisoformat(self.ended_at[:-1] + "+00:00")
        if ended < started:
            raise Protocol28ExecutionError(
                "L4ExecutionCaptureV1 wall-clock interval is reversed"
            )
        if not isinstance(self.duration_ms, int) or isinstance(self.duration_ms, bool) or self.duration_ms < 0:
            raise Protocol28ExecutionError("L4ExecutionCaptureV1.duration_ms must be nonnegative")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "L4ExecutionCaptureV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class PersistedL4ExecutionV1:
    envelope: L4ExecutionEnvelopeV1
    capture: L4ExecutionCaptureV1

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, L4ExecutionEnvelopeV1) or not isinstance(
            self.capture, L4ExecutionCaptureV1
        ):
            raise Protocol28ExecutionError("persisted execution requires typed envelope and capture")
        if (
            self.capture.execution_envelope_id != self.envelope.identity
            or self.capture.dispatch_id != self.envelope.dispatch_id
            or self.capture.role != self.envelope.role
        ):
            raise Protocol28ExecutionError("capture does not authenticate its execution envelope")


@dataclass(frozen=True, slots=True)
class L4CandidateReceiptV1:
    schema_version: int
    slice_spec_id: str
    plan_entry_id: str
    candidate_hash: str
    producer_execution_capture_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "slice_spec_id", "plan_entry_id", "candidate_hash",
        "producer_execution_capture_hash",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "L4CandidateReceiptV1.schema_version")
        for field in self.FIELDS[1:]:
            _schema(digest_value, getattr(self, field), f"L4CandidateReceiptV1.{field}")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "L4CandidateReceiptV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class L4VerificationReceiptV1:
    schema_version: int
    slice_spec_id: str
    plan_entry_id: str
    candidate_id: str
    verifier_result_hash: str
    verifier_execution_capture_hash: str
    verdict: Literal["PASS", "REPAIR"]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "slice_spec_id", "plan_entry_id", "candidate_id",
        "verifier_result_hash", "verifier_execution_capture_hash", "verdict",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "L4VerificationReceiptV1.schema_version")
        for field in self.FIELDS[1:6]:
            _schema(digest_value, getattr(self, field), f"L4VerificationReceiptV1.{field}")
        _schema(one_of, self.verdict, frozenset({"PASS", "REPAIR"}), "L4VerificationReceiptV1.verdict")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "L4VerificationReceiptV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class L4CertificationReceiptV1:
    schema_version: int
    slice_spec_id: str
    plan_entry_id: str
    output_artifact_key_id: str
    candidate_hash: str
    producer_execution_capture_hash: str
    verifier_result_hash: str
    verifier_execution_capture_hash: str
    scope_verified: bool
    evidence_verified: bool
    verdict: Literal["accepted"]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "slice_spec_id", "plan_entry_id", "output_artifact_key_id",
        "candidate_hash", "producer_execution_capture_hash", "verifier_result_hash",
        "verifier_execution_capture_hash", "scope_verified", "evidence_verified", "verdict",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "L4CertificationReceiptV1.schema_version")
        for field in self.FIELDS[1:8]:
            _schema(digest_value, getattr(self, field), f"L4CertificationReceiptV1.{field}")
        _schema(boolean, self.scope_verified, "L4CertificationReceiptV1.scope_verified")
        _schema(boolean, self.evidence_verified, "L4CertificationReceiptV1.evidence_verified")
        if not self.scope_verified or not self.evidence_verified:
            raise Protocol28ExecutionError("accepted certification requires verified scope and evidence")
        _schema(literal, self.verdict, "accepted", "L4CertificationReceiptV1.verdict")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "L4CertificationReceiptV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class L4AcceptanceReceiptV1:
    schema_version: int
    slice_spec_id: str
    output_artifact_key_id: str
    candidate_hash: str
    certification_receipt_hash: str
    verdict: Literal["accepted"]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version", "slice_spec_id", "output_artifact_key_id", "candidate_hash",
        "certification_receipt_hash", "verdict",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "L4AcceptanceReceiptV1.schema_version")
        for field in self.FIELDS[1:5]:
            _schema(digest_value, getattr(self, field), f"L4AcceptanceReceiptV1.{field}")
        _schema(literal, self.verdict, "accepted", "L4AcceptanceReceiptV1.verdict")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "L4AcceptanceReceiptV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


def persist_provider_result(
    object_store: ObjectStore,
    envelope: L4ExecutionEnvelopeV1,
    raw_result: bytes,
    *,
    provider_name: str,
    model_revision: str | None,
    started_at: str,
    ended_at: str,
    duration_ms: int,
    result_kind: Literal["provider_result", "provider_failure"] = "provider_result",
    ledger: _L4Ledger | None = None,
    fault: Callable[[str], None] | None = None,
) -> PersistedL4ExecutionV1:
    """Capture raw provider bytes before publishing or parsing any result authority."""
    if not isinstance(object_store, ObjectStore):
        raise Protocol28ExecutionError("provider capture requires an object store")
    if not isinstance(envelope, L4ExecutionEnvelopeV1):
        raise Protocol28ExecutionError("provider capture requires an execution envelope")
    if not isinstance(raw_result, bytes):
        raise Protocol28ExecutionError("raw provider result must be bytes")
    if fault is not None:
        fault("before_raw_result")
    raw_hash = object_store.put_blob(raw_result)
    if fault is not None:
        fault("raw_result_durable")
    envelope_hash = object_store.put_blob(canonical_json_bytes(envelope.to_json_dict()))
    if envelope_hash != envelope.identity:
        raise Protocol28ExecutionError("execution envelope object identity mismatch")
    capture = L4ExecutionCaptureV1(
        1,
        envelope.identity,
        envelope.dispatch_id,
        envelope.role,
        raw_hash,
        len(raw_result),
        result_kind,
        provider_name,
        model_revision,
        started_at,
        ended_at,
        duration_ms,
    )
    capture_hash = object_store.put_blob(canonical_json_bytes(capture.to_json_dict()))
    if capture_hash != capture.identity:
        raise Protocol28ExecutionError("execution capture object identity mismatch")
    if fault is not None:
        fault("capture_durable")
    persisted = PersistedL4ExecutionV1(envelope, capture)
    if ledger is not None:
        ledger.record_execution_capture(envelope, capture)
        if fault is not None:
            fault("ledger_appended")
    return persisted


def parse_captured_result(
    object_store: ObjectStore,
    capture: L4ExecutionCaptureV1,
    parser: Callable[[bytes], _T],
    *,
    fault: Callable[[str], None] | None = None,
) -> _T:
    """Parse only bytes authenticated by an already-durable execution capture."""
    if not isinstance(capture, L4ExecutionCaptureV1):
        raise Protocol28ExecutionError("captured parsing requires L4ExecutionCaptureV1")
    if not callable(parser):
        raise Protocol28ExecutionError("captured parsing requires a parser")
    raw = object_store.read_blob(capture.raw_result_hash)
    if len(raw) != capture.raw_byte_count:
        raise Protocol28ExecutionError("captured raw byte count mismatch")
    if fault is not None:
        fault("before_parse")
    result = parser(raw)
    if fault is not None:
        fault("after_parse")
    return result


def certify_and_accept(
    object_store: ObjectStore,
    ledger: _L4Ledger,
    slice_spec: SliceSpecV1,
    plan_entry: SlicePlanEntryV1,
    evidence_catalog: SnapshotEvidenceCatalogV1,
    policy: ExhaustivePolicyV1,
    candidate: ExhaustiveEvidenceSliceV1,
    verification: ExhaustiveVerificationV1,
    producer: PersistedL4ExecutionV1,
    verifier: PersistedL4ExecutionV1,
    *,
    fault: Callable[[str], None] | None = None,
) -> AcceptedExhaustiveSliceV1:
    """Mint accepted L4 authority only from a closed candidate and independent PASS."""
    if verification.verdict != "PASS":
        raise Protocol28ExecutionError("L4 acceptance requires a controller-validated PASS")
    try:
        raw_candidate = parse_captured_result(
            object_store, producer.capture, decode_provider_result_object
        )
    except Protocol28ExecutionError as exc:
        raise Protocol28ExecutionError(
            f"producer capture does not contain a valid candidate: {exc}"
        ) from exc
    if raw_candidate != candidate.to_json_dict():
        raise Protocol28ExecutionError(
            "producer capture does not contain the candidate presented for acceptance"
        )
    try:
        raw_verification = parse_captured_result(
            object_store, verifier.capture, decode_provider_result_object
        )
    except Protocol28ExecutionError as exc:
        raise Protocol28ExecutionError(
            f"verifier capture does not contain a valid verification: {exc}"
        ) from exc
    if raw_verification != verification.to_json_dict():
        raise Protocol28ExecutionError(
            "verifier capture does not contain the verification presented for acceptance"
        )
    validated_candidate = validate_candidate(
        slice_spec, plan_entry, evidence_catalog, raw_candidate, policy
    )
    validated_verification = validate_verification(
        slice_spec, plan_entry, validated_candidate, raw_verification
    )
    _validate_independent_executions(
        slice_spec, plan_entry, validated_candidate, producer, verifier
    )

    if fault is not None:
        fault("before_candidate_and_verification_objects")
    candidate_hash = object_store.put_blob(canonical_json_bytes(validated_candidate.to_json_dict()))
    verification_hash = object_store.put_blob(canonical_json_bytes(validated_verification.to_json_dict()))
    if fault is not None:
        fault("candidate_and_verification_objects_durable")

    candidate_receipt = L4CandidateReceiptV1(
        1, slice_spec.identity, plan_entry.identity, candidate_hash, producer.capture.identity
    )
    ledger.record_candidate(candidate_receipt)
    verification_receipt = L4VerificationReceiptV1(
        1,
        slice_spec.identity,
        plan_entry.identity,
        candidate_hash,
        verification_hash,
        verifier.capture.identity,
        "PASS",
    )
    ledger.record_verification(verification_receipt)
    if fault is not None:
        fault("candidate_and_verification_recorded")

    if fault is not None:
        fault("before_certification")
    certification = L4CertificationReceiptV1(
        1,
        slice_spec.identity,
        plan_entry.identity,
        slice_spec.output_artifact_key_id,
        candidate_hash,
        producer.capture.identity,
        verification_hash,
        verifier.capture.identity,
        True,
        True,
        "accepted",
    )
    certification_hash = object_store.put_blob(canonical_json_bytes(certification.to_json_dict()))
    if certification_hash != certification.identity:
        raise Protocol28ExecutionError("certification object identity mismatch")
    if fault is not None:
        fault("certification_durable")
    ledger.record_certification(certification)
    if fault is not None:
        fault("certification_recorded")

    if fault is not None:
        fault("before_acceptance")
    acceptance = L4AcceptanceReceiptV1(
        1,
        slice_spec.identity,
        slice_spec.output_artifact_key_id,
        candidate_hash,
        certification.identity,
        "accepted",
    )
    acceptance_hash = object_store.put_blob(canonical_json_bytes(acceptance.to_json_dict()))
    if acceptance_hash != acceptance.identity:
        raise Protocol28ExecutionError("acceptance object identity mismatch")
    if fault is not None:
        fault("acceptance_durable")
    ledger.record_acceptance(acceptance)
    if fault is not None:
        fault("acceptance_recorded")

    if fault is not None:
        fault("before_accepted_slice")
    accepted = AcceptedExhaustiveSliceV1(
        1,
        plan_entry.identity,
        slice_spec.identity,
        slice_spec.output_artifact_key_id,
        candidate_hash,
        producer.capture.identity,
        verification_hash,
        verifier.capture.identity,
        certification.identity,
        acceptance.identity,
        validated_candidate.addressed_finding_ids,
        "PASS",
    )
    accepted_hash = object_store.put_blob(canonical_json_bytes(accepted.to_json_dict()))
    if accepted_hash != accepted.identity:
        raise Protocol28ExecutionError("accepted slice object identity mismatch")
    if fault is not None:
        fault("accepted_slice_durable")
    ledger.record_accepted_slice(accepted)
    if fault is not None:
        fault("accepted_slice_recorded")
    return accepted


def _validate_independent_executions(
    slice_spec: SliceSpecV1,
    plan_entry: SlicePlanEntryV1,
    candidate: ExhaustiveEvidenceSliceV1,
    producer: PersistedL4ExecutionV1,
    verifier: PersistedL4ExecutionV1,
) -> None:
    if not isinstance(producer, PersistedL4ExecutionV1) or not isinstance(
        verifier, PersistedL4ExecutionV1
    ):
        raise Protocol28ExecutionError("L4 certification requires persisted producer and verifier executions")
    if producer.envelope.role != "producer" or verifier.envelope.role != "verifier":
        raise Protocol28ExecutionError("L4 certification requires producer then verifier roles")
    if (
        producer.capture.result_kind != "provider_result"
        or verifier.capture.result_kind != "provider_result"
    ):
        raise Protocol28ExecutionError(
            "L4 certification requires successful producer and verifier results"
        )
    for envelope in (producer.envelope, verifier.envelope):
        if envelope.slice_spec_id != slice_spec.identity or envelope.plan_entry_id != plan_entry.identity:
            raise Protocol28ExecutionError("execution envelope does not match frozen slice")
    if producer.envelope.agent_contract_hash != plan_entry.producer_contract_hash:
        raise Protocol28ExecutionError("producer execution uses the wrong agent contract")
    if verifier.envelope.agent_contract_hash != plan_entry.verifier_contract_hash:
        raise Protocol28ExecutionError("verifier execution uses the wrong agent contract")
    if verifier.envelope.candidate_id != candidate.identity:
        raise Protocol28ExecutionError("verifier execution does not bind the candidate")
    if (
        producer.envelope.dispatch_id == verifier.envelope.dispatch_id
        or producer.envelope.context_bundle_hash == verifier.envelope.context_bundle_hash
        or producer.envelope.provider_request_hash == verifier.envelope.provider_request_hash
    ):
        raise Protocol28ExecutionError("verifier requires a fresh independent context")


def decode_provider_result_object(raw: bytes) -> object:
    """Decode one provider JSON object while rejecting duplicate/non-finite values."""
    def pairs_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Protocol28ExecutionError(
                    f"provider result contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs_without_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                Protocol28ExecutionError(
                    f"provider result contains non-finite number {value}"
                )
            ),
        )
    except Protocol28ExecutionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise Protocol28ExecutionError("provider result is not one exact JSON object") from exc
    if not isinstance(value, dict):
        raise Protocol28ExecutionError("provider result is not one exact JSON object")
    return value


__all__ = (
    "L4AcceptanceReceiptV1",
    "L4CandidateReceiptV1",
    "L4CertificationReceiptV1",
    "L4ExecutionCaptureV1",
    "L4ExecutionEnvelopeV1",
    "L4VerificationReceiptV1",
    "PersistedL4ExecutionV1",
    "Protocol28ExecutionError",
    "certify_and_accept",
    "decode_provider_result_object",
    "parse_captured_result",
    "persist_provider_result",
)
