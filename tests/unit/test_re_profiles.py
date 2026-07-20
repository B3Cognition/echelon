from __future__ import annotations

import pytest

from harness.re_profiles import builtin_re_profile, migrate_legacy_re_profile


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("name", "target", "tokens", "minutes", "repairs", "cycles", "audit", "semantic_rounds"),
    [
        ("fast", 30, 1_000_000, 60, 1, 1, "none", 0),
        ("balanced", 60, 5_000_000, 180, 3, 2, "all", 1),
        ("high", 180, 15_000_000, 720, 5, 5, "all", 5),
    ],
)
def test_builtin_profiles_have_exact_limits(
    name: str,
    target: int,
    tokens: int,
    minutes: int,
    repairs: int,
    cycles: int,
    audit: str,
    semantic_rounds: int,
) -> None:
    profile = builtin_re_profile(name)

    assert profile.performance_target_minutes == target
    assert profile.hard_token_limit == tokens
    assert profile.hard_active_minutes == minutes
    assert profile.max_domain_repairs == repairs
    assert profile.max_source_cycles == cycles
    assert profile.max_source_reanalysis == cycles
    assert profile.semantic_audit_mode == audit
    assert profile.max_semantic_repair_rounds == semantic_rounds


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown RE execution profile"):
        builtin_re_profile("unbounded")


def test_legacy_migration_preserves_convergence_without_inventing_limits() -> None:
    state = {
        "re_source_budgets": {
            "max_domain_repairs": 7,
            "max_source_cycles": 6,
            "max_source_reanalysis": 4,
        }
    }

    profile = migrate_legacy_re_profile(state)

    assert profile.name == "legacy"
    assert profile.hard_token_limit is None
    assert profile.hard_active_minutes is None
    assert profile.max_domain_repairs == 7
    assert profile.max_source_cycles == 6
    assert profile.max_source_reanalysis == 4
