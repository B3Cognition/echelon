"""Tests for the /journal endpoint — returns JSON array."""
import pytest
from pathlib import Path


def test_journal_no_params_returns_empty_list(mock_app):
    r = mock_app.get("/journal")
    assert r.status_code == 200
    assert r.get_json() == []


def test_journal_missing_agent_returns_empty_list(mock_app):
    r = mock_app.get("/journal?run_id=mock-run-default")
    assert r.get_json() == []


def test_journal_missing_run_id_returns_empty_list(mock_app):
    r = mock_app.get("/journal?agent=MOCK-SCOUT-1")
    assert r.get_json() == []


def test_journal_empty_agent_returns_empty_list(mock_app):
    r = mock_app.get("/journal?agent=&run_id=mock-run-default")
    assert r.get_json() == []


def test_journal_empty_run_id_returns_empty_list(mock_app):
    r = mock_app.get("/journal?agent=MOCK-SCOUT-1&run_id=")
    assert r.get_json() == []


def test_journal_unknown_agent_returns_empty_list(mock_app):
    r = mock_app.get("/journal?agent=NONEXISTENT&run_id=mock-run-default")
    assert r.get_json() == []


def test_journal_wrong_run_id_returns_empty_list(mock_app):
    r = mock_app.get("/journal?agent=MOCK-SCOUT-1&run_id=wrong-run-id")
    assert r.get_json() == []


# Test non-empty response using a scenario that has journal entries.
# The "default" scenario has journal_entries: {} so we need a fresh app.
@pytest.fixture
def journal_app(squad_dir):
    """App backed by a minimal scenario that has journal entries."""
    from radar.mock_server import create_app
    from radar.scenarios import MockAgent, Scenario
    import time

    _RUN_ID = "test-journal-run-001"
    scenario = Scenario(
        name="test-journal",
        description="Scenario with journal entries for testing",
        initial_agents=[
            MockAgent("SCOUT-1", "SCOUT", "Scout 1", "idle", "discover", "2026-03-22T10:00:00Z")
        ],
        event_sequence=[],
        initial_run={
            "run_id": _RUN_ID, "status": "running", "phase": "discover",
            "phase_display": "DISCOVER", "iteration": 1,
            "created_at": "2026-03-22T10:00:00Z", "updated_at": "2026-03-22T10:00:00Z",
            "completed_at": None,
        },
        journal_entries={
            "SCOUT-1": [
                {"id": "j-001", "dispatch_id": "SCOUT-1", "codename": "SCOUT",
                 "run_id": _RUN_ID, "timestamp_ms": 2000, "type": "finding",
                 "content": "Found bounded context A"},
                {"id": "j-002", "dispatch_id": "SCOUT-1", "codename": "SCOUT",
                 "run_id": _RUN_ID, "timestamp_ms": 1000, "type": "decision",
                 "content": "Older entry"},
            ]
        },
        loop=False,
    )
    app, stop_event = create_app(scenario, squad_dir=squad_dir)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, _RUN_ID
    stop_event.set()
    time.sleep(0.05)


def test_journal_returns_entries_sorted_newest_first(journal_app):
    client, run_id = journal_app
    r = client.get(f"/journal?agent=SCOUT-1&run_id={run_id}")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data) == 2
    # newest-first: timestamp_ms 2000 before 1000
    assert data[0]["timestamp_ms"] == 2000
    assert data[1]["timestamp_ms"] == 1000


def test_journal_returns_list_not_dict(journal_app):
    client, run_id = journal_app
    r = client.get(f"/journal?agent=SCOUT-1&run_id={run_id}")
    assert isinstance(r.get_json(), list)


def test_journal_entry_has_required_fields(journal_app):
    client, run_id = journal_app
    r = client.get(f"/journal?agent=SCOUT-1&run_id={run_id}")
    entry = r.get_json()[0]
    for field in ("id", "dispatch_id", "codename", "run_id", "timestamp_ms", "type", "content"):
        assert field in entry, f"missing field: {field}"
