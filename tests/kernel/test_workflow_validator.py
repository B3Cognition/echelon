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
    )

    assert report.ok, report.format()


def test_real_workflow_gate_edges_match_declared_outcomes() -> None:
    definition = yaml.safe_load(DEFINITION.read_text(encoding="utf-8"))
    phases = {phase["id"]: phase for phase in definition["phases"]}

    assert phases["checkpoint-assess"]["transitions"] == [
        {
            "to": "phase2-decide",
            "condition": "human_input_outcome = approved",
            "outcome": "approved",
        },
        {
            "to": "terminal-blocked",
            "condition": "human_input_outcome = rejected",
            "outcome": "rejected",
        },
    ]
    assert phases["checkpoint-plan"]["transitions"] == [
        {
            "to": "phase4-document",
            "condition": "human_input_outcome = approved",
            "outcome": "approved",
        },
        {
            "to": "terminal-blocked",
            "condition": "human_input_outcome = rejected",
            "outcome": "rejected",
        },
    ]


def _human_input_provider_policy(*, reason_code: str = "human_clarification_required") -> dict:
    return {
        "reason_code": reason_code,
        "classification": "material",
        "semi_policy": "auto_if_recommended_low_risk",
        "resolution_handler": "clarification_resume",
        "allow_free_text": True,
        "allowed_target_phases": ["done"],
        "context_state_keys": ["user_message", "phase"],
        "context_paths": ["{staging_dir}/user-intent.md"],
        "options": [],
    }


def _human_input_gate_policy() -> dict:
    return {
        "reason_code": "checkpoint_plan_decision_required",
        "classification": "operational",
        "semi_policy": "auto_if_recommended_low_risk",
        "resolution_handler": "gate_outcome",
        "allow_free_text": False,
        "allowed_target_phases": ["done", "terminal-blocked"],
        "context_state_keys": ["user_message", "phase"],
        "context_paths": ["{spec_dir}/plan.md"],
        "options": [
            {
                "id": "approve",
                "label": "Approve",
                "description": "Continue.",
                "recommended": True,
                "risk_level": "low",
                "next_phase": "done",
                "outcome": "approved",
            },
            {
                "id": "reject",
                "label": "Reject",
                "description": "Stop.",
                "recommended": False,
                "risk_level": "low",
                "next_phase": "terminal-blocked",
                "outcome": "rejected",
            },
        ],
    }


def test_workflow_validator_keeps_a_legacy_workflow_without_declarations_valid(tmp_path: Path) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "provider",
                "type": "agent",
                "allowed_state_updates": ["escalation_question"],
                "transitions": [{"to": "done", "condition": "always"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
    )

    assert report.ok, report.format()


def test_workflow_validator_allows_provider_policy_without_static_options(tmp_path: Path) -> None:
    policy = _human_input_provider_policy()
    policy.pop("options")
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "provider",
                "type": "agent",
                "allowed_state_updates": ["escalation_question"],
                "human_input": [policy],
                "transitions": [{"to": "done", "condition": "always"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
    )

    assert report.ok, report.format()


def test_workflow_validator_requires_complete_provider_coverage_after_opt_in(tmp_path: Path) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "provider-a",
                "type": "agent",
                "allowed_state_updates": ["escalation_question"],
                "human_input": [_human_input_provider_policy()],
                "transitions": [{"to": "done", "condition": "always"}],
            },
            {
                "id": "provider-b",
                "type": "agent",
                "allowed_state_updates": ["escalation_question"],
                "transitions": [{"to": "done", "condition": "always"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
    )

    assert not report.ok
    assert any(issue.phase_id == "provider-b" and "human_input policy" in issue.message for issue in report.issues)


@pytest.mark.parametrize(
    "mutation, expected",
    [
        (lambda policy: policy.update({"classification": "optional"}), "classification"),
        (lambda policy: policy.update({"semi_policy": "sometimes"}), "semi_policy"),
        (lambda policy: policy.update({"resolution_handler": "anything"}), "resolution_handler"),
        (lambda policy: policy.update({"context_state_keys": ["write_anything"]}), "context_state_keys"),
        (lambda policy: policy.update({"context_paths": ["/tmp/escape"]}), "context_paths"),
        (lambda policy: policy.update({"allowed_target_phases": ["missing"]}), "allowed_target_phases"),
        (lambda policy: policy.update({"options": "not-a-list"}), "options"),
    ],
)
def test_workflow_validator_closes_human_input_declarations(tmp_path: Path, mutation, expected: str) -> None:
    policy = _human_input_provider_policy()
    mutation(policy)
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "provider",
                "type": "agent",
                "allowed_state_updates": ["escalation_question"],
                "human_input": [policy],
                "transitions": [{"to": "done", "condition": "always"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
    )

    assert not report.ok
    assert any(expected in issue.message for issue in report.issues)


def test_workflow_validator_requires_list_mappings_unique_reasons_and_exact_gate_edges(tmp_path: Path) -> None:
    gate_policy = _human_input_gate_policy()
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "provider",
                "type": "agent",
                "allowed_state_updates": ["escalation_question"],
                "human_input": [
                    _human_input_provider_policy(),
                    _human_input_provider_policy(reason_code="investigation_access_required"),
                ],
                "transitions": [{"to": "done", "condition": "always"}],
            },
            {
                "id": "checkpoint",
                "type": "human_gate",
                "human_input": [gate_policy],
                "transitions": [
                    {
                        "to": "done",
                        "condition": "human_input_outcome = denied",
                        "outcome": "approved",
                    },
                    {
                        "to": "terminal-blocked",
                        "condition": "human_input_outcome = rejected",
                        "outcome": "approved",
                    },
                ],
            },
            {"id": "done", "type": "terminal"},
            {"id": "terminal-blocked", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
    )

    assert not report.ok
    messages = "\n".join(issue.message for issue in report.issues)
    assert "outcome must match" in messages
    assert "outcome must be unique" in messages


def _gate_workflow(
    tmp_path: Path,
    *,
    policies: list[dict] | None = None,
    transitions: list[dict] | None = None,
) -> Path:
    return _write_definition(
        tmp_path,
        [
            {
                "id": "checkpoint",
                "type": "human_gate",
                "human_input": (
                    [_human_input_gate_policy()]
                    if policies is None
                    else policies
                ),
                "transitions": transitions or [
                    {
                        "to": "done",
                        "condition": "human_input_outcome = approved",
                        "outcome": "approved",
                    },
                    {
                        "to": "terminal-blocked",
                        "condition": "human_input_outcome = rejected",
                        "outcome": "rejected",
                    },
                ],
            },
            {"id": "done", "type": "terminal"},
            {"id": "terminal-blocked", "type": "terminal"},
        ],
    )


def _gate_report(tmp_path: Path, definition: Path):
    return validate_workflow_definition(
        definition_path=definition,
    )


def test_workflow_validator_rejects_multiple_gate_policies(tmp_path: Path) -> None:
    second = _human_input_gate_policy()
    second["reason_code"] = "another_gate_decision_required"
    report = _gate_report(
        tmp_path,
        _gate_workflow(
            tmp_path,
            policies=[_human_input_gate_policy(), second],
        ),
    )

    assert not report.ok
    assert any("exactly one human_input policy" in issue.message for issue in report.issues)


def test_workflow_validator_rejects_missing_gate_policy(tmp_path: Path) -> None:
    report = _gate_report(
        tmp_path,
        _gate_workflow(tmp_path, policies=[]),
    )

    assert not report.ok
    assert any("exactly one human_input policy" in issue.message for issue in report.issues)


def test_workflow_validator_rejects_custom_gate_outcome(tmp_path: Path) -> None:
    policy = _human_input_gate_policy()
    policy["options"][0]["outcome"] = "continued"
    report = _gate_report(
        tmp_path,
        _gate_workflow(
            tmp_path,
            policies=[policy],
            transitions=[
                {
                    "to": "done",
                    "condition": "human_input_outcome = continued",
                    "outcome": "continued",
                },
                {
                    "to": "terminal-blocked",
                    "condition": "human_input_outcome = rejected",
                    "outcome": "rejected",
                },
            ],
        ),
    )

    assert not report.ok
    assert any("exact approved/rejected outcomes" in issue.message for issue in report.issues)


def test_workflow_validator_rejects_gate_handler_mismatch(tmp_path: Path) -> None:
    policy = _human_input_gate_policy()
    policy["resolution_handler"] = "clarification_resume"
    report = _gate_report(
        tmp_path,
        _gate_workflow(tmp_path, policies=[policy]),
    )

    assert not report.ok
    assert any("resolution_handler must be gate_outcome" in issue.message for issue in report.issues)


def test_workflow_validator_rejects_gate_target_mismatch(tmp_path: Path) -> None:
    transitions = [
        {
            "to": "terminal-blocked",
            "condition": "human_input_outcome = approved",
            "outcome": "approved",
        },
        {
            "to": "terminal-blocked",
            "condition": "human_input_outcome = rejected",
            "outcome": "rejected",
        },
    ]
    report = _gate_report(
        tmp_path,
        _gate_workflow(tmp_path, transitions=transitions),
    )

    assert not report.ok
    assert any("target must match" in issue.message for issue in report.issues)


def test_workflow_validator_rejects_approved_route_to_terminal_blocked(
    tmp_path: Path,
) -> None:
    policy = _human_input_gate_policy()
    policy["options"][0]["next_phase"] = "terminal-blocked"
    report = _gate_report(
        tmp_path,
        _gate_workflow(
            tmp_path,
            policies=[policy],
            transitions=[
                {
                    "to": "terminal-blocked",
                    "condition": "human_input_outcome = approved",
                    "outcome": "approved",
                },
                {
                    "to": "terminal-blocked",
                    "condition": "human_input_outcome = rejected",
                    "outcome": "rejected",
                },
            ],
        ),
    )

    assert not report.ok
    assert any(
        "approved human gate outcome cannot target terminal-blocked"
        in issue.message
        for issue in report.issues
    )


def test_workflow_validator_requires_rejected_route_to_terminal_blocked(
    tmp_path: Path,
) -> None:
    policy = _human_input_gate_policy()
    policy["options"][1]["next_phase"] = "done"
    report = _gate_report(
        tmp_path,
        _gate_workflow(
            tmp_path,
            policies=[policy],
            transitions=[
                {
                    "to": "done",
                    "condition": "human_input_outcome = approved",
                    "outcome": "approved",
                },
                {
                    "to": "done",
                    "condition": "human_input_outcome = rejected",
                    "outcome": "rejected",
                },
            ],
        ),
    )

    assert not report.ok
    assert any(
        "rejected human gate outcome must target terminal-blocked"
        in issue.message
        for issue in report.issues
    )


def test_workflow_validator_rejects_gate_condition_mismatch(tmp_path: Path) -> None:
    transitions = [
        {
            "to": "done",
            "condition": "human_input_outcome = rejected",
            "outcome": "approved",
        },
        {
            "to": "terminal-blocked",
            "condition": "human_input_outcome = rejected",
            "outcome": "rejected",
        },
    ]
    report = _gate_report(
        tmp_path,
        _gate_workflow(tmp_path, transitions=transitions),
    )

    assert not report.ok
    assert any("condition" in issue.message for issue in report.issues)


def test_workflow_validator_rejects_duplicate_human_input_reason_code(tmp_path: Path) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "provider",
                "type": "agent",
                "allowed_state_updates": ["escalation_question"],
                "human_input": [
                    _human_input_provider_policy(),
                    _human_input_provider_policy(),
                ],
                "transitions": [{"to": "done", "condition": "always"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
    )

    assert not report.ok
    assert any("duplicate human_input reason_code" in issue.message for issue in report.issues)


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
    )

    assert not report.ok
    assert any("unknown transition target" in issue.message for issue in report.issues)


def test_workflow_validator_accepts_terminal_blocked_runtime_target(tmp_path: Path) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "investigate",
                "type": "agent",
                "transitions": [
                    {"to": "terminal-blocked", "condition": "always"},
                ],
            }
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
    )

    assert report.ok, report.format()


def test_workflow_validator_rejects_unknown_evidence_routing_mode(tmp_path: Path) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "what",
                "type": "agent",
                "evidence_routing": "prose",
                "transitions": [{"to": "done", "condition": "always"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
    )

    assert not report.ok
    assert any("evidence_routing" in issue.message for issue in report.issues)


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
    )

    assert not report.ok
    assert any(
        "unresolvable condition field 'alignment'" in issue.message
        for issue in report.issues
    )


def test_workflow_validator_accepts_derived_spec_lexicon_condition_field(
    tmp_path: Path,
) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "transitions": [
                    {
                        "to": "done",
                        "condition": "lexicon_gate.spec_enabled",
                    }
                ],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
    )

    assert report.ok, report.format()


def test_workflow_validator_rejects_unknown_nested_lexicon_condition_field(
    tmp_path: Path,
) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "transitions": [
                    {
                        "to": "done",
                        "condition": "lexicon_gate.unknown",
                    }
                ],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
    )

    assert not report.ok
    assert any(
        "unresolvable condition field 'lexicon_gate.unknown'" in issue.message
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
    )

    assert not report.ok
    assert any("required_state_updates must be a subset" in issue.message for issue in report.issues)


@pytest.mark.parametrize(
    "provider_location",
    ["phase", "nested_agent", "pre_dispatch"],
)
def test_workflow_validator_rejects_transaction_owned_provider_allowlist(
    tmp_path: Path,
    provider_location: str,
) -> None:
    phase = {
        "id": "start",
        "type": "agent",
        "allowed_state_updates": [],
        "transitions": [{"to": "done", "condition": "always"}],
    }
    if provider_location == "phase":
        phase["allowed_state_updates"] = ["manual_phase_runs"]
    elif provider_location == "nested_agent":
        phase["type"] = "conditional_sequential"
        phase["agents"] = [{
            "id": "nested",
            "allowed_state_updates": ["manual_phase_runs"],
        }]
    else:
        phase["pre_dispatch"] = [{
            "id": "guard",
            "agent": "nested",
            "allowed_state_updates": ["manual_phase_runs"],
        }]
    definition = _write_definition(
        tmp_path,
        [phase, {"id": "done", "type": "terminal"}],
    )

    report = validate_workflow_definition(
        definition_path=definition,
    )

    assert not report.ok
    assert any(
        "transaction-owned key 'manual_phase_runs'" in issue.message
        for issue in report.issues
    )


def test_workflow_validator_allows_provider_block_control_syntax(
    tmp_path: Path,
) -> None:
    definition = _write_definition(
        tmp_path,
        [
            {
                "id": "start",
                "type": "agent",
                "allowed_state_updates": ["status", "blocked_reason"],
                "transitions": [{"to": "done", "condition": "always"}],
            },
            {"id": "done", "type": "terminal"},
        ],
    )

    report = validate_workflow_definition(
        definition_path=definition,
    )

    assert report.ok, report.format()


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
    )

    assert any(
        "skip_agent_proceed_to_next cannot bypass a controller state contract"
        in issue.message
        for issue in report.issues
    )


_REQUIRED_CONTROLLER_CONTRACTS = {
    "phase1-lexicon": "spec_lexicon",
    "phase1-understanding": "understanding",
    "phase2-decide": "feasibility_authoring_verdict",
    "phase2-tracker-alignment": "intent_alignment_authoring_verdict",
    "phase3-tasks-lexicon": "tasks_lexicon",
    "phase3-understanding": "understanding",
    "phase3-consensus": "consensus_gate",
    "phase3-consensus-tasks-lexicon": "tasks_lexicon",
}


def _write_real_workflow_copy(tmp_path: Path) -> Path:
    raw = yaml.safe_load(DEFINITION.read_text(encoding="utf-8"))
    path = tmp_path / "definition.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    registry = DEFINITION.parent / "controller-state-contracts.yaml"
    (tmp_path / registry.name).write_text(
        registry.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("phase_id", "expected_contract"),
    sorted(_REQUIRED_CONTROLLER_CONTRACTS.items()),
)
@pytest.mark.parametrize("mutation", ["missing", "mismatched"])
def test_workflow_validator_requires_exact_contract_for_controller_role(
    tmp_path: Path,
    phase_id: str,
    expected_contract: str,
    mutation: str,
) -> None:
    definition = _write_real_workflow_copy(tmp_path)
    raw = yaml.safe_load(definition.read_text(encoding="utf-8"))
    phase = next(item for item in raw["phases"] if item["id"] == phase_id)
    if mutation == "missing":
        phase.pop("controller_state_contract")
    else:
        phase["controller_state_contract"] = (
            "tasks_lexicon"
            if expected_contract != "tasks_lexicon"
            else "understanding"
        )
    definition.write_text(
        yaml.safe_dump(raw, sort_keys=False),
        encoding="utf-8",
    )

    report = validate_workflow_definition(
        definition_path=definition,
    )

    assert any(
        phase_id == issue.phase_id
        and expected_contract in issue.message
        and "required controller state contract" in issue.message
        for issue in report.issues
    ), report.format()


def test_workflow_validator_requires_registry_for_controller_producing_nodes(
    tmp_path: Path,
) -> None:
    definition = _write_real_workflow_copy(tmp_path)
    raw = yaml.safe_load(definition.read_text(encoding="utf-8"))
    raw.pop("controller_state_contracts_file")
    definition.write_text(
        yaml.safe_dump(raw, sort_keys=False),
        encoding="utf-8",
    )

    report = validate_workflow_definition(
        definition_path=definition,
    )

    assert any(
        "controller-producing phases require controller_state_contracts_file"
        in issue.message
        for issue in report.issues
    ), report.format()


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
    )

    assert not report.ok
    assert any("state_update_enums keys must be a subset" in issue.message for issue in report.issues)
