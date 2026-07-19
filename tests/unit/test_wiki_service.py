from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from echelon.wiki.render import WikiRenderError
from echelon.wiki.service import (
    WikiBuildError,
    WikiCleanError,
    build_wiki,
    capture_input_snapshot,
    clean_wiki,
    refresh_after_changed_command,
    wiki_status,
)


FIXED_NOW = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)


def _write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _workspace(tmp_path: Path) -> Path:
    _write_yaml(
        tmp_path / ".echelon/config.yml",
        {"sources": [], "wiki": {"auto_refresh": True}},
    )
    spec = tmp_path / "specs/001-demo"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text(
        "---\nstatus: phase_a\n---\n# Demo\n\n- **FR-001** Work.\n",
        encoding="utf-8",
    )
    (spec / "plan.md").write_text("# Plan\n", encoding="utf-8")
    (spec / "tasks.md").write_text("# Tasks\n\n- [ ] T-001 Work\n", encoding="utf-8")
    return tmp_path


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_spec(root: Path, spec_id: str) -> None:
    spec = root / "specs" / spec_id
    spec.mkdir(parents=True, exist_ok=True)
    (spec / "spec.md").write_text(
        f"---\nstatus: phase_a\n---\n# {spec_id}\n\n- **FR-001** Work.\n",
        encoding="utf-8",
    )
    (spec / "plan.md").write_text(f"# Plan for {spec_id}\n", encoding="utf-8")
    (spec / "tasks.md").write_text("# Tasks\n\n- [ ] T-001 Work\n", encoding="utf-8")


def _workspace_with_feature_and_published_master(
    tmp_path: Path,
) -> tuple[Path, Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "master")
    _git(repo, "config", "user.name", "Echelon Tests")
    _git(repo, "config", "user.email", "echelon@example.test")
    _write_yaml(
        repo / ".echelon/config.yml",
        {"target_default_branch": "master", "sources": [], "wiki": {"auto_refresh": True}},
    )
    _write_spec(repo, "001-one")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "publish 001")
    _git(repo, "switch", "-c", "004-feature")
    _write_spec(repo, "004-four")
    _git(repo, "add", "specs/004-four")
    _git(repo, "commit", "-m", "author 004")
    caller_head = _git(repo, "rev-parse", "HEAD")

    master_worktree = tmp_path / "master-worktree"
    _git(repo, "worktree", "add", str(master_worktree), "master")
    for spec_id in ("002-two", "003-three", "004-four"):
        _write_spec(master_worktree, spec_id)
    _git(master_worktree, "add", "specs")
    _git(master_worktree, "commit", "-m", "publish remaining specs")
    return repo, master_worktree, caller_head


@pytest.mark.unit
def test_build_writes_valid_manifest_and_fresh_status(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path)

    result = build_wiki(project_root, now=lambda: FIXED_NOW)
    status = wiki_status(project_root)

    assert result.home_path == project_root / ".echelon/runtime/wiki/Home.md"
    manifest = json.loads((result.output_dir / "manifest.json").read_text())
    assert manifest["echelon_human_wiki"] is True
    assert manifest["generated_at"] == "2026-07-18T10:00:00Z"
    assert "specs/001-demo/spec.md" in manifest["inputs"]
    assert "Home.md" in manifest["outputs"]
    assert status.state == "fresh"
    assert status.added_inputs == ()
    assert status.changed_inputs == ()
    assert status.removed_inputs == ()


@pytest.mark.unit
def test_feature_branch_build_uses_default_catalog_without_switching(
    tmp_path: Path,
) -> None:
    repo, _master_worktree, caller_head = _workspace_with_feature_and_published_master(
        tmp_path
    )

    result = build_wiki(repo, now=lambda: FIXED_NOW)

    assert _git(repo, "branch", "--show-current") == "004-feature"
    assert _git(repo, "rev-parse", "HEAD") == caller_head
    assert result.catalog_branch == "master"
    assert result.catalog_revision == _git(repo, "rev-parse", "master")
    for spec_id in ("001-one", "002-two", "003-three", "004-four"):
        assert (result.output_dir / f"Specs/{spec_id}/Overview.md").is_file()
    assert wiki_status(repo).state == "fresh"


@pytest.mark.unit
def test_default_catalog_commit_makes_feature_branch_wiki_stale(
    tmp_path: Path,
) -> None:
    repo, master_worktree, _caller_head = _workspace_with_feature_and_published_master(
        tmp_path
    )
    build_wiki(repo, now=lambda: FIXED_NOW)
    _write_spec(master_worktree, "005-five")
    _git(master_worktree, "add", "specs/005-five")
    _git(master_worktree, "commit", "-m", "publish 005")

    status = wiki_status(repo)

    assert status.state == "stale"
    assert "specs/005-five/spec.md" in status.added_inputs
    assert status.workspace_revision == _git(repo, "rev-parse", "master")


@pytest.mark.unit
def test_refresh_tracks_default_catalog_changes_from_feature_branch(
    tmp_path: Path,
) -> None:
    repo, master_worktree, caller_head = _workspace_with_feature_and_published_master(
        tmp_path
    )
    build_wiki(repo, now=lambda: FIXED_NOW)
    before = capture_input_snapshot(repo)
    assert before is not None
    _write_spec(master_worktree, "005-five")
    _git(master_worktree, "add", "specs/005-five")
    _git(master_worktree, "commit", "-m", "publish 005")

    refreshed = refresh_after_changed_command(repo, before, now=lambda: FIXED_NOW)

    assert refreshed is not None
    assert (refreshed.output_dir / "Specs/005-five/Overview.md").is_file()
    assert refreshed.catalog_revision == _git(repo, "rev-parse", "master")
    assert _git(repo, "branch", "--show-current") == "004-feature"
    assert _git(repo, "rev-parse", "HEAD") == caller_head


@pytest.mark.unit
def test_uncommitted_feature_spec_is_ignored_by_default_catalog(
    tmp_path: Path,
) -> None:
    repo, _master_worktree, _caller_head = _workspace_with_feature_and_published_master(
        tmp_path
    )
    build_wiki(repo, now=lambda: FIXED_NOW)
    feature_spec = repo / "specs/004-four/spec.md"
    feature_spec.write_text("# Unpublished feature-only edit\n", encoding="utf-8")

    status = wiki_status(repo)

    assert status.state == "fresh"
    projection = repo / ".echelon/runtime/wiki/Artifacts/specs/004-four/spec.md"
    assert "Unpublished feature-only edit" not in projection.read_text(encoding="utf-8")


@pytest.mark.unit
def test_failed_rebuild_preserves_previous_valid_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = _workspace(tmp_path)
    first = build_wiki(project_root, now=lambda: FIXED_NOW)
    home_before = first.home_path.read_bytes()

    def fail_render(*_args, **_kwargs):
        raise WikiRenderError("broken required link")

    monkeypatch.setattr("echelon.wiki.service.render_wiki", fail_render)

    with pytest.raises(WikiBuildError, match="broken required link"):
        build_wiki(project_root, now=lambda: FIXED_NOW)

    assert first.home_path.read_bytes() == home_before
    assert wiki_status(project_root).state == "fresh"


@pytest.mark.unit
def test_catalog_cleanup_failure_preserves_previous_valid_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _master_worktree, _caller_head = _workspace_with_feature_and_published_master(
        tmp_path
    )
    first = build_wiki(repo, now=lambda: FIXED_NOW)
    home_before = first.home_path.read_bytes()
    retained: list[Path] = []

    def fail_cleanup(path: Path) -> None:
        retained.append(path)
        raise OSError(f"cannot remove {path}")

    monkeypatch.setattr(
        "echelon.wiki.catalog_source._remove_temporary_parent", fail_cleanup
    )

    with pytest.raises(WikiBuildError, match="retained at"):
        build_wiki(repo, now=lambda: FIXED_NOW)

    assert first.home_path.read_bytes() == home_before
    monkeypatch.undo()
    for path in retained:
        shutil.rmtree(path)


@pytest.mark.unit
def test_status_detects_changed_added_and_removed_inputs(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path)
    build_wiki(project_root, now=lambda: FIXED_NOW)
    spec = project_root / "specs/001-demo/spec.md"
    spec.write_text("# Changed\n", encoding="utf-8")
    (project_root / "specs/001-demo/new.md").write_text("# New\n", encoding="utf-8")
    (project_root / "specs/001-demo/plan.md").unlink()

    status = wiki_status(project_root)

    assert status.state == "stale"
    assert status.changed_inputs == ("specs/001-demo/spec.md",)
    assert status.added_inputs == ("specs/001-demo/new.md",)
    assert status.removed_inputs == ("specs/001-demo/plan.md",)


@pytest.mark.unit
def test_clean_refuses_output_without_valid_manifest(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path)
    output = project_root / ".echelon/runtime/wiki"
    output.mkdir(parents=True)
    (output / "human-note.md").write_text("keep me\n", encoding="utf-8")

    with pytest.raises(WikiCleanError, match="valid Echelon wiki manifest"):
        clean_wiki(project_root)

    assert (output / "human-note.md").is_file()


@pytest.mark.unit
def test_clean_removes_only_valid_generated_vault_and_is_idempotent(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path)
    build_wiki(project_root, now=lambda: FIXED_NOW)

    removed = clean_wiki(project_root)
    removed_again = clean_wiki(project_root)

    assert removed == project_root / ".echelon/runtime/wiki"
    assert removed_again is None
    assert not removed.exists()


@pytest.mark.unit
def test_refresh_rebuilds_only_when_existing_vault_inputs_change(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path)
    assert capture_input_snapshot(project_root) is None
    build_wiki(project_root, now=lambda: FIXED_NOW)
    before = capture_input_snapshot(project_root)
    assert before is not None
    spec = project_root / "specs/001-demo/spec.md"
    spec.write_text("# Changed by command\n", encoding="utf-8")

    refreshed = refresh_after_changed_command(
        project_root, before, now=lambda: FIXED_NOW
    )

    assert refreshed is not None
    projection = project_root / ".echelon/runtime/wiki/Artifacts/specs/001-demo/spec.md"
    assert "Changed by command" in projection.read_text(encoding="utf-8")


@pytest.mark.unit
def test_refresh_does_not_run_when_only_resolved_config_changes(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path)
    build_wiki(project_root, now=lambda: FIXED_NOW)
    before = capture_input_snapshot(project_root)
    assert before is not None
    _write_yaml(
        project_root / ".echelon/local.yml",
        {"workspace": {"git_role": "orchestration"}},
    )

    refreshed = refresh_after_changed_command(
        project_root, before, now=lambda: FIXED_NOW
    )

    assert refreshed is None
    assert wiki_status(project_root).state == "stale"


@pytest.mark.unit
def test_local_config_can_disable_auto_refresh(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path)
    build_wiki(project_root, now=lambda: FIXED_NOW)
    before = capture_input_snapshot(project_root)
    _write_yaml(project_root / ".echelon/local.yml", {"wiki": {"auto_refresh": False}})
    (project_root / "specs/001-demo/spec.md").write_text("# Changed\n", encoding="utf-8")

    refreshed = refresh_after_changed_command(
        project_root, before, now=lambda: FIXED_NOW
    )

    assert refreshed is None
    assert wiki_status(project_root).state == "stale"
