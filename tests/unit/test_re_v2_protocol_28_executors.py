from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_28.executors import (
    L4ExecutorCatalogV1,
    Protocol28ExecutorError,
    build_l4_executor_catalog,
    canonical_exhaustive_response_schema_bytes,
)


@pytest.mark.unit
def test_executor_catalog_binds_both_independent_roles() -> None:
    catalog = build_l4_executor_catalog(
        inherited_executor_contract_hash=content_digest(b"shared-cli"),
        producer_agent_contract_hash=content_digest(b"producer"),
        verifier_agent_contract_hash=content_digest(b"verifier"),
    )

    assert tuple(item.role for item in catalog.entries) == ("producer", "verifier")
    assert catalog.entries[0].agent_contract_hash != catalog.entries[1].agent_contract_hash
    assert L4ExecutorCatalogV1.from_json_dict(catalog.to_json_dict()) == catalog


@pytest.mark.unit
def test_executor_catalog_rejects_same_role_contract() -> None:
    catalog = build_l4_executor_catalog(
        inherited_executor_contract_hash=content_digest(b"shared-cli"),
        producer_agent_contract_hash=content_digest(b"producer"),
        verifier_agent_contract_hash=content_digest(b"verifier"),
    )

    with pytest.raises(Protocol28ExecutorError, match="independent agent"):
        replace(
            catalog,
            entries=(
                catalog.entries[0],
                replace(
                    catalog.entries[1],
                    agent_contract_hash=catalog.entries[0].agent_contract_hash,
                ),
            ),
        )


@pytest.mark.unit
def test_response_schemas_are_role_specific_closed_authority() -> None:
    producer = canonical_exhaustive_response_schema_bytes("producer")
    verifier = canonical_exhaustive_response_schema_bytes("verifier")

    assert producer != verifier
    assert b'"additionalProperties":false' in producer
    assert b'"ExhaustiveEvidenceSliceV1"' in producer
    assert b'"ExhaustiveVerificationV1"' in verifier
