from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml


def test_workspace_init_accepts_openai_compatible_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_workspace

    calls: list[dict[str, object]] = []

    def fake_init(
        project_root,
        *,
        allow_unsafe_host_execution=False,
        llm_cli=None,
        openai_base_url=None,
        openai_model=None,
        openai_api_key_file=None,
        openai_api_key_env=None,
    ):
        calls.append(
            {
                "project_root": project_root,
                "allow_unsafe_host_execution": allow_unsafe_host_execution,
                "llm_cli": llm_cli,
                "openai_base_url": openai_base_url,
                "openai_model": openai_model,
                "openai_api_key_file": openai_api_key_file,
                "openai_api_key_env": openai_api_key_env,
            }
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.cli._cmd_init", fake_init)
    monkeypatch.setattr("echelon.cli._wants_unsafe_host_execution_interactively", lambda: False)

    _cmd_workspace(["init", "--llm", "openai-compatible", "--no-unsafe-host-execution"])

    assert calls == [
        {
            "project_root": tmp_path,
            "allow_unsafe_host_execution": False,
            "llm_cli": "openai-compatible",
            "openai_base_url": None,
            "openai_model": None,
            "openai_api_key_file": None,
            "openai_api_key_env": None,
        }
    ]


def test_workspace_init_accepts_openai_compatible_endpoint_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_workspace

    calls: list[dict[str, object]] = []

    def fake_init(
        project_root,
        *,
        allow_unsafe_host_execution=False,
        llm_cli=None,
        openai_base_url=None,
        openai_model=None,
        openai_api_key_file=None,
        openai_api_key_env=None,
    ):
        calls.append(
            {
                "project_root": project_root,
                "allow_unsafe_host_execution": allow_unsafe_host_execution,
                "llm_cli": llm_cli,
                "openai_base_url": openai_base_url,
                "openai_model": openai_model,
                "openai_api_key_file": openai_api_key_file,
                "openai_api_key_env": openai_api_key_env,
            }
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.cli._cmd_init", fake_init)
    monkeypatch.setattr("echelon.cli._wants_unsafe_host_execution_interactively", lambda: False)

    _cmd_workspace(
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
    )

    assert calls == [
        {
            "project_root": tmp_path,
            "allow_unsafe_host_execution": False,
            "llm_cli": "openai-compatible",
            "openai_base_url": "http://127.0.0.1:8000/v1",
            "openai_model": "ThinkingCap-Qwen3.6-27B-OptiQ-4bit",
            "openai_api_key_file": "~/.omlx_token",
            "openai_api_key_env": "OMLX_API_KEY",
        }
    ]


def test_workspace_doctor_exits_clean_for_valid_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / ".gitignore").write_text("/.specify/\n/runs/\n/app/\n", encoding="utf-8")
    (tmp_path / ".specify").mkdir()
    (tmp_path / "specs").mkdir()
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n  git_role: orchestration\nsources:\n  - id: app\n    path: app\n",
        encoding="utf-8",
    )
    (tmp_path / "app").mkdir()
    monkeypatch.chdir(tmp_path)

    from echelon.cli import _cmd_workspace

    _cmd_workspace(["doctor"])

    out = capsys.readouterr().out
    assert "Buildable: yes" in out
    assert "Findings: none" in out


def test_workspace_doctor_exits_nonzero_for_invalid_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / ".specify").mkdir()
    monkeypatch.chdir(tmp_path)

    from echelon.cli import _cmd_workspace

    with pytest.raises(SystemExit) as exc:
        _cmd_workspace(["doctor"])

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "workspace_not_git_backed" in out
    assert "canonical_config_missing" in out


def test_workspace_migrate_command_applies_legacy_config_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / ".specify" / "extensions" / "echelon").mkdir(parents=True)
    (tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml").write_text(
        "verify_command: pytest\n",
        encoding="utf-8",
    )
    (tmp_path / "specs" / "001-demo").mkdir(parents=True)
    (tmp_path / "specs" / "001-demo" / "spec.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    from echelon.cli import _cmd_workspace

    with pytest.raises(SystemExit) as exc:
        _cmd_workspace(["migrate", "--write"])

    assert exc.value.code == 0
    assert (tmp_path / ".echelon" / "config.yml").read_text(encoding="utf-8") == (
        "verify_command: pytest\n"
    )
    out = capsys.readouterr().out
    assert "canonical_config_copied: True" in out


def test_workspace_sources_sync_write_updates_config_from_sources_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n"
        "  git_role: orchestration\n"
        "sources:\n"
        "  - id: stale\n"
        "    path: sources/stale\n"
        "  - id: external\n"
        "    path: vendor/external\n",
        encoding="utf-8",
    )
    for source_id in ("api", "web"):
        source = tmp_path / "sources" / source_id
        source.mkdir(parents=True)
        (source / "package.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    from echelon.cli import _cmd_workspace

    _cmd_workspace(["sources", "sync", "--write"])

    out = capsys.readouterr().out
    assert "added: api, web" in out
    assert "removed: stale" in out
    config = yaml.safe_load((tmp_path / ".echelon" / "config.yml").read_text(encoding="utf-8"))
    assert config["sources"] == [
        {"id": "external", "path": "vendor/external"},
        {"id": "api", "path": "sources/api"},
        {"id": "web", "path": "sources/web"},
    ]


def test_workspace_sources_sync_dry_run_leaves_config_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / ".echelon").mkdir()
    config_path = tmp_path / ".echelon" / "config.yml"
    original_config = "workspace:\n  git_role: orchestration\nsources: []\n"
    config_path.write_text(original_config, encoding="utf-8")
    source = tmp_path / "sources" / "optasearch-pro"
    source.mkdir(parents=True)
    (source / "package.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    from echelon.cli import _cmd_workspace

    _cmd_workspace(["sources", "sync"])

    out = capsys.readouterr().out
    assert "Dry run: yes" in out
    assert "added: optasearch-pro" in out
    assert config_path.read_text(encoding="utf-8") == original_config


def test_workspace_sources_sync_normalizes_path_only_sources_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / ".echelon").mkdir()
    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.write_text(
        "workspace:\n"
        "  git_role: orchestration\n"
        "sources:\n"
        "  - path: sources/api\n",
        encoding="utf-8",
    )
    source = tmp_path / "sources" / "api"
    source.mkdir(parents=True)
    (source / "package.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    from echelon.cli import _cmd_workspace

    _cmd_workspace(["sources", "sync", "--write"])

    out = capsys.readouterr().out
    assert "added: none" in out
    assert "removed: none" in out
    assert "unchanged: api" in out
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config["sources"] == [{"id": "api", "path": "sources/api"}]
