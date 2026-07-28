"""Static guards for the Phase A human-input migration boundary."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "extension" / "workflow" / "definition.yaml"
SQUAD = ROOT / "src" / "harness" / "squad.py"
EXECUTORS = ROOT / "src" / "harness" / "squad_executors.py"
COMMANDER = ROOT / "extension" / "agents" / "control" / "commander.md"

PROVIDER_PROMPTS = {
    "phase1-tracker": (
        ROOT / "extension" / "workflow" / "phases" / "phase1-tracker.md"
    ),
    "phase1-why1": (
        ROOT / "extension" / "workflow" / "phases" / "phase1-why1.md"
    ),
    "phase1-why2": (
        ROOT / "extension" / "workflow" / "phases" / "phase1-why2.md"
    ),
    "phase1-investigate": (
        ROOT / "extension" / "workflow" / "phases" / "phase1-investigate.md"
    ),
    "phase2-tracker-alignment": (
        ROOT
        / "extension"
        / "workflow"
        / "phases"
        / "phase2-tracker-alignment.md"
    ),
}
SHARED_PROMPTS = (
    ROOT / "extension" / "agents" / "control" / "tracker.md",
    ROOT / "extension" / "agents" / "exploration" / "sage.md",
    ROOT / "extension" / "agents" / "specialists" / "investigator.md",
)
QUESTION_FIELDS = {
    "status",
    "blocked_reason",
    "escalation_question",
    "escalation_recommended_answer",
    "escalation_risk_level",
}


def _workflow_phases() -> dict[str, dict]:
    definition = yaml.safe_load(DEFINITION.read_text(encoding="utf-8"))
    return {phase["id"]: phase for phase in definition["phases"]}


def test_phase_a_has_no_terminal_human_input_executor() -> None:
    squad_text = SQUAD.read_text(encoding="utf-8")
    executor_text = EXECUTORS.read_text(encoding="utf-8")

    assert "HumanGateExecutor" not in squad_text
    assert "HumanGateExecutor" not in executor_text
    assert '"human_gate": HumanGateExecutor' not in squad_text
    assert re.search(r"\binput\(", squad_text) is None
    assert re.search(r"\binput\(", executor_text) is None


def test_workflow_gates_have_only_compiled_outcome_policy() -> None:
    phases = _workflow_phases()

    for gate_id in ("checkpoint-assess", "checkpoint-plan"):
        gate = phases[gate_id]
        assert "autonomy" not in gate
        assert len(gate["human_input"]) == 1
        assert {
            transition["outcome"]
            for transition in gate["transitions"]
        } == {"approved", "rejected"}


def test_question_capable_provider_edges_do_not_accept_escalate() -> None:
    phases = _workflow_phases()

    for producer_id in PROVIDER_PROMPTS:
        phase = phases[producer_id]
        assert "ESCALATE" not in (phase.get("allowed_verdicts") or [])
        assert all(
            "ESCALATE" not in transition.get("condition", "")
            for transition in phase["transitions"]
        )


def test_provider_prompts_declare_exact_controller_question_shape() -> None:
    for producer_id, path in PROVIDER_PROMPTS.items():
        text = path.read_text(encoding="utf-8")
        expected_reason = (
            '"<human_clarification_required | investigation_access_required>"'
            if producer_id == "phase1-investigate"
            else "human_clarification_required"
        )
        assert re.search(
            r"verdict: STOP_AND_ASK\n"
            r"  state_updates:\n"
            r"(?:    evidence_resolution_status: .+\n)?"
            r"    status: blocked\n"
            rf"    blocked_reason: {re.escape(expected_reason)}\n"
            r"    escalation_question: .+\n"
            r"    escalation_recommended_answer: .+\n"
            r"    escalation_risk_level: .+",
            text,
        )
        assert (
            "Include `escalation_recommended_answer` and "
            "`escalation_risk_level` together"
        ) in text
        assert (
            "question-bearing" in text
            or "Return a question only" in text
            or "Use `STOP_AND_ASK` only" in text
        )
        assert "STOP_AND_ASK" in text

    for path in SHARED_PROMPTS:
        text = path.read_text(encoding="utf-8")
        assert "STOP_AND_ASK" in text
        assert "blocked_reason" in text
        assert "human_clarification_required" in text
        assert "escalation_question" in text
        assert "escalation_recommended_answer" in text
        assert "escalation_risk_level" in text


def test_stop_and_ask_producers_allow_the_complete_question_shape() -> None:
    phases = _workflow_phases()

    for producer_id in PROVIDER_PROMPTS:
        phase = phases[producer_id]
        assert QUESTION_FIELDS <= set(phase["allowed_state_updates"])
        assert phase["state_update_types"]["status"] == "string"
        assert phase["state_update_enums"]["status"] == ["blocked"]


def test_investigation_prompt_reserves_access_reason_for_external_authority() -> None:
    text = " ".join(
        PROVIDER_PROMPTS["phase1-investigate"]
        .read_text(encoding="utf-8")
        .split()
    )

    assert (
        "Use `human_clarification_required` with `inconclusive` only when the "
        "remaining gap is a project decision that cannot be inferred."
    ) in text
    assert (
        "Use `investigation_access_required` with `access_required` only when "
        "authority or credentials unavailable to Echelon are required."
    ) in text
    assert (
        "Do not use the access reason for an unread source that remains "
        "reachable with current authority."
    ) in text


def test_commander_has_no_direct_clarification_or_state_cleanup_instruction() -> None:
    text = COMMANDER.read_text(encoding="utf-8")

    assert "write the clarification" not in text.lower()
    assert "append the clarification" not in text.lower()
    assert "clear `escalation_question`" not in text
    assert "delete `blocked_decision`" not in text
    assert re.search(
        r"(?im)^(?!.*\b(?:never|do not|does not|must not)\b).*"
        r"\b(?:write|append|edit|mutate|clear|delete|remove|reset)\b.*"
        r"\b(?:user-clarifications|state\.json|escalation_question|"
        r"blocked_decision)\b",
        text,
    ) is None
