from __future__ import annotations

from harness.re_v2.protocol_22.policies import (
    ContextBundlePolicyParametersV1,
    build_compact_v1_policy_catalog,
    layer_policy_hash,
    policy_for,
)
from harness.re_v2.protocol_24.policies import build_deepening_v1_policy_catalog


L2_SLOTS = {
    ("L2", "domain-evidence-pack"),
    ("L2", "domain-context-bundle"),
    ("L2", "domain-baseline"),
    ("L2", "source-overview-context-bundle"),
    ("L2", "source-overview"),
    ("L2", "source-baseline-root"),
}


def test_deepening_catalog_preserves_every_inherited_policy_entry_exactly() -> None:
    inherited = build_compact_v1_policy_catalog()
    deepening = build_deepening_v1_policy_catalog()

    inherited_by_slot = {
        (entry.layer, entry.artifact_kind): entry for entry in inherited.entries
    }
    deepening_by_slot = {
        (entry.layer, entry.artifact_kind): entry for entry in deepening.entries
    }

    assert set(deepening_by_slot) == set(inherited_by_slot) | L2_SLOTS
    assert {
        slot: layer_policy_hash(deepening_by_slot[slot]) for slot in inherited_by_slot
    } == {
        slot: layer_policy_hash(entry) for slot, entry in inherited_by_slot.items()
    }


def test_deepening_catalog_pins_l2_context_and_authorial_limits() -> None:
    catalog = build_deepening_v1_policy_catalog()
    domain_context = policy_for(catalog, "L2", "domain-context-bundle")
    source_context = policy_for(
        catalog, "L2", "source-overview-context-bundle"
    )
    domain = policy_for(catalog, "L2", "domain-baseline")
    source = policy_for(catalog, "L2", "source-overview")

    assert (
        domain_context.max_context_bundle_bytes,
        domain_context.max_conservative_input_tokens,
    ) == (160 * 1024, 163_840)
    assert (
        source_context.max_context_bundle_bytes,
        source_context.max_conservative_input_tokens,
    ) == (128 * 1024, 131_072)
    assert domain.max_canonical_json_bytes == 64 * 1024
    assert source.max_canonical_json_bytes == 64 * 1024
    assert domain.max_rendered_markdown_bytes == 128 * 1024
    assert source.max_rendered_markdown_bytes == 128 * 1024


def test_l2_context_entries_bind_the_matching_l2_authorial_policy() -> None:
    catalog = build_deepening_v1_policy_catalog()

    for context_kind, target_kind in (
        ("domain-context-bundle", "domain-baseline"),
        ("source-overview-context-bundle", "source-overview"),
    ):
        context = policy_for(catalog, "L2", context_kind).policy_parameters
        assert isinstance(context, ContextBundlePolicyParametersV1)
        assert context.target_policy_hash == layer_policy_hash(
            policy_for(catalog, "L2", target_kind)
        )
