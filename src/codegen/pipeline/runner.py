"""
runner.py — Pipeline phase runner with F1 Tier 0 Gate integration.
Spec 018 T-006.

Inserts the Tier 0 LSP Pre-Flight Gate sub-phase between DECOMPOSE and TEST.
Pipeline phase order (with F1 addition):
  RE → DECOMPOSE → [TIER0_GATE] → IMPLEMENT → GATE → TEST → DELIVER

INV-006: The runner DOES NOT advance current_phase directly.
         It calls soar_bridge.inject_tier0_gate_wme() and lets SOAR decide.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..bridge.model_b_evaluator import PipelineBlockedError, evaluate_model_b_tier0
from ..bridge.soar_bridge import SOARBridge, SOARBridgeModel
from ..epmem.recorder import Tier0GateRecorder
from ..lsp.lsp_gate import LspGate, LspResult

if TYPE_CHECKING:
    from ..memory.run_index import RunIndex
    from ..memory.smem_accumulator import SmemAccumulator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tier 0 Gate runner function
# ---------------------------------------------------------------------------

def run_tier0_gate(
    language: str,
    files: list[Path],
    state_file: Path,
    soar_bridge: SOARBridge,
    timeout_seconds: float = 30.0,
    working_dir: Path | None = None,
) -> LspResult:
    """
    Execute the F1 LSP Pre-Flight Gate sub-phase.

    Steps (per T-006 AC):
    1. Invoke LspGate.run() — produces LspResult
    2. Call soar_bridge.inject_tier0_gate_wme(result) — injects WME
    3. Write codegen-state.json tier0_gate + tier0_gate_violations fields
    4. Record EPMEM event (INV-004)
    5. Return LspResult — caller uses SOAR decision to advance (INV-006)

    Args:
        language: Detected project language for this run.
        files: Source files to analyze.
        state_file: Path to codegen-state.json for writing tier0_gate results.
        soar_bridge: Active SOAR bridge (Model A or B).
        timeout_seconds: Hard timeout for LSP tool subprocess.
        working_dir: Optional working directory override.

    Returns:
        LspResult from the gate invocation.

    Raises:
        PipelineBlockedError: (Model B only) When gate fails and bridge is in Model B.
                              Model A raises the block via SOAR prohibit preference.
    """
    # Step 1: Run LSP gate
    gate = LspGate(timeout_seconds=timeout_seconds)
    result = gate.run(language=language, files=files, working_dir=working_dir)

    # Step 2: Inject WME into SOAR (Model A) or WM state (Model B)
    soar_bridge.inject_tier0_gate_wme(result)

    # Step 3: Persist to codegen-state.json
    _write_tier0_state(result, state_file)

    # Step 4: Record EPMEM (INV-004)
    recorder = Tier0GateRecorder()
    event = recorder.record(result)
    logger.info(
        "EPMEM [%s] language=%s tool=%s violations=%d duration=%.2fs",
        event.event_type,
        result.language,
        result.tool_name,
        len(result.violations),
        result.duration_seconds,
    )

    # Step 5: Model B evaluation (if applicable)
    if soar_bridge.model == SOARBridgeModel.B:
        wm_state = soar_bridge._load_wm_state()
        decision = evaluate_model_b_tier0(wm_state)  # raises PipelineBlockedError if BLOCK
        logger.info("Model B tier0 decision: %s", decision)
        if decision == "DEGRADE":
            logger.warning(
                "[TIER0] Tool '%s' unavailable for language '%s'. "
                "Pipeline continues with degraded quality (NFR-008).",
                result.tool_name, result.language,
            )

    # Log summary (AC-002-4: pipeline summary must include violations count + tool version)
    _log_gate_summary(result)

    return result


def increment_run_sequence_number(
    state_file: Path,
    run_index: "RunIndex | None" = None,
) -> int:
    """
    Increment the run_sequence_number counter in codegen-state.json.
    Spec 018 T-021.

    Steps:
    1. Load codegen-state.json (create if absent)
    2. Read run_sequence_number (default 0 if absent)
    3. Increment by 1
    4. Save back to state file
    5. If run_index provided: calls run_index.record(run_id, sequence_number)
    6. Returns new sequence_number

    Args:
        state_file: Path to codegen-state.json.
        run_index:  Optional RunIndex to record the new sequence number.

    Returns:
        The new (incremented) sequence_number.
    """
    import uuid as _uuid

    state: dict[str, Any] = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    current = state.get("run_sequence_number", 0)
    new_sequence = current + 1
    state["run_sequence_number"] = new_sequence

    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(state, indent=2))
    except OSError as exc:
        logger.warning("Could not write run_sequence_number to %s: %s", state_file, exc)

    if run_index is not None:
        run_id = state.get("run_id") or str(_uuid.uuid4())
        run_index.record(run_id, new_sequence)

    return new_sequence


def load_and_inject_smem_patterns(
    soar_bridge: "SOARBridge",
    state_file: Path,
    accumulator: "SmemAccumulator | None" = None,
) -> list:
    """
    Phase 0 DECOMPOSE: load active SMEM patterns and inject as best preferences.
    Project isolation: only inject patterns matching current code_domain_hash.
    INV-003: patterns injected as best preferences ONLY.

    Args:
        soar_bridge: Active SOAR bridge (Model A or B).
        state_file:  Path to codegen-state.json (used to derive code_domain_hash).
        accumulator: Optional SmemAccumulator; if None, creates one in CWD.

    Returns:
        List of WMEInjectionResult from inject_smem_pattern_wmes().
    """
    from ..memory.smem_accumulator import SmemAccumulator as _SmemAccumulator

    if accumulator is None:
        accumulator = _SmemAccumulator()

    # Derive current code_domain_hash from state file if available
    code_domain_hash: str | None = None
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            code_domain_hash = state.get("code_domain_hash")
        except (json.JSONDecodeError, OSError):
            pass

    active_patterns = accumulator.load_active_patterns(
        code_domain_hash=code_domain_hash,
    )

    if not active_patterns:
        return []

    return soar_bridge.inject_smem_pattern_wmes(active_patterns)


def deliver_pipeline(soar_bridge: SOARBridge) -> None:
    """
    Call at DELIVER to clear transient anchoring constraints (AC-015-1/2/3).
    INV-006: Does not advance current_phase directly.
    """
    soar_bridge.clear_anchoring_constraint_wmes()
    logger.info("[DELIVER] Anchoring constraint WMEs cleared (transient lifetime enforced).")


def abort_pipeline(soar_bridge: SOARBridge) -> None:
    """
    Call at ABORT to clear transient anchoring constraints (AC-015-1/2/3).
    INV-006: Does not advance current_phase directly.
    """
    soar_bridge.clear_anchoring_constraint_wmes()
    logger.info("[ABORT] Anchoring constraint WMEs cleared (transient lifetime enforced).")


def _write_tier0_state(result: LspResult, state_file: Path) -> None:
    """
    Write tier0_gate and tier0_gate_violations to codegen-state.json.
    Spec 018 T-006 AC: state fields updated after gate.
    """
    state: dict[str, Any] = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    state["tier0_gate"] = result.status
    state["tier0_gate_violations"] = (
        [
            {
                "file": v.file,
                "line": v.line,
                "column": v.column,
                "error_code": v.error_code,
                "message": v.message,
                "severity": v.severity,
            }
            for v in result.violations
        ]
        if result.status != "unavailable"
        else None
    )

    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(state, indent=2))
    except OSError as exc:
        logger.warning("Could not write tier0_gate state to %s: %s", state_file, exc)


def _log_gate_summary(result: LspResult) -> None:
    """Log gate summary for pipeline output (AC-002-4)."""
    if result.status == "passed":
        logger.info(
            "[TIER0] PASS — language=%s tool=%s version=%s (%.2fs)",
            result.language, result.tool_name, result.tool_version, result.duration_seconds,
        )
    elif result.status == "failed":
        logger.warning(
            "[TIER0] FAIL — language=%s tool=%s violations=%d%s (%.2fs)",
            result.language,
            result.tool_name,
            len(result.violations),
            " [TIMEOUT]" if result.timeout_hit else "",
            result.duration_seconds,
        )
    else:
        logger.warning(
            "[TIER0] UNAVAILABLE — language=%s tool=%s not found on PATH (NFR-008 degraded mode)",
            result.language, result.tool_name,
        )
