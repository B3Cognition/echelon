from __future__ import annotations

import json
from pathlib import Path

import pytest

from echelon.workspace_model import WorkspaceInfo, WorkspaceManifest
from harness.re_controller import ReControllerResult
from harness.re_fingerprint import ReFingerprintProfile
from harness.re_lifecycle import ReLifecycleController
from harness.re_planner import ReExecutionPlan
from harness.re_registry import load_published_index
from tests.unit.test_re_publication import write_valid_re_run


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


@pytest.mark.integration
def test_re_lifecycle_automatically_publishes_complete_output(
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

    class CompleteController:
        def __init__(self, **kwargs: object) -> None:
            self.run_dir = Path(kwargs["run_dir"])

        def run(self) -> ReControllerResult:
            outer = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
            write_valid_re_run(tmp_path, ("api",), run_id=self.run_dir.name)
            (self.run_dir / "state.json").write_text(
                json.dumps(outer, indent=2) + "\n",
                encoding="utf-8",
            )
            return ReControllerResult(completed=True)

    monkeypatch.setattr("harness.re_lifecycle.ReExtractionController", CompleteController)
    controller = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=object,
    )

    result = controller.run(policy="refresh-all")

    assert result.status == "done"
    assert result.generation == 1
    published = load_published_index(tmp_path)
    assert published is not None
    assert published.generation == 1
    assert set(published.sources) == {"api"}
    run_state = json.loads(
        (tmp_path / "runs" / result.run_id / "state.json").read_text(encoding="utf-8")
    )
    assert run_state["extraction_complete"] is True
    assert run_state["publication_complete"] is True


@pytest.mark.integration
def test_active_spec_run_does_not_block_re_lifecycle_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec_dir = tmp_path / "runs/spec-active"
    spec_dir.mkdir(parents=True)
    (spec_dir / "state.json").write_text(
        json.dumps({"run_id": "spec-active", "status": "in_progress"}) + "\n",
        encoding="utf-8",
    )
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

    class CompleteController:
        def __init__(self, **kwargs: object) -> None:
            self.run_dir = Path(kwargs["run_dir"])

        def run(self) -> ReControllerResult:
            outer = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
            write_valid_re_run(tmp_path, ("api",), run_id=self.run_dir.name)
            (self.run_dir / "state.json").write_text(
                json.dumps(outer, indent=2) + "\n",
                encoding="utf-8",
            )
            return ReControllerResult(completed=True)

    monkeypatch.setattr("harness.re_lifecycle.ReExtractionController", CompleteController)

    result = ReLifecycleController(
        project_root=tmp_path,
        extension_root=tmp_path / "extension",
        provider_factory=object,
    ).run(policy="refresh-all")

    assert result.status == "done"
    assert load_published_index(tmp_path).generation == 1
