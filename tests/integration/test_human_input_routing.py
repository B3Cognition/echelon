"""Integration coverage for the controller-owned autonomy boundary."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.human_input import (
    HumanInputOption,
    HumanInputPolicy,
    HumanInputPolicyError,
    HumanInputPolicyRegistry,
)
from harness.phase_graph import PhaseGraph
from harness.squad import SquadController, _ProviderHumanInputAdvance
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore


ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "extension" / "workflow" / "definition.yaml"
EXTENSION = ROOT / "extension" / "extension.yml"


def _choice_policy(
    *,
    classification: str = "operational",
    semi_policy: str = "auto_if_recommended_low_risk",
    recommended: bool = True,
    option_risk: str | None = "low",
) -> HumanInputPolicy:
    return HumanInputPolicy(
        source_kind="human_gate",
        producer_id="checkpoint-plan",
        reason_code="checkpoint_plan_decision_required",
        classification=classification,
        semi_policy=semi_policy,
        resolution_handler="gate_outcome",
        allow_free_text=False,
        allowed_phase_ids=frozenset({"checkpoint-plan"}),
        allowed_target_phases=frozenset(
            {"phase4-document", "terminal-blocked"}
        ),
        context_state_keys=("user_message", "phase"),
        context_paths=(),
        options=(
            HumanInputOption(
                id="approve",
                label="Approve",
                description="Continue to finalization.",
                recommended=recommended,
                risk_level=option_risk,
                next_phase="phase4-document",
                outcome="approved",
            ),
            HumanInputOption(
                id="reject",
                label="Reject",
                description="Stop for revision.",
                recommended=False,
                risk_level="low",
                next_phase="terminal-blocked",
                outcome="rejected",
            ),
        ),
    )


def _free_text_policy(
    *,
    classification: str = "operational",
    semi_policy: str = "auto_if_recommended_low_risk",
    context_state_keys: tuple[str, ...] = ("user_message", "phase"),
    context_paths: tuple[str, ...] = (),
    source_kind: str = "provider_escalation",
) -> HumanInputPolicy:
    return HumanInputPolicy(
        source_kind=source_kind,
        producer_id="phase1-investigate",
        reason_code="human_clarification_required",
        classification=classification,
        semi_policy=semi_policy,
        resolution_handler="clarification_resume",
        allow_free_text=True,
        allowed_phase_ids=frozenset({"phase1-investigate"}),
        allowed_target_phases=frozenset({"phase1-what"}),
        context_state_keys=context_state_keys,
        context_paths=context_paths,
        options=(),
    )


def _decision_result(
    *,
    selected_option_id: str | None = "approve",
    answer_text: str | None = None,
) -> SquadAgentResult:
    return SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DECISION_RESOLVED",
            "state_updates": {},
            "journal_entries": [],
            "decision": {
                "selected_option_id": selected_option_id,
                "answer_text": answer_text,
                "rationale": "This is the best allowed resolution.",
                "confidence": "high",
            },
        },
        raw_output="",
        duration_ms=1,
        timed_out=False,
    )


def _controller(
    tmp_path: Path,
    *,
    autonomy_mode: str,
    policy: HumanInputPolicy,
    provider_result: object | None = None,
) -> tuple[SquadController, SquadStateStore, MagicMock]:
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    (squad_dir / "staging").mkdir()
    store = SquadStateStore(squad_dir)
    store.initialize(
        "run-test",
        "greenfield",
        "registered user message",
        0,
        next(iter(policy.allowed_phase_ids)),
        autonomy_mode=autonomy_mode,
    )
    state = store.load()
    state["staging_dir"] = str(squad_dir / "staging")
    state["context_dir"] = str(squad_dir / "context")
    state["spec_dir"] = str(tmp_path / "spec")
    store.save(state)

    provider = MagicMock()
    provider.exec_agent.return_value = provider_result or _decision_result()
    controller = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=PhaseGraph(DEFINITION, EXTENSION),
        ext_dir=ROOT / "extension",
        project_root=tmp_path,
        squad_dir=squad_dir,
    )
    controller._human_input_registry = HumanInputPolicyRegistry((policy,))
    return controller, store, provider


def _request(
    controller: SquadController,
    store: SquadStateStore,
    policy: HumanInputPolicy,
    *,
    recommended_answer: str | None = None,
    risk_level: str | None = None,
):
    return controller._human_input_registry.prepare(
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        phase_id=next(iter(policy.allowed_phase_ids)),
        reason_code=policy.reason_code,
        question="Which valid resolution should be applied?",
        recommended_answer=recommended_answer,
        risk_level=risk_level,
        source_state_revision=store.load()["state_revision"],
    )


@pytest.mark.parametrize(
    ("mode", "classification", "expected_status", "expected_resolver"),
    [
        ("guided", "operational", "awaiting_human", None),
        ("guided", "material", "awaiting_human", None),
        ("guided", "external_prerequisite", "awaiting_human", None),
        ("semi", "operational", "pending", "semi"),
        ("semi", "material", "awaiting_human", None),
        ("semi", "external_prerequisite", "awaiting_human", None),
        ("banzai", "operational", "pending", "COMMANDER"),
        ("banzai", "material", "pending", "COMMANDER"),
        ("banzai", "external_prerequisite", "awaiting_human", None),
    ],
)
def test_mode_matrix_routes_from_the_sealed_autonomy_mode(
    tmp_path: Path,
    mode: str,
    classification: str,
    expected_status: str,
    expected_resolver: str | None,
) -> None:
    policy = _choice_policy(classification=classification)
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode=mode,
        policy=policy,
    )
    applied: list[object] = []
    controller.apply_human_input_resolution = MagicMock(
        side_effect=lambda *_args, resolution, **_kwargs: (
            applied.append(resolution) or True
        )
    )

    resolved = controller.handle_human_input(
        _request(controller, store, policy),
    )

    decision = store.load()["blocked_decision"]
    assert decision["autonomy_mode"] == mode
    assert decision["status"] == (
        "resolving" if expected_resolver == "COMMANDER" else expected_status
    )
    assert resolved is (expected_resolver is not None)
    if expected_resolver is None:
        assert applied == []
        provider.exec_agent.assert_not_called()
    else:
        assert applied[0].resolved_by == expected_resolver
        assert provider.exec_agent.call_count == (
            1 if expected_resolver == "COMMANDER" else 0
        )


@pytest.mark.parametrize(
    (
        "option_risk",
        "request_risk",
        "recommended",
        "semi_policy",
        "classification",
        "expected_resolved",
    ),
    [
        ("medium", "low", True, "auto_if_recommended_low_risk", "operational", False),
        ("low", "high", True, "auto_if_recommended_low_risk", "operational", True),
        (None, None, True, "auto_if_recommended_low_risk", "operational", False),
        ("low", None, False, "auto_if_recommended_low_risk", "operational", False),
        ("low", "low", True, "require_human", "operational", False),
        ("low", "low", True, "auto_if_recommended_low_risk", "material", False),
    ],
)
def test_semi_choice_selection_is_closed_and_risk_aware(
    tmp_path: Path,
    option_risk: str | None,
    request_risk: str | None,
    recommended: bool,
    semi_policy: str,
    classification: str,
    expected_resolved: bool,
) -> None:
    policy = _choice_policy(
        classification=classification,
        semi_policy=semi_policy,
        recommended=recommended,
        option_risk=option_risk,
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="semi",
        policy=policy,
    )
    controller.apply_human_input_resolution = MagicMock(return_value=True)

    resolved = controller.handle_human_input(
        _request(controller, store, policy, risk_level=request_risk),
    )

    assert resolved is expected_resolved
    if expected_resolved:
        resolution = controller.apply_human_input_resolution.call_args.kwargs[
            "resolution"
        ]
        assert resolution.selected_option_id == "approve"
        assert resolution.answer_text is None
        assert resolution.resolved_by == "semi"
    else:
        controller.apply_human_input_resolution.assert_not_called()
        assert store.load()["blocked_decision"]["status"] == "awaiting_human"


def test_semi_free_text_requires_an_explicit_low_risk_recommendation(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy(source_kind="legacy_recovery")
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="semi",
        policy=policy,
    )
    controller.apply_human_input_resolution = MagicMock(return_value=True)

    assert controller.handle_human_input(
        _request(
            controller,
            store,
            policy,
            recommended_answer="Use the existing product boundary.",
            risk_level="low",
        ),
    )
    resolution = controller.apply_human_input_resolution.call_args.kwargs[
        "resolution"
    ]
    assert resolution.answer_text == "Use the existing product boundary."
    assert resolution.selected_option_id is None
    assert resolution.resolved_by == "semi"
    provider.exec_agent.assert_not_called()


def test_semi_multiple_recommendations_are_rejected_during_preparation() -> None:
    policy = _choice_policy()
    with pytest.raises(HumanInputPolicyError, match="at most one recommended"):
        replace(
            policy,
            options=(
                policy.options[0],
                replace(policy.options[1], recommended=True),
            ),
        )


def test_provider_question_uses_the_exact_attested_advance_without_replay(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy(classification="material")
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    attested_decision = MagicMock(name="attested-routing-decision")
    attested_decision.from_phase = policy.producer_id
    attested_decision.to_phase = "phase1-what"
    controller._advance_prepared_result_or_block = MagicMock(return_value=MagicMock())

    resolved = controller.handle_human_input(
        _request(controller, store, policy),
        provider_advance=_ProviderHumanInputAdvance(
            from_phase=policy.producer_id,
            to_phase="phase1-what",
            decision=attested_decision,
        ),
    )

    assert resolved is False
    call = controller._advance_prepared_result_or_block.call_args
    assert call.args[1] is attested_decision
    assert call.kwargs["human_input_initial_status"] == "awaiting_human"
    provider.exec_agent.assert_not_called()


def test_commander_context_contains_only_policy_declared_state_and_files(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy(
        context_state_keys=("user_message",),
        context_paths=("{staging_dir}/allowed.md",),
        source_kind="legacy_recovery",
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    staging = Path(store.load()["staging_dir"])
    (staging / "allowed.md").write_text("REGISTERED FILE", encoding="utf-8")
    (staging / "secret.md").write_text("UNREGISTERED FILE", encoding="utf-8")
    state = store.load()
    state["secret_state"] = "UNREGISTERED STATE"
    store.save(state)
    request = _request(
        controller,
        store,
        policy,
        recommended_answer="Use the registered evidence.",
        risk_level="medium",
    )
    store.set_human_input_decision(request, initial_status="pending")
    state = store.load()

    prompt = controller._render_commander_decision_prompt(
        state["blocked_decision"],
        policy,
        state,
    )

    assert "registered user message" in prompt
    assert "REGISTERED FILE" in prompt
    assert "UNREGISTERED FILE" not in prompt
    assert "UNREGISTERED STATE" not in prompt


def test_commander_context_rejects_symlink_escape_from_declared_root(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy(
        context_paths=("{staging_dir}/escape.md",),
        source_kind="legacy_recovery",
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    outside = tmp_path / "outside.md"
    outside.write_text("OUTSIDE SECRET", encoding="utf-8")
    staging = Path(store.load()["staging_dir"])
    (staging / "escape.md").symlink_to(outside)
    request = _request(controller, store, policy)
    store.set_human_input_decision(request, initial_status="pending")
    state = store.load()

    with pytest.raises(HumanInputPolicyError, match="escape"):
        controller._render_commander_decision_prompt(
            state["blocked_decision"],
            policy,
            state,
        )


def test_commander_context_bounds_the_complete_utf8_prompt(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy(
        context_paths=("{staging_dir}/large.md",),
        source_kind="legacy_recovery",
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    staging = Path(store.load()["staging_dir"])
    (staging / "large.md").write_text("ž" * 40_000, encoding="utf-8")
    request = _request(controller, store, policy)
    store.set_human_input_decision(request, initial_status="pending")
    state = store.load()

    prompt = controller._render_commander_decision_prompt(
        state["blocked_decision"],
        policy,
        state,
    )

    assert len(prompt.encode("utf-8")) <= 32_768
    prompt.encode("utf-8").decode("utf-8")
    assert "DECISION_RESOLVED" in prompt


def test_commander_invalid_result_retries_once_after_a_fresh_claim(
    tmp_path: Path,
) -> None:
    policy = _choice_policy()
    invalid = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "BLOCKED",
            "state_updates": {"status": "blocked"},
        },
        raw_output="",
        duration_ms=1,
        timed_out=False,
        token_usage=7,
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    events: list[str] = []
    original_claim = store.claim_human_input_decision

    def claim(*args, **kwargs):
        events.append("claim")
        return original_claim(*args, **kwargs)

    store.claim_human_input_decision = MagicMock(side_effect=claim)
    valid = _decision_result()
    valid.token_usage = 11
    results = iter((invalid, valid))

    def execute(*_args, **_kwargs):
        events.append("model")
        return next(results)

    provider.exec_agent.side_effect = execute
    controller.apply_human_input_resolution = MagicMock(return_value=True)

    assert controller.handle_human_input(_request(controller, store, policy))
    assert events == ["claim", "model", "claim", "model"]
    assert provider.exec_agent.call_count == 2
    assert store.load()["blocked_decision"]["attempts"] == 2
    assert store.load()["token_usage"] == 18
    controller.apply_human_input_resolution.assert_called_once()


def test_commander_second_failure_persists_manual_diagnosis_without_human_fallback(
    tmp_path: Path,
) -> None:
    policy = _choice_policy()
    provider_failure = SquadAgentResult(
        exit_code=1,
        echelon_result=None,
        raw_output="provider failed",
        duration_ms=1,
        timed_out=False,
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    provider.exec_agent.return_value = provider_failure
    controller.apply_human_input_resolution = MagicMock(return_value=True)

    assert controller.handle_human_input(
        _request(controller, store, policy)
    ) is False

    state = store.load()
    assert provider.exec_agent.call_count == 2
    assert state["blocked_decision"]["status"] == "failed"
    assert state["blocked_decision"]["attempts"] == 2
    assert state["recovery_instruction"]["kind"] == "manual_diagnosis"
    assert "escalation_question" not in state
    controller.apply_human_input_resolution.assert_not_called()


def test_commander_resume_recovers_interrupted_resolution_before_claim(
    tmp_path: Path,
) -> None:
    policy = _choice_policy()
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    request = _request(controller, store, policy)
    sealed = store.set_human_input_decision(request, initial_status="pending")
    decision = sealed["blocked_decision"]
    store.claim_human_input_decision(
        decision["id"],
        expected_state_revision=sealed["state_revision"],
    )
    events: list[str] = []
    original_recover = store.recover_interrupted_human_input_decision
    original_claim = store.claim_human_input_decision

    def recover():
        events.append("recover")
        return original_recover()

    def claim(*args, **kwargs):
        events.append("claim")
        return original_claim(*args, **kwargs)

    store.recover_interrupted_human_input_decision = MagicMock(
        side_effect=recover
    )
    store.claim_human_input_decision = MagicMock(side_effect=claim)
    controller.apply_human_input_resolution = MagicMock(return_value=True)

    assert controller.resume_pending_human_input()
    assert events[:2] == ["recover", "claim"]
