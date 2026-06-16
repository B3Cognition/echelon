"""Tests for deterministic scoped verify planning and report merging."""

from __future__ import annotations

from harness.scoped_verify import (
    build_scoped_verify_plan,
    merge_scoped_fulfillment_report,
)


def test_scoped_plan_includes_completed_task_requirements_and_dependencies(tmp_path):
    spec_dir = tmp_path / "specs" / "spec-001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "tasks.md").write_text(
        "- [x] T-001 complexity=standard phase=base req=FR-001 depends=none\n"
        "- [x] T-002 complexity=standard phase=base req=FR-002 depends=T-001\n"
        "- [ ] T-003 complexity=standard phase=base req=FR-003 depends=none\n",
        encoding="utf-8",
    )
    report = spec_dir / "fulfillment-report.md"
    report.write_text(
        "---\nverify_scope: full\nverified_commit: base123\n---\n"
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-001 | IMPLEMENTED | src/a.swift | high | ok |\n"
        "| FR-002 | PARTIAL | src/b.swift | medium | old |\n"
        "| FR-003 | MISSING | src/c.swift | low | old |\n",
        encoding="utf-8",
    )

    plan = build_scoped_verify_plan(
        spec_dir=spec_dir,
        completed_task_ids=["T-002"],
        changed_files=[],
    )

    assert plan.impacted_requirement_ids == ("FR-001", "FR-002")
    assert plan.base_full_report_path == report
    assert plan.base_full_verify_commit == "base123"


def test_scoped_plan_includes_rows_whose_evidence_file_changed(tmp_path):
    spec_dir = tmp_path / "specs" / "spec-001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=base req=FR-001 depends=none\n",
        encoding="utf-8",
    )
    (spec_dir / "fulfillment-report.md").write_text(
        "---\nverify_scope: full\nverified_commit: base123\n---\n"
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-001 | IMPLEMENTED | src/a.swift | high | ok |\n"
        "| NFR-004 | IMPLEMENTED | tests/performance/MissionStart3s.swift | high | ok |\n",
        encoding="utf-8",
    )

    plan = build_scoped_verify_plan(
        spec_dir=spec_dir,
        completed_task_ids=[],
        changed_files=["tests/performance/MissionStart3s.swift"],
    )

    assert plan.impacted_requirement_ids == ("NFR-004",)


def test_scoped_plan_matches_backticked_evidence_with_line_numbers(tmp_path):
    spec_dir = tmp_path / "specs" / "spec-001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=base req=FR-001 depends=none\n",
        encoding="utf-8",
    )
    (spec_dir / "fulfillment-report.md").write_text(
        "---\nverify_scope: full\nverified_commit: base123\n---\n"
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-001 | IMPLEMENTED | `src/a.swift:42` | high | ok |\n",
        encoding="utf-8",
    )

    plan = build_scoped_verify_plan(
        spec_dir=spec_dir,
        completed_task_ids=[],
        changed_files=["src/a.swift"],
    )

    assert plan.impacted_requirement_ids == ("FR-001",)


def test_scoped_plan_preserves_original_full_verify_commit_after_scoped_report(tmp_path):
    spec_dir = tmp_path / "specs" / "spec-001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "tasks.md").write_text(
        "- [x] T-001 complexity=standard phase=base req=FR-001 depends=none\n",
        encoding="utf-8",
    )
    (spec_dir / "fulfillment-report.md").write_text(
        "---\n"
        "verify_scope: scoped\n"
        "verified_commit: scoped456\n"
        "base_full_verify_commit: base123\n"
        "---\n"
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-001 | IMPLEMENTED | src/a.swift | high | ok |\n",
        encoding="utf-8",
    )

    plan = build_scoped_verify_plan(
        spec_dir=spec_dir,
        completed_task_ids=["T-001"],
        changed_files=[],
    )

    assert plan.base_full_verify_commit == "base123"


def test_merge_scoped_report_preserves_unaffected_rows(tmp_path):
    base = tmp_path / "fulfillment-report.md"
    scoped = tmp_path / "scoped-report.md"
    merged = tmp_path / "merged.md"
    base.write_text(
        "---\nverify_scope: full\nverified_commit: base123\n---\n"
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-001 | IMPLEMENTED | src/a.swift | high | keep |\n"
        "| FR-002 | PARTIAL | src/b.swift | medium | replace |\n",
        encoding="utf-8",
    )
    scoped.write_text(
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-002 | IMPLEMENTED | src/b.swift | high | fixed |\n",
        encoding="utf-8",
    )

    merge_scoped_fulfillment_report(
        base_report_path=base,
        scoped_report_path=scoped,
        output_report_path=merged,
        impacted_requirement_ids=["FR-002"],
        spec_id="spec-001",
        commit="head456",
        base_full_verify_commit="base123",
    )

    text = merged.read_text(encoding="utf-8")
    assert "verify_scope: scoped" in text
    assert "verified_commit: head456" in text
    assert "base_full_verify_commit: base123" in text
    assert "| FR-001 | IMPLEMENTED | src/a.swift | high | keep |" in text
    assert "| FR-002 | IMPLEMENTED | src/b.swift | high | fixed |" in text
    assert "| FR-002 | PARTIAL | src/b.swift | medium | replace |" not in text
