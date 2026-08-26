from __future__ import annotations

from dataclasses import replace
import importlib
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.executors import (
    ExecutorContractCatalogV1,
    ResponseSchemaReferenceV1,
)
from harness.re_v2.protocol_22.model import CatalogReferenceV1
from harness.re_v2.protocol_25.adoption import (
    ParentAuthorityBundleV2,
    ParentSemanticAuthorityV1,
)
from harness.re_v2.protocol_25.inputs import (
    Protocol25InputSet,
    Protocol25InputStoreError,
    create_protocol_25_run_store,
    load_protocol_25_inputs,
)
from harness.re_v2.protocol_25.policies import (
    SEMANTIC_EXECUTOR_FAMILIES,
    SemanticExecutorAuthorityV1,
    build_semantic_executor_catalog,
    build_semantic_v1_policy_catalog,
)
from harness.re_v2.run_store import ReV2Paths, ReV2RunStoreError, load_run_manifest
from tests.re_v2_protocol_22_fixtures import digest
from tests.re_v2_protocol_25_fixtures import (
    audit_candidate_v1,
    audit_epoch_v1,
    lower_parent_authority_bundle_v1,
    manifest_v4,
)
from tests.unit.test_re_v2_protocol_22_executors import _shared_cli_entry
from tests.unit.test_re_v2_protocol_22_inputs import _input_fixture


def _executor_fixture():  # type: ignore[no-untyped-def]
    baseline_agent = b"authenticated baseline agent\n"
    baseline_domain_schema = canonical_json_bytes({"kind": "domain-baseline"})
    baseline_source_schema = canonical_json_bytes({"kind": "source-overview"})
    baseline = _shared_cli_entry()
    assert baseline.request_renderer is not None
    baseline = replace(
        baseline,
        request_renderer=replace(
            baseline.request_renderer,
            agent_contract_hash=content_digest(baseline_agent),
            response_schemas=(
                ResponseSchemaReferenceV1(
                    "domain-baseline", content_digest(baseline_domain_schema)
                ),
                ResponseSchemaReferenceV1(
                    "source-overview", content_digest(baseline_source_schema)
                ),
            ),
        ),
    )
    inherited = ExecutorContractCatalogV1(1, (baseline,))
    objects = {
        content_digest(baseline_agent): baseline_agent,
        content_digest(baseline_domain_schema): baseline_domain_schema,
        content_digest(baseline_source_schema): baseline_source_schema,
    }
    authorities = []
    for family in SEMANTIC_EXECUTOR_FAMILIES:
        agent = f"authenticated {family} Prosaic role\n".encode()
        schema = canonical_json_bytes({"kind": family, "type": "object"})
        objects[content_digest(agent)] = agent
        objects[content_digest(schema)] = schema
        authorities.append(
            SemanticExecutorAuthorityV1(
                schema_version=1,
                producer_family=family,
                agent_contract_hash=content_digest(agent),
                response_schema_kind=(
                    "semantic-audit-findings"
                    if family == "semantic-audit"
                    else "semantic-resolution-overlay"
                    if family == "semantic-resolution"
                    else "semantic-closure-assessment"
                ),
                response_schema_hash=content_digest(schema),
                verifier_id=f"{family}-verifier-v1",
                verifier_implementation_digest=digest(f"{family}-verifier"),
                result_contract_id=f"{family}-candidate-ready-v1",
            )
        )
    return build_semantic_executor_catalog(inherited, tuple(authorities)), objects


def _fixture(*, mode: str = "new-audit-epoch"):  # type: ignore[no-untyped-def]
    inherited, _ = _input_fixture()
    policy = build_semantic_v1_policy_catalog()
    executor, executor_objects = _executor_fixture()
    base = manifest_v4(run_id=f"re-l3-inputs-{mode}", run_mode=mode)

    parent_manifest = b'{"parent":"manifest"}\n'
    parent_events = b'{"parent":"events"}\n'
    parent_ledger = b'{"parent":"ledger"}\n'
    lower = replace(
        lower_parent_authority_bundle_v1(),
        source_manifest_hash=content_digest(parent_manifest),
        source_event_chain_hash=content_digest(parent_events),
        source_ledger_chain_hash=content_digest(parent_ledger),
        lineage_root_run_id="re-parent",
        ancestor_bundle_hashes=(),
    )
    objects = {
        **executor_objects,
        content_digest(parent_manifest): parent_manifest,
        content_digest(parent_events): parent_events,
        content_digest(parent_ledger): parent_ledger,
    }

    frozen_epoch = None
    guidance = None
    parent_state = "complete"
    parent_layer = "L2"
    semantic = ParentSemanticAuthorityV1.empty()
    if mode == "audit-successor":
        candidate = audit_candidate_v1()
        candidate_payload = canonical_json_bytes(candidate.to_json_dict())
        objects[candidate.identity] = candidate_payload
        parent_state = "blocked_incomplete"
        parent_layer = "L3"
        semantic = ParentSemanticAuthorityV1(
            1,
            (candidate.audit_target_id,),
            (candidate.identity,),
            (digest("missing-audit-target"),),
            None,
            (),
            (),
            (),
            (),
            None,
            (),
            (),
            (),
        )
        guidance = canonical_json_bytes(
            {"answer": "Use the authenticated bounded context.", "schema_version": 1}
        )
    elif mode == "closure-successor":
        candidate = audit_candidate_v1()
        candidate_payload = canonical_json_bytes(candidate.to_json_dict())
        objects[candidate.identity] = candidate_payload
        frozen_epoch = replace(
            audit_epoch_v1(candidate=candidate),
            selection_id=base.selection.identity,
            audit_policy_hash=policy.audit_taxonomy.identity,
        )
        objects[frozen_epoch.identity] = canonical_json_bytes(
            frozen_epoch.to_json_dict()
        )
        closure_payloads = {
            name: canonical_json_bytes({"kind": name, "schema_version": 1})
            for name in (
                "overlay",
                "target-assessment",
                "source-assessment",
                "closure-receipt",
                "closure-root",
                "l3-source-root",
            )
        }
        objects.update(
            {content_digest(payload): payload for payload in closure_payloads.values()}
        )
        semantic = ParentSemanticAuthorityV1(
            1,
            (candidate.audit_target_id,),
            (candidate.identity,),
            (),
            frozen_epoch.identity,
            (content_digest(closure_payloads["overlay"]),),
            (content_digest(closure_payloads["target-assessment"]),),
            (content_digest(closure_payloads["source-assessment"]),),
            (content_digest(closure_payloads["closure-receipt"]),),
            content_digest(closure_payloads["closure-root"]),
            (candidate.findings[0].finding_key_id,),
            (),
            (content_digest(closure_payloads["l3-source-root"]),),
        )
        parent_state = "blocked_plateau"
        parent_layer = "L3"
        guidance = canonical_json_bytes(
            {"answer": "Resolve the frozen retry finding.", "schema_version": 1}
        )

    parent = ParentAuthorityBundleV2(
        schema_version=2,
        parent_layer=parent_layer,
        parent_state=parent_state,
        source_snapshot_id=inherited.workspace_partition.snapshot_id,
        selection_id=base.selection.identity,
        lower_authority_bundle=lower,
        semantic_authority=semantic,
    )
    manifest = replace(
        base,
        source_snapshot_id=inherited.workspace_partition.snapshot_id,
        workspace_partition_catalog=CatalogReferenceV1(
            inherited.workspace_partition.identity, "workspace-partition.json"
        ),
        artifact_policy_catalog=CatalogReferenceV1(
            policy.identity, "artifact-policy.json"
        ),
        executor_contract_catalog=CatalogReferenceV1(
            executor.identity, "executor-contract.json"
        ),
        audit_policy_catalog=CatalogReferenceV1(
            policy.audit_taxonomy.identity, "audit-policy.json"
        ),
        parent_authority_bundle=CatalogReferenceV1(
            parent.identity, "parent-authority-v2.json"
        ),
        parent_lineage=replace(
            base.parent_lineage,
            direct_parent_run_id=lower.direct_parent_run_id,
            direct_parent_manifest_hash=lower.source_manifest_hash,
            direct_parent_terminal_event_hash=lower.source_terminal_event_hash,
            lineage_root_run_id=lower.lineage_root_run_id,
        ),
        frozen_audit_epoch=(
            None
            if frozen_epoch is None
            else CatalogReferenceV1(frozen_epoch.identity, "audit-epoch.json")
        ),
        human_guidance=(
            None
            if guidance is None
            else CatalogReferenceV1(content_digest(guidance), "human-guidance.json")
        ),
    )
    inputs = Protocol25InputSet(
        workspace_partition=inherited.workspace_partition,
        artifact_policy=policy,
        executor_contract=executor,
        audit_policy=policy.audit_taxonomy,
        parent_authority_bundle=parent,
        immutable_objects=objects,
        frozen_audit_epoch=frozen_epoch,
        human_guidance=guidance,
    )
    return inputs, manifest


def test_schema4_manifest_is_published_after_every_input(tmp_path: Path) -> None:
    inputs, manifest = _fixture()
    seen: list[str] = []

    paths = create_protocol_25_run_store(
        tmp_path / "runs" / manifest.run_id,
        manifest,
        inputs,
        fault_hook=seen.append,
    )

    assert seen[-1] == "manifest_published"
    for name in (
        "workspace_partition",
        "artifact_policy",
        "executor_contract",
        "audit_policy",
        "parent_authority",
    ):
        assert seen.index(f"catalog_published:{name}") < seen.index("inputs_fsynced")
    for object_hash in inputs.immutable_objects:
        assert seen.index(f"object_published:{object_hash}") < seen.index(
            "inputs_fsynced"
        )
    assert seen.index("inputs_fsynced") < seen.index("manifest_linked")
    assert load_run_manifest(paths.root.parent) == manifest


@pytest.mark.parametrize(
    ("mode", "has_epoch", "has_guidance"),
    (
        ("new-audit-epoch", False, False),
        ("audit-successor", False, True),
        ("closure-successor", True, True),
    ),
)
def test_schema4_inputs_round_trip_mode_specific_authority(
    tmp_path: Path,
    mode: str,
    has_epoch: bool,
    has_guidance: bool,
) -> None:
    inputs, manifest = _fixture(mode=mode)
    paths = create_protocol_25_run_store(
        tmp_path / "runs" / manifest.run_id, manifest, inputs
    )

    loaded = load_protocol_25_inputs(paths, manifest)

    assert loaded.workspace_partition == inputs.workspace_partition
    assert loaded.artifact_policy == inputs.artifact_policy
    assert loaded.executor_contract == inputs.executor_contract
    assert loaded.audit_policy == inputs.audit_policy
    assert loaded.parent_authority_bundle == inputs.parent_authority_bundle
    assert dict(loaded.immutable_objects) == dict(inputs.immutable_objects)
    assert (loaded.frozen_audit_epoch is not None) is has_epoch
    assert (loaded.human_guidance is not None) is has_guidance
    assert loaded.graph_inputs.workspace_partition == loaded.workspace_partition


@pytest.mark.parametrize(
    ("mode", "mutation", "message"),
    (
        ("new-audit-epoch", {"human_guidance": b'{"answer":"extra"}\n'}, "new audit"),
        ("audit-successor", {"human_guidance": None}, "guidance"),
        ("audit-successor", {"frozen_audit_epoch": audit_epoch_v1()}, "audit successor"),
        ("closure-successor", {"frozen_audit_epoch": None}, "closure successor"),
        ("closure-successor", {"human_guidance": None}, "closure successor"),
    ),
)
def test_mode_specific_optional_input_mismatch_fails_before_mutation(
    tmp_path: Path,
    mode: str,
    mutation: dict[str, object],
    message: str,
) -> None:
    inputs, manifest = _fixture(mode=mode)
    invalid = replace(inputs, **mutation)
    run_dir = tmp_path / "runs" / manifest.run_id

    with pytest.raises(Protocol25InputStoreError, match=message):
        create_protocol_25_run_store(run_dir, manifest, invalid)

    assert not (run_dir / "v2").exists()


def test_catalogs_authenticate_before_inputs_are_exposed(tmp_path: Path) -> None:
    inputs, manifest = _fixture()
    paths = create_protocol_25_run_store(
        tmp_path / "runs" / manifest.run_id, manifest, inputs
    )
    policy_path = paths.inputs / manifest.audit_policy_catalog.relative_path
    policy_path.chmod(0o600)
    policy_path.write_bytes(b'{"forged":true}\n')

    with pytest.raises(Protocol25InputStoreError, match="audit policy.*hash"):
        load_protocol_25_inputs(paths, manifest)


def test_every_publication_fault_is_absent_or_fully_loadable(tmp_path: Path) -> None:
    baseline_inputs, baseline_manifest = _fixture()
    seen: list[str] = []
    create_protocol_25_run_store(
        tmp_path / "baseline" / baseline_manifest.run_id,
        baseline_manifest,
        baseline_inputs,
        fault_hook=seen.append,
    )

    for index, point in enumerate(dict.fromkeys(seen)):
        inputs, manifest = _fixture()
        manifest = replace(manifest, run_id=f"re-l3-fault-{index}")
        run_dir = tmp_path / "faults" / manifest.run_id

        def fail(current: str, *, selected: str = point) -> None:
            if current == selected:
                raise RuntimeError(f"fault:{selected}")

        with pytest.raises(RuntimeError, match="fault:"):
            create_protocol_25_run_store(run_dir, manifest, inputs, fault_hook=fail)

        try:
            authoritative = load_run_manifest(run_dir)
        except ReV2RunStoreError:
            assert not (run_dir / "v2" / "run.json").exists()
        else:
            load_protocol_25_inputs(
                ReV2Paths.for_run(run_dir),
                authoritative,
            )


def test_incomplete_existing_and_symlinked_stores_fail_closed(tmp_path: Path) -> None:
    inputs, manifest = _fixture()
    incomplete = tmp_path / "runs" / manifest.run_id
    (incomplete / "v2").mkdir(parents=True)

    with pytest.raises(Protocol25InputStoreError, match="incomplete"):
        create_protocol_25_run_store(incomplete, manifest, inputs)

    target = tmp_path / "real-run"
    target.mkdir()
    linked = tmp_path / "linked-run"
    linked.symlink_to(target, target_is_directory=True)
    linked_manifest = replace(manifest, run_id=linked.name)
    with pytest.raises(Protocol25InputStoreError, match="symlink"):
        create_protocol_25_run_store(linked, linked_manifest, inputs)


def test_existing_manifest_is_never_clobbered(tmp_path: Path) -> None:
    inputs, manifest = _fixture()
    run_dir = tmp_path / "runs" / manifest.run_id
    create_protocol_25_run_store(run_dir, manifest, inputs)

    with pytest.raises(Protocol25InputStoreError, match="already exists"):
        create_protocol_25_run_store(run_dir, manifest, inputs)


def test_protocol_package_exports_schema4_input_contract() -> None:
    protocol = importlib.import_module("harness.re_v2.protocol_25")

    assert protocol.Protocol25InputSet is Protocol25InputSet
    assert protocol.create_protocol_25_run_store is create_protocol_25_run_store
