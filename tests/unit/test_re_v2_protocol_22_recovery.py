from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
from types import SimpleNamespace
from types import MappingProxyType
from typing import Mapping

import pytest

import harness.re_v2.protocol_22.recovery as recovery_module
from harness.re_v2.candidates import ProcessIdentity
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.events import EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.authorities import InstalledAuthorityRegistry
from harness.re_v2.protocol_22.artifacts import ContextBundleV1
from harness.re_v2.protocol_22.baseline import CandidateAssessmentReceiptV1
from harness.re_v2.protocol_22.events import PROTOCOL_22_EVENTS
from harness.re_v2.protocol_22.execution import (
    DeterministicExecutionDependenciesV1,
    DeterministicRawResultV1,
    Protocol22ExecutionStore,
    ProviderExecutionDependenciesV1,
)
from harness.re_v2.protocol_22.graph import (
    build_protocol_22_graph,
    instantiate_ready_item,
)
from harness.re_v2.protocol_22.inputs import (
    create_protocol_22_run_store,
    load_protocol_22_inputs,
)
from harness.re_v2.protocol_22.ledger import Protocol22Ledger, Protocol22LedgerView
from harness.re_v2.protocol_22.ledger import (
    ExecutorFailureReceiptV1,
    WorkItemFailureReceiptV1,
)
from harness.re_v2.protocol_22.model import (
    DeterministicInvocationInputV1,
    DeterministicInvocationV1,
    WorkItemV2,
)
from harness.re_v2.protocol_22.recovery import (
    PinnedAuthorityUnavailable,
    Protocol22RecoveryError,
    Protocol22RunContext,
    candidate_reconstructs_result_contract,
    recover_protocol_22_run,
)
from harness.re_v2.protocol_22.response_schemas import canonical_response_schema_bytes
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.protocol_22.provider import (
    RawExecutionResultV1,
    RawExecutionTimingV1,
)
from harness.re_v2.recovery import ProcessState
from tests.re_v2_protocol_22_fixtures import digest, work_item_v2
from tests.unit.test_re_v2_protocol_22_inputs import _input_fixture
from tests.unit.test_re_v2_protocol_22_ledger import _deterministic_authority
from tests.unit.test_re_v2_protocol_22_certification import _valid_domain_candidate
from tests.unit.test_re_v2_protocol_22_context import _domain_fixture
from tests.unit.test_re_v2_protocol_22_provider import (
    AGENT_BYTES,
    _authority,
    _tokenizer,
)


NOW = "2026-08-22T10:00:00Z"


@dataclass
class _RecordingProvider:
    calls: int = 0

    def execute(self, *_args: object, **_kwargs: object) -> None:
        self.calls += 1
        raise AssertionError("recovery must not call the provider")


@dataclass(frozen=True)
class _Inspector:
    state: ProcessState

    def inspect(self, _identity: ProcessIdentity) -> ProcessState:
        return self.state


@dataclass(frozen=True)
class RecoveryFixture:
    context: Protocol22RunContext
    item: WorkItemV2
    dependencies: DeterministicExecutionDependenciesV1
    prepared: object
    provider: _RecordingProvider
    exact_registry: InstalledAuthorityRegistry

    @property
    def dispatch_id(self) -> str:
        return self.prepared.dispatch_id  # type: ignore[attr-defined,no-any-return]


def _registry_from_inputs(inputs: object) -> InstalledAuthorityRegistry:
    executor_implementations: dict[str, str] = {}
    renderer_implementations: dict[str, str] = {}
    tokenizer_implementations: dict[str, str] = {}
    calculator_implementations: dict[str, str] = {}
    normalizer_implementations: dict[str, str] = {}
    verifier_implementations: dict[str, str] = {}
    agent_contracts: dict[str, str] = {}
    response_schemas: dict[str, str] = {}
    for entry in inputs.executor_contract.entries:  # type: ignore[attr-defined]
        executor_implementations[entry.adapter_id] = (
            entry.executor_implementation_digest
        )
        calculator_implementations[entry.reservation_calculator.calculator_id] = (
            entry.reservation_calculator.implementation_digest
        )
        normalizer_implementations[entry.token_accounting.normalization_id] = (
            entry.token_accounting.implementation_digest
        )
        verifier_implementations[entry.verifier.verifier_id] = (
            entry.verifier.implementation_digest
        )
        if entry.request_renderer is not None:
            renderer_implementations[entry.request_renderer.renderer_id] = (
                entry.request_renderer.implementation_digest
            )
            agent_contracts["echelon.re-baseliner"] = (
                entry.request_renderer.agent_contract_hash
            )
            for schema in entry.request_renderer.response_schemas:
                response_schemas[schema.artifact_kind] = schema.schema_hash
        if entry.request_tokenizer is not None:
            tokenizer_implementations[entry.request_tokenizer.tokenizer_id] = (
                entry.request_tokenizer.implementation_digest
            )
    partition = inputs.workspace_partition  # type: ignore[attr-defined]
    return InstalledAuthorityRegistry(
        executor_implementations=executor_implementations,
        renderer_implementations=renderer_implementations,
        tokenizer_implementations=tokenizer_implementations,
        calculator_implementations=calculator_implementations,
        normalizer_implementations=normalizer_implementations,
        verifier_implementations=verifier_implementations,
        partitioner_implementations={
            partition.partitioner.id: partition.partitioner.implementation_digest
        },
        ownership_implementations={
            partition.ownership_policy.id: (
                partition.ownership_policy.implementation_digest
            )
        },
        agent_contracts=agent_contracts,
        response_schemas=response_schemas,
    )


def interrupted_dispatch(
    tmp_path: Path,
    *,
    started: bool,
    staging: bool,
    committed: bool,
    process_state: ProcessState = ProcessState.DEAD,
    artifact_bytes: bytes = b'{"schema_version":1}\n',
) -> RecoveryFixture:
    raw_inputs, raw_manifest = _input_fixture()
    run_id = f"re-recovery-{tmp_path.name}"
    manifest = replace(raw_manifest, run_id=run_id)
    paths = create_protocol_22_run_store(tmp_path / run_id, manifest, raw_inputs)
    inputs = load_protocol_22_inputs(paths, manifest)
    graph = build_protocol_22_graph(manifest, inputs)
    template = next(
        value for value in graph.templates if value.artifact_kind == "source-inventory"
    )
    item = instantiate_ready_item(template, {}, inputs)
    registry = _registry_from_inputs(inputs)
    workspace_bytes = canonical_json_bytes(inputs.workspace_partition.to_json_dict())
    workspace_hash = content_digest(workspace_bytes)
    executor = inputs.executor_contract.entry_for(item.producer_family)
    invocation = DeterministicInvocationV1(
        schema_version=1,
        producer_family=item.producer_family,
        output_key=item.output_key,
        artifact_policy_hash=item.output_key.layer_policy_hash,
        inputs=(
            DeterministicInvocationInputV1(
                role="workspace_partition",
                object_hash=workspace_hash,
            ),
        ),
    )
    dependencies = DeterministicExecutionDependenciesV1(
        executor=executor,
        registry=registry,
        invocation=invocation,
        workspace_partition_hash=workspace_hash,
        referenced_objects={workspace_hash: workspace_bytes},
    )
    objects = ObjectStore(paths.objects)
    execution = Protocol22ExecutionStore(
        paths,
        objects,
        process_probe=lambda _pid: "stable-start",
    )
    prepared = execution.prepare_execution(
        item,
        "initial_generation",
        dependencies,
    )
    events = EventStore(paths, protocol=PROTOCOL_22_EVENTS)
    events.append(
        "run_created",
        {"run_manifest_id": manifest.run_manifest_id},
        occurred_at=manifest.created_at,
    )
    if started:
        process = ProcessIdentity(
            pid=os.getpid(),
            process_start_identity="stable-start",
            command_hash=digest("recovery-controller"),
            provider_identity=digest("in-process-provider"),
            started_at=manifest.created_at,
        )
        execution.record_started_lease(prepared, item, dependencies, process)
        events.append(
            "dispatch_leased",
            {"dispatch_id": prepared.dispatch_id, "work_item_id": item.work_item_id},
            occurred_at=manifest.created_at,
        )
        events.append(
            "dispatch_started",
            {
                "active_ms_reservation": prepared.reservation.active_ms,
                "attempt_index": 1,
                "attempt_kind": "initial_generation",
                "billable_token_reservation": prepared.reservation.billable_tokens,
                "dispatch_id": prepared.dispatch_id,
                "execution_input_hash": prepared.execution_input_hash,
                "executor_contract_hash": item.executor_contract_hash,
                "work_item_id": item.work_item_id,
            },
            occurred_at=manifest.created_at,
        )
    if staging or committed:
        captured = execution.capture_deterministic_result(
            prepared,
            DeterministicRawResultV1(
                artifact_bytes=artifact_bytes,
                stdout=b"",
                stderr=b"",
                started_at="2026-08-22T09:00:01Z",
                ended_at="2026-08-22T09:00:02Z",
                duration_ms=1000,
                exit_code=0,
                timed_out=False,
            ),
        )
        if committed:
            execution.commit_capture(captured)
        else:

            def stop_after_ready(boundary: str) -> None:
                if boundary == "capture_staging_ready_fsynced":
                    raise RuntimeError("fixture crash after staging")

            with pytest.raises(RuntimeError, match="fixture crash"):
                execution.commit_capture(captured, stop_after_ready)

    provider = _RecordingProvider()

    def dependencies_for(
        selected: WorkItemV2,
        _attempt_kind: str,
    ) -> DeterministicExecutionDependenciesV1:
        assert selected == item
        return dependencies

    context = Protocol22RunContext(
        paths=paths,
        inputs=inputs,
        graph=graph,
        event_store=events,
        object_store=objects,
        ledger=Protocol22Ledger(paths, objects),
        execution_store=execution,
        installed_authorities=registry,
        dependencies_for=dependencies_for,
        executors=MappingProxyType({"fixture-provider": provider}),
        producers=MappingProxyType({}),
        verifiers=MappingProxyType({}),
        process_inspector=_Inspector(process_state),
        clock=lambda: NOW,
    )
    return RecoveryFixture(
        context=context,
        item=item,
        dependencies=dependencies,
        prepared=prepared,
        provider=provider,
        exact_registry=registry,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("started", "staging", "committed", "expected_action", "provider_calls"),
    (
        (False, False, False, "prepared", 0),
        (True, False, True, "adopt_committed", 0),
        (True, True, False, "finish_commit", 0),
        (True, False, False, "abandon", 0),
    ),
)
def test_recovery_never_reissues_started_dispatch(
    tmp_path: Path,
    started: bool,
    staging: bool,
    committed: bool,
    expected_action: str,
    provider_calls: int,
) -> None:
    fixture = interrupted_dispatch(
        tmp_path,
        started=started,
        staging=staging,
        committed=committed,
    )

    result = recover_protocol_22_run(fixture.context)

    assert result.dispatch_actions[fixture.dispatch_id] == expected_action
    assert fixture.provider.calls == provider_calls
    if expected_action in {"adopt_committed", "finish_commit"}:
        assert [event.type for event in result.events].count("dispatch_observed") == 1
    if expected_action == "abandon":
        assert [event.type for event in result.events].count("dispatch_abandoned") == 1
        assert result.budget is not None
        assert result.budget.charged_active_ms == fixture.prepared.reservation.active_ms


@pytest.mark.unit
def test_matching_live_owner_is_unavailable_without_abandonment(tmp_path: Path) -> None:
    fixture = interrupted_dispatch(
        tmp_path,
        started=True,
        staging=False,
        committed=False,
        process_state=ProcessState.SAME_PROCESS_LIVE,
    )

    result = recover_protocol_22_run(fixture.context)

    assert result.operational_state == "dispatch_owner_live"
    assert result.dispatch_actions[fixture.dispatch_id] == "live_owner"
    assert all(event.type != "dispatch_abandoned" for event in result.events)
    assert fixture.provider.calls == 0


@pytest.mark.unit
def test_ambiguous_owner_is_unavailable_without_abandonment(tmp_path: Path) -> None:
    fixture = interrupted_dispatch(
        tmp_path,
        started=True,
        staging=False,
        committed=False,
        process_state=ProcessState.PID_REUSED_OR_AMBIGUOUS,
    )

    result = recover_protocol_22_run(fixture.context)

    assert result.operational_state == "dispatch_owner_ambiguous"
    assert result.dispatch_actions[fixture.dispatch_id] == "ambiguous_owner"
    assert all(event.type != "dispatch_abandoned" for event in result.events)
    assert fixture.provider.calls == 0


@pytest.mark.unit
def test_conflicting_or_corrupt_capture_fails_before_provider_call(
    tmp_path: Path,
) -> None:
    fixture = interrupted_dispatch(
        tmp_path,
        started=True,
        staging=False,
        committed=True,
    )
    committed = (
        fixture.context.execution_store.committed_root / f"{fixture.dispatch_id}.json"
    )
    committed.chmod(0o600)
    committed.write_bytes(b'{"conflict":true}\n')

    with pytest.raises(Protocol22RecoveryError, match="capture"):
        recover_protocol_22_run(fixture.context)

    assert fixture.provider.calls == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    "object_field", ("stdout_blob_hash", "deterministic_artifact_hash")
)
def test_corrupt_capture_object_fails_closed(
    tmp_path: Path,
    object_field: str,
) -> None:
    fixture = interrupted_dispatch(
        tmp_path,
        started=True,
        staging=False,
        committed=True,
    )
    state = fixture.context.execution_store.capture_state(fixture.dispatch_id)
    capture = state.closure.capture  # type: ignore[union-attr]
    object_hash = getattr(capture, object_field)
    assert object_hash is not None
    suffix = object_hash.removeprefix("sha256:")
    object_path = fixture.context.paths.objects / "sha256" / suffix[:2] / suffix[2:]
    object_path.unlink()

    with pytest.raises(Protocol22RecoveryError, match="capture"):
        recover_protocol_22_run(fixture.context)

    assert fixture.provider.calls == 0


@pytest.mark.unit
def test_incomplete_staging_is_abandoned_once(tmp_path: Path) -> None:
    fixture = interrupted_dispatch(
        tmp_path,
        started=True,
        staging=False,
        committed=False,
    )
    staging = fixture.context.execution_store.staging_root / fixture.dispatch_id
    staging.mkdir()

    first = recover_protocol_22_run(fixture.context)
    second = recover_protocol_22_run(fixture.context)

    assert first.dispatch_actions[fixture.dispatch_id] == "abandon"
    assert [event.type for event in second.events].count("dispatch_abandoned") == 1
    assert fixture.provider.calls == 0


@pytest.mark.unit
def test_orphan_deterministic_certification_and_acceptance_gain_one_event(
    tmp_path: Path,
) -> None:
    artifact = b"canonical source inventory\n"
    fixture = interrupted_dispatch(
        tmp_path,
        started=True,
        staging=False,
        committed=True,
        artifact_bytes=artifact,
    )
    item, certification, acceptance = _deterministic_authority(
        fixture.context.object_store,
        payload=artifact,
        item=fixture.item,
    )
    assert item == fixture.item
    fixture.context.ledger.record_certification(certification, fixture.item)
    fixture.context.ledger.record_artifact_acceptance(acceptance)

    first = recover_protocol_22_run(fixture.context)
    event_bytes = fixture.context.paths.events.read_bytes()
    second = recover_protocol_22_run(fixture.context)

    accepted = [event for event in first.events if event.type == "artifact_accepted"]
    assert len(accepted) == 1
    assert accepted[0].payload["artifact_acceptance_receipt_id"] == acceptance.identity
    assert accepted[0].payload["candidate_assessment_id"] is None
    assert second.events == first.events
    assert fixture.context.paths.events.read_bytes() == event_bytes
    assert fixture.provider.calls == 0


@pytest.mark.unit
def test_orphan_indeterminate_failure_receipt_gains_one_event(tmp_path: Path) -> None:
    fixture = interrupted_dispatch(
        tmp_path,
        started=True,
        staging=False,
        committed=False,
    )
    abandonment = fixture.context.event_store.append(
        "dispatch_abandoned",
        {
            "dispatch_id": fixture.dispatch_id,
            "execution_input_hash": fixture.prepared.execution_input_hash,
            "executor_contract_hash": fixture.item.executor_contract_hash,
            "reason_code": "execution_outcome_indeterminate",
            "work_item_id": fixture.item.work_item_id,
        },
        occurred_at=NOW,
    )
    receipt = WorkItemFailureReceiptV1(
        schema_version=1,
        work_item_id=fixture.item.work_item_id,
        dispatch_id=fixture.dispatch_id,
        candidate_id=None,
        candidate_assessment_id=None,
        execution_capture_hash=None,
        dispatch_abandonment_event_hash=abandonment.event_hash,
        failure_class="execution_indeterminate",
        reason_code="execution_outcome_indeterminate",
        normalized_diagnostics=("execution_outcome_indeterminate",),
    )
    fixture.context.ledger.record_work_item_failure(receipt)

    result = recover_protocol_22_run(fixture.context)

    failed = [event for event in result.events if event.type == "work_item_failed"]
    assert len(failed) == 1
    assert failed[0].payload["failure_receipt_id"] == receipt.identity
    assert fixture.provider.calls == 0


@pytest.mark.unit
def test_orphan_predispatch_executor_failure_gains_one_event(tmp_path: Path) -> None:
    fixture = interrupted_dispatch(
        tmp_path,
        started=False,
        staging=False,
        committed=False,
    )
    receipt = ExecutorFailureReceiptV1(
        schema_version=1,
        executor_contract_hash=fixture.item.executor_contract_hash,
        trigger_work_item_id=fixture.item.work_item_id,
        dispatch_id=None,
        candidate_id=None,
        execution_capture_hash=None,
        reason_code="reservation_mismatch",
        normalized_diagnostics=("reservation_mismatch",),
    )
    fixture.context.ledger.record_executor_failure(receipt)

    result = recover_protocol_22_run(fixture.context)

    failed = [event for event in result.events if event.type == "executor_failed"]
    assert len(failed) == 1
    assert failed[0].payload["executor_failure_receipt_id"] == receipt.identity
    assert fixture.provider.calls == 0


@pytest.mark.unit
def test_orphan_candidate_assessment_gains_one_matching_event(tmp_path: Path) -> None:
    item = work_item_v2(domain=True)
    candidate_id = digest("orphan-candidate")
    capture_hash = digest("orphan-capture")
    receipt = CandidateAssessmentReceiptV1(
        schema_version=1,
        candidate_id=candidate_id,
        work_item_id=item.work_item_id,
        execution_capture_hash=capture_hash,
        normalized_authorial_payload_hash=None,
        artifact_hash=None,
        certification_receipt_id=None,
        outcome="rejected_before_artifact",
        normalized_diagnostics=("authorial_schema_invalid",),
    )
    events = EventStore(tmp_path / "events.jsonl", protocol=PROTOCOL_22_EVENTS)
    events.append(
        "run_created",
        {"run_manifest_id": digest("run")},
        occurred_at=NOW,
    )
    events.append(
        "dispatch_leased",
        {"dispatch_id": "dispatch-orphan", "work_item_id": item.work_item_id},
        occurred_at=NOW,
    )
    events.append(
        "dispatch_started",
        {
            "active_ms_reservation": 1000,
            "attempt_index": 1,
            "attempt_kind": "initial_generation",
            "billable_token_reservation": 100,
            "dispatch_id": "dispatch-orphan",
            "execution_input_hash": digest("input"),
            "executor_contract_hash": item.executor_contract_hash,
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    events.append(
        "dispatch_observed",
        {
            "active_usage_status": "trusted_exact",
            "dispatch_id": "dispatch-orphan",
            "execution_capture_hash": capture_hash,
            "observed_active_ms": 10,
            "raw_result_contract_status": "valid",
            "reported_token_usage": 10,
            "token_usage_status": "trusted_exact",
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    events.append(
        "candidate_persisted",
        {
            "candidate_id": candidate_id,
            "candidate_inventory_hash": digest("inventory"),
            "dispatch_id": "dispatch-orphan",
            "execution_capture_hash": capture_hash,
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    empty: Mapping[str, object] = MappingProxyType({})
    ledger = Protocol22LedgerView(
        certifications=empty,
        certification_work_items=empty,
        candidate_assessments=MappingProxyType({receipt.identity: receipt}),
        accepted_artifacts=empty,
        work_item_failures=empty,
        executor_failures=empty,
        certification_records=empty,
        candidate_assessment_records=empty,
        artifact_acceptance_records=empty,
        work_item_failure_records=empty,
        executor_failure_records=empty,
    )
    context = SimpleNamespace(event_store=events, clock=lambda: NOW)

    recovery_module._reconcile_orphan_receipts(
        context,
        events.replay(),
        ledger,
        {item.work_item_id: item},
        None,
    )

    recovered = events.replay()
    rejected = [event for event in recovered if event.type == "candidate_rejected"]
    assert len(rejected) == 1
    assert rejected[0].payload["candidate_assessment_id"] == receipt.identity


@pytest.mark.unit
def test_valid_provider_candidate_can_reconstruct_a_missing_result(
    tmp_path: Path,
) -> None:
    fixture = _domain_fixture()
    item, executor, context_bytes = _authority()
    registry = _registry_from_inputs(fixture.inputs)
    dependencies = ProviderExecutionDependenciesV1(
        executor=executor,
        registry=registry,
        agent_bytes=AGENT_BYTES,
        context_bytes=context_bytes,
        response_schema_bytes=canonical_response_schema_bytes(
            item.output_key.artifact_kind
        ),
        tokenizer=_tokenizer(executor, None),
    )
    paths = create_protocol_22_run_store(
        tmp_path / "re-provider-reconstruction",
        replace(
            _input_fixture()[1],
            run_id="re-provider-reconstruction",
        ),
        _input_fixture()[0],
    )
    objects = ObjectStore(paths.objects)
    execution = Protocol22ExecutionStore(paths, objects)
    prepared = execution.prepare_execution(item, "initial_generation", dependencies)
    candidate_root = tmp_path / "provider-candidate"
    candidate_root.mkdir()
    context = load_canonical_object(
        fixture.context_bytes,
        ContextBundleV1.from_json_dict,
    )
    candidate_root.joinpath("baseline.json").write_bytes(
        canonical_json_bytes(_valid_domain_candidate(context))
    )

    captured = execution.capture_provider_result(
        prepared,
        candidate_root,
        RawExecutionResultV1(
            stdout=b"malformed result\n",
            stderr=b"",
            provider_usage=None,
            timing=RawExecutionTimingV1(
                "2026-08-22T09:00:00Z",
                "2026-08-22T09:00:01Z",
                1000,
            ),
            outcome="invalid_response",
        ),
    )
    closure = execution.validate_capture_closure(captured.commit)

    assert candidate_reconstructs_result_contract(
        item,
        closure,
        objects,
        fixture.inputs,
    )
    candidate_root.joinpath("extra.txt").write_text("extra", encoding="utf-8")
    captured_extra = execution.capture_provider_result(
        execution.prepare_execution(item, "result_contract_retry", dependencies),
        candidate_root,
        RawExecutionResultV1(
            stdout=b"malformed result\n",
            stderr=b"",
            provider_usage=None,
            timing=RawExecutionTimingV1(
                "2026-08-22T09:00:02Z",
                "2026-08-22T09:00:03Z",
                1000,
            ),
            outcome="invalid_response",
        ),
    )
    assert not candidate_reconstructs_result_contract(
        item,
        execution.validate_capture_closure(captured_extra.commit),
        objects,
        fixture.inputs,
    )


def _authority_file_bytes(root: Path) -> Mapping[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.unit
def test_pinned_authority_unavailable_is_non_mutating_and_restorable(
    tmp_path: Path,
) -> None:
    fixture = interrupted_dispatch(
        tmp_path,
        started=False,
        staging=False,
        committed=False,
    )
    exact = fixture.exact_registry
    adapter_id = fixture.dependencies.executor.adapter_id
    drifted = replace(
        exact,
        executor_implementations={
            **exact.executor_implementations,
            adapter_id: digest("drifted-installed-executor"),
        },
    )
    context = replace(fixture.context, installed_authorities=drifted)
    before = _authority_file_bytes(context.paths.root)

    unavailable = recover_protocol_22_run(context)

    assert unavailable.operational_state == "pinned_authority_unavailable"
    assert isinstance(unavailable.unavailable, PinnedAuthorityUnavailable)
    assert [
        mismatch.authority_id for mismatch in unavailable.unavailable.mismatches
    ] == [adapter_id]
    assert fixture.provider.calls == 0
    assert _authority_file_bytes(context.paths.root) == before

    restored = recover_protocol_22_run(replace(context, installed_authorities=exact))
    assert restored.operational_state == "ready"
    assert restored.dispatch_actions[fixture.dispatch_id] == "prepared"


@pytest.mark.unit
def test_recovery_is_idempotent_after_adopting_a_committed_capture(
    tmp_path: Path,
) -> None:
    fixture = interrupted_dispatch(
        tmp_path,
        started=True,
        staging=False,
        committed=True,
    )
    first = recover_protocol_22_run(fixture.context)
    event_bytes = fixture.context.paths.events.read_bytes()

    second = recover_protocol_22_run(fixture.context)

    assert second.events == first.events
    assert fixture.context.paths.events.read_bytes() == event_bytes
    assert fixture.provider.calls == 0
