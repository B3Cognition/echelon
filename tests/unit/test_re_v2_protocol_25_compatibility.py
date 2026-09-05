from __future__ import annotations

import pytest

from tests.re_v2_protocol_22_fixtures import digest


@pytest.mark.unit
def test_zero_domain_root_schema_upgrade_preserves_legacy_semantic_authority() -> None:
    """Catch a reviewed root-only change invalidating an in-flight L3 run."""
    from harness.re_v2.protocol_25.compatibility import (
        LEGACY_L3_IMPLEMENTATION_DIGEST,
        ZERO_DOMAIN_ROOT_L3_IMPLEMENTATION_DIGEST,
        compatible_installed_l3_digest,
    )

    assert compatible_installed_l3_digest(
        frozenset((LEGACY_L3_IMPLEMENTATION_DIGEST,)),
        ZERO_DOMAIN_ROOT_L3_IMPLEMENTATION_DIGEST,
    ) == LEGACY_L3_IMPLEMENTATION_DIGEST


@pytest.mark.unit
def test_l3_implementation_compatibility_fails_closed_for_unknown_changes() -> None:
    from harness.re_v2.protocol_25.compatibility import (
        LEGACY_L3_IMPLEMENTATION_DIGEST,
        ZERO_DOMAIN_ROOT_L3_IMPLEMENTATION_DIGEST,
        compatible_installed_l3_digest,
    )

    unknown = digest("unknown-l3-implementation")
    assert compatible_installed_l3_digest(
        frozenset((LEGACY_L3_IMPLEMENTATION_DIGEST,)),
        unknown,
    ) == unknown
    assert compatible_installed_l3_digest(
        frozenset((digest("unknown-frozen-authority"),)),
        ZERO_DOMAIN_ROOT_L3_IMPLEMENTATION_DIGEST,
    ) == ZERO_DOMAIN_ROOT_L3_IMPLEMENTATION_DIGEST
    assert compatible_installed_l3_digest(
        frozenset(
            (
                LEGACY_L3_IMPLEMENTATION_DIGEST,
                digest("conflicting-frozen-authority"),
            )
        ),
        ZERO_DOMAIN_ROOT_L3_IMPLEMENTATION_DIGEST,
    ) == ZERO_DOMAIN_ROOT_L3_IMPLEMENTATION_DIGEST
