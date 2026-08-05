"""Run-local planning context for workspace reverse engineering."""

from __future__ import annotations

import json
import os
import tempfile
import shutil
from pathlib import Path
from typing import Any

from echelon.workspace_model import WorkspaceManifest
from harness.re_planner import ReExecutionPlan, RePlanSource
from harness.re_registry import (
    PublishedReIndex,
    canonical_re_artifacts,
    load_published_index,
    published_source_is_usable,
)


def materialize_re_run_context(
    *,
    project_root: Path,
    run_re_dir: Path,
    workspace_manifest: WorkspaceManifest,
    plan: ReExecutionPlan,
    published_index: PublishedReIndex | None,
    reuse_published: bool = True,
) -> dict[str, Any]:
    """Write run provenance while referencing published RE documents directly."""
    root = project_root.resolve()
    run_re = run_re_dir.resolve()
    if not run_re.is_relative_to(root):
        raise ValueError(f"run RE directory must be inside workspace: {run_re}")
    run_relative = run_re.relative_to(root).as_posix()
    run_re.mkdir(parents=True, exist_ok=True)

    if published_index is not None and reuse_published:
        _copy_published_sources(root, run_re, plan, published_index)

    workspace_manifest_path = run_re / "workspace-manifest.json"
    plan_path = run_re / "re-execution-plan.json"
    source_index_path = run_re / "re-source-index.json"
    analysis_manifest_path = run_re / "re-analysis-manifest.json"
    workspace_inputs_path = run_re / "re-workspace-inputs.json"
    analysis_path = run_re / "analysis.json"
    cross_repo_path = run_re / "cross-repo.json"

    _write_json_atomic(workspace_manifest_path, workspace_manifest.to_json_dict())
    _write_json_atomic(plan_path, plan.to_json_dict())

    source_entries = [
        _source_index_entry(
            root=root,
            run_re=run_re,
            source=source,
            published_index=published_index,
        )
        for source in plan.sources
    ]
    _write_json_atomic(source_index_path, _source_index(plan, source_entries))

    refresh_ids = {source.id for source in plan.sources if source.action == "refresh"}
    analysis_manifest = workspace_manifest.to_json_dict()
    analysis_manifest["sources"] = [
        source.to_json_dict()
        for source in workspace_manifest.sources
        if source.id in refresh_ids
    ]
    _write_json_atomic(analysis_manifest_path, analysis_manifest)

    workspace_inputs = build_re_workspace_inputs(
        plan,
        run_relative=run_relative,
    )
    _write_json_atomic(workspace_inputs_path, workspace_inputs)
    _write_json_atomic(analysis_path, _aggregate_analysis(plan))
    _write_json_atomic(cross_repo_path, _cross_repo_index(plan))

    canonical = (
        canonical_re_artifacts(root, published_index)
        if published_index is not None
        else {}
    )
    artifacts: dict[str, Any] = {
        "manifest": canonical.get("manifest", str(workspace_manifest_path)),
        "execution_plan": str(plan_path),
        "source_index": str(source_index_path),
        "analysis_manifest": str(analysis_manifest_path),
        "workspace_inputs": str(workspace_inputs_path),
        "analysis": str(analysis_path),
        "cross_repo": (
            str(cross_repo_path)
            if plan.publication_required
            else canonical.get("cross_repo", str(cross_repo_path))
        ),
        "per_repo": canonical.get("per_repo", []),
        "re_contexts": canonical.get("re_contexts", []),
        "re_specs": canonical.get("re_specs", []),
        "re_overview": canonical.get("re_overview"),
        "architecture_map": canonical.get("architecture_map"),
        "domain_catalog": canonical.get("domain_catalog"),
        "source_manifests": canonical.get("source_manifests", {}),
        "workspace_manifest": canonical.get("workspace_manifest"),
        "artifact_descriptors": canonical.get("artifact_descriptors", []),
        "published_generation": published_index.generation if published_index else 0,
    }
    return artifacts


def materialize_re_run_view(
    *,
    project_root: Path,
    run_re_dir: Path,
    workspace_manifest: WorkspaceManifest,
    plan: ReExecutionPlan,
    cache_root: Path | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper for callers migrating from cache materialization."""
    del cache_root
    return materialize_re_run_context(
        project_root=project_root,
        run_re_dir=run_re_dir,
        workspace_manifest=workspace_manifest,
        plan=plan,
        published_index=load_published_index(project_root),
    )


def _copy_published_sources(
    root: Path,
    run_re: Path,
    plan: ReExecutionPlan,
    published_index: PublishedReIndex,
) -> None:
    """Seed mutable staging from the registered immutable publication."""
    for source in plan.sources:
        if source.action != "refresh" or not published_source_is_usable(
            root, published_index, source.id
        ):
            continue
        source_root = root / "re" / "sources" / source.id
        destination = run_re / "sources" / source.id
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source_root, destination)


def _source_index(plan: ReExecutionPlan, sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "policy": plan.policy,
        "requested_policy": plan.requested_policy,
        "target_source": plan.target_source,
        "forbidden_source_roots": plan.forbidden_source_roots,
        "removed_sources": list(plan.removed_sources),
        "sources": sources,
    }


def _source_index_entry(
    *,
    root: Path,
    run_re: Path,
    source: RePlanSource,
    published_index: PublishedReIndex | None,
) -> dict[str, Any]:
    published = bool(
        published_index
        and source.id in published_index.sources
        and published_source_is_usable(root, published_index, source.id)
    )
    if source.action in {"refresh", "skip-empty"}:
        run_path = str(run_re / "sources" / source.id)
    elif published:
        run_path = str(root / "re" / "sources" / source.id)
    else:
        run_path = ""
    entry = source.to_json_dict()
    entry.update({"run_path": run_path, "artifacts": []})
    return entry


def build_re_workspace_inputs(
    plan: ReExecutionPlan,
    *,
    run_relative: str,
) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for source in plan.sources:
        input_path = (
            f"{run_relative}/sources/{source.id}"
            if source.action in {"refresh", "skip-empty"}
            else f"re/sources/{source.id}/manifest.json"
        )
        sources.append(
            {
                "id": source.id,
                "decision": source.classification,
                "source_path": source.path,
                "fingerprint": source.fingerprint.value,
                "profile_hash": source.fingerprint.profile_hash,
                "input_path": input_path,
            }
        )
    sources.extend(
        {"id": source_id, "decision": "removed"}
        for source_id in plan.removed_sources
    )
    return {"schema_version": 1, "sources": sources}


def _aggregate_analysis(plan: ReExecutionPlan) -> dict[str, Any]:
    repo_analyses = [
        {"name": source.id, "path": f"sources/{source.id}/analysis.json"}
        for source in plan.sources
        if source.action == "refresh"
    ]
    return {
        "schema_version": 1,
        "mode": "workspace",
        "repo_count": len(repo_analyses),
        "repo_analyses": repo_analyses,
        "manifest_path": "re-analysis-manifest.json",
        "source_index_path": "re-source-index.json",
        "cross_repo_path": "cross-repo.json",
        "metadata": {"repo_count": len(repo_analyses), "materialized": False},
        "repos": repo_analyses,
    }


def _cross_repo_index(plan: ReExecutionPlan) -> dict[str, Any]:
    source_ids = [source.id for source in plan.sources if source.action != "exclude"]
    return {
        "schema_version": 1,
        "source_count": len(source_ids),
        "repo_count": len(source_ids),
        "sources": source_ids,
        "dependency_links": [],
        "potential_integrations": [],
        "relationships": [],
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
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
