from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

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


def test_workspace_init_uses_prosaic_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_workspace

    calls: list[dict[str, object]] = []

    def fake_init(project_root, **kwargs):
        calls.append({"project_root": project_root, **kwargs})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.cli._cmd_init", fake_init)
    monkeypatch.setattr("echelon.cli._wants_unsafe_host_execution_interactively", lambda: False)

    _cmd_workspace(["init", "--no-unsafe-host-execution"])

    assert calls == [
        {
            "project_root": tmp_path,
            "allow_unsafe_host_execution": False,
            "llm_cli": None,
            "openai_base_url": None,
            "openai_model": None,
            "openai_api_key_file": None,
            "openai_api_key_env": None,
        }
    ]


def test_workspace_init_rejects_legacy_spec_kit_escape_hatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_workspace

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.cli._wants_unsafe_host_execution_interactively", lambda: False)

    with pytest.raises(SystemExit) as raised:
        _cmd_workspace(["init", "--legacy-spec-kit", "--no-unsafe-host-execution"])

    assert raised.value.code == 1
    assert "unknown option '--legacy-spec-kit'" in capsys.readouterr().err


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


def test_phase_runtime_guard_accepts_complete_prosaic_workspace(tmp_path: Path) -> None:
    from echelon.cli import _installed_phase_runtime_or_exit

    workflow = tmp_path / ".echelon/runtime/workflow"
    subagents = tmp_path / ".echelon/prosaic/subagents"
    workflow.mkdir(parents=True)
    subagents.mkdir(parents=True)
    (tmp_path / ".specify/extensions/echelon").mkdir(parents=True)
    source_definition = Path(__file__).resolve().parents[2] / "runtime/workflow/definition.yaml"
    (workflow / "definition.yaml").write_bytes(source_definition.read_bytes())
    (workflow / "controller-state-contracts.yaml").write_bytes(
        source_definition.with_name("controller-state-contracts.yaml").read_bytes()
    )

    assert _installed_phase_runtime_or_exit(tmp_path) == workflow.parent


def test_phase_runtime_guard_rejects_workflow_missing_checkpoint_policies(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _installed_phase_runtime_or_exit

    workflow = tmp_path / ".echelon/runtime/workflow"
    subagents = tmp_path / ".echelon/prosaic/subagents"
    workflow.mkdir(parents=True)
    subagents.mkdir(parents=True)
    source_definition = Path(__file__).resolve().parents[2] / "runtime/workflow/definition.yaml"
    (workflow / "controller-state-contracts.yaml").write_bytes(
        source_definition.with_name("controller-state-contracts.yaml").read_bytes()
    )
    definition = yaml.safe_load(source_definition.read_text(encoding="utf-8"))
    for phase in definition["phases"]:
        phase.pop("checkpoint", None)
        phase.pop("rewind", None)
    (workflow / "definition.yaml").write_text(
        yaml.safe_dump(definition, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(SystemExit) as exc:
        _installed_phase_runtime_or_exit(tmp_path)

    assert exc.value.code == 1
    assert "echelon workspace migrate-to-prosaic" in capsys.readouterr().err


def test_phase_runtime_guard_rejects_workflow_missing_compatibility_version(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _installed_phase_runtime_or_exit

    workflow = tmp_path / ".echelon/runtime/workflow"
    subagents = tmp_path / ".echelon/prosaic/subagents"
    workflow.mkdir(parents=True)
    subagents.mkdir(parents=True)
    source_definition = Path(__file__).resolve().parents[2] / "runtime/workflow/definition.yaml"
    (workflow / "controller-state-contracts.yaml").write_bytes(
        source_definition.with_name("controller-state-contracts.yaml").read_bytes()
    )
    definition = yaml.safe_load(source_definition.read_text(encoding="utf-8"))
    definition.pop("controller_runtime_compatibility_version", None)
    (workflow / "definition.yaml").write_text(
        yaml.safe_dump(definition, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(SystemExit) as exc:
        _installed_phase_runtime_or_exit(tmp_path)

    assert exc.value.code == 1
    assert "compatibility" in capsys.readouterr().err


def test_spec_run_rejects_v1_runtime_before_provider_or_run_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_spec_run

    workflow = tmp_path / ".echelon/runtime/workflow"
    subagents = tmp_path / ".echelon/prosaic/subagents"
    workflow.mkdir(parents=True)
    subagents.mkdir(parents=True)
    source_definition = (
        Path(__file__).resolve().parents[2]
        / "runtime/workflow/definition.yaml"
    )
    definition = yaml.safe_load(source_definition.read_text(encoding="utf-8"))
    definition["controller_runtime_compatibility_version"] = 1
    (workflow / "definition.yaml").write_text(
        yaml.safe_dump(definition, sort_keys=False),
        encoding="utf-8",
    )
    (workflow / "controller-state-contracts.yaml").write_bytes(
        source_definition.with_name("controller-state-contracts.yaml").read_bytes()
    )
    (tmp_path / ".echelon/config.yml").write_text(
        "harness:\n  llm:\n    cli: codex\n",
        encoding="utf-8",
    )
    initialized_target = tmp_path / "generated-target"
    provider_calls: list[str] = []
    run_calls: list[str] = []

    def fake_provider(*_args, **_kwargs) -> None:
        provider_calls.append("provider")

    def fake_run(*_args, **_kwargs) -> None:
        run_calls.append("run")
        initialized_target.mkdir()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.cli._require_provider_capability", fake_provider)
    monkeypatch.setattr("echelon.cli._cmd_run", fake_run)

    with pytest.raises(SystemExit) as exc:
        _cmd_spec_run(["Write Hello World"])

    assert exc.value.code == 1
    assert provider_calls == []
    assert run_calls == []
    assert not initialized_target.exists()


def test_phase_runtime_guard_rejects_legacy_extension_only_workspace(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _installed_phase_runtime_or_exit

    (tmp_path / ".specify/extensions/echelon/workflow").mkdir(parents=True)

    with pytest.raises(SystemExit) as exc:
        _installed_phase_runtime_or_exit(tmp_path)

    assert exc.value.code == 1
    assert "echelon workspace migrate-to-prosaic" in capsys.readouterr().err


def test_workspace_migrate_to_prosaic_preserves_config_and_validates_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy_config = tmp_path / ".specify/extensions/echelon/echelon-config.yml"
    legacy_config.parent.mkdir(parents=True)
    legacy_config.write_text("verify_command: pytest\n", encoding="utf-8")

    def deploy_bundle(project_root: Path) -> object:
        workflow = project_root / ".echelon/runtime/workflow"
        subagents = project_root / ".echelon/prosaic/subagents"
        workflow.mkdir(parents=True)
        subagents.mkdir(parents=True)
        (workflow / "definition.yaml").write_text(
            "phases:\n  - id: discover\n    type: agent\n    agent: echelon.scout\n",
            encoding="utf-8",
        )
        (subagents / "echelon.scout.md").write_text("# Scout\n", encoding="utf-8")
        return object()

    monkeypatch.setattr("echelon.prosaic_packages.install_prosaic_bundle", deploy_bundle)
    disabled: list[Path] = []
    monkeypatch.setattr(
        "echelon.speckit_git.disable_speckit_git",
        lambda root: disabled.append(root) or SimpleNamespace(installed=True),
    )

    from echelon.cli import _cmd_workspace_migrate_to_prosaic

    _cmd_workspace_migrate_to_prosaic(tmp_path)

    assert (tmp_path / ".echelon/config.yml").read_text(encoding="utf-8") == "verify_command: pytest\n"
    assert "/.echelon/re/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "/.echelon/prosaic/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "/.prosaic-manifest.json" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "/.prosaic-backups/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert disabled == [tmp_path]
    assert "Prosaic migration complete" in capsys.readouterr().out


def test_workspace_migrate_to_prosaic_normalizes_legacy_re_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / ".echelon/config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "re:\n  output:\n    directory: .specify/echelon/re\n",
        encoding="utf-8",
    )

    def deploy_bundle(project_root: Path) -> object:
        workflow = project_root / ".echelon/runtime/workflow"
        subagents = project_root / ".echelon/prosaic/subagents"
        workflow.mkdir(parents=True)
        subagents.mkdir(parents=True)
        (workflow / "definition.yaml").write_text(
            "phases:\n  - id: discover\n    type: agent\n    agent: echelon.scout\n",
            encoding="utf-8",
        )
        (subagents / "echelon.scout.md").write_text("# Scout\n", encoding="utf-8")
        return object()

    monkeypatch.setattr("echelon.prosaic_packages.install_prosaic_bundle", deploy_bundle)

    from echelon.cli import _cmd_workspace_migrate_to_prosaic

    _cmd_workspace_migrate_to_prosaic(tmp_path)

    text = config.read_text(encoding="utf-8")
    assert ".echelon/re" in text
    assert ".specify/echelon/re" not in text


def test_workspace_migrate_to_prosaic_migrates_global_deploy_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "deployed-app"
    home = tmp_path / "home"
    config = project / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text("harness:\n  provider: docker\n", encoding="utf-8")
    legacy_state = home / ".speckit-deploy" / "deployed-app.json"
    legacy_state.parent.mkdir(parents=True)
    legacy_state.write_text(
        json.dumps(
            {
                "app": "deployed-app",
                "type": "http",
                "active": "blue",
                "global_state_dir": str(legacy_state.parent),
                "traefik_name": "speckit-traefik",
                "deploy_network": "speckit-deploy",
            }
        ),
        encoding="utf-8",
    )

    def deploy_bundle(project_root: Path) -> object:
        workflow = project_root / ".echelon/runtime/workflow"
        subagents = project_root / ".echelon/prosaic/subagents"
        workflow.mkdir(parents=True)
        subagents.mkdir(parents=True)
        (workflow / "definition.yaml").write_text(
            "phases:\n  - id: discover\n    type: agent\n    agent: echelon.scout\n",
            encoding="utf-8",
        )
        (subagents / "echelon.scout.md").write_text("# Scout\n", encoding="utf-8")
        return object()

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("echelon.prosaic_packages.install_prosaic_bundle", deploy_bundle)
    monkeypatch.setattr(
        "echelon.speckit_git.disable_speckit_git",
        lambda _root: SimpleNamespace(installed=False),
    )

    from echelon.cli import _cmd_workspace_migrate_to_prosaic

    _cmd_workspace_migrate_to_prosaic(project)

    migrated = home / ".echelon" / "deploy" / "deployed-app.json"
    assert migrated.is_file()
    assert not legacy_state.exists()
    assert f"deployment state: {migrated}" in capsys.readouterr().out
