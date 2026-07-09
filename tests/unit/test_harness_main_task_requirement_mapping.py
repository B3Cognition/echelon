"""CLI tests for harness task requirement metadata mapping."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    tasks_path = tmp_path / "tasks.md"
    candidate_path = tmp_path / "task-requirement-map.candidates.json"
    out_dir = tmp_path / "out"
    tasks_path.write_text(
        "# Tasks\n\n"
        "- [ ] T-001 complexity=standard phase=engine req=UNMAPPED depends=none\n"
        "  **Status:** PENDING\n",
        encoding="utf-8",
    )
    candidate_path.write_text(
        json.dumps(
            {
                "task_requirement_mappings": [
                    {
                        "task_id": "T-001",
                        "requirements": ["FR-001"],
                        "evidence": "fulfillment-report.md#FR-001",
                        "reason": "Task owns FR-001",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return tasks_path, candidate_path, out_dir


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_apply_task_requirement_mapping_dry_run_cli_does_not_mutate(
    tmp_path: Path,
) -> None:
    tasks_path, candidate_path, out_dir = _write_inputs(tmp_path)

    result = _run(
        [
            "apply-task-requirement-mapping",
            str(tasks_path),
            str(candidate_path),
            str(out_dir),
            "--dry-run",
        ]
    )

    assert result.returncode == 0
    assert "dry-run wrote" in result.stdout
    assert "req=UNMAPPED" in tasks_path.read_text(encoding="utf-8")
    assert (out_dir / "task-requirement-map-plan.md").exists()
    assert not (out_dir / "task-requirement-map-applied.md").exists()


def test_apply_task_requirement_mapping_cli_updates_req_metadata(tmp_path: Path) -> None:
    tasks_path, candidate_path, out_dir = _write_inputs(tmp_path)

    result = _run(
        [
            "apply-task-requirement-mapping",
            str(tasks_path),
            str(candidate_path),
            str(out_dir),
        ]
    )

    assert result.returncode == 0
    assert "applied 1 task requirement mappings" in result.stdout
    assert "req=FR-001" in tasks_path.read_text(encoding="utf-8")
    assert (out_dir / "task-requirement-map-applied.md").exists()


def test_write_task_requirement_mapping_candidates_cli_maps_explicit_ids(
    tmp_path: Path,
) -> None:
    tasks_path = tmp_path / "tasks.md"
    out_path = tmp_path / "task-requirement-map.candidates.json"
    tasks_path.write_text(
        "# Tasks\n\n"
        "- [ ] T-001 complexity=standard phase=engine req=UNMAPPED depends=none\n"
        "  **Title:** Implement FR-001 course formula\n\n"
        "- [ ] T-002 complexity=standard phase=engine req=UNMAPPED depends=none\n"
        "  **Title:** Build grid behavior\n\n"
        "- [ ] T-003 complexity=standard phase=engine req=FR-002 depends=none\n"
        "  **Title:** Already mapped\n",
        encoding="utf-8",
    )

    result = _run(
        [
            "write-task-requirement-mapping-candidates",
            str(tasks_path),
            str(out_path),
        ]
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["task_requirement_mappings"] == [
        {
            "task_id": "T-001",
            "requirements": ["FR-001"],
            "evidence": "tasks.md#T-001 explicit requirement IDs: FR-001",
            "reason": "task text explicitly names mapped requirement IDs",
        }
    ]
    assert payload["ambiguous_task_requirement_mappings"] == [
        {
            "task_id": "T-002",
            "requirements": [],
            "evidence": "tasks.md#T-002",
            "reason": "task has req=UNMAPPED and no explicit requirement IDs in task text",
        }
    ]
