"""Unit tests for the Lexicon extraction strategy in understanding's parser."""

import pytest

from understanding.markdown_parser import (
    extract_lexicon_requirements,
    extract_requirements,
    is_lexicon_spec,
)

LEXICON_SPEC = """ARTIFACT: SPEC
TITLE: Word frequency counter

REQ: FR-001
GIVEN: a readable file path is provided
WHEN: the tool is invoked
THEN: the tool MUST read the entire contents of that file as the input text
OUTPUT: the full character stream is available to the pipeline

REQ: FR-002
GIVEN: a decoded character stream
WHEN: the aggregation stage runs
THEN: the tool MUST count occurrences of each distinct normalized word
OUTPUT: a frequency table keyed by normalized word
CONSTRAINT: processing_time <= 2 s for inputs up to 100 MB

AC: AC-001
GIVEN: an input file with five words
WHEN: the tool is invoked
THEN: the output lists each word with its count
"""

BULLET_SPEC = """# Spec

## Requirements

- **FR-001**: The system SHALL read the input file and decode it as UTF-8 text.
- **FR-002**: The system SHALL count occurrences of each distinct word.
"""


@pytest.mark.unit
def test_is_lexicon_spec_detects_artifact_header():
    assert is_lexicon_spec(LEXICON_SPEC) is True


@pytest.mark.unit
def test_is_lexicon_spec_false_for_bullet_spec():
    assert is_lexicon_spec(BULLET_SPEC) is False


@pytest.mark.unit
def test_extract_lexicon_requirements_keys_then_clause_by_id():
    reqs = extract_lexicon_requirements(LEXICON_SPEC)
    assert [rid for rid, _ in reqs] == ["FR-001", "FR-002"]
    # The THEN normative statement is the core of each requirement text.
    assert "the tool MUST read the entire contents" in reqs[0][1]
    assert "MUST count occurrences" in reqs[1][1]


@pytest.mark.unit
def test_rich_fold_includes_trigger_output_and_constraint():
    # The folded view feeds semantic/behavioral metrics, which need the WHEN
    # trigger and OUTPUT outcome present, plus the CONSTRAINT threshold.
    reqs = dict(extract_lexicon_requirements(LEXICON_SPEC))
    assert "when the tool is invoked" in reqs["FR-001"]      # WHEN trigger folded in
    assert "character stream" in reqs["FR-001"]              # OUTPUT folded in
    assert "processing_time <= 2 s" in reqs["FR-002"]         # CONSTRAINT folded in


@pytest.mark.unit
def test_humanize_identifiers_splits_snake_and_camel():
    from understanding.requirements_metrics import _humanize_identifiers

    assert _humanize_identifiers("the Temperature_Converter sets converted_value") == (
        "the Temperature Converter sets converted value"
    )
    assert _humanize_identifiers("a TemperatureConverter object") == "a Temperature Converter object"


@pytest.mark.unit
def test_ac_then_clause_is_not_extracted_as_requirement():
    ids = [rid for rid, _ in extract_lexicon_requirements(LEXICON_SPEC)]
    assert "AC-001" not in ids


@pytest.mark.unit
def test_extract_requirements_uses_lexicon_strategy_not_id_lines():
    out = extract_requirements(LEXICON_SPEC)
    # The THEN clauses, not the "REQ: FR-001" id lines.
    assert any("MUST read the entire contents" in r for r in out)
    assert all(not r.strip().startswith("REQ:") for r in out)
    assert all(not r.strip().startswith("THEN:") for r in out)


@pytest.mark.unit
def test_extract_requirements_unchanged_for_bullet_spec():
    out = extract_requirements(BULLET_SPEC)
    joined = " ".join(out)
    assert "read the input file" in joined
    assert "count occurrences" in joined


@pytest.mark.unit
def test_bullet_extraction_uses_priority_order_not_union():
    # A "- **FR-001**:" line is caught by BOTH the structured-ID and bullet
    # strategies, and unrelated bullets inflate the count. Priority order must
    # return only the structured-ID requirements, not every bullet on the page.
    spec = (
        "# Spec\n\n## Requirements\n"
        "- **FR-001**: The system SHALL read the input file.\n"
        "- **FR-002**: The system SHALL count occurrences of each word.\n"
        "\n## Notes\n"
        "- This is a note about future scope.\n"
        "- Another note that is not a requirement.\n"
        "- A third non-requirement note here.\n"
    )
    out = extract_requirements(spec)
    assert len(out) == 2
    assert all("note" not in r.lower() for r in out)


@pytest.mark.unit
def test_cli_parse_requirements_extracts_lexicon_reqs():
    # The --per-req path SAGE uses must key per-requirement scoring off the
    # REQ ids and the THEN-clause text when the spec is Lexicon grammar.
    from understanding.cli import _parse_requirements

    parsed = _parse_requirements(LEXICON_SPEC)
    assert parsed["count"] == 2
    assert [r["id"] for r in parsed["requirements"]] == ["FR-001", "FR-002"]
    assert "MUST read the entire contents" in parsed["requirements"][0]["text"]


@pytest.mark.unit
def test_cli_parse_requirements_unchanged_for_bullet_spec():
    from understanding.cli import _parse_requirements

    parsed = _parse_requirements(BULLET_SPEC)
    assert parsed["count"] == 2
    assert [r["id"] for r in parsed["requirements"]] == ["FR-001", "FR-002"]


@pytest.mark.unit
def test_then_only_extraction_excludes_output_and_constraint():
    # The structure/atomicity path needs the atomic THEN clause, NOT the folded
    # THEN+OUTPUT+CONSTRAINT text (which reads as multiple statements).
    reqs = dict(extract_lexicon_requirements(LEXICON_SPEC, fold_output_constraint=False))
    assert reqs["FR-001"] == "the tool MUST read the entire contents of that file as the input text"
    assert "character stream" not in reqs["FR-001"]       # OUTPUT excluded
    assert "processing_time" not in reqs["FR-002"]          # CONSTRAINT excluded


@pytest.mark.unit
def test_structure_metrics_score_all_requirements_not_one():
    # Old extractor returned 1 req (the only THEN ending in a period) -> fake
    # 100% atomicity. The Lexicon path must score every REQ.
    from understanding.requirements_metrics import RequirementsAnalyzer

    s = RequirementsAnalyzer().analyze_requirements(LEXICON_SPEC).structure
    assert s.total_requirements == 2


@pytest.mark.unit
def test_lexicon_readability_not_broken_by_missing_terminal_punctuation():
    # Grammar lines (GIVEN:/WHEN:/THEN:) have no '.', so counting sentences by
    # [.!?] sees the whole spec as ~1 sentence -> avg words/sentence explodes ->
    # grade-level formulas blow up (~30+) and clamp to 0%. Scoring the extracted
    # prose (real terminated sentences) keeps the grade sane.
    from understanding.requirements_metrics import RequirementsAnalyzer

    r = RequirementsAnalyzer().analyze_requirements(LEXICON_SPEC).readability
    assert r.flesch_kincaid_grade < 25
    assert r.gunning_fog_index < 25


@pytest.mark.unit
def test_bullet_readability_still_computes_normally():
    from understanding.requirements_metrics import RequirementsAnalyzer

    r = RequirementsAnalyzer().analyze_requirements(BULLET_SPEC).readability
    assert 0 < r.flesch_kincaid_grade < 25
