"""SquadController — deterministic phase routing for the pre-code squad run."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import signal
import shutil
import stat
import subprocess
import sys
import time
import threading
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Optional

from echelon.artifact_index import write_artifact_index
from echelon.context_builder import build_run_context
from echelon.kb_proposals import accepted_kb_target_paths
from echelon.spec_lifecycle import (
    PhaseAExecutionLock,
    SpecLifecycleLocked,
    SpecRunExecutionLock,
)
from harness.condition_evaluator import ConditionEvaluator
from harness.controller_state_contracts import ControllerStateContractViolation
from harness.echelon_result_schema import (
    EchelonResultContract,
    EchelonResultValidationError,
    validate_echelon_result,
    validate_echelon_result_contract,
)
from harness.phase_graph import PhaseGraph, PhaseNode
from harness.phase_a_readiness import (
    PhaseAReadinessResult,
    unresolved_constitution_template_markers,
    validate_phase_a_readiness,
)
from harness.phase_checkpoints import create_phase_checkpoint
from harness.prepared_phase_result import (
    PreparedPhaseResult,
    PreparedRoutingDecision,
    _canonical_payload_sha256,
    detach_squad_agent_result,
    prepare_phase_result,
)
from harness.quality_scores import (
    normalize_why_quality_scores,
    resolve_quality_gate_thresholds,
)
from harness.published_re_context import attach_published_re_context
from harness.run_history import append_phase_a_run
from harness.spec_frontmatter import find_spec_dir, write_targets
from harness.spec_lexicon_gate import has_current_spec_lexicon_evidence
from harness.squad_executors import (
    AgentExecutor,
    CommanderInternalExecutor,
    ConditionalSequentialExecutor,
    DeterministicLexiconExecutor,
    DeterministicUnderstandingExecutor,
    HumanGateExecutor,
    PhaseExecutor,
    StagedParallelExecutor,
)
from harness.squad_provider import SquadAgentResult, SquadCliProvider
from harness.squad_completion import (
    CompletionError,
    PreparedControllerCompletion,
    apply_or_verify_completion_journal,
    apply_or_verify_completion_mining,
    apply_or_verify_completion_timing,
    create_or_recover_completion_checkpoint,
    discard_unreferenced_controller_completion,
    install_or_verify_completion_context,
    load_prepared_controller_completion,
    persist_completion_effect_receipt,
    prepare_completion_journal_plan,
    prepare_controller_completion as prepare_controller_completion_stage,
    prepare_or_load_completion_context,
)
from harness.controller_lock_order import controller_lock_order
from harness.squad_publication import (
    PreparedSquadPublication,
    PublicationError,
    SquadPublicationTransaction,
    load_prepared_publication,
)
from echelon.telemetry.phase_timing import record_phase_finish, record_phase_start
from echelon.telemetry.provider import DispatchContext, InstrumentedProvider
from echelon.telemetry.store import TelemetryStore
from harness.squad_state import (
    AdvanceReceipt,
    RoutingStateSnapshot,
    StateAdvanceError,
    StateDurabilityError,
    SquadStateStore,
)
from harness.state_transaction_namespace import (
    PENDING_CONTROLLER_COMPLETION_KEY,
    PENDING_EXTERNAL_PUBLICATION_KEY,
    STORE_OWNED_TRANSACTION_KEYS,
    TRUSTED_ROUTING_EFFECT_KEYS,
    validate_pending_controller_completion,
    validate_pending_external_publication,
)
from harness.prompt_markdown import read_prompt_markdown
from harness.terminal import color_text
from harness.understanding_gate import has_current_understanding_evidence


PHASE_TERMINAL_BLOCKED = "terminal-blocked"
TERMINAL_PHASES = {"DONE", "done", PHASE_TERMINAL_BLOCKED}
WHY_PHASES = frozenset({"phase1-why1", "phase1-why2"})
ITERATIVE_PHASES = WHY_PHASES | frozenset(
    {
        "phase1-what",
        "phase1-lexicon",
        "phase3-how",
        "phase3-sentinel",
        "phase3-plan",
        "phase3-tasks-lexicon",
        "phase3-consensus",
        "phase3-consensus-tasks-lexicon",
    }
)

# Max times the convergence guard may redirect to the same recommended phase before
# force-advancing. Protects against agents that re-assert convergence on every dispatch.
MAX_CONVERGENCE_GUARD_FIRES = 3

# Max dispatches of any single phase per run before forcing escalation.
# WHY phases are governed separately by why_fail_count; this cap applies to all others.
MAX_PHASE_DISPATCHES = 5
# A planning agent gets the original pass plus two controller-directed repairs
# to resolve its own product-input mapping omissions.  This is intentionally
# bounded: the controller may demand evidence, but must never invent mappings.
MAX_PRODUCT_INPUT_MAPPING_REPAIRS = 2
PRODUCT_INPUT_MAPPING_REPAIR_PROTOCOL_VERSION = 2
PROJECT_MODES = {"greenfield", "brownfield", "self_analysis"}
_PHASE_A_GENERATED_FILES = frozenset(
    {
        Path("constitution.md"),
        Path("targets.yml"),
        Path("run-history.json"),
        Path("squad-report.md"),
        Path("ARTIFACTS.md"),
        Path("feature-metadata.yml"),
    }
)
_PHASE_A_KB_REPORT_FILES = frozenset(
    {
        Path("kb/kb-apply-report.yaml"),
        Path("kb/kb-usage-summary.yaml"),
    }
)
_PRODUCT_INPUT_PATH_KEYS = frozenset(
    {
        "manifest",
        "catalog",
        "input_context",
        "requirement_context",
        "reference_context",
        "traceability",
        "traceability_markdown",
    }
)
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
JUDGMENT_RESULT_CONTRACT = EchelonResultContract(
    allowed_state_update_keys=JUDGMENT_STATE_UPDATE_KEYS,
    state_update_types={
        "iteration": "integer",
        "status": "string",
        "escalation_resolved": "boolean",
    },
    state_update_enums={
        "status": frozenset({"running", "blocked", "done", "interrupted", "killed"}),
    },
    allowed_verdicts=frozenset({"JUDGMENT_RESOLVED", "BLOCKED"}),
    unexpected_state_updates="quarantine",
)

logger = logging.getLogger(__name__)


def _phase_dispatch_limit_phase(state: dict, fallback: str = "") -> str:
    """Identify the phase to retry after a human-authorized dispatch-cap recovery."""
    phase = str(state.get("phase_dispatch_limit_phase") or "").strip()
    if phase:
        return phase

    question = str(state.get("escalation_question") or "")
    match = re.search(r"Phase ['\"]([^'\"]+)['\"] has been dispatched", question)
    if match:
        return match.group(1)

    return fallback if fallback not in TERMINAL_PHASES else ""


def _spec_id_from_phase_a_dir(spec_dir: Path) -> str:
    if spec_dir.name.startswith("spec-"):
        return spec_dir.name.removeprefix("spec-")
    return spec_dir.name


def _checkpoint_spec_id_from_state(state: dict, spec_dir: Path) -> str:
    spec_dir_id = _spec_id_from_phase_a_dir(spec_dir)
    state_spec_id = str(state.get("spec_id") or "").strip()
    if state_spec_id and spec_dir_id.startswith(f"{state_spec_id}-"):
        return spec_dir_id
    return state_spec_id or spec_dir_id


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
    return not unresolved_constitution_template_markers(text)


def _blocked_banner(phase: str, reason: str, question: str) -> None:
    from echelon.ui import banner as _banner
    _banner(
        "SQUAD — BLOCKED",
        [
            ("phase", phase),
            ("reason", reason),
            ("question", question),
            ("answer with", "echelon spec resume \"<your answer>\""),
            ("discard with", "echelon spec run --reset \"<new task>\""),
        ],
    )


def _format_phase_dispatch_line(
    node: PhaseNode,
    graph: PhaseGraph,
    ext_dir: Path,
    *,
    file: object = None,
    suffix: str = "",
) -> str:
    """Render a squad phase dispatch line, using agent frontmatter color."""
    label = node.label or node.id
    target = file if file is not None else sys.stdout
    phase_id = color_text(
        node.id,
        _agent_frontmatter_color(node, graph, ext_dir),
        file=target,
    )
    return f"\n[squad] ▶ {phase_id}  {label}{suffix}"


def _agent_frontmatter_color(node: PhaseNode, graph: PhaseGraph, ext_dir: Path) -> str:
    if not node.agent:
        return ""
    rel = graph.agent_file(node.agent)
    if not rel:
        return ""
    path = ext_dir / rel
    if not path.exists():
        return ""
    color = read_prompt_markdown(path).metadata.get("color")
    return color if isinstance(color, str) else ""


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


@dataclass(frozen=True)
class ControllerEnrichment:
    """Controller-owned result additions produced before preparation."""

    updates: Mapping[str, object] = field(default_factory=dict)
    routing_override: str | None = None
    controller_owns_result_updates: bool = False
    state_removals: frozenset[str] = frozenset()
    control_updates: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "updates",
            MappingProxyType(deepcopy(dict(self.updates))),
        )
        object.__setattr__(
            self,
            "state_removals",
            frozenset(self.state_removals),
        )
        object.__setattr__(
            self,
            "control_updates",
            MappingProxyType(deepcopy(dict(self.control_updates))),
        )


@dataclass(frozen=True)
class CompletionRecoveryOutcome:
    """Structured proof of one completion recovered before phase work."""

    recovered: bool
    origin: str = ""
    manual_phase_run: bool = False
    completion_id: str = ""


class _TransitionJudgmentRequired(RuntimeError):
    """Signal that ordered routing needs external COMMANDER coordination."""

    def __init__(self, condition: str, transition_index: int) -> None:
        super().__init__(condition)
        self.condition = condition
        self.transition_index = transition_index


class _ProductInputCommitError(RuntimeError):
    """Product-input publication failed inside the state CAS window."""

    def __init__(self, reason: str) -> None:
        super().__init__("product input commit failed")
        self.reason = reason


class _PhaseAReadinessCommitError(RuntimeError):
    """Phase A publication was not build-ready inside the state CAS window."""

    def __init__(self, readiness: PhaseAReadinessResult) -> None:
        super().__init__("Phase A publication is not ready")
        self.readiness = readiness


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
        ignore_re: bool = False,
        implementation_targets: list[str] | None = None,
        product_inputs: object | None = None,
    ) -> None:
        existing_state = state_store.load()
        resolved_squad_dir = squad_dir or state_store.squad_dir
        manifest = resolved_squad_dir / "telemetry" / "manifest.json"
        try:
            manifest_trace_id = json.loads(manifest.read_text(encoding="utf-8")).get(
                "trace_id"
            )
        except (OSError, json.JSONDecodeError):
            manifest_trace_id = None
        trace_id = (
            manifest_trace_id
            if isinstance(manifest_trace_id, str) and len(manifest_trace_id) == 32
            else uuid.uuid4().hex
        )
        telemetry_store = TelemetryStore(
            resolved_squad_dir,
            workflow="spec",
            run_id=str(existing_state.get("run_id") or resolved_squad_dir.name),
            profile={"name": str(existing_state.get("autonomy_mode") or "default")},
            trace_id=trace_id,
        )
        self._telemetry_store = telemetry_store
        self._telemetry_usage_lock = threading.Lock()
        self._deferred_provider_usage: dict[str, int] | None = None
        self._provider = provider
        self._telemetry_provider = InstrumentedProvider(
            provider,
            telemetry_store,
            usage_recorder=self._record_provider_usage,
        )
        self._state_store = state_store
        self._graph = phase_graph
        self._ext_dir = ext_dir
        self._project_root = project_root
        self._token_budget = token_budget
        self._max_iterations = max_iterations
        self._squad_dir = squad_dir or state_store.squad_dir
        self._ignore_re = ignore_re
        self._implementation_targets = list(implementation_targets or [])
        self._product_inputs = product_inputs
        self._evaluator = ConditionEvaluator()
        self._gate_config_cache: Optional[dict] = None
        self._gov_config_cache: Optional[dict] = None
        self._executors: dict[str, PhaseExecutor] = {
            "agent": AgentExecutor(self._telemetry_provider, phase_graph, ext_dir, project_root, self._squad_dir),
            "commander_internal": CommanderInternalExecutor(self._telemetry_provider, phase_graph, ext_dir, project_root, self._squad_dir),
            "deterministic_lexicon": DeterministicLexiconExecutor(phase_graph, ext_dir, project_root, self._squad_dir),
            "deterministic_understanding": DeterministicUnderstandingExecutor(phase_graph, ext_dir, project_root, self._squad_dir),
            "staged_parallel": StagedParallelExecutor(self._telemetry_provider, phase_graph, ext_dir, project_root, self._squad_dir),
            "conditional_sequential": ConditionalSequentialExecutor(self._telemetry_provider, phase_graph, ext_dir, project_root, self._squad_dir),
            "human_gate": HumanGateExecutor(self._telemetry_provider, phase_graph, ext_dir, project_root, self._squad_dir),
        }
        self._cancelled = False
        self._phase_a_published_this_run = False
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _ensure_telemetry_manifest(self) -> None:
        """Make a run's telemetry identity available before agents invoke shims."""
        state = self._state_store.load()
        if not self._telemetry_store.manifest_path.exists():
            self._telemetry_store.run_id = str(
                state.get("run_id") or self._squad_dir.name
            )
            self._telemetry_store.profile = {
                "name": str(state.get("autonomy_mode") or "default")
            }
        try:
            self._telemetry_store.ensure_manifest()
        except Exception:
            logger.warning(
                "Could not initialize telemetry manifest for run_id=%s",
                state.get("run_id") or self._squad_dir.name,
                exc_info=True,
            )

    def _start_declared_phase_timing(self, node: PhaseNode) -> None:
        """Open a workflow-declared timing window before phase dispatch."""
        phase = str(node.timing_window_start or "").strip()
        budget = node.budget_seconds
        if not phase or budget is None:
            return
        try:
            record_phase_start(
                self._telemetry_store,
                phase=phase,
                budget_seconds=float(budget),
            )
        except Exception:
            logger.warning(
                "Could not start declared phase timing for %s",
                phase,
                exc_info=True,
            )

    def _declared_phase_timing_budget(self, phase: str) -> float | None:
        """Resolve a timing budget from start or transition declarations."""
        for phase_id in self._graph.all_phase_ids():
            candidate = self._graph.get(phase_id)
            if (
                candidate.timing_window_start == phase
                and candidate.budget_seconds is not None
            ):
                return float(candidate.budget_seconds)
            transition = candidate.timing_window_transition
            if (
                isinstance(transition, dict)
                and str(transition.get("open") or "").strip() == phase
                and transition.get("open_budget_seconds") is not None
            ):
                return float(transition["open_budget_seconds"])
        return None

    def _apply_declared_phase_timing_transition(
        self,
        node: PhaseNode,
        next_phase: str,
    ) -> None:
        """Apply timing close/open metadata after a successful phase advance."""
        if next_phase == node.id:
            return
        transition = node.timing_window_transition
        if not isinstance(transition, dict) or not transition:
            return

        close_phase = str(transition.get("close") or "").strip()
        open_phase = str(transition.get("open") or "").strip()
        open_budget = transition.get("open_budget_seconds")
        try:
            if close_phase:
                events, diagnostics = self._telemetry_store.read_phase_timings()
                if diagnostics:
                    raise ValueError("invalid phase timing telemetry")
                latest = next(
                    (
                        event
                        for event in reversed(events)
                        if event.phase == close_phase
                    ),
                    None,
                )
                if latest is None:
                    close_budget = self._declared_phase_timing_budget(close_phase)
                    if close_budget is None:
                        raise ValueError(
                            f"no timing budget declared for {close_phase!r}"
                        )
                    record_phase_start(
                        self._telemetry_store,
                        phase=close_phase,
                        budget_seconds=close_budget,
                    )
                    latest = next(
                        event
                        for event in reversed(
                            self._telemetry_store.read_phase_timings()[0]
                        )
                        if event.phase == close_phase
                    )
                if latest.event == "started":
                    record_phase_finish(
                        self._telemetry_store,
                        phase=close_phase,
                    )

            if open_phase:
                if open_budget is None:
                    raise ValueError(
                        f"no timing budget declared for {open_phase!r}"
                    )
                record_phase_start(
                    self._telemetry_store,
                    phase=open_phase,
                    budget_seconds=float(open_budget),
                )
        except Exception:
            logger.warning(
                "Could not apply declared phase timing transition for %s",
                node.id,
                exc_info=True,
            )

    def _record_provider_usage(self, result: object) -> None:
        if type(result) is not SquadAgentResult:
            return
        raw = result.token_usage
        if type(raw) is not int or raw <= 0:
            return
        with controller_lock_order(
            "telemetry",
            f"provider-usage:{self._squad_dir.absolute()}",
        ):
            with self._telemetry_usage_lock:
                if self._deferred_provider_usage is not None:
                    self._deferred_provider_usage["tokens"] += raw
                    return
                self._state_store.increment_token_usage(raw)

    @contextmanager
    def _defer_routing_provider_usage(self):
        previous = self._deferred_provider_usage
        accumulator = {"tokens": 0}
        self._deferred_provider_usage = accumulator
        try:
            yield accumulator
        finally:
            self._deferred_provider_usage = previous

    def _project_config_path(self) -> Path:
        canonical = self._project_root / ".echelon" / "config.yml"
        if canonical.exists():
            return canonical
        return self._ext_dir / "echelon-config.yml"

    def _quality_gate_thresholds(self) -> dict:
        return resolve_quality_gate_thresholds(
            self._project_root,
            fallback_config_path=self._ext_dir / "echelon-config.yml",
        )

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

    def _completion_timing_parameters(
        self,
        from_phase: str,
        to_phase: str,
    ) -> dict[str, object] | None:
        if from_phase == to_phase:
            return None
        try:
            node = self._graph.get(from_phase)
        except KeyError:
            return None
        transition = node.timing_window_transition
        if not isinstance(transition, dict) or not transition:
            return None
        close_phase = str(transition.get("close") or "").strip()
        open_phase = str(transition.get("open") or "").strip()
        if not close_phase and not open_phase:
            return None
        close_budget = (
            self._declared_phase_timing_budget(close_phase)
            if close_phase
            else None
        )
        open_budget_value = transition.get("open_budget_seconds")
        open_budget = (
            float(open_budget_value)
            if open_phase
            and type(open_budget_value) in (int, float)
            and float(open_budget_value) >= 0
            else (
                self._declared_phase_timing_budget(open_phase)
                if open_phase
                else None
            )
        )
        if (
            (close_phase and close_budget is None)
            or (open_phase and open_budget is None)
        ):
            return None
        return {
            "close_phase": close_phase or None,
            "close_budget_seconds": close_budget,
            "open_phase": open_phase or None,
            "open_budget_seconds": open_budget,
        }

    def _completion_checkpoint_prestate(self) -> dict[str, object]:
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "HEAD^{commit}"],
                cwd=self._project_root,
                check=True,
                capture_output=True,
                text=True,
            )
            stdout = completed.stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise StateAdvanceError(
                "controller checkpoint prestate is unavailable",
                json_path=(
                    f"$.{PENDING_CONTROLLER_COMPLETION_KEY}"
                    ".checkpoint_prestate"
                ),
                validator="checkpoint_prestate",
            ) from exc
        head = stdout.strip() if type(stdout) is str else ""
        if (
            re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", head)
            is None
            or set(head) == {"0"}
        ):
            raise StateAdvanceError(
                "controller checkpoint prestate is invalid",
                json_path=(
                    f"$.{PENDING_CONTROLLER_COMPLETION_KEY}"
                    ".checkpoint_prestate"
                ),
                validator="checkpoint_prestate",
            )
        return {"kind": "git_head", "head": head}

    def _completion_timing_is_active(
        self,
        from_phase: str,
        to_phase: str,
    ) -> bool:
        parameters = self._completion_timing_parameters(
            from_phase,
            to_phase,
        )
        if parameters is None:
            return False
        close_phase = parameters["close_phase"]
        if close_phase is None:
            return True
        try:
            events, diagnostics = (
                self._telemetry_store.read_phase_timings()
            )
        except Exception:
            return False
        if diagnostics:
            return False
        latest = next(
            (
                event
                for event in reversed(events)
                if event.phase == close_phase
            ),
            None,
        )
        return (
            latest is not None
            and latest.event == "started"
            and latest.budget_seconds
            == parameters["close_budget_seconds"]
        )

    @staticmethod
    def _completion_judgment_record(
        result: SquadAgentResult,
    ) -> dict[str, object]:
        detached = detach_squad_agent_result(result)
        payload = detached.echelon_result
        return {
            "echelon_result": payload if isinstance(payload, dict) else {},
            "quarantined_state_updates": dict(
                detached.quarantined_state_updates
            ),
        }

    def _prepare_controller_completion(
        self,
        *,
        from_phase: str,
        to_phase: str,
        snapshot: RoutingStateSnapshot,
        manual_phase_run: bool,
        conditional_skip: bool,
        record_completion: bool,
        publication_marker: Mapping[str, object] | None,
        judgments: tuple[SquadAgentResult, ...] = (),
        origin: str = "routed",
    ) -> PreparedControllerCompletion:
        """Seal all post-dispatch work before its authorizing state save."""
        if origin == "terminal":
            route: dict[str, object] = {
                "kind": "terminal",
                "terminal_phase": from_phase,
            }
            effect_plan = (
                ("mining",)
                if self._active_phase_a_spec_dir(snapshot.state) is not None
                else ()
            )
            judgment_records: tuple[dict[str, object], ...] = ()
        else:
            route = {
                "kind": "routed",
                "from_phase": from_phase,
                "to_phase": to_phase,
                "manual_phase_run": manual_phase_run,
                "record_completion": record_completion,
            }
            judgment_records = tuple(
                self._completion_judgment_record(result)
                for result in judgments
            )
            if not record_completion:
                effect_plan = ("journal", "checkpoint")
            else:
                effects: list[str] = []
                if judgment_records:
                    effects.append("journal")
                if (
                    self._completion_timing_is_active(
                        from_phase,
                        to_phase,
                    )
                ):
                    effects.append("timing")
                active_spec_dir = self._active_phase_a_spec_dir(
                    snapshot.state
                )
                if (
                    active_spec_dir is not None
                    and active_spec_dir.exists()
                ):
                    effects.append("checkpoint")
                effects.append("context")
                if from_phase == "phase4-document":
                    effects.append("mining")
                effect_plan = tuple(effects)
        publication = (
            {
                "kind": "external",
                "marker": dict(publication_marker),
            }
            if publication_marker is not None
            else {"kind": "none"}
        )
        checkpoint_prestate = (
            self._completion_checkpoint_prestate()
            if "checkpoint" in effect_plan
            else {"kind": "none"}
        )
        judgment_digests = tuple(
            _canonical_payload_sha256(
                dict(record["echelon_result"])
            )
            for record in judgment_records
        )
        try:
            return prepare_controller_completion_stage(
                self._project_root,
                self._squad_dir,
                completion_id=uuid.uuid4().hex,
                origin=origin,
                publication=publication,
                route=route,
                effect_plan=effect_plan,
                checkpoint_prestate=checkpoint_prestate,
                context_reason=(
                    "terminal Phase A reconciliation"
                    if origin == "terminal"
                    else (
                        f"{'manual ' if manual_phase_run else ''}"
                        f"{'skip ' if conditional_skip else ''}"
                        f"phase advance {from_phase} -> {to_phase}"
                    )
                ),
                mine_phase_a="mining" in effect_plan,
                judgment_payload_sha256=judgment_digests,
                judgments=judgment_records,
            )
        except CompletionError as exc:
            raise StateAdvanceError(
                "controller completion preparation failed",
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                validator=exc.code,
            ) from exc

    def _record_controller_completion_failure_best_effort(
        self,
        marker: object,
        code: str,
    ) -> None:
        try:
            self._state_store.record_controller_completion_failure(
                marker,
                code,
            )
        except Exception:
            logger.exception(
                "Could not persist controller completion failure code %s",
                code,
            )

    def _completion_checkpoint_inputs(
        self,
        prepared: PreparedControllerCompletion,
        state: Mapping[str, object],
    ) -> dict[str, object]:
        route = prepared.intent.route
        spec_dir = self._active_phase_a_spec_dir(dict(state))
        if spec_dir is not None and not spec_dir.exists():
            spec_dir = None
        additional_spec_dirs: tuple[Path, ...] = ()
        additional_owned_paths: tuple[Path, ...] = ()
        if (
            spec_dir is not None
            and route.get("from_phase") == "phase4-document"
            and route.get("to_phase") in TERMINAL_PHASES
        ):
            published = self._published_phase_a_spec_dir(
                dict(state),
                spec_dir,
            )
            if (
                published.exists()
                and published.resolve() != spec_dir.resolve()
            ):
                additional_spec_dirs = (published,)
            additional_owned_paths = accepted_kb_target_paths(
                self._project_root,
                str(state.get("run_id") or ""),
            )
        return {
            "project_root": self._project_root,
            "spec_dir": spec_dir,
            "run_id": str(state.get("run_id") or ""),
            "spec_id": (
                _checkpoint_spec_id_from_state(dict(state), spec_dir)
                if spec_dir is not None
                else ""
            ),
            "additional_spec_dirs": additional_spec_dirs,
            "additional_owned_paths": additional_owned_paths,
        }

    def _apply_controller_completion_effect(
        self,
        prepared: PreparedControllerCompletion,
        state: Mapping[str, object],
    ) -> None:
        with controller_lock_order(
            "completion",
            str(prepared._transaction_root.absolute()),
        ):
            self._apply_controller_completion_effect_ordered(
                prepared,
                state,
            )

    def _apply_controller_completion_effect_ordered(
        self,
        prepared: PreparedControllerCompletion,
        state: Mapping[str, object],
    ) -> None:
        effect = prepared.marker.step
        existing = prepared.receipts["effects"].get(effect)
        if effect == "journal":
            plan = prepare_completion_journal_plan(
                prepared.intent,
                self._squad_dir / "reasoning-journal.jsonl",
            )
            receipt = apply_or_verify_completion_journal(plan)
            persist_completion_effect_receipt(
                prepared,
                effect,
                receipt,
            )
            return
        if effect == "timing":
            route = prepared.intent.route
            parameters = self._completion_timing_parameters(
                str(route["from_phase"]),
                str(route["to_phase"]),
            )
            if parameters is None:
                raise CompletionError("intent_mismatch")
            receipt = apply_or_verify_completion_timing(
                prepared.intent,
                self._telemetry_store,
                expected_receipt=existing,
                **parameters,
            )
            persist_completion_effect_receipt(
                prepared,
                effect,
                receipt,
            )
            return
        if effect == "checkpoint":
            receipt = create_or_recover_completion_checkpoint(
                prepared.intent,
                expected_receipt=existing,
                **self._completion_checkpoint_inputs(
                    prepared,
                    state,
                ),
            )
            persist_completion_effect_receipt(
                prepared,
                effect,
                receipt,
            )
            return
        if effect == "context":
            receipt = prepare_or_load_completion_context(
                prepared,
                project_root=self._project_root,
                source_state_revision=int(
                    state.get("state_revision") or 0
                ),
                user_request=str(
                    state.get(
                        "user_request",
                        state.get("user_message", ""),
                    )
                    or ""
                ),
                drawers=self._retrieve_mempalace_context_drawers(
                    str(
                        state.get(
                            "user_request",
                            state.get("user_message", ""),
                        )
                        or ""
                    ),
                    str(state.get("run_id") or ""),
                ),
            )
            install_or_verify_completion_context(
                prepared,
                expected_receipt=receipt,
            )
            return
        if effect == "mining":
            published_ref = str(
                state.get("published_spec_dir") or ""
            ).strip()
            spec_file = (
                self._absolute_project_path(published_ref) / "spec.md"
                if published_ref
                else None
            )
            if spec_file is not None and not spec_file.is_file():
                spec_file = None
            metadata: object = None
            if spec_file is not None:
                try:
                    from echelon.context_metadata import (
                        read_feature_metadata,
                    )

                    raw_metadata = read_feature_metadata(
                        spec_file.parent
                    )
                    if raw_metadata is not None:
                        spec_sha256 = hashlib.sha256(
                            spec_file.read_bytes()
                        ).hexdigest()
                        metadata = (
                            self._canonical_spec_artifact_metadata(
                                spec_file,
                                raw_metadata,
                                f"sha256:{spec_sha256}",
                            )
                        )
                except Exception:
                    metadata = None
            apply_or_verify_completion_mining(
                prepared,
                project_root=self._project_root,
                spec_file=spec_file,
                run_id=str(state.get("run_id") or ""),
                artifact_metadata=metadata,
                expected_receipt=existing,
            )
            return
        raise CompletionError("intent_mismatch")

    def _discard_completed_controller_stage(
        self,
        prepared: PreparedControllerCompletion,
    ) -> None:
        try:
            state = self._state_store.load()
        except Exception:
            return
        if PENDING_CONTROLLER_COMPLETION_KEY in state:
            return
        try:
            state = self._state_store.confirm_durable_state(state)
        except StateDurabilityError:
            return
        marker = prepared.marker
        if marker.origin == "routed":
            dispatch = state.get("last_dispatch")
            proven = (
                isinstance(dispatch, Mapping)
                and dispatch.get("dispatch_id") == marker.completion_id
                and dispatch.get("post_dispatch_complete") is True
                and dispatch.get("completion_intent_sha256")
                == marker.intent_sha256
                and dispatch.get("completion_receipts_sha256")
                == marker.receipts_sha256
            )
        else:
            terminal = state.get("last_terminal_completion")
            proven = (
                isinstance(terminal, Mapping)
                and terminal.get("completion_id") == marker.completion_id
                and terminal.get("intent_sha256")
                == marker.intent_sha256
                and terminal.get("receipts_sha256")
                == marker.receipts_sha256
            )
        if not proven:
            return
        try:
            prepared.discard()
        except CompletionError:
            logger.warning(
                "Could not discard completed controller stage",
                exc_info=True,
            )

    def _cleanup_controller_completion_orphans(self) -> bool:
        """Remove valid unreferenced stages; retain incomplete dispatch proof."""
        try:
            state = self._state_store.load()
        except Exception:
            return False
        if (
            PENDING_CONTROLLER_COMPLETION_KEY in state
            or PENDING_EXTERNAL_PUBLICATION_KEY in state
        ):
            return False
        retained_id = ""
        dispatch = state.get("last_dispatch")
        if (
            isinstance(dispatch, Mapping)
            and dispatch.get("post_dispatch_complete") is False
        ):
            candidate = dispatch.get("dispatch_id")
            intent_digest = dispatch.get(
                "completion_intent_sha256"
            )
            if (
                type(candidate) is not str
                or re.fullmatch(r"[0-9a-f]{32}", candidate) is None
                or type(intent_digest) is not str
                or re.fullmatch(r"[0-9a-f]{64}", intent_digest) is None
            ):
                return False
            retained_id = candidate
        outbox = self._squad_dir / ".completion-outbox"
        try:
            metadata = os.lstat(outbox)
        except FileNotFoundError:
            return not retained_id
        except OSError:
            return False
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
        ):
            return False
        try:
            state = self._state_store.confirm_durable_state(state)
        except StateDurabilityError:
            return False
        try:
            with os.scandir(outbox) as iterator:
                entries = tuple(iterator)
        except OSError:
            return False
        for entry in entries:
            if (
                re.fullmatch(r"[0-9a-f]{32}", entry.name) is None
                or entry.name == retained_id
            ):
                continue
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                discard_unreferenced_controller_completion(
                    self._project_root,
                    self._squad_dir,
                    entry.name,
                )
            except CompletionError:
                continue
        return not retained_id

    def _drain_pending_controller_completion(
        self,
    ) -> CompletionRecoveryOutcome:
        """Validate, replay, and finalize one exact durable completion."""
        state = self._state_store.load()
        if (
            PENDING_CONTROLLER_COMPLETION_KEY in state
            or PENDING_EXTERNAL_PUBLICATION_KEY in state
        ):
            try:
                state = self._state_store.confirm_durable_state(state)
            except StateDurabilityError:
                return CompletionRecoveryOutcome(False)
        if PENDING_CONTROLLER_COMPLETION_KEY not in state:
            if PENDING_EXTERNAL_PUBLICATION_KEY in state:
                self._record_controller_completion_failure_best_effort(
                    None,
                    "completion_missing",
                )
            return CompletionRecoveryOutcome(False)
        raw_marker = state[PENDING_CONTROLLER_COMPLETION_KEY]
        try:
            marker = validate_pending_controller_completion(raw_marker)
            prepared = load_prepared_controller_completion(
                self._project_root,
                self._squad_dir,
                marker,
            )
        except CompletionError as exc:
            self._record_controller_completion_failure_best_effort(
                raw_marker,
                exc.code,
            )
            return CompletionRecoveryOutcome(False)
        except Exception:
            self._record_controller_completion_failure_best_effort(
                raw_marker,
                "intent_invalid",
            )
            return CompletionRecoveryOutcome(False)

        route = prepared.intent.route
        origin = prepared.intent.origin
        manual = bool(
            route.get("manual_phase_run", False)
            if origin == "routed"
            else False
        )
        outcome = CompletionRecoveryOutcome(
            False,
            origin,
            manual,
            prepared.marker.completion_id,
        )
        try:
            publication = prepared.intent.publication
            has_persisted_publication = (
                PENDING_EXTERNAL_PUBLICATION_KEY in state
            )
            persisted_publication = state.get(
                PENDING_EXTERNAL_PUBLICATION_KEY
            )
            if publication["kind"] == "external":
                expected_publication = publication["marker"]
                if prepared.marker.step == "awaiting_publication":
                    if (
                        not has_persisted_publication
                        or persisted_publication
                        != expected_publication
                    ):
                        raise CompletionError("intent_mismatch")
                    try:
                        staged_publication = load_prepared_publication(
                            self._project_root,
                            self._squad_dir,
                            expected_publication,
                        )
                        staged_publication.publish()
                    except PublicationError as exc:
                        self._record_external_publication_failure_best_effort(
                            expected_publication,
                            exc.code,
                        )
                        return outcome
                    except Exception:
                        self._record_external_publication_failure_best_effort(
                            expected_publication,
                            "publish_io",
                        )
                        return outcome
                    try:
                        self._state_store.handoff_external_publication(
                            expected_publication,
                            prepared,
                        )
                    except StateDurabilityError:
                        return outcome
                    except StateAdvanceError:
                        self._record_external_publication_failure_best_effort(
                            expected_publication,
                            "state_finalize",
                        )
                        return outcome
                    handed = self._state_store.load()
                    expected_next = (
                        prepared.intent.effect_plan[0]
                        if prepared.intent.effect_plan
                        else "complete"
                    )
                    next_marker = handed.get(
                        PENDING_CONTROLLER_COMPLETION_KEY
                    )
                    if (
                        PENDING_EXTERNAL_PUBLICATION_KEY in handed
                        or not isinstance(next_marker, Mapping)
                        or next_marker.get("completion_id")
                        != prepared.marker.completion_id
                        or next_marker.get("step") != expected_next
                    ):
                        return outcome
                    try:
                        self._state_store.confirm_durable_state(handed)
                    except StateDurabilityError:
                        return outcome
                    try:
                        staged_publication.discard()
                    except PublicationError:
                        logger.warning(
                            "Could not discard handed-off publication stage",
                            exc_info=True,
                        )
                    if route.get("from_phase") == "phase4-document":
                        self._phase_a_published_this_run = True
                elif has_persisted_publication:
                    raise CompletionError("intent_mismatch")
            elif has_persisted_publication:
                raise CompletionError("intent_mismatch")

            while True:
                current_state = self._state_store.load()
                if (
                    PENDING_CONTROLLER_COMPLETION_KEY
                    not in current_state
                ):
                    return outcome
                current_raw = current_state[
                    PENDING_CONTROLLER_COMPLETION_KEY
                ]
                prepared = load_prepared_controller_completion(
                    self._project_root,
                    self._squad_dir,
                    current_raw,
                )
                step = prepared.marker.step
                if step == "awaiting_publication":
                    raise CompletionError("intent_mismatch")
                if step == "complete":
                    digests = self._phase_a_inventory_digests(
                        current_state
                    )
                    if (
                        prepared.marker.origin == "routed"
                        and prepared.intent.route.get("from_phase")
                        == "phase4-document"
                    ):
                        if digests is None:
                            raise CompletionError("receipts_mismatch")
                        self._state_store.complete_controller_completion(
                            prepared,
                            phase_a_active_source_sha256=digests[0],
                            phase_a_published_postimage_sha256=digests[1],
                        )
                    elif (
                        prepared.marker.origin == "terminal"
                    ):
                        if digests is None:
                            raise CompletionError("receipts_mismatch")
                        self._state_store.complete_controller_completion(
                            prepared,
                            phase_a_active_source_sha256=digests[0],
                            phase_a_published_postimage_sha256=digests[1],
                        )
                    else:
                        self._state_store.complete_controller_completion(
                            prepared,
                        )
                    self._discard_completed_controller_stage(prepared)
                    return CompletionRecoveryOutcome(
                        True,
                        origin,
                        manual,
                        prepared.marker.completion_id,
                    )
                self._apply_controller_completion_effect(
                    prepared,
                    current_state,
                )
                one_ahead = load_prepared_controller_completion(
                    self._project_root,
                    self._squad_dir,
                    current_raw,
                )
                self._state_store.advance_controller_completion(
                    one_ahead,
                )
        except CompletionError as exc:
            self._record_controller_completion_failure_best_effort(
                self._state_store.load().get(
                    PENDING_CONTROLLER_COMPLETION_KEY
                ),
                exc.code,
            )
            return outcome
        except StateDurabilityError:
            return outcome
        except StateAdvanceError:
            self._record_controller_completion_failure_best_effort(
                self._state_store.load().get(
                    PENDING_CONTROLLER_COMPLETION_KEY
                ),
                "stage_io",
            )
            return outcome

    def _run_with_execution_lease(
        self,
        execute: Callable[[], SquadResult],
        *,
        stop_after_recovered_manual: bool = False,
    ) -> SquadResult:
        """Serialize controller execution for this run before touching state."""

        operation_id = f"squad-exec-{os.getpid()}"
        try:
            with PhaseAExecutionLock.acquire(
                self._project_root,
                operation_id,
            ):
                with SpecRunExecutionLock.acquire(
                    self._squad_dir,
                    operation_id,
                ):
                    recovery = (
                        self._drain_pending_controller_completion()
                    )
                    recovered_state = self._state_store.load()
                    if (
                        PENDING_CONTROLLER_COMPLETION_KEY
                        in recovered_state
                        or PENDING_EXTERNAL_PUBLICATION_KEY
                        in recovered_state
                    ):
                        return SquadResult.from_state(recovered_state)
                    if (
                        stop_after_recovered_manual
                        and recovery.recovered
                        and recovery.manual_phase_run
                    ):
                        return SquadResult.from_state(recovered_state)
                    if not self._cleanup_controller_completion_orphans():
                        return SquadResult.from_state(
                            self._state_store.load()
                        )
                    return execute()
        except SpecLifecycleLocked as exc:
            state = self._state_store.load()
            phase = str(state.get("phase") or "unknown")
            run_id = str(state.get("run_id") or self._squad_dir.name)
            logger.warning("Phase A run %s is already executing: %s", run_id, exc)
            print(
                f"[squad] run already active — refusing concurrent execution ({exc})",
                flush=True,
            )
            return SquadResult(status="busy", phase=phase, run_id=run_id)

    def _record_external_publication_failure_best_effort(
        self,
        marker: Mapping[str, object],
        code: str,
    ) -> None:
        try:
            self._state_store.record_external_publication_failure(
                marker,
                code,
            )
        except Exception:
            logger.exception(
                "Could not persist external publication failure code %s",
                code,
            )

    def _record_malformed_external_publication_failure_best_effort(
        self,
        marker: object,
    ) -> None:
        try:
            self._state_store.record_malformed_external_publication_failure(
                marker,
            )
        except Exception:
            logger.exception(
                "Could not persist malformed external publication failure"
            )

    def _publish_and_finalize(
        self,
        prepared: PreparedSquadPublication,
        marker: Mapping[str, object],
    ) -> bool:
        """Publish one authorized stage and durably clear its exact marker."""
        try:
            expected_marker = validate_pending_external_publication(marker)
            prepared_marker = validate_pending_external_publication(
                prepared.marker.to_dict()
            )
            persisted_marker = validate_pending_external_publication(
                self._state_store.load().get(
                    PENDING_EXTERNAL_PUBLICATION_KEY
                )
            )
        except Exception:
            return False
        if (
            prepared_marker != expected_marker
            or persisted_marker != expected_marker
        ):
            return False
        try:
            prepared.publish()
        except PublicationError as exc:
            self._record_external_publication_failure_best_effort(
                expected_marker,
                exc.code,
            )
            return False
        except Exception:
            self._record_external_publication_failure_best_effort(
                expected_marker,
                "publish_io",
            )
            return False

        try:
            self._state_store.complete_external_publication(expected_marker)
            cleared = self._state_store.load()
            if PENDING_EXTERNAL_PUBLICATION_KEY in cleared:
                raise StateAdvanceError(
                    "external publication marker was not cleared",
                    json_path=f"$.{PENDING_EXTERNAL_PUBLICATION_KEY}",
                    validator="state_finalize",
                )
            try:
                self._state_store.confirm_durable_state(cleared)
            except StateDurabilityError:
                return False
        except StateDurabilityError:
            return False
        except Exception:
            try:
                cleared = self._state_store.load()
                completion_won = (
                    PENDING_EXTERNAL_PUBLICATION_KEY not in cleared
                )
            except Exception:
                completion_won = False
            if completion_won:
                try:
                    self._state_store.confirm_durable_state(cleared)
                except StateDurabilityError:
                    return False
                try:
                    prepared.discard()
                except PublicationError:
                    logger.warning(
                        "Could not discard completed external publication stage",
                        exc_info=True,
                    )
                return True
            self._record_external_publication_failure_best_effort(
                expected_marker,
                "state_finalize",
            )
            return False

        try:
            prepared.discard()
        except PublicationError:
            logger.warning(
                "Could not discard completed external publication stage",
                exc_info=True,
            )
        return True

    def _recover_pending_external_publication(self) -> bool:
        """Replay the exact state-authorized stage before any phase work."""
        state = self._state_store.load()
        if PENDING_EXTERNAL_PUBLICATION_KEY not in state:
            return True
        try:
            state = self._state_store.confirm_durable_state(state)
        except StateDurabilityError:
            return False
        marker_value = state[PENDING_EXTERNAL_PUBLICATION_KEY]
        try:
            marker = validate_pending_external_publication(marker_value)
        except Exception:
            self._record_malformed_external_publication_failure_best_effort(
                marker_value,
            )
            return False
        try:
            prepared = load_prepared_publication(
                self._project_root,
                self._squad_dir,
                marker,
            )
        except PublicationError as exc:
            marker = (
                marker_value
                if isinstance(marker_value, Mapping)
                else {}
            )
            self._record_external_publication_failure_best_effort(
                marker,
                exc.code,
            )
            return False
        except Exception:
            self._record_external_publication_failure_best_effort(
                marker,
                "manifest_invalid",
            )
            return False
        completed = self._publish_and_finalize(prepared, marker)
        if completed:
            last_dispatch = state.get("last_dispatch")
            if (
                (
                    isinstance(last_dispatch, Mapping)
                    and last_dispatch.get("phase_id")
                    == "phase4-document"
                )
                or (
                    str(state.get("phase") or "") in TERMINAL_PHASES
                    and bool(state.get("published_spec_dir"))
                )
            ):
                self._phase_a_published_this_run = True
                self._mine_published_context_after_publication()
        return completed

    def _discard_publication_without_authority(
        self,
        prepared: PreparedSquadPublication | None,
    ) -> None:
        """Discard a stage only after proving its marker is not durable."""
        if prepared is None:
            return
        marker = prepared.marker.to_dict()
        try:
            state = self._state_store.load()
        except Exception:
            return
        if state.get(PENDING_EXTERNAL_PUBLICATION_KEY) == marker:
            return
        try:
            prepared.discard()
        except PublicationError:
            logger.warning(
                "Could not discard unreferenced external publication stage",
                exc_info=True,
            )

    def run(
        self,
        user_message: str = "",
        mode: str = "semi",
        next_phase_override: str = "",
    ) -> SquadResult:
        return self._run_with_execution_lease(
            lambda: self._run_locked(user_message, mode, next_phase_override)
        )

    def _run_locked(
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
                        ("then re-run", "echelon spec run"),
                        ("or discard", "echelon spec run --reset"),
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
                        ("recover", "echelon spec run --next-phase <phase-id>"),
                        ("valid phase IDs", "\n".join(f"  {p}" for p in valid_phases)),
                        ("discard", "echelon spec run --reset"),
                    ],
                )
                return SquadResult(
                    status="blocked",
                    phase=existing.get("phase", "unknown"),
                    run_id=existing.get("run_id", ""),
                )

        # Contract failures are retryable at the same node. Keep the diagnostic
        # until a later successful state advance proves that the phase completed.
        elif (
            existing_status == "blocked"
            and blocked_reason == "controller_state_contract_validation_failed"
        ):
            state = self._state_store.load()
            state["status"] = "running"
            state["blocked_reason"] = None
            self._state_store.save(state)
            existing_status = "running"
            force_resume = True
            print(
                f"[squad] controller contract recovery → retrying "
                f"{state.get('phase')!r}",
                flush=True,
            )

        # Deterministic analysis failures are retryable at the same node. Keep
        # their immutable evidence pointer and run identity instead of treating
        # them like an incomplete provider dispatch that must be reinitialized.
        elif (
            existing_status == "blocked"
            and self._is_deterministic_understanding_phase(
                str(existing.get("phase") or "")
            )
        ):
            state = self._state_store.load()
            state["status"] = "running"
            state["blocked_reason"] = None
            self._state_store.save(state)
            existing_status = "running"
            force_resume = True
            print(
                f"[squad] deterministic analysis recovery → retrying "
                f"{state.get('phase')!r}",
                flush=True,
            )

        # ── Escalation block ──────────────────────────────────────────────
        elif existing_status == "blocked" and existing.get("escalation_question"):
            q = existing.get("escalation_question", "")
            mode_at_block = _state_autonomy_mode(existing, mode)
            recovery_reason = str(existing.get("blocked_reason") or "")

            if mode_at_block == "banzai":
                print(
                    f"\n[squad] escalation detected — banzai mode, "
                    f"dispatching COMMANDER judgment\n"
                    f"  Questions: {q[:120]}",
                    flush=True,
                )
                self._judgment_dispatch_escalation(
                    escalation_question=q,
                    blocked_phase=existing.get("phase", "unknown"),
                    recovery_reason=recovery_reason,
                )
                recovered = self._state_store.load()
                existing_status = recovered.get("status")
                if existing_status == "blocked":
                    return SquadResult.from_state(recovered)
                force_resume = True
            else:
                # semi / guided: stop and require echelon spec resume
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

        if existing and existing_status == "done" and str(existing.get("phase") or "") in TERMINAL_PHASES:
            readiness = self._publish_terminal_phase_a_artifacts_if_available()
            if readiness is not None and not readiness.ready:
                pending_state = self._state_store.load()
                if (
                    PENDING_CONTROLLER_COMPLETION_KEY
                    in pending_state
                    or PENDING_EXTERNAL_PUBLICATION_KEY in pending_state
                ):
                    return SquadResult.from_state(pending_state)
                self._block_after_phase_a_readiness_failure(readiness)
            else:
                state = self._state_store.load()
                state["status"] = "done"
                self._state_store.save(state)
            return SquadResult.from_state(self._state_store.load())

        # Fresh start if no state or not resumable
        # The correct squad dir was already selected by _cmd_run before creating this controller.
        if not existing or existing_status not in ("running", "in_progress"):
            prepared_identity = {
                key: existing[key]
                for key in (
                    "run_id",
                    "spec_id",
                    "spec_number",
                    "spec_dir",
                    "published_spec_dir",
                    "feature_branch",
                    "phase_a_default_branch",
                    "phase_a_base_commit",
                    "specify_feature_directory",
                )
                if key in existing
            }
            run_id = str(prepared_identity.get("run_id") or f"squad-{int(time.time())}")
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
                implementation_targets=self._implementation_targets,
                product_inputs=(
                    self._product_inputs.state_payload(self._project_root)
                    if self._product_inputs is not None
                    else None
                ),
            )
            if prepared_identity:
                initialized = self._state_store.load()
                initialized.update(prepared_identity)
                self._state_store.save(initialized)
            self._ensure_telemetry_manifest()
            self._attach_published_re_context()
            if self._state_store.load().get("status") == "blocked":
                return SquadResult.from_state(self._state_store.load())
            self._refresh_run_context("fresh initialization")
        else:
            print(f"[squad] resuming from phase: {self._state_store.current_phase()}", flush=True)
            state = self._state_store.load()
            if state.get("cancel_requested"):
                state["cancel_requested"] = False
                self._state_store.save(state)
            self._ensure_telemetry_manifest()

        while True:
            phase = self._state_store.current_phase()
            phase = self._guard_spec_lexicon_evidence(phase)
            phase = self._guard_understanding_evidence(phase)
            guarded_phase = self._apply_phase_recommendation_guard(phase)
            if guarded_phase != phase:
                phase = guarded_phase
            guarded_phase = self._guard_constitution_provenance(phase)
            if guarded_phase != phase:
                phase = guarded_phase

            if phase in TERMINAL_PHASES:
                state = self._state_store.load()
                # ``terminal-blocked`` is not finalization.  It is a hard stop
                # requested by a guard, and must never be converted into a
                # readiness check or a successful completion merely because an
                # earlier banzai handler temporarily set status=running.
                if phase == PHASE_TERMINAL_BLOCKED:
                    if state.get("status") != "blocked":
                        state["status"] = "blocked"
                        state["blocked_reason"] = (
                            state.get("blocked_reason") or "terminal_blocked"
                        )
                        self._state_store.save(state)
                    return SquadResult.from_state(self._state_store.load())
                # Preserve "blocked" status set by guards (e.g. consecutive-fail).
                # Only write "done" when not already in a terminal-blocked state.
                if state.get("status") != "blocked":
                    readiness = self._publish_terminal_phase_a_artifacts_if_available()
                    if readiness is not None and not readiness.ready:
                        pending_state = self._state_store.load()
                        if (
                            PENDING_CONTROLLER_COMPLETION_KEY
                            in pending_state
                            or PENDING_EXTERNAL_PUBLICATION_KEY in pending_state
                        ):
                            return SquadResult.from_state(pending_state)
                        self._block_after_phase_a_readiness_failure(readiness)
                        return SquadResult.from_state(self._state_store.load())
                    state = self._state_store.load()
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
                self._record_blocker_event(phase, "token_budget_exhausted")
                return SquadResult(
                    status="budget_exhausted",
                    phase=phase,
                    run_id=self._state_store.load().get("run_id", ""),
                )

            node = self._graph.get(phase)

            if self._skip_phase_if_condition_false(node):
                continue

            self._start_declared_phase_timing(node)

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
                s["phase_dispatch_limit_phase"] = phase
                s["phase_dispatch_limit"] = phase_limit
                s["status"] = "blocked"
                self._state_store.save(s)
                self._record_blocker_event(phase, "phase_dispatch_limit")
                print(
                    f"[squad] ✗ phase dispatch limit: {phase!r} dispatched "
                    f"{dispatch_count}× (limit {phase_limit}) — forcing escalation",
                    flush=True,
                )
                s = self._state_store.load()
                s["phase"] = PHASE_TERMINAL_BLOCKED
                self._state_store.save(s)
                return SquadResult.from_state(self._state_store.load())

            print(
                _format_phase_dispatch_line(node, self._graph, self._ext_dir),
                flush=True,
            )

            executor = self._executors.get(node.type)
            try:
                if executor is None:
                    result = self._judgment_dispatch(
                        f"Unknown phase type {node.type!r} for phase {phase!r}",
                        node,
                    )
                else:
                    with self._telemetry_provider.dispatch(
                        DispatchContext(
                            phase=phase,
                            agent=str(node.agent or node.type),
                            kind=(
                                "repair"
                                if dispatch_count > 1
                                else "phase"
                            ),
                            attempt=dispatch_count,
                            reason=self._dispatch_reason(
                                phase,
                                dispatch_count,
                            ),
                        )
                    ):
                        result = executor.execute(
                            node,
                            self._state_store,
                        )
            except ControllerStateContractViolation as exc:
                self._block_after_executor_contract_failure(node, exc)
                return SquadResult.from_state(self._state_store.load())

            snapshot = self._state_store.capture_routing_snapshot(
                expected_phase=node.id
            )
            prepared = self._prepare_phase_result_or_block(
                node,
                result,
                snapshot,
            )
            if prepared is None:
                return SquadResult.from_state(self._state_store.load())
            prepared_result = prepared.as_squad_agent_result()

            blocked_result = self._blocked_executor_reason(
                prepared_result,
                prepared.control_updates,
            )
            if blocked_result:
                self._block_after_executor_failure(
                    phase,
                    blocked_result,
                    prepared_result,
                    snapshot=snapshot,
                )
                return SquadResult.from_state(self._state_store.load())

            prepared_publication: PreparedSquadPublication | None = None
            try:
                prepared_publication = (
                    self._prepare_external_phase_effects(
                        prepared_result,
                        phase,
                        snapshot.state,
                        manual_phase_run=False,
                    )
                )
            except _ProductInputCommitError as exc:
                product_input_error = exc.reason
                if self._schedule_product_input_mapping_repair(
                    phase,
                    product_input_error,
                    prepared_result,
                    snapshot=snapshot,
                ):
                    continue
                self._block_after_executor_failure(
                    phase,
                    product_input_error,
                    prepared_result,
                    snapshot=snapshot,
                )
                return SquadResult.from_state(self._state_store.load())
            except _PhaseAReadinessCommitError as exc:
                self._block_after_phase_a_readiness_failure(
                    exc.readiness,
                    snapshot=snapshot,
                )
                return SquadResult.from_state(self._state_store.load())

            routing_updates = self._planned_phase_a_publication_updates(
                phase,
                snapshot.state,
            )
            if prepared_publication is not None:
                routing_updates[PENDING_EXTERNAL_PUBLICATION_KEY] = (
                    prepared_publication.marker.to_dict()
                )
            decision = self._construct_routing_decision_or_block(
                node,
                prepared,
                snapshot,
                additional_state_updates=routing_updates,
            )
            if decision is None:
                self._discard_publication_without_authority(
                    prepared_publication,
                )
                return SquadResult.from_state(self._state_store.load())
            next_phase = decision.to_phase

            receipt = self._advance_prepared_result_or_block(
                node,
                decision,
                prepared_publication=prepared_publication,
            )
            if receipt is None:
                return SquadResult.from_state(self._state_store.load())

            # Inline escalation check — fires when _evaluate_transitions detected
            # escalation_question in state_updates and returned the current phase.
            # Handles it in the same run() invocation rather than requiring a
            # re-invocation to reach the top-of-loop escalation block.
            state_now = self._state_store.load()
            if state_now.get("status") == "blocked" and state_now.get("escalation_question") and not state_now.get("escalation_resolved"):
                q = state_now["escalation_question"]
                run_mode = _state_autonomy_mode(state_now, mode)
                recovery_reason = str(state_now.get("blocked_reason") or "")
                if run_mode == "banzai":
                    print(
                        f"[squad] ~ {node.id}  escalation — banzai COMMANDER judgment",
                        flush=True,
                    )
                    self._judgment_dispatch_escalation(
                        q,
                        phase,
                        recovery_reason=recovery_reason,
                    )
                    if self._state_store.load().get("status") == "blocked":
                        return SquadResult.from_state(self._state_store.load())
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

    def _guard_understanding_evidence(self, phase: str) -> str:
        """Route legacy or stale SAGE dispatches through deterministic analysis."""
        gate_by_target = {
            "phase1-why2": "phase1-understanding",
            "phase3-consensus": "phase3-understanding",
        }
        gate = gate_by_target.get(phase)
        if gate is None:
            return phase
        state = self._state_store.load()
        if has_current_understanding_evidence(
            state,
            project_root=self._project_root,
            phase=phase,
        ):
            return phase
        state["phase"] = gate
        self._state_store.save(state)
        print(
            f"[squad] {phase}: certified Understanding evidence missing or stale; "
            f"routing through {gate}",
            flush=True,
        )
        return gate

    def _guard_spec_lexicon_evidence(self, phase: str) -> str:
        """Route legacy downstream resumes through visible spec certification."""
        phase_ids = list(self._graph.all_phase_ids())
        try:
            gate_index = phase_ids.index("phase1-lexicon")
            done_index = phase_ids.index("done")
        except ValueError:
            return phase
        downstream = set(phase_ids[gate_index + 1 : done_index + 1])
        if phase not in downstream:
            return phase
        state = self._state_store.load()
        if has_current_spec_lexicon_evidence(
            state,
            project_root=self._project_root,
            config=self._lexicon_gate_config(),
        ):
            return phase
        invalidated = downstream | {"phase1-lexicon"}
        completed = state.get("completed_phases")
        if isinstance(completed, list):
            state["completed_phases"] = [
                item for item in completed if item not in invalidated
            ]
        counts = state.get("phase_dispatch_counts")
        if isinstance(counts, dict):
            state["phase_dispatch_counts"] = {
                item: count
                for item, count in counts.items()
                if item not in invalidated
            }
        state["iteration"] = 0
        state["why_fail_count"] = 0
        state["convergence_forced"] = False
        state["convergence_detected"] = False
        state["convergence_guard_fire_count"] = 0
        state.pop("phase_recommendation", None)
        state["phase"] = "phase1-lexicon"
        self._state_store.save(state)
        print(
            f"[squad] {phase}: spec Lexicon evidence missing or stale; "
            "routing through phase1-lexicon",
            flush=True,
        )
        return "phase1-lexicon"

    def _is_deterministic_understanding_phase(self, phase: str) -> bool:
        if not phase:
            return False
        try:
            return self._graph.get(phase).type == "deterministic_understanding"
        except KeyError:
            return False

    def _attach_published_re_context(self) -> None:
        """Snapshot the latest durable RE publication for this spec run."""
        state = self._state_store.load()
        try:
            context = attach_published_re_context(
                self._project_root,
                self._squad_dir,
                ignore=self._ignore_re,
            )
        except Exception as exc:
            state["status"] = "blocked"
            state["blocked_reason"] = f"published_re_context_failed: {exc}"
            self._state_store.save(state)
            return
        state["published_re_context"] = context
        self._state_store.save(state)

    def run_single_phase(
        self,
        phase_id: str,
        user_message: str = "",
        mode: str = "semi",
        initial_state_updates: dict | None = None,
    ) -> SquadResult:
        return self._run_with_execution_lease(
            lambda: self._run_single_phase_locked(
                phase_id,
                user_message,
                mode,
                initial_state_updates,
            ),
            stop_after_recovered_manual=True,
        )

    def _run_single_phase_locked(
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
            self._ensure_telemetry_manifest()
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
            self._ensure_telemetry_manifest()
            self._refresh_run_context(f"manual phase replay {phase_id}")

        phase = phase_id
        guarded_phase = self._guard_constitution_provenance(phase)
        if guarded_phase in TERMINAL_PHASES:
            return SquadResult.from_state(self._state_store.load())
        phase = guarded_phase
        phase = self._guard_spec_lexicon_evidence(phase)
        phase = self._guard_understanding_evidence(phase)

        node = self._graph.get(phase)
        label = node.label or node.id
        if self._skip_phase_if_condition_false(node, manual_phase_run=True):
            return SquadResult.from_state(self._state_store.load())
        self._start_declared_phase_timing(node)
        print(
            _format_phase_dispatch_line(
                node,
                self._graph,
                self._ext_dir,
                suffix="  (manual phase run)",
            ),
            flush=True,
        )

        executor = self._executors.get(node.type)
        try:
            if executor is None:
                result = self._judgment_dispatch(
                    f"Unknown phase type {node.type!r} for phase {phase!r}",
                    node,
                )
            else:
                state = self._state_store.load()
                attempts = state.get("phase_dispatch_counts")
                attempt = (
                    int(attempts.get(phase, 0)) + 1
                    if isinstance(attempts, dict)
                    else 1
                )
                with self._telemetry_provider.dispatch(
                    DispatchContext(
                        phase=phase,
                        agent=str(node.agent or node.type),
                        kind="repair" if attempt > 1 else "phase",
                        attempt=attempt,
                        reason="manual_rerun",
                    )
                ):
                    result = executor.execute(node, self._state_store)
        except ControllerStateContractViolation as exc:
            self._block_after_executor_contract_failure(node, exc)
            return SquadResult.from_state(self._state_store.load())

        snapshot = self._state_store.capture_routing_snapshot(
            expected_phase=node.id
        )
        prepared = self._prepare_phase_result_or_block(
            node,
            result,
            snapshot,
        )
        if prepared is None:
            return SquadResult.from_state(self._state_store.load())
        prepared_result = prepared.as_squad_agent_result()

        blocked_result = self._blocked_executor_reason(
            prepared_result,
            prepared.control_updates,
        )
        if blocked_result:
            self._block_after_executor_failure(
                phase,
                blocked_result,
                prepared_result,
                snapshot=snapshot,
            )
            return SquadResult.from_state(self._state_store.load())

        prepared_publication: PreparedSquadPublication | None = None
        try:
            prepared_publication = self._prepare_external_phase_effects(
                prepared_result,
                phase,
                snapshot.state,
                manual_phase_run=True,
            )
        except _ProductInputCommitError as exc:
            product_input_error = exc.reason
            if self._schedule_product_input_mapping_repair(
                phase,
                product_input_error,
                prepared_result,
                snapshot=snapshot,
            ):
                return SquadResult.from_state(self._state_store.load())
            self._block_after_executor_failure(
                phase,
                product_input_error,
                prepared_result,
                snapshot=snapshot,
            )
            return SquadResult.from_state(self._state_store.load())
        except _PhaseAReadinessCommitError as exc:
            self._block_after_phase_a_readiness_failure(
                exc.readiness,
                snapshot=snapshot,
            )
            return SquadResult.from_state(self._state_store.load())

        routing_updates = self._planned_phase_a_publication_updates(
            phase,
            snapshot.state,
        )
        if prepared_publication is not None:
            routing_updates[PENDING_EXTERNAL_PUBLICATION_KEY] = (
                prepared_publication.marker.to_dict()
            )
        decision = self._construct_routing_decision_or_block(
            node,
            prepared,
            snapshot,
            additional_state_updates=routing_updates,
            manual_phase_run=True,
        )
        if decision is None:
            self._discard_publication_without_authority(
                prepared_publication,
            )
            return SquadResult.from_state(self._state_store.load())
        next_phase = decision.to_phase

        receipt = self._advance_prepared_result_or_block(
            node,
            decision,
            prepared_publication=prepared_publication,
        )
        if receipt is None:
            return SquadResult.from_state(self._state_store.load())
        print(f"[squad] ✓ {node.id}  → {next_phase}  (stopped)", flush=True)
        return SquadResult.from_state(self._state_store.load())

    def _skip_phase_if_condition_false(
        self,
        node: PhaseNode,
        *,
        manual_phase_run: bool = False,
    ) -> bool:
        """Apply node-level phase conditions before dispatching an agent."""
        condition = (node.condition or "").strip()
        if not condition:
            return False

        snapshot = self._state_store.capture_routing_snapshot(
            expected_phase=node.id
        )
        state = snapshot.state
        evaluation = self._evaluator.evaluate(condition, state)
        if evaluation is True:
            return False
        if evaluation is None:
            state["phase"] = PHASE_TERMINAL_BLOCKED
            state["status"] = "blocked"
            state["blocked_reason"] = f"unresolvable phase condition {condition!r}"
            self._state_store.save(state)
            print(
                f"[squad] ✗ {node.id} phase condition {condition!r} is unresolvable",
                flush=True,
            )
            return True

        action = ""
        if isinstance(node.on_greenfield, dict):
            action = str(node.on_greenfield.get("action") or "")
        if state.get("mode") == "greenfield" and action == "skip_agent_proceed_to_next":
            result = SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "output_files": [],
                    "state_updates": {},
                    "journal_entries": [],
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
                cost_usd=0.0,
            )
            prepared = self._prepare_phase_result_or_block(
                node,
                result,
                snapshot,
            )
            if prepared is None:
                return True
            decision = self._construct_routing_decision_or_block(
                node,
                prepared,
                snapshot,
                manual_phase_run=manual_phase_run,
                conditional_skip=True,
            )
            if decision is None:
                return True
            next_phase = decision.to_phase
            receipt = self._advance_prepared_result_or_block(
                node,
                decision,
            )
            if receipt is None:
                return True
            suffix = "  (stopped)" if manual_phase_run else ""
            print(
                f"[squad] skipped {node.id}  ({condition} false) -> {next_phase}{suffix}",
                flush=True,
            )
            return True

        state["phase"] = PHASE_TERMINAL_BLOCKED
        state["status"] = "blocked"
        state["blocked_reason"] = f"phase condition {condition!r} evaluated false"
        self._state_store.save(state)
        print(
            f"[squad] ✗ {node.id} phase condition {condition!r} evaluated false",
            flush=True,
        )
        return True

    def _absolute_project_path(self, value: str | Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self._project_root / path
        return Path(os.path.abspath(path))

    def _project_relative_target(self, path: Path) -> Path:
        root = Path(os.path.abspath(self._project_root))
        candidate = Path(os.path.abspath(path))
        try:
            relative = candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("publication target is outside the project") from exc
        if not relative.parts:
            raise ValueError("publication target must be a file")
        return relative

    @staticmethod
    def _lstat_or_none(path: Path) -> os.stat_result | None:
        try:
            return os.lstat(path)
        except FileNotFoundError:
            return None

    def _read_project_regular_file(self, path: Path) -> bytes | None:
        """Read an optional controller source without following symlinks."""
        absolute = Path(os.path.abspath(path))
        self._project_relative_target(absolute)
        try:
            resolved = absolute.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise OSError(
                "controller publication source path cannot be resolved"
            ) from exc
        if resolved != absolute:
            raise OSError(
                "controller publication source has a symbolic-link ancestor"
            )
        metadata = self._lstat_or_none(absolute)
        if metadata is None:
            return None
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
        ):
            raise OSError(
                "controller publication source is not a regular file"
            )
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(absolute, flags)
        except OSError as exc:
            raise OSError(
                "controller publication source cannot be opened safely"
            ) from exc
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino)
                != (metadata.st_dev, metadata.st_ino)
            ):
                raise OSError(
                    "controller publication source changed during validation"
                )
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    @staticmethod
    def _safe_run_id(value: object) -> str:
        run_id = str(value or "unknown")
        candidate = Path(run_id)
        if (
            candidate.is_absolute()
            or candidate.name != run_id
            or candidate.parts != (run_id,)
            or run_id in {".", ".."}
        ):
            raise OSError("run ID is not a safe path component")
        return run_id

    def _controller_tree_files(
        self,
        root: Path,
        *,
        exclude_echelon: bool,
    ) -> frozenset[Path]:
        absolute_root = Path(os.path.abspath(root))
        try:
            resolved_root = root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise OSError(
                "controller publication source is not a real directory"
            ) from exc
        if resolved_root != absolute_root:
            raise OSError(
                "controller publication source has a symbolic-link ancestor"
            )
        metadata = self._lstat_or_none(root)
        if (
            metadata is None
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
        ):
            raise OSError("controller publication source is not a directory")
        files: set[Path] = set()
        for current, directories, filenames in os.walk(
            root,
            topdown=True,
            followlinks=False,
        ):
            current_path = Path(current)
            retained_directories: list[str] = []
            for name in sorted(directories):
                if exclude_echelon and name == ".echelon":
                    continue
                child = current_path / name
                child_metadata = os.lstat(child)
                if (
                    stat.S_ISLNK(child_metadata.st_mode)
                    or not stat.S_ISDIR(child_metadata.st_mode)
                ):
                    raise OSError(
                        "controller publication source contains an unsafe directory"
                    )
                retained_directories.append(name)
            directories[:] = retained_directories
            for name in sorted(filenames):
                child = current_path / name
                child_metadata = os.lstat(child)
                if (
                    stat.S_ISLNK(child_metadata.st_mode)
                    or not stat.S_ISREG(child_metadata.st_mode)
                ):
                    raise OSError(
                        "controller publication source contains an unsafe file"
                    )
                relative = child.relative_to(root)
                if exclude_echelon and ".echelon" in relative.parts:
                    continue
                files.add(relative)
        return frozenset(files)

    def _controller_tree_inventory_sha256(
        self,
        root: Path,
    ) -> str:
        records: list[dict[str, object]] = []
        for relative in sorted(
            self._controller_tree_files(
                root,
                exclude_echelon=True,
            ),
            key=lambda path: path.as_posix(),
        ):
            content = self._read_project_regular_file(root / relative)
            if content is None:
                raise OSError(
                    "controller inventory source changed during read"
                )
            records.append(
                {
                    "path": relative.as_posix(),
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        encoded = json.dumps(
            records,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _phase_a_inventory_digests(
        self,
        state: Mapping[str, object],
    ) -> tuple[str, str] | None:
        detached = dict(state)
        active = self._active_phase_a_spec_dir(detached)
        if active is None or not active.is_dir():
            return None
        published_ref = str(
            detached.get("published_spec_dir") or ""
        ).strip()
        if not published_ref:
            published = self._published_phase_a_spec_dir(
                detached,
                active,
            )
        else:
            published = self._absolute_project_path(published_ref)
        if not published.is_dir():
            return None
        try:
            return (
                self._controller_tree_inventory_sha256(
                    self._absolute_project_path(active)
                ),
                self._controller_tree_inventory_sha256(
                    self._absolute_project_path(published)
                ),
            )
        except OSError:
            return None

    def _copy_controller_tree(
        self,
        source: Path,
        destination: Path,
        *,
        exclude_echelon: bool,
    ) -> frozenset[Path]:
        files = self._controller_tree_files(
            source,
            exclude_echelon=exclude_echelon,
        )
        destination.mkdir(parents=True, exist_ok=True)
        directories_to_copy: list[Path] = []
        for current, directories, _ in os.walk(
            source,
            topdown=True,
            followlinks=False,
        ):
            current_path = Path(current)
            current_relative = current_path.relative_to(source)
            if exclude_echelon and ".echelon" in current_relative.parts:
                directories[:] = []
                continue
            retained: list[str] = []
            for name in sorted(directories):
                relative = (current_path / name).relative_to(source)
                if exclude_echelon and ".echelon" in relative.parts:
                    continue
                retained.append(name)
                directories_to_copy.append(relative)
            directories[:] = retained
        for relative in sorted(
            directories_to_copy,
            key=lambda path: (len(path.parts), path.as_posix()),
        ):
            target = destination / relative
            existing = self._lstat_or_none(target)
            if existing is not None and not stat.S_ISDIR(existing.st_mode):
                if stat.S_ISREG(existing.st_mode):
                    target.unlink()
                else:
                    raise OSError(
                        "virtual publication tree contains an unsafe directory"
                    )
            target.mkdir(parents=True, exist_ok=True)
        for relative in sorted(files):
            target = destination / relative
            existing = self._lstat_or_none(target)
            if existing is not None and stat.S_ISDIR(existing.st_mode):
                shutil.rmtree(target)
            elif existing is not None and (
                stat.S_ISLNK(existing.st_mode)
                or not stat.S_ISREG(existing.st_mode)
            ):
                raise OSError("virtual publication tree contains an unsafe file")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((source / relative).read_bytes())
        return files

    def _add_owned_file_diff(
        self,
        transaction: SquadPublicationTransaction,
        *,
        virtual_root: Path,
        target_root: Path,
        owned_relative_paths: set[Path] | frozenset[Path],
    ) -> int:
        owned_targets = {
            self._project_relative_target(target_root / relative)
            for relative in owned_relative_paths
        }
        operation_count = 0
        for relative in sorted(owned_relative_paths):
            staged = virtual_root / relative
            target = target_root / relative
            target_relative = self._project_relative_target(target)
            staged_metadata = self._lstat_or_none(staged)
            target_metadata = self._lstat_or_none(target)
            if staged_metadata is not None:
                if (
                    stat.S_ISLNK(staged_metadata.st_mode)
                    or not stat.S_ISREG(staged_metadata.st_mode)
                ):
                    raise OSError("staged publication output is not a regular file")
                if (
                    target_metadata is not None
                    and stat.S_ISREG(target_metadata.st_mode)
                    and not stat.S_ISLNK(target_metadata.st_mode)
                    and target.read_bytes() == staged.read_bytes()
                ):
                    continue
                transaction.add_write(
                    target_relative,
                    staged,
                    owned_paths=owned_targets,
                )
                operation_count += 1
                continue
            if target_metadata is None:
                continue
            transaction.add_delete(
                target_relative,
                owned_paths=owned_targets,
            )
            operation_count += 1
        return operation_count

    @staticmethod
    def _discard_uncommitted_publication(
        transaction: SquadPublicationTransaction,
    ) -> None:
        try:
            transaction.seal().discard()
        except Exception:
            # The stage has no state marker and therefore no publication
            # authority. Recovery may clean an unreferenced stage later.
            return

    def _product_effects_requested(
        self,
        result: SquadAgentResult,
        phase: str,
        state: Mapping[str, object],
    ) -> bool:
        payload = result.echelon_result or {}
        updates = (
            payload.get("product_input_updates")
            if isinstance(payload, Mapping)
            else None
        )
        metadata = state.get("product_inputs")
        return bool(updates) or (
            isinstance(metadata, dict)
            and bool(metadata)
            and phase in {"phase3-plan", "phase3-consensus"}
        )

    def _require_run_local_product_inputs(
        self,
        path: Path,
        *,
        staged_path: Path | None = None,
    ) -> None:
        candidate = Path(os.path.abspath(path))
        allowed = {
            Path(os.path.abspath(self._squad_dir / "inputs")),
        }
        if staged_path is not None:
            allowed.add(Path(os.path.abspath(staged_path)))
        if candidate not in allowed:
            raise _ProductInputCommitError(
                "product input evidence directory is not owned by this squad run"
            )

    def _stage_product_input_effects(
        self,
        transaction: SquadPublicationTransaction,
        result: SquadAgentResult,
        phase: str,
        state: Mapping[str, object],
    ) -> tuple[int, dict[str, object]]:
        staged_state = dict(state)
        metadata = staged_state.get("product_inputs")
        if not isinstance(metadata, dict) or not metadata:
            error = self._apply_product_input_updates(result, phase, staged_state)
            if error:
                raise _ProductInputCommitError(error)
            return 0, staged_state

        inputs_ref = str(metadata.get("inputs_dir") or "").strip()
        if not inputs_ref:
            raise _ProductInputCommitError(
                "product input staging path is missing from run state"
            )
        source_inputs = self._absolute_project_path(inputs_ref)
        self._require_run_local_product_inputs(source_inputs)
        virtual_inputs = transaction.build_path(
            Path("work/product-inputs")
        )
        self._copy_controller_tree(
            source_inputs,
            virtual_inputs,
            exclude_echelon=False,
        )

        staged_metadata = dict(metadata)
        original_paths: dict[str, Path] = {}
        staged_paths: dict[str, Path] = {}
        for key in _PRODUCT_INPUT_PATH_KEYS:
            ref = str(metadata.get(key) or "").strip()
            if not ref:
                continue
            original = self._absolute_project_path(ref)
            try:
                relative = original.relative_to(source_inputs)
            except ValueError as exc:
                raise _ProductInputCommitError(
                    "product input metadata path is outside its evidence directory"
                ) from exc
            staged = virtual_inputs / relative
            original_paths[key] = original
            staged_paths[key] = staged
            staged_metadata[key] = str(staged)
        staged_metadata["inputs_dir"] = str(virtual_inputs)
        staged_state["product_inputs"] = staged_metadata

        error = self._apply_product_input_updates(
            result,
            phase,
            staged_state,
            path_overrides=staged_paths,
        )
        if error:
            raise _ProductInputCommitError(error)

        traceability = original_paths.get("traceability")
        if traceability is None:
            raise _ProductInputCommitError(
                "product input traceability path is missing from run state"
            )
        owned_relative = {
            traceability.relative_to(source_inputs),
            traceability.with_suffix(".md").relative_to(source_inputs),
        }
        requirement_context = original_paths.get("requirement_context")
        if requirement_context is not None:
            owned_relative.add(requirement_context.relative_to(source_inputs))
        return (
            self._add_owned_file_diff(
                transaction,
                virtual_root=virtual_inputs,
                target_root=source_inputs,
                owned_relative_paths=owned_relative,
            ),
            staged_state,
        )

    def _manual_publication_spec_dir(
        self,
        state: Mapping[str, object],
    ) -> Path | None:
        spec_ref = str(
            state.get("published_spec_dir") or state.get("spec_dir") or ""
        ).strip()
        if not spec_ref:
            return None
        spec_dir = self._absolute_project_path(spec_ref)
        metadata = self._lstat_or_none(spec_dir)
        if metadata is None:
            return None
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
        ):
            raise OSError("manual publication target is not a directory")
        self._project_relative_target(spec_dir / "ARTIFACTS.md")
        return spec_dir

    def _stage_manual_phase_effects(
        self,
        transaction: SquadPublicationTransaction,
        state: Mapping[str, object],
    ) -> int:
        target = self._manual_publication_spec_dir(state)
        if target is None:
            return 0
        virtual = transaction.build_path(
            Path("work/manual/specs") / target.name
        )
        self._copy_controller_tree(
            target,
            virtual,
            exclude_echelon=True,
        )
        self._publish_manual_phase_artifacts(
            state,
            spec_dir_override=virtual,
            strict=True,
        )
        return self._add_owned_file_diff(
            transaction,
            virtual_root=virtual,
            target_root=target,
            owned_relative_paths={
                Path("constitution.md"),
                Path("ARTIFACTS.md"),
            },
        )

    def _phase_a_preparation_failure(
        self,
        blocker: str,
    ) -> _PhaseAReadinessCommitError:
        return _PhaseAReadinessCommitError(
            PhaseAReadinessResult(
                ready=False,
                blockers=[blocker],
                missing={},
                ready_spec_dir=None,
            )
        )

    def _stage_phase_a_effects(
        self,
        transaction: SquadPublicationTransaction,
        state: Mapping[str, object],
    ) -> tuple[int, PhaseAReadinessResult]:
        detached_state = dict(state)
        active_spec_dir = self._active_phase_a_spec_dir(detached_state)
        if active_spec_dir is None or not active_spec_dir.exists():
            return (
                0,
                validate_phase_a_readiness(
                    detached_state,
                    self._phase_a_readiness_candidate_dirs(detached_state),
                ),
            )
        active_spec_dir = self._absolute_project_path(active_spec_dir)
        self._project_relative_target(active_spec_dir / "spec.md")
        published_spec_dir = self._absolute_project_path(
            self._published_phase_a_spec_dir(
                detached_state,
                active_spec_dir,
            )
        )
        self._project_relative_target(published_spec_dir / "spec.md")
        virtual_spec_dir = transaction.build_path(
            Path("work/phase-a/specs") / published_spec_dir.name
        )
        published_metadata = self._lstat_or_none(published_spec_dir)
        if published_metadata is not None:
            if (
                stat.S_ISLNK(published_metadata.st_mode)
                or not stat.S_ISDIR(published_metadata.st_mode)
            ):
                raise OSError("published Phase A target is not a directory")
            self._copy_controller_tree(
                published_spec_dir,
                virtual_spec_dir,
                exclude_echelon=True,
            )
        else:
            virtual_spec_dir.mkdir(parents=True, exist_ok=True)

        active_spec_files = self._controller_tree_files(
            active_spec_dir,
            exclude_echelon=True,
        )
        self._copy_spec_tree(active_spec_dir, virtual_spec_dir)
        targets = [
            str(value).strip()
            for value in (
                detached_state.get("implementation_targets")
                or getattr(self, "_implementation_targets", [])
            )
            if str(value).strip()
        ]
        if targets:
            write_targets(virtual_spec_dir, targets)

        published_input_files: set[Path] = set()
        metadata = detached_state.get("product_inputs")
        if isinstance(metadata, dict) and metadata:
            inputs_ref = str(metadata.get("inputs_dir") or "").strip()
            if not inputs_ref:
                return (
                    0,
                    PhaseAReadinessResult(
                        ready=False,
                        blockers=[
                            "product input evidence path is missing from run state"
                        ],
                        missing={},
                        ready_spec_dir=None,
                    ),
                )
            source_inputs = self._absolute_project_path(inputs_ref)
            self._require_run_local_product_inputs(
                source_inputs,
                staged_path=transaction.build_path(
                    Path("work/product-inputs")
                ),
            )
            source_input_files = self._controller_tree_files(
                source_inputs,
                exclude_echelon=False,
            )
            published_input_files.update(
                Path("inputs") / path for path in source_input_files
            )
            visible_inputs = published_spec_dir / "inputs"
            if visible_inputs.exists():
                published_input_files.update(
                    Path("inputs") / path
                    for path in self._controller_tree_files(
                        visible_inputs,
                        exclude_echelon=False,
                    )
                )
        input_blockers = self._publish_product_input_evidence(
            virtual_spec_dir,
            detached_state,
        )
        if input_blockers:
            return (
                0,
                PhaseAReadinessResult(
                    ready=False,
                    blockers=input_blockers,
                    missing={},
                    ready_spec_dir=None,
                ),
            )
        self._publish_constitution_snapshot(virtual_spec_dir)
        self._write_phase_a_finalization_outputs(
            virtual_spec_dir,
            detached_state,
            strict=True,
        )
        write_artifact_index(virtual_spec_dir)
        self._write_published_context_metadata(
            virtual_spec_dir,
            str(detached_state.get("run_id") or "").strip(),
            canonical_spec_file=published_spec_dir / "spec.md",
        )

        updated = deepcopy(detached_state)
        updated["published_spec_dir"] = self._repo_relative_or_absolute(
            published_spec_dir
        )
        readiness = validate_phase_a_readiness(
            updated,
            [virtual_spec_dir],
        )
        if not readiness.ready:
            return 0, readiness
        published_kb_files = {
            path
            for path in _PHASE_A_KB_REPORT_FILES
            if (virtual_spec_dir / path).is_file()
        }
        owned_relative = (
            set(active_spec_files)
            | published_input_files
            | set(_PHASE_A_GENERATED_FILES)
            | published_kb_files
        )
        return (
            self._add_owned_file_diff(
                transaction,
                virtual_root=virtual_spec_dir,
                target_root=published_spec_dir,
                owned_relative_paths=owned_relative,
            ),
            readiness,
        )

    def _prepare_external_phase_effects(
        self,
        result: SquadAgentResult,
        phase: str,
        state: Mapping[str, object],
        *,
        manual_phase_run: bool,
    ) -> PreparedSquadPublication | None:
        needs_product = self._product_effects_requested(result, phase, state)
        needs_phase_a = phase == "phase4-document"
        needs_manual = manual_phase_run and not needs_phase_a
        if not (needs_product or needs_phase_a or needs_manual):
            return None

        transaction = SquadPublicationTransaction.begin(
            self._project_root,
            self._squad_dir,
            uuid.uuid4().hex,
        )
        operation_count = 0
        staged_state = dict(state)
        try:
            if needs_product:
                product_operations, staged_state = (
                    self._stage_product_input_effects(
                        transaction,
                        result,
                        phase,
                        staged_state,
                    )
                )
                operation_count += product_operations
            if needs_phase_a:
                phase_a_operations, readiness = self._stage_phase_a_effects(
                    transaction,
                    staged_state,
                )
                if not readiness.ready:
                    raise _PhaseAReadinessCommitError(readiness)
                operation_count += phase_a_operations
            elif needs_manual:
                operation_count += self._stage_manual_phase_effects(
                    transaction,
                    staged_state,
                )
            if operation_count == 0:
                self._discard_uncommitted_publication(transaction)
                return None
            return transaction.seal()
        except (_ProductInputCommitError, _PhaseAReadinessCommitError):
            self._discard_uncommitted_publication(transaction)
            raise
        except (Exception, SystemExit) as exc:
            self._discard_uncommitted_publication(transaction)
            if needs_phase_a or needs_manual:
                raise self._phase_a_preparation_failure(
                    "failed to stage controller-owned spec artifacts"
                ) from exc
            raise _ProductInputCommitError(
                "invalid product input updates: staged preparation failed"
            ) from exc

    def _publish_manual_phase_artifacts(
        self,
        state: Mapping[str, object] | None = None,
        *,
        spec_dir_override: Path | None = None,
        strict: bool = False,
    ) -> None:
        """Refresh project-visible spec metadata after a targeted phase run."""
        state = (
            dict(state)
            if state is not None
            else self._state_store.load()
        )
        spec_dir = spec_dir_override
        if spec_dir is None:
            spec_ref = str(
                state.get("published_spec_dir") or state.get("spec_dir") or ""
            ).strip()
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
            if strict:
                raise
            logger.warning("Could not refresh artifact index for %s", spec_dir)

    def _planned_phase_a_publication_updates(
        self,
        phase: str,
        state: Mapping[str, object],
    ) -> dict[str, object]:
        """Derive publication identity without performing publication writes."""
        if phase != "phase4-document":
            return {}
        detached_state = dict(state)
        active_spec_dir = self._active_phase_a_spec_dir(detached_state)
        if active_spec_dir is None:
            return {}
        published_spec_dir = self._published_phase_a_spec_dir(
            detached_state,
            active_spec_dir,
        )
        return {
            "published_spec_dir": self._repo_relative_or_absolute(
                published_spec_dir
            )
        }

    def _publish_terminal_phase_a_artifacts_if_available(
        self,
    ) -> PhaseAReadinessResult | None:
        """Reconcile terminal Phase A through an explicit completion intent."""
        state = self._state_store.load()
        active_spec_dir = self._active_phase_a_spec_dir(state)
        if active_spec_dir is None or not active_spec_dir.exists():
            return None
        current_digests = self._phase_a_inventory_digests(state)
        if (
            current_digests is not None
            and self._terminal_inventory_provenance_matches(
                state,
                current_digests,
            )
        ):
            published_ref = str(
                state.get("published_spec_dir") or ""
            ).strip()
            if published_ref:
                return validate_phase_a_readiness(
                    state,
                    [self._absolute_project_path(published_ref)],
                )
        snapshot = self._state_store.capture_routing_snapshot(
            expected_phase=str(state.get("phase") or "")
        )
        terminal_result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        try:
            prepared = self._prepare_external_phase_effects(
                terminal_result,
                "phase4-document",
                snapshot.state,
                manual_phase_run=False,
            )
        except _PhaseAReadinessCommitError as exc:
            return exc.readiness
        except _ProductInputCommitError as exc:
            return PhaseAReadinessResult(
                ready=False,
                blockers=[exc.reason],
                missing={},
                ready_spec_dir=None,
            )
        planned_updates = self._planned_phase_a_publication_updates(
            "phase4-document",
            snapshot.state,
        )
        publication_marker = (
            prepared.marker.to_dict()
            if prepared is not None
            else None
        )
        completion = self._prepare_controller_completion(
            from_phase=snapshot.phase,
            to_phase=snapshot.phase,
            snapshot=snapshot,
            manual_phase_run=False,
            conditional_skip=False,
            record_completion=True,
            publication_marker=publication_marker,
            origin="terminal",
        )
        try:
            self._state_store.begin_terminal_controller_completion(
                completion,
                snapshot=snapshot,
                state_updates=planned_updates,
            )
        except StateAdvanceError:
            self._discard_publication_without_authority(prepared)
            self._discard_controller_completion_without_authority(
                completion.marker.to_dict()
            )
            return PhaseAReadinessResult(
                ready=False,
                blockers=[
                    "failed to commit terminal completion authority"
                ],
                missing={},
                ready_spec_dir=None,
            )
        recovery = self._drain_pending_controller_completion()
        if (
            not recovery.recovered
            or recovery.completion_id
            != completion.marker.completion_id
        ):
            return PhaseAReadinessResult(
                ready=False,
                blockers=["terminal completion remains pending"],
                missing={},
                ready_spec_dir=None,
            )
        if prepared is not None:
            self._phase_a_published_this_run = True
        published_ref = str(
            self._state_store.load().get("published_spec_dir") or ""
        ).strip()
        if not published_ref:
            return PhaseAReadinessResult(
                ready=False,
                blockers=["published Phase A directory is missing from state"],
                missing={},
                ready_spec_dir=None,
            )
        published_spec_dir = self._absolute_project_path(published_ref)
        return validate_phase_a_readiness(
            self._state_store.load(),
            [published_spec_dir],
        )

    @staticmethod
    def _terminal_inventory_provenance_matches(
        state: Mapping[str, object],
        digests: tuple[str, str],
    ) -> bool:
        active_digest, published_digest = digests
        dispatch = state.get("last_dispatch")
        routed_match = (
            isinstance(dispatch, Mapping)
            and dispatch.get("phase_id") == "phase4-document"
            and dispatch.get("post_dispatch_complete") is True
            and state.get("phase_a_active_source_sha256")
            == active_digest
            and state.get("phase_a_published_postimage_sha256")
            == published_digest
        )
        terminal = state.get("last_terminal_completion")
        terminal_match = (
            isinstance(terminal, Mapping)
            and terminal.get("terminal_phase") == state.get("phase")
            and terminal.get("phase_a_active_source_sha256")
            == active_digest
            and terminal.get(
                "phase_a_published_postimage_sha256"
            )
            == published_digest
        )
        return routed_match or terminal_match

    def _phase_a_readiness_candidate_dirs(
        self,
        state: Mapping[str, object] | None = None,
    ) -> list[Path]:
        state = dict(state) if state is not None else self._state_store.load()
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

    def _publish_phase_a_artifacts_for_build(
        self,
        state: Mapping[str, object] | None = None,
    ) -> PhaseAReadinessResult:
        state = dict(state) if state is not None else self._state_store.load()
        self._materialize_implementation_targets(state)
        active_spec_dir = self._active_phase_a_spec_dir(state)
        if active_spec_dir is None or not active_spec_dir.exists():
            return validate_phase_a_readiness(
                state,
                self._phase_a_readiness_candidate_dirs(state),
            )

        published_spec_dir = self._published_phase_a_spec_dir(state, active_spec_dir)
        try:
            if active_spec_dir.resolve() != published_spec_dir.resolve():
                self._copy_spec_tree(active_spec_dir, published_spec_dir)
            else:
                published_spec_dir.mkdir(parents=True, exist_ok=True)
            input_blockers = self._publish_product_input_evidence(published_spec_dir, state)
            if input_blockers:
                return PhaseAReadinessResult(
                    ready=False,
                    blockers=input_blockers,
                    missing={},
                    ready_spec_dir=None,
                )
            self._publish_constitution_snapshot(published_spec_dir)
            self._write_phase_a_finalization_outputs(published_spec_dir, state)
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

        updated = deepcopy(state)
        updated["published_spec_dir"] = self._repo_relative_or_absolute(published_spec_dir)
        self._phase_a_published_this_run = True
        return validate_phase_a_readiness(updated, [published_spec_dir])

    def _publish_product_input_evidence(self, published_spec_dir: Path, state: dict) -> list[str]:
        """Publish safe run-local evidence and enforce the normative input chain."""
        metadata = state.get("product_inputs")
        if not isinstance(metadata, dict) or not metadata:
            return []
        inputs_ref = str(metadata.get("inputs_dir") or "").strip()
        if not inputs_ref:
            return ["product input evidence path is missing from run state"]
        source = Path(inputs_ref)
        if not source.is_absolute():
            source = self._project_root / source
        if not source.is_dir():
            return [f"product input evidence directory is missing: {source}"]
        destination = published_spec_dir / "inputs"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
        from echelon.product_inputs import validate_product_input_traceability
        targets = [
            str(value).strip()
            for value in state.get("implementation_targets", [])
            if str(value).strip()
        ]
        return validate_product_input_traceability(published_spec_dir, targets)

    def _write_phase_a_finalization_outputs(
        self,
        published_spec_dir: Path,
        state: dict,
        *,
        strict: bool = False,
    ) -> None:
        run_id = str(state.get("run_id") or "unknown")
        try:
            from echelon.kb_proposals import publish_kb_reports

            run_id = self._safe_run_id(run_id)
            run_dir = self._project_root / "runs" / run_id
            expected_reports = (
                (
                    run_dir / "kb-apply-report.yaml",
                    published_spec_dir / "kb/kb-apply-report.yaml",
                ),
                (
                    run_dir / "kb-usage.yaml",
                    published_spec_dir / "kb/kb-usage-summary.yaml",
                ),
            )
            expected_states = tuple(
                (
                    source,
                    target,
                    self._read_project_regular_file(source),
                    self._read_project_regular_file(target),
                )
                for source, target in expected_reports
            )
            publish_kb_reports(self._project_root, run_id, published_spec_dir)
            if strict:
                for source, target, source_before, target_before in expected_states:
                    source_after = self._read_project_regular_file(source)
                    if source_after != source_before:
                        raise OSError(
                            "KB publication source changed during staging"
                        )
                    target_after = self._read_project_regular_file(target)
                    expected_target = (
                        source_before
                        if source_before is not None
                        else target_before
                    )
                    if target_after != expected_target:
                        raise OSError(
                            "KB publication did not produce its exact staged output"
                        )
        except Exception as exc:  # noqa: BLE001
            if strict:
                raise
            logger.warning("Could not publish KB provenance reports: %s", exc)
        spec_status = str(state.get("spec_status") or "planned")
        constitution_hash = self._constitution_hash(published_spec_dir / "constitution.md")
        append_phase_a_run(
            published_spec_dir,
            run_id=run_id,
            spec_status=spec_status,
            constitution_hash=constitution_hash,
        )
        self._write_squad_report(published_spec_dir, state)

    def _constitution_hash(self, constitution_path: Path) -> str:
        if not constitution_path.exists():
            return ""
        return hashlib.sha256(constitution_path.read_bytes()).hexdigest()

    def _write_squad_report(self, published_spec_dir: Path, state: dict) -> None:
        artifact_count = sum(
            1
            for path in published_spec_dir.rglob("*")
            if path.is_file() and ".git" not in path.parts
        )
        quality_scores = state.get("quality_scores") or []
        final_quality = quality_scores[-1] if quality_scores else {}
        lines = [
            "# Squad Report",
            "",
            "## Run",
            "",
            f"- Run ID: {state.get('run_id') or 'unknown'}",
            f"- Spec ID: {state.get('spec_id') or published_spec_dir.name}",
            f"- Mode: {state.get('mode') or 'unknown'}",
            f"- Autonomy: {state.get('autonomy_mode') or 'unknown'}",
            f"- Spec status: {state.get('spec_status') or 'planned'}",
            "",
            "## Final Quality",
            "",
            f"- WHY pass: {final_quality.get('pass', 'unknown')}",
            f"- Overall: {final_quality.get('overall', 'n/a')}",
            "",
            "## Handoff",
            "",
            f"- Artifacts: {artifact_count} files in `{published_spec_dir.name}/`",
            "- Ready for: `echelon delivery run <spec-id>`",
            "- Application source files modified by Phase A: none",
            "",
        ]
        (published_spec_dir / "squad-report.md").write_text(
            "\n".join(lines),
            encoding="utf-8",
        )

    def _publish_constitution_snapshot(self, published_spec_dir: Path) -> None:
        """Copy the project constitution into the published spec build inputs."""
        source = self._project_root / ".specify" / "memory" / "constitution.md"
        target = published_spec_dir / "constitution.md"
        content = self._read_project_regular_file(source)
        if content is not None:
            target.write_bytes(content)

    def _refresh_published_context_metadata(
        self,
        published_spec_dir: Path,
        run_id: str,
    ) -> None:
        metadata = self._write_published_context_metadata(
            published_spec_dir,
            run_id,
        )
        if metadata is None:
            return
        self._mine_published_spec_best_effort(
            published_spec_dir,
            published_spec_dir / "spec.md",
            run_id,
            metadata,
        )

    def _mine_published_context_after_publication(self) -> None:
        """Mine canonical metadata only after durable marker clearance."""
        state = self._state_store.load()
        published_ref = str(state.get("published_spec_dir") or "").strip()
        if not published_ref:
            return
        published_spec_dir = self._absolute_project_path(published_ref)
        spec_file = published_spec_dir / "spec.md"
        if not spec_file.is_file():
            return
        try:
            from echelon.context_metadata import read_feature_metadata

            metadata = read_feature_metadata(published_spec_dir)
        except Exception:
            return
        if metadata is None:
            return
        self._mine_published_spec_best_effort(
            published_spec_dir,
            spec_file,
            str(state.get("run_id") or ""),
            metadata,
        )

    def _write_published_context_metadata(
        self,
        published_spec_dir: Path,
        run_id: str,
        *,
        canonical_spec_file: Path | None = None,
    ) -> object | None:
        spec_file = published_spec_dir / "spec.md"
        if not spec_file.exists():
            return None

        from echelon.context_metadata import FeatureMetadata, write_feature_metadata

        metadata = FeatureMetadata.from_spec_dir(
            published_spec_dir,
            run_id=run_id or None,
        )
        if canonical_spec_file is not None:
            canonical_artifact_path = self._repo_relative_or_absolute(
                canonical_spec_file
            )
            metadata = replace(
                metadata,
                requirements=[
                    replace(
                        requirement,
                        artifact_path=canonical_artifact_path,
                    )
                    for requirement in metadata.requirements
                ],
            )
        write_feature_metadata(published_spec_dir, metadata)
        return metadata

    def _mine_published_spec_best_effort(
        self,
        published_spec_dir: Path,
        spec_file: Path,
        run_id: str,
        metadata: object,
    ) -> str:
        try:
            from codegen.memory.context import MemPalaceContext
            from codegen.memory.requirements_miner import RequirementsMiner
        except Exception:
            return "unavailable"

        try:
            content = spec_file.read_bytes()
            spec_sha256 = hashlib.sha256(content).hexdigest()
            artifact_metadata = self._canonical_spec_artifact_metadata(
                spec_file,
                metadata,
                f"sha256:{spec_sha256}",
            )
        except (Exception, SystemExit):
            return "failed"

        try:
            ctx = MemPalaceContext.from_project(self._project_root, run_id=run_id)
            miner = RequirementsMiner(ctx, project_dir=self._project_root)
        except (Exception, SystemExit):
            return "unavailable"
        try:
            source = str(artifact_metadata["artifact_path"])
            result = miner.mine_canonical_bytes(
                content,
                source=source,
                artifact_metadata=artifact_metadata,
            )
            if (
                spec_file.read_bytes() != content
                or hashlib.sha256(content).hexdigest() != spec_sha256
            ):
                return "failed"
        except (Exception, SystemExit):
            return "failed"
        failed = getattr(result, "failed", None)
        unavailable = getattr(result, "unavailable", None)
        written = getattr(result, "written", None)
        already_present = getattr(result, "already_present", None)
        if any(
            type(value) is not int or value < 0
            for value in (
                failed,
                unavailable,
                written,
                already_present,
            )
        ):
            return "failed"
        if failed:
            return "failed"
        if unavailable:
            return "unavailable" if not written and not already_present else "failed"
        if written:
            return "written"
        return "already_present"

    def _canonical_spec_artifact_metadata(
        self,
        spec_file: Path,
        metadata: object,
        spec_hash: str,
    ) -> dict[str, object]:
        try:
            artifact_path = spec_file.relative_to(self._project_root).as_posix()
        except ValueError as exc:
            raise ValueError(
                "canonical spec must be inside the project"
            ) from exc

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

    def _checkpoint_successful_phase(self, phase: str, next_phase: str) -> bool:
        state = self._state_store.load()
        spec_dir = self._active_phase_a_spec_dir(state)
        if spec_dir is None or not spec_dir.exists():
            return True
        additional_spec_dirs: tuple[Path, ...] = ()
        additional_owned_paths: tuple[Path, ...] = ()
        if phase == "phase4-document" and next_phase in TERMINAL_PHASES:
            published_spec_dir = self._published_phase_a_spec_dir(state, spec_dir)
            if (
                published_spec_dir.exists()
                and published_spec_dir.resolve() != spec_dir.resolve()
            ):
                additional_spec_dirs = (published_spec_dir,)
            additional_owned_paths = accepted_kb_target_paths(
                self._project_root,
                str(state.get("run_id") or ""),
            )
        try:
            create_phase_checkpoint(
                project_root=self._project_root,
                spec_dir=spec_dir,
                phase=phase,
                next_phase=next_phase,
                run_id=str(state.get("run_id") or ""),
                spec_id=_checkpoint_spec_id_from_state(state, spec_dir),
                additional_spec_dirs=additional_spec_dirs,
                additional_owned_paths=additional_owned_paths,
            )
        except Exception as exc:
            logger.error("Could not create required phase checkpoint for %s: %s", phase, exc)
            blocked = self._state_store.load()
            blocked["status"] = "blocked"
            blocked["phase"] = PHASE_TERMINAL_BLOCKED
            blocked["blocked_reason"] = f"phase_checkpoint_failed: {phase}: {exc}"
            self._state_store.save(blocked)
            return False
        return True

    def _materialize_implementation_targets(
        self,
        state: Mapping[str, object] | None = None,
    ) -> None:
        """Write authoritative run targets once an active spec exists."""
        state = dict(state) if state is not None else self._state_store.load()
        targets = [
            str(value).strip()
            for value in (
                state.get("implementation_targets")
                or getattr(self, "_implementation_targets", [])
            )
            if str(value).strip()
        ]
        if not targets:
            return
        spec_dir = self._active_phase_a_spec_dir(state)
        if (
            spec_dir is None
            or not spec_dir.exists()
            or not (spec_dir / "spec.md").is_file()
        ):
            return
        try:
            write_targets(spec_dir, targets)
        except (OSError, ValueError) as exc:
            logger.warning("Could not materialize implementation targets: %s", exc)

    def _apply_product_input_updates(
        self,
        result: SquadAgentResult,
        phase: str,
        state: Mapping[str, object],
        *,
        path_overrides: Mapping[str, Path] | None = None,
    ) -> str | None:
        """Validate and persist agent proposals through the controller-owned ledger."""
        payload = result.echelon_result or {}
        updates = payload.get("product_input_updates")
        state = dict(state)
        metadata = state.get("product_inputs")
        if not isinstance(metadata, dict) or not metadata:
            return "product_input_updates received without declared product inputs" if updates else None
        if not updates and not (
            phase in {"phase3-plan", "phase3-consensus"}
        ):
            return None
        traceability_override = (
            path_overrides.get("traceability")
            if path_overrides is not None
            else None
        )
        traceability_ref = str(metadata.get("traceability") or "").strip()
        if traceability_override is None and not traceability_ref:
            return "product input traceability path is missing from run state"
        traceability_path = (
            Path(traceability_override)
            if traceability_override is not None
            else Path(traceability_ref)
        )
        if not traceability_path.is_absolute():
            traceability_path = self._project_root / traceability_path
        catalog_override = (
            path_overrides.get("catalog")
            if path_overrides is not None
            else None
        )
        catalog_ref = str(metadata.get("catalog") or "").strip()
        catalog_path = (
            Path(catalog_override)
            if catalog_override is not None
            else (Path(catalog_ref) if catalog_ref else None)
        )
        if catalog_path is not None and not catalog_path.is_absolute():
            catalog_path = self._project_root / catalog_path
        active_spec_dir = self._active_phase_a_spec_dir(state)
        enforce_direct_task_mappings = phase in {"phase3-plan", "phase3-consensus"}
        tasks_path = active_spec_dir / "tasks.md" if enforce_direct_task_mappings and active_spec_dir else None
        targets = [
            str(value).strip()
            for value in state.get("implementation_targets", [])
            if str(value).strip()
        ]
        try:
            from echelon.product_inputs import (
                ProductInputError,
                apply_product_input_updates,
                normalize_context_only_product_input_updates,
                repair_product_input_structural_units,
                refresh_requirement_context_from_catalog,
                validate_product_input_traceability_paths,
            )
            if catalog_path is not None:
                repair_product_input_structural_units(
                    traceability_path,
                    catalog_path,
                    apply=True,
                )
                requirement_context_override = (
                    path_overrides.get("requirement_context")
                    if path_overrides is not None
                    else None
                )
                requirement_context_ref = str(
                    metadata.get("requirement_context") or ""
                ).strip()
                if (
                    requirement_context_override is not None
                    or requirement_context_ref
                ):
                    requirement_context_path = (
                        Path(requirement_context_override)
                        if requirement_context_override is not None
                        else Path(requirement_context_ref)
                    )
                    if not requirement_context_path.is_absolute():
                        requirement_context_path = self._project_root / requirement_context_path
                    refresh_requirement_context_from_catalog(catalog_path, requirement_context_path)
            normalized_updates = updates
            if updates and catalog_path is not None:
                normalized_updates, _ = normalize_context_only_product_input_updates(
                    updates,
                    catalog_path,
                )
            if normalized_updates:
                apply_product_input_updates(
                    traceability_path,
                    normalized_updates,
                    tasks_path=tasks_path,
                    declared_targets=targets,
                )
            elif tasks_path is not None:
                blockers = validate_product_input_traceability_paths(
                    traceability_path,
                    tasks_path,
                    targets,
                )
                if blockers:
                    return "invalid product input task mappings: " + "; ".join(blockers)
        except (OSError, ProductInputError) as exc:
            return f"invalid product input updates: {exc}"
        return None

    def _schedule_product_input_mapping_repair(
        self,
        phase: str,
        error: str,
        result: SquadAgentResult | None = None,
        *,
        snapshot: RoutingStateSnapshot,
    ) -> bool:
        """Re-dispatch PLAN with exact unresolved product-input evidence.

        Product-input mappings are authored by ORCHESTRATOR, not inferred by the
        controller.  A missing/invalid update therefore gets a bounded repair
        pass with the ledger blockers injected into its prompt; only exhaustion
        becomes a terminal block.
        """
        if phase not in {"phase3-plan", "phase3-consensus"}:
            return False
        prefixes = (
            "invalid product input task mappings:",
            "invalid product input updates:",
        )
        if not error.startswith(prefixes):
            return False

        state = snapshot.state
        existing_repair = state.get("product_input_mapping_repair")
        protocol_version = (
            existing_repair.get("protocol_version")
            if isinstance(existing_repair, dict)
            else None
        )
        attempts = state.get("product_input_mapping_repair_attempts", 0)
        attempts = attempts if isinstance(attempts, int) else 0
        # A repair protocol upgrade carries strictly more deterministic evidence
        # than the prior prompt.  Give interrupted historical runs a fresh,
        # bounded repair budget instead of preserving a spent, weaker loop.
        protocol_upgraded = (
            isinstance(existing_repair, dict)
            and protocol_version != PRODUCT_INPUT_MAPPING_REPAIR_PROTOCOL_VERSION
        )
        if protocol_upgraded:
            attempts = 0
            dispatch_counts = state.get("phase_dispatch_counts")
            if isinstance(dispatch_counts, dict):
                dispatch_counts[phase] = 0
        if attempts >= MAX_PRODUCT_INPUT_MAPPING_REPAIRS:
            return False

        detail = error.split(":", 1)[1].strip() if ":" in error else error
        blockers = [item.strip() for item in detail.split(";") if item.strip()]
        hints: dict[str, object] = {}
        payload = result.echelon_result if result is not None else None
        updates = payload.get("product_input_updates") if isinstance(payload, dict) else None
        active_spec_dir = self._active_phase_a_spec_dir(state)
        if isinstance(updates, list) and active_spec_dir is not None:
            try:
                from echelon.product_inputs import build_product_input_mapping_repair_hints

                hints = build_product_input_mapping_repair_hints(
                    updates,
                    active_spec_dir / "tasks.md",
                    [
                        str(value).strip()
                        for value in state.get("implementation_targets", [])
                        if str(value).strip()
                    ],
                )
            except (OSError, ValueError) as exc:
                logger.warning("Could not construct product-input repair hints: %s", exc)
        state["product_input_mapping_repair_attempts"] = attempts + 1
        state["product_input_mapping_repair"] = {
            "attempt": attempts + 1,
            "blockers": blockers,
            "protocol_version": PRODUCT_INPUT_MAPPING_REPAIR_PROTOCOL_VERSION,
            **hints,
        }
        state["phase"] = phase
        state["status"] = "running"
        state["blocked_reason"] = None
        if not self._state_store.commit_routing_snapshot_state(
            snapshot,
            state,
        ):
            return False
        print(
            f"[squad] ~ {phase} product-input mapping repair "
            f"({attempts + 1}/{MAX_PRODUCT_INPUT_MAPPING_REPAIRS})",
            flush=True,
        )
        return True

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
        runtime_metadata = destination / ".echelon"
        if runtime_metadata.is_dir():
            shutil.rmtree(runtime_metadata)
        elif runtime_metadata.exists():
            runtime_metadata.unlink()
        self._copy_controller_tree(
            source,
            destination,
            exclude_echelon=True,
        )

    def _repo_relative_or_absolute(self, path: Path) -> str:
        try:
            return str(path.relative_to(self._project_root))
        except ValueError:
            return str(path)

    def _block_after_phase_a_readiness_failure(
        self,
        readiness: PhaseAReadinessResult,
        *,
        snapshot: RoutingStateSnapshot | None = None,
    ) -> bool:
        state = (
            snapshot.state
            if snapshot is not None
            else self._state_store.load()
        )
        state["phase"] = PHASE_TERMINAL_BLOCKED
        state["status"] = "blocked"
        state["blocked_reason"] = "phase_a_readiness_failed"
        state["phase_a_readiness_blockers"] = readiness.blockers
        persisted = (
            self._state_store.commit_routing_snapshot_state(
                snapshot,
                state,
            )
            if snapshot is not None
            else (self._state_store.save(state) is None)
        )
        if not persisted:
            return False
        self._record_blocker_event("phase4-document", "phase_a_readiness_failed")
        print(
            "[squad] ✗ phase4-document blocked: Phase A readiness failed "
            "(build-input artifacts incomplete)",
            flush=True,
        )
        return True

    def _blocked_executor_reason(
        self,
        result: SquadAgentResult,
        control_updates: Mapping[str, object] | None = None,
    ) -> str | None:
        if result.provider_limit_message:
            return "provider_session_limit"
        if result.echelon_result is None:
            return "missing_echelon_result"
        if result.timed_out:
            return "agent_timeout"
        if result.exit_code != 0:
            return f"agent_exit_code_{result.exit_code}"
        if (result.verdict or "").upper() == "BLOCKED":
            explicit_reason = (
                (control_updates or {}).get("blocked_reason")
                or (result.state_updates or {}).get("blocked_reason")
            )
            if isinstance(explicit_reason, str) and explicit_reason.strip():
                return explicit_reason.strip()
            return "agent_blocked"
        return None

    def _block_after_executor_failure(
        self,
        phase: str,
        reason: str,
        result: SquadAgentResult,
        *,
        snapshot: RoutingStateSnapshot,
    ) -> bool:
        from datetime import datetime, timezone

        state = snapshot.state
        if phase == "phase1-what":
            self._preserve_cartographer_spec_context(state)
        retryable_analysis = self._is_deterministic_understanding_phase(phase)
        state["phase"] = phase if retryable_analysis else PHASE_TERMINAL_BLOCKED
        state["status"] = "blocked"
        state["blocked_reason"] = reason
        if retryable_analysis:
            node = self._graph.get(phase)
            for key in node.controller_state_update_keys:
                if key in (result.state_updates or {}) and key != "blocked_reason":
                    state[key] = result.state_updates[key]
        if reason == "provider_session_limit":
            state["provider_limit_message"] = result.provider_limit_message
            if result.echelon_result is None:
                state["blocked_context"] = "missing_echelon_result"
        else:
            state.pop("provider_limit_message", None)
            state.pop("blocked_context", None)
        state["last_dispatch"] = {
            "phase_id": phase,
            "verdict": result.verdict,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        if not self._state_store.commit_routing_snapshot_state(
            snapshot,
            state,
        ):
            return False
        self._record_blocker_event(phase, reason)
        detail = (
            "retryable deterministic phase"
            if retryable_analysis
            else "phase not marked complete"
        )
        if reason == "provider_session_limit":
            detail = f"missing_echelon_result; provider: {result.provider_limit_message}"
        print(f"[squad] ✗ {phase} blocked: {reason} ({detail})", flush=True)
        return True

    def _record_blocker_event(self, phase: str, reason: str) -> None:
        from datetime import datetime, timezone

        try:
            self._telemetry_store.append_event(
                {
                    "schema_version": 1,
                    "type": "blocker",
                    "trace_id": self._telemetry_store.trace_id,
                    "phase": phase,
                    "reason": reason,
                    "event_time": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception:
            logger.warning("Could not persist blocker lifecycle event", exc_info=True)

    def _preserve_cartographer_spec_context(self, state: dict) -> None:
        """Record an existing CARTOGRAPHER spec before blocking a failed dispatch."""
        state.pop("cartographer_resume_existing_spec", None)
        spec_dir_ref = str(state.get("spec_dir") or "").strip()
        if spec_dir_ref:
            candidate = Path(spec_dir_ref)
            if not candidate.is_absolute():
                candidate = self._project_root / candidate
            if (candidate / "spec.md").is_file():
                spec_id = str(state.get("spec_id") or candidate.name).strip()
                if spec_id:
                    state["spec_id"] = spec_id
                    published = self._project_root / "specs" / spec_id
                    if published.exists():
                        state["published_spec_dir"] = self._repo_relative_or_absolute(published)
                state["cartographer_resume_existing_spec"] = True
                return

        branch = self._current_git_branch()
        if not branch or not self._is_spec_feature_branch(branch):
            return

        candidate = self._project_root / "specs" / branch
        if not (candidate / "spec.md").is_file():
            return

        state["spec_id"] = state.get("spec_id") or branch
        state["spec_dir"] = self._repo_relative_or_absolute(candidate)
        state["published_spec_dir"] = self._repo_relative_or_absolute(candidate)
        state["feature_branch"] = state.get("feature_branch") or branch
        state["cartographer_resume_existing_spec"] = True

    def _current_git_branch(self) -> str:
        try:
            proc = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(self._project_root),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception:
            return ""
        if proc.returncode != 0:
            return ""
        return (proc.stdout or "").strip()

    def _is_spec_feature_branch(self, branch: str) -> bool:
        return re.match(r"^[0-9]{3,4}-[A-Za-z0-9][A-Za-z0-9._-]*$", branch) is not None

    @staticmethod
    def _canonicalize_judgment_result(
        result: SquadAgentResult,
    ) -> SquadAgentResult:
        """Detach and validate COMMANDER output without mutating live state."""
        candidate = detach_squad_agent_result(result)
        operational_error_path = ""
        if candidate.exit_code != 0:
            operational_error_path = "$.exit_code"
        elif candidate.timed_out:
            operational_error_path = "$.timed_out"
        elif candidate.provider_limit_message:
            operational_error_path = "$.provider_limit_message"
        if operational_error_path:
            raise ControllerStateContractViolation(
                "COMMANDER judgment did not complete successfully",
                contract="judgment",
                json_path=operational_error_path,
                validator="operational_success",
            )
        try:
            outcome = validate_echelon_result_contract(
                candidate.echelon_result,
                JUDGMENT_RESULT_CONTRACT,
            )
        except EchelonResultValidationError as exc:
            raise ControllerStateContractViolation(
                "COMMANDER judgment contract validation failed",
                contract="judgment",
                json_path="$.echelon_result",
                validator="echelon_result",
            ) from exc
        candidate.echelon_result = outcome.result
        candidate.quarantined_state_updates.update(
            outcome.quarantined_state_updates
        )
        return candidate

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

        The spec Lexicon repair guard references the config-namespace key
        `lexicon_gate.spec_enabled`, derived from both the global gate and the
        spec artifact subgate. Merging this block into the eval state lets that
        guard resolve deterministically without changing global enablement used
        by other Lexicon artifacts. Only `lexicon_gate` is merged to keep the
        blast radius constrained. Returns {} when the file is absent or
        unparseable.
        """
        if self._gate_config_cache is not None:
            return self._gate_config_cache
        cfg: dict = {}
        try:
            from harness.config import get_full_resolved_config

            data = get_full_resolved_config(
                self._project_root,
                fallback_config_path=self._ext_dir / "echelon-config.yml",
            )
            block = data.get("lexicon_gate")
            if isinstance(block, dict):
                resolved_gate = dict(block)
                artifacts = resolved_gate.get("artifacts")
                artifacts = artifacts if isinstance(artifacts, dict) else {}
                spec_gate = artifacts.get("spec")
                spec_gate = spec_gate if isinstance(spec_gate, dict) else {}
                resolved_gate["spec_enabled"] = bool(
                    resolved_gate.get("enabled", False)
                    and spec_gate.get("enabled", True) is not False
                )
                cfg = {"lexicon_gate": resolved_gate}
        except Exception:
            cfg = {}
        # The workflow conditions compare each controlled gate's repair count
        # against the configured cap. Missing result fields must mean "zero
        # reported repairs", never an indeterminate condition that falls
        # through to a later phase.
        cfg.setdefault("lexicon_attempts", 0)
        self._gate_config_cache = cfg
        return cfg

    def _lexicon_gate_enrichment(
        self,
        node: PhaseNode,
        state: dict,
        result: SquadAgentResult,
    ) -> tuple[dict[str, object], str | None]:
        """Return spec Lexicon exhaustion updates without mutating state.

        A `warn` policy deliberately permits downstream review with a recorded
        warning.  A `block` policy is a hard delivery contract: after the final
        repair attempt there is no valid transition to a later authoring phase.
        """
        gate_artifacts = {
            "phase1-lexicon": ("spec", "lexicon_pass", "lexicon_attempts"),
        }
        gate_fields = gate_artifacts.get(node.id)
        if gate_fields is None:
            return {}, None
        artifact_name, pass_key, attempts_key = gate_fields
        gate = self._lexicon_gate_config().get("lexicon_gate", {})
        if not isinstance(gate, dict) or not gate.get("enabled", False):
            return {}, None
        artifacts = gate.get("artifacts", {})
        artifact_gate = artifacts.get(artifact_name, {}) if isinstance(artifacts, dict) else {}
        if not isinstance(artifact_gate, dict) or not artifact_gate.get("enabled", False):
            return {}, None
        try:
            repair_cap = int(gate.get("max_repair_attempts", 3))
        except (TypeError, ValueError):
            repair_cap = 3
        reported_attempts = result.state_updates.get(attempts_key, state.get(attempts_key))
        repair_attempts_exhausted = (
            isinstance(reported_attempts, int)
            and repair_cap > 0
            and reported_attempts >= repair_cap
        )
        squad_iterations_exhausted = int(state.get("iteration") or 0) >= int(
            state.get("max_iterations") or self._max_iterations
        )
        if not repair_attempts_exhausted and not squad_iterations_exhausted:
            return {}, None
        if result.state_updates.get(pass_key) is True:
            return {}, None

        if str(gate.get("on_exhausted", "block")).lower() == "warn":
            return {"lexicon_warning_waiver": True}, None

        return {}, PHASE_TERMINAL_BLOCKED

    def _governance_config(self) -> dict:
        """Load the `governance` block so governance.* resolves in transition conditions.

        Mirrors _lexicon_gate_config: merges the governance block into eval_state
        so conditions like `governance.enabled` evaluate deterministically instead
        of returning None and punting the routing decision to COMMANDER.
        Returns {} when the file is absent or unparseable.

        Also injects defaults for the structural-gate pass flags
        (feasibility_structural_pass, intent_alignment_check_structural_pass).
        Configured structural gates default to False so an omitted model field
        cannot fail open. Disabled or absent gates default to True so the guard
        remains inert when governance is not active for that artifact.
        """
        if self._gov_config_cache is not None:
            return self._gov_config_cache
        cfg: dict = {}
        try:
            from harness.config import get_full_resolved_config

            data = get_full_resolved_config(
                self._project_root,
                fallback_config_path=self._ext_dir / "echelon-config.yml",
            )
            block = data.get("governance")
            if isinstance(block, dict):
                cfg = {"governance": block}
        except Exception:
            cfg = {}
        governance = cfg.get("governance", {})
        governance_enabled = isinstance(governance, dict) and governance.get("enabled", False)
        artifacts = governance.get("artifacts", {}) if isinstance(governance, dict) else {}

        def _structural_gate_enabled(key: str) -> bool:
            entry = artifacts.get(key, {}) if isinstance(artifacts, dict) else {}
            if not isinstance(entry, dict):
                return False
            if entry.get("enabled", True) is False:
                return False
            return governance_enabled and str(entry.get("tier") or "").lower() == "structural"

        cfg.setdefault("feasibility_structural_pass", not _structural_gate_enabled("feasibility"))
        cfg.setdefault(
            "intent_alignment_check_structural_pass",
            not _structural_gate_enabled("intent-alignment-check"),
        )
        self._gov_config_cache = cfg
        return cfg

    def _governance_structural_gate_updates(
        self,
        node: PhaseNode,
        state: dict,
        result: SquadAgentResult,
    ) -> dict[str, object]:
        """Validate governance artifacts and return controller-owned updates."""
        gates = {
            "phase2-decide": (
                "feasibility",
                "feasibility.md",
                "feasibility_structural_pass",
                "feasibility_structural_attempts",
                "feasibility_structural_findings",
                "feasibility_structural_report",
            ),
            "phase2-tracker-alignment": (
                "intent-alignment-check",
                "intent-alignment-check.md",
                "intent_alignment_check_structural_pass",
                "intent_alignment_check_structural_attempts",
                "intent_alignment_check_structural_findings",
                "intent_alignment_check_structural_report",
            ),
        }
        gate_fields = gates.get(node.id)
        if gate_fields is None:
            return {}

        artifact_key, default_name, pass_key, attempts_key, findings_key, report_key = gate_fields
        governance = self._governance_config().get("governance", {})
        artifacts = governance.get("artifacts", {}) if isinstance(governance, dict) else {}
        entry = artifacts.get(artifact_key, {}) if isinstance(artifacts, dict) else {}
        gate_enabled = (
            isinstance(governance, dict)
            and governance.get("enabled", False)
            and isinstance(entry, dict)
            and entry.get("enabled", True) is not False
            and str(entry.get("tier") or "").lower() == "structural"
        )
        updates: dict[str, object] = {}
        if not gate_enabled:
            updates[pass_key] = True
            updates[attempts_key] = 0
            return updates

        spec_dir_ref = str(
            result.state_updates.get("spec_dir")
            or state.get("spec_dir")
            or ""
        ).strip()
        if spec_dir_ref:
            spec_dir = Path(spec_dir_ref)
            if not spec_dir.is_absolute():
                spec_dir = self._project_root / spec_dir
        else:
            spec_dir = self._project_root / "runs" / str(state.get("run_id") or "unknown") / "specs"

        artifact_name = str(entry.get("path") or default_name).strip()
        artifact_path = spec_dir / artifact_name
        report = self._validate_governance_structural_artifact(
            artifact_key=artifact_key,
            artifact_path=artifact_path,
            spec_dir=spec_dir,
            entry=entry,
        )
        report_path = spec_dir / str(
            entry.get("report") or f"{artifact_key}-structural-report.json"
        ).strip()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        updates[report_key] = str(report_path)
        updates[findings_key] = len(report["findings"])
        updates[pass_key] = bool(report["ok"])
        if report["ok"]:
            updates[attempts_key] = 0
            return updates

        try:
            previous_attempts = int(state.get(attempts_key, 0))
        except (TypeError, ValueError):
            previous_attempts = 0
        updates[attempts_key] = max(0, previous_attempts) + 1
        return updates

    def _validate_governance_structural_artifact(
        self,
        *,
        artifact_key: str,
        artifact_path: Path,
        spec_dir: Path,
        entry: dict,
    ) -> dict[str, object]:
        findings: list[dict[str, object]] = []
        if not artifact_path.is_file():
            findings.append({
                "code": "missing-structural-artifact",
                "message": f"required governance artifact is missing: {artifact_path.name}",
                "artifact": artifact_path.name,
            })
        else:
            spec_chunks: list[str] = []
            for cross_ref in entry.get("cross_refs") or []:
                against = str(cross_ref.get("against") or "").strip()
                if not against:
                    continue
                spec_path = spec_dir / against
                if spec_path.is_file():
                    spec_chunks.append(spec_path.read_text(encoding="utf-8", errors="replace"))
                else:
                    findings.append({
                        "code": "missing-cross-reference",
                        "message": f"structural reference artifact is missing: {against}",
                        "artifact": against,
                    })
            try:
                from lexicon.structural import structural_validate

                validation_entry = dict(entry)
                template = str(validation_entry.get("template") or "").strip()
                if template:
                    validation_entry["template"] = self._ext_dir / "templates" / template
                validation = structural_validate(
                    artifact_path.read_text(encoding="utf-8", errors="replace"),
                    validation_entry,
                    spec_text="\n\n".join(spec_chunks),
                )
                findings.extend(
                    {
                        "code": str(item.code),
                        "message": str(item.message),
                        "line": int(item.line),
                        "span": str(item.span),
                    }
                    for item in validation.findings
                )
            except Exception as exc:
                findings.append({
                    "code": "structural-validator-error",
                    "message": f"structural validator failed: {exc}",
                })

        return {
            "schema_version": 1,
            "artifact": artifact_key,
            "path": str(artifact_path),
            "ok": not findings,
            "findings": findings,
        }

    def _governance_exhaustion_enrichment(
        self,
        node: PhaseNode,
        state: dict,
        controller_updates: Mapping[str, object],
    ) -> tuple[dict[str, object], str | None]:
        gate_fields = {
            "phase2-decide": (
                "feasibility",
                "feasibility_structural_pass",
                "feasibility_structural_attempts",
            ),
            "phase2-tracker-alignment": (
                "intent-alignment-check",
                "intent_alignment_check_structural_pass",
                "intent_alignment_check_structural_attempts",
            ),
        }.get(node.id)
        if gate_fields is None:
            return {}, None
        artifact_key, pass_key, attempts_key = gate_fields
        governance = self._governance_config().get("governance", {})
        if (
            not isinstance(governance, dict)
            or controller_updates.get(pass_key) is True
        ):
            return {}, None
        try:
            repair_cap = int(governance.get("max_repair_attempts", 3))
        except (TypeError, ValueError):
            repair_cap = 3
        try:
            attempts = int(
                controller_updates.get(
                    attempts_key,
                    state.get(attempts_key, 0),
                )
            )
        except (TypeError, ValueError):
            attempts = 0
        iterations_exhausted = int(state.get("iteration") or 0) >= int(
            state.get("max_iterations") or self._max_iterations
        )
        if not ((repair_cap > 0 and attempts >= repair_cap) or iterations_exhausted):
            return {}, None

        updates = {"governance_gate_exhausted": artifact_key}
        if str(governance.get("on_exhausted") or "warn").lower() != "block":
            return updates, None

        return updates, PHASE_TERMINAL_BLOCKED

    def _controller_enrichment(
        self,
        node: PhaseNode,
        state: Mapping[str, object],
        result: SquadAgentResult,
    ) -> ControllerEnrichment:
        """Build controller-owned updates without mutating result or state."""
        state_copy = deepcopy(dict(state))
        updates = self._governance_structural_gate_updates(
            node,
            state_copy,
            result,
        )
        governance_updates, governance_override = (
            self._governance_exhaustion_enrichment(
                node,
                state_copy,
                updates,
            )
        )
        updates.update(governance_updates)
        lexicon_updates, lexicon_override = self._lexicon_gate_enrichment(
            node,
            state_copy,
            result,
        )
        updates.update(lexicon_updates)
        state_removals: set[str] = set()
        if node.id == "phase1-lexicon":
            state_removals.add("lexicon_warning_waiver")
            if result.state_updates.get("lexicon_evaluation") == "pending":
                state_removals.update(
                    {
                        "lexicon_pass",
                        "lexicon_findings",
                        "lexicon_report",
                    }
                )
        if node.id in {"phase3-plan", "phase3-consensus"}:
            state_removals.update(
                {
                    "product_input_mapping_repair",
                    "product_input_mapping_repair_attempts",
                }
            )
        routing_override = governance_override or lexicon_override
        control_updates: dict[str, object] = {}
        if routing_override == PHASE_TERMINAL_BLOCKED:
            control_updates["status"] = "blocked"
            if governance_override:
                control_updates["blocked_reason"] = (
                    "governance_gate_exhausted"
                )
            elif lexicon_override:
                control_updates.update(
                    {
                        "blocked_reason": "lexicon_gate_exhausted",
                        "lexicon_gate_exhausted": True,
                    }
                )
        return ControllerEnrichment(
            updates=updates,
            routing_override=routing_override,
            controller_owns_result_updates=node.type
            in {"deterministic_lexicon", "deterministic_understanding"},
            state_removals=frozenset(state_removals),
            control_updates=control_updates,
        )

    def _prepare_phase_result(
        self,
        node: PhaseNode,
        result: SquadAgentResult,
        snapshot: RoutingStateSnapshot,
    ) -> PreparedPhaseResult:
        """Prepare one detached executor result for routing and persistence."""
        candidate = detach_squad_agent_result(result)
        if node.id in WHY_PHASES:
            self._normalize_why_result_quality_scores(candidate)
        provider_control_intents: dict[str, object] = {}
        payload = candidate.echelon_result
        if type(payload) is dict:
            updates = dict.get(payload, "state_updates")
            if type(updates) is dict:
                declared = frozenset(node.allowed_state_updates or ()) | (
                    node.controller_state_update_keys
                )
                blocking_control_syntax = candidate.verdict in {
                    "BLOCKED",
                    "STOP_AND_ASK",
                }
                sanitized_updates = dict(updates)
                for key in ("status", "blocked_reason"):
                    if key in sanitized_updates and (
                        key in declared or blocking_control_syntax
                    ):
                        provider_control_intents[key] = (
                            sanitized_updates[key]
                        )
        enrichment = self._controller_enrichment(
            node,
            snapshot.state,
            candidate,
        )
        control_updates = {
            **provider_control_intents,
            **dict(enrichment.control_updates),
        }
        return prepare_phase_result(
            node,
            candidate,
            controller_updates=enrichment.updates,
            routing_override=enrichment.routing_override,
            controller_owns_result_updates=(
                enrichment.controller_owns_result_updates
            ),
            state_removals=frozenset(
                enrichment.state_removals
                - STORE_OWNED_TRANSACTION_KEYS
            ),
            trusted_transaction_state_removals=frozenset(
                enrichment.state_removals
                & STORE_OWNED_TRANSACTION_KEYS
            ),
            control_updates=control_updates,
        )

    def _block_after_executor_contract_failure(
        self,
        node: PhaseNode,
        exc: ControllerStateContractViolation,
    ) -> None:
        """Record a detached, redacted failure from executor-side preparation."""
        try:
            snapshot = self._state_store.capture_routing_snapshot(
                expected_phase=node.id,
            )
        except StateAdvanceError:
            return
        self._block_after_state_advance_failure(
            node,
            node.id,
            StateAdvanceError(
                "controller result preparation failed",
                json_path=exc.json_path,
                validator=exc.validator,
            ),
            snapshot=snapshot,
            diagnostic_contract=exc.contract,
            diagnostic_subject="controller result preparation",
        )

    def _prepare_phase_result_or_block(
        self,
        node: PhaseNode,
        result: SquadAgentResult,
        snapshot: RoutingStateSnapshot,
    ) -> PreparedPhaseResult | None:
        """Prepare a result or persist one stable, redacted contract failure."""
        try:
            return self._prepare_phase_result(node, result, snapshot)
        except ControllerStateContractViolation as exc:
            self._block_after_state_advance_failure(
                node,
                node.id,
                StateAdvanceError(
                    "controller result preparation failed",
                    json_path=exc.json_path,
                    validator=exc.validator,
                ),
                snapshot=snapshot,
                diagnostic_contract=exc.contract,
                diagnostic_subject="controller result preparation",
            )
            return None

    def _advance_prepared_result_or_block(
        self,
        node: PhaseNode,
        decision: PreparedRoutingDecision,
        *,
        prepared_publication: PreparedSquadPublication | None = None,
    ) -> AdvanceReceipt | None:
        """Commit one sealed route or persist a separate redacted failure."""
        completion_marker = dict(
            decision.transaction_state_updates
        ).get(PENDING_CONTROLLER_COMPLETION_KEY)
        if not isinstance(completion_marker, Mapping):
            self._block_after_state_advance_failure(
                node,
                decision.from_phase,
                StateAdvanceError(
                    "routing decision does not authorize completion",
                    json_path=(
                        "$.transaction_state_updates."
                        f"{PENDING_CONTROLLER_COMPLETION_KEY}"
                    ),
                    validator="completion_binding",
                ),
                decision=decision,
                token_usage_delta=decision.token_usage_delta,
            )
            return None
        completion_id = str(
            completion_marker.get("completion_id") or ""
        )
        try:
            if prepared_publication is not None:
                expected_marker = prepared_publication.marker.to_dict()
                if (
                    dict(decision.transaction_state_updates).get(
                        PENDING_EXTERNAL_PUBLICATION_KEY
                    )
                    != expected_marker
                ):
                    raise StateAdvanceError(
                        "routing decision does not authorize publication",
                        json_path=(
                            "$.transaction_state_updates."
                            f"{PENDING_EXTERNAL_PUBLICATION_KEY}"
                        ),
                        validator="ownership",
                    )
            receipt = self._state_store.advance(
                decision.from_phase,
                decision.to_phase,
                decision,
            )
            if not isinstance(receipt, AdvanceReceipt):
                raise StateAdvanceError(
                    "state advance did not return a receipt",
                    json_path="$.advance_receipt",
                    validator="receipt",
                )
            recovery = self._drain_pending_controller_completion()
            if (
                not recovery.recovered
                or recovery.completion_id != completion_id
            ):
                return None
            return receipt
        except StateAdvanceError as exc:
            self._discard_publication_without_authority(
                prepared_publication,
            )
            self._discard_controller_completion_without_authority(
                completion_marker,
            )
            self._block_after_state_advance_failure(
                node,
                decision.from_phase,
                exc,
                decision=decision,
                token_usage_delta=decision.token_usage_delta,
            )
            return None

    def _discard_controller_completion_without_authority(
        self,
        marker: Mapping[str, object],
    ) -> None:
        """Discard a route stage only after exact state proves no authority."""
        try:
            expected = validate_pending_controller_completion(marker)
            state = self._state_store.load()
        except Exception:
            return
        if state.get(PENDING_CONTROLLER_COMPLETION_KEY) == expected:
            return
        dispatch = state.get("last_dispatch")
        if (
            isinstance(dispatch, Mapping)
            and dispatch.get("dispatch_id") == expected["completion_id"]
            and dispatch.get("post_dispatch_complete") is False
            and dispatch.get("completion_intent_sha256")
            == expected["intent_sha256"]
        ):
            return
        try:
            prepared = load_prepared_controller_completion(
                self._project_root,
                self._squad_dir,
                expected,
            )
            prepared.discard()
        except CompletionError:
            return

    def _block_after_state_advance_failure(
        self,
        node: PhaseNode,
        from_phase: str,
        error: StateAdvanceError,
        *,
        decision: PreparedRoutingDecision | None = None,
        snapshot: RoutingStateSnapshot | None = None,
        token_usage_delta: int = 0,
        diagnostic_contract: str | None = None,
        diagnostic_subject: str = "state advance",
    ) -> None:
        """Persist a stable diagnostic without treating failure as an advance."""
        contract = node.controller_state_contract
        json_path = (
            error.json_path
            if isinstance(error.json_path, str)
            and error.json_path.startswith("$")
            else "$.prepared_result"
        )
        validator = (
            error.validator
            if isinstance(error.validator, str)
            and re.fullmatch(r"[a-zA-Z0-9_.-]+", error.validator)
            else "state_advance"
        )
        persisted = self._state_store.merge_advance_failure_diagnostic(
            from_phase=from_phase,
            expected_state_revision=(
                decision.expected_state_revision
                if decision is not None
                else snapshot.state_revision
                if snapshot is not None
                else -1
            ),
            expected_previous_dispatch_sha256=(
                decision.expected_previous_dispatch_sha256
                if decision is not None
                else snapshot.previous_dispatch_sha256
                if snapshot is not None
                else None
            ),
            updates={
                "status": "blocked",
                "blocked_reason": (
                    "controller_state_contract_validation_failed"
                ),
                "controller_contract_error": {
                    "phase_id": from_phase,
                    "contract": (
                        diagnostic_contract
                        or (
                            contract.name
                            if contract is not None
                            else "routing_decision"
                        )
                    ),
                    "contract_sha256": (
                        contract.sha256 if contract is not None else None
                    ),
                    "json_path": json_path,
                    "validator": validator,
                    "message": (
                        f"{diagnostic_subject} failed at "
                        f"{json_path} ({validator})"
                    ),
                },
            },
            token_usage_delta=token_usage_delta,
        )
        if not persisted and token_usage_delta:
            self._state_store.increment_token_usage(token_usage_delta)
        if persisted:
            self._record_blocker_event(
                from_phase,
                "controller_state_contract_validation_failed",
            )

    @staticmethod
    def _with_why_verdict_quality_fallback(
        node: PhaseNode,
        result: SquadAgentResult,
        eval_state: dict[str, object],
    ) -> None:
        if node.id not in WHY_PHASES or eval_state.get("quality_scores"):
            return
        verdict_upper = (result.verdict or "").upper()
        if verdict_upper in ("FAIL", "BLOCKED"):
            eval_state["quality_scores"] = [{"pass": False}]
        elif verdict_upper in ("DONE", "COMPLETE", "PASS"):
            eval_state["quality_scores"] = [{"pass": True}]

    def _transition_evaluation_inputs(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
    ) -> tuple[SquadAgentResult, dict, dict[str, object]]:
        result = prepared.as_squad_agent_result()
        state = snapshot.state
        # Merge order (lowest→highest precedence): controller config, persisted
        # state, then the prepared canonical updates.
        eval_state: dict[str, object] = {
            **self._lexicon_gate_config(),
            **self._governance_config(),
            **state,
            **prepared.state_updates,
        }
        self._with_why_verdict_quality_fallback(node, result, eval_state)
        return result, state, eval_state

    def _evaluate_transition_conditions(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
        *,
        start_index: int = 0,
    ) -> str:
        result, _state, eval_state = self._transition_evaluation_inputs(
            node,
            prepared,
            snapshot,
        )
        for index, transition in enumerate(
            node.transitions[start_index:],
            start=start_index,
        ):
            condition = transition.get("condition", "always")
            evaluation = self._evaluator.evaluate(
                condition,
                eval_state,
                result,
            )
            if evaluation is True:
                self._matched_transition = (node.id, index)
                return transition["to"]
            if evaluation is None:
                raise _TransitionJudgmentRequired(condition, index)
        return "DONE"

    def _evaluate_transitions(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
    ) -> str:
        """Select a route without mutating the prepared payload or state."""
        if not isinstance(prepared, PreparedPhaseResult):
            raise TypeError(
                "_evaluate_transitions requires PreparedPhaseResult"
            )
        if prepared.routing_override:
            return prepared.routing_override
        return self._evaluate_transition_conditions(
            node,
            prepared,
            snapshot,
        )

    def _coordinate_why_transition_state(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
    ) -> tuple[str | None, dict[str, object]]:
        """Return WHY routing and state effects without persisting them."""
        if node.id not in WHY_PHASES:
            return None, {}

        result, state, eval_state = self._transition_evaluation_inputs(
            node,
            prepared,
            snapshot,
        )
        escalation_q = prepared.state_updates.get("escalation_question")
        if escalation_q:
            updates: dict[str, object] = {"status": "blocked"}
            if "blocked_reason" not in prepared.control_updates:
                updates["blocked_reason"] = "WHY phase: agent escalation"
            return node.id, updates

        verdict_upper = (result.verdict or "").upper()
        is_fail = (
            self._evaluator.evaluate(
                "quality_gates.fail",
                eval_state,
                result,
            )
            is True
            or verdict_upper in ("FAIL", "BLOCKED")
        )
        if not is_fail:
            return None, {"why_fail_count": 0}

        try:
            fail_count = int(state.get("why_fail_count") or 0) + 1
        except (TypeError, ValueError):
            fail_count = 1
        updates = {"why_fail_count": fail_count}
        if fail_count < 2 or state.get("escalation_question"):
            return None, updates
        last_ts = (state.get("last_dispatch") or {}).get("completed_at")
        if self._phase_artifacts_changed_since(last_ts, snapshot.state):
            return None, updates

        print(
            f"[squad] ✗ consecutive-fail guard: {fail_count} {node.id} "
            "FAILs with no artifact progress — forcing escalation",
            flush=True,
        )
        updates["escalation_question"] = (
            f"Auto-detected: {fail_count} consecutive {node.id} FAILs "
            "with no artifact progress. User input or banzai COMMANDER "
            "judgment required before continuing."
        )
        updates["blocked_reason"] = "consecutive_why_fails"
        updates["status"] = "blocked"
        return PHASE_TERMINAL_BLOCKED, updates

    def _construct_routing_decision_or_block(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
        *,
        additional_state_updates: Mapping[str, object] | None = None,
        manual_phase_run: bool = False,
        conditional_skip: bool = False,
    ) -> PreparedRoutingDecision | None:
        """Construct one route or record a redacted snapshot-bound failure."""
        with self._defer_routing_provider_usage() as usage:
            try:
                return self._coordinate_transition_routing(
                    node,
                    prepared,
                    snapshot,
                    additional_state_updates=additional_state_updates,
                    manual_phase_run=manual_phase_run,
                    conditional_skip=conditional_skip,
                )
            except (
                ControllerStateContractViolation,
                StateAdvanceError,
            ) as exc:
                if (
                    isinstance(exc, StateAdvanceError)
                    and exc.validator == "checkpoint_prestate"
                ):
                    # The caller owns any publication stage prepared before
                    # routing and discards it when this returns no decision.
                    # Do not turn unavailable Git authority into state.
                    return None
                if isinstance(exc, ControllerStateContractViolation):
                    error = StateAdvanceError(
                        "routing decision construction failed",
                        json_path=exc.json_path,
                        validator=exc.validator,
                    )
                else:
                    error = exc
                self._block_after_state_advance_failure(
                    node,
                    snapshot.phase,
                    error,
                    snapshot=snapshot,
                    token_usage_delta=usage["tokens"],
                    diagnostic_contract=(
                        exc.contract
                        if isinstance(
                            exc,
                            ControllerStateContractViolation,
                        )
                        else None
                    ),
                    diagnostic_subject="routing decision construction",
                )
                return None

    def _coordinate_transition_routing(
        self,
        node: PhaseNode,
        prepared: PreparedPhaseResult,
        snapshot: RoutingStateSnapshot,
        *,
        additional_state_updates: Mapping[str, object] | None = None,
        manual_phase_run: bool = False,
        conditional_skip: bool = False,
    ) -> PreparedRoutingDecision:
        """Select and seal one route without mutating live success state."""
        self._matched_transition = None
        queued_updates: dict[str, object] = {}
        transaction_updates: dict[str, object] = {}
        transaction_removals = set(
            prepared.trusted_transaction_state_removals
        )

        def merge_effects(effects: Mapping[str, object]) -> None:
            for key, value in effects.items():
                if key in STORE_OWNED_TRANSACTION_KEYS:
                    if key not in TRUSTED_ROUTING_EFFECT_KEYS:
                        raise ControllerStateContractViolation(
                            "routing effect contains a transaction identity",
                            contract="routing",
                            json_path=f"$.state_updates.{key}",
                            validator="ownership",
                        )
                    transaction_updates[key] = value
                else:
                    queued_updates[key] = value

        def merge_judgment_effects(
            effects: Mapping[str, object],
        ) -> None:
            """Promote validated control syntax; reject judgment ownership."""
            status = effects.get("status")
            has_status = "status" in effects
            blocked_reason = effects.get("blocked_reason")
            has_blocked_reason = "blocked_reason" in effects
            for key, value in effects.items():
                if key in {"status", "blocked_reason"}:
                    continue
                if key in STORE_OWNED_TRANSACTION_KEYS:
                    raise ControllerStateContractViolation(
                        "judgment effect contains a transaction identity",
                        contract="judgment",
                        json_path=f"$.state_updates.{key}",
                        validator="ownership",
                    )
                queued_updates[key] = value
            if has_status and status != "blocked":
                raise ControllerStateContractViolation(
                    "judgment lifecycle intent is not controller-promotable",
                    contract="judgment",
                    json_path="$.state_updates.status",
                    validator="ownership",
                )
            if has_blocked_reason and (
                type(blocked_reason) is not str
                or not blocked_reason.strip()
                or status != "blocked"
            ):
                raise ControllerStateContractViolation(
                    "judgment blocked reason is not a valid control intent",
                    contract="judgment",
                    json_path="$.state_updates.blocked_reason",
                    validator="ownership",
                )
            if status == "blocked":
                transaction_updates["status"] = "blocked"
                transaction_updates["blocked_reason"] = (
                    blocked_reason
                    if type(blocked_reason) is str
                    and blocked_reason.strip()
                    else "judgment_blocked"
                )

        merge_effects(dict(additional_state_updates or {}))
        judgment_payloads: list[dict[str, object]] = []
        judgment_results: list[SquadAgentResult] = []
        source = "transition"
        transition_index: int | None = None
        if prepared.routing_override:
            next_phase = self._evaluate_transitions(
                node,
                prepared,
                snapshot,
            )
            source = "controller_override"
        else:
            why_override, why_updates = (
                self._coordinate_why_transition_state(
                    node,
                    prepared,
                    snapshot,
                )
            )
            merge_effects(why_updates)
            if why_override:
                next_phase = why_override
                source = "why_policy"
            else:
                start_index = 0
                while True:
                    try:
                        if start_index == 0:
                            next_phase = self._evaluate_transitions(
                                node,
                                prepared,
                                snapshot,
                            )
                        else:
                            next_phase = (
                                self._evaluate_transition_conditions(
                                    node,
                                    prepared,
                                    snapshot,
                                    start_index=start_index,
                                )
                            )
                        break
                    except _TransitionJudgmentRequired as unresolved:
                        transition_index = unresolved.transition_index
                        source = "commander"
                        result = prepared.as_squad_agent_result()
                        judgment = self._judgment_dispatch(
                            "Cannot evaluate condition "
                            f"{unresolved.condition!r} in phase "
                            f"{node.id!r}",
                            node,
                            result,
                            snapshot,
                        )
                        judgment_payload = judgment.echelon_result
                        if isinstance(judgment_payload, dict):
                            judgment_payloads.append(judgment_payload)
                            judgment_results.append(judgment)
                        requested_phase = (
                            judgment.state_updates.get("next_phase")
                            or judgment.state_updates.get("phase")
                        )
                        valid_phases = self._graph.all_phase_ids()
                        if (
                            requested_phase
                            and requested_phase not in valid_phases
                        ):
                            print(
                                "[squad] ✗ judgment returned invalid phase "
                                f"{requested_phase!r} — not in phase graph. "
                                "Blocking.",
                                flush=True,
                            )
                            merge_effects(
                                {
                                    "status": "blocked",
                                    "blocked_reason": (
                                        "judgment_invalid_next_phase"
                                    ),
                                }
                            )
                            next_phase = PHASE_TERMINAL_BLOCKED
                            break
                        routing_keys = {"next_phase", "phase"}
                        extra = {
                            key: value
                            for key, value in judgment.state_updates.items()
                            if key not in routing_keys
                        }
                        if judgment.verdict == "BLOCKED":
                            if requested_phase:
                                raise ControllerStateContractViolation(
                                    "blocked judgment cannot select a route",
                                    contract="judgment",
                                    json_path="$.state_updates.next_phase",
                                    validator="blocked_intent",
                                )
                            if (
                                extra.get("status") != "blocked"
                                or type(extra.get("blocked_reason")) is not str
                                or not extra["blocked_reason"].strip()
                            ):
                                raise ControllerStateContractViolation(
                                    "blocked judgment requires an exact block intent",
                                    contract="judgment",
                                    json_path="$.state_updates",
                                    validator="blocked_intent",
                                )
                            merge_judgment_effects(extra)
                            next_phase = node.id
                            break
                        if "status" in extra or "blocked_reason" in extra:
                            raise ControllerStateContractViolation(
                                "resolved judgment cannot own lifecycle state",
                                contract="judgment",
                                json_path="$.state_updates",
                                validator="resolved_intent",
                            )
                        merge_judgment_effects(extra)
                        if requested_phase:
                            next_phase = str(requested_phase)
                            break
                        start_index = unresolved.transition_index + 1

        matched = getattr(self, "_matched_transition", None)
        if (
            isinstance(matched, tuple)
            and len(matched) == 2
            and matched[0] == node.id
            and isinstance(matched[1], int)
        ):
            transition_index = matched[1]
        for key in set(queued_updates) & set(prepared.state_updates):
            if queued_updates[key] == prepared.state_updates[key]:
                queued_updates.pop(key)
        increment_iteration = self._transition_increments_iteration(
            node,
            next_phase,
        )
        if PENDING_CONTROLLER_COMPLETION_KEY in transaction_updates:
            raise ControllerStateContractViolation(
                "routing effects cannot provide completion authority",
                contract="routing",
                json_path=(
                    "$.transaction_state_updates."
                    f"{PENDING_CONTROLLER_COMPLETION_KEY}"
                ),
                validator="ownership",
            )
        publication_marker = transaction_updates.get(
            PENDING_EXTERNAL_PUBLICATION_KEY
        )
        completion = self._prepare_controller_completion(
            from_phase=node.id,
            to_phase=next_phase,
            snapshot=snapshot,
            manual_phase_run=manual_phase_run,
            conditional_skip=conditional_skip,
            record_completion=True,
            publication_marker=(
                publication_marker
                if isinstance(publication_marker, Mapping)
                else None
            ),
            judgments=tuple(judgment_results),
        )
        transaction_updates[PENDING_CONTROLLER_COMPLETION_KEY] = (
            completion.marker.to_dict()
        )
        try:
            return self._state_store.prepare_routing_decision(
                prepared,
                snapshot=snapshot,
                from_phase=node.id,
                to_phase=next_phase,
                queued_state_updates=queued_updates,
                transaction_state_updates=transaction_updates,
                transaction_state_removals=transaction_removals,
                judgment_payloads=judgment_payloads,
                source=source,
                transition_index=transition_index,
                increment_iteration=increment_iteration,
                manual_phase_run=manual_phase_run,
                conditional_skip=conditional_skip,
                token_usage_delta=(
                    self._deferred_provider_usage or {"tokens": 0}
                )["tokens"],
                dispatch_id=completion.marker.completion_id,
            )
        except BaseException:
            try:
                completion.discard()
            except CompletionError:
                pass
            raise

    def _transition_increments_iteration(
        self,
        node: PhaseNode,
        next_phase: str,
    ) -> bool:
        """Resolve action only from the transition selected during routing."""
        matched = getattr(self, "_matched_transition", None)
        if (
            not isinstance(matched, tuple)
            or len(matched) != 2
            or matched[0] != node.id
            or not isinstance(matched[1], int)
            or matched[1] < 0
            or matched[1] >= len(node.transitions)
        ):
            return False
        transition = node.transitions[matched[1]]
        return (
            transition.get("to") == next_phase
            and transition.get("action") == "increment_iteration"
        )

    def _dispatch_reason(self, phase: str, attempt: int) -> str:
        """Choose telemetry reason from controller state, never model output."""
        state = self._state_store.load()
        if phase == "phase1-what" and state.get("cartographer_resume_existing_spec"):
            return "resume"
        if state.get("product_input_mapping_repair"):
            return "deterministic_repair"
        if phase == "phase1-what" and attempt > 1:
            return "semantic_repair"
        return "planned_iteration" if attempt > 1 else "initial"

    def _judgment_dispatch(
        self,
        reason: str,
        node: PhaseNode,
        result: Optional[SquadAgentResult] = None,
        snapshot: RoutingStateSnapshot | None = None,
    ) -> SquadAgentResult:
        """Dispatch slimmed COMMANDER for judgment calls."""
        commander_path = self._ext_dir / "agents/control/commander.md"
        state = (
            snapshot.state
            if snapshot is not None
            else self._state_store.load()
        )
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
        with self._telemetry_provider.dispatch(
            DispatchContext(node.id, "COMMANDER", "judgment", 1)
        ):
            raw_judgment = self._telemetry_provider.exec_agent(
                str(self._project_root),
                context,
            )
        judgment = self._canonicalize_judgment_result(raw_judgment)
        return judgment

    def _judgment_dispatch_escalation(
        self,
        escalation_question: str,
        blocked_phase: str,
        recovery_reason: str = "",
    ) -> SquadAgentResult:
        """Dispatch COMMANDER to resolve a user-gated escalation in banzai mode.

        COMMANDER produces staging/user-clarifications.md with BANZAI-AUTO-RESOLVED
        answers and returns state_updates that clear the block.
        """
        commander_path = self._ext_dir / "agents/control/commander.md"
        snapshot = self._state_store.capture_routing_snapshot()
        state = snapshot.state
        # Recovery arguments are observational hints from an earlier caller
        # load.  The captured immutable snapshot is the only routing authority.
        snapshot_question = str(state.get("escalation_question") or "")
        blocked_reason = str(state.get("blocked_reason") or "")
        if (
            not blocked_reason
            and str(state.get("phase_dispatch_limit_phase") or "").strip()
        ):
            blocked_reason = "phase_dispatch_limit"
        snapshot_phase = snapshot.phase
        last_dispatch = state.get("last_dispatch")
        last_dispatch_phase = (
            str(last_dispatch.get("phase_id") or "").strip()
            if isinstance(last_dispatch, dict)
            else ""
        )
        dispatch_limit_phase = _phase_dispatch_limit_phase(state)
        blocked_origin_phase = snapshot_phase
        if snapshot_phase == PHASE_TERMINAL_BLOCKED:
            if (
                dispatch_limit_phase
                and dispatch_limit_phase in self._graph.all_phase_ids()
                and dispatch_limit_phase not in TERMINAL_PHASES
            ):
                blocked_origin_phase = dispatch_limit_phase
            elif (
                last_dispatch_phase
                and last_dispatch_phase in self._graph.all_phase_ids()
                and last_dispatch_phase not in TERMINAL_PHASES
            ):
                blocked_origin_phase = last_dispatch_phase
        reset_why_fail_count = blocked_reason == "consecutive_why_fails"
        capped_phase = (
            _phase_dispatch_limit_phase(state)
            if blocked_reason == "phase_dispatch_limit"
            else ""
        )

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
            f"**Phase blocked:** {blocked_origin_phase}\n\n"
            f"**Blocking questions:**\n{snapshot_question}\n\n"
            f"**Your task:**\n"
            f"1. For each blocking question, produce a best-judgment answer.\n"
            f"2. Write `{staging_dir}/user-clarifications.md` using the "
            f"BANZAI-AUTO-RESOLVED format from commander.md §Banzai Escalation.\n"
            f"3. Return echelon_result state_updates that clear the block:\n"
            f"   escalation_question: null\n"
            f"   escalation_resolved: true\n"
            f"   escalation_resolver: COMMANDER-banzai\n"
            f"   blocked_reason: null\n\n"
            f"Do NOT return `why_fail_count`; it is controller-owned and the "
            f"harness resets it after a valid consecutive-fail recovery.\n\n"
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

        with self._defer_routing_provider_usage() as usage:
            with self._telemetry_provider.dispatch(
                DispatchContext(
                    blocked_origin_phase,
                    "COMMANDER",
                    "escalation",
                    1,
                )
            ):
                raw_result = self._telemetry_provider.exec_agent(
                    str(self._project_root),
                    context,
                )

        validation_reason = ""
        try:
            result = self._canonicalize_judgment_result(raw_result)
        except ControllerStateContractViolation:
            validation_reason = "contract"
            result = SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "JUDGMENT_RESOLVED",
                    "state_updates": {},
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )
        if result.quarantined_state_updates:
            validation_reason = sorted(
                result.quarantined_state_updates
            )[0]
        if not validation_reason and result.verdict != "JUDGMENT_RESOLVED":
            validation_reason = "verdict"
        cleanup = result.state_updates
        if not validation_reason and not (
            "escalation_question" in cleanup
            and cleanup["escalation_question"] is None
            and cleanup.get("escalation_resolved") is True
            and cleanup.get("escalation_resolver") == "COMMANDER-banzai"
            and "blocked_reason" in cleanup
            and cleanup["blocked_reason"] is None
            and (
                "status" not in cleanup
                or cleanup.get("status") == "running"
            )
        ):
            validation_reason = "cleanup_intent"

        from_phase = snapshot.phase
        requested_phase = str(
            result.state_updates.get("next_phase")
            or result.state_updates.get("phase")
            or ""
        ).strip()
        if (
            requested_phase
            and requested_phase not in self._graph.all_phase_ids()
        ):
            validation_reason = "next_phase"

        queued_updates: dict[str, object] = {}
        removals: set[str] = set()
        transaction_updates: dict[str, object] = {}
        transaction_removals: set[str] = set()
        target_phase = requested_phase or from_phase
        source = "commander_recovery"
        if validation_reason:
            target_phase = PHASE_TERMINAL_BLOCKED
            transaction_updates.update(
                {
                    "status": "blocked",
                    "blocked_reason": (
                        "judgment state_updates validation failed: "
                        f"{validation_reason}"
                    ),
                }
            )
            source = "commander_recovery_rejected"
        else:
            for key, value in result.state_updates.items():
                if key in {"next_phase", "phase"}:
                    continue
                if key in STORE_OWNED_TRANSACTION_KEYS:
                    valid_control_intent = (
                        (key == "status" and value == "running")
                        or (key == "blocked_reason" and value is None)
                        or (
                            key == "escalation_resolved"
                            and value is True
                        )
                        or (
                            key == "escalation_resolver"
                            and value == "COMMANDER-banzai"
                        )
                    )
                    if not valid_control_intent:
                        validation_reason = "ownership"
                        break
                    continue
                if value is None:
                    removals.add(key)
                else:
                    queued_updates[key] = value
            if validation_reason:
                queued_updates.clear()
                removals.clear()
                transaction_updates.clear()
                transaction_removals.clear()
                target_phase = PHASE_TERMINAL_BLOCKED
                transaction_updates.update(
                    {
                        "status": "blocked",
                        "blocked_reason": (
                            "judgment state_updates validation failed: "
                            f"{validation_reason}"
                        ),
                    }
                )
                source = "commander_recovery_rejected"
            else:
                transaction_updates.update(
                    {
                        "status": "running",
                        "escalation_resolved": True,
                        "escalation_resolver": "COMMANDER-banzai",
                    }
                )
                transaction_removals.add("blocked_reason")
                removals.add("escalation_question")
                if reset_why_fail_count:
                    transaction_updates["why_fail_count"] = 0
                if capped_phase:
                    counts = state.get("phase_dispatch_counts")
                    next_counts = (
                        dict(counts) if isinstance(counts, dict) else {}
                    )
                    next_counts.pop(capped_phase, None)
                    transaction_updates["phase_dispatch_counts"] = (
                        next_counts
                    )
                    transaction_updates["phase_dispatch_limit_recovery"] = {
                        "phase": capped_phase,
                        "resolver": "COMMANDER-banzai",
                    }
                if (
                    not requested_phase
                    and from_phase == PHASE_TERMINAL_BLOCKED
                    and blocked_origin_phase
                    and blocked_origin_phase != PHASE_TERMINAL_BLOCKED
                ):
                    target_phase = blocked_origin_phase

        payload = deepcopy(result.echelon_result or {})
        payload["state_updates"] = {}
        synthetic_result = detach_squad_agent_result(result)
        synthetic_result.echelon_result = payload
        recovery_node = PhaseNode(
            id=from_phase,
            type="commander_recovery",
            allowed_state_updates=[],
        )
        completion: PreparedControllerCompletion | None = None
        try:
            prepared = prepare_phase_result(
                recovery_node,
                synthetic_result,
                controller_updates={},
                routing_override=target_phase,
                state_removals=removals,
            )
            completion = self._prepare_controller_completion(
                from_phase=from_phase,
                to_phase=target_phase,
                snapshot=snapshot,
                manual_phase_run=False,
                conditional_skip=False,
                record_completion=False,
                publication_marker=None,
                judgments=(result,),
            )
            transaction_updates[
                PENDING_CONTROLLER_COMPLETION_KEY
            ] = completion.marker.to_dict()
            decision = self._state_store.prepare_routing_decision(
                prepared,
                snapshot=snapshot,
                from_phase=from_phase,
                to_phase=target_phase,
                queued_state_updates=queued_updates,
                transaction_state_updates=transaction_updates,
                transaction_state_removals=transaction_removals,
                token_usage_delta=usage["tokens"],
                judgment_payloads=(
                    [result.echelon_result]
                    if isinstance(result.echelon_result, dict)
                    else []
                ),
                source=source,
                record_completion=False,
                dispatch_id=completion.marker.completion_id,
            )
            receipt = self._state_store.advance(
                from_phase,
                target_phase,
                decision,
            )
            if not isinstance(receipt, AdvanceReceipt):
                raise StateAdvanceError(
                    "recovery state advance did not return a receipt",
                    json_path="$.advance_receipt",
                    validator="receipt",
                )
            recovery = self._drain_pending_controller_completion()
            if (
                not recovery.recovered
                or recovery.completion_id
                != completion.marker.completion_id
            ):
                return result
        except (
            ControllerStateContractViolation,
            StateAdvanceError,
        ) as exc:
            error = (
                StateAdvanceError(
                    "recovery routing decision construction failed",
                    json_path=exc.json_path,
                    validator=exc.validator,
                )
                if isinstance(exc, ControllerStateContractViolation)
                else exc
            )
            self._block_after_state_advance_failure(
                recovery_node,
                from_phase,
                error,
                snapshot=snapshot,
                token_usage_delta=usage["tokens"],
                diagnostic_contract=(
                    exc.contract
                    if isinstance(
                        exc,
                        ControllerStateContractViolation,
                    )
                    else "commander_recovery"
                ),
                diagnostic_subject="recovery routing decision",
            )
            if completion is not None:
                self._discard_controller_completion_without_authority(
                    completion.marker.to_dict()
                )
            return result
        return result

    def _write_journal_entries(self, result: SquadAgentResult, phase_id: str) -> None:
        """Mirror executor journal writes through the shared durable store."""
        from harness.journal_entry_validator import (
            append_reasoning_journal_entries,
        )

        entries = list((result.echelon_result or {}).get("journal_entries", []))
        if result.quarantined_state_updates:
            entries.insert(
                0,
                {
                    "type": "state_contract_warning",
                    "agent": "speckit-echelon-commander",
                    "data": {
                        "dropped_keys": sorted(result.quarantined_state_updates),
                        "action": "quarantined",
                        "reason": (
                            "undeclared reporting fields were excluded from the "
                            "state mutation control plane"
                        ),
                    },
                },
            )
        if not entries:
            return
        append_reasoning_journal_entries(
            self._squad_dir,
            entries,
            phase_id=phase_id,
            schema_path=self._ext_dir / "workflow/journal-entry-types.yaml",
            invalid_registered_policy="quarantine",
        )

    def _phase_artifacts_changed_since(
        self,
        iso_timestamp: Optional[str],
        state: Mapping[str, object],
    ) -> bool:
        """Return True if a canonical phase artifact is newer than the cutoff.

        Before WHAT creates ``state.spec_dir``, discovery/WHY1 artifacts live in
        the run-local staging directory. After that boundary, ``spec_dir`` is the
        authoritative artifact root and staging is only a control-message inbox.
        """
        if iso_timestamp is None:
            return True
        try:
            from datetime import datetime, timezone
            cutoff = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            spec_dir_ref = str(state.get("spec_dir") or "").strip()
            if spec_dir_ref:
                artifact_root = Path(spec_dir_ref)
                if not artifact_root.is_absolute():
                    artifact_root = self._project_root / artifact_root
            else:
                artifact_root = Path(
                    state.get("staging_dir", str(self._squad_dir / "staging"))
                )
            for f in artifact_root.rglob("*.md"):
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
        # Signal handlers must not enter the file-backed state lock: SIGINT can
        # interrupt this thread while it already owns that non-reentrant lock.
        # The main loop persists the interrupted state after the current phase.
        self._cancelled = True
