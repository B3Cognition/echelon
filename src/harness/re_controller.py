"""Harness-owned execution controller for active workspace RE runs."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

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
    quality_target_for_domain,
    validate_semantic_quality_review,
    validate_staged_re_domain_quality,
    validate_staged_re_quality,
    write_re_semantic_quality_report,
    write_re_target_quality_report,
    write_re_quality_report,
)
from kernel.re_state import complete_dispatch, init_re_state, write_last_dispatch


class ReAgentProvider(Protocol):
    def exec_agent(self, project_root: str, prompt: str): ...


@dataclass(frozen=True)
class ReControllerResult:
    completed: bool
    blocked_reason: str | None = None


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
_REPAIR_EPHEMERAL_OUTPUTS = frozenset({"state.json", "quality/deep-spec-gate.json"})


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
        if state.get("status") == "blocked":
            state["status"] = "in_progress"
            state.pop("blocked_reason", None)
            self._save_state(state)
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
                target_error = self._prepare_specification_target(target)
                if target_error is not None:
                    return self._block(state, target_error)

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
                    str(self._project_root), self._prompt_for(phase, state, target)
                )
                if result.blocked:
                    return self._block(state, "re_agent_dispatch_failed")
                payload = result.echelon_result
            if not isinstance(payload, dict) or payload.get("verdict") != "DONE":
                state["re_agent_result_detail"] = (
                    "missing result object"
                    if not isinstance(payload, dict)
                    else f"unexpected verdict: {payload.get('verdict')!r}"
                )
                return self._block(state, "re_agent_result_invalid")
            try:
                state = complete_dispatch(state, self._agent_result_without_controller_keys(payload))
            except (KeyError, ValueError) as exc:
                state["re_agent_result_detail"] = str(exc)
                return self._block(state, "re_agent_result_invalid")
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
                target_report = self._target_quality_report(plan, target)
                if target_report is not None and not target_report.passed:
                    source_id = str(target["source_id"])
                    domain_id = str(target["domain_id"])
                    report_path = write_re_target_quality_report(
                        self._run_re_dir, source_id, domain_id, target_report
                    )
                    attempts = self._record_target_quality_failure(
                        state, target, target_report
                    )
                    state["re_target_quality_gate_report"] = str(report_path)
                    if attempts > self._metric(state, "max_verify_expand_iterations"):
                        return self._block(state, "re_domain_deep_spec_gate_failed")
                    self._save_state(state)
                    continue
                self._clear_target_quality_failure(state, target)
                self._complete_specification_target(state, target)
            if phase == "re-extract-5-validate":
                semantic_report, semantic_error = validate_semantic_quality_review(
                    self._run_re_dir,
                    plan,
                    payload.get("semantic_quality_review")
                    if isinstance(payload, dict)
                    else None,
                )
                if semantic_error is not None or semantic_report is None:
                    state["re_agent_result_detail"] = (
                        semantic_error or "semantic quality review was unavailable"
                    )
                    return self._block(state, "re_semantic_quality_review_invalid")
                semantic_report_path = write_re_semantic_quality_report(
                    self._run_re_dir, semantic_report
                )
                state["re_semantic_quality_report"] = str(semantic_report_path)
                if not semantic_report.passed:
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
            state["re_domain_partition_version"] = DOMAIN_PARTITION_VERSION
            state["re_specification_targets"] = self._initial_specification_targets(plan)
            state["re_workspace_synthesis_complete"] = False
            state["phase"] = "re-extract-2-specify"
        elif phase == "re-extract-2-specify":
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
        return prompt

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
        quality_contract = ""
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
            "source overview, or workspace synthesis.\n"
            + quality_contract
            + (
                f"Read `{target_report}` before editing: it is the exact deterministic "
                "failure report for this target.\n"
                if target_report.is_file()
                else ""
            )
        )

    def _prepare_specification_target(self, target: dict[str, object]) -> str | None:
        """Create the one writable target so constrained providers can edit it."""
        if target.get("kind") != "source-domain":
            return None
        source_id = target.get("source_id")
        domain_id = target.get("domain_id")
        if not all(isinstance(value, str) and value for value in (source_id, domain_id)):
            return "re_specification_target_invalid"
        path = self._run_re_dir / "sources" / source_id / "specs" / domain_id / "spec.md"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
        except OSError as exc:
            return f"re_specification_target_prepare_failed: {exc}"
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
        return ReControllerResult(completed=False, blocked_reason=reason)

    @staticmethod
    def _agent_result_without_controller_keys(payload: dict) -> dict:
        updates = payload.get("state_updates")
        if not isinstance(updates, dict):
            return payload
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
        }
        filtered = {key: value for key, value in updates.items() if key not in controlled}
        return {**payload, "state_updates": filtered}

    @staticmethod
    def _metric(state: dict, key: str) -> int:
        value = state.get(key, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0
