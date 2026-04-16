"""
interface.py — IMPLEMENTER LLM interface and context pack assembly.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

T-021: SOAR dispatches the Echelon IMPLEMENTER per task.

This module handles:
  1. Context pack assembly (FR-IMPL-002):
     - Task description + scope
     - Scoped staging artifacts
     - CQ-ISC advisory rules (informational — NOT enforcement)
     - Constitution sections
     - Current Ψ score
     - |I_D| estimate
  2. IMPLEMENTER task result parsing (FR-IMPL-004):
     - Parse status (DONE | BLOCKED | NEEDS_CONTEXT)
     - Extract files modified, test pass rate
     - Inject result WMEs into SOAR Working Memory
  3. BLOCKED/NEEDS_CONTEXT handling (FR-IMPL-008):
     - SOAR does NOT re-dispatch without updated context
     - Context update required before re-dispatch

INV-003: IMPLEMENTER outputs 'best' preferences ONLY.
         IMPLEMENTER does NOT inject prohibit, require, or worst preferences.
INV-006: SOAR owns phase transition decision. IMPLEMENTER advises only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ImplementerStatus(str, Enum):
    DONE = "DONE"
    BLOCKED = "BLOCKED"
    NEEDS_CONTEXT = "NEEDS_CONTEXT"


# ---------------------------------------------------------------------------
# Context pack (FR-IMPL-002)
# ---------------------------------------------------------------------------

@dataclass
class ContextPack:
    """
    Context pack assembled by SOAR for IMPLEMENTER dispatch.

    INV-003: CQ-ISC advisory rules are INFORMATIONAL. IMPLEMENTER does not
    enforce them — SOAR evaluates them post-hoc via prohibit preferences.
    INV-006: IMPLEMENTER advises SOAR; SOAR makes all operator decisions.
    """
    task_id: str
    description: str
    scope: str
    language: str
    module_boundary: str
    cq_isc_advisory: list[dict[str, str]] = field(default_factory=list)
    staging_artifacts: list[str] = field(default_factory=list)
    constitution_sections: list[str] = field(default_factory=list)
    psi_score: float = 0.0
    psi_threshold: float = 0.70
    id_estimate: int = 0
    id_confidence: str = "LOW"              # HIGH | MEDIUM | LOW
    retry_count: int = 0
    max_retries: int = 3
    context_updates: list[str] = field(default_factory=list)   # for re-dispatch

    def to_prompt_block(self) -> str:
        """
        Render the context pack as a markdown block for IMPLEMENTER dispatch.
        INV-003: advisory rules are presented as informational guidance only.
        """
        advisory_lines = "\n".join(
            f"  - [{r.get('cq_isc_id', '?')}] {r.get('rule_text', '')[:80]}"
            for r in self.cq_isc_advisory
        ) or "  (no advisory rules — default CQ-ISC library applies)"

        artifact_lines = "\n".join(f"  - {a}" for a in self.staging_artifacts) or "  (none)"
        constitution_lines = "\n".join(f"  - {s}" for s in self.constitution_sections) or "  (none)"

        retry_note = ""
        if self.retry_count > 0:
            retry_note = f"\n**Retry:** This is attempt {self.retry_count + 1} of {self.max_retries + 1}."

        context_update_block = ""
        if self.context_updates:
            updates = "\n".join(f"  - {u}" for u in self.context_updates)
            context_update_block = f"\n**Context updates for this retry:**\n{updates}"

        return f"""## IMPLEMENTER Context Pack

**Task ID:** {self.task_id}
**Description:** {self.description}
**Scope:** {self.scope} (module: {self.module_boundary})
**Language:** {self.language}
**Ψ score:** {self.psi_score:.3f} (threshold {self.psi_threshold:.2f})
**|I_D| estimate:** {self.id_estimate} ({self.id_confidence} confidence){retry_note}

### CQ-ISC Advisory Rules (INFORMATIONAL — SOAR enforces, not IMPLEMENTER)
{advisory_lines}

### Staging Artifacts Available
{artifact_lines}

### Constitution Sections
{constitution_lines}{context_update_block}

---

**IMPORTANT: You are ADVISING SOAR. Output best-preference recommendations only.**
**Do NOT make final quality gate decisions — SOAR evaluates all gates post-hoc.**
**INV-003: Do not inject prohibit, require, or worst preferences.**
**INV-006: SOAR owns the phase transition decision.**
"""


# ---------------------------------------------------------------------------
# IMPLEMENTER task result (FR-IMPL-004)
# ---------------------------------------------------------------------------

@dataclass
class ImplementerResult:
    """
    Result WMEs injected into SOAR Working Memory after IMPLEMENTER completes.

    FR-IMPL-004: Result must include status, files_modified, test_pass_rate.
    """
    task_id: str
    status: ImplementerStatus
    files_modified: list[str] = field(default_factory=list)
    test_pass_rate: float = 0.0         # 0.0 - 1.0; 1.0 = all tests pass
    test_files_created: list[str] = field(default_factory=list)
    blocker_reason: Optional[str] = None   # set when status == BLOCKED
    context_question: Optional[str] = None  # set when status == NEEDS_CONTEXT
    confidence_envelope: dict[str, Any] = field(default_factory=dict)

    def to_wme_dict(self) -> dict[str, Any]:
        """Serialize as a SOAR result WME dict (best preference only, INV-003)."""
        return {
            "wme_type": "implementer-result",
            "task-id": self.task_id,
            "status": self.status.value,
            "files-modified": self.files_modified,
            "test-pass-rate": self.test_pass_rate,
            "test-files-created": self.test_files_created,
            "blocker-reason": self.blocker_reason,
            "context-question": self.context_question,
            "preference": "best",        # INV-003: best preference ONLY
        }

    @property
    def is_done(self) -> bool:
        return self.status == ImplementerStatus.DONE

    @property
    def is_blocked(self) -> bool:
        return self.status == ImplementerStatus.BLOCKED

    @property
    def is_needs_context(self) -> bool:
        return self.status == ImplementerStatus.NEEDS_CONTEXT


# ---------------------------------------------------------------------------
# DispatchRecord — tracks dispatch history per task (FR-IMPL-008)
# ---------------------------------------------------------------------------

@dataclass
class DispatchRecord:
    """
    Tracks IMPLEMENTER dispatch history for a task.

    FR-IMPL-008: SOAR does NOT re-dispatch to the same task without updated
    context. Each blocked dispatch must be accompanied by a context update
    before the next dispatch is allowed.
    """
    task_id: str
    dispatch_count: int = 0
    context_updates_applied: int = 0
    last_status: Optional[ImplementerStatus] = None
    dispatch_history: list[dict[str, Any]] = field(default_factory=list)

    def record_dispatch(self, context_pack: ContextPack, result: ImplementerResult) -> None:
        """Record one IMPLEMENTER dispatch and its result."""
        self.dispatch_count += 1
        self.last_status = result.status
        self.context_updates_applied += len(context_pack.context_updates)
        self.dispatch_history.append({
            "dispatch_number": self.dispatch_count,
            "status": result.status.value,
            "test_pass_rate": result.test_pass_rate,
            "files_modified": result.files_modified,
            "context_updates": len(context_pack.context_updates),
        })

    def can_redispatch(self, new_context: list[str]) -> tuple[bool, str]:
        """
        Check if re-dispatch is allowed (FR-IMPL-008).

        Returns (allowed, reason).
        Allowed if:
          1. Last status was BLOCKED or NEEDS_CONTEXT, AND
          2. New context updates are provided (non-empty), AND
          3. dispatch_count < max_retries.
        """
        if self.last_status == ImplementerStatus.DONE:
            return False, "Task is already DONE — no re-dispatch needed."
        if not new_context:
            return False, (
                f"FR-IMPL-008: Cannot re-dispatch task {self.task_id} without updated context. "
                f"Provide context updates addressing the blocker."
            )
        if self.dispatch_count >= 3:
            return False, (
                f"Maximum dispatch count (3) reached for task {self.task_id}. "
                f"SOAR must select ESCALATE."
            )
        return True, "Re-dispatch allowed with updated context."


# ---------------------------------------------------------------------------
# ImplementerDispatcher
# ---------------------------------------------------------------------------

class ImplementerDispatcher:
    """
    Manages IMPLEMENTER dispatch for a single pipeline.

    Enforces:
      - INV-003: IMPLEMENTER outputs best preferences only.
      - INV-006: SOAR owns phase transition — dispatcher does not advance phases.
      - FR-IMPL-008: No re-dispatch without updated context.
    """

    def __init__(self) -> None:
        self._records: dict[str, DispatchRecord] = {}

    def prepare_context(
        self,
        task_id: str,
        description: str,
        scope: str,
        language: str,
        module_boundary: str,
        cq_isc_library: list[dict[str, str]],
        psi_score: float,
        id_estimate: int,
        staging_artifacts: list[str] | None = None,
        constitution_sections: list[str] | None = None,
        context_updates: list[str] | None = None,
    ) -> ContextPack:
        """
        Assemble the context pack for an IMPLEMENTER dispatch (FR-IMPL-002).

        Scopes the CQ-ISC advisory rules to the task's language and module.
        """
        record = self._records.get(task_id)
        retry_count = record.dispatch_count if record else 0

        # Scope advisory rules to task language (all + language-specific)
        advisory = [
            {
                "cq_isc_id": entry.get("cq_isc_id", ""),
                "rule_text": entry.get("rule_text", ""),
                "constraint_class": entry.get("constraint_class", ""),
            }
            for entry in cq_isc_library
            if _matches_language(entry.get("language_scope", "all"), language)
        ]

        return ContextPack(
            task_id=task_id,
            description=description,
            scope=scope,
            language=language,
            module_boundary=module_boundary,
            cq_isc_advisory=advisory,
            staging_artifacts=staging_artifacts or [],
            constitution_sections=constitution_sections or [],
            psi_score=psi_score,
            id_estimate=id_estimate,
            retry_count=retry_count,
            context_updates=context_updates or [],
        )

    def record_result(self, context: ContextPack, result: ImplementerResult) -> None:
        """Record an IMPLEMENTER dispatch result."""
        if context.task_id not in self._records:
            self._records[context.task_id] = DispatchRecord(task_id=context.task_id)
        self._records[context.task_id].record_dispatch(context, result)

    def check_redispatch(self, task_id: str, new_context: list[str]) -> tuple[bool, str]:
        """
        Check if re-dispatch is allowed for a blocked/needs-context task (FR-IMPL-008).
        Returns (allowed, reason).
        """
        record = self._records.get(task_id)
        if record is None:
            return True, "First dispatch — always allowed."
        return record.can_redispatch(new_context)

    def get_record(self, task_id: str) -> Optional[DispatchRecord]:
        return self._records.get(task_id)

    def dispatch_count(self, task_id: str) -> int:
        record = self._records.get(task_id)
        return record.dispatch_count if record else 0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _matches_language(language_scope: str, task_language: str) -> bool:
    """Return True if the CQ-ISC entry applies to the task's language."""
    if language_scope.strip().lower() == "all":
        return True
    langs = [l.strip().lower() for l in language_scope.split(",")]
    return task_language.lower() in langs
