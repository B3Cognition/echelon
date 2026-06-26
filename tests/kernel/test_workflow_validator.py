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


def _write_definition(tmp_path: Path, phases: list[dict]) -> Path:
    path = tmp_path / "definition.yaml"
    path.write_text(yaml.safe_dump({"phases": phases}), encoding="utf-8")
    return path


def _write_extension_yml(tmp_path: Path) -> Path:
    path = tmp_path / "extension.yml"
    path.write_text("provides: {commands: []}\n", encoding="utf-8")
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
