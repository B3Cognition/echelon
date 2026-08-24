from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.model import CatalogReferenceV1
from harness.re_v2.protocol_24.inputs import (
    Protocol24InputSet,
    Protocol24InputStoreError,
    create_protocol_24_run_store,
    load_protocol_24_inputs,
)
from harness.re_v2.protocol_24.model import (
    AdoptedArtifactAuthorityV1,
    ParentAuthorityBundleV1,
)
from harness.re_v2.protocol_24.policies import build_deepening_v1_policy_catalog
from harness.re_v2.run_store import load_run_manifest
from tests.re_v2_protocol_22_fixtures import digest
from tests.re_v2_protocol_24_fixtures import manifest_v3
from tests.unit.test_re_v2_protocol_22_inputs import _input_fixture


def _fixture() -> tuple[Protocol24InputSet, object]:
    inherited, _manifest = _input_fixture()
    policy = build_deepening_v1_policy_catalog()
    manifest_payload = b'{"parent":"manifest"}\n'
    events_payload = b'{"parent":"events"}\n'
    ledger_payload = b'{"parent":"ledger"}\n'
    artifact = AdoptedArtifactAuthorityV1(
        schema_version=1,
        artifact_key_id=digest("parent-key"),
        artifact_hash=digest("parent-artifact"),
        dependency_hashes=(),
        certification_receipt_id=digest("parent-certification"),
        candidate_assessment_id=None,
        artifact_acceptance_receipt_id=digest("parent-acceptance"),
        source_run_id="re-parent",
        source_ledger_entry_hash=digest("parent-ledger-entry"),
    )
    bundle = ParentAuthorityBundleV1(
        schema_version=1,
        direct_parent_run_id="re-parent",
        source_manifest_hash=content_digest(manifest_payload),
        source_event_chain_hash=content_digest(events_payload),
        source_terminal_event_hash=digest("parent-terminal"),
        source_ledger_chain_hash=content_digest(ledger_payload),
        lineage_root_run_id="re-parent",
        ancestor_bundle_hashes=(),
        artifacts=(artifact,),
    )
    objects = {
        **dict(inherited.immutable_objects),
        content_digest(manifest_payload): manifest_payload,
        content_digest(events_payload): events_payload,
        content_digest(ledger_payload): ledger_payload,
    }
    inputs = Protocol24InputSet(
        workspace_partition=inherited.workspace_partition,
        artifact_policy=policy,
        executor_contract=inherited.executor_contract,
        immutable_objects=objects,
        parent_authority_bundle=bundle,
    )
    base = manifest_v3(run_id="re-child-inputs")
    manifest = replace(
        base,
        source_snapshot_id=inherited.workspace_partition.snapshot_id,
        workspace_partition_catalog=CatalogReferenceV1(
            inherited.workspace_partition.identity,
            "workspace-partition.json",
        ),
        artifact_policy_catalog=CatalogReferenceV1(
            policy.identity,
            "artifact-policy.json",
        ),
        executor_contract_catalog=CatalogReferenceV1(
            inherited.executor_contract.identity,
            "executor-contract.json",
        ),
        parent_authority_bundle=CatalogReferenceV1(
            bundle.identity,
            "parent-authority.json",
        ),
        parent_lineage=replace(
            base.parent_lineage,
            direct_parent_run_id=bundle.direct_parent_run_id,
            direct_parent_manifest_hash=bundle.source_manifest_hash,
            direct_parent_terminal_event_hash=bundle.source_terminal_event_hash,
            lineage_root_run_id=bundle.lineage_root_run_id,
        ),
    )
    return inputs, manifest


def test_protocol24_manifest_is_published_after_all_four_inputs(tmp_path: Path) -> None:
    inputs, manifest = _fixture()
    seen: list[str] = []

    paths = create_protocol_24_run_store(
        tmp_path / "runs" / manifest.run_id,
        manifest,
        inputs,
        fault_hook=seen.append,
    )

    assert seen[-1] == "manifest_published"
    assert seen.index("catalog_published:parent_authority") < seen.index(
        "inputs_fsynced"
    )
    assert seen.index("inputs_fsynced") < seen.index("manifest_linked")
    assert load_run_manifest(paths.root.parent) == manifest


def test_protocol24_inputs_round_trip_exact_catalogs_bundle_and_objects(
    tmp_path: Path,
) -> None:
    inputs, manifest = _fixture()
    paths = create_protocol_24_run_store(
        tmp_path / "runs" / manifest.run_id,
        manifest,
        inputs,
    )

    loaded = load_protocol_24_inputs(paths, manifest)

    assert loaded.workspace_partition == inputs.workspace_partition
    assert loaded.artifact_policy == inputs.artifact_policy
    assert loaded.executor_contract == inputs.executor_contract
    assert loaded.parent_authority_bundle == inputs.parent_authority_bundle
    assert dict(loaded.immutable_objects) == dict(inputs.immutable_objects)


def test_protocol24_creation_rejects_bundle_hash_mismatch_before_mutation(
    tmp_path: Path,
) -> None:
    inputs, manifest = _fixture()
    forged = replace(
        manifest,
        parent_authority_bundle=replace(
            manifest.parent_authority_bundle,
            object_hash=digest("wrong-bundle"),
        ),
    )
    run_dir = tmp_path / "runs" / forged.run_id

    with pytest.raises(Protocol24InputStoreError, match="parent authority.*hash"):
        create_protocol_24_run_store(run_dir, forged, inputs)
    assert not (run_dir / "v2").exists()


def test_protocol24_creation_rejects_bundle_lineage_mismatch(tmp_path: Path) -> None:
    inputs, manifest = _fixture()
    forged = replace(
        manifest,
        parent_lineage=replace(
            manifest.parent_lineage,
            direct_parent_terminal_event_hash=digest("wrong-terminal"),
        ),
    )

    with pytest.raises(Protocol24InputStoreError, match="lineage"):
        create_protocol_24_run_store(
            tmp_path / "runs" / forged.run_id,
            forged,
            inputs,
        )


def test_protocol24_fault_before_manifest_leaves_no_authoritative_manifest(
    tmp_path: Path,
) -> None:
    inputs, manifest = _fixture()
    run_dir = tmp_path / "runs" / manifest.run_id

    def fail(point: str) -> None:
        if point == "inputs_fsynced":
            raise RuntimeError("fault")

    with pytest.raises(RuntimeError, match="fault"):
        create_protocol_24_run_store(run_dir, manifest, inputs, fault_hook=fail)

    assert (run_dir / "v2").is_dir()
    assert not (run_dir / "v2" / "run.json").exists()


def test_protocol24_input_reference_cannot_escape_or_alias(tmp_path: Path) -> None:
    inputs, manifest = _fixture()
    forged = replace(
        manifest,
        parent_authority_bundle=CatalogReferenceV1(
            manifest.parent_authority_bundle.object_hash,
            "workspace-partition.json/child",
        ),
    )

    with pytest.raises(Protocol24InputStoreError, match="overlap|alias"):
        create_protocol_24_run_store(
            tmp_path / "runs" / forged.run_id,
            forged,
            inputs,
        )
