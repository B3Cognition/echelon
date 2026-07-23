from collections import UserDict
from collections.abc import Mapping as MappingABC
from enum import Enum
from os import PathLike
from pathlib import Path, PurePosixPath

import pytest
import yaml

from harness.controller_state_contracts import (
    ControllerContractRegistryError,
    ControllerStateContractViolation,
    load_controller_state_contracts,
    normalize_controller_updates,
    validate_controller_result,
)


class DemoEnum(Enum):
    VALUE = "value"


class BytesPath(PathLike[bytes]):
    def __fspath__(self) -> bytes:
        return b"not-text"


class ListSubclass(list[object]):
    pass


class TupleSubclass(tuple):
    pass


class ExplodingPath(PathLike[str]):
    def __fspath__(self) -> str:
        raise RuntimeError("secret-path-protocol-detail")


class ExplodingMapping(MappingABC[str, object]):
    def __getitem__(self, key: str) -> object:
        raise KeyError(key)

    def __iter__(self):
        raise RuntimeError("secret-mapping-protocol-detail")

    def __len__(self) -> int:
        return 1


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


def _load_sample_contract(tmp_path: Path):
    return load_controller_state_contracts(
        _write_registry(
            tmp_path,
            {
                "sample": _schema(
                    {
                        "count": {"type": "integer", "minimum": 0},
                        "pass": {"type": "boolean"},
                    }
                )
            },
        )
    )["sample"]


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


def test_registry_rejects_dangling_local_ref_at_startup(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        {
            "sample": _schema(
                {"value": {"$ref": "#/$defs/missing"}},
            )
        },
    )

    with pytest.raises(
        ControllerContractRegistryError,
        match="unresolved local.*\\$ref",
    ):
        load_controller_state_contracts(path)


def test_registry_rejects_dynamic_and_recursive_reference_keywords(
    tmp_path: Path,
) -> None:
    for keyword, reference in (
        ("$dynamicRef", "https://example.test/schema"),
        ("$recursiveRef", "#"),
    ):
        path = _write_registry(
            tmp_path,
            {
                "sample": _schema(
                    {"value": {"type": "string"}},
                    extra={keyword: reference},
                )
            },
        )

        with pytest.raises(
            ControllerContractRegistryError,
            match="dynamic or recursive",
        ):
            load_controller_state_contracts(path)


def test_compiled_contract_hides_an_immutable_validator_facade(
    tmp_path: Path,
) -> None:
    contract = _load_sample_contract(tmp_path)

    assert not hasattr(contract, "validator")
    assert not contract.iter_validation_errors(
        {"verdict": "DONE", "state_updates": {"count": 0, "pass": True}}
    )
    with pytest.raises(TypeError):
        contract.schema["properties"]["state_updates"]["properties"]["count"][
            "minimum"
        ] = -100


@pytest.mark.parametrize(
    "mutate",
    [
        lambda schema: schema.update(
            {"$schema": "https://json-schema.org/draft/2019-09/schema"}
        ),
        lambda schema: schema["required"].remove("verdict"),
        lambda schema: schema["properties"].pop("verdict"),
        lambda schema: schema.update({"$id": "https://example.test/contract"}),
        lambda schema: schema.update({"$dynamicAnchor": "node"}),
    ],
    ids=[
        "wrong-draft",
        "verdict-not-required",
        "missing-verdict-property",
        "schema-id",
        "dynamic-anchor",
    ],
)
def test_registry_enforces_the_complete_supported_schema_profile(
    tmp_path: Path,
    mutate,
) -> None:
    schema = _schema({"value": {"type": "string"}})
    mutate(schema)
    path = _write_registry(tmp_path, {"sample": schema})

    with pytest.raises(
        ControllerContractRegistryError,
        match="supported schema profile|dynamic or recursive",
    ):
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


def test_lossless_normalization_is_idempotent() -> None:
    source = {
        "path": PurePosixPath("reports/result.json"),
        "enum": DemoEnum.VALUE,
        "items": ["native", ("one", {"two": ("three",)})],
    }

    first = normalize_controller_updates(source)
    second = normalize_controller_updates(first.updates)

    assert first.updates == {
        "path": "reports/result.json",
        "enum": "value",
        "items": ["native", ["one", {"two": ["three"]}]],
    }
    assert first.normalized_paths == (
        "$.state_updates.enum",
        "$.state_updates.items[1]",
        "$.state_updates.items[1][1].two",
        "$.state_updates.path",
    )
    assert second.updates == first.updates
    assert second.normalized_paths == ()
    assert source["items"] == ["native", ("one", {"two": ("three",)})]


def test_normalizer_records_non_dict_mapping_conversion() -> None:
    outcome = normalize_controller_updates({"nested": UserDict({"value": 1})})

    assert outcome.updates == {"nested": {"value": 1}}
    assert outcome.normalized_paths == ("$.state_updates.nested",)


def test_normalizer_records_root_non_dict_mapping_conversion() -> None:
    outcome = normalize_controller_updates(UserDict({"value": 1}))

    assert outcome.updates == {"value": 1}
    assert outcome.normalized_paths == ("$.state_updates",)


def test_normalizer_rejects_oversized_root_mapping_before_traversal() -> None:
    class OversizedMapping(MappingABC[str, object]):
        def __getitem__(self, key: str) -> object:
            raise AssertionError(f"root mapping must not access {key!r}")

        def __iter__(self):
            raise AssertionError("root mapping must not be traversed")

        def __len__(self) -> int:
            return 10_001

    with pytest.raises(ControllerStateContractViolation, match="too large") as raised:
        normalize_controller_updates(OversizedMapping())

    assert raised.value.validator == "maxProperties"


@pytest.mark.parametrize("value", [ListSubclass(), TupleSubclass()])
def test_normalizer_rejects_list_and_tuple_subclasses(value: object) -> None:
    with pytest.raises(ControllerStateContractViolation, match="unsupported") as raised:
        normalize_controller_updates({"value": value})

    assert raised.value.validator == "type"


@pytest.mark.parametrize("value", [{1, 2}, b"bytes"])
def test_normalizer_rejects_ambiguous_values(value: object) -> None:
    with pytest.raises(ControllerStateContractViolation):
        normalize_controller_updates({"value": value})


def test_normalizer_preserves_json_native_scalar_types() -> None:
    outcome = normalize_controller_updates(
        {"text": "true", "other_text": "2", "flag": True, "count": 2}
    )

    assert outcome.updates == {
        "text": "true",
        "other_text": "2",
        "flag": True,
        "count": 2,
    }
    assert outcome.normalized_paths == ()


def test_normalizer_rejects_cycles() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)

    with pytest.raises(ControllerStateContractViolation, match="cyclic") as raised:
        normalize_controller_updates({"value": cyclic})

    assert raised.value.validator == "cycle"


def test_normalizer_rejects_depth_33() -> None:
    value: object = []
    for _ in range(33):
        value = [value]

    with pytest.raises(ControllerStateContractViolation, match="limit exceeded") as raised:
        normalize_controller_updates({"value": value})

    assert raised.value.validator == "normalization_limit"


def test_normalizer_rejects_10001_visited_values() -> None:
    with pytest.raises(ControllerStateContractViolation, match="limit exceeded") as raised:
        normalize_controller_updates({"value": [None] * 9_999})

    assert raised.value.validator == "normalization_limit"


def test_normalizer_rejects_10001_entry_collection() -> None:
    with pytest.raises(ControllerStateContractViolation, match="too large") as raised:
        normalize_controller_updates({"value": [None] * 10_001})

    assert raised.value.validator == "maxItems"


def test_normalizer_rejects_bytes_returning_pathlike() -> None:
    with pytest.raises(ControllerStateContractViolation, match="must normalize to text") as raised:
        normalize_controller_updates({"value": BytesPath()})

    assert raised.value.validator == "pathlike"


def test_normalizer_rejects_non_string_mapping_keys() -> None:
    with pytest.raises(ControllerStateContractViolation, match="keys must be strings") as raised:
        normalize_controller_updates({"value": {1: "one"}})

    assert raised.value.validator == "propertyNames"


@pytest.mark.parametrize(
    "updates",
    [
        {"value": ExplodingPath()},
        ExplodingMapping(),
    ],
    ids=["pathlike-protocol", "mapping-protocol"],
)
def test_normalizer_converts_protocol_failures_to_context_free_violation(
    updates: MappingABC[str, object],
) -> None:
    with pytest.raises(ControllerStateContractViolation) as raised:
        normalize_controller_updates(updates)

    assert str(raised.value) == "controller value detachment failed"
    assert raised.value.validator == "normalization_protocol"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "secret-" not in repr(raised.value)


def test_contract_errors_are_sorted_and_value_redacted(tmp_path: Path) -> None:
    contract = _load_sample_contract(tmp_path)
    errors = validate_controller_result(
        contract,
        "DONE",
        {"count": -1, "pass": "secret-invalid-value"},
    )

    assert [error.json_path for error in errors] == sorted(
        error.json_path for error in errors
    )
    assert all("secret-invalid-value" not in str(error) for error in errors)
    assert [error.message for error in errors] == [
        "minimum constraint 0 violated at $.state_updates.count",
        'type constraint "boolean" violated at $.state_updates.pass',
    ]


def test_contract_validation_rejects_boolean_for_integer_schema(tmp_path: Path) -> None:
    errors = validate_controller_result(
        _load_sample_contract(tmp_path),
        "DONE",
        {"count": True, "pass": True},
    )

    assert [(error.json_path, error.validator) for error in errors] == [
        ("$.state_updates.count", "type")
    ]
    assert errors[0].message == (
        'type constraint "integer" violated at $.state_updates.count'
    )
