from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from echelon.workspace_model import WorkspaceInfo, WorkspaceManifest
from harness.re_fingerprint import ReFingerprintProfile
from harness.re_lifecycle import (
    ReLifecycleController,
    ReLifecycleError,
    resolve_current_re_run,
)
from harness.re_planner import ReExecutionPlan
from harness.re_publication import RePublicationError, RePublicationResult


def _empty_manifest(root: Path) -> WorkspaceManifest:
    return WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(root=root, git_role="orchestration", git_present=False),
        sources=(),
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


def _changed_plan_with_reuse(root: Path, profile: ReFingerprintProfile) -> ReExecutionPlan:
    return ReExecutionPlan.from_json_dict(
        {
            "schema_version": 1,
            "policy": "changed",
            "requested_policy": "changed",
            "target_source": "",
            "forbidden_source_roots": [],
            "profile": profile.to_json_dict(),
            "sources": [
                {
                    "id": "api",
                    "path": "sources/api",
                    "absolute_path": str(root / "sources/api"),
                    "action": "reuse",
                    "fingerprint": {
                        "value": "api-current",
                        "kind": "file-tree",
                        "dirty": False,
                        "profile_hash": profile.profile_hash(),
                    },
                    "cache_path": str(root / "re/.cache/api"),
                    "dirty": False,
                    "selected": True,
                    "classification": "current",
                },
                {
                    "id": "worker",
                    "path": "sources/worker",
                    "absolute_path": str(root / "sources/worker"),
                    "action": "refresh",
                    "fingerprint": {
                        "value": "worker-stale",
                        "kind": "file-tree",
                        "dirty": False,
                        "profile_hash": profile.profile_hash(),
                    },
                    "cache_path": str(root / "re/.cache/worker"),
                    "dirty": False,
                    "selected": True,
                    "classification": "refresh",
                },
            ],
            "removed_sources": [],
            "analysis_required": True,
            "workspace_synthesis_required": True,
            "publication_required": True,
        }
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
def test_changed_run_preserves_reuse_actions_from_planner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = ReFingerprintProfile()
    plan = _changed_plan_with_reuse(tmp_path, profile)
    monkeypatch.setattr("harness.re_lifecycle.discover_workspace", _empty_manifest)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_re_fingerprint_profile", lambda root: profile
    )
    monkeypatch.setattr(
        "harness.re_lifecycle.load_published_index",
        lambda root: SimpleNamespace(generation=1),
    )
    monkeypatch.setattr(
        "harness.re_lifecycle.build_re_execution_plan", lambda **kwargs: plan
    )
    captured_plans: list[ReExecutionPlan] = []

    def materialize(**kwargs: object) -> dict[str, object]:
        captured = kwargs["plan"]
        run_re_dir = kwargs["run_re_dir"]
        assert isinstance(captured, ReExecutionPlan)
        assert isinstance(run_re_dir, Path)
        captured_plans.append(captured)
        run_re_dir.mkdir(parents=True)
        return {}

    monkeypatch.setattr("harness.re_lifecycle.materialize_re_run_context", materialize)

    class FakeExtractionController:
        def __init__(self, **kwargs: object) -> None:
            pass

        def run(self):
            from harness.re_controller import ReControllerResult

            return ReControllerResult(completed=True)

    monkeypatch.setattr(
        "harness.re_lifecycle.ReExtractionController", FakeExtractionController
    )
    controller = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=object,
    )

    result = controller.run(policy="changed", reset=False)

    assert result.status == "done"
    assert {source.id: source.action for source in captured_plans[0].sources} == {
        "api": "reuse",
        "worker": "refresh",
    }


@pytest.mark.unit
def test_no_reuse_forces_reusable_sources_to_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = ReFingerprintProfile()
    plan = _changed_plan_with_reuse(tmp_path, profile)
    monkeypatch.setattr("harness.re_lifecycle.discover_workspace", _empty_manifest)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_re_fingerprint_profile", lambda root: profile
    )
    monkeypatch.setattr(
        "harness.re_lifecycle.load_published_index",
        lambda root: SimpleNamespace(generation=1),
    )
    monkeypatch.setattr(
        "harness.re_lifecycle.build_re_execution_plan", lambda **kwargs: plan
    )
    captured_plans: list[ReExecutionPlan] = []

    def materialize(**kwargs: object) -> dict[str, object]:
        captured = kwargs["plan"]
        run_re_dir = kwargs["run_re_dir"]
        assert isinstance(captured, ReExecutionPlan)
        assert isinstance(run_re_dir, Path)
        captured_plans.append(captured)
        run_re_dir.mkdir(parents=True)
        return {}

    monkeypatch.setattr("harness.re_lifecycle.materialize_re_run_context", materialize)

    class FakeExtractionController:
        def __init__(self, **kwargs: object) -> None:
            pass

        def run(self):
            from harness.re_controller import ReControllerResult

            return ReControllerResult(completed=True)

    monkeypatch.setattr(
        "harness.re_lifecycle.ReExtractionController", FakeExtractionController
    )
    controller = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=object,
    )

    result = controller.run(policy="changed", reuse_published=False)

    assert result.status == "done"
    assert {source.id: source.action for source in captured_plans[0].sources} == {
        "api": "refresh",
        "worker": "refresh",
    }


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


@pytest.mark.unit
def test_continue_can_raise_token_ceiling_without_resetting_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "runs/re-1"
    re_dir = run_dir / "re"
    re_dir.mkdir(parents=True)
    (tmp_path / "runs/.current-re").write_text("re-1\n", encoding="utf-8")
    profile = {
        "name": "balanced",
        "hard_token_limit": 5_000_000,
        "hard_active_minutes": 180,
    }
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "re-1",
                "run_kind": "re",
                "status": "blocked",
                "re_execution_profile": profile,
            }
        ),
        encoding="utf-8",
    )
    (re_dir / "state.json").write_text(
        json.dumps(
            {
                "re_execution_profile": profile,
                "re_token_usage": 5_000_000,
            }
        ),
        encoding="utf-8",
    )

    class FakeExtractionController:
        def __init__(self, **kwargs: object) -> None:
            state = json.loads((re_dir / "state.json").read_text(encoding="utf-8"))
            assert state["re_execution_profile"]["hard_token_limit"] == 6_000_000
            assert state["re_token_usage"] == 5_000_000

        def run(self):
            from harness.re_controller import ReControllerResult

            return ReControllerResult(completed=True)

    monkeypatch.setattr(
        "harness.re_lifecycle.ReExtractionController", FakeExtractionController
    )
    controller = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=object,
    )

    result = controller.continue_run(hard_token_limit=6_000_000)

    assert result.status == "done"
    outer = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    inner = json.loads((re_dir / "state.json").read_text(encoding="utf-8"))
    assert outer["re_execution_profile"]["hard_token_limit"] == 6_000_000
    assert inner["re_execution_profile"]["hard_token_limit"] == 6_000_000
    assert inner["re_token_usage"] == 5_000_000
    assert outer["re_execution_budget_overrides"] == [
        {
            "hard_token_limit": {
                "previous": 5_000_000,
                "updated": 6_000_000,
            }
        }
    ]


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
