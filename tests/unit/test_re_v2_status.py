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
PROVIDER_CONTRACT = {
    "provider": "deterministic-inventory",
    "provider_protocol_version": "re-v2-l0-v1",
    "result_contract_id": "deterministic-inventory-v1",
}


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
        provider_contract=PROVIDER_CONTRACT,
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
        provider_contract=PROVIDER_CONTRACT,
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


def _created_run(
    tmp_path: Path,
    *,
    suffix: str,
    requested_goals: tuple[str, ...] = ("inventory",),
    artifact_policy_versions: dict[str, str] | None = None,
) -> Path:
    run_dir = tmp_path / "runs" / f"re-{suffix}"
    manifest = RunManifest(
        schema_version=1,
        engine="re-v2",
        engine_protocol_version="2.0",
        run_id=run_dir.name,
        created_at=NOW,
        source_snapshot_id=content_digest(f"{suffix}-snapshot".encode()),
        source_snapshot_kind="content-snapshot",
        partition_manifest_id=content_digest(f"{suffix}-partitions".encode()),
        requested_goals=requested_goals,
        initial_budget_policy=BudgetPolicy(
            token_limit=500,
            active_ms_limit=5_000,
            provider_attempt_limit=1,
            artifact_generation_attempt_limit=1,
            semantic_repair_round_limit=2,
            result_contract_retry_limit=3,
        ),
        provider_contract=PROVIDER_CONTRACT,
        artifact_policy_versions=(
            artifact_policy_versions
            if artifact_policy_versions is not None
            else {"L0": "egr-164-v1"}
        ),
        parent_run_id=None,
    )
    paths = create_run_store(run_dir, manifest)
    EventStore(paths).append(
        "run_created",
        {"run_manifest_id": manifest.run_manifest_id},
        occurred_at=NOW,
    )
    return run_dir


def _append_rejected_attempts(run_dir: Path, count: int) -> tuple[str, ...]:
    from harness.re_v2.run_store import ReV2Paths

    events = EventStore(ReV2Paths.for_run(run_dir))
    work_item_ids: list[str] = []
    for index in range(count):
        work_item_id = content_digest(f"attempt-work-{index}".encode())
        work_item_ids.append(work_item_id)
        dispatch_id = f"dispatch-attempt-{index}"
        candidate_id = f"candidate-attempt-{index}"
        events.append(
            "dispatch_leased",
            {"dispatch_id": dispatch_id, "work_item_id": work_item_id},
            occurred_at="2026-08-14T12:00:01Z",
        )
        events.append(
            "dispatch_started",
            {
                "attempt_index": 1,
                "attempt_kind": "initial_generation",
                "dispatch_id": dispatch_id,
                "work_item_id": work_item_id,
            },
            occurred_at="2026-08-14T12:00:01Z",
        )
        events.append(
            "dispatch_observed",
            {
                "dispatch_id": dispatch_id,
                "observation": {
                    "started_at": "2026-08-14T12:00:01Z",
                    "ended_at": "2026-08-14T12:00:02Z",
                    "duration_ms": 1_000,
                    "exit_code": 0,
                    "timed_out": False,
                    "output_truncated": False,
                    "result_contract_valid": True,
                    "token_usage": 5,
                    "provider_name": "deterministic-inventory",
                    "model_name": "none",
                    "stderr_digest": None,
                },
                "work_item_id": work_item_id,
            },
            occurred_at="2026-08-14T12:00:02Z",
        )
        events.append(
            "candidate_persisted",
            {
                "candidate_id": candidate_id,
                "dispatch_id": dispatch_id,
                "work_item_id": work_item_id,
            },
            occurred_at="2026-08-14T12:00:02Z",
        )
        events.append(
            "candidate_rejected",
            {
                "candidate_id": candidate_id,
                "certification_id": content_digest(
                    f"attempt-certification-{index}".encode()
                ),
                "reason": "fixture rejection",
                "work_item_id": work_item_id,
            },
            occurred_at="2026-08-14T12:00:02Z",
        )
    return tuple(work_item_ids)


def _record_unmatched_l0_artifact(run_dir: Path, artifact_kind: str) -> None:
    from harness.re_v2.ledger import Ledger, ObjectStore
    from harness.re_v2.model import (
        ArtifactKey,
        ArtifactReceipt,
        CertificationKey,
        CertificationReceipt,
        WorkItem,
    )
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    manifest = load_run_manifest(run_dir)
    paths = ReV2Paths.for_run(run_dir)
    objects = ObjectStore(paths.objects)
    artifact_hash = objects.put_blob(b"unmatched accepted artifact")
    output_key = ArtifactKey(
        source_snapshot_id=manifest.source_snapshot_id,
        partition_manifest_id=manifest.partition_manifest_id,
        artifact_kind=artifact_kind,
        layer="L0",
        producer_protocol_version="re-v2-l0-v1",
        layer_policy_hash=content_digest(b"incompatible-layer-policy"),
        dependency_hashes=(),
    )
    work_item = WorkItem(
        template_id="unmatched-l0-template",
        goal_id="inventory",
        output_key=output_key,
        required_artifact_hashes=(),
        producer_id="unmatched-l0-producer",
        producer_protocol_version="re-v2-l0-v1",
        verifier_id="deterministic-inventory-verifier",
        verifier_version="v1",
        result_contract_id="deterministic-inventory-v1",
        max_provider_attempts=1,
        max_generation_attempts=1,
        max_semantic_rounds=0,
        max_result_contract_retries=0,
    )
    certification = CertificationReceipt(
        certification_key=CertificationKey(
            artifact_hash=artifact_hash,
            verifier_id="deterministic-inventory-verifier",
            verifier_version="v1",
            source_snapshot_id=manifest.source_snapshot_id,
            audit_epoch_id=None,
        ),
        candidate_id="unmatched-l0-candidate",
        work_item_id=work_item.work_item_id,
        verdict="accepted",
        normalized_diagnostics=(),
        evidence_references=(),
        scope_verified=True,
        certified_at=NOW,
    )
    artifact = ArtifactReceipt(
        artifact_key=output_key,
        artifact_hash=artifact_hash,
        certification_id=certification.identity,
        candidate_id=certification.candidate_id,
        work_item_id=work_item.work_item_id,
        accepted_at="2026-08-14T12:00:01Z",
    )
    ledger = Ledger(
        paths,
        objects,
        {"deterministic-inventory-verifier": "v1"},
    )
    ledger.record_certification(certification, work_item)
    ledger.record_artifact(artifact)


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
    assert data["layers"] == {
        "L0": {
            "accepted_artifacts": 0,
            "required_artifacts": 2,
            "status": "pending",
        }
    }
    assert "L0=pending (0/2 accepted)" in human
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


@pytest.mark.unit
@pytest.mark.parametrize("as_json", (False, True), ids=("human", "json"))
@pytest.mark.parametrize(
    ("requested_goals", "artifact_policies", "expected"),
    (
        (("future-goal",), {"L0": "egr-164-v1"}, "unsupported pinned requested goals"),
        (("inventory",), {"L0": "future-policy"}, "unsupported pinned artifact policies"),
    ),
)
def test_v2_status_fails_closed_for_unsupported_goal_or_artifact_policy(
    tmp_path: Path,
    as_json: bool,
    requested_goals: tuple[str, ...],
    artifact_policies: dict[str, str],
    expected: str,
) -> None:
    from harness.re_v2.status import ReV2StatusError, render_v2_status

    run_dir = _created_run(
        tmp_path,
        suffix="unsupported-status-pin",
        requested_goals=requested_goals,
        artifact_policy_versions=artifact_policies,
    )

    with pytest.raises(ReV2StatusError, match=expected):
        render_v2_status(run_dir, as_json=as_json)


@pytest.mark.unit
@pytest.mark.parametrize("attempt_count", (0, 1, 2))
def test_v2_status_represents_attempt_limits_per_work_item(
    tmp_path: Path,
    attempt_count: int,
) -> None:
    from harness.re_v2.status import render_v2_status

    run_dir = _created_run(tmp_path, suffix=f"attempts-{attempt_count}")
    work_item_ids = _append_rejected_attempts(run_dir, attempt_count)

    data = json.loads(render_v2_status(run_dir, as_json=True))
    human = render_v2_status(run_dir)

    expected_by_work_item = {
        work_item_id: {"authorized": 1, "remaining": 0, "used": 1}
        for work_item_id in work_item_ids
    }
    assert data["budgets"]["provider_attempts"] == {
        "aggregate_used": attempt_count,
        "authorized_per_work_item": 1,
        "by_work_item": expected_by_work_item,
    }
    assert data["budgets"]["generation_attempts"] == {
        "aggregate_used": attempt_count,
        "authorized_per_work_item": 1,
        "by_work_item": expected_by_work_item,
    }
    assert data["budgets"]["semantic_rounds"] == {
        "aggregate_used": 0,
        "authorized_per_work_item": 2,
        "by_work_item": {},
    }
    assert data["budgets"]["result_contract_retries"] == {
        "aggregate_used": 0,
        "authorized_per_work_item": 3,
        "by_work_item": {},
    }
    assert (
        f"aggregate used={attempt_count}; authorized per work item=1"
        in human
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "artifact_kind",
    ("unrelated-inventory", "source-inventory"),
    ids=("unrelated", "incompatible"),
)
def test_v2_layer_completion_counts_only_exact_graph_certifications(
    tmp_path: Path,
    artifact_kind: str,
) -> None:
    from harness.re_v2.status import render_v2_status

    run_dir = _created_run(tmp_path, suffix=f"layer-{artifact_kind}")
    _record_unmatched_l0_artifact(run_dir, artifact_kind)

    data = json.loads(render_v2_status(run_dir, as_json=True))

    assert data["artifact_counts"]["certified"] == 1
    assert data["layers"] == {
        "L0": {
            "accepted_artifacts": 0,
            "required_artifacts": 2,
            "status": "pending",
        }
    }
