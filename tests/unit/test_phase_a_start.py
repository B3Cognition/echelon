"""Real-Git tests for Echelon-owned fresh Phase A starts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from echelon.phase_a_start import (
    PhaseAStartError,
    start_phase_a_spec,
    start_retarget_phase_a_spec,
)
from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRun, resolve_active_spec_run
from harness.human_input import HumanInputPolicyRegistry


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Echelon Tests")
    _git(repo, "config", "user.email", "echelon@example.test")
    (repo / ".gitignore").write_text(
        "/.echelon/runtime/\n/runs/.current\n/runs/*/state.json\n"
        "/runs/*/specs/*/.echelon/checkpoints.json\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "README.md")
    _git(repo, "commit", "-m", "base")
    return repo


def _checkpoint_active_run(repo: Path) -> str:
    base = _git(repo, "rev-parse", "main^{commit}")
    _git(repo, "switch", "-c", "001-spec-a", base)
    run_dir = repo / "runs" / "run-a"
    spec_dir = run_dir / "specs" / "001-spec-a"
    spec_dir.mkdir(parents=True)
    (repo / "specs" / "001-spec-a").mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec A\n", encoding="utf-8")
    _git(repo, "add", str((spec_dir / "spec.md").relative_to(repo)))
    _git(repo, "commit", "-m", "checkpoint A")
    checkpoint = _git(repo, "rev-parse", "HEAD^{commit}")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "runtime-a",
                "spec_id": "001-spec-a",
                "feature_branch": "001-spec-a",
                "spec_dir": "runs/run-a/specs/001-spec-a",
                "published_spec_dir": "specs/001-spec-a",
                "spec_number": "001",
                "phase_a_default_branch": "main",
                "phase_a_base_commit": base,
                "implementation_targets": ["services/legacy"],
            }
        ),
        encoding="utf-8",
    )
    ledger = spec_dir / ".echelon" / "checkpoints.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        json.dumps(
            {
                "spec_id": "001-spec-a",
                "checkpoints": [
                    {
                        "id": "phase-a",
                        "spec_id": "001-spec-a",
                        "phase": "phase-a",
                        "next_phase": "phase-next",
                        "commit": checkpoint,
                        "metadata_commit": "",
                        "source": "auto",
                        "run_id": "runtime-a",
                        "created_at": "2026-07-17T12:00:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (repo / "runs" / ".current").write_text("run-a\n", encoding="utf-8")
    return base


def _retarget_state(
    repo: Path,
    baseline: SpecRun,
    replacement_run_id: str,
    replacement_targets: tuple[str, ...],
    operation_id: object,
    *,
    revision_id: object = "retarget-test-revision",
) -> dict[str, object]:
    baseline_state = json.loads((baseline.run_dir / "state.json").read_text(encoding="utf-8"))
    return {
        "operation_id": operation_id,
        "revision_id": revision_id,
        "status": "checkpointed",
        "baseline_run_id": baseline.run_id,
        "replacement_run_id": replacement_run_id,
        "old_targets": baseline_state.get("implementation_targets", []),
        "replacement_targets": list(replacement_targets),
        "checkpoint_id": "retarget-preflight",
        "checkpoint_commit": _git(repo, "rev-parse", "HEAD^{commit}"),
        "failure_code": None,
    }


def _tree_snapshot(root: Path) -> tuple[tuple[object, ...], ...]:
    rows: list[tuple[object, ...]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        if path.is_symlink():
            rows.append((relative, "symlink", metadata.st_mode, path.readlink().as_posix()))
        elif path.is_dir():
            rows.append((relative, "directory", metadata.st_mode))
        else:
            rows.append((relative, "file", metadata.st_mode, path.read_bytes()))
    return tuple(rows)


def _retarget_arguments(
    repo: Path,
    baseline: SpecRun,
    *,
    replacement_run_id: str,
    operation_id: str,
    replacement_targets: tuple[str, ...] = ("apps/web",),
) -> dict[str, object]:
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "user_message": "Original",
            "autonomy_mode": "semi",
            "ignore_re": False,
            "requested_re_sources": [],
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    checkpoint = _git(repo, "rev-parse", "HEAD^{commit}")
    return {
        "replacement_run_id": replacement_run_id,
        "baseline": baseline,
        "checkpoint_commit": checkpoint,
        "replacement_targets": replacement_targets,
        "retarget_state": _retarget_state(
            repo,
            baseline,
            replacement_run_id,
            replacement_targets,
            operation_id,
        ),
    }


def test_first_spec_starts_on_sibling_branch_and_selects_discoverable_run(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "main^{commit}")

    outcome = start_phase_a_spec(repo, "run-b", "Build audit logging")

    assert outcome.bootstrap.spec_id == "001-build-audit-logging"
    assert _git(repo, "branch", "--show-current") == outcome.bootstrap.feature_branch
    assert _git(repo, "rev-parse", "HEAD^{commit}") == base
    assert (repo / "runs" / ".current").read_text().strip() == "run-b"
    state = json.loads((outcome.run_dir / "state.json").read_text())
    assert state["status"] == "preparing"
    assert state["run_id"] == "run-b"
    assert state["feature_branch"] == outcome.bootstrap.feature_branch
    assert (repo / state["spec_dir"]).is_dir()


def test_first_spec_refuses_unmanaged_nondefault_checkout(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "switch", "-c", "unmanaged-work")

    with pytest.raises(PhaseAStartError, match="requires the configured default branch"):
        start_phase_a_spec(repo, "run-b", "Build audit logging")

    assert _git(repo, "branch", "--show-current") == "unmanaged-work"
    assert not (repo / "runs" / ".current").exists()


def test_next_spec_ignores_prior_status_but_requires_checkpoint_and_uses_main(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    base = _checkpoint_active_run(repo)

    outcome = start_phase_a_spec(repo, "run-b", "Build search dashboard")

    assert outcome.source_checkpoint is not None
    assert outcome.source_checkpoint.checkpoint_id == "phase-a"
    assert outcome.bootstrap.spec_id == "002-build-search-dashboard"
    assert _git(repo, "branch", "--show-current") == "002-build-search-dashboard"
    assert _git(repo, "rev-parse", "HEAD^{commit}") == base
    assert (repo / "runs" / ".current").read_text().strip() == "run-b"


def test_next_spec_refuses_dirty_outgoing_run_by_default(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(PhaseAStartError, match="dirty worktree"):
        start_phase_a_spec(repo, "run-b", "Build search dashboard")

    assert _git(repo, "branch", "--show-current") == "001-spec-a"
    assert (repo / "runs" / ".current").read_text().strip() == "run-a"
    assert not (repo / "runs" / "run-b").exists()


def test_next_spec_refuses_to_switch_checkout_while_phase_a_is_executing(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)

    with PhaseAExecutionLock.acquire(repo, "active-controller"):
        with pytest.raises(PhaseAStartError, match="active-controller"):
            start_phase_a_spec(repo, "run-b", "Build search dashboard")

    assert _git(repo, "branch", "--show-current") == "001-spec-a"
    assert (repo / "runs" / ".current").read_text().strip() == "run-a"
    assert not (repo / "runs" / "run-b").exists()


def test_next_spec_can_stash_dirty_outgoing_run(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")

    outcome = start_phase_a_spec(
        repo,
        "run-b",
        "Build search dashboard",
        dirty_action="stash",
    )

    assert outcome.stash_commit
    assert _git(repo, "status", "--short") == ""
    source_state = json.loads((repo / "runs" / "run-a" / "state.json").read_text())
    assert source_state["phase_a_stash"]["commit"] == outcome.stash_commit


def test_next_spec_requires_a_checkpoint_even_when_prior_status_is_nonfinal(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    ledger = repo / "runs" / "run-a" / "specs" / "001-spec-a" / ".echelon" / "checkpoints.json"
    ledger.unlink()

    with pytest.raises(PhaseAStartError, match="checkpoint"):
        start_phase_a_spec(repo, "run-b", "Build search dashboard")

    assert _git(repo, "branch", "--show-current") == "001-spec-a"
    assert (repo / "runs" / ".current").read_text().strip() == "run-a"


def test_next_spec_can_discard_dirty_changes_only_with_confirmation(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(PhaseAStartError, match="explicit confirmation"):
        start_phase_a_spec(
            repo,
            "run-b",
            "Build search dashboard",
            dirty_action="discard",
        )

    outcome = start_phase_a_spec(
        repo,
        "run-b",
        "Build search dashboard",
        dirty_action="discard",
        confirm_discard=True,
    )

    assert outcome.bootstrap.spec_id == "002-build-search-dashboard"
    assert (repo / "README.md").read_text(encoding="utf-8") == "base\n"


def test_controller_preserves_prepared_git_identity_without_provider(tmp_path: Path) -> None:
    from harness.squad import SquadController
    from harness.squad_state import SquadStateStore

    class TerminalGraph:
        def entry_phase(self) -> str:
            return "DONE"

        def all_phase_ids(self) -> set[str]:
            return {"DONE"}

        def human_input_policy_registry(self) -> HumanInputPolicyRegistry:
            return HumanInputPolicyRegistry(())

    repo = _repo(tmp_path)
    outcome = start_phase_a_spec(repo, "run-b", "Build audit logging")
    store = SquadStateStore(outcome.run_dir)
    controller = SquadController(
        provider=object(),
        state_store=store,
        phase_graph=TerminalGraph(),
        ext_dir=repo / "missing-extension",
        project_root=repo,
        squad_dir=outcome.run_dir,
    )

    result = controller.run(user_message="Build audit logging")

    state = store.load()
    assert result.status == "blocked"
    assert state["run_id"] == "run-b"
    assert state["spec_id"] == outcome.bootstrap.spec_id
    assert state["feature_branch"] == outcome.bootstrap.feature_branch
    assert state["phase_a_base_commit"] == outcome.bootstrap.default_commit


def test_retarget_bootstrap_keeps_spec_and_branch_but_creates_new_run(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    baseline_state_path = baseline.run_dir / "state.json"
    baseline_state = json.loads(baseline_state_path.read_text(encoding="utf-8"))
    baseline_state.update(
        {
            "user_message": "Build the original API feature",
            "autonomy_mode": "autonomous",
            "implementation_targets": ["services/legacy"],
            "published_re_context": {
                "status": "attached",
                "selected_sources": ["api", "legacy"],
                "selection_reason": {
                    "api": "explicit --re-source",
                    "legacy": "target matched published source path",
                },
            },
        }
    )
    baseline_state_path.write_text(json.dumps(baseline_state), encoding="utf-8")
    checkpoint_commit = _git(repo, "rev-parse", "HEAD^{commit}")
    before_branches = set(_git(repo, "branch", "--format=%(refname:short)").splitlines())

    outcome = start_retarget_phase_a_spec(
        repo,
        replacement_run_id="squad-retarget-1",
        baseline=baseline,
        checkpoint_commit=checkpoint_commit,
        replacement_targets=("apps/web", "services/api"),
        retarget_state={
            "operation_id": "rt-bootstrap-1",
            "revision_id": "retarget-1",
            "status": "checkpointed",
            "baseline_run_id": baseline.run_id,
            "replacement_run_id": "squad-retarget-1",
            "old_targets": ["services/legacy"],
            "replacement_targets": ["apps/web", "services/api"],
            "checkpoint_id": "retarget-preflight",
            "checkpoint_commit": checkpoint_commit,
            "failure_code": None,
        },
    )

    state = json.loads((outcome.run_dir / "state.json").read_text(encoding="utf-8"))
    assert outcome.run.spec_id == baseline.spec_id
    assert outcome.run.feature_branch == baseline.feature_branch
    assert set(_git(repo, "branch", "--format=%(refname:short)").splitlines()) == before_branches
    assert (repo / "runs" / ".current").read_text(encoding="utf-8").strip() == "squad-retarget-1"
    assert state["implementation_targets"] == ["apps/web", "services/api"]
    assert state["retarget"]["baseline_run_id"] == baseline.run_id
    assert state["retarget"]["status"] == "checkpointed"
    assert state["phase"] == "phase0-constitution"
    assert state["user_message"] == "Build the original API feature"
    assert state["autonomy_mode"] == "autonomous"
    assert state["ignore_re"] is False
    assert state["requested_re_sources"] == ["api"]


def test_retarget_bootstrap_clones_baseline_product_input_bytes(tmp_path: Path) -> None:
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    input_source = repo / "requirements.md"
    input_source.write_text("Original immutable request\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        repo,
        baseline.run_dir,
        [parse_input_declaration("requirement:requirements.md")],
    )
    baseline_state_path = baseline.run_dir / "state.json"
    baseline_state = json.loads(baseline_state_path.read_text(encoding="utf-8"))
    baseline_state.update(
        {
            "user_message": "Build the original request",
            "autonomy_mode": "semi",
            "implementation_targets": ["services/legacy"],
            "product_inputs": resolution.state_payload(repo),
            "ignore_re": False,
            "requested_re_sources": [],
        }
    )
    baseline_state_path.write_text(json.dumps(baseline_state), encoding="utf-8")
    baseline_bytes = {
        path.relative_to(resolution.inputs_dir).as_posix(): path.read_bytes()
        for path in resolution.inputs_dir.rglob("*")
        if path.is_file()
    }

    outcome = start_retarget_phase_a_spec(
        repo,
        replacement_run_id="squad-retarget-inputs",
        baseline=baseline,
        checkpoint_commit=_git(repo, "rev-parse", "HEAD^{commit}"),
        replacement_targets=("apps/web",),
        retarget_state=_retarget_state(
            repo,
            baseline,
            "squad-retarget-inputs",
            ("apps/web",),
            "rt-bootstrap-inputs",
        ),
    )

    state = json.loads((outcome.run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["product_inputs"]["inputs_dir"] == "runs/squad-retarget-inputs/inputs"
    assert {
        path.relative_to(outcome.run_dir / "inputs").as_posix(): path.read_bytes()
        for path in (outcome.run_dir / "inputs").rglob("*")
        if path.is_file()
    } == baseline_bytes
    assert {
        path.relative_to(resolution.inputs_dir).as_posix(): path.read_bytes()
        for path in resolution.inputs_dir.rglob("*")
        if path.is_file()
    } == baseline_bytes


def test_retarget_bootstrap_retry_rejects_tampered_product_input_pointer(
    tmp_path: Path,
) -> None:
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    source = repo / "requirements.md"
    source.write_text("Original immutable request\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        repo,
        baseline.run_dir,
        [parse_input_declaration("requirement:requirements.md")],
    )
    baseline_state_path = baseline.run_dir / "state.json"
    baseline_state = json.loads(baseline_state_path.read_text(encoding="utf-8"))
    baseline_state.update(
        {
            "user_message": "Build the original request",
            "autonomy_mode": "semi",
            "product_inputs": resolution.state_payload(repo),
            "ignore_re": False,
            "requested_re_sources": [],
        }
    )
    baseline_state_path.write_text(json.dumps(baseline_state), encoding="utf-8")
    arguments = {
        "replacement_run_id": "squad-retarget-tampered-inputs",
        "baseline": baseline,
        "checkpoint_commit": _git(repo, "rev-parse", "HEAD^{commit}"),
        "replacement_targets": ("apps/web",),
        "retarget_state": _retarget_state(
            repo,
            baseline,
            "squad-retarget-tampered-inputs",
            ("apps/web",),
            "rt-bootstrap-tampered-inputs",
        ),
    }
    outcome = start_retarget_phase_a_spec(repo, **arguments)
    replacement_state_path = outcome.run_dir / "state.json"
    replacement_state = json.loads(replacement_state_path.read_text(encoding="utf-8"))
    replacement_state["product_inputs"]["manifest"] = (
        "runs/run-a/inputs/manifest.json"
    )
    replacement_state_path.write_text(json.dumps(replacement_state), encoding="utf-8")

    with pytest.raises(PhaseAStartError, match="prepared state postimage"):
        start_retarget_phase_a_spec(repo, **arguments)


def test_retarget_bootstrap_retry_returns_already_selected_operation(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "user_message": "Original",
            "autonomy_mode": "semi",
            "ignore_re": False,
            "requested_re_sources": [],
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    arguments = {
        "replacement_run_id": "squad-retarget-retry",
        "baseline": baseline,
        "checkpoint_commit": _git(repo, "rev-parse", "HEAD^{commit}"),
        "replacement_targets": ("apps/web",),
        "retarget_state": _retarget_state(
            repo,
            baseline,
            "squad-retarget-retry",
            ("apps/web",),
            "rt-bootstrap-retry",
        ),
    }

    first = start_retarget_phase_a_spec(repo, **arguments)
    second = start_retarget_phase_a_spec(repo, **arguments)

    assert second.run == first.run
    assert second.baseline == baseline
    assert (repo / "runs" / ".current").read_text(encoding="utf-8").strip() == (
        "squad-retarget-retry"
    )


def test_retarget_bootstrap_retry_rejects_tampered_original_intent(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "user_message": "Original",
            "autonomy_mode": "semi",
            "ignore_re": False,
            "requested_re_sources": [],
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    arguments = {
        "replacement_run_id": "squad-retarget-tampered-intent",
        "baseline": baseline,
        "checkpoint_commit": _git(repo, "rev-parse", "HEAD^{commit}"),
        "replacement_targets": ("apps/web",),
        "retarget_state": _retarget_state(
            repo,
            baseline,
            "squad-retarget-tampered-intent",
            ("apps/web",),
            "rt-bootstrap-tampered-intent",
        ),
    }
    outcome = start_retarget_phase_a_spec(repo, **arguments)
    replacement_state_path = outcome.run_dir / "state.json"
    replacement_state = json.loads(replacement_state_path.read_text(encoding="utf-8"))
    replacement_state["user_message"] = "Tampered"
    replacement_state_path.write_text(json.dumps(replacement_state), encoding="utf-8")

    with pytest.raises(PhaseAStartError, match="prepared state postimage"):
        start_retarget_phase_a_spec(repo, **arguments)


def test_retarget_bootstrap_retry_completes_matching_interrupted_switch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.phase_a_start as phase_a_start

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "user_message": "Original",
            "autonomy_mode": "semi",
            "ignore_re": False,
            "requested_re_sources": [],
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    arguments = {
        "replacement_run_id": "squad-retarget-interrupted",
        "baseline": baseline,
        "checkpoint_commit": _git(repo, "rev-parse", "HEAD^{commit}"),
        "replacement_targets": ("apps/web",),
        "retarget_state": _retarget_state(
            repo,
            baseline,
            "squad-retarget-interrupted",
            ("apps/web",),
            "rt-bootstrap-interrupted",
        ),
    }
    original_mark = phase_a_start.mark_spec_switch_checked_out

    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected switch interruption")

    monkeypatch.setattr(phase_a_start, "mark_spec_switch_checked_out", interrupt)
    with pytest.raises(RuntimeError, match="injected switch interruption"):
        start_retarget_phase_a_spec(repo, **arguments)
    assert (repo / "runs" / ".current").read_text(encoding="utf-8").strip() == "run-a"

    monkeypatch.setattr(phase_a_start, "mark_spec_switch_checked_out", original_mark)
    outcome = start_retarget_phase_a_spec(repo, **arguments)

    assert outcome.run.run_dir_name == "squad-retarget-interrupted"
    assert (repo / "runs" / ".current").read_text(encoding="utf-8").strip() == (
        "squad-retarget-interrupted"
    )


def test_retarget_bootstrap_rejects_missing_original_intent_before_mutation(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)

    with pytest.raises(PhaseAStartError, match="original user message"):
        start_retarget_phase_a_spec(
            repo,
            replacement_run_id="squad-retarget-missing-intent",
            baseline=baseline,
            checkpoint_commit=_git(repo, "rev-parse", "HEAD^{commit}"),
            replacement_targets=("apps/web",),
            retarget_state=_retarget_state(
                repo,
                baseline,
                "squad-retarget-missing-intent",
                ("apps/web",),
                "rt-bootstrap-missing-intent",
            ),
        )

    assert not (repo / "runs" / "squad-retarget-missing-intent").exists()
    assert (repo / "runs" / ".current").read_text(encoding="utf-8").strip() == "run-a"


def test_retarget_bootstrap_rejects_unknown_original_re_policy(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update({"user_message": "Original", "autonomy_mode": "semi"})
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(PhaseAStartError, match="original reverse-engineering policy"):
        start_retarget_phase_a_spec(
            repo,
            replacement_run_id="squad-retarget-missing-re-policy",
            baseline=baseline,
            checkpoint_commit=_git(repo, "rev-parse", "HEAD^{commit}"),
            replacement_targets=("apps/web",),
            retarget_state=_retarget_state(
                repo,
                baseline,
                "squad-retarget-missing-re-policy",
                ("apps/web",),
                "rt-bootstrap-missing-re-policy",
            ),
        )

    assert not (repo / "runs" / "squad-retarget-missing-re-policy").exists()


@pytest.mark.parametrize(
    "malformed_update",
    [
        {"ignore_re": "false", "requested_re_sources": []},
        {"ignore_re": False, "requested_re_sources": [1]},
    ],
)
def test_retarget_bootstrap_rejects_malformed_original_re_policy(
    tmp_path: Path,
    malformed_update: dict[str, object],
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "user_message": "Original",
            "autonomy_mode": "semi",
            "published_re_context": {
                "status": "attached",
                "selected_sources": [],
                "selection_reason": {},
            },
            **malformed_update,
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(PhaseAStartError, match="reverse-engineering"):
        start_retarget_phase_a_spec(
            repo,
            replacement_run_id="squad-retarget-malformed-re-policy",
            baseline=baseline,
            checkpoint_commit=_git(repo, "rev-parse", "HEAD^{commit}"),
            replacement_targets=("apps/web",),
            retarget_state=_retarget_state(
                repo,
                baseline,
                "squad-retarget-malformed-re-policy",
                ("apps/web",),
                "rt-bootstrap-malformed-re-policy",
            ),
        )


@pytest.mark.parametrize(
    "published_context",
    [
        {"status": "absent", "selected_sources": [], "selection_reason": {}},
        {"status": "attached", "selected_sources": ["api"], "selection_reason": {}},
    ],
)
def test_retarget_bootstrap_rejects_incomplete_legacy_re_context(
    tmp_path: Path,
    published_context: dict[str, object],
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "user_message": "Original",
            "autonomy_mode": "semi",
            "ignore_re": False,
            "published_re_context": published_context,
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(PhaseAStartError, match="published RE context"):
        start_retarget_phase_a_spec(
            repo,
            replacement_run_id="squad-retarget-incomplete-re",
            baseline=baseline,
            checkpoint_commit=_git(repo, "rev-parse", "HEAD^{commit}"),
            replacement_targets=("apps/web",),
            retarget_state=_retarget_state(
                repo,
                baseline,
                "squad-retarget-incomplete-re",
                ("apps/web",),
                "rt-incomplete-re",
            ),
        )


def test_retarget_bootstrap_preserves_ignore_and_deduplicates_requested_sources(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "user_message": "Original",
            "autonomy_mode": "semi",
            "ignore_re": False,
            "requested_re_sources": ["web", "api", "web"],
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    outcome = start_retarget_phase_a_spec(
        repo,
        replacement_run_id="squad-retarget-re-order",
        baseline=baseline,
        checkpoint_commit=_git(repo, "rev-parse", "HEAD^{commit}"),
        replacement_targets=("apps/web",),
        retarget_state=_retarget_state(
            repo,
            baseline,
            "squad-retarget-re-order",
            ("apps/web",),
            "rt-re-order",
        ),
    )

    replacement = json.loads((outcome.run_dir / "state.json").read_text(encoding="utf-8"))
    assert replacement["requested_re_sources"] == ["web", "api"]

    ignored_root = tmp_path / "ignored"
    ignored_root.mkdir()
    ignored_repo = _repo(ignored_root)
    _checkpoint_active_run(ignored_repo)
    ignored_baseline = resolve_active_spec_run(ignored_repo)
    ignored_state_path = ignored_baseline.run_dir / "state.json"
    ignored_state = json.loads(ignored_state_path.read_text(encoding="utf-8"))
    ignored_state.update(
        {
            "user_message": "Original",
            "autonomy_mode": "semi",
            "ignore_re": True,
            "published_re_context": {"status": "absent"},
        }
    )
    ignored_state_path.write_text(json.dumps(ignored_state), encoding="utf-8")
    ignored_outcome = start_retarget_phase_a_spec(
        ignored_repo,
        replacement_run_id="squad-retarget-re-ignored",
        baseline=ignored_baseline,
        checkpoint_commit=_git(ignored_repo, "rev-parse", "HEAD^{commit}"),
        replacement_targets=("apps/web",),
        retarget_state=_retarget_state(
            ignored_repo,
            ignored_baseline,
            "squad-retarget-re-ignored",
            ("apps/web",),
            "rt-re-ignored",
        ),
    )
    ignored_replacement = json.loads(
        (ignored_outcome.run_dir / "state.json").read_text(encoding="utf-8")
    )
    assert ignored_replacement["ignore_re"] is True
    assert ignored_replacement["requested_re_sources"] == []


@pytest.mark.parametrize("drift_kind", ["branch", "head"])
def test_retarget_bootstrap_fails_closed_when_git_drifts_before_pointer_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift_kind: str,
) -> None:
    import echelon.phase_a_start as phase_a_start

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "user_message": "Original",
            "autonomy_mode": "semi",
            "ignore_re": False,
            "requested_re_sources": [],
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    if drift_kind == "branch":
        _git(repo, "branch", "drifted-branch", "HEAD")
    original_mark = phase_a_start.mark_spec_switch_checked_out

    def mark_then_drift(*args: object, **kwargs: object):
        result = original_mark(*args, **kwargs)
        if drift_kind == "branch":
            _git(repo, "switch", "drifted-branch")
        else:
            _git(repo, "commit", "--allow-empty", "-m", "drifted head")
        return result

    monkeypatch.setattr(phase_a_start, "mark_spec_switch_checked_out", mark_then_drift)

    with pytest.raises(PhaseAStartError, match="Git position drifted"):
        start_retarget_phase_a_spec(
            repo,
            replacement_run_id=f"squad-retarget-drift-{drift_kind}",
            baseline=baseline,
            checkpoint_commit=_git(repo, "rev-parse", "HEAD^{commit}"),
            replacement_targets=("apps/web",),
            retarget_state=_retarget_state(
                repo,
                baseline,
                f"squad-retarget-drift-{drift_kind}",
                ("apps/web",),
                f"rt-bootstrap-drift-{drift_kind}",
            ),
        )

    assert (repo / "runs" / ".current").read_text(encoding="utf-8").strip() == "run-a"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operation_id", "wrong-operation"),
        ("source_run", "wrong-source"),
        ("target_run", "run-a"),
        ("source_branch", "wrong-branch"),
        ("target_branch", "wrong-branch"),
    ],
)
def test_retarget_retry_rejects_stale_intent_identity(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update({"user_message": "Original", "autonomy_mode": "semi", "ignore_re": False, "requested_re_sources": []})
    state_path.write_text(json.dumps(state), encoding="utf-8")
    arguments = {
        "replacement_run_id": "squad-retarget-stale-intent",
        "baseline": baseline,
        "checkpoint_commit": _git(repo, "rev-parse", "HEAD^{commit}"),
        "replacement_targets": ("apps/web",),
        "retarget_state": _retarget_state(
            repo,
            baseline,
            "squad-retarget-stale-intent",
            ("apps/web",),
            "rt-stale-intent",
        ),
    }
    start_retarget_phase_a_spec(repo, **arguments)
    intent = {
        "operation_id": "rt-stale-intent",
        "source_run": "run-a",
        "target_run": "squad-retarget-stale-intent",
        "source_branch": baseline.feature_branch,
        "target_branch": baseline.feature_branch,
        "stage": "checked_out",
        "created_at": "2026-08-04T12:00:00+00:00",
    }
    intent[field] = value
    intent_path = repo / ".echelon/runtime/spec-switch-intent.json"
    intent_path.parent.mkdir(parents=True, exist_ok=True)
    intent_path.write_text(json.dumps(intent), encoding="utf-8")

    with pytest.raises(PhaseAStartError, match="intent identity"):
        start_retarget_phase_a_spec(repo, **arguments)

    assert json.loads(intent_path.read_text(encoding="utf-8"))[field] == value
    assert (repo / "runs/.current").read_text().strip() == "squad-retarget-stale-intent"


@pytest.mark.parametrize("stage", ["prepared", "completed"])
def test_retarget_retry_rejects_wrong_intent_stage(
    tmp_path: Path,
    stage: str,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "user_message": "Original",
            "autonomy_mode": "semi",
            "ignore_re": False,
            "requested_re_sources": [],
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    arguments = {
        "replacement_run_id": "squad-retarget-stale-stage",
        "baseline": baseline,
        "checkpoint_commit": _git(repo, "rev-parse", "HEAD^{commit}"),
        "replacement_targets": ("apps/web",),
        "retarget_state": _retarget_state(
            repo,
            baseline,
            "squad-retarget-stale-stage",
            ("apps/web",),
            "rt-stale-stage",
        ),
    }
    start_retarget_phase_a_spec(repo, **arguments)
    intent_path = repo / ".echelon/runtime/spec-switch-intent.json"
    intent_path.parent.mkdir(parents=True, exist_ok=True)
    intent_path.write_text(
        json.dumps(
            {
                "operation_id": "rt-stale-stage",
                "source_run": "run-a",
                "target_run": "squad-retarget-stale-stage",
                "source_branch": baseline.feature_branch,
                "target_branch": baseline.feature_branch,
                "stage": stage,
                "created_at": "2026-08-04T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PhaseAStartError, match="intent stage"):
        start_retarget_phase_a_spec(repo, **arguments)

    assert (repo / "runs/.current").read_text().strip() == "squad-retarget-stale-stage"
    assert intent_path.exists()


@pytest.mark.parametrize(
    "crash_point",
    ["before_install", "after_install", "after_begin", "checked_out"],
)
def test_retarget_bootstrap_baseexception_crash_retries_complete_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_point: str,
) -> None:
    import echelon.phase_a_start as phase_a_start

    class InjectedCrash(BaseException):
        pass

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update({"user_message": "Original", "autonomy_mode": "semi", "ignore_re": False, "requested_re_sources": []})
    state_path.write_text(json.dumps(state), encoding="utf-8")
    arguments = {
        "replacement_run_id": f"squad-retarget-crash-{crash_point}",
        "baseline": baseline,
        "checkpoint_commit": _git(repo, "rev-parse", "HEAD^{commit}"),
        "replacement_targets": ("apps/web",),
        "retarget_state": _retarget_state(
            repo,
            baseline,
            f"squad-retarget-crash-{crash_point}",
            ("apps/web",),
            f"rt-crash-{crash_point}",
        ),
    }
    if crash_point == "before_install":
        original = phase_a_start._write_retarget_prepared_state
        patched_name = "_write_retarget_prepared_state"

        def crash(*args: object, **kwargs: object) -> None:
            raise InjectedCrash()

    elif crash_point == "after_install":
        original = phase_a_start.begin_spec_switch
        patched_name = "begin_spec_switch"

        def crash(*args: object, **kwargs: object) -> None:
            raise InjectedCrash()

    elif crash_point == "after_begin":
        original = phase_a_start.mark_spec_switch_checked_out
        patched_name = "mark_spec_switch_checked_out"

        def crash(*args: object, **kwargs: object) -> None:
            raise InjectedCrash()

    else:
        original = phase_a_start.commit_spec_switch_pointer
        patched_name = "commit_spec_switch_pointer"

        def crash(*args: object, **kwargs: object) -> None:
            raise InjectedCrash()

    monkeypatch.setattr(phase_a_start, patched_name, crash)
    with pytest.raises(InjectedCrash):
        start_retarget_phase_a_spec(repo, **arguments)
    unrelated = repo / "runs/.retarget-bootstrap-unrelated"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("unrelated", encoding="utf-8")
    monkeypatch.setattr(phase_a_start, patched_name, original)

    outcome = start_retarget_phase_a_spec(repo, **arguments)
    assert outcome.run.run_dir_name == arguments["replacement_run_id"]
    assert (repo / "runs/.current").read_text().strip() == arguments["replacement_run_id"]
    assert (unrelated / "keep.txt").read_text(encoding="utf-8") == "unrelated"
    assert not list((repo / "runs").glob(f".retarget-bootstrap-*{arguments['replacement_run_id']}"))


def test_retarget_retry_rejects_empty_product_input_substitution(tmp_path: Path) -> None:
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    source = repo / "requirements.md"
    source.write_text("Original immutable request\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        repo,
        baseline.run_dir,
        [parse_input_declaration("requirement:requirements.md")],
    )
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "user_message": "Original",
            "autonomy_mode": "semi",
            "ignore_re": False,
            "requested_re_sources": [],
            "product_inputs": resolution.state_payload(repo),
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    arguments = {
        "replacement_run_id": "squad-retarget-empty-inputs",
        "baseline": baseline,
        "checkpoint_commit": _git(repo, "rev-parse", "HEAD^{commit}"),
        "replacement_targets": ("apps/web",),
        "retarget_state": _retarget_state(
            repo,
            baseline,
            "squad-retarget-empty-inputs",
            ("apps/web",),
            "rt-empty-inputs",
        ),
    }
    outcome = start_retarget_phase_a_spec(repo, **arguments)
    replacement_state_path = outcome.run_dir / "state.json"
    replacement_state = json.loads(replacement_state_path.read_text(encoding="utf-8"))
    replacement_state["product_inputs"] = {}
    replacement_state_path.write_text(json.dumps(replacement_state), encoding="utf-8")

    with pytest.raises(PhaseAStartError, match="prepared state postimage"):
        start_retarget_phase_a_spec(repo, **arguments)


@pytest.mark.parametrize("lifecycle", ["interrupted", "completed"])
@pytest.mark.parametrize(
    "tamper",
    [
        "spec-delete",
        "spec-file",
        "spec-symlink",
        "staging-delete",
        "staging-file",
        "staging-symlink",
    ],
)
def test_retarget_retry_requires_exact_real_prepared_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lifecycle: str,
    tamper: str,
) -> None:
    import echelon.phase_a_start as phase_a_start

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id=f"squad-structure-{lifecycle}-{tamper}",
        operation_id=f"rt-structure-{lifecycle}-{tamper}",
    )
    original_mark = phase_a_start.mark_spec_switch_checked_out
    if lifecycle == "interrupted":
        monkeypatch.setattr(
            phase_a_start,
            "mark_spec_switch_checked_out",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("interrupt")),
        )
        with pytest.raises(RuntimeError, match="interrupt"):
            start_retarget_phase_a_spec(repo, **arguments)
        monkeypatch.setattr(phase_a_start, "mark_spec_switch_checked_out", original_mark)
    else:
        start_retarget_phase_a_spec(repo, **arguments)

    run_dir = repo / "runs" / str(arguments["replacement_run_id"])
    target = (
        run_dir / "specs" / baseline.spec_id
        if tamper.startswith("spec-")
        else run_dir / "staging"
    )
    shutil.rmtree(target)
    if tamper.endswith("file"):
        target.write_text("not a directory", encoding="utf-8")
    elif tamper.endswith("symlink"):
        target.symlink_to(baseline.spec_dir, target_is_directory=True)

    pointer = (repo / "runs/.current").read_bytes()
    intent_path = repo / ".echelon/runtime/spec-switch-intent.json"
    intent = intent_path.read_bytes() if intent_path.exists() else None
    with pytest.raises(PhaseAStartError, match="prepared run structure"):
        start_retarget_phase_a_spec(repo, **arguments)

    assert (repo / "runs/.current").read_bytes() == pointer
    assert (intent_path.read_bytes() if intent_path.exists() else None) == intent


@pytest.mark.parametrize("lifecycle", ["interrupted", "completed"])
@pytest.mark.parametrize("tamper", ["delete", "file", "symlink"])
def test_retarget_retry_requires_exact_real_product_input_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lifecycle: str,
    tamper: str,
) -> None:
    import echelon.phase_a_start as phase_a_start
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    source = repo / "requirements.md"
    source.write_text("Immutable request\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        repo,
        baseline.run_dir,
        [parse_input_declaration("requirement:requirements.md")],
    )
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id=f"squad-input-structure-{lifecycle}-{tamper}",
        operation_id=f"rt-input-structure-{lifecycle}-{tamper}",
    )
    baseline_state_path = baseline.run_dir / "state.json"
    baseline_state = json.loads(baseline_state_path.read_text(encoding="utf-8"))
    baseline_state["product_inputs"] = resolution.state_payload(repo)
    baseline_state_path.write_text(json.dumps(baseline_state), encoding="utf-8")
    original_mark = phase_a_start.mark_spec_switch_checked_out
    if lifecycle == "interrupted":
        monkeypatch.setattr(
            phase_a_start,
            "mark_spec_switch_checked_out",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("interrupt")),
        )
        with pytest.raises(RuntimeError, match="interrupt"):
            start_retarget_phase_a_spec(repo, **arguments)
        monkeypatch.setattr(phase_a_start, "mark_spec_switch_checked_out", original_mark)
    else:
        start_retarget_phase_a_spec(repo, **arguments)

    run_dir = repo / "runs" / str(arguments["replacement_run_id"])
    inputs = run_dir / "inputs"
    shutil.rmtree(inputs)
    if tamper == "file":
        inputs.write_text("not a directory", encoding="utf-8")
    elif tamper == "symlink":
        inputs.symlink_to(resolution.inputs_dir, target_is_directory=True)
    pointer = (repo / "runs/.current").read_bytes()
    intent_path = repo / ".echelon/runtime/spec-switch-intent.json"
    intent = intent_path.read_bytes() if intent_path.exists() else None

    with pytest.raises(PhaseAStartError, match="prepared run structure"):
        start_retarget_phase_a_spec(repo, **arguments)

    assert (repo / "runs/.current").read_bytes() == pointer
    assert (intent_path.read_bytes() if intent_path.exists() else None) == intent


@pytest.mark.parametrize("lifecycle", ["interrupted", "completed"])
@pytest.mark.parametrize(
    "tamper",
    [
        "phase_a_base_commit",
        "completed_phases",
        "missing_spec_number",
        "extra_state_key",
        "retarget_revision",
        "retarget_status",
        "retarget_extra_key",
        "spec_dir_binding",
    ],
)
def test_retarget_retry_requires_exact_prepared_state_postimage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lifecycle: str,
    tamper: str,
) -> None:
    import echelon.phase_a_start as phase_a_start

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id=f"squad-state-{lifecycle}-{tamper}",
        operation_id=f"rt-state-{lifecycle}-{tamper}",
    )
    original_mark = phase_a_start.mark_spec_switch_checked_out
    if lifecycle == "interrupted":
        monkeypatch.setattr(
            phase_a_start,
            "mark_spec_switch_checked_out",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("interrupt")),
        )
        with pytest.raises(RuntimeError, match="interrupt"):
            start_retarget_phase_a_spec(repo, **arguments)
        monkeypatch.setattr(phase_a_start, "mark_spec_switch_checked_out", original_mark)
    else:
        start_retarget_phase_a_spec(repo, **arguments)

    state_path = repo / "runs" / str(arguments["replacement_run_id"]) / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if tamper == "phase_a_base_commit":
        state["phase_a_base_commit"] = "f" * 40
    elif tamper == "completed_phases":
        state["completed_phases"] = ["phase0-constitution"]
    elif tamper == "missing_spec_number":
        state.pop("spec_number")
    elif tamper == "extra_state_key":
        state["unexpected"] = True
    elif tamper == "retarget_revision":
        state["retarget"]["revision_id"] = "retarget-other"
    elif tamper == "retarget_status":
        state["retarget"]["status"] = "rebuilding"
    elif tamper == "spec_dir_binding":
        state["spec_dir"] = "runs/run-a/specs/001-spec-a"
    else:
        state["retarget"]["unexpected"] = True
    state_path.write_text(json.dumps(state), encoding="utf-8")

    pointer = (repo / "runs/.current").read_bytes()
    intent_path = repo / ".echelon/runtime/spec-switch-intent.json"
    intent = intent_path.read_bytes() if intent_path.exists() else None
    with pytest.raises(PhaseAStartError, match="prepared state postimage"):
        start_retarget_phase_a_spec(repo, **arguments)

    assert (repo / "runs/.current").read_bytes() == pointer
    assert (intent_path.read_bytes() if intent_path.exists() else None) == intent


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_top", "duplicate_nested", "bool_for_integer"],
)
def test_retarget_retry_uses_strict_type_exact_prepared_state_json(
    tmp_path: Path,
    mutation: str,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id=f"squad-strict-state-{mutation}",
        operation_id=f"rt-strict-state-{mutation}",
    )
    start_retarget_phase_a_spec(repo, **arguments)
    state_path = repo / "runs" / str(arguments["replacement_run_id"]) / "state.json"
    raw = state_path.read_text(encoding="utf-8")
    if mutation == "duplicate_top":
        run_id = arguments["replacement_run_id"]
        raw = raw.replace(
            f'"run_id": "{run_id}",',
            f'"run_id": "{run_id}",\n  "run_id": "{run_id}",',
            1,
        )
    elif mutation == "duplicate_nested":
        raw = raw.replace(
            '"status": "checkpointed",',
            '"status": "checkpointed",\n    "status": "checkpointed",',
            1,
        )
    else:
        raw = raw.replace('"ignore_re": false,', '"ignore_re": 0,', 1)
    state_path.write_text(raw, encoding="utf-8")
    before = _tree_snapshot(repo / "runs")

    with pytest.raises(PhaseAStartError):
        start_retarget_phase_a_spec(repo, **arguments)

    assert _tree_snapshot(repo / "runs") == before


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_top", "duplicate_nested", "bool_for_integer"],
)
def test_retarget_retry_uses_strict_type_exact_reservation_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    import echelon.phase_a_start as phase_a_start

    class InjectedCrash(BaseException):
        pass

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id=f"squad-strict-sidecar-{mutation}",
        operation_id=f"rt-strict-sidecar-{mutation}",
    )
    original_create = phase_a_start._create_retarget_staging_directory
    monkeypatch.setattr(
        phase_a_start,
        "_create_retarget_staging_directory",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(InjectedCrash()),
    )
    with pytest.raises(InjectedCrash):
        start_retarget_phase_a_spec(repo, **arguments)
    monkeypatch.setattr(
        phase_a_start,
        "_create_retarget_staging_directory",
        original_create,
    )
    reservation_path = next((repo / "runs").glob(".retarget-bootstrap-*.json"))
    raw = reservation_path.read_text(encoding="utf-8")
    if mutation == "duplicate_top":
        raw = raw.replace(
            '"schema_version": 1,',
            '"schema_version": 1, "schema_version": 1,',
            1,
        )
    elif mutation == "duplicate_nested":
        operation_id = arguments["retarget_state"]["operation_id"]
        raw = raw.replace(
            f'"operation_id": "{operation_id}",',
            f'"operation_id": "{operation_id}", "operation_id": "{operation_id}",',
            1,
        )
    else:
        raw = raw.replace('"schema_version": 1,', '"schema_version": true,', 1)
    reservation_path.write_text(raw, encoding="utf-8")
    before = _tree_snapshot(repo / "runs")

    with pytest.raises(PhaseAStartError):
        start_retarget_phase_a_spec(repo, **arguments)

    assert _tree_snapshot(repo / "runs") == before


@pytest.mark.parametrize(
    "mutation",
    [
        "integer_operation",
        "missing_revision",
        "wrong_baseline",
        "wrong_replacement",
        "wrong_targets",
        "extra_contract_key",
    ],
)
def test_retarget_rejects_malformed_contract_before_runs_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id=f"squad-invalid-{mutation}",
        operation_id=f"rt-invalid-{mutation}",
    )
    contract = arguments["retarget_state"]
    assert isinstance(contract, dict)
    if mutation == "integer_operation":
        contract["operation_id"] = 7
    elif mutation == "missing_revision":
        contract.pop("revision_id")
    elif mutation == "wrong_baseline":
        contract["baseline_run_id"] = "wrong-baseline"
    elif mutation == "wrong_replacement":
        contract["replacement_run_id"] = "wrong-replacement"
    elif mutation == "wrong_targets":
        contract["replacement_targets"] = ["services/other"]
    else:
        contract["unexpected"] = True
    before = _tree_snapshot(repo / "runs")

    with pytest.raises(PhaseAStartError, match="retarget contract"):
        start_retarget_phase_a_spec(repo, **arguments)

    assert _tree_snapshot(repo / "runs") == before


@pytest.mark.parametrize("tamper", ["bytes", "hardlink"])
def test_retarget_authenticates_baseline_inputs_before_runs_mutation(
    tmp_path: Path,
    tamper: str,
) -> None:
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    source = repo / "requirements.md"
    source.write_text("Immutable request\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        repo,
        baseline.run_dir,
        [parse_input_declaration("requirement:requirements.md")],
    )
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id=f"squad-invalid-input-{tamper}",
        operation_id=f"rt-invalid-input-{tamper}",
    )
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["product_inputs"] = resolution.state_payload(repo)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    if tamper == "bytes":
        (resolution.inputs_dir / "catalog.json").write_text("tampered", encoding="utf-8")
    else:
        os.link(
            resolution.inputs_dir / "manifest.json",
            resolution.inputs_dir / "untrusted-hardlink.json",
        )
    before = _tree_snapshot(repo / "runs")

    with pytest.raises(PhaseAStartError):
        start_retarget_phase_a_spec(repo, **arguments)

    assert _tree_snapshot(repo / "runs") == before


@pytest.mark.parametrize("mutation", ["missing_hash", "invalid_hash", "unindexed_bytes"])
def test_retarget_requires_persisted_baseline_input_tree_preimage_before_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    source = repo / "requirements.md"
    source.write_text("Persisted preimage\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        repo,
        baseline.run_dir,
        [parse_input_declaration("requirement:requirements.md")],
    )
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id=f"squad-invalid-preimage-{mutation}",
        operation_id=f"rt-invalid-preimage-{mutation}",
    )
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    product_inputs = resolution.state_payload(repo)
    if mutation == "missing_hash":
        product_inputs.pop("tree_hash")
    elif mutation == "invalid_hash":
        product_inputs["tree_hash"] = "sha256:not-a-digest"
    else:
        (resolution.inputs_dir / "unindexed.txt").write_text(
            "not represented by the persisted preimage\n",
            encoding="utf-8",
        )
    state["product_inputs"] = product_inputs
    state_path.write_text(json.dumps(state), encoding="utf-8")
    before = _tree_snapshot(repo / "runs")

    with pytest.raises(PhaseAStartError, match="tree hash"):
        start_retarget_phase_a_spec(repo, **arguments)

    assert _tree_snapshot(repo / "runs") == before


@pytest.mark.parametrize(
    ("replacement_run_id", "replacement_targets"),
    [
        (7, ("apps/web",)),
        ("squad-invalid-args", ["apps/web"]),
        ("squad-invalid-args", ("apps//web",)),
    ],
)
def test_retarget_rejects_noncanonical_arguments_before_runs_mutation(
    tmp_path: Path,
    replacement_run_id: object,
    replacement_targets: object,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    before = _tree_snapshot(repo / "runs")

    with pytest.raises(PhaseAStartError):
        start_retarget_phase_a_spec(
            repo,
            replacement_run_id=replacement_run_id,
            baseline=baseline,
            checkpoint_commit=_git(repo, "rev-parse", "HEAD^{commit}"),
            replacement_targets=replacement_targets,
            retarget_state={},
        )

    assert _tree_snapshot(repo / "runs") == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("spec_number", "999"),
        ("phase_a_base_commit", "main"),
    ],
)
def test_retarget_rejects_noncanonical_baseline_bindings_before_runs_mutation(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state[field] = value
    state_path.write_text(json.dumps(state), encoding="utf-8")
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id=f"squad-invalid-{field}",
        operation_id=f"rt-invalid-{field}",
    )
    before = _tree_snapshot(repo / "runs")

    with pytest.raises(PhaseAStartError, match=field):
        start_retarget_phase_a_spec(repo, **arguments)

    assert _tree_snapshot(repo / "runs") == before


@pytest.mark.parametrize(
    "binding",
    [
        "alternate_spec_dir",
        "missing_spec_dir",
        "symlink_spec_dir",
        "alternate_published_dir",
        "missing_published_dir",
        "symlink_published_dir",
    ],
)
def test_retarget_requires_exact_canonical_baseline_artifact_paths_before_mutation(
    tmp_path: Path,
    binding: str,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    state_path = repo / "runs/run-a/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if binding in {"alternate_spec_dir", "missing_spec_dir", "symlink_spec_dir"}:
        if binding == "alternate_spec_dir":
            target = repo / "runs/run-a/alternate/001-spec-a"
            target.mkdir(parents=True)
            state["spec_dir"] = target.relative_to(repo).as_posix()
        elif binding == "missing_spec_dir":
            state["spec_dir"] = "runs/run-a/missing/001-spec-a"
        else:
            alias = repo / "runs/run-a/spec-alias"
            alias.symlink_to(repo / "runs/run-a/specs/001-spec-a", target_is_directory=True)
            state["spec_dir"] = alias.relative_to(repo).as_posix()
    else:
        if binding == "alternate_published_dir":
            target = repo / "published/001-spec-a"
            target.mkdir(parents=True)
            state["published_spec_dir"] = target.relative_to(repo).as_posix()
        elif binding == "missing_published_dir":
            state["published_spec_dir"] = "specs/missing-001-spec-a"
        else:
            alias = repo / "published-spec-alias"
            alias.symlink_to(repo / "specs/001-spec-a", target_is_directory=True)
            state["published_spec_dir"] = alias.relative_to(repo).as_posix()
    state_path.write_text(json.dumps(state), encoding="utf-8")
    baseline = resolve_active_spec_run(repo)
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id=f"squad-invalid-binding-{binding}",
        operation_id=f"rt-invalid-binding-{binding}",
    )
    before = _tree_snapshot(repo / "runs")

    with pytest.raises(PhaseAStartError, match="canonical baseline"):
        start_retarget_phase_a_spec(repo, **arguments)

    assert _tree_snapshot(repo / "runs") == before


def test_retarget_rejects_symlink_aliased_baseline_run_before_mutation(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    source = repo / "runs/run-a"
    hidden_source = repo / "runs/.source-run-a"
    source.rename(hidden_source)
    source.symlink_to(hidden_source, target_is_directory=True)
    (repo / "runs/.current").write_text("run-a\n", encoding="utf-8")
    baseline = resolve_active_spec_run(repo)
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id="squad-invalid-run-alias",
        operation_id="rt-invalid-run-alias",
    )
    before = _tree_snapshot(repo / "runs")

    with pytest.raises(PhaseAStartError, match="canonical baseline"):
        start_retarget_phase_a_spec(repo, **arguments)

    assert _tree_snapshot(repo / "runs") == before


@pytest.mark.parametrize("spec_number", ["001-spec", "002", "0" * 300])
def test_retarget_requires_exact_numeric_spec_prefix_before_runs_mutation(
    tmp_path: Path,
    spec_number: str,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    state_path = baseline.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["spec_number"] = spec_number
    state_path.write_text(json.dumps(state), encoding="utf-8")
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id="squad-invalid-spec-prefix",
        operation_id="rt-invalid-spec-prefix",
    )
    before = _tree_snapshot(repo / "runs")

    with pytest.raises(PhaseAStartError, match="spec_number"):
        start_retarget_phase_a_spec(repo, **arguments)

    assert _tree_snapshot(repo / "runs") == before


@pytest.mark.parametrize("collision_kind", ["directory", "file", "symlink"])
def test_retarget_whole_run_install_never_overwrites_racing_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    collision_kind: str,
) -> None:
    import echelon.atomic_install as atomic_install

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    replacement = f"squad-run-race-{collision_kind}"
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id=replacement,
        operation_id=f"rt-run-race-{collision_kind}",
    )
    destination = repo / "runs" / replacement
    original_install = atomic_install.atomic_rename_no_replace

    def race(source: Path, target: Path) -> None:
        if target != destination:
            original_install(source, target)
            return
        if collision_kind == "directory":
            target.mkdir()
            (target / "keep.txt").write_text("directory", encoding="utf-8")
        elif collision_kind == "file":
            target.write_text("file", encoding="utf-8")
        else:
            symlink_target = repo / "outside-run-target"
            symlink_target.write_text("target", encoding="utf-8")
            target.symlink_to(symlink_target)
        original_install(source, target)

    monkeypatch.setattr(atomic_install, "atomic_rename_no_replace", race)
    with pytest.raises((PhaseAStartError, OSError)):
        start_retarget_phase_a_spec(repo, **arguments)

    if collision_kind == "directory":
        assert (destination / "keep.txt").read_text(encoding="utf-8") == "directory"
    elif collision_kind == "file":
        assert destination.read_text(encoding="utf-8") == "file"
    else:
        assert destination.is_symlink()
        assert destination.readlink() == repo / "outside-run-target"
    assert (repo / "runs/.current").read_text().strip() == "run-a"


@pytest.mark.parametrize(
    ("boundary", "patched_name"),
    [
        ("before_directory", "_create_retarget_staging_directory"),
        ("before_marker", "_write_retarget_staging_marker"),
        ("during_population", "_write_retarget_prepared_state"),
        ("after_install", "begin_spec_switch"),
    ],
)
def test_retarget_reservation_recovers_every_staging_crash_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    patched_name: str,
) -> None:
    import echelon.phase_a_start as phase_a_start

    class InjectedCrash(BaseException):
        pass

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id=f"squad-reservation-{boundary}",
        operation_id=f"rt-reservation-{boundary}",
    )
    unrelated = repo / "runs/.retarget-run-unproven"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("unrelated", encoding="utf-8")
    sentinel = object()
    original = getattr(phase_a_start, patched_name, sentinel)

    def crash(*_args: object, **_kwargs: object) -> None:
        raise InjectedCrash()

    monkeypatch.setattr(phase_a_start, patched_name, crash, raising=False)
    with pytest.raises(InjectedCrash):
        start_retarget_phase_a_spec(repo, **arguments)

    reservations = list((repo / "runs").glob(".retarget-bootstrap-*.json"))
    assert len(reservations) == 1
    assert reservations[0].is_file() and not reservations[0].is_symlink()
    reservation = json.loads(reservations[0].read_text(encoding="utf-8"))
    assert reservation == {
        "schema_version": 1,
        "owner": {
            "operation_id": arguments["retarget_state"]["operation_id"],
            "source_run": baseline.run_dir_name,
            "target_run": arguments["replacement_run_id"],
            "spec_id": baseline.spec_id,
        },
        "staging_name": reservation["staging_name"],
    }
    if original is sentinel:
        monkeypatch.delattr(phase_a_start, patched_name)
    else:
        monkeypatch.setattr(phase_a_start, patched_name, original)

    outcome = start_retarget_phase_a_spec(repo, **arguments)
    assert outcome.run.run_dir_name == arguments["replacement_run_id"]
    assert not list((repo / "runs").glob(".retarget-bootstrap-*.json"))
    assert (unrelated / "keep.txt").read_text(encoding="utf-8") == "unrelated"


def test_retarget_retry_preserves_staging_without_ownership_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.phase_a_start as phase_a_start

    class InjectedCrash(BaseException):
        pass

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id="squad-unproven-staging",
        operation_id="rt-unproven-staging",
    )
    original_marker = phase_a_start._write_retarget_staging_marker
    monkeypatch.setattr(
        phase_a_start,
        "_write_retarget_staging_marker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(InjectedCrash()),
    )
    with pytest.raises(InjectedCrash):
        start_retarget_phase_a_spec(repo, **arguments)
    reservation_path = next((repo / "runs").glob(".retarget-bootstrap-*.json"))
    reservation = json.loads(reservation_path.read_text(encoding="utf-8"))
    abandoned = repo / "runs" / reservation["staging_name"]
    assert abandoned.is_dir()
    reservation_path.unlink()
    monkeypatch.setattr(
        phase_a_start,
        "_write_retarget_staging_marker",
        original_marker,
    )

    start_retarget_phase_a_spec(repo, **arguments)

    assert abandoned.is_dir()


@pytest.mark.parametrize("installed_mutation", ["missing_state", "tampered_state"])
def test_retarget_retains_installed_ownership_evidence_until_postimage_validates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    installed_mutation: str,
) -> None:
    import echelon.phase_a_start as phase_a_start

    class InjectedCrash(BaseException):
        pass

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id="squad-retained-installed-evidence",
        operation_id="rt-retained-installed-evidence",
    )
    original_install = phase_a_start._install_prepared_retarget_run

    def install_then_tamper(*args: object, **kwargs: object) -> None:
        original_install(*args, **kwargs)
        run_dir = repo / "runs/squad-retained-installed-evidence"
        state_path = run_dir / "state.json"
        if installed_mutation == "missing_state":
            state_path.unlink()
        else:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["completed_phases"] = ["phase0-constitution"]
            state_path.write_text(json.dumps(state), encoding="utf-8")

    monkeypatch.setattr(
        phase_a_start,
        "_install_prepared_retarget_run",
        install_then_tamper,
    )
    with pytest.raises(PhaseAStartError, match="prepared"):
        start_retarget_phase_a_spec(repo, **arguments)
    monkeypatch.setattr(
        phase_a_start,
        "_install_prepared_retarget_run",
        original_install,
    )

    reservation_path = next((repo / "runs").glob(".retarget-bootstrap-*.json"))
    run_dir = repo / "runs/squad-retained-installed-evidence"
    marker_path = run_dir / ".echelon-retarget-bootstrap.json"
    assert marker_path.is_file() and not marker_path.is_symlink()
    assert json.loads(marker_path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "owner": {
            "operation_id": "rt-retained-installed-evidence",
            "source_run": baseline.run_dir_name,
            "target_run": "squad-retained-installed-evidence",
            "spec_id": baseline.spec_id,
        },
    }
    reservation_bytes = reservation_path.read_bytes()
    marker_bytes = marker_path.read_bytes()

    with pytest.raises(PhaseAStartError, match="prepared"):
        start_retarget_phase_a_spec(repo, **arguments)

    assert reservation_path.read_bytes() == reservation_bytes
    assert marker_path.read_bytes() == marker_bytes


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_top", "duplicate_nested", "bool_for_integer"],
)
def test_retarget_retry_uses_strict_type_exact_installed_marker_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    import echelon.phase_a_start as phase_a_start

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id=f"squad-strict-marker-{mutation}",
        operation_id=f"rt-strict-marker-{mutation}",
    )
    original_install = phase_a_start._install_prepared_retarget_run
    valid_state: bytes | None = None

    def install_then_tamper(*args: object, **kwargs: object) -> None:
        nonlocal valid_state
        original_install(*args, **kwargs)
        state_path = repo / "runs" / str(arguments["replacement_run_id"]) / "state.json"
        valid_state = state_path.read_bytes()
        state = json.loads(valid_state)
        state["completed_phases"] = ["phase0-constitution"]
        state_path.write_text(json.dumps(state), encoding="utf-8")

    monkeypatch.setattr(
        phase_a_start,
        "_install_prepared_retarget_run",
        install_then_tamper,
    )
    with pytest.raises(PhaseAStartError):
        start_retarget_phase_a_spec(repo, **arguments)
    monkeypatch.setattr(
        phase_a_start,
        "_install_prepared_retarget_run",
        original_install,
    )
    assert valid_state is not None
    run_dir = repo / "runs" / str(arguments["replacement_run_id"])
    (run_dir / "state.json").write_bytes(valid_state)
    marker_path = run_dir / ".echelon-retarget-bootstrap.json"
    raw = marker_path.read_text(encoding="utf-8")
    if mutation == "duplicate_top":
        raw = raw.replace(
            '"schema_version": 1,',
            '"schema_version": 1, "schema_version": 1,',
            1,
        )
    elif mutation == "duplicate_nested":
        operation_id = arguments["retarget_state"]["operation_id"]
        raw = raw.replace(
            f'"operation_id": "{operation_id}",',
            f'"operation_id": "{operation_id}", "operation_id": "{operation_id}",',
            1,
        )
    else:
        raw = raw.replace('"schema_version": 1,', '"schema_version": true,', 1)
    marker_path.write_text(raw, encoding="utf-8")
    reservation_path = next((repo / "runs").glob(".retarget-bootstrap-*.json"))
    marker_bytes = marker_path.read_bytes()
    reservation_bytes = reservation_path.read_bytes()

    with pytest.raises(PhaseAStartError):
        start_retarget_phase_a_spec(repo, **arguments)

    assert marker_path.read_bytes() == marker_bytes
    assert reservation_path.read_bytes() == reservation_bytes


def test_retarget_state_atomic_replace_fsyncs_parent_after_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.phase_a_start as phase_a_start

    destination = tmp_path / "owned/state.json"
    destination.parent.mkdir()
    events: list[tuple[str, Path]] = []
    original_replace = phase_a_start.os.replace

    def replace(source: Path, target: Path) -> None:
        original_replace(source, target)
        events.append(("replace", Path(target)))

    monkeypatch.setattr(phase_a_start.os, "replace", replace)
    monkeypatch.setattr(
        phase_a_start,
        "_sync_parent_directory",
        lambda path: events.append(("parent", Path(path))),
        raising=False,
    )

    phase_a_start._write_json_atomic(destination, {"ready": True})

    assert events == [("replace", destination), ("parent", destination.parent)]


def test_retarget_durably_syncs_complete_run_before_atomic_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.atomic_install as atomic_install
    import echelon.durable_tree as durable_tree

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id="squad-durable-run",
        operation_id="rt-durable-run",
    )
    destination = repo / "runs/squad-durable-run"
    events: list[tuple[str, Path]] = []
    original_sync = durable_tree.durably_sync_owned_tree
    original_install = atomic_install.atomic_rename_no_replace

    def sync(path: Path, **kwargs: object) -> None:
        events.append(("sync", path))
        original_sync(path, **kwargs)

    def install(source: Path, target: Path) -> None:
        events.append(("install", target))
        original_install(source, target)

    monkeypatch.setattr(durable_tree, "durably_sync_owned_tree", sync)
    monkeypatch.setattr(atomic_install, "atomic_rename_no_replace", install)

    start_retarget_phase_a_spec(repo, **arguments)

    install_index = events.index(("install", destination))
    assert events[install_index - 1][0] == "sync"


def test_retarget_durable_sync_failure_never_installs_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.atomic_install as atomic_install
    import echelon.durable_tree as durable_tree

    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id="squad-failed-durable-run",
        operation_id="rt-failed-durable-run",
    )
    destination = repo / "runs/squad-failed-durable-run"
    installed: list[Path] = []
    original_install = atomic_install.atomic_rename_no_replace

    def fail(_path: Path, **_kwargs: object) -> None:
        raise OSError("injected durable sync failure")

    def install(source: Path, target: Path) -> None:
        installed.append(target)
        original_install(source, target)

    monkeypatch.setattr(durable_tree, "durably_sync_owned_tree", fail)
    monkeypatch.setattr(atomic_install, "atomic_rename_no_replace", install)

    with pytest.raises(OSError, match="injected durable sync failure"):
        start_retarget_phase_a_spec(repo, **arguments)

    assert destination not in installed
    assert not destination.exists()


@pytest.mark.parametrize("directory", ["specs", "spec", "staging"])
def test_retarget_retry_rejects_noncanonical_owned_directory_mode(
    tmp_path: Path,
    directory: str,
) -> None:
    repo = _repo(tmp_path)
    _checkpoint_active_run(repo)
    baseline = resolve_active_spec_run(repo)
    arguments = _retarget_arguments(
        repo,
        baseline,
        replacement_run_id=f"squad-mode-{directory}",
        operation_id=f"rt-mode-{directory}",
    )
    start_retarget_phase_a_spec(repo, **arguments)
    run_dir = repo / "runs" / str(arguments["replacement_run_id"])
    paths = {
        "specs": run_dir / "specs",
        "spec": run_dir / "specs" / baseline.spec_id,
        "staging": run_dir / "staging",
    }
    paths[directory].chmod(0o777)
    before = _tree_snapshot(repo / "runs")

    with pytest.raises(PhaseAStartError, match="prepared run structure"):
        start_retarget_phase_a_spec(repo, **arguments)

    assert _tree_snapshot(repo / "runs") == before
