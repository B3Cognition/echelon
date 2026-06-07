"""Tests for blocked squad next-step guidance."""

from __future__ import annotations

import json
from pathlib import Path

from echelon.cli import _print_next_steps


def test_blocked_squad_escalation_prioritizes_resume(
    tmp_path: Path,
    capsys,
) -> None:
    constitution = tmp_path / ".specify" / "memory" / "constitution.md"
    constitution.parent.mkdir(parents=True)
    constitution.write_text("# Constitution\n\nReady.\n", encoding="utf-8")

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text(
        "\n".join(
            [
                "# Quality Gates",
                "",
                "## Verdict: FAIL",
                "",
                "| Gate | Score | Threshold | Result | Note |",
                "| --- | --- | --- | --- | --- |",
                "| Overall | 0.68 | 0.75 | FAIL | hard fail |",
            ]
        ),
        encoding="utf-8",
    )

    run_dir = tmp_path / "runs" / "spec-20260607-215902-820491"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "phase1-why2",
                "staging_dir": str(run_dir / "staging"),
                "blocked_reason": "WHY2 user-gated issue",
                "escalation_question": "Q1: confirm widget team intent?",
            }
        ),
        encoding="utf-8",
    )

    _print_next_steps(tmp_path, "blocked")

    captured = capsys.readouterr()
    assert "RUN BLOCKED — answer required" in captured.out
    assert 'echelon resume "<your answer>"' in captured.out
    assert "Q1: confirm widget team intent?" in captured.out
    assert "echelon continue" not in captured.out
