"""Read-only binding validation against one caller-owned lifecycle projection."""

from collections.abc import Sequence

from harness import element_identity_binding_store as binding_store
from harness import element_identity_bindings as bindings
from harness import element_identity_lifecycle as lifecycle
from harness import element_identity_lifecycle_store as lifecycle_store


def _request(batch, request):
    if not isinstance(batch, Sequence) or isinstance(batch, (str, bytes)):
        raise ValueError("projected binding batches must be sequences excluding strings and bytes")
    batch = tuple(batch)
    if batch:
        request(batch)
    return batch


class _ProjectedView:
    def __init__(self, connection, store, spec_id, planned):
        self._connection = connection
        self._store = store
        self._spec_id = spec_id
        self._heads = {}
        self._revisions = {}
        for label, revision, subject, content, status, reason, kind, ordinal in planned:
            if kind is None:
                head = store._head(connection, spec_id, label)
                if head is None:
                    raise ValueError("projected lifecycle entity must already exist")
                kind, ordinal = head["kind"], head["ordinal"]
            self._heads[label] = {
                "element_id": label,
                "kind": kind,
                "ordinal": ordinal,
                "subject": subject,
                "content": content,
                "status": status,
                "revision": revision,
            }
            self._revisions[(label, revision)] = {
                "element_id": label,
                "revision": revision,
                "subject": subject,
                "content": content,
                "status": status,
                "reason": reason,
            }

    def head(self, label):
        return self._heads.get(label) or self._store._head(
            self._connection, self._spec_id, label,
        )

    def revision(self, label, revision):
        return self._revisions.get((label, revision)) or self._store._revision(
            self._connection, self._spec_id, label, revision,
        )


def _requests(changes, claims, occurrences):
    changes = _request(changes, lambda batch: lifecycle.request(batch)[0])
    claims = _request(claims, lambda batch: bindings.request(batch, bindings.ReferenceClaim))
    occurrences = _request(
        occurrences, lambda batch: bindings.request(batch, bindings.IssueOccurrence),
    )
    return changes, claims, occurrences


def validate_projected(connection, store, spec_id, *, changes=(), claims=(), occurrences=()) -> None:
    """Validate on the caller's transaction without owning it or writing."""
    lifecycle.text(spec_id, "spec_id")
    changes, claims, occurrences = _requests(changes, claims, occurrences)
    if not connection.in_transaction:
        from harness.element_identity_store import IdentityStoreError

        raise IdentityStoreError("projected binding validation requires an active transaction")
    planned = lifecycle_store.plan_changes(connection, store, spec_id, changes)[0] if changes else ()
    view = _ProjectedView(connection, store, spec_id, planned)
    claim_payloads = bindings.request(claims, bindings.ReferenceClaim) if claims else ()
    occurrence_payloads = bindings.request(occurrences, bindings.IssueOccurrence) if occurrences else ()
    for payload in claim_payloads:
        binding_store._target(connection, store, spec_id, payload, "reference_claims", view)
    for payload in occurrence_payloads:
        binding_store._target(connection, store, spec_id, payload, "issue_occurrences", view)
