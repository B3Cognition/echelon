"""derive_upstream() — finds the upstream agent for the current dispatch.

Heuristic: walk the journal's recent_dispatches backwards (most-recent-first),
find the most recent routing_decision entry whose agent != current. That's
the upstream. Falls back to None if no such entry exists.

This is intentionally a "most recent other agent" heuristic rather than a
context_pack file-overlap analysis — the latter would require reading
workflow/definition.yaml at runtime and is fragile. The simpler heuristic
correctly identifies upstream in the linear-phase common case (which is
what the existing on_peer_accept / propagate_* handlers are designed for).

Subagent-fork phases (staged_parallel like phase3-consensus) may give
arbitrary "upstream" results. That's acceptable — the spec's "skip if None"
fallback in dispatch_chain triggers means false-positive upstreams just
emit one extra propagate event with small magnitude.
"""
from __future__ import annotations

from typing import Optional

from hormone_calc.observable import ObservableState


def derive_upstream(obs: ObservableState) -> Optional[str]:
    """Return the most recent dispatched agent that isn't the current agent.

    Considers only entries of type "routing_decision". Returns None if no
    such prior dispatch is found in the last 50 journal entries.
    """
    for entry in reversed(obs.recent_dispatches):
        if entry.get("type") != "routing_decision":
            continue
        prior_agent = entry.get("agent")
        if prior_agent and prior_agent != obs.agent:
            return prior_agent
    return None
