"""Closed producer selection for the shared managed discovery machinery."""
from copy import deepcopy
from dataclasses import replace
import re

from harness.discovery_bootstrap_state import bootstrap_from_state


SOURCE_KEY = "managed_synthesizer_source"
SOURCE_FIELDS = ("dispatch_id", "completion_intent_sha256", "completion_receipts_sha256",
                 "completed_publication_binding_sha256")


def producer_key(producer, suffix):
    if producer not in {"discovery", "synthesizer"} or suffix not in {"operation", "turns"}:
        raise ValueError("unsupported managed producer")
    return f"managed_{producer}_{suffix}"


def producer_phase(producer):
    producer_key(producer, "operation")
    return "phase1-discover" if producer == "discovery" else "phase1-synthesizer"


def producer_role(producer, role):
    producer_key(producer, "operation")
    if role not in {"producer", "reviewer"}:
        raise ValueError("unsupported semantic role")
    return "echelon.synthesis-producer" if producer == "synthesizer" and role == "producer" else "echelon.discovery-" + role


def synthesis_source(state):
    if SOURCE_KEY not in state:
        return None
    source = state[SOURCE_KEY]
    if type(source) is not dict or set(source) != set(SOURCE_FIELDS):
        raise ValueError("invalid synthesis source")
    for key, value in source.items():
        size = 32 if key == "dispatch_id" else 64
        if type(value) is not str or re.fullmatch(r"[0-9a-f]{%d}" % size, value) is None:
            raise ValueError("invalid synthesis source binding")
    if bootstrap_from_state(state) is None or "managed_identity" not in state:
        raise ValueError("synthesis requires managed discovery")
    return deepcopy(source)


def producer_operation_id(state, producer):
    producer_key(producer, "operation")
    if producer == "discovery":
        return bootstrap_from_state(state)["selection"]["operation_id"]
    source = synthesis_source(state)
    if source is None:
        raise ValueError("synthesis source not selected")
    return "synthesis-" + source["dispatch_id"]


def identity_spec_tree(tree):
    """Identity view only; callers authenticate metadata and retain raw guards."""
    metadata = tree.path + "/.echelon"
    return replace(tree,
        directories=tuple(row for row in tree.directories if row.path != metadata and not row.path.startswith(metadata + "/")),
        files=tuple(row for row in tree.files if not row.path.startswith(metadata + "/")))
