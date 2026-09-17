"""Forward restoration planning; selected completion provenance stays external.

This read-only helper cannot select a quality candidate or authorize a write.
Its caller must bind the exact selected history/artifacts to native completion.
The existing publication owner validates and applies the resulting CAS changes.
"""
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from harness.element_identity_json import strict_json
from harness.element_identity_lifecycle import ElementSnapshotMembership, text
from harness.element_identity_snapshot import IdentityHistorySnapshot


def _require(condition):
    if not condition:
        raise ValueError("restoration history is not an exact retained snapshot")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _selected_history(selected, current):
    _require(type(selected) is IdentityHistorySnapshot and type(selected.payload) is str)
    _require(hashlib.sha256(selected.payload.encode("ascii")).hexdigest() == selected.sha256)
    value = strict_json(selected.payload)
    required = {"version", "workspace_uuid", "epoch_uuid", "spec_id", "entities",
                "revisions", "lineage", "reference_claims", "issue_occurrences"}
    _require(type(value) is dict and value.get("version") in {"1", "2"}
        and set(value) == required | ({"snapshot_memberships"} if value["version"] == "2" else set())
        and _json(value) == selected.payload)
    _require(all(value[key] == current[key] for key in ("workspace_uuid", "epoch_uuid", "spec_id")))
    for table in ("revisions", "lineage", "reference_claims", "issue_occurrences", "snapshot_memberships"):
        rows = value.get(table, [])
        _require(type(rows) is list)
        retained = {_json(row) for row in current.get(table, [])}
        selected_rows = {_json(row) for row in rows}
        _require(len(selected_rows) == len(rows) and selected_rows <= retained)
    _require(type(value["entities"]) is list)
    entities = {row["element_id"]: row for row in current["entities"]}
    revisions = {(row["element_id"], row["revision"]): row for row in value["revisions"]}
    _require(len({row["element_id"] for row in value["entities"]}) == len(value["entities"]))
    for row in value["entities"]:
        current_row = entities.get(row["element_id"])
        _require(current_row is not None and set(row) == set(current_row)
            and all(row[key] == current_row[key] for key in set(row) - {"revision", "status"}))
        head = revisions.get((row["element_id"], row["revision"]))
        _require((row["revision"] is None and row["status"] == "imported")
            or (head is not None and row["status"] == head["status"]))
    return value


def _present(history, entity):
    if entity is None or entity["status"] != "active":
        return False
    rows = [row for row in history.get("snapshot_memberships", []) if row["element_id"] == entity["element_id"]]
    return not rows or max(rows, key=lambda row: (len(row["revision"]), row["revision"]))["present"]


def requirement_restoration_changes(store, *, spec_id, selected_history, snapshot_id):
    """Describe exact old requirement membership/content using forward revisions."""
    return _requirement_restoration_changes(current_history=store.identity_history(spec_id=spec_id),
        selected_history=selected_history, snapshot_id=snapshot_id)


def _requirement_restoration_changes(*, current_history, selected_history, snapshot_id):
    """Replay a captured plan; caller must authenticate both completion histories.

    No live-store authority is inferred from these detached images. In particular,
    recovery must retain the original before-history after the child is applied.
    The publication owner's immutable request/CAS checks authorize any write.
    """
    text(snapshot_id, "snapshot_id")
    _require(type(current_history) is IdentityHistorySnapshot)
    current = strict_json(current_history.payload)
    current = _selected_history(current_history, current)
    selected = _selected_history(selected_history, current)
    targets = {row["element_id"]: row for row in selected["entities"]}
    revisions = {(row["element_id"], row["revision"]): row for row in current["revisions"]}
    changes = []
    for entity in current["entities"]:
        if entity["kind"] not in {"FR", "NFR", "AC"}:
            continue
        label = entity["element_id"]
        target = targets.get(label)
        desired, present = _present(selected, target), _present(current, entity)
        if desired:
            _require(entity["status"] == "active")
            target_revision = target["revision"]
            if present and revisions[label, entity["revision"]]["content"] == revisions[label, target_revision]["content"]:
                continue
            changes.append(ElementSnapshotMembership(label, entity["revision"], True, target_revision, snapshot_id))
        elif present:
            changes.append(ElementSnapshotMembership(label, entity["revision"], False, None, snapshot_id))
    return tuple(changes)


def retained_quality_candidate_history(project_root, run_dir, state, *, source, selected):
    """Read the exact selected assessment's history along authenticated ancestry.

    This is not candidate-selection or restoration authority. The native
    completion owner supplies its retained parent pointer and selected restore;
    it still owns policy, effect execution and release. No current artifact is
    interpreted as an old assessment, and no identity history is rewound.
    """
    try:
        return _retained_candidate_history(Path(project_root), Path(run_dir), state, source, selected)
    except Exception:
        raise ValueError("selected candidate has no exact retained managed history") from None


def _retained_candidate_history(root, run, state, source, selected):
    from harness.discovery_bootstrap_state import bootstrap_from_state
    from harness.discovery_completion import _released_discovery_projections, _retained_input_projection, _document
    from harness.element_identity_store import IdentityStore
    from harness.proportional_quality import (
        PreflightedCandidateRestore, _is_candidate_id, preflight_quality_candidate_restore,
        quality_candidate_effect_payload,
    )
    from harness.proportional_quality_effects import _preflight_quality_effect_receipt
    _require(type(selected) is PreflightedCandidateRestore)
    candidate = selected.snapshot.manifest
    _require(_is_candidate_id(candidate.candidate_id))
    selection = bootstrap_from_state(state)["selection"]
    _require(str(root) == selection["project_root"] and str(run) == selection["run_dir"])
    actual = preflight_quality_candidate_restore(project_root=root, spec_dir=root / selection["spec_path"],
        manifest_path=run / "quality-candidates" / (candidate.candidate_id + ".json"),
        expected_candidate_id=candidate.candidate_id, expected_manifest_sha256=selected.snapshot.sha256)
    _require(actual == selected)
    # A proof-addressed individual row does not prove that it is an ancestor.
    # Authenticate the complete retained chain before selecting any row from it.
    _released_discovery_projections(root, run, state, source=source, historical=True)
    store = IdentityStore.open(root)
    seen = set()
    while source is not None:
        operation_id = "discovery-completion-" + source["dispatch_id"]
        _require(operation_id not in seen)
        seen.add(operation_id)
        binding, _, _ = _retained_input_projection(root, run, state, store,
            operation_id=operation_id, source=source, require_checkpoint=False)
        if binding.producer == "why2" and not binding.clarification:
            row = store.identity_publication(spec_id=selection["spec_id"], operation_id=operation_id)
            proof = _document(row["completion_payload"])
            retained = proof["proof" if proof["version"] == 3 else "checkpoint"]
            effect = retained["intent"]["quality_effect"]
            if effect.get("candidate", {}).get("candidate_id") == candidate.candidate_id:
                _require(effect["kind"] == "proportional_quality" and effect["operation"] == "candidate"
                    and effect["candidate"] == quality_candidate_effect_payload(replace(candidate, checkpoint_commit="0" * 40)))
                receipt = _preflight_quality_effect_receipt(effect, "candidate", retained["receipts"]["effects"].get("quality"))
                _require(receipt is not None and receipt["candidate"]["candidate_id"] == candidate.candidate_id
                    and receipt["candidate"]["manifest_sha256"] == selected.snapshot.sha256
                    and receipt["candidate"]["checkpoint"]["commit"] == candidate.checkpoint_commit)
                history = IdentityHistorySnapshot(**binding.candidate["history"])
                _selected_history(history, strict_json(store.identity_history(spec_id=binding.spec_id).payload))
                return history, dict(source)
        source = binding.recovery.get("source_completion")
    raise ValueError("selected candidate is not in the retained completion ancestry")
