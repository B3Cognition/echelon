"""Unit tests for wing threading in PipelineEngine."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from codegen.memory.context import MemPalaceContext
from codegen.pipeline.pipeline_engine import PipelineEngine


def _make_ctx(wing="test-wing", run_id="r1"):
    return MemPalaceContext(wing=wing, run_id=run_id, palace_path="/fake/palace")


def test_set_context_stores_ctx(tmp_path):
    engine = PipelineEngine(state_file=tmp_path / "codegen-state.json")
    ctx = _make_ctx()
    engine.set_context(ctx)
    assert engine._ctx is ctx


def test_get_mempalace_writer_uses_ctx_wing(tmp_path):
    engine = PipelineEngine(state_file=tmp_path / "codegen-state.json")
    ctx = _make_ctx(wing="correct-wing", run_id="pipeline-abc")
    engine.set_context(ctx)

    from codegen.memory.mempalace_writer import MemPalaceWriter
    writer = engine._get_mempalace_writer(pipeline_id="pipeline-abc")

    assert isinstance(writer, MemPalaceWriter)
    assert writer.ctx.wing == "correct-wing"
    assert writer.ctx.run_id == "pipeline-abc"


def test_get_mempalace_writer_raises_without_ctx(tmp_path):
    engine = PipelineEngine(state_file=tmp_path / "codegen-state.json")
    with pytest.raises(RuntimeError, match="set_context"):
        engine._get_mempalace_writer(pipeline_id="x")


def test_initialize_writes_wing_to_state_file(tmp_path):
    state_file = tmp_path / "codegen-state.json"
    engine = PipelineEngine(state_file=state_file)
    ctx = _make_ctx(wing="stored-wing")
    engine.set_context(ctx)

    with patch.object(engine.gate_runner, "_get_bridge") as mock_bridge:
        mock_bridge.return_value.model.value = "B"
        mock_bridge.return_value._pid = 0
        engine.initialize(intent="test", mode="greenfield")

    state = json.loads(state_file.read_text())
    assert state["wing"] == "stored-wing"


def test_initialize_without_ctx_sets_empty_wing(tmp_path):
    state_file = tmp_path / "codegen-state.json"
    engine = PipelineEngine(state_file=state_file)

    with patch.object(engine.gate_runner, "_get_bridge") as mock_bridge:
        mock_bridge.return_value.model.value = "B"
        mock_bridge.return_value._pid = 0
        engine.initialize(intent="test", mode="greenfield")

    state = json.loads(state_file.read_text())
    assert state.get("wing", "") == ""
