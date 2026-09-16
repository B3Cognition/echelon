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
TRACKER_OUTPUTS = {"user-intent.md": "intent", "stakeholder-model.md": "references"}
WHY1_OUTPUTS = {"assumption-review.md": "references", "issues.md": "issues", "unknowns.md": "unknowns"}
_MAX_REPLY_BYTES = 256 * 1024


def artifact_roles(producer):
    from harness.discovery_producer import producer_key
    if producer in {"what", "why2"}:
        from harness.discovery_spec import WHAT_OUTPUTS, WHY2_OUTPUTS
        return {**artifact_roles("constitution"), **WHAT_OUTPUTS, **WHY2_OUTPUTS}
    if producer == "constitution":
        return {**artifact_roles("why1"), "constitution.md": "references"}
    # Semantic decoding is not producer selection. Tracker execution remains
    # closed until its retained round/publication owners admit it separately.
    if producer not in {"tracker", "why1"}:
        producer_key(producer, "operation")
    return DISCOVERY_ROLES if producer == "discovery" else {
        **DISCOVERY_ROLES, "contradictions-and-gaps.md": "references", "risks.md": "references",
        **({**TRACKER_OUTPUTS, "feature-policy-reconciliation.md": "references"} if producer in {"tracker", "why1"} else {}),
        **(WHY1_OUTPUTS if producer == "why1" else {})}


def identity_kinds(producer):
    if producer in {"what", "why2"}:
        return {"FR", "NFR", "AC"} if producer == "what" else {"ISS"}
    if producer == "constitution":
        return set()
    if producer == "why1":
        return {"U", "ISS"}
    return {"UI", "II"} if producer == "tracker" else {"U", "A"}


def captured_artifact_roles(producer, *, after_review=False):
    """Read-only downstream context, never assignment or write-scope authority."""
    if type(after_review) is not bool:
        raise ValueError("invalid captured role policy")
    roles = artifact_roles(producer)
    if not after_review:
        return roles
    from harness.discovery_spec import WHAT_OUTPUTS, WHY2_OUTPUTS
    return {**artifact_roles("why1"), **roles, **WHAT_OUTPUTS, **WHY2_OUTPUTS}


def optional_artifacts(producer):
    return {"issues.md"} if producer == "why1" else {"stakeholder-model.md"} if producer == "tracker" else set()


def _plain(value):
    if (type(value) is not str or not value.strip() or len(value) > 8192
            or any(unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} for char in value)):
        raise ValueError("discovery metadata must be nonblank single-line text")
    value.encode("utf-8")


def _discovery_id(value, producer="discovery"):
    label(value)
    kinds = identity_kinds(producer)
    if value.split("-", 1)[0] not in kinds:
        raise ValueError("Tracker supports only UI/II identities" if producer == "tracker"
            else "discovery supports only U/A identities")


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
    producer: str = "discovery"
    routing: tuple[tuple[str, object], ...] | None = None

    def identity(self) -> dict:
        for value in (self.operation_id, self.dispatch_id, self.spec_id, self.run_id):
            _plain(value)
        if type(self.step) is not str or self.step not in {"propose", "author", "review"}:
            raise ValueError("invalid discovery step")
        if type(self.input_fingerprint) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.input_fingerprint):
            raise ValueError("invalid discovery input fingerprint")
        if (type(self.artifact_paths) is not tuple or not self.artifact_paths
                or any(type(path) is not str or path not in artifact_roles(self.producer) for path in self.artifact_paths)
                or len(set(self.artifact_paths)) != len(self.artifact_paths)):
            raise ValueError("invalid discovery artifact selection")
        if self.producer == "tracker" and ("user-intent.md" not in self.artifact_paths
                or not set(self.artifact_paths) <= set(TRACKER_OUTPUTS)):
            raise ValueError("Tracker can author only its assigned intent outputs")
        if self.producer == "why1" and ("assumption-review.md" not in self.artifact_paths
                or not set(self.artifact_paths) <= set(WHY1_OUTPUTS)):
            raise ValueError("WHY1 can author only its review, issues and unknown additions")
        if self.producer == "constitution" and (self.artifact_paths != ("constitution.md",)
                or self.editable_revisions or self.assigned_ids):
            raise ValueError("Constitution has one shared artifact and no identity scope")
        if self.producer in {"what", "why2"}:
            from harness.discovery_spec import WHAT_OUTPUTS, WHY2_OUTPUTS
            if set(self.artifact_paths) != set(WHAT_OUTPUTS if self.producer == "what" else WHY2_OUTPUTS):
                raise ValueError("specification producer must author its exact canonical outputs")
        if type(self.editable_revisions) is not tuple or type(self.assigned_ids) is not tuple:
            raise ValueError("discovery selections must be immutable tuples")
        selected = []
        for pair in self.editable_revisions:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError("invalid editable revision")
            _discovery_id(pair[0], self.producer)
            if self.producer == "why1" and not pair[0].startswith("ISS-"):
                raise ValueError("WHY1 cannot revise existing unknowns or assumptions")
            revision(pair[1])
            selected.append(pair[0])
        for item in self.assigned_ids:
            _discovery_id(item, self.producer)
        if len(set(selected)) != len(selected) or len(set(self.assigned_ids)) != len(self.assigned_ids):
            raise ValueError("duplicate discovery selection")
        if self.producer in {"tracker", "why1"} and self.step == "review":
            if (type(self.routing) is not tuple or len(self.routing) != 4
                    or any(type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not str for pair in self.routing)):
                raise ValueError("Tracker review requires exact immutable routing")
            _tracker_routing(dict(self.routing), self.producer)
        elif self.producer in {"what", "why2"} and self.step == "review":
            from harness.discovery_spec import validate_spec_routing
            if (type(self.routing) is not tuple or len(self.routing) != 2
                    or any(type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not str for pair in self.routing)):
                raise ValueError("specification review requires exact routing")
            validate_spec_routing(dict(self.routing), self.producer)
        elif self.routing is not None:
            raise ValueError("routing can be bound only to a Tracker review")
        result = dict(schema_version=1, operation_id=self.operation_id, dispatch_id=self.dispatch_id,
            spec_id=self.spec_id, run_id=self.run_id, step=self.step, input_fingerprint=self.input_fingerprint,
            artifact_paths=list(self.artifact_paths), editable_revisions=[list(pair) for pair in self.editable_revisions],
            assigned_ids=list(self.assigned_ids))
        if self.producer != "discovery":
            result.update(schema_version=7 if self.producer == "why2" else 6 if self.producer == "what" else 5 if self.producer == "constitution" else 4 if self.producer == "why1" else 3 if self.producer == "tracker" else 2, producer=self.producer)
        if self.routing is not None:
            result["routing"] = deepcopy(dict(self.routing))
        return result


def _proposal(value, assignment):
    if type(value["new_subjects"]) is not list or type(value["revisions"]) is not list:
        raise ValueError("proposal collections must be lists")
    keys, ids = [], []
    allowed = dict(assignment.editable_revisions)
    for item in value["new_subjects"]:
        _object(item, ("key", "kind", "subject", "caption"))
        if type(item["key"]) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", item["key"]):
            raise ValueError("invalid discovery proposal handle")
        if type(item["kind"]) is not str or item["kind"] not in identity_kinds(assignment.producer):
            raise ValueError("invalid discovery proposal kind")
        for field in ("subject", "caption"):
            _plain(item[field])
        if assignment.producer in {"why1", "why2"} and item["kind"] == "ISS" and item["subject"] != item["caption"]:
            raise ValueError("issue subject must equal its immutable report title")
        keys.append(item["key"])
    for item in value["revisions"]:
        _object(item, ("id", "expected_revision"))
        _discovery_id(item["id"], assignment.producer)
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
    for path, content in value["artifacts"].items():
        if path in optional_artifacts(assignment.producer) and content is None:
            continue
        if type(content) is not str or "\x00" in content:
            raise ValueError("discovery artifact must be exact UTF-8 text without NUL")
        content.encode("utf-8")
    if assignment.producer in {"tracker", "why1"}:
        required = "assumption-review.md" if assignment.producer == "why1" else "user-intent.md"
        if not value["artifacts"][required].strip():
            raise ValueError("review/intent output must be nonblank")
        _tracker_routing(value["routing"], assignment.producer)
    if assignment.producer in {"what", "why2"}:
        from harness.discovery_spec import validate_spec_routing
        validate_spec_routing(value["routing"], assignment.producer)


def _tracker_routing(value, producer="tracker"):
    _object(value, ("verdict", "question", "recommended_answer", "risk_level"))
    verdicts = {"PASS", "FAIL", "STOP_AND_ASK", "BLOCKED"} if producer == "why1" else {"ALIGNED", "DRIFT", "STOP_AND_ASK"}
    if type(value["verdict"]) is not str or value["verdict"] not in verdicts:
        raise ValueError("invalid Tracker routing verdict")
    if value["verdict"] != "STOP_AND_ASK":
        if any(value[key] is not None for key in ("question", "recommended_answer", "risk_level")):
            raise ValueError("Tracker clarification metadata requires STOP_AND_ASK")
        return
    _plain(value["question"])
    if value["recommended_answer"] is not None:
        _plain(value["recommended_answer"])
    risk = value["risk_level"]
    if risk is not None and (type(risk) is not str or risk not in {"low", "medium", "high", "critical"}
            or value["recommended_answer"] is None):
        raise ValueError("Tracker risk requires a recommendation and a valid risk level")


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
        _discovery_id(item["id"], assignment.producer)
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
        if assignment.producer in {"tracker", "why1", "what", "why2"} and assignment.step == "author":
            extra.add("routing")
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


def decode_discovery_assignment(value: object) -> DiscoveryAssignment:
    """Recover an exact persisted assignment; this grants no execution authority."""
    try:
        if type(value) is not dict or type(value.get("schema_version")) is not int:
            raise ValueError("invalid saved discovery assignment")
        fields = {"schema_version", "operation_id", "dispatch_id", "spec_id", "run_id", "step",
            "input_fingerprint", "artifact_paths", "editable_revisions", "assigned_ids"}
        if value["schema_version"] in {2, 3, 4, 5, 6, 7}:
            fields.add("producer")
        if value["schema_version"] in {3, 4, 6, 7} and value.get("step") == "review":
            fields.add("routing")
        _object(value, fields)
        if any(type(value[key]) is not list for key in ("artifact_paths", "editable_revisions", "assigned_ids")):
            raise ValueError("invalid saved discovery selection")
        if any(type(pair) is not list or len(pair) != 2 for pair in value["editable_revisions"]):
            raise ValueError("invalid saved editable revision")
        if "routing" in value:
            if value.get("producer") in {"what", "why2"}:
                from harness.discovery_spec import validate_spec_routing
                validate_spec_routing(value["routing"], value["producer"])
            else:
                _tracker_routing(value["routing"], value.get("producer"))
        selected = DiscoveryAssignment(**{key: (
            tuple(tuple(pair) for pair in item) if key == "editable_revisions"
            else tuple(item) if key in {"artifact_paths", "assigned_ids"}
            else tuple(item.items()) if key == "routing" else item)
            for key, item in value.items() if key != "schema_version"})
        if selected.identity() != value:
            raise ValueError("saved discovery assignment encoding changed")
        return selected
    except (TypeError, UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("invalid saved discovery assignment") from exc


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
