"""Consistent colored rendering for phase-scoped squad output."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from harness.prompt_markdown import read_prompt_markdown
from harness.terminal import color_text

if TYPE_CHECKING:
    from harness.phase_graph import PhaseGraph, PhaseNode


def agent_frontmatter_color(node: "PhaseNode", graph: "PhaseGraph", ext_dir: Path) -> str:
    """Return an agent's declared Prosaic color, or an empty color for non-agents."""
    if not node.agent:
        return ""
    rel = graph.agent_file(node.agent)
    if not rel:
        return ""
    path = ext_dir / rel
    if not path.exists():
        return ""
    color = read_prompt_markdown(path).metadata.get("color")
    return color if isinstance(color, str) else ""


def color_phase_id(
    node: "PhaseNode", graph: "PhaseGraph", ext_dir: Path, *, file: object = None
) -> str:
    """Render one phase ID with its agent's declared terminal color."""
    target = file if file is not None else sys.stdout
    return color_text(node.id, agent_frontmatter_color(node, graph, ext_dir), file=target)


def format_phase_dispatch_line(
    node: "PhaseNode",
    graph: "PhaseGraph",
    ext_dir: Path,
    *,
    file: object = None,
    suffix: str = "",
) -> str:
    """Render a squad phase dispatch line using the agent's Prosaic color."""
    label = node.label or node.id
    return f"\n[squad] ▶ {color_phase_id(node, graph, ext_dir, file=file)}  {label}{suffix}"


def format_phase_transition_line(
    phase_id: str,
    next_phase: str,
    graph: "PhaseGraph",
    ext_dir: Path,
    *,
    file: object = None,
    suffix: str = "",
) -> str:
    """Render a transition, coloring each endpoint by its own declared agent."""
    phase = _color_phase_reference(phase_id, graph, ext_dir, file=file)
    target = _color_phase_reference(next_phase, graph, ext_dir, file=file)
    return f"[squad] ✓ {phase}  → {target}{suffix}"


def _color_phase_reference(
    phase_id: str, graph: "PhaseGraph", ext_dir: Path, *, file: object = None
) -> str:
    """Color a declared graph phase, retaining terminal pseudo-phases verbatim."""
    try:
        node = graph.get(phase_id)
    except KeyError:
        return phase_id
    return color_phase_id(node, graph, ext_dir, file=file)
