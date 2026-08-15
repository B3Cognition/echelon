from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.events import EventStore
from harness.re_v2.model import BudgetPolicy, RunManifest
from harness.re_v2.projection import (
    ReV2ProjectionError,
    project_run,
    rebuild_projection,
)
from harness.re_v2.run_store import ReV2Paths, create_run_store


NOW = "2026-08-14T12:00:00Z"


def digest(value: str) -> str:
    return content_digest(value.encode())


def manifest(run_id: str) -> RunManifest:
    return RunManifest(
        schema_version=1,
        engine="re-v2",
        engine_protocol_version="2.0",
        run_id=run_id,
        created_at=NOW,
        source_snapshot_id=digest("source"),
        source_snapshot_kind="content-snapshot",
        partition_manifest_id=digest("partition"),
        requested_goals=("baseline",),
        initial_budget_policy=BudgetPolicy(
            token_limit=100,
            active_ms_limit=1_000,
            provider_attempt_limit=2,
            artifact_generation_attempt_limit=2,
            semantic_repair_round_limit=1,
            result_contract_retry_limit=1,
        ),
        provider_contract={"provider": "fixture"},
        artifact_policy_versions={"inventory": "1"},
        parent_run_id=None,
    )


@dataclass(frozen=True)
class FixtureLedgerView:
    accepted_artifacts: Mapping[str, object]


def populated_run(tmp_path: Path) -> tuple[ReV2Paths, RunManifest]:
    run_dir = tmp_path / "re-projection"
    run_manifest = manifest(run_dir.name)
    paths = create_run_store(run_dir, run_manifest)
    store = EventStore(paths.events)
    store.append(
        "run_created",
        {"run_manifest_id": run_manifest.run_manifest_id},
        occurred_at=NOW,
    )
    store.append(
        "work_planned", {"work_item_ids": [digest("work")]}, occurred_at=NOW
    )
    return paths, run_manifest


def test_project_run_derives_status_usage_counts_and_roots_from_authorities(
    tmp_path: Path,
) -> None:
    run_manifest = manifest("re-projection")
    store_events = [
        ("run_created", {"run_manifest_id": run_manifest.run_manifest_id}),
        ("work_planned", {"work_item_ids": [digest("work")]}),
        (
            "dispatch_leased",
            {"dispatch_id": "dispatch-1", "work_item_id": digest("work")},
        ),
        (
            "dispatch_started",
            {"dispatch_id": "dispatch-1", "work_item_id": digest("work")},
        ),
        (
            "dispatch_observed",
            {
                "dispatch_id": "dispatch-1",
                "observation": {
                    "duration_ms": 75,
                    "ended_at": NOW,
                    "exit_code": 0,
                    "model_name": "fixture-model",
                    "output_truncated": False,
                    "provider_name": "fixture",
                    "result_contract_valid": True,
                    "started_at": NOW,
                    "stderr_digest": None,
                    "timed_out": False,
                    "token_usage": 42,
                },
                "work_item_id": digest("work"),
            },
        ),
        (
            "candidate_persisted",
            {
                "candidate_id": "candidate-1",
                "dispatch_id": "dispatch-1",
                "work_item_id": digest("work"),
            },
        ),
        (
            "candidate_certified",
            {
                "candidate_id": "candidate-1",
                "certification_id": digest("certification"),
                "work_item_id": digest("work"),
            },
        ),
        (
            "artifact_accepted",
            {
                "artifact_hash": digest("artifact"),
                "artifact_key_id": digest("artifact-key"),
                "certification_id": digest("certification"),
                "work_item_id": digest("work"),
            },
        ),
        ("run_completed", {"reason": "goals_satisfied"}),
    ]
    # EventStore supplies fully validated immutable EventRecord values.
    event_store = EventStore(tmp_path / "events.jsonl")
    events = tuple(
        event_store.append(event_type, payload, occurred_at=NOW)
        for event_type, payload in store_events
    )

    ledger = FixtureLedgerView(
        accepted_artifacts={
            digest("dependency-key"): SimpleNamespace(
                artifact_hash=digest("dependency"),
                artifact_key=SimpleNamespace(dependency_hashes=()),
            ),
            digest("artifact-key"): SimpleNamespace(
                artifact_hash=digest("artifact"),
                artifact_key=SimpleNamespace(
                    dependency_hashes=(digest("dependency"),)
                ),
            ),
        }
    )
    projection = project_run(run_manifest, events, ledger)

    assert projection["state"] == "complete"
    assert projection["current_work_item_id"] is None
    assert projection["usage"] == {
        "active_ms": 75,
        "known_tokens": 42,
        "token_coverage_complete": True,
        "unknown_token_dispatches": 0,
    }
    assert projection["candidate_counts"] == {"persisted": 1}
    assert projection["certification_counts"] == {"accepted": 1, "rejected": 0}
    assert projection["accepted_roots"] == [digest("artifact")]
    assert projection["pause_reason"] is None
    assert projection["terminal_reason"] == "goals_satisfied"


def test_projection_rebuild_is_byte_identical_and_ignores_existing_projection(
    tmp_path: Path,
) -> None:
    paths, _ = populated_run(tmp_path)
    paths.projection.write_text('{"stale":true}\n')

    first = canonical_json_bytes(rebuild_projection(paths))
    assert paths.projection.read_bytes() == first
    paths.projection.unlink()
    second = canonical_json_bytes(rebuild_projection(paths))

    assert first == second
    assert paths.projection.read_bytes() == second
    assert not tuple(paths.root.glob(".projection.json.*.tmp"))


def test_projection_write_retries_interrupted_write_and_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness.re_v2.projection as projection_module

    paths, _ = populated_run(tmp_path)
    real_write = os.write
    real_fsync = os.fsync
    write_calls = 0
    fsync_calls = 0

    def interrupted_write(fd: int, payload: bytes) -> int:
        nonlocal write_calls
        write_calls += 1
        if write_calls == 1:
            return real_write(fd, payload[:11])
        if write_calls == 2:
            raise InterruptedError
        return real_write(fd, payload)

    def interrupted_fsync(fd: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            raise InterruptedError
        real_fsync(fd)

    monkeypatch.setattr(projection_module.os, "write", interrupted_write)
    monkeypatch.setattr(projection_module.os, "fsync", interrupted_fsync)
    rebuilt = rebuild_projection(paths)

    assert paths.projection.read_bytes() == canonical_json_bytes(rebuilt)
    assert write_calls >= 3
    assert fsync_calls >= 3


_UNSORTED_DEPENDENCIES = tuple(reversed(sorted((digest("dep-a"), digest("dep-b")))))


@pytest.mark.parametrize(
    ("receipt", "message"),
    [
        (SimpleNamespace(artifact_hash=digest("artifact")), "artifact_key"),
        (
            SimpleNamespace(
                artifact_hash=digest("artifact"), artifact_key=SimpleNamespace()
            ),
            "dependency_hashes",
        ),
        (
            SimpleNamespace(
                artifact_hash=digest("artifact"),
                artifact_key=SimpleNamespace(
                    dependency_hashes=_UNSORTED_DEPENDENCIES
                ),
            ),
            "unique and sorted",
        ),
        (
            SimpleNamespace(
                artifact_hash=digest("artifact"),
                artifact_key=SimpleNamespace(
                    dependency_hashes=(digest("dep-a"), digest("dep-a"))
                ),
            ),
            "unique and sorted",
        ),
        (
            SimpleNamespace(
                artifact_hash=digest("artifact"),
                artifact_key=SimpleNamespace(dependency_hashes={digest("dep-a")}),
            ),
            "dependency_hashes",
        ),
    ],
)
def test_projection_rejects_noncanonical_ledger_dependency_structure(
    receipt: object, message: str
) -> None:
    ledger = FixtureLedgerView(accepted_artifacts={digest("key"): receipt})

    with pytest.raises(ReV2ProjectionError, match=message):
        project_run(manifest("re-projection"), (), ledger)
