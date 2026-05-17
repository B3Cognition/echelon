"""Trigger types + serialization for the bash hook to consume.

Each Trigger represents one mutation the calculator wants to apply.
serialize() renders a list of Triggers as one-per-line text the hook
parses via simple field splitting.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Union


@dataclass(frozen=True)
class HandlerCall:
    """Invokes an existing endocrine.sh subcommand by name with positional args.

    Used for: on_gate_pass, on_gate_fail, on_rework, on_low_confidence,
    on_quality_improvement, on_quality_regression, on_innovate_summon,
    on_peer_accept, on_peer_reject, propagate_downstream,
    propagate_cortisol_contagion, decay_hormones.
    """
    name: str
    args: tuple[str, ...]


@dataclass(frozen=True)
class HormoneUpdate:
    """Direct hormone update — used by F1/F2/F3 dynamics where there's no
    matching on_* handler. The hook maps `hormone` name to its index and
    invokes `endocrine.sh update_hormone <agent> <idx> <delta>`.
    """
    agent: str
    hormone: str   # "adrenaline" | "dopamine" | "cortisol" | "serotonin" | "oxytocin" | "norepinephrine"
    delta: float


@dataclass(frozen=True)
class BroadcastAdrenaline:
    """Broadcast adrenaline to all agents — used by F1 critical band."""
    delta: float


Trigger = Union[HandlerCall, HormoneUpdate, BroadcastAdrenaline]


def _fmt_signed(value: float) -> str:
    """Format a delta with explicit sign (+0.05 / -0.10)."""
    if value >= 0:
        return f"+{value:.2f}"
    return f"{value:.2f}"


def serialize(triggers: Sequence[Trigger]) -> str:
    """Render a list of Triggers as newline-joined trigger lines.

    Each line: "<verb> <args...>" — parsed by the bash hook with simple word
    splitting. Empty list returns empty string (no trailing newline).
    """
    lines = []
    for t in triggers:
        if isinstance(t, HandlerCall):
            line = t.name
            if t.args:
                line += " " + " ".join(t.args)
            lines.append(line)
        elif isinstance(t, HormoneUpdate):
            lines.append(f"hormone_update {t.agent} {t.hormone} {_fmt_signed(t.delta)}")
        elif isinstance(t, BroadcastAdrenaline):
            lines.append(f"broadcast_adrenaline {_fmt_signed(t.delta)}")
        else:
            raise TypeError(f"unknown Trigger type: {type(t).__name__}")
    return "\n".join(lines)
