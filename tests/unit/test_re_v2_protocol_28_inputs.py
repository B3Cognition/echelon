from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil

import pytest

from harness.re_v2.protocol_24.model import ParentLineageV1
from harness.re_v2.protocol_28.inputs import (
    Protocol28ClosureInputs,
    Protocol28CreationInputs,
    Protocol28InputError,
    SafeProtocol28CreationInputs,
    ValidatedSafeProtocol28Inputs,
    load_protocol_28_inputs,
    publish_protocol_28_run,
    stage_closure_inputs,
    stage_exhaustive_inputs,
)
from harness.re_v2.protocol_28.executors import (
    build_l4_executor_catalog,
    canonical_exhaustive_response_schema_bytes,
)
from harness.re_v2.protocol_28.model import (
    ExhaustiveBudgetPolicyV1,
    ExhaustiveRequestV1,
    ExhaustiveRunManifestV7,
    SafeExhaustiveRequestV1,
    SafeExhaustiveRunManifestV7,
    L4ClosureLineageV1,
    L4ClosureRequestV1,
    L4ClosureRunManifestV7,
)
from harness.re_v2.protocol_28.safe_evidence import (
    build_safe_lower_authority_catalog,
    build_safe_snapshot_evidence_catalog,
)
from harness.re_v2.protocol_28.authority import L4ClosureParentBundleV1
from harness.re_v2.protocol_28.graph import (
    AcceptedExhaustiveSliceV1,
    ExhaustiveVerificationReceiptV1,
    L4RunRootV1,
    L4TargetRootV1,
)
from tests.unit.test_re_v2_protocol_28_planning import _authorities, _plan


def _fixture(run_id: str = "re-l4-inputs"):  # type: ignore[no-untyped-def]
    plan, subjects, evidence = _plan()
    _, selection, parent, l3, _ = _authorities()
    from harness.re_v2.protocol_28.policies import build_initial_exhaustive_policy

    policy = build_initial_exhaustive_policy()
    opaque_payloads = (
        b"partition-catalog",
        b"artifact-policy",
        b"attempt-policy",
        b"lower",
        b"l3-manifest",
        b"l3-terminal",
        b"partition",
        b"l0-root-manifest",
        b"epoch",
        b"candidate",
        b"audit-policy",
        b"executor-policy",
        b"l2-root",
        b"epoch-entry",
        b"evidence-policy",
        b"target-partition",
        b"membership-proof",
        b"file-record",
        b"subject-one",
        b"subject-two",
        b"shared-cli",
        b"re-v2-l4-producer-contract-v1",
        b"re-v2-l4-verifier-contract-v1",
        canonical_exhaustive_response_schema_bytes("producer"),
        canonical_exhaustive_response_schema_bytes("verifier"),
    )
    from harness.re_v2.canonical import content_digest

    authority_objects = {content_digest(payload): payload for payload in opaque_payloads}
    executors = build_l4_executor_catalog(
        inherited_executor_contract_hash=content_digest(b"shared-cli"),
        producer_agent_contract_hash=policy.producer_contract_hash,
        verifier_agent_contract_hash=policy.verifier_contract_hash,
    )
    request = ExhaustiveRequestV1(
        1,
        selection.identity,
        parent.identity,
        l3.identity,
        evidence.identity,
        policy.identity,
        executors.identity,
        parent.source_snapshot_id,
        parent.partition_manifest_id,
        plan.identity,
    )
    manifest = ExhaustiveRunManifestV7(
        schema_version=7,
        engine="re-v2",
        engine_protocol_version="2.8",
        run_mode="exhaustive-depth",
        requested_goals=("selective-exhaustive-depth",),
        target_layer="L4",
        run_id=run_id,
        created_at="2026-08-31T12:00:00Z",
        source_snapshot_id=parent.source_snapshot_id,
        source_snapshot_kind="workspace-git-composite",
        partition_manifest_id=parent.partition_manifest_id,
        selection=selection,
        lineage=ParentLineageV1(
            1,
            parent.l3_run_id,
            parent.l3_manifest_hash,
            parent.l3_terminal_event_hash,
            "re-l0-root",
            content_digest(b"l0-root-manifest"),
        ),
        workspace_partition_catalog_id=parent.workspace_partition_catalog_id,
        inherited_artifact_policy_catalog_id=parent.inherited_artifact_policy_catalog_id,
        parent_authority_bundle_id=parent.identity,
        l3_target_projection_catalog_id=l3.identity,
        snapshot_evidence_catalog_id=evidence.identity,
        exhaustive_request=request,
        exhaustive_plan_id=plan.identity,
        exhaustive_policy_catalog_id=policy.identity,
        executor_catalog_id=executors.identity,
        attempt_policy_id=content_digest(b"attempt-policy"),
        budget_policy=ExhaustiveBudgetPolicyV1(1, 400_000, 600_000, 3, 0, 1),
    )
    inputs = Protocol28CreationInputs(
        manifest=manifest,
        parent_authority_bundle=parent,
        l3_projection_catalog=l3,
        snapshot_evidence_catalog=evidence,
        exhaustive_subject_catalog=subjects,
        exhaustive_policy=policy,
        executor_catalog=executors,
        exhaustive_plan=plan,
        authority_objects=authority_objects,
    )
    return manifest, inputs


def _safe_fixture(run_id: str = "re-l4-safe-inputs"):  # type: ignore[no-untyped-def]
    legacy_manifest, legacy = _fixture(run_id)
    safe = build_safe_snapshot_evidence_catalog(legacy.snapshot_evidence_catalog)
    lower_ids = tuple(
        sorted(
            {
                object_id
                for target in legacy.exhaustive_plan.target_plans
                for entry in target.entries
                for object_id in entry.required_lower_authority_ids
            }
        )
    )
    safe_lower = build_safe_lower_authority_catalog(
        legacy.authority_objects,
        lower_ids,
    )
    old_request = legacy_manifest.exhaustive_request
    request = SafeExhaustiveRequestV1(
        **{
            field: getattr(old_request, field)
            for field in old_request.FIELDS
        },
        safe_snapshot_evidence_catalog_id=safe.identity,
        safe_lower_authority_catalog_id=safe_lower.identity,
    )
    manifest = SafeExhaustiveRunManifestV7(
        **{
            field: getattr(legacy_manifest, field)
            for field in legacy_manifest.FIELDS
            if field != "exhaustive_request"
        },
        exhaustive_request=request,
        safe_snapshot_evidence_catalog_id=safe.identity,
        safe_lower_authority_catalog_id=safe_lower.identity,
    )
    inputs = SafeProtocol28CreationInputs(
        manifest=manifest,
        parent_authority_bundle=legacy.parent_authority_bundle,
        l3_projection_catalog=legacy.l3_projection_catalog,
        snapshot_evidence_catalog=legacy.snapshot_evidence_catalog,
        exhaustive_subject_catalog=legacy.exhaustive_subject_catalog,
        exhaustive_policy=legacy.exhaustive_policy,
        executor_catalog=legacy.executor_catalog,
        exhaustive_plan=legacy.exhaustive_plan,
        authority_objects=legacy.authority_objects,
        safe_snapshot_evidence_catalog=safe,
        safe_lower_authority_catalog=safe_lower,
    )
    return manifest, inputs


@pytest.mark.unit
def test_private_stage_has_every_input_but_no_manifest(tmp_path: Path) -> None:
    manifest, inputs = _fixture()
    stage = tmp_path / "runs" / f".{manifest.run_id}.stage"

    paths = stage_exhaustive_inputs(stage, inputs)

    assert paths.inputs.is_dir()
    assert paths.objects.is_dir()
    assert not paths.manifest.exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    "boundary",
    (
        "authority_objects_staged",
        "canonical_authorities_staged",
        "snapshot_evidence_staged",
        "inputs_fsynced",
        "before_manifest_publish",
    ),
)
def test_staging_crash_never_publishes_partial_run(
    tmp_path: Path, boundary: str
) -> None:
    manifest, inputs = _fixture()
    runs = tmp_path / "runs"
    stage = runs / f".{manifest.run_id}.stage"
    final = runs / manifest.run_id

    def crash(point: str) -> None:
        if point == boundary:
            raise RuntimeError(point)

    with pytest.raises(RuntimeError, match=boundary):
        stage_exhaustive_inputs(stage, inputs, fault_hook=crash)

    assert not stage.exists()
    assert not final.exists()


@pytest.mark.unit
def test_loaded_inputs_need_no_source_or_parent(tmp_path: Path) -> None:
    manifest, inputs = _fixture()
    runs = tmp_path / "runs"
    stage = runs / f".{manifest.run_id}.stage"
    final = runs / manifest.run_id
    source = tmp_path / "source-checkout"
    parent = runs / "re-l3-parent"
    source.mkdir(parents=True)
    parent.mkdir(parents=True)
    stage_exhaustive_inputs(stage, inputs)
    publish_protocol_28_run(stage, final, manifest)

    shutil.rmtree(source)
    shutil.rmtree(parent)
    loaded = load_protocol_28_inputs(final)

    assert loaded.exhaustive_plan.identity == inputs.exhaustive_plan.identity
    assert loaded.snapshot_evidence_catalog.identity == inputs.snapshot_evidence_catalog.identity
    assert loaded.exhaustive_subject_catalog.identity == inputs.exhaustive_subject_catalog.identity


@pytest.mark.unit
def test_safe_inputs_persist_exact_projection_while_historical_inputs_still_load(
    tmp_path: Path,
) -> None:
    safe_manifest, safe_inputs = _safe_fixture()
    safe_stage = tmp_path / "runs" / ".safe.stage"
    safe_final = tmp_path / "runs" / safe_manifest.run_id
    stage_exhaustive_inputs(safe_stage, safe_inputs)
    publish_protocol_28_run(safe_stage, safe_final, safe_manifest)

    loaded = load_protocol_28_inputs(safe_final)

    assert isinstance(loaded, ValidatedSafeProtocol28Inputs)
    assert loaded.safe_snapshot_evidence_catalog.identity == (
        safe_inputs.safe_snapshot_evidence_catalog.identity
    )
    assert loaded.manifest.safe_snapshot_evidence_catalog_id == (
        loaded.safe_snapshot_evidence_catalog.identity
    )

    historical_manifest, historical = _fixture("re-l4-historical-inputs")
    historical_stage = tmp_path / "runs" / ".historical.stage"
    historical_final = tmp_path / "runs" / historical_manifest.run_id
    stage_exhaustive_inputs(historical_stage, historical)
    publish_protocol_28_run(historical_stage, historical_final, historical_manifest)
    historical_loaded = load_protocol_28_inputs(historical_final)
    assert type(historical_loaded.manifest) is ExhaustiveRunManifestV7
    assert type(historical_loaded) is not ValidatedSafeProtocol28Inputs


@pytest.mark.unit
def test_cross_shard_overlapping_secret_ranges_stage_and_replay_safe_inputs(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_28.preparation import prepare_protocol_28_request
    from tests.unit.test_re_v2_protocol_28_preparation import _preparation_fixture

    token = b"ghp_" + b"R" * 36
    prefix = "é".encode("utf-8") + b"a" * (65_497 - 2) + b"; "
    payload = prefix + b'API_TOKEN="prefix-' + token + b'-suffix"\n'
    workspace, intent, parent, options = _preparation_fixture(
        tmp_path,
        extra_source_files={"src/overlap.py": payload},
    )

    inputs = prepare_protocol_28_request(workspace, intent, parent, options)
    stage = workspace / "runs" / ".overlap.stage"
    final = workspace / "runs" / inputs.manifest.run_id
    stage_exhaustive_inputs(stage, inputs)
    publish_protocol_28_run(stage, final, inputs.manifest)
    loaded = load_protocol_28_inputs(final)

    assert isinstance(loaded, ValidatedSafeProtocol28Inputs)
    assert token not in loaded.safe_snapshot_evidence_catalog.provider_bytes()


@pytest.mark.unit
def test_safe_replay_rejects_missing_required_authority_with_rebound_forged_row(
    tmp_path: Path,
) -> None:
    import base64
    import json

    from harness.re_v2.canonical import canonical_json_bytes, content_digest
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_28.context import (
        Protocol28RunContext,
        build_protocol_28_slice_context,
        load_protocol_28_run_context,
    )
    from harness.re_v2.protocol_28.planning import realize_slice
    from harness.re_v2.protocol_28.preparation import prepare_protocol_28_request
    from harness.re_v2.protocol_28.safe_evidence import (
        SafeLowerAuthorityCatalogV1,
        SafeLowerAuthorityObjectV1,
    )
    from tests.unit.test_re_v2_protocol_28_preparation import _preparation_fixture

    workspace, intent, parent, options = _preparation_fixture(tmp_path)
    inputs = prepare_protocol_28_request(workspace, intent, parent, options)
    stage = workspace / "runs" / ".forged-replay.stage"
    final = workspace / "runs" / inputs.manifest.run_id
    paths = stage_exhaustive_inputs(stage, inputs)

    target_plans = inputs.exhaustive_plan.target_plans
    assert len(target_plans) >= 2
    exposed_target, exposed_entry = target_plans[0], target_plans[0].entries[0]
    missing_id = content_digest(b"absent-plan-required-authority")
    later_target = target_plans[-1]
    later_entry = later_target.entries[-1]
    forged_later_entry = replace(
        later_entry,
        required_lower_authority_ids=tuple(
            sorted((*later_entry.required_lower_authority_ids, missing_id))
        ),
    )
    forged_later_target = replace(
        later_target,
        entries=tuple(
            forged_later_entry if item == later_entry else item
            for item in later_target.entries
        ),
    )
    forged_plan = replace(
        inputs.exhaustive_plan,
        target_plans=tuple(
            forged_later_target if item == later_target else item
            for item in target_plans
        ),
    )

    exposed_id = exposed_entry.required_lower_authority_ids[0]
    existing_row = next(
        row
        for row in inputs.safe_lower_authority_catalog.objects
        if row.raw_authority_id == exposed_id
    )
    forged_token = ("ghp_" + "F" * 36).encode("ascii")
    forged_row = SafeLowerAuthorityObjectV1(
        1,
        exposed_id,
        existing_row.security_policy_id,
        len(forged_token),
        "available",
        None,
        base64.b64encode(forged_token).decode("ascii"),
        (),
    )
    missing_row = SafeLowerAuthorityObjectV1(
        1,
        missing_id,
        existing_row.security_policy_id,
        0,
        "available",
        None,
        "",
        (),
    )
    forged_lower = SafeLowerAuthorityCatalogV1(
        1,
        inputs.safe_lower_authority_catalog.security_policy_id,
        tuple(
            sorted(
                (
                    *(
                        forged_row if row.raw_authority_id == exposed_id else row
                        for row in inputs.safe_lower_authority_catalog.objects
                    ),
                    missing_row,
                ),
                key=lambda row: row.raw_authority_id,
            )
        ),
    )
    forged_request = replace(
        inputs.manifest.exhaustive_request,
        exhaustive_plan_id=forged_plan.identity,
        safe_lower_authority_catalog_id=forged_lower.identity,
    )
    forged_manifest = replace(
        inputs.manifest,
        exhaustive_request=forged_request,
        exhaustive_plan_id=forged_plan.identity,
        safe_lower_authority_catalog_id=forged_lower.identity,
    )

    store = ObjectStore(paths.objects)
    for authority in (
        forged_later_entry,
        forged_later_target,
        forged_plan,
        forged_row,
        missing_row,
        forged_lower,
        forged_request,
    ):
        store.put_blob(canonical_json_bytes(authority.to_json_dict()))
    for path, authority in (
        (paths.inputs / "exhaustive-plan.json", forged_plan),
        (paths.inputs / "exhaustive-request.json", forged_request),
        (paths.inputs / "safe-lower-authority-catalog.json", forged_lower),
    ):
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(authority.to_json_dict()))

    try:
        publish_protocol_28_run(stage, final, forged_manifest)
    except Protocol28InputError as exc:
        assert "required lower authority" in str(exc)
        assert not final.exists()
        return

    context = load_protocol_28_run_context(final)
    assert isinstance(context, Protocol28RunContext)
    loaded_target = next(
        item for item in context.inputs.exhaustive_plan.target_plans
        if item.sort_key == exposed_target.sort_key
    )
    loaded_entry = loaded_target.entries[0]
    spec = realize_slice(
        loaded_entry,
        {
            object_id: object_id
            for object_id in loaded_entry.planned_dependency_root_ids
        },
    )
    provider = json.loads(
        build_protocol_28_slice_context(
            context,
            loaded_target,
            loaded_entry,
            spec,
            role="producer",
        )
    )
    decoded = tuple(
        base64.b64decode(row["bytes_base64"], validate=True)
        for row in provider["lower_authority_objects"]
    )
    assert all(forged_token not in payload for payload in decoded)
    pytest.fail("forged Safe lower-authority closure survived replay validation")


@pytest.mark.unit
@pytest.mark.parametrize(
    "tamper",
    ("safe-row", "policy", "raw-binding", "manifest-reference", "authority-object"),
)
def test_safe_input_tampering_fails_before_activation(
    tmp_path: Path,
    tamper: str,
) -> None:
    import json

    from harness.re_v2.canonical import canonical_json_bytes, content_digest

    manifest, inputs = _safe_fixture()
    stage = tmp_path / "runs" / ".safe.stage"
    final = tmp_path / "runs" / manifest.run_id
    stage_exhaustive_inputs(stage, inputs)
    paths = publish_protocol_28_run(stage, final, manifest)
    safe_path = paths.inputs / "safe-snapshot-evidence-catalog.json"
    if tamper in {"safe-row", "policy", "raw-binding"}:
        raw = json.loads(safe_path.read_bytes())
        if tamper == "safe-row":
            raw["objects"][0]["source_relative_path"] = "tampered.py"
        elif tamper == "policy":
            raw["security_policy_id"] = content_digest(b"other-policy")
        else:
            raw["raw_catalog_id"] = content_digest(b"other-raw-catalog")
        safe_path.chmod(0o600)
        safe_path.write_bytes(canonical_json_bytes(raw))
    elif tamper == "manifest-reference":
        raw = json.loads(paths.manifest.read_bytes())
        raw["safe_snapshot_evidence_catalog_id"] = content_digest(b"other-safe-catalog")
        paths.manifest.chmod(0o600)
        paths.manifest.write_bytes(canonical_json_bytes(raw))
    else:
        row_id = inputs.safe_snapshot_evidence_catalog.objects[0].identity
        digest = row_id.removeprefix("sha256:")
        (paths.objects / "sha256" / digest[:2] / digest[2:]).unlink()

    with pytest.raises(Protocol28InputError):
        load_protocol_28_inputs(final)


@pytest.mark.unit
def test_failed_private_staging_publishes_no_run_or_pointer(tmp_path: Path) -> None:
    manifest, inputs = _fixture()
    runs = tmp_path / "runs"
    stage = runs / f".{manifest.run_id}.stage"
    final = runs / manifest.run_id
    pointer = runs / ".current-re-v2"
    runs.mkdir(parents=True)
    pointer.write_text("re-existing\n", encoding="utf-8")
    missing = inputs.parent_authority_bundle.lower_l0_l2_authority_ids[0]
    with pytest.raises(Protocol28InputError, match="authority object"):
        broken = replace(
            inputs,
            authority_objects={
                key: payload for key, payload in inputs.authority_objects.items() if key != missing
            },
        )
        stage_exhaustive_inputs(stage, broken)

    assert not stage.exists()
    assert not final.exists()
    assert pointer.read_text(encoding="utf-8") == "re-existing\n"


@pytest.mark.unit
def test_loader_rejects_missing_plan_object(tmp_path: Path) -> None:
    manifest, inputs = _fixture()
    runs = tmp_path / "runs"
    stage = runs / f".{manifest.run_id}.stage"
    final = runs / manifest.run_id
    stage_exhaustive_inputs(stage, inputs)
    paths = publish_protocol_28_run(stage, final, manifest)
    suffix = inputs.exhaustive_plan.identity.removeprefix("sha256:")
    (paths.objects / "sha256" / suffix[:2] / suffix[2:]).unlink()

    with pytest.raises(Protocol28InputError, match="exhaustive plan"):
        load_protocol_28_inputs(final)


@pytest.mark.unit
def test_loader_rejects_missing_transitive_shard_authority(tmp_path: Path) -> None:
    manifest, inputs = _fixture()
    runs = tmp_path / "runs"
    stage = runs / f".{manifest.run_id}.stage"
    final = runs / manifest.run_id
    stage_exhaustive_inputs(stage, inputs)
    paths = publish_protocol_28_run(stage, final, manifest)
    shard_id = inputs.snapshot_evidence_catalog.shards[0].identity
    suffix = shard_id.removeprefix("sha256:")
    (paths.objects / "sha256" / suffix[:2] / suffix[2:]).unlink()

    with pytest.raises(Protocol28InputError, match="canonical authority"):
        load_protocol_28_inputs(final)


@pytest.mark.unit
def test_publish_is_no_clobber(tmp_path: Path) -> None:
    manifest, inputs = _fixture()
    runs = tmp_path / "runs"
    stage = runs / f".{manifest.run_id}.stage"
    final = runs / manifest.run_id
    stage_exhaustive_inputs(stage, inputs)
    publish_protocol_28_run(stage, final, manifest)

    retry_stage = runs / f".{manifest.run_id}.retry"
    stage_exhaustive_inputs(retry_stage, inputs)
    with pytest.raises(Protocol28InputError, match="already exists"):
        publish_protocol_28_run(retry_stage, final, manifest)


def _closure_fixture(run_id: str = "re-l4-closure-inputs"):  # type: ignore[no-untyped-def]
    from harness.re_v2.canonical import content_digest
    from tests.re_v2_protocol_28_fixtures import selection_scope_v1

    finding = content_digest(b"finding")
    accepted = AcceptedExhaustiveSliceV1(
        1,
        content_digest(b"plan-entry"),
        content_digest(b"slice-spec"),
        content_digest(b"output-key"),
        content_digest(b"candidate"),
        content_digest(b"producer-capture"),
        content_digest(b"verifier-result"),
        content_digest(b"verifier-capture"),
        content_digest(b"certification"),
        content_digest(b"acceptance"),
        (finding,),
        "PASS",
    )
    verifier = ExhaustiveVerificationReceiptV1(
        1,
        accepted.identity,
        accepted.plan_entry_id,
        accepted.verifier_result_hash,
        accepted.verifier_execution_capture_hash,
        (finding,),
        "PASS",
    )
    target = L4TargetRootV1(
        1,
        "domain",
        "api",
        content_digest(b"domain"),
        content_digest(b"target-plan"),
        content_digest(b"l3-projection"),
        content_digest(b"evidence-projection"),
        content_digest(b"coverage-ledger"),
        (accepted.plan_entry_id,),
        (accepted.identity,),
        (accepted.verifier_result_hash,),
        (accepted.acceptance_receipt_hash,),
        (finding,),
        "complete",
    )
    selection = selection_scope_v1()
    source_snapshot = content_digest(b"source-snapshot")
    partition = content_digest(b"partition-manifest")
    run_root = L4RunRootV1(
        1,
        source_snapshot,
        partition,
        selection.identity,
        content_digest(b"parent-authority"),
        content_digest(b"exhaustive-plan"),
        content_digest(b"exhaustive-policy"),
        (target.identity,),
        (),
        (accepted.identity,),
        "selected-scope",
        "complete",
    )
    immutable_payload = b"immutable"
    immutable_id = content_digest(immutable_payload)
    parent = L4ClosureParentBundleV1(
        1,
        selection.identity,
        source_snapshot,
        partition,
        "re-l3-parent",
        content_digest(b"l3-manifest"),
        content_digest(b"l3-terminal"),
        content_digest(b"epoch"),
        "re-l4-evidence",
        content_digest(b"l4-manifest"),
        content_digest(b"l4-terminal"),
        run_root.identity,
        "complete",
        (content_digest(b"l3-projection"),),
        (accepted.identity,),
        (verifier.identity,),
        (target.identity,),
        (immutable_id,),
    )
    closure_policy = b"closure-policy"
    request = L4ClosureRequestV1(
        1,
        parent.l3_manifest_hash,
        parent.l3_terminal_event_hash,
        parent.frozen_epoch_id,
        (finding,),
        run_root.identity,
        (target.identity,),
        (verifier.identity,),
        content_digest(closure_policy),
        source_snapshot,
        partition,
        selection.identity,
    )
    manifest = L4ClosureRunManifestV7(
        7,
        "re-v2",
        "2.8",
        "l4-closure-successor",
        ("l4-evidence-closure",),
        "L4",
        run_id,
        "2026-08-31T12:30:00Z",
        source_snapshot,
        "workspace-git-composite",
        partition,
        selection,
        L4ClosureLineageV1(
            1,
            parent.l3_run_id,
            parent.l3_manifest_hash,
            parent.l3_terminal_event_hash,
            parent.l4_run_id,
            parent.l4_manifest_hash,
            parent.l4_terminal_event_hash,
        ),
        parent.identity,
        request,
        run_root.identity,
        content_digest(closure_policy),
    )
    return manifest, Protocol28ClosureInputs(
        manifest,
        parent,
        run_root,
        (target,),
        (accepted,),
        (verifier,),
        closure_policy,
        {immutable_id: immutable_payload},
    )


@pytest.mark.unit
def test_closure_successor_is_self_contained_and_provider_free(tmp_path: Path) -> None:
    manifest, inputs = _closure_fixture()
    runs = tmp_path / "runs"
    stage = runs / f".{manifest.run_id}.stage"
    final = runs / manifest.run_id

    stage_closure_inputs(stage, inputs)
    publish_protocol_28_run(stage, final, manifest)
    loaded = load_protocol_28_inputs(final)

    assert loaded.l4_run_root.identity == inputs.l4_run_root.identity
    assert loaded.verification_receipts == inputs.verification_receipts
    assert "budget_policy" not in manifest.to_json_dict()
    assert "executor_catalog_id" not in manifest.to_json_dict()
