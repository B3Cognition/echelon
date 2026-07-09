"""Tests for the Typer-backed Echelon CLI front door."""

from __future__ import annotations

import sys

import pytest
from typer.testing import CliRunner


@pytest.mark.unit
def test_delivery_run_canonical_flags_route_to_harness_run(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_harness_run",
        lambda args, **_kwargs: calls.append(args),
    )

    run([
        "delivery",
        "run",
        "001",
        "--mode",
        "banzai",
        "--strategy",
        "codegen",
        "--max-outer",
        "3",
        "--max-inner",
        "2",
        "--token-budget",
        "1000",
        "--no-auto-merge",
        "--kill-losers",
        "--reset",
    ])

    assert calls == [[
        "001",
        "mode=banzai",
        "strategy=codegen",
        "max_outer=3",
        "max_inner=2",
        "token_budget=1000",
        "auto_merge=false",
        "kill_losers=true",
        "--reset",
    ]]


@pytest.mark.unit
def test_delivery_run_legacy_key_value_args_still_route(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_harness_run",
        lambda args, **_kwargs: calls.append(args),
    )

    run(["delivery", "run", "001", "mode=banzai", "strategy=codegen", "max_outer=3"])

    assert calls == [["001", "mode=banzai", "strategy=codegen", "max_outer=3"]]


@pytest.mark.unit
def test_delivery_run_canonical_flags_take_precedence_over_legacy_args(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_harness_run",
        lambda args, **_kwargs: calls.append(args),
    )

    run(["delivery", "run", "001", "mode=semi", "--mode", "banzai"])

    assert calls == [["001", "mode=semi", "mode=banzai"]]


@pytest.mark.unit
def test_delivery_resume_canonical_flags_route_to_harness_resume(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_harness_resume", lambda args: calls.append(args))

    run([
        "delivery",
        "resume",
        "001",
        "Use the direct mapping",
        "--mode",
        "banzai",
        "--strategy",
        "codegen",
    ])

    assert calls == [["001", "Use the direct mapping", "mode=banzai", "strategy=codegen"]]


@pytest.mark.unit
def test_delivery_continue_canonical_flags_route_to_harness_continue(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_harness_continue", lambda args: calls.append(args))

    run(["delivery", "continue", "001", "--mode", "banzai", "--strategy", "codegen"])

    assert calls == [["001", "mode=banzai", "strategy=codegen"]]


@pytest.mark.unit
def test_delivery_run_declares_canonical_flags():
    from echelon.cli_app import app
    from typer.main import get_command

    result = CliRunner().invoke(
        app,
        ["delivery", "run", "--help"],
    )

    assert result.exit_code == 0
    command = get_command(app)
    delivery_command = command.commands["delivery"]
    run_command = delivery_command.commands["run"]
    declared_options = {
        opt
        for param in run_command.params
        for opt in getattr(param, "opts", [])
    }
    assert "--mode" in declared_options
    assert "--strategy" in declared_options
    assert "--max-outer" in declared_options


@pytest.mark.unit
def test_delivery_land_declares_canonical_flags():
    from echelon.cli_app import app
    from typer.main import get_command

    result = CliRunner().invoke(
        app,
        ["delivery", "land", "--help"],
    )

    assert result.exit_code == 0
    assert "--continue" in result.output
    assert "--prepare-only" in result.output
    assert "--no-autoresolve" in result.output
    assert "--allow-fulfillment-gaps" in result.output
    assert "--strategy" in result.output
    command = get_command(app)
    delivery_command = command.commands["delivery"]
    land_command = delivery_command.commands["land"]
    declared_options = {
        opt
        for param in land_command.params
        for opt in getattr(param, "opts", [])
    }
    assert "--continue" in declared_options
    assert "--prepare-only" in declared_options
    assert "--no-autoresolve" in declared_options
    assert "--allow-fulfillment-gaps" in declared_options
    assert "--strategy" in declared_options


@pytest.mark.unit
def test_delivery_land_canonical_flags_route_to_land(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_land", lambda args: calls.append(args))

    run([
        "delivery",
        "land",
        "001",
        "--continue",
        "--prepare-only",
        "--no-autoresolve",
        "--allow-fulfillment-gaps",
        "--strategy",
        "rebase",
    ])

    assert calls == [[
        "001",
        "--continue",
        "--prepare-only",
        "--no-autoresolve",
        "--allow-fulfillment-gaps",
        "--strategy",
        "rebase",
    ]]


@pytest.mark.unit
def test_typer_front_door_declares_all_top_level_commands():
    from echelon.cli_app import app
    from typer.main import get_command

    command = get_command(app)

    assert {
        "artifacts",
        "benchmark",
        "bugfix",
        "build",
        "change",
        "cicd",
        "codegen",
        "continue",
        "delivery",
        "harness",
        "init",
        "land",
        "phase",
        "reopen",
        "resume",
        "review",
        "rewind",
        "run",
        "spec",
        "stack",
        "status",
        "verify-spec",
        "version",
        "workspace",
    }.issubset(command.commands)


@pytest.mark.unit
def test_typer_run_prints_version_without_subcommand(capsys):
    from echelon.cli_app import run

    run(["--version"])

    assert capsys.readouterr().out.strip() == "echelon 3.0.0"


@pytest.mark.unit
def test_spec_help_uses_typer_front_door():
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "--help"])

    assert result.exit_code == 0
    assert "Usage: root spec [OPTIONS] COMMAND [ARGS]..." in result.output
    assert "Phase A/spec lifecycle commands" in result.output
    assert "run" in result.output
    assert "status" in result.output
    assert "Usage: echelon spec <subcommand>" not in result.output


@pytest.mark.unit
def test_spec_status_routes_to_legacy_status(monkeypatch):
    from echelon.cli_app import run

    calls = []
    monkeypatch.setattr("echelon.cli._cmd_status", lambda project_root: calls.append(project_root))

    run(["spec", "status"])

    assert len(calls) == 1


@pytest.mark.unit
def test_main_routes_workspace_help_through_typer(monkeypatch, capsys):
    from echelon.cli import main

    monkeypatch.setattr(sys, "argv", ["echelon", "workspace", "--help"])

    main()

    out = capsys.readouterr().out
    assert "workspace [OPTIONS] COMMAND [ARGS]..." in out
    assert "Workspace setup, doctor, and migration commands." in out
    assert "Usage: echelon workspace <subcommand>" not in out
