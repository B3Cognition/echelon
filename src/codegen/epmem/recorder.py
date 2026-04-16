"""
recorder.py — EPMEM event recorder for Spec 018 F1 LSP Gate events.
Spec 018 T-006.

INV-004: Every SOAR phase transition MUST produce an EPMEM entry.
New event types introduced by F1:
  - lsp_gate_invoked   (always, after gate runs)
  - TIER0_GATE_PASS    (when status="passed")
  - TIER0_GATE_FAIL    (when status="failed")
  - TIER0_GATE_UNAVAILABLE (when status="unavailable")
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# F1 EPMEM event type constants
# ---------------------------------------------------------------------------

EPMEM_TIER0_GATE_PASS = "TIER0_GATE_PASS"
EPMEM_TIER0_GATE_FAIL = "TIER0_GATE_FAIL"
EPMEM_TIER0_GATE_UNAVAILABLE = "TIER0_GATE_UNAVAILABLE"
EPMEM_LSP_GATE_INVOKED = "lsp_gate_invoked"

# F3 EPMEM event type constant (T-014)
EPMEM_CONSTITUTION_EXTRACTED = "constitution_extracted"

# F4 EPMEM event type constant (T-017)
EPMEM_ANCHORING_CONSTRAINTS_INJECTED = "anchoring_constraints_injected"

# F5 EPMEM event type constants (T-020) — Impasse Memory
EPMEM_IMPASSE_AUTO_APPLIED = "IMPASSE_AUTO_APPLIED"
EPMEM_IMPASSE_STALE_HASH = "IMPASSE_STALE_HASH"

# F6 EPMEM event type constants (T-023) — Cross-Run SMEM Accumulation
EPMEM_SMEM_ACCUMULATION_COMPLETE = "SMEM_ACCUMULATION_COMPLETE"
EPMEM_SMEM_PATTERN_DISTILLED = "smem_pattern_distilled"

# F7 EPMEM event type constants (T-026) — Ψ Score Granularity + Convergence Tracking
EPMEM_PSI_CRITERION_DIVERGING = "PSI_CRITERION_DIVERGING"
EPMEM_PSI_DIVERGING_DETECTED = "psi_diverging_detected"

#: All F1 EPMEM event types
TIER0_EVENT_TYPES: frozenset[str] = frozenset({
    EPMEM_TIER0_GATE_PASS,
    EPMEM_TIER0_GATE_FAIL,
    EPMEM_TIER0_GATE_UNAVAILABLE,
    EPMEM_LSP_GATE_INVOKED,
    EPMEM_CONSTITUTION_EXTRACTED,
})

#: F5 Impasse Memory EPMEM event types
IMPASSE_EVENT_TYPES: frozenset[str] = frozenset({
    EPMEM_IMPASSE_AUTO_APPLIED,
    EPMEM_IMPASSE_STALE_HASH,
})


# ---------------------------------------------------------------------------
# EpmemEvent dataclass
# ---------------------------------------------------------------------------

@dataclass
class EpmemEvent:
    """
    A single EPMEM event record.
    INV-004: produced for every gate invocation.
    """
    event_id: str
    event_type: str
    timestamp_ms: int
    language: str
    tool_name: str
    tool_version: str
    gate_result: str              # "passed" | "failed" | "unavailable"
    violations_count: int
    duration_seconds: float
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp_ms": self.timestamp_ms,
            "language": self.language,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "gate_result": self.gate_result,
            "violations_count": self.violations_count,
            "duration_seconds": self.duration_seconds,
            **self.extra,
        }


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------

class Tier0GateRecorder:
    """
    Records EPMEM events for F1 LSP Pre-Flight Gate invocations.
    Maintains an in-memory log; caller is responsible for persisting.
    """

    def __init__(self) -> None:
        self._events: list[EpmemEvent] = []

    def record(self, lsp_result: "LspResult") -> EpmemEvent:
        """
        Create and store an EPMEM event from an LspResult.
        Always emits `lsp_gate_invoked`; also emits the specific typed event.

        Args:
            lsp_result: The result from LspGate.run().

        Returns:
            The primary typed EpmemEvent (PASS/FAIL/UNAVAILABLE).
        """
        ts = int(time.time() * 1000)
        violations_count = len(lsp_result.violations)

        # Always emit lsp_gate_invoked (per contract table)
        invoked_event = EpmemEvent(
            event_id=str(uuid.uuid4()),
            event_type=EPMEM_LSP_GATE_INVOKED,
            timestamp_ms=ts,
            language=lsp_result.language,
            tool_name=lsp_result.tool_name,
            tool_version=lsp_result.tool_version,
            gate_result=lsp_result.status,
            violations_count=violations_count,
            duration_seconds=lsp_result.duration_seconds,
            extra={"tool_used": lsp_result.tool_name},
        )
        self._events.append(invoked_event)

        # Emit typed event based on status
        if lsp_result.status == "passed":
            typed_type = EPMEM_TIER0_GATE_PASS
            extra = {
                "tool_name": lsp_result.tool_name,
                "tool_version": lsp_result.tool_version,
            }
        elif lsp_result.status == "failed":
            typed_type = EPMEM_TIER0_GATE_FAIL
            extra = {
                "tool_name": lsp_result.tool_name,
                "violation_count": violations_count,
                "timeout_hit": lsp_result.timeout_hit,
                "tier0_gate_violations": [
                    {
                        "file": v.file,
                        "line": v.line,
                        "error_code": v.error_code,
                        "message": v.message,
                        "severity": v.severity,
                    }
                    for v in lsp_result.violations[:50]  # cap at 50 for EPMEM size
                ],
            }
        else:  # unavailable
            typed_type = EPMEM_TIER0_GATE_UNAVAILABLE
            extra = {"tool_name": lsp_result.tool_name}

        typed_event = EpmemEvent(
            event_id=str(uuid.uuid4()),
            event_type=typed_type,
            timestamp_ms=ts,
            language=lsp_result.language,
            tool_name=lsp_result.tool_name,
            tool_version=lsp_result.tool_version,
            gate_result=lsp_result.status,
            violations_count=violations_count,
            duration_seconds=lsp_result.duration_seconds,
            extra=extra,
        )
        self._events.append(typed_event)
        return typed_event

    def record_constitution_extracted(
        self,
        draft: "ConstitutionDraft",
    ) -> EpmemEvent:
        """
        Create and store an EPMEM event for a completed constitution extraction.
        INV-004: every SOAR phase transition must produce an EPMEM entry.

        Args:
            draft: The ConstitutionDraft returned by ConstitutionExtractor.run().

        Returns:
            The EpmemEvent recorded.
        """
        from src.codegen.extract.constitution_extractor import ExtractedRule  # noqa: PLC0415

        ts = int(time.time() * 1000)
        category_s_count = sum(
            1 for r in draft.rules if r.category in ("S", "S_HUMAN")
        )
        category_b_count = sum(1 for r in draft.rules if r.category == "B")

        event = EpmemEvent(
            event_id=str(uuid.uuid4()),
            event_type=EPMEM_CONSTITUTION_EXTRACTED,
            timestamp_ms=ts,
            language="*",
            tool_name="constitution_extractor",
            tool_version="1.0.0",
            gate_result="extracted",
            violations_count=0,
            duration_seconds=0.0,
            extra={
                "source_types_found": list(draft.sources_found),
                "rules_generated": len(draft.rules),
                "confidence_score": draft.overall_confidence,
                "category_s_count": category_s_count,
                "category_b_count": category_b_count,
            },
        )
        self._events.append(event)
        return event

    def record_anchoring_constraints_injected(
        self,
        constraints: "list",
        anchor_path: str,
    ) -> EpmemEvent:
        """
        Create and store an EPMEM event for anchoring constraints injection.
        Spec 018 T-017: F4 Anchoring Mode — EPMEM recording.
        INV-004: every SOAR phase transition must produce an EPMEM entry.

        Args:
            constraints: List of AnchoringConstraint objects injected as WMEs.
            anchor_path: The anchor codebase path that was analyzed.

        Returns:
            The EpmemEvent recorded.
        """
        ts = int(time.time() * 1000)
        constraint_count = len(constraints)

        event = EpmemEvent(
            event_id=str(uuid.uuid4()),
            event_type=EPMEM_ANCHORING_CONSTRAINTS_INJECTED,
            timestamp_ms=ts,
            language="*",
            tool_name="anchor_extractor",
            tool_version="1.0.0",
            gate_result="injected",
            violations_count=0,
            duration_seconds=0.0,
            extra={
                "constraint_count": constraint_count,
                "anchor_path": anchor_path,
                "dimensions": list({c.dimension for c in constraints}) if constraints else [],
            },
        )
        self._events.append(event)
        return event

    def record_impasse_auto_applied(
        self,
        resolution: "ImpasseResolution",
        rule_pair_key: frozenset,
        language_context: str,
    ) -> EpmemEvent:
        """
        Record an IMPASSE_AUTO_APPLIED event (F5 T-020).

        Called when ImpasseMemory finds a prior human resolution that can be
        auto-applied without re-escalating to human (INV-008: human already
        made the decision; this merely re-applies it).

        Args:
            resolution:       The ImpasseResolution being auto-applied.
            rule_pair_key:    The frozenset rule-pair key for this impasse.
            language_context: The language context tag.

        Returns:
            The EpmemEvent recorded.
        """
        ts = int(time.time() * 1000)
        event = EpmemEvent(
            event_id=str(uuid.uuid4()),
            event_type=EPMEM_IMPASSE_AUTO_APPLIED,
            timestamp_ms=ts,
            language=language_context,
            tool_name="impasse_memory",
            tool_version="1.0.0",
            gate_result="auto_applied",
            violations_count=0,
            duration_seconds=0.0,
            extra={
                "entry_id": resolution.entry_id,
                "resolved_in_run_id": resolution.resolved_in_run_id,
                "apply_count": resolution.apply_count,
                "resolution_type": resolution.resolution_type,
                "exception_wme_value": resolution.exception_wme_value,
                "rule_pair_key": str(sorted(rule_pair_key)),
                "language_context": language_context,
            },
        )
        self._events.append(event)
        return event

    def record_impasse_stale_hash(
        self,
        entry_id: str,
        cq_isc_id: str,
        stored_hash: str,
        current_hash: str,
    ) -> EpmemEvent:
        """
        Record an IMPASSE_STALE_HASH event (F5 T-020).

        Called when Phase 0 staleness check detects that a rule's content
        hash has changed, rendering the stored resolution potentially stale.

        Args:
            entry_id:     The ImpasseResolution entry_id being marked stale.
            cq_isc_id:    The CQ-ISC rule ID whose hash changed.
            stored_hash:  The rule_content_hash stored in the resolution.
            current_hash: The current rule_content_hash from the codebase.

        Returns:
            The EpmemEvent recorded.
        """
        ts = int(time.time() * 1000)
        event = EpmemEvent(
            event_id=str(uuid.uuid4()),
            event_type=EPMEM_IMPASSE_STALE_HASH,
            timestamp_ms=ts,
            language="*",
            tool_name="impasse_memory",
            tool_version="1.0.0",
            gate_result="stale",
            violations_count=0,
            duration_seconds=0.0,
            extra={
                "entry_id": entry_id,
                "cq_isc_id": cq_isc_id,
                "stored_rule_content_hash": stored_hash,
                "current_rule_content_hash": current_hash,
            },
        )
        self._events.append(event)
        return event

    def record_smem_accumulation_complete(
        self,
        patterns_new: int,
        patterns_updated: int,
        patterns_total: int,
    ) -> EpmemEvent:
        """
        Record an SMEM_ACCUMULATION_COMPLETE event (F6 T-023).
        INV-004: every SOAR phase transition must produce an EPMEM entry.

        Args:
            patterns_new:     Number of newly created patterns in this distill cycle.
            patterns_updated: Number of existing patterns updated in this cycle.
            patterns_total:   Total active pattern count after distillation.

        Returns:
            The EpmemEvent recorded.
        """
        ts = int(time.time() * 1000)
        event = EpmemEvent(
            event_id=str(uuid.uuid4()),
            event_type=EPMEM_SMEM_ACCUMULATION_COMPLETE,
            timestamp_ms=ts,
            language="*",
            tool_name="smem_accumulator",
            tool_version="1.0.0",
            gate_result="complete",
            violations_count=0,
            duration_seconds=0.0,
            extra={
                "patterns_new": patterns_new,
                "patterns_updated": patterns_updated,
                "patterns_total": patterns_total,
            },
        )
        self._events.append(event)
        return event

    def record_psi_criterion_diverging(
        self,
        criterion_id: str,
        retry_count: int,
        last_delta: float,
    ) -> EpmemEvent:
        """
        Record a PSI_CRITERION_DIVERGING event (F7 T-026).
        INV-004: every SOAR phase transition must produce an EPMEM entry.

        Called when PsiTracker.check_divergence() returns True for a criterion,
        AFTER inject_psi_diverging_wme() is called (INV-006 compliance).

        Args:
            criterion_id: The CQ-ISC criterion ID that is DIVERGING.
            retry_count:  Number of retry cycles the criterion has been uncovered.
            last_delta:   Coverage delta from last cycle (typically 0.0 when diverging).

        Returns:
            The EpmemEvent recorded.
        """
        ts = int(time.time() * 1000)
        event = EpmemEvent(
            event_id=str(uuid.uuid4()),
            event_type=EPMEM_PSI_CRITERION_DIVERGING,
            timestamp_ms=ts,
            language="*",
            tool_name="psi_tracker",
            tool_version="1.0.0",
            gate_result=EPMEM_PSI_DIVERGING_DETECTED,
            violations_count=0,
            duration_seconds=0.0,
            extra={
                "criterion_id": criterion_id,
                "retry_count": retry_count,
                "last_delta": last_delta,
            },
        )
        self._events.append(event)
        return event

    @property
    def events(self) -> list[EpmemEvent]:
        """All recorded events (immutable view)."""
        return list(self._events)

    def export(self) -> list[dict[str, Any]]:
        """Export all events as a list of dicts for EPMEM serialization."""
        return [e.to_dict() for e in self._events]
