"""
pipeline_engine.py — Full pipeline lifecycle manager.
Spec 008: SOAR-Powered Claude Code Software Development Agent

Manages state across all phases. This is what `codegen run` calls.

INV-006: PipelineEngine never sets current_phase directly — it reads it from SOAR WM state.
INV-010: Deliver only when tier1_gate=pass.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from codegen.memory.context import MemPalaceContext

logger = logging.getLogger(__name__)

try:
    from codegen.pipeline.phase_gate import GateDecision, PhaseGateRunner, PSI_THRESHOLD
    from codegen.pipeline.runner import deliver_pipeline, abort_pipeline
except ImportError:
    from src.codegen.pipeline.phase_gate import GateDecision, PhaseGateRunner, PSI_THRESHOLD  # type: ignore[no-redef]
    from src.codegen.pipeline.runner import deliver_pipeline, abort_pipeline  # type: ignore[no-redef]

PHASES = ["RE", "DECOMPOSE", "IMPLEMENT", "GATE", "TEST", "DELIVER"]


# ---------------------------------------------------------------------------
# PipelineState dataclass
# ---------------------------------------------------------------------------

@dataclass
class PipelineState:
    pipeline_id: str
    mode: str                  # brownfield | greenfield
    target_path: str | None
    intent: str
    current_phase: str
    phases_completed: list[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    psi_score: float = 0.0
    tier1_gate: str = "pending"   # pending | pass | fail
    soar_model: str = "B"
    soar_pid: int | None = None
    violations_blocked: int = 0
    impasse_count: int = 0
    wing: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# PipelineEngine
# ---------------------------------------------------------------------------

class PipelineEngine:
    """
    Full pipeline lifecycle manager.

    Usage:
        engine = PipelineEngine()
        state = engine.initialize(intent="Build REST API", mode="greenfield")
        gate = engine.advance_phase("IMPLEMENT", files=[...], language="python")
        engine.record_tier1_result(passed=True)
        engine.deliver()
    """

    def __init__(self, state_file: Path = Path("codegen-state.json"), verbose: bool = False) -> None:
        self.state_file = state_file
        self.gate_runner = PhaseGateRunner(state_file=state_file, verbose=verbose)
        self._mempalace_writer = None  # Initialized lazily by _get_mempalace_writer()
        self._ctx: "Optional[MemPalaceContext]" = None

    def set_context(self, ctx: "MemPalaceContext") -> None:
        """Store MemPalaceContext for use by writer and RE phase."""
        self._ctx = ctx

    def run_re_phase(self, intent: str, ctx: "MemPalaceContext", n_results: int = 10) -> str:
        """
        Execute the RE phase requirement lookup.

        Searches MemPalace for requirements relevant to the intent, injects
        them as a WME into SOAR working memory, writes them to codegen-state.json,
        and records an EPMEM entry (INV-004).

        Args:
            intent: The pipeline intent.
            ctx: MemPalaceContext for this run.
            n_results: Maximum requirements to retrieve.

        Returns:
            Formatted requirements context block (markdown string), or "" if none found.
        """
        context = self.search_requirements(intent=intent, ctx=ctx, n_results=n_results)

        # Inject RE context into SOAR WM so DECOMPOSE phase can see it
        bridge = self.gate_runner._get_bridge()
        bridge.inject_wme(
            "re-requirements-context",
            f"retrieved:{n_results}:wing={ctx.wing}",
        )

        # Write retrieved requirements to state file for DECOMPOSE to consume
        state = self._read_state()
        self._write_re_context(state, context, ctx.wing)

        # EPMEM (INV-004) — record RE phase retrieval event
        try:
            bridge.record_phase_transition(
                from_phase="RE",
                to_phase="DECOMPOSE",
                psi_score=state.psi_score,
                violations_blocked=0,
                cq_isc_evaluated=[],
                cq_isc_fired=[],
            )
        except Exception as exc:
            logger.warning("[PipelineEngine] RE EPMEM record failed (non-fatal): %s", exc)

        logger.info(
            "[PipelineEngine] RE phase complete — wing=%s requirements_retrieved=%s",
            ctx.wing, "yes" if context else "no",
        )
        return context

    def _write_re_context(self, state: "PipelineState", context: str, wing: str) -> None:
        """Persist RE phase retrieval results to state file."""
        raw: dict = {}
        if self.state_file.exists():
            try:
                import json as _json
                raw = _json.loads(self.state_file.read_text())
            except Exception:
                pass
        raw["re_phase"] = {
            "wing": wing,
            "requirements_retrieved": bool(context),
            "context_length": len(context),
        }
        try:
            import json as _json
            self.state_file.write_text(_json.dumps(raw, indent=2))
        except OSError as exc:
            logger.warning("[PipelineEngine] Could not write RE context to state: %s", exc)

    def search_requirements(self, intent: str, ctx: "MemPalaceContext", n_results: int = 10) -> str:
        """
        RE phase hook (FR-RM-005): search MemPalace for requirements relevant
        to the intent and return a formatted context block.

        Called at pipeline start so IMPLEMENTER receives targeted requirements
        instead of a full spec dump. Non-fatal — returns empty string if
        MemPalace is unavailable.

        Args:
            intent: The pipeline intent (user's goal).
            ctx: MemPalaceContext for this run.
            n_results: Maximum requirements to retrieve.

        Returns:
            Formatted markdown string for context injection, or "" if unavailable.
        """
        try:
            from codegen.memory.mempalace_reader import MemPalaceReader
        except ImportError:
            from src.codegen.memory.mempalace_reader import MemPalaceReader  # type: ignore

        reader = MemPalaceReader(ctx)
        drawers = reader.search_requirements(intent=intent, n_results=n_results)

        # FR-022: Exclude delivered FRs from task decomposition context.
        # Drawers with status="delivered" must not generate implementation tasks.
        drawers = [
            d for d in drawers
            if d.metadata.get("status", "pending") != "delivered"
        ]

        if not drawers:
            logger.info(
                "[PipelineEngine] RE hook: no requirements found in MemPalace for wing=%s", ctx.wing
            )
            return ""

        context = reader.format_for_context(drawers)
        logger.info(
            "[PipelineEngine] RE hook: retrieved %d requirements from MemPalace for wing=%s",
            len(drawers), ctx.wing,
        )
        return context

    def initialize(
        self,
        intent: str,
        mode: str = "greenfield",
        target_path: str | None = None,
    ) -> PipelineState:
        """
        Create new pipeline state, start SOAR bridge, write state file.

        Args:
            intent: Human-readable goal for this pipeline run.
            mode: "greenfield" | "brownfield".
            target_path: Optional path for brownfield RE.

        Returns:
            Initial PipelineState.
        """
        now = _iso_now()
        state = PipelineState(
            pipeline_id=str(uuid.uuid4()),
            mode=mode,
            target_path=target_path,
            intent=intent,
            current_phase=PHASES[0],
            phases_completed=[],
            retry_count=0,
            max_retries=3,
            psi_score=0.0,
            tier1_gate="pending",
            soar_model="B",
            soar_pid=None,
            violations_blocked=0,
            impasse_count=0,
            created_at=now,
            updated_at=now,
        )

        if self._ctx is not None:
            state.wing = self._ctx.wing

        # Start SOAR bridge (to detect Model A/B early)
        bridge = self.gate_runner._get_bridge()
        state.soar_model = bridge.model.value
        state.soar_pid = bridge._pid

        self._write_state(state)
        logger.info(
            "[PipelineEngine] Initialized pipeline_id=%s mode=%s soar_model=%s",
            state.pipeline_id, mode, state.soar_model,
        )
        return state

    def resume(self) -> PipelineState:
        """
        Load existing state file and resume from current_phase.

        Returns:
            PipelineState loaded from state file.

        Raises:
            FileNotFoundError: If state file does not exist.
        """
        if not self.state_file.exists():
            raise FileNotFoundError(
                f"No pipeline state file found at {self.state_file}. "
                "Run `codegen run --intent <intent>` to start a new pipeline."
            )
        state = self._read_state()
        logger.info(
            "[PipelineEngine] Resuming pipeline_id=%s current_phase=%s",
            state.pipeline_id, state.current_phase,
        )
        return state

    def advance_phase(
        self,
        current_phase: str,
        files: list[Path],
        language: str,
    ) -> GateDecision:
        """
        Run gate for current_phase, return SOAR decision.

        INV-006: Does not set current_phase — reads result from GateDecision.

        Args:
            current_phase: Phase name to gate (e.g. "IMPLEMENT").
            files: Files produced in this phase.
            language: Detected language.

        Returns:
            GateDecision from SOAR.
        """
        gate = self.gate_runner.run_gate(
            phase=current_phase,
            files=files,
            language=language,
        )

        # Update tracked state
        state = self._read_state()
        state.psi_score = gate.psi_score
        state.violations_blocked = gate.violations_blocked
        state.soar_model = gate.soar_model
        state.soar_pid = gate.soar_pid
        state.updated_at = _iso_now()

        if gate.decision in ("ADVANCE", "DELIVER"):
            if current_phase not in state.phases_completed:
                state.phases_completed.append(current_phase)

        if gate.decision == "ESCALATE":
            state.impasse_count += 1

        self._write_state(state)
        return gate

    def record_tier1_result(self, passed: bool) -> None:
        """
        INV-010: Record tier1 gate result and inject WME into SOAR.

        Args:
            passed: True if all unit tests passed.
        """
        state = self._read_state()
        state.tier1_gate = "pass" if passed else "fail"
        state.updated_at = _iso_now()
        self._write_state(state)

        # Inject WME so SOAR can see tier1 result
        bridge = self.gate_runner._get_bridge()
        bridge.inject_wme("tier1-gate-result", "pass" if passed else "fail")

        logger.info(
            "[PipelineEngine] tier1_gate=%s injected into SOAR",
            state.tier1_gate,
        )

    def deliver(self) -> None:
        """
        Final delivery: clear anchoring WMEs, export audit, write final state.

        INV-010: Only delivers when tier1_gate=pass.

        Raises:
            RuntimeError: If tier1_gate != pass.
        """
        state = self._read_state()
        if state.tier1_gate != "pass":
            raise RuntimeError(
                f"INV-010: DELIVER blocked — tier1_gate={state.tier1_gate!r}. "
                "All unit tests must pass before delivery."
            )

        bridge = self.gate_runner._get_bridge()

        # Clear anchoring WMEs (transient lifetime)
        deliver_pipeline(bridge)

        # Export EPMEM audit record
        audit = bridge.export_audit_record()
        audit_file = self.state_file.parent / "codegen-epmem.json"
        try:
            audit_file.write_text(json.dumps(audit, indent=2))
            logger.info("[PipelineEngine] EPMEM exported to %s", audit_file)
        except OSError as exc:
            logger.warning("[PipelineEngine] Could not write EPMEM: %s", exc)

        # T-021: Back-fill MemPalace run_outcome for all drawers written this run
        self._backfill_mempalace_run_outcome(state.pipeline_id, outcome="passed")

        # Write final state
        state.current_phase = "DONE"
        state.updated_at = _iso_now()
        self._write_state(state)

        logger.info("[PipelineEngine] Delivery complete. Pipeline DONE.")
        self.gate_runner.close()

    def abort(self, reason: str) -> None:
        """
        Abort pipeline: clear anchoring WMEs, write abort state.

        Args:
            reason: Human-readable abort reason.
        """
        bridge = self.gate_runner._get_bridge()
        abort_pipeline(bridge)

        state = self._read_state()

        # T-021: Back-fill MemPalace run_outcome for failed/partial runs
        self._backfill_mempalace_run_outcome(state.pipeline_id, outcome="failed")

        state.current_phase = "ABORTED"
        state.updated_at = _iso_now()
        self._write_state(state)

        logger.warning("[PipelineEngine] Pipeline ABORTED: %s", reason)
        self.gate_runner.close()

    def get_state(self) -> PipelineState:
        """Read current state from file."""
        return self._read_state()

    # ------------------------------------------------------------------
    # T-021: MemPalace run_outcome back-fill
    # ------------------------------------------------------------------

    def _get_mempalace_writer(self, pipeline_id: str):
        """Lazily initialize MemPalaceWriter for this run."""
        if self._mempalace_writer is None:
            if self._ctx is None:
                raise RuntimeError(
                    "[PipelineEngine] set_context() must be called before writing to MemPalace. "
                    "Call engine.set_context(MemPalaceContext.from_project(...)) after initialize()."
                )
            try:
                from codegen.memory.mempalace_writer import MemPalaceWriter
            except ImportError:
                from src.codegen.memory.mempalace_writer import MemPalaceWriter  # type: ignore
            try:
                from codegen.memory.context import MemPalaceContext
            except ImportError:
                from src.codegen.memory.context import MemPalaceContext  # type: ignore
            ctx = MemPalaceContext(
                wing=self._ctx.wing,
                run_id=pipeline_id,
                palace_path=self._ctx.palace_path,
            )
            self._mempalace_writer = MemPalaceWriter(ctx)
        return self._mempalace_writer

    def _backfill_mempalace_run_outcome(self, pipeline_id: str, outcome: str) -> None:
        """
        T-021: Update run_outcome for all MemPalace drawers written this run.
        Non-fatal: logs warning on failure, does not block pipeline completion.
        """
        try:
            writer = self._get_mempalace_writer(pipeline_id)
            updated = writer.backfill_run_outcome(outcome)
            if updated > 0:
                logger.info(
                    "[PipelineEngine] MemPalace back-fill: %d drawers → run_outcome=%s",
                    updated, outcome,
                )
        except Exception as exc:
            logger.warning(
                "[PipelineEngine] MemPalace back-fill failed (non-fatal): %s", exc
            )

    # ------------------------------------------------------------------
    # Internal state I/O
    # ------------------------------------------------------------------

    def _read_state(self) -> PipelineState:
        """Read PipelineState from state file."""
        if not self.state_file.exists():
            raise FileNotFoundError(f"State file not found: {self.state_file}")
        try:
            raw = json.loads(self.state_file.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(f"Could not read state file {self.state_file}: {exc}") from exc

        return PipelineState(
            pipeline_id=raw.get("pipeline_id", str(uuid.uuid4())),
            mode=raw.get("mode", "greenfield"),
            target_path=raw.get("target_path"),
            intent=raw.get("intent", ""),
            current_phase=raw.get("current_phase", PHASES[0]),
            phases_completed=raw.get("phases_completed", []),
            retry_count=raw.get("retry_count", 0),
            max_retries=raw.get("max_retries", 3),
            psi_score=raw.get("psi", {}).get("score", 0.0) if isinstance(raw.get("psi"), dict) else raw.get("psi_score", 0.0),
            tier1_gate=raw.get("tier1_gate", "pending"),
            soar_model=raw.get("soar_model", "B"),
            soar_pid=raw.get("soar_pid"),
            violations_blocked=raw.get("cq_isc_violations_blocked", 0),
            impasse_count=raw.get("impasse_count", 0),
            wing=raw.get("wing", ""),
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
        )

    def _write_state(self, state: PipelineState) -> None:
        """Write PipelineState to state file."""
        raw = state.to_dict()
        # Normalize psi field to match codegen-state.json schema
        raw["psi"] = {"score": state.psi_score, "threshold": PSI_THRESHOLD}
        raw["cq_isc_violations_blocked"] = state.violations_blocked

        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(raw, indent=2))
        except OSError as exc:
            logger.warning("[PipelineEngine] Could not write state to %s: %s", self.state_file, exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
