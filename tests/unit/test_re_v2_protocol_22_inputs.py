from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from harness.config import HarnessConfig, LlmConfig, ReV2BaselineConfig
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.authorities import InstalledAuthorityRegistry
from harness.re_v2.protocol_22.executors import resolve_executor_catalog
from harness.re_v2.protocol_22.inputs import (
    Protocol22InputSet,
    Protocol22InputStoreError,
    create_protocol_22_run_store,
    load_protocol_22_inputs,
)
from harness.re_v2.protocol_22.model import CatalogReferenceV1, RunManifestV2
from harness.re_v2.protocol_22.partition import (
    DomainDescriptorV1,
    FileRecordV1,
    ImplementationAuthorityV1,
    PartitionAuthoritiesV1,
    SourceDescriptorV1,
    SourcePartitionIdentityInputV1,
    WorkspacePartitionCatalogV1,
    domain_content_id,
    domain_key,
    domain_partition_id,
    source_content_id,
    source_partition_id,
)
from harness.re_v2.protocol_22.policies import build_compact_v1_policy_catalog
from harness.re_v2.protocol_22.response_schemas import (
    canonical_response_schema_bytes,
    response_schema_hash,
)
from harness.re_v2.protocol_22.schema import Protocol22SchemaError
from harness.re_v2.run_store import (
    ReV2Paths,
    ReV2RunStoreError,
    detect_re_engine,
    load_run_manifest,
)
from tests.re_v2_protocol_22_fixtures import digest, manifest_v2


def _input_fixture() -> tuple[Protocol22InputSet, RunManifestV2]:
    partitioner = ImplementationAuthorityV1(
        id="existing-domain-partitioner",
        version="5",
        implementation_digest=digest("partitioner"),
    )
    ownership = ImplementationAuthorityV1(
        id="explicit-domain-ownership",
        version="1",
        implementation_digest=digest("ownership"),
    )
    authorities = PartitionAuthoritiesV1(partitioner, ownership)
    record = FileRecordV1(
        source_relative_path="src/app.py",
        mode="100644",
        object_kind="regular",
        content_hash=content_digest(b"print('ok')\n"),
        byte_count=12,
        line_count=1,
        text_status="eligible_utf8",
    )
    stable_key = domain_key("api", "src", ownership.version)
    partition_id = domain_partition_id(
        partitioner,
        ownership,
        stable_key,
        "src",
        ("app.py",),
        (),
    )
    domain = DomainDescriptorV1(
        domain_key=stable_key,
        presentation_domain_id="001-re-src",
        source_relative_root="src",
        owned_file_count=1,
        owned_line_count=1,
        supporting_file_count=0,
        domain_content_id=domain_content_id(
            ownership.version,
            stable_key,
            "src",
            (record,),
            (),
        ),
        domain_partition_id=partition_id,
        owned_domain_relative_paths=("app.py",),
        supporting_source_relative_paths=(),
    )
    source_partition_input = SourcePartitionIdentityInputV1(
        source_id="api",
        partitioner=partitioner,
        ownership_policy=ownership,
        source_supporting_paths=(),
        domains=(domain.partition_projection(),),
    )
    snapshot_id = digest("workspace-snapshot")
    source = SourceDescriptorV1(
        source_id="api",
        workspace_relative_path="sources/api",
        snapshot_id=snapshot_id,
        source_content_id=source_content_id(
            "declared-clean-git-tree-v1", (record,)
        ),
        source_partition_id=source_partition_id(source_partition_input),
        files=(record,),
        source_supporting_paths=(),
        domains=(domain,),
    )
    workspace_partition = WorkspacePartitionCatalogV1(
        schema_version=1,
        snapshot_id=snapshot_id,
        source_selection_policy_version="declared-clean-git-tree-v1",
        partitioner=partitioner,
        ownership_policy=ownership,
        sources=(source,),
    )
    artifact_policy = build_compact_v1_policy_catalog()

    agent = b"canonical baseliner contract\n"
    domain_schema = canonical_response_schema_bytes("domain-baseline")
    source_schema = canonical_response_schema_bytes("source-overview")
    objects = {
        content_digest(agent): agent,
        content_digest(domain_schema): domain_schema,
        content_digest(source_schema): source_schema,
    }
    registry = InstalledAuthorityRegistry(
        executor_implementations={
            "bounded-api-baseline-v1": digest("api executor"),
            "re-v2-in-process-v1": digest("in-process executor"),
        },
        renderer_implementations={
            "compact-baseline-renderer-v1": digest("renderer"),
        },
        tokenizer_implementations={
            "utf8-byte-upper-bound-v1": digest("tokenizer"),
        },
        calculator_implementations={
            "bounded-dispatch-v1": digest("dispatch calculator"),
            "bounded-in-process-v1": digest("in-process calculator"),
        },
        normalizer_implementations={
            "deterministic-zero-usage-v1": digest("zero normalizer"),
            "openai-usage-v1": digest("openai normalizer"),
        },
        verifier_implementations={},
        partitioner_implementations={},
        ownership_implementations={},
        agent_contracts={"echelon.re-baseliner": content_digest(agent)},
        response_schemas={
            "domain-baseline": response_schema_hash("domain-baseline"),
            "source-overview": response_schema_hash("source-overview"),
        },
    )
    config = HarnessConfig(
        provider="docker",
        llm=LlmConfig(
            enabled=True,
            cli="openai-compatible",
            base_url="https://api.example.test/v1",
            model="gpt-example",
            temperature=0.2,
            max_tokens=8192,
            timeout_ms=300_000,
            re_v2_baseline=ReV2BaselineConfig(
                model_revision="gpt-example-2026-08-01",
                revision_authority="provider_resolved_revision",
                provider_context_tokens=200_000,
            ),
        ),
    )
    executor_contract = resolve_executor_catalog(config, "baseline", registry)
    inputs = Protocol22InputSet(
        workspace_partition=workspace_partition,
        artifact_policy=artifact_policy,
        executor_contract=executor_contract,
        immutable_objects=objects,
    )
    workspace_bytes = canonical_json_bytes(workspace_partition.to_json_dict())
    policy_bytes = canonical_json_bytes(artifact_policy.to_json_dict())
    executor_bytes = canonical_json_bytes(executor_contract.to_json_dict())
    base = manifest_v2(run_id="re-inputs")
    manifest = replace(
        base,
        source_snapshot_id=snapshot_id,
        workspace_partition_catalog=CatalogReferenceV1(
            object_hash=content_digest(workspace_bytes),
            relative_path="workspace-partition.json",
        ),
        artifact_policy_catalog=CatalogReferenceV1(
            object_hash=content_digest(policy_bytes),
            relative_path="artifact-policy.json",
        ),
        executor_contract_catalog=CatalogReferenceV1(
            object_hash=content_digest(executor_bytes),
            relative_path="executor-contract.json",
        ),
    )
    return inputs, manifest


@pytest.mark.unit
def test_protocol_22_manifest_is_published_after_every_input(tmp_path: Path) -> None:
    inputs, manifest = _input_fixture()
    seen: list[str] = []

    paths = create_protocol_22_run_store(
        tmp_path / "runs" / manifest.run_id,
        manifest,
        inputs,
        fault_hook=seen.append,
    )

    assert seen[-1] == "manifest_published"
    object_events = [point for point in seen if point.startswith("object_published:")]
    assert len(object_events) == 3
    assert max(seen.index(point) for point in object_events) < seen.index(
        "catalog_published:workspace_partition"
    )
    assert seen.index("inputs_fsynced") < seen.index("manifest_temporary_fsynced")
    assert seen.index("manifest_temporary_fsynced") < seen.index("manifest_linked")
    assert paths.manifest.is_file()
    assert not (paths.root / "active.json").exists()
    assert not (paths.root.parent / "active.json").exists()
    assert load_run_manifest(paths.root.parent) == manifest


@pytest.mark.unit
def test_protocol_22_inputs_round_trip_exact_catalogs_and_objects(
    tmp_path: Path,
) -> None:
    inputs, manifest = _input_fixture()
    paths = create_protocol_22_run_store(
        tmp_path / "runs" / manifest.run_id,
        manifest,
        inputs,
    )

    loaded = load_protocol_22_inputs(paths, manifest)

    assert loaded.workspace_partition == inputs.workspace_partition
    assert loaded.artifact_policy == inputs.artifact_policy
    assert loaded.executor_contract == inputs.executor_contract
    assert dict(loaded.immutable_objects) == dict(inputs.immutable_objects)


@pytest.mark.unit
@pytest.mark.parametrize(
    "relative",
    ("/absolute.json", "../escape.json", "nested/../x.json"),
)
def test_catalog_reference_rejects_unsafe_path(relative: str) -> None:
    with pytest.raises(Protocol22SchemaError, match="relative_path"):
        CatalogReferenceV1(object_hash=digest("catalog"), relative_path=relative)


@pytest.mark.unit
def test_creation_rejects_catalog_hash_mismatch_before_mutation(tmp_path: Path) -> None:
    inputs, manifest = _input_fixture()
    manifest = replace(
        manifest,
        workspace_partition_catalog=replace(
            manifest.workspace_partition_catalog,
            object_hash=digest("wrong workspace catalog"),
        ),
    )
    run_dir = tmp_path / "runs" / manifest.run_id

    with pytest.raises(Protocol22InputStoreError, match="workspace partition.*hash"):
        create_protocol_22_run_store(run_dir, manifest, inputs)

    assert not (run_dir / "v2").exists()


@pytest.mark.unit
def test_creation_rejects_overlapping_catalog_paths_before_mutation(
    tmp_path: Path,
) -> None:
    inputs, manifest = _input_fixture()
    manifest = replace(
        manifest,
        workspace_partition_catalog=replace(
            manifest.workspace_partition_catalog,
            relative_path="catalogs",
        ),
        artifact_policy_catalog=replace(
            manifest.artifact_policy_catalog,
            relative_path="catalogs/policy.json",
        ),
    )
    run_dir = tmp_path / "runs" / manifest.run_id

    with pytest.raises(Protocol22InputStoreError, match="overlap"):
        create_protocol_22_run_store(run_dir, manifest, inputs)

    assert not (run_dir / "v2").exists()


@pytest.mark.unit
def test_creation_rejects_missing_or_extra_nested_objects_before_mutation(
    tmp_path: Path,
) -> None:
    inputs, manifest = _input_fixture()
    missing = dict(inputs.immutable_objects)
    missing.pop(next(iter(missing)))
    run_dir = tmp_path / "runs" / manifest.run_id

    with pytest.raises(Protocol22InputStoreError, match="immutable object set"):
        create_protocol_22_run_store(
            run_dir,
            manifest,
            replace(inputs, immutable_objects=missing),
        )
    assert not (run_dir / "v2").exists()

    extra_payload = b"unreferenced\n"
    extra = {
        **inputs.immutable_objects,
        content_digest(extra_payload): extra_payload,
    }
    with pytest.raises(Protocol22InputStoreError, match="immutable object set"):
        create_protocol_22_run_store(
            run_dir,
            manifest,
            replace(inputs, immutable_objects=extra),
        )
    assert not (run_dir / "v2").exists()


@pytest.mark.unit
@pytest.mark.parametrize("object_number", (1, 2, 3))
def test_fault_after_each_object_leaves_no_manifest(
    tmp_path: Path,
    object_number: int,
) -> None:
    inputs, manifest = _input_fixture()
    run_dir = tmp_path / "runs" / manifest.run_id
    observed = 0

    def fail(point: str) -> None:
        nonlocal observed
        if not point.startswith("object_published:"):
            return
        observed += 1
        if observed == object_number:
            raise RuntimeError(f"fault after object {object_number}")

    with pytest.raises(RuntimeError, match="fault after object"):
        create_protocol_22_run_store(
            run_dir,
            manifest,
            inputs,
            fault_hook=fail,
        )

    assert observed == object_number
    assert not (run_dir / "v2" / "run.json").exists()
    with pytest.raises(ReV2RunStoreError, match="incomplete"):
        detect_re_engine(run_dir)


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure_point",
    (
        "catalog_published:workspace_partition",
        "catalog_published:artifact_policy",
        "catalog_published:executor_contract",
        "inputs_fsynced",
        "manifest_temporary_fsynced",
    ),
)
def test_pre_manifest_faults_leave_an_explicitly_incomplete_store(
    tmp_path: Path,
    failure_point: str,
) -> None:
    inputs, manifest = _input_fixture()
    run_dir = tmp_path / "runs" / manifest.run_id

    def fail(point: str) -> None:
        if point == failure_point:
            raise RuntimeError(f"fault at {point}")

    with pytest.raises(RuntimeError, match="fault"):
        create_protocol_22_run_store(
            run_dir,
            manifest,
            inputs,
            fault_hook=fail,
        )

    assert not (run_dir / "active.json").exists()
    with pytest.raises(ReV2RunStoreError, match="incomplete"):
        detect_re_engine(run_dir)


@pytest.mark.unit
@pytest.mark.parametrize("failure_point", ("manifest_linked", "run_directory_fsynced"))
def test_post_link_fault_never_overwrites_the_complete_store(
    tmp_path: Path,
    failure_point: str,
) -> None:
    inputs, manifest = _input_fixture()
    run_dir = tmp_path / "runs" / manifest.run_id
    paths = ReV2Paths.for_run(run_dir)

    def fail(point: str) -> None:
        if point == failure_point:
            raise RuntimeError(f"fault at {point}")

    with pytest.raises(RuntimeError, match="fault"):
        create_protocol_22_run_store(
            run_dir,
            manifest,
            inputs,
            fault_hook=fail,
        )

    assert load_run_manifest(run_dir) == manifest
    assert load_protocol_22_inputs(paths, manifest).workspace_partition == (
        inputs.workspace_partition
    )
    with pytest.raises(Protocol22InputStoreError, match="already exists"):
        create_protocol_22_run_store(run_dir, manifest, inputs)


@pytest.mark.unit
def test_load_rejects_symlinked_catalog_and_corrupt_object(tmp_path: Path) -> None:
    inputs, manifest = _input_fixture()
    paths = create_protocol_22_run_store(
        tmp_path / "runs" / manifest.run_id,
        manifest,
        inputs,
    )
    catalog = paths.inputs / manifest.workspace_partition_catalog.relative_path
    outside = tmp_path / "outside.json"
    outside.write_bytes(catalog.read_bytes())
    catalog.unlink()
    catalog.symlink_to(outside)

    with pytest.raises(Protocol22InputStoreError, match="symlink"):
        load_protocol_22_inputs(paths, manifest)

    # Restore the catalog, then prove every renderer object is authenticated.
    catalog.unlink()
    catalog.write_bytes(outside.read_bytes())
    object_hash = next(iter(inputs.immutable_objects))
    suffix = object_hash.removeprefix("sha256:")
    object_path = paths.objects / "sha256" / suffix[:2] / suffix[2:]
    object_path.chmod(0o600)
    object_path.write_bytes(b"corrupt\n")
    with pytest.raises(Protocol22InputStoreError, match="object hash mismatch"):
        load_protocol_22_inputs(paths, manifest)


@pytest.mark.unit
def test_load_rejects_manifest_argument_that_is_not_store_authority(
    tmp_path: Path,
) -> None:
    inputs, manifest = _input_fixture()
    paths = create_protocol_22_run_store(
        tmp_path / "runs" / manifest.run_id,
        manifest,
        inputs,
    )
    forged = replace(manifest, partition_manifest_id=digest("forged"))

    with pytest.raises(Protocol22InputStoreError, match="authoritative manifest"):
        load_protocol_22_inputs(paths, forged)


@pytest.mark.unit
def test_create_protocol_22_store_is_no_clobber(tmp_path: Path) -> None:
    inputs, manifest = _input_fixture()
    run_dir = tmp_path / "runs" / manifest.run_id
    create_protocol_22_run_store(run_dir, manifest, inputs)

    with pytest.raises(Protocol22InputStoreError, match="already exists"):
        create_protocol_22_run_store(run_dir, manifest, inputs)

    assert json.loads((run_dir / "v2" / "run.json").read_text())["run_id"] == manifest.run_id
