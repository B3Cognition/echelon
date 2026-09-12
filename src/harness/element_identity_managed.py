"""Immutable first-enrollment request; pure, closed canonical string wire."""

from dataclasses import dataclass
from functools import wraps
import re
from uuid import UUID

from harness.element_identity_json import strict_json
from harness.element_identity_lifecycle import text
from harness.element_identity_request_codec import _canonical
from harness.squad_source_snapshot import _source_path


def _bounded(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            raise ValueError("invalid managed identity request") from None
    return checked


_FIELDS = ("workspace_uuid", "epoch_uuid", "run_id", "context_id", "spec_path",
           "source_registration_operation_id", "source_manifest_sha256")


@dataclass(frozen=True, slots=True)
class ManagedIdentityRequest:
    workspace_uuid: str
    epoch_uuid: str
    run_id: str
    context_id: str
    spec_path: str
    source_registration_operation_id: str
    source_manifest_sha256: str

    def __post_init__(self):
        validate_managed_identity_request(self)


@_bounded
def validate_managed_identity_request(request):
    if type(request) is not ManagedIdentityRequest:
        raise ValueError("exact request required")
    for field in _FIELDS:
        text(getattr(request, field), field)
    for field in ("workspace_uuid", "epoch_uuid"):
        value = getattr(request, field)
        if str(UUID(value)) != value:
            raise ValueError("noncanonical namespace")
    if _source_path(request.spec_path).as_posix() != request.spec_path:
        raise ValueError("noncanonical spec path")
    if re.fullmatch(r"[0-9a-f]{64}", request.source_manifest_sha256) is None:
        raise ValueError("invalid manifest hash")
    return request


@_bounded
def encode_managed_identity_request(request: ManagedIdentityRequest) -> str:
    validate_managed_identity_request(request)
    return _canonical({"version": "1", **{field: getattr(request, field) for field in _FIELDS}})


@_bounded
def decode_managed_identity_request(payload: str) -> ManagedIdentityRequest:
    value = strict_json(payload)
    if type(value) is not dict or set(value) != {"version", *_FIELDS} or value["version"] != "1":
        raise ValueError("invalid request shape")
    request = ManagedIdentityRequest(*(value[field] for field in _FIELDS))
    if encode_managed_identity_request(request) != payload:
        raise ValueError("noncanonical request")
    return request
