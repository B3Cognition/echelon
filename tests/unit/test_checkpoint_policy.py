from pathlib import Path

import pytest
import yaml

from harness.checkpoint_policy import (
    CheckpointPolicyError,
    checkpoint_additional_owned_paths,
    phase_checkpoint_policy,
)
from harness.human_input import (
    HumanInputOption,
    HumanInputPolicyRegistry,
    RecommendationEvidence,
    controller_safeguard_policies,
)
from harness.phase_graph import PhaseGraph


def _graph(tmp_path: Path, phase: dict[str, object]) -> PhaseGraph:
    definition = tmp_path / "definition.yaml"
    definition.write_text(
        yaml.safe_dump({"phases": [phase]}, sort_keys=False),
        encoding="utf-8",
    )
    return PhaseGraph(definition)


def test_policy_resolver_returns_declared_policy(tmp_path: Path) -> None:
    graph = _graph(tmp_path, {
        "id": "phase1-discover",
        "type": "terminal",
        "checkpoint": "required",
        "rewind": "supported",
    })

    assert phase_checkpoint_policy(graph, "phase1-discover") == (
        "required",
        "supported",
    )


@pytest.mark.parametrize(
    "phase",
    [
        {"id": "phase1-discover", "type": "terminal"},
        {
            "id": "phase1-discover",
            "type": "terminal",
            "checkpoint": "sometimes",
            "rewind": "supported",
        },
    ],
)
def test_policy_resolver_rejects_missing_or_invalid_runtime_policy(
    tmp_path: Path,
    phase: dict[str, object],
) -> None:
    graph = _graph(tmp_path, phase)

    with pytest.raises(CheckpointPolicyError, match="checkpoint policy"):
        phase_checkpoint_policy(graph, "phase1-discover")


def test_policy_resolver_rejects_unknown_phase(tmp_path: Path) -> None:
    graph = _graph(tmp_path, {
        "id": "phase1-discover",
        "type": "terminal",
        "checkpoint": "required",
        "rewind": "supported",
    })

    with pytest.raises(CheckpointPolicyError, match="unknown phase"):
        phase_checkpoint_policy(graph, "phase1-missing")


def test_constitution_adds_only_canonical_constitution_path(tmp_path: Path) -> None:
    assert checkpoint_additional_owned_paths(
        tmp_path,
        "phase1-constitution",
        {"spec_id": "001-demo"},
    ) == (tmp_path / ".echelon" / "constitution.md",)


def test_ordinary_phase_has_no_additional_owned_paths(tmp_path: Path) -> None:
    assert checkpoint_additional_owned_paths(
        tmp_path,
        "phase1-discover",
        {"spec_id": "001-demo"},
    ) == ()


def test_registered_checkpoint_assess_preparer_describes_accepted_debt() -> None:
    graph = PhaseGraph(
        Path(__file__).resolve().parents[2]
        / "runtime"
        / "workflow"
        / "definition.yaml"
    )
    registry = graph.human_input_policy_registry()
    authorization_digest = "a" * 64

    prepared = registry.prepare_controller(
        source_kind="human_gate",
        producer_id="checkpoint-assess",
        reason_code="checkpoint_assess_decision_required",
        phase_id="checkpoint-assess",
        question="Review the current Phase 1 checkpoint authority.",
        source_state_revision=12,
        authority_kind="accepted_with_debt",
        authority_evidence=(
            RecommendationEvidence(
                id="checkpoint-assess:accepted-debt",
                kind="accepted_with_debt",
                reference="state:spec_quality_debt_authorization",
                digest=authorization_digest,
            ),
            RecommendationEvidence(
                id="checkpoint-assess:quality-gates",
                kind="quality_gate_failure",
                reference="specs/001-demo/quality-gates.md",
                digest="b" * 64,
            ),
        ),
        accepted_debt_resolver="user",
        authorization_digest=authorization_digest,
    )

    assert prepared.recommended_option_id == "approve"
    assert "accepted_with_debt" in prepared.recommendation_rationale
    assert "user" in prepared.recommendation_rationale
    assert authorization_digest in prepared.recommendation_rationale
    assert any(
        evidence.kind == "quality_gate_failure"
        for evidence in prepared.recommendation_evidence
    )


def test_registered_phase_dispatch_preparer_uses_document_order() -> None:
    registry = HumanInputPolicyRegistry(controller_safeguard_policies())
    option_contract = tuple(
        HumanInputOption(
            id=issue_id,
            label=f"{issue_id}: {title}",
            description=f"Evidence-backed suggestion for {issue_id}.",
            recommended=False,
            risk_level="medium",
            next_phase="phase1-what",
            outcome=None,
        )
        for issue_id, title in (
            ("ISS-010", "First in the document"),
            ("ISS-001", "Lower numeric identifier"),
        )
    )

    prepared = registry.prepare_controller(
        source_kind="controller_safeguard",
        producer_id="phase_dispatch_limit",
        reason_code="phase_dispatch_limit",
        phase_id="phase1-why2",
        question="Select one sealed evidence-backed issue resolution.",
        source_state_revision=8,
        option_contract=option_contract,
    )

    assert prepared.recommended_option_id == "ISS-010"
    assert "first eligible entry" in prepared.recommendation_rationale
    assert [option.id for option in prepared.options if option.recommended] == [
        "ISS-010"
    ]
    assert prepared.recommendation_evidence[0].kind == "phase_dispatch_issue"
