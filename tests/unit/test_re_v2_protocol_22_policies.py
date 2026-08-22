from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.protocol_22.policies import (
    ArtifactPolicyCatalogV1,
    CompactBaselinePolicyParametersV1,
    ContextBundlePolicyParametersV1,
    DomainEvidencePackPolicyParametersV1,
    EmptyPolicyParametersV1,
    Protocol22PolicyError,
    SourceEvidencePackPolicyParametersV1,
    build_compact_v1_policy_catalog,
    layer_policy_hash,
    policy_for,
)
from harness.re_v2.protocol_22.schema import load_canonical_object
from tests.re_v2_protocol_22_fixtures import digest


EXPECTED_KINDS = {
    ("L0", "source-inventory"),
    ("L0", "source-partition"),
    ("L0", "domain-inventory"),
    ("L0", "source-evidence-pack"),
    ("L0", "domain-evidence-pack"),
    ("L1", "domain-context-bundle"),
    ("L1", "source-overview-context-bundle"),
    ("L1", "domain-baseline"),
    ("L1", "source-overview"),
    ("L1", "source-baseline-root"),
}

DOMAIN_SURFACES = (
    "responsibilities",
    "entry_points",
    "core_behavior",
    "failure_paths",
    "state_and_data",
    "external_contracts",
    "tests",
    "operational_constraints",
)

SOURCE_SURFACES = (
    "purpose",
    "runtime_shape",
    "major_entry_points",
    "intra_source_boundaries",
    "domain_relationships",
)


def test_builtin_catalog_has_one_policy_per_graph_slot() -> None:
    catalog = build_compact_v1_policy_catalog()

    assert {(entry.layer, entry.artifact_kind) for entry in catalog.entries} == EXPECTED_KINDS
    assert tuple((entry.layer, entry.artifact_kind) for entry in catalog.entries) == tuple(
        sorted(EXPECTED_KINDS)
    )


def test_builtin_catalog_pins_literal_compact_bounds_and_surfaces() -> None:
    catalog = build_compact_v1_policy_catalog()
    domain = policy_for(catalog, "L1", "domain-baseline")
    source = policy_for(catalog, "L1", "source-overview")

    assert domain.required_surfaces == DOMAIN_SURFACES
    assert source.required_surfaces == SOURCE_SURFACES
    assert (domain.max_canonical_json_bytes, source.max_canonical_json_bytes) == (
        32 * 1024,
        48 * 1024,
    )
    assert (domain.max_context_bundle_bytes, source.max_context_bundle_bytes) == (
        128 * 1024,
        96 * 1024,
    )
    assert (
        domain.max_conservative_input_tokens,
        source.max_conservative_input_tokens,
    ) == (131_072, 98_304)
    assert domain.max_rendered_markdown_bytes == 96 * 1024
    assert source.max_rendered_markdown_bytes == 96 * 1024


def test_policy_parameter_branches_match_only_their_artifact_kinds() -> None:
    catalog = build_compact_v1_policy_catalog()

    assert isinstance(
        policy_for(catalog, "L0", "source-evidence-pack").policy_parameters,
        SourceEvidencePackPolicyParametersV1,
    )
    assert isinstance(
        policy_for(catalog, "L0", "domain-evidence-pack").policy_parameters,
        DomainEvidencePackPolicyParametersV1,
    )
    assert isinstance(
        policy_for(catalog, "L1", "domain-context-bundle").policy_parameters,
        ContextBundlePolicyParametersV1,
    )
    assert isinstance(
        policy_for(catalog, "L1", "domain-baseline").policy_parameters,
        CompactBaselinePolicyParametersV1,
    )
    assert isinstance(
        policy_for(catalog, "L0", "source-inventory").policy_parameters,
        EmptyPolicyParametersV1,
    )


def test_evidence_roles_and_omission_codes_are_literal_and_ordered() -> None:
    catalog = build_compact_v1_policy_catalog()
    source = policy_for(catalog, "L0", "source-evidence-pack").policy_parameters
    domain = policy_for(catalog, "L0", "domain-evidence-pack").policy_parameters
    assert isinstance(source, SourceEvidencePackPolicyParametersV1)
    assert isinstance(domain, DomainEvidencePackPolicyParametersV1)

    assert source.role_priority == (
        "declared_entry_point",
        "build_runtime",
        "explicit_supporting",
        "documentation",
    )
    assert domain.role_priority == (
        "explicit_supporting",
        "entry_point",
        "production",
        "test",
        "documentation",
        "other",
    )
    assert tuple(classifier.role for classifier in source.path_classifiers) == source.role_priority
    assert tuple(classifier.role for classifier in domain.path_classifiers) == domain.role_priority
    assert source.omission_reason_codes == (
        "policy_ineligible",
        "non_text",
        "line_too_large",
        "capacity_exhausted",
    )
    assert domain.omission_reason_codes == source.omission_reason_codes


def test_context_policy_pins_exact_target_policy_hash_and_projection_branch() -> None:
    catalog = build_compact_v1_policy_catalog()
    domain_target = policy_for(catalog, "L1", "domain-baseline")
    source_target = policy_for(catalog, "L1", "source-overview")
    domain_context = policy_for(catalog, "L1", "domain-context-bundle").policy_parameters
    source_context = policy_for(
        catalog, "L1", "source-overview-context-bundle"
    ).policy_parameters
    assert isinstance(domain_context, ContextBundlePolicyParametersV1)
    assert isinstance(source_context, ContextBundlePolicyParametersV1)

    assert domain_context.target_artifact_kind == "domain-baseline"
    assert domain_context.target_policy_hash == layer_policy_hash(domain_target)
    assert domain_context.projection is None
    assert source_context.target_artifact_kind == "source-overview"
    assert source_context.target_policy_hash == layer_policy_hash(source_target)
    assert source_context.projection is not None
    assert source_context.projection.surface_priority == (
        "responsibilities",
        "entry_points",
        "external_contracts",
    )
    assert source_context.projection.max_canonical_bytes_per_domain == 2048
    assert source_context.projection.max_total_canonical_bytes == 32768


def test_catalog_rejects_context_hash_that_does_not_resolve_to_target_policy() -> None:
    catalog = build_compact_v1_policy_catalog()
    context = policy_for(catalog, "L1", "domain-context-bundle")
    parameters = context.policy_parameters
    assert isinstance(parameters, ContextBundlePolicyParametersV1)
    changed_context = replace(
        context,
        policy_parameters=replace(parameters, target_policy_hash=digest("fabricated-policy")),
    )
    changed_entries = tuple(
        changed_context if entry is context else entry for entry in catalog.entries
    )

    with pytest.raises(Protocol22PolicyError, match="target_policy_hash"):
        ArtifactPolicyCatalogV1(schema_version=1, entries=changed_entries)


def test_catalog_round_trip_preserves_canonical_bytes_and_hashes() -> None:
    catalog = build_compact_v1_policy_catalog()
    payload = canonical_json_bytes(catalog.to_json_dict())

    restored = load_canonical_object(payload, ArtifactPolicyCatalogV1.from_json_dict)

    assert canonical_json_bytes(restored.to_json_dict()) == payload
    assert [layer_policy_hash(entry) for entry in restored.entries] == [
        layer_policy_hash(entry) for entry in catalog.entries
    ]


def test_policy_for_rejects_unknown_graph_slot() -> None:
    with pytest.raises(Protocol22PolicyError, match="unknown artifact policy"):
        policy_for(build_compact_v1_policy_catalog(), "L2", "future-artifact")


def test_classifier_pattern_mutation_rekeys_only_its_policy_entry() -> None:
    catalog = build_compact_v1_policy_catalog()
    source_entry = policy_for(catalog, "L0", "source-evidence-pack")
    source_parameters = source_entry.policy_parameters
    assert isinstance(source_parameters, SourceEvidencePackPolicyParametersV1)
    classifier = source_parameters.path_classifiers[0]
    changed_classifier = replace(
        classifier,
        patterns=tuple(sorted((*classifier.patterns, "**/bootstrap.*"))),
    )
    changed_parameters = replace(
        source_parameters,
        path_classifiers=(changed_classifier, *source_parameters.path_classifiers[1:]),
    )
    changed_entry = replace(source_entry, policy_parameters=changed_parameters)

    assert layer_policy_hash(changed_entry) != layer_policy_hash(source_entry)
    domain_entry = policy_for(catalog, "L0", "domain-evidence-pack")
    assert layer_policy_hash(domain_entry) == layer_policy_hash(
        policy_for(build_compact_v1_policy_catalog(), "L0", "domain-evidence-pack")
    )


def test_legal_compact_limit_mutation_changes_the_complete_entry_hash() -> None:
    entry = policy_for(build_compact_v1_policy_catalog(), "L1", "domain-baseline")
    parameters = entry.policy_parameters
    assert isinstance(parameters, CompactBaselinePolicyParametersV1)
    changed = replace(
        entry,
        policy_parameters=replace(parameters, max_statement_utf8_bytes=900),
    )

    assert layer_policy_hash(changed) != layer_policy_hash(entry)


def test_catalog_rejects_duplicate_or_missing_graph_slots() -> None:
    catalog = build_compact_v1_policy_catalog()

    with pytest.raises(Protocol22PolicyError, match="exact graph slots"):
        ArtifactPolicyCatalogV1(schema_version=1, entries=catalog.entries[:-1])
    with pytest.raises(Protocol22PolicyError, match="sorted and unique"):
        ArtifactPolicyCatalogV1(
            schema_version=1,
            entries=(catalog.entries[0], catalog.entries[0], *catalog.entries[2:]),
        )


def test_compact_surface_order_cannot_drift_from_required_surfaces() -> None:
    entry = policy_for(build_compact_v1_policy_catalog(), "L1", "domain-baseline")
    parameters = entry.policy_parameters
    assert isinstance(parameters, CompactBaselinePolicyParametersV1)

    with pytest.raises(Protocol22PolicyError, match="surface_order"):
        replace(entry, required_surfaces=tuple(reversed(entry.required_surfaces)))


def test_unknown_policy_parameter_fields_are_rejected() -> None:
    catalog = build_compact_v1_policy_catalog().to_json_dict()
    entries = catalog["entries"]
    assert isinstance(entries, list)
    baseline = next(entry for entry in entries if entry["artifact_kind"] == "domain-baseline")
    parameters = baseline["policy_parameters"]
    assert isinstance(parameters, dict)
    parameters["future_extension"] = True

    with pytest.raises(Protocol22PolicyError, match="unknown fields"):
        ArtifactPolicyCatalogV1.from_json_dict(catalog)
