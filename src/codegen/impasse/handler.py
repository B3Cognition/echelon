"""
handler.py — Conflict impasse handler and human escalation for /codegen pipeline.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

T-014: Implements FR-DELIVER-005, FR-GATE-003, INV-008, FR-AUDIT-004.

When SOAR fires a conflict impasse (two CQ-ISC rules prohibit all operators
simultaneously), this module:
  1. Detects the impasse type (conflict | no-change | failure).
  2. Extracts the conflicting CQ-ISC IDs and code location.
  3. Writes codegen-impasse.md with the full escalation report (FR-DELIVER-005).
  4. Displays the report in the terminal.
  5. Halts the pipeline and waits for human resolution.

Human resolution paths (FR-GATE-003):
  (a) Amend constitution: update one CQ-ISC rule to allow an exception.
  (b) Add exception WME: provide human sign-off (^source human ^confidence 1.0).
  (c) Narrow scope: restrict one CQ-ISC entry's language/phase scope.

INV-008: Conflict impasse = correct behaviour, NOT a failure.
         Autonomous resolution is FORBIDDEN. Human must decide.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Impasse report data model
# ---------------------------------------------------------------------------

@dataclass
class ConflictingConstraint:
    """A CQ-ISC entry that participated in the impasse."""
    cq_isc_id: str
    rule_text: str
    soar_predicate: str
    phase_scope: str
    language_scope: str


@dataclass
class ImpasseReport:
    """
    Full impasse record produced when SOAR fires a conflict impasse.

    Fields map 1:1 to the sections of codegen-impasse.md.
    """
    impasse_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    impasse_type: str = "conflict"          # conflict | no-change | failure
    pipeline_id: str = ""
    task_id: str = ""
    task_description: str = ""
    conflicting_constraints: list[ConflictingConstraint] = field(default_factory=list)
    code_file: str = ""
    code_line: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    resolution: Optional[str] = None        # None | "exception_wme" | "constitution_amended" | "scope_narrowed"
    resolution_source: str = "pending"      # pending | human | system
    resolution_confidence: float = 0.0


# ---------------------------------------------------------------------------
# ImpasseHandler
# ---------------------------------------------------------------------------

class ImpasseHandler:
    """
    Manages conflict impasse detection, reporting, and human resolution.

    Usage:
        handler = ImpasseHandler(output_dir=Path("."))
        report = ImpasseHandler.build_report(
            pipeline_id="abc",
            task_id="T-003",
            task_description="Implement auth middleware",
            conflicting=[
                ConflictingConstraint("CQ-ISC-SEC-001", "No hardcoded secrets...", ...),
                ConflictingConstraint("CQ-ISC-STRUCT-001", "Function max 30 lines...", ...),
            ],
            code_file="src/auth.py",
            code_line=45,
        )
        handler.write_report(report)   # writes codegen-impasse.md
        handler.display(report)        # prints to terminal
        # Pipeline halts here — awaiting human via resolve()
    """

    IMPASSE_FILE = "codegen-impasse.md"

    def __init__(self, output_dir: Path = Path(".")) -> None:
        self.output_dir = Path(output_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def build_report(
        pipeline_id: str,
        task_id: str,
        task_description: str,
        conflicting: list[ConflictingConstraint],
        code_file: str,
        code_line: int,
        impasse_type: str = "conflict",
    ) -> ImpasseReport:
        """Construct an ImpasseReport from the raw impasse data."""
        return ImpasseReport(
            impasse_type=impasse_type,
            pipeline_id=pipeline_id,
            task_id=task_id,
            task_description=task_description,
            conflicting_constraints=conflicting,
            code_file=code_file,
            code_line=code_line,
        )

    def write_report(self, report: ImpasseReport) -> Path:
        """
        Write codegen-impasse.md (FR-DELIVER-005).
        Returns the path of the written file.
        """
        content = self._render_markdown(report)
        path = self.output_dir / self.IMPASSE_FILE
        path.write_text(content, encoding="utf-8")
        return path

    def display(self, report: ImpasseReport, file=None) -> None:
        """
        Print the escalation report to terminal (FR-DELIVER-005).
        """
        if file is None:
            file = sys.stdout
        lines = [
            "",
            "╔══════════════════════════════════════════════════════════════╗",
            "║       CODEGEN — CONSTRAINT IMPASSE ESCALATION (INV-008)      ║",
            "╠══════════════════════════════════════════════════════════════╣",
            f"║  Pipeline : {report.pipeline_id:<49}║",
            f"║  Task     : {report.task_id:<49}║",
            f"║  Impasse  : {report.impasse_type:<49}║",
            f"║  Location : {report.code_file}:{report.code_line}",
            "╠══════════════════════════════════════════════════════════════╣",
            "║  Conflicting constraints:                                    ║",
        ]
        for c in report.conflicting_constraints:
            lines.append(f"║    [{c.cq_isc_id}] {c.rule_text[:50].strip()}")
        lines += [
            "╠══════════════════════════════════════════════════════════════╣",
            "║  Resolution options:                                         ║",
            "║  (a) Amend constitution — update one CQ-ISC rule             ║",
            "║  (b) Add exception WME — human sign-off (^source human)      ║",
            "║  (c) Narrow scope — restrict CQ-ISC language/phase scope     ║",
            "╠══════════════════════════════════════════════════════════════╣",
            "║  PIPELINE HALTED — awaiting human resolution                 ║",
            f"║  See: {self.IMPASSE_FILE:<55}║",
            "╚══════════════════════════════════════════════════════════════╝",
            "",
        ]
        print("\n".join(lines), file=file)

    def resolve(
        self,
        report: ImpasseReport,
        resolution: str,
        resolution_source: str = "human",
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        """
        Record human resolution and return an exception WME (option b).

        resolution: "exception_wme" | "constitution_amended" | "scope_narrowed"
        Returns a WME dict that can be injected into SOAR Working Memory.

        INV-008: Only humans may resolve impasses (resolution_source must be "human").
        FR-AUDIT-004: Resolution is recorded with ^source human.
        """
        if resolution_source != "human":
            raise ValueError(
                f"Impasse resolution source must be 'human' (INV-008). Got: {resolution_source!r}"
            )
        if confidence <= 0.0 or confidence > 1.0:
            raise ValueError(f"Confidence must be in (0.0, 1.0]. Got: {confidence}")

        report.resolution = resolution
        report.resolution_source = resolution_source
        report.resolution_confidence = confidence

        exception_wme = {
            "wme_type": "exception",
            "impasse_id": report.impasse_id,
            "pipeline_id": report.pipeline_id,
            "task_id": report.task_id,
            "cq_isc_ids_excepted": [c.cq_isc_id for c in report.conflicting_constraints],
            "resolution": resolution,
            "source": resolution_source,           # ^source human (FR-AUDIT-004)
            "confidence": confidence,              # ^confidence 1.0
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return exception_wme

    # ------------------------------------------------------------------
    # T-020: Impasse Memory integration
    # ------------------------------------------------------------------

    def resolve_from_memory(
        self,
        rule_pair_key: frozenset,
        language_context: str,
        current_normalized_hash: str = "",
        memory: "ImpasseMemory | None" = None,
    ) -> "ImpasseResolution | None":
        """
        Before escalating to human, check ImpasseMemory for a prior resolution.

        - If active match found: auto-apply (increment apply_count, log EPMEM),
          do NOT escalate (INV-008 satisfied — human already decided).
        - If no match: return None (caller escalates to human per INV-008).

        Args:
            rule_pair_key:           frozenset of (cq_isc_id, rule_content_hash)
            language_context:        language context tag
            current_normalized_hash: SHA-256 of current rule_text.strip().lower()
            memory:                  ImpasseMemory instance (default: new instance)

        Returns:
            ImpasseResolution if auto-applied, None if human escalation required.
        """
        from src.codegen.impasse.memory import ImpasseMemory  # noqa: PLC0415
        from src.codegen.epmem.recorder import Tier0GateRecorder  # noqa: PLC0415

        mem = memory or ImpasseMemory()
        existing = mem.lookup(rule_pair_key, language_context, current_normalized_hash)
        if existing is None:
            return None

        # Auto-apply: increment apply_count and persist
        existing.apply_count += 1
        mem.store(existing, language_context=language_context)

        # Log EPMEM event
        recorder = Tier0GateRecorder()
        recorder.record_impasse_auto_applied(existing, rule_pair_key, language_context)
        logger.info(
            "ImpasseHandler: auto-applied prior resolution %s (apply_count=%d, run=%s)",
            existing.entry_id,
            existing.apply_count,
            existing.resolved_in_run_id,
        )
        return existing

    def after_human_resolution(
        self,
        rule_pair_key: frozenset,
        language_context: str,
        exception_wme_value: str,
        run_id: str,
        rule_content_hash: str = "",
        rule_text_normalized_hash: str = "",
        memory: "ImpasseMemory | None" = None,
    ) -> "ImpasseResolution":
        """
        Called after a human resolves an impasse. Stores the resolution in memory.

        Args:
            rule_pair_key:             frozenset of (cq_isc_id, rule_content_hash)
            language_context:          language context tag
            exception_wme_value:       WME value to inject on future auto-applies
            run_id:                    pipeline run_id of this resolution
            rule_content_hash:         SHA-256 of rule_text at resolution time
            rule_text_normalized_hash: SHA-256 of rule_text.strip().lower()
            memory:                    ImpasseMemory instance (default: new instance)

        Returns:
            The stored ImpasseResolution.
        """
        from src.codegen.impasse.memory import ImpasseMemory, _serialize_key  # noqa: PLC0415
        from src.codegen.impasse.impasse_types import ImpasseResolution  # noqa: PLC0415

        mem = memory or ImpasseMemory()
        resolution = ImpasseResolution(
            entry_id=str(uuid.uuid4()),
            matching_key=_serialize_key(rule_pair_key),
            resolution_type="exception_wme",
            exception_wme_value=exception_wme_value,
            resolved_in_run_id=run_id,
            resolution_timestamp=datetime.utcnow().isoformat(),
            apply_count=0,
            status="active",
            rule_content_hash=rule_content_hash,
            rule_text_normalized_hash=rule_text_normalized_hash,
        )
        mem.store(resolution, language_context=language_context)
        logger.info(
            "ImpasseHandler: stored human resolution %s for run=%s",
            resolution.entry_id,
            run_id,
        )
        return resolution

    def build_epmem_record(self, report: ImpasseReport, exception_wme: dict) -> dict[str, Any]:
        """
        Build an EPMEM entry for the impasse resolution (FR-AUDIT-004).
        Must be recorded with ^source human (not soar).
        """
        return {
            "record_id": str(uuid.uuid4()),
            "record_type": "impasse-resolution",
            "task_id": report.task_id,
            "impasse_id": report.impasse_id,
            "impasse_type": report.impasse_type,
            "conflicting_cq_isc_ids": [c.cq_isc_id for c in report.conflicting_constraints],
            "code_file": report.code_file,
            "code_line": report.code_line,
            "resolution": report.resolution,
            "source": "human",                    # INV-008: human resolution only
            "confidence": report.resolution_confidence,
            "operator_outcome": "ESCALATE",
            "timestamp_ms": int(time.time() * 1000),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _render_markdown(self, report: ImpasseReport) -> str:
        """Render the full codegen-impasse.md content (FR-DELIVER-005)."""
        constraint_table_rows = "\n".join(
            f"| {c.cq_isc_id} | {c.rule_text[:60].strip()} | `{c.soar_predicate[:50]}` |"
            for c in report.conflicting_constraints
        )

        return f"""# CODEGEN — Constraint Impasse Escalation

**Impasse ID:** {report.impasse_id}
**Pipeline ID:** {report.pipeline_id}
**Task:** {report.task_id}: {report.task_description}
**Impasse type:** {report.impasse_type}
**Timestamp:** {report.timestamp}

---

## Conflicting Constraints

| CQ-ISC ID | Rule Text | Predicate |
|-----------|-----------|-----------|
{constraint_table_rows}

---

## Code Location

**File:** `{report.code_file}`
**Line:** {report.code_line}

---

## Why This Cannot Be Resolved Automatically

Both constraints prohibit all available operators simultaneously.
Autonomous resolution would violate **INV-008**: conflict impasse = correct behaviour, NOT a failure.
Impasse triggers human escalation, not autonomous resolution.

---

## Resolution Options

1. **Amend constitution (`constitution_amended`):**
   Update one CQ-ISC rule to allow an exception for this specific case.
   Edit the CQ-ISC library YAML and re-run the pipeline.

2. **Add exception WME (`exception_wme`):**
   Provide a human sign-off WME `(^source human ^confidence 1.0)` for this task.
   This allows the pipeline to resume for this task only (FR-GATE-003).
   Call `ImpasseHandler.resolve(report, resolution="exception_wme", resolution_source="human")`.

3. **Narrow scope (`scope_narrowed`):**
   Restrict one CQ-ISC entry's `language_scope` or `phase_scope` to exclude this task.
   Edit the CQ-ISC library YAML and re-run the pipeline.

---

**Pipeline is HALTED. Awaiting human resolution.**

*SOAR invariant INV-008 enforced. Do not modify this file to bypass the gate.*
"""


# ---------------------------------------------------------------------------
# T-020: Phase 0 staleness check (module-level function)
# ---------------------------------------------------------------------------

def check_impasse_log_staleness(
    memory: "ImpasseMemory",
    current_rule_hashes: dict[str, str],
) -> list[str]:
    """
    Check all active entries in the impasse log against current rule hashes.

    For each active entry whose stored rule_content_hash no longer matches
    the current hash for any of its cq_isc_ids:
      - Mark the entry stale via memory.mark_stale()
      - Write an IMPASSE_STALE_HASH EPMEM record

    Runs at Phase 0 (before any build work) to pre-emptively invalidate
    resolutions that may no longer apply after rule edits.

    Args:
        memory:               ImpasseMemory instance.
        current_rule_hashes:  Mapping of {cq_isc_id: current_rule_content_hash}
                              reflecting the current constitution state.

    Returns:
        List of entry_ids that were marked stale.
    """
    from src.codegen.epmem.recorder import Tier0GateRecorder  # noqa: PLC0415
    import ast  # noqa: PLC0415

    recorder = Tier0GateRecorder()
    stale_ids: list[str] = []

    entries = memory._load_entries()
    for raw in entries:
        if raw.get("status") != "active":
            continue

        entry_id = raw.get("entry_id", "")
        stored_content_hash = raw.get("rule_content_hash", "")
        stored_key = raw.get("matching_key", "")

        # Parse cq_isc_ids from matching_key
        try:
            parsed = ast.literal_eval(stored_key)
            stored_id_pairs = [(item[0], item[1]) for item in parsed if len(item) >= 2]
        except (ValueError, SyntaxError, TypeError):
            continue

        # Check each cq_isc_id in this entry against current hashes
        for cq_isc_id, _stored_pair_hash in stored_id_pairs:
            current_hash = current_rule_hashes.get(cq_isc_id)
            if current_hash is None:
                continue  # not tracking this rule
            if current_hash != stored_content_hash:
                # Hash mismatch — mark stale
                memory.mark_stale(entry_id)
                recorder.record_impasse_stale_hash(
                    entry_id=entry_id,
                    cq_isc_id=cq_isc_id,
                    stored_hash=stored_content_hash,
                    current_hash=current_hash,
                )
                logger.info(
                    "check_impasse_log_staleness: entry %s marked stale "
                    "(cq_isc_id=%s, stored=%s, current=%s)",
                    entry_id,
                    cq_isc_id,
                    stored_content_hash,
                    current_hash,
                )
                stale_ids.append(entry_id)
                break  # one stale rule in the pair is enough

    return stale_ids
