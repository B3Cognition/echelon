"""Deterministic validation for Echelon workflow definitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml

from harness.phase_graph import PhaseGraph


SUPPORTED_TRANSITION_KEYS = frozenset({
    "to",
    "condition",
    "action",
    "state_update",
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

    try:
        graph = PhaseGraph(definition_path, extension_yml_path)
    except Exception as exc:
        return WorkflowValidationReport([
            WorkflowValidationIssue(f"cannot load phase graph: {exc}", path=path)
        ])

    phase_ids = set(graph.all_phase_ids())
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
                    path=path,
                )
            )

    return WorkflowValidationReport(issues)


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
    elif target not in known_phase_ids:
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

    return issues


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
