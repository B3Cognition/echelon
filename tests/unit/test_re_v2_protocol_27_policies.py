from __future__ import annotations

from dataclasses import replace

import pytest

from tests.re_v2_protocol_27_fixtures import digest


def _catalog():
    from harness.re_v2.protocol_27.policies import (
        SynthesisImplementationAuthorityV1,
        build_synthesis_policy_catalog,
    )

    return build_synthesis_policy_catalog(
        SynthesisImplementationAuthorityV1(
            schema_version=1,
            producer_authority_hash=digest("producer"),
            executor_contract_hash=digest("executor"),
            verifier_authority_hash=digest("verifier"),
        )
    )


@pytest.mark.unit
def test_policy_catalog_registers_only_closed_synthesis_kinds() -> None:
    from harness.re_v2.protocol_27.policies import SYNTHESIS_GENERATED_KINDS

    catalog = _catalog()

    assert {item.artifact_kind for item in catalog.entries} == SYNTHESIS_GENERATED_KINDS
    assert all(
        (
            item.max_provider_attempts,
            item.max_generation_attempts,
            item.max_result_contract_retries,
            item.max_artifact_contract_retries,
        )
        == (2, 2, 1, 1)
        for item in catalog.entries
    )


@pytest.mark.unit
def test_policy_catalog_round_trips_canonically() -> None:
    from harness.re_v2.protocol_27.policies import SynthesisPolicyCatalogV1

    catalog = _catalog()

    assert SynthesisPolicyCatalogV1.from_json_dict(catalog.to_json_dict()) == catalog
    assert (
        SynthesisPolicyCatalogV1.from_json_dict(catalog.to_json_dict()).identity
        == catalog.identity
    )


@pytest.mark.unit
def test_policy_rejects_a_third_dispatch_or_semantic_repair_round() -> None:
    from harness.re_v2.protocol_27.policies import Protocol27PolicyError

    entry = _catalog().entries[0]

    with pytest.raises(Protocol27PolicyError, match="fixed bounded attempt"):
        replace(entry, max_provider_attempts=3)
    with pytest.raises(Protocol27PolicyError, match="semantic repair"):
        replace(entry, max_semantic_repair_rounds=1)


@pytest.mark.unit
def test_policy_rejects_wrong_scope_or_dependency_taxonomy() -> None:
    from harness.re_v2.protocol_27.policies import Protocol27PolicyError

    source = next(
        item for item in _catalog().entries if item.artifact_kind == "source-architecture"
    )

    with pytest.raises(Protocol27PolicyError, match="scope"):
        replace(source, scope_kind="workspace")
    with pytest.raises(Protocol27PolicyError, match="dependency"):
        replace(source, required_artifact_kinds=("workspace-overview",))
