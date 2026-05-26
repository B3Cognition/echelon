"""RalphController — outer/inner ralph-loop orchestration.

Per ralph-controller.md contract:
  Outer loop: build -> verify -> feedback
  Inner loop: fix -> re-verify
  Termination: converged, outer_cap, budget, same_failure, SIGTERM, cancel

Per FR-LOOP-001: outer loop
Per FR-LOOP-002: inner loop
Per FR-LOOP-003a/b: same-failure detection and escalation
Per FR-LOOP-004: termination conditions
Per FR-LOOP-005: escalation protocol
Per FR-STRATEGY-004b: cancel_requested check between exec calls
"""

from __future__ import annotations

import json
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness.config import HarnessConfig
from harness.llm_provider import ClaudeCliProvider
from harness.escalation import EscalationHandler
from harness.exec_result import ExecResult
from harness.failure_signature import detect_same_failure, normalize
from harness.loop_result import LoopResult
from harness.mode import ModeController
from harness.provider import SandboxHandle, SandboxProvider, SandboxSpec
from harness.state import StateStore
from harness.verify_result import FailureCategory, FailureEntry, VerifyResult

logger = logging.getLogger(__name__)


class RalphController:
    """Orchestrates the ralph-loop for one strategy.

    Per-strategy loop controller. Manages the outer/inner iteration loop,
    state transitions, termination conditions, and escalation.
    """

    def __init__(
        self,
        provider: SandboxProvider,
        gitops: Any,  # GitOpsManager (type hint avoids circular import)
        state_store: StateStore,
        mode_controller: ModeController,
        escalation_handler: EscalationHandler,
        spec_id: str,
        strategy_id: str,
        config: HarnessConfig,
        llm_provider: Optional[ClaudeCliProvider] = None,
    ) -> None:
        self._provider = provider
        self._gitops = gitops
        self._state_store = state_store
        self._mode = mode_controller
        self._escalation = escalation_handler
        self._spec_id = spec_id
        self._strategy_id = strategy_id
        self._config = config
        self._llm_provider = llm_provider

        self._interrupted = False
        self._original_sigterm: Any = None
        self._original_sigint: Any = None

    # === Main entry point ===

    def run_loop(
        self,
        max_outer: int = 5,
        max_inner: int = 3,
        token_budget: Optional[int] = None,
        build_command: str = "echelon build",
        strategy_context: str = "",
        build_prompt: str = "",
    ) -> LoopResult:
        """Execute the ralph-loop until a termination condition.

        Args:
            max_outer: Maximum outer iterations.
            max_inner: Maximum inner iterations per outer.
            token_budget: Total token budget (None = unlimited).
            build_command: Shell command to invoke for the build phase.
                Defaults to ``echelon build``. Override via strategy file
                frontmatter (``command: echelon codegen``).
            strategy_context: Additional context from strategy file body.

        Returns:
            LoopResult with termination details.
        """
        self._install_signal_handlers()

        try:
            return self._run_loop_inner(
                max_outer=max_outer,
                max_inner=max_inner,
                token_budget=token_budget,
                build_command=build_command,
                strategy_context=strategy_context,
                build_prompt=build_prompt,
            )
        finally:
            self._restore_signal_handlers()

    def _run_loop_inner(
        self,
        max_outer: int,
        max_inner: int,
        token_budget: Optional[int],
        build_command: str,
        strategy_context: str,
        build_prompt: str = "",
    ) -> LoopResult:
        """Inner implementation of run_loop (signal handlers installed)."""
        state = self._state_store.read()
        if not state:
            raise RuntimeError("State not initialized. Call state_store.initialize() first.")

        # Handle resume from blocked/interrupted state
        current_status = state.get("status", "initialized")
        if current_status == "blocked":
            return self._handle_blocked_resume(state, max_outer, max_inner, token_budget, build_command, strategy_context, build_prompt)
        if current_status == "interrupted":
            # Resume from interrupted: restart from current counters
            logger.info("Resuming from interrupted state")

        # Transition to running
        if current_status in ("initialized", "interrupted"):
            state = self._state_store.transition("running")
            # Clear stale cancel_requested set by a prior SIGINT — it persists across process
            # invocations and would cause immediate killed_by_coordinator exit on next run.
            if state.get("cancel_requested"):
                state["cancel_requested"] = False
                self._state_store.write(state)

        total_inner_iterations = 0
        pr_url = state.get("pr_url")
        tokens_used = state.get("tokens_used", 0)
        start_outer = state.get("outer_iter", 0)
        last_verify_failures_text: str = ""
        final_verify: Optional[VerifyResult] = None  # tracks last known verify across outer iters

        for outer_iter in range(start_outer, max_outer):
            # Check termination conditions
            termination = self._check_termination(
                tokens_used=tokens_used,
                token_budget=token_budget,
            )
            if termination:
                term_status = "cancelled" if termination == "killed_by_coordinator" else (
                    "interrupted" if termination == "user_cancel" else "failed"
                )
                return self._finalize(
                    status=term_status,
                    reason=termination,
                    outer_iterations=outer_iter,
                    inner_iterations=total_inner_iterations,
                    pr_url=pr_url,
                    tokens_used=tokens_used,
                    final_verify=None,
                )

            # Create worktree
            worktree_path = self._gitops.create_worktree(
                self._spec_id, self._strategy_id, outer_iter,
            )

            try:
                # Create sandbox
                sandbox_spec = self._build_sandbox_spec(worktree_path, outer_iter)
                handle = self._provider.create(sandbox_spec)

                try:
                    # Run build
                    iter_prompt = self._make_iter_prompt(build_prompt, outer_iter, last_verify_failures_text)
                    build_result = self._exec_build(
                        handle, build_command, strategy_context,
                        worktree_path=worktree_path,
                        prompt=iter_prompt,
                    )
                    tokens_used += build_result.get("tokens", 0)

                    # Log build iteration
                    self._append_iteration_log(
                        state, outer_iter, 0, "build",
                        build_result.get("exit_code", 0),
                        build_result.get("passed", True),
                        build_result.get("duration_s", 0.0),
                        build_result.get("tokens", 0),
                    )

                    # Check mode boundary
                    if self._mode.should_pause_at_boundary("after_build"):
                        return self._pause_at_boundary(
                            "after_build", outer_iter, total_inner_iterations,
                            pr_url, tokens_used,
                        )

                    # Check termination after build — catches SIGINT that fired during
                    # the build phase, which check_cancel() alone does not detect.
                    termination = self._check_termination(tokens_used, token_budget)
                    if termination:
                        term_status = (
                            "interrupted" if termination == "user_cancel"
                            else "cancelled" if termination == "killed_by_coordinator"
                            else "failed"
                        )
                        return self._finalize(
                            status=term_status,
                            reason=termination,
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=None,
                        )

                    # Run verify
                    verify_result = self._exec_verify(handle, worktree_path=worktree_path)
                    tokens_used += verify_result.token_usage

                    # Log verify iteration
                    self._append_iteration_log(
                        state, outer_iter, 0, "verify",
                        0 if verify_result.passed else 1,
                        verify_result.passed,
                        verify_result.duration_s,
                        verify_result.token_usage,
                        failure_signatures=[
                            normalize(f.category.value, f.id, f.error)
                            for f in verify_result.failures
                        ],
                    )

                    if self._mode.should_pause_at_boundary("after_verify"):
                        return self._pause_at_boundary(
                            "after_verify", outer_iter, total_inner_iterations,
                            pr_url, tokens_used, verify_result,
                        )

                    if verify_result.passed:
                        # Converged!
                        # Commit and push
                        self._commit_and_push(worktree_path, outer_iter)

                        # Create/promote PR
                        pr_url = self._manage_pr(pr_url, outer_iter, converged=True)

                        return self._finalize(
                            status="converged",
                            reason="converged",
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=verify_result,
                        )

                    # Inner loop
                    inner_result = self._run_inner_loop(
                        handle=handle,
                        verify_result=verify_result,
                        outer_iter=outer_iter,
                        max_inner=max_inner,
                        tokens_used=tokens_used,
                        token_budget=token_budget,
                        state=state,
                        build_command=build_command,
                        strategy_context=strategy_context,
                        worktree_path=worktree_path,
                        build_prompt=build_prompt,
                    )
                    tokens_used = inner_result["tokens_used"]
                    total_inner_iterations += inner_result["inner_count"]

                    final_verify = inner_result.get("final_verify")
                    if final_verify and final_verify.failures:
                        last_verify_failures_text = "\n".join(
                            f"[{f.category.value}] {f.id}: {f.error}"
                            for f in final_verify.failures
                        )

                    if inner_result["converged"]:
                        self._commit_and_push(worktree_path, outer_iter)
                        pr_url = self._manage_pr(pr_url, outer_iter, converged=True)
                        return self._finalize(
                            status="converged",
                            reason="converged",
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=inner_result.get("final_verify"),
                        )

                    if inner_result.get("blocked"):
                        return self._finalize(
                            status="blocked",
                            reason="blocker_escalation",
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=inner_result.get("final_verify"),
                        )

                    # Inner loop exhausted -- commit progress and continue outer
                    self._commit_and_push(worktree_path, outer_iter)
                    pr_url = self._manage_pr(pr_url, outer_iter, converged=False)

                finally:
                    self._provider.destroy(handle)

            finally:
                # Keep last worktree (FR-REPO-003b)
                if outer_iter < max_outer - 1:
                    self._gitops.destroy_worktree(worktree_path, keep_branch=True)

            # Update state after each iteration
            state = self._state_store.read()
            state["outer_iter"] = outer_iter + 1
            state["tokens_used"] = tokens_used
            state["pr_url"] = pr_url
            self._state_store.write(state)

        # Outer cap reached
        return self._finalize(
            status="failed",
            reason="outer_cap",
            outer_iterations=max_outer,
            inner_iterations=total_inner_iterations,
            pr_url=pr_url,
            tokens_used=tokens_used,
            final_verify=final_verify,
        )

    # === Inner loop ===

    def _run_inner_loop(
        self,
        handle: SandboxHandle,
        verify_result: VerifyResult,
        outer_iter: int,
        max_inner: int,
        tokens_used: int,
        token_budget: Optional[int],
        state: Dict[str, Any],
        build_command: str,
        strategy_context: str,
        worktree_path: str = "",
        build_prompt: str = "",
    ) -> Dict[str, Any]:
        """Run inner fix-verify loop.

        Returns dict with: converged, blocked, inner_count, tokens_used, final_verify.
        """
        failure_history: List[List[str]] = []
        current_verify = verify_result

        for inner_iter in range(1, max_inner + 1):
            # Check termination (covers both SIGINT and coordinator cancel)
            termination = self._check_termination(tokens_used, token_budget)
            if termination:
                return {
                    "converged": False,
                    "blocked": False,
                    "inner_count": inner_iter - 1,
                    "tokens_used": tokens_used,
                    "final_verify": current_verify,
                }

            # Compute failure signatures
            signatures = [
                normalize(f.category.value, f.id, f.error)
                for f in current_verify.failures
            ]
            failure_history.append(signatures)

            # Check same-failure detection (FR-LOOP-003a)
            same_failures = detect_same_failure(failure_history, threshold=3)
            if same_failures:
                if self._mode.should_escalate("same_failure_repeat"):
                    self._escalation.escalate(
                        spec_id=self._spec_id,
                        strategy_id=self._strategy_id,
                        category="same_failure_repeat",
                        context=(
                            f"Same failure detected {len(same_failures)} time(s) "
                            f"in inner loop at outer_iter={outer_iter}, "
                            f"inner_iter={inner_iter}."
                        ),
                        last_verify_result=_verify_to_dict(current_verify),
                    )
                    return {
                        "converged": False,
                        "blocked": True,
                        "inner_count": inner_iter,
                        "tokens_used": tokens_used,
                        "final_verify": current_verify,
                    }
                else:
                    logger.info(
                        "Same failure detected but mode %s does not escalate",
                        self._mode.mode,
                    )

            # Run feedback (fix)
            feedback_prompt = self._make_feedback_prompt(build_prompt, current_verify, inner_iter)
            fix_result = self._exec_feedback(
                handle, current_verify, build_command, strategy_context,
                worktree_path=worktree_path,
                prompt=feedback_prompt,
            )
            tokens_used += fix_result.get("tokens", 0)

            self._append_iteration_log(
                state, outer_iter, inner_iter, "fix",
                fix_result.get("exit_code", 0),
                fix_result.get("passed", True),
                fix_result.get("duration_s", 0.0),
                fix_result.get("tokens", 0),
            )

            # Check termination
            termination = self._check_termination(
                tokens_used=tokens_used, token_budget=token_budget,
            )
            if termination:
                return {
                    "converged": False,
                    "blocked": False,
                    "inner_count": inner_iter,
                    "tokens_used": tokens_used,
                    "final_verify": current_verify,
                }

            # Re-verify
            current_verify = self._exec_verify(handle, worktree_path=worktree_path)
            tokens_used += current_verify.token_usage

            self._append_iteration_log(
                state, outer_iter, inner_iter, "verify",
                0 if current_verify.passed else 1,
                current_verify.passed,
                current_verify.duration_s,
                current_verify.token_usage,
                failure_signatures=[
                    normalize(f.category.value, f.id, f.error)
                    for f in current_verify.failures
                ],
            )

            if current_verify.passed:
                return {
                    "converged": True,
                    "blocked": False,
                    "inner_count": inner_iter,
                    "tokens_used": tokens_used,
                    "final_verify": current_verify,
                }

        # Inner loop exhausted
        return {
            "converged": False,
            "blocked": False,
            "inner_count": max_inner,
            "tokens_used": tokens_used,
            "final_verify": current_verify,
        }

    # === Termination check ===

    def check_cancel(self) -> bool:
        """Check cancel_requested flag in state file (FR-STRATEGY-004b)."""
        state = self._state_store.read()
        return state.get("cancel_requested", False)

    def _check_termination(
        self,
        tokens_used: int,
        token_budget: Optional[int],
    ) -> Optional[str]:
        """Check all termination conditions.

        Returns termination reason or None.
        """
        # SIGTERM/SIGINT
        if self._interrupted:
            return "user_cancel"

        # Cancel requested
        if self.check_cancel():
            return "killed_by_coordinator"

        # Budget exhaustion (95% threshold)
        if token_budget is not None and token_budget > 0:
            if tokens_used >= token_budget * 0.95:
                return "budget_exhausted"

        return None

    # === Sandbox execution helpers ===

    def _exec_build(
        self,
        handle: SandboxHandle,
        build_command: str,
        strategy_context: str,
        worktree_path: str = "",
        prompt: str = "",
    ) -> Dict[str, Any]:
        """Execute the strategy's build command in sandbox or via LLM provider.

        When ``llm_provider`` is set and both ``worktree_path`` and ``prompt``
        are non-empty, delegates to ``llm_provider.exec_build``.  Otherwise
        falls back to the sandbox provider path.

        Args:
            handle: Active sandbox handle.
            build_command: Command to run (e.g. ``echelon build`` or
                ``echelon codegen``). Declared via strategy file frontmatter.
            strategy_context: Additional context injected via STRATEGY_CONTEXT
                env var. Empty string = no injection.
            worktree_path: Path to the git worktree (LLM provider path only).
            prompt: Prompt text for the LLM (LLM provider path only).

        Returns:
            Dict with exit_code, passed, duration_s, tokens, impasse,
            impasse_file.
        """
        if self._llm_provider and worktree_path and prompt:
            result = self._llm_provider.exec_build(worktree_path, prompt)
            return {
                "exit_code": result.exit_code,
                "passed": result.succeeded,
                "duration_s": result.duration_ms / 1000.0,
                "tokens": 0,
                "impasse": result.is_impasse,
                "impasse_file": result.impasse_file,
            }
        # Fallback: original sandbox path
        cmd = build_command
        if strategy_context:
            cmd = f"STRATEGY_CONTEXT='{strategy_context}' {cmd}"

        result = self._provider.exec(handle, cmd, timeout_ms=1_200_000)
        return {
            "exit_code": result.exit_code,
            "passed": result.exit_code == 0,
            "duration_s": result.duration_ms / 1000.0,
            "tokens": _estimate_tokens(result),
            "impasse": False,
            "impasse_file": None,
        }

    def _exec_verify(self, handle: SandboxHandle, worktree_path: str = "") -> VerifyResult:
        """Execute verification.

        When llm_provider is set and worktree_path is provided, runs verification
        locally on the host via the detected package manager's install + test + build
        commands (avoids Docker networking issues where the internal network blocks
        package downloads). Falls back to sandbox provider path otherwise.

        Returns parsed VerifyResult.
        """
        if self._llm_provider and worktree_path:
            return self._exec_verify_locally(worktree_path)

        result = self._provider.exec(handle, "echelon verify", timeout_ms=600_000)

        # Parse verify result from stdout
        try:
            data = json.loads(result.stdout)
            return VerifyResult.from_dict(data)
        except (json.JSONDecodeError, Exception):
            # If parsing fails, create a failed VerifyResult
            return VerifyResult(
                passed=result.exit_code == 0,
                failures=[],
                duration_s=result.duration_ms / 1000.0,
                token_usage=_estimate_tokens(result),
            )

    def _exec_verify_locally(self, worktree_path: str) -> VerifyResult:
        """Run verification locally on the host when LLM provider is active.

        Detects the package manager from lockfiles and runs the appropriate
        install + test + build commands in the worktree directory.
        worktrees don't inherit node_modules from the parent repo.

        For Python projects (pyproject.toml / setup.py / requirements.txt present
        but no package.json), runs verify.sh if it exists, otherwise falls back
        to ``python -m pytest``.

        Returns VerifyResult with structured failures when tests fail.
        """
        import subprocess
        import time

        failures = []
        start = time.monotonic()

        wt = Path(worktree_path)

        # Explicit override: verify_command in config takes priority over detection.
        # Run from project root (base_dir) so test paths resolve against the actual
        # source tree (e.g. echelon/ submodule), not the worktree which may only contain
        # generated spec-repo artifacts.
        if self._config.verify_command:
            import subprocess as _sp
            cmd = self._config.verify_command.split()
            verify_cwd = str(getattr(self._gitops, "base_dir", None) or worktree_path)
            try:
                res = _sp.run(cmd, cwd=verify_cwd, capture_output=True, text=True, timeout=300)
                if res.returncode != 0:
                    out = (res.stdout + res.stderr).strip()
                    failures.append(FailureEntry(
                        category=FailureCategory.TEST,
                        id="verify-command",
                        error=out[-2000:] if len(out) > 2000 else out,
                    ))
            except Exception as e:
                failures.append(FailureEntry(
                    category=FailureCategory.OTHER, id="verify-command-error", error=str(e),
                ))
            duration_s = time.monotonic() - start
            return VerifyResult(passed=not failures, failures=failures, duration_s=duration_s)

        # Python project: skip all npm/pnpm/yarn steps, delegate to verify.sh
        # Python takes priority over Node when both pyproject.toml and package.json exist
        # (e.g., a full-stack project where the primary runtime is Python).
        has_python_markers = (
            (wt / "pyproject.toml").exists()
            or (wt / "setup.py").exists()
            or (wt / "requirements.txt").exists()
            or any(wt.glob("test_*.py"))
            or any(wt.glob("*_test.py"))
        )
        is_node = (wt / "package.json").exists() and not has_python_markers
        is_python = has_python_markers

        if is_python:
            return self._exec_verify_python(worktree_path, start)

        if (wt / "pnpm-lock.yaml").exists():
            commands = [
                ("install", "pnpm install --frozen-lockfile --ignore-scripts"),
                ("test", "pnpm test"),
                ("build", "pnpm run build"),
            ]
        elif (wt / "yarn.lock").exists():
            commands = [
                ("install", "yarn install --frozen-lockfile"),
                ("test", "yarn test"),
                ("build", "yarn run build"),
            ]
        elif is_node:
            commands = [
                ("install", "npm ci"),
                ("test", "npm test"),
                ("build", "npm run build"),
            ]
        else:
            # Unknown project type — cannot verify locally.
            # Return passed=False so the harness does not falsely claim convergence.
            # Users can add a verify_command to echelon-config.yml to enable verification.
            logger.warning(
                "Cannot detect project type in %s; local verification skipped",
                worktree_path,
            )
            return VerifyResult(
                passed=False,
                failures=[FailureEntry(
                    category=FailureCategory.BUILD,
                    id="local-verify-skipped",
                    error=(
                        f"Cannot detect project type in {worktree_path}; "
                        "local verification skipped. "
                        "Add verify_command to echelon-config.yml to enable verification."
                    ),
                )],
                duration_s=0.0,
            )

        for stage, cmd in commands:
            try:
                result = subprocess.run(
                    cmd.split(),
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode != 0:
                    output = (result.stdout + result.stderr).strip()
                    failures.append(FailureEntry(
                        category=FailureCategory.BUILD if stage in ("build", "install") else FailureCategory.TEST,
                        id=f"local-{stage}",
                        error=output[-2000:] if len(output) > 2000 else output,
                    ))
                    # Don't run further stages if install or test fails
                    if stage in ("install", "test"):
                        break
            except subprocess.TimeoutExpired:
                failures.append(FailureEntry(
                    category=FailureCategory.BUILD if stage in ("build", "install") else FailureCategory.TEST,
                    id=f"local-{stage}-timeout",
                    error=f"{cmd} timed out after 300 seconds",
                ))
                break
            except Exception as e:
                failures.append(FailureEntry(
                    category=FailureCategory.OTHER,
                    id=f"local-{stage}-error",
                    error=str(e),
                ))
                break

        duration_s = time.monotonic() - start
        return VerifyResult(
            passed=len(failures) == 0,
            failures=failures,
            duration_s=duration_s,
        )

    def _exec_verify_python(self, worktree_path: str, start: float) -> VerifyResult:
        """Run Python verification using uv (if uv.lock present) or pytest.

        verify.sh is Docker-specific (mounts /workspace) and is NOT executed
        on the host; instead this method runs the test suite directly.

        Priority:
          1. ``uv run pytest`` when uv.lock exists in the worktree
          2. ``python -m pytest`` otherwise
        """
        import subprocess
        import time
        import shutil

        failures = []
        wt = Path(worktree_path)

        # Prefer uv when a lockfile is present (handles venv + deps automatically)
        use_uv = (wt / "uv.lock").exists() and shutil.which("uv") is not None

        _pytest_args = ["--tb=short", "-q", "--no-header", "--override-ini=addopts=",
                        "--ignore=tests/test_playwright"]
        pytest_bin = shutil.which("pytest")
        pytest_cmd = (
            ["uv", "run", "--no-sync", "pytest"] + _pytest_args
            if use_uv
            else ([pytest_bin] + _pytest_args
                  if pytest_bin
                  else ["python", "-m", "pytest"] + _pytest_args)
        )

        try:
            result = subprocess.run(
                pytest_cmd,
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                output = (result.stdout + result.stderr).strip()
                failures.append(FailureEntry(
                    category=FailureCategory.TEST,
                    id="pytest",
                    error=output[-2000:] if len(output) > 2000 else output,
                ))
        except subprocess.TimeoutExpired:
            failures.append(FailureEntry(
                category=FailureCategory.TEST,
                id="pytest-timeout",
                error="pytest timed out after 300 seconds",
            ))
        except Exception as e:
            failures.append(FailureEntry(
                category=FailureCategory.OTHER,
                id="pytest-error",
                error=str(e),
            ))

        duration_s = time.monotonic() - start
        return VerifyResult(
            passed=len(failures) == 0,
            failures=failures,
            duration_s=duration_s,
        )

    def _exec_feedback(
        self,
        handle: SandboxHandle,
        verify_result: VerifyResult,
        build_command: str,
        strategy_context: str,
        worktree_path: str = "",
        prompt: str = "",
    ) -> Dict[str, Any]:
        """Execute feedback (fix) step in sandbox or via LLM provider.

        When ``llm_provider`` is set and both ``worktree_path`` and ``prompt``
        are non-empty, delegates to ``llm_provider.exec_feedback``.  Otherwise
        falls back to the sandbox provider path.

        Returns dict with exit_code, passed, duration_s, tokens.
        """
        if self._llm_provider and worktree_path and prompt:
            result = self._llm_provider.exec_feedback(worktree_path, prompt)
            return {
                "exit_code": result.exit_code,
                "passed": result.succeeded,
                "duration_s": result.duration_ms / 1000.0,
                "tokens": 0,
                "impasse": result.is_impasse,
                "impasse_file": result.impasse_file,
            }
        # Fallback: original sandbox path
        failures_json = json.dumps([
            {"category": f.category.value, "id": f.id, "error": f.error}
            for f in verify_result.failures
        ])

        # Derive feedback command: use build_command base + --fix flag
        base = build_command.split()[0] if build_command else "echelon"
        subcommand = build_command.split()[1] if len(build_command.split()) > 1 else "build"
        cmd = f"{base} {subcommand} --fix --failures '{failures_json}'"
        if strategy_context:
            cmd = f"STRATEGY_CONTEXT='{strategy_context}' {cmd}"

        result = self._provider.exec(handle, cmd, timeout_ms=1_200_000)
        return {
            "exit_code": result.exit_code,
            "passed": result.exit_code == 0,
            "duration_s": result.duration_ms / 1000.0,
            "tokens": _estimate_tokens(result),
            "impasse": False,
            "impasse_file": None,
        }

    def _make_iter_prompt(self, base: str, outer_iter: int, last_failures: str) -> str:
        """Augment base prompt with iteration context for outer loop."""
        if not base:
            return ""
        if outer_iter == 0 or not last_failures:
            return base
        return (
            f"{base}\n\n"
            f"This is iteration {outer_iter}. "
            f"Previous build failed with:\n{last_failures}"
        )

    def _make_feedback_prompt(self, base: str, verify_result: VerifyResult, inner_iter: int) -> str:
        """Construct targeted feedback prompt from base prompt + verify failures."""
        if not base:
            return ""
        failures_text = "\n".join(
            f"[{f.category.value}] {f.id}: {f.error}"
            for f in verify_result.failures
        )
        return (
            f"{base}\n\n"
            f"Inner fix {inner_iter}. Fix these verification failures "
            f"without re-running the full build pipeline:\n{failures_text}"
        )

    # === Git operations ===

    def _commit_and_push(self, worktree_path: str, outer_iter: int) -> None:
        """Commit all changes and push to remote.

        Uses the actual current branch of the worktree rather than a hardcoded
        harness/* pattern. In feature-branch mode (echelon flow) the worktree is
        checked out on the echelon feature branch (e.g. '001-weather-dashboard'),
        not on a harness/* branch — pushing the wrong name silently fails.
        """
        try:
            message = f"harness: {self._spec_id}/{self._strategy_id} iter-{outer_iter}"
            self._gitops.commit(worktree_path, message)

            # Detect the actual branch rather than assuming a harness/* name.
            # create_worktree() checks out the feature branch directly in
            # feature-branch mode, so we must read HEAD to get the real branch.
            from harness.gitops import _run_git  # local import to avoid circular
            result = _run_git(
                ["branch", "--show-current"],
                cwd=worktree_path,
                check=False,
            )
            branch = result.stdout.strip()
            if not branch:
                # Detached HEAD — fall back to legacy naming so we at least try
                branch = f"harness/{self._spec_id}-{self._strategy_id}-iter-{outer_iter}"
                logger.warning(
                    "Worktree at %s is in detached HEAD state; pushing as %s",
                    worktree_path, branch,
                )

            self._gitops.push(worktree_path, branch)
        except Exception as e:
            logger.warning("Commit/push failed: %s", e)

    def _manage_pr(self, pr_url: Optional[str], outer_iter: int, converged: bool) -> Optional[str]:
        """Create/update/promote PR as needed."""
        branch = f"harness/{self._spec_id}/{self._strategy_id}/iter-{outer_iter}"

        if pr_url is None:
            # First iteration: create draft PR
            pr_url = self._gitops.create_draft_pr(
                branch, self._spec_id, self._strategy_id,
            )
            if not pr_url:
                pr_url = None

        if converged and pr_url:
            self._gitops.promote_pr_ready(pr_url)

        return pr_url

    # === Sandbox spec builder ===

    def _build_sandbox_spec(self, worktree_path: str, outer_iter: int) -> SandboxSpec:
        """Build SandboxSpec from config and context."""
        from harness.provider import NetworkPolicy, ResourceLimits as ProviderResourceLimits

        return SandboxSpec(
            image=self._config.base_image or "python:3.9-slim",
            image_source="config_override" if self._config.base_image else "fingerprint",
            worktree_mount=worktree_path,
            container_mount="/workspace",
            resource_limits=ProviderResourceLimits(
                memory=self._config.resource_limits.memory,
                cpu=self._config.resource_limits.cpu,
                pids=self._config.resource_limits.pids,
                storage=self._config.resource_limits.storage,
            ),
            network_policy=NetworkPolicy(
                allowlist=self._config.network.allowlist,
                proxy_image=self._config.network.proxy_image,
            ),
            env={
                # SPEC_KIT_ROOT lets common.sh find .specify/ when walking up from /workspace
                # is blocked by the container boundary (e.g. Docker).
                # ECHELON_HARNESS_RUN tells spec-kit scripts to skip branch-name validation
                # since branch management is the harness's responsibility.
                "SPEC_KIT_ROOT": str(self._gitops.base_dir),
                "ECHELON_HARNESS_RUN": "1",
            },
            secrets_env={},
            post_create_command=None,
            forward_ports=[],
            labels={
                "strategy_id": self._strategy_id,
                "spec_id": self._spec_id,
                "run_id": str(outer_iter),
            },
        )

    # === State helpers ===

    def _append_iteration_log(
        self,
        state: Dict[str, Any],
        outer_iter: int,
        inner_iter: int,
        phase: str,
        exit_code: int,
        passed: bool,
        duration_s: float,
        tokens: int,
        failure_signatures: Optional[List[str]] = None,
    ) -> None:
        """Append entry to iteration_log in state."""
        fresh_state = self._state_store.read()
        log = fresh_state.get("iteration_log", [])
        entry = {
            "outer_iter": outer_iter,
            "inner_iter": inner_iter,
            "phase": phase,
            "exit_code": exit_code,
            "passed": passed,
            "duration_s": duration_s,
            "tokens": tokens,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if failure_signatures:
            entry["failure_signatures"] = failure_signatures
        log.append(entry)
        fresh_state["iteration_log"] = log
        # Only update counters if they increase (monotonic invariant)
        if outer_iter > fresh_state.get("outer_iter", 0):
            fresh_state["outer_iter"] = outer_iter
        if inner_iter > fresh_state.get("inner_iter", 0):
            fresh_state["inner_iter"] = inner_iter
        self._state_store.write(fresh_state)

    def _finalize(
        self,
        status: str,
        reason: str,
        outer_iterations: int,
        inner_iterations: int,
        pr_url: Optional[str],
        tokens_used: int,
        final_verify: Optional[VerifyResult],
    ) -> LoopResult:
        """Write final state and return LoopResult."""
        # Map to state status
        state_status_map = {
            "converged": "converged",
            "failed": "failed",
            "blocked": "blocked",
            "interrupted": "interrupted",
            "cancelled": "cancelled_by_coordinator",
        }
        state_status = state_status_map.get(status, "failed")

        try:
            state = self._state_store.read()
            current = state.get("status", "running")
            # Only transition if valid
            if current == "running" or (current == "blocked" and state_status == "running"):
                self._state_store.transition(state_status)

            # Update additional fields
            state = self._state_store.read()
            state["tokens_used"] = tokens_used
            state["pr_url"] = pr_url
            state["termination_reason"] = reason
            state["last_verify_result"] = (
                _verify_to_dict(final_verify) if final_verify else None
            )
            self._state_store.write(state)
        except Exception as e:
            logger.warning("Failed to update final state: %s", e)

        return LoopResult(
            status=status,
            termination_reason=reason,
            outer_iterations=outer_iterations,
            inner_iterations=inner_iterations,
            pr_url=pr_url,
            tokens_used=tokens_used,
            final_verify=final_verify,
        )

    def _pause_at_boundary(
        self,
        boundary: str,
        outer_iter: int,
        inner_iterations: int,
        pr_url: Optional[str],
        tokens_used: int,
        verify_result: Optional[VerifyResult] = None,
    ) -> LoopResult:
        """Pause at a phase boundary (guided mode)."""
        logger.info("Paused at %s boundary (guided mode)", boundary)

        state = self._state_store.read()
        state["tokens_used"] = tokens_used
        state["pr_url"] = pr_url
        self._state_store.write(state)
        self._state_store.transition("blocked")

        print(
            f"Paused at {boundary} boundary -- resume to continue",
            file=sys.stderr,
        )

        return LoopResult(
            status="blocked",
            termination_reason="blocker_escalation",
            outer_iterations=outer_iter + 1,
            inner_iterations=inner_iterations,
            pr_url=pr_url,
            tokens_used=tokens_used,
            final_verify=verify_result,
        )

    def _handle_blocked_resume(
        self,
        state: Dict[str, Any],
        max_outer: int,
        max_inner: int,
        token_budget: Optional[int],
        build_command: str,
        strategy_context: str,
        build_prompt: str = "",
    ) -> LoopResult:
        """Handle resume from blocked state."""
        escalation_file = state.get("escalation_file")
        if escalation_file:
            answer = self._escalation.check_resume(escalation_file)
            if answer:
                # Resume with answer
                self._state_store.transition("running")
                # Inject answer into strategy context
                augmented_context = f"RESUME ANSWER: {answer}\n\n{strategy_context}"
                return self._run_loop_inner(
                    max_outer=max_outer,
                    max_inner=max_inner,
                    token_budget=token_budget,
                    build_command=build_command,
                    strategy_context=augmented_context,
                    build_prompt=build_prompt,
                )
            else:
                _print_blocked_banner(
                    spec_id=self._spec_id,
                    strategy_id=self._strategy_id,
                    escalation_file=escalation_file,
                )
                return LoopResult(
                    status="blocked",
                    termination_reason="blocker_escalation",
                    outer_iterations=state.get("outer_iter", 0),
                    inner_iterations=state.get("inner_iter", 0),
                    tokens_used=state.get("tokens_used", 0),
                    pr_url=state.get("pr_url"),
                    final_verify=None,
                )
        else:
            # Blocked without escalation file (e.g., guided mode pause)
            self._state_store.transition("running")
            return self._run_loop_inner(
                max_outer=max_outer,
                max_inner=max_inner,
                token_budget=token_budget,
                build_command=build_command,
                strategy_context=strategy_context,
                build_prompt=build_prompt,
            )

    # === Signal handling ===

    def _install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT handlers for graceful interruption.

        Signal handlers can only be installed from the main thread.
        When running in a worker thread (e.g., via StrategyCoordinator's
        ThreadPoolExecutor), skip signal installation. The controller
        will rely on cancel_requested checks via state file instead.
        """
        import threading

        if threading.current_thread() is not threading.main_thread():
            logger.debug(
                "Skipping signal handler installation (not main thread). "
                "Cancellation will use cancel_requested state flag."
            )
            return

        self._original_sigterm = signal.getsignal(signal.SIGTERM)
        self._original_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _restore_signal_handlers(self) -> None:
        """Restore original signal handlers."""
        import threading

        if threading.current_thread() is not threading.main_thread():
            return

        if self._original_sigterm is not None:
            signal.signal(signal.SIGTERM, self._original_sigterm)
        if self._original_sigint is not None:
            signal.signal(signal.SIGINT, self._original_sigint)

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handle SIGTERM/SIGINT for graceful interruption."""
        logger.warning("Received signal %d, setting interrupted flag", signum)
        self._interrupted = True


# === Utility functions ===

def _print_blocked_banner(spec_id: str, strategy_id: str, escalation_file: str) -> None:
    """Print a formatted blocked banner to stderr."""
    sep = "=" * 60
    print(f"\n{sep}", file=sys.stderr)
    print("  ✗  HARNESS RUN BLOCKED — escalation pending", file=sys.stderr)
    print(sep, file=sys.stderr)
    print(f"\n  Spec:      {spec_id}", file=sys.stderr)
    print(f"  Strategy:  {strategy_id}", file=sys.stderr)
    print(f"  File:      {escalation_file}", file=sys.stderr)
    print("\n  Answer with:  /speckit-harness-resume", file=sys.stderr)
    print(f"  Discard with: echelon harness run {spec_id} --reset\n", file=sys.stderr)
    print(sep, file=sys.stderr)


def _estimate_tokens(result: ExecResult) -> int:
    """Rough token estimate from ExecResult output length."""
    text_len = len(result.stdout) + len(result.stderr)
    return text_len // 4  # ~4 chars per token


def _verify_to_dict(verify: VerifyResult) -> Dict[str, Any]:
    """Convert VerifyResult to dict for state storage."""
    return {
        "passed": verify.passed,
        "failures": [
            {"category": f.category.value, "id": f.id, "error": f.error}
            for f in verify.failures
        ],
        "duration_s": verify.duration_s,
        "token_usage": verify.token_usage,
    }
