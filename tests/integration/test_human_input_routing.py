"""Integration coverage for the controller-owned autonomy boundary."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

import harness.squad as squad_module
from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.blocked_decision import (
    build_blocked_decision_v2,
    validate_blocked_decision,
)
from harness.config import HarnessConfig, LlmConfig
from harness.human_input import (
    HumanInputOption,
    HumanInputPolicy,
    HumanInputPolicyError,
    HumanInputPolicyRegistry,
    HumanInputResolution,
    ProportionalQualityRecommendationEvidence,
    RecommendationEvidence,
    controller_safeguard_policies,
    prepare_controller_checkpoint_assessment_decision,
    prepare_controller_phase_dispatch_limit_decision,
    prepare_controller_proportional_quality_decision,
    select_initial_decision_status,
)
from harness.phase_graph import PhaseGraph, PhaseNode
from harness.prepared_phase_result import prepare_phase_result
from harness.recovery_instruction import (
    RecoveryKind,
    RecoveryInstruction,
    validate_recovery_instruction,
)
from harness.squad import SquadController, _ProviderHumanInputAdvance
from harness.squad_provider import SquadAgentResult, SquadCliProvider
from harness.squad_state import SquadStateStore, StateAdvanceError
from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock


ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "runtime" / "workflow" / "definition.yaml"
PROSAIC_SUBAGENTS = ROOT / "prosaic" / "subagents"


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
    rationale: str = "This is the best allowed resolution.",
    confidence: str = "high",
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
                "rationale": rationale,
                "confidence": confidence,
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
    provider: object | None = None,
) -> tuple[SquadController, SquadStateStore, object]:
    squad_dir = tmp_path / "runs" / "spec-test"
    squad_dir.mkdir(parents=True)
    (squad_dir / "staging").mkdir()
    store = SquadStateStore(squad_dir)
    store.initialize(
        "spec-test",
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

    if provider is None:
        provider = MagicMock()
        provider.exec_agent.return_value = provider_result or _decision_result()
    controller = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS),
        ext_dir=ROOT / "runtime",
        project_root=tmp_path,
        squad_dir=squad_dir,
    )
    policies = (policy,)
    if policy.source_kind == "legacy_recovery":
        safeguard_identities = {
            (item.producer_id, item.reason_code)
            for item in controller_safeguard_policies()
        }
        current_source_kind = (
            "controller_safeguard"
            if (policy.producer_id, policy.reason_code)
            in safeguard_identities
            else "provider_escalation"
        )
        policies = (replace(policy, source_kind=current_source_kind),)
    controller._human_input_registry = HumanInputPolicyRegistry(policies)
    return controller, store, provider


def _workflow_gate_controller(
    tmp_path: Path,
    *,
    gate_id: str,
    autonomy_mode: str,
    provider_result: SquadAgentResult | None = None,
) -> tuple[SquadController, SquadStateStore, object]:
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    policy = graph.get(gate_id).human_input_policies[0]
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode=autonomy_mode,
        policy=policy,
        provider_result=provider_result,
    )
    controller._graph = graph
    controller._human_input_registry = graph.human_input_policy_registry()
    return controller, store, provider


def _seed_current_checkpoint_pass(
    monkeypatch: pytest.MonkeyPatch,
    controller: SquadController,
    store: SquadStateStore,
) -> None:
    state = store.load()
    spec_dir = Path(str(state["spec_dir"]))
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "spec.md").write_text("# Certified specification\n", encoding="utf-8")
    (spec_dir / "quality-gates.md").write_text(
        "# Quality gates\n\nVerdict: PASS\n",
        encoding="utf-8",
    )
    (spec_dir / "issues.md").write_text(
        "# Issues\n\nNo issues found.\n",
        encoding="utf-8",
    )
    lexicon_report = spec_dir / "spec-lexicon-report.json"
    lexicon_report.write_text(
        json.dumps({"schema_version": 1, "ok": True}, sort_keys=True),
        encoding="utf-8",
    )
    state.update(
        {
            "spec_quality_certificate": {
                "schema_version": 2,
                "status": "passed",
                "source_path": "spec/spec.md",
                "source_sha256": "1" * 64,
                "understanding_evidence": "runs/spec-test/evidence.json",
                "understanding_evidence_sha256": "2" * 64,
                "sage_phase": "phase1-why2",
                "sage_evidence": "spec/issues.md",
                "sage_evidence_sha256": "3" * 64,
                "sage_verdict": "PASS",
            },
            "lexicon_evaluation": "passed",
            "lexicon_pass": True,
            "lexicon_report": str(lexicon_report),
        }
    )
    store.save(state)
    controller._gate_config_cache = {
        "lexicon_gate": {
            "enabled": True,
            "spec_enabled": True,
            "artifacts": {"spec": {"enabled": True}},
        }
    }
    monkeypatch.setattr(
        "harness.phase1_quality.has_current_phase1_quality_certificate",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "harness.phase1_quality_debt.has_current_quality_debt_authorization",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "harness.spec_lexicon_gate.has_current_spec_lexicon_evidence",
        lambda *_args, **_kwargs: True,
    )


def _seed_current_checkpoint_debt(
    monkeypatch: pytest.MonkeyPatch,
    store: SquadStateStore,
) -> str:
    state = store.load()
    spec_dir = Path(str(state["spec_dir"]))
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "spec.md").write_text("# Debt-authorized specification\n", encoding="utf-8")
    (spec_dir / "quality-gates.md").write_text(
        "# Quality gates\n\nVerdict: FAIL\nOverall: 0.70 / 0.80\n",
        encoding="utf-8",
    )
    (spec_dir / "issues.md").write_text(
        "# Issues\n\nResidual quality debt remains.\n",
        encoding="utf-8",
    )
    state["spec_quality_debt_authorization"] = {
        "schema_version": 1,
        "status": "accepted_with_debt",
        "resolved_by": "user",
        "decision_id": "dec-quality-debt",
        "debt_artifact": "spec/quality-debt.json",
        "debt_artifact_sha256": "4" * 64,
        "resolved_decision_sha256": "5" * 64,
    }
    store.save(state)
    monkeypatch.setattr(
        "harness.phase1_quality.has_current_phase1_quality_certificate",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "harness.phase1_quality_debt.has_current_quality_debt_authorization",
        lambda *_args, **_kwargs: True,
    )
    return "user"


def _prepare_real_v3_quality_debt(
    tmp_path: Path,
) -> tuple[SquadController, SquadStateStore]:
    from tests.integration.test_squad_controller import (
        _coordinate_prepared_result,
        _make_proportional_assessment_numerically_passing,
        _mark_constitution_complete,
        _proportional_assessment_fixture,
        _start_proportional_quality_loop,
    )

    controller, store = _start_proportional_quality_loop(
        tmp_path,
        automatic_consumed=3,
        squad_dir=tmp_path / "runs" / "run-test",
    )
    (tmp_path / "runs" / ".current").write_text(
        f"{store.squad_dir.name}\n",
        encoding="utf-8",
    )
    _mark_constitution_complete(tmp_path, store)
    updates, result = _proportional_assessment_fixture(
        controller,
        store,
        0,
    )
    _make_proportional_assessment_numerically_passing(updates)
    state = store.load()
    state.update(updates)
    store.save(state)

    route = _coordinate_prepared_result(
        controller,
        controller._graph.get("phase1-why2"),
        result,
    )
    assert route == "terminal-blocked"
    assert store.load()["blocked_decision"]["schema_version"] == 3
    return controller, store


def _accept_real_v3_quality_debt(
    tmp_path: Path,
) -> tuple[SquadController, SquadStateStore]:
    controller, store = _prepare_real_v3_quality_debt(tmp_path)
    assert controller.resume_with_human_input("continue_with_debt") is True
    return controller, store


def _advance_real_debt_fixture_to_checkpoint(
    store: SquadStateStore,
) -> None:
    for index, to_phase in enumerate(
        ("phase1-lexicon", "checkpoint-assess"),
        start=1,
    ):
        state = store.load()
        from_phase = str(state["phase"])
        if from_phase == "checkpoint-assess":
            return
        if from_phase == "phase1-lexicon" and to_phase == "phase1-lexicon":
            continue
        prepared = prepare_phase_result(
            PhaseNode(
                id=from_phase,
                type="agent",
                allowed_state_updates=[],
            ),
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {},
                },
                raw_output="",
                duration_ms=1,
                timed_out=False,
            ),
            controller_updates={},
        )
        snapshot = store.capture_routing_snapshot(expected_phase=from_phase)
        routing = store.prepare_routing_decision(
            prepared,
            snapshot=snapshot,
            from_phase=from_phase,
            to_phase=to_phase,
            dispatch_id=f"{index:032x}",
        )
        store.advance(from_phase, to_phase, routing)


def _request(
    controller: SquadController,
    store: SquadStateStore,
    policy: HumanInputPolicy,
    *,
    recommended_answer: str | None = None,
    risk_level: str | None = None,
):
    registry = (
        HumanInputPolicyRegistry((policy,))
        if policy.source_kind == "legacy_recovery"
        else controller._human_input_registry
    )
    return registry.prepare(
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        phase_id=next(iter(policy.allowed_phase_ids)),
        reason_code=policy.reason_code,
        question="Which valid resolution should be applied?",
        recommended_answer=recommended_answer,
        risk_level=risk_level,
        source_state_revision=store.load()["state_revision"],
    )


def _automatic_free_text_request(
    controller: SquadController,
    store: SquadStateStore,
    policy: HumanInputPolicy,
    *,
    recommended_answer: str = "Use the sealed evidence.",
):
    return _request(
        controller,
        store,
        policy,
        recommended_answer=recommended_answer,
        risk_level="low",
    )


def _seal_awaiting_human(
    controller: SquadController,
    store: SquadStateStore,
    policy: HumanInputPolicy,
    *,
    question: str = "Which valid resolution should be applied?",
) -> tuple[str, int]:
    registry = (
        HumanInputPolicyRegistry((policy,))
        if policy.source_kind == "legacy_recovery"
        else controller._human_input_registry
    )
    request = registry.prepare(
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        phase_id=next(iter(policy.allowed_phase_ids)),
        reason_code=policy.reason_code,
        question=question,
        source_state_revision=store.load()["state_revision"],
    )
    store.set_human_input_decision(
        request,
        initial_status="awaiting_human",
    )
    state = store.load()
    return state["blocked_decision"]["id"], state["state_revision"]


def _safeguard_policy(
    producer_id: str,
    *,
    phase_id: str,
    setter_compatible: bool = False,
) -> HumanInputPolicy:
    policy = next(
        item
        for item in controller_safeguard_policies()
        if item.producer_id == producer_id
    )
    return replace(
        policy,
        source_kind=(
            "legacy_recovery"
            if setter_compatible
            and producer_id != "phase_dispatch_limit"
            else policy.source_kind
        ),
        allowed_phase_ids=frozenset({phase_id}),
    )


def _proportional_repair_state(
    *,
    extension_authorized: int = 0,
    extension_consumed: int = 0,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "authoring_mode": "proportional",
        "automatic_limit": 3,
        "automatic_consumed": 3,
        "extension_limit": 1,
        "extension_authorized": extension_authorized,
        "extension_consumed": extension_consumed,
        "migration_basis": "fresh",
        "baseline_candidate_id": "quality-candidate-0",
        "candidate_ids": [
            "quality-candidate-0",
            "quality-candidate-1",
            "quality-candidate-2",
            "quality-candidate-3",
        ],
    }


def _proportional_recommendation_evidence(
    *,
    current_depth: float = 0.72,
    previous_depth: float = 0.70,
    borderline_margin: float = 0.05,
    formal_statement_count: int = 8,
    previous_formal_statement_count: int = 8,
) -> ProportionalQualityRecommendationEvidence:
    return ProportionalQualityRecommendationEvidence(
        borderline_margin=borderline_margin,
        previous_gates=(
            ("depth", previous_depth, 0.75, False),
            ("overall", 0.74, 0.75, False),
            ("structure", 0.80, 0.75, True),
        ),
        current_gates=(
            ("depth", current_depth, 0.75, False),
            ("overall", 0.745, 0.75, False),
            ("structure", 0.80, 0.75, True),
        ),
        previous_formal_statement_count=previous_formal_statement_count,
        formal_statement_count=formal_statement_count,
    )


def _dispatch_cap_candidate(
    issue_id: str = "ISS-001",
    *,
    title: str = "Retry policy",
    suggested_option: str = "Use exponential backoff.",
) -> dict[str, str]:
    return {
        "issue_id": issue_id,
        "title": title,
        "decision_required": "Retry behavior.",
        "suggested_option": suggested_option,
        "evidence_basis": "The API reference documents idempotent reads.",
    }


def _dispatch_cap_option(candidate: dict[str, str]) -> HumanInputOption:
    return HumanInputOption(
        id=candidate["issue_id"],
        label=f"{candidate['issue_id']}: {candidate['title']}",
        description=json.dumps(
            candidate,
            sort_keys=True,
            separators=(",", ":"),
        ),
        recommended=False,
        risk_level="medium",
        next_phase="phase1-what",
        outcome=None,
    )


def _seal_dispatch_cap_decision(
    controller: SquadController,
    store: SquadStateStore,
    policy: HumanInputPolicy,
    candidates: tuple[dict[str, str], ...],
    *,
    initial_status: str = "awaiting_human",
    legacy: bool = False,
    phase_id: str = "phase1-what",
) -> tuple[str, int]:
    option_contract = (
        tuple(_dispatch_cap_option(item) for item in candidates)
        if legacy
        else controller._dispatch_cap_options(list(candidates))
    )
    request = controller._human_input_registry.prepare_controller(
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        phase_id=phase_id,
        reason_code=policy.reason_code,
        question="Select one sealed evidence-backed issue resolution.",
        source_state_revision=store.load()["state_revision"],
        option_contract=option_contract,
    )
    store.set_human_input_decision(request, initial_status=initial_status)
    state = store.load()
    return state["blocked_decision"]["id"], state["state_revision"]


def _legacy_workflow_controller(
    tmp_path: Path,
    *,
    autonomy_mode: str,
    phase_id: str,
    reason_code: str,
    recovery_phase: str | None = None,
    options: object = None,
    decision_status: str = "pending",
    recovery_kind: RecoveryKind = RecoveryKind.AWAIT_HUMAN_ANSWER,
    provider_result: SquadAgentResult | None = None,
    recommended_answer: str | None = None,
    risk_level: str | None = None,
) -> tuple[SquadController, SquadStateStore, object]:
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    setup_policy = graph.human_input_policy_registry().lookup(
        "provider_escalation",
        "phase1-tracker",
        "human_clarification_required",
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode=autonomy_mode,
        policy=setup_policy,
        provider_result=provider_result,
    )
    controller._graph = graph
    controller._human_input_registry = graph.human_input_policy_registry()
    state = store.load()
    state.update(
        {
            "status": "blocked",
            "phase": phase_id,
            "blocked_reason": reason_code,
            "escalation_question": "Which exact legacy decision should be applied?",
            "escalation_options": [] if options is None else options,
            "escalation_recommended_answer": recommended_answer,
            "escalation_risk_level": risk_level,
            "recovery_instruction": RecoveryInstruction(
                kind=recovery_kind,
                reason_code=reason_code,
                phase=recovery_phase or phase_id,
                requires_human_input=True,
            ).to_dict(),
        }
    )
    if recovery_phase is not None:
        state["last_dispatch"] = {"phase_id": recovery_phase}
        if reason_code == "phase_dispatch_limit":
            state["phase_dispatch_limit_phase"] = recovery_phase
    store.save(state)
    if decision_status != "pending":
        state = store.load()
        state["blocked_decision"]["status"] = decision_status
        store.save(state)
    return controller, store, provider


def _provider_routing_decision(
    store: SquadStateStore,
    policy: HumanInputPolicy,
):
    prepared = prepare_phase_result(
        PhaseNode(
            id=policy.producer_id,
            type="agent",
            allowed_state_updates=[],
        ),
        SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "state_updates": {},
            },
            raw_output="",
            duration_ms=1,
            timed_out=False,
        ),
        controller_updates={},
    )
    snapshot = store.capture_routing_snapshot(
        expected_phase=policy.producer_id,
    )
    return store.prepare_routing_decision(
        prepared,
        snapshot=snapshot,
        from_phase=policy.producer_id,
        to_phase=policy.producer_id,
        record_completion=False,
        dispatch_id="d" * 32,
    )


def test_provider_request_resolved_inline_keeps_sealed_decision_id(
    tmp_path: Path,
) -> None:
    answer = "Hello, World!"
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    policy = graph.human_input_policy_registry().lookup(
        "provider_escalation",
        "phase1-tracker",
        "human_clarification_required",
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
        provider_result=_decision_result(
            selected_option_id=None,
            answer_text=answer,
        ),
    )
    routing = _provider_routing_decision(store, policy)
    request = _automatic_free_text_request(
        controller,
        store,
        policy,
        recommended_answer=answer,
    )
    sealed_ids: list[str] = []

    def advance(_node, decision, **kwargs):
        receipt = store.advance(
            policy.producer_id,
            policy.producer_id,
            decision,
            human_input=kwargs["human_input"],
            human_input_initial_status=kwargs[
                "human_input_initial_status"
            ],
        )
        sealed_ids.append(store.load()["blocked_decision"]["id"])
        return receipt

    controller._advance_prepared_result_or_block = MagicMock(
        side_effect=advance
    )

    assert controller.handle_human_input(
        request,
        provider_advance=_ProviderHumanInputAdvance(
            from_phase=policy.producer_id,
            to_phase=policy.producer_id,
            decision=routing,
        ),
    )

    resolved = store.load()["blocked_decision"]
    assert resolved["source_kind"] == "provider_escalation"
    assert resolved["id"] == sealed_ids[0]
    assert resolved["status"] == "resolved"
    assert resolved["answer_text"] == answer
    assert resolved["recommendation_followed"] is True
    assert resolved["override_reason"] is None
    provider.exec_agent.assert_called_once()


def test_commander_resolution_persists_low_confidence_follow_audit(
    tmp_path: Path,
) -> None:
    rationale = "Debt is authorized by the sealed evidence."
    controller, store, provider = _workflow_gate_controller(
        tmp_path,
        gate_id="checkpoint-plan",
        autonomy_mode="banzai",
        provider_result=_decision_result(
            rationale=rationale,
            confidence="low",
        ),
    )
    policy = controller._graph.get("checkpoint-plan").human_input_policies[0]

    assert controller.handle_human_input(_request(controller, store, policy))

    decision = store.load()["blocked_decision"]
    assert decision["schema_version"] == 3
    assert decision["resolution_rationale"] == rationale
    assert decision["resolution_confidence"] == "low"
    assert decision["recommendation_followed"] is True
    assert decision["override_reason"] is None
    provider.exec_agent.assert_called_once()


def test_commander_override_uses_its_rationale_as_the_durable_reason(
    tmp_path: Path,
) -> None:
    rationale = "The sealed evidence exposes a blocking contradiction."
    controller, store, provider = _workflow_gate_controller(
        tmp_path,
        gate_id="checkpoint-plan",
        autonomy_mode="banzai",
        provider_result=_decision_result(
            selected_option_id="reject",
            rationale=rationale,
            confidence="low",
        ),
    )
    policy = controller._graph.get("checkpoint-plan").human_input_policies[0]

    assert (
        controller.handle_human_input(_request(controller, store, policy))
        is False
    )

    decision = store.load()["blocked_decision"]
    assert decision["selected_option_id"] == "reject"
    assert decision["resolution_rationale"] == rationale
    assert decision["resolution_confidence"] == "low"
    assert decision["recommendation_followed"] is False
    assert decision["override_reason"] == rationale
    provider.exec_agent.assert_called_once()


def test_semi_resolution_copies_the_sealed_recommendation_audit(
    tmp_path: Path,
) -> None:
    controller, store, provider = _workflow_gate_controller(
        tmp_path,
        gate_id="checkpoint-plan",
        autonomy_mode="semi",
    )
    policy = controller._graph.get("checkpoint-plan").human_input_policies[0]

    assert controller.handle_human_input(_request(controller, store, policy))

    decision = store.load()["blocked_decision"]
    assert decision["resolved_by"] == "semi"
    assert decision["resolution_rationale"] == decision[
        "recommendation_rationale"
    ]
    assert decision["resolution_confidence"] == decision[
        "recommendation_confidence"
    ]
    assert decision["recommendation_followed"] is True
    assert decision["override_reason"] is None
    provider.exec_agent.assert_not_called()


def test_banzai_human_only_free_text_waits_and_accepts_user_answer(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy()
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    routing = _provider_routing_decision(store, policy)
    request = _request(controller, store, policy)
    controller._advance_prepared_result_or_block = MagicMock(
        side_effect=lambda _node, decision, **kwargs: store.advance(
            policy.producer_id,
            policy.producer_id,
            decision,
            human_input=kwargs["human_input"],
            human_input_initial_status=kwargs["human_input_initial_status"],
        )
    )

    assert controller.handle_human_input(
        request,
        provider_advance=_ProviderHumanInputAdvance(
            from_phase=policy.producer_id,
            to_phase=policy.producer_id,
            decision=routing,
        ),
    ) is False

    waiting = store.load()["blocked_decision"]
    assert waiting["schema_version"] == 3
    assert waiting["status"] == "awaiting_human"
    assert waiting["automatic_eligible"] is False
    provider.exec_agent.assert_not_called()

    assert controller.resume_with_human_input("Use the public boundary.")

    resolved = store.load()["blocked_decision"]
    assert resolved["schema_version"] == 3
    assert resolved["status"] == "resolved"
    assert resolved["answer_text"] == "Use the public boundary."
    assert resolved["resolved_by"] == "user"
    assert resolved["resolution_rationale"] is None
    assert resolved["resolution_confidence"] is None
    assert resolved["recommendation_followed"] is None
    provider.exec_agent.assert_not_called()


def test_legacy_v2_awaiting_human_choice_without_recommendation_remains_v2(
    tmp_path: Path,
) -> None:
    policy = _choice_policy()
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    created_at = "2026-08-20T09:30:00+00:00"
    decision = build_blocked_decision_v2(
        decision_id="dec-legacy-awaiting-choice",
        status="awaiting_human",
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        source_phase="checkpoint-plan",
        reason_code=policy.reason_code,
        classification=policy.classification,
        question="Approve or reject the retained plan?",
        options=[
            {
                "id": option.id,
                "label": option.label,
                "description": option.description,
                "recommended": False,
                "risk_level": option.risk_level,
                "next_phase": option.next_phase,
                "outcome": option.outcome,
            }
            for option in policy.options
        ],
        recommended_answer=None,
        risk_level=None,
        resolution_handler=policy.resolution_handler,
        autonomy_mode="banzai",
        source_state_revision=1,
        now=created_at,
    )
    raw = store.load()
    raw.update(
        {
            "status": "blocked",
            "blocked_reason": decision["reason_code"],
            "escalation_question": decision["question"],
            "blocked_decision": decision,
            "recovery_instruction": RecoveryInstruction(
                kind=RecoveryKind.AWAIT_HUMAN_ANSWER,
                reason_code=str(decision["reason_code"]),
                phase=str(decision["source_phase"]),
                requires_human_input=True,
                schema_version=2,
                decision_id=str(decision["id"]),
            ).to_dict(),
        }
    )
    store._path.write_text(json.dumps(raw), encoding="utf-8")
    restarted = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=controller._graph,
        ext_dir=ROOT / "runtime",
        project_root=tmp_path,
        squad_dir=store.squad_dir,
    )
    restarted._human_input_registry = HumanInputPolicyRegistry((policy,))

    assert restarted.resume_with_human_input("approve")

    resolved = store.load()["blocked_decision"]
    assert resolved["schema_version"] == 2
    assert resolved["id"] == "dec-legacy-awaiting-choice"
    assert resolved["created_at"] == created_at
    assert resolved["status"] == "resolved"
    assert resolved["selected_option_id"] == "approve"
    assert resolved["resolved_by"] == "user"
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize("initial_status", ("pending", "resolving"))
def test_legacy_v2_semi_resolution_remains_v2_without_invented_audit(
    tmp_path: Path,
    initial_status: str,
) -> None:
    policy = _choice_policy()
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="semi",
        policy=policy,
    )
    decision = build_blocked_decision_v2(
        decision_id=f"dec-legacy-semi-{initial_status}",
        status=initial_status,
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        source_phase="checkpoint-plan",
        reason_code=policy.reason_code,
        classification=policy.classification,
        question="Approve or reject the retained plan?",
        options=[
            {
                "id": option.id,
                "label": option.label,
                "description": option.description,
                "recommended": option.recommended,
                "risk_level": option.risk_level,
                "next_phase": option.next_phase,
                "outcome": option.outcome,
            }
            for option in policy.options
        ],
        recommended_answer=None,
        risk_level=None,
        resolution_handler=policy.resolution_handler,
        autonomy_mode="semi",
        source_state_revision=1,
        attempts=1 if initial_status == "resolving" else 0,
        now="2026-08-20T09:45:00+00:00",
    )
    raw = store.load()
    raw.update(
        {
            "status": "blocked",
            "blocked_reason": decision["reason_code"],
            "escalation_question": decision["question"],
            "blocked_decision": decision,
            "recovery_instruction": RecoveryInstruction(
                kind=RecoveryKind.RESOLVE_DECISION,
                reason_code=str(decision["reason_code"]),
                phase=str(decision["source_phase"]),
                requires_human_input=False,
                schema_version=2,
                decision_id=str(decision["id"]),
            ).to_dict(),
        }
    )
    store._path.write_text(json.dumps(raw), encoding="utf-8")

    assert controller.resume_pending_human_input()

    resolved = store.load()["blocked_decision"]
    assert resolved["schema_version"] == 2
    assert resolved["id"] == decision["id"]
    assert resolved["status"] == "resolved"
    assert resolved["selected_option_id"] == "approve"
    assert resolved["resolved_by"] == "semi"
    assert "resolution_rationale" not in resolved
    assert "resolution_confidence" not in resolved
    provider.exec_agent.assert_not_called()


def test_unreconstructable_pending_v2_banzai_fails_without_provider_dispatch(
    tmp_path: Path,
) -> None:
    policy = HumanInputPolicy(
        source_kind="provider_escalation",
        producer_id="phase1-investigate",
        reason_code="human_clarification_required",
        classification="operational",
        semi_policy="auto_if_recommended_low_risk",
        resolution_handler="clarification_resume",
        allow_free_text=False,
        allowed_phase_ids=frozenset({"phase1-investigate"}),
        allowed_target_phases=frozenset({"phase1-what"}),
        context_state_keys=("user_message", "phase"),
        context_paths=(),
        options=(),
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    created_at = "2026-08-20T10:15:00+00:00"
    options = [
        {
            "id": "approve",
            "label": "Approve",
            "description": "Continue with the retained provider choice.",
            "recommended": False,
            "risk_level": "low",
            "next_phase": "phase1-what",
            "outcome": None,
        }
    ]
    decision = build_blocked_decision_v2(
        decision_id="dec-legacy-migration-failure",
        status="pending",
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        source_phase="phase1-investigate",
        reason_code=policy.reason_code,
        classification=policy.classification,
        question="Which retained provider option should be applied?",
        options=options,
        recommended_answer=None,
        risk_level=None,
        resolution_handler=policy.resolution_handler,
        autonomy_mode="banzai",
        source_state_revision=1,
        attempts=1,
        now=created_at,
    )
    raw = store.load()
    raw.update(
        {
            "status": "blocked",
            "blocked_reason": decision["reason_code"],
            "escalation_question": decision["question"],
            "blocked_decision": decision,
            "recovery_instruction": RecoveryInstruction(
                kind=RecoveryKind.RESOLVE_DECISION,
                reason_code=str(decision["reason_code"]),
                phase=str(decision["source_phase"]),
                requires_human_input=False,
                schema_version=2,
                decision_id=str(decision["id"]),
            ).to_dict(),
        }
    )
    store._path.write_text(json.dumps(raw), encoding="utf-8")

    assert controller.resume_pending_human_input() is False

    failed_state = store.load()
    failed = failed_state["blocked_decision"]
    assert failed["schema_version"] == 2
    assert failed["id"] == decision["id"]
    assert failed["status"] == "failed"
    assert failed["failure_code"] == "decision_recommendation_unavailable"
    for field in (
        "id",
        "schema_version",
        "source_kind",
        "producer_id",
        "source_phase",
        "reason_code",
        "classification",
        "question",
        "options",
        "recommended_answer",
        "risk_level",
        "resolution_handler",
        "autonomy_mode",
        "source_state_revision",
        "attempts",
        "created_at",
        "resolved_at",
    ):
        assert failed[field] == decision[field]
    assert failed_state["blocked_reason"] == (
        "decision_recommendation_unavailable"
    )
    assert failed_state["recovery_instruction"] == RecoveryInstruction(
        kind=RecoveryKind.MANUAL_DIAGNOSIS,
        reason_code=str(decision["reason_code"]),
        phase="",
        requires_human_input=False,
        schema_version=2,
        decision_id=str(decision["id"]),
    ).to_dict()
    provider.exec_agent.assert_not_called()


def test_eligible_v2_migration_failure_reconstructs_replay_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _free_text_policy()
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    state = store.load()
    decision = build_blocked_decision_v2(
        decision_id="dec-eligible-v2-migration-failure",
        status="pending",
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        source_phase="phase1-investigate",
        reason_code=policy.reason_code,
        classification=policy.classification,
        question="Which retained product boundary should be applied?",
        options=[],
        recommended_answer="Use the sealed evidence.",
        risk_level="low",
        resolution_handler=policy.resolution_handler,
        autonomy_mode="banzai",
        source_state_revision=state["state_revision"],
        now="2026-08-23T12:00:00+00:00",
    )
    state.update(
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": decision["reason_code"],
            "escalation_question": decision["question"],
            "blocked_decision": decision,
            "recovery_instruction": RecoveryInstruction(
                kind=RecoveryKind.RESOLVE_DECISION,
                reason_code=str(decision["reason_code"]),
                phase=str(decision["source_phase"]),
                requires_human_input=False,
                schema_version=2,
                decision_id=str(decision["id"]),
            ).to_dict(),
        }
    )
    store._path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(
        controller,
        "_v2_migration_preserves_decision_contract",
        lambda *_args: False,
    )

    assert controller.resume_pending_human_input() is False

    failed = store.load()
    assert failed["blocked_decision"]["status"] == "failed"
    assert failed["phase"] == "phase1-investigate"
    assert controller._v2_decision_automatic_eligible(decision) is True
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize(
    ("legacy_outcome", "migrates"),
    [(None, True), ("approved", False)],
    ids=("canonical-null-outcome", "owned-non-null-outcome"),
)
def test_pending_v2_banzai_provider_choice_migration_preserves_outcome_ownership(
    tmp_path: Path,
    legacy_outcome: str | None,
    migrates: bool,
) -> None:
    policy = HumanInputPolicy(
        source_kind="provider_escalation",
        producer_id="phase1-investigate",
        reason_code="human_clarification_required",
        classification="operational",
        semi_policy="auto_if_recommended_low_risk",
        resolution_handler="clarification_resume",
        allow_free_text=False,
        allowed_phase_ids=frozenset({"phase1-investigate"}),
        allowed_target_phases=frozenset({"phase1-what"}),
        context_state_keys=("user_message", "phase"),
        context_paths=(),
        options=(),
    )
    rationale = "The sealed provider choice remains the bounded recommendation."
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
        provider_result=_decision_result(
            selected_option_id="approve",
            rationale=rationale,
            confidence="low",
        ),
    )
    decision = build_blocked_decision_v2(
        decision_id=f"dec-provider-choice-{legacy_outcome or 'null'}",
        status="pending",
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        source_phase="phase1-investigate",
        reason_code=policy.reason_code,
        classification=policy.classification,
        question="Which retained provider choice should be applied?",
        options=[
            {
                "id": "approve",
                "label": "Approve",
                "description": "Continue with the retained provider choice.",
                "recommended": True,
                "risk_level": "low",
                "next_phase": "phase1-what",
                "outcome": legacy_outcome,
            }
        ],
        recommended_answer=None,
        risk_level=None,
        resolution_handler=policy.resolution_handler,
        autonomy_mode="banzai",
        source_state_revision=1,
        now="2026-08-20T10:45:00+00:00",
    )
    raw = store.load()
    raw.update(
        {
            "status": "blocked",
            "blocked_reason": decision["reason_code"],
            "escalation_question": decision["question"],
            "blocked_decision": decision,
            "recovery_instruction": RecoveryInstruction(
                kind=RecoveryKind.RESOLVE_DECISION,
                reason_code=str(decision["reason_code"]),
                phase=str(decision["source_phase"]),
                requires_human_input=False,
                schema_version=2,
                decision_id=str(decision["id"]),
            ).to_dict(),
        }
    )
    store._path.write_text(json.dumps(raw), encoding="utf-8")

    assert controller.resume_pending_human_input() is migrates

    persisted = store.load()["blocked_decision"]
    assert persisted["id"] == decision["id"]
    if migrates:
        assert persisted["schema_version"] == 3
        assert persisted["status"] == "resolved"
        assert persisted["selected_option_id"] == "approve"
        assert persisted["recommendation_followed"] is True
        assert persisted["resolution_rationale"] == rationale
        assert persisted["options"][0]["outcome"] is None
        provider.exec_agent.assert_called_once()
    else:
        assert persisted["schema_version"] == 2
        assert persisted["status"] == "failed"
        assert persisted["failure_code"] == (
            "decision_recommendation_unavailable"
        )
        assert persisted["options"][0]["outcome"] == legacy_outcome
        provider.exec_agent.assert_not_called()


def test_pending_v2_banzai_human_only_migrates_to_v3_human_resume(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy()
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    decision = build_blocked_decision_v2(
        decision_id="dec-legacy-banzai-human-only",
        status="pending",
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        source_phase="phase1-investigate",
        reason_code=policy.reason_code,
        classification=policy.classification,
        question="Which retained product boundary should be applied?",
        options=[],
        recommended_answer=None,
        risk_level=None,
        resolution_handler=policy.resolution_handler,
        autonomy_mode="banzai",
        source_state_revision=1,
        now="2026-08-20T11:00:00+00:00",
    )
    raw = store.load()
    raw.update(
        {
            "status": "blocked",
            "blocked_reason": decision["reason_code"],
            "escalation_question": decision["question"],
            "blocked_decision": decision,
            "recovery_instruction": RecoveryInstruction(
                kind=RecoveryKind.RESOLVE_DECISION,
                reason_code=str(decision["reason_code"]),
                phase=str(decision["source_phase"]),
                requires_human_input=False,
                schema_version=2,
                decision_id=str(decision["id"]),
            ).to_dict(),
        }
    )
    store._path.write_text(json.dumps(raw), encoding="utf-8")

    assert controller.resume_pending_human_input() is False

    waiting = store.load()["blocked_decision"]
    assert waiting["schema_version"] == 3
    assert waiting["id"] == decision["id"]
    assert waiting["status"] == "awaiting_human"
    assert waiting["automatic_eligible"] is False
    provider.exec_agent.assert_not_called()

    assert controller.resume_with_human_input("Use the retained public boundary.")
    resolved = store.load()["blocked_decision"]
    assert resolved["schema_version"] == 3
    assert resolved["id"] == decision["id"]
    assert resolved["status"] == "resolved"
    assert resolved["resolved_by"] == "user"
    assert resolved["recommendation_followed"] is None
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize("initial_status", ("pending", "resolving"))
def test_pending_or_resolving_v2_banzai_recovers_then_migrates_before_dispatch(
    tmp_path: Path,
    initial_status: str,
) -> None:
    policy = _choice_policy()
    rationale = "The current workflow recommendation remains authoritative."
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
        provider_result=_decision_result(
            rationale=rationale,
            confidence="medium",
        ),
    )
    created_at = "2026-08-20T11:45:00+00:00"
    decision = build_blocked_decision_v2(
        decision_id="dec-legacy-banzai-migration",
        status=initial_status,
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        source_phase="checkpoint-plan",
        reason_code=policy.reason_code,
        classification=policy.classification,
        question="Approve or reject the retained plan?",
        options=[
            {
                "id": option.id,
                "label": option.label,
                "description": option.description,
                "recommended": False,
                "risk_level": option.risk_level,
                "next_phase": option.next_phase,
                "outcome": option.outcome,
            }
            for option in policy.options
        ],
        recommended_answer=None,
        risk_level=None,
        resolution_handler=policy.resolution_handler,
        autonomy_mode="banzai",
        source_state_revision=1,
        attempts=1,
        now=created_at,
    )
    raw = store.load()
    raw.update(
        {
            "status": "blocked",
            "blocked_reason": decision["reason_code"],
            "escalation_question": decision["question"],
            "blocked_decision": decision,
            "recovery_instruction": RecoveryInstruction(
                kind=RecoveryKind.RESOLVE_DECISION,
                reason_code=str(decision["reason_code"]),
                phase=str(decision["source_phase"]),
                requires_human_input=False,
                schema_version=2,
                decision_id=str(decision["id"]),
            ).to_dict(),
        }
    )
    store._path.write_text(json.dumps(raw), encoding="utf-8")

    assert controller.resume_pending_human_input()

    resolved = store.load()["blocked_decision"]
    assert resolved["schema_version"] == 3
    assert resolved["id"] == decision["id"]
    assert resolved["created_at"] == created_at
    assert resolved["attempts"] == 2
    assert resolved["status"] == "resolved"
    assert resolved["selected_option_id"] == "approve"
    assert resolved["recommendation_followed"] is True
    assert resolved["resolution_rationale"] == rationale
    assert resolved["resolution_confidence"] == "medium"
    provider.exec_agent.assert_called_once()


def _controller_migration_prepared(
    controller: SquadController,
    store: SquadStateStore,
    producer_id: str,
):
    registry = controller._human_input_registry
    revision = store.load()["state_revision"]
    question = f"Retain the current {producer_id} controller decision?"
    if producer_id == "checkpoint-assess":
        return prepare_controller_checkpoint_assessment_decision(
            registry,
            reason_code="checkpoint_assess_decision_required",
            phase_id="checkpoint-assess",
            question=question,
            source_state_revision=revision,
            authority_kind="ordinary_pass",
            authority_evidence=(
                RecommendationEvidence(
                    id="checkpoint-assess:quality",
                    kind="phase1_quality_certificate",
                    reference="state:spec_quality_certificate",
                    digest="c" * 64,
                ),
            ),
        )
    if producer_id == "phase_dispatch_limit":
        candidate = _dispatch_cap_candidate()
        return prepare_controller_phase_dispatch_limit_decision(
            registry,
            reason_code="phase_dispatch_limit",
            phase_id="phase1-what",
            question=question,
            source_state_revision=revision,
            option_contract=controller._dispatch_cap_options([candidate]),
        )
    policy = registry.lookup(
        "controller_safeguard",
        producer_id,
        producer_id,
    )
    extension_exhausted = producer_id == (
        "proportional_quality_extension_exhausted"
    )
    return prepare_controller_proportional_quality_decision(
        registry,
        reason_code=producer_id,
        phase_id="phase1-why2",
        question=question,
        source_state_revision=revision,
        repair_state=_proportional_repair_state(
            extension_authorized=1 if extension_exhausted else 0,
            extension_consumed=1 if extension_exhausted else 0,
        ),
        recommendation_evidence=_proportional_recommendation_evidence(),
        option_contract=policy.options,
    )


def _seal_legacy_controller_migration(
    store: SquadStateStore,
    prepared,
) -> dict[str, object]:
    decision = build_blocked_decision_v2(
        decision_id=f"dec-migrate-{prepared.producer_id}",
        status="pending",
        source_kind=prepared.source_kind,
        producer_id=prepared.producer_id,
        source_phase=prepared.phase_id,
        reason_code=prepared.reason_code,
        classification=prepared.classification,
        question=prepared.question,
        options=[
            {
                "id": option.id,
                "label": option.label,
                "description": option.description,
                "recommended": False,
                "risk_level": option.risk_level,
                "next_phase": option.next_phase,
                "outcome": option.outcome,
            }
            for option in prepared.options
        ],
        recommended_answer=prepared.recommended_answer,
        risk_level=prepared.risk_level,
        resolution_handler=prepared.resolution_handler,
        autonomy_mode="banzai",
        source_state_revision=prepared.source_state_revision,
        now="2026-08-23T12:00:00+00:00",
    )
    state = store.load()
    state.update(
        {
            "status": "blocked",
            "phase": prepared.phase_id,
            "blocked_reason": prepared.reason_code,
            "blocked_decision": decision,
            "recovery_instruction": RecoveryInstruction(
                kind=RecoveryKind.RESOLVE_DECISION,
                reason_code=prepared.reason_code,
                phase=prepared.phase_id,
                requires_human_input=False,
                schema_version=2,
                decision_id=str(decision["id"]),
            ).to_dict(),
        }
    )
    store._path.write_text(json.dumps(state), encoding="utf-8")
    return decision


@pytest.mark.parametrize(
    "producer_id",
    (
        "checkpoint-assess",
        "phase_dispatch_limit",
        "proportional_quality_budget_exhausted",
        "proportional_quality_extension_exhausted",
    ),
)
def test_v2_controller_decision_restart_uses_registered_dynamic_preparer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    producer_id: str,
) -> None:
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    setup_policy = graph.human_input_policy_registry().lookup(
        "provider_escalation",
        "phase1-tracker",
        "human_clarification_required",
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=setup_policy,
    )
    controller._graph = graph
    controller._human_input_registry = graph.human_input_policy_registry()
    if producer_id == "checkpoint-assess":
        _seed_current_checkpoint_pass(monkeypatch, controller, store)
        question = "Retain the current checkpoint-assess controller decision?"
        prepared = controller._prepare_checkpoint_assessment_decision(
            store.load(),
            question=question,
            source_state_revision=store.load()["state_revision"],
        )
    else:
        if producer_id == "phase_dispatch_limit":
            spec_dir = Path(str(store.load()["spec_dir"]))
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "issues.md").write_text(
                """### ISS-001: Retry policy

### Resolution Guidance
- **Decision required:** Retry behavior.
- **Suggested option:** Use exponential backoff.
- **Evidence basis:** The API reference documents idempotent reads.
- **Banzai eligible:** yes
""",
                encoding="utf-8",
            )
        prepared = _controller_migration_prepared(controller, store, producer_id)
    decision = _seal_legacy_controller_migration(store, prepared)
    restarted = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=graph,
        ext_dir=ROOT / "runtime",
        project_root=tmp_path,
        squad_dir=store.squad_dir,
    )
    if producer_id == "checkpoint-assess":
        dynamic = MagicMock(
            wraps=restarted._prepare_checkpoint_assessment_decision
        )
        monkeypatch.setattr(
            restarted,
            "_prepare_checkpoint_assessment_decision",
            dynamic,
        )
    elif producer_id == "phase_dispatch_limit":
        candidates = MagicMock(
            wraps=restarted._banzai_issue_resolution_candidates
        )
        monkeypatch.setattr(
            restarted,
            "_banzai_issue_resolution_candidates",
            candidates,
        )
        dynamic = candidates
    else:
        dynamic = MagicMock(return_value=(prepared, {}))
        monkeypatch.setattr(
            restarted,
            "_prepare_proportional_quality_decision",
            dynamic,
        )

    migrated = restarted._migrate_pending_v2_banzai_decision(
        store.load(),
        decision,
    )

    assert migrated is not None
    sealed = store.load()["blocked_decision"]
    assert sealed["schema_version"] == 3
    assert sealed["id"] == decision["id"]
    assert sealed["producer_id"] == producer_id
    assert sealed["recommended_option_id"] == prepared.recommended_option_id
    dynamic.assert_called_once()
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize(
    "producer_id",
    (
        "checkpoint-assess",
        "phase_dispatch_limit",
        "proportional_quality_budget_exhausted",
    ),
)
def test_v2_controller_migration_missing_or_stale_authority_fails_pre_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    producer_id: str,
) -> None:
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    setup_policy = graph.human_input_policy_registry().lookup(
        "provider_escalation",
        "phase1-tracker",
        "human_clarification_required",
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=setup_policy,
    )
    controller._graph = graph
    controller._human_input_registry = graph.human_input_policy_registry()
    prepared = _controller_migration_prepared(controller, store, producer_id)
    decision = _seal_legacy_controller_migration(store, prepared)
    if producer_id == "checkpoint-assess":
        dynamic = MagicMock(
            wraps=controller._prepare_checkpoint_assessment_decision
        )
        monkeypatch.setattr(
            controller,
            "_prepare_checkpoint_assessment_decision",
            dynamic,
        )
    elif producer_id == "phase_dispatch_limit":
        dynamic = MagicMock(
            wraps=controller._banzai_issue_resolution_candidates
        )
        monkeypatch.setattr(
            controller,
            "_banzai_issue_resolution_candidates",
            dynamic,
        )
    else:
        dynamic = MagicMock(
            wraps=controller._prepare_proportional_quality_decision
        )
        monkeypatch.setattr(
            controller,
            "_prepare_proportional_quality_decision",
            dynamic,
        )

    assert controller._migrate_pending_v2_banzai_decision(
        store.load(),
        decision,
    ) is None

    failed = store.load()["blocked_decision"]
    assert failed["schema_version"] == 2
    assert failed["status"] == "failed"
    dynamic.assert_called_once()
    provider.exec_agent.assert_not_called()


def test_provider_v3_seal_survives_process_restart_with_same_decision_id(
    tmp_path: Path,
) -> None:
    answer = "Use the attested public contract."
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    policy = graph.human_input_policy_registry().lookup(
        "provider_escalation",
        "phase1-tracker",
        "human_clarification_required",
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    routing = _provider_routing_decision(store, policy)
    request = _automatic_free_text_request(
        controller,
        store,
        policy,
        recommended_answer=answer,
    )
    store.advance(
        policy.producer_id,
        policy.producer_id,
        routing,
        human_input=request,
        human_input_initial_status="pending",
    )
    sealed = store.load()
    decision_id = sealed["blocked_decision"]["id"]
    assert sealed["recovery_instruction"]["decision_id"] == decision_id

    provider = MagicMock()
    provider.exec_agent.return_value = _decision_result(
        selected_option_id=None,
        answer_text=answer,
    )
    restarted = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=graph,
        ext_dir=ROOT / "runtime",
        project_root=tmp_path,
        squad_dir=store.squad_dir,
    )

    assert restarted.resume_pending_human_input()
    resolved = store.load()["blocked_decision"]
    assert resolved["id"] == decision_id
    assert resolved["status"] == "resolved"
    assert resolved["resolved_by"] == "COMMANDER"
    provider.exec_agent.assert_called_once()


def _cli_awaiting_human_controller(
    tmp_path: Path,
) -> tuple[SquadController, SquadStateStore, object, str]:
    echelon_dir = tmp_path / ".echelon"
    shutil.copytree(ROOT / "runtime", echelon_dir / "runtime")
    shutil.copytree(ROOT / "prosaic", echelon_dir / "prosaic")
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    policy = graph.human_input_policy_registry().lookup(
        "provider_escalation",
        "phase1-investigate",
        "investigation_access_required",
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    state = store.load()
    decision = build_blocked_decision_v2(
        decision_id="dec-cli-legacy-awaiting-human",
        status="awaiting_human",
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        source_phase=next(iter(policy.allowed_phase_ids)),
        reason_code=policy.reason_code,
        classification=policy.classification,
        question="Which valid resolution should be applied?",
        options=[],
        recommended_answer=None,
        risk_level=None,
        resolution_handler=policy.resolution_handler,
        autonomy_mode="banzai",
        source_state_revision=int(state["state_revision"]),
    )
    state.update(
        {
            "status": "blocked",
            "blocked_reason": policy.reason_code,
            "escalation_question": decision["question"],
            "escalation_options": [],
            "blocked_decision": decision,
            "recovery_instruction": RecoveryInstruction(
                kind=RecoveryKind.AWAIT_HUMAN_ANSWER,
                reason_code=policy.reason_code,
                phase=str(decision["source_phase"]),
                requires_human_input=True,
                schema_version=2,
                decision_id=str(decision["id"]),
            ).to_dict(),
        }
    )
    store._path.write_text(json.dumps(state), encoding="utf-8")
    (tmp_path / ".git").mkdir(exist_ok=True)
    (tmp_path / "runs" / ".current").write_text(
        store.squad_dir.name,
        encoding="utf-8",
    )
    return controller, store, provider, store.load()["blocked_decision"]["id"]


def test_status_continue_and_resume_commands_observe_one_durable_decision_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_continue, _cmd_resume, _cmd_status

    _controller_instance, store, provider, decision_id = (
        _cli_awaiting_human_controller(tmp_path)
    )
    monkeypatch.setattr(
        "harness.squad_provider.SquadCliProvider",
        lambda _config: provider,
    )

    _cmd_status(tmp_path)
    assert decision_id in capsys.readouterr().out
    assert store.load()["blocked_decision"]["id"] == decision_id

    _cmd_continue(
        [],
        project_root=tmp_path,
        ext_dir=ROOT / "runtime",
    )
    assert decision_id in capsys.readouterr().out
    assert store.load()["blocked_decision"]["id"] == decision_id

    answer = (
        "One static greeting; no auth, persistence, routing, backend, deployment, "
        "or public hosting requirement; bootstrap is in scope; do not require "
        "compliance scan, axe suite, or Playwright visual-regression work."
    )
    _cmd_resume(
        [answer],
        project_root=tmp_path,
        ext_dir=ROOT / "runtime",
    )
    assert decision_id in capsys.readouterr().out
    resumed_state = store.load()
    resumed = resumed_state["blocked_decision"]
    assert resumed["id"] == decision_id
    assert resumed["status"] == "resolved"
    assert resumed["resolved_by"] == "user"
    clarification = Path(resumed_state["staging_dir"]) / "user-clarifications.md"
    assert answer in clarification.read_text(encoding="utf-8")
    policy_path = Path(resumed_state["staging_dir"]) / "feature-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    assert policy["scope"]["deployment"] == "descoped"
    assert policy["verification"]["accessibility_suite"] == "not_required"
    assert resumed_state["feature_policy"] == policy
    context = Path(resumed_state["context_dir"]) / "current-feature-context.md"
    assert "Authoritative Feature Policy" in context.read_text(encoding="utf-8")
    provider.exec_agent.assert_not_called()


def test_clarification_discards_stale_proportional_quality_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A material clarification cannot reuse quality evidence for old requirements."""
    from echelon.cli import _cmd_resume

    _controller_instance, store, provider, _decision_id = (
        _cli_awaiting_human_controller(tmp_path)
    )
    monkeypatch.setattr(
        "harness.squad_provider.SquadCliProvider",
        lambda _config: provider,
    )
    state = store.load()
    state.update(
        {
            "spec_authoring_mode": "proportional",
            "phase1_quality_repair": {
                "schema_version": 1,
                "authoring_mode": "proportional",
                "automatic_limit": 3,
                "automatic_consumed": 1,
                "extension_limit": 1,
                "extension_authorized": 0,
                "extension_consumed": 0,
                "migration_basis": "fresh",
                "baseline_candidate_id": "quality-candidate-0",
                "candidate_ids": ["quality-candidate-0"],
            },
            "quality_gate_remediation": {"kind": "proportional_quality"},
            "proportional_quality_candidate_evidence": {
                "current_candidate_id": "quality-candidate-0"
            },
        }
    )
    store.save(state)

    _cmd_resume(
        ["Use only the latest checkpoint."],
        project_root=tmp_path,
        ext_dir=ROOT / "runtime",
    )

    resumed = store.load()
    assert resumed["phase1_quality_repair"]["candidate_ids"] == []
    assert resumed["phase1_quality_repair"]["automatic_consumed"] == 0
    assert "quality_gate_remediation" not in resumed
    assert "proportional_quality_candidate_evidence" not in resumed
    capsys.readouterr()


@contextmanager
def _external_resume_lease(lock_type, lock_root: Path):
    acquired = Event()
    release = Event()
    failures: list[BaseException] = []

    def hold() -> None:
        try:
            with lock_type.acquire(lock_root, "external-resume-owner"):
                acquired.set()
                assert release.wait(timeout=5)
        except BaseException as error:
            failures.append(error)
            acquired.set()

    owner = Thread(target=hold)
    owner.start()
    assert acquired.wait(timeout=5)
    assert not failures
    try:
        yield
    finally:
        release.set()
        owner.join(timeout=5)
        assert not failures
        assert not owner.is_alive()


@pytest.mark.parametrize(
    ("lock_type", "root_selector"),
    [
        (PhaseAExecutionLock, lambda project_root, _run_dir: project_root),
        (SpecRunExecutionLock, lambda _project_root, run_dir: run_dir),
    ],
    ids=("phase_a_owner", "run_owner"),
)
def test_cli_resume_refuses_external_execution_owner_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lock_type,
    root_selector,
) -> None:
    from echelon.cli import _cmd_resume

    _controller_instance, store, provider, _decision_id = (
        _cli_awaiting_human_controller(tmp_path)
    )
    monkeypatch.setattr(
        "harness.squad_provider.SquadCliProvider",
        lambda _config: provider,
    )
    state_path = store.squad_dir / "state.json"
    before = json.loads(state_path.read_text(encoding="utf-8"))
    clarification = Path(store.load()["staging_dir"]) / "user-clarifications.md"

    with _external_resume_lease(
        lock_type,
        root_selector(tmp_path, store.squad_dir),
    ):
        with pytest.raises(SystemExit) as exc:
            _cmd_resume(
                ["Lease-blocked answer"],
                project_root=tmp_path,
                ext_dir=ROOT / "runtime",
            )

    assert exc.value.code == 1
    assert store.load() == before
    assert not clarification.exists()
    provider.exec_agent.assert_not_called()


def test_concurrent_cli_resume_keeps_decision_and_file_answer_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_resume

    _controller_instance, store, provider, _decision_id = (
        _cli_awaiting_human_controller(tmp_path)
    )
    monkeypatch.setattr(
        "harness.squad_provider.SquadCliProvider",
        lambda _config: provider,
    )
    entered = Event()
    release = Event()
    original_resume = SquadController.resume_with_human_input

    def coordinated_resume(self, answer):
        entered.set()
        assert release.wait(timeout=5)
        return original_resume(self, answer)

    monkeypatch.setattr(
        SquadController,
        "resume_with_human_input",
        coordinated_resume,
    )
    outcomes: dict[str, BaseException | None] = {}

    def submit_second() -> None:
        assert entered.wait(timeout=5)
        try:
            _cmd_resume(
                ["Answer B"],
                project_root=tmp_path,
                ext_dir=ROOT / "runtime",
            )
        except BaseException as error:
            outcomes["second"] = error
        else:
            outcomes["second"] = None
        finally:
            release.set()

    second = Thread(target=submit_second)
    second.start()
    _cmd_resume(
        ["Answer A"],
        project_root=tmp_path,
        ext_dir=ROOT / "runtime",
    )
    second.join(timeout=5)

    assert not second.is_alive()
    assert isinstance(outcomes["second"], SystemExit)
    state = store.load()
    assert state["blocked_decision"]["answer_text"] == "Answer A"
    clarification = Path(state["staging_dir"]) / "user-clarifications.md"
    assert "**Answer:** Answer A" in clarification.read_text(encoding="utf-8")
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize(
    ("phase_id", "reason_code", "producer_id", "classification", "handler"),
    [
        (
            "phase1-tracker",
            "human_clarification_required",
            "phase1-tracker",
            "material",
            "clarification_resume",
        ),
        (
            "phase1-why2",
            "why2_metric_stagnation",
            "why2_metric_stagnation",
            "material",
            "reset_why2_stagnation",
        ),
    ],
)
def test_legacy_squad_adapts_one_exact_current_policy_without_broadening(
    tmp_path: Path,
    phase_id: str,
    reason_code: str,
    producer_id: str,
    classification: str,
    handler: str,
) -> None:
    controller, store, provider = _legacy_workflow_controller(
        tmp_path,
        autonomy_mode="guided",
        phase_id=phase_id,
        reason_code=reason_code,
    )

    result = controller.run(
        user_message="registered user message",
        mode="banzai",
    )

    state = store.load()
    decision = state["blocked_decision"]
    assert result.status == "blocked"
    assert decision["schema_version"] == 3
    assert decision["source_kind"] == "legacy_recovery"
    assert decision["producer_id"] == producer_id
    assert decision["source_phase"] == phase_id
    assert decision["reason_code"] == reason_code
    assert decision["classification"] == classification
    assert decision["resolution_handler"] == handler
    assert decision["autonomy_mode"] == "guided"
    assert decision["status"] == "awaiting_human"
    assert state["recovery_instruction"]["decision_id"] == decision["id"]
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize(
    ("mode", "expected_status", "expected_resolver", "provider_calls"),
    [
        ("guided", "awaiting_human", None, 0),
        ("semi", "awaiting_human", None, 0),
        ("banzai", "awaiting_human", None, 0),
    ],
)
def test_run_single_phase_adapts_active_exact_legacy_question_before_manual_mutation(
    tmp_path: Path,
    mode: str,
    expected_status: str,
    expected_resolver: str | None,
    provider_calls: int,
) -> None:
    controller, store, provider = _legacy_workflow_controller(
        tmp_path,
        autonomy_mode=mode,
        phase_id="phase1-tracker",
        reason_code="human_clarification_required",
        provider_result=_decision_result(
            selected_option_id=None,
            answer_text="Use the bounded legacy answer.",
        ),
    )
    controller._refresh_run_context = MagicMock()
    controller._skip_phase_if_condition_false = MagicMock(return_value=True)

    result = controller.run_single_phase(
        "phase1-tracker",
        user_message="registered user message",
        mode=mode,
    )

    state = store.load()
    decision = state["blocked_decision"]
    assert decision["schema_version"] == 3
    assert decision["source_kind"] == "legacy_recovery"
    assert decision["status"] == expected_status
    assert decision["resolved_by"] == expected_resolver
    assert provider.exec_agent.call_count == provider_calls
    assert result.status == (
        "running" if expected_status == "resolved" else "blocked"
    )


def test_run_single_phase_rejects_malformed_active_legacy_question_before_mutation(
    tmp_path: Path,
) -> None:
    controller, store, provider = _legacy_workflow_controller(
        tmp_path,
        autonomy_mode="guided",
        phase_id="phase1-tracker",
        reason_code="human_clarification_required",
    )
    raw = json.loads(store._path.read_text(encoding="utf-8"))
    raw["blocked_decision"]["unexpected_authority"] = "must not be adapted"
    store._path.write_text(json.dumps(raw), encoding="utf-8")
    before = store._path.read_bytes()
    controller._refresh_run_context = MagicMock()

    result = controller.run_single_phase(
        "phase4-document",
        user_message="different manual input",
        mode="banzai",
        initial_state_updates={"manual_mutation": "must-not-commit"},
    )

    assert result.status == "blocked"
    assert store._path.read_bytes() == before
    assert "manual_mutation" not in store.load()
    provider.exec_agent.assert_not_called()


def test_legacy_terminal_safeguard_adapts_from_exact_resume_phase(
    tmp_path: Path,
) -> None:
    controller, store, provider = _legacy_workflow_controller(
        tmp_path,
        autonomy_mode="guided",
        phase_id="terminal-blocked",
        recovery_phase="phase1-why2",
        reason_code="why2_metric_stagnation",
    )

    result = controller.run(
        user_message="registered user message",
        mode="guided",
    )

    decision = store.load()["blocked_decision"]
    assert result.status == "blocked"
    assert decision["schema_version"] == 3
    assert decision["source_kind"] == "legacy_recovery"
    assert decision["producer_id"] == "why2_metric_stagnation"
    assert decision["source_phase"] == "phase1-why2"
    assert decision["resolution_handler"] == "reset_why2_stagnation"
    assert decision["status"] == "awaiting_human"
    provider.exec_agent.assert_not_called()


def test_legacy_terminal_dispatch_cap_requires_exact_sealed_option(
    tmp_path: Path,
) -> None:
    option = _dispatch_cap_option(_dispatch_cap_candidate())
    controller, store, provider = _legacy_workflow_controller(
        tmp_path,
        autonomy_mode="guided",
        phase_id="terminal-blocked",
        recovery_phase="phase1-what",
        reason_code="phase_dispatch_limit",
        recovery_kind=RecoveryKind.RESOLVE_ISSUE,
        options=[
            {
                "id": option.id,
                "label": option.label,
                "description": option.description,
                "recommended": option.recommended,
                "risk_level": option.risk_level,
                "next_phase": option.next_phase,
            }
        ],
    )

    result = controller.run(
        user_message="registered user message",
        mode="guided",
    )

    decision = store.load()["blocked_decision"]
    assert result.status == "blocked"
    assert decision["schema_version"] == 3
    assert decision["source_kind"] == "legacy_recovery"
    assert decision["producer_id"] == "phase_dispatch_limit"
    assert decision["source_phase"] == "phase1-what"
    assert decision["resolution_handler"] == "phase_dispatch_limit"
    assert decision["options"][0]["id"] == "ISS-001"
    assert decision["status"] == "awaiting_human"
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize(
    (
        "phase_id",
        "reason_code",
        "options",
        "decision_status",
        "recovery_kind",
    ),
    [
        (
            "phase1-tracker",
            "unknown_legacy_reason",
            [],
            "pending",
            RecoveryKind.AWAIT_HUMAN_ANSWER,
        ),
        (
            "phase1-tracker",
            "human_clarification_required",
            "not-a-list",
            "pending",
            RecoveryKind.AWAIT_HUMAN_ANSWER,
        ),
        (
            "terminal-blocked",
            "human_clarification_required",
            [],
            "pending",
            RecoveryKind.AWAIT_HUMAN_ANSWER,
        ),
        (
            "phase1-investigate",
            "human_input_required",
            [],
            "pending",
            RecoveryKind.AWAIT_HUMAN_ANSWER,
        ),
        (
            "phase1-tracker",
            "human_clarification_required",
            [],
            "resolved",
            RecoveryKind.AWAIT_HUMAN_ANSWER,
        ),
        (
            "phase1-tracker",
            "human_clarification_required",
            [],
            "pending",
            RecoveryKind.RESOLVE_ISSUE,
        ),
    ],
    ids=(
        "unknown_reason",
        "malformed_options",
        "terminal_without_handler",
        "ambiguous_investigate_reason",
        "already_resolved",
        "mismatched_resume_behavior",
    ),
)
def test_legacy_squad_rejects_unproven_or_terminal_recovery_state(
    tmp_path: Path,
    phase_id: str,
    reason_code: str,
    options: object,
    decision_status: str,
    recovery_kind: RecoveryKind,
) -> None:
    controller, store, provider = _legacy_workflow_controller(
        tmp_path,
        autonomy_mode="guided",
        phase_id=phase_id,
        reason_code=reason_code,
        options=options,
        decision_status=decision_status,
        recovery_kind=recovery_kind,
    )
    before = store.load()

    result = controller.run(
        user_message="registered user message",
        mode="guided",
    )

    assert result.status == "blocked"
    assert store.load() == before
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize(
    "malformation",
    (
        "boolean_schema",
        "unknown_field",
        "missing_blocked_at",
        "invalid_blocked_at",
        "pending_answer_metadata",
        "malformed_raw_options",
        "null_recommendation",
        "null_risk",
        "recommendation_projection_mismatch",
        "risk_projection_mismatch",
    ),
)
def test_legacy_squad_rejects_malformed_raw_v1_envelope(
    tmp_path: Path,
    malformation: str,
) -> None:
    controller, store, provider = _legacy_workflow_controller(
        tmp_path,
        autonomy_mode="guided",
        phase_id="phase1-tracker",
        reason_code="human_clarification_required",
    )
    state_path = store.squad_dir / "state.json"
    state = store.load()
    raw = state["blocked_decision"]
    if malformation == "boolean_schema":
        raw["schema_version"] = True
    elif malformation == "unknown_field":
        raw["unexpected_authority"] = "accepted"
    elif malformation == "missing_blocked_at":
        raw.pop("blocked_at")
    elif malformation == "invalid_blocked_at":
        raw["blocked_at"] = "not-a-timestamp"
    elif malformation == "pending_answer_metadata":
        raw["answer_text"] = "Already answered."
    elif malformation == "malformed_raw_options":
        raw["options"] = [{"malformed": True}]
    elif malformation == "null_recommendation":
        raw["recommended_answer"] = None
    elif malformation == "null_risk":
        raw["risk_level"] = None
    elif malformation == "recommendation_projection_mismatch":
        state["escalation_recommended_answer"] = "Use top-level authority."
        raw["recommended_answer"] = "Use durable authority."
    elif malformation == "risk_projection_mismatch":
        state["escalation_risk_level"] = "medium"
        raw["risk_level"] = "high"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    before = json.loads(state_path.read_text(encoding="utf-8"))

    result = controller.run(
        user_message="registered user message",
        mode="guided",
    )

    assert result.status == "blocked"
    assert store.load() == before
    provider.exec_agent.assert_not_called()


def test_legacy_squad_rejects_mismatched_durable_choice_projection(
    tmp_path: Path,
) -> None:
    option = _dispatch_cap_option(_dispatch_cap_candidate())
    top_level_options = [
        {
            "id": option.id,
            "label": option.label,
            "description": option.description,
            "recommended": option.recommended,
            "risk_level": option.risk_level,
            "next_phase": option.next_phase,
        }
    ]
    controller, store, provider = _legacy_workflow_controller(
        tmp_path,
        autonomy_mode="guided",
        phase_id="terminal-blocked",
        recovery_phase="phase1-what",
        reason_code="phase_dispatch_limit",
        recovery_kind=RecoveryKind.RESOLVE_ISSUE,
        options=top_level_options,
    )
    state_path = store.squad_dir / "state.json"
    state = store.load()
    state["blocked_decision"]["options"][0]["label"] = "Different durable label"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    before = json.loads(state_path.read_text(encoding="utf-8"))

    result = controller.run(
        user_message="registered user message",
        mode="guided",
    )

    assert result.status == "blocked"
    assert store.load() == before
    provider.exec_agent.assert_not_called()


def test_controller_rejects_registry_with_only_legacy_recovery_policy(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy(source_kind="legacy_recovery")
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    controller._human_input_registry = HumanInputPolicyRegistry((policy,))
    request = HumanInputPolicyRegistry((policy,)).prepare(
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        phase_id=next(iter(policy.allowed_phase_ids)),
        reason_code=policy.reason_code,
        question="Which exact boundary should be used?",
        source_state_revision=store.load()["state_revision"],
    )
    before = store.load()

    with pytest.raises(
        HumanInputPolicyError,
        match="one exact current policy",
    ):
        controller.handle_human_input(request)

    assert store.load() == before
    provider.exec_agent.assert_not_called()


def test_legacy_adapter_leaves_re_schema_v1_state_untouched(
    tmp_path: Path,
) -> None:
    controller, store, provider = _legacy_workflow_controller(
        tmp_path,
        autonomy_mode="guided",
        phase_id="phase1-tracker",
        reason_code="human_clarification_required",
    )
    state = store.load()
    state["run_kind"] = "re"
    store.save(state)
    before = store.load()

    result = controller.run(
        user_message="registered user message",
        mode="guided",
    )

    assert result.status == "blocked"
    assert store.load() == before
    assert before["blocked_decision"]["schema_version"] == 1
    provider.exec_agent.assert_not_called()


def test_legacy_provider_restart_reuses_decision_id_after_v3_seal(
    tmp_path: Path,
) -> None:
    answer = "Use the public contract boundary."
    controller, store, _provider = _legacy_workflow_controller(
        tmp_path,
        autonomy_mode="banzai",
        phase_id="phase1-tracker",
        reason_code="human_clarification_required",
        provider_result=_decision_result(
            selected_option_id=None,
            answer_text=answer,
        ),
        recommended_answer=answer,
        risk_level="low",
    )
    original_seal = store.set_human_input_decision

    def seal_then_crash(*args, **kwargs):
        original_seal(*args, **kwargs)
        raise RuntimeError("simulated restart after v3 seal")

    store.set_human_input_decision = MagicMock(side_effect=seal_then_crash)
    with pytest.raises(RuntimeError, match="simulated restart"):
        controller.run(
            user_message="registered user message",
            mode="banzai",
        )

    sealed = store.load()
    decision_id = sealed["blocked_decision"]["id"]
    assert sealed["blocked_decision"]["status"] == "pending"
    assert sealed["recovery_instruction"]["decision_id"] == decision_id

    provider = MagicMock()
    provider.exec_agent.return_value = _decision_result(
        selected_option_id=None,
        answer_text=answer,
    )
    restarted = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS),
        ext_dir=ROOT / "runtime",
        project_root=tmp_path,
        squad_dir=store.squad_dir,
    )

    assert restarted.resume_pending_human_input()
    resolved = store.load()
    assert resolved["blocked_decision"]["id"] == decision_id
    assert resolved["blocked_decision"]["status"] == "resolved"
    assert resolved["blocked_decision"]["resolved_by"] == "COMMANDER"
    provider.exec_agent.assert_called_once()


def test_human_input_handler_clarification_appends_decision_section_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _free_text_policy(source_kind="legacy_recovery")
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    decision_id, revision = _seal_awaiting_human(
        controller,
        store,
        policy,
        question="Which product boundary should be used?",
    )
    real_replace = os.replace
    replacements: list[tuple[Path, dict[str, object]]] = []

    def recording_replace(
        source: object,
        destination: object,
        **kwargs: object,
    ) -> None:
        replacements.append((Path(destination), kwargs))
        real_replace(source, destination, **kwargs)

    monkeypatch.setattr(squad_module.os, "replace", recording_replace)

    assert controller.apply_human_input_resolution(
        decision_id,
        expected_state_revision=revision,
        resolution=HumanInputResolution(
            selected_option_id=None,
            answer_text="Use the existing product boundary.",
            resolved_by="user",
        ),
    )

    state = store.load()
    clarification_path = Path(state["staging_dir"]) / "user-clarifications.md"
    clarification_replacements = [
        replacement
        for replacement in replacements
        if replacement[0] == Path("user-clarifications.md")
    ]
    assert len(clarification_replacements) == 1
    destination, replace_kwargs = clarification_replacements[0]
    assert destination == Path("user-clarifications.md")
    assert replace_kwargs["src_dir_fd"] == replace_kwargs["dst_dir_fd"]
    assert clarification_path.read_text(encoding="utf-8") == (
        f"## Decision {decision_id}\n\n"
        "**Question:** Which product boundary should be used?\n\n"
        "**Answer:** Use the existing product boundary.\n"
    )
    assert state["blocked_decision"]["status"] == "resolved"
    assert state["phase"] == policy.producer_id
    assert state["status"] == "running"
    assert "recovery_instruction" not in state
    assert "escalation_question" not in state


def test_clarification_idempotent_after_state_save_interruption(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy(source_kind="legacy_recovery")
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    decision_id, revision = _seal_awaiting_human(
        controller,
        store,
        policy,
        question="Which product boundary should be used?",
    )
    apply_state_resolution = store.apply_human_input_state_resolution
    store.apply_human_input_state_resolution = MagicMock(
        side_effect=RuntimeError("simulated state-save interruption"),
    )
    resolution = HumanInputResolution(
        selected_option_id=None,
        answer_text="Use the existing product boundary.",
        resolved_by="user",
    )

    with pytest.raises(RuntimeError, match="state-save interruption"):
        controller.apply_human_input_resolution(
            decision_id,
            expected_state_revision=revision,
            resolution=resolution,
        )

    clarification_path = (
        Path(store.load()["staging_dir"]) / "user-clarifications.md"
    )
    assert clarification_path.read_text(encoding="utf-8").count(
        f"## Decision {decision_id}"
    ) == 1

    conflicting = HumanInputResolution(
        selected_option_id=None,
        answer_text="Use a different product boundary.",
        resolved_by="user",
    )
    before = store.load()
    with pytest.raises(HumanInputPolicyError, match="clarification"):
        controller.apply_human_input_resolution(
            decision_id,
            expected_state_revision=revision,
            resolution=conflicting,
        )
    assert store.load() == before

    store.apply_human_input_state_resolution = MagicMock(
        wraps=apply_state_resolution,
    )
    assert controller.apply_human_input_resolution(
        decision_id,
        expected_state_revision=revision,
        resolution=resolution,
    )
    assert clarification_path.read_text(encoding="utf-8").count(
        f"## Decision {decision_id}"
    ) == 1
    store.apply_human_input_state_resolution.assert_called_once()


def test_clarification_resolution_replaces_stale_prior_decision_receipts(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy(source_kind="legacy_recovery")
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    decision_id, revision = _seal_awaiting_human(
        controller,
        store,
        policy,
        question="Should the current exception be accepted?",
    )
    clarification_path = Path(store.load()["staging_dir"]) / "user-clarifications.md"
    clarification_path.write_text(
        "## Decision dec-stale\n\n"
        "**Question:** Older escalation?\n\n"
        "**Answer:** (c) authorize extra remediation\n",
        encoding="utf-8",
    )

    assert controller.apply_human_input_resolution(
        decision_id,
        expected_state_revision=revision,
        resolution=HumanInputResolution(
            selected_option_id=None,
            answer_text="(a) accept the exception",
            resolved_by="user",
        ),
    )

    receipt = clarification_path.read_text(encoding="utf-8")
    assert f"## Decision {decision_id}" in receipt
    assert "(a) accept the exception" in receipt
    assert "dec-stale" not in receipt
    assert "(c) authorize extra remediation" not in receipt


def test_clarification_rejects_tampered_staging_root_without_outside_write(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy(source_kind="legacy_recovery")
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    _decision_id, _revision = _seal_awaiting_human(
        controller,
        store,
        policy,
    )
    outside = tmp_path.parent / f"{tmp_path.name}-clarification-outside"
    outside.mkdir()
    raw = json.loads(store._path.read_text(encoding="utf-8"))
    raw["staging_dir"] = str(outside)
    store._path.write_text(json.dumps(raw), encoding="utf-8")
    before = store._path.read_bytes()

    with pytest.raises(HumanInputPolicyError, match="staging|root|identity"):
        controller.resume_with_human_input("Use the contained answer.")

    assert store._path.read_bytes() == before
    assert not (outside / "user-clarifications.md").exists()
    assert not (store.staging_dir / "user-clarifications.md").exists()
    provider.exec_agent.assert_not_called()


def test_clarification_rejects_symlink_target_without_following_it(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy(source_kind="legacy_recovery")
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    _decision_id, _revision = _seal_awaiting_human(
        controller,
        store,
        policy,
    )
    outside = tmp_path / "outside-clarifications.md"
    outside.write_text("OUTSIDE CONTENT", encoding="utf-8")
    clarification = store.staging_dir / "user-clarifications.md"
    clarification.symlink_to(outside)
    before = store._path.read_bytes()

    with pytest.raises(HumanInputPolicyError, match="symlink|clarification"):
        controller.resume_with_human_input("Use the contained answer.")

    assert store._path.read_bytes() == before
    assert outside.read_text(encoding="utf-8") == "OUTSIDE CONTENT"
    assert clarification.is_symlink()
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize(
    "existing_section",
    [
        "## Decision {decision_id}\n",
        "## Decision {decision_id} \n",
        (
            "## Decision {decision_id}\n\n"
            "**Question:** Which product boundary should be used?\n\n"
            "**Answer:** A conflicting answer.\n"
        ),
    ],
)
def test_task6_fix_round1_clarification_rejects_conflicting_owned_section(
    tmp_path: Path,
    existing_section: str,
) -> None:
    policy = _free_text_policy(source_kind="legacy_recovery")
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    decision_id, revision = _seal_awaiting_human(
        controller,
        store,
        policy,
        question="Which product boundary should be used?",
    )
    clarification_path = (
        Path(store.load()["staging_dir"]) / "user-clarifications.md"
    )
    clarification_path.write_text(
        existing_section.format(decision_id=decision_id),
        encoding="utf-8",
    )
    before = store.load()

    with pytest.raises(HumanInputPolicyError, match="clarification"):
        controller.apply_human_input_resolution(
            decision_id,
            expected_state_revision=revision,
            resolution=HumanInputResolution(
                selected_option_id=None,
                answer_text="Use the existing product boundary.",
                resolved_by="user",
            ),
        )

    assert store.load() == before
    assert clarification_path.read_text(encoding="utf-8") == (
        existing_section.format(decision_id=decision_id)
    )


def test_task6_fix_round1_clarification_option_without_route_resumes_source(
    tmp_path: Path,
) -> None:
    source_phase = "phase1-investigate"
    policy = replace(
        _free_text_policy(source_kind="legacy_recovery"),
        allow_free_text=False,
        recommendation_mode="static",
        options=(
            HumanInputOption(
                id="use-answer",
                label="Use the supplied answer",
                description="Resume from the sealed source phase.",
                recommended=True,
                risk_level="low",
                next_phase=None,
                outcome=None,
            ),
        ),
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    decision_id, revision = _seal_awaiting_human(
        controller,
        store,
        policy,
        question="Which product boundary should be used?",
    )

    assert controller.apply_human_input_resolution(
        decision_id,
        expected_state_revision=revision,
        resolution=HumanInputResolution(
            selected_option_id="use-answer",
            answer_text=None,
            resolved_by="user",
        ),
    )
    assert store.load()["phase"] == source_phase


@pytest.mark.parametrize(
    ("option_id", "expected_phase", "expected_status", "expected_reason"),
    [
        ("approve", "phase4-document", "running", None),
        ("reject", "terminal-blocked", "blocked", "gate_rejected"),
    ],
)
def test_human_input_handler_gate_applies_declared_outcome(
    tmp_path: Path,
    option_id: str,
    expected_phase: str,
    expected_status: str,
    expected_reason: str | None,
) -> None:
    policy = _choice_policy()
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    decision_id, revision = _seal_awaiting_human(
        controller,
        store,
        policy,
    )
    store.apply_human_input_state_resolution = MagicMock(
        wraps=store.apply_human_input_state_resolution,
    )

    resolved = controller.apply_human_input_resolution(
        decision_id,
        expected_state_revision=revision,
        resolution=HumanInputResolution(
            selected_option_id=option_id,
            answer_text=None,
            resolved_by="user",
        ),
    )

    state = store.load()
    assert resolved is (expected_status == "running")
    assert state["phase"] == expected_phase
    assert state["status"] == expected_status
    assert state.get("blocked_reason") == expected_reason
    store.apply_human_input_state_resolution.assert_called_once()


@pytest.mark.parametrize(
    (
        "gate_id",
        "mode",
        "commander_option",
        "expected_phase",
        "expected_status",
        "expected_resolver",
    ),
    [
        (
            "checkpoint-assess",
            "guided",
            None,
            "checkpoint-assess",
            "awaiting_human",
            None,
        ),
        (
            "checkpoint-plan",
            "guided",
            None,
            "checkpoint-plan",
            "awaiting_human",
            None,
        ),
        (
            "checkpoint-assess",
            "semi",
            None,
            "checkpoint-assess",
            "awaiting_human",
            None,
        ),
        (
            "checkpoint-plan",
            "semi",
            None,
            "phase4-document",
            "resolved",
            "semi",
        ),
        (
            "checkpoint-assess",
            "banzai",
            "approve",
            "phase2-decide",
            "resolved",
            "COMMANDER",
        ),
        (
            "checkpoint-assess",
            "banzai",
            "reject",
            "terminal-blocked",
            "resolved",
            "COMMANDER",
        ),
        (
            "checkpoint-plan",
            "banzai",
            "approve",
            "phase4-document",
            "resolved",
            "COMMANDER",
        ),
        (
            "checkpoint-plan",
            "banzai",
            "reject",
            "terminal-blocked",
            "resolved",
            "COMMANDER",
        ),
    ],
)
def test_real_workflow_gate_mode_matrix_uses_controller_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_id: str,
    mode: str,
    commander_option: str | None,
    expected_phase: str,
    expected_status: str,
    expected_resolver: str | None,
) -> None:
    provider_result = (
        _decision_result(selected_option_id=commander_option)
        if commander_option is not None
        else None
    )
    controller, store, provider = _workflow_gate_controller(
        tmp_path,
        gate_id=gate_id,
        autonomy_mode=mode,
        provider_result=provider_result,
    )
    if gate_id == "checkpoint-assess":
        _seed_current_checkpoint_pass(monkeypatch, controller, store)

    controller._intercept_human_gate(controller._graph.get(gate_id))

    state = store.load()
    decision = state["blocked_decision"]
    assert state["phase"] == expected_phase
    assert decision["status"] == expected_status
    assert decision["resolved_by"] == expected_resolver
    assert "human_input_outcome" not in state
    assert provider.exec_agent.call_count == (
        1 if mode == "banzai" else 0
    )


def test_checkpoint_assess_pass_and_lexicon_prepare_approve_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, store, provider = _workflow_gate_controller(
        tmp_path,
        gate_id="checkpoint-assess",
        autonomy_mode="banzai",
        provider_result=_decision_result(selected_option_id="approve"),
    )
    _seed_current_checkpoint_pass(monkeypatch, controller, store)

    assert controller._intercept_human_gate(
        controller._graph.get("checkpoint-assess")
    )

    decision = store.load()["blocked_decision"]
    assert decision["recommended_option_id"] == "approve"
    assert {evidence["kind"] for evidence in decision["recommendation_evidence"]} == {
        "phase1_quality_certificate",
        "spec_lexicon_pass",
    }
    assert decision["recommendation_authority"] == "controller_evidence"
    provider.exec_agent.assert_called_once()


def test_real_v3_debt_acceptance_persists_one_canonical_decision_postimage(
    tmp_path: Path,
) -> None:
    _controller, store = _accept_real_v3_quality_debt(tmp_path)

    state = store.load()
    authorization = state["spec_quality_debt_authorization"]
    debt_path = tmp_path / str(authorization["debt_artifact"])
    debt = json.loads(debt_path.read_text(encoding="utf-8"))
    resolved = state["blocked_decision"]
    canonical = (
        json.dumps(
            resolved,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")

    assert resolved["schema_version"] == 3
    assert resolved == authorization["resolved_decision"]
    assert resolved == debt["resolved_decision"]
    assert authorization["resolved_decision_sha256"] == hashlib.sha256(
        canonical
    ).hexdigest()


@pytest.mark.parametrize("tamper", ["embedded_decision", "completion"])
def test_real_v3_debt_tampering_is_stale(
    tmp_path: Path,
    tamper: str,
) -> None:
    from harness.phase1_quality_debt import (
        has_current_quality_debt_authorization,
    )

    _controller, store = _accept_real_v3_quality_debt(tmp_path)
    state = store.load()
    assert has_current_quality_debt_authorization(
        state,
        project_root=tmp_path,
    )

    if tamper == "embedded_decision":
        authorization = dict(state["spec_quality_debt_authorization"])
        resolved = dict(authorization["resolved_decision"])
        resolved["resolution_rationale"] = "Tampered audit rationale."
        resolved["resolution_confidence"] = "low"
        authorization["resolved_decision"] = resolved
        state["spec_quality_debt_authorization"] = authorization
    else:
        completion = dict(state["last_human_input_completion"])
        completion["receipts_sha256"] = "f" * 64
        state["last_human_input_completion"] = completion

    assert not has_current_quality_debt_authorization(
        state,
        project_root=tmp_path,
    )


def test_debt_acceptance_aborts_before_publication_on_postimage_divergence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, store = _prepare_real_v3_quality_debt(tmp_path)
    before = store.load()
    original_builder = squad_module.build_quality_debt_authorization

    def divergent_builder(*args, **kwargs):
        prepared = original_builder(*args, **kwargs)
        authorization = json.loads(json.dumps(prepared.authorization))
        debt = json.loads(json.dumps(prepared.debt))
        divergent = dict(authorization["resolved_decision"])
        divergent.update(
            {
                "resolution_rationale": "Injected divergent audit.",
                "resolution_confidence": "low",
            }
        )
        divergent = validate_blocked_decision(divergent)
        decision_bytes = (
            json.dumps(
                divergent,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        decision_digest = hashlib.sha256(decision_bytes).hexdigest()
        for record in (authorization, debt):
            record["resolved_decision"] = divergent
            record["resolved_decision_sha256"] = decision_digest
        debt_bytes = (
            json.dumps(debt, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        authorization["debt_artifact_sha256"] = hashlib.sha256(
            debt_bytes
        ).hexdigest()
        return replace(
            prepared,
            authorization=authorization,
            debt=debt,
        )

    monkeypatch.setattr(
        squad_module,
        "build_quality_debt_authorization",
        divergent_builder,
    )

    with pytest.raises(StateAdvanceError, match="postimage"):
        controller.resume_with_human_input("continue_with_debt")

    state = store.load()
    assert state == before
    assert state["blocked_decision"]["status"] == "awaiting_human"
    assert "spec_quality_debt_authorization" not in state
    assert not (Path(str(state["spec_dir"])) / "quality-debt.json").exists()
    assert not list((store.squad_dir / ".completion-outbox").iterdir())


def test_debt_acceptance_aborts_on_completion_receipt_divergence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, store = _prepare_real_v3_quality_debt(tmp_path)
    before = store.load()
    original_builder = squad_module.build_quality_debt_authorization

    def divergent_builder(*args, **kwargs):
        prepared = original_builder(*args, **kwargs)
        authorization = json.loads(json.dumps(prepared.authorization))
        debt = json.loads(json.dumps(prepared.debt))
        for record in (authorization, debt):
            binding = dict(record["resolution_completion"])
            binding["completion_id"] = "f" * 32
            record["resolution_completion"] = binding
        debt_bytes = (
            json.dumps(debt, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        authorization["debt_artifact_sha256"] = hashlib.sha256(
            debt_bytes
        ).hexdigest()
        return replace(
            prepared,
            authorization=authorization,
            debt=debt,
        )

    monkeypatch.setattr(
        squad_module,
        "build_quality_debt_authorization",
        divergent_builder,
    )

    with pytest.raises(StateAdvanceError, match="postimage"):
        controller.resume_with_human_input("continue_with_debt")

    state = store.load()
    assert state == before
    assert not (Path(str(state["spec_dir"])) / "quality-debt.json").exists()
    assert not list((store.squad_dir / ".completion-outbox").iterdir())


@pytest.mark.parametrize(
    "divergence",
    ["alternate_debt_path", "alternate_preimage", "extra_shared_field"],
)
def test_debt_acceptance_rejects_unbound_effect_postimage_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    divergence: str,
) -> None:
    controller, store = _prepare_real_v3_quality_debt(tmp_path)
    state_path = store.squad_dir / "state.json"
    before = state_path.read_bytes()
    original_builder = squad_module.build_quality_debt_authorization
    alternate_path = "specs/alternate/quality-debt.json"

    def divergent_builder(*args, **kwargs):
        prepared = original_builder(*args, **kwargs)
        authorization = json.loads(json.dumps(prepared.authorization))
        debt = json.loads(json.dumps(prepared.debt))
        payload = json.loads(json.dumps(prepared.effect_payload()))
        payload["authorization"] = authorization
        payload["debt"] = debt
        if divergence == "alternate_debt_path":
            payload["debt_path"] = alternate_path
        elif divergence == "alternate_preimage":
            payload["previous_debt_artifact_sha256"] = "f" * 64
        else:
            authorization["injected_shared_field"] = "attacker-controlled"
            debt["injected_shared_field"] = "attacker-controlled"
            debt_bytes = (
                json.dumps(debt, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            authorization["debt_artifact_sha256"] = hashlib.sha256(
                debt_bytes
            ).hexdigest()
        return SimpleNamespace(
            authorization=authorization,
            debt=debt,
            debt_path=prepared.debt_path,
            effect_payload=lambda: payload,
        )

    monkeypatch.setattr(
        squad_module,
        "build_quality_debt_authorization",
        divergent_builder,
    )

    with pytest.raises(StateAdvanceError, match="postimage"):
        controller.resume_with_human_input("continue_with_debt")

    assert state_path.read_bytes() == before
    state = store.load()
    assert "pending_controller_completion" not in state
    assert not (Path(str(state["spec_dir"])) / "quality-debt.json").exists()
    assert not (tmp_path / alternate_path).exists()
    assert not list((store.squad_dir / ".completion-outbox").glob("*"))


def test_real_debt_checkpoint_preparation_reuses_decision_slot_without_staling(
    tmp_path: Path,
) -> None:
    from harness.phase1_quality_debt import (
        has_current_quality_debt_authorization,
    )

    controller, store = _accept_real_v3_quality_debt(tmp_path)
    accepted = store.load()
    debt_decision = accepted["blocked_decision"]
    assert has_current_quality_debt_authorization(
        accepted,
        project_root=tmp_path,
    )
    _advance_real_debt_fixture_to_checkpoint(store)

    controller._intercept_human_gate(
        controller._graph.get("checkpoint-assess")
    )

    checkpoint = store.load()
    assert checkpoint["blocked_decision"]["id"] != debt_decision["id"]
    assert checkpoint["blocked_decision"]["source_phase"] == (
        "checkpoint-assess"
    )
    assert has_current_quality_debt_authorization(
        checkpoint,
        project_root=tmp_path,
    )


def test_real_debt_survives_checkpoint_reject_reset_and_fresh_approval(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_rewind, _cmd_status
    from harness.phase_checkpoints import (
        create_phase_checkpoint,
        load_checkpoint_ledger,
    )
    from harness.phase1_quality_debt import (
        has_current_quality_debt_authorization,
    )

    controller, store = _accept_real_v3_quality_debt(tmp_path)
    assert has_current_quality_debt_authorization(
        store.load(),
        project_root=tmp_path,
    )
    _advance_real_debt_fixture_to_checkpoint(store)
    checkpoint_state = store.load()
    subprocess.run(
        ["git", "branch", "-m", checkpoint_state["spec_id"]],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    active_spec_dir = Path(str(checkpoint_state["spec_dir"]))
    if not active_spec_dir.is_absolute():
        active_spec_dir = tmp_path / active_spec_dir
    checkpoint = create_phase_checkpoint(
        project_root=tmp_path,
        spec_dir=active_spec_dir,
        phase="phase1-lexicon",
        next_phase="checkpoint-assess",
        run_id=str(checkpoint_state["run_id"]),
        spec_id=str(checkpoint_state["spec_id"]),
        force_commit=True,
    )
    assert load_checkpoint_ledger(active_spec_dir).checkpoints[-1] == checkpoint

    after_checkpoint = tmp_path / "after-checkpoint.txt"
    after_checkpoint.write_text("must be removed by rewind\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", after_checkpoint.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "post-checkpoint evidence"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    controller._intercept_human_gate(
        controller._graph.get("checkpoint-assess")
    )
    controller.resume_with_human_input("reject")
    rejected = store.load()
    assert rejected["phase"] == "terminal-blocked"
    assert rejected["blocked_decision"]["selected_option_id"] == "reject"
    assert has_current_quality_debt_authorization(
        rejected,
        project_root=tmp_path,
    )

    _cmd_status(tmp_path)
    status_output = capsys.readouterr().out
    command = next(
        line.strip()
        for line in status_output.splitlines()
        if line.strip().startswith("echelon spec rewind ")
    )
    assert command == (
        "echelon spec rewind phase1-lexicon "
        "--next-phase checkpoint-assess --confirm"
    )
    _cmd_rewind(shlex.split(command)[3:], project_root=tmp_path)
    rewind_output = capsys.readouterr().out
    assert "REWIND COMPLETE" in rewind_output
    assert subprocess.run(
        ["git", "rev-parse", "HEAD^{commit}"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == checkpoint.commit
    assert not after_checkpoint.exists()
    assert store.load()["phase"] == "phase1-lexicon"
    assert has_current_quality_debt_authorization(
        store.load(),
        project_root=tmp_path,
    )

    _advance_real_debt_fixture_to_checkpoint(store)
    controller._intercept_human_gate(
        controller._graph.get("checkpoint-assess")
    )
    fresh = store.load()["blocked_decision"]
    assert fresh["status"] == "awaiting_human"
    assert fresh["selected_option_id"] is None
    assert has_current_quality_debt_authorization(
        store.load(),
        project_root=tmp_path,
    )

    assert controller.resume_with_human_input("approve") is True
    approved = store.load()
    assert approved["phase"] == "phase2-decide"
    assert approved["blocked_decision"]["selected_option_id"] == "approve"
    assert has_current_quality_debt_authorization(
        approved,
        project_root=tmp_path,
    )
    assert controller._guard_phase1_quality_evidence("phase2-decide") == (
        "phase2-decide"
    )
    assert store.load()["phase"] != "phase1-understanding"


def test_checkpoint_assess_accepted_debt_keeps_fail_evidence_authorized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, store, provider = _workflow_gate_controller(
        tmp_path,
        gate_id="checkpoint-assess",
        autonomy_mode="banzai",
        provider_result=_decision_result(selected_option_id="approve"),
    )
    resolver = _seed_current_checkpoint_debt(monkeypatch, store)

    assert controller._intercept_human_gate(
        controller._graph.get("checkpoint-assess")
    )

    decision = store.load()["blocked_decision"]
    assert decision["recommended_option_id"] == "approve"
    assert "accepted_with_debt" in decision["recommendation_rationale"]
    assert resolver in decision["recommendation_rationale"]
    assert any(
        evidence["kind"] == "quality_gate_failure"
        for evidence in decision["recommendation_evidence"]
    )
    prompt = provider.exec_agent.call_args.args[1]
    assert prompt.index("## Authoritative Recommendation") < prompt.index(
        "## Registered Context"
    )
    assert "authorized debt" in prompt
    assert "quality_gate_failure" in prompt
    assert "Verdict: FAIL" in prompt


def test_checkpoint_assess_accepted_debt_reserves_raw_fail_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, store, provider = _workflow_gate_controller(
        tmp_path,
        gate_id="checkpoint-assess",
        autonomy_mode="banzai",
        provider_result=_decision_result(selected_option_id="approve"),
    )
    _seed_current_checkpoint_debt(monkeypatch, store)
    spec_dir = Path(str(store.load()["spec_dir"]))
    (spec_dir / "spec.md").write_text(
        "# Oversized specification\n" + ("x" * 1_000_000),
        encoding="utf-8",
    )

    assert controller._intercept_human_gate(
        controller._graph.get("checkpoint-assess")
    )

    prompt = provider.exec_agent.call_args.args[1]
    assert len(prompt.encode("utf-8")) <= (
        squad_module.COMMANDER_DECISION_PROMPT_MAX_BYTES
    )
    assert "authorized debt" in prompt
    assert "### File {spec_dir}/quality-gates.md" in prompt
    assert "Verdict: FAIL" in prompt


@pytest.mark.parametrize("authority_state", ("missing", "stale"))
def test_checkpoint_assess_missing_or_stale_authority_blocks_before_provider(
    tmp_path: Path,
    authority_state: str,
) -> None:
    controller, store, provider = _workflow_gate_controller(
        tmp_path,
        gate_id="checkpoint-assess",
        autonomy_mode="banzai",
        provider_result=_decision_result(selected_option_id="approve"),
    )
    if authority_state == "stale":
        state = store.load()
        state["completed_phases"] = ["phase1-why2"]
        state["spec_quality_certificate"] = {
            "schema_version": 2,
            "status": "passed",
            "source_path": "spec/spec.md",
            "source_sha256": "0" * 64,
            "sage_evidence": "spec/issues.md",
            "sage_evidence_sha256": "0" * 64,
            "sage_verdict": "PASS",
        }
        store.save(state)
    before_revision = store.load()["state_revision"]

    assert controller._intercept_human_gate(
        controller._graph.get("checkpoint-assess")
    ) is False

    state = store.load()
    assert state["state_revision"] == before_revision + 1
    assert state["status"] == "blocked"
    assert state["phase"] == "checkpoint-assess"
    assert state["blocked_reason"] == "decision_recommendation_unavailable"
    assert state["recovery_instruction"] == RecoveryInstruction(
        kind=RecoveryKind.RETRY_PHASE,
        reason_code="decision_recommendation_unavailable",
        phase="checkpoint-assess",
        requires_human_input=False,
    ).to_dict()
    assert "blocked_decision" not in state
    provider.exec_agent.assert_not_called()


def test_checkpoint_assess_stale_debt_retires_resolved_authority_for_restart(
    tmp_path: Path,
) -> None:
    controller, store, provider = _workflow_gate_controller(
        tmp_path,
        gate_id="checkpoint-plan",
        autonomy_mode="banzai",
        provider_result=_decision_result(selected_option_id="approve"),
    )
    assert controller._intercept_human_gate(
        controller._graph.get("checkpoint-plan")
    )
    resolved = validate_blocked_decision(
        store.load()["blocked_decision"]
    )
    assert resolved["schema_version"] == 3
    assert resolved["status"] == "resolved"

    state = store.load()
    state["phase"] = "checkpoint-assess"
    stale_authorization = {
        "schema_version": 1,
        "status": "accepted_with_debt",
        "resolved_by": "user",
        "decision_id": resolved["id"],
        "debt_artifact": "spec/quality-debt.json",
        "debt_artifact_sha256": "4" * 64,
        "resolved_decision": resolved,
        "resolved_decision_sha256": "5" * 64,
    }
    state["spec_quality_debt_authorization"] = stale_authorization
    store.save(state)
    provider.exec_agent.reset_mock()

    assert controller._intercept_human_gate(
        controller._graph.get("checkpoint-assess")
    ) is False

    persisted = store.load()
    assert persisted["status"] == "blocked"
    assert persisted["phase"] == "checkpoint-assess"
    assert persisted["blocked_reason"] == (
        "decision_recommendation_unavailable"
    )
    assert "blocked_decision" not in persisted
    assert persisted["spec_quality_debt_authorization"] == (
        stale_authorization
    )
    provider.exec_agent.assert_not_called()

    restarted_store = SquadStateStore(store.squad_dir)
    restarted_provider = MagicMock()
    restarted = SquadController(
        provider=restarted_provider,
        state_store=restarted_store,
        phase_graph=PhaseGraph(
            DEFINITION,
            prosaic_subagents_dir=PROSAIC_SUBAGENTS,
        ),
        ext_dir=ROOT / "runtime",
        project_root=tmp_path,
        squad_dir=store.squad_dir,
    )
    restarted_state = restarted_store.load()
    assert restarted_state == persisted
    recovery = validate_recovery_instruction(
        restarted_state["recovery_instruction"]
    )
    assert recovery.kind is RecoveryKind.RETRY_PHASE
    assert recovery.phase == "checkpoint-assess"
    assert restarted.resume_pending_human_input() is False
    assert restarted_store.load() == persisted
    restarted_provider.exec_agent.assert_not_called()


@pytest.mark.parametrize(
    ("producer_id", "reason_code", "extra_updates"),
    [
        ("phase1-tracker", "human_clarification_required", {}),
        ("phase1-why1", "human_clarification_required", {}),
        (
            "phase1-why2",
            "human_clarification_required",
            {
                "evidence_resolution_status": "not_required",
                "finding_routes": {"findings": []},
            },
        ),
        (
            "phase1-investigate",
            "human_clarification_required",
            {"evidence_resolution_status": "inconclusive"},
        ),
        (
            "phase1-investigate",
            "investigation_access_required",
            {"evidence_resolution_status": "access_required"},
        ),
        (
            "phase2-tracker-alignment",
            "human_clarification_required",
            {},
        ),
    ],
)
def test_real_provider_and_executor_accept_each_declared_question_contract(
    tmp_path: Path,
    producer_id: str,
    reason_code: str,
    extra_updates: dict,
) -> None:
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    policy = graph.human_input_policy_registry().lookup(
        "provider_escalation",
        producer_id,
        reason_code,
    )
    node = graph.get(producer_id)
    payload = {
        "verdict": "STOP_AND_ASK",
        "state_updates": {
            **extra_updates,
            "status": "blocked",
            "blocked_reason": reason_code,
            "escalation_question": "Which bounded decision should be applied?",
            "escalation_recommended_answer": "Use the evidence-backed default.",
            "escalation_risk_level": "low",
        },
        "journal_entries": [],
    }

    class FakeBackend:
        def run_prompt(self, request: CliRunRequest) -> CliRunResult:
            raise AssertionError("question validation must use run_agent")

        def run_agent(self, request: CliRunRequest) -> CliRunResult:
            return CliRunResult(
                exit_code=0,
                stdout=yaml.safe_dump(
                    {"echelon_result": payload},
                    sort_keys=False,
                ),
                stderr="",
            )

    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="codex"),
    )
    provider = SquadCliProvider(config)
    provider._backend = FakeBackend()
    controller, _store, _provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
        provider=provider,
    )
    contract = node.result_contract()

    normalized = provider.exec_agent(
        str(tmp_path),
        "Return the supplied question result.",
        result_contract=contract,
        allow_result_repair=False,
    )

    assert normalized.echelon_result == payload
    assert normalized.quarantined_state_updates == {}
    validated = controller._executors["agent"]._validate_result_state_updates(
        node,
        normalized,
        result_contract=contract,
    )
    assert validated.echelon_result == payload
    assert validated.verdict == "STOP_AND_ASK"


def test_controller_blocks_malformed_provider_options_before_decision_sealing(
    tmp_path: Path,
) -> None:
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    policy = graph.human_input_policy_registry().lookup(
        "provider_escalation",
        "phase1-tracker",
        "human_clarification_required",
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    controller._graph = graph
    controller._human_input_registry = graph.human_input_policy_registry()
    result = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "STOP_AND_ASK",
            "state_updates": {
                "status": "blocked",
                "blocked_reason": "human_clarification_required",
                "escalation_question": "Which bounded decision should be applied?",
                "escalation_options": [
                    {
                        "id": "one",
                        "label": "Same",
                        "description": "First bounded route.",
                        "recommended": True,
                        "risk_level": "low",
                        "next_phase": "phase1-tracker",
                    },
                    {
                        "id": "two",
                        "label": "Same",
                        "description": "Second bounded route.",
                        "recommended": False,
                        "risk_level": "low",
                        "next_phase": "phase1-tracker",
                    },
                ],
            },
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=1,
        timed_out=False,
    )

    node = graph.get("phase1-tracker")
    snapshot = store.capture_routing_snapshot(expected_phase=node.id)
    prepared = controller._prepare_phase_result(node, result, snapshot)
    before = store.load()

    with pytest.raises(HumanInputPolicyError, match="duplicate option label"):
        controller._prepare_provider_human_input(node, prepared, snapshot)

    assert store.load() == before


def test_human_input_handler_phase_dispatch_limit_reuses_issue_lifecycle(
    tmp_path: Path,
) -> None:
    policy = replace(
        _safeguard_policy(
            "phase_dispatch_limit",
            phase_id="phase1-what",
        ),
        allow_free_text=False,
        allowed_target_phases=frozenset({"phase1-what"}),
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "issues.md").write_text(
        """### ISS-001: Retry policy

### Resolution Guidance
- **Decision required:** Retry behavior.
- **Suggested option:** Use exponential backoff.
- **Evidence basis:** The API reference documents idempotent reads.
- **Banzai eligible:** yes
""",
        encoding="utf-8",
    )
    state = store.load()
    state.update(
        {
            "phase_dispatch_counts": {"phase1-what": 6, "phase1-why1": 2},
        }
    )
    store.save(state)
    candidate = _dispatch_cap_candidate()
    decision_id, revision = _seal_dispatch_cap_decision(
        controller,
        store,
        policy,
        (candidate,),
    )

    assert controller.apply_human_input_resolution(
        decision_id,
        expected_state_revision=revision,
        resolution=HumanInputResolution(
            selected_option_id="ISS-001",
            answer_text=None,
            resolved_by="user",
        ),
    )

    state = store.load()
    assert state["phase"] == "phase1-what"
    assert state["phase_dispatch_counts"] == {"phase1-why1": 2}
    assert state["phase_dispatch_limit_recovery"]["phase"] == "phase1-what"
    assert state["issue_resolution_ledger"]["ISS-001"]["status"] == "selected"
    assert state["issue_resolution_recovery"]["to_phase"] == "phase1-what"
    assert state["issue_resolution_repair_baseline"]["issue_id"] == "ISS-001"


def test_dispatch_cap_routes_phase3_issue_to_its_capable_owner_and_resets_corridor(
    tmp_path: Path,
) -> None:
    policy = replace(
        _safeguard_policy(
            "phase_dispatch_limit",
            phase_id="phase3-tasks-lexicon",
        ),
        allow_free_text=False,
        allowed_target_phases=frozenset(
            {"phase1-what", "phase3-how", "phase3-sentinel", "phase3-plan"}
        ),
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "issues.md").write_text(
        """### ISS-001: Coverage handoff is stale

- **Responsible agent:** SENTINEL
- **Action Required:** Amend coverage-map.md from the current task plan.

### Resolution Guidance
- **Decision required:** No user decision — agent repair
- **Suggested option:** Align coverage evidence with T-009, T-012, and T-013.
- **Evidence basis:** Current tasks.md and dependencies.md.
- **Banzai eligible:** yes
""",
        encoding="utf-8",
    )
    state = store.load()
    state["phase"] = "phase3-tasks-lexicon"
    state["phase_dispatch_counts"] = {
        "phase1-tracker": 2,
        "phase3-how": 4,
        "phase3-sentinel": 5,
        "phase3-plan": 6,
        "phase3-tasks-lexicon": 6,
        "phase3-understanding": 4,
        "phase3-consensus": 4,
        "phase3-consensus-tasks-lexicon": 4,
    }
    store.save(state)

    candidates = controller._banzai_issue_resolution_candidates(store.load())
    assert candidates[0]["repair_phase"] == "phase3-sentinel"
    options = controller._dispatch_cap_options(candidates)
    assert options[0].next_phase == "phase3-sentinel"
    decision_id, revision = _seal_dispatch_cap_decision(
        controller,
        store,
        policy,
        tuple(candidates),
        phase_id="phase3-tasks-lexicon",
    )

    assert controller.apply_human_input_resolution(
        decision_id,
        expected_state_revision=revision,
        resolution=HumanInputResolution(
            selected_option_id="ISS-001",
            answer_text=None,
            resolved_by="user",
        ),
    )

    resolved = store.load()
    assert resolved["phase"] == "phase3-sentinel"
    assert resolved["phase_dispatch_counts"] == {"phase1-tracker": 2}
    assert resolved["issue_resolution_ledger"]["ISS-001"]["repair_phase"] == (
        "phase3-sentinel"
    )
    assert resolved["issue_resolution_recovery"]["to_phase"] == "phase3-sentinel"
    assert resolved["phase_dispatch_limit_recovery"]["phase"] == (
        "phase3-tasks-lexicon"
    )


def test_dispatch_cap_rejects_evidence_drift_after_sealing(
    tmp_path: Path,
) -> None:
    policy = replace(
        _safeguard_policy(
            "phase_dispatch_limit",
            phase_id="phase1-what",
        ),
        allow_free_text=False,
        allowed_target_phases=frozenset({"phase1-what"}),
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    issues_path = spec_dir / "issues.md"
    issues_path.write_text(
        """### ISS-001: Retry policy

### Resolution Guidance
- **Decision required:** Retry behavior.
- **Suggested option:** Use exponential backoff.
- **Evidence basis:** The API reference documents idempotent reads.
- **Banzai eligible:** yes
""",
        encoding="utf-8",
    )
    state = store.load()
    state["phase_dispatch_counts"] = {"phase1-what": 6}
    store.save(state)
    sealed_candidate = _dispatch_cap_candidate()
    decision_id, revision = _seal_dispatch_cap_decision(
        controller,
        store,
        policy,
        (sealed_candidate,),
    )
    issues_path.write_text(
        """### ISS-002: New issue

### Resolution Guidance
- **Decision required:** New behavior.
- **Suggested option:** Use a new answer.
- **Evidence basis:** New evidence appeared after sealing.
- **Banzai eligible:** yes
""",
        encoding="utf-8",
    )
    before = store.load()
    with pytest.raises(HumanInputPolicyError, match="unknown option"):
        controller.apply_human_input_resolution(
            decision_id,
            expected_state_revision=revision,
            resolution=HumanInputResolution(
                selected_option_id="ISS-002",
                answer_text=None,
                resolved_by="user",
            ),
        )
    assert store.load() == before

    with pytest.raises(HumanInputPolicyError, match="evidence.*changed"):
        controller.apply_human_input_resolution(
            decision_id,
            expected_state_revision=revision,
            resolution=HumanInputResolution(
                selected_option_id="ISS-001",
                answer_text=None,
                resolved_by="user",
            ),
        )

    assert store.load() == before


def test_dispatch_cap_accepts_legacy_candidate_description(
    tmp_path: Path,
) -> None:
    policy = replace(
        _safeguard_policy(
            "phase_dispatch_limit",
            phase_id="phase1-what",
        ),
        allow_free_text=False,
        allowed_target_phases=frozenset({"phase1-what"}),
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "issues.md").write_text(
        """### ISS-001: Retry policy

### Resolution Guidance
- **Decision required:** Retry behavior.
- **Suggested option:** Use exponential backoff.
- **Evidence basis:** The API reference documents idempotent reads.
- **Banzai eligible:** yes
""",
        encoding="utf-8",
    )
    decision_id, revision = _seal_dispatch_cap_decision(
        controller,
        store,
        policy,
        (_dispatch_cap_candidate(),),
        legacy=True,
    )

    assert controller.apply_human_input_resolution(
        decision_id,
        expected_state_revision=revision,
        resolution=HumanInputResolution(
            selected_option_id="ISS-001",
            answer_text=None,
            resolved_by="user",
        ),
    )
    assert store.load()["selected_issue_resolution"] == "ISS-001"


def test_dispatch_cap_accepts_pending_schema1_reference_without_route_rewrite(
    tmp_path: Path,
) -> None:
    policy = replace(
        _safeguard_policy(
            "phase_dispatch_limit",
            phase_id="phase3-tasks-lexicon",
        ),
        allow_free_text=False,
        allowed_target_phases=frozenset(
            {"phase1-what", "phase3-how", "phase3-sentinel", "phase3-plan"}
        ),
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "issues.md").write_text(
        """### ISS-001: Retry policy

- **Responsible agent:** SENTINEL
- **Action Required:** Repair the test handoff.

### Resolution Guidance
- **Decision required:** Retry behavior.
- **Suggested option:** Use exponential backoff.
- **Evidence basis:** The API reference documents idempotent reads.
- **Banzai eligible:** yes
""",
        encoding="utf-8",
    )
    state = store.load()
    state["phase"] = "phase3-tasks-lexicon"
    store.save(state)
    candidate = _dispatch_cap_candidate()
    legacy_reference = json.dumps(
        {
            "evidence_sha256": controller._dispatch_cap_candidate_digest(
                candidate
            ),
            "issue_id": candidate["issue_id"],
            "schema_version": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    option = HumanInputOption(
        id=candidate["issue_id"],
        label=f"{candidate['issue_id']}: {candidate['title']}",
        description=legacy_reference,
        recommended=False,
        risk_level="medium",
        next_phase="phase1-what",
        outcome=None,
    )
    request = controller._human_input_registry.prepare_controller(
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        phase_id="phase3-tasks-lexicon",
        reason_code=policy.reason_code,
        question="Select one sealed evidence-backed issue resolution.",
        source_state_revision=store.load()["state_revision"],
        option_contract=(option,),
    )
    store.set_human_input_decision(request, initial_status="awaiting_human")
    sealed = store.load()

    assert controller.apply_human_input_resolution(
        sealed["blocked_decision"]["id"],
        expected_state_revision=sealed["state_revision"],
        resolution=HumanInputResolution(
            selected_option_id="ISS-001",
            answer_text=None,
            resolved_by="user",
        ),
    )

    assert store.load()["phase"] == "phase1-what"


def test_task6_fix_round1_dispatch_cap_rejects_conflicting_legacy_phase(
    tmp_path: Path,
) -> None:
    policy = replace(
        _safeguard_policy(
            "phase_dispatch_limit",
            phase_id="phase1-what",
        ),
        allow_free_text=False,
        allowed_target_phases=frozenset({"phase1-what"}),
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "issues.md").write_text(
        """### ISS-001: Retry policy

### Resolution Guidance
- **Decision required:** Retry behavior.
- **Suggested option:** Use exponential backoff.
- **Evidence basis:** The API reference documents idempotent reads.
- **Banzai eligible:** yes
""",
        encoding="utf-8",
    )
    state = store.load()
    state.update(
        {
            "phase_dispatch_limit_phase": "phase1-why1",
            "phase_dispatch_counts": {"phase1-what": 6, "phase1-why1": 2},
        }
    )
    store.save(state)
    decision_id, revision = _seal_dispatch_cap_decision(
        controller,
        store,
        policy,
        (_dispatch_cap_candidate(),),
    )
    before = store.load()

    with pytest.raises(HumanInputPolicyError, match="phase"):
        controller.apply_human_input_resolution(
            decision_id,
            expected_state_revision=revision,
            resolution=HumanInputResolution(
                selected_option_id="ISS-001",
                answer_text=None,
                resolved_by="user",
            ),
        )

    assert store.load() == before


@pytest.mark.parametrize(
    ("producer_id", "initial_counters", "expected_counters"),
    [
        (
            "consecutive_why_fails",
            {"why_fail_count": 2, "why2_metric_stagnation_count": 1},
            {"why_fail_count": 0, "why2_metric_stagnation_count": 1},
        ),
        (
            "why2_metric_stagnation",
            {"why_fail_count": 3, "why2_metric_stagnation_count": 2},
            {"why_fail_count": 0, "why2_metric_stagnation_count": 0},
        ),
    ],
)
def test_human_input_handler_why_safeguards_reset_owned_counters(
    tmp_path: Path,
    producer_id: str,
    initial_counters: dict[str, int],
    expected_counters: dict[str, int],
) -> None:
    policy = _safeguard_policy(
        producer_id,
        phase_id="phase1-why2",
        setter_compatible=True,
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    state = store.load()
    state.update(initial_counters)
    store.save(state)
    decision_id, revision = _seal_awaiting_human(
        controller,
        store,
        policy,
    )

    assert controller.apply_human_input_resolution(
        decision_id,
        expected_state_revision=revision,
        resolution=HumanInputResolution(
            selected_option_id=None,
            answer_text="Retry the declared WHY2 assessment.",
            resolved_by="user",
        ),
    )

    state = store.load()
    assert state["phase"] == "phase1-why2"
    assert state["status"] == "running"
    for key, value in expected_counters.items():
        assert state[key] == value


@pytest.mark.parametrize(
    "fault",
    [
        "answer",
        "handler",
        "id",
        "option",
        "outcome",
        "resolver",
        "revision",
        "target",
    ],
)
def test_human_input_handler_invalid_resolution_writes_nothing(
    tmp_path: Path,
    fault: str,
) -> None:
    case_root = tmp_path / fault
    if fault == "target":
        policy = HumanInputPolicy(
            source_kind="legacy_recovery",
            producer_id="phase1-investigate",
            reason_code="human_clarification_required",
            classification="material",
            semi_policy="require_human",
            resolution_handler="clarification_resume",
            allow_free_text=False,
            allowed_phase_ids=frozenset({"phase1-investigate"}),
            allowed_target_phases=frozenset({"missing-phase"}),
            context_state_keys=("phase",),
            context_paths=(),
            options=(
                HumanInputOption(
                    id="missing",
                    label="Missing",
                    description="Route outside the graph.",
                    recommended=True,
                    risk_level="low",
                    next_phase="missing-phase",
                    outcome=None,
                ),
            ),
            recommendation_mode="static",
        )
    elif fault == "outcome":
        base = _choice_policy()
        policy = replace(
            base,
            options=(
                replace(base.options[0], outcome="deferred"),
                base.options[1],
            ),
        )
    else:
        policy = _choice_policy()
    controller, store, _provider = _controller(
        case_root,
        autonomy_mode="guided",
        policy=policy,
    )
    decision_id, revision = _seal_awaiting_human(
        controller,
        store,
        policy,
    )
    if fault == "handler":
        with store._lock(exclusive=True):
            before_tamper = store._load_unlocked()
            state = json.loads(json.dumps(before_tamper))
            decision = dict(state["blocked_decision"])
            decision["resolution_handler"] = "unknown_handler"
            store._replace_human_input_decision_unlocked(state, decision)
            store._commit_human_input_state_unlocked(
                before_tamper,
                state,
            )
        revision = store.load()["state_revision"]
    selected_option_id = (
        "missing"
        if fault == "target"
        else "not-registered"
        if fault == "option"
        else "approve"
    )
    resolution = HumanInputResolution(
        selected_option_id=selected_option_id,
        answer_text="also supplied" if fault == "answer" else None,
        resolved_by="root" if fault == "resolver" else "user",
    )
    before = store.load()

    with pytest.raises(HumanInputPolicyError):
        controller.apply_human_input_resolution(
            "dec-wrong" if fault == "id" else decision_id,
            expected_state_revision=(
                revision + 1 if fault == "revision" else revision
            ),
            resolution=resolution,
        )

    assert store.load() == before
    assert not (
        Path(before["staging_dir"]) / "user-clarifications.md"
    ).exists()


def test_phase_dispatch_limit_uses_human_input_setter_path(
    tmp_path: Path,
) -> None:
    policy = replace(
        _safeguard_policy(
            "phase_dispatch_limit",
            phase_id="phase1-what",
        ),
        allow_free_text=False,
        allowed_target_phases=frozenset({"phase1-what"}),
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    for guard_name in (
        "_guard_constitution_provenance",
        "_guard_spec_lexicon_evidence",
        "_guard_phase1_quality_evidence",
        "_guard_understanding_evidence",
    ):
        setattr(controller, guard_name, MagicMock(side_effect=lambda phase: phase))
    state = store.load()
    state["phase_dispatch_counts"] = {
        "phase1-what": controller._max_iterations + 1,
    }
    store.save(state)
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "issues.md").write_text(
        """### ISS-001: Retry policy

### Resolution Guidance
- **Decision required:** Retry behavior.
- **Suggested option:** Use exponential backoff.
- **Evidence basis:** The API reference documents idempotent reads.
- **Banzai eligible:** yes
""",
        encoding="utf-8",
    )
    controller.handle_human_input = MagicMock(return_value=False)

    result = controller.run("message", "guided")

    assert result.status == "running"
    controller.handle_human_input.assert_called_once()
    call = controller.handle_human_input.call_args
    request = call.args[0]
    assert request.source_kind == "controller_safeguard"
    assert request.producer_id == "phase_dispatch_limit"
    assert request.reason_code == "phase_dispatch_limit"
    assert request.phase_id == "phase1-what"
    assert request.source_state_revision == store.load()["state_revision"]
    assert request.recommended_option_id == "ISS-001"
    assert [option.id for option in request.options if option.recommended] == [
        "ISS-001"
    ]
    assert "first eligible entry" in request.recommendation_rationale
    assert call.kwargs == {}
    provider.exec_agent.assert_not_called()


def test_dispatch_cap_options_reject_an_empty_candidate_set() -> None:
    with pytest.raises(HumanInputPolicyError, match="eligible|option"):
        SquadController._dispatch_cap_options([])


def test_dispatch_cap_options_bound_long_utf8_title() -> None:
    options = SquadController._dispatch_cap_options([
        _dispatch_cap_candidate(title="ž" * 200),
    ])

    label = options[0].label
    assert len(label.encode("utf-8")) <= 256
    assert label.encode("utf-8").decode("utf-8") == label
    assert label.startswith("ISS-001: ")
    assert label.endswith("…")


def test_dispatch_cap_options_reference_large_evidence() -> None:
    options = SquadController._dispatch_cap_options([
        _dispatch_cap_candidate(suggested_option="x" * 2_000),
    ])

    description = options[0].description
    assert len(description.encode("utf-8")) <= 1_024
    reference = json.loads(description)
    assert set(reference) == {
        "evidence_sha256",
        "issue_id",
        "repair_phase",
        "schema_version",
    }
    assert reference["schema_version"] == 2
    assert reference["issue_id"] == "ISS-001"
    assert reference["repair_phase"] == "phase1-what"
    assert len(reference["evidence_sha256"]) == 64


def test_controller_rejects_empty_dispatch_cap_request_before_sealing(
    tmp_path: Path,
) -> None:
    policy = replace(
        _safeguard_policy(
            "phase_dispatch_limit",
            phase_id="phase1-what",
        ),
        allow_free_text=False,
        allowed_target_phases=frozenset({"phase1-what"}),
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    request = controller._human_input_registry.prepare(
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        phase_id="phase1-what",
        reason_code=policy.reason_code,
        question="Select one sealed evidence-backed issue resolution.",
        source_state_revision=store.load()["state_revision"],
    )
    before = store.load()

    with pytest.raises(HumanInputPolicyError, match="eligible|option"):
        controller.handle_human_input(request)

    assert store.load() == before
    provider.exec_agent.assert_not_called()


def test_controller_rejects_prepared_answer_shape_that_conflicts_with_policy(
    tmp_path: Path,
) -> None:
    policy = replace(
        _free_text_policy(source_kind="legacy_recovery"),
        allow_free_text=False,
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    request = _request(controller, store, policy)
    before = store.load()

    with pytest.raises(HumanInputPolicyError, match="answer shape"):
        controller.handle_human_input(request)

    assert store.load() == before
    provider.exec_agent.assert_not_called()


def test_dispatch_cap_option_contract_failure_is_not_malformed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = replace(
        _safeguard_policy(
            "phase_dispatch_limit",
            phase_id="phase1-what",
        ),
        allow_free_text=False,
        allowed_target_phases=frozenset({"phase1-what"}),
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    for guard_name in (
        "_guard_constitution_provenance",
        "_guard_spec_lexicon_evidence",
        "_guard_phase1_quality_evidence",
        "_guard_understanding_evidence",
    ):
        setattr(
            controller,
            guard_name,
            MagicMock(side_effect=lambda phase: phase),
        )
    state = store.load()
    state["phase_dispatch_counts"] = {
        "phase1-what": controller._max_iterations + 1,
    }
    store.save(state)
    spec_dir = Path(store.load()["spec_dir"])
    spec_dir.mkdir(parents=True)
    (spec_dir / "issues.md").write_text(
        """### ISS-001: Valid issue

### Resolution Guidance
- **Decision required:** Repair the issue.
- **Suggested option:** Apply the evidence-backed repair.
- **Evidence basis:** The active artifact contains the exact correction.
- **Banzai eligible:** yes
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        controller,
        "_dispatch_cap_options",
        MagicMock(
            side_effect=HumanInputPolicyError(
                "controller-generated option is invalid"
            )
        ),
    )

    result = controller.run("message", "guided")

    failed = store.load()
    assert result.status == "blocked"
    assert failed["blocked_reason"] == (
        "phase_dispatch_limit_option_contract_failed"
    )
    assert failed["recovery_instruction"]["kind"] == "manual_diagnosis"
    assert "blocked_decision" not in failed
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize("mode", ("guided", "semi", "banzai"))
@pytest.mark.parametrize(
    ("evidence", "expected_reason"),
    [
        ("missing", "phase_dispatch_limit_evidence_missing"),
        ("empty", "phase_dispatch_limit_evidence_empty"),
        ("malformed", "phase_dispatch_limit_evidence_malformed"),
        ("ineligible", "phase_dispatch_limit_evidence_ineligible"),
    ],
)
def test_dispatch_cap_without_resolvable_evidence_fails_manual_diagnosis_in_all_modes(
    tmp_path: Path,
    mode: str,
    evidence: str,
    expected_reason: str,
) -> None:
    from echelon.cli import _active_v2_decision, _classify_run_recovery

    policy = replace(
        _safeguard_policy(
            "phase_dispatch_limit",
            phase_id="phase1-what",
        ),
        allow_free_text=False,
        allowed_target_phases=frozenset({"phase1-what"}),
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode=mode,
        policy=policy,
    )
    for guard_name in (
        "_guard_constitution_provenance",
        "_guard_spec_lexicon_evidence",
        "_guard_phase1_quality_evidence",
        "_guard_understanding_evidence",
    ):
        setattr(controller, guard_name, MagicMock(side_effect=lambda phase: phase))
    state = store.load()
    state["phase_dispatch_counts"] = {
        "phase1-what": controller._max_iterations + 1,
    }
    store.save(state)
    spec_dir = Path(store.load()["spec_dir"])
    if evidence != "missing":
        spec_dir.mkdir(parents=True)
        content = {
            "empty": "",
            "malformed": (
                "### ISS-001: Incomplete guidance\n\n"
                "### Resolution Guidance\n"
                "- **Banzai eligible:** yes\n"
            ),
            "ineligible": (
                "### ISS-001: Product preference\n\n"
                "### Resolution Guidance\n"
                "- **Decision required:** Choose a product preference.\n"
                "- **Suggested option:** Use option A.\n"
                "- **Evidence basis:** The user must decide.\n"
                "- **Banzai eligible:** no\n"
            ),
        }[evidence]
        (spec_dir / "issues.md").write_text(content, encoding="utf-8")

    result = controller.run("message", mode)

    failed = store.load()
    assert result.status == "blocked"
    assert failed["blocked_reason"] == expected_reason
    assert failed["recovery_instruction"]["kind"] == "manual_diagnosis"
    assert failed["recovery_instruction"]["requires_human_input"] is False
    assert "blocked_decision" not in failed
    assert "escalation_question" not in failed
    assert _active_v2_decision(failed) is None
    action = _classify_run_recovery(failed, project_root=tmp_path)
    assert action.kind == "manual_recovery"
    assert "free text" not in f"{action.command} {action.note}".lower()
    provider.exec_agent.assert_not_called()


def test_dispatch_cap_uses_active_spec_when_published_copy_is_stale(
    tmp_path: Path,
) -> None:
    policy = replace(
        _safeguard_policy("phase_dispatch_limit", phase_id="phase1-what"),
        allow_free_text=False,
        allowed_target_phases=frozenset({"phase1-what"}),
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="semi",
        policy=policy,
    )
    active_spec = Path(store.load()["spec_dir"])
    active_spec.mkdir(parents=True)
    (active_spec / "issues.md").write_text("active issues", encoding="utf-8")
    state = store.load()
    state.update(
        {
            "spec_id": "spec",
            "published_spec_dir": "specs/spec",
        }
    )
    store.save(state)

    assert controller._read_dispatch_cap_issues(store.load()) == "active issues"


def test_dispatch_cap_uses_staging_issues_before_spec_artifacts_exist(
    tmp_path: Path,
) -> None:
    policy = replace(
        _safeguard_policy("phase_dispatch_limit", phase_id="phase1-why1"),
        allow_free_text=False,
        allowed_target_phases=frozenset({"phase1-why1"}),
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="semi",
        policy=policy,
    )
    staging_issues = Path(store.load()["staging_dir"]) / "issues.md"
    staging_issues.write_text("early Phase A issues", encoding="utf-8")

    assert controller._read_dispatch_cap_issues(store.load()) == "early Phase A issues"


@pytest.mark.parametrize(
    ("evidence", "expected_reason"),
    [
        ("oversized", "phase_dispatch_limit_evidence_oversized"),
        ("too_many", "phase_dispatch_limit_evidence_too_many_candidates"),
    ],
)
def test_dispatch_cap_bounds_issue_reads_and_candidate_count(
    tmp_path: Path,
    evidence: str,
    expected_reason: str,
) -> None:
    policy = replace(
        _safeguard_policy(
            "phase_dispatch_limit",
            phase_id="phase1-what",
        ),
        allow_free_text=False,
        allowed_target_phases=frozenset({"phase1-what"}),
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    for guard_name in (
        "_guard_constitution_provenance",
        "_guard_spec_lexicon_evidence",
        "_guard_phase1_quality_evidence",
        "_guard_understanding_evidence",
    ):
        setattr(controller, guard_name, MagicMock(side_effect=lambda phase: phase))
    state = store.load()
    state["phase_dispatch_counts"] = {
        "phase1-what": controller._max_iterations + 1,
    }
    store.save(state)
    spec_dir = Path(store.load()["spec_dir"])
    spec_dir.mkdir(parents=True)
    issue = (
        "### {issue_id}: Retry policy\n\n"
        "### Resolution Guidance\n"
        "- **Decision required:** Retry behavior.\n"
        "- **Suggested option:** Use exponential backoff.\n"
        "- **Evidence basis:** The API documents idempotent reads.\n"
        "- **Banzai eligible:** yes\n"
    )
    if evidence == "oversized":
        content = issue.format(issue_id="ISS-001") + ("x" * 1_000_000)
    else:
        content = "\n".join(
            issue.format(issue_id=f"ISS-{index:03d}")
            for index in range(1, 66)
        )
    (spec_dir / "issues.md").write_text(content, encoding="utf-8")

    result = controller.run("message", "guided")

    failed = store.load()
    assert result.status == "blocked"
    assert failed["blocked_reason"] == expected_reason
    assert failed["recovery_instruction"]["kind"] == "manual_diagnosis"
    assert "blocked_decision" not in failed
    provider.exec_agent.assert_not_called()


def test_unresolvable_dispatch_cap_retires_prior_terminal_decision_authority(
    tmp_path: Path,
) -> None:
    policy = replace(
        _safeguard_policy(
            "phase_dispatch_limit",
            phase_id="phase1-what",
        ),
        allow_free_text=False,
        allowed_target_phases=frozenset({"phase1-what"}),
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    for guard_name in (
        "_guard_constitution_provenance",
        "_guard_spec_lexicon_evidence",
        "_guard_phase1_quality_evidence",
        "_guard_understanding_evidence",
    ):
        setattr(
            controller,
            guard_name,
            MagicMock(side_effect=lambda phase: phase),
        )
    _seal_dispatch_cap_decision(
        controller,
        store,
        policy,
        (_dispatch_cap_candidate(),),
        legacy=True,
    )
    assert controller.resume_with_human_input("ISS-001")
    assert store.load()["blocked_decision"]["status"] == "resolved"
    state = store.load()
    state["phase_dispatch_counts"] = {
        "phase1-what": controller._max_iterations + 1,
    }
    store.save(state)

    result = controller.run("message", "guided")

    failed = store.load()
    assert result.status == "blocked"
    assert failed["blocked_reason"] == (
        "phase_dispatch_limit_evidence_missing"
    )
    assert failed["recovery_instruction"]["kind"] == "manual_diagnosis"
    assert "blocked_decision" not in failed
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize(
    ("producer_id", "stagnation_count", "expected_updates"),
    [
        (
            "consecutive_why_fails",
            0,
            {
                "why_fail_count": 2,
            },
        ),
        (
            "why2_metric_stagnation",
            1,
            {
                "why_fail_count": 2,
                "why2_metric_stagnation_count": 2,
            },
        ),
    ],
)
def test_consecutive_fail_and_why2_metric_stagnation_return_safeguard_request(
    tmp_path: Path,
    producer_id: str,
    stagnation_count: int,
    expected_updates: dict[str, int],
) -> None:
    policy = _safeguard_policy(
        producer_id,
        phase_id="phase1-why2",
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    state = store.load()
    state.update(
        {
            "spec_authoring_mode": "perfectionist",
            "why_fail_count": 1,
            "why2_metric_stagnation_count": stagnation_count,
            "why_failure_baseline": {
                "phase_id": "phase1-why2",
                "recorded_at": "2999-01-01T00:00:00+00:00",
            },
        }
    )
    if stagnation_count:
        score = {
            "pass_id": "WHY2-1",
            "overall": 0.5,
            "structure": 0.5,
            "testability": 0.5,
            "behavioral": 0.5,
            "semantic": 0.5,
            "cognitive": 0.5,
            "readability": 0.5,
            "depth": 0.5,
        }
        state["quality_scores"] = [
            score,
            {**score, "pass_id": "WHY2-2"},
        ]
    store.save(state)
    node = controller._graph.get("phase1-why2")
    snapshot = store.capture_routing_snapshot(expected_phase=node.id)
    prepared = controller._prepare_phase_result(
        node,
        SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {
                    "evidence_resolution_status": "not_required",
                    "finding_routes": {
                        "findings": [{
                            "issue_id": "ISS-BLOCKED",
                            "route": "spec_repair",
                            "rationale": "The specification needs repair.",
                        }]
                    },
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        ),
        snapshot,
    )

    route, updates, request = controller._coordinate_why_transition_state(
        node,
        prepared,
        snapshot,
    )

    assert route == "terminal-blocked"
    assert {
        key: updates[key]
        for key in expected_updates
    } == expected_updates
    assert "escalation_question" not in updates
    assert "blocked_reason" not in updates
    assert request.source_kind == "controller_safeguard"
    assert request.producer_id == producer_id
    assert request.reason_code == producer_id
    assert request.phase_id == "phase1-why2"
    assert request.source_state_revision == snapshot.state_revision


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
    request = _automatic_free_text_request(
        controller,
        store,
        policy,
        recommended_answer="Use the registered evidence.",
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
    request = _automatic_free_text_request(controller, store, policy)
    store.set_human_input_decision(request, initial_status="pending")
    state = store.load()

    with pytest.raises(HumanInputPolicyError, match="escape"):
        controller._render_commander_decision_prompt(
            state["blocked_decision"],
            policy,
            state,
        )


def test_commander_context_rejects_parent_symlink_swap_during_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _free_text_policy(
        context_paths=("{staging_dir}/parent/evidence.md",),
        source_kind="legacy_recovery",
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    staging = Path(store.load()["staging_dir"])
    parent = staging / "parent"
    parent.mkdir()
    (parent / "evidence.md").write_text("IN-ROOT", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evidence.md").write_text("OUTSIDE", encoding="utf-8")
    request = _automatic_free_text_request(controller, store, policy)
    store.set_human_input_decision(request, initial_status="pending")
    state = store.load()
    original_open = squad_module.os.open
    swapped = False

    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if path == "parent" and dir_fd is not None and not swapped:
            parent.rename(staging / "parent-original")
            parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(squad_module.os, "open", racing_open)

    with pytest.raises(HumanInputPolicyError, match="symlink|context"):
        controller._render_commander_decision_prompt(
            state["blocked_decision"],
            policy,
            state,
        )
    assert swapped


@pytest.mark.parametrize(
    ("state_key", "context_path"),
    [
        ("staging_dir", "{staging_dir}/evidence.md"),
        ("context_dir", "{context_dir}/evidence.md"),
        ("squad_dir", "{squad_dir}/evidence.md"),
        ("spec_dir", "{spec_dir}/evidence.md"),
    ],
)
def test_commander_context_rejects_tampered_persisted_roots_before_claim(
    tmp_path: Path,
    state_key: str,
    context_path: str,
) -> None:
    policy = _free_text_policy(
        context_paths=(context_path,),
        source_kind="legacy_recovery",
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    outside = tmp_path.parent / f"{tmp_path.name}-{state_key}-outside"
    outside.mkdir()
    (outside / "evidence.md").write_text(
        "OUTSIDE SECRET",
        encoding="utf-8",
    )
    state = store.load()
    state[state_key] = str(outside)
    store.save(state)

    assert controller.handle_human_input(
        _automatic_free_text_request(controller, store, policy)
    ) is False

    failed = store.load()
    assert failed["blocked_decision"]["status"] == "failed"
    assert failed["blocked_decision"]["attempts"] == 0
    assert failed["blocked_decision"]["failure_code"] == (
        "decision_context_setup_failed"
    )
    assert failed["recovery_instruction"]["kind"] == "manual_diagnosis"
    assert "escalation_question" not in failed
    provider.exec_agent.assert_not_called()


def test_commander_context_rejects_mismatched_spec_identity_before_claim(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy(
        context_paths=("{spec_dir}/evidence.md",),
        source_kind="legacy_recovery",
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    wrong_spec = tmp_path / "specs" / "999-other"
    wrong_spec.mkdir(parents=True)
    (wrong_spec / "evidence.md").write_text("WRONG SPEC", encoding="utf-8")
    state = store.load()
    state["spec_id"] = "001-expected"
    state["spec_dir"] = str(wrong_spec)
    store.save(state)

    assert controller.handle_human_input(
        _automatic_free_text_request(controller, store, policy)
    ) is False

    failed = store.load()
    assert failed["blocked_decision"]["status"] == "failed"
    assert failed["blocked_decision"]["attempts"] == 0
    assert failed["blocked_decision"]["failure_code"] == (
        "decision_context_setup_failed"
    )
    provider.exec_agent.assert_not_called()


def test_commander_context_setup_failure_is_stable_across_restart(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy(
        context_paths=("{staging_dir}/evidence.md",),
        source_kind="legacy_recovery",
    )
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    outside = tmp_path.parent / f"{tmp_path.name}-restart-outside"
    outside.mkdir()
    (outside / "evidence.md").write_text("OUTSIDE SECRET", encoding="utf-8")
    state = store.load()
    state["staging_dir"] = str(outside)
    store.save(state)

    assert controller.handle_human_input(
        _automatic_free_text_request(controller, store, policy)
    ) is False
    before_restart = store.load()
    restarted_provider = MagicMock()
    restarted = SquadController(
        provider=restarted_provider,
        state_store=store,
        phase_graph=PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS),
        ext_dir=ROOT / "runtime",
        project_root=tmp_path,
        squad_dir=store.squad_dir,
    )

    assert restarted.resume_pending_human_input() is False
    assert store.load() == before_restart
    assert before_restart["blocked_decision"]["status"] == "failed"
    assert before_restart["blocked_decision"]["attempts"] == 0
    provider.exec_agent.assert_not_called()
    restarted_provider.exec_agent.assert_not_called()


def test_commander_context_reads_only_the_remaining_aggregate_file_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _free_text_policy(
        context_paths=("{staging_dir}/oversized.md",),
        source_kind="legacy_recovery",
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    staging = Path(store.load()["staging_dir"])
    (staging / "oversized.md").write_bytes(b"x" * 1_000_000)
    request = _automatic_free_text_request(controller, store, policy)
    store.set_human_input_decision(request, initial_status="pending")
    state = store.load()
    original_read = squad_module.os.read
    requested_sizes: list[int] = []

    def bounded_read(fd: int, size: int) -> bytes:
        requested_sizes.append(size)
        return original_read(fd, size)

    monkeypatch.setattr(squad_module.os, "read", bounded_read)

    prompt = controller._render_commander_decision_prompt(
        state["blocked_decision"],
        policy,
        state,
    )

    assert requested_sizes
    assert sum(requested_sizes) <= 32_768
    assert len(prompt.encode("utf-8")) <= 32_768


def test_commander_context_bounds_state_before_full_json_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _free_text_policy(
        context_state_keys=("user_message",),
        source_kind="legacy_recovery",
    )
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    request = _automatic_free_text_request(controller, store, policy)
    store.set_human_input_decision(request, initial_status="pending")
    state = store.load()
    huge_state_value = "s" * 1_000_000
    state["user_message"] = huge_state_value
    original_dumps = squad_module.json.dumps

    def guarded_dumps(value, *args, **kwargs):
        if (
            isinstance(value, dict)
            and value.get("user_message") is huge_state_value
        ):
            raise AssertionError("unbounded state JSON was materialized")
        return original_dumps(value, *args, **kwargs)

    monkeypatch.setattr(squad_module.json, "dumps", guarded_dumps)

    prompt = controller._render_commander_decision_prompt(
        state["blocked_decision"],
        policy,
        state,
    )

    assert len(prompt.encode("utf-8")) <= 32_768
    assert huge_state_value not in prompt


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
    request = _automatic_free_text_request(controller, store, policy)
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


def test_commander_runtime_prompt_contains_the_complete_strict_contract(
    tmp_path: Path,
) -> None:
    policy = _choice_policy()
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    controller.apply_human_input_resolution = MagicMock(return_value=True)

    assert controller.handle_human_input(_request(controller, store, policy))

    prompt = provider.exec_agent.call_args.args[1]
    assert (
        "echelon_result:\n"
        "  verdict: DECISION_RESOLVED\n"
        "  state_updates: {}\n"
        "  journal_entries: []\n"
        "  decision:\n"
        '    selected_option_id: "<exact allowed option id>"\n'
        "    answer_text: null\n"
        '    rationale: "<non-empty explanation, at most 2,000 characters>"\n'
        "    confidence: high\n"
    ) in prompt
    assert "confidence must be exactly high, medium, or low" in prompt
    assert "exactly one of selected_option_id or answer_text" in prompt
    assert "Do not ask another question" in prompt
    assert "Do not write files or mutate state" in prompt


def test_commander_free_text_prompt_requires_exact_recommendation_copy(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy(source_kind="legacy_recovery")
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    request = _automatic_free_text_request(
        controller,
        store,
        policy,
        recommended_answer="Hello, World!",
    )
    store.set_human_input_decision(request, initial_status="pending")
    state = store.load()

    prompt = controller._render_commander_decision_prompt(
        state["blocked_decision"],
        policy,
        state,
    )

    assert (
        "When following a free-text recommended_answer, copy its exact value "
        "into answer_text, character for character."
    ) in prompt
    assert (
        "Any different answer_text is an override; explain that difference "
        "in rationale."
    ) in prompt


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

    assert controller.handle_human_input(_request(controller, store, policy))
    assert events == ["claim", "model", "claim", "model"]
    assert provider.exec_agent.call_count == 2
    assert store.load()["blocked_decision"]["attempts"] == 2
    assert store.load()["token_usage"] == 18


@pytest.mark.parametrize("invalid_second_answer", [False, True])
def test_task6_fix_round1_commander_invalid_dispatch_cap_answer_consumes_attempt(
    tmp_path: Path,
    invalid_second_answer: bool,
) -> None:
    policy = replace(
        _safeguard_policy(
            "phase_dispatch_limit",
            phase_id="phase1-what",
        ),
        allow_free_text=False,
        allowed_target_phases=frozenset({"phase1-what"}),
    )
    first = _decision_result(selected_option_id="ISS-999")
    first.token_usage = 7
    second = _decision_result(
        selected_option_id=(
            "ISS-998" if invalid_second_answer else "ISS-001"
        )
    )
    second.token_usage = 11
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    provider.exec_agent.side_effect = (first, second)
    state = store.load()
    state["phase_dispatch_counts"] = {"phase1-what": 6}
    store.save(state)
    request = controller._human_input_registry.prepare_controller(
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        phase_id="phase1-what",
        reason_code=policy.reason_code,
        question="Select one sealed evidence-backed issue resolution.",
        source_state_revision=store.load()["state_revision"],
        option_contract=(
            _dispatch_cap_option(_dispatch_cap_candidate()),
        ),
    )

    assert controller.handle_human_input(request) is (not invalid_second_answer)

    state = store.load()
    assert provider.exec_agent.call_count == 2
    assert state["blocked_decision"]["attempts"] == 2
    assert state["token_usage"] == 18
    if invalid_second_answer:
        assert state["blocked_decision"]["status"] == "failed"
        assert state["blocked_decision"]["failure_code"] == (
            "invalid_resolution_result"
        )
    else:
        assert state["blocked_decision"]["status"] == "resolved"
        assert state["selected_issue_resolution"] == "ISS-001"


def test_task6_fix_round1_commander_semantic_apply_error_consumes_attempts(
    tmp_path: Path,
) -> None:
    policy = HumanInputPolicy(
        source_kind="legacy_recovery",
        producer_id="phase1-investigate",
        reason_code="human_clarification_required",
        classification="material",
        semi_policy="require_human",
        resolution_handler="clarification_resume",
        allow_free_text=False,
        allowed_phase_ids=frozenset({"phase1-investigate"}),
        allowed_target_phases=frozenset({"missing-phase"}),
        context_state_keys=("phase",),
        context_paths=(),
        options=(
                HumanInputOption(
                    id="missing",
                    label="Missing route",
                    description="A strictly shaped but semantically invalid route.",
                    recommended=True,
                    risk_level="low",
                    next_phase="missing-phase",
                    outcome=None,
                ),
            ),
            recommendation_mode="static",
        )
    first = _decision_result(selected_option_id="missing")
    first.token_usage = 3
    second = _decision_result(selected_option_id="missing")
    second.token_usage = 5
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    provider.exec_agent.side_effect = (first, second)

    assert controller.handle_human_input(
        _request(controller, store, policy)
    ) is False

    state = store.load()
    assert provider.exec_agent.call_count == 2
    assert state["blocked_decision"]["status"] == "failed"
    assert state["blocked_decision"]["attempts"] == 2
    assert state["blocked_decision"]["failure_code"] == (
        "invalid_resolution_result"
    )
    assert state["token_usage"] == 8


def test_task6_fix_round1_commander_resolution_accounts_usage_in_resolution_cas(
    tmp_path: Path,
) -> None:
    policy = _choice_policy()
    result = _decision_result()
    result.token_usage = 37
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
        provider_result=result,
    )
    store.apply_human_input_state_resolution = MagicMock(
        wraps=store.apply_human_input_state_resolution,
    )
    store.increment_token_usage = MagicMock(
        wraps=store.increment_token_usage,
    )

    assert controller.handle_human_input(_request(controller, store, policy))

    state = store.load()
    assert state["blocked_decision"]["status"] == "resolved"
    assert state["token_usage"] == 37
    assert (
        store.apply_human_input_state_resolution.call_args.kwargs[
            "token_usage_delta"
        ]
        == 37
    )
    store.increment_token_usage.assert_not_called()


def test_task6_fix_round1_commander_resolution_save_error_preserves_recovery(
    tmp_path: Path,
) -> None:
    policy = _choice_policy()
    result = _decision_result()
    result.token_usage = 37
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
        provider_result=result,
    )
    store.apply_human_input_state_resolution = MagicMock(
        side_effect=StateAdvanceError("injected resolution save failure"),
    )

    with pytest.raises(StateAdvanceError, match="resolution save failure"):
        controller.handle_human_input(_request(controller, store, policy))

    state = store.load()
    assert state["blocked_decision"]["status"] == "resolving"
    assert state["blocked_decision"]["attempts"] == 1
    assert state["token_usage"] == 0


def test_commander_real_provider_has_one_physical_call_per_durable_claim(
    tmp_path: Path,
) -> None:
    class FakeBackend:
        def __init__(self) -> None:
            self.requests: list[CliRunRequest] = []

        def run_prompt(self, request: CliRunRequest) -> CliRunResult:
            raise AssertionError("decision resolution must use run_agent")

        def run_agent(self, request: CliRunRequest) -> CliRunResult:
            self.requests.append(request)
            if len(self.requests) == 1:
                return CliRunResult(
                    exit_code=0,
                    stdout="Clean output without an echelon_result block.\n",
                    stderr="",
                    token_usage=3,
                )
            return CliRunResult(
                exit_code=0,
                stdout=(
                    "echelon_result:\n"
                    "  verdict: DECISION_RESOLVED\n"
                    "  state_updates: {}\n"
                    "  journal_entries: []\n"
                    "  decision:\n"
                    "    selected_option_id: approve\n"
                    "    answer_text: null\n"
                    "    rationale: Best exact allowed option.\n"
                    "    confidence: high\n"
                ),
                stderr="",
                token_usage=5,
            )

    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="codex"),
    )
    provider = SquadCliProvider(config)
    backend = FakeBackend()
    provider._backend = backend
    policy = _choice_policy()
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
        provider=provider,
    )
    claims: list[int] = []
    original_claim = store.claim_human_input_decision

    def claim(*args, **kwargs):
        claimed = original_claim(*args, **kwargs)
        claims.append(claimed["blocked_decision"]["attempts"])
        return claimed

    store.claim_human_input_decision = MagicMock(side_effect=claim)

    assert controller.handle_human_input(_request(controller, store, policy))

    state = store.load()
    assert len(backend.requests) == 2
    assert claims == [1, 2]
    assert state["blocked_decision"]["attempts"] == 2
    assert state["token_usage"] == 8


def test_commander_duplicate_physical_envelope_consumes_one_claim(
    tmp_path: Path,
) -> None:
    valid = (
        "echelon_result:\n"
        "  verdict: DECISION_RESOLVED\n"
        "  state_updates: {}\n"
        "  journal_entries: []\n"
        "  decision:\n"
        "    selected_option_id: approve\n"
        "    answer_text: null\n"
        "    rationale: Best exact allowed option.\n"
        "    confidence: high\n"
    )

    class FakeBackend:
        def __init__(self) -> None:
            self.requests: list[CliRunRequest] = []

        def run_prompt(self, request: CliRunRequest) -> CliRunResult:
            raise AssertionError("decision resolution must use run_agent")

        def run_agent(self, request: CliRunRequest) -> CliRunResult:
            self.requests.append(request)
            return CliRunResult(
                exit_code=0,
                stdout=(
                    (
                        valid.replace(
                            "selected_option_id: approve",
                            "selected_option_id: reject",
                        )
                        + "\nConflicting answer follows.\n\n"
                        + valid
                    )
                    if len(self.requests) == 1
                    else valid
                ),
                stderr="",
                token_usage=3 if len(self.requests) == 1 else 5,
            )

    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="codex"),
    )
    provider = SquadCliProvider(config)
    backend = FakeBackend()
    provider._backend = backend
    policy = _choice_policy()
    controller, store, _provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
        provider=provider,
    )

    assert controller.handle_human_input(_request(controller, store, policy))

    state = store.load()
    assert len(backend.requests) == 2
    assert state["blocked_decision"]["attempts"] == 2
    assert state["blocked_decision"]["selected_option_id"] == "approve"
    assert state["token_usage"] == 8


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

    def recover(**kwargs):
        events.append("recover")
        return original_recover(**kwargs)

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


@pytest.mark.parametrize("entrypoint", ("next_phase", "manual_phase"))
def test_unresolved_v2_decision_blocks_controller_phase_bypass(
    tmp_path: Path,
    entrypoint: str,
) -> None:
    policy = _choice_policy()
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    request = _request(controller, store, policy)
    store.set_human_input_decision(request, initial_status="pending")
    state = store.load()
    decision_id = state["blocked_decision"]["id"]
    revision = state["state_revision"]
    claimed = store.claim_human_input_decision(
        decision_id,
        expected_state_revision=revision,
    )
    retry = store.record_human_input_resolution_failure(
        decision_id,
        expected_state_revision=claimed["state_revision"],
        failure_code="provider_failed",
    )
    claimed = store.claim_human_input_decision(
        decision_id,
        expected_state_revision=retry["state_revision"],
    )
    failed = store.record_human_input_resolution_failure(
        decision_id,
        expected_state_revision=claimed["state_revision"],
        failure_code="provider_failed",
    )
    assert failed["blocked_decision"]["status"] == "failed"
    assert "escalation_question" not in failed
    before = store.load()

    if entrypoint == "next_phase":
        result = controller.run(
            user_message="registered user message",
            mode="guided",
            next_phase_override="phase4-document",
        )
    else:
        result = controller.run_single_phase(
            "phase4-document",
            user_message="registered user message",
            mode="guided",
        )

    assert result.status == "blocked"
    assert store.load() == before
    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize(
    ("answer", "expected_option_id"),
    [
        ("approve", "approve"),
        ("Approve", "approve"),
    ],
)
def test_resume_with_human_input_resolves_exact_option_id_or_label(
    tmp_path: Path,
    answer: str,
    expected_option_id: str,
) -> None:
    policy = _choice_policy()
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    _seal_awaiting_human(controller, store, policy)

    assert controller.resume_with_human_input(answer)

    decision = store.load()["blocked_decision"]
    assert decision["status"] == "resolved"
    assert decision["selected_option_id"] == expected_option_id
    provider.exec_agent.assert_not_called()


def test_resume_with_human_input_resolves_allowed_free_text(
    tmp_path: Path,
) -> None:
    policy = _free_text_policy(source_kind="legacy_recovery")
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    _seal_awaiting_human(controller, store, policy)

    assert controller.resume_with_human_input("Use the public boundary.")

    decision = store.load()["blocked_decision"]
    assert decision["status"] == "resolved"
    assert decision["answer_text"] == "Use the public boundary."
    provider.exec_agent.assert_not_called()


def test_resume_rejects_banzai_project_decision_but_allows_external_prerequisite(
    tmp_path: Path,
) -> None:
    project_policy = _choice_policy()
    project_controller, project_store, project_provider = _controller(
        tmp_path / "project",
        autonomy_mode="banzai",
        policy=project_policy,
    )
    _seal_awaiting_human(project_controller, project_store, project_policy)

    with pytest.raises(HumanInputPolicyError, match="Banzai project decisions"):
        project_controller.resume_with_human_input("approve")

    external_policy = _choice_policy(classification="external_prerequisite")
    external_controller, external_store, external_provider = _controller(
        tmp_path / "external",
        autonomy_mode="banzai",
        policy=external_policy,
    )
    _seal_awaiting_human(external_controller, external_store, external_policy)

    assert external_controller.resume_with_human_input("approve")
    assert external_store.load()["blocked_decision"]["status"] == "resolved"
    project_provider.exec_agent.assert_not_called()
    external_provider.exec_agent.assert_not_called()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: state["blocked_decision"].update({"status": "pending"}),
        lambda state: state.pop("recovery_instruction"),
        lambda state: state["recovery_instruction"].update({"kind": "resolve_decision", "requires_human_input": False}),
        lambda state: state["recovery_instruction"].update({"phase": "phase4-document"}),
        lambda state: state["recovery_instruction"].update({"decision_id": "dec-stale"}),
        lambda state: state["recovery_instruction"].update({"reason_code": "stale_reason"}),
    ],
    ids=("non_awaiting", "missing_instruction", "kind", "phase", "decision_id", "reason"),
)
def test_resume_rejects_invalid_or_stale_durable_authority_before_resolution(
    tmp_path: Path,
    mutation,
) -> None:
    policy = _choice_policy()
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    _seal_awaiting_human(controller, store, policy)
    raw = json.loads(store._path.read_text(encoding="utf-8"))
    mutation(raw)
    store._path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises((HumanInputPolicyError, ValueError)):
        controller.resume_with_human_input("approve")

    provider.exec_agent.assert_not_called()


def test_resume_rejects_a_replaced_decision_with_a_stale_instruction(
    tmp_path: Path,
) -> None:
    policy = _choice_policy()
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="guided",
        policy=policy,
    )
    _seal_awaiting_human(controller, store, policy)
    raw = json.loads(store._path.read_text(encoding="utf-8"))
    raw["blocked_decision"]["id"] = "dec-replaced"
    store._path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="decision_id"):
        controller.resume_with_human_input("approve")

    provider.exec_agent.assert_not_called()


@pytest.mark.parametrize("status", ("pending", "resolving"))
@pytest.mark.parametrize("entrypoint", ("next_phase", "manual_phase"))
def test_pending_and_resolving_v2_decisions_block_controller_phase_bypass(
    tmp_path: Path,
    status: str,
    entrypoint: str,
) -> None:
    policy = _choice_policy()
    controller, store, provider = _controller(
        tmp_path,
        autonomy_mode="banzai",
        policy=policy,
    )
    request = _request(controller, store, policy)
    sealed = store.set_human_input_decision(request, initial_status="pending")
    if status == "resolving":
        store.claim_human_input_decision(
            sealed["blocked_decision"]["id"],
            expected_state_revision=sealed["state_revision"],
        )
    before = store.load()

    if entrypoint == "next_phase":
        result = controller.run(next_phase_override="phase4-document")
    else:
        result = controller.run_single_phase("phase4-document")

    assert result.status == "blocked"
    assert store.load() == before
    provider.exec_agent.assert_not_called()


def test_proportional_budget_recommends_one_extension_only_for_bounded_progress(
) -> None:
    registry = HumanInputPolicyRegistry(controller_safeguard_policies())
    policy = registry.lookup(
        "controller_safeguard",
        "proportional_quality_budget_exhausted",
        "proportional_quality_budget_exhausted",
    )

    request = prepare_controller_proportional_quality_decision(
        registry,
        reason_code="proportional_quality_budget_exhausted",
        phase_id="phase1-why2",
        question="Choose how to resolve the exhausted proportional quality budget.",
        source_state_revision=12,
        repair_state=_proportional_repair_state(),
        recommendation_evidence=_proportional_recommendation_evidence(),
        option_contract=policy.options,
    )

    assert [option.id for option in request.options if option.recommended] == [
        "extend_once"
    ]
    assert tuple(
        replace(option, recommended=False) for option in request.options
    ) == policy.options


@pytest.mark.parametrize(
    ("current_depth", "expected_recommendation"),
    (
        (0.70, "extend_once"),
        (0.699999999999, "continue_with_debt"),
    ),
    ids=("exact_inclusive_boundary", "just_outside_boundary"),
)
def test_proportional_budget_borderline_margin_is_stably_inclusive(
    current_depth: float,
    expected_recommendation: str,
) -> None:
    registry = HumanInputPolicyRegistry(controller_safeguard_policies())
    policy = registry.lookup(
        "controller_safeguard",
        "proportional_quality_budget_exhausted",
        "proportional_quality_budget_exhausted",
    )

    request = prepare_controller_proportional_quality_decision(
        registry,
        reason_code="proportional_quality_budget_exhausted",
        phase_id="phase1-why2",
        question="Choose how to resolve the exhausted proportional quality budget.",
        source_state_revision=12,
        repair_state=_proportional_repair_state(),
        recommendation_evidence=_proportional_recommendation_evidence(
            current_depth=current_depth,
            previous_depth=0.69,
        ),
        option_contract=policy.options,
    )

    assert [option.id for option in request.options if option.recommended] == [
        expected_recommendation
    ]


@pytest.mark.parametrize(
    "evidence",
    [
        _proportional_recommendation_evidence(current_depth=0.69),
        _proportional_recommendation_evidence(
            current_depth=0.70,
            previous_depth=0.70,
        ),
        _proportional_recommendation_evidence(formal_statement_count=9),
    ],
    ids=("outside_borderline_margin", "failed_dimension_not_improved", "formal_growth"),
)
def test_proportional_budget_recommends_debt_when_any_extension_predicate_fails(
    evidence: ProportionalQualityRecommendationEvidence,
) -> None:
    registry = HumanInputPolicyRegistry(controller_safeguard_policies())
    policy = registry.lookup(
        "controller_safeguard",
        "proportional_quality_budget_exhausted",
        "proportional_quality_budget_exhausted",
    )

    request = prepare_controller_proportional_quality_decision(
        registry,
        reason_code="proportional_quality_budget_exhausted",
        phase_id="phase1-why2",
        question="Choose how to resolve the exhausted proportional quality budget.",
        source_state_revision=12,
        repair_state=_proportional_repair_state(),
        recommendation_evidence=evidence,
        option_contract=policy.options,
    )

    assert [option.id for option in request.options if option.recommended] == [
        "continue_with_debt"
    ]
    assert not next(option for option in request.options if option.id == "stop").recommended


def test_proportional_extension_exhaustion_never_recommends_another_extension(
) -> None:
    registry = HumanInputPolicyRegistry(controller_safeguard_policies())
    policy = registry.lookup(
        "controller_safeguard",
        "proportional_quality_extension_exhausted",
        "proportional_quality_extension_exhausted",
    )

    request = prepare_controller_proportional_quality_decision(
        registry,
        reason_code="proportional_quality_extension_exhausted",
        phase_id="phase1-why2",
        question="Choose how to resolve the exhausted proportional quality extension.",
        source_state_revision=13,
        repair_state=_proportional_repair_state(
            extension_authorized=1,
            extension_consumed=1,
        ),
        recommendation_evidence=_proportional_recommendation_evidence(),
        option_contract=policy.options,
    )

    assert [option.id for option in request.options] == [
        "continue_with_debt",
        "stop",
    ]
    assert [option.id for option in request.options if option.recommended] == [
        "continue_with_debt"
    ]


def test_qualitative_only_failure_never_vacuously_recommends_extension() -> None:
    registry = HumanInputPolicyRegistry(controller_safeguard_policies())
    policy = registry.lookup(
        "controller_safeguard",
        "proportional_quality_budget_exhausted",
        "proportional_quality_budget_exhausted",
    )
    passing = (
        ("overall", 0.90, 0.80, True),
        ("structure", 0.85, 0.80, True),
    )
    evidence = ProportionalQualityRecommendationEvidence(
        borderline_margin=0.05,
        previous_gates=passing,
        current_gates=passing,
        previous_formal_statement_count=8,
        formal_statement_count=8,
        qualitative_failure_count=1,
    )

    request = prepare_controller_proportional_quality_decision(
        registry,
        reason_code="proportional_quality_budget_exhausted",
        phase_id="phase1-why2",
        question="Resolve the qualitative-only SAGE failure.",
        source_state_revision=12,
        repair_state=_proportional_repair_state(),
        recommendation_evidence=evidence,
        option_contract=policy.options,
    )

    assert [option.id for option in request.options] == [
        "extend_once",
        "continue_with_debt",
        "stop",
    ]
    assert [option.id for option in request.options if option.recommended] == [
        "continue_with_debt"
    ]
    assert next(
        option for option in request.options if option.id == "continue_with_debt"
    ).risk_level == "high"


@pytest.mark.parametrize(
    ("reason_code", "extension_authorized", "extension_consumed", "expected"),
    (
        ("proportional_quality_budget_exhausted", 0, 0, "extend_once"),
        ("proportional_quality_extension_exhausted", 1, 1, "stop"),
    ),
)
def test_qualitative_hard_blocker_never_recommends_impossible_debt(
    reason_code: str,
    extension_authorized: int,
    extension_consumed: int,
    expected: str,
) -> None:
    registry = HumanInputPolicyRegistry(controller_safeguard_policies())
    policy = registry.lookup(
        "controller_safeguard",
        reason_code,
        reason_code,
    )
    passing = (
        ("overall", 0.90, 0.80, True),
        ("structure", 0.85, 0.80, True),
    )
    evidence = ProportionalQualityRecommendationEvidence(
        borderline_margin=0.05,
        previous_gates=passing,
        current_gates=passing,
        previous_formal_statement_count=8,
        formal_statement_count=8,
        qualitative_failure_count=1,
        qualitative_hard_blocker_count=1,
    )

    request = prepare_controller_proportional_quality_decision(
        registry,
        reason_code=reason_code,
        phase_id="phase1-why2",
        question="Resolve the residual SAGE contradiction.",
        source_state_revision=12,
        repair_state=_proportional_repair_state(
            extension_authorized=extension_authorized,
            extension_consumed=extension_consumed,
        ),
        recommendation_evidence=evidence,
        option_contract=policy.options,
    )

    assert [option.id for option in request.options if option.recommended] == [
        expected
    ]
    assert not next(
        option for option in request.options if option.id == "continue_with_debt"
    ).recommended


def test_proportional_budget_policy_cannot_be_prepared_after_extension_authorization(
) -> None:
    registry = HumanInputPolicyRegistry(controller_safeguard_policies())
    policy = registry.lookup(
        "controller_safeguard",
        "proportional_quality_budget_exhausted",
        "proportional_quality_budget_exhausted",
    )

    with pytest.raises(HumanInputPolicyError, match="extension"):
        prepare_controller_proportional_quality_decision(
            registry,
            reason_code="proportional_quality_budget_exhausted",
            phase_id="phase1-why2",
            question="Choose how to resolve the exhausted proportional quality budget.",
            source_state_revision=12,
            repair_state=_proportional_repair_state(extension_authorized=1),
            recommendation_evidence=_proportional_recommendation_evidence(),
            option_contract=policy.options,
        )


@pytest.mark.parametrize(
    "option_contract",
    [
        lambda options: (replace(options[0], id="forged"), *options[1:]),
        lambda options: (
            replace(options[0], description="Provider-authored effect."),
            *options[1:],
        ),
        lambda options: (
            replace(options[0], next_phase="terminal-blocked"),
            *options[1:],
        ),
        lambda options: (replace(options[0], outcome="approved"), *options[1:]),
    ],
    ids=("id", "description", "target", "outcome"),
)
def test_controller_recommendation_helper_rejects_non_recommendation_option_changes(
    option_contract,
) -> None:
    registry = HumanInputPolicyRegistry(controller_safeguard_policies())
    policy = registry.lookup(
        "controller_safeguard",
        "proportional_quality_budget_exhausted",
        "proportional_quality_budget_exhausted",
    )

    with pytest.raises(HumanInputPolicyError, match="option contract"):
        prepare_controller_proportional_quality_decision(
            registry,
            reason_code="proportional_quality_budget_exhausted",
            phase_id="phase1-why2",
            question="Choose how to resolve the exhausted proportional quality budget.",
            source_state_revision=12,
            repair_state=_proportional_repair_state(),
            recommendation_evidence=_proportional_recommendation_evidence(),
            option_contract=option_contract(policy.options),
        )


def test_provider_preparation_cannot_supply_quality_options_or_recommendation_evidence(
) -> None:
    registry = HumanInputPolicyRegistry(controller_safeguard_policies())

    with pytest.raises(HumanInputPolicyError, match="provider options"):
        registry.prepare(
            source_kind="controller_safeguard",
            producer_id="proportional_quality_budget_exhausted",
            phase_id="phase1-why2",
            reason_code="proportional_quality_budget_exhausted",
            question="Choose how to resolve the exhausted proportional quality budget.",
            source_state_revision=12,
            options=[],
        )

    with pytest.raises(HumanInputPolicyError, match="policy-owned fields"):
        registry.prepare(
            source_kind="controller_safeguard",
            producer_id="proportional_quality_budget_exhausted",
            phase_id="phase1-why2",
            reason_code="proportional_quality_budget_exhausted",
            question="Choose how to resolve the exhausted proportional quality budget.",
            source_state_revision=12,
            recommendation_evidence=_proportional_recommendation_evidence(),
        )


@pytest.mark.parametrize(
    ("autonomy_mode", "expected_status"),
    (
        ("guided", "awaiting_human"),
        ("semi", "awaiting_human"),
        ("banzai", "pending"),
    ),
)
@pytest.mark.parametrize(
    "reason_code",
    (
        "proportional_quality_budget_exhausted",
        "proportional_quality_extension_exhausted",
    ),
)
def test_material_proportional_quality_decision_status_is_autonomy_bounded(
    reason_code: str,
    autonomy_mode: str,
    expected_status: str,
) -> None:
    registry = HumanInputPolicyRegistry(controller_safeguard_policies())
    policy = registry.lookup(
        "controller_safeguard",
        reason_code,
        reason_code,
    )
    extension_exhausted = (
        reason_code == "proportional_quality_extension_exhausted"
    )
    request = registry.prepare_controller(
        source_kind="controller_safeguard",
        producer_id=policy.producer_id,
        phase_id="phase1-why2",
        reason_code=policy.reason_code,
        question="Choose how to resolve the exhausted proportional quality budget.",
        source_state_revision=12,
        repair_state=_proportional_repair_state(
            extension_authorized=1 if extension_exhausted else 0,
            extension_consumed=1 if extension_exhausted else 0,
        ),
        recommendation_evidence=_proportional_recommendation_evidence(),
        option_contract=policy.options,
    )

    assert select_initial_decision_status(autonomy_mode, policy, request) == (
        expected_status
    )
