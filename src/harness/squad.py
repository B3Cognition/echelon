"""SquadController — deterministic phase routing for the pre-code squad run."""
from __future__ import annotations

import json
import logging
import re
import signal
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from echelon.artifact_index import write_artifact_index
from echelon.context_builder import build_run_context
from harness.condition_evaluator import ConditionEvaluator
from harness.echelon_result_schema import (
    EchelonResultValidationError,
    validate_echelon_result,
)
from harness.phase_graph import PhaseGraph, PhaseNode
from harness.phase_a_readiness import PhaseAReadinessResult, validate_phase_a_readiness
from harness.quality_scores import normalize_why_quality_scores
from harness.spec_frontmatter import find_spec_dir
from harness.squad_executors import (
    AgentExecutor,
    CommanderInternalExecutor,
    ConditionalSequentialExecutor,
    HumanGateExecutor,
    PhaseExecutor,
    StagedParallelExecutor,
)
from harness.squad_provider import SquadAgentResult, SquadCliProvider
from harness.squad_state import SquadStateStore


PHASE_TERMINAL_BLOCKED = "terminal-blocked"
TERMINAL_PHASES = {"DONE", "done", PHASE_TERMINAL_BLOCKED}
WHY_PHASES = frozenset({"phase1-why1", "phase1-why2"})
ITERATIVE_PHASES = WHY_PHASES | frozenset(
    {
        "phase3-how",
        "phase3-sentinel",
        "phase3-plan",
        "phase3-consensus",
    }
)

# Max times the convergence guard may redirect to the same recommended phase before
# force-advancing. Protects against agents that re-assert convergence on every dispatch.
MAX_CONVERGENCE_GUARD_FIRES = 3

# Max dispatches of any single phase per run before forcing escalation.
# WHY phases are governed separately by why_fail_count; this cap applies to all others.
MAX_PHASE_DISPATCHES = 5
PROJECT_MODES = {"greenfield", "brownfield", "self_analysis"}
JUDGMENT_STATE_UPDATE_KEYS = frozenset(
    {
        "next_phase",
        "phase",
        "iteration",
        "status",
        "blocked_reason",
        "escalation_question",
        "escalation_options",
        "escalation_resolved",
        "escalation_resolver",
        "escalation_risk_level",
        "escalation_recommended_answer",
        "escalation_default_answer",
        "risk_level",
        "fallback_mode",
        "execution_mode",
        "dependency_fallbacks",
        "shadow_output_recovered",
    }
)

logger = logging.getLogger(__name__)


def _state_autonomy_mode(state: dict, fallback: str) -> str:
    autonomy = state.get("autonomy_mode")
    if isinstance(autonomy, str) and autonomy:
        return autonomy
    legacy = state.get("mode")
    if isinstance(legacy, str) and legacy in {"guided", "semi", "banzai"}:
        return legacy
    return fallback


def _normalize_phase_recommendation(recommended: object, valid_phases: set[str]) -> str | None:
    """Return a concrete phase id for semantic phase recommendations."""
    if not isinstance(recommended, str) or not recommended:
        return None
    if recommended in valid_phases:
        return recommended
    semantic_routes = {
        "advance_past_consensus_to_delivery": "checkpoint-plan",
        "advance_to_delivery": "checkpoint-plan",
    }
    mapped = semantic_routes.get(recommended)
    if mapped in valid_phases:
        return mapped
    return None


def _phase_requires_constitution_provenance(phase: str) -> bool:
    """Return True for phases that must run only after CHIEF has completed.

    The exempt set is not "pre-constitution" only: it also includes
    phase1-constitution itself, because CHIEF is the phase that creates the
    provenance this guard checks.
    """
    if phase in {
        "init",
        "phase1-discover",
        "phase1-synthesizer",
        "phase1-modeler",
        "phase1-tracker",
        "phase1-why1",
        "phase1-constitution",
        *TERMINAL_PHASES,
    }:
        return False
    return (
        phase.startswith("phase1-")
        or phase.startswith("phase2-")
        or phase.startswith("phase3-")
        or phase.startswith("phase4-")
        or phase.startswith("checkpoint-")
        or phase.startswith("build-")
    )


def _constitution_artifact_is_real(project_root: Path) -> bool:
    """Secondary integrity check for constitution completion provenance."""
    path = project_root / ".specify" / "memory" / "constitution.md"
    if not path.exists():
        return False
    text = path.read_text(errors="replace")
    template_markers = (
        "[PROJECT_NAME]",
        "[CONSTITUTION_VERSION]",
        "[RATIFICATION_DATE]",
        "[LAST_AMENDED_DATE]",
    )
    return not any(marker in text for marker in template_markers) and not re.search(
        r"\[PRINCIPLE_[0-9]+_NAME\]",
        text,
    )


def _blocked_banner(phase: str, reason: str, question: str) -> None:
    from echelon.ui import banner as _banner
    _banner(
        "SQUAD — BLOCKED",
        [
            ("phase", phase),
            ("reason", reason),
            ("question", question),
            ("answer with", "echelon resume \"<your answer>\""),
            ("discard with", "echelon run --reset \"<new task>\""),
        ],
    )


@dataclass
class SquadResult:
    status: str         # "done" | "blocked" | "interrupted" | "budget_exhausted"
    phase: str
    run_id: str
    summary: str = ""

    @classmethod
    def from_state(cls, state: dict) -> "SquadResult":
        return cls(
            status=state.get("status", "unknown"),
            phase=state.get("phase", "unknown"),
            run_id=state.get("run_id", ""),
        )

    @classmethod
    def interrupted(cls) -> "SquadResult":
        return cls(status="interrupted", phase="unknown", run_id="")


class SquadController:
    """Drives the squad run phase graph deterministically.

    Phase routing is pure Python (ConditionEvaluator + state.json).
    COMMANDER (LLM) is dispatched only for judgment calls.
    """

    def __init__(
        self,
        provider: SquadCliProvider,
        state_store: SquadStateStore,
        phase_graph: PhaseGraph,
        ext_dir: Path,
        project_root: Path,
        token_budget: int = 0,
        max_iterations: int = 5,
        squad_dir: Optional[Path] = None,
    ) -> None:
        self._provider = provider
        self._state_store = state_store
        self._graph = phase_graph
        self._ext_dir = ext_dir
        self._project_root = project_root
        self._token_budget = token_budget
        self._max_iterations = max_iterations
        self._squad_dir = squad_dir or state_store.squad_dir
        self._evaluator = ConditionEvaluator()
        self._gate_config_cache: Optional[dict] = None
        self._gov_config_cache: Optional[dict] = None
        self._executors: dict[str, PhaseExecutor] = {
            "agent": AgentExecutor(provider, phase_graph, ext_dir, project_root, self._squad_dir),
            "commander_internal": CommanderInternalExecutor(provider, phase_graph, ext_dir, project_root, self._squad_dir),
            "staged_parallel": StagedParallelExecutor(provider, phase_graph, ext_dir, project_root, self._squad_dir),
            "conditional_sequential": ConditionalSequentialExecutor(provider, phase_graph, ext_dir, project_root, self._squad_dir),
            "human_gate": HumanGateExecutor(provider, phase_graph, ext_dir, project_root, self._squad_dir),
        }
        self._cancelled = False
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _project_config_path(self) -> Path:
        canonical = self._project_root / ".echelon" / "config.yml"
        if canonical.exists():
            return canonical
        return self._ext_dir / "echelon-config.yml"

    def _quality_gate_thresholds(self) -> dict:
        try:
            import yaml

            data = yaml.safe_load(self._project_config_path().read_text()) or {}
            gates = data.get("quality_gates")
            return gates if isinstance(gates, dict) else {}
        except Exception:
            return {}

    def _normalize_why_result_quality_scores(
        self,
        result: SquadAgentResult,
    ) -> None:
        updates = result.state_updates
        if "quality_scores" not in updates:
            return
        updates["quality_scores"] = normalize_why_quality_scores(
            updates["quality_scores"],
            verdict=result.verdict,
            gates=self._quality_gate_thresholds(),
        )

    def _detect_project_mode(self, requested_mode: str) -> str:
        """Return the project type stored in state.mode.

        `requested_mode` is the user-selected autonomy mode (`semi`/`banzai`/`guided`)
        for normal CLI entrypoints, but older tests and internal callers may still
        pass a project mode directly. Preserve that when present.
        """
        if requested_mode in PROJECT_MODES:
            return requested_mode

        script = self._ext_dir / "scripts" / "bash" / "detect-project.sh"
        if not script.exists():
            return "greenfield"
        try:
            proc = subprocess.run(
                [str(script), str(self._project_root)],
                check=False,
                capture_output=True,
                text=True,
            )
            detected = (proc.stdout or "").strip()
            if proc.returncode == 0 and detected in PROJECT_MODES:
                return detected
        except Exception:
            pass
        return "greenfield"

    def _refresh_run_context(self, reason: str = "") -> None:
        state = self._state_store.load()
        run_dir = Path(state.get("squad_dir", self._squad_dir))
        user_request = str(state.get("user_request", state.get("user_message", "")))
        try:
            context_result = build_run_context(
                self._project_root,
                run_dir,
                user_request=user_request,
                drawers=self._retrieve_mempalace_context_drawers(
                    user_request,
                    str(state.get("run_id") or ""),
                ),
            )
        except Exception as exc:
            logger.warning(
                "run-local context refresh failed for %s%s: %s",
                run_dir,
                f" ({reason})" if reason else "",
                exc,
            )
            return

        state["context_dir"] = str(context_result.context_dir)
        self._state_store.save(state)

    def _retrieve_mempalace_context_drawers(
        self,
        user_request: str,
        run_id: str,
    ) -> list[object]:
        query = user_request.strip()
        if not query:
            return []
        try:
            from codegen.memory.context import MemPalaceContext
            from codegen.memory.mempalace_reader import MemPalaceReader
        except Exception:
            return []
        try:
            ctx = MemPalaceContext.from_project(self._project_root, run_id=run_id or "squad-context")
            reader = MemPalaceReader(ctx)
            return list(reader.search_requirements(query, n_results=10))
        except (Exception, SystemExit):
            return []

    def run(
        self,
        user_message: str = "",
        mode: str = "semi",
        next_phase_override: str = "",
    ) -> SquadResult:
        """Run the squad from current state or initialize fresh."""
        import os as _os
        _os.environ["ECHELON_SQUAD_ACTIVE"] = "1"

        existing = self._state_store.load()
        existing_status = existing.get("status") if existing else None
        blocked_reason = (existing.get("blocked_reason") or "") if existing else ""
        force_resume = False  # set True by recovery paths to bypass message check

        # ── Recovery: token budget bumped ─────────────────────────────────
        if existing_status == "blocked" and blocked_reason == "token_budget_exhausted":
            stored_usage = existing.get("token_usage", 0)
            if self._token_budget == 0 or self._token_budget > stored_usage:
                state = self._state_store.load()
                state["status"] = "running"
                state["blocked_reason"] = None
                state["token_budget"] = self._token_budget
                self._state_store.save(state)
                existing_status = "running"
                force_resume = True
                budget_display = f"{self._token_budget:,}" if self._token_budget else "∞"
                print(
                    f"[squad] budget bumped → resuming "
                    f"(usage={stored_usage:,}, new budget={budget_display})",
                    flush=True,
                )
            else:
                from echelon.ui import banner as _banner
                config_path = self._project_config_path()
                _banner(
                    "SQUAD — TOKEN BUDGET EXHAUSTED",
                    [
                        ("usage", f"{existing.get('token_usage', 0):,}"),
                        ("budget", f"{self._token_budget:,}"),
                        ("fix",
                         f"Edit {config_path}:\n"
                         f"  analysis:\n"
                         f"    token_budget_k: <increase this value>"),
                        ("then re-run", "echelon run"),
                        ("or discard", "echelon run --reset"),
                    ],
                )
                return SquadResult(
                    status="blocked",
                    phase=existing.get("phase", "unknown"),
                    run_id=existing.get("run_id", ""),
                )

        # ── Recovery: invalid judgment phase (--next-phase manual override) ─
        elif existing_status == "blocked" and "invalid next_phase" in blocked_reason:
            valid_phases = self._graph.all_phase_ids()
            from echelon.ui import banner as _banner
            if next_phase_override:
                if next_phase_override not in valid_phases:
                    _banner(
                        "SQUAD — INVALID PHASE ID",
                        [
                            ("given", next_phase_override),
                            ("valid phase IDs", "\n".join(f"  {p}" for p in valid_phases)),
                        ],
                    )
                    return SquadResult(
                        status="blocked",
                        phase=existing.get("phase", "unknown"),
                        run_id=existing.get("run_id", ""),
                    )
                state = self._state_store.load()
                state["status"] = "running"
                state["blocked_reason"] = None
                state["phase"] = next_phase_override
                self._state_store.save(state)
                existing_status = "running"
                force_resume = True
                print(
                    f"[squad] manual recovery → advancing to {next_phase_override!r}",
                    flush=True,
                )
            else:
                _banner(
                    "SQUAD — BLOCKED",
                    [
                        ("reason", blocked_reason),
                        ("recover", "echelon run --next-phase <phase-id>"),
                        ("valid phase IDs", "\n".join(f"  {p}" for p in valid_phases)),
                        ("discard", "echelon run --reset"),
                    ],
                )
                return SquadResult(
                    status="blocked",
                    phase=existing.get("phase", "unknown"),
                    run_id=existing.get("run_id", ""),
                )

        # ── Escalation block ──────────────────────────────────────────────
        elif existing_status == "blocked" and existing.get("escalation_question"):
            q = existing.get("escalation_question", "")
            mode_at_block = _state_autonomy_mode(existing, mode)

            if mode_at_block == "banzai":
                print(
                    f"\n[squad] escalation detected — banzai mode, "
                    f"dispatching COMMANDER judgment\n"
                    f"  Questions: {q[:120]}",
                    flush=True,
                )
                # Clear the block so run() proceeds after judgment
                s = self._state_store.load()
                s["status"] = "running"
                s["blocked_reason"] = None
                self._state_store.save(s)
                existing_status = "running"
                self._judgment_dispatch_escalation(
                    escalation_question=q,
                    blocked_phase=existing.get("phase", "unknown"),
                )
                force_resume = True
            else:
                # semi / guided: stop and require echelon resume
                _blocked_banner(
                    phase=existing.get("phase", "?"),
                    reason=existing.get("blocked_reason", ""),
                    question=q,
                )
                return SquadResult(
                    status="blocked",
                    phase=existing.get("phase", "unknown"),
                    run_id=existing.get("run_id", ""),
                )

        # ── Recovery: convergence already picked the next phase ─────────────
        elif (
            existing_status == "blocked"
            and not existing.get("escalation_question")
            and (existing.get("convergence_forced") or existing.get("convergence_detected"))
            and _normalize_phase_recommendation(
                existing.get("phase_recommendation"),
                self._graph.all_phase_ids(),
            )
        ):
            state = self._state_store.load()
            recommended = _normalize_phase_recommendation(
                state.get("phase_recommendation"),
                self._graph.all_phase_ids(),
            )
            state["status"] = "running"
            state["blocked_reason"] = None
            state["phase"] = recommended
            self._state_store.save(state)
            existing_status = "running"
            force_resume = True
            print(
                f"[squad] convergence recovery → advancing to {recommended!r}",
                flush=True,
            )

        # (keep all recovery blocks exactly as-is above this point)

        # Fresh start if no state or not resumable
        # The correct squad dir was already selected by _cmd_run before creating this controller.
        if not existing or existing_status not in ("running", "in_progress"):
            run_id = f"squad-{int(time.time())}"
            entry_phase = next_phase_override or self._graph.entry_phase()
            project_mode = self._detect_project_mode(mode)
            self._state_store.initialize(
                run_id=run_id,
                mode=project_mode,
                user_message=user_message,
                token_budget=self._token_budget,
                entry_phase=entry_phase,
                max_iterations=self._max_iterations,
                autonomy_mode=mode,
            )
            self._refresh_run_context("fresh initialization")
        else:
            print(f"[squad] resuming from phase: {self._state_store.current_phase()}", flush=True)
            state = self._state_store.load()
            if state.get("cancel_requested"):
                state["cancel_requested"] = False
                self._state_store.save(state)

        while True:
            phase = self._state_store.current_phase()
            guarded_phase = self._apply_phase_recommendation_guard(phase)
            if guarded_phase != phase:
                phase = guarded_phase
            guarded_phase = self._guard_constitution_provenance(phase)
            if guarded_phase != phase:
                phase = guarded_phase

            if phase in TERMINAL_PHASES:
                state = self._state_store.load()
                # Preserve "blocked" status set by guards (e.g. consecutive-fail).
                # Only write "done" when not already in a terminal-blocked state.
                if state.get("status") != "blocked":
                    state["status"] = "done"
                    self._state_store.save(state)
                return SquadResult.from_state(self._state_store.load())

            if self._cancelled:
                state = self._state_store.load()
                state["status"] = "interrupted"
                state["phase"] = phase
                state["interrupted_phase"] = phase
                state["blocked_reason"] = None
                self._state_store.save(state)
                return SquadResult.from_state(self._state_store.load())

            if self._budget_exhausted():
                self._state_store.set_blocked("token_budget_exhausted")
                return SquadResult(
                    status="budget_exhausted",
                    phase=phase,
                    run_id=self._state_store.load().get("run_id", ""),
                )

            node = self._graph.get(phase)
            label = node.label or node.id

            # Per-phase dispatch cap — prevents runaway loops on any phase.
            # WHY phases use max_iterations as their cap (they legitimately iterate).
            # All other phases use MAX_PHASE_DISPATCHES.
            dispatch_count = self._state_store.increment_phase_dispatch_count(phase)
            phase_limit = (
                self._max_iterations + 1
                if phase in ITERATIVE_PHASES
                else MAX_PHASE_DISPATCHES
            )
            if dispatch_count > phase_limit:
                escalation_q = (
                    f"Phase {phase!r} has been dispatched {dispatch_count} times "
                    f"(limit {phase_limit}) without converging or advancing. "
                    f"Possible routing loop. How should I proceed?"
                )
                s = self._state_store.load()
                s["escalation_question"] = escalation_q
                s["blocked_reason"] = "phase_dispatch_limit"
                s["status"] = "blocked"
                self._state_store.save(s)
                print(
                    f"[squad] ✗ phase dispatch limit: {phase!r} dispatched "
                    f"{dispatch_count}× (limit {phase_limit}) — forcing escalation",
                    flush=True,
                )
                s = self._state_store.load()
                s["phase"] = PHASE_TERMINAL_BLOCKED
                self._state_store.save(s)
                return SquadResult.from_state(self._state_store.load())

            print(f"\n[squad] ▶ {node.id}  {label}", flush=True)

            executor = self._executors.get(node.type)
            if executor is None:
                result = self._judgment_dispatch(
                    f"Unknown phase type {node.type!r} for phase {phase!r}",
                    node,
                )
            else:
                result = executor.execute(node, self._state_store)

            blocked_result = self._blocked_executor_reason(result)
            if blocked_result:
                self._block_after_executor_failure(phase, blocked_result, result)
                return SquadResult.from_state(self._state_store.load())

            next_phase = self._evaluate_transitions(node, result)
            if phase == "phase4-document" and next_phase in TERMINAL_PHASES:
                readiness = self._publish_phase_a_artifacts_for_build()
                if not readiness.ready:
                    self._block_after_phase_a_readiness_failure(readiness)
                    return SquadResult.from_state(self._state_store.load())

            self._state_store.advance(
                phase,
                next_phase,
                result,
                allowed_state_update_keys=node.allowed_state_updates,
            )
            self._refresh_run_context(f"phase advance {phase} -> {next_phase}")

            # Enforce iteration increment for transitions that declare action: increment_iteration.
            # The condition `iteration < max_iterations` in definition.yaml must work regardless
            # of whether the agent included `iteration` in its state_updates.
            # Only increment if the agent didn't already write it explicitly.
            if "iteration" not in (result.state_updates or {}):
                for t in node.transitions:
                    if t.get("to") == next_phase and t.get("action") == "increment_iteration":
                        s = self._state_store.load()
                        s["iteration"] = s.get("iteration", 0) + 1
                        self._state_store.save(s)
                        break

            # Inline escalation check — fires when _evaluate_transitions detected
            # escalation_question in state_updates and returned the current phase.
            # Handles it in the same run() invocation rather than requiring a
            # re-invocation to reach the top-of-loop escalation block.
            state_now = self._state_store.load()
            if state_now.get("status") == "blocked" and state_now.get("escalation_question") and not state_now.get("escalation_resolved"):
                q = state_now["escalation_question"]
                run_mode = _state_autonomy_mode(state_now, mode)
                if run_mode == "banzai":
                    print(
                        f"[squad] ~ {node.id}  escalation — banzai COMMANDER judgment",
                        flush=True,
                    )
                    # Clear blocked status before dispatch (mirrors top-of-loop handler)
                    s = self._state_store.load()
                    s["status"] = "running"
                    s["blocked_reason"] = None
                    self._state_store.save(s)
                    self._judgment_dispatch_escalation(q, phase)
                    if self._state_store.load().get("status") == "blocked":
                        return SquadResult.from_state(self._state_store.load())
                    # Unconditionally mark escalation resolved — do not rely on COMMANDER
                    # to include it in state_updates. If it forgets, the check at line 354
                    # re-fires on every iteration, which spins forever on WHY phases.
                    s = self._state_store.load()
                    s["escalation_resolved"] = True
                    self._state_store.save(s)
                    continue  # re-dispatch the same phase (e.g. phase1-why1) next iteration
                else:
                    _blocked_banner(
                        phase=phase,
                        reason=state_now.get("blocked_reason", ""),
                        question=q,
                    )
                    return SquadResult(
                        status="blocked",
                        phase=phase,
                        run_id=state_now.get("run_id", ""),
                    )
            else:
                print(f"[squad] ✓ {node.id}  → {next_phase}", flush=True)
                continue

    def run_single_phase(
        self,
        phase_id: str,
        user_message: str = "",
        mode: str = "semi",
        initial_state_updates: dict | None = None,
    ) -> SquadResult:
        """Execute one explicit workflow phase and stop after recording state.

        This is for targeted repair/replay. It uses the normal phase executor,
        transition evaluator, journal writer, and state validation path, but it
        never enters the full controller loop.
        """
        import os as _os

        _os.environ["ECHELON_SQUAD_ACTIVE"] = "1"

        if phase_id not in self._graph.all_phase_ids():
            raise KeyError(f"Phase not found in definition.yaml: {phase_id!r}")

        existing = self._state_store.load()
        if not existing:
            run_id = f"squad-{int(time.time())}"
            project_mode = self._detect_project_mode(mode)
            self._state_store.initialize(
                run_id=run_id,
                mode=project_mode,
                user_message=user_message or f"Manual phase run: {phase_id}",
                token_budget=self._token_budget,
                entry_phase=phase_id,
                max_iterations=self._max_iterations,
                autonomy_mode=mode,
            )
            if initial_state_updates:
                state = self._state_store.load()
                state.update(initial_state_updates)
                self._state_store.save(state)
            self._refresh_run_context("manual phase initialization")
        else:
            state = self._state_store.load()
            state["status"] = "running"
            state["phase"] = phase_id
            if user_message and not state.get("user_message"):
                state["user_message"] = user_message
            state["blocked_reason"] = None
            state["escalation_question"] = None
            state["escalation_options"] = None
            if initial_state_updates:
                state.update(initial_state_updates)
            self._state_store.save(state)
            self._refresh_run_context(f"manual phase replay {phase_id}")

        phase = phase_id
        guarded_phase = self._guard_constitution_provenance(phase)
        if guarded_phase in TERMINAL_PHASES:
            return SquadResult.from_state(self._state_store.load())
        phase = guarded_phase

        node = self._graph.get(phase)
        label = node.label or node.id
        print(f"\n[squad] ▶ {node.id}  {label}  (manual phase run)", flush=True)

        executor = self._executors.get(node.type)
        if executor is None:
            result = self._judgment_dispatch(
                f"Unknown phase type {node.type!r} for phase {phase!r}",
                node,
            )
        else:
            result = executor.execute(node, self._state_store)

        blocked_result = self._blocked_executor_reason(result)
        if blocked_result:
            self._block_after_executor_failure(phase, blocked_result, result)
            return SquadResult.from_state(self._state_store.load())

        next_phase = self._evaluate_transitions(node, result)
        if phase == "phase4-document" and next_phase in TERMINAL_PHASES:
            readiness = self._publish_phase_a_artifacts_for_build()
            if not readiness.ready:
                self._block_after_phase_a_readiness_failure(readiness)
                return SquadResult.from_state(self._state_store.load())
        else:
            self._publish_manual_phase_artifacts()

        self._state_store.advance(
            phase,
            next_phase,
            result,
            allowed_state_update_keys=node.allowed_state_updates,
            manual_phase_run=True,
        )
        self._refresh_run_context(f"manual phase advance {phase} -> {next_phase}")
        print(f"[squad] ✓ {node.id}  → {next_phase}  (stopped)", flush=True)
        return SquadResult.from_state(self._state_store.load())

    def _publish_manual_phase_artifacts(self) -> None:
        """Refresh project-visible spec metadata after a targeted phase run."""
        state = self._state_store.load()
        spec_ref = str(state.get("published_spec_dir") or state.get("spec_dir") or "").strip()
        if not spec_ref:
            return
        spec_dir = Path(spec_ref)
        if not spec_dir.is_absolute():
            spec_dir = self._project_root / spec_dir
        if not spec_dir.exists() or not spec_dir.is_dir():
            return
        self._publish_constitution_snapshot(spec_dir)
        try:
            write_artifact_index(spec_dir)
        except OSError:
            logger.warning("Could not refresh artifact index for %s", spec_dir)

    def _phase_a_readiness_candidate_dirs(self) -> list[Path]:
        state = self._state_store.load()
        candidates: list[Path] = []

        def add(candidate: Path | None) -> None:
            if candidate is None:
                return
            path = candidate if candidate.is_absolute() else self._project_root / candidate
            if path not in candidates:
                candidates.append(path)

        spec_id = str(state.get("spec_id") or "").strip()
        spec_dir_ref = str(state.get("spec_dir") or "").strip()
        published_ref = str(state.get("published_spec_dir") or "").strip()
        staging_ref = str(state.get("staging_dir") or "").strip()

        if spec_dir_ref:
            add(Path(spec_dir_ref))
        if published_ref:
            add(Path(published_ref))
        if spec_id:
            add(self._project_root / "specs" / spec_id)
            add(self._squad_dir / "specs" / spec_id)
        if staging_ref:
            add(Path(staging_ref))
        else:
            add(self._squad_dir / "staging")

        return candidates

    def _publish_phase_a_artifacts_for_build(self) -> PhaseAReadinessResult:
        state = self._state_store.load()
        active_spec_dir = self._active_phase_a_spec_dir(state)
        if active_spec_dir is None or not active_spec_dir.exists():
            return validate_phase_a_readiness(
                state,
                self._phase_a_readiness_candidate_dirs(),
            )

        published_spec_dir = self._published_phase_a_spec_dir(state, active_spec_dir)
        try:
            if active_spec_dir.resolve() != published_spec_dir.resolve():
                self._copy_spec_tree(active_spec_dir, published_spec_dir)
            else:
                published_spec_dir.mkdir(parents=True, exist_ok=True)
            self._publish_constitution_snapshot(published_spec_dir)
            write_artifact_index(published_spec_dir)
            self._refresh_published_context_metadata(
                published_spec_dir,
                str(state.get("run_id") or "").strip(),
            )
        except OSError as exc:
            return PhaseAReadinessResult(
                ready=False,
                blockers=[f"failed to publish Phase A artifacts: {exc}"],
                missing={},
                ready_spec_dir=None,
            )

        updated = self._state_store.load()
        updated["published_spec_dir"] = self._repo_relative_or_absolute(published_spec_dir)
        self._state_store.save(updated)
        return validate_phase_a_readiness(updated, [published_spec_dir])

    def _publish_constitution_snapshot(self, published_spec_dir: Path) -> None:
        """Copy the project constitution into the published spec build inputs."""
        source = self._project_root / ".specify" / "memory" / "constitution.md"
        target = published_spec_dir / "constitution.md"
        if source.exists():
            target.write_text(
                source.read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8",
            )

    def _refresh_published_context_metadata(
        self,
        published_spec_dir: Path,
        run_id: str,
    ) -> None:
        spec_file = published_spec_dir / "spec.md"
        if not spec_file.exists():
            return

        from echelon.context_metadata import FeatureMetadata, write_feature_metadata

        metadata = FeatureMetadata.from_spec_dir(
            published_spec_dir,
            run_id=run_id or None,
        )
        write_feature_metadata(published_spec_dir, metadata)
        self._mine_published_spec_best_effort(
            published_spec_dir,
            spec_file,
            run_id,
            metadata,
        )

    def _mine_published_spec_best_effort(
        self,
        published_spec_dir: Path,
        spec_file: Path,
        run_id: str,
        metadata: object,
    ) -> None:
        try:
            from codegen.memory.context import MemPalaceContext
            from codegen.memory.requirements_miner import RequirementsMiner
            from echelon.context_metadata import artifact_hash
        except Exception:
            return

        artifact_metadata = self._canonical_spec_artifact_metadata(
            spec_file,
            metadata,
            artifact_hash(spec_file),
        )

        try:
            ctx = MemPalaceContext.from_project(self._project_root, run_id=run_id)
            miner = RequirementsMiner(ctx, project_dir=self._project_root)
            miner.mine_file(spec_file, artifact_metadata=artifact_metadata)
        except (Exception, SystemExit):
            return

    def _canonical_spec_artifact_metadata(
        self,
        spec_file: Path,
        metadata: object,
        spec_hash: str,
    ) -> dict[str, object]:
        try:
            artifact_path = spec_file.relative_to(self._project_root).as_posix()
        except ValueError:
            artifact_path = spec_file.as_posix()

        payload: dict[str, object] = {
            "scope": "canonical",
            "canonical": True,
            "artifact_path": artifact_path,
            "artifact_hash": spec_hash,
            "lifecycle_status": getattr(metadata, "status", "active"),
            "spec_id": getattr(metadata, "spec_id", ""),
            "feature_id": getattr(metadata, "feature_id", ""),
        }
        for reserved_key in {
            "run_id",
            "phase",
            "run_outcome",
            "provenance_type",
            "embedding_model",
            "status",
            "source_file",
        }:
            payload.pop(reserved_key, None)
        return payload

    def _active_phase_a_spec_dir(self, state: dict) -> Path | None:
        spec_ref = str(state.get("spec_dir") or "").strip()
        if spec_ref:
            candidate = Path(spec_ref)
            if not candidate.is_absolute():
                candidate = self._project_root / candidate
            return candidate

        spec_id = str(state.get("spec_id") or "").strip()
        if spec_id:
            run_local = self._squad_dir / "specs" / spec_id
            if run_local.exists():
                return run_local
        return None

    def _published_phase_a_spec_dir(self, state: dict, active_spec_dir: Path) -> Path:
        published_ref = str(state.get("published_spec_dir") or "").strip()
        if published_ref:
            candidate = Path(published_ref)
            return candidate if candidate.is_absolute() else self._project_root / candidate

        spec_id = str(state.get("spec_id") or "").strip()
        if spec_id:
            existing = find_spec_dir(spec_id, self._project_root)
            if existing is not None:
                return existing
            if re.match(r"^[0-9]{3}-", spec_id):
                return self._project_root / "specs" / spec_id
            active_name = active_spec_dir.name
            if active_name.startswith(f"{spec_id}-"):
                return self._project_root / "specs" / active_name
            slug = self._spec_title_slug(active_spec_dir)
            if slug:
                return self._project_root / "specs" / f"{spec_id}-{slug}"
            return self._project_root / "specs" / spec_id

        return self._project_root / "specs" / active_spec_dir.name

    def _spec_title_slug(self, spec_dir: Path) -> str:
        spec_file = spec_dir / "spec.md"
        if not spec_file.exists():
            return ""
        for line in spec_file.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*#\s+(.+?)\s*$", line)
            if not match:
                continue
            title = match.group(1).strip().lower()
            slug = re.sub(r"[^a-z0-9]+", "-", title).strip("-")
            return slug
        return ""

    def _copy_spec_tree(self, source: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            target = destination / child.name
            if child.is_dir():
                if target.exists() and not target.is_dir():
                    target.unlink()
                shutil.copytree(child, target, dirs_exist_ok=True)
            elif child.is_file():
                if target.exists() and target.is_dir():
                    shutil.rmtree(target)
                shutil.copy2(child, target)

    def _repo_relative_or_absolute(self, path: Path) -> str:
        try:
            return str(path.relative_to(self._project_root))
        except ValueError:
            return str(path)

    def _block_after_phase_a_readiness_failure(
        self, readiness: PhaseAReadinessResult
    ) -> None:
        state = self._state_store.load()
        state["phase"] = PHASE_TERMINAL_BLOCKED
        state["status"] = "blocked"
        state["blocked_reason"] = "phase_a_readiness_failed"
        state["phase_a_readiness_blockers"] = readiness.blockers
        self._state_store.save(state)
        print(
            "[squad] ✗ phase4-document blocked: Phase A readiness failed "
            "(build-input artifacts incomplete)",
            flush=True,
        )

    def _blocked_executor_reason(
        self, result: SquadAgentResult
    ) -> str | None:
        if result.echelon_result is None:
            return "missing_echelon_result"
        if result.timed_out:
            return "agent_timeout"
        if result.exit_code != 0:
            return f"agent_exit_code_{result.exit_code}"
        if (result.verdict or "").upper() == "BLOCKED":
            explicit_reason = (result.state_updates or {}).get("blocked_reason")
            if isinstance(explicit_reason, str) and explicit_reason.strip():
                return explicit_reason.strip()
            return "agent_blocked"
        return None

    def _block_after_executor_failure(
        self, phase: str, reason: str, result: SquadAgentResult
    ) -> None:
        from datetime import datetime, timezone

        state = self._state_store.load()
        state["phase"] = PHASE_TERMINAL_BLOCKED
        state["status"] = "blocked"
        state["blocked_reason"] = reason
        state["last_dispatch"] = {
            "phase_id": phase,
            "verdict": result.verdict,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._state_store.save(state)
        print(
            f"[squad] ✗ {phase} blocked: {reason} "
            "(phase not marked complete)",
            flush=True,
        )

    def _block_after_judgment_validation_failure(
        self,
        phase: str,
        reason: str,
    ) -> None:
        state = self._state_store.load()
        state["phase"] = PHASE_TERMINAL_BLOCKED
        state["status"] = "blocked"
        state["blocked_reason"] = (
            f"judgment state_updates validation failed: {reason}"
        )
        self._state_store.save(state)
        print(
            f"[squad] ✗ {phase} blocked: judgment state_updates validation failed: {reason}",
            flush=True,
        )

    def _ensure_judgment_state_updates_allowed(
        self,
        result: SquadAgentResult,
        phase: str,
    ) -> bool:
        try:
            result.echelon_result = validate_echelon_result(
                result.echelon_result,
                allowed_state_update_keys=JUDGMENT_STATE_UPDATE_KEYS,
            )
            return True
        except EchelonResultValidationError as exc:
            self._block_after_judgment_validation_failure(phase, str(exc))
            return False

    def _apply_judgment_state_updates(
        self,
        result: SquadAgentResult,
        phase: str,
        *,
        exclude_keys: set[str] | None = None,
        delete_null: bool = False,
    ) -> bool:
        if not self._ensure_judgment_state_updates_allowed(result, phase):
            return False

        excluded = exclude_keys or set()
        updates = {
            key: value
            for key, value in result.state_updates.items()
            if key not in excluded
        }
        if not updates:
            return True

        state = self._state_store.load()
        for key, value in updates.items():
            if delete_null and value is None:
                state.pop(key, None)
            else:
                state[key] = value
        self._state_store.save(state)
        return True

    def _guard_constitution_provenance(self, phase: str) -> str:
        """Route normal spec/build phases through CHIEF until constitution is proven.

        The state machine owns the primary decision: phase1-constitution must have
        completed before phase1-what or later phases run. The filesystem check is
        a secondary integrity check so stale or template artifacts cannot satisfy
        the provenance gate by accident.
        """
        if not _phase_requires_constitution_provenance(phase):
            return phase

        state = self._state_store.load()
        completed = state.get("completed_phases")
        completed_phases = completed if isinstance(completed, list) else []
        has_provenance = "phase1-constitution" in completed_phases
        if has_provenance:
            if _constitution_artifact_is_real(self._project_root):
                return phase
            state["phase"] = PHASE_TERMINAL_BLOCKED
            state["status"] = "blocked"
            state["blocked_reason"] = "constitution_artifact_mismatch"
            state["constitution_guard_reason"] = (
                "phase1-constitution completed, but constitution artifact is "
                "missing or still template"
            )
            self._state_store.save(state)
            print(
                "[squad] constitution guard → blocked "
                "(phase1-constitution completed but artifact is invalid)",
                flush=True,
            )
            return PHASE_TERMINAL_BLOCKED

        reason = "missing phase1-constitution completion provenance"
        state["phase"] = "phase1-constitution"
        state["constitution_guard_reason"] = reason
        self._state_store.save(state)
        print(
            f"[squad] constitution guard → phase1-constitution ({reason})",
            flush=True,
        )
        return "phase1-constitution"

    def _apply_phase_recommendation_guard(self, phase: str) -> str:
        """Honor forced-convergence routing before dispatching another agent.

        The guard fires exactly once per convergence event: it redirects to the
        recommended phase, then clears itself when we arrive there.  Without the
        clear, every subsequent transition from the recommended phase would be
        overridden back to it, creating an infinite loop.
        """
        if phase in TERMINAL_PHASES:
            return phase

        state = self._state_store.load()
        if not (state.get("convergence_forced") or state.get("convergence_detected")):
            return phase

        raw_recommended = state.get("phase_recommendation")
        recommended = _normalize_phase_recommendation(
            raw_recommended,
            self._graph.all_phase_ids(),
        )
        if not recommended or recommended == phase:
            # We've arrived at the recommended phase (or there's no recommendation).
            # Clear the flags so they don't override the next forward transition.
            state["convergence_forced"] = False
            state["convergence_detected"] = False
            state["phase_recommendation"] = None
            state["convergence_guard_fire_count"] = 0
            self._state_store.save(state)
            return phase
        fire_count = self._state_store.increment_convergence_guard_fires()
        if fire_count > MAX_CONVERGENCE_GUARD_FIRES:
            # Agent keeps re-asserting convergence on every dispatch — infinite loop.
            # Force-advance by clearing the recommendation.
            state = self._state_store.load()
            state["convergence_forced"] = False
            state["convergence_detected"] = False
            state["phase_recommendation"] = None
            state["convergence_guard_fire_count"] = 0
            self._state_store.save(state)
            print(
                f"[squad] convergence guard → force-advancing from {phase!r} "
                f"(guard fired {fire_count}× on {recommended!r} — agent re-assertion loop)",
                flush=True,
            )
            return phase

        state = self._state_store.load()
        state["phase"] = recommended
        if state.get("status") == "blocked" and not state.get("escalation_question"):
            state["status"] = "running"
            state["blocked_reason"] = None
        self._state_store.save(state)
        print(
            f"[squad] convergence guard → honoring phase_recommendation "
            f"{recommended!r} (skipping {phase!r}) [{fire_count}/{MAX_CONVERGENCE_GUARD_FIRES}]",
            flush=True,
        )
        return recommended

    def _lexicon_gate_config(self) -> dict:
        """Load the `lexicon_gate` config block once for transition evaluation.

        Self-loop guard conditions (phase1-what, phase3-plan) reference the
        config-namespace key `lexicon_gate.enabled`, which does not live in
        state.json. Merging this block into the eval state lets those guards
        resolve deterministically instead of returning None and punting the
        re-dispatch decision to COMMANDER. Only `lexicon_gate` is merged (not
        the whole config) to keep the blast radius to the gate transitions.
        Returns {} when the file is absent or unparseable.
        """
        if self._gate_config_cache is not None:
            return self._gate_config_cache
        cfg: dict = {}
        try:
            import yaml
            data = yaml.safe_load(self._project_config_path().read_text()) or {}
            block = data.get("lexicon_gate")
            if isinstance(block, dict):
                cfg = {"lexicon_gate": block}
        except Exception:
            cfg = {}
        self._gate_config_cache = cfg
        return cfg

    def _governance_config(self) -> dict:
        """Load the `governance` block so governance.* resolves in transition conditions.

        Mirrors _lexicon_gate_config: merges the governance block into eval_state
        so conditions like `governance.enabled` evaluate deterministically instead
        of returning None and punting the routing decision to COMMANDER.
        Returns {} when the file is absent or unparseable.

        Also injects default `True` for the structural-gate pass flags
        (feasibility_structural_pass, intent_alignment_check_structural_pass).
        This is FAIL-OPEN by design — deliberate trade-off recorded here:

        (a) Fail-open is consistent with `governance.on_exhausted: warn`: when
            the gate exhausts its repair iterations the run proceeds with a
            warning rather than blocking.  Defaulting absent flags to True
            extends that same "warn and continue" philosophy to the case where
            the agent simply did not emit the flag at all.

        (b) The alternative — absent flag → COMMANDER judgment dispatch — would
            make phase2-decide and phase2-tracker-alignment non-deterministic.
            The lexicon gate (phase1-what, phase3-plan) lives with that
            indeterminacy because CARTOGRAPHER/ORCHESTRATOR always emit
            lexicon_pass; for the structural gates the flag is conditional on
            the repair loop running, so a missing flag is the common case (gate
            disabled or agent pre-empted).  Defaulting to True avoids that
            COMMANDER punt entirely.

        (c) A real gate failure (agent emits flag=False) is still honoured: the
            re-dispatch condition `governance.enabled AND NOT <flag>` evaluates
            to True, triggering a re-dispatch.  result.state_updates merges at
            higher precedence than these defaults in eval_state (see
            _evaluate_transitions), so an explicit False always wins.
        """
        if self._gov_config_cache is not None:
            return self._gov_config_cache
        cfg: dict = {}
        try:
            import yaml
            data = yaml.safe_load(self._project_config_path().read_text()) or {}
            block = data.get("governance")
            if isinstance(block, dict):
                cfg = {"governance": block}
        except Exception:
            cfg = {}
        # Structural gate pass flags default to True (= "not triggered" / "already
        # passed"). GATEKEEPER and TRACKER override via state_updates when the gate
        # is active. Without these defaults, absent flags produce NOT None = None,
        # which triggers an unwanted COMMANDER judgment dispatch.
        cfg.setdefault("feasibility_structural_pass", True)
        cfg.setdefault("intent_alignment_check_structural_pass", True)
        self._gov_config_cache = cfg
        return cfg

    def _evaluate_transitions(
        self, node: PhaseNode, result: SquadAgentResult
    ) -> str:
        state = self._state_store.load()
        if node.id in WHY_PHASES:
            self._normalize_why_result_quality_scores(result)
        # Merge order (lowest→highest precedence): lexicon_gate config, governance
        # config, then state, then result.state_updates — so freshly-written values
        # (quality_scores, tasks_lexicon_pass, etc.) win, while config-namespace
        # keys (lexicon_gate.*, governance.*) the self-loop guards reference resolve.
        eval_state = {**self._lexicon_gate_config(), **self._governance_config(), **state, **(result.state_updates or {})}

        # ── WHY fail tracking + consecutive-fail safety net ──────────────────
        if node.id in WHY_PHASES:
            # Early escalation detection: agent explicitly signalled user-gated
            # CRITICAL issues via escalation_question in state_updates.  Handle
            # here before condition evaluation so empty quality_scores don't cause
            # COMMANDER to be dispatched as a routing judge instead.
            escalation_q = (result.state_updates or {}).get("escalation_question")
            if escalation_q:
                s = self._state_store.load()
                s["escalation_question"] = escalation_q
                s["blocked_reason"] = (result.state_updates or {}).get(
                    "blocked_reason", "WHY phase: agent escalation"
                )
                s["status"] = "blocked"
                self._state_store.save(s)
                return node.id  # stay at current phase; inline loop check handles escalation

            # WHY phases return verdict: FAIL without quality_scores by design
            # (COMMANDER NEVER rule #8).  Inject a synthetic score derived from
            # result.verdict so quality_gates conditions evaluate correctly,
            # preventing COMMANDER from being dispatched as a routing judge.
            if not eval_state.get("quality_scores"):
                verdict_upper = (result.verdict or "").upper()
                if verdict_upper in ("FAIL", "BLOCKED"):
                    eval_state["quality_scores"] = [{"pass": False}]
                elif verdict_upper in ("DONE", "COMPLETE", "PASS"):
                    eval_state["quality_scores"] = [{"pass": True}]

            is_fail = self._evaluator.evaluate("quality_gates.fail", eval_state, result) is True
            if is_fail:
                fail_count = self._state_store.increment_why_fail_count()
                if fail_count >= 2 and not state.get("escalation_question"):
                    last_ts = (state.get("last_dispatch") or {}).get("completed_at")
                    if not self._staging_changed_since(last_ts):
                        print(
                            f"[squad] ✗ consecutive-fail guard: {fail_count} {node.id} FAILs "
                            f"with no staging progress — forcing escalation",
                            flush=True,
                        )
                        s = self._state_store.load()
                        s["escalation_question"] = (
                            f"Auto-detected: {fail_count} consecutive {node.id} FAILs "
                            f"with no staging progress. User input or banzai COMMANDER "
                            f"judgment required before continuing."
                        )
                        s["blocked_reason"] = "consecutive_why_fails"
                        s["status"] = "blocked"
                        self._state_store.save(s)
                        return PHASE_TERMINAL_BLOCKED
            else:
                self._state_store.reset_why_fail_count()
        # ── end WHY tracking ─────────────────────────────────────────────────

        for transition in node.transitions:
            condition = transition.get("condition", "always")
            evaluation = self._evaluator.evaluate(condition, eval_state, result)
            if evaluation is True:
                return transition["to"]
            if evaluation is None:
                judgment = self._judgment_dispatch(
                    f"Cannot evaluate condition {condition!r} in phase {node.id!r}",
                    node,
                    result,
                )
                if not self._ensure_judgment_state_updates_allowed(judgment, node.id):
                    return PHASE_TERMINAL_BLOCKED
                # Accept either "next_phase" or "phase" as the routing key.
                next_phase = (
                    judgment.state_updates.get("next_phase")
                    or judgment.state_updates.get("phase")
                )
                # Hard-validate: next_phase must exist in the phase graph.
                # Reject hallucinated phase names rather than silently routing
                # to a non-existent phase or falling through to DONE.
                valid_phases = self._graph.all_phase_ids()
                if next_phase and next_phase not in valid_phases:
                    print(
                        f"[squad] ✗ judgment returned invalid phase {next_phase!r} "
                        f"— not in phase graph. Blocking.",
                        flush=True,
                    )
                    self._state_store.set_blocked(
                        f"judgment returned invalid next_phase {next_phase!r}"
                    )
                    return PHASE_TERMINAL_BLOCKED
                # Apply judgment state_updates (e.g. iteration increment) now —
                # advance() only applies the executor result's state_updates.
                routing_keys = {"next_phase", "phase"}
                extra = {
                    k: v for k, v in judgment.state_updates.items()
                    if k not in routing_keys
                }
                if extra:
                    if not self._apply_judgment_state_updates(
                        judgment,
                        node.id,
                        exclude_keys=routing_keys,
                    ):
                        return PHASE_TERMINAL_BLOCKED
                # If this judgment blocked the run (e.g. COMMANDER set
                # status=blocked after reading SAGE artifacts), stop evaluating
                # further transitions — continuing would let a second COMMANDER
                # override the blocked state with a forward route.
                if self._state_store.load().get("status") == "blocked":
                    return node.id
                if next_phase:
                    return next_phase
        return "DONE"

    def _judgment_dispatch(
        self,
        reason: str,
        node: PhaseNode,
        result: Optional[SquadAgentResult] = None,
    ) -> SquadAgentResult:
        """Dispatch slimmed COMMANDER for judgment calls."""
        commander_path = self._ext_dir / "agents/control/commander.md"
        state = self._state_store.load()
        valid_phases = self._graph.all_phase_ids()
        transitions_text = "\n".join(
            f"  - to: {t.get('to')}  (condition: {t.get('condition', 'always')})"
            for t in node.transitions
        ) or "  (none defined)"
        context = (
            f"# COMMANDER JUDGMENT REQUEST\n\n"
            f"**Reason:** {reason}\n\n"
            f"**Current phase:** {node.id} (type: {node.type})\n\n"
            f"**Transitions defined for this phase:**\n{transitions_text}\n\n"
            f"**VALID phase IDs** (only these may appear in next_phase):\n"
            f"{json.dumps(valid_phases, indent=2)}\n\n"
            f"**State:**\n```json\n{json.dumps(state, indent=2)}\n```\n\n"
        )
        if commander_path.exists():
            context = commander_path.read_text() + "\n\n" + context
        judgment = self._provider.exec_agent(str(self._project_root), context)
        # COMMANDER writes most journal entries directly via journal-append.sh
        # during LLM execution.  This catches any entries it returns in
        # echelon_result.journal_entries[] that it didn't write itself.
        self._write_journal_entries(judgment, node.id)
        return judgment

    def _judgment_dispatch_escalation(
        self,
        escalation_question: str,
        blocked_phase: str,
    ) -> SquadAgentResult:
        """Dispatch COMMANDER to resolve a user-gated escalation in banzai mode.

        COMMANDER produces staging/user-clarifications.md with BANZAI-AUTO-RESOLVED
        answers and returns state_updates that clear the block.
        """
        commander_path = self._ext_dir / "agents/control/commander.md"
        state = self._state_store.load()

        staging_dir = Path(state.get("staging_dir", str(self._squad_dir / "staging")))
        staging_context = ""
        for f in sorted(staging_dir.glob("*.md"))[:8]:
            try:
                staging_context += f"\n---\n# {f.name}\n{f.read_text()[:3000]}\n"
            except Exception:
                pass

        context = (
            f"# COMMANDER BANZAI ESCALATION JUDGMENT\n\n"
            f"**Mode:** banzai — produce best-judgment answers and continue. "
            f"Do NOT stop the run.\n\n"
            f"**Phase blocked:** {blocked_phase}\n\n"
            f"**Blocking questions:**\n{escalation_question}\n\n"
            f"**Your task:**\n"
            f"1. For each blocking question, produce a best-judgment answer.\n"
            f"2. Write `{staging_dir}/user-clarifications.md` using the "
            f"BANZAI-AUTO-RESOLVED format from commander.md §Banzai Escalation.\n"
            f"3. Return echelon_result state_updates that clear the block:\n"
            f"   escalation_question: null\n"
            f"   escalation_resolved: true\n"
            f"   escalation_resolver: COMMANDER-banzai\n"
            f"   blocked_reason: null\n\n"
            f"**Staging context:**\n{staging_context}"
        )
        if commander_path.exists():
            context = commander_path.read_text() + "\n\n" + context
        else:
            print(
                f"[squad] warning: commander.md not found at {commander_path} — "
                f"dispatching COMMANDER without preamble",
                flush=True,
            )

        result = self._provider.exec_agent(str(self._project_root), context)
        if not self._apply_judgment_state_updates(
            result,
            blocked_phase,
            delete_null=True,
        ):
            return result
        self._write_journal_entries(result, blocked_phase)

        return result

    def _write_journal_entries(self, result: SquadAgentResult, phase_id: str) -> None:
        """Mirror of PhaseExecutor._write_journal_entries for SquadController use."""
        import json as _json
        from datetime import datetime, timezone
        from harness.journal_entry_validator import prepare_journal_entries_for_append

        entries = (result.echelon_result or {}).get("journal_entries", [])
        if not entries:
            return

        journal_path = self._squad_dir / "reasoning-journal.jsonl"
        journal_path.parent.mkdir(parents=True, exist_ok=True)

        next_id = 1
        if journal_path.exists():
            lines = [ln for ln in journal_path.read_text().splitlines() if ln.strip()]
            next_id = len(lines) + 1

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        prepared_entries = prepare_journal_entries_for_append(
            entries,
            phase_id=phase_id,
            next_id=next_id,
            timestamp=ts,
            schema_path=self._ext_dir / "workflow/journal-entry-types.yaml",
            invalid_registered_policy="quarantine",
        )
        with journal_path.open("a") as fh:
            for entry in prepared_entries:
                fh.write(_json.dumps(entry) + "\n")

    def _staging_changed_since(self, iso_timestamp: Optional[str]) -> bool:
        """Return True if any staging .md file is newer than iso_timestamp.

        Returns True (progress detected) when timestamp is None or when
        any .md in staging_dir has mtime newer than the given UTC timestamp.
        """
        if iso_timestamp is None:
            return True
        try:
            from datetime import datetime, timezone
            cutoff = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            state = self._state_store.load()
            staging_dir = Path(state.get("staging_dir", str(self._squad_dir / "staging")))
            for f in staging_dir.glob("*.md"):
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime > cutoff:
                    return True
            return False
        except Exception:
            return True  # conservative: treat parse failure as progress

    def _budget_exhausted(self) -> bool:
        if self._token_budget <= 0:
            return False
        return self._state_store.token_usage() >= self._token_budget

    def _handle_sigint(self, signum, frame) -> None:
        print("\n[squad] Interrupted — finishing current phase then stopping.")
        self._cancelled = True
        self._state_store.set_cancel_requested()
