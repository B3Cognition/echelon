"""
model_b_evaluator.py — Model B (per-phase) SOAR evaluator extensions.
Spec 018 T-005: tier0 gate evaluation for Model B parity.

INV-006: This module reads WM state and returns decision strings.
The CALLER is responsible for advancing current_phase via soar_bridge.
This module NEVER advances current_phase directly.
"""
from __future__ import annotations


class PipelineBlockedError(Exception):
    """
    Raised by Model B evaluator when a gate block is detected.
    Spec 018 AC-004-4: Model B MUST block on failed tier0 gate — silent continuation is a bug.

    Attributes:
        gate: the gate that triggered the block (e.g. "tier0_gate")
        reason: human-readable description of why the block was raised
        wm_state_snapshot: the WM state dict at block time (for EPMEM recording)
    """

    def __init__(self, gate: str, reason: str, wm_state_snapshot: dict | None = None) -> None:
        self.gate = gate
        self.reason = reason
        self.wm_state_snapshot = wm_state_snapshot or {}
        super().__init__(f"Pipeline blocked at gate '{gate}': {reason}")


def evaluate_model_b_tier0(wm_state: dict) -> str:
    """
    Evaluate the Tier 0 Gate decision in Model B mode.
    Mirrors SOAR productions in tier0_gate.soar.

    INV-006 preserved: this function reads WM state and returns a decision string.
    The caller advances current_phase only via soar_bridge.

    Args:
        wm_state: The deserialized WM state dict (from codegen-wm-state.json).

    Returns:
        One of: "ADVANCE" | "BLOCK" | "DEGRADE"

    Raises:
        PipelineBlockedError: When tier0_gate == "failed" (AC-004-4: must block, not continue).
    """
    tier0 = wm_state.get("tier0_gate")

    if tier0 is None:
        # AC-003-3: absent field means gate has not run → treat as ADVANCE
        return "ADVANCE"

    if tier0 == "failed":
        # AC-004-4: Model B MUST raise, not silently continue
        violation_count = wm_state.get("tier0_gate_violation_count", 0)
        language = wm_state.get("tier0_gate_language", "unknown")
        raise PipelineBlockedError(
            gate="tier0_gate",
            reason=(
                f"LSP gate failed for language '{language}' "
                f"with {violation_count} violation(s). "
                "Pipeline blocked before TEST phase."
            ),
            wm_state_snapshot=dict(wm_state),
        )

    if tier0 == "unavailable":
        # NFR-008: tool absence is a WARNING, not a fatal error
        return "DEGRADE"

    if tier0 == "passed":
        return "ADVANCE"

    # Unknown value: degrade gracefully (TP-004: WME-first, trust WM state)
    return "ADVANCE"


def evaluate_model_b_anchoring(wm_state: dict, code_text: str = "") -> str:
    """
    Evaluate the Anchoring Gate decision in Model B mode.
    Mirrors SOAR productions in anchoring.soar.

    INV-006 preserved: this function reads WM state and returns a decision string.
    The caller advances current_phase only via soar_bridge.

    Args:
        wm_state: The deserialized WM state dict (from codegen-wm-state.json).
        code_text: Generated code to evaluate against constraints (optional).

    Returns:
        One of: "PASS" | "BLOCK" | "UNAVAILABLE"
    """
    raw_constraints = wm_state.get("anchoring_constraints")
    if not raw_constraints:
        # No anchoring WMEs — unavailable (AC-015 semantics)
        return "UNAVAILABLE"

    # Reconstruct AnchoringConstraint objects from WM state dicts
    try:
        from src.codegen.anchor.anchoring_types import AnchoringConstraint  # noqa: PLC0415
        from src.codegen.anchor.anchoring_evaluator import AnchoringEvaluator  # noqa: PLC0415
    except ImportError:
        from codegen.anchor.anchoring_types import AnchoringConstraint  # type: ignore[no-redef]
        from codegen.anchor.anchoring_evaluator import AnchoringEvaluator  # type: ignore[no-redef]

    constraints = [
        AnchoringConstraint(
            constraint_id=c.get("constraint_id", ""),
            dimension=c.get("dimension", ""),
            constraint_text=c.get("constraint_text", ""),
            source_path=c.get("source_path", ""),
            run_id=c.get("run_id", ""),
        )
        for c in raw_constraints
        if c.get("status") == "active"
    ]

    if not constraints:
        return "UNAVAILABLE"

    if not code_text:
        # No code to evaluate — constraints present but nothing to check → PASS
        return "PASS"

    evaluator = AnchoringEvaluator()
    violations = evaluator.evaluate(code_text, constraints)

    if violations:
        return "BLOCK"
    return "PASS"
