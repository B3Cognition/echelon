from __future__ import annotations

import json
from pathlib import Path

from echelon.workspace_model import SourceRoot, WorkspaceInfo, WorkspaceManifest
from harness.re_cache import ReCacheRecord, cache_source_dir, write_cache_record
from harness.re_fingerprint import ReFingerprintProfile, fingerprint_source
from harness.re_materializer import materialize_re_run_view
from harness.re_planner import build_re_execution_plan


def _manifest(root: Path, *source_ids: str) -> WorkspaceManifest:
    return WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(root=root, git_role="orchestration", git_present=True),
        sources=tuple(
            SourceRoot(
                id=source_id,
                path=f"sources/{source_id}",
                git_present=False,
                project_markers=("package.json",),
                source_file_count=1,
            )
            for source_id in source_ids
        ),
    )


def _manifest_with_counts(root: Path, source_counts: dict[str, int]) -> WorkspaceManifest:
    return WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(root=root, git_role="orchestration", git_present=True),
        sources=tuple(
            SourceRoot(
                id=source_id,
                path=f"sources/{source_id}",
                git_present=False,
                project_markers=("package.json",),
                source_file_count=count,
            )
            for source_id, count in source_counts.items()
        ),
    )


def _write_source(root: Path, source_id: str) -> None:
    source = root / "sources" / source_id
    source.mkdir(parents=True)
    (source / "package.json").write_text(f'{{"name":"{source_id}"}}\n', encoding="utf-8")
    (source / "index.ts").write_text(f"export const id = '{source_id}';\n", encoding="utf-8")


def _write_empty_source(root: Path, source_id: str) -> None:
    source = root / "sources" / source_id
    source.mkdir(parents=True)


def _cache_source(root: Path, cache_root: Path, source_id: str, profile: ReFingerprintProfile) -> None:
    source = root / "sources" / source_id
    fingerprint = fingerprint_source(source, profile)
    output = root / "tmp-output" / source_id
    output.mkdir(parents=True)
    (output / "analysis.json").write_text(
        json.dumps({"repo_name": source_id, "metadata": {"total_files": 1}}) + "\n",
        encoding="utf-8",
    )
    (output / "re-context.md").write_text(f"# {source_id} context\n", encoding="utf-8")
    write_cache_record(
        output,
        cache_source_dir(cache_root, source_id, fingerprint),
        ReCacheRecord(
            source_id=source_id,
            source_path=f"sources/{source_id}",
            fingerprint=fingerprint,
            profile={"profile": profile.profile, "depth": profile.depth},
        ),
    )


def test_materialize_re_run_view_copies_cached_sources_and_writes_indexes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    for source_id in ("original-a", "prosaic"):
        _write_source(root, source_id)
    manifest = _manifest(root, "original-a", "prosaic")
    profile = ReFingerprintProfile()
    cache_root = root / ".echelon" / "cache" / "re"
    for source_id in ("original-a", "prosaic"):
        _cache_source(root, cache_root, source_id, profile)
    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        cache_root=cache_root,
        target_source="",
        requested_policy="changed",
        profile=profile,
    )

    artifacts = materialize_re_run_view(
        project_root=root,
        run_re_dir=root / "runs" / "run-1" / "re",
        workspace_manifest=manifest,
        plan=plan,
        cache_root=cache_root,
    )

    run_re = root / "runs" / "run-1" / "re"
    assert (run_re / "workspace-manifest.json").is_file()
    assert (run_re / "re-execution-plan.json").is_file()
    assert (run_re / "re-source-index.json").is_file()
    assert (run_re / "analysis.json").is_file()
    assert (run_re / "cross-repo.json").is_file()
    assert (run_re / "original-a" / "analysis.json").is_file()
    assert (run_re / "prosaic" / "re-context.md").read_text(encoding="utf-8") == "# prosaic context\n"
    assert not (run_re / "original-a" / "analysis.json").is_symlink()

    source_index = json.loads((run_re / "re-source-index.json").read_text(encoding="utf-8"))
    assert [source["id"] for source in source_index["sources"]] == ["original-a", "prosaic"]
    assert [source["action"] for source in source_index["sources"]] == ["reuse", "reuse"]
    assert source_index["sources"][0]["run_path"] == str(run_re / "original-a")

    aggregate = json.loads((run_re / "analysis.json").read_text(encoding="utf-8"))
    assert aggregate["mode"] == "polyrepo"
    assert aggregate["repo_count"] == 2
    assert aggregate["repo_analyses"] == [
        {"name": "original-a", "path": "original-a/analysis.json"},
        {"name": "prosaic", "path": "prosaic/analysis.json"},
    ]

    cross_repo = json.loads((run_re / "cross-repo.json").read_text(encoding="utf-8"))
    assert cross_repo["source_count"] == 2
    assert cross_repo["sources"] == ["original-a", "prosaic"]

    assert artifacts["manifest"] == str(run_re / "workspace-manifest.json")
    assert artifacts["source_index"] == str(run_re / "re-source-index.json")
    assert artifacts["analysis"] == str(run_re / "analysis.json")
    assert artifacts["cross_repo"] == str(run_re / "cross-repo.json")
    assert artifacts["per_repo"] == [str(run_re / "original-a"), str(run_re / "prosaic")]
    assert artifacts["re_contexts"] == [
        str(run_re / "original-a" / "re-context.md"),
        str(run_re / "prosaic" / "re-context.md"),
    ]


def test_materialize_re_run_view_records_refresh_sources_without_cache(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    for source_id in ("original-a", "prosaic"):
        _write_source(root, source_id)
    manifest = _manifest(root, "original-a", "prosaic")
    profile = ReFingerprintProfile()
    cache_root = root / ".echelon" / "cache" / "re"
    _cache_source(root, cache_root, "original-a", profile)
    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        cache_root=cache_root,
        target_source="",
        requested_policy="changed",
        profile=profile,
    )

    artifacts = materialize_re_run_view(
        project_root=root,
        run_re_dir=root / "runs" / "run-1" / "re",
        workspace_manifest=manifest,
        plan=plan,
        cache_root=cache_root,
    )

    run_re = root / "runs" / "run-1" / "re"
    assert (run_re / "original-a" / "analysis.json").is_file()
    assert not (run_re / "prosaic").exists()

    source_index = json.loads((run_re / "re-source-index.json").read_text(encoding="utf-8"))
    assert {source["id"]: source["action"] for source in source_index["sources"]} == {
        "original-a": "reuse",
        "prosaic": "refresh",
    }
    assert source_index["sources"][1]["run_path"] == ""
    assert source_index["sources"][1]["artifacts"] == []

    aggregate = json.loads((run_re / "analysis.json").read_text(encoding="utf-8"))
    assert aggregate["repo_count"] == 1
    assert artifacts["per_repo"] == [str(run_re / "original-a")]


def test_materialize_re_run_view_records_empty_target_skip_without_artifacts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "original-a")
    _write_empty_source(root, "prosaic")
    manifest = _manifest_with_counts(root, {"original-a": 1, "prosaic": 0})
    profile = ReFingerprintProfile()
    cache_root = root / ".echelon" / "cache" / "re"
    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        cache_root=cache_root,
        target_source="prosaic",
        requested_policy="",
        profile=profile,
    )

    artifacts = materialize_re_run_view(
        project_root=root,
        run_re_dir=root / "runs" / "run-1" / "re",
        workspace_manifest=manifest,
        plan=plan,
        cache_root=cache_root,
    )

    run_re = root / "runs" / "run-1" / "re"
    assert not (run_re / "prosaic").exists()
    source_index = json.loads((run_re / "re-source-index.json").read_text(encoding="utf-8"))
    assert {source["id"]: source["action"] for source in source_index["sources"]} == {
        "original-a": "exclude",
        "prosaic": "skip-empty",
    }
    assert source_index["sources"][1]["run_path"] == ""
    assert source_index["sources"][1]["artifacts"] == []

    aggregate = json.loads((run_re / "analysis.json").read_text(encoding="utf-8"))
    assert aggregate["repo_count"] == 0
    assert artifacts["per_repo"] == []
