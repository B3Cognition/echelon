"""
recovery_generator.py — Recovery Instruction Generator (RIG).

Generates hookSpecificOutput JSON payloads for Claude Code PostCompact and
SessionStart hooks when a codegen pipeline is active.

FR references:
  FR-CC-005  — PostCompact additionalContext MUST start with "IMMEDIATELY"
  FR-CC-012  — SessionStart additionalContext MUST start with "NOTICE"
  FR-CC-013  — Stale sentinel cleanup (phase==DONE or state missing)
  FR-CC-014  — Cleanup is idempotent
  FR-CC-015  — Injection text MUST NOT exceed 2000 characters
  FR-CC-021  — phase==ABORT also treated as stale
  FR-CC-022  — Stale cleanup writes to hook.log
  FR-CC-030  — Hook MUST write timestamped entries to ~/.codegen/hook.log
  FR-CC-031  — Log entry: timestamp, hook_type, phase, psi, action
  FR-CC-032  — Log file is append-only
  FR-CC-037  — Dedup: suppress SessionStart if PostCompact fired within 30 s

ADR references:
  ADR-001    — Python module, not shell script
  ADR-003    — Dedup via .codegen-compact-ts timestamp file, 30 s window
  ADR-006    — Hook log at ~/.codegen/hook.log, persistent, append-only

CQ-ISC advisories:
  CQ-ISC-SEC-001   — No shell injection / eval / exec with user input
  CQ-ISC-STRUCT-001 — Module <=200 lines, single responsibility
  CQ-ISC-TEST-001  — Every public function has a unit test
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SENTINEL_NAME = ".codegen-active"
_STATE_FILE_NAME = "codegen-state.json"
_COMPACT_TS_NAME = ".codegen-compact-ts"
_HOOK_LOG_PATH = Path.home() / ".echelon" / "hook.log"
_DEDUP_WINDOW_SECONDS = 30
_MAX_CONTEXT_CHARS = 2000  # FR-CC-015: <=2000 chars (<=500 tokens proxy)

# Phases that are treated as stale (FR-CC-013, FR-CC-021)
_STALE_PHASES = {"DONE", "ABORT"}

# additionalContext templates (FR-CC-005, FR-CC-012)
_POSTCOMPACT_TEMPLATE = (
    "IMMEDIATELY invoke /codegen --resume via Skill tool. "
    "Pipeline active at phase {phase}. "
    "Intent: {intent}. "
    "Psi={psi:.2f}. "
    "Do NOT simulate the pipeline."
)
_SESSIONSTART_TEMPLATE = (
    "NOTICE: A codegen pipeline is active. "
    "Pipeline ID: {pipeline_id}. "
    "Phase: {phase}. "
    "Intent: {intent}. "
    "Psi={psi:.2f}. "
    "When ready, invoke /codegen --resume via the Skill tool."
)

# Hook event name map (determines hookEventName and template selection)
_HOOK_EVENT_NAMES: dict[str, str] = {
    "postcompact": "PostCompact",
    "sessionstart": "SessionStart",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_recovery_context(
    hook_type: str,
    work_dir: str | None = None,
) -> dict | None:
    """
    Generate hookSpecificOutput JSON for Claude Code hooks.

    Args:
        hook_type: "postcompact" or "sessionstart" (case-insensitive).
        work_dir:  Working directory to inspect (default: CWD).

    Returns:
        dict with hookSpecificOutput if pipeline is active and not stale,
        None if pipeline is not active or stale cleanup was performed.
    """
    hook_type_lower = hook_type.lower()
    hook_event_name = _HOOK_EVENT_NAMES.get(hook_type_lower, hook_type)
    base = Path(work_dir) if work_dir else Path.cwd()

    # Step 1: sentinel presence check
    sentinel = base / _SENTINEL_NAME
    if not sentinel.exists():
        return None

    # Step 2: read codegen-state.json; stale cleanup if missing or stale phase
    state_file = base / _STATE_FILE_NAME
    state = _read_state(state_file)
    phase_upper = (
        "" if state is None else state.get("current_phase", "").upper()
    )
    if state is None or phase_upper in _STALE_PHASES:
        reason = "phase=%s or state missing" % (phase_upper or "MISSING")
        _stale_cleanup(
            sentinel, base, reason=reason,
            hook_event_name=hook_event_name,
        )
        return None

    # Step 3: dedup check (FR-CC-037) — suppress SessionStart if PostCompact
    #         fired within 30 seconds
    if hook_type_lower == "sessionstart":
        if _is_within_dedup_window(base):
            return None

    # Step 4: write .codegen-compact-ts with current timestamp
    _write_compact_ts(base)

    # Step 5: read phase, psi, pipeline_id, intent from state
    phase = str(state.get("current_phase", "UNKNOWN"))
    psi = _extract_psi(state)
    pipeline_id = str(state.get("pipeline_id", ""))
    intent = str(state.get("intent", ""))

    # Step 6: build additionalContext string (<=2000 chars, FR-CC-015)
    additional_context = _build_context(
        hook_type_lower, phase, psi, pipeline_id=pipeline_id, intent=intent
    )

    # Step 7: write to hook.log (FR-CC-030..032)
    _write_hook_log(hook_type_lower, phase, psi, "injected")

    # Step 8: return hookSpecificOutput payload
    return {
        "hookSpecificOutput": {
            "hookEventName": hook_event_name,
            "additionalContext": additional_context,
        }
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_state(state_file: Path) -> dict | None:
    """Read and parse codegen-state.json; return None on any failure."""
    if not state_file.exists():
        return None
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _stale_cleanup(
    sentinel: Path,
    base: Path,
    reason: str,
    hook_event_name: str = "unknown",
) -> None:
    """
    FR-CC-013/021/022: Remove sentinel, log to hook.log, write to stderr.
    FR-CC-014: Idempotent — silently succeeds if sentinel already removed.
    """
    try:
        sentinel.unlink(missing_ok=True)
    except OSError:
        pass  # idempotent — already gone

    compact_ts = base / _COMPACT_TS_NAME
    try:
        compact_ts.unlink(missing_ok=True)
    except OSError:
        pass

    _write_stale_log(
        hook_event_name=hook_event_name,
        work_dir=base,
        status="STALE_CLEANUP",
        msg=reason,
    )

    sys.stderr.write(
        "[codegen-rig] stale sentinel removed: %s\n" % reason
    )


def _is_within_dedup_window(base: Path) -> bool:
    """
    ADR-003 / FR-CC-037: Return True if .codegen-compact-ts exists and the
    timestamp recorded is within the 30-second dedup window.
    """
    ts_file = base / _COMPACT_TS_NAME
    if not ts_file.exists():
        return False
    try:
        raw = ts_file.read_text(encoding="utf-8").strip()
        recorded = float(raw)
        now = datetime.now(tz=timezone.utc).timestamp()
        return (now - recorded) <= _DEDUP_WINDOW_SECONDS
    except (OSError, ValueError):
        return False


def _write_compact_ts(base: Path) -> None:
    """Write current UTC timestamp (float) to .codegen-compact-ts."""
    ts_file = base / _COMPACT_TS_NAME
    now = datetime.now(tz=timezone.utc).timestamp()
    try:
        ts_file.write_text(str(now), encoding="utf-8")
    except OSError:
        pass  # non-fatal — dedup may not work next time


def _extract_psi(state: dict) -> float:
    """Extract psi score from state; supports nested psi.score form."""
    # Nested form: psi: {score: 0.1, ...}
    psi_obj = state.get("psi")
    if isinstance(psi_obj, dict):
        raw = psi_obj.get("score", 0.0)
    else:
        # Flat form: psi_score: 0.1 (legacy)
        raw = state.get("psi_score", 0.0)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _build_context(
    hook_type: str,
    phase: str,
    psi: float,
    pipeline_id: str = "",
    intent: str = "",
) -> str:
    """
    Build additionalContext string (FR-CC-005, FR-CC-012, FR-CC-015).
    Truncates to _MAX_CONTEXT_CHARS if needed (safety guard).
    """
    if hook_type == "postcompact":
        text = _POSTCOMPACT_TEMPLATE.format(
            phase=phase, psi=psi, intent=intent
        )
    else:
        text = _SESSIONSTART_TEMPLATE.format(
            phase=phase, psi=psi, pipeline_id=pipeline_id, intent=intent
        )
    # FR-CC-015: hard cap at 2000 chars
    return text[:_MAX_CONTEXT_CHARS]


def _write_hook_log(
    hook_type: str,
    phase: str,
    psi: float,
    action: str,
) -> None:
    """
    FR-CC-030..032: Append a timestamped pipe-separated entry to hook.log.
    Format: timestamp | hook_type | phase=X | psi=Y | action=Z
    File is created (including parent dirs) if absent.
    """
    log_path = _HOOK_LOG_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=timezone.utc).isoformat()
    entry = (
        "%s | %s | phase=%s | psi=%.4f | action=%s"
        % (timestamp, hook_type, phase, psi, action)
    )
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(entry + "\n")
    except OSError:
        pass  # non-fatal — log failure must not block hook output


def _write_stale_log(
    hook_event_name: str,
    work_dir: Path,
    status: str,
    msg: str,
) -> None:
    """
    FR-CC-022: Append tab-separated stale cleanup entry to hook.log.
    Format: timestamp<TAB>hook_event<TAB>work_dir<TAB>status<TAB>msg
    File is created (including parent dirs) if absent.
    """
    log_path = _HOOK_LOG_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=timezone.utc).isoformat()
    entry = "\t".join(
        [timestamp, hook_event_name, str(work_dir), status, msg]
    )
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(entry + "\n")
    except OSError:
        pass  # non-fatal — log failure must not block hook output
