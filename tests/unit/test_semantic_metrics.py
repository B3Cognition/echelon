"""Shared semantic-role contracts."""

import pytest

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
    ],
)
def test_shared_detector_selects_known_action_verbs(
    text: str, action: str, object: str
) -> None:
    roles = SemanticAnalyzer(use_spacy=False).extract_roles_as_dict(text)

    assert roles["actors"] == ["the command"]
    assert roles["actions"] == [action]
    assert roles["objects"] == [object]
