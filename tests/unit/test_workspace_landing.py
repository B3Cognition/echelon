from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import harness.workspace_landing as workspace_landing
from echelon.spec_publish import SpecPublishError
from harness.fulfillment_runner import _spec_input_hash
from harness.spec_frontmatter import read_frontmatter
from harness.workspace_landing import (
    finalize_workspace_landing,
    landing_transition_covers_hashes,
)


def _git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Echelon Test")
    _git(repo, "config", "user.email", "echelon@example.test")
    (repo / "README.md").write_text("# Test\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")


def _create_spec_branch(workspace: Path, spec_id: str = "001-demo") -> Path:
    _git(workspace, "switch", "-c", spec_id)
    spec_dir = workspace / "specs" / spec_id
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: ready_to_land\n---\n# Demo\n\n"
        "**Status**: ready_to_land\n",
        encoding="utf-8",
    )
    (spec_dir / "harness-run-history.json").write_text(
        json.dumps({"runs": []}, indent=2) + "\n",
        encoding="utf-8",
    )
    _git(workspace, "add", f"specs/{spec_id}")
    _git(workspace, "commit", "-m", "spec ready")
    return spec_dir


@pytest.mark.unit
def test_polyrepo_finalization_commits_publishes_and_returns_to_clean_main(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    target = tmp_path / "target"
    _init_repo(workspace)
    _init_repo(target)
    spec_dir = _create_spec_branch(workspace)
    (spec_dir / "harness-run-history.json").write_text(
        json.dumps({"runs": [{"build_id": "build-final"}]}, indent=2) + "\n",
        encoding="utf-8",
    )

    result = finalize_workspace_landing(
        "001-demo",
        workspace_root=workspace,
        target_root=target,
    )

    assert result.ok is True
    assert result.source_commit
    assert result.published_commit
    assert _git(workspace, "branch", "--show-current") == "main"
    assert _git(workspace, "status", "--porcelain") == ""
    published_spec = _git(workspace, "show", "main:specs/001-demo/spec.md")
    assert "status: landed" in published_spec
    assert "**Status**: landed" in published_spec
    published_history = json.loads(
        _git(
            workspace,
            "show",
            "main:specs/001-demo/harness-run-history.json",
        )
    )
    assert published_history["runs"] == [{"build_id": "build-final"}]
    manifest = json.loads(
        _git(workspace, "show", "main:specs/001-demo/.echelon-publication.json")
    )
    assert manifest["source_commit"] == result.source_commit


@pytest.mark.unit
def test_monorepo_finalization_commits_bounded_spec_changes_on_main(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    spec_dir = repo / "specs/001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: ready_to_land\n---\n# Demo\n",
        encoding="utf-8",
    )
    _git(repo, "add", "specs/001-demo/spec.md")
    _git(repo, "commit", "-m", "ready")

    result = finalize_workspace_landing(
        "001-demo",
        workspace_root=repo,
        target_root=repo,
    )

    assert result.ok is True
    assert result.published_commit is None
    assert _git(repo, "branch", "--show-current") == "main"
    assert _git(repo, "status", "--porcelain") == ""
    assert "status: landed" in (spec_dir / "spec.md").read_text(encoding="utf-8")
    assert _git(repo, "log", "-1", "--pretty=%s") == (
        "chore: finalize landed spec 001-demo"
    )


@pytest.mark.unit
def test_finalization_refuses_unrelated_workspace_dirt_without_deleting_it(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    target = tmp_path / "target"
    _init_repo(workspace)
    _init_repo(target)
    spec_dir = _create_spec_branch(workspace)
    (spec_dir / "harness-run-history.json").write_text(
        '{"runs":[{"build_id":"build-final"}]}\n',
        encoding="utf-8",
    )
    unknown = workspace / "notes.txt"
    unknown.write_text("keep me\n", encoding="utf-8")

    result = finalize_workspace_landing(
        "001-demo",
        workspace_root=workspace,
        target_root=target,
    )

    assert result.ok is False
    assert result.reason == "workspace_dirty"
    assert result.paths == ("?? notes.txt",)
    assert unknown.read_text(encoding="utf-8") == "keep me\n"
    assert "status: ready_to_land" in (spec_dir / "spec.md").read_text(
        encoding="utf-8"
    )
    assert _git(workspace, "branch", "--show-current") == "001-demo"


@pytest.mark.unit
def test_finalization_refuses_dirty_target_without_deleting_output(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    target = tmp_path / "target"
    _init_repo(workspace)
    _init_repo(target)
    spec_dir = _create_spec_branch(workspace)
    output = target / "test-results/result.json"
    output.parent.mkdir()
    output.write_text("{}\n", encoding="utf-8")

    result = finalize_workspace_landing(
        "001-demo",
        workspace_root=workspace,
        target_root=target,
    )

    assert result.ok is False
    assert result.reason == "target_dirty"
    assert result.paths == ("?? test-results/result.json",)
    assert output.is_file()
    assert "status: ready_to_land" in (spec_dir / "spec.md").read_text(
        encoding="utf-8"
    )


@pytest.mark.unit
def test_polyrepo_finalization_is_idempotent_after_publication(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    target = tmp_path / "target"
    _init_repo(workspace)
    _init_repo(target)
    _create_spec_branch(workspace)

    first = finalize_workspace_landing(
        "001-demo", workspace_root=workspace, target_root=target
    )
    first_main = _git(workspace, "rev-parse", "main")
    first_source = _git(workspace, "rev-parse", "001-demo")

    second = finalize_workspace_landing(
        "001-demo", workspace_root=workspace, target_root=target
    )

    assert first.ok is True
    assert second.ok is True
    assert _git(workspace, "rev-parse", "main") == first_main
    assert _git(workspace, "rev-parse", "001-demo") == first_source
    assert _git(workspace, "status", "--porcelain") == ""


@pytest.mark.unit
def test_publication_failure_leaves_clean_landed_source_for_safe_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    target = tmp_path / "target"
    _init_repo(workspace)
    _init_repo(target)
    spec_dir = _create_spec_branch(workspace)
    recorded_hash = _spec_input_hash(spec_dir)

    def fail_publish(*args: object, **kwargs: object) -> object:
        raise SpecPublishError("injected publication failure")

    monkeypatch.setattr(workspace_landing, "publish_specs", fail_publish)

    result = finalize_workspace_landing(
        "001-demo", workspace_root=workspace, target_root=target
    )

    assert result.ok is False
    assert result.reason == "workspace_finalize_failed"
    assert "injected publication failure" in result.detail
    assert _git(workspace, "branch", "--show-current") == "001-demo"
    assert _git(workspace, "status", "--porcelain") == ""
    assert "status: landed" in _git(
        workspace, "show", "001-demo:specs/001-demo/spec.md"
    )
    assert landing_transition_covers_hashes(
        spec_dir,
        recorded_hash=recorded_hash,
        current_hash=_spec_input_hash(spec_dir),
    )
    assert _git(workspace, "ls-tree", "--name-only", "main", "specs/001-demo") == ""

    with (spec_dir / "spec.md").open("a", encoding="utf-8") as handle:
        handle.write("\nUnverified scope change.\n")
    assert not landing_transition_covers_hashes(
        spec_dir,
        recorded_hash=recorded_hash,
        current_hash=_spec_input_hash(spec_dir),
    )


@pytest.mark.unit
def test_transition_write_failure_is_recoverable_without_overwriting_unknown_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    target = tmp_path / "target"
    _init_repo(workspace)
    _init_repo(target)
    spec_dir = _create_spec_branch(workspace)
    recorded_hash = _spec_input_hash(spec_dir)

    def fail_transition(*args: object, **kwargs: object) -> None:
        raise OSError("injected transition write failure")

    monkeypatch.setattr(workspace_landing, "_record_landing_transition", fail_transition)
    first = finalize_workspace_landing(
        "001-demo", workspace_root=workspace, target_root=target
    )

    assert first.ok is False
    assert first.reason == "workspace_finalize_failed"
    assert "injected transition write failure" in first.detail
    assert read_frontmatter(spec_dir)["status"] == "landed"
    assert not (spec_dir / "landing-transition.json").exists()

    monkeypatch.undo()
    second = finalize_workspace_landing(
        "001-demo", workspace_root=workspace, target_root=target
    )

    assert second.ok is True
    assert landing_transition_covers_hashes(
        spec_dir,
        recorded_hash=recorded_hash,
        current_hash=_spec_input_hash(spec_dir),
    )


@pytest.mark.unit
def test_status_only_recovery_rejects_other_frontmatter_changes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _init_repo(workspace)
    spec_dir = _create_spec_branch(workspace)
    spec_path = spec_dir / "spec.md"
    original = spec_path.read_text(encoding="utf-8").replace(
        "status: ready_to_land",
        "status: ready_to_land\ntitle: Original",
        1,
    )
    spec_path.write_text(original, encoding="utf-8")
    _git(workspace, "add", "specs/001-demo/spec.md")
    _git(workspace, "commit", "-m", "add verified metadata")
    recorded_hash = _spec_input_hash(spec_dir)
    spec_path.write_text(
        original.replace("status: ready_to_land", "status: landed", 1).replace(
            "title: Original",
            "title: Changed after verification",
            1,
        ),
        encoding="utf-8",
    )

    assert not workspace_landing.landing_transition_allows_retry(
        spec_dir,
        workspace_root=workspace,
        recorded_hash=recorded_hash,
        current_hash=_spec_input_hash(spec_dir),
    )


@pytest.mark.unit
def test_finalization_preserves_unknown_transition_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    target = tmp_path / "target"
    _init_repo(workspace)
    _init_repo(target)
    spec_dir = _create_spec_branch(workspace)
    collision = spec_dir / "landing-transition.json"
    collision.write_text("user-owned content\n", encoding="utf-8")

    result = finalize_workspace_landing(
        "001-demo", workspace_root=workspace, target_root=target
    )

    assert result.ok is False
    assert result.reason == "workspace_file_collision"
    assert str(collision) in result.detail
    assert collision.read_text(encoding="utf-8") == "user-owned content\n"
    assert read_frontmatter(spec_dir)["status"] == "ready_to_land"


@pytest.mark.unit
def test_finalization_rejects_symlinked_spec_directory_without_touching_target(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    notes = repo / "notes"
    notes.mkdir()
    note_spec = notes / "spec.md"
    note_spec.write_text(
        "---\nstatus: ready_to_land\n---\n# Notes\n",
        encoding="utf-8",
    )
    specs = repo / "specs"
    specs.mkdir()
    (specs / "001-demo").symlink_to("../notes", target_is_directory=True)
    _git(repo, "add", "notes/spec.md", "specs/001-demo")
    _git(repo, "commit", "-m", "symlink fixture")

    result = finalize_workspace_landing(
        "001-demo", workspace_root=repo, target_root=repo
    )

    assert result.ok is False
    assert result.reason == "unsafe_spec_path"
    assert "status: ready_to_land" in note_spec.read_text(encoding="utf-8")
    assert _git(repo, "status", "--porcelain") == ""
