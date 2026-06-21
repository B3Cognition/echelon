"""WS1: a blocked or incomplete Phase-A run must never be reported as ready.

Regression for the live finding (docs/findings/2026-06-20-blocked-run-reports-
ready-to-build.md): a run with only constitution.md — or a blocked run with no
spec/tasks — surfaced "READY TO BUILD" / "Build is ready — nothing left to do".
"""
import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from echelon import cli


pytestmark = pytest.mark.unit


# ── Pure readiness predicate ──────────────────────────────────────────────

def test_buildable_true_only_when_clean_and_not_blocked():
    assert cli._phase_a_buildable("done", []) is True

def test_not_buildable_when_blockers_present():
    assert cli._phase_a_buildable("done", ["tasks.md absent"]) is False

def test_not_buildable_when_run_blocked_even_with_no_blockers():
    # The exact bug: empty blocker list but the run is blocked → NOT ready.
    assert cli._phase_a_buildable("blocked", []) is False

def test_not_buildable_when_interrupted():
    assert cli._phase_a_buildable("interrupted", []) is False


# ── _next_continue_phase never returns None for a not-ready run ────────────

def _scaffold(tmp_path: Path, *, state: dict, constitution: bool) -> None:
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(json.dumps(state))
    (tmp_path / "runs" / ".current").write_text("run-1")
    if constitution:
        mem = tmp_path / ".specify" / "memory"
        mem.mkdir(parents=True)
        (mem / "constitution.md").write_text("# Constitution\n\nReal project rules.\n")

def test_constitution_only_run_is_not_ready(tmp_path):
    # constitution complete, but no spec dir / spec.md → not ready.
    _scaffold(tmp_path,
              state={"completed_phases": ["phase1-constitution"], "status": "running"},
              constitution=True)
    nxt = cli._next_continue_phase(tmp_path)
    assert nxt is not None, "constitution-only run must not report build-ready"

def test_blocked_run_without_artifacts_is_not_ready(tmp_path):
    _scaffold(tmp_path,
              state={"completed_phases": ["phase1-constitution"], "status": "blocked",
                     "blocked_reason": "missing_echelon_result"},
              constitution=True)
    nxt = cli._next_continue_phase(tmp_path)
    assert nxt is not None, "blocked run with no build artifacts must not report ready"
