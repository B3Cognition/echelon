from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass, field
from enum import Enum
from os import PathLike, fspath
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry
from referencing.exceptions import NoSuchResource


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


@dataclass(frozen=True, slots=True)
class CompiledControllerStateContract:
    name: str
    schema: Mapping[str, Any]
    state_update_keys: frozenset[str]
    sha256: str
    _validator: Draft202012Validator = field(repr=False)

    def iter_validation_errors(
        self,
        payload: Mapping[str, Any],
    ) -> tuple[Any, ...]:
        """Validate through the immutable, digest-bound compiled schema."""
        return tuple(self._validator.iter_errors(payload))


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


def _jsonable_schema_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable_schema_value(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_jsonable_schema_value(item) for item in value]
    return value


_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_FORBIDDEN_REFERENCE_KEYWORDS = frozenset(
    {
        "$dynamicRef",
        "$recursiveRef",
        "$dynamicAnchor",
        "$recursiveAnchor",
    }
)
_FORBIDDEN_IDENTIFIER_KEYWORDS = frozenset({"$id", "$anchor"})


def _resolve_local_pointer(
    root: dict[str, Any],
    reference: str,
    *,
    path: str,
) -> None:
    current: Any = root
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if 0 <= index < len(current):
                current = current[index]
                continue
        raise ControllerContractRegistryError(
            f"unresolved local $ref {reference!r} at {path}"
        )


def _validate_schema_keywords(
    value: Any,
    *,
    root: dict[str, Any],
    path: str = "$",
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key in _FORBIDDEN_REFERENCE_KEYWORDS:
                raise ControllerContractRegistryError(
                    f"dynamic or recursive reference keyword {key} is "
                    f"forbidden at {child}"
                )
            if key in _FORBIDDEN_IDENTIFIER_KEYWORDS:
                raise ControllerContractRegistryError(
                    f"controller contract does not satisfy the supported "
                    f"schema profile: {key} is forbidden at {child}"
                )
            if key == "$ref":
                if (
                    not isinstance(item, str)
                    or not item.startswith("#/$defs/")
                ):
                    raise ControllerContractRegistryError(
                        f"remote or non-local $ref is forbidden at {child}"
                    )
                _resolve_local_pointer(root, item, path=child)
            if key == "default":
                raise ControllerContractRegistryError(
                    f"schema defaults are forbidden at {child}"
                )
            _validate_schema_keywords(item, root=root, path=child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_schema_keywords(
                item,
                root=root,
                path=f"{path}[{index}]",
            )


def _no_schema_retrieval(uri: str):
    raise NoSuchResource(ref=uri)


def _schema_profile_state_properties(
    name: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    properties = schema.get("properties")
    verdict_schema = (
        properties.get("verdict") if isinstance(properties, dict) else None
    )
    state_schema = (
        properties.get("state_updates")
        if isinstance(properties, dict)
        else None
    )
    state_properties = (
        state_schema.get("properties")
        if isinstance(state_schema, dict)
        else None
    )
    required = schema.get("required")
    if (
        schema.get("$schema") != _DRAFT_2020_12
        or schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or not isinstance(required, list)
        or not {"verdict", "state_updates"}.issubset(required)
        or not isinstance(verdict_schema, dict)
        or verdict_schema.get("type") != "string"
        or not isinstance(state_schema, dict)
        or state_schema.get("type") != "object"
        or state_schema.get("additionalProperties") is not False
        or not isinstance(state_properties, dict)
        or not state_properties
        or any(
            not isinstance(key, str) or not key
            for key in state_properties
        )
    ):
        raise ControllerContractRegistryError(
            f"controller contract {name!r} does not satisfy the supported "
            "schema profile"
        )
    return state_properties


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
        _validate_schema_keywords(schema, root=schema)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ControllerContractRegistryError(
                f"invalid controller contract {name!r}: {exc.message}"
            ) from exc
        state_properties = _schema_profile_state_properties(name, schema)
        canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
        immutable_schema = _freeze(schema)
        compiled[name] = CompiledControllerStateContract(
            name=name,
            schema=immutable_schema,
            state_update_keys=frozenset(str(key) for key in state_properties),
            sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            _validator=Draft202012Validator(
                immutable_schema,
                registry=Registry(retrieve=_no_schema_retrieval),
            ),
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
        if type(value) in (list, tuple):
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
            if type(value) is tuple:
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
            "unsupported controller value type",
            contract="normalization",
            json_path=path,
            validator="type",
        )

    protocol_failure: ControllerStateContractViolation | None = None
    try:
        result = visit(updates, "$.state_updates", 0)
    except ControllerStateContractViolation:
        raise
    except Exception:
        protocol_failure = ControllerStateContractViolation(
            "controller value detachment failed",
            contract="normalization",
            json_path="$.state_updates",
            validator="normalization_protocol",
        )
    if protocol_failure is not None:
        raise protocol_failure
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
    for error in contract.iter_validation_errors(payload):
        path = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}"
            for part in error.absolute_path
        )
        validator = str(error.validator or "schema")
        constraint = json.dumps(
            _jsonable_schema_value(error.validator_value),
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
