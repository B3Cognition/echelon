from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


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
