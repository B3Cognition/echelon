"""
radar/scenarios/blocked_escalation.py — Blocked escalation lifecycle scenario.

GATEKEEPER-1 blocks at assess, triggering a CARTOGRAPHER-2 rework loop.
15 agents, 11 phases, ends with status=done.
Registers itself as "blocked-escalation" on import.
"""

from __future__ import annotations
from radar.scenarios import MockAgent, Scenario, ScenarioEvent, register

_RUN_ID = "squad-be-20260322-1000"

_INITIAL_RUN = {
    "run_id": _RUN_ID,
    "status": "running",
    "phase": "discover",
    "phase_display": "DISCOVER",
    "iteration": 1,
    "created_at": "2026-03-22T10:00:00Z",
    "updated_at": "2026-03-22T10:00:00Z",
    "completed_at": None,
}

_T = "2026-03-22T10:00:00Z"

_AGENTS = [
    MockAgent("PROSPECTOR-1",  "PROSPECTOR",  "Prospector 1",  "idle", "discover",      _T),
    MockAgent("SCOUT-1",       "SCOUT",       "Scout 1",       "idle", "discover",      _T),
    MockAgent("SYNTHESIZER-1", "SYNTHESIZER", "Synthesizer 1", "idle", "synthesize",    _T),
    MockAgent("TRACKER-1",     "TRACKER",     "Tracker 1",     "idle", "synthesize",    _T),
    MockAgent("SAGE-1",        "SAGE",        "Sage 1",        "idle", "why1",          _T),
    MockAgent("CARTOGRAPHER-1","CARTOGRAPHER","Cartographer 1","idle", "cartographer",  _T),
    MockAgent("SAGE-2",        "SAGE",        "Sage 2",        "idle", "why2",          _T),
    MockAgent("GATEKEEPER-1",  "GATEKEEPER",  "Gatekeeper 1",  "idle", "assess",        _T),
    MockAgent("CARTOGRAPHER-2","CARTOGRAPHER","Cartographer 2","idle", "cartographer",  _T),
    MockAgent("SAGE-3",        "SAGE",        "Sage 3",        "idle", "why3",          _T),
    MockAgent("GATEKEEPER-2",  "GATEKEEPER",  "Gatekeeper 2",  "idle", "assess",        _T),
    MockAgent("ARCHITECT-1",   "ARCHITECT",   "Architect 1",   "idle", "solution",      _T),
    MockAgent("SENTINEL-1",    "SENTINEL",    "Sentinel 1",    "idle", "solution",      _T),
    MockAgent("ORCHESTRATOR-1","ORCHESTRATOR","Orchestrator 1","idle", "plan",          _T),
    MockAgent("REALIST-1",     "REALIST",     "Realist 1",     "idle", "finalize",      _T),
]


def _ev(dispatch_id, state, phase, phase_display, delay_ms,
        completed_at=None, blocked_reason=None):
    payload = {"dispatch_id": dispatch_id, "state": state, "phase": phase,
               "phase_display": phase_display, "updated_at": "2026-03-22T10:00:00Z"}
    if completed_at:
        payload["completed_at"] = completed_at
    if blocked_reason is not None:
        payload["blocked_reason"] = blocked_reason
    return ScenarioEvent("agent_state_change", payload, delay_ms)


def _rsc(phase, phase_display, status="running", completed_at=None, delay_ms=500):
    run = {"run_id": _RUN_ID, "status": status, "phase": phase, "phase_display": phase_display,
           "iteration": 1, "created_at": "2026-03-22T10:00:00Z",
           "updated_at": "2026-03-22T10:15:00Z", "completed_at": completed_at}
    return ScenarioEvent("run_state_change", {"ts": "2026-03-22T10:15:00Z", "run": run}, delay_ms)


_EVENTS = [
    # ── discover ─────────────────────────────────────────────────────────────
    _ev("PROSPECTOR-1", "working",  "discover", "DISCOVER", 2000),
    _ev("PROSPECTOR-1", "complete", "discover", "DISCOVER", 2000, "2026-03-22T10:04:00Z"),
    _ev("SCOUT-1",      "working",  "discover", "DISCOVER", 2000),
    _ev("SCOUT-1",      "thinking", "discover", "DISCOVER", 3000),
    _ev("SCOUT-1",      "complete", "discover", "DISCOVER", 2000, "2026-03-22T10:09:00Z"),
    _rsc("synthesize", "SYNTHESIZE"),

    # ── synthesize ────────────────────────────────────────────────────────────
    _ev("SYNTHESIZER-1", "working",  "synthesize", "SYNTHESIZE", 2000),
    _ev("SYNTHESIZER-1", "thinking", "synthesize", "SYNTHESIZE", 3000),
    _ev("SYNTHESIZER-1", "complete", "synthesize", "SYNTHESIZE", 2000, "2026-03-22T10:14:00Z"),
    _ev("TRACKER-1",     "working",  "synthesize", "SYNTHESIZE", 2000),
    _ev("TRACKER-1",     "complete", "synthesize", "SYNTHESIZE", 2000, "2026-03-22T10:18:00Z"),
    _rsc("why1", "WHY1 — Assumption Challenge"),

    # ── why1 ──────────────────────────────────────────────────────────────────
    _ev("SAGE-1", "working",  "why1", "WHY1 — Assumption Challenge", 2000),
    _ev("SAGE-1", "thinking", "why1", "WHY1 — Assumption Challenge", 3000),
    _ev("SAGE-1", "complete", "why1", "WHY1 — Assumption Challenge", 2000, "2026-03-22T10:23:00Z"),
    _rsc("cartographer", "CARTOGRAPHER"),

    # ── cartographer (first pass) ─────────────────────────────────────────────
    _ev("CARTOGRAPHER-1", "working",  "cartographer", "CARTOGRAPHER", 2000),
    _ev("CARTOGRAPHER-1", "thinking", "cartographer", "CARTOGRAPHER", 3000),
    _ev("CARTOGRAPHER-1", "complete", "cartographer", "CARTOGRAPHER", 2000, "2026-03-22T10:28:00Z"),
    _rsc("why2", "WHY2 — Spec Validation"),

    # ── why2 ──────────────────────────────────────────────────────────────────
    _ev("SAGE-2", "working",  "why2", "WHY2 — Spec Validation", 2000),
    _ev("SAGE-2", "thinking", "why2", "WHY2 — Spec Validation", 3000),
    _ev("SAGE-2", "complete", "why2", "WHY2 — Spec Validation", 2000, "2026-03-22T10:33:00Z"),
    _rsc("assess", "ASSESS — Kill Gate"),

    # ── assess (GATEKEEPER-1 blocks) ─────────────────────────────────────────
    _ev("GATEKEEPER-1", "working",  "assess", "ASSESS — Kill Gate", 2000),
    _ev("GATEKEEPER-1", "thinking", "assess", "ASSESS — Kill Gate", 4000),
    _ev("GATEKEEPER-1", "blocked",  "assess", "ASSESS — Kill Gate", 3000,
        blocked_reason="Spec coverage below kill threshold — 3 critical requirements unresolved"),
    _rsc("assess", "ASSESS — Kill Gate", status="blocked"),

    # 8000ms simulates human review window; GATEKEEPER-1 resumes working
    _ev("GATEKEEPER-1", "working", "assess", "ASSESS — Kill Gate", 8000,
        blocked_reason=None),  # blocked_reason=None clears it in mock_snapshot
    _rsc("cartographer", "CARTOGRAPHER (rework)", status="running"),

    # ── cartographer rework (CARTOGRAPHER-2) ─────────────────────────────────
    _ev("CARTOGRAPHER-2", "working",  "cartographer", "CARTOGRAPHER (rework)", 1000),
    _ev("CARTOGRAPHER-2", "thinking", "cartographer", "CARTOGRAPHER (rework)", 3000),
    _ev("CARTOGRAPHER-2", "complete", "cartographer", "CARTOGRAPHER (rework)", 2000, "2026-03-22T10:56:00Z"),
    _rsc("why3", "WHY3 — Consensus"),

    # ── why3 ──────────────────────────────────────────────────────────────────
    _ev("SAGE-3", "working",  "why3", "WHY3 — Consensus", 2000),
    _ev("SAGE-3", "thinking", "why3", "WHY3 — Consensus", 3000),
    _ev("SAGE-3", "complete", "why3", "WHY3 — Consensus", 2000, "2026-03-22T11:01:00Z"),
    _rsc("assess", "ASSESS — Kill Gate"),

    # ── assess (GATEKEEPER-2 passes) ──────────────────────────────────────────
    _ev("GATEKEEPER-2", "working",  "assess", "ASSESS — Kill Gate", 2000),
    _ev("GATEKEEPER-2", "thinking", "assess", "ASSESS — Kill Gate", 3000),
    _ev("GATEKEEPER-2", "complete", "assess", "ASSESS — Kill Gate", 2000, "2026-03-22T11:06:00Z"),
    _rsc("solution", "SOLUTION"),

    # ── solution ──────────────────────────────────────────────────────────────
    _ev("ARCHITECT-1", "working",  "solution", "SOLUTION", 2000),
    _ev("ARCHITECT-1", "thinking", "solution", "SOLUTION", 3000),
    _ev("ARCHITECT-1", "complete", "solution", "SOLUTION", 2000, "2026-03-22T11:11:00Z"),
    _ev("SENTINEL-1",  "working",  "solution", "SOLUTION", 2000),
    _ev("SENTINEL-1",  "complete", "solution", "SOLUTION", 2000, "2026-03-22T11:15:00Z"),
    _rsc("plan", "PLAN"),

    # ── plan ──────────────────────────────────────────────────────────────────
    _ev("ORCHESTRATOR-1", "working",  "plan", "PLAN", 2000),
    _ev("ORCHESTRATOR-1", "thinking", "plan", "PLAN", 3000),
    _ev("ORCHESTRATOR-1", "complete", "plan", "PLAN", 2000, "2026-03-22T11:20:00Z"),
    _rsc("finalize", "FINALIZE"),

    # ── finalize ──────────────────────────────────────────────────────────────
    _ev("REALIST-1", "working",  "finalize", "FINALIZE", 2000),
    _ev("REALIST-1", "complete", "finalize", "FINALIZE", 2000, "2026-03-22T11:24:00Z"),
    # AUDITOR-1 intentionally absent — 15 agents per spec; finalize simplified to REALIST-1 only
    _rsc("finalize", "FINALIZE", status="done", completed_at="2026-03-22T11:24:30Z", delay_ms=1000),
]

_JOURNAL = {
    "GATEKEEPER-1": [
        {"id": "j-GATE-1-001", "dispatch_id": "GATEKEEPER-1", "codename": "GATEKEEPER",
         "run_id": _RUN_ID, "timestamp_ms": 1742641200000, "type": "assessment",
         "content": "BLOCK — 3 critical requirements unresolved: payment idempotency (REQ-047), refund edge cases (REQ-051), fraud-check timeout handling (REQ-059)"},
        {"id": "j-GATE-1-002", "dispatch_id": "GATEKEEPER-1", "codename": "GATEKEEPER",
         "run_id": _RUN_ID, "timestamp_ms": 1742641260000, "type": "decision",
         "content": "Routing back to CARTOGRAPHER-2 for rework — spec must explicitly define all three failure modes before re-assessment"},
        {"id": "j-GATE-1-003", "dispatch_id": "GATEKEEPER-1", "codename": "GATEKEEPER",
         "run_id": _RUN_ID, "timestamp_ms": 1742649600000, "type": "assessment",
         "content": "Resumed after human review — rework completed, requirements now fully specified"},
    ],
    "CARTOGRAPHER-2": [
        {"id": "j-CART-2-001", "dispatch_id": "CARTOGRAPHER-2", "codename": "CARTOGRAPHER",
         "run_id": _RUN_ID, "timestamp_ms": 1742650200000, "type": "decision",
         "content": "Added explicit failure mode specs for REQ-047, REQ-051, REQ-059 — idempotency key TTL set to 24h"},
        {"id": "j-CART-2-002", "dispatch_id": "CARTOGRAPHER-2", "codename": "CARTOGRAPHER",
         "run_id": _RUN_ID, "timestamp_ms": 1742650260000, "type": "amendment",
         "content": "Updated REQ-059: fraud-check timeout falls back to allow-with-flag, not reject — reduces false negatives"},
    ],
    "GATEKEEPER-2": [
        {"id": "j-GATE-2-001", "dispatch_id": "GATEKEEPER-2", "codename": "GATEKEEPER",
         "run_id": _RUN_ID, "timestamp_ms": 1742652600000, "type": "assessment",
         "content": "PASS — all previously blocked requirements now resolved, spec coverage 97%"},
    ],
}

BLOCKED_ESCALATION = Scenario(
    name="blocked-escalation",
    description="GATEKEEPER blocks at assess, triggers rework loop: 15 agents, 11 phases, ends status=done",
    initial_agents=_AGENTS,
    event_sequence=_EVENTS,
    initial_run=_INITIAL_RUN,
    journal_entries=_JOURNAL,
    loop=False,
)
register(BLOCKED_ESCALATION)
