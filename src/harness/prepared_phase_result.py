"""Immutable boundary for validated phase results.

Preparation is the sole place where provider-owned and controller-owned state
updates are combined.  The resulting payload is detached from all producer
objects and exposes copies only, so later routing and persistence stages can
consume one canonical value.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from os import PathLike, fspath
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


_ATTESTATION_KEY = secrets.token_bytes(32)


class PreparedPhaseResultAttestationError(ValueError):
    """Raised when a prepared result no longer matches its factory seal."""


@dataclass(frozen=True)
class _PreparationAttestation:
    phase_id: str
    facts_sha256: str
    signature: bytes


@dataclass(frozen=True)
class PreparedPhaseResult:
    """A sealed, canonical result safe for routing and state advancement."""

    _result: SquadAgentResult = field(repr=False)
    provider_update_keys: frozenset[str]
    controller_update_keys: frozenset[str]
    controller_contract_name: str | None
    controller_contract_sha256: str | None
    normalized_paths: tuple[str, ...]
    _controller_owns_result_updates: bool = field(repr=False)
    _attestation: _PreparationAttestation = field(repr=False)
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


def _attestable_value(
    value: Any,
    *,
    active: set[int] | None = None,
) -> object:
    """Return a deterministic, JSON-safe structural snapshot."""
    if active is None:
        active = set()
    if value is None:
        return ["none"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        return ["float", value.hex()]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, PathLike):
        return [
            "pathlike",
            f"{type(value).__module__}.{type(value).__qualname__}",
            _attestable_value(fspath(value), active=active),
        ]
    if isinstance(value, Enum):
        return [
            "enum",
            f"{type(value).__module__}.{type(value).__qualname__}",
            _attestable_value(value.value, active=active),
        ]

    identity = id(value)
    if identity in active:
        raise PreparedPhaseResultAttestationError(
            "cyclic value cannot be attested"
        )
    active.add(identity)
    try:
        if isinstance(value, Mapping):
            items = [
                (
                    _attestable_value(key, active=active),
                    _attestable_value(item, active=active),
                )
                for key, item in value.items()
            ]
            items.sort(
                key=lambda pair: json.dumps(
                    pair[0],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            )
            return ["mapping", items]
        if isinstance(value, list):
            return [
                "list",
                [_attestable_value(item, active=active) for item in value],
            ]
        if isinstance(value, tuple):
            return [
                "tuple",
                [_attestable_value(item, active=active) for item in value],
            ]
        if isinstance(value, (set, frozenset)):
            items = [
                _attestable_value(item, active=active)
                for item in value
            ]
            items.sort(
                key=lambda item: json.dumps(
                    item,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            )
            return [type(value).__name__, items]
        attributes = getattr(value, "__dict__", None)
        if isinstance(attributes, dict):
            return [
                "object",
                f"{type(value).__module__}.{type(value).__qualname__}",
                _attestable_value(attributes, active=active),
            ]
        return [
            "repr",
            f"{type(value).__module__}.{type(value).__qualname__}",
            repr(value),
        ]
    finally:
        active.remove(identity)


def _attestation_facts(
    *,
    phase_id: str,
    result: SquadAgentResult,
    provider_update_keys: object,
    controller_update_keys: object,
    controller_contract_name: object,
    controller_contract_sha256: object,
    normalized_paths: object,
    routing_override: object,
    controller_owns_result_updates: object,
) -> bytes:
    payload = result.echelon_result
    facts = {
        "phase_id": _attestable_value(phase_id),
        "canonical_payload": _attestable_value(payload),
        "verdict": _attestable_value(result.verdict),
        "state_updates": _attestable_value(result.state_updates),
        "provider_update_keys": _attestable_value(provider_update_keys),
        "controller_update_keys": _attestable_value(controller_update_keys),
        "controller_contract_name": _attestable_value(
            controller_contract_name
        ),
        "controller_contract_sha256": _attestable_value(
            controller_contract_sha256
        ),
        "normalized_paths": _attestable_value(normalized_paths),
        "routing_override": _attestable_value(routing_override),
        "controller_owns_result_updates": _attestable_value(
            controller_owns_result_updates
        ),
    }
    return json.dumps(
        facts,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _create_preparation_attestation(
    *,
    phase_id: str,
    result: SquadAgentResult,
    provider_update_keys: frozenset[str],
    controller_update_keys: frozenset[str],
    controller_contract_name: str | None,
    controller_contract_sha256: str | None,
    normalized_paths: tuple[str, ...],
    routing_override: str | None,
    controller_owns_result_updates: bool,
) -> _PreparationAttestation:
    facts = _attestation_facts(
        phase_id=phase_id,
        result=result,
        provider_update_keys=provider_update_keys,
        controller_update_keys=controller_update_keys,
        controller_contract_name=controller_contract_name,
        controller_contract_sha256=controller_contract_sha256,
        normalized_paths=normalized_paths,
        routing_override=routing_override,
        controller_owns_result_updates=controller_owns_result_updates,
    )
    facts_sha256 = hashlib.sha256(facts).hexdigest()
    return _PreparationAttestation(
        phase_id=phase_id,
        facts_sha256=facts_sha256,
        signature=hmac.digest(
            _ATTESTATION_KEY,
            facts_sha256.encode("ascii"),
            "sha256",
        ),
    )


def verify_prepared_phase_result_attestation(
    prepared: PreparedPhaseResult,
    *,
    from_phase: str,
    to_phase: str,
) -> dict[str, Any]:
    """Verify the factory seal and return one detached canonical payload."""
    if type(prepared) is not PreparedPhaseResult:
        raise PreparedPhaseResultAttestationError(
            "advance requires a factory-prepared phase result"
        )
    attestation = prepared._attestation
    if type(attestation) is not _PreparationAttestation:
        raise PreparedPhaseResultAttestationError(
            "prepared result attestation is missing"
        )
    facts = _attestation_facts(
        phase_id=attestation.phase_id,
        result=prepared._result,
        provider_update_keys=prepared.provider_update_keys,
        controller_update_keys=prepared.controller_update_keys,
        controller_contract_name=prepared.controller_contract_name,
        controller_contract_sha256=prepared.controller_contract_sha256,
        normalized_paths=prepared.normalized_paths,
        routing_override=prepared.routing_override,
        controller_owns_result_updates=(
            prepared._controller_owns_result_updates
        ),
    )
    facts_sha256 = hashlib.sha256(facts).hexdigest()
    expected_signature = hmac.digest(
        _ATTESTATION_KEY,
        facts_sha256.encode("ascii"),
        "sha256",
    )
    if (
        not hmac.compare_digest(attestation.facts_sha256, facts_sha256)
        or not hmac.compare_digest(
            attestation.signature,
            expected_signature,
        )
    ):
        raise PreparedPhaseResultAttestationError(
            "prepared result attestation mismatch"
        )
    if attestation.phase_id != from_phase:
        raise PreparedPhaseResultAttestationError(
            "prepared result phase does not match state advance"
        )
    if (
        prepared.routing_override is not None
        and prepared.routing_override != to_phase
    ):
        raise PreparedPhaseResultAttestationError(
            "prepared routing override does not match state advance"
        )
    payload = prepared._result.echelon_result
    if not isinstance(payload, dict):
        raise PreparedPhaseResultAttestationError(
            "attested echelon_result is not an object"
        )
    return deepcopy(payload)


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
    provider_update_keys = frozenset(provider_updates)
    controller_update_keys = frozenset(normalized_controller)
    controller_contract_name = (
        contract.name if contract is not None else None
    )
    controller_contract_sha256 = (
        contract.sha256 if contract is not None else None
    )
    try:
        attestation = _create_preparation_attestation(
            phase_id=node.id,
            result=sealed_result,
            provider_update_keys=provider_update_keys,
            controller_update_keys=controller_update_keys,
            controller_contract_name=controller_contract_name,
            controller_contract_sha256=controller_contract_sha256,
            normalized_paths=normalized_paths,
            routing_override=routing_override,
            controller_owns_result_updates=controller_owns_result_updates,
        )
    except PreparedPhaseResultAttestationError as exc:
        raise ControllerStateContractViolation(
            "prepared result attestation failed",
            contract=_contract_label(contract),
            json_path="$.echelon_result",
            validator="attestation",
        ) from exc
    return PreparedPhaseResult(
        _result=sealed_result,
        provider_update_keys=provider_update_keys,
        controller_update_keys=controller_update_keys,
        controller_contract_name=controller_contract_name,
        controller_contract_sha256=controller_contract_sha256,
        normalized_paths=normalized_paths,
        _controller_owns_result_updates=controller_owns_result_updates,
        _attestation=attestation,
        routing_override=routing_override,
    )
