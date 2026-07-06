"""CLI tests for the delivery namespace and top-level help."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.unit
def test_help_command_prints_usage_without_unknown_command(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "help"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "echelon: unknown command" not in captured.err
    assert "Usage: echelon <command>" in captured.out
    assert "delivery init" in captured.out
    assert "delivery run <spec_id> [mode=<m>] [strategy=<s>]" in captured.out
    assert "max_outer=<n>" in captured.out
    assert "auto_merge=<bool>" in captured.out
    assert "workspace migrate [--write] [--commit] [--message <msg>]" in captured.out
    assert "spec run <description> [--mode semi|banzai|guided] [--reset]" in captured.out
    assert "[--message <text>] [--next-phase <id>]" in captured.out
    assert "phase run <phase-id> [--spec <id>] [--mode semi|banzai|guided]" in captured.out
    assert "[--message <text>]" in captured.out
    assert "checkpoint list|accept|commit [--spec <id>] [--phase <phase-id>]" in captured.out
    assert "benchmark show [latest|<summary-path-or-run-dir>]" in captured.out
    assert "[--baseline-ref <ref>] [--dry-run]" in captured.out


@pytest.mark.unit
def test_phase_help_does_not_require_installed_extension(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "phase", "--help"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "Echelon extension not installed" not in captured.err
    assert "echelon phase run <phase-id>" in captured.out
    assert "--message <text>" in captured.out


@pytest.mark.unit
def test_checkpoint_help_documents_subcommands_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "checkpoint", "--help"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "echelon checkpoint list" in captured.out
    assert "echelon checkpoint accept --phase <phase-id>" in captured.out
    assert "echelon checkpoint commit --phase <phase-id>" in captured.out
    assert "--run-id <id>" in captured.out
    assert "--message <msg>" in captured.out


@pytest.mark.unit
def test_delivery_init_routes_to_harness_init(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "init", "app"])

    with patch("echelon.cli._cmd_harness_init") as mock_init:
        main()

    mock_init.assert_called_once_with(["app"])


@pytest.mark.unit
def test_delivery_run_routes_to_harness_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "run", "001", "strategy=codegen"])

    with patch("echelon.cli._cmd_harness_run") as mock_run:
        main()

    mock_run.assert_called_once_with(["001", "strategy=codegen"])


@pytest.mark.unit
def test_delivery_resume_routes_to_harness_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "resume", "001"])

    with patch("echelon.cli._cmd_harness_resume") as mock_resume:
        main()

    mock_resume.assert_called_once_with(["001"])


@pytest.mark.unit
def test_delivery_land_routes_to_land(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "land", "001", "--continue"])

    with patch("echelon.cli._cmd_land") as mock_land:
        main()

    mock_land.assert_called_once_with(["001", "--continue"])


@pytest.mark.unit
def test_harness_namespace_remains_compatibility_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "harness", "run", "001"])

    with patch("echelon.cli._cmd_harness_run") as mock_run:
        main()

    mock_run.assert_called_once_with(["001"])
