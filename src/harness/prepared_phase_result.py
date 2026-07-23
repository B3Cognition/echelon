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
import math
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from os import fspath
from pathlib import Path, PosixPath, PurePath, PurePosixPath, PureWindowsPath, WindowsPath
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
from harness.state_transaction_namespace import (
    PROVIDER_CONTROL_INTENT_KEYS,
    STORE_OWNED_TRANSACTION_KEYS,
    TRUSTED_ROUTING_EFFECT_KEYS,
    store_owned_update_keys,
)


_ATTESTATION_KEY = secrets.token_bytes(32)
_MAX_DETACHMENT_DEPTH = 32
_MAX_DETACHMENT_NODES = 10_000
_MAX_DETACHMENT_COLLECTION = 10_000
_MAX_DETACHMENT_STRING_LENGTH = 1_000_000
_MAX_DETACHMENT_INTEGER_ABS = (1 << 63) - 1
_SAFE_PATH_TYPES = frozenset(
    {
        Path,
        PurePath,
        PosixPath,
        WindowsPath,
        PurePosixPath,
        PureWindowsPath,
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
        if item is None or type(item) is bool:
            return item
        if type(item) is str:
            if len(item) > _MAX_DETACHMENT_STRING_LENGTH:
                raise _detachment_violation(
                    json_path=path,
                    validator="detachment_limit",
                )
            return item
        if type(item) is int:
            if abs(item) > _MAX_DETACHMENT_INTEGER_ABS:
                raise _detachment_violation(
                    json_path=path,
                    validator="detachment_limit",
                )
            return item
        if type(item) is float:
            if not math.isfinite(item):
                raise _detachment_violation(
                    json_path=path,
                    validator="finite",
                )
            return item
        if type(item) in _SAFE_PATH_TYPES:
            if len(fspath(item)) > _MAX_DETACHMENT_STRING_LENGTH:
                raise _detachment_violation(
                    json_path=path,
                    validator="detachment_limit",
                )
            return type(item)(*item.parts)
        if isinstance(item, Enum):
            enum_value = object.__getattribute__(item, "_value_")
            if type(enum_value) not in (str, bool, int, float):
                raise _detachment_violation(json_path=path)
            visit(enum_value, path, depth + 1)
            # Enum members with scalar values are immutable identities.
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
                    if (
                        type(key) is not str
                        or len(key) > _MAX_DETACHMENT_STRING_LENGTH
                    ):
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


@dataclass(frozen=True)
class _CanonicalSquadAgentResult:
    exit_code: int
    echelon_result: dict[str, Any] | None
    raw_output: str
    duration_ms: int
    timed_out: bool
    cost_usd: float
    token_usage: int
    token_usage_details: dict[str, int]
    provider_name: str
    model_name: str
    echelon_result_repair_attempted: bool
    echelon_result_repair_succeeded: bool
    echelon_result_repair_duration_ms: int | None
    echelon_result_repair_model_name: str
    echelon_result_repair_outcome: str
    echelon_result_repair_started_at: str
    echelon_result_repair_ended_at: str
    provider_limit_message: str
    quarantined_state_updates: dict[str, Any]
    stderr: str


def _type_violation(field_name: str) -> ControllerStateContractViolation:
    return _detachment_violation(
        json_path=f"$.{field_name}",
        validator="type",
    )


def _exact_field(
    result: SquadAgentResult,
    field_name: str,
    expected_type: type,
) -> Any:
    missing = False
    try:
        value = object.__getattribute__(result, field_name)
    except Exception:
        missing = True
        value = None
    if missing:
        raise _type_violation(field_name)
    if type(value) is not expected_type:
        raise _type_violation(field_name)
    if (
        expected_type is str
        and len(value) > _MAX_DETACHMENT_STRING_LENGTH
    ):
        raise _detachment_violation(
            json_path=f"$.{field_name}",
            validator="detachment_limit",
        )
    if (
        expected_type is int
        and abs(value) > _MAX_DETACHMENT_INTEGER_ABS
    ):
        raise _detachment_violation(
            json_path=f"$.{field_name}",
            validator="detachment_limit",
        )
    if expected_type is float and not math.isfinite(value):
        raise _detachment_violation(
            json_path=f"$.{field_name}",
            validator="finite",
        )
    return value


def _canonicalize_squad_agent_result(
    result: SquadAgentResult,
) -> _CanonicalSquadAgentResult:
    if type(result) is not SquadAgentResult:
        raise _detachment_violation()

    payload_missing = False
    try:
        raw_payload = object.__getattribute__(result, "echelon_result")
    except Exception:
        payload_missing = True
        raw_payload = None
    if payload_missing:
        raise _type_violation("echelon_result")
    if raw_payload is not None and type(raw_payload) is not dict:
        raise _type_violation("echelon_result")
    payload = _bounded_detach_untrusted(
        raw_payload,
        root_path="$.echelon_result",
    )
    if payload is not None and type(payload) is not dict:
        raise _type_violation("echelon_result")
    token_details = _bounded_detach_untrusted(
        _exact_field(result, "token_usage_details", dict),
        root_path="$.token_usage_details",
    )
    if type(token_details) is not dict or any(
        type(key) is not str
        or type(value) is not int
        or value < 0
        for key, value in dict.items(token_details)
    ):
        raise _type_violation("token_usage_details")
    quarantined = _bounded_detach_untrusted(
        _exact_field(result, "quarantined_state_updates", dict),
        root_path="$.quarantined_state_updates",
    )
    if type(quarantined) is not dict:
        raise _type_violation("quarantined_state_updates")

    exit_code = _exact_field(result, "exit_code", int)
    raw_output = _exact_field(result, "raw_output", str)
    duration_ms = _exact_field(result, "duration_ms", int)
    timed_out = _exact_field(result, "timed_out", bool)
    cost_usd = _exact_field(result, "cost_usd", float)
    token_usage = _exact_field(result, "token_usage", int)
    repair_duration_missing = False
    try:
        repair_duration = object.__getattribute__(
            result,
            "echelon_result_repair_duration_ms",
        )
    except Exception:
        repair_duration_missing = True
        repair_duration = None
    if repair_duration_missing:
        raise _type_violation("echelon_result_repair_duration_ms")
    if repair_duration is not None and type(repair_duration) is not int:
        raise _type_violation("echelon_result_repair_duration_ms")
    if (
        type(repair_duration) is int
        and abs(repair_duration) > _MAX_DETACHMENT_INTEGER_ABS
    ):
        raise _detachment_violation(
            json_path="$.echelon_result_repair_duration_ms",
            validator="detachment_limit",
        )
    if duration_ms < 0:
        raise _type_violation("duration_ms")
    if cost_usd < 0:
        raise _type_violation("cost_usd")
    if token_usage < 0:
        raise _type_violation("token_usage")
    if repair_duration is not None and repair_duration < 0:
        raise _type_violation("echelon_result_repair_duration_ms")

    return _CanonicalSquadAgentResult(
        exit_code=exit_code,
        echelon_result=payload,
        raw_output=raw_output,
        duration_ms=duration_ms,
        timed_out=timed_out,
        cost_usd=cost_usd,
        token_usage=token_usage,
        token_usage_details=token_details,
        provider_name=_exact_field(result, "provider_name", str),
        model_name=_exact_field(result, "model_name", str),
        echelon_result_repair_attempted=_exact_field(
            result,
            "echelon_result_repair_attempted",
            bool,
        ),
        echelon_result_repair_succeeded=_exact_field(
            result,
            "echelon_result_repair_succeeded",
            bool,
        ),
        echelon_result_repair_duration_ms=repair_duration,
        echelon_result_repair_model_name=_exact_field(
            result,
            "echelon_result_repair_model_name",
            str,
        ),
        echelon_result_repair_outcome=_exact_field(
            result,
            "echelon_result_repair_outcome",
            str,
        ),
        echelon_result_repair_started_at=_exact_field(
            result,
            "echelon_result_repair_started_at",
            str,
        ),
        echelon_result_repair_ended_at=_exact_field(
            result,
            "echelon_result_repair_ended_at",
            str,
        ),
        provider_limit_message=_exact_field(
            result,
            "provider_limit_message",
            str,
        ),
        quarantined_state_updates=quarantined,
        stderr=_exact_field(result, "stderr", str),
    )


def _clone_canonical(value: Any) -> Any:
    if value is None or type(value) in (str, bool, int, float, bytes):
        return value
    if type(value) in _SAFE_PATH_TYPES:
        return type(value)(*value.parts)
    if isinstance(value, Enum):
        return value
    if type(value) is dict:
        return {
            key: _clone_canonical(item)
            for key, item in dict.items(value)
        }
    if type(value) is list:
        return [_clone_canonical(item) for item in value]
    if type(value) is tuple:
        return tuple(_clone_canonical(item) for item in value)
    if type(value) is frozenset:
        return frozenset(_clone_canonical(item) for item in value)
    raise PreparedPhaseResultAttestationError(
        "canonical result contains an unsupported value"
    )


def _reconstruct_squad_agent_result(
    result: _CanonicalSquadAgentResult,
) -> SquadAgentResult:
    return SquadAgentResult(
        exit_code=result.exit_code,
        echelon_result=_clone_canonical(result.echelon_result),
        raw_output=result.raw_output,
        duration_ms=result.duration_ms,
        timed_out=result.timed_out,
        cost_usd=result.cost_usd,
        token_usage=result.token_usage,
        token_usage_details=_clone_canonical(result.token_usage_details),
        provider_name=result.provider_name,
        model_name=result.model_name,
        echelon_result_repair_attempted=(
            result.echelon_result_repair_attempted
        ),
        echelon_result_repair_succeeded=(
            result.echelon_result_repair_succeeded
        ),
        echelon_result_repair_duration_ms=(
            result.echelon_result_repair_duration_ms
        ),
        echelon_result_repair_model_name=(
            result.echelon_result_repair_model_name
        ),
        echelon_result_repair_outcome=result.echelon_result_repair_outcome,
        echelon_result_repair_started_at=(
            result.echelon_result_repair_started_at
        ),
        echelon_result_repair_ended_at=(
            result.echelon_result_repair_ended_at
        ),
        provider_limit_message=result.provider_limit_message,
        quarantined_state_updates=_clone_canonical(
            result.quarantined_state_updates
        ),
        stderr=result.stderr,
    )


def detach_squad_agent_result(result: SquadAgentResult) -> SquadAgentResult:
    """Return an exact-type, bounded, protocol-free provider result."""
    return _reconstruct_squad_agent_result(
        _canonicalize_squad_agent_result(result)
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

    _result: _CanonicalSquadAgentResult = field(repr=False)
    provider_update_keys: frozenset[str]
    controller_update_keys: frozenset[str]
    controller_contract_name: str | None
    controller_contract_sha256: str | None
    normalized_paths: tuple[str, ...]
    state_removals: frozenset[str]
    trusted_transaction_state_removals: frozenset[str]
    _controller_owns_result_updates: bool = field(repr=False)
    _control_updates: dict[str, Any] = field(repr=False)
    _attestation: _PreparationAttestation = field(repr=False)
    routing_override: str | None = None

    @property
    def echelon_result(self) -> dict[str, Any]:
        payload = self._result.echelon_result
        return _clone_canonical(payload) if type(payload) is dict else {}

    @property
    def verdict(self) -> str:
        payload = self._result.echelon_result
        if type(payload) is not dict:
            return ""
        verdict = dict.get(payload, "verdict")
        return verdict if type(verdict) is str else ""

    @property
    def state_updates(self) -> dict[str, Any]:
        payload = self._result.echelon_result
        if type(payload) is not dict:
            return {}
        updates = dict.get(payload, "state_updates")
        if type(updates) is not dict:
            return {}
        owned_keys = self.provider_update_keys | self.controller_update_keys
        return {
            key: _clone_canonical(value)
            for key, value in dict.items(updates)
            if key in owned_keys
        }

    @property
    def control_updates(self) -> dict[str, Any]:
        return _clone_canonical(self._control_updates)

    def as_squad_agent_result(self) -> SquadAgentResult:
        return _reconstruct_squad_agent_result(self._result)

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
    token_usage_delta: int
    judgment_payload_sha256: tuple[str, ...]
    _queued_state_updates: dict[str, Any] = field(repr=False)
    _transaction_state_updates: dict[str, Any] = field(repr=False)
    _transaction_state_removals: frozenset[str] = field(repr=False)
    _attestation: _RoutingAttestation = field(repr=False)

    @property
    def prepared_result(self) -> PreparedPhaseResult:
        return self._prepared_result

    @property
    def queued_state_updates(self) -> dict[str, Any]:
        return _clone_canonical(self._queued_state_updates)

    @property
    def transaction_state_updates(self) -> dict[str, Any]:
        return _clone_canonical(self._transaction_state_updates)

    @property
    def transaction_state_removals(self) -> frozenset[str]:
        return self._transaction_state_removals

    @property
    def routing_sha256(self) -> str:
        return self._attestation.facts_sha256


@dataclass(frozen=True)
class VerifiedRoutingDecision:
    """Detached values returned only after a routing seal is verified."""

    prepared_payload: dict[str, Any]
    queued_state_updates: dict[str, Any]
    transaction_state_updates: dict[str, Any]
    transaction_state_removals: frozenset[str]


def _attestable_value(
    value: Any,
    *,
    active: set[int] | None = None,
) -> object:
    """Return a deterministic snapshot of already-canonical values only."""
    if active is None:
        active = set()
    if value is None:
        return ["none"]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", str(value)]
    if type(value) is float:
        return ["float", value.hex()]
    if type(value) is str:
        return ["str", value]
    if type(value) is bytes:
        return ["bytes", value.hex()]
    if type(value) in _SAFE_PATH_TYPES:
        return [
            "pathlike",
            f"{type(value).__module__}.{type(value).__qualname__}",
            _attestable_value(fspath(value), active=active),
        ]
    if isinstance(value, Enum):
        enum_value = object.__getattribute__(value, "_value_")
        if type(enum_value) not in (str, bool, int, float):
            raise PreparedPhaseResultAttestationError(
                "canonical enum contains an unsupported value"
            )
        return [
            "enum",
            f"{type(value).__module__}.{type(value).__qualname__}",
            _attestable_value(enum_value, active=active),
        ]

    identity = id(value)
    if identity in active:
        raise PreparedPhaseResultAttestationError(
            "cyclic value cannot be attested"
        )
    active.add(identity)
    try:
        if type(value) is dict:
            items = [
                (
                    _attestable_value(key, active=active),
                    _attestable_value(item, active=active),
                )
                for key, item in dict.items(value)
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
        if type(value) is list:
            return [
                "list",
                [_attestable_value(item, active=active) for item in value],
            ]
        if type(value) is tuple:
            return [
                "tuple",
                [_attestable_value(item, active=active) for item in value],
            ]
        if type(value) is frozenset:
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
            return ["frozenset", items]
        raise PreparedPhaseResultAttestationError(
            "canonical result contains an unsupported value"
        )
    finally:
        active.remove(identity)


def _canonical_result_facts(
    result: _CanonicalSquadAgentResult,
) -> dict[str, object]:
    return {
        "exit_code": _attestable_value(result.exit_code),
        "echelon_result": _attestable_value(result.echelon_result),
        "raw_output": _attestable_value(result.raw_output),
        "duration_ms": _attestable_value(result.duration_ms),
        "timed_out": _attestable_value(result.timed_out),
        "cost_usd": _attestable_value(result.cost_usd),
        "token_usage": _attestable_value(result.token_usage),
        "token_usage_details": _attestable_value(
            result.token_usage_details
        ),
        "provider_name": _attestable_value(result.provider_name),
        "model_name": _attestable_value(result.model_name),
        "echelon_result_repair_attempted": _attestable_value(
            result.echelon_result_repair_attempted
        ),
        "echelon_result_repair_succeeded": _attestable_value(
            result.echelon_result_repair_succeeded
        ),
        "echelon_result_repair_duration_ms": _attestable_value(
            result.echelon_result_repair_duration_ms
        ),
        "echelon_result_repair_model_name": _attestable_value(
            result.echelon_result_repair_model_name
        ),
        "echelon_result_repair_outcome": _attestable_value(
            result.echelon_result_repair_outcome
        ),
        "echelon_result_repair_started_at": _attestable_value(
            result.echelon_result_repair_started_at
        ),
        "echelon_result_repair_ended_at": _attestable_value(
            result.echelon_result_repair_ended_at
        ),
        "provider_limit_message": _attestable_value(
            result.provider_limit_message
        ),
        "quarantined_state_updates": _attestable_value(
            result.quarantined_state_updates
        ),
        "stderr": _attestable_value(result.stderr),
    }


def _attestation_facts(
    *,
    phase_id: str,
    result: _CanonicalSquadAgentResult,
    provider_update_keys: object,
    controller_update_keys: object,
    controller_contract_name: object,
    controller_contract_sha256: object,
    normalized_paths: object,
    state_removals: object,
    trusted_transaction_state_removals: object,
    control_updates: object,
    routing_override: object,
    controller_owns_result_updates: object,
) -> bytes:
    facts = {
        "phase_id": _attestable_value(phase_id),
        "canonical_result": _canonical_result_facts(result),
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
        "trusted_transaction_state_removals": _attestable_value(
            trusted_transaction_state_removals
        ),
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
    result: _CanonicalSquadAgentResult,
    provider_update_keys: frozenset[str],
    controller_update_keys: frozenset[str],
    controller_contract_name: str | None,
    controller_contract_sha256: str | None,
    normalized_paths: tuple[str, ...],
    state_removals: frozenset[str],
    trusted_transaction_state_removals: frozenset[str],
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
        trusted_transaction_state_removals=(
            trusted_transaction_state_removals
        ),
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
        trusted_transaction_state_removals=(
            prepared.trusted_transaction_state_removals
        ),
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
    if type(payload) is not dict:
        raise PreparedPhaseResultAttestationError(
            "attested echelon_result is not an object"
        )
    return _clone_canonical(payload)


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
    token_usage_delta: object,
    judgment_payload_sha256: object,
    queued_state_updates: object,
    transaction_state_updates: object,
    transaction_state_removals: object,
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
        "token_usage_delta": _attestable_value(token_usage_delta),
        "judgment_payload_sha256": _attestable_value(
            judgment_payload_sha256
        ),
        "queued_state_updates": _attestable_value(queued_state_updates),
        "transaction_state_updates": _attestable_value(
            transaction_state_updates
        ),
        "transaction_state_removals": _attestable_value(
            transaction_state_removals
        ),
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
    token_usage_delta: int,
    judgment_payload_sha256: tuple[str, ...],
    queued_state_updates: dict[str, Any],
    transaction_state_updates: dict[str, Any],
    transaction_state_removals: frozenset[str],
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
        token_usage_delta=token_usage_delta,
        judgment_payload_sha256=judgment_payload_sha256,
        queued_state_updates=queued_state_updates,
        transaction_state_updates=transaction_state_updates,
        transaction_state_removals=transaction_state_removals,
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
    token_usage_delta: int = 0,
    transaction_state_updates: Mapping[str, Any] | None = None,
    transaction_state_removals: object = (),
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
    if type(token_usage_delta) is not int or token_usage_delta < 0:
        raise PreparedPhaseResultAttestationError(
            "routing decision token usage delta is invalid"
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
    invalid_keys = store_owned_update_keys(detached_updates)
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

    if transaction_state_updates is None:
        transaction_state_updates = {}
    if type(transaction_state_updates) is not dict:
        raise _detachment_violation(
            json_path="$.transaction_state_updates",
        )
    detached_transaction_updates = _bounded_detach_untrusted(
        transaction_state_updates,
        root_path="$.transaction_state_updates",
    )
    unsupported_transaction_updates = (
        frozenset(detached_transaction_updates)
        - TRUSTED_ROUTING_EFFECT_KEYS
    )
    if unsupported_transaction_updates:
        key = sorted(unsupported_transaction_updates)[0]
        raise ControllerStateContractViolation(
            "trusted transaction updates contain a non-transaction key",
            contract="routing",
            json_path=f"$.transaction_state_updates.{key}",
            validator="ownership",
        )
    try:
        detached_transaction_removals = frozenset(
            transaction_state_removals  # type: ignore[arg-type]
        )
    except Exception:
        raise _detachment_violation(
            json_path="$.transaction_state_removals",
        )
    if any(
        type(key) is not str
        for key in detached_transaction_removals
    ):
        raise _detachment_violation(
            json_path="$.transaction_state_removals",
        )
    unsupported_transaction_removals = (
        detached_transaction_removals
        - TRUSTED_ROUTING_EFFECT_KEYS
    )
    if unsupported_transaction_removals:
        key = sorted(unsupported_transaction_removals)[0]
        raise ControllerStateContractViolation(
            "trusted transaction removals contain a non-transaction key",
            contract="routing",
            json_path=f"$.transaction_state_removals.{key}",
            validator="ownership",
        )
    transaction_overlap = (
        frozenset(detached_transaction_updates)
        & detached_transaction_removals
    )
    if transaction_overlap:
        key = sorted(transaction_overlap)[0]
        raise ControllerStateContractViolation(
            "trusted transaction update and removal effects overlap",
            contract="routing",
            json_path=f"$.transaction_state_updates.{key}",
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
        token_usage_delta=token_usage_delta,
        judgment_payload_sha256=sealed_digests,
        queued_state_updates=detached_updates,
        transaction_state_updates=detached_transaction_updates,
        transaction_state_removals=detached_transaction_removals,
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
        token_usage_delta=token_usage_delta,
        judgment_payload_sha256=sealed_digests,
        _queued_state_updates=detached_updates,
        _transaction_state_updates=detached_transaction_updates,
        _transaction_state_removals=detached_transaction_removals,
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
        token_usage_delta=decision.token_usage_delta,
        judgment_payload_sha256=decision.judgment_payload_sha256,
        queued_state_updates=decision._queued_state_updates,
        transaction_state_updates=decision._transaction_state_updates,
        transaction_state_removals=decision._transaction_state_removals,
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
        queued_state_updates=_clone_canonical(
            decision._queued_state_updates
        ),
        transaction_state_updates=_clone_canonical(
            decision._transaction_state_updates
        ),
        transaction_state_removals=(
            decision._transaction_state_removals
        ),
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
    result = _clone_canonical(payload)
    result["state_updates"] = _clone_canonical(dict(provider_updates))
    return result


def _validate_provider_result(
    node: PhaseNode,
    payload: dict[str, Any],
    provider_updates: Mapping[str, Any],
    provider_control_intents: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        outcome = validate_echelon_result_contract(
            _provider_payload(
                payload,
                {
                    **provider_updates,
                    **provider_control_intents,
                },
            ),
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
    trusted_transaction_state_removals: object,
    control_updates: Mapping[str, Any] | None,
) -> tuple[frozenset[str], frozenset[str], dict[str, Any]]:
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
        or key in STORE_OWNED_TRANSACTION_KEYS
        for key in removals
    ):
        raise ControllerStateContractViolation(
            "state removals contain an invalid key",
            contract="preparation",
            json_path="$.state_removals",
            validator="state_effects",
        )

    try:
        transaction_removals = frozenset(
            trusted_transaction_state_removals  # type: ignore[arg-type]
        )
    except Exception:
        raise ControllerStateContractViolation(
            "trusted transaction state removals must be a collection of strings",
            contract="preparation",
            json_path="$.trusted_transaction_state_removals",
            validator="state_effects",
        )
    if any(
        type(key) is not str
        or not key
        or key not in STORE_OWNED_TRANSACTION_KEYS
        or key not in TRUSTED_ROUTING_EFFECT_KEYS
        for key in transaction_removals
    ):
        raise ControllerStateContractViolation(
            "trusted transaction state removals contain an invalid key",
            contract="preparation",
            json_path="$.trusted_transaction_state_removals",
            validator="state_effects",
        )

    if control_updates is None:
        return removals, transaction_removals, {}
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
    if "status" in normalized and normalized["status"] not in {
        "running",
        "blocked",
        "done",
        "interrupted",
        "killed",
    }:
        raise ControllerStateContractViolation(
            "control status is invalid",
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
    return removals, transaction_removals, normalized


def prepare_phase_result(
    node: PhaseNode,
    result: SquadAgentResult,
    controller_updates: Mapping[str, Any],
    routing_override: str | None = None,
    controller_owns_result_updates: bool = False,
    *,
    state_removals: object = (),
    trusted_transaction_state_removals: object = (),
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
    canonical_result = _canonicalize_squad_agent_result(result)
    result = _reconstruct_squad_agent_result(canonical_result)
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

    (
        sealed_removals,
        sealed_transaction_removals,
        sealed_control_updates,
    ) = _prepare_state_effects(
        state_removals,
        trusted_transaction_state_removals,
        control_updates,
    )
    allowed = node.allowed_state_updates
    provider_allowed = (
        None if allowed is None else frozenset(str(key) for key in allowed)
    )
    blocking_control_syntax = raw_verdict in {
        "BLOCKED",
        "STOP_AND_ASK",
    }
    raw_control_intents: dict[str, Any] = {}
    for key in sorted(store_owned_update_keys(dict.keys(raw_updates))):
        raw_value = dict.get(raw_updates, key)
        promoted_value = dict.get(sealed_control_updates, key)
        if (
            key in PROVIDER_CONTROL_INTENT_KEYS
            and (
                (
                    provider_allowed is not None
                    and key in provider_allowed
                )
                or blocking_control_syntax
            )
            and type(raw_value) is str
            and type(promoted_value) is str
            and raw_value == promoted_value
        ):
            raw_control_intents[key] = raw_value
            continue
        raise _ownership_violation(
            f"state update key {key!r} is owned by the transaction",
            contract,
            json_path=f"$.state_updates.{key}",
        )
    effective_raw_updates = {
        key: value
        for key, value in dict.items(raw_updates)
        if key not in raw_control_intents
    }
    raw_keys = frozenset(dict.keys(effective_raw_updates))
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
        normalized_raw_controller = normalize_controller_updates(
            effective_raw_updates
        )
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
        provider_updates_candidate = effective_raw_updates

    candidate_payload = {
        key: value
        for key, value in dict.items(raw_payload)
        if key != "state_updates"
    }
    candidate_payload["state_updates"] = {
        **provider_updates_candidate,
        **raw_control_intents,
    }
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
        provider_updates = {
            key: value
            for key, value in dict.items(base_payload["state_updates"])
            if key not in raw_control_intents
        }

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
    reserved_final = store_owned_update_keys(final_keys)
    if reserved_final:
        key = sorted(reserved_final)[0]
        raise _ownership_violation(
            f"state update key {key!r} is owned by the transaction",
            contract,
            json_path=f"$.state_updates.{key}",
        )
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
        raw_control_intents,
    )

    if contract is None:
        normalized_controller = {}
        normalized_paths = ()
    else:
        controller_errors = validate_controller_result(
            contract,
            str(provider_payload["verdict"]),
            {
                **normalized_controller,
                **{
                    key: value
                    for key, value in raw_control_intents.items()
                    if key in controller_allowed
                },
            },
        )
        if controller_errors:
            error = controller_errors[0]
            raise ControllerStateContractViolation(
                error.message,
                contract=error.contract,
                json_path=error.json_path,
                validator=error.validator,
            )

    canonical_payload = _clone_canonical(provider_payload)
    canonical_payload["state_updates"] = {
        **_clone_canonical(provider_updates),
        **_clone_canonical(normalized_controller),
        **_clone_canonical(raw_control_intents),
    }
    sealed_result = _canonicalize_squad_agent_result(
        replace(result, echelon_result=canonical_payload)
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
            trusted_transaction_state_removals=(
                sealed_transaction_removals
            ),
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
        trusted_transaction_state_removals=sealed_transaction_removals,
        _controller_owns_result_updates=controller_owns_result_updates,
        _control_updates=sealed_control_updates,
        _attestation=attestation,
        routing_override=routing_override,
    )
