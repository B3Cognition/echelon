"""Shared structural-role contracts for requirements metrics."""

import pytest

from understanding.requirements_metrics import RequirementsAnalyzer


@pytest.mark.unit
def test_structure_counts_domain_actor_roles_as_complete() -> None:
    """A vocabulary change must not make a grammatical requirement incomplete."""
    structure = RequirementsAnalyzer()._analyze_structure(
        ["The greeting command must write the configured message to standard output."]
    )

    assert structure.actor_action_complete == 1
    assert structure.actor_action_incomplete == 0
