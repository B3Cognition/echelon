import json
from pathlib import Path

import pytest

from harness.human_input import HumanInputOption
from harness.squad import _checkpoint_context, _resolve_human_input_option_answer


OPTIONS = (
    HumanInputOption(
        id="approve",
        label="Approve",
        description="Continue.",
        recommended=False,
        risk_level="medium",
        next_phase="phase2-decide",
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


@pytest.mark.unit
def test_checkpoint_context_explains_human_gate_and_recent_repairs(tmp_path: Path) -> None:
    journal = tmp_path / "reasoning-journal.jsonl"
    journal.write_text(
        json.dumps(
            {
                "phase": "phase1-lexicon-derive",
                "type": "insight",
                "data": {
                    "artifact": "requirements.lexicon.md",
                    "reasoning": (
                        "Repair finding source-hash-mismatch was caused solely by "
                        "a stale SOURCE_SHA256 header value. Corrected only the "
                        "header line; verified all 18 FR and 5 NFR identifiers "
                        "from spec.md are already present verbatim."
                    ),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    context = _checkpoint_context(
        {
            "autonomy_mode": "semi",
            "quality_scores": [
                {
                    "pass": True,
                    "pass_id": "WHY2-iter-4",
                    "overall": 0.8092,
                    "structure": 0.95,
                    "testability": 0.9271,
                    "cognitive": 0.6732,
                }
            ],
            "lexicon_evaluation": "passed",
            "lexicon_findings": 0,
            "lexicon_report": "runs/spec/spec-lexicon-report.json",
        },
        node_id="checkpoint-assess",
        node_label="Phase 1 Checkpoint",
        journal_path=journal,
    )

    assert "Why approval is needed: semi mode pauses at Phase 1 Checkpoint" in context
    assert "WHY2 passed (WHY2-iter-4: overall 0.8092" in context
    assert "Spec Lexicon passed with 0 finding(s)" in context
    assert "source-hash-mismatch" in context
    assert "Corrected only the header line" in context


@pytest.mark.unit
def test_checkpoint_context_omits_missing_optional_evidence(tmp_path: Path) -> None:
    context = _checkpoint_context(
        {},
        node_id="checkpoint-assess",
        node_label="Phase 1 Checkpoint",
        journal_path=tmp_path / "missing.jsonl",
    )

    assert context == ""


@pytest.mark.unit
@pytest.mark.parametrize(
    ("answer", "expected_id"),
    [
        ("A", "approve"),
        ("a", "approve"),
        ("A:", "approve"),
        ("B", "reject"),
        ("approve", "approve"),
        ("Reject", "reject"),
    ],
)
def test_human_input_option_answer_accepts_rendered_letters_and_exact_choices(
    answer: str,
    expected_id: str,
) -> None:
    selected = _resolve_human_input_option_answer(answer, OPTIONS)

    assert selected is not None
    assert selected.id == expected_id


@pytest.mark.unit
def test_human_input_option_answer_rejects_unknown_letter() -> None:
    assert _resolve_human_input_option_answer("C", OPTIONS) is None
