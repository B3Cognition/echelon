from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.phase_graph import PhaseGraph, PhaseNode
from harness.phase_display import format_phase_dispatch_line, format_phase_transition_line


class _TTYBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_phase_dispatch_line_uses_agent_frontmatter_color(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents" / "control"
    agent_dir.mkdir(parents=True)
    (agent_dir / "chief.md").write_text(
        "---\n"
        "color: blue\n"
        "---\n"
        "# Chief\n",
        encoding="utf-8",
    )
    graph = MagicMock()
    graph.agent_file.return_value = "agents/control/chief.md"
    node = PhaseNode(
        id="phase1-constitution",
        type="agent",
        label="Constitution",
        agent="echelon-chief",
    )

    line = format_phase_dispatch_line(node, graph, ext_dir, file=_TTYBuffer())

    assert line == "\n[squad] ▶ \033[34mphase1-constitution\033[0m  Constitution"


def test_phase_dispatch_line_is_plain_without_agent_color(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    graph = MagicMock()
    graph.agent_file.return_value = None
    node = PhaseNode(id="phase1-what", type="agent", label="What", agent="echelon-scout")

    line = format_phase_dispatch_line(node, graph, tmp_path / "ext", file=_TTYBuffer())

    assert line == "\n[squad] ▶ phase1-what  What"


def test_phase_transition_colors_each_agent_phase_on_tty(
    tmp_path: Path, monkeypatch
) -> None:
    """Catches progress output bypassing the Prosaic agent-color resolver."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "source.md").write_text("---\ncolor: blue\n---\n", encoding="utf-8")
    (agent_dir / "target.md").write_text("---\ncolor: green\n---\n", encoding="utf-8")
    graph = MagicMock()
    graph.get.side_effect = [
        PhaseNode(id="phase-source", type="agent", agent="echelon-source"),
        PhaseNode(id="phase-target", type="agent", agent="echelon-target"),
    ]
    graph.agent_file.side_effect = ["agents/source.md", "agents/target.md"]

    line = format_phase_transition_line(
        "phase-source", "phase-target", graph, ext_dir, file=_TTYBuffer()
    )

    assert line == "[squad] ✓ \033[34mphase-source\033[0m  → \033[32mphase-target\033[0m"


def test_phase_transition_leaves_terminal_target_plain(tmp_path: Path, monkeypatch) -> None:
    """Catches coloring a terminal pseudo-phase by looking it up as an agent node."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "source.md").write_text("---\ncolor: blue\n---\n", encoding="utf-8")
    graph = MagicMock()
    graph.get.side_effect = [
        PhaseNode(id="phase-source", type="agent", agent="echelon-source"),
        KeyError("DONE"),
    ]
    graph.agent_file.return_value = "agents/source.md"

    line = format_phase_transition_line(
        "phase-source", "DONE", graph, ext_dir, file=_TTYBuffer()
    )

    assert line == "[squad] ✓ \033[34mphase-source\033[0m  → DONE"


@pytest.fixture
def workflow():
    root = Path(__file__).resolve().parents[2]
    graph = PhaseGraph(
        root / "runtime/workflow/definition.yaml",
        prosaic_subagents_dir=root / "prosaic/subagents",
    )
    return graph, root / "runtime"


@pytest.mark.parametrize("phase,code", [
    ("phase3-specialists", "36"),
    ("phase3-consensus", "36"),
    ("checkpoint-assess", "90"),
    ("phase2-feasibility-structural", "90"),
    ("phase2-intent-alignment-structural", "90"),
    ("phase3-tasks-lexicon", "90"),
    ("phase3-understanding", "90"),
])
def test_real_group_and_controller_dispatches_are_colored(workflow, monkeypatch, phase, code):
    """Non-agent workflow nodes must not fall through the single-agent lookup."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    graph, ext_dir = workflow
    node = graph.get(phase)
    line = format_phase_dispatch_line(node, graph, ext_dir, file=_TTYBuffer())
    assert line == f"\n[squad] ▶ \033[{code}m{phase}\033[0m  {node.label}"


def test_transition_uses_group_and_controller_colors_consistently(workflow, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    graph, ext_dir = workflow
    line = format_phase_transition_line(
        "phase3-consensus", "phase3-consensus-tasks-lexicon", graph, ext_dir, file=_TTYBuffer()
    )
    assert line == (
        "[squad] ✓ \033[36mphase3-consensus\033[0m  → "
        "\033[90mphase3-consensus-tasks-lexicon\033[0m"
    )


@pytest.mark.parametrize("disabled_by", ["pipe", "NO_COLOR"])
def test_group_and_controller_colors_respect_plain_output(workflow, monkeypatch, disabled_by):
    monkeypatch.delenv("NO_COLOR", raising=False)
    output = io.StringIO() if disabled_by == "pipe" else _TTYBuffer()
    if disabled_by == "NO_COLOR":
        monkeypatch.setenv("NO_COLOR", "")
    graph, ext_dir = workflow
    line = format_phase_transition_line(
        "phase3-consensus", "phase3-consensus-tasks-lexicon", graph, ext_dir, file=output
    )
    assert line == "[squad] ✓ phase3-consensus  → phase3-consensus-tasks-lexicon"
