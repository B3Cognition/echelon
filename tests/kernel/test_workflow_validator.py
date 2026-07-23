"""Tests for deterministic workflow/definition.yaml validation."""

from pathlib import Path

import pytest
import yaml

from harness.workflow_validator import (
    validate_condition_expression,
    validate_workflow_definition,
)


ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "extension/workflow/definition.yaml"
EXT_YML = ROOT / "extension/extension.yml"


def _write_definition(
    tmp_path: Path,
    phases: list[dict],
    *,
    controller_state_contracts_file: str | None = None,
) -> Path:
    path = tmp_path / "definition.yaml"
    definition: dict[str, object] = {"phases": phases}
    if controller_state_contracts_file is not None:
        definition["controller_state_contracts_file"] = (
            controller_state_contracts_file
        )
    path.write_text(yaml.safe_dump(definition), encoding="utf-8")
    return path


def _write_extension_yml(tmp_path: Path) -> Path:
    path = tmp_path / "extension.yml"
    path.write_text("provides: {commands: []}\n", encoding="utf-8")
    return path


def _write_controller_registry(tmp_path: Path) -> Path:
    path = tmp_path / "controller-state-contracts.yaml"
    path.write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "contracts": {
                "sample": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["verdict", "state_updates"],
                    "properties": {
                        "verdict": {"type": "string"},
                        "state_updates": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "controller_only": {"type": "boolean"},
                            },
                        },
                    },
                }
            },
        }),
        encoding="utf-8",
    )
    return path


def test_real_workflow_definition_is_valid() -> None:
    report = validate_workflow_definition(
        definition_path=DEFINITION,
        extension_yml_path=EXT_YML,
    )

    assert report.ok, report.format()


@pytest.mark.parametrize(
    "condition",
    [
        "always",
        "verdict = PASS",
        "verdict in [DONE, DONE_WITH_CONCERNS]",
        "iteration < max_iterations",
        "quality_gates.fail AND iteration < max_iterations",
        "autonomy = banzai OR human_approved",
        "governance.enabled AND NOT feasibility_structural_pass",
        "more_tasks_in_phase_group",
    ],
)
def test_condition_validator_accepts_supported_condition_syntax(
    condition: str,
) -> None:
    assert validate_condition_expression(condition) is None


@pytest.mark.parametrize(
    "condition",
    [
        "",
        "verdict ~= PASS",
        "iteration between 1 and 3",
        "status != blocked",
        "flag AND",
        "OR flag",
        "field in []",
    ],
)
def test_condition_validator_rejects_unsupported_condition_syntax(
    condition: str,
) -> None:
    issue = validate_condition_expression(condition)

    assert issue is not None


def test_workflow_validator_rejects_unknown_transition_key(tmp_path: Path) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "transitions": [
                    {
                        "to": "done",
                        "condition": "always",
                        "guard": "iteration < max_iterations",
                    }
                ],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert not report.ok
    assert any("unsupported transition key 'guard'" in issue.message for issue in report.issues)


def test_workflow_validator_rejects_unknown_transition_target(tmp_path: Path) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "transitions": [{"to": "missing-phase", "condition": "always"}],
            }
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert not report.ok
    assert any("unknown transition target" in issue.message for issue in report.issues)


def test_workflow_validator_rejects_unknown_phase_condition_field(tmp_path: Path) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "condition": "missing_field",
                "transitions": [{"to": "done", "condition": "always"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert not report.ok
    assert any("unresolvable phase condition field 'missing_field'" in issue.message for issue in report.issues)


def test_workflow_validator_rejects_unknown_greenfield_action(tmp_path: Path) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "condition": "mode = brownfield",
                "on_greenfield": {"action": "invented_skip"},
                "transitions": [{"to": "done", "condition": "always"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert not report.ok
    assert any("phase.on_greenfield.action" in issue.message for issue in report.issues)


def test_workflow_validator_rejects_non_object_transition(tmp_path: Path) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "transitions": ["done"],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert not report.ok
    assert any("transition must be an object" in issue.message for issue in report.issues)


def test_workflow_validator_rejects_invalid_condition(tmp_path: Path) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "transitions": [{"to": "done", "condition": "verdict ~= PASS"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert not report.ok
    assert any("unsupported condition syntax" in issue.message for issue in report.issues)


def test_workflow_validator_rejects_unresolvable_condition_field(tmp_path: Path) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "transitions": [{"to": "done", "condition": "alignment = ALIGNED"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert not report.ok
    assert any(
        "unresolvable condition field 'alignment'" in issue.message
        for issue in report.issues
    )


def test_workflow_validator_accepts_declared_state_update_condition_field(
    tmp_path: Path,
) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "allowed_state_updates": ["alignment"],
                "transitions": [{"to": "done", "condition": "alignment = ALIGNED"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert report.ok, report.format()


def test_workflow_validator_rejects_later_phase_state_update_condition_field(
    tmp_path: Path,
) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "transitions": [{"to": "done", "condition": "alignment = ALIGNED"}],
            },
            {
                "id": "done",
                "type": "terminal",
                "allowed_state_updates": ["alignment"],
            },
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert not report.ok
    assert any(
        "unresolvable condition field 'alignment'" in issue.message
        for issue in report.issues
    )


def test_workflow_validator_rejects_required_state_update_outside_allowlist(
    tmp_path: Path,
) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "allowed_state_updates": ["alignment"],
                "required_state_updates": ["invented"],
                "transitions": [{"to": "done", "condition": "always"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert not report.ok
    assert any("required_state_updates must be a subset" in issue.message for issue in report.issues)


def test_workflow_validator_rejects_legacy_controller_state_updates(
    tmp_path: Path,
) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "allowed_state_updates": [],
                "controller_state_updates": ["legacy"],
                "transitions": [{"to": "done", "condition": "always"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert not report.ok
    assert any(
        "controller_state_updates is no longer supported" in issue.message
        for issue in report.issues
    )


def test_workflow_validator_rejects_unknown_controller_contract(
    tmp_path: Path,
) -> None:
    registry = _write_controller_registry(tmp_path)
    definition = _write_definition(
        tmp_path,
        [{
            "id": "start",
            "type": "agent",
            "allowed_state_updates": [],
            "controller_state_contract": "missing",
            "transitions": [{"to": "done", "condition": "always"}],
        }, {"id": "done", "type": "terminal"}],
        controller_state_contracts_file=registry.name,
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert any(
        "unknown controller state contract 'missing'" in issue.message
        for issue in report.issues
    )


def test_workflow_validator_requires_explicit_allowlist_for_controller_contract(
    tmp_path: Path,
) -> None:
    registry = _write_controller_registry(tmp_path)
    definition = _write_definition(
        tmp_path,
        [{
            "id": "start",
            "type": "agent",
            "controller_state_contract": "sample",
            "transitions": [{"to": "done", "condition": "always"}],
        }, {"id": "done", "type": "terminal"}],
        controller_state_contracts_file=registry.name,
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert any(
        "controller_state_contract requires an explicit allowed_state_updates"
        in issue.message
        for issue in report.issues
    )


def test_workflow_validator_rejects_null_allowlist_for_controller_contract(
    tmp_path: Path,
) -> None:
    registry = _write_controller_registry(tmp_path)
    definition = _write_definition(
        tmp_path,
        [{
            "id": "start",
            "type": "agent",
            "allowed_state_updates": None,
            "controller_state_contract": "sample",
            "transitions": [{"to": "done", "condition": "always"}],
        }, {"id": "done", "type": "terminal"}],
        controller_state_contracts_file=registry.name,
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert any(
        "controller_state_contract requires allowed_state_updates to be a list"
        in issue.message
        for issue in report.issues
    )


def test_workflow_validator_reports_malformed_top_level_allowlist_with_contract(
    tmp_path: Path,
) -> None:
    registry = _write_controller_registry(tmp_path)
    definition = _write_definition(
        tmp_path,
        [{
            "id": "start",
            "type": "agent",
            "allowed_state_updates": 1,
            "controller_state_contract": "sample",
            "transitions": [{"to": "done", "condition": "always"}],
        }, {"id": "done", "type": "terminal"}],
        controller_state_contracts_file=registry.name,
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert any(
        "allowed_state_updates must be a list" in issue.message
        for issue in report.issues
    )


def test_workflow_validator_rejects_controller_provider_overlap(
    tmp_path: Path,
) -> None:
    registry = _write_controller_registry(tmp_path)
    definition = _write_definition(
        tmp_path,
        [{
            "id": "start",
            "type": "agent",
            "allowed_state_updates": ["controller_only"],
            "controller_state_contract": "sample",
            "transitions": [{"to": "done", "condition": "always"}],
        }, {"id": "done", "type": "terminal"}],
        controller_state_contracts_file=registry.name,
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert any(
        "controller state contract must not overlap allowed_state_updates"
        in issue.message
        for issue in report.issues
    )


def test_workflow_validator_rejects_nested_controller_reference(
    tmp_path: Path,
) -> None:
    registry = _write_controller_registry(tmp_path)
    definition = _write_definition(
        tmp_path,
        [{
            "id": "start",
            "type": "staged_parallel",
            "allowed_state_updates": [],
            "agents": [{
                "id": "nested",
                "allowed_state_updates": [],
                "controller_state_contract": "sample",
            }],
            "transitions": [{"to": "done", "condition": "always"}],
        }, {"id": "done", "type": "terminal"}],
        controller_state_contracts_file=registry.name,
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert any(
        "nested agents cannot declare controller_state_contract" in issue.message
        for issue in report.issues
    )


def test_workflow_validator_reports_malformed_nested_allowlist_with_contract(
    tmp_path: Path,
) -> None:
    registry = _write_controller_registry(tmp_path)
    definition = _write_definition(
        tmp_path,
        [{
            "id": "start",
            "type": "staged_parallel",
            "allowed_state_updates": [],
            "controller_state_contract": "sample",
            "agents": [{"id": "nested", "allowed_state_updates": 1}],
            "transitions": [{"to": "done", "condition": "always"}],
        }, {"id": "done", "type": "terminal"}],
        controller_state_contracts_file=registry.name,
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert any(
        "allowed_state_updates must be a list" in issue.message
        for issue in report.issues
    )


def test_workflow_validator_rejects_nested_null_allowlist_override(
    tmp_path: Path,
) -> None:
    registry = _write_controller_registry(tmp_path)
    definition = _write_definition(
        tmp_path,
        [{
            "id": "start",
            "type": "staged_parallel",
            "allowed_state_updates": [],
            "controller_state_contract": "sample",
            "agents": [{"id": "nested", "allowed_state_updates": None}],
            "transitions": [{"to": "done", "condition": "always"}],
        }, {"id": "done", "type": "terminal"}],
        controller_state_contracts_file=registry.name,
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert any(
        "nested agent cannot override allowed_state_updates with null"
        in issue.message
        for issue in report.issues
    )


def test_workflow_validator_rejects_contract_bearing_greenfield_skip(
    tmp_path: Path,
) -> None:
    registry = _write_controller_registry(tmp_path)
    definition = _write_definition(
        tmp_path,
        [{
            "id": "start",
            "type": "agent",
            "allowed_state_updates": [],
            "controller_state_contract": "sample",
            "on_greenfield": {"action": "skip_agent_proceed_to_next"},
            "transitions": [{"to": "done", "condition": "always"}],
        }, {"id": "done", "type": "terminal"}],
        controller_state_contracts_file=registry.name,
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert any(
        "skip_agent_proceed_to_next cannot bypass a controller state contract"
        in issue.message
        for issue in report.issues
    )


def test_workflow_validator_resolves_controller_condition_fields(
    tmp_path: Path,
) -> None:
    registry = _write_controller_registry(tmp_path)
    definition = _write_definition(
        tmp_path,
        [{
            "id": "start",
            "type": "agent",
            "allowed_state_updates": [],
            "controller_state_contract": "sample",
            "transitions": [{
                "to": "done",
                "condition": "controller_only",
            }],
        }, {"id": "done", "type": "terminal"}],
        controller_state_contracts_file=registry.name,
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert report.ok, report.format()


def test_workflow_validator_rejects_unsupported_state_update_type(
    tmp_path: Path,
) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "allowed_state_updates": ["alignment"],
                "state_update_types": {"alignment": "made_up_type"},
                "transitions": [{"to": "done", "condition": "always"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert not report.ok
    assert any("unsupported state update type" in issue.message for issue in report.issues)


def test_workflow_validator_rejects_enum_for_undeclared_state_key(
    tmp_path: Path,
) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "allowed_state_updates": ["status"],
                "state_update_enums": {"invented": ["one", "two"]},
                "transitions": [{"to": "done", "condition": "always"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )

    assert not report.ok
    assert any("state_update_enums keys must be a subset" in issue.message for issue in report.issues)
