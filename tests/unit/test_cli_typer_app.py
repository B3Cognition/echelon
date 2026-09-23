"""Tests for the Typer-backed Echelon CLI front door."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner


def invoke_help(*args: str):
    from echelon.cli_app import app

    return CliRunner().invoke(app, [*args, "--help"])


@pytest.mark.unit
def test_re_publish_routes_explicit_flags(monkeypatch):
    from echelon.cli_app import run
    from echelon.re_service import RePublishRequest

    calls: list[RePublishRequest] = []
    monkeypatch.setattr("echelon.re_service.publish_re", calls.append)

    run(["re", "publish", "spec-123", "--allow-partial", "--commit"])

    assert calls == [
        RePublishRequest(run_id="spec-123", allow_partial=True, commit=True)
    ]


@pytest.mark.unit
def test_re_v2_creation_options_are_typed_and_routed(monkeypatch):
    from echelon.cli_app import app, run
    from echelon.re_service import ReRunRequest

    help_result = invoke_help("re", "run")
    calls: list[ReRunRequest] = []
    monkeypatch.setattr(
        "echelon.re_service.run_re",
        lambda request: calls.append(request),
    )

    run(["re", "run", "--engine", "v2", "--shadow"])
    invalid = CliRunner().invoke(app, ["re", "run", "--engine", "future"])

    assert help_result.exit_code == 0
    assert "--engine" not in help_result.output
    assert "--shadow" not in help_result.output
    assert calls == [ReRunRequest(engine="v2", shadow=True)]
    assert invalid.exit_code == 2


@pytest.mark.unit
def test_re_knowledge_actions_lead_with_depth_and_repeatable_source(monkeypatch):
    from echelon.cli_app import app, run
    from echelon.re_service import ReRefreshRequest, ReRunRequest

    run_calls: list[ReRunRequest] = []
    refresh_calls: list[ReRefreshRequest] = []
    monkeypatch.setattr(
        "echelon.re_service.run_re",
        lambda request: run_calls.append(request),
    )
    monkeypatch.setattr(
        "echelon.re_service.refresh_re",
        lambda request: refresh_calls.append(request),
    )

    run_help = CliRunner().invoke(app, ["re", "run", "--help"])
    refresh_help = CliRunner().invoke(app, ["re", "refresh", "--help"])
    run(["re", "run", "--depth", "deep"])
    run(
        [
            "re",
            "refresh",
            "--source",
            "api",
            "--source",
            "worker",
            "--depth",
            "quick",
        ]
    )

    assert run_help.exit_code == refresh_help.exit_code == 0
    assert "--depth" in run_help.output
    assert "quick" in run_help.output
    assert "standard" in run_help.output
    assert "deep" in run_help.output
    assert "--source" in refresh_help.output
    assert "--depth" in refresh_help.output
    assert run_calls == [ReRunRequest(depth="deep")]
    assert refresh_calls == [
        ReRefreshRequest(sources=("api", "worker"), depth="quick")
    ]


@pytest.mark.unit
def test_re_knowledge_actions_reject_unknown_depth_without_dispatch(monkeypatch):
    from echelon.cli_app import app

    monkeypatch.setattr(
        "echelon.re_service.run_re",
        lambda _request: pytest.fail("invalid depth dispatched"),
    )
    monkeypatch.setattr(
        "echelon.re_service.refresh_re",
        lambda _request: pytest.fail("invalid depth dispatched"),
    )
    runner = CliRunner()

    run_result = runner.invoke(app, ["re", "run", "--depth", "future"])
    refresh_result = runner.invoke(
        app, ["re", "refresh", "--depth", "future"]
    )

    assert run_result.exit_code == refresh_result.exit_code == 2


@pytest.mark.unit
def test_re_status_json_option_routes_without_changing_default(monkeypatch):
    from echelon.cli_app import run
    from echelon.re_service import ReStatusRequest

    calls: list[ReStatusRequest] = []
    monkeypatch.setattr(
        "echelon.re_service.show_re_status",
        lambda request: calls.append(request),
    )

    run(["re", "status"])
    run(["re", "status", "--json"])

    assert calls == [ReStatusRequest(), ReStatusRequest(as_json=True)]


@pytest.mark.unit
def test_re_resume_routes_custom_recommended_and_banzai_modes(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import ReResumeRequest

    calls: list[ReResumeRequest] = []
    monkeypatch.setattr("echelon.re_service.resume_re", calls.append)
    runner = CliRunner()

    custom = runner.invoke(app, ["re", "resume", "Use accepted timeout evidence."])
    recommended = runner.invoke(app, ["re", "resume", "--recommended"])
    banzai = runner.invoke(
        app,
        [
            "re",
            "resume",
            "--banzai",
            "--re-semantic-token-limit",
            "9000000",
            "--re-semantic-time-limit-minutes",
            "720",
        ],
    )

    assert custom.exit_code == recommended.exit_code == banzai.exit_code == 0
    assert calls == [
        ReResumeRequest(answer="Use accepted timeout evidence."),
        ReResumeRequest(recommended=True),
        ReResumeRequest(
            banzai=True,
            re_semantic_token_limit=9000000,
            re_semantic_time_limit_minutes=720,
        ),
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "args",
    (
        ["re", "resume"],
        ["re", "resume", "Use option 1", "--recommended"],
        ["re", "resume", "Use option 1", "--banzai"],
        ["re", "resume", "--recommended", "--banzai"],
    ),
)
def test_re_resume_preserves_kernel_error_for_malformed_modes(args):
    from echelon.cli_app import app

    result = CliRunner().invoke(app, args, env={"COLUMNS": "200"})

    assert result.exit_code == 2
    assert result.output == (
        "\n"
        "╭─ ✈ echelon · RE v2 · ERROR ──────────────────────────────────────────────────╮\n"
        "│  ✗ COMMAND FAILED                                                            │\n"
        "╰──────────────────────────────────────────────────────────────────────────────╯\n"
        "\n"
        "  command\n"
        "  ───────\n"
        "  echelon re resume\n"
        "\n"
        "  error\n"
        "  ─────\n"
        '  exactly one resume mode is required: "<guidance>", '
        "--recommended, or --banzai\n"
        "\n"
    )


@pytest.mark.unit
def test_re_resume_help_explains_bounded_debt_acceptance() -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["re", "resume", "--help"],
        env={"COLUMNS": "200"},
    )
    normalized = " ".join(result.output.split())

    assert result.exit_code == 0
    assert "--recommended" in result.output
    assert "--banzai" in result.output
    assert "one automatic successor" in normalized
    assert "documented residual debt" in normalized
    assert "absolute L3 semantic token ceiling" in normalized
    assert "absolute L3 semantic active-time ceiling" in normalized
    assert "--re-semantic-token-limit" in result.output


@pytest.mark.unit
def test_quiet_is_accepted_after_a_nested_command_and_scoped_to_that_invocation(
    monkeypatch,
):
    """Removing --quiet during dispatch would leave provider diagnostics enabled."""
    from echelon.cli_app import run
    from harness.verbosity import is_verbose

    observed: list[tuple[str | None, bool]] = []
    monkeypatch.setattr(
        "echelon.spec_service.run_spec",
        lambda _root, request: observed.append((request.description, is_verbose())),
    )

    run(["spec", "run", "Describe the feature", "--quiet"])

    assert observed == [("Describe the feature", False)]
    assert is_verbose() is False


@pytest.mark.unit
def test_provider_diagnostics_are_enabled_by_default(monkeypatch):
    """An ordinary command should enable provider diagnostics."""
    from echelon.cli_app import run
    from harness.verbosity import is_verbose

    observed: list[bool] = []
    monkeypatch.setattr(
        "echelon.re_service.show_re_status",
        lambda _request: observed.append(is_verbose()),
    )

    run(["re", "status"])

    assert observed == [True]


@pytest.mark.unit
def test_root_help_documents_common_quiet_option() -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--quiet" in result.output


@pytest.mark.unit
def test_re_finalize_routes_explicit_partial_acknowledgement(monkeypatch):
    from echelon.cli_app import run
    from echelon.re_service import ReFinalizeRequest

    calls: list[ReFinalizeRequest] = []
    monkeypatch.setattr(
        "echelon.re_service.finalize_re",
        calls.append,
    )

    run(["re", "finalize", "re-123", "--allow-partial"])

    assert calls == [ReFinalizeRequest(run_id="re-123", allow_partial=True)]


@pytest.mark.unit
def test_re_synthesize_routes_partial_acknowledgement_and_budget(monkeypatch):
    from echelon.cli_app import run
    from echelon.re_service import ReSynthesizeRequest

    calls: list[ReSynthesizeRequest] = []
    monkeypatch.setattr(
        "echelon.re_service.synthesize_re",
        calls.append,
    )

    run(
        [
            "re",
            "synthesize",
            "re-123",
            "--allow-partial",
            "--re-token-limit",
            "1325000000",
        ]
    )

    assert calls == [
        ReSynthesizeRequest(
            run_id="re-123",
            allow_partial=True,
            re_token_limit=1325000000,
        )
    ]


@pytest.mark.unit
def test_re_execute_run_routes_to_deterministic_controller(monkeypatch):
    from echelon.cli_app import run

    calls: list[dict[str, str]] = []
    monkeypatch.setattr(
        "echelon.re_service.execute_re_run",
        lambda **kwargs: calls.append(kwargs),
    )

    run(["re", "execute-run", "spec-123"])

    assert calls == [{"run_id": "spec-123"}]


@pytest.mark.unit
def test_cli_does_not_expose_extension_backed_prosaic_export() -> None:
    result = invoke_help()

    assert result.exit_code == 0
    assert "prosaic" not in result.output


@pytest.mark.unit
def test_re_check_domain_routes_to_deterministic_gate(monkeypatch):
    from echelon.cli_app import run

    calls: list[dict[str, str]] = []
    monkeypatch.setattr(
        "echelon.re_service.check_re_domain",
        lambda **kwargs: calls.append(kwargs),
    )

    run(["re", "check-domain", "spec-123", "api", "001-re-api"])

    assert calls == [
        {
            "run_id": "spec-123",
            "source_id": "api",
            "domain_id": "001-re-api",
        }
    ]


@pytest.mark.unit
def test_re_publish_help_declares_manual_safety_flags():
    result = invoke_help("re", "publish")

    assert result.exit_code == 0
    assert "RUN_ID" in result.output
    assert "--allow-partial" in result.output
    assert "--commit" in result.output


@pytest.mark.unit
def test_re_help_exposes_explicit_one_source_refresh():
    group = invoke_help("re")
    refresh = invoke_help("re", "refresh")

    assert group.exit_code == 0
    assert "refresh" in group.output
    assert refresh.exit_code == 0
    assert "--source" in refresh.output


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
        "echelon.spec_service._cmd_rewind",
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
    from echelon.spec_service import SpecRetargetRequest

    calls: list[SpecRetargetRequest] = []
    monkeypatch.setattr(
        "echelon.spec_service.retarget_spec",
        lambda _root, request: calls.append(request),
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

    assert calls == [SpecRetargetRequest(
        spec_id="001-demo",
        targets=("apps/web", "services/api"),
        confirm_count=1,
    )]

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
    from echelon import spec_service as cli
    from echelon.spec_service import SpecRetargetRequest
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
    monkeypatch.setattr(cli, "_installed_phase_runtime_or_exit", lambda root: root / "ext")
    monkeypatch.setattr(
        cli,
        "_cmd_run",
        lambda args, project_root, ext_dir: calls.append((args, project_root, ext_dir)),
    )

    cli.retarget_spec(
        tmp_path,
        SpecRetargetRequest(
            spec_id="001-demo", targets=("apps/web",), confirm_count=1
        ),
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

    calls: list[tuple[Path, dict[str, object]]] = []
    monkeypatch.setattr(
        "echelon.spec_service.prepare_amendment",
        lambda project_root, **values: calls.append((project_root, values)),
    )

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

    assert calls == [(Path.cwd(), {
        "spec_id": "004-demo",
        "description": "Add requirement evidence",
        "input_values": (
            "requirement:sources/PBS-E-73.pdf",
            "reference:sources/PBS-E-73-figma-design.pdf",
        ),
        "dry_run": True,
        "extra_args": (),
    })]


@pytest.mark.unit
def test_spec_add_input_routes_product_inputs(monkeypatch):
    from echelon.cli_app import run

    calls: list[tuple[Path, tuple[str, ...]]] = []
    monkeypatch.setattr(
        "echelon.spec_service.add_input",
        lambda project_root, *, input_values: calls.append(
            (project_root, tuple(input_values))
        ),
    )

    run([
        "spec",
        "add-input",
        "--input",
        "reference:sources/DE-OPTA-SCHEMA-MAPPING",
        "--input",
        "reference:sources/DE-RESOLVER-BENCHMARK",
    ])

    assert calls == [(Path.cwd(), (
        "reference:sources/DE-OPTA-SCHEMA-MAPPING",
        "reference:sources/DE-RESOLVER-BENCHMARK",
    ))]


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

    calls: list[tuple[Path, dict[str, object]]] = []
    monkeypatch.setattr(
        "echelon.spec_service.prepare_amendment",
        lambda project_root, **values: calls.append((project_root, values)),
    )

    run(["spec", "amend", "status", "004-demo/001"])

    assert calls == [(Path.cwd(), {
        "spec_id": "status",
        "description": "004-demo/001",
        "input_values": (),
        "dry_run": False,
        "extra_args": (),
    })]


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
    from echelon.delivery_service import DeliveryRunRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.run_delivery",
        lambda project_root, request: calls.append((project_root, request)),
    )

    run([
        "delivery",
        "run",
        "001",
        "--mode",
        "banzai",
        "--strategy",
        "alternate",
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

    assert calls == [(
        Path.cwd(),
        DeliveryRunRequest(
            spec_id="001",
            mode="banzai",
            strategy="alternate",
            max_outer=3,
            max_inner=2,
            token_budget=1000,
            auto_merge=False,
            kill_losers=True,
            reset=True,
        ),
    )]


@pytest.mark.unit
def test_delivery_run_legacy_key_value_args_still_route(monkeypatch):
    from echelon.cli_app import run
    from echelon.delivery_service import DeliveryRunRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.run_delivery",
        lambda project_root, request: calls.append((project_root, request)),
    )

    run(["delivery", "run", "001", "mode=banzai", "strategy=alternate", "max_outer=3"])

    assert calls == [(
        Path.cwd(),
        DeliveryRunRequest(
            spec_id="001",
            extra_args=("mode=banzai", "strategy=alternate", "max_outer=3"),
        ),
    )]


@pytest.mark.unit
def test_delivery_run_canonical_flags_take_precedence_over_legacy_args(monkeypatch):
    from echelon.cli_app import run
    from echelon.delivery_service import DeliveryRunRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.run_delivery",
        lambda project_root, request: calls.append((project_root, request)),
    )

    run(["delivery", "run", "001", "mode=semi", "--mode", "banzai"])

    assert calls == [(
        Path.cwd(),
        DeliveryRunRequest(
            spec_id="001",
            extra_args=("mode=semi",),
            mode="banzai",
        ),
    )]


@pytest.mark.unit
def test_delivery_resume_canonical_flags_route_to_harness_resume(monkeypatch):
    from echelon.cli_app import run
    from echelon.delivery_service import DeliveryRecoveryRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.resume_delivery",
        lambda project_root, request: calls.append((project_root, request)),
    )

    run([
        "delivery",
        "resume",
        "001",
        "Use the direct mapping",
        "--mode",
        "banzai",
        "--strategy",
        "alternate",
    ])

    assert calls == [(
        Path.cwd(),
        DeliveryRecoveryRequest(
            spec_id="001",
            answer="Use the direct mapping",
            mode="banzai",
            strategy="alternate",
        ),
    )]


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
    from echelon.delivery_service import DeliveryRecoveryRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.continue_delivery",
        lambda project_root, request: calls.append((project_root, request)),
    )

    run(["delivery", "continue", "001", "--mode", "banzai", "--strategy", "alternate"])

    assert calls == [(
        Path.cwd(),
        DeliveryRecoveryRequest(
            spec_id="001",
            mode="banzai",
            strategy="alternate",
        ),
    )]


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
    from echelon.delivery_service import DeliveryLandRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.land_delivery",
        lambda project_root, request: calls.append((project_root, request)),
    )

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

    assert calls == [(
        Path.cwd(),
        DeliveryLandRequest(
            spec_id="001",
            continue_existing=True,
            prepare_only=True,
            autoresolve=False,
            allow_fulfillment_gaps=True,
            strategy="rebase",
        ),
    )]


@pytest.mark.unit
def test_typer_front_door_declares_all_top_level_commands():
    from echelon.cli_app import app
    from typer.main import get_command

    command = get_command(app)

    assert {
        "artifacts",
        "benchmark",
        "bugfix",
        "change",
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
        "topology",
        "verify-spec",
        "version",
        "wiki",
        "workspace",
    }.issubset(command.commands)
    assert "build" not in command.commands
    assert "cicd" not in command.commands


@pytest.mark.unit
def test_topology_help_declares_deterministic_read_commands_and_options():
    group = invoke_help("topology")

    assert group.exit_code == 0
    for command in (
        "audit",
        "list-sources",
        "search",
        "explain",
        "neighbors",
        "impact",
    ):
        assert command in group.output

    audit = invoke_help("topology", "audit")
    list_sources = invoke_help("topology", "list-sources")
    search = invoke_help("topology", "search")
    explain = invoke_help("topology", "explain")
    neighbors = invoke_help("topology", "neighbors")
    impact = invoke_help("topology", "impact")

    assert all(result.exit_code == 0 for result in (
        audit,
        list_sources,
        search,
        explain,
        neighbors,
        impact,
    ))
    assert "--source" in audit.output
    assert "--json" in audit.output
    assert "--json" in list_sources.output
    assert "QUERY" in search.output
    assert "--source" in search.output
    assert "--type" in search.output
    assert "--limit" in search.output
    assert "--json" in search.output
    assert "NODE" in explain.output
    assert "--source" in explain.output
    assert "--json" in explain.output
    assert "--direction" in neighbors.output
    assert "--relation" in neighbors.output
    assert "--limit" in neighbors.output
    assert "--json" in neighbors.output
    assert "--max-depth" in impact.output
    assert "--relation" in impact.output
    assert "--json" in impact.output


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
        "review",
        "verify-spec",
        "reopen",
        "bugfix",
        "change",
    ):
        assert command.commands[alias].hidden
    assert "build" not in command.commands
    assert "cicd" not in command.commands


@pytest.mark.unit
@pytest.mark.parametrize(
    ("argv", "target", "expected_args", "expected_kwargs"),
    (
        (
            ["harness", "run", "001", "--mode", "banzai"],
            "delivery_run",
            ("001",),
            {
                "mode": "banzai",
                "strategy": None,
                "max_outer": None,
                "max_inner": None,
                "token_budget": None,
                "auto_merge": None,
                "kill_losers": False,
                "reset": False,
            },
        ),
        (
            ["harness", "land", "001", "--continue"],
            "delivery_land",
            ("001",),
            {
                "continue_": True,
                "prepare_only": False,
                "no_autoresolve": False,
                "allow_fulfillment_gaps": False,
                "strategy": None,
            },
        ),
        (
            ["harness", "continue", "001"],
            "delivery_continue",
            ("001",),
            {"mode": None, "strategy": None},
        ),
        (
            ["harness", "resume", "001", "go"],
            "delivery_resume",
            ("001",),
            {"answer": "go", "mode": None, "strategy": None},
        ),
    ),
)
def test_harness_aliases_route_through_canonical_delivery_commands(
    monkeypatch, argv, target, expected_args, expected_kwargs
):
    from echelon import cli_app

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def canonical(_ctx, *args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(cli_app, target, canonical)
    result = CliRunner().invoke(cli_app.app, argv)

    assert result.exit_code == 0
    assert calls == [(expected_args, expected_kwargs)]


@pytest.mark.parametrize("command", ("build", "cicd"))
def test_retired_top_level_routes_are_absent(command):
    from echelon.cli_app import app

    result = CliRunner().invoke(app, [command])

    assert result.exit_code == 2
    assert "No such command" in result.output


@pytest.mark.parametrize(
    ("argv", "target", "expected_args", "expected_kwargs"),
    (
        (["artifacts", "001"], "spec_artifacts", ("001",), {}),
        (["status"], "spec_status", (), {}),
        (
            ["land", "001", "--continue", "--strategy", "merge"],
            "delivery_land",
            ("001",),
            {
                "continue_": True,
                "prepare_only": False,
                "no_autoresolve": False,
                "allow_fulfillment_gaps": False,
                "strategy": "merge",
            },
        ),
        (["continue", "--mode", "banzai"], "spec_continue", (), {"mode": "banzai"}),
        (
            ["rewind", "phase-2", "--commit", "abc", "--next-phase", "phase-3", "--confirm"],
            "spec_rewind",
            ("phase-2",),
            {"checkpoint_commit": "abc", "checkpoint_next_phase": "phase-3", "confirm": True},
        ),
        (["resume", "approved"], "spec_resume", (), {"answer": "approved"}),
        (
            ["run", "Write it", "--mode", "semi"],
            "spec_run",
            (),
            {
                "description": "Write it",
                "mode": "semi",
                "reset": False,
                "perfectionist": False,
                "init": False,
                "message": None,
                "next_phase": None,
                "target": None,
                "input_values": None,
                "ignore_re": False,
                "stash": False,
                "discard": False,
                "confirm": False,
            },
        ),
        (
            ["verify-spec", "001", "--reconcile", "--dry-run"],
            "spec_verify",
            ("001",),
            {"reconcile": True, "dry_run": True},
        ),
        (["reopen", "001", "from=report.json"], "spec_reopen", ("001",), {"report": "from=report.json"}),
        (["bugfix", "001", "Broken"], "spec_bugfix", ("001", "Broken"), {}),
        (["change", "001", "Different"], "spec_change", ("001", "Different"), {}),
    ),
)
def test_root_aliases_route_through_canonical_commands(
    monkeypatch, argv, target, expected_args, expected_kwargs
):
    from click import Context
    from echelon import cli_app

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def canonical(*args, **kwargs):
        if args and isinstance(args[0], Context):
            args = args[1:]
        calls.append((args, kwargs))

    monkeypatch.setattr(cli_app, target, canonical)
    result = CliRunner().invoke(cli_app.app, argv)

    assert result.exit_code == 0
    assert calls == [(expected_args, expected_kwargs)]


@pytest.mark.unit
def test_typer_run_prints_version_without_subcommand(capsys):
    from echelon.version import CLI_VERSION
    from echelon.cli_app import run

    run(["--version"])

    assert capsys.readouterr().out.strip() == f"echelon {CLI_VERSION}"


@pytest.mark.unit
@pytest.mark.parametrize("args", (["--version"], ["version"]))
def test_version_commands_bypass_legacy_cli(capsys, args):
    from echelon import cli_app

    assert not hasattr(cli_app, "_legacy_cli")
    cli_app.run(args)

    assert capsys.readouterr().out.strip() == "echelon 4.1.1"


@pytest.mark.unit
def test_spec_help_uses_typer_front_door():
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "--help"])
    normalized = " ".join(result.output.split())

    assert result.exit_code == 0
    assert "Usage: root spec [OPTIONS] COMMAND [ARGS]..." in result.output
    assert "Phase A/spec lifecycle commands" in result.output
    assert "Common forms:" in result.output
    assert "run <description> [--mode semi|banzai|guided] [--reset] [--perfectionist]" in normalized
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

    calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        "echelon.spec_service.show_targets",
        lambda project_root, *, spec_id: calls.append((project_root, spec_id)),
    )

    run(["spec", "targets", "001"])

    assert calls == [(Path.cwd(), "001")]


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

    calls: list[dict[str, object]] = []

    def record_status_command(
        *,
        spec_id: str = "",
        strategy: str = "",
        json_output: bool = False,
    ) -> None:
        calls.append(
            {
                "spec_id": spec_id,
                "strategy": strategy,
                "json_output": json_output,
            }
        )

    monkeypatch.setattr("echelon.delivery_status.command", record_status_command)

    run(["delivery", "status", "001", "--strategy", "alternate", "--json"])

    assert calls == [
        {
            "spec_id": "001",
            "strategy": "alternate",
            "json_output": True,
        }
    ]


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
def test_spec_run_typed_options_route_to_spec_service(monkeypatch):
    from echelon.cli_app import run
    from echelon.spec_service import SpecRunRequest

    calls: list[SpecRunRequest] = []
    monkeypatch.setattr(
        "echelon.spec_service.run_spec",
        lambda _root, request: calls.append(request),
    )

    run([
        "spec",
        "run",
        "Add archive export",
        "--mode",
        "banzai",
        "--reset",
        "--perfectionist",
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

    assert calls == [SpecRunRequest(
        description="Add archive export",
        mode="banzai",
        reset=True,
        perfectionist=True,
        init=True,
        message="include migration notes",
        next_phase="phase2-model",
        targets=("api", "web"),
        input_values=(
            "requirement:sources/PBS-E-45",
            "reference:sources/provision",
        ),
        ignore_re=True,
        stash=True,
    )]


@pytest.mark.unit
def test_spec_run_help_exposes_perfectionist_authoring_mode():
    result = invoke_help("spec", "run")
    normalized = " ".join(result.output.split())

    assert result.exit_code == 0
    assert "--perfectionist" in normalized
    assert "Cartographer" in normalized
    assert "authoring" in normalized


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
    assert "--legacy-spec-kit" not in result.output
    command = get_command(app)
    workspace_command = command.commands["workspace"]
    init_command = workspace_command.commands["init"]
    declared_options: set[str] = set()
    for param in init_command.params:
        declared_options.update(getattr(param, "opts", []))
        declared_options.update(getattr(param, "secondary_opts", []))
    assert "--allow-unsafe-host-execution" in declared_options
    assert "--no-unsafe-host-execution" in declared_options
    assert "--legacy-spec-kit" not in declared_options


@pytest.mark.unit
def test_spec_target_routes_to_service_rejection(monkeypatch):
    from echelon.cli_app import run

    calls: list[bool] = []
    monkeypatch.setattr(
        "echelon.spec_service.reject_target_mutation",
        lambda: calls.append(True),
    )

    run(["spec", "target", "001", "sources/api", "sources/web", "--init"])

    assert calls == [True]


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
    from harness.config import HarnessConfig

    target = tmp_path / "sources" / "prosaic"
    target.mkdir(parents=True)
    spec_dir = tmp_path / "specs" / "906-cli-output-styling"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\ntargets:\n  - sources/prosaic\n---\n# Spec\n",
        encoding="utf-8",
    )
    config = HarnessConfig(
        target_repo=str(target), target_default_branch="main", provider="docker"
    )
    resolved = SimpleNamespace(services=(), runnability=SimpleNamespace(policy="not_applicable"))
    provider = object()
    verifier = MagicMock()
    verifier.run.return_value = SimpleNamespace(
        status="refreshed", exit_code=0, ok=True,
        reason="full verify-spec completed",
        report_path=str(spec_dir / "fulfillment-report.md"),
        verified_ledger=None, verify_run_dir=tmp_path / "runs" / "verify",
        failure_class="",
    )
    verifier_type = MagicMock(return_value=verifier)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.prosaic_packages.install_prosaic_bundle", lambda _root: None)
    monkeypatch.setattr("harness.config.load_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr("harness.verification_stack_runtime.resolve_verification_stacks", lambda *_args: resolved)
    monkeypatch.setattr("harness.docker_provider.DockerWorktreeProvider", MagicMock(return_value=provider))
    monkeypatch.setattr("harness.authoritative_spec_verifier.AuthoritativeSpecVerifier", verifier_type)

    run(["spec", "verify", "906", "--reconcile"])

    assert verifier_type.call_args.kwargs["target"] == target.resolve()
    assert verifier_type.call_args.kwargs["spec_dir"] == spec_dir.resolve()
    assert verifier_type.call_args.kwargs["provider"] is provider
    verifier.run.assert_called_once_with(reconcile=True, dry_run=False)


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
    from harness.config import HarnessConfig

    spec_dir = tmp_path / "specs" / "906-cli-output-styling"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    config = HarnessConfig(
        target_repo=str(tmp_path), target_default_branch="main", provider="docker"
    )
    resolved = SimpleNamespace(services=(), runnability=SimpleNamespace(policy="not_applicable"))
    verifier = MagicMock()
    verifier.run.return_value = SimpleNamespace(
        status="failed", exit_code=1, ok=False,
        reason="artifact validation failed", report_path=None,
        verified_ledger=None, verify_run_dir=tmp_path / "runs" / "verify",
        failure_class="harness_error",
    )
    monkeypatch.setattr("echelon.prosaic_packages.install_prosaic_bundle", lambda _root: None)
    monkeypatch.setattr("harness.config.load_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr("harness.verification_stack_runtime.resolve_verification_stacks", lambda *_args: resolved)
    monkeypatch.setattr("harness.docker_provider.DockerWorktreeProvider", MagicMock())
    monkeypatch.setattr("harness.authoritative_spec_verifier.AuthoritativeSpecVerifier", MagicMock(return_value=verifier))

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
    review_help = invoke_help("review")
    verify_help = invoke_help("verify-spec")
    reopen_help = invoke_help("reopen")
    bugfix_help = invoke_help("bugfix")
    change_help = invoke_help("change")

    assert review_help.exit_code == 0
    assert "SPEC_ID" in review_help.output
    assert "--pr-url" in review_help.output
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
def test_retired_codegen_command_is_absent() -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["codegen", "--help"])

    assert result.exit_code != 0
    assert "No such command" in result.output


@pytest.mark.unit
def test_spec_status_routes_to_legacy_status(monkeypatch):
    from echelon.cli_app import run

    calls = []
    monkeypatch.setattr("echelon.spec_service._cmd_status", lambda project_root: calls.append(project_root))

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
