"""Real process, recovery, and capacity checks for the inactive authority."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from pathlib import Path
import sqlite3
import time

import pytest

from harness.element_identity_store import IdentityStore, IdentityStoreError


pytestmark = pytest.mark.integration


def _reserve_batch(arguments):
    workspace, index = arguments
    return IdentityStore.open(Path(workspace)).reserve(
        spec_id="001-demo", kind="AC", operation_id=f"process-{index}", count=100,
    )


def _commit_then_wait(workspace, ready):
    store = IdentityStore.open(Path(workspace))
    store.reserve(spec_id="001-demo", kind="AC", operation_id="terminated", count=3)
    ready.set()
    time.sleep(60)


def _import_while_backing_up(workspace, ready):
    store = IdentityStore.open(Path(workspace))
    for batch in range(30):
        store.import_identities(spec_id="001-demo", operation_id=f"import-{batch}", definitions=[
            (f"AC-{number:06d}", f"subject {number}")
            for number in range(batch * 100 + 1, batch * 100 + 101)
        ])
        ready.set()
        time.sleep(0.01)


def test_multiprocess_contention_reserves_disjoint_batches(tmp_path):
    IdentityStore.initialize(tmp_path)
    with ProcessPoolExecutor(max_workers=6, mp_context=multiprocessing.get_context("spawn")) as executor:
        batches = list(executor.map(_reserve_batch, [(str(tmp_path), index) for index in range(30)]))
    labels = [label for batch in batches for label in batch]
    assert len(labels) == len(set(labels)) == 3000
    assert "AC-000001" in labels and "AC-003000" in labels
    assert IdentityStore.open(tmp_path).high_water(spec_id="001-demo", kind="AC") == "3000"


def test_terminated_process_keeps_committed_reservation_retryable(tmp_path):
    IdentityStore.initialize(tmp_path)
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(target=_commit_then_wait, args=(str(tmp_path), ready))
    process.start()
    try:
        assert ready.wait(20), "child did not commit"
        process.terminate()
        process.join(10)
        assert not process.is_alive()
        store = IdentityStore.open(tmp_path)
        assert store.reserve(spec_id="001-demo", kind="AC", operation_id="terminated", count=3) == (
            "AC-000001", "AC-000002", "AC-000003",
        )
        assert store.reserve(spec_id="001-demo", kind="AC", operation_id="next", count=1) == ("AC-000004",)
    finally:
        if process.is_alive():
            process.terminate()
            process.join(10)


def test_online_backup_is_consistent_while_another_process_imports(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = IdentityStore.initialize(workspace)
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    writer = context.Process(target=_import_while_backing_up, args=(str(workspace), ready))
    writer.start()
    try:
        assert ready.wait(20)
        backup = tmp_path / "backup"
        store.backup(backup)
        restored_workspace = tmp_path / "restored"
        restored_workspace.mkdir()
        restored = IdentityStore.restore(restored_workspace, backup)
        watermark = int(restored.high_water(spec_id="001-demo", kind="AC"))
        assert 100 <= watermark <= 3000 and watermark % 100 == 0
        with sqlite3.connect(backup / "registry.sqlite3") as connection:
            assert connection.execute("SELECT count(*) FROM entities").fetchone()[0] == watermark
        assert restored.lookup(spec_id="001-demo", element_id=f"AC-{watermark:06d}")["subject"] == f"subject {watermark}"
        writer.join(20)
        assert writer.exitcode == 0
    finally:
        if writer.is_alive():
            writer.terminate()
            writer.join(10)


def test_busy_writer_times_out_without_reusing_or_advancing_reservations(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    database = tmp_path / ".echelon/identity/registry.sqlite3"
    with sqlite3.connect(database) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(IdentityStoreError, match="locked"):
            store.reserve(spec_id="001-demo", kind="AC", operation_id="busy", count=1)
    assert store.reserve(spec_id="001-demo", kind="AC", operation_id="busy", count=1) == ("AC-000001",)


@pytest.mark.slow
def test_million_identity_capacity_uses_indexed_lookup_and_counter(tmp_path):
    started = time.monotonic()
    store = IdentityStore.initialize(tmp_path)
    for first in range(1, 1_000_001, 10_000):
        store.import_identities(spec_id="capacity", operation_id=f"import-{first}", definitions=[
            (f"AC-{ordinal:06d}", f"subject {ordinal}") for ordinal in range(first, first + 10_000)
        ])
    imported_seconds = time.monotonic() - started
    opened = time.monotonic()
    reopened = IdentityStore.open(tmp_path)
    open_seconds = time.monotonic() - opened
    allocation_started = time.monotonic()
    assert reopened.reserve(spec_id="capacity", kind="AC", operation_id="after-million", count=1) == ("AC-1000001",)
    allocation_seconds = time.monotonic() - allocation_started
    assert reopened.lookup(spec_id="capacity", element_id="AC-1000000")["subject"] == "subject 1000000"
    database = tmp_path / ".echelon/identity/registry.sqlite3"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM entities").fetchone()[0] == 1_000_000
        queries = [
            ("SELECT * FROM entities WHERE spec_id=? AND element_id=?", ("capacity", "AC-1000000")),
            ("SELECT high_water FROM counters WHERE spec_id=? AND kind=?", ("capacity", "AC")),
            ("SELECT element_id FROM entities WHERE spec_id=? AND kind=? AND ordinal=?", ("capacity", "AC", "1000000")),
            ("SELECT last_ordinal FROM reservations WHERE spec_id=? AND kind=? "
             "AND (first_length, first_ordinal) <= (?, ?) ORDER BY first_length DESC, first_ordinal DESC LIMIT 1",
             ("capacity", "AC", 7, "1000001")),
            ("SELECT last_ordinal FROM reservations WHERE spec_id=? AND kind=? "
             "ORDER BY length(last_ordinal) DESC, last_ordinal DESC LIMIT 1", ("capacity", "AC")),
            ("SELECT ordinal FROM entities WHERE spec_id=? AND kind=? AND ordinal IS NOT NULL "
             "ORDER BY length(ordinal) DESC, ordinal DESC LIMIT 1", ("capacity", "AC")),
        ]
        for query, args in queries:
            plan = connection.execute("EXPLAIN QUERY PLAN " + query, args).fetchall()
            assert any("SEARCH" in row[3] and ("INDEX" in row[3] or "PRIMARY KEY" in row[3]) for row in plan), plan
            assert not any("SCAN" in row[3] for row in plan), plan
            assert not any("TEMP B-TREE" in row[3] for row in plan), plan
    print(f"CAPACITY records=1000000 import_seconds={imported_seconds:.3f} "
          f"open_seconds={open_seconds:.6f} allocation_seconds={allocation_seconds:.6f} "
          f"database_bytes={database.stat().st_size}")
