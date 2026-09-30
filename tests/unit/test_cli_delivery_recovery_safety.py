"""CLI recovery delegates durable effects to the locked Delivery controller."""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from tests.unit.test_cli_harness_resume import (
    _make_echelon_yml,
    _make_phase_a_spec,
    _setup_build,
    _write_state,
)


UNKNOWN_REASON = "delivery_reconciliation_required: dispatch completion is unknown"


@pytest.mark.parametrize("reason,build_status", [
    ("harness_error", ""),
    ("build_incomplete", "phase_a_not_ready"),
    ("build_incomplete", ""),
    ("publish_failed", ""),
])
def test_cli_continue_forwards_overrides_without_applying_source_recovery(
    tmp_path, monkeypatch, reason, build_status,
):
    from echelon.cli_app import app

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    _make_echelon_yml(tmp_path, verify_command="pytest")
    _make_phase_a_spec(tmp_path)
    state_dir = _setup_build(tmp_path, "001")
    _write_state(state_dir, "001", "default", {
        "status": "blocked", "termination_reason": reason,
        "build_status": build_status, "spec_dir": "/missing/spec",
    })
    before = (state_dir / "delivery.json").read_bytes()
    with patch("harness.skills.run_skill.run") as run, \
         patch("harness.recovery.recover_blocked_run") as recover, \
         patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
         patch("harness.gitops.GitOpsManager.__init__", return_value=None):
        result = CliRunner().invoke(app, [
            "delivery", "continue", "001", "--mode", "banzai",
            "--token-budget", "5000000", "--max-outer", "12", "--no-auto-merge",
        ])

    assert result.exit_code == 0, result.output
    assert run.call_count == 1
    assert run.call_args.args[0] == (
        "spec 001 mode=banzai resume token_budget=5000000 max 12 outer iterations no_auto_merge"
    )
    assert run.call_args.kwargs["resume_build_id"] == "build-test"
    recover.assert_not_called()
    assert (state_dir / "delivery.json").read_bytes() == before


@pytest.mark.parametrize("state_updates", [{}, {
    "status": "blocked", "termination_reason": "build_incomplete",
    "build_status": "provider_session_limit", "blocked_phase": "implementation",
}])
def test_second_cli_caller_cannot_rewrite_live_owners_state(tmp_path, monkeypatch, state_updates):
    from echelon.delivery_service import _run_delivery_continue
    from harness.state import StateStore

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    _make_echelon_yml(tmp_path, verify_command="pytest")
    state_dir = _setup_build(tmp_path, "001")
    owner = StateStore(state_dir, "001")
    owner.initialize("live-run", "semi")
    owner.transition("running")
    state = owner.read()
    state.update(state_updates)
    state["spec_dir"] = "/stale/spec"
    owner.write(state)
    owner.acquire_lock("live-run")
    before = owner.state_file.read_bytes()

    def reject_second_owner(*args, **kwargs):
        StateStore(state_dir, "001").acquire_lock("second-run")

    try:
        with patch("harness.skills.run_skill.run", side_effect=reject_second_owner), \
             patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
             patch("harness.gitops.GitOpsManager.__init__", return_value=None):
            with pytest.raises(SystemExit) as exc:
                _run_delivery_continue(tmp_path, ["001"])
        assert exc.value.code == 1
        assert owner.state_file.read_bytes() == before
    finally:
        owner.release_lock()


@pytest.mark.parametrize("status,reason", [("blocked", "build_blocked"), ("blocked", "harness_error"), ("running", ""), ("interrupted", "user_cancel")])
def test_unknown_dispatch_authorization_is_typed_and_read_only_in_cli(tmp_path, monkeypatch, status, reason):
    from echelon.cli_app import app

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    _make_echelon_yml(tmp_path)
    _make_phase_a_spec(tmp_path)
    state_dir = _setup_build(tmp_path, "001")
    _write_state(state_dir, "001", "default", {
        "status": status, "termination_reason": reason,
        "blocked_phase": "implementation", "build_reason": UNKNOWN_REASON,
        "interrupted_phase": "implementation",
        "delivery_slice_operation": {"id": "pending", "progress_applied": False},
    })
    before = (state_dir / "delivery.json").read_bytes()
    with patch("harness.skills.run_skill.run") as run, \
         patch("harness.docker_provider.DockerWorktreeProvider.__init__", return_value=None), \
         patch("harness.gitops.GitOpsManager.__init__", return_value=None):
        result = CliRunner().invoke(app, [
            "delivery", "continue", "001", "--reconcile-unknown-dispatch",
        ])
    assert result.exit_code == 0, result.output
    assert run.call_args.kwargs["reconcile_unknown_dispatch"] is True
    assert (state_dir / "delivery.json").read_bytes() == before


@pytest.mark.parametrize("unknown_targets", [("api",), ("api", "web"), ()])
def test_multi_target_unknown_dispatch_requires_one_eligible_target(
    tmp_path, monkeypatch, unknown_targets,
):
    from echelon.delivery_service import _run_delivery_continue
    from harness.paths import build_dir, current_build_marker

    monkeypatch.chdir(tmp_path)
    spec = tmp_path / "specs" / "001-demo"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text("---\ntargets:\n  - sources/api\n  - sources/web\n---\n")
    for name in ("api", "web"):
        target = tmp_path / "sources" / name
        (target / ".git").mkdir(parents=True)
        base = tmp_path / "runs" / "targets" / name
        marker = current_build_marker(base, "001")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("build-test")
        _write_state(build_dir(base, "build-test") / "state", "001", "default", {
            "status": "blocked", "termination_reason": "build_blocked",
            "blocked_phase": "implementation",
            "build_reason": UNKNOWN_REASON if name in unknown_targets else "other_blocker",
            "delivery_slice_operation": {"id": "pending", "progress_applied": False} if name in unknown_targets else None,
        })
    with patch("echelon.delivery_service._block_if_spec_task_targets_mismatch"), \
         patch("echelon.orchestrator.run_multi_target", return_value=0) as dispatch:
        with pytest.raises(SystemExit) as exc:
            _run_delivery_continue(tmp_path, ["001", "--reconcile-unknown-dispatch"])
    if len(unknown_targets) == 1:
        assert exc.value.code == 0
        assert dispatch.call_args.args[1] == [tmp_path / "sources" / "api"]
    else:
        assert exc.value.code == 1
        dispatch.assert_not_called()
