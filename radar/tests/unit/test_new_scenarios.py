"""Tests for greenfield, brownfield, and blocked-escalation scenarios."""
from radar.scenarios import get_scenario

# ── greenfield ────────────────────────────────────────────────────────────

def test_greenfield_registered():
    assert get_scenario("greenfield") is not None

def test_greenfield_loop_false():
    assert get_scenario("greenfield").loop is False

def test_greenfield_agent_count():
    assert len(get_scenario("greenfield").initial_agents) == 13

def test_greenfield_has_initial_run():
    s = get_scenario("greenfield")
    assert s.initial_run["run_id"] == "squad-gf-20260322-1000"
    assert s.initial_run["status"] == "running"

def test_greenfield_terminal_event_is_done():
    s = get_scenario("greenfield")
    run_events = [e for e in s.event_sequence if e.event_type == "run_state_change"]
    terminal = run_events[-1]
    assert terminal.payload["run"]["status"] == "done"
    assert terminal.payload["run"]["completed_at"] is not None

def test_greenfield_has_journal_entries():
    s = get_scenario("greenfield")
    assert len(s.journal_entries) >= 3  # at least 3 agents have journal entries

def test_greenfield_display_names_space_convention():
    s = get_scenario("greenfield")
    for a in s.initial_agents:
        assert "-" not in a.display_name, f"display_name uses hyphen: {a.display_name!r}"

# ── brownfield ────────────────────────────────────────────────────────────

def test_brownfield_registered():
    assert get_scenario("brownfield") is not None

def test_brownfield_agent_count():
    assert len(get_scenario("brownfield").initial_agents) == 14

def test_brownfield_has_golddigger():
    s = get_scenario("brownfield")
    ids = [a.dispatch_id for a in s.initial_agents]
    assert "GOLDDIGGER-1" in ids

def test_brownfield_golddigger_before_scout():
    s = get_scenario("brownfield")
    ids = [a.dispatch_id for a in s.initial_agents]
    assert ids.index("GOLDDIGGER-1") < ids.index("SCOUT-1")

def test_brownfield_terminal_event_is_done():
    s = get_scenario("brownfield")
    run_events = [e for e in s.event_sequence if e.event_type == "run_state_change"]
    terminal = run_events[-1]
    assert terminal.payload["run"]["status"] == "done"
    assert terminal.payload["run"]["completed_at"] is not None

def test_brownfield_loop_false():
    assert get_scenario("brownfield").loop is False

# ── blocked-escalation ────────────────────────────────────────────────────

def test_blocked_escalation_registered():
    assert get_scenario("blocked-escalation") is not None

def test_blocked_escalation_agent_count():
    assert len(get_scenario("blocked-escalation").initial_agents) == 15

def test_blocked_escalation_has_gatekeeper_block():
    s = get_scenario("blocked-escalation")
    blocked_events = [e for e in s.event_sequence
                      if e.event_type == "agent_state_change"
                      and e.payload.get("state") == "blocked"]
    assert len(blocked_events) >= 1
    assert blocked_events[0].payload["dispatch_id"] == "GATEKEEPER-1"

def test_blocked_escalation_has_blocked_run_state():
    s = get_scenario("blocked-escalation")
    run_events = [e for e in s.event_sequence if e.event_type == "run_state_change"]
    statuses = [e.payload["run"]["status"] for e in run_events]
    assert "blocked" in statuses

def test_blocked_escalation_terminal_event_is_done():
    s = get_scenario("blocked-escalation")
    run_events = [e for e in s.event_sequence if e.event_type == "run_state_change"]
    assert run_events[-1].payload["run"]["status"] == "done"

def test_blocked_escalation_has_cartographer2():
    s = get_scenario("blocked-escalation")
    ids = [a.dispatch_id for a in s.initial_agents]
    assert "CARTOGRAPHER-2" in ids

def test_blocked_escalation_loop_false():
    assert get_scenario("blocked-escalation").loop is False
