"""Pure repair association and attempt transitions owned by Squad state.

These records are not report provenance or permission to dispatch. The runtime
caller must authenticate the accepted source and requesting review under its
execution leases. Original discovery records are never rotated or replaced.
"""
from copy import deepcopy
import hashlib
import json
import re

from harness.discovery_bootstrap_state import bootstrap_from_state
from harness.discovery_semantics import DiscoveryAssignment


DISCOVERY_REPAIRS_KEY = "managed_discovery_repairs"
_SOURCE_FIELDS = ("dispatch_id", "completion_intent_sha256", "completion_receipts_sha256",
                  "completed_publication_binding_sha256")


def _require(value):
    if not value:
        raise ValueError("invalid discovery repair state")


def _closed(value, keys):
    _require(type(value) is dict and set(value) == set(keys))


def _sha(value, digits=64):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{" + str(digits) + "}", value) is not None)


def _text(value):
    _require(type(value) is str and bool(value.strip()) and "\x00" not in value)


def normalize_selection(state, value):
    bootstrap = bootstrap_from_state(state)
    _require(bootstrap is not None and "managed_identity" in state)
    _closed(value, ("source", "origin", "findings", "artifact_paths", "editable_revisions"))
    _closed(value["source"], _SOURCE_FIELDS)
    for key, item in value["source"].items():
        _sha(item, 32 if key == "dispatch_id" else 64)
    _closed(value["origin"], ("review_id", "return_phase"))
    _text(value["origin"]["review_id"])
    phase = value["origin"]["return_phase"]
    _require(type(phase) is str and re.fullmatch(r"phase[0-9]+-[a-z0-9-]+", phase) is not None)
    findings = value["findings"]
    _require(type(findings) is list and bool(findings))
    for finding in findings:
        _closed(finding, ("key", "detail"))
        _text(finding["key"])
        _text(finding["detail"])
    _require(len({row["key"] for row in findings}) == len(findings))
    _require(type(value["artifact_paths"]) is list and type(value["editable_revisions"]) is list)
    selected = bootstrap["selection"]
    DiscoveryAssignment("repair-selection", "selection", selected["spec_id"], selected["run_id"],
        "propose", "0" * 64, tuple(value["artifact_paths"]),
        tuple(tuple(pair) for pair in value["editable_revisions"])).identity()
    _require(all(type(pair) is list for pair in value["editable_revisions"]))
    _require(len(json.dumps(value, allow_nan=False).encode("utf-8")) <= 1024 * 1024)
    normalized = deepcopy(value)
    normalized["findings"] = sorted(normalized["findings"], key=lambda row: row["key"])
    normalized["artifact_paths"].sort()
    normalized["editable_revisions"].sort()
    # Report identity and accepted source select the unit. Changed instructions,
    # target scope, candidate bytes or finding order cannot mint another budget.
    identity = [selected["spec_id"], selected["run_id"], value["source"]["dispatch_id"], value["origin"]["review_id"]]
    unit = hashlib.sha256(json.dumps(identity, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
    return unit, normalized


def repairs_from_state(state):
    if DISCOVERY_REPAIRS_KEY not in state:
        return None
    value = state[DISCOVERY_REPAIRS_KEY]
    _closed(value, ("schema_version", "units"))
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1
        and type(value["units"]) is dict and bool(value["units"]))
    sources, unfinished = set(), 0
    for unit, record in value["units"].items():
        _closed(record, ("selection", "attempts", *(("execution",) if "execution" in record else ())))
        expected, selected = normalize_selection(state, record["selection"])
        _require(unit == expected and selected == record["selection"])
        if "execution" in record:
            from harness.discovery_operation_state import validate_binding
            from harness.discovery_turn_state import discovery_turns_from_state
            _closed(record["execution"], ("binding", "turns"))
            validate_binding(state, record["execution"]["binding"], repair_unit=unit)
            discovery_turns_from_state(state, repair_unit=unit)
        source = selected["source"]["dispatch_id"]
        _require(source not in sources)
        sources.add(source)
        attempts = record["attempts"]
        _require(type(attempts) is list and len(attempts) <= 3)
        for index, attempt in enumerate(attempts, 1):
            _closed(attempt, ("number", "result"))
            _require(type(attempt["number"]) is int and attempt["number"] == index)
            result = attempt["result"]
            if result is not None:
                _closed(result, ("status", "candidate_sha256", "findings_sha256", "progress_sha256"))
                _require(type(result["status"]) is str and result["status"] in {"accepted", "rejected"})
                for key in ("candidate_sha256", "findings_sha256", "progress_sha256"):
                    _sha(result[key])
            if index < len(attempts):
                _require(result is not None and result["status"] == "rejected")
        if len(attempts) == 3:
            _require(attempts[0]["result"]["progress_sha256"] != attempts[1]["result"]["progress_sha256"])
        if not attempts or attempts[-1]["result"] is None or attempts[-1]["result"]["status"] != "accepted":
            unfinished += 1
    _require(unfinished <= 1)
    return deepcopy(value)


def prepare_repair(state, selection):
    unit, selected = normalize_selection(state, selection)
    retained = repairs_from_state(state) or dict(schema_version=1, units={})
    if unit in retained["units"]:
        _require(retained["units"][unit]["selection"] == selected)
        return deepcopy(state)
    dispatch = state.get("last_dispatch")
    _require(type(dispatch) is dict and dispatch.get("post_dispatch_complete") is True
        and all(dispatch.get(key) == selected["source"][key] for key in _SOURCE_FIELDS)
        and not any(key in state for key in ("_spec_step_effect_plan", "_spec_step_publication_plan")))
    for previous in retained["units"].values():
        attempts = previous["attempts"]
        _require(attempts and attempts[-1]["result"] is not None
            and attempts[-1]["result"]["status"] == "accepted"
            and previous["selection"]["source"]["dispatch_id"] != selected["source"]["dispatch_id"])
    retained["units"][unit] = dict(selection=selected, attempts=[])
    updated = {**state, DISCOVERY_REPAIRS_KEY: retained}
    repairs_from_state(updated)
    return updated


def advance_repair(state, unit, event, result=None):
    _sha(unit)
    retained = repairs_from_state(state)
    _require(retained is not None and unit in retained["units"])
    attempts = retained["units"][unit]["attempts"]
    if event == "begin" and result is None:
        if not attempts or attempts[-1]["result"] is not None:
            _require(len(attempts) < 3 and (not attempts or attempts[-1]["result"]["status"] == "rejected"))
            if len(attempts) == 2:
                _require(attempts[0]["result"]["progress_sha256"] != attempts[1]["result"]["progress_sha256"])
            attempts.append(dict(number=len(attempts) + 1, result=None))
    elif event == "finish" and type(result) is dict and attempts:
        _require(attempts[-1]["result"] is None or attempts[-1]["result"] == result)
        attempts[-1]["result"] = deepcopy(result)
    else:
        raise ValueError("invalid discovery repair transition")
    updated = {**state, DISCOVERY_REPAIRS_KEY: retained}
    repairs_from_state(updated)
    return updated
