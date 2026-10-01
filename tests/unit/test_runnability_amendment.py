"""Published Spec runnability-owner amendment preview and preparation."""

from __future__ import annotations

from pathlib import Path
import json
import subprocess

import pytest

from echelon.runnability_amendment import (
    prepare_runnability_owner,
    preview_runnability_owner,
)
from harness.task_progress import checkpoint_input_hash


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "control"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / ".echelon").mkdir()
    (repo / ".echelon/config.yml").write_text(
        "stacks:\n  selected:\n    - browser-threejs-npm\n", encoding="utf-8",
    )
    (repo / ".gitignore").write_text("/.echelon/runtime/\n", encoding="utf-8")
    (repo / "apps/web").mkdir(parents=True)
    (repo / "apps/web/package.json").write_text('{"name":"web"}\n', encoding="utf-8")
    spec = repo / "specs/004-demo"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text("# Demo\n", encoding="utf-8")
    (spec / "targets.yml").write_text(
        "schema_version: 1\ntargets:\n- id: web\n  path: apps/web\n"
        "  role: primary\n  branch: 004-demo\n", encoding="utf-8",
    )
    (spec / "tasks.md").write_text(
        "# Tasks\n\n## Summary\n\n- Total tasks: 1\n\n## Phase: Release\n\n"
        "- [ ] T-001 complexity=standard phase=release req=INFRA depends=none target=apps/web\n"
        "  **Status:** PENDING\n\n  **Files:**\n  - `apps/web/package.json`\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".gitignore", ".echelon/config.yml", "apps/web/package.json", "specs/004-demo")
    _git(repo, "commit", "-m", "published spec")
    _git(repo, "switch", "-c", "004-demo")
    return repo


def test_preview_is_read_only_and_names_missing_owner(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    before_ref = _git(repo, "rev-parse", "refs/heads/004-demo")
    before_status = _git(repo, "status", "--porcelain", "--untracked-files=all")

    preview = preview_runnability_owner(repo, "004-demo")

    assert preview["new_task_ids"] == ["T-002"]
    assert preview["contract_paths"] == ["apps/web/.echelon/runnability.yml"]
    assert preview["pre_amendment_working_hash"] == checkpoint_input_hash(
        repo / "specs/004-demo"
    )
    assert _git(repo, "rev-parse", "refs/heads/004-demo") == before_ref
    assert _git(repo, "status", "--porcelain", "--untracked-files=all") == before_status
    assert not (repo / ".echelon/runtime/amend-worktrees/004-demo").exists()
    assert not (repo / ".git/echelon/amendments/004-demo").exists()


def test_prepare_commits_proposal_only_in_isolated_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    old_ref = _git(repo, "rev-parse", "refs/heads/004-demo")
    tasks = repo / "specs/004-demo/tasks.md"
    tasks.write_text(tasks.read_text().replace("- [ ] T-001", "- [x] T-001")
                     .replace("**Status:** PENDING", "**Status:** DONE"))
    working_before = tasks.read_bytes()

    prepared = prepare_runnability_owner(repo, "004-demo")

    assert prepared["amendment_id"] == "004-demo/001"
    isolated = Path(str(prepared["worktree_path"]))
    amended_tasks = (isolated / "specs/004-demo/tasks.md").read_text()
    assert "- [ ] T-002" in amended_tasks
    assert "- [ ] T-001" in amended_tasks
    assert "- Total tasks: 2" in amended_tasks
    assert _git(repo, "rev-parse", "refs/heads/004-demo") == old_ref
    assert tasks.read_bytes() == working_before
    assert _git(repo, "status", "--porcelain", "--untracked-files=all") == "M specs/004-demo/tasks.md"
    assert Path(str(prepared["state_path"])).is_file()
    assert _git(isolated, "show", "--format=", "--name-only", "HEAD") == "specs/004-demo/tasks.md"


def test_preview_refuses_missing_stack_selection(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / ".echelon/config.yml").write_text("stacks:\n  selected: []\n")

    with pytest.raises(ValueError, match="stack_selection_required"):
        preview_runnability_owner(repo, "004-demo")


def test_preview_binds_delivery_lifecycle_hash_without_confusing_published_hash(
    tmp_path: Path,
) -> None:
    from harness.spec_frontmatter import write_status

    repo = _repo(tmp_path)
    spec = repo / "specs/004-demo"
    (spec / "spec.md").write_text("# Demo\n\n**Status**: Planned\n")
    _git(repo, "add", "specs/004-demo/spec.md")
    _git(repo, "commit", "-m", "published status")
    write_status(spec, "in_progress")

    preview = preview_runnability_owner(repo, "004-demo")

    assert preview["published_input_hash"] != preview["pre_amendment_working_hash"]
    assert preview["pre_amendment_working_hash"] == checkpoint_input_hash(spec)


def test_preview_rejects_non_lifecycle_spec_edit(tmp_path: Path) -> None:
    from harness.spec_frontmatter import write_status

    repo = _repo(tmp_path)
    spec = repo / "specs/004-demo"
    write_status(spec, "in_progress")
    path = spec / "spec.md"
    path.write_text(path.read_text().replace("# Demo", "# Different requirement"))

    with pytest.raises(ValueError, match="unrecognized working spec lifecycle edit"):
        preview_runnability_owner(repo, "004-demo")


def test_preview_rejects_unsettled_spec_step(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    state = repo / "runs/spec-incomplete/state.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({
        "spec_id": "004-demo",
        "pending_spec_step": {"step_id": "phase3-plan"},
    }))

    with pytest.raises(ValueError, match="pending Spec step"):
        preview_runnability_owner(repo, "004-demo")


def test_clean_pending_delivery_operation_blocks_preview_and_prepare(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    state_path = repo / "runs/targets/web/runs/build-001/state/delivery.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "spec_id": "004-demo", "status": "interrupted",
        "delivery_slice_operation": {"operation_id": "sealed-001", "progress_applied": False},
    }), encoding="utf-8")
    before_ref = _git(repo, "rev-parse", "refs/heads/004-demo")
    before_file = (repo / "specs/004-demo/tasks.md").read_bytes()
    before_index = _git(repo, "rev-parse", ":specs/004-demo/tasks.md")

    with pytest.raises(ValueError, match="pending Delivery operation"):
        preview_runnability_owner(repo, "004-demo")
    with pytest.raises(ValueError, match="pending Delivery operation"):
        prepare_runnability_owner(repo, "004-demo")

    assert _git(repo, "rev-parse", "refs/heads/004-demo") == before_ref
    assert _git(repo, "rev-parse", ":specs/004-demo/tasks.md") == before_index
    assert (repo / "specs/004-demo/tasks.md").read_bytes() == before_file
    assert not (repo / ".git/echelon/amendments/004-demo").exists()


def test_preview_existing_owner_reports_noop_without_writes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    tasks = repo / "specs/004-demo/tasks.md"
    tasks.write_text(tasks.read_text().replace(
        "apps/web/package.json", "apps/web/.echelon/runnability.yml"
    ))
    _git(repo, "add", "specs/004-demo/tasks.md")
    _git(repo, "commit", "-m", "published runnability owner")
    before = _git(repo, "status", "--porcelain", "--untracked-files=all")

    preview = preview_runnability_owner(repo, "004-demo")

    assert preview["new_task_ids"] == []
    assert preview["status"] == "no_change"
    assert _git(repo, "status", "--porcelain", "--untracked-files=all") == before
    assert not (repo / ".git/echelon/amendments/004-demo").exists()


def test_preview_valid_owner_deferral_is_read_only_noop(tmp_path: Path) -> None:
    from harness.runnability_disposition import defer_runnability
    from harness.runnability_evidence import RunnabilityStage, write_runnability_report

    repo = _repo(tmp_path)
    spec = repo / "specs/004-demo"
    report = write_runnability_report(
        evidence_dir=repo / "runs/targets/web/runs/build-old/evidence/user-runnability",
        spec_id="004-demo", target_id="apps/web", build_id="build-old",
        candidate_commit="a" * 40, candidate_fingerprint="product-1",
        contract_hash="contract-1", stack_hash="stack-1",
        status="not_runnable", failure_class="primary_journey_failed",
        summary="Composed local journey needs an owner decision.",
        stages=(RunnabilityStage(name="primary_journey", status="failed", exit_code=1),),
        required_stages=("primary_journey",), attempt_sequence=1,
        sensitive_environment={}, user_commands={},
    )
    defer_runnability(
        spec_dir=spec, target="apps/web", reason="Explicitly deferred by owner",
        evidence_report=report.path.parent / "report.json",
    )
    before_status = _git(repo, "status", "--porcelain", "--untracked-files=all")
    before_ref = _git(repo, "rev-parse", "HEAD")

    preview = preview_runnability_owner(repo, "004-demo")

    assert preview["status"] == "no_change"
    assert preview["new_task_ids"] == []
    assert _git(repo, "rev-parse", "HEAD") == before_ref
    assert _git(repo, "status", "--porcelain", "--untracked-files=all") == before_status
    assert not (repo / ".git/echelon/amendments/004-demo").exists()


def test_prepare_failed_commit_removes_only_its_isolated_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.runnability_amendment as amendment

    repo = _repo(tmp_path)
    original_git = amendment._git

    def fail_commit(root: Path, *args: str) -> str:
        if args[:1] == ("commit",):
            raise amendment.RunnabilityAmendmentError("injected commit failure")
        return original_git(root, *args)

    monkeypatch.setattr(amendment, "_git", fail_commit)

    with pytest.raises(ValueError, match="injected commit failure"):
        prepare_runnability_owner(repo, "004-demo")

    assert not (repo / ".echelon/runtime/amend-worktrees/004-demo/001").exists()
    assert not (repo / ".git/echelon/amendments/004-demo/001/state.json").exists()
    assert not _git(repo, "branch", "--list", "amend/004-demo/001")
    assert _git(repo, "status", "--porcelain", "--untracked-files=all") == ""


def test_cli_dry_run_is_read_only_in_real_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typer.testing import CliRunner
    from echelon.cli_app import app

    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)
    before_ref = _git(repo, "rev-parse", "HEAD")
    before_status = _git(repo, "status", "--porcelain", "--untracked-files=all")

    result = CliRunner().invoke(app, [
        "spec", "amend", "004-demo", "Add runnability owner",
        "--runnability-owner", "--dry-run",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["new_task_ids"] == ["T-002"]
    assert _git(repo, "rev-parse", "HEAD") == before_ref
    assert _git(repo, "status", "--porcelain", "--untracked-files=all") == before_status
    assert not (repo / ".git/echelon/amendments/004-demo").exists()


def test_cli_rejects_product_input_on_typed_owner_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typer.testing import CliRunner
    from echelon.cli_app import app

    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    result = CliRunner().invoke(app, [
        "spec", "amend", "004-demo", "Add runnability owner",
        "--runnability-owner", "--input", "reference:notes.md",
    ])

    assert result.exit_code == 2
    assert "cannot be combined" in result.output
    assert not (repo / ".git/echelon/amendments/004-demo").exists()
