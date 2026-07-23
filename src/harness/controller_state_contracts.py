from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from enum import Enum
from os import PathLike, fspath
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


class ControllerContractRegistryError(ValueError):
    pass


class ControllerStateContractViolation(ValueError):
    def __init__(
        self,
        message: str,
        *,
        contract: str,
        json_path: str = "$",
        validator: str = "contract",
    ) -> None:
        super().__init__(message)
        self.contract = contract
        self.json_path = json_path
        self.validator = validator


MAX_NORMALIZATION_DEPTH = 32
MAX_NORMALIZATION_NODES = 10_000
MAX_NORMALIZATION_COLLECTION = 10_000


@dataclass(frozen=True)
class NormalizationOutcome:
    updates: dict[str, Any]
    normalized_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class ControllerContractError:
    contract: str
    json_path: str
    validator: str
    message: str


@dataclass(frozen=True)
class CompiledControllerStateContract:
    name: str
    schema: Mapping[str, Any]
    state_update_keys: frozenset[str]
    validator: Draft202012Validator
    sha256: str


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ControllerContractRegistryError(f"duplicate key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _reject_external_refs(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key == "$ref" and (
                not isinstance(item, str) or not item.startswith("#/$defs/")
            ):
                raise ControllerContractRegistryError(
                    f"remote or non-local $ref is forbidden at {child}"
                )
            if key == "default":
                raise ControllerContractRegistryError(
                    f"schema defaults are forbidden at {child}"
                )
            _reject_external_refs(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_external_refs(item, f"{path}[{index}]")


def load_controller_state_contracts(
    path: Path,
) -> Mapping[str, CompiledControllerStateContract]:
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except ControllerContractRegistryError:
        raise
    except Exception as exc:
        raise ControllerContractRegistryError(
            f"cannot read controller contract registry: {exc}"
        ) from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ControllerContractRegistryError(
            "controller contract registry schema_version must be 1"
        )
    contracts = raw.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        raise ControllerContractRegistryError(
            "controller contract registry must contain contracts"
        )

    compiled = {}
    for name, schema in contracts.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(schema, dict):
            raise ControllerContractRegistryError("contract names and schemas must be mappings")
        _reject_external_refs(schema)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ControllerContractRegistryError(
                f"invalid controller contract {name!r}: {exc.message}"
            ) from exc
        properties = schema.get("properties")
        state_schema = properties.get("state_updates") if isinstance(properties, dict) else None
        state_properties = (
            state_schema.get("properties") if isinstance(state_schema, dict) else None
        )
        if (
            schema.get("type") != "object"
            or schema.get("additionalProperties") is not False
            or not isinstance(state_schema, dict)
            or state_schema.get("type") != "object"
            or state_schema.get("additionalProperties") is not False
            or not isinstance(state_properties, dict)
            or not state_properties
        ):
            raise ControllerContractRegistryError(
                f"controller contract {name!r} does not satisfy the supported schema profile"
            )
        canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
        compiled[name] = CompiledControllerStateContract(
            name=name,
            schema=_freeze(schema),
            state_update_keys=frozenset(str(key) for key in state_properties),
            validator=Draft202012Validator(schema),
            sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )
    return MappingProxyType(compiled)


def normalize_controller_updates(
    updates: Mapping[str, Any],
) -> NormalizationOutcome:
    normalized_paths: list[str] = []
    active: set[int] = set()
    visited = 0

    def limit_error(path: str) -> ControllerStateContractViolation:
        return ControllerStateContractViolation(
            "controller normalization limit exceeded",
            contract="normalization",
            json_path=path,
            validator="normalization_limit",
        )

    def collection_error(
        path: str,
        validator: str,
        message: str,
    ) -> ControllerStateContractViolation:
        return ControllerStateContractViolation(
            message,
            contract="normalization",
            json_path=path,
            validator=validator,
        )

    def visit(value: Any, path: str, depth: int) -> Any:
        nonlocal visited
        visited += 1
        if depth > MAX_NORMALIZATION_DEPTH or visited > MAX_NORMALIZATION_NODES:
            raise limit_error(path)
        if isinstance(value, PathLike):
            result = fspath(value)
            if not isinstance(result, str):
                raise ControllerStateContractViolation(
                    "PathLike must normalize to text",
                    contract="normalization",
                    json_path=path,
                    validator="pathlike",
                )
            normalized_paths.append(path)
            return result
        if isinstance(value, Enum):
            result = visit(value.value, path, depth + 1)
            if result is not None and not isinstance(result, (str, bool, int, float)):
                raise ControllerStateContractViolation(
                    "Enum value must be a supported scalar",
                    contract="normalization",
                    json_path=path,
                    validator="enum",
                )
            normalized_paths.append(path)
            return result
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        if isinstance(value, (list, tuple)):
            if len(value) > MAX_NORMALIZATION_COLLECTION:
                raise collection_error(
                    path,
                    "maxItems",
                    "controller collection is too large",
                )
            identity = id(value)
            if identity in active:
                raise collection_error(path, "cycle", "cyclic controller value")
            active.add(identity)
            try:
                result = [
                    visit(item, f"{path}[{index}]", depth + 1)
                    for index, item in enumerate(value)
                ]
            finally:
                active.remove(identity)
            if isinstance(value, tuple):
                normalized_paths.append(path)
            return result
        if isinstance(value, MappingABC):
            if len(value) > MAX_NORMALIZATION_COLLECTION:
                raise collection_error(
                    path,
                    "maxProperties",
                    "controller mapping is too large",
                )
            if not all(isinstance(key, str) for key in value):
                raise collection_error(
                    path,
                    "propertyNames",
                    "controller mapping keys must be strings",
                )
            identity = id(value)
            if identity in active:
                raise collection_error(path, "cycle", "cyclic controller value")
            active.add(identity)
            try:
                result = {
                    key: visit(item, f"{path}.{key}", depth + 1)
                    for key, item in value.items()
                }
            finally:
                active.remove(identity)
            if type(value) is not dict:
                normalized_paths.append(path)
            return result
        raise ControllerStateContractViolation(
            f"unsupported controller value type {type(value).__name__}",
            contract="normalization",
            json_path=path,
            validator="type",
        )

    result = visit(dict(updates), "$.state_updates", 0)
    return NormalizationOutcome(
        updates=result,
        normalized_paths=tuple(sorted(set(normalized_paths))),
    )


def validate_controller_result(
    contract: CompiledControllerStateContract,
    verdict: str,
    updates: Mapping[str, Any],
) -> tuple[ControllerContractError, ...]:
    payload = {"verdict": verdict, "state_updates": dict(updates)}
    errors = []
    for error in contract.validator.iter_errors(payload):
        path = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}"
            for part in error.absolute_path
        )
        validator = str(error.validator or "schema")
        constraint = json.dumps(
            error.validator_value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        errors.append(
            ControllerContractError(
                contract=contract.name,
                json_path=path,
                validator=validator,
                message=f"{validator} constraint {constraint} violated at {path}",
            )
        )
    return tuple(
        sorted(errors, key=lambda item: (item.json_path, item.validator, item.message))
    )
