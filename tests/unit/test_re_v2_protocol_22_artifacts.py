from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.artifacts import (
    AcceptedDependencySetV2,
    ArtifactDependencyV1,
    ArtifactEnvelopeV1,
    ContextBundleV1,
    DepthDebtV1,
    DeterministicAssessmentInputV2,
    DomainDepthDebtRollupV1,
    EvidenceExcerptV1,
    EvidencePackV1,
    OmittedDomainDescriptorV1,
    OmittedEvidenceDescriptorV1,
    OmittedProjectedClaimDescriptorV1,
    SourceBaselineDomainV1,
    SourceBaselineRootV1,
)
from harness.re_v2.protocol_22.graph import AcceptedArtifactV2
from harness.re_v2.protocol_22.policies import (
    ContextBundlePolicyParametersV1,
    build_compact_v1_policy_catalog,
    layer_policy_hash,
    policy_for,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    load_canonical_object,
)
from tests.re_v2_protocol_22_fixtures import artifact_scope_v2, digest


def _zero_debt() -> DepthDebtV1:
    return DepthDebtV1(
        inventory_file_count=0,
        fully_selected_file_count=0,
        partially_selected_file_count=0,
        omitted_file_count=0,
        omitted_range_count=0,
        omitted_descriptor_hash=None,
        domain_depth_debt_rollup=None,
        omitted_domain_summary_count=0,
        omitted_domain_descriptor_hash=None,
        retained_projected_claim_count=0,
        omitted_projected_claim_count=0,
        omitted_projected_claim_descriptor_hash=None,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("changes", "message"),
    (
        (
            {"inventory_file_count": 1, "omitted_file_count": 1},
            "omitted_descriptor_hash",
        ),
        ({"omitted_descriptor_hash": digest("unexpected")}, "omitted_descriptor_hash"),
        ({"inventory_file_count": 1}, "file counts"),
        ({"omitted_domain_summary_count": 1}, "omitted_domain_descriptor_hash"),
        (
            {"omitted_domain_descriptor_hash": digest("unexpected-domain")},
            "omitted_domain_descriptor_hash",
        ),
        ({"omitted_projected_claim_count": 1}, "projected_claim_descriptor_hash"),
        (
            {"omitted_projected_claim_descriptor_hash": digest("unexpected-claim")},
            "projected_claim_descriptor_hash",
        ),
    ),
)
def test_depth_debt_enforces_count_and_zero_null_equations(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(Protocol22SchemaError, match=message):
        replace(_zero_debt(), **changes)


@pytest.mark.unit
def test_domain_rollup_enforces_read_set_equation_and_domain_hash_rule() -> None:
    with pytest.raises(Protocol22SchemaError, match="read-set counts"):
        DomainDepthDebtRollupV1(
            domain_count=1,
            inventory_read_set_entry_count=2,
            fully_selected_read_set_entry_count=0,
            partially_selected_read_set_entry_count=0,
            omitted_read_set_entry_count=0,
            omitted_range_count=0,
            domain_debt_descriptor_hash=digest("rollup"),
        )
    with pytest.raises(Protocol22SchemaError, match="domain_debt_descriptor_hash"):
        DomainDepthDebtRollupV1(
            domain_count=1,
            inventory_read_set_entry_count=0,
            fully_selected_read_set_entry_count=0,
            partially_selected_read_set_entry_count=0,
            omitted_read_set_entry_count=0,
            omitted_range_count=0,
            domain_debt_descriptor_hash=None,
        )


@pytest.mark.unit
def test_omission_descriptors_enforce_line_and_ownership_nullability() -> None:
    with pytest.raises(Protocol22SchemaError, match="line fields"):
        OmittedEvidenceDescriptorV1(
            descriptor_kind="file",
            source_relative_path="src/app.py",
            ownership="source",
            origin_domain_key=None,
            start_line=1,
            end_line=1,
            reason_code="policy_ineligible",
        )
    with pytest.raises(Protocol22SchemaError, match="origin_domain_key"):
        OmittedEvidenceDescriptorV1(
            descriptor_kind="line_range",
            source_relative_path="src/app.py",
            ownership="owned",
            origin_domain_key=None,
            start_line=2,
            end_line=3,
            reason_code="capacity_exhausted",
        )


@pytest.mark.unit
def test_all_omission_descriptor_variants_round_trip_canonically() -> None:
    values = (
        OmittedEvidenceDescriptorV1(
            descriptor_kind="file",
            source_relative_path="README.md",
            ownership="source",
            origin_domain_key=None,
            start_line=None,
            end_line=None,
            reason_code="policy_ineligible",
        ),
        OmittedDomainDescriptorV1(
            domain_key=digest("domain"),
            baseline_artifact_hash=digest("baseline"),
            reason_code="capacity_exhausted",
        ),
        OmittedProjectedClaimDescriptorV1(
            domain_key=digest("domain"),
            surface="responsibilities",
            claim_index=0,
            claim_hash=digest("claim"),
            reason_code="capacity_exhausted",
        ),
    )

    for value in values:
        payload = canonical_json_bytes(value.to_json_dict())
        assert load_canonical_object(payload, type(value).from_json_dict) == value


@pytest.mark.unit
def test_evidence_excerpt_requires_regular_mode_and_matching_origin() -> None:
    excerpt = EvidenceExcerptV1(
        evidence_authority_id=digest("authority"),
        source_relative_path="src/app.py",
        ownership="source",
        origin_domain_key=None,
        mode="100644",
        source_blob_hash=digest("blob"),
        start_line=1,
        end_line=1,
        raw_excerpt_hash=content_digest(b"line\n"),
        text_lf="line\n",
        complete_file=True,
    )

    with pytest.raises(Protocol22SchemaError, match="regular"):
        replace(excerpt, mode="120000")
    with pytest.raises(Protocol22SchemaError, match="origin_domain_key"):
        replace(excerpt, ownership="owned")


@pytest.mark.unit
def test_empty_evidence_pack_round_trips_and_enforces_scope_kind() -> None:
    pack = EvidencePackV1(
        schema_version=1,
        artifact_kind="source-evidence-pack",
        scope=artifact_scope_v2(),
        layer_policy_hash=digest("policy"),
        inventory_artifact_hash=digest("inventory"),
        byte_estimator_id="utf8-byte-upper-bound-v1",
        max_canonical_json_bytes=48 * 1024,
        max_conservative_input_tokens=48 * 1024,
        excerpts=(),
        depth_debt=_zero_debt(),
    )
    payload = canonical_json_bytes(pack.to_json_dict())

    assert load_canonical_object(payload, EvidencePackV1.from_json_dict) == pack
    with pytest.raises(Protocol22SchemaError, match="domain_key"):
        replace(pack, artifact_kind="domain-evidence-pack")


@pytest.mark.unit
def test_domain_context_pins_target_policy_and_dependency() -> None:
    policies = build_compact_v1_policy_catalog()
    context_policy = policy_for(policies, "L1", "domain-context-bundle")
    target_policy = policy_for(policies, "L1", "domain-baseline")
    assert isinstance(context_policy.policy_parameters, ContextBundlePolicyParametersV1)
    evidence_hash = digest("evidence-pack")
    context = ContextBundleV1(
        schema_version=1,
        artifact_kind="domain-context-bundle",
        target_artifact_kind="domain-baseline",
        scope=artifact_scope_v2(domain=True),
        context_policy_hash=layer_policy_hash(context_policy),
        target_policy_hash=layer_policy_hash(target_policy),
        target_artifact_policy=target_policy,
        dependencies=(
            ArtifactDependencyV1("domain-evidence-pack", evidence_hash),
            ArtifactDependencyV1("domain-inventory", digest("inventory")),
        ),
        evidence_pack_hash=evidence_hash,
        evidence=(),
        domain_projections=(),
        depth_debt=_zero_debt(),
    )

    payload = canonical_json_bytes(context.to_json_dict())
    assert load_canonical_object(payload, ContextBundleV1.from_json_dict) == context
    with pytest.raises(Protocol22SchemaError, match="target policy"):
        replace(context, target_policy_hash=digest("wrong"))


@pytest.mark.unit
def test_source_root_requires_exact_overview_and_domain_dependency_set() -> None:
    overview_hash = digest("overview")
    domain_hash = digest("domain baseline")
    root = SourceBaselineRootV1(
        schema_version=1,
        artifact=ArtifactEnvelopeV1(
            artifact_kind="source-baseline-root",
            layer="L1",
            scope=artifact_scope_v2(),
            partition_id=digest("source partition"),
            layer_policy_hash=digest("root policy"),
            dependency_hashes=tuple(sorted((overview_hash, domain_hash))),
        ),
        overview_artifact_hash=overview_hash,
        domains=(
            SourceBaselineDomainV1(
                domain_key=digest("orders"),
                presentation_domain_id="001-re-orders",
                baseline_artifact_hash=domain_hash,
            ),
        ),
    )

    assert SourceBaselineRootV1.from_json_dict(root.to_json_dict()) == root
    with pytest.raises(Protocol22SchemaError, match="dependency"):
        replace(root, overview_artifact_hash=digest("not present"))


@pytest.mark.unit
def test_accepted_dependency_set_is_closed_sorted_and_immutable() -> None:
    dependencies = AcceptedDependencySetV2(
        by_role={
            "workspace_partition": AcceptedArtifactV2(
                digest("partition-key"), digest("partition")
            )
        }
    )

    assert tuple(dependencies.by_role) == ("workspace_partition",)
    with pytest.raises(TypeError):
        dependencies.by_role["extra"] = AcceptedArtifactV2(  # type: ignore[index]
            digest("extra-key"), digest("extra")
        )
    with pytest.raises(Protocol22SchemaError, match="role"):
        AcceptedDependencySetV2(
            by_role={"bad role": AcceptedArtifactV2(digest("key"), digest("value"))}
        )


@pytest.mark.unit
def test_deterministic_assessment_truth_values_bind_diagnostics() -> None:
    accepted = DeterministicAssessmentInputV2(
        canonical_schema_valid=True,
        dependency_closure_valid=True,
        policy_conformance_valid=True,
        depth_debt=None,
        normalized_diagnostics=(),
    )
    assert accepted.normalized_diagnostics == ()

    with pytest.raises(Protocol22SchemaError, match="diagnostic"):
        replace(accepted, canonical_schema_valid=False)
    with pytest.raises(Protocol22SchemaError, match="diagnostic"):
        replace(accepted, normalized_diagnostics=("unexpected",))
