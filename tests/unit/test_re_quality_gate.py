from __future__ import annotations

from pathlib import Path
import re

import pytest

from harness.re_domain_manifest import ReDomain, domain_manifest_path
from harness.re_planner import ReExecutionPlan
from harness.re_quality_gate import (
    measure_source_quality,
    quality_target_for_domain,
    validate_semantic_quality_review,
    validate_staged_re_domain_quality,
    validate_staged_re_quality,
)
from tests.unit.test_re_publication import write_valid_re_run


def _plan(run_dir: Path) -> ReExecutionPlan:
    return ReExecutionPlan.from_json_dict(
        __import__("json").loads(
            (run_dir / "re" / "re-execution-plan.json").read_text(encoding="utf-8")
        )
    )


@pytest.mark.unit
def test_shallow_architecture_summary_reports_all_missing_deep_requirements(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text(
        "# Build Configuration\n\n"
        "## Purpose and Responsibility\n\n"
        "The build system produces the frontend bundle.\n\n"
        "## Architecture\n\n"
        "Webpack assembles the modules.\n\n"
        "## Key Files and Entry Points\n\n"
        "The configuration is in the build directory.\n",
        encoding="utf-8",
    )

    report = validate_staged_re_quality(run_dir / "re", _plan(run_dir))

    assert not report.passed
    assert len(report.failures) == 1
    failure = report.failures[0]
    assert failure.source_id == "api"
    assert failure.spec_path == spec
    assert failure.missing_sections == (
        "User Scenarios & Testing",
        "Requirements (Functional)",
        "Requirements (Non-Functional)",
        "Key Entities",
        "Edge Cases",
    )
    assert failure.source_evidence_count == 0


@pytest.mark.unit
def test_gate_rejects_a_source_when_any_manifest_domain_has_no_spec(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    manifest_path = domain_manifest_path(run_dir / "re", "api")
    manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
    manifest["domains"].append(
        {
            "domain_id": "002-re-worker",
            "root": "worker",
            "source_file_count": 1,
            "source_line_count": 1,
        }
    )
    manifest_path.write_text(__import__("json").dumps(manifest), encoding="utf-8")

    report = validate_staged_re_quality(run_dir / "re", _plan(run_dir))

    assert not report.passed
    assert len(report.failures) == 1
    assert report.failures[0].domain_id == "002-re-worker"
    assert report.failures[0].reason == "required_domain_spec_missing"


@pytest.mark.unit
def test_gate_rejects_source_evidence_outside_the_domain_root(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace("src/file-1.ts:1", "outside.ts:1"),
        encoding="utf-8",
    )

    report = validate_staged_re_quality(run_dir / "re", _plan(run_dir))

    assert not report.passed
    assert report.failures[0].invalid_source_evidence == ("`outside.ts:1`",)


@pytest.mark.unit
def test_gate_accepts_domain_relative_source_evidence(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace("src/file-", "file-"),
        encoding="utf-8",
    )

    report = validate_staged_re_quality(run_dir / "re", _plan(run_dir))

    assert report.passed


@pytest.mark.unit
def test_source_measurement_counts_only_visible_cited_source_files(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    source_root = tmp_path / "sources" / "api"
    (source_root / "src" / "orphan.ts").write_text("export const orphan = true;\n")
    hidden = source_root / ".github"
    hidden.mkdir()
    (hidden / "workflow.ts").write_text("export const ignored = true;\n")

    report = measure_source_quality(run_dir / "re", _plan(run_dir), "api")

    assert report.eligible_file_count == 6
    assert report.covered_file_count == 5
    assert report.coverage_pct == pytest.approx(83.3333333333)
    assert report.orphan_paths == ("src/orphan.ts",)
    assert not report.passed


@pytest.mark.unit
def test_source_measurement_counts_supporting_artifacts_for_unowned_files(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    source_root = tmp_path / "sources" / "api"
    (source_root / "root-support.ts").write_text(
        "export const runtimeSupport = true;\n", encoding="utf-8"
    )
    (run_dir / "re" / "sources" / "api" / "supporting-artifacts.md").write_text(
        "# Supporting Artifacts\n\n"
        "## Source Evidence\n\n"
        "- `root-support.ts:1` configures runtime support.\n",
        encoding="utf-8",
    )

    report = measure_source_quality(run_dir / "re", _plan(run_dir), "api")

    assert report.eligible_file_count == 6
    assert report.covered_file_count == 6
    assert report.coverage_pct == 100
    assert report.orphan_paths == ()
    assert report.passed


@pytest.mark.unit
def test_target_gate_reports_only_its_declared_domain(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text("# Architecture summary\n", encoding="utf-8")

    report = validate_staged_re_domain_quality(
        run_dir / "re", _plan(run_dir), "api", "001-re-domain"
    )

    assert not report.passed
    assert len(report.failures) == 1
    assert report.failures[0].domain_id == "001-re-domain"
    assert report.failures[0].spec_path == spec


@pytest.mark.unit
def test_quality_target_scales_from_domain_files_and_lines() -> None:
    target = quality_target_for_domain(
        ReDomain(
            domain_id="001-re-api",
            root="src/api",
            source_file_count=25,
            source_line_count=1_600,
        )
    )

    assert target.complexity_units == 3
    assert target.minimum_scenarios == 7
    assert target.minimum_functional_requirements == 11
    assert target.minimum_non_functional_requirements == 4


@pytest.mark.unit
def test_gate_reports_missing_acceptance_cases_and_adaptive_requirement_counts(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    text = spec.read_text(encoding="utf-8")
    text = text.replace("Given the current source state", "With the current source state")
    text = re.sub(r"^### NFR-.*?(?=^### NFR-|^## )", "", text, flags=re.MULTILINE | re.DOTALL)
    spec.write_text(text, encoding="utf-8")

    report = validate_staged_re_domain_quality(
        run_dir / "re", _plan(run_dir), "api", "001-re-domain"
    )

    assert not report.passed
    failure = report.failures[0]
    assert failure.expected_scenario_count == 5
    assert failure.scenario_count == 5
    assert len(failure.scenarios_without_acceptance) == 5
    assert failure.expected_functional_requirement_count == 7
    assert failure.functional_requirement_count == 7
    assert failure.expected_non_functional_requirement_count == 3
    assert failure.non_functional_requirement_count == 0


@pytest.mark.unit
def test_semantic_review_requires_complete_domain_audit_and_evidence(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    payload = {
        "schema_version": 1,
        "domains": [
            {
                "source_id": "api",
                "domain_id": "001-re-domain",
                "verdict": "REPAIR",
                "findings": [
                    "The retry exhaustion behavior is absent from the failure scenarios."
                ],
                "source_evidence": ["`src/file-1.ts:1`"],
            }
        ],
    }

    report, error = validate_semantic_quality_review(
        run_dir / "re", _plan(run_dir), payload
    )

    assert error is None
    assert report is not None
    assert not report.passed
    assert report.failures[0].reason == "semantic_quality_incomplete"
    assert report.failures[0].semantic_findings == (
        "The retry exhaustion behavior is absent from the failure scenarios.",
    )
    record = report.failures[0].semantic_finding_records[0]
    assert record.finding_id.startswith("ref-")
    assert record.category == "error-recovery"
    assert record.source_evidence == ("`src/file-1.ts:1`",)


@pytest.mark.unit
def test_semantic_review_rejects_invalid_repair_evidence_with_domain_detail(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    payload = {
        "schema_version": 1,
        "domains": [
            {
                "source_id": "api",
                "domain_id": "001-re-domain",
                "verdict": "REPAIR",
                "findings": [
                    "The retry exhaustion behavior is absent from the failure scenarios.",
                    "The timeout behavior is absent from the failure scenarios.",
                ],
                "source_evidence": [
                    "`src/file-1.ts:1`",
                    "`sources/api/specs/001-re-domain/spec.md:10-12`",
                    "`runs/run-test/re/quality/sources/api.json` (coverage_pct: 59.15)",
                ],
            }
        ],
    }

    report, error = validate_semantic_quality_review(
        run_dir / "re", _plan(run_dir), payload
    )

    assert report is None
    assert error is not None
    assert "api/001-re-domain" in error
    assert "needs 2 valid source citation(s), found 1" in error
    assert "`sources/api/specs/001-re-domain/spec.md:10-12`" in error
    assert "`runs/run-test/re/quality/sources/api.json`" in error


@pytest.mark.unit
def test_semantic_review_rejects_an_incomplete_domain_inventory(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))

    report, error = validate_semantic_quality_review(
        run_dir / "re", _plan(run_dir), {"schema_version": 1, "domains": []}
    )

    assert report is None
    assert error is not None
    assert "semantic quality review did not audit every refreshed domain" in error
    assert "missing 1" in error
    assert "api/001-re-domain" in error
