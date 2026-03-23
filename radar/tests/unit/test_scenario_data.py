import pytest
from radar.scenarios import get_scenario

ALL_STATES = {"working", "thinking", "blocked", "complete", "error", "idle", "unknown"}

def test_default_has_8_agents():
    s = get_scenario("default")
    assert len(s.initial_agents) == 8

def test_default_initial_states_cover_all_7():
    s = get_scenario("default")
    states = set(a.state for a in s.initial_agents)
    assert states == ALL_STATES

def test_default_event_sequence_covers_all_7_states():
    s = get_scenario("default")
    states = set(e.payload["state"] for e in s.event_sequence if "state" in e.payload)
    assert states == ALL_STATES

def test_default_delays_in_range():
    s = get_scenario("default")
    for e in s.event_sequence:
        assert 0 <= e.delay_ms <= 5000, f"delay_ms out of range: {e.delay_ms}"

def test_default_loop_true():
    assert get_scenario("default").loop is True

def test_all_blocked_loop_false():
    assert get_scenario("all-blocked").loop is False

def test_all_blocked_agents_blocked():
    s = get_scenario("all-blocked")
    for agent in s.initial_agents:
        assert agent.state == "blocked"
        assert agent.blocked_reason

# --- New field assertions ---

def test_default_has_initial_run():
    s = get_scenario("default")
    assert isinstance(s.initial_run, dict)
    assert "run_id" in s.initial_run
    assert "status" in s.initial_run
    assert "phase" in s.initial_run

def test_default_has_journal_entries():
    s = get_scenario("default")
    assert isinstance(s.journal_entries, dict)

def test_all_blocked_has_initial_run():
    s = get_scenario("all-blocked")
    assert isinstance(s.initial_run, dict)
    assert "run_id" in s.initial_run

def test_all_blocked_has_journal_entries():
    s = get_scenario("all-blocked")
    assert isinstance(s.journal_entries, dict)

def test_default_display_names_space_convention():
    s = get_scenario("default")
    for a in s.initial_agents:
        assert "-" not in a.display_name, f"display_name uses hyphen: {a.display_name!r}"

def test_all_blocked_display_names_space_convention():
    s = get_scenario("all-blocked")
    for a in s.initial_agents:
        assert "-" not in a.display_name, f"display_name uses hyphen: {a.display_name!r}"

