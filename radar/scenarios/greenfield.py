"""
radar/scenarios/greenfield.py — Greenfield lifecycle scenario.

13 agents, 9 phases, happy-path run that ends with status "done".
Registers itself as "greenfield" on import.
"""

from __future__ import annotations
from radar.scenarios import MockAgent, Scenario, ScenarioEvent, register

_RUN_ID = "squad-gf-20260322-1000"

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

_T = "2026-03-22T10:00:00Z"   # static dispatched_at for all agents

_AGENTS = [
    MockAgent("PROSPECTOR-1",  "PROSPECTOR",  "Prospector 1",  "idle", "discover",     _T),
    MockAgent("SCOUT-1",       "SCOUT",       "Scout 1",       "idle", "discover",     _T),
    MockAgent("SYNTHESIZER-1", "SYNTHESIZER", "Synthesizer 1", "idle", "synthesize",   _T),
    MockAgent("TRACKER-1",     "TRACKER",     "Tracker 1",     "idle", "synthesize",   _T),
    MockAgent("SAGE-1",        "SAGE",        "Sage 1",        "idle", "why1",         _T),
    MockAgent("CARTOGRAPHER-1","CARTOGRAPHER","Cartographer 1","idle", "cartographer", _T),
    MockAgent("SAGE-2",        "SAGE",        "Sage 2",        "idle", "why2",         _T),
    MockAgent("GATEKEEPER-1",  "GATEKEEPER",  "Gatekeeper 1",  "idle", "assess",       _T),
    MockAgent("ARCHITECT-1",   "ARCHITECT",   "Architect 1",   "idle", "solution",     _T),
    MockAgent("SENTINEL-1",    "SENTINEL",    "Sentinel 1",    "idle", "solution",     _T),
    MockAgent("ORCHESTRATOR-1","ORCHESTRATOR","Orchestrator 1","idle", "plan",         _T),
    MockAgent("REALIST-1",     "REALIST",     "Realist 1",     "idle", "finalize",     _T),
    MockAgent("AUDITOR-1",     "AUDITOR",     "Auditor 1",     "idle", "finalize",     _T),
]


def _ev(dispatch_id: str, state: str, phase: str, phase_display: str, delay_ms: int,
        completed_at: str | None = None, blocked_reason: str | None = None) -> ScenarioEvent:
    payload = {
        "dispatch_id": dispatch_id,
        "state": state,
        "phase": phase,
        "phase_display": phase_display,
        "updated_at": "2026-03-22T10:00:00Z",
    }
    if completed_at is not None:
        payload["completed_at"] = completed_at
    if blocked_reason is not None:
        payload["blocked_reason"] = blocked_reason
    return ScenarioEvent("agent_state_change", payload, delay_ms)


def _rsc(phase: str, phase_display: str, status: str = "running",
         completed_at: str | None = None, delay_ms: int = 500) -> ScenarioEvent:
    run = {
        "run_id": _RUN_ID,
        "status": status,
        "phase": phase,
        "phase_display": phase_display,
        "iteration": 1,
        "created_at": "2026-03-22T10:00:00Z",
        "updated_at": "2026-03-22T10:15:00Z",
        "completed_at": completed_at,
    }
    return ScenarioEvent("run_state_change", {"ts": "2026-03-22T10:15:00Z", "run": run}, delay_ms)


_EVENTS = [
    # ── discover ─────────────────────────────────────────────────────────────
    _ev("PROSPECTOR-1", "working",  "discover", "DISCOVER", 2000),
    _ev("PROSPECTOR-1", "complete", "discover", "DISCOVER", 2000, completed_at="2026-03-22T10:04:00Z"),
    _ev("SCOUT-1",      "working",  "discover", "DISCOVER", 2000),
    _ev("SCOUT-1",      "thinking", "discover", "DISCOVER", 3000),
    _ev("SCOUT-1",      "complete", "discover", "DISCOVER", 2000, completed_at="2026-03-22T10:09:00Z"),
    _rsc("synthesize", "SYNTHESIZE"),

    # ── synthesize ────────────────────────────────────────────────────────────
    _ev("SYNTHESIZER-1", "working",  "synthesize", "SYNTHESIZE", 2000),
    _ev("SYNTHESIZER-1", "thinking", "synthesize", "SYNTHESIZE", 3000),
    _ev("SYNTHESIZER-1", "complete", "synthesize", "SYNTHESIZE", 2000, completed_at="2026-03-22T10:14:00Z"),
    _ev("TRACKER-1",     "working",  "synthesize", "SYNTHESIZE", 2000),
    _ev("TRACKER-1",     "complete", "synthesize", "SYNTHESIZE", 2000, completed_at="2026-03-22T10:18:00Z"),
    _rsc("why1", "WHY1 — Assumption Challenge"),

    # ── why1 ──────────────────────────────────────────────────────────────────
    _ev("SAGE-1", "working",  "why1", "WHY1 — Assumption Challenge", 2000),
    _ev("SAGE-1", "thinking", "why1", "WHY1 — Assumption Challenge", 3000),
    _ev("SAGE-1", "complete", "why1", "WHY1 — Assumption Challenge", 2000, completed_at="2026-03-22T10:23:00Z"),
    _rsc("cartographer", "CARTOGRAPHER"),

    # ── cartographer ──────────────────────────────────────────────────────────
    _ev("CARTOGRAPHER-1", "working",  "cartographer", "CARTOGRAPHER", 2000),
    _ev("CARTOGRAPHER-1", "thinking", "cartographer", "CARTOGRAPHER", 3000),
    _ev("CARTOGRAPHER-1", "complete", "cartographer", "CARTOGRAPHER", 2000, completed_at="2026-03-22T10:28:00Z"),
    _rsc("why2", "WHY2 — Spec Validation"),

    # ── why2 ──────────────────────────────────────────────────────────────────
    _ev("SAGE-2", "working",  "why2", "WHY2 — Spec Validation", 2000),
    _ev("SAGE-2", "thinking", "why2", "WHY2 — Spec Validation", 3000),
    _ev("SAGE-2", "complete", "why2", "WHY2 — Spec Validation", 2000, completed_at="2026-03-22T10:33:00Z"),
    _rsc("assess", "ASSESS — Kill Gate"),

    # ── assess ────────────────────────────────────────────────────────────────
    _ev("GATEKEEPER-1", "working",  "assess", "ASSESS — Kill Gate", 2000),
    _ev("GATEKEEPER-1", "thinking", "assess", "ASSESS — Kill Gate", 3000),
    _ev("GATEKEEPER-1", "complete", "assess", "ASSESS — Kill Gate", 2000, completed_at="2026-03-22T10:38:00Z"),
    _rsc("solution", "SOLUTION"),

    # ── solution ──────────────────────────────────────────────────────────────
    _ev("ARCHITECT-1", "working",  "solution", "SOLUTION", 2000),
    _ev("ARCHITECT-1", "thinking", "solution", "SOLUTION", 3000),
    _ev("ARCHITECT-1", "complete", "solution", "SOLUTION", 2000, completed_at="2026-03-22T10:43:00Z"),
    _ev("SENTINEL-1",  "working",  "solution", "SOLUTION", 2000),
    _ev("SENTINEL-1",  "complete", "solution", "SOLUTION", 2000, completed_at="2026-03-22T10:47:00Z"),
    _rsc("plan", "PLAN"),

    # ── plan ──────────────────────────────────────────────────────────────────
    _ev("ORCHESTRATOR-1", "working",  "plan", "PLAN", 2000),
    _ev("ORCHESTRATOR-1", "thinking", "plan", "PLAN", 3000),
    _ev("ORCHESTRATOR-1", "complete", "plan", "PLAN", 2000, completed_at="2026-03-22T10:52:00Z"),
    _rsc("finalize", "FINALIZE"),

    # ── finalize ──────────────────────────────────────────────────────────────
    _ev("REALIST-1", "working",  "finalize", "FINALIZE", 2000),
    _ev("REALIST-1", "complete", "finalize", "FINALIZE", 2000, completed_at="2026-03-22T10:56:00Z"),
    _ev("AUDITOR-1", "working",  "finalize", "FINALIZE", 2000),
    _ev("AUDITOR-1", "thinking", "finalize", "FINALIZE", 3000),
    _ev("AUDITOR-1", "complete", "finalize", "FINALIZE", 2000, completed_at="2026-03-22T11:01:00Z"),
    # terminal run_state_change — status: done
    _rsc("finalize", "FINALIZE", status="done",
         completed_at="2026-03-22T11:01:30Z", delay_ms=1000),
]

_JOURNAL = {
    "SCOUT-1": [
        {"id": "j-SCOUT-1-001", "dispatch_id": "SCOUT-1", "codename": "SCOUT",
         "run_id": _RUN_ID, "timestamp_ms": 1742637060000, "type": "finding",
         "content": "Identified 3 bounded contexts: auth, payments, notifications — different ownership, separate schemas"},
        {"id": "j-SCOUT-1-002", "dispatch_id": "SCOUT-1", "codename": "SCOUT",
         "run_id": _RUN_ID, "timestamp_ms": 1742637090000, "type": "decision",
         "content": "Treating payments and notifications as separate bounded contexts — different release cadence confirmed by git log"},
        {"id": "j-SCOUT-1-003", "dispatch_id": "SCOUT-1", "codename": "SCOUT",
         "run_id": _RUN_ID, "timestamp_ms": 1742637125000, "type": "risk",
         "content": "No API versioning strategy found — /v1/ prefix exists but no deprecation policy in docs"},
    ],
    "CARTOGRAPHER-1": [
        {"id": "j-CART-1-001", "dispatch_id": "CARTOGRAPHER-1", "codename": "CARTOGRAPHER",
         "run_id": _RUN_ID, "timestamp_ms": 1742638200000, "type": "finding",
         "content": "Payment flow requires 4 external integrations: Stripe, fraud-check, email, ledger"},
        {"id": "j-CART-1-002", "dispatch_id": "CARTOGRAPHER-1", "codename": "CARTOGRAPHER",
         "run_id": _RUN_ID, "timestamp_ms": 1742638260000, "type": "decision",
         "content": "Separating idempotency key management as a cross-cutting concern — applies to all payment mutations"},
        {"id": "j-CART-1-003", "dispatch_id": "CARTOGRAPHER-1", "codename": "CARTOGRAPHER",
         "run_id": _RUN_ID, "timestamp_ms": 1742638320000, "type": "concern",
         "content": "Refund flow is underspecified — no mention of partial refunds or currency conversion"},
    ],
    "GATEKEEPER-1": [
        {"id": "j-GATE-1-001", "dispatch_id": "GATEKEEPER-1", "codename": "GATEKEEPER",
         "run_id": _RUN_ID, "timestamp_ms": 1742640000000, "type": "assessment",
         "content": "PASS — spec coverage 94%, all critical requirements resolved, RICE score 78"},
        {"id": "j-GATE-1-002", "dispatch_id": "GATEKEEPER-1", "codename": "GATEKEEPER",
         "run_id": _RUN_ID, "timestamp_ms": 1742640060000, "type": "finding",
         "content": "3 low-priority requirements deferred to v2 — documented in spec with rationale"},
    ],
    "ORCHESTRATOR-1": [
        {"id": "j-ORCH-1-001", "dispatch_id": "ORCHESTRATOR-1", "codename": "ORCHESTRATOR",
         "run_id": _RUN_ID, "timestamp_ms": 1742641800000, "type": "decision",
         "content": "Splitting into 6 implementation tasks — payment core, webhook handler, idempotency, refunds, admin UI, migration"},
        {"id": "j-ORCH-1-002", "dispatch_id": "ORCHESTRATOR-1", "codename": "ORCHESTRATOR",
         "run_id": _RUN_ID, "timestamp_ms": 1742641860000, "type": "finding",
         "content": "Payment core and idempotency must be sequential — all other tasks can run in parallel after"},
    ],
}

GREENFIELD = Scenario(
    name="greenfield",
    description="Happy-path lifecycle: 13 agents, 9 phases, ends with status=done (~8 min simulated)",
    initial_agents=_AGENTS,
    event_sequence=_EVENTS,
    initial_run=_INITIAL_RUN,
    journal_entries=_JOURNAL,
    loop=False,
)
register(GREENFIELD)
