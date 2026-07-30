"""Deterministic validation for Echelon workflow definitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml

from harness.controller_state_contract_requirements import (
    is_controller_producing_phase,
    required_controller_contract_name,
    structural_phase_definition_errors,
)
from harness.echelon_result_schema import ALLOWED_VERDICTS, SUPPORTED_STATE_UPDATE_TYPES
from harness.phase_graph import PhaseGraph, PhaseNode
from harness.human_input import (
    HumanInputPolicy,
    HumanInputPolicyError,
    compile_workflow_human_input_policies,
    gate_outcome_route_error,
)
from harness.state_transaction_namespace import (
    PROVIDER_CONTROL_INTENT_KEYS,
    STORE_OWNED_TRANSACTION_KEYS,
)


SUPPORTED_TRANSITION_KEYS = frozenset({
    "to",
    "condition",
    "action",
    "state_update",
    "outcome",
})

# Runtime-only terminal used by SquadController guards and explicit evidence
# escalation routes. It intentionally has no workflow definition node.
RUNTIME_TERMINAL_TARGETS = frozenset({"terminal-blocked"})


KNOWN_CONDITION_FIELDS = frozenset({
    # Result payload fields.
    "verdict",
    # CLI/run configuration fields injected into condition evaluation state.
    "autonomy",
    "guardian_mode",
    "human_approved",
    "mode",
    # Loop counters and limits managed by the harness/commander.
    "assess_defer_loop_limit",
    "defer_count",
    "feasibility_verdict",
    "intent_alignment_verdict",
    "fix_cycle",
    "iteration",
    "max_iterations",
    "retry_count",
    # Derived evaluator predicates.
    "CRITICAL_issues",
    "convergence_detected",
    "no_CRITICAL_issues",
    "quality_gates.fail",
    "quality_gates.pass",
    # Nested config-derived gates merged into evaluation state.
    "governance.enabled",
    "governance.max_repair_attempts",
    "lexicon_gate.enabled",
    "lexicon_gate.max_repair_attempts",
    "lexicon_gate.spec_enabled",
    # Build-task-loop progress predicates.
    "all_phase_groups_complete",
    "all_tasks_complete",
    "more_phase_groups",
    "more_tasks_in_phase_group",
    "no_more_phase_checkpoints",
    "phase_group_complete",
    "human_input_outcome",
})


@dataclass(frozen=True)
class WorkflowValidationIssue:
    """A machine-checkable workflow definition problem."""

    message: str
    phase_id: str | None = None
    transition_index: int | None = None
    path: str | None = None


@dataclass
class WorkflowValidationReport:
    """Validation report for workflow/definition.yaml."""

    issues: list[WorkflowValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def format(self) -> str:
        if self.ok:
            return "workflow definition valid"

        lines = ["workflow definition validation failed:"]
        for issue in self.issues:
            where = " ".join(
                part
                for part in [
                    issue.path or "",
                    issue.phase_id or "",
                    (
                        f"transition[{issue.transition_index}]"
                        if issue.transition_index is not None
                        else ""
                    ),
                ]
                if part
            )
            lines.append(f"- {where}: {issue.message}".rstrip())
        return "\n".join(lines)


def validate_workflow_definition(
    *,
    definition_path: Path,
    extension_yml_path: Path,
) -> WorkflowValidationReport:
    """Validate the main squad phase graph before runtime dispatch.

    The current harness executes only the top-level ``phases`` graph through
    ``PhaseGraph``. Nested command-specific workflow sections are intentionally
    out of scope for this first validator pass.
    """
    issues: list[WorkflowValidationIssue] = []
    path = str(definition_path)

    try:
        raw = yaml.safe_load(definition_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return WorkflowValidationReport([
            WorkflowValidationIssue(f"cannot read workflow YAML: {exc}", path=path)
        ])

    if not isinstance(raw, dict):
        return WorkflowValidationReport([
            WorkflowValidationIssue("workflow definition must be a mapping", path=path)
        ])

    phases = raw.get("phases")
    if not isinstance(phases, list) or not phases:
        return WorkflowValidationReport([
            WorkflowValidationIssue("workflow definition must contain phases[]", path=path)
        ])

    required_contract_issues = _validate_required_controller_contracts(
        raw,
        phases,
        path=path,
    )
    if required_contract_issues:
        return WorkflowValidationReport(required_contract_issues)

    boundary_issues: list[WorkflowValidationIssue] = []
    for phase in phases:
        if (
            not isinstance(phase, dict)
            or "controller_state_contract" not in phase
        ):
            continue
        phase_id = (
            phase.get("id")
            if isinstance(phase.get("id"), str)
            else None
        )
        if "allowed_state_updates" not in phase:
            boundary_issues.append(
                WorkflowValidationIssue(
                    "controller_state_contract requires an explicit "
                    "allowed_state_updates list",
                    phase_id=phase_id,
                    path=path,
                )
            )
        elif not isinstance(phase.get("allowed_state_updates"), list):
            boundary_issues.append(
                WorkflowValidationIssue(
                    (
                        "controller_state_contract requires "
                        "allowed_state_updates to be a list"
                        if phase.get("allowed_state_updates") is None
                        else "allowed_state_updates must be a list"
                    ),
                    phase_id=phase_id,
                    path=path,
                )
            )
        for nested_name in ("agents", "pre_dispatch"):
            entries = phase.get(nested_name, [])
            if not isinstance(entries, list):
                continue
            for index, entry in enumerate(entries):
                if (
                    not isinstance(entry, dict)
                    or "allowed_state_updates" not in entry
                    or isinstance(entry["allowed_state_updates"], list)
                ):
                    continue
                message = (
                    "nested agent cannot override "
                    "allowed_state_updates with null"
                    if entry["allowed_state_updates"] is None
                    else "allowed_state_updates must be a list"
                )
                boundary_issues.append(
                    WorkflowValidationIssue(
                        message,
                        phase_id=phase_id,
                        path=f"{path} {nested_name}[{index}]",
                    )
                )
    if boundary_issues:
        return WorkflowValidationReport(boundary_issues)

    try:
        graph = PhaseGraph(definition_path, extension_yml_path)
    except Exception as exc:
        return WorkflowValidationReport([
            WorkflowValidationIssue(f"cannot load phase graph: {exc}", path=path)
        ])

    phase_ids = set(graph.all_phase_ids())
    workflow_declares_human_input = any(
        isinstance(phase, dict) and "human_input" in phase
        for phase in phases
    )
    compiled_human_input: dict[str, tuple[HumanInputPolicy, ...]] = {}
    for phase in phases:
        if not isinstance(phase, dict) or not isinstance(phase.get("id"), str):
            continue
        try:
            compiled_human_input[phase["id"]] = compile_workflow_human_input_policies(
                phase,
                known_phase_ids=frozenset(phase_ids),
            )
        except HumanInputPolicyError as exc:
            issues.append(WorkflowValidationIssue(
                str(exc), phase_id=phase["id"], path=path,
            ))
    known_condition_fields = set(KNOWN_CONDITION_FIELDS)
    seen: set[str] = set()

    for phase_index, phase in enumerate(phases):
        if not isinstance(phase, dict):
            issues.append(
                WorkflowValidationIssue(
                    "phase must be an object",
                    transition_index=phase_index,
                    path=path,
                )
            )
            continue

        phase_id = phase.get("id")
        if not isinstance(phase_id, str) or not phase_id.strip():
            issues.append(
                WorkflowValidationIssue(
                    "phase.id must be a non-empty string",
                    transition_index=phase_index,
                    path=path,
                )
            )
            continue
        if phase_id in seen:
            issues.append(
                WorkflowValidationIssue(
                    f"duplicate phase id {phase_id!r}",
                    phase_id=phase_id,
                    path=path,
                )
            )
        seen.add(phase_id)
        node = graph.get(phase_id)
        known_condition_fields.update(_phase_condition_fields(node))

        issues.extend(
            _validate_result_contract_definition(
                phase,
                phase_id=phase_id,
                path=path,
            )
        )
        issues.extend(
            _validate_controller_ownership(
                phase,
                node=node,
                phase_id=phase_id,
                path=path,
            )
        )
        for agent_index, agent_entry in enumerate(phase.get("agents") or []):
            if not isinstance(agent_entry, dict):
                continue
            effective = {
                "allowed_state_updates": agent_entry.get(
                    "allowed_state_updates", phase.get("allowed_state_updates")
                ),
                "required_state_updates": agent_entry.get(
                    "required_state_updates", phase.get("required_state_updates", [])
                ),
                "state_update_types": agent_entry.get(
                    "state_update_types", phase.get("state_update_types", {})
                ),
                "state_update_enums": agent_entry.get(
                    "state_update_enums", phase.get("state_update_enums", {})
                ),
                "allowed_verdicts": agent_entry.get(
                    "allowed_verdicts", phase.get("allowed_verdicts")
                ),
                "unexpected_state_updates": agent_entry.get(
                    "unexpected_state_updates",
                    phase.get("unexpected_state_updates", "quarantine"),
                ),
                "evidence_routing": agent_entry.get(
                    "evidence_routing", phase.get("evidence_routing", "none")
                ),
            }
            issues.extend(
                _validate_result_contract_definition(
                    effective,
                    phase_id=phase_id,
                    path=f"{path} agents[{agent_index}]",
                )
            )
            if "controller_state_updates" in agent_entry:
                issues.append(WorkflowValidationIssue(
                    "controller_state_updates is no longer supported",
                    phase_id=phase_id,
                    path=f"{path} agents[{agent_index}]",
                ))
            if "controller_state_contract" in agent_entry:
                issues.append(WorkflowValidationIssue(
                    "nested agents cannot declare controller_state_contract",
                    phase_id=phase_id,
                    path=f"{path} agents[{agent_index}]",
                ))
            if (
                node.controller_state_contract is not None
                and "allowed_state_updates" in agent_entry
                and agent_entry.get("allowed_state_updates") is None
            ):
                issues.append(WorkflowValidationIssue(
                    "nested agent cannot override allowed_state_updates with null",
                    phase_id=phase_id,
                    path=f"{path} agents[{agent_index}]",
                ))
            nested_allowed = agent_entry.get(
                "allowed_state_updates",
                phase.get("allowed_state_updates"),
            )
            nested_allowed_set = (
                set(str(key) for key in nested_allowed)
                if isinstance(nested_allowed, list)
                else set()
            )
            overlap = node.controller_state_update_keys & nested_allowed_set
            if overlap:
                issues.append(WorkflowValidationIssue(
                    "nested agent allowed_state_updates overlap controller-owned "
                    f"fields: {', '.join(sorted(overlap))}",
                    phase_id=phase_id,
                    path=f"{path} agents[{agent_index}]",
                ))
        for pre_dispatch_index, agent_entry in enumerate(
            phase.get("pre_dispatch") or []
        ):
            if not isinstance(agent_entry, dict):
                continue
            effective = {
                "allowed_state_updates": agent_entry.get(
                    "allowed_state_updates", phase.get("allowed_state_updates")
                ),
                "required_state_updates": agent_entry.get(
                    "required_state_updates",
                    phase.get("required_state_updates", []),
                ),
                "state_update_types": agent_entry.get(
                    "state_update_types", phase.get("state_update_types", {})
                ),
                "state_update_enums": agent_entry.get(
                    "state_update_enums", phase.get("state_update_enums", {})
                ),
                "allowed_verdicts": agent_entry.get(
                    "allowed_verdicts", phase.get("allowed_verdicts")
                ),
                "unexpected_state_updates": agent_entry.get(
                    "unexpected_state_updates",
                    phase.get("unexpected_state_updates", "quarantine"),
                ),
            }
            issues.extend(
                _validate_result_contract_definition(
                    effective,
                    phase_id=phase_id,
                    path=f"{path} pre_dispatch[{pre_dispatch_index}]",
                )
            )

        phase_condition = phase.get("condition")
        if phase_condition is not None:
            condition_issue = validate_condition_expression(phase_condition)
            if condition_issue:
                issues.append(
                    WorkflowValidationIssue(
                        f"unsupported phase condition syntax: {condition_issue}",
                        phase_id=phase_id,
                        path=path,
                    )
                )
            else:
                for field in sorted(_condition_fields(str(phase_condition).strip())):
                    if field not in known_condition_fields:
                        issues.append(
                            WorkflowValidationIssue(
                                f"unresolvable phase condition field {field!r}",
                                phase_id=phase_id,
                                path=path,
                            )
                        )

        on_greenfield = phase.get("on_greenfield")
        if on_greenfield is not None:
            if not isinstance(on_greenfield, dict):
                issues.append(
                    WorkflowValidationIssue(
                        "phase.on_greenfield must be an object when present",
                        phase_id=phase_id,
                        path=path,
                    )
                )
            elif on_greenfield.get("action") not in {"skip_agent_proceed_to_next"}:
                issues.append(
                    WorkflowValidationIssue(
                        "phase.on_greenfield.action must be 'skip_agent_proceed_to_next'",
                        phase_id=phase_id,
                        path=path,
                    )
                )

        transitions = phase.get("transitions", [])
        if transitions is None:
            continue
        if not isinstance(transitions, list):
            issues.append(
                WorkflowValidationIssue(
                    "phase.transitions must be a list",
                    phase_id=phase_id,
                    path=path,
                )
            )
            continue

        for index, transition in enumerate(transitions):
            issues.extend(
                _validate_transition(
                    transition,
                    phase_id=phase_id,
                    transition_index=index,
                    known_phase_ids=phase_ids,
                    known_condition_fields=known_condition_fields,
                    path=path,
                )
            )

        policies = compiled_human_input.get(phase_id, ())
        if workflow_declares_human_input and phase.get("type") == "human_gate":
            issues.extend(_validate_human_gate_outcomes(
                phase_id=phase_id,
                transitions=transitions,
                policies=policies,
                path=path,
            ))
        elif any(isinstance(item, dict) and "outcome" in item for item in transitions):
            issues.append(WorkflowValidationIssue(
                "outcome is accepted only on human_gate transitions",
                phase_id=phase_id,
                path=path,
            ))

        if (
            workflow_declares_human_input
            and phase.get("type") == "agent"
            and isinstance(phase.get("allowed_state_updates"), list)
            and "escalation_question" in phase["allowed_state_updates"]
            and not policies
        ):
            issues.append(WorkflowValidationIssue(
                "question-capable provider requires at least one human_input policy after workflow opt-in",
                phase_id=phase_id,
                path=path,
            ))

    return WorkflowValidationReport(issues)


def _validate_required_controller_contracts(
    workflow: dict[str, Any],
    phases: list[Any],
    *,
    path: str,
) -> list[WorkflowValidationIssue]:
    issues: list[WorkflowValidationIssue] = []
    producers = [
        phase
        for phase in phases
        if isinstance(phase, dict)
        and is_controller_producing_phase(phase)
    ]
    if (
        producers
        and not isinstance(
            workflow.get("controller_state_contracts_file"),
            str,
        )
    ):
        issues.append(
            WorkflowValidationIssue(
                "controller-producing phases require "
                "controller_state_contracts_file",
                path=path,
            )
        )
    for phase in producers:
        phase_id = phase.get("id")
        phase_id = phase_id if isinstance(phase_id, str) else None
        expected = required_controller_contract_name(phase)
        actual = phase.get("controller_state_contract")
        for message in structural_phase_definition_errors(phase):
            issues.append(
                WorkflowValidationIssue(
                    message,
                    phase_id=phase_id,
                    path=path,
                )
            )
        if expected is None:
            issues.append(
                WorkflowValidationIssue(
                    "controller-producing phase has an unsupported role/type",
                    phase_id=phase_id,
                    path=path,
                )
            )
        elif actual != expected:
            issues.append(
                WorkflowValidationIssue(
                    f"required controller state contract {expected!r}; "
                    f"got {actual!r}",
                    phase_id=phase_id,
                    path=path,
                )
            )
    return issues


def _validate_result_contract_definition(
    contract: dict,
    *,
    phase_id: str,
    path: str,
) -> list[WorkflowValidationIssue]:
    issues: list[WorkflowValidationIssue] = []
    allowed = contract.get("allowed_state_updates")
    required = contract.get("required_state_updates", [])
    value_types = contract.get("state_update_types", {})
    value_enums = contract.get("state_update_enums", {})
    verdicts = contract.get("allowed_verdicts")
    unexpected = contract.get("unexpected_state_updates", "quarantine")
    evidence_routing = contract.get("evidence_routing", "none")

    if allowed is not None and (
        not isinstance(allowed, list)
        or not all(isinstance(key, str) and key for key in allowed)
    ):
        issues.append(WorkflowValidationIssue(
            "allowed_state_updates must be a list of non-empty strings",
            phase_id=phase_id,
            path=path,
        ))
        allowed_set: set[str] | None = set()
    else:
        allowed_set = set(allowed) if allowed is not None else None
        transaction_owned = (
            (allowed_set or set())
            & STORE_OWNED_TRANSACTION_KEYS
            - PROVIDER_CONTROL_INTENT_KEYS
        )
        for key in sorted(transaction_owned):
            issues.append(WorkflowValidationIssue(
                "allowed_state_updates contains transaction-owned key "
                f"{key!r}",
                phase_id=phase_id,
                path=path,
            ))

    if not isinstance(required, list) or not all(
        isinstance(key, str) and key for key in required
    ):
        issues.append(WorkflowValidationIssue(
            "required_state_updates must be a list of non-empty strings",
            phase_id=phase_id,
            path=path,
        ))
        required_set: set[str] = set()
    else:
        required_set = set(required)
    if allowed_set is None and required_set:
        issues.append(WorkflowValidationIssue(
            "required_state_updates requires an explicit allowed_state_updates list",
            phase_id=phase_id,
            path=path,
        ))
    elif allowed_set is not None and not required_set.issubset(allowed_set):
        issues.append(WorkflowValidationIssue(
            "required_state_updates must be a subset of allowed_state_updates",
            phase_id=phase_id,
            path=path,
        ))

    if not isinstance(value_types, dict):
        issues.append(WorkflowValidationIssue(
            "state_update_types must be an object",
            phase_id=phase_id,
            path=path,
        ))
    else:
        if allowed_set is not None and not set(value_types).issubset(allowed_set):
            issues.append(WorkflowValidationIssue(
                "state_update_types keys must be a subset of allowed_state_updates",
                phase_id=phase_id,
                path=path,
            ))
        for key, value_type in value_types.items():
            if value_type not in SUPPORTED_STATE_UPDATE_TYPES:
                issues.append(WorkflowValidationIssue(
                    f"unsupported state update type {value_type!r} for {key!r}",
                    phase_id=phase_id,
                    path=path,
                ))

    if not isinstance(value_enums, dict):
        issues.append(WorkflowValidationIssue(
            "state_update_enums must be an object",
            phase_id=phase_id,
            path=path,
        ))
    else:
        if allowed_set is not None and not set(value_enums).issubset(allowed_set):
            issues.append(WorkflowValidationIssue(
                "state_update_enums keys must be a subset of allowed_state_updates",
                phase_id=phase_id,
                path=path,
            ))
        for key, values in value_enums.items():
            if not isinstance(values, list) or not values:
                issues.append(WorkflowValidationIssue(
                    f"state_update_enums.{key} must be a non-empty list",
                    phase_id=phase_id,
                    path=path,
                ))

    if verdicts is not None:
        if not isinstance(verdicts, list) or not all(
            isinstance(verdict, str) and verdict for verdict in verdicts
        ):
            issues.append(WorkflowValidationIssue(
                "allowed_verdicts must be a list of non-empty strings",
                phase_id=phase_id,
                path=path,
            ))
        else:
            unsupported = set(verdicts) - ALLOWED_VERDICTS
            if unsupported:
                issues.append(WorkflowValidationIssue(
                    "allowed_verdicts contains unsupported verdict(s): "
                    + ", ".join(sorted(unsupported)),
                    phase_id=phase_id,
                    path=path,
                ))

    if unexpected not in {"reject", "quarantine"}:
        issues.append(WorkflowValidationIssue(
            "unexpected_state_updates must be 'reject' or 'quarantine'",
            phase_id=phase_id,
            path=path,
        ))
    if evidence_routing not in {"none", "requests", "finding_routes"}:
        issues.append(WorkflowValidationIssue(
            "evidence_routing must be 'none', 'requests', or 'finding_routes'",
            phase_id=phase_id,
            path=path,
        ))
    return issues


def _validate_controller_ownership(
    phase: dict[str, Any],
    *,
    node: PhaseNode,
    phase_id: str,
    path: str,
) -> list[WorkflowValidationIssue]:
    issues: list[WorkflowValidationIssue] = []
    if "controller_state_updates" in phase:
        issues.append(WorkflowValidationIssue(
            "controller_state_updates is no longer supported",
            phase_id=phase_id,
            path=path,
        ))

    contract = node.controller_state_contract
    if contract is None:
        return issues

    if "allowed_state_updates" not in phase:
        issues.append(WorkflowValidationIssue(
            "controller_state_contract requires an explicit "
            "allowed_state_updates list",
            phase_id=phase_id,
            path=path,
        ))
        allowed: set[str] = set()
    else:
        raw_allowed = phase.get("allowed_state_updates")
        if not isinstance(raw_allowed, list):
            issues.append(WorkflowValidationIssue(
                "controller_state_contract requires allowed_state_updates "
                "to be a list",
                phase_id=phase_id,
                path=path,
            ))
            allowed = set()
        else:
            allowed = set(str(key) for key in raw_allowed)

    overlap = contract.state_update_keys & allowed
    if overlap:
        issues.append(WorkflowValidationIssue(
            "controller state contract must not overlap allowed_state_updates: "
            + ", ".join(sorted(overlap)),
            phase_id=phase_id,
            path=path,
        ))

    on_greenfield = phase.get("on_greenfield")
    if (
        isinstance(on_greenfield, dict)
        and on_greenfield.get("action") == "skip_agent_proceed_to_next"
    ):
        issues.append(WorkflowValidationIssue(
            "skip_agent_proceed_to_next cannot bypass a controller state contract",
            phase_id=phase_id,
            path=path,
        ))
    return issues


def validate_condition_expression(condition: Any) -> str | None:
    """Return an issue message when a transition condition is unsupported."""
    if not isinstance(condition, str) or not condition.strip():
        return "condition must be a non-empty string"
    condition = condition.strip()
    return _validate_condition(condition)


def _validate_transition(
    transition: Any,
    *,
    phase_id: str,
    transition_index: int,
    known_phase_ids: set[str],
    known_condition_fields: set[str],
    path: str,
) -> list[WorkflowValidationIssue]:
    issues: list[WorkflowValidationIssue] = []
    if not isinstance(transition, dict):
        return [
            WorkflowValidationIssue(
                "transition must be an object",
                phase_id=phase_id,
                transition_index=transition_index,
                path=path,
            )
        ]

    for key in transition:
        if key not in SUPPORTED_TRANSITION_KEYS:
            issues.append(
                WorkflowValidationIssue(
                    f"unsupported transition key {key!r}",
                    phase_id=phase_id,
                    transition_index=transition_index,
                    path=path,
                )
            )

    target = transition.get("to")
    if not isinstance(target, str) or not target.strip():
        issues.append(
            WorkflowValidationIssue(
                "transition.to must be a non-empty string",
                phase_id=phase_id,
                transition_index=transition_index,
                path=path,
            )
        )
    elif target not in known_phase_ids and target not in RUNTIME_TERMINAL_TARGETS:
        issues.append(
            WorkflowValidationIssue(
                f"unknown transition target {target!r}",
                phase_id=phase_id,
                transition_index=transition_index,
                path=path,
            )
        )

    condition_issue = validate_condition_expression(transition.get("condition"))
    if condition_issue:
        issues.append(
            WorkflowValidationIssue(
                f"unsupported condition syntax: {condition_issue}",
                phase_id=phase_id,
                transition_index=transition_index,
                path=path,
            )
        )
    else:
        for field in sorted(_condition_fields(str(transition.get("condition")).strip())):
            if field not in known_condition_fields:
                issues.append(
                    WorkflowValidationIssue(
                        f"unresolvable condition field {field!r}",
                        phase_id=phase_id,
                        transition_index=transition_index,
                        path=path,
                    )
                )

    action = transition.get("action")
    if action is not None and not isinstance(action, str):
        issues.append(
            WorkflowValidationIssue(
                "transition.action must be a string when present",
                phase_id=phase_id,
                transition_index=transition_index,
                path=path,
            )
        )

    state_update = transition.get("state_update")
    if state_update is not None and not isinstance(state_update, dict):
        issues.append(
            WorkflowValidationIssue(
                "transition.state_update must be an object when present",
                phase_id=phase_id,
                transition_index=transition_index,
                path=path,
            )
        )

    outcome = transition.get("outcome")
    if outcome is not None and (not isinstance(outcome, str) or not outcome.strip()):
        issues.append(WorkflowValidationIssue(
            "transition.outcome must be a non-empty string when present",
            phase_id=phase_id,
            transition_index=transition_index,
            path=path,
        ))

    return issues


def _validate_human_gate_outcomes(
    *,
    phase_id: str,
    transitions: object,
    policies: tuple[HumanInputPolicy, ...],
    path: str,
) -> list[WorkflowValidationIssue]:
    if not isinstance(transitions, list):
        return []
    issues: list[WorkflowValidationIssue] = []
    if len(policies) != 1:
        issues.append(WorkflowValidationIssue(
            "human_gate requires exactly one human_input policy",
            phase_id=phase_id,
            path=path,
        ))
    policy = policies[0] if len(policies) == 1 else None
    if policy is not None and policy.resolution_handler != "gate_outcome":
        issues.append(WorkflowValidationIssue(
            "human_gate resolution_handler must be gate_outcome",
            phase_id=phase_id,
            path=path,
        ))

    outcomes: dict[str, tuple[int, str]] = {}
    for index, transition in enumerate(transitions):
        if not isinstance(transition, dict):
            continue
        outcome = transition.get("outcome")
        if outcome is None:
            issues.append(WorkflowValidationIssue(
                "human_gate transitions require outcome",
                phase_id=phase_id, transition_index=index, path=path,
            ))
            continue
        if not isinstance(outcome, str) or not outcome.strip():
            continue
        if outcome in outcomes:
            issues.append(WorkflowValidationIssue(
                "human_gate transition outcome must be unique",
                phase_id=phase_id, transition_index=index, path=path,
            ))
        outcomes[outcome] = (index, str(transition.get("to") or ""))
        if transition.get("condition") != f"human_input_outcome = {outcome}":
            issues.append(WorkflowValidationIssue(
                "human_gate outcome must match its exact condition",
                phase_id=phase_id, transition_index=index, path=path,
            ))

    expected_outcomes = {"approved", "rejected"}
    if len(outcomes) != 2 or set(outcomes) != expected_outcomes:
        issues.append(WorkflowValidationIssue(
            "human_gate transitions require exact approved/rejected outcomes",
            phase_id=phase_id, path=path,
        ))

    option_outcomes: dict[str, str] = {}
    if policy is not None:
        for option in policy.options:
            if option.outcome is not None and option.next_phase is not None:
                if option.outcome in option_outcomes:
                    issues.append(WorkflowValidationIssue(
                        "human_gate option outcome must be unique",
                        phase_id=phase_id,
                        path=path,
                    ))
                option_outcomes[option.outcome] = option.next_phase
                route_error = gate_outcome_route_error(
                    option.outcome,
                    option.next_phase,
                )
                if route_error is not None:
                    issues.append(WorkflowValidationIssue(
                        route_error,
                        phase_id=phase_id,
                        path=path,
                    ))
        if len(policy.options) != 2 or set(option_outcomes) != expected_outcomes:
            issues.append(WorkflowValidationIssue(
                "human_gate options require exact approved/rejected outcomes",
                phase_id=phase_id, path=path,
            ))
        for outcome, (_, target) in outcomes.items():
            if outcome in option_outcomes and option_outcomes[outcome] != target:
                issues.append(WorkflowValidationIssue(
                    "human_gate outcome target must match its option next_phase",
                    phase_id=phase_id, path=path,
                ))
    return issues


def _phase_condition_fields(phase: PhaseNode) -> set[str]:
    allowed = phase.allowed_state_updates
    fields = (
        set(str(key) for key in allowed)
        if isinstance(allowed, list)
        else set()
    )
    fields.update(phase.controller_state_update_keys)
    fields.update(_output_fields(phase.outputs or []))
    fields.update(_nested_agent_output_fields(phase))
    transitions = phase.transitions or []
    if isinstance(transitions, list):
        for transition in transitions:
            if isinstance(transition, dict) and isinstance(transition.get("state_update"), dict):
                fields.update(str(key) for key in transition["state_update"])
    return fields


def _nested_agent_output_fields(phase: PhaseNode) -> set[str]:
    fields: set[str] = set()
    for agent in phase.agents or []:
        if isinstance(agent, dict):
            fields.update(_output_fields(agent.get("outputs") or []))
    return fields


def _output_fields(outputs: list[Any]) -> set[str]:
    fields: set[str] = set()
    for output in outputs:
        if isinstance(output, dict):
            fields.update(str(key) for key in output)
    return fields


def _condition_fields(condition: str) -> set[str]:
    if condition == "always":
        return set()

    for operator in ("AND", "OR"):
        if re.search(rf"\b{operator}\b", condition):
            fields: set[str] = set()
            for part in re.split(rf"\b{operator}\b", condition):
                fields.update(_condition_fields(part.strip()))
            return fields

    not_match = re.fullmatch(r"NOT\s+(.+)", condition)
    if not_match:
        return _condition_fields(not_match.group(1).strip())

    match = re.fullmatch(r"verdict\s*=\s*\S+", condition)
    if match:
        return {"verdict"}

    match = re.fullmatch(r"([\w.\-]+)\s+in\s+\[([^\]]*)\]", condition)
    if match:
        return {match.group(1)}

    match = re.fullmatch(r"([\w.\-]+)\s*(>=|<=|>|<)\s*([\w.\-]+)", condition)
    if match:
        fields = {match.group(1)}
        right = match.group(3)
        try:
            float(right)
        except ValueError:
            fields.add(right)
        return fields

    match = re.fullmatch(r"([\w.\-]+)\s*=\s*.+", condition)
    if match:
        return {match.group(1)}

    if re.fullmatch(r"[\w.\-]+", condition):
        return {condition}

    return set()


def _validate_condition(condition: str) -> str | None:
    if condition == "always":
        return None

    for operator in ("AND", "OR"):
        if re.search(rf"\b{operator}\b", condition):
            parts = re.split(rf"\b{operator}\b", condition)
            if any(not part.strip() for part in parts):
                return f"incomplete {operator} expression {condition!r}"
            for part in parts:
                issue = _validate_condition(part.strip())
                if issue:
                    return issue
            return None

    not_match = re.fullmatch(r"NOT\s+(.+)", condition)
    if not_match:
        inner = not_match.group(1).strip()
        if not inner:
            return f"incomplete NOT expression {condition!r}"
        return _validate_condition(inner)

    if re.fullmatch(r"verdict\s*=\s*\S+", condition):
        return None

    in_match = re.fullmatch(r"([\w.\-]+)\s+in\s+\[([^\]]*)\]", condition)
    if in_match:
        values = [value.strip() for value in in_match.group(2).split(",")]
        if not values or any(not value for value in values):
            return f"empty value in membership expression {condition!r}"
        return None

    if re.fullmatch(r"[\w.\-]+\s*(>=|<=|>|<)\s*[\w.\-]+", condition):
        return None

    if re.fullmatch(r"[\w.\-]+\s*=\s*.+", condition):
        return None

    if re.fullmatch(r"[\w.\-]+", condition):
        return None

    return f"unrecognized expression {condition!r}"
