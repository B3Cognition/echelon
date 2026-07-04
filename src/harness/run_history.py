"""Python-owned spec run history updates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    runs.append(entry)
    if verification_result == "PASS":
        history["authoritative_run"] = run_id

    history_path.write_text(
        json.dumps(history, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def append_phase_a_run(
    spec_dir: Path,
    *,
    run_id: str,
    spec_status: str,
    constitution_hash: str,
) -> None:
    """Append or refresh a Phase A spec-authoring run completion record."""
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
    runs[:] = [
        run for run in runs
        if not (
            isinstance(run, dict)
            and run.get("run_id") == run_id
            and run.get("phase") == "A"
        )
    ]
    runs.append(entry)

    history_path.write_text(
        json.dumps(history, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _read_history(history_path: Path) -> dict[str, Any]:
    if not history_path.exists():
        return {"runs": []}
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"runs": []}
    return data if isinstance(data, dict) else {"runs": []}
