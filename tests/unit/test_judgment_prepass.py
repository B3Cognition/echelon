from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from harness.judgment_prepass import (
    assemble_full_report,
    assemble_fulfillment_report,
    build_judgment_prepass,
    write_fallback_fulfillment_template,
    write_judgment_prepass,
)
from harness.deferred_scope import apply_defer


def _run_harness(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    )
    return subprocess.run(
        [sys.executable, "-m", "harness", *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_write_judgment_prepass_emits_rows_and_fallback_summary(tmp_path: Path):
    spec_dir = tmp_path / "specs" / "001-demo"
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    spec_dir.mkdir(parents=True)
    verify_run_dir.mkdir(parents=True)

    (verify_run_dir / "canonical-requirements.json").write_text(
        json.dumps(
            {
                "requirements": [
                    {"id": "FR-001"},
                    {"id": "NFR-002"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (verify_run_dir / "requirement-audit.md").write_text(
        "# Requirement Audit\n\n"
        "| ID | Category | Source | Requirement | Acceptance Signal |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-001 | functional | spec.md | Start mission | UI flow |\n"
        "| NFR-002 | non_functional | spec.md | Startup under 500ms | measured runtime |\n",
        encoding="utf-8",
    )
    (verify_run_dir / "implementation-map.md").write_text(
        "# Implementation Map\n\n"
        "| ID | Implementation Evidence | Test Evidence | CodeGraph Evidence | Evidence Kind | Evidence Strength | Runtime Threshold | Confidence | Notes |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| FR-001 | app.py:start | tests/test_app.py::test_start | app.start | source_and_test | strong | false | high | |\n"
        "| NFR-002 | perf.py | tests/test_perf.py::test_budget | perf.metric | assertion_only | strong | true | high | |\n",
        encoding="utf-8",
    )
    (verify_run_dir / "state.json").write_text("{}", encoding="utf-8")

    result = write_judgment_prepass(spec_dir=spec_dir, verify_run_dir=verify_run_dir)

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["mechanical_count"] == 2
    assert payload["summary"]["fallback_count"] == 0
    by_id = {row["id"]: row for row in payload["rows"]}
    assert by_id["FR-001"]["proposed_status"] == "IMPLEMENTED"
    assert by_id["NFR-002"]["proposed_status"] == "UNVERIFIED"


def test_prepass_excludes_active_deferred_scope_from_llm_fallback(tmp_path: Path):
    spec_dir = tmp_path / "specs" / "906-demo"
    verify_run_dir = tmp_path / "runs" / "verify-spec-906-demo-1"
    spec_dir.mkdir(parents=True)
    verify_run_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("NFR-008\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=NFR-008 depends=none\n",
        encoding="utf-8",
    )
    apply_defer(spec_dir, ["NFR-008"], reason="owner decision")
    (verify_run_dir / "canonical-requirements.json").write_text(
        json.dumps({"requirements": [{"id": "NFR-008"}]}),
        encoding="utf-8",
    )
    (verify_run_dir / "implementation-map.md").write_text(
        "# Implementation Map\n\n"
        "| ID | Implementation Evidence | Test Evidence | CodeGraph Evidence | Evidence Kind | Evidence Strength | Runtime Threshold | Confidence | Notes |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
        encoding="utf-8",
    )

    result = write_judgment_prepass(spec_dir=spec_dir, verify_run_dir=verify_run_dir)

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    row = payload["rows"][0]
    assert payload["summary"]["fallback_ids"] == []
    assert row["mechanical"] is True
    assert row["proposed_status"] == "DEFERRED_SCOPE"
    assert row["report_row"] == (
        "| NFR-008 | DEFERRED_SCOPE | defer:defer-001: owner decision |"
    )


def test_write_judgment_prepass_cli_stamps_success_state(tmp_path: Path):
    spec_dir = tmp_path / "specs" / "001-demo"
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    spec_dir.mkdir(parents=True)
    verify_run_dir.mkdir(parents=True)

    (verify_run_dir / "canonical-requirements.json").write_text(
        json.dumps({"requirements": [{"id": "FR-001"}, {"id": "FR-002"}]}),
        encoding="utf-8",
    )
    (verify_run_dir / "implementation-map.md").write_text(
        "# Implementation Map\n\n"
        "| ID | Implementation Evidence | Test Evidence | CodeGraph Evidence | Evidence Kind | Evidence Strength | Runtime Threshold | Confidence | Notes |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| FR-001 | app.py:start | tests/test_app.py::test_start | app.start | source_and_test | strong | false | high | |\n",
        encoding="utf-8",
    )
    (verify_run_dir / "state.json").write_text("{}", encoding="utf-8")

    completed = _run_harness(
        ["write-judgment-prepass", str(spec_dir), str(verify_run_dir)]
    )

    assert completed.returncode == 0, completed.stderr
    state = json.loads((verify_run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["judgment_prepass"] == "ready"
    assert state["judgment_prepass_mechanical_count"] == 1
    assert state["judgment_prepass_fallback_count"] == 1


def test_write_judgment_prepass_cli_requires_state_before_writing(tmp_path: Path):
    spec_dir = tmp_path / "specs" / "001-demo"
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    spec_dir.mkdir(parents=True)
    verify_run_dir.mkdir(parents=True)

    (verify_run_dir / "canonical-requirements.json").write_text(
        json.dumps({"requirements": [{"id": "FR-001"}]}),
        encoding="utf-8",
    )
    (verify_run_dir / "implementation-map.md").write_text(
        "# Implementation Map\n\n"
        "| ID | Implementation Evidence | Test Evidence | CodeGraph Evidence | Evidence Kind | Evidence Strength | Runtime Threshold | Confidence | Notes |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| FR-001 | app.py:start | tests/test_app.py::test_start | app.start | source_and_test | strong | false | high | |\n",
        encoding="utf-8",
    )

    completed = _run_harness(
        ["write-judgment-prepass", str(spec_dir), str(verify_run_dir)]
    )

    assert completed.returncode == 1
    assert "state.json missing for verify-spec run:" in completed.stderr
    assert not (verify_run_dir / "judgment-prepass.json").exists()


def test_write_judgment_prepass_cli_reports_missing_map_without_traceback(
    tmp_path: Path,
):
    spec_dir = tmp_path / "specs" / "001-demo"
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    spec_dir.mkdir(parents=True)
    verify_run_dir.mkdir(parents=True)
    (verify_run_dir / "canonical-requirements.json").write_text(
        json.dumps({"requirements": [{"id": "FR-001"}]}),
        encoding="utf-8",
    )

    completed = _run_harness(
        ["write-judgment-prepass", str(spec_dir), str(verify_run_dir)]
    )

    assert completed.returncode == 2
    assert "missing required input:" in completed.stderr
    assert "implementation-map.md" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_prepass_marks_blank_evidence_rows_missing(tmp_path: Path):
    rows = _build_rows(
        tmp_path,
        implementation_row="| FR-010 |  |  |  | source_only | weak | false | none | |",
        requirement_id="FR-010",
    )
    assert rows[0].proposed_status == "MISSING"
    assert rows[0].mechanical is True


def test_prepass_falls_back_when_notes_signal_partial_or_ambiguous(tmp_path: Path):
    rows = _build_rows(
        tmp_path,
        implementation_row="| FR-011 | app.py:run | tests/test_app.py::test_run | app.run | source_and_test | strong | false | high | partial coverage remains |",
        requirement_id="FR-011",
    )
    assert rows[0].mechanical is False
    assert rows[0].fallback_reason == "notes_require_judgment"


def _build_rows(tmp_path: Path, *, implementation_row: str, requirement_id: str):
    spec_dir = tmp_path / "specs" / "001-demo"
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    spec_dir.mkdir(parents=True, exist_ok=True)
    verify_run_dir.mkdir(parents=True, exist_ok=True)

    (verify_run_dir / "canonical-requirements.json").write_text(
        json.dumps({"requirements": [{"id": requirement_id}]}),
        encoding="utf-8",
    )
    (verify_run_dir / "requirement-audit.md").write_text(
        "# Requirement Audit\n\n"
        "| ID | Category | Source | Requirement | Acceptance Signal |\n"
        "| --- | --- | --- | --- | --- |\n"
        f"| {requirement_id} | functional | spec.md | Requirement | Signal |\n",
        encoding="utf-8",
    )
    (verify_run_dir / "implementation-map.md").write_text(
        "# Implementation Map\n\n"
        "| ID | Implementation Evidence | Test Evidence | CodeGraph Evidence | Evidence Kind | Evidence Strength | Runtime Threshold | Confidence | Notes |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        f"{implementation_row}\n",
        encoding="utf-8",
    )
    (verify_run_dir / "state.json").write_text("{}", encoding="utf-8")

    return build_judgment_prepass(spec_dir=spec_dir, verify_run_dir=verify_run_dir)


def test_assemble_full_report_preserves_canonical_order():
    report = assemble_full_report(
        canonical_ids=["FR-001", "FR-002"],
        mechanical_rows={"FR-001": "| FR-001 | IMPLEMENTED | impl |"},
        fallback_rows={"FR-002": "| FR-002 | PARTIAL | needs judgment |"},
        task_progress_row="| TASK-PROGRESS | PARTIAL | mismatch |",
    )
    assert report.splitlines()[0] == "# Fulfillment Report"
    assert report.index("| FR-001 |") < report.index("| FR-002 |")
    assert "| TASK-PROGRESS | PARTIAL | mismatch |" in report


def test_assemble_fulfillment_report_creates_output_parent(tmp_path: Path):
    canonical_inventory = tmp_path / "canonical-requirements.json"
    canonical_inventory.write_text(
        json.dumps({"requirements": [{"id": "FR-001"}]}),
        encoding="utf-8",
    )
    prepass = tmp_path / "judgment-prepass.json"
    prepass.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "FR-001",
                        "mechanical": True,
                        "proposed_status": "IMPLEMENTED",
                        "reason_code": "source_and_test",
                        "fallback_reason": None,
                        "report_row": "| FR-001 | IMPLEMENTED | source_and_test |",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fallback = tmp_path / "fulfillment-report.fallback.md"
    fallback.write_text(
        "# Fallback Fulfillment Judgment\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n",
        encoding="utf-8",
    )
    output = tmp_path / "nested" / "fulfillment-report.md"

    assemble_fulfillment_report(
        canonical_inventory_path=canonical_inventory,
        judgment_prepass_path=prepass,
        fallback_report_path=fallback,
        output_report_path=output,
    )

    assert output.is_file()
    assert "| FR-001 | IMPLEMENTED | source_and_test |" in output.read_text(
        encoding="utf-8"
    )


def test_assemble_fulfillment_report_cli_stamps_state(tmp_path: Path):
    canonical_inventory = tmp_path / "canonical-requirements.json"
    canonical_inventory.write_text(
        json.dumps({"requirements": [{"id": "FR-001"}]}),
        encoding="utf-8",
    )
    prepass = tmp_path / "judgment-prepass.json"
    prepass.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "FR-001",
                        "mechanical": True,
                        "proposed_status": "IMPLEMENTED",
                        "reason_code": "source_and_test",
                        "fallback_reason": None,
                        "report_row": "| FR-001 | IMPLEMENTED | source_and_test |",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fallback = tmp_path / "fulfillment-report.fallback.md"
    fallback.write_text(
        "# Fallback Fulfillment Judgment\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n",
        encoding="utf-8",
    )
    output = tmp_path / "fulfillment-report.md"
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")

    completed = _run_harness(
        [
            "assemble-fulfillment-report",
            str(canonical_inventory),
            str(prepass),
            str(fallback),
            str(output),
            str(state_path),
        ]
    )

    assert completed.returncode == 0, completed.stderr
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["fulfillment_report"] == "ready"
    assert state["fulfillment_report_path"] == str(output.resolve())


def test_assemble_fulfillment_report_cli_requires_state_before_writing(tmp_path: Path):
    canonical_inventory = tmp_path / "canonical-requirements.json"
    canonical_inventory.write_text(
        json.dumps({"requirements": [{"id": "FR-001"}]}),
        encoding="utf-8",
    )
    prepass = tmp_path / "judgment-prepass.json"
    prepass.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "FR-001",
                        "mechanical": True,
                        "proposed_status": "IMPLEMENTED",
                        "reason_code": "source_and_test",
                        "fallback_reason": None,
                        "report_row": "| FR-001 | IMPLEMENTED | source_and_test |",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fallback = tmp_path / "fulfillment-report.fallback.md"
    fallback.write_text(
        "# Fallback Fulfillment Judgment\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n",
        encoding="utf-8",
    )
    output = tmp_path / "fulfillment-report.md"
    state_path = tmp_path / "state.json"

    completed = _run_harness(
        [
            "assemble-fulfillment-report",
            str(canonical_inventory),
            str(prepass),
            str(fallback),
            str(output),
            str(state_path),
        ]
    )

    assert completed.returncode == 1
    assert "state.json missing for verify-spec run:" in completed.stderr
    assert not output.exists()


def test_write_fallback_fulfillment_template_creates_output_parent(tmp_path: Path):
    prepass = tmp_path / "judgment-prepass.json"
    prepass.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "FR-001",
                        "mechanical": False,
                        "proposed_status": None,
                        "reason_code": None,
                        "fallback_reason": "needs_judgment",
                        "report_row": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "nested" / "fulfillment-report.fallback.md"

    fallback_ids = write_fallback_fulfillment_template(
        judgment_prepass_path=prepass,
        output_path=output,
    )

    assert fallback_ids == ["FR-001"]
    assert output.is_file()


def test_large_map_produces_small_fallback_queue(tmp_path: Path):
    spec_dir = tmp_path / "specs" / "001-demo"
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    spec_dir.mkdir(parents=True)
    verify_run_dir.mkdir(parents=True)

    requirement_rows = [{"id": f"FR-{i:03d}"} for i in range(1, 21)]
    (verify_run_dir / "canonical-requirements.json").write_text(
        json.dumps({"requirements": requirement_rows}),
        encoding="utf-8",
    )
    (verify_run_dir / "requirement-audit.md").write_text(
        _audit_markdown([row["id"] for row in requirement_rows]),
        encoding="utf-8",
    )
    lines = [
        "# Implementation Map",
        "",
        "| ID | Implementation Evidence | Test Evidence | CodeGraph Evidence | Evidence Kind | Evidence Strength | Runtime Threshold | Confidence | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in requirement_rows[:18]:
        lines.append(
            f"| {row['id']} | app.py:{row['id']} | tests/test_app.py::{row['id']} | app.{row['id']} | source_and_test | strong | false | high | |"
        )
    lines.append(
        "| FR-019 | perf.py |  | perf.metric | source_only | medium | false | medium | ambiguous |"
    )
    lines.append("| FR-020 |  |  |  | source_only | weak | false | none | |")
    (verify_run_dir / "implementation-map.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    (verify_run_dir / "state.json").write_text("{}", encoding="utf-8")

    result = write_judgment_prepass(spec_dir=spec_dir, verify_run_dir=verify_run_dir)
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))

    assert payload["summary"]["mechanical_count"] == 19
    assert payload["summary"]["fallback_ids"] == ["FR-019"]


def test_assemble_fulfillment_report_filters_scoped_ids(tmp_path: Path):
    canonical = tmp_path / "canonical-requirements.json"
    canonical.write_text(
        json.dumps({"requirements": [{"id": "FR-001"}, {"id": "FR-002"}]}),
        encoding="utf-8",
    )
    prepass = tmp_path / "judgment-prepass.json"
    prepass.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "FR-001",
                        "mechanical": True,
                        "proposed_status": "IMPLEMENTED",
                        "reason_code": "source_and_test_strong",
                        "fallback_reason": None,
                        "report_row": "| FR-001 | IMPLEMENTED | prepass:source_and_test_strong |",
                    },
                    {
                        "id": "FR-002",
                        "mechanical": False,
                        "proposed_status": None,
                        "reason_code": None,
                        "fallback_reason": "needs_judgment",
                        "report_row": None,
                    },
                ],
                "summary": {"mechanical_count": 1, "fallback_count": 1, "fallback_ids": ["FR-002"]},
            }
        ),
        encoding="utf-8",
    )
    fallback = tmp_path / "fallback-report.md"
    fallback.write_text(
        "# Fulfillment Report\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n"
        "| FR-002 | PARTIAL | fallback |\n",
        encoding="utf-8",
    )
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps({"verify_scope": "scoped", "scoped_ids": ["FR-002"]}),
        encoding="utf-8",
    )
    output = tmp_path / "fulfillment-report.md"

    assemble_fulfillment_report(
        canonical_inventory_path=canonical,
        judgment_prepass_path=prepass,
        fallback_report_path=fallback,
        output_report_path=output,
        state_path=state,
    )

    text = output.read_text(encoding="utf-8")
    assert "| FR-001 |" not in text
    assert "| FR-002 | PARTIAL | fallback |" in text


def test_assemble_fulfillment_report_rejects_unfilled_fallback_template(
    tmp_path: Path,
):
    canonical = tmp_path / "canonical-requirements.json"
    canonical.write_text(
        json.dumps({"requirements": [{"id": "FR-001"}]}),
        encoding="utf-8",
    )
    prepass = tmp_path / "judgment-prepass.json"
    prepass.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "FR-001",
                        "mechanical": False,
                        "proposed_status": None,
                        "reason_code": None,
                        "fallback_reason": "needs_judgment",
                        "report_row": None,
                    },
                ],
                "summary": {
                    "mechanical_count": 0,
                    "fallback_count": 1,
                    "fallback_ids": ["FR-001"],
                },
            }
        ),
        encoding="utf-8",
    )
    fallback = tmp_path / "fulfillment-report.fallback.md"
    fallback.write_text(
        "# Fallback Fulfillment Judgment\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n"
        "| FR-001 | TODO_STATUS | TODO_EVIDENCE |\n",
        encoding="utf-8",
    )

    try:
        assemble_fulfillment_report(
            canonical_inventory_path=canonical,
            judgment_prepass_path=prepass,
            fallback_report_path=fallback,
            output_report_path=tmp_path / "fulfillment-report.md",
        )
    except ValueError as exc:
        assert "unfilled fallback fulfillment row for FR-001" in str(exc)
    else:
        raise AssertionError("expected unfilled fallback row to fail")


def test_assemble_fulfillment_report_rejects_invalid_fallback_status(
    tmp_path: Path,
):
    canonical = tmp_path / "canonical-requirements.json"
    canonical.write_text(
        json.dumps({"requirements": [{"id": "FR-001"}]}),
        encoding="utf-8",
    )
    prepass = tmp_path / "judgment-prepass.json"
    prepass.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "FR-001",
                        "mechanical": False,
                        "proposed_status": None,
                        "reason_code": None,
                        "fallback_reason": "needs_judgment",
                        "report_row": None,
                    },
                ],
                "summary": {
                    "mechanical_count": 0,
                    "fallback_count": 1,
                    "fallback_ids": ["FR-001"],
                },
            }
        ),
        encoding="utf-8",
    )
    fallback = tmp_path / "fulfillment-report.fallback.md"
    fallback.write_text(
        "# Fallback Fulfillment Judgment\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n"
        "| FR-001 | DONE | evidence |\n",
        encoding="utf-8",
    )

    try:
        assemble_fulfillment_report(
            canonical_inventory_path=canonical,
            judgment_prepass_path=prepass,
            fallback_report_path=fallback,
            output_report_path=tmp_path / "fulfillment-report.md",
        )
    except ValueError as exc:
        assert "invalid fallback fulfillment status for FR-001: DONE" in str(exc)
    else:
        raise AssertionError("expected invalid fallback status to fail")


def test_assemble_fulfillment_report_rejects_unexpected_fallback_row(
    tmp_path: Path,
):
    canonical = tmp_path / "canonical-requirements.json"
    canonical.write_text(
        json.dumps({"requirements": [{"id": "FR-001"}, {"id": "FR-002"}]}),
        encoding="utf-8",
    )
    prepass = tmp_path / "judgment-prepass.json"
    prepass.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "FR-001",
                        "mechanical": True,
                        "proposed_status": "IMPLEMENTED",
                        "reason_code": "source_and_test_strong",
                        "fallback_reason": None,
                        "report_row": "| FR-001 | IMPLEMENTED | prepass:source_and_test_strong |",
                    },
                    {
                        "id": "FR-002",
                        "mechanical": False,
                        "proposed_status": None,
                        "reason_code": None,
                        "fallback_reason": "needs_judgment",
                        "report_row": None,
                    },
                ],
                "summary": {
                    "mechanical_count": 1,
                    "fallback_count": 1,
                    "fallback_ids": ["FR-002"],
                },
            }
        ),
        encoding="utf-8",
    )
    fallback = tmp_path / "fulfillment-report.fallback.md"
    fallback.write_text(
        "# Fallback Fulfillment Judgment\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n"
        "| FR-001 | IMPLEMENTED | duplicate mechanical row |\n"
        "| FR-002 | PARTIAL | evidence |\n",
        encoding="utf-8",
    )

    try:
        assemble_fulfillment_report(
            canonical_inventory_path=canonical,
            judgment_prepass_path=prepass,
            fallback_report_path=fallback,
            output_report_path=tmp_path / "fulfillment-report.md",
        )
    except ValueError as exc:
        assert "unexpected fallback fulfillment row for FR-001" in str(exc)
    else:
        raise AssertionError("expected unexpected fallback row to fail")


def test_assemble_fulfillment_report_rejects_duplicate_fallback_row(
    tmp_path: Path,
):
    canonical = tmp_path / "canonical-requirements.json"
    canonical.write_text(
        json.dumps({"requirements": [{"id": "FR-001"}]}),
        encoding="utf-8",
    )
    prepass = tmp_path / "judgment-prepass.json"
    prepass.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "FR-001",
                        "mechanical": False,
                        "proposed_status": None,
                        "reason_code": None,
                        "fallback_reason": "needs_judgment",
                        "report_row": None,
                    },
                ],
                "summary": {
                    "mechanical_count": 0,
                    "fallback_count": 1,
                    "fallback_ids": ["FR-001"],
                },
            }
        ),
        encoding="utf-8",
    )
    fallback = tmp_path / "fulfillment-report.fallback.md"
    fallback.write_text(
        "# Fallback Fulfillment Judgment\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n"
        "| FR-001 | PARTIAL | first evidence |\n"
        "| FR-001 | MISSING | conflicting duplicate |\n",
        encoding="utf-8",
    )

    try:
        assemble_fulfillment_report(
            canonical_inventory_path=canonical,
            judgment_prepass_path=prepass,
            fallback_report_path=fallback,
            output_report_path=tmp_path / "fulfillment-report.md",
        )
    except ValueError as exc:
        assert "duplicate fallback fulfillment row for FR-001" in str(exc)
    else:
        raise AssertionError("expected duplicate fallback row to fail")


def test_assemble_fulfillment_report_rejects_missing_fallback_row(
    tmp_path: Path,
):
    canonical = tmp_path / "canonical-requirements.json"
    canonical.write_text(
        json.dumps({"requirements": [{"id": "FR-001"}, {"id": "FR-002"}]}),
        encoding="utf-8",
    )
    prepass = tmp_path / "judgment-prepass.json"
    prepass.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "FR-001",
                        "mechanical": False,
                        "proposed_status": None,
                        "reason_code": None,
                        "fallback_reason": "needs_judgment",
                        "report_row": None,
                    },
                    {
                        "id": "FR-002",
                        "mechanical": False,
                        "proposed_status": None,
                        "reason_code": None,
                        "fallback_reason": "needs_judgment",
                        "report_row": None,
                    },
                ],
                "summary": {
                    "mechanical_count": 0,
                    "fallback_count": 2,
                    "fallback_ids": ["FR-001", "FR-002"],
                },
            }
        ),
        encoding="utf-8",
    )
    fallback = tmp_path / "fulfillment-report.fallback.md"
    fallback.write_text(
        "# Fallback Fulfillment Judgment\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n"
        "| FR-001 | PARTIAL | evidence |\n",
        encoding="utf-8",
    )

    try:
        assemble_fulfillment_report(
            canonical_inventory_path=canonical,
            judgment_prepass_path=prepass,
            fallback_report_path=fallback,
            output_report_path=tmp_path / "fulfillment-report.md",
        )
    except ValueError as exc:
        assert "missing fallback fulfillment row for FR-002" in str(exc)
    else:
        raise AssertionError("expected missing fallback row to fail")


def test_write_fallback_fulfillment_template_limits_rows_to_scoped_fallback_ids(
    tmp_path: Path,
):
    prepass = tmp_path / "judgment-prepass.json"
    prepass.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "FR-001",
                        "mechanical": True,
                        "proposed_status": "IMPLEMENTED",
                        "reason_code": "source_and_test_strong",
                        "fallback_reason": None,
                        "report_row": "| FR-001 | IMPLEMENTED | prepass:source_and_test_strong |",
                    },
                    {
                        "id": "FR-002",
                        "mechanical": False,
                        "proposed_status": None,
                        "reason_code": None,
                        "fallback_reason": "needs_judgment",
                        "report_row": None,
                    },
                    {
                        "id": "FR-003",
                        "mechanical": False,
                        "proposed_status": None,
                        "reason_code": None,
                        "fallback_reason": "needs_judgment",
                        "report_row": None,
                    },
                ],
                "summary": {
                    "mechanical_count": 1,
                    "fallback_count": 2,
                    "fallback_ids": ["FR-002", "FR-003"],
                },
            }
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps({"verify_scope": "scoped", "scoped_ids": ["FR-002"]}),
        encoding="utf-8",
    )
    output = tmp_path / "fulfillment-report.fallback.md"

    result = write_fallback_fulfillment_template(
        judgment_prepass_path=prepass,
        output_path=output,
        state_path=state,
    )

    text = output.read_text(encoding="utf-8")
    assert result == ["FR-002"]
    assert (
        "Allowed status values: IMPLEMENTED, PARTIAL, UNVERIFIED, MISSING, "
        "DEVIATED, OBSOLETE_SPEC, DEFERRED_SCOPE."
    ) in text
    assert "| FR-001 |" not in text
    assert "| FR-002 | TODO_STATUS | TODO_EVIDENCE |" in text
    assert "| FR-003 |" not in text


def test_write_fallback_fulfillment_template_cli(tmp_path: Path):
    prepass = tmp_path / "judgment-prepass.json"
    prepass.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "FR-010",
                        "mechanical": False,
                        "proposed_status": None,
                        "reason_code": None,
                        "fallback_reason": "needs_judgment",
                        "report_row": None,
                    }
                ],
                "summary": {
                    "mechanical_count": 0,
                    "fallback_count": 1,
                    "fallback_ids": ["FR-010"],
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "fulfillment-report.fallback.md"

    completed = _run_harness(
        ["write-fallback-fulfillment-template", str(prepass), str(output)]
    )

    assert completed.returncode == 0
    assert "OK: wrote fallback fulfillment template" in completed.stdout
    assert "| FR-010 | TODO_STATUS | TODO_EVIDENCE |" in output.read_text(
        encoding="utf-8"
    )


def test_write_fallback_fulfillment_template_cli_stamps_state(tmp_path: Path):
    prepass = tmp_path / "judgment-prepass.json"
    prepass.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "FR-010",
                        "mechanical": False,
                        "proposed_status": None,
                        "reason_code": None,
                        "fallback_reason": "needs_judgment",
                        "report_row": None,
                    }
                ],
                "summary": {
                    "mechanical_count": 0,
                    "fallback_count": 1,
                    "fallback_ids": ["FR-010"],
                },
            }
        ),
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "fulfillment-report.fallback.md"

    completed = _run_harness(
        [
            "write-fallback-fulfillment-template",
            str(prepass),
            str(output),
            str(state_path),
        ]
    )

    assert completed.returncode == 0, completed.stderr
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["fallback_fulfillment_template"] == "ready"
    assert state["fallback_fulfillment_count"] == 1


def test_write_fallback_fulfillment_template_cli_requires_state_before_writing(
    tmp_path: Path,
):
    prepass = tmp_path / "judgment-prepass.json"
    prepass.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "FR-010",
                        "mechanical": False,
                        "proposed_status": None,
                        "reason_code": None,
                        "fallback_reason": "needs_judgment",
                        "report_row": None,
                    }
                ],
                "summary": {
                    "mechanical_count": 0,
                    "fallback_count": 1,
                    "fallback_ids": ["FR-010"],
                },
            }
        ),
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    output = tmp_path / "fulfillment-report.fallback.md"

    completed = _run_harness(
        [
            "write-fallback-fulfillment-template",
            str(prepass),
            str(output),
            str(state_path),
        ]
    )

    assert completed.returncode == 1
    assert "state.json missing for verify-spec run:" in completed.stderr
    assert not output.exists()


def _audit_markdown(ids: list[str]) -> str:
    lines = [
        "# Requirement Audit",
        "",
        "| ID | Category | Source | Requirement | Acceptance Signal |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item_id in ids:
        lines.append(
            f"| {item_id} | functional | spec.md | Requirement {item_id} | Signal {item_id} |"
        )
    return "\n".join(lines) + "\n"
