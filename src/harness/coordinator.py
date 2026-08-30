"""StrategyCoordinator -- multi-strategy management.

Per FR-STRATEGY-001: fan out N ralph-loops.
Per FR-STRATEGY-003: budget slicing.
Per FR-STRATEGY-004a: kill_losers on first convergence.
Per FR-STRATEGY-004b: cancel_requested between exec calls.

Uses stdlib concurrent.futures.ThreadPoolExecutor (CS2: no external deps).
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness.budget import slice_budget
from harness.paths import build_dir, strategies_dir as _strategies_dir_fn
from harness.config import HarnessConfig
from harness.llm_provider import AICodingCliProvider
from harness.escalation import EscalationHandler, print_escalation_sticky_banner
from harness.delivery_results import (
    DeliveryResult,
    ImplementationResult,
    ReviewResult,
    VisualResult,
)
from harness.verify_result import VerifyResult
from harness.mode import ModeController
from harness.provider import SandboxProvider
from harness.ralph import RalphController
from harness.repair_loop import (
    RepairAttempt,
    RepairCheck,
    RepairCritique,
    RepairLoop,
    RepairVerdict,
)
from harness.review_loop import ReviewLoopController
from harness.run_intent import RunIntent
from harness.skill_loader import resolve_llm_prompt
from harness.spec_frontmatter import find_spec_dir, read_frontmatter, read_targets
from harness.stacks.context import build_stack_context
from harness.visual_ralph import VisualRalphController
from harness.state import (
    DELIVERY_STATE_VERSION,
    StateStore,
    migrate_legacy_delivery_state,
)
from harness.strategy_loader import StrategySpec, load_strategies
from echelon.artifact_index import write_artifact_index
from harness.run_history import append_implementation_run
from harness.spec_frontmatter import write_status
from kernel.fulfillment import latest_fulfillment_report, read_fulfillment_metadata

logger = logging.getLogger(__name__)


def _split_env_list(raw: str | None) -> list[str]:
    """Parse a comma-separated orchestrator contract without empty entries."""
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def _string_tuple(value: object) -> tuple[str, ...]:
    """Accept only concrete canonical task IDs supplied by the review controller."""
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _path_tuple(value: object) -> tuple[Path, ...]:
    """Accept only concrete published artifact paths from the review controller."""
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(Path(item) for item in value if isinstance(item, Path))


def _serialize_verify_result(result: Any) -> dict[str, Any] | None:
    """Persist the portable verification evidence used by terminal resumes."""
    if result is None:
        return None
    failures = []
    for failure in getattr(result, "failures", ()):
        category = getattr(failure, "category", "")
        failures.append(
            {
                "category": getattr(category, "value", str(category)),
                "id": str(getattr(failure, "id", "")),
                "error": str(getattr(failure, "error", "")),
            }
        )
    return {
        "passed": bool(getattr(result, "passed", False)),
        "failures": failures,
        "duration_s": float(getattr(result, "duration_s", 0.0)),
        "token_usage": int(getattr(result, "token_usage", 0)),
    }


def _pending_review_reentry(value: object) -> dict[str, object] | None:
    """Validate the persisted review handoff before resuming an exact re-entry."""
    if not isinstance(value, dict):
        return None
    attempt_id = value.get("attempt_id")
    task_ids = value.get("task_ids")
    artifact_paths = value.get("artifact_paths")
    phase1_verified = value.get("phase1_verified", False)
    if (
        not isinstance(attempt_id, str)
        or not attempt_id
        or not isinstance(task_ids, list)
        or not all(isinstance(task_id, str) for task_id in task_ids)
        or not isinstance(artifact_paths, list)
        or not all(isinstance(path, str) for path in artifact_paths)
        or not isinstance(phase1_verified, bool)
    ):
        return None
    return value


def _derive_target_task_ids(
    *,
    tasks_file: Path | None,
    declared_targets: list[str],
    implementation_target: str | None,
) -> list[str]:
    """Recover target-owned task IDs from canonical task ownership metadata."""
    target = (implementation_target or "").strip()
    if not target or tasks_file is None or not tasks_file.is_file():
        return []

    from harness.task_targets import validate_task_targets

    result = validate_task_targets(
        tasks_file.read_text(encoding="utf-8", errors="replace"),
        declared_targets=declared_targets or [target],
    )
    if not result.valid:
        return []
    return list(result.target_tasks.get(target, ()))



class StrategyCoordinator:
    """Coordinates multiple strategy runs.

    One RalphController per strategy, each with independent state.
    N=1 is passthrough (no threading overhead).
    """

    def __init__(
        self,
        provider: SandboxProvider,
        gitops: Any,
        config: HarnessConfig,
        base_dir: str = ".",
        build_id: str = "",
        orchestration_root: str | Path | None = None,
    ) -> None:
        self._provider = provider
        self._gitops = gitops
        self._config = config
        self._base_dir = base_dir
        self._orchestration_root = (
            Path(orchestration_root).resolve()
            if orchestration_root is not None
            else None
        )
        self._build_id = build_id
        self._build_dir = build_dir(Path(base_dir), build_id)
        self._state_dir = self._build_dir / "state"
        self._strategies_dir = _strategies_dir_fn(Path(base_dir))
        self._escalation_dir = self._build_dir

        # Convergence event for kill_losers
        self._convergence_event = threading.Event()
        self._converged_strategy: Optional[str] = None
        self._lock = threading.Lock()

        # Active state stores (for cancel propagation)
        self._state_stores: Dict[str, StateStore] = {}

    def start(self, intent: RunIntent) -> List[DeliveryResult]:
        """Launch N RalphControllers (one per strategy).

        Args:
            intent: Parsed RunIntent with strategies, budget, etc.

        Returns:
            Delivery results from all strategies.
        """
        n = len(intent.strategies)

        # Pre-flight: refuse to wipe any active escalation block without --reset
        for sid in intent.strategies:
            store = StateStore(self._state_dir, intent.spec_id, sid)
            existing = store.read()
            if (
                existing.get("status") == "blocked"
                and existing.get("escalation_file")
                and not intent.reset
                and not intent.resume
            ):
                escalation_handler = EscalationHandler(str(self._escalation_dir))
                answer = escalation_handler.check_resume(str(existing["escalation_file"]))
                if answer is None:
                    print_escalation_sticky_banner(intent.spec_id, sid, str(existing["escalation_file"]))
                    raise RuntimeError(
                        f"[{sid}] blocked — escalation pending. "
                        f"Run echelon delivery continue {intent.spec_id} if no answer is needed, "
                        f"or run echelon delivery resume {intent.spec_id} \"<answer>\" "
                        "to clarify; pass --reset to discard."
                    )

        # Load strategy specs (build_command + context per strategy)
        strategy_specs = load_strategies(
            intent.spec_id, intent.strategies,
            base_dir=str(self._strategies_dir),
        )

        # Slice budget
        budgets = slice_budget(
            intent.token_budget, n,
            strategy_ids=intent.strategies,
        )

        if n == 1:
            # N=1 passthrough: no threading overhead
            spec = strategy_specs.get(intent.strategies[0], StrategySpec())
            return [self._run_strategy(
                intent=intent,
                strategy_id=intent.strategies[0],
                budget=budgets[intent.strategies[0]],
                spec=spec,
            )]

        # N>1: concurrent execution
        results: Dict[str, DeliveryResult] = {}

        with ThreadPoolExecutor(max_workers=min(n, 3)) as executor:
            futures = {}
            for sid in intent.strategies:
                future = executor.submit(
                    self._run_strategy,
                    intent=intent,
                    strategy_id=sid,
                    budget=budgets[sid],
                    spec=strategy_specs.get(sid, StrategySpec()),
                )
                futures[future] = sid

            for future in as_completed(futures):
                sid = futures[future]
                try:
                    result = future.result()
                    results[sid] = result

                    # kill_losers: cancel peers on first convergence
                    if intent.kill_losers and result.status == "converged":
                        self._cancel_peers(sid, intent.strategies)
                except Exception as e:
                    logger.error("Strategy %s failed: %s", sid, e)
                    results[sid] = DeliveryResult(
                        status="blocked",
                        termination_reason="outer_cap",
                        outer_iterations=0,
                        inner_iterations=0,
                        pr_url=None,
                        tokens_used=0,
                        final_verify=None,
                        blocked_phase="finalization",
                    )

        # Return in original strategy order
        return [results[sid] for sid in intent.strategies if sid in results]

    def status(self) -> Dict[str, Any]:
        """Aggregate status across all strategies."""
        statuses: Dict[str, Any] = {}
        if not self._state_dir.exists():
            return {"active_loops": 0, "strategies": {}}

        for state_file in self._state_dir.glob("*.json"):
            try:
                import json
                data = json.loads(state_file.read_text(encoding="utf-8"))
                sid = data.get("strategy_id", state_file.stem)
                statuses[sid] = {
                    "status": data.get("status", "unknown"),
                    "outer_iter": data.get("outer_iter", 0),
                    "inner_iter": data.get("inner_iter", 0),
                    "tokens_used": data.get("tokens_used", 0),
                    "token_budget": data.get("token_budget"),
                    "pr_url": data.get("pr_url"),
                    "termination_reason": data.get("termination_reason"),
                }
            except Exception as e:
                statuses[state_file.stem] = {"status": "corrupted", "error": str(e)}

        return {
            "active_loops": sum(
                1 for s in statuses.values()
                if s.get("status") in ("running", "blocked", "initialized")
            ),
            "strategies": statuses,
        }

    def compare_results(self, results: Dict[str, DeliveryResult]) -> Dict[str, Any]:
        """Compare results across strategies.

        Returns structured dict suitable for display.
        """
        comparison: Dict[str, Any] = {
            "strategy_count": len(results),
            "strategies": {},
        }

        for sid, result in results.items():
            state = {}
            try:
                store = self._state_stores.get(sid)
                state = store.read() if store is not None else {}
            except Exception:
                state = {}
            comparison["strategies"][sid] = {
                "status": result.status,
                "termination_reason": result.termination_reason,
                "outer_iterations": result.outer_iterations,
                "inner_iterations": result.inner_iterations,
                "tokens_used": result.tokens_used,
                "pr_url": result.pr_url,
                "branch": result.branch,
                "converged": result.status == "converged",
                "build_status": state.get("build_status"),
                "build_reason": state.get("build_reason"),
                "provider_reset_hint": state.get("provider_reset_hint"),
                "provider_limit_message": state.get("provider_limit_message"),
                "salvage_commit": state.get("salvage_commit"),
                "salvage_branch": state.get("salvage_branch"),
                "salvage_verified": state.get("salvage_verified"),
                "escalation_file": state.get("escalation_file"),
                "fulfillment_refresh": state.get("fulfillment_refresh"),
            }

        # Summary
        converged_count = sum(
            1 for s in comparison["strategies"].values() if s["converged"]
        )
        comparison["summary"] = {
            "converged": converged_count,
            "failed": len(results) - converged_count,
            "total_tokens": sum(r.tokens_used for r in results.values()),
        }

        return comparison

    # === Private methods ===

    def _enabled_phases(self, llm_provider: AICodingCliProvider | None) -> list[str]:
        """Snapshot the delivery phases selected for a new run."""
        phases = ["implementation"]
        if self._config.visual_tests.enabled and llm_provider is None:
            phases.append("visual")
        if self._config.review_loop.enabled and self._config.pr_host != "none":
            phases.append("review")
        phases.append("finalization")
        return phases

    @staticmethod
    def _run_enabled_phases(enabled_phases: list[str], start_phase: str) -> list[str]:
        """Return the persisted phase suffix beginning at a durable checkpoint."""
        try:
            return enabled_phases[enabled_phases.index(start_phase):]
        except ValueError:
            return []

    def _migrate_delivery_state(
        self, state_store: StateStore, llm_provider: AICodingCliProvider | None
    ) -> Dict[str, Any]:
        """Upgrade a nonterminal v1 state once without reopening terminal work."""
        state = state_store.read()
        if not state or state.get("delivery_state_version") == DELIVERY_STATE_VERSION:
            return state
        if state.get("status") in {"converged", "failed", "cancelled_by_coordinator"}:
            return state

        state = migrate_legacy_delivery_state(
            state,
            enabled_phases=self._enabled_phases(llm_provider),
        )
        state_store.write(state)
        return state

    @staticmethod
    def _resume_phase(state: Dict[str, Any]) -> str:
        """Return the persisted checkpoint phase, never the live configuration."""
        status = state.get("status")
        if status in {"blocked", "interrupted"}:
            return str(state.get(f"{status}_phase") or "implementation")
        if status == "validating":
            return "visual"
        if status == "reviewing":
            return "review"
        if status == "finalizing":
            return "finalization"
        if status == "verified":
            completed = state.get("last_completed_phase")
            phases = state.get("enabled_phases") or ["implementation", "finalization"]
            if completed in phases:
                completed_index = phases.index(completed)
                if completed_index + 1 < len(phases):
                    return str(phases[completed_index + 1])
            return "finalization"
        return "implementation"

    @staticmethod
    def _terminal_delivery_result(state: Dict[str, Any]) -> DeliveryResult:
        """Return an existing terminal delivery outcome without mutating state."""
        persisted_status = str(state.get("status"))
        status = {
            "converged": "converged",
            "failed": "failed",
            "cancelled_by_coordinator": "cancelled",
        }[persisted_status]
        final_verify = None
        persisted_verify = state.get("last_verify_result")
        if isinstance(persisted_verify, dict):
            try:
                final_verify = VerifyResult.from_dict(persisted_verify)
            except Exception:
                final_verify = None
        return DeliveryResult(
            status=status,
            termination_reason=str(state.get("termination_reason") or status),
            outer_iterations=int(state.get("outer_iter") or 0),
            inner_iterations=int(state.get("inner_iter") or 0),
            pr_url=state.get("pr_url"),
            tokens_used=int(state.get("tokens_used") or 0),
            final_verify=final_verify,
            blocked_phase=None,
            branch=state.get("branch") or state.get("branch_name"),
        )

    @staticmethod
    def _worktree_head(worktree_path: Path) -> str:
        """Return HEAD from the registered delivery worktree only."""
        try:
            result = subprocess.run(
                ["git", "-C", str(worktree_path), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return ""
        return result.stdout.strip() if result.returncode == 0 else ""

    @staticmethod
    def _implementation_from_state(state: Dict[str, Any]) -> ImplementationResult:
        """Project durable common delivery evidence into a phase result."""
        return ImplementationResult(
            status="verified",
            termination_reason=str(state.get("termination_reason") or "verified"),
            outer_iterations=int(state.get("outer_iter") or 0),
            inner_iterations=int(state.get("inner_iter") or 0),
            pr_url=state.get("pr_url"),
            tokens_used=int(state.get("tokens_used") or 0),
            final_verify=None,
            branch=state.get("branch") or state.get("branch_name"),
        )

    def _downstream_resume_error(self, state: Dict[str, Any]) -> str | None:
        """Validate the immutable worktree/commit pair before phase re-entry."""
        worktree_text = state.get("registered_worktree")
        verified_commit = str(state.get("verified_commit") or "")
        if not isinstance(worktree_text, str) or not worktree_text:
            return "missing_registered_worktree"
        worktree_path = Path(worktree_text)
        if not worktree_path.is_dir():
            return "missing_registered_worktree"
        if not verified_commit or self._worktree_head(worktree_path) != verified_commit:
            return "verified_provenance_mismatch"
        return None

    def _verified_checkpoint_updates(
        self,
        *,
        spec_id: str,
        strategy_id: str,
        implementation: ImplementationResult,
    ) -> Dict[str, Any] | None:
        """Capture mandatory immutable worktree provenance with Phase 1 verification."""
        registered_worktree = self._gitops.get_latest_worktree(
            spec_id, strategy_id, build_id=self._build_id
        )
        worktree_path = (
            Path(registered_worktree)
            if isinstance(registered_worktree, str) and registered_worktree
            else None
        )
        if worktree_path is None or not worktree_path.is_dir():
            return None
        verified_commit = self._worktree_head(worktree_path)
        if not verified_commit:
            return None
        return {
            "last_completed_phase": "implementation",
            "pr_url": implementation.pr_url,
            "registered_worktree": str(worktree_path) if worktree_path else None,
            "verified_commit": verified_commit,
        }

    def _checkpoint_verified_result(
        self,
        state_store: StateStore,
        *,
        spec_id: str,
        strategy_id: str,
        implementation: ImplementationResult,
        outer_iterations: int,
        tokens_used: int,
    ) -> DeliveryResult | None:
        """Persist a verified checkpoint or return its durable implementation block."""
        state = state_store.read()
        recovery = state.get("verified_publish_recovery")
        registered = state.get("registered_worktree")
        recovered_commit = str(state.get("verified_commit") or "")
        if (
            isinstance(recovery, dict)
            and recovery.get("status") == "completed"
            and isinstance(registered, str)
            and registered
            and recovered_commit
            and Path(registered).is_dir()
            and self._worktree_head(Path(registered)) == recovered_commit
        ):
            checkpoint_updates = {
                "last_completed_phase": "implementation",
                "pr_url": implementation.pr_url,
                "registered_worktree": registered,
                "verified_commit": recovered_commit,
            }
        else:
            checkpoint_updates = self._verified_checkpoint_updates(
                spec_id=spec_id,
                strategy_id=strategy_id,
                implementation=implementation,
            )
        if checkpoint_updates is None:
            return self._persist_phase_block(
                state_store,
                phase="implementation",
                reason="verified_provenance_unavailable",
                implementation=implementation,
                outer_iterations=outer_iterations,
                tokens_used=tokens_used,
            )
        state_store.transition("verified", updates=checkpoint_updates)
        return None

    def _persist_phase_block(
        self,
        state_store: StateStore,
        *,
        phase: str,
        reason: str,
        implementation: ImplementationResult,
        outer_iterations: int,
        tokens_used: int,
        final_verify: Any = None,
    ) -> DeliveryResult:
        """Persist a recoverable phase failure with its exact restart point."""
        state = state_store.read()
        state_store.transition(
            "blocked",
            updates={
                "blocked_phase": phase,
                "termination_reason": reason,
                "pr_url": implementation.pr_url,
                "outer_iter": max(int(state.get("outer_iter") or 0), outer_iterations),
                "tokens_used": max(int(state.get("tokens_used") or 0), tokens_used),
            },
        )
        return DeliveryResult(
            status="blocked",
            termination_reason=reason,
            outer_iterations=outer_iterations,
            inner_iterations=implementation.inner_iterations,
            pr_url=implementation.pr_url,
            tokens_used=tokens_used,
            final_verify=final_verify if final_verify is not None else implementation.final_verify,
            blocked_phase=phase,  # type: ignore[arg-type]
            branch=implementation.branch,
        )

    def _finalize_delivery(
        self,
        state_store: StateStore,
        *,
        spec_dir: Path | None,
        declared_targets: list[str],
        implementation: ImplementationResult,
        outer_iterations: int,
        tokens_used: int,
        final_verify: Any,
    ) -> DeliveryResult:
        """Own single-target lifecycle publication and terminal convergence."""
        state = state_store.read()
        if state.get("status") != "finalizing":
            state_store.transition("finalizing", updates={"blocked_phase": None})
        if len(declared_targets) == 1:
            try:
                state = state_store.read()
                worktree_text = state.get("registered_worktree")
                persisted_verified_commit = str(state.get("verified_commit") or "")
                if not isinstance(worktree_text, str) or not worktree_text or not persisted_verified_commit:
                    return self._persist_phase_block(
                        state_store,
                        phase="finalization",
                        reason="verified_provenance_mismatch",
                        implementation=implementation,
                        outer_iterations=outer_iterations,
                        tokens_used=tokens_used,
                        final_verify=final_verify,
                    )
                recorded_commit = self._worktree_head(Path(worktree_text))
                report = latest_fulfillment_report(spec_dir) if spec_dir is not None else None
                metadata = read_fulfillment_metadata(report) if report is not None else {}
                verified_commit = str(metadata.get("verified_commit") or "")
                if (
                    not verified_commit
                    or verified_commit != recorded_commit
                    or persisted_verified_commit != recorded_commit
                    or persisted_verified_commit != verified_commit
                ):
                    return self._persist_phase_block(
                        state_store,
                        phase="finalization",
                        reason="verified_provenance_mismatch",
                        implementation=implementation,
                        outer_iterations=outer_iterations,
                        tokens_used=tokens_used,
                        final_verify=final_verify,
                    )
                state_store.transition(
                    "finalizing", updates={"verified_commit": verified_commit}
                )
                current_status = read_frontmatter(spec_dir).get("status")
                if current_status == "In Progress":
                    write_status(spec_dir, "in_progress")
                    current_status = "in_progress"
                if current_status not in {None, "planned", "in_progress", "ready_to_land"}:
                    return self._persist_phase_block(
                        state_store,
                        phase="finalization",
                        reason="lifecycle_status_conflict",
                        implementation=implementation,
                        outer_iterations=outer_iterations,
                        tokens_used=tokens_used,
                        final_verify=final_verify,
                    )
                if current_status != "ready_to_land":
                    write_status(spec_dir, "ready_to_land")
                append_implementation_run(
                    spec_dir,
                    run_id=str(state_store.read().get("run_id") or ""),
                    spec_status="ready_to_land",
                    verification_result="PASS",
                )
                write_artifact_index(spec_dir)
            except Exception as exc:
                logger.warning("Could not finalize %s: %s", spec_dir, exc)
                return self._persist_phase_block(
                    state_store,
                    phase="finalization",
                    reason="finalization_write_failed",
                    implementation=implementation,
                    outer_iterations=outer_iterations,
                    tokens_used=tokens_used,
                    final_verify=final_verify,
                )
        state = state_store.read()
        state_store.transition(
            "converged",
            updates={
                "termination_reason": "converged",
                "outer_iter": max(int(state.get("outer_iter") or 0), outer_iterations),
                "inner_iter": max(
                    int(state.get("inner_iter") or 0), implementation.inner_iterations
                ),
                "tokens_used": max(int(state.get("tokens_used") or 0), tokens_used),
                "pr_url": implementation.pr_url,
                "branch_name": implementation.branch,
                "last_verify_result": _serialize_verify_result(final_verify),
            },
        )
        return DeliveryResult(
            status="converged",
            termination_reason="converged",
            outer_iterations=outer_iterations,
            inner_iterations=implementation.inner_iterations,
            pr_url=implementation.pr_url,
            tokens_used=tokens_used,
            final_verify=final_verify,
            blocked_phase=None,
            branch=implementation.branch,
        )

    def _run_strategy(
        self,
        intent: RunIntent,
        strategy_id: str,
        budget: Optional[int],
        spec: StrategySpec,
    ) -> DeliveryResult:
        """Run a single strategy's ralph-loop."""
        state_store = StateStore(self._state_dir, intent.spec_id, strategy_id)

        with self._lock:
            self._state_stores[strategy_id] = state_store

        mode_controller = ModeController(intent.mode)
        escalation_handler = EscalationHandler(str(self._escalation_dir))

        # Initialize state
        import uuid
        run_id = str(uuid.uuid4())
        target_repo_name = os.environ.get("ECHELON_TARGET_REPO_NAME")
        target_repo_path = os.environ.get("ECHELON_TARGET_REPO_PATH")
        environment_workspace_root = os.environ.get("ECHELON_WORKSPACE_ROOT")
        workspace_git_role = os.environ.get("ECHELON_WORKSPACE_GIT_ROLE")
        source_root = os.environ.get("ECHELON_SOURCE_ROOT")
        source_id = os.environ.get("ECHELON_SOURCE_ID")
        source_git_role = os.environ.get("ECHELON_SOURCE_GIT_ROLE")
        implementation_target = os.environ.get("ECHELON_IMPLEMENTATION_TARGET")
        declared_targets = _split_env_list(os.environ.get("ECHELON_DECLARED_TARGETS"))
        target_task_ids = _split_env_list(os.environ.get("ECHELON_TARGET_TASK_IDS"))
        if self._orchestration_root is not None:
            spec_search_root = self._orchestration_root
            workspace_root = str(self._orchestration_root)
        else:
            spec_search_root = Path(
                os.environ.get("ECHELON_POLYREPO_ROOT") or self._base_dir
            ).resolve()
            workspace_root = environment_workspace_root or str(spec_search_root)
        source_root = source_root or target_repo_path or str(Path(self._base_dir).resolve())
        source_id = source_id or target_repo_name or Path(source_root).name
        if workspace_git_role is None:
            workspace_git_role = "orchestration" if target_repo_path else "source"
        if source_git_role is None:
            source_git_role = "source"
        spec_dir = find_spec_dir(intent.spec_id, spec_search_root)
        spec_file = spec_dir / "spec.md" if spec_dir is not None else None
        tasks_file = spec_dir / "tasks.md" if spec_dir is not None else None
        if not declared_targets and spec_dir is not None:
            declared_targets = read_targets(spec_dir)
        state_store.acquire_lock(run_id)

        try:
            existing = state_store.read()
            if (
                not intent.reset
                and existing.get("status")
                in {"converged", "failed", "cancelled_by_coordinator"}
            ):
                return self._terminal_delivery_result(existing)
            llm_provider = (
                AICodingCliProvider(self._config)
                if self._config.llm.enabled
                else None
            )
            existing = self._migrate_delivery_state(state_store, llm_provider)
            existing_status = existing.get("status")
            raw_pending_reentry = existing.get("pending_review_reentry")
            if (
                raw_pending_reentry is not None
                and _pending_review_reentry(raw_pending_reentry) is None
            ):
                implementation = self._implementation_from_state(existing)
                return self._persist_phase_block(
                    state_store,
                    phase="review",
                    reason="invalid_pending_review_reentry",
                    implementation=implementation,
                    outer_iterations=implementation.outer_iterations,
                    tokens_used=implementation.tokens_used,
                )
            pending_reentry = _pending_review_reentry(
                existing.get("pending_review_reentry")
            )
            pending_effects_only_resume = (
                not intent.reset
                and pending_reentry is not None
                and bool(pending_reentry.get("phase1_verified"))
            )
            should_resume_running = (
                not intent.reset
                and not pending_effects_only_resume
                and existing_status in {
                    "running", "interrupted", "verified", "validating",
                    "reviewing", "finalizing",
                }
            )
            should_resume_blocked = (
                not intent.reset
                and intent.resume
                and existing_status == "blocked"
                and not pending_effects_only_resume
            )
            should_resume_verified_publication = (
                should_resume_blocked
                and existing.get("termination_reason")
                in {"publish_failed", "target_merge_failed"}
                and isinstance(existing.get("verified_publish_checkpoint"), dict)
            )
            if should_resume_running or should_resume_blocked or pending_effects_only_resume:
                persisted_target = existing.get("implementation_target")
                if (
                    (not implementation_target or pending_effects_only_resume)
                    and isinstance(persisted_target, str)
                ):
                    implementation_target = persisted_target.strip() or None
                persisted_declared = existing.get("declared_targets")
                if isinstance(persisted_declared, list):
                    declared_targets = [
                        str(item).strip()
                        for item in persisted_declared
                        if str(item).strip()
                    ]

            if not target_task_ids:
                target_task_ids = _derive_target_task_ids(
                    tasks_file=tasks_file,
                    declared_targets=declared_targets,
                    implementation_target=implementation_target,
                )

            if (
                self._orchestration_root is not None
                and (
                    should_resume_running
                    or should_resume_blocked
                    or pending_effects_only_resume
                )
            ):
                # Resume progress belongs to the target harness, but canonical
                # spec identity belongs to the explicitly supplied workspace.
                # Refresh only that context before Ralph reads persisted state.
                existing["workspace_root"] = workspace_root
                existing["spec_dir"] = (
                    str(spec_dir) if spec_dir is not None else None
                )
                existing["spec_file"] = (
                    str(spec_file) if spec_file is not None else None
                )
                existing["tasks_file"] = (
                    str(tasks_file) if tasks_file is not None else None
                )
                existing["implementation_target"] = implementation_target
                existing["declared_targets"] = declared_targets
                pending = _pending_review_reentry(existing.get("pending_review_reentry"))
                if pending is not None:
                    for task_id in pending["task_ids"]:
                        if task_id not in target_task_ids:
                            target_task_ids.append(task_id)
                existing["target_task_ids"] = target_task_ids
                state_store.write(existing)

            if should_resume_running:
                logger.info(
                    "[%s/%s] Resuming from %s state (outer=%s)",
                    intent.spec_id, strategy_id,
                    existing_status,
                    existing.get("outer_iter", 0),
                )
                resume_phase = self._resume_phase(existing)
                implementation = self._implementation_from_state(existing)
                enabled_phases = existing.get("enabled_phases")
                if not isinstance(enabled_phases, list) or resume_phase not in enabled_phases:
                    return self._persist_phase_block(
                        state_store,
                        phase=resume_phase,
                        reason="invalid_resume_phase",
                        implementation=implementation,
                        outer_iterations=implementation.outer_iterations,
                        tokens_used=implementation.tokens_used,
                    )
                if resume_phase in {"visual", "review"}:
                    reason = self._downstream_resume_error(existing)
                    if reason is not None:
                        return self._persist_phase_block(
                            state_store,
                            phase=resume_phase,
                            reason=reason,
                            implementation=implementation,
                            outer_iterations=implementation.outer_iterations,
                            tokens_used=implementation.tokens_used,
                        )
                resume_status = {
                    "implementation": "running",
                    "visual": "validating",
                    "review": "reviewing",
                    "finalization": "finalizing",
                }[resume_phase]
                if existing_status != resume_status:
                    state_store.transition(resume_status)
            elif should_resume_blocked:
                logger.info(
                    "[%s/%s] Resuming from blocked state (outer=%s)",
                    intent.spec_id, strategy_id,
                    existing.get("outer_iter", 0),
                )
                resume_phase = self._resume_phase(existing)
                implementation = self._implementation_from_state(existing)
                enabled_phases = existing.get("enabled_phases")
                if not isinstance(enabled_phases, list) or resume_phase not in enabled_phases:
                    return self._persist_phase_block(
                        state_store,
                        phase=resume_phase,
                        reason="invalid_resume_phase",
                        implementation=implementation,
                        outer_iterations=implementation.outer_iterations,
                        tokens_used=implementation.tokens_used,
                    )
                if resume_phase in {"visual", "review"}:
                    reason = self._downstream_resume_error(existing)
                    if reason is not None:
                        return self._persist_phase_block(
                            state_store,
                            phase=resume_phase,
                            reason=reason,
                            implementation=implementation,
                            outer_iterations=implementation.outer_iterations,
                            tokens_used=implementation.tokens_used,
                        )
                state_store.transition({
                    "implementation": "running",
                    "visual": "validating",
                    "review": "reviewing",
                    "finalization": "finalizing",
                }[resume_phase])
            elif not pending_effects_only_resume:
                state_store.initialize(
                    run_id=run_id,
                    mode=intent.mode,
                    max_outer=intent.max_outer,
                    max_inner=intent.max_inner,
                    token_budget=budget or 0,
                    target_repo=target_repo_name,
                    target_path=target_repo_path,
                    workspace_root=workspace_root,
                    workspace_git_role=workspace_git_role,
                    source_root=source_root,
                    source_id=source_id,
                    source_git_role=source_git_role,
                    implementation_target=implementation_target,
                    declared_targets=declared_targets,
                    target_task_ids=target_task_ids,
                    spec_dir=str(spec_dir) if spec_dir is not None else None,
                    spec_file=str(spec_file) if spec_file is not None else None,
                    tasks_file=str(tasks_file) if tasks_file is not None else None,
                    enabled_phases=self._enabled_phases(llm_provider),
                )
                state_store.transition("running")

            stack_context = self._build_stack_context(spec_dir)
            strategy_context = self._combine_strategy_context(
                spec.context,
                stack_context,
            )

            arguments = f"spec {intent.spec_id} strategy={strategy_id} {intent.mode} mode"
            if intent.task_description:
                arguments += f"\n\n{intent.task_description}"
            if strategy_context:
                arguments += f"\n\n{strategy_context}"

            if llm_provider is not None:
                build_prompt = resolve_llm_prompt(
                    build_command=spec.build_command,
                    arguments=arguments,
                    project_dir=Path(self._base_dir),
                    cli=self._config.llm.cli,
                )
            else:
                build_prompt = arguments

            controller = RalphController(
                provider=self._provider,
                gitops=self._gitops,
                state_store=state_store,
                mode_controller=mode_controller,
                escalation_handler=escalation_handler,
                spec_id=intent.spec_id,
                strategy_id=strategy_id,
                config=self._config,
                llm_provider=llm_provider,
                build_id=self._build_id,
                fresh_delivery=not (
                    should_resume_running
                    or should_resume_blocked
                    or pending_effects_only_resume
                ),
            )

            pending_reentry = _pending_review_reentry(
                state_store.read().get("pending_review_reentry")
            )
            if pending_effects_only_resume and pending_reentry is not None:
                completion_controller = ReviewLoopController(
                    gitops=self._gitops,
                    config=self._config,
                    spec_id=intent.spec_id,
                    strategy_id=strategy_id,
                    base_dir=str(self._base_dir),
                    build_id=self._build_id,
                    spec_dir=spec_dir,
                )
                if not self._complete_verified_review_reentry(
                    state_store,
                    completion_controller,
                    pr_url=str(state_store.read().get("pr_url") or ""),
                    pending_reentry=pending_reentry,
                ):
                    implementation = self._implementation_from_state(state_store.read())
                    return self._persist_phase_block(
                        state_store,
                        phase="review",
                        reason="review_side_effects_pending",
                        implementation=implementation,
                        outer_iterations=implementation.outer_iterations,
                        tokens_used=implementation.tokens_used,
                    )
                pending_reentry = None

            resumed_phase = (
                self._resume_phase(existing)
                if should_resume_running or should_resume_blocked
                else "implementation"
            )
            if pending_effects_only_resume:
                resumed_phase = self._resume_phase(state_store.read())
            if pending_reentry is not None:
                resumed_phase = "implementation"
                current_status = state_store.read().get("status")
                if current_status != "running":
                    state_store.transition(
                        "running", updates={"pending_review_reentry": pending_reentry}
                    )
            current_phase = self._run_enabled_phases(
                list(state_store.read().get("enabled_phases") or ["implementation"]),
                resumed_phase,
            )[0]
            if pending_reentry is not None:
                build_prompt = self._build_reentry_prompt(
                    build_prompt,
                    intent.spec_id,
                    spec_dir=spec_dir,
                    published_artifacts=tuple(
                        Path(path) for path in pending_reentry["artifact_paths"]
                    ),
                )
            if current_phase == "implementation":
                implementation_result = (
                    controller.resume_verified_publication()
                    if should_resume_verified_publication
                    else None
                )
                if implementation_result is None:
                    implementation_result = controller.run_loop(
                        max_outer=intent.max_outer,
                        max_inner=intent.max_inner,
                        token_budget=budget,
                        build_command=spec.build_command,
                        strategy_context=strategy_context,
                        build_prompt=build_prompt,
                    )
            else:
                resumed = state_store.read()
                implementation_result = ImplementationResult(
                    status="verified",
                    termination_reason=str(
                        resumed.get("termination_reason") or "converged"
                    ),
                    outer_iterations=int(resumed.get("outer_iter") or 0),
                    inner_iterations=int(resumed.get("inner_iter") or 0),
                    pr_url=resumed.get("pr_url"),
                    tokens_used=int(resumed.get("tokens_used") or 0),
                    final_verify=None,
                    branch=resumed.get("branch") or resumed.get("branch_name"),
                )
            implementation_outer_iterations = implementation_result.outer_iterations
            implementation_tokens = implementation_result.tokens_used
            if implementation_result.status == "verified" and current_phase == "implementation":
                checkpoint_block = self._checkpoint_verified_result(
                    state_store,
                    spec_id=intent.spec_id,
                    strategy_id=strategy_id,
                    implementation=implementation_result,
                    outer_iterations=implementation_outer_iterations,
                    tokens_used=implementation_tokens,
                )
                if checkpoint_block is not None:
                    return checkpoint_block
                if pending_reentry is not None:
                    self._mark_review_reentry_phase_verified(
                        state_store, pending_reentry
                    )
                    pending_reentry = dict(pending_reentry)
                    pending_reentry["phase1_verified"] = True
                    completion_controller = ReviewLoopController(
                        gitops=self._gitops,
                        config=self._config,
                        spec_id=intent.spec_id,
                        strategy_id=strategy_id,
                        base_dir=str(self._base_dir),
                        build_id=self._build_id,
                        spec_dir=spec_dir,
                    )
                    if not self._complete_verified_review_reentry(
                        state_store,
                        completion_controller,
                        pr_url=implementation_result.pr_url or "",
                        pending_reentry=pending_reentry,
                    ):
                        return self._persist_phase_block(
                            state_store,
                            phase="review",
                            reason="review_side_effects_pending",
                            implementation=implementation_result,
                            outer_iterations=implementation_outer_iterations,
                            tokens_used=implementation_tokens,
                        )
                    pending_reentry = None

            visual_result: VisualResult | None = None
            visual_reentry_block: DeliveryResult | None = None
            visual_iterations = 0
            visual_tokens = 0
            # Phase 2: visual loop — only when Phase 1 verified via Docker sandbox.
            # Skipped when LLM provider ran Phase 1: the LLM already verified tests
            # locally (including Playwright if present), and the Docker visual loop
            # has no access to the LLM-managed worktree after it is committed.
            visual_controller = (
                VisualRalphController(
                    provider=self._provider,
                    config=self._config,
                    spec_id=intent.spec_id,
                    strategy_id=strategy_id,
                    base_dir=self._base_dir,
                )
                if "visual" in state_store.read().get("enabled_phases", [])
                else None
            )

            def registered_phase_worktree() -> str:
                """Use durable provenance for restarts, never a discovered replacement."""
                registered = state_store.read().get("registered_worktree")
                if isinstance(registered, str) and registered:
                    return registered
                if should_resume_running or should_resume_blocked:
                    return ""
                discovered = self._gitops.get_latest_worktree(
                    intent.spec_id, strategy_id, build_id=self._build_id
                )
                return discovered if isinstance(discovered, str) else ""

            def run_visual_phase() -> VisualResult | None:
                nonlocal implementation_result
                nonlocal implementation_outer_iterations, implementation_tokens
                nonlocal visual_iterations, visual_tokens
                nonlocal visual_reentry_block
                if visual_controller is None:
                    return None
                visual_attempts = 0
                last_visual_verify = None
                while implementation_result.status == "verified":
                    if state_store.read().get("status") == "verified":
                        state_store.transition("validating")
                    if visual_attempts >= self._config.visual_tests.max_iterations:
                        return VisualResult(
                            status="blocked",
                            termination_reason="visual_failed",
                            iterations=0,
                            tokens_used=0,
                            final_verify=last_visual_verify,
                        )
                    worktree_path = registered_phase_worktree()
                    if not worktree_path:
                        return VisualResult(
                            status="blocked",
                            termination_reason="missing_registered_worktree",
                            iterations=0,
                            tokens_used=0,
                            final_verify=last_visual_verify,
                        )
                    current_visual_result = visual_controller.run_loop(
                        worktree_path=worktree_path,
                        token_budget=budget,
                    )
                    visual_attempts += 1
                    last_visual_verify = current_visual_result.final_verify
                    visual_iterations += current_visual_result.iterations
                    visual_tokens += current_visual_result.tokens_used
                    if current_visual_result.status != "fix_applied":
                        return current_visual_result
                    state_store.transition("running")
                    implementation_result = controller.run_loop(
                        max_outer=intent.max_outer,
                        max_inner=intent.max_inner,
                        token_budget=budget,
                        build_command=spec.build_command,
                        strategy_context=strategy_context,
                        build_prompt=build_prompt,
                    )
                    implementation_outer_iterations += implementation_result.outer_iterations
                    implementation_tokens += implementation_result.tokens_used
                    if implementation_result.status == "verified":
                        visual_reentry_block = self._checkpoint_verified_result(
                            state_store,
                            spec_id=intent.spec_id,
                            strategy_id=strategy_id,
                            implementation=implementation_result,
                            outer_iterations=(
                                implementation_outer_iterations + visual_iterations
                            ),
                            tokens_used=implementation_tokens + visual_tokens,
                        )
                        if visual_reentry_block is not None:
                            return None
                return None

            visual_result = (
                run_visual_phase()
                if current_phase in {"implementation", "visual"}
                else None
            )
            if visual_reentry_block is not None:
                return visual_reentry_block
            if visual_result is not None and visual_result.status == "blocked":
                return self._persist_phase_block(
                    state_store,
                    phase="visual",
                    reason=visual_result.termination_reason,
                    implementation=implementation_result,
                    outer_iterations=implementation_outer_iterations + visual_iterations,
                    tokens_used=implementation_tokens + visual_tokens,
                    final_verify=visual_result.final_verify,
                )

            review_result: ReviewResult | None = None
            review_iterations = 0
            review_tokens = 0
            # Phase 3: review loop — only when Phase 1 is verified, review_loop enabled,
            # and a PR host is configured. Option A: coordinator owns the
            # Phase 1 → Phase 3 → Phase 1 re-entry loop.
            if (
                implementation_result.status == "verified"
                and "review" in state_store.read().get("enabled_phases", [])
                and current_phase != "finalization"
            ):
                current_state = state_store.read()
                if current_state.get("status") in {"verified", "validating"}:
                    state_store.transition(
                        "reviewing",
                        updates={
                            "last_completed_phase": (
                                "visual"
                                if visual_result is not None
                                and visual_result.status == "passed"
                                else "implementation"
                            )
                        },
                    )
                pr_url = implementation_result.pr_url
                if not pr_url:
                    logger.warning(
                        "review_loop enabled but Phase 1 produced no pr_url "
                        "for %s/%s — skipping Phase 3",
                        intent.spec_id, strategy_id,
                    )
                    review_result = ReviewResult(
                        status="blocked",
                        termination_reason="missing_pr_url",
                        iterations=0,
                        pr_url="",
                        tokens_used=0,
                    )
                else:
                    review_controller = ReviewLoopController(
                        gitops=self._gitops,
                        config=self._config,
                        spec_id=intent.spec_id,
                        strategy_id=strategy_id,
                        base_dir=str(self._base_dir),
                        build_id=self._build_id,
                        spec_dir=spec_dir,
                    )
                    def critique(_check: RepairCheck, iteration: int) -> RepairCritique:
                        return RepairCritique(
                            summary=f"review-loop-cycle-{iteration}",
                            signature="",
                        )

                    def repair(_critique: RepairCritique, _iteration: int) -> RepairAttempt:
                        nonlocal implementation_result, review_result, visual_result
                        nonlocal implementation_outer_iterations, implementation_tokens
                        nonlocal review_iterations, review_tokens

                        if state_store.read().get("status") != "reviewing":
                            state_store.transition("reviewing")
                        worktree_path = registered_phase_worktree()
                        if not worktree_path:
                            review_result = ReviewResult(
                                status="blocked",
                                termination_reason="missing_registered_worktree",
                                iterations=0,
                                pr_url=pr_url,
                                tokens_used=0,
                            )
                            return RepairAttempt(
                                output={
                                    "result": implementation_result,
                                    "review_result": review_result,
                                }
                            )
                        try:
                            review_result = review_controller.run_loop(
                                pr_url=pr_url,
                                worktree_path=worktree_path,
                                token_budget=budget,
                            )
                        except Exception as exc:
                            logger.warning("Review boundary failed: %s", exc)
                            review_result = ReviewResult(
                                status="blocked",
                                termination_reason="review_boundary_failed",
                                iterations=0,
                                pr_url=pr_url,
                                tokens_used=0,
                            )
                        review_iterations += review_result.iterations
                        review_tokens += review_result.tokens_used
                        if review_result.status != "review_fix_queued":
                            return RepairAttempt(
                                output={
                                    "result": implementation_result,
                                    "review_result": review_result,
                                }
                            )

                        # echelon.review queued new fix tasks — re-run Phase 1
                        # Use only the just-published batch; historical review
                        # fixes may already have been completed or superseded.
                        published_task_ids = _string_tuple(
                            getattr(review_controller, "queued_task_ids", ())
                        )
                        published_artifacts = _path_tuple(
                            getattr(review_controller, "published_artifacts", ())
                        )
                        attempt_id = getattr(
                            review_controller, "pending_batch_attempt_id", None
                        )
                        if not isinstance(attempt_id, str) or not attempt_id:
                            review_result = ReviewResult(
                                status="blocked",
                                termination_reason="review_reentry_checkpoint_failed",
                                iterations=review_result.iterations,
                                pr_url=pr_url,
                                tokens_used=review_result.tokens_used,
                            )
                            return RepairAttempt(
                                output={
                                    "result": implementation_result,
                                    "review_result": review_result,
                                }
                            )
                        try:
                            self._checkpoint_review_reentry(
                                state_store,
                                attempt_id=attempt_id,
                                task_ids=published_task_ids,
                                artifacts=published_artifacts,
                            )
                        except (OSError, ValueError) as exc:
                            logger.warning("Could not checkpoint review re-entry: %s", exc)
                            review_result = ReviewResult(
                                status="blocked",
                                termination_reason="review_reentry_checkpoint_failed",
                                iterations=review_result.iterations,
                                pr_url=pr_url,
                                tokens_used=review_result.tokens_used,
                            )
                            return RepairAttempt(
                                output={
                                    "result": implementation_result,
                                    "review_result": review_result,
                                }
                            )
                        reentry_prompt = self._build_reentry_prompt(
                            build_prompt,
                            intent.spec_id,
                            spec_dir=spec_dir,
                            published_artifacts=published_artifacts,
                        )
                        state_store.transition("running")
                        implementation_result = controller.run_loop(
                            max_outer=intent.max_outer,
                            max_inner=intent.max_inner,
                            token_budget=budget,
                            build_command=spec.build_command,
                            strategy_context=strategy_context,
                            build_prompt=reentry_prompt,
                        )
                        implementation_outer_iterations += (
                            implementation_result.outer_iterations
                        )
                        implementation_tokens += implementation_result.tokens_used
                        if implementation_result.status == "verified":
                            checkpoint_updates = self._verified_checkpoint_updates(
                                spec_id=intent.spec_id,
                                strategy_id=strategy_id,
                                implementation=implementation_result,
                            )
                            if checkpoint_updates is None:
                                implementation_result = ImplementationResult(
                                    status="blocked",
                                    termination_reason="verified_provenance_unavailable",
                                    outer_iterations=implementation_result.outer_iterations,
                                    inner_iterations=implementation_result.inner_iterations,
                                    pr_url=implementation_result.pr_url,
                                    tokens_used=implementation_result.tokens_used,
                                    final_verify=implementation_result.final_verify,
                                    branch=implementation_result.branch,
                                )
                                return RepairAttempt(
                                    output={"result": implementation_result}
                                )
                            state_store.transition(
                                "verified",
                                updates=checkpoint_updates,
                            )
                            pending_reentry = {
                                "attempt_id": attempt_id,
                                "task_ids": list(published_task_ids),
                                "artifact_paths": [
                                    str(path) for path in published_artifacts
                                ],
                                "phase1_verified": False,
                            }
                            self._mark_review_reentry_phase_verified(
                                state_store, pending_reentry
                            )
                            pending_reentry["phase1_verified"] = True
                            if not self._complete_verified_review_reentry(
                                state_store,
                                review_controller,
                                pr_url=pr_url,
                                pending_reentry=pending_reentry,
                            ):
                                review_result = ReviewResult(
                                    status="blocked",
                                    termination_reason="review_side_effects_pending",
                                    iterations=review_result.iterations,
                                    pr_url=pr_url,
                                    tokens_used=review_result.tokens_used,
                                )
                                return RepairAttempt(
                                    output={
                                        "result": implementation_result,
                                        "review_result": review_result,
                                    }
                                )
                        visual_result = run_visual_phase()
                        return RepairAttempt(
                            output={
                                "result": implementation_result,
                                "review_result": review_result,
                                "visual_result": visual_result,
                            }
                        )

                    def recheck(attempt: RepairAttempt, _iteration: int) -> RepairCheck:
                        payload = attempt.output if isinstance(attempt.output, dict) else {}
                        payload_result = payload.get("result")
                        current = (
                            payload_result
                            if isinstance(payload_result, ImplementationResult)
                            else implementation_result
                        )
                        current_review = payload.get("review_result")
                        current_visual = payload.get("visual_result")

                        if (
                            isinstance(current_visual, VisualResult)
                            and current_visual.status == "blocked"
                        ):
                            return RepairCheck(
                                verdict=RepairVerdict.BLOCK,
                                output=current,
                                reason=current_visual.termination_reason,
                                tokens=0,
                            )

                        if not isinstance(current_review, ReviewResult):
                            return RepairCheck(
                                verdict=RepairVerdict.BLOCK,
                                output=current,
                                reason=current.termination_reason,
                                tokens=0,
                            )

                        if current_review.status != "review_fix_queued":
                            return RepairCheck(
                                verdict=(
                                    RepairVerdict.ACCEPT
                                    if (
                                        current.status == "verified"
                                        and current_review.status == "completed"
                                    )
                                    else RepairVerdict.BLOCK
                                ),
                                output=current,
                                reason=current.termination_reason,
                                tokens=0,
                            )

                        if current.status == "verified":
                            return RepairCheck(
                                verdict=RepairVerdict.CONTINUE,
                                output=current,
                                reason=current.termination_reason,
                                tokens=0,
                            )

                        return RepairCheck(
                            verdict=RepairVerdict.BLOCK,
                            output=current,
                            reason=current.termination_reason,
                            tokens=0,
                        )

                    repair_loop_result = RepairLoop(
                        max_repairs=self._config.review_loop.max_fix_iterations,
                        critique=critique,
                        repair=repair,
                        recheck=recheck,
                    ).run(
                        RepairCheck(
                            verdict=RepairVerdict.CONTINUE,
                            output=implementation_result,
                            reason=implementation_result.termination_reason,
                            tokens=implementation_result.tokens_used,
                        )
                    )
                    if isinstance(
                        repair_loop_result.final_check.output, ImplementationResult
                    ):
                        implementation_result = repair_loop_result.final_check.output
                    if (
                        review_result is not None
                        and review_result.status == "completed"
                        and state_store.read().get("status") == "reviewing"
                    ):
                        state_store.transition(
                            "finalizing",
                            updates={"last_completed_phase": "review"},
                        )

            total_outer_iterations = (
                implementation_outer_iterations + visual_iterations + review_iterations
            )
            total_tokens = implementation_tokens + visual_tokens + review_tokens
            final_verify = (
                visual_result.final_verify
                if visual_result is not None
                else implementation_result.final_verify
            )
            if visual_result is not None and visual_result.status == "blocked":
                delivery_status = "blocked"
                termination_reason = visual_result.termination_reason
                blocked_phase = "visual"
            elif implementation_result.status != "verified":
                if implementation_result.status == "interrupted":
                    delivery_status = "interrupted"
                elif implementation_result.status == "cancelled":
                    delivery_status = "cancelled"
                elif implementation_result.termination_reason == "state_corruption":
                    delivery_status = "failed"
                else:
                    delivery_status = "blocked"
                termination_reason = implementation_result.termination_reason
                blocked_phase = (
                    "implementation" if delivery_status == "blocked" else None
                )
            elif review_result is not None and review_result.status != "completed":
                delivery_status = "blocked"
                termination_reason = review_result.termination_reason
                blocked_phase = "review"
            else:
                delivery_status = "converged"
                termination_reason = "converged"
                blocked_phase = None
            if delivery_status == "converged":
                return self._finalize_delivery(
                    state_store,
                    spec_dir=spec_dir,
                    declared_targets=declared_targets,
                    implementation=implementation_result,
                    outer_iterations=total_outer_iterations,
                    tokens_used=total_tokens,
                    final_verify=final_verify,
                )
            elif delivery_status == "blocked":
                return self._persist_phase_block(
                    state_store,
                    phase=str(blocked_phase),
                    reason=termination_reason,
                    implementation=implementation_result,
                    outer_iterations=total_outer_iterations,
                    tokens_used=total_tokens,
                    final_verify=final_verify,
                )
            elif delivery_status == "failed":
                state_store.transition("failed")
            elif delivery_status == "interrupted":
                state_store.transition(
                    "interrupted", updates={"interrupted_phase": "implementation"}
                )
            elif delivery_status == "cancelled":
                state_store.transition("cancelled_by_coordinator")
            return DeliveryResult(
                status=delivery_status,
                termination_reason=termination_reason,
                outer_iterations=total_outer_iterations,
                inner_iterations=implementation_result.inner_iterations,
                pr_url=implementation_result.pr_url,
                tokens_used=total_tokens,
                final_verify=final_verify,
                blocked_phase=blocked_phase,
                branch=implementation_result.branch,
            )

        finally:
            state_store.release_lock()

    def _build_stack_context(self, spec_dir: Path | None = None) -> str:
        """Render resolved Echelon stack context for selected project stacks."""
        return build_stack_context(
            Path(self._base_dir),
            selected_stacks=self._config.stacks.selected,
            target_archetypes=self._config.stacks.target_archetypes,
            spec_dir=spec_dir,
        )

    @staticmethod
    def _combine_strategy_context(
        strategy_context: str,
        stack_context: str,
    ) -> str:
        """Append generated stack context without changing empty-stack behavior."""
        if not stack_context:
            return strategy_context
        if not strategy_context:
            return stack_context
        return f"{strategy_context.rstrip()}\n\n{stack_context}"

    def _build_reentry_prompt(
        self,
        base_prompt: str,
        spec_id: str,
        *,
        spec_dir: Path | None = None,
        published_artifacts: tuple[Path, ...] = (),
    ) -> str:
        """Augment a build prompt from this batch's canonical review artifacts."""
        canonical_spec_dir = (
            Path(spec_dir).resolve()
            if spec_dir is not None
            else find_spec_dir(
                spec_id,
                self._orchestration_root or Path(self._base_dir).resolve(),
            )
        )
        if canonical_spec_dir is None:
            return base_prompt

        try:
            parts = []
            for path in published_artifacts:
                resolved = Path(path).resolve()
                if resolved.parent != canonical_spec_dir or not resolved.is_file():
                    logger.warning("Ignoring invalid published review artifact: %s", path)
                    continue
                content = resolved.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(content)
            parts = [part for part in parts if part]
        except OSError as exc:
            logger.warning("Could not read review-fix content: %s", exc)
            return base_prompt

        if not parts:
            return base_prompt

        review_content = "\n\n---\n\n".join(parts)
        return (
            f"{base_prompt}\n\n"
            f"## Review Feedback (address these before completing the build)\n"
            f"{review_content}"
        )

    @staticmethod
    def _extend_target_task_ids(
        state_store: StateStore,
        task_ids: tuple[str, ...],
    ) -> None:
        """Atomically append a published batch's canonical tasks without duplicates."""
        if not task_ids:
            return
        current = state_store.read()
        existing = current.get("target_task_ids", [])
        ordered = [value for value in existing if isinstance(value, str)]
        for task_id in task_ids:
            if task_id not in ordered:
                ordered.append(task_id)
        status = current.get("status")
        if isinstance(status, str):
            state_store.transition(status, updates={"target_task_ids": ordered})

    @staticmethod
    def _checkpoint_review_reentry(
        state_store: StateStore,
        *,
        attempt_id: str,
        task_ids: tuple[str, ...],
        artifacts: tuple[Path, ...],
    ) -> None:
        """Persist the complete published batch before Phase 1 can restart."""
        current = state_store.read()
        existing = current.get("target_task_ids", [])
        ordered = [value for value in existing if isinstance(value, str)]
        for task_id in task_ids:
            if task_id not in ordered:
                ordered.append(task_id)
        status = current.get("status")
        if not isinstance(status, str):
            raise OSError("review re-entry state has no status")
        state_store.transition(
            status,
            updates={
                "target_task_ids": ordered,
                "pending_review_reentry": {
                    "attempt_id": attempt_id,
                    "task_ids": list(task_ids),
                    "artifact_paths": [str(path) for path in artifacts],
                    "phase1_verified": False,
                },
            },
        )

    @staticmethod
    def _mark_review_reentry_phase_verified(
        state_store: StateStore,
        pending_reentry: dict[str, object],
    ) -> None:
        """Durably record that the queued batch's Phase 1 re-entry completed."""
        status = state_store.read().get("status")
        if not isinstance(status, str):
            raise OSError("review re-entry state has no status")
        verified_reentry = dict(pending_reentry)
        verified_reentry["phase1_verified"] = True
        state_store.transition(
            status,
            updates={"pending_review_reentry": verified_reentry},
        )

    @staticmethod
    def _complete_verified_review_reentry(
        state_store: StateStore,
        review_controller: ReviewLoopController,
        *,
        pr_url: str,
        pending_reentry: dict[str, object],
    ) -> bool:
        """Retry side effects only after a durably verified Phase 1 re-entry."""
        if not bool(pending_reentry.get("phase1_verified")):
            return False
        if not review_controller.complete_published_batch(
            pr_url, str(pending_reentry["attempt_id"])
        ):
            return False

        # A prior side-effect failure is persisted as blocked. Restore the
        # Phase 1 checkpoint without calling Ralph or spending another loop
        # iteration, then atomically clear the completed handoff.
        status = state_store.read().get("status")
        if status == "blocked":
            state_store.transition("running")
            status = "running"
        if status not in {"running", "verified"}:
            return False
        state_store.transition("verified", updates={"pending_review_reentry": None})
        return True

    def _cancel_peers(self, converged_sid: str, all_strategies: List[str]) -> None:
        """Set cancel_requested on all peer strategies (kill_losers)."""
        with self._lock:
            if self._converged_strategy is not None:
                return  # Already cancelled
            self._converged_strategy = converged_sid
            self._convergence_event.set()

        for sid in all_strategies:
            if sid == converged_sid:
                continue
            store = self._state_stores.get(sid)
            if store:
                try:
                    state = store.read()
                    if state.get("status") == "running":
                        state["cancel_requested"] = True
                        store.write(state)
                        logger.info("Cancelled peer strategy '%s'", sid)
                except Exception as e:
                    logger.warning("Failed to cancel strategy '%s': %s", sid, e)
