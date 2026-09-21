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
import hashlib
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional
from uuid import uuid4

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from harness.build_result import BUILD_STATUS_FILENAME, ECHELON_RESULT_FILENAME
from harness.candidate_evidence import CandidateEvidenceRunner
from harness.convergence import (
    DEFAULT_MAX_OUTER,
    ConvergenceLease,
    LeaseObservation,
    ProgressSnapshot,
)
from harness.config import HarnessConfig
from harness.dirty_adjudicator import adjudicate_dirty_worktree
from harness.documentation_gate import (
    DocumentationGateResult,
    evaluate_documentation_gate,
)
from harness.coverage_evidence import (
    active_unmapped_coverage_requirement_ids,
    parse_coverage_map_obligations,
    task_owned_coverage_case_ids,
)
from harness.deferred_scope import active_entries
from harness.coverage_observation import (
    CoverageObservationError,
    CoverageObservationRef,
    CoverageObservationResult,
    load_coverage_observation,
    validate_coverage_observation,
    write_coverage_observation,
)
from harness.coverage_observer_runner import run_coverage_observers
from harness.llm_provider import AICodingCliProvider
from harness.escalation import EscalationHandler
from harness.errors import NotSupportedError, SandboxError
from harness.exec_result import ExecResult
from harness.failure_signature import detect_same_failure, normalize
from harness.fulfillment_runner import FulfillmentRunner
from harness.delivery_results import ImplementationResult
from harness.mode import ModeController
from harness.provider import SandboxHandle, SandboxProvider, SandboxSpec
from harness.product_inventory import product_evidence_fingerprint
from harness.runnability_contract import (
    CONTRACT_PATH as RUNNABILITY_CONTRACT_PATH,
    RunnabilityContractError,
    load_runnability_contract,
    runnability_contract_sha256,
)
from harness.runnability_disposition import (
    RunnabilityDispositionError,
    read_runnability_disposition,
)
from harness.runnability_evidence import (
    RunnabilityEvidenceRef,
    load_runnability_evidence_ref,
    validate_runnability_report,
    runnability_product_fingerprint,
)
from harness.runnability_runner import RunnabilityRunResult, RunnabilityRunner
from harness.phase_a_readiness import validate_phase_a_readiness
from harness.secret_scan import scan_git_staged
from harness.spec_frontmatter import find_spec_dir
from harness.state import StateStore
from harness.task_progress import (
    TaskProgressError,
    summarize_task_progress,
    update_task_progress_markdown,
)
from harness.verify_result import FailureCategory, FailureEntry, VerifyResult
from harness.verification_evidence import (
    VerificationEvidenceRef,
    VerificationStage,
    redact_verification_text,
    write_verification_receipt,
)
from harness.verification_diagnostic import (
    diagnosis_required as verification_diagnosis_required,
    run_verification_diagnostic,
)
from harness.verification_plan import build_verification_plan, materialize_services
from harness.stacks.resolver import (
    resolved_coverage_observer_plan_sha256,
    resolved_stack_contract_sha256,
)
from harness.stacks.preflight import (
    coverage_observer_preflight_findings,
    required_coverage_observers_for_types,
)
from harness.verify_detection import detect_verify_command
from harness.canonical_requirements import extract_canonical_requirements
from kernel.fulfillment import (
    blocking_fulfillment_gaps,
    blocking_statuses,
    fulfillment_has_blocking_gaps,
    fulfillment_report_is_current,
    latest_fulfillment_report,
    read_fulfillment_metadata,
    validate_deferred_scope_rows,
)
from kernel.task_contract import TaskRow, parse_task_rows

logger = logging.getLogger(__name__)

SAME_FAILURE_REPEAT_THRESHOLD = 3

_NON_CHARGEABLE_INFRASTRUCTURE_REASONS = {
    "provider_session_limit",
    "sandbox_verification_unavailable",
    "user_runnability_sandbox_prerequisite",
    "verification_infrastructure",
    "verify_command_needed",
}
_BANZAI_MILESTONE_DEFER_REASON = (
    "banzai milestone defers full verify until task completion"
)
_SCOPED_REFRESH_DEFER_REASON = "scoped fulfillment refresh completed"
_EXTERNAL_SPEC_ARTIFACT_FAILURE_IDS = {"coverage-observer-scope-invalid"}
_TASK_HEADER_RE = re.compile(r"^- \[[ xX]\] (?P<task_id>T-[A-Za-z0-9-]+)\b")
_TASK_FILE_BULLET_RE = re.compile(r"^\s*-\s+`(?P<path>[^`]+)`(?:\s|$)")
_VERIFICATION_ARTIFACT_PATHS = (
    "test-results/**",
    "playwright-report/**",
    "blob-report/**",
    "coverage/**",
)


def _is_user_runnability_sandbox_prerequisite(result: VerifyResult) -> bool:
    return any(
        failure.id == "user-runnability-sandbox-prerequisite"
        for failure in result.failures
    )


def _runnability_target_id(target_repo: str) -> str:
    target = str(target_repo).strip().rstrip("/")
    if not target:
        return "workspace"
    return Path(target).name or "target"


def _next_runnability_attempt_sequence(evidence_dir: Path) -> int:
    highest = 0
    for path in Path(evidence_dir).glob("attempt-*.json"):
        match = re.match(r"attempt-(\d+)-", path.name)
        if match is not None:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _missing_completed_task_deliverables(
    markdown: str,
    *,
    task_statuses: Mapping[str, str],
    worktree_path: Path,
    implementation_target: str,
) -> list[str]:
    """Return completed task deliverables absent from the target worktree."""
    target = implementation_target.strip().strip("/")
    missing: list[str] = []
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        match = _TASK_HEADER_RE.match(line)
        if match is None or task_statuses.get(match.group("task_id")) not in {
            "DONE", "DONE_WITH_CONCERNS"
        }:
            continue
        task_id = match.group("task_id")
        end = next(
            (
                candidate
                for candidate in range(index + 1, len(lines))
                if _TASK_HEADER_RE.match(lines[candidate]) is not None
            ),
            len(lines),
        )
        in_files = False
        for task_line in lines[index + 1:end]:
            if task_line.strip() == "**Files:**":
                in_files = True
                continue
            if in_files and task_line.startswith("  **"):
                break
            if not in_files:
                continue
            path_match = _TASK_FILE_BULLET_RE.match(task_line)
            if path_match is None:
                continue
            declared = path_match.group("path").strip().lstrip("./")
            relative = (
                declared[len(target) + 1:]
                if target and declared.startswith(target + "/")
                else declared
            )
            if relative and not (worktree_path / relative).is_file():
                missing.append(f"{task_id}: {relative}")
    return missing


def _is_verification_environment_deferral(
    result: Mapping[str, object],
) -> bool:
    return (
        result.get("completion_marker_explicit") is True
        and str(result.get("build_status") or "") == "blocked"
        and str(result.get("blocker_kind") or "")
        == "verification_environment"
    )


def _current_git_commit(worktree: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def _current_git_branch(worktree: Path) -> str | None:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def _recent_git_commits(worktree: Path, *, limit: int = 3) -> list[str]:
    result = subprocess.run(
        ["git", "log", f"--max-count={limit}", "--abbrev=12", "--format=%h %s"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _normalized_path_list(value: object, *, base_path: object | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    base = Path(str(base_path)).expanduser() if base_path else None
    paths: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            path = Path(text).expanduser()
            if base is not None and not path.is_absolute():
                path = base / path
            paths.append(str(path))
    return paths


class CommitPushError(RuntimeError):
    """Raised when verified work cannot be committed or pushed."""

    def __init__(
        self,
        message: str,
        *,
        branch: str,
        worktree_path: str,
        stage: str = "commit",
    ) -> None:
        super().__init__(message)
        self.branch = branch
        self.worktree_path = worktree_path
        self.stage = stage


class _DocumentationBuildResult(dict):
    """Controller-only provenance for a taskless documentation completion."""


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
        fulfillment_runner: Optional[FulfillmentRunner] = None,
        build_id: str = "",
        fresh_delivery: bool = False,
        fresh_branch_base: Optional[str] = None,
        defer_target_merge: bool = False,
        resume_worktree_path: Optional[str] = None,
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
        self._controlled_slice_budget: float | None = None
        self._fulfillment_runner = (
            fulfillment_runner
            if fulfillment_runner is not None
            else FulfillmentRunner(llm_provider, controlled=True)
            if llm_provider is not None else None
        )
        self._build_id = build_id
        self._fresh_delivery = fresh_delivery
        self._fresh_branch_base = fresh_branch_base
        self._defer_target_merge = defer_target_merge
        self._resume_worktree_path = resume_worktree_path
        self._candidate_evidence_runner = CandidateEvidenceRunner(
            provider=self._provider,
            config=lambda: self._config,
            sandbox_spec_factory=lambda worktree: self._build_sandbox_spec(
                str(worktree), 0
            ),
            evidence_root=self._state_store.state_dir.parent / "evidence",
            spec_id=self._spec_id,
            target_id=_runnability_target_id(self._config.target_repo),
            strategy_id=self._strategy_id,
            build_id=self._build_id
            or str(self._state_store.read().get("run_id") or "run"),
        )

        self._interrupted = False
        self._original_sigterm: Any = None
        self._original_sigint: Any = None

    # === Main entry point ===

    def reuse_worktree_on_next_run(self, worktree_path: str) -> None:
        """Carry a downstream repair into the next Phase 1 verification run."""
        self._resume_worktree_path = worktree_path

    def run_loop(
        self,
        max_outer: int = DEFAULT_MAX_OUTER,
        max_inner: int = 3,
        token_budget: Optional[int] = None,
        build_command: str = "echelon build",
        strategy_context: str = "",
        build_prompt: str = "",
    ) -> ImplementationResult:
        """Execute the ralph-loop until a termination condition.

        Args:
            max_outer: Maximum outer iterations.
            max_inner: Maximum inner iterations per outer.
            token_budget: Total token budget (None = unlimited).
            build_command: Shell command to invoke for the build phase.
                Defaults to ``echelon build``. Override via strategy file
                frontmatter.
            strategy_context: Additional context from strategy file body.

        Returns:
            ImplementationResult with termination details.
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
    ) -> ImplementationResult:
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

        # Resolve the spec's feature branch once. When found, all worktrees are
        # checked out on that branch so spec artifacts (spec.md, tasks.md,
        # constitution.md, etc.) are available without the build agent needing to
        # merge them in manually. Falls back to an ordinary harness delivery
        # branch when no source-owned feature branch exists.
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
                    "No source-owned feature branch found for spec '%s' — using "
                    "a harness delivery branch",
                    self._spec_id,
                )
        except Exception as e:
            logger.warning(
                "Could not resolve feature branch for spec '%s' (continuing with "
                "a harness delivery branch): %s",
                self._spec_id, e,
            )

        outer_iter = start_outer
        while self._convergence_lease().meaningful_attempts < max_outer:
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

            pending_slice = self._state_store.read().get("delivery_slice_operation")
            recovering_slice = pending_slice is not None
            if recovering_slice:
                preserved = pending_slice.get("worktree_path") if isinstance(pending_slice, dict) else None
                if (not isinstance(preserved, str) or not Path(preserved).is_absolute()
                        or Path(preserved).is_symlink() or not Path(preserved).is_dir()):
                    return self._finalize(
                        status="blocked", reason="delivery_reconciliation_required",
                        outer_iterations=outer_iter, inner_iterations=total_inner_iterations,
                        pr_url=pr_url, tokens_used=tokens_used, final_verify=None,
                        extra_state={"build_reason": "pending delivery candidate is missing or unsafe"},
                    )
                self._resume_worktree_path = None
                worktree_path = preserved
            # Create worktree — use feature branch when available so spec artifacts
            # (spec.md, tasks.md, constitution.md) are present from the start.
            elif self._resume_worktree_path and outer_iter == start_outer:
                worktree_path = self._resume_worktree_path
                self._resume_worktree_path = None
                if not Path(worktree_path).is_dir():
                    return self._finalize(
                        status="blocked",
                        reason="verified_provenance_unavailable",
                        outer_iterations=outer_iter,
                        inner_iterations=total_inner_iterations,
                        pr_url=pr_url,
                        tokens_used=tokens_used,
                        final_verify=None,
                    )
                state = self._state_store.read()
                reentry = state.get("downstream_reentry")
                if isinstance(reentry, dict):
                    state["downstream_reentry"] = {**reentry, "consumed": True}
                    self._state_store.write(state)
                logger.info(
                    "Reusing registered worktree %s for downstream repair re-verification",
                    worktree_path,
                )
            else:
                worktree_path = self._gitops.create_worktree(
                    self._spec_id, self._strategy_id, outer_iter,
                    base_branch=feature_branch,
                    build_id=self._build_id,
                    prepare_codegraph=True,
                    fresh_branch=self._fresh_delivery and outer_iter == start_outer,
                    fresh_branch_base=(
                        self._fresh_branch_base
                        if self._fresh_delivery and outer_iter == start_outer
                        else None
                    ),
                )
            preserve_worktree = False

            try:
                phase_a_blockers = [] if recovering_slice else self._sync_phase_a_inputs_into_worktree(
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

                # Host-side LLM builds and verification do not use the sandbox.
                # Avoid creating it here: doing so makes Codex/Claude delivery
                # fail when Docker is unavailable despite no sandbox operation
                # being required.
                handle: Optional[SandboxHandle] = None

                try:
                    # Clear stale build status before each iteration so a
                    # status file committed from a prior build on this branch
                    # cannot be mistaken for this build completing successfully.
                    _clear_build_status(worktree_path)

                    # Run build
                    iter_prompt = self._make_iter_prompt(build_prompt, outer_iter, last_verify_failures_text)
                    before_build_state = self._state_store.read()
                    containment_before = _snapshot_containment_projects(
                        before_build_state,
                        getattr(self._gitops, "base_dir", None),
                        worktree_path,
                    )
                    before_build_head = self._current_head(worktree_path)
                    self._controlled_slice_budget = (
                        token_budget * 0.95 - tokens_used if token_budget and token_budget > 0 else None
                    )
                    build_result = self._exec_build(
                        handle, build_command, strategy_context,
                        worktree_path=worktree_path,
                        prompt=iter_prompt,
                    )
                    after_build_head = self._current_head(worktree_path)
                    source_root_violation = self._detect_forbidden_source_root_access(
                        before_build_state,
                        build_result,
                    )
                    if source_root_violation is not None:
                        preserve_worktree = True
                        _print_source_root_containment_violation_banner(
                            self._spec_id,
                            self._strategy_id,
                            source_root_violation,
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
                                "source_root_containment_violation": source_root_violation,
                            },
                        )
                    harness_source_violation = self._detect_forbidden_harness_source_access(
                        build_result,
                        worktree_path=worktree_path,
                    )
                    if harness_source_violation is not None:
                        preserve_worktree = True
                        _print_harness_source_containment_violation_banner(
                            self._spec_id,
                            self._strategy_id,
                            harness_source_violation,
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
                                "harness_source_containment_violation": harness_source_violation,
                            },
                        )
                    containment_violation = _detect_first_containment_violation(
                        containment_before,
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
                    tokens_used += _known_token_count(build_result.get("tokens"))
                    self._enforce_completed_task_ids(build_result, worktree_path)

                    build_log_phase = "build"

                    # Log build iteration
                    self._append_iteration_log(
                        state, outer_iter, 0, build_log_phase,
                        build_result.get("exit_code", 0),
                        build_result.get("passed", True),
                        build_result.get("duration_s", 0.0),
                        build_result.get("tokens"),
                        provider_invocation=build_result.get("provider_invocation"),
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
                        allow_without_task_progress=(
                            build_result.get("completion_marker_explicit", False)
                            and build_result.get("passed", True)
                            and build_result.get("build_status") == "done"
                        ),
                    )

                    # Check mode boundary
                    if self._mode.should_pause_at_boundary("after_build"):
                        preserve_worktree = True
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
                        preserve_worktree = term_status in {"blocked", "interrupted"}
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
                        if _is_verification_environment_deferral(build_result):
                            try:
                                deferred_commit = (
                                    self._checkpoint_verification_deferred_candidate(
                                        worktree_path,
                                        outer_iter=outer_iter,
                                        inner_iter=0,
                                        phase="build",
                                    )
                                )
                                self._record_verification_environment_deferral(
                                    build_result,
                                    commit=deferred_commit,
                                    outer_iter=outer_iter,
                                    inner_iter=0,
                                    phase="build",
                                )
                            except Exception as exc:
                                preserve_worktree = True
                                return self._finalize(
                                    status="blocked",
                                    reason="verification_evidence_invalid",
                                    outer_iterations=outer_iter + 1,
                                    inner_iterations=total_inner_iterations,
                                    pr_url=pr_url,
                                    tokens_used=tokens_used,
                                    final_verify=VerifyResult(
                                        passed=False,
                                        failures=[
                                            FailureEntry(
                                                FailureCategory.OTHER,
                                                "verification-evidence-invalid",
                                                "could not checkpoint verification-deferred "
                                                f"candidate: {exc}",
                                            )
                                        ],
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
                            if build_status == "timeout":
                                why = "build invocation timed out before COMMANDER finalized"
                                meaning = (
                                    "The controlled delivery slice exceeded its timeout before "
                                    "verification and final status could be trusted"
                                )
                            elif build_status == "blocked":
                                why = "controlled delivery reported a blocker"
                                meaning = (
                                    "The delivery controller completed all safely resolvable work and "
                                    "requires an owner decision before it can proceed"
                                )
                            else:
                                why = f"build reported status '{build_status}'"
                                meaning = (
                                    "The controlled delivery slice did not complete successfully"
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
                            next_action = (
                                "resolve the reported blocker, then start a new delivery run"
                                if build_status == "blocked"
                                else "recover and finalize this build"
                            )
                            fields.extend(
                                [
                                    ("meaning", meaning),
                                    (
                                        "next",
                                        f"echelon delivery continue {self._spec_id}  ({next_action})",
                                    ),
                                ]
                            )
                            title = (
                                "HARNESS — BUILD BLOCKED"
                                if build_status == "blocked"
                                else "HARNESS — BUILD DID NOT COMPLETE"
                            )
                            _ui_banner(title, fields, file=sys.stderr)
                            blocked_state = {
                                **(salvage or {}),
                                "build_status": build_status,
                                "build_reason": build_reason,
                                "build_exit_code": build_exit_code,
                            }
                            return self._finalize(
                                status="blocked",
                                reason=(
                                    "build_blocked"
                                    if build_status == "blocked"
                                    else "build_incomplete"
                                ),
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
                    verify_result = self._apply_verification_diagnosis(
                        verify_result, worktree_path
                    )
                    self._controlled_slice_budget = (
                        max(0, token_budget * 0.95 - tokens_used - verify_result.token_usage)
                        if token_budget and token_budget > 0 else None)
                    verify_result = self._apply_post_verify_gates(
                        verify_result,
                        worktree_path,
                        completed_task_ids=scoped_completed_task_ids,
                        changed_files=scoped_changed_files,
                    )
                    tokens_used += verify_result.token_usage
                    self._record_provider_attempt_summary(
                        phase="build",
                        attempt=outer_iter + 1,
                        result=build_result,
                        verify_result=verify_result,
                        changed_files=scoped_changed_files,
                    )

                    if _is_provider_session_limit_verify_result(verify_result):
                        preserve_worktree = True
                        _print_verify_spec_provider_session_limit_banner(
                            self._spec_id,
                            self._strategy_id,
                            verify_result,
                        )
                        return self._finalize(
                            status="blocked",
                            reason="provider_session_limit",
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
                        preserve_worktree = True
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

                    # Infrastructure cannot be repaired by the product agent.
                    # Block immediately with a durable reason instead of consuming
                    # build retries and misreporting a coordinator exception.
                    if any(
                        f.id == "sandbox-verification-unavailable"
                        for f in verify_result.failures
                    ):
                        preserve_worktree = True
                        return self._finalize(
                            status="blocked",
                            reason="sandbox_verification_unavailable",
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=verify_result,
                        )

                    if _is_user_runnability_sandbox_prerequisite(verify_result):
                        preserve_worktree = True
                        return self._finalize(
                            status="blocked",
                            reason="user_runnability_sandbox_prerequisite",
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
                        preserve_worktree = True
                        return self._pause_at_boundary(
                            "after_verify", outer_iter, total_inner_iterations,
                            pr_url, tokens_used, verify_result,
                        )

                    if verify_result.passed:
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
                                extra_state=self._publish_checkpoint_state(
                                    worktree_path=worktree_path,
                                    branch=e.branch,
                                    stage=e.stage,
                                    verify_result=verify_result,
                                    error=e,
                                ),
                            )
                        if not self._merge_verified_branch(worktree_path, branch, verify_result):
                            preserve_worktree = True
                            return self._finalize(
                                status="blocked",
                                reason="target_merge_failed",
                                outer_iterations=outer_iter + 1,
                                inner_iterations=total_inner_iterations,
                                pr_url=pr_url,
                                tokens_used=tokens_used,
                                final_verify=verify_result,
                                branch=branch,
                                extra_state=self._publish_checkpoint_state(
                                    worktree_path=worktree_path,
                                    branch=branch,
                                    stage="target_merge",
                                    verify_result=verify_result,
                                ),
                            )
                        try:
                            self._commit_orchestration_spec_artifacts(
                                worktree_path, outer_iter, branch=branch
                            )
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
                                extra_state=self._publish_checkpoint_state(
                                    worktree_path=worktree_path,
                                    branch=e.branch,
                                    stage=e.stage,
                                    verify_result=verify_result,
                                    error=e,
                                ),
                            )
                        try:
                            pr_url = self._manage_pr(pr_url, branch, converged=True)
                        except Exception as exc:
                            preserve_worktree = True
                            logger.warning("Verified PR publication failed: %s", exc)
                            return self._finalize(
                                status="blocked",
                                reason="publish_failed",
                                outer_iterations=outer_iter + 1,
                                inner_iterations=total_inner_iterations,
                                pr_url=pr_url,
                                tokens_used=tokens_used,
                                final_verify=verify_result,
                                branch=branch,
                                extra_state=self._publish_checkpoint_state(
                                    worktree_path=worktree_path,
                                    branch=branch,
                                    stage="pr",
                                    verify_result=verify_result,
                                    error=exc,
                                ),
                            )
                        # Phase 2/3 and landing consume the converged delivery
                        # worktree after Ralph returns, even on an early outer
                        # iteration.
                        preserve_worktree = True
                        return self._finalize(
                            status="verified",
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
                        preserve_worktree = True
                        _print_verify_spec_provider_session_limit_banner(
                            self._spec_id,
                            self._strategy_id,
                            final_verify,
                        )
                        return self._finalize(
                            status="blocked",
                            reason="provider_session_limit",
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
                                extra_state=self._publish_checkpoint_state(
                                    worktree_path=worktree_path,
                                    branch=e.branch,
                                    stage=e.stage,
                                    verify_result=inner_result.get("final_verify"),
                                    error=e,
                                ),
                            )
                        if not self._merge_verified_branch(
                            worktree_path, branch, inner_result.get("final_verify")
                        ):
                            preserve_worktree = True
                            return self._finalize(
                                status="blocked",
                                reason="target_merge_failed",
                                outer_iterations=outer_iter + 1,
                                inner_iterations=total_inner_iterations,
                                pr_url=pr_url,
                                tokens_used=tokens_used,
                                final_verify=inner_result.get("final_verify"),
                                branch=branch,
                                extra_state=self._publish_checkpoint_state(
                                    worktree_path=worktree_path,
                                    branch=branch,
                                    stage="target_merge",
                                    verify_result=inner_result.get("final_verify"),
                                ),
                            )
                        try:
                            self._commit_orchestration_spec_artifacts(
                                worktree_path, outer_iter, branch=branch
                            )
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
                                extra_state=self._publish_checkpoint_state(
                                    worktree_path=worktree_path,
                                    branch=e.branch,
                                    stage=e.stage,
                                    verify_result=inner_result.get("final_verify"),
                                    error=e,
                                ),
                            )
                        try:
                            pr_url = self._manage_pr(pr_url, branch, converged=True)
                        except Exception as exc:
                            preserve_worktree = True
                            logger.warning("Verified PR publication failed: %s", exc)
                            return self._finalize(
                                status="blocked",
                                reason="publish_failed",
                                outer_iterations=outer_iter + 1,
                                inner_iterations=total_inner_iterations,
                                pr_url=pr_url,
                                tokens_used=tokens_used,
                                final_verify=inner_result.get("final_verify"),
                                branch=branch,
                                extra_state=self._publish_checkpoint_state(
                                    worktree_path=worktree_path,
                                    branch=branch,
                                    stage="pr",
                                    verify_result=inner_result.get("final_verify"),
                                    error=exc,
                                ),
                            )
                        # Phase 2/3 and landing consume the converged delivery
                        # worktree after Ralph returns, even on an early outer
                        # iteration.
                        preserve_worktree = True
                        return self._finalize(
                            status="verified",
                            reason="converged",
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=inner_result.get("final_verify"),
                            branch=branch,
                        )

                    if inner_result.get("blocked"):
                        # Preserve committed post-checkpoint evidence (notably
                        # documentation-only commits) for delivery resume.
                        preserve_worktree = True
                        return self._finalize(
                            status="blocked",
                            reason=str(
                                inner_result.get("blocked_reason")
                                or "blocker_escalation"
                            ),
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=inner_result.get("final_verify"),
                        )

                    if _is_task_progress_incomplete(inner_result.get("final_verify")):
                        # Canonical task evidence is a delivery-completeness
                        # blocker, not an implementation retry or a publication
                        # failure. Do not consume more outer iterations or try
                        # to checkpoint incidental verification artifacts.
                        preserve_worktree = True
                        return self._finalize(
                            status="blocked",
                            reason="task_progress_incomplete",
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=inner_result.get("final_verify"),
                        )

                    convergence_observation = self._record_convergence_observation(
                        inner_result["final_verify"],
                        worktree_path,
                        hard_ceiling=max_outer,
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
                            extra_state=self._publish_checkpoint_state(
                                worktree_path=worktree_path,
                                branch=e.branch,
                                stage=e.stage,
                                verify_result=inner_result.get("final_verify"),
                                error=e,
                            ),
                        )
                    pr_url = self._manage_pr(pr_url, branch, converged=False)

                    if convergence_observation.should_stop:
                        stop_reason = (
                            "convergence_stalled"
                            if convergence_observation.stop_reason == "stall_patience"
                            else "checkpoint_outer_cap"
                            if (
                                fulfillment_refresh_deferred
                                or (
                                    final_verify is not None
                                    and _is_only_fulfillment_gaps(final_verify)
                                    and self._last_checkpoint_has_task_progress()
                                )
                            )
                            else "outer_cap"
                        )
                        return self._finalize(
                            status="blocked",
                            reason=stop_reason,
                            outer_iterations=outer_iter + 1,
                            inner_iterations=total_inner_iterations,
                            pr_url=pr_url,
                            tokens_used=tokens_used,
                            final_verify=inner_result.get("final_verify"),
                        )

                finally:
                    if handle is not None:
                        try:
                            self._provider.destroy(handle)
                        except Exception as exc:
                            self._record_cleanup_warning("sandbox_destroy", exc)
                            logger.warning("Sandbox cleanup failed after build iteration: %s", exc)

            except BaseException:
                # An unexpected interruption may leave uncommitted evidence that
                # cannot be reconstructed from the mirror.
                preserve_worktree = True
                raise
            finally:
                # Checkpoint commits and run records are durable; keep a checkout
                # only while a downstream phase or recovery path needs it.
                if not preserve_worktree:
                    self._gitops.destroy_worktree(worktree_path, keep_branch=True)
                    current = self._state_store.read()
                    operation = current.get("delivery_slice_operation")
                    if isinstance(operation, dict) and operation.get("worktree_path") == worktree_path:
                        current.pop("delivery_slice_operation")
                        self._state_store.write(current)

            # Update state after each iteration
            state = self._state_store.read()
            state["outer_iter"] = outer_iter + 1
            state["tokens_used"] = tokens_used
            state["pr_url"] = pr_url
            self._state_store.write(state)
            outer_iter += 1

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
                outer_iterations=outer_iter,
                inner_iterations=total_inner_iterations,
                pr_url=pr_url,
                tokens_used=tokens_used,
                final_verify=final_verify,
            )

        # Outer cap reached
        return self._finalize(
            status="blocked",
            reason="outer_cap",
            outer_iterations=outer_iter,
            inner_iterations=total_inner_iterations,
            pr_url=pr_url,
            tokens_used=tokens_used,
            final_verify=final_verify,
        )

    # === Inner loop ===

    def _run_inner_loop(
        self,
        handle: Optional[SandboxHandle],
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
        if (
            _is_fulfillment_refresh_deferred(verify_result)
            or _is_fulfillment_freshness_failure(verify_result)
            or _is_task_progress_incomplete(verify_result)
        ):
            return {
                "converged": False,
                "blocked": False,
                "inner_count": 0,
                "tokens_used": tokens_used,
                "final_verify": verify_result,
            }
        if _is_user_runnability_sandbox_prerequisite(verify_result):
            return {
                "converged": False,
                "blocked": True,
                "blocked_reason": "user_runnability_sandbox_prerequisite",
                "inner_count": 0,
                "tokens_used": tokens_used,
                "final_verify": verify_result,
            }
        if _is_sandbox_browser_runtime_unavailable(verify_result):
            return {
                "converged": False,
                "blocked": True,
                "blocked_reason": "verification_infrastructure",
                "inner_count": 0,
                "tokens_used": tokens_used,
                "final_verify": verify_result,
            }

        failure_history: List[List[str]] = []
        current_verify = verify_result

        for inner_iter in range(1, max_inner + 1):
            if self._is_external_spec_artifact_failure(current_verify):
                self._print_external_spec_artifact_blocker(current_verify)
                return {
                    "converged": False,
                    "blocked": True,
                    "blocked_reason": "external_spec_artifact_missing",
                    "inner_count": inner_iter - 1,
                    "tokens_used": tokens_used,
                    "final_verify": current_verify,
                }

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
                    escalation_file = self._escalation.escalate(
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
                    state = self._state_store.read()
                    state["escalation_file"] = escalation_file
                    state["build_status"] = "blocked"
                    state["build_reason"] = "same_failure_repeat"
                    state.pop("provider_limit_message", None)
                    state.pop("provider_reset_hint", None)
                    self._state_store.write(state)
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
            gap_fingerprint_before = _concrete_fulfillment_gap_fingerprint(
                current_verify
            )
            product_fingerprint_before = _safe_product_evidence_fingerprint(
                worktree_path
            )
            feedback_prompt = self._make_feedback_prompt(
                build_prompt, current_verify, inner_iter
            )
            before_fix_state = self._state_store.read()
            self._controlled_slice_budget = (
                token_budget * 0.95 - tokens_used if token_budget and token_budget > 0 else None
            )
            fix_result = self._exec_feedback(
                handle, current_verify, build_command, strategy_context,
                worktree_path=worktree_path,
                prompt=feedback_prompt,
                repair_context={"base_prompt": build_prompt, "phase": "inner",
                                "inner_iteration": inner_iter, "evidence_paths": []},
            )
            tokens_used += _known_token_count(fix_result.get("tokens"))
            self._enforce_completed_task_ids(fix_result, worktree_path)
            fix_log_phase = "fix"
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
                state, outer_iter, inner_iter, fix_log_phase,
                fix_result.get("exit_code", 0),
                fix_result.get("passed", True),
                fix_result.get("duration_s", 0.0),
                fix_result.get("tokens"),
                provider_invocation=fix_result.get("provider_invocation"),
            )
            self._try_checkpoint_progress_commit(
                worktree_path=worktree_path,
                before_state=before_fix_state,
                after_state=self._state_store.read(),
                outer_iter=outer_iter,
                inner_iter=inner_iter,
                phase="fix",
                allow_without_task_progress=(
                    fix_result.get("completion_marker_explicit", False)
                    and fix_result.get("passed", True)
                    and fix_result.get("build_status") == "done"
                ),
            )

            if fix_result.get("build_status") == "blocked":
                if _is_verification_environment_deferral(fix_result):
                    try:
                        deferred_commit = (
                            self._checkpoint_verification_deferred_candidate(
                                worktree_path,
                                outer_iter=outer_iter,
                                inner_iter=inner_iter,
                                phase="fix",
                            )
                        )
                        self._record_verification_environment_deferral(
                            fix_result,
                            commit=deferred_commit,
                            outer_iter=outer_iter,
                            inner_iter=inner_iter,
                            phase="fix",
                        )
                    except Exception as exc:
                        return {
                            "converged": False,
                            "blocked": True,
                            "blocked_reason": "verification_evidence_invalid",
                            "inner_count": inner_iter,
                            "tokens_used": tokens_used,
                            "final_verify": VerifyResult(
                                passed=False,
                                failures=[
                                    FailureEntry(
                                        FailureCategory.OTHER,
                                        "verification-evidence-invalid",
                                        "could not checkpoint verification-deferred "
                                        f"candidate: {exc}",
                                    )
                                ],
                            ),
                        }
                else:
                    blocker = str(
                        fix_result.get("build_reason")
                        or "build agent reported a blocker"
                    )
                    return {
                        "converged": False,
                        "blocked": True,
                        "blocked_reason": "build_blocked",
                        "inner_count": inner_iter,
                        "tokens_used": tokens_used,
                        "final_verify": VerifyResult(
                            passed=False,
                            failures=[
                                FailureEntry(
                                    FailureCategory.OTHER,
                                    "build-blocked",
                                    blocker,
                                )
                            ],
                        ),
                    }

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
            current_verify = self._apply_verification_diagnosis(
                current_verify, worktree_path
            )
            inner_changed_files = self._changed_files_since_head(worktree_path)
            self._controlled_slice_budget = (
                max(0, token_budget * 0.95 - tokens_used - current_verify.token_usage)
                if token_budget and token_budget > 0 else None)
            current_verify = self._apply_post_verify_gates(
                current_verify,
                worktree_path,
                completed_task_ids=scoped_completed_task_ids,
                changed_files=inner_changed_files,
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
            self._record_provider_attempt_summary(
                phase="fix",
                attempt=inner_iter,
                result=fix_result,
                verify_result=current_verify,
                changed_files=inner_changed_files,
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

            if _is_user_runnability_sandbox_prerequisite(current_verify):
                return {
                    "converged": False,
                    "blocked": True,
                    "blocked_reason": "user_runnability_sandbox_prerequisite",
                    "inner_count": inner_iter,
                    "tokens_used": tokens_used,
                    "final_verify": current_verify,
                }

            gap_fingerprint_after = _concrete_fulfillment_gap_fingerprint(
                current_verify
            )
            product_fingerprint_after = _safe_product_evidence_fingerprint(
                worktree_path
            )
            if (
                not applied_task_ids
                and gap_fingerprint_before
                and gap_fingerprint_after == gap_fingerprint_before
                and product_fingerprint_before is not None
                and product_fingerprint_after == product_fingerprint_before
            ):
                escalation_file = self._escalation.escalate(
                    spec_id=self._spec_id,
                    strategy_id=self._strategy_id,
                    category="no_progress",
                    context=(
                        "## Fulfillment Repair Made No Progress\n\n"
                        "COMMANDER completed one repair attempt, but the normalized "
                        "fulfillment gap set and bounded product/evidence fingerprint "
                        "were unchanged. Ralph stopped before spending another repair "
                        "iteration on the same evidence state."
                    ),
                    last_verify_result=_verify_to_dict(current_verify),
                )
                fresh_state = self._state_store.read()
                fresh_state["escalation_file"] = escalation_file
                fresh_state["build_status"] = "blocked"
                fresh_state["build_reason"] = "fulfillment_no_progress"
                self._state_store.write(fresh_state)
                return {
                    "converged": False,
                    "blocked": True,
                    "blocked_reason": "fulfillment_no_progress",
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
            if _is_fulfillment_refresh_deferred(
                current_verify
            ) or _is_fulfillment_freshness_failure(current_verify):
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

    def _exec_controlled_slice(
        self, worktree_path: str, prompt: str, *, repair: bool,
        documentation: bool = False,
    ) -> Dict[str, Any]:
        """Adapt the delivery controller to Ralph's existing result boundary."""
        from harness.delivery_slice_runner import DeliverySliceRunner
        from harness.delivery_slice_runner import _digest, _spec_inputs
        from harness.delivery_slice import DeliverySliceError
        from harness.delivery_documentation import DeliveryDocumentationRunner

        try:
            worktree = Path(worktree_path)
            spec_dir = self._find_existing_spec_dir(worktree)
            if spec_dir is None:
                raise DeliverySliceError("controlled delivery requires a canonical spec directory")
            state = self._state_store.read()
            raw_scope = state.get("target_task_ids", [])
            if (state.get("implementation_target") or state.get("declared_targets")
                    or state.get("target_repo") or state.get("target_path") or raw_scope):
                if not isinstance(raw_scope, list) or any(not isinstance(item, str) for item in raw_scope):
                    raise DeliverySliceError("invalid persisted delivery task scope")
                scope = set(raw_scope)
            else:
                scope = self._target_task_ids()
            repair_task_id = state.get("delivery_slice_task_id") if repair else None
            operation = state.get("delivery_slice_operation")
            requested_kind = "documentation" if documentation else "task"
            source = self._source_phase_a_spec_dir(worktree)
            source_binding = None
            if source is not None and source.resolve() != spec_dir.resolve():
                source_binding = _digest(_spec_inputs(source, self._orchestration_root(worktree)))
            if isinstance(operation, dict):
                kind = operation.get("kind", "task")
                if kind not in {"task", "documentation"}:
                    raise DeliverySliceError("invalid pending delivery operation kind")
                if (operation.get("worktree_path") != str(worktree.resolve())
                        or operation.get("source_binding") != source_binding):
                    raise DeliverySliceError("delivery_reconciliation_required: pending worktree or published source changed")
                if operation.get("progress_applied") is True:
                    if repair and kind == requested_kind == "documentation":
                        raise DeliverySliceError("delivery_reconciliation_required: accepted documentation received new failure evidence")
                    if repair or state.get("outer_iter", 0) > operation.get("outer_iter", 0):
                        operation = None  # Advance only an applied operation.
                elif repair and kind != requested_kind:
                    raise DeliverySliceError("delivery_reconciliation_required: unresolved delivery operation has a different kind")
                elif repair and kind == "documentation" and operation.get("feedback") != prompt:
                    raise DeliverySliceError("delivery_reconciliation_required: documentation failure evidence changed")
            resuming = operation is not None
            if resuming:
                if (not isinstance(operation, dict) or not isinstance(operation.get("id"), str)
                        or not operation["id"] or not isinstance(operation.get("feedback"), str)
                        or type(operation.get("accounted_tokens")) is not int
                        or operation["accounted_tokens"] < 0):
                    raise DeliverySliceError("invalid pending delivery operation")
                repair_task_id = operation.get("repair_task_id")
                prompt = operation["feedback"]
                documentation = operation.get("kind", "task") == "documentation"
                if repair_task_id is not None and not documentation:
                    # Old snapshots are immutable evidence. Never reinterpret a
                    # saved legacy completion recipe as a new role assignment.
                    try:
                        saved_feedback = json.loads(prompt)
                    except (ValueError, RecursionError):
                        saved_feedback = None
                    if (not isinstance(saved_feedback, dict)
                            or saved_feedback.get("feedback_kind") != "controlled_source_repair_v1"):
                        raise DeliverySliceError(
                            "delivery_reconciliation_required: legacy source repair feedback"
                        )
            elif repair and not documentation and (not isinstance(repair_task_id, str) or not repair_task_id):
                raise DeliverySliceError("feedback requires a previously accepted delivery slice task")
            else:
                operation = {"id": uuid4().hex, "feedback": prompt,
                             "repair_task_id": repair_task_id, "accounted_tokens": 0,
                             "worktree_path": str(worktree.resolve()), "source_binding": source_binding,
                             "outer_iter": state.get("outer_iter", 0), "progress_applied": False}
                if documentation:
                    operation["kind"] = "documentation"
                    operation["repair_task_id"] = None
                    operation["changed_files"] = self._documentation_delivery_changes(worktree)

            def remember_operation():
                current = self._state_store.read()
                current["delivery_slice_operation"] = operation
                self._state_store.write(current)

            self._prepare_delivery_context(worktree_path)
            runner = DeliveryDocumentationRunner if documentation else DeliverySliceRunner
            runner_options = {}
            if documentation:
                # The writer changes README/CHANGELOG itself. Replay the input
                # inventory while the runner checks actual candidate/source bytes.
                if "changed_files" not in operation or (
                    operation["changed_files"] is not None and (
                        not isinstance(operation["changed_files"], list)
                        or any(not isinstance(path, str) for path in operation["changed_files"])
                    )
                ):
                    raise DeliverySliceError("invalid pending documentation change inventory")
                runnability_ref, runnability_required = self._controlled_documentation_runnability(worktree)
                runner_options = {
                    "changed_files": operation["changed_files"],
                    "runnability_report": runnability_ref,
                    "runnability_required": runnability_required,
                    "runnability_checkpoint": (
                        lambda: self._refresh_documentation_runnability(worktree)
                    ) if runnability_ref is not None else None,
                }
            else:
                runner_options["repair_task_id"] = repair_task_id
            result = runner(
                self._llm_provider, self._orchestration_root(worktree),
            ).run(
                worktree=worktree, spec_dir=spec_dir,
                evidence_root=self._delivery_operation_evidence_root(),
                allowed_task_ids=scope, **runner_options,
                feedback=prompt, stop_requested=lambda: self._interrupted or self.check_cancel(),
                containment_policy_file=str(self._state_store.state_dir / "delivery-containment-policy.json"),
                token_budget=(self._controlled_slice_budget + operation["accounted_tokens"]
                              if self._controlled_slice_budget is not None else None),
                operation_id=operation["id"], journal_required=resuming,
                on_journal_ready=remember_operation,
            )
            current = self._state_store.read()
            new_tokens = None
            if result.token_usage is not None:
                new_tokens = max(0, result.token_usage - operation["accounted_tokens"])
                operation["accounted_tokens"] = max(operation["accounted_tokens"], result.token_usage)
                current["tokens_used"] = current.get("tokens_used", 0) + new_tokens
            if current.get("delivery_slice_operation", {}).get("id") == operation["id"]:
                current["delivery_slice_operation"] = operation
            if result.succeeded and documentation:
                # The runner publishes both exact reports after durable review
                # receipts. No canonical task progress belongs to this operation.
                operation["progress_applied"] = True
                operation["runnability_reviewed"] = result.provider_invocation.get("runnability_reviewed") is True
            elif result.succeeded and result.task_ids:
                current["delivery_slice_task_id"] = result.task_ids[0]
                operation["accepted_task_id"] = result.task_ids[0]
            elif result.succeeded and not resuming:
                # Completed-scope handoff has no new dispatch journal. Retire
                # only the prior operation already eligible for advancement;
                # preserve its receipts and last task for explicit repairs.
                current.pop("delivery_slice_operation", None)
            self._state_store.write(current)
            adapted = {
                "exit_code": result.exit_code, "passed": result.succeeded,
                "build_status": result.status, "completion_marker_explicit": True,
                "build_reason": result.reason, "blocker_kind": result.blocker_kind,
                "duration_s": result.duration_ms / 1000, "tokens": new_tokens,
                "provider_invocation": result.provider_invocation,
                "impasse": False, "impasse_file": None, "task_ids": result.task_ids or [],
                "stdout": result.stdout, "stderr": result.stderr,
            }
            if documentation and result.succeeded:
                adapted = _DocumentationBuildResult(adapted, documentation_operation_id=operation["id"])
            return adapted
        except (DeliverySliceError, OSError) as exc:
            return {"exit_code": 1, "passed": False, "build_status": "blocked",
                    "completion_marker_explicit": True, "build_reason": str(exc),
                    "duration_s": 0, "tokens": 0, "task_ids": [], "stdout": "", "stderr": ""}

    def _exec_build(
        self,
        handle: Optional[SandboxHandle],
        build_command: str,
        strategy_context: str,
        worktree_path: str = "",
        prompt: str = "",
    ) -> Dict[str, Any]:
        """Execute one controller-selected delivery slice."""
        del handle, build_command, strategy_context
        return self._exec_controlled_slice(worktree_path, prompt, repair=False)

    def _exec_verify(self, handle: SandboxHandle | None, worktree_path: str = "") -> VerifyResult:
        """Execute verification.

        Verification runs in a managed sandbox by default.  Host execution is an
        explicit compatibility fallback only; the LLM build process itself may
        still run on the host.

        Returns parsed VerifyResult.
        """
        if self._llm_provider is not None and worktree_path and self._config.verification.execution == "host":
            return self._exec_verify_locally(worktree_path)
        return self._candidate_evidence_runner.run_standard(
            handle=handle,
            worktree=Path(worktree_path),
            allow_legacy_structured=False,
        )

    def _apply_fulfillment_gate(
        self,
        verify_result: VerifyResult,
        worktree_path: str,
    ) -> VerifyResult:
        """Treat unresolved fulfillment gaps as verification failures."""
        if not verify_result.passed or not worktree_path:
            return verify_result

        spec_dir = self._find_existing_spec_dir(worktree_path)
        if spec_dir is None:
            return verify_result

        report = latest_fulfillment_report(spec_dir)
        if report is None:
            return verify_result

        metadata = read_fulfillment_metadata(report)
        target_scoped_delivery = self._target_task_ids() is not None
        if metadata.get("verify_scope") == "scoped" and not target_scoped_delivery:
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
                verification_evidence=dict(verify_result.verification_evidence),
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
                verification_evidence=dict(verify_result.verification_evidence),
            )

        deferred_scope_issues = validate_deferred_scope_rows(report, spec_dir)
        if deferred_scope_issues:
            failure = FailureEntry(
                category=FailureCategory.OTHER,
                id="fulfillment-deferred-scope-invalid",
                error="; ".join(deferred_scope_issues),
            )
            return VerifyResult(
                passed=False,
                failures=[failure],
                duration_s=verify_result.duration_s,
                token_usage=verify_result.token_usage,
                verification_evidence=dict(verify_result.verification_evidence),
            )

        if not fulfillment_has_blocking_gaps(report, strict=True):
            return verify_result

        statuses = ", ".join(sorted(blocking_statuses(strict=True)))
        gaps = blocking_fulfillment_gaps(
            report,
            strict=True,
            gaps_path=spec_dir / "fulfillment-gaps.md",
        )
        normalized_gaps = [
            {
                "requirement_id": gap.requirement_id,
                "status": gap.status,
                "summary": gap.summary,
                "recommended_action": gap.recommended_action
                or (
                    f"Run `echelon spec reopen {self._spec_id}` or implement and "
                    f"verify {gap.requirement_id}."
                ),
            }
            for gap in gaps
        ]
        concrete_lines = "\n".join(
            "- {requirement_id} [{status}]: {summary} Recommended action: "
            "{recommended_action}".format(**gap)
            for gap in normalized_gaps
        )
        failure = FailureEntry(
            category=FailureCategory.OTHER,
            id="fulfillment-gaps",
            error=(
                f"fulfillment report has unresolved statuses ({statuses}): {report}."
                + (
                    f"\nConcrete unresolved requirements:\n{concrete_lines}"
                    if concrete_lines
                    else ""
                )
                + "\n"
                f"Run `echelon spec reopen {self._spec_id}` or continue the delivery loop "
                "with fulfillment-gaps.md as mandatory implementation context."
            ),
            details={"gaps": normalized_gaps},
        )
        return VerifyResult(
            passed=False,
            failures=[failure],
            duration_s=verify_result.duration_s,
            token_usage=verify_result.token_usage,
            verification_evidence=dict(verify_result.verification_evidence),
        )

    def _apply_post_verify_gates(
        self,
        verify_result: VerifyResult,
        worktree_path: str,
        *,
        completed_task_ids: Optional[List[str]] = None,
        changed_files: Optional[List[str]] = None,
    ) -> VerifyResult:
        """Apply candidate gates in evidence-production order.

        User runnability executes before fulfillment refresh because its
        harness-owned composition evidence is an input to requirement judgment,
        not a consequence of that judgment.
        """
        verify_result = self._apply_task_progress_gate(
            verify_result, worktree_path, require_completion=False
        )
        verify_result = self._apply_user_runnability_gate(
            verify_result,
            worktree_path,
            candidate_commit=_current_git_commit(Path(worktree_path)) or "",
            evidence_dir=self._runnability_evidence_dir(),
        )
        verify_result = self._apply_coverage_observation_gate(
            verify_result,
            worktree_path,
        )
        verify_result = self._refresh_fulfillment_report(
            verify_result,
            worktree_path,
            completed_task_ids=completed_task_ids,
            changed_files=changed_files,
        )
        verify_result = self._apply_fulfillment_gate(verify_result, worktree_path)
        verify_result = self._apply_documentation_gate(
            verify_result,
            worktree_path,
            changed_files=changed_files,
        )
        return self._apply_task_progress_gate(
            verify_result, worktree_path, require_completion=True
        )

    def _apply_verification_diagnosis(
        self,
        verify_result: VerifyResult,
        worktree_path: str,
    ) -> VerifyResult:
        """Attach one DEBUGGER receipt to the timeout/cleanup-error signature.

        A diagnostic is not authority to block or pass a candidate.  The
        deterministic signature already proves that verification failed; after
        its one fresh-sandbox retry, the safe delivery action is to give the
        ordinary repair loop a test failure plus the retained explanation.
        """
        if not verification_diagnosis_required(verify_result):
            return verify_result

        if self._llm_provider is None:
            diagnosis_note = "DEBUGGER diagnosis unavailable: no coding provider configured."
            report_path = ""
        else:
            diagnosis = run_verification_diagnostic(
                worktree=Path(worktree_path),
                evidence_root=self._state_store.state_dir.parent / "evidence",
                result=verify_result,
                executor=self._llm_provider,
            )
            report_path = str(diagnosis.report_path or "")
            diagnosis_note = (
                f"DEBUGGER diagnosis ({diagnosis.status}; owner={diagnosis.owner}; "
                f"disposition={diagnosis.disposition}): {diagnosis.reason or 'no conclusion'}"
            )
            if diagnosis.recommended_action:
                diagnosis_note += f" Recommended action: {diagnosis.recommended_action}"

        routed_failures: list[FailureEntry] = []
        for failure in verify_result.failures:
            if failure.id != "browser-verification-diagnosis-required":
                routed_failures.append(failure)
                continue
            details = dict(failure.details)
            details.update({
                "original_failure_id": failure.id,
                "diagnostic_report": report_path,
                "diagnostic": diagnosis_note,
            })
            routed_failures.append(
                FailureEntry(
                    category=FailureCategory.TEST,
                    id="playwright-test-timeout",
                    error=(
                        f"{failure.error}\n\n{diagnosis_note}"
                        + (f"\nDiagnostic receipt: {report_path}" if report_path else "")
                    ),
                    details=details,
                )
            )
        evidence = dict(verify_result.verification_evidence)
        evidence["verification_diagnostic"] = {
            "required": True,
            "report_path": report_path,
        }
        return VerifyResult(
            passed=False,
            failures=routed_failures,
            duration_s=verify_result.duration_s,
            token_usage=verify_result.token_usage,
            verification_evidence=evidence,
        )

    def _apply_coverage_observation_gate(
        self,
        verify_result: VerifyResult,
        worktree_path: str,
    ) -> VerifyResult:
        """Attach fail-closed per-case execution evidence for required stacks.

        This deliberately runs after the candidate-owned runnability journey:
        its contract hash is part of the immutable coverage-observation tuple.
        It runs before fulfillment refresh, where later phases consume the
        recorded observation rather than a green aggregate verifier.
        """
        spec_dir = self._find_existing_spec_dir(worktree_path)
        required_case_ids = _completed_task_coverage_case_ids(
            spec_dir / "tasks.md" if spec_dir is not None else None
        )
        gate = self._candidate_evidence_runner.apply_coverage(
            verify_result=verify_result,
            worktree=Path(worktree_path),
            spec_dir=spec_dir,
            evidence_dir=self._coverage_observer_evidence_dir(),
            required_case_ids=required_case_ids,
        )
        if gate.state_summary is not None:
            self._record_coverage_observation_summary(gate.state_summary)
        return gate.verify_result


    @staticmethod
    def _verification_receipt_from_result(
        verify_result: VerifyResult,
    ) -> VerificationEvidenceRef | None:
        try:
            return VerificationEvidenceRef.from_mapping(
                verify_result.verification_evidence
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _runnability_contract_hash(verify_result: VerifyResult) -> str | None:
        raw = verify_result.verification_evidence.get("runnability_evidence")
        if not isinstance(raw, Mapping):
            return None
        value = raw.get("contract_hash")
        return str(value) if isinstance(value, str) and value else None

    def _coverage_observation_for_fulfillment(
        self,
        verify_result: VerifyResult,
        worktree_path: str,
    ) -> tuple[CoverageObservationResult | None, bool, str]:
        """Return the current strict observation for fulfillment, or a reason.

        The observation is a Ralph-owned immutable artifact. Fulfillment must
        not discover a path from provider-authored output or reuse it after the
        product, coverage map, selected stacks, observer plan, or required
        runnability contract changes.
        """
        resolved = getattr(self._config, "resolved_stacks", None)
        observers = tuple(
            item
            for item in getattr(resolved, "coverage_observers", ())
            if item.observer.required
        )
        if not observers:
            return None, False, ""

        try:
            spec_dir = self._find_existing_spec_dir(worktree_path)
            if spec_dir is None:
                raise CoverageObservationError("active spec directory is unavailable")
            coverage_map = spec_dir / "coverage-map.md"
            canonical_ids = {
                item.id for item in extract_canonical_requirements(spec_dir)
            }
            obligations = tuple(
                obligation
                for row in parse_coverage_map_obligations(coverage_map, canonical_ids)
                for obligation in row
            )
            owner_deferred_ids = {
                item_id
                for entry in active_entries(spec_dir)
                for item_id in entry.selected_ids
                if not item_id.startswith("T-")
            }
            unmapped_requirement_ids = active_unmapped_coverage_requirement_ids(
                canonical_ids=canonical_ids,
                obligations=obligations,
                deferred_ids=owner_deferred_ids,
            )
            if unmapped_requirement_ids:
                return (
                    None,
                    True,
                    "coverage map has no planned test obligation for active requirement(s): "
                    + ", ".join(unmapped_requirement_ids[:20]),
                )
            if not any(
                obligation.requirement_id not in owner_deferred_ids
                for obligation in obligations
            ):
                return None, False, ""
            coverage_map_hash = hashlib.sha256(coverage_map.read_bytes()).hexdigest()
        except (CoverageObservationError, OSError, ValueError) as exc:
            return None, True, f"coverage observation inputs are invalid: {exc}"

        raw_ref = verify_result.verification_evidence.get("coverage_observation")
        if not isinstance(raw_ref, Mapping):
            return (
                None,
                True,
                "selected stack requires a coverage observation, but Ralph did "
                "not attach one to the passed verification evidence",
            )
        try:
            declared = CoverageObservationRef.from_mapping(raw_ref)
            loaded = load_coverage_observation(declared.path)
            if loaded.ref != declared:
                raise CoverageObservationError(
                    "coverage observation reference does not match its immutable artifact"
                )
            candidate_fingerprint = _safe_product_evidence_fingerprint(worktree_path)
            if not candidate_fingerprint:
                raise CoverageObservationError(
                    "candidate product fingerprint is unavailable"
                )
            candidate_commit = _current_git_commit(Path(worktree_path))
            if not candidate_commit:
                raise CoverageObservationError("candidate commit is unavailable")
            runnability_contract_hash = self._runnability_contract_hash(verify_result)
            if (
                str(getattr(resolved.runnability, "policy", "not_applicable"))
                == "required"
                and runnability_contract_hash is None
            ):
                raise CoverageObservationError(
                    "required runnability contract evidence is missing"
                )
            validation = validate_coverage_observation(
                loaded.ref,
                candidate_commit=candidate_commit,
                candidate_fingerprint=candidate_fingerprint,
                coverage_map_hash=coverage_map_hash,
                resolved_stack_hash=resolved_stack_contract_sha256(resolved),
                observer_plan_hash=resolved_coverage_observer_plan_sha256(resolved),
                runnability_contract_hash=runnability_contract_hash,
            )
            if not validation.valid:
                raise CoverageObservationError(validation.reason)
        except (CoverageObservationError, OSError, ValueError) as exc:
            return None, True, f"coverage observation is invalid: {exc}"
        return loaded, True, ""

    def _coverage_observer_evidence_dir(self) -> Path:
        return (
            self._state_store.state_dir.parent
            / "evidence"
            / self._strategy_id
        )

    @staticmethod
    def _next_coverage_observation_attempt(evidence_dir: Path) -> int:
        root = Path(evidence_dir) / "coverage-observation"
        highest = 0
        for path in root.glob("attempt-*.json") if root.exists() else ():
            match = re.match(r"attempt-(\d+)-", path.name)
            if match is not None:
                highest = max(highest, int(match.group(1)))
        return highest + 1

    def _record_coverage_observation_state(
        self,
        observation: object,
        observer_evidence: Mapping[str, object],
    ) -> None:
        ref = getattr(observation, "ref", None)
        requirements = getattr(observation, "requirements", {})
        raw_fingerprints = getattr(observation, "fingerprints", {})
        fingerprints = {
            key: str(raw_fingerprints.get(key) or "")
            for key in (
                "coverage_map_hash",
                "resolved_stack_hash",
                "observer_plan_hash",
                "runnability_contract_hash",
            )
            if isinstance(raw_fingerprints, Mapping) and raw_fingerprints.get(key)
        }
        if isinstance(ref, CoverageObservationRef) and ref.candidate_fingerprint:
            fingerprints["candidate_fingerprint"] = ref.candidate_fingerprint
        state = self._state_store.read()
        state["coverage_observation"] = {
            "status": "passed" if getattr(ref, "passed", False) else "failed",
            "path": str(getattr(ref, "path", "")),
            "ref": ref.as_mapping() if isinstance(ref, CoverageObservationRef) else None,
            "requirements_observed": sum(
                item.status == "observed" for item in requirements.values()
            ) if isinstance(requirements, Mapping) else 0,
            "requirements_total": len(requirements) if isinstance(requirements, Mapping) else 0,
            "observers": dict(observer_evidence),
            "fingerprints": fingerprints,
        }
        self._state_store.write(state)

    def _record_coverage_observation_summary(
        self, summary: Mapping[str, object]
    ) -> None:
        state = self._state_store.read()
        state["coverage_observation"] = dict(summary)
        self._state_store.write(state)

    def _coverage_observation_failure(
        self,
        verify_result: VerifyResult,
        *,
        failure_id: str,
        error: str,
        observer_evidence: Mapping[str, object] | None = None,
    ) -> VerifyResult:
        evidence = dict(verify_result.verification_evidence)
        if observer_evidence is not None:
            evidence["coverage_observers"] = dict(observer_evidence)
        return VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id=failure_id,
                    error=error,
                )
            ],
            duration_s=verify_result.duration_s,
            token_usage=verify_result.token_usage,
            verification_evidence=evidence,
        )

    def _apply_user_runnability_gate(
        self,
        verify_result: VerifyResult,
        worktree_path: str,
        *,
        candidate_commit: str,
        evidence_dir: Path,
    ) -> VerifyResult:
        """Require a fresh composed journey when resolved stacks demand it."""
        operation = self._state_store.read().get("delivery_slice_operation")
        if (verify_result.passed and isinstance(operation, dict)
                and operation.get("kind") == "documentation"
                and operation.get("progress_applied") is True and operation.get("runnability_reviewed") is True):
            from harness.delivery_documentation import reviewed_runnability_checkpoint
            try:
                if operation.get("worktree_path") != str(Path(worktree_path).resolve()):
                    raise ValueError("reviewed documentation worktree changed")
                ref = reviewed_runnability_checkpoint(
                    worktree=Path(worktree_path), spec_dir=self._find_existing_spec_dir(worktree_path),
                    evidence_root=self._delivery_operation_evidence_root(), operation_id=operation["id"],
                )
                current, _ = self._controlled_documentation_runnability(Path(worktree_path), validate_candidate=True)
                if current != ref:
                    raise ValueError("reviewed runnability receipt is not the current controller receipt")
            except (ValueError, OSError, RuntimeError, TypeError) as exc:
                return self._runnability_failure(verify_result, failure_id="docs-runnability-evidence-stale",
                                                error=str(exc), details={})
            evidence = {**verify_result.verification_evidence, "runnability_evidence": ref.as_mapping()}
            return VerifyResult(passed=True, failures=list(verify_result.failures), duration_s=verify_result.duration_s,
                                token_usage=verify_result.token_usage, verification_evidence=evidence)
        gate = self._candidate_evidence_runner.apply_runnability(
            verify_result=verify_result,
            worktree=Path(worktree_path),
            spec_dir=self._find_existing_spec_dir(worktree_path),
            candidate_commit=candidate_commit,
            evidence_dir=evidence_dir,
        )
        if gate.state_summary is not None:
            self._record_user_runnability_state(gate.state_summary)
        return gate.verify_result


    def _runnability_failure(
        self,
        verify_result: VerifyResult,
        *,
        failure_id: str,
        error: str,
        details: dict[str, object],
    ) -> VerifyResult:
        return VerifyResult(
            passed=False,
            failures=[
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id=failure_id,
                    error=error,
                    details=details,
                )
            ],
            duration_s=verify_result.duration_s,
            token_usage=verify_result.token_usage,
            verification_evidence=dict(verify_result.verification_evidence),
        )

    def _runnability_evidence_dir(self) -> Path:
        return self._state_store.state_dir.parent / "evidence" / "user-runnability"

    def _record_user_runnability_result(self, result: RunnabilityRunResult) -> None:
        summary: dict[str, object] = {
            "status": result.status,
            "failed_stage": result.failed_stage,
            "failure_class": result.failure_class,
            "summary": result.summary,
            "report": str(result.evidence.markdown_path),
            "candidate_fingerprint": result.candidate_fingerprint,
            "contract_hash": result.contract_hash,
            "stack_hash": result.stack_hash,
            "user_commands": {
                key: list(commands)
                for key, commands in result.user_commands.items()
            },
        }
        if (
            result.local_journey_status != "not_required"
            or result.local_user_commands
        ):
            local_journey: dict[str, object] = {
                "status": result.local_journey_status,
                "reason": result.local_journey_reason,
                "commands": {
                    key: list(commands)
                    for key, commands in result.local_user_commands.items()
                },
            }
            if result.local_boundary_probes:
                local_journey["boundary_probes"] = [
                    {
                        "id": probe.id,
                        "service": probe.service,
                        "command": probe.command,
                    }
                    for probe in result.local_boundary_probes
                ]
            summary["local_journey"] = local_journey
        self._record_user_runnability_state(summary)

    def _record_user_runnability_state(self, summary: dict[str, object]) -> None:
        state = self._state_store.read()
        state["user_runnability"] = summary
        self._state_store.write(state)

    def _apply_documentation_gate(
        self,
        verify_result: VerifyResult,
        worktree_path: str,
        changed_files: Optional[List[str]] = None,
    ) -> VerifyResult:
        """Treat stale or missing README/CHANGELOG decisions as verification failures."""
        if not verify_result.passed or not worktree_path:
            return verify_result

        spec_dir = self._find_spec_dir(worktree_path)
        if spec_dir is None:
            return verify_result

        documentation_changes = self._documentation_delivery_changes(
            Path(worktree_path)
        )
        if documentation_changes is None:
            documentation_changes = changed_files
        self._record_documentation_evidence(
            Path(worktree_path),
            documentation_changes,
        )

        from harness.delivery_slice import DeliverySliceError
        try:
            runnability_ref, runnability_required = (
                self._controlled_documentation_runnability(
                    Path(worktree_path), validate_candidate=True
                )
            )
        except (DeliverySliceError, OSError) as exc:
            return self._runnability_failure(
                verify_result,
                failure_id="docs-runnability-evidence-stale",
                error=str(exc),
                details={},
            )

        gate = evaluate_documentation_gate(
            Path(worktree_path),
            spec_dir,
            changed_files=documentation_changes,
            runnability_report=runnability_ref,
            runnability_required=runnability_required,
            require_independent_review=True,
        )
        if gate.passed:
            return verify_result

        assert gate.failure is not None
        return VerifyResult(
            passed=False,
            failures=[gate.failure],
            duration_s=verify_result.duration_s,
            token_usage=verify_result.token_usage,
            verification_evidence=dict(verify_result.verification_evidence),
        )

    def _controlled_documentation_runnability(
        self, worktree: Path, *, validate_candidate: bool = False,
    ) -> tuple[RunnabilityEvidenceRef | None, bool]:
        """Bind documentation to the current resolved stack and actual receipt."""
        from harness.delivery_slice import DeliverySliceError

        policy = getattr(self._config, "resolved_runnability", None)
        required = str(getattr(policy, "policy", "not_applicable")) == "required"
        raw = self._state_store.read().get("user_runnability")
        if not isinstance(raw, dict) or raw.get("status") != "runnable":
            return None, required
        try:
            ref = load_runnability_evidence_ref(str(raw.get("report") or ""))
            resolved = self._config.resolved_stacks
            stack_hash = resolved_stack_contract_sha256(resolved) if resolved is not None else ""
            contract = load_runnability_contract(worktree)
            validation = validate_runnability_report(
                ref, candidate_commit=_current_git_commit(worktree) or "",
                # The documentation runner validates the initial product and
                # guards byte changes on replay. Its own document/report edits
                # must not invalidate the captured runnability receipt here.
                candidate_fingerprint=(runnability_product_fingerprint(worktree, self._find_existing_spec_dir(worktree))
                                       if validate_candidate else ref.candidate_fingerprint),
                contract_hash=runnability_contract_sha256(contract) if contract else "",
                stack_hash=stack_hash,
            )
            if not validation.valid:
                raise ValueError(validation.reason)
        except (ValueError, RunnabilityContractError) as exc:
            raise DeliverySliceError(f"documentation_runnability_evidence_invalid: {exc}") from exc
        return ref, True

    def _delivery_operation_evidence_root(self) -> Path:
        state = self._state_store.read()
        return self._state_store.state_dir / "delivery-slices" / hashlib.sha256(
            f"{self._strategy_id}:{state.get('run_id', '')}".encode()).hexdigest()

    def _refresh_documentation_runnability(self, worktree: Path) -> RunnabilityEvidenceRef:
        """Execute the existing runnability owner at the journaled author checkpoint."""
        from harness.delivery_slice import DeliverySliceError
        gate = self._candidate_evidence_runner.apply_runnability(
            verify_result=VerifyResult(True), worktree=worktree,
            spec_dir=self._find_existing_spec_dir(worktree),
            candidate_commit=_current_git_commit(worktree) or "", evidence_dir=self._runnability_evidence_dir(),
        )
        if gate.state_summary is not None:
            self._record_user_runnability_state(gate.state_summary)
        if not gate.verify_result.passed:
            raise DeliverySliceError("documentation_runnability_refresh_failed: " + "; ".join(
                f"{failure.id}: {failure.error}" for failure in gate.verify_result.failures))
        ref, _ = self._controlled_documentation_runnability(worktree, validate_candidate=True)
        if ref is None:
            raise DeliverySliceError("documentation_runnability_refresh_missing")
        return ref

    def _documentation_delivery_changes(
        self,
        worktree_path: Path,
    ) -> Optional[List[str]]:
        """Return committed and dirty paths in the cumulative delivery slice."""
        committed = self._cumulative_target_delivery_changes(worktree_path)
        if committed is None:
            return None
        dirty = self._changed_files_since_head(str(worktree_path))
        return sorted(set(committed) | set(dirty))

    def _record_documentation_evidence(
        self,
        worktree_path: Path,
        changed_files: Optional[List[str]],
    ) -> None:
        """Persist the reachable head used for documentation verification."""
        head = _current_git_commit(worktree_path)
        if head is None:
            return
        default_branch = str(
            getattr(self._config, "target_default_branch", "") or "main"
        )
        baseline: Optional[str] = None
        for ref in (
            f"upstream/{default_branch}",
            f"origin/{default_branch}",
            default_branch,
        ):
            baseline = _git_merge_base(worktree_path, "HEAD", ref)
            if baseline is not None:
                break
        if baseline is None:
            baseline = _git_first_commit(worktree_path)
        state = self._state_store.read()
        state["documentation_evidence"] = {
            "baseline": baseline,
            "head": head,
            "changed_files": sorted(set(changed_files or [])),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self._state_store.write(state)


    def _cumulative_target_delivery_changes(self, worktree_path: Path) -> Optional[List[str]]:
        """Return target changes on this branch relative to the default branch."""
        if not worktree_path.is_dir():
            return None
        default_branch = str(getattr(self._config, "target_default_branch", "") or "main")
        for ref in (
            f"upstream/{default_branch}",
            f"origin/{default_branch}",
            default_branch,
        ):
            base = _git_merge_base(worktree_path, "HEAD", ref)
            if base is None:
                continue
            changed = _git_changed_files_between(worktree_path, base, "HEAD")
            if changed is None:
                continue
            return [
                path
                for path in changed
                if not _is_harness_or_spec_artifact(path)
            ]
        first_commit = _git_first_commit(worktree_path)
        if first_commit is None:
            return None
        changed = _git_changed_files_between(worktree_path, first_commit, "HEAD")
        if changed is None:
            return None
        return [
            path
            for path in changed
            if not _is_harness_or_spec_artifact(path)
        ]

    def _is_external_spec_artifact_failure(self, verify_result: VerifyResult) -> bool:
        """Return True when a verifier failure points at Ralph-owned spec artifacts."""
        if verify_result.passed or self._spec_artifacts_mode() != "external":
            return False
        return any(
            failure.id in _EXTERNAL_SPEC_ARTIFACT_FAILURE_IDS
            for failure in verify_result.failures
        )

    def _print_external_spec_artifact_blocker(
        self,
        verify_result: VerifyResult,
    ) -> None:
        from echelon.ui import banner as _ui_banner

        details = "\n".join(
            f"[{failure.category.value}] {failure.id}: {failure.error}"
            for failure in verify_result.failures
            if failure.id in _EXTERNAL_SPEC_ARTIFACT_FAILURE_IDS
        )
        _ui_banner(
            "HARNESS — RALPH-OWNED SPEC ARTIFACT MISSING",
            [
                ("spec", self._spec_id),
                ("strategy", self._strategy_id),
                (
                    "why",
                    "Ralph-owned external spec artifact is missing or invalid",
                ),
                (
                    "meaning",
                    "The target build agent cannot legally fix this because "
                    "external spec artifacts are read-only in delivery worktrees",
                ),
                ("failure", details),
            ],
            file=sys.stderr,
        )

    def _apply_task_progress_gate(
        self,
        verify_result: VerifyResult,
        worktree_path: str,
        *,
        require_completion: bool = True,
    ) -> VerifyResult:
        """Treat task progress mismatches as verification failures."""
        if not verify_result.passed or not worktree_path:
            return verify_result

        spec_dir = self._find_existing_spec_dir(worktree_path)
        if spec_dir is None:
            return verify_result

        tasks_path = spec_dir / "tasks.md"
        if not tasks_path.exists():
            return verify_result

        state = self._state_store.read()
        summary = summarize_task_progress(
            tasks_path.read_text(encoding="utf-8", errors="replace"),
            state.get("build") if isinstance(state.get("build"), dict) else {},
            selected_task_ids=self._target_task_ids(),
        )
        if not summary.valid:
            failure = FailureEntry(
                category=FailureCategory.OTHER,
                id="task-progress-mismatch",
                error=(
                    "task progress tracking is inconsistent: "
                    + "; ".join(summary.errors)
                    + ". Update tasks.md canonical rows and state.json build progress before convergence."
                ),
            )
        elif require_completion:
            incomplete = sorted(
                task_id
                for task_id, status in summary.task_statuses.items()
                if status in {"PENDING", "BLOCKED"}
            )
            if incomplete:
                failure = FailureEntry(
                    category=FailureCategory.OTHER,
                    id="task-progress-incomplete",
                    error=(
                        "canonical delivery tasks remain open: "
                        + ", ".join(incomplete)
                        + ". Complete them or record approved deferred scope before convergence."
                    ),
                )
            else:
                missing = _missing_completed_task_deliverables(
                    tasks_path.read_text(encoding="utf-8", errors="replace"),
                    task_statuses=summary.task_statuses,
                    worktree_path=Path(worktree_path),
                    implementation_target=str(state.get("implementation_target") or ""),
                )
                if not missing:
                    return verify_result
                failure = FailureEntry(
                    category=FailureCategory.OTHER,
                    id="task-deliverable-missing",
                    error=(
                        "completed task deliverables are absent from the target worktree: "
                        + ", ".join(missing)
                    ),
                )
        else:
            return verify_result
        return VerifyResult(
            passed=False,
            failures=[failure],
            duration_s=verify_result.duration_s,
            token_usage=verify_result.token_usage,
            verification_evidence=dict(verify_result.verification_evidence),
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

        target_task_ids = self._target_task_ids()
        completed_ids = [
            str(task_id).strip()
            for task_id in task_ids
            if str(task_id).strip()
            and (target_task_ids is None or str(task_id).strip() in target_task_ids)
        ]
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
        summary = summarize_task_progress(
            markdown,
            selected_task_ids=target_task_ids,
        )
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
        operation = state.get("delivery_slice_operation")
        if isinstance(operation, dict) and operation.get("accepted_task_id") in applied:
            operation["progress_applied"] = True
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
        if isinstance(build_result, _DocumentationBuildResult):
            operation = self._state_store.read().get("delivery_slice_operation")
            if (isinstance(operation, dict) and operation.get("kind") == "documentation"
                    and operation.get("progress_applied") is True
                    and operation.get("id") == build_result.get("documentation_operation_id")
                    and operation.get("worktree_path") == str(Path(worktree_path).resolve())):
                return
        if (
            build_result.get("completion_metadata_recovery") is True
            and build_result.get("partial_progress") is True
        ):
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
            tasks_path.read_text(encoding="utf-8", errors="replace"),
            selected_task_ids=self._target_task_ids(),
        )
        if (
            summary.total_tasks <= 0
            or summary.terminal_tasks >= summary.total_tasks
        ):
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
                verification_evidence=dict(verify_result.verification_evidence),
            )

        coverage_observation, observer_required, coverage_error = (
            self._coverage_observation_for_fulfillment(
                verify_result,
                worktree_path,
            )
        )
        if coverage_error:
            return self._coverage_observation_failure(
                verify_result,
                failure_id="coverage-observation-invalid",
                error=coverage_error,
            )
        refresh_kwargs: dict[str, object] = {
            "spec_dir": (
                self._find_existing_spec_dir(worktree_path)
                if observer_required
                else self._find_spec_dir(worktree_path)
            ),
            "orchestration_root": (
                self._orchestration_root(Path(worktree_path))
                if self._spec_artifacts_mode() == "external"
                else None
            ),
        }
        delivery_state = self._state_store.read()
        source_id = str(delivery_state.get("source_id") or "").strip()
        source_root = str(delivery_state.get("source_root") or "").strip()
        if source_id and source_root:
            refresh_kwargs["source_id"] = source_id
            refresh_kwargs["source_root"] = source_root
        if observer_required:
            refresh_kwargs["observer_required"] = True
            refresh_kwargs["coverage_observation"] = coverage_observation
        if verify_result.verification_evidence:
            refresh_kwargs["verification_evidence"] = dict(
                verify_result.verification_evidence
            )
        if decision.get("action") == "scoped":
            refresh_kwargs.update(
                {
                    "scope": "scoped",
                    "completed_task_ids": completed_task_ids or [],
                    "changed_files": changed_files or [],
                }
            )
        try:
            refresh_kwargs.update(
                self._controlled_fulfillment_options(worktree_path, refresh_kwargs)
            )
        except (ValueError, OSError, TypeError, KeyError) as exc:
            return VerifyResult(False, [FailureEntry(FailureCategory.OTHER,
                "fulfillment-containment-invalid", str(exc))], verify_result.duration_s,
                verify_result.token_usage, dict(verify_result.verification_evidence))
        refresh_result = self._fulfillment_runner.refresh(
            worktree_path,
            self._spec_id,
            **refresh_kwargs,
        )
        from dataclasses import replace
        newly_used = self._account_fulfillment_usage(refresh_result)
        verify_result = replace(
            verify_result, token_usage=verify_result.token_usage + newly_used
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
                "verified_ledger": getattr(refresh_result, "verified_ledger", None),
            }
        )
        if exit_code == 0:
            if decision.get("action") == "scoped" and getattr(
                refresh_result, "scope", ""
            ) == "scoped":
                if self._target_task_ids() is not None:
                    return verify_result
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
                    verification_evidence=dict(verify_result.verification_evidence),
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
                verification_evidence=dict(verify_result.verification_evidence),
            )

        failure = FailureEntry(
            category=FailureCategory.OTHER,
            id="verify-spec-failed",
            error=(
                f"`echelon spec verify {self._spec_id}` failed with exit code "
                f"{exit_code}; fulfillment could not be refreshed."
            ),
        )
        return VerifyResult(
            passed=False,
            failures=[failure],
            duration_s=verify_result.duration_s,
            token_usage=verify_result.token_usage,
            verification_evidence=dict(verify_result.verification_evidence),
        )

    def _controlled_fulfillment_options(self, worktree_path, refresh_kwargs):
        """Bind the exact refresh before dispatch; reuse delivery's root policy."""
        from harness.llm_build_runner import _containment_policy_env
        from harness.fulfillment_runner import _spec_input_hash, _implementation_input_hash
        from harness.controlled_fulfillment import _digest
        state = self._state_store.read()
        workspace = self._orchestration_root(Path(worktree_path))
        policy_path = self._state_store.state_dir / "delivery-containment-policy.json"
        if policy_path.is_symlink():
            raise ValueError("unsafe fulfillment containment policy")
        policy = json.loads(policy_path.read_text())
        source_root = state.get("source_root") or str(worktree_path)
        source_id = state.get("source_id") or Path(str(source_root)).name
        expected = dict(schema_version=1, worktree=str(worktree_path), workspace_root=str(workspace),
                        source_id=source_id, source_root=source_root)
        if any(policy.get(key) != value for key, value in expected.items()):
            raise ValueError("fulfillment containment policy binding changed")
        env, error = _containment_policy_env(str(policy_path), worktree_path=worktree_path)
        if error:
            raise ValueError(error)
        forbidden = tuple(Path(path) for key in ("ECHELON_FORBIDDEN_ROOTS_JSON", "ECHELON_FORBIDDEN_ROOT_ALIASES_JSON")
                          for path in json.loads(env[key]))
        spec = refresh_kwargs.get("spec_dir")
        if spec is None:
            raise ValueError("controlled fulfillment spec is unavailable")
        key = _digest(dict(worktree=str(worktree_path), workspace=str(workspace),
            spec=_spec_input_hash(Path(spec)), product=_implementation_input_hash(Path(worktree_path)),
            scope=refresh_kwargs.get("scope", "full"), tasks=refresh_kwargs.get("completed_task_ids", []),
            changed=refresh_kwargs.get("changed_files", []), evidence=refresh_kwargs.get("verification_evidence"),
            observation=refresh_kwargs["coverage_observation"].ref.as_mapping() if refresh_kwargs.get("coverage_observation") else None))
        pending = state.get("fulfillment_operation")
        selected = None
        if isinstance(pending, dict) and (pending.get("input_key") == key or pending.get("status") in {"pending", "unknown"}):
            selected = pending.get("id")
            if not isinstance(selected, str) or not selected:
                raise ValueError("invalid persisted fulfillment selection")
        records = state.get("fulfillment_operations", {})
        if not isinstance(records, dict) or any(not isinstance(row, dict)
                or type(row.get("accounted_tokens")) is not int or row["accounted_tokens"] < 0 for row in records.values()):
            raise ValueError("invalid persisted fulfillment accounting")
        ceilings = []
        if self._controlled_slice_budget is not None:
            ceilings.append(max(0, self._controlled_slice_budget))
        budget = state.get("token_budget")
        if isinstance(budget, (int, float)) and budget > 0:
            ceilings.append(max(0, budget * 0.95 - state.get("tokens_used", 0)))
        def selected_run(path):
            current = self._state_store.read()
            current["fulfillment_operation"] = dict(id=str(path), input_key=key, status="pending")
            self._state_store.write(current)
        return dict(orchestration_root=workspace, forbidden_paths=forbidden,
            verify_run_dir=selected, on_run_selected=selected_run,
            token_budget=min(ceilings) if ceilings else None,
            accounted_usage={name: row["accounted_tokens"] for name, row in records.items()})

    def _account_fulfillment_usage(self, result):
        """Commit cumulative receipts and the newly charged amount atomically."""
        operation_id = getattr(result, "operation_id", None)
        if operation_id is None:
            return 0
        state = self._state_store.read()
        records = state.setdefault("fulfillment_operations", {})
        row = records.setdefault(operation_id, {"accounted_tokens": 0, "usage_unknown": False})
        usage = getattr(result, "token_usage", None)
        newly_used = 0
        if usage is None:
            row["usage_unknown"] = True
            state["fulfillment_usage_unknown"] = True
        else:
            newly_used = max(0, usage - row["accounted_tokens"])
            row["accounted_tokens"] = max(row["accounted_tokens"], usage)
            state["tokens_used"] = state.get("tokens_used", 0) + newly_used
        pending = state.get("fulfillment_operation")
        if isinstance(pending, dict) and pending.get("id") == operation_id:
            pending["status"] = "unknown" if usage is None else ("complete" if result.ok else "failed")
        self._state_store.write(state)
        return newly_used

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
        tasks_complete = (
            total > 0 and completed >= total
        ) or self._all_canonical_tasks_complete(worktree_path)
        if self._target_task_ids() is not None:
            state = self._state_store.read()
            declared_targets = state.get("declared_targets")
            if (
                tasks_complete
                and isinstance(declared_targets, list)
                and len([target for target in declared_targets if str(target).strip()]) == 1
            ):
                return {
                    "action": "full",
                    "reason": "single target convergence boundary reached",
                }
            return {
                "action": "scoped",
                "reason": "multi-target delivery uses target-owned task scope",
            }
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
        verified_ledger = data.get("verified_ledger")
        if isinstance(verified_ledger, dict):
            state["fulfillment_refresh"]["verified_ledger"] = {
                "reused": int(verified_ledger.get("reused") or 0),
                "rechecked": int(verified_ledger.get("rechecked") or 0),
                "invalidated": int(verified_ledger.get("invalidated") or 0),
                "unresolved": int(verified_ledger.get("unresolved") or 0),
            }
        self._state_store.write(state)
        self._print_fulfillment_refresh_decision(
            status=str(state["fulfillment_refresh"]["status"]),
            reason=str(state["fulfillment_refresh"]["reason"]),
            verified_ledger=state["fulfillment_refresh"].get("verified_ledger"),
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

    def _convergence_lease(self) -> ConvergenceLease:
        state = self._state_store.read()
        return ConvergenceLease.from_state(state.get("convergence_lease"))

    def _latest_checkpoint_commit(self) -> str | None:
        state = self._state_store.read()
        checkpoints = state.get("checkpoint_commits")
        if not isinstance(checkpoints, list):
            return None
        for checkpoint in reversed(checkpoints):
            if not isinstance(checkpoint, dict):
                continue
            commit = checkpoint.get("commit")
            if isinstance(commit, str) and commit.strip():
                return commit.strip()
        return None

    def _record_convergence_observation(
        self,
        verify_result: VerifyResult,
        worktree_path: str,
        *,
        hard_ceiling: int,
    ) -> LeaseObservation:
        total_tasks, completed_tasks = self._task_progress_counts()
        snapshot = ProgressSnapshot.from_verify_result(
            verify_result,
            completed_tasks=completed_tasks,
            total_tasks=total_tasks,
            product_fingerprint=_safe_product_evidence_fingerprint(worktree_path),
            checkpoint_commit=self._latest_checkpoint_commit(),
        )
        observation = self._convergence_lease().observe(
            snapshot,
            hard_ceiling=hard_ceiling,
        )
        state = self._state_store.read()
        state["convergence_lease"] = observation.lease.to_state()
        self._state_store.write(state)
        self._append_convergence_telemetry(
            observation,
            snapshot=snapshot,
            hard_ceiling=hard_ceiling,
            state=state,
        )
        logger.info(
            "Convergence observation %s (%s): meaningful=%d/%d stalled=%d",
            observation.outcome,
            observation.reason_code,
            observation.lease.meaningful_attempts,
            hard_ceiling,
            observation.lease.stalled_attempts,
        )
        return observation

    def _append_convergence_telemetry(
        self,
        observation: LeaseObservation,
        *,
        snapshot: ProgressSnapshot,
        hard_ceiling: int,
        state: Mapping[str, object],
    ) -> None:
        """Append one content-free authoritative convergence observation."""
        try:
            telemetry_dir = self._state_store.state_dir.parent / "telemetry"
            telemetry_dir.mkdir(parents=True, exist_ok=True)
            event = {
                "schema_version": 1,
                "type": "delivery.convergence_observation",
                "event_time": datetime.now(timezone.utc).isoformat(),
                "run_id": state.get("run_id") or self._build_id,
                "spec_id": self._spec_id,
                "strategy_id": self._strategy_id,
                "outcome": observation.outcome,
                "reason_code": observation.reason_code,
                "should_stop": observation.should_stop,
                "stop_reason": observation.stop_reason,
                "meaningful_attempts": observation.lease.meaningful_attempts,
                "stalled_attempts": observation.lease.stalled_attempts,
                "infrastructure_attempts": observation.lease.infrastructure_attempts,
                "hard_ceiling": hard_ceiling,
                "completed_tasks": snapshot.completed_tasks,
                "total_tasks": snapshot.total_tasks,
                "fulfillment_debt": snapshot.fulfillment_debt,
                "blocking_failure_count": len(snapshot.failure_keys),
                "gate_rank": snapshot.gate_rank,
                "product_fingerprint": snapshot.product_fingerprint,
                "best_checkpoint_commit": observation.lease.best_checkpoint_commit,
            }
            with (telemetry_dir / "events.jsonl").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception as exc:
            logger.warning("Could not append convergence telemetry: %s", exc)

    def _print_fulfillment_refresh_decision(
        self,
        *,
        status: str,
        reason: str,
        verified_ledger: object = None,
    ) -> None:
        print(f"fulfillment refresh: {status} ({reason})", file=sys.stderr)
        if isinstance(verified_ledger, dict):
            print(
                "verified ledger: "
                f"reused {int(verified_ledger.get('reused') or 0)}, "
                f"rechecked {int(verified_ledger.get('rechecked') or 0)}, "
                f"invalidated {int(verified_ledger.get('invalidated') or 0)}, "
                f"unresolved {int(verified_ledger.get('unresolved') or 0)}",
                file=sys.stderr,
            )

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
            cmd = shlex.split(self._config.verify_command)
            verify_cwd = (
                str(Path(worktree_path).resolve())
                if worktree_path
                else str(getattr(self._gitops, "base_dir", ""))
            )
            fingerprint_before = _safe_product_evidence_fingerprint(
                worktree_path
            )
            candidate_commit = _current_git_commit(Path(worktree_path))
            stage_started_at = datetime.now(timezone.utc).isoformat()
            stage_start = time.monotonic()
            stdout = b""
            stderr = b""
            exit_code = 1
            try:
                res = _sp.run(
                    cmd,
                    cwd=verify_cwd,
                    capture_output=True,
                    timeout=300,
                )
                stdout = bytes(res.stdout or b"")
                stderr = bytes(res.stderr or b"")
                exit_code = int(res.returncode)
                if res.returncode != 0:
                    out = (stdout + stderr).decode(
                        "utf-8", errors="replace"
                    ).strip()
                    failures.append(FailureEntry(
                        category=FailureCategory.TEST,
                        id="verify-command",
                        error=out[-2000:] if len(out) > 2000 else out,
                    ))
            except _sp.TimeoutExpired as exc:
                stdout = bytes(exc.stdout or b"")
                stderr = bytes(exc.stderr or b"")
                exit_code = 124
                failures.append(FailureEntry(
                    category=FailureCategory.TEST,
                    id="verify-command-timeout",
                    error="configured verifier timed out after 300 seconds",
                ))
            except Exception as e:
                failures.append(FailureEntry(
                    category=FailureCategory.OTHER, id="verify-command-error", error=str(e),
                ))
            stage_completed_at = datetime.now(timezone.utc).isoformat()
            fingerprint_after = _safe_product_evidence_fingerprint(
                worktree_path
            )
            if (
                fingerprint_before is not None
                and fingerprint_after is not None
                and fingerprint_before != fingerprint_after
            ):
                failures.append(
                    FailureEntry(
                        category=FailureCategory.OTHER,
                        id="candidate-mutated-during-verification",
                        error=(
                            "configured verifier changed bounded candidate "
                            "content during verification"
                        ),
                    )
                )
            duration_s = time.monotonic() - start
            return self._attach_host_verification_receipt(
                worktree_path=worktree_path,
                candidate_commit=candidate_commit,
                fingerprint_before=fingerprint_before,
                fingerprint_after=fingerprint_after,
                verifier_source="configured",
                detection_evidence=("harness verify_command",),
                stages=(
                    VerificationStage(
                        name="verify",
                        command=tuple(cmd),
                        exit_code=exit_code,
                        duration_ms=int(
                            (time.monotonic() - stage_start) * 1000
                        ),
                        stdout=stdout,
                        stderr=stderr,
                        started_at=stage_started_at,
                        completed_at=stage_completed_at,
                    ),
                ),
                failures=failures,
                duration_s=duration_s,
            )

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
            return self._exec_verify_swift(
                str(swift_package_dir), start, worktree_path
            )

        detection = detect_verify_command(wt)
        if (wt / "pnpm-lock.yaml").exists():
            commands = [
                ("install", "pnpm install --frozen-lockfile --ignore-scripts"),
            ]
            fallback_commands = [("test", "pnpm test"), ("build", "pnpm run build")]
        elif (wt / "yarn.lock").exists():
            commands = [
                ("install", "yarn install --frozen-lockfile"),
            ]
            fallback_commands = [("test", "yarn test"), ("build", "yarn run build")]
        elif is_node:
            commands = [
                ("install", "npm ci"),
            ]
            fallback_commands = [("test", "npm test"), ("build", "npm run build")]
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

        if detection.command and detection.evidence == ["package.json scripts.verify"]:
            commands.append(("verify", detection.command))
        else:
            commands.extend(fallback_commands)

        verify_env = os.environ.copy()
        verify_env["CI"] = "true"
        candidate_commit = _current_git_commit(wt)
        fingerprint_before = _safe_product_evidence_fingerprint(worktree_path)
        verification_stages: list[VerificationStage] = []
        for stage, cmd in commands:
            stage_started_at = datetime.now(timezone.utc).isoformat()
            stage_start = time.monotonic()
            stdout = b""
            stderr = b""
            exit_code = 1
            try:
                result = subprocess.run(
                    shlex.split(cmd),
                    cwd=worktree_path,
                    capture_output=True,
                    stdin=subprocess.DEVNULL,
                    env=verify_env,
                    timeout=300,
                )
                stdout = _output_bytes(result.stdout)
                stderr = _output_bytes(result.stderr)
                exit_code = int(result.returncode)
                if result.returncode != 0:
                    output = (stdout + stderr).decode(
                        "utf-8", errors="replace"
                    ).strip()
                    failures.append(FailureEntry(
                        category=FailureCategory.BUILD if stage in ("build", "install") else FailureCategory.TEST,
                        id=f"local-{stage}",
                        error=output[-2000:] if len(output) > 2000 else output,
                    ))
                    # Don't run further stages if install or test fails
                    if stage in ("install", "test"):
                        break
            except subprocess.TimeoutExpired:
                exit_code = 124
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
            finally:
                verification_stages.append(
                    VerificationStage(
                        name=stage,
                        command=tuple(shlex.split(cmd)),
                        exit_code=exit_code,
                        duration_ms=int(
                            (time.monotonic() - stage_start) * 1000
                        ),
                        stdout=stdout,
                        stderr=stderr,
                        started_at=stage_started_at,
                        completed_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
            if failures:
                break

        duration_s = time.monotonic() - start
        fingerprint_after = _safe_product_evidence_fingerprint(worktree_path)
        if (
            fingerprint_before is not None
            and fingerprint_after is not None
            and fingerprint_before != fingerprint_after
        ):
            failures.append(
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id="candidate-mutated-during-verification",
                    error=(
                        "detected verifier changed bounded candidate content "
                        "during verification"
                    ),
                )
            )
        return self._attach_host_verification_receipt(
            worktree_path=worktree_path,
            candidate_commit=candidate_commit,
            fingerprint_before=fingerprint_before,
            fingerprint_after=fingerprint_after,
            verifier_source="detected",
            detection_evidence=tuple(detection.evidence),
            stages=tuple(verification_stages),
            failures=failures,
            duration_s=duration_s,
        )

    def _attach_host_verification_receipt(
        self,
        *,
        worktree_path: str,
        candidate_commit: str | None,
        fingerprint_before: str | None,
        fingerprint_after: str | None,
        verifier_source: str,
        detection_evidence: tuple[str, ...],
        stages: tuple[VerificationStage, ...],
        failures: list[FailureEntry],
        duration_s: float,
        execution_context: Mapping[str, object] | None = None,
    ) -> VerifyResult:
        """Persist and attach evidence for one Ralph-owned verification."""
        if not candidate_commit or not fingerprint_before or not fingerprint_after:
            missing = [
                name
                for name, value in (
                    ("candidate commit", candidate_commit),
                    ("pre-verification fingerprint", fingerprint_before),
                    ("post-verification fingerprint", fingerprint_after),
                )
                if not value
            ]
            return VerifyResult(
                passed=False,
                failures=[
                    *failures,
                    FailureEntry(
                        category=FailureCategory.OTHER,
                        id="verification-evidence-invalid",
                        error=(
                            "could not bind verification to the candidate "
                            "commit and content fingerprint; missing "
                            + ", ".join(missing)
                        ),
                    ),
                ],
                duration_s=duration_s,
            )
        evidence_dir = (
            self._state_store.state_dir.parent
            / "evidence"
            / self._strategy_id
            / "verification"
        )
        sequence = self._next_host_verification_attempt(evidence_dir)
        try:
            ref = write_verification_receipt(
                evidence_dir=evidence_dir,
                spec_id=self._spec_id,
                strategy_id=self._strategy_id,
                build_id=self._build_id
                or str(self._state_store.read().get("run_id") or ""),
                target_id=str(
                    self._state_store.read().get("source_id") or ""
                ),
                candidate_commit=candidate_commit,
                fingerprint_before=fingerprint_before,
                fingerprint_after=fingerprint_after,
                verifier_source=verifier_source,
                detection_evidence=detection_evidence,
                execution_context=execution_context,
                stages=stages,
                attempt_sequence=sequence,
                sensitive_environment=os.environ,
                started_at=stages[0].started_at if stages else None,
            )
        except (OSError, ValueError) as exc:
            return VerifyResult(
                passed=False,
                failures=[
                    *failures,
                    FailureEntry(
                        category=FailureCategory.OTHER,
                        id="verification-evidence-invalid",
                        error=f"could not persist verification evidence: {exc}",
                    ),
                ],
                duration_s=duration_s,
            )
        return VerifyResult(
            passed=ref.passed and not failures,
            failures=failures,
            duration_s=duration_s,
            verification_evidence=ref.as_mapping(),
        )

    @staticmethod
    def _next_host_verification_attempt(evidence_dir: Path) -> int:
        if not evidence_dir.exists():
            return 1
        sequences: list[int] = []
        for path in evidence_dir.glob("attempt-*.json"):
            match = re.match(r"attempt-(\d+)-", path.name)
            if match:
                sequences.append(int(match.group(1)))
        return max(sequences, default=0) + 1

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
        candidate_commit = _current_git_commit(wt)
        fingerprint_before = _safe_product_evidence_fingerprint(worktree_path)

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

        stage_started_at = datetime.now(timezone.utc).isoformat()
        stage_start = time.monotonic()
        stdout = b""
        stderr = b""
        exit_code = 1
        try:
            result = subprocess.run(
                pytest_cmd,
                cwd=worktree_path,
                capture_output=True,
                timeout=300,
            )
            stdout = _output_bytes(result.stdout)
            stderr = _output_bytes(result.stderr)
            exit_code = int(result.returncode)
            if result.returncode != 0:
                output = (stdout + stderr).decode(
                    "utf-8", errors="replace"
                ).strip()
                failures.append(FailureEntry(
                    category=FailureCategory.TEST,
                    id="pytest",
                    error=output[-2000:] if len(output) > 2000 else output,
                ))
        except subprocess.TimeoutExpired:
            exit_code = 124
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
        fingerprint_after = _safe_product_evidence_fingerprint(worktree_path)
        if (
            fingerprint_before is not None
            and fingerprint_after is not None
            and fingerprint_before != fingerprint_after
        ):
            failures.append(
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id="candidate-mutated-during-verification",
                    error=(
                        "pytest changed bounded candidate content during "
                        "verification"
                    ),
                )
            )
        detection = detect_verify_command(wt)
        return self._attach_host_verification_receipt(
            worktree_path=worktree_path,
            candidate_commit=candidate_commit,
            fingerprint_before=fingerprint_before,
            fingerprint_after=fingerprint_after,
            verifier_source="detected",
            detection_evidence=tuple(detection.evidence),
            stages=(
                VerificationStage(
                    name="pytest",
                    command=tuple(str(item) for item in pytest_cmd),
                    exit_code=exit_code,
                    duration_ms=int((time.monotonic() - stage_start) * 1000),
                    stdout=stdout,
                    stderr=stderr,
                    started_at=stage_started_at,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                ),
            ),
            failures=failures,
            duration_s=duration_s,
        )

    def _exec_verify_swift(
        self, package_dir: str, start: float, worktree_path: str
    ) -> VerifyResult:
        """Run Swift Package Manager verification: ``swift build`` then ``swift test``.

        Runs from ``package_dir`` (the directory containing Package.swift).
        Timeout is 600 s per stage to allow for initial dependency resolution and
        compilation which can be slow on a cold cache.
        """
        import subprocess
        import shutil
        import time

        failures = []
        candidate_commit = _current_git_commit(Path(worktree_path))
        fingerprint_before = _safe_product_evidence_fingerprint(worktree_path)
        stages: list[VerificationStage] = []

        if not shutil.which("swift"):
            duration_s = time.monotonic() - start
            message = (
                "swift toolchain not found on PATH. Install Xcode or the "
                "Swift toolchain and ensure 'swift' is on PATH."
            )
            failures.append(FailureEntry(
                    category=FailureCategory.BUILD,
                    id="swift-not-found",
                    error=message,
                ))
            stages.append(
                VerificationStage(
                    name="swift-build",
                    command=("swift", "build"),
                    exit_code=127,
                    duration_ms=0,
                    stdout=b"",
                    stderr=message.encode("utf-8"),
                    started_at=datetime.now(timezone.utc).isoformat(),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
            )
            return self._attach_host_verification_receipt(
                worktree_path=worktree_path,
                candidate_commit=candidate_commit,
                fingerprint_before=fingerprint_before,
                fingerprint_after=_safe_product_evidence_fingerprint(
                    worktree_path
                ),
                verifier_source="detected",
                detection_evidence=("Package.swift",),
                stages=tuple(stages),
                failures=failures,
                duration_s=duration_s,
            )

        for stage, cmd in [("build", "swift build"), ("test", "swift test")]:
            stage_started_at = datetime.now(timezone.utc).isoformat()
            stage_start = time.monotonic()
            stdout = b""
            stderr = b""
            exit_code = 1
            try:
                result = subprocess.run(
                    cmd.split(),
                    cwd=package_dir,
                    capture_output=True,
                    timeout=600,
                )
                stdout = _output_bytes(result.stdout)
                stderr = _output_bytes(result.stderr)
                exit_code = int(result.returncode)
                if result.returncode != 0:
                    output = (stdout + stderr).decode(
                        "utf-8", errors="replace"
                    ).strip()
                    failures.append(FailureEntry(
                        category=FailureCategory.BUILD if stage == "build" else FailureCategory.TEST,
                        id=f"swift-{stage}",
                        error=output[-2000:] if len(output) > 2000 else output,
                    ))
                    break
            except subprocess.TimeoutExpired:
                exit_code = 124
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
            finally:
                stages.append(
                    VerificationStage(
                        name=f"swift-{stage}",
                        command=tuple(cmd.split()),
                        exit_code=exit_code,
                        duration_ms=int(
                            (time.monotonic() - stage_start) * 1000
                        ),
                        stdout=stdout,
                        stderr=stderr,
                        started_at=stage_started_at,
                        completed_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
            if failures:
                break

        duration_s = time.monotonic() - start
        fingerprint_after = _safe_product_evidence_fingerprint(worktree_path)
        if (
            fingerprint_before is not None
            and fingerprint_after is not None
            and fingerprint_before != fingerprint_after
        ):
            failures.append(
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id="candidate-mutated-during-verification",
                    error=(
                        "Swift verification changed bounded candidate content"
                    ),
                )
            )
        return self._attach_host_verification_receipt(
            worktree_path=worktree_path,
            candidate_commit=candidate_commit,
            fingerprint_before=fingerprint_before,
            fingerprint_after=fingerprint_after,
            verifier_source="detected",
            detection_evidence=("Package.swift",),
            stages=tuple(stages),
            failures=failures,
            duration_s=duration_s,
        )

    def run_downstream_feedback(
        self,
        *,
        handle: SandboxHandle,
        worktree_path: str,
        verify_result: VerifyResult,
        build_command: str,
        strategy_context: str,
        build_prompt: str,
        phase: str,
        evidence_paths: tuple[str, ...] = (),
        token_budget: int | None = None,
        tokens_used: int = 0,
    ) -> Dict[str, Any]:
        """Apply a downstream-gate repair through the configured build provider."""
        state = self._state_store.read()
        # Downstream entry may reconstruct Ralph without running either build
        # loop. Recompute its allowance, including caller-owned gate usage that
        # has not reached strategy state yet; never reuse a prior slice's value.
        ceilings = [value for value in (token_budget, state.get("token_budget"))
                    if value is not None and value > 0]
        used = max(tokens_used, state.get("tokens_used", 0))
        self._controlled_slice_budget = (
            max(0, min(ceilings) * 0.95 - used) if ceilings else None
        )
        _clear_build_status(worktree_path)
        prompt = self._make_feedback_prompt(build_prompt, verify_result, 0)
        prompt += (
            f"\n\nThis repair was requested by the downstream {phase} gate. "
            "Repair the product or its executable acceptance test; do not weaken, "
            "skip, or remove the gate. The harness will rerun Phase 1 and the "
            f"{phase} gate after this invocation."
        )
        if evidence_paths:
            prompt += "\nEvidence paths available for inspection:\n" + "\n".join(
                f"- {path}" for path in evidence_paths
            )
        return self._exec_feedback(
            handle,
            verify_result,
            build_command,
            strategy_context,
            worktree_path=worktree_path,
            prompt=prompt,
            repair_context={"base_prompt": build_prompt, "phase": phase,
                            "inner_iteration": 0, "evidence_paths": list(evidence_paths)},
        )

    def _exec_feedback(
        self,
        handle: SandboxHandle,
        verify_result: VerifyResult,
        build_command: str,
        strategy_context: str,
        worktree_path: str = "",
        prompt: str = "",
        repair_context: Mapping[str, object] | None = None,
    ) -> Dict[str, Any]:
        """Execute one controller-owned repair or documentation slice."""
        del handle, build_command
        documentation = bool(verify_result.failures) and all(
            failure.id.startswith(("documentation-", "docs-", "readme-", "changelog-"))
            for failure in verify_result.failures
        )
        if documentation:
            prompt = json.dumps({"failures": [
                {"category": failure.category.value, "id": failure.id,
                 "error": failure.error, "details": failure.details}
                for failure in verify_result.failures
            ], "verification_evidence": verify_result.verification_evidence}, sort_keys=True)
        else:
            context = dict(repair_context) if repair_context is not None else {
                "base_prompt": prompt, "phase": "inner",
                "inner_iteration": 0, "evidence_paths": [],
            }
            context["strategy_context"] = strategy_context
            prompt = json.dumps({
                "feedback_kind": "controlled_source_repair_v1",
                "context": context,
                "failures": [
                    {"category": failure.category.value, "id": failure.id,
                     "error": failure.error, "details": failure.details}
                    for failure in verify_result.failures
                ],
                "verification_evidence": verify_result.verification_evidence,
            }, sort_keys=True)
        return self._exec_controlled_slice(
            worktree_path, prompt, repair=True, documentation=documentation
        )

    def _prepare_delivery_context(self, worktree_path: str) -> None:
        """Write deterministic context and containment inputs for a slice."""
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
        allowed_context_roots = _normalized_path_list(
            state.get("allowed_context_roots"),
            base_path=workspace_root,
        )
        forbidden_source_roots = self._forbidden_sibling_source_roots(
            workspace_root=workspace_root,
            source_root=source_root,
            allowed_context_roots=allowed_context_roots,
        )
        self._write_delivery_containment_policy(
            worktree_path=worktree_path,
            workspace_root=workspace_root,
            workspace_git_role=workspace_git_role,
            source_root=source_root,
            source_id=source_id,
            source_git_role=source_git_role,
            spec_dir=spec_dir,
            allowed_context_roots=allowed_context_roots,
            forbidden_source_roots=forbidden_source_roots,
        )
        spec_dir_text = str(spec_dir) if spec_dir is not None else "MISSING"
        spec_file_text = str(spec_dir / "spec.md" if spec_dir is not None else "MISSING")
        tasks_file_text = str(spec_dir / "tasks.md" if spec_dir is not None else "MISSING")
        dirty_verify_artifacts = self._dirty_verify_artifacts(worktree_path)
        dirty_verify_block = ""
        if dirty_verify_artifacts:
            self._record_dirty_verify_artifacts(worktree_path, dirty_verify_artifacts)
            dirty_verify_block = (
                "dirty_verify_artifacts:\n"
                + "".join(f"- {path}\n" for path in dirty_verify_artifacts)
                + "Treat these as inherited verify-spec outputs. Do not hand-edit "
                "them in build slices; Ralph owns regeneration and commit/salvage.\n"
            )
        self._write_build_slice_context(
            worktree_path=worktree_path,
            workspace_root=workspace_root,
            workspace_git_role=workspace_git_role,
            source_root=source_root,
            source_id=source_id,
            source_git_role=source_git_role,
            spec_artifacts_mode=spec_artifacts_mode,
            spec_dir_text=spec_dir_text,
            spec_file_text=spec_file_text,
            tasks_file_text=tasks_file_text,
            spec_dir=spec_dir,
            tasks_path=(spec_dir / "tasks.md" if spec_dir is not None else None),
            dirty_verify_block=dirty_verify_block,
            progress_ledger_block=self._delivery_progress_ledger_block(state),
            implementation_target_contract=self._implementation_target_contract_block(state),
        )

    def _coverage_observation_contract_block(self) -> str:
        """Tell build providers how required structured coverage is bound."""
        resolved = getattr(self._config, "resolved_stacks", None)
        required_observers = tuple(
            item
            for item in getattr(resolved, "coverage_observers", ())
            if item.observer.required
        )
        if not required_observers:
            return ""
        return (
            "## Coverage Observation Contract\n"
            "Selected stacks require structured coverage observation. For every "
            "coverage-map test-case ID that your slice implements, the executed "
            "test title must end with an Echelon case tag, for example "
            "`[echelon:UT-EXAMPLE-001]`. Use the coverage-map test-case ID, "
            "not an AC/FR requirement ID. A single test may list multiple "
            "comma-separated case IDs only when it genuinely proves each case "
            "and their planned test types match the executing observer. Each case "
            "ID must appear in exactly one physical test identity; duplicate case "
            "tags are invalid. Do not edit the coverage map or weaken its required "
            "observations.\n"
        )

    def _write_build_slice_context(
        self,
        *,
        worktree_path: str,
        workspace_root: object,
        workspace_git_role: object,
        source_root: object,
        source_id: object,
        source_git_role: object,
        spec_artifacts_mode: str,
        spec_dir_text: str,
        spec_file_text: str,
        tasks_file_text: str,
        spec_dir: Path | None,
        tasks_path: Path | None,
        dirty_verify_block: str,
        progress_ledger_block: str,
        implementation_target_contract: str,
    ) -> Path:
        """Write bounded build context for LLM build and feedback turns."""
        context_dir = self._state_store.state_dir.parent / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        context_file = context_dir / f"{self._strategy_id}-build-slice-context.md"
        lines = [
            "# Build Slice Context",
            "",
            "This file is generated by Ralph. Treat it as read-only context.",
            "",
            "## Roots",
            f"- worktree: `{worktree_path}`",
            f"- target_repo_worktree: `{worktree_path}`",
            f"- workspace_root: `{workspace_root}`",
            f"- workspace_git_role: `{workspace_git_role}`",
            f"- source_root: `{source_root}`",
            f"- source_id: `{source_id}`",
            f"- source_git_role: `{source_git_role}`",
            "",
            "## Spec Inputs",
            f"- spec_artifacts_mode: `{spec_artifacts_mode}`",
            f"- spec_dir: `{spec_dir_text}`",
            f"- spec_file: `{spec_file_text}`",
            f"- tasks_file: `{tasks_file_text}`",
            "",
        ]
        target_git_state = self._build_slice_target_git_state(Path(worktree_path))
        if target_git_state:
            lines.extend(["## Target Git State", *target_git_state, ""])
        current_slice = self._build_slice_current_slice(tasks_path)
        if current_slice:
            lines.extend(["## Current Build Slice", *current_slice, ""])
        current_requirement_excerpts = self._build_slice_current_requirement_excerpts(
            spec_dir=spec_dir,
            tasks_path=tasks_path,
        )
        if current_requirement_excerpts:
            lines.extend(
                ["## Current Requirement Excerpts", *current_requirement_excerpts, ""]
            )
        open_task_rows = self._build_slice_open_task_rows(tasks_path)
        if open_task_rows:
            lines.extend(["## Candidate Open Task Rows", *open_task_rows, ""])
        requirement_excerpts = self._build_slice_requirement_excerpts(
            spec_dir=spec_dir,
            tasks_path=tasks_path,
        )
        if requirement_excerpts:
            lines.extend(["## Referenced Requirement Excerpts", *requirement_excerpts, ""])
        adjacent_artifacts = self._build_slice_spec_adjacent_artifacts(
            spec_dir,
            workspace_root=Path(str(workspace_root)),
        )
        if adjacent_artifacts:
            lines.extend(
                ["## Spec-Adjacent Artifact Excerpts", *adjacent_artifacts, ""]
            )
        target_manifest_excerpts = self._build_slice_target_manifest_excerpts(
            Path(worktree_path)
        )
        if target_manifest_excerpts:
            lines.extend(
                ["## Target Manifest Excerpts", *target_manifest_excerpts, ""]
            )
        target_layout_excerpts = self._build_slice_target_layout_excerpts(
            Path(worktree_path)
        )
        if target_layout_excerpts:
            lines.extend(["## Target Layout Excerpts", *target_layout_excerpts, ""])
        quality_commands = self._build_slice_quality_commands()
        if quality_commands:
            lines.extend(["## Quality Commands", *quality_commands, ""])
        last_verify_failures = self._build_slice_last_verify_failures()
        if last_verify_failures:
            lines.extend(["## Last Verify Failures", *last_verify_failures, ""])
        if dirty_verify_block:
            lines.extend(["## Dirty Verify Artifacts", dirty_verify_block.strip(), ""])
        if implementation_target_contract:
            lines.extend([implementation_target_contract.strip(), ""])
        if progress_ledger_block:
            lines.extend([progress_ledger_block.strip(), ""])
        lines.extend(
            [
                "## Build Rules",
                "- Read/search/edit/test inside `worktree`.",
                "- Read spec inputs only for understanding; Ralph owns progress writes.",
                "- TECH WRITER may write `documentation-impact-report.md` under `spec_dir`.",
                "- DOCS VERIFIER may write `docs-verification-report.md` under `spec_dir`.",
                "- If the impact report requires documentation updates, IMPLEMENTER may update only `README.md` and `CHANGELOG.md` as specified by that report, then DOCS VERIFIER must re-validate the reports.",
                "- If all task IDs are complete but documentation reports are missing, run the documentation phases before reporting done.",
                "- Report completed progress through the harness build status marker.",
            ]
        )
        context_text = "\n".join(lines).rstrip() + "\n"
        context_file.write_text(context_text, encoding="utf-8")
        context_index_file = context_file.with_suffix(".json")
        sections = _markdown_section_headings(context_text)
        section_blocks = _markdown_section_blocks(context_text)
        agent_sections = _build_context_agent_sections(sections)
        agent_context_files = _write_build_agent_context_files(
            context_file=context_file,
            section_blocks=section_blocks,
            agent_sections=agent_sections,
        )
        context_index_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "strategy": self._strategy_id,
                    "markdown_path": str(context_file),
                    "spec_dir": spec_dir_text,
                    "spec_file": spec_file_text,
                    "tasks_file": tasks_file_text,
                    "sections": sections,
                    "agent_sections": agent_sections,
                    "agent_context_files": agent_context_files,
                    "section_blocks": section_blocks,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return context_file

    def _build_slice_quality_commands(self) -> list[str]:
        verify_command = str(self._config.verify_command or "").strip()
        if not verify_command:
            return []
        return [
            f"- verify_command: `{verify_command}`",
            "- Ralph executes this after your build slice; do not run it from the coding CLI.",
        ]

    def _build_slice_target_manifest_excerpts(
        self, worktree_path: Path, *, script_limit: int = 6
    ) -> list[str]:
        lines: list[str] = []
        package_json = worktree_path / "package.json"
        if package_json.is_file():
            try:
                manifest = json.loads(package_json.read_text(encoding="utf-8"))
            except Exception:
                manifest = None
            if isinstance(manifest, dict):
                name = _single_line(str(manifest.get("name") or "unknown"))
                version = _single_line(str(manifest.get("version") or "unknown"))
                lines.append(f"- package.json: name=`{name}`, version=`{version}`")

                package_manager = _detect_package_manager(worktree_path)
                if package_manager:
                    manager_name, lockfile = package_manager
                    lines.append(
                        f"  - package_manager: `{manager_name}` (lockfile: `{lockfile}`)"
                    )

                pinned_manager = manifest.get("packageManager")
                if isinstance(pinned_manager, str) and pinned_manager.strip():
                    lines.append(f"  - packageManager (declared): `{_single_line(pinned_manager)}`")
                engines = manifest.get("engines")
                if isinstance(engines, dict):
                    for tool, constraint in sorted(engines.items())[:script_limit]:
                        if isinstance(constraint, str):
                            lines.append(
                                f"  - engine {_single_line(tool)}: `{_single_line(constraint)}`"
                            )

                for field in ("main", "module", "types"):
                    value = _single_line(str(manifest.get(field) or ""))
                    if value:
                        lines.append(f"  - {field}: `{value}`")

                package_bin = manifest.get("bin")
                if isinstance(package_bin, str):
                    command = _single_line(package_bin)
                    if command:
                        lines.append(f"  - bin: `{command}`")
                elif isinstance(package_bin, dict):
                    for bin_name in sorted(str(name) for name in package_bin.keys())[
                        :script_limit
                    ]:
                        command = _single_line(str(package_bin.get(bin_name) or ""))
                        if command:
                            lines.append(f"  - bin {bin_name}: `{command}`")

                dependency_names = _manifest_dependency_names(manifest, "dependencies")
                if dependency_names:
                    lines.append("  - dependencies: " + ", ".join(dependency_names))

                dev_dependency_names = _manifest_dependency_names(
                    manifest, "devDependencies"
                )
                if dev_dependency_names:
                    lines.append(
                        "  - dev_dependencies: " + ", ".join(dev_dependency_names)
                    )

                scripts = manifest.get("scripts")
                if isinstance(scripts, dict):
                    for script_name in sorted(str(name) for name in scripts.keys())[
                        :script_limit
                    ]:
                        command = _single_line(str(scripts.get(script_name) or ""))
                        if command:
                            lines.append(f"  - script {script_name}: `{command}`")

        pyproject = worktree_path / "pyproject.toml"
        if pyproject.is_file():
            try:
                manifest = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            except Exception:
                manifest = None
            if isinstance(manifest, dict):
                project = manifest.get("project")
                if not isinstance(project, dict):
                    project = {}
                name = _single_line(str(project.get("name") or "unknown"))
                version = _single_line(str(project.get("version") or "unknown"))
                lines.append(f"- pyproject.toml: name=`{name}`, version=`{version}`")

                python_package_manager = _detect_python_package_manager(worktree_path)
                if python_package_manager:
                    manager_name, lockfile = python_package_manager
                    lines.append(
                        f"  - python_package_manager: `{manager_name}` (lockfile: `{lockfile}`)"
                    )

                dependency_names = _pyproject_dependency_names(project)
                if dependency_names:
                    lines.append("  - dependencies: " + ", ".join(dependency_names))

                optional_dependency_groups = project.get("optional-dependencies")
                if isinstance(optional_dependency_groups, dict):
                    group_names = sorted(str(name) for name in optional_dependency_groups.keys())[
                        :script_limit
                    ]
                    if group_names:
                        lines.append(
                            "  - optional_dependency_groups: " + ", ".join(group_names)
                        )

                project_scripts = project.get("scripts")
                if isinstance(project_scripts, dict):
                    for script_name in sorted(
                        str(name) for name in project_scripts.keys()
                    )[:script_limit]:
                        command = _single_line(str(project_scripts.get(script_name) or ""))
                        if command:
                            lines.append(f"  - script {script_name}: `{command}`")

                project_gui_scripts = project.get("gui-scripts")
                if isinstance(project_gui_scripts, dict):
                    for script_name in sorted(
                        str(name) for name in project_gui_scripts.keys()
                    )[:script_limit]:
                        command = _single_line(
                            str(project_gui_scripts.get(script_name) or "")
                        )
                        if command:
                            lines.append(f"  - gui-script {script_name}: `{command}`")

                tool = manifest.get("tool")
                if isinstance(tool, dict) and tool:
                    tool_names = sorted(_pyproject_tool_label(str(name)) for name in tool.keys())
                    lines.append(
                        "  - tool sections: " + ", ".join(tool_names[:script_limit])
                    )
        return lines

    def _build_slice_target_layout_excerpts(
        self, worktree_path: Path, *, entry_limit: int = 16
    ) -> list[str]:
        if not worktree_path.is_dir():
            return []
        ignored = {
            ".git",
            ".echelon",
            ".claude",
            ".venv",
            "__pycache__",
            "node_modules",
            "dist",
            "build",
            ".build",
            "coverage",
            "runs",
            "target",
            ".pytest_cache",
        }
        try:
            entries = [
                path
                for path in worktree_path.iterdir()
                if path.name not in ignored and not path.name.startswith(".DS_Store")
            ]
        except Exception:
            return []
        entries = sorted(entries, key=lambda path: path.name.lower())
        rendered = [_render_layout_entry(path) for path in entries[:entry_limit]]
        lines = []
        if rendered:
            lines.append("- top-level: " + ", ".join(rendered))

        doc_artifacts = _target_doc_artifacts(worktree_path)
        if doc_artifacts:
            lines.append("- docs: " + ", ".join(doc_artifacts))

        config_files = _target_config_files(worktree_path)
        if config_files:
            lines.append("- config files: " + ", ".join(config_files))

        source_dirs = _existing_named_dirs(
            worktree_path,
            ("src", "Sources", "lib", "app", "packages"),
        )
        source_files = _code_files_under_dirs(worktree_path, source_dirs)
        if source_dirs:
            lines.append("- source dirs: " + ", ".join(source_dirs))

        test_dirs = _existing_named_dirs(
            worktree_path,
            ("tests", "test", "__tests__", "Tests"),
        )
        test_files = _code_files_under_dirs(worktree_path, test_dirs)
        if test_dirs:
            lines.append("- test dirs: " + ", ".join(test_dirs))
        if source_files or test_files:
            lines.append(f"- file counts: source={len(source_files)}, test={len(test_files)}")
        if source_files:
            lines.append("- source files: " + ", ".join(source_files[:8]))
        if test_files:
            lines.append("- test files: " + ", ".join(test_files[:8]))
        return lines

    def _build_slice_target_git_state(
        self, worktree_path: Path, *, dirty_limit: int = 8
    ) -> list[str]:
        if not worktree_path.is_dir():
            return []
        branch = _current_git_branch(worktree_path)
        commit = _current_git_commit(worktree_path)
        recent_commits = _recent_git_commits(worktree_path)
        status_lines = _git_status_lines(worktree_path)
        if branch is None and commit is None and status_lines is None:
            return []

        lines: list[str] = []
        if branch:
            lines.append(f"- branch: `{branch}`")
        if commit:
            lines.append(f"- head: `{commit[:12]}`")
        if recent_commits:
            lines.append("- recent commits:")
            for entry in recent_commits:
                lines.append(f"  - {entry}")
        if status_lines is None:
            lines.append("- status: unavailable")
        elif not status_lines:
            lines.append("- status: clean")
        else:
            count = len(status_lines)
            noun = "path" if count == 1 else "paths"
            lines.append(f"- status: dirty ({count} {noun})")
            for entry in status_lines[:dirty_limit]:
                lines.append(f"  - {entry.strip()}")
            if count > dirty_limit:
                lines.append(f"  - ... {count - dirty_limit} more")
        return lines

    def _build_slice_current_slice(self, tasks_path: Path | None) -> list[str]:
        try:
            build = self._state_store.read().get("build")
        except Exception:
            return []
        if not isinstance(build, dict):
            return []

        task_ids = _clean_task_ids(build.get("current_task_ids"))
        current_task = str(build.get("current_task") or "").strip()
        if current_task and current_task not in task_ids:
            task_ids.append(current_task)
        target_task_ids = self._target_task_ids()
        if target_task_ids is not None:
            task_ids = [task_id for task_id in task_ids if task_id in target_task_ids]
        phase_group = str(build.get("current_phase_group") or "").strip()

        lines: list[str] = []
        if task_ids:
            lines.append("- current_task_ids: " + ", ".join(task_ids))
        if phase_group:
            lines.append(f"- current_phase_group: {phase_group}")
        rows, requirements = self._build_slice_task_rows_for_ids(tasks_path, task_ids)
        if requirements:
            lines.append("- current_requirements: " + ", ".join(requirements))
        for row in rows:
            lines.append(f"- current_task_row: {row}")
        return lines

    def _build_slice_task_rows_for_ids(
        self, tasks_path: Path | None, task_ids: list[str]
    ) -> tuple[list[str], list[str]]:
        if not task_ids or tasks_path is None or not tasks_path.is_file():
            return [], []
        try:
            tasks = parse_task_rows(
                tasks_path.read_text(encoding="utf-8", errors="replace")
            )
        except Exception:
            return [], []
        requested = set(task_ids)
        rows: list[str] = []
        requirements: list[str] = []
        for task in tasks:
            if task.task_id in requested:
                rows.append(_render_canonical_task_row(task))
                requirements.extend(
                    requirement
                    for requirement in task.requirements
                    if requirement != "UNMAPPED"
                )
        return rows, sorted(dict.fromkeys(requirements))

    def _build_slice_current_requirement_excerpts(
        self,
        *,
        spec_dir: Path | None,
        tasks_path: Path | None,
        limit: int = 5,
    ) -> list[str]:
        requirement_ids = set(self._build_slice_current_requirement_ids(tasks_path))
        if not requirement_ids:
            return []
        return self._build_slice_requirement_excerpts_for_ids(
            spec_dir=spec_dir,
            requirement_ids=requirement_ids,
            limit=limit,
        )

    def _build_slice_current_requirement_ids(self, tasks_path: Path | None) -> list[str]:
        try:
            build = self._state_store.read().get("build")
        except Exception:
            return []
        if not isinstance(build, dict):
            return []
        task_ids = _clean_task_ids(build.get("current_task_ids"))
        current_task = str(build.get("current_task") or "").strip()
        if current_task and current_task not in task_ids:
            task_ids.append(current_task)
        _rows, requirements = self._build_slice_task_rows_for_ids(tasks_path, task_ids)
        return requirements

    def _build_slice_last_verify_failures(self, *, limit: int = 5) -> list[str]:
        try:
            last_verify_result = self._state_store.read().get("last_verify_result")
        except Exception:
            return []
        if not isinstance(last_verify_result, dict):
            return []
        failures = last_verify_result.get("failures")
        if not isinstance(failures, list) or not failures:
            return []

        lines: list[str] = []
        for failure in failures[:limit]:
            if not isinstance(failure, dict):
                continue
            category = str(failure.get("category") or "other").strip() or "other"
            failure_id = str(failure.get("id") or "unknown").strip() or "unknown"
            error = _single_line(str(failure.get("error") or "").strip())
            if len(error) > 300:
                error = error[:297].rstrip() + "..."
            lines.append(f"- [{category}] {failure_id}: {error}")
        return lines

    def _build_slice_spec_adjacent_artifacts(
        self,
        spec_dir: Path | None,
        *,
        workspace_root: Path | None = None,
        contracts_limit: int = 5,
        adrs_limit: int = 5,
    ) -> list[str]:
        if spec_dir is None or not spec_dir.is_dir():
            return []
        candidates: list[tuple[str, Path]] = []
        seen_paths: set[Path] = set()
        for name in (
            "plan.md",
            "test-strategy.md",
            "data-model.md",
            "research.md",
            "constitution.md",
        ):
            path = spec_dir / name
            if path.is_file():
                candidates.append((name, path))
                seen_paths.add(path.resolve())
        if workspace_root is not None:
            from echelon.constitution import canonical_constitution_path

            canonical_constitution = canonical_constitution_path(workspace_root)
        else:
            canonical_constitution = None
        if (
            canonical_constitution is not None
            and canonical_constitution.is_file()
            and canonical_constitution.resolve() not in seen_paths
        ):
            candidates.append((
                str(canonical_constitution.relative_to(workspace_root)),
                canonical_constitution,
            ))
            seen_paths.add(canonical_constitution.resolve())
        contracts_dir = spec_dir / "contracts"
        if contracts_dir.is_dir():
            for path in sorted(contracts_dir.glob("*.md"))[:contracts_limit]:
                resolved = path.resolve()
                if resolved in seen_paths:
                    continue
                candidates.append((f"contracts/{path.name}", path))
                seen_paths.add(resolved)
        adrs_dir = spec_dir / "adrs"
        if adrs_dir.is_dir():
            for path in sorted(adrs_dir.glob("*.md"))[:adrs_limit]:
                resolved = path.resolve()
                if resolved in seen_paths:
                    continue
                candidates.append((f"adrs/{path.name}", path))
                seen_paths.add(resolved)

        lines: list[str] = []
        for label, path in candidates:
            excerpt = _first_meaningful_markdown_line(path)
            if not excerpt:
                continue
            lines.append(f"- {label}: `{path}`")
            lines.append(f"  - {excerpt}")
        return lines

    def _build_slice_requirement_excerpts(
        self,
        *,
        spec_dir: Path | None,
        tasks_path: Path | None,
        limit: int = 10,
    ) -> list[str]:
        requirement_ids = self._build_slice_open_requirement_ids(tasks_path)
        return self._build_slice_requirement_excerpts_for_ids(
            spec_dir=spec_dir,
            requirement_ids=requirement_ids,
            limit=limit,
        )

    def _build_slice_requirement_excerpts_for_ids(
        self,
        *,
        spec_dir: Path | None,
        requirement_ids: set[str],
        limit: int,
    ) -> list[str]:
        if spec_dir is None or not spec_dir.is_dir():
            return []
        if not requirement_ids:
            return []
        try:
            requirements = extract_canonical_requirements(spec_dir)
        except Exception:
            return []
        excerpts: list[str] = []
        seen: set[str] = set()
        for row in requirements:
            if row.id not in requirement_ids or row.id in seen:
                continue
            seen.add(row.id)
            excerpts.append(
                f"- {row.id} ({row.source_file}:{row.source_line}): {row.source_text}"
            )
            if len(excerpts) >= limit:
                break
        return excerpts

    def _build_slice_open_requirement_ids(self, tasks_path: Path | None) -> set[str]:
        if tasks_path is None or not tasks_path.is_file():
            return set()
        try:
            tasks = parse_task_rows(
                tasks_path.read_text(encoding="utf-8", errors="replace")
            )
        except Exception:
            return set()
        requirement_ids: set[str] = set()
        target_task_ids = self._target_task_ids()
        for task in tasks:
            if target_task_ids is not None and task.task_id not in target_task_ids:
                continue
            if task.status.strip().lower() == "x":
                continue
            requirement_ids.update(
                requirement for requirement in task.requirements if requirement != "UNMAPPED"
            )
        return requirement_ids

    def _build_slice_open_task_rows(
        self, tasks_path: Path | None, *, limit: int = 5
    ) -> list[str]:
        if tasks_path is None or not tasks_path.is_file():
            return []
        try:
            tasks = parse_task_rows(
                tasks_path.read_text(encoding="utf-8", errors="replace")
            )
        except Exception:
            return []
        rows: list[str] = []
        target_task_ids = self._target_task_ids()
        for task in tasks:
            if target_task_ids is not None and task.task_id not in target_task_ids:
                continue
            if task.status.strip().lower() == "x":
                continue
            rows.append(_render_canonical_task_row(task))
            if len(rows) >= limit:
                break
        return rows

    def _write_delivery_containment_policy(
        self,
        *,
        worktree_path: str,
        workspace_root: object,
        workspace_git_role: object,
        source_root: object,
        source_id: object,
        source_git_role: object,
        spec_dir: Path | None,
        allowed_context_roots: list[str],
        forbidden_source_roots: list[str],
    ) -> Path:
        """Write machine-readable delivery root boundaries for provider enforcement."""
        policy_file = self._state_store.state_dir / "delivery-containment-policy.json"
        spec_inputs = [str(spec_dir)] if spec_dir is not None else []
        forbidden_source_root_aliases = _forbidden_source_root_aliases(
            forbidden_source_roots,
            workspace_root=str(workspace_root),
        )
        policy = {
            "schema_version": 1,
            "worktree": str(worktree_path),
            "target_repo_worktree": str(worktree_path),
            "workspace_root": str(workspace_root),
            "workspace_git_role": str(workspace_git_role),
            "source_root": str(source_root),
            "source_id": str(source_id),
            "source_git_role": str(source_git_role),
            "state_dir": str(self._state_store.state_dir),
            "allowed_roots": {
                "implementation": [str(worktree_path)],
                "context": allowed_context_roots,
                "spec_inputs": spec_inputs,
                "harness_state": [str(self._state_store.state_dir)],
                "orchestration": [],
            },
            "forbidden_source_roots": forbidden_source_roots,
            "forbidden_source_root_aliases": forbidden_source_root_aliases,
            "rules": [
                "implementation reads, searches, edits, and tests must stay in worktree",
                "spec_inputs are read-only",
                "harness_state is Ralph-owned",
                "forbidden_source_roots must not be inspected, listed, searched, read, checked, looked at, or edited",
                "forbidden_source_roots must not be delegated to subagents",
            ],
        }
        policy_file.write_text(
            json.dumps(policy, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return policy_file

    def _forbidden_sibling_source_roots(
        self,
        *,
        workspace_root: object,
        source_root: object,
        allowed_context_roots: list[str] | None = None,
    ) -> list[str]:
        workspace_path = Path(str(workspace_root)).expanduser()
        source_path = Path(str(source_root)).expanduser()
        sources_dir = workspace_path / "sources"
        if not sources_dir.is_dir():
            return []
        try:
            resolved_source = source_path.resolve()
        except OSError:
            resolved_source = source_path.absolute()
        allowed_resolved = set()
        for allowed_root in allowed_context_roots or []:
            allowed_path = Path(allowed_root).expanduser()
            try:
                allowed_resolved.add(allowed_path.resolve())
            except OSError:
                allowed_resolved.add(allowed_path.absolute())

        forbidden: list[str] = []
        for candidate in sorted(path for path in sources_dir.iterdir() if path.is_dir()):
            try:
                resolved_candidate = candidate.resolve()
            except OSError:
                resolved_candidate = candidate.absolute()
            if resolved_candidate == resolved_source:
                continue
            if resolved_candidate in allowed_resolved:
                continue
            forbidden.append(str(candidate))
        return forbidden

    def _detect_forbidden_source_root_access(
        self,
        state: Dict[str, Any],
        build_result: Dict[str, Any],
    ) -> Optional[Dict[str, str]]:
        forbidden_roots = self._forbidden_sibling_source_roots(
            workspace_root=state.get("workspace_root") or "",
            source_root=state.get("source_root") or "",
            allowed_context_roots=_normalized_path_list(
                state.get("allowed_context_roots"),
                base_path=state.get("workspace_root") or "",
            ),
        )
        if not forbidden_roots:
            return None
        text = "\n".join(
            str(build_result.get(key) or "") for key in ("stdout", "stderr")
        )
        if not text.strip():
            return None
        match = _find_forbidden_source_root_in_tool_transcript(
            text,
            forbidden_roots,
            workspace_root=str(state.get("workspace_root") or ""),
        )
        if match is not None:
            root, line = match
            return {
                "workspace_root": str(state.get("workspace_root") or ""),
                "source_root": str(state.get("source_root") or ""),
                "forbidden_root": root,
                "matched_line": line,
            }
        return None

    def _detect_forbidden_harness_source_access(
        self,
        build_result: Dict[str, Any],
        *,
        worktree_path: str,
    ) -> Optional[Dict[str, str]]:
        forbidden_roots = _forbidden_harness_source_roots(Path(worktree_path))
        if not forbidden_roots:
            return None
        text = "\n".join(
            str(build_result.get(key) or "") for key in ("stdout", "stderr")
        )
        if not text.strip():
            return None
        match = _find_forbidden_root_in_tool_transcript(text, forbidden_roots)
        if match is not None:
            root, line = match
            return {
                "worktree": str(worktree_path),
                "forbidden_root": root,
                "matched_line": line,
            }
        for line in _iter_tool_transcript_lines(text):
            marker = _forbidden_harness_source_marker(line, Path(worktree_path))
            if marker:
                return {
                    "worktree": str(worktree_path),
                    "forbidden_root": marker,
                    "matched_line": line,
                }
        return None

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
        workspace_root = self._state_store.read().get("workspace_root")
        if workspace_root:
            return Path(str(workspace_root)).resolve()
        base_dir = getattr(self._gitops, "base_dir", None)
        if base_dir:
            return Path(base_dir).resolve()
        return (fallback or Path.cwd()).resolve()

    def _find_existing_spec_dir(self, worktree_path: str | Path) -> Path | None:
        """Find a spec for evidence validation without changing the candidate.

        Standard verification is already bound to a product fingerprint. Evidence
        gates therefore must never materialize a missing worktree-owned spec
        after that verification; doing so would invalidate the receipt they are
        about to consume.
        """
        worktree = Path(worktree_path)
        if self._spec_artifacts_mode() == "worktree":
            return self._find_spec_dir_in_root(worktree)

        state = self._state_store.read()
        state_spec_dir = state.get("spec_dir")
        if state_spec_dir:
            candidate = Path(str(state_spec_dir))
            if not candidate.is_absolute():
                candidate = self._orchestration_root(worktree) / candidate
            return candidate if candidate.is_dir() else None
        return find_spec_dir(self._spec_id, self._orchestration_root(worktree))

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

        from echelon.constitution import canonical_constitution_path

        orchestration_root = self._orchestration_root(worktree)
        source_constitution = canonical_constitution_path(orchestration_root)
        if source_constitution.exists():
            target_constitution = worktree / source_constitution.relative_to(orchestration_root)
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

    def _target_task_ids(self) -> set[str] | None:
        """Return the orchestrator-owned task scope for this source repo."""
        persisted = self._state_store.read().get("target_task_ids")
        if isinstance(persisted, list):
            task_ids = {
                str(task_id).strip()
                for task_id in persisted
                if str(task_id).strip()
            }
            if task_ids:
                return task_ids
        raw = os.environ.get("ECHELON_TARGET_TASK_IDS", "").strip()
        if not raw:
            return None
        return {task_id.strip() for task_id in raw.split(",") if task_id.strip()}

    def _implementation_target_contract_block(self, state: dict[str, object]) -> str:
        """Render the persisted target boundary supplied by Phase A dispatch."""
        implementation_target = str(state.get("implementation_target") or "").strip()
        if not implementation_target:
            return ""
        raw_declared = state.get("declared_targets")
        declared_targets = (
            [str(target).strip() for target in raw_declared if str(target).strip()]
            if isinstance(raw_declared, list)
            else []
        )
        assigned_task_ids = sorted(self._target_task_ids() or set())
        forbidden_targets = [
            target for target in declared_targets if target != implementation_target
        ]
        return (
            "## Implementation Target Contract\n"
            f"implementation_target: {implementation_target}\n"
            "declared_implementation_targets: "
            f"{','.join(declared_targets) or implementation_target}\n"
            f"assigned_task_ids: {','.join(assigned_task_ids) or 'none'}\n"
            "forbidden_implementation_targets: "
            f"{','.join(forbidden_targets) or 'none'}\n"
            "Implement only the assigned task IDs in the implementation target. "
            "Do not edit or implement work owned by another declared target.\n"
        )

    def _make_iter_prompt(self, base: str, outer_iter: int, last_failures: str) -> str:
        """Augment base prompt with iteration context for outer loop."""
        if not base:
            return ""
        convergence_context = self._convergence_high_water_context()
        if outer_iter == 0 or not last_failures:
            return f"{base}{convergence_context}"
        return (
            f"{base}\n\n"
            f"This is iteration {outer_iter}. "
            f"Previous build failed with:\n{last_failures}"
            f"{convergence_context}"
        )

    def _convergence_high_water_context(self) -> str:
        lease = self._convergence_lease()
        best = lease.best_snapshot
        if lease.last_outcome not in {"stalled", "regressed"} or best is None:
            return ""
        checkpoint = lease.best_checkpoint_commit or "unavailable"
        fingerprint = best.product_fingerprint[:12] or "unavailable"
        return (
            "\n\n## High-water convergence context\n"
            f"last outcome: {lease.last_outcome}\n"
            f"reason: {lease.last_reason}\n"
            f"best checkpoint: {checkpoint}\n"
            f"best fingerprint: {fingerprint}\n"
            f"completed tasks: {best.completed_tasks}/{best.total_tasks}\n"
            f"fulfillment debt: {best.fulfillment_debt}\n"
            f"blocking failure identities: {len(best.failure_keys)}\n"
            f"verification gate: {best.gate_rank}\n"
            "Recover or improve on that authoritative high-water evidence. "
            "Do not create report-only churn or weaken verification.\n"
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
            "Do not run `echelon spec verify`. "
            "Do not hand-edit `fulfillment-report.md` or `fulfillment-gaps.md`. "
            "If a failure mentions stale/scoped fulfillment evidence, treat it as "
            "read-only context and fix source/tests or stop after writing the harness status marker.\n\n"
            "Ralph owns browser verification execution. Browser or Playwright evidence "
            "must not be run from the coding CLI. Do not launch Chromium. Do not run "
            "Playwright or browser E2E commands there. Ralph will rerun the configured "
            "authoritative verifier after this repair. You may run focused non-browser "
            "checks that do not invoke a browser.\n\n"
            f"Inner fix {inner_iter}. "
            + (
                "The prior repair did not clear this failure: diagnose before editing. "
                "Reproduce the focused failing check and identify the actual failing "
                "component or browser hit target. For pointer/interactivity failures, "
                "inspect DOM hit-testing and stacking contexts; do not make speculative "
                "CSS or selector changes. Do not commit generated test traces or results.\n\n"
                if inner_iter >= 2
                else ""
            )
            + "Fix these verification failures without re-running the full build pipeline:\n"
            + failures_text
            + self._coverage_observation_repair_block(verify_result)
        )

    @staticmethod
    def _coverage_observation_repair_block(verify_result: VerifyResult) -> str:
        """Return bounded, harness-owned case-level repair guidance.

        Coverage observation is an evidence contract, so an aggregate failed
        requirement tells a provider too little to repair responsibly.  Pass
        only validated, redacted case debt generated by Ralph; never send a
        provider the mutable coverage map or raw reporter output as authority.
        """
        cases: list[tuple[str, str, str, str]] = []
        from harness.coverage_contract import is_coverage_case_id
        valid_types = {"unit", "integration", "e2e", "contract"}
        valid_statuses = {
            "unbound",
            "duplicate_binding",
            "invalid_report",
            "observer_missing",
            "failed",
            "skipped",
        }
        for failure in verify_result.failures:
            if failure.id != "coverage-observation-gaps":
                continue
            raw_cases = failure.details.get("test_cases")
            if not isinstance(raw_cases, Mapping):
                continue
            for raw_case_id, raw_case in raw_cases.items():
                case_id = str(raw_case_id).strip()
                if not is_coverage_case_id(case_id) or not isinstance(raw_case, Mapping):
                    continue
                test_type = str(raw_case.get("test_type") or "").strip()
                status = str(raw_case.get("status") or "").strip()
                if test_type not in valid_types or status not in valid_statuses:
                    continue
                reason = _compact_provider_note(raw_case.get("reason"), limit=280)
                cases.append((case_id, test_type, status, reason or status))
        if not cases:
            return ""

        lines = [
            "\n\n## Coverage Observation Repair Contract",
            "This is source-bound evidence debt, not an aggregate test-output failure. "
            "Do not edit the coverage map or weaken its required observations.",
            "Each listed case ID must appear in exactly one physical test identity. "
            "For an unbound case, implement the planned behavior and bind a real matching test; "
            "do not attach its tag to an unrelated test.",
            "Repair these exact observed case bindings:",
        ]
        for case_id, test_type, status, reason in sorted(cases)[:50]:
            lines.append(
                f"- `[echelon:{case_id}]` ({test_type}) — {status}: {reason}"
            )
        if len(cases) > 50:
            lines.append(f"- {len(cases) - 50} additional invalid case binding(s) omitted.")
        return "\n".join(lines)

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
        allow_without_task_progress: bool = False,
    ) -> Optional[Dict[str, Any]]:
        try:
            return self._checkpoint_progress_commit(
                worktree_path=worktree_path,
                before_state=before_state,
                after_state=after_state,
                outer_iter=outer_iter,
                inner_iter=inner_iter,
                phase=phase,
                allow_without_task_progress=allow_without_task_progress,
            )
        except Exception as exc:
            logger.warning("Could not create harness checkpoint commit: %s", exc)
            return None

    def _checkpoint_verification_deferred_candidate(
        self,
        worktree_path: str,
        *,
        outer_iter: int,
        inner_iter: int,
        phase: str,
    ) -> str:
        """Commit a neutral candidate without claiming task completion."""
        marker = Path(worktree_path) / BUILD_STATUS_FILENAME
        marker.unlink(missing_ok=True)
        if self._has_non_verify_worktree_changes(worktree_path):
            message = build_echelon_commit_message(
                (
                    f"harness-checkpoint: {self._spec_id}/{self._strategy_id} "
                    f"iter-{outer_iter} {phase} verification-deferred"
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
            reported_commit = self._gitops.commit(
                worktree_path, message, exclude_paths=_VERIFICATION_ARTIFACT_PATHS
            )
            commit = _current_git_commit(Path(worktree_path))
            if not commit or (
                reported_commit and str(reported_commit) != commit
            ):
                raise RuntimeError(
                    "verification-deferred checkpoint did not bind current HEAD"
                )
        else:
            commit = _current_git_commit(Path(worktree_path))
            if not commit:
                raise RuntimeError(
                    "verification-deferred candidate has no Git commit"
                )
        state = self._state_store.read()
        checkpoints = state.get("checkpoint_commits")
        if not isinstance(checkpoints, list):
            checkpoints = []
        checkpoints.append(
            {
                "commit": commit,
                "outer_iter": outer_iter,
                "inner_iter": inner_iter,
                "phase": phase,
                "task_ids": [],
                "provenance": "verification_deferred",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        state["checkpoint_commits"] = checkpoints
        self._state_store.write(state)
        return commit

    def _record_verification_environment_deferral(
        self,
        result: Mapping[str, object],
        *,
        commit: str,
        outer_iter: int,
        inner_iter: int,
        phase: str,
    ) -> None:
        state = self._state_store.read()
        deferrals = state.get("verification_environment_deferrals")
        if not isinstance(deferrals, list):
            deferrals = []
        deferrals.append(
            {
                "commit": commit,
                "outer_iter": outer_iter,
                "inner_iter": inner_iter,
                "phase": phase,
                "reason": str(result.get("build_reason") or ""),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        state["verification_environment_deferrals"] = deferrals
        self._state_store.write(state)

    def _checkpoint_progress_commit(
        self,
        *,
        worktree_path: str,
        before_state: Dict[str, Any],
        after_state: Dict[str, Any],
        outer_iter: int,
        inner_iter: int,
        phase: str,
        allow_without_task_progress: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Commit a dirty worktree after verified build progress.

        Stage 1 checkpointing records truthful metadata only: task IDs when
        state identifies newly completed tasks, otherwise phase/wave context.
        An explicitly successful invocation may preserve file-only finalization
        after all canonical task progress has already been recorded.
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

        if (
            after_completed <= before_completed
            and not phase_group
            and not allow_without_task_progress
        ):
            return None
        if not self._has_non_verify_worktree_changes(worktree_path):
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
        commit = self._gitops.commit(
            worktree_path, message, exclude_paths=_VERIFICATION_ARTIFACT_PATHS
        )
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
        from harness.task_progress import checkpoint_input_hash

        checkpoint["checkpoint_input_hash"] = checkpoint_input_hash(
            self._find_existing_spec_dir(worktree_path)
        )
        state = self._state_store.read()
        checkpoints = state.get("checkpoint_commits")
        if not isinstance(checkpoints, list):
            checkpoints = []
        checkpoints.append(checkpoint)
        state["checkpoint_commits"] = checkpoints
        self._state_store.write(state)
        if allow_without_task_progress and after_completed <= before_completed:
            branch = self._checkpoint_branch(worktree_path, outer_iter)
            self._gitops.push(worktree_path, branch)
        logger.info("Committed harness checkpoint %s for %s", commit[:12], label)
        return checkpoint

    def _checkpoint_branch(self, worktree_path: str, outer_iter: int) -> str:
        fallback = (
            f"harness/{self._spec_id}/{self._strategy_id}/iter-{outer_iter}"
        )
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return fallback
        return result.stdout.strip() or fallback

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


    def _all_canonical_tasks_complete(self, worktree_path: str) -> bool:
        spec_dir = self._find_spec_dir(worktree_path)
        if spec_dir is None:
            return False
        tasks_path = spec_dir / "tasks.md"
        if not tasks_path.exists():
            return False
        summary = summarize_task_progress(
            tasks_path.read_text(encoding="utf-8", errors="replace"),
            selected_task_ids=self._target_task_ids(),
        )
        return (
            summary.valid
            and summary.total_tasks > 0
            and summary.terminal_tasks >= summary.total_tasks
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
        adjudication = adjudicate_dirty_worktree(
            Path(worktree_path),
            llm_provider=self._llm_provider,
            exclude_paths=_VERIFICATION_ARTIFACT_PATHS,
        )
        if adjudication.status != "skipped":
            try:
                state = self._state_store.read()
                state["dirty_worktree_adjudication"] = adjudication.to_state_dict()
                self._state_store.write(state)
                self._append_dirty_adjudication_telemetry(
                    adjudication.telemetry_event,
                    state,
                )
            except Exception as state_exc:
                logger.warning(
                    "Could not persist dirty worktree adjudication: %s",
                    state_exc,
                )
        if adjudication.blocked:
            raise CommitPushError(
                "Dirty worktree adjudication blocked commit: "
                f"{adjudication.summary.get('blocked', 0)} blocked path(s), "
                f"{adjudication.summary.get('left', 0)} unresolved path(s)",
                branch=branch,
                worktree_path=worktree_path,
                stage="dirty_adjudication",
            )
        if self._has_non_verify_worktree_changes(worktree_path):
            try:
                self._gitops.commit(
                    worktree_path, message, exclude_paths=_VERIFICATION_ARTIFACT_PATHS
                )
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
                stage="push",
            ) from e

    def _append_dirty_adjudication_telemetry(
        self,
        event: dict[str, object],
        state: dict[str, Any],
    ) -> None:
        """Best-effort append of dirty adjudication evidence to run telemetry."""
        try:
            run_dir = self._state_store.state_dir.parent
            telemetry_dir = run_dir / "telemetry"
            telemetry_dir.mkdir(parents=True, exist_ok=True)
            enriched = dict(event)
            trace_id = state.get("telemetry_trace_id") or state.get("trace_id")
            if isinstance(trace_id, str) and trace_id:
                enriched["trace_id"] = trace_id
            enriched["spec_id"] = self._spec_id
            enriched["strategy_id"] = self._strategy_id
            enriched["run_id"] = state.get("run_id") or self._build_id
            with (telemetry_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(enriched, sort_keys=True, separators=(",", ":")))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception as exc:
            logger.warning("Could not append dirty adjudication telemetry: %s", exc)

    def _merge_verified_branch(
        self,
        worktree_path: str,
        branch: str,
        verify_result: Optional[VerifyResult],
        *,
        force: bool = False,
    ) -> bool:
        """Merge a verified delivery branch into the target default branch."""
        if verify_result is None or not verify_result.passed:
            return False

        if self._defer_target_merge and not force:
            try:
                state = self._state_store.read()
                state["target_merge"] = {
                    "status": "deferred",
                    "branch": branch,
                    "default_branch": self._gitops.get_default_branch(),
                    "verified": True,
                    "worktree_path": worktree_path,
                    "verify_result": _verify_to_dict(verify_result),
                }
                self._state_store.write(state)
                logger.info(
                    "Deferred verified delivery branch merge for %s until "
                    "downstream delivery gates pass",
                    self._spec_id,
                )
                return True
            except Exception as exc:
                logger.warning(
                    "Could not persist deferred target merge for %s: %s",
                    self._spec_id,
                    exc,
                )
                return False

        default_branch = None
        try:
            default_branch = self._gitops.get_default_branch()
            merge_result = self._gitops.local_merge(branch, self._spec_id)
            merge_evidence = merge_result if isinstance(merge_result, dict) else {}
            evidence: Dict[str, Any] = {
                "branch": branch,
                "default_branch": default_branch,
                "verified": True,
                "pushed": bool(merge_evidence.pop("pushed", True)),
            }
            evidence.update(merge_evidence)
            try:
                state = self._state_store.read()
                state["target_merge"] = evidence
                self._state_store.write(state)
            except Exception as state_exc:
                logger.warning("Could not persist target merge evidence: %s", state_exc)
            if merge_evidence.get("target_synced") is False:
                logger.warning(
                    "Published verified delivery branch %s into harness mirror %s "
                    "for %s; target checkout remains unsynced (%s)",
                    branch,
                    default_branch,
                    self._spec_id,
                    merge_evidence.get("target_sync_skip_reason") or "unknown reason",
                )
            else:
                logger.info(
                    "Merged verified delivery branch %s into %s for %s",
                    branch,
                    default_branch,
                    self._spec_id,
                )
            return True
        except Exception as exc:
            logger.warning(
                "Target default branch merge failed for %s -> %s: %s",
                branch,
                default_branch or "(unknown default)",
                exc,
            )
            try:
                state = self._state_store.read()
                state["target_merge"] = {
                    "branch": branch,
                    "default_branch": default_branch,
                    "verified": True,
                    "pushed": False,
                    "error": str(exc),
                    "worktree_path": worktree_path,
                }
                self._state_store.write(state)
            except Exception as state_exc:
                logger.warning("Could not persist target merge failure: %s", state_exc)
            return False

    def publish_verified_branch(
        self,
        worktree_path: str,
        branch: str,
        verify_result: Optional[VerifyResult],
    ) -> bool:
        """Publish a deferred Phase 1 candidate after downstream gates pass."""
        return self._merge_verified_branch(
            worktree_path,
            branch,
            verify_result,
            force=True,
        )

    def _commit_orchestration_spec_artifacts(
        self,
        worktree_path: str,
        outer_iter: int,
        *,
        branch: str,
    ) -> str | None:
        """Commit external workspace-owned spec artifacts after target convergence."""
        if self._spec_artifacts_mode() != "external":
            return None

        spec_dir = self._find_spec_dir(worktree_path)
        if spec_dir is None:
            return None

        root = self._orchestration_root(Path(worktree_path))
        try:
            spec_rel = spec_dir.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise CommitPushError(
                f"Spec dir {spec_dir} is outside orchestration root {root}",
                branch=branch,
                worktree_path=str(root),
                stage="orchestration_spec_artifacts",
            ) from exc

        status = subprocess.run(
            ["git", "status", "--porcelain", "--", str(spec_rel)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if status.returncode != 0:
            raise CommitPushError(
                f"Could not inspect orchestration spec artifacts: {status.stderr.strip()}",
                branch=branch,
                worktree_path=str(root),
                stage="orchestration_spec_artifacts",
            )
        if not status.stdout.strip():
            return None

        try:
            subprocess.run(
                ["git", "add", "-A", "--", str(spec_rel)],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            secret_scan = scan_git_staged(root)
            if not secret_scan.ok:
                raise RuntimeError(
                    "secret scan blocked orchestration spec commit: "
                    f"{secret_scan.format_summary()}"
                )
            staged = subprocess.run(
                ["git", "diff", "--cached", "--quiet", "--", str(spec_rel)],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if staged.returncode == 0:
                return None
            if staged.returncode not in {0, 1}:
                raise RuntimeError(staged.stderr.strip() or "git diff --cached failed")

            message = build_echelon_commit_message(
                f"chore: record delivery convergence for {self._spec_id}",
                EchelonCommitMetadata(
                    origin="delivery",
                    action="workspace-spec-convergence",
                    spec_id=self._spec_id,
                    run_id=self._build_id,
                    strategy=self._strategy_id,
                ),
            )
            subprocess.run(
                ["git", "commit", "-m", message, "--", str(spec_rel)],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            ).stdout.strip()
            logger.info(
                "Committed orchestration spec artifacts in %s: %s",
                root,
                head[:12],
            )
            return head
        except Exception as exc:
            raise CommitPushError(
                f"Could not commit orchestration spec artifacts: {exc}",
                branch=branch,
                worktree_path=str(root),
                stage="orchestration_spec_artifacts",
            ) from exc

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
        from harness.verification_stack_runtime import (
            build_verification_sandbox_spec,
        )

        return build_verification_sandbox_spec(
            self._config,
            worktree=Path(worktree_path),
            spec_id=self._spec_id,
            strategy_id=self._strategy_id,
            run_id=str(outer_iter),
        )

    def _append_iteration_log(
        self,
        state: Dict[str, Any],
        outer_iter: int,
        inner_iter: int,
        phase: str,
        exit_code: int,
        passed: bool,
        duration_s: float,
        tokens: int | None,
        failure_signatures: Optional[List[str]] = None,
        provider_invocation: object = None,
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
        invocation = (
            dict(provider_invocation)
            if type(provider_invocation) is dict
            else None
        )
        if invocation is not None:
            entry["provider_invocation"] = invocation
            invocation_count = int(fresh_state.get("provider_invocation_count", 0)) + 1
            fresh_state["provider_invocation_count"] = invocation_count
            if invocation.get("token_usage") is None:
                fresh_state["provider_token_usage_unknown_count"] = (
                    int(fresh_state.get("provider_token_usage_unknown_count", 0)) + 1
                )
        log.append(entry)
        fresh_state["iteration_log"] = log
        # Only update counters if they increase (monotonic invariant)
        if outer_iter > fresh_state.get("outer_iter", 0):
            fresh_state["outer_iter"] = outer_iter
        if inner_iter > fresh_state.get("inner_iter", 0):
            fresh_state["inner_iter"] = inner_iter
        self._state_store.write(fresh_state)
        if invocation is not None:
            self._append_delivery_provider_telemetry(
                invocation,
                phase=phase,
                invocation_index=invocation_count,
                state=fresh_state,
            )

    def _record_provider_attempt_summary(
        self,
        *,
        phase: str,
        attempt: int,
        result: Mapping[str, object],
        verify_result: VerifyResult,
        changed_files: Iterable[str],
    ) -> dict[str, object] | None:
        """Persist and render one fact-backed summary for an LLM attempt."""
        raw_invocation = result.get("provider_invocation")
        invocation = raw_invocation if isinstance(raw_invocation, Mapping) else None
        provider = str(invocation.get("provider") or "").strip() if invocation else ""
        if not provider:
            return None
        note = _compact_provider_note(str(result.get("stdout") or ""))
        failures = verify_result.failures or []
        primary_failure = _compact_failure_summary(failures[0]) if failures else ""
        summary: dict[str, object] = {
            "provider": provider,
            "phase": phase,
            "attempt": attempt,
            "outcome": "verification passed" if verify_result.passed else "verification failed",
            "changed_files": sorted(
                {
                    str(path).strip()
                    for path in changed_files
                    if str(path).strip() and not _is_verify_owned_artifact(str(path))
                }
            )[:8],
            "provider_note": note or "Provider did not return a completion note.",
            "primary_failure": primary_failure,
        }
        verification_evidence = verify_result.verification_evidence
        raw_playwright = (
            verification_evidence.get("playwright")
            if isinstance(verification_evidence, dict)
            else None
        )
        if isinstance(raw_playwright, dict):
            summary["playwright"] = {
                key: max(0, _safe_int(raw_playwright.get(key)))
                for key in ("total", "passed", "failed", "skipped")
            }
        evidence_gaps: list[str] = []
        for failure in failures:
            details = failure.details
            raw_gaps = details.get("gaps") if isinstance(details, dict) else None
            if not isinstance(raw_gaps, list):
                continue
            for gap in raw_gaps:
                if not isinstance(gap, dict):
                    continue
                requirement_id = str(gap.get("requirement_id") or "").strip()
                gap_status = str(gap.get("status") or "").strip()
                if requirement_id:
                    evidence_gaps.append(
                        f"{requirement_id} [{gap_status or 'UNRESOLVED'}]"
                    )
        if evidence_gaps:
            summary["evidence_gaps"] = evidence_gaps[:8]
        state = self._state_store.read()
        attempts = state.get("provider_attempts")
        if not isinstance(attempts, list):
            attempts = []
        attempts.append(summary)
        state["provider_attempts"] = attempts
        self._state_store.write(state)

        from echelon.ui import banner

        fields = [
            ("changed", ", ".join(summary["changed_files"]) or "no product files detected"),
            ("provider", str(summary["provider_note"])),
            ("verify", str(summary["outcome"])),
        ]
        if primary_failure:
            fields.append(("blocker", primary_failure))
        playwright = summary.get("playwright")
        if isinstance(playwright, dict):
            fields.append(
                (
                    "playwright",
                    (
                        f"{playwright.get('total', 0)} total, "
                        f"{playwright.get('passed', 0)} passed, "
                        f"{playwright.get('failed', 0)} failed, "
                        f"{playwright.get('skipped', 0)} skipped"
                    ),
                )
            )
        if evidence_gaps:
            fields.append(("evidence gaps", ", ".join(evidence_gaps[:8])))
        banner(
            f"{provider.upper()} {'BUILD' if phase == 'build' else 'REPAIR'} {attempt}",
            fields,
            subtitle=str(summary["outcome"]).capitalize(),
            file=sys.stderr,
        )
        return summary

    def _append_delivery_provider_telemetry(
        self,
        invocation: dict[str, object],
        *,
        phase: str,
        invocation_index: int,
        state: dict[str, Any],
    ) -> None:
        """Best-effort append of one content-free delivery provider invocation."""
        try:
            run_dir = self._state_store.state_dir.parent
            telemetry_dir = run_dir / "telemetry"
            telemetry_dir.mkdir(parents=True, exist_ok=True)
            event = {
                "schema_version": 1,
                "type": "delivery.provider_invocation",
                "event_time": datetime.now(timezone.utc).isoformat(),
                "run_id": state.get("run_id") or self._build_id,
                "spec_id": self._spec_id,
                "strategy_id": self._strategy_id,
                "phase": phase,
                "invocation_index": invocation_index,
                **invocation,
            }
            trace_id = state.get("telemetry_trace_id") or state.get("trace_id")
            if isinstance(trace_id, str) and trace_id:
                event["trace_id"] = trace_id
            with (telemetry_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception as exc:
            logger.warning("Could not append delivery provider telemetry: %s", exc)

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
    ) -> ImplementationResult:
        """Write phase evidence and return an implementation result."""

        try:
            state = self._state_store.read()
            if reason in _NON_CHARGEABLE_INFRASTRUCTURE_REASONS:
                state["convergence_lease"] = (
                    ConvergenceLease.from_state(state.get("convergence_lease"))
                    .with_infrastructure_attempt(reason)
                    .to_state()
                )
            state["tokens_used"] = tokens_used
            state["pr_url"] = pr_url
            state["termination_reason"] = reason
            state["branch"] = branch
            state["last_verify_result"] = (
                _verify_to_dict(final_verify) if final_verify else None
            )
            if reason != "publish_failed":
                state.pop("publication_failure", None)
            if extra_state:
                state.update(extra_state)
            self._state_store.write(state)
        except Exception as e:
            logger.warning("Failed to update final state: %s", e)

        return ImplementationResult(
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
    ) -> ImplementationResult:
        """Pause at a phase boundary (guided mode)."""
        logger.info("Paused at %s boundary (guided mode)", boundary)

        state = self._state_store.read()
        state["tokens_used"] = tokens_used
        state["pr_url"] = pr_url
        self._state_store.write(state)
        self._state_store.transition(
            "blocked", updates={"blocked_phase": "implementation"}
        )

        print(
            f"Paused at {boundary} boundary -- resume to continue",
            file=sys.stderr,
        )

        return ImplementationResult(
            status="blocked",
            termination_reason="blocker_escalation",
            outer_iterations=outer_iter + 1,
            inner_iterations=inner_iterations,
            pr_url=pr_url,
            tokens_used=tokens_used,
            final_verify=verify_result,
        )

    def _verified_publish_checkpoint(
        self,
        *,
        worktree_path: str,
        branch: str,
        stage: str,
        verify_result: Optional[VerifyResult],
    ) -> Optional[Dict[str, Any]]:
        """Capture the immutable evidence required for provider-free publication retry."""
        if (
            verify_result is None
            or not verify_result.passed
            or stage
            not in {
                "push",
                "target_merge",
                "orchestration_spec_artifacts",
                "pr",
            }
        ):
            return None
        commit = self._current_head(worktree_path)
        fingerprint = _safe_product_evidence_fingerprint(worktree_path)
        if not commit or not fingerprint:
            return None
        return {
            "schema_version": 1,
            "stage": stage,
            "worktree_path": worktree_path,
            "branch": branch,
            "commit": commit,
            "product_evidence_fingerprint": fingerprint,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }

    def _publish_checkpoint_state(
        self,
        *,
        worktree_path: str,
        branch: str,
        stage: str,
        verify_result: Optional[VerifyResult],
        error: BaseException | None = None,
    ) -> Optional[Dict[str, Any]]:
        checkpoint = self._verified_publish_checkpoint(
            worktree_path=worktree_path,
            branch=branch,
            stage=stage,
            verify_result=verify_result,
        )
        state: Dict[str, Any] = {}
        if checkpoint:
            state["verified_publish_checkpoint"] = checkpoint
        if error is not None:
            state["publication_failure"] = {
                "stage": stage,
                "error": str(error),
                "branch": branch,
                "worktree_path": worktree_path,
            }
        return state or None

    def resume_verified_publication(self) -> Optional[ImplementationResult]:
        """Retry verified publication effects without dispatching another build."""
        state = self._state_store.read()
        checkpoint = state.get("verified_publish_checkpoint")
        if not isinstance(checkpoint, dict):
            return None

        verify_data = state.get("last_verify_result")
        try:
            verify_result = VerifyResult.from_dict(verify_data)
        except Exception:
            self._invalidate_verified_publish_checkpoint(
                state, "verified_result_missing_or_invalid"
            )
            return None
        if not verify_result.passed:
            self._invalidate_verified_publish_checkpoint(
                state, "prior_verification_did_not_pass"
            )
            return None

        stage = str(checkpoint.get("stage") or "")
        worktree_path = str(checkpoint.get("worktree_path") or "")
        branch = str(checkpoint.get("branch") or "")
        commit = str(checkpoint.get("commit") or "")
        fingerprint = str(checkpoint.get("product_evidence_fingerprint") or "")
        if checkpoint.get("schema_version") != 1 or stage not in {
            "push",
            "target_merge",
            "orchestration_spec_artifacts",
            "pr",
        }:
            self._invalidate_verified_publish_checkpoint(state, "checkpoint_invalid")
            return None
        if not worktree_path or not Path(worktree_path).is_dir():
            self._invalidate_verified_publish_checkpoint(state, "worktree_missing")
            return None
        if not commit or self._current_head(worktree_path) != commit:
            self._invalidate_verified_publish_checkpoint(state, "verified_commit_changed")
            return None
        if (
            not fingerprint
            or _safe_product_evidence_fingerprint(worktree_path) != fingerprint
        ):
            self._invalidate_verified_publish_checkpoint(state, "product_evidence_changed")
            return None
        if not branch:
            self._invalidate_verified_publish_checkpoint(state, "branch_missing")
            return None

        outer_iterations = int(state.get("outer_iter") or 0)
        inner_iterations = int(state.get("inner_iter") or 0)
        tokens_used = int(state.get("tokens_used") or 0)
        pr_url = state.get("pr_url")

        if stage == "push":
            try:
                self._gitops.push(worktree_path, branch)
            except Exception as exc:
                logger.warning("Verified publication push retry failed: %s", exc)
                return self._finalize(
                    status="blocked",
                    reason="publish_failed",
                    outer_iterations=outer_iterations,
                    inner_iterations=inner_iterations,
                    pr_url=pr_url,
                    tokens_used=tokens_used,
                    final_verify=verify_result,
                    branch=branch,
                    extra_state={
                        "verified_publish_checkpoint": checkpoint,
                        "publication_failure": {
                            "stage": "push",
                            "error": str(exc),
                            "branch": branch,
                            "worktree_path": worktree_path,
                        },
                    },
                )
            stage = "target_merge"

        if stage == "target_merge":
            if not self._merge_verified_branch(worktree_path, branch, verify_result):
                checkpoint["stage"] = "target_merge"
                return self._finalize(
                    status="blocked",
                    reason="target_merge_failed",
                    outer_iterations=outer_iterations,
                    inner_iterations=inner_iterations,
                    pr_url=pr_url,
                    tokens_used=tokens_used,
                    final_verify=verify_result,
                    branch=branch,
                    extra_state={"verified_publish_checkpoint": checkpoint},
                )
            stage = "orchestration_spec_artifacts"

        if stage == "orchestration_spec_artifacts":
            try:
                self._commit_orchestration_spec_artifacts(
                    worktree_path,
                    max(outer_iterations - 1, 0),
                    branch=branch,
                )
            except CommitPushError as exc:
                checkpoint["stage"] = "orchestration_spec_artifacts"
                logger.warning("Verified orchestration publication retry failed: %s", exc)
                return self._finalize(
                    status="blocked",
                    reason="publish_failed",
                    outer_iterations=outer_iterations,
                    inner_iterations=inner_iterations,
                    pr_url=pr_url,
                    tokens_used=tokens_used,
                    final_verify=verify_result,
                    branch=branch,
                    extra_state={
                        "verified_publish_checkpoint": checkpoint,
                        "publication_failure": {
                            "stage": exc.stage,
                            "error": str(exc),
                            "branch": branch,
                            "worktree_path": worktree_path,
                        },
                    },
                )
            stage = "pr"

        try:
            pr_url = self._manage_pr(pr_url, branch, converged=True)
        except Exception as exc:
            checkpoint["stage"] = "pr"
            logger.warning("Verified PR publication retry failed: %s", exc)
            return self._finalize(
                status="blocked",
                reason="publish_failed",
                outer_iterations=outer_iterations,
                inner_iterations=inner_iterations,
                pr_url=pr_url,
                tokens_used=tokens_used,
                final_verify=verify_result,
                branch=branch,
                extra_state={
                    "verified_publish_checkpoint": checkpoint,
                    "publication_failure": {
                        "stage": "pr",
                        "error": str(exc),
                        "branch": branch,
                        "worktree_path": worktree_path,
                    },
                },
            )

        state = self._state_store.read()
        state.pop("verified_publish_checkpoint", None)
        state.pop("publication_failure", None)
        state["verified_publish_recovery"] = {
            "status": "completed",
            "commit": commit,
            "branch": branch,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        state["termination_reason"] = "converged"
        state["pr_url"] = pr_url
        state["branch"] = branch
        state["registered_worktree"] = worktree_path
        state["verified_commit"] = commit
        state["last_completed_phase"] = "implementation"
        self._state_store.write(state)
        return ImplementationResult(
            status="verified",
            termination_reason="converged",
            outer_iterations=outer_iterations,
            inner_iterations=inner_iterations,
            pr_url=pr_url,
            tokens_used=tokens_used,
            final_verify=verify_result,
            branch=branch,
        )

    def _invalidate_verified_publish_checkpoint(
        self, state: Dict[str, Any], reason: str
    ) -> None:
        checkpoint = state.pop("verified_publish_checkpoint", None)
        state["verified_publish_recovery"] = {
            "status": "invalidated",
            "reason": reason,
            "checkpoint": checkpoint,
            "invalidated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._state_store.write(state)

    def _handle_blocked_resume(
        self,
        state: Dict[str, Any],
        max_outer: int,
        max_inner: int,
        token_budget: Optional[int],
        build_command: str,
        strategy_context: str,
        build_prompt: str = "",
    ) -> ImplementationResult:
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
                return ImplementationResult(
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
                return ImplementationResult(
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
                resumed_state = self._state_store.transition("running")
                resumed_state["escalation_file"] = None
                self._state_store.write(resumed_state)
                print(
                    "[harness] continuing without escalation answer",
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
             "Run 'echelon delivery init' to auto-detect high-confidence verification, or add\n"
             "verify_command manually to echelon-config.yml, for example:\n\n"
             "  verify_command: swift test --package-path Packages/MyLib\n"
             "  verify_command: pytest\n"
             "  verify_command: go test ./..."),
            ("continue with", f"echelon delivery continue {spec_id}"),
            ("discard with", f"echelon delivery run {spec_id} --reset"),
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
            ("answer with", f'echelon delivery resume {spec_id} "<answer>"'),
            ("continue without answer", f"echelon delivery continue {spec_id}"),
            ("discard with", f"echelon delivery run {spec_id} --reset"),
        ],
        file=sys.stderr,
    )


def _clear_build_status(worktree_path: str) -> None:
    """Remove stale build result markers before a build iteration.

    Prevents a status file committed from a prior build on this branch from
    being read back as a successful completion of the current build.
    """
    try:
        (Path(worktree_path) / BUILD_STATUS_FILENAME).unlink(missing_ok=True)
        (Path(worktree_path) / ECHELON_RESULT_FILENAME).unlink(missing_ok=True)
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
    project = _git_top_level(project) or project
    status = _git_status_lines(project)
    if status is None:
        return None
    return {
        "project_dir": str(project),
        "before_status": status,
    }


def _snapshot_containment_projects(
    state: Dict[str, Any],
    project_dir: Any,
    worktree_path: str,
) -> List[Dict[str, Any]]:
    """Snapshot every git root whose drift would violate worktree isolation."""
    snapshots: List[Dict[str, Any]] = []
    seen: Set[Path] = set()
    for candidate in (
        project_dir,
        state.get("workspace_root"),
        state.get("source_root"),
    ):
        snapshot = _snapshot_project_status(candidate, worktree_path)
        if snapshot is None:
            continue
        try:
            resolved = Path(str(snapshot["project_dir"])).resolve()
        except OSError:
            resolved = Path(str(snapshot["project_dir"]))
        if resolved in seen:
            continue
        seen.add(resolved)
        snapshots.append(snapshot)
    return snapshots


def _detect_first_containment_violation(
    snapshots: List[Dict[str, Any]],
    worktree_path: str,
) -> Optional[Dict[str, Any]]:
    for snapshot in snapshots:
        violation = _detect_containment_violation(
            snapshot,
            snapshot.get("project_dir"),
            worktree_path,
        )
        if violation is not None:
            return violation
    return None


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
    project = _git_top_level(project) or project
    after = _git_status_lines(project)
    if after is None:
        return None
    before_lines = list(before.get("before_status") or [])
    changed_status = [
        line
        for line in _status_delta(before_lines, after)
        if not _is_allowed_external_documentation_status(line)
    ]
    if not changed_status:
        return None
    return {
        "project_dir": str(project),
        "worktree_path": str(worktree_path),
        "before_status": before_lines,
        "after_status": after,
        "changed_status": changed_status,
    }


def _git_top_level(project: Path) -> Optional[Path]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip())


def _is_allowed_external_documentation_status(status_line: str) -> bool:
    path = _status_path(status_line)
    if not path.startswith("specs/"):
        return False
    return PurePosixPath(path).name in {
        "documentation-impact-report.md",
        "docs-verification-report.md",
    }


def _status_path(status_line: str) -> str:
    line = status_line.strip()
    if not line:
        return ""
    path = status_line[3:].strip() if len(status_line) >= 4 else line
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path.strip('"').replace("\\", "/")


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


def _is_task_progress_incomplete(verify_result: VerifyResult) -> bool:
    return any(f.id == "task-progress-incomplete" for f in verify_result.failures)


def _is_fulfillment_freshness_failure(verify_result: VerifyResult) -> bool:
    return any(
        f.id in {"fulfillment-report-stale", "fulfillment-report-scoped"}
        for f in verify_result.failures
    )


def _is_provider_session_limit_verify_result(verify_result: VerifyResult) -> bool:
    return any(
        f.id == "fulfillment-refresh-provider-session-limit"
        for f in verify_result.failures
    )


def _is_sandbox_browser_runtime_unavailable(verify_result: VerifyResult) -> bool:
    return any(
        failure.category == FailureCategory.OTHER
        and failure.id == "sandbox-browser-runtime-unavailable"
        for failure in verify_result.failures
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
            ("next", f"echelon delivery continue {spec_id}  (retry verification after provider reset)"),
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


def _concrete_fulfillment_gap_fingerprint(
    verify_result: VerifyResult,
) -> str | None:
    """Fingerprint structured actionable gaps; ignore legacy aggregate failures."""
    if not _is_only_fulfillment_gaps(verify_result):
        return None
    gaps = verify_result.failures[0].details.get("gaps")
    if not isinstance(gaps, list) or not gaps:
        return None
    normalized: list[dict[str, str]] = []
    for raw in gaps:
        if not isinstance(raw, dict):
            return None
        normalized.append(
            {
                "requirement_id": str(raw.get("requirement_id") or "").strip(),
                "status": str(raw.get("status") or "").strip().upper(),
                "summary": re.sub(
                    r"\s+", " ", str(raw.get("summary") or "").strip()
                ),
                "recommended_action": re.sub(
                    r"\s+",
                    " ",
                    str(raw.get("recommended_action") or "").strip(),
                ),
            }
        )
    return json.dumps(
        sorted(normalized, key=lambda row: row["requirement_id"]),
        sort_keys=True,
        separators=(",", ":"),
    )


def _safe_product_evidence_fingerprint(worktree_path: str) -> str | None:
    if not worktree_path:
        return None
    try:
        return product_evidence_fingerprint(Path(worktree_path))
    except (OSError, ValueError):
        logger.warning(
            "Could not fingerprint bounded product evidence at %s",
            worktree_path,
            exc_info=True,
        )
        return None


def _output_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if value is None:
        return b""
    return str(value).encode("utf-8", errors="replace")


def _clean_task_ids(value: object) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(task_id).strip() for task_id in value if str(task_id).strip()]


def _compact_provider_note(value: object, *, limit: int = 360) -> str:
    """Keep provider text useful in normal output without exposing raw logs."""
    text = " ".join(
        redact_verification_text(str(value or ""), os.environ).split()
    )
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _completed_task_coverage_case_ids(tasks_path: Path | None) -> set[str] | None:
    """Return coverage cases owned by completed tasks in a partial delivery.

    ``None`` means the task ledger is complete and the full coverage map must
    be observed.  An empty set is meaningful for a partial ledger whose
    completed tasks declare no direct test ownership.
    """
    if tasks_path is None or not tasks_path.is_file():
        return None
    markdown = tasks_path.read_text(encoding="utf-8", errors="replace")
    summary = summarize_task_progress(markdown)
    if not summary.valid:
        return None
    if summary.terminal_tasks == summary.total_tasks:
        return None

    completed = {
        task_id
        for task_id, status in summary.task_statuses.items()
        if status in {"DONE", "DONE_WITH_CONCERNS", "DEGRADED"}
    }
    ownership = task_owned_coverage_case_ids(tasks_path)
    return {
        case_id
        for task_id in completed
        for case_id in ownership.get(task_id, set())
    }


def _compact_failure_summary(failure: object, *, limit: int = 360) -> str:
    """Prefer a named failed test over an arbitrary slice of verbose output."""
    error = redact_verification_text(str(getattr(failure, "error", "") or ""), os.environ)
    failure_id = str(getattr(failure, "id", "") or "").strip()
    for raw_line in error.splitlines():
        line = " ".join(raw_line.split())
        match = re.match(
            r"^(?:×|✗|✕|✘|FAIL(?:ED)?)\s+(.+)$",
            line,
            re.IGNORECASE,
        )
        if match is None:
            match = re.match(r"^(\[[^]]+\]\s+›\s+.+)$", line)
        if not match:
            continue
        detail = match.group(1).strip()
        rendered = f"{failure_id}: {detail}" if failure_id else detail
        return _compact_provider_note(rendered, limit=limit)
    return _compact_provider_note(error, limit=limit)


def _safe_int(value: object) -> int:
    """Normalize an evidence counter without trusting provider-authored types."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _is_verify_owned_artifact(path: str) -> bool:
    posix = path.replace("\\", "/")
    if posix.startswith(("test-results/", "playwright-report/", "blob-report/", "coverage/")):
        return True
    if posix.startswith("runs/verify-spec-"):
        return True
    if "/runs/verify-spec-" in posix:
        return True
    if not posix.startswith("specs/"):
        return False
    name = PurePosixPath(posix).name
    return name in {"fulfillment-report.md", "fulfillment-gaps.md"}


def _is_markerless_recovery_ignored_artifact(path: str) -> bool:
    posix = path.replace("\\", "/")
    if posix == BUILD_STATUS_FILENAME:
        return True
    if PurePosixPath(posix).name == "echelon_result.json":
        return True
    return _is_verify_owned_artifact(posix)


def _is_harness_or_spec_artifact(path: str) -> bool:
    posix = path.replace("\\", "/").strip()
    if _is_markerless_recovery_ignored_artifact(posix):
        return True
    return posix.startswith(("specs/", "runs/"))


def _has_target_delivery_changes(paths: Iterable[str]) -> bool:
    for raw_path in paths:
        path = str(raw_path).strip()
        if not path:
            continue
        if _is_harness_or_spec_artifact(path):
            continue
        return True
    return False


def _git_merge_base(worktree: Path, left: str, right: str) -> Optional[str]:
    result = subprocess.run(
        ["git", "merge-base", left, right],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _git_first_commit(worktree: Path) -> Optional[str]:
    result = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.splitlines()
    return value[-1].strip() if value else None


def _git_changed_files_between(
    worktree: Path,
    base: str,
    head: str,
) -> Optional[List[str]]:
    result = subprocess.run(
        ["git", "diff", "--name-only", base, head],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _status_delta(before: List[str], after: List[str]) -> List[str]:
    before_set = set(before)
    return [line for line in after if line not in before_set]


_PROVIDER_FILESYSTEM_TOOL_LABELS = (
    "Read",
    "NotebookRead",
    "NotebookEdit",
    "NotebookWrite",
    "Write",
    "Edit",
    "MultiEdit",
    "BashOutput",
    "Bash",
    "Shell",
    "Command",
    "Run",
    "Python",
    "Node",
    "JS",
    "JavaScript",
    "Grep",
    "Glob",
    "Find",
    "Search",
    "List",
    "LS",
    "Open",
    "View",
    "Show",
    "Display",
    "Print",
    "Dump",
    "Inspect",
    "Agent",
    "Task",
    "Subagent",
)

_FILESYSTEM_ACCESS_COMMANDS_BY_CATEGORY = {
    "shell_reader": (
        "cat",
        "rg",
        "grep",
        "find",
        "sed",
        "head",
        "tail",
        "less",
        "more",
        "awk",
        "nl",
        "wc",
        "file",
        "stat",
        "strings",
        "hexdump",
        "xxd",
        "od",
        "cmp",
        "diff",
    ),
    "path_inspection": (
        "fd",
        "locate",
        "tree",
        "ls",
        "du",
        "readlink",
        "realpath",
        "dirname",
        "basename",
    ),
    "vcs_and_network": (
        "git",
        "gh",
        "curl",
        "wget",
        "http",
        "https",
    ),
    "structured_data_processor": (
        "jq",
        "yq",
        "dasel",
        "xmllint",
    ),
    "editor_or_viewer": (
        "open",
        "vim",
        "vi",
        "nano",
        "emacs",
        "code",
    ),
    "shell_writer_or_metadata": (
        "tee",
        "touch",
        "mkdir",
        "rm",
        "rmdir",
        "chmod",
        "chown",
        "chgrp",
        "ln",
        "install",
        "truncate",
        "dd",
        "patch",
    ),
    "shell_execution": (
        "source",
        "bash",
        "sh",
        "zsh",
        "dash",
        "ksh",
        "fish",
        "env",
        "xargs",
    ),
    "test_build_runner": (
        "pytest",
        "tox",
        "nox",
        "coverage",
        "unittest",
        "ruff",
        "mypy",
        "eslint",
        "tsc",
        "npm",
        "pnpm",
        "yarn",
        "bun",
        "make",
        "just",
        "task",
        "go",
        "cargo",
        "swift",
        "xcodebuild",
        "gradle",
        "mvn",
    ),
    "file_transfer_or_archive": (
        "cp",
        "mv",
        "rsync",
        "ditto",
        "tar",
        "zip",
        "unzip",
        "gzip",
        "gunzip",
    ),
    "code_execution": (
        "python",
        "python3",
        "node",
        "deno",
        "ruby",
        "perl",
    ),
}


def _regex_union(values: Iterable[str]) -> str:
    return "|".join(re.escape(value) for value in values)


_FILESYSTEM_ACCESS_COMMANDS = tuple(
    command
    for commands in _FILESYSTEM_ACCESS_COMMANDS_BY_CATEGORY.values()
    for command in commands
)

_PROVIDER_FILESYSTEM_TOOL_LABEL_RE = _regex_union(_PROVIDER_FILESYSTEM_TOOL_LABELS)
_FILESYSTEM_ACCESS_COMMAND_RE = _regex_union(_FILESYSTEM_ACCESS_COMMANDS)

_TOOL_ACCESS_LINE_RE = re.compile(
    r"(?:"
    rf"▷\s*(?:{_PROVIDER_FILESYSTEM_TOOL_LABEL_RE})|"
    rf"\b(?:{_PROVIDER_FILESYSTEM_TOOL_LABEL_RE}):|"
    rf"\b(?:{_FILESYSTEM_ACCESS_COMMAND_RE})\s+"
    r")",
    re.IGNORECASE,
)

_HOST_HARNESS_SOURCE_MARKERS = (
    "/src/harness/ralph.py",
    "/src/harness/fulfillment_runner.py",
    "/src/harness/llm_build_runner.py",
    "/src/harness/gitops.py",
    "/src/kernel/fulfillment.py",
)

_HOST_HARNESS_SOURCE_PATH_RE = re.compile(
    r"\bsrc/(?:codegen|echelon|harness|hormone_calc|kernel|lexicon|understanding)(?:/[\w.-]+)+\.py\b"
)


def _looks_like_tool_access_line(line: str) -> bool:
    return bool(_TOOL_ACCESS_LINE_RE.search(line))


def _looks_like_tool_output_line(raw_line: str) -> bool:
    stripped = raw_line.strip()
    if not stripped:
        return False
    if stripped.startswith(("⎿", "…")):
        return True
    return raw_line.startswith(("  ", "    ", "\t"))


def _iter_tool_transcript_lines(text: str) -> Iterable[str]:
    in_tool_block = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            in_tool_block = False
            continue
        if _looks_like_tool_access_line(line):
            in_tool_block = True
            yield line
            continue
        if in_tool_block and _looks_like_tool_output_line(raw_line):
            yield line
            continue
        in_tool_block = False


def _find_forbidden_root_in_tool_transcript(
    text: str,
    forbidden_roots: Iterable[str],
) -> tuple[str, str] | None:
    roots = [root for root in forbidden_roots if root]
    if not roots:
        return None
    for line in _iter_tool_transcript_lines(text):
        for root in roots:
            if root in line:
                return root, line
    return None


def _find_forbidden_source_root_in_tool_transcript(
    text: str,
    forbidden_roots: Iterable[str],
    *,
    workspace_root: str,
) -> tuple[str, str] | None:
    aliases = _forbidden_source_root_aliases(
        forbidden_roots,
        workspace_root=workspace_root,
        include_absolute=True,
    )
    aliases_by_root: list[tuple[str, list[str]]] = []
    for root, root_aliases in aliases.items():
        aliases_by_root.append((root, root_aliases))
    if not aliases_by_root:
        return None
    for line in _iter_tool_transcript_lines(text):
        for root, aliases in aliases_by_root:
            if any(_line_contains_path_alias(line, alias) for alias in aliases):
                return root, line
    return None


def _forbidden_source_root_aliases(
    forbidden_roots: Iterable[str],
    *,
    workspace_root: str,
    include_absolute: bool = False,
) -> dict[str, list[str]]:
    workspace = Path(workspace_root).expanduser() if workspace_root else None
    aliases_by_root: dict[str, list[str]] = {}
    for root in forbidden_roots:
        if not root:
            continue
        aliases: list[str] = [root] if include_absolute else []
        if workspace is not None:
            try:
                relative = Path(root).expanduser().relative_to(workspace)
            except ValueError:
                relative = None
            if relative is not None and str(relative):
                relative_alias = str(relative)
                aliases.append(relative_alias)
                aliases.append(f"./{relative_alias}")
        aliases_by_root[root] = aliases
    return aliases_by_root


def _line_contains_path_alias(line: str, alias: str) -> bool:
    start = line.find(alias)
    while start != -1:
        end = start + len(alias)
        before_ok = start == 0 or line[start - 1] in " \t`'\"([{<"
        after_ok = end == len(line) or line[end] in "/\\ \t`'\".,:;)]}>"
        if before_ok and after_ok:
            return True
        start = line.find(alias, start + 1)
    return False


def _forbidden_harness_source_marker(line: str, worktree: Path) -> str | None:
    try:
        resolved_worktree = worktree.resolve()
    except OSError:
        resolved_worktree = worktree.absolute()
    harness_path_match = _HOST_HARNESS_SOURCE_PATH_RE.search(line)
    if harness_path_match:
        relative_marker = harness_path_match.group(0)
        if (resolved_worktree / relative_marker).exists():
            return None
        return f"host Echelon source outside worktree (/{relative_marker})"
    for marker in _HOST_HARNESS_SOURCE_MARKERS:
        relative_marker = marker.lstrip("/")
        if marker in line or relative_marker in line:
            if relative_marker and (resolved_worktree / relative_marker).exists():
                return None
            return f"host Echelon source outside worktree ({marker})"
    return None


def _forbidden_harness_source_roots(worktree: Path) -> list[str]:
    """Return host Echelon implementation roots that build agents must not inspect."""
    try:
        resolved_worktree = worktree.resolve()
    except OSError:
        resolved_worktree = worktree.absolute()
    try:
        harness_root = Path(__file__).resolve().parents[2]
    except (IndexError, OSError):
        return []

    # When Echelon itself is the target, the worktree copy of src/harness is
    # legitimate implementation code. The host checkout used to run Ralph is not.
    try:
        if harness_root == resolved_worktree or harness_root.is_relative_to(resolved_worktree):
            return []
    except OSError:
        pass
    return [str(harness_root)]


def _print_harness_source_containment_violation_banner(
    spec_id: str,
    strategy_id: str,
    violation: Dict[str, str],
) -> None:
    from echelon.ui import banner as _ui_banner

    _ui_banner(
        "HARNESS — HARNESS SOURCE CONTAINMENT VIOLATION",
        [
            ("spec", spec_id),
            ("strategy", strategy_id),
            ("worktree", violation.get("worktree", "")),
            ("forbidden_root", violation.get("forbidden_root", "")),
            (
                "why",
                "The LLM build transcript shows access to the host Echelon implementation source instead of the target worktree contract.",
            ),
            ("matched", violation.get("matched_line", "")),
            (
                "next",
                f"inspect the run output, then continue after confirming the build slice should use only harness-provided context: echelon delivery continue {spec_id}",
            ),
        ],
        file=sys.stderr,
    )


def _print_source_root_containment_violation_banner(
    spec_id: str,
    strategy_id: str,
    violation: Dict[str, str],
) -> None:
    from echelon.ui import banner as _ui_banner

    _ui_banner(
        "HARNESS — SOURCE ROOT CONTAINMENT VIOLATION",
        [
            ("spec", spec_id),
            ("strategy", strategy_id),
            ("source_root", violation.get("source_root", "")),
            ("forbidden_root", violation.get("forbidden_root", "")),
            (
                "why",
                "The LLM build transcript shows access to a sibling workspace source root outside the targeted build slice.",
            ),
            ("matched", violation.get("matched_line", "")),
            (
                "next",
                f"inspect the run output, then rerun after narrowing context: echelon delivery run {spec_id}",
            ),
        ],
        file=sys.stderr,
    )


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
                f"inspect/salvage the out-of-worktree changes, then rerun: echelon delivery run {spec_id}",
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




def _provider_limit_text(build_result: dict[str, object]) -> str:
    return "\n".join(
        str(build_result.get(key) or "")
        for key in ("stdout", "stderr", "build_reason", "reason")
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


def _render_canonical_task_row(task: TaskRow) -> str:
    parallel = " [P]" if task.parallel else ""
    requirements = ",".join(task.requirements) if task.requirements else "UNMAPPED"
    dependencies = ",".join(task.dependencies) if task.dependencies else "none"
    target = f" target={task.target}" if task.target else ""
    return (
        f"- [ ] {task.task_id}{parallel} complexity={task.complexity} "
        f"phase={task.phase} req={requirements} depends={dependencies}{target}"
    )


def _first_meaningful_markdown_line(path: Path, *, max_chars: int = 220) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if len(text) > max_chars:
            return text[: max_chars - 3].rstrip() + "..."
        return text
    return ""


def _single_line(text: str) -> str:
    return " ".join(text.split())


def _pyproject_tool_label(name: str) -> str:
    return name.split(".", 1)[0] if name.startswith("pytest.") else name


def _detect_package_manager(root: Path) -> tuple[str, str] | None:
    for lockfile, manager in (
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lockb", "bun"),
        ("package-lock.json", "npm"),
        ("npm-shrinkwrap.json", "npm"),
    ):
        if (root / lockfile).is_file():
            return manager, lockfile
    return None


def _detect_python_package_manager(root: Path) -> tuple[str, str] | None:
    for lockfile, manager in (
        ("uv.lock", "uv"),
        ("poetry.lock", "poetry"),
        ("pdm.lock", "pdm"),
        ("requirements.txt", "pip"),
    ):
        if (root / lockfile).is_file():
            return manager, lockfile
    return None


def _manifest_dependency_names(
    manifest: dict[str, Any],
    field: str,
    *,
    limit: int = 10,
) -> list[str]:
    value = manifest.get(field)
    if not isinstance(value, dict):
        return []
    return sorted(str(name) for name in value.keys())[:limit]


def _pyproject_dependency_names(project: dict[str, Any], *, limit: int = 10) -> list[str]:
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list):
        return []
    names: list[str] = []
    for dependency in dependencies:
        name = _python_requirement_name(str(dependency))
        if name:
            names.append(name)
    return sorted(names)[:limit]


def _python_requirement_name(requirement: str) -> str:
    text = requirement.strip()
    if not text:
        return ""
    text = text.split(";", 1)[0].strip()
    text = text.split("[", 1)[0].strip()
    match = re.match(r"([A-Za-z0-9_.-]+)", text)
    return match.group(1) if match else ""


def _render_layout_entry(path: Path) -> str:
    return f"{path.name}/" if path.is_dir() else path.name


def _existing_named_dirs(root: Path, names: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    seen_paths: set[Path | tuple[int, int]] = set()
    for name in names:
        path = root / name
        if path.is_dir():
            try:
                stat = path.stat()
                resolved: Path | tuple[int, int] = (stat.st_dev, stat.st_ino)
            except Exception:
                try:
                    resolved = path.resolve()
                except Exception:
                    resolved = path
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            found.append(f"{name}/")
    return found


def _code_files_under_dirs(
    root: Path,
    dirs: list[str],
    *,
    limit: int | None = None,
    max_depth: int = 3,
) -> list[str]:
    ignored_parts = {
        "__pycache__",
        "fixtures",
        "__fixtures__",
        "snapshots",
        "__snapshots__",
        "node_modules",
        "dist",
        "build",
        "coverage",
    }
    code_suffixes = {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".go",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".m",
        ".mm",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".swift",
        ".ts",
        ".tsx",
    }
    files: list[str] = []
    for rendered_dir in dirs:
        base = root / rendered_dir.rstrip("/")
        if not base.is_dir():
            continue
        try:
            candidates = sorted(base.rglob("*"), key=lambda path: str(path).lower())
        except Exception:
            continue
        for path in candidates:
            if not path.is_file() or path.suffix not in code_suffixes:
                continue
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            if len(relative.parts) - 1 > max_depth:
                continue
            if any(part in ignored_parts for part in relative.parts[:-1]):
                continue
            files.append(relative.as_posix())
            if limit is not None and len(files) >= limit:
                return files
    return files


def _target_config_files(root: Path, *, limit: int = 12) -> list[str]:
    exact_names = {
        "babel.config.js",
        "eslint.config.js",
        "jest.config.js",
        "jest.config.ts",
        "mypy.ini",
        "package.json",
        "playwright.config.js",
        "playwright.config.ts",
        "pytest.ini",
        "ruff.toml",
        "setup.cfg",
        "tsconfig.json",
        "tsconfig.test.json",
        "vite.config.js",
        "vite.config.ts",
        "vitest.config.js",
        "vitest.config.ts",
    }
    prefixes = ("jest.config.", "vitest.config.", "vite.config.", "playwright.config.")
    found: list[str] = []
    try:
        entries = list(root.iterdir())
    except Exception:
        return []
    for path in entries:
        if not path.is_file():
            continue
        name = path.name
        if name in exact_names or any(name.startswith(prefix) for prefix in prefixes):
            found.append(name)
    return sorted(set(found), key=str.lower)[:limit]


def _markdown_section_headings(text: str) -> list[str]:
    sections: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("## "):
            continue
        heading = stripped[3:].strip()
        if heading:
            sections.append(heading)
    return sections


def _markdown_section_blocks(text: str) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    current_heading: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current_heading = stripped[3:].strip()
            if current_heading:
                blocks.setdefault(current_heading, [])
            continue
        if current_heading is None or not stripped:
            continue
        blocks.setdefault(current_heading, []).append(line)
    return blocks


def _build_context_agent_sections(sections: list[str]) -> dict[str, list[str]]:
    available = set(sections)
    profiles = {
        "IMPLEMENTER": [
            "Roots",
            "Spec Inputs",
            "Current Build Slice",
            "Current Requirement Excerpts",
            "Candidate Open Task Rows",
            "Referenced Requirement Excerpts",
            "Spec-Adjacent Artifact Excerpts",
            "Target Manifest Excerpts",
            "Target Layout Excerpts",
            "Quality Commands",
            "Last Verify Failures",
            "Dirty Verify Artifacts",
            "Build Rules",
        ],
        "SPEC_GUARD": [
            "Spec Inputs",
            "Current Build Slice",
            "Current Requirement Excerpts",
            "Candidate Open Task Rows",
            "Referenced Requirement Excerpts",
            "Spec-Adjacent Artifact Excerpts",
            "Last Verify Failures",
            "Build Rules",
        ],
        "CODE_REVIEWER": [
            "Roots",
            "Current Build Slice",
            "Current Requirement Excerpts",
            "Target Manifest Excerpts",
            "Target Layout Excerpts",
            "Last Verify Failures",
            "Build Rules",
        ],
        "TEST_GUARDIAN": [
            "Roots",
            "Current Build Slice",
            "Current Requirement Excerpts",
            "Target Manifest Excerpts",
            "Target Layout Excerpts",
            "Quality Commands",
            "Last Verify Failures",
            "Build Rules",
        ],
        "TECH_WRITER": [
            "Roots",
            "Spec Inputs",
            "Current Build Slice",
            "Current Requirement Excerpts",
            "Referenced Requirement Excerpts",
            "Spec-Adjacent Artifact Excerpts",
            "Target Manifest Excerpts",
            "Target Layout Excerpts",
            "Build Rules",
        ],
        "DOCS_VERIFIER": [
            "Roots",
            "Spec Inputs",
            "Current Build Slice",
            "Current Requirement Excerpts",
            "Referenced Requirement Excerpts",
            "Spec-Adjacent Artifact Excerpts",
            "Target Manifest Excerpts",
            "Target Layout Excerpts",
            "Quality Commands",
            "Last Verify Failures",
            "Build Rules",
        ],
        "PROGRESS_TRACKER": [
            "Spec Inputs",
            "Current Build Slice",
            "Current Requirement Excerpts",
            "Candidate Open Task Rows",
            "Referenced Requirement Excerpts",
            "Last Verify Failures",
            "Build Rules",
        ],
        "INTEGRATOR": [
            "Roots",
            "Spec Inputs",
            "Current Build Slice",
            "Current Requirement Excerpts",
            "Spec-Adjacent Artifact Excerpts",
            "Target Manifest Excerpts",
            "Target Layout Excerpts",
            "Last Verify Failures",
            "Build Rules",
        ],
        "VISUAL_VALIDATOR": [
            "Roots",
            "Spec Inputs",
            "Current Build Slice",
            "Current Requirement Excerpts",
            "Target Manifest Excerpts",
            "Target Layout Excerpts",
            "Quality Commands",
            "Last Verify Failures",
            "Build Rules",
        ],
        "ENGINEERING_MANAGER": [
            "Roots",
            "Spec Inputs",
            "Current Build Slice",
            "Current Requirement Excerpts",
            "Candidate Open Task Rows",
            "Referenced Requirement Excerpts",
            "Spec-Adjacent Artifact Excerpts",
            "Target Manifest Excerpts",
            "Target Layout Excerpts",
            "Quality Commands",
            "Last Verify Failures",
            "Dirty Verify Artifacts",
            "Build Rules",
        ],
        "VERIFICATION": [
            "Roots",
            "Spec Inputs",
            "Current Build Slice",
            "Current Requirement Excerpts",
            "Referenced Requirement Excerpts",
            "Spec-Adjacent Artifact Excerpts",
            "Target Manifest Excerpts",
            "Target Layout Excerpts",
            "Quality Commands",
            "Last Verify Failures",
            "Build Rules",
        ],
    }
    return {
        agent_name: [section for section in profile if section in available]
        for agent_name, profile in profiles.items()
    }


def _write_build_agent_context_files(
    *,
    context_file: Path,
    section_blocks: dict[str, list[str]],
    agent_sections: dict[str, list[str]],
) -> dict[str, str]:
    context_files: dict[str, str] = {}
    context_dir = context_file.parent
    strategy_prefix = context_file.name.removesuffix("-build-slice-context.md")
    for agent_name, sections in agent_sections.items():
        agent_slug = agent_name.lower().replace("_", "-")
        agent_context_file = context_dir / f"{strategy_prefix}-{agent_slug}-context.md"
        lines = [
            f"# {agent_name} Context Pack",
            "",
            "This file is generated by Ralph from the build-slice context index.",
            "",
        ]
        for section in sections:
            block = section_blocks.get(section)
            if not block:
                continue
            lines.extend([f"## {section}", *block, ""])
        agent_context_file.write_text(
            "\n".join(lines).rstrip() + "\n",
            encoding="utf-8",
        )
        context_files[agent_name] = str(agent_context_file)
    return context_files


def _target_doc_artifacts(root: Path) -> list[str]:
    names = []
    for name in ("CHANGELOG.md", "docs", "LICENSE", "README.md"):
        path = root / name
        if path.is_dir():
            names.append(f"{name}/")
        elif path.is_file():
            names.append(name)
    return names


def _estimate_tokens(result: ExecResult) -> int:
    """Rough token estimate from ExecResult output length."""
    text_len = len(result.stdout) + len(result.stderr)
    return text_len // 4  # ~4 chars per token


def _known_token_count(value: object) -> int:
    """Return reported positive usage for budget arithmetic, else zero."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if value > 0 else 0


def _verify_to_dict(verify: VerifyResult) -> Dict[str, Any]:
    """Convert VerifyResult to dict for state storage."""
    return {
        "passed": verify.passed,
        "failures": [
            {
                "category": f.category.value,
                "id": f.id,
                "error": f.error,
                **({"details": f.details} if f.details else {}),
            }
            for f in verify.failures
        ],
        "duration_s": verify.duration_s,
        "token_usage": verify.token_usage,
        "verification_evidence": dict(verify.verification_evidence),
    }
