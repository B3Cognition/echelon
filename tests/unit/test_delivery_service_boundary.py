from pathlib import Path

from typer.testing import CliRunner


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
        lambda project_root, *, spec_id, strategy, extra_args=(): calls.append(
            (project_root, spec_id, strategy, tuple(extra_args))
        ),
    )
    result = CliRunner().invoke(
        app,
        ["delivery", "checkpoint", "list", "001-demo", "--strategy", "safe"],
    )
    assert result.exit_code == 0
    assert calls == [(Path.cwd(), "001-demo", "safe", ())]
