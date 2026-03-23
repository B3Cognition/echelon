"""
radar/scenarios/brownfield.py — Brownfield lifecycle scenario.

14 agents, 9 phases — identical to greenfield but GOLDDIGGER-1 runs between
PROSPECTOR-1 and SCOUT-1 in the discover phase.
Registers itself as "brownfield" on import.
"""

from __future__ import annotations
from radar.scenarios import MockAgent, Scenario, ScenarioEvent, register

_RUN_ID = "squad-bf-20260322-1000"

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
    MockAgent("PROSPECTOR-1",  "PROSPECTOR",  "Prospector 1",  "idle", "discover",     _T),
    MockAgent("GOLDDIGGER-1",  "GOLDDIGGER",  "Golddigger 1",  "idle", "discover",     _T),
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


def _ev(dispatch_id, state, phase, phase_display, delay_ms, completed_at=None):
    payload = {"dispatch_id": dispatch_id, "state": state, "phase": phase,
               "phase_display": phase_display, "updated_at": "2026-03-22T10:00:00Z"}
    if completed_at:
        payload["completed_at"] = completed_at
    return ScenarioEvent("agent_state_change", payload, delay_ms)


def _rsc(phase, phase_display, status="running", completed_at=None, delay_ms=500):
    run = {"run_id": _RUN_ID, "status": status, "phase": phase, "phase_display": phase_display,
           "iteration": 1, "created_at": "2026-03-22T10:00:00Z",
           "updated_at": "2026-03-22T10:15:00Z", "completed_at": completed_at}
    return ScenarioEvent("run_state_change", {"ts": "2026-03-22T10:15:00Z", "run": run}, delay_ms)


_EVENTS = [
    # ── discover (with GOLDDIGGER-1) ──────────────────────────────────────────
    _ev("PROSPECTOR-1",  "working",  "discover", "DISCOVER", 2000),
    _ev("PROSPECTOR-1",  "complete", "discover", "DISCOVER", 2000, "2026-03-22T10:04:00Z"),
    _ev("GOLDDIGGER-1",  "working",  "discover", "DISCOVER", 2000),
    _ev("GOLDDIGGER-1",  "thinking", "discover", "DISCOVER", 5000),  # Mode 1 survey
    _ev("GOLDDIGGER-1",  "complete", "discover", "DISCOVER", 1000,  "2026-03-22T10:12:00Z"),
    _ev("SCOUT-1",       "working",  "discover", "DISCOVER", 2000),
    _ev("SCOUT-1",       "thinking", "discover", "DISCOVER", 3000),
    _ev("SCOUT-1",       "complete", "discover", "DISCOVER", 2000,  "2026-03-22T10:19:00Z"),
    _rsc("synthesize", "SYNTHESIZE"),

    # ── synthesize → finalize (identical to greenfield) ───────────────────────
    _ev("SYNTHESIZER-1", "working",  "synthesize", "SYNTHESIZE", 2000),
    _ev("SYNTHESIZER-1", "thinking", "synthesize", "SYNTHESIZE", 3000),
    _ev("SYNTHESIZER-1", "complete", "synthesize", "SYNTHESIZE", 2000, "2026-03-22T10:24:00Z"),
    _ev("TRACKER-1",     "working",  "synthesize", "SYNTHESIZE", 2000),
    _ev("TRACKER-1",     "complete", "synthesize", "SYNTHESIZE", 2000, "2026-03-22T10:28:00Z"),
    _rsc("why1", "WHY1 — Assumption Challenge"),

    _ev("SAGE-1", "working",  "why1", "WHY1 — Assumption Challenge", 2000),
    _ev("SAGE-1", "thinking", "why1", "WHY1 — Assumption Challenge", 3000),
    _ev("SAGE-1", "complete", "why1", "WHY1 — Assumption Challenge", 2000, "2026-03-22T10:33:00Z"),
    _rsc("cartographer", "CARTOGRAPHER"),

    _ev("CARTOGRAPHER-1", "working",  "cartographer", "CARTOGRAPHER", 2000),
    _ev("CARTOGRAPHER-1", "thinking", "cartographer", "CARTOGRAPHER", 3000),
    _ev("CARTOGRAPHER-1", "complete", "cartographer", "CARTOGRAPHER", 2000, "2026-03-22T10:38:00Z"),
    _rsc("why2", "WHY2 — Spec Validation"),

    _ev("SAGE-2", "working",  "why2", "WHY2 — Spec Validation", 2000),
    _ev("SAGE-2", "thinking", "why2", "WHY2 — Spec Validation", 3000),
    _ev("SAGE-2", "complete", "why2", "WHY2 — Spec Validation", 2000, "2026-03-22T10:43:00Z"),
    _rsc("assess", "ASSESS — Kill Gate"),

    _ev("GATEKEEPER-1", "working",  "assess", "ASSESS — Kill Gate", 2000),
    _ev("GATEKEEPER-1", "thinking", "assess", "ASSESS — Kill Gate", 3000),
    _ev("GATEKEEPER-1", "complete", "assess", "ASSESS — Kill Gate", 2000, "2026-03-22T10:48:00Z"),
    _rsc("solution", "SOLUTION"),

    _ev("ARCHITECT-1", "working",  "solution", "SOLUTION", 2000),
    _ev("ARCHITECT-1", "thinking", "solution", "SOLUTION", 3000),
    _ev("ARCHITECT-1", "complete", "solution", "SOLUTION", 2000, "2026-03-22T10:53:00Z"),
    _ev("SENTINEL-1",  "working",  "solution", "SOLUTION", 2000),
    _ev("SENTINEL-1",  "complete", "solution", "SOLUTION", 2000, "2026-03-22T10:57:00Z"),
    _rsc("plan", "PLAN"),

    _ev("ORCHESTRATOR-1", "working",  "plan", "PLAN", 2000),
    _ev("ORCHESTRATOR-1", "thinking", "plan", "PLAN", 3000),
    _ev("ORCHESTRATOR-1", "complete", "plan", "PLAN", 2000, "2026-03-22T11:02:00Z"),
    _rsc("finalize", "FINALIZE"),

    _ev("REALIST-1", "working",  "finalize", "FINALIZE", 2000),
    _ev("REALIST-1", "complete", "finalize", "FINALIZE", 2000, "2026-03-22T11:06:00Z"),
    _ev("AUDITOR-1", "working",  "finalize", "FINALIZE", 2000),
    _ev("AUDITOR-1", "thinking", "finalize", "FINALIZE", 3000),
    _ev("AUDITOR-1", "complete", "finalize", "FINALIZE", 2000, "2026-03-22T11:11:00Z"),
    _rsc("finalize", "FINALIZE", status="done", completed_at="2026-03-22T11:11:30Z", delay_ms=1000),
]

_JOURNAL = {
    "GOLDDIGGER-1": [
        {"id": "j-GD-1-001", "dispatch_id": "GOLDDIGGER-1", "codename": "GOLDDIGGER",
         "run_id": _RUN_ID, "timestamp_ms": 1742637600000, "type": "finding",
         "content": "Mode 1 survey complete: 23 domain objects identified across 4 bounded contexts"},
        {"id": "j-GD-1-002", "dispatch_id": "GOLDDIGGER-1", "codename": "GOLDDIGGER",
         "run_id": _RUN_ID, "timestamp_ms": 1742637660000, "type": "decision",
         "content": "brownfield-index.md written — SCOUT-1 can proceed with pre-seeded domain vocabulary"},
    ],
    "SCOUT-1": [
        {"id": "j-SCOUT-1-001", "dispatch_id": "SCOUT-1", "codename": "SCOUT",
         "run_id": _RUN_ID, "timestamp_ms": 1742638200000, "type": "finding",
         "content": "Seeded from brownfield-index.md — 23 domain objects pre-mapped, validating against live code"},
        {"id": "j-SCOUT-1-002", "dispatch_id": "SCOUT-1", "codename": "SCOUT",
         "run_id": _RUN_ID, "timestamp_ms": 1742638260000, "type": "risk",
         "content": "3 hotspot files changed > 40x in past year — StripeWebhookHandler, PaymentService, RefundPolicy"},
    ],
    "GATEKEEPER-1": [
        {"id": "j-GATE-1-001", "dispatch_id": "GATEKEEPER-1", "codename": "GATEKEEPER",
         "run_id": _RUN_ID, "timestamp_ms": 1742641800000, "type": "assessment",
         "content": "PASS — spec coverage 91%, all critical requirements resolved"},
    ],
}

BROWNFIELD = Scenario(
    name="brownfield",
    description="Brownfield lifecycle with GOLDDIGGER-1 survey: 14 agents, 9 phases, ends status=done",
    initial_agents=_AGENTS,
    event_sequence=_EVENTS,
    initial_run=_INITIAL_RUN,
    journal_entries=_JOURNAL,
    loop=False,
)
register(BROWNFIELD)
