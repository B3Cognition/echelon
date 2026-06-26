"""Pytest migration for language-rule file contract checks."""

from pathlib import Path

import pytest

from tests.contract.language_rules import validate_language_rules


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_language_rule_files_match_contract() -> None:
    failures = validate_language_rules(ROOT)

    assert failures == []
