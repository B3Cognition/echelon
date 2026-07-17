"""CLI tests for the delivery namespace and top-level help."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.config import HarnessConfig, LlmConfig


@pytest.mark.unit
def test_help_command_prints_usage_without_unknown_command(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "help"])

    main()

    captured = capsys.readouterr()
    assert "echelon: unknown command" not in captured.err
    assert "Echelon CLI" in captured.out
    assert "delivery" in captured.out
    assert "spec" in captured.out
    assert "workspace" in captured.out
    assert "phase" in captured.out
    assert "benchmark" in captured.out
    assert "stack" in captured.out


@pytest.mark.unit
def test_phase_help_does_not_require_installed_extension(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "phase", "--help"])

    main()

    captured = capsys.readouterr()
    assert "Echelon extension not installed" not in captured.err
    assert "phase [OPTIONS] COMMAND [ARGS]" in captured.out
    assert "Workflow phase inspection and manual replay commands." in captured.out
    assert "run" in captured.out


@pytest.mark.unit
def test_spec_help_lists_current_run_and_target_options(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "spec", "--help"])

    main()

    captured = capsys.readouterr()
    assert "run <description> [--mode semi|banzai|guided] [--reset]" in captured.out
    assert "[--target <source-id-or-path>]..." in captured.out
    assert "--re-policy" in captured.out
    assert "none|cached-only|changed|refresh-all" in captured.out
    assert "checkpoint list|accept|commit [--spec <id>] [--phase <phase-id>]" in captured.out
    assert "target <spec_id>" not in captured.out


@pytest.mark.unit
def test_top_level_checkpoint_is_not_a_compatibility_alias(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "checkpoint", "--help"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "No such command 'checkpoint'" in captured.err
    assert "echelon spec checkpoint list" not in captured.out


@pytest.mark.unit
def test_delivery_run_rejects_artifact_only_provider(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from echelon import cli

    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(
            cli="openai-compatible",
            base_url="http://127.0.0.1:8000/v1",
            model="local-model",
        ),
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.cli.load_config", lambda project_dir, squad_only=True: config)

    with pytest.raises(SystemExit) as exc:
        cli._cmd_harness_run(["001-demo"])

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert 'Provider "openai-compatible" supports artifact work only.' in captured.err
    assert 'Command "echelon delivery run" requires build capability.' in captured.err
    assert "Choose a build-capable provider." in captured.err


@pytest.mark.unit
def test_spec_checkpoint_list_routes_to_spec_checkpoint_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "spec", "checkpoint", "list", "--spec", "001"])

    with patch("echelon.checkpoint_cli.run_checkpoint_command") as mock_checkpoint:
        main()

    mock_checkpoint.assert_called_once()
    assert mock_checkpoint.call_args.args[0] == ["list", "--spec", "001"]


@pytest.mark.unit
def test_delivery_checkpoint_list_prints_harness_checkpoint_commits(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from echelon.cli import main

    state_dir = tmp_path / "runs" / "build-20260708-120000-000000" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "default.json").write_text(
        """
{
  "spec_id": "001-demo",
  "strategy_id": "default",
  "status": "blocked",
  "termination_reason": "build_incomplete",
  "checkpoint_commits": [
    {
      "commit": "abcdef1234567890",
      "phase": "build",
      "task_ids": ["T-001", "T-002"],
      "phase_group": "phase-1-foundation",
      "created_at": "2026-07-08T12:00:00Z"
    }
  ],
  "salvage_commit": "feedface12345678",
  "target_commit": "0123456789abcdef"
}
""",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "checkpoint", "list", "001-demo"])

    main()

    out = capsys.readouterr().out
    assert "CHECKPOINTS - delivery 001-demo" in out
    assert "abcdef1" in out
    assert "phase-1-foundation" in out
    assert "T-001,T-002" in out
    assert "salvage" in out
    assert "feedfac" in out
    assert "target" in out
    assert "0123456" in out


@pytest.mark.unit
def test_delivery_init_routes_to_harness_init(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "init"])

    with patch("echelon.cli._cmd_harness_init") as mock_init:
        main()

    mock_init.assert_called_once_with([], command_prefix="echelon delivery init")


@pytest.mark.unit
def test_delivery_target_detects_verify_command_from_spec_target_branch(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from echelon.cli import main
    from harness.spec_frontmatter import read_target_entries, write_targets

    workspace = tmp_path
    (workspace / ".git").mkdir()
    spec_dir = workspace / "specs" / "001-prose-distribution-engine"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Prosaic\n", encoding="utf-8")
    write_targets(spec_dir, ["sources/prosaic"])

    target = workspace / "sources" / "prosaic"
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=target, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=target, check=True)
    (target / "README.md").write_text("# Prosaic\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=target, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=target, check=True, capture_output=True)
    subprocess.run(
        ["git", "switch", "-c", "001-prose-distribution-engine"],
        cwd=target,
        check=True,
        capture_output=True,
    )
    (target / "package.json").write_text(
        json.dumps({"scripts": {"test": "jest"}}),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "package.json"], cwd=target, check=True)
    subprocess.run(["git", "commit", "-m", "add app"], cwd=target, check=True, capture_output=True)
    subprocess.run(["git", "switch", "main"], cwd=target, check=True, capture_output=True)

    monkeypatch.chdir(workspace)
    monkeypatch.setattr(
        "sys.argv",
        ["echelon", "delivery", "target", "001-prose-distribution-engine"],
    )

    main()

    entry = read_target_entries(spec_dir)[0]
    assert entry["delivery"]["verify_command"] == "npm test"
    assert entry["delivery"]["verify_detection"] == "high"
    assert "package.json scripts.test" in entry["delivery"]["verify_evidence"]
    out = capsys.readouterr().out
    assert "DELIVERY TARGET" in out
    assert "sources/prosaic" in out
    assert "npm test" in out
    assert "echelon delivery run 001-prose-distribution-engine --mode=banzai" in out


@pytest.mark.unit
def test_delivery_init_rejects_target_argument(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from echelon.cli import main

    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "init", "sources/app"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "no longer accepts a target repository" in captured.err
    assert "echelon spec run <description> --target <source-path>" in captured.err


@pytest.mark.unit
def test_delivery_init_non_git_workspace_fails_before_mirror_clone(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from harness.init import InitError
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "init"])
    monkeypatch.chdir(tmp_path)

    def fail_if_called(*_args, **_kwargs):
        raise InitError("Failed to clone mirror: should not be reached")

    monkeypatch.setattr("harness.init.init_harness", fail_if_called)

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "workspace root is not a Git repo" in captured.err
    assert "Failed to clone mirror" not in captured.err
    assert "Then rerun:\n  echelon delivery init" in captured.err


@pytest.mark.unit
def test_delivery_run_routes_to_harness_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "run", "001", "strategy=codegen"])

    with patch("echelon.cli._cmd_harness_run") as mock_run:
        main()

    mock_run.assert_called_once_with(
        ["001", "strategy=codegen"],
        command_prefix="echelon delivery run",
        display_args=["001", "strategy=codegen"],
    )


@pytest.mark.unit
def test_delivery_run_multiple_source_roots_reports_delivery_rerun_command(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from echelon.cli import main

    (tmp_path / ".git").mkdir()
    spec_dir = tmp_path / "specs" / "001-feature"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Feature\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=foundation req=FR-001 depends=none\n",
        encoding="utf-8",
    )
    for name in ["ruler", "spec-kit-skills-agents"]:
        source = tmp_path / "sources" / name
        (source / ".git").mkdir(parents=True)
        (source / "package.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["echelon", "delivery", "run", "--mode=banzai", "001-feature"],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "has no implementation target" in err
    assert "echelon spec run <description> --target <source-path>" in err
    assert "echelon harness run" not in err


@pytest.mark.unit
def test_delivery_resume_routes_to_harness_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "resume", "001"])

    with patch("echelon.cli._cmd_harness_resume") as mock_resume:
        main()

    mock_resume.assert_called_once_with(["001"])


@pytest.mark.unit
def test_delivery_continue_routes_to_harness_continue(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "continue", "001"])

    with patch("echelon.cli._cmd_harness_continue") as mock_continue:
        main()

    mock_continue.assert_called_once_with(["001"])


@pytest.mark.unit
def test_delivery_land_routes_to_land(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "land", "001", "--continue"])

    with patch("echelon.cli._cmd_land") as mock_land:
        main()

    mock_land.assert_called_once_with(["001", "--continue"])


@pytest.mark.unit
def test_harness_land_remains_compatibility_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "harness", "land", "001", "--continue"])

    with patch("echelon.cli._cmd_land") as mock_land:
        main()

    mock_land.assert_called_once_with(["001", "--continue"])


@pytest.mark.unit
def test_harness_namespace_remains_compatibility_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "harness", "run", "001"])

    with patch("echelon.cli._cmd_harness_run") as mock_run:
        main()

    mock_run.assert_called_once_with(
        ["001"],
        command_prefix="echelon delivery run",
        display_args=["001"],
    )


@pytest.mark.unit
def test_delivery_unknown_subcommand_exits_without_traceback(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "bogus"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "No such command 'bogus'" in captured.err
    assert "Traceback" not in captured.err
