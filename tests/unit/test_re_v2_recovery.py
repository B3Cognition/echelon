from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

import pytest

import harness.re_v2.recovery as recovery_module
from harness.re_v2.candidates import CandidateStore, ProcessIdentity
from harness.re_v2.canonical import content_digest
from harness.re_v2.events import EventStore
from harness.re_v2.ledger import (
    CertificationDecision,
    Ledger,
    ObjectStore,
)
from harness.re_v2.model import (
    ArtifactKey,
    ArtifactReceipt,
    BudgetPolicy,
    CertificationKey,
    CertificationReceipt,
    ExecutionObservation,
    RunManifest,
    WorkItem,
    WorkTemplate,
)
from harness.re_v2.planner import validate_work_graph
from harness.re_v2.recovery import (
    ProcessState,
    ReV2RecoveryError,
    ReV2RunContext,
    next_dispatch_attempt,
    recover_run,
)
from harness.re_v2.run_store import create_run_store
from harness.re_v2.snapshot import capture_source_snapshot


NOW = "2026-08-14T12:00:00Z"
OBSERVED = "2026-08-14T12:00:01Z"
PERSISTED = "2026-08-14T12:00:02Z"
CERTIFIED = "2026-08-14T12:00:03Z"
PROCESS_START = "linux:fixture-start"
POLICY_VERSION = "egr-164-v1"


@dataclass
class FixtureCertifier:
    objects: ObjectStore
    calls: int = 0
    verifier_id: str = "fixture-verifier"
    verifier_version: str = "v1"

    def certify(
        self, candidate: object, work_item: WorkItem
    ) -> CertificationDecision:
        self.calls += 1
        candidate_id = getattr(candidate, "candidate_id")
        payload_path = getattr(candidate, "payload_path")
        artifact_hash = self.objects.put_tree(payload_path)
        certification = CertificationReceipt(
            certification_key=CertificationKey(
                artifact_hash=artifact_hash,
                verifier_id=self.verifier_id,
                verifier_version=self.verifier_version,
                source_snapshot_id=work_item.output_key.source_snapshot_id,
                audit_epoch_id=None,
            ),
            candidate_id=candidate_id,
            work_item_id=work_item.work_item_id,
            verdict="accepted",
            normalized_diagnostics=(),
            evidence_references=(),
            scope_verified=True,
            certified_at=CERTIFIED,
        )
        artifact = ArtifactReceipt(
            artifact_key=work_item.output_key,
            artifact_hash=artifact_hash,
            certification_id=certification.identity,
            candidate_id=candidate_id,
            work_item_id=work_item.work_item_id,
            accepted_at=CERTIFIED,
        )
        return CertificationDecision(certification, artifact)


class RecordingInspector:
    def __init__(self, states: dict[int, ProcessState]) -> None:
        self.states = states
        self.calls: list[ProcessIdentity] = []

    def inspect(self, identity: ProcessIdentity) -> ProcessState:
        self.calls.append(identity)
        return self.states[identity.pid]


def _template(*, layer: str = "L0", protocol: str = "v1") -> WorkTemplate:
    return WorkTemplate(
        goal_id="inventory",
        artifact_kind="fixture-inventory",
        layer=layer,
        producer_id="fixture-producer",
        producer_protocol_version=protocol,
        layer_policy_hash=content_digest(
            {
                "artifact_kind": "fixture-inventory",
                "policy_version": POLICY_VERSION,
            }
        ),
        required_template_ids=(),
        verifier_id="fixture-verifier",
        verifier_version="v1",
        result_contract_id="fixture-result-v1",
        max_provider_attempts=3,
        max_generation_attempts=3,
        max_semantic_rounds=1,
        max_result_contract_retries=2,
    )


def _work_item(snapshot_id: str, partition_id: str) -> WorkItem:
    template = _template()
    output_key = ArtifactKey(
        source_snapshot_id=snapshot_id,
        partition_manifest_id=partition_id,
        artifact_kind=template.artifact_kind,
        layer=template.layer,
        producer_protocol_version=template.producer_protocol_version,
        layer_policy_hash=template.layer_policy_hash,
        dependency_hashes=(),
    )
    return WorkItem(
        template_id=template.template_id,
        goal_id=template.goal_id,
        output_key=output_key,
        required_artifact_hashes=(),
        producer_id=template.producer_id,
        producer_protocol_version=template.producer_protocol_version,
        verifier_id=template.verifier_id,
        verifier_version=template.verifier_version,
        result_contract_id=template.result_contract_id,
        max_provider_attempts=template.max_provider_attempts,
        max_generation_attempts=template.max_generation_attempts,
        max_semantic_rounds=template.max_semantic_rounds,
        max_result_contract_retries=template.max_result_contract_retries,
    )


def _context(tmp_path: Path) -> ReV2RunContext:
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
    snapshot = capture_source_snapshot(
        source, tmp_path / "snapshots", exclusions=()
    )
    partition_id = content_digest(b"fixture-partitions")
    run_dir = tmp_path / "runs" / "re-fixture"
    manifest = RunManifest(
        schema_version=1,
        engine="re-v2",
        engine_protocol_version="2.0",
        run_id=run_dir.name,
        created_at=NOW,
        source_snapshot_id=snapshot.snapshot_id,
        source_snapshot_kind=snapshot.kind,
        partition_manifest_id=partition_id,
        requested_goals=("inventory",),
        initial_budget_policy=BudgetPolicy(
            token_limit=100,
            active_ms_limit=100_000,
            provider_attempt_limit=5,
            artifact_generation_attempt_limit=5,
            semantic_repair_round_limit=2,
            result_contract_retry_limit=2,
        ),
        provider_contract={"provider": "fixture"},
        artifact_policy_versions={"L0": POLICY_VERSION},
        parent_run_id=None,
    )
    paths = create_run_store(run_dir, manifest)
    objects = ObjectStore(paths.objects)
    ledger = Ledger(
        paths,
        objects,
        supported_verifiers={"fixture-verifier": "v1"},
    )
    candidates = CandidateStore(
        paths,
        process_probe=lambda pid: PROCESS_START if pid in {1234, 5678} else None,
        clock=lambda: PERSISTED,
    )
    graph = validate_work_graph(
        (_template(),),
        requested_goals=manifest.requested_goals,
        source_snapshot_id=snapshot.snapshot_id,
        partition_manifest_id=partition_id,
    )
    return ReV2RunContext(
        paths=paths,
        snapshot=snapshot,
        graph=graph,
        event_store=EventStore(paths),
        object_store=objects,
        ledger=ledger,
        candidate_store=candidates,
        certifier=FixtureCertifier(objects),
    )


def _identity(pid: int = 1234) -> ProcessIdentity:
    return ProcessIdentity(
        pid=pid,
        process_start_identity=PROCESS_START,
        command_hash=content_digest(f"fixture-command-{pid}".encode()),
        provider_identity=content_digest(b"fixture-provider"),
        started_at=NOW,
    )


def _observation(*, result_contract_valid: bool = False) -> ExecutionObservation:
    return ExecutionObservation(
        started_at=NOW,
        ended_at=OBSERVED,
        duration_ms=1_000,
        exit_code=None,
        timed_out=True,
        output_truncated=False,
        result_contract_valid=result_contract_valid,
        token_usage=None,
        provider_name="fixture",
        model_name="fixture-model",
        stderr_digest=None,
    )


def _start_run(context: ReV2RunContext) -> None:
    manifest = context.manifest
    context.event_store.append(
        "run_created",
        {"run_manifest_id": manifest.run_manifest_id},
        occurred_at=NOW,
    )


def _persist_orphan_candidate(
    context: ReV2RunContext,
) -> tuple[WorkItem, object]:
    _start_run(context)
    item = _work_item(
        context.snapshot.snapshot_id,
        context.manifest.partition_manifest_id,
    )
    lease = context.candidate_store.begin(
        item,
        _identity(),
        dispatch_id="dispatch-fixture",
        leased_at=NOW,
    )
    context.event_store.append(
        "dispatch_leased",
        {"dispatch_id": lease.dispatch_id, "work_item_id": item.work_item_id},
        occurred_at=NOW,
    )
    context.event_store.append(
        "dispatch_started",
        {
            "attempt_index": 1,
            "attempt_kind": "initial_generation",
            "dispatch_id": lease.dispatch_id,
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    observation = _observation()
    context.event_store.append(
        "dispatch_observed",
        {
            "dispatch_id": lease.dispatch_id,
            "observation": observation.to_json_dict(),
            "work_item_id": item.work_item_id,
        },
        occurred_at=OBSERVED,
    )
    output = context.paths.root.parent.parent.parent / "provider-output"
    output.mkdir()
    (output / "artifact.md").write_text(
        "complete bytes despite missing result object\n", encoding="utf-8"
    )
    return item, context.candidate_store.persist(lease, output, observation)


def test_recovery_certifies_orphan_candidate_before_redispatch(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _item, candidate = _persist_orphan_candidate(context)

    result = recover_run(
        context,
        process_inspector=RecordingInspector({}),
        clock=lambda: CERTIFIED,
    )

    assert result.reconciled_candidate_ids == (candidate.candidate_id,)
    assert [event.type for event in result.events][-4:] == [
        "candidate_persisted",
        "candidate_certified",
        "artifact_accepted",
        "checkpoint_recorded",
    ]
    assert len(result.ledger.accepted_artifacts) == 1


def test_recovery_is_idempotent_after_candidate_checkpoint(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _persist_orphan_candidate(context)

    recover_run(context, process_inspector=RecordingInspector({}), clock=lambda: CERTIFIED)
    first = context.event_store.replay()
    recover_run(context, process_inspector=RecordingInspector({}), clock=lambda: CERTIFIED)
    second = context.event_store.replay()

    assert second == first
    assert [event.type for event in second].count("candidate_certified") == 1
    assert [event.type for event in second].count("artifact_accepted") == 1
    assert [event.type for event in second].count("checkpoint_recorded") == 1
    assert context.certifier.calls == 1


def test_recovery_appends_missing_event_suffix_for_ledger_ahead_candidate(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    item, candidate = _persist_orphan_candidate(context)
    decision = context.certifier.certify(candidate, item)
    context.ledger.record_certification(decision.certification_receipt, item)
    assert decision.artifact_receipt is not None
    context.ledger.record_artifact(decision.artifact_receipt)

    result = recover_run(
        context,
        process_inspector=RecordingInspector({}),
        clock=lambda: CERTIFIED,
    )

    assert [event.type for event in result.events][-4:] == [
        "candidate_persisted",
        "candidate_certified",
        "artifact_accepted",
        "checkpoint_recorded",
    ]
    assert context.certifier.calls == 1


def test_recovery_rejects_ledger_work_item_different_from_exact_candidate(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    item, candidate = _persist_orphan_candidate(context)
    other_item = replace(item, goal_id="other-goal")
    decision = context.certifier.certify(candidate, other_item)
    context.ledger.record_certification(
        decision.certification_receipt, other_item
    )
    assert decision.artifact_receipt is not None
    context.ledger.record_artifact(decision.artifact_receipt)

    with pytest.raises(ReV2RecoveryError, match="WorkItem"):
        recover_run(
            context,
            process_inspector=RecordingInspector({}),
            clock=lambda: CERTIFIED,
        )


@pytest.mark.parametrize(
    ("state", "message"),
    [
        (ProcessState.SAME_PROCESS_LIVE, "still running"),
        (ProcessState.PID_REUSED_OR_AMBIGUOUS, "ambiguous"),
    ],
)
def test_live_or_ambiguous_lease_fails_closed(
    tmp_path: Path, state: ProcessState, message: str
) -> None:
    context = _context(tmp_path)
    _start_run(context)
    item = _work_item(
        context.snapshot.snapshot_id,
        context.manifest.partition_manifest_id,
    )
    lease = context.candidate_store.begin(
        item, _identity(), dispatch_id="dispatch-live", leased_at=NOW
    )
    context.event_store.append(
        "dispatch_leased",
        {"dispatch_id": lease.dispatch_id, "work_item_id": item.work_item_id},
        occurred_at=NOW,
    )
    context.event_store.append(
        "dispatch_started",
        {
            "attempt_index": 1,
            "attempt_kind": "initial_generation",
            "dispatch_id": lease.dispatch_id,
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )

    with pytest.raises(ReV2RecoveryError, match=message):
        recover_run(
            context,
            process_inspector=RecordingInspector({1234: state}),
            clock=lambda: CERTIFIED,
        )

    assert [event.type for event in context.event_store.replay()][-1] == (
        "dispatch_started"
    )


def test_recovery_inspects_every_outstanding_lease_before_failing(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _start_run(context)
    item = _work_item(
        context.snapshot.snapshot_id,
        context.manifest.partition_manifest_id,
    )
    context.candidate_store.begin(
        item, _identity(1234), dispatch_id="dispatch-one", leased_at=NOW
    )
    context.candidate_store.begin(
        item, _identity(5678), dispatch_id="dispatch-two", leased_at=NOW
    )
    inspector = RecordingInspector(
        {
            1234: ProcessState.DEAD,
            5678: ProcessState.PID_REUSED_OR_AMBIGUOUS,
        }
    )

    with pytest.raises(ReV2RecoveryError, match="ambiguous"):
        recover_run(context, process_inspector=inspector, clock=lambda: CERTIFIED)

    assert [identity.pid for identity in inspector.calls] == [1234, 5678]


def test_recovery_rejects_a_lease_swapped_to_a_symlink_during_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    _start_run(context)
    item = _work_item(
        context.snapshot.snapshot_id,
        context.manifest.partition_manifest_id,
    )
    lease = context.candidate_store.begin(
        item, _identity(), dispatch_id="dispatch-raced", leased_at=NOW
    )
    lease_path = context.paths.candidates / ".leases" / f"{lease.dispatch_id}.json"
    outside = tmp_path / "outside-lease.json"
    outside.write_bytes(lease_path.read_bytes())
    real_open = recovery_module.os.open
    swapped = False

    def racing_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == lease_path.name and dir_fd is not None and not swapped:
            swapped = True
            lease_path.unlink()
            lease_path.symlink_to(outside)
        if dir_fd is None:
            return real_open(path, flags, mode)  # type: ignore[arg-type]
        return real_open(path, flags, mode, dir_fd=dir_fd)  # type: ignore[arg-type]

    monkeypatch.setattr(recovery_module.os, "open", racing_open)

    with pytest.raises(ReV2RecoveryError, match="lease"):
        recover_run(
            context,
            process_inspector=RecordingInspector(
                {1234: ProcessState.DEAD}
            ),
            clock=lambda: CERTIFIED,
        )

    assert swapped is True


def test_dead_started_lease_is_closed_with_an_invalid_observation(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _start_run(context)
    item = _work_item(
        context.snapshot.snapshot_id,
        context.manifest.partition_manifest_id,
    )
    lease = context.candidate_store.begin(
        item, _identity(), dispatch_id="dispatch-dead", leased_at=NOW
    )
    context.event_store.append(
        "dispatch_leased",
        {"dispatch_id": lease.dispatch_id, "work_item_id": item.work_item_id},
        occurred_at=NOW,
    )
    context.event_store.append(
        "dispatch_started",
        {
            "attempt_index": 1,
            "attempt_kind": "initial_generation",
            "dispatch_id": lease.dispatch_id,
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )

    result = recover_run(
        context,
        process_inspector=RecordingInspector({1234: ProcessState.DEAD}),
        clock=lambda: OBSERVED,
    )

    observed = result.events[-1]
    assert observed.type == "dispatch_observed"
    assert observed.payload["observation"]["result_contract_valid"] is False
    assert observed.payload["observation"]["token_usage"] is None


def test_paused_recovery_retires_eventless_dead_lease_without_attempt_charge(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _start_run(context)
    item = _work_item(
        context.snapshot.snapshot_id,
        context.manifest.partition_manifest_id,
    )
    lease = context.candidate_store.begin(
        item,
        _identity(),
        dispatch_id="dispatch-eventless-dead",
        leased_at=NOW,
    )
    context.event_store.append(
        "run_paused",
        {"reason": "operator hold", "reason_code": "operator_hold"},
        occurred_at=NOW,
    )

    first = recover_run(
        context,
        process_inspector=RecordingInspector({1234: ProcessState.DEAD}),
        clock=lambda: CERTIFIED,
    )
    first_events = context.event_store.replay()
    second = recover_run(
        context,
        process_inspector=RecordingInspector({1234: ProcessState.DEAD}),
        clock=lambda: CERTIFIED,
    )

    retired = [
        event
        for event in first.events
        if event.type == "dispatch_lease_retired"
    ]
    assert len(retired) == 1
    assert retired[0].payload == {
        "dispatch_id": lease.dispatch_id,
        "lease_id": lease.lease_id,
        "reason": "dead process without a committed candidate",
        "work_item_id": item.work_item_id,
    }
    assert not any(event.type == "dispatch_started" for event in first.events)
    assert second.events == first_events


def test_recovery_rejects_retirement_event_for_a_different_work_item(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _start_run(context)
    item = _work_item(
        context.snapshot.snapshot_id,
        context.manifest.partition_manifest_id,
    )
    lease = context.candidate_store.begin(
        item,
        _identity(),
        dispatch_id="dispatch-forged-retirement",
        leased_at=NOW,
    )
    context.event_store.append(
        "dispatch_lease_retired",
        {
            "dispatch_id": lease.dispatch_id,
            "lease_id": lease.lease_id,
            "reason": "forged retirement",
            "work_item_id": content_digest(b"different-work-item"),
        },
        occurred_at=NOW,
    )

    with pytest.raises(ReV2RecoveryError, match="retirement|work item"):
        recover_run(
            context,
            process_inspector=RecordingInspector({}),
            clock=lambda: CERTIFIED,
        )


def test_recovery_rejects_retirement_with_an_altered_lease_id(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _start_run(context)
    item = _work_item(
        context.snapshot.snapshot_id,
        context.manifest.partition_manifest_id,
    )
    lease = context.candidate_store.begin(
        item,
        _identity(),
        dispatch_id="dispatch-altered-retirement",
        leased_at=NOW,
    )
    context.event_store.append(
        "dispatch_lease_retired",
        {
            "dispatch_id": lease.dispatch_id,
            "lease_id": content_digest(b"altered-lease"),
            "reason": "forged retirement",
            "work_item_id": lease.work_item_id,
        },
        occurred_at=NOW,
    )

    with pytest.raises(ReV2RecoveryError, match="retirement|lease"):
        recover_run(
            context,
            process_inspector=RecordingInspector({}),
            clock=lambda: CERTIFIED,
        )


def test_recovery_inspects_and_rejects_an_exact_retired_live_lease(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _start_run(context)
    item = _work_item(
        context.snapshot.snapshot_id,
        context.manifest.partition_manifest_id,
    )
    lease = context.candidate_store.begin(
        item,
        _identity(),
        dispatch_id="dispatch-retired-live",
        leased_at=NOW,
    )
    context.event_store.append(
        "dispatch_lease_retired",
        {
            "dispatch_id": lease.dispatch_id,
            "lease_id": lease.lease_id,
            "reason": "claimed dead",
            "work_item_id": lease.work_item_id,
        },
        occurred_at=NOW,
    )
    inspector = RecordingInspector({1234: ProcessState.SAME_PROCESS_LIVE})

    with pytest.raises(ReV2RecoveryError, match="still running"):
        recover_run(context, process_inspector=inspector, clock=lambda: CERTIFIED)

    assert inspector.calls == [lease.process_identity]


def test_exact_dead_retirement_remains_idempotent_and_inspected(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _start_run(context)
    item = _work_item(
        context.snapshot.snapshot_id,
        context.manifest.partition_manifest_id,
    )
    lease = context.candidate_store.begin(
        item,
        _identity(),
        dispatch_id="dispatch-retired-dead",
        leased_at=NOW,
    )
    context.event_store.append(
        "dispatch_lease_retired",
        {
            "dispatch_id": lease.dispatch_id,
            "lease_id": lease.lease_id,
            "reason": "dead process without a committed candidate",
            "work_item_id": lease.work_item_id,
        },
        occurred_at=NOW,
    )
    first_inspector = RecordingInspector({1234: ProcessState.DEAD})

    first = recover_run(
        context,
        process_inspector=first_inspector,
        clock=lambda: CERTIFIED,
    )
    first_events = first.events
    second_inspector = RecordingInspector({1234: ProcessState.DEAD})
    second = recover_run(
        context,
        process_inspector=second_inspector,
        clock=lambda: CERTIFIED,
    )

    assert first_inspector.calls == [lease.process_identity]
    assert second_inspector.calls == [lease.process_identity]
    assert second.events == first_events


def test_recovery_reconstructs_eventless_committed_candidate_lifecycle(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _start_run(context)
    item = _work_item(
        context.snapshot.snapshot_id,
        context.manifest.partition_manifest_id,
    )
    lease = context.candidate_store.begin(
        item,
        _identity(),
        dispatch_id="dispatch-eventless-candidate",
        leased_at=NOW,
    )
    output = tmp_path / "eventless-candidate-output"
    output.mkdir()
    (output / "artifact.md").write_text("durable bytes\n", encoding="utf-8")
    candidate = context.candidate_store.persist(
        lease,
        output,
        _observation(result_contract_valid=True),
    )

    result = recover_run(
        context,
        process_inspector=RecordingInspector({1234: ProcessState.DEAD}),
        clock=lambda: CERTIFIED,
    )

    lifecycle = [
        event.type
        for event in result.events
        if event.type != "run_created"
    ]
    assert lifecycle == [
        "dispatch_leased",
        "dispatch_started",
        "dispatch_observed",
        "candidate_persisted",
        "candidate_certified",
        "artifact_accepted",
        "checkpoint_recorded",
    ]
    assert result.reconciled_candidate_ids == (candidate.candidate_id,)
    assert context.certifier.calls == 1


def test_paused_recovery_closes_committed_candidate_before_return(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _start_run(context)
    item = _work_item(
        context.snapshot.snapshot_id,
        context.manifest.partition_manifest_id,
    )
    lease = context.candidate_store.begin(
        item,
        _identity(),
        dispatch_id="dispatch-paused-candidate",
        leased_at=NOW,
    )
    context.event_store.append(
        "dispatch_leased",
        {"dispatch_id": lease.dispatch_id, "work_item_id": item.work_item_id},
        occurred_at=NOW,
    )
    context.event_store.append(
        "dispatch_started",
        {
            "attempt_index": 1,
            "attempt_kind": "initial_generation",
            "dispatch_id": lease.dispatch_id,
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    observation = _observation(result_contract_valid=True)
    context.event_store.append(
        "dispatch_observed",
        {
            "dispatch_id": lease.dispatch_id,
            "observation": observation.to_json_dict(),
            "work_item_id": item.work_item_id,
        },
        occurred_at=OBSERVED,
    )
    output = tmp_path / "paused-candidate-output"
    output.mkdir()
    (output / "artifact.md").write_text("durable bytes\n", encoding="utf-8")
    context.candidate_store.persist(
        lease,
        output,
        observation,
    )
    context.event_store.append(
        "run_paused",
        {"reason": "operator hold", "reason_code": "operator_hold"},
        occurred_at=NOW,
    )

    result = recover_run(
        context,
        process_inspector=RecordingInspector({1234: ProcessState.DEAD}),
        clock=lambda: CERTIFIED,
    )

    assert result.projection["state"] == "paused"
    assert [event.type for event in result.events][-4:] == [
        "candidate_persisted",
        "candidate_certified",
        "artifact_accepted",
        "checkpoint_recorded",
    ]


def test_recovery_rebuilds_projection_without_reading_existing_projection(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _start_run(context)
    context.paths.projection.write_text("not authoritative", encoding="utf-8")

    result = recover_run(
        context,
        process_inspector=RecordingInspector({}),
        clock=lambda: CERTIFIED,
    )

    assert json.loads(context.paths.projection.read_text(encoding="utf-8")) == (
        result.projection
    )


def test_recovery_validates_snapshot_before_process_inspection(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _start_run(context)
    inspector = RecordingInspector({})
    mismatched = replace(
        context,
        snapshot=replace(
            context.snapshot,
            snapshot_id=content_digest(b"different-snapshot"),
        ),
    )

    with pytest.raises(ReV2RecoveryError, match="snapshot"):
        recover_run(mismatched, process_inspector=inspector, clock=lambda: CERTIFIED)

    assert inspector.calls == []


def test_recovery_binds_policy_hash_independently_of_producer_protocol(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    graph = validate_work_graph(
        (_template(protocol="v2"),),
        requested_goals=context.manifest.requested_goals,
        source_snapshot_id=context.snapshot.snapshot_id,
        partition_manifest_id=context.manifest.partition_manifest_id,
    )

    result = recover_run(
        replace(context, graph=graph),
        process_inspector=RecordingInspector({}),
        clock=lambda: CERTIFIED,
    )

    assert result.manifest.artifact_policy_versions["L0"] == POLICY_VERSION


def test_recovery_rejects_a_graph_layer_without_a_manifest_policy(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    graph = validate_work_graph(
        (_template(layer="L1"),),
        requested_goals=context.manifest.requested_goals,
        source_snapshot_id=context.snapshot.snapshot_id,
        partition_manifest_id=context.manifest.partition_manifest_id,
    )

    with pytest.raises(ReV2RecoveryError, match="no manifest artifact policy"):
        recover_run(
            replace(context, graph=graph),
            process_inspector=RecordingInspector({}),
            clock=lambda: CERTIFIED,
        )


def test_recovery_rejects_a_graph_policy_hash_mismatch(tmp_path: Path) -> None:
    context = _context(tmp_path)
    mismatched = replace(
        _template(),
        layer_policy_hash=content_digest(
            {
                "artifact_kind": "fixture-inventory",
                "policy_version": "different-policy-v1",
            }
        ),
    )
    graph = validate_work_graph(
        (mismatched,),
        requested_goals=context.manifest.requested_goals,
        source_snapshot_id=context.snapshot.snapshot_id,
        partition_manifest_id=context.manifest.partition_manifest_id,
    )

    with pytest.raises(ReV2RecoveryError, match="policy hash"):
        recover_run(
            replace(context, graph=graph),
            process_inspector=RecordingInspector({}),
            clock=lambda: CERTIFIED,
        )


def test_recovery_rejects_an_object_store_outside_the_run_authority(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    outside = ObjectStore(tmp_path / "outside-objects")
    outside_ledger = Ledger(
        context.paths,
        outside,
        supported_verifiers={"fixture-verifier": "v1"},
    )
    mismatched = replace(
        context,
        object_store=outside,
        ledger=outside_ledger,
        certifier=FixtureCertifier(outside),
    )

    with pytest.raises(ReV2RecoveryError, match="run-local object"):
        recover_run(
            mismatched,
            process_inspector=RecordingInspector({}),
            clock=lambda: CERTIFIED,
        )


def test_recovery_rejects_a_handled_event_that_conflicts_with_ledger(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    item, candidate = _persist_orphan_candidate(context)
    decision = context.certifier.certify(candidate, item)
    context.ledger.record_certification(decision.certification_receipt, item)
    context.event_store.append(
        "candidate_persisted",
        {
            "candidate_id": candidate.candidate_id,
            "dispatch_id": candidate.dispatch_id,
            "work_item_id": candidate.work_item_id,
        },
        occurred_at=PERSISTED,
    )
    context.event_store.append(
        "candidate_rejected",
        {
            "candidate_id": candidate.candidate_id,
            "certification_id": content_digest(b"not-the-ledger-certification"),
            "reason": "forged outcome",
            "work_item_id": candidate.work_item_id,
        },
        occurred_at=CERTIFIED,
    )

    with pytest.raises(ReV2RecoveryError, match="matching ledger certification"):
        recover_run(
            context,
            process_inspector=RecordingInspector({}),
            clock=lambda: CERTIFIED,
        )


def test_recovery_cross_checks_candidate_observation_even_with_persisted_event(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _start_run(context)
    item = _work_item(
        context.snapshot.snapshot_id,
        context.manifest.partition_manifest_id,
    )
    lease = context.candidate_store.begin(
        item,
        _identity(),
        dispatch_id="dispatch-observation-mismatch",
        leased_at=NOW,
    )
    context.event_store.append(
        "dispatch_leased",
        {"dispatch_id": lease.dispatch_id, "work_item_id": item.work_item_id},
        occurred_at=NOW,
    )
    context.event_store.append(
        "dispatch_started",
        {
            "attempt_index": 1,
            "attempt_kind": "initial_generation",
            "dispatch_id": lease.dispatch_id,
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    candidate_observation = _observation(result_contract_valid=True)
    event_observation = replace(
        candidate_observation,
        model_name="different-model",
    )
    context.event_store.append(
        "dispatch_observed",
        {
            "dispatch_id": lease.dispatch_id,
            "observation": event_observation.to_json_dict(),
            "work_item_id": item.work_item_id,
        },
        occurred_at=OBSERVED,
    )
    output = tmp_path / "mismatched-observation-output"
    output.mkdir()
    (output / "artifact.md").write_text("candidate bytes\n", encoding="utf-8")
    candidate = context.candidate_store.persist(
        lease, output, candidate_observation
    )
    context.event_store.append(
        "candidate_persisted",
        {
            "candidate_id": candidate.candidate_id,
            "dispatch_id": candidate.dispatch_id,
            "work_item_id": candidate.work_item_id,
        },
        occurred_at=PERSISTED,
    )

    with pytest.raises(ReV2RecoveryError, match="observation"):
        recover_run(
            context,
            process_inspector=RecordingInspector({}),
            clock=lambda: CERTIFIED,
        )


def test_recovery_rejects_candidate_from_unpinned_observation_provider(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _start_run(context)
    item = _work_item(
        context.snapshot.snapshot_id,
        context.manifest.partition_manifest_id,
    )
    lease = context.candidate_store.begin(
        item,
        _identity(),
        dispatch_id="dispatch-wrong-provider",
        leased_at=NOW,
    )
    output = tmp_path / "wrong-provider-output"
    output.mkdir()
    (output / "artifact.md").write_text("candidate bytes\n", encoding="utf-8")
    context.candidate_store.persist(
        lease,
        output,
        replace(_observation(), provider_name="other-provider"),
    )

    with pytest.raises(ReV2RecoveryError, match="provider"):
        recover_run(
            context,
            process_inspector=RecordingInspector({1234: ProcessState.DEAD}),
            clock=lambda: CERTIFIED,
        )


def test_recovery_rejects_ledger_receipts_without_an_exact_candidate(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _start_run(context)
    item = _work_item(
        context.snapshot.snapshot_id,
        context.manifest.partition_manifest_id,
    )
    payload = tmp_path / "ledger-only-payload"
    payload.mkdir()
    (payload / "artifact.md").write_text("ledger only\n", encoding="utf-8")
    artifact_hash = context.object_store.put_tree(payload)
    certification = CertificationReceipt(
        certification_key=CertificationKey(
            artifact_hash=artifact_hash,
            verifier_id=item.verifier_id,
            verifier_version=item.verifier_version,
            source_snapshot_id=item.output_key.source_snapshot_id,
            audit_epoch_id=None,
        ),
        candidate_id="candidate-missing",
        work_item_id=item.work_item_id,
        verdict="accepted",
        normalized_diagnostics=(),
        evidence_references=(),
        scope_verified=True,
        certified_at=CERTIFIED,
    )
    artifact = ArtifactReceipt(
        artifact_key=item.output_key,
        artifact_hash=artifact_hash,
        certification_id=certification.identity,
        candidate_id=certification.candidate_id,
        work_item_id=item.work_item_id,
        accepted_at=CERTIFIED,
    )
    context.ledger.record_certification(certification, item)
    context.ledger.record_artifact(artifact)

    with pytest.raises(ReV2RecoveryError, match="candidate"):
        recover_run(
            context,
            process_inspector=RecordingInspector({}),
            clock=lambda: CERTIFIED,
        )


def test_attempt_selection_never_rediscovers_stale_repair_debt(
    tmp_path: Path,
) -> None:
    store = EventStore(tmp_path / "events.jsonl")
    first = _work_item(content_digest(b"source"), content_digest(b"partitions"))
    second = replace(first, goal_id="other-goal")
    store.append(
        "run_created",
        {"run_manifest_id": content_digest(b"manifest")},
        occurred_at=NOW,
    )

    def append_rejected(item: WorkItem, suffix: str) -> None:
        store.append(
            "dispatch_leased",
            {"dispatch_id": f"dispatch-{suffix}", "work_item_id": item.work_item_id},
            occurred_at=NOW,
        )
        store.append(
            "dispatch_started",
            {
                "attempt_index": 1,
                "attempt_kind": "initial_generation",
                "dispatch_id": f"dispatch-{suffix}",
                "work_item_id": item.work_item_id,
            },
            occurred_at=NOW,
        )
        observed = _observation(result_contract_valid=True)
        store.append(
            "dispatch_observed",
            {
                "dispatch_id": f"dispatch-{suffix}",
                "observation": observed.to_json_dict(),
                "work_item_id": item.work_item_id,
            },
            occurred_at=OBSERVED,
        )
        store.append(
            "candidate_persisted",
            {
                "candidate_id": f"candidate-{suffix}",
                "dispatch_id": f"dispatch-{suffix}",
                "work_item_id": item.work_item_id,
            },
            occurred_at=PERSISTED,
        )
        store.append(
            "candidate_rejected",
            {
                "candidate_id": f"candidate-{suffix}",
                "certification_id": content_digest(f"cert-{suffix}".encode()),
                "reason": "rejected",
                "work_item_id": item.work_item_id,
            },
            occurred_at=CERTIFIED,
        )

    append_rejected(first, "first")
    append_rejected(second, "second")

    with pytest.raises(ReV2RecoveryError, match="does not authorize|stale"):
        next_dispatch_attempt(store.replay(), first)
