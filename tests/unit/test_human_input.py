"""Tests for the closed human-input policy registry."""

from dataclasses import replace

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
        recommendation_mode="controller",
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
        recommendation_mode="static",
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
    assert select_initial_decision_status("semi", registry.lookup("provider_escalation", "phase1-investigate", "human_clarification_required"), request) == "awaiting_human"

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


def test_registry_prepares_normalized_provider_dynamic_options() -> None:
    policy = HumanInputPolicy(
        **{
            **_provider_policy().__dict__,
            "classification": "operational",
        }
    )
    registry = HumanInputPolicyRegistry((policy,))

    request = registry.prepare(
        source_kind="provider_escalation",
        producer_id="phase1-investigate",
        phase_id="phase1-investigate",
        reason_code="human_clarification_required",
        question="Choose the next investigation step.",
        options=[
            {
                "id": "  use-api  ",
                "label": "Use API access",
                "description": "Query the approved API.",
                "recommended": True,
                "risk_level": None,
                "next_phase": " phase1-what ",
            },
            {
                "id": "manual",
                "label": "Use manual evidence",
                "description": "Continue with public evidence.",
                "recommended": False,
                "risk_level": "medium",
                "next_phase": "phase1-what",
            },
        ],
        risk_level="low",
        source_state_revision=8,
    )

    assert request.options[0].id == "use-api"
    assert request.options[0].next_phase == "phase1-what"
    assert request.options[0].outcome is None
    assert select_initial_decision_status("semi", policy, request) == "pending"


@pytest.mark.parametrize(
    "options, match",
    [
        ([{"id": "one", "label": "One", "description": "First.", "recommended": True, "risk_level": "low", "next_phase": "phase1-what", "outcome": "approved"}], "outcome"),
        ([{"id": "one", "label": "One", "description": "First.", "recommended": True, "risk_level": "low", "next_phase": "phase1-what"}, {"id": "one", "label": "Two", "description": "Second.", "recommended": False, "risk_level": "low", "next_phase": "phase1-what"}], "duplicate option id"),
        ([{"id": "one", "label": "Same", "description": "First.", "recommended": True, "risk_level": "low", "next_phase": "phase1-what"}, {"id": "two", "label": "Same", "description": "Second.", "recommended": False, "risk_level": "low", "next_phase": "phase1-what"}], "duplicate option label"),
        ([{"id": "one", "label": "two", "description": "First.", "recommended": True, "risk_level": "low", "next_phase": "phase1-what"}, {"id": "two", "label": "Two", "description": "Second.", "recommended": False, "risk_level": "low", "next_phase": "phase1-what"}], "option label conflicts"),
        ([{"id": "one", "label": "One", "description": "First.", "recommended": True, "risk_level": "low", "next_phase": "terminal-blocked"}], "allowed_target_phases"),
    ],
)
def test_registry_rejects_invalid_provider_dynamic_options(options: list[dict], match: str) -> None:
    registry = HumanInputPolicyRegistry((_provider_policy(),))

    with pytest.raises(HumanInputPolicyError, match=match):
        registry.prepare(
            source_kind="provider_escalation",
            producer_id="phase1-investigate",
            phase_id="phase1-investigate",
            reason_code="human_clarification_required",
            question="Choose the next investigation step.",
            options=options,
            source_state_revision=8,
        )


def test_registry_allows_a_provider_option_whose_own_id_is_its_label() -> None:
    registry = HumanInputPolicyRegistry((_provider_policy(),))

    request = registry.prepare(
        source_kind="provider_escalation",
        producer_id="phase1-investigate",
        phase_id="phase1-investigate",
        reason_code="human_clarification_required",
        question="Choose the next investigation step.",
        options=[
            {
                "id": "continue",
                "label": "continue",
                "description": "Continue with the bounded investigation.",
                "recommended": True,
                "risk_level": "low",
                "next_phase": "phase1-what",
            }
        ],
        source_state_revision=8,
    )

    assert request.options[0].id == request.options[0].label == "continue"


def test_semi_requires_an_operational_low_risk_recommendation() -> None:
    policy = _gate_policy(
        options=(
            HumanInputOption(
                id="approve",
                label="Approve",
                description="Continue.",
                recommended=True,
                risk_level=None,
                next_phase="phase4-document",
                outcome="approved",
            ),
            HumanInputOption(
                id="reject",
                label="Reject",
                description="Stop.",
                recommended=False,
                risk_level="low",
                next_phase="terminal-blocked",
                outcome="rejected",
            ),
        )
    )
    registry = HumanInputPolicyRegistry((policy,))
    request = registry.prepare(
        source_kind="human_gate",
        producer_id="checkpoint-plan",
        phase_id="checkpoint-plan",
        reason_code="checkpoint_plan_decision_required",
        question="Approve this plan?",
        risk_level="low",
        source_state_revision=8,
    )

    assert select_initial_decision_status("semi", policy, request) == "pending"

    material_policy = HumanInputPolicy(**{**policy.__dict__, "classification": "material"})
    assert select_initial_decision_status("semi", material_policy, request) == "awaiting_human"


@pytest.mark.parametrize(
    "classification, expected_status",
    [
        ("operational", "pending"),
        ("material", "pending"),
        ("external_prerequisite", "awaiting_human"),
    ],
)
def test_banzai_routes_project_decisions_but_not_external_prerequisites(
    classification: str,
    expected_status: str,
) -> None:
    policy = HumanInputPolicy(
        **{**_provider_policy().__dict__, "classification": classification}
    )
    registry = HumanInputPolicyRegistry((policy,))
    request = registry.prepare(
        source_kind="provider_escalation",
        producer_id="phase1-investigate",
        phase_id="phase1-investigate",
        reason_code="human_clarification_required",
        question="Choose the next investigation step.",
        source_state_revision=9,
    )

    assert select_initial_decision_status("banzai", policy, request) == expected_status


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


def test_prepared_choice_requires_one_recommendation_and_evidence() -> None:
    registry = HumanInputPolicyRegistry((_gate_policy(),))
    prepared_choice = registry.prepare(
        source_kind="human_gate",
        producer_id="checkpoint-plan",
        phase_id="checkpoint-plan",
        reason_code="checkpoint_plan_decision_required",
        question="Approve this plan?",
        source_state_revision=4,
    )

    with pytest.raises(HumanInputPolicyError, match="exactly one option"):
        replace(
            prepared_choice,
            options=tuple(
                replace(option, recommended=False)
                for option in prepared_choice.options
            ),
        )


def test_human_only_free_text_requires_action_and_is_not_automatic() -> None:
    registry = HumanInputPolicyRegistry((_provider_policy(),))
    prepared_free_text = registry.prepare(
        source_kind="provider_escalation",
        producer_id="phase1-investigate",
        phase_id="phase1-investigate",
        reason_code="human_clarification_required",
        question="Which scope should the investigation use?",
        recommended_answer="Use the existing product boundary.",
        risk_level="low",
        source_state_revision=7,
    )

    request = replace(
        prepared_free_text,
        recommended_answer=None,
        recommended_action='Run echelon spec resume "<answer>" with the requested value.',
        automatic_eligible=False,
    )

    assert request.recommended_action.startswith("Run echelon spec resume")


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


def test_registry_rejects_choice_options_with_a_free_text_recommendation() -> None:
    registry = HumanInputPolicyRegistry((_provider_policy(),))

    with pytest.raises(
        HumanInputPolicyError,
        match="recommended_answer.*options|options.*recommended_answer",
    ):
        registry.prepare(
            source_kind="provider_escalation",
            producer_id="phase1-investigate",
            phase_id="phase1-investigate",
            reason_code="human_clarification_required",
            question="Choose one bounded investigation route.",
            options=[
                {
                    "id": "use-api",
                    "label": "Use API access",
                    "description": "Query the approved API.",
                    "recommended": False,
                    "risk_level": "medium",
                    "next_phase": "phase1-what",
                }
            ],
            recommended_answer="Ignore the choice and use free text.",
            risk_level="medium",
            source_state_revision=8,
        )


@pytest.mark.parametrize(
    ("field", "overlong_value"),
    [
        ("id", "i" * 5_000),
        ("label", "l" * 5_000),
        ("description", "d" * 5_000),
        ("next_phase", "p" * 5_000),
        ("outcome", "o" * 5_000),
    ],
)
def test_human_input_option_bounds_every_string_field(
    field: str,
    overlong_value: str,
) -> None:
    values = {
        "id": "approve",
        "label": "Approve",
        "description": "Continue.",
        "recommended": False,
        "risk_level": "low",
        "next_phase": "phase4-document",
        "outcome": "approved",
    }
    values[field] = overlong_value

    with pytest.raises(HumanInputPolicyError, match=field):
        HumanInputOption(**values)


def test_registry_bounds_recommendation_option_count_and_utf8_question() -> None:
    registry = HumanInputPolicyRegistry((_provider_policy(),))
    base = {
        "source_kind": "provider_escalation",
        "producer_id": "phase1-investigate",
        "phase_id": "phase1-investigate",
        "reason_code": "human_clarification_required",
        "question": "Which bounded answer should be used?",
        "source_state_revision": 8,
    }

    with pytest.raises(HumanInputPolicyError, match="recommended_answer"):
        registry.prepare(
            **base,
            recommended_answer="r" * 40_000,
            risk_level="low",
        )

    with pytest.raises(HumanInputPolicyError, match="options"):
        registry.prepare(
            **base,
            options=[
                {
                    "id": f"option-{index}",
                    "label": f"Option {index}",
                    "description": "One bounded option.",
                    "recommended": False,
                    "risk_level": "medium",
                    "next_phase": "phase1-what",
                }
                for index in range(65)
            ],
        )

    with pytest.raises(HumanInputPolicyError, match="question"):
        registry.prepare(
            **{**base, "question": "ž" * 4_000},
        )
