"""Tests for Python reasoning-journal entry validation."""

import json
import threading
from pathlib import Path

import pytest

import harness.journal_entry_validator as journal_module
import harness.squad_completion as completion_module
from harness.reasoning_journal_store import (
    JournalStoreError,
    REASONING_JOURNAL_LOCK_RANK,
)
from harness.journal_entry_validator import (
    default_journal_schema_path,
    prepare_journal_entries_for_append,
    validate_journal_entry,
)


def test_default_schema_comes_from_echelon_runtime_bundle() -> None:
    root = Path(__file__).resolve().parents[2]

    assert default_journal_schema_path() == (
        root / "runtime" / "workflow" / "journal-entry-types.yaml"
    )


def test_valid_registered_entry_passes() -> None:
    verdict = validate_journal_entry(
        {
            "type": "routing_decision",
            "data": {
                "from_phase": "phase1-why1",
                "to_phase": "phase2-how",
                "reason": "complete",
                "evoi_score": 0.8,
            },
        }
    )

    assert verdict.valid
    assert verdict.errors == []


def test_missing_required_field_fails_registered_type() -> None:
    verdict = validate_journal_entry(
        {
            "type": "routing_decision",
            "data": {
                "from_phase": "phase1-why1",
                "to_phase": "phase2-how",
                "reason": "missing score",
            },
        }
    )

    assert not verdict.valid
    assert "evoi_score" in verdict.errors[0]


def test_unknown_type_warns_but_is_valid() -> None:
    verdict = validate_journal_entry({"type": "future_signal", "data": {"x": 1}})

    assert verdict.valid
    assert verdict.warnings == ["Type not registered in schema: future_signal"]


def test_prepare_adds_schema_warning_for_invalid_registered_type() -> None:
    prepared = prepare_journal_entries_for_append(
        [
            {
                "type": "routing_decision",
                "data": {
                    "from_phase": "phase1-why1",
                    "to_phase": "phase2-how",
                    "reason": "missing score",
                },
            }
        ],
        phase_id="phase1-why1",
        next_id=7,
        timestamp="2026-06-26T12:00:00Z",
    )

    assert [entry["type"] for entry in prepared] == ["routing_decision", "schema_warning"]
    assert prepared[0]["id"] == 7
    assert prepared[1]["id"] == 8
    assert prepared[1]["data"]["violating_entry_id"] == 7
    assert prepared[1]["data"]["violation_type"] == "missing_required_field"


def test_prepare_quarantines_invalid_registered_type_when_strict() -> None:
    prepared = prepare_journal_entries_for_append(
        [
            {
                "type": "routing_decision",
                "data": {
                    "from_phase": "phase1-why1",
                    "to_phase": "phase2-how",
                    "reason": "missing score",
                },
            }
        ],
        phase_id="phase1-why1",
        next_id=7,
        timestamp="2026-06-26T12:00:00Z",
        invalid_registered_policy="quarantine",
    )

    assert [entry["type"] for entry in prepared] == ["schema_warning"]
    assert prepared[0]["id"] == 7
    assert prepared[0]["data"]["violating_entry_type"] == "routing_decision"
    assert prepared[0]["data"]["violation_type"] == "missing_required_field"


def test_journal_lock_serializes_shared_python_writer(
    tmp_path: Path,
) -> None:
    squad_dir = tmp_path / "runs" / "run-1"
    squad_dir.mkdir(parents=True)
    started = threading.Event()
    finished = threading.Event()

    def append() -> None:
        started.set()
        journal_module.append_reasoning_journal_entries(
            squad_dir,
            [{"type": "future_signal", "data": {"worker": True}}],
            phase_id="phase1-discover",
        )
        finished.set()

    with completion_module.reasoning_journal_lock(squad_dir):
        worker = threading.Thread(target=append)
        worker.start()
        assert started.wait(timeout=1)
        assert not finished.wait(timeout=0.1)
    worker.join(timeout=2)

    assert finished.is_set()
    assert (squad_dir / "reasoning-journal.lock").is_file()
    rows = [
        json.loads(line)
        for line in (
            squad_dir / "reasoning-journal.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["id"] == 1


def test_shared_journal_writer_rejects_malformed_preimage(
    tmp_path: Path,
) -> None:
    squad_dir = tmp_path / "runs" / "run-1"
    squad_dir.mkdir(parents=True)
    journal = squad_dir / "reasoning-journal.jsonl"
    journal.write_text("not-json\n", encoding="utf-8")
    before = journal.read_bytes()

    with pytest.raises(ValueError):
        journal_module.append_reasoning_journal_entries(
            squad_dir,
            [{"type": "future_signal", "data": {}}],
            phase_id="phase1-discover",
        )

    assert journal.read_bytes() == before


def test_reasoning_journal_lock_keeps_declared_rank_six() -> None:
    assert REASONING_JOURNAL_LOCK_RANK == 6
    assert (
        completion_module.REASONING_JOURNAL_LOCK_RANK
        == REASONING_JOURNAL_LOCK_RANK
    )


@pytest.mark.parametrize("failure_point", ("before_index", "after_index"))
def test_indexed_journal_batch_adopts_after_index_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    squad_dir = tmp_path / "runs/run-1"
    squad_dir.mkdir(parents=True)
    journal = squad_dir / "reasoning-journal.jsonl"
    index = squad_dir / "reasoning-journal-index.json"
    journal.write_text(
        '{"id":"RJ-001","type":"seed","data":{"keep":true}}\n',
        encoding="utf-8",
    )
    index.write_text(
        '{"last_entry_id":"RJ-001","unrelated":"preserve"}\n',
        encoding="utf-8",
    )
    entries = [
        {
            "type": "endocrine_event",
            "phase": "phase3-plan",
            "timestamp": "2026-07-23T10:00:00Z",
            "data": {
                "dispatch_id": "D-CRASH",
                "trigger": "on_gate_pass",
            },
        }
    ]
    real_replace = journal_module.durably_replace_file

    def crash_on_index(path: Path, content: bytes) -> None:
        if path == index:
            if failure_point == "after_index":
                real_replace(path, content)
            raise JournalStoreError("journal_io")
        real_replace(path, content)

    monkeypatch.setattr(
        journal_module,
        "durably_replace_file",
        crash_on_index,
    )

    with pytest.raises(ValueError):
        journal_module.append_indexed_reasoning_journal_entries(
            squad_dir,
            entries,
            phase_id="phase3-plan",
            batch_id="D-CRASH",
        )

    crash_postimage = journal.read_bytes()
    monkeypatch.setattr(
        journal_module,
        "durably_replace_file",
        real_replace,
    )
    retry_entries = json.loads(json.dumps(entries))
    retry_entries[0]["timestamp"] = "2026-07-23T11:00:00Z"

    adopted = journal_module.append_indexed_reasoning_journal_entries(
        squad_dir,
        retry_entries,
        phase_id="phase3-plan",
        batch_id="D-CRASH",
    )

    assert journal.read_bytes() == crash_postimage
    rows = [
        json.loads(line)
        for line in journal.read_text(encoding="utf-8").splitlines()
    ]
    dispatch_rows = [
        row
        for row in rows
        if row.get("data", {}).get("dispatch_id") == "D-CRASH"
    ]
    assert len(dispatch_rows) == 1
    assert adopted == dispatch_rows
    assert json.loads(index.read_text(encoding="utf-8")) == {
        "last_entry_id": "RJ-002",
        "unrelated": "preserve",
    }
