"""Closed producer selection for the shared managed discovery machinery."""
from copy import deepcopy
from dataclasses import replace
import re

from harness.discovery_bootstrap_state import bootstrap_from_state


SOURCE_KEY = "managed_synthesizer_source"
SOURCE_FIELDS = ("dispatch_id", "completion_intent_sha256", "completion_receipts_sha256",
                 "completed_publication_binding_sha256")
TRACKER_KEY = "managed_tracker_rounds"


def rounds_key(producer):
    if producer not in {"synthesizer", "tracker", "why1"}:
        raise ValueError("unsupported round producer")
    return "managed_" + producer + "_rounds"


def tracker_rounds(state, producer="tracker"):
    """Validate retained selection structure; component owners validate payloads."""
    key = rounds_key(producer)
    value = state.get(key)
    if value is None:
        if key in state:
            raise ValueError("invalid Tracker rounds")
        return None
    if (type(value) is not dict or set(value) != {"schema_version", "active", "rounds"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or type(value["rounds"]) is not dict or not value["rounds"]
            or type(value["active"]) is not str or value["active"] not in value["rounds"]
            or bootstrap_from_state(state) is None or "managed_identity" not in state):
        raise ValueError("invalid Tracker rounds")
    original_synthesis = state.get("managed_synthesizer_operation") if producer == "synthesizer" else None
    root = original_synthesis["binding"]["operation_id"] if original_synthesis is not None else None
    repair_units = set()
    for operation_id, row in value["rounds"].items():
        if (type(operation_id) is not str or re.fullmatch(producer + r"-[0-9a-f]{32}", operation_id) is None
                or type(row) is not dict or set(row) != {"source", "resolution", "operation", "turns", "predecessor", *(("refresh",) if "refresh" in row else ())}):
            raise ValueError("invalid retained Tracker round")
        source = row["source"]
        if type(source) is not dict or set(source) != set(SOURCE_FIELDS):
            raise ValueError("invalid Tracker parent")
        for key, digest in source.items():
            size = 32 if key == "dispatch_id" else 64
            if type(digest) is not str or re.fullmatch(r"[0-9a-f]{%d}" % size, digest) is None:
                raise ValueError("invalid Tracker parent digest")
        if operation_id != producer + "-" + source["dispatch_id"]:
            raise ValueError("Tracker round parent changed")
        resolution = row["resolution"]
        predecessor = row["predecessor"]
        if "refresh" in row:
            validate_refresh_round(state, producer, row)
            unit = row["refresh"]["repair_unit"]
            if unit in repair_units:
                raise ValueError("repeated repair refresh")
            repair_units.add(unit)
        elif producer == "synthesizer" or (resolution is None) != (predecessor is None):
            raise ValueError("invalid Tracker predecessor")
        if predecessor is not None and (type(predecessor) is not str
                or (predecessor not in value["rounds"] and predecessor != root) or predecessor == operation_id):
            raise ValueError("invalid Tracker predecessor")
        if resolution is not None:
            from harness.blocked_decision import validate_blocked_decision
            if type(resolution) is not dict or set(resolution) != {"decision", "completion"}:
                raise ValueError("invalid Tracker resolution association")
            decision = validate_blocked_decision(resolution["decision"])
            receipt = resolution["completion"]
            if (decision != resolution["decision"] or decision["status"] != "resolved"
                    or decision["source_phase"] != "phase1-" + producer or type(receipt) is not dict
                    or receipt.get("decision_id") != decision["id"]):
                raise ValueError("invalid Tracker resolved decision")
            if (set(receipt) != {"schema_version", "decision_id", "completion_id", "intent_sha256",
                    "receipts_sha256", "publication_binding_sha256"} or type(receipt["schema_version"]) is not int
                    or receipt["schema_version"] != 1):
                raise ValueError("invalid Tracker resolution receipt")
            for key in ("completion_id", "intent_sha256", "receipts_sha256", "publication_binding_sha256"):
                size = 32 if key == "completion_id" else 64
                if type(receipt[key]) is not str or re.fullmatch(r"[0-9a-f]{%d}" % size, receipt[key]) is None:
                    raise ValueError("invalid Tracker resolution receipt digest")
    seen, decisions, completions = set(), set(), set()
    current = value["active"]
    while current is not None and current != root:
        if current in seen:
            raise ValueError("cyclic Tracker rounds")
        seen.add(current)
        row = value["rounds"][current]
        if row["resolution"] is not None:
            decision_id = row["resolution"]["decision"]["id"]
            completion_id = row["resolution"]["completion"]["completion_id"]
            if decision_id in decisions or completion_id in completions:
                raise ValueError("repeated Tracker clarification")
            decisions.add(decision_id)
            completions.add(completion_id)
        current = row["predecessor"]
    if seen != set(value["rounds"]):
        raise ValueError("disconnected Tracker rounds")
    return deepcopy(value)


def validate_refresh_round(state, producer, row):
    """Validate association structure, not publication authority or execution."""
    refresh = row["refresh"]
    if type(refresh) is not dict or set(refresh) != {"repair_unit", "repair_source", "predecessor_source"}:
        raise ValueError("invalid refresh association")
    for source in (refresh["repair_source"], refresh["predecessor_source"]):
        if type(source) is not dict or set(source) != set(SOURCE_FIELDS) or any(
                type(digest) is not str or re.fullmatch(r"[0-9a-f]{%d}" % (32 if key == "dispatch_id" else 64), digest) is None
                for key, digest in source.items()):
            raise ValueError("invalid refresh source")
    repair = repair_record(state, "discovery", refresh["repair_unit"])
    if ("execution" not in repair or not repair["attempts"]
            or (repair["attempts"][-1]["result"] or {}).get("status") != "accepted"
            or row["source"] != refresh["repair_source"]
            or refresh["predecessor_source"]["dispatch_id"] == row["source"]["dispatch_id"]
            or repair["selection"]["origin"] != dict(review_id=repair["selection"]["source"]["dispatch_id"], return_phase="phase1-why1")
            or row["resolution"] is not None or row["operation"] is not None or row["turns"] is not None):
        raise ValueError("refresh requires an accepted repair; execution is not admitted")
    predecessor = row["predecessor"]
    if type(predecessor) is not str:
        raise ValueError("refresh requires a predecessor")
    if producer == "synthesizer" and predecessor.startswith("synthesis-"):
        previous = state.get("managed_synthesizer_operation")
    else:
        previous = state[rounds_key(producer)]["rounds"].get(predecessor, {}).get("operation")
    if (previous is None or previous["binding"]["operation_id"] != predecessor
            or not previous["attempts"] or (previous["attempts"][-1]["result"] or {}).get("status") != "accepted"):
        raise ValueError("refresh predecessor must be accepted")
    if producer == "why1" and refresh["predecessor_source"] != repair["selection"]["source"]:
        raise ValueError("refresh must return to the requesting WHY1")


def tracker_round(state, operation_id=None, *, producer="tracker"):
    rounds = tracker_rounds(state, producer)
    if rounds is None:
        if operation_id is not None:
            raise ValueError("Tracker round not retained")
        return None
    key = rounds["active"] if operation_id is None else operation_id
    if key not in rounds["rounds"]:
        raise ValueError("Tracker round not retained")
    return rounds["rounds"][key]


def tracker_input_source(state, operation_id=None, *, producer="tracker"):
    row = tracker_round(state, operation_id, producer=producer)
    if row["resolution"] is None:
        return row["source"]
    receipt = row["resolution"]["completion"]
    return dict(dispatch_id=receipt["completion_id"], completion_intent_sha256=receipt["intent_sha256"],
        completion_receipts_sha256=receipt["receipts_sha256"],
        completed_publication_binding_sha256=receipt["publication_binding_sha256"])


def repair_record(state, producer, unit):
    if producer != "discovery" or type(unit) is not str or re.fullmatch(r"[0-9a-f]{64}", unit) is None:
        raise ValueError("invalid repair selection")
    return state["managed_discovery_repairs"]["units"][unit]


def producer_component(state, producer, suffix, *, operation_id=None, repair_unit=None):
    if repair_unit is not None:
        row = repair_record(state, producer, repair_unit)
        if operation_id is not None and operation_id != producer_operation_id(state, producer, repair_unit=repair_unit):
            raise ValueError("repair operation changed")
        execution = row.get("execution")
        if suffix not in {"operation", "turns"}:
            raise ValueError("invalid repair component")
        if execution is None:
            return None
        return deepcopy(execution["turns"] if suffix == "turns" else dict(
            schema_version=1, binding=execution["binding"], attempts=row["attempts"]))
    if producer == "synthesizer" and operation_id is not None and operation_id.startswith("synthesizer-"):
        if suffix not in {"operation", "turns"}:
            raise ValueError("invalid synthesis round component")
        return tracker_round(state, operation_id, producer=producer)[suffix]
    if producer not in {"tracker", "why1"}:
        if operation_id is not None and operation_id != producer_operation_id(state, producer):
            raise ValueError("producer operation changed")
        return state.get(producer_key(producer, suffix))
    if suffix not in {"operation", "turns"}:
        raise ValueError("invalid Tracker component")
    row = tracker_round(state, operation_id, producer=producer)
    return None if row is None else row[suffix]


def with_producer_component(state, producer, suffix, value, *, repair_unit=None):
    if repair_unit is not None:
        updated = deepcopy(state)
        row = repair_record(updated, producer, repair_unit)
        if suffix != "turns" or "execution" not in row:
            raise ValueError("repair execution must be selected")
        old = row["execution"]["turns"]
        if old is not None and old != value:
            raise ValueError("repair turns are immutable")
        row["execution"]["turns"] = deepcopy(value)
        return updated
    if producer not in {"tracker", "why1"}:
        return {**state, producer_key(producer, suffix): value}
    rounds = tracker_rounds(state, producer)
    if rounds is None or suffix not in {"operation", "turns"}:
        raise ValueError("Tracker round must be selected")
    rounds["rounds"][rounds["active"]][suffix] = deepcopy(value)
    return {**state, rounds_key(producer): rounds}


def producer_key(producer, suffix):
    if producer not in {"discovery", "synthesizer"} or suffix not in {"operation", "turns"}:
        raise ValueError("unsupported managed producer")
    return f"managed_{producer}_{suffix}"


def producer_phase(producer):
    if producer in {"tracker", "why1"}:
        return "phase1-" + producer
    producer_key(producer, "operation")
    return "phase1-discover" if producer == "discovery" else "phase1-synthesizer"


def producer_role(producer, role):
    if producer in {"tracker", "why1"} and role in {"producer", "reviewer"}:
        return "echelon." + producer + "-" + role
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


def producer_operation_id(state, producer, operation_id=None, *, repair_unit=None):
    if repair_unit is not None:
        repair_record(state, producer, repair_unit)
        expected = "discovery-repair-" + repair_unit
        if operation_id is not None and operation_id != expected:
            raise ValueError("repair operation changed")
        return expected
    if producer in {"tracker", "why1"}:
        row = tracker_round(state, operation_id, producer=producer)
        if row is None:
            raise ValueError("Tracker round not selected")
        return producer + "-" + row["source"]["dispatch_id"]
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
