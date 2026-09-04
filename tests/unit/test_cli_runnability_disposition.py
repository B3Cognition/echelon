from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harness.runnability_evidence import RunnabilityStage, write_runnability_report


def _workspace(tmp_path: Path, *, status: str = "not_runnable") -> tuple[Path, Path]:
    spec_dir = tmp_path / "specs" / "003-browser-game"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Browser game\n", encoding="utf-8")
    evidence = (
        tmp_path
        / "runs"
        / "targets"
        / "browser-game"
        / "runs"
        / "build-1"
        / "evidence"
        / "user-runnability"
    )
    ref = write_runnability_report(
        evidence_dir=evidence,
        spec_id=spec_dir.name,
        target_id="sources/game",
        strategy_id="default",
        build_id="build-1",
        candidate_commit="a" * 40,
        candidate_fingerprint="product-1",
        contract_hash="contract-1",
        stack_hash="stack-1",
        status=status,
        failure_class="readiness_failed" if status != "runnable" else "",
        summary="The local app did not become ready." if status != "runnable" else "Passed.",
        stages=(
            RunnabilityStage(
                name="readiness",
                status="failed" if status != "runnable" else "passed",
                exit_code=1 if status != "runnable" else 0,
            ),
        ),
        required_stages=("readiness",),
        attempt_sequence=1,
        sensitive_environment={},
        user_commands={},
    )
    return spec_dir, ref.path.parent / "report.json"


@pytest.mark.unit
def test_spec_defer_runnability_discovers_failed_report_and_writes_owner_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec_dir, report = _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        [
            "spec",
            "defer-runnability",
            "003",
            "--reason",
            "Provisioning is explicitly scheduled as a follow-up.",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "RUNNABILITY DEFERRED" in result.output
    assert "target: sources/game" in result.output
    assert f"evidence: {report.resolve()}" in result.output
    assert "proposal:" in result.output
    ledger = json.loads(
        (spec_dir / "runnability-disposition.json").read_text(encoding="utf-8")
    )
    assert ledger["events"][-1]["status"] == "deferred"


@pytest.mark.unit
def test_spec_plan_runnability_restores_required_current_spec_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    from echelon.cli_app import app

    runner = CliRunner()
    deferred = runner.invoke(
        app,
        [
            "spec",
            "defer-runnability",
            "003",
            "--reason",
            "Provisioning is explicitly scheduled as a follow-up.",
        ],
    )
    planned = runner.invoke(app, ["spec", "plan-runnability", "003"])

    assert deferred.exit_code == 0, deferred.output
    assert planned.exit_code == 0, planned.output
    assert "RUNNABILITY PLANNED" in planned.output
    assert "current-spec blocking restored" in planned.output


@pytest.mark.unit
def test_spec_defer_runnability_rejects_missing_report_without_writing_ledger(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec_dir = tmp_path / "specs" / "003-browser-game"
    spec_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["spec", "defer-runnability", "003", "--reason", "Owner approved."],
    )

    assert result.exit_code == 2
    assert "no user-runnability report found" in result.output.lower()
    assert not (spec_dir / "runnability-disposition.json").exists()


@pytest.mark.unit
def test_spec_defer_runnability_rejects_latest_runnable_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec_dir, _report = _workspace(tmp_path, status="runnable")
    monkeypatch.chdir(tmp_path)
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["spec", "defer-runnability", "003", "--reason", "Owner approved."],
    )

    assert result.exit_code == 2
    assert "failed current report" in result.output.lower()
    assert not (spec_dir / "runnability-disposition.json").exists()
