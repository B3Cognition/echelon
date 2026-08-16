from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.events import EventStore
from harness.re_v2.model import BudgetPolicy, RunManifest
from harness.re_v2.run_store import create_run_store


NOW = "2026-08-14T12:00:00Z"
WORK_ITEM_ID = content_digest(b"work-item")
DISPATCH_ID = "dispatch-status-fixture"


def _paused_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "re-20260814-120000-000001"
    manifest = RunManifest(
        schema_version=1,
        engine="re-v2",
        engine_protocol_version="2.0",
        run_id=run_dir.name,
        created_at=NOW,
        source_snapshot_id=content_digest(b"snapshot"),
        source_snapshot_kind="content-snapshot",
        partition_manifest_id=content_digest(b"partitions"),
        requested_goals=("inventory",),
        initial_budget_policy=BudgetPolicy(
            token_limit=100,
            active_ms_limit=5_000,
            provider_attempt_limit=3,
            artifact_generation_attempt_limit=2,
            semantic_repair_round_limit=1,
            result_contract_retry_limit=1,
        ),
        provider_contract={"provider": "deterministic-inventory"},
        artifact_policy_versions={"L0": "egr-164-v1"},
        parent_run_id=None,
    )
    paths = create_run_store(run_dir, manifest)
    events = EventStore(paths)
    events.append(
        "run_created",
        {"run_manifest_id": manifest.run_manifest_id},
        occurred_at=NOW,
    )
    events.append(
        "work_planned",
        {"work_item_ids": [WORK_ITEM_ID]},
        occurred_at="2026-08-14T12:00:01Z",
    )
    events.append(
        "dispatch_leased",
        {"dispatch_id": DISPATCH_ID, "work_item_id": WORK_ITEM_ID},
        occurred_at="2026-08-14T12:00:02Z",
    )
    events.append(
        "dispatch_started",
        {
            "attempt_index": 1,
            "attempt_kind": "initial_generation",
            "dispatch_id": DISPATCH_ID,
            "work_item_id": WORK_ITEM_ID,
        },
        occurred_at="2026-08-14T12:00:02Z",
    )
    events.append(
        "dispatch_observed",
        {
            "dispatch_id": DISPATCH_ID,
            "observation": {
                "started_at": "2026-08-14T12:00:02Z",
                "ended_at": "2026-08-14T12:00:03Z",
                "duration_ms": 1_000,
                "exit_code": 0,
                "timed_out": False,
                "output_truncated": False,
                "result_contract_valid": True,
                "token_usage": 100,
                "provider_name": "deterministic-inventory",
                "model_name": "none",
                "stderr_digest": None,
            },
            "work_item_id": WORK_ITEM_ID,
        },
        occurred_at="2026-08-14T12:00:03Z",
    )
    events.append(
        "run_paused",
        {"reason": "token_limit", "reason_code": "tokens_exhausted"},
        occurred_at="2026-08-14T12:00:04Z",
    )
    paths.projection.write_text(
        json.dumps({"state": "complete", "known_tokens": 0}),
        encoding="utf-8",
    )
    return run_dir


def _terminal_run(tmp_path: Path, event_type: str, reason: str) -> Path:
    run_dir = tmp_path / "runs" / f"re-{event_type}"
    manifest = RunManifest(
        schema_version=1,
        engine="re-v2",
        engine_protocol_version="2.0",
        run_id=run_dir.name,
        created_at=NOW,
        source_snapshot_id=content_digest(b"terminal-snapshot"),
        source_snapshot_kind="content-snapshot",
        partition_manifest_id=content_digest(b"terminal-partitions"),
        requested_goals=("inventory",),
        initial_budget_policy=BudgetPolicy(
            token_limit=500,
            active_ms_limit=5_000,
            provider_attempt_limit=3,
            artifact_generation_attempt_limit=2,
            semantic_repair_round_limit=1,
            result_contract_retry_limit=1,
        ),
        provider_contract={"provider": "deterministic-inventory"},
        artifact_policy_versions={"L0": "egr-164-v1"},
        parent_run_id=None,
    )
    paths = create_run_store(run_dir, manifest)
    events = EventStore(paths)
    events.append(
        "run_created",
        {"run_manifest_id": manifest.run_manifest_id},
        occurred_at=NOW,
    )
    events.append(event_type, {"reason": reason}, occurred_at="2026-08-14T12:00:01Z")
    return run_dir


@pytest.mark.unit
def test_v2_paused_banner_replays_authority_and_names_next_action(
    tmp_path: Path,
) -> None:
    from harness.re_v2.status import render_v2_status

    output = render_v2_status(_paused_run(tmp_path))

    assert "RE V2 — PAUSED" in output
    assert "token_limit: 100 / 100" in output
    assert "reason: token_limit" in output
    assert "echelon re continue --re-token-limit" in output
    assert "RE V2 — COMPLETE" not in output


@pytest.mark.unit
def test_v2_status_json_exposes_the_same_operator_facts(tmp_path: Path) -> None:
    from harness.re_v2.status import render_v2_status

    run_dir = _paused_run(tmp_path)
    data = json.loads(render_v2_status(run_dir, as_json=True))
    human = render_v2_status(run_dir)

    assert data["engine"] == "re-v2"
    assert data["engine_protocol_version"] == "2.0"
    assert data["source_snapshot_id"] == content_digest(b"snapshot")
    assert data["partition_manifest_id"] == content_digest(b"partitions")
    assert data["requested_goals"] == ["inventory"]
    assert data["layers"] == {"L0": {"accepted_artifacts": 0, "status": "pending"}}
    assert data["current_work_item_id"] == WORK_ITEM_ID
    assert data["token_coverage"] == {
        "complete": True,
        "known_tokens": 100,
        "unknown_dispatches": 0,
    }
    assert data["budgets"]["tokens"] == {
        "authorized": 100,
        "remaining": 0,
        "used": 100,
    }
    assert data["budgets"]["active_ms"] == {
        "authorized": 5_000,
        "remaining": 4_000,
        "used": 1_000,
    }
    assert set(data["budgets"]) == {
        "tokens",
        "active_ms",
        "provider_attempts",
        "generation_attempts",
        "semantic_rounds",
        "result_contract_retries",
    }
    assert data["artifact_counts"] == {
        "adopted": 0,
        "certified": 0,
        "generated": 0,
        "rejected": 0,
        "reused": 0,
    }
    assert data["audit"] == "not registered"
    assert data["synthesis"] == "not registered"
    assert data["publication_generation_id"] is None
    assert data["status"] == "paused"
    assert data["reason_code"] == "tokens_exhausted"
    assert data["reason"] == "token_limit"
    for value in (
        data["engine"],
        data["engine_protocol_version"],
        data["source_snapshot_id"],
        data["partition_manifest_id"],
        data["status"].upper(),
        data["reason"],
    ):
        assert value in human


@pytest.mark.unit
@pytest.mark.parametrize(
    ("event_type", "expected_status", "expected_banner"),
    (
        ("run_completed", "complete", "RE V2 — COMPLETE"),
        (
            "run_finalized_partial",
            "finalized_partial",
            "RE V2 — FINALIZED PARTIAL",
        ),
        ("run_failed", "failed", "RE V2 — FAILED"),
    ),
)
def test_v2_terminal_banners_come_from_authoritative_events(
    tmp_path: Path,
    event_type: str,
    expected_status: str,
    expected_banner: str,
) -> None:
    from harness.re_v2.status import render_v2_status

    reason = f"exact {event_type} reason"
    run_dir = _terminal_run(tmp_path, event_type, reason)

    data = json.loads(render_v2_status(run_dir, as_json=True))
    human = render_v2_status(run_dir)

    assert data["status"] == expected_status
    assert data["reason"] == reason
    assert expected_banner in human
    assert f"reason: {reason}" in human
    assert "echelon re continue" not in human
