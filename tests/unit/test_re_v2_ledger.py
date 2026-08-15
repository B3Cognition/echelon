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
)
from harness.re_v2.model import (
    ArtifactKey,
    ArtifactReceipt,
    CertificationKey,
    CertificationReceipt,
    WorkItem,
)


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
        ),
        objects,
    )


def object_path(objects: ObjectStore, object_hash: str) -> Path:
    suffix = object_hash.removeprefix("sha256:")
    return objects.root / "sha256" / suffix[:2] / suffix[2:]


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
    ledger.record_certification(decision.certification_receipt)
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
    manifest = json.loads(object_path(objects, tree_hash).read_bytes())

    assert manifest == {
        "entries": [
            {
                "blob_hash": content_digest(b"alpha"),
                "mode": 0o640,
                "path": "a.txt",
                "size": 5,
            },
            {
                "blob_hash": content_digest(b"#!/bin/sh\n"),
                "mode": 0o755,
                "path": "nested/run.sh",
                "size": 10,
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


@pytest.mark.parametrize(
    "bad_path", ["../escape", "/absolute", "nested/../../escape", "a\\..\\escape"]
)
def test_verify_rejects_tree_manifest_path_traversal(
    tmp_path: Path, bad_path: str
) -> None:
    objects = ObjectStore(tmp_path / "objects")
    blob_hash = objects.put_blob(b"safe bytes")
    manifest_hash = objects.put_blob(
        b'{"entries":[{"blob_hash":"'
        + blob_hash.encode()
        + b'","mode":420,"path":"'
        + bad_path.replace("\\", "\\\\").encode()
        + b'","size":10}],"schema_version":1,"type":"tree"}\n'
    )

    with pytest.raises(ReV2LedgerError, match="path|traversal"):
        objects.verify(manifest_hash)


def test_verify_tree_recursively_checks_referenced_blob_size(tmp_path: Path) -> None:
    objects = ObjectStore(tmp_path / "objects")
    blob_hash = objects.put_blob(b"three")
    manifest_hash = objects.put_blob(
        b'{"entries":[{"blob_hash":"'
        + blob_hash.encode()
        + b'","mode":420,"path":"file.txt","size":999}],'
        b'"schema_version":1,"type":"tree"}\n'
    )

    with pytest.raises(ReV2LedgerError, match="size"):
        objects.verify(manifest_hash)


def test_ledger_writes_canonical_hash_chained_records(tmp_path: Path) -> None:
    ledger, objects = make_ledger(tmp_path)
    certification, artifact = accepted_receipts(objects)

    first = ledger.record_certification(certification)
    second = ledger.record_artifact(artifact)
    records = [json.loads(line) for line in ledger.path.read_bytes().splitlines()]

    assert (first.seq, first.previous_record_hash) == (1, None)
    assert (second.seq, second.previous_record_hash) == (2, first.record_hash)
    assert records == [first.to_json_dict(), second.to_json_dict()]
    assert all(record["schema_version"] == LEDGER_SCHEMA_VERSION for record in records)


@pytest.mark.parametrize(
    ("suffix", "message"),
    [(b'{"schema_version":1', "partial"), (b"not-json\n", "JSON"), (b"\n", "JSON")],
)
def test_ledger_replay_fails_closed_on_torn_or_invalid_records(
    tmp_path: Path, suffix: bytes, message: str
) -> None:
    ledger, objects = make_ledger(tmp_path)
    certification, _ = accepted_receipts(objects)
    ledger.record_certification(certification)
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
    record = ledger.record_certification(certification).to_json_dict()
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
    ledger.record_certification(certification)

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
        with pytest.raises(ReV2LedgerError, match="match certification"):
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
    ledger.record_certification(certification)

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

    with pytest.raises(ReV2LedgerError, match="unsupported verifier"):
        ledger.record_certification(unsupported)
    assert not ledger.path.exists()


def test_duplicate_receipts_are_idempotent_but_identity_conflicts_fail(
    tmp_path: Path,
) -> None:
    ledger, objects = make_ledger(tmp_path)
    certification, artifact = accepted_receipts(objects)
    ledger.record_certification(certification)
    ledger.record_artifact(artifact)
    original = ledger.path.read_bytes()

    ledger.record_certification(certification)
    ledger.record_artifact(artifact)
    assert ledger.path.read_bytes() == original

    conflicting_certification = replace(
        certification,
        normalized_diagnostics=("different-decision",),
    )
    with pytest.raises(ReV2LedgerError, match="conflict"):
        ledger.record_certification(conflicting_certification)

    next_certification, next_artifact = accepted_receipts(
        objects, payload=b"replacement", candidate_id="candidate-2"
    )
    ledger.record_certification(next_certification)
    with pytest.raises(ReV2LedgerError, match="conflict"):
        ledger.record_artifact(next_artifact)


def test_ledger_replay_verifies_referenced_object_bytes(tmp_path: Path) -> None:
    ledger, objects = make_ledger(tmp_path)
    certification, artifact = accepted_receipts(objects)
    ledger.record_certification(certification)
    ledger.record_artifact(artifact)
    object_path(objects, artifact.artifact_hash).chmod(0o600)
    object_path(objects, artifact.artifact_hash).write_bytes(b"corrupt")

    with pytest.raises(ReV2LedgerError, match="mismatch|corrupt"):
        ledger.replay()


def test_ledger_view_is_narrow_and_immutable(tmp_path: Path) -> None:
    ledger, objects = make_ledger(tmp_path)
    certification, artifact = accepted_receipts(objects)
    ledger.record_certification(certification)
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
        tuple(pool.map(ledger.record_certification, receipts))

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

    ledger.record_certification(certification)

    assert ledger.replay().certifications[certification.identity] == certification
    assert interrupted == {"write": True, "fsync": True}
