"""Tests for the Typer-backed Echelon CLI front door."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner


@pytest.mark.unit
def test_delivery_run_canonical_flags_route_to_harness_run(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_harness_run", lambda args: calls.append(args))

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
    monkeypatch.setattr("echelon.cli._cmd_harness_run", lambda args: calls.append(args))

    run(["delivery", "run", "001", "mode=banzai", "strategy=codegen", "max_outer=3"])

    assert calls == [["001", "mode=banzai", "strategy=codegen", "max_outer=3"]]


@pytest.mark.unit
def test_delivery_run_canonical_flags_take_precedence_over_legacy_args(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_harness_run", lambda args: calls.append(args))

    run(["delivery", "run", "001", "mode=semi", "--mode", "banzai"])

    assert calls == [["001", "mode=semi", "mode=banzai"]]


@pytest.mark.unit
def test_delivery_resume_canonical_flags_route_to_harness_resume(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_harness_resume", lambda args: calls.append(args))

    run(["delivery", "resume", "001", "--mode", "banzai", "--strategy", "codegen"])

    assert calls == [["001", "mode=banzai", "strategy=codegen"]]


@pytest.mark.unit
def test_delivery_run_help_shows_canonical_flags():
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["delivery", "run", "--help"],
        env={"COLUMNS": "120"},
    )

    assert result.exit_code == 0
    assert "--mode" in result.stdout
    assert "--strategy" in result.stdout
    assert "--max-outer" in result.stdout
