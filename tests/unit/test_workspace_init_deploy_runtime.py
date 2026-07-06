from __future__ import annotations

import subprocess
import sys

import pytest
import yaml

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
    assert "deploy.enabled: false" in captured.err
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
    assert "deploy.enabled=false written" in captured.out
    assert "skipped (deploy.enabled=false)" in captured.out
    assert "deploy-init.sh not found" not in captured.err
    config = yaml.safe_load((tmp_path / ".echelon" / "config.yml").read_text(encoding="utf-8"))
    assert config["deploy"]["enabled"] is False


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


def test_workspace_init_persists_selected_llm_provider(tmp_path, monkeypatch, capsys) -> None:
    _write_workspace_config(
        tmp_path,
        "  enabled: false\n  type: http\n  blue_port: 18080\n  green_port: 18081\n",
    )
    monkeypatch.setenv("ECHELON_LLM", "codex")
    monkeypatch.setattr(cli, "_provision_wing", lambda _project_dir, _config: "test-wing")

    cli._cmd_init(tmp_path)

    captured = capsys.readouterr()
    assert "ECHELON INIT — COMPLETE" in captured.out
    config = yaml.safe_load((tmp_path / ".echelon" / "config.yml").read_text(encoding="utf-8"))
    assert config["harness"]["llm"]["cli"] == "codex"


def test_workspace_init_llm_option_overrides_template_default(tmp_path, monkeypatch, capsys) -> None:
    config = tmp_path / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "deploy:\n"
        "  enabled: false\n"
        "  type: http\n"
        "  blue_port: 18080\n"
        "  green_port: 18081\n"
        "harness:\n"
        "  llm:\n"
        "    cli: claude\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_provision_wing", lambda _project_dir, _config: "test-wing")

    cli._cmd_workspace(["init", "--llm", "codex", "--no-unsafe-host-execution"])

    captured = capsys.readouterr()
    assert "LLM provider configured: codex" in captured.out
    loaded = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert loaded["harness"]["llm"]["cli"] == "codex"
    assert not (tmp_path / ".echelon" / "local.yml").exists()


def test_workspace_init_rejects_invalid_llm_option(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        cli._cmd_workspace(["init", "--llm", "kubernetes"])

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert "invalid --llm" in captured.err


@pytest.mark.parametrize("llm_cli", ["opencode", "copilot"])
def test_workspace_init_persists_additional_llm_providers(tmp_path, monkeypatch, capsys, llm_cli: str) -> None:
    _write_workspace_config(
        tmp_path,
        "  enabled: false\n  type: http\n  blue_port: 18080\n  green_port: 18081\n",
    )
    monkeypatch.setenv("ECHELON_LLM", llm_cli)
    monkeypatch.setattr(cli, "_provision_wing", lambda _project_dir, _config: "test-wing")

    cli._cmd_init(tmp_path)

    captured = capsys.readouterr()
    assert "ECHELON INIT — COMPLETE" in captured.out
    config = yaml.safe_load((tmp_path / ".echelon" / "config.yml").read_text(encoding="utf-8"))
    assert config["harness"]["llm"]["cli"] == llm_cli


def test_workspace_init_flag_writes_local_unsafe_host_execution_policy(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _write_workspace_config(
        tmp_path,
        "  enabled: false\n  type: http\n  blue_port: 18080\n  green_port: 18081\n",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_provision_wing", lambda _project_dir, _config: "test-wing")

    cli._cmd_workspace(["init", "--allow-unsafe-host-execution"])

    captured = capsys.readouterr()
    assert "host tool execution approval written" in captured.out
    local = yaml.safe_load((tmp_path / ".echelon" / "local.yml").read_text(encoding="utf-8"))
    policy = local["harness"]["llm"]["tool_policy"]
    assert policy["allow_unsafe_host_execution"] is True
    assert "workspace init" in policy["approval_reason"]
    assert "/.echelon/local.yml" in (tmp_path / ".gitignore").read_text(encoding="utf-8")


def test_workspace_init_interactive_yes_writes_local_unsafe_host_execution_policy(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _write_workspace_config(
        tmp_path,
        "  enabled: false\n  type: http\n  blue_port: 18080\n  green_port: 18081\n",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_provision_wing", lambda _project_dir, _config: "test-wing")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")

    cli._cmd_workspace(["init"])

    captured = capsys.readouterr()
    assert "host tool execution approval written" in captured.out
    local = yaml.safe_load((tmp_path / ".echelon" / "local.yml").read_text(encoding="utf-8"))
    policy = local["harness"]["llm"]["tool_policy"]
    assert policy["allow_unsafe_host_execution"] is True


def test_http_deploy_preflight_accepts_ready_docker() -> None:
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["docker", "info"], returncode=0)

    ready = cli._preflight_deploy_runtime(
        {"type": "http"},
        which=lambda _name: "/usr/local/bin/docker",
        run=fake_run,
    )

    assert ready is True
