"""Combined inherited and L2 artifact policies for protocol 2.4."""

from __future__ import annotations

from dataclasses import replace

from harness.re_v2.protocol_22.policies import (
    ArtifactPolicyCatalogV1,
    ContextBundlePolicyParametersV1,
    build_compact_v1_policy_catalog,
    layer_policy_hash,
    policy_for,
)


def build_deepening_v1_policy_catalog() -> ArtifactPolicyCatalogV1:
    """Return exact L0/L1 authority plus the registered L2 policy slots."""
    inherited = build_compact_v1_policy_catalog()

    domain_evidence = replace(
        policy_for(inherited, "L0", "domain-evidence-pack"),
        layer="L2",
    )
    domain = replace(
        policy_for(inherited, "L1", "domain-baseline"),
        layer="L2",
        max_canonical_json_bytes=64 * 1024,
        max_rendered_markdown_bytes=128 * 1024,
        max_context_bundle_bytes=160 * 1024,
        max_conservative_input_tokens=163_840,
    )
    source = replace(
        policy_for(inherited, "L1", "source-overview"),
        layer="L2",
        max_canonical_json_bytes=64 * 1024,
        max_rendered_markdown_bytes=128 * 1024,
        max_context_bundle_bytes=128 * 1024,
        max_conservative_input_tokens=131_072,
    )

    inherited_domain_context = policy_for(
        inherited, "L1", "domain-context-bundle"
    )
    domain_context_parameters = inherited_domain_context.policy_parameters
    assert isinstance(domain_context_parameters, ContextBundlePolicyParametersV1)
    domain_context = replace(
        inherited_domain_context,
        layer="L2",
        max_canonical_json_bytes=160 * 1024,
        max_context_bundle_bytes=160 * 1024,
        max_conservative_input_tokens=163_840,
        policy_parameters=replace(
            domain_context_parameters,
            target_policy_hash=layer_policy_hash(domain),
        ),
    )

    inherited_source_context = policy_for(
        inherited, "L1", "source-overview-context-bundle"
    )
    source_context_parameters = inherited_source_context.policy_parameters
    assert isinstance(source_context_parameters, ContextBundlePolicyParametersV1)
    source_context = replace(
        inherited_source_context,
        layer="L2",
        max_canonical_json_bytes=128 * 1024,
        max_context_bundle_bytes=128 * 1024,
        max_conservative_input_tokens=131_072,
        policy_parameters=replace(
            source_context_parameters,
            target_policy_hash=layer_policy_hash(source),
        ),
    )
    source_root = replace(
        policy_for(inherited, "L1", "source-baseline-root"),
        layer="L2",
    )

    entries = (
        *inherited.entries,
        domain_evidence,
        domain_context,
        domain,
        source_context,
        source,
        source_root,
    )
    return ArtifactPolicyCatalogV1(
        schema_version=1,
        entries=tuple(sorted(entries, key=lambda entry: (entry.layer, entry.artifact_kind))),
    )


__all__ = ("build_deepening_v1_policy_catalog",)
