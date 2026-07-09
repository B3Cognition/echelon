from __future__ import annotations

from pathlib import Path

from echelon.workspace_model import SourceRoot, WorkspaceInfo, WorkspaceManifest
from harness.re_cache import ReCacheRecord, cache_source_dir, write_cache_record
from harness.re_fingerprint import ReFingerprintProfile, fingerprint_source
from harness.re_planner import (
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


def _write_source(root: Path, source_id: str) -> Path:
    source = root / "sources" / source_id
    source.mkdir(parents=True)
    (source / "package.json").write_text(f'{{"name":"{source_id}"}}\n', encoding="utf-8")
    (source / "index.ts").write_text(f"export const id = '{source_id}';\n", encoding="utf-8")
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
