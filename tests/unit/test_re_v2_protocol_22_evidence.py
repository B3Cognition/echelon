from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
from typing import Mapping

import pytest

from echelon.workspace_model import SourceRoot, WorkspaceInfo, WorkspaceManifest
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.artifacts import (
    EvidencePackV1,
    OmittedEvidenceDescriptorV1,
)
from harness.re_v2.protocol_22.evidence import (
    EvidenceAuthorityDescriptorV1,
    PinnedSnapshotReaderV1,
    Protocol22EvidenceError,
    build_evidence_pack,
    evidence_authority_id,
    validate_evidence_pack,
)
from harness.re_v2.protocol_22.graph import (
    AcceptedArtifactV2,
    build_protocol_22_graph,
    instantiate_ready_item,
)
from harness.re_v2.protocol_22.inventory import InventoryArtifactV1, InventoryFileV1
from harness.re_v2.protocol_22.partition import (
    FileRecordV1,
    PartitionAuthoritiesV1,
    ImplementationAuthorityV1,
    build_workspace_partition_catalog,
)
from harness.re_v2.protocol_22.policies import (
    ArtifactPolicyCatalogV1,
    ArtifactPolicyEntryV1,
    build_compact_v1_policy_catalog,
    policy_for,
)
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.workspace_snapshot import capture_workspace_snapshot
from tests.re_v2_protocol_22_fixtures import digest
from tests.unit.test_re_v2_protocol_22_graph import _fixture, _template


class _MemoryReader:
    def __init__(self, blobs: Mapping[str, bytes], *, provider: str = "none") -> None:
        self._blobs = dict(blobs)
        self.provider = provider
        self.reads: list[str] = []

    def read_file(
        self,
        source_id: str,
        source_relative_path: str,
        expected: FileRecordV1,
    ) -> bytes:
        assert source_id == "api"
        payload = self._blobs[source_relative_path]
        assert expected.source_relative_path == source_relative_path
        assert expected.content_hash == content_digest(payload)
        assert expected.byte_count == len(payload)
        self.reads.append(source_relative_path)
        return payload


def _raw_line_count(payload: bytes) -> int:
    if not payload:
        return 0
    return 1 + payload.count(b"\n") - int(payload.endswith(b"\n"))


def _record(
    path: str,
    payload: bytes,
    ownership: str,
    *,
    mode: str = "100644",
    object_kind: str = "regular",
    text_status: str = "eligible_utf8",
) -> InventoryFileV1:
    return InventoryFileV1(
        source_relative_path=path,
        mode=mode,
        object_kind=object_kind,
        content_hash=content_digest(payload),
        byte_count=len(payload),
        line_count=_raw_line_count(payload) if object_kind == "regular" else 0,
        text_status=text_status,
        ownership=ownership,
    )


def _catalog_with_cap(kind: str, cap: int | None) -> ArtifactPolicyCatalogV1:
    base = build_compact_v1_policy_catalog()
    entries = tuple(
        replace(
            entry,
            max_canonical_json_bytes=cap,
            max_conservative_input_tokens=cap,
        )
        if entry.artifact_kind == kind and cap is not None
        else entry
        for entry in base.entries
    )
    return ArtifactPolicyCatalogV1(schema_version=1, entries=entries)


def _case(
    kind: str,
    rows: tuple[InventoryFileV1, ...],
    blobs: Mapping[str, bytes],
    *,
    cap: int | None = None,
    provider: str = "none",
) -> tuple[object, bytes, _MemoryReader, ArtifactPolicyEntryV1]:
    catalog = _catalog_with_cap(kind, cap)
    manifest, inputs = _fixture({"api": ("orders",)}, policy=catalog)
    graph = build_protocol_22_graph(manifest, inputs)
    source = inputs.workspace_partition.sources[0]
    domain = source.domains[0]
    is_domain = kind == "domain-evidence-pack"
    template = _template(
        graph,
        source.source_id,
        kind,
        domain_key_value=domain.domain_key if is_domain else None,
    )
    inventory = InventoryArtifactV1(
        schema_version=1,
        artifact_kind="domain-inventory" if is_domain else "source-inventory",
        scope=template.scope,
        partition_id=domain.domain_partition_id if is_domain else None,
        files=tuple(sorted(rows, key=lambda row: row.sort_key)),
    )
    inventory_bytes = canonical_json_bytes(inventory.to_json_dict())
    by_template = {item.template_id: item for item in graph.templates}
    accepted: dict[str, AcceptedArtifactV2] = {}
    for required_id in template.required_template_ids:
        dependency = by_template[required_id]
        artifact_hash = (
            content_digest(inventory_bytes)
            if dependency.artifact_kind.endswith("inventory")
            else digest(f"dependency:{required_id}")
        )
        accepted[required_id] = AcceptedArtifactV2(
            artifact_key_id=digest(f"key:{required_id}"),
            artifact_hash=artifact_hash,
        )
    work_item = instantiate_ready_item(template, accepted, inputs)
    return (
        work_item,
        inventory_bytes,
        _MemoryReader(blobs, provider=provider),
        policy_for(catalog, "L0", kind),
    )


def _build(
    kind: str,
    rows: tuple[InventoryFileV1, ...],
    blobs: Mapping[str, bytes],
    *,
    cap: int | None = None,
    provider: str = "none",
) -> EvidencePackV1:
    item, inventory, reader, policy = _case(
        kind,
        rows,
        blobs,
        cap=cap,
        provider=provider,
    )
    return load_canonical_object(
        build_evidence_pack(item, inventory, reader, policy),
        EvidencePackV1.from_json_dict,
    )


@pytest.mark.unit
def test_evidence_authority_ids_are_closed_and_scope_sensitive() -> None:
    source = EvidenceAuthorityDescriptorV1(
        source_id="api",
        source_relative_path="main.py",
        authority_kind="direct",
        origin_domain_key=None,
    )
    domain = replace(source, origin_domain_key=digest("orders"))
    projection = replace(domain, authority_kind="domain_projection")

    assert evidence_authority_id(source) == content_digest(source.to_json_dict())
    assert len(
        {
            evidence_authority_id(source),
            evidence_authority_id(domain),
            evidence_authority_id(projection),
        }
    ) == 3
    with pytest.raises(Protocol22EvidenceError, match="origin_domain_key"):
        replace(source, authority_kind="domain_projection")


@pytest.mark.unit
def test_evidence_pack_is_stable_across_reader_order_and_provider() -> None:
    blobs = {"main.py": b"main\n", "app.py": b"app\n"}
    rows = tuple(_record(path, payload, "source") for path, payload in blobs.items())

    first_item, inventory, first_reader, policy = _case(
        "source-evidence-pack", rows, blobs, provider="one"
    )
    second_item, second_inventory, second_reader, second_policy = _case(
        "source-evidence-pack",
        tuple(reversed(rows)),
        dict(reversed(tuple(blobs.items()))),
        provider="two",
    )

    assert first_item.output_key == second_item.output_key
    assert inventory == second_inventory
    assert build_evidence_pack(first_item, inventory, first_reader, policy) == (
        build_evidence_pack(second_item, second_inventory, second_reader, second_policy)
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("kind", "rows", "blobs", "expected"),
    (
        (
            "source-evidence-pack",
            (
                _record("README.md", b"d" * 500 + b"\n", "source"),
                _record("package.json", b"b" * 500 + b"\n", "source"),
                _record("main.py", b"m" * 500 + b"\n", "source"),
            ),
            {
                "README.md": b"d" * 500 + b"\n",
                "package.json": b"b" * 500 + b"\n",
                "main.py": b"m" * 500 + b"\n",
            },
            "main.py",
        ),
        (
            "domain-evidence-pack",
            (
                _record(
                    "shared/config/app.yml",
                    b"c" * 500 + b"\n",
                    "shared_supporting",
                ),
                _record("orders/main.py", b"m" * 500 + b"\n", "owned"),
                _record("orders/z.py", b"z" * 500 + b"\n", "owned"),
            ),
            {
                "shared/config/app.yml": b"c" * 500 + b"\n",
                "orders/main.py": b"m" * 500 + b"\n",
                "orders/z.py": b"z" * 500 + b"\n",
            },
            "shared/config/app.yml",
        ),
    ),
)
def test_first_line_allocation_obeys_exact_role_priority(
    kind: str,
    rows: tuple[InventoryFileV1, ...],
    blobs: Mapping[str, bytes],
    expected: str,
) -> None:
    pack = _build(kind, rows, blobs, cap=2_200)

    assert [excerpt.source_relative_path for excerpt in pack.excerpts] == [expected]


@pytest.mark.unit
def test_crlf_excerpt_hashes_raw_bytes_but_exposes_lf_text() -> None:
    payload = b"one\r\ntwo\r\n"
    pack = _build(
        "source-evidence-pack",
        (_record("main.py", payload, "source"),),
        {"main.py": payload},
    )

    excerpt = pack.excerpts[0]
    assert excerpt.text_lf == "one\ntwo\n"
    assert excerpt.raw_excerpt_hash == content_digest(payload)
    assert (excerpt.start_line, excerpt.end_line) == (1, 2)
    assert excerpt.complete_file


@pytest.mark.unit
def test_final_unterminated_line_and_lone_cr_are_preserved() -> None:
    payload = b"one\r\ntwo\rthree"
    pack = _build(
        "domain-evidence-pack",
        (_record("orders/main.py", payload, "owned"),),
        {"orders/main.py": payload},
    )

    excerpt = pack.excerpts[0]
    assert excerpt.text_lf == "one\ntwo\rthree"
    assert excerpt.end_line == 2
    assert excerpt.raw_excerpt_hash == content_digest(payload)


@pytest.mark.unit
def test_empty_eligible_file_is_fully_selected_without_excerpt() -> None:
    pack = _build(
        "source-evidence-pack",
        (_record("main.py", b"", "source"),),
        {"main.py": b""},
    )

    assert pack.excerpts == ()
    assert pack.depth_debt.inventory_file_count == 1
    assert pack.depth_debt.fully_selected_file_count == 1
    assert pack.depth_debt.omitted_descriptor_hash is None


@pytest.mark.unit
def test_non_text_and_policy_ineligible_files_become_exact_debt() -> None:
    blobs = {
        "bad.bin": b"\xff",
        "nul.py": b"x\x00y",
        "notes.txt": b"not selected\n",
    }
    rows = (
        _record("bad.bin", blobs["bad.bin"], "source", text_status="invalid_utf8"),
        _record("nul.py", blobs["nul.py"], "source", text_status="contains_nul"),
        _record("notes.txt", blobs["notes.txt"], "source"),
        _record(
            "vendor-link",
            b"vendor",
            "source",
            mode="120000",
            object_kind="symlink",
            text_status="non_regular",
        ),
    )
    item, inventory, reader, policy = _case(
        "source-evidence-pack", rows, blobs
    )
    pack = load_canonical_object(
        build_evidence_pack(item, inventory, reader, policy),
        EvidencePackV1.from_json_dict,
    )

    assert pack.excerpts == ()
    assert pack.depth_debt.omitted_file_count == 4
    assert pack.depth_debt.omitted_range_count == 0
    assert pack.depth_debt.omitted_descriptor_hash is not None
    assert reader.reads == []


@pytest.mark.unit
def test_first_line_too_large_is_distinct_from_later_capacity_exhaustion() -> None:
    huge = b"x" * 10_000 + b"\n"
    huge_pack = _build(
        "source-evidence-pack",
        (_record("main.py", huge, "source"),),
        {"main.py": huge},
        cap=2_048,
    )
    assert huge_pack.excerpts == ()
    assert huge_pack.depth_debt.omitted_file_count == 1
    huge_omission = OmittedEvidenceDescriptorV1(
        descriptor_kind="file",
        source_relative_path="main.py",
        ownership="source",
        origin_domain_key=None,
        start_line=None,
        end_line=None,
        reason_code="line_too_large",
    )
    assert huge_pack.depth_debt.omitted_descriptor_hash == content_digest(
        [huge_omission.to_json_dict()]
    )

    blobs = {"app.py": b"a" * 700 + b"\n", "main.py": b"m" * 700 + b"\n"}
    rows = tuple(_record(path, payload, "source") for path, payload in blobs.items())
    constrained = _build("source-evidence-pack", rows, blobs, cap=2_500)
    assert len(constrained.excerpts) == 1
    assert constrained.depth_debt.omitted_file_count == 1
    capacity_omission = OmittedEvidenceDescriptorV1(
        descriptor_kind="file",
        source_relative_path="main.py",
        ownership="source",
        origin_domain_key=None,
        start_line=None,
        end_line=None,
        reason_code="capacity_exhausted",
    )
    assert constrained.depth_debt.omitted_descriptor_hash == content_digest(
        [capacity_omission.to_json_dict()]
    )


@pytest.mark.unit
def test_partial_prefix_never_splits_a_line_and_records_range_debt() -> None:
    lines = tuple((f"line-{index:03d}-" + "x" * 160 + "\n").encode() for index in range(30))
    payload = b"".join(lines)
    pack = _build(
        "domain-evidence-pack",
        (_record("orders/main.py", payload, "owned"),),
        {"orders/main.py": payload},
        cap=3_000,
    )

    excerpt = pack.excerpts[0]
    selected = b"".join(lines[: excerpt.end_line])
    assert excerpt.raw_excerpt_hash == content_digest(selected)
    assert not excerpt.complete_file
    assert 1 <= excerpt.end_line < len(lines)
    assert pack.depth_debt.partially_selected_file_count == 1
    assert pack.depth_debt.omitted_range_count == 1


@pytest.mark.unit
def test_equal_share_and_round_robin_keep_identical_files_balanced() -> None:
    payload = b"".join(b"x" * 80 + b"\n" for _ in range(50))
    blobs = {"app.py": payload, "main.py": payload}
    rows = tuple(_record(path, data, "source") for path, data in blobs.items())
    pack = _build("source-evidence-pack", rows, blobs, cap=3_500)

    assert len(pack.excerpts) == 2
    selected_lines = [excerpt.end_line for excerpt in pack.excerpts]
    assert max(selected_lines) - min(selected_lines) <= 1
    assert pack.depth_debt.partially_selected_file_count == 2
    assert len(canonical_json_bytes(pack.to_json_dict())) <= 3_500


@pytest.mark.unit
@pytest.mark.parametrize(
    ("kind", "cap", "ownership", "path"),
    (
        ("source-evidence-pack", 48 * 1024, "source", "main.py"),
        ("domain-evidence-pack", 96 * 1024, "owned", "orders/main.py"),
    ),
)
def test_builtin_evidence_boundaries_are_exact(
    kind: str,
    cap: int,
    ownership: str,
    path: str,
) -> None:
    payload = b"".join(b"z" * 2_000 + b"\n" for _ in range(100))
    pack = _build(kind, (_record(path, payload, ownership),), {path: payload})
    encoded = canonical_json_bytes(pack.to_json_dict())

    assert pack.max_canonical_json_bytes == cap
    assert pack.max_conservative_input_tokens == cap
    assert len(encoded) <= cap
    assert not pack.excerpts[0].complete_file


@pytest.mark.unit
def test_validation_reconstructs_pack_and_rejects_tampered_excerpt() -> None:
    payload = b"one\ntwo\n"
    item, inventory, reader, policy = _case(
        "source-evidence-pack",
        (_record("main.py", payload, "source"),),
        {"main.py": payload},
    )
    encoded = build_evidence_pack(item, inventory, reader, policy)
    raw = json.loads(encoded)
    raw["excerpts"][0]["text_lf"] = "forged\n"
    tampered = canonical_json_bytes(raw)

    accepted = validate_evidence_pack(item, encoded, inventory, reader, policy)
    rejected = validate_evidence_pack(item, tampered, inventory, reader, policy)

    assert accepted.normalized_diagnostics == ()
    assert rejected.canonical_schema_valid
    assert not rejected.policy_conformance_valid
    assert "evidence_reconstruction_mismatch" in rejected.normalized_diagnostics


@pytest.mark.unit
def test_build_rejects_wrong_inventory_hash_scope_and_policy() -> None:
    payload = b"ok\n"
    item, inventory, reader, policy = _case(
        "source-evidence-pack",
        (_record("main.py", payload, "source"),),
        {"main.py": payload},
    )
    wrong_inventory = canonical_json_bytes(
        {
            **json.loads(inventory),
            "scope": {**json.loads(inventory)["scope"], "source_id": "other"},
        }
    )

    with pytest.raises(Protocol22EvidenceError, match="canonical"):
        build_evidence_pack(item, inventory + b" ", reader, policy)
    with pytest.raises(Protocol22EvidenceError, match="scope"):
        build_evidence_pack(item, wrong_inventory, reader, policy)
    with pytest.raises(Protocol22EvidenceError, match="policy"):
        build_evidence_pack(
            item,
            inventory,
            reader,
            replace(policy, max_canonical_json_bytes=policy.max_canonical_json_bytes - 1),
        )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
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
    )


def _real_snapshot(tmp_path: Path):
    workspace = tmp_path / "workspace"
    repo = workspace / "sources" / "api"
    repo.mkdir(parents=True)
    _git(repo, "init")
    (repo / "main.py").write_bytes(b"print('ok')\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    source = SourceRoot(id="api", path="sources/api", git_present=True)
    manifest = WorkspaceManifest(
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
            implementation_digest=digest("partitioner"),
        ),
        ownership_policy=ImplementationAuthorityV1(
            id="explicit-domain-ownership",
            version="1",
            implementation_digest=digest("ownership"),
        ),
    )
    catalog = build_workspace_partition_catalog(snapshot, manifest, authorities)
    return snapshot, catalog


@pytest.mark.unit
def test_pinned_snapshot_reader_verifies_catalog_record(tmp_path: Path) -> None:
    snapshot, catalog = _real_snapshot(tmp_path)
    reader = PinnedSnapshotReaderV1(snapshot, catalog)
    expected = catalog.sources[0].files[0]

    assert reader.read_file("api", "main.py", expected) == b"print('ok')\n"
    with pytest.raises(Protocol22EvidenceError, match="catalog"):
        reader.read_file("api", "main.py", replace(expected, byte_count=999))


@pytest.mark.unit
def test_pinned_snapshot_reader_never_follows_replaced_file_link(tmp_path: Path) -> None:
    snapshot, catalog = _real_snapshot(tmp_path)
    reader = PinnedSnapshotReaderV1(snapshot, catalog)
    expected = catalog.sources[0].files[0]
    target = snapshot.read_root / "sources" / "api" / "main.py"
    outside = tmp_path / "outside.py"
    outside.write_bytes(b"forged\n")
    target.parent.chmod(0o755)
    target.unlink()
    target.symlink_to(outside)

    with pytest.raises(Protocol22EvidenceError, match="safely|link|regular"):
        reader.read_file("api", "main.py", expected)


@pytest.mark.unit
def test_pinned_snapshot_reader_rejects_changed_snapshot_bytes(tmp_path: Path) -> None:
    snapshot, catalog = _real_snapshot(tmp_path)
    reader = PinnedSnapshotReaderV1(snapshot, catalog)
    expected = catalog.sources[0].files[0]
    target = snapshot.read_root / "sources" / "api" / "main.py"
    target.chmod(0o644)
    target.write_bytes(b"print('changed')\n")

    with pytest.raises(Protocol22EvidenceError, match="catalog authority"):
        reader.read_file("api", "main.py", expected)
