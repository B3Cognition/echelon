"""Shared, dependency-free role evidence for formal requirements."""

from __future__ import annotations

from dataclasses import dataclass
import re


_MODAL_RE = re.compile(r"\b(shall|must|should|will|can|may)\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
_LEADING_NON_ACTION = {"not", "be", "able", "to", "become", "required"}


@dataclass(frozen=True)
class RequirementRoles:
    actor: str | None
    action: str | None
    object: str | None
    detector_evidence: tuple[str, ...]


def detect_requirement_roles(text: str) -> RequirementRoles:
    """Find the subject, first action, and action complement without NLP."""
    modal = _MODAL_RE.search(text)
    if not modal:
        return RequirementRoles(None, None, None, ("no_modal",))

    subject = text[: modal.start()].strip(" ,;:")
    if "," in subject:
        subject = subject.rsplit(",", 1)[-1].strip()
    subject = re.sub(r"^(?:then\s+)", "", subject, flags=re.IGNORECASE)
    words = list(_WORD_RE.finditer(text[modal.end() :]))
    action_match = next(
        (
            word
            for word in words
            if word.group(0).lower() not in _LEADING_NON_ACTION
            and not word.group(0).lower().endswith("ly")
        ),
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
    tail = text[modal.end() + action_match.end() :].strip(" .;:,")
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
