"""trace_shim.py — COMMANDER decision event tracer (WS2 side channel).

Logs every COMMANDER "decision" event to the active run's trace.jsonl.

Contract:
- Writes ONLY to the side-channel file (`trace.jsonl` in the active run dir)
- NEVER raises in COMMANDER's critical path — all exceptions are swallowed silently
- NEVER reads from or writes to state.json
- NEVER blocks dispatch
- Must be importable even when the squad directory does not exist

Usage (inline in COMMANDER):

    from scripts.python.trace_shim import trace_decision

    # After each routing decision:
    trace_decision(
        run_id=run_id,
        phase=current_phase,
        decision_type="routing_decision",
        data={"condition": condition, "next_phase": next_phase},
    )

The trace file is separate from reasoning-journal.jsonl and is never
read by the critical path (WS2 side channel only).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default trace file location — can be overridden at import time
_DEFAULT_TRACE_DIR: str | None = None  # auto-detected if None

_TRACE_FILENAME = "trace.jsonl"
_MAX_TRACE_FILE_BYTES = 50 * 1024 * 1024  # 50 MB cap — rotate beyond this

# Global sequence counter (within this process)
_seq = 0


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _auto_detect_trace_dir() -> Path:
    """Auto-detect the active run directory for trace.jsonl."""
    if os.environ.get("ECHELON_RUN_DIR"):
        return Path(os.environ["ECHELON_RUN_DIR"])

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent.parent
    for candidate_root in (script_dir, *script_dir.parents):
        if (candidate_root / ".specify").exists() or (candidate_root / "knowledge-base").exists():
            repo_root = candidate_root
            break

    current = repo_root / "runs" / ".current"
    if current.exists():
        run_id = current.read_text(encoding="utf-8").strip()
        candidate = repo_root / "runs" / run_id
        if run_id and candidate.is_dir():
            return candidate

    return repo_root / "runs"


def _get_trace_path(squad_dir: Path) -> Path:
    return squad_dir / _TRACE_FILENAME


def trace_decision(
    run_id: str,
    phase: str,
    decision_type: str,
    data: dict | None = None,
    squad_dir: Path | None = None,
) -> None:
    """Log a COMMANDER decision event to the trace side channel.

    All exceptions are silently swallowed — this function MUST NOT raise.

    Args:
        run_id:        Current run ID
        phase:         Current phase node ID
        decision_type: Event type (e.g., "routing_decision", "preflight_result")
        data:          Optional dict of event data (will be JSON-serialized)
        squad_dir:     Override for the squad directory (auto-detected if None)
    """
    global _seq
    try:
        _seq += 1
        seq = _seq

        if squad_dir is None:
            if _DEFAULT_TRACE_DIR is not None:
                squad_dir = Path(_DEFAULT_TRACE_DIR)
            else:
                squad_dir = _auto_detect_trace_dir()

        trace_path = _get_trace_path(squad_dir)

        # Do not create the squad directory — only write if it exists
        if not squad_dir.exists():
            return

        # Rotation: if file exceeds cap, rename and start fresh
        try:
            if trace_path.exists() and trace_path.stat().st_size > _MAX_TRACE_FILE_BYTES:
                rotated = trace_path.with_suffix(".jsonl.1")
                trace_path.rename(rotated)
        except Exception:
            pass  # Swallow rotation failure

        entry = {
            "seq": seq,
            "run_id": run_id,
            "phase": phase,
            "type": decision_type,
            "timestamp": _iso_now(),
            "monotonic": round(time.monotonic(), 4),
            "data": data or {},
        }

        line = json.dumps(entry, separators=(",", ":")) + "\n"

        with open(trace_path, "a", encoding="utf-8") as f:
            f.write(line)

    except Exception:
        # Swallow silently — never brick the meta-run
        pass


def trace_predicate_eval(
    run_id: str,
    phase: str,
    predicate: str,
    result: bool | None,
    trace_entry: dict | None = None,
    squad_dir: Path | None = None,
) -> None:
    """Log a single predicate evaluation to the trace side channel.

    Lighter-weight than trace_decision — just the predicate + result.
    All exceptions are silently swallowed.
    """
    try:
        trace_decision(
            run_id=run_id,
            phase=phase,
            decision_type="predicate_eval",
            data={
                "predicate": predicate,
                "result": result,
                "trace_entry": trace_entry,
            },
            squad_dir=squad_dir,
        )
    except Exception:
        pass


def trace_preflight(
    run_id: str,
    phase: str,
    dependency: str,
    status: str,
    reason_code: str,
    squad_dir: Path | None = None,
) -> None:
    """Log a preflight probe result to the trace side channel.

    All exceptions are silently swallowed.
    """
    try:
        trace_decision(
            run_id=run_id,
            phase=phase,
            decision_type="preflight_probe",
            data={
                "dependency": dependency,
                "status": status,
                "reason_code": reason_code,
            },
            squad_dir=squad_dir,
        )
    except Exception:
        pass


def configure(squad_dir: Path | None = None) -> None:
    """Configure the trace shim (optional).

    Call at COMMANDER startup to pin the squad directory.
    """
    global _DEFAULT_TRACE_DIR
    try:
        if squad_dir is not None:
            _DEFAULT_TRACE_DIR = str(squad_dir)
    except Exception:
        pass


def load_trace(squad_dir: Path | None = None, run_id: str | None = None) -> list:
    """Load trace.jsonl entries (for WS2 analysis only — NOT for COMMANDER use).

    Args:
        squad_dir: Override squad directory
        run_id:    If provided, filter to entries matching this run_id

    Returns:
        List of trace entry dicts.
    """
    try:
        if squad_dir is None:
            squad_dir = _auto_detect_trace_dir()

        trace_path = _get_trace_path(squad_dir)
        if not trace_path.exists():
            return []

        entries = []
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entry = json.loads(line)
                    if run_id is None or entry.get("run_id") == run_id:
                        entries.append(entry)
                except json.JSONDecodeError:
                    pass
        return entries
    except Exception:
        return []
