"""Unit tests for fixed MemPalaceWriter."""
from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from codegen.memory.context import MemPalaceContext
from codegen.memory.mempalace_writer import MemPalaceWriter


def _make_ctx(wing="my-app", run_id="run-abc"):
    return MemPalaceContext(wing=wing, run_id=run_id, palace_path="/fake/palace")


def test_drawer_id_uses_sha256_matching_add_drawer():
    """drawer_id constructed by writer must match add_drawer's SHA256[:24] formula."""
    ctx = _make_ctx(wing="proj", run_id="run-1")
    writer = MemPalaceWriter(ctx)

    source_file = "codegen/RE"
    chunk_index = int(hashlib.sha256("run-1".encode()).hexdigest(), 16) & 0xFFFF
    expected_id = (
        f"drawer_proj_functional-requirements_"
        f"{hashlib.sha256((source_file + str(chunk_index)).encode()).hexdigest()[:24]}"
    )

    mock_col = MagicMock()
    mock_col.update = MagicMock()

    with patch.object(writer, "_get_collection", return_value=mock_col):
        with patch("codegen.memory.mempalace_writer.add_drawer", return_value=True):
            drawer_id = writer._write_drawer(
                wing="proj",
                room="functional-requirements",
                content="FR-001: test",
                metadata={"phase": "RE", "run_id": "run-1", "run_outcome": "in_progress"},
            )

    assert drawer_id == expected_id
    mock_col.update.assert_called_once_with(
        ids=[expected_id],
        metadatas=[{"phase": "RE", "run_id": "run-1", "run_outcome": "in_progress"}],
    )


def test_chunk_index_is_deterministic():
    """Same run_id always produces same chunk_index regardless of process restart."""
    ctx = _make_ctx(run_id="stable-run-id")
    writer = MemPalaceWriter(ctx)

    idx1 = int(hashlib.sha256("stable-run-id".encode()).hexdigest(), 16) & 0xFFFF
    idx2 = int(hashlib.sha256("stable-run-id".encode()).hexdigest(), 16) & 0xFFFF
    assert idx1 == idx2

    # Verify writer uses the same formula
    source_file = "codegen/RE"
    expected_id = (
        f"drawer_my-app_bugs_"
        f"{hashlib.sha256((source_file + str(idx1)).encode()).hexdigest()[:24]}"
    )
    mock_col = MagicMock()
    with patch.object(writer, "_get_collection", return_value=mock_col):
        with patch("codegen.memory.mempalace_writer.add_drawer", return_value=True):
            drawer_id = writer._write_drawer(
                wing="my-app", room="bugs", content="BUG-001: x",
                metadata={"phase": "RE"},
            )
    assert drawer_id == expected_id


def test_write_returns_none_when_add_drawer_is_none():
    """When mempalace not installed, write returns None without calling _get_collection."""
    ctx = _make_ctx()
    writer = MemPalaceWriter(ctx)

    with patch("codegen.memory.mempalace_writer.add_drawer", None):
        with patch.object(writer, "_get_collection") as mock_get_col:
            result = writer.write(room="functional-requirements", content="FR-001: x", phase="RE")

    assert result is None
    assert writer.write_failures == 0
    mock_get_col.assert_not_called()


def test_write_uses_wing_from_ctx():
    ctx = _make_ctx(wing="correct-wing")
    writer = MemPalaceWriter(ctx)

    mock_col = MagicMock()
    with patch.object(writer, "_get_collection", return_value=mock_col):
        with patch("codegen.memory.mempalace_writer.add_drawer", return_value=True) as mock_add:
            writer.write(room="bugs", content="BUG-001: crash", phase="GATE")

    _, kwargs = mock_add.call_args
    assert kwargs["wing"] == "correct-wing"


def test_backfill_run_outcome_calls_update_drawer_metadata():
    ctx = _make_ctx()
    writer = MemPalaceWriter(ctx)
    writer.drawers_written = ["drawer_my-app_bugs_abc123456789012345678901"]

    mock_col = MagicMock()
    with patch.object(writer, "_get_collection", return_value=mock_col):
        updated = writer.backfill_run_outcome("passed")

    assert updated == 1
    mock_col.update.assert_called_once_with(
        ids=["drawer_my-app_bugs_abc123456789012345678901"],
        metadatas=[{"run_outcome": "passed"}],
    )


def test_write_increments_failure_count_on_exception():
    ctx = _make_ctx()
    writer = MemPalaceWriter(ctx)

    with patch("codegen.memory.mempalace_writer.add_drawer", return_value=True):
        with patch.object(writer, "_get_collection", side_effect=RuntimeError("db error")):
            result = writer.write(room="bugs", content="x", phase="RE")

    assert result is None
    assert writer.write_failures == 1


def test_backfill_status_updates_drawer_metadata():
    ctx = _make_ctx()
    writer = MemPalaceWriter(ctx)

    mock_col = MagicMock()
    with patch.object(writer, "_get_collection", return_value=mock_col):
        result = writer.backfill_status(["drawer-id-abc"], "delivered")

    assert result == 1
    mock_col.update.assert_called_once_with(
        ids=["drawer-id-abc"],
        metadatas=[{"status": "delivered"}],
    )


def test_backfill_status_rejects_invalid_status():
    ctx = _make_ctx()
    writer = MemPalaceWriter(ctx)
    result = writer.backfill_status(["drawer-id-abc"], "invalid-status")
    assert result == 0
