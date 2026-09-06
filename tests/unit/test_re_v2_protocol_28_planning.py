from __future__ import annotations

import base64
from dataclasses import replace

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_24.model import SelectionScopeV1
from harness.re_v2.protocol_28.authority import (
    L3TargetAuthorityProjectionV1,
    L3TargetEpochMembershipV1,
    L3TargetProjectionCatalogV1,
    ParentAuthorityBundleV3,
)
from harness.re_v2.protocol_28.evidence import (
    SnapshotEvidenceCatalogV1,
    SnapshotEvidenceShardV1,
    TargetSnapshotEvidenceProjectionV1,
)
from harness.re_v2.protocol_28.planning import (
    ExhaustivePlanV1,
    ExhaustiveSubjectV1,
    Protocol28PlanningError,
    build_exhaustive_plan,
    build_exhaustive_subject_catalog,
    realize_slice,
)
from harness.re_v2.protocol_28.policies import build_initial_exhaustive_policy
from tests.re_v2_protocol_28_fixtures import digest


RAW_MAGIC = b"re-v2-l4-raw-v1\x00"


def _selection(domain_key: str) -> SelectionScopeV1:
    return SelectionScopeV1(1, False, ("api",), (domain_key,))


def _shard(*, start: int, payload: bytes, proof_id: str) -> SnapshotEvidenceShardV1:
    return SnapshotEvidenceShardV1(
        schema_version=1,
        source_id="api",
        source_relative_path="src/app.py",
        file_record_hash=digest("file-record"),
        file_content_hash=content_digest(b"a\nb\n"),
        mode="100644",
        byte_start=start,
        byte_end=start + len(payload),
        line_start=start // 2 + 1,
        column_start=1,
        line_end=start // 2 + 2,
        column_end=1,
        raw_hash=content_digest(payload),
        raw_object_hash=content_digest(RAW_MAGIC + payload),
        raw_bytes_base64=base64.b64encode(payload).decode("ascii"),
        membership_proof_id=proof_id,
    )


def _authorities(payloads: tuple[bytes, ...] = (b"a\n", b"b\n")):  # type: ignore[no-untyped-def]
    domain_key = digest("api-domain")
    selection = _selection(domain_key)
    target_content_id = digest("target-content")
    projection = L3TargetAuthorityProjectionV1(
        schema_version=1,
        target_kind="domain",
        source_id="api",
        target_id=domain_key,
        target_content_id=target_content_id,
        candidate_authority_hash=digest("candidate"),
        finding_ids=(),
        unresolved_finding_ids=(),
        resolution_overlay_ids=(),
        closure_receipt_ids=(),
        closure_state="complete",
        relevant_l2_root_ids=(digest("l2-root"),),
        audit_policy_id=digest("audit-policy"),
        executor_policy_id=digest("executor-policy"),
    )
    membership = L3TargetEpochMembershipV1(
        1, projection.identity, digest("epoch"), digest("epoch-entry")
    )
    l3 = L3TargetProjectionCatalogV1(
        schema_version=1,
        parent_manifest_hash=digest("l3-manifest"),
        parent_terminal_event_hash=digest("l3-terminal"),
        source_snapshot_id=digest("snapshot"),
        partition_manifest_id=digest("partition"),
        selection_id=selection.identity,
        frozen_epoch_id=digest("epoch"),
        projections=(projection,),
        memberships=(membership,),
    )
    parent = ParentAuthorityBundleV3(
        schema_version=3,
        source_snapshot_id=l3.source_snapshot_id,
        partition_manifest_id=l3.partition_manifest_id,
        selection_id=selection.identity,
        workspace_partition_catalog_id=digest("partition-catalog"),
        inherited_artifact_policy_catalog_id=digest("artifact-policy"),
        lower_l0_l2_authority_ids=(digest("lower"),),
        l3_run_id="re-l3",
        l3_manifest_hash=l3.parent_manifest_hash,
        l3_terminal_event_hash=l3.parent_terminal_event_hash,
        frozen_epoch_id=l3.frozen_epoch_id,
        l3_projection_catalog_id=l3.identity,
        selected_projection_ids=(projection.identity,),
        selected_epoch_membership_ids=(membership.identity,),
        unresolved_deeper_finding_ids=(),
        staged_checkpoint_provenance_ids=(),
    )
    proof = digest("membership-proof")
    shards = tuple(
        _shard(start=sum(map(len, payloads[:index])), payload=payload, proof_id=proof)
        for index, payload in enumerate(payloads)
    )
    evidence_projection = TargetSnapshotEvidenceProjectionV1(
        schema_version=1,
        target_kind="domain",
        source_id="api",
        target_id=domain_key,
        target_partition_id=digest("target-partition"),
        target_content_id=target_content_id,
        source_snapshot_id=l3.source_snapshot_id,
        primary_shard_ids=tuple(item.shard_id for item in shards),
        primary_empty_receipt_ids=(),
        primary_nontext_disposition_ids=(),
        supporting_shard_ids=(),
        supporting_empty_receipt_ids=(),
        supporting_nontext_disposition_ids=(),
        membership_proof_ids=(proof,),
    )
    evidence = SnapshotEvidenceCatalogV1(
        schema_version=1,
        source_snapshot_id=l3.source_snapshot_id,
        partition_catalog_id=parent.workspace_partition_catalog_id,
        selection_id=selection.identity,
        policy_id=digest("evidence-policy"),
        shards=shards,
        empty_receipts=(),
        nontext_dispositions=(),
        projections=(evidence_projection,),
    )
    return domain_key, selection, parent, l3, evidence


def _subjects(domain_key: str, shard_ids: tuple[str, ...], *, reverse: bool = False):  # type: ignore[no-untyped-def]
    subjects = [
        ExhaustiveSubjectV1(
            1,
            "domain",
            "api",
            domain_key,
            "operation:first",
            ("public-surfaces",),
            (shard_ids[0],),
            (),
            (digest("subject-one"),),
        ),
        ExhaustiveSubjectV1(
            1,
            "domain",
            "api",
            domain_key,
            "operation:second",
            ("public-surfaces",),
            (shard_ids[1],),
            (),
            (digest("subject-two"),),
        ),
    ]
    return tuple(reversed(subjects)) if reverse else tuple(subjects)


def _plan(reverse: bool = False):  # type: ignore[no-untyped-def]
    domain, selection, parent, l3, evidence = _authorities()
    subjects = build_exhaustive_subject_catalog(
        parent.source_snapshot_id,
        parent.partition_manifest_id,
        l3.identity,
        _subjects(
            domain,
            tuple(item.shard_id for item in evidence.shards),
            reverse=reverse,
        ),
    )
    plan = build_exhaustive_plan(
        parent,
        l3,
        evidence,
        subjects,
        build_initial_exhaustive_policy(),
        selection,
    )
    return plan, subjects, evidence


@pytest.mark.unit
def test_plan_assigns_every_primary_shard_once() -> None:
    """No lower-layer omission or duplicate may survive into an L4 root plan."""
    plan, _, evidence = _plan()
    assigned = [
        item
        for target in plan.target_plans
        for entry in target.entries
        for item in entry.primary_snapshot_evidence_ids
    ]
    assert set(assigned) == set(evidence.projections[0].primary_shard_ids)
    assert len(assigned) == len(set(assigned))


@pytest.mark.unit
def test_plan_is_independent_of_subject_discovery_order() -> None:
    """Filesystem or mapping iteration order must not change L4 work identity."""
    forward, forward_subjects, _ = _plan(False)
    reverse, reverse_subjects, _ = _plan(True)

    assert forward_subjects.identity == reverse_subjects.identity
    assert forward.identity == reverse.identity


@pytest.mark.unit
def test_exhaustive_plan_closed_round_trip() -> None:
    plan, _, _ = _plan()
    assert ExhaustivePlanV1.from_json_dict(plan.to_json_dict()) == plan

    encoded = plan.to_json_dict()
    encoded["runtime_budget"] = 1
    with pytest.raises(Protocol28PlanningError, match="unknown fields"):
        ExhaustivePlanV1.from_json_dict(encoded)


@pytest.mark.unit
def test_empty_categories_get_vacancy_receipts_not_silent_omission() -> None:
    """A required category with no inputs still needs deterministic closure."""
    plan, _, _ = _plan()
    target = plan.target_plans[0]

    assert {item.category_id for item in target.vacancy_receipts} == {
        "boundaries-integrations-protocols-dependencies",
        "configuration-controls-security-permissions",
        "failure-retry-recovery-degraded-behavior",
        "negative-space",
        "observability-operations-lifecycle",
        "state-models-transformations-invariants",
    }


@pytest.mark.unit
def test_subject_with_unknown_evidence_is_pre_activation_blocker() -> None:
    """A plan cannot cite evidence outside its exact target projection."""
    domain, selection, parent, l3, evidence = _authorities()
    bad = ExhaustiveSubjectV1(
        1,
        "domain",
        "api",
        domain,
        "operation:bad",
        ("public-surfaces",),
        (digest("unknown-shard"),),
        (),
        (digest("subject-bad"),),
    )
    subjects = build_exhaustive_subject_catalog(
        parent.source_snapshot_id,
        parent.partition_manifest_id,
        l3.identity,
        (bad,),
    )

    with pytest.raises(Protocol28PlanningError, match="unknown.*evidence"):
        build_exhaustive_plan(
            parent,
            l3,
            evidence,
            subjects,
            build_initial_exhaustive_policy(),
            selection,
        )


@pytest.mark.unit
def test_uncited_primary_shards_are_assigned_to_negative_space() -> None:
    """Lower-layer silence must cause discovery work, not an L4 coverage hole."""
    domain, selection, parent, l3, evidence = _authorities()
    subjects = build_exhaustive_subject_catalog(
        parent.source_snapshot_id, parent.partition_manifest_id, l3.identity, ()
    )

    plan = build_exhaustive_plan(
        parent, l3, evidence, subjects, build_initial_exhaustive_policy(), selection
    )
    discovery = next(
        item for item in plan.target_plans[0].entries if item.category_id == "negative-space"
    )

    assert discovery.primary_snapshot_evidence_ids == tuple(
        sorted(evidence.projections[0].primary_shard_ids)
    )


@pytest.mark.unit
def test_semantically_applicable_empty_evidence_category_is_not_vacant() -> None:
    """A real subject still requires analysis even when it has no direct shard."""
    domain, selection, parent, l3, evidence = _authorities()
    subject = ExhaustiveSubjectV1(
        1, "domain", "api", domain, "lifecycle:startup",
        ("observability-operations-lifecycle",), (), (), (digest("lifecycle"),),
    )
    subjects = build_exhaustive_subject_catalog(
        parent.source_snapshot_id, parent.partition_manifest_id, l3.identity, (subject,)
    )

    plan = build_exhaustive_plan(
        parent, l3, evidence, subjects, build_initial_exhaustive_policy(), selection
    )
    target = plan.target_plans[0]

    assert any(item.category_id == "observability-operations-lifecycle" for item in target.entries)
    assert all(item.category_id != "observability-operations-lifecycle" for item in target.vacancy_receipts)


@pytest.mark.unit
def test_context_is_split_before_canonical_byte_bound() -> None:
    """Packing accounts for subject bytes as well as raw evidence bytes."""
    domain, selection, parent, l3, evidence = _authorities(
        tuple(bytes([value]) * 65_536 for value in range(4))
    )
    shard_ids = tuple(item.shard_id for item in evidence.shards)
    first, second = _subjects(domain, shard_ids)
    subjects = build_exhaustive_subject_catalog(
        parent.source_snapshot_id,
        parent.partition_manifest_id,
        l3.identity,
        (first, replace(second, evidence_ids=tuple(sorted(shard_ids[1:])))),
    )

    policy = build_initial_exhaustive_policy()
    plan = build_exhaustive_plan(parent, l3, evidence, subjects, policy, selection)
    public = [
        item for item in plan.target_plans[0].entries if item.category_id == "public-surfaces"
    ]

    assert len(public) >= 2
    assert all(item.canonical_context_bytes <= policy.max_context_bytes for item in public)


@pytest.mark.unit
def test_realization_waits_for_every_named_dependency() -> None:
    """Deferred realization cannot substitute a convenient accepted root."""
    plan, _, _ = _plan()
    dependency_key = digest("planned-domain-root")
    entry = replace(
        plan.target_plans[0].entries[0],
        planned_dependency_root_ids=(dependency_key,),
    )

    with pytest.raises(Protocol28PlanningError, match="exactly realize"):
        realize_slice(entry, {})

    accepted = digest("accepted-domain-root")
    realized = realize_slice(entry, {dependency_key: accepted})
    assert realized.accepted_dependency_artifact_ids == (accepted,)


@pytest.mark.unit
def test_source_composition_waits_for_selected_domain_plan_roots() -> None:
    """Source composition is frozen before execution but realized after domains."""
    domain, selection, parent, l3, evidence = _authorities()
    source_projection = L3TargetAuthorityProjectionV1(
        schema_version=1,
        target_kind="source",
        source_id="api",
        target_id="api",
        target_content_id=digest("source-content"),
        candidate_authority_hash=digest("source-candidate"),
        finding_ids=(),
        unresolved_finding_ids=(),
        resolution_overlay_ids=(),
        closure_receipt_ids=(),
        closure_state="complete",
        relevant_l2_root_ids=(digest("source-l2-root"),),
        audit_policy_id=digest("audit-policy"),
        executor_policy_id=digest("executor-policy"),
    )
    source_membership = L3TargetEpochMembershipV1(
        1, source_projection.identity, l3.frozen_epoch_id, digest("source-epoch-entry")
    )
    l3 = replace(
        l3,
        projections=tuple(sorted((*l3.projections, source_projection), key=lambda item: item.sort_key)),
        memberships=tuple(
            sorted((*l3.memberships, source_membership), key=lambda item: item.target_projection_id)
        ),
    )
    parent = replace(
        parent,
        l3_projection_catalog_id=l3.identity,
        selected_projection_ids=tuple(sorted(item.identity for item in l3.projections)),
        selected_epoch_membership_ids=tuple(sorted(item.identity for item in l3.memberships)),
    )
    source_evidence = TargetSnapshotEvidenceProjectionV1(
        schema_version=1,
        target_kind="source",
        source_id="api",
        target_id="api",
        target_partition_id=digest("source-partition"),
        target_content_id=source_projection.target_content_id,
        source_snapshot_id=l3.source_snapshot_id,
        primary_shard_ids=(),
        primary_empty_receipt_ids=(),
        primary_nontext_disposition_ids=(),
        supporting_shard_ids=evidence.projections[0].primary_shard_ids,
        supporting_empty_receipt_ids=(),
        supporting_nontext_disposition_ids=(),
        membership_proof_ids=evidence.projections[0].membership_proof_ids,
    )
    evidence = replace(
        evidence,
        projections=tuple(
            sorted((*evidence.projections, source_evidence), key=lambda item: (item.source_id, item.target_kind, item.target_id))
        ),
    )
    source_subject = ExhaustiveSubjectV1(
        1, "source", "api", "api", "composition:selected-domains",
        ("source-composition",), (), (), (digest("source-composition"),),
    )
    subjects = build_exhaustive_subject_catalog(
        parent.source_snapshot_id, parent.partition_manifest_id, l3.identity,
        (*_subjects(domain, tuple(item.shard_id for item in evidence.shards)), source_subject),
    )

    plan = build_exhaustive_plan(
        parent, l3, evidence, subjects, build_initial_exhaustive_policy(), selection
    )
    domain_plan = next(item for item in plan.target_plans if item.target_kind == "domain")
    source_plan = next(item for item in plan.target_plans if item.target_kind == "source")
    composition = next(item for item in source_plan.entries if item.category_id == "source-composition")

    assert composition.planned_dependency_root_ids == (domain_plan.identity,)
