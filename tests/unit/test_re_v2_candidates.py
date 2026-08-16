from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import stat

import pytest

from harness.re_v2.candidates import (
    CandidateStore,
    ProcessIdentity,
    ReV2CandidateError,
)
from harness.re_v2.canonical import content_digest
from harness.re_v2.model import ArtifactKey, ExecutionObservation, WorkItem
from harness.re_v2.run_store import ReV2Paths


NOW = "2026-08-14T12:00:00Z"


def work_item() -> WorkItem:
    output_key = ArtifactKey(
        source_snapshot_id=content_digest(b"source"),
        partition_manifest_id=content_digest(b"partitions"),
        artifact_kind="fixture",
        layer="L1",
        producer_protocol_version="v1",
        layer_policy_hash=content_digest(b"policy"),
        dependency_hashes=(),
    )
    return WorkItem(
        template_id="fixture-template",
        goal_id="fixture-goal",
        output_key=output_key,
        required_artifact_hashes=(),
        producer_id="fixture-provider",
        producer_protocol_version="v1",
        verifier_id="fixture-verifier",
        verifier_version="v1",
        result_contract_id="fixture-result-v1",
        max_provider_attempts=2,
        max_generation_attempts=2,
        max_semantic_rounds=1,
        max_result_contract_retries=1,
    )


def process_identity() -> ProcessIdentity:
    return ProcessIdentity(
        pid=1234,
        process_start_identity="linux-start-987",
        command_hash=content_digest(b"provider --run"),
        provider_identity=content_digest(b"fixture-provider-v1"),
        started_at=NOW,
    )


def observation(*, result_contract_valid: bool = True) -> ExecutionObservation:
    return ExecutionObservation(
        started_at=NOW,
        ended_at="2026-08-14T12:00:01Z",
        duration_ms=1_000,
        exit_code=0,
        timed_out=False,
        output_truncated=False,
        result_contract_valid=result_contract_valid,
        token_usage=12,
        provider_name="fixture",
        model_name="fixture-model",
        stderr_digest=None,
    )


def candidate_store(tmp_path: Path) -> CandidateStore:
    paths = ReV2Paths.for_run(tmp_path / "run")
    paths.root.mkdir(parents=True)
    return CandidateStore(paths)


def fixture_output(tmp_path: Path) -> Path:
    output = tmp_path / "output"
    output.mkdir()
    (output / "artifact.md").write_text("durable provider bytes\n", encoding="utf-8")
    return output


def different_item() -> WorkItem:
    item = work_item()
    return replace(item, goal_id="different-goal")


def test_complete_candidate_survives_missing_result_object(tmp_path: Path) -> None:
    store = candidate_store(tmp_path)
    lease = store.begin(work_item(), process_identity())
    candidate = store.persist(
        lease,
        fixture_output(tmp_path),
        observation(result_contract_valid=False),
    )

    assert store.discover() == (candidate,)
    assert candidate.observation.result_contract_valid is False


def test_candidate_store_rejects_symlink_payload(tmp_path: Path) -> None:
    store = candidate_store(tmp_path)
    lease = store.begin(work_item(), process_identity())
    output = tmp_path / "output"
    output.mkdir()
    (output / "escape").symlink_to(tmp_path)

    with pytest.raises(ReV2CandidateError, match="symlink"):
        store.persist(lease, output, observation())


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"pid": 0}, "pid"),
        ({"process_start_identity": "../start"}, "process_start_identity"),
        ({"command_hash": "not-a-hash"}, "command_hash"),
        ({"provider_identity": "not-a-hash"}, "provider_identity"),
        ({"started_at": "yesterday"}, "started_at"),
    ],
)
def test_process_identity_rejects_ambiguous_or_unvalidated_fields(
    change: dict[str, object], message: str
) -> None:
    values = {
        "pid": 1234,
        "process_start_identity": "linux-start-987",
        "command_hash": content_digest(b"provider --run"),
        "provider_identity": content_digest(b"fixture-provider-v1"),
        "started_at": NOW,
    }
    values.update(change)

    with pytest.raises(ReV2CandidateError, match=message):
        ProcessIdentity(**values)  # type: ignore[arg-type]


def test_begin_is_exactly_idempotent_and_conflicts_fail_closed(tmp_path: Path) -> None:
    store = candidate_store(tmp_path)
    first = store.begin(work_item(), process_identity(), dispatch_id="dispatch-fixed")

    assert store.begin(work_item(), process_identity(), dispatch_id="dispatch-fixed") == first
    with pytest.raises(ReV2CandidateError, match="conflicting lease"):
        store.begin(different_item(), process_identity(), dispatch_id="dispatch-fixed")
    changed_process = replace(process_identity(), pid=5678)
    with pytest.raises(ReV2CandidateError, match="conflicting lease"):
        store.begin(work_item(), changed_process, dispatch_id="dispatch-fixed")


def test_begin_fault_leaves_one_complete_idempotent_lease(tmp_path: Path) -> None:
    boundaries: list[str] = []

    def fail(boundary: str) -> None:
        boundaries.append(boundary)
        if boundary == "lease_written":
            raise RuntimeError("crash")

    paths = ReV2Paths.for_run(tmp_path / "run")
    paths.root.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="crash"):
        CandidateStore(paths, fault_hook=fail).begin(
            work_item(), process_identity(), dispatch_id="dispatch-fixed"
        )

    lease = CandidateStore(paths).begin(
        work_item(), process_identity(), dispatch_id="dispatch-fixed"
    )
    assert lease.dispatch_id == "dispatch-fixed"
    assert boundaries == ["lease_written"]


def test_begin_rejects_a_lease_timestamp_before_process_start(tmp_path: Path) -> None:
    store = candidate_store(tmp_path)

    with pytest.raises(ReV2CandidateError, match="precedes process start"):
        store.begin(
            work_item(),
            process_identity(),
            dispatch_id="dispatch-fixed",
            leased_at="2026-08-14T11:59:59Z",
        )


def test_persist_requires_the_exact_active_lease(tmp_path: Path) -> None:
    store = candidate_store(tmp_path)
    lease = store.begin(work_item(), process_identity(), dispatch_id="dispatch-fixed")
    other = different_item()
    changed = replace(lease, work_item=other, work_item_id=other.work_item_id)

    with pytest.raises(ReV2CandidateError, match="active lease"):
        store.persist(changed, fixture_output(tmp_path), observation())


def test_persist_rejects_source_mutation_after_copy(tmp_path: Path) -> None:
    output = fixture_output(tmp_path)

    def mutate(boundary: str) -> None:
        if boundary == "payload_copied":
            (output / "artifact.md").write_text("mutated\n", encoding="utf-8")

    paths = ReV2Paths.for_run(tmp_path / "run")
    paths.root.mkdir(parents=True)
    store = CandidateStore(paths, fault_hook=mutate)
    lease = store.begin(work_item(), process_identity())

    with pytest.raises(ReV2CandidateError, match="changed"):
        store.persist(lease, output, observation())
    assert CandidateStore(paths).discover() == ()


def test_persist_rejects_an_output_with_a_symlinked_parent(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    output = real_parent / "output"
    output.mkdir()
    (output / "artifact.md").write_text("bytes\n", encoding="utf-8")
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    store = candidate_store(tmp_path)
    lease = store.begin(work_item(), process_identity())

    with pytest.raises(ReV2CandidateError, match="symlinked parent"):
        store.persist(lease, linked_parent / "output", observation())


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unavailable")
def test_persist_rejects_special_payload_files(tmp_path: Path) -> None:
    store = candidate_store(tmp_path)
    lease = store.begin(work_item(), process_identity())
    output = tmp_path / "output"
    output.mkdir()
    os.mkfifo(output / "pipe")

    with pytest.raises(ReV2CandidateError, match="special file"):
        store.persist(lease, output, observation())


@pytest.mark.parametrize(
    ("boundary", "expected_count"),
    [
        ("payload_copied", 0),
        ("metadata_fsynced", 0),
        ("candidate_renamed", 1),
    ],
)
def test_fault_boundaries_expose_zero_or_one_complete_candidate(
    tmp_path: Path, boundary: str, expected_count: int
) -> None:
    paths = ReV2Paths.for_run(tmp_path / "run")
    paths.root.mkdir(parents=True)
    base = CandidateStore(paths)
    lease = base.begin(work_item(), process_identity())

    def fail(observed: str) -> None:
        if observed == boundary:
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        CandidateStore(paths, fault_hook=fail).persist(
            lease, fixture_output(tmp_path), observation()
        )

    candidates = base.discover()
    assert len(candidates) == expected_count
    if candidates:
        assert (candidates[0].payload_path / "artifact.md").read_bytes() == b"durable provider bytes\n"


def test_retry_after_candidate_rename_recognizes_exact_candidate(tmp_path: Path) -> None:
    paths = ReV2Paths.for_run(tmp_path / "run")
    paths.root.mkdir(parents=True)
    base = CandidateStore(paths)
    lease = base.begin(work_item(), process_identity())
    output = fixture_output(tmp_path)

    def fail(boundary: str) -> None:
        if boundary == "candidate_renamed":
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        CandidateStore(paths, fault_hook=fail).persist(lease, output, observation())

    discovered = base.discover()[0]
    assert base.persist(lease, output, observation()) == discovered


def test_discovery_ignores_private_work_areas_and_sorts_candidates(tmp_path: Path) -> None:
    store = candidate_store(tmp_path)
    output_one = fixture_output(tmp_path)
    first = store.persist(
        store.begin(work_item(), process_identity(), dispatch_id="dispatch-z"),
        output_one,
        observation(),
    )
    output_one.rename(tmp_path / "used-output")
    output_two = fixture_output(tmp_path)
    second = store.persist(
        store.begin(work_item(), replace(process_identity(), pid=5678), dispatch_id="dispatch-a"),
        output_two,
        observation(),
    )
    (store.paths.candidates / ".abandoned.tmp").mkdir()

    assert store.discover() == (second, first)


@pytest.mark.parametrize("mutation", ["content", "extra", "missing", "mode"])
def test_discovery_fails_closed_on_any_payload_mutation(
    tmp_path: Path, mutation: str
) -> None:
    store = candidate_store(tmp_path)
    lease = store.begin(work_item(), process_identity())
    candidate = store.persist(lease, fixture_output(tmp_path), observation())
    payload = candidate.payload_path / "artifact.md"
    candidate.path.chmod(0o700)
    candidate.payload_path.chmod(0o700)
    if mutation == "content":
        payload.chmod(0o600)
        payload.write_text("changed but same mode restored\n", encoding="utf-8")
        payload.chmod(0o644)
    elif mutation == "extra":
        (candidate.payload_path / "extra").write_text("extra", encoding="utf-8")
    elif mutation == "missing":
        payload.unlink()
    else:
        payload.chmod(0o600)

    with pytest.raises(ReV2CandidateError, match="hash mismatch|extra|missing|mode mismatch"):
        store.discover()


def test_discovery_fails_closed_on_malformed_published_candidate(tmp_path: Path) -> None:
    store = candidate_store(tmp_path)
    malformed = store.paths.candidates / "dispatch-malformed"
    malformed.mkdir()
    (malformed / "metadata.json").write_text(json.dumps({"schema_version": 1}))

    with pytest.raises(ReV2CandidateError, match="malformed|invalid|missing"):
        store.discover()


def test_discovery_verifies_every_canonical_metadata_field(tmp_path: Path) -> None:
    store = candidate_store(tmp_path)
    candidate = store.persist(
        store.begin(work_item(), process_identity()),
        fixture_output(tmp_path),
        observation(),
    )
    metadata_path = candidate.path / "metadata.json"
    candidate.path.chmod(0o700)
    metadata_path.chmod(0o600)
    metadata = json.loads(metadata_path.read_bytes())
    metadata["observation_hash"] = content_digest(b"different observation")
    metadata_path.write_bytes(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    metadata_path.chmod(0o400)
    candidate.path.chmod(0o500)

    with pytest.raises(ReV2CandidateError, match="metadata|identity"):
        store.discover()


def test_store_rejects_external_or_symlinked_candidate_roots(tmp_path: Path) -> None:
    paths = ReV2Paths.for_run(tmp_path / "run")
    paths.root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = replace(paths, candidates=outside)
    with pytest.raises(ReV2CandidateError, match="candidates path"):
        CandidateStore(escaped)

    paths.candidates.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ReV2CandidateError, match="symlink"):
        CandidateStore(paths)


def test_store_rejects_symlinked_lease_and_published_targets(tmp_path: Path) -> None:
    paths = ReV2Paths.for_run(tmp_path / "run")
    paths.root.mkdir(parents=True)
    paths.candidates.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (paths.candidates / ".leases").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ReV2CandidateError, match="symlink"):
        CandidateStore(paths).begin(work_item(), process_identity())

    (paths.candidates / ".leases").unlink()
    store = CandidateStore(paths)
    (paths.candidates / "dispatch-fixed").symlink_to(outside, target_is_directory=True)
    lease = store.begin(work_item(), process_identity(), dispatch_id="dispatch-fixed")
    with pytest.raises(ReV2CandidateError, match="symlink|already exists"):
        store.persist(lease, fixture_output(tmp_path), observation())


def test_candidate_preserves_nested_inventory_and_is_immutable(tmp_path: Path) -> None:
    store = candidate_store(tmp_path)
    lease = store.begin(work_item(), process_identity())
    output = fixture_output(tmp_path)
    nested = output / "nested"
    nested.mkdir(mode=0o750)
    script = nested / "tool.sh"
    script.write_bytes(b"#!/bin/sh\n")
    script.chmod(0o755)
    empty = output / "empty"
    empty.mkdir(mode=0o711)

    candidate = store.persist(lease, output, observation())

    assert tuple(entry.path for entry in candidate.inventory) == (
        "artifact.md",
        "empty",
        "nested",
        "nested/tool.sh",
    )
    assert stat.S_IMODE((candidate.payload_path / "nested/tool.sh").stat().st_mode) == 0o555
    assert stat.S_IMODE(candidate.path.stat().st_mode) & stat.S_IWUSR == 0
    assert store.discover() == (candidate,)
