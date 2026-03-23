"""
radar/scenarios — mock scenario dataclasses and registry.

Provides MockAgent, ScenarioEvent, and Scenario dataclasses plus a simple
name-keyed registry (register / get_scenario / list_scenarios).

Zero side effects on import: no scenarios are registered here.
Scenario modules register themselves when imported (see bottom of file).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MockAgent:
    """A single simulated agent for use in mock scenarios."""

    dispatch_id: str       # e.g. "SCOUT-1"
    codename: str          # e.g. "SCOUT"
    display_name: str      # e.g. "Scout 1"  (title-case, space before number)
    state: str             # "working" | "thinking" | "blocked" | "complete" | "error" | "idle" | "unknown"
    phase: str             # e.g. "discover"
    dispatched_at: str     # ISO 8601 UTC with trailing Z

    completed_at: Optional[str] = None
    blocked_reason: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to the inner agent object schema defined in contracts/sse-api.md.

        NOTE: the outer key in the ``agents`` map is ``dispatch_id``; the inner
        object exposes it as ``"id"``.
        """
        d: dict = {
            "id": self.dispatch_id,
            "codename": self.codename,
            "display_name": self.display_name,
            "state": self.state,
            "phase": self.phase,
            "dispatched_at": self.dispatched_at,
        }
        if self.completed_at is not None:
            d["completed_at"] = self.completed_at
        if self.blocked_reason is not None:
            d["blocked_reason"] = self.blocked_reason
        return d


@dataclass
class ScenarioEvent:
    """A single event step inside a Scenario's event sequence."""

    event_type: str   # "agent_state_change" | "run_state_change" | "heartbeat"
    payload: dict
    delay_ms: int     # milliseconds to wait before emitting this event


@dataclass
class Scenario:
    """A complete mock scenario definition."""

    name: str
    description: str
    initial_agents: list            # list[MockAgent]
    event_sequence: list            # list[ScenarioEvent]
    initial_run: dict               # SquadRun dict for snapshot + run state tracking
    journal_entries: dict = field(default_factory=dict)  # keyed by dispatch_id
    loop: bool = False              # default False — one-shot is the new norm


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict = {}


def register(scenario: Scenario) -> None:
    """Add *scenario* to the registry, keyed by its name."""
    _REGISTRY[scenario.name] = scenario


def get_scenario(name: str):
    """Return the Scenario registered under *name*, or None."""
    return _REGISTRY.get(name)


def list_scenarios() -> list:
    """Return a list of all registered Scenario instances."""
    return list(_REGISTRY.values())


# ---------------------------------------------------------------------------
# Scenario modules register themselves on import:
from radar.scenarios import default as _default          # noqa: F401
from radar.scenarios import all_blocked as _all_blocked  # noqa: F401
from radar.scenarios import greenfield as _greenfield  # noqa: F401
from radar.scenarios import brownfield as _brownfield  # noqa: F401
from radar.scenarios import blocked_escalation as _blocked_escalation  # noqa: F401
# ---------------------------------------------------------------------------
