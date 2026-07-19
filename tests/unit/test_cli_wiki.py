from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from echelon.cli_app import app, run


def _write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _workspace(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / ".echelon/config.yml",
        {"sources": [], "wiki": {"auto_refresh": True}},
    )
    spec = tmp_path / "specs/001-demo"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text(
        "---\nstatus: phase_a\n---\n# Demo\n\n- **FR-001** Work.\n",
        encoding="utf-8",
    )
    (spec / "plan.md").write_text("# Plan\n", encoding="utf-8")
    (spec / "tasks.md").write_text("# Tasks\n\n- [ ] T-001 Work\n", encoding="utf-8")


@pytest.mark.unit
def test_wiki_build_prints_home_and_optional_obsidian_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path)
    subprocess.run(["git", "init", "-b", "master"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Echelon Tests"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "echelon@example.test"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=tmp_path, check=True)

    result = CliRunner().invoke(app, ["wiki", "build"])

    assert result.exit_code == 0
    assert ".echelon/runtime/wiki/Home.md" in result.output
    assert "Obsidian" in result.output
    assert "optional" in result.output.lower()
    assert "https://obsidian.md/download" in result.output
    assert "Catalog: master@" in result.output


@pytest.mark.unit
def test_wiki_status_and_clean_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path)
    runner = CliRunner()

    assert runner.invoke(app, ["wiki", "status"]).output.startswith("State: absent")
    assert runner.invoke(app, ["wiki", "build"]).exit_code == 0
    assert runner.invoke(app, ["wiki", "status"]).output.startswith("State: fresh")
    cleaned = runner.invoke(app, ["wiki", "clean"])
    assert cleaned.exit_code == 0
    assert "Removed:" in cleaned.output
    assert runner.invoke(app, ["wiki", "clean"]).output.startswith("Wiki is absent")


@pytest.mark.unit
def test_read_only_command_does_not_refresh_preexisting_stale_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path)
    run(["wiki", "build"])
    (tmp_path / "specs/001-demo/spec.md").write_text(
        "# External change\n", encoding="utf-8"
    )
    manifest = tmp_path / ".echelon/runtime/wiki/manifest.json"
    before = manifest.read_bytes()

    run(["wiki", "status"])

    assert manifest.read_bytes() == before


@pytest.mark.unit
def test_successful_command_that_changes_inputs_refreshes_existing_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path)
    run(["wiki", "build"])

    def mutate(_args: list[str]) -> None:
        (tmp_path / "specs/001-demo/spec.md").write_text(
            "# Changed by command\n", encoding="utf-8"
        )

    monkeypatch.setattr("echelon.cli._cmd_artifacts", mutate)

    run(["spec", "artifacts", "001"])

    projection = tmp_path / ".echelon/runtime/wiki/Artifacts/specs/001-demo/spec.md"
    assert "Changed by command" in projection.read_text(encoding="utf-8")


@pytest.mark.unit
def test_failed_command_does_not_attempt_auto_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _workspace(tmp_path)
    run(["wiki", "build"])
    calls: list[object] = []
    monkeypatch.setattr(
        "echelon.wiki.service.refresh_after_changed_command",
        lambda *_args, **_kwargs: calls.append(object()),
    )

    with pytest.raises(SystemExit):
        run(["spec", "artifacts", "999"])

    assert calls == []
