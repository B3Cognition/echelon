"""Immutable lifecycle requests and pure validation; no storage or publication."""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
import re
from typing import TypeAlias


_LABEL = re.compile(r"(AC|FR|NFR|ISS|UI|II|U|A|T)-([A-Za-z0-9][A-Za-z0-9_.-]*)\Z")
_REVISION = re.compile(r"[1-9][0-9]*\Z")


def text(value, name):
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be a nonblank string without NUL")
    # Reject unencodable text before any transaction or digest computation.
    value.encode("utf-8")


def label(value):
    if type(value) is not str or not (match := _LABEL.fullmatch(value)):
        raise ValueError("element_id must have a recognized kind and ASCII legacy suffix")
    suffix = match[2]
    if suffix.isdecimal() and not suffix.strip("0"):
        raise ValueError("numeric element ordinals must be positive")


def revision(value):
    if type(value) is not str or not _REVISION.fullmatch(value):
        raise ValueError("revision must be a positive canonical decimal string")


@dataclass(frozen=True, slots=True)
class ElementCreate:
    element_id: str
    subject: str
    content: str
    reservation_operation_id: str

    def __post_init__(self):
        label(self.element_id)
        text(self.subject, "subject")
        text(self.content, "content")
        text(self.reservation_operation_id, "reservation_operation_id")


@dataclass(frozen=True, slots=True)
class ElementAdopt:
    element_id: str
    subject: str
    content: str

    def __post_init__(self):
        label(self.element_id)
        text(self.subject, "subject")
        text(self.content, "content")


@dataclass(frozen=True, slots=True)
class ElementRevision:
    element_id: str
    expected_revision: str
    subject: str
    content: str

    def __post_init__(self):
        label(self.element_id)
        revision(self.expected_revision)
        text(self.subject, "subject")
        text(self.content, "content")


@dataclass(frozen=True, slots=True)
class ElementRetirement:
    element_id: str
    expected_revision: str
    reason: str

    def __post_init__(self):
        label(self.element_id)
        revision(self.expected_revision)
        text(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class ElementSnapshotMembership:
    """Controller-selected snapshot membership, never permanent retirement."""
    element_id: str
    expected_revision: str
    present: bool
    source_revision: str | None
    snapshot_id: str

    def __post_init__(self):
        label(self.element_id)
        if self.element_id.split("-", 1)[0] not in {"FR", "NFR", "AC"}:
            raise ValueError("snapshot membership supports requirements only")
        revision(self.expected_revision)
        if type(self.present) is not bool:
            raise ValueError("present must be a boolean")
        if self.present:
            revision(self.source_revision)
        elif self.source_revision is not None:
            raise ValueError("absence cannot select content")
        text(self.snapshot_id, "snapshot_id")


@dataclass(frozen=True, slots=True)
class ElementTransition:
    kind: str
    predecessors: tuple[tuple[str, str], ...]
    successors: tuple[ElementCreate, ...]
    reason: str

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in {"replace", "split", "merge"}:
            raise ValueError("transition kind must be replace, split, or merge")
        if type(self.predecessors) is not tuple or type(self.successors) is not tuple:
            raise ValueError("transition inputs must be tuples")
        for pair in self.predecessors:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError("predecessor must contain an exact ID and expected revision")
            label(pair[0])
            revision(pair[1])
        for successor in self.successors:
            if type(successor) is not ElementCreate:
                raise ValueError("successor must be ElementCreate")
            successor.__post_init__()
        p, s = len(self.predecessors), len(self.successors)
        if not ((self.kind == "replace" and p == s == 1)
                or (self.kind == "split" and p == 1 and s >= 2)
                or (self.kind == "merge" and p >= 2 and s == 1)):
            raise ValueError("invalid transition cardinality")
        labels = [pair[0] for pair in self.predecessors] + [item.element_id for item in self.successors]
        if len(set(labels)) != len(labels):
            raise ValueError("duplicate or overlapping transition labels")
        text(self.reason, "reason")


LifecycleChange: TypeAlias = ElementCreate | ElementAdopt | ElementRevision | ElementRetirement | ElementTransition | ElementSnapshotMembership
_TYPES = (ElementCreate, ElementAdopt, ElementRevision, ElementRetirement, ElementTransition, ElementSnapshotMembership)


def request(changes: Sequence[LifecycleChange]) -> tuple[tuple[LifecycleChange, ...], list, tuple[str, ...]]:
    """Copy a request, validate strict types and order-independent entity scope."""
    if not isinstance(changes, Sequence) or isinstance(changes, (str, bytes)) or not changes:
        raise ValueError("changes must be a nonempty sequence of lifecycle operations")
    changes = tuple(changes)
    labels, payload = [], []
    for change in changes:
        if type(change) not in _TYPES:
            raise ValueError("unsupported lifecycle change")
        change.__post_init__()
        payload.append([type(change).__name__, asdict(change)])
        if type(change) is ElementTransition:
            labels.extend(pair[0] for pair in change.predecessors)
            labels.extend(item.element_id for item in change.successors)
        else:
            labels.append(change.element_id)
    if len(set(labels)) != len(labels):
        raise ValueError("multiple changes to the same entity in one batch")
    return changes, payload, tuple(labels)
