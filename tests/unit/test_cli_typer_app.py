"""Tests for the Typer-backed Echelon CLI front door."""

from __future__ import annotations

import sys

import pytest
from typer.testing import CliRunner


def invoke_help(*args: str):
    from echelon.cli_app import app

    return CliRunner().invoke(app, [*args, "--help"])


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
        "--target",
        "api",
        "--no-auto-merge",
        "--kill-losers",
        "--reset",
    ])

    assert calls == [[
        "001",
        "mode=banzai",
        "strategy=codegen",
        "target=api",
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
def test_delivery_resume_help_declares_answer_argument():
    result = invoke_help("delivery", "resume")

    assert result.exit_code == 0
    assert "SPEC_ID" in result.output
    assert "ANSWER" in result.output
    assert "--mode" in result.output
    assert "--strategy" in result.output


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
    assert "--target" in declared_options


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
def test_root_help_hides_compatibility_aliases():
    from echelon.cli_app import app
    from typer.main import get_command

    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "workspace" in result.output
    assert "spec" in result.output
    assert "delivery" in result.output
    assert "stack" in result.output
    assert "benchmark" in result.output
    assert "harness" not in result.output
    command = get_command(app)
    for alias in (
        "artifacts",
        "land",
        "continue",
        "rewind",
        "resume",
        "run",
        "build",
        "review",
        "codegen",
        "verify-spec",
        "reopen",
        "bugfix",
        "change",
        "cicd",
    ):
        assert command.commands[alias].hidden


@pytest.mark.unit
def test_hidden_top_level_alias_still_routes(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_harness_run", lambda args, **_kwargs: calls.append(args))

    run(["harness", "run", "001", "--target", "api"])

    assert calls == [["001", "target=api"]]


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
    assert "Common forms:" in result.output
    assert "run <description> [--mode semi|banzai|guided] [--reset]" in result.output
    assert "run" in result.output
    assert "status" in result.output
    assert "Usage: echelon spec <subcommand>" not in result.output


@pytest.mark.unit
def test_delivery_help_uses_phase_b_common_forms():
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["delivery", "--help"])

    assert result.exit_code == 0
    assert "Usage: root delivery [OPTIONS] COMMAND [ARGS]..." in result.output
    assert "Phase B/delivery commands" in result.output
    assert "Common forms:" in result.output
    assert "status [<spec_id>] [--strategy <s>]" in result.output
    assert "run <spec_id> [--target <source-id-or-path>] [--mode <m>]" in result.output
    assert "land <spec_id> [--continue] [--prepare-only]" in result.output


@pytest.mark.unit
def test_delivery_status_declares_options_and_routes(monkeypatch):
    from echelon.cli_app import run

    help_result = invoke_help("delivery", "status")

    assert help_result.exit_code == 0
    assert "SPEC_ID" in help_result.output
    assert "--strategy" in help_result.output
    assert "--json" in help_result.output

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_delivery_status", lambda args: calls.append(args))

    run(["delivery", "status", "001", "--strategy", "codegen", "--json"])

    assert calls == [["001", "--strategy", "codegen", "--json"]]


@pytest.mark.unit
def test_spec_run_help_declares_phase_a_options():
    result = invoke_help("spec", "run")

    assert result.exit_code == 0
    assert "DESCRIPTION" in result.output
    assert "--mode" in result.output
    assert "--reset" in result.output
    assert "--message" in result.output
    assert "--next-phase" in result.output
    assert "--target" in result.output
    assert "--target-source" in result.output
    assert "--re-policy" in result.output


@pytest.mark.unit
def test_spec_run_typed_options_route_to_legacy_spec_run(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_spec_run", lambda args: calls.append(args))

    run([
        "spec",
        "run",
        "Add archive export",
        "--mode",
        "banzai",
        "--reset",
        "--message",
        "include migration notes",
        "--next-phase",
        "phase2-model",
        "--target",
        "api",
        "--re-policy",
        "target-only",
    ])

    assert calls == [[
        "Add archive export",
        "--mode",
        "banzai",
        "--reset",
        "--message",
        "include migration notes",
        "--next-phase",
        "phase2-model",
        "--target",
        "api",
        "--re-policy",
        "target-only",
    ]]


@pytest.mark.unit
def test_workspace_init_help_declares_workspace_options():
    from echelon.cli_app import app
    from typer.main import get_command

    result = invoke_help("workspace", "init")

    assert result.exit_code == 0
    assert "--llm" in result.output
    assert "--llm-cli" in result.output
    command = get_command(app)
    workspace_command = command.commands["workspace"]
    init_command = workspace_command.commands["init"]
    declared_options: set[str] = set()
    for param in init_command.params:
        declared_options.update(getattr(param, "opts", []))
        declared_options.update(getattr(param, "secondary_opts", []))
    assert "--allow-unsafe-host-execution" in declared_options
    assert "--no-unsafe-host-execution" in declared_options


@pytest.mark.unit
def test_workspace_init_typed_options_route_to_legacy_workspace(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_workspace", lambda args: calls.append(args))

    run([
        "workspace",
        "init",
        "--llm",
        "codex",
        "--allow-unsafe-host-execution",
    ])

    assert calls == [["init", "--llm", "codex", "--allow-unsafe-host-execution"]]


@pytest.mark.unit
def test_spec_target_typed_args_route_to_legacy_spec_target(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_spec_target", lambda args: calls.append(args))

    run(["spec", "target", "001", "sources/api", "sources/web", "--init"])

    assert calls == [["001", "sources/api", "sources/web", "--init"]]


@pytest.mark.unit
def test_phase_run_help_declares_phase_replay_options():
    result = invoke_help("phase", "run")

    assert result.exit_code == 0
    assert "PHASE_ID" in result.output
    assert "--spec" in result.output
    assert "--mode" in result.output
    assert "--message" in result.output


@pytest.mark.unit
def test_benchmark_help_declares_run_and_show_contracts():
    run_help = invoke_help("benchmark", "run")
    show_help = invoke_help("benchmark", "show")

    assert run_help.exit_code == 0
    assert "FIXTURE_ID" in run_help.output
    assert "--variant" in run_help.output
    assert "--baseline-ref" in run_help.output
    assert "--dry-run" in run_help.output
    assert show_help.exit_code == 0
    assert "TARGET" in show_help.output


@pytest.mark.unit
def test_stack_help_declares_detection_and_preflight_options():
    list_help = invoke_help("stack", "list")
    detect_help = invoke_help("stack", "detect")
    preflight_help = invoke_help("stack", "preflight")

    assert list_help.exit_code == 0
    assert "--json" in list_help.output
    assert detect_help.exit_code == 0
    assert "--target" in detect_help.output
    assert "--artifacts" in detect_help.output
    assert "--write" in detect_help.output
    assert "--format" in detect_help.output
    assert "--json" in detect_help.output
    assert preflight_help.exit_code == 0
    assert "--stack" in preflight_help.output
    assert "--target-archetype" in preflight_help.output
    assert "--from-detect" in preflight_help.output
    assert "--probe-tools" in preflight_help.output
    assert "--json" in preflight_help.output


@pytest.mark.unit
def test_stack_detect_repeated_artifacts_route_to_legacy_stack(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_stack",
        lambda args, **_kwargs: calls.append(args),
    )

    run([
        "stack",
        "detect",
        "--target",
        "sources/api",
        "--artifacts",
        "specs/001",
        "--artifacts",
        "runs/re",
        "--write",
        "--format",
        "yaml",
    ])

    assert calls == [[
        "detect",
        "--target",
        "sources/api",
        "--artifacts",
        "specs/001",
        "--artifacts",
        "runs/re",
        "--write",
        "--format",
        "yaml",
    ]]


@pytest.mark.unit
def test_spec_skill_help_declares_common_arguments():
    verify_help = invoke_help("spec", "verify")
    reopen_help = invoke_help("spec", "reopen")
    bugfix_help = invoke_help("spec", "bugfix")
    change_help = invoke_help("spec", "change")

    assert verify_help.exit_code == 0
    assert "SPEC_ID" in verify_help.output
    assert "--reconcile" in verify_help.output
    assert "--dry-run" in verify_help.output
    assert reopen_help.exit_code == 0
    assert "SPEC_ID" in reopen_help.output
    assert bugfix_help.exit_code == 0
    assert "SPEC_ID" in bugfix_help.output
    assert "DESCRIPTION" in bugfix_help.output
    assert change_help.exit_code == 0
    assert "SPEC_ID" in change_help.output
    assert "DESCRIPTION" in change_help.output


@pytest.mark.unit
def test_top_level_skill_aliases_declare_common_arguments():
    build_help = invoke_help("build")
    review_help = invoke_help("review")
    codegen_help = invoke_help("codegen")
    verify_help = invoke_help("verify-spec")
    reopen_help = invoke_help("reopen")
    bugfix_help = invoke_help("bugfix")
    change_help = invoke_help("change")

    assert build_help.exit_code == 0
    assert "SPEC_ID" in build_help.output
    assert "--fix" in build_help.output
    assert "--failures" in build_help.output
    assert "--context" in build_help.output
    assert review_help.exit_code == 0
    assert "SPEC_ID" in review_help.output
    assert "--pr-url" in review_help.output
    assert codegen_help.exit_code == 0
    assert "SPEC_ID" in codegen_help.output
    assert verify_help.exit_code == 0
    assert "SPEC_ID" in verify_help.output
    assert "--reconcile" in verify_help.output
    assert "--dry-run" in verify_help.output
    assert reopen_help.exit_code == 0
    assert "SPEC_ID" in reopen_help.output
    assert bugfix_help.exit_code == 0
    assert "SPEC_ID" in bugfix_help.output
    assert "DESCRIPTION" in bugfix_help.output
    assert change_help.exit_code == 0
    assert "SPEC_ID" in change_help.output
    assert "DESCRIPTION" in change_help.output


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
