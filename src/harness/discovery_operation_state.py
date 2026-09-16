"""Pure selected discovery operation and durable attempt transitions."""
from copy import deepcopy
import json
from pathlib import PurePosixPath
import re

from harness.discovery_bootstrap_state import bootstrap_from_state
from harness.discovery_semantics import DiscoveryAssignment
from harness.discovery_producer import producer_component, with_producer_component, producer_phase, producer_operation_id


DISCOVERY_OPERATION_KEY = "managed_discovery_operation"


def _closed(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError("invalid discovery operation fields")


def _digest(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid discovery operation digest")


def validate_binding(state, binding, producer="discovery", *, operation_id=None, repair_unit=None):
    _closed(binding, ("operation_id", "spec_id", "run_id", "input_tree", "artifact_paths",
        "editable_revisions", "unowned_writable_paths", "intent", "fingerprint"))
    selected = bootstrap_from_state(state)
    if selected is None or "managed_identity" not in state:
        raise ValueError("completed discovery bootstrap required")
    if (binding["operation_id"] != producer_operation_id(state, producer, operation_id, repair_unit=repair_unit)
            or any(binding[key] != selected["selection"][key] for key in ("spec_id", "run_id"))):
        raise ValueError("discovery operation selection changed")
    if any(type(binding[key]) is not list for key in ("artifact_paths", "editable_revisions", "unowned_writable_paths")):
        raise ValueError("invalid discovery scope")
    DiscoveryAssignment(binding["operation_id"], "selection", binding["spec_id"], binding["run_id"],
        "propose", binding["fingerprint"], tuple(binding["artifact_paths"]),
        tuple(tuple(pair) for pair in binding["editable_revisions"]), producer=producer).identity()
    path = binding["input_tree"]
    if type(path) is not str or not path or PurePosixPath(path).is_absolute() or any(
            part in {"", ".", ".."} for part in path.split("/")) or "\x00" in path or "\\" in path:
        raise ValueError("invalid discovery input tree")
    unowned = binding["unowned_writable_paths"]
    if len(set(unowned)) != len(unowned) or not set(unowned) <= set(binding["artifact_paths"]):
        raise ValueError("invalid discovery unowned scope")
    intent = binding["intent"]
    if (type(intent) is not dict or intent.get("kind") not in ({"specify"} if producer == "what" else {"validate"} if producer == "why2" else {"create", "repair"} if producer == "discovery" else {"constitute"} if producer == "constitution" else {"challenge"} if producer == "why1" else {"track"} if producer == "tracker" else {"synthesize"})
            or type(intent.get("request")) is not str or not intent["request"].strip()
            or (intent["kind"] == "repair" and (not intent.get("origin") or not intent.get("findings")))):
        raise ValueError("discovery requires an explicit bound origin")
    if repair_unit is not None:
        from harness.discovery_producer import repair_record
        claim = repair_record(state, producer, repair_unit)["selection"]
        if (intent["kind"] != "repair" or set(intent) != {"kind", "request", "origin", "findings"}
                or any(binding[key] != claim[key] for key in ("artifact_paths", "editable_revisions"))
                or binding["unowned_writable_paths"]
                or any(intent[key] != claim[key] for key in ("origin", "findings"))):
            raise ValueError("repair execution scope changed")
    if len(json.dumps(binding, sort_keys=True, allow_nan=False).encode("utf-8")) > 1024 * 1024:
        raise ValueError("discovery selection exceeds limit")


def operation_from_state(state, producer="discovery", *, operation_id=None, repair_unit=None):
    value = producer_component(state, producer, "operation", operation_id=operation_id, repair_unit=repair_unit)
    if value is None:
        return None
    _closed(value, ("schema_version", "binding", "attempts"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("invalid discovery operation version")
    validate_binding(state, value["binding"], producer, operation_id=operation_id, repair_unit=repair_unit)
    attempts = value["attempts"]
    if type(attempts) is not list or len(attempts) > 3:
        raise ValueError("invalid discovery attempt count")
    for index, attempt in enumerate(attempts, 1):
        _closed(attempt, ("number", "result"))
        if type(attempt["number"]) is not int or attempt["number"] != index:
            raise ValueError("invalid discovery attempt number")
        result = attempt["result"]
        if result is not None:
            _closed(result, ("status", "candidate_sha256", "findings_sha256", *(("progress_sha256",) if repair_unit is not None else ())))
            if repair_unit is not None:
                _digest(result["progress_sha256"])
            if type(result["status"]) is not str or result["status"] not in {"accepted", "rejected"}:
                raise ValueError("invalid discovery attempt result")
            _digest(result["candidate_sha256"])
            _digest(result["findings_sha256"])
        if index < len(attempts) and (result is None or result["status"] != "rejected"):
            raise ValueError("discovery attempt follows unfinished or accepted work")
    return deepcopy(value)


def advance_operation(state, binding, event, result=None, producer="discovery", *, repair_unit=None):
    validate_binding(state, binding, producer, repair_unit=repair_unit)
    retained = operation_from_state(state, producer, repair_unit=repair_unit)
    if retained is not None and retained["binding"] != binding:
        raise ValueError("discovery operation is immutable")
    if repair_unit is not None:
        from harness.discovery_repair_state import advance_repair, repairs_from_state
        from harness.discovery_producer import repair_record
        if event == "prepare" and result is None:
            if retained is not None:
                return deepcopy(state)
            if state.get("phase") != "phase1-discover" or state.get("status") != "running":
                raise ValueError("repair requires active discovery")
            updated = deepcopy(state)
            repair_record(updated, producer, repair_unit)["execution"] = dict(binding=deepcopy(binding), turns=None)
            repairs_from_state(updated)
            return updated
        if retained is None:
            raise ValueError("repair execution not selected")
        return advance_repair(state, repair_unit, event, result)
    if event == "prepare" and result is None:
        if retained is None:
            if state.get("phase") != producer_phase(producer) or state.get("status") != "running":
                raise ValueError("discovery operation requires active discovery")
            retained = dict(schema_version=1, binding=deepcopy(binding), attempts=[])
    elif retained is None:
        raise ValueError("discovery operation was not selected")
    elif event == "begin" and result is None:
        attempts = retained["attempts"]
        if not attempts or attempts[-1]["result"] is not None:
            if len(attempts) >= 3 or (attempts and attempts[-1]["result"]["status"] == "accepted"):
                raise ValueError("discovery attempts exhausted or accepted")
            attempts.append(dict(number=len(attempts) + 1, result=None))
    elif event == "finish" and type(result) is dict and retained["attempts"]:
        attempt = retained["attempts"][-1]
        if attempt["result"] is not None and attempt["result"] != result:
            raise ValueError("discovery attempt result changed")
        attempt["result"] = deepcopy(result)
    else:
        raise ValueError("invalid discovery operation transition")
    updated = with_producer_component(state, producer, "operation", retained)
    operation_from_state(updated, producer)
    return updated
