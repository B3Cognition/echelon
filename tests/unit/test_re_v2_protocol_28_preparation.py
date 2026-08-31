from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_24.model import SelectionScopeV1
from harness.re_v2.protocol_28.authority import (
    ValidatedL3ParentV1,
    ValidatedL3TargetV1,
)
from harness.re_v2.protocol_28.executors import build_l4_executor_catalog
from harness.re_v2.protocol_28.lifecycle import (
    Protocol28PreparationOptions,
    create_or_reuse_protocol_28_child,
    prepare_protocol_28_request,
)
from harness.re_v2.protocol_28.orchestration import DeepenOrchestrationRequestV1
from harness.re_v2.protocol_28.policies import build_initial_exhaustive_policy
from harness.re_v2.protocol_28.preparation import Protocol28PreparationError
from harness.re_v2.protocol_28.context import load_protocol_28_run_context
from tests.unit.test_re_v2_protocol_28_evidence import _fixture


def _authority(values: dict[str, bytes], seed: str) -> str:
    payload = seed.encode("utf-8")
    object_id = content_digest(payload)
    values[object_id] = payload
    return object_id


def _preparation_fixture(tmp_path: Path):  # type: ignore[no-untyped-def]
    snapshot, partition = _fixture(
        tmp_path,
        {
            "README.md": "API service\n",
            "src/orders/handler.py": "def handle():\n    return 'ok'\n",
        },
    )
    workspace = tmp_path / "workspace"
    domain = partition.sources[0].domains[0]
    selection = SelectionScopeV1(1, False, ("api",), (domain.domain_key,))
    objects: dict[str, bytes] = {}
    epoch = _authority(objects, "epoch")
    manifest_hash = _authority(objects, "l3-manifest")
    terminal_hash = _authority(objects, "l3-terminal")
    artifact_policy = _authority(objects, "artifact-policy")
    partition_manifest = _authority(objects, "partition-manifest")
    lower = _authority(objects, "lower-authority")
    audit = _authority(objects, "audit-policy")
    executor = _authority(objects, "executor-policy")

    def target(kind: str, target_id: str, content_id: str) -> ValidatedL3TargetV1:
        candidate = _authority(objects, f"{kind}:{target_id}:candidate")
        root = _authority(objects, f"{kind}:{target_id}:l2-root")
        epoch_entry = _authority(objects, f"{kind}:{target_id}:epoch-entry")
        return ValidatedL3TargetV1(
            1,
            kind,  # type: ignore[arg-type]
            "api",
            target_id,
            content_id,
            candidate,
            (),
            (),
            (),
            (),
            "complete",
            (root,),
            audit,
            executor,
            epoch,
            epoch_entry,
        )

    source = partition.sources[0]
    parent = ValidatedL3ParentV1(
        1,
        "re-l3-parent",
        manifest_hash,
        terminal_hash,
        snapshot.snapshot_id,
        partition_manifest,
        selection.identity,
        epoch,
        "complete",
        (),
        partition.identity,
        artifact_policy,
        (lower,),
        tuple(
            sorted(
                (
                    target("domain", domain.domain_key, domain.domain_content_id),
                    target("source", "api", source.source_content_id),
                ),
                key=lambda item: item.sort_key,
            )
        ),
    )
    producer = b"installed-l4-producer"
    verifier = b"installed-l4-verifier"
    inherited = b"shared-cli-executor"
    policy = build_initial_exhaustive_policy(
        producer_contract_hash=content_digest(producer),
        verifier_contract_hash=content_digest(verifier),
    )
    executors = build_l4_executor_catalog(
        inherited_executor_contract_hash=content_digest(inherited),
        producer_agent_contract_hash=content_digest(producer),
        verifier_agent_contract_hash=content_digest(verifier),
    )
    intent = DeepenOrchestrationRequestV1(
        1,
        "re-input",
        _authority(objects, "input-manifest"),
        _authority(objects, "input-terminal"),
        snapshot.snapshot_id,
        partition_manifest,
        selection,
        policy.identity,
        executors.identity,
        _authority(objects, "l3-prerequisite-request"),
    )
    lineage_root_hash = _authority(objects, "lineage-root-manifest")
    options = Protocol28PreparationOptions(
        run_id="re-l4-prepared",
        created_at="2026-08-31T12:00:00Z",
        snapshot=snapshot,
        workspace_partition=partition,
        inherited_executor_contract_bytes=inherited,
        lineage_root_run_id="re-l0-root",
        lineage_root_manifest_hash=lineage_root_hash,
        authority_objects=objects,
        token_limit=400_000,
        active_ms_limit=600_000,
        producer_agent_bytes=producer,
        verifier_agent_bytes=verifier,
    )
    return workspace, intent, parent, options


@pytest.mark.unit
def test_preparation_builds_publishable_self_contained_exact_child(
    tmp_path: Path,
) -> None:
    workspace, intent, parent, options = _preparation_fixture(tmp_path)

    inputs = prepare_protocol_28_request(workspace, intent, parent, options)
    run_dir = create_or_reuse_protocol_28_child(workspace, inputs)

    assert inputs.manifest.exhaustive_request.selection_id == intent.selection.identity
    assert inputs.exhaustive_plan.target_plans
    assert (run_dir / "v2" / "run.json").is_file()
    assert inputs.executor_catalog.identity == intent.executor_catalog_id
    assert inputs.exhaustive_policy.identity == intent.exhaustive_policy_catalog_id


@pytest.mark.unit
def test_preparation_stops_on_dirty_source_with_actionable_guidance(
    tmp_path: Path,
) -> None:
    workspace, intent, parent, options = _preparation_fixture(tmp_path)
    (workspace / "sources" / "api" / "untracked.txt").write_text(
        "dirty\n", encoding="utf-8"
    )

    with pytest.raises(Protocol28PreparationError, match="Commit, stash.*revert"):
        prepare_protocol_28_request(workspace, intent, parent, options)


@pytest.mark.unit
def test_published_child_loads_after_snapshot_and_source_disappear(tmp_path: Path) -> None:
    workspace, intent, parent, options = _preparation_fixture(tmp_path)
    inputs = prepare_protocol_28_request(workspace, intent, parent, options)
    run_dir = create_or_reuse_protocol_28_child(workspace, inputs)

    options.snapshot.read_root.parent.parent.rename(tmp_path / "hidden-snapshots")
    (workspace / "sources" / "api").rename(tmp_path / "hidden-source")

    loaded = load_protocol_28_run_context(run_dir)
    assert loaded.inputs.exhaustive_plan.identity == inputs.exhaustive_plan.identity


@pytest.mark.unit
def test_preparation_rejects_authorization_below_one_paired_dispatch(
    tmp_path: Path,
) -> None:
    workspace, intent, parent, options = _preparation_fixture(tmp_path)
    constrained = replace(options, active_ms_limit=599_999)

    with pytest.raises(Protocol28PreparationError, match="minimum=600000"):
        prepare_protocol_28_request(workspace, intent, parent, constrained)
