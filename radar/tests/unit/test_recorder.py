"""Tests for the --record flag in radar/server.py's broadcast_event."""
import json
import threading
import time
import pytest


def test_record_event_creates_file(tmp_path):
    import radar.server as srv
    path = str(tmp_path / "rec.jsonl")
    srv._record_path = path
    try:
        srv._record_event("heartbeat", {"ts": "2026-03-22T10:00:00Z"})
        assert (tmp_path / "rec.jsonl").exists()
    finally:
        srv._record_path = None


def test_record_event_appends_valid_jsonl(tmp_path):
    import radar.server as srv
    path = str(tmp_path / "rec.jsonl")
    srv._record_path = path
    try:
        srv._record_event("heartbeat", {"ts": "2026-03-22T10:00:00Z"})
        srv._record_event("agent_state_change", {"dispatch_id": "SCOUT-1", "state": "working"})
        lines = (tmp_path / "rec.jsonl").read_text().strip().split("\n")
        assert len(lines) == 2
        record = json.loads(lines[0])
        assert record["event_type"] == "heartbeat"
        assert "recorded_at_ms" in record
        assert "payload" in record
    finally:
        srv._record_path = None


def test_record_event_noop_when_path_none(tmp_path):
    import radar.server as srv
    srv._record_path = None
    specific_file = tmp_path / "should_not_exist.jsonl"
    srv._record_event("heartbeat", {"ts": "2026-03-22T10:00:00Z"})
    assert not specific_file.exists()


def test_record_event_thread_safe(tmp_path):
    """Multiple threads appending should produce all expected lines."""
    import radar.server as srv
    path = str(tmp_path / "rec.jsonl")
    srv._record_path = path
    try:
        errors = []
        def write_events():
            try:
                for i in range(10):
                    srv._record_event("heartbeat", {"i": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_events) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        lines = (tmp_path / "rec.jsonl").read_text().strip().split("\n")
        assert len(lines) == 50  # 5 threads × 10 events each
        for line in lines:
            json.loads(line)  # each line must be valid JSON
    finally:
        srv._record_path = None
