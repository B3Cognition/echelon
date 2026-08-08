"""Harness-owned execution controller for active workspace RE runs."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import hashlib
import subprocess
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from harness.re_architecture import (
    build_re_architecture_map,
    load_re_architecture_map,
    write_re_architecture_catalog,
)
from harness.re_lock import ReExtractLocked, ReExtractionLock
from harness.re_materializer import build_re_workspace_inputs
from harness.re_domain_manifest import (
    DOMAIN_PARTITION_VERSION,
    discover_source_domains,
    domain_manifest_path,
    load_domain_manifest,
    write_domain_manifest,
)
from harness.re_planner import ReExecutionPlan
from harness.re_registry import (
    PublishedReIndex,
    ReRegistryError,
    canonical_re_artifacts,
    load_published_index,
    published_source_is_usable,
)
from harness.re_quality_gate import (
    ReQualityReport,
    ReSpecQualityFailure,
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
from echelon.telemetry.model import ExecutionSpan, TokenUsage
from echelon.telemetry.store import TelemetryStore
from harness.re_budget import evaluate_re_budget
from harness.re_repair_packet import ReRepairFinding, ReRepairPacket
from harness.squad_executors import _canonical_echelon_result_contract


class ReAgentProvider(Protocol):
    def exec_agent(self, project_root: str, prompt: str, **kwargs: object): ...


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
_SEMANTIC_DOMAIN_AUDIT_PROTOCOL_VERSION = 1
_WORKSPACE_SYNTHESIS_SCOPE_PROTOCOL_VERSION = 1
_WORKSPACE_SYNTHESIS_REPAIR_LIMIT = 1
_RETARGET_MARKER = "[REQUIRES INPUT]"
_RETARGET_STRATEGY_FILES = (
    "constitution.md",
    "migration-strategy.md",
    "risk-matrix.md",
    "gap-analysis.md",
)


def discover_retarget_markers(re_root: Path) -> dict[str, object]:
    """Return a deterministic inventory of unresolved strategy decisions."""
    root = re_root.resolve()
    strategy_root = root / "workspace" / "strategy"
    paths = [strategy_root / name for name in _RETARGET_STRATEGY_FILES]
    adrs_root = strategy_root / "adrs"
    if adrs_root.is_dir() and not adrs_root.is_symlink():
        paths.extend(
            path
            for path in adrs_root.rglob("*.md")
            if path.is_file() and not path.is_symlink()
        )

    markers: list[dict[str, object]] = []
    for path in sorted(set(paths)):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            relative = path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(),
            start=1,
        ):
            for occurrence in range(line.count(_RETARGET_MARKER)):
                markers.append({
                    "path": relative,
                    "line": line_number,
                    "occurrence": occurrence + 1,
                    "context": line.strip(),
                })
    return {
        "schema_version": 1,
        "count": len(markers),
        "markers": markers,
    }


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
        self._invocation_started_monotonic = 0.0

    def run(self) -> ReControllerResult:
        self._invocation_started_monotonic = time.monotonic()
        try:
            with ReExtractionLock.acquire(
                self._project_root,
                self._run_dir.name,
                self._run_dir,
            ):
                try:
                    return self._run_locked()
                finally:
                    self._finish_active_interval()
        except ReExtractLocked:
            return ReControllerResult(
                completed=False,
                blocked_reason="re_extraction_locked",
            )

    def _run_locked(self) -> ReControllerResult:
        plan = self._load_plan()
        state = self._load_state()
        if self._recover_rejected_workspace_synthesis(state, plan):
            self._save_state(state)
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

            semantic_target: dict[str, str] | None = None
            if phase == "re-extract-5-validate":
                semantic_target = self._next_semantic_validation_target(state, plan)
                if semantic_target is None:
                    aggregate = self._semantic_validation_payload(state, plan)
                    semantic_report, semantic_error = validate_semantic_quality_review(
                        self._run_re_dir,
                        plan,
                        aggregate,
                        expected_domains=self._semantic_expected_domains(plan) or None,
                    )
                    if semantic_error is not None or semantic_report is None:
                        state["re_agent_result_detail"] = semantic_error or (
                            "semantic quality review was unavailable"
                        )
                        return self._block(state, "re_semantic_quality_review_invalid")
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
                        else:
                            state["re_quality_gate_report"] = str(semantic_report_path)
                            scheduled = self._schedule_quality_repair(
                                state, semantic_report
                            )
                        if scheduled is not None:
                            return scheduled
                        state = self._load_state()
                        continue
                    state["phase"] = "re-extract-6-checklist"
                    self._save_state(state)
                    continue

            budget = evaluate_re_budget(
                state,
                current_invocation_ms=self._current_invocation_ms(),
            )
            if not budget.allowed:
                state["re_budget_limit"] = {
                    "reason": budget.reason,
                    "limit": budget.limit,
                    "consumed": budget.consumed,
                }
                return self._block(state, budget.reason)

            dispatch_kwargs: dict[str, object] = {}
            if phase != "re-extract-1-analyze":
                if getattr(self._provider, "supports_result_contract", False):
                    dispatch_kwargs["result_contract"] = self._result_contract_for_phase(
                        phase
                    )
                prompt_metadata: dict[str, object] = {}
                if isinstance(target, dict) and target.get("kind") == "workspace-synthesis":
                    if (
                        getattr(
                            self._provider,
                            "enforces_workspace_synthesis_boundary",
                            None,
                        )
                        is not True
                    ):
                        state["re_agent_result_detail"] = (
                            "selected provider cannot enforce workspace synthesis "
                            "file scopes"
                        )
                        return self._block(
                            state, "re_workspace_synthesis_scope_unsupported"
                        )
                    try:
                        self._clean_workspace_synthesis_sources(state, plan)
                        prompt_metadata = self._prompt_metadata_for_target(
                            plan, target, state
                        )
                    except (OSError, ValueError, json.JSONDecodeError) as exc:
                        state["re_agent_result_detail"] = (
                            f"workspace synthesis canonical inputs are invalid: {exc}"
                        )
                        return self._block(
                            state, "re_workspace_synthesis_inputs_invalid"
                        )
                elif getattr(self._provider, "supports_prompt_metadata", False):
                    prompt_metadata = self._prompt_metadata_for_target(
                        plan, target, state
                    )
                if (
                    prompt_metadata
                    and getattr(self._provider, "supports_prompt_metadata", False)
                ):
                    dispatch_kwargs["prompt_metadata"] = prompt_metadata
                if isinstance(target, dict) and target.get("kind") == "workspace-synthesis":
                    state["re_workspace_synthesis_scope_protocol_version"] = (
                        _WORKSPACE_SYNTHESIS_SCOPE_PROTOCOL_VERSION
                    )

            state = write_last_dispatch(state, phase, _PHASES[phase])
            self._save_state(state)
            if phase == "re-extract-1-analyze":
                analysis_error = self._run_analysis_script(plan)
                if analysis_error is not None:
                    state["re_analysis_error"] = analysis_error
                    return self._block(state, "re_analysis_script_failed")
                payload = self._analysis_result()
            else:
                dispatch_started = datetime.now(timezone.utc)
                result = self._provider.exec_agent(
                    str(self._project_root),
                    self._prompt_for(
                        phase,
                        state,
                        plan,
                        target,
                        semantic_target=semantic_target,
                    ),
                    **dispatch_kwargs,
                )
                dispatch_ended = datetime.now(timezone.utc)
                self._account_provider_usage(state, result)
                try:
                    self._record_dispatch_span(
                        state,
                        phase=phase,
                        target=target,
                        semantic_target=semantic_target,
                        result=result,
                        started=dispatch_started,
                        ended=dispatch_ended,
                    )
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    state["re_agent_result_detail"] = f"telemetry write failed: {exc}"
                    return self._block(state, "re_telemetry_write_failed")
                self._save_state(state)
                if phase == "re-extract-2-specify" and target is not None:
                    cleanup_error = self._clean_noncanonical_target_artifacts(
                        state, target, stage="post-dispatch"
                    )
                    if cleanup_error is not None:
                        return self._block(state, cleanup_error)
                if result.timed_out or result.exit_code != 0:
                    state["re_agent_result_detail"] = self._dispatch_failure_detail(
                        result.timed_out,
                        result.exit_code,
                        getattr(result, "stderr", ""),
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
                    target_result = self._run_specification_target_post_dispatch(
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
                    state,
                    self._agent_result_without_controller_keys(
                        payload, target, phase=phase
                    ),
                )
            except (KeyError, ValueError) as exc:
                state["re_agent_result_detail"] = str(exc)
                return self._block(state, "re_agent_result_invalid")
            state.pop("re_agent_result_detail", None)
            if phase == "re-extract-3-verify":
                coverage_error = self._refresh_controller_coverage(state, plan)
                if coverage_error is not None:
                    state["re_agent_result_detail"] = coverage_error
                    return self._block(state, "re_coverage_measurement_failed")
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
                target_result = self._run_specification_target_post_dispatch(
                    state,
                    plan,
                    target,
                )
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
                    expected_domains={
                        (
                            str(semantic_target["source_id"]),
                            str(semantic_target["domain_id"]),
                        )
                    },
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
                raw_review = payload["semantic_quality_review"]["domains"][0]
                self._store_semantic_domain_audit(
                    state, plan, semantic_target, raw_review
                )
                self._save_state(state)
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
                state["phase"] = (
                    "re-extract-5-validate"
                    if self._semantic_audit_enabled(state)
                    else "re-extract-6-checklist"
                )
                if not self._semantic_audit_enabled(state):
                    state["re_semantic_audit"] = {
                        "status": "not-evaluated",
                        "reason": "execution-profile",
                    }
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

    def _refresh_controller_coverage(
        self,
        state: dict,
        plan: ReExecutionPlan,
    ) -> str | None:
        """Measure aggregate source coverage without trusting model state."""
        reports: list[ReSourceQualityReport] = []
        try:
            for source in plan.refresh_sources:
                report = measure_source_quality(
                    self._run_re_dir,
                    plan,
                    source.id,
                    coverage_threshold=self._metric(state, "coverage_threshold"),
                )
                write_re_source_quality_report(self._run_re_dir, report)
                reports.append(report)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return str(exc)

        eligible = sum(report.eligible_file_count for report in reports)
        covered = sum(report.covered_file_count for report in reports)
        state["coverage_pct"] = (
            100 if eligible == 0 else int(round((covered / eligible) * 100))
        )
        state["re_coverage_measurement"] = {
            "eligible_file_count": eligible,
            "covered_file_count": covered,
            "source_count": len(reports),
        }
        return None

    @staticmethod
    def _source_convergence_enabled(state: dict) -> bool:
        return (
            state.get("re_convergence_schema_version") == 1
            and isinstance(state.get("re_source_states"), dict)
        )

    @staticmethod
    def _semantic_audit_enabled(state: dict) -> bool:
        profile = state.get("re_execution_profile")
        if not isinstance(profile, dict):
            return True
        return profile.get("semantic_audit_mode", "all") != "none"

    def _semantic_repair_limit(self, state: dict) -> int:
        profile = state.get("re_execution_profile")
        if isinstance(profile, dict):
            value = profile.get("max_semantic_repair_rounds")
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
        if self._source_convergence_enabled(state):
            return self._source_budget(state, "max_domain_repairs")
        return self._metric(state, "max_verify_expand_iterations")

    @staticmethod
    def _is_unscoped_universal_claim_only(failure: ReSpecQualityFailure) -> bool:
        return (
            bool(failure.semantic_preflight_findings)
            and all(
                finding.code == "unscoped_universal_claim"
                for finding in failure.semantic_preflight_findings
            )
            and not failure.missing_sections
            and not failure.invalid_source_evidence
            and not failure.scenarios_without_acceptance
            and not failure.scenarios_without_evidence
            and not failure.functional_requirements_without_evidence
            and not failure.non_functional_requirements_without_evidence
            and not failure.semantic_findings
            and failure.scenario_count >= failure.expected_scenario_count
            and (
                failure.functional_requirement_count
                >= failure.expected_functional_requirement_count
            )
            and (
                failure.non_functional_requirement_count
                >= failure.expected_non_functional_requirement_count
            )
        )

    def _target_quality_repair_limit(
        self, state: dict, report: ReQualityReport
    ) -> int:
        if report.failures and all(
            self._is_unscoped_universal_claim_only(failure)
            for failure in report.failures
        ):
            return self._semantic_repair_limit(state)
        if self._source_convergence_enabled(state):
            return self._source_budget(state, "max_domain_repairs")
        return self._metric(state, "max_verify_expand_iterations")

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
            state["phase"] = (
                "re-extract-5-validate"
                if self._semantic_audit_enabled(state)
                else "re-extract-6-checklist"
            )
            if not self._semantic_audit_enabled(state):
                state["re_semantic_audit"] = {
                    "status": "not-evaluated",
                    "reason": "execution-profile",
                }
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
        state["re_workspace_synthesis_complete"] = False
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
                failure = next(
                    item for item in failures if item.domain_id == domain_id
                )
                spec_path = Path(failure.spec_path)
                packet = ReRepairPacket(
                    source_id=source_id,
                    domain_id=domain_id,
                    spec_fingerprint=hashlib.sha256(spec_path.read_bytes()).hexdigest(),
                    attempt=repair_count,
                    findings=tuple(
                        ReRepairFinding(
                            finding_id=item.finding_id,
                            category=item.category,
                            text=item.text,
                            source_evidence=item.source_evidence,
                        )
                        for item in failure.semantic_finding_records
                    ),
                )
                target["repair_packet"] = packet.to_json_dict()
                self._record_repeated_findings(state, packet)
                exhausted = exhausted or repair_count > self._semantic_repair_limit(state)
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
            audits = state.get("re_semantic_domain_audits")
            if isinstance(audits, dict):
                for target in targets:
                    audits.pop(f"{source_id}/{target['domain_id']}", None)
            state["re_workspace_synthesis_complete"] = False
            state["phase"] = "re-extract-2-specify"
            self._reported_source_id = None
            self._save_state(state)
            return None
        state["phase"] = "re-extract-6-checklist"
        self._save_state(state)
        return None

    @staticmethod
    def _record_repeated_findings(state: dict, packet: ReRepairPacket) -> None:
        key = f"{packet.source_id}/{packet.domain_id}"
        history = state.setdefault("re_repair_finding_history", {})
        if not isinstance(history, dict):
            history = {}
            state["re_repair_finding_history"] = history
        raw_previous = history.get(key)
        previous = (
            {item for item in raw_previous if isinstance(item, str)}
            if isinstance(raw_previous, list)
            else set()
        )
        current = {item.finding_id for item in packet.findings}
        repeated = previous & current
        if repeated:
            repeated_by_domain = state.setdefault("re_repeated_finding_ids", {})
            if not isinstance(repeated_by_domain, dict):
                repeated_by_domain = {}
                state["re_repeated_finding_ids"] = repeated_by_domain
            raw_existing = repeated_by_domain.get(key)
            existing = (
                {item for item in raw_existing if isinstance(item, str)}
                if isinstance(raw_existing, list)
                else set()
            )
            repeated_by_domain[key] = sorted(existing | repeated)
        history[key] = sorted(previous | current)

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
        semantic = bool(report.failures) and all(
            failure.reason == "semantic_quality_incomplete"
            for failure in report.failures
        )
        maximum = (
            self._semantic_repair_limit(state)
            if semantic
            else self._metric(state, "max_verify_expand_iterations")
        )
        if attempts >= maximum:
            return self._block(state, "re_deep_spec_gate_failed")
        if not state.get("re_quality_repair_pending"):
            repair_targets = self._repair_specification_targets(report)
            if repair_targets is None:
                return self._block(state, "re_domain_manifest_invalid")
            attempts += 1
            for target in repair_targets:
                domain_id = str(target["domain_id"])
                source_id = str(target["source_id"])
                failure = next(
                    item
                    for item in report.failures
                    if item.source_id == source_id and item.domain_id == domain_id
                )
                if failure.semantic_finding_records:
                    spec_path = Path(failure.spec_path)
                    packet = ReRepairPacket(
                        source_id=source_id,
                        domain_id=domain_id,
                        spec_fingerprint=hashlib.sha256(
                            spec_path.read_bytes()
                        ).hexdigest(),
                        attempt=attempts,
                        findings=tuple(
                            ReRepairFinding(
                                finding_id=item.finding_id,
                                category=item.category,
                                text=item.text,
                                source_evidence=item.source_evidence,
                            )
                            for item in failure.semantic_finding_records
                        ),
                    )
                    target["repair_packet"] = packet.to_json_dict()
                    self._record_repeated_findings(state, packet)
            state["re_quality_repair_attempts"] = attempts
            state["re_quality_repair_pending"] = True
            state["re_quality_repair_snapshot"] = self._repair_snapshot(report)
            state["re_specification_targets"] = repair_targets
        state["phase"] = "re-extract-2-specify"
        self._save_state(state)
        return None

    def _semantic_validation_targets(
        self, plan: ReExecutionPlan
    ) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []
        for source in plan.refresh_sources:
            manifest = load_domain_manifest(
                domain_manifest_path(self._run_re_dir, source.id)
            )
            for domain in manifest.domains:
                spec_path = (
                    self._run_re_dir
                    / "sources"
                    / source.id
                    / "specs"
                    / domain.domain_id
                    / "spec.md"
                )
                if not spec_path.is_file():
                    continue
                targets.append(
                    {
                        "source_id": source.id,
                        "domain_id": domain.domain_id,
                    }
                )
        return targets

    def _semantic_target_fingerprints(
        self, target: dict[str, str], plan: ReExecutionPlan
    ) -> tuple[str, str]:
        source = next(
            source
            for source in plan.refresh_sources
            if source.id == target["source_id"]
        )
        source_fingerprint = hashlib.sha256(
            json.dumps(
                source.fingerprint.to_json_dict(), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        spec_path = (
            self._run_re_dir
            / "sources"
            / target["source_id"]
            / "specs"
            / target["domain_id"]
            / "spec.md"
        )
        spec_fingerprint = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        return source_fingerprint, spec_fingerprint

    def _semantic_expected_domains(
        self, plan: ReExecutionPlan
    ) -> set[tuple[str, str]]:
        return {
            (target["source_id"], target["domain_id"])
            for target in self._semantic_validation_targets(plan)
        }

    def _next_semantic_validation_target(
        self, state: dict, plan: ReExecutionPlan
    ) -> dict[str, str] | None:
        audits = state.get("re_semantic_domain_audits")
        if not isinstance(audits, dict):
            audits = {}
        for target in self._semantic_validation_targets(plan):
            key = f"{target['source_id']}/{target['domain_id']}"
            source_fingerprint, spec_fingerprint = self._semantic_target_fingerprints(
                target, plan
            )
            record = audits.get(key)
            if not isinstance(record, dict) or (
                record.get("protocol_version")
                != _SEMANTIC_DOMAIN_AUDIT_PROTOCOL_VERSION
                or record.get("source_fingerprint") != source_fingerprint
                or record.get("spec_fingerprint") != spec_fingerprint
                or not isinstance(record.get("review"), dict)
            ):
                return target
        return None

    def _store_semantic_domain_audit(
        self,
        state: dict,
        plan: ReExecutionPlan,
        target: dict[str, str],
        review: dict[str, object],
    ) -> None:
        source_fingerprint, spec_fingerprint = self._semantic_target_fingerprints(
            target, plan
        )
        audits = state.setdefault("re_semantic_domain_audits", {})
        if not isinstance(audits, dict):
            audits = {}
            state["re_semantic_domain_audits"] = audits
        key = f"{target['source_id']}/{target['domain_id']}"
        audits[key] = {
            "protocol_version": _SEMANTIC_DOMAIN_AUDIT_PROTOCOL_VERSION,
            "source_id": target["source_id"],
            "domain_id": target["domain_id"],
            "source_fingerprint": source_fingerprint,
            "spec_fingerprint": spec_fingerprint,
            "review": review,
        }

    def _semantic_validation_payload(
        self, state: dict, plan: ReExecutionPlan
    ) -> dict[str, object]:
        audits = state.get("re_semantic_domain_audits")
        if not isinstance(audits, dict):
            audits = {}
        domains = [
            audits[f"{target['source_id']}/{target['domain_id']}"]["review"]
            for target in self._semantic_validation_targets(plan)
        ]
        return {"schema_version": 1, "domains": domains}

    @staticmethod
    def _result_contract_for_phase(phase: str):
        from harness.echelon_result_schema import EchelonResultContract

        file_only_state_phases = {
            "re-extract-2-specify",
            "re-extract-3-verify",
            "re-extract-4-expand",
            "re-extract-5-validate",
            "re-extract-6-checklist",
            "re-extract-7-constitute",
        }
        return EchelonResultContract(
            allowed_state_update_keys=(
                frozenset() if phase in file_only_state_phases else None
            ),
            allowed_verdicts=frozenset({"DONE", "BLOCKED"}),
            unexpected_state_updates="reject",
        )

    @staticmethod
    def _phase_result_contract_prompt(phase: str) -> str:
        lines = [
            "\n\n## RE Result Contract",
            "Return exactly one final, unfenced YAML block starting with `echelon_result:`.",
            "Do not add prose after the final block.",
            f"Set `phase_id: {phase}`.",
            "Allowed verdicts for this RE dispatch are `DONE` and `BLOCKED`.",
        ]
        if phase in {
            "re-extract-2-specify",
            "re-extract-3-verify",
            "re-extract-4-expand",
            "re-extract-5-validate",
            "re-extract-6-checklist",
            "re-extract-7-constitute",
        }:
            lines.append(
                "Return `state_updates: {}`; controller-owned routing and quality "
                "state are applied after dispatch."
            )
        if phase == "re-extract-5-validate":
            lines.append(
                "Include exactly one `semantic_quality_review` object for the "
                "requested domain; the controller validates it before routing."
            )
        return "\n".join(lines) + "\n"

    def _prompt_for(
        self,
        phase: str,
        state: dict,
        plan: ReExecutionPlan,
        target: dict[str, object] | None = None,
        *,
        semantic_target: dict[str, str] | None = None,
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
            prompt += self._specification_target_prompt(target, state)
            synthesis_feedback = state.get("re_agent_result_detail")
            if (
                target.get("kind") == "workspace-synthesis"
                and isinstance(synthesis_feedback, str)
                and synthesis_feedback.startswith("workspace synthesis ")
            ):
                prompt += (
                    "\n## Controller Validation Feedback\n"
                    "The previous workspace synthesis was rejected: "
                    f"{synthesis_feedback[:4000]}\n"
                    "Read `workspace/architecture-map.json` and create every missing "
                    "workspace domain summary before returning DONE. Preserve the "
                    "source-owned specs and existing synthesis artifacts.\n"
                )
        if phase == "re-extract-5-validate":
            if semantic_target is None:
                raise ValueError("semantic validation target is required")
            prompt += self._semantic_domain_inventory_prompt(semantic_target)
            semantic_error = state.get("re_semantic_review_invalid_error")
            if isinstance(semantic_error, str) and semantic_error:
                prompt += (
                    "\n## Controller Validation Feedback\n"
                    "Your previous semantic_quality_review was rejected: "
                    f"{semantic_error}\n"
                    "Regenerate the requested domain review. Each REPAIR finding requires "
                    "valid owned-domain source evidence in exact `path:line` or "
                    "`path:start-end` form; path-only prose is invalid. Return DONE "
                    "only after the domain review satisfies this contract.\n"
                )
        resume_answer = state.get("resume_answer")
        if isinstance(resume_answer, str) and resume_answer.strip():
            prompt += (
                "\n## Human Resume Answer\n"
                f"{resume_answer.strip()}\n"
                "Use this answer only to resolve the blocker that requested it; "
                "preserve all deterministic RE boundaries and validation rules.\n"
            )
        return (
            prompt
            + self._phase_result_contract_prompt(phase)
            + _canonical_echelon_result_contract(self._extension_root)
        )

    @staticmethod
    def _semantic_domain_inventory_prompt(target: dict[str, str]) -> str:
        key = f"{target['source_id']}/{target['domain_id']}"
        lines = [
            "\n## Requested Semantic Domain",
            f"Requested semantic domain: `{key}`",
            "Your final echelon_result.semantic_quality_review.domains list must contain exactly one record for this domain and no sibling domains.",
            "Do not write RE_VALIDATOR_RESULT.yaml, semantic-quality-review-validator.json, ECHELON_RESULT.yaml, or any other sidecar result file. The controller reads only the final echelon_result block in your response.",
        ]
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

    def _prompt_metadata_for_target(
        self,
        plan: ReExecutionPlan,
        target: dict[str, object] | None,
        state: dict | None = None,
    ) -> dict[str, object]:
        """Restrict API-provider tools to controller-owned target boundaries."""
        if not isinstance(target, dict):
            return {}
        kind = target.get("kind")
        if kind == "workspace-synthesis":
            return self._workspace_synthesis_prompt_metadata(
                plan,
                retry_outputs=self._workspace_synthesis_retry_outputs(plan, state),
            )
        source_id = target.get("source_id")
        if kind not in {"source-domain", "source-support"} or not isinstance(
            source_id, str
        ):
            return {}
        source = next((item for item in plan.sources if item.id == source_id), None)
        if source is None:
            raise ValueError(f"unknown controller specification source: {source_id}")
        source_root = Path(source.absolute_path).resolve()
        read_roots = [str(self._run_re_dir.resolve())]
        if kind == "source-domain":
            root = target.get("root")
            domain_id = target.get("domain_id")
            if not isinstance(root, str) or not root or not isinstance(domain_id, str):
                raise ValueError("invalid controller source-domain tool scope")
            read_roots.append(str((source_root / root).resolve()))
            write_paths = [
                str(
                    (
                        self._run_re_dir
                        / "sources"
                        / source_id
                        / "specs"
                        / domain_id
                        / "spec.md"
                    ).resolve()
                )
            ]
        else:
            read_roots.append(str(source_root))
            write_paths = [
                str(
                    (
                        self._run_re_dir
                        / "sources"
                        / source_id
                        / "supporting-artifacts.md"
                    ).resolve()
                )
            ]
        return {
            "tool_read_roots": read_roots,
            "tool_write_paths": write_paths,
        }

    def _workspace_synthesis_prompt_metadata(
        self,
        plan: ReExecutionPlan,
        *,
        retry_outputs: tuple[Path, ...] = (),
    ) -> dict[str, object]:
        published, canonical_source_ids = self._validated_workspace_inputs(plan)
        read_roots = [self._run_re_dir.resolve()]
        if canonical_source_ids:
            if published is None:
                raise ValueError("canonical input index is missing")
            try:
                canonical = canonical_re_artifacts(self._project_root, published)
            except ReRegistryError as exc:
                raise ValueError(
                    f"cannot authenticate canonical RE artifacts: {exc}"
                ) from exc
            source_manifests = canonical.get("source_manifests")
            if not isinstance(source_manifests, dict):
                raise ValueError("canonical source manifest registry is invalid")
            for source_id in canonical_source_ids:
                expected_manifest = (
                    self._project_root
                    / "re"
                    / "sources"
                    / source_id
                    / "manifest.json"
                )
                if source_manifests.get(source_id) != str(expected_manifest):
                    raise ValueError(
                        f"canonical source manifest mismatch for {source_id}"
                    )
                source_root = expected_manifest.parent
                if source_root.is_symlink() or source_root.resolve() != source_root:
                    raise ValueError(
                        f"canonical source root is unsafe for {source_id}"
                    )
                read_roots.append(source_root)
            workspace_root = self._project_root / "re" / "workspace"
            if workspace_root.is_symlink() or workspace_root.resolve() != workspace_root:
                raise ValueError("canonical workspace root is unsafe")
            read_roots.append(workspace_root)

        write_paths = retry_outputs or self._workspace_synthesis_output_paths(plan)
        return {
            "tool_read_roots": [str(path) for path in read_roots],
            "tool_write_paths": [str(path) for path in write_paths],
            "tool_forbidden_roots": sorted(
                {
                    str(Path(source.absolute_path).resolve())
                    for source in plan.sources
                }
            ),
        }

    def _workspace_synthesis_output_paths(
        self, plan: ReExecutionPlan
    ) -> tuple[Path, ...]:
        write_paths = {
            self._workspace_synthesis_run_path("workspace", name)
            for name in ("overview.md", "relationships.md", "contracts.md")
        }
        for source in plan.refresh_sources:
            source_id = self._workspace_synthesis_component(source.id)
            write_paths.update(
                self._workspace_synthesis_run_path("sources", source_id, name)
                for name in (
                    "overview.md",
                    "architecture.md",
                    "contracts.md",
                    "components.md",
                )
            )
        architecture = load_re_architecture_map(
            self._run_re_dir / "workspace" / "architecture-map.json"
        )
        write_paths.update(
            self._workspace_synthesis_run_path(
                "workspace",
                "domains",
                f"{self._workspace_synthesis_component(domain_id)}.md",
            )
            for domain_id in {domain.domain_id for domain in architecture.domains}
        )
        return tuple(sorted(write_paths))

    def _workspace_synthesis_retry_outputs(
        self,
        plan: ReExecutionPlan,
        state: dict | None,
    ) -> tuple[Path, ...]:
        """Return validated missing outputs for a bounded synthesis repair pass."""
        if not isinstance(state, dict):
            return ()
        detail = state.get("re_agent_result_detail")
        prefix = "workspace synthesis has missing or empty artifacts: "
        if not isinstance(detail, str) or not detail.startswith(prefix):
            return ()
        expected = {
            path.relative_to(self._run_re_dir).as_posix(): path
            for path in self._workspace_synthesis_output_paths(plan)
        }
        requested = [
            item.strip() for item in detail.removeprefix(prefix).split(",") if item.strip()
        ]
        outputs = [expected[item] for item in requested if item in expected]
        return tuple(sorted(set(outputs)))

    def _validated_workspace_inputs(
        self, plan: ReExecutionPlan
    ) -> tuple[PublishedReIndex | None, tuple[str, ...]]:
        path = self._run_re_dir / "re-workspace-inputs.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read workspace inputs {path}: {exc}") from exc
        try:
            run_relative = self._run_re_dir.relative_to(self._project_root).as_posix()
        except ValueError as exc:
            raise ValueError("run RE directory is outside the workspace") from exc
        expected = build_re_workspace_inputs(plan, run_relative=run_relative)
        if payload != expected:
            raise ValueError("workspace inputs do not match the execution plan")
        index_path = self._project_root / "re" / "index.json"
        if index_path.exists() and (
            index_path.is_symlink()
            or not index_path.is_file()
            or index_path.resolve() != index_path
        ):
            raise ValueError(f"published RE index is unsafe: {index_path}")
        try:
            published = load_published_index(self._project_root)
        except ReRegistryError as exc:
            raise ValueError(f"cannot authenticate canonical input index: {exc}") from exc

        canonical: list[str] = []
        for source in plan.sources:
            if source.action in {"refresh", "skip-empty"}:
                continue
            registered = published.sources.get(source.id) if published is not None else None
            usable = bool(
                registered is not None
                and registered.source_path == source.path
                and registered.fingerprint == source.fingerprint.value
                and registered.profile_hash == source.fingerprint.profile_hash
                and published_source_is_usable(
                    self._project_root, published, source.id
                )
            )
            if usable:
                canonical.append(source.id)
            elif source.action == "reuse":
                raise ValueError(
                    f"canonical input authentication failed for {source.id}"
                )
        return published, tuple(sorted(canonical))

    def _workspace_synthesis_run_path(self, *parts: str) -> Path:
        candidate = self._run_re_dir.joinpath(*parts)
        cursor = self._run_re_dir
        for part in parts:
            cursor /= part
            if cursor.is_symlink():
                raise ValueError(
                    f"symlinked workspace synthesis path: {candidate}"
                )
        if candidate.exists():
            if not candidate.is_file():
                raise ValueError(f"unsafe workspace synthesis path: {candidate}")
            if candidate.stat().st_nlink != 1:
                raise ValueError(
                    f"hardlinked workspace synthesis path: {candidate}"
                )
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self._run_re_dir.resolve()):
            raise ValueError(f"unsafe workspace synthesis path: {candidate}")
        return resolved

    @staticmethod
    def _workspace_synthesis_component(value: str) -> str:
        if (
            not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            or Path(value).name != value
        ):
            raise ValueError(f"unsafe workspace synthesis component: {value}")
        return value

    def _clean_workspace_synthesis_sources(
        self,
        state: dict,
        plan: ReExecutionPlan,
    ) -> None:
        sources_root = self._run_re_dir / "sources"
        if sources_root.is_symlink():
            raise ValueError(f"unsafe workspace synthesis path: {sources_root}")
        if not sources_root.exists():
            return
        refresh_ids = {source.id for source in plan.refresh_sources}
        removed: list[str] = []
        for path in sources_root.iterdir():
            if path.name in refresh_ids:
                continue
            relative = path.relative_to(self._run_re_dir).as_posix()
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(relative)
        if removed:
            state["re_workspace_synthesis_cleanup"] = sorted(removed)
            self._save_state(state)

    def _evaluate_specification_target(
        self,
        state: dict,
        plan: ReExecutionPlan,
        target: dict[str, object],
        *,
        agent_block_detail: str | None = None,
    ) -> ReControllerResult | None:
        """Route one specification target from deterministic evidence, not verdict alone.

        The controller owns the source-domain quality gate and must turn the
        observed incomplete artifact into bounded repair work. A BLOCKED
        response with a passing target remains an explicit agent blocker
        instead of being silently accepted.
        """
        if (
            target.get("kind") == "workspace-synthesis"
            and agent_block_detail is None
        ):
            synthesis_error = self._workspace_synthesis_error(plan)
            if synthesis_error is not None:
                state["re_agent_result_detail"] = synthesis_error
                if self._schedule_workspace_synthesis_repair(
                    state, plan, synthesis_error
                ):
                    return None
                return self._block(state, "re_workspace_synthesis_incomplete")

        target_report = self._target_quality_report(plan, target)
        if target_report is not None and not target_report.passed:
            source_id = str(target["source_id"])
            domain_id = str(target["domain_id"])
            report_path = write_re_target_quality_report(
                self._run_re_dir, source_id, domain_id, target_report
            )
            attempts = self._record_target_quality_failure(state, target, target_report)
            repair_limit = self._target_quality_repair_limit(state, target_report)
            state["re_target_quality_gate_report"] = str(report_path)
            self._report_target_quality_failure(
                source_id,
                domain_id,
                attempts,
                repair_limit,
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
                    if repair_count > repair_limit:
                        source_report = measure_source_quality(
                            self._run_re_dir,
                            plan,
                            source_id,
                            coverage_threshold=self._metric(
                                state, "coverage_threshold"
                            ),
                        )
                        source_report_path = write_re_source_quality_report(
                            self._run_re_dir, source_report
                        )
                        self._mark_active_source_partial(
                            state, source_id, source_report_path
                        )
                        self._activate_next_source(state, plan)
                        return None
            if attempts > repair_limit:
                return self._block(state, "re_domain_deep_spec_gate_failed")
            return None

        self._clear_target_quality_failure(state, target)
        if agent_block_detail is not None:
            return self._block(state, self._agent_blocked_reason(agent_block_detail))
        self._complete_specification_target(state, target)
        return None

    def _run_specification_target_post_dispatch(
        self,
        state: dict,
        plan: ReExecutionPlan,
        target: dict[str, object],
        *,
        agent_block_detail: str | None = None,
    ) -> ReControllerResult | None:
        """Run controller-owned post-dispatch gates for one RE specification target."""
        return self._evaluate_specification_target(
            state,
            plan,
            target,
            agent_block_detail=agent_block_detail,
        )

    @staticmethod
    def _dispatch_failure_detail(
        timed_out: bool, exit_code: int, provider_detail: str = ""
    ) -> str:
        details: list[str] = []
        if timed_out:
            details.append("agent timed out")
        if exit_code != 0:
            details.append(f"agent exited with code {exit_code}")
        detail = " ".join(provider_detail.split())
        if detail:
            details.append(detail[:500])
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
        repair_status = (
            f"repair attempt {attempts}/{budget}"
            if attempts <= budget
            else f"repair budget exhausted ({budget}/{budget})"
        )
        message = (
            "[re] target quality failed: "
            f"{source_id}/{domain_id}; {repair_status}"
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

    @staticmethod
    def _target_quality_failure_guidance(report_path: Path) -> str:
        """Render the exact deterministic findings into a compact repair checklist."""
        if not report_path.is_file():
            return ""
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        failures = payload.get("failures") if isinstance(payload, dict) else None
        if not isinstance(failures, list):
            return ""
        findings: list[str] = []
        list_fields = (
            ("missing_sections", "Missing sections"),
            ("invalid_source_evidence", "Invalid source evidence"),
            ("scenarios_without_acceptance", "Scenarios without acceptance cases"),
            ("scenarios_without_evidence", "Scenarios without evidence"),
            (
                "functional_requirements_without_evidence",
                "Functional requirements without evidence",
            ),
            (
                "non_functional_requirements_without_evidence",
                "Non-functional requirements without evidence",
            ),
            ("semantic_findings", "Semantic findings"),
        )
        count_fields = (
            ("scenario_count", "expected_scenario_count", "Scenario count"),
            (
                "functional_requirement_count",
                "expected_functional_requirement_count",
                "Functional requirement count",
            ),
            (
                "non_functional_requirement_count",
                "expected_non_functional_requirement_count",
                "Non-functional requirement count",
            ),
        )
        for failure in failures:
            if not isinstance(failure, dict):
                continue
            for key, label in list_fields:
                values = failure.get(key)
                if isinstance(values, list) and values:
                    rendered = ", ".join(str(value) for value in values)
                    findings.append(f"- {label}: {rendered}")
            for actual_key, expected_key, label in count_fields:
                actual = failure.get(actual_key)
                expected = failure.get(expected_key)
                if (
                    isinstance(actual, int)
                    and isinstance(expected, int)
                    and actual < expected
                ):
                    findings.append(f"- {label}: {actual}; required: {expected}")
            semantic = failure.get("semantic_preflight_findings")
            if isinstance(semantic, list):
                for item in semantic:
                    if isinstance(item, dict):
                        message = item.get("message")
                        code = item.get("code")
                        if isinstance(message, str) and message:
                            prefix = f" [{code}]" if isinstance(code, str) and code else ""
                            findings.append(f"- Semantic preflight{prefix}: {message}")
                    elif isinstance(item, str) and item:
                        findings.append(f"- Semantic preflight: {item}")
        if not findings:
            return ""
        return (
            "\n## Authoritative Deterministic Repair Findings\n"
            + "\n".join(findings)
            + "\nFix every listed finding. Do not substitute evidence from outside the "
            "absolute owned domain root. The controller report remains authoritative.\n"
        )

    def _specification_target_prompt(
        self,
        target: dict[str, object],
        state: dict | None = None,
    ) -> str:
        kind = target.get("kind")
        if kind == "workspace-synthesis":
            plan = self._load_plan()
            refreshed = self._workspace_synthesis_id_list(
                source.id for source in plan.sources if source.action == "refresh"
            )
            reused = self._workspace_synthesis_id_list(
                source.id for source in plan.sources if source.action == "reuse"
            )
            empty = self._workspace_synthesis_id_list(
                source.id for source in plan.sources if source.action == "skip-empty"
            )
            unavailable = self._workspace_synthesis_id_list(
                source.id
                for source in plan.sources
                if source.action in {"missing", "exclude"}
            )
            removed = self._workspace_synthesis_id_list(plan.removed_sources)
            retry_outputs = self._workspace_synthesis_retry_outputs(plan, state)
            output_paths = retry_outputs or self._workspace_synthesis_output_paths(plan)
            required_outputs = "\n".join(
                f"- `{path}`"
                for path in output_paths
            )
            output_instruction = (
                "Repair only these missing workspace-synthesis output files. "
                "Do not rewrite already-valid synthesis artifacts:\n"
                if retry_outputs
                else "Required workspace-synthesis output files (write every file exactly once):\n"
            )
            return (
                "\n## Controller-Owned Specification Target\n"
                "Generate source overviews, source-owned synthesis, and workspace synthesis only. "
                "Source-owned outputs are permitted only for refreshed source IDs. All required "
                "source-domain specs have already been dispatched independently.\n"
                f"Refreshed source IDs: {refreshed}\n"
                f"Reused source IDs: {reused}\n"
                f"Empty source IDs: {empty}\n"
                f"Missing/excluded source IDs: {unavailable}\n"
                f"Removed source IDs: {removed}\n"
                + output_instruction
                + f"{required_outputs}\n"
                "Read source semantics only from the current run RE output directory and "
                "canonical published RE artifacts referenced by `re-workspace-inputs.json`. "
                "Do not inspect, search, count, summarize, or cite any configured live source root, "
                "including the selected source, a `sources/{source-id}` path, or its absolute equivalent. "
                "Do not use `source_path` as a filesystem input. If a reused source's canonical input "
                "is missing or unreadable, return BLOCKED; never fall back to a live source root.\n"
                "Write source-owned overview, architecture, contracts, and components synthesis only "
                "for the refreshed source IDs above. Do not create any staged source file or directory "
                "for reused, empty, unavailable, or removed sources. Empty-source semantic artifacts "
                "are controller/publication-owned. Do not create, rename, or rewrite any source-domain "
                "spec. Return an "
                "`echelon_result` with `state_updates: {}`; lifecycle routing and "
                "workspace-synthesis completion are controller-owned.\n"
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
        plan = self._load_plan()
        source = next((item for item in plan.sources if item.id == source_id), None)
        if source is None:
            raise ValueError(f"unknown controller specification source: {source_id}")
        source_root = Path(source.absolute_path).resolve()
        absolute_domain_root = (source_root / root).resolve()
        quality_failure_guidance = self._target_quality_failure_guidance(target_report)
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
        semantic_repair = ""
        packet_raw = target.get("repair_packet")
        if isinstance(packet_raw, dict):
            packet = ReRepairPacket.from_json_dict(packet_raw)
            lines = []
            for finding in packet.findings:
                lines.append(
                    f"- `{finding.finding_id}` [{finding.category}]: {finding.text}\n"
                    f"  Evidence: {', '.join(finding.source_evidence)}"
                )
            semantic_repair = (
                "\n## Controller-Owned Semantic Repair Packet\n"
                f"Attempt: {packet.attempt}\n"
                f"Spec fingerprint: `{packet.spec_fingerprint}`\n"
                + "\n".join(lines)
                + "\nModify only the scenarios, requirements, entities, edge cases, or "
                "coverage rows needed by these findings. Preserve unrelated content "
                "and every still-valid citation.\n"
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
            f"Source repository root: `{source_root}`\n"
            f"Absolute owned domain root: `{absolute_domain_root}`\n"
            f"RE output directory: `{self._run_re_dir.resolve()}`\n"
            f"Domain manifest: `{manifest}`\n"
            "Do not look for source code below the RE output directory; it contains "
            "artifacts and analysis, not a staged repository copy. When the provider "
            "offers `read_domain_pack`, use it first with the RE output directory, source "
            "ID, and domain ID above. Read source code only from the absolute owned domain "
            "root. You may read staged extraction artifacts from the RE output directory, "
            "but they are context rather than source citations. "
            "Every source citation must be a backticked `path/to/file:line` reference "
            "using either the source-root path or a path relative to the owned domain "
            "root; it must resolve within that domain. Never use Markdown-link citations. "
            "Never search outside the owned domain root for tests. If no tests exist "
            "inside it, record the canonical `tests` Behavior Coverage row as "
            "`not-observed`. A rejected out-of-scope read is authoritative and final; "
            "do not retry it or broaden the requested path. "
            "Include at least five distinct valid citations. Do not write another domain spec, "
            "source overview, or workspace synthesis. Write only this target's `spec.md`; "
            "never create backup, temporary, alternate, or scratch files beside it.\n"
            + coverage_repair
            + semantic_repair
            + quality_failure_guidance
            + "Before returning DONE, make the spec satisfy the deterministic "
            "source-domain quality gate. The controller runs that gate after "
            "dispatch and records the authoritative target-quality report when "
            "the spec is not acceptable. Do not claim that a citation is valid "
            "because its path exists: its line range must also exist.\n"
            + quality_contract
            + architecture_contract
            + (
                f"Read `{target_report}` before editing: it is the exact deterministic "
                "failure report for this target.\n"
                if target_report.is_file()
                else ""
            )
            + "`echelon_result` is a final YAML response block, not a callable tool. "
            "Do not invoke a function named `echelon_result` and do not call more tools "
            "after the target artifact is complete.\n"
        )

    @staticmethod
    def _workspace_synthesis_id_list(source_ids: Iterable[str]) -> str:
        values = sorted(source_ids)
        return ", ".join(f"`{source_id}`" for source_id in values) or "(none)"

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
        if not plan.analysis_required:
            if not (self._run_re_dir / "analysis.json").is_file():
                return "materialized analysis.json missing for no-analysis RE plan"
            return None
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
                    "perlgraph_analysis": str(
                        self._run_re_dir / "perlgraph-analysis.json"
                    )
                    if (self._run_re_dir / "perlgraph-analysis.json").is_file()
                    else None,
                    "perlgraph_summary": str(
                        self._run_re_dir / "perlgraph-summary.json"
                    )
                    if (self._run_re_dir / "perlgraph-summary.json").is_file()
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

    def _current_invocation_ms(self) -> int:
        if self._invocation_started_monotonic <= 0:
            return 0
        return max(
            0,
            int((time.monotonic() - self._invocation_started_monotonic) * 1000),
        )

    def _finish_active_interval(self) -> None:
        elapsed = self._current_invocation_ms()
        if elapsed <= 0 or not (self._run_re_dir / "state.json").is_file():
            return
        state = self._load_state()
        state["re_active_duration_ms"] = self._metric(
            state, "re_active_duration_ms"
        ) + elapsed
        intervals = state.get("re_execution_intervals")
        if not isinstance(intervals, list):
            intervals = []
            state["re_execution_intervals"] = intervals
        ended = datetime.now(timezone.utc)
        started = ended.timestamp() - (elapsed / 1000)
        intervals.append(
            {
                "started_at": datetime.fromtimestamp(
                    started, timezone.utc
                ).isoformat().replace("+00:00", "Z"),
                "ended_at": ended.isoformat().replace("+00:00", "Z"),
                "duration_ms": elapsed,
            }
        )
        self._save_state(state)

    def _account_provider_usage(self, state: dict, result: object) -> None:
        raw_total = getattr(result, "token_usage", 0)
        total = (
            int(raw_total)
            if isinstance(raw_total, (int, float)) and not isinstance(raw_total, bool)
            else 0
        )
        details = getattr(result, "token_usage_details", None)
        known = total > 0 or (isinstance(details, dict) and bool(details))
        if known:
            state["re_token_usage"] = self._metric(state, "re_token_usage") + max(
                0, total
            )
        else:
            state["re_unknown_token_dispatches"] = self._metric(
                state, "re_unknown_token_dispatches"
            ) + 1

    def _record_dispatch_span(
        self,
        state: dict,
        *,
        phase: str,
        target: dict[str, object] | None,
        semantic_target: dict[str, str] | None,
        result: object,
        started: datetime,
        ended: datetime,
    ) -> None:
        profile = state.get("re_execution_profile")
        profile_dict = profile if isinstance(profile, dict) else {"name": "legacy"}
        trace_id = state.get("re_trace_id")
        if not isinstance(trace_id, str) or len(trace_id) != 32:
            trace_id = uuid.uuid4().hex
            state["re_trace_id"] = trace_id
        details = getattr(result, "token_usage_details", None)
        usage_mapping = dict(details) if isinstance(details, dict) else {}
        raw_total = getattr(result, "token_usage", 0)
        if (
            "total_tokens" not in usage_mapping
            and isinstance(raw_total, (int, float))
            and not isinstance(raw_total, bool)
            and int(raw_total) > 0
        ):
            usage_mapping["total_tokens"] = int(raw_total)
        usage = TokenUsage.from_mapping(usage_mapping)
        attributes: dict[str, object] = {
            "echelon.run.id": self._run_dir.name,
            "echelon.workflow.name": "re",
            "echelon.workflow.phase": phase,
            "echelon.agent.name": _PHASES[phase],
            "echelon.execution.profile": str(profile_dict.get("name") or "legacy"),
            "echelon.result.verdict": str(getattr(result, "verdict", None) or "UNKNOWN"),
            "gen_ai.operation.name": "agent",
        }
        provider = getattr(result, "provider_name", "")
        model = getattr(result, "model_name", "")
        if provider:
            attributes["gen_ai.provider.name"] = str(provider)
        if model:
            attributes["gen_ai.response.model"] = str(model)
        for field, attribute in (
            ("input_tokens", "gen_ai.usage.input_tokens"),
            ("output_tokens", "gen_ai.usage.output_tokens"),
            ("reasoning_output_tokens", "gen_ai.usage.reasoning.output_tokens"),
            ("cache_read_input_tokens", "gen_ai.usage.cache_read.input_tokens"),
            (
                "cache_creation_input_tokens",
                "gen_ai.usage.cache_creation.input_tokens",
            ),
        ):
            value = getattr(usage, field)
            if value is not None:
                attributes[attribute] = value
        selected = semantic_target or target or {}
        for source_key, attribute in (
            ("source_id", "echelon.source.id"),
            ("domain_id", "echelon.domain.id"),
        ):
            value = selected.get(source_key)
            if isinstance(value, str) and value:
                attributes[attribute] = value
        store = TelemetryStore(
            self._run_dir,
            workflow="re",
            run_id=self._run_dir.name,
            profile=profile_dict,
            trace_id=trace_id,
        )
        duration_ms = max(0, int((ended - started).total_seconds() * 1000))
        store.append_span(
            ExecutionSpan(
                trace_id=trace_id,
                span_id=uuid.uuid4().hex[:16],
                parent_span_id=None,
                name=phase,
                start_time=started.isoformat().replace("+00:00", "Z"),
                end_time=ended.isoformat().replace("+00:00", "Z"),
                duration_ms=duration_ms,
                status=(
                    "ERROR"
                    if getattr(result, "timed_out", False)
                    or int(getattr(result, "exit_code", 0) or 0) != 0
                    else "OK"
                ),
                attributes=attributes,
                token_usage=usage,
            )
        )

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

    def _schedule_workspace_synthesis_repair(
        self,
        state: dict,
        plan: ReExecutionPlan,
        detail: str,
    ) -> bool:
        """Schedule one scoped retry when file validation finds only missing outputs."""
        retry_outputs = self._workspace_synthesis_retry_outputs(
            plan, {"re_agent_result_detail": detail}
        )
        if not retry_outputs:
            return False
        attempts = self._metric(state, "re_workspace_synthesis_repair_attempts")
        if attempts >= _WORKSPACE_SYNTHESIS_REPAIR_LIMIT:
            return False
        attempts += 1
        state["re_workspace_synthesis_repair_attempts"] = attempts
        print(
            "[re] workspace synthesis incomplete; automatic repair attempt "
            f"{attempts}/{_WORKSPACE_SYNTHESIS_REPAIR_LIMIT} for "
            f"{len(retry_outputs)} missing artifact(s)",
            flush=True,
        )
        return True

    def _workspace_synthesis_error(self, plan: ReExecutionPlan) -> str | None:
        """Return a deterministic error for an incomplete staged synthesis."""
        forbidden: list[str] = []
        refresh_ids = {source.id for source in plan.refresh_sources}
        sources_root = self._run_re_dir / "sources"
        try:
            if sources_root.is_symlink():
                forbidden.append("sources")
            elif sources_root.is_dir():
                forbidden.extend(
                    path.relative_to(self._run_re_dir).as_posix()
                    for path in sources_root.iterdir()
                    if path.name not in refresh_ids
                )
        except OSError:
            forbidden.append("sources")
        if forbidden:
            return (
                "workspace synthesis created non-refresh source artifacts: "
                + ", ".join(sorted(forbidden))
            )

        required = [
            self._run_re_dir / "workspace" / "overview.md",
            self._run_re_dir / "workspace" / "relationships.md",
            self._run_re_dir / "workspace" / "contracts.md",
        ]
        required.extend(
            self._run_re_dir / "sources" / source.id / "overview.md"
            for source in plan.refresh_sources
        )
        for source in plan.refresh_sources:
            required.extend(
                (
                    self._run_re_dir / "sources" / source.id / "architecture.md",
                    self._run_re_dir / "sources" / source.id / "contracts.md",
                    self._run_re_dir / "sources" / source.id / "components.md",
                )
            )
        try:
            architecture = load_re_architecture_map(
                self._run_re_dir / "workspace" / "architecture-map.json"
            )
        except ValueError as exc:
            return f"workspace synthesis architecture map is invalid: {exc}"
        required.extend(
            self._run_re_dir / "workspace" / "domains" / f"{domain_id}.md"
            for domain_id in sorted(
                {domain.domain_id for domain in architecture.domains}
            )
        )

        invalid: list[str] = []
        for path in required:
            relative = path.relative_to(self._run_re_dir).as_posix()
            try:
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or path.stat().st_nlink != 1
                    or not path.read_text(encoding="utf-8").strip()
                ):
                    invalid.append(relative)
            except OSError:
                invalid.append(relative)
        if invalid:
            return "workspace synthesis has missing or empty artifacts: " + ", ".join(
                invalid
            )
        return None

    def _recover_rejected_workspace_synthesis(
        self,
        state: dict,
        plan: ReExecutionPlan,
    ) -> bool:
        """Accept one known stranded synthesis only after artifact validation."""
        detail = state.get("re_agent_result_detail")
        last_dispatch = state.get("last_dispatch")
        targets = state.get("re_specification_targets")
        if not (
            state.get("status") == "blocked"
            and state.get("blocked_reason") == "re_agent_result_invalid"
            and state.get("phase") == "re-extract-2-specify"
            and isinstance(detail, str)
            and "re_workspace_synthesis_complete" in detail
            and isinstance(last_dispatch, dict)
            and last_dispatch.get("phase_id") == "re-extract-2-specify"
            and last_dispatch.get("agent") == "specifier"
            and last_dispatch.get("post_dispatch_complete") is False
            and isinstance(targets, list)
            and bool(targets)
            and isinstance(targets[0], dict)
            and targets[0].get("kind") == "workspace-synthesis"
            and state.get("re_workspace_synthesis_scope_protocol_version")
            == _WORKSPACE_SYNTHESIS_SCOPE_PROTOCOL_VERSION
        ):
            return False
        if self._workspace_synthesis_error(plan) is not None:
            return False

        target = targets[0]
        recovered = complete_dispatch(state, {"state_updates": {}})
        state.clear()
        state.update(recovered)
        self._complete_specification_target(state, target)
        state["status"] = "in_progress"
        state.pop("blocked_reason", None)
        state.pop("re_agent_result_detail", None)
        print(
            "[re] recovered completed workspace synthesis from validated staged artifacts",
            flush=True,
        )
        return True

    @staticmethod
    def _agent_result_without_controller_keys(
        payload: dict,
        target: dict[str, object] | None = None,
        *,
        phase: str = "",
    ) -> dict:
        updates = payload.get("state_updates")
        if not isinstance(updates, dict):
            return payload
        if isinstance(target, dict) and target.get("kind") in {
            "source-domain",
            "source-support",
            "workspace-synthesis",
        }:
            # Specification targets produce files; their queue and completion
            # transitions are controller-owned. Providers sometimes report
            # descriptive inventory or completion metadata, but none of it may
            # mutate RE routing state.
            return {**payload, "state_updates": {}}
        if phase in {
            "re-extract-2-specify",
            "re-extract-3-verify",
            "re-extract-4-expand",
            "re-extract-5-validate",
            "re-extract-6-checklist",
            "re-extract-7-constitute",
        }:
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
