from __future__ import annotations

import json

from typer.testing import CliRunner

from echelon.cli_app import app


def _run(tmp_path):
    run = tmp_path / "runs/spec-1"
    run.mkdir(parents=True)
    (run / "state.json").write_text(
        json.dumps({"run_id": "spec-1", "spec_id": "001-demo", "status": "done", "token_usage": 7}),
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
