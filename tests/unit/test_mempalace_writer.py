"""Unit tests for fixed MemPalaceWriter."""
from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from codegen.memory.context import MemPalaceContext
import codegen.memory.mempalace_writer as writer_module
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


def test_write_merges_extra_metadata(monkeypatch, tmp_path):
    captured = {}
    ctx = MemPalaceContext(wing="demo", run_id="run-1", palace_path=str(tmp_path))
    writer = MemPalaceWriter(ctx)

    def fake_write_drawer(*, wing, room, content, metadata):
        captured.update(metadata)
        return "drawer_demo"

    monkeypatch.setattr(writer, "_write_drawer", fake_write_drawer)

    writer.write(
        room="functional-requirements",
        content="FR-001: Upload.",
        phase="RE",
        source_file="specs/001/spec.md",
        extra_metadata={"artifact_hash": "sha256:" + "1" * 64, "canonical": True},
    )

    assert captured["artifact_hash"] == "sha256:" + "1" * 64
    assert captured["canonical"] is True
    assert captured["run_id"] == "run-1"


class _ExactCollection:
    def __init__(self) -> None:
        self.records: dict[str, tuple[str, dict[str, object]]] = {}
        self.upsert_calls = 0
        self.add_calls = 0

    def get(self, *, ids, include):
        found = [drawer_id for drawer_id in ids if drawer_id in self.records]
        return {
            "ids": found,
            "documents": [self.records[drawer_id][0] for drawer_id in found],
            "metadatas": [self.records[drawer_id][1] for drawer_id in found],
        }

    def upsert(self, *, ids, documents, metadatas):
        self.upsert_calls += 1
        for drawer_id, document, metadata in zip(
            ids,
            documents,
            metadatas,
            strict=True,
        ):
            self.records[drawer_id] = (document, metadata)

    def add(self, *, ids, documents, metadatas):
        self.add_calls += 1
        for drawer_id, document, metadata in zip(
            ids,
            documents,
            metadatas,
            strict=True,
        ):
            if drawer_id in self.records:
                raise ValueError("duplicate ID")
            self.records[drawer_id] = (document, metadata)


def test_deterministic_requirement_drawer_ids_are_unique_and_path_run_independent() -> None:
    digest = "1" * 64
    first = writer_module.deterministic_requirement_drawer_id(
        wing="demo",
        room="functional-requirements",
        spec_sha256=digest,
        requirement_id="FR-001",
        content="FR-001: First",
    )
    second = writer_module.deterministic_requirement_drawer_id(
        wing="demo",
        room="functional-requirements",
        spec_sha256=digest,
        requirement_id="FR-002",
        content="FR-002: Second",
    )
    replay = writer_module.deterministic_requirement_drawer_id(
        wing="demo",
        room="functional-requirements",
        spec_sha256=digest,
        requirement_id="FR-001",
        content="FR-001: First",
    )

    assert first != second
    assert replay == first
    assert len(first.rsplit("_", 1)[-1]) == 64


def test_write_exact_distinguishes_written_from_exact_existing() -> None:
    ctx = _make_ctx(wing="demo", run_id="run-one")
    writer = MemPalaceWriter(ctx)
    collection = _ExactCollection()
    digest = "2" * 64
    content = "FR-001: Upload."
    drawer_id = writer_module.deterministic_requirement_drawer_id(
        wing="demo",
        room="functional-requirements",
        spec_sha256=digest,
        requirement_id="FR-001",
        content=content,
    )

    with patch.object(writer, "_get_collection", return_value=collection):
        with patch(
            "codegen.memory.mempalace_writer.add_drawer",
            object(),
        ):
            first = writer.write_exact(
                room="functional-requirements",
                content=content,
                phase="RE",
                drawer_id=drawer_id,
                spec_sha256=digest,
                requirement_id="FR-001",
                source_file="/first/location/spec.md",
            )
            replay = writer.write_exact(
                room="functional-requirements",
                content=content,
                phase="RE",
                drawer_id=drawer_id,
                spec_sha256=digest,
                requirement_id="FR-001",
                source_file="/different/location/spec.md",
            )

    assert first.outcome == "written"
    assert replay.outcome == "already_present"
    assert first.drawer_id == replay.drawer_id == drawer_id
    assert collection.add_calls == 1
    assert collection.upsert_calls == 0


def test_write_exact_protects_and_verifies_wing_and_room_metadata() -> None:
    ctx = _make_ctx(wing="demo")
    writer = MemPalaceWriter(ctx)
    collection = _ExactCollection()
    digest = "7" * 64
    content = "FR-001: Upload."
    room = "functional-requirements"
    drawer_id = writer_module.deterministic_requirement_drawer_id(
        wing="demo",
        room=room,
        spec_sha256=digest,
        requirement_id="FR-001",
        content=content,
    )

    with patch.object(writer, "_get_collection", return_value=collection):
        with patch(
            "codegen.memory.mempalace_writer.add_drawer",
            object(),
        ):
            written = writer.write_exact(
                room=room,
                content=content,
                phase="RE",
                drawer_id=drawer_id,
                spec_sha256=digest,
                requirement_id="FR-001",
                extra_metadata={
                    "wing": "other",
                    "room": "bugs",
                    "scope": "other",
                    "canonical": False,
                    "artifact_hash": "sha256:" + ("0" * 64),
                },
            )
            verified = writer.verify_exact(
                room=room,
                content=content,
                drawer_id=drawer_id,
                spec_sha256=digest,
                requirement_id="FR-001",
            )
            stored_wing = collection.records[drawer_id][1]["wing"]
            stored_room = collection.records[drawer_id][1]["room"]
            stored_scope = collection.records[drawer_id][1]["scope"]
            stored_canonical = collection.records[drawer_id][1][
                "canonical"
            ]
            stored_artifact_hash = collection.records[drawer_id][1][
                "artifact_hash"
            ]
            collection.records[drawer_id][1]["wing"] = "other"
            drifted = writer.verify_exact(
                room=room,
                content=content,
                drawer_id=drawer_id,
                spec_sha256=digest,
                requirement_id="FR-001",
            )

    assert written.outcome == "written"
    assert verified.outcome == "already_present"
    assert stored_wing == "demo"
    assert stored_room == room
    assert stored_scope == "canonical"
    assert stored_canonical is True
    assert stored_artifact_hash == f"sha256:{digest}"
    assert drifted.outcome == "drift"


def test_write_exact_rejects_same_id_content_drift_without_overwrite() -> None:
    ctx = _make_ctx(wing="demo")
    writer = MemPalaceWriter(ctx)
    collection = _ExactCollection()
    digest = "3" * 64
    expected_content = "FR-001: Expected"
    drawer_id = writer_module.deterministic_requirement_drawer_id(
        wing="demo",
        room="functional-requirements",
        spec_sha256=digest,
        requirement_id="FR-001",
        content=expected_content,
    )
    collection.records[drawer_id] = (
        "FR-001: Drifted",
        {
            "canonical_spec_sha256": digest,
            "requirement_id": "FR-001",
            "requirement_content_sha256": hashlib.sha256(
                b"FR-001: Drifted"
            ).hexdigest(),
        },
    )

    with patch.object(writer, "_get_collection", return_value=collection):
        with patch(
            "codegen.memory.mempalace_writer.add_drawer",
            object(),
        ):
            result = writer.write_exact(
                room="functional-requirements",
                content=expected_content,
                phase="RE",
                drawer_id=drawer_id,
                spec_sha256=digest,
                requirement_id="FR-001",
            )

    assert result.outcome == "drift"
    assert collection.upsert_calls == 0
    assert collection.records[drawer_id][0] == "FR-001: Drifted"


def test_write_exact_does_not_overwrite_racing_same_id_drift() -> None:
    ctx = _make_ctx(wing="demo")
    writer = MemPalaceWriter(ctx)
    digest = "6" * 64
    content = "FR-001: Expected"
    drawer_id = writer_module.deterministic_requirement_drawer_id(
        wing="demo",
        room="functional-requirements",
        spec_sha256=digest,
        requirement_id="FR-001",
        content=content,
    )

    class RacingCollection(_ExactCollection):
        def add(self, *, ids, documents, metadatas):
            self.records[drawer_id] = (
                "FR-001: Racing drift",
                {
                    "canonical_spec_sha256": digest,
                    "requirement_id": "FR-001",
                    "requirement_content_sha256": hashlib.sha256(
                        b"FR-001: Racing drift"
                    ).hexdigest(),
                },
            )
            raise ValueError("duplicate ID")

    collection = RacingCollection()
    with patch.object(writer, "_get_collection", return_value=collection):
        with patch(
            "codegen.memory.mempalace_writer.add_drawer",
            object(),
        ):
            result = writer.write_exact(
                room="functional-requirements",
                content=content,
                phase="RE",
                drawer_id=drawer_id,
                spec_sha256=digest,
                requirement_id="FR-001",
            )

    assert result.outcome == "drift"
    assert collection.records[drawer_id][0] == "FR-001: Racing drift"


def test_write_exact_distinguishes_unavailable_from_write_failure() -> None:
    ctx = _make_ctx(wing="demo")
    writer = MemPalaceWriter(ctx)
    digest = "4" * 64
    content = "FR-001: Upload."
    drawer_id = writer_module.deterministic_requirement_drawer_id(
        wing="demo",
        room="functional-requirements",
        spec_sha256=digest,
        requirement_id="FR-001",
        content=content,
    )

    with patch("codegen.memory.mempalace_writer.add_drawer", None):
        unavailable = writer.write_exact(
            room="functional-requirements",
            content=content,
            phase="RE",
            drawer_id=drawer_id,
            spec_sha256=digest,
            requirement_id="FR-001",
        )
    with patch(
        "codegen.memory.mempalace_writer.add_drawer",
        object(),
    ):
        with patch.object(
            writer,
            "_get_collection",
            side_effect=RuntimeError("database unavailable"),
        ):
            failed = writer.write_exact(
                room="functional-requirements",
                content=content,
                phase="RE",
                drawer_id=drawer_id,
                spec_sha256=digest,
                requirement_id="FR-001",
            )

    assert unavailable.outcome == "unavailable"
    assert failed.outcome == "failed"
