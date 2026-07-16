from __future__ import annotations

from pathlib import Path

import pytest

from echelon.workspace_model import WorkspaceInfo, WorkspaceManifest
from harness.re_fingerprint import ReFingerprintProfile
from harness.re_lifecycle import (
    ReLifecycleController,
    ReLifecycleError,
    resolve_current_re_run,
)
from harness.re_planner import ReExecutionPlan


def _empty_manifest(root: Path) -> WorkspaceManifest:
    return WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(root=root, git_role="orchestration", git_present=False),
        sources=(),
    )


@pytest.mark.unit
def test_resolve_current_re_run_is_independent_of_spec_pointer(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    spec_run = runs / "spec-1"
    re_run = runs / "re-1"
    spec_run.mkdir(parents=True)
    re_run.mkdir()
    (runs / ".current").write_text("spec-1\n", encoding="utf-8")
    (runs / ".current-re").write_text("re-1\n", encoding="utf-8")

    assert resolve_current_re_run(tmp_path) == re_run


@pytest.mark.unit
def test_resolve_current_re_run_rejects_path_like_pointer(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / ".current-re").write_text("../outside\n", encoding="utf-8")

    with pytest.raises(ReLifecycleError, match="unsafe RE run id"):
        resolve_current_re_run(tmp_path)


@pytest.mark.unit
def test_changed_current_plan_exits_before_provider_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = ReFingerprintProfile()
    plan = ReExecutionPlan(
        policy="changed",
        requested_policy="changed",
        target_source="",
        sources=(),
        forbidden_source_roots=[],
        profile=profile,
        analysis_required=False,
        workspace_synthesis_required=False,
        publication_required=False,
    )
    monkeypatch.setattr("harness.re_lifecycle.discover_workspace", _empty_manifest)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_re_fingerprint_profile", lambda root: profile
    )
    monkeypatch.setattr("harness.re_lifecycle.load_published_index", lambda root: None)
    monkeypatch.setattr(
        "harness.re_lifecycle.build_re_execution_plan", lambda **kwargs: plan
    )
    provider_calls: list[bool] = []

    controller = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=lambda: provider_calls.append(True),
    )
    result = controller.run(policy="changed", re_max_inner=None, reset=False)

    assert result.status == "done"
    assert result.no_work is True
    assert provider_calls == []
    assert not (tmp_path / "runs" / ".current-re").exists()


@pytest.mark.unit
def test_cached_only_missing_sources_blocks_without_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = ReFingerprintProfile()
    plan_json = {
        "schema_version": 1,
        "policy": "cached-only",
        "requested_policy": "cached-only",
        "target_source": "",
        "refresh_sources_count": 0,
        "forbidden_source_roots": [],
        "profile": profile.to_json_dict(),
        "sources": [
            {
                "id": "api",
                "path": "sources/api",
                "absolute_path": str(tmp_path / "sources/api"),
                "action": "missing",
                "fingerprint": {
                    "value": "missing",
                    "kind": "file-tree",
                    "dirty": False,
                    "profile_hash": profile.profile_hash(),
                },
                "cache_path": str(tmp_path / "re/.cache/api"),
                "dirty": False,
                "selected": True,
                "classification": "refresh",
            }
        ],
        "removed_sources": [],
        "analysis_required": False,
        "workspace_synthesis_required": False,
        "publication_required": False,
    }
    plan = ReExecutionPlan.from_json_dict(plan_json)
    monkeypatch.setattr("harness.re_lifecycle.discover_workspace", _empty_manifest)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_re_fingerprint_profile", lambda root: profile
    )
    monkeypatch.setattr("harness.re_lifecycle.load_published_index", lambda root: None)
    monkeypatch.setattr(
        "harness.re_lifecycle.build_re_execution_plan", lambda **kwargs: plan
    )
    provider_calls: list[bool] = []
    controller = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=lambda: provider_calls.append(True),
    )

    result = controller.run(policy="cached-only", re_max_inner=None, reset=False)

    assert result.status == "blocked"
    assert result.blocked_reason == "cached-only missing published RE: api"
    assert provider_calls == []
