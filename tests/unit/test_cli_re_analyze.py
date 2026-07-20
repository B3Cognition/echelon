from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from echelon.cli_app import app


pytestmark = pytest.mark.unit


def _run(root: Path, run_id: str = "re-1") -> Path:
    run = root / run_id
    (run / "re/workspace").mkdir(parents=True)
    (run / "state.json").write_text(
        json.dumps({"run_id": run_id, "run_kind": "re", "status": "blocked"}),
        encoding="utf-8",
    )
    (run / "re/state.json").write_text(
        json.dumps({"run_id": run_id, "status": "blocked", "re_source_states": {}}),
        encoding="utf-8",
    )
    return run


def test_re_analyze_is_callable_but_hidden_from_re_help(tmp_path: Path) -> None:
    _run(tmp_path)
    runner = CliRunner()

    help_result = runner.invoke(app, ["re", "--help"])
    result = runner.invoke(
        app,
        ["re", "analyze", str(tmp_path), "--run-id", "re-1", "--format", "json"],
    )

    assert "analyze" not in help_result.output
    assert result.exit_code == 0
    assert json.loads(result.output)["schema_version"] == 1


def test_re_analyze_accepts_concrete_run_directory(tmp_path: Path) -> None:
    run = _run(tmp_path)

    result = CliRunner().invoke(
        app,
        ["re", "analyze", str(run), "--format", "json"],
    )

    assert result.exit_code == 0
    report = json.loads(result.output)
    assert report["run_id"] == "re-1"


def test_admin_catalog_is_hidden_but_lists_diagnostics() -> None:
    runner = CliRunner()

    assert "admin" not in runner.invoke(app, ["--help"]).output
    result = runner.invoke(app, ["admin", "commands"])

    assert result.exit_code == 0
    assert "echelon re analyze" in result.output


def test_re_analyze_rejects_unsafe_run_id(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["re", "analyze", str(tmp_path), "--run-id", "../escape"],
    )

    assert result.exit_code == 2
    assert "unsafe run id" in result.output
