from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

from harness.phase_graph import PhaseNode
from harness.squad import _format_phase_dispatch_line


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
        agent="speckit-echelon-chief",
    )

    line = _format_phase_dispatch_line(node, graph, ext_dir, file=_TTYBuffer())

    assert line == "\n[squad] ▶ \033[34mphase1-constitution\033[0m  Constitution"


def test_phase_dispatch_line_is_plain_without_agent_color(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    graph = MagicMock()
    graph.agent_file.return_value = None
    node = PhaseNode(id="phase1-what", type="agent", label="What", agent="speckit-echelon-scout")

    line = _format_phase_dispatch_line(node, graph, tmp_path / "ext", file=_TTYBuffer())

    assert line == "\n[squad] ▶ phase1-what  What"
