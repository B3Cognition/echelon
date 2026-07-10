"""CLI tests for harness progress reconciliation."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _tasks_md() -> str:
    return """# Tasks

- [ ] T-001 complexity=standard phase=engine req=FR-001 depends=none
  **Status:** PENDING
  **Title:** Implement formula
"""


def _candidate() -> dict[str, object]:
    return {
        "safe_task_updates": [
            {
                "task_id": "T-001",
                "status": "DONE",
                "evidence": "fulfillment-report.md#FR-001",
                "reason": "FR-001 is implemented",
            }
        ],
        "ambiguous_task_matches": [],
        "fulfillment_gap_tasks": {},
        "manual_followups": [],
    }


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    tasks_path = tmp_path / "tasks.md"
    candidate_path = tmp_path / "candidate.json"
    out_dir = tmp_path / "out"
    tasks_path.write_text(_tasks_md(), encoding="utf-8")
    candidate_path.write_text(json.dumps(_candidate()), encoding="utf-8")
    return tasks_path, candidate_path, out_dir


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_apply_progress_reconciliation_dry_run_cli_does_not_mutate(
    tmp_path: Path,
) -> None:
    tasks_path, candidate_path, out_dir = _write_inputs(tmp_path)

    result = _run(
        [
            "apply-progress-reconciliation",
            str(tasks_path),
            str(candidate_path),
            str(out_dir),
            "--dry-run",
        ]
    )

    assert result.returncode == 0
    assert "dry-run wrote" in result.stdout
    assert "- [ ] T-001" in tasks_path.read_text(encoding="utf-8")
    assert (out_dir / "progress-reconciliation-plan.md").exists()
    assert not (out_dir / "progress-reconciliation-applied.md").exists()


def test_apply_progress_reconciliation_cli_marks_done(tmp_path: Path) -> None:
    tasks_path, candidate_path, out_dir = _write_inputs(tmp_path)

    result = _run(
        [
            "apply-progress-reconciliation",
            str(tasks_path),
            str(candidate_path),
            str(out_dir),
        ]
    )

    assert result.returncode == 0
    assert "applied 1 task updates" in result.stdout
    assert "- [x] T-001" in tasks_path.read_text(encoding="utf-8")
    assert (out_dir / "progress-reconciliation-applied.md").exists()


def test_apply_progress_reconciliation_cli_stamps_state(tmp_path: Path) -> None:
    tasks_path, candidate_path, out_dir = _write_inputs(tmp_path)
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")

    result = _run(
        [
            "apply-progress-reconciliation",
            str(tasks_path),
            str(candidate_path),
            str(out_dir),
            str(state_path),
        ]
    )

    assert result.returncode == 0, result.stderr
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["progress_reconciliation"] == "applied"
    assert state["progress_reconciliation_safe_count"] == 1
    assert state["progress_reconciliation_applied_count"] == 1


def test_write_progress_reconciliation_candidates_cli_uses_fulfillment_statuses(
    tmp_path: Path,
) -> None:
    tasks_path = tmp_path / "tasks.md"
    tasks_path.write_text(
        "# Tasks\n\n"
        "- [ ] T-001 complexity=standard phase=engine req=FR-001 depends=none\n"
        "- [ ] T-002 complexity=standard phase=engine req=FR-002 depends=none\n"
        "- [ ] T-003 complexity=standard phase=engine req=UNMAPPED depends=none\n"
        "- [x] T-004 complexity=standard phase=engine req=FR-001 depends=none\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "fulfillment-report.md"
    report_path.write_text(
        "# Fulfillment Report\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n"
        "| FR-001 | IMPLEMENTED | source and tests |\n"
        "| FR-002 | PARTIAL | needs more work |\n",
        encoding="utf-8",
    )
    gaps_path = tmp_path / "fulfillment-gaps.md"
    gaps_path.write_text("# Gaps\n", encoding="utf-8")
    out_path = tmp_path / "progress-reconciliation-candidates.json"

    result = _run(
        [
            "write-progress-reconciliation-candidates",
            str(tasks_path),
            str(report_path),
            str(gaps_path),
            str(out_path),
        ]
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["safe_task_updates"] == [
        {
            "task_id": "T-001",
            "status": "DONE",
            "evidence": "fulfillment-report.md#FR-001",
            "reason": "all mapped requirements are IMPLEMENTED: FR-001",
        }
    ]
    ambiguous_ids = {
        item["task_id"] for item in payload["ambiguous_task_matches"]
    }
    assert ambiguous_ids == {"T-002", "T-003"}
    assert payload["fulfillment_gap_tasks"]["details"] == str(gaps_path)


def test_write_progress_reconciliation_candidates_cli_stamps_state(
    tmp_path: Path,
) -> None:
    tasks_path = tmp_path / "tasks.md"
    tasks_path.write_text(
        "# Tasks\n\n"
        "- [ ] T-001 complexity=standard phase=engine req=FR-001 depends=none\n"
        "- [ ] T-002 complexity=standard phase=engine req=FR-002 depends=none\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "fulfillment-report.md"
    report_path.write_text(
        "# Fulfillment Report\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n"
        "| FR-001 | IMPLEMENTED | source and tests |\n"
        "| FR-002 | PARTIAL | needs more work |\n",
        encoding="utf-8",
    )
    gaps_path = tmp_path / "fulfillment-gaps.md"
    gaps_path.write_text("# Gaps\n", encoding="utf-8")
    out_path = tmp_path / "progress-reconciliation-candidates.json"
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")

    result = _run(
        [
            "write-progress-reconciliation-candidates",
            str(tasks_path),
            str(report_path),
            str(gaps_path),
            str(out_path),
            str(state_path),
        ]
    )

    assert result.returncode == 0, result.stderr
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["progress_reconciliation_candidates"] == "ready"
    assert state["progress_reconciliation_safe_count"] == 1
    assert state["progress_reconciliation_ambiguous_count"] == 1
