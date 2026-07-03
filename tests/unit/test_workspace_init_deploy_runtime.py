from __future__ import annotations

import subprocess

import pytest

from echelon import cli


def test_http_deploy_preflight_blocks_when_docker_missing(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli._preflight_deploy_runtime(
            {"type": "http"},
            which=lambda _name: None,
        )

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Docker is required for HTTP deploy initialization" in captured.err
    assert "docker command not found on PATH" in captured.err
    assert "ECHELON_CONTAINER_CLI=podman echelon delivery init" in captured.err
    assert "Traefik setup currently expects Docker" in captured.err


def test_http_deploy_preflight_blocks_when_docker_daemon_unreachable(capsys) -> None:
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["docker", "info"],
            returncode=1,
            stderr="Cannot connect to the Docker daemon",
        )

    with pytest.raises(SystemExit) as exc_info:
        cli._preflight_deploy_runtime(
            {"type": "http"},
            which=lambda _name: "/usr/local/bin/docker",
            run=fake_run,
        )

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Docker CLI found, but the Docker daemon is not reachable" in captured.err
    assert "Cannot connect to the Docker daemon" in captured.err
    assert "Install/start Docker" in captured.err


def test_cli_deploy_skips_http_deploy_runtime_preflight() -> None:
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("docker runtime should not be checked for deploy.type=cli")

    cli._preflight_deploy_runtime(
        {"type": "cli"},
        which=fail_if_called,
        run=fail_if_called,
    )


def test_http_deploy_preflight_accepts_ready_docker() -> None:
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["docker", "info"], returncode=0)

    cli._preflight_deploy_runtime(
        {"type": "http"},
        which=lambda _name: "/usr/local/bin/docker",
        run=fake_run,
    )
