"""Harness-owned execution controller for active workspace RE runs."""

from __future__ import annotations

import json
import os
import tempfile
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from harness.re_lock import ReExtractLocked, ReExtractionLock
from harness.re_planner import ReExecutionPlan
from harness.re_quality_gate import (
    ReQualityReport,
    validate_staged_re_quality,
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
        while True:
            phase = str(state.get("phase") or "re-extract-1-analyze")
            last_dispatch = state.get("last_dispatch")
            if (
                state.get("re_quality_repair_pending")
                and isinstance(last_dispatch, dict)
                and last_dispatch.get("phase_id") == phase
                and not last_dispatch.get("post_dispatch_complete", True)
            ):
                snapshot_reason = self._repair_snapshot_failure(state)
                if snapshot_reason is not None:
                    return self._block(state, snapshot_reason)
            if phase == "re-extract-0-preflight":
                state["phase"] = "re-extract-1-analyze"
                self._save_state(state)
                continue
            if phase not in _PHASES:
                return self._block(state, "re_controller_unknown_phase")

            state = write_last_dispatch(state, phase, _PHASES[phase])
            self._save_state(state)
            result = self._provider.exec_agent(
                str(self._project_root), self._prompt_for(phase, state)
            )
            if result.blocked:
                return self._block(state, "re_agent_dispatch_failed")
            payload = result.echelon_result
            if not isinstance(payload, dict) or payload.get("verdict") != "DONE":
                return self._block(state, "re_agent_result_invalid")
            try:
                state = complete_dispatch(state, self._agent_result_without_controller_keys(payload))
            except (KeyError, ValueError):
                return self._block(state, "re_agent_result_invalid")
            if phase == "re-extract-2-specify" and state.get("re_quality_repair_pending"):
                snapshot_reason = self._repair_snapshot_failure(state)
                if snapshot_reason is not None:
                    return self._block(state, snapshot_reason)
            self._save_state(state)

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
            state["phase"] = "re-extract-2-specify"
        elif phase == "re-extract-2-specify":
            report = validate_staged_re_quality(self._run_re_dir, plan)
            report_path = write_re_quality_report(self._run_re_dir, report)
            state["re_quality_gate_report"] = str(report_path)
            if not report.passed:
                return self._schedule_quality_repair(state, report)
            state.pop("re_quality_repair_pending", None)
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
            if self._metric(state, "resolution_pct") < self._metric(state, "resolution_threshold"):
                iterations = self._metric(state, "validate_iterations")
                if iterations >= self._metric(state, "max_validate_iterations"):
                    return self._block(state, "re_resolution_threshold_not_met")
                state["validate_iterations"] = iterations + 1
                state["phase"] = "re-extract-5-validate"
            else:
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
            attempts += 1
            state["re_quality_repair_attempts"] = attempts
            state["re_quality_repair_pending"] = True
            state["re_quality_repair_snapshot"] = self._repair_snapshot(report)
        state["phase"] = "re-extract-2-specify"
        self._save_state(state)
        return None

    def _prompt_for(self, phase: str, state: dict) -> str:
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
        return prompt

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

    def _repair_snapshot_failure(self, state: dict) -> str | None:
        snapshot = state.get("re_quality_repair_snapshot")
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
            if target.is_file()
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
            if relative in {"state.json", "quality/deep-spec-gate.json"}:
                continue
            if relative in target_files or any(
                relative.startswith(root + "/") for root in target_roots
            ):
                continue
            paths.append(path)
        return self._snapshot_paths(paths)

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
        }
        filtered = {key: value for key, value in updates.items() if key not in controlled}
        return {**payload, "state_updates": filtered}

    @staticmethod
    def _metric(state: dict, key: str) -> int:
        value = state.get(key, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0
