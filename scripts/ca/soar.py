"""
T-027 through T-033 — SOAR Cognitive Architecture Overlay (CA overlay 6, ADR-005)

Exposes:
  enrich_context(context_pack, run_id) -> dict
  update_soar_memory(outcome, run_id) -> None

Implements a Match-Select-Apply decision cycle using production rules
stored in a run-scoped ProceduralMemoryStore. Standard library only
per ADR-005 OQ-005 resolution.

Human override of P-006 authorized 2026-04-03 (user instruction: "build it anyway").
"""

from __future__ import annotations

import json
import os
import re
import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Seed rules (5 hard-coded production rules)
# ---------------------------------------------------------------------------

SEED_RULES: list[dict] = [
    {
        # seed-001: active_goal only — earliest dispatch, sparse context
        # dispatch_mode=exploratory: no prior artifacts → cast wide, surface unknowns
        # worst-case 200-char check (cycle=100, wme_count=1): 191 chars ✓
        "rule_id": "seed-001",
        "conditions": [{"attr": "active_goal"}],
        "actions": {
            "dispatch_mode": "exploratory",
            "guidance": "No prior artifacts. Cast wide; surface unknowns over depth.",
        },
        "confidence": 0.70,
        "learned": False,
    },
    {
        # seed-002: goal + actr_buffers — declarative knowledge loaded, no workspace
        # dispatch_mode=focused: ACT-R buffers available → use retrieved excerpts specifically
        # worst-case 200-char check (cycle=100, wme_count=2): 193 chars ✓
        "rule_id": "seed-002",
        "conditions": [{"attr": "active_goal"}, {"attr": "actr_buffers"}],
        "actions": {
            "dispatch_mode": "focused",
            "guidance": "ACT-R buffers loaded. Use retrieved excerpts; be specific.",
        },
        "confidence": 0.75,
        "learned": False,
    },
    {
        # seed-003: goal + gwt_workspace — workspace history present, no episodic artifact
        # dispatch_mode=incremental: prior workspace context → build on it, avoid repetition
        # worst-case 200-char check (cycle=100, wme_count=2): 196 chars ✓
        "rule_id": "seed-003",
        "conditions": [{"attr": "active_goal"}, {"attr": "gwt_workspace"}],
        "actions": {
            "dispatch_mode": "incremental",
            "guidance": "Workspace loaded. Build on prior context; avoid repetition.",
        },
        "confidence": 0.75,
        "learned": False,
    },
    {
        # seed-004: full Tier 1+2 — all context layers present, prior artifact exists
        # dispatch_mode=convergent: full context → target depth, resolve open unknowns
        # NOTE: guidance MUST be ≤71 chars. At cycle=100, wme_count=5, budget is tight.
        # worst-case 200-char check (cycle=100, wme_count=5): 197 chars ✓
        "rule_id": "seed-004",
        "conditions": [
            {"attr": "active_goal"},
            {"attr": "actr_buffers"},
            {"attr": "gwt_workspace"},
            {"attr": "episodic_prior_artifact"},
        ],
        "actions": {
            "dispatch_mode": "convergent",
            "guidance": "Full context. Target depth; resolve open unknowns.",
        },
        "confidence": 0.90,
        "learned": False,
    },
    {
        # seed-005: goal + lida_broadcast — COMMANDER broadcast override active
        # dispatch_mode=reactive: broadcast is high-priority context override → process first
        # worst-case 200-char check (cycle=100, wme_count=2): 192 chars ✓
        "rule_id": "seed-005",
        "conditions": [{"attr": "active_goal"}, {"attr": "lida_broadcast"}],
        "actions": {
            "dispatch_mode": "reactive",
            "guidance": "Broadcast active. Treat it as high-priority context override.",
        },
        "confidence": 0.85,
        "learned": False,
    },
]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _repo_root() -> str:
    """Walk up from CWD (then __file__) until .git or .specify directory is found.

    CWD is checked first so that tests using monkeypatch.chdir(tmp_path) get
    isolation without environment patching.
    """
    for start in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        path = start
        while path != os.path.dirname(path):
            if os.path.isdir(os.path.join(path, ".git")):
                return path
            if os.path.isdir(os.path.join(path, ".specify")):
                return path
            path = os.path.dirname(path)
    return os.path.dirname(os.path.abspath(__file__))


def _validate_run_id(run_id: str) -> None:
    """Raise ValueError if run_id contains path-traversal or illegal characters.

    RAR-001 mitigation: prevents writes outside .specify/squad/ directory.
    Allowed: [a-zA-Z0-9_\\-.], max 128 chars. Rejects '..', '/', '\\', null bytes.
    """
    if not isinstance(run_id, str):
        raise ValueError(f"run_id must be a string, got {type(run_id)}")
    if len(run_id) > 128:
        raise ValueError(f"run_id exceeds 128 characters: {len(run_id)}")
    if ".." in run_id or "/" in run_id or "\\" in run_id or "\x00" in run_id:
        raise ValueError(f"run_id contains illegal path characters: {run_id!r}")
    if not re.match(r"^[a-zA-Z0-9_\-.]+$", run_id):
        raise ValueError(f"run_id contains illegal characters: {run_id!r}")


def _procedural_path(run_id: str) -> str:
    _validate_run_id(run_id)
    return os.path.join(_repo_root(), ".specify", "squad", f"soar-procedural-{run_id}.json")


def _impasse_path(run_id: str) -> str:
    _validate_run_id(run_id)
    return os.path.join(_repo_root(), ".specify", "squad", f"soar-impasse-{run_id}.json")


def _episodic_index_path(run_id: str) -> str:
    _validate_run_id(run_id)
    return os.path.join(_repo_root(), ".specify", "squad", f"episodic-index-{run_id}.json")


def _load_config() -> dict:
    """Read ca_overlays.soar.chunking_enabled from squad-config.yml.

    Returns {"chunking_enabled": False} when key or section absent.
    No YAML library — regex-based parsing.
    """
    config_path = os.path.join(_repo_root(), "squad-config.yml")
    if not os.path.exists(config_path):
        return {"chunking_enabled": False}
    try:
        with open(config_path, encoding="utf-8") as f:
            text = f.read()
        # Find chunking_enabled under ca_overlays > soar section
        m = re.search(r"chunking_enabled\s*:\s*(true|false)", text, re.IGNORECASE)
        if m:
            return {"chunking_enabled": m.group(1).lower() == "true"}
    except Exception:
        pass
    return {"chunking_enabled": False}


def _load_procedural_store(run_id: str) -> dict:
    """Load ProceduralMemoryStore or initialize with SEED_RULES on first call.

    Create-if-absent, do-not-overwrite on subsequent calls.
    Schema: {run_id, last_updated, cycle_count, last_matched_rule_id,
             last_cycle, last_wme_snapshot, rules}
    """
    path = _procedural_path(run_id)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    # First call: initialize with seed rules
    store = {
        "run_id": run_id,
        "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "cycle_count": 0,
        "last_matched_rule_id": None,
        "last_cycle": None,
        "last_wme_snapshot": None,
        "rules": [dict(r) for r in SEED_RULES],
    }
    _save_procedural_store(store, run_id)
    return store


def _save_procedural_store(store: dict, run_id: str) -> None:
    """Atomic write to soar-procedural-{run_id}.json."""
    path = _procedural_path(run_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    store["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)
    os.replace(tmp, path)


def _extract_wmes(context_pack: dict) -> list[dict]:
    """Extract WMEs from context_pack for Tier 1, 2, and present Tier 3 keys.

    Recognized attrs (in order): active_goal, actr_buffers, gwt_workspace,
    episodic_prior_artifact (Tier 1+2), lida_broadcast (Tier 3 — included when present).
    All other context_pack keys are silently ignored.

    active_goal is sourced from context_pack["active_goal"] directly (not from
    inside actr_buffers) — per plan.md Section 5 downstream constraint.
    """
    _WME_ATTRS = [
        "active_goal",              # Tier 1
        "actr_buffers",             # Tier 2
        "gwt_workspace",            # Tier 2
        "episodic_prior_artifact",  # Tier 2
        "lida_broadcast",           # Tier 3
    ]
    wmes = []
    for attr in _WME_ATTRS:
        if attr not in context_pack:
            continue
        raw = context_pack[attr]
        if isinstance(raw, (dict, list)):
            coerced = json.dumps(raw)
        else:
            coerced = str(raw)
        coerced = coerced[:200]
        wmes.append({"id": f"{attr}-wme", "attr": attr, "value": coerced})
    return wmes


def _match_rules(wmes: list[dict], rules: list[dict]) -> dict | None:
    """Linear scan: return highest-confidence fully-matching rule, first-match on ties.

    Condition schema (OQ-001 resolved):
      {"attr": A}          — matches if any WME has attr == A
      {"attr": A, "value": V} — matches if any WME has attr == A and V in wme.value

    Returns None if no rule fully matches (impasse).
    """
    wme_by_attr: dict[str, str] = {w["attr"]: w["value"] for w in wmes}

    best_rule = None
    best_confidence = -1.0

    for rule in rules:
        conditions = rule.get("conditions", [])
        matched = True
        for cond in conditions:
            attr = cond["attr"]
            if attr not in wme_by_attr:
                matched = False
                break
            if "value" in cond and cond["value"] not in wme_by_attr[attr]:
                matched = False
                break
        if not matched:
            continue
        # Rule fully matches — check confidence
        conf = float(rule.get("confidence", 0.0))
        if conf > best_confidence:
            best_confidence = conf
            best_rule = rule

    return best_rule


def _apply_operator(winning_rule: dict, cycle: int, wme_count: int) -> dict:
    """Merge operator payload with mandatory fields; enforce 200-char soar_state cap.

    Mandatory fields: operator_applied, impasse, cycle, wme_count.
    If full soar_state exceeds 200 chars: fall back to mandatory-fields only.
    operator_applied is truncated to 64 chars.
    """
    op_name = str(winning_rule.get("rule_id", "unknown"))[:64]
    soar_state: dict[str, Any] = {
        "operator_applied": op_name,
        "impasse": False,
        "cycle": cycle,
        "wme_count": wme_count,
    }
    # Merge actions payload
    actions = winning_rule.get("actions", {})
    soar_state.update(actions)

    if len(json.dumps(soar_state)) <= 200:
        return soar_state

    # Truncation fallback: mandatory fields only (AC-1.7, FR-SOAR-008)
    return {
        "operator_applied": op_name,
        "impasse": False,
        "cycle": cycle,
        "wme_count": wme_count,
    }


def _log_impasse(run_id: str, wmes: list[dict], cycle: int) -> None:
    """Append ImpasseEvent to soar-impasse-{run_id}.json.

    Creates the file if absent (AC-2.3). Four mandatory fields: type, run_id,
    cycle, wme_snapshot (NFR-SOAR-006).
    """
    path = _impasse_path(run_id)
    event = {
        "type": "no-operator",
        "run_id": run_id,
        "cycle": cycle,
        "wme_snapshot": {w["attr"]: w["value"] for w in wmes},
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            events = json.load(f)
    else:
        events = []
    events.append(event)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2)


def _build_chunk(matched_rule: dict, run_id: str, cycle: int) -> dict:
    """Construct a ChunkRecord from a successful dispatch episode.

    OQ-005 resolved as Option B: conditions copied verbatim from triggering rule.
    confidence always 0.6 (below seed rule range of 0.70-0.90).
    """
    return {
        "rule_id": f"chunk-{run_id}:{cycle}",
        "conditions": list(matched_rule.get("conditions", [])),
        "actions": dict(matched_rule.get("actions", {})),
        "confidence": 0.6,
        "learned": True,
        "episode_id": f"{run_id}:{cycle}",
    }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def enrich_context(context_pack: dict, run_id: str) -> dict:
    """Run a Match-Select-Apply cycle and inject soar_state into context_pack.

    ADR-005 public interface. Position 6 in the COMMANDER pre-dispatch sequence.
    Does NOT modify COMMANDER state. (FR-CAO-006)

    Returns enriched context_pack with soar_state key added.
    On any exception: caller should catch and proceed without soar_state (NFR-SOAR-004).
    """
    _validate_run_id(run_id)
    store = _load_procedural_store(run_id)
    wmes = _extract_wmes(context_pack)

    # Increment cycle counter
    cycle = store.get("cycle_count", 0) + 1

    winning_rule = _match_rules(wmes, store.get("rules", []))

    if winning_rule is not None:
        soar_state = _apply_operator(winning_rule, cycle, len(wmes))
        soar_state["impasse"] = False
        # Update store metadata
        store["last_matched_rule_id"] = winning_rule["rule_id"]
    else:
        # Impasse: no rule matched
        _log_impasse(run_id, wmes, cycle)
        soar_state = {
            "operator_applied": "default-no-match",
            "impasse": True,
            "cycle": cycle,
            "wme_count": len(wmes),
        }
        store["last_matched_rule_id"] = None

    # Save updated metadata
    store["cycle_count"] = cycle
    store["last_cycle"] = cycle
    store["last_wme_snapshot"] = {w["attr"]: w["value"] for w in wmes}
    _save_procedural_store(store, run_id)

    # Return enriched pack (AC-1.5: all prior overlay keys preserved)
    enriched = dict(context_pack)
    enriched["soar_state"] = soar_state
    return enriched


def update_soar_memory(outcome: dict, run_id: str) -> None:
    """Post-dispatch learning hook: create ChunkRecord on successful outcome.

    ADR-005 public interface. Called by COMMANDER after each agent dispatch.
    Does NOT modify COMMANDER state. (FR-CAO-006)

    Success criterion (OQ-004 resolved):
        outcome['status'] not in ['BLOCKED', 'ESCALATED']
    """
    _validate_run_id(run_id)

    # AC-3.2: skip on non-successful outcome
    if outcome.get("status") in ["BLOCKED", "ESCALATED"]:
        return

    # AC-3.4: skip when chunking disabled (default)
    cfg = _load_config()
    if not cfg.get("chunking_enabled", False):
        return

    # AC-3.3: skip silently when episodic index absent
    index_path = _episodic_index_path(run_id)
    if not os.path.exists(index_path):
        return

    # Load store to get last matched rule metadata
    store = _load_procedural_store(run_id)
    last_rule_id = store.get("last_matched_rule_id")
    last_cycle = store.get("last_cycle", 0)

    if last_rule_id is None:
        return  # Last dispatch was an impasse — nothing to chunk

    # Find the matched rule
    matched_rule = None
    for rule in store.get("rules", []):
        if rule.get("rule_id") == last_rule_id:
            matched_rule = rule
            break

    if matched_rule is None:
        return

    # Build and append ChunkRecord
    chunk = _build_chunk(matched_rule, run_id, last_cycle)
    store["rules"].append(chunk)
    _save_procedural_store(store, run_id)
