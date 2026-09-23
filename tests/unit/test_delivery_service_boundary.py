import ast
import inspect
from pathlib import Path
import textwrap

import pytest
from typer.testing import CliRunner


ACTIVE_DELIVERY_FUNCTIONS = {
    "delivery_init",
    "delivery_target",
    "delivery_verify_local",
    "delivery_cleanup_local",
    "delivery_run",
    "delivery_resume",
    "delivery_continue",
    "delivery_land",
    "delivery_checkpoint_list",
}

REMOVED_HANDLERS = {
    "_cmd_land",
    "_cmd_harness_init",
    "_cmd_delivery_target",
    "_cmd_harness_run",
    "_cmd_harness_resume",
    "_cmd_harness_continue",
    "_cmd_delivery_verify_local",
    "_cmd_delivery_cleanup_local",
    "_cmd_delivery_checkpoint",
    "_outer_cap_delivery_action",
}


def test_delivery_init_routes_extra_args_to_service(monkeypatch):
    from echelon.cli_app import app

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.initialize_delivery",
        lambda project_root, *, extra_args=(): calls.append(
            (project_root, tuple(extra_args))
        ),
    )
    result = CliRunner().invoke(app, ["delivery", "init", "provider=claude"])
    assert result.exit_code == 0
    assert calls == [(Path.cwd(), ("provider=claude",))]


def test_delivery_target_routes_spec_id_to_service(monkeypatch):
    from echelon.cli_app import app

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.prepare_target",
        lambda project_root, *, spec_id: calls.append((project_root, spec_id)),
    )
    result = CliRunner().invoke(app, ["delivery", "target", "001-demo"])
    assert result.exit_code == 0
    assert calls == [(Path.cwd(), "001-demo")]


def test_delivery_verify_local_routes_immutable_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.delivery_service import LocalVerificationRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.verify_local",
        lambda project_root, request: calls.append((project_root, request)),
    )
    result = CliRunner().invoke(
        app,
        [
            "delivery", "verify-local", "001-demo", "--target", "api",
            "--engine", "podman", "--yes", "--keep-on-failure",
        ],
    )
    assert result.exit_code == 0
    assert calls == [(
        Path.cwd(),
        LocalVerificationRequest(
            spec_id="001-demo",
            target_id="api",
            engine="podman",
            assume_yes=True,
            keep_on_failure=True,
        ),
    )]


def test_delivery_cleanup_local_routes_run_id(monkeypatch):
    from echelon.cli_app import app

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.cleanup_local",
        lambda project_root, *, local_run_id: calls.append(
            (project_root, local_run_id)
        ),
    )
    result = CliRunner().invoke(app, ["delivery", "cleanup-local", "local-123"])
    assert result.exit_code == 0
    assert calls == [(Path.cwd(), "local-123")]


def test_delivery_checkpoint_list_routes_typed_values(monkeypatch):
    from echelon.cli_app import app

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.list_checkpoints",
        lambda project_root, *, spec_id, extra_args=(): calls.append(
            (project_root, spec_id, tuple(extra_args))
        ),
    )
    result = CliRunner().invoke(
        app,
        ["delivery", "checkpoint", "list", "001-demo"],
    )
    assert result.exit_code == 0
    assert calls == [(Path.cwd(), "001-demo", ())]


def test_delivery_run_routes_immutable_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.delivery_service import DeliveryRunRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.run_delivery",
        lambda project_root, request: calls.append((project_root, request)),
    )
    result = CliRunner().invoke(
        app,
        [
            "delivery", "run", "001-demo", "legacy=value",
            "--mode", "banzai",
            "--max-outer", "4", "--max-inner", "2",
            "--token-budget", "9000", "--no-auto-merge",
            "--reset",
        ],
    )
    assert result.exit_code == 0
    assert calls == [(
        Path.cwd(),
        DeliveryRunRequest(
            spec_id="001-demo",
            extra_args=("legacy=value",),
            mode="banzai",
            max_outer=4,
            max_inner=2,
            token_budget=9000,
            auto_merge=False,
            reset=True,
        ),
    )]


def test_delivery_resume_routes_answer_and_options(monkeypatch):
    from echelon.cli_app import app
    from echelon.delivery_service import DeliveryRecoveryRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.resume_delivery",
        lambda project_root, request: calls.append((project_root, request)),
    )
    result = CliRunner().invoke(
        app,
        ["delivery", "resume", "001-demo", "Use option 1", "--mode", "semi"],
    )
    assert result.exit_code == 0
    assert calls == [(
        Path.cwd(),
        DeliveryRecoveryRequest(
            spec_id="001-demo",
            answer="Use option 1",
            mode="semi",
        ),
    )]


def test_delivery_continue_routes_answerless_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.delivery_service import DeliveryRecoveryRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.continue_delivery",
        lambda project_root, request: calls.append((project_root, request)),
    )
    result = CliRunner().invoke(
        app,
        ["delivery", "continue", "001-demo", "--mode", "banzai"],
    )
    assert result.exit_code == 0
    assert calls == [(
        Path.cwd(),
        DeliveryRecoveryRequest(spec_id="001-demo", mode="banzai"),
    )]


def test_delivery_land_routes_immutable_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.delivery_service import DeliveryLandRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.land_delivery",
        lambda project_root, request: calls.append((project_root, request)),
    )
    result = CliRunner().invoke(
        app,
        [
            "delivery", "land", "001-demo", "legacy=value", "--continue",
            "--prepare-only", "--no-autoresolve",
            "--allow-fulfillment-gaps", "--strategy", "rebase",
        ],
    )
    assert result.exit_code == 0
    assert calls == [(
        Path.cwd(),
        DeliveryLandRequest(
            spec_id="001-demo",
            extra_args=("legacy=value",),
            continue_existing=True,
            prepare_only=True,
            autoresolve=False,
            allow_fulfillment_gaps=True,
            strategy="rebase",
        ),
    )]


def test_active_delivery_surfaces_do_not_import_legacy_cli():
    import echelon.cli_app as cli_app
    import echelon.delivery_status as delivery_status

    for name in ACTIVE_DELIVERY_FUNCTIONS:
        source = textwrap.dedent(inspect.getsource(getattr(cli_app, name)))
        assert "echelon import cli" not in source
        assert "echelon.cli import" not in source
    status_source = inspect.getsource(delivery_status)
    assert "echelon import cli" not in status_source
    assert "echelon.cli import" not in status_source


def test_legacy_cli_does_not_define_delivery_handlers():
    from echelon import cli

    tree = ast.parse(inspect.getsource(cli))
    definitions = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert definitions.isdisjoint(REMOVED_HANDLERS)


def test_land_delivery_roots_config_and_gitops_in_supplied_project(
    monkeypatch,
    tmp_path,
):
    from echelon.delivery_service import DeliveryLandRequest, land_delivery

    project_root = tmp_path / "project"
    other_root = tmp_path / "other"
    project_root.mkdir()
    other_root.mkdir()
    monkeypatch.chdir(other_root)

    config = object()
    load_calls = []
    gitops_calls = []
    land_calls = []
    monkeypatch.setattr(
        "echelon.cli._require_provider_capability",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("echelon.cli._banner", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "echelon.delivery_service._dispatch_land_to_spec_targets",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "echelon.delivery_service._archive_squad_run",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "harness.config.load_config",
        lambda **kwargs: load_calls.append(kwargs) or config,
    )
    monkeypatch.setattr(
        "harness.gitops.GitOpsManager",
        lambda loaded, *, base_dir=None: gitops_calls.append(
            (loaded, base_dir)
        ) or object(),
    )
    monkeypatch.setattr(
        "harness.land.land",
        lambda spec_id, **kwargs: land_calls.append((spec_id, kwargs)) or True,
    )

    with pytest.raises(SystemExit) as exc_info:
        land_delivery(project_root, DeliveryLandRequest(spec_id="001-demo"))

    assert exc_info.value.code == 0
    assert load_calls == [{"project_root": project_root}]
    assert gitops_calls == [(config, str(project_root))]
    assert land_calls[0][0] == "001-demo"
    assert land_calls[0][1]["project_dir"] == project_root


def test_continue_delivery_rejects_answer():
    from echelon.delivery_service import DeliveryRecoveryRequest, continue_delivery

    with pytest.raises(
        ValueError,
        match="^delivery continue does not accept an answer$",
    ):
        continue_delivery(
            Path.cwd(),
            DeliveryRecoveryRequest(spec_id="001-demo", answer="Use option 1"),
        )


@pytest.mark.parametrize("entry_point", ["run_delivery", "resume_delivery", "continue_delivery"])
def test_execution_capability_gate_uses_supplied_project_root(
    monkeypatch, tmp_path, entry_point,
):
    from echelon import delivery_service
    from harness.provider_capability import ProviderCapability

    project_root = tmp_path / "project"
    other_root = tmp_path / "other"
    project_root.mkdir()
    other_root.mkdir()
    monkeypatch.chdir(other_root)
    calls = []

    class CapabilityGateReached(Exception):
        pass

    def capability_gate(command_name, required, *, project_dir=None):
        calls.append((command_name, required, project_dir))
        raise CapabilityGateReached

    monkeypatch.setattr("echelon.cli._require_provider_capability", capability_gate)
    request_type = (
        delivery_service.DeliveryRunRequest
        if entry_point == "run_delivery"
        else delivery_service.DeliveryRecoveryRequest
    )
    with pytest.raises(CapabilityGateReached):
        getattr(delivery_service, entry_point)(
            project_root, request_type(spec_id="001-demo"),
        )

    command = entry_point.removesuffix("_delivery")
    assert calls == [(f"echelon delivery {command}", ProviderCapability.BUILD, project_root)]


def test_legacy_cli_does_not_retain_delivery_only_helpers():
    from echelon import cli

    moved_helpers = {
        "_print_harness_config_error",
        "HarnessWorkspaceTarget",
        "_apply_target_verify_command_detection",
        "_block_if_spec_task_targets_mismatch",
        "_format_missing_verify_command_resume_message",
        "_resolve_harness_workspace_target",
        "_source_dispatch_metadata",
        "_sync_polyrepo_runtime_extension",
        "_workspace_target_dispatch_metadata",
    }
    assert moved_helpers.isdisjoint(vars(cli))
