"""State emitter for cognitive-squad agent monitoring.

Writes agent state changes to files that RADAR watches and streams to the UI.
"""

import json
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


SQUAD_DIR = Path(".specify/squad")
AGENT_STATES_PATH = SQUAD_DIR / "agent-states.json"
EVENTS_JSONL_PATH = SQUAD_DIR / "agent-states-events.jsonl"


def init_run(run_id: str) -> None:
    """Initialize files for a new run.

    Call once when a new run starts. Truncates both files so RADAR
    doesn't replay stale history.

    Args:
        run_id: Unique identifier for this run (e.g., "squad-1711036800")
    """
    SQUAD_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(AGENT_STATES_PATH, json.dumps({
        "run_id": run_id,
        "updated_at": _now(),
        "agents": {},
        "dispatch_order": [],
    }, indent=2))
    EVENTS_JSONL_PATH.write_text("")


def on_dispatched(run_id: str, dispatch_id: str, codename: str, phase: str) -> None:
    """Record agent dispatch.

    Call immediately before dispatching an agent (Agent tool call).

    Args:
        run_id: Current run ID
        dispatch_id: Unique agent instance ID (e.g., "SCOUT-1")
        codename: Agent type (e.g., "SCOUT")
        phase: Current squad phase (e.g., "discover")
    """
    _append_event(run_id, dispatch_id, codename, "working", phase, {})
    _patch_snapshot(run_id, dispatch_id, codename, "working", phase, {
        "dispatched_at": _now(),
        "completed_at": None,
        "artifacts_produced": [],
        "blocked_reason": None,
    })


def on_complete(
    run_id: str,
    dispatch_id: str,
    codename: str,
    phase: str,
    artifacts: Optional[list[str]] = None
) -> None:
    """Record successful agent completion.

    Call after reading a successful agent result.

    Args:
        run_id: Current run ID
        dispatch_id: Agent instance ID
        codename: Agent type
        phase: Squad phase when completed
        artifacts: List of artifact filenames produced (not full paths)
    """
    artifacts = artifacts or []
    _append_event(run_id, dispatch_id, codename, "complete", phase,
                  {"artifacts_produced": artifacts})
    _patch_snapshot(run_id, dispatch_id, codename, "complete", phase, {
        "completed_at": _now(),
        "artifacts_produced": artifacts,
        "blocked_reason": None,
    })


def on_error(run_id: str, dispatch_id: str, codename: str, phase: str) -> None:
    """Record agent failure.

    Call when an agent produces no output or fails.
    """
    _append_event(run_id, dispatch_id, codename, "error", phase, {})
    _patch_snapshot(run_id, dispatch_id, codename, "error", phase, {
        "completed_at": _now(),
    })


def on_blocked(
    run_id: str,
    dispatch_id: str,
    codename: str,
    phase: str,
    reason: str
) -> None:
    """Record agent blocked state.

    Call when an agent is blocked (human escalation).
    """
    _append_event(run_id, dispatch_id, codename, "blocked", phase,
                  {"blocked_reason": reason})
    _patch_snapshot(run_id, dispatch_id, codename, "blocked", phase, {
        "blocked_reason": reason,
    })


def on_resumed(run_id: str, dispatch_id: str, codename: str, phase: str) -> None:
    """Record agent resumption.

    Call when a blocked agent resumes (MANAGER resolves the escalation).
    """
    _append_event(run_id, dispatch_id, codename, "working", phase, {})
    _patch_snapshot(run_id, dispatch_id, codename, "working", phase, {
        "blocked_reason": None,
    })


# ── Internal helpers ─────────────────────────────────────────────────────────

def _append_event(
    run_id: str,
    dispatch_id: str,
    codename: str,
    state: str,
    phase: str,
    extras: dict
) -> None:
    """Append a single event line to the JSONL file."""
    event = {
        "id": dispatch_id,
        "codename": codename,
        "state": state,
        "ts": _now(),
        "phase": phase,
        "run_id": run_id,
        **extras,
    }
    with open(EVENTS_JSONL_PATH, "a") as f:
        f.write(json.dumps(event) + "\n")


def _patch_snapshot(
    run_id: str,
    dispatch_id: str,
    codename: str,
    state: str,
    phase: str,
    patch: dict
) -> None:
    """Update the snapshot file with new agent state."""
    try:
        snapshot = json.loads(AGENT_STATES_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        snapshot = {"run_id": run_id, "agents": {}, "dispatch_order": []}

    existing = snapshot["agents"].get(dispatch_id, {
        "id": dispatch_id,
        "codename": codename,
        "state": "idle",
        "dispatched_at": None,
        "completed_at": None,
        "phase": phase,
        "run_id": run_id,
        "artifacts_produced": [],
        "blocked_reason": None,
    })

    snapshot["agents"][dispatch_id] = {**existing, "state": state, "phase": phase, **patch}
    snapshot["updated_at"] = _now()

    if dispatch_id not in snapshot["dispatch_order"]:
        snapshot["dispatch_order"].append(dispatch_id)

    _atomic_write(AGENT_STATES_PATH, json.dumps(snapshot, indent=2))


def _atomic_write(file_path: Path, content: str) -> None:
    """Write atomically via temp file + rename (POSIX atomic)."""
    tmp_path = Path(tempfile.gettempdir()) / f"radar-{secrets.token_hex(6)}.tmp"
    tmp_path.write_text(content)
    tmp_path.rename(file_path)


def _now() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
