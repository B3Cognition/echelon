"""Explicit compatibility bridges for frozen protocol-2.5 authorities."""

from __future__ import annotations

from collections.abc import Collection

from harness.re_v2.protocol_22.schema import digest_value


# These are exact reviewed bridges for the preserved OptaSearch authority. The
# first relaxed zero-domain source-root cardinality. The second adds authenticated
# guidance projection and bounded convergence without changing result schemas.
LEGACY_L3_IMPLEMENTATION_DIGEST = (
    "sha256:342dcbedd99a50a67c2c2b465e3eb55526bda213d2598798247b7b1fba8e31b0"
)
ZERO_DOMAIN_ROOT_L3_IMPLEMENTATION_DIGEST = (
    "sha256:6460528b314ab9e89e43157d34fb4b36d04b8b9d698822b709293ba1a4c9193a"
)
GUIDED_CONVERGENCE_L3_IMPLEMENTATION_DIGEST = (
    "sha256:6592f2ef66a989e0cb5a0ff1b01f543ec7c946374f10fa72c9d5a5b8e899af21"
)


def compatible_installed_l3_digest(
    expected_digests: Collection[str],
    installed_digest: str,
) -> str:
    """Alias exact reviewed upgrades; fail closed for every other digest pair."""
    expected = frozenset(
        digest_value(value, "expected L3 implementation digest")
        for value in expected_digests
    )
    installed = digest_value(installed_digest, "installed L3 implementation digest")
    if (
        expected == frozenset((LEGACY_L3_IMPLEMENTATION_DIGEST,))
        and installed in {
            ZERO_DOMAIN_ROOT_L3_IMPLEMENTATION_DIGEST,
            GUIDED_CONVERGENCE_L3_IMPLEMENTATION_DIGEST,
        }
    ):
        return LEGACY_L3_IMPLEMENTATION_DIGEST
    return installed


__all__ = (
    "LEGACY_L3_IMPLEMENTATION_DIGEST",
    "GUIDED_CONVERGENCE_L3_IMPLEMENTATION_DIGEST",
    "ZERO_DOMAIN_ROOT_L3_IMPLEMENTATION_DIGEST",
    "compatible_installed_l3_digest",
)
