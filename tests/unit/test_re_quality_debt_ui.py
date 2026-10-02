from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner


@pytest.fixture
def debt_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    run = tmp_path / "runs" / "re-quality-debt"
    quality = run / "re" / "quality" / "sources"
    quality.mkdir(parents=True)
    (tmp_path / "runs" / ".current-re").write_text(run.name + "\n")
    (run / "state.json").write_text(json.dumps({
        "status": "blocked", "blocked_reason": "re_source_quality_debt: api",
        "extraction_complete": True,
    }))
    (run / "re" / "state.json").write_text(json.dumps({
        "status": "done", "phase": "re-extract-7-constitute",
        "re_workspace_synthesis_complete": False,
        "re_source_order": ["api"],
        "re_source_states": {"api": {"status": "partial_quality_debt", "coverage_pct": 100}},
        "re_source_budgets": {
            "max_source_cycles": 2, "max_domain_repairs": 3, "max_source_reanalysis": 2,
        },
    }))
    (quality / "api.json").write_text(json.dumps({
        "source_id": "api", "passed": False, "coverage_pct": 100,
        "eligible_file_count": 2, "covered_file_count": 2,
        "orphan_paths": [], "domain_failures": [],
        "semantic_failures": [{
            "domain_id": "001-re-api", "reason": "semantic_quality_incomplete",
            "semantic_findings": ["Timeout behavior is misstated.", "Header citations are incomplete."],
            "semantic_finding_records": [
                {"finding_id": "ref-one", "text": "Timeout behavior is misstated."},
                {"finding_id": "ref-two", "text": "Header citations are incomplete."},
            ],
        }],
    }))
    workspace = run / "re" / "workspace"
    workspace.mkdir()
    (workspace / "overview.md").write_text("# Workspace draft\n")
    monkeypatch.chdir(tmp_path)
    return run


@pytest.mark.unit
def test_status_explains_semantic_debt_despite_complete_file_coverage(debt_run: Path) -> None:
    from echelon.cli_app import app

    before = {path: path.read_bytes() for path in debt_run.rglob("*") if path.is_file()}
    result = CliRunner().invoke(app, ["re", "status"])

    assert result.exit_code == 0
    assert "file coverage" in result.output.lower()
    assert "100.0%" in result.output
    assert "2 semantic findings" in result.output
    assert "001-re-api" in result.output
    assert "Timeout behavior is misstated." in result.output
    assert str(debt_run / "re" / "quality" / "sources" / "api.json") in result.output
    assert "not quality-approved" in result.output
    assert "file coverage does not mean" in result.output.lower()
    assert "echelon re continue --re-max-inner 4" in result.output
    assert "echelon re finalize re-quality-debt --allow-partial" in result.output
    assert "echelon re publish re-quality-debt --allow-partial" in result.output
    assert before == {path: path.read_bytes() for path in debt_run.rglob("*") if path.is_file()}


@pytest.mark.unit
def test_final_blocker_exposes_the_same_debt_and_commands(debt_run: Path, capsys) -> None:
    from echelon.cli import _print_re_lifecycle_result

    with pytest.raises(SystemExit) as error:
        _print_re_lifecycle_result(SimpleNamespace(
            status="blocked", run_id=debt_run.name,
            blocked_reason="re_source_quality_debt: api", phase="re-extract-7-constitute",
        ))
    output = capsys.readouterr().err
    assert error.value.code == 1
    assert "2 semantic findings" in output
    assert "001-re-api" in output
    assert "Timeout behavior is misstated." in output
    assert "echelon re continue --re-max-inner 4" in output
    assert "Resolve the blocker, then" not in output


@pytest.mark.unit
def test_status_does_not_call_missing_debt_reports_zero_findings(debt_run: Path) -> None:
    from echelon.cli_app import app

    (debt_run / "re" / "quality" / "sources" / "api.json").unlink()
    result = CliRunner().invoke(app, ["re", "status"])
    assert result.exit_code == 0
    assert "report unavailable" in result.output.lower()
    assert "0 semantic findings" not in result.output


@pytest.mark.unit
def test_structural_debt_is_not_hidden_by_semantic_counts(debt_run: Path) -> None:
    from echelon.cli_app import app

    report_path = debt_run / "re" / "quality" / "sources" / "api.json"
    report = json.loads(report_path.read_text())
    report["orphan_paths"] = ["src/uncovered.ts"]
    report["domain_failures"] = [{
        "domain_id": "002-re-other", "reason": "deep_spec_incomplete",
        "missing_sections": ["Edge Cases"],
    }]
    report_path.write_text(json.dumps(report))
    result = CliRunner().invoke(app, ["re", "status"])
    assert result.exit_code == 0
    assert "src/uncovered.ts" in result.output
    assert "002-re-other" in result.output
    assert "Edge Cases" in result.output
    assert "2 semantic findings" in result.output


@pytest.mark.unit
@pytest.mark.parametrize("reason,show_repair", [
    ("re_source_quality_debt: api", True), ("provider_authentication_failed", False),
])
def test_stopped_controller_only_offers_debt_repair_for_a_quality_blocker(
    debt_run: Path, reason: str, show_repair: bool,
) -> None:
    from echelon.cli_app import app

    inner_path = debt_run / "re" / "state.json"
    inner = json.loads(inner_path.read_text())
    inner.update(status="blocked", blocked_reason=reason)
    inner_path.write_text(json.dumps(inner))
    result = CliRunner().invoke(app, ["re", "status"])
    assert result.exit_code == 0
    assert ("echelon re continue --re-max-inner 4" in result.output) is show_repair
    assert ("echelon re finalize re-quality-debt --allow-partial" in result.output) is show_repair


@pytest.mark.unit
def test_accepted_debt_does_not_offer_a_new_repair_or_finalization(debt_run: Path) -> None:
    from echelon.cli_app import app

    outer_path = debt_run / "state.json"
    outer = json.loads(outer_path.read_text())
    outer.update(finalized_partial=True, golddigger_status="partial", publication_complete=True)
    outer_path.write_text(json.dumps(outer))
    result = CliRunner().invoke(app, ["re", "status"])
    assert result.exit_code == 0
    assert "2 semantic findings" in result.output
    assert "accepted, not resolved" in result.output
    assert "No continuation is required" in result.output
    assert "echelon re continue --re-max-inner" not in result.output


@pytest.mark.unit
def test_record_only_debt_has_bounded_terminal_safe_examples(debt_run: Path) -> None:
    from echelon.cli_app import app

    report_path = debt_run / "re" / "quality" / "sources" / "api.json"
    report = json.loads(report_path.read_text())
    failure = report["semantic_failures"][0]
    failure.pop("semantic_findings")
    failure["semantic_finding_records"][0]["text"] = "Unsupported claim.\x1b[2J " + "x" * 500
    report_path.write_text(json.dumps(report))
    result = CliRunner().invoke(app, ["re", "status"])
    assert result.exit_code == 0
    assert "2 semantic findings" in result.output
    assert "Unsupported claim." in result.output
    assert "\x1b" not in result.output
    assert "x" * 500 not in result.output


@pytest.mark.unit
def test_generated_synthesis_does_not_imply_quality_approval_with_source_debt(debt_run: Path) -> None:
    from echelon.cli_app import app

    inner_path = debt_run / "re" / "state.json"
    inner = json.loads(inner_path.read_text())
    inner["re_workspace_synthesis_complete"] = True
    inner_path.write_text(json.dumps(inner))
    result = CliRunner().invoke(app, ["re", "status"])
    assert result.exit_code == 0
    assert "not quality-approved" in result.output
