from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from harness.re_v2.budget import authorize_resource_increase, evaluate_budget
from harness.re_v2.candidates import CandidateStore, DispatchLease, ProcessIdentity
from harness.re_v2.canonical import content_digest
from harness.re_v2.controller import (
    DeterministicInventoryExecutor,
    ReV2Controller,
    ReV2ControllerError,
    WorkExecutor,
)
from harness.re_v2.events import EventStore
from harness.re_v2.ledger import (
    CertificationDecision,
    Ledger,
    ObjectStore,
)
from harness.re_v2.model import (
    ArtifactReceipt,
    BudgetPolicy,
    CertificationKey,
    CertificationReceipt,
    ExecutionObservation,
    RunManifest,
    WorkItem,
    WorkTemplate,
)
from harness.re_v2.planner import plan_next, validate_work_graph
from harness.re_v2.recovery import ProcessState, ReV2RunContext
from harness.re_v2.run_store import create_run_store
from harness.re_v2.snapshot import capture_source_snapshot


NOW = "2026-08-14T12:00:00Z"
OBSERVED = "2026-08-14T12:00:01Z"
PERSISTED = "2026-08-14T12:00:02Z"
CERTIFIED = "2026-08-14T12:00:03Z"
PROCESS_START = "linux:fixture-start"


class DeadInspector:
    def inspect(self, _identity: ProcessIdentity) -> ProcessState:
        return ProcessState.DEAD


@dataclass
class AcceptingCertifier:
    objects: ObjectStore
    calls: int = 0
    verifier_id: str = "fixture-verifier"
    verifier_version: str = "v1"

    def certify(
        self, candidate: object, work_item: WorkItem
    ) -> CertificationDecision:
        self.calls += 1
        candidate_id = getattr(candidate, "candidate_id")
        artifact_hash = self.objects.put_tree(getattr(candidate, "payload_path"))
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


class FakeProviderExecutor(WorkExecutor):
    def __init__(
        self,
        root: Path,
        *,
        token_usage: int | None = None,
        timed_out: bool = False,
        result_contract_valid: bool = True,
        provider_name: str = "fixture",
    ) -> None:
        self.root = root
        self.token_usage = token_usage
        self.timed_out = timed_out
        self.result_contract_valid = result_contract_valid
        self.provider_name = provider_name
        self.calls: list[tuple[Path, WorkItem, DispatchLease]] = []

    def execute(
        self, snapshot_root: Path, work_item: WorkItem, lease: DispatchLease
    ) -> tuple[Path, ExecutionObservation]:
        self.calls.append((snapshot_root, work_item, lease))
        output = self.root / f"output-{lease.dispatch_id}"
        output.mkdir()
        (output / "artifact.md").write_text(
            f"candidate for {work_item.work_item_id}\n", encoding="utf-8"
        )
        return output, ExecutionObservation(
            started_at=NOW,
            ended_at=OBSERVED,
            duration_ms=1_000,
            exit_code=None if self.timed_out else 0,
            timed_out=self.timed_out,
            output_truncated=False,
            result_contract_valid=self.result_contract_valid,
            token_usage=self.token_usage,
            provider_name=self.provider_name,
            model_name="fixture-model",
            stderr_digest=None,
        )


def _template(
    kind: str,
    *,
    goal: str | None = None,
    layer: str = "L0",
    producer: str = "fixture-producer",
    dependencies: tuple[str, ...] = (),
) -> WorkTemplate:
    return WorkTemplate(
        goal_id=goal or kind,
        artifact_kind=kind,
        layer=layer,
        producer_id=producer,
        producer_protocol_version="v1",
        layer_policy_hash=content_digest(f"policy-{kind}".encode()),
        required_template_ids=dependencies,
        verifier_id="fixture-verifier",
        verifier_version="v1",
        result_contract_id="fixture-result-v1",
        max_provider_attempts=3,
        max_generation_attempts=3,
        max_semantic_rounds=1,
        max_result_contract_retries=2,
    )


def _context(
    tmp_path: Path,
    templates: tuple[WorkTemplate, ...],
    *,
    token_limit: int = 100,
    generation_attempt_limit: int = 5,
) -> ReV2RunContext:
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
    snapshot = capture_source_snapshot(
        source, tmp_path / "snapshots", exclusions=()
    )
    partition_id = content_digest(b"fixture-partitions")
    goals = tuple(sorted({template.goal_id for template in templates}))
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
        requested_goals=goals,
        initial_budget_policy=BudgetPolicy(
            token_limit=token_limit,
            active_ms_limit=100_000,
            provider_attempt_limit=5,
            artifact_generation_attempt_limit=generation_attempt_limit,
            semantic_repair_round_limit=2,
            result_contract_retry_limit=2,
        ),
        provider_contract={"provider": "fixture"},
        artifact_policy_versions={
            template.layer: template.producer_protocol_version
            for template in templates
        },
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
        process_probe=lambda pid: PROCESS_START if pid == 1234 else None,
        clock=lambda: PERSISTED,
    )
    graph = validate_work_graph(
        templates,
        requested_goals=goals,
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
        certifier=AcceptingCertifier(objects),
    )


def _identity_factory(
    item: WorkItem, attempt_kind: str, attempt_index: int, _now: str
) -> ProcessIdentity:
    return ProcessIdentity(
        pid=1234,
        process_start_identity=PROCESS_START,
        command_hash=content_digest(
            f"{item.work_item_id}:{attempt_kind}:{attempt_index}".encode()
        ),
        provider_identity=content_digest(item.producer_id.encode()),
        started_at=NOW,
    )


def _registry_key(template: WorkTemplate) -> tuple[str, str, str, str]:
    return (
        template.producer_id,
        template.producer_protocol_version,
        template.layer,
        template.result_contract_id,
    )


def _controller(
    context: ReV2RunContext,
    *,
    executor: WorkExecutor | None = None,
) -> ReV2Controller:
    registry = (
        None
        if executor is None
        else {
            _registry_key(template): executor
            for template in context.graph.templates
        }
    )
    return ReV2Controller(
        context,
        executor_registry=registry,
        process_inspector=DeadInspector(),
        process_identity_factory=_identity_factory,
        clock=lambda: NOW,
    )


def test_run_once_dispatches_at_most_one_ready_item(tmp_path: Path) -> None:
    first = _template("first")
    second = _template("second")
    context = _context(tmp_path, (first, second))
    executor = FakeProviderExecutor(tmp_path)

    result = _controller(context, executor=executor).run_once()

    assert result.status == "active"
    assert len(executor.calls) == 1
    assert [event.type for event in context.event_store.replay()].count(
        "dispatch_started"
    ) == 1


def test_transport_failure_bytes_are_certified_not_provider_result_text(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    executor = FakeProviderExecutor(
        tmp_path,
        timed_out=True,
        result_contract_valid=False,
    )

    result = _controller(context, executor=executor).run_until_stopped()

    assert result.status == "complete"
    assert len(context.candidate_store.discover()) == 1
    assert len(context.ledger.replay().accepted_artifacts) == 1
    assert context.candidate_store.discover()[0].observation.timed_out is True


def test_dispatch_lifecycle_events_use_explicit_attempt_and_checkpoint_order(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    executor = FakeProviderExecutor(tmp_path)

    _controller(context, executor=executor).run_until_stopped()

    events = context.event_store.replay()
    lifecycle = [
        event.type
        for event in events
        if event.type
        in {
            "dispatch_leased",
            "dispatch_started",
            "dispatch_observed",
            "candidate_persisted",
            "candidate_certified",
            "artifact_accepted",
            "checkpoint_recorded",
        }
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
    started = next(event for event in events if event.type == "dispatch_started")
    assert started.payload["attempt_kind"] == "initial_generation"
    assert started.payload["attempt_index"] == 1


def test_unregistered_producer_pauses_without_v1_or_executor_fallback(
    tmp_path: Path,
) -> None:
    context = _context(
        tmp_path,
        (_template("depth", layer="L2", producer="unregistered-provider"),),
    )

    result = _controller(context).run_once()

    assert result.status == "paused"
    assert result.reason_code == "producer_not_registered"
    events = context.event_store.replay()
    assert [event.type for event in events].count("dispatch_started") == 0
    assert events[-1].type == "run_paused"
    assert events[-1].payload["reason_code"] == "producer_not_registered"


def test_executor_registry_requires_the_exact_work_protocol_tuple(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    executor = FakeProviderExecutor(tmp_path)
    wrong_key = (
        "fixture-producer",
        "wrong-protocol",
        "L0",
        "fixture-result-v1",
    )
    controller = ReV2Controller(
        context,
        executor_registry={wrong_key: executor},
        process_inspector=DeadInspector(),
        process_identity_factory=_identity_factory,
        clock=lambda: NOW,
    )

    result = controller.run_once()

    assert result.status == "paused"
    assert result.reason_code == "producer_not_registered"
    assert not any(
        event.type == "dispatch_leased"
        for event in context.event_store.replay()
    )


def test_observation_provider_must_match_the_manifest_before_persistence(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    executor = FakeProviderExecutor(tmp_path, provider_name="other-provider")

    with pytest.raises(ReV2ControllerError, match="provider"):
        _controller(context, executor=executor).run_once()

    assert context.candidate_store.discover() == ()


def test_resource_exhaustion_pauses_and_can_resume_after_authorization(
    tmp_path: Path,
) -> None:
    first = _template("first", goal="inventory")
    second = _template(
        "second",
        goal="inventory",
        dependencies=(first.template_id,),
    )
    context = _context(tmp_path, (first, second), token_limit=5)
    first_executor = FakeProviderExecutor(tmp_path, token_usage=5)
    controller = _controller(context, executor=first_executor)

    paused = controller.run_until_stopped()

    assert paused.status == "paused"
    assert paused.reason_code == "tokens_exhausted"
    assert not any(
        event.type == "run_completed" for event in context.event_store.replay()
    )

    history = context.event_store.replay()
    authorization = authorize_resource_increase(
        context.manifest.initial_budget_policy,
        history,
        dimension="tokens",
        old_value=5,
        new_value=10,
        actor="operator",
        reason="continue deterministic inventory",
    )
    context.event_store.append(
        authorization["type"],
        authorization["payload"],
        occurred_at=CERTIFIED,
    )
    context.event_store.append(
        "run_resumed",
        {"reason": "resource ceiling raised"},
        occurred_at=CERTIFIED,
    )
    second_executor = FakeProviderExecutor(tmp_path, token_usage=1)

    completed = _controller(context, executor=second_executor).run_until_stopped()

    assert completed.status == "complete"
    assert len(second_executor.calls) == 1


def test_result_contract_retry_is_not_blocked_by_generation_exhaustion(
    tmp_path: Path,
) -> None:
    template = _template("inventory", goal="inventory")
    context = _context(
        tmp_path,
        (template,),
        generation_attempt_limit=1,
    )
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.manifest.run_manifest_id},
        occurred_at=NOW,
    )
    item = plan_next(
        context.graph,
        context.ledger.replay(),
        evaluate_budget(
            context.manifest.initial_budget_policy,
            context.event_store.replay(),
            now=NOW,
        ),
    ).ready[0]
    lease = context.candidate_store.begin(
        item,
        _identity_factory(item, "initial_generation", 1, NOW),
        dispatch_id="dispatch-invalid-initial",
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
    invalid = ExecutionObservation(
        started_at=NOW,
        ended_at=OBSERVED,
        duration_ms=1_000,
        exit_code=0,
        timed_out=False,
        output_truncated=False,
        result_contract_valid=False,
        token_usage=0,
        provider_name="fixture",
        model_name="fixture-model",
        stderr_digest=None,
    )
    context.event_store.append(
        "dispatch_observed",
        {
            "dispatch_id": lease.dispatch_id,
            "observation": invalid.to_json_dict(),
            "work_item_id": item.work_item_id,
        },
        occurred_at=OBSERVED,
    )
    executor = FakeProviderExecutor(tmp_path)

    result = _controller(context, executor=executor).run_until_stopped()

    starts = [
        event
        for event in context.event_store.replay()
        if event.type == "dispatch_started"
    ]
    assert result.status == "complete"
    assert [event.payload["attempt_kind"] for event in starts] == [
        "initial_generation",
        "result_contract_retry",
    ]


def test_repeated_terminal_runs_do_not_duplicate_work_or_acceptance(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    executor = FakeProviderExecutor(tmp_path)
    controller = _controller(context, executor=executor)

    first = controller.run_until_stopped()
    first_events = context.event_store.replay()
    second = controller.run_once()

    assert first.status == second.status == "complete"
    assert context.event_store.replay() == first_events
    assert len(executor.calls) == 1
    assert context.certifier.calls == 1


def test_completion_requires_every_requested_goal_to_be_reused_or_accepted(
    tmp_path: Path,
) -> None:
    first = _template("first")
    second = _template("second")
    context = _context(tmp_path, (first, second))
    executor = FakeProviderExecutor(tmp_path)
    controller = _controller(context, executor=executor)

    after_one = controller.run_once()

    assert after_one.status == "active"
    assert not any(
        event.type == "run_completed" for event in context.event_store.replay()
    )


def test_controller_validates_the_pinned_certifier_before_dispatch(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    context.certifier.verifier_version = "v2"
    executor = FakeProviderExecutor(tmp_path)

    with pytest.raises(ReV2ControllerError, match="certifier"):
        _controller(context, executor=executor).run_once()

    assert executor.calls == []
    assert not any(
        event.type in {"work_planned", "dispatch_leased"}
        for event in context.event_store.replay()
    )


def test_deterministic_inventory_omits_operational_git_worktree_metadata(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / ".git").write_text("gitdir: /mutable/admin/path\n", encoding="utf-8")
    (snapshot / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
    item_template = _template(
        "source-inventory",
        goal="inventory",
        producer="deterministic-source-inventory",
    )
    context_root = tmp_path / "context"
    context_root.mkdir()
    context = _context(context_root, (item_template,))
    item = plan_next(
        context.graph,
        context.ledger.replay(),
        evaluate_budget(
            context.manifest.initial_budget_policy,
            (),
            now=NOW,
        ),
    ).ready[0]
    identity = _identity_factory(item, "initial_generation", 1, NOW)
    lease = DispatchLease(
        dispatch_id="dispatch-inventory",
        work_item_id=item.work_item_id,
        work_item=item,
        process_identity=identity,
        leased_at=NOW,
    )
    executor = DeterministicInventoryExecutor(
        tmp_path / "inventory-output", clock=lambda: NOW
    )

    output, _observation = executor.execute(snapshot, item, lease)
    inventory = json.loads((output / "inventory.json").read_bytes())

    assert [entry["path"] for entry in inventory["snapshot_entries"]] == ["api.py"]


def test_production_registry_does_not_write_before_recovery_validation(
    tmp_path: Path,
) -> None:
    template = _template(
        "source-inventory",
        goal="inventory",
        producer="deterministic-source-inventory",
    )
    context = _context(tmp_path, (template,))
    output_root = context.paths.root / ".execution"

    ReV2Controller(
        context,
        process_inspector=DeadInspector(),
        process_identity_factory=_identity_factory,
        clock=lambda: NOW,
    )

    assert not output_root.exists()


@pytest.mark.parametrize(
    ("fault_point", "initial_executor_calls"),
    [
        ("dispatch_started", 0),
        ("provider_terminated", 1),
    ],
)
def test_restart_before_durable_candidate_dispatches_one_replacement(
    tmp_path: Path, fault_point: str, initial_executor_calls: int
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    executor = FakeProviderExecutor(tmp_path)
    failed = False

    def fail_once(boundary: str) -> None:
        nonlocal failed
        if boundary == fault_point and not failed:
            failed = True
            raise RuntimeError(f"crash at {boundary}")

    crashing = ReV2Controller(
        context,
        executor_registry={_registry_key(context.graph.templates[0]): executor},
        process_inspector=DeadInspector(),
        process_identity_factory=_identity_factory,
        clock=lambda: NOW,
        fault_hook=fail_once,
    )
    with pytest.raises(RuntimeError, match="crash"):
        crashing.run_once()

    assert len(executor.calls) == initial_executor_calls

    recovered = _controller(context, executor=executor).run_until_stopped()
    event_types = [event.type for event in context.event_store.replay()]

    assert recovered.status == "complete"
    assert len(executor.calls) == initial_executor_calls + 1
    assert event_types.count("dispatch_started") == 2
    assert event_types.count("dispatch_observed") == 2
    assert event_types.count("candidate_persisted") == 1
    assert event_types.count("candidate_certified") == 1


@pytest.mark.parametrize(
    "fault_point",
    [
        "candidate_renamed",
        "certification_written",
        "artifact_acceptance_written",
        "checkpoint_recorded",
    ],
)
def test_restart_after_durable_candidate_never_duplicates_work(
    tmp_path: Path, fault_point: str
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    executor = FakeProviderExecutor(tmp_path)
    failed = False

    def fail_once(boundary: str) -> None:
        nonlocal failed
        if boundary == fault_point and not failed:
            failed = True
            raise RuntimeError(f"crash at {boundary}")

    crashing = ReV2Controller(
        context,
        executor_registry={_registry_key(context.graph.templates[0]): executor},
        process_inspector=DeadInspector(),
        process_identity_factory=_identity_factory,
        clock=lambda: NOW,
        fault_hook=fail_once,
    )
    with pytest.raises((RuntimeError, ReV2ControllerError), match="crash"):
        crashing.run_once()

    if fault_point == "candidate_renamed":
        assert len(context.candidate_store.discover()) == 1
        assert not any(
            event.type == "dispatch_observed"
            for event in context.event_store.replay()
        )

    recovered = _controller(context, executor=executor).run_until_stopped()
    event_types = [event.type for event in context.event_store.replay()]

    assert recovered.status == "complete"
    assert len(executor.calls) == 1
    assert context.certifier.calls == 1
    assert event_types.count("dispatch_started") == 1
    assert event_types.count("candidate_certified") == 1
    assert event_types.count("artifact_accepted") == 1
    assert event_types.count("checkpoint_recorded") == 1
