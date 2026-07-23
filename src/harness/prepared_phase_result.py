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
from dataclasses import dataclass, field, replace
from enum import Enum
from os import PathLike, fspath
from pathlib import PurePath
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
_MAX_DETACHMENT_DEPTH = 32
_MAX_DETACHMENT_NODES = 10_000
_MAX_DETACHMENT_COLLECTION = 10_000
_RESERVED_TRANSACTION_KEYS = frozenset(
    {
        "completed_phases",
        "created_at",
        "last_dispatch",
        "phase",
        "run_id",
        "state_revision",
        "updated_at",
    }
)


class PreparedPhaseResultAttestationError(ValueError):
    """Raised when a prepared result no longer matches its factory seal."""


def _detachment_violation(
    *,
    json_path: str = "$.echelon_result",
    validator: str = "detachment",
) -> ControllerStateContractViolation:
    return ControllerStateContractViolation(
        "untrusted result detachment failed",
        contract="preparation",
        json_path=json_path,
        validator=validator,
    )


def _bounded_detach_untrusted(
    value: Any,
    *,
    root_path: str,
) -> Any:
    """Detach JSON-shaped provider data without invoking copy protocols."""
    active: set[int] = set()
    visited = 0

    def visit(item: Any, path: str, depth: int) -> Any:
        nonlocal visited
        visited += 1
        if depth > _MAX_DETACHMENT_DEPTH or visited > _MAX_DETACHMENT_NODES:
            raise _detachment_violation(
                json_path=path,
                validator="detachment_limit",
            )
        if item is None or type(item) in (str, bool, int, float):
            return item
        if isinstance(item, (PurePath, Enum)):
            # These values are immutable. Provider-owned values retain their
            # existing representation; controller-owned values are normalized
            # separately before they reach this walker.
            return item
        if type(item) not in (dict, list, tuple):
            raise _detachment_violation(json_path=path)
        if len(item) > _MAX_DETACHMENT_COLLECTION:
            raise _detachment_violation(
                json_path=path,
                validator="detachment_limit",
            )
        identity = id(item)
        if identity in active:
            raise _detachment_violation(
                json_path=path,
                validator="cycle",
            )
        active.add(identity)
        try:
            if type(item) is dict:
                detached: dict[str, Any] = {}
                for key, child in dict.items(item):
                    if not isinstance(key, str):
                        raise _detachment_violation(
                            json_path=path,
                            validator="propertyNames",
                        )
                    detached[key] = visit(
                        child,
                        f"{path}.{key}",
                        depth + 1,
                    )
                return detached
            values = [
                visit(child, f"{path}[{index}]", depth + 1)
                for index, child in enumerate(item)
            ]
            return values if type(item) is list else tuple(values)
        finally:
            active.remove(identity)

    protocol_failure: ControllerStateContractViolation | None = None
    try:
        return visit(value, root_path, 0)
    except ControllerStateContractViolation:
        raise
    except Exception:
        protocol_failure = _detachment_violation()
    if protocol_failure is not None:
        raise protocol_failure
    raise AssertionError("unreachable")


def detach_squad_agent_result(result: SquadAgentResult) -> SquadAgentResult:
    """Return a bounded, protocol-free copy of one provider result."""
    if type(result) is not SquadAgentResult:
        raise _detachment_violation()
    payload = _bounded_detach_untrusted(
        result.echelon_result,
        root_path="$.echelon_result",
    )
    token_details = _bounded_detach_untrusted(
        result.token_usage_details,
        root_path="$.token_usage_details",
    )
    quarantined = _bounded_detach_untrusted(
        result.quarantined_state_updates,
        root_path="$.quarantined_state_updates",
    )
    return replace(
        result,
        echelon_result=payload,
        token_usage_details=token_details,
        quarantined_state_updates=quarantined,
    )


@dataclass(frozen=True)
class _PreparationAttestation:
    phase_id: str
    facts_sha256: str
    signature: bytes


@dataclass(frozen=True)
class _RoutingAttestation:
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
    state_removals: frozenset[str]
    _controller_owns_result_updates: bool = field(repr=False)
    _control_updates: dict[str, Any] = field(repr=False)
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

    @property
    def control_updates(self) -> dict[str, Any]:
        return deepcopy(self._control_updates)

    def as_squad_agent_result(self) -> SquadAgentResult:
        return deepcopy(self._result)

    @property
    def preparation_sha256(self) -> str:
        return self._attestation.facts_sha256


@dataclass(frozen=True)
class PreparedRoutingDecision:
    """A sealed state transition derived from one prepared phase result."""

    _prepared_result: PreparedPhaseResult = field(repr=False)
    from_phase: str
    to_phase: str
    expected_state_revision: int
    expected_previous_dispatch_sha256: str
    source: str
    transition_index: int | None
    increment_iteration: bool
    manual_phase_run: bool
    conditional_skip: bool
    record_completion: bool
    judgment_payload_sha256: tuple[str, ...]
    _queued_state_updates: dict[str, Any] = field(repr=False)
    _attestation: _RoutingAttestation = field(repr=False)

    @property
    def prepared_result(self) -> PreparedPhaseResult:
        return self._prepared_result

    @property
    def queued_state_updates(self) -> dict[str, Any]:
        return deepcopy(self._queued_state_updates)

    @property
    def routing_sha256(self) -> str:
        return self._attestation.facts_sha256


@dataclass(frozen=True)
class VerifiedRoutingDecision:
    """Detached values returned only after a routing seal is verified."""

    prepared_payload: dict[str, Any]
    queued_state_updates: dict[str, Any]


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
    state_removals: object,
    control_updates: object,
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
        "state_removals": _attestable_value(state_removals),
        "control_updates": _attestable_value(control_updates),
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
    state_removals: frozenset[str],
    control_updates: dict[str, Any],
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
        state_removals=state_removals,
        control_updates=control_updates,
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
        state_removals=prepared.state_removals,
        control_updates=prepared._control_updates,
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


def _valid_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _routing_attestation_facts(
    *,
    prepared: PreparedPhaseResult,
    from_phase: object,
    to_phase: object,
    expected_state_revision: object,
    expected_previous_dispatch_sha256: object,
    source: object,
    transition_index: object,
    increment_iteration: object,
    manual_phase_run: object,
    conditional_skip: object,
    record_completion: object,
    judgment_payload_sha256: object,
    queued_state_updates: object,
) -> bytes:
    preparation_attestation = prepared._attestation
    facts = {
        "prepared_phase_id": _attestable_value(
            preparation_attestation.phase_id
        ),
        "prepared_facts_sha256": _attestable_value(
            preparation_attestation.facts_sha256
        ),
        "prepared_signature": _attestable_value(
            preparation_attestation.signature
        ),
        "from_phase": _attestable_value(from_phase),
        "to_phase": _attestable_value(to_phase),
        "expected_state_revision": _attestable_value(
            expected_state_revision
        ),
        "expected_previous_dispatch_sha256": _attestable_value(
            expected_previous_dispatch_sha256
        ),
        "source": _attestable_value(source),
        "transition_index": _attestable_value(transition_index),
        "increment_iteration": _attestable_value(increment_iteration),
        "manual_phase_run": _attestable_value(manual_phase_run),
        "conditional_skip": _attestable_value(conditional_skip),
        "record_completion": _attestable_value(record_completion),
        "judgment_payload_sha256": _attestable_value(
            judgment_payload_sha256
        ),
        "queued_state_updates": _attestable_value(queued_state_updates),
    }
    return json.dumps(
        facts,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _create_routing_attestation(
    *,
    prepared: PreparedPhaseResult,
    from_phase: str,
    to_phase: str,
    expected_state_revision: int,
    expected_previous_dispatch_sha256: str,
    source: str,
    transition_index: int | None,
    increment_iteration: bool,
    manual_phase_run: bool,
    conditional_skip: bool,
    record_completion: bool,
    judgment_payload_sha256: tuple[str, ...],
    queued_state_updates: dict[str, Any],
) -> _RoutingAttestation:
    facts = _routing_attestation_facts(
        prepared=prepared,
        from_phase=from_phase,
        to_phase=to_phase,
        expected_state_revision=expected_state_revision,
        expected_previous_dispatch_sha256=(
            expected_previous_dispatch_sha256
        ),
        source=source,
        transition_index=transition_index,
        increment_iteration=increment_iteration,
        manual_phase_run=manual_phase_run,
        conditional_skip=conditional_skip,
        record_completion=record_completion,
        judgment_payload_sha256=judgment_payload_sha256,
        queued_state_updates=queued_state_updates,
    )
    facts_sha256 = hashlib.sha256(facts).hexdigest()
    return _RoutingAttestation(
        facts_sha256=facts_sha256,
        signature=hmac.digest(
            _ATTESTATION_KEY,
            facts_sha256.encode("ascii"),
            "sha256",
        ),
    )


def _canonical_payload_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        _attestable_value(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def prepare_routing_decision(
    prepared: PreparedPhaseResult,
    *,
    from_phase: str,
    to_phase: str,
    expected_state_revision: int,
    expected_previous_dispatch_sha256: str,
    queued_state_updates: Mapping[str, Any] | None = None,
    judgment_payloads: object = (),
    source: str = "transition",
    transition_index: int | None = None,
    increment_iteration: bool = False,
    manual_phase_run: bool = False,
    conditional_skip: bool = False,
    record_completion: bool = True,
) -> PreparedRoutingDecision:
    """Seal routing identity and approved state effects for one CAS commit."""
    if (
        type(from_phase) is not str
        or not from_phase.strip()
        or type(to_phase) is not str
        or not to_phase.strip()
    ):
        raise PreparedPhaseResultAttestationError(
            "routing decision phases must be non-empty strings"
        )
    verify_prepared_phase_result_attestation(
        prepared,
        from_phase=from_phase,
        to_phase=to_phase,
    )
    if (
        type(expected_state_revision) is not int
        or expected_state_revision < 0
    ):
        raise PreparedPhaseResultAttestationError(
            "routing decision state revision is invalid"
        )
    if not _valid_sha256(expected_previous_dispatch_sha256):
        raise PreparedPhaseResultAttestationError(
            "routing decision previous dispatch digest is invalid"
        )
    if type(source) is not str or not source.strip():
        raise PreparedPhaseResultAttestationError(
            "routing decision source is invalid"
        )
    if transition_index is not None and (
        type(transition_index) is not int or transition_index < 0
    ):
        raise PreparedPhaseResultAttestationError(
            "routing decision transition index is invalid"
        )
    if any(
        type(flag) is not bool
        for flag in (
            increment_iteration,
            manual_phase_run,
            conditional_skip,
            record_completion,
        )
    ):
        raise PreparedPhaseResultAttestationError(
            "routing decision flags must be Boolean"
        )

    if queued_state_updates is None:
        queued_state_updates = {}
    if type(queued_state_updates) is not dict:
        raise _detachment_violation(
            json_path="$.queued_state_updates",
        )
    detached_updates = _bounded_detach_untrusted(
        queued_state_updates,
        root_path="$.queued_state_updates",
    )
    invalid_keys = {
        key
        for key in detached_updates
        if key in _RESERVED_TRANSACTION_KEYS
    }
    if invalid_keys:
        raise ControllerStateContractViolation(
            "queued state updates contain a reserved key",
            contract="routing",
            json_path=(
                f"$.queued_state_updates.{sorted(invalid_keys)[0]}"
            ),
            validator="ownership",
        )
    overlap = (
        frozenset(detached_updates)
        & frozenset(prepared.state_updates)
    )
    if overlap:
        raise ControllerStateContractViolation(
            "queued and prepared state updates overlap",
            contract="routing",
            json_path=f"$.queued_state_updates.{sorted(overlap)[0]}",
            validator="ownership",
        )

    if type(judgment_payloads) not in (list, tuple):
        raise _detachment_violation(json_path="$.judgment_payloads")
    judgment_digests: list[str] = []
    for index, payload in enumerate(judgment_payloads):
        if type(payload) is not dict:
            raise _detachment_violation(
                json_path=f"$.judgment_payloads[{index}]"
            )
        detached_payload = _bounded_detach_untrusted(
            payload,
            root_path=f"$.judgment_payloads[{index}]",
        )
        judgment_digests.append(
            _canonical_payload_sha256(detached_payload)
        )
    sealed_digests = tuple(judgment_digests)
    attestation = _create_routing_attestation(
        prepared=prepared,
        from_phase=from_phase,
        to_phase=to_phase,
        expected_state_revision=expected_state_revision,
        expected_previous_dispatch_sha256=(
            expected_previous_dispatch_sha256
        ),
        source=source,
        transition_index=transition_index,
        increment_iteration=increment_iteration,
        manual_phase_run=manual_phase_run,
        conditional_skip=conditional_skip,
        record_completion=record_completion,
        judgment_payload_sha256=sealed_digests,
        queued_state_updates=detached_updates,
    )
    return PreparedRoutingDecision(
        _prepared_result=prepared,
        from_phase=from_phase,
        to_phase=to_phase,
        expected_state_revision=expected_state_revision,
        expected_previous_dispatch_sha256=(
            expected_previous_dispatch_sha256
        ),
        source=source,
        transition_index=transition_index,
        increment_iteration=increment_iteration,
        manual_phase_run=manual_phase_run,
        conditional_skip=conditional_skip,
        record_completion=record_completion,
        judgment_payload_sha256=sealed_digests,
        _queued_state_updates=detached_updates,
        _attestation=attestation,
    )


def verify_prepared_routing_decision_attestation(
    decision: PreparedRoutingDecision,
    *,
    from_phase: str,
    to_phase: str,
) -> VerifiedRoutingDecision:
    """Verify routing and nested preparation seals, returning detached data."""
    if type(decision) is not PreparedRoutingDecision:
        raise PreparedPhaseResultAttestationError(
            "advance requires a factory-prepared routing decision"
        )
    attestation = decision._attestation
    if type(attestation) is not _RoutingAttestation:
        raise PreparedPhaseResultAttestationError(
            "routing decision attestation is missing"
        )
    facts = _routing_attestation_facts(
        prepared=decision._prepared_result,
        from_phase=decision.from_phase,
        to_phase=decision.to_phase,
        expected_state_revision=decision.expected_state_revision,
        expected_previous_dispatch_sha256=(
            decision.expected_previous_dispatch_sha256
        ),
        source=decision.source,
        transition_index=decision.transition_index,
        increment_iteration=decision.increment_iteration,
        manual_phase_run=decision.manual_phase_run,
        conditional_skip=decision.conditional_skip,
        record_completion=decision.record_completion,
        judgment_payload_sha256=decision.judgment_payload_sha256,
        queued_state_updates=decision._queued_state_updates,
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
            "routing decision attestation mismatch"
        )
    if decision.from_phase != from_phase or decision.to_phase != to_phase:
        raise PreparedPhaseResultAttestationError(
            "routing decision identity does not match state advance"
        )
    prepared_payload = verify_prepared_phase_result_attestation(
        decision._prepared_result,
        from_phase=from_phase,
        to_phase=to_phase,
    )
    return VerifiedRoutingDecision(
        prepared_payload=prepared_payload,
        queued_state_updates=deepcopy(decision._queued_state_updates),
    )


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


def _prepare_state_effects(
    state_removals: object,
    control_updates: Mapping[str, Any] | None,
) -> tuple[frozenset[str], dict[str, Any]]:
    try:
        removals = frozenset(state_removals)  # type: ignore[arg-type]
    except Exception:
        failure = ControllerStateContractViolation(
            "state removals must be a collection of strings",
            contract="preparation",
            json_path="$.state_removals",
            validator="state_effects",
        )
        raise failure
    if any(
        not isinstance(key, str)
        or not key
        or key in _RESERVED_TRANSACTION_KEYS
        for key in removals
    ):
        raise ControllerStateContractViolation(
            "state removals contain an invalid key",
            contract="preparation",
            json_path="$.state_removals",
            validator="state_effects",
        )

    if control_updates is None:
        return removals, {}
    if not isinstance(control_updates, Mapping):
        raise ControllerStateContractViolation(
            "control updates must be a mapping",
            contract="preparation",
            json_path="$.control_updates",
            validator="state_effects",
        )
    normalized = normalize_controller_updates(control_updates).updates
    allowed = {
        "status",
        "blocked_reason",
        "lexicon_gate_exhausted",
    }
    if set(normalized) - allowed:
        raise ControllerStateContractViolation(
            "control updates contain an unsupported key",
            contract="preparation",
            json_path="$.control_updates",
            validator="state_effects",
        )
    if "status" in normalized and normalized["status"] != "blocked":
        raise ControllerStateContractViolation(
            "terminal control status must be blocked",
            contract="preparation",
            json_path="$.control_updates.status",
            validator="state_effects",
        )
    if "blocked_reason" in normalized and (
        not isinstance(normalized["blocked_reason"], str)
        or not normalized["blocked_reason"].strip()
    ):
        raise ControllerStateContractViolation(
            "terminal control blocked_reason must be non-empty",
            contract="preparation",
            json_path="$.control_updates.blocked_reason",
            validator="state_effects",
        )
    if "lexicon_gate_exhausted" in normalized and (
        normalized["lexicon_gate_exhausted"] is not True
    ):
        raise ControllerStateContractViolation(
            "lexicon exhaustion metadata must be true",
            contract="preparation",
            json_path="$.control_updates.lexicon_gate_exhausted",
            validator="state_effects",
        )
    return removals, normalized


def prepare_phase_result(
    node: PhaseNode,
    result: SquadAgentResult,
    controller_updates: Mapping[str, Any],
    routing_override: str | None = None,
    controller_owns_result_updates: bool = False,
    *,
    state_removals: object = (),
    control_updates: Mapping[str, Any] | None = None,
) -> PreparedPhaseResult:
    """Validate, normalize, merge, and seal one phase result.

    Provider values are checked against the existing phase result contract but
    are otherwise left unchanged.  Only the controller-owned bundle is passed
    through controller normalization.
    """

    contract = node.controller_state_contract

    if type(result) is not SquadAgentResult:
        raise _detachment_violation()
    raw_payload = result.echelon_result
    if type(raw_payload) is not dict:
        raise ControllerStateContractViolation(
            "provider echelon_result validation failed",
            contract="provider",
            json_path="$.echelon_result",
            validator="echelon_result",
        )
    raw_verdict = dict.get(raw_payload, "verdict")
    raw_updates_value = dict.get(raw_payload, "state_updates")
    if raw_updates_value is None and raw_verdict != "BLOCKED":
        raw_updates: dict[str, Any] = {}
    elif type(raw_updates_value) is dict:
        raw_updates = raw_updates_value
    else:
        raise ControllerStateContractViolation(
            "provider echelon_result validation failed",
            contract="provider",
            json_path="$.echelon_result",
            validator="echelon_result",
        )

    raw_keys = frozenset(dict.keys(raw_updates))
    allowed = node.allowed_state_updates
    provider_allowed = (
        None if allowed is None else frozenset(str(key) for key in allowed)
    )
    controller_allowed = (
        contract.state_update_keys if contract is not None else frozenset()
    )

    if not isinstance(controller_updates, Mapping):
        raise _ownership_violation(
            "controller_updates must be a mapping",
            contract,
        )
    normalized_enrichment = normalize_controller_updates(
        controller_updates
    )
    enrichment_keys = frozenset(normalized_enrichment.updates)

    if controller_owns_result_updates:
        normalized_raw_controller = normalize_controller_updates(raw_updates)
        normalized_controller = {
            **normalized_raw_controller.updates,
            **normalized_enrichment.updates,
        }
        normalized_paths = tuple(
            sorted(
                set(normalized_raw_controller.normalized_paths)
                | set(normalized_enrichment.normalized_paths)
            )
        )
        provider_updates_candidate: dict[str, Any] = {}
    else:
        normalized_controller = normalized_enrichment.updates
        normalized_paths = normalized_enrichment.normalized_paths
        provider_updates_candidate = raw_updates

    candidate_payload = {
        key: value
        for key, value in dict.items(raw_payload)
        if key != "state_updates"
    }
    candidate_payload["state_updates"] = provider_updates_candidate
    try:
        bounded_payload = _bounded_detach_untrusted(
            candidate_payload,
            root_path="$.echelon_result",
        )
        base_payload = validate_echelon_result(bounded_payload)
    except ControllerStateContractViolation:
        raise
    except EchelonResultValidationError:
        raise ControllerStateContractViolation(
            "provider echelon_result validation failed",
            contract="provider",
            json_path="$.echelon_result",
            validator="echelon_result",
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
        provider_updates = base_payload["state_updates"]

    if contract is None and normalized_controller:
        raise _ownership_violation(
            "controller updates require a controller state contract; "
            "this node has no controller state contract",
            contract,
        )

    unknown_controller = frozenset(normalized_controller) - controller_allowed
    if unknown_controller:
        key = sorted(unknown_controller)[0]
        raise _ownership_violation(
            f"controller update key {key!r} is not declared by the contract",
            contract,
            json_path=f"$.state_updates.{key}",
        )

    final_keys = frozenset(provider_updates) | frozenset(normalized_controller)
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
        normalized_controller = {}
        normalized_paths = ()
    else:
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
    sealed_result = detach_squad_agent_result(
        replace(result, echelon_result=canonical_payload)
    )
    sealed_removals, sealed_control_updates = _prepare_state_effects(
        state_removals,
        control_updates,
    )
    provider_update_keys = frozenset(provider_updates)
    controller_update_keys = frozenset(normalized_controller)
    controller_contract_name = (
        contract.name if contract is not None else None
    )
    controller_contract_sha256 = (
        contract.sha256 if contract is not None else None
    )
    attestation_failure: ControllerStateContractViolation | None = None
    try:
        attestation = _create_preparation_attestation(
            phase_id=node.id,
            result=sealed_result,
            provider_update_keys=provider_update_keys,
            controller_update_keys=controller_update_keys,
            controller_contract_name=controller_contract_name,
            controller_contract_sha256=controller_contract_sha256,
            normalized_paths=normalized_paths,
            state_removals=sealed_removals,
            control_updates=sealed_control_updates,
            routing_override=routing_override,
            controller_owns_result_updates=controller_owns_result_updates,
        )
    except ControllerStateContractViolation:
        raise
    except Exception:
        attestation_failure = ControllerStateContractViolation(
            "prepared result attestation failed",
            contract=_contract_label(contract),
            json_path="$.echelon_result",
            validator="attestation",
        )
    if attestation_failure is not None:
        raise attestation_failure
    return PreparedPhaseResult(
        _result=sealed_result,
        provider_update_keys=provider_update_keys,
        controller_update_keys=controller_update_keys,
        controller_contract_name=controller_contract_name,
        controller_contract_sha256=controller_contract_sha256,
        normalized_paths=normalized_paths,
        state_removals=sealed_removals,
        _controller_owns_result_updates=controller_owns_result_updates,
        _control_updates=sealed_control_updates,
        _attestation=attestation,
        routing_override=routing_override,
    )
