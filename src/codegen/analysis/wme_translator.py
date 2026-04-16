"""
wme_translator.py — WME Translator: static analysis output → SOAR WMEs.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

T-011: Maps normalised ViolationRecord objects (from T-010 adapters) to
SOAR WME dictionaries that can be injected into Working Memory.

Lookup table:
  The translator is initialised with the CQ-ISC library (CQISCEntry list).
  A tool+rule_id → cq_isc_id index is built from the TOOL_RULE_MAP constant
  (derived from the wme_source field and the rule-id catalogue in descriptions).

WME types produced:
  - code-violation WME : for type-based predicates
      {"wme_type": "code-violation", "cq_isc_id": "...", "type": "...",
       "count": N, "status": "confirmed-failing|unstable|none",
       "files": [...], "task_id": "..."}
  - code-metrics WME   : for numeric threshold predicates
      {"wme_type": "code-metrics", "cq_isc_id": "...", "metric": "...",
       "value": N, "status": "confirmed-failing|unstable|none",
       "task_id": "..."}

Instability detection (FR-TEST-008):
  A violation is "unstable" if it appeared in fewer than 2 of the last 3 runs.
  CQ-ISC prohibit preferences gate on "confirmed-failing", not "unstable".
  The run_history dict maps violation_key → deque of booleans (True = appeared).

ADR-008-004: Translator output is deterministic: same input always → same WME set.
"""

from __future__ import annotations

import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Tool → Rule-ID → CQ-ISC-ID mapping table
#
# Source: descriptions in cq-isc-default-v1.0.0.yaml.
# Format: {tool_name: {rule_id: cq_isc_id}}
# ---------------------------------------------------------------------------

TOOL_RULE_MAP: dict[str, dict[str, str]] = {
    "eslint": {
        # Security
        "no-eval":              "CQ-ISC-SEC-003",
        "no-cors-wildcard":     "CQ-ISC-SEC-005",
        "no-warning-comments":  "CQ-ISC-QUAL-002",
        # Structural
        "max-lines-per-function": "CQ-ISC-STRUCT-001",
        "complexity":             "CQ-ISC-STRUCT-002",
        "import/no-cycle":        "CQ-ISC-STRUCT-003",
        "max-params":             "CQ-ISC-STRUCT-004",
        "max-lines":              "CQ-ISC-STRUCT-005",
        "max-depth":              "CQ-ISC-STRUCT-006",
        # Quality
        "no-console":            "CQ-ISC-QUAL-001",
        "no-magic-numbers":      "CQ-ISC-QUAL-003",
        "no-unreachable":        "CQ-ISC-QUAL-004",
    },
    "ruff": {
        # Security (bandit codes via ruff)
        "S105": "CQ-ISC-SEC-001",
        "S106": "CQ-ISC-SEC-001",
        "S107": "CQ-ISC-SEC-001",
        "S608": "CQ-ISC-SEC-002",
        "S307": "CQ-ISC-SEC-003",
        "S113": "CQ-ISC-SEC-004",
        # Quality
        "T201": "CQ-ISC-QUAL-001",
        "T202": "CQ-ISC-QUAL-001",
        "FIX001": "CQ-ISC-QUAL-002",
        "FIX002": "CQ-ISC-QUAL-002",
        "FIX003": "CQ-ISC-QUAL-002",
        "FIX004": "CQ-ISC-QUAL-002",
        "PLR2004": "CQ-ISC-QUAL-003",
        "F401": "CQ-ISC-QUAL-004",
        "F811": "CQ-ISC-QUAL-004",
        # Structural — ruff C901 is complexity; length checks are separate
        "C901":    "CQ-ISC-STRUCT-002",   # cyclomatic complexity
        "PLR0913": "CQ-ISC-STRUCT-004",   # too many arguments
    },
    "golangci-lint": {
        "gocyclo":    "CQ-ISC-STRUCT-002",
        "nestif":     "CQ-ISC-STRUCT-006",
        "forbidigo":  "CQ-ISC-QUAL-001",
        "deadcode":   "CQ-ISC-QUAL-004",
        "unused":     "CQ-ISC-QUAL-004",
    },
    "checkstyle": {
        # Full Checkstyle class names (as extracted by CheckstyleAdapter)
        "MethodLengthCheck":          "CQ-ISC-STRUCT-001",
        "CyclomaticComplexityCheck":  "CQ-ISC-STRUCT-002",
        "ParameterNumberCheck":       "CQ-ISC-STRUCT-004",
        "FileLengthCheck":            "CQ-ISC-STRUCT-005",
        "RegexpSinglelineCheck":      "CQ-ISC-QUAL-001",
        "MagicNumberCheck":           "CQ-ISC-QUAL-003",
        # Short names (used in error messages directly, without package prefix)
        "MethodLength":          "CQ-ISC-STRUCT-001",
        "CyclomaticComplexity":  "CQ-ISC-STRUCT-002",
        "ParameterNumber":       "CQ-ISC-STRUCT-004",
        "FileLength":            "CQ-ISC-STRUCT-005",
        "RegexpSingleline":      "CQ-ISC-QUAL-001",
        "MagicNumber":           "CQ-ISC-QUAL-003",
    },
}


# ---------------------------------------------------------------------------
# WME dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CodeViolationWME:
    """
    SOAR code-violation WME.
    Corresponds to predicates: (code-violation <v> ^type |...| ^count > 0)
    """
    cq_isc_id: str
    violation_type: str    # maps to ^type in SOAR predicate
    count: int
    status: str            # confirmed-failing | unstable | none
    files: list[str]
    task_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "wme_type": "code-violation",
            "cq_isc_id": self.cq_isc_id,
            "type": self.violation_type,
            "count": self.count,
            "status": self.status,
            "files": sorted(self.files),
            "task_id": self.task_id,
        }


@dataclass
class CodeMetricsWME:
    """
    SOAR code-metrics WME.
    Corresponds to predicates: (code-metrics <m> ^function-length > 30)
    """
    cq_isc_id: str
    metric_name: str       # function-length | cyclomatic-complexity | parameter-count | ...
    value: float
    status: str            # confirmed-failing | unstable | none
    task_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "wme_type": "code-metrics",
            "cq_isc_id": self.cq_isc_id,
            "metric": self.metric_name,
            "value": self.value,
            "status": self.status,
            "task_id": self.task_id,
        }


# ---------------------------------------------------------------------------
# Predicate-type to WME-type mapping
#
# CQ-ISC entries whose soar_predicate starts with "(code-metrics" use
# CodeMetricsWME; others use CodeViolationWME.
# ---------------------------------------------------------------------------

# Map cq_isc_id → (wme_type, metric_name or violation_type)
_CQ_ISC_WME_SHAPE: dict[str, tuple[str, str]] = {
    # code-violation entries
    "CQ-ISC-SEC-001": ("violation", "hardcoded-secret"),
    "CQ-ISC-SEC-002": ("violation", "sql-injection-risk"),
    "CQ-ISC-SEC-003": ("violation", "eval-exec-user-input"),
    "CQ-ISC-SEC-004": ("violation", "http-request-no-timeout"),
    "CQ-ISC-SEC-005": ("violation", "cors-wildcard-sensitive"),
    "CQ-ISC-SEC-006": ("violation", "secret-in-logs"),
    "CQ-ISC-STRUCT-003": ("violation", "circular-import"),
    "CQ-ISC-TEST-001": ("violation", "missing-test-file"),
    "CQ-ISC-TEST-002": ("violation", "untested-public-function"),
    "CQ-ISC-TEST-003": ("violation", "test-file-no-assertion"),
    "CQ-ISC-TEST-004": ("violation", "test-name-too-short"),
    "CQ-ISC-QUAL-001": ("violation", "debug-print-in-production"),
    "CQ-ISC-QUAL-002": ("violation", "unlinked-todo-in-production"),
    "CQ-ISC-QUAL-003": ("violation", "magic-number"),
    "CQ-ISC-QUAL-004": ("violation", "dead-code"),
    # code-metrics entries
    "CQ-ISC-STRUCT-001": ("metrics", "function-length"),
    "CQ-ISC-STRUCT-002": ("metrics", "cyclomatic-complexity"),
    "CQ-ISC-STRUCT-004": ("metrics", "parameter-count"),
    "CQ-ISC-STRUCT-005": ("metrics", "file-length"),
    "CQ-ISC-STRUCT-006": ("metrics", "nesting-depth"),
}


# ---------------------------------------------------------------------------
# WMETranslator
# ---------------------------------------------------------------------------

class WMETranslator:
    """
    Translate ViolationRecord objects from static analysis adapters into
    SOAR WME dicts ready for bridge injection.

    Usage:
        from codegen.analysis.adapters import RuffAdapter
        from codegen.analysis.wme_translator import WMETranslator

        adapter = RuffAdapter()
        violations = adapter.parse(ruff_json_output)

        translator = WMETranslator()
        wmes = translator.translate(violations, task_id="T-003")

        for wme in wmes:
            bridge.inject_wme(wme["type"], wme["value"])

    Instability detection:
        translator.record_run(violation_key, appeared=True/False)
        The status "unstable" is set when a violation appeared < 2 of 3 runs.
        confirmed-failing is set when it appeared in >= 2 of 3 runs (or only 1 run
        when history has < 3 entries).
    """

    INSTABILITY_WINDOW = 3     # number of runs to track
    INSTABILITY_THRESHOLD = 2  # minimum appearances to be "confirmed-failing"

    def __init__(self) -> None:
        # run_history[violation_key] = deque of bools (True = appeared in that run)
        self._run_history: dict[str, deque[bool]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def translate(
        self,
        violations: list,
        task_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Translate a list of ViolationRecord objects into SOAR WME dicts.

        Violations that map to no known CQ-ISC entry are silently dropped
        (they are not enforced by SOAR — correct per spec).

        Returns a deterministic list sorted by cq_isc_id.
        """
        # Group violations by cq_isc_id
        by_cq_isc: dict[str, list] = {}
        for v in violations:
            cq_isc_id = self._lookup(v.tool, v.rule_id)
            if cq_isc_id is None:
                continue
            by_cq_isc.setdefault(cq_isc_id, []).append(v)

        # Build WMEs
        wmes: list[dict[str, Any]] = []
        for cq_isc_id in sorted(by_cq_isc.keys()):
            group = by_cq_isc[cq_isc_id]
            shape = _CQ_ISC_WME_SHAPE.get(cq_isc_id)
            if shape is None:
                continue

            violation_key = f"{cq_isc_id}:{task_id}"
            self._record_run(violation_key, appeared=True)
            status = self._compute_status(violation_key)

            wme_type, type_or_metric = shape
            if wme_type == "violation":
                wme = CodeViolationWME(
                    cq_isc_id=cq_isc_id,
                    violation_type=type_or_metric,
                    count=len(group),
                    status=status,
                    files=sorted({v.file for v in group}),
                    task_id=task_id,
                )
            else:
                # metrics: use the maximum value across all violations
                max_value = max(
                    (v.line for v in group),  # line is best proxy for metric value from adapters
                    default=1,
                )
                wme = CodeMetricsWME(
                    cq_isc_id=cq_isc_id,
                    metric_name=type_or_metric,
                    value=float(max_value),
                    status=status,
                    task_id=task_id,
                )
            wmes.append(wme.to_dict())

        return wmes

    def record_clean_run(self, cq_isc_ids: list[str], task_id: Optional[str] = None) -> None:
        """
        Record a run where a CQ-ISC rule was evaluated but did NOT fire.
        Used for instability detection: if a rule alternates appearing/not-appearing,
        it becomes 'unstable'.
        """
        for cq_isc_id in cq_isc_ids:
            violation_key = f"{cq_isc_id}:{task_id}"
            self._record_run(violation_key, appeared=False)

    def get_status(self, cq_isc_id: str, task_id: Optional[str] = None) -> str:
        """Return the current status for a cq_isc_id/task_id pair."""
        violation_key = f"{cq_isc_id}:{task_id}"
        return self._compute_status(violation_key)

    def reset_history(self) -> None:
        """Clear all run history (use between pipelines)."""
        self._run_history.clear()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _lookup(self, tool: str, rule_id: str) -> Optional[str]:
        """Look up cq_isc_id for a given tool + rule_id pair."""
        tool_map = TOOL_RULE_MAP.get(tool.lower(), {})
        return tool_map.get(rule_id)

    def _record_run(self, violation_key: str, appeared: bool) -> None:
        if violation_key not in self._run_history:
            self._run_history[violation_key] = deque(maxlen=self.INSTABILITY_WINDOW)
        self._run_history[violation_key].append(appeared)

    def _compute_status(self, violation_key: str) -> str:
        """
        Compute status from run history.

        - < 2 appearances in last 3 runs → "unstable"
        - >= 2 appearances in last 3 runs → "confirmed-failing"
        - No history → "confirmed-failing" (first occurrence is treated as confirmed)
        """
        history = self._run_history.get(violation_key)
        if not history:
            return "confirmed-failing"
        appearances = sum(1 for x in history if x)
        if len(history) < self.INSTABILITY_WINDOW:
            # Not enough history — treat as confirmed-failing on first occurrence
            return "confirmed-failing"
        if appearances < self.INSTABILITY_THRESHOLD:
            return "unstable"
        return "confirmed-failing"
