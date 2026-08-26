from __future__ import annotations

from dataclasses import replace
import importlib

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.executors import (
    ExecutorContractCatalogV1,
    SHARED_AI_CLI_ADAPTER_ID,
)
from harness.re_v2.protocol_22.policies import policy_for
from harness.re_v2.protocol_24.policies import build_deepening_v1_policy_catalog
from tests.re_v2_protocol_22_fixtures import digest
from tests.unit.test_re_v2_protocol_22_executors import _shared_cli_entry


SEMANTIC_FAMILIES = (
    "closure-recheck",
    "semantic-audit",
    "semantic-resolution",
    "source-composition-guard",
)


def _policies():  # type: ignore[no-untyped-def]
    try:
        return importlib.import_module("harness.re_v2.protocol_25.policies")
    except ModuleNotFoundError:
        pytest.fail("protocol 2.5 semantic policy composition is not registered")


def _authorities():  # type: ignore[no-untyped-def]
    module = _policies()
    validator = digest("validator-agent")
    resolver = digest("resolver-agent")
    return tuple(
        module.SemanticExecutorAuthorityV1(
            schema_version=1,
            producer_family=family,
            agent_contract_hash=(resolver if family == "semantic-resolution" else validator),
            response_schema_kind=(
                "semantic-audit-findings"
                if family == "semantic-audit"
                else "semantic-resolution-overlay"
                if family == "semantic-resolution"
                else "semantic-closure-assessment"
            ),
            response_schema_hash=digest(f"{family}-schema"),
            verifier_id=f"{family}-verifier-v1",
            verifier_implementation_digest=digest(f"{family}-verifier"),
            result_contract_id=f"{family}-candidate-ready-v1",
        )
        for family in SEMANTIC_FAMILIES
    )


def _parent_executor_catalog() -> ExecutorContractCatalogV1:
    return ExecutorContractCatalogV1(1, (_shared_cli_entry(),))


def test_l3_policy_catalog_is_layered_over_exact_l2_catalog() -> None:
    module = _policies()
    catalog = module.build_semantic_v1_policy_catalog()

    assert catalog.inherited_catalog == build_deepening_v1_policy_catalog()
    assert tuple(entry.artifact_kind for entry in catalog.l3_entries) == (
        "audit-closure-root",
        "l3-source-root",
        "semantic-audit-findings",
        "semantic-resolution-overlay",
        "source-composition-assessment",
        "target-closure-assessment",
    )
    assert all(entry.layer == "L3" for entry in catalog.l3_entries)
    assert catalog.entry_for("L2", "domain-baseline") == (
        policy_for(build_deepening_v1_policy_catalog(), "L2", "domain-baseline")
    )


def test_audit_taxonomy_is_closed_and_exact() -> None:
    module = _policies()
    taxonomy = module.build_semantic_v1_policy_catalog().audit_taxonomy

    assert taxonomy.finding_classes == tuple(sorted(module.FINDING_CLASSES))
    assert taxonomy.assessment_kinds == ("source-composition", "target")
    assert taxonomy.rule_ids == (
        "behavior.incorrect",
        "behavior.missing",
        "claim.contradictory",
        "claim.unsupported",
        "decision.requires-human",
        "evidence.requires-deeper",
        "evidence.scope-gap",
        "source.cross-domain-inconsistency",
    )
    with pytest.raises(module.Protocol25SchemaError, match="taxonomy"):
        replace(taxonomy, assessment_kinds=("workspace",))


def test_l3_executor_catalog_reuses_shared_cli_authorities() -> None:
    module = _policies()
    inherited = _parent_executor_catalog()
    baseline = inherited.entry_for("compact-baseline")
    catalog = module.build_semantic_executor_catalog(inherited, _authorities())

    assert catalog.inherited_catalog == inherited
    for family in SEMANTIC_FAMILIES:
        entry = catalog.entry_for(family)
        assert entry.execution_mode == "cli"
        assert entry.adapter_id == SHARED_AI_CLI_ADAPTER_ID
        assert entry.provider_id == baseline.provider_id
        assert entry.executor_implementation_digest == baseline.executor_implementation_digest
        assert entry.reservation_calculator == baseline.reservation_calculator
        assert entry.token_accounting == baseline.token_accounting
        assert entry.limits == baseline.limits
        assert entry.model is None
        assert entry.api_transport is None
        assert entry.request_tokenizer is None
        assert entry.generation is None


@pytest.mark.parametrize("provider_id", ("claude", "codex", "copilot", "opencode"))
def test_semantic_executor_preserves_configured_shared_provider(provider_id: str) -> None:
    module = _policies()
    inherited = _parent_executor_catalog()
    baseline = inherited.entry_for("compact-baseline")
    inherited = ExecutorContractCatalogV1(
        1,
        (replace(baseline, provider_id=provider_id),),
    )

    catalog = module.build_semantic_executor_catalog(inherited, _authorities())

    assert {
        catalog.entry_for(family).provider_id for family in SEMANTIC_FAMILIES
    } == {provider_id}


def test_protocol_package_exports_semantic_policy_builders() -> None:
    protocol = importlib.import_module("harness.re_v2.protocol_25")
    module = _policies()

    assert protocol.build_semantic_v1_policy_catalog is module.build_semantic_v1_policy_catalog
    assert protocol.build_semantic_executor_catalog is module.build_semantic_executor_catalog


def test_semantic_executor_changes_only_pinned_role_schema_and_verifier() -> None:
    module = _policies()
    inherited = _parent_executor_catalog()
    baseline = inherited.entry_for("compact-baseline")
    catalog = module.build_semantic_executor_catalog(
        inherited,
        _authorities(),
    )

    for authority in _authorities():
        entry = catalog.entry_for(authority.producer_family)
        renderer = entry.request_renderer
        assert renderer is not None
        assert renderer.renderer_id == baseline.request_renderer.renderer_id
        assert renderer.renderer_version == baseline.request_renderer.renderer_version
        assert renderer.implementation_digest == baseline.request_renderer.implementation_digest
        assert renderer.agent_contract_hash == authority.agent_contract_hash
        assert tuple(
            (item.artifact_kind, item.schema_hash)
            for item in renderer.response_schemas
        ) == ((authority.response_schema_kind, authority.response_schema_hash),)
        assert entry.verifier.verifier_id == authority.verifier_id
        assert entry.verifier.implementation_digest == authority.verifier_implementation_digest
        assert entry.result_contract_id == authority.result_contract_id


def test_semantic_catalog_round_trips_canonically() -> None:
    module = _policies()
    inherited = _parent_executor_catalog()
    policies = module.build_semantic_v1_policy_catalog()
    executors = module.build_semantic_executor_catalog(
        inherited,
        _authorities(),
    )

    assert type(policies).from_json_dict(policies.to_json_dict()) == policies
    assert type(executors).from_json_dict(executors.to_json_dict()) == executors
    assert content_digest(policies.to_json_dict()) == policies.identity
    assert content_digest(executors.to_json_dict()) == executors.identity


def test_semantic_executor_rejects_missing_or_duplicate_family() -> None:
    module = _policies()
    inherited = _parent_executor_catalog()
    authorities = _authorities()

    with pytest.raises(module.Protocol25SchemaError, match="exactly"):
        module.build_semantic_executor_catalog(
            inherited,
            authorities[:-1],
        )
    with pytest.raises(module.Protocol25SchemaError, match="exactly"):
        module.build_semantic_executor_catalog(
            inherited,
            authorities[:-1] + (authorities[0],),
        )


def test_shared_authority_registry_maps_semantic_families_to_existing_roles() -> None:
    from harness.re_v2.protocol_22.authorities import _agent_contract_id

    assert _agent_contract_id("semantic-audit") == "echelon.re-validator"
    assert _agent_contract_id("semantic-resolution") == "echelon.re-resolver"
    assert _agent_contract_id("closure-recheck") == "echelon.re-validator"
    assert _agent_contract_id("source-composition-guard") == "echelon.re-validator"


def test_semantic_catalog_exposes_all_entries_to_shared_authority_validation() -> None:
    catalog = _policies().build_semantic_executor_catalog(
        _parent_executor_catalog(),
        _authorities(),
    )

    assert {entry.producer_family for entry in catalog.entries} == {
        "compact-baseline",
        *SEMANTIC_FAMILIES,
    }
