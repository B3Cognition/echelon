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


def test_ready_next_step_has_clear_subtitle_and_next_command(
    tmp_path: Path,
    capsys,
) -> None:
    constitution = tmp_path / ".specify" / "memory" / "constitution.md"
    constitution.parent.mkdir(parents=True)
    constitution.write_text("# Constitution\n\nReady.\n", encoding="utf-8")

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n## Verdict: PASS\n",
        encoding="utf-8",
    )
    for name in ("plan.md", "research.md", "data-model.md", "tasks.md"):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "READY TO BUILD" in captured.out
    assert "ready" in captured.out
    assert "constitution.md" in captured.out
    assert "HOW artifacts" in captured.out
    assert "tasks.md" in captured.out
    assert "next" in captured.out
    assert "echelon harness run 001-demo" in captured.out
    assert "\n  build\n" not in captured.out


def test_partial_constitution_placeholders_are_reported_precisely(
    tmp_path: Path,
    capsys,
) -> None:
    constitution = tmp_path / ".specify" / "memory" / "constitution.md"
    constitution.parent.mkdir(parents=True)
    constitution.write_text(
        "# Constitution\n\n[PRINCIPLE_1_NAME] -> I. Real Principle\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "spec-20260609-152410-385227"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "terminal-blocked",
                "completed_phases": ["phase1-constitution"],
            }
        ),
        encoding="utf-8",
    )

    _print_next_steps(tmp_path, "blocked")

    captured = capsys.readouterr()
    assert "unresolved constitution template marker" in captured.out
    assert "[PRINCIPLE_1_NAME]" in captured.out
    assert "blank template" not in captured.out


def test_blocked_non_escalation_run_does_not_claim_ready_to_build(
    tmp_path: Path,
    capsys,
) -> None:
    constitution = tmp_path / ".specify" / "memory" / "constitution.md"
    constitution.parent.mkdir(parents=True)
    constitution.write_text("# Constitution\n\nReady.\n", encoding="utf-8")

    spec_dir = tmp_path / "specs" / "006-element-creator"
    spec_dir.mkdir(parents=True)
    for name in ("plan.md", "research.md", "data-model.md", "tasks.md"):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n## Verdict: FAIL\n",
        encoding="utf-8",
    )

    run_dir = tmp_path / "runs" / "spec-20260618-073106-635192"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "terminal-blocked",
                "blocked_reason": "missing_echelon_result",
                "last_dispatch": {"phase_id": "phase3-sentinel"},
                "completed_phases": ["phase1-constitution", "phase3-how"],
            }
        ),
        encoding="utf-8",
    )

    _print_next_steps(tmp_path, "blocked")

    captured = capsys.readouterr()
    assert "READY TO BUILD" not in captured.out
    assert "RUN BLOCKED" in captured.out
    assert "missing_echelon_result" in captured.out
    assert "echelon rewind phase3-sentinel" in captured.out
