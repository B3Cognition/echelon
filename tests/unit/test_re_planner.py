from __future__ import annotations

from pathlib import Path

import pytest

from echelon.workspace_model import SourceRoot, WorkspaceInfo, WorkspaceManifest
from harness.re_cache import ReCacheRecord, cache_source_dir, write_cache_record
from harness.re_fingerprint import ReFingerprintProfile, fingerprint_source
from harness.re_planner import (
    ReExecutionPlan,
    RePlanError,
    build_re_execution_plan,
    resolve_re_policy,
)


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


def _cache_source(root: Path, cache_root: Path, source_id: str, profile: ReFingerprintProfile) -> None:
    source = root / "sources" / source_id
    fingerprint = fingerprint_source(source, profile)
    output = root / "tmp-output" / source_id
    output.mkdir(parents=True)
    (output / "analysis.json").write_text(f'{{"repo_name":"{source_id}"}}\n', encoding="utf-8")
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


def test_changed_policy_reuses_cached_sources_and_refreshes_new_source(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    for source_id in ("original-a", "original-b", "original-c", "prosaic"):
        _write_source(root, source_id)
    manifest = _manifest(root, "original-a", "original-b", "original-c", "prosaic")
    profile = ReFingerprintProfile()
    cache_root = root / ".echelon" / "cache" / "re"
    for source_id in ("original-a", "original-b", "original-c"):
        _cache_source(root, cache_root, source_id, profile)

    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        cache_root=cache_root,
        target_source="",
        requested_policy="changed",
        profile=profile,
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
    cache_root = root / ".echelon" / "cache" / "re"
    _cache_source(root, cache_root, "original-a", profile)

    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        cache_root=cache_root,
        target_source="",
        requested_policy="cached-only",
        profile=profile,
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
    cache_root = root / ".echelon" / "cache" / "re"
    _cache_source(root, cache_root, "original-a", profile)

    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        cache_root=cache_root,
        target_source="prosaic",
        requested_policy="",
        profile=profile,
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
    cache_root = root / ".echelon" / "cache" / "re"

    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        cache_root=cache_root,
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
    cache_root = root / ".echelon" / "cache" / "re"

    plan = build_re_execution_plan(
        project_root=root,
        manifest=manifest,
        cache_root=cache_root,
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
        cache_root=root / ".echelon" / "cache" / "re",
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
        cache_root=root / ".echelon" / "cache" / "re",
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
        cache_root=root / ".echelon" / "cache" / "re",
        target_source="",
        requested_policy="changed",
        profile=ReFingerprintProfile(),
    ).to_json_dict()
    plan["sources"].append(dict(plan["sources"][0]))

    with pytest.raises(RePlanError, match="duplicate source ID"):
        ReExecutionPlan.from_json_dict(plan)
