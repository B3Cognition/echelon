"""Shared, dependency-free role evidence for formal requirements."""

from __future__ import annotations

from dataclasses import dataclass
import re


_MODAL_RE = re.compile(r"\b(shall|must|should|will|can|may)\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
_GWT_RE = re.compile(
    r"^\s*given\b.+?(?:[,;]|\n)\s*when\b.+?(?:[,;]|\n)\s*then\b\s+"
    r"(?P<outcome>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_GWT_ACTION_RE = re.compile(
    r"\b(?:is|are|has|have|contains?|remains?|shows?|displays?|renders?|"
    r"presents?|exposes?|returns?|emits?|writes?|updates?|changes?|opens?|"
    r"starts?|stops?|differs?|becomes?|equals?|observes?|collects?|"
    r"conforms?|executes?|uses?|supports?|matches?|receives?|produces?|rejects?|"
    r"accepts?|keeps?|records?|loads?|runs?|includes?)\b",
    re.IGNORECASE,
)
_ACTOR_ONLY_WORDS = {"a", "an", "the", "there"}
_UI_ELEMENT_NOUNS = {"button", "control", "link", "menu", "tab"}
_WHEN_MARKER_RE = re.compile(r"(?:[,;]|\n)\s*when\b", re.IGNORECASE)
_THEN_MARKER_RE = re.compile(r"(?:[,;]|\n)\s*then\b", re.IGNORECASE)

_INTERVENING_MODIFIERS = {
    "a", "able", "an", "always", "automatically", "be", "directly",
    "explicitly", "immediately", "never", "not", "only", "quickly",
    "reliably", "required", "safely", "the", "to",
}


@dataclass(frozen=True)
class RequirementRoles:
    actor: str | None
    action: str | None
    object: str | None
    detector_evidence: tuple[str, ...]


def detect_requirement_roles(text: str) -> RequirementRoles:
    """Find the subject, first action, and action complement without NLP."""
    gwt = _GWT_RE.match(text)
    if (
        not gwt
        and re.match(r"^\s*given\b", text, re.IGNORECASE)
        and _WHEN_MARKER_RE.search(text)
        and _THEN_MARKER_RE.search(text)
    ):
        return RequirementRoles(None, None, None, ("unparsed_gwt",))
    clause = gwt.group("outcome") if gwt else text
    modal = _MODAL_RE.search(clause)
    if not modal:
        if gwt:
            for predicate in _GWT_ACTION_RE.finditer(clause):
                subject = clause[: predicate.start()].strip(" ,;:")
                complement = clause[predicate.end() :].strip(" .;:,")
                subject_words = [
                    word.group(0).lower() for word in _WORD_RE.finditer(subject)
                ]
                next_word = _WORD_RE.search(clause, predicate.end())
                label_noun = (
                    next_word is not None
                    and not clause[predicate.end() : next_word.start()].strip()
                    and next_word.group(0).lower() in _UI_ELEMENT_NOUNS
                    and not predicate.group(0).lower().endswith("s")
                )
                if (
                    any(word not in _ACTOR_ONLY_WORDS for word in subject_words)
                    and complement
                    and len(subject_words) <= 8
                    and predicate.group(0).islower()
                    and not label_noun
                    and not re.search(r"\b(?:given|when|then)\b", subject, re.IGNORECASE)
                ):
                    return RequirementRoles(
                        subject.lower(),
                        predicate.group(0).lower(),
                        complement.lower(),
                        ("gwt:then", "subject_before_action", "object_after_action"),
                    )
        return RequirementRoles(None, None, None, ("no_modal",))

    subject = clause[: modal.start()].strip(" ,;:")
    if "," in subject:
        subject = subject.rsplit(",", 1)[-1].strip()
    subject = re.sub(r"^(?:then\s+)", "", subject, flags=re.IGNORECASE)
    words = list(_WORD_RE.finditer(clause[modal.end() :]))
    action_match = next(
        (word for word in words if word.group(0).lower() not in _INTERVENING_MODIFIERS),
        None,
    )
    if action_match is None:
        return RequirementRoles(
            subject.lower() or None,
            None,
            None,
            (f"modal:{modal.group(1).lower()}", "subject_before_modal", "no_action"),
        )
    action = action_match.group(0).lower()
    tail = clause[modal.end() + action_match.end() :].strip(" .;:,")
    evidence = [f"modal:{modal.group(1).lower()}"]
    if subject:
        evidence.append("subject_before_modal")
    evidence.append("first_action_after_modal")
    if tail:
        evidence.append("object_after_action")
    return RequirementRoles(
        subject.lower() or None,
        action,
        tail.lower() or None,
        tuple(evidence),
    )
