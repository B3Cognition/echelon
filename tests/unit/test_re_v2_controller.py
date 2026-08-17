from __future__ import annotations

from dataclasses import dataclass, replace as dataclass_replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Callable

import pytest

from harness.re_v2 import candidates as candidate_module
from harness.re_v2.budget import authorize_resource_increase, evaluate_budget
from harness.re_v2.candidates import CandidateStore, DispatchLease, ProcessIdentity
from harness.re_v2.canonical import content_digest
from harness.re_v2.controller import (
    DeterministicInventoryExecutor,
    ExecutorRegistration,
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
from harness.re_v2.recovery import (
    ProcessInspector,
    ProcessState,
    ReV2RecoveryError,
    ReV2RunContext,
)
from harness.re_v2.run_store import create_run_store
from harness.re_v2.snapshot import capture_source_snapshot


NOW = "2026-08-14T12:00:00Z"
OBSERVED = "2026-08-14T12:00:01Z"
PERSISTED = "2026-08-14T12:00:02Z"
CERTIFIED = "2026-08-14T12:00:03Z"
PROCESS_START = "linux:fixture-start"
POLICY_VERSION = "egr-164-v1"
PROVIDER_CONTRACT = {"provider": "fixture"}
PROVIDER_CONTRACT_HASH = content_digest(PROVIDER_CONTRACT)


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
        provider_contract_hash: str = PROVIDER_CONTRACT_HASH,
    ) -> None:
        self.root = root
        self.token_usage = token_usage
        self.timed_out = timed_out
        self.result_contract_valid = result_contract_valid
        self._provider_name = provider_name
        self._provider_contract_hash = provider_contract_hash
        self.calls: list[tuple[Path, WorkItem, DispatchLease]] = []

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def provider_contract_hash(self) -> str:
        return self._provider_contract_hash

    @property
    def execution_mode(self) -> str:
        return "in_process"

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


class WritableMetadataExecutor:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.provider_name = "fixture"
        self.provider_contract_hash = PROVIDER_CONTRACT_HASH
        self.calls: list[tuple[Path, WorkItem, DispatchLease]] = []

    def execute(
        self, snapshot_root: Path, work_item: WorkItem, lease: DispatchLease
    ) -> tuple[Path, ExecutionObservation]:
        self.calls.append((snapshot_root, work_item, lease))
        raise AssertionError("writable-metadata executor must never execute")


class PipeGatedProcessHandle:
    """Test handle whose child treats pipe EOF as an unleased abort."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        control_fd: int,
        process_identity: object,
    ) -> None:
        self.process = process
        self._control_fd: int | None = control_fd
        self._process_identity = process_identity
        self.release_calls = 0
        self.abort_calls = 0
        self.close_calls = 0

    @property
    def process_identity(self) -> object:
        return self._process_identity

    def release_leased(self) -> None:
        self.release_calls += 1
        if self._control_fd is None:
            raise AssertionError("gated handle was already released or closed")
        os.write(self._control_fd, b"L")
        os.close(self._control_fd)
        self._control_fd = None

    def abort_unleased(self) -> None:
        self.abort_calls += 1
        if self._control_fd is not None:
            os.close(self._control_fd)
            self._control_fd = None
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)

    def close(self) -> None:
        self.close_calls += 1
        if self._control_fd is not None:
            os.close(self._control_fd)
            self._control_fd = None


class GatedSubprocessExecutor:
    """Create a real provider child gated by an owned control-pipe handle."""

    def __init__(
        self,
        *,
        side_effect_path: Path | None = None,
        identity_path: Path | None = None,
        after_start: Callable[[PipeGatedProcessHandle, WorkItem, str], None]
        | None = None,
    ) -> None:
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.handles: dict[str, PipeGatedProcessHandle] = {}
        self.start_calls: list[str] = []
        self.collect_calls: list[str] = []
        self.side_effect_path = side_effect_path
        self.identity_path = identity_path
        self.after_start = after_start
        self._provider_name = "fixture"
        self._execution_mode = "provider_process"

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def provider_contract_hash(self) -> str:
        return PROVIDER_CONTRACT_HASH

    @property
    def execution_mode(self) -> str:
        return self._execution_mode

    def start(
        self,
        snapshot_root: Path,
        work_item: WorkItem,
        dispatch_id: str,
    ) -> PipeGatedProcessHandle:
        assert snapshot_root.is_dir()
        read_fd, write_fd = os.pipe()
        child_script = (
            "import os, pathlib, sys, time\n"
            "fd = int(sys.argv[1])\n"
            "token = os.read(fd, 1)\n"
            "os.close(fd)\n"
            "if token != b'L':\n"
            "    raise SystemExit(0)\n"
            "marker = sys.argv[2]\n"
            "if marker:\n"
            "    pathlib.Path(marker).write_text('provider work started\\n')\n"
            "time.sleep(120)\n"
        )
        command = [
            sys.executable,
            "-c",
            child_script,
            str(read_fd),
            str(self.side_effect_path) if self.side_effect_path is not None else "",
        ]
        child = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            pass_fds=(read_fd,),
        )
        os.close(read_fd)
        observed = recovery_process_start(child.pid)
        assert observed is not None
        self.processes[dispatch_id] = child
        self.start_calls.append(dispatch_id)
        identity = ProcessIdentity(
            pid=child.pid,
            process_start_identity=observed,
            command_hash=content_digest(command),
            provider_identity=content_digest(
                {
                    "producer_id": work_item.producer_id,
                    "provider": self.provider_name,
                }
            ),
            started_at=_utc_now(),
        )
        handle = PipeGatedProcessHandle(child, write_fd, identity)
        self.handles[dispatch_id] = handle
        if self.identity_path is not None:
            self.identity_path.write_bytes(
                json.dumps(identity.to_json_dict(), sort_keys=True).encode()
            )
        if self.after_start is not None:
            self.after_start(handle, work_item, dispatch_id)
        return handle

    def collect(
        self,
        snapshot_root: Path,
        work_item: WorkItem,
        lease: DispatchLease,
    ) -> tuple[Path, ExecutionObservation]:
        assert self.handles[lease.dispatch_id].release_calls == 1
        self.collect_calls.append(lease.dispatch_id)
        raise AssertionError("crash test must never release the gated provider child")

    def terminate_all(self) -> None:
        for handle in self.handles.values():
            handle.close()
        for process in self.processes.values():
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def recovery_process_start(pid: int) -> str | None:
    return ProcessInspector()._probe(pid)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _wait_for_dead(identity: ProcessIdentity) -> None:
    for _attempt in range(200):
        if ProcessInspector().inspect(identity) is ProcessState.DEAD:
            return
        time.sleep(0.01)
    pytest.fail(f"provider child {identity.pid} remained live")


def _assert_unleased_child_aborted(
    executor: GatedSubprocessExecutor,
    side_effect_path: Path,
) -> None:
    assert len(executor.handles) == 1
    handle = next(iter(executor.handles.values()))
    assert isinstance(handle.process_identity, ProcessIdentity)
    assert handle.release_calls == 0
    assert handle.abort_calls == 1
    assert handle.close_calls == 1
    assert handle.process.poll() is not None
    assert executor.collect_calls == []
    assert not side_effect_path.exists()


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
        layer_policy_hash=content_digest(
            {"artifact_kind": kind, "policy_version": POLICY_VERSION}
        ),
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
        provider_contract=PROVIDER_CONTRACT,
        artifact_policy_versions={
            template.layer: POLICY_VERSION
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


def _registry_key(template: WorkTemplate) -> tuple[str, str, str, str, str, str]:
    return (
        "fixture",
        PROVIDER_CONTRACT_HASH,
        template.producer_id,
        template.producer_protocol_version,
        template.layer,
        template.result_contract_id,
    )


def _registration(
    template: WorkTemplate,
    executor: WorkExecutor,
) -> ExecutorRegistration:
    return ExecutorRegistration(
        provider_name="fixture",
        provider_contract_hash=PROVIDER_CONTRACT_HASH,
        producer_id=template.producer_id,
        producer_protocol_version=template.producer_protocol_version,
        layer=template.layer,
        result_contract_id=template.result_contract_id,
        execution_mode="in_process",
        executor=executor,
    )


def _controller(
    context: ReV2RunContext,
    *,
    executor: WorkExecutor | None = None,
) -> ReV2Controller:
    return ReV2Controller(
        context,
        executor=executor,
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
        "fixture",
        PROVIDER_CONTRACT_HASH,
        "fixture-producer",
        "wrong-protocol",
        "L0",
        "fixture-result-v1",
    )
    registration = ExecutorRegistration(
        provider_name="fixture",
        provider_contract_hash=PROVIDER_CONTRACT_HASH,
        producer_id="fixture-producer",
        producer_protocol_version="wrong-protocol",
        layer="L0",
        result_contract_id="fixture-result-v1",
        execution_mode="in_process",
        executor=executor,
    )
    controller = ReV2Controller(
        context,
        executor_registry={wrong_key: registration},
        process_inspector=DeadInspector(),
        process_identity_factory=_identity_factory,
        clock=lambda: NOW,
    )

    result = controller.run_once()

    assert result.status == "paused"
    assert result.reason_code == "producer_not_registered"
    events = context.event_store.replay()
    assert not any(
        event.type in {"work_planned", "dispatch_leased", "dispatch_started"}
        for event in events
    )


def test_executor_registry_rejects_raw_executor_values(tmp_path: Path) -> None:
    template = _template("inventory", goal="inventory")
    context = _context(tmp_path, (template,))
    executor = FakeProviderExecutor(tmp_path)

    with pytest.raises(ReV2ControllerError, match="ExecutorRegistration|frozen"):
        ReV2Controller(
            context,
            executor_registry={_registry_key(template): executor},
            process_inspector=DeadInspector(),
            process_identity_factory=_identity_factory,
            clock=lambda: NOW,
        )

    assert executor.calls == []
    assert context.event_store.replay() == ()


def test_provider_process_registration_requires_two_phase_executor_contract() -> None:
    template = _template("inventory", goal="inventory")
    executor = GatedSubprocessExecutor()

    registration = ExecutorRegistration(
        provider_name="fixture",
        provider_contract_hash=PROVIDER_CONTRACT_HASH,
        producer_id=template.producer_id,
        producer_protocol_version=template.producer_protocol_version,
        layer=template.layer,
        result_contract_id=template.result_contract_id,
        execution_mode="provider_process",
        executor=executor,
    )

    assert registration.execution_mode == "provider_process"


def test_convenience_executor_rejects_writable_provider_metadata(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    executor = WritableMetadataExecutor(tmp_path)

    with pytest.raises(ReV2ControllerError, match="read-only|immutable"):
        ReV2Controller(
            context,
            executor=executor,
            process_inspector=DeadInspector(),
            process_identity_factory=_identity_factory,
            clock=lambda: NOW,
        )

    assert executor.calls == []
    assert context.event_store.replay() == ()


@pytest.mark.parametrize(
    ("attribute", "wrong_value"),
    (
        ("_provider_name", "other-provider"),
        (
            "_provider_contract_hash",
            content_digest({"provider": "fixture", "tier": 2}),
        ),
    ),
)
def test_registry_revalidates_executor_declared_provider_binding(
    tmp_path: Path,
    attribute: str,
    wrong_value: str,
) -> None:
    template = _template("inventory", goal="inventory")
    context = _context(tmp_path, (template,))
    executor = FakeProviderExecutor(tmp_path)
    registration = _registration(template, executor)
    setattr(executor, attribute, wrong_value)

    with pytest.raises(ReV2ControllerError, match="provider"):
        ReV2Controller(
            context,
            executor_registry={registration.key: registration},
            process_inspector=DeadInspector(),
            process_identity_factory=_identity_factory,
            clock=lambda: NOW,
        )

    assert executor.calls == []
    assert context.event_store.replay() == ()


@pytest.mark.parametrize(
    ("attribute", "wrong_value"),
    (
        ("_provider_name", "other-provider"),
        (
            "_provider_contract_hash",
            content_digest({"provider": "fixture", "tier": 2}),
        ),
    ),
)
def test_registry_revalidates_executor_binding_immediately_before_dispatch(
    tmp_path: Path,
    attribute: str,
    wrong_value: str,
) -> None:
    template = _template("inventory", goal="inventory")
    context = _context(tmp_path, (template,))
    executor = FakeProviderExecutor(tmp_path)
    registration = _registration(template, executor)
    controller = ReV2Controller(
        context,
        executor_registry={registration.key: registration},
        process_inspector=DeadInspector(),
        process_identity_factory=_identity_factory,
        clock=lambda: NOW,
    )
    setattr(executor, attribute, wrong_value)

    with pytest.raises(ReV2ControllerError, match="provider binding"):
        controller.run_once()

    assert executor.calls == []
    assert not any(
        event.type in {"work_planned", "dispatch_leased", "dispatch_started"}
        for event in context.event_store.replay()
    )
    assert not (context.paths.candidates / ".leases").exists()


@pytest.mark.parametrize(
    ("attribute", "wrong_value"),
    (
        ("_provider_name", "other-provider"),
        (
            "_provider_contract_hash",
            content_digest({"provider": "fixture", "tier": 2}),
        ),
    ),
)
def test_convenience_executor_revalidates_binding_immediately_before_dispatch(
    tmp_path: Path,
    attribute: str,
    wrong_value: str,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    executor = FakeProviderExecutor(tmp_path)
    controller = _controller(context, executor=executor)
    setattr(executor, attribute, wrong_value)

    with pytest.raises(ReV2ControllerError, match="provider binding"):
        controller.run_once()

    assert executor.calls == []
    assert not any(
        event.type in {"work_planned", "dispatch_leased", "dispatch_started"}
        for event in context.event_store.replay()
    )
    assert not (context.paths.candidates / ".leases").exists()


def test_convenience_executor_provider_name_must_match_before_planning(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    executor = FakeProviderExecutor(tmp_path, provider_name="other-provider")

    with pytest.raises(ReV2ControllerError, match="provider"):
        _controller(context, executor=executor).run_once()

    assert executor.calls == []
    assert not any(
        event.type in {"work_planned", "dispatch_leased", "dispatch_started"}
        for event in context.event_store.replay()
    )
    assert context.candidate_store.discover() == ()


def test_convenience_executor_contract_hash_must_match_before_planning(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    executor = FakeProviderExecutor(
        tmp_path,
        provider_contract_hash=content_digest({"provider": "fixture", "tier": 2}),
    )

    with pytest.raises(ReV2ControllerError, match="provider contract"):
        _controller(context, executor=executor).run_once()

    assert executor.calls == []
    assert not any(
        event.type in {"work_planned", "dispatch_leased", "dispatch_started"}
        for event in context.event_store.replay()
    )


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
        tmp_path / "inventory-output",
        provider_contract_hash=PROVIDER_CONTRACT_HASH,
        clock=lambda: NOW,
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


def test_probe_mismatch_aborts_and_reaps_unleased_provider_child(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    context = dataclass_replace(
        context,
        candidate_store=CandidateStore(
            context.paths,
            process_probe=lambda _pid: "wrong-process-start",
            clock=_utc_now,
        ),
    )
    marker = tmp_path / "provider-side-effect"
    executor = GatedSubprocessExecutor(side_effect_path=marker)

    try:
        with pytest.raises(ReV2ControllerError, match="start identity mismatch"):
            ReV2Controller(
                context,
                executor=executor,
                process_inspector=ProcessInspector(),
                clock=_utc_now,
            ).run_once()

        _assert_unleased_child_aborted(executor, marker)
    finally:
        executor.terminate_all()


def test_controller_pid_identity_aborts_actual_owned_provider_child(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    context = dataclass_replace(
        context,
        candidate_store=CandidateStore(context.paths, clock=_utc_now),
    )
    marker = tmp_path / "provider-side-effect"

    def return_controller_identity(
        handle: PipeGatedProcessHandle,
        _item: WorkItem,
        _dispatch_id: str,
    ) -> None:
        controller_start = recovery_process_start(os.getpid())
        assert controller_start is not None
        actual = handle.process_identity
        assert isinstance(actual, ProcessIdentity)
        handle._process_identity = dataclass_replace(
            actual,
            pid=os.getpid(),
            process_start_identity=controller_start,
        )

    executor = GatedSubprocessExecutor(
        side_effect_path=marker,
        after_start=return_controller_identity,
    )
    try:
        with pytest.raises(ReV2ControllerError, match="controller PID"):
            ReV2Controller(
                context,
                executor=executor,
                process_inspector=ProcessInspector(),
                clock=_utc_now,
            ).run_once()

        handle = next(iter(executor.handles.values()))
        assert handle.abort_calls == 1
        assert handle.close_calls == 1
        assert handle.process.poll() is not None
        assert not marker.exists()
    finally:
        executor.terminate_all()


def test_invalid_handle_identity_aborts_and_reaps_owned_provider_child(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    marker = tmp_path / "provider-side-effect"

    def return_invalid_identity(
        handle: PipeGatedProcessHandle,
        _item: WorkItem,
        _dispatch_id: str,
    ) -> None:
        handle._process_identity = object()

    executor = GatedSubprocessExecutor(
        side_effect_path=marker,
        after_start=return_invalid_identity,
    )
    try:
        with pytest.raises(ReV2ControllerError, match="ProcessIdentity"):
            ReV2Controller(
                context,
                executor=executor,
                process_inspector=ProcessInspector(),
                clock=_utc_now,
            ).run_once()

        handle = next(iter(executor.handles.values()))
        assert handle.release_calls == 0
        assert handle.abort_calls == 1
        assert handle.close_calls == 1
        assert handle.process.poll() is not None
        assert not marker.exists()
    finally:
        executor.terminate_all()


def test_post_start_clock_rejection_aborts_and_reaps_unleased_provider_child(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    marker = tmp_path / "provider-side-effect"
    executor = GatedSubprocessExecutor(side_effect_path=marker)
    clock_values = iter((NOW, "not-a-timestamp"))

    try:
        with pytest.raises(ReV2ControllerError, match="post-start controller clock"):
            ReV2Controller(
                context,
                executor=executor,
                process_inspector=ProcessInspector(),
                clock=lambda: next(clock_values),
            ).run_once()

        _assert_unleased_child_aborted(executor, marker)
    finally:
        executor.terminate_all()


@pytest.mark.parametrize(
    ("attribute", "wrong_value"),
    (
        ("_provider_name", "other-provider"),
        ("_execution_mode", "in_process"),
    ),
)
def test_post_start_binding_or_mode_rejection_aborts_unleased_provider_child(
    tmp_path: Path,
    attribute: str,
    wrong_value: str,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    marker = tmp_path / "provider-side-effect"
    executor: GatedSubprocessExecutor

    def mutate_executor_binding(
        _handle: PipeGatedProcessHandle,
        _item: WorkItem,
        _dispatch_id: str,
    ) -> None:
        setattr(executor, attribute, wrong_value)

    executor = GatedSubprocessExecutor(
        side_effect_path=marker,
        after_start=mutate_executor_binding,
    )
    try:
        with pytest.raises(ReV2ControllerError, match="provider binding"):
            ReV2Controller(
                context,
                executor=executor,
                process_inspector=ProcessInspector(),
                clock=_utc_now,
            ).run_once()

        _assert_unleased_child_aborted(executor, marker)
        assert not (context.paths.candidates / ".leases").exists()
    finally:
        executor.terminate_all()


def test_conflicting_lease_aborts_and_reaps_unleased_provider_child(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    context = dataclass_replace(
        context,
        candidate_store=CandidateStore(context.paths, clock=_utc_now),
    )
    marker = tmp_path / "provider-side-effect"

    def write_conflicting_lease(
        handle: PipeGatedProcessHandle,
        item: WorkItem,
        dispatch_id: str,
    ) -> None:
        actual = handle.process_identity
        assert isinstance(actual, ProcessIdentity)
        conflicting = dataclass_replace(
            actual,
            command_hash=content_digest({"conflicting": dispatch_id}),
        )
        context.candidate_store.begin(
            item,
            conflicting,
            dispatch_id=dispatch_id,
            leased_at=_utc_now(),
        )

    executor = GatedSubprocessExecutor(
        side_effect_path=marker,
        after_start=write_conflicting_lease,
    )
    try:
        with pytest.raises(ReV2ControllerError, match="conflicting lease"):
            ReV2Controller(
                context,
                executor=executor,
                process_inspector=ProcessInspector(),
                clock=_utc_now,
            ).run_once()

        _assert_unleased_child_aborted(executor, marker)
    finally:
        executor.terminate_all()


@pytest.mark.parametrize("failure_point", ("write", "link", "fsync"))
def test_lease_publication_failure_aborts_and_reaps_unleased_provider_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    context = dataclass_replace(
        context,
        candidate_store=CandidateStore(context.paths, clock=_utc_now),
    )
    if failure_point == "fsync":
        (context.paths.candidates / ".leases").mkdir(mode=0o700)
    marker = tmp_path / "provider-side-effect"

    def fail_lease_publication(
        _handle: PipeGatedProcessHandle,
        _item: WorkItem,
        _dispatch_id: str,
    ) -> None:
        def fail(*_args: object, **_kwargs: object) -> None:
            raise OSError(f"lease {failure_point} failed")

        if failure_point == "write":
            monkeypatch.setattr(candidate_module, "_write_new_file", fail)
        elif failure_point == "link":
            monkeypatch.setattr(candidate_module.os, "link", fail)
        else:
            monkeypatch.setattr(candidate_module, "_fsync_directory", fail)

    executor = GatedSubprocessExecutor(
        side_effect_path=marker,
        after_start=fail_lease_publication,
    )
    try:
        with pytest.raises(OSError, match=f"lease {failure_point} failed"):
            ReV2Controller(
                context,
                executor=executor,
                process_inspector=ProcessInspector(),
                clock=_utc_now,
            ).run_once()

        _assert_unleased_child_aborted(executor, marker)
    finally:
        executor.terminate_all()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX process recovery")
def test_unleased_provider_child_exits_when_controller_hard_crashes(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    context = dataclass_replace(
        context,
        candidate_store=CandidateStore(context.paths, clock=_utc_now),
    )
    marker = tmp_path / "provider-side-effect"
    identity_path = tmp_path / "provider-identity.json"
    controller_pid = os.fork()
    if controller_pid == 0:  # pragma: no cover - assertions run in the parent
        try:
            executor = GatedSubprocessExecutor(
                side_effect_path=marker,
                identity_path=identity_path,
            )

            def die_before_lease(boundary: str) -> None:
                if boundary == "provider_started":
                    os._exit(81)

            ReV2Controller(
                context,
                executor=executor,
                process_inspector=ProcessInspector(),
                clock=_utc_now,
                fault_hook=die_before_lease,
            ).run_once()
        except BaseException:
            os._exit(82)
        os._exit(83)

    _waited_pid, status = os.waitpid(controller_pid, 0)
    assert os.waitstatus_to_exitcode(status) == 81
    identity = ProcessIdentity.from_json_dict(json.loads(identity_path.read_bytes()))
    _wait_for_dead(identity)
    assert not marker.exists()
    assert not tuple((context.paths.candidates / ".leases").glob("*.json"))


def test_real_provider_child_is_leased_before_collect_and_blocks_redispatch(
    tmp_path: Path,
) -> None:
    """A provider child surviving controller death remains the recovery authority."""
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    context = dataclass_replace(
        context,
        candidate_store=CandidateStore(context.paths, clock=_utc_now),
    )
    first = GatedSubprocessExecutor()
    replacement = GatedSubprocessExecutor()

    def controller_died(boundary: str) -> None:
        if boundary == "dispatch_started":
            raise RuntimeError("controller died")

    try:
        crashing = ReV2Controller(
            context,
            executor=first,
            process_inspector=ProcessInspector(),
            clock=_utc_now,
            fault_hook=controller_died,
        )

        with pytest.raises(RuntimeError, match="controller died"):
            crashing.run_once()

        assert len(first.start_calls) == 1
        assert first.collect_calls == []
        dispatch_id = first.start_calls[0]
        child = first.processes[dispatch_id]
        assert child.poll() is None
        lease_envelope = json.loads(
            (
                context.paths.candidates
                / ".leases"
                / f"{dispatch_id}.json"
            ).read_bytes()
        )
        lease = DispatchLease.from_json_dict(lease_envelope["lease"])
        assert lease.process_identity.pid == child.pid
        assert lease.process_identity.pid != os.getpid()

        recovering = ReV2Controller(
            context,
            executor=replacement,
            process_inspector=ProcessInspector(),
            clock=_utc_now,
        )
        with pytest.raises(ReV2RecoveryError, match="still running"):
            recovering.run_once()

        assert replacement.start_calls == []
        assert replacement.collect_calls == []
        assert [
            event.type for event in context.event_store.replay()
        ].count("dispatch_started") == 1
    finally:
        first.terminate_all()
        replacement.terminate_all()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX process recovery")
def test_provider_child_survives_actual_controller_process_death(
    tmp_path: Path,
) -> None:
    """The durable lease names the grandchild after its controller exits abruptly."""
    context = _context(tmp_path, (_template("inventory", goal="inventory"),))
    context = dataclass_replace(
        context,
        candidate_store=CandidateStore(context.paths, clock=_utc_now),
    )
    controller_pid = os.fork()
    if controller_pid == 0:  # pragma: no cover - assertions run in the parent
        try:
            executor = GatedSubprocessExecutor()

            def die_after_durable_start(boundary: str) -> None:
                if boundary == "dispatch_started":
                    os._exit(73)

            ReV2Controller(
                context,
                executor=executor,
                process_inspector=ProcessInspector(),
                clock=_utc_now,
                fault_hook=die_after_durable_start,
            ).run_once()
        except BaseException:
            os._exit(74)
        os._exit(75)

    _waited_pid, status = os.waitpid(controller_pid, 0)
    assert os.waitstatus_to_exitcode(status) == 73
    lease_files = tuple(
        (context.paths.candidates / ".leases").glob("*.json")
    )
    assert len(lease_files) == 1
    lease = DispatchLease.from_json_dict(
        json.loads(lease_files[0].read_bytes())["lease"]
    )
    provider_pid = lease.process_identity.pid
    replacement = GatedSubprocessExecutor()
    try:
        assert provider_pid != controller_pid
        assert provider_pid != os.getpid()
        assert (
            ProcessInspector().inspect(lease.process_identity)
            is ProcessState.SAME_PROCESS_LIVE
        )

        recovering = ReV2Controller(
            context,
            executor=replacement,
            process_inspector=ProcessInspector(),
            clock=_utc_now,
        )
        with pytest.raises(ReV2RecoveryError, match="still running"):
            recovering.run_once()

        assert replacement.start_calls == []
        assert replacement.collect_calls == []
        assert [
            event.type for event in context.event_store.replay()
        ].count("dispatch_started") == 1
    finally:
        try:
            os.kill(provider_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        for _attempt in range(100):
            if ProcessInspector().inspect(lease.process_identity) is ProcessState.DEAD:
                break
            time.sleep(0.01)
        replacement.terminate_all()


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
        executor=executor,
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
        executor=executor,
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
