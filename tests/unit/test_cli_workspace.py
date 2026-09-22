from __future__ import annotations

import json
import subprocess
from contextlib import chdir
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner

from echelon.cli_app import app


def _invoke_workspace(project_root: Path, args: list[str]):
    with chdir(project_root):
        return CliRunner().invoke(app, ["workspace", *args])


def _reject_legacy_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_legacy_cli():
        raise AssertionError("workspace commands must not load echelon.cli")

    monkeypatch.setattr("echelon.cli_app._legacy_cli", fail_legacy_cli)


@pytest.mark.unit
def test_workspace_doctor_bypasses_legacy_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reject_legacy_workspace(monkeypatch)

    result = _invoke_workspace(tmp_path, ["doctor"])

    assert result.exit_code == 1
    assert "workspace_not_git_backed" in result.output
    assert "canonical_config_missing" in result.output


@pytest.mark.unit
def test_workspace_sources_sync_bypasses_legacy_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n  git_role: orchestration\nsources: []\n",
        encoding="utf-8",
    )
    source = tmp_path / "sources" / "api"
    source.mkdir(parents=True)
    (source / "package.json").write_text("{}\n", encoding="utf-8")
    _reject_legacy_workspace(monkeypatch)

    result = _invoke_workspace(tmp_path, ["sources", "sync"])

    assert result.exit_code == 0, result.output
    assert "Dry run: yes" in result.output
    assert "added: api" in result.output


@pytest.mark.unit
def test_workspace_migrate_bypasses_legacy_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = tmp_path / ".specify" / "extensions" / "echelon"
    legacy.mkdir(parents=True)
    (legacy / "echelon-config.yml").write_text(
        "verify_command: pytest\n",
        encoding="utf-8",
    )
    (tmp_path / "specs").mkdir()
    _reject_legacy_workspace(monkeypatch)

    result = _invoke_workspace(tmp_path, ["migrate", "--write"])

    assert result.exit_code == 0, result.output
    assert "canonical_config_copied: True" in result.output
    assert (tmp_path / ".echelon" / "config.yml").is_file()


@pytest.mark.unit
def test_workspace_init_bypasses_legacy_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / ".echelon" / "config.yml"
    config.parent.mkdir()
    config.write_text(
        "deploy:\n  enabled: false\n  type: cli\n",
        encoding="utf-8",
    )
    _reject_legacy_workspace(monkeypatch)

    result = _invoke_workspace(
        tmp_path,
        ["init", "--llm", "codex", "--no-unsafe-host-execution"],
    )

    assert result.exit_code == 0, result.output
    assert "ECHELON INIT — COMPLETE" in result.output
    loaded = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert loaded["harness"]["llm"]["cli"] == "codex"


@pytest.mark.unit
def test_workspace_migrate_to_prosaic_bypasses_legacy_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / ".echelon" / "config.yml"
    config.parent.mkdir()
    config.write_text("deploy:\n  enabled: false\n  type: cli\n", encoding="utf-8")
    _reject_legacy_workspace(monkeypatch)

    result = _invoke_workspace(tmp_path, ["migrate-to-prosaic"])

    assert result.exit_code == 0, result.output
    assert "Prosaic migration complete" in result.output
    assert (tmp_path / ".echelon" / "runtime" / "workflow" / "definition.yaml").is_file()


def test_workspace_init_rejects_legacy_spec_kit_escape_hatch(
    tmp_path: Path,
) -> None:
    result = _invoke_workspace(
        tmp_path,
        ["init", "--legacy-spec-kit", "--no-unsafe-host-execution"],
    )

    assert result.exit_code == 1
    assert "unknown option '--legacy-spec-kit'" in result.output

def test_workspace_doctor_exits_clean_for_valid_workspace(
    tmp_path: Path,
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
    result = _invoke_workspace(tmp_path, ["doctor"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert "Buildable: yes" in out
    assert "Findings: none" in out


def test_workspace_doctor_exits_nonzero_for_invalid_workspace(
    tmp_path: Path,
) -> None:
    (tmp_path / ".specify").mkdir()
    result = _invoke_workspace(tmp_path, ["doctor"])

    assert result.exit_code == 1
    out = result.output
    assert "workspace_not_git_backed" in out
    assert "canonical_config_missing" in out


def test_workspace_migrate_command_applies_legacy_config_copy(
    tmp_path: Path,
) -> None:
    (tmp_path / ".specify" / "extensions" / "echelon").mkdir(parents=True)
    (tmp_path / ".specify" / "extensions" / "echelon" / "echelon-config.yml").write_text(
        "verify_command: pytest\n",
        encoding="utf-8",
    )
    (tmp_path / "specs" / "001-demo").mkdir(parents=True)
    (tmp_path / "specs" / "001-demo" / "spec.md").write_text("# Demo\n", encoding="utf-8")
    result = _invoke_workspace(tmp_path, ["migrate", "--write"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".echelon" / "config.yml").read_text(encoding="utf-8") == (
        "verify_command: pytest\n"
    )
    out = result.output
    assert "canonical_config_copied: True" in out


def test_workspace_sources_sync_write_updates_config_from_sources_directory(
    tmp_path: Path,
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
    result = _invoke_workspace(tmp_path, ["sources", "sync", "--write"])

    assert result.exit_code == 0, result.output
    out = result.output
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
) -> None:
    (tmp_path / ".echelon").mkdir()
    config_path = tmp_path / ".echelon" / "config.yml"
    original_config = "workspace:\n  git_role: orchestration\nsources: []\n"
    config_path.write_text(original_config, encoding="utf-8")
    source = tmp_path / "sources" / "optasearch-pro"
    source.mkdir(parents=True)
    (source / "package.json").write_text("{}\n", encoding="utf-8")
    result = _invoke_workspace(tmp_path, ["sources", "sync"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert "Dry run: yes" in out
    assert "added: optasearch-pro" in out
    assert config_path.read_text(encoding="utf-8") == original_config


def test_workspace_sources_sync_normalizes_path_only_sources_entries(
    tmp_path: Path,
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
    result = _invoke_workspace(tmp_path, ["sources", "sync", "--write"])

    assert result.exit_code == 0, result.output
    out = result.output
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
    (workflow / "definition.yaml").write_text(
        "controller_runtime_compatibility_version: 3\n"
        "phases:\n"
        "  - id: complete\n"
        "    type: terminal\n"
        "    checkpoint: none\n"
        "    rewind: none\n"
        "    allowed_state_updates: []\n"
        "    transitions: []\n",
        encoding="utf-8",
    )

    assert _installed_phase_runtime_or_exit(tmp_path) == workflow.parent


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

    from echelon.workspace_service import migrate_to_prosaic

    migrate_to_prosaic(tmp_path)

    assert (tmp_path / ".echelon/config.yml").read_text(encoding="utf-8") == "verify_command: pytest\n"
    assert "/.echelon/re/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "/.echelon/re-v2/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
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

    from echelon.workspace_service import migrate_to_prosaic

    migrate_to_prosaic(tmp_path)

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

    from echelon.workspace_service import migrate_to_prosaic

    migrate_to_prosaic(project)

    migrated = home / ".echelon" / "deploy" / "deployed-app.json"
    assert migrated.is_file()
    assert not legacy_state.exists()
    assert f"deployment state: {migrated}" in capsys.readouterr().out
