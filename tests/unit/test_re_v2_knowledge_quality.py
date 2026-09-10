from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from harness.re_v2.protocol_28 import policies
from harness.re_v2.protocol_28.planning import (
    ExhaustiveSubjectV1,
    Protocol28PlanningError,
    build_exhaustive_plan,
    build_exhaustive_subject_catalog,
)
from tests.unit.test_re_v2_protocol_28_planning import _authorities, _subjects


def _repaired_policy(**contracts):  # type: ignore[no-untyped-def]
    return policies.build_repaired_exhaustive_policy(**contracts)


def _complete_plan(payloads=(b"a\n", b"b\n")):  # type: ignore[no-untyped-def]
    domain, selection, parent, l3, evidence = _authorities(payloads)
    policy = _repaired_policy()
    subject = ExhaustiveSubjectV1(
        1, "domain", "api", domain, "operation:handler",
        tuple(sorted(policy.domain_categories)),
        tuple(sorted(shard.shard_id for shard in evidence.shards)), (), (),
    )
    subjects = build_exhaustive_subject_catalog(
        parent.source_snapshot_id, parent.partition_manifest_id, l3.identity, (subject,),
    )
    plan = build_exhaustive_plan(parent, l3, evidence, subjects, policy, selection)
    return plan, subjects, evidence, policy


@pytest.mark.unit
def test_policy_reader_preserves_legacy_and_repaired_contract_identities() -> None:
    legacy = policies.build_initial_exhaustive_policy()
    repaired = _repaired_policy()
    assert policies.ExhaustivePolicyV1.from_json_dict(legacy.to_json_dict()) == legacy
    decoded = policies.ExhaustivePolicyV1.from_json_dict(repaired.to_json_dict())
    assert decoded == repaired
    assert decoded.identity != legacy.identity
    assert policies.build_initial_exhaustive_policy() == legacy
    with pytest.raises(policies.Protocol28PolicyError):
        replace(decoded, producer_attempt_limit=4)


@pytest.mark.unit
@pytest.mark.parametrize("empty_catalog", [False, True])
def test_repaired_planning_does_not_certify_unassessed_categories(empty_catalog: bool) -> None:
    domain, selection, parent, l3, evidence = _authorities()
    subjects = build_exhaustive_subject_catalog(
        parent.source_snapshot_id, parent.partition_manifest_id, l3.identity,
        () if empty_catalog else _subjects(domain, tuple(s.shard_id for s in evidence.shards)),
    )
    with pytest.raises(Protocol28PlanningError, match="unassessed"):
        build_exhaustive_plan(parent, l3, evidence, subjects, _repaired_policy(), selection)


@pytest.mark.unit
def test_overflow_evidence_keeps_relevant_subjects_and_exact_primary_ownership() -> None:
    plan, subjects, evidence, policy = _complete_plan(
        tuple(bytes([value]) * 65_536 for value in range(4))
    )
    target = plan.target_plans[0]
    assert not target.vacancy_receipts
    assert {entry.category_id for entry in target.entries} == set(policy.domain_categories)
    primary = [shard for entry in target.entries for shard in entry.primary_snapshot_evidence_ids]
    assert sorted(primary) == sorted(shard.shard_id for shard in evidence.shards)
    assert len(primary) == len(set(primary))
    assert any(entry.supporting_subject_ids for entry in target.entries)
    for entry in target.entries:
        assert entry.canonical_context_bytes <= policy.max_context_bytes
        attached = set(entry.primary_subject_ids + entry.supporting_subject_ids)
        for shard_id in entry.primary_snapshot_evidence_ids:
            assert any(
                subject.identity in attached and shard_id in subject.evidence_ids
                and entry.category_id in subject.category_ids
                for subject in subjects.subjects
            ), "overflow shard lost its subject"


@pytest.mark.unit
def test_repaired_planning_rejects_orphan_evidence_instead_of_inventing_a_subject() -> None:
    domain, selection, parent, l3, evidence = _authorities()
    policy = _repaired_policy()
    subject = ExhaustiveSubjectV1(
        1, "domain", "api", domain, "operation:first",
        tuple(sorted(policy.domain_categories)), (evidence.shards[0].shard_id,), (), (),
    )
    subjects = build_exhaustive_subject_catalog(
        parent.source_snapshot_id, parent.partition_manifest_id, l3.identity, (subject,),
    )
    with pytest.raises(Protocol28PlanningError, match="subject.*evidence|evidence.*subject"):
        build_exhaustive_plan(parent, l3, evidence, subjects, policy, selection)


@pytest.mark.unit
def test_real_preparation_blocks_unassessed_categories_before_child_publication(tmp_path: Path) -> None:
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.protocol_28.preparation import prepare_protocol_28_request
    from tests.unit.test_re_v2_protocol_28_preparation import _preparation_fixture

    workspace, intent, parent, options = _preparation_fixture(tmp_path)
    policy = _repaired_policy(
        producer_contract_hash=content_digest(options.producer_agent_bytes),
        verifier_contract_hash=content_digest(options.verifier_agent_bytes),
    )
    intent = replace(intent, exhaustive_policy_catalog_id=policy.identity)
    with pytest.raises(Protocol28PlanningError, match="unassessed"):
        prepare_protocol_28_request(workspace, intent, parent, options)
    assert not (workspace / "runs" / options.run_id).exists()


def _prepared_complete_plan(tmp_path: Path, *, large: bool = False):  # type: ignore[no-untyped-def]
    from harness.re_v2.protocol_28.preparation import prepare_protocol_28_request
    from tests.unit.test_re_v2_protocol_28_preparation import _preparation_fixture

    workspace, intent, parent, options = _preparation_fixture(tmp_path, large_source=large)
    legacy = prepare_protocol_28_request(workspace, intent, parent, options)
    policy = _repaired_policy(
        producer_contract_hash=legacy.exhaustive_policy.producer_contract_hash,
        verifier_contract_hash=legacy.exhaustive_policy.verifier_contract_hash,
    )
    subjects = replace(legacy.exhaustive_subject_catalog, subjects=tuple(
        replace(subject, category_ids=tuple(sorted(
            policy.domain_categories if subject.target_kind == "domain" else policy.source_categories
        ))) for subject in legacy.exhaustive_subject_catalog.subjects
    ))
    plan = build_exhaustive_plan(
        legacy.parent_authority_bundle, legacy.l3_projection_catalog,
        legacy.snapshot_evidence_catalog, subjects, policy, legacy.manifest.selection,
    )
    return legacy, plan, subjects, policy


@pytest.mark.unit
def test_real_exact_sizing_splits_supporting_evidence_without_losing_subjects(tmp_path: Path) -> None:
    from harness.re_v2.protocol_28.preparation import _bind_exact_context_sizes

    legacy, plan, subjects, policy = _prepared_complete_plan(tmp_path, large=True)
    sized = _bind_exact_context_sizes(
        plan, legacy.l3_projection_catalog, legacy.snapshot_evidence_catalog,
        subjects, policy, legacy.authority_objects,
    )
    assert sum(len(t.entries) for t in sized.target_plans) > sum(len(t.entries) for t in plan.target_plans)
    for target in sized.target_plans:
        for entry in target.entries:
            assert entry.canonical_context_bytes <= policy.max_context_bytes
            attached = set(entry.primary_subject_ids + entry.supporting_subject_ids)
            for evidence_id in entry.primary_snapshot_evidence_ids + entry.supporting_snapshot_evidence_ids:
                assert any(
                    subject.identity in attached and evidence_id in subject.evidence_ids
                    and entry.category_id in subject.category_ids
                    for subject in subjects.subjects
                )


def _manifest_for_plan(legacy, plan, policy):  # type: ignore[no-untyped-def]
    request = replace(
        legacy.manifest.exhaustive_request,
        exhaustive_plan_id=plan.identity, exhaustive_policy_catalog_id=policy.identity,
    )
    return replace(
        legacy.manifest, exhaustive_request=request,
        exhaustive_plan_id=plan.identity, exhaustive_policy_catalog_id=policy.identity,
    )


def _false_plan(plan, defect):  # type: ignore[no-untyped-def]
    target = plan.target_plans[0]
    if defect == "unassessed":
        entries = tuple(e for e in target.entries if e.category_id != target.entries[-1].category_id)
    else:
        entries = (replace(target.entries[0], primary_subject_ids=(), supporting_subject_ids=()),
                   *target.entries[1:])
    return replace(plan, target_plans=(replace(target, entries=entries), *plan.target_plans[1:]))


@pytest.mark.unit
@pytest.mark.parametrize("defect", ["unassessed", "subjects"])
def test_creation_rejects_hash_consistent_false_coverage(tmp_path: Path, defect: str) -> None:
    from harness.re_v2.protocol_28.inputs import Protocol28InputError

    legacy, plan, subjects, policy = _prepared_complete_plan(tmp_path)
    plan = _false_plan(plan, defect)
    with pytest.raises(Protocol28InputError, match="unassessed|subjects"):
        replace(
            legacy, manifest=_manifest_for_plan(legacy, plan, policy),
            exhaustive_plan=plan, exhaustive_subject_catalog=subjects, exhaustive_policy=policy,
        )


@pytest.mark.unit
def test_durable_load_rechecks_repaired_coverage_after_valid_round_trip(tmp_path: Path) -> None:
    from harness.re_v2.canonical import canonical_json_bytes
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_28.inputs import (
        Protocol28InputError, load_protocol_28_inputs, publish_protocol_28_run,
        stage_exhaustive_inputs,
    )
    from harness.re_v2.run_store import ReV2Paths

    legacy, plan, subjects, policy = _prepared_complete_plan(tmp_path)
    manifest = _manifest_for_plan(legacy, plan, policy)
    inputs = replace(
        legacy, manifest=manifest, exhaustive_plan=plan,
        exhaustive_subject_catalog=subjects, exhaustive_policy=policy,
    )
    stage, final = tmp_path / "stage", tmp_path / manifest.run_id
    stage_exhaustive_inputs(stage, inputs)
    publish_protocol_28_run(stage, final, manifest)
    loaded = load_protocol_28_inputs(final)
    assert loaded.exhaustive_policy == policy
    assert loaded.exhaustive_plan == plan

    # Consistent content hashes are necessary but cannot certify structural coverage.
    bad_plan = _false_plan(plan, "subjects")
    bad_manifest = _manifest_for_plan(legacy, bad_plan, policy)
    paths = ReV2Paths.for_run(final)
    store = ObjectStore(paths.objects)
    for target in bad_plan.target_plans:
        for authority in (target, target.coverage_ledger, *target.entries):
            store.put_blob(canonical_json_bytes(authority.to_json_dict()))
    for name, authority in (
        ("exhaustive-plan.json", bad_plan),
        ("exhaustive-request.json", bad_manifest.exhaustive_request),
    ):
        payload = canonical_json_bytes(authority.to_json_dict())
        store.put_blob(payload)
        path = paths.inputs / name
        path.chmod(0o600)
        path.write_bytes(payload)
    paths.manifest.chmod(0o600)
    paths.manifest.write_bytes(canonical_json_bytes(bad_manifest.to_json_dict()))
    with pytest.raises(Protocol28InputError, match="subjects"):
        load_protocol_28_inputs(final)


@pytest.mark.unit
@pytest.mark.parametrize("defect", ["primary_subject", "records", "ledger", "entry_target", "category_evidence"])
def test_repaired_coverage_rejects_structurally_consistent_omissions(defect: str) -> None:
    from harness.re_v2.protocol_28.planning import validate_exhaustive_plan_coverage

    plan, subjects, evidence, policy = _complete_plan()
    target = plan.target_plans[0]
    entries = list(target.entries)
    ledger = target.coverage_ledger
    if defect == "primary_subject":
        entries[0] = replace(entries[0], supporting_subject_ids=entries[0].primary_subject_ids,
                             primary_subject_ids=())
    elif defect == "records":
        entries[0] = replace(entries[0], primary_source_record_ids=())
    elif defect == "ledger":
        ledger = replace(ledger, subject_assignment_ids=())
    elif defect == "entry_target":
        entries[0] = replace(entries[0], source_id="unselected-source")
    else:
        entries[-1] = replace(entries[-1], supporting_snapshot_evidence_ids=())
    plan = replace(plan, target_plans=(replace(target, entries=tuple(entries), coverage_ledger=ledger),))
    with pytest.raises(Protocol28PlanningError):
        validate_exhaustive_plan_coverage(plan, subjects, evidence, policy)


@pytest.mark.unit
@pytest.mark.parametrize("defect", ["target", "finding"])
def test_input_boundary_rechecks_parent_obligations(tmp_path: Path, defect: str) -> None:
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.protocol_28.inputs import (
        Protocol28InputError, ValidatedProtocol28Inputs, _validate_bindings,
    )
    from harness.re_v2.protocol_28.model import ExhaustiveRequestV1, ExhaustiveRunManifestV7

    legacy, plan, subjects, policy = _prepared_complete_plan(tmp_path)
    evidence, parent = legacy.snapshot_evidence_catalog, legacy.parent_authority_bundle
    if defect == "target":
        # Keep the plan, subjects and evidence mutually consistent while dropping a selected target.
        removed = plan.target_plans[-1].sort_key
        evidence = replace(evidence, projections=tuple(
            p for p in evidence.projections if (p.source_id, p.target_kind, p.target_id) != removed
        ))
        subjects = replace(subjects, subjects=tuple(
            s for s in subjects.subjects if (s.source_id, s.target_kind, s.target_id) != removed
        ))
        plan = replace(plan, target_plans=plan.target_plans[:-1],
                       evidence_catalog_id=evidence.identity, subject_catalog_id=subjects.identity)
    else:
        parent = replace(parent, unresolved_deeper_finding_ids=(content_digest(b"required-finding"),))
        plan = replace(plan, parent_authority_bundle_id=parent.identity)
    manifest = _manifest_for_plan(legacy, plan, policy)
    manifest = replace(
        manifest, parent_authority_bundle_id=parent.identity, snapshot_evidence_catalog_id=evidence.identity,
        exhaustive_request=replace(manifest.exhaustive_request,
                                   parent_authority_bundle_id=parent.identity,
                                   snapshot_evidence_catalog_id=evidence.identity),
    )
    # This test exercises the historical boundary independently of the Safe subtype.
    # Preparation now emits Safe manifests; do not wrap one in a legacy input type.
    request = ExhaustiveRequestV1(**{
        field: getattr(manifest.exhaustive_request, field) for field in ExhaustiveRequestV1.FIELDS
    })
    manifest = ExhaustiveRunManifestV7(**{
        field: request if field == "exhaustive_request" else getattr(manifest, field)
        for field in ExhaustiveRunManifestV7.FIELDS
    })
    inputs = ValidatedProtocol28Inputs(
        manifest, parent, legacy.l3_projection_catalog, evidence, subjects,
        policy, legacy.executor_catalog, plan, legacy.authority_objects,
    )
    with pytest.raises(Protocol28InputError, match="target|finding"):
        _validate_bindings(inputs)


@pytest.mark.unit
def test_exact_splitting_respects_support_caps_as_well_as_bytes() -> None:
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.protocol_28.preparation import _bind_exact_context_sizes

    domain, selection, parent, l3, evidence = _authorities(
        (b"52:" + b"x" * 65_520, *(b"a\n" for _ in range(47)))
    )
    lower = b"z" * 100_000
    policy = _repaired_policy()
    subjects = build_exhaustive_subject_catalog(
        parent.source_snapshot_id, parent.partition_manifest_id, l3.identity,
        tuple(ExhaustiveSubjectV1(
            1, "domain", "api", domain, f"operation:{index}",
            tuple(sorted(policy.domain_categories)), (shard.shard_id,), (),
            (content_digest(lower),),
        ) for index, shard in enumerate(evidence.shards)),
    )
    plan = build_exhaustive_plan(parent, l3, evidence, subjects, policy, selection)
    sized = _bind_exact_context_sizes(
        plan, l3, evidence, subjects, policy,
        {content_digest(payload): payload for payload in (lower, b"candidate", b"l2-root")},
    )
    for target in sized.target_plans:
        for entry in target.entries:
            assert entry.canonical_context_bytes <= policy.max_context_bytes
            assert len(entry.supporting_subject_ids) <= policy.max_supporting_subjects
            assert len(entry.supporting_source_record_ids) <= policy.max_supporting_records
