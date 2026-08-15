from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.ledger import (
    CertificationDecision,
    LEDGER_SCHEMA_VERSION,
    Ledger,
    ObjectStore,
    ReV2LedgerError,
    TREE_OBJECT_MAGIC,
)
from harness.re_v2.model import (
    ArtifactKey,
    ArtifactReceipt,
    BudgetPolicy,
    CertificationKey,
    CertificationReceipt,
    RunManifest,
    WorkItem,
)
from harness.re_v2.run_store import create_run_store


NOW = "2026-08-14T12:00:00Z"
LATER = "2026-08-14T12:00:01Z"


def digest(value: str) -> str:
    return content_digest(value.encode())


def work_item() -> WorkItem:
    output_key = ArtifactKey(
        source_snapshot_id=digest("source"),
        partition_manifest_id=digest("partitions"),
        artifact_kind="inventory",
        layer="L0",
        producer_protocol_version="v1",
        layer_policy_hash=digest("policy"),
        dependency_hashes=(),
    )
    return WorkItem(
        template_id="inventory-template",
        goal_id="inventory",
        output_key=output_key,
        required_artifact_hashes=(),
        producer_id="fixture-producer",
        producer_protocol_version="v1",
        verifier_id="fixture-verifier",
        verifier_version="v1",
        result_contract_id="fixture-result-v1",
        max_provider_attempts=1,
        max_generation_attempts=1,
        max_semantic_rounds=0,
        max_result_contract_retries=0,
    )


@dataclass(frozen=True)
class FixtureCandidate:
    candidate_id: str
    artifact_hash: str
    provider_verdict: str


class DeterministicFixtureCertifier:
    verifier_id = "fixture-verifier"
    verifier_version = "v1"

    def certify(
        self, candidate: FixtureCandidate, item: WorkItem
    ) -> CertificationDecision:
        certification = CertificationReceipt(
            certification_key=CertificationKey(
                artifact_hash=candidate.artifact_hash,
                verifier_id=self.verifier_id,
                verifier_version=self.verifier_version,
                source_snapshot_id=item.output_key.source_snapshot_id,
                audit_epoch_id=None,
            ),
            candidate_id=candidate.candidate_id,
            work_item_id=item.work_item_id,
            verdict="accepted",
            normalized_diagnostics=(),
            evidence_references=(),
            scope_verified=True,
            certified_at=NOW,
        )
        artifact = ArtifactReceipt(
            artifact_key=item.output_key,
            artifact_hash=candidate.artifact_hash,
            certification_id=certification.identity,
            candidate_id=candidate.candidate_id,
            work_item_id=item.work_item_id,
            accepted_at=LATER,
        )
        return CertificationDecision(certification, artifact)


def make_ledger(tmp_path: Path) -> tuple[Ledger, ObjectStore]:
    objects = ObjectStore(tmp_path / "objects")
    return (
        Ledger(
            tmp_path / "ledger.jsonl",
            objects,
            supported_verifiers={"fixture-verifier": "v1"},
            pinned_source_snapshot_id=digest("source"),
        ),
        objects,
    )


def object_path(objects: ObjectStore, object_hash: str) -> Path:
    suffix = object_hash.removeprefix("sha256:")
    return objects.root / "sha256" / suffix[:2] / suffix[2:]


def write_raw_object(objects: ObjectStore, payload: bytes) -> str:
    """Install an adversarial on-disk object without using the safe public API."""
    object_hash = content_digest(payload)
    path = object_path(objects, object_hash)
    path.parent.mkdir()
    path.write_bytes(payload)
    return object_hash


def accepted_receipts(
    objects: ObjectStore,
    *,
    payload: bytes = b"candidate output",
    candidate_id: str = "candidate-1",
    item: WorkItem | None = None,
) -> tuple[CertificationReceipt, ArtifactReceipt]:
    selected = item or work_item()
    candidate = FixtureCandidate(
        candidate_id, objects.put_blob(payload), "provider-field-is-untrusted"
    )
    decision = DeterministicFixtureCertifier().certify(candidate, selected)
    assert decision.artifact_receipt is not None
    return decision.certification_receipt, decision.artifact_receipt


def test_provider_verdict_cannot_accept_an_artifact(tmp_path: Path) -> None:
    ledger, objects = make_ledger(tmp_path)
    artifact_hash = objects.put_blob(b"candidate output")
    candidate = FixtureCandidate("candidate-1", artifact_hash, "PASS")

    assert ledger.replay().accepted_artifacts == {}

    decision = DeterministicFixtureCertifier().certify(candidate, work_item())
    ledger.record_certification(decision.certification_receipt, work_item())
    assert decision.artifact_receipt is not None
    ledger.record_artifact(decision.artifact_receipt)

    assert work_item().output_key.identity in ledger.replay().accepted_artifacts


def test_tree_object_rejects_symlinks(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "escape").symlink_to(tmp_path)

    with pytest.raises(ReV2LedgerError, match="symlink"):
        ObjectStore(tmp_path / "objects").put_tree(tree)


def test_blob_is_published_at_its_content_address_and_existing_bytes_are_verified(
    tmp_path: Path,
) -> None:
    objects = ObjectStore(tmp_path / "objects")
    payload = b"immutable artifact\x00bytes"

    object_hash = objects.put_blob(payload)

    assert object_hash == digest("immutable artifact\x00bytes")
    assert object_path(objects, object_hash).read_bytes() == payload
    assert objects.verify(object_hash) is True

    object_path(objects, object_hash).chmod(0o600)
    object_path(objects, object_hash).write_bytes(b"corrupt")
    with pytest.raises(ReV2LedgerError, match="corrupt|mismatch"):
        objects.put_blob(payload)
    assert object_path(objects, object_hash).read_bytes() == b"corrupt"


def test_concurrent_identical_blob_writers_never_clobber_the_object(
    tmp_path: Path,
) -> None:
    objects = ObjectStore(tmp_path / "objects")
    payload = b"one immutable value" * 2048

    with ThreadPoolExecutor(max_workers=8) as pool:
        hashes = tuple(pool.map(objects.put_blob, [payload] * 32))

    assert set(hashes) == {content_digest(payload)}
    assert object_path(objects, hashes[0]).read_bytes() == payload


def test_tree_manifest_binds_path_mode_size_and_blob_hash(tmp_path: Path) -> None:
    objects = ObjectStore(tmp_path / "objects")
    tree = tmp_path / "tree"
    (tree / "nested").mkdir(parents=True)
    first = tree / "a.txt"
    second = tree / "nested" / "run.sh"
    first.write_bytes(b"alpha")
    second.write_bytes(b"#!/bin/sh\n")
    first.chmod(0o640)
    second.chmod(0o755)

    tree_hash = objects.put_tree(tree)
    stored = object_path(objects, tree_hash).read_bytes()
    assert stored.startswith(TREE_OBJECT_MAGIC)
    manifest = json.loads(stored.removeprefix(TREE_OBJECT_MAGIC))

    assert manifest == {
        "entries": [
            {
                "blob_hash": content_digest(b"alpha"),
                "mode": 0o640,
                "path": "a.txt",
                "size": 5,
                "type": "file",
            },
            {
                "mode": 0o755,
                "path": "nested",
                "type": "directory",
            },
            {
                "blob_hash": content_digest(b"#!/bin/sh\n"),
                "mode": 0o755,
                "path": "nested/run.sh",
                "size": 10,
                "type": "file",
            },
        ],
        "schema_version": 1,
        "type": "tree",
    }
    assert objects.verify(tree_hash) is True

    first.chmod(0o600)
    assert objects.put_tree(tree) != tree_hash


def test_tree_object_rejects_special_files(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    os.mkfifo(tree / "pipe")

    with pytest.raises(ReV2LedgerError, match="special"):
        ObjectStore(tmp_path / "objects").put_tree(tree)


def test_tree_object_rejects_mutation_during_ingest(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    source = tree / "artifact.txt"
    source.write_bytes(b"before")

    class MutatingStore(ObjectStore):
        mutated = False

        def put_blob(self, payload: bytes) -> str:
            result = super().put_blob(payload)
            if not self.mutated:
                self.mutated = True
                source.write_bytes(b"after mutation")
            return result

    with pytest.raises(ReV2LedgerError, match="mutat"):
        MutatingStore(tmp_path / "objects").put_tree(tree)


def test_tree_manifest_binds_empty_directories_and_their_modes(tmp_path: Path) -> None:
    objects = ObjectStore(tmp_path / "objects")
    tree = tmp_path / "tree"
    empty = tree / "empty"
    empty.mkdir(parents=True)
    empty.chmod(0o750)

    first_hash = objects.put_tree(tree)
    manifest = json.loads(
        object_path(objects, first_hash).read_bytes().removeprefix(TREE_OBJECT_MAGIC)
    )

    assert manifest["entries"] == [
        {"mode": 0o750, "path": "empty", "type": "directory"}
    ]
    empty.chmod(0o700)
    assert objects.put_tree(tree) != first_hash


def test_tree_object_rejects_directory_mode_mutation_during_ingest(
    tmp_path: Path,
) -> None:
    tree = tmp_path / "tree"
    nested = tree / "nested"
    nested.mkdir(parents=True)
    (tree / "artifact.txt").write_bytes(b"before")

    class MutatingStore(ObjectStore):
        mutated = False

        def put_blob(self, payload: bytes) -> str:
            result = super().put_blob(payload)
            if not self.mutated:
                self.mutated = True
                nested.chmod(0o700)
            return result

    with pytest.raises(ReV2LedgerError, match="mutat"):
        MutatingStore(tmp_path / "objects").put_tree(tree)


@pytest.mark.parametrize(
    "bad_path", ["../escape", "/absolute", "nested/../../escape", "a\\..\\escape"]
)
def test_verify_rejects_tree_manifest_path_traversal(
    tmp_path: Path, bad_path: str
) -> None:
    objects = ObjectStore(tmp_path / "objects")
    blob_hash = objects.put_blob(b"safe bytes")
    manifest_hash = write_raw_object(
        objects,
        TREE_OBJECT_MAGIC
        + b'{"entries":[{"blob_hash":"'
        + blob_hash.encode()
        + b'","mode":420,"path":"'
        + bad_path.replace("\\", "\\\\").encode()
        + b'","size":10,"type":"file"}],"schema_version":1,'
        b'"type":"tree"}\n'
    )

    with pytest.raises(ReV2LedgerError, match="path|traversal"):
        objects.verify(manifest_hash)


def test_verify_tree_recursively_checks_referenced_blob_size(tmp_path: Path) -> None:
    objects = ObjectStore(tmp_path / "objects")
    blob_hash = objects.put_blob(b"three")
    manifest_hash = write_raw_object(
        objects,
        TREE_OBJECT_MAGIC
        + b'{"entries":[{"blob_hash":"'
        + blob_hash.encode()
        + b'","mode":420,"path":"file.txt","size":999,"type":"file"}],'
        b'"schema_version":1,"type":"tree"}\n'
    )

    with pytest.raises(ReV2LedgerError, match="size"):
        objects.verify(manifest_hash)


def test_blob_json_that_resembles_a_tree_is_never_parsed_as_a_tree(
    tmp_path: Path,
) -> None:
    objects = ObjectStore(tmp_path / "objects")
    tree_shaped_blob = (
        b'{"entries":[{"blob_hash":"not-a-digest","mode":420,'
        b'"path":"../escape","size":0,"type":"file"}],'
        b'"schema_version":1,"type":"tree"}\n'
    )

    blob_hash = objects.put_blob(tree_shaped_blob)

    assert objects.verify(blob_hash) is True
    assert object_path(objects, blob_hash).read_bytes() == tree_shaped_blob


@pytest.mark.parametrize(
    "payload",
    [TREE_OBJECT_MAGIC, TREE_OBJECT_MAGIC + b"ordinary blob bytes"],
)
def test_blob_rejects_reserved_tree_envelope_before_publication(
    tmp_path: Path, payload: bytes
) -> None:
    objects = ObjectStore(tmp_path / "objects")

    with pytest.raises(ReV2LedgerError, match="reserved tree.*prefix"):
        objects.put_blob(payload)

    assert list((objects.root / "sha256").rglob("*")) == []


def test_ledger_writes_canonical_hash_chained_records(tmp_path: Path) -> None:
    ledger, objects = make_ledger(tmp_path)
    certification, artifact = accepted_receipts(objects)

    first = ledger.record_certification(certification, work_item())
    second = ledger.record_artifact(artifact)
    records = [json.loads(line) for line in ledger.path.read_bytes().splitlines()]

    assert (first.seq, first.previous_record_hash) == (1, None)
    assert (second.seq, second.previous_record_hash) == (2, first.record_hash)
    assert records == [first.to_json_dict(), second.to_json_dict()]
    assert all(record["schema_version"] == LEDGER_SCHEMA_VERSION for record in records)


@pytest.mark.parametrize(
    ("suffix", "message"),
    [
        (b'{"schema_version":1', "partial"),
        (b"not-json\n", "JSON"),
        (b"\n", "framing"),
    ],
)
def test_ledger_replay_fails_closed_on_torn_or_invalid_records(
    tmp_path: Path, suffix: bytes, message: str
) -> None:
    ledger, objects = make_ledger(tmp_path)
    certification, _ = accepted_receipts(objects)
    ledger.record_certification(certification, work_item())
    with ledger.path.open("ab") as stream:
        stream.write(suffix)

    before = ledger.path.read_bytes()
    with pytest.raises(ReV2LedgerError, match=message):
        ledger.replay()
    assert ledger.path.read_bytes() == before


def test_ledger_replay_rejects_chain_tampering_and_noncanonical_json(
    tmp_path: Path,
) -> None:
    ledger, objects = make_ledger(tmp_path)
    certification, _ = accepted_receipts(objects)
    record = ledger.record_certification(certification, work_item()).to_json_dict()
    record["record_hash"] = digest("forged")
    ledger.path.write_bytes(
        json.dumps(record, sort_keys=False, separators=(",", ":")).encode() + b"\n"
    )

    with pytest.raises(ReV2LedgerError, match="hash|canonical"):
        ledger.replay()


def test_acceptance_requires_exact_certification_cross_references(
    tmp_path: Path,
) -> None:
    ledger, objects = make_ledger(tmp_path)
    certification, artifact = accepted_receipts(objects)
    ledger.record_certification(certification, work_item())

    mismatches = (
        replace(artifact, artifact_hash=objects.put_blob(b"different")),
        replace(artifact, candidate_id="candidate-other"),
        replace(artifact, work_item_id=digest("different-work")),
        replace(
            artifact,
            artifact_key=replace(
                artifact.artifact_key, source_snapshot_id=digest("different-source")
            ),
        ),
    )
    for mismatch in mismatches:
        with pytest.raises(
            ReV2LedgerError, match="match certification|pinned source"
        ):
            ledger.record_artifact(mismatch)
    assert ledger.replay().accepted_artifacts == {}


@pytest.mark.parametrize(("verdict", "scope_verified"), [("rejected", True), ("accepted", False)])
def test_rejected_or_unscoped_certification_cannot_authorize_acceptance(
    tmp_path: Path, verdict: str, scope_verified: bool
) -> None:
    ledger, objects = make_ledger(tmp_path)
    certification, artifact = accepted_receipts(objects)
    certification = replace(
        certification, verdict=verdict, scope_verified=scope_verified
    )
    artifact = replace(artifact, certification_id=certification.identity)
    ledger.record_certification(certification, work_item())

    with pytest.raises(ReV2LedgerError, match="accepted certification"):
        ledger.record_artifact(artifact)


def test_unsupported_verifier_version_is_rejected_without_appending(
    tmp_path: Path,
) -> None:
    ledger, objects = make_ledger(tmp_path)
    certification, _ = accepted_receipts(objects)
    unsupported = replace(
        certification,
        certification_key=replace(
            certification.certification_key, verifier_version="v2"
        ),
    )

    unsupported_item = replace(work_item(), verifier_version="v2")
    unsupported = replace(unsupported, work_item_id=unsupported_item.work_item_id)
    with pytest.raises(ReV2LedgerError, match="unsupported verifier"):
        ledger.record_certification(unsupported, unsupported_item)
    assert not ledger.path.exists()


def test_duplicate_receipts_are_idempotent_but_identity_conflicts_fail(
    tmp_path: Path,
) -> None:
    ledger, objects = make_ledger(tmp_path)
    certification, artifact = accepted_receipts(objects)
    ledger.record_certification(certification, work_item())
    ledger.record_artifact(artifact)
    original = ledger.path.read_bytes()

    ledger.record_certification(certification, work_item())
    ledger.record_artifact(artifact)
    assert ledger.path.read_bytes() == original

    conflicting_certification = replace(
        certification,
        normalized_diagnostics=("different-decision",),
    )
    with pytest.raises(ReV2LedgerError, match="conflict"):
        ledger.record_certification(conflicting_certification, work_item())

    next_certification, next_artifact = accepted_receipts(
        objects, payload=b"replacement", candidate_id="candidate-2"
    )
    ledger.record_certification(next_certification, work_item())
    with pytest.raises(ReV2LedgerError, match="conflict"):
        ledger.record_artifact(next_artifact)


def test_ledger_replay_verifies_referenced_object_bytes(tmp_path: Path) -> None:
    ledger, objects = make_ledger(tmp_path)
    certification, artifact = accepted_receipts(objects)
    ledger.record_certification(certification, work_item())
    ledger.record_artifact(artifact)
    object_path(objects, artifact.artifact_hash).chmod(0o600)
    object_path(objects, artifact.artifact_hash).write_bytes(b"corrupt")

    with pytest.raises(ReV2LedgerError, match="mismatch|corrupt"):
        ledger.replay()


def test_ledger_view_is_narrow_and_immutable(tmp_path: Path) -> None:
    ledger, objects = make_ledger(tmp_path)
    certification, artifact = accepted_receipts(objects)
    ledger.record_certification(certification, work_item())
    ledger.record_artifact(artifact)

    view = ledger.replay()

    assert isinstance(view.accepted_artifacts, MappingProxyType)
    assert view.accepted_artifacts[artifact.artifact_key.identity] == artifact
    with pytest.raises(TypeError):
        view.accepted_artifacts["replacement"] = artifact  # type: ignore[index]


def test_concurrent_ledger_appends_are_serialized_without_lost_records(
    tmp_path: Path,
) -> None:
    ledger, objects = make_ledger(tmp_path)
    receipts = [
        accepted_receipts(
            objects,
            payload=f"artifact-{index}".encode(),
            candidate_id=f"candidate-{index}",
        )[0]
        for index in range(16)
    ]

    with ThreadPoolExecutor(max_workers=8) as pool:
        tuple(
            pool.map(
                lambda receipt: ledger.record_certification(receipt, work_item()),
                receipts,
            )
        )

    view = ledger.replay()
    records = [json.loads(line) for line in ledger.path.read_bytes().splitlines()]
    assert len(view.certifications) == 16
    assert [record["seq"] for record in records] == list(range(1, 17))


def test_ledger_append_retries_interrupted_and_short_os_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness.re_v2.ledger as ledger_module

    ledger, objects = make_ledger(tmp_path)
    certification, _ = accepted_receipts(objects)
    real_write = os.write
    real_fsync = os.fsync
    interrupted = {"write": False, "fsync": False}

    def short_write(fd: int, payload: bytes) -> int:
        if not interrupted["write"]:
            interrupted["write"] = True
            raise InterruptedError
        return real_write(fd, payload[:7])

    def interrupted_fsync(fd: int) -> None:
        if not interrupted["fsync"]:
            interrupted["fsync"] = True
            raise InterruptedError
        real_fsync(fd)

    monkeypatch.setattr(ledger_module.os, "write", short_write)
    monkeypatch.setattr(ledger_module.os, "fsync", interrupted_fsync)

    ledger.record_certification(certification, work_item())

    assert ledger.replay().certifications[certification.identity] == certification
    assert interrupted == {"write": True, "fsync": True}


def test_bare_ledger_requires_an_explicit_pinned_source_snapshot(
    tmp_path: Path,
) -> None:
    objects = ObjectStore(tmp_path / "objects")

    with pytest.raises(ReV2LedgerError, match="pinned source"):
        Ledger(
            tmp_path / "ledger.jsonl",
            objects,
            supported_verifiers={"fixture-verifier": "v1"},
        )


def test_re_v2_paths_bind_ledger_to_the_immutable_run_manifest(
    tmp_path: Path,
) -> None:
    manifest = RunManifest(
        schema_version=1,
        engine="re-v2",
        engine_protocol_version="2.0",
        run_id="run-1",
        created_at=NOW,
        source_snapshot_id=digest("source"),
        source_snapshot_kind="content-snapshot",
        partition_manifest_id=digest("partitions"),
        requested_goals=("inventory",),
        initial_budget_policy=BudgetPolicy(None, None, 1, 1, 0, 0),
        provider_contract={"provider": "fixture"},
        artifact_policy_versions={"inventory": "v1"},
        parent_run_id=None,
    )
    paths = create_run_store(tmp_path / "run-1", manifest)
    objects = ObjectStore(tmp_path / "objects")
    ledger = Ledger(
        paths,
        objects,
        supported_verifiers={"fixture-verifier": "v1"},
    )
    certification, artifact = accepted_receipts(objects)

    ledger.record_certification(certification, work_item())
    ledger.record_artifact(artifact)

    assert artifact.artifact_key.identity in ledger.replay().accepted_artifacts


def test_certification_persists_and_validates_the_full_work_item(
    tmp_path: Path,
) -> None:
    ledger, objects = make_ledger(tmp_path)
    item = work_item()
    certification, _ = accepted_receipts(objects, item=item)

    record = ledger.record_certification(certification, item)

    assert record.to_json_dict()["payload"] == {
        "receipt": certification.to_json_dict(),
        "work_item": item.to_json_dict(),
    }

    wrong_item = replace(item, verifier_id="other-verifier")
    with pytest.raises(ReV2LedgerError, match="work item|work_item|verifier"):
        ledger.record_certification(certification, wrong_item)


def test_artifact_key_must_equal_the_certified_work_item_output_key(
    tmp_path: Path,
) -> None:
    ledger, objects = make_ledger(tmp_path)
    item = work_item()
    certification, artifact = accepted_receipts(objects, item=item)
    ledger.record_certification(certification, item)
    wrong_key = replace(artifact.artifact_key, artifact_kind="other-inventory")

    with pytest.raises(ReV2LedgerError, match="output key|artifact key"):
        ledger.record_artifact(replace(artifact, artifact_key=wrong_key))


def test_pinned_source_rejects_other_work_and_receipt_sources(
    tmp_path: Path,
) -> None:
    ledger, objects = make_ledger(tmp_path)
    other_key = replace(
        work_item().output_key, source_snapshot_id=digest("other-source")
    )
    other_item = replace(
        work_item(), output_key=other_key, required_artifact_hashes=()
    )
    certification, _ = accepted_receipts(objects, item=other_item)

    with pytest.raises(ReV2LedgerError, match="pinned source"):
        ledger.record_certification(certification, other_item)


def test_ledger_rejects_crlf_record_framing(tmp_path: Path) -> None:
    ledger, objects = make_ledger(tmp_path)
    certification, _ = accepted_receipts(objects)
    ledger.record_certification(certification, work_item())
    ledger.path.write_bytes(ledger.path.read_bytes().replace(b"\n", b"\r\n"))

    with pytest.raises(ReV2LedgerError, match="framing|carriage|canonical"):
        ledger.replay()


def test_certification_decision_requires_scope_for_an_artifact(
    tmp_path: Path,
) -> None:
    objects = ObjectStore(tmp_path / "objects")
    certification, artifact = accepted_receipts(objects)
    unscoped = replace(certification, scope_verified=False)

    assert CertificationDecision(unscoped, None).artifact_receipt is None
    with pytest.raises(ReV2LedgerError, match="scope"):
        CertificationDecision(unscoped, replace(artifact, certification_id=unscoped.identity))
