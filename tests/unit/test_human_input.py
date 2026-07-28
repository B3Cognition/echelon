"""Tests for the closed human-input policy registry."""

import pytest

from harness.human_input import (
    HumanInputOption,
    HumanInputPolicy,
    HumanInputPolicyError,
    HumanInputPolicyRegistry,
    select_initial_decision_status,
)


def _provider_policy(*, reason_code: str = "human_clarification_required") -> HumanInputPolicy:
    return HumanInputPolicy(
        source_kind="provider_escalation",
        producer_id="phase1-investigate",
        reason_code=reason_code,
        classification="material",
        semi_policy="auto_if_recommended_low_risk",
        resolution_handler="clarification_resume",
        allow_free_text=True,
        allowed_phase_ids=frozenset({"phase1-investigate"}),
        allowed_target_phases=frozenset({"phase1-what"}),
        context_state_keys=("user_message", "phase"),
        context_paths=("{staging_dir}/user-intent.md",),
        options=(),
    )


def _gate_policy(*, options: tuple[HumanInputOption, ...] | None = None) -> HumanInputPolicy:
    return HumanInputPolicy(
        source_kind="human_gate",
        producer_id="checkpoint-plan",
        reason_code="checkpoint_plan_decision_required",
        classification="operational",
        semi_policy="auto_if_recommended_low_risk",
        resolution_handler="gate_outcome",
        allow_free_text=False,
        allowed_phase_ids=frozenset({"checkpoint-plan"}),
        allowed_target_phases=frozenset({"phase4-document", "terminal-blocked"}),
        context_state_keys=("user_message", "phase", "quality_scores"),
        context_paths=("{spec_dir}/plan.md",),
        options=options
        or (
            HumanInputOption(
                id="approve",
                label="Approve",
                description="Continue to finalization.",
                recommended=True,
                risk_level="low",
                next_phase="phase4-document",
                outcome="approved",
            ),
            HumanInputOption(
                id="reject",
                label="Reject",
                description="Stop for plan revision.",
                recommended=False,
                risk_level="low",
                next_phase="terminal-blocked",
                outcome="rejected",
            ),
        ),
    )


def test_registry_prepares_exact_provider_policy_without_provider_policy_authority() -> None:
    policy = _provider_policy()
    access_policy = HumanInputPolicy(
        **{
            **policy.__dict__,
            "reason_code": "investigation_access_required",
            "classification": "external_prerequisite",
        }
    )
    registry = HumanInputPolicyRegistry((policy, access_policy))

    access_policy = registry.lookup(
        "provider_escalation",
        "phase1-investigate",
        "investigation_access_required",
    )
    assert access_policy.classification == "external_prerequisite"

    request = registry.prepare(
        source_kind="provider_escalation",
        producer_id="phase1-investigate",
        phase_id="phase1-investigate",
        reason_code="human_clarification_required",
        question="Which scope should the investigation use?",
        recommended_answer="Use the existing product boundary.",
        risk_level="low",
        source_state_revision=7,
    )

    assert request.classification == "material"
    assert request.resolution_handler == "clarification_resume"
    assert request.question == "Which scope should the investigation use?"
    assert select_initial_decision_status("semi", registry.lookup("provider_escalation", "phase1-investigate", "human_clarification_required"), request) == "pending"

    with pytest.raises(HumanInputPolicyError, match="policy-owned"):
        registry.prepare(
            source_kind="provider_escalation",
            producer_id="phase1-investigate",
            phase_id="phase1-investigate",
            reason_code="human_clarification_required",
            question="Which scope should the investigation use?",
            source_state_revision=7,
            classification="operational",
        )


def test_registry_prepares_gate_options_from_the_exact_policy() -> None:
    registry = HumanInputPolicyRegistry((_gate_policy(),))

    request = registry.prepare(
        source_kind="human_gate",
        producer_id="checkpoint-plan",
        phase_id="checkpoint-plan",
        reason_code="checkpoint_plan_decision_required",
        question="Approve this plan?",
        source_state_revision=4,
    )

    assert tuple(option.outcome for option in request.options) == ("approved", "rejected")
    assert request.options[0].next_phase == "phase4-document"
    policy = registry.lookup("human_gate", "checkpoint-plan", "checkpoint_plan_decision_required")
    assert select_initial_decision_status("guided", policy, request) == "awaiting_human"


def test_registry_rejects_duplicate_and_unknown_exact_keys() -> None:
    policy = _provider_policy()

    with pytest.raises(HumanInputPolicyError, match="duplicate human input policy"):
        HumanInputPolicyRegistry((policy, policy))

    registry = HumanInputPolicyRegistry((policy,))
    with pytest.raises(HumanInputPolicyError, match="unknown human input policy"):
        registry.lookup("provider_escalation", "phase1-investigate", "unknown_reason")


def test_policy_rejects_duplicate_option_ids_and_multiple_recommendations() -> None:
    approve = HumanInputOption(
        id="approve",
        label="Approve",
        description="Continue.",
        recommended=True,
        risk_level="low",
        next_phase="phase4-document",
        outcome="approved",
    )

    with pytest.raises(HumanInputPolicyError, match="duplicate option id"):
        _gate_policy(options=(approve, approve))

    with pytest.raises(HumanInputPolicyError, match="at most one recommended"):
        _gate_policy(
            options=(
                approve,
                HumanInputOption(
                    id="reject",
                    label="Reject",
                    description="Stop.",
                    recommended=True,
                    risk_level="low",
                    next_phase="terminal-blocked",
                    outcome="rejected",
                ),
            )
        )

    with pytest.raises(HumanInputPolicyError, match="duplicate human_gate option outcome"):
        _gate_policy(
            options=(
                approve,
                HumanInputOption(
                    id="approve-alternate",
                    label="Approve with conditions",
                    description="Continue with conditions.",
                    recommended=False,
                    risk_level="medium",
                    next_phase="phase4-document",
                    outcome="approved",
                ),
            )
        )


def test_registry_rejects_malformed_risk_and_invalid_request_bounds() -> None:
    with pytest.raises(HumanInputPolicyError, match="risk_level"):
        HumanInputOption(
            id="approve",
            label="Approve",
            description="Continue.",
            recommended=True,
            risk_level="urgent",  # type: ignore[arg-type]
            next_phase="phase4-document",
            outcome="approved",
        )

    registry = HumanInputPolicyRegistry((_provider_policy(),))
    arguments = {
        "source_kind": "provider_escalation",
        "producer_id": "phase1-investigate",
        "phase_id": "phase1-investigate",
        "reason_code": "human_clarification_required",
        "question": "x" * 4_001,
        "source_state_revision": 0,
    }
    with pytest.raises(HumanInputPolicyError, match="4,000"):
        registry.prepare(**arguments)

    arguments["question"] = "Please decide."
    for revision in (-1, True):
        arguments["source_state_revision"] = revision
        with pytest.raises(HumanInputPolicyError, match="source_state_revision"):
            registry.prepare(**arguments)
