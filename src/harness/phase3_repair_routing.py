"""Pure Phase 3 work effects consumed by the existing sealed controller route."""
from __future__ import annotations

from dataclasses import asdict
from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json

from harness.issue_identity import record_issue_resolution, issue_fingerprint
from harness.phase3_repair import RepairContractError, RepairIdentity, validate_repair_action

OWNER_FILES = {
    "phase3-how": frozenset({"plan.md", "architecture.md", "research.md", "data-model.md"}),
    "phase3-sentinel": frozenset({"test-strategy.md", "test-architecture.md", "coverage-map.md"}),
    "phase3-plan": frozenset({"tasks.md", "critical-path.md", "risk-matrix.md", "dependencies.md"}),
}


def owned_artifacts(owner: str, manifest: Mapping[str, str]) -> frozenset[str]:
    files = OWNER_FILES.get(owner, frozenset())
    return frozenset(path for path in manifest if path in files or
        (owner == "phase3-how" and path.startswith(("contracts/", "adr/"))))


def planner_review_route(state: Mapping, manifest: Mapping[str, str], *,
                         detail: str, blocker: object = None) -> tuple[str | None, dict]:
    """A blocked consumer may return a submitted repair to review, not approve it.

    Only the existing selected, identity-bound submission grants this route.
    Planner prose is diagnostic, never authority to choose an owner or answer.
    The receipt bounds identical handoffs across restarts; normal review and
    dispatch budgets still apply, including when review exhausts repair budget.
    """
    if state.get("phase") != "phase3-plan" or state.get("autonomy_mode") != "banzai":
        return None, {}
    entry = (state.get("issue_resolution_ledger") or {}).get(state.get("selected_issue_resolution"))
    if not isinstance(entry, Mapping) or entry.get("status") != "repaired" or entry.get("repair_phase") not in OWNER_FILES:
        return None, {}
    try:
        identity = RepairIdentity(**entry["repair_identity"])
        if identity.run_id != state.get("run_id"):
            raise RepairContractError("submitted repair belongs to another run")
    except (RepairContractError, TypeError, KeyError):
        return "terminal-blocked", {"status": "blocked", "blocked_reason": "repair_review_stale"}
    receipt = {"identity": asdict(identity), "input_manifest": dict(manifest),
               "submission_count": entry.get("submission_count", 0)}
    key = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
    handoffs = dict(state.get("phase3_planner_review_handoffs") or {})
    if key in handoffs:
        return "terminal-blocked", {"status": "blocked", "blocked_reason": "repair_no_progress"}
    summary = {"detail": detail[:2000]}
    fields = {"issue_id", "owner_phase", "detail", "next_action"}
    if (isinstance(blocker, Mapping) and set(blocker) == fields
            and all(isinstance(value, str) and 0 < len(value.strip()) <= 2000 for value in blocker.values())):
        summary = dict(blocker)
    handoffs[key] = receipt
    return "phase3-consensus", {
        "phase3_planner_review_handoffs": handoffs,
        "phase3_last_blocker": {"producer": "PLAN", **summary, **receipt},
        "status": "running",
        "blocked_reason": None,
    }


def has_phase3_repairs(state: Mapping) -> bool:
    def relevant(entry):
        return isinstance(entry, Mapping) and (entry.get("repair_phase") in OWNER_FILES or
            any(relevant(old) for old in entry.get("previous_resolutions") or []))
    return any(relevant(entry) for entry in (state.get("issue_resolution_ledger") or {}).values())


def reconcile_review_state(state: Mapping, manifest: Mapping[str, str]) -> dict:
    """Invalidate all stale closures, including records hidden by label reuse.

    Historical instances get stable internal slots so reviewing one never
    overwrites the newer finding using its former display label.
    """
    updated = deepcopy(dict(state))
    ledger = updated.get("issue_resolution_ledger") or {}
    receipts = updated.get("phase3_issue_reviews") or {}
    historical = []

    def invalidate(entry):
        if not isinstance(entry, dict) or entry.get("repair_phase") not in OWNER_FILES:
            return
        if entry.get("status") == "validated" and not entry.get("repair_identity"):
            entry["repair_identity"] = asdict(RepairIdentity(str(state.get("run_id") or ""),
                entry.get("issue_fingerprint") or issue_fingerprint(str(entry.get("title", "")), str(entry.get("decision", ""))),
                state.get("state_revision", 0)))
        receipt = receipts.get(entry.get("last_review_dispatch_id"))
        if entry.get("status") == "validated" and (
                not isinstance(receipt, Mapping) or receipt.get("reviewed_artifacts") != dict(manifest)):
            entry.update(status="repaired", review_revalidation_required=True)

    for issue_id, entry in list(ledger.items()):
        if not isinstance(entry, dict):
            continue
        invalidate(entry)
        for record in entry.get("previous_resolutions") or []:
            invalidate(record)
            if isinstance(record, dict) and record.get("review_revalidation_required"):
                historical.append((issue_id, record))
    for issue_id, record in historical:
        digest = hashlib.sha256(json.dumps(record["repair_identity"], sort_keys=True).encode()).hexdigest()
        slot = f"{issue_id}@{digest}"
        # Keep a historical receipt, but never continually resurrect it after
        # its active identity-bound slot has already been reviewed again.
        if slot not in ledger:
            ledger[slot] = deepcopy(record)
    for issue_id, entry in ledger.items():
        if (isinstance(entry, dict) and entry.get("review_revalidation_required")
                and not updated.get("selected_issue_resolution")):
            updated["selected_issue_resolution"] = issue_id
            updated["issue_resolution_repair_baseline"] = {"issue_id": issue_id, "repair_phase": entry["repair_phase"]}
            updated["issue_resolution_recovery"] = {"issue_id": issue_id, "status": "awaiting_review"}
    if ledger:
        updated["issue_resolution_ledger"] = ledger
    return updated


def phase3_work_route(state: Mapping, manifest: Mapping[str, str], *, current_findings: frozenset[str] | None = None) -> tuple[str | None, dict]:
    """Assign technical work only; all decision kinds keep existing authority."""
    if state.get("phase") != "phase3-consensus":
        return None, {}
    if state.get("phase3_final_review"):
        # A completed planner is not a reviewed final candidate. All modes
        # return through the ordinary controller loop, including fresh specs.
        return "phase3-consensus", {}
    selected = state.get("selected_issue_resolution")
    ledger = state.get("issue_resolution_ledger") or {}
    entry = ledger.get(selected)
    at_cap = (int(state.get("max_iterations") or 0) > 0
              and int(state.get("iteration") or 0) >= int(state["max_iterations"]))
    if (
        selected
        and isinstance(entry, Mapping)
        and current_findings is not None
        and entry.get("issue_fingerprint")
        and entry.get("issue_fingerprint") not in current_findings
    ):
        # WHY3 display IDs are local to each report revision. A new finding
        # may reuse ISS-001 while describing different work. Never let that
        # label reuse carry an old selected owner into the new review.
        repair_phase = str(state.get("why3_repair_phase") or "").strip()
        allowed = frozenset(OWNER_FILES) | frozenset({"phase1-discover", "phase1-what"})
        if at_cap:
            return "terminal-blocked", {
                "status": "blocked",
                "blocked_reason": "repair_budget_exhausted",
            }
        if repair_phase not in allowed:
            repair_phase = "phase3-consensus"
        return repair_phase, {
            "selected_issue_resolution": None,
            "issue_resolution_repair_baseline": None,
            "issue_resolution_recovery": {
                "issue_id": selected,
                "status": "superseded",
            },
            "why3_repair_phase": repair_phase,
        }
    reconciled = reconcile_review_state(state, manifest)
    if reconciled != state:
        return "phase3-consensus", {key: value for key, value in reconciled.items() if state.get(key) != value}
    selected = state.get("selected_issue_resolution")
    ledger = state.get("issue_resolution_ledger") or {}
    entry = ledger.get(selected)
    if isinstance(entry, Mapping) and entry.get("review_revalidation_required"):
        return "phase3-consensus", {}
    if state.get("autonomy_mode") != "banzai":
        return None, {}
    if isinstance(entry, Mapping) and entry.get("status") == "repaired" and entry.get("repair_phase") in OWNER_FILES:
        receipt = (state.get("phase3_issue_reviews") or {}).get(entry.get("last_review_dispatch_id"))
        if not isinstance(receipt, Mapping) or receipt.get("reviewed_artifacts") != dict(manifest):
            return "phase3-consensus", {}
        if receipt.get("outcome") in {"unresolved", "unverifiable"}:
            if at_cap:
                return "terminal-blocked", {"status": "blocked", "blocked_reason": "repair_budget_exhausted"}
            if int(entry.get("reviewed_unresolved_count", 0)) >= 2:
                return "terminal-blocked", {"status": "blocked", "blocked_reason": "repair_no_progress"}
            updated = deepcopy(ledger)
            updated[selected]["status"] = "selected"
            return entry["repair_phase"], {"issue_resolution_ledger": updated,
                "why3_repair_phase": entry["repair_phase"]}
    pending = state.get("phase3_pending_action")
    if not selected and any(isinstance(item, Mapping) and item.get("review_revalidation_required") for item in ledger.values()):
        return "phase3-consensus", {}
    if not isinstance(pending, Mapping) or state.get("selected_issue_resolution"):
        return None, {}
    if state.get("why3_verdict") != "FAIL":
        return None, {}
    try:
        identity = RepairIdentity(**pending["identity"])
        if current_findings is not None and identity.issue_fingerprint not in current_findings:
            return None, {"phase3_pending_action": None}
        if identity.run_id != state.get("run_id") or pending["input_manifest"] != dict(manifest):
            raise RepairContractError("technical work inputs changed after assessment")
        payload = pending["assessment"]
        action = validate_repair_action(payload, expected=identity,
            allowed_owner_phases=frozenset(OWNER_FILES),
            allowed_artifacts=owned_artifacts(payload.get("owner_phase"), manifest))
        if any(ref.split("#", 1)[0] not in manifest for ref in action.evidence_refs):
            raise RepairContractError("technical work cites undispatched evidence")
    except (RepairContractError, TypeError, KeyError, AttributeError):
        return "terminal-blocked", {"status": "blocked", "blocked_reason": "repair_action_unclassified"}
    if action.kind == "external_prerequisite":
        return "terminal-blocked", {"status": "blocked", "blocked_reason": "repair_external_prerequisite"}
    if action.kind == "human_decision":
        return "terminal-blocked", {"status": "blocked", "blocked_reason": "repair_human_decision"}
    if action.kind != "investigate_or_design":
        # A typed assessment is not an eligible-option certificate. The
        # existing decision/adoption flow must establish that authority.
        return "terminal-blocked", {"status": "blocked", "blocked_reason": "repair_action_unclassified"}
    if at_cap:
        return "terminal-blocked", {"status": "blocked", "blocked_reason": "repair_budget_exhausted"}
    issue_id = pending["issue_id"]
    entry = {"issue_id": issue_id, "title": pending["title"], "status": "selected",
        "issue_fingerprint": identity.issue_fingerprint, "repair_identity": asdict(identity),
        "repair_phase": action.owner_phase, "repair_action": dict(payload),
        "submission_count": 0, "reviewed_unresolved_count": 0}
    return action.owner_phase, {
        "issue_resolution_ledger": record_issue_resolution(state.get("issue_resolution_ledger"), issue_id, entry),
        "selected_issue_resolution": issue_id,
        "issue_resolution_repair_baseline": {"issue_id": issue_id, "repair_phase": action.owner_phase},
        "issue_resolution_recovery": {"issue_id": issue_id, "status": "work_assigned"},
        "phase3_pending_action": None,
        "why3_repair_phase": action.owner_phase,
    }
