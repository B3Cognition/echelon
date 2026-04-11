"""T022: Unit test pack — constitution_checker.py

Tests per test-strategy § constitution checker.
Covers all 6 predicate types, all 4 accessor forms, SKIP for prose, and ERROR cases.
"""

import sys
from pathlib import Path

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from kernel.constitution_checker import (
    AccessorError,
    CheckResult,
    PredicateError,
    check_constitution,
    check_principle,
    evaluate_predicate,
    resolve_accessor,
)


# ---------------------------------------------------------------------------
# Test artifacts (minimal markdown + YAML)
# ---------------------------------------------------------------------------

SAMPLE_MARKDOWN = """
# Overview

This is the overview section.

## Quality Gates

The quality gate threshold is 0.70.

## Truthful Chrome

No FR may claim a user-facing affordance that is not implemented by a named code path.
Do not add keybinding-not-implemented stubs.

## Functional Requirements

### FR-001: Run ID format

Every run must have a run_id matching pattern squad-N.
citation: data-model.md

### FR-002: Mode validation

mode: brownfield

### FR-003: No citation

This FR has no citation field.
"""

SAMPLE_YAML = {
    "schema_version": 1,
    "meta": {
        "cold_start": True,
        "total_runs": 1,
    },
    "domains": {
        "evaluator": {"accuracy": 0.7}
    }
}


# ---------------------------------------------------------------------------
# Accessor tests
# ---------------------------------------------------------------------------


class TestResolveAccessorSections:
    def test_top_level_section_found(self):
        result = resolve_accessor("sections[title='Truthful Chrome']", SAMPLE_MARKDOWN)
        assert result is not None
        assert "affordance" in result

    def test_top_level_section_not_found(self):
        result = resolve_accessor("sections[title='Nonexistent Section']", SAMPLE_MARKDOWN)
        assert result is None

    def test_nested_subsection_found(self):
        result = resolve_accessor(
            "sections[title='Functional Requirements'].subsections[title='FR-001: Run ID format']",
            SAMPLE_MARKDOWN
        )
        assert result is not None
        assert "squad-N" in result

    def test_nested_subsection_not_found(self):
        result = resolve_accessor(
            "sections[title='Functional Requirements'].subsections[title='FR-999']",
            SAMPLE_MARKDOWN
        )
        assert result is None


class TestResolveAccessorFR:
    def test_fr_by_id_found(self):
        result = resolve_accessor("fr[id='FR-001']", SAMPLE_MARKDOWN)
        assert result is not None
        assert "run_id" in result or "squad" in result

    def test_fr_wildcard_returns_full_text(self):
        result = resolve_accessor("fr[id='*']", SAMPLE_MARKDOWN)
        assert result == SAMPLE_MARKDOWN

    def test_fr_not_found_returns_none(self):
        result = resolve_accessor("fr[id='FR-999']", SAMPLE_MARKDOWN)
        assert result is None


class TestResolveAccessorYamlNode:
    def test_top_level_key(self):
        result = resolve_accessor("yaml_node['schema_version']", "", SAMPLE_YAML)
        assert result == "1"

    def test_nested_key(self):
        result = resolve_accessor("yaml_node['meta.cold_start']", "", SAMPLE_YAML)
        assert result is not None

    def test_missing_key_returns_none(self):
        result = resolve_accessor("yaml_node['missing.key']", "", SAMPLE_YAML)
        assert result is None

    def test_yaml_accessor_without_parsed_yaml_raises(self):
        with pytest.raises(AccessorError) as exc_info:
            resolve_accessor("yaml_node['meta.total_runs']", SAMPLE_MARKDOWN, artifact_yaml=None)
        assert "artifact_yaml=None" in str(exc_info.value)


class TestResolveAccessorErrors:
    def test_unknown_accessor_form_raises(self):
        with pytest.raises(AccessorError) as exc_info:
            resolve_accessor("completely_invalid[accessor]", SAMPLE_MARKDOWN)
        assert "Unknown accessor form" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Predicate tests
# ---------------------------------------------------------------------------


class TestPredicateMustContain:
    def test_pass_when_contains(self):
        passed, reason = evaluate_predicate("MUST_CONTAIN affordance", "No affordance without code path.")
        assert passed
        assert "contains" in reason

    def test_fail_when_missing(self):
        passed, reason = evaluate_predicate("MUST_CONTAIN keybinding", "No affordance.")
        assert not passed
        assert "does not contain" in reason


class TestPredicateMustNotContain:
    def test_pass_when_absent(self):
        passed, reason = evaluate_predicate("MUST_NOT_CONTAIN keybinding-not-implemented", "Clean text.")
        assert passed

    def test_fail_when_present(self):
        passed, reason = evaluate_predicate(
            "MUST_NOT_CONTAIN keybinding-not-implemented",
            "stub: keybinding-not-implemented placeholder"
        )
        assert not passed


class TestPredicateMustMatchRegex:
    def test_pass_when_matches(self):
        passed, reason = evaluate_predicate(r"MUST_MATCH_REGEX squad-\d+", "run_id: squad-12345")
        assert passed

    def test_fail_when_no_match(self):
        passed, reason = evaluate_predicate(r"MUST_MATCH_REGEX squad-\d+", "run_id: run-abc")
        assert not passed

    def test_invalid_regex_raises(self):
        with pytest.raises(PredicateError):
            evaluate_predicate("MUST_MATCH_REGEX [invalid(", "text")


class TestPredicateMustNotMatchRegex:
    def test_pass_when_no_match(self):
        passed, reason = evaluate_predicate(r"MUST_NOT_MATCH_REGEX TODO:\s+\w+", "All done.")
        assert passed

    def test_fail_when_matches(self):
        passed, reason = evaluate_predicate(r"MUST_NOT_MATCH_REGEX TODO:\s+\w+", "TODO: fix this")
        assert not passed


class TestPredicateMustHaveField:
    def test_pass_when_field_present(self):
        passed, reason = evaluate_predicate("MUST_HAVE_FIELD citation", "citation: data-model.md\n")
        assert passed

    def test_fail_when_field_absent(self):
        passed, reason = evaluate_predicate("MUST_HAVE_FIELD citation", "No citation here.")
        assert not passed


class TestPredicateMustHaveNonEmptyField:
    def test_pass_when_non_empty(self):
        passed, reason = evaluate_predicate("MUST_HAVE_NON_EMPTY_FIELD citation", "citation: data-model.md\n")
        assert passed

    def test_fail_when_empty(self):
        passed, reason = evaluate_predicate("MUST_HAVE_NON_EMPTY_FIELD citation", "No citation here.")
        assert not passed


class TestPredicateErrors:
    def test_unknown_predicate_raises(self):
        with pytest.raises(PredicateError):
            evaluate_predicate("MIGHT_CONTAIN something", "text")

    def test_missing_arg_raises(self):
        with pytest.raises(PredicateError):
            evaluate_predicate("MUST_CONTAIN", "text")  # no arg


# ---------------------------------------------------------------------------
# check_principle tests
# ---------------------------------------------------------------------------


class TestCheckPrinciple:
    def test_prose_principle_is_skipped(self):
        principle = {
            "id": "I-prose-rule",
            "form": "prose",
            "text": "COMMANDER must route decisions",
            "accessor": "sections[title='Overview']",
            "predicate": "MUST_CONTAIN COMMANDER",
        }
        result = check_principle(principle, SAMPLE_MARKDOWN)
        assert result["verdict"] == "SKIP"
        assert result["principle_id"] == "I-prose-rule"

    def test_structural_principle_pass(self):
        principle = {
            "id": "IV-truthful-chrome",
            "form": "structural",
            "text": "Truthful Chrome section must exist",
            "accessor": "sections[title='Truthful Chrome']",
            "predicate": "MUST_CONTAIN affordance",
        }
        result = check_principle(principle, SAMPLE_MARKDOWN)
        assert result["verdict"] == "PASS"

    def test_structural_principle_fail(self):
        principle = {
            "id": "IV-no-stubs",
            "form": "structural",
            "text": "No stubs in Truthful Chrome",
            "accessor": "sections[title='Truthful Chrome']",
            "predicate": "MUST_NOT_CONTAIN affordance",  # This text IS there, so MUST_NOT fails
        }
        result = check_principle(principle, SAMPLE_MARKDOWN)
        assert result["verdict"] == "FAIL"

    def test_structural_principle_accessor_not_found(self):
        principle = {
            "id": "V-missing",
            "form": "structural",
            "text": "Missing section",
            "accessor": "sections[title='Nonexistent']",
            "predicate": "MUST_CONTAIN anything",
        }
        result = check_principle(principle, SAMPLE_MARKDOWN)
        assert result["verdict"] == "FAIL"
        assert "None" in result["reason"] or "not found" in result["reason"]

    def test_structural_principle_error_on_bad_predicate(self):
        principle = {
            "id": "VI-bad-pred",
            "form": "structural",
            "text": "Bad predicate",
            "accessor": "sections[title='Overview']",
            "predicate": "UNKNOWN_VERB something",
        }
        result = check_principle(principle, SAMPLE_MARKDOWN)
        assert result["verdict"] == "ERROR"


# ---------------------------------------------------------------------------
# check_constitution (batch) tests
# ---------------------------------------------------------------------------


class TestCheckConstitution:
    def test_batch_returns_one_result_per_principle(self):
        principles = [
            {"id": "P1", "form": "structural", "accessor": "sections[title='Overview']", "predicate": "MUST_CONTAIN overview"},
            {"id": "P2", "form": "prose", "accessor": "", "predicate": ""},
        ]
        results = check_constitution(principles, SAMPLE_MARKDOWN)
        assert len(results) == 2

    def test_all_pass_verdict_when_all_pass(self):
        principles = [
            {
                "id": "P1",
                "form": "structural",
                "accessor": "sections[title='Overview']",
                "predicate": "MUST_CONTAIN overview",
            }
        ]
        # Use original SAMPLE_MARKDOWN (not lowercased) so section header matches
        results = check_constitution(principles, SAMPLE_MARKDOWN)
        assert results[0]["verdict"] == "PASS"

    def test_mix_of_pass_fail_skip(self):
        principles = [
            {"id": "P1", "form": "structural", "accessor": "sections[title='Overview']", "predicate": "MUST_CONTAIN overview"},
            {"id": "P2", "form": "prose", "accessor": "", "predicate": ""},
            {"id": "P3", "form": "structural", "accessor": "sections[title='Nonexistent']", "predicate": "MUST_CONTAIN x"},
        ]
        results = check_constitution(principles, SAMPLE_MARKDOWN.lower())
        verdicts = {r["principle_id"]: r["verdict"] for r in results}
        assert verdicts["P2"] == "SKIP"
        assert verdicts["P3"] == "FAIL"

    def test_empty_principles_returns_empty(self):
        results = check_constitution([], SAMPLE_MARKDOWN)
        assert results == []
