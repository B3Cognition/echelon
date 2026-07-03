from __future__ import annotations

import subprocess

import pytest

from echelon import cli


def _write_workspace_config(project_dir, deploy_block: str) -> None:
    config = project_dir / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "deploy:\n" + deploy_block + "\n",
        encoding="utf-8",
    )


def test_http_deploy_preflight_skips_when_docker_missing(capsys) -> None:
    ready = cli._preflight_deploy_runtime(
        {"type": "http"},
        which=lambda _name: None,
    )

    assert ready is False
    captured = capsys.readouterr()
    assert "HTTP deploy initialization skipped" in captured.err
    assert "docker command not found on PATH" in captured.err
    assert "workspace init will continue" in captured.err
    assert "ECHELON_CONTAINER_CLI=podman echelon delivery init" in captured.err
    assert "Traefik setup currently expects Docker" in captured.err


def test_http_deploy_preflight_skips_when_docker_daemon_unreachable(capsys) -> None:
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["docker", "info"],
            returncode=1,
            stderr="Cannot connect to the Docker daemon",
        )

    ready = cli._preflight_deploy_runtime(
        {"type": "http"},
        which=lambda _name: "/usr/local/bin/docker",
        run=fake_run,
    )

    assert ready is False
    captured = capsys.readouterr()
    assert "Docker CLI found, but the Docker daemon is not reachable" in captured.err
    assert "Cannot connect to the Docker daemon" in captured.err
    assert "install/start docker" in captured.err.lower()


def test_cli_deploy_skips_http_deploy_runtime_preflight() -> None:
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("docker runtime should not be checked for deploy.type=cli")

    ready = cli._preflight_deploy_runtime(
        {"type": "cli"},
        which=fail_if_called,
        run=fail_if_called,
    )

    assert ready is True


def test_workspace_init_continues_when_http_deploy_runtime_unavailable(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _write_workspace_config(
        tmp_path,
        "  type: http\n  blue_port: 18080\n  green_port: 18081\n",
    )
    monkeypatch.setattr(cli, "_preflight_deploy_runtime", lambda _deploy: False)
    monkeypatch.setattr(cli, "_provision_wing", lambda _project_dir, _config: "test-wing")

    cli._cmd_init(tmp_path)

    captured = capsys.readouterr()
    assert "ECHELON INIT — COMPLETE" in captured.out
    assert "skipped (Docker unavailable)" in captured.out
    assert "deploy-init.sh not found" not in captured.err


def test_workspace_init_skips_deploy_when_disabled(tmp_path, monkeypatch, capsys) -> None:
    _write_workspace_config(
        tmp_path,
        "  enabled: false\n  type: http\n  blue_port: 18080\n  green_port: 18081\n",
    )
    monkeypatch.setattr(
        cli,
        "_preflight_deploy_runtime",
        lambda _deploy: pytest.fail("deploy runtime should not be checked when disabled"),
    )
    monkeypatch.setattr(cli, "_provision_wing", lambda _project_dir, _config: "test-wing")

    cli._cmd_init(tmp_path)

    captured = capsys.readouterr()
    assert "ECHELON INIT — COMPLETE" in captured.out
    assert "skipped (deploy.enabled=false)" in captured.out


def test_http_deploy_preflight_accepts_ready_docker() -> None:
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["docker", "info"], returncode=0)

    ready = cli._preflight_deploy_runtime(
        {"type": "http"},
        which=lambda _name: "/usr/local/bin/docker",
        run=fake_run,
    )

    assert ready is True
