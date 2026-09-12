"""Identity checks on one caller-owned read transaction; no writes or verdicts."""

from harness import element_identity_binding_store as binding_store
from harness import element_identity_lifecycle as lifecycle
from harness import element_identity_lifecycle_store as lifecycle_store
from harness import element_identity_store as authority
from harness.element_artifacts import parse_identity_artifact
from harness.element_identity_candidate import (
    CandidateDiagnostic, CandidateReferenceState, DiscoveryCandidateCheck,
    IdentityCandidateCheck, _DISCOVERY_POLICY, _IDENTITY_POLICY,
    _identity_scope_diagnostics, scope_diagnostics,
)


def _head(connection, store, spec_id, label):
    kind, ordinal = authority._parse_label(label)
    store._high_water(connection, spec_id, kind)
    head = store._head(connection, spec_id, label)
    if head is not None:
        lifecycle.text(head["subject"], "stored subject")
        if (head["kind"], head["ordinal"]) != (kind, ordinal):
            raise ValueError("identity label, kind and ordinal binding disagree")
    return head


def check(connection, store, spec_id, artifacts, scope, changes, affected, *,
          policy=_DISCOVERY_POLICY, result_factory=DiscoveryCandidateCheck):
    diagnostics, references, images = [], [], []
    definitions = {"before": {}, "after": {}}
    ordinals = {"before": {}, "after": {}}

    def diagnose(code, path, label, detail):
        diagnostics.append(CandidateDiagnostic(code, path, label, detail))

    def result():
        ordered = sorted(set(diagnostics), key=lambda row: (row.path or "", row.element_id or "", row.code, row.detail))
        return result_factory(tuple(ordered), tuple(references))

    for artifact in sorted(artifacts, key=lambda item: item.path):
        if artifact.role not in policy.supported_roles:
            diagnose("unsupported_role", artifact.path, None,
                     f"unsupported {policy.name} role: {artifact.role}")
            if artifact.before_text != artifact.after_text and artifact.path not in scope.writable_paths:
                diagnose("artifact_out_of_scope", artifact.path, None, "changed artifact is not writable")
            continue
        parsed_images = []
        for image, text in (("before", artifact.before_text), ("after", artifact.after_text)):
            parsed = parse_identity_artifact(path=artifact.path, role=artifact.role, text=text or "")
            parsed_images.append(parsed)
            for diagnostic in parsed.diagnostics:
                diagnose(diagnostic.code, artifact.path, None,
                         f"{image} span:{diagnostic.span.start}:{diagnostic.span.end}: {diagnostic.detail}")
            for entry in parsed.declarations:
                definitions[image].setdefault(entry.element_id, []).append((artifact.path, entry))
                try:
                    kind, ordinal = authority._parse_label(entry.element_id)
                except ValueError as error:
                    diagnose("invalid_definition_identity", artifact.path, entry.element_id, f"{image}: {error}")
                    continue
                if ordinal is not None:
                    ordinals[image].setdefault((kind, ordinal), set()).add(entry.element_id)
        before, after = parsed_images
        scope_checker = _identity_scope_diagnostics if policy.nested_requirement_spans else scope_diagnostics
        diagnostics.extend(scope_checker(artifact, before, after, scope))
        images.append((artifact, before, after))

    for image in ("before", "after"):
        for label, entries in definitions[image].items():
            if len(entries) > 1:
                for path, _ in entries:
                    diagnose("duplicate_definition", path, label, f"{image}: repeated declaration in captured bundle")
        for labels in ordinals[image].values():
            if len(labels) > 1:
                for label in labels:
                    for path, _ in definitions[image][label]:
                        diagnose("numeric_padding_alias", path, label, f"{image}: labels share a numeric ordinal")

    # Validate retained authority before interpreting candidate defects. Missing
    # rows can be candidate mistakes; inconsistent existing rows cannot. These
    # reads stay outside proposal-rejection catches and use the same connection.
    relevant = set(definitions["before"]) | set(definitions["after"]) | set(affected)
    relevant.update(ref.target_id for _, _, parsed in images for ref in parsed.references
                    if ref.range_end_id is None)
    current = {}
    for label in sorted(relevant):
        try:
            authority._parse_label(label)
        except ValueError:
            # Malformed labels in source are diagnosed as candidate defects.
            continue
        current[label] = _head(connection, store, spec_id, label)
    for change in changes:
        creations = change.successors if type(change) is lifecycle.ElementTransition else (
            (change,) if type(change) is lifecycle.ElementCreate else ())
        for creation in creations:
            reservation = connection.execute("SELECT * FROM reservations WHERE operation_id=?",
                                             (creation.reservation_operation_id,)).fetchone()
            if reservation is not None:
                store._validate_reservation(connection, reservation)
    retained_claims = {}
    for artifact, _, parsed in images:
        if any(ref.range_end_id is None for ref in parsed.references):
            retained_claims[artifact.path] = binding_store.read(
                connection, store, "reference_claims", spec_id, (artifact.path, parsed.content_sha256))

    for label, entries in definitions["before"].items():
        for path, entry in entries:
            head = current.get(label)
            if head is None or head["revision"] is None or head["content"] != entry.content:
                diagnose("baseline_identity_mismatch", path, label,
                         "baseline requires exact assessed declaration content")

    # Rendered captions are separate from immutable registry subjects. Preserve
    # before/after captions independently of lifecycle subject validation, even
    # when a proposal is rejected and no projection can be consulted.
    for label, entries in definitions["after"].items():
        before_entries = definitions["before"].get(label, ())
        for path, entry in entries:
            if entry.kind in policy.preserve_caption_kinds and any(
                    entry.caption != old.caption for _, old in before_entries):
                diagnose("subject_changed", path, label,
                         "caption change requires a new identity through an explicit transition")

    proposal_invalid = False
    for label in affected:
        entries = definitions["before"].get(label, ()) or definitions["after"].get(label, ())
        path = entries[0][0] if entries else None
        if label.split("-", 1)[0] not in policy.supported_kinds:
            diagnose("unsupported_lifecycle_kind", path, label,
                     f"{policy.name} lifecycle changes support only "
                     f"{'/'.join(policy.supported_kinds)} identities")
            proposal_invalid = True
        if label not in scope.element_ids:
            diagnose("element_out_of_scope", path, label, "lifecycle identity is outside element scope")
            proposal_invalid = True
        if not entries:
            diagnose("lifecycle_without_artifact", None, label, "lifecycle identity lacks a captured declaration")
            proposal_invalid = True
    projected = {}
    if changes and not proposal_invalid:
        try:
            planned, _ = lifecycle_store.plan_changes(connection, store, spec_id, changes)
            projected = {label: {"revision": revision, "subject": subject, "content": content, "status": status}
                         for label, revision, subject, content, status, _, _, _ in planned}
        except ValueError as error:
            diagnose("lifecycle_rejected", None, None, str(error))
            proposal_invalid = True
    if proposal_invalid:
        return result()

    created = set()
    for change in changes:
        if type(change) is lifecycle.ElementCreate:
            created.add(change.element_id)
        elif type(change) is lifecycle.ElementTransition:
            created.update(successor.element_id for successor in change.successors)

    for label, entries in definitions["after"].items():
        for path, entry in entries:
            old_head = current.get(label)
            head = projected.get(label, old_head)
            if label not in definitions["before"] and label not in created:
                diagnose("unallocated_definition", path, label, "new declaration requires exact reserved creation or transition successor")
            if head is None:
                diagnose("unallocated_definition", path, label, "declaration has no materialized or projected identity")
                continue
            if entry.content != head["content"]:
                code = "terminal_content_changed" if head["status"] in {"retired", "superseded"} else "definition_content_mismatch"
                diagnose(code, path, label, "declaration differs from exact current or projected content")
            # A proposed revision cannot legitimize a drifted preimage; the
            # independent baseline checks above remain blocking diagnostics.

    for label, entries in definitions["before"].items():
        if label in definitions["after"]:
            continue
        head = projected.get(label, current.get(label))
        if head is not None and head["status"] == "active":
            for path, _ in entries:
                diagnose("definition_removed", path, label, "active declaration removed without retirement or transition")
    for label, head in projected.items():
        if head["status"] == "active" and label not in definitions["after"]:
            diagnose("definition_removed", None, label, "projected active identity requires an after declaration")

    for artifact, _, after in images:
        claims = retained_claims.get(artifact.path, ())
        for ref in sorted(after.references, key=lambda entry: (entry.span.start, entry.span.end)):
            if ref.range_end_id is not None:
                diagnose("unsupported_reference_range", artifact.path, ref.target_id,
                         f"after span:{ref.span.start}:{ref.span.end}: interval references are unsupported")
                continue
            head = projected.get(ref.target_id, current.get(ref.target_id))
            if head is None:
                diagnose("reference_identity_mismatch", artifact.path, ref.target_id,
                         "reference target must exist by exact label in the same spec")
                continue
            if ref.relation in {"requires", "depends"} and head["status"] != "active":
                diagnose("inactive_dependency", artifact.path, ref.target_id,
                         "required dependency is not active")
            revisions = tuple(claim["target_revision"] for claim in claims if (
                claim["source_anchor"] == f"span:{ref.span.start}:{ref.span.end}"
                and claim["target_id"] == ref.target_id and claim["relation"] == ref.relation
            ))
            assessed = tuple(revision for revision in revisions if revision is not None)
            state = "unassessed" if not assessed else (
                "current" if head["status"] == "active" and head["revision"] in assessed else "historical")
            references.append(CandidateReferenceState(artifact.path, after.content_sha256,
                ref.span.start, ref.span.end, ref.target_id, ref.relation, revisions, state))
    return result()


def check_identity(connection, store, spec_id, artifacts, scope, changes, affected):
    return check(connection, store, spec_id, artifacts, scope, changes, affected,
                 policy=_IDENTITY_POLICY, result_factory=IdentityCandidateCheck)
