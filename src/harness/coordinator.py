"""StrategyCoordinator -- multi-strategy management.

Per FR-STRATEGY-001: fan out N ralph-loops.
Per FR-STRATEGY-003: budget slicing.
Per FR-STRATEGY-004a: kill_losers on first convergence.
Per FR-STRATEGY-004b: cancel_requested between exec calls.

Uses stdlib concurrent.futures.ThreadPoolExecutor (CS2: no external deps).
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness.budget import slice_budget
from harness.paths import build_dir, strategies_dir as _strategies_dir_fn
from harness.config import HarnessConfig
from harness.llm_provider import ClaudeCliProvider
from harness.escalation import EscalationHandler, print_escalation_sticky_banner
from harness.loop_result import LoopResult
from harness.mode import ModeController
from harness.provider import SandboxProvider
from harness.ralph import RalphController
from harness.review_loop import ReviewLoopController
from harness.run_intent import RunIntent
from harness.skill_loader import resolve_llm_prompt
from harness.visual_ralph import VisualRalphController
from harness.state import StateStore
from harness.strategy_loader import StrategySpec, load_strategies

logger = logging.getLogger(__name__)



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
    ) -> None:
        self._provider = provider
        self._gitops = gitops
        self._config = config
        self._base_dir = base_dir
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

    def start(self, intent: RunIntent) -> List[LoopResult]:
        """Launch N RalphControllers (one per strategy).

        Args:
            intent: Parsed RunIntent with strategies, budget, etc.

        Returns:
            List of LoopResults from all strategies.
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
            ):
                escalation_handler = EscalationHandler(str(self._escalation_dir))
                answer = escalation_handler.check_resume(str(existing["escalation_file"]))
                if answer is None:
                    print_escalation_sticky_banner(intent.spec_id, sid, str(existing["escalation_file"]))
                    raise RuntimeError(
                        f"[{sid}] blocked — escalation pending. "
                        f"Answer with /speckit-harness-resume or pass --reset to discard."
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
        results: Dict[str, LoopResult] = {}

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
                    results[sid] = LoopResult(
                        status="failed",
                        termination_reason="outer_cap",
                        outer_iterations=0,
                        inner_iterations=0,
                        pr_url=None,
                        tokens_used=0,
                        final_verify=None,
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

    def compare_results(self, results: Dict[str, LoopResult]) -> Dict[str, Any]:
        """Compare results across strategies.

        Returns structured dict suitable for display.
        """
        comparison: Dict[str, Any] = {
            "strategy_count": len(results),
            "strategies": {},
        }

        for sid, result in results.items():
            comparison["strategies"][sid] = {
                "status": result.status,
                "termination_reason": result.termination_reason,
                "outer_iterations": result.outer_iterations,
                "inner_iterations": result.inner_iterations,
                "tokens_used": result.tokens_used,
                "pr_url": result.pr_url,
                "converged": result.status == "converged",
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

    def _run_strategy(
        self,
        intent: RunIntent,
        strategy_id: str,
        budget: Optional[int],
        spec: StrategySpec,
    ) -> LoopResult:
        """Run a single strategy's ralph-loop."""
        state_store = StateStore(self._state_dir, intent.spec_id, strategy_id)

        with self._lock:
            self._state_stores[strategy_id] = state_store

        mode_controller = ModeController(intent.mode)
        escalation_handler = EscalationHandler(str(self._escalation_dir))

        # Initialize state
        import uuid
        run_id = str(uuid.uuid4())
        state_store.acquire_lock(run_id)

        try:
            existing = state_store.read()
            existing_status = existing.get("status")
            should_resume = (
                not intent.reset
                and existing_status in ("running", "interrupted")
            )

            if should_resume:
                logger.info(
                    "[%s/%s] Resuming from %s state (outer=%s)",
                    intent.spec_id, strategy_id,
                    existing_status,
                    existing.get("outer_iter", 0),
                )
                state_store.transition("running")
            else:
                state_store.initialize(
                    run_id=run_id,
                    mode=intent.mode,
                    max_outer=intent.max_outer,
                    max_inner=intent.max_inner,
                    token_budget=budget or 0,
                )
                state_store.transition("running")

            arguments = f"spec {intent.spec_id} strategy={strategy_id} {intent.mode} mode"
            if intent.task_description:
                arguments += f"\n\n{intent.task_description}"
            if spec.context:
                arguments += f"\n\n{spec.context}"

            llm_provider = (
                ClaudeCliProvider(self._config)
                if self._config.llm.enabled
                else None
            )

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
            )

            result = controller.run_loop(
                max_outer=intent.max_outer,
                max_inner=intent.max_inner,
                token_budget=budget,
                build_command=spec.build_command,
                strategy_context=spec.context,
                build_prompt=build_prompt,
            )

            # Phase 2: visual loop — only when Phase 1 converged via Docker sandbox.
            # Skipped when LLM provider ran Phase 1: the LLM already verified tests
            # locally (including Playwright if present), and the Docker visual loop
            # has no access to the LLM-managed worktree after it is committed.
            if (
                result.status == "converged"
                and self._config.visual_tests.enabled
                and llm_provider is None
            ):

                worktree_path = self._gitops.get_latest_worktree(
                    intent.spec_id, strategy_id, build_id=self._build_id,
                )
                visual_controller = VisualRalphController(
                    provider=self._provider,
                    config=self._config,
                    spec_id=intent.spec_id,
                    strategy_id=strategy_id,
                    base_dir=self._base_dir,
                )
                visual_result = visual_controller.run_loop(
                    worktree_path=worktree_path or str(self._base_dir),
                    token_budget=budget,
                )
                # Visual result supersedes Phase 1 result as the final verdict
                result = LoopResult(
                    status=visual_result.status,
                    termination_reason=visual_result.termination_reason,
                    outer_iterations=result.outer_iterations + visual_result.outer_iterations,
                    inner_iterations=result.inner_iterations,
                    pr_url=result.pr_url,
                    tokens_used=result.tokens_used + visual_result.tokens_used,
                    final_verify=visual_result.final_verify,
                )

            # Phase 3: review loop — only when converged, review_loop enabled,
            # and a PR host is configured. Option A: coordinator owns the
            # Phase 1 → Phase 3 → Phase 1 re-entry loop.
            if (
                result.status == "converged"
                and self._config.review_loop.enabled
                and self._config.pr_host != "none"
            ):
                pr_url = result.pr_url
                if not pr_url:
                    logger.warning(
                        "review_loop enabled but Phase 1 produced no pr_url "
                        "for %s/%s — skipping Phase 3",
                        intent.spec_id, strategy_id,
                    )
                else:
                    review_controller = ReviewLoopController(
                        gitops=self._gitops,
                        config=self._config,
                        spec_id=intent.spec_id,
                        strategy_id=strategy_id,
                        base_dir=str(self._base_dir),
                        build_id=self._build_id,
                    )
                    for _ in range(self._config.review_loop.max_fix_iterations):
                        worktree_path = self._gitops.get_latest_worktree(
                            intent.spec_id, strategy_id, build_id=self._build_id,
                        )
                        review_result = review_controller.run_loop(
                            pr_url=pr_url,
                            worktree_path=worktree_path or str(self._base_dir),
                            token_budget=budget,
                        )
                        result = LoopResult(
                            status=review_result.status,
                            termination_reason=review_result.termination_reason,
                            outer_iterations=result.outer_iterations + review_result.outer_iterations,
                            inner_iterations=result.inner_iterations,
                            pr_url=review_result.pr_url or result.pr_url,
                            tokens_used=result.tokens_used + review_result.tokens_used,
                            final_verify=result.final_verify,
                        )
                        if review_result.status != "review_fix_queued":
                            break
                        # echelon.review queued new fix tasks — re-run Phase 1
                        # Inject all review-fix content so Claude knows what to address.
                        reentry_prompt = self._build_reentry_prompt(
                            build_prompt, intent.spec_id,
                        )
                        result = controller.run_loop(
                            max_outer=intent.max_outer,
                            max_inner=intent.max_inner,
                            token_budget=budget,
                            build_command=spec.build_command,
                            strategy_context=spec.context,
                            build_prompt=reentry_prompt,
                        )
                        if result.status != "converged":
                            break

            return result

        finally:
            state_store.release_lock()

    def _build_reentry_prompt(self, base_prompt: str, spec_id: str) -> str:
        """Augment build prompt with review-fix content from the feature branch.

        Reads all review-fix-*.md files from the feature branch (named
        {spec_id}-{spec_name}) via git-show so the worktree stays on main.
        Returns the original prompt unchanged if no review-fix files exist.
        """
        import subprocess as _sp

        spec_dirs = sorted(Path(self._base_dir).glob(f"specs/{spec_id}-*"))
        if not spec_dirs:
            return base_prompt
        spec_name = spec_dirs[0].name          # e.g. "005-fix-photo-text-overlay"
        feature_branch = spec_name             # branch name matches spec dir name

        try:
            ls = _sp.run(
                ["git", "ls-tree", "--name-only", "-r", feature_branch,
                 f"specs/{spec_name}/"],
                capture_output=True, text=True,
                cwd=str(self._base_dir), timeout=10,
            )
            review_fix_paths = sorted(
                p for p in ls.stdout.splitlines() if "review-fix-" in p
            )
            if not review_fix_paths:
                return base_prompt

            parts = []
            for path in review_fix_paths:
                show = _sp.run(
                    ["git", "show", f"{feature_branch}:{path}"],
                    capture_output=True, text=True,
                    cwd=str(self._base_dir), timeout=10,
                )
                if show.returncode == 0 and show.stdout.strip():
                    parts.append(show.stdout.strip())

            if not parts:
                return base_prompt

            review_content = "\n\n---\n\n".join(parts)
            return (
                f"{base_prompt}\n\n"
                f"## Review Feedback (address these before completing the build)\n"
                f"{review_content}"
            )
        except Exception as e:
            logger.warning("Could not read review-fix content: %s", e)
            return base_prompt

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
