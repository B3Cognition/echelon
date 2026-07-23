"""Immutable boundary for validated phase results.

Preparation is the sole place where provider-owned and controller-owned state
updates are combined.  The resulting payload is detached from all producer
objects and exposes copies only, so later routing and persistence stages can
consume one canonical value.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from harness.controller_state_contracts import (
    CompiledControllerStateContract,
    ControllerStateContractViolation,
    normalize_controller_updates,
    validate_controller_result,
)
from harness.echelon_result_schema import (
    EchelonResultValidationError,
    validate_echelon_result,
    validate_echelon_result_contract,
)
from harness.phase_graph import PhaseNode
from harness.squad_provider import SquadAgentResult


@dataclass(frozen=True)
class PreparedPhaseResult:
    """A sealed, canonical result safe for routing and state advancement."""

    _result: SquadAgentResult = field(repr=False)
    provider_update_keys: frozenset[str]
    controller_update_keys: frozenset[str]
    controller_contract_name: str | None
    controller_contract_sha256: str | None
    normalized_paths: tuple[str, ...]
    routing_override: str | None = None

    @property
    def echelon_result(self) -> dict[str, Any]:
        payload = self._result.echelon_result
        return deepcopy(payload) if isinstance(payload, dict) else {}

    @property
    def verdict(self) -> str:
        return str(self._result.verdict or "")

    @property
    def state_updates(self) -> dict[str, Any]:
        return deepcopy(self._result.state_updates)

    def as_squad_agent_result(self) -> SquadAgentResult:
        return deepcopy(self._result)


def _contract_label(
    contract: CompiledControllerStateContract | None,
) -> str:
    return contract.name if contract is not None else "preparation"


def _ownership_violation(
    message: str,
    contract: CompiledControllerStateContract | None,
    *,
    json_path: str = "$.state_updates",
) -> ControllerStateContractViolation:
    return ControllerStateContractViolation(
        message,
        contract=_contract_label(contract),
        json_path=json_path,
        validator="ownership",
    )


def _provider_payload(
    payload: dict[str, Any],
    provider_updates: Mapping[str, Any],
) -> dict[str, Any]:
    result = deepcopy(payload)
    result["state_updates"] = deepcopy(dict(provider_updates))
    return result


def _validate_provider_result(
    node: PhaseNode,
    payload: dict[str, Any],
    provider_updates: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        outcome = validate_echelon_result_contract(
            _provider_payload(payload, provider_updates),
            node.result_contract(),
        )
    except EchelonResultValidationError as exc:
        raise ControllerStateContractViolation(
            "provider echelon_result contract validation failed",
            contract="provider",
            json_path="$.echelon_result",
            validator="echelon_result",
        ) from exc
    return outcome.result


def prepare_phase_result(
    node: PhaseNode,
    result: SquadAgentResult,
    controller_updates: Mapping[str, Any],
    routing_override: str | None = None,
    controller_owns_result_updates: bool = False,
) -> PreparedPhaseResult:
    """Validate, normalize, merge, and seal one phase result.

    Provider values are checked against the existing phase result contract but
    are otherwise left unchanged.  Only the controller-owned bundle is passed
    through controller normalization.
    """

    contract = node.controller_state_contract

    try:
        detached_result = deepcopy(result)
        base_payload = validate_echelon_result(detached_result.echelon_result)
    except EchelonResultValidationError as exc:
        raise ControllerStateContractViolation(
            "provider echelon_result validation failed",
            contract="provider",
            json_path="$.echelon_result",
            validator="echelon_result",
        ) from exc

    raw_updates = base_payload["state_updates"]
    raw_keys = frozenset(raw_updates)
    allowed = node.allowed_state_updates
    provider_allowed = (
        None if allowed is None else frozenset(str(key) for key in allowed)
    )
    controller_allowed = (
        contract.state_update_keys if contract is not None else frozenset()
    )

    if provider_allowed is not None:
        overlap = provider_allowed & controller_allowed
        if overlap:
            key = sorted(overlap)[0]
            raise _ownership_violation(
                f"provider/controller ownership overlap for key {key!r}",
                contract,
                json_path=f"$.state_updates.{key}",
            )

    if not isinstance(controller_updates, Mapping):
        raise _ownership_violation(
            "controller_updates must be a mapping",
            contract,
        )

    detached_controller_updates = deepcopy(controller_updates)
    enrichment_keys = frozenset(detached_controller_updates)
    non_string_controller_keys = sorted(
        (key for key in enrichment_keys if not isinstance(key, str)),
        key=repr,
    )
    if non_string_controller_keys:
        key = non_string_controller_keys[0]
        raise _ownership_violation(
            f"controller update key {key!r} must be a string",
            contract,
        )

    if routing_override is not None and (
        not isinstance(routing_override, str) or not routing_override.strip()
    ):
        raise ControllerStateContractViolation(
            "routing_override must be a non-empty string or None",
            contract=_contract_label(contract),
            json_path="$.routing_override",
            validator="routing_override",
        )

    if controller_owns_result_updates:
        if allowed is None or provider_allowed:
            raise _ownership_violation(
                "controller-owned result updates require an explicitly empty "
                "provider allowlist",
                contract,
            )
        if contract is None:
            raise _ownership_violation(
                "controller-owned result updates require a controller state contract",
                contract,
            )
        duplicates = raw_keys & enrichment_keys
        if duplicates:
            key = sorted(duplicates)[0]
            raise _ownership_violation(
                f"duplicate controller update key {key!r}",
                contract,
                json_path=f"$.state_updates.{key}",
            )
        provider_updates: dict[str, Any] = {}
        controller_bundle = deepcopy(raw_updates)
        controller_bundle.update(detached_controller_updates)
    else:
        if contract is not None:
            effective_provider_allowed = provider_allowed or frozenset()
            unknown_provider = raw_keys - effective_provider_allowed
            if unknown_provider:
                key = sorted(unknown_provider)[0]
                raise _ownership_violation(
                    f"provider result update key {key!r} is not explicitly allowed",
                    contract,
                    json_path=f"$.state_updates.{key}",
                )
        elif provider_allowed is not None:
            unknown_provider = raw_keys - provider_allowed
            if unknown_provider:
                key = sorted(unknown_provider)[0]
                raise _ownership_violation(
                    f"provider result update key {key!r} is not allowed",
                    contract,
                    json_path=f"$.state_updates.{key}",
                )
        provider_updates = deepcopy(raw_updates)
        controller_bundle = detached_controller_updates

    if contract is None and controller_bundle:
        raise _ownership_violation(
            "controller updates require a controller state contract; "
            "this node has no controller state contract",
            contract,
        )

    unknown_controller = frozenset(controller_bundle) - controller_allowed
    if unknown_controller:
        key = sorted(unknown_controller)[0]
        raise _ownership_violation(
            f"controller update key {key!r} is not declared by the contract",
            contract,
            json_path=f"$.state_updates.{key}",
        )

    final_keys = frozenset(provider_updates) | frozenset(controller_bundle)
    if provider_allowed is not None:
        unknown_final = final_keys - (provider_allowed | controller_allowed)
        if unknown_final:
            key = sorted(unknown_final)[0]
            raise _ownership_violation(
                f"final result update key {key!r} has no declared owner",
                contract,
                json_path=f"$.state_updates.{key}",
            )

    provider_payload = _validate_provider_result(
        node,
        base_payload,
        provider_updates,
    )

    if contract is None:
        normalized_controller: dict[str, Any] = {}
        normalized_paths: tuple[str, ...] = ()
    else:
        normalization = normalize_controller_updates(controller_bundle)
        normalized_controller = normalization.updates
        normalized_paths = normalization.normalized_paths
        controller_errors = validate_controller_result(
            contract,
            str(provider_payload["verdict"]),
            normalized_controller,
        )
        if controller_errors:
            error = controller_errors[0]
            raise ControllerStateContractViolation(
                error.message,
                contract=error.contract,
                json_path=error.json_path,
                validator=error.validator,
            )

    canonical_payload = deepcopy(provider_payload)
    canonical_payload["state_updates"] = {
        **deepcopy(provider_updates),
        **deepcopy(normalized_controller),
    }
    detached_result.echelon_result = canonical_payload

    sealed_result = deepcopy(detached_result)
    return PreparedPhaseResult(
        _result=sealed_result,
        provider_update_keys=frozenset(provider_updates),
        controller_update_keys=frozenset(normalized_controller),
        controller_contract_name=contract.name if contract is not None else None,
        controller_contract_sha256=contract.sha256 if contract is not None else None,
        normalized_paths=normalized_paths,
        routing_override=routing_override,
    )
