"""Closed discovery semantic replies; no allocation, dispatch or write authority."""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import json
import re
import unicodedata

from harness.element_identity_lifecycle import label, revision


DISCOVERY_ROLES = {
    "unknowns.md": "unknowns", "assumptions.md": "assumptions",
    "glossary.md": "glossary", "mental-model.md": "references",
    "boundaries.md": "references", "reference-architectures.md": "references",
}
_MAX_REPLY_BYTES = 256 * 1024


def _plain(value):
    if (type(value) is not str or not value.strip() or len(value) > 8192
            or any(unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} for char in value)):
        raise ValueError("discovery metadata must be nonblank single-line text")
    value.encode("utf-8")


def _discovery_id(value):
    label(value)
    if value.split("-", 1)[0] not in {"U", "A"}:
        raise ValueError("discovery supports only U/A identities")


def _object(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError("discovery object has an invalid schema")


@dataclass(frozen=True)
class DiscoveryAssignment:
    operation_id: str
    dispatch_id: str
    spec_id: str
    run_id: str
    step: str
    input_fingerprint: str
    artifact_paths: tuple[str, ...]
    editable_revisions: tuple[tuple[str, str], ...] = ()
    assigned_ids: tuple[str, ...] = ()

    def identity(self) -> dict:
        for value in (self.operation_id, self.dispatch_id, self.spec_id, self.run_id):
            _plain(value)
        if type(self.step) is not str or self.step not in {"propose", "author", "review"}:
            raise ValueError("invalid discovery step")
        if type(self.input_fingerprint) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.input_fingerprint):
            raise ValueError("invalid discovery input fingerprint")
        if (type(self.artifact_paths) is not tuple or not self.artifact_paths
                or any(type(path) is not str or path not in DISCOVERY_ROLES for path in self.artifact_paths)
                or len(set(self.artifact_paths)) != len(self.artifact_paths)):
            raise ValueError("invalid discovery artifact selection")
        if type(self.editable_revisions) is not tuple or type(self.assigned_ids) is not tuple:
            raise ValueError("discovery selections must be immutable tuples")
        selected = []
        for pair in self.editable_revisions:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError("invalid editable revision")
            _discovery_id(pair[0])
            revision(pair[1])
            selected.append(pair[0])
        for item in self.assigned_ids:
            _discovery_id(item)
        if len(set(selected)) != len(selected) or len(set(self.assigned_ids)) != len(self.assigned_ids):
            raise ValueError("duplicate discovery selection")
        return dict(schema_version=1, operation_id=self.operation_id, dispatch_id=self.dispatch_id,
            spec_id=self.spec_id, run_id=self.run_id, step=self.step, input_fingerprint=self.input_fingerprint,
            artifact_paths=list(self.artifact_paths), editable_revisions=[list(pair) for pair in self.editable_revisions],
            assigned_ids=list(self.assigned_ids))


def _proposal(value, assignment):
    if type(value["new_subjects"]) is not list or type(value["revisions"]) is not list:
        raise ValueError("proposal collections must be lists")
    keys, ids = [], []
    allowed = dict(assignment.editable_revisions)
    for item in value["new_subjects"]:
        _object(item, ("key", "kind", "subject", "caption"))
        if type(item["key"]) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", item["key"]):
            raise ValueError("invalid discovery proposal handle")
        if type(item["kind"]) is not str or item["kind"] not in {"U", "A"}:
            raise ValueError("invalid discovery proposal kind")
        for field in ("subject", "caption"):
            _plain(item[field])
        keys.append(item["key"])
    for item in value["revisions"]:
        _object(item, ("id", "expected_revision"))
        _discovery_id(item["id"])
        revision(item["expected_revision"])
        if allowed.get(item["id"]) != item["expected_revision"]:
            raise ValueError("revision is outside discovery assignment")
        ids.append(item["id"])
    if len(set(keys)) != len(keys) or len(set(ids)) != len(ids):
        raise ValueError("duplicate discovery proposal")
    value["new_subjects"].sort(key=lambda item: item["key"])
    value["revisions"].sort(key=lambda item: item["id"])


def _author(value, assignment):
    _object(value["artifacts"], assignment.artifact_paths)
    for content in value["artifacts"].values():
        if type(content) is not str or "\x00" in content:
            raise ValueError("discovery artifact must be exact UTF-8 text without NUL")
        content.encode("utf-8")


def _verdict(value):
    if type(value) is not str or value not in {"accept", "reject"}:
        raise ValueError("invalid discovery review verdict")


def _review(value, assignment):
    _verdict(value["verdict"])
    _plain(value["reason"])
    if type(value["assessments"]) is not list:
        raise ValueError("discovery assessments must be a list")
    ids = []
    for item in value["assessments"]:
        _object(item, ("id", "verdict", "reason", "evidence"))
        _discovery_id(item["id"])
        _verdict(item["verdict"])
        _plain(item["reason"])
        if type(item["evidence"]) is not list or not item["evidence"]:
            raise ValueError("assessment requires evidence references")
        for citation in item["evidence"]:
            _plain(citation)
        if value["verdict"] == "accept" and item["verdict"] == "reject":
            raise ValueError("overall acceptance contradicts an assessment")
        ids.append(item["id"])
    if len(set(ids)) != len(ids) or set(ids) != set(assignment.assigned_ids):
        raise ValueError("review must assess each exact assigned ID once")
    order = {item: index for index, item in enumerate(assignment.assigned_ids)}
    value["assessments"].sort(key=lambda item: order[item["id"]])


def validate_discovery_reply(value: object, assignment: DiscoveryAssignment) -> dict:
    """Validate syntax and assignment only; citations and semantic truth need the host."""
    try:
        identity = assignment.identity()
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > _MAX_REPLY_BYTES:
            raise ValueError("oversize discovery reply")
        value = deepcopy(value)
        if type(value) is not dict or type(value.get("schema_version")) is not int:
            raise ValueError("discovery reply must be a versioned object")
        if any(value.get(key) != expected for key, expected in identity.items()):
            raise ValueError("discovery assignment binding mismatch")
        action = value.get("action")
        if type(action) is not str:
            raise ValueError("invalid discovery action")
        extra = {"new_subjects", "revisions"} if assignment.step == "propose" else (
            {"artifacts"} if assignment.step == "author" else {"verdict", "reason", "assessments"})
        fields = extra if action == "final" else {"request"} if action == "read" else {"reason"}
        if action not in {"final", "read", "blocked"}:
            raise ValueError("invalid discovery action")
        _object(value, set(identity) | {"action"} | fields)
        if action == "final":
            {"propose": _proposal, "author": _author, "review": _review}[assignment.step](value, assignment)
        elif action == "blocked":
            _plain(value["reason"])
        elif type(value["request"]) is not dict:
            raise ValueError("read request must be an object")
        return value
    except (TypeError, UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("invalid discovery reply") from exc


def parse_discovery_reply(raw: str, assignment: DiscoveryAssignment) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate discovery JSON key")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ValueError("nonfinite discovery JSON number")

    try:
        if type(raw) is not str or len(raw.encode("utf-8")) > _MAX_REPLY_BYTES:
            raise ValueError("invalid or oversize discovery reply")
        return validate_discovery_reply(json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite), assignment)
    except (UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("invalid discovery JSON") from exc
