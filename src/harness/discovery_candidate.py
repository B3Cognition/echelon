"""Translate captured discovery claims into existing candidate/lifecycle objects.

No storage is read or written here. The caller must authenticate the saved
proposal/reservations/baseline and run the existing coherent authority preview.
Neither this translation nor its descriptors authorize publication.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re

from harness.discovery_semantics import artifact_roles, DiscoveryAssignment, validate_discovery_reply
from harness.element_artifacts import parse_identity_artifact
from harness.element_identity_candidate import CandidateArtifact
from harness.element_identity_lifecycle import ElementCreate, ElementRevision, text


@dataclass(frozen=True)
class DiscoveryReservation:
    key: str
    element_id: str
    operation_id: str


def _final(assignment, reply, step):
    if type(assignment) is not DiscoveryAssignment or assignment.step != step:
        raise ValueError("wrong discovery assignment step")
    value = validate_discovery_reply(reply, assignment)
    if value["action"] != "final":
        raise ValueError("only a final discovery reply can be materialized")
    return value


def author_artifacts(assignment, reply, *, before: Mapping[str, str | None]) -> tuple[CandidateArtifact, ...]:
    value = _final(assignment, reply, "author")
    if not isinstance(before, Mapping) or set(before) != set(assignment.artifact_paths):
        raise ValueError("captured discovery baseline must match assigned paths")
    for content in before.values():
        if content is not None:
            if type(content) is not str or "\x00" in content:
                raise ValueError("invalid captured discovery text")
            content.encode("utf-8")
    return tuple(CandidateArtifact(path, artifact_roles(assignment.producer)[path], before[path], value["artifacts"][path])
                 for path in assignment.artifact_paths)


def _declarations(artifacts, field):
    result = {}
    for artifact in artifacts:
        content = getattr(artifact, field)
        if content is None or artifact.role not in {"unknowns", "assumptions"}:
            continue
        parsed = parse_identity_artifact(path=artifact.path, role=artifact.role, text=content)
        if parsed.diagnostics:
            raise ValueError("discovery definition grammar is invalid")
        for declaration in parsed.declarations:
            if declaration.element_id in result:
                raise ValueError("duplicate discovery definition")
            result[declaration.element_id] = (artifact.path, declaration)
    return result


def build_discovery_changes(assignment, reply, *, reservations, artifacts, existing_subjects):
    value = _final(assignment, reply, "propose")
    if type(reservations) is not tuple or type(artifacts) is not tuple:
        raise ValueError("captured discovery collections must be tuples")
    if any(type(item) is not CandidateArtifact for item in artifacts):
        raise ValueError("invalid discovery artifact descriptor")
    if (len(artifacts) != len(assignment.artifact_paths)
            or {item.path for item in artifacts} != set(assignment.artifact_paths)
            or any(item.role != artifact_roles(assignment.producer)[item.path] for item in artifacts)):
        raise ValueError("discovery artifacts must match assigned paths and roles")
    bindings, ids = {}, set()
    for item in reservations:
        if type(item) is not DiscoveryReservation:
            raise ValueError("invalid discovery reservation descriptor")
        text(item.key, "proposal key")
        text(item.operation_id, "reservation operation")
        if type(item.element_id) is not str or not re.fullmatch(r"[UA]-[0-9]{6,}", item.element_id):
            raise ValueError("new discovery IDs require numeric six-digit-minimum labels")
        if not item.element_id.split("-", 1)[1].strip("0"):
            raise ValueError("discovery ordinals must be positive")
        if item.key in bindings or item.element_id in ids:
            raise ValueError("duplicate discovery reservation")
        bindings[item.key] = item
        ids.add(item.element_id)
    if set(bindings) != {item["key"] for item in value["new_subjects"]}:
        raise ValueError("reservations must match the exact proposed keys")
    before = _declarations(artifacts, "before_text")
    after = _declarations(artifacts, "after_text")
    if set(after) - set(before) != ids or ids & set(before):
        raise ValueError("introduced discovery definitions differ from reservations")
    changes = []
    for proposed in value["new_subjects"]:
        binding = bindings[proposed["key"]]
        _, declaration = after[binding.element_id]
        if declaration.kind != proposed["kind"] or declaration.caption != proposed["caption"]:
            raise ValueError("reserved subject kind or caption changed")
        changes.append(ElementCreate(binding.element_id, proposed["subject"], declaration.content, binding.operation_id))
    if not isinstance(existing_subjects, Mapping) or set(existing_subjects) != {item["id"] for item in value["revisions"]}:
        raise ValueError("existing subject claims must match proposed revisions")
    for proposed in value["revisions"]:
        element_id = proposed["id"]
        if element_id not in before or element_id not in after:
            raise ValueError("revised discovery definition is missing")
        old_path, old = before[element_id]
        new_path, new = after[element_id]
        if old_path != new_path or old.caption != new.caption:
            raise ValueError("existing discovery subject caption or path changed")
        subject = existing_subjects[element_id]
        text(subject, "existing subject")
        if old.content != new.content:
            changes.append(ElementRevision(element_id, proposed["expected_revision"], subject, new.content))
    return tuple(changes)
