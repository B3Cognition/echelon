"""Tests for src/hormone_calc/output.py — Trigger types + serialization."""
from hormone_calc.output import (
    Trigger,
    HandlerCall,
    HormoneUpdate,
    BroadcastAdrenaline,
    serialize,
)


def test_handler_call_serializes_with_args():
    t = HandlerCall(name="on_gate_pass", args=("SAGE",))
    assert serialize([t]) == "on_gate_pass SAGE"


def test_handler_call_no_args():
    t = HandlerCall(name="on_quality_improvement", args=())
    assert serialize([t]) == "on_quality_improvement"


def test_handler_call_two_args():
    t = HandlerCall(name="propagate_downstream", args=("CARTOGRAPHER", "SAGE"))
    assert serialize([t]) == "propagate_downstream CARTOGRAPHER SAGE"


def test_hormone_update_positive_delta():
    t = HormoneUpdate(agent="IMPLEMENTER", hormone="adrenaline", delta=0.05)
    assert serialize([t]) == "hormone_update IMPLEMENTER adrenaline +0.05"


def test_hormone_update_negative_delta():
    t = HormoneUpdate(agent="MAVERICK", hormone="cortisol", delta=-0.10)
    assert serialize([t]) == "hormone_update MAVERICK cortisol -0.10"


def test_broadcast_adrenaline():
    t = BroadcastAdrenaline(delta=0.05)
    assert serialize([t]) == "broadcast_adrenaline +0.05"


def test_serialize_multiple_triggers_one_per_line():
    triggers = [
        HandlerCall(name="decay_hormones", args=("SAGE",)),
        HormoneUpdate(agent="SAGE", hormone="adrenaline", delta=0.03),
        HandlerCall(name="on_gate_pass", args=("SAGE",)),
    ]
    out = serialize(triggers)
    lines = out.split("\n")
    assert len(lines) == 3
    assert lines[0] == "decay_hormones SAGE"
    assert lines[1] == "hormone_update SAGE adrenaline +0.03"
    assert lines[2] == "on_gate_pass SAGE"


def test_serialize_empty_list_returns_empty_string():
    assert serialize([]) == ""
