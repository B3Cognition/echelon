from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

import harness.re_v2.protocol_22.execution as execution_module
from harness.re_v2.candidates import ProcessIdentity
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.baseline import (
    CompactCandidateError,
    parse_authorial_candidate,
)
from harness.re_v2.protocol_22.execution import (
    CandidateInventoryV1,
    Committed,
    Conflict,
    DeterministicExecutionDependenciesV1,
    DeterministicRawResultV1,
    InProcessDispatchReservationV1,
    Missing,
    Protocol22ExecutionError,
    Protocol22ExecutionStore,
    ProviderExecutionDependenciesV1,
    StagingReady,
)
from harness.re_v2.protocol_22.graph import (
    build_protocol_22_graph,
    instantiate_ready_item,
)
from harness.re_v2.protocol_22.model import (
    DeterministicInvocationInputV1,
    DeterministicInvocationV1,
)
from harness.re_v2.protocol_22.policies import policy_for
from harness.re_v2.protocol_22.provider import (
    RawExecutionResultV1,
    RawExecutionTimingV1,
)
from harness.re_v2.protocol_22.response_schemas import (
    canonical_response_schema_bytes,
)
from harness.re_v2.run_store import ReV2Paths
from tests.re_v2_protocol_22_fixtures import digest
from tests.unit.test_re_v2_protocol_22_executors import _registry
from tests.unit.test_re_v2_protocol_22_graph import _fixture, _template
from tests.unit.test_re_v2_protocol_22_provider import (
    AGENT_BYTES,
    _authority,
    _tokenizer,
)


RESULT_STDOUT = b"echelon_result:\n  schema_version: 1\n  outcome: candidate_ready\n"


def _store(
    tmp_path: Path,
    *,
    process_probe=None,  # type: ignore[no-untyped-def]
) -> Protocol22ExecutionStore:
    paths = ReV2Paths.for_run(tmp_path / "re-execution")
    paths.root.mkdir(parents=True)
    objects = ObjectStore(paths.objects)
    return Protocol22ExecutionStore(
        paths,
        objects,
        process_probe=process_probe,
    )


def _provider_dependencies() -> tuple[object, ProviderExecutionDependenciesV1]:
    item, executor, context = _authority()
    return item, ProviderExecutionDependenciesV1(
        executor=executor,
        registry=_registry(),
        agent_bytes=AGENT_BYTES,
        context_bytes=context,
        response_schema_bytes=canonical_response_schema_bytes(
            item.output_key.artifact_kind
        ),
        tokenizer=_tokenizer(executor, None),
    )


def _deterministic_dependencies():  # type: ignore[no-untyped-def]
    manifest, inputs = _fixture({"api": ("orders",)}, goal="inventory")
    graph = build_protocol_22_graph(manifest, inputs)
    template = _template(graph, "api", "source-inventory")
    item = instantiate_ready_item(template, {}, inputs)
    executor = inputs.executor_contract.entry_for(item.producer_family)
    workspace_bytes = canonical_json_bytes(inputs.workspace_partition.to_json_dict())
    invocation = DeterministicInvocationV1(
        schema_version=1,
        producer_family=item.producer_family,
        output_key=item.output_key,
        artifact_policy_hash=item.output_key.layer_policy_hash,
        inputs=(
            DeterministicInvocationInputV1(
                role="workspace_partition",
                object_hash=content_digest(workspace_bytes),
            ),
        ),
    )
    dependencies = DeterministicExecutionDependenciesV1(
        executor=executor,
        registry=_registry(),
        invocation=invocation,
        workspace_partition_hash=content_digest(workspace_bytes),
        referenced_objects={content_digest(workspace_bytes): workspace_bytes},
    )
    return item, dependencies


def _provider_result(
    *,
    stdout: bytes = RESULT_STDOUT,
    stderr: bytes = b"",
    usage: bytes
    | None = b'{"completion_tokens":5,"prompt_tokens":10,"total_tokens":15}\n',
    outcome: str = "candidate_ready",
) -> RawExecutionResultV1:
    return RawExecutionResultV1(
        stdout=stdout,
        stderr=stderr,
        provider_usage=usage,
        timing=RawExecutionTimingV1(
            "2026-08-22T09:00:00Z",
            "2026-08-22T09:00:01Z",
            1000,
        ),
        outcome=outcome,  # type: ignore[arg-type]
    )


def _candidate_root(tmp_path: Path, payload: bytes | None = b'{"ok":true}') -> Path:
    root = tmp_path / "candidate"
    root.mkdir(parents=True)
    if payload is not None:
        (root / "baseline.json").write_bytes(payload)
        (root / "baseline.json").chmod(0o600)
    return root


def _object_path(objects: ObjectStore, object_hash: str) -> Path:
    suffix = object_hash.removeprefix("sha256:")
    return objects.root / "sha256" / suffix[:2] / suffix[2:]


def test_provider_input_persists_envelope_before_execution_input(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    boundaries: list[str] = []

    prepared = store.prepare_execution(
        item,
        "initial_generation",
        dependencies,
        boundaries.append,
    )

    assert boundaries.index("provider_envelope_fsynced") < boundaries.index(
        "execution_input_fsynced"
    )
    assert prepared.execution_input.provider_request_envelope_hash is not None
    assert prepared.execution_input.deterministic_invocation is None
    assert prepared.provider_envelope_hash == (
        prepared.execution_input.provider_request_envelope_hash
    )
    assert store.object_store.read_blob(prepared.execution_input_hash) == (
        canonical_json_bytes(prepared.execution_input.to_json_dict())
    )


def test_deterministic_input_persists_closed_invocation_and_zero_token_reservation(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _deterministic_dependencies()
    boundaries: list[str] = []

    prepared = store.prepare_execution(
        item,
        "initial_generation",
        dependencies,
        boundaries.append,
    )

    invocation = prepared.execution_input.deterministic_invocation
    assert invocation is not None
    assert tuple(value.role for value in invocation.inputs) == ("workspace_partition",)
    assert prepared.execution_input.agent_contract_hash is None
    assert prepared.execution_input.context_bundle_hash is None
    assert prepared.execution_input.provider_request_envelope_hash is None
    assert prepared.provider_envelope_hash is None
    assert prepared.reservation == InProcessDispatchReservationV1(
        billable_tokens=0,
        active_ms=dependencies.executor.limits.max_active_ms_per_dispatch,
    )
    assert boundaries.index("deterministic_invocation_fsynced") < boundaries.index(
        "execution_input_fsynced"
    )
    assert store.object_store.read_blob(invocation.identity) == canonical_json_bytes(
        invocation.to_json_dict()
    )


def test_prepare_reuses_the_same_unstarted_dispatch_identity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()

    first = store.prepare_execution(item, "initial_generation", dependencies)
    second = store.prepare_execution(item, "initial_generation", dependencies)

    assert second == first
    assert isinstance(store.capture_state(first.dispatch_id), Missing)


def test_deterministic_invocation_rejects_missing_or_unknown_roles(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _deterministic_dependencies()
    empty = replace(
        dependencies,
        invocation=replace(dependencies.invocation, inputs=()),
    )
    unknown = replace(
        dependencies,
        invocation=replace(
            dependencies.invocation,
            inputs=(
                DeterministicInvocationInputV1(
                    "mutable_default",
                    dependencies.invocation.inputs[0].object_hash,
                ),
            ),
        ),
    )

    with pytest.raises(Protocol22ExecutionError, match="invocation roles"):
        store.prepare_execution(item, "initial_generation", empty)
    with pytest.raises(Protocol22ExecutionError, match="invocation roles"):
        store.prepare_execution(item, "initial_generation", unknown)


def test_l0_invocation_must_name_the_pinned_workspace_partition(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _deterministic_dependencies()
    other_payload = b'{"workspace":"other"}\n'
    other_hash = content_digest(other_payload)
    changed = replace(
        dependencies,
        invocation=replace(
            dependencies.invocation,
            inputs=(
                DeterministicInvocationInputV1(
                    "workspace_partition",
                    other_hash,
                ),
            ),
        ),
        referenced_objects={other_hash: other_payload},
    )

    with pytest.raises(Protocol22ExecutionError, match="workspace partition"):
        store.prepare_execution(item, "initial_generation", changed)


def test_started_lease_revalidates_authority_and_is_no_clobber(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, process_probe=lambda _pid: "stable-start")
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    process = ProcessIdentity(
        pid=os.getpid(),
        process_start_identity="stable-start",
        command_hash=digest("controller-command"),
        provider_identity=digest("provider-instance"),
        started_at="2026-08-22T09:00:00Z",
    )

    first = store.record_started_lease(
        prepared,
        item,
        dependencies,
        process,
    )
    second = store.record_started_lease(
        prepared,
        item,
        dependencies,
        process,
    )

    assert first == second
    assert store.load_started_lease(prepared.dispatch_id) == first
    drifted_registry = replace(
        dependencies.registry,
        executor_implementations={
            **dependencies.registry.executor_implementations,
            dependencies.executor.adapter_id: digest("drifted executor"),
        },
    )
    with pytest.raises(Protocol22ExecutionError, match="installed authority"):
        store.record_started_lease(
            prepared,
            item,
            replace(dependencies, registry=drifted_registry),
            process,
        )
    assert store.load_started_lease(prepared.dispatch_id) == first


def test_prepared_validation_never_recreates_missing_schema_authority(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    schema_hash = content_digest(dependencies.response_schema_bytes)
    schema_path = _object_path(store.object_store, schema_hash)
    schema_path.unlink()

    with pytest.raises(Protocol22ExecutionError, match="schema"):
        store.validate_prepared_execution(prepared, item, dependencies)

    assert not schema_path.exists()


def test_capture_requires_the_durable_prepared_input_closure(tmp_path: Path) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    _object_path(store.object_store, prepared.execution_input_hash).unlink()

    with pytest.raises(Protocol22ExecutionError, match="prepared execution"):
        store.capture_provider_result(
            prepared,
            _candidate_root(tmp_path),
            _provider_result(),
        )


def test_provider_capture_persists_regular_candidate_stdout_usage_and_closure(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    payload = b'{"schema_version":1,"surfaces":{},"unknowns":[]}'

    captured = store.capture_provider_result(
        prepared,
        _candidate_root(tmp_path, payload),
        _provider_result(),
    )
    closure = store.validate_capture_closure(captured.commit)

    assert closure.capture == captured.capture
    assert closure.stdout_bytes == RESULT_STDOUT
    assert closure.provider_usage_bytes == _provider_result().provider_usage
    assert closure.candidate_inventory is not None
    assert closure.candidate_inventory.entries[0].to_json_dict() == {
        "relative_path": "baseline.json",
        "object_kind": "regular",
        "mode": 0o600,
        "byte_count": len(payload),
        "content_hash": content_digest(payload),
    }
    assert store.object_store.read_blob(content_digest(payload)) == payload
    assert captured.capture.resolved_model_revision == (
        dependencies.executor.model.model_revision
    )


def test_empty_api_candidate_inventory_is_still_durable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    result = _provider_result(
        stdout=b"",
        stderr=b"invalid_response\n",
        outcome="invalid_response",
    )

    captured = store.capture_provider_result(
        prepared,
        _candidate_root(tmp_path, None),
        result,
    )
    closure = store.validate_capture_closure(captured.commit)

    assert closure.candidate_inventory == CandidateInventoryV1(
        schema_version=1,
        dispatch_id=prepared.dispatch_id,
        work_item_id=item.work_item_id,
        entries=(),
    )
    assert captured.capture.result_kind == "provider_candidate"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unavailable")
def test_symlink_and_special_candidate_entries_are_recorded_without_following(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    root = _candidate_root(tmp_path, None)
    outside = tmp_path / "outside-secret"
    outside.write_text("do not ingest", encoding="utf-8")
    (root / "linked").symlink_to(outside)
    os.mkfifo(root / "pipe")
    result = _provider_result(
        stdout=b"",
        stderr=b"invalid_response\n",
        outcome="invalid_response",
    )

    captured = store.capture_provider_result(prepared, root, result)
    inventory = store.validate_capture_closure(captured.commit).candidate_inventory

    assert inventory is not None
    assert tuple(
        (entry.relative_path, entry.object_kind) for entry in inventory.entries
    ) == (
        ("linked", "symlink"),
        ("pipe", "special"),
    )
    assert all(entry.content_hash is None for entry in inventory.entries)
    assert all(entry.byte_count == 0 for entry in inventory.entries)


@pytest.mark.parametrize("stdout_size", (128 * 1024, 128 * 1024 + 1))
def test_stdout_capture_is_complete_or_exact_terminal_tail(
    tmp_path: Path,
    stdout_size: int,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    stdout = b"x" * stdout_size
    result = _provider_result(
        stdout=stdout,
        stderr=b"invalid_response\n",
        outcome="invalid_response",
    )

    captured = store.capture_provider_result(
        prepared,
        _candidate_root(tmp_path, None),
        result,
    )
    closure = store.validate_capture_closure(captured.commit)

    expected = "complete" if stdout_size == 128 * 1024 else "terminal_tail"
    assert captured.capture.stdout_capture == expected
    assert closure.stdout_bytes == stdout[-128 * 1024 :]
    assert captured.capture.stdout_digest == content_digest(stdout)
    assert captured.capture.output_truncated == (expected == "terminal_tail")


def test_missing_stdout_or_usage_blob_invalidates_capture_closure(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    captured = store.capture_provider_result(
        prepared,
        _candidate_root(tmp_path),
        _provider_result(),
    )

    _object_path(store.object_store, captured.capture.stdout_blob_hash).unlink()
    with pytest.raises(Protocol22ExecutionError, match="stdout"):
        store.validate_capture_closure(captured.commit)

    captured = store.capture_provider_result(
        store.prepare_execution(
            item,
            "artifact_contract_retry",
            replace(
                dependencies,
                retry_diagnostics=("authorial_schema_invalid",),
            ),
        ),
        _candidate_root(tmp_path / "retry"),
        _provider_result(),
    )
    usage_hash = captured.capture.provider_usage_blob_hash
    assert usage_hash is not None
    _object_path(store.object_store, usage_hash).unlink()
    with pytest.raises(Protocol22ExecutionError, match="usage"):
        store.validate_capture_closure(captured.commit)


def test_deterministic_capture_has_no_candidate_or_provider_metadata(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _deterministic_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    artifact = b'{"schema_version":1}\n'
    result = DeterministicRawResultV1(
        artifact_bytes=artifact,
        stdout=b"",
        stderr=b"",
        started_at="2026-08-22T09:00:00Z",
        ended_at="2026-08-22T09:00:00.010Z",
        duration_ms=10,
        exit_code=0,
        timed_out=False,
    )

    captured = store.capture_deterministic_result(prepared, result)
    closure = store.validate_capture_closure(captured.commit)

    assert closure.deterministic_artifact_bytes == artifact
    assert closure.candidate_inventory is None
    assert closure.provider_envelope is None
    assert closure.provider_usage_bytes is None
    assert captured.capture.result_kind == "deterministic_artifact"
    assert captured.capture.resolved_model_revision is None


def test_deterministic_failure_capture_has_no_artifact(tmp_path: Path) -> None:
    store = _store(tmp_path)
    item, dependencies = _deterministic_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    result = DeterministicRawResultV1(
        artifact_bytes=None,
        stdout=b"",
        stderr=b"producer failed",
        started_at="2026-08-22T09:00:00Z",
        ended_at="2026-08-22T09:00:00.010Z",
        duration_ms=10,
        exit_code=1,
        timed_out=False,
    )

    captured = store.capture_deterministic_result(prepared, result)
    closure = store.validate_capture_closure(captured.commit)

    assert captured.capture.result_kind == "none"
    assert captured.capture.deterministic_artifact_hash is None
    assert closure.deterministic_artifact_bytes is None


def test_capture_timestamps_must_be_monotonic_in_wall_order(tmp_path: Path) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    result = replace(
        _provider_result(),
        timing=RawExecutionTimingV1(
            "2026-08-22T09:00:02Z",
            "2026-08-22T09:00:01Z",
            1000,
        ),
    )

    with pytest.raises(Protocol22ExecutionError, match="timeline"):
        store.capture_provider_result(
            prepared,
            _candidate_root(tmp_path),
            result,
        )


def test_capture_commit_fault_leaves_adoptable_staging_then_commits_idempotently(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    captured = store.capture_provider_result(
        prepared,
        _candidate_root(tmp_path),
        _provider_result(),
    )
    seen: list[str] = []

    def stop_after_ready(boundary: str) -> None:
        seen.append(boundary)
        if boundary == "capture_staging_ready_fsynced":
            raise RuntimeError("crash after ready")

    with pytest.raises(RuntimeError, match="crash after ready"):
        store.commit_capture(captured, stop_after_ready)

    staged = store.capture_state(prepared.dispatch_id)
    assert isinstance(staged, StagingReady)
    committed = store.commit_capture(captured)
    assert isinstance(committed, Committed)
    assert store.commit_capture(captured) == committed
    assert isinstance(store.capture_state(prepared.dispatch_id), Committed)
    assert seen == ["capture_staging_ready_fsynced"]


def test_incomplete_and_unsafe_staging_are_distinct_read_only_states(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    staging = store.staging_root / prepared.dispatch_id
    staging.mkdir()

    incomplete = store.capture_state(prepared.dispatch_id)
    assert isinstance(incomplete, Missing)
    assert incomplete.incomplete_staging is True

    staging.rmdir()
    outside = tmp_path / "outside-staging"
    outside.mkdir()
    staging.symlink_to(outside, target_is_directory=True)
    unsafe = store.capture_state(prepared.dispatch_id)
    assert isinstance(unsafe, Conflict)
    assert "unsafe staging" in unsafe.reason


def test_committed_capture_is_never_clobbered_by_conflicting_bytes(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    captured = store.capture_provider_result(
        prepared,
        _candidate_root(tmp_path),
        _provider_result(),
    )
    committed = store.commit_capture(captured)
    committed.path.unlink()
    committed.path.write_bytes(b'{"conflict":true}\n')
    conflict_bytes = committed.path.read_bytes()

    with pytest.raises(Protocol22ExecutionError, match="conflicting.*commit"):
        store.commit_capture(captured)

    assert committed.path.read_bytes() == conflict_bytes


def test_capture_closure_rejects_resolved_revision_mismatch(tmp_path: Path) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    captured = store.capture_provider_result(
        prepared,
        _candidate_root(tmp_path),
        _provider_result(),
    )
    wrong_capture = replace(
        captured.capture,
        resolved_model_revision="gpt-different-2026-08-01",
    )
    wrong_hash = store.object_store.put_blob(
        canonical_json_bytes(wrong_capture.to_json_dict())
    )
    wrong_commit = replace(captured.commit, execution_capture_hash=wrong_hash)

    with pytest.raises(Protocol22ExecutionError, match="revision"):
        store.validate_capture_closure(wrong_commit)


def test_capture_closure_rejects_provider_and_timeline_mismatch(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    captured = store.capture_provider_result(
        prepared,
        _candidate_root(tmp_path),
        _provider_result(),
    )
    mutations = (
        (
            replace(captured.capture, provider_name="different-provider"),
            "provider",
        ),
        (
            replace(
                captured.capture,
                started_at="2026-08-22T09:00:02Z",
                ended_at="2026-08-22T09:00:01Z",
            ),
            "timeline",
        ),
    )

    for changed_capture, message in mutations:
        changed_hash = store.object_store.put_blob(
            canonical_json_bytes(changed_capture.to_json_dict())
        )
        changed_commit = replace(
            captured.commit,
            execution_capture_hash=changed_hash,
        )
        with pytest.raises(Protocol22ExecutionError, match=message):
            store.validate_capture_closure(changed_commit)


def test_fsync_failure_cannot_publish_committed_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    captured = store.capture_provider_result(
        prepared,
        _candidate_root(tmp_path),
        _provider_result(),
    )
    real_fsync = execution_module.os.fsync
    failed = False

    def fail_once(fd: int) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("injected fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(execution_module.os, "fsync", fail_once)
    with pytest.raises(Protocol22ExecutionError, match="commit capture"):
        store.commit_capture(captured)

    assert failed
    assert isinstance(store.capture_state(prepared.dispatch_id), Missing)


def test_candidate_id_has_no_path_or_timestamp(tmp_path: Path) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    captured = store.capture_provider_result(
        prepared,
        _candidate_root(tmp_path),
        _provider_result(),
    )
    committed = store.commit_capture(captured)

    candidate = store.persist_candidate(committed)

    assert set(candidate.to_json_dict()) == {
        "schema_version",
        "dispatch_id",
        "work_item_id",
        "execution_capture_hash",
        "candidate_inventory_hash",
    }
    assert candidate.candidate_id == content_digest(candidate.to_json_dict())
    assert store.object_store.read_blob(candidate.candidate_id) == (
        canonical_json_bytes(candidate.to_json_dict())
    )


def test_oversized_raw_candidate_is_preserved_then_rejected_before_parsing(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    policy = policy_for(
        _fixture({"api": ("orders",)})[1].artifact_policy,
        "L1",
        item.output_key.artifact_kind,
    )
    raw_limit = (
        policy.policy_parameters.raw_candidate_size_multiplier
        * policy.max_canonical_json_bytes
    )
    payload = b"{" + b"x" * raw_limit + b"}"
    captured = store.capture_provider_result(
        prepared,
        _candidate_root(tmp_path, payload),
        _provider_result(),
    )
    closure = store.validate_capture_closure(captured.commit)
    entry = closure.candidate_inventory.entries[0]  # type: ignore[union-attr]

    assert store.object_store.read_blob(entry.content_hash or "") == payload
    with pytest.raises(CompactCandidateError, match="pre-parse size"):
        parse_authorial_candidate(payload, item.output_key.artifact_kind, policy)


def test_execution_and_capture_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    captured = store.capture_provider_result(
        prepared,
        _candidate_root(tmp_path),
        _provider_result(),
    )
    with pytest.raises(Protocol22ExecutionError, match="capture.*identity"):
        replace(
            captured,
            capture=replace(captured.capture, dispatch_id="different-dispatch"),
        )


def test_provider_usage_must_be_canonical_json_before_capture(tmp_path: Path) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    result = _provider_result(usage=b'{"prompt_tokens": 1}\n')

    with pytest.raises(Protocol22ExecutionError, match="usage.*canonical"):
        store.capture_provider_result(
            prepared,
            _candidate_root(tmp_path),
            result,
        )


def test_staging_and_commit_files_use_closed_canonical_schema_and_mode(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    item, dependencies = _provider_dependencies()
    prepared = store.prepare_execution(item, "initial_generation", dependencies)
    captured = store.capture_provider_result(
        prepared,
        _candidate_root(tmp_path),
        _provider_result(),
    )
    committed = store.commit_capture(captured)

    ready = store.staging_root / prepared.dispatch_id / "ready.json"
    assert ready.read_bytes() == committed.path.read_bytes()
    assert json.loads(ready.read_bytes()) == captured.commit.to_json_dict()
    assert ready.stat().st_ino == committed.path.stat().st_ino
    assert ready.stat().st_mode & 0o7777 == 0o400
    assert committed.path.stat().st_mode & 0o7777 == 0o400
