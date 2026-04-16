"""
gate.py — Delivery Gate and delivery package assembly.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

T-025: DELIVER operator logic and delivery package assembly.

DELIVER operator fires when ALL of:
  1. Tier 1 gate: ^test-pass-rate 1.0 AND ^build-status CLEAN (INV-010)
  2. Ψ ≥ psi-threshold (default 0.70; Phase 2 uses simplified |I_D| proxy)
  3. Zero CQ-ISC violations at DELIVER phase-scope

Partial delivery path (FR-DELIVER-006):
  - Ψ ≥ partial-delivery-threshold (0.60) AND < psi-threshold
  - Requires explicit user confirmation before proceeding

FR-DELIVER-004: Delivery package includes:
  - All generated source files
  - All generated test files
  - Generated CI YAML
  - codegen-report.md (human-readable)
  - codegen-epmem.json (structured EPMEM record)

AC-BENCH-004: failing unit test → SOAR selects RETRY_TASK, not DELIVER.
              After max retries → SOAR selects ESCALATE.
INV-010: test-pass-rate 1.0 is the gate condition.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Thresholds and enums
# ---------------------------------------------------------------------------

PSI_THRESHOLD = 0.70               # full delivery threshold
PSI_PARTIAL_THRESHOLD = 0.60       # partial delivery threshold
MAX_RETRIES_DEFAULT = 3


class DeliveryDecision(str, Enum):
    DELIVER = "DELIVER"             # all gates pass
    PARTIAL = "PARTIAL"             # Ψ in [0.60, 0.70) — requires confirmation
    RETRY_TASK = "RETRY_TASK"       # test gate failed, retry budget remaining
    ESCALATE = "ESCALATE"           # max retries exhausted with failures
    BLOCKED = "BLOCKED"             # CQ-ISC violations or Ψ < partial threshold


# ---------------------------------------------------------------------------
# Gate result
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    """
    Aggregated gate evaluation result for the DELIVER operator.

    FR-DELIVER-001: Gate is evaluated after every IMPLEMENTER task.
    """
    task_id: str
    tier1_pass: bool                    # test-pass-rate == 1.0 AND build CLEAN
    test_pass_rate: float               # from TestResult WME
    build_status: str                   # CLEAN | FAILING
    psi_score: float                    # Ψ coverage metric (or proxy)
    psi_threshold: float = PSI_THRESHOLD
    psi_partial_threshold: float = PSI_PARTIAL_THRESHOLD
    cq_isc_violations: list[str] = field(default_factory=list)  # CQ-ISC IDs at DELIVER scope
    retry_count: int = 0
    max_retries: int = MAX_RETRIES_DEFAULT

    # Derived
    decision: Optional[DeliveryDecision] = None

    def evaluate(self) -> "GateResult":
        """Compute the DeliveryDecision and set self.decision."""
        self.decision = _evaluate_gate(self)
        return self

    def to_wme_dict(self) -> dict[str, Any]:
        """Serialize as SOAR WME."""
        return {
            "wme_type": "delivery-gate",
            "task-id": self.task_id,
            "tier1-pass": self.tier1_pass,
            "test-pass-rate": round(self.test_pass_rate, 4),
            "build-status": self.build_status,
            "psi-score": round(self.psi_score, 4),
            "psi-threshold": self.psi_threshold,
            "cq-isc-violations": self.cq_isc_violations,
            "decision": self.decision.value if self.decision else None,
            "retry-count": self.retry_count,
            "preference": "best",   # INV-003
        }


def _evaluate_gate(gate: GateResult) -> DeliveryDecision:
    """
    Core decision logic for the DELIVER operator.

    AC-BENCH-004: failing test → RETRY_TASK (not DELIVER).
    INV-010: test-pass-rate 1.0 required for DELIVER.
    FR-DELIVER-006: Ψ ≥ partial threshold → PARTIAL (with confirmation).
    """
    # Tier 1 gate failure (AC-BENCH-004)
    if not gate.tier1_pass or gate.test_pass_rate < 1.0:
        if gate.retry_count >= gate.max_retries:
            return DeliveryDecision.ESCALATE
        return DeliveryDecision.RETRY_TASK

    # CQ-ISC violations block delivery
    if gate.cq_isc_violations:
        return DeliveryDecision.BLOCKED

    # Ψ below partial threshold → hard block
    if gate.psi_score < gate.psi_partial_threshold:
        return DeliveryDecision.BLOCKED

    # Ψ in partial zone [psi_partial_threshold, psi_threshold)
    if gate.psi_score < gate.psi_threshold:
        return DeliveryDecision.PARTIAL

    # All gates pass
    return DeliveryDecision.DELIVER


# ---------------------------------------------------------------------------
# Delivery package
# ---------------------------------------------------------------------------

@dataclass
class DeliveryPackage:
    """
    Assembled delivery package per FR-DELIVER-004.

    Contents:
      - source_files: all generated source files
      - test_files: all generated test files
      - ci_yaml: GitHub Actions workflow YAML path
      - report: codegen-report.md path (human-readable)
      - epmem: codegen-epmem.json path (structured audit)
      - partial: True if this is a partial delivery (FR-DELIVER-006)
    """
    pipeline_id: str
    task_id: str
    source_files: list[Path] = field(default_factory=list)
    test_files: list[Path] = field(default_factory=list)
    ci_yaml: Optional[Path] = None
    report: Optional[Path] = None
    epmem: Optional[Path] = None
    partial: bool = False
    gate_result: Optional[GateResult] = None
    state_checkpoint: dict[str, Any] = field(default_factory=dict)

    def to_manifest(self) -> dict[str, Any]:
        """
        Build a delivery manifest dict.

        FR-DELIVER-004: package contents are enumerable.
        """
        return {
            "pipeline_id": self.pipeline_id,
            "task_id": self.task_id,
            "partial": self.partial,
            "source_files": [str(p) for p in self.source_files],
            "test_files": [str(p) for p in self.test_files],
            "ci_yaml": str(self.ci_yaml) if self.ci_yaml else None,
            "report": str(self.report) if self.report else None,
            "epmem": str(self.epmem) if self.epmem else None,
            "gate": self.gate_result.to_wme_dict() if self.gate_result else None,
            "state_checkpoint": self.state_checkpoint,
        }

    def write_manifest(self, output_path: Path) -> Path:
        """Write delivery manifest JSON to disk."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(self.to_manifest(), indent=2), encoding="utf-8")
        return output_path

    @property
    def is_complete(self) -> bool:
        """True if this package contains all required artifacts."""
        return (
            len(self.source_files) > 0
            and self.ci_yaml is not None
            and self.report is not None
            and self.epmem is not None
        )


# ---------------------------------------------------------------------------
# Delivery gate evaluator
# ---------------------------------------------------------------------------

class DeliveryGate:
    """
    DELIVER operator implementation.

    Evaluates all gate conditions and produces a DeliveryDecision.
    Assembles the delivery package on success.

    FR-DELIVER-001..006, INV-010, AC-BENCH-004.
    """

    def __init__(
        self,
        psi_threshold: float = PSI_THRESHOLD,
        psi_partial_threshold: float = PSI_PARTIAL_THRESHOLD,
        max_retries: int = MAX_RETRIES_DEFAULT,
    ) -> None:
        self.psi_threshold = psi_threshold
        self.psi_partial_threshold = psi_partial_threshold
        self.max_retries = max_retries

    def evaluate(
        self,
        task_id: str,
        test_pass_rate: float,
        build_status: str,
        psi_score: float,
        cq_isc_violations: list[str],
        retry_count: int = 0,
    ) -> GateResult:
        """
        Evaluate delivery gate conditions.

        Returns a GateResult with decision field set.
        """
        tier1_pass = (test_pass_rate == 1.0 and build_status == "CLEAN")
        gate = GateResult(
            task_id=task_id,
            tier1_pass=tier1_pass,
            test_pass_rate=test_pass_rate,
            build_status=build_status,
            psi_score=psi_score,
            psi_threshold=self.psi_threshold,
            psi_partial_threshold=self.psi_partial_threshold,
            cq_isc_violations=cq_isc_violations,
            retry_count=retry_count,
            max_retries=self.max_retries,
        )
        return gate.evaluate()

    def assemble_package(
        self,
        pipeline_id: str,
        gate_result: GateResult,
        source_files: list[Path],
        test_files: list[Path],
        ci_yaml: Optional[Path],
        report_path: Optional[Path],
        epmem_path: Optional[Path],
        state_checkpoint: Optional[dict] = None,
    ) -> DeliveryPackage:
        """
        Assemble the delivery package after gate passes.

        FR-DELIVER-004: package includes all generated artifacts.
        FR-DELIVER-006: partial=True when decision is PARTIAL.
        Raises ValueError if gate did not pass (DELIVER or PARTIAL).
        """
        if gate_result.decision not in (DeliveryDecision.DELIVER, DeliveryDecision.PARTIAL):
            raise ValueError(
                f"Cannot assemble delivery package — gate decision is "
                f"'{gate_result.decision.value}'. "
                f"Package assembly is only allowed when decision is DELIVER or PARTIAL."
            )

        return DeliveryPackage(
            pipeline_id=pipeline_id,
            task_id=gate_result.task_id,
            source_files=source_files,
            test_files=test_files,
            ci_yaml=ci_yaml,
            report=report_path,
            epmem=epmem_path,
            partial=(gate_result.decision == DeliveryDecision.PARTIAL),
            gate_result=gate_result,
            state_checkpoint=state_checkpoint or {},
        )

    def write_state_checkpoint(
        self, state_path: Path, gate_result: GateResult, package: DeliveryPackage,
    ) -> None:
        """
        Write state.json checkpoint at DELIVER phase completion.

        FR-CMD-003: state.json updated at DELIVER.
        """
        checkpoint = {
            "deliver_phase": {
                "task_id": gate_result.task_id,
                "decision": gate_result.decision.value if gate_result.decision else None,
                "test_pass_rate": gate_result.test_pass_rate,
                "psi_score": gate_result.psi_score,
                "partial": package.partial,
                "artifacts": package.to_manifest(),
            }
        }

        if state_path.exists():
            existing = json.loads(state_path.read_text())
        else:
            existing = {}

        existing.update(checkpoint)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
