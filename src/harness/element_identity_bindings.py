"""Immutable declared provenance requests; no file access or semantic verdicts."""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
import re

from harness.element_identity_lifecycle import label, revision, text


def source_path(value):
    text(value, "source_path")
    if "\\" in value or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("source_path must be canonical spec-relative POSIX syntax")


def sha256(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("digest must be a lowercase 64-digit SHA256 string")


def issue_label(value):
    label(value)
    if not value.startswith("ISS-"):
        raise ValueError("issue and display IDs must be ISS labels")


@dataclass(frozen=True, slots=True)
class ReferenceClaim:
    source_path: str
    source_sha256: str
    source_anchor: str
    target_id: str
    target_revision: str | None
    relation: str

    def __post_init__(self):
        source_path(self.source_path)
        sha256(self.source_sha256)
        text(self.source_anchor, "source_anchor")
        label(self.target_id)
        if self.target_revision is not None:
            revision(self.target_revision)
        if type(self.relation) is not str or self.relation not in {"reference", "requires", "depends", "evidence"}:
            raise ValueError("unsupported reference relation")


@dataclass(frozen=True, slots=True)
class IssueOccurrence:
    issue_id: str
    issue_revision: str
    report_id: str
    report_sha256: str
    display_id: str
    title: str
    body: str

    def __post_init__(self):
        issue_label(self.issue_id)
        revision(self.issue_revision)
        text(self.report_id, "report_id")
        sha256(self.report_sha256)
        issue_label(self.display_id)
        text(self.title, "title")
        text(self.body, "body")


def request(entries: Sequence, entry_type):
    """Snapshot and revalidate exact immutable types before a write transaction."""
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise ValueError("bindings must be a nonempty sequence")
    entries = tuple(entries)
    if not entries:
        raise ValueError("bindings must be a nonempty sequence")
    for entry in entries:
        if type(entry) is not entry_type:
            raise ValueError("binding must have the exact immutable request type")
        entry.__post_init__()
    if len(set(entries)) != len(entries):
        raise ValueError("duplicate binding in one batch")
    return tuple(asdict(entry) for entry in entries)
