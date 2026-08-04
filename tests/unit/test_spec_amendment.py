"""Tests for the pre-build spec amendment lifecycle."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


def _write_spec(repo: Path, spec_id: str, body: str = "planned") -> None:
    spec = repo / "specs" / spec_id / "spec.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(body + "\n", encoding="utf-8")
    _git(repo, "add", str(spec.relative_to(repo)))
    _git(repo, "commit", "-m", f"add {spec_id}")


def test_control_baseline_prefers_existing_spec_branch_over_caller_branch(tmp_path: Path) -> None:
    from echelon.spec_amendment import resolve_control_baseline

    repo = _repo(tmp_path)
    _write_spec(repo, "004-demo", "main copy")
    _git(repo, "switch", "-c", "004-demo")
    _write_spec(repo, "004-demo", "spec branch copy")
    expected = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "main")
    _git(repo, "switch", "-c", "006-other-work")

    baseline = resolve_control_baseline(repo, "004-demo")

    assert baseline.branch == "004-demo"
    assert baseline.commit == expected
    assert baseline.used_default_branch is False
    assert _git(repo, "branch", "--show-current") == "006-other-work"


def test_control_baseline_falls_back_to_default_branch_when_spec_branch_is_missing(tmp_path: Path) -> None:
    from echelon.spec_amendment import resolve_control_baseline

    repo = _repo(tmp_path)
    _write_spec(repo, "004-demo")
    expected = _git(repo, "rev-parse", "main")
    _git(repo, "switch", "-c", "006-other-work")

    baseline = resolve_control_baseline(repo, "004-demo")

    assert baseline.branch == "main"
    assert baseline.commit == expected
    assert baseline.used_default_branch is True
    assert _git(repo, "branch", "--show-current") == "006-other-work"


def test_control_baseline_refuses_missing_spec_on_default_branch(tmp_path: Path) -> None:
    from echelon.spec_amendment import SpecAmendmentError, resolve_control_baseline

    repo = _repo(tmp_path)

    with pytest.raises(SpecAmendmentError, match="does not contain spec"):
        resolve_control_baseline(repo, "004-demo")


def test_amendment_lock_is_scoped_to_the_spec_being_amended(tmp_path: Path) -> None:
    from echelon.spec_amendment import (
        AmendmentLock,
        SpecAmendmentLocked,
        prepare_amendment,
    )

    repo = _repo(tmp_path)
    _write_spec(repo, "004-demo")

    with AmendmentLock.acquire(repo, "004-demo", "test-owner"):
        with pytest.raises(SpecAmendmentLocked, match="test-owner"):
            AmendmentLock.acquire(repo, "004-demo", "other-owner")
        with pytest.raises(SpecAmendmentLocked, match="test-owner"):
            prepare_amendment(repo, ["004-demo", "Concurrent change"])
        with AmendmentLock.acquire(repo, "006-demo", "other-owner"):
            pass


def test_amendment_uses_the_shared_spec_mutation_lock(tmp_path: Path) -> None:
    from echelon.spec_amendment import SpecAmendmentLocked, prepare_amendment
    from echelon.spec_lifecycle import SpecMutationLock

    repo = _repo(tmp_path)
    _write_spec(repo, "004-demo")

    with SpecMutationLock.acquire(repo, "004-demo", "retarget-held"):
        with pytest.raises(SpecAmendmentLocked, match="retarget-held"):
            prepare_amendment(repo, ["004-demo", "Concurrent change"])


def test_amendment_worktree_leaves_caller_branch_unchanged(tmp_path: Path) -> None:
    from echelon.spec_amendment import create_amendment_worktree, resolve_control_baseline

    repo = _repo(tmp_path)
    _write_spec(repo, "004-demo")
    _git(repo, "switch", "-c", "004-demo")
    baseline_commit = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "main")
    _git(repo, "switch", "-c", "006-other-work")
    caller_branch = _git(repo, "branch", "--show-current")
    baseline = resolve_control_baseline(repo, "004-demo")

    worktree = create_amendment_worktree(repo, baseline, revision=1)

    assert _git(repo, "branch", "--show-current") == caller_branch
    assert _git(worktree.path, "branch", "--show-current") == "amend/004-demo/001"
    assert _git(worktree.path, "rev-parse", "HEAD") == baseline_commit
    assert (worktree.path / "specs" / "004-demo" / "spec.md").is_file()


def test_target_baseline_falls_back_to_target_default_branch(tmp_path: Path) -> None:
    from echelon.spec_amendment import resolve_target_baseline

    target = _repo(tmp_path)
    _git(target, "switch", "-c", "006-other-work")
    expected = _git(target, "rev-parse", "main")

    baseline = resolve_target_baseline(
        target,
        feature_branch="004-demo",
        configured_default_branch="main",
    )

    assert baseline.branch == "main"
    assert baseline.commit == expected
    assert baseline.used_default_branch is True
    assert _git(target, "branch", "--show-current") == "006-other-work"


def test_target_baseline_prefers_existing_feature_branch(tmp_path: Path) -> None:
    from echelon.spec_amendment import resolve_target_baseline

    target = _repo(tmp_path)
    _git(target, "switch", "-c", "004-demo")
    (target / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(target, "add", "feature.txt")
    _git(target, "commit", "-m", "feature")
    expected = _git(target, "rev-parse", "HEAD")
    _git(target, "switch", "main")

    baseline = resolve_target_baseline(
        target,
        feature_branch="004-demo",
        configured_default_branch="main",
    )

    assert baseline.branch == "004-demo"
    assert baseline.commit == expected
    assert baseline.used_default_branch is False


def test_promote_amendment_uses_compare_and_swap(tmp_path: Path) -> None:
    from echelon.spec_amendment import (
        promote_amendment,
        resolve_control_baseline,
    )

    repo = _repo(tmp_path)
    _write_spec(repo, "004-demo")
    _git(repo, "switch", "-c", "004-demo")
    old_commit = _git(repo, "rev-parse", "HEAD")
    baseline = resolve_control_baseline(repo, "004-demo")
    _git(repo, "switch", "-c", "amend/004-demo/001")
    (repo / "specs" / "004-demo" / "spec.md").write_text("amended\n", encoding="utf-8")
    _git(repo, "add", "specs/004-demo/spec.md")
    _git(repo, "commit", "-m", "amend spec")
    amended_commit = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "main")

    promote_amendment(repo, baseline, amended_commit)

    assert _git(repo, "rev-parse", "004-demo") == amended_commit
    assert old_commit != amended_commit


def test_promote_amendment_refuses_changed_canonical_branch(tmp_path: Path) -> None:
    from echelon.spec_amendment import (
        SpecAmendmentConflict,
        promote_amendment,
        resolve_control_baseline,
    )

    repo = _repo(tmp_path)
    _write_spec(repo, "004-demo")
    _git(repo, "switch", "-c", "004-demo")
    baseline = resolve_control_baseline(repo, "004-demo")
    (repo / "specs" / "004-demo" / "spec.md").write_text("competing\n", encoding="utf-8")
    _git(repo, "add", "specs/004-demo/spec.md")
    _git(repo, "commit", "-m", "competing change")
    competing_commit = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "main")

    with pytest.raises(SpecAmendmentConflict, match="advanced"):
        promote_amendment(repo, baseline, baseline.commit)

    assert _git(repo, "rev-parse", "004-demo") == competing_commit


def test_prepare_amendment_snapshots_input_in_isolated_worktree(tmp_path: Path) -> None:
    from echelon.spec_amendment import prepare_amendment

    repo = _repo(tmp_path)
    _write_spec(repo, "004-demo")
    _git(repo, "switch", "-c", "004-demo")
    _git(repo, "switch", "main")
    _git(repo, "switch", "-c", "006-other-work")
    source = repo / "sources" / "PBS-E-73.md"
    source.parent.mkdir(parents=True)
    source.write_text("New product requirement\n", encoding="utf-8")

    result = prepare_amendment(
        repo,
        [
            "004-demo",
            "Add product evidence",
            "--input",
            "requirement:sources/PBS-E-73.md",
        ],
    )

    assert _git(repo, "branch", "--show-current") == "006-other-work"
    assert result.amendment_id == "004-demo/001"
    amendment_dir = result.worktree.path / "specs" / "004-demo" / "amendments" / "001"
    assert (amendment_dir / "inputs" / "manifest.json").is_file()
    assert (amendment_dir / "change-request.md").is_file()
    assert (amendment_dir / "impact.md").is_file()
    assert "New input declarations: 1" in (amendment_dir / "impact.md").read_text(
        encoding="utf-8"
    )
    assert not (repo / "specs" / "004-demo" / "amendments").exists()
    assert result.state_path.is_file()


def test_prepare_amendment_dry_run_creates_no_worktree_or_runtime_state(tmp_path: Path) -> None:
    from echelon.spec_amendment import prepare_amendment

    repo = _repo(tmp_path)
    _write_spec(repo, "004-demo")
    _git(repo, "switch", "-c", "006-other-work")

    result = prepare_amendment(repo, ["004-demo", "Preview", "--dry-run"])

    assert result.dry_run is True
    assert result.worktree is None
    assert not (repo / ".echelon" / "runtime" / "amend-worktrees").exists()
    assert not (repo / ".git" / "echelon" / "amendments").exists()


def test_prepare_amendment_pins_target_default_branch_in_detached_worktree(tmp_path: Path) -> None:
    from echelon.spec_amendment import prepare_amendment

    repo = _repo(tmp_path)
    _write_spec(repo, "004-demo")
    _git(repo, "switch", "-c", "004-demo")
    target = repo / "sources" / "target"
    target.mkdir(parents=True)
    _git(target, "init", "-b", "main")
    _git(target, "config", "user.name", "Test User")
    _git(target, "config", "user.email", "test@example.com")
    (target / "source.txt").write_text("base\n", encoding="utf-8")
    _git(target, "add", "source.txt")
    _git(target, "commit", "-m", "initial")
    target_commit = _git(target, "rev-parse", "HEAD")
    targets = repo / "specs" / "004-demo" / "targets.yml"
    targets.write_text(
        "schema_version: 1\n"
        "targets:\n"
        "- id: target\n"
        "  path: sources/target\n"
        "  branch: 004-demo\n",
        encoding="utf-8",
    )
    _git(repo, "add", "specs/004-demo/targets.yml")
    _git(repo, "commit", "-m", "add target")
    _git(repo, "switch", "main")
    _git(repo, "switch", "-c", "006-other-work")

    result = prepare_amendment(repo, ["004-demo", "Add requirement evidence"])

    assert len(result.target_snapshots) == 1
    snapshot = result.target_snapshots[0]
    assert snapshot.branch == "main"
    assert snapshot.commit == target_commit
    assert _git(snapshot.path, "rev-parse", "HEAD") == target_commit
    assert _git(target, "branch", "--show-current") == "main"


def test_prepare_amendment_cleans_already_created_target_snapshots_on_failure(
    tmp_path: Path,
) -> None:
    from echelon.spec_amendment import SpecAmendmentError, prepare_amendment

    repo = _repo(tmp_path)
    _write_spec(repo, "004-demo")
    _git(repo, "switch", "-c", "004-demo")
    target = repo / "sources" / "target-good"
    target.mkdir(parents=True)
    _git(target, "init", "-b", "main")
    _git(target, "config", "user.name", "Test User")
    _git(target, "config", "user.email", "test@example.com")
    (target / "source.txt").write_text("base\n", encoding="utf-8")
    _git(target, "add", "source.txt")
    _git(target, "commit", "-m", "initial")
    (repo / "specs" / "004-demo" / "targets.yml").write_text(
        "schema_version: 1\n"
        "targets:\n"
        "- id: good\n"
        "  path: sources/target-good\n"
        "- id: missing\n"
        "  path: sources/target-missing\n",
        encoding="utf-8",
    )
    _git(repo, "add", "specs/004-demo/targets.yml")
    _git(repo, "commit", "-m", "add targets")

    with pytest.raises(SpecAmendmentError, match="target repository does not exist"):
        prepare_amendment(repo, ["004-demo", "Add product evidence"])

    leaked_path = (
        repo
        / ".echelon"
        / "runtime"
        / "amend-worktrees"
        / "004-demo"
        / "001"
        / "sources"
        / "target-good"
    )
    assert str(leaked_path) not in _git(target, "worktree", "list", "--porcelain")
    assert "amend/004-demo/001" not in _git(repo, "branch", "--format=%(refname:short)")


def test_latest_amendment_state_can_be_loaded_and_abandoned(tmp_path: Path) -> None:
    from echelon.spec_amendment import (
        abandon_amendment,
        load_amendment_state,
        prepare_amendment,
    )

    repo = _repo(tmp_path)
    _write_spec(repo, "004-demo")
    result = prepare_amendment(repo, ["004-demo", "Add product evidence"])

    loaded = load_amendment_state(repo, "004-demo")
    abandoned = abandon_amendment(repo, result.amendment_id)

    assert loaded["amendment_id"] == result.amendment_id
    assert loaded["status"] == "prepared"
    assert abandoned["status"] == "abandoned"
    assert load_amendment_state(repo, result.amendment_id)["status"] == "abandoned"
