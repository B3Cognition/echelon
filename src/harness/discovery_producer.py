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
    if producer not in {"synthesizer", "tracker", "why1", "constitution", "what", "why2", "lexicon", "feasibility", "strategy", "alignment"}:
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
    original = state.get("managed_" + producer + "_operation") if producer in {"synthesizer", "constitution"} else None
    root = original["binding"]["operation_id"] if original is not None else None
    prefix = "constitution-refresh" if producer == "constitution" else producer
    repair_units = set()
    for operation_id, row in value["rounds"].items():
        if (type(operation_id) is not str or re.fullmatch(prefix + r"-[0-9a-f]{32}", operation_id) is None
                or type(row) is not dict or set(row) != {"source", "resolution", "operation", "turns", "predecessor",
                    *(("refresh",) if "refresh" in row else ()), *(("execution_input",) if "execution_input" in row else ()),
                    *(("tracker_parent",) if "tracker_parent" in row else ()),
                    *(("constitution_parent",) if "constitution_parent" in row else ()),
                    *(("review_resolution", "review_parent") if "review_resolution" in row else ())}
                or ("execution_input" in row and "refresh" not in row)):
            raise ValueError("invalid retained Tracker round")
        if "tracker_parent" in row:
            if (producer != "why1" or row["resolution"] is not None
                    or (row["predecessor"] is not None and "refresh" not in row)
                    or ("refresh" in row and "execution_input" not in row)
                    or type(row["tracker_parent"]) is not str):
                raise ValueError("Tracker history belongs to a bound WHY1 input")
            parents = tracker_rounds(state)
            previous = None if parents is None else parents["rounds"].get(row["tracker_parent"], {}).get("operation")
            if (previous is None or previous["binding"]["operation_id"] != row["tracker_parent"]
                    or not previous["attempts"] or (previous["attempts"][-1]["result"] or {}).get("status") != "accepted"):
                raise ValueError("WHY1 history requires a retained accepted Tracker")
        if "constitution_parent" in row:
            if (producer != "what" or row["predecessor"] is None or row["resolution"] is not None
                    or type(row["constitution_parent"]) is not str
                    or re.fullmatch(r"constitution-refresh-[0-9a-f]{32}", row["constitution_parent"]) is None):
                raise ValueError("refreshed specification requires an exact Constitution parent")
            parents = tracker_rounds(state, "constitution")
            previous = None if parents is None else parents["rounds"].get(row["constitution_parent"], {}).get("operation")
            if (previous is None or previous["binding"]["operation_id"] != row["constitution_parent"]
                    or not previous["attempts"] or (previous["attempts"][-1]["result"] or {}).get("status") != "accepted"):
                raise ValueError("specification requires its accepted Constitution refresh")
        source = row["source"]
        if type(source) is not dict or set(source) != set(SOURCE_FIELDS):
            raise ValueError("invalid Tracker parent")
        for key, digest in source.items():
            size = 32 if key == "dispatch_id" else 64
            if type(digest) is not str or re.fullmatch(r"[0-9a-f]{%d}" % size, digest) is None:
                raise ValueError("invalid Tracker parent digest")
        if operation_id != prefix + "-" + source["dispatch_id"]:
            raise ValueError("Tracker round parent changed")
        resolution = row["resolution"]
        if "review_resolution" in row:
            if producer != "what" or resolution is not None or row["predecessor"] is None or "constitution_parent" in row:
                raise ValueError("WHAT answer input requires its requesting review")
            reviews = tracker_rounds(state, "why2")
            parent = None if reviews is None else reviews["rounds"].get(row["review_parent"])
            operation = None if parent is None else parent["operation"]
            if (operation is None or not operation["attempts"]
                    or (operation["attempts"][-1].get("result") or {}).get("status") != "accepted"):
                raise ValueError("WHAT answer input requires an accepted WHY2 operation")
        predecessor = row["predecessor"]
        if "refresh" in row:
            if producer in {"constitution", "what", "why2", "lexicon", "feasibility", "strategy", "alignment"}:
                raise ValueError("specification rounds require native parent completions")
            validate_refresh_round(state, producer, row)
            unit = row["refresh"]["repair_unit"]
            if unit in repair_units:
                raise ValueError("repeated repair refresh")
            repair_units.add(unit)
        elif producer not in {"constitution", "what", "why2", "lexicon", "feasibility", "strategy", "alignment"} and (producer == "synthesizer" or (resolution is None) != (predecessor is None)):
            raise ValueError("invalid Tracker predecessor")
        if predecessor is not None and (type(predecessor) is not str
                or (predecessor not in value["rounds"] and predecessor != root) or predecessor == operation_id):
            raise ValueError("invalid Tracker predecessor")
        if producer == "constitution" and (predecessor is None or resolution is not None):
            raise ValueError("Constitution refresh requires an immutable predecessor")
        if producer in {"constitution", "what", "why2", "lexicon", "feasibility", "strategy", "alignment"} and predecessor is not None:
            previous = original if predecessor == root else value["rounds"][predecessor]["operation"]
            if (previous is None or not previous.get("attempts")
                    or (previous["attempts"][-1].get("result") or {}).get("status") != "accepted"):
                raise ValueError("specification predecessor must be accepted")
        if producer == "what" and resolution is not None:
            raise ValueError("WHAT clarification belongs to its requesting review")
        if producer == "lexicon" and resolution is not None and predecessor is not None:
            raise ValueError("debt can admit only the initial derivation")
        if producer == "feasibility" and (resolution is None) == (predecessor is None):
            raise ValueError("feasibility requires initial approval or a retained structural predecessor")
        if producer == "strategy" and (resolution is not None or predecessor is not None or len(value["rounds"]) != 1):
            raise ValueError("first-entry assessment requires one exact parent, without repair or resolution")
        if producer == "alignment" and resolution is not None and predecessor is None:
            raise ValueError("alignment answer requires its accepted question predecessor")
        association = row.get("review_resolution", resolution)
        if association is not None:
            from harness.blocked_decision import validate_blocked_decision
            if type(association) is not dict or set(association) != {"decision", "completion"}:
                raise ValueError("invalid Tracker resolution association")
            decision = validate_blocked_decision(association["decision"])
            receipt = association["completion"]
            owner = "why2" if "review_resolution" in row or producer == "lexicon" else producer
            phase = "checkpoint-assess" if producer == "feasibility" else "phase2-tracker-alignment" if producer == "alignment" else "phase1-" + owner
            if (decision != association["decision"] or decision["status"] != "resolved"
                    or decision["source_phase"] != phase or type(receipt) is not dict
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
            if producer == "lexicon":
                from harness.discovery_spec import clarification_source
                from harness.discovery_policy_resolution import require_resolved
                require_resolved(decision, debt=True)
                if decision["selected_option_id"] != "continue_with_debt" or source != clarification_source(receipt):
                    raise ValueError("derivation requires exact accepted-debt resolution")
            if producer == "feasibility":
                from harness.discovery_checkpoint_resolution import state_effects
                from harness.discovery_spec import clarification_source
                if state_effects(decision)["route"] != "phase2-decide" or source != clarification_source(receipt):
                    raise ValueError("feasibility requires exact native approval resolution")
            if producer == "alignment":
                from harness.discovery_spec import clarification_source
                from harness.tracker_clarification import _record
                _record(decision, "alignment")
                if source != clarification_source(receipt):
                    raise ValueError("alignment answer source differs from its native receipt")
            if "review_resolution" in row:
                from harness.discovery_spec import clarification_source
                if row["source"] != clarification_source(receipt):
                    raise ValueError("WHAT answer source differs from the native resolution")
                if decision["resolution_handler"] == "clarification_resume":
                    if decision["selected_option_id"] is not None:
                        raise ValueError("clarification cannot select a policy option")
                elif decision["resolution_handler"] == "banzai_issue_resolution":
                    from harness.discovery_issue_resolution import require_resolved
                    require_resolved(decision)
                else:
                    from harness.discovery_policy_resolution import require_resolved
                    require_resolved(decision)
    seen, decisions, completions = set(), set(), set()
    current = value["active"]
    while current is not None and current != root:
        if current in seen:
            raise ValueError("cyclic Tracker rounds")
        seen.add(current)
        row = value["rounds"][current]
        association = row.get("review_resolution", row["resolution"])
        if association is not None:
            decision_id = association["decision"]["id"]
            completion_id = association["completion"]["completion_id"]
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
    return_phase = repair_return_phase(state, refresh["repair_unit"])
    if ("execution" not in repair or not repair["attempts"]
            or (repair["attempts"][-1]["result"] or {}).get("status") != "accepted"
            or row["source"] != refresh["repair_source"]
            or refresh["predecessor_source"]["dispatch_id"] == row["source"]["dispatch_id"]
            or row["resolution"] is not None):
        raise ValueError("refresh requires an accepted repair")
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
    if producer == "why1" and ((refresh["predecessor_source"] == repair["selection"]["source"])
            != (return_phase == "phase1-why1")):
        raise ValueError("refresh predecessor must distinguish WHY1 from the requesting review")
    if "execution_input" in row:
        validate_refresh_input(producer, refresh, row["execution_input"])
        if producer == "why1" and "tracker_parent" not in row:
            raise ValueError("WHY1 refresh requires its accepted Tracker history")
    if row["operation"] is not None or row["turns"] is not None:
        if (producer not in {"synthesizer", "tracker", "why1"} or "execution_input" not in row
                or row["operation"] is None):
            raise ValueError("refresh execution requires bound inputs")


def validate_refresh_input(producer, refresh, bound):
    """Closed input shape shared by retained state and completion proofs."""
    if (producer not in {"synthesizer", "tracker", "why1"} or type(bound) is not dict or set(bound) != {"source", "dependencies"}
            or type(bound["source"]) is not dict or set(bound["source"]) != set(SOURCE_FIELDS)
            or any(type(value) is not str or re.fullmatch(r"[0-9a-f]{%d}" % (32 if key == "dispatch_id" else 64), value) is None
                for key, value in bound["source"].items())
            or (producer == "synthesizer" and bound["source"] != refresh["repair_source"])
            or (producer in {"tracker", "why1"} and bound["source"]["dispatch_id"] == refresh["repair_source"]["dispatch_id"])):
        raise ValueError("refresh execution input is not admitted")
    dependencies = bound["dependencies"]
    if (type(dependencies) is not dict or set(dependencies) != {"before_sha256", "after_sha256", "changed"}
            or any(type(dependencies[key]) is not str or re.fullmatch(r"[0-9a-f]{64}", dependencies[key]) is None
                for key in ("before_sha256", "after_sha256"))
            or type(dependencies["changed"]) is not list
            or any(type(key) is not str or not key for key in dependencies["changed"])
            or dependencies["changed"] != sorted(set(dependencies["changed"]))
            or (dependencies["before_sha256"] == dependencies["after_sha256"]) != (not dependencies["changed"])):
        raise ValueError("invalid refresh dependency comparison")


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
    if "refresh" in row:
        if "execution_input" not in row:
            raise ValueError("refresh execution input is not bound")
        return deepcopy(row["execution_input"]["source"])
    if row["resolution"] is None:
        return row["source"]
    receipt = row["resolution"]["completion"]
    return dict(dispatch_id=receipt["completion_id"], completion_intent_sha256=receipt["intent_sha256"],
        completion_receipts_sha256=receipt["receipts_sha256"],
        completed_publication_binding_sha256=receipt["publication_binding_sha256"])


def post_why1_context(state, producer):
    """Refresh descendants retain read-only review context, not new write roles."""
    if producer not in {"synthesizer", "tracker", "why1"}:
        return False
    rounds = tracker_rounds(state, producer)
    return rounds is not None and any("refresh" in row for row in rounds["rounds"].values())


def repair_record(state, producer, unit):
    if producer != "discovery" or type(unit) is not str or re.fullmatch(r"[0-9a-f]{64}", unit) is None:
        raise ValueError("invalid repair selection")
    return state["managed_discovery_repairs"]["units"][unit]


def repair_return_phase(state, unit):
    """Closed requesting-review association, not proof of native routing."""
    selected = repair_record(state, "discovery", unit)["selection"]
    phase = selected["origin"].get("return_phase")
    if (phase not in {"phase1-why1", "phase1-why2"}
            or selected["origin"] != dict(review_id=selected["source"]["dispatch_id"], return_phase=phase)):
        raise ValueError("repair requires an exact supported requesting review")
    return phase


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
    if producer == "constitution" and rounds_key(producer) in state:
        if suffix not in {"operation", "turns"}:
            raise ValueError("invalid Constitution component")
        selected = producer_operation_id(state, producer, operation_id)
        if selected.startswith("constitution-refresh-"):
            return tracker_round(state, selected, producer=producer)[suffix]
        return state.get(producer_key(producer, suffix))
    if producer == "synthesizer":
        if suffix not in {"operation", "turns"}:
            raise ValueError("invalid synthesis round component")
        if synthesis_source(state) is None and operation_id is None and rounds_key(producer) not in state:
            return state.get(producer_key(producer, suffix))
        selected = producer_operation_id(state, producer, operation_id)
        if selected.startswith("synthesizer-"):
            return tracker_round(state, selected, producer=producer)[suffix]
        return state.get(producer_key(producer, suffix))
    if producer not in {"tracker", "why1", "what", "why2", "lexicon", "feasibility", "strategy", "alignment"}:
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
    if producer not in {"tracker", "why1", "what", "why2", "lexicon", "feasibility", "strategy", "alignment"} and not (producer in {"synthesizer", "constitution"} and rounds_key(producer) in state):
        return {**state, producer_key(producer, suffix): value}
    rounds = tracker_rounds(state, producer)
    if rounds is None or suffix not in {"operation", "turns"}:
        raise ValueError("Tracker round must be selected")
    rounds["rounds"][rounds["active"]][suffix] = deepcopy(value)
    return {**state, rounds_key(producer): rounds}


def producer_key(producer, suffix):
    if producer not in {"discovery", "synthesizer", "constitution"} or suffix not in {"operation", "turns"}:
        raise ValueError("unsupported managed producer")
    return f"managed_{producer}_{suffix}"


def producer_phase(producer):
    if producer == "alignment_gate":
        return "phase2-intent-alignment-structural"
    if producer == "feasibility_gate":
        return "phase2-feasibility-structural"
    if producer in {"feasibility", "strategy", "alignment"}:
        return {"feasibility": "phase2-decide", "strategy": "phase2-strategic-overview",
                "alignment": "phase2-tracker-alignment"}[producer]
    if producer == "checkpoint":
        return "checkpoint-assess"
    if producer == "lexicon_gate":
        return "phase1-lexicon"
    if producer == "lexicon":
        return "phase1-lexicon-derive"
    if producer in {"tracker", "why1", "constitution", "what", "why2", "understanding"}:
        return "phase1-" + producer
    producer_key(producer, "operation")
    return "phase1-discover" if producer == "discovery" else "phase1-synthesizer"


def producer_role(producer, role):
    if producer in {"tracker", "why1", "constitution", "what", "why2", "lexicon", "feasibility", "strategy", "alignment"} and role in {"producer", "reviewer"}:
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


def synthesis_input_source(state, operation_id=None):
    """Actual accepted parent; the original source and refresh origin never move."""
    selected = producer_operation_id(state, "synthesizer", operation_id)
    if selected.startswith("synthesis-"):
        return synthesis_source(state)
    row = tracker_round(state, selected, producer="synthesizer")
    if "execution_input" not in row:
        raise ValueError("Synthesis refresh input is not bound")
    return deepcopy(row["execution_input"]["source"])


def producer_operation_id(state, producer, operation_id=None, *, repair_unit=None):
    if repair_unit is not None:
        repair_record(state, producer, repair_unit)
        expected = "discovery-repair-" + repair_unit
        if operation_id is not None and operation_id != expected:
            raise ValueError("repair operation changed")
        return expected
    if producer in {"tracker", "why1", "what", "why2", "lexicon", "feasibility", "strategy", "alignment"}:
        row = tracker_round(state, operation_id, producer=producer)
        if row is None:
            raise ValueError("Tracker round not selected")
        return producer + "-" + row["source"]["dispatch_id"]
    producer_key(producer, "operation")
    if producer == "discovery":
        return bootstrap_from_state(state)["selection"]["operation_id"]
    if producer == "constitution":
        from harness.discovery_constitution import constitution_source
        source = constitution_source(state)
        if source is None:
            raise ValueError("Constitution source not selected")
        original = "constitution-" + source["dispatch_id"]
        rounds = tracker_rounds(state, producer)
        selected = operation_id if operation_id is not None else (original if rounds is None else rounds["active"])
        if selected != original and (rounds is None or selected not in rounds["rounds"]):
            raise ValueError("Constitution operation changed")
        return selected
    source = synthesis_source(state)
    if source is None:
        raise ValueError("synthesis source not selected")
    original = "synthesis-" + source["dispatch_id"]
    if operation_id == original:
        return original
    if operation_id is not None or rounds_key(producer) in state:
        row = tracker_round(state, operation_id, producer=producer)
        if row is None:
            raise ValueError("synthesis round not selected")
        return producer + "-" + row["source"]["dispatch_id"]
    return original


def identity_spec_tree(tree):
    """Identity view only; callers authenticate metadata and retain raw guards."""
    metadata = tree.path + "/.echelon"
    return replace(tree,
        directories=tuple(row for row in tree.directories if row.path != metadata and not row.path.startswith(metadata + "/")),
        files=tuple(row for row in tree.files if not row.path.startswith(metadata + "/")))
