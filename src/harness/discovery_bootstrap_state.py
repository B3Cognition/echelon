"""Pure bootstrap selection/transitions; durable state and registry have owners."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from harness.element_identity_lifecycle import text
from harness.element_identity_managed import ManagedIdentityRequest
from harness.element_identity_state import validate_managed_identity_record
from harness.squad_publication import _marker_from
from harness.squad_source_manifest_codec import decode_source_manifest


BOOTSTRAP_KEY = "managed_discovery_bootstrap"
_SELECTION_FIELDS = {"spec_id", "run_id", "operation_id", "project_root", "run_dir", "spec_path",
                     "workspace_uuid", "epoch_uuid", "capture_marker"}


def validate_selection(value):
    if type(value) is not dict or set(value) != _SELECTION_FIELDS:
        raise ValueError("invalid discovery bootstrap selection")
    for key in _SELECTION_FIELDS - {"capture_marker"}:
        if type(value[key]) is not str:
            raise ValueError("invalid discovery bootstrap identifier")
        text(value[key], key)
    ManagedIdentityRequest(value["workspace_uuid"], value["epoch_uuid"], value["run_id"],
        "source", value["spec_path"], "registration", "0" * 64)
    for key in ("project_root", "run_dir"):
        path = Path(value[key])
        if not path.is_absolute() or str(path) != value[key] or ".." in path.parts:
            raise ValueError("bootstrap paths must be canonical absolute paths")
    if (Path(value["run_dir"]).name != value["run_id"]
            or not Path(value["run_dir"]).is_relative_to(value["project_root"])
            or value["run_dir"] == value["project_root"]):
        raise ValueError("bootstrap run is outside its selected workspace")
    marker = value["capture_marker"]
    if type(marker) is not dict or _marker_from(marker).to_dict() != marker:
        raise ValueError("invalid bootstrap capture marker")
    return deepcopy(value)


def bootstrap_ids(selection):
    selection = validate_selection(selection)
    digest = hashlib.sha256(json.dumps(selection, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True).encode("ascii")).hexdigest()
    return {"context_id": "discovery-context-" + digest,
            "source_registration_operation_id": "discovery-source-" + digest,
            "operation_id": "discovery-genesis-" + digest}


def validate_bootstrap_manifest(selection, payload):
    if type(payload) is not str:
        raise ValueError("bootstrap source manifest must be canonical text")
    manifest = decode_source_manifest(payload)
    value = json.loads(manifest.payload)
    trees = value["trees"]
    if (value["files"] or len(trees) != 1 or trees[0]["path"] != selection["spec_path"]
            or trees[0]["exists"] != "true" or trees[0]["files"]
            or len(trees[0]["directories"]) != 1
            or trees[0]["directories"][0]["path"] != selection["spec_path"]):
        raise ValueError("bootstrap requires its exact empty selected spec tree")
    return manifest


def bootstrap_genesis(selection, payload):
    selection = validate_selection(selection)
    manifest = validate_bootstrap_manifest(selection, payload)
    ids = bootstrap_ids(selection)
    return {"version": "1", **{key: selection[key] for key in (
        "workspace_uuid", "epoch_uuid", "spec_id", "run_id", "spec_path")}, **ids,
        "source_manifest_sha256": manifest.sha256}


def bootstrap_from_state(state):
    if BOOTSTRAP_KEY not in state:
        return None
    value = state[BOOTSTRAP_KEY]
    if (type(value) is not dict or set(value) != {"schema_version", "selection", "source_manifest"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1):
        raise ValueError("invalid discovery bootstrap record")
    selected = validate_selection(value["selection"])
    if (state.get("spec_id"), state.get("run_id"), state.get("squad_dir")) != (
            selected["spec_id"], selected["run_id"], selected["run_dir"]):
        raise ValueError("discovery bootstrap state association changed")
    if value["source_manifest"] is not None:
        validate_bootstrap_manifest(selected, value["source_manifest"])
    if "managed_identity" in state:
        if validate_managed_identity_record(state["managed_identity"]) != bootstrap_genesis(selected, value["source_manifest"]):
            raise ValueError("managed genesis differs from selected bootstrap")
    return deepcopy(value)


def advance_bootstrap_state(state, selection, step, payload=None):
    selection = validate_selection(selection)
    current = bootstrap_from_state(state)
    if (state.get("run_id") != selection["run_id"] or state.get("squad_dir") != selection["run_dir"]
            or state.get("spec_id") not in (None, selection["spec_id"])
            or state.get("phase") != "phase1-discover" or state.get("status") != "running"
            or state.get("_spec_step_effect_plan") is not None
            or state.get("_spec_step_publication_plan") is not None):
        raise ValueError("bootstrap is outside selected fresh discovery state")
    if current is not None and current["selection"] != selection:
        raise ValueError("discovery bootstrap selection is immutable")
    result = deepcopy(state)
    if step == "prepare":
        if current is None:
            if "managed_identity" in state:
                raise ValueError("bootstrap cannot enroll an already managed run")
            result["spec_id"] = selection["spec_id"]
            result[BOOTSTRAP_KEY] = dict(schema_version=1, selection=selection, source_manifest=None)
    elif step == "capture":
        if current is None:
            raise ValueError("bootstrap selection is missing")
        validate_bootstrap_manifest(selection, payload)
        if current["source_manifest"] not in (None, payload):
            raise ValueError("bootstrap source selection changed")
        result[BOOTSTRAP_KEY]["source_manifest"] = payload
    elif step == "complete":
        if current is None or current["source_manifest"] is None:
            raise ValueError("bootstrap source capture is missing")
        expected = bootstrap_genesis(selection, current["source_manifest"])
        if validate_managed_identity_record(payload) != expected:
            raise ValueError("bootstrap genesis differs from selected request")
        result["managed_identity"] = expected
    else:
        raise ValueError("unknown bootstrap transition")
    bootstrap_from_state(result)
    return result
