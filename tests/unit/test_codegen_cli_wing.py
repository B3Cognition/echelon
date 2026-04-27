"""Unit tests for wing threading in codegen CLI."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


def test_run_pipeline_constructs_ctx_from_project(tmp_path):
    """_run_pipeline builds MemPalaceContext from echelon.yml and calls engine.set_context."""
    from codegen.cli.codegen_cli import _run_pipeline
    import argparse

    echelon_yml = tmp_path / "echelon.yml"
    echelon_yml.write_text("mempalace:\n  wing: my-app\n")
    state_file = tmp_path / "codegen-state.json"

    args = argparse.Namespace(
        state_file=str(state_file),
        verbose=False,
        resume=False,
        intent="build REST API",
        target=None,
        wing=None,
    )

    mock_state = MagicMock()
    mock_state.pipeline_id = "p-123"
    mock_state.current_phase = "RE"
    mock_state.phases_completed = []
    mock_state.psi_score = 0.0
    mock_state.tier1_gate = "pending"

    mock_engine = MagicMock()
    mock_engine.initialize.return_value = mock_state
    mock_engine.run_re_phase.return_value = ""

    with patch("codegen.cli.codegen_cli.PipelineEngine", return_value=mock_engine):
        with patch("codegen.cli.codegen_cli.Path.cwd", return_value=tmp_path):
            _run_pipeline(args)

    mock_engine.set_context.assert_called_once()
    ctx = mock_engine.set_context.call_args[0][0]
    assert ctx.wing == "my-app"
    assert ctx.run_id == "p-123"


def test_run_pipeline_wing_override_from_args(tmp_path):
    """--wing arg overrides echelon.yml wing."""
    from codegen.cli.codegen_cli import _run_pipeline
    import argparse

    echelon_yml = tmp_path / "echelon.yml"
    echelon_yml.write_text("mempalace:\n  wing: yaml-wing\n")
    state_file = tmp_path / "codegen-state.json"

    args = argparse.Namespace(
        state_file=str(state_file),
        verbose=False,
        resume=False,
        intent="test",
        target=None,
        wing="cli-override",
    )

    mock_state = MagicMock()
    mock_state.pipeline_id = "p-456"
    mock_state.current_phase = "RE"
    mock_state.phases_completed = []
    mock_state.psi_score = 0.0
    mock_state.tier1_gate = "pending"

    mock_engine = MagicMock()
    mock_engine.initialize.return_value = mock_state
    mock_engine.run_re_phase.return_value = ""

    with patch("codegen.cli.codegen_cli.PipelineEngine", return_value=mock_engine):
        with patch("codegen.cli.codegen_cli.Path.cwd", return_value=tmp_path):
            _run_pipeline(args)

    ctx = mock_engine.set_context.call_args[0][0]
    assert ctx.wing == "cli-override"
