"""
radar/scenarios/all_blocked.py — All-blocked scenario.

Eight agents, all in blocked state waiting for human escalation.
No events; loop=False (static snapshot).
"""

from radar.scenarios import MockAgent, Scenario, register

# ---------------------------------------------------------------------------
# Run metadata
# ---------------------------------------------------------------------------

_INITIAL_RUN = {
    "run_id": "mock-run-blocked",
    "status": "blocked",
    "phase": "operations",
    "phase_display": "OPERATIONS",
    "iteration": 1,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
    "completed_at": None,
}

# ---------------------------------------------------------------------------
# Agents — same roster as default scenario, all blocked
# display_name uses space convention: "Agent N" not "Agent-N"
# ---------------------------------------------------------------------------

_DISPATCHED_AT = "2026-01-01T00:00:00Z"
_BLOCKED_REASON = "Waiting for human escalation"

_agents = [
    MockAgent(
        dispatch_id="MOCK-SCOUT-1",
        codename="SCOUT",
        display_name="Scout 1",
        state="blocked",
        phase="OPERATIONS",
        dispatched_at=_DISPATCHED_AT,
        blocked_reason=_BLOCKED_REASON,
    ),
    MockAgent(
        dispatch_id="MOCK-SAGE-1",
        codename="SAGE",
        display_name="Sage 1",
        state="blocked",
        phase="OPERATIONS",
        dispatched_at=_DISPATCHED_AT,
        blocked_reason=_BLOCKED_REASON,
    ),
    MockAgent(
        dispatch_id="MOCK-CARTOGRAPHER-1",
        codename="CARTOGRAPHER",
        display_name="Cartographer 1",
        state="blocked",
        phase="OPERATIONS",
        dispatched_at=_DISPATCHED_AT,
        blocked_reason=_BLOCKED_REASON,
    ),
    MockAgent(
        dispatch_id="MOCK-STRATEGIST-1",
        codename="STRATEGIST",
        display_name="Strategist 1",
        state="blocked",
        phase="OPERATIONS",
        dispatched_at=_DISPATCHED_AT,
        blocked_reason=_BLOCKED_REASON,
    ),
    MockAgent(
        dispatch_id="MOCK-ARCHITECT-1",
        codename="ARCHITECT",
        display_name="Architect 1",
        state="blocked",
        phase="OPERATIONS",
        dispatched_at=_DISPATCHED_AT,
        blocked_reason=_BLOCKED_REASON,
    ),
    MockAgent(
        dispatch_id="MOCK-SENTINEL-1",
        codename="SENTINEL",
        display_name="Sentinel 1",
        state="blocked",
        phase="OPERATIONS",
        dispatched_at=_DISPATCHED_AT,
        blocked_reason=_BLOCKED_REASON,
    ),
    MockAgent(
        dispatch_id="MOCK-BUILDER-1",
        codename="BUILDER",
        display_name="Builder 1",
        state="blocked",
        phase="OPERATIONS",
        dispatched_at=_DISPATCHED_AT,
        blocked_reason=_BLOCKED_REASON,
    ),
    MockAgent(
        dispatch_id="MOCK-MANAGER-1",
        codename="MANAGER",
        display_name="Manager 1",
        state="blocked",
        phase="OPERATIONS",
        dispatched_at=_DISPATCHED_AT,
        blocked_reason=_BLOCKED_REASON,
    ),
]

# ---------------------------------------------------------------------------
# Event sequence — none; this is a static snapshot
# ---------------------------------------------------------------------------

event_sequence = []

# ---------------------------------------------------------------------------
# Scenario definition and registration
# ---------------------------------------------------------------------------

ALL_BLOCKED = Scenario(
    name="all-blocked",
    description="All agents in blocked state waiting for human escalation",
    initial_agents=_agents,
    event_sequence=event_sequence,
    initial_run=_INITIAL_RUN,
    journal_entries={},
    loop=False,
)

register(ALL_BLOCKED)
