"""
smem_writer.py — SmemPatternWriter: SOAR SMEM write-back via _send_command().
Spec 024 T-026/T-027: F5 Cross-Run SMEM Accumulation.

ARCHITECTURAL DECISION (T-026 PR):
  SmemPatternWriter is implemented ALONGSIDE smem_accumulator.py, NOT extending it.
  Reason: smem_accumulator.py is a file-I/O class with zero SOAR coupling.
  Adding SOAR bridge dependency there would couple a file class to a subprocess —
  different failure modes, different test requirements. SmemPatternWriter owns
  the SOAR SMEM write-back path exclusively. MemoryManager (or PipelineEngine)
  coordinates both layers at DELIVER phase.

INV-003: Only `best` preferences — never prohibit, require, or worst.
FR-ACC-001: Write-back only triggered at DELIVER phase with Ψ ≥ 0.70.
FR-ACC-002: Human approval required before any smem --add call.
FR-ACC-004: Tag ^critical true for CQ-ISC-SEC-* and CQ-ISC-MSR-* patterns.
NFR-SEC-003: Credential validation before smem --add (see _validate_content).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Patterns that must NOT appear in SMEM content (NFR-SEC-003).
# CANONICAL SOURCE — imported by codegen.security.secret_scrubber for MemPalace write scrubbing.
# Do NOT import secret_scrubber here (circular import).
_CREDENTIAL_DENY_PATTERNS = [
    re.compile(r"/Users/[^/\s]+"),            # absolute macOS paths
    re.compile(r"/home/[^/\s]+"),             # absolute Linux paths
    re.compile(r"C:\\\\[^\\s]+"),             # Windows absolute paths
    re.compile(r"sk-[A-Za-z0-9]{20,}"),       # OpenAI-style API keys
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}"),  # emails
    re.compile(r"(?i)(password|secret|token)\s*[:=]\s*\S+"),          # credential assignments
]

# CQ-ISC classes that get ^critical true (FR-ACC-004)
_CRITICAL_CONSTRAINT_CLASSES = {"CQ-ISC-SEC", "CQ-ISC-MSR"}


@dataclass
class PatternCandidate:
    """
    A candidate pattern for SOAR SMEM write-back.
    Produced by identify_patterns_for_accumulation() in smem_accumulator.py.
    Consumed by SmemPatternWriter.write().
    """
    source_run_id: str
    psi_score_at_accumulation: float
    phase: str
    cq_isc_ids_active: list[str]
    codebase_language: str
    schema_version: int = 1

    @property
    def is_critical(self) -> bool:
        """True when any active CQ-ISC ID belongs to SEC or MSR class (FR-ACC-004)."""
        for cq_id in self.cq_isc_ids_active:
            prefix = "-".join(cq_id.split("-")[:3])  # e.g. "CQ-ISC-SEC"
            if prefix in _CRITICAL_CONSTRAINT_CLASSES:
                return True
        return False

    @property
    def smem_lti_content(self) -> str:
        """
        Generate the SOAR SMEM --add content for this pattern.
        Format: (<lti> ^attr val ^attr val ...)
        INV-003: best preferences only — this is informational content, not a rule.
        """
        cq_ids_str = " ".join(f"|{cid}|" for cid in self.cq_isc_ids_active)
        critical_str = "true" if self.is_critical else "false"
        return (
            f"(<lti> "
            f"^type |cq-isc-pattern| "
            f"^schema-version {self.schema_version} "
            f"^source-run-id |{self.source_run_id}| "
            f"^psi-score-at-accumulation {self.psi_score_at_accumulation:.4f} "
            f"^phase |{self.phase}| "
            f"^cq-isc-ids-active {cq_ids_str} "
            f"^codebase-language |{self.codebase_language}| "
            f"^critical {critical_str} "
            f"^accumulated-at (time))"
        )


class SmemPatternWriter:
    """
    Writes approved PatternCandidates into SOAR SMEM via bridge._send_command().

    This class has ONE responsibility: bridge the approved patterns into SOAR's
    persistent SMEM database. It does NOT manage the JSON patterns file
    (that remains smem_accumulator.py's domain).

    Usage (at DELIVER phase, after human approval):
        writer = SmemPatternWriter(bridge)
        count = writer.write(candidates)
    """

    def __init__(self, bridge: Any) -> None:
        """
        Args:
            bridge: SOARBridge instance (Model A). Must be alive.
        """
        self._bridge = bridge
        self._patterns_written: int = 0

    @property
    def patterns_written(self) -> int:
        return self._patterns_written

    def write(self, candidates: list[PatternCandidate]) -> int:
        """
        Write approved PatternCandidates into SOAR SMEM via `smem --add`.

        Validates each candidate's content before writing (NFR-SEC-003).
        Skips candidates that fail validation (logs ERROR, does not raise).

        Args:
            candidates: List of approved PatternCandidates to write.

        Returns:
            Number of patterns successfully written to SOAR SMEM.
        """
        written = 0
        for candidate in candidates:
            content = candidate.smem_lti_content
            if not self._validate_content(content, candidate.source_run_id):
                continue

            smem_cmd = f"smem --add {{{content}}}"
            try:
                self._bridge._send_command(smem_cmd)
                written += 1
                logger.info(
                    "[SmemPatternWriter] smem --add: run_id=%s phase=%s cq_ids=%s critical=%s",
                    candidate.source_run_id,
                    candidate.phase,
                    candidate.cq_isc_ids_active,
                    candidate.is_critical,
                )
            except Exception as exc:
                logger.error(
                    "[SmemPatternWriter] smem --add failed for run_id=%s: %s",
                    candidate.source_run_id, exc,
                )

        self._patterns_written += written
        return written

    @staticmethod
    def _validate_content(content: str, run_id: str) -> bool:
        """
        Validate pattern content against credential deny-list (NFR-SEC-003).
        Returns True if safe, False (and logs ERROR) if a deny-pattern matches.
        """
        for pattern in _CREDENTIAL_DENY_PATTERNS:
            match = pattern.search(content)
            if match:
                logger.error(
                    "[SmemPatternWriter] REJECTED pattern for run_id=%s: "
                    "content matches credential deny-pattern %r at %r",
                    run_id, pattern.pattern, match.group(0),
                )
                return False
        return True
