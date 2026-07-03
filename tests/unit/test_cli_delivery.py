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
