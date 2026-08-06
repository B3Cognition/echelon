"""Tests for the low-level resume skill entry point."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
def test_resume_skill_delegates_to_run_skill_with_existing_build_id(tmp_path: Path) -> None:
    """Low-level resume should re-enter the normal coordinator path for LLM/prompt setup."""
    from harness.paths import build_dir, current_build_marker
    from harness.skills.resume_skill import resume

    spec_id = "001"
    build_id = "build-existing"
    strategy_id = "default"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = current_build_marker(tmp_path, spec_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(build_id, encoding="utf-8")
    bdir = build_dir(tmp_path, build_id)
    escalation_file = bdir / "escalations" / "001-default.md"
    escalation_file.parent.mkdir(parents=True, exist_ok=True)
    escalation_file.write_text("# Escalation\n", encoding="utf-8")
    state_dir = bdir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / f"{strategy_id}.json").write_text(
        json.dumps(
            {
                "spec_id": spec_id,
                "strategy_id": strategy_id,
                "status": "blocked",
                "mode": "semi",
                "termination_reason": "blocker_escalation",
                "escalation_file": str(escalation_file),
            }
        ),
        encoding="utf-8",
    )

    with patch("harness.config.load_config", return_value=MagicMock()), \
         patch("harness.skills.run_skill.run") as mock_run:
        resume(
            "resume spec 001 strategy default answer: use option A",
            provider=MagicMock(),
            gitops=MagicMock(),
            base_dir=str(tmp_path),
            orchestration_root=workspace,
        )

    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["resume_build_id"] == build_id
    assert mock_run.call_args.kwargs["base_dir"] == str(tmp_path)
    assert mock_run.call_args.kwargs["orchestration_root"] == workspace
    assert "spec 001" in mock_run.call_args.args[0]
    assert "resume" in mock_run.call_args.args[0]
