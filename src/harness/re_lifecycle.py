"""First-class run/continue/resume lifecycle for workspace reverse engineering."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from echelon.workspace_model import discover_workspace
from harness.config import get_full_resolved_config
from harness.re_fingerprint import ReFingerprintProfile
from harness.re_planner import build_re_execution_plan
from harness.re_registry import load_published_index


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class ReLifecycleError(RuntimeError):
    """Raised when RE lifecycle state or input is unsafe."""


@dataclass(frozen=True)
class ReLifecycleResult:
    status: Literal["done", "blocked", "failed"]
    run_id: str = ""
    phase: str = ""
    blocked_reason: str = ""
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
    ) -> ReLifecycleResult:
        if re_max_inner is not None and re_max_inner < 1:
            raise ReLifecycleError("--re-max-inner requires a positive integer")
        if reset:
            marker = self._project_root / "runs" / ".current-re"
            marker.unlink(missing_ok=True)

        manifest = discover_workspace(self._project_root)
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
        raise ReLifecycleError("work-bearing RE lifecycle execution is not initialized")

