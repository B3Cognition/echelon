from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path, PurePath

import pytest

from harness.controller_state_contracts import (
    CompiledControllerStateContract,
    ControllerStateContractViolation,
    load_controller_state_contracts,
)
from harness.phase_graph import PhaseNode
from harness.prepared_phase_result import PreparedPhaseResult, prepare_phase_result
from harness.squad_provider import SquadAgentResult


def _result(
    updates: dict[str, object],
    *,
    verdict: str = "DONE",
) -> SquadAgentResult:
    return SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": verdict,
            "state_updates": updates,
            "journal_entries": [{"kind": "note", "details": {"items": ["original"]}}],
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
        token_usage_details={"input": 1},
    )


def _node(contract: CompiledControllerStateContract) -> PhaseNode:
    return PhaseNode(
        id="controller-node",
        type="deterministic_lexicon",
        allowed_state_updates=[],
        controller_state_contract=contract,
    )


@pytest.fixture
def contract(tmp_path: Path) -> CompiledControllerStateContract:
    path = tmp_path / "contracts.yaml"
    path.write_text(
        """
schema_version: 1
contracts:
  sample:
    $schema: https://json-schema.org/draft/2020-12/schema
    type: object
    additionalProperties: false
    required: [verdict, state_updates]
    properties:
      verdict: {type: string}
      state_updates:
        type: object
        additionalProperties: false
        properties:
          tasks_lexicon_pass: {type: boolean}
          tasks_lexicon_report: {type: string}
          blocked_reason: {type: string}
          evidence:
            type: object
            additionalProperties: false
            required: [items]
            properties:
              items:
                type: array
                items: {type: string}
""".lstrip(),
        encoding="utf-8",
    )
    return load_controller_state_contracts(path)["sample"]


def test_prepare_merges_disjoint_provider_and_controller_updates(
    contract: CompiledControllerStateContract,
) -> None:
    node = PhaseNode(
        id="mixed",
        type="agent",
        allowed_state_updates=["status"],
        controller_state_contract=contract,
    )
    prepared = prepare_phase_result(
        node,
        _result({"status": "running"}),
        controller_updates={"tasks_lexicon_report": PurePath("report.json")},
    )

    assert prepared.state_updates == {
        "status": "running",
        "tasks_lexicon_report": "report.json",
    }
    assert prepared.provider_update_keys == frozenset({"status"})
    assert prepared.controller_update_keys == frozenset({"tasks_lexicon_report"})
    assert prepared.controller_contract_name == "sample"
    assert prepared.controller_contract_sha256 == contract.sha256
    assert prepared.normalized_paths == (
        "$.state_updates.tasks_lexicon_report",
    )


def test_prepare_rejects_configured_provider_controller_overlap(
    contract: CompiledControllerStateContract,
) -> None:
    node = PhaseNode(
        id="mixed",
        type="agent",
        allowed_state_updates=["tasks_lexicon_pass"],
        controller_state_contract=contract,
    )

    with pytest.raises(ControllerStateContractViolation, match="overlap") as raised:
        prepare_phase_result(node, _result({}), controller_updates={})

    assert raised.value.contract == "sample"
    assert raised.value.validator == "ownership"


def test_mixed_node_rejects_raw_controller_key_impersonation(
    contract: CompiledControllerStateContract,
) -> None:
    node = PhaseNode(
        id="mixed",
        type="agent",
        allowed_state_updates=["status"],
        controller_state_contract=contract,
    )

    with pytest.raises(
        ControllerStateContractViolation,
        match="tasks_lexicon_pass",
    ):
        prepare_phase_result(
            node,
            _result({"tasks_lexicon_pass": True}),
            controller_updates={},
        )


def test_prepare_rejects_unknown_provider_key_deterministically(
    contract: CompiledControllerStateContract,
) -> None:
    node = PhaseNode(
        id="mixed",
        type="agent",
        allowed_state_updates=["status"],
        controller_state_contract=contract,
    )

    with pytest.raises(ControllerStateContractViolation, match="'a_unknown'"):
        prepare_phase_result(
            node,
            _result({"z_unknown": 1, "a_unknown": 2}),
            controller_updates={},
        )


def test_prepare_rejects_unknown_controller_key_deterministically(
    contract: CompiledControllerStateContract,
) -> None:
    with pytest.raises(ControllerStateContractViolation, match="'a_unknown'"):
        prepare_phase_result(
            _node(contract),
            _result({}),
            controller_updates={"z_unknown": 1, "a_unknown": 2},
        )


@pytest.mark.parametrize("allowed", [None, ["status"]])
def test_controller_owned_result_requires_explicitly_empty_provider_allowlist(
    contract: CompiledControllerStateContract,
    allowed: list[str] | None,
) -> None:
    node = PhaseNode(
        id="controller",
        type="deterministic_lexicon",
        allowed_state_updates=allowed,
        controller_state_contract=contract,
    )

    with pytest.raises(
        ControllerStateContractViolation,
        match="explicitly empty",
    ):
        prepare_phase_result(
            node,
            _result({"tasks_lexicon_pass": True}),
            controller_updates={},
            controller_owns_result_updates=True,
        )


def test_controller_owned_raw_updates_join_and_normalize_controller_bundle(
    contract: CompiledControllerStateContract,
) -> None:
    prepared = prepare_phase_result(
        _node(contract),
        _result({"tasks_lexicon_report": PurePath("report.json")}),
        controller_updates={"tasks_lexicon_pass": True},
        controller_owns_result_updates=True,
    )

    assert prepared.state_updates == {
        "tasks_lexicon_report": "report.json",
        "tasks_lexicon_pass": True,
    }
    assert prepared.provider_update_keys == frozenset()
    assert prepared.controller_update_keys == frozenset(
        {"tasks_lexicon_report", "tasks_lexicon_pass"}
    )
    assert prepared.normalized_paths == (
        "$.state_updates.tasks_lexicon_report",
    )


def test_controller_owned_result_rejects_duplicate_enrichment_key(
    contract: CompiledControllerStateContract,
) -> None:
    with pytest.raises(ControllerStateContractViolation, match="duplicate.*evidence"):
        prepare_phase_result(
            _node(contract),
            _result({"evidence": {"items": ["raw"]}}),
            controller_updates={"evidence": {"items": ["enriched"]}},
            controller_owns_result_updates=True,
        )


def test_no_contract_preserves_unbounded_provider_behavior() -> None:
    node = PhaseNode(id="legacy", type="agent", allowed_state_updates=None)
    provider_path = PurePath("provider.json")

    prepared = prepare_phase_result(
        node,
        _result({"legacy": provider_path}),
        controller_updates={},
    )

    assert prepared.state_updates == {"legacy": provider_path}
    assert prepared.provider_update_keys == frozenset({"legacy"})
    assert prepared.controller_update_keys == frozenset()
    assert prepared.controller_contract_name is None
    assert prepared.controller_contract_sha256 is None
    assert prepared.normalized_paths == ()


def test_no_contract_rejects_controller_updates() -> None:
    node = PhaseNode(id="provider", type="agent", allowed_state_updates=["status"])

    with pytest.raises(
        ControllerStateContractViolation,
        match="no controller state contract",
    ):
        prepare_phase_result(
            node,
            _result({"status": "running"}),
            controller_updates={"controller_value": True},
        )


def test_blocked_result_is_prepared_and_controller_validated(
    contract: CompiledControllerStateContract,
) -> None:
    prepared = prepare_phase_result(
        _node(contract),
        _result({"blocked_reason": PurePath("evidence/failure.txt")}, verdict="BLOCKED"),
        controller_updates={},
        routing_override="terminal-blocked",
        controller_owns_result_updates=True,
    )

    assert prepared.verdict == "BLOCKED"
    assert prepared.state_updates == {"blocked_reason": "evidence/failure.txt"}
    assert prepared.routing_override == "terminal-blocked"
    assert prepared.normalized_paths == ("$.state_updates.blocked_reason",)


def test_blocked_result_does_not_bypass_mixed_node_ownership(
    contract: CompiledControllerStateContract,
) -> None:
    node = PhaseNode(
        id="mixed",
        type="agent",
        allowed_state_updates=["status"],
        controller_state_contract=contract,
    )

    with pytest.raises(ControllerStateContractViolation, match="blocked_reason"):
        prepare_phase_result(
            node,
            _result({"blocked_reason": "failed"}, verdict="BLOCKED"),
            controller_updates={},
        )


def test_controller_schema_error_raises_first_sorted_violation(
    contract: CompiledControllerStateContract,
) -> None:
    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            _node(contract),
            _result({}),
            controller_updates={
                "tasks_lexicon_report": 3,
                "tasks_lexicon_pass": "yes",
            },
        )

    assert raised.value.contract == "sample"
    assert raised.value.json_path == "$.state_updates.tasks_lexicon_pass"
    assert raised.value.validator == "type"
    assert "yes" not in str(raised.value)


def test_invalid_base_result_is_reported_as_contract_violation() -> None:
    node = PhaseNode(id="provider", type="agent", allowed_state_updates=[])
    result = _result({})
    assert result.echelon_result is not None
    result.echelon_result["verdict"] = "NOT_A_VERDICT"

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(node, result, controller_updates={})

    assert raised.value.contract == "provider"
    assert raised.value.validator == "echelon_result"


@pytest.mark.parametrize("routing_override", ["", "  ", 42])
def test_prepare_rejects_invalid_routing_override(
    routing_override: object,
) -> None:
    node = PhaseNode(id="provider", type="agent", allowed_state_updates=[])

    with pytest.raises(
        ControllerStateContractViolation,
        match="routing_override",
    ):
        prepare_phase_result(
            node,
            _result({}),
            controller_updates={},
            routing_override=routing_override,  # type: ignore[arg-type]
        )


def test_provider_values_are_not_controller_normalized(
    contract: CompiledControllerStateContract,
) -> None:
    node = PhaseNode(
        id="mixed",
        type="agent",
        allowed_state_updates=["provider_path"],
        controller_state_contract=contract,
    )
    provider_path = PurePath("provider.json")

    prepared = prepare_phase_result(
        node,
        _result({"provider_path": provider_path}),
        controller_updates={},
    )

    assert prepared.state_updates["provider_path"] == provider_path
    assert isinstance(prepared.state_updates["provider_path"], PurePath)
    assert prepared.normalized_paths == ()


def test_prepared_result_has_no_alias_to_raw_or_controller_payloads(
    contract: CompiledControllerStateContract,
) -> None:
    provider_items = ["provider"]
    controller_items = ["controller"]
    result = _result({"provider_data": {"items": provider_items}})
    controller = {"evidence": {"items": controller_items}}
    node = PhaseNode(
        id="mixed",
        type="agent",
        allowed_state_updates=["provider_data"],
        controller_state_contract=contract,
    )

    prepared = prepare_phase_result(node, result, controller)
    provider_items.append("mutated")
    controller_items.append("mutated")
    assert result.echelon_result is not None
    result.echelon_result["state_updates"]["provider_data"]["items"].append("raw")
    result.echelon_result["journal_entries"][0]["details"]["items"].append("raw")
    result.token_usage_details["input"] = 99

    assert prepared.state_updates == {
        "provider_data": {"items": ["provider"]},
        "evidence": {"items": ["controller"]},
    }
    assert prepared.echelon_result["journal_entries"][0]["details"]["items"] == [
        "original"
    ]
    assert prepared.as_squad_agent_result().token_usage_details == {"input": 1}


def test_prepared_result_accessors_return_deep_copies(
    contract: CompiledControllerStateContract,
) -> None:
    prepared = prepare_phase_result(
        _node(contract),
        _result({}),
        controller_updates={"evidence": {"items": ["sealed"]}},
    )

    updates = prepared.state_updates
    updates["evidence"]["items"].append("changed")
    payload = prepared.echelon_result
    payload["state_updates"]["evidence"]["items"].append("changed")
    result_copy = prepared.as_squad_agent_result()
    assert result_copy.echelon_result is not None
    result_copy.echelon_result["state_updates"]["evidence"]["items"].append("changed")

    assert prepared.state_updates == {"evidence": {"items": ["sealed"]}}


def test_prepared_result_metadata_is_frozen(
    contract: CompiledControllerStateContract,
) -> None:
    prepared = prepare_phase_result(
        _node(contract),
        _result({}),
        controller_updates={},
    )

    with pytest.raises(FrozenInstanceError):
        prepared.routing_override = "other"  # type: ignore[misc]
    assert isinstance(prepared, PreparedPhaseResult)
