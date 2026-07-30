from __future__ import annotations

import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner

from echelon.cli_app import app


def _run(tmp_path):
    run = tmp_path / "runs/spec-1"
    run.mkdir(parents=True)
    (run / "state.json").write_text(
        json.dumps(
            {
                "run_id": "spec-1",
                "spec_id": "001-demo",
                "status": "done",
                "token_usage": 7,
                "created_at": "2026-07-20T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    return run


def test_spec_analyze_is_hidden_from_spec_help() -> None:
    result = CliRunner().invoke(app, ["spec", "--help"])
    assert result.exit_code == 0
    assert "analyze" not in result.output


def test_spec_analyze_accepts_one_run_path_and_json(tmp_path) -> None:
    run = _run(tmp_path)

    result = CliRunner().invoke(app, ["spec", "analyze", str(run), "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["workflow"] == "spec"
    assert payload["run_id"] == "spec-1"


def test_spec_analyze_rejects_non_spec_run(tmp_path) -> None:
    run = tmp_path / "runs/re-1"
    (run / "re").mkdir(parents=True)
    (run / "state.json").write_text(json.dumps({"run_id": "re-1"}), encoding="utf-8")
    (run / "re/state.json").write_text("{}", encoding="utf-8")

    result = CliRunner().invoke(app, ["spec", "analyze", str(run)])

    assert result.exit_code != 0
    assert "not a Spec run" in result.output


def test_spec_analyze_health_accepts_one_run_path_and_json(tmp_path) -> None:
    run = _run(tmp_path)

    result = CliRunner().invoke(
        app,
        ["spec", "analyze", str(run), "--health", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["workflow"] == "spec"
    assert payload["state"] == "INSUFFICIENT_DATA"
    assert payload["cohort"]["latest_run"] == "spec-1"
    assert payload["findings"][0]["code"] == "telemetry.dispatches_unavailable"


def test_spec_analyze_health_renders_directory_text(tmp_path) -> None:
    _run(tmp_path)
    second = tmp_path / "runs/spec-2"
    second.mkdir(parents=True)
    (second / "state.json").write_text(
        json.dumps(
            {
                "run_id": "spec-2",
                "spec_id": "001-demo",
                "status": "done",
                "created_at": "2026-07-21T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["spec", "analyze", str(tmp_path / "runs"), "--health"],
    )

    assert result.exit_code == 0
    assert "SPEC TELEMETRY HEALTH" in result.output
    assert "State: INSUFFICIENT_DATA" in result.output
    assert "Latest run: spec-2" in result.output


def test_spec_analyze_health_does_not_modify_run_inputs(tmp_path) -> None:
    run = _run(tmp_path)
    before = _file_hashes(run)

    result = CliRunner().invoke(
        app,
        ["spec", "analyze", str(run), "--health"],
    )

    assert result.exit_code == 0
    assert _file_hashes(run) == before


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
