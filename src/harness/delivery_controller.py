"""Single-run Delivery controller."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from harness.paths import build_dir
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
from harness.product_inventory import product_evidence_fingerprint
from harness.verification_evidence import (
    VerificationEvidenceRef,
    validate_verification_receipt,
)
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
from harness.delivery_errors import DeliveryConfigurationError
from harness.spec_frontmatter import find_spec_dir, read_frontmatter, read_targets
from harness.task_progress import (
    TaskProgressError,
    summarize_task_progress,
    update_task_progress_markdown,
)
from harness.stacks.context import build_stack_context
from harness.stacks.renderer import resolved_to_dict
from harness.stacks.resolver import (
    ResolvedStacks,
    resolved_coverage_observer_plan_sha256,
    resolved_stack_contract_sha256,
)
from harness.visual_ralph import VisualRalphController
from harness.state import (
    DELIVERY_STATE_VERSION,
    StateStore,
    migrate_legacy_delivery_state,
)
from echelon.artifact_index import write_artifact_index
from harness.run_history import append_implementation_run
from harness.spec_frontmatter import write_status
from kernel.fulfillment import latest_fulfillment_report, read_fulfillment_metadata

logger = logging.getLogger(__name__)


def _split_env_list(raw: str | None) -> list[str]:
    """Parse a comma-separated orchestrator contract without empty entries."""
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def _delivery_stack_snapshot(resolved: object) -> dict[str, object] | None:
    """Freeze the stack-owned local-verification inputs for a fresh build.

    A delivery may resume for days while project configuration changes.  The
    local runner therefore consumes this persisted snapshot and its digests,
    rather than resolving the candidate's or target's current config again.
    """
    if not isinstance(resolved, ResolvedStacks):
        return None
    return {
        "schema_version": 1,
        "resolved": resolved_to_dict(resolved),
        "resolved_stack_hash": resolved_stack_contract_sha256(resolved),
        "observer_plan_hash": resolved_coverage_observer_plan_sha256(resolved),
    }


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
        serialized_failure = {
            "category": getattr(category, "value", str(category)),
            "id": str(getattr(failure, "id", "")),
            "error": str(getattr(failure, "error", "")),
        }
        details = getattr(failure, "details", None)
        if isinstance(details, dict) and details:
            serialized_failure["details"] = dict(details)
        failures.append(serialized_failure)
    serialized = {
        "passed": bool(getattr(result, "passed", False)),
        "failures": failures,
        "duration_s": float(getattr(result, "duration_s", 0.0)),
        "token_usage": int(getattr(result, "token_usage", 0)),
    }
    evidence = getattr(result, "verification_evidence", None)
    if isinstance(evidence, dict) and evidence:
        serialized["verification_evidence"] = dict(evidence)
    return serialized


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



class DeliveryController:
    """Own one durable Delivery run and its phase transitions."""

    def __init__(
        self,
        provider: SandboxProvider,
        gitops: Any,
        config: HarnessConfig,
        base_dir: str = ".",
        build_id: str = "",
        orchestration_root: str | Path | None = None,
        fresh_branch_base: str | None = None,
        fresh_completed_task_ids: tuple[str, ...] = (),
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
        self._escalation_dir = self._build_dir
        self._fresh_branch_base = fresh_branch_base
        self._fresh_completed_task_ids = tuple(fresh_completed_task_ids)
        self._state_store: StateStore | None = None

    def run(self, intent: RunIntent) -> DeliveryResult:
        """Run the one supported Delivery execution."""
        store = StateStore(self._state_dir, intent.spec_id, "default")
        existing = store.read()
        if (
            existing.get("status") == "blocked"
            and existing.get("escalation_file")
            and not intent.reset
            and not intent.resume
        ):
            escalation_handler = EscalationHandler(str(self._escalation_dir))
            escalation_file = str(existing["escalation_file"])
            if escalation_handler.check_resume(escalation_file) is None:
                print_escalation_sticky_banner(
                    intent.spec_id, "default", escalation_file
                )
                raise RuntimeError(
                    "delivery blocked — escalation pending. "
                    f"Run echelon delivery continue {intent.spec_id} if no answer "
                    "is needed, or run echelon delivery resume "
                    f'{intent.spec_id} "<answer>" to clarify; pass --reset to discard.'
                )
        return self._run_delivery(intent, budget=intent.token_budget)

    def state(self) -> dict[str, object]:
        """Return the current durable state for summaries and history."""
        return self._state_store.read() if self._state_store is not None else {}

    # === Private methods ===

    @staticmethod
    def _inherit_fresh_task_progress(
        *,
        state_store: StateStore,
        tasks_file: Path | None,
        task_ids: tuple[str, ...],
    ) -> None:
        """Restore checkpoint-owned progress before the next provider dispatch."""
        if not task_ids or tasks_file is None or not tasks_file.is_file():
            return
        markdown = tasks_file.read_text(encoding="utf-8", errors="replace")
        applied: list[str] = []
        for task_id in task_ids:
            try:
                updated = update_task_progress_markdown(markdown, task_id, "DONE")
            except TaskProgressError:
                continue
            if updated != markdown or f"- [x] {task_id}" in markdown:
                applied.append(task_id)
            markdown = updated
        if not applied:
            return
        tasks_file.write_text(markdown, encoding="utf-8")
        summary = summarize_task_progress(markdown)
        state = state_store.read()
        state["build"] = {
            "total_tasks": summary.total_tasks,
            "completed_tasks": summary.terminal_tasks,
            "tasks_completed_pct": (
                round(summary.terminal_tasks * 100 / summary.total_tasks)
                if summary.total_tasks
                else 0
            ),
            "task_results": {
                task_id: {"status": "DONE"} for task_id in applied
            },
        }
        state["inherited_checkpoint_task_ids"] = applied
        state_store.write(state)

    def _enabled_phases(self, llm_provider: AICodingCliProvider | None) -> list[str]:
        """Snapshot the delivery phases selected for a new run."""
        phases = ["implementation"]
        runnability = getattr(self._config, "resolved_runnability", None)
        stack_requires_visual = (
            str(getattr(runnability, "policy", "not_applicable")) == "required"
            and "browser_dom"
            in tuple(getattr(runnability, "required_observations", ()) or ())
        )
        if self._config.visual_tests.enabled or stack_requires_visual:
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
        final_verify = None
        persisted_verify = state.get("last_verify_result")
        if isinstance(persisted_verify, dict):
            try:
                final_verify = VerifyResult.from_dict(persisted_verify)
            except Exception:
                final_verify = None
        return ImplementationResult(
            status="verified",
            termination_reason=str(state.get("termination_reason") or "verified"),
            outer_iterations=int(state.get("outer_iter") or 0),
            inner_iterations=int(state.get("inner_iter") or 0),
            pr_url=state.get("pr_url"),
            tokens_used=int(state.get("tokens_used") or 0),
            final_verify=final_verify,
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

    @staticmethod
    def _downstream_candidate_changed(state: Dict[str, Any]) -> bool:
        """Detect an uncommitted provider repair left at a downstream block."""
        worktree_text = state.get("registered_worktree")
        expected = str(state.get("verified_product_fingerprint") or "")
        if not isinstance(worktree_text, str) or not worktree_text or not expected:
            return False
        try:
            current = product_evidence_fingerprint(Path(worktree_text))
        except (OSError, RuntimeError, ValueError):
            return False
        return current != expected

    @staticmethod
    def _git_commit_is_ancestor(
        worktree_path: Path, ancestor: str, descendant: str
    ) -> bool:
        """Return whether a verified candidate is retained by the final commit."""
        if not ancestor or not descendant:
            return False
        try:
            result = subprocess.run(
                [
                    "git", "-C", str(worktree_path), "merge-base", "--is-ancestor",
                    ancestor, descendant,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return False
        return result.returncode == 0

    def _verified_evidence_updates(
        self,
        *,
        spec_id: str,
        implementation: ImplementationResult,
        worktree_path: Path,
        verified_commit: str,
    ) -> Dict[str, Any]:
        """Capture host evidence that proves an equivalent final product."""
        verify = implementation.final_verify
        raw_evidence = getattr(verify, "verification_evidence", None)
        if not isinstance(raw_evidence, dict):
            return {}
        try:
            ref = VerificationEvidenceRef.from_mapping(raw_evidence)
            fingerprint = product_evidence_fingerprint(worktree_path)
        except (OSError, RuntimeError, ValueError):
            return {}
        validation = validate_verification_receipt(
            ref,
            candidate_commit=ref.candidate_commit,
            candidate_fingerprint=fingerprint,
        )
        if not validation.valid or not self._git_commit_is_ancestor(
            worktree_path, ref.candidate_commit, verified_commit
        ):
            return {}
        updates: dict[str, Any] = {
            "verified_evidence": ref.as_mapping(),
            "verified_product_fingerprint": fingerprint,
        }
        spec_dir = find_spec_dir(
            spec_id,
            self._orchestration_root or Path(self._base_dir).resolve(),
        )
        if spec_dir is not None:
            from harness.canonical_requirements import (
                canonical_requirement_fingerprint,
                extract_canonical_requirements,
            )
            from harness.fulfillment_runner import (
                _spec_input_hash,
                fulfillment_contract_hash,
            )
            from harness.verified_fulfillment_ledger import (
                read_verified_ledger,
                verified_fulfillment_ledger_path,
            )

            requirements = extract_canonical_requirements(spec_dir)

            updates.update(
                {
                    "verified_spec_input_hash": _spec_input_hash(spec_dir),
                    "verified_requirement_set_fingerprint": (
                        canonical_requirement_fingerprint(requirements)
                    ),
                    "verified_contract_hash": fulfillment_contract_hash(),
                    "verified_requirement_snapshot": [
                        {
                            "id": item.id,
                            "source_kind": item.source_kind,
                            "source_file": item.source_file,
                            "source_line": item.source_line,
                            "source_text": item.source_text,
                        }
                        for item in requirements
                    ],
                }
            )
            ledger_path = verified_fulfillment_ledger_path(spec_dir)
            if ledger_path.is_file():
                ledger = read_verified_ledger(ledger_path)
                contracts = {item.contract_hash for item in ledger.rows}
                if len(contracts) != 1 or not next(iter(contracts)):
                    # An immutable checkpoint must not relabel mixed or
                    # unbound rows as the currently configured verifier.
                    updates["verified_contract_hash"] = ""
                    return updates
                updates["verified_contract_hash"] = next(iter(contracts))
                updates["verified_fulfillment_rows"] = [
                    {
                        "requirement_id": item.requirement_id,
                        "status": item.status,
                        "evidence_refs": list(item.selected_evidence or item.evidence_refs),
                        "verified_at": item.verified_at,
                    }
                    for item in ledger.rows
                ]
        return updates

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
        updates = {
            "last_completed_phase": "implementation",
            "pr_url": implementation.pr_url,
            "registered_worktree": str(worktree_path) if worktree_path else None,
            "verified_commit": verified_commit,
        }
        updates.update(
            self._verified_evidence_updates(
                spec_id=spec_id,
                implementation=implementation,
                worktree_path=worktree_path,
                verified_commit=verified_commit,
            )
        )
        return updates

    def _has_equivalent_verified_provenance(
        self,
        *,
        state: Dict[str, Any],
        worktree_path: Path,
        recorded_commit: str,
        report_verified_commit: str,
    ) -> bool:
        """Allow only a descendant whose bounded product evidence is unchanged."""
        raw_evidence = state.get("verified_evidence")
        expected_fingerprint = str(state.get("verified_product_fingerprint") or "")
        if not isinstance(raw_evidence, dict) or not expected_fingerprint:
            return False
        try:
            ref = VerificationEvidenceRef.from_mapping(raw_evidence)
            current_fingerprint = product_evidence_fingerprint(worktree_path)
        except (OSError, RuntimeError, ValueError):
            return False
        if current_fingerprint != expected_fingerprint:
            return False
        validation = validate_verification_receipt(
            ref,
            candidate_commit=ref.candidate_commit,
            candidate_fingerprint=current_fingerprint,
        )
        return bool(
            validation.valid
            and report_verified_commit == ref.candidate_commit
            and self._git_commit_is_ancestor(
                worktree_path, ref.candidate_commit, recorded_commit
            )
        )

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
        diagnostic: str | None = None,
    ) -> DeliveryResult:
        """Persist a recoverable phase failure with its exact restart point."""
        state = state_store.read()
        effective_verify = (
            final_verify if final_verify is not None else implementation.final_verify
        )
        updates = {
            "blocked_phase": phase,
            "termination_reason": reason,
            "pr_url": implementation.pr_url,
            "outer_iter": max(int(state.get("outer_iter") or 0), outer_iterations),
            "tokens_used": max(int(state.get("tokens_used") or 0), tokens_used),
            "last_verify_result": _serialize_verify_result(effective_verify),
        }
        if diagnostic is not None:
            updates.update(build_status=reason, build_reason=diagnostic)
        state_store.transition("blocked", updates=updates)
        return DeliveryResult(
            status="blocked",
            termination_reason=reason,
            outer_iterations=outer_iterations,
            inner_iterations=implementation.inner_iterations,
            pr_url=implementation.pr_url,
            tokens_used=tokens_used,
            final_verify=effective_verify,
            blocked_phase=phase,  # type: ignore[arg-type]
            branch=implementation.branch,
        )

    @staticmethod
    def _publish_deferred_target(
        state_store: StateStore,
        implementation: ImplementationResult,
        publication_controller: RalphController | None,
    ) -> bool:
        """Publish the Phase 1 branch only when a deferred merge is recorded."""
        state = state_store.read()
        target_merge = state.get("target_merge")
        if not (
            isinstance(target_merge, dict)
            and target_merge.get("status") == "deferred"
        ):
            return True
        worktree_text = state.get("registered_worktree")
        deferred_branch = str(
            implementation.branch or target_merge.get("branch") or ""
        )
        if (
            publication_controller is None
            or not isinstance(worktree_text, str)
            or not worktree_text
            or not deferred_branch
        ):
            return False
        publish_verify = implementation.final_verify
        if publish_verify is None or not publish_verify.passed:
            persisted_verify = target_merge.get("verify_result")
            if isinstance(persisted_verify, dict):
                try:
                    publish_verify = VerifyResult.from_dict(persisted_verify)
                except Exception:
                    publish_verify = None
        return publication_controller.publish_verified_branch(
            worktree_text,
            deferred_branch,
            publish_verify,
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
        publication_controller: RalphController | None = None,
    ) -> DeliveryResult:
        """Own single-target lifecycle publication and terminal convergence."""
        state = state_store.read()
        if state.get("status") != "finalizing":
            state_store.transition("finalizing", updates={"blocked_phase": None})
        if len(declared_targets) != 1 and not self._publish_deferred_target(
            state_store, implementation, publication_controller
        ):
            return self._persist_phase_block(
                state_store,
                phase="finalization",
                reason="target_merge_failed",
                implementation=implementation,
                outer_iterations=outer_iterations,
                tokens_used=tokens_used,
                final_verify=final_verify,
            )
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
                exact_provenance = (
                    bool(verified_commit)
                    and verified_commit == recorded_commit
                    and persisted_verified_commit == recorded_commit
                    and persisted_verified_commit == verified_commit
                )
                equivalent_provenance = self._has_equivalent_verified_provenance(
                    state=state,
                    worktree_path=Path(worktree_text),
                    recorded_commit=recorded_commit,
                    report_verified_commit=verified_commit,
                )
                if not (exact_provenance or equivalent_provenance):
                    return self._persist_phase_block(
                        state_store,
                        phase="finalization",
                        reason="verified_provenance_mismatch",
                        implementation=implementation,
                        outer_iterations=outer_iterations,
                        tokens_used=tokens_used,
                        final_verify=final_verify,
                    )
                if not self._publish_deferred_target(
                    state_store, implementation, publication_controller
                ):
                    return self._persist_phase_block(
                        state_store,
                        phase="finalization",
                        reason="target_merge_failed",
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

    def _run_delivery(
        self,
        intent: RunIntent,
        budget: Optional[int],
    ) -> DeliveryResult:
        """Run the single durable Delivery loop."""
        strategy_id = "default"
        state_store = StateStore(self._state_dir, intent.spec_id, strategy_id)
        self._state_store = state_store

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
                resume_updates: dict[str, object] = {}
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
                    if self._downstream_candidate_changed(existing):
                        resume_phase = "implementation"
                        resume_updates["downstream_reentry"] = {
                            "from_phase": self._resume_phase(existing),
                            "reason": "candidate_changed_after_checkpoint",
                        }
                        existing = dict(existing)
                        existing["status"] = "running"
                        existing["blocked_phase"] = None
                resume_status = {
                    "implementation": "running",
                    "visual": "validating",
                    "review": "reviewing",
                    "finalization": "finalizing",
                }[resume_phase]
                if existing_status != resume_status or resume_updates:
                    state_store.transition(resume_status, updates=resume_updates)
            elif should_resume_blocked:
                logger.info(
                    "[%s/%s] Resuming from blocked state (outer=%s)",
                    intent.spec_id, strategy_id,
                    existing.get("outer_iter", 0),
                )
                resume_phase = self._resume_phase(existing)
                resume_updates = {}
                transitioned_for_reentry = False
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
                    if self._downstream_candidate_changed(existing):
                        downstream_phase = resume_phase
                        resume_phase = "implementation"
                        resume_updates["downstream_reentry"] = {
                            "from_phase": downstream_phase,
                            "reason": "candidate_changed_after_checkpoint",
                        }
                        state_store.transition(
                            {
                                "visual": "validating",
                                "review": "reviewing",
                            }[downstream_phase],
                            updates=resume_updates,
                        )
                        state_store.transition(
                            "running", updates={"blocked_phase": None}
                        )
                        transitioned_for_reentry = True
                        existing = dict(existing)
                        existing["status"] = "running"
                        existing["blocked_phase"] = None
                if not transitioned_for_reentry:
                    state_store.transition({
                        "implementation": "running",
                        "visual": "validating",
                        "review": "reviewing",
                        "finalization": "finalizing",
                    }[resume_phase], updates=resume_updates)
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
                    delivery_stack_snapshot=_delivery_stack_snapshot(
                        getattr(self._config, "resolved_stacks", None)
                    ),
                )
                state_store.transition("running")
                self._inherit_fresh_task_progress(
                    state_store=state_store,
                    tasks_file=tasks_file,
                    task_ids=self._fresh_completed_task_ids,
                )

            stack_context = self._build_stack_context(spec_dir)
            strategy_context = stack_context

            if llm_provider is None:
                raise DeliveryConfigurationError(
                    "Controlled delivery requires an enabled LLM provider"
                )
            arguments = f"spec {intent.spec_id} {intent.mode} mode"
            if intent.task_description:
                arguments += f"\n\n{intent.task_description}"
            if strategy_context:
                arguments += f"\n\n{strategy_context}"

            build_prompt: str | None = None
            initial_review_artifacts: tuple[Path, ...] = ()

            def get_build_prompt() -> str:
                """Return controller context only when a model step needs it."""
                nonlocal build_prompt
                if build_prompt is None:
                    resolved = arguments
                    if initial_review_artifacts:
                        resolved = self._build_reentry_prompt(
                            resolved, intent.spec_id, spec_dir=spec_dir,
                            published_artifacts=initial_review_artifacts,
                        )
                    build_prompt = resolved
                return build_prompt

            controller_state = state_store.read()
            downstream_reentry = controller_state.get("downstream_reentry")
            resume_repaired_worktree = (
                str(controller_state.get("registered_worktree") or "") or None
                if isinstance(downstream_reentry, dict)
                and downstream_reentry.get("reason")
                == "candidate_changed_after_checkpoint"
                and not downstream_reentry.get("consumed")
                else None
            )
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
                fresh_branch_base=self._fresh_branch_base,
                defer_target_merge=any(
                    phase in {"visual", "review"}
                    for phase in controller_state.get("enabled_phases", [])
                ),
                resume_worktree_path=resume_repaired_worktree,
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
                initial_review_artifacts = tuple(
                    Path(path) for path in pending_reentry["artifact_paths"]
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
                        build_command="echelon build",
                        strategy_context=strategy_context,
                        build_prompt=get_build_prompt(),
                    )
            else:
                implementation_result = self._implementation_from_state(state_store.read())
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
            # Phase 2 is harness-owned. A coding provider's self-reported browser
            # checks never substitute for deterministic sandbox Playwright evidence.
            visual_controller = (
                VisualRalphController(
                    provider=self._provider,
                    config=self._config,
                    spec_id=intent.spec_id,
                    strategy_id=strategy_id,
                    base_dir=self._base_dir,
                    build_id=self._build_id,
                    sandbox_spec_factory=lambda worktree: controller._build_sandbox_spec(
                        worktree, 0
                    ),
                    feedback_runner=lambda handle, worktree, verify, evidence_paths: (
                        controller.run_downstream_feedback(
                            handle=handle,
                            worktree_path=worktree,
                            verify_result=verify,
                            build_command="echelon build",
                            strategy_context=strategy_context,
                            build_prompt=get_build_prompt(),
                            phase="visual",
                            evidence_paths=tuple(evidence_paths),
                            token_budget=budget,
                            tokens_used=implementation_tokens + visual_tokens + verify.token_usage,
                        )
                    ),
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
                    controller.reuse_worktree_on_next_run(worktree_path)
                    reentry_usage_baseline = state_store.read().get("tokens_used", 0)
                    implementation_result = controller.run_loop(
                        max_outer=intent.max_outer,
                        max_inner=intent.max_inner,
                        token_budget=budget,
                        build_command="echelon build",
                        strategy_context=strategy_context,
                        build_prompt=get_build_prompt(),
                    )
                    implementation_outer_iterations += implementation_result.outer_iterations
                    implementation_tokens += max(0, implementation_result.tokens_used - reentry_usage_baseline)
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
            if visual_result is not None and visual_result.evidence is not None:
                visual_updates: dict[str, object] = {
                    "visual_evidence": visual_result.evidence.as_mapping(),
                }
                if visual_result.status == "passed":
                    visual_updates["last_completed_phase"] = "visual"
                state_store.transition("validating", updates=visual_updates)
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
                        # Ralph may be interrupted during the queued repair.
                        # Its durable baseline must already include triage;
                        # the re-entry delta below excludes that baseline.
                        current = state_store.read()
                        state_store.transition(current["status"], updates={
                            "tokens_used": max(
                                current.get("tokens_used", 0),
                                implementation_tokens + visual_tokens + review_tokens,
                            ),
                        })
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
                            get_build_prompt(),
                            intent.spec_id,
                            spec_dir=spec_dir,
                            published_artifacts=published_artifacts,
                        )
                        state_store.transition("running")
                        reentry_usage_baseline = state_store.read().get("tokens_used", 0)
                        implementation_result = controller.run_loop(
                            max_outer=intent.max_outer,
                            max_inner=intent.max_inner,
                            token_budget=budget,
                            build_command="echelon build",
                            strategy_context=strategy_context,
                            build_prompt=reentry_prompt,
                        )
                        implementation_outer_iterations += (
                            implementation_result.outer_iterations
                        )
                        implementation_tokens += max(0, implementation_result.tokens_used - reentry_usage_baseline)
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
                    publication_controller=controller,
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

        except DeliveryConfigurationError as exc:
            state = state_store.read()
            phase = {
                "running": "implementation",
                "validating": "visual",
                "reviewing": "review",
                "finalizing": "finalization",
            }.get(str(state.get("status")), "implementation")
            implementation = self._implementation_from_state(state)
            return self._persist_phase_block(
                state_store,
                phase=phase,
                reason="delivery_configuration_invalid",
                implementation=implementation,
                outer_iterations=implementation.outer_iterations,
                tokens_used=implementation.tokens_used,
                diagnostic=str(exc),
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

    def _build_reentry_prompt(
        self,
        base_prompt: str,
        spec_id: str,
        *,
        spec_dir: Path | None = None,
        published_artifacts: tuple[Path, ...] = (),
    ) -> str:
        """Augment controller context with this batch's canonical review artifacts."""
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
