from pathlib import Path

from harness.journal_prompt_validator import validate_prompt_journal_examples


def test_prompt_validator_flags_sparse_registered_journal_entry(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        """
```yaml
echelon_result:
  verdict: DONE
  state_updates: {}
  journal_entries:
    - type: insight
      phase: phase1-discover
```
""",
        encoding="utf-8",
    )

    findings = validate_prompt_journal_examples([prompt])

    assert len(findings) == 1
    assert findings[0].entry_type == "insight"
    assert findings[0].reason == "missing_data"


def test_prompt_validator_accepts_schema_complete_registered_entry(
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        """
echelon_result:
  verdict: COMPLETE
  state_updates: {}
  journal_entries:
    - type: insight
      data:
        artifact: glossary.md
        section: Terms
        reasoning: Domain terms were inferred from request language.
        confidence: 0.8
        evidence_grade: B
""",
        encoding="utf-8",
    )

    assert validate_prompt_journal_examples([prompt]) == []


def test_prompt_validator_flags_unregistered_concrete_type(tmp_path: Path) -> None:
    prompt = tmp_path / "agent.md"
    prompt.write_text(
        """
echelon_result:
  verdict: DONE
  state_updates: {}
  journal_entries:
    - type: future_phase_signal
      data:
        summary: Done.
""",
        encoding="utf-8",
    )

    findings = validate_prompt_journal_examples([prompt])

    assert len(findings) == 1
    assert findings[0].entry_type == "future_phase_signal"
    assert findings[0].reason == "unregistered_type"
