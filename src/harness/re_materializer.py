"""Run-local reverse-engineering artifact materialization."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from echelon.workspace_model import WorkspaceManifest
from harness.re_cache import copy_cached_source
from harness.re_planner import ReExecutionPlan, RePlanSource


def materialize_re_run_view(
    *,
    project_root: Path,
    run_re_dir: Path,
    workspace_manifest: WorkspaceManifest,
    plan: ReExecutionPlan,
    cache_root: Path,
) -> dict[str, Any]:
    """Copy selected RE artifacts into a self-contained run directory."""
    del project_root, cache_root

    run_re_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_re_dir / "workspace-manifest.json"
    plan_path = run_re_dir / "re-execution-plan.json"
    source_index_path = run_re_dir / "re-source-index.json"
    analysis_path = run_re_dir / "analysis.json"
    cross_repo_path = run_re_dir / "cross-repo.json"

    _write_json_atomic(manifest_path, workspace_manifest.to_json_dict())
    _write_json_atomic(plan_path, plan.to_json_dict())

    materialized_sources: list[dict[str, Any]] = []
    per_repo_paths: list[str] = []
    re_context_paths: list[str] = []

    for source in plan.sources:
        run_path = ""
        artifacts: list[str] = []
        if source.selected and source.action in {"reuse", "refresh"}:
            run_source_dir = copy_cached_source(Path(source.cache_path), run_re_dir / source.id)
            run_path = str(run_source_dir)
            artifacts = _relative_files(run_source_dir)
            per_repo_paths.append(str(run_source_dir))
            re_context_path = run_source_dir / "re-context.md"
            if re_context_path.is_file():
                re_context_paths.append(str(re_context_path))

        materialized_sources.append(
            _source_index_entry(
                source=source,
                run_path=run_path,
                artifacts=artifacts,
            )
        )

    selected_sources = [
        source
        for source in materialized_sources
        if source["selected"] and source["action"] in {"reuse", "refresh"}
    ]
    _write_json_atomic(source_index_path, _source_index(plan, materialized_sources))
    _write_json_atomic(analysis_path, _aggregate_analysis(selected_sources))
    _write_json_atomic(cross_repo_path, _cross_repo_index(selected_sources))

    return {
        "manifest": str(manifest_path),
        "execution_plan": str(plan_path),
        "source_index": str(source_index_path),
        "analysis": str(analysis_path),
        "cross_repo": str(cross_repo_path),
        "per_repo": per_repo_paths,
        "re_contexts": re_context_paths,
    }


def _source_index(plan: ReExecutionPlan, sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "policy": plan.policy,
        "requested_policy": plan.requested_policy,
        "target_source": plan.target_source,
        "forbidden_source_roots": plan.forbidden_source_roots,
        "sources": sources,
    }


def _source_index_entry(
    *,
    source: RePlanSource,
    run_path: str,
    artifacts: list[str],
) -> dict[str, Any]:
    return {
        "id": source.id,
        "path": source.path,
        "absolute_path": source.absolute_path,
        "action": source.action,
        "selected": source.selected,
        "dirty": source.dirty,
        "cache_path": source.cache_path,
        "run_path": run_path,
        "artifacts": artifacts,
        "fingerprint": {
            "value": source.fingerprint.value,
            "kind": source.fingerprint.kind,
            "dirty": source.fingerprint.dirty,
            "profile_hash": source.fingerprint.profile_hash,
            "git_head": source.fingerprint.git_head,
        },
    }


def _aggregate_analysis(selected_sources: list[dict[str, Any]]) -> dict[str, Any]:
    repo_analyses = [
        {"name": source["id"], "path": f"{source['id']}/analysis.json"}
        for source in selected_sources
        if "analysis.json" in source["artifacts"]
    ]
    return {
        "schema_version": 1,
        "mode": "polyrepo" if len(repo_analyses) > 1 else "single",
        "repo_count": len(repo_analyses),
        "repo_analyses": repo_analyses,
        "manifest_path": "workspace-manifest.json",
        "source_index_path": "re-source-index.json",
        "cross_repo_path": "cross-repo.json",
        "metadata": {
            "repo_count": len(repo_analyses),
            "materialized": True,
        },
        "repos": repo_analyses,
    }


def _cross_repo_index(selected_sources: list[dict[str, Any]]) -> dict[str, Any]:
    source_ids = [source["id"] for source in selected_sources]
    return {
        "schema_version": 1,
        "source_count": len(source_ids),
        "repo_count": len(source_ids),
        "sources": source_ids,
        "dependency_links": [],
        "potential_integrations": [],
        "relationships": [],
    }


def _relative_files(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp).replace(path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
