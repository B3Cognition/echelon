"""Harness-owned execution controller for active workspace RE runs."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import tempfile
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from harness.re_architecture import (
    build_re_architecture_map,
    load_re_architecture_map,
    write_re_architecture_catalog,
)
from harness.re_lock import ReExtractLocked, ReExtractionLock
from harness.re_domain_manifest import (
    DOMAIN_PARTITION_VERSION,
    discover_source_domains,
    domain_manifest_path,
    load_domain_manifest,
    write_domain_manifest,
)
from harness.re_planner import ReExecutionPlan
from harness.re_quality_gate import (
    ReQualityReport,
    ReSourceQualityReport,
    quality_target_for_domain,
    validate_semantic_quality_review,
    validate_staged_re_domain_quality,
    validate_staged_re_quality,
    write_re_semantic_quality_report,
    write_re_source_quality_report,
    write_re_target_quality_report,
    write_re_quality_report,
    measure_source_quality,
)
from kernel.re_state import complete_dispatch, init_re_state, write_last_dispatch


class ReAgentProvider(Protocol):
    def exec_agent(self, project_root: str, prompt: str): ...


@dataclass(frozen=True)
class ReControllerResult:
    completed: bool
    blocked_reason: str | None = None
    blocked_detail: str | None = None


_PHASES = {
    "re-extract-1-analyze": "analyzer",
    "re-extract-2-specify": "specifier",
    "re-extract-3-verify": "verifier",
    "re-extract-4-expand": "expander",
    "re-extract-5-validate": "validator",
    "re-extract-6-checklist": "checklister",
    "re-extract-7-constitute": "constituter",
}
_PHASE_SPECS = {
    "re-extract-1-analyze": "re-extract-1-analyze.md",
    "re-extract-2-specify": "re-extract-2-specify.md",
    "re-extract-3-verify": "re-extract-3-verify.md",
    "re-extract-4-expand": "re-extract-4-expand.md",
    "re-extract-5-validate": "re-extract-5-validate.md",
    "re-extract-6-checklist": "re-extract-6-checklist.md",
    "re-extract-7-constitute": "re-extract-7-constitute.md",
}
_REPAIR_EPHEMERAL_OUTPUTS = frozenset(
    {
        "state.json",
        "echelon_result.json",
        "quality/deep-spec-gate.json",
    }
)
_ARCHITECTURE_OVERLAY_OUTPUTS = frozenset(
    {
        "workspace/architecture-map.json",
        "workspace/domain-catalog.md",
    }
)
_TARGET_QUALITY_PROTOCOL_VERSION = 1
_SEMANTIC_QUALITY_REVIEW_PROTOCOL_VERSION = 2


class ReExtractionController:
    """Execute staged RE phases with deterministic quality transitions."""

    def __init__(
        self,
        *,
        provider: ReAgentProvider,
        project_root: Path,
        run_dir: Path,
        extension_root: Path,
    ) -> None:
        self._provider = provider
        self._project_root = project_root.resolve()
        self._run_dir = run_dir.resolve()
        self._run_re_dir = self._run_dir / "re"
        self._extension_root = extension_root.resolve()
        self._reported_source_id: str | None = None

    def run(self) -> ReControllerResult:
        try:
            with ReExtractionLock.acquire(
                self._project_root,
                self._run_dir.name,
                self._run_dir,
            ):
                return self._run_locked()
        except ReExtractLocked:
            return ReControllerResult(
                completed=False,
                blocked_reason="re_extraction_locked",
            )

    def _run_locked(self) -> ReControllerResult:
        plan = self._load_plan()
        state = self._load_state()
        if self._migrate_workspace_source_convergence(state):
            self._save_state(state)
        if self._upgrade_source_convergence_quality_contract(state):
            self._save_state(state)
        if self._upgrade_source_coverage_repair_protocol(state, plan):
            self._save_state(state)
        if self._upgrade_semantic_quality_review_protocol(state):
            self._save_state(state)
        if self._apply_re_budget_override(state, plan):
            self._save_state(state)
        if (
            state.get("phase") == "re-extract-2-specify"
            and state.get("re_domain_partition_version") != DOMAIN_PARTITION_VERSION
        ):
            changed_sources, manifest_error = self._synchronize_domain_manifests(plan)
            if manifest_error is not None:
                return self._block(state, manifest_error)
            if changed_sources:
                migration_error = self._migrate_changed_domain_manifests(
                    state, plan, changed_sources
                )
                if migration_error is not None:
                    return self._block(state, migration_error)
            state["re_domain_partition_version"] = DOMAIN_PARTITION_VERSION
            self._save_state(state)
        if state.get("phase") not in {"re-extract-0-preflight", "re-extract-1-analyze"}:
            architecture_error = self._ensure_architecture_overlay(state, plan)
            if architecture_error is not None:
                return self._block(state, architecture_error)
        if state.get("status") == "blocked":
            state["status"] = "in_progress"
            state.pop("blocked_reason", None)
            self._save_state(state)
        protocol_error = self._ensure_target_quality_protocol(state, plan)
        if protocol_error is not None:
            return self._block(state, protocol_error)
        while True:
            phase = str(state.get("phase") or "re-extract-1-analyze")
            last_dispatch = state.get("last_dispatch")
            if (
                isinstance(last_dispatch, dict)
                and last_dispatch.get("phase_id") == phase
                and not last_dispatch.get("post_dispatch_complete", True)
            ):
                for snapshot_key in (
                    "re_quality_repair_snapshot",
                    "re_target_quality_repair_snapshot",
                ):
                    if snapshot_key not in state:
                        continue
                    snapshot_reason = self._repair_snapshot_failure(state, snapshot_key)
                    if snapshot_reason is not None:
                        return self._block(state, snapshot_reason)
            if phase == "re-extract-0-preflight":
                state["phase"] = "re-extract-1-analyze"
                self._save_state(state)
                continue
            if phase not in _PHASES:
                return self._block(state, "re_controller_unknown_phase")

            target: dict[str, object] | None = None
            if phase == "re-extract-2-specify":
                target = self._next_specification_target(state)
                if target is None:
                    next_result = self._advance(phase, state, plan)
                    if next_result is not None:
                        return next_result
                    state = self._load_state()
                    continue
                target_error = self._prepare_specification_target(state, target)
                if target_error is not None:
                    return self._block(state, target_error)
                if self._source_convergence_enabled(state):
                    self._report_source_start(state, plan, target)

            state = write_last_dispatch(state, phase, _PHASES[phase])
            self._save_state(state)
            if phase == "re-extract-1-analyze":
                analysis_error = self._run_analysis_script(plan)
                if analysis_error is not None:
                    state["re_analysis_error"] = analysis_error
                    return self._block(state, "re_analysis_script_failed")
                payload = self._analysis_result()
            else:
                result = self._provider.exec_agent(
                    str(self._project_root), self._prompt_for(phase, state, plan, target)
                )
                if phase == "re-extract-2-specify" and target is not None:
                    cleanup_error = self._clean_noncanonical_target_artifacts(
                        state, target, stage="post-dispatch"
                    )
                    if cleanup_error is not None:
                        return self._block(state, cleanup_error)
                if result.timed_out or result.exit_code != 0:
                    state["re_agent_result_detail"] = self._dispatch_failure_detail(
                        result.timed_out, result.exit_code
                    )
                    return self._block(state, "re_agent_dispatch_failed")
                payload = result.echelon_result
            if not isinstance(payload, dict):
                state["re_agent_result_detail"] = "missing result object"
                return self._block(state, "re_agent_result_invalid")
            if payload.get("verdict") == "BLOCKED":
                agent_block_detail = self._agent_block_detail(payload)
                state["re_agent_result_detail"] = agent_block_detail
                try:
                    # A parseable BLOCKED response completed the dispatch. Do
                    # not leave the compaction sentinel false and redispatch it
                    # as though the provider died mid-call.
                    state = complete_dispatch(state, {"state_updates": {}})
                except (KeyError, ValueError) as exc:
                    state["re_agent_result_detail"] = str(exc)
                    return self._block(state, "re_agent_result_invalid")
                print(
                    f"[re] agent blocked: {phase}; {agent_block_detail}",
                    flush=True,
                )
                if phase == "re-extract-2-specify" and target is not None:
                    for snapshot_key in (
                        "re_quality_repair_snapshot",
                        "re_target_quality_repair_snapshot",
                    ):
                        if snapshot_key not in state:
                            continue
                        snapshot_reason = self._repair_snapshot_failure(
                            state, snapshot_key
                        )
                        if snapshot_reason is not None:
                            return self._block(state, snapshot_reason)
                    target_result = self._evaluate_specification_target(
                        state,
                        plan,
                        target,
                        agent_block_detail=agent_block_detail,
                    )
                    if target_result is not None:
                        return target_result
                    self._save_state(state)
                    continue
                return self._block(
                    state, self._agent_blocked_reason(agent_block_detail)
                )
            if payload.get("verdict") != "DONE":
                state["re_agent_result_detail"] = (
                    f"unexpected verdict: {payload.get('verdict')!r}"
                )
                return self._block(state, "re_agent_result_invalid")
            try:
                state = complete_dispatch(
                    state, self._agent_result_without_controller_keys(payload, target)
                )
            except (KeyError, ValueError) as exc:
                state["re_agent_result_detail"] = str(exc)
                return self._block(state, "re_agent_result_invalid")
            state.pop("re_agent_result_detail", None)
            if phase == "re-extract-2-specify":
                for snapshot_key in (
                    "re_quality_repair_snapshot",
                    "re_target_quality_repair_snapshot",
                ):
                    if snapshot_key not in state:
                        continue
                    snapshot_reason = self._repair_snapshot_failure(state, snapshot_key)
                    if snapshot_reason is not None:
                        return self._block(state, snapshot_reason)
            if phase == "re-extract-2-specify" and target is not None:
                target_result = self._evaluate_specification_target(state, plan, target)
                if target_result is not None:
                    return target_result
                self._save_state(state)
                continue
            if phase == "re-extract-5-validate":
                semantic_report, semantic_error = validate_semantic_quality_review(
                    self._run_re_dir,
                    plan,
                    payload.get("semantic_quality_review")
                    if isinstance(payload, dict)
                    else None,
                )
                if semantic_error is not None or semantic_report is None:
                    error = semantic_error or "semantic quality review was unavailable"
                    attempts = (
                        self._metric(state, "re_semantic_review_invalid_attempts") + 1
                    )
                    state["re_semantic_review_invalid_attempts"] = attempts
                    state["re_semantic_review_invalid_error"] = error
                    state["re_agent_result_detail"] = error
                    if attempts >= self._metric(state, "max_validate_iterations"):
                        return self._block(state, "re_semantic_quality_review_invalid")
                    self._save_state(state)
                    continue
                state.pop("re_semantic_review_invalid_attempts", None)
                state.pop("re_semantic_review_invalid_error", None)
                if semantic_report.passed:
                    self._clear_semantic_quality_debt(state, plan)
                semantic_report_path = write_re_semantic_quality_report(
                    self._run_re_dir, semantic_report
                )
                state["re_semantic_quality_report"] = str(semantic_report_path)
                if not semantic_report.passed:
                    if self._source_convergence_enabled(state):
                        scheduled = self._schedule_source_semantic_repair(
                            state, plan, semantic_report
                        )
                        if scheduled is not None:
                            return scheduled
                        state = self._load_state()
                        continue
                    state["re_quality_gate_report"] = str(semantic_report_path)
                    scheduled = self._schedule_quality_repair(state, semantic_report)
                    if scheduled is not None:
                        return scheduled
                    state = self._load_state()
                    continue
            self._save_state(state)

            if phase == "re-extract-2-specify":
                continue

            next_result = self._advance(phase, state, plan)
            if next_result is not None:
                return next_result
            state = self._load_state()

    def _advance(
        self,
        phase: str,
        state: dict,
        plan: ReExecutionPlan,
    ) -> ReControllerResult | None:
        if phase == "re-extract-1-analyze":
            if state.get("re_domain_partition_version") != DOMAIN_PARTITION_VERSION:
                changed_sources, manifest_error = self._synchronize_domain_manifests(plan)
            else:
                changed_sources = set()
                manifest_error = self._ensure_domain_manifests(plan)
            if manifest_error is not None:
                return self._block(state, manifest_error)
            if changed_sources:
                migration_error = self._migrate_changed_domain_manifests(
                    state, plan, changed_sources
                )
                if migration_error is not None:
                    return self._block(state, migration_error)
            architecture_error = self._ensure_architecture_overlay(
                state, plan, rebuild=True
            )
            if architecture_error is not None:
                return self._block(state, architecture_error)
            state["re_domain_partition_version"] = DOMAIN_PARTITION_VERSION
            if self._source_convergence_enabled(state):
                self._initialize_source_convergence(state, plan)
            else:
                state["re_specification_targets"] = self._initial_specification_targets(plan)
            state["re_target_quality_protocol_version"] = (
                _TARGET_QUALITY_PROTOCOL_VERSION
            )
            state["re_workspace_synthesis_complete"] = False
            state["phase"] = "re-extract-2-specify"
        elif phase == "re-extract-2-specify":
            if self._source_convergence_enabled(state):
                return self._advance_source_convergence(state, plan)
            report = validate_staged_re_quality(self._run_re_dir, plan)
            report_path = write_re_quality_report(self._run_re_dir, report)
            state["re_quality_gate_report"] = str(report_path)
            if not report.passed:
                # Every target from the current repair pass has completed. A
                # remaining failure must start a new bounded pass with a new
                # snapshot; retaining an empty pending list would spin here.
                if state.get("re_quality_repair_pending"):
                    state.pop("re_quality_repair_pending", None)
                    state.pop("re_quality_repair_snapshot", None)
                return self._schedule_quality_repair(state, report)
            state.pop("re_quality_repair_pending", None)
            if not state.get("re_workspace_synthesis_complete"):
                state["re_specification_targets"] = [
                    {"kind": "workspace-synthesis"}
                ]
            else:
                state["phase"] = "re-extract-3-verify"
        elif phase == "re-extract-3-verify":
            if self._metric(state, "coverage_pct") < self._metric(state, "coverage_threshold"):
                iterations = self._metric(state, "verify_expand_iterations")
                if iterations >= self._metric(state, "max_verify_expand_iterations"):
                    return self._block(state, "re_coverage_threshold_not_met")
                state["verify_expand_iterations"] = iterations + 1
                state["phase"] = "re-extract-4-expand"
            else:
                state["phase"] = "re-extract-5-validate"
        elif phase == "re-extract-4-expand":
            state["phase"] = "re-extract-3-verify"
        elif phase == "re-extract-5-validate":
            state["phase"] = "re-extract-6-checklist"
        elif phase == "re-extract-6-checklist":
            state["phase"] = "re-extract-7-constitute"
        elif phase == "re-extract-7-constitute":
            state["status"] = "done"
            self._save_state(state)
            return ReControllerResult(completed=True)
        self._save_state(state)
        return None

    @staticmethod
    def _source_convergence_enabled(state: dict) -> bool:
        return (
            state.get("re_convergence_schema_version") == 1
            and isinstance(state.get("re_source_states"), dict)
        )

    @staticmethod
    def _migrate_workspace_source_convergence(state: dict) -> bool:
        """Move active workspace runs from global RE routing to source-local state."""
        if (
            state.get("mode") != "workspace"
            or ReExtractionController._source_convergence_enabled(state)
        ):
            return False
        state["re_convergence_schema_version"] = 1
        state["re_source_budgets"] = {
            "max_source_cycles": 5,
            "max_domain_repairs": 5,
            "max_source_reanalysis": 5,
        }
        state["re_source_states"] = {}
        # Existing active workspace runs predate the deep-by-default contract.
        # Migration must not preserve their former shallow thresholds.
        state["coverage_threshold"] = 99
        state["resolution_threshold"] = 99
        state["max_verify_expand_iterations"] = 5
        state["max_validate_iterations"] = 5
        state["re_source_convergence_quality_contract_version"] = 1
        state["phase"] = "re-extract-1-analyze"
        state["re_source_convergence_migrated"] = True
        for key in (
            "re_specification_targets",
            "re_quality_repair_pending",
            "re_quality_repair_snapshot",
            "re_target_quality_repair_snapshot",
            "re_domain_quality_attempts",
            "re_target_quality_protocol_version",
            "re_agent_result_detail",
        ):
            state.pop(key, None)
        return True

    @staticmethod
    def _upgrade_source_convergence_quality_contract(state: dict) -> bool:
        """Upgrade already-migrated runs from the former shallow defaults."""
        if (
            state.get("mode") != "workspace"
            or not ReExtractionController._source_convergence_enabled(state)
            or state.get("re_source_convergence_quality_contract_version") == 1
        ):
            return False
        state["coverage_threshold"] = 99
        state["resolution_threshold"] = 99
        state["max_verify_expand_iterations"] = 5
        state["max_validate_iterations"] = 5
        state["re_source_convergence_quality_contract_version"] = 1
        state.pop("re_agent_result_detail", None)
        return True

    @staticmethod
    def _upgrade_semantic_quality_review_protocol(state: dict) -> bool:
        """Clear stale validator-format failures after the evidence contract changes."""
        if state.get("re_semantic_quality_review_protocol_version") == (
            _SEMANTIC_QUALITY_REVIEW_PROTOCOL_VERSION
        ):
            return False
        state["re_semantic_quality_review_protocol_version"] = (
            _SEMANTIC_QUALITY_REVIEW_PROTOCOL_VERSION
        )
        for key in (
            "re_semantic_review_invalid_attempts",
            "re_semantic_review_invalid_error",
            "re_agent_result_detail",
        ):
            state.pop(key, None)
        return True

    def _initialize_source_convergence(
        self, state: dict, plan: ReExecutionPlan
    ) -> None:
        """Initialize controller-owned source lifecycle records after analysis."""
        source_states = state.get("re_source_states")
        if not isinstance(source_states, dict):
            source_states = {}
            state["re_source_states"] = source_states
        for source in plan.refresh_sources:
            source_states.setdefault(
                source.id,
                {
                    "status": "pending",
                    "source_cycles": 0,
                    "domain_repairs": {},
                    "source_reanalysis": 0,
                },
            )
        state["re_source_order"] = [source.id for source in plan.refresh_sources]
        state["re_source_coverage_repair_protocol_version"] = 1
        state.pop("re_active_source_id", None)
        state["re_specification_targets"] = []
        self._activate_next_source(state, plan)

    def _apply_re_budget_override(self, state: dict, plan: ReExecutionPlan) -> bool:
        """Raise source-local budgets and resume debt only when the limit increases."""
        try:
            outer_state = json.loads(
                (self._run_dir / "state.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        override = outer_state.get("re_max_inner")
        if not isinstance(override, int) or isinstance(override, bool) or override < 1:
            return False
        budgets = state.get("re_source_budgets")
        if not isinstance(budgets, dict):
            budgets = {}
            state["re_source_budgets"] = budgets
        changed = False
        for key in (
            "max_source_cycles",
            "max_domain_repairs",
            "max_source_reanalysis",
        ):
            existing = budgets.get(key)
            current = existing if isinstance(existing, int) and not isinstance(existing, bool) else 5
            if override > current:
                budgets[key] = override
                changed = True
        if changed:
            state["re_source_budget_override"] = override
            self._reclaim_quality_debt_for_budget_override(state, plan)
        return changed

    def _reclaim_quality_debt_for_budget_override(
        self, state: dict, plan: ReExecutionPlan
    ) -> None:
        """Return still-failing debt sources to their exact source-local repair queue.

        A higher `--re-max-inner` is an explicit operator decision to spend more
        source-local budget. Preserve counters already consumed under the former
        ceiling, measure the current staged output again, and queue only the
        unresolved domains. This leaves passed sources untouched and prevents a
        higher limit from silently restarting the whole workspace.
        """
        if not self._source_convergence_enabled(state):
            return
        source_states = state.get("re_source_states")
        order = state.get("re_source_order")
        if not isinstance(source_states, dict) or not isinstance(order, list):
            return

        pending_repairs = state.get("re_pending_source_repair_targets")
        if not isinstance(pending_repairs, dict):
            pending_repairs = {}
            state["re_pending_source_repair_targets"] = pending_repairs
        reclaimed: set[str] = set()
        for source_id in order:
            if not isinstance(source_id, str):
                continue
            source_state = source_states.get(source_id)
            if (
                not isinstance(source_state, dict)
                or source_state.get("status") != "partial_quality_debt"
            ):
                continue
            semantic_failures = self._quality_debt_semantic_failures(source_state)
            report = measure_source_quality(
                self._run_re_dir,
                plan,
                source_id,
                coverage_threshold=self._metric(state, "coverage_threshold"),
            )
            report_path = write_re_source_quality_report(self._run_re_dir, report)
            source_state["quality_report"] = str(report_path)
            source_state["coverage_pct"] = report.coverage_pct
            reclaimed.add(source_id)
            if report.passed and not semantic_failures:
                source_state["status"] = "passed"
                continue

            targets = self._source_repair_targets(
                plan,
                source_id,
                report.orphan_paths,
                semantic_failures or report.domain_failures,
            )
            if not targets:
                continue
            source_state["status"] = "pending"
            source_state["source_cycles"] = (
                self._source_counter(source_state, "source_cycles") + 1
            )
            source_state["quality_debt_reactivated_at_budget"] = self._source_budget(
                state, "max_source_cycles"
            )
            pending_repairs[source_id] = targets
            print(
                "[re] source budget recovery: "
                f"{source_id} - {report.coverage_pct:.1f}% coverage "
                f"({report.covered_file_count}/{report.eligible_file_count} files); "
                "resuming exact repair targets",
                flush=True,
            )

        if not reclaimed:
            return
        debt_sources = state.get("re_quality_debt_sources")
        if isinstance(debt_sources, list):
            state["re_quality_debt_sources"] = [
                source_id for source_id in debt_sources if source_id not in reclaimed
            ]
        if not pending_repairs:
            state.pop("re_pending_source_repair_targets", None)
            return
        active_source_id = state.get("re_active_source_id")
        active_state = (
            source_states.get(active_source_id)
            if isinstance(active_source_id, str)
            else None
        )
        if not isinstance(active_state, dict) or active_state.get("status") != "active":
            self._activate_next_source(state, plan)
            self._reported_source_id = None

    def _advance_source_convergence(
        self, state: dict, plan: ReExecutionPlan
    ) -> ReControllerResult | None:
        """Measure the active source and route its exact next repair action."""
        active_source_id = state.get("re_active_source_id")
        if isinstance(active_source_id, str) and active_source_id:
            report = measure_source_quality(
                self._run_re_dir,
                plan,
                active_source_id,
                coverage_threshold=self._metric(state, "coverage_threshold"),
            )
            report_path = write_re_source_quality_report(self._run_re_dir, report)
            source_state = self._source_state(state, active_source_id)
            source_state["quality_report"] = str(report_path)
            source_state["coverage_pct"] = report.coverage_pct
            self._report_source_measurement(report)
            if report.passed:
                source_state["status"] = "passed"
                self._report_source_ready(report, active_source_id, plan)
                state.pop("re_active_source_id", None)
                self._activate_next_source(state, plan)
                self._save_state(state)
                return None

            cycles = self._source_counter(source_state, "source_cycles")
            if cycles >= self._source_budget(state, "max_source_cycles"):
                self._report_source_quality_debt(report)
                self._mark_active_source_partial(state, active_source_id, report_path)
                self._activate_next_source(state, plan)
                self._save_state(state)
                return None

            source_state["source_cycles"] = cycles + 1
            state["re_specification_targets"] = self._source_repair_targets(
                plan, active_source_id, report.orphan_paths, report.domain_failures
            )
            if not state["re_specification_targets"]:
                return self._block(state, "re_source_quality_routing_failed")
            self._report_source_repair(
                active_source_id,
                self._source_counter(source_state, "source_cycles"),
                self._source_budget(state, "max_source_cycles"),
                state["re_specification_targets"],
            )
            state["phase"] = "re-extract-2-specify"
            self._save_state(state)
            return None

        if state.get("re_workspace_synthesis_complete"):
            state["phase"] = "re-extract-5-validate"
            self._save_state(state)
            return None
        self._activate_next_source(state, plan)
        self._save_state(state)
        return None

    def _report_source_start(
        self,
        state: dict,
        plan: ReExecutionPlan,
        target: dict[str, object],
    ) -> None:
        """Print one controller-owned progress marker for each source session."""
        source_id = target.get("source_id")
        if not isinstance(source_id, str) or source_id == self._reported_source_id:
            return
        source_state = self._source_state(state, source_id)
        domain_count = len(self._source_targets(plan, source_id))
        cycle = self._source_counter(source_state, "source_cycles") + 1
        budget = self._source_budget(state, "max_source_cycles")
        print(f"[re] source: {source_id}", flush=True)
        print(
            f"[re]   processing {domain_count} domain(s); source cycle {cycle}/{budget}",
            flush=True,
        )
        self._reported_source_id = source_id

    @staticmethod
    def _report_source_measurement(report: ReSourceQualityReport) -> None:
        """Print every deterministic source measurement, including failed ones."""
        print(
            "[re] source measured: "
            f"{report.source_id} - {report.coverage_pct:.1f}% coverage "
            f"({report.covered_file_count}/{report.eligible_file_count} files; "
            f"threshold {report.coverage_threshold}%)",
            flush=True,
        )

    @staticmethod
    def _report_source_repair(
        source_id: str,
        cycle: int,
        budget: int,
        targets: list[dict[str, object]],
    ) -> None:
        """Make the next deterministic source repair visible in the terminal."""
        domain_targets = sum(target.get("kind") == "source-domain" for target in targets)
        support_targets = sum(target.get("kind") == "source-support" for target in targets)
        details = [f"{domain_targets} domain repair target(s)"]
        if support_targets:
            details.append(f"{support_targets} support-artifact target(s)")
        print(
            "[re] source repair: "
            f"{source_id} - cycle {cycle}/{budget}; "
            + ", ".join(details),
            flush=True,
        )

    def _report_source_ready(
        self,
        report: ReSourceQualityReport,
        source_id: str,
        plan: ReExecutionPlan,
    ) -> None:
        domain_count = len(self._source_targets(plan, source_id))
        print(
            "[re] source ready: "
            f"{source_id} - {report.coverage_pct:.1f}% coverage "
            f"({report.covered_file_count}/{report.eligible_file_count} files); "
            f"{domain_count} domain spec(s) pass; semantic review pending",
            flush=True,
        )

    @staticmethod
    def _report_source_quality_debt(report: ReSourceQualityReport) -> None:
        issues: list[str] = []
        if report.orphan_paths:
            issues.append(f"{len(report.orphan_paths)} uncovered file(s)")
        if report.domain_failures:
            issues.append(f"{len(report.domain_failures)} incomplete domain spec(s)")
        detail = "; ".join(issues) if issues else "quality budget exhausted"
        print(
            "[re] source quality debt: "
            f"{report.source_id} - {report.coverage_pct:.1f}% coverage "
            f"({report.covered_file_count}/{report.eligible_file_count} files); {detail}",
            flush=True,
        )

    def _activate_next_source(self, state: dict, plan: ReExecutionPlan) -> None:
        """Queue domains for the next unfinished source, never a workspace union."""
        source_states = state.get("re_source_states")
        order = state.get("re_source_order")
        if not isinstance(source_states, dict) or not isinstance(order, list):
            return
        pending_repairs = state.get("re_pending_source_repair_targets")
        for source_id in order:
            if not isinstance(source_id, str):
                continue
            source_state = source_states.get(source_id)
            if not isinstance(source_state, dict) or source_state.get("status") != "pending":
                continue
            source_state["status"] = "active"
            state["re_active_source_id"] = source_id
            targets = (
                pending_repairs.pop(source_id, None)
                if isinstance(pending_repairs, dict)
                else None
            )
            state["re_specification_targets"] = (
                targets if isinstance(targets, list) else self._source_targets(plan, source_id)
            )
            if isinstance(pending_repairs, dict) and not pending_repairs:
                state.pop("re_pending_source_repair_targets", None)
            state["phase"] = "re-extract-2-specify"
            return
        state.pop("re_active_source_id", None)
        if not state.get("re_workspace_synthesis_complete"):
            state["re_specification_targets"] = [{"kind": "workspace-synthesis"}]
            state["phase"] = "re-extract-2-specify"

    def _source_targets(
        self, plan: ReExecutionPlan, source_id: str
    ) -> list[dict[str, object]]:
        manifest = load_domain_manifest(domain_manifest_path(self._run_re_dir, source_id))
        if not any(source.id == source_id for source in plan.refresh_sources):
            raise ValueError(f"source is not refreshable: {source_id}")
        return [
            {
                "kind": "source-domain",
                "source_id": source_id,
                "domain_id": domain.domain_id,
                "root": domain.root,
            }
            for domain in manifest.domains
        ]

    def _source_repair_targets(
        self,
        plan: ReExecutionPlan,
        source_id: str,
        orphan_paths: tuple[str, ...],
        failures: tuple[object, ...],
    ) -> list[dict[str, object]]:
        targets = self._source_targets(plan, source_id)
        wanted = {
            domain_id
            for failure in failures
            if isinstance(
                domain_id := (
                    failure.get("domain_id")
                    if isinstance(failure, dict)
                    else getattr(failure, "domain_id", None)
                ),
                str,
            )
        }
        owned_orphans: dict[str, list[str]] = {
            str(target["domain_id"]): [] for target in targets
        }
        unowned_orphans: list[str] = []
        for orphan in orphan_paths:
            owners = [
                target
                for target in targets
                if (
                    str(target["root"]) == "."
                    or orphan == str(target["root"])
                    or orphan.startswith(str(target["root"]) + "/")
                )
            ]
            if not owners:
                unowned_orphans.append(orphan)
                continue
            owner = max(owners, key=lambda target: len(str(target["root"])))
            domain_id = str(owner["domain_id"])
            owned_orphans[domain_id].append(orphan)
            wanted.add(domain_id)
        selected: list[dict[str, object]] = []
        for target in targets:
            domain_id = str(target["domain_id"])
            if domain_id not in wanted:
                continue
            repaired_target = dict(target)
            if owned_orphans[domain_id]:
                repaired_target["orphan_paths"] = owned_orphans[domain_id]
            selected.append(repaired_target)
        if unowned_orphans:
            selected.append(
                {
                    "kind": "source-support",
                    "source_id": source_id,
                    "orphan_paths": unowned_orphans,
                }
            )
        return selected or targets

    def _quality_debt_semantic_failures(self, source_state: dict) -> tuple[dict, ...]:
        """Load semantic debt recorded by current or pre-upgrade controller runs."""
        raw_failures = source_state.get("re_quality_debt_semantic_failures")
        if isinstance(raw_failures, list):
            return tuple(
                item
                for item in raw_failures
                if isinstance(item, dict) and isinstance(item.get("domain_id"), str)
            )
        report_path = source_state.get("quality_debt_report")
        if not isinstance(report_path, str):
            return ()
        try:
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return ()
        raw_failures = report.get("semantic_failures") if isinstance(report, dict) else None
        if not isinstance(raw_failures, list):
            return ()
        return tuple(
            item
            for item in raw_failures
            if isinstance(item, dict) and isinstance(item.get("domain_id"), str)
        )

    def _clear_semantic_quality_debt(
        self, state: dict, plan: ReExecutionPlan
    ) -> None:
        source_states = state.get("re_source_states")
        if not isinstance(source_states, dict):
            return
        for source in plan.refresh_sources:
            source_state = source_states.get(source.id)
            if isinstance(source_state, dict):
                source_state.pop("re_quality_debt_semantic_failures", None)

    def _upgrade_source_coverage_repair_protocol(
        self, state: dict, plan: ReExecutionPlan
    ) -> bool:
        """Give active legacy repair queues the source evidence they lacked."""
        if (
            not self._source_convergence_enabled(state)
            or state.get("re_source_coverage_repair_protocol_version") == 1
        ):
            return False
        state["re_source_coverage_repair_protocol_version"] = 1
        source_states = state.get("re_source_states")
        order = state.get("re_source_order")
        if isinstance(source_states, dict) and isinstance(order, list):
            recovered: list[tuple[str, ReSourceQualityReport]] = []
            for source_id in order:
                if not isinstance(source_id, str):
                    continue
                source_state = source_states.get(source_id)
                if not isinstance(source_state, dict) or source_state.get("status") not in {
                    "passed",
                    "partial_quality_debt",
                }:
                    continue
                report = measure_source_quality(
                    self._run_re_dir,
                    plan,
                    source_id,
                    coverage_threshold=self._metric(state, "coverage_threshold"),
                )
                report_path = write_re_source_quality_report(self._run_re_dir, report)
                source_state["quality_report"] = str(report_path)
                source_state["coverage_pct"] = report.coverage_pct
                if report.passed:
                    source_state["status"] = "passed"
                    continue
                source_state["status"] = "pending"
                source_state["source_cycles"] = 0
                source_state["domain_repairs"] = {}
                source_state["source_reanalysis"] = 0
                recovered.append((source_id, report))
            if recovered:
                for source_id, _report in recovered:
                    source_state = self._source_state(state, source_id)
                    source_state["status"] = "pending"
                active_source = state.get("re_active_source_id")
                if isinstance(active_source, str):
                    active_state = source_states.get(active_source)
                    if isinstance(active_state, dict) and active_state.get("status") == "active":
                        active_state["status"] = "pending"
                first_source, first_report = recovered[0]
                first_state = self._source_state(state, first_source)
                first_state["status"] = "active"
                state["re_active_source_id"] = first_source
                state["re_specification_targets"] = self._source_repair_targets(
                    plan,
                    first_source,
                    first_report.orphan_paths,
                    first_report.domain_failures,
                )
                state["phase"] = "re-extract-2-specify"
                debt_sources = state.get("re_quality_debt_sources")
                if isinstance(debt_sources, list):
                    state["re_quality_debt_sources"] = [
                        source_id
                        for source_id in debt_sources
                        if source_id not in {source for source, _report in recovered}
                    ]
                return True
        source_id = state.get("re_active_source_id")
        if not isinstance(source_id, str):
            return True
        source_state = self._source_state(state, source_id)
        if not isinstance(source_state.get("quality_report"), str):
            return True
        report = measure_source_quality(
            self._run_re_dir,
            plan,
            source_id,
            coverage_threshold=self._metric(state, "coverage_threshold"),
        )
        report_path = write_re_source_quality_report(self._run_re_dir, report)
        source_state["quality_report"] = str(report_path)
        source_state["coverage_pct"] = report.coverage_pct
        if report.passed:
            return True
        targets = self._source_repair_targets(
            plan, source_id, report.orphan_paths, report.domain_failures
        )
        if targets:
            state["re_specification_targets"] = targets
            state["phase"] = "re-extract-2-specify"
        return True

    @staticmethod
    def _source_state(state: dict, source_id: str) -> dict:
        source_states = state.get("re_source_states")
        if not isinstance(source_states, dict):
            raise ValueError("source convergence state is unavailable")
        source_state = source_states.get(source_id)
        if not isinstance(source_state, dict):
            raise ValueError(f"source convergence state is unavailable: {source_id}")
        return source_state

    @staticmethod
    def _source_counter(source_state: dict, key: str) -> int:
        value = source_state.get(key, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    @staticmethod
    def _source_budget(state: dict, key: str) -> int:
        budgets = state.get("re_source_budgets")
        value = budgets.get(key) if isinstance(budgets, dict) else None
        return value if isinstance(value, int) and not isinstance(value, bool) else 5

    def _mark_active_source_partial(
        self,
        state: dict,
        source_id: str,
        report_path: Path,
        *,
        semantic_failures: tuple[ReSpecQualityFailure, ...] = (),
    ) -> None:
        source_state = self._source_state(state, source_id)
        source_state["status"] = "partial_quality_debt"
        source_state["quality_debt_report"] = str(report_path)
        if semantic_failures:
            source_state["re_quality_debt_semantic_failures"] = [
                {"domain_id": failure.domain_id, "reason": failure.reason}
                for failure in semantic_failures
                if failure.domain_id
            ]
        state["re_specification_targets"] = []
        debt_sources = state.setdefault("re_quality_debt_sources", [])
        if isinstance(debt_sources, list) and source_id not in debt_sources:
            debt_sources.append(source_id)
        for key in (
            "re_quality_repair_pending",
            "re_quality_repair_snapshot",
            "re_target_quality_repair_snapshot",
            "re_target_quality_gate_report",
        ):
            state.pop(key, None)
        state.pop("re_active_source_id", None)

    def _schedule_source_semantic_repair(
        self,
        state: dict,
        plan: ReExecutionPlan,
        report: ReQualityReport,
    ) -> ReControllerResult | None:
        """Return semantic findings to their owning source before finalizing RE."""
        source_states = state.get("re_source_states")
        order = state.get("re_source_order")
        if not isinstance(source_states, dict) or not isinstance(order, list):
            return self._block(state, "re_source_semantic_routing_failed")
        for source_id in order:
            if not isinstance(source_id, str):
                continue
            source_state = source_states.get(source_id)
            if not isinstance(source_state, dict) or source_state.get("status") == "partial_quality_debt":
                continue
            failures = tuple(
                failure for failure in report.failures if failure.source_id == source_id
            )
            if not failures:
                continue
            targets = self._source_repair_targets(plan, source_id, (), failures)
            repairs = source_state.get("domain_repairs")
            if not isinstance(repairs, dict):
                repairs = {}
                source_state["domain_repairs"] = repairs
            exhausted = False
            for target in targets:
                domain_id = str(target["domain_id"])
                repair_count = self._metric(repairs, domain_id) + 1
                repairs[domain_id] = repair_count
                exhausted = exhausted or repair_count > self._source_budget(
                    state, "max_domain_repairs"
                )
            if exhausted:
                source_report = measure_source_quality(
                    self._run_re_dir,
                    plan,
                    source_id,
                    coverage_threshold=self._metric(state, "coverage_threshold"),
                    semantic_failures=failures,
                )
                report_path = write_re_source_quality_report(
                    self._run_re_dir, source_report
                )
                self._mark_active_source_partial(
                    state,
                    source_id,
                    report_path,
                    semantic_failures=failures,
                )
                return self._schedule_source_semantic_repair(state, plan, report)
            source_state["status"] = "active"
            state["re_active_source_id"] = source_id
            state["re_specification_targets"] = targets
            state["phase"] = "re-extract-2-specify"
            self._reported_source_id = None
            self._save_state(state)
            return None
        state["phase"] = "re-extract-6-checklist"
        self._save_state(state)
        return None

    def _ensure_target_quality_protocol(
        self,
        state: dict,
        plan: ReExecutionPlan,
    ) -> str | None:
        """Backfill per-domain validation before a legacy specification resume.

        Older runs produced several domain specs before target-level quality
        enforcement existed. Without this migration, they are first checked by
        the workspace-wide gate only after the remaining queue drains. A
        one-time scan makes every existing shallow or missing spec an immediate
        controller-owned target, while fresh runs mark the protocol when their
        queue is created.
        """
        if state.get("phase") != "re-extract-2-specify":
            return None
        if state.get("re_target_quality_protocol_version") == (
            _TARGET_QUALITY_PROTOCOL_VERSION
        ):
            return None

        report = validate_staged_re_quality(self._run_re_dir, plan)
        report_path = write_re_quality_report(self._run_re_dir, report)
        state["re_quality_gate_report"] = str(report_path)
        if not report.passed:
            targets = self._repair_specification_targets(report)
            if targets is None:
                return "re_domain_manifest_invalid"
            state["re_specification_targets"] = targets
            state["re_workspace_synthesis_complete"] = False
            # This is a protocol migration, not a failed repair pass. Reset
            # only target-local retries so the revised, executable validation
            # protocol gets one bounded chance to correct legacy output.
            state.pop("re_domain_quality_attempts", None)
            state.pop("re_target_quality_repair_snapshot", None)
        state["re_target_quality_protocol_version"] = (
            _TARGET_QUALITY_PROTOCOL_VERSION
        )
        self._save_state(state)
        return None

    def _schedule_quality_repair(
        self,
        state: dict,
        report: ReQualityReport,
    ) -> ReControllerResult | None:
        attempts = self._metric(state, "re_quality_repair_attempts")
        maximum = self._metric(state, "max_verify_expand_iterations")
        if attempts >= maximum:
            return self._block(state, "re_deep_spec_gate_failed")
        if not state.get("re_quality_repair_pending"):
            repair_targets = self._repair_specification_targets(report)
            if repair_targets is None:
                return self._block(state, "re_domain_manifest_invalid")
            attempts += 1
            state["re_quality_repair_attempts"] = attempts
            state["re_quality_repair_pending"] = True
            state["re_quality_repair_snapshot"] = self._repair_snapshot(report)
            state["re_specification_targets"] = repair_targets
        state["phase"] = "re-extract-2-specify"
        self._save_state(state)
        return None

    def _prompt_for(
        self,
        phase: str,
        state: dict,
        plan: ReExecutionPlan,
        target: dict[str, object] | None = None,
    ) -> str:
        agent = _PHASES[phase]
        agent_path = self._extension_root / "agents" / "re" / f"{agent}.md"
        agent_text = agent_path.read_text(encoding="utf-8")
        phase_path = self._extension_root / "workflow" / "phases" / _PHASE_SPECS[phase]
        phase_text = (
            phase_path.read_text(encoding="utf-8") if phase_path.is_file() else ""
        )
        prompt = (
            f"{agent_text}\n\n"
            f"{phase_text}\n\n"
            f"RE phase: {phase}\n"
            f"RE output directory: {self._run_re_dir}\n"
            "Return a valid echelon_result with verdict DONE or BLOCKED.\n"
        )
        if phase == "re-extract-2-specify" and state.get("re_quality_repair_pending"):
            prompt += (
                "Repair only the source-owned specs listed in "
                f"{state.get('re_quality_gate_report', '')}. Do not re-analyze sources.\n"
            )
        if phase == "re-extract-2-specify" and target is not None:
            prompt += self._specification_target_prompt(target)
        if phase == "re-extract-5-validate":
            prompt += self._semantic_domain_inventory_prompt(plan)
            semantic_error = state.get("re_semantic_review_invalid_error")
            if isinstance(semantic_error, str) and semantic_error:
                prompt += (
                    "\n## Controller Validation Feedback\n"
                    "Your previous semantic_quality_review was rejected: "
                    f"{semantic_error}\n"
                    "Regenerate the complete review. Each REPAIR finding requires "
                    "valid owned-domain source evidence in exact `path:line` or "
                    "`path:start-end` form; path-only prose is invalid. Return DONE "
                    "only after the complete review satisfies this contract.\n"
                )
        return prompt

    def _semantic_domain_inventory_prompt(self, plan: ReExecutionPlan) -> str:
        lines = [
            "\n## Required Semantic Domain Inventory",
            "Your final echelon_result.semantic_quality_review.domains list must contain exactly one record for each source/domain below. Do not return only the currently failing domain.",
            "Do not write RE_VALIDATOR_RESULT.yaml, semantic-quality-review-validator.json, ECHELON_RESULT.yaml, or any other sidecar result file. The controller reads only the final echelon_result block in your response.",
        ]
        for source in plan.refresh_sources:
            try:
                manifest = load_domain_manifest(
                    domain_manifest_path(self._run_re_dir, source.id)
                )
            except ValueError:
                continue
            for domain in manifest.domains:
                lines.append(f"- {source.id}/{domain.domain_id}")
        lines.append("")
        return "\n".join(lines)

    def _synchronize_domain_manifests(
        self, plan: ReExecutionPlan
    ) -> tuple[set[str], str | None]:
        """Refresh deterministic manifests and report source partitions that changed."""
        changed_sources: set[str] = set()
        try:
            for source in plan.refresh_sources:
                path = domain_manifest_path(self._run_re_dir, source.id)
                discovered = discover_source_domains(source)
                existing = None
                if path.exists():
                    manifest = load_domain_manifest(path)
                    existing = manifest
                    if not self._same_domain_partition(manifest, discovered):
                        changed_sources.add(source.id)
                if existing != discovered:
                    write_domain_manifest(path, discovered)
        except (OSError, ValueError) as exc:
            return set(), f"domain manifest generation failed: {exc}"
        return changed_sources, None

    def _ensure_domain_manifests(self, plan: ReExecutionPlan) -> str | None:
        """Materialize missing manifests without changing an active partition."""
        try:
            for source in plan.refresh_sources:
                path = domain_manifest_path(self._run_re_dir, source.id)
                if path.exists():
                    manifest = load_domain_manifest(path)
                    if (
                        manifest.source_id == source.id
                        and manifest.source_path == source.path
                    ):
                        continue
                write_domain_manifest(path, discover_source_domains(source))
        except (OSError, ValueError) as exc:
            return f"domain manifest generation failed: {exc}"
        return None

    @staticmethod
    def _same_domain_partition(first: object, second: object) -> bool:
        return (
            hasattr(first, "source_id")
            and hasattr(first, "source_path")
            and hasattr(first, "domains")
            and hasattr(second, "source_id")
            and hasattr(second, "source_path")
            and hasattr(second, "domains")
            and first.source_id == second.source_id
            and first.source_path == second.source_path
            and [
                (domain.domain_id, domain.root) for domain in first.domains
            ]
            == [
                (domain.domain_id, domain.root) for domain in second.domains
            ]
        )

    def _migrate_changed_domain_manifests(
        self,
        state: dict,
        plan: ReExecutionPlan,
        changed_sources: set[str],
    ) -> str | None:
        """Replace obsolete staged specs when domain ownership has changed."""
        try:
            for source_id in changed_sources:
                specs_root = self._run_re_dir / "sources" / source_id / "specs"
                if specs_root.exists():
                    shutil.rmtree(specs_root)
            refreshed_targets = [
                target
                for target in self._initial_specification_targets(plan)
                if target.get("source_id") in changed_sources
            ]
        except (OSError, ValueError) as exc:
            return f"domain manifest migration failed: {exc}"

        existing_targets = state.get("re_specification_targets")
        remaining_targets = (
            [
                target
                for target in existing_targets
                if not (
                    isinstance(target, dict)
                    and target.get("source_id") in changed_sources
                )
            ]
            if isinstance(existing_targets, list)
            else []
        )
        state["re_specification_targets"] = refreshed_targets + remaining_targets
        state["re_workspace_synthesis_complete"] = False
        state["phase"] = "re-extract-2-specify"
        for key in (
            "re_quality_repair_pending",
            "re_quality_repair_snapshot",
            "re_target_quality_repair_snapshot",
            "re_domain_quality_attempts",
            "re_target_quality_gate_report",
        ):
            state.pop(key, None)
        return None

    def _initial_specification_targets(self, plan: ReExecutionPlan) -> list[dict[str, object]]:
        targets: list[dict[str, object]] = []
        for source in plan.refresh_sources:
            manifest = load_domain_manifest(domain_manifest_path(self._run_re_dir, source.id))
            for domain in manifest.domains:
                targets.append(
                    {
                        "kind": "source-domain",
                        "source_id": source.id,
                        "domain_id": domain.domain_id,
                        "root": domain.root,
                    }
                )
        return targets

    def _repair_specification_targets(
        self, report: ReQualityReport
    ) -> list[dict[str, object]] | None:
        """Translate quality failures to the exact domain specs a repair may edit."""
        targets: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for failure in report.failures:
            if failure.reason not in {
                "deep_spec_incomplete",
                "required_domain_spec_missing",
                "semantic_quality_incomplete",
            }:
                return None
            if not failure.domain_id:
                return None
            manifest_path = domain_manifest_path(self._run_re_dir, failure.source_id)
            try:
                manifest = load_domain_manifest(manifest_path)
            except ValueError:
                return None
            domain = next(
                (
                    candidate
                    for candidate in manifest.domains
                    if candidate.domain_id == failure.domain_id
                ),
                None,
            )
            if domain is None:
                return None
            key = (failure.source_id, domain.domain_id)
            if key in seen:
                continue
            seen.add(key)
            targets.append(
                {
                    "kind": "source-domain",
                    "source_id": failure.source_id,
                    "domain_id": domain.domain_id,
                    "root": domain.root,
                }
            )
        return targets

    @staticmethod
    def _next_specification_target(
        state: dict,
    ) -> dict[str, object] | None:
        raw_targets = state.get("re_specification_targets")
        if raw_targets is None:
            # Legacy interrupted runs did not persist a queue. Reconstruct the
            # initial source-domain queue only before a repair is scheduled.
            if state.get("re_quality_repair_pending"):
                return None
            return None
        if not isinstance(raw_targets, list):
            return None
        if not raw_targets:
            return None
        target = raw_targets[0]
        return target if isinstance(target, dict) else None

    @staticmethod
    def _complete_specification_target(state: dict, target: dict[str, object]) -> None:
        targets = state.get("re_specification_targets")
        if not isinstance(targets, list) or not targets or targets[0] != target:
            raise ValueError("specification target queue changed during dispatch")
        del targets[0]
        if target.get("kind") == "workspace-synthesis":
            state["re_workspace_synthesis_complete"] = True

    def _evaluate_specification_target(
        self,
        state: dict,
        plan: ReExecutionPlan,
        target: dict[str, object],
        *,
        agent_block_detail: str | None = None,
    ) -> ReControllerResult | None:
        """Route one specification target from deterministic evidence, not verdict alone.

        A specifier can report BLOCKED after its own check-domain command fails.
        The controller owns that gate and must turn the observed incomplete
        artifact into the same bounded repair work as a DONE response with an
        incomplete artifact. A BLOCKED response with a passing target remains
        an explicit agent blocker instead of being silently accepted.
        """
        target_report = self._target_quality_report(plan, target)
        if target_report is not None and not target_report.passed:
            source_id = str(target["source_id"])
            domain_id = str(target["domain_id"])
            report_path = write_re_target_quality_report(
                self._run_re_dir, source_id, domain_id, target_report
            )
            attempts = self._record_target_quality_failure(state, target, target_report)
            state["re_target_quality_gate_report"] = str(report_path)
            self._report_target_quality_failure(
                source_id,
                domain_id,
                attempts,
                self._metric(state, "max_verify_expand_iterations"),
                agent_block_detail,
            )
            if self._source_convergence_enabled(state):
                source_id = target.get("source_id")
                domain_id = target.get("domain_id")
                if isinstance(source_id, str) and isinstance(domain_id, str):
                    source_state = self._source_state(state, source_id)
                    repairs = source_state.get("domain_repairs")
                    if not isinstance(repairs, dict):
                        repairs = {}
                        source_state["domain_repairs"] = repairs
                    repair_count = self._metric(repairs, domain_id) + 1
                    repairs[domain_id] = repair_count
                    if repair_count > self._source_budget(
                        state, "max_domain_repairs"
                    ):
                        self._mark_active_source_partial(state, source_id, report_path)
                        self._activate_next_source(state, plan)
                        return None
            if attempts > self._metric(state, "max_verify_expand_iterations"):
                return self._block(state, "re_domain_deep_spec_gate_failed")
            return None

        self._clear_target_quality_failure(state, target)
        if agent_block_detail is not None:
            return self._block(state, self._agent_blocked_reason(agent_block_detail))
        self._complete_specification_target(state, target)
        return None

    @staticmethod
    def _dispatch_failure_detail(timed_out: bool, exit_code: int) -> str:
        details: list[str] = []
        if timed_out:
            details.append("agent timed out")
        if exit_code != 0:
            details.append(f"agent exited with code {exit_code}")
        return "; ".join(details) or "agent dispatch failed"

    @staticmethod
    def _agent_block_detail(payload: dict) -> str:
        candidates = (
            payload.get("blocked_reason"),
            (payload.get("state_updates") or {}).get("blocked_reason")
            if isinstance(payload.get("state_updates"), dict)
            else None,
        )
        for candidate in candidates:
            if isinstance(candidate, str):
                detail = " ".join(candidate.split())
                if detail:
                    return detail[:500]
        return "agent reported BLOCKED without a reason"

    @staticmethod
    def _agent_blocked_reason(detail: str) -> str:
        return f"re_agent_blocked: {detail}"

    @staticmethod
    def _report_target_quality_failure(
        source_id: str,
        domain_id: str,
        attempts: int,
        budget: int,
        agent_block_detail: str | None,
    ) -> None:
        message = (
            "[re] target quality failed: "
            f"{source_id}/{domain_id}; repair attempt {attempts}/{budget}"
        )
        if agent_block_detail is not None:
            message += "; agent result routed into deterministic repair"
        print(message, flush=True)

    def _target_quality_report(
        self, plan: ReExecutionPlan, target: dict[str, object]
    ) -> ReQualityReport | None:
        if target.get("kind") != "source-domain":
            return None
        source_id = target.get("source_id")
        domain_id = target.get("domain_id")
        if not isinstance(source_id, str) or not isinstance(domain_id, str):
            return ReQualityReport(passed=False, failures=())
        return validate_staged_re_domain_quality(
            self._run_re_dir, plan, source_id, domain_id
        )

    @staticmethod
    def _target_quality_key(target: dict[str, object]) -> str | None:
        source_id = target.get("source_id")
        domain_id = target.get("domain_id")
        if not isinstance(source_id, str) or not isinstance(domain_id, str):
            return None
        return f"{source_id}/{domain_id}"

    def _record_target_quality_failure(
        self,
        state: dict,
        target: dict[str, object],
        report: ReQualityReport,
    ) -> int:
        key = self._target_quality_key(target)
        if key is None:
            return self._metric(state, "max_verify_expand_iterations") + 1
        raw_attempts = state.get("re_domain_quality_attempts")
        attempts = raw_attempts if isinstance(raw_attempts, dict) else {}
        next_attempt = self._metric(attempts, key) + 1
        attempts[key] = next_attempt
        state["re_domain_quality_attempts"] = attempts
        if (
            not state.get("re_quality_repair_pending")
            and "re_target_quality_repair_snapshot" not in state
        ):
            state["re_target_quality_repair_snapshot"] = self._repair_snapshot(report)
        return next_attempt

    def _clear_target_quality_failure(self, state: dict, target: dict[str, object]) -> None:
        key = self._target_quality_key(target)
        attempts = state.get("re_domain_quality_attempts")
        if key is not None and isinstance(attempts, dict):
            attempts.pop(key, None)
            if not attempts:
                state.pop("re_domain_quality_attempts", None)
        state.pop("re_target_quality_repair_snapshot", None)
        source_id = target.get("source_id")
        domain_id = target.get("domain_id")
        if isinstance(source_id, str) and isinstance(domain_id, str):
            path = self._run_re_dir / "quality" / "targets" / source_id / f"{domain_id}.json"
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _specification_target_prompt(self, target: dict[str, object]) -> str:
        kind = target.get("kind")
        if kind == "workspace-synthesis":
            return (
                "\n## Controller-Owned Specification Target\n"
                "Generate source overviews and workspace synthesis only. All required "
                "source-domain specs have already been dispatched independently. Do not "
                "create, rename, or rewrite any source-domain spec.\n"
            )
        if kind == "source-support":
            source_id = target.get("source_id")
            orphan_paths = target.get("orphan_paths")
            if (
                not isinstance(source_id, str)
                or not source_id
                or not isinstance(orphan_paths, list)
                or not orphan_paths
                or any(not isinstance(path, str) or not path for path in orphan_paths)
            ):
                raise ValueError("invalid source supporting-artifacts target")
            support_path = (
                self._run_re_dir / "sources" / source_id / "supporting-artifacts.md"
            )
            source_report = self._run_re_dir / "quality" / "sources" / f"{source_id}.json"
            paths = "\n".join(f"- `{path}`" for path in orphan_paths)
            return (
                "\n## Controller-Owned Source Supporting-Artifacts Target\n"
                f"Generate exactly one source supporting-artifacts register: `{support_path}`.\n"
                f"Source ID: `{source_id}`\n"
                f"Read `{source_report}`. The following visible source files are outside "
                "every product-domain root, but remain required source evidence:\n"
                f"{paths}\n"
                "For every listed file, document its observed configuration, test-support, "
                "or runtime role and cite it with a valid source-root-relative `path:line` "
                "reference. Do not merely list paths. Do not create or modify a domain spec, "
                "workspace synthesis, manifest, or planner artifact. Return DONE only after "
                "every listed file is cited in this register. Return an `echelon_result` with "
                "`state_updates: {}`; do not emit source inventory or other state updates.\n"
            )
        source_id = target.get("source_id")
        domain_id = target.get("domain_id")
        root = target.get("root")
        if not all(isinstance(value, str) and value for value in (source_id, domain_id, root)):
            raise ValueError("invalid controller specification target")
        manifest = domain_manifest_path(self._run_re_dir, source_id)
        spec_path = self._run_re_dir / "sources" / source_id / "specs" / domain_id / "spec.md"
        target_report = (
            self._run_re_dir / "quality" / "targets" / source_id / f"{domain_id}.json"
        )
        source_report = self._run_re_dir / "quality" / "sources" / f"{source_id}.json"
        orphan_paths = target.get("orphan_paths")
        coverage_repair = ""
        if isinstance(orphan_paths, list) and orphan_paths:
            if any(not isinstance(path, str) or not path for path in orphan_paths):
                raise ValueError("invalid source coverage repair paths")
            paths = "\n".join(f"- `{path}`" for path in orphan_paths)
            coverage_repair = (
                "Source coverage repair: read the controller-owned source report "
                f"`{source_report}`. The following files are inside this domain but still "
                "lack valid evidence:\n"
                f"{paths}\n"
                "Extend this target spec with concrete, valid citations for every listed "
                "file and integrate the observed behavior into its scenarios, requirements, "
                "edge cases, or source-evidence explanation. Do not merely append a path list.\n"
            )
        quality_contract = ""
        architecture_contract = self._architecture_target_context(source_id, domain_id)
        try:
            domain_manifest = load_domain_manifest(manifest)
            domain = next(
                candidate
                for candidate in domain_manifest.domains
                if candidate.domain_id == domain_id
            )
            target = quality_target_for_domain(domain)
            quality_contract = (
                "The deterministic quality contract for this domain requires at least "
                f"{target.minimum_scenarios} scenario headings, "
                f"{target.minimum_functional_requirements} FR headings, and "
                f"{target.minimum_non_functional_requirements} NFR headings. "
                "Every scenario needs a source-evidenced Given/When/Then acceptance case; "
                "every FR and NFR needs at least one valid source citation.\n"
            )
        except (StopIteration, ValueError):
            quality_contract = (
                "The domain manifest could not provide adaptive quality counts. "
                "Do not infer another target; the controller will report the manifest failure.\n"
            )
        return (
            "\n## Controller-Owned Specification Target\n"
            f"Generate exactly one deep source-domain spec: `{spec_path}`.\n"
            f"Source ID: `{source_id}`\n"
            f"Domain ID: `{domain_id}`\n"
            f"Owned source root: `{root}`\n"
            f"Domain manifest: `{manifest}`\n"
            "Read only this source's owned root and its staged extraction artifacts. "
            "Every source citation must be a backticked `path/to/file:line` reference "
            "using either the source-root path or a path relative to the owned domain "
            "root; it must resolve within that domain. Never use Markdown-link citations. "
            "Include at least five distinct valid citations. Do not write another domain spec, "
            "source overview, or workspace synthesis. Write only this target's `spec.md`; "
            "never create backup, temporary, alternate, or scratch files beside it.\n"
            + coverage_repair
            + "Before returning DONE, run this exact deterministic check from the "
            "workspace root; it exits non-zero and prints the authoritative failures "
            "when the spec is not acceptable:\n"
            f"`cd {shlex.quote(str(self._project_root))} && echelon re check-domain "
            f"{self._run_dir.name} {source_id} {domain_id}`\n"
            "Do not claim that a citation is valid because its path exists: its line "
            "range must also exist. Correct every printed failure before returning DONE.\n"
            + quality_contract
            + architecture_contract
            + (
                f"Read `{target_report}` before editing: it is the exact deterministic "
                "failure report for this target.\n"
                if target_report.is_file()
                else ""
            )
        )

    def _ensure_architecture_overlay(
        self,
        state: dict,
        plan: ReExecutionPlan,
        *,
        rebuild: bool = False,
    ) -> str | None:
        """Materialize the read-only architectural view over stable domains."""
        map_path = self._run_re_dir / "workspace" / "architecture-map.json"
        catalog_path = self._run_re_dir / "workspace" / "domain-catalog.md"
        try:
            overlay_written = rebuild or not map_path.is_file() or not catalog_path.is_file()
            if overlay_written:
                architecture = build_re_architecture_map(plan, run_re_dir=self._run_re_dir)
                map_path, catalog_path = write_re_architecture_catalog(
                    self._run_re_dir, architecture
                )
            else:
                load_re_architecture_map(map_path)
            snapshot_error = self._refresh_repair_snapshots_for_architecture_overlay(
                state
            )
            if snapshot_error is not None:
                return snapshot_error
            state["re_architecture_map"] = str(map_path)
            state["re_domain_catalog"] = str(catalog_path)
            self._save_state(state)
        except (OSError, ValueError) as exc:
            return f"architecture catalog generation failed: {exc}"
        return None

    def _architecture_target_context(self, source_id: str, domain_id: str) -> str:
        """Return immutable layer and dependency context for one source-domain spec."""
        map_path = self._run_re_dir / "workspace" / "architecture-map.json"
        try:
            architecture = load_re_architecture_map(map_path)
        except ValueError:
            return (
                "Architecture catalog is unavailable; do not infer an architecture layer. "
                "The controller will block and regenerate it.\n"
            )
        key = f"{source_id}/{domain_id}"
        domain = next((item for item in architecture.domains if item.key == key), None)
        if domain is None:
            return (
                "Architecture catalog has no entry for this domain; do not infer one. "
                "The controller will block and regenerate it.\n"
            )
        prerequisites = ", ".join(domain.dependencies) if domain.dependencies else "None"
        cycle = domain.cycle_group or "None"
        return (
            "Architecture composition is controller-owned and read-only. Include these exact "
            "values in the spec header: "
            f"layer `{domain.layer_label}`, migration wave `{domain.migration_wave}`, "
            f"prerequisites `{prerequisites}`, cycle group `{cycle}`. "
            f"Read `{map_path}` and `{self._run_re_dir / 'workspace' / 'domain-catalog.md'}` "
            "for the complete architecture view. Do not change either artifact.\n"
        )

    def _prepare_specification_target(
        self, state: dict, target: dict[str, object]
    ) -> str | None:
        """Create the one writable target so constrained providers can edit it."""
        kind = target.get("kind")
        if kind not in {None, "source-domain", "source-support"}:
            return None
        source_id = target.get("source_id")
        domain_id = target.get("domain_id")
        if not isinstance(source_id, str) or not source_id:
            return "re_specification_target_invalid"
        if kind != "source-support":
            if not isinstance(domain_id, str) or not domain_id:
                return "re_specification_target_invalid"
            path = self._run_re_dir / "sources" / source_id / "specs" / domain_id / "spec.md"
        else:
            path = self._run_re_dir / "sources" / source_id / "supporting-artifacts.md"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            cleanup_error = self._clean_noncanonical_target_artifacts(
                state, target, stage="pre-dispatch"
            )
            if cleanup_error is not None:
                return cleanup_error
            path.touch(exist_ok=True)
        except OSError as exc:
            return f"re_specification_target_prepare_failed: {exc}"
        return None

    def _clean_noncanonical_target_artifacts(
        self,
        state: dict,
        target: dict[str, object],
        *,
        stage: str,
    ) -> str | None:
        """Keep a source-domain target directory to its canonical `spec.md` only."""
        kind = target.get("kind")
        if kind not in {None, "source-domain"}:
            return None
        source_id = target.get("source_id")
        domain_id = target.get("domain_id")
        if not isinstance(source_id, str) or not isinstance(domain_id, str):
            return "re_specification_target_invalid"
        target_dir = self._run_re_dir / "sources" / source_id / "specs" / domain_id
        if not target_dir.is_dir():
            return None
        removed: list[str] = []
        try:
            for candidate in target_dir.iterdir():
                if candidate.name == "spec.md":
                    continue
                relative = str(candidate.relative_to(self._run_re_dir))
                if candidate.is_dir() and not candidate.is_symlink():
                    shutil.rmtree(candidate)
                else:
                    candidate.unlink()
                removed.append(relative)
        except OSError as exc:
            return f"re_target_artifact_cleanup_failed: {exc}"
        if removed and state:
            cleanup = state.setdefault("re_target_artifact_cleanup", [])
            if isinstance(cleanup, list):
                cleanup.append(
                    {
                        "stage": stage,
                        "source_id": source_id,
                        "domain_id": domain_id,
                        "paths": sorted(removed),
                    }
                )
        return None

    def _run_analysis_script(self, plan: ReExecutionPlan) -> str | None:
        """Run extraction in the controller so one-shot agents cannot detach it."""
        profile = plan.profile
        script = self._extension_root / "scripts" / "bash" / "re" / "run-analysis.sh"
        manifest = self._run_re_dir / "re-analysis-manifest.json"
        if not script.is_file():
            return f"analysis script not found: {script}"
        if not manifest.is_file():
            return f"analysis manifest not found: {manifest}"

        command = [
            "bash",
            str(script),
            "--output",
            str(self._run_re_dir),
            "--manifest",
            str(manifest),
            "--source-output-root",
            str(self._run_re_dir / "sources"),
            "--profile",
            profile.profile,
            "--depth",
            profile.depth,
            "--max-lines-per-file",
            str(profile.max_lines_per_file or 5000),
            "--git-history-limit",
            str(profile.git_history_limit or 2500),
        ]
        environment = os.environ.copy()
        environment["EXTENSION_PATH"] = str(self._extension_root)
        try:
            completed = self._execute_analysis_command(command, environment)
        except subprocess.TimeoutExpired:
            return "analysis script exceeded the 3-hour controller timeout"
        except OSError as exc:
            return f"analysis script could not start: {exc}"
        if completed.returncode != 0:
            output = (completed.stderr or completed.stdout or "").strip()
            return f"analysis script exited {completed.returncode}: {output[-1000:]}"
        if not (self._run_re_dir / "analysis.json").is_file():
            return "analysis script completed without aggregate analysis.json"
        return None

    def _execute_analysis_command(
        self,
        command: list[str],
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=self._project_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10_800,
            check=False,
        )

    def _analysis_result(self) -> dict:
        return {
            "verdict": "DONE",
            "state_updates": {
                "mode": "workspace",
                "domains": [],
                "artifacts": {
                    "analysis_json": str(self._run_re_dir / "analysis.json"),
                    "analysis_manifest": str(
                        self._run_re_dir / "re-analysis-manifest.json"
                    ),
                    "workspace_manifest": str(
                        self._run_re_dir / "workspace-manifest.json"
                    ),
                    "repos_manifest": str(self._run_re_dir / "repos-manifest.json"),
                    "cross_repo": str(self._run_re_dir / "cross-repo.json")
                    if (self._run_re_dir / "cross-repo.json").is_file()
                    else None,
                    "codegraph_analysis": str(
                        self._run_re_dir / "codegraph-analysis.json"
                    )
                    if (self._run_re_dir / "codegraph-analysis.json").is_file()
                    else None,
                    "codegraph_summary": str(
                        self._run_re_dir / "codegraph-summary.json"
                    )
                    if (self._run_re_dir / "codegraph-summary.json").is_file()
                    else None,
                },
            },
            "journal_entries": [],
        }

    def _load_plan(self) -> ReExecutionPlan:
        raw = json.loads(
            (self._run_re_dir / "re-execution-plan.json").read_text(encoding="utf-8")
        )
        return ReExecutionPlan.from_json_dict(raw)

    def _repair_snapshot(self, report: ReQualityReport) -> dict[str, object]:
        targets = self._repair_target_paths(report)
        immutable = [
            self._run_re_dir / "re-execution-plan.json",
            self._run_re_dir / "re-source-index.json",
            self._run_re_dir / "re-workspace-inputs.json",
            self._run_re_dir / "workspace-manifest.json",
            self._run_re_dir / "analysis.json",
        ]
        immutable.extend((self._run_re_dir / "sources").glob("*/analysis.json"))
        return {
            "immutable_inputs": self._snapshot_paths(immutable),
            "non_target_outputs": self._non_target_snapshot(targets),
            "repair_targets": [
                target.relative_to(self._run_re_dir).as_posix() for target in targets
            ],
        }

    def _repair_snapshot_failure(
        self, state: dict, snapshot_key: str = "re_quality_repair_snapshot"
    ) -> str | None:
        snapshot = state.get(snapshot_key)
        if not isinstance(snapshot, dict):
            return "re_quality_repair_snapshot_missing"
        immutable = snapshot.get("immutable_inputs")
        non_target = snapshot.get("non_target_outputs")
        target_relatives = snapshot.get("repair_targets")
        if (
            not isinstance(immutable, dict)
            or not isinstance(non_target, dict)
            or not isinstance(target_relatives, list)
            or any(not isinstance(path, str) for path in target_relatives)
        ):
            return "re_quality_repair_snapshot_missing"
        if self._snapshot_changed(immutable):
            return "re_quality_repair_modified_immutable_input"
        targets = [self._run_re_dir / path for path in target_relatives]
        if self._non_target_snapshot(targets) != non_target:
            return "re_quality_repair_modified_non_target_output"
        return None

    def _refresh_repair_snapshots_for_architecture_overlay(
        self, state: dict
    ) -> str | None:
        """Accept only controller-created catalog changes in an active snapshot.

        A run can predate either the architecture catalog or the exclusion of
        Finder metadata from artifact comparison. Normalize those historical
        snapshot entries first, then allow only the two controller-owned catalog
        files to enter its expected-output baseline. Any other difference remains
        a guarded non-target modification.
        """
        for snapshot_key in (
            "re_quality_repair_snapshot",
            "re_target_quality_repair_snapshot",
        ):
            snapshot = state.get(snapshot_key)
            if snapshot is None:
                continue
            if not isinstance(snapshot, dict):
                return "re_quality_repair_snapshot_missing"
            previous = snapshot.get("non_target_outputs")
            target_relatives = snapshot.get("repair_targets")
            if (
                not isinstance(previous, dict)
                or not isinstance(target_relatives, list)
                or any(not isinstance(path, str) for path in target_relatives)
            ):
                return "re_quality_repair_snapshot_missing"
            normalized_previous = {
                relative: digest
                for relative, digest in previous.items()
                if isinstance(relative, str)
                and not self._is_repair_control_plane_file(relative)
            }
            targets = [self._run_re_dir / path for path in target_relatives]
            current = self._non_target_snapshot(targets)
            changed = {
                relative
                for relative in set(normalized_previous) | set(current)
                if normalized_previous.get(relative) != current.get(relative)
            }
            if not changed.issubset(_ARCHITECTURE_OVERLAY_OUTPUTS):
                return "re_quality_repair_modified_non_target_output"
            snapshot["non_target_outputs"] = current
        return None

    def _repair_target_paths(self, report: ReQualityReport) -> list[Path]:
        targets: list[Path] = []
        for failure in report.failures:
            target = failure.spec_path.resolve()
            specs_root = (
                self._run_re_dir / "sources" / failure.source_id / "specs"
            ).resolve()
            if not target.is_relative_to(specs_root):
                raise ValueError(f"unsafe RE repair target: {target}")
            targets.append(target)
        return targets

    def _snapshot_paths(self, paths: object) -> dict[str, str]:
        snapshot: dict[str, str] = {}
        for path in paths:
            if not isinstance(path, Path) or not path.is_file():
                continue
            relative = path.relative_to(self._run_re_dir).as_posix()
            snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return dict(sorted(snapshot.items()))

    def _non_target_snapshot(self, targets: list[Path]) -> dict[str, str]:
        target_files = {
            target.relative_to(self._run_re_dir).as_posix()
            for target in targets
        }
        target_roots = {
            target.relative_to(self._run_re_dir).as_posix()
            for target in targets
            if target.is_dir()
        }
        paths: list[Path] = []
        for path in self._run_re_dir.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self._run_re_dir).as_posix()
            # The controller state, quality report, and root-level agent result
            # captures are control-plane files. They are never RE artifacts and
            # are not read or published as source output.
            if self._is_repair_control_plane_file(relative):
                continue
            if relative in target_files or any(
                relative.startswith(root + "/") for root in target_roots
            ):
                continue
            paths.append(path)
        return self._snapshot_paths(paths)

    @staticmethod
    def _is_repair_control_plane_file(relative: str) -> bool:
        if relative in _REPAIR_EPHEMERAL_OUTPUTS:
            return True
        if Path(relative).name == ".DS_Store":
            return True
        # Providers may persist the trailing echelon_result under a phase-specific
        # name (for example, REPAIR_RESULT.yaml). Restrict the exemption to the
        # RE root: any source-owned or other nested output remains protected.
        return relative.startswith("quality/") or (
            "/" not in relative and relative.endswith("_RESULT.yaml")
        )

    def _snapshot_changed(self, expected: dict) -> bool:
        paths = [self._run_re_dir / str(relative) for relative in expected]
        return self._snapshot_paths(paths) != expected

    def _load_state(self) -> dict:
        path = self._run_re_dir / "state.json"
        if not path.exists():
            return self._initialize_state()
        state = json.loads(path.read_text(encoding="utf-8"))
        if not self._is_controller_state(state):
            # Legacy/manual extraction state has no dispatch protocol.  Treat it
            # as unverified rather than accepting a shallow result as complete.
            return self._initialize_state()
        return state

    def _initialize_state(self) -> dict:
        self._run_re_dir.mkdir(parents=True, exist_ok=True)
        state = init_re_state(
            output_dir=f"runs/{self._run_dir.name}/re",
            mode="workspace",
        )
        state["run_id"] = self._run_dir.name
        self._save_state(state)
        return state

    @staticmethod
    def _is_controller_state(state: object) -> bool:
        if not isinstance(state, dict):
            return False
        phase = state.get("phase")
        last_dispatch = state.get("last_dispatch")
        return (
            isinstance(phase, str)
            and phase in {"re-extract-0-preflight", *_PHASES}
            and isinstance(last_dispatch, dict)
            and isinstance(last_dispatch.get("post_dispatch_complete"), bool)
        )

    def _save_state(self, state: dict) -> None:
        path = self._run_re_dir / "state.json"
        fd, temporary = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary).replace(path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _block(self, state: dict, reason: str) -> ReControllerResult:
        state["status"] = "blocked"
        state["blocked_reason"] = reason
        self._save_state(state)
        detail = state.get("re_agent_result_detail")
        return ReControllerResult(
            completed=False,
            blocked_reason=reason,
            blocked_detail=detail if isinstance(detail, str) and detail.strip() else None,
        )

    @staticmethod
    def _agent_result_without_controller_keys(
        payload: dict, target: dict[str, object] | None = None
    ) -> dict:
        updates = payload.get("state_updates")
        if not isinstance(updates, dict):
            return payload
        if isinstance(target, dict) and target.get("kind") == "source-support":
            # A supporting-artifacts target has no state transition. Providers
            # sometimes report a descriptive `sources` list; never let that
            # non-routing metadata block the deterministic coverage repair.
            return {**payload, "state_updates": {}}
        controlled = {
            "max_validate_iterations",
            "max_verify_expand_iterations",
            "validate_iterations",
            "verify_expand_iterations",
            "re_quality_repair_attempts",
            "re_domain_quality_attempts",
            "re_target_quality_repair_snapshot",
            # Repair metadata is useful in the agent transcript but is not a
            # RE-state transition. Treat it as controller-owned diagnostics.
            "repair_action",
            # RE lifecycle status is controller-owned. The controller marks
            # extraction done only after the current phase result has passed
            # validation and deterministic routing.
            "status",
        }
        filtered = {key: value for key, value in updates.items() if key not in controlled}
        return {**payload, "state_updates": filtered}

    @staticmethod
    def _metric(state: dict, key: str) -> int:
        value = state.get(key, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0
