"""Static guards for the Phase A human-input migration boundary."""

import re
from pathlib import Path

import pytest
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
SHARED_PROMPTS = {
    "tracker": ROOT / "extension" / "agents" / "control" / "tracker.md",
    "sage": ROOT / "extension" / "agents" / "exploration" / "sage.md",
    "investigator": (
        ROOT / "extension" / "agents" / "specialists" / "investigator.md"
    ),
}
SHARED_REQUIRED_CLAUSES = {
    "tracker": (
        "ALWAYS include `status: blocked`, `blocked_reason`, and a concrete "
        "`escalation_question` in `echelon_result.state_updates` when returning "
        "`verdict: STOP_AND_ASK`.",
        "For every question use `blocked_reason: human_clarification_required`.",
        "Include `escalation_recommended_answer` and `escalation_risk_level: "
        "low | medium | high | critical` together only for an evidence-backed "
        "recommendation; otherwise omit both.",
        "Never put a question on `ESCALATE` or another verdict.",
        "The controller owns clarification writes and state cleanup.",
    ),
    "sage": (
        "return `verdict: STOP_AND_ASK` with `status: blocked`, "
        "`blocked_reason: human_clarification_required`, and one concrete "
        "`escalation_question`.",
        "Include `escalation_recommended_answer` and `escalation_risk_level: "
        "low | medium | high | critical` together only when the recommendation "
        "is evidence-backed; otherwise omit both.",
        "Never attach a question to `FAIL`, `BLOCKED`, or `ESCALATE`.",
        "The controller owns clarification writes and state cleanup.",
    ),
    "investigator": (
        "For Phase A evidence resolution, every question-bearing result uses "
        "`STOP_AND_ASK`.",
        "Use `investigation_access_required` only when authority or credentials "
        "unavailable to Echelon are required.",
        "Use `human_clarification_required` only when reachable evidence is "
        "inconclusive and the remaining gap is a project decision that cannot "
        "be inferred:",
        "Include `escalation_recommended_answer` and `escalation_risk_level` "
        "together only when evidence supports a recommendation; otherwise "
        "omit both.",
        "Do not use the access reason for a source reachable under current "
        "authority.",
        "The controller owns clarification writes and state cleanup.",
    ),
}
SHARED_FORBIDDEN_CLAUSES = {
    "tracker": (
        "Questions may use `ESCALATE`.",
        "Return recommendation without escalation risk.",
        "The agent writes clarification state.",
    ),
    "sage": (
        "Attach a question to `FAIL`.",
        "Attach a question to `BLOCKED`.",
        "Attach a question to `ESCALATE`.",
        "Return recommendation without escalation risk.",
    ),
    "investigator": (
        "Use `investigation_access_required` for reachable evidence.",
        "Use `human_clarification_required` for unavailable credentials.",
        "Return recommendation without escalation risk.",
    ),
}
QUESTION_FIELDS = {
    "status",
    "blocked_reason",
    "escalation_question",
    "escalation_recommended_answer",
    "escalation_risk_level",
}
_DIRECT_WRITE_VERBS = (
    r"writ(?:e|es|ing|ten)|append(?:s|ed|ing)?|edit(?:s|ed|ing)?|"
    r"mutat(?:e|es|ed|ing)|clear(?:s|ed|ing)?|delet(?:e|es|ed|ing)|"
    r"remov(?:e|es|ed|ing)|reset(?:s|ting)?|persist(?:s|ed|ing)?|"
    r"updat(?:e|es|ed|ing)|replac(?:e|es|ed|ing)|unset(?:s|ting)?"
)
_DIRECT_WRITE_TARGETS = (
    r"user-clarifications|clarification(?:s)?|state\.json|"
    r"escalation_question|blocked_decision|cleanup fields?"
)
_DIRECT_WRITE_PATTERN = re.compile(
    rf"\b(?:{_DIRECT_WRITE_VERBS})\b"
    rf"(?:(?![.!?]).|\n){{0,180}}"
    rf"\b(?:{_DIRECT_WRITE_TARGETS})\b"
    rf"|"
    rf"\b(?:{_DIRECT_WRITE_TARGETS})\b"
    rf"(?:(?![.!?]).|\n){{0,180}}"
    rf"\b(?:{_DIRECT_WRITE_VERBS})\b",
    re.IGNORECASE,
)
_DIRECT_WRITE_EXEMPTION = re.compile(
    r"\b(?:never|do not|does not|must not|you do not)\b|"
    r"\b(?:controller owns|controller applies|harness handles)\b",
    re.IGNORECASE,
)
_CLAUSE_BOUNDARY = re.compile(r"[.!?](?=\s+(?:[A-Z*#`]|\Z))")


def _workflow_phases() -> dict[str, dict]:
    definition = yaml.safe_load(DEFINITION.read_text(encoding="utf-8"))
    return {phase["id"]: phase for phase in definition["phases"]}


def _normalized_prompt(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _direct_write_instruction(text: str) -> str | None:
    for match in _DIRECT_WRITE_PATTERN.finditer(text):
        paragraph_start = text.rfind("\n\n", 0, match.start())
        paragraph_end = text.find("\n\n", match.end())
        content_start = paragraph_start + 2 if paragraph_start >= 0 else 0
        content_end = paragraph_end if paragraph_end >= 0 else len(text)
        paragraph = text[
            content_start:content_end
        ]
        relative_start = match.start() - content_start
        boundaries = [
            0,
            *(
                boundary.end()
                for boundary in _CLAUSE_BOUNDARY.finditer(paragraph)
            ),
            len(paragraph),
        ]
        clause = paragraph
        for start, end in zip(boundaries, boundaries[1:]):
            if start <= relative_start < end:
                clause = paragraph[start:end]
                break
        if _DIRECT_WRITE_EXEMPTION.search(clause) is None:
            return match.group(0)
    return None


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

    for prompt_name, path in SHARED_PROMPTS.items():
        text = _normalized_prompt(path)
        for clause in SHARED_REQUIRED_CLAUSES[prompt_name]:
            assert clause in text
        for clause in SHARED_FORBIDDEN_CLAUSES[prompt_name]:
            assert clause not in text


def test_stop_and_ask_producers_allow_the_complete_question_shape() -> None:
    phases = _workflow_phases()

    for producer_id in PROVIDER_PROMPTS:
        phase = phases[producer_id]
        assert QUESTION_FIELDS <= set(phase["allowed_state_updates"])
        assert phase["state_update_types"]["status"] == "string"
        assert phase["state_update_enums"]["status"] == ["blocked"]


@pytest.mark.parametrize(
    ("path", "required_clauses"),
    [
        (
            PROVIDER_PROMPTS["phase1-investigate"],
            (
                "Use `human_clarification_required` with `inconclusive` only "
                "when the remaining gap is a project decision that cannot be "
                "inferred.",
                "Use `investigation_access_required` with `access_required` "
                "only when authority or credentials unavailable to Echelon "
                "are required.",
                "Do not use the access reason for an unread source that remains "
                "reachable with current authority.",
            ),
        ),
        (
            SHARED_PROMPTS["investigator"],
            (
                "Use `investigation_access_required` only when authority or "
                "credentials unavailable to Echelon are required.",
                "Use `human_clarification_required` only when reachable "
                "evidence is inconclusive and the remaining gap is a project "
                "decision that cannot be inferred:",
                "Do not use the access reason for a source reachable under "
                "current authority.",
            ),
        ),
    ],
)
def test_investigation_prompts_reserve_access_reason_for_external_authority(
    path: Path,
    required_clauses: tuple[str, ...],
) -> None:
    text = _normalized_prompt(path)

    for clause in required_clauses:
        assert clause in text


@pytest.mark.parametrize(
    "instruction",
    [
        "Persist the clarification\nin state.json.",
        "Update\n`escalation_question` after resolving the choice.",
        "Replace blocked_decision with the selected answer.",
        "Unset\nstate.json cleanup fields.",
        (
            "Do not update state.json manually. "
            "Persist the clarification in state.json."
        ),
    ],
)
def test_direct_write_guard_detects_multiline_equivalent_instructions(
    instruction: str,
) -> None:
    assert _direct_write_instruction(instruction) is not None


@pytest.mark.parametrize(
    "instruction",
    [
        "Do not persist the clarification in state.json.",
        "Never update escalation_question or blocked_decision.",
        "The controller owns clarification writes and state cleanup.",
        "The harness handles state.json application and cleanup.",
    ],
)
def test_direct_write_guard_allows_explicit_controller_ownership(
    instruction: str,
) -> None:
    assert _direct_write_instruction(instruction) is None


def test_commander_has_no_direct_clarification_or_state_cleanup_instruction() -> None:
    text = COMMANDER.read_text(encoding="utf-8")

    assert "write the clarification" not in text.lower()
    assert "append the clarification" not in text.lower()
    assert "clear `escalation_question`" not in text
    assert "delete `blocked_decision`" not in text
    assert _direct_write_instruction(text) is None
