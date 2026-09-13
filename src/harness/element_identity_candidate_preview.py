"""Inactive structural candidate and exact journal preview on one read snapshot."""

from dataclasses import dataclass, replace
import json

from harness import element_identity_candidate as candidate
from harness import element_identity_candidate_store as candidate_store
from harness import element_identity_publication_store as publication_store
from harness import element_identity_snapshot as snapshot
from harness import element_identity_snapshot_preview as snapshot_preview
from harness.element_identity_bindings import IssueOccurrence
from harness.element_identity_issue_candidate import IssueReportContext
from harness.element_identity_publication import validated_operations
from harness.element_identity_reference_sources import validate_reference_claim_sources


@dataclass(frozen=True, slots=True)
class IdentityCandidatePreview:
    check: candidate.IdentityCandidateCheck
    history: snapshot.IdentityHistorySnapshot | None


def normalize(spec_id, artifacts, scope, operations, projection_sources,
              evidence_inventories, issue_reports):
    """Select detached native request records before acquiring authority."""
    operations = validated_operations(operations)
    children = publication_store.operation_children(operations, spec_id)
    batches = {operation.method: entries for operation, entries, _, _ in children}
    (artifacts, scope, changes, affected, projection_sources,
     evidence_inventories, issue_reports) = candidate.identity_request(
        spec_id, artifacts, scope, batches.get("lifecycle", ()), projection_sources,
        evidence_inventories, issue_reports)
    artifacts = tuple(replace(artifact) for artifact in artifacts)
    issue_reports = tuple(IssueReportContext(
        context.path, context.before_report_id, context.after_report_id,
        tuple(replace(entry) for entry in context.before_occurrences),
        tuple(replace(entry) for entry in context.after_occurrences),
    ) for context in issue_reports)
    return (children, batches, artifacts, scope, changes, affected,
            projection_sources, evidence_inventories, issue_reports)


def _issue_associations(retained, proposed, contexts):
    # Only the native occurrence payload establishes identity; retained receipt
    # metadata and fingerprints do not stand in for any of these fields.
    retained_occurrences = {IssueOccurrence(
        row["issue_id"], row["issue_revision"], row["report_id"], row["report_sha256"],
        row["display_id"], row["title"], row["body"],
    ) for row in json.loads(retained.payload)["issue_occurrences"]}
    after = {entry for context in contexts for entry in context.after_occurrences}
    proposed = set(proposed)
    diagnostics = [candidate.CandidateDiagnostic(
        "issue_operation_unbound", None, entry.issue_id,
        "proposed occurrence requires an exact captured after report occurrence",
    ) for entry in proposed - after]
    diagnostics.extend(candidate.CandidateDiagnostic(
        "issue_operation_missing", context.path, entry.issue_id,
        "after occurrence requires an exact proposed operation or retained provenance",
    ) for context in contexts for entry in context.after_occurrences
      if entry not in proposed and entry not in retained_occurrences)
    return diagnostics


def preview(connection, store, spec_id, request):
    """Compose existing owners using the caller's single query-only transaction."""
    (children, batches, artifacts, scope, changes, affected,
     projection_sources, evidence_inventories, issue_reports) = request
    publication_store._require(connection, spec_id)
    if connection.execute(publication_store._PENDING, (spec_id,)).fetchone():
        raise ValueError("spec has a pending identity publication")
    publication_store.require_new_children(connection, children)
    retained = snapshot.capture(connection, store, spec_id)
    observed = candidate_store.check_identity(
        connection, store, spec_id, artifacts, scope, changes, affected,
        projection_sources, evidence_inventories, issue_reports)
    diagnostics = (*observed.diagnostics,
        *validate_reference_claim_sources(artifacts, batches.get("reference_claims", ())),
        *_issue_associations(retained, batches.get("issue_occurrences", ()), issue_reports))
    check = candidate.IdentityCandidateCheck(
        tuple(sorted({replace(entry) for entry in diagnostics},
                     key=lambda row: (row.path or "", row.element_id or "", row.code, row.detail))),
        tuple(replace(entry) for entry in observed.references),
    )
    if check.diagnostics:
        return IdentityCandidatePreview(check, None)
    plan = publication_store.planned_effects(connection, store, spec_id, children)
    return IdentityCandidatePreview(check, snapshot_preview._overlay(retained, spec_id, children, plan))
