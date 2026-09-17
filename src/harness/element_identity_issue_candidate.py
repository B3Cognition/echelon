"""Explicit report occurrence snapshots; no publication or resolution verdicts."""

from dataclasses import asdict, dataclass, replace

from harness.element_artifacts import _validate_input
from harness.element_identity_bindings import IssueOccurrence
from harness.element_identity_candidate import CandidateDiagnostic, _sequence
from harness.element_identity_lifecycle import text


@dataclass(frozen=True, slots=True)
class IssueReportContext:
    path: str
    before_report_id: str | None
    after_report_id: str | None
    before_occurrences: tuple[IssueOccurrence, ...] = ()
    after_occurrences: tuple[IssueOccurrence, ...] = ()


def _normalize(issue_reports):
    """Snapshot exact nested descriptors before entering the authority."""
    normalized = []
    for context in _sequence(issue_reports, "issue_reports"):
        if type(context) is not IssueReportContext:
            raise ValueError("issue report must be an exact IssueReportContext")
        _validate_input(path=context.path, role="references", text="")
        context.path.encode("utf-8")
        for report_id in (context.before_report_id, context.after_report_id):
            if report_id is not None:
                text(report_id, "report_id")
        sequences = []
        for entries in (context.before_occurrences, context.after_occurrences):
            entries = _sequence(entries, "issue occurrences")
            for entry in entries:
                if type(entry) is not IssueOccurrence:
                    raise ValueError("occurrence must be an exact IssueOccurrence")
                entry.__post_init__()
            sequences.append(entries)
        normalized.append(IssueReportContext(context.path, context.before_report_id,
                                             context.after_report_id, *sequences))
    if len({context.path for context in normalized}) != len(normalized):
        raise ValueError("duplicate issue report context path")
    return tuple(normalized)


def _prepare(connection, store, spec_id, images, contexts):
    """Authenticate report mappings and retain full original spans for scope.

    Only completely matched occurrences enter lifecycle presence maps. Binding
    reads authenticate every retained payload and its operation receipt, even
    when the candidate's own report mapping is defective.
    """
    from harness import element_identity_binding_store as binding_store

    diagnostics, mapped_images = [], []
    occurrences = {"before": {}, "after": {}}
    historic_paths = set()
    relevant = {entry.issue_id for context in contexts
                for entry in (*context.before_occurrences, *context.after_occurrences)}
    retained = {label: binding_store.read(connection, store, "issue_occurrences", spec_id, (label,))
                for label in sorted(relevant)}
    by_path = {context.path: context for context in contexts}
    roles = {artifact.path: artifact.role for artifact, _, _ in images}

    def diagnose(code, path, label, detail):
        diagnostics.append(CandidateDiagnostic(code, path, label, detail))

    for context in contexts:
        if roles.get(context.path) != "issues":
            diagnose("issue_report_mismatch", context.path, None,
                     "report context requires a captured issues artifact")

    for artifact, before, after in images:
        if artifact.role != "issues":
            mapped_images.append((artifact, before, after))
            continue
        context = by_path.get(artifact.path)
        if context is None:
            diagnose("issue_report_context_missing", artifact.path, None,
                     "issues artifact requires explicit report context")
            mapped_images.append((artifact, before, after))
            continue
        valid_report = True
        mapped = []
        for image, parsed, source, report_id, entries in (
                ("before", before, artifact.before_text, context.before_report_id, context.before_occurrences),
                ("after", after, artifact.after_text, context.after_report_id, context.after_occurrences)):
            image_matches = ((source is not None and report_id is not None)
                             or (source is None and report_id is None and not entries))
            if not image_matches:
                diagnose("issue_report_mismatch", artifact.path, None,
                         f"{image}: report ID and occurrences disagree with image presence")
                valid_report = False
            display_ids = [entry.display_id for entry in entries]
            issue_ids = [entry.issue_id for entry in entries]
            parsed_ids = [entry.element_id for entry in parsed.declarations]
            unique = (len(set(display_ids)) == len(display_ids)
                      and len(set(issue_ids)) == len(issue_ids)
                      and len(set(parsed_ids)) == len(parsed_ids))
            if not unique or set(display_ids) != set(parsed_ids):
                diagnose("issue_occurrence_mismatch", artifact.path, None,
                         f"{image}: report requires one occurrence per unique display and durable issue ID")
                valid_report = False
            authenticated = set()
            if image == "before":
                for entry in entries:
                    payload = asdict(entry)
                    if any(all(row[key] == value for key, value in payload.items())
                           for row in retained[entry.issue_id]):
                        authenticated.add(entry)
                    else:
                        diagnose("unrecorded_issue_occurrence", artifact.path, entry.issue_id,
                                 "before occurrence lacks exact authenticated retained provenance")
                        valid_report = False
            declarations = []
            for declaration in parsed.declarations:
                matches = [entry for entry in entries if entry.display_id == declaration.element_id]
                entry = matches[0] if len(matches) == 1 else None
                # The adapter owns this complete typed block, including any
                # Resolution Guidance companion and excluding report footers.
                body = declaration.content.partition("\n")[2]
                matches_report = (entry is not None and image_matches and unique
                                  and entry.report_id == report_id
                                  and entry.report_sha256 == parsed.content_sha256
                                  and entry.title == declaration.caption and entry.body == body)
                if not matches_report:
                    diagnose("issue_occurrence_mismatch", artifact.path,
                             entry.issue_id if entry is not None else declaration.element_id,
                             f"{image}: occurrence must match exact report hash, ID, title and typed body")
                    valid_report = False
                else:
                    declaration = replace(declaration, element_id=entry.issue_id)
                    if image == "after" or entry in authenticated:
                        occurrences[image].setdefault(entry.issue_id, []).append((artifact.path, entry))
                declarations.append(declaration)
            mapped.append(replace(parsed, declarations=tuple(declarations)))
        mapped_images.append((artifact, *mapped))
        if (valid_report and artifact.before_text is not None
                and artifact.before_text == artifact.after_text
                and context.before_report_id == context.after_report_id
                and context.before_occurrences == context.after_occurrences):
            historic_paths.add(artifact.path)
    return mapped_images, occurrences, historic_paths, relevant, tuple(diagnostics)


def _after_diagnostics(occurrences, historic_paths, current, projected):
    """Compare body-only issue revisions; exact retained reports stay history."""
    diagnostics = []
    for label, entries in occurrences["after"].items():
        head = projected.get(label, current.get(label))
        for path, entry in entries:
            if entry.display_id != entry.issue_id:
                diagnostics.append(CandidateDiagnostic("issue_display_identity_mismatch", path, label,
                    "managed report label must equal the exact canonical durable issue ID"))
            if path in historic_paths:
                continue
            if (head is None or head["status"] != "active" or head["revision"] != entry.issue_revision
                    or head["subject"] != entry.title or head["content"] != entry.body):
                diagnostics.append(CandidateDiagnostic("issue_revision_mismatch", path, label,
                    "after occurrence requires exact current or projected active issue revision, title and body"))
    for label, head in projected.items():
        if label.startswith("ISS-") and head["status"] == "active" and not any(
                entry.issue_revision == head["revision"] and entry.title == head["subject"]
                and entry.body == head["content"] for _, entry in occurrences["after"].get(label, ())):
            diagnostics.append(CandidateDiagnostic("issue_occurrence_missing", None, label,
                "projected active issue requires a matching after occurrence"))
    return tuple(diagnostics)
