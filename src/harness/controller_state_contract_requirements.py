"""Single source of truth for controller-producing workflow roles."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


REQUIRED_CONTROLLER_CONTRACTS: Mapping[str, str] = MappingProxyType(
    {
        "phase1-lexicon": "spec_lexicon",
        "phase1-understanding": "understanding",
        "phase2-decide": "feasibility_structural",
        "phase2-tracker-alignment": "intent_alignment_structural",
        "phase3-tasks-lexicon": "tasks_lexicon",
        "phase3-understanding": "understanding",
        "phase3-consensus-tasks-lexicon": "tasks_lexicon",
    }
)

_LEXICON_CONTRACTS: Mapping[str, str] = MappingProxyType(
    {
        "spec": "spec_lexicon",
        "tasks": "tasks_lexicon",
    }
)
CONTROLLER_PRODUCING_TYPES = frozenset(
    {"deterministic_lexicon", "deterministic_understanding"}
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
    return None
