"""Translate captured discovery claims into existing candidate/lifecycle objects.

No storage is read or written here. The caller must authenticate the saved
proposal/reservations/baseline and run the existing coherent authority preview.
Neither this translation nor its descriptors authorize publication.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import re

from harness.discovery_semantics import artifact_roles, optional_artifacts, identity_kinds, DiscoveryAssignment, validate_discovery_reply
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
    if any(before.get(path) is not None and value["artifacts"].get(path) is None
            for path in optional_artifacts(assignment.producer)):
        raise ValueError("optional absence cannot remove an existing artifact")
    if assignment.producer == "why1":
        verdicts = re.findall(r"^## Verdict: ([^\n]+)$", value["artifacts"]["assumption-review.md"], re.MULTILINE)
        expected = "PASS" if value["routing"]["verdict"] == "PASS" else "FAIL"
        if verdicts != [expected]:
            raise ValueError("WHY1 report must contain one verdict matching its structured result")
    if assignment.producer == "why1" and before.get("unknowns.md") is not None:
        old = parse_identity_artifact(path="unknowns.md", role="unknowns", text=before["unknowns.md"])
        new = parse_identity_artifact(path="unknowns.md", role="unknowns", text=value["artifacts"]["unknowns.md"])
        definitions = {item.element_id: item.content for item in new.declarations}
        if old.diagnostics or new.diagnostics or any(definitions.get(item.element_id) != item.content for item in old.declarations):
            raise ValueError("WHY1 must preserve existing unknown definitions")
    return tuple(CandidateArtifact(path, artifact_roles(assignment.producer)[path], before[path], value["artifacts"][path])
                 for path in assignment.artifact_paths
                 if before[path] is not None or value["artifacts"][path] is not None)


def _declarations(artifacts, field):
    result = {}
    for artifact in artifacts:
        content = getattr(artifact, field)
        if content is None or artifact.role not in {"unknowns", "assumptions", "intent", "issues"}:
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
    paths = {item.path for item in artifacts}
    omitted = set(assignment.artifact_paths) - paths
    if (len(artifacts) != len(paths) or not paths <= set(assignment.artifact_paths)
            or not omitted <= optional_artifacts(assignment.producer)
            or any(item.role != artifact_roles(assignment.producer)[item.path] for item in artifacts)):
        raise ValueError("discovery artifacts must match assigned paths and roles")
    bindings, ids = {}, set()
    for item in reservations:
        if type(item) is not DiscoveryReservation:
            raise ValueError("invalid discovery reservation descriptor")
        text(item.key, "proposal key")
        text(item.operation_id, "reservation operation")
        pattern = r"(?:" + "|".join(sorted(identity_kinds(assignment.producer))) + r")-[0-9]{6,}"
        if type(item.element_id) is not str or not re.fullmatch(pattern, item.element_id):
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
        content = declaration.content.partition("\n")[2] if declaration.kind == "ISS" else declaration.content
        changes.append(ElementCreate(binding.element_id, proposed["subject"], content, binding.operation_id))
    if not isinstance(existing_subjects, Mapping) or set(existing_subjects) != {item["id"] for item in value["revisions"]}:
        raise ValueError("existing subject claims must match proposed revisions")
    for proposed in value["revisions"]:
        element_id = proposed["id"]
        if element_id not in before or element_id not in after:
            raise ValueError("revised discovery definition is missing")
        old_path, old = before[element_id]
        new_path, new = after[element_id]
        if old_path != new_path or (assignment.producer != "tracker" and old.caption != new.caption):
            raise ValueError("existing discovery subject caption or path changed")
        subject = existing_subjects[element_id]
        text(subject, "existing subject")
        old_content = old.content.partition("\n")[2] if old.kind == "ISS" else old.content
        new_content = new.content.partition("\n")[2] if new.kind == "ISS" else new.content
        if old_content != new_content:
            changes.append(ElementRevision(element_id, proposed["expected_revision"], subject, new_content))
    return tuple(changes)


def issue_report_changes(artifacts, changes, history, *, report_id):
    """Compose native occurrence descriptors from exact captured report images.

    The authority preview still authenticates every retained occurrence and
    validates projected revisions. This is translation, not a second authority.
    """
    from dataclasses import fields
    from harness.element_identity_bindings import IssueOccurrence
    from harness.element_identity_issue_candidate import IssueReportContext
    from kernel.element_ids import decimal_to_int, int_to_decimal
    rows = json.loads(history.payload)
    heads = {row["element_id"]: row for row in rows["entities"]}
    revisions = {label: row["revision"] for label, row in heads.items()}
    for change in changes:
        revisions[change.element_id] = ("1" if type(change) is ElementCreate else
            int_to_decimal(decimal_to_int(change.expected_revision) + 1))
    retained = tuple(IssueOccurrence(**{field.name: row[field.name] for field in fields(IssueOccurrence)})
        for row in rows["issue_occurrences"])
    contexts, proposed = [], []
    for artifact in artifacts:
        if artifact.role != "issues":
            continue
        before_id, before_entries = None, ()
        if artifact.before_text is not None:
            parsed = parse_identity_artifact(path=artifact.path, role="issues", text=artifact.before_text)
            if parsed.diagnostics:
                raise ValueError("invalid captured issue report")
            matches = []
            for identifier in sorted({entry.report_id for entry in retained if entry.report_sha256 == parsed.content_sha256}):
                entries = tuple(dict.fromkeys(entry for entry in retained
                    if entry.report_id == identifier and entry.report_sha256 == parsed.content_sha256))
                expected = []
                for item in parsed.declarations:
                    matching = [entry for entry in entries if entry.issue_id == entry.display_id == item.element_id
                        and entry.title == item.caption and entry.body == item.content.partition("\n")[2]]
                    if len(matching) != 1:
                        break
                    expected.append(matching[0])
                if len(expected) == len(parsed.declarations) and set(entries) == set(expected):
                    matches.append((identifier, tuple(expected)))
            if parsed.declarations and not matches:
                raise ValueError("captured issue report lacks retained provenance")
            # Empty reports have no identity occurrences to authenticate. Their
            # exact source bytes remain guarded by the publication source claim.
            before_id, before_entries = matches[0] if matches else (report_id + "-empty-before", ())
        if artifact.after_text == artifact.before_text:
            contexts.append(IssueReportContext(artifact.path, before_id, before_id, before_entries, before_entries))
            continue
        if artifact.after_text is None:
            raise ValueError("managed issue reports cannot be deleted")
        parsed = parse_identity_artifact(path=artifact.path, role="issues", text=artifact.after_text)
        if parsed.diagnostics:
            raise ValueError("invalid authored issue report")
        entries = tuple(IssueOccurrence(item.element_id, revisions[item.element_id], report_id,
            parsed.content_sha256, item.element_id, item.caption, item.content.partition("\n")[2])
            for item in parsed.declarations)
        contexts.append(IssueReportContext(artifact.path, before_id, report_id, before_entries, entries))
        proposed.extend(entries)
    return tuple(contexts), tuple(proposed)
