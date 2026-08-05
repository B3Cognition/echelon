"""Tests for the Typer-backed Echelon CLI front door."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner


def invoke_help(*args: str):
    from echelon.cli_app import app

    return CliRunner().invoke(app, [*args, "--help"])


@pytest.mark.unit
def test_re_publish_routes_explicit_flags(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_re_publish", lambda args: calls.append(args))

    run(["re", "publish", "spec-123", "--allow-partial", "--commit"])

    assert calls == [["spec-123", "--allow-partial", "--commit"]]


@pytest.mark.unit
def test_re_execute_run_routes_to_deterministic_controller(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_re_execute_run", lambda args: calls.append(args))

    run(["re", "execute-run", "spec-123"])

    assert calls == [["spec-123"]]


@pytest.mark.unit
def test_prosaic_export_routes_explicit_source_and_destination(monkeypatch, tmp_path: Path):
    from echelon.cli_app import run
    from harness.prosaic_export import ProsaicExportResult

    calls: list[tuple[Path, Path]] = []

    def fake_export(extension_root: Path, destination: Path) -> ProsaicExportResult:
        calls.append((extension_root, destination))
        return ProsaicExportResult(destination=destination, exported_count=2)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("harness.prosaic_export.export_normalized_prose", fake_export)

    run([
        "prosaic",
        "export",
        "--extension-root",
        "fixture-extension",
        "--output",
        "generated-prosaic",
    ])

    assert calls == [
        (tmp_path / "fixture-extension", tmp_path / "generated-prosaic"),
    ]


@pytest.mark.unit
def test_re_check_domain_routes_to_deterministic_gate(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_re_check_domain", lambda args: calls.append(args))

    run(["re", "check-domain", "spec-123", "api", "001-re-api"])

    assert calls == [["spec-123", "api", "001-re-api"]]


@pytest.mark.unit
def test_re_publish_help_declares_manual_safety_flags():
    result = invoke_help("re", "publish")

    assert result.exit_code == 0
    assert "RUN_ID" in result.output
    assert "--allow-partial" in result.output
    assert "--commit" in result.output


@pytest.mark.unit
def test_spec_rewind_help_declares_a_ledger_checkpoint_target():
    result = invoke_help("spec", "rewind")

    assert result.exit_code == 0
    assert "Recorded checkpoint phase or ID" in result.output
    assert "--commit" in result.output
    assert "Safe phase id" not in result.output


@pytest.mark.unit
def test_spec_rewind_forwards_checkpoint_commit(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_rewind",
        lambda args, project_root: calls.append(args),
    )

    run([
        "spec",
        "rewind",
        "phase1-what",
        "--commit",
        "98152f1",
        "--confirm",
    ])

    assert calls == [[
        "phase1-what",
        "--commit",
        "98152f1",
        "--confirm",
    ]]


@pytest.mark.unit
def test_spec_retarget_forwards_ordered_targets_and_confirm(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_spec_retarget",
        lambda args: calls.append(args),
        raising=False,
    )

    run([
        "spec",
        "retarget",
        "001-demo",
        "--target",
        "apps/web",
        "--target",
        "services/api",
        "--confirm",
    ])

    assert calls == [[
        "001-demo",
        "--target",
        "apps/web",
        "--target",
        "services/api",
        "--confirm",
    ]]

    from echelon.cli import USAGE

    assert "spec retarget <spec_id> --target <source-id-or-path>... [--confirm]" in USAGE


@pytest.mark.unit
def test_spec_retarget_typer_help_declares_destructive_arguments():
    result = invoke_help("spec", "retarget")

    assert result.exit_code == 0
    assert "SPEC_ID" in result.output
    assert "--target" in result.output
    assert "--confirm" in result.output
    assert "complete replacement" in result.output.lower()


@pytest.mark.unit
def test_spec_retarget_dispatches_preserved_phase_a_arguments(monkeypatch, tmp_path):
    from echelon import cli
    from echelon.spec_retarget import RetargetCommandResult

    result = RetargetCommandResult(
        applied=True,
        resume_existing=False,
        spec_id="001-demo",
        baseline_run_id="squad-base",
        replacement_run_id="squad-replacement",
        replacement_targets=("apps/web", "services/api"),
        checkpoint_id="retarget-preflight-rev-1",
        checkpoint_commit="a" * 40,
        recovery_command="echelon spec rewind checkpoint:retarget-preflight-rev-1 --confirm",
        invalidated_paths=("spec.md",),
        original_user_message="Build account search exactly",
        autonomy_mode="guided",
        ignore_re=True,
        explicit_re_sources=("catalog", "billing"),
    )
    calls: list[tuple[list[str], Path, Path]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.spec_retarget_cli.run_spec_retarget_command",
        lambda *_args, **_kwargs: result,
    )
    monkeypatch.setattr(cli, "_installed_extension_or_exit", lambda root: root / "ext")
    monkeypatch.setattr(
        cli,
        "_cmd_run",
        lambda args, project_root, ext_dir: calls.append((args, project_root, ext_dir)),
    )

    cli._cmd_spec_retarget(
        ["001-demo", "--target", "apps/web", "--confirm"]
    )

    assert calls == [
        (
            [
                "Build account search exactly",
                "--mode",
                "guided",
                "--target",
                "apps/web",
                "--target",
                "services/api",
                "--re-source",
                "catalog",
                "--re-source",
                "billing",
                "--ignore-re",
            ],
            tmp_path,
            tmp_path / "ext",
        )
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "args",
    (
        ("spec", "retarget"),
        ("spec", "retarget", "001-demo"),
        ("spec", "retarget", "001-demo", "apps/web"),
        ("spec", "retarget", "001-demo", "--target"),
        ("spec", "retarget", "001-demo", "--target", "apps/web", "--init"),
        ("spec", "retarget", "001-demo", "--target", "apps/web", "--unknown"),
        (
            "spec",
            "retarget",
            "001-demo",
            "--target",
            "apps/web",
            "--confirm",
            "--confirm",
        ),
    ),
)
def test_spec_retarget_typer_invalid_shapes_exit_2(args):
    from echelon.cli_app import app

    result = CliRunner().invoke(app, list(args))

    assert result.exit_code == 2


@pytest.mark.unit
def test_spec_amend_routes_product_inputs_and_dry_run(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_spec_amend", lambda args: calls.append(args))

    run([
        "spec",
        "amend",
        "004-demo",
        "Add requirement evidence",
        "--input",
        "requirement:sources/PBS-E-73.pdf",
        "--input",
        "reference:sources/PBS-E-73-figma-design.pdf",
        "--dry-run",
    ])

    assert calls == [[
        "004-demo",
        "Add requirement evidence",
        "--input",
        "requirement:sources/PBS-E-73.pdf",
        "--input",
        "reference:sources/PBS-E-73-figma-design.pdf",
        "--dry-run",
    ]]


@pytest.mark.unit
def test_spec_add_input_routes_product_inputs(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_spec_add_input", lambda args: calls.append(args))

    run([
        "spec",
        "add-input",
        "--input",
        "reference:sources/DE-OPTA-SCHEMA-MAPPING",
        "--input",
        "reference:sources/DE-RESOLVER-BENCHMARK",
    ])

    assert calls == [[
        "--input",
        "reference:sources/DE-OPTA-SCHEMA-MAPPING",
        "--input",
        "reference:sources/DE-RESOLVER-BENCHMARK",
    ]]


@pytest.mark.unit
def test_spec_add_input_help_declares_input_option():
    result = invoke_help("spec", "add-input")

    assert result.exit_code == 0
    assert "--input" in result.output
    assert "parked investigation" in result.output


@pytest.mark.unit
def test_spec_amend_help_declares_input_and_dry_run_options():
    result = invoke_help("spec", "amend")

    assert result.exit_code == 0
    assert "SPEC_ID" in result.output
    assert "--input" in result.output
    assert "--dry-run" in result.output


@pytest.mark.unit
def test_spec_amend_status_routes_to_the_amendment_lifecycle(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_spec_amend", lambda args: calls.append(args))

    run(["spec", "amend", "status", "004-demo/001"])

    assert calls == [["status", "004-demo/001"]]


@pytest.mark.unit
def test_spec_amend_preparation_does_not_advertise_an_unimplemented_approval_action(
    monkeypatch,
):
    from echelon.cli_app import app
    from echelon.spec_amendment import (
        AmendmentPreparation,
        AmendmentWorktree,
        ControlBaseline,
    )

    baseline = ControlBaseline("004-demo", "004-demo", "a" * 40, False)
    prepared = AmendmentPreparation(
        amendment_id="004-demo/001",
        baseline=baseline,
        revision=1,
        dry_run=False,
        worktree=AmendmentWorktree(Path("/tmp/amendment"), "amend/004-demo/001", baseline, 1),
        state_path=Path("/tmp/state.json"),
    )
    monkeypatch.setattr("echelon.spec_amendment.prepare_amendment", lambda *_args: prepared)

    result = CliRunner().invoke(app, ["spec", "amend", "004-demo", "Add evidence"])

    assert result.exit_code == 0
    assert "No canonical spec, plan, or task artifact has been changed." in result.output
    assert "approve its workflow" not in result.output


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
    assert "--target" not in declared_options


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
        "wiki",
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

    run(["harness", "run", "001", "--mode", "banzai"])

    assert calls == [["001", "mode=banzai"]]


@pytest.mark.unit
def test_typer_run_prints_version_without_subcommand(capsys):
    from echelon.cli import CLI_VERSION
    from echelon.cli_app import run

    run(["--version"])

    assert capsys.readouterr().out.strip() == f"echelon {CLI_VERSION}"


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
def test_spec_switch_is_exposed_by_typer_front_door(monkeypatch, tmp_path):
    from echelon.cli_app import app, run

    help_result = CliRunner().invoke(app, ["spec", "switch", "--help"])

    assert help_result.exit_code == 0
    assert "SPEC_OR_RUN_ID" in help_result.output
    assert "--stash" in help_result.output
    assert "--discard" in help_result.output
    assert "--restore-stash" in help_result.output

    calls: list[tuple[list[str], Path]] = []

    def fake_switch(args, *, project_root, **_kwargs):
        calls.append((args, project_root))
        return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.spec_switch_cli.run_spec_switch_command",
        fake_switch,
    )

    run(["spec", "switch", "001-demo", "--stash", "--restore-stash"])

    assert calls == [(["001-demo", "--stash", "--restore-stash"], tmp_path)]


@pytest.mark.unit
def test_spec_targets_declares_argument_and_routes(monkeypatch):
    from echelon.cli_app import run

    result = invoke_help("spec", "targets")

    assert result.exit_code == 0
    assert "SPEC_ID" in result.output
    assert "Display every task grouped by delivery target" in result.output

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_spec_targets", lambda args: calls.append(args))

    run(["spec", "targets", "001"])

    assert calls == [["001"]]


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
    assert "--init" in result.output
    assert "--message" in result.output
    assert "--next-phase" in result.output
    assert "--target" in result.output
    assert "--input" in result.output
    assert "--ignore-re" in result.output
    assert "--stash" in result.output
    assert "--discard" in result.output
    assert "--confirm" in result.output
    assert "--re-policy" not in result.output
    assert "--re-max-inner" not in result.output


@pytest.mark.unit
def test_spec_help_offers_only_guarded_unused_target_removal():
    result = invoke_help("spec")
    normalized = " ".join(result.output.split())

    assert result.exit_code == 0
    assert "target Set implementation targets" not in normalized
    assert "targets <spec_id>" in normalized
    assert "drop-target <spec_id> <target> --confirm" in normalized


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
        "--init",
        "--message",
        "include migration notes",
        "--next-phase",
        "phase2-model",
        "--target",
        "api",
        "--target",
        "web",
        "--input",
        "requirement:sources/PBS-E-45",
        "--input",
        "reference:sources/provision",
        "--ignore-re",
        "--stash",
    ])

    assert calls == [[
        "Add archive export",
        "--mode",
        "banzai",
        "--reset",
        "--init",
        "--message",
        "include migration notes",
        "--next-phase",
        "phase2-model",
        "--target",
        "api",
        "--target",
        "web",
        "--input",
        "requirement:sources/PBS-E-45",
        "--input",
        "reference:sources/provision",
        "--ignore-re",
        "--stash",
    ]]


@pytest.mark.unit
def test_workspace_init_help_declares_workspace_options():
    from echelon.cli_app import app
    from typer.main import get_command

    result = invoke_help("workspace", "init")

    assert result.exit_code == 0
    assert "--llm" in result.output
    assert "--llm-cli" in result.output
    assert "--openai-base-url" in result.output
    assert "--openai-model" in result.output
    assert "--openai-api-key-file" in result.output
    assert "--openai-api-key-env" in result.output
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
def test_workspace_init_typed_openai_options_route_to_legacy_workspace(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_workspace", lambda args: calls.append(args))

    run(
        [
            "workspace",
            "init",
            "--llm",
            "openai-compatible",
            "--openai-base-url",
            "http://127.0.0.1:8000/v1",
            "--openai-model",
            "ThinkingCap-Qwen3.6-27B-OptiQ-4bit",
            "--openai-api-key-file",
            "~/.omlx_token",
            "--openai-api-key-env",
            "OMLX_API_KEY",
            "--no-unsafe-host-execution",
        ]
    )

    assert calls == [
        [
            "init",
            "--llm",
            "openai-compatible",
            "--openai-base-url",
            "http://127.0.0.1:8000/v1",
            "--openai-model",
            "ThinkingCap-Qwen3.6-27B-OptiQ-4bit",
            "--openai-api-key-file",
            "~/.omlx_token",
            "--openai-api-key-env",
            "OMLX_API_KEY",
            "--no-unsafe-host-execution",
        ]
    ]


@pytest.mark.unit
def test_workspace_sources_sync_typed_options_route_to_legacy_workspace(monkeypatch):
    from echelon.cli_app import run

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_workspace", lambda args: calls.append(args))

    run(["workspace", "sources", "sync", "--write"])

    assert calls == [["sources", "sync", "--write"]]


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
    assert "--artifact-only" in run_help.output
    assert "--context-render" in run_help.output
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
def test_spec_verify_resolves_canonical_spec_and_declared_target(
    monkeypatch, tmp_path: Path
) -> None:
    from echelon.cli_app import run
    from harness.fulfillment_runner import FulfillmentRefreshResult

    target = tmp_path / "sources" / "prosaic"
    target.mkdir(parents=True)
    spec_dir = tmp_path / "specs" / "906-cli-output-styling"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\ntargets:\n  - sources/prosaic\n---\n# Spec\n",
        encoding="utf-8",
    )
    calls: list[dict[str, object]] = []

    class FakeRunner:
        def __init__(self, provider: object) -> None:
            calls.append({"provider": provider})

        def refresh(self, worktree_path: str, spec_id: str, **kwargs: object):
            calls[-1].update(
                {"worktree_path": worktree_path, "spec_id": spec_id, **kwargs}
            )
            return FulfillmentRefreshResult(
                status="refreshed",
                exit_code=0,
                reason="full verify-spec completed",
                report_path=str(spec_dir / "fulfillment-report.md"),
            )

    provider = object()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("harness.config.load_config", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("harness.llm_provider.AICodingCliProvider", lambda _config: provider)
    monkeypatch.setattr("harness.fulfillment_runner.FulfillmentRunner", FakeRunner)

    run(["spec", "verify", "906", "--reconcile"])

    assert calls == [
        {
            "provider": provider,
            "worktree_path": str(target.resolve()),
            "spec_id": "906-cli-output-styling",
            "spec_dir": spec_dir.resolve(),
            "orchestration_root": tmp_path.resolve(),
            "reconcile": True,
            "dry_run": False,
        }
    ]


@pytest.mark.unit
def test_spec_verify_rejects_multiple_targets_before_provider(
    monkeypatch, tmp_path: Path
) -> None:
    from echelon.cli_app import app

    spec_dir = tmp_path / "specs" / "906-cli-output-styling"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\ntargets:\n  - sources/a\n  - sources/b\n---\n# Spec\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["spec", "verify", "906"])

    assert result.exit_code != 0
    assert "exactly one target" in result.output


@pytest.mark.unit
def test_spec_verify_returns_nonzero_for_failed_runner_status(
    monkeypatch, tmp_path: Path
) -> None:
    from echelon.cli_app import app
    from harness.fulfillment_runner import FulfillmentRefreshResult

    spec_dir = tmp_path / "specs" / "906-cli-output-styling"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    class FailedRunner:
        def __init__(self, _provider: object) -> None:
            pass

        def refresh(self, *_args: object, **_kwargs: object):
            return FulfillmentRefreshResult(
                status="failed",
                exit_code=0,
                reason="artifact validation failed",
            )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("harness.config.load_config", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("harness.llm_provider.AICodingCliProvider", lambda _config: object())
    monkeypatch.setattr("harness.fulfillment_runner.FulfillmentRunner", FailedRunner)

    result = CliRunner().invoke(app, ["spec", "verify", "906"])

    assert result.exit_code == 1
    assert "status: failed" in result.output
    assert "artifact validation failed" in result.output


@pytest.mark.unit
def test_spec_verify_rejects_dry_run_without_reconcile(
    monkeypatch, tmp_path: Path
) -> None:
    from echelon.cli_app import app

    spec_dir = tmp_path / "specs" / "906-cli-output-styling"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app,
        ["spec", "verify", "906", "--dry-run"],
    )

    assert result.exit_code == 2
    assert "--dry-run requires --reconcile" in result.output


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
