from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
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
