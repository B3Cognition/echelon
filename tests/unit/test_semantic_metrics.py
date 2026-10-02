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
def test_incidental_given_when_then_words_do_not_suppress_formal_modal_roles() -> None:
    roles = detect_requirement_roles(
        "Given valid input, the server must log when validation fails, then "
        "notify the operator."
    )

    assert roles.actor == "the server"
    assert roles.action == "log"
    assert roles.object == "when validation fails, then notify the operator"


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


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "actor", "action", "object"),
    [
        (
            "Given a supported graphics environment, when the visitor opens "
            "the page, then the scene contains exactly one visible cube mesh.",
            "the scene",
            "contains",
            "exactly one visible cube mesh",
        ),
        (
            "Given an initialized page, when the viewport changes, then "
            "the primary canvas remains visible after resize.",
            "the primary canvas",
            "remains",
            "visible after resize",
        ),
        (
            "Given the page is active, when its interactions are observed, then "
            "no runtime network request supports that behavior.",
            "no runtime network request",
            "supports",
            "that behavior",
        ),
        (
            "Given exactly 1 delivered script and an available Python runtime, "
            "when the Invoker performs 1 Program invocation, then exactly 1 "
            "delivered artifact runs as a script through that Python runtime.",
            "exactly 1 delivered artifact",
            "runs",
            "as a script through that python runtime",
        ),
        (
            "Given the page is ready, when the user clicks the Then button, "
            "then the scene shows the cube.",
            "the scene",
            "shows",
            "the cube",
        ),
        (
            "Given the page is ready, when the user visits it, then the Open "
            "button is visible.",
            "the open button",
            "is",
            "visible",
        ),
        (
            "Given the page is ready, when the user visits it, then the Return "
            "button is visible.",
            "the return button",
            "is",
            "visible",
        ),
        (
            "Given the page is ready, when the user visits it, then the primary "
            "Open button is visible.",
            "the primary open button",
            "is",
            "visible",
        ),
        (
            "Given the page is ready, when the user visits it, then the primary "
            "open button is visible.",
            "the primary open button",
            "is",
            "visible",
        ),
        (
            "Given the request is valid\nWhen the server processes it\n"
            "Then the response includes an error code.",
            "the response",
            "includes",
            "an error code",
        ),
        (
            "Given the page is ready, when the user opens it, then the app "
            "shows button status.",
            "the app",
            "shows",
            "button status",
        ),
        (
            "Given the scene is ready, when the user starts it, then the scene "
            "shows the cube, then emits light.",
            "the scene",
            "shows",
            "the cube, then emits light",
        ),
    ],
)
def test_gwt_then_clause_supplies_explicit_roles_without_modal(
    text: str, actor: str, action: str, object: str
) -> None:
    """Valid acceptance paths must not fail formal modal-only role detection."""
    shared = detect_requirement_roles(text)
    semantic = SemanticAnalyzer(use_spacy=False).extract_roles_as_dict(text)
    structure = RequirementsAnalyzer()._analyze_structure([text])

    assert (shared.actor, shared.action, shared.object) == (actor, action, object)
    assert semantic["actors"] == [actor]
    assert semantic["actions"] == [action]
    assert semantic["objects"] == [object]
    assert structure.actor_action_complete == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "Given the system must log a request, when the page opens, then an error.",
        "Given the page is ready, when the visitor opens it, then a visible cube.",
        "Given the page is ready, when the visitor opens it, then there is a cube.",
        "Given the system must log a request\nWhen the page opens\nThen an error.",
        "Given the page is ready, when the user visits it, then the primary load button.",
        "Given the page is ready, when the user visits it, then the primary stop button.",
        "The scene contains a cube.",
    ],
)
def test_gwt_role_detection_does_not_borrow_context_or_accept_missing_action(
    text: str,
) -> None:
    """Only an explicit then-clause predicate satisfies acceptance role evidence."""
    roles = detect_requirement_roles(text)

    assert roles.action is None
    assert roles.object is None
