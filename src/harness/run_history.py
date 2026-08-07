"""Python-owned spec run history updates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.spec_frontmatter import write_text_atomic


def append_implementation_run(
    spec_dir: Path,
    *,
    run_id: str,
    spec_status: str,
    verification_result: str,
) -> None:
    """Append a phase B implementation run and mark it authoritative on pass."""
    history_path = spec_dir / "run-history.json"
    history = _read_history(history_path)
    runs = history.setdefault("runs", [])
    if not isinstance(runs, list):
        runs = []
        history["runs"] = runs

    entry = {
        "run_id": run_id,
        "phase": "B",
        "status": spec_status,
        "verification_result": verification_result,
        "spec_status": spec_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    runs[:] = [
        run for run in runs
        if not (
            isinstance(run, dict)
            and run.get("run_id") == run_id
            and run.get("phase") == "B"
        )
    ]
    runs.append(entry)
    if verification_result == "PASS":
        history["authoritative_run"] = run_id

    write_text_atomic(
        history_path, json.dumps(history, indent=2, ensure_ascii=False, sort_keys=True)
    )


def append_phase_a_run(
    spec_dir: Path,
    *,
    run_id: str,
    spec_status: str,
    constitution_hash: str,
    retarget_revision: str | None = None,
    supersedes_run_id: str | None = None,
    baseline_checkpoint: str | None = None,
) -> None:
    """Append or refresh a Phase A spec-authoring run completion record."""
    retarget_fields = (
        retarget_revision,
        supersedes_run_id,
        baseline_checkpoint,
    )
    if any(value is not None for value in retarget_fields) and not all(
        type(value) is str and value for value in retarget_fields
    ):
        raise ValueError("retarget Phase A history linkage must be supplied together")
    history_path = spec_dir / "run-history.json"
    history = _read_history(history_path)
    runs = history.setdefault("runs", [])
    if not isinstance(runs, list):
        runs = []
        history["runs"] = runs

    entry = {
        "run_id": run_id,
        "phase": "A",
        "status": "done",
        "constitution_hash": constitution_hash,
        "spec_status": spec_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if retarget_revision is not None:
        entry.update(
            {
                "retarget_revision": retarget_revision,
                "supersedes_run_id": supersedes_run_id,
                "baseline_checkpoint": baseline_checkpoint,
            }
        )
    runs[:] = [
        run for run in runs
        if not (
            isinstance(run, dict)
            and run.get("run_id") == run_id
            and run.get("phase") == "A"
        )
    ]
    runs.append(entry)

    write_text_atomic(
        history_path, json.dumps(history, indent=2, ensure_ascii=False, sort_keys=True)
    )


def _read_history(history_path: Path) -> dict[str, Any]:
    if not history_path.exists():
        return {"runs": []}
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"runs": []}
    return data if isinstance(data, dict) else {"runs": []}
