from __future__ import annotations

from dataclasses import replace
import io
from pathlib import Path
import json
import zipfile

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_24.model import SelectionScopeV1
from harness.re_v2.protocol_28.authority import (
    ValidatedL3ParentV1,
    ValidatedL3ParentV2,
    ValidatedL3TargetV1,
)
from harness.re_v2.protocol_25.debt import DebtGroupV1, ResidualDebtAcceptanceV1
from harness.re_v2.protocol_28.inputs import (
    Protocol28InputError,
    protocol_28_input_quality,
    protocol_28_residual_debt_acceptance,
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
from harness.re_v2.protocol_28.context import (
    build_protocol_28_slice_context,
    load_protocol_28_run_context,
)
from harness.re_v2.protocol_28.planning import realize_slice
from harness.re_v2.snapshot import load_snapshot_manifest
from tests.unit.test_re_v2_protocol_28_evidence import _fixture


def _authority(values: dict[str, bytes], seed: str) -> str:
    payload = seed.encode("utf-8")
    object_id = content_digest(payload)
    values[object_id] = payload
    return object_id


def _preparation_fixture(
    tmp_path: Path,
    *,
    large_source: bool = False,
    extra_source_files: dict[str, str | bytes] | None = None,
):  # type: ignore[no-untyped-def]
    handler = (
        "x = '" + ("a" * 100_000) + "'\n"
        if large_source
        else "def handle():\n    return 'ok'\n"
    )
    source_files: dict[str, str | bytes] = {
        "README.md": "API service\n",
        "src/orders/handler.py": handler,
    }
    source_files.update(extra_source_files or {})
    snapshot, partition = _fixture(tmp_path, source_files)
    workspace = tmp_path / "workspace"
    domain = partition.sources[0].domains[0]
    selection = SelectionScopeV1(1, False, ("api",), (domain.domain_key,))
    objects: dict[str, bytes] = {}
    epoch = _authority(objects, "epoch")
    manifest_hash = _authority(objects, "l3-manifest")
    terminal_hash = _authority(objects, "l3-terminal")
    artifact_policy = _authority(objects, "artifact-policy")
    snapshot_manifest = load_snapshot_manifest(snapshot)
    assert snapshot_manifest.components is not None
    partition_manifest_bytes = canonical_json_bytes(
        {
            "partition_protocol": "re-v2-partition-v2",
            "source_snapshot_id": snapshot.snapshot_id,
            "sources": [
                {
                    "git_role": item.git_role,
                    "id": item.source_id,
                    "path": item.workspace_path,
                }
                for item in snapshot_manifest.components
            ],
        }
    )
    partition_manifest = content_digest(partition_manifest_bytes)
    objects[partition_manifest] = partition_manifest_bytes
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


def _accepted_debt_fixture(tmp_path: Path):  # type: ignore[no-untyped-def]
    workspace, intent, parent, options = _preparation_fixture(tmp_path)
    objects = dict(options.authority_objects)
    finding_id = _authority(objects, "accepted residual finding")
    domain_target = next(item for item in parent.targets if item.target_kind == "domain")
    domain_target = replace(
        domain_target,
        finding_ids=(finding_id,),
        unresolved_finding_ids=(finding_id,),
        closure_state="deeper-evidence-blocked",
    )
    raw = replace(
        parent,
        terminal_state="blocked",
        blocker_classes=("requires_human_decision",),
        targets=tuple(
            sorted(
                (
                    domain_target,
                    *(item for item in parent.targets if item.target_kind != "domain"),
                ),
                key=lambda item: item.sort_key,
            )
        ),
    )
    acceptance = ResidualDebtAcceptanceV1(
        1,
        raw.manifest_hash,
        raw.terminal_event_hash,
        raw.frozen_epoch_id,
        content_digest(b"closure-root"),
        (("api", content_digest(b"source-root")),),
        (DebtGroupV1("api", "requires_human_decision", (finding_id,)),),
        (content_digest(b"deferred-observation"),),
        content_digest(b"guidance"),
        "re-v2-banzai-residual-debt-v1",
        raw.source_snapshot_id,
        raw.selection_id,
        content_digest(b"finalize-operation"),
    )
    objects[acceptance.identity] = canonical_json_bytes(acceptance.to_json_dict())
    partial = ValidatedL3ParentV2(
        raw,
        "partial",
        acceptance.identity,
        (finding_id,),
        acceptance.deferred_observation_ids,
    )
    return (
        workspace,
        intent,
        partial,
        replace(options, authority_objects=objects),
        acceptance,
    )


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
    loaded = load_protocol_28_run_context(run_dir)
    for target_plan in inputs.exhaustive_plan.target_plans:
        for entry in target_plan.entries:
            spec = realize_slice(
                entry,
                {
                    dependency_id: dependency_id
                    for dependency_id in entry.planned_dependency_root_ids
                },
            )
            encoded = build_protocol_28_slice_context(
                loaded,
                target_plan,
                entry,
                spec,
                role="producer",
            )
            assert entry.canonical_context_bytes == len(encoded)


@pytest.mark.unit
def test_preparation_covers_mp4_asset_as_nonbehavioral_metadata(
    tmp_path: Path,
) -> None:
    workspace, intent, parent, options = _preparation_fixture(
        tmp_path,
        extra_source_files={
            "public/editor-placeholder-video.mp4": b"\x00\x00\x00\x18ftypmp42",
        },
    )

    inputs = prepare_protocol_28_request(workspace, intent, parent, options)

    disposition = next(
        item
        for item in inputs.snapshot_evidence_catalog.nontext_dispositions
        if item.source_relative_path == "public/editor-placeholder-video.mp4"
    )
    assert disposition.disposition == "proven_non_behavioral"


@pytest.mark.unit
def test_preparation_recognizes_macro_free_ooxml_with_misleading_suffix(
    tmp_path: Path,
) -> None:
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
                b'content-types"><Override PartName="/xl/workbook.xml" '
                b'ContentType="application/vnd.openxmlformats-officedocument.'
                b'spreadsheetml.sheet.main+xml"/></Types>'
            ),
        )
        archive.writestr("xl/workbook.xml", b"<workbook/>")
        archive.writestr("xl/worksheets/sheet1.xml", b"<worksheet/>")
    workspace, intent, parent, options = _preparation_fixture(
        tmp_path,
        extra_source_files={"Player Statistics.csv": package.getvalue()},
    )

    inputs = prepare_protocol_28_request(workspace, intent, parent, options)

    disposition = next(
        item
        for item in inputs.snapshot_evidence_catalog.nontext_dispositions
        if item.source_relative_path == "Player Statistics.csv"
    )
    assert disposition.disposition == "proven_non_behavioral"


@pytest.mark.unit
def test_partial_debt_is_bound_to_every_l4_input_and_context(tmp_path: Path) -> None:
    workspace, intent, parent, options, acceptance = _accepted_debt_fixture(tmp_path)

    inputs = prepare_protocol_28_request(workspace, intent, parent, options)
    run_dir = create_or_reuse_protocol_28_child(workspace, inputs)
    loaded = load_protocol_28_run_context(run_dir)

    assert protocol_28_input_quality(inputs) == "partial"
    assert protocol_28_residual_debt_acceptance(inputs) == acceptance
    assert protocol_28_residual_debt_acceptance(loaded.inputs) == acceptance
    for target_plan in loaded.inputs.exhaustive_plan.target_plans:
        for entry in target_plan.entries:
            assert acceptance.identity in entry.required_lower_authority_ids
            payload = json.loads(
                build_protocol_28_slice_context(
                    loaded,
                    target_plan,
                    entry,
                    realize_slice(
                        entry,
                        {
                            dependency_id: dependency_id
                            for dependency_id in entry.planned_dependency_root_ids
                        },
                    ),
                    role="producer",
                )
            )
            assert payload["input_quality"] == "partial"
            assert payload["residual_debt_acceptance_hash"] == acceptance.identity
            assert payload["accepted_residual_debt"] == acceptance.to_json_dict()
            assert payload["residual_debt_disposition"] == "accepted_not_closed_by_l4"


@pytest.mark.unit
def test_partial_l4_rejects_missing_exact_debt_object(tmp_path: Path) -> None:
    workspace, intent, parent, options, acceptance = _accepted_debt_fixture(tmp_path)
    reduced = replace(
        options,
        authority_objects={
            key: value
            for key, value in options.authority_objects.items()
            if key != acceptance.identity
        },
    )

    with pytest.raises(
        (Protocol28InputError, Protocol28PreparationError),
        match="authority closure is incomplete|required authority object is missing",
    ):
        prepare_protocol_28_request(workspace, intent, parent, reduced)


@pytest.mark.unit
def test_preparation_reconstructs_partition_manifest_authority(
    tmp_path: Path,
) -> None:
    """A derived partition identity must still have self-contained canonical bytes."""
    workspace, intent, parent, options = _preparation_fixture(tmp_path)
    reduced = replace(
        options,
        authority_objects={
            key: value
            for key, value in options.authority_objects.items()
            if key != parent.partition_manifest_id
        },
    )

    inputs = prepare_protocol_28_request(workspace, intent, parent, reduced)

    assert parent.partition_manifest_id in inputs.authority_objects


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


@pytest.mark.unit
def test_preparation_rejects_unsplittable_exact_provider_context(
    tmp_path: Path,
) -> None:
    """Authority bytes count after base64 encoding, not merely by object ID."""
    workspace, intent, parent, options = _preparation_fixture(tmp_path)
    oversized_payload = b"x" * 150_000
    oversized_id = content_digest(oversized_payload)
    first, *remaining = parent.targets
    oversized_target = replace(first, relevant_l2_root_ids=(oversized_id,))
    oversized_parent = replace(
        parent,
        targets=tuple(sorted((oversized_target, *remaining), key=lambda item: item.sort_key)),
        lower_l0_l2_authority_ids=tuple(
            sorted({*parent.lower_l0_l2_authority_ids, oversized_id})
        ),
    )
    oversized_options = replace(
        options,
        authority_objects={**options.authority_objects, oversized_id: oversized_payload},
    )

    with pytest.raises(
        Protocol28PreparationError,
        match="unsplittable.*context|context.*byte bound",
    ):
        prepare_protocol_28_request(
            workspace,
            intent,
            oversized_parent,
            oversized_options,
        )


@pytest.mark.unit
def test_preparation_splits_on_exact_serialized_context_size(tmp_path: Path) -> None:
    workspace, intent, parent, options = _preparation_fixture(
        tmp_path,
        large_source=True,
    )

    inputs = prepare_protocol_28_request(workspace, intent, parent, options)

    assert any(
        len(target.entries) > 1
        for target in inputs.exhaustive_plan.target_plans
    )
    assert all(
        entry.canonical_context_bytes <= inputs.exhaustive_policy.max_context_bytes
        for target in inputs.exhaustive_plan.target_plans
        for entry in target.entries
    )
    split_target = next(
        target
        for target in inputs.exhaustive_plan.target_plans
        if len(target.entries) > 1
    )
    assert split_target.entries[0].primary_subject_ids
    assert all(
        entry.supporting_subject_ids
        for entry in split_target.entries[1:]
        if entry.primary_snapshot_evidence_ids
    )
