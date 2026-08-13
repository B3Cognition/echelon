from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from echelon.cli import _print_squad_summary


def test_squad_summary_includes_one_human_readable_worked_on_section(
    tmp_path: Path,
    capsys,
) -> None:
    squad_dir = tmp_path / "runs" / "spec-123"
    squad_dir.mkdir(parents=True)
    (squad_dir / "state.json").write_text(
        json.dumps(
            {
                "spec_id": "123-run-handoff",
                "status": "done",
                "phase": "terminal-done",
                "completed_phases": ["phase1", "phase2"],
            }
        ),
        encoding="utf-8",
    )

    with patch(
        "harness.run_summary.summarize_run_for_cli",
        return_value=(
            "Published the proportional specification.\n"
            "Verified the result with 42 passing tests.\n"
            "The specification is ready for delivery."
        ),
    ):
        _print_squad_summary(
            tmp_path,
            squad_dir,
            SimpleNamespace(status="done", phase="terminal-done"),
            mode="semi",
            message="Add a run handoff.",
        )

    output = capsys.readouterr().out
    assert output.count("SQUAD SUMMARY") == 1
    assert "worked on" in output
    assert "Published the proportional specification." in output
    assert "Verified the result with 42 passing tests." in output
    assert "next" in output
    assert "echelon delivery run 123-run-handoff" in output


def test_squad_summary_keeps_invoked_command_distinct_from_recovery_command(
    tmp_path: Path,
) -> None:
    squad_dir = tmp_path / "runs" / "spec-123"
    squad_dir.mkdir(parents=True)
    (squad_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "interrupted",
                "phase": "phase2-decide",
                "user_message": "Add a run handoff.",
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def summarize(context):
        captured["context"] = context
        return "The resumed run was interrupted and can be continued."

    with patch(
        "harness.run_summary.summarize_run_for_cli",
        side_effect=summarize,
    ):
        _print_squad_summary(
            tmp_path,
            squad_dir,
            SimpleNamespace(status="interrupted", phase="phase2-decide"),
            mode="semi",
            message="Add a run handoff.",
            command="echelon spec resume",
        )

    context = captured["context"]
    assert context.command == "echelon spec resume"
    assert context.next_step == "echelon spec continue"
