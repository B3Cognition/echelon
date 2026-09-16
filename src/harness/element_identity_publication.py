"""Immutable publication intent claims; decoding grants no execution authority."""

from dataclasses import dataclass
import json

from harness.element_identity_bindings import sha256
from harness.element_identity_lifecycle import text
from harness.element_identity_json import strict_json
from harness.element_identity_request_codec import encode_request, decode_request
from harness.squad_publication import PublicationError


class PublicationIntentError(ValueError):
    """Malformed publication request, with bounded diagnostics."""


_METHODS = ("lifecycle", "reference_claims", "issue_occurrences")


@dataclass(frozen=True, slots=True)
class PublicationSourceClaim:
    context_id: str
    expected_operation_id: str
    baseline_payload: str

    def __post_init__(self):
        _source_baseline(self)


def _source_baseline(claim):
    from harness.squad_source_baseline_codec import (
        encode_initial_publication_sources, decode_initial_publication_sources,
    )
    try:
        if type(claim) is not PublicationSourceClaim:
            raise ValueError("invalid source claim type")
        text(claim.context_id, "context_id")
        text(claim.expected_operation_id, "expected_operation_id")
        baseline = decode_initial_publication_sources(claim.baseline_payload)
        if encode_initial_publication_sources(baseline) != claim.baseline_payload:
            raise ValueError("noncanonical source baseline")
        return baseline
    except (PublicationError, ValueError, TypeError, AttributeError, KeyError, RecursionError, OverflowError):
        raise PublicationIntentError("invalid publication source claim") from None


@dataclass(frozen=True, slots=True)
class PublicationOperation:
    method: str
    operation_id: str
    payload: str

    def __post_init__(self):
        try:
            if type(self) is not PublicationOperation or type(self.method) is not str or self.method not in _METHODS:
                raise ValueError("invalid publication operation type or method")
            text(self.operation_id, "operation_id")
            if self.payload != encode_request(self.method, decode_request(self.method, self.payload)):
                raise ValueError("child request must use its canonical ASCII encoding")
        except (ValueError, TypeError, AttributeError, RecursionError) as error:
            raise PublicationIntentError("invalid publication operation") from error


@dataclass(frozen=True, slots=True)
class PublicationContinuationClaim:
    """Opaque completion association; the completion owner authenticates it."""
    parent_operation_id: str
    parent_request_sha256: str
    parent_application_sha256: str
    completion_id: str
    completion_intent_sha256: str

    def __post_init__(self):
        _continuation_claim(self)


def _continuation_claim(claim):
    if type(claim) is not PublicationContinuationClaim:
        raise ValueError("invalid continuation claim type")
    text(claim.parent_operation_id, "parent_operation_id")
    text(claim.completion_id, "completion_id")
    for value in (claim.parent_request_sha256, claim.parent_application_sha256,
                  claim.completion_intent_sha256):
        sha256(value)


@dataclass(frozen=True, slots=True)
class PublicationIntentRequest:
    manifest_sha256: str
    recovery_payload: str
    operations: tuple[PublicationOperation, ...] = ()
    sources: PublicationSourceClaim | None = None
    proposed_history_sha256: str | None = None
    continuation_id: str | None = None
    continuation: PublicationContinuationClaim | None = None

    def __post_init__(self):
        _validate(self)


def validated_operations(operations):
    """Validate and detach the canonical ordered child operations, without a parent."""
    if type(operations) is not tuple:
        raise ValueError("operations must be an exact tuple")
    previous, seen, detached = -1, set(), []
    for operation in operations:
        if type(operation) is not PublicationOperation:
            raise ValueError("operation must have its exact immutable type")
        copy = PublicationOperation(operation.method, operation.operation_id, operation.payload)
        index = _METHODS.index(copy.method)
        if index <= previous or copy.operation_id in seen:
            raise ValueError("operations must be unique and in method order")
        previous = index
        seen.add(copy.operation_id)
        detached.append(copy)
    return tuple(detached)


def _validate(request):
    try:
        if type(request) is not PublicationIntentRequest:
            raise ValueError("request must have its exact immutable type")
        sha256(request.manifest_sha256)
        text(request.recovery_payload, "recovery_payload")
        validated_operations(request.operations)
        if request.continuation_id is not None:
            text(request.continuation_id, "continuation_id")
            if request.continuation is not None or any(
                    op.operation_id == request.continuation_id for op in request.operations):
                raise ValueError("continuation must be distinct and cannot be nested")
        if request.continuation is not None:
            _continuation_claim(request.continuation)
        if (request.continuation_id is not None or request.continuation is not None) and request.sources is None:
            raise ValueError("continuation requires source ownership")
        if request.proposed_history_sha256 is not None:
            sha256(request.proposed_history_sha256)
        if request.sources is not None:
            baseline = _source_baseline(request.sources)
            if baseline.publication.marker.manifest_sha256 != request.manifest_sha256:
                raise ValueError("source baseline marker differs from publication")
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError, OverflowError):
        raise PublicationIntentError("invalid publication intent request") from None


def encode_publication_request(request: PublicationIntentRequest) -> str:
    _validate(request)
    value = {"version": "1", "manifest_sha256": request.manifest_sha256,
                       "recovery_payload": request.recovery_payload,
                       "operations": [{"method": op.method, "operation_id": op.operation_id,
                                       "payload": op.payload} for op in request.operations]}
    if request.sources is not None:
        value["version"] = "2"
        value["sources"] = {"context_id": request.sources.context_id,
                            "expected_operation_id": request.sources.expected_operation_id,
                            "baseline_payload": request.sources.baseline_payload}
    if request.proposed_history_sha256 is not None:
        value.update(version="3", proposed_history_sha256=request.proposed_history_sha256)
    if request.continuation_id is not None or request.continuation is not None:
        claim = request.continuation
        value.update(version="4", continuation_id=request.continuation_id,
                     continuation=None if claim is None else {
                         "parent_operation_id": claim.parent_operation_id,
                         "parent_request_sha256": claim.parent_request_sha256,
                         "parent_application_sha256": claim.parent_application_sha256,
                         "completion_id": claim.completion_id,
                         "completion_intent_sha256": claim.completion_intent_sha256})
    return json.dumps(value,
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def decode_publication_request(payload: str) -> PublicationIntentRequest:
    try:
        value = strict_json(payload)
        if (type(value) is not dict or type(value.get("version")) is not str or value["version"] not in {"1", "2", "3", "4"}
                or set(value) != ({"version", "manifest_sha256", "recovery_payload", "operations"}
                                  | ({"sources"} if value["version"] in {"2", "4"} or (value["version"] == "3" and "sources" in value) else set())
                                  | ({"proposed_history_sha256"} if value["version"] == "3" or (value["version"] == "4" and "proposed_history_sha256" in value) else set())
                                  | ({"continuation_id", "continuation"} if value["version"] == "4" else set()))
                or type(value["operations"]) is not list):
            raise ValueError("invalid publication shape/version")
        operations = []
        for operation in value["operations"]:
            if type(operation) is not dict or set(operation) != {"method", "operation_id", "payload"}:
                raise ValueError("invalid operation shape")
            operations.append(PublicationOperation(**operation))
        sources = None
        if "sources" in value:
            if type(value["sources"]) is not dict or set(value["sources"]) != {"context_id", "expected_operation_id", "baseline_payload"}:
                raise ValueError("invalid source claim shape")
            sources = PublicationSourceClaim(**value["sources"])
        if "proposed_history_sha256" in value:
            sha256(value["proposed_history_sha256"])
        continuation = None
        if value["version"] == "4":
            if value["continuation"] is not None:
                claim = value["continuation"]
                if type(claim) is not dict or set(claim) != {
                        "parent_operation_id", "parent_request_sha256", "parent_application_sha256",
                        "completion_id", "completion_intent_sha256"}:
                    raise ValueError("invalid continuation shape")
                continuation = PublicationContinuationClaim(**claim)
            if value["continuation_id"] is None and continuation is None:
                raise ValueError("empty continuation envelope")
        return PublicationIntentRequest(value["manifest_sha256"], value["recovery_payload"], tuple(operations), sources,
                                        value.get("proposed_history_sha256"), value.get("continuation_id"), continuation)
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError, OverflowError):
        raise PublicationIntentError("malformed serialized publication intent") from None


def application_metadata(request):
    """Pure retained request/receipt association, without observing current history."""
    if request.proposed_history_sha256 is not None:
        return {"version": "3", "identity_history_sha256": request.proposed_history_sha256}
    return {"version": "2" if request.sources is not None else "1"}
