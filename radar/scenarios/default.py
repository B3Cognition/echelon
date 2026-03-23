"""
radar/scenarios/default.py — Default scenario.

Cycles all 8 mock agents through all 7 state values indefinitely.
Registers itself as "default" on import.
"""

from __future__ import annotations

from radar.mock_server import _now
from radar.scenarios import MockAgent, Scenario, ScenarioEvent, register

# ---------------------------------------------------------------------------
# Run metadata
# ---------------------------------------------------------------------------

_INITIAL_RUN = {
    "run_id": "mock-run-default",
    "status": "running",
    "phase": "operations",
    "phase_display": "OPERATIONS",
    "iteration": 1,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
    "completed_at": None,
}

# ---------------------------------------------------------------------------
# Initial agents (8 total — display_name uses "Agent N" space convention)
# ---------------------------------------------------------------------------

_AGENTS = [
    MockAgent(dispatch_id="MOCK-SCOUT-1", codename="SCOUT", display_name="Scout 1",
              state="working", phase="OPERATIONS", dispatched_at=_now()),
    MockAgent(dispatch_id="MOCK-SAGE-1", codename="SAGE", display_name="Sage 1",
              state="thinking", phase="OPERATIONS", dispatched_at=_now()),
    MockAgent(dispatch_id="MOCK-CARTOGRAPHER-1", codename="CARTOGRAPHER", display_name="Cartographer 1",
              state="idle", phase="OPERATIONS", dispatched_at=_now()),
    MockAgent(dispatch_id="MOCK-STRATEGIST-1", codename="STRATEGIST", display_name="Strategist 1",
              state="blocked", phase="OPERATIONS", dispatched_at=_now(),
              blocked_reason="Waiting for human decision"),
    MockAgent(dispatch_id="MOCK-ARCHITECT-1", codename="ARCHITECT", display_name="Architect 1",
              state="complete", phase="OPERATIONS", dispatched_at=_now(), completed_at=_now()),
    MockAgent(dispatch_id="MOCK-SENTINEL-1", codename="SENTINEL", display_name="Sentinel 1",
              state="error", phase="OPERATIONS", dispatched_at=_now()),
    MockAgent(dispatch_id="MOCK-BUILDER-1", codename="BUILDER", display_name="Builder 1",
              state="unknown", phase="OPERATIONS", dispatched_at=_now()),
    MockAgent(dispatch_id="MOCK-MANAGER-1", codename="MANAGER", display_name="Manager 1",
              state="working", phase="OPERATIONS", dispatched_at=_now()),
]

# ---------------------------------------------------------------------------
# Event sequence (14 events, ~28s per loop — all 7 states appear in payload)
# ---------------------------------------------------------------------------
#
# Strategy: rotate agents through states so every state appears at least once
# in the sequence, and the animation stays visually interesting.

_EVENTS = [
    # 1 — Scout: working -> thinking
    ScenarioEvent(
        event_type="agent_state_change",
        payload={
            "dispatch_id": "MOCK-SCOUT-1",
            "state": "thinking",
            "phase": "OPERATIONS",
            "updated_at": _now(),
        },
        delay_ms=2500,
    ),
    # 2 — Sage: thinking -> working
    ScenarioEvent(
        event_type="agent_state_change",
        payload={
            "dispatch_id": "MOCK-SAGE-1",
            "state": "working",
            "phase": "OPERATIONS",
            "updated_at": _now(),
        },
        delay_ms=2500,
    ),
    # 3 — Cartographer: idle -> working
    ScenarioEvent(
        event_type="agent_state_change",
        payload={
            "dispatch_id": "MOCK-CARTOGRAPHER-1",
            "state": "working",
            "phase": "OPERATIONS",
            "updated_at": _now(),
        },
        delay_ms=2000,
    ),
    # 4 — Strategist: blocked -> thinking
    ScenarioEvent(
        event_type="agent_state_change",
        payload={
            "dispatch_id": "MOCK-STRATEGIST-1",
            "state": "thinking",
            "phase": "OPERATIONS",
            "updated_at": _now(),
        },
        delay_ms=2500,
    ),
    # 5 — Sentinel: error -> idle
    ScenarioEvent(
        event_type="agent_state_change",
        payload={
            "dispatch_id": "MOCK-SENTINEL-1",
            "state": "idle",
            "phase": "OPERATIONS",
            "updated_at": _now(),
        },
        delay_ms=2000,
    ),
    # 6 — Builder: unknown -> working
    ScenarioEvent(
        event_type="agent_state_change",
        payload={
            "dispatch_id": "MOCK-BUILDER-1",
            "state": "working",
            "phase": "OPERATIONS",
            "updated_at": _now(),
        },
        delay_ms=2500,
    ),
    # 7 — Manager: working -> blocked
    ScenarioEvent(
        event_type="agent_state_change",
        payload={
            "dispatch_id": "MOCK-MANAGER-1",
            "state": "blocked",
            "phase": "OPERATIONS",
            "updated_at": _now(),
        },
        delay_ms=2000,
    ),
    # 8 — Scout: thinking -> complete
    ScenarioEvent(
        event_type="agent_state_change",
        payload={
            "dispatch_id": "MOCK-SCOUT-1",
            "state": "complete",
            "phase": "OPERATIONS",
            "updated_at": _now(),
        },
        delay_ms=2500,
    ),
    # 9 — Sage: working -> error
    ScenarioEvent(
        event_type="agent_state_change",
        payload={
            "dispatch_id": "MOCK-SAGE-1",
            "state": "error",
            "phase": "OPERATIONS",
            "updated_at": _now(),
        },
        delay_ms=2000,
    ),
    # 10 — Architect: complete -> unknown
    ScenarioEvent(
        event_type="agent_state_change",
        payload={
            "dispatch_id": "MOCK-ARCHITECT-1",
            "state": "unknown",
            "phase": "OPERATIONS",
            "updated_at": _now(),
        },
        delay_ms=2500,
    ),
    # 11 — Cartographer: working -> blocked
    ScenarioEvent(
        event_type="agent_state_change",
        payload={
            "dispatch_id": "MOCK-CARTOGRAPHER-1",
            "state": "blocked",
            "phase": "OPERATIONS",
            "updated_at": _now(),
        },
        delay_ms=2000,
    ),
    # 12 — Sentinel: idle -> thinking
    ScenarioEvent(
        event_type="agent_state_change",
        payload={
            "dispatch_id": "MOCK-SENTINEL-1",
            "state": "thinking",
            "phase": "OPERATIONS",
            "updated_at": _now(),
        },
        delay_ms=2500,
    ),
    # 13 — Manager: blocked -> working
    ScenarioEvent(
        event_type="agent_state_change",
        payload={
            "dispatch_id": "MOCK-MANAGER-1",
            "state": "working",
            "phase": "OPERATIONS",
            "updated_at": _now(),
        },
        delay_ms=2000,
    ),
    # 14 — Builder: working -> idle  (all 7 states now covered)
    ScenarioEvent(
        event_type="agent_state_change",
        payload={
            "dispatch_id": "MOCK-BUILDER-1",
            "state": "idle",
            "phase": "OPERATIONS",
            "updated_at": _now(),
        },
        delay_ms=2500,
    ),
]

# ---------------------------------------------------------------------------
# Scenario registration
# ---------------------------------------------------------------------------

DEFAULT = Scenario(
    name="default",
    description="Cycles through all 7 agent states indefinitely (8 mock agents, ~35s per loop)",
    initial_agents=_AGENTS,
    event_sequence=_EVENTS,
    initial_run=_INITIAL_RUN,
    journal_entries={},
    loop=True,
)
register(DEFAULT)
