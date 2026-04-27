"""
phase_gate.py — Phase gate runner: scan violations, inject WMEs, get SOAR decision.
Spec 008: SOAR-Powered Claude Code Software Development Agent

Called at every phase transition. Injects violations into SOAR, gets operator
decision, updates codegen-state.json, records EPMEM (INV-004).

INV-002: Violations block ONLY via SOAR prohibit — never by Python logic.
INV-006: PhaseGateRunner does NOT set current_phase directly.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Lazy imports to avoid circular deps and allow graceful degradation
try:
    from codegen.bridge.soar_bridge import SOARBridge
    from codegen.analysis.violation_scanner import CqIscViolation, ViolationScanner
    from codegen.security.yaml_safety import YamlSafety
    from codegen.memory.mempalace_reader import MemPalaceReader
    from codegen.memory.mempalace_writer import MemPalaceWriter
    from codegen.memory.requirements_miner import RequirementsMiner
    from codegen.memory.context import MemPalaceContext
    from codegen.decompose.cartographer import (
        CartographerDispatcher,
        CONFIDENCE_THRESHOLD_AUTO,
        CONFIDENCE_THRESHOLD_FLAGGED,
    )
except ImportError:
    from src.codegen.bridge.soar_bridge import SOARBridge  # type: ignore[no-redef]
    from src.codegen.analysis.violation_scanner import CqIscViolation, ViolationScanner  # type: ignore[no-redef]
    from src.codegen.security.yaml_safety import YamlSafety  # type: ignore[no-redef]
    from src.codegen.memory.mempalace_reader import MemPalaceReader  # type: ignore[no-redef]
    from src.codegen.memory.mempalace_writer import MemPalaceWriter  # type: ignore[no-redef]
    from src.codegen.memory.requirements_miner import RequirementsMiner  # type: ignore[no-redef]
    from src.codegen.memory.context import MemPalaceContext  # type: ignore[no-redef]
    from src.codegen.decompose.cartographer import (  # type: ignore[no-redef]
        CartographerDispatcher,
        CONFIDENCE_THRESHOLD_AUTO,
        CONFIDENCE_THRESHOLD_FLAGGED,
    )

# CQ-ISC library path (same default as soar_bridge.py)
_DEFAULT_SMEM_FILE = Path(__file__).parent.parent / "library" / "cq-isc-default-v1.0.0.yaml"

# Phase-gate operator → canonical decision mapping
_OPERATOR_DECISION_MAP: dict[str, str] = {
    "advance-phase": "ADVANCE",
    "deliver": "DELIVER",
    "retry-task": "RETRY",
    "escalate": "ESCALATE",
    "respecify": "RESPECIFY",  # Spec 026 FR-013: confidence-gated FR revision
    "unknown": "RETRY",  # conservative fallback
}

# Default Ψ threshold
PSI_THRESHOLD = 0.70

# Default max retries per phase
DEFAULT_MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# GateDecision dataclass
# ---------------------------------------------------------------------------

@dataclass
class RequirementCitation:
    """FR-RM-006: A cited requirement drawer attached to a gate decision."""
    req_id: str
    content: str
    room: str
    distance: float
    drawer_id: str


@dataclass
class GateDecision:
    decision: str              # ADVANCE | RETRY | ESCALATE | DELIVER
    operator: str              # advance-phase | retry-task | escalate | deliver
    violations_blocked: int
    cq_isc_fired: list[str]
    cq_isc_evaluated: list[str]
    violations: list[dict]     # serialized CqIscViolation list
    psi_score: float
    psi_weighted: float
    retry_count: int
    max_retries: int
    soar_model: str            # "A" | "B"
    soar_pid: int | None
    phase: str
    timestamp_ms: int
    requirement_citations: list[RequirementCitation] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


# ---------------------------------------------------------------------------
# PhaseGateRunner
# ---------------------------------------------------------------------------

class PhaseGateRunner:
    """
    Evaluates a phase gate by:
      1. Starting/reusing a SOARBridge (Model A preferred)
      2. Injecting phase WMEs (current-phase, pipeline-status)
      3. Running ViolationScanner on files
      4. Injecting each violation as a code-violation WME
      5. Computing and injecting Ψ score
      6. Calling get_selected_operator() for SOAR decision
      7. Mapping operator to GateDecision
      8. Updating codegen-state.json
      9. Recording EPMEM (INV-004)
    """

    def __init__(self, state_file: Path = Path("codegen-state.json"), verbose: bool = False) -> None:
        self.state_file = state_file
        self.verbose = verbose
        self._bridge: SOARBridge | None = None
        self._scanner = ViolationScanner()
        self._retry_counts: dict[str, int] = {}

        # Load MemoryConfig automatically from ~/.echelon/memory-config.yml
        try:
            from codegen.memory.config import MemoryConfigLoader
        except ImportError:
            from src.codegen.memory.config import MemoryConfigLoader  # type: ignore
        _default_config_path = Path.home() / ".echelon" / "memory-config.yml"
        self._memory_config = MemoryConfigLoader.load(
            _default_config_path if _default_config_path.exists() else None
        )

    def run_gate(
        self,
        phase: str,
        files: list[Path],
        language: str,
        task_id: str | None = None,
        working_dir: Path | None = None,
    ) -> GateDecision:
        """
        Full gate evaluation for one phase transition.

        Args:
            phase: Current pipeline phase name (e.g. "GATE").
            files: Source files produced in this phase.
            language: Detected language ("python" | "typescript" | …).
            task_id: Optional task identifier for EPMEM.
            working_dir: Optional CWD override for subprocess calls.

        Returns:
            GateDecision with SOAR operator decision.
        """
        bridge = self._get_bridge()

        # Step 2: Inject phase WMEs
        bridge.inject_wme("current-phase", phase, task_id=task_id)
        bridge.inject_wme("pipeline-status", "active", task_id=task_id)

        # Step 3: Run violation scanner
        violations = self._scanner.scan(files=files, language=language, working_dir=working_dir)

        # Step 4: Inject each violation as a WME
        for v in violations:
            bridge.inject_wme(
                "code-violation",
                {
                    "cq-isc-id": v.cq_isc_id,
                    "status": "confirmed-failing",
                    "file": v.file,
                    "line": v.line,
                },
                task_id=task_id,
            )

        # Step 5: Compute and inject Ψ score
        psi_score, psi_weighted, total_eligible = self._compute_psi(violations)
        bridge.inject_wme("psi-score", psi_score, task_id=task_id)
        bridge.inject_wme("psi-threshold", PSI_THRESHOLD, task_id=task_id)

        # Step 5b: TEST phase requires tier1-gate=pass for SOAR's TEST→DELIVER rule.
        # If no violations were found, the static scan passed — inject tier1-gate pass.
        # The caller is responsible for only invoking the TEST gate after tests have run.
        if phase == "TEST":
            tier1_status = "pass" if not violations else "fail"
            bridge.inject_wme("tier1-gate", tier1_status, task_id=task_id)

        # Step 6: Get SOAR operator decision
        op = bridge.get_selected_operator()

        # Step 7: Map operator → decision
        decision = _OPERATOR_DECISION_MAP.get(op.operator_name, "RETRY")

        # Compute violations_blocked (CQ-ISC-IDs that fired prohibit)
        fired_ids = op.prohibit_fired or []
        violations_blocked = len(fired_ids) if fired_ids else len(violations)

        # Retry count tracking
        retry_count = self._retry_counts.get(phase, 0)
        if decision == "RETRY":
            retry_count += 1
            self._retry_counts[phase] = retry_count
            # FR-008: Auto-mine bug drawer on every RETRY event (non-fatal)
            self._mine_bug_on_retry(phase, violations, retry_count, task_id)

        max_retries = self._load_max_retries()

        # If retry count >= max_retries, escalate (INV-008)
        if decision == "RETRY" and retry_count >= max_retries:
            decision = "ESCALATE"

        # Spec 026 FR-013: Handle RESPECIFY operator — dispatch CartographerDispatcher
        if decision == "RESPECIFY":
            working_dir = self.state_file.parent if self.state_file else Path(".")
            decision = self._handle_respecify(phase, violations, task_id, working_dir)

        ts = int(time.time() * 1000)

        # Step 7b: GATE traceability — fetch FR citations from MemPalace (FR-RM-006)
        citations = self._fetch_requirement_citations(violations, phase)

        gate = GateDecision(
            decision=decision,
            operator=op.operator_name,
            violations_blocked=violations_blocked,
            cq_isc_fired=fired_ids,
            cq_isc_evaluated=op.cq_isc_ids_evaluated or [],
            violations=[v.to_dict() for v in violations],
            psi_score=psi_score,
            psi_weighted=psi_weighted,
            retry_count=retry_count,
            max_retries=max_retries,
            soar_model=bridge.model.value,
            soar_pid=bridge._pid,
            phase=phase,
            timestamp_ms=ts,
            requirement_citations=citations,
        )

        # Step 8: Update codegen-state.json
        self._update_state_file(gate)

        # Step 9: Record EPMEM (INV-004)
        self._record_epmem(bridge, gate, task_id)

        logger.info(
            "[PhaseGate] phase=%s decision=%s Ψ=%.3f violations_blocked=%d soar_model=%s",
            phase, decision, psi_score, violations_blocked, bridge.model.value,
        )
        return gate

    def close(self) -> None:
        """Shutdown SOAR bridge if it was started."""
        if self._bridge is not None:
            try:
                self._bridge.shutdown()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[PhaseGate] Bridge shutdown error: %s", exc)
            self._bridge = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_bridge(self) -> SOARBridge:
        """Return existing bridge or create a new one (Model A preferred)."""
        if self._bridge is not None:
            return self._bridge

        bridge = SOARBridge(verbose=self.verbose, memory_config=self._memory_config)
        started = bridge.start()
        if not started:
            # Model B fallback already set internally by bridge.start()
            logger.warning("[PhaseGate] SOAR Model A unavailable — using Model B fallback")
        self._bridge = bridge
        return bridge

    def _compute_psi(
        self, violations: list[CqIscViolation]
    ) -> tuple[float, float, int]:
        """
        Compute Ψ score against CQ-ISC library.

        psi_score = rules with no confirmed-failing violations / total_eligible_rules
        psi_weighted = weighted version using psi_contribution_weight

        Returns (psi_score, psi_weighted, total_eligible).
        """
        rules = _load_cq_isc_rules()
        if not rules:
            # No library loaded — return neutral score
            return 1.0, 1.0, 0

        failing_ids = {v.cq_isc_id for v in violations if v.status == "confirmed-failing"}
        total_eligible = len(rules)
        total_weight = sum(r.get("psi_contribution_weight", 1.0) for r in rules)

        covered_count = sum(1 for r in rules if r.get("cq_isc_id") not in failing_ids)
        covered_weight = sum(
            r.get("psi_contribution_weight", 1.0)
            for r in rules
            if r.get("cq_isc_id") not in failing_ids
        )

        psi_score = covered_count / total_eligible if total_eligible > 0 else 1.0
        psi_weighted = covered_weight / total_weight if total_weight > 0 else 1.0
        return round(psi_score, 4), round(psi_weighted, 4), total_eligible

    def _load_max_retries(self) -> int:
        """Load max_retries from state file, or return default."""
        if self.state_file.exists():
            try:
                state = json.loads(self.state_file.read_text())
                return int(state.get("max_retries", DEFAULT_MAX_RETRIES))
            except (json.JSONDecodeError, OSError, ValueError):
                pass
        return DEFAULT_MAX_RETRIES

    def _update_state_file(self, gate: GateDecision) -> None:
        """Write gate result fields to codegen-state.json."""
        state: dict[str, Any] = {}
        if self.state_file.exists():
            try:
                state = json.loads(self.state_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        state["current_phase"] = gate.phase
        state["last_gate_decision"] = gate.decision
        state["psi"] = {
            "score": gate.psi_score,
            "threshold": PSI_THRESHOLD,
        }
        state["cq_isc_violations_blocked"] = gate.violations_blocked
        state["soar_model"] = gate.soar_model

        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(state, indent=2))
        except OSError as exc:
            logger.warning("[PhaseGate] Could not write state to %s: %s", self.state_file, exc)

    def _fetch_requirement_citations(
        self,
        violations: list,
        phase: str,
    ) -> list[RequirementCitation]:
        """
        FR-RM-006: Search MemPalace for requirement drawers relevant to each violation.

        Each CQ-ISC violation maps to a requirement category — e.g. a security
        violation (CQ-ISC-SEC-*) maps to "security-requirements". This method
        retrieves the closest matching FR/NFR drawers and attaches them to the
        gate decision for traceability.

        Non-fatal: returns empty list if MemPalace is unavailable.
        """
        if not violations:
            return []

        citations: list[RequirementCitation] = []
        seen_drawer_ids: set[str] = set()

        # Read wing from state file (same pattern as _mine_bug_on_retry)
        _state: dict = {}
        if self.state_file.exists():
            try:
                _state = json.loads(self.state_file.read_text())
            except Exception:
                pass
        wing = _state.get("wing") or "codegen"
        pipeline_id = _state.get("pipeline_id", "gate")
        ctx = MemPalaceContext.from_wing(wing=wing, run_id=pipeline_id)
        reader = MemPalaceReader(ctx)

        for v in violations[:5]:  # Cap at 5 to avoid latency explosion
            query = f"{v.cq_isc_id} {getattr(v, 'rule_text', '')} phase:{phase}"
            result = reader.search(query=query, n_results=2)
            for drawer in result.drawers:
                if drawer.drawer_id in seen_drawer_ids:
                    continue
                seen_drawer_ids.add(drawer.drawer_id)
                citations.append(RequirementCitation(
                    req_id=drawer.req_id or drawer.drawer_id,
                    content=drawer.content[:200],
                    room=drawer.room,
                    distance=drawer.distance,
                    drawer_id=drawer.drawer_id,
                ))

        if citations:
            logger.info(
                "[PhaseGate] Traceability: %d FR citations attached for phase=%s",
                len(citations), phase,
            )
        return citations

    def _record_epmem(
        self,
        bridge: SOARBridge,
        gate: GateDecision,
        task_id: str | None,
    ) -> None:
        """Record phase transition in EPMEM (INV-004)."""
        try:
            bridge.record_phase_transition(
                from_phase=gate.phase,
                to_phase=_next_phase(gate.phase, gate.decision),
                psi_score=gate.psi_score,
                violations_blocked=gate.violations_blocked,
                cq_isc_evaluated=gate.cq_isc_evaluated,
                cq_isc_fired=gate.cq_isc_fired,
                task_id=task_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PhaseGate] EPMEM record_phase_transition failed: %s", exc)

    def _mine_bug_on_retry(
        self,
        phase: str,
        violations: list[Any],
        retry_count: int,
        task_id: str | None,
    ) -> None:
        """
        FR-008: Auto-mine a bug drawer to MemPalace on every RETRY event.
        FR-009: Aggregate all violations into a single bug drawer.
        FR-010: Non-fatal — exceptions caught; RETRY continues.
        FR-011: Skip silently if wing absent from state file.
        FR-012: Bug drawer includes failing test name, violation IDs, fr_id, retry count, pipeline_id.
        FR-023: EPMEM entry written for each mined bug drawer.
        """
        try:
            # Read wing and pipeline_id from state file (FR-011)
            state: dict = {}
            if self.state_file.exists():
                try:
                    state = json.loads(self.state_file.read_text())
                except Exception:
                    pass

            wing = state.get("wing") or state.get("project_name")
            if not wing:
                logger.debug(
                    "[PhaseGate] Bug mining skipped: no wing in state file (FR-011)"
                )
                return

            pipeline_id = state.get("pipeline_id", "unknown")
            fr_id = task_id or "UNTRACED"

            # Aggregate all violations into one bug dict (FR-009)
            violation_ids = [getattr(v, "cq_isc_id", str(v)) for v in violations]
            violation_messages = [getattr(v, "message", "") or "" for v in violations]
            test_name = (
                getattr(violations[0], "file", None) if violations else None
            ) or f"phase:{phase}"

            bug = {
                "id": f"{retry_count:03d}",
                "title": (
                    f"Phase {phase} failure (retry {retry_count}): "
                    + (violation_ids[0] if violation_ids else "unknown")
                ),
                "test_name": test_name,
                "fr_id": fr_id,
                "description": "; ".join(
                    f"{vid}: {msg}"
                    for vid, msg in zip(violation_ids, violation_messages)
                ) or "(no violation details)",
                "file": ",".join(
                    getattr(v, "file", "") for v in violations if getattr(v, "file", "")
                ),
                "iteration": retry_count,
                "pipeline_id": pipeline_id,
            }

            ctx = MemPalaceContext.from_wing(wing=wing, run_id=pipeline_id)
            miner = RequirementsMiner(ctx, project_dir=Path("."))
            mine_result = miner.mine_bug(bug)
            logger.info(
                "[PhaseGate] Bug mined: phase=%s retry=%d fr_id=%s drawer_ids=%s",
                phase, retry_count, fr_id, mine_result.drawer_ids,
            )

            # FR-023: EPMEM entry for bug drawer
            if mine_result.drawer_ids:
                try:
                    bridge = self._get_bridge()
                    bridge.record_phase_transition(
                        from_phase=phase,
                        to_phase=phase,  # same phase — not advancing
                        psi_score=0.0,
                        violations_blocked=len(violations),
                        cq_isc_evaluated=[],
                        cq_isc_fired=[],
                        task_id=task_id,
                    )
                except Exception as epmem_exc:
                    logger.warning("[PhaseGate] Bug EPMEM entry failed (non-fatal): %s", epmem_exc)

        except Exception as exc:  # noqa: BLE001
            # FR-010: Non-fatal — RETRY continues regardless
            logger.warning(
                "[PhaseGate] Bug mining failed (non-fatal, FR-010): %s", exc
            )

    def _append_respec_log(
        self,
        working_dir: Path,
        timestamp: str,
        task_id: str,
        original_fr: str,
        revised_fr: str,
        confidence: float,
        outcome: str,
        raw_response: str | None = None,
    ) -> None:
        """
        FR-019: Append a RESPECIFY event record to respec-log.md.
        Append-only; creates file if absent; OSError is non-fatal.
        """
        log_path = working_dir / "respec-log.md"
        flag = " [FLAGGED]" if outcome == "flagged" else ""
        lines = [
            f"\n## RESPECIFY — {timestamp}{flag}\n",
            f"- **task_id**: {task_id}\n",
            f"- **confidence**: {confidence:.4f}\n",
            f"- **outcome**: {outcome}\n",
            f"- **original_fr**: {original_fr[:500]}\n",
            f"- **revised_fr**: {revised_fr[:500]}\n",
        ]
        if raw_response is not None:
            lines.append(
                f"- **raw_response (parse failed)**:\n```\n{raw_response[:1000]}\n```\n"
            )
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as f:
                f.writelines(lines)
        except OSError as exc:
            logger.warning("[PhaseGate] respec-log.md write failed (non-fatal): %s", exc)

    def _handle_respecify(
        self,
        phase: str,
        violations: list[Any],
        task_id: str | None,
        working_dir: Path | None,
    ) -> str:
        """
        FR-013–FR-020, FR-024: Dispatch CartographerDispatcher, apply confidence thresholds.

        Returns:
            "ADVANCE" (auto-apply or flagged) or "ESCALATE".
        """
        import datetime
        import uuid as _uuid

        state: dict = {}
        if self.state_file.exists():
            try:
                state = json.loads(self.state_file.read_text())
            except Exception:
                pass

        wing = state.get("wing", "unknown")
        pipeline_id = state.get("pipeline_id", "unknown")
        fr_id = task_id or "UNTRACED"
        wd = working_dir or Path(".")
        ts = datetime.datetime.utcnow().isoformat() + "Z"

        ctx = MemPalaceContext.from_wing(wing=wing, run_id=pipeline_id)
        reader = MemPalaceReader(ctx)

        # Retrieve original FR
        fr_drawer = reader.lookup_drawer_by_req_id(fr_id, room="functional-requirements")
        original_fr = fr_drawer.content if fr_drawer else ""

        # Retrieve bug drawers for this task + pipeline (FR-015)
        bug_result = reader.search(query=fr_id, room="bugs", n_results=10)
        bug_context = "\n".join(
            d.content for d in bug_result.drawers
            if pipeline_id in d.metadata.get("pipeline_id", "")
        ) or "(no bug drawers for this pipeline run)"

        # Summarise current violations
        test_output = "; ".join(
            f"{getattr(v, 'cq_isc_id', '?')}: {getattr(v, 'message', '')}"
            for v in violations
        ) or "(no violations)"

        # Dispatch CartographerDispatcher (FR-016, FR-024)
        cart_result = CartographerDispatcher().dispatch(original_fr, bug_context, test_output)
        confidence = cart_result.confidence

        # FR-017: Apply confidence thresholds
        if confidence >= CONFIDENCE_THRESHOLD_AUTO:
            outcome = "auto-apply"
            new_status: str | None = "auto-respecified"
        elif confidence >= CONFIDENCE_THRESHOLD_FLAGGED:
            outcome = "flagged"
            new_status = "flagged-respecify"
        else:
            outcome = "escalate"
            new_status = None

        # FR-019: Write respec-log.md for every RESPECIFY event
        self._append_respec_log(
            wd, ts, fr_id, original_fr,
            cart_result.revised_fr if outcome != "escalate" else "N/A",
            confidence, outcome,
            cart_result.raw_response if not cart_result.parse_success else None,
        )

        if outcome == "escalate":
            # Write codegen-impasse.md
            impasse_path = wd / "codegen-impasse.md"
            try:
                impasse_path.write_text(
                    f"# RESPECIFY Impasse\n\n"
                    f"**task_id**: {fr_id}\n"
                    f"**confidence**: {confidence:.4f} (threshold: {CONFIDENCE_THRESHOLD_FLAGGED})\n\n"
                    f"## Original FR\n\n{original_fr}\n\n"
                    f"## Proposed Revision\n\n{cart_result.revised_fr or '(parse failed)'}\n\n"
                    f"## Rationale\n\n{cart_result.rationale}\n\n"
                    f"## Resolution\n\n"
                    f"Update the spec, re-mine, and re-run the pipeline.\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning("[PhaseGate] codegen-impasse.md write failed: %s", exc)
            return "ESCALATE"

        # FR-018: Apply revision — update FR drawer + write revised drawer
        if fr_drawer and new_status:
            try:
                _run_id = str(_uuid.uuid4())
                ctx_w = MemPalaceContext.from_wing(wing=wing, run_id=_run_id)
                writer = MemPalaceWriter(ctx_w)
                writer.backfill_status([fr_drawer.drawer_id], new_status)
                if cart_result.revised_fr:
                    writer.write(
                        room="functional-requirements",
                        content=cart_result.revised_fr,
                        phase="RESPECIFY",
                        provenance_type="cartographer",
                        status=new_status,
                    )
            except Exception as exc:
                logger.warning("[PhaseGate] RESPECIFY FR update failed: %s", exc)

        # FR-020: EPMEM entry for RESPECIFY transition
        try:
            bridge = self._get_bridge()
            bridge.record_phase_transition(
                from_phase=phase,
                to_phase="IMPLEMENT",
                psi_score=confidence,
                violations_blocked=len(violations),
                cq_isc_evaluated=[],
                cq_isc_fired=[],
                task_id=task_id,
            )
        except Exception as exc:
            logger.warning("[PhaseGate] RESPECIFY EPMEM failed: %s", exc)

        # FR-018: Reset retry count; pipeline advances
        self._retry_counts[phase] = 0
        logger.info(
            "[PhaseGate] RESPECIFY outcome=%s confidence=%.2f fr_id=%s",
            outcome, confidence, fr_id,
        )
        return "ADVANCE"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

_PHASES = ["RE", "DECOMPOSE", "IMPLEMENT", "GATE", "TEST", "DELIVER"]


def _next_phase(current: str, decision: str) -> str:
    """Return the logical next phase name after a gate decision."""
    if decision in ("ADVANCE", "DELIVER"):
        try:
            idx = _PHASES.index(current)
            return _PHASES[idx + 1] if idx + 1 < len(_PHASES) else "DONE"
        except ValueError:
            return "UNKNOWN"
    return current  # RETRY / ESCALATE stay in same phase


def _load_cq_isc_rules() -> list[dict]:
    """Load CQ-ISC library entries. Returns empty list on failure."""
    try:
        data = YamlSafety.load(_DEFAULT_SMEM_FILE)
        if isinstance(data, dict):
            return data.get("entries", [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PhaseGate] Could not load CQ-ISC library: %s", exc)
    return []
