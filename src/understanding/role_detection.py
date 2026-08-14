"""Shared, dependency-free role evidence for formal requirements."""

from __future__ import annotations

from dataclasses import dataclass
import re


_MODAL_RE = re.compile(r"\b(shall|must|should|will|can|may)\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")

# This is the one deterministic action vocabulary shared by the structural and
# semantic role paths.  Keep it as base forms so reported action tokens remain
# stable across modal constructions.
ACTION_VERBS = (
    "accept", "add", "alert", "allow", "apply", "append", "assign", "authorize",
    "block", "build", "calculate", "cancel", "check", "change", "clear", "compress",
    "compute", "confirm", "configure", "create", "decrypt", "delete", "deny",
    "deploy", "destroy", "detect", "dispatch", "display", "edit", "emit", "enable",
    "encrypt", "ensure", "evaluate", "execute", "exclude", "fetch", "filter", "generate",
    "get", "grant", "handle", "include", "install", "load", "lock", "log", "make",
    "maintain", "manage", "migrate", "modify", "notify", "perform", "permit", "persist",
    "present", "prevent", "process", "produce", "publish", "purge", "read", "record",
    "refuse", "reject", "remove", "render", "report", "retrieve", "return", "revise",
    "rely", "run", "save", "send", "set", "show", "start", "stop", "store", "submit",
    "supply", "support", "tag", "transform", "transmit", "update", "validate", "verify", "visualize",
    "multiply",
    "write",
)


def _base_action(word: str) -> str | None:
    """Return a recognised action base form without treating adverbs as verbs."""
    word = word.lower()
    if word in ACTION_VERBS:
        return word
    candidates = [word.rstrip("s"), word.removesuffix("ed"), word.removesuffix("ing")]
    if word.endswith("ies"):
        candidates.append(word[:-3] + "y")
    for candidate in candidates:
        if candidate in ACTION_VERBS:
            return candidate
    return None


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
    action_word = next(
        ((word, _base_action(word.group(0))) for word in words if _base_action(word.group(0))),
        None,
    )
    if action_word is None:
        return RequirementRoles(
            subject.lower() or None,
            None,
            None,
            (f"modal:{modal.group(1).lower()}", "subject_before_modal", "no_action"),
        )
    action_match, action = action_word
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
