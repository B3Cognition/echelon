"""Shared semantic-role contracts."""

import pytest

from understanding.requirements_metrics import RequirementsAnalyzer
from understanding.role_detection import detect_requirement_roles
from understanding.semantic_metrics import SemanticAnalyzer


@pytest.mark.unit
def test_extract_roles_uses_shared_domain_actor_detection() -> None:
    """The shared detector prevents semantic and structural disagreements."""
    roles = SemanticAnalyzer(use_spacy=False).extract_roles_as_dict(
        "The greeting command must write the configured message to standard output."
    )

    assert roles["actors"] == ["the greeting command"]
    assert roles["actions"] == ["write"]
    assert roles["objects"] == ["the configured message to standard output"]
    assert roles["detector_evidence"]


@pytest.mark.unit
def test_shared_detector_skips_intervening_adverbs_before_the_action() -> None:
    roles = SemanticAnalyzer(use_spacy=False).extract_roles_as_dict(
        "The greeting command must immediately write the configured message."
    )

    assert roles["actors"] == ["the greeting command"]
    assert roles["actions"] == ["write"]
    assert roles["objects"] == ["the configured message"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "action", "object"),
    [
        ("The command must immediately write the message.", "write", "the message"),
        ("The command must always write the message.", "write", "the message"),
        ("The command must apply the policy.", "apply", "the policy"),
        ("The command must supply the value.", "supply", "the value"),
        ("The command must rely on the cache.", "rely", "on the cache"),
        ("The command must multiply the value.", "multiply", "the value"),
        ("The command must archive the record.", "archive", "the record"),
        ("The command must route the request.", "route", "the request"),
        ("The command must replicate the state.", "replicate", "the state"),
    ],
)
def test_shared_detector_selects_known_action_verbs(
    text: str, action: str, object: str
) -> None:
    roles = SemanticAnalyzer(use_spacy=False).extract_roles_as_dict(text)

    assert roles["actors"] == ["the command"]
    assert roles["actions"] == [action]
    assert roles["objects"] == [object]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "action", "object"),
    [
        (
            "The command must be able to archive the record.",
            "archive",
            "the record",
        ),
        (
            "The command must be required to route the request.",
            "route",
            "the request",
        ),
    ],
)
def test_shared_detector_skips_post_modal_auxiliary_constructions(
    text: str, action: str, object: str
) -> None:
    shared_roles = detect_requirement_roles(text)
    semantic_roles = SemanticAnalyzer(use_spacy=False).extract_roles_as_dict(text)
    structure = RequirementsAnalyzer()._analyze_structure([text])

    assert shared_roles.actor == "the command"
    assert shared_roles.action == action
    assert shared_roles.object == object
    assert semantic_roles["actors"] == [shared_roles.actor]
    assert semantic_roles["actions"] == [action]
    assert semantic_roles["objects"] == [object]
    assert semantic_roles["detector_evidence"] == list(
        shared_roles.detector_evidence
    )
    assert structure.actor_action_complete == 1
    assert structure.actor_action_incomplete == 0
