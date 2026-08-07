"""First-class run/continue/resume lifecycle for workspace reverse engineering."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import replace
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from echelon.workspace_model import discover_workspace
from harness.blocked_decision import (
    ensure_blocked_decision,
    mark_blocked_decision_resolved,
)
from harness.config import get_full_resolved_config
from harness.re_controller import ReExtractionController
from harness.re_fingerprint import ReFingerprintProfile
from harness.re_materializer import materialize_re_run_context
from harness.re_planner import build_re_execution_plan
from harness.re_profiles import migrate_legacy_re_profile, resolve_re_execution_profile
from harness.re_registry import load_published_index
from kernel.re_state import init_re_state


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class ReLifecycleError(RuntimeError):
    """Raised when RE lifecycle state or input is unsafe."""


@dataclass(frozen=True)
class ReLifecycleResult:
    status: Literal["done", "blocked", "failed"]
    run_id: str = ""
    phase: str = ""
    blocked_reason: str = ""
    blocked_detail: str = ""
    generation: int = 0
    no_work: bool = False


def resolve_current_re_run(project_root: Path) -> Path | None:
    """Resolve the dedicated active RE run without consulting spec markers."""
    root = project_root.resolve()
    runs = root / "runs"
    marker = runs / ".current-re"
    if not marker.exists():
        return None
    if not marker.is_file() or marker.is_symlink():
        raise ReLifecycleError(f"unsafe RE current marker: {marker}")
    run_id = marker.read_text(encoding="utf-8").strip()
    if not _SAFE_RUN_ID.fullmatch(run_id) or not run_id.startswith("re-"):
        raise ReLifecycleError(f"unsafe RE run id: {run_id!r}")
    run_dir = runs / run_id
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ReLifecycleError(f"RE run does not exist: {run_id}")
    resolved = run_dir.resolve()
    if not resolved.is_relative_to(runs.resolve()):
        raise ReLifecycleError(f"RE run escapes workspace: {run_id}")
    return resolved


def resolve_re_fingerprint_profile(project_root: Path) -> ReFingerprintProfile:
    """Resolve extraction settings that participate in RE fingerprints."""
    config = get_full_resolved_config(project_root)
    re_config = config.get("re") if isinstance(config.get("re"), dict) else {}
    depth_config = (
        re_config.get("depth") if isinstance(re_config.get("depth"), dict) else {}
    )
    sources_config = (
        re_config.get("sources")
        if isinstance(re_config.get("sources"), dict)
        else {}
    )
    discovery_config = (
        config.get("discovery") if isinstance(config.get("discovery"), dict) else {}
    )
    return ReFingerprintProfile.from_json_dict(
        {
            "profile": re_config.get("profile", "full"),
            "depth": depth_config.get("level", "full"),
            "max_lines_per_file": depth_config.get(
                "max_lines_per_file",
                discovery_config.get("max_lines_per_file", 5000),
            ),
            "git_history_limit": sources_config.get(
                "git_history_limit",
                discovery_config.get("git_history_limit", 2500),
            ),
            "codegraph_version": re_config.get("codegraph_version"),
        }
    )


class ReLifecycleController:
    """Own RE freshness planning and the dedicated RE run namespace."""

    def __init__(
        self,
        *,
        project_root: Path,
        extension_root: Path,
        provider_factory: Callable[[], object],
    ) -> None:
        self._project_root = project_root.resolve()
        self._extension_root = extension_root.resolve()
        self._provider_factory = provider_factory

    def run(
        self,
        *,
        policy: str = "",
        re_max_inner: int | None = None,
        reset: bool = False,
        profile_name: str | None = None,
        hard_token_limit: int | None = None,
        hard_active_minutes: int | None = None,
        reuse_published: bool = True,
    ) -> ReLifecycleResult:
        if re_max_inner is not None and re_max_inner < 1:
            raise ReLifecycleError("--re-max-inner requires a positive integer")
        if reset:
            marker = self._project_root / "runs" / ".current-re"
            marker.unlink(missing_ok=True)
        else:
            current = resolve_current_re_run(self._project_root)
            if current is not None:
                state = self._load_state(current)
                if state.get("status") != "done":
                    return self._execute_run(current, state, re_max_inner=re_max_inner)

        manifest = discover_workspace(self._project_root)
        try:
            execution_profile = resolve_re_execution_profile(
                self._project_root,
                name=profile_name,
                hard_token_limit=hard_token_limit,
                hard_active_minutes=hard_active_minutes,
            )
        except ValueError as exc:
            raise ReLifecycleError(str(exc)) from exc
        profile = resolve_re_fingerprint_profile(self._project_root)
        published = load_published_index(self._project_root)
        plan = build_re_execution_plan(
            project_root=self._project_root,
            manifest=manifest,
            target_source="",
            requested_policy=policy,
            profile=profile,
            published_index=published,
        )
        if not reuse_published:
            plan = replace(
                plan,
                sources=tuple(
                    replace(source, action="refresh", classification="refresh")
                    if source.action == "reuse"
                    else source
                    for source in plan.sources
                ),
                analysis_required=True,
                workspace_synthesis_required=True,
                publication_required=True,
            )
        missing = sorted(source.id for source in plan.sources if source.action == "missing")
        if plan.policy == "cached-only" and missing:
            return ReLifecycleResult(
                status="blocked",
                blocked_reason="cached-only missing published RE: " + ", ".join(missing),
            )
        if not plan.analysis_required and not plan.workspace_synthesis_required:
            return ReLifecycleResult(
                status="done",
                generation=published.generation if published is not None else 0,
                no_work=True,
            )
        run_dir = self._create_run_dir()
        expected_generation = published.generation if published is not None else 0
        materialize_re_run_context(
            project_root=self._project_root,
            run_re_dir=run_dir / "re",
            workspace_manifest=manifest,
            plan=plan,
            published_index=published,
            reuse_published=reuse_published,
        )
        state: dict[str, object] = {
            "run_id": run_dir.name,
            "run_kind": "re",
            "status": "running",
            "phase": "re-extract-0-preflight",
            "requested_re_policy": policy,
            "re_policy": plan.policy,
            "expected_generation": expected_generation,
            "extraction_complete": False,
            "publication_complete": False,
            "publication_pending": False,
            "re_execution_profile": execution_profile.to_json_dict(),
            "re_baseline": {
                "status": "attached" if published is not None and reuse_published else "not-used",
                "generation": expected_generation if published is not None and reuse_published else 0,
            },
        }
        if re_max_inner is not None:
            state["re_max_inner"] = re_max_inner
        self._save_state(run_dir, state)
        self._initialize_controller_state(
            run_dir, re_max_inner, execution_profile.to_json_dict()
        )
        return self._execute_run(run_dir, state, re_max_inner=re_max_inner)

    def continue_run(
        self,
        re_max_inner: int | None = None,
        *,
        hard_token_limit: int | None = None,
        hard_active_minutes: int | None = None,
    ) -> ReLifecycleResult:
        if re_max_inner is not None and re_max_inner < 1:
            raise ReLifecycleError("--re-max-inner requires a positive integer")
        run_dir = resolve_current_re_run(self._project_root)
        if run_dir is None:
            raise ReLifecycleError("no active RE run; start one with echelon re run")
        state = self._load_state(run_dir)
        if state.get("status") == "done":
            return ReLifecycleResult(
                status="done",
                run_id=run_dir.name,
                generation=int(state.get("generation") or 0),
                no_work=True,
            )
        decision = state.get("blocked_decision")
        if (
            state.get("status") == "blocked"
            and isinstance(decision, dict)
            and decision.get("status") == "pending"
        ):
            return ReLifecycleResult(
                status="blocked",
                run_id=run_dir.name,
                phase=str(state.get("phase") or ""),
                blocked_reason=str(state.get("blocked_reason") or "human input required"),
                blocked_detail=str(state.get("blocked_detail") or ""),
            )
        return self._execute_run(
            run_dir,
            state,
            re_max_inner=re_max_inner,
            hard_token_limit=hard_token_limit,
            hard_active_minutes=hard_active_minutes,
        )

    def resume(
        self,
        answer: str,
        re_max_inner: int | None = None,
        *,
        hard_token_limit: int | None = None,
        hard_active_minutes: int | None = None,
    ) -> ReLifecycleResult:
        answer = answer.strip()
        if not answer:
            raise ReLifecycleError("echelon re resume requires a non-empty answer")
        run_dir = resolve_current_re_run(self._project_root)
        if run_dir is None:
            raise ReLifecycleError("no active RE run; start one with echelon re run")
        state = self._load_state(run_dir)
        ensure_blocked_decision(state)
        decision = state.get("blocked_decision")
        if not isinstance(decision, dict) or decision.get("status") != "pending":
            raise ReLifecycleError("active RE run is not waiting for human input")
        selected = _resolve_option(answer, decision.get("options"))
        mark_blocked_decision_resolved(
            state,
            answer=answer,
            selected_option=selected,
            resumed_phase=str(decision.get("blocked_phase") or state.get("phase") or ""),
        )
        metadata = state.get("resume_metadata")
        if isinstance(metadata, dict):
            metadata["source"] = "echelon re resume"
        state["resume_answer"] = answer
        state["status"] = "running"
        state.pop("blocked_reason", None)
        self._save_state(run_dir, state)
        re_state = self._load_json(run_dir / "re" / "state.json")
        re_state["resume_answer"] = answer
        self._save_json(run_dir / "re" / "state.json", re_state)
        return self._execute_run(
            run_dir,
            state,
            re_max_inner=re_max_inner,
            hard_token_limit=hard_token_limit,
            hard_active_minutes=hard_active_minutes,
        )

    def _create_run_dir(self) -> Path:
        runs = self._project_root / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        gitignore = runs / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*/state.json\n*/*.tmp\n.current*\n", encoding="utf-8")
        run_id = datetime.now(timezone.utc).strftime("re-%Y%m%d-%H%M%S-%f")
        run_dir = runs / run_id
        run_dir.mkdir()
        (runs / ".current-re").write_text(run_id + "\n", encoding="utf-8")
        return run_dir

    def _initialize_controller_state(
        self,
        run_dir: Path,
        re_max_inner: int | None,
        execution_profile: dict[str, object],
    ) -> None:
        state = init_re_state(
            output_dir=f"runs/{run_dir.name}/re",
            mode="workspace",
            execution_profile=execution_profile,
        )
        state["run_id"] = run_dir.name
        if re_max_inner is not None:
            state["re_max_inner"] = re_max_inner
        self._save_json(run_dir / "re" / "state.json", state)

    def _execute_run(
        self,
        run_dir: Path,
        state: dict,
        *,
        re_max_inner: int | None,
        hard_token_limit: int | None = None,
        hard_active_minutes: int | None = None,
    ) -> ReLifecycleResult:
        if not isinstance(state.get("re_execution_profile"), dict):
            re_state = self._load_json(run_dir / "re" / "state.json")
            execution_profile = migrate_legacy_re_profile(re_state).to_json_dict()
            state["re_execution_profile"] = execution_profile
            re_state["re_execution_profile"] = execution_profile
            self._save_json(run_dir / "re" / "state.json", re_state)
            self._save_state(run_dir, state)
        if hard_token_limit is not None or hard_active_minutes is not None:
            self._raise_execution_budget(
                run_dir,
                state,
                hard_token_limit=hard_token_limit,
                hard_active_minutes=hard_active_minutes,
            )
        if re_max_inner is not None:
            state["re_max_inner"] = re_max_inner
            re_state = self._load_json(run_dir / "re" / "state.json")
            re_state["re_max_inner"] = re_max_inner
            self._save_json(run_dir / "re" / "state.json", re_state)
            self._save_state(run_dir, state)

        if not state.get("extraction_complete"):
            outcome = ReExtractionController(
                provider=self._provider_factory(),
                project_root=self._project_root,
                run_dir=run_dir,
                extension_root=self._extension_root,
            ).run()
            self._sync_controller_usage(run_dir, state)
            if not outcome.completed:
                state["status"] = "blocked"
                state["blocked_reason"] = outcome.blocked_reason or "re_controller_failed"
                state["phase"] = self._controller_phase(run_dir)
                if outcome.blocked_detail:
                    state["blocked_detail"] = outcome.blocked_detail
                else:
                    state.pop("blocked_detail", None)
                self._save_state(run_dir, state)
                return ReLifecycleResult(
                    status="blocked",
                    run_id=run_dir.name,
                    phase=str(state["phase"]),
                    blocked_reason=str(state["blocked_reason"]),
                    blocked_detail=str(state.get("blocked_detail") or ""),
                )
            state["extraction_complete"] = True
            state["publication_pending"] = True
            state["phase"] = self._controller_phase(run_dir)
            self._save_state(run_dir, state)

        if self._partial_debt_sources(run_dir):
            debt = self._partial_debt_sources(run_dir)
            state["status"] = "blocked"
            state["blocked_reason"] = "re_source_quality_debt: " + ", ".join(debt)
            self._save_state(run_dir, state)
            return ReLifecycleResult(
                status="blocked",
                run_id=run_dir.name,
                phase=str(state.get("phase") or ""),
                blocked_reason=str(state["blocked_reason"]),
            )

        state["status"] = "done"
        state["publication_pending"] = True
        state["publication_complete"] = False
        state["generation"] = int(state.get("expected_generation") or 0)
        state.pop("blocked_reason", None)
        state.pop("blocked_detail", None)
        self._save_state(run_dir, state)
        return ReLifecycleResult(
            status="done",
            run_id=run_dir.name,
            phase=str(state.get("phase") or ""),
            generation=int(state["generation"]),
        )

    def _raise_execution_budget(
        self,
        run_dir: Path,
        state: dict,
        *,
        hard_token_limit: int | None,
        hard_active_minutes: int | None,
    ) -> None:
        profile = state.get("re_execution_profile")
        if not isinstance(profile, dict):
            raise ReLifecycleError("active RE run has no execution profile")
        updated = dict(profile)
        changes: dict[str, dict[str, int | None]] = {}
        for field, value, option in (
            ("hard_token_limit", hard_token_limit, "--re-token-limit"),
            ("hard_active_minutes", hard_active_minutes, "--re-time-limit-minutes"),
        ):
            if value is None:
                continue
            if value < 1:
                raise ReLifecycleError(f"{option} requires a positive integer")
            previous = updated.get(field)
            if isinstance(previous, bool) or (
                isinstance(previous, (int, float)) and int(previous) >= value
            ):
                raise ReLifecycleError(
                    f"{option} must be greater than the active run's current {field}"
                )
            changes[field] = {
                "previous": int(previous)
                if isinstance(previous, (int, float)) and not isinstance(previous, bool)
                else None,
                "updated": value,
            }
            updated[field] = value
        if not changes:
            return

        re_state = self._load_json(run_dir / "re" / "state.json")
        state["re_execution_profile"] = updated
        re_state["re_execution_profile"] = updated
        overrides = state.setdefault("re_execution_budget_overrides", [])
        if not isinstance(overrides, list):
            raise ReLifecycleError("invalid RE execution budget override history")
        overrides.append(changes)
        re_state["re_execution_budget_overrides"] = list(overrides)
        self._save_json(run_dir / "re" / "state.json", re_state)
        self._save_state(run_dir, state)

    def _load_state(self, run_dir: Path) -> dict:
        state = self._load_json(run_dir / "state.json")
        if state.get("run_kind") != "re" or state.get("run_id") != run_dir.name:
            raise ReLifecycleError(f"invalid RE lifecycle state: {run_dir}")
        return state

    def _save_state(self, run_dir: Path, state: dict) -> None:
        self._save_json(run_dir / "state.json", state)

    def _sync_controller_usage(self, run_dir: Path, state: dict) -> None:
        inner = self._load_json(run_dir / "re" / "state.json")
        for source_key, target_key in (
            ("re_token_usage", "token_usage"),
            ("re_unknown_token_dispatches", "unknown_token_dispatches"),
            ("re_active_duration_ms", "active_duration_ms"),
            ("re_execution_intervals", "execution_intervals"),
            ("re_trace_id", "trace_id"),
        ):
            if source_key in inner:
                state[target_key] = inner[source_key]
        self._save_state(run_dir, state)

    @staticmethod
    def _load_json(path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReLifecycleError(f"cannot read RE lifecycle state {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ReLifecycleError(f"RE lifecycle state must be an object: {path}")
        return value

    @staticmethod
    def _save_json(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary).replace(path)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise

    @staticmethod
    def _controller_phase(run_dir: Path) -> str:
        try:
            state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        return str(state.get("phase") or "") if isinstance(state, dict) else ""

    @staticmethod
    def _partial_debt_sources(run_dir: Path) -> list[str]:
        try:
            state = json.loads((run_dir / "re" / "state.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        sources = state.get("re_source_states") if isinstance(state, dict) else None
        if not isinstance(sources, dict):
            return []
        return sorted(
            str(source_id)
            for source_id, source_state in sources.items()
            if isinstance(source_state, dict)
            and source_state.get("status") == "partial_quality_debt"
        )


def _resolve_option(answer: str, options: object) -> dict | None:
    if not isinstance(options, list):
        return None
    normalized = answer.strip().casefold()
    for option in options:
        if not isinstance(option, dict):
            continue
        candidates = (option.get("id"), option.get("label"))
        if any(isinstance(item, str) and item.strip().casefold() == normalized for item in candidates):
            return option
    return None
