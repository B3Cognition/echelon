"""
codegen_state_schema.py — codegen-state.json schema definitions and defaults.

Spec 008 base fields + Spec 018 extension fields (T-002).
All new fields are backward-compatible: absent = treat as default value.

Spec 018 new fields:
  tier0_gate              — F1 LSP gate result (null until LSP gate runs)
  tier0_gate_violations   — F1 violation list (null until LSP gate runs)
  anchoring_constraints   — F4 per-run transient style rules ([] by default)
  active_packs            — F2 rule pack paths loaded this run ([] by default)
  run_sequence_number     — monotonically increasing across runs (0 = first run)
  psi_diverging_threshold — F7: retry cycles before marking criterion DIVERGING (default 2)
  smem_accumulation_min_runs — F6: min runs before pattern is distilled (default 3)
"""
from __future__ import annotations

import copy
from typing import Any

# ---------------------------------------------------------------------------
# Default values for all Spec 018 state extension fields
# ---------------------------------------------------------------------------

SPEC018_DEFAULTS: dict[str, Any] = {
    # F1 LSP gate results — null until Phase LSP_GATE completes
    "tier0_gate": None,
    "tier0_gate_violations": None,
    # F4 anchoring — list of AnchoringConstraint dicts, cleared after each run
    "anchoring_constraints": [],
    # F2 rule pack paths — list of str, populated at pipeline init from config
    "active_packs": [],
    # Cross-run tracking — incremented by SmemAccumulator at DELIVER
    "run_sequence_number": 0,
    # F7 Ψ divergence threshold — number of retries without improvement
    "psi_diverging_threshold": 2,
    # F6 SMEM accumulation minimum runs before distillation
    "smem_accumulation_min_runs": 3,
}


# ---------------------------------------------------------------------------
# Field documentation (for tooling and constitution reference)
# ---------------------------------------------------------------------------

SPEC018_FIELD_DOCS: dict[str, str] = {
    "tier0_gate": (
        "F1 LSP Pre-Flight Gate result. "
        "null: gate has not run. "
        "{'status': 'PASS'|'FAIL'|'SKIPPED', 'tool': str, 'violations': list, "
        "'tool_version': str, 'duration_seconds': float}"
    ),
    "tier0_gate_violations": (
        "F1 LSP violation list produced by the pre-flight gate. "
        "null: gate has not run. "
        "List of LspViolation dicts: "
        "{'file': str, 'line': int, 'col': int, 'code': str, 'message': str, "
        "'tool': str, 'severity': 'error'|'warning'|'note'}"
    ),
    "anchoring_constraints": (
        "F4 transient per-run style rules extracted from --anchor target. "
        "Cleared after DELIVER phase. Never persisted to codegen-patterns.yaml. "
        "Each entry: AnchoringConstraint dict with dimension, value, source_file."
    ),
    "active_packs": (
        "F2 rule pack file paths loaded at pipeline initialization. "
        "Each element is an absolute or project-relative path to a CQ-ISC YAML pack file. "
        "Set from pipeline config 'active_packs' key."
    ),
    "run_sequence_number": (
        "Monotonically increasing integer across pipeline runs in this project. "
        "Incremented by SmemAccumulator at DELIVER. "
        "0: first run, no cross-run patterns available."
    ),
    "psi_diverging_threshold": (
        "F7 Ψ granularity: number of IMPLEMENT retry cycles with no improvement "
        "before a per-criterion Ψ score is marked DIVERGING. "
        "Default 2. DIVERGING criteria are surfaced to human instead of consuming retries."
    ),
    "smem_accumulation_min_runs": (
        "F6 Cross-run SMEM: minimum number of pipeline runs in which a pattern "
        "must appear before SmemAccumulator distills it into codegen-patterns.yaml. "
        "Default 3. Prevents single-run noise from polluting the pattern store."
    ),
}


# ---------------------------------------------------------------------------
# Schema validation helpers
# ---------------------------------------------------------------------------

def apply_spec018_defaults(state: dict[str, Any]) -> dict[str, Any]:
    """
    Merge Spec 018 extension fields into an existing state dict.
    Only absent fields are set — existing values are preserved (backward-compat).
    Returns the mutated state dict.
    """
    for field, default in SPEC018_DEFAULTS.items():
        if field not in state:
            state[field] = copy.deepcopy(default)
    return state


def validate_spec018_fields(state: dict[str, Any]) -> list[str]:
    """
    Validate Spec 018 fields in a loaded state dict.
    Returns a list of error strings (empty = valid).
    """
    errors: list[str] = []

    # tier0_gate: null or dict with required keys
    tg = state.get("tier0_gate")
    if tg is not None:
        if not isinstance(tg, dict):
            errors.append("tier0_gate must be null or a dict")
        elif "status" not in tg:
            errors.append("tier0_gate dict must contain 'status' key")
        elif tg["status"] not in ("PASS", "FAIL", "SKIPPED"):
            errors.append(
                f"tier0_gate.status '{tg['status']}' invalid — must be PASS, FAIL, or SKIPPED"
            )

    # tier0_gate_violations: null or list
    tgv = state.get("tier0_gate_violations")
    if tgv is not None and not isinstance(tgv, list):
        errors.append("tier0_gate_violations must be null or a list")

    # anchoring_constraints: list
    ac = state.get("anchoring_constraints", [])
    if not isinstance(ac, list):
        errors.append("anchoring_constraints must be a list")

    # active_packs: list of strings
    ap = state.get("active_packs", [])
    if not isinstance(ap, list):
        errors.append("active_packs must be a list")
    elif any(not isinstance(p, str) for p in ap):
        errors.append("active_packs entries must be strings (file paths)")

    # run_sequence_number: non-negative int
    rsn = state.get("run_sequence_number", 0)
    if not isinstance(rsn, int) or rsn < 0:
        errors.append("run_sequence_number must be a non-negative integer")

    # psi_diverging_threshold: positive int
    pdt = state.get("psi_diverging_threshold", 2)
    if not isinstance(pdt, int) or pdt < 1:
        errors.append("psi_diverging_threshold must be a positive integer >= 1")

    # smem_accumulation_min_runs: positive int
    samr = state.get("smem_accumulation_min_runs", 3)
    if not isinstance(samr, int) or samr < 1:
        errors.append("smem_accumulation_min_runs must be a positive integer >= 1")

    return errors
