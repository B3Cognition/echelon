"""Typed provider assignments that are created outside the workflow graph."""

from __future__ import annotations

from dataclasses import dataclass

from harness.provider_output_publication import (
    ProviderArtifactContract,
    ProviderArtifactContractError,
    compile_provider_artifact_contract,
)


@dataclass(frozen=True)
class CompiledProviderAssignment:
    assignment_id: str
    agent_id: str
    mode: str | None
    contract: ProviderArtifactContract


_RUNTIME_ASSIGNMENTS: dict[str, tuple[str, str | None, str]] = {
    "phase3-consensus/sage-work-assessment": (
        "echelon.sage",
        "WORK_ASSESSMENT",
        "result_only",
    ),
    "phase3-consensus/sage-decision-proposal": (
        "echelon.sage",
        "DECISION_PROPOSAL",
        "publish",
    ),
    "commander/routing-judgment": (
        "echelon.commander",
        "ROUTING_JUDGMENT",
        "result_only",
    ),
    "commander/human-resolution": (
        "echelon.commander",
        "HUMAN_RESOLUTION",
        "result_only",
    ),
    "provider/echelon-result-repair": (
        "echelon.result-repair",
        "RESULT_REPAIR",
        "result_only",
    ),
}


def runtime_provider_assignment(
    assignment_id: str,
    *,
    artifact_path: str | None = None,
) -> CompiledProviderAssignment:
    """Return one explicit non-graph provider assignment."""
    try:
        agent_id, mode, contract_mode = _RUNTIME_ASSIGNMENTS[assignment_id]
    except KeyError as exc:
        raise ProviderArtifactContractError(
            f"unknown runtime provider assignment {assignment_id!r}"
        ) from exc
    artifacts: list[dict[str, str]] = []
    if artifact_path is not None:
        if assignment_id != "phase3-consensus/sage-decision-proposal":
            raise ProviderArtifactContractError(
                f"runtime provider assignment {assignment_id!r} does not accept "
                "an artifact path"
            )
        artifacts.append(
            {
                "root": "proposal",
                "path": artifact_path,
                "kind": "file",
                "requirement": "optional",
            }
        )
    return CompiledProviderAssignment(
        assignment_id=assignment_id,
        agent_id=agent_id,
        mode=mode,
        contract=compile_provider_artifact_contract(
            {"mode": contract_mode, "artifacts": artifacts},
            assignment_id=assignment_id,
        ),
    )
