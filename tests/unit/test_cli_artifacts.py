"""Unit tests for 'echelon artifacts' CLI command."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def _setup_spec(tmp_path: Path) -> Path:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
    (spec_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
    return spec_dir


def _run_artifacts(tmp_path: Path, args: list[str]) -> int:
    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        from echelon.spec_service import write_artifacts

        try:
            if not args:
                from echelon.cli_app import app
                from typer.testing import CliRunner

                return CliRunner().invoke(app, ["spec", "artifacts"]).exit_code
            write_artifacts(tmp_path, spec_id=args[0], extra_args=args[1:])
            return 0
        except SystemExit as e:
            return int(e.code) if e.code is not None else 0
    finally:
        os.chdir(orig)


@pytest.mark.unit
def test_artifacts_command_writes_index(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec_dir = _setup_spec(tmp_path)

    rc = _run_artifacts(tmp_path, ["001"])

    captured = capsys.readouterr()
    assert rc == 0
    assert (spec_dir / "ARTIFACTS.md").exists()
    assert "Wrote artifact map" in captured.out


@pytest.mark.unit
def test_artifacts_command_requires_spec_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = _run_artifacts(tmp_path, [])

    assert rc == 2


@pytest.mark.unit
def test_artifacts_command_reports_missing_spec(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = _run_artifacts(tmp_path, ["999"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "Spec not found" in captured.err
