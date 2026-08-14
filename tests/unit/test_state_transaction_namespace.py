"""Transaction ownership for proportional quality repair state."""

from harness.state_transaction_namespace import store_owned_update_keys


def test_phase1_quality_repair_is_reserved_from_agent_state_updates() -> None:
    assert store_owned_update_keys({"phase1_quality_repair"}) == frozenset(
        {"phase1_quality_repair"}
    )


def test_quality_debt_authorization_is_reserved_from_agent_state_updates() -> None:
    assert store_owned_update_keys(
        {"spec_quality_debt_authorization"}
    ) == frozenset({"spec_quality_debt_authorization"})
