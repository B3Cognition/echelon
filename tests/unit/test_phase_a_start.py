"""Real-Git tests for Echelon-owned fresh Phase A starts."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from echelon.phase_a_start import (
    PhaseAStartError,
    start_phase_a_spec,
    start_retarget_phase_a_spec,
)
from echelon.spec_lifecycle import PhaseAExecutionLock, resolve_active_spec_run
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
            "baseline_run_id": baseline.run_id,
            "replacement_run_id": "squad-retarget-1",
            "old_targets": ["services/legacy"],
            "replacement_targets": ["apps/web", "services/api"],
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
        retarget_state={"operation_id": "rt-bootstrap-inputs"},
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
        "retarget_state": {"operation_id": "rt-bootstrap-tampered-inputs"},
    }
    outcome = start_retarget_phase_a_spec(repo, **arguments)
    replacement_state_path = outcome.run_dir / "state.json"
    replacement_state = json.loads(replacement_state_path.read_text(encoding="utf-8"))
    replacement_state["product_inputs"]["manifest"] = (
        "runs/run-a/inputs/manifest.json"
    )
    replacement_state_path.write_text(json.dumps(replacement_state), encoding="utf-8")

    with pytest.raises(PhaseAStartError, match="manifest pointer"):
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
        "retarget_state": {"operation_id": "rt-bootstrap-retry"},
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
        "retarget_state": {"operation_id": "rt-bootstrap-tampered-intent"},
    }
    outcome = start_retarget_phase_a_spec(repo, **arguments)
    replacement_state_path = outcome.run_dir / "state.json"
    replacement_state = json.loads(replacement_state_path.read_text(encoding="utf-8"))
    replacement_state["user_message"] = "Tampered"
    replacement_state_path.write_text(json.dumps(replacement_state), encoding="utf-8")

    with pytest.raises(PhaseAStartError, match="user_message"):
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
        "retarget_state": {"operation_id": "rt-bootstrap-interrupted"},
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
            retarget_state={"operation_id": "rt-bootstrap-missing-intent"},
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
            retarget_state={"operation_id": "rt-bootstrap-missing-re-policy"},
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
            retarget_state={"operation_id": "rt-bootstrap-malformed-re-policy"},
        )


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
            retarget_state={"operation_id": f"rt-bootstrap-drift-{drift_kind}"},
        )

    assert (repo / "runs" / ".current").read_text(encoding="utf-8").strip() == "run-a"
