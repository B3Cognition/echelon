"""Single source of truth for controller-producing workflow roles."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


REQUIRED_CONTROLLER_CONTRACTS: Mapping[str, str] = MappingProxyType(
    {
        "phase1-lexicon": "spec_lexicon",
        "phase1-understanding": "understanding",
        "phase1-why2": "phase1_quality_certificate",
        "phase2-decide": "feasibility_authoring_verdict",
        "phase2-feasibility-structural": "feasibility_structural",
        "phase2-tracker-alignment": "intent_alignment_authoring_verdict",
        "phase2-intent-alignment-structural": "intent_alignment_structural",
        "phase3-tasks-lexicon": "tasks_lexicon",
        "phase3-understanding": "understanding",
        "phase3-consensus": "consensus_gate",
        "phase3-consensus-tasks-lexicon": "tasks_lexicon",
    }
)

_LEXICON_CONTRACTS: Mapping[str, str] = MappingProxyType(
    {
        "spec": "spec_lexicon",
        "tasks": "tasks_lexicon",
    }
)
_STRUCTURAL_CONTRACTS: Mapping[str, str] = MappingProxyType(
    {
        "feasibility": "feasibility_structural",
        "intent-alignment-check": "intent_alignment_structural",
    }
)
CONTROLLER_PRODUCING_TYPES = frozenset(
    {
        "deterministic_lexicon",
        "deterministic_structural",
        "deterministic_understanding",
    }
)


def is_controller_producing_phase(phase: Mapping[str, object]) -> bool:
    phase_id = phase.get("id")
    phase_type = phase.get("type")
    return (
        isinstance(phase_id, str)
        and phase_id in REQUIRED_CONTROLLER_CONTRACTS
    ) or phase_type in CONTROLLER_PRODUCING_TYPES


def required_controller_contract_name(
    phase: Mapping[str, object],
) -> str | None:
    """Return the exact contract required by a known role or producer type."""
    phase_id = phase.get("id")
    if isinstance(phase_id, str):
        named = REQUIRED_CONTROLLER_CONTRACTS.get(phase_id)
        if named is not None:
            return named

    phase_type = phase.get("type")
    if phase_type == "deterministic_understanding":
        return "understanding"
    if phase_type == "deterministic_lexicon":
        artifact = phase.get("lexicon_artifact")
        return (
            _LEXICON_CONTRACTS.get(artifact)
            if isinstance(artifact, str)
            else None
        )
    if phase_type == "deterministic_structural":
        artifact = phase.get("structural_artifact")
        return (
            _STRUCTURAL_CONTRACTS.get(artifact)
            if isinstance(artifact, str)
            else None
        )
    return None


def structural_phase_definition_errors(
    phase: Mapping[str, object],
) -> tuple[str, ...]:
    """Return deterministic definition errors for an explicit structural node."""
    if phase.get("type") != "deterministic_structural":
        return ()
    errors: list[str] = []
    artifact = phase.get("structural_artifact")
    if not isinstance(artifact, str) or artifact not in _STRUCTURAL_CONTRACTS:
        errors.append(
            "deterministic_structural requires structural_artifact to be "
            "'feasibility' or 'intent-alignment-check'"
        )
    if phase.get("agent") is not None:
        errors.append("deterministic_structural must not declare agent")
    if phase.get("agents", []) != []:
        errors.append("deterministic_structural must declare no agents")
    if phase.get("allowed_state_updates") != []:
        errors.append(
            "deterministic_structural requires empty allowed_state_updates"
        )
    conditions = {
        transition.get("condition")
        for transition in phase.get("transitions", [])
        if isinstance(transition, Mapping)
    } if isinstance(phase.get("transitions", []), list) else set()
    for action in ("repair", "block"):
        expected = f"structural_action = {action}"
        if expected not in conditions:
            errors.append(
                f"deterministic_structural requires transition condition {expected!r}"
            )
    if not any(
        isinstance(condition, str)
        and "structural_action in [proceed, proceed_with_warning]" in condition
        for condition in conditions
    ):
        errors.append(
            "deterministic_structural requires a certified-forward transition"
        )
    return tuple(errors)
