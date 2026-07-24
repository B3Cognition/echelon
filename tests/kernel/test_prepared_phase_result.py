from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace
from pathlib import Path, PurePath

import pytest

import harness.prepared_phase_result as prepared_phase_result_module
import harness.state_transaction_namespace as state_transaction_namespace
from harness.controller_state_contracts import (
    CompiledControllerStateContract,
    ControllerContractRegistryError,
    ControllerStateContractViolation,
    load_controller_state_contracts,
)
from harness.phase_graph import PhaseNode
from harness.prepared_phase_result import (
    PreparedPhaseResult,
    PreparedPhaseResultAttestationError,
    PreparedRoutingDecision,
    prepare_phase_result,
    prepare_routing_decision,
    verify_prepared_routing_decision_attestation,
)
from harness.squad_provider import SquadAgentResult
from harness.state_transaction_namespace import (
    PENDING_CONTROLLER_COMPLETION_KEY,
    PENDING_EXTERNAL_PUBLICATION_KEY,
    STORE_OWNED_TRANSACTION_KEYS,
    TRUSTED_ROUTING_EFFECT_KEYS,
    TRUSTED_ROUTING_REMOVAL_KEYS,
)


_RAW_ATTESTATION_SECRET = "raw-attestation-secret"
VALID_MARKER = {
    "schema_version": 1,
    "transaction_id": "a" * 32,
    "manifest_sha256": "b" * 64,
}
VALID_COMPLETION_MARKER = {
    "schema_version": 1,
    "completion_id": "a" * 32,
    "intent_sha256": "b" * 64,
    "publication_binding_sha256": "c" * 64,
    "receipts_sha256": "d" * 64,
    "origin": "routed",
    "step": "journal",
}


class _ExplodingPath:
    def __deepcopy__(self, _memo):
        return self

    def __fspath__(self):
        raise RuntimeError(_RAW_ATTESTATION_SECRET)


class _ExplodingMapping(Mapping):
    def __deepcopy__(self, _memo):
        return self

    def __getitem__(self, _key):
        raise KeyError

    def __iter__(self):
        raise RuntimeError(_RAW_ATTESTATION_SECRET)

    def __len__(self):
        return 1


class _ExplodingRepr:
    __slots__ = ()

    def __deepcopy__(self, _memo):
        return self

    def __repr__(self):
        raise RuntimeError(_RAW_ATTESTATION_SECRET)


class _ExplodingDeepcopy:
    def __deepcopy__(self, _memo):
        raise RuntimeError(_RAW_ATTESTATION_SECRET)


class _HostileString(str):
    def __deepcopy__(self, _memo):
        raise RuntimeError(_RAW_ATTESTATION_SECRET)

    def __repr__(self):
        raise RuntimeError(_RAW_ATTESTATION_SECRET)


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
        allowed_state_updates=["provider_note"],
        controller_state_contract=contract,
    )
    prepared = prepare_phase_result(
        node,
        _result({"provider_note": "running"}),
        controller_updates={"tasks_lexicon_report": PurePath("report.json")},
    )

    assert prepared.state_updates == {
        "provider_note": "running",
        "tasks_lexicon_report": "report.json",
    }
    assert prepared.provider_update_keys == frozenset({"provider_note"})
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


def test_store_owned_transaction_namespace_covers_every_identity_class() -> None:
    assert {
        "run_id",
        "phase",
        "state_revision",
        "last_dispatch",
        "completed_phases",
        "record_completion",
        "manual_phase_run",
        "manual_phase_runs",
        "conditional_skip",
        "iteration",
        "status",
        "blocked_reason",
        "controller_contract_error",
        "blocked_decision",
        "phase_dispatch_counts",
        "phase_dispatch_limit",
        "phase_dispatch_limit_phase",
        "phase_dispatch_limit_recovery",
        "product_input_mapping_repair",
        "product_input_mapping_repair_attempts",
        "convergence_detected",
        "convergence_forced",
        "interrupted_phase",
        "provider_limit_message",
        "blocked_context",
        "phase_a_readiness_blockers",
        "published_re_context",
        "why3_verdict",
        "assess2_verdict",
        "user_request",
    } <= STORE_OWNED_TRANSACTION_KEYS


@pytest.mark.parametrize(
    "reserved_key",
    sorted(STORE_OWNED_TRANSACTION_KEYS),
)
def test_provider_cannot_own_any_store_transaction_key(
    reserved_key: str,
) -> None:
    node = PhaseNode(
        id="provider",
        type="agent",
        allowed_state_updates=[reserved_key],
    )

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            node,
            _result({reserved_key: "forged"}),
            controller_updates={},
        )

    assert raised.value.validator == "ownership"
    assert raised.value.json_path == f"$.state_updates.{reserved_key}"


@pytest.mark.parametrize(
    "reserved_key",
    sorted(STORE_OWNED_TRANSACTION_KEYS),
)
def test_generic_removals_cannot_own_any_store_transaction_key(
    reserved_key: str,
) -> None:
    node = PhaseNode(
        id="provider",
        type="agent",
        allowed_state_updates=[],
    )

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            node,
            _result({}),
            controller_updates={},
            state_removals={reserved_key},
        )

    assert raised.value.validator == "state_effects"
    assert raised.value.json_path == "$.state_removals"


def test_controller_can_seal_explicit_trusted_transaction_removals() -> None:
    node = PhaseNode(
        id="controller",
        type="agent",
        allowed_state_updates=[],
    )

    prepared = prepare_phase_result(
        node,
        _result({}),
        controller_updates={},
        trusted_transaction_state_removals={
            "product_input_mapping_repair",
            "product_input_mapping_repair_attempts",
        },
    )

    assert prepared.trusted_transaction_state_removals == {
        "product_input_mapping_repair",
        "product_input_mapping_repair_attempts",
    }


def test_prepared_phase_cannot_seal_pending_publication_removal() -> None:
    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            PhaseNode(
                id="controller",
                type="agent",
                allowed_state_updates=[],
            ),
            _result({}),
            controller_updates={},
            trusted_transaction_state_removals={
                PENDING_EXTERNAL_PUBLICATION_KEY
            },
        )

    assert raised.value.validator == "state_effects"
    assert raised.value.json_path == "$.trusted_transaction_state_removals"


def test_prepared_phase_cannot_seal_pending_completion_removal() -> None:
    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            PhaseNode(
                id="controller",
                type="agent",
                allowed_state_updates=[],
            ),
            _result({}),
            controller_updates={},
            trusted_transaction_state_removals={
                PENDING_CONTROLLER_COMPLETION_KEY
            },
        )

    assert raised.value.validator == "state_effects"
    assert raised.value.json_path == "$.trusted_transaction_state_removals"


@pytest.mark.parametrize(
    "invalid_key",
    sorted(STORE_OWNED_TRANSACTION_KEYS - TRUSTED_ROUTING_EFFECT_KEYS)[:3]
    + ["provider_owned"],
)
def test_trusted_transaction_removals_reject_untrusted_keys(
    invalid_key: str,
) -> None:
    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            PhaseNode(
                id="controller",
                type="agent",
                allowed_state_updates=[],
            ),
            _result({}),
            controller_updates={},
            trusted_transaction_state_removals={invalid_key},
        )

    assert raised.value.json_path == "$.trusted_transaction_state_removals"


@pytest.mark.parametrize(
    "reserved_key",
    sorted(STORE_OWNED_TRANSACTION_KEYS),
)
def test_routing_queue_cannot_own_any_store_transaction_key(
    reserved_key: str,
) -> None:
    prepared = prepare_phase_result(
        PhaseNode(id="provider", type="agent", allowed_state_updates=[]),
        _result({}),
        controller_updates={},
    )

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_routing_decision(
            prepared,
            from_phase="provider",
            to_phase="next",
            expected_state_revision=1,
            expected_previous_dispatch_sha256="0" * 64,
            queued_state_updates={reserved_key: "forged"},
        )

    assert raised.value.validator == "ownership"
    assert (
        raised.value.json_path
        == f"$.queued_state_updates.{reserved_key}"
    )


@pytest.mark.parametrize(
    "invalid_marker",
    [
        None,
        [],
        {
            "schema_version": True,
            "transaction_id": "a" * 32,
            "manifest_sha256": "b" * 64,
        },
        {
            "schema_version": 1,
            "transaction_id": "A" * 32,
            "manifest_sha256": "b" * 64,
        },
        {
            "schema_version": 1,
            "transaction_id": "a" * 32,
            "manifest_sha256": "b" * 63,
        },
        {
            "schema_version": 1,
            "transaction_id": "a" * 32,
            "manifest_sha256": "b" * 64,
            "extra": False,
        },
    ],
)
def test_pending_publication_marker_rejects_non_exact_values(
    invalid_marker: object,
) -> None:
    with pytest.raises(ValueError):
        state_transaction_namespace.validate_pending_external_publication(
            invalid_marker
        )


def test_pending_publication_marker_rejects_dict_and_string_subclasses() -> None:
    class DictSubclass(dict):
        pass

    class StringSubclass(str):
        pass

    with pytest.raises(ValueError):
        state_transaction_namespace.validate_pending_external_publication(
            DictSubclass(VALID_MARKER)
        )
    with pytest.raises(ValueError):
        state_transaction_namespace.validate_pending_external_publication(
            {
                **VALID_MARKER,
                "transaction_id": StringSubclass("a" * 32),
            }
        )


def test_pending_publication_marker_returns_an_exact_detached_record() -> None:
    marker = dict(VALID_MARKER)

    validated = (
        state_transaction_namespace.validate_pending_external_publication(
            marker
        )
    )
    marker["transaction_id"] = "c" * 32

    assert validated == VALID_MARKER
    assert validated is not marker
    assert type(validated) is dict
    assert all(type(value) in {int, str} for value in validated.values())


def test_pending_publication_key_is_reserved_for_all_untrusted_owners() -> None:
    assert PENDING_EXTERNAL_PUBLICATION_KEY in STORE_OWNED_TRANSACTION_KEYS

    node = PhaseNode(
        id="provider",
        type="agent",
        allowed_state_updates=[PENDING_EXTERNAL_PUBLICATION_KEY],
    )
    with pytest.raises(ControllerStateContractViolation):
        prepare_phase_result(
            node,
            _result({PENDING_EXTERNAL_PUBLICATION_KEY: VALID_MARKER}),
            controller_updates={},
        )
    with pytest.raises(ControllerStateContractViolation):
        prepare_phase_result(
            PhaseNode(
                id="provider",
                type="agent",
                allowed_state_updates=[],
            ),
            _result({}),
            controller_updates={},
            state_removals={PENDING_EXTERNAL_PUBLICATION_KEY},
        )

    prepared = prepare_phase_result(
        PhaseNode(
            id="provider",
            type="agent",
            allowed_state_updates=[],
        ),
        _result({}),
        controller_updates={},
    )
    with pytest.raises(ControllerStateContractViolation):
        prepare_routing_decision(
            prepared,
            from_phase="provider",
            to_phase="next",
            expected_state_revision=1,
            expected_previous_dispatch_sha256="0" * 64,
            queued_state_updates={
                PENDING_EXTERNAL_PUBLICATION_KEY: VALID_MARKER
            },
        )


def test_pending_publication_marker_is_the_only_trusted_publication_effect() -> None:
    assert PENDING_EXTERNAL_PUBLICATION_KEY in TRUSTED_ROUTING_EFFECT_KEYS
    assert "external_publication_failure" in STORE_OWNED_TRANSACTION_KEYS
    assert "external_publication_failure" not in TRUSTED_ROUTING_EFFECT_KEYS

    prepared = prepare_phase_result(
        PhaseNode(
            id="provider",
            type="agent",
            allowed_state_updates=[],
        ),
        _result({}),
        controller_updates={},
    )
    decision = prepare_routing_decision(
        prepared,
        from_phase="provider",
        to_phase="next",
        expected_state_revision=1,
        expected_previous_dispatch_sha256="0" * 64,
        transaction_state_updates={
            PENDING_EXTERNAL_PUBLICATION_KEY: VALID_MARKER
        },
    )

    assert decision.transaction_state_updates == {
        PENDING_EXTERNAL_PUBLICATION_KEY: VALID_MARKER
    }


def test_pending_publication_marker_cannot_be_a_trusted_routing_removal() -> None:
    prepared = prepare_phase_result(
        PhaseNode(
            id="provider",
            type="agent",
            allowed_state_updates=[],
        ),
        _result({}),
        controller_updates={},
    )

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_routing_decision(
            prepared,
            from_phase="provider",
            to_phase="next",
            expected_state_revision=1,
            expected_previous_dispatch_sha256="0" * 64,
            transaction_state_removals={
                PENDING_EXTERNAL_PUBLICATION_KEY
            },
        )

    assert raised.value.validator == "ownership"
    assert raised.value.json_path == (
        "$.transaction_state_removals."
        f"{PENDING_EXTERNAL_PUBLICATION_KEY}"
    )


def test_pending_completion_marker_has_controller_only_routing_authority() -> None:
    assert PENDING_CONTROLLER_COMPLETION_KEY in STORE_OWNED_TRANSACTION_KEYS
    assert PENDING_CONTROLLER_COMPLETION_KEY in TRUSTED_ROUTING_EFFECT_KEYS
    assert PENDING_CONTROLLER_COMPLETION_KEY not in TRUSTED_ROUTING_REMOVAL_KEYS

    prepared = prepare_phase_result(
        PhaseNode(
            id="provider",
            type="agent",
            allowed_state_updates=[],
        ),
        _result({}),
        controller_updates={},
    )
    decision = prepare_routing_decision(
        prepared,
        from_phase="provider",
        to_phase="next",
        expected_state_revision=1,
        expected_previous_dispatch_sha256="0" * 64,
        dispatch_id=VALID_COMPLETION_MARKER["completion_id"],
        transaction_state_updates={
            PENDING_CONTROLLER_COMPLETION_KEY: VALID_COMPLETION_MARKER,
        },
    )

    assert decision.transaction_state_updates == {
        PENDING_CONTROLLER_COMPLETION_KEY: VALID_COMPLETION_MARKER,
    }


def test_controller_completion_receipt_keys_are_store_owned_only() -> None:
    keys = {
        "controller_completion_failure",
        "last_terminal_completion",
        "phase_a_active_source_sha256",
        "phase_a_published_postimage_sha256",
    }

    assert keys <= STORE_OWNED_TRANSACTION_KEYS
    assert keys.isdisjoint(TRUSTED_ROUTING_EFFECT_KEYS)


@pytest.mark.parametrize(
    "invalid_marker",
    [
        None,
        {
            **VALID_COMPLETION_MARKER,
            "completion_id": "unsafe",
        },
        {
            **VALID_COMPLETION_MARKER,
            "extra": None,
        },
    ],
)
def test_routing_decision_rejects_malformed_pending_completion_marker(
    invalid_marker: object,
) -> None:
    prepared = prepare_phase_result(
        PhaseNode(
            id="provider",
            type="agent",
            allowed_state_updates=[],
        ),
        _result({}),
        controller_updates={},
    )

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_routing_decision(
            prepared,
            from_phase="provider",
            to_phase="next",
            expected_state_revision=1,
            expected_previous_dispatch_sha256="0" * 64,
            transaction_state_updates={
                PENDING_CONTROLLER_COMPLETION_KEY: invalid_marker,
            },
        )

    assert raised.value.validator == "type"
    assert raised.value.json_path == (
        "$.transaction_state_updates."
        f"{PENDING_CONTROLLER_COMPLETION_KEY}"
    )


def test_provider_cannot_set_or_remove_pending_completion_marker() -> None:
    node = PhaseNode(
        id="provider",
        type="agent",
        allowed_state_updates=[PENDING_CONTROLLER_COMPLETION_KEY],
    )
    with pytest.raises(ControllerStateContractViolation):
        prepare_phase_result(
            node,
            _result(
                {
                    PENDING_CONTROLLER_COMPLETION_KEY: (
                        VALID_COMPLETION_MARKER
                    )
                }
            ),
            controller_updates={},
        )

    prepared = prepare_phase_result(
        PhaseNode(
            id="provider",
            type="agent",
            allowed_state_updates=[],
        ),
        _result({}),
        controller_updates={},
    )
    with pytest.raises(ControllerStateContractViolation):
        prepare_routing_decision(
            prepared,
            from_phase="provider",
            to_phase="next",
            expected_state_revision=1,
            expected_previous_dispatch_sha256="0" * 64,
            transaction_state_removals={
                PENDING_CONTROLLER_COMPLETION_KEY,
            },
        )


@pytest.mark.parametrize(
    "reserved_key",
    sorted(STORE_OWNED_TRANSACTION_KEYS),
)
def test_controller_cannot_own_any_store_transaction_key(
    contract: CompiledControllerStateContract,
    reserved_key: str,
) -> None:
    reserved_contract = replace(
        contract,
        state_update_keys=frozenset({reserved_key}),
    )

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            _node(reserved_contract),
            _result({}),
            controller_updates={reserved_key: "forged"},
        )

    assert raised.value.validator == "ownership"
    assert raised.value.json_path == f"$.state_updates.{reserved_key}"


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


def test_prepare_bounds_controller_depth_before_any_recursive_copy(
    contract: CompiledControllerStateContract,
) -> None:
    value: object = "leaf"
    for _ in range(1_200):
        value = {"nested": value}

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            _node(contract),
            _result({"evidence": value}),
            controller_updates={},
            controller_owns_result_updates=True,
        )

    assert raised.value.contract == "preparation"
    assert raised.value.validator == "detachment_limit"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_prepare_rejects_copy_protocol_before_invoking_it(
    contract: CompiledControllerStateContract,
) -> None:
    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            _node(contract),
            _result({"evidence": _ExplodingDeepcopy()}),
            controller_updates={},
            controller_owns_result_updates=True,
        )

    assert str(raised.value) == "untrusted result detachment failed"
    assert raised.value.contract == "preparation"
    assert raised.value.validator == "detachment"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert _RAW_ATTESTATION_SECRET not in repr(raised.value)


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

    assert node.result_contract().allowed_state_update_keys is None

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


def test_contract_runtime_rejects_null_provider_allowlist(
    contract: CompiledControllerStateContract,
) -> None:
    node = PhaseNode(
        id="provider",
        type="agent",
        allowed_state_updates=None,
        controller_state_contract=contract,
    )

    with pytest.raises(
        ControllerStateContractViolation,
        match="provider allowlist",
    ):
        prepare_phase_result(
            node,
            _result({"evidence": {"items": ["escape"]}}),
            controller_updates={},
        )


@pytest.mark.parametrize(
    "unsafe_allowlist",
    ([123], [""], ["tasks_lexicon_pass"]),
)
def test_contract_dispatch_rejects_unsafe_provider_allowlist(
    contract: CompiledControllerStateContract,
    unsafe_allowlist: list[object],
) -> None:
    node = _node(contract)

    with pytest.raises(ControllerContractRegistryError):
        node.result_contract(
            {"allowed_state_updates": unsafe_allowlist}
        )


def test_no_contract_rejects_controller_updates() -> None:
    node = PhaseNode(
        id="provider",
        type="agent",
        allowed_state_updates=["provider_value"],
    )

    with pytest.raises(
        ControllerStateContractViolation,
        match="no controller state contract",
    ):
        prepare_phase_result(
            node,
            _result({"provider_value": "running"}),
            controller_updates={"controller_value": True},
        )


def test_blocked_result_is_prepared_and_controller_validated(
    contract: CompiledControllerStateContract,
) -> None:
    prepared = prepare_phase_result(
        _node(contract),
        _result({}, verdict="BLOCKED"),
        controller_updates={},
        routing_override="terminal-blocked",
        controller_owns_result_updates=True,
        control_updates={
            "status": "blocked",
            "blocked_reason": "evidence/failure.txt",
        },
    )

    assert prepared.verdict == "BLOCKED"
    assert prepared.state_updates == {}
    assert prepared.control_updates == {
        "status": "blocked",
        "blocked_reason": "evidence/failure.txt",
    }
    assert prepared.routing_override == "terminal-blocked"
    assert prepared.normalized_paths == ()

def test_declared_provider_control_intents_are_promoted_not_provider_owned() -> None:
    node = PhaseNode(
        id="tracker",
        type="agent",
        allowed_state_updates=[
            "status",
            "blocked_reason",
            "escalation_question",
        ],
    )
    control_updates = {
        "status": "blocked",
        "blocked_reason": "user intent needs clarification",
    }
    prepared = prepare_phase_result(
        node,
        _result(
            {
                **control_updates,
                "escalation_question": "Which target should Echelon use?",
            },
            verdict="STOP_AND_ASK",
        ),
        controller_updates={},
        control_updates=control_updates,
    )

    assert prepared.provider_update_keys == frozenset(
        {"escalation_question"}
    )
    assert prepared.control_updates == control_updates
    assert prepared.state_updates == {
        "escalation_question": "Which target should Echelon use?"
    }
    assert prepared.as_squad_agent_result().state_updates == {
        **control_updates,
        "escalation_question": "Which target should Echelon use?",
    }


def test_matching_control_payload_cannot_promote_undeclared_done_status() -> None:
    node = PhaseNode(
        id="provider",
        type="agent",
        allowed_state_updates=[],
    )

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            node,
            _result({"status": "done"}, verdict="DONE"),
            controller_updates={},
            control_updates={"status": "done"},
        )

    assert raised.value.validator == "ownership"
    assert raised.value.json_path == "$.state_updates.status"


def test_blocked_result_does_not_bypass_controller_schema_validation(
    contract: CompiledControllerStateContract,
) -> None:
    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            _node(contract),
            _result(
                {
                    "tasks_lexicon_pass": "yes",
                },
                verdict="BLOCKED",
            ),
            controller_updates={},
            controller_owns_result_updates=True,
        )

    assert raised.value.contract == "sample"
    assert raised.value.json_path == "$.state_updates.tasks_lexicon_pass"
    assert raised.value.validator == "type"


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


def test_prepare_rejects_provider_cycle_before_recursive_copy() -> None:
    node = PhaseNode(
        id="provider",
        type="agent",
        allowed_state_updates=["cyclic"],
    )
    cyclic: list[object] = []
    cyclic.append(cyclic)

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            node,
            _result({"cyclic": cyclic}),
            controller_updates={},
        )

    assert raised.value.contract == "preparation"
    assert raised.value.validator == "cycle"


@pytest.mark.parametrize(
    "probe_factory",
    [_ExplodingPath, _ExplodingMapping, _ExplodingRepr],
    ids=["pathlike", "mapping-iteration", "repr"],
)
def test_prepare_rejects_protocol_objects_before_attestation(
    probe_factory,
) -> None:
    node = PhaseNode(id="provider", type="agent", allowed_state_updates=[])
    result = _result({})
    assert result.echelon_result is not None
    result.echelon_result["attestation_probe"] = probe_factory()

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(node, result, controller_updates={})

    assert str(raised.value) == "untrusted result detachment failed"
    assert raised.value.contract == "preparation"
    assert raised.value.json_path == "$.echelon_result.attestation_probe"
    assert raised.value.validator == "detachment"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    diagnostic = {
        "message": str(raised.value),
        "contract": raised.value.contract,
        "json_path": raised.value.json_path,
        "validator": raised.value.validator,
    }
    assert _RAW_ATTESTATION_SECRET not in repr(diagnostic)


@pytest.mark.parametrize(
    ("field_name", "hostile_value", "json_path"),
    [
        ("raw_output", _ExplodingDeepcopy(), "$.raw_output"),
        ("raw_output", _HostileString("secret"), "$.raw_output"),
        ("duration_ms", True, "$.duration_ms"),
        ("timed_out", 1, "$.timed_out"),
        ("exit_code", False, "$.exit_code"),
        ("provider_name", _HostileString("provider"), "$.provider_name"),
        (
            "echelon_result_repair_duration_ms",
            False,
            "$.echelon_result_repair_duration_ms",
        ),
    ],
    ids=[
        "raw-object",
        "raw-string-subclass",
        "duration-bool",
        "timed-out-integer",
        "exit-code-bool",
        "provider-name-subclass",
        "repair-duration-bool",
    ],
)
def test_prepare_rejects_hostile_non_payload_fields_before_routing(
    field_name: str,
    hostile_value: object,
    json_path: str,
) -> None:
    node = PhaseNode(id="provider", type="agent", allowed_state_updates=[])
    result = _result({})
    setattr(result, field_name, hostile_value)

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(node, result, controller_updates={})

    assert str(raised.value) == "untrusted result detachment failed"
    assert raised.value.contract == "preparation"
    assert raised.value.json_path == json_path
    assert raised.value.validator == "type"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert _RAW_ATTESTATION_SECRET not in str(raised.value)


def test_prepare_bounds_non_payload_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        prepared_phase_result_module,
        "_MAX_DETACHMENT_STRING_LENGTH",
        64,
    )
    result = _result({})
    result.raw_output = "x" * 65

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            PhaseNode(id="provider", type="agent", allowed_state_updates=[]),
            result,
            controller_updates={},
        )

    assert raised.value.json_path == "$.raw_output"
    assert raised.value.validator == "detachment_limit"


@pytest.mark.parametrize("cost", [float("nan"), float("inf")])
def test_prepare_rejects_nonfinite_cost(cost: float) -> None:
    result = _result({})
    result.cost_usd = cost

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            PhaseNode(id="provider", type="agent", allowed_state_updates=[]),
            result,
            controller_updates={},
        )

    assert raised.value.json_path == "$.cost_usd"
    assert raised.value.validator == "finite"


def test_prepare_bounds_payload_integers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        prepared_phase_result_module,
        "_MAX_DETACHMENT_INTEGER_ABS",
        10,
    )

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            PhaseNode(
                id="provider",
                type="agent",
                allowed_state_updates=["score"],
            ),
            _result({"score": 11}),
            controller_updates={},
        )

    assert raised.value.json_path == "$.echelon_result.state_updates.score"
    assert raised.value.validator == "detachment_limit"


def test_prepare_redacts_missing_exact_result_field() -> None:
    result = _result({})
    del result.raw_output

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            PhaseNode(id="provider", type="agent", allowed_state_updates=[]),
            result,
            controller_updates={},
        )

    assert str(raised.value) == "untrusted result detachment failed"
    assert raised.value.json_path == "$.raw_output"
    assert raised.value.validator == "type"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_attestation_boundary_preserves_typed_contract_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typed = ControllerStateContractViolation(
        "already redacted",
        contract="typed",
        json_path="$.typed",
        validator="typed",
    )

    def reject(**_kwargs):
        raise typed

    monkeypatch.setattr(
        prepared_phase_result_module,
        "_create_preparation_attestation",
        reject,
    )

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_phase_result(
            PhaseNode(id="provider", type="agent", allowed_state_updates=[]),
            _result({}),
            controller_updates={},
        )

    assert raised.value is typed


def test_attestation_boundary_does_not_catch_base_exception_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupt(**_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        prepared_phase_result_module,
        "_create_preparation_attestation",
        interrupt,
    )

    with pytest.raises(KeyboardInterrupt):
        prepare_phase_result(
            PhaseNode(id="provider", type="agent", allowed_state_updates=[]),
            _result({}),
            controller_updates={},
        )


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


def test_routing_decision_seals_transition_identity_and_judgment_updates() -> None:
    prepared = prepare_phase_result(
        PhaseNode(id="provider", type="agent", allowed_state_updates=[]),
        _result({}),
        controller_updates={},
    )
    queued = {"judgment_note": "sealed"}
    judgment = {
        "verdict": "DONE",
        "state_updates": {"iteration": 2},
    }

    decision = prepare_routing_decision(
        prepared,
        from_phase="provider",
        to_phase="next",
        expected_state_revision=7,
        expected_previous_dispatch_sha256="0" * 64,
        queued_state_updates=queued,
        judgment_payloads=[judgment],
        source="commander",
        transition_index=1,
        increment_iteration=True,
        token_usage_delta=17,
    )
    queued["judgment_note"] = "changed"
    judgment["state_updates"]["iteration"] = 99

    verified = verify_prepared_routing_decision_attestation(
        decision,
        from_phase="provider",
        to_phase="next",
    )
    assert isinstance(decision, PreparedRoutingDecision)
    assert decision.queued_state_updates == {"judgment_note": "sealed"}
    assert verified.queued_state_updates == {"judgment_note": "sealed"}
    assert decision.expected_state_revision == 7
    assert len(decision.judgment_payload_sha256) == 1
    assert decision.increment_iteration is True
    assert decision.token_usage_delta == 17


def test_routing_decision_attests_supplied_dispatch_id() -> None:
    prepared = prepare_phase_result(
        PhaseNode(id="provider", type="agent", allowed_state_updates=[]),
        _result({}),
        controller_updates={},
    )

    first = prepare_routing_decision(
        prepared,
        from_phase="provider",
        to_phase="next",
        expected_state_revision=7,
        expected_previous_dispatch_sha256="0" * 64,
        dispatch_id="1" * 32,
    )
    second = prepare_routing_decision(
        prepared,
        from_phase="provider",
        to_phase="next",
        expected_state_revision=7,
        expected_previous_dispatch_sha256="0" * 64,
        dispatch_id="2" * 32,
    )

    assert first.dispatch_id == "1" * 32
    assert second.dispatch_id == "2" * 32
    assert first.routing_sha256 != second.routing_sha256
    verified = verify_prepared_routing_decision_attestation(
        first,
        from_phase="provider",
        to_phase="next",
    )
    assert verified.transaction_state_updates == {}


def test_routing_decision_dispatch_id_tampering_breaks_attestation() -> None:
    prepared = prepare_phase_result(
        PhaseNode(id="provider", type="agent", allowed_state_updates=[]),
        _result({}),
        controller_updates={},
    )
    decision = prepare_routing_decision(
        prepared,
        from_phase="provider",
        to_phase="next",
        expected_state_revision=1,
        expected_previous_dispatch_sha256="0" * 64,
        dispatch_id="1" * 32,
    )
    tampered = replace(decision, dispatch_id="2" * 32)

    with pytest.raises(PreparedPhaseResultAttestationError):
        verify_prepared_routing_decision_attestation(
            tampered,
            from_phase="provider",
            to_phase="next",
        )


@pytest.mark.parametrize(
    "dispatch_id",
    [
        None,
        "1" * 31,
        "A" * 32,
        "g" * 32,
        True,
    ],
)
def test_routing_decision_rejects_invalid_explicit_dispatch_id(
    dispatch_id: object,
) -> None:
    prepared = prepare_phase_result(
        PhaseNode(id="provider", type="agent", allowed_state_updates=[]),
        _result({}),
        controller_updates={},
    )

    if dispatch_id is None:
        decision = prepare_routing_decision(
            prepared,
            from_phase="provider",
            to_phase="next",
            expected_state_revision=1,
            expected_previous_dispatch_sha256="0" * 64,
        )
        assert len(decision.dispatch_id) == 32
        assert set(decision.dispatch_id) <= set("0123456789abcdef")
        return

    with pytest.raises(PreparedPhaseResultAttestationError):
        prepare_routing_decision(
            prepared,
            from_phase="provider",
            to_phase="next",
            expected_state_revision=1,
            expected_previous_dispatch_sha256="0" * 64,
            dispatch_id=dispatch_id,
        )


def test_routing_decision_binds_completion_id_to_dispatch_id() -> None:
    prepared = prepare_phase_result(
        PhaseNode(id="provider", type="agent", allowed_state_updates=[]),
        _result({}),
        controller_updates={},
    )

    decision = prepare_routing_decision(
        prepared,
        from_phase="provider",
        to_phase="next",
        expected_state_revision=1,
        expected_previous_dispatch_sha256="0" * 64,
        dispatch_id=VALID_COMPLETION_MARKER["completion_id"],
        transaction_state_updates={
            PENDING_CONTROLLER_COMPLETION_KEY: (
                VALID_COMPLETION_MARKER
            )
        },
    )
    assert decision.dispatch_id == VALID_COMPLETION_MARKER["completion_id"]

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_routing_decision(
            prepared,
            from_phase="provider",
            to_phase="next",
            expected_state_revision=1,
            expected_previous_dispatch_sha256="0" * 64,
            dispatch_id="2" * 32,
            transaction_state_updates={
                PENDING_CONTROLLER_COMPLETION_KEY: (
                    VALID_COMPLETION_MARKER
                )
            },
        )
    assert raised.value.validator == "completion_binding"


def test_routing_decision_tampering_breaks_attestation() -> None:
    prepared = prepare_phase_result(
        PhaseNode(id="provider", type="agent", allowed_state_updates=[]),
        _result({}),
        controller_updates={},
    )
    decision = prepare_routing_decision(
        prepared,
        from_phase="provider",
        to_phase="next",
        expected_state_revision=1,
        expected_previous_dispatch_sha256="0" * 64,
    )

    object.__setattr__(decision, "to_phase", "forged")

    with pytest.raises(
        PreparedPhaseResultAttestationError,
        match="routing decision attestation mismatch",
    ):
        verify_prepared_routing_decision_attestation(
            decision,
            from_phase="provider",
            to_phase="forged",
        )

def test_routing_token_usage_delta_tampering_breaks_attestation() -> None:
    prepared = prepare_phase_result(
        PhaseNode(id="provider", type="agent", allowed_state_updates=[]),
        _result({}),
        controller_updates={},
    )
    decision = prepare_routing_decision(
        prepared,
        from_phase="provider",
        to_phase="next",
        expected_state_revision=1,
        expected_previous_dispatch_sha256="0" * 64,
        token_usage_delta=11,
    )

    object.__setattr__(decision, "token_usage_delta", 12)

    with pytest.raises(
        PreparedPhaseResultAttestationError,
        match="routing decision attestation mismatch",
    ):
        verify_prepared_routing_decision_attestation(
            decision,
            from_phase="provider",
            to_phase="next",
        )


def test_routing_decision_rejects_untrusted_judgment_protocols() -> None:
    prepared = prepare_phase_result(
        PhaseNode(id="provider", type="agent", allowed_state_updates=[]),
        _result({}),
        controller_updates={},
    )

    with pytest.raises(ControllerStateContractViolation) as raised:
        prepare_routing_decision(
            prepared,
            from_phase="provider",
            to_phase="next",
            expected_state_revision=1,
            expected_previous_dispatch_sha256="0" * 64,
            judgment_payloads=[{"probe": _ExplodingDeepcopy()}],
        )

    assert raised.value.validator == "detachment"
    assert _RAW_ATTESTATION_SECRET not in str(raised.value)
