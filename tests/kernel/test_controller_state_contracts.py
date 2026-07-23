from pathlib import Path

import pytest
import yaml

from harness.controller_state_contracts import (
    ControllerContractRegistryError,
    load_controller_state_contracts,
)


def _schema(
    fields: dict[str, object],
    *,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["verdict", "state_updates"],
        "properties": {
            "verdict": {"type": "string"},
            "state_updates": {
                "type": "object",
                "additionalProperties": False,
                "properties": fields,
            },
        },
    }
    schema.update(extra or {})
    return schema


def _write_registry(
    tmp_path: Path,
    contracts: dict[str, object],
) -> Path:
    path = tmp_path / "contracts.yaml"
    path.write_text(
        yaml.safe_dump({"schema_version": 1, "contracts": contracts}),
        encoding="utf-8",
    )
    return path


def test_registry_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    path = tmp_path / "contracts.yaml"
    path.write_text(
        "schema_version: 1\ncontracts:\n  sample: {}\n  sample: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(ControllerContractRegistryError, match="duplicate key 'sample'"):
        load_controller_state_contracts(path)


def test_registry_rejects_remote_ref(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        {
            "sample": _schema(
                {"value": {"type": "string"}},
                extra={"$ref": "https://example.test/schema.json"},
            )
        },
    )
    with pytest.raises(ControllerContractRegistryError, match="remote.*\\$ref"):
        load_controller_state_contracts(path)


def test_registry_compiles_immutable_contract_and_stable_digest(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        {"sample": _schema({"value": {"type": "string"}})},
    )
    first = load_controller_state_contracts(path)["sample"]
    second = load_controller_state_contracts(path)["sample"]
    assert first.state_update_keys == frozenset({"value"})
    assert first.sha256 == second.sha256
    with pytest.raises(TypeError):
        first.schema["type"] = "array"
