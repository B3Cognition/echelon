"""Pure provider-receipt selection; no file, provider or registry access."""
import re

from harness.discovery_bootstrap_state import bootstrap_from_state
from harness.discovery_producer import producer_component, producer_operation_id


DISCOVERY_TURNS_KEY = "managed_discovery_turns"


def discovery_turns_from_state(state, producer="discovery", *, operation_id=None):
    marker = producer_component(state, producer, "turns", operation_id=operation_id)
    if marker is None:
        return None
    bootstrap = bootstrap_from_state(state)
    if (bootstrap is None or "managed_identity" not in state or type(marker) is not dict
            or set(marker) != {"schema_version", "operation_id", "binding_sha256"}
            or type(marker["schema_version"]) is not int or marker["schema_version"] != 1
            or type(marker["operation_id"]) is not str
            or marker["operation_id"] != producer_operation_id(state, producer, operation_id)
            or type(marker["binding_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", marker["binding_sha256"]) is None):
        raise ValueError("invalid discovery provider receipt selection")
    return dict(marker)
