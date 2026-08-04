from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from echelon.workspace_model import SourceRoot, WorkspaceInfo, WorkspaceManifest
from harness.re_fingerprint import ReFingerprintProfile, fingerprint_source
from harness.re_materializer import materialize_re_run_context
from harness.re_planner import build_re_execution_plan
from harness.re_quality_contract import QUALITY_CONTRACT_VERSION
from harness.re_registry import ensure_re_layout, load_published_index


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _manifest(root: Path, source_counts: dict[str, int]) -> WorkspaceManifest:
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


def _publish_sources(
    root: Path,
    source_ids: tuple[str, ...],
    profile: ReFingerprintProfile,
) -> None:
    paths = ensure_re_layout(root)
    records: dict[str, object] = {}
    workspace_sources: list[dict[str, object]] = []
    for source_id in source_ids:
        source = root / "sources" / source_id
        fingerprint = fingerprint_source(source, profile)
        source_re = paths.sources / source_id
        spec = source_re / "specs" / "domain" / "spec.md"
        spec.parent.mkdir(parents=True)
        spec.write_text("# Domain\n", encoding="utf-8")
        (source_re / "overview.md").write_text(f"# {source_id}\n", encoding="utf-8")
        _write_json(
            source_re / "manifest.json",
            {
                "schema_version": 1,
                "source_id": source_id,
                "source_path": f"sources/{source_id}",
                "source_fingerprint": fingerprint.value,
                "profile": profile.to_json_dict(),
                "profile_hash": fingerprint.profile_hash,
                "quality_contract_version": QUALITY_CONTRACT_VERSION,
                "publication_status": "complete",
                "overview": f"re/sources/{source_id}/overview.md",
                "specs": [f"re/sources/{source_id}/specs/domain/spec.md"],
            },
        )
        records[source_id] = {
            "path": f"sources/{source_id}",
            "published_path": f"re/sources/{source_id}",
            "fingerprint": fingerprint.value,
            "profile_hash": fingerprint.profile_hash,
            "status": "complete",
            "manifest": f"re/sources/{source_id}/manifest.json",
        }
        workspace_sources.append(
            {
                "source_id": source_id,
                "fingerprint": fingerprint.value,
                "profile_hash": fingerprint.profile_hash,
                "status": "complete",
                "manifest": f"re/sources/{source_id}/manifest.json",
            }
        )
    _write_json(
        paths.workspace / "manifest.json",
        {"schema_version": 1, "generation": 1, "sources": workspace_sources},
    )
    for name in ("overview.md", "relationships.md", "contracts.md"):
        (paths.workspace / name).write_text(f"# {name}\n", encoding="utf-8")
    _write_json(
        paths.index,
        {
            "schema_version": 1,
            "generation": 1,
            "publication_status": "complete",
            "published_at": "2026-07-12T12:00:00+00:00",
            "published_from_run": "fixture",
            "sources": records,
            "workspace": {
                "manifest": "re/workspace/manifest.json",
                "overview": "re/workspace/overview.md",
                "relationships": "re/workspace/relationships.md",
                "contracts": "re/workspace/contracts.md",
            },
            "warnings": [],
        },
    )


def test_materialize_re_run_context_uses_canonical_current_source(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "api")
    profile = ReFingerprintProfile()
    _publish_sources(root, ("api",), profile)
    index = load_published_index(root)
    assert index is not None
    plan = build_re_execution_plan(
        project_root=root,
        manifest=_manifest(root, {"api": 1}),
        target_source="",
        requested_policy="changed",
        profile=profile,
        published_index=index,
    )

    run_re = root / "runs" / "run-2" / "re"
    artifacts = materialize_re_run_context(
        project_root=root,
        run_re_dir=run_re,
        workspace_manifest=_manifest(root, {"api": 1}),
        plan=plan,
        published_index=index,
    )

    assert artifacts["manifest"] == str(root / "re/index.json")
    assert artifacts["per_repo"] == [str(root / "re/sources/api")]
    assert artifacts["architecture_map"] is None
    assert artifacts["domain_catalog"] is None
    descriptors = artifacts["artifact_descriptors"]
    assert [row["path"] for row in descriptors] == sorted(
        row["path"] for row in descriptors
    )
    assert {row["kind"] for row in descriptors} == {
        "re-contracts",
        "re-generated-spec",
        "re-overview",
        "re-relationships",
        "re-source-manifest",
        "re-workspace-manifest",
    }
    assert not (run_re / "sources/api").exists()
    source_index = json.loads((run_re / "re-source-index.json").read_text())
    assert source_index["sources"][0]["run_path"] == str(root / "re/sources/api")
    analysis_manifest = json.loads((run_re / "re-analysis-manifest.json").read_text())
    assert analysis_manifest["sources"] == []
    workspace_inputs = json.loads((run_re / "re-workspace-inputs.json").read_text())
    assert workspace_inputs["sources"][0]["input_path"] == "re/sources/api/manifest.json"


def test_improvement_run_copies_published_source_into_mutable_staging(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "api")
    profile = ReFingerprintProfile()
    _publish_sources(root, ("api",), profile)
    index = load_published_index(root)
    assert index is not None
    original = build_re_execution_plan(
        project_root=root,
        manifest=_manifest(root, {"api": 1}),
        target_source="",
        requested_policy="changed",
        profile=profile,
        published_index=index,
    )
    plan = replace(
        original,
        sources=(replace(original.sources[0], action="refresh", classification="refresh"),),
        analysis_required=True,
        workspace_synthesis_required=True,
        publication_required=True,
    )
    run_re = root / "runs/run-improve/re"

    materialize_re_run_context(
        project_root=root,
        run_re_dir=run_re,
        workspace_manifest=_manifest(root, {"api": 1}),
        plan=plan,
        published_index=index,
    )

    assert (run_re / "sources/api/specs/domain/spec.md").read_text() == "# Domain\n"
    assert (root / "re/sources/api/specs/domain/spec.md").read_text() == "# Domain\n"


def test_materialize_re_run_context_selects_only_refresh_sources_for_analysis(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "api")
    _write_source(root, "web")
    profile = ReFingerprintProfile()
    _publish_sources(root, ("api",), profile)
    index = load_published_index(root)
    assert index is not None
    manifest = _manifest(root, {"api": 1, "web": 1})
    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        target_source="",
        requested_policy="changed",
        profile=profile,
        published_index=index,
    )

    run_re = root / "runs" / "run-2" / "re"
    artifacts = materialize_re_run_context(
        project_root=root,
        run_re_dir=run_re,
        workspace_manifest=manifest,
        plan=plan,
        published_index=index,
    )

    analysis_manifest = json.loads((run_re / "re-analysis-manifest.json").read_text())
    assert [source["id"] for source in analysis_manifest["sources"]] == ["web"]
    source_index = json.loads((run_re / "re-source-index.json").read_text())
    assert {source["id"]: source["run_path"] for source in source_index["sources"]} == {
        "api": str(root / "re/sources/api"),
        "web": str(run_re / "sources/web"),
    }
    assert artifacts["per_repo"] == [str(root / "re/sources/api")]
    assert not (run_re / "sources/web").exists()


def test_materialize_re_run_context_records_empty_source_without_analysis(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    (root / "sources/empty").mkdir(parents=True)
    manifest = _manifest(root, {"empty": 0})
    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        target_source="",
        requested_policy="changed",
        profile=ReFingerprintProfile(),
    )

    run_re = root / "runs/run-1/re"
    materialize_re_run_context(
        project_root=root,
        run_re_dir=run_re,
        workspace_manifest=manifest,
        plan=plan,
        published_index=None,
    )

    analysis_manifest = json.loads((run_re / "re-analysis-manifest.json").read_text())
    assert analysis_manifest["sources"] == []
    inputs = json.loads((run_re / "re-workspace-inputs.json").read_text())
    assert inputs["sources"] == [
        {
            "decision": "empty",
            "fingerprint": plan.sources[0].fingerprint.value,
            "id": "empty",
            "input_path": "runs/run-1/re/sources/empty",
            "profile_hash": plan.sources[0].fingerprint.profile_hash,
            "source_path": "sources/empty",
        }
    ]


def test_materialize_re_run_context_records_removed_sources(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "api")
    _write_source(root, "web")
    profile = ReFingerprintProfile()
    _publish_sources(root, ("api", "web"), profile)
    index = load_published_index(root)
    assert index is not None
    manifest = _manifest(root, {"api": 1})
    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        target_source="",
        requested_policy="changed",
        profile=profile,
        published_index=index,
    )

    run_re = root / "runs/run-2/re"
    materialize_re_run_context(
        project_root=root,
        run_re_dir=run_re,
        workspace_manifest=manifest,
        plan=plan,
        published_index=index,
    )

    inputs = json.loads((run_re / "re-workspace-inputs.json").read_text())
    assert inputs["sources"][-1] == {"decision": "removed", "id": "web"}
