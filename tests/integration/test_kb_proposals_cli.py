"""Integration tests for `echelon kb` CLI commands."""

from __future__ import annotations

from typer.testing import CliRunner

from echelon.cli_app import app


runner = CliRunner()


def test_kb_validate_reports_missing_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["kb", "validate", "--run-id", "squad-001"])

    assert result.exit_code == 0
    assert "proposals: 0" in result.stdout
    assert "status: degraded" in result.stdout


def test_kb_apply_writes_report_for_empty_run(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["kb", "apply", "--run-id", "squad-001"])

    assert result.exit_code == 0
    assert (tmp_path / "runs" / "squad-001" / "kb-apply-report.yaml").exists()
    assert "kb_apply_status: degraded" in result.stdout


def test_kb_apply_reports_degraded_for_mixed_apply_outcomes(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    proposal_dir = tmp_path / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (tmp_path / "runs" / "squad-001" / "reasoning-journal.jsonl").write_text(
        '{"id":"RJ-001","claim":"supported"}\n',
        encoding="utf-8",
    )
    (tmp_path / "knowledge-base").mkdir()
    (tmp_path / "knowledge-base" / "patterns.yaml").write_text(
        "schema_version: 1\nentries: []\n", encoding="utf-8"
    )
    (proposal_dir / "accepted.yaml").write_text(
        """schema_version: 1
proposal_id: kb-prop-0001
proposal_type: pattern
run_id: squad-001
agent: speckit-echelon-mirror
created_at: \"2026-07-17T12:00:00Z\"
targets: [knowledge-base/patterns.yaml]
confidence: 0.72
source_artifacts: [runs/squad-001/reasoning-journal.jsonl]
evidence_refs:
  - artifact: runs/squad-001/reasoning-journal.jsonl
    locator: RJ-001
    claim: Supported by review.
payload:
  name: Constraint first
  domain: planning
  description: Use constraints before estimates.
  tags: [planning]
  status: active
  project_fingerprint: auto
  scope: local_only
""",
        encoding="utf-8",
    )
    (proposal_dir / "rejected.yaml").write_text("schema_version: [", encoding="utf-8")

    result = runner.invoke(app, ["kb", "apply", "--run-id", "squad-001"])

    assert result.exit_code == 0
    assert "kb_apply_status: degraded" in result.stdout
    assert "accepted: 1" in result.stdout
    assert "rejected: 1" in result.stdout


def test_kb_validate_reports_missing_source_artifact(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    proposal_dir = tmp_path / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "missing-artifact.yaml").write_text(
        """schema_version: 1
proposal_id: kb-prop-0001
proposal_type: pattern
run_id: squad-001
agent: speckit-echelon-mirror
created_at: "2026-07-17T12:00:00Z"
targets: [knowledge-base/patterns.yaml]
source_artifacts: [runs/squad-001/reasoning-journal.jsonl]
evidence_refs:
  - artifact: runs/squad-001/reasoning-journal.jsonl
    locator: RJ-001
    claim: Supported by review.
payload:
  name: Constraint first
  domain: planning
  description: Use constraints before estimates.
  tags: [planning]
  status: active
  project_fingerprint: auto
  scope: local_only
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["kb", "validate", "--run-id", "squad-001"])

    assert result.exit_code == 0
    assert "kb_validation_status: degraded" in result.stdout
    assert "invalid: 1" in result.stdout
