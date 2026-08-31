from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.protocol_28.policies import (
    DOMAIN_CATEGORIES,
    SOURCE_CATEGORIES,
    Protocol28PolicyError,
    build_initial_exhaustive_policy,
)


@pytest.mark.unit
def test_initial_exhaustive_policy_freezes_reviewed_bounds() -> None:
    """A silent bound change would alter work identity and worst-case spend."""
    policy = build_initial_exhaustive_policy()

    assert policy.raw_shard_byte_limit == 65_536
    assert policy.max_primary_subjects == 16
    assert policy.max_supporting_subjects == 32
    assert policy.max_primary_records == 64
    assert policy.max_supporting_records == 128
    assert policy.max_context_bytes == 131_072
    assert policy.max_conservative_tokens == 131_072
    assert policy.max_entries_per_target == 512
    assert policy.max_entries_per_run == 16_384
    assert policy.domain_categories == DOMAIN_CATEGORIES
    assert policy.source_categories == SOURCE_CATEGORIES


@pytest.mark.unit
def test_initial_policy_rejects_mutated_fixed_attempt_contract() -> None:
    """Resource authorization must not turn into an adaptive repair policy."""
    policy = build_initial_exhaustive_policy()

    with pytest.raises(Protocol28PolicyError, match="producer_attempt_limit"):
        replace(policy, producer_attempt_limit=4)


@pytest.mark.unit
def test_exhaustive_policy_closed_round_trip() -> None:
    policy = build_initial_exhaustive_policy()
    assert type(policy).from_json_dict(policy.to_json_dict()) == policy

    encoded = policy.to_json_dict()
    encoded["adaptive_repair"] = True
    with pytest.raises(Protocol28PolicyError, match="unknown fields"):
        type(policy).from_json_dict(encoded)
