"""preflight.py — Preflight runner and dependency probe registry.

Implements run_preflight() per contracts/preflight-contract.md (ADR-002).

Supported dependencies:
    understanding    — probe run-understanding.sh
    revenge          — probe GOLDDIGGER entry script
    skill:GOLDDIGGER — probe subagent skill availability
    kb_schema        — verify all 5 KB files present and schema-valid

Pure function contract:
    - COMMANDER persists journal writes (this module only returns results)
    - No agent dispatch
    - No state.json writes (caller's responsibility)
    - Budget <= 10s per preflight

Routing boundary:
    - Preflight nodes are routed here by COMMANDER
    - The typed evaluator (evaluator.py) MUST skip preflight nodes entirely
"""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------


PreflightStatus = str  # "AVAILABLE" | "UNAVAILABLE" | "DEGRADED"
ReasonCode = str       # "n/a" | "missing_install" | "script_error" | "timeout" | ...

PREFLIGHT_BUDGET_SECONDS = 10.0


class PreflightResult(dict):
    """Return type of run_preflight.
    Keys: dependency, status, reason_code, exit_code, stderr_excerpt,
          detected_cause, checked_at, next_node
    """


class PreflightNoMatchingTransition(Exception):
    """Raised when no transition in the node matches the status returned by the probe."""

    def __init__(self, node_id: str, status: str) -> None:
        super().__init__(
            f"PreflightNoMatchingTransition: no transition in node '{node_id}' "
            f"matches status '{status}'"
        )


# ---------------------------------------------------------------------------
# Probe registry
# ---------------------------------------------------------------------------

# Maps dependency name → probe function
# Probe signature: (state, config, ext_dir) -> (status, reason_code, exit_code, stderr_excerpt, detected_cause)
ProbeFunc = Callable[[dict, dict, Path], tuple[str, str, Optional[int], str, str]]

_PROBE_REGISTRY: dict[str, ProbeFunc] = {}


def register_probe(dependency: str, func: ProbeFunc) -> None:
    """Register a probe function for a dependency name."""
    _PROBE_REGISTRY[dependency] = func


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _truncate(text: str, max_bytes: int = 2048) -> str:
    """Truncate text to max_bytes bytes (FR-OBSERV-001/002)."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore") + "... [truncated]"


def _run_script(script_path: Path, timeout: float = 5.0) -> tuple[int, str, str]:
    """Run a script and return (exit_code, stdout, stderr). Times out after timeout seconds."""
    try:
        result = subprocess.run(
            [str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except Exception as exc:
        return -2, "", str(exc)


# ---------------------------------------------------------------------------
# Probe: understanding
# ---------------------------------------------------------------------------


def _probe_understanding(
    state: dict, config: dict, ext_dir: Path
) -> tuple[str, str, Optional[int], str, str]:
    """Probe speckit-understanding availability.

    Checks for run-understanding.sh and optionally runs a smoke test.
    """
    # Look for run-understanding.sh in known locations
    candidate_paths = [
        ext_dir / "scripts" / "bash" / "run-understanding.sh",
        ext_dir.parent / "speckit-understanding" / "run-understanding.sh",
    ]

    script = None
    for path in candidate_paths:
        if path.exists():
            script = path
            break

    if script is None:
        return (
            "UNAVAILABLE",
            "missing_install",
            None,
            "run-understanding.sh not found in expected locations",
            "speckit-understanding extension not installed",
        )

    if not os.access(str(script), os.X_OK):
        return (
            "DEGRADED",
            "permission_denied",
            None,
            f"run-understanding.sh found at {script} but not executable",
            "Script not executable — may need chmod +x",
        )

    # Run a smoke probe with --check flag (if supported) or just --help
    exit_code, stdout, stderr = _run_script(script, timeout=5.0)
    if stderr == "TIMEOUT":
        return ("UNAVAILABLE", "timeout", -1, "TIMEOUT: script did not respond in 5s", "slow startup")
    if exit_code not in (0, 1, 2):  # 0=ok, 1=help, 2=check-only; others are errors
        return (
            "DEGRADED",
            "script_error",
            exit_code,
            _truncate(stderr or stdout),
            f"exit_code={exit_code}",
        )

    return ("AVAILABLE", "n/a", exit_code, "", "smoke probe passed")


# ---------------------------------------------------------------------------
# Probe: revenge (GOLDDIGGER)
# ---------------------------------------------------------------------------


def _probe_revenge(
    state: dict, config: dict, ext_dir: Path
) -> tuple[str, str, Optional[int], str, str]:
    """Probe speckit-revenge / GOLDDIGGER availability."""
    # Check for revenge extension entry point
    candidate_paths = [
        ext_dir.parent / "speckit-revenge" / "golddigger.sh",
        ext_dir.parent / "speckit-revenge" / "run.sh",
    ]

    for path in candidate_paths:
        if path.exists():
            if os.access(str(path), os.X_OK):
                return ("AVAILABLE", "n/a", None, "", "revenge entry script found and executable")
            else:
                return ("DEGRADED", "permission_denied", None,
                        f"{path} not executable", "needs chmod +x")

    return (
        "UNAVAILABLE",
        "missing_install",
        None,
        "speckit-revenge entry script not found",
        "speckit-revenge extension not installed",
    )


# ---------------------------------------------------------------------------
# Probe: skill:GOLDDIGGER
# ---------------------------------------------------------------------------


def _probe_skill_golddigger(
    state: dict, config: dict, ext_dir: Path
) -> tuple[str, str, Optional[int], str, str]:
    """Probe whether GOLDDIGGER skill is provisioned in the current environment.

    Since we cannot directly inspect the subagent tool set from Python,
    we use a heuristic: check if the skill definition file exists.
    """
    # Check skill manifest
    skill_paths = [
        ext_dir.parent.parent.parent / ".claude" / "skills" / "speckit-echelon-run",
        ext_dir.parent.parent.parent / ".claude" / "skills" / "speckit-revenge-extract",
    ]

    for path in skill_paths:
        if path.exists():
            return ("AVAILABLE", "n/a", None, "", f"skill manifest found at {path}")

    # Check if golddigger agent file exists (weaker signal)
    golddigger_agent = ext_dir / "agents" / "exploration" / "golddigger.md"
    if golddigger_agent.exists():
        return (
            "DEGRADED",
            "skill_unprovisioned",
            None,
            "GOLDDIGGER agent file found but skill not provisioned in tool set",
            "Agent file exists but Skill tool registration unclear",
        )

    return (
        "UNAVAILABLE",
        "skill_unprovisioned",
        None,
        "GOLDDIGGER skill not found in tool set or manifest",
        "skill:GOLDDIGGER not provisioned",
    )


# ---------------------------------------------------------------------------
# Probe: kb_schema
# ---------------------------------------------------------------------------


def _probe_kb_schema(
    state: dict, config: dict, ext_dir: Path
) -> tuple[str, str, Optional[int], str, str]:
    """Probe KB schema validity: verify all 5 KB files present and schema-valid."""
    kb_dir = ext_dir / "knowledge-base"
    required_files = [
        "calibration-profile.yaml",
        "estimates-log.yaml",
        "patterns.yaml",
        "pitfalls.yaml",
        "agent-scores.yaml",
    ]

    missing = []
    invalid = []

    for fname in required_files:
        fpath = kb_dir / fname
        if not fpath.exists():
            missing.append(fname)
            continue
        # Minimal schema check: must have schema_version
        try:
            text = fpath.read_text(encoding="utf-8")
            if "schema_version:" not in text:
                invalid.append(f"{fname}:missing_schema_version")
        except Exception as exc:
            invalid.append(f"{fname}:{exc}")

    if missing:
        return (
            "UNAVAILABLE",
            "missing_install",
            None,
            f"Missing KB files: {', '.join(missing)}",
            "KB not seeded — run kb-seed.sh",
        )

    if invalid:
        return (
            "DEGRADED",
            "script_error",
            None,
            f"Invalid KB files: {'; '.join(invalid)}",
            "KB schema validation failed — run kb-recover.sh or kb-seed.sh",
        )

    return ("AVAILABLE", "n/a", None, "", "all 5 KB files present and schema-valid")


# ---------------------------------------------------------------------------
# Register probes
# ---------------------------------------------------------------------------

register_probe("understanding", _probe_understanding)
register_probe("revenge", _probe_revenge)
register_probe("skill:GOLDDIGGER", _probe_skill_golddigger)
register_probe("kb_schema", _probe_kb_schema)


# ---------------------------------------------------------------------------
# Transition resolution
# ---------------------------------------------------------------------------


def _resolve_next_node(
    node: dict,
    status: str,
    meta_run: bool,
) -> str:
    """Resolve the next_node from the preflight node's transitions based on status."""
    transitions = node.get("transitions", [])

    for transition in transitions:
        condition = str(transition.get("condition", "")).strip()
        target = transition.get("to", "")

        # Try to match the condition against our status
        # Conditions for preflight nodes use the form:
        #   preflight_result = AVAILABLE
        #   preflight_result = DEGRADED
        #   preflight_result = UNAVAILABLE AND meta_run = false
        #   preflight_result = UNAVAILABLE AND meta_run = true

        # Normalize: strip "preflight_result = " prefix
        cond_status = None
        cond_meta_run = None

        if "AND" in condition:
            parts = condition.split("AND")
            for part in parts:
                part = part.strip()
                if "preflight_result" in part:
                    val = part.split("=", 1)[-1].strip()
                    cond_status = val
                elif "meta_run" in part:
                    val = part.split("=", 1)[-1].strip()
                    cond_meta_run = val
        else:
            if "preflight_result" in condition:
                cond_status = condition.split("=", 1)[-1].strip()

        # Match?
        if cond_status is not None and cond_status == status:
            if cond_meta_run is not None:
                # Must also match meta_run
                expected_meta = cond_meta_run == "true"
                if meta_run == expected_meta:
                    return target
            else:
                # No meta_run constraint
                return target

    # No match found — raise
    raise PreflightNoMatchingTransition(node.get("id", "unknown"), status)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_preflight(
    node: dict,
    state: dict,
    config: dict,
    ext_dir: Optional[Path] = None,
) -> PreflightResult:
    """Run the preflight probe for a preflight node.

    Args:
        node:    The preflight node dict from definition.yaml.
        state:   Schema-validated state.json dict.
        config:  echelon-config.yml dict.
        ext_dir: Extension root directory (auto-detected if None).

    Returns:
        PreflightResult dict.

    Raises:
        PreflightNoMatchingTransition: if no transition matches the probe result.
    """
    t_start = time.monotonic()

    dependency = node.get("dependency", "")
    node_id = node.get("id", "unknown")
    meta_run = bool(state.get("meta_run", False))

    if ext_dir is None:
        ext_dir = Path(__file__).resolve().parent.parent

    # Find probe function
    probe = _PROBE_REGISTRY.get(dependency)
    if probe is None:
        # Unknown dependency — treat as UNAVAILABLE
        result = PreflightResult(
            dependency=dependency,
            status="UNAVAILABLE",
            reason_code="missing_install",
            exit_code=None,
            stderr_excerpt=f"No probe registered for dependency '{dependency}'",
            detected_cause=f"Unregistered dependency: {dependency}",
            checked_at=_iso_now(),
            next_node="",
        )
        try:
            result["next_node"] = _resolve_next_node(node, "UNAVAILABLE", meta_run)
        except PreflightNoMatchingTransition:
            result["next_node"] = ""
        return result

    # Run probe with budget enforcement
    try:
        status, reason_code, exit_code, stderr_excerpt, detected_cause = probe(
            state, config, ext_dir
        )
    except Exception as exc:
        status = "UNAVAILABLE"
        reason_code = "script_error"
        exit_code = None
        stderr_excerpt = _truncate(str(exc))
        detected_cause = "probe raised exception"

    elapsed = time.monotonic() - t_start
    if elapsed > PREFLIGHT_BUDGET_SECONDS:
        status = "UNAVAILABLE"
        reason_code = "timeout"
        exit_code = -1
        stderr_excerpt = f"TIMEOUT: preflight exceeded {PREFLIGHT_BUDGET_SECONDS}s budget (took {elapsed:.1f}s)"
        detected_cause = "timeout"

    # Resolve next node
    next_node = _resolve_next_node(node, status, meta_run)

    return PreflightResult(
        dependency=dependency,
        status=status,
        reason_code=reason_code,
        exit_code=exit_code,
        stderr_excerpt=_truncate(stderr_excerpt),
        detected_cause=detected_cause,
        checked_at=_iso_now(),
        next_node=next_node,
    )
