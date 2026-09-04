from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Mapping

import pytest

from echelon.workspace_model import SourceRoot, WorkspaceInfo, WorkspaceManifest
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.partition import (
    ImplementationAuthorityV1,
    PartitionAuthoritiesV1,
    WorkspacePartitionCatalogV1,
    build_workspace_partition_catalog,
)
from harness.re_v2.protocol_24.model import SelectionScopeV1
from harness.re_v2.protocol_28.evidence import (
    EvidenceStagingPolicyV1,
    Protocol28EvidenceError,
    SnapshotEvidenceCatalogV1,
    read_staged_shard_bytes,
    stage_snapshot_evidence,
    validate_snapshot_evidence_closure,
)
from harness.re_v2.workspace_snapshot import capture_workspace_snapshot


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.test",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.test",
        },
    ).stdout


def _write_files(root: Path, files: Mapping[str, str | bytes]) -> None:
    for relative, payload in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, bytes):
            target.write_bytes(payload)
        else:
            target.write_text(payload, encoding="utf-8")


def _fixture(
    tmp_path: Path,
    files: Mapping[str, str | bytes],
) -> tuple[object, WorkspacePartitionCatalogV1]:
    workspace = tmp_path / "workspace"
    repo = workspace / "sources" / "api"
    repo.mkdir(parents=True)
    _git(repo, "init")
    _write_files(repo, files)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    source = SourceRoot(id="api", path="sources/api", git_present=True)
    workspace_manifest = WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(
            root=workspace.resolve(),
            git_role="orchestration",
            git_present=False,
        ),
        sources=(source,),
    )
    snapshot = capture_workspace_snapshot(
        workspace,
        (source,),
        tmp_path / "snapshots",
    )
    authorities = PartitionAuthoritiesV1(
        partitioner=ImplementationAuthorityV1(
            id="existing-domain-partitioner",
            version="5",
            implementation_digest=content_digest(b"partitioner"),
        ),
        ownership_policy=ImplementationAuthorityV1(
            id="explicit-domain-ownership",
            version="1",
            implementation_digest=content_digest(b"ownership"),
        ),
    )
    partition = build_workspace_partition_catalog(
        snapshot,
        workspace_manifest,
        authorities,
    )
    return snapshot, partition


def _policy(*, shard_byte_limit: int = 65_536) -> EvidenceStagingPolicyV1:
    return EvidenceStagingPolicyV1(
        schema_version=1,
        shard_byte_limit=shard_byte_limit,
        proven_non_behavioral_suffixes=(".gif", ".ico", ".jpeg", ".jpg", ".png"),
    )


def _domain_selection(partition: WorkspacePartitionCatalogV1, root: str) -> SelectionScopeV1:
    domain = next(
        item
        for item in partition.sources[0].domains
        if item.source_relative_root == root
    )
    return SelectionScopeV1(
        schema_version=1,
        all_sources=False,
        source_ids=("api",),
        domain_keys=(domain.domain_key,),
    )


def _source_selection() -> SelectionScopeV1:
    return SelectionScopeV1(
        schema_version=1,
        all_sources=False,
        source_ids=("api",),
        domain_keys=(),
    )


def _primary_paths(catalog: SnapshotEvidenceCatalogV1) -> list[tuple[str, str]]:
    shards = {item.shard_id: item for item in catalog.shards}
    empty = {item.receipt_id: item for item in catalog.empty_receipts}
    nontext = {item.disposition_id: item for item in catalog.nontext_dispositions}
    paths: list[tuple[str, str]] = []
    for projection in catalog.projections:
        paths.extend(
            (shards[item].source_id, shards[item].source_relative_path)
            for item in projection.primary_shard_ids
        )
        paths.extend(
            (empty[item].source_id, empty[item].source_relative_path)
            for item in projection.primary_empty_receipt_ids
        )
        paths.extend(
            (nontext[item].source_id, nontext[item].source_relative_path)
            for item in projection.primary_nontext_disposition_ids
        )
    return paths


@pytest.mark.unit
def test_utf8_shards_cover_exact_raw_bytes_without_gaps(tmp_path: Path) -> None:
    """A shard split that drops or duplicates even one byte breaks exhaustive evidence."""
    payload = "a\nβ\nc\n"
    snapshot, partition = _fixture(
        tmp_path,
        {
            "README.md": "API\n",
            "src/orders/handler.py": payload,
        },
    )
    selection = _domain_selection(partition, "src")
    objects = ObjectStore(tmp_path / "objects")

    catalog = stage_snapshot_evidence(
        snapshot,
        partition,
        selection,
        _policy(shard_byte_limit=4),
        objects,
    )

    projection = catalog.projection_for(selection.domain_keys[0])
    shards = tuple(catalog.shard_by_id(item) for item in projection.primary_shard_ids)
    assert b"".join(shard.raw_bytes for shard in shards) == payload.encode("utf-8")
    assert [(item.byte_start, item.byte_end) for item in shards] == [
        (0, 2),
        (2, 5),
        (5, 7),
    ]
    assert all(read_staged_shard_bytes(objects, item) == item.raw_bytes for item in shards)
    validate_snapshot_evidence_closure(catalog, partition, selection)


@pytest.mark.unit
def test_behavioral_binary_blocks_before_evidence_catalog_exists(tmp_path: Path) -> None:
    """Unknown binary source content must not be relabelled as exhaustive metadata."""
    snapshot, partition = _fixture(tmp_path, {"plugin.bin": b"\x00\x01"})

    with pytest.raises(
        Protocol28EvidenceError,
        match=(
            r"unsupported_behavioral_content: api/plugin\.bin "
            r"\(regular, contains_nul, 2 bytes\)"
        ),
    ):
        stage_snapshot_evidence(
            snapshot,
            partition,
            _source_selection(),
            _policy(),
            ObjectStore(tmp_path / "objects"),
        )


@pytest.mark.unit
def test_selected_domain_and_source_projection_cover_each_primary_record_once(
    tmp_path: Path,
) -> None:
    """Source-unowned files must not disappear or duplicate domain-owned coverage."""
    snapshot, partition = _fixture(
        tmp_path,
        {
            "README.md": "API\n",
            "src/orders/handler.py": "order = True\n",
        },
    )
    selection = _domain_selection(partition, "src")

    catalog = stage_snapshot_evidence(
        snapshot,
        partition,
        selection,
        _policy(),
        ObjectStore(tmp_path / "objects"),
    )

    primary = _primary_paths(catalog)
    assert set(primary) == {("api", "README.md"), ("api", "src/orders/handler.py")}
    assert len(primary) == len(set(primary))


@pytest.mark.unit
def test_all_scope_assigns_every_source_record_once(tmp_path: Path) -> None:
    """The all-scope evidence claim must be a complete partition, not a percentage."""
    snapshot, partition = _fixture(
        tmp_path,
        {
            "README.md": "API\n",
            "src/orders/handler.py": "order = True\n",
            "src/orders/model.py": "class Order: pass\n",
        },
    )
    selection = SelectionScopeV1(
        schema_version=1,
        all_sources=True,
        source_ids=(),
        domain_keys=(),
    )

    catalog = stage_snapshot_evidence(
        snapshot,
        partition,
        selection,
        _policy(),
        ObjectStore(tmp_path / "objects"),
    )

    primary = _primary_paths(catalog)
    expected = {
        ("api", item.source_relative_path) for item in partition.sources[0].files
    }
    assert set(primary) == expected
    assert len(primary) == len(set(primary))
    validate_snapshot_evidence_closure(catalog, partition, selection)


@pytest.mark.unit
def test_proven_nonbehavioral_binary_gets_metadata_disposition(tmp_path: Path) -> None:
    """Closed asset rules may cover bytes as metadata without treating them as code."""
    snapshot, partition = _fixture(tmp_path, {"logo.png": b"\x89PNG\x00"})
    selection = _source_selection()

    catalog = stage_snapshot_evidence(
        snapshot,
        partition,
        selection,
        _policy(),
        ObjectStore(tmp_path / "objects"),
    )

    assert len(catalog.nontext_dispositions) == 1
    assert catalog.nontext_dispositions[0].disposition == "proven_non_behavioral"
    validate_snapshot_evidence_closure(catalog, partition, selection)


@pytest.mark.unit
def test_empty_file_has_explicit_primary_coverage_receipt(tmp_path: Path) -> None:
    """Zero bytes still require an affirmative selected-scope coverage fact."""
    snapshot, partition = _fixture(tmp_path, {"empty.txt": ""})
    selection = _source_selection()

    catalog = stage_snapshot_evidence(
        snapshot,
        partition,
        selection,
        _policy(),
        ObjectStore(tmp_path / "objects"),
    )

    projection = catalog.projection_for("api")
    assert len(projection.primary_empty_receipt_ids) == 1
    assert not projection.primary_shard_ids
    validate_snapshot_evidence_closure(catalog, partition, selection)


@pytest.mark.unit
def test_catalog_round_trip_preserves_target_local_projection_identity(
    tmp_path: Path,
) -> None:
    """Canonical reconstruction must not smuggle execution order into local reuse."""
    snapshot, partition = _fixture(
        tmp_path,
        {"src/orders/handler.py": "return_value = 1\n"},
    )
    selection = _domain_selection(partition, "src")
    catalog = stage_snapshot_evidence(
        snapshot,
        partition,
        selection,
        _policy(),
        ObjectStore(tmp_path / "objects"),
    )

    rebuilt = SnapshotEvidenceCatalogV1.from_json_dict(catalog.to_json_dict())

    assert rebuilt == catalog
    assert rebuilt.projections[0].identity == catalog.projections[0].identity
    assert canonical_json_bytes(rebuilt.to_json_dict()) == canonical_json_bytes(
        catalog.to_json_dict()
    )


@pytest.mark.unit
def test_changed_snapshot_is_rejected_before_sharding(tmp_path: Path) -> None:
    """Staging must never read mutable bytes under an old snapshot identity."""
    snapshot, partition = _fixture(tmp_path, {"main.py": "before = True\n"})
    target = snapshot.read_root / "sources" / "api" / "main.py"
    target.chmod(0o644)
    target.write_text("after = True\n", encoding="utf-8")

    with pytest.raises(Protocol28EvidenceError, match="snapshot|changed|pinned"):
        stage_snapshot_evidence(
            snapshot,
            partition,
            _source_selection(),
            _policy(),
            ObjectStore(tmp_path / "objects"),
        )
