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


def test_run_re_phase_constructs_reader_with_ctx(tmp_path):
    """run_re_phase passes MemPalaceContext to MemPalaceReader, not bare wing string."""
    state_file = tmp_path / "codegen-state.json"
    engine = PipelineEngine(state_file=state_file)
    ctx = _make_ctx(wing="re-wing")
    engine.set_context(ctx)

    # Bootstrap a minimal state file so _write_re_context can write
    state_file.write_text(json.dumps({"pipeline_id": "p1", "wing": "re-wing",
                                       "current_phase": "RE", "phases_completed": [],
                                       "mode": "greenfield", "intent": "test",
                                       "target_path": None, "retry_count": 0,
                                       "max_retries": 3, "psi_score": 0.0,
                                       "tier1_gate": "pending", "soar_model": "B",
                                       "soar_pid": None, "violations_blocked": 0,
                                       "impasse_count": 0, "created_at": "", "updated_at": ""}))

    with patch("codegen.memory.mempalace_reader.MemPalaceReader") as mock_reader_cls:
        mock_reader = MagicMock()
        mock_reader.search_requirements.return_value = []
        mock_reader_cls.return_value = mock_reader

        with patch.object(engine.gate_runner, "_get_bridge") as mock_bridge:
            mock_bridge.return_value.inject_wme = MagicMock()
            mock_bridge.return_value.record_phase_transition = MagicMock()
            engine.run_re_phase(intent="build REST API", ctx=ctx)

    # MemPalaceReader must be constructed with ctx, not wing= kwarg
    mock_reader_cls.assert_called_once_with(ctx)


def test_resume_preserves_wing_from_state_file(tmp_path):
    """resume() must return PipelineState with wing read from codegen-state.json."""
    state_file = tmp_path / "codegen-state.json"
    state_file.write_text(json.dumps({
        "pipeline_id": "p-abc", "wing": "saved-wing",
        "current_phase": "IMPLEMENT", "phases_completed": ["RE"],
        "mode": "greenfield", "intent": "test", "target_path": None,
        "retry_count": 0, "max_retries": 3, "psi_score": 0.0,
        "tier1_gate": "pending", "soar_model": "B", "soar_pid": None,
        "violations_blocked": 0, "impasse_count": 0,
        "created_at": "", "updated_at": "",
    }))
    engine = PipelineEngine(state_file=state_file)
    state = engine.resume()
    assert state.wing == "saved-wing"
