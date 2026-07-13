from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from echelon.workspace_model import SourceRoot, WorkspaceInfo, WorkspaceManifest
from harness.re_fingerprint import ReFingerprintProfile, fingerprint_source
from harness.re_planner import (
    ReExecutionPlan,
    RePlanError,
    build_re_execution_plan,
    resolve_re_policy,
)
from harness.re_quality_contract import QUALITY_CONTRACT_VERSION
from harness.re_registry import ensure_re_layout, load_published_index


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


def _write_source(root: Path, source_id: str) -> Path:
    source = root / "sources" / source_id
    source.mkdir(parents=True)
    (source / "package.json").write_text(f'{{"name":"{source_id}"}}\n', encoding="utf-8")
    (source / "index.ts").write_text(f"export const id = '{source_id}';\n", encoding="utf-8")
    return source


def _write_empty_source(root: Path, source_id: str) -> Path:
    source = root / "sources" / source_id
    source.mkdir(parents=True)
    return source


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _publish_source(root: Path, source_id: str, profile: ReFingerprintProfile) -> None:
    source = root / "sources" / source_id
    fingerprint = fingerprint_source(source, profile)
    paths = ensure_re_layout(root)
    source_re = paths.sources / source_id
    spec = source_re / "specs" / "domain" / "spec.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
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
    records: dict[str, object] = {}
    if paths.index.is_file():
        records = json.loads(paths.index.read_text(encoding="utf-8"))["sources"]
    records[source_id] = {
        "path": f"sources/{source_id}",
        "published_path": f"re/sources/{source_id}",
        "fingerprint": fingerprint.value,
        "profile_hash": fingerprint.profile_hash,
        "status": "complete",
        "manifest": f"re/sources/{source_id}/manifest.json",
    }
    _write_json(paths.workspace / "manifest.json", {"schema_version": 1, "sources": []})
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


def test_resolve_re_policy_defaults_to_changed_or_target_changed() -> None:
    assert resolve_re_policy(target_source="", requested_policy="") == "changed"
    assert resolve_re_policy(target_source="prosaic", requested_policy="") == "target-changed"
    assert resolve_re_policy(target_source="prosaic", requested_policy="refresh-all") == "refresh-all"


def test_resolve_re_policy_rejects_unknown_policy() -> None:
    try:
        resolve_re_policy(target_source="", requested_policy="sometimes")
    except RePlanError as exc:
        assert "invalid re-policy" in str(exc)
    else:
        raise AssertionError("invalid policy should fail")


def test_re_fingerprint_profile_defaults_to_full_depth() -> None:
    profile = ReFingerprintProfile()

    assert profile.profile == "full"
    assert profile.depth == "full"
    assert profile.max_lines_per_file == 5000
    assert profile.git_history_limit == 2500


def test_changed_policy_reuses_published_sources_and_refreshes_new_source(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    for source_id in ("original-a", "original-b", "original-c", "prosaic"):
        _write_source(root, source_id)
    manifest = _manifest(root, "original-a", "original-b", "original-c", "prosaic")
    profile = ReFingerprintProfile()
    for source_id in ("original-a", "original-b", "original-c"):
        _publish_source(root, source_id, profile)

    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        target_source="",
        requested_policy="changed",
        profile=profile,
        published_index=load_published_index(root),
    )

    assert plan.policy == "changed"
    assert plan.refresh_sources_count == 1
    assert {source.id: source.action for source in plan.sources} == {
        "original-a": "reuse",
        "original-b": "reuse",
        "original-c": "reuse",
        "prosaic": "refresh",
    }


def test_cached_only_never_refreshes_missing_sources(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    for source_id in ("original-a", "prosaic"):
        _write_source(root, source_id)
    manifest = _manifest(root, "original-a", "prosaic")
    profile = ReFingerprintProfile()
    _publish_source(root, "original-a", profile)

    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        target_source="",
        requested_policy="cached-only",
        profile=profile,
        published_index=load_published_index(root),
    )

    assert plan.refresh_sources_count == 0
    assert {source.id: source.action for source in plan.sources} == {
        "original-a": "reuse",
        "prosaic": "missing",
    }


def test_target_changed_refreshes_missing_target_but_requires_cached_siblings(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    for source_id in ("original-a", "original-b", "prosaic"):
        _write_source(root, source_id)
    manifest = _manifest(root, "original-a", "original-b", "prosaic")
    profile = ReFingerprintProfile()
    _publish_source(root, "original-a", profile)

    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        target_source="prosaic",
        requested_policy="",
        profile=profile,
        published_index=load_published_index(root),
    )

    assert plan.policy == "target-changed"
    assert plan.refresh_sources_count == 1
    assert {source.id: source.action for source in plan.sources} == {
        "original-a": "reuse",
        "original-b": "missing",
        "prosaic": "refresh",
    }


def test_target_changed_skips_empty_target_without_requiring_sibling_cache(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "original-a")
    _write_empty_source(root, "prosaic")
    manifest = _manifest_with_counts(root, {"original-a": 1, "prosaic": 0})
    profile = ReFingerprintProfile()

    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        target_source="prosaic",
        requested_policy="",
        profile=profile,
    )

    assert plan.policy == "target-changed"
    assert plan.refresh_sources_count == 0
    assert {source.id: source.action for source in plan.sources} == {
        "original-a": "exclude",
        "prosaic": "skip-empty",
    }


def test_target_only_selects_target_and_forbids_sibling_roots(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    for source_id in ("original-a", "original-b", "prosaic"):
        _write_source(root, source_id)
    manifest = _manifest(root, "original-a", "original-b", "prosaic")
    profile = ReFingerprintProfile()

    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        target_source="prosaic",
        requested_policy="target-only",
        profile=profile,
    )

    assert plan.target_source == "prosaic"
    assert plan.refresh_sources_count == 1
    assert {source.id: source.action for source in plan.sources} == {
        "original-a": "exclude",
        "original-b": "exclude",
        "prosaic": "refresh",
    }
    assert plan.forbidden_source_roots == [
        str(root / "sources" / "original-a"),
        str(root / "sources" / "original-b"),
    ]


def test_re_execution_plan_round_trips_exact_profile_and_fingerprints(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "api")
    profile = ReFingerprintProfile()
    plan = build_re_execution_plan(
        project_root=root,
        manifest=_manifest(root, "api"),
        target_source="",
        requested_policy="changed",
        profile=profile,
    )

    restored = ReExecutionPlan.from_json_dict(plan.to_json_dict())

    assert restored == plan
    assert restored.sources[0].classification == "refresh"
    assert restored.analysis_required is True
    assert restored.workspace_synthesis_required is True
    assert restored.publication_required is True


def test_re_execution_plan_rejects_profile_hash_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "api")
    plan = build_re_execution_plan(
        project_root=root,
        manifest=_manifest(root, "api"),
        target_source="",
        requested_policy="changed",
        profile=ReFingerprintProfile(),
    ).to_json_dict()
    plan["sources"][0]["fingerprint"]["profile_hash"] = "wrong"

    with pytest.raises(RePlanError, match="profile hash"):
        ReExecutionPlan.from_json_dict(plan)


def test_re_execution_plan_rejects_duplicate_source_ids(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "api")
    plan = build_re_execution_plan(
        project_root=root,
        manifest=_manifest(root, "api"),
        target_source="",
        requested_policy="changed",
        profile=ReFingerprintProfile(),
    ).to_json_dict()
    plan["sources"].append(dict(plan["sources"][0]))

    with pytest.raises(RePlanError, match="duplicate source ID"):
        ReExecutionPlan.from_json_dict(plan)


def test_matching_publication_is_current_without_heavy_cache(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "api")
    profile = ReFingerprintProfile()
    _publish_source(root, "api", profile)

    plan = build_re_execution_plan(
        project_root=root,
        manifest=_manifest(root, "api"),
        target_source="",
        requested_policy="changed",
        profile=profile,
        published_index=load_published_index(root),
    )

    assert plan.sources[0].classification == "current"
    assert plan.sources[0].action == "reuse"
    assert not plan.analysis_required
    assert not plan.publication_required
    assert not (root / "re/.cache/sources/api").exists()


def test_changed_policy_refreshes_sources_published_under_an_old_quality_contract(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "api")
    profile = ReFingerprintProfile()
    _publish_source(root, "api", profile)
    manifest_path = root / "re" / "sources" / "api" / "manifest.json"
    published_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    published_manifest.pop("quality_contract_version")
    _write_json(manifest_path, published_manifest)

    plan = build_re_execution_plan(
        project_root=root,
        manifest=_manifest(root, "api"),
        target_source="",
        requested_policy="changed",
        profile=profile,
        published_index=load_published_index(root),
    )

    assert plan.sources[0].action == "refresh"
    assert plan.sources[0].classification == "refresh"


def test_profile_change_refreshes_published_source(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "api")
    _publish_source(root, "api", ReFingerprintProfile())
    changed_profile = ReFingerprintProfile(profile="deep", depth="full")

    plan = build_re_execution_plan(
        project_root=root,
        manifest=_manifest(root, "api"),
        target_source="",
        requested_policy="changed",
        profile=changed_profile,
        published_index=load_published_index(root),
    )

    assert plan.sources[0].classification == "refresh"
    assert plan.sources[0].action == "refresh"


def test_unavailable_declared_source_retains_published_context(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "api")
    profile = ReFingerprintProfile()
    _publish_source(root, "api", profile)
    shutil.rmtree(root / "sources/api")

    plan = build_re_execution_plan(
        project_root=root,
        manifest=_manifest(root, "api"),
        target_source="",
        requested_policy="changed",
        profile=profile,
        published_index=load_published_index(root),
    )

    assert plan.sources[0].classification == "unavailable"
    assert plan.sources[0].action == "missing"
    assert not plan.analysis_required
    assert not plan.publication_required


def test_published_source_absent_from_workspace_is_removed(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_source(root, "api")
    _write_source(root, "web")
    profile = ReFingerprintProfile()
    _publish_source(root, "api", profile)
    _publish_source(root, "web", profile)

    plan = build_re_execution_plan(
        project_root=root,
        manifest=_manifest(root, "api"),
        target_source="",
        requested_policy="changed",
        profile=profile,
        published_index=load_published_index(root),
    )

    assert plan.removed_sources == ("web",)
    assert not plan.analysis_required
    assert plan.workspace_synthesis_required
    assert plan.publication_required
