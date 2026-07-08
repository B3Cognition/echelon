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
import os
import re
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

from echelon.artifact_index import write_artifact_index
from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from harness.build_result import BUILD_STATUS_FILENAME
from harness.config import HarnessConfig
from harness.documentation_gate import evaluate_documentation_gate
from harness.llm_provider import AICodingCliProvider
from harness.escalation import EscalationHandler
from harness.exec_result import ExecResult
from harness.failure_signature import detect_same_failure, normalize
from harness.fulfillment_runner import FulfillmentRunner
from harness.llm_build_runner import LlmBuildRunner
from harness.loop_result import LoopResult
from harness.mode import ModeController
from harness.provider import SandboxHandle, SandboxProvider, SandboxSpec
from harness.run_history import append_implementation_run
from harness.phase_a_readiness import validate_phase_a_readiness
from harness.spec_frontmatter import find_spec_dir, write_status
from harness.state import StateStore
from harness.task_progress import (
    TaskProgressError,
    summarize_task_progress,
    update_task_progress_markdown,
)
from harness.verify_result import FailureCategory, FailureEntry, VerifyResult
from kernel.fulfillment import (
    blocking_statuses,
    fulfillment_has_blocking_gaps,
    fulfillment_report_is_current,
    latest_fulfillment_report,
    read_fulfillment_metadata,
)

logger = logging.getLogger(__name__)

SAME_FAILURE_REPEAT_THRESHOLD = 3

# Number of consecutive failed outer iterations with no file changes before
# escalating with a no-progress block.
_NO_PROGRESS_THRESHOLD = 2
_BANZAI_MILESTONE_DEFER_REASON = (
    "banzai milestone defers full verify until task completion"
)
_SCOPED_REFRESH_DEFER_REASON = "scoped fulfillment refresh completed"


def _current_git_commit(worktree: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


class CommitPushError(RuntimeError):
    """Raised when verified work cannot be committed or pushed."""

    def __init__(self, message: str, *, branch: str, worktree_path: str) -> None:
        super().__init__(message)
        self.branch = branch
        self.worktree_path = worktree_path


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
        llm_provider: Optional[AICodingCliProvider] = None,
        llm_build_runner: Optional[LlmBuildRunner] = None,
        fulfillment_runner: Optional[FulfillmentRunner] = None,
        build_id: str = "",
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
        self._llm_build_runner = (
            llm_build_runner
            if llm_build_runner is not None
            else LlmBuildRunner(llm_provider) if llm_provider is not None else None
        )
        self._fulfillment_runner = (
            fulfillment_runner
            if fulfillment_runner is not None
            else FulfillmentRunner(llm_provider) if llm_provider is not None else None
        )
        self._build_id = build_id

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
        no_progress_count = 0  # consecutive failed outer iters with no file changes

        # Resolve the spec's feature branch once. When found, all worktrees are
        # checked out on that branch so spec artifacts (spec.md, tasks.md,
        # constitution.md, etc.) are available without the build agent needing to
        # merge them in manually.  Falls back to legacy harness/* branching when no
        # feature branch exists (first-time or pure-harness workflows).
        feature_branch: Optional[str] = None
        try:
            feature_branch = self._gitops.find_feature_branch(self._spec_id)
            if feature_branch:
                logger.info(
                    "Feature branch '%s' found — worktrees will use it as base "
                    "so spec artifacts are available from the start",
                    feature_branch,
                )
            else:
                logger.info(
                    "No feature branch found for spec '%s' — using legacy harness/* branching",
                    self._spec_id,
                )
        except Exception as e:
            logger.warning(
                "Could not resolve feature branch for spec '%s' (continuing with "
                "legacy harness/* mode): %s",
                self._spec_id, e,
            )

        for outer_iter in range(start_outer, max_outer):
            # Check termination conditions
            termination = self._check_termination(
                tokens_used=tokens_used,
                token_budget=token_budget,
            )
            if termination:
                if termination == "killed_by_coordinator":
                    term_status = "cancelled"
                elif termination == "user_cancel":
                    term_status = "interrupted"
                elif termination == "budget_exhausted":
                    term_status = "blocked"
                else:
                    term_status = "failed"
                return self._finalize(
                    status=term_status,
                    reason=termination,
                    outer_iterations=outer_iter,
                    inner_iterations=total_inner_iterations,
                    pr_url=pr_url,
                    tokens_used=tokens_used,
                    final_verify=None,
                )

            # Create worktree — use feature branch when available so spec artifacts
            # (spec.md, tasks.md, constitution.md) are present from the start.
            worktree_path = self._gitops.create_worktree(
                self._spec_id, self._strategy_id, outer_iter,
                base_branch=feature_branch,
                build_id=self._build_id,
            )
            preserve_worktree = False

            try:
                phase_a_blockers = self._sync_phase_a_inputs_into_worktree(
                    Path(worktree_path)
                )
                if phase_a_blockers:
                    preserve_worktree = True
                    reason = (
                        "Phase A artifacts are not build-ready in harness worktree: "
                        + "; ".join(phase_a_blockers)
                    )
                    return self._finalize(
                        status="blocked",
                        reason="build_incomplete",
                        outer_iterations=outer_iter + 1,
                        inner_iterations=total_inner_iterations,
                        pr_url=pr_url,
                        tokens_used=tokens_used,
                        final_verify=None,
                        extra_state={
                            "build_status": "phase_a_not_ready",
                            "build_reason": reason,
                        },
                    )

                # Create sandbox
                sandbox_spec = self._build_sandbox_spec(worktree_path, outer_iter)
                handle = self._provider.create(sandbox_spec)

                try:
                    # Clear stale build status before each iteration so a
                    # status file committed from a prior build on this branch
                    # cannot be mistaken for this build completing successfully.
                    _clear_build_status(worktree_path)

                    # Run build
                    iter_prompt = self._make_iter_prompt(build_prompt, outer_iter, last_verify_failures_text)
                    before_build_state = self._state_store.read()
                    containment_before = _snapshot_project_status(
                        getattr(self._gitops, "base_dir", None),
                        worktree_path,
                    )
                    before_build_head = self._current_head(worktree_path)
                    build_result = self._exec_build(
                        handle, build_command, strategy_context,
                        worktree_path=worktree_path,
                        prompt=iter_prompt,
                    )
                    after_build_head = self._current_head(worktree_path)
                    containment_violation = _detect_containment_violation(
                        containment_before,
                        getattr(self._gitops, "base_dir", None),
                        worktree_path,
                    )
                    if containment_violation is not None:
                        preserve_worktree = True
                        _print_containment_violation_banner(
                            self._spec_id,
                            self._strategy_id,
                            containment_violation,
                        )
                        return self._finalize(
                            status="blocked",
                            reason="containment_violation",
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=None,
                            extra_state={
                                "containment_violation": containment_violation,
                            },
                        )
                    tokens_used += build_result.get("tokens", 0)
                    self._enforce_completed_task_ids(build_result, worktree_path)

                    # Log build iteration
                    self._append_iteration_log(
                        state, outer_iter, 0, "build",
                        build_result.get("exit_code", 0),
                        build_result.get("passed", True),
                        build_result.get("duration_s", 0.0),
                        build_result.get("tokens", 0),
                    )
                    scoped_completed_task_ids = _clean_task_ids(
                        build_result.get("task_ids")
                    )
                    applied_task_ids = self._apply_build_task_progress(
                        worktree_path=worktree_path,
                        task_ids=build_result.get("task_ids"),
                    )
                    if scoped_completed_task_ids and set(applied_task_ids) != set(scoped_completed_task_ids):
                        missing_task_ids = sorted(set(scoped_completed_task_ids) - set(applied_task_ids))
                        build_result["passed"] = False
                        build_result["build_status"] = "task_progress_update_failed"
                        build_result["build_reason"] = (
                            "could not mark completed_task_ids in canonical tasks.md: "
                            + ", ".join(missing_task_ids)
                        )
                        build_result["exit_code"] = 1
                    scoped_changed_files = self._changed_files_since_head(worktree_path)
                    build_checkpoint = self._try_checkpoint_progress_commit(
                        worktree_path=worktree_path,
                        before_state=before_build_state,
                        after_state=self._state_store.read(),
                        outer_iter=outer_iter,
                        inner_iter=0,
                        phase="build",
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
                        if termination == "killed_by_coordinator":
                            term_status = "cancelled"
                        elif termination == "user_cancel":
                            term_status = "interrupted"
                        elif termination == "budget_exhausted":
                            term_status = "blocked"
                        else:
                            term_status = "failed"
                        return self._finalize(
                            status=term_status,
                            reason=termination,
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=None,
                        )

                    # Hard-stop: if the build did not complete. Ralph clears
                    # the status file before each build; "unknown" means the
                    # marker was missing/unreadable, while other statuses (for
                    # example "impasse") are explicit build outcomes.
                    if not build_result.get("passed", True):
                        if self._should_continue_after_missing_marker(
                            build_result,
                            worktree_path=worktree_path,
                            checkpoint=build_checkpoint,
                            head_advanced=self._head_advanced(
                                before_build_head,
                                after_build_head,
                            ),
                        ):
                            self._record_missing_marker_recovery(
                                build_result,
                                checkpoint=build_checkpoint,
                                head_advanced=self._head_advanced(
                                    before_build_head,
                                    after_build_head,
                                ),
                            )
                        else:
                            preserve_worktree = True
                            salvage = _salvage_build_worktree(
                                worktree_path=worktree_path,
                                spec_id=self._spec_id,
                                strategy_id=self._strategy_id,
                                outer_iter=outer_iter,
                            )
                            from echelon.ui import banner as _ui_banner
                            build_status = str(
                                build_result.get("build_status") or "unknown"
                            )
                            build_reason = build_result.get("build_reason")
                            build_exit_code = build_result.get("exit_code")
                            provider_reset_hint = ""
                            provider_limit_message = ""
                            if build_status == "unknown" and _is_host_tool_permission_denied(build_result):
                                why = "host LLM tool permissions blocked the build"
                                meaning = (
                                    "The selected AI CLI refused writes or local command "
                                    "execution in the harness worktree before COMMANDER "
                                    "could write the build completion marker"
                                )
                                build_status = "host_tool_permission_denied"
                                build_reason = (
                                    "Unsafe host execution is disabled. If this disposable "
                                    "harness worktree is approved for AI-driven writes and "
                                    "local test execution, set "
                                    "harness.llm.tool_policy.allow_unsafe_host_execution: true "
                                    "and provide harness.llm.tool_policy.approval_reason."
                                )
                            elif build_status == "unknown" and _is_provider_session_limit(build_result):
                                provider_reset_hint = _provider_session_limit_reset_hint(build_result)
                                provider_limit_message = _provider_session_limit_message(build_result)
                                why = "LLM provider session limit reached before COMMANDER finalized"
                                meaning = (
                                    "The provider stopped the build because its session budget "
                                    "was exhausted; wait for the reset window, then resume to "
                                    "recover the salvage commit"
                                )
                                build_status = "provider_session_limit"
                            elif build_status == "unknown":
                                try:
                                    exit_code = int(build_exit_code)
                                except (TypeError, ValueError):
                                    exit_code = None
                                if exit_code == 0:
                                    why = "missing build status marker: .harness-build-status.json"
                                    meaning = (
                                        "COMMANDER may have changed files, but did not write "
                                        "the harness completion marker"
                                    )
                                else:
                                    code_text = (
                                        f"code {exit_code}"
                                        if exit_code is not None
                                        else "a nonzero code"
                                    )
                                    why = (
                                        "build process exited with "
                                        f"{code_text} before writing the completion marker"
                                    )
                                    meaning = (
                                        "The LLM/provider process stopped before COMMANDER "
                                        "could finalize the harness build status"
                                    )
                            elif build_status == "timeout":
                                why = "build invocation timed out before COMMANDER finalized"
                                meaning = (
                                    "COMMANDER may have made useful progress, but the LLM "
                                    "process exceeded the build timeout before verification "
                                    "and final status could be trusted"
                                )
                            elif build_status == "missing_task_ids":
                                why = "build completion marker omitted completed_task_ids"
                                meaning = (
                                    "COMMANDER reported the build slice done, but did not "
                                    "identify the canonical tasks Ralph must mark DONE"
                                )
                            elif build_status == "task_progress_update_failed":
                                why = "completed_task_ids could not be reconciled with tasks.md"
                                meaning = (
                                    "COMMANDER reported completed task IDs, but Ralph could "
                                    "not update the canonical task ledger before verification"
                                )
                            else:
                                why = f"build reported status '{build_status}'"
                                meaning = (
                                    "COMMANDER wrote the harness completion marker, "
                                    "but did not report BUILD_DONE"
                                )
                            fields = [
                                ("spec", self._spec_id),
                                ("strategy", self._strategy_id),
                                ("why", why),
                            ]
                            if build_reason:
                                fields.append(("reason", str(build_reason)))
                            if salvage:
                                fields.extend(
                                    [
                                        ("salvage commit", salvage["salvage_commit"][:12]),
                                        ("salvage branch", salvage["salvage_branch"]),
                                        ("salvage verified", salvage.get("salvage_verified", "not_run")),
                                    ]
                                )
                            if build_status == "provider_session_limit":
                                if provider_limit_message:
                                    fields.append(("provider", provider_limit_message))
                                if provider_reset_hint:
                                    fields.append(("reset", provider_reset_hint))
                                fields.append(("retry after", "provider reset window"))
                            fields.extend(
                                [
                                    ("meaning", meaning),
                                    (
                                        "next",
                                        f"echelon harness resume {self._spec_id}  (recover and finalize this build)",
                                    ),
                                ]
                            )
                            title = (
                                "HARNESS — PROVIDER SESSION LIMIT"
                                if build_status == "provider_session_limit"
                                else "HARNESS — BUILD DID NOT COMPLETE"
                            )
                            _ui_banner(title, fields, file=sys.stderr)
                            blocked_state = {
                                **(salvage or {}),
                                "build_status": build_status,
                                "build_reason": build_reason,
                                "build_exit_code": build_exit_code,
                            }
                            if provider_reset_hint:
                                blocked_state["provider_reset_hint"] = provider_reset_hint
                            if provider_limit_message:
                                blocked_state["provider_limit_message"] = provider_limit_message
                            return self._finalize(
                                status="blocked",
                                reason="build_incomplete",
                                outer_iterations=outer_iter + 1,
                                inner_iterations=total_inner_iterations,
                                pr_url=pr_url,
                                tokens_used=tokens_used,
                                final_verify=None,
                                branch=salvage.get("salvage_branch") if salvage else None,
                                extra_state=blocked_state,
                            )

                    # Run verify
                    verify_result = self._exec_verify(handle, worktree_path=worktree_path)
                    verify_result = self._apply_task_progress_gate(
                        verify_result, worktree_path
                    )
                    verify_result = self._refresh_fulfillment_report(
                        verify_result,
                        worktree_path,
                        completed_task_ids=scoped_completed_task_ids,
                        changed_files=scoped_changed_files,
                    )
                    verify_result = self._apply_fulfillment_gate(
                        verify_result, worktree_path
                    )
                    verify_result = self._apply_documentation_gate(
                        verify_result, worktree_path
                    )
                    tokens_used += verify_result.token_usage

                    if _is_provider_session_limit_verify_result(verify_result):
                        _print_verify_spec_provider_session_limit_banner(
                            self._spec_id,
                            self._strategy_id,
                            verify_result,
                        )
                        return self._finalize(
                            status="blocked",
                            reason="build_incomplete",
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=verify_result,
                            extra_state={
                                "build_status": "provider_session_limit",
                                "build_reason": "verify-spec provider session limit",
                                "provider_limit_message": _provider_session_limit_failure_text(
                                    verify_result
                                ),
                            },
                        )

                    # Hard-stop: unknown project type cannot be fixed by the LLM.
                    # Block immediately and ask the human to configure verify_command.
                    if any(f.id == "local-verify-skipped" for f in verify_result.failures):
                        _print_verify_command_needed_banner(self._spec_id, self._strategy_id)
                        return self._finalize(
                            status="blocked",
                            reason="verify_command_needed",
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=verify_result,
                        )

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
                        if not self._mark_spec_ready_to_land(worktree_path):
                            preserve_worktree = True
                            return self._finalize(
                                status="blocked",
                                reason="ready_status_failed",
                                outer_iterations=outer_iter + 1,
                                inner_iterations=total_inner_iterations,
                                pr_url=pr_url,
                                tokens_used=tokens_used,
                                final_verify=verify_result,
                            )
                        try:
                            branch = self._commit_and_push(worktree_path, outer_iter)
                        except CommitPushError as e:
                            preserve_worktree = True
                            return self._finalize(
                                status="blocked",
                                reason="publish_failed",
                                outer_iterations=outer_iter + 1,
                                inner_iterations=total_inner_iterations,
                                pr_url=pr_url,
                                tokens_used=tokens_used,
                                final_verify=verify_result,
                                branch=e.branch,
                            )
                        pr_url = self._manage_pr(pr_url, branch, converged=True)

                        return self._finalize(
                            status="converged",
                            reason="converged",
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=verify_result,
                            branch=branch,
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
                    if final_verify and _is_provider_session_limit_verify_result(final_verify):
                        _print_verify_spec_provider_session_limit_banner(
                            self._spec_id,
                            self._strategy_id,
                            final_verify,
                        )
                        return self._finalize(
                            status="blocked",
                            reason="build_incomplete",
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=final_verify,
                            extra_state={
                                "build_status": "provider_session_limit",
                                "build_reason": "verify-spec provider session limit",
                                "provider_limit_message": _provider_session_limit_failure_text(
                                    final_verify
                                ),
                            },
                        )
                    fulfillment_refresh_deferred = bool(
                        final_verify and _is_fulfillment_refresh_deferred(final_verify)
                    )
                    if final_verify and final_verify.failures and not fulfillment_refresh_deferred:
                        last_verify_failures_text = "\n".join(
                            f"[{f.category.value}] {f.id}: {f.error}"
                            for f in final_verify.failures
                        )

                    if inner_result["converged"]:
                        if not self._mark_spec_ready_to_land(worktree_path):
                            preserve_worktree = True
                            return self._finalize(
                                status="blocked",
                                reason="ready_status_failed",
                                outer_iterations=outer_iter + 1,
                                inner_iterations=total_inner_iterations,
                                pr_url=pr_url,
                                tokens_used=tokens_used,
                                final_verify=inner_result.get("final_verify"),
                            )
                        try:
                            branch = self._commit_and_push(worktree_path, outer_iter)
                        except CommitPushError as e:
                            preserve_worktree = True
                            return self._finalize(
                                status="blocked",
                                reason="publish_failed",
                                outer_iterations=outer_iter + 1,
                                inner_iterations=total_inner_iterations,
                                pr_url=pr_url,
                                tokens_used=tokens_used,
                                final_verify=inner_result.get("final_verify"),
                                branch=e.branch,
                            )
                        pr_url = self._manage_pr(pr_url, branch, converged=True)
                        return self._finalize(
                            status="converged",
                            reason="converged",
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=inner_result.get("final_verify"),
                            branch=branch,
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

                    # No-progress guard: if the LLM made no file changes on a
                    # failed iteration, increment the stuck counter and escalate
                    # after _NO_PROGRESS_THRESHOLD consecutive stuck iterations.
                    fulfillment_gaps_after_checkpoint = bool(
                        final_verify
                        and _is_only_fulfillment_gaps(final_verify)
                        and self._last_checkpoint_has_task_progress()
                    )
                    if fulfillment_refresh_deferred or fulfillment_gaps_after_checkpoint:
                        no_progress_count = 0
                    elif self._has_file_changes(worktree_path):
                        no_progress_count = 0
                    else:
                        no_progress_count += 1
                        logger.warning(
                            "No file changes detected after failed outer iter %d "
                            "(no_progress_count=%d/%d)",
                            outer_iter, no_progress_count, _NO_PROGRESS_THRESHOLD,
                        )
                        if no_progress_count >= _NO_PROGRESS_THRESHOLD:
                            escalation_file = self._escalation.escalate(
                                spec_id=self._spec_id,
                                strategy_id=self._strategy_id,
                                category="no_progress",
                                context=(
                                    "## No Progress Detected\n\n"
                                    f"The build loop has failed {no_progress_count} consecutive "
                                    "iterations with no file changes.\n"
                                    "This usually means the LLM is stuck or the build "
                                    "instructions are unclear.\n\n"
                                    "Please review the build output above and either:\n"
                                    "1. Append clarification under ## Answer in the escalation "
                                    f"file and run echelon harness resume {self._spec_id}\n"
                                    "2. Reset and restart with --reset flag"
                                ),
                                last_verify_result=_verify_to_dict(
                                    inner_result["final_verify"]
                                ) if inner_result.get("final_verify") else None,
                            )
                            state = self._state_store.read()
                            state["escalation_file"] = escalation_file
                            self._state_store.write(state)
                            return self._finalize(
                                status="blocked",
                                reason="no_progress",
                                outer_iterations=outer_iter + 1,
                                inner_iterations=total_inner_iterations,
                                pr_url=pr_url,
                                tokens_used=tokens_used,
                                final_verify=inner_result.get("final_verify"),
                            )

                    # Inner loop exhausted -- commit progress and continue outer
                    try:
                        branch = self._commit_and_push(worktree_path, outer_iter)
                    except CommitPushError as e:
                        preserve_worktree = True
                        return self._finalize(
                            status="blocked",
                            reason="publish_failed",
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=inner_result.get("final_verify"),
                            branch=e.branch,
                        )
                    pr_url = self._manage_pr(pr_url, branch, converged=False)

                finally:
                    try:
                        self._provider.destroy(handle)
                    except Exception as exc:
                        self._record_cleanup_warning("sandbox_destroy", exc)
                        logger.warning("Sandbox cleanup failed after build iteration: %s", exc)

            finally:
                # Keep last worktree (FR-REPO-003b)
                if not preserve_worktree and outer_iter < max_outer - 1:
                    self._gitops.destroy_worktree(worktree_path, keep_branch=True)

            # Update state after each iteration
            state = self._state_store.read()
            state["outer_iter"] = outer_iter + 1
            state["tokens_used"] = tokens_used
            state["pr_url"] = pr_url
            self._state_store.write(state)

        # Outer cap reached. If the only outstanding verification failure is an
        # intentionally deferred banzai fulfillment refresh, useful checkpointed
        # progress exists and the correct next step is continuation, not failure.
        if (
            final_verify is not None
            and (
                (
                    _is_fulfillment_refresh_deferred(final_verify)
                    and self._last_fulfillment_refresh_reason()
                    in {
                        _BANZAI_MILESTONE_DEFER_REASON,
                        _SCOPED_REFRESH_DEFER_REASON,
                    }
                )
                or (
                    _is_only_fulfillment_gaps(final_verify)
                    and self._last_checkpoint_has_task_progress()
                )
            )
        ):
            return self._finalize(
                status="blocked",
                reason="checkpoint_outer_cap",
                outer_iterations=max_outer,
                inner_iterations=total_inner_iterations,
                pr_url=pr_url,
                tokens_used=tokens_used,
                final_verify=final_verify,
            )

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
        if _is_fulfillment_refresh_deferred(verify_result):
            return {
                "converged": False,
                "blocked": False,
                "inner_count": 0,
                "tokens_used": tokens_used,
                "final_verify": verify_result,
            }

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
            same_failures = detect_same_failure(
                failure_history,
                threshold=SAME_FAILURE_REPEAT_THRESHOLD,
            )
            if same_failures:
                if self._mode.should_escalate("same_failure_repeat"):
                    repeat_count = _consecutive_failure_repeat_count(
                        failure_history,
                        same_failures,
                    )
                    self._escalation.escalate(
                        spec_id=self._spec_id,
                        strategy_id=self._strategy_id,
                        category="same_failure_repeat",
                        context=(
                            f"Same failure detected {repeat_count} consecutive time(s) "
                            f"(threshold={SAME_FAILURE_REPEAT_THRESHOLD}; "
                            f"fingerprints={len(same_failures)}) "
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
            feedback_prompt = self._make_feedback_prompt(
                build_prompt, current_verify, inner_iter
            )
            before_fix_state = self._state_store.read()
            fix_result = self._exec_feedback(
                handle, current_verify, build_command, strategy_context,
                worktree_path=worktree_path,
                prompt=feedback_prompt,
            )
            tokens_used += fix_result.get("tokens", 0)
            self._enforce_completed_task_ids(fix_result, worktree_path)
            scoped_completed_task_ids = _clean_task_ids(fix_result.get("task_ids"))
            applied_task_ids = self._apply_build_task_progress(
                worktree_path=worktree_path,
                task_ids=fix_result.get("task_ids"),
            )
            if scoped_completed_task_ids and set(applied_task_ids) != set(
                scoped_completed_task_ids
            ):
                missing_task_ids = sorted(
                    set(scoped_completed_task_ids) - set(applied_task_ids)
                )
                current_verify = VerifyResult(
                    passed=False,
                    failures=[
                        FailureEntry(
                            FailureCategory.OTHER,
                            "task-progress-update-failed",
                            (
                                "completed_task_ids could not be reconciled with "
                                "canonical tasks.md: " + ", ".join(missing_task_ids)
                            ),
                        )
                    ],
                )
                return {
                    "converged": False,
                    "blocked": True,
                    "inner_count": inner_iter,
                    "tokens_used": tokens_used,
                    "final_verify": current_verify,
                }

            self._append_iteration_log(
                state, outer_iter, inner_iter, "fix",
                fix_result.get("exit_code", 0),
                fix_result.get("passed", True),
                fix_result.get("duration_s", 0.0),
                fix_result.get("tokens", 0),
            )
            self._try_checkpoint_progress_commit(
                worktree_path=worktree_path,
                before_state=before_fix_state,
                after_state=self._state_store.read(),
                outer_iter=outer_iter,
                inner_iter=inner_iter,
                phase="fix",
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
            current_verify = self._refresh_fulfillment_report(
                current_verify,
                worktree_path,
                completed_task_ids=scoped_completed_task_ids,
                changed_files=self._changed_files_since_head(worktree_path),
            )
            current_verify = self._apply_fulfillment_gate(
                current_verify, worktree_path
            )
            current_verify = self._apply_documentation_gate(
                current_verify, worktree_path
            )
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

            if _is_provider_session_limit_verify_result(current_verify):
                return {
                    "converged": False,
                    "blocked": False,
                    "inner_count": inner_iter,
                    "tokens_used": tokens_used,
                    "final_verify": current_verify,
                }

            # Full-spec fulfillment gaps are expected while a build is still
            # partial. If this fix completed canonical task IDs, stop the inner
            # loop and let the outer loop checkpoint/commit progress before the
            # next build slice, instead of escalating on the repeated aggregate
            # fulfillment-gaps signature.
            if applied_task_ids and _is_only_fulfillment_gaps(current_verify):
                return {
                    "converged": False,
                    "blocked": False,
                    "inner_count": inner_iter,
                    "tokens_used": tokens_used,
                    "final_verify": current_verify,
                }

            # A post-fix re-verify whose only failure is the intentionally
            # deferred banzai fulfillment refresh is benign: all real checks
            # passed and only the full verify-spec refresh is deferred until
            # task completion (it is always the sole failure — see
            # _refresh_fulfillment_report, which only runs once verify passes).
            # Exit the inner loop here, mirroring the entry guard, so the outer
            # loop checkpoints this slice and advances to the next task instead
            # of dispatching fixers against an unfixable deferral until
            # max_inner (the milestone-boundary defer-loop).
            if _is_fulfillment_refresh_deferred(current_verify):
                return {
                    "converged": False,
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
        """Execute the strategy's build command in sandbox or via LLM build runner.

        When an LLM build runner is set and both ``worktree_path`` and ``prompt``
        are non-empty, delegates to it. Otherwise
        falls back to the sandbox provider path.

        Args:
            handle: Active sandbox handle.
            build_command: Command to run (e.g. ``echelon build`` or
                ``echelon codegen``). Declared via strategy file frontmatter.
            strategy_context: Additional context injected via STRATEGY_CONTEXT
                env var. Empty string = no injection.
            worktree_path: Path to the git worktree (LLM build runner path only).
            prompt: Prompt text for the LLM (LLM build runner path only).

        Returns:
            Dict with exit_code, passed, duration_s, tokens, impasse,
            impasse_file.
        """
        if self._llm_build_runner and worktree_path and prompt:
            prompt = self._with_harness_context(prompt, worktree_path)
            result = self._llm_build_runner.exec_build(worktree_path, prompt)
            return {
                "exit_code": result.exit_code,
                "passed": result.succeeded,
                "build_status": result.status,
                "build_reason": result.reason,
                "duration_s": result.duration_ms / 1000.0,
                "tokens": result.token_usage,
                "impasse": result.is_impasse,
                "impasse_file": result.impasse_file,
                "task_ids": result.task_ids or [],
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        # Fallback: original sandbox path
        cmd = build_command
        if strategy_context:
            cmd = f"STRATEGY_CONTEXT='{strategy_context}' {cmd}"

        result = self._provider.exec(handle, cmd, timeout_ms=1_200_000)
        return {
            "exit_code": result.exit_code,
            "passed": result.exit_code == 0,
            "build_status": "done" if result.exit_code == 0 else "unknown",
            "build_reason": None,
            "duration_s": result.duration_ms / 1000.0,
            "tokens": _estimate_tokens(result),
            "impasse": False,
            "impasse_file": None,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def _exec_verify(self, handle: SandboxHandle, worktree_path: str = "") -> VerifyResult:
        """Execute verification.

        When the LLM build runner path is active and worktree_path is provided, runs verification
        locally on the host via the detected package manager's install + test + build
        commands (avoids Docker networking issues where the internal network blocks
        package downloads). Falls back to sandbox provider path otherwise.

        Returns parsed VerifyResult.
        """
        if self._llm_build_runner and worktree_path:
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

    def _apply_fulfillment_gate(
        self,
        verify_result: VerifyResult,
        worktree_path: str,
    ) -> VerifyResult:
        """Treat unresolved fulfillment gaps as verification failures."""
        if not verify_result.passed or not worktree_path:
            return verify_result

        spec_dir = self._find_spec_dir(worktree_path)
        if spec_dir is None:
            return verify_result

        report = latest_fulfillment_report(spec_dir)
        if report is None:
            return verify_result

        metadata = read_fulfillment_metadata(report)
        if metadata.get("verify_scope") == "scoped":
            failure = FailureEntry(
                category=FailureCategory.OTHER,
                id="fulfillment-report-scoped",
                error=(
                    f"fulfillment report is scoped incremental evidence: {report}. "
                    "Do not regenerate fulfillment artifacts in a build slice; "
                    "Ralph must run a full fulfillment refresh before convergence."
                ),
            )
            return VerifyResult(
                passed=False,
                failures=[failure],
                duration_s=verify_result.duration_s,
                token_usage=verify_result.token_usage,
            )

        current_commit = _current_git_commit(Path(worktree_path))
        if current_commit and not fulfillment_report_is_current(
            report, current_commit=current_commit
        ):
            verified_commit = metadata.get("verified_commit") or "(missing)"
            failure = FailureEntry(
                category=FailureCategory.OTHER,
                id="fulfillment-report-stale",
                error=(
                    f"fulfillment report is stale for current HEAD {current_commit}: "
                    f"{report} was verified at {verified_commit}. "
                    "Do not regenerate fulfillment artifacts in a build slice; "
                    "Ralph must refresh fulfillment evidence before convergence."
                ),
            )
            return VerifyResult(
                passed=False,
                failures=[failure],
                duration_s=verify_result.duration_s,
                token_usage=verify_result.token_usage,
            )

        if not fulfillment_has_blocking_gaps(report, strict=True):
            return verify_result

        statuses = ", ".join(sorted(blocking_statuses(strict=True)))
        failure = FailureEntry(
            category=FailureCategory.OTHER,
            id="fulfillment-gaps",
            error=(
                f"fulfillment report has unresolved statuses ({statuses}): {report}. "
                f"Run `echelon reopen {self._spec_id}` or continue the harness loop "
                "with fulfillment-gaps.md as mandatory implementation context."
            ),
        )
        return VerifyResult(
            passed=False,
            failures=[failure],
            duration_s=verify_result.duration_s,
            token_usage=verify_result.token_usage,
        )

    def _apply_documentation_gate(
        self,
        verify_result: VerifyResult,
        worktree_path: str,
    ) -> VerifyResult:
        """Treat stale or missing README/CHANGELOG decisions as verification failures."""
        if not verify_result.passed or not worktree_path:
            return verify_result

        spec_dir = self._find_spec_dir(worktree_path)
        if spec_dir is None:
            return verify_result

        gate = evaluate_documentation_gate(Path(worktree_path), spec_dir)
        if gate.passed:
            return verify_result

        assert gate.failure is not None
        return VerifyResult(
            passed=False,
            failures=[gate.failure],
            duration_s=verify_result.duration_s,
            token_usage=verify_result.token_usage,
        )

    def _apply_task_progress_gate(
        self,
        verify_result: VerifyResult,
        worktree_path: str,
    ) -> VerifyResult:
        """Treat task progress mismatches as verification failures."""
        if not verify_result.passed or not worktree_path:
            return verify_result

        spec_dir = self._find_spec_dir(worktree_path)
        if spec_dir is None:
            return verify_result

        tasks_path = spec_dir / "tasks.md"
        if not tasks_path.exists():
            return verify_result

        state = self._state_store.read()
        summary = summarize_task_progress(
            tasks_path.read_text(encoding="utf-8", errors="replace"),
            state.get("build") if isinstance(state.get("build"), dict) else {},
        )
        if summary.valid:
            return verify_result

        failure = FailureEntry(
            category=FailureCategory.OTHER,
            id="task-progress-mismatch",
            error=(
                "task progress tracking is inconsistent: "
                + "; ".join(summary.errors)
                + ". Update tasks.md canonical rows and state.json build progress before convergence."
            ),
        )
        return VerifyResult(
            passed=False,
            failures=[failure],
            duration_s=verify_result.duration_s,
            token_usage=verify_result.token_usage,
        )

    def _apply_build_task_progress(
        self,
        *,
        worktree_path: str,
        task_ids: object,
    ) -> list[str]:
        """Apply build-reported completed task IDs to canonical tasks.md."""
        if not isinstance(task_ids, list) or not task_ids:
            return []

        spec_dir = self._find_spec_dir(worktree_path)
        if spec_dir is None:
            return []

        tasks_path = spec_dir / "tasks.md"
        if not tasks_path.exists():
            return []

        completed_ids = [str(task_id).strip() for task_id in task_ids if str(task_id).strip()]
        if not completed_ids:
            return []

        markdown = tasks_path.read_text(encoding="utf-8", errors="replace")
        applied: list[str] = []
        for task_id in completed_ids:
            try:
                markdown = update_task_progress_markdown(markdown, task_id, "DONE")
            except TaskProgressError as exc:
                logger.warning("Could not mark completed build task %s: %s", task_id, exc)
                continue
            applied.append(task_id)

        if not applied:
            return []

        tasks_path.write_text(markdown, encoding="utf-8")
        summary = summarize_task_progress(markdown)
        state = self._state_store.read()
        build = state.get("build")
        if not isinstance(build, dict):
            build = {}
        build["total_tasks"] = summary.total_tasks
        build["completed_tasks"] = summary.completed_tasks
        build["tasks_completed_pct"] = summary.tasks_completed_pct
        task_results = build.get("task_results")
        if not isinstance(task_results, dict):
            task_results = {}
        for task_id in applied:
            result = task_results.get(task_id)
            if not isinstance(result, dict):
                result = {}
            result["status"] = "DONE"
            task_results[task_id] = result
        build["task_results"] = task_results
        state["build"] = build
        self._state_store.write(state)
        return applied

    def _enforce_completed_task_ids(
        self,
        build_result: Dict[str, Any],
        worktree_path: str,
    ) -> None:
        """Require completed task IDs for successful task-backed build slices."""
        if not build_result.get("passed", True):
            return
        if (build_result.get("build_status") or "unknown") != "done":
            return
        task_ids = build_result.get("task_ids")
        if isinstance(task_ids, list) and any(str(task_id).strip() for task_id in task_ids):
            return
        if not self._has_non_verify_worktree_changes(worktree_path):
            return

        spec_dir = self._find_spec_dir(worktree_path)
        if spec_dir is None:
            return
        tasks_path = spec_dir / "tasks.md"
        if not tasks_path.exists():
            return

        summary = summarize_task_progress(
            tasks_path.read_text(encoding="utf-8", errors="replace")
        )
        if summary.total_tasks <= 0:
            return

        build_result["passed"] = False
        build_result["build_status"] = "missing_task_ids"
        build_result["build_reason"] = (
            "successful harness build marker omitted completed_task_ids for a "
            "task-backed build slice"
        )
        build_result["exit_code"] = 1

    def _has_non_verify_worktree_changes(self, worktree_path: str) -> bool:
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return True
        if result.returncode != 0:
            return True
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].strip()
            if path == BUILD_STATUS_FILENAME or _is_verify_owned_artifact(path):
                continue
            return True
        return False

    def _refresh_fulfillment_report(
        self,
        verify_result: VerifyResult,
        worktree_path: str,
        completed_task_ids: Optional[List[str]] = None,
        changed_files: Optional[List[str]] = None,
    ) -> VerifyResult:
        """Run verify-spec after ordinary verification passes, when possible."""
        if not verify_result.passed or not worktree_path or self._fulfillment_runner is None:
            return verify_result
        decision = self._fulfillment_refresh_decision(worktree_path)
        if decision.get("action") == "defer":
            reason = str(decision.get("reason") or "fulfillment refresh deferred")
            self._record_fulfillment_refresh(
                {
                    "status": "deferred",
                    "reason": reason,
                    "scope": "full",
                }
            )
            failure = FailureEntry(
                category=FailureCategory.OTHER,
                id="fulfillment-refresh-deferred",
                error=(
                    f"full verify-spec refresh deferred: {reason}; "
                    "full fulfillment evidence is still required before convergence"
                ),
            )
            return VerifyResult(
                passed=False,
                failures=[failure],
                duration_s=verify_result.duration_s,
                token_usage=verify_result.token_usage,
            )

        refresh_kwargs: dict[str, object] = {
            "orchestration_root": (
                getattr(self._gitops, "base_dir", None)
                if self._spec_artifacts_mode() == "external"
                else None
            )
        }
        if decision.get("action") == "scoped":
            refresh_kwargs.update(
                {
                    "scope": "scoped",
                    "completed_task_ids": completed_task_ids or [],
                    "changed_files": changed_files or [],
                }
            )
        refresh_result = self._fulfillment_runner.refresh(
            worktree_path,
            self._spec_id,
            **refresh_kwargs,
        )
        exit_code = getattr(refresh_result, "exit_code", refresh_result)
        self._record_fulfillment_refresh(
            {
                "status": getattr(
                    refresh_result,
                    "status",
                    "refreshed" if exit_code == 0 else "failed",
                ),
                "reason": getattr(refresh_result, "reason", ""),
                "scope": getattr(refresh_result, "scope", "full"),
                "cache_key": getattr(refresh_result, "cache_key", None),
                "report_path": getattr(refresh_result, "report_path", None),
            }
        )
        if exit_code == 0:
            if decision.get("action") == "scoped" and getattr(
                refresh_result, "scope", ""
            ) == "scoped":
                self._record_fulfillment_refresh(
                    {
                        "status": "deferred",
                        "reason": _SCOPED_REFRESH_DEFER_REASON,
                        "scope": "full",
                        "report_path": getattr(refresh_result, "report_path", None),
                    }
                )
                failure = FailureEntry(
                    category=FailureCategory.OTHER,
                    id="fulfillment-refresh-deferred",
                    error=(
                        "scoped fulfillment refresh completed; full verify-spec "
                        "evidence is still required before convergence"
                    ),
                )
                return VerifyResult(
                    passed=False,
                    failures=[failure],
                    duration_s=verify_result.duration_s,
                    token_usage=verify_result.token_usage,
                )
            return verify_result

        if getattr(refresh_result, "status", "") == "provider_session_limit":
            failure = FailureEntry(
                category=FailureCategory.OTHER,
                id="fulfillment-refresh-provider-session-limit",
                error=(
                    "verify-spec fulfillment refresh hit the LLM provider "
                    f"session limit: {getattr(refresh_result, 'reason', '')}"
                ),
            )
            return VerifyResult(
                passed=False,
                failures=[failure],
                duration_s=verify_result.duration_s,
                token_usage=verify_result.token_usage,
            )

        failure = FailureEntry(
            category=FailureCategory.OTHER,
            id="verify-spec-failed",
            error=(
                f"`echelon verify-spec {self._spec_id}` failed with exit code "
                f"{exit_code}; fulfillment could not be refreshed."
            ),
        )
        return VerifyResult(
            passed=False,
            failures=[failure],
            duration_s=verify_result.duration_s,
            token_usage=verify_result.token_usage,
        )

    def _task_progress_counts(self) -> tuple[int, int]:
        state = self._state_store.read()
        build = state.get("build")
        if not isinstance(build, dict):
            return (0, 0)
        try:
            total = int(build.get("total_tasks") or 0)
            completed = int(build.get("completed_tasks") or 0)
        except (TypeError, ValueError):
            return (0, 0)
        return (total, completed)

    def _fulfillment_refresh_decision(self, worktree_path: str) -> dict[str, object]:
        policy = self._config.fulfillment.refresh_policy
        total, completed = self._task_progress_counts()
        tasks_complete = total > 0 and completed >= total
        if policy == "scoped":
            if tasks_complete or total <= 0:
                return {"action": "full", "reason": "convergence boundary reached"}
            return {"action": "scoped", "reason": "fulfillment.refresh_policy=scoped"}
        if policy == "every_slice":
            return {"action": "full", "reason": "fulfillment.refresh_policy=every_slice"}
        if policy != "convergence_only":
            if (
                policy == "milestone"
                and self._mode.mode == "banzai"
                and total > 0
                and not tasks_complete
            ):
                return {
                    "action": "defer",
                    "reason": _BANZAI_MILESTONE_DEFER_REASON,
                }
            return {"action": "full", "reason": f"fulfillment.refresh_policy={policy}"}
        if tasks_complete or total <= 0:
            return {"action": "full", "reason": "convergence boundary reached"}
        return {
            "action": "defer",
            "reason": "fulfillment.refresh_policy=convergence_only",
        }

    def _should_refresh_fulfillment(self, worktree_path: str) -> bool:
        return self._fulfillment_refresh_decision(worktree_path).get("action") in {
            "full",
            "scoped",
        }

    def _changed_files_since_head(self, worktree_path: str) -> List[str]:
        changed: set[str] = set()
        for args in (
            ["git", "diff", "--name-only", "HEAD"],
            ["git", "diff", "--cached", "--name-only", "HEAD"],
            ["git", "ls-files", "--others", "--exclude-standard"],
        ):
            try:
                result = subprocess.run(
                    args,
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except OSError:
                continue
            if result.returncode != 0:
                continue
            for line in result.stdout.splitlines():
                if line.strip():
                    changed.add(line.strip())
        return sorted(changed)

    def _record_fulfillment_refresh(self, data: dict[str, object]) -> None:
        state = self._state_store.read()
        state["fulfillment_refresh"] = {
            "status": str(data.get("status") or ""),
            "reason": str(data.get("reason") or ""),
            "scope": str(data.get("scope") or "full"),
            "cache_key": data.get("cache_key"),
            "report_path": data.get("report_path"),
        }
        self._state_store.write(state)
        self._print_fulfillment_refresh_decision(
            status=str(state["fulfillment_refresh"]["status"]),
            reason=str(state["fulfillment_refresh"]["reason"]),
        )

    def _last_fulfillment_refresh_reason(self) -> str:
        state = self._state_store.read()
        refresh = state.get("fulfillment_refresh")
        if not isinstance(refresh, dict):
            return ""
        return str(refresh.get("reason") or "")

    def _last_checkpoint_has_task_progress(self) -> bool:
        state = self._state_store.read()
        checkpoints = state.get("checkpoint_commits")
        if not isinstance(checkpoints, list) or not checkpoints:
            return False
        checkpoint = checkpoints[-1]
        if not isinstance(checkpoint, dict):
            return False
        task_ids = checkpoint.get("task_ids")
        if isinstance(task_ids, list) and any(str(task_id).strip() for task_id in task_ids):
            return True
        try:
            before = int(checkpoint.get("completed_tasks_before") or 0)
            after = int(checkpoint.get("completed_tasks_after") or 0)
        except (TypeError, ValueError):
            return False
        return after > before

    def _print_fulfillment_refresh_decision(self, *, status: str, reason: str) -> None:
        print(f"fulfillment refresh: {status} ({reason})", file=sys.stderr)

    def _exec_verify_locally(self, worktree_path: str) -> VerifyResult:
        """Run verification locally on the host when LLM provider is active.

        Detects the package manager from lockfiles and runs the appropriate
        install + test + build commands in the worktree directory.
        worktrees don't inherit node_modules from the parent repo.

        For Python projects (pyproject.toml / setup.py / requirements.txt present
        but no package.json), runs verify.sh if it exists, otherwise falls back
        to ``python -m pytest``.

        For Swift projects (Package.swift present at root or in a subdirectory),
        runs ``swift build`` then ``swift test``.

        Returns VerifyResult with structured failures when tests fail.
        """
        import subprocess
        import time

        failures = []
        start = time.monotonic()

        wt = Path(worktree_path)

        # Explicit override: verify_command in config takes priority over detection.
        # Run from the candidate worktree so verification exercises the commit Ralph
        # just built. In workspace/source-root mode, the orchestration workspace root
        # intentionally does not contain source scripts.
        if self._config.verify_command:
            import subprocess as _sp
            cmd = self._config.verify_command.split()
            verify_cwd = (
                str(Path(worktree_path).resolve())
                if worktree_path
                else str(getattr(self._gitops, "base_dir", ""))
            )
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

        # Swift Package Manager: root Package.swift takes priority; fall back to
        # the shallowest Package.swift found in subdirectories (e.g. Packages/Foo/).
        swift_package_dir: Optional[Path] = None
        if (wt / "Package.swift").exists():
            swift_package_dir = wt
        else:
            candidates = sorted(wt.glob("**/Package.swift"), key=lambda p: len(p.parts))
            if candidates:
                swift_package_dir = candidates[0].parent
        is_swift = swift_package_dir is not None and not is_python and not is_node

        if is_python:
            return self._exec_verify_python(worktree_path, start)

        if is_swift:
            return self._exec_verify_swift(str(swift_package_dir), start)

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

    def _exec_verify_swift(self, package_dir: str, start: float) -> VerifyResult:
        """Run Swift Package Manager verification: ``swift build`` then ``swift test``.

        Runs from ``package_dir`` (the directory containing Package.swift).
        Timeout is 600 s per stage to allow for initial dependency resolution and
        compilation which can be slow on a cold cache.
        """
        import subprocess
        import shutil
        import time

        failures = []

        if not shutil.which("swift"):
            duration_s = time.monotonic() - start
            return VerifyResult(
                passed=False,
                failures=[FailureEntry(
                    category=FailureCategory.BUILD,
                    id="swift-not-found",
                    error=(
                        "swift toolchain not found on PATH. "
                        "Install Xcode or the Swift toolchain and ensure 'swift' is on PATH."
                    ),
                )],
                duration_s=duration_s,
            )

        for stage, cmd in [("build", "swift build"), ("test", "swift test")]:
            try:
                result = subprocess.run(
                    cmd.split(),
                    cwd=package_dir,
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                if result.returncode != 0:
                    output = (result.stdout + result.stderr).strip()
                    failures.append(FailureEntry(
                        category=FailureCategory.BUILD if stage == "build" else FailureCategory.TEST,
                        id=f"swift-{stage}",
                        error=output[-2000:] if len(output) > 2000 else output,
                    ))
                    break
            except subprocess.TimeoutExpired:
                failures.append(FailureEntry(
                    category=FailureCategory.BUILD if stage == "build" else FailureCategory.TEST,
                    id=f"swift-{stage}-timeout",
                    error=f"{cmd} timed out after 600 seconds",
                ))
                break
            except Exception as e:
                failures.append(FailureEntry(
                    category=FailureCategory.OTHER,
                    id=f"swift-{stage}-error",
                    error=str(e),
                ))
                break

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
        """Execute feedback (fix) step in sandbox or via LLM build runner.

        When an LLM build runner is set and both ``worktree_path`` and ``prompt``
        are non-empty, delegates to it. Otherwise
        falls back to the sandbox provider path.

        Returns dict with exit_code, passed, duration_s, tokens.
        """
        if self._llm_build_runner and worktree_path and prompt:
            prompt = self._with_harness_context(prompt, worktree_path)
            result = self._llm_build_runner.exec_feedback(worktree_path, prompt)
            return {
                "exit_code": result.exit_code,
                "passed": result.succeeded,
                "build_status": result.status,
                "build_reason": result.reason,
                "duration_s": result.duration_ms / 1000.0,
                "tokens": 0,
                "impasse": result.is_impasse,
                "impasse_file": result.impasse_file,
                "task_ids": result.task_ids or [],
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

    def _with_harness_context(self, prompt: str, worktree_path: str) -> str:
        """Attach deterministic harness paths for LLM build/fix prompts."""
        if "## Harness Context\n" in prompt:
            return prompt
        project_root = Path(worktree_path)
        orchestration_root = self._orchestration_root(project_root)
        spec_dir = self._find_spec_dir(worktree_path)
        spec_artifacts_mode = self._spec_artifacts_mode()
        state = self._state_store.read()
        workspace_root = state.get("workspace_root") or str(orchestration_root)
        workspace_git_role = state.get("workspace_git_role") or "unknown"
        source_root = state.get("source_root") or worktree_path
        source_id = state.get("source_id") or Path(str(source_root)).name
        source_git_role = state.get("source_git_role") or "source"
        spec_dir_text = str(spec_dir) if spec_dir is not None else "MISSING"
        spec_file_text = str(spec_dir / "spec.md" if spec_dir is not None else "MISSING")
        tasks_file_text = str(spec_dir / "tasks.md" if spec_dir is not None else "MISSING")
        harness_source_dir = os.environ.get("HARNESS_SOURCE_DIR") or str(
            Path(__file__).resolve().parent
        )
        dirty_verify_artifacts = self._dirty_verify_artifacts(worktree_path)
        dirty_verify_block = ""
        if dirty_verify_artifacts:
            self._record_dirty_verify_artifacts(worktree_path, dirty_verify_artifacts)
            dirty_verify_block = (
                "dirty_verify_artifacts:\n"
                + "".join(f"- {path}\n" for path in dirty_verify_artifacts)
                + "Treat these as inherited verify-spec outputs. Do not hand-edit them in build slices; Ralph owns regeneration and commit/salvage.\n"
            )
        progress_ledger_block = self._delivery_progress_ledger_block(state)
        block = (
            "## Harness Context\n"
            f"worktree: {worktree_path}\n"
            f"target_repo_worktree: {worktree_path}\n"
            f"orchestration_root: {orchestration_root}\n"
            f"workspace_root: {workspace_root}\n"
            f"workspace_git_role: {workspace_git_role}\n"
            f"source_root: {source_root}\n"
            f"source_id: {source_id}\n"
            f"source_git_role: {source_git_role}\n"
            f"spec_artifacts_mode: {spec_artifacts_mode}\n"
            f"spec_dir: {spec_dir_text}\n"
            f"spec_file: {spec_file_text}\n"
            f"tasks_file: {tasks_file_text}\n"
            f"harness_source_dir: {harness_source_dir}\n"
            f"{dirty_verify_block}"
            f"state_file: {self._state_store.state_file}\n"
            f"state_dir: {self._state_store.state_dir}\n"
            "Use `worktree` / `target_repo_worktree` for implementation reads, searches, edits, and tests.\n"
            "Use `source_root` only as source identity/context; implementation edits must stay in `worktree`.\n"
            "Do not search for the application repo; it is named here and mirrored by `worktree`.\n"
            "Use `workspace_root` only for Echelon/spec orchestration unless `source_root` is the same path.\n"
            "Use `spec_dir`, `spec_file`, and `tasks_file` as read-only inputs for understanding the requested work.\n"
            "Do not edit `tasks_file`, `spec_file`, or any file under `spec_dir` for progress tracking during a build slice.\n"
            "Report completed progress only by writing `completed_task_ids` to the harness build status marker; Ralph owns task progress writes.\n"
            "Do not search for harness source, Ralph code, or ralph.py. If harness internals are needed, read files under `harness_source_dir` directly.\n"
            "When `spec_artifacts_mode` is `worktree`, inherited spec artifacts still remain Ralph-owned for progress writes.\n"
            "When `spec_artifacts_mode` is `external`, external spec artifacts are read-only inputs; never write to them from the build agent.\n"
            "Do not discover spec artifacts with `find`, `ls`, globbing, parent-directory scans, or absolute searches.\n"
            "The harness state file is owned by Ralph and may be outside the worktree.\n"
            "Read it only when the build phase explicitly needs orchestration context.\n"
            "Do not search for state.json; use this exact state_file path.\n"
            "Do not write harness state directly; return state_updates in echelon_result.\n"
            f"{progress_ledger_block}"
        )
        return f"{block}\n{prompt}"

    def _delivery_progress_ledger_block(self, state: Dict[str, Any]) -> str:
        """Render persisted delivery progress as read-only prompt context."""
        build = state.get("build")
        checkpoints = state.get("checkpoint_commits")
        if not isinstance(build, dict) and not isinstance(checkpoints, list):
            return ""

        completed_ids: list[str] = []
        total_tasks = None
        completed_tasks = None
        completed_pct = None
        if isinstance(build, dict):
            total_tasks = build.get("total_tasks")
            completed_tasks = build.get("completed_tasks")
            completed_pct = build.get("tasks_completed_pct")
            task_results = build.get("task_results")
            if isinstance(task_results, dict):
                for task_id, result in task_results.items():
                    if not isinstance(result, dict):
                        continue
                    status = str(result.get("status") or "").strip().upper()
                    if status in {"DONE", "DONE_WITH_CONCERNS", "DEGRADED"}:
                        completed_ids.append(str(task_id))

        checkpoint_lines: list[str] = []
        if isinstance(checkpoints, list):
            for checkpoint in checkpoints:
                if not isinstance(checkpoint, dict):
                    continue
                commit = str(checkpoint.get("commit") or "").strip()
                short_commit = commit[:12] if commit else "(missing)"
                outer = checkpoint.get("outer_iter", "?")
                phase = str(checkpoint.get("phase") or "?").strip() or "?"
                task_ids = checkpoint.get("task_ids")
                if isinstance(task_ids, list) and task_ids:
                    tasks = ",".join(str(task_id).strip() for task_id in task_ids)
                else:
                    tasks = "(none recorded)"
                checkpoint_lines.append(
                    f"- {short_commit} outer={outer} phase={phase} tasks={tasks}"
                )

        if not completed_ids and not checkpoint_lines and completed_tasks in (None, 0):
            return ""

        completed_ids = sorted(dict.fromkeys(completed_ids))
        if total_tasks is not None and completed_tasks is not None:
            pct = f" ({completed_pct}%)" if completed_pct is not None else ""
            count_line = f"completed_tasks: {completed_tasks}/{total_tasks}{pct}"
        elif completed_tasks is not None:
            count_line = f"completed_tasks: {completed_tasks}"
        else:
            count_line = f"completed_tasks: {len(completed_ids)}"

        lines = [
            "\n## Delivery Progress Ledger",
            "This ledger is Python-owned read-only context from harness state.",
            count_line,
            "completed_task_ids: "
            + (", ".join(completed_ids) if completed_ids else "(none recorded)"),
        ]
        if checkpoint_lines:
            lines.append("checkpoint_commits:")
            lines.extend(checkpoint_lines)
        lines.extend(
            [
                "Do not redo completed_task_ids; treat them as already implemented unless source/tests prove a regression.",
                "Select only unchecked/open canonical tasks from tasks.md for the next build slice.",
                "Stale or scoped fulfillment reports are Ralph-owned evidence refresh context; do not hand-edit or regenerate them in a build slice.",
            ]
        )
        return "\n".join(lines) + "\n"

    def _dirty_verify_artifacts(self, worktree_path: str) -> list[str]:
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception:
            return []
        if result.returncode != 0:
            return []

        artifacts: list[str] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            path = _porcelain_path(line)
            if path and _is_verify_owned_artifact(path):
                artifacts.append(path)
        return sorted(dict.fromkeys(artifacts))

    def _record_dirty_verify_artifacts(
        self, worktree_path: str, artifacts: list[str]
    ) -> None:
        state = self._state_store.read()
        state["dirty_verify_artifacts"] = {
            "count": len(artifacts),
            "paths": artifacts,
            "worktree": worktree_path,
        }
        self._state_store.write(state)

    def _orchestration_root(self, fallback: Path | None = None) -> Path:
        base_dir = getattr(self._gitops, "base_dir", None)
        if base_dir:
            return Path(base_dir).resolve()
        return (fallback or Path.cwd()).resolve()

    def _find_spec_dir(self, worktree_path: str | Path) -> Path | None:
        worktree = Path(worktree_path)
        if self._spec_artifacts_mode() == "worktree":
            spec_dir = self._find_spec_dir_in_root(worktree)
            if spec_dir is not None:
                return spec_dir
            return self._materialize_state_spec_dir_into_worktree(worktree)

        state = self._state_store.read()
        state_spec_dir = state.get("spec_dir")
        if state_spec_dir:
            candidate = Path(str(state_spec_dir))
            if not candidate.is_absolute():
                candidate = self._orchestration_root(Path(worktree_path)) / candidate
            return candidate
        spec_dir = find_spec_dir(self._spec_id, self._orchestration_root(worktree))
        if spec_dir is not None:
            return spec_dir
        return find_spec_dir(self._spec_id, worktree)

    def _materialize_state_spec_dir_into_worktree(self, worktree: Path) -> Path | None:
        """Copy the Python-owned spec into an isolated worktree when it is absent."""
        state = self._state_store.read()
        state_spec_dir = state.get("spec_dir")
        if not state_spec_dir:
            return None

        source = Path(str(state_spec_dir))
        if not source.is_absolute():
            source = self._orchestration_root(worktree) / source
        if not source.is_dir():
            return None

        dest = worktree / "specs" / source.name
        if dest.exists():
            return dest if dest.is_dir() else None

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, dest)
        return dest

    def _sync_phase_a_inputs_into_worktree(self, worktree: Path) -> list[str]:
        """Materialize current Phase A inputs into the build worktree.

        The CLI preflight validates the project-visible published spec directory,
        but Ralph builds in a generated git worktree that may be based on an older
        feature-branch commit. Copy the current published spec artifacts into that
        worktree before dispatch so the build agent sees the same inputs that
        preflight approved.
        """
        if self._spec_artifacts_mode() != "worktree":
            return []

        source = self._source_phase_a_spec_dir(worktree)
        if source is None:
            return []
        try:
            if source.resolve().is_relative_to(worktree.resolve()):
                return []
        except OSError:
            return []

        dest = worktree / "specs" / source.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, dest, dirs_exist_ok=True)
        self._reconcile_synced_task_progress(dest)

        source_constitution = self._orchestration_root(worktree) / ".specify" / "memory" / "constitution.md"
        if source_constitution.exists():
            target_constitution = worktree / ".specify" / "memory" / "constitution.md"
            target_constitution.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_constitution, target_constitution)

        readiness = validate_phase_a_readiness({"status": "done"}, [dest])
        if readiness.ready:
            return []
        return readiness.blockers or ["Phase A build inputs are not ready"]

    def _reconcile_synced_task_progress(self, spec_dir: Path) -> None:
        """Reapply Python-owned task progress after copying Phase A inputs."""
        tasks_path = spec_dir / "tasks.md"
        if not tasks_path.exists():
            return

        state = self._state_store.read()
        build = state.get("build")
        if not isinstance(build, dict):
            return
        task_results = build.get("task_results")
        if not isinstance(task_results, dict):
            return

        markdown = tasks_path.read_text(encoding="utf-8", errors="replace")
        changed = False
        for task_id, result in sorted(task_results.items()):
            if not isinstance(result, dict):
                continue
            status = str(result.get("status") or "").strip().upper()
            if status not in {"DONE", "DONE_WITH_CONCERNS", "DEGRADED"}:
                continue
            try:
                updated = update_task_progress_markdown(markdown, str(task_id), status)
            except TaskProgressError as exc:
                logger.warning("Could not reconcile synced task progress for %s: %s", task_id, exc)
                continue
            changed = changed or updated != markdown
            markdown = updated

        if changed:
            tasks_path.write_text(markdown, encoding="utf-8")

    def _source_phase_a_spec_dir(self, worktree: Path) -> Path | None:
        state = self._state_store.read()
        state_spec_dir = state.get("spec_dir")
        if state_spec_dir:
            source = Path(str(state_spec_dir))
            if not source.is_absolute():
                source = self._orchestration_root(worktree) / source
            if source.is_dir():
                return source
        return find_spec_dir(self._spec_id, self._orchestration_root(worktree))

    def _find_spec_dir_in_root(self, root: Path) -> Path | None:
        """Find a spec directory directly under root without walking parents."""
        root = root.resolve()
        exact = root / "specs" / self._spec_id
        if exact.is_dir():
            return exact
        matches = sorted(root.glob(f"specs/{self._spec_id}-*"))
        if matches:
            return matches[0]
        return None

    def _spec_artifacts_mode(self) -> str:
        """Return where build agents should write spec artifacts.

        Ordinary single-repo harness runs use an isolated git worktree, so spec
        artifacts must be written inside that worktree and committed with the
        implementation. Targeted polyrepo runs intentionally keep specs in the
        orchestration repo while implementation happens in a target repo.
        """
        state = self._state_store.read()
        if state.get("target_repo") or state.get("target_path"):
            return "external"
        return "worktree"

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
            "Ralph owns fulfillment refresh and verify-spec regeneration. "
            "Do not run `echelon verify-spec`. "
            "Do not hand-edit `fulfillment-report.md` or `fulfillment-gaps.md`. "
            "If a failure mentions stale/scoped fulfillment evidence, treat it as "
            "read-only context and fix source/tests or stop after writing the harness status marker.\n\n"
            f"Inner fix {inner_iter}. Fix these verification failures "
            f"without re-running the full build pipeline:\n{failures_text}"
        )

    # === Git operations ===

    def _try_checkpoint_progress_commit(
        self,
        *,
        worktree_path: str,
        before_state: Dict[str, Any],
        after_state: Dict[str, Any],
        outer_iter: int,
        inner_iter: int,
        phase: str,
    ) -> Optional[Dict[str, Any]]:
        try:
            return self._checkpoint_progress_commit(
                worktree_path=worktree_path,
                before_state=before_state,
                after_state=after_state,
                outer_iter=outer_iter,
                inner_iter=inner_iter,
                phase=phase,
            )
        except Exception as exc:
            logger.warning("Could not create harness checkpoint commit: %s", exc)
            return None

    def _checkpoint_progress_commit(
        self,
        *,
        worktree_path: str,
        before_state: Dict[str, Any],
        after_state: Dict[str, Any],
        outer_iter: int,
        inner_iter: int,
        phase: str,
    ) -> Optional[Dict[str, Any]]:
        """Commit a dirty worktree when build progress advanced.

        Stage 1 checkpointing records truthful metadata only: task IDs when
        state identifies newly completed tasks, otherwise phase/wave context.
        """
        before_build = before_state.get("build") if isinstance(before_state, dict) else {}
        after_build = after_state.get("build") if isinstance(after_state, dict) else {}
        if not isinstance(before_build, dict):
            before_build = {}
        if not isinstance(after_build, dict):
            after_build = {}

        before_completed = int(before_build.get("completed_tasks") or 0)
        after_completed = int(after_build.get("completed_tasks") or 0)
        phase_group = str(after_build.get("current_phase_group") or "").strip()

        if after_completed <= before_completed and not phase_group:
            return None
        if not self._has_file_changes(worktree_path):
            return None

        task_ids = _newly_completed_task_ids(before_build, after_build)
        label = ",".join(task_ids) if task_ids else (phase_group or "tasks-unknown")
        if task_ids and phase_group:
            label = f"{phase_group} {label}"
        if not task_ids and phase_group:
            label = f"{phase_group} tasks-unknown"
        message = build_echelon_commit_message(
            (
                f"harness-checkpoint: {self._spec_id}/{self._strategy_id} "
                f"iter-{outer_iter} {phase} {label}"
            ),
            EchelonCommitMetadata(
                origin="delivery",
                action="checkpoint",
                spec_id=self._spec_id,
                run_id=self._build_id,
                phase=phase,
                strategy=self._strategy_id,
            ),
        )
        commit = self._gitops.commit(worktree_path, message)
        checkpoint = {
            "commit": commit,
            "outer_iter": outer_iter,
            "inner_iter": inner_iter,
            "phase": phase,
            "task_ids": task_ids,
            "phase_group": phase_group,
            "completed_tasks_before": before_completed,
            "completed_tasks_after": after_completed,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        state = self._state_store.read()
        checkpoints = state.get("checkpoint_commits")
        if not isinstance(checkpoints, list):
            checkpoints = []
        checkpoints.append(checkpoint)
        state["checkpoint_commits"] = checkpoints
        self._state_store.write(state)
        logger.info("Committed harness checkpoint %s for %s", commit[:12], label)
        return checkpoint

    def _has_file_changes(self, worktree_path: str) -> bool:
        """Return True if any files were added or modified since last commit.

        Checks both working-tree changes and staged (index) changes so that
        files written and staged but not yet committed are also detected.
        Returns True on error to avoid false escalation.
        """
        try:
            # git status --porcelain covers both staged and unstaged changes
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True,
                cwd=worktree_path, timeout=10,
            )
            return bool(result.stdout.strip())
        except Exception:
            return True  # Assume progress on error to avoid false escalation

    def _should_continue_after_missing_marker(
        self,
        build_result: Dict[str, Any],
        *,
        worktree_path: str,
        checkpoint: Optional[Dict[str, Any]],
        head_advanced: bool = False,
    ) -> bool:
        """Treat clean markerless builds with evidence of work as verifiable.

        COMMANDER sometimes exits 0 after producing valid code and test output
        but forgets `.harness-build-status.json`. That marker is still required
        for explicit failure/timeout/impasse handling; this recovery path only
        applies when the process exited cleanly and git shows deterministic
        evidence that work happened in the harness worktree.
        """
        build_status = str(build_result.get("build_status") or "unknown")
        if build_status != "unknown":
            return False
        if _is_host_tool_permission_denied(build_result):
            return False

        try:
            exit_code = int(build_result.get("exit_code", 1))
        except (TypeError, ValueError):
            return False
        if exit_code != 0:
            return False

        if checkpoint is not None:
            return True
        if head_advanced:
            return True
        return self._has_confirmed_file_changes(worktree_path)

    def _record_missing_marker_recovery(
        self,
        build_result: Dict[str, Any],
        *,
        checkpoint: Optional[Dict[str, Any]],
        head_advanced: bool = False,
    ) -> None:
        state = self._state_store.read()
        recoveries = state.get("missing_marker_recoveries")
        if not isinstance(recoveries, list):
            recoveries = []
        recoveries.append(
            {
                "build_status": str(build_result.get("build_status") or "unknown"),
                "exit_code": build_result.get("exit_code"),
                "checkpoint_commit": checkpoint.get("commit") if checkpoint else None,
                "head_advanced": head_advanced,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        state["missing_marker_recoveries"] = recoveries
        self._state_store.write(state)
        logger.warning(
            "Build status marker missing after clean exit; continuing to verify "
            "because harness worktree progress was detected"
        )

    def _record_cleanup_warning(self, operation: str, exc: Exception) -> None:
        """Persist non-fatal cleanup failures without replacing the run blocker."""
        try:
            state = self._state_store.read()
            warnings = state.get("cleanup_warnings")
            if not isinstance(warnings, list):
                warnings = []
            warnings.append(
                {
                    "operation": operation,
                    "error": str(exc),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            state["cleanup_warnings"] = warnings
            self._state_store.write(state)
        except Exception as state_exc:
            logger.warning("Could not persist cleanup warning: %s", state_exc)

    def _has_confirmed_file_changes(self, worktree_path: str) -> bool:
        """Return True only when git confirms the worktree has changes."""
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=worktree_path,
                timeout=10,
            )
        except Exception:
            return False
        if result.returncode != 0:
            return False
        return bool(result.stdout.strip())

    @staticmethod
    def _current_head(worktree_path: str) -> Optional[str]:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=worktree_path,
                timeout=10,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    @staticmethod
    def _head_advanced(before: Optional[str], after: Optional[str]) -> bool:
        return bool(before and after and before != after)

    def _commit_and_push(self, worktree_path: str, outer_iter: int) -> str:
        """Commit all changes and push to remote. Returns the branch pushed to.

        Uses the actual current branch of the worktree rather than a hardcoded
        harness/* pattern. In feature-branch mode (echelon flow) the worktree is
        checked out on the echelon feature branch (e.g. '001-weather-dashboard'),
        not on a harness/* branch — pushing the wrong name silently fails.
        """
        fallback = f"harness/{self._spec_id}-{self._strategy_id}-iter-{outer_iter}"
        branch = fallback
        message = build_echelon_commit_message(
            f"harness: {self._spec_id}/{self._strategy_id} iter-{outer_iter}",
            EchelonCommitMetadata(
                origin="delivery",
                action="commit",
                spec_id=self._spec_id,
                run_id=self._build_id,
                strategy=self._strategy_id,
            ),
        )
        try:
            self._gitops.commit(worktree_path, message)
        except Exception as e:
            logger.warning("Commit failed for %s: %s", worktree_path, e)
            raise CommitPushError(
                f"Commit failed: {e}",
                branch=branch,
                worktree_path=worktree_path,
            ) from e

        # Detect the actual branch rather than assuming a harness/* name.
        # create_worktree() checks out the feature branch directly in
        # feature-branch mode, so we must read HEAD to get the real branch.
        try:
            from harness.gitops import _run_git  # local import to avoid circular
            result = _run_git(
                ["branch", "--show-current"],
                cwd=worktree_path,
                check=False,
            )
            detected_branch = result.stdout.strip()
            branch = detected_branch or fallback
            if not result.stdout.strip():
                logger.warning(
                    "Worktree at %s is in detached HEAD state; pushing as %s",
                    worktree_path, branch,
                )
        except Exception as e:
            logger.warning(
                "Could not detect current branch for %s; pushing fallback %s: %s",
                worktree_path, branch, e,
            )

        try:
            self._gitops.push(worktree_path, branch)
            return branch
        except Exception as e:
            logger.warning("Push failed for %s on %s: %s", worktree_path, branch, e)
            raise CommitPushError(
                f"Push failed: {e}",
                branch=branch,
                worktree_path=worktree_path,
            ) from e

    def _manage_pr(self, pr_url: Optional[str], branch: str, converged: bool) -> Optional[str]:
        """Create/update/promote PR as needed."""
        if pr_url is None:
            # First iteration: create draft PR
            pr_url = self._gitops.create_draft_pr(
                branch, self._spec_id, self._strategy_id,
            ) or None

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

    def _mark_spec_ready_to_land(self, worktree_path: str) -> bool:
        """Write Python-owned implemented-but-not-landed spec status."""
        spec_dir = self._find_spec_dir(worktree_path)
        if spec_dir is None:
            state = self._state_store.read()
            expected_spec = bool(state.get("spec_dir") or state.get("spec_file"))
            if not expected_spec:
                logger.info(
                    "No spec directory found for %s; skipping ready_to_land marker",
                    self._spec_id,
                )
                return True
            logger.warning(
                "Could not mark %s ready_to_land: spec directory not found",
                self._spec_id,
            )
            return False
        try:
            write_status(spec_dir, "ready_to_land")
            state = self._state_store.read()
            append_implementation_run(
                spec_dir,
                run_id=str(state.get("run_id") or ""),
                spec_status="ready_to_land",
                verification_result="PASS",
            )
            write_artifact_index(spec_dir)
            return True
        except Exception as exc:
            logger.warning("Could not mark %s ready_to_land: %s", self._spec_id, exc)
            return False

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
        branch: Optional[str] = None,
        extra_state: Optional[Dict[str, Any]] = None,
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
            state["branch"] = branch
            state["last_verify_result"] = (
                _verify_to_dict(final_verify) if final_verify else None
            )
            if extra_state:
                state.update(extra_state)
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
            branch=branch,
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
        # verify_command_needed: check if the user has now configured verify_command
        # or if the project type is now auto-detectable, then re-run from scratch.
        if state.get("termination_reason") == "verify_command_needed":
            if self._config.verify_command:
                self._state_store.transition("running")
                print(
                    "[harness] verify_command configured → re-running from scratch",
                    file=sys.stderr,
                    flush=True,
                )
                return self._run_loop_inner(
                    max_outer=max_outer,
                    max_inner=max_inner,
                    token_budget=token_budget,
                    build_command=build_command,
                    strategy_context=strategy_context,
                    build_prompt=build_prompt,
                )
            else:
                _print_verify_command_needed_banner(self._spec_id, self._strategy_id)
                return LoopResult(
                    status="blocked",
                    termination_reason="verify_command_needed",
                    outer_iterations=state.get("outer_iter", 0),
                    inner_iterations=state.get("inner_iter", 0),
                    tokens_used=state.get("tokens_used", 0),
                    pr_url=state.get("pr_url"),
                    final_verify=None,
                )

        # Budget-exhausted recovery: if budget was bumped, resume from current progress
        if state.get("termination_reason") == "budget_exhausted":
            stored_usage = state.get("tokens_used", 0)
            # None/<=0 = unlimited; positive must clear 95% re-trigger threshold
            budget_sufficient = token_budget is None or token_budget <= 0 or token_budget > stored_usage / 0.95
            if budget_sufficient:
                self._state_store.transition("running")
                budget_display = f"{token_budget:,}" if token_budget else "∞"
                print(
                    f"[harness] budget bumped → resuming "
                    f"(usage={stored_usage:,}, new budget={budget_display})",
                    file=sys.stderr,
                    flush=True,
                )
                return self._run_loop_inner(
                    max_outer=max_outer,
                    max_inner=max_inner,
                    token_budget=token_budget,
                    build_command=build_command,
                    strategy_context=strategy_context,
                    build_prompt=build_prompt,
                )
            else:
                print(
                    f"\n[harness] ✗ Token budget still exhausted "
                    f"(usage={stored_usage:,}, budget={token_budget:,}).\n"
                    f"  Increase token_budget in harness config or pass --reset to start fresh.",
                    file=sys.stderr,
                )
                # _finalize() is intentionally skipped here: the state already
                # reflects the blocked/exhausted status from the prior run and
                # calling it would not change anything meaningful.
                return LoopResult(
                    status="blocked",
                    termination_reason="budget_exhausted",
                    outer_iterations=state.get("outer_iter", 0),
                    inner_iterations=state.get("inner_iter", 0),
                    tokens_used=stored_usage,
                    pr_url=state.get("pr_url"),
                    final_verify=None,
                )

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

def _consecutive_failure_repeat_count(
    failure_history: List[List[str]],
    repeated_failures: set[str],
) -> int:
    """Return the current consecutive streak for the repeated failure set."""
    if not failure_history or not repeated_failures:
        return 0

    max_count = 0
    for fingerprint in repeated_failures:
        count = 0
        for failures in reversed(failure_history):
            if fingerprint in failures:
                count += 1
            else:
                break
        max_count = max(max_count, count)
    return max_count


def _print_verify_command_needed_banner(spec_id: str, strategy_id: str) -> None:
    """Print a formatted banner when verify_command is missing."""
    from echelon.ui import banner as _banner
    _banner(
        "HARNESS — TEST RUNNER MISSING",
        [
            ("spec", spec_id),
            ("strategy", strategy_id),
            ("problem",
             "The harness could not detect a test runner in the built worktree.\n"
             "Run 'echelon harness init' to auto-detect high-confidence verification, or add\n"
             "verify_command manually to echelon-config.yml, for example:\n\n"
             "  verify_command: swift test --package-path Packages/MyLib\n"
             "  verify_command: pytest\n"
             "  verify_command: go test ./..."),
            ("resume with", f"echelon harness resume {spec_id}"),
            ("discard with", f"echelon harness run {spec_id} --reset"),
        ],
        file=sys.stderr,
    )


def _print_blocked_banner(spec_id: str, strategy_id: str, escalation_file: str) -> None:
    """Print a formatted blocked banner to stderr."""
    from echelon.ui import banner as _banner
    _banner(
        "HARNESS — ESCALATION PENDING",
        [
            ("spec", spec_id),
            ("strategy", strategy_id),
            ("file", escalation_file),
            ("answer in", "Append a ## Answer section to the escalation file."),
            ("resume with", f"echelon harness resume {spec_id}"),
            ("discard with", f"echelon harness run {spec_id} --reset"),
        ],
        file=sys.stderr,
    )


def _clear_build_status(worktree_path: str) -> None:
    """Remove .harness-build-status.json before a build iteration.

    Prevents a status file committed from a prior build on this branch from
    being read back as a successful completion of the current build.
    """
    try:
        (Path(worktree_path) / BUILD_STATUS_FILENAME).unlink(missing_ok=True)
    except Exception:
        pass


def _snapshot_project_status(
    project_dir: Any,
    worktree_path: str,
) -> Optional[Dict[str, Any]]:
    """Return the real target repo status before an LLM step.

    The harness worktree may live under ``runs/`` inside the target repo. That
    is okay: we compare snapshots instead of requiring the target repo to be
    pristine. A changed snapshot means the LLM wrote somewhere outside the
    isolated worktree Ralph is managing.
    """
    try:
        project = Path(project_dir)
    except TypeError:
        return None
    if not project.exists():
        return None
    try:
        if project.resolve() == Path(worktree_path).resolve():
            return None
    except OSError:
        return None
    status = _git_status_lines(project)
    if status is None:
        return None
    return {
        "project_dir": str(project),
        "before_status": status,
    }


def _detect_containment_violation(
    before: Optional[Dict[str, Any]],
    project_dir: Any,
    worktree_path: str,
) -> Optional[Dict[str, Any]]:
    """Detect writes to the real target repo during an isolated harness step."""
    if before is None:
        return None
    try:
        project = Path(project_dir)
    except TypeError:
        return None
    after = _git_status_lines(project)
    if after is None:
        return None
    before_lines = list(before.get("before_status") or [])
    if after == before_lines:
        return None
    return {
        "project_dir": str(project),
        "worktree_path": str(worktree_path),
        "before_status": before_lines,
        "after_status": after,
        "changed_status": _status_delta(before_lines, after),
    }


def _git_status_lines(project: Path) -> Optional[List[str]]:
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if status.returncode != 0:
            return None
        return [line for line in status.stdout.splitlines() if line.strip()]
    except Exception:
        return None


def _porcelain_path(line: str) -> str:
    value = line[3:].strip()
    if " -> " in value:
        value = value.split(" -> ", 1)[1].strip()
    return value.strip('"')


def _is_fulfillment_refresh_deferred(verify_result: VerifyResult) -> bool:
    return any(f.id == "fulfillment-refresh-deferred" for f in verify_result.failures)


def _is_provider_session_limit_verify_result(verify_result: VerifyResult) -> bool:
    return any(
        f.id == "fulfillment-refresh-provider-session-limit"
        for f in verify_result.failures
    )


def _provider_session_limit_failure_text(verify_result: VerifyResult) -> str:
    for failure in verify_result.failures:
        if failure.id == "fulfillment-refresh-provider-session-limit":
            return failure.error
    return ""


def _print_verify_spec_provider_session_limit_banner(
    spec_id: str,
    strategy_id: str,
    verify_result: VerifyResult,
) -> None:
    from echelon.ui import banner as _ui_banner

    message = _provider_session_limit_failure_text(verify_result)
    _ui_banner(
        "HARNESS — PROVIDER SESSION LIMIT",
        [
            ("spec", spec_id),
            ("strategy", strategy_id),
            ("why", "LLM provider session limit reached during verify-spec fulfillment refresh"),
            ("provider", message),
            (
                "meaning",
                "Implementation progress was checkpointed, but full fulfillment evidence could not be refreshed.",
            ),
            ("next", f"echelon harness resume {spec_id}  (retry verification after provider reset)"),
        ],
        file=sys.stderr,
    )


def _is_only_fulfillment_gaps(verify_result: VerifyResult) -> bool:
    return (
        not verify_result.passed
        and len(verify_result.failures) == 1
        and verify_result.failures[0].category == FailureCategory.OTHER
        and verify_result.failures[0].id == "fulfillment-gaps"
    )


def _clean_task_ids(value: object) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(task_id).strip() for task_id in value if str(task_id).strip()]


def _is_verify_owned_artifact(path: str) -> bool:
    posix = path.replace("\\", "/")
    if posix.startswith("runs/verify-spec-"):
        return True
    if "/runs/verify-spec-" in posix:
        return True
    if not posix.startswith("specs/"):
        return False
    name = PurePosixPath(posix).name
    return name in {"fulfillment-report.md", "fulfillment-gaps.md"}


def _status_delta(before: List[str], after: List[str]) -> List[str]:
    before_set = set(before)
    return [line for line in after if line not in before_set]


def _print_containment_violation_banner(
    spec_id: str,
    strategy_id: str,
    violation: Dict[str, Any],
) -> None:
    from echelon.ui import banner as _ui_banner

    changed = "\n".join(violation.get("changed_status") or [])
    if not changed:
        changed = "\n".join(violation.get("after_status") or [])
    _ui_banner(
        "HARNESS — CONTAINMENT VIOLATION",
        [
            ("spec", spec_id),
            ("strategy", strategy_id),
            ("project", str(violation.get("project_dir") or "")),
            ("worktree", str(violation.get("worktree_path") or "")),
            (
                "why",
                "The LLM build changed files outside the isolated worktree while Ralph was managing that worktree.",
            ),
            ("changed", changed or "(status changed, no changed lines captured)"),
            (
                "next",
                f"inspect/salvage the out-of-worktree changes, then rerun: echelon harness run {spec_id}",
            ),
        ],
        file=sys.stderr,
    )


def _salvage_build_worktree(
    *,
    worktree_path: str,
    spec_id: str,
    strategy_id: str,
    outer_iter: int,
) -> Optional[Dict[str, str]]:
    """Commit dirty harness worktree output before blocking on build_incomplete."""
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if status.returncode != 0 or not status.stdout.strip():
            return None
        (Path(worktree_path) / BUILD_STATUS_FILENAME).unlink(missing_ok=True)
        subprocess.run(
            ["git", "add", "-A"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        message = build_echelon_commit_message(
            f"harness-salvage: {spec_id} {strategy_id} iter-{outer_iter}",
            EchelonCommitMetadata(
                origin="delivery",
                action="salvage",
                spec_id=spec_id,
                strategy=strategy_id,
            ),
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Echelon Harness",
                "-c",
                "user.email=echelon-harness@example.invalid",
                "commit",
                "-m",
                message,
            ],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout.strip()
        return {
            "salvage_commit": commit,
            "salvage_branch": branch,
            "salvage_verified": "not_run",
        }
    except Exception as exc:
        logger.warning("Could not salvage dirty harness worktree %s: %s", worktree_path, exc)
        return None


def _is_provider_session_limit(build_result: dict[str, object]) -> bool:
    text = _provider_limit_text(build_result).lower()
    if not text:
        return False
    needles = (
        "session limit",
        "usage limit",
        "rate limit",
        "quota exceeded",
        "resets ",
        "reset window",
    )
    return any(needle in text for needle in needles)


def _provider_limit_text(build_result: dict[str, object]) -> str:
    return "\n".join(
        str(build_result.get(key) or "")
        for key in ("stdout", "stderr", "build_reason", "reason")
    )


def _provider_session_limit_message(build_result: dict[str, object]) -> str:
    text = _provider_limit_text(build_result)
    for line in text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        lower = cleaned.lower()
        if any(
            needle in lower
            for needle in ("session limit", "usage limit", "rate limit", "quota exceeded")
        ):
            return cleaned
    return ""


def _provider_session_limit_reset_hint(build_result: dict[str, object]) -> str:
    text = _provider_limit_text(build_result)
    patterns = (
        r"resets?\s+(?:at\s+|in\s+)?([^\n.;]+)",
        r"reset window[:\s]+([^\n.;]+)",
        r"try again\s+(?:at\s+|in\s+)?([^\n.;]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _is_host_tool_permission_denied(build_result: dict[str, object]) -> bool:
    text = "\n".join(
        str(build_result.get(key) or "")
        for key in ("stdout", "stderr", "build_reason", "reason")
    ).lower()
    if not text:
        return False
    permission_needles = (
        "requires approval",
        "require approval",
        "requested permissions",
        "permission not granted",
        "permissions gate",
        "permission mode is denying",
        "requires permission",
        "command requires approval",
        "this command requires approval",
        "write access",
        "execute access",
    )
    action_needles = (
        "write",
        "bash",
        "python",
        "pytest",
        "command",
        "execution",
        "tool",
        "worktree",
    )
    return any(needle in text for needle in permission_needles) and any(
        needle in text for needle in action_needles
    )


def _newly_completed_task_ids(
    before_build: Dict[str, Any],
    after_build: Dict[str, Any],
) -> List[str]:
    """Return task IDs newly marked done between two build state snapshots."""
    before_results = before_build.get("task_results")
    after_results = after_build.get("task_results")
    if not isinstance(before_results, dict):
        before_results = {}
    if not isinstance(after_results, dict):
        return []

    def _is_done(value: Any) -> bool:
        if isinstance(value, dict):
            status = str(value.get("status") or value.get("verdict") or "").upper()
            return status in {"DONE", "PASS", "PASSED", "COMPLETE", "COMPLETED"}
        return str(value).upper() in {"DONE", "PASS", "PASSED", "COMPLETE", "COMPLETED"}

    newly_done: List[str] = []
    for task_id, result in after_results.items():
        if _is_done(result) and not _is_done(before_results.get(task_id)):
            newly_done.append(str(task_id))
    return sorted(newly_done)


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
