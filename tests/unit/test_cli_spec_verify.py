from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from harness.config import HarnessConfig


@pytest.mark.unit
@pytest.mark.parametrize("git_workspace", [False, True])
def test_spec_verify_runs_authoritative_stack_evidence_before_fulfillment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git_workspace: bool
) -> None:
    workspace = tmp_path / "workspace"
    target = workspace / "sources" / "game"
    spec_dir = workspace / "specs" / "003-game"
    target.mkdir(parents=True)
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\ntargets:\n  - sources/game\n---\n# Game\n",
        encoding="utf-8",
    )
    if git_workspace:
        from echelon.git_helpers import run_git
        run_git(workspace, "init", "-b", "main")
        run_git(workspace, "config", "user.name", "Test")
        run_git(workspace, "config", "user.email", "test@example.test")
        run_git(workspace, "add", ".")
        run_git(workspace, "commit", "-m", "baseline")
    config = HarnessConfig(
        target_repo=str(target),
        target_default_branch="main",
        provider="docker",
    )
    resolved = SimpleNamespace(services=("postgres-service",), runnability="required")
    monkeypatch.chdir(workspace)
    monkeypatch.setattr("harness.config.load_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        "echelon.prosaic_packages.install_prosaic_bundle", lambda _root: None
    )
    monkeypatch.setattr(
        "harness.verification_stack_runtime.resolve_verification_stacks",
        lambda _workspace, _target: resolved,
    )
    provider = MagicMock()
    monkeypatch.setattr(
        "harness.docker_provider.DockerWorktreeProvider",
        MagicMock(return_value=provider),
    )
    verifier = MagicMock()
    verifier.run.return_value = SimpleNamespace(
        status="refreshed",
        exit_code=0,
        reason="full verify-spec completed",
        report_path=str(spec_dir / "fulfillment-report.md"),
        verified_ledger={"implemented": 1},
        verify_run_dir=workspace / "runs" / "verify-spec-003-game-test",
        failure_class="",
        ok=True,
    )
    verifier_type = MagicMock(return_value=verifier)
    if git_workspace:
        def write_outputs(**kwargs):
            for name in ("fulfillment-report.md", "fulfillment-gaps.md", "verified-fulfillment-ledger.json"):
                (spec_dir / name).write_text("{}\n")
            return verifier.run.return_value
        verifier.run.side_effect = write_outputs
    monkeypatch.setattr(
        "harness.authoritative_spec_verifier.AuthoritativeSpecVerifier",
        verifier_type,
    )

    from echelon.cli_app import app

    result = CliRunner().invoke(
        app, ["spec", "verify", "003-game", "--reconcile"]
    )

    assert result.exit_code == 0, result.output
    if git_workspace:
        assert run_git(workspace, "status", "--porcelain").stdout == ""
        assert "record verification evidence" in run_git(workspace, "log", "-1", "--format=%s").stdout
    assert "evidence: authoritative sandbox" in result.output
    assert config.verification_services == ["postgres-service"]
    assert config.resolved_stacks is resolved
    verifier.run.assert_called_once_with(reconcile=True, dry_run=False)
    assert verifier_type.call_args.kwargs["provider"] is provider
