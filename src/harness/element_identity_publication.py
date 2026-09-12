"""Immutable publication intent claims; decoding grants no execution authority."""

from dataclasses import dataclass
import json

from harness.element_identity_bindings import sha256
from harness.element_identity_lifecycle import text
from harness.element_identity_json import strict_json
from harness.element_identity_request_codec import encode_request, decode_request


class PublicationIntentError(ValueError):
    """Malformed publication request, with bounded diagnostics."""


_METHODS = ("lifecycle", "reference_claims", "issue_occurrences")


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
class PublicationIntentRequest:
    manifest_sha256: str
    recovery_payload: str
    operations: tuple[PublicationOperation, ...] = ()

    def __post_init__(self):
        _validate(self)


def _validate(request):
    try:
        if type(request) is not PublicationIntentRequest:
            raise ValueError("request must have its exact immutable type")
        sha256(request.manifest_sha256)
        text(request.recovery_payload, "recovery_payload")
        if type(request.operations) is not tuple:
            raise ValueError("operations must be an exact tuple")
        previous, seen = -1, set()
        for operation in request.operations:
            if type(operation) is not PublicationOperation:
                raise ValueError("operation must have its exact immutable type")
            PublicationOperation.__post_init__(operation)
            index = _METHODS.index(operation.method)
            if index <= previous or operation.operation_id in seen:
                raise ValueError("operations must be unique and in method order")
            previous = index
            seen.add(operation.operation_id)
    except (ValueError, TypeError, AttributeError, RecursionError) as error:
        raise PublicationIntentError("invalid publication intent request") from error


def encode_publication_request(request: PublicationIntentRequest) -> str:
    _validate(request)
    return json.dumps({"version": "1", "manifest_sha256": request.manifest_sha256,
                       "recovery_payload": request.recovery_payload,
                       "operations": [{"method": op.method, "operation_id": op.operation_id,
                                       "payload": op.payload} for op in request.operations]},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def decode_publication_request(payload: str) -> PublicationIntentRequest:
    try:
        value = strict_json(payload)
        if (type(value) is not dict or set(value) != {"version", "manifest_sha256", "recovery_payload", "operations"}
                or type(value["version"]) is not str or value["version"] != "1"
                or type(value["operations"]) is not list):
            raise ValueError("invalid publication shape/version")
        operations = []
        for operation in value["operations"]:
            if type(operation) is not dict or set(operation) != {"method", "operation_id", "payload"}:
                raise ValueError("invalid operation shape")
            operations.append(PublicationOperation(**operation))
        return PublicationIntentRequest(value["manifest_sha256"], value["recovery_payload"], tuple(operations))
    except (ValueError, TypeError, RecursionError) as error:
        raise PublicationIntentError("malformed serialized publication intent") from error
