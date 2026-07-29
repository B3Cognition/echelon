from pathlib import Path
import json

import pytest
from typer.testing import CliRunner


@pytest.mark.unit
def test_spec_evidence_publish_outputs_package_summary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from echelon.mempalace_spec_evidence import SpecEvidencePublishReport

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_spec_evidence.publish_spec_evidence_package",
        lambda project_root, spec_selector, run_id=None, allow_unlanded=False: SpecEvidencePublishReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            evidence_dir=str(tmp_path / "specs" / "003-demo" / "evidence"),
            source_run_dir=str(tmp_path / "runs" / "spec-1" / "verify-spec" / "003-demo"),
            status="published",
            published_count=8,
            skipped_count=0,
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "evidence", "publish", "003-demo"])

    assert result.exit_code == 0
    assert "Spec evidence package published" in result.output
    assert "artifacts=8" in result.output


@pytest.mark.unit
def test_spec_evidence_publish_passes_allow_unlanded(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from echelon.mempalace_spec_evidence import SpecEvidencePublishReport

    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_spec_evidence.publish_spec_evidence_package",
        lambda project_root, spec_selector, run_id=None, allow_unlanded=False: calls.append(
            allow_unlanded
        )
        or SpecEvidencePublishReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            evidence_dir=str(tmp_path / "specs" / "003-demo" / "evidence"),
            source_run_dir=str(tmp_path / "runs" / "spec-1" / "verify-spec" / "003-demo"),
            status="published",
            published_count=8,
            skipped_count=0,
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["spec", "evidence", "publish", "003-demo", "--allow-unlanded"],
    )

    assert result.exit_code == 0
    assert calls == [True]


@pytest.mark.unit
def test_spec_evidence_publish_all_outputs_batch_summary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from echelon.mempalace_spec_evidence import (
        SpecEvidencePublishAllReport,
        SpecEvidencePublishReport,
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_spec_evidence.publish_all_spec_evidence_packages",
        lambda project_root, allow_unlanded=False: SpecEvidencePublishAllReport(
            schema_version=1,
            status="complete",
            total_count=2,
            published_count=2,
            failed_count=0,
            reports=[
                SpecEvidencePublishReport(
                    schema_version=1,
                    spec_id="001-one",
                    spec_dir=str(tmp_path / "specs" / "001-one"),
                    evidence_dir=str(tmp_path / "specs" / "001-one" / "evidence"),
                    source_run_dir=str(tmp_path / "runs" / "spec-1" / "verify-spec" / "001-one"),
                    status="published",
                    published_count=3,
                    skipped_count=0,
                ),
                SpecEvidencePublishReport(
                    schema_version=1,
                    spec_id="002-two",
                    spec_dir=str(tmp_path / "specs" / "002-two"),
                    evidence_dir=str(tmp_path / "specs" / "002-two" / "evidence"),
                    source_run_dir=str(tmp_path / "runs" / "spec-2" / "verify-spec" / "002-two"),
                    status="published",
                    published_count=4,
                    skipped_count=0,
                ),
            ],
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "evidence", "publish", "--all"])

    assert result.exit_code == 0
    assert "Spec evidence packages complete" in result.output
    assert "published=2" in result.output


@pytest.mark.unit
def test_spec_evidence_memory_refresh_outputs_mine_summary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from echelon.mempalace_spec_evidence import SpecEvidenceMemoryMineReport
    from echelon.mempalace_spec_evidence import SpecEvidenceMemoryAuditReport

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_spec_evidence.mine_spec_evidence_memory",
        lambda project_root, spec_selector, run_id, allow_unlanded=False: SpecEvidenceMemoryMineReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="complete",
            artifact_count=3,
            expected_count=9,
            written_count=9,
            adopted_count=0,
            skipped_count=0,
            failed_count=0,
            drifted_count=0,
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "echelon.mempalace_spec_evidence.audit_spec_evidence_memory",
        lambda project_root, spec_selector, allow_unlanded=False: SpecEvidenceMemoryAuditReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="pass",
            artifact_count=3,
            expected_count=9,
            present_current_count=9,
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["spec", "evidence", "memory", "refresh", "003-demo"],
    )

    assert result.exit_code == 0
    assert "MemPalace spec evidence mine complete" in result.output
    assert "artifacts=3" in result.output
    assert "written=9" in result.output
    assert "# MemPalace Spec Evidence Audit" in result.output


@pytest.mark.unit
def test_spec_evidence_memory_audit_outputs_reconciliation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from echelon.mempalace_spec_evidence import SpecEvidenceMemoryAuditReport

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_spec_evidence.audit_spec_evidence_memory",
        lambda project_root, spec_selector, allow_unlanded=False: SpecEvidenceMemoryAuditReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="fail",
            artifact_count=3,
            expected_count=9,
            present_current_count=8,
            stale=["evidence-drawer"],
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["spec", "evidence", "memory", "audit", "003-demo"],
    )

    assert result.exit_code == 1
    assert "# MemPalace Spec Evidence Audit" in result.output
    assert "Stale: 1" in result.output


@pytest.mark.unit
def test_spec_evidence_memory_refresh_json_outputs_combined_report(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from echelon.mempalace_spec_evidence import (
        SpecEvidenceMemoryAuditReport,
        SpecEvidenceMemoryMineReport,
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_spec_evidence.mine_spec_evidence_memory",
        lambda project_root, spec_selector, run_id, allow_unlanded=False: SpecEvidenceMemoryMineReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="complete",
            artifact_count=1,
            expected_count=1,
            written_count=1,
            adopted_count=0,
            skipped_count=0,
            failed_count=0,
            drifted_count=0,
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "echelon.mempalace_spec_evidence.audit_spec_evidence_memory",
        lambda project_root, spec_selector, allow_unlanded=False: SpecEvidenceMemoryAuditReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="pass",
            artifact_count=1,
            expected_count=1,
            present_current_count=1,
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["spec", "evidence", "memory", "refresh", "003-demo", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert sorted(payload) == ["audit", "mine"]
