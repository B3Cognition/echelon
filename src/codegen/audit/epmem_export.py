"""
epmem_export.py — EPMEM export and codegen-report.md generation.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

T-015: Implements FR-AUDIT-001..005, INV-004, FR-DELIVER-004.

Functions:
  - export_to_file(audit_dict, output_path): write codegen-epmem.json
  - validate_audit_dict(audit_dict): verify all mandatory fields are present
  - generate_report(audit_dict, pipeline_summary, output_path): write codegen-report.md
  - count_phase_transitions(audit_dict): count phase-transition records (AC-BENCH-005)

AC-BENCH-005 (EPMEM audit completeness):
  Run a complete pipeline on a 2-task greenfield scenario.
  Count phase transitions in execution log == AuditRecord count.
  Verified by: count_phase_transitions(audit_dict) == actual_transitions.

INV-004: Every SOAR phase transition MUST produce an EPMEM entry.
FR-DELIVER-004: codegen-report.md is human-readable without SOAR knowledge.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Mandatory fields per AuditRecord (INV-004, FR-AUDIT-001..005)
# ---------------------------------------------------------------------------

MANDATORY_AUDIT_RECORD_FIELDS = {
    "record_id",
    "record_type",
    "selected_operator",
    "cq_isc_ids_evaluated",
    "cq_isc_prohibit_fired",
    "operator_outcome",
    "psi_at_decision",
    "violations_blocked",
    "timestamp_ms",
}

MANDATORY_EXPORT_FIELDS = {
    "schema_version",
    "pipeline_id",
    "export_ts",
    "soar_model",
    "total_records",
    "records",
}

VALID_OPERATOR_OUTCOMES = {"ADVANCE", "RETRY", "ESCALATE", "DELIVER"}
VALID_RECORD_TYPES = {
    "phase-transition",
    "retry-task",
    "escalation",
    "delivery",
    "smem-load",
    "impasse-resolution",
}


# ---------------------------------------------------------------------------
# Pipeline summary (passed in from the codegen skill / state.json)
# ---------------------------------------------------------------------------

@dataclass
class PipelineSummary:
    """Human-readable pipeline summary for codegen-report.md."""
    pipeline_id: str
    mode: str                          # brownfield | greenfield
    intent: str
    psi_score: float
    psi_threshold: float
    tier1_gate: str                    # pass | fail | unavailable
    cq_isc_violation_count: int
    impasse_count: int
    tasks_done: int
    tasks_total: int
    tasks_blocked: int
    wall_clock_seconds: float
    soar_model: str                    # A | B
    phases_completed: list[str] = field(default_factory=list)
    final_phase: str = "DELIVER"


# ---------------------------------------------------------------------------
# Export functions
# ---------------------------------------------------------------------------

def export_to_file(audit_dict: dict[str, Any], output_path: Path) -> Path:
    """
    Write the EPMEM audit export to codegen-epmem.json.

    The file must be valid JSON (parseable by jq).
    Raises ValueError if mandatory export-level fields are missing.

    Returns the output path.
    """
    _validate_export_top_level(audit_dict)

    # Ensure pipeline-summary section exists
    if "pipeline_summary" not in audit_dict:
        audit_dict = dict(audit_dict)
        audit_dict["pipeline_summary"] = {
            "note": "pipeline_summary was not provided at export time"
        }

    output_path = Path(output_path)
    output_path.write_text(json.dumps(audit_dict, indent=2), encoding="utf-8")
    return output_path


def validate_audit_dict(audit_dict: dict[str, Any]) -> list[str]:
    """
    Validate the audit export dict for mandatory fields.

    Returns a list of error strings (empty = valid).
    Checks:
      1. Top-level mandatory export fields present.
      2. Every AuditRecord has all mandatory fields.
      3. operator_outcome is in VALID_OPERATOR_OUTCOMES.
      4. record_type is in VALID_RECORD_TYPES.
    """
    errors: list[str] = []

    # Top-level fields
    missing_top = MANDATORY_EXPORT_FIELDS - set(audit_dict.keys())
    for f in sorted(missing_top):
        errors.append(f"Export-level field missing: {f!r}")

    # Per-record validation
    records = audit_dict.get("records", [])
    for i, record in enumerate(records):
        missing = MANDATORY_AUDIT_RECORD_FIELDS - set(record.keys())
        for f in sorted(missing):
            errors.append(f"Record [{i}] missing mandatory field: {f!r}")

        outcome = record.get("operator_outcome", "")
        if outcome not in VALID_OPERATOR_OUTCOMES:
            errors.append(
                f"Record [{i}] invalid operator_outcome: {outcome!r}. "
                f"Must be one of {VALID_OPERATOR_OUTCOMES}"
            )

        rtype = record.get("record_type", "")
        if rtype not in VALID_RECORD_TYPES:
            errors.append(
                f"Record [{i}] invalid record_type: {rtype!r}. "
                f"Must be one of {VALID_RECORD_TYPES}"
            )

    return errors


def count_phase_transitions(audit_dict: dict[str, Any]) -> int:
    """
    Count AuditRecord entries with record_type == 'phase-transition'.

    AC-BENCH-005: This count must equal the number of actual phase transitions
    in the execution log (1:1 correspondence enforced by INV-004).
    """
    return sum(
        1 for r in audit_dict.get("records", [])
        if r.get("record_type") == "phase-transition"
    )


def generate_report(
    audit_dict: dict[str, Any],
    summary: PipelineSummary,
    output_path: Path,
) -> Path:
    """
    Write codegen-report.md — human-readable pipeline summary (FR-DELIVER-004).

    The report must be readable without SOAR knowledge. Covers:
      - Ψ score and threshold
      - CQ-ISC violation count
      - Tier 1 result
      - Wall-clock time
      - Task summary (done / blocked / total)
      - Phase completion list
      - SOAR model used

    Returns the output path.
    """
    output_path = Path(output_path)
    content = _render_report(audit_dict, summary)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def add_pipeline_summary_to_export(
    audit_dict: dict[str, Any],
    summary: PipelineSummary,
) -> dict[str, Any]:
    """
    Inject a pipeline_summary section into the audit export dict.

    This satisfies the AC-BENCH-005 requirement that codegen-epmem.json
    contains a pipeline-summary section.
    """
    summary_dict = {
        "pipeline_id": summary.pipeline_id,
        "mode": summary.mode,
        "intent": summary.intent,
        "psi_score": summary.psi_score,
        "psi_threshold": summary.psi_threshold,
        "tier1_gate": summary.tier1_gate,
        "cq_isc_violation_count": summary.cq_isc_violation_count,
        "impasse_count": summary.impasse_count,
        "tasks_done": summary.tasks_done,
        "tasks_total": summary.tasks_total,
        "tasks_blocked": summary.tasks_blocked,
        "wall_clock_seconds": summary.wall_clock_seconds,
        "soar_model": summary.soar_model,
        "phases_completed": summary.phases_completed,
        "final_phase": summary.final_phase,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    result = dict(audit_dict)
    result["pipeline_summary"] = summary_dict
    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _validate_export_top_level(audit_dict: dict[str, Any]) -> None:
    missing = MANDATORY_EXPORT_FIELDS - set(audit_dict.keys())
    if missing:
        raise ValueError(
            f"Missing mandatory export fields: {sorted(missing)}. "
            f"Ensure bridge.export_audit_record() was called before export."
        )


def _render_report(audit_dict: dict[str, Any], summary: PipelineSummary) -> str:
    """Render codegen-report.md content."""
    psi_bar = _psi_bar(summary.psi_score, summary.psi_threshold)
    tier1_icon = "PASS" if summary.tier1_gate == "pass" else (
        "UNAVAILABLE" if summary.tier1_gate == "unavailable" else "FAIL"
    )
    wall_clock = _format_wall_clock(summary.wall_clock_seconds)
    phases_str = " → ".join(summary.phases_completed) if summary.phases_completed else "(none)"
    phase_transition_count = count_phase_transitions(audit_dict)

    violations = summary.cq_isc_violation_count
    violation_str = f"{violations} violation(s) blocked" if violations else "0 violations (clean)"

    return f"""# CODEGEN Pipeline Report

**Pipeline ID:** `{summary.pipeline_id}`
**Mode:** {summary.mode}
**Intent:** {summary.intent}
**Final phase:** {summary.final_phase}
**SOAR model:** Model {summary.soar_model}

---

## Quality Gate Summary

| Metric | Value |
|--------|-------|
| **Ψ score** | {summary.psi_score:.3f} (threshold {summary.psi_threshold:.2f}) |
| **Ψ status** | {psi_bar} |
| **Tier 1 gate** | {tier1_icon} |
| **CQ-ISC violations blocked** | {violation_str} |
| **Impasse escalations** | {summary.impasse_count} |
| **Phase transitions (EPMEM)** | {phase_transition_count} |

---

## Task Summary

| Status | Count |
|--------|-------|
| Done | {summary.tasks_done} |
| Blocked | {summary.tasks_blocked} |
| Total | {summary.tasks_total} |

---

## Phases Completed

{phases_str}

---

## Timing

**Wall-clock time:** {wall_clock}

---

## EPMEM Audit

**Total records:** {audit_dict.get('total_records', 0)}
**Export file:** `codegen-epmem.json`

*Full EPMEM audit available in `codegen-epmem.json`. Each record maps to one
SOAR decision cycle (INV-004). Records include: operator selected, CQ-ISC rules
evaluated, prohibits fired, Ψ at decision time.*

---

*Generated by /codegen — SOAR-Powered Software Development Agent (Spec 008)*
"""


def _psi_bar(score: float, threshold: float) -> str:
    if score >= threshold:
        return f"PASS ({score:.3f} >= {threshold:.2f})"
    return f"BELOW THRESHOLD ({score:.3f} < {threshold:.2f})"


def _format_wall_clock(seconds: float) -> str:
    if seconds < 0:
        return "N/A"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
