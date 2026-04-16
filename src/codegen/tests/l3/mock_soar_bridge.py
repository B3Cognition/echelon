"""
mock_soar_bridge.py — Mock SML bridge for L3 validation tests.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

This mock simulates SOAR prohibit preference firing based on WME injection.
It replicates the Rete evaluation semantics from codegen.soar and phases.soar
without requiring a SOAR binary.

Design:
- CQ-ISC entries are loaded from the default library YAML.
- WMEs are injected via inject_wme().
- evaluate() runs one simulated decision cycle and returns which prohibits fired.
- reset() clears all WMEs (between tests).
- The mock faithfully implements INV-005 semantics (phase-gate check first).
- The mock faithfully implements INV-002 semantics (prohibit is sole enforcement).

All L3 tests run against this mock, not a real SOAR binary, making CI feasible
without a SOAR 9.6.4 installation.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_FILE = Path(__file__).parent.parent.parent / "library" / "cq-isc-default-v1.0.0.yaml"
VALID_PHASES = {"RE", "DECOMPOSE", "IMPLEMENT", "GATE", "TEST", "DELIVER"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MockWME:
    """A Working Memory Element injected into the mock bridge."""
    attribute: str
    value: Any
    task_id: Optional[str] = None
    language: str = "python"
    status: str = "confirmed-failing"  # confirmed-failing | unstable | none


@dataclass
class EvaluationResult:
    """Result of one simulated SOAR decision cycle."""
    selected_operator: str                   # advance-phase | retry-task | escalate | deliver
    prohibits_fired: list[str]               # CQ-ISC IDs whose prohibit preference fired
    cq_isc_ids_evaluated: list[str]          # all CQ-ISC IDs evaluated
    phase: str                               # current phase at evaluation time
    psi_score: float
    violations_confirmed: list[str]          # violation types that triggered prohibits

    @property
    def any_prohibit_fired(self) -> bool:
        return len(self.prohibits_fired) > 0


# ---------------------------------------------------------------------------
# CQ-ISC entry (simplified for mock)
# ---------------------------------------------------------------------------

@dataclass
class MockCQISCEntry:
    cq_isc_id: str
    constraint_class: str
    phase_scope: str          # VERIFY | DELIVER | ALL
    language_scope: str       # all | typescript | python | go | java
    soar_predicate: str
    wme_source: str
    policy_drift_status: str  # current | drifted | pending-review
    psi_contribution_weight: float
    test_proxy_observable: bool
    rule_text: str

    def applies_to_phase(self, phase: str) -> bool:
        """INV-005: check phase scope before evaluating predicate."""
        if self.phase_scope == "ALL":
            return True
        if self.phase_scope == "VERIFY":
            return phase == "GATE"
        if self.phase_scope == "DELIVER":
            return phase == "DELIVER"
        return False

    def applies_to_language(self, language: str) -> bool:
        if self.language_scope.strip().lower() == "all":
            return True
        langs = [l.strip().lower() for l in self.language_scope.split(",")]
        return language.lower() in langs

    def is_enforceable(self) -> bool:
        """Only current entries fire prohibit preferences."""
        return self.policy_drift_status == "current"


# ---------------------------------------------------------------------------
# Mock SOAR Bridge
# ---------------------------------------------------------------------------

class MockSOARBridge:
    """
    Mock SML bridge for L3 tests.

    Simulates SOAR Rete evaluation semantics:
    - INV-005: phase-gate is checked FIRST before any predicate.
    - INV-002: prohibit preference is the sole enforcement mechanism.
    - INV-008: conflict impasse when all operators are prohibited simultaneously.
    - Quarantine: drifted and pending-review entries do NOT fire prohibits.
    """

    def __init__(
        self,
        library_file: Path = LIBRARY_FILE,
        initial_phase: str = "GATE",
        psi_score: float = 0.5,
        psi_threshold: float = 0.70,
        retry_count: int = 0,
        max_retries: int = 3,
        tier1_gate: str = "pending",
        language: str = "python",
    ):
        self._phase = initial_phase
        self._psi_score = psi_score
        self._psi_threshold = psi_threshold
        self._retry_count = retry_count
        self._max_retries = max_retries
        self._tier1_gate = tier1_gate
        self._language = language

        self._wmes: list[MockWME] = []
        self._audit_log: list[dict] = []
        self._entries: list[MockCQISCEntry] = []

        self._load_library(library_file)

    # ------------------------------------------------------------------
    # Public API (mirrors SOARBridge interface)
    # ------------------------------------------------------------------

    def inject_wme(self, attribute: str, value: Any, task_id: Optional[str] = None, status: str = "confirmed-failing") -> MockWME:
        """Inject a WME into mock Working Memory."""
        wme = MockWME(
            attribute=attribute,
            value=value,
            task_id=task_id,
            language=self._language,
            status=status,
        )
        self._wmes.append(wme)
        return wme

    def inject_violation(self, cq_isc_id: str, status: str = "confirmed-failing") -> MockWME:
        """
        Inject a code-violation WME directly by CQ-ISC ID.
        Convenience method for L3 positive tests.
        """
        return self.inject_wme(
            attribute=f"code-violation-{cq_isc_id}",
            value=cq_isc_id,
            status=status,
        )

    def inject_metric(self, metric_name: str, value: float) -> MockWME:
        """
        Inject a code-metrics WME.
        Convenience method for threshold tests.
        """
        return self.inject_wme(attribute=f"code-metrics-{metric_name}", value=value)

    def evaluate(self) -> EvaluationResult:
        """
        Run one simulated SOAR decision cycle.

        Evaluates all current CQ-ISC entries against injected WMEs.
        Returns which prohibit preferences fired and the selected operator.
        """
        prohibits_fired: list[str] = []
        evaluated: list[str] = []
        violations_confirmed: list[str] = []

        for entry in self._entries:
            # Skip quarantined entries (INV-002 / SMEM quarantine semantics)
            if not entry.is_enforceable():
                continue

            # INV-005: check phase scope FIRST
            if not entry.applies_to_phase(self._phase):
                continue

            # Language scope check
            if not entry.applies_to_language(self._language):
                continue

            evaluated.append(entry.cq_isc_id)

            # Check if this entry's predicate matches any injected WME
            if self._predicate_matches(entry):
                prohibits_fired.append(entry.cq_isc_id)
                violations_confirmed.append(entry.cq_isc_id)

        # Determine selected operator (mirrors SOAR preference resolution)
        operator = self._resolve_operator(prohibits_fired)

        result = EvaluationResult(
            selected_operator=operator,
            prohibits_fired=prohibits_fired,
            cq_isc_ids_evaluated=evaluated,
            phase=self._phase,
            psi_score=self._psi_score,
            violations_confirmed=violations_confirmed,
        )

        # INV-004: record in audit log
        self._audit_log.append({
            "phase": self._phase,
            "operator": operator,
            "prohibits": prohibits_fired,
            "evaluated": evaluated,
            "psi": self._psi_score,
        })

        return result

    def reset(self):
        """Clear all injected WMEs. Called between tests."""
        self._wmes.clear()

    def set_phase(self, phase: str):
        """Set the current pipeline phase."""
        assert phase in VALID_PHASES, f"Invalid phase: {phase}"
        self._phase = phase

    def set_psi(self, score: float):
        self._psi_score = score

    def set_tier1_gate(self, status: str):
        assert status in {"pending", "pass", "fail", "running", "unavailable"}
        self._tier1_gate = status

    def set_retry_count(self, count: int):
        self._retry_count = count

    def set_language(self, language: str):
        self._language = language

    def get_entry(self, cq_isc_id: str) -> Optional[MockCQISCEntry]:
        """Look up a CQ-ISC entry by ID."""
        for e in self._entries:
            if e.cq_isc_id == cq_isc_id:
                return e
        return None

    def get_all_entry_ids(self) -> list[str]:
        return [e.cq_isc_id for e in self._entries]

    def get_audit_log(self) -> list[dict]:
        return list(self._audit_log)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_library(self, library_file: Path):
        """Load CQ-ISC entries from YAML library file."""
        if not library_file.exists():
            print(f"[MockSOARBridge] WARNING: Library file not found: {library_file}", file=sys.stderr)
            return

        raw = yaml.safe_load(library_file.read_text())
        entries_raw = raw.get("entries", raw) if isinstance(raw, dict) else raw

        for e in entries_raw:
            if not isinstance(e, dict):
                continue
            self._entries.append(MockCQISCEntry(
                cq_isc_id=str(e.get("cq_isc_id", "")),
                constraint_class=str(e.get("constraint_class", "")).upper(),
                phase_scope=str(e.get("phase_scope", "VERIFY")).upper(),
                language_scope=str(e.get("language_scope", "all")),
                soar_predicate=str(e.get("soar_predicate", "")),
                wme_source=str(e.get("wme_source", "")),
                policy_drift_status=str(e.get("policy_drift_status", "current")),
                psi_contribution_weight=float(e.get("psi_contribution_weight", 1.0)),
                test_proxy_observable=bool(e.get("test_proxy_observable", True)),
                rule_text=str(e.get("rule_text", "")),
            ))

    def _predicate_matches(self, entry: MockCQISCEntry) -> bool:
        """
        Check if any injected WME matches this entry's predicate.

        Two distinct matching paths:
        1. Violation-type WMEs (attribute starts with 'code-violation-'):
           Match if the WME attribute contains the canonical violation type for this entry
           AND the WME value contains the CQ-ISC ID or the canonical violation type.
           These WMEs have an explicit status (confirmed-failing etc).
        2. Metric WMEs (attribute starts with 'code-metrics-'):
           Match ONLY if the metric name matches AND the value exceeds the threshold.
           Metric WMEs below threshold do NOT trigger prohibits (correct boundary behaviour).

        This separation ensures that:
        - inject_metric("function-length", 20) does NOT fire STRUCT-001 (20 <= 30)
        - inject_metric("function-length", 45) DOES fire STRUCT-001 (45 > 30)
        - inject_violation("CQ-ISC-SEC-001") fires SEC-001 regardless of metric thresholds
        """
        canonical = self._get_canonical_violation_type(entry.cq_isc_id)
        metric_name, threshold, op = self._parse_metric_predicate(entry.soar_predicate)
        is_metric_entry = metric_name is not None

        for wme in self._wmes:
            attr = wme.attribute

            # ------------------------------------------------------------------
            # Path 1: Violation-type WMEs (prefix: code-violation-)
            # ------------------------------------------------------------------
            if attr.startswith("code-violation-"):
                # Skip non-failing violation WMEs
                if wme.status == "unstable" or wme.status == "none":
                    continue

                # Match: canonical violation type must be in attribute
                if canonical and not is_metric_entry:
                    if canonical in attr:
                        return True

                # Match: CQ-ISC ID injected directly as value
                if entry.cq_isc_id in str(wme.value):
                    return True

                # Match: canonical name in value (e.g., value="hardcoded-secret")
                if canonical and canonical in str(wme.value):
                    return True

            # ------------------------------------------------------------------
            # Path 2: Metric WMEs (prefix: code-metrics-)
            # For metric-based entries, ONLY fire if threshold is exceeded.
            # A below-threshold metric WME must NOT trigger the prohibit.
            # ------------------------------------------------------------------
            elif attr.startswith("code-metrics-") and is_metric_entry:
                # The metric name must appear in the attribute
                if metric_name and metric_name in attr:
                    try:
                        val = float(wme.value)
                        if op == ">" and val > threshold:
                            return True
                        if op == ">=" and val >= threshold:
                            return True
                        if op == "<" and val < threshold:
                            return True
                        if op == "<=" and val <= threshold:
                            return True
                    except (TypeError, ValueError):
                        pass
                # If metric name doesn't match this entry, skip — do NOT fall through
                # to canonical matching to avoid cross-entry false positives.

        return False

    def _get_canonical_violation_type(self, cq_isc_id: str) -> Optional[str]:
        """Extract the canonical violation type from a CQ-ISC ID."""
        mapping = {
            "CQ-ISC-SEC-001": "hardcoded-secret",
            "CQ-ISC-SEC-002": "sql-injection-risk",
            "CQ-ISC-SEC-003": "eval-exec-user-input",
            "CQ-ISC-SEC-004": "http-request-no-timeout",
            "CQ-ISC-SEC-005": "cors-wildcard-sensitive",
            "CQ-ISC-SEC-006": "secret-in-logs",
            "CQ-ISC-STRUCT-001": "function-length",
            "CQ-ISC-STRUCT-002": "cyclomatic-complexity",
            "CQ-ISC-STRUCT-003": "circular-import",
            "CQ-ISC-STRUCT-004": "parameter-count",
            "CQ-ISC-STRUCT-005": "file-length",
            "CQ-ISC-STRUCT-006": "nesting-depth",
            "CQ-ISC-TEST-001": "missing-test-file",
            "CQ-ISC-TEST-002": "untested-public-function",
            "CQ-ISC-TEST-003": "test-file-no-assertion",
            "CQ-ISC-TEST-004": "test-name-too-short",
            "CQ-ISC-QUAL-001": "debug-print-in-production",
            "CQ-ISC-QUAL-002": "unlinked-todo-in-production",
            "CQ-ISC-QUAL-003": "magic-number",
            "CQ-ISC-QUAL-004": "dead-code",
        }
        return mapping.get(cq_isc_id)

    def _parse_metric_predicate(self, predicate: str) -> tuple[Optional[str], float, str]:
        """
        Parse metric predicates like "(code-metrics <m> ^function-length > 30)".
        Returns (metric_name, threshold, operator) or (None, 0, ">").

        Only matches predicates that reference code-metrics WMEs specifically.
        Predicates referencing code-violation WMEs (SEC/TEST/QUAL entries) return None.
        This prevents false metric matches on predicates like
        "(code-violation <v> ^type |hardcoded-secret| ^count > 0)".
        """
        # Only parse metric predicates from entries that reference code-metrics
        # The canonical metric predicate format used in the library:
        # "(code-metrics <m> ^function-length > 30)"
        if "code-metrics" not in predicate:
            return None, 0.0, ">"
        # Match the ^<metric-name> <op> <value> portion after code-metrics
        m = re.search(r"code-metrics.*?\^\s*([\w-]+)\s*(>|>=|<|<=|=)\s*(\d+(?:\.\d+)?)", predicate)
        if m:
            return m.group(1), float(m.group(3)), m.group(2)
        return None, 0.0, ">"

    def _resolve_operator(self, prohibits_fired: list[str]) -> str:
        """
        Resolve the selected SOAR operator given which prohibits fired.

        Mirrors the preference resolution in codegen.soar:
        - If prohibits fired AND retry < max: retry-task
        - If prohibits fired AND retry >= max: escalate
        - If at DELIVER, tier1=pass, psi>=threshold, no prohibits: deliver
        - If tier1=fail at TEST: retry-tier1
        - Otherwise: advance-phase (or wait if psi too low)
        """
        if prohibits_fired:
            if self._retry_count < self._max_retries:
                return "retry-task"
            else:
                return "escalate"

        if self._phase == "DELIVER":
            if self._tier1_gate == "pass" and self._psi_score >= self._psi_threshold:
                return "deliver"
            elif self._tier1_gate == "fail":
                return "retry-tier1"
            elif self._psi_score < self._psi_threshold:
                return "wait-psi"

        if self._phase == "TEST":
            if self._tier1_gate == "fail":
                return "retry-tier1"
            if self._tier1_gate == "pass":
                return "advance-phase"

        if self._psi_score >= self._psi_threshold:
            return "advance-phase"

        return "wait"
