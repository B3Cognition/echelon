"""Python-owned harness run history for per-spec operator orientation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.loop_result import LoopResult

HISTORY_FILENAME = "harness-run-history.json"


def history_path(spec_dir: Path) -> Path:
    return spec_dir / HISTORY_FILENAME


def read_history(spec_dir: Path) -> dict[str, Any]:
    path = history_path(spec_dir)
    if not path.exists():
        return {"runs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"runs": []}
    if not isinstance(data, dict):
        return {"runs": []}
    runs = data.get("runs")
    if not isinstance(runs, list):
        data["runs"] = []
    return data


def append_run(
    spec_dir: Path,
    *,
    spec_id: str,
    build_id: str,
    mode: str,
    strategy_id: str,
    result: LoopResult,
    pr_url: str | None,
    started_at: str | None = None,
) -> None:
    data = read_history(spec_dir)
    runs = data.setdefault("runs", [])
    assert isinstance(runs, list)
    runs.append(
        {
            "spec_id": spec_id,
            "build_id": build_id,
            "mode": mode,
            "strategy_id": strategy_id,
            "status": result.status,
            "termination_reason": result.termination_reason,
            "outer_iterations": result.outer_iterations,
            "inner_iterations": result.inner_iterations,
            "tokens_used": result.tokens_used,
            "pr_url": pr_url,
            "branch": result.branch,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    history_path(spec_dir).write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def summarize_history(
    spec_dir: Path,
    *,
    limit: int = 5,
) -> dict[str, Any]:
    data = read_history(spec_dir)
    runs = data.get("runs", [])
    if not isinstance(runs, list):
        runs = []
    valid_runs = [row for row in runs if isinstance(row, dict)]
    recent = valid_runs[-limit:]
    total_tokens = sum(_int_or_zero(row.get("tokens_used")) for row in valid_runs)
    return {
        "count": len(valid_runs),
        "recent": recent,
        "total_tokens": total_tokens,
    }


def _int_or_zero(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
