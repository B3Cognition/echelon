"""Pure validation of claimed genesis metadata; no registry authentication."""

from harness.element_identity_lifecycle import text
from harness.element_identity_managed import (
    ManagedIdentityRequest,
    decode_managed_identity_request,
    encode_managed_identity_request,
)


MANAGED_IDENTITY_KEY = "managed_identity"
_REQUEST_FIELDS = (
    "workspace_uuid", "epoch_uuid", "run_id", "context_id", "spec_path",
    "source_registration_operation_id", "source_manifest_sha256",
)
_RECORD_FIELDS = frozenset({"version", "spec_id", "operation_id", *_REQUEST_FIELDS})


def validate_managed_identity_record(value: object) -> dict[str, str]:
    """Detach a closed first-run record without certifying its provenance."""
    try:
        if type(value) is not dict:
            raise ValueError("exact dict required")
        # Check exact key types before hashing or comparing untrusted keys.
        if any(type(key) is not str for key in value) or set(value) != _RECORD_FIELDS:
            raise ValueError("exact fields required")
        if any(type(item) is not str for item in value.values()) or value["version"] != "1":
            raise ValueError("exact string record required")
        text(value["spec_id"], "spec_id")
        text(value["operation_id"], "operation_id")
        request = ManagedIdentityRequest(*(value[field] for field in _REQUEST_FIELDS))
        decode_managed_identity_request(encode_managed_identity_request(request))
        return dict(value)
    except Exception:
        pass
    # Raise after leaving the handler so even __context__ cannot retain the
    # untrusted exception. BaseException deliberately bypasses normalization.
    raise ValueError("invalid managed identity record") from None
