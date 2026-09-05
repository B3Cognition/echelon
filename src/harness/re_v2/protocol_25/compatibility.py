"""Explicit compatibility bridges for frozen protocol-2.5 authorities."""

from __future__ import annotations

from collections.abc import Collection

from harness.re_v2.protocol_22.schema import digest_value


# This reviewed change only relaxed L3SourceRootV1's selected-domain cardinality.
# The provider renderer and all four provider-result verifiers are unchanged, but
# the legacy implementation closure coarsely included the local root schema.
LEGACY_L3_IMPLEMENTATION_DIGEST = (
    "sha256:342dcbedd99a50a67c2c2b465e3eb55526bda213d2598798247b7b1fba8e31b0"
)
ZERO_DOMAIN_ROOT_L3_IMPLEMENTATION_DIGEST = (
    "sha256:6460528b314ab9e89e43157d34fb4b36d04b8b9d698822b709293ba1a4c9193a"
)


def compatible_installed_l3_digest(
    expected_digests: Collection[str],
    installed_digest: str,
) -> str:
    """Alias one reviewed root-only upgrade; fail closed for every other pair."""
    expected = frozenset(
        digest_value(value, "expected L3 implementation digest")
        for value in expected_digests
    )
    installed = digest_value(installed_digest, "installed L3 implementation digest")
    if (
        expected == frozenset((LEGACY_L3_IMPLEMENTATION_DIGEST,))
        and installed == ZERO_DOMAIN_ROOT_L3_IMPLEMENTATION_DIGEST
    ):
        return LEGACY_L3_IMPLEMENTATION_DIGEST
    return installed


__all__ = (
    "LEGACY_L3_IMPLEMENTATION_DIGEST",
    "ZERO_DOMAIN_ROOT_L3_IMPLEMENTATION_DIGEST",
    "compatible_installed_l3_digest",
)
