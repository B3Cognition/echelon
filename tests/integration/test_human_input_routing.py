"""Integration coverage for the controller-owned autonomy boundary."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import harness.squad as squad_module
from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig, LlmConfig
from harness.human_input import (
    HumanInputOption,
    HumanInputPolicy,
    HumanInputPolicyError,
    HumanInputPolicyRegistry,
    HumanInputResolution,
    controller_safeguard_policies,
)
from harness.phase_graph import PhaseGraph
from harness.squad import SquadController, _ProviderHumanInputAdvance
from harness.squad_provider import SquadAgentResult, SquadCliProvider
from harness.squad_state import SquadStateStore, StateAdvanceError


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
    provider: object | None = None,
) -> tuple[SquadController, SquadStateStore, object]:
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

    if provider is None:
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


def _seal_awaiting_human(
    controller: SquadController,
    store: SquadStateStore,
    policy: HumanInputPolicy,
    *,
    question: str = "Which valid resolution should be applied?",
) -> tuple[str, int]:
    request = controller._human_input_registry.prepare(
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
) -> tuple[str, int]:
    request = controller._human_input_registry.prepare(
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        phase_id="phase1-what",
        reason_code=policy.reason_code,
        question="Select one sealed evidence-backed issue resolution.",
        source_state_revision=store.load()["state_revision"],
    )
    request = replace(
        request,
        options=tuple(_dispatch_cap_option(item) for item in candidates),
    )
    store.set_human_input_decision(request, initial_status=initial_status)
    state = store.load()
    return state["blocked_decision"]["id"], state["state_revision"]


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
    replacements: list[Path] = []

    def recording_replace(source: object, destination: object) -> None:
        replacements.append(Path(destination))
        real_replace(source, destination)

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
    assert clarification_path in replacements
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
        options=(
            HumanInputOption(
                id="use-answer",
                label="Use the supplied answer",
                description="Resume from the sealed source phase.",
                recommended=False,
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


def test_task6_fix_round1_dispatch_cap_uses_sealed_options_after_evidence_drift(
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
    assert state["selected_issue_resolution"] == "ISS-001"
    assert "ISS-002" not in state["issue_resolution_ledger"]


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
                    recommended=False,
                    risk_level="low",
                    next_phase="missing-phase",
                    outcome=None,
                ),
            ),
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
    assert request.options == (
        _dispatch_cap_option(_dispatch_cap_candidate()),
    )
    assert call.kwargs == {}
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
    request = _request(controller, store, policy)
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
    request = _request(controller, store, policy)
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
    request = _request(controller, store, policy)
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
    request = controller._human_input_registry.prepare(
        source_kind=policy.source_kind,
        producer_id=policy.producer_id,
        phase_id="phase1-what",
        reason_code=policy.reason_code,
        question="Select one sealed evidence-backed issue resolution.",
        source_state_revision=store.load()["state_revision"],
    )
    request = replace(
        request,
        options=(_dispatch_cap_option(_dispatch_cap_candidate()),),
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
                recommended=False,
                risk_level="medium",
                next_phase="missing-phase",
                outcome=None,
            ),
        ),
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
