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
