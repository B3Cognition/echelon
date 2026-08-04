from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from echelon.workspace_model import SourceRoot, WorkspaceInfo, WorkspaceManifest
from harness.re_fingerprint import ReFingerprintProfile
from harness.re_lifecycle import (
    ReLifecycleController,
    ReLifecycleError,
    resolve_current_re_run,
)
from harness.re_planner import ReExecutionPlan, build_re_execution_plan
from harness.re_publication import RePublicationError, RePublicationResult


def _empty_manifest(root: Path) -> WorkspaceManifest:
    return WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(root=root, git_role="orchestration", git_present=False),
        sources=(),
    )


def _manifest_with_source(
    root: Path,
    source_id: str,
    *,
    source_file_count: int = 1,
) -> WorkspaceManifest:
    return WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(root=root, git_role="orchestration", git_present=False),
        sources=(
            SourceRoot(
                id=source_id,
                path=f"sources/{source_id}",
                git_present=False,
                project_markers=(),
                source_file_count=source_file_count,
            ),
        ),
    )


def _work_plan(profile: ReFingerprintProfile) -> ReExecutionPlan:
    return ReExecutionPlan(
        policy="refresh-all",
        requested_policy="refresh-all",
        target_source="",
        sources=(),
        forbidden_source_roots=[],
        profile=profile,
        analysis_required=True,
        workspace_synthesis_required=True,
        publication_required=True,
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
    monkeypatch.setattr(
        "harness.re_lifecycle.materialize_re_run_context",
        lambda **kwargs: pytest.fail("current changed plan must not materialize a run"),
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
def test_changed_current_publication_does_not_blanket_refresh_reusable_sources(
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
    monkeypatch.setattr(
        "harness.re_lifecycle.load_published_index",
        lambda root: type("Published", (), {"generation": 7})(),
    )
    monkeypatch.setattr(
        "harness.re_lifecycle.build_re_execution_plan", lambda **kwargs: plan
    )
    monkeypatch.setattr(
        "harness.re_lifecycle.materialize_re_run_context",
        lambda **kwargs: pytest.fail("current changed plan must not materialize a run"),
    )
    provider_calls: list[bool] = []

    result = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=lambda: provider_calls.append(True),
    ).run(policy="changed")

    assert result.status == "done"
    assert result.no_work is True
    assert result.generation == 7
    assert provider_calls == []
    assert not (tmp_path / "runs" / ".current-re").exists()


@pytest.mark.unit
def test_no_reuse_keeps_published_index_available_to_planner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = ReFingerprintProfile()
    published = SimpleNamespace(generation=7, sources={"removed": object()})
    observed: dict[str, object] = {}
    monkeypatch.setattr("harness.re_lifecycle.discover_workspace", _empty_manifest)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_re_fingerprint_profile", lambda root: profile
    )
    monkeypatch.setattr(
        "harness.re_lifecycle.load_published_index", lambda root: published
    )

    def build_plan(**kwargs: object) -> ReExecutionPlan:
        observed.update(kwargs)
        return ReExecutionPlan(
            policy="changed",
            requested_policy="changed",
            target_source="",
            sources=(),
            forbidden_source_roots=[],
            profile=profile,
        )

    monkeypatch.setattr("harness.re_lifecycle.build_re_execution_plan", build_plan)

    ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=object,
    ).run(policy="changed", reuse_published=False)

    assert observed["published_index"] is published
    assert observed["reuse_published"] is False


@pytest.mark.unit
def test_targeted_run_passes_selected_force_semantics_to_planner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "sources/api"
    source.mkdir(parents=True)
    (source / "app.py").write_text("pass\n", encoding="utf-8")
    profile = ReFingerprintProfile()
    plan = ReExecutionPlan(
        policy="target-only",
        requested_policy="target-only",
        target_source="api",
        sources=(),
        forbidden_source_roots=[],
        profile=profile,
        analysis_required=False,
        workspace_synthesis_required=False,
        publication_required=False,
    )
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        "harness.re_lifecycle.discover_workspace",
        lambda root: _manifest_with_source(root, "api"),
    )
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_re_fingerprint_profile", lambda root: profile
    )
    monkeypatch.setattr("harness.re_lifecycle.load_published_index", lambda root: None)

    def build_plan(**kwargs: object) -> ReExecutionPlan:
        observed.update(kwargs)
        return plan

    monkeypatch.setattr("harness.re_lifecycle.build_re_execution_plan", build_plan)

    result = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=object,
    ).run(
        policy="target-only",
        target_source="api",
        force_selected_refresh=True,
    )

    assert result.status == "done"
    assert result.no_work is True
    assert observed["target_source"] == "api"
    assert observed["requested_policy"] == "target-only"
    assert observed["force_selected_refresh"] is True


@pytest.mark.unit
def test_targeted_run_rejects_disappeared_declared_source_before_run_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = ReFingerprintProfile()
    monkeypatch.setattr(
        "harness.re_lifecycle.discover_workspace",
        lambda root: _manifest_with_source(root, "api"),
    )
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_re_fingerprint_profile", lambda root: profile
    )
    monkeypatch.setattr("harness.re_lifecycle.load_published_index", lambda root: None)

    controller = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=object,
    )

    with pytest.raises(ReLifecycleError, match="selected source api is unavailable"):
        controller.run(
            policy="target-only",
            target_source="api",
            force_selected_refresh=True,
        )

    assert not (tmp_path / "runs").exists()


@pytest.mark.unit
def test_targeted_run_rejects_overlapping_target_and_sibling_before_planning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sibling = tmp_path / "sources/web"
    sibling.mkdir(parents=True)
    manifest = WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(root=tmp_path, git_role="orchestration", git_present=False),
        sources=(
            SourceRoot(
                id="workspace",
                path=".",
                git_present=False,
                project_markers=(),
                source_file_count=1,
            ),
            SourceRoot(
                id="web",
                path="sources/web",
                git_present=False,
                project_markers=(),
                source_file_count=1,
            ),
        ),
    )
    monkeypatch.setattr("harness.re_lifecycle.discover_workspace", lambda root: manifest)
    monkeypatch.setattr(
        "harness.re_lifecycle.build_re_execution_plan",
        lambda **kwargs: pytest.fail("overlap must be rejected before planning"),
    )
    provider_calls: list[bool] = []

    controller = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=lambda: provider_calls.append(True),
    )

    with pytest.raises(ReLifecycleError, match="overlapping source roots.*workspace.*web"):
        controller.run(
            policy="target-only",
            target_source="workspace",
            force_selected_refresh=True,
        )

    assert provider_calls == []
    assert not (tmp_path / "runs").exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("persisted_force", "exclude_sibling"),
    ((False, False), (True, True)),
)
def test_targeted_run_rejects_active_plan_that_is_not_forced_equivalent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    persisted_force: bool,
    exclude_sibling: bool,
) -> None:
    for source_id in ("api", "web"):
        source = tmp_path / f"sources/{source_id}"
        source.mkdir(parents=True)
        (source / "app.py").write_text("pass\n", encoding="utf-8")
    manifest = WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(root=tmp_path, git_role="orchestration", git_present=False),
        sources=tuple(
            SourceRoot(
                id=source_id,
                path=f"sources/{source_id}",
                git_present=False,
                project_markers=(),
                source_file_count=1,
            )
            for source_id in ("api", "web")
        ),
    )
    profile = ReFingerprintProfile()
    published_source = SimpleNamespace(
        fingerprint="1" * 64,
        profile_hash=profile.profile_hash(),
        source_path="sources/web",
    )
    published = SimpleNamespace(generation=4, sources={"web": published_source})
    monkeypatch.setattr("harness.re_lifecycle.discover_workspace", lambda root: manifest)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_re_fingerprint_profile", lambda root: profile
    )
    monkeypatch.setattr("harness.re_lifecycle.load_published_index", lambda root: published)
    monkeypatch.setattr(
        "harness.re_planner.published_source_is_current", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        "harness.re_planner.published_source_is_usable", lambda *args, **kwargs: True
    )
    plan = build_re_execution_plan(
        project_root=tmp_path,
        manifest=manifest,
        target_source="api",
        requested_policy="target-only",
        profile=profile,
        published_index=published,
        force_selected_refresh=True,
    )
    if exclude_sibling:
        plan = replace(
            plan,
            sources=tuple(
                replace(source, action="exclude") if source.id == "web" else source
                for source in plan.sources
            ),
        )
    run_dir = tmp_path / "runs/re-active"
    (run_dir / "re").mkdir(parents=True)
    (tmp_path / "runs/.current-re").write_text("re-active\n", encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "re-active",
                "run_kind": "re",
                "status": "running",
                "re_policy": "target-only",
                "target_source": "api",
                "force_selected_refresh": persisted_force,
                "expected_generation": 4,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "re/re-execution-plan.json").write_text(
        json.dumps(plan.to_json_dict()),
        encoding="utf-8",
    )
    controller = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=object,
    )
    monkeypatch.setattr(
        controller,
        "_execute_run",
        lambda *args, **kwargs: pytest.fail("unauthenticated active plan was executed"),
    )

    with pytest.raises(ReLifecycleError, match="active RE run.*forced selected refresh"):
        controller.run(
            policy="target-only",
            target_source="api",
            force_selected_refresh=True,
        )


@pytest.mark.unit
def test_empty_targeted_run_never_invokes_semantic_analyzer_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness.re_controller import ReControllerResult, ReExtractionController

    source = tmp_path / "sources/docs"
    source.mkdir(parents=True)
    manifest = _manifest_with_source(tmp_path, "docs", source_file_count=0)
    profile = ReFingerprintProfile()
    monkeypatch.setattr("harness.re_lifecycle.discover_workspace", lambda root: manifest)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_re_fingerprint_profile", lambda root: profile
    )
    monkeypatch.setattr("harness.re_lifecycle.load_published_index", lambda root: None)
    run_analysis = ReExtractionController._run_analysis_script

    class EmptyExtractionController:
        def __init__(self, **kwargs: object) -> None:
            self._kwargs = kwargs

        def run(self) -> ReControllerResult:
            run_dir = self._kwargs["run_dir"]
            assert isinstance(run_dir, Path)
            plan = ReExecutionPlan.from_json_dict(
                json.loads((run_dir / "re/re-execution-plan.json").read_text())
            )
            assert plan.analysis_required is False
            controller = object.__new__(ReExtractionController)
            controller._run_re_dir = run_dir / "re"
            controller._extension_root = tmp_path / "missing-extension"
            controller._execute_analysis_command = lambda *args, **kwargs: pytest.fail(
                "empty selected source invoked the semantic analyzer"
            )
            assert run_analysis(controller, plan) is None
            return ReControllerResult(completed=True)

    monkeypatch.setattr(
        "harness.re_lifecycle.ReExtractionController", EmptyExtractionController
    )

    result = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=object,
    ).run(
        policy="target-only",
        target_source="docs",
        force_selected_refresh=True,
    )

    assert result.status == "done"
    assert result.run_id


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


@pytest.mark.unit
def test_work_bearing_run_completes_with_explicit_publication_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = ReFingerprintProfile()
    monkeypatch.setattr("harness.re_lifecycle.discover_workspace", _empty_manifest)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_re_fingerprint_profile", lambda root: profile
    )
    monkeypatch.setattr("harness.re_lifecycle.load_published_index", lambda root: None)
    monkeypatch.setattr(
        "harness.re_lifecycle.build_re_execution_plan",
        lambda **kwargs: _work_plan(profile),
    )

    def materialize(**kwargs: object) -> dict[str, object]:
        run_re_dir = kwargs["run_re_dir"]
        assert isinstance(run_re_dir, Path)
        run_re_dir.mkdir(parents=True)
        return {}

    monkeypatch.setattr("harness.re_lifecycle.materialize_re_run_context", materialize)
    extraction_calls: list[Path] = []

    class FakeExtractionController:
        def __init__(self, **kwargs: object) -> None:
            run_dir = kwargs["run_dir"]
            assert isinstance(run_dir, Path)
            extraction_calls.append(run_dir)

        def run(self):
            from harness.re_controller import ReControllerResult

            return ReControllerResult(completed=True)

    monkeypatch.setattr(
        "harness.re_lifecycle.ReExtractionController", FakeExtractionController
    )
    provider = object()
    controller = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=lambda: provider,
    )

    result = controller.run(policy="refresh-all", re_max_inner=7, reset=False)

    assert result.status == "done"
    assert result.generation == 0
    assert len(extraction_calls) == 1
    assert (tmp_path / "runs/.current-re").read_text().strip() == result.run_id
    state = json.loads((tmp_path / "runs" / result.run_id / "state.json").read_text())
    assert state["run_kind"] == "re"
    assert state["extraction_complete"] is True
    assert state["publication_complete"] is False
    assert state["publication_pending"] is True
    assert state["re_max_inner"] == 7


@pytest.mark.unit
def test_continue_completed_run_does_not_publish_or_repeat_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = ReFingerprintProfile()
    monkeypatch.setattr("harness.re_lifecycle.discover_workspace", _empty_manifest)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_re_fingerprint_profile", lambda root: profile
    )
    monkeypatch.setattr("harness.re_lifecycle.load_published_index", lambda root: None)
    monkeypatch.setattr(
        "harness.re_lifecycle.build_re_execution_plan",
        lambda **kwargs: _work_plan(profile),
    )
    monkeypatch.setattr(
        "harness.re_lifecycle.materialize_re_run_context",
        lambda **kwargs: kwargs["run_re_dir"].mkdir(parents=True) or {},
    )
    extraction_calls: list[bool] = []

    class FakeExtractionController:
        def __init__(self, **kwargs: object) -> None:
            pass

        def run(self):
            from harness.re_controller import ReControllerResult

            extraction_calls.append(True)
            return ReControllerResult(completed=True)

    monkeypatch.setattr(
        "harness.re_lifecycle.ReExtractionController", FakeExtractionController
    )
    controller = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=object,
    )

    first = controller.run(policy="refresh-all", re_max_inner=None, reset=False)
    second = controller.continue_run()

    assert first.status == "done"
    assert second.status == "done"
    assert extraction_calls == [True]


def _blocked_forced_target_run_that_becomes_overlapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    pending_decision: bool,
) -> tuple[ReLifecycleController, Path, list[bool], list[bool]]:
    for source_id in ("api", "web"):
        source = tmp_path / f"sources/{source_id}"
        source.mkdir(parents=True)
        (source / "app.py").write_text("pass\n", encoding="utf-8")
    manifest = WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(root=tmp_path, git_role="orchestration", git_present=False),
        sources=tuple(
            SourceRoot(
                id=source_id,
                path=f"sources/{source_id}",
                git_present=False,
                project_markers=(),
                source_file_count=1,
            )
            for source_id in ("api", "web")
        ),
    )
    profile = ReFingerprintProfile()
    published_source = SimpleNamespace(
        fingerprint="1" * 64,
        profile_hash=profile.profile_hash(),
        source_path="sources/web",
    )
    published = SimpleNamespace(generation=4, sources={"web": published_source})
    monkeypatch.setattr("harness.re_lifecycle.discover_workspace", lambda root: manifest)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_re_fingerprint_profile", lambda root: profile
    )
    monkeypatch.setattr("harness.re_lifecycle.load_published_index", lambda root: published)
    monkeypatch.setattr(
        "harness.re_planner.published_source_is_usable", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        "harness.re_planner.published_source_is_current", lambda *args, **kwargs: False
    )
    plan = build_re_execution_plan(
        project_root=tmp_path,
        manifest=manifest,
        target_source="api",
        requested_policy="target-only",
        profile=profile,
        published_index=published,
        force_selected_refresh=True,
    )
    run_dir = tmp_path / "runs/re-blocked"
    re_dir = run_dir / "re"
    re_dir.mkdir(parents=True)
    (tmp_path / "runs/.current-re").write_text("re-blocked\n", encoding="utf-8")
    decision = {
        "status": "pending" if pending_decision else "resolved",
        "question": "Continue?",
        "options": [{"id": "continue", "label": "Continue"}],
        "blocked_phase": "re-extract-2-specify",
    }
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "re-blocked",
                "run_kind": "re",
                "status": "blocked",
                "phase": "re-extract-2-specify",
                "re_policy": "target-only",
                "target_source": "api",
                "force_selected_refresh": True,
                "expected_generation": 4,
                "extraction_complete": False,
                "blocked_decision": decision,
            }
        ),
        encoding="utf-8",
    )
    (re_dir / "state.json").write_text(
        json.dumps({"phase": "re-extract-2-specify"}), encoding="utf-8"
    )
    (re_dir / "re-execution-plan.json").write_text(
        json.dumps(plan.to_json_dict()), encoding="utf-8"
    )

    provider_calls: list[bool] = []
    analyzer_calls: list[bool] = []

    class ForbiddenExtractionController:
        def __init__(self, **kwargs: object) -> None:
            analyzer_calls.append(True)

        def run(self) -> object:
            pytest.fail("overlapping targeted run reached extraction")

    monkeypatch.setattr(
        "harness.re_lifecycle.ReExtractionController", ForbiddenExtractionController
    )
    controller = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=lambda: provider_calls.append(True),
    )

    api = tmp_path / "sources/api"
    (api / "app.py").unlink()
    api.rmdir()
    api.symlink_to(tmp_path / "sources/web", target_is_directory=True)
    return controller, run_dir, provider_calls, analyzer_calls


@pytest.mark.unit
def test_continue_revalidates_forced_target_root_isolation_before_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, _run_dir, provider_calls, analyzer_calls = (
        _blocked_forced_target_run_that_becomes_overlapping(
            tmp_path, monkeypatch, pending_decision=False
        )
    )

    with pytest.raises(ReLifecycleError, match="overlapping source roots.*api.*web"):
        controller.continue_run()

    assert provider_calls == []
    assert analyzer_calls == []


@pytest.mark.unit
def test_resume_revalidates_forced_target_root_isolation_before_state_or_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, run_dir, provider_calls, analyzer_calls = (
        _blocked_forced_target_run_that_becomes_overlapping(
            tmp_path, monkeypatch, pending_decision=True
        )
    )

    with pytest.raises(ReLifecycleError, match="overlapping source roots.*api.*web"):
        controller.resume("continue")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "blocked"
    assert state["blocked_decision"]["status"] == "pending"
    assert provider_calls == []
    assert analyzer_calls == []


@pytest.mark.unit
def test_resume_rejects_run_without_typed_question(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs/re-1"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs/.current-re").write_text("re-1\n", encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps({"run_id": "re-1", "run_kind": "re", "status": "blocked"}),
        encoding="utf-8",
    )
    controller = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=object,
    )

    with pytest.raises(ReLifecycleError, match="not waiting for human input"):
        controller.resume("answer")


@pytest.mark.unit
def test_resume_records_typed_answer_before_continuing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "runs/re-1"
    re_dir = run_dir / "re"
    re_dir.mkdir(parents=True)
    (tmp_path / "runs/.current-re").write_text("re-1\n", encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "re-1",
                "run_kind": "re",
                "status": "blocked",
                "phase": "re-extract-2-specify",
                "blocked_reason": "human_choice_required",
                "escalation_question": "Which API contract is authoritative?",
                "extraction_complete": False,
            }
        ),
        encoding="utf-8",
    )
    (re_dir / "state.json").write_text(
        json.dumps({"phase": "re-extract-2-specify"}), encoding="utf-8"
    )

    class FakeExtractionController:
        def __init__(self, **kwargs: object) -> None:
            pass

        def run(self):
            from harness.re_controller import ReControllerResult

            return ReControllerResult(
                completed=False,
                blocked_reason="still_blocked",
                blocked_detail="state update was rejected",
            )

    monkeypatch.setattr(
        "harness.re_lifecycle.ReExtractionController", FakeExtractionController
    )
    controller = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=object,
    )

    result = controller.resume("Use the public v2 contract")

    assert result.status == "blocked"
    assert result.blocked_detail == "state update was rejected"
    state = json.loads((run_dir / "state.json").read_text())
    assert state["blocked_decision"]["status"] == "resolved"
    assert state["resume_metadata"]["source"] == "echelon re resume"
    assert state["resume_answer"] == "Use the public v2 contract"
    re_state = json.loads((re_dir / "state.json").read_text())
    assert re_state["resume_answer"] == "Use the public v2 contract"
