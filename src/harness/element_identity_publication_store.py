"""Caller-connection publication journal; no filesystem or completion authority.

The existing lifecycle and binding writers remain the only child writers.
Recovery/completion strings are retained claims authenticated only by their owner.
"""

import hashlib

from harness import element_identity_bindings as bindings
from harness import element_identity_binding_store as binding_store
from harness import element_identity_binding_preview as binding_preview
from harness import element_identity_lifecycle as lifecycle
from harness import element_identity_lifecycle_store as lifecycle_store
from harness.element_identity_json import strict_json
from harness.element_identity_publication import (
    encode_publication_request, decode_publication_request,
    application_metadata,
)
from harness.element_identity_request_codec import decode_request
from harness import element_identity_store as authority


_PENDING = "SELECT operation_id FROM publication_intents WHERE spec_id=? AND state!='released'"
_CLAIM = "SELECT publication_id,method,digest FROM publication_operation_claims WHERE operation_id=?"
_CHILD_TABLES = ("reservations", "revisions", "lifecycle_lineage", "lifecycle_receipts",
                 "reference_claims", "issue_occurrences", "binding_receipts")
_OMITTED = object()


def _hash(payload, encoding="ascii"):
    return hashlib.sha256(payload.encode(encoding)).hexdigest()


def _require(connection, spec_id=_OMITTED, operation_id=_OMITTED):
    if not connection.in_transaction:
        raise authority.IdentityStoreError("publication journal requires an active caller transaction")
    if spec_id is not _OMITTED:
        lifecycle.text(spec_id, "spec_id")
    if operation_id is not _OMITTED:
        lifecycle.text(operation_id, "operation_id")


def _preparation(connection, row):
    return {"version": "1", **authority.IdentityStore._namespace(connection), "spec_id": row["spec_id"],
            "operation_id": row["operation_id"], "request_sha256": row["request_sha256"],
            "plan_sha256": row["plan_sha256"]}


def _children(request, spec_id):
    return operation_children(request.operations, spec_id)


def operation_children(operations, spec_id):
    children = []
    for operation in operations:
        entries = decode_request(operation.method, operation.payload)
        if operation.method == "lifecycle":
            payload = lifecycle.request(entries)[1]
            digest = authority._digest(["lifecycle", spec_id, payload])
        else:
            entry_type = bindings.ReferenceClaim if operation.method == "reference_claims" else bindings.IssueOccurrence
            payload = bindings.request(entries, entry_type)
            digest = authority._digest([operation.method, spec_id, operation.operation_id, payload])
        children.append((operation, entries, payload, digest))
    return children


def planned_effects(connection, store, spec_id, children):
    """Plan lifecycle and validate all bindings using the journal's projected view."""
    batches = {operation.method: entries for operation, entries, _, _ in children}
    changes = batches.get("lifecycle", ())
    planned, links = lifecycle_store.plan_changes(connection, store, spec_id, changes) if changes else ([], [])
    binding_preview.validate_projected(connection, store, spec_id, changes=changes,
                                       claims=batches.get("reference_claims", ()),
                                       occurrences=batches.get("issue_occurrences", ()))
    return {"revisions": planned, "lineage": links}


def _plan(connection, store, spec_id, children):
    return authority._json(planned_effects(connection, store, spec_id, children))


def require_new_children(connection, children):
    """Require globally unused operation IDs, including permanent child claims."""
    for op, _, _, _ in children:
        if (connection.execute("SELECT 1 FROM operations WHERE operation_id=?", (op.operation_id,)).fetchone()
                or connection.execute(_CLAIM, (op.operation_id,)).fetchone()):
            raise ValueError("publication child operation_id already executed or claimed")


def _stored_json(payload):
    try:
        value = strict_json(payload)
        if authority._json(value) != payload:
            raise ValueError("noncanonical retained JSON")
        return value
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("malformed retained publication JSON") from error


def _plan_shape(value, spec_id):
    if type(value) is not dict or set(value) != {"revisions", "lineage"}:
        raise ValueError("invalid publication plan shape")
    if type(value["revisions"]) is not list or type(value["lineage"]) is not list:
        raise ValueError("invalid publication plan arrays")
    labels = set()
    for row in value["revisions"]:
        if type(row) is not list or len(row) != 8:
            raise ValueError("invalid planned revision")
        label, revision, subject, content, status, reason, kind, ordinal = row
        lifecycle.label(label)
        lifecycle.revision(revision)
        lifecycle.text(subject, "planned subject")
        lifecycle.text(content, "planned content")
        if type(status) is not str or status not in {"active", "retired", "superseded"} or label in labels:
            raise ValueError("invalid planned status or duplicate label")
        labels.add(label)
        if status == "active":
            if reason is not None:
                raise ValueError("active plan cannot retain a reason")
        else:
            lifecycle.text(reason, "planned reason")
        if kind is not None or ordinal is not None:
            if (kind, ordinal) != authority._parse_label(label) or ordinal is None or revision != "1":
                raise ValueError("invalid planned creation binding")
    for link in value["lineage"]:
        if type(link) is not list or len(link) != 7 or link[0] != spec_id:
            raise ValueError("invalid planned lineage")
        lifecycle.label(link[1])
        lifecycle.revision(link[2])
        lifecycle.label(link[3])
        lifecycle.revision(link[4])
        lifecycle.text(link[6], "planned lineage reason")
        if type(link[5]) is not str or link[5] not in {"replace", "split", "merge"}:
            raise ValueError("invalid planned lineage kind")


def _absent_rows(connection, operation_id, allowed=()):
    for table in _CHILD_TABLES:
        if table not in allowed and connection.execute(
            f"SELECT 1 FROM {table} WHERE operation_id=? LIMIT 1", (operation_id,),
        ).fetchone():
            raise ValueError("publication operation has unexpected or premature child rows")


def _persisted_plan(connection, store, row, plan, child_id):
    spec_id = row["spec_id"]
    actual = connection.execute("SELECT * FROM revisions WHERE operation_id=?", (child_id,)).fetchall()
    expected = []
    for label, revision, subject, content, status, reason, kind, ordinal in plan["revisions"]:
        expected.append({"spec_id": spec_id, "element_id": label, "revision": revision,
                         "subject": subject, "content": content, "content_sha256": _hash(content, "utf-8"),
                         "status": status, "reason": reason, "operation_id": child_id})
        entity = connection.execute("SELECT kind,ordinal,subject FROM entities WHERE spec_id=? AND element_id=?",
                                    (spec_id, label)).fetchone()
        expected_kind, expected_ordinal = authority._parse_label(label) if kind is None else (kind, ordinal)
        if entity is None or tuple(entity) != (expected_kind, expected_ordinal, subject):
            raise ValueError("published entity differs from retained planned binding")
        store._revision(connection, spec_id, label, revision)
    if sorted((authority._json(dict(item)) for item in actual)) != sorted(authority._json(item) for item in expected):
        raise ValueError("published revisions differ from retained exact plan")
    links = [tuple(link) for link in connection.execute(
        "SELECT spec_id,predecessor_id,predecessor_revision,successor_id,successor_revision,kind,reason "
        "FROM lifecycle_lineage WHERE operation_id=?", (child_id,))]
    if sorted(links) != sorted(tuple(link) for link in plan["lineage"]):
        raise ValueError("published lineage differs from retained exact plan")


def _application(connection, store, row, plan, children, *, source_receipt=None):
    results = []
    for operation, _, _, digest in children:
        saved = connection.execute("SELECT method,spec_id,digest FROM operations WHERE operation_id=?",
                                   (operation.operation_id,)).fetchone()
        if saved is None or tuple(saved) != (operation.method, row["spec_id"], digest):
            raise ValueError("published child operation is missing or damaged")
        if operation.method == "lifecycle":
            _absent_rows(connection, operation.operation_id, ("revisions", "lifecycle_lineage", "lifecycle_receipts"))
            _persisted_plan(connection, store, row, plan, operation.operation_id)
            receipt = store._receipt(connection, operation.operation_id, row["spec_id"])
            # Existing receipt validation authenticates entries; this journal also
            # requires the complete planned entry set and its original order.
            expected = [{"element_id": p[0], "revision": p[1], "status": p[4],
                         "lineage": [link for link in store._lineage(connection, row["spec_id"], p[0])
                                     if link["operation_id"] == operation.operation_id]}
                        for p in plan["revisions"]]
            if list(receipt) != expected:
                raise ValueError("published lifecycle receipt differs from complete plan")
        else:
            _absent_rows(connection, operation.operation_id, (operation.method, "binding_receipts"))
            receipt = binding_store.receipt(connection, store, operation.method, row["spec_id"], operation.operation_id)
        results.append({"method": operation.method, "operation_id": operation.operation_id, "receipt": list(receipt)})
    result = {**application_metadata(decode_publication_request(row["request"])),
              "publication": _preparation(connection, row), "operations": results}
    if source_receipt is not None:
        result["sources"] = source_receipt
    return result


def _check_proposed_history(connection, store, spec_id, request, children, plan):
    if request.proposed_history_sha256 is not None:
        from harness.element_identity_snapshot import capture
        from harness.element_identity_snapshot_preview import _overlay
        proposed = _overlay(capture(connection, store, spec_id), spec_id, children, plan)
        if proposed.sha256 != request.proposed_history_sha256:
            raise ValueError("proposed complete identity history differs from publication claim")


def _load(connection, store, spec_id, operation_id, *, effects=True, source_state=True):
    operation = connection.execute("SELECT method,spec_id,digest FROM operations WHERE operation_id=?",
                                   (operation_id,)).fetchone()
    row = connection.execute("SELECT * FROM publication_intents WHERE operation_id=?", (operation_id,)).fetchone()
    if operation is None and row is None:
        if connection.execute(_CLAIM, (operation_id,)).fetchone():
            raise ValueError("operation_id belongs to a claimed child method")
        if source_state and connection.execute(
            "SELECT 1 FROM source_publications WHERE publication_id=?", (operation_id,),
        ).fetchone():
            raise ValueError("source publication retained without its parent operation")
        return None
    if operation is None or tuple(operation)[:2] != ("identity_publication", spec_id) or row is None or row["spec_id"] != spec_id:
        raise ValueError("publication intent/operation association is missing or conflicting")
    row = dict(row)
    lifecycle.text(spec_id, "spec_id")
    lifecycle.text(operation_id, "operation_id")
    request = decode_publication_request(row["request"])
    if not source_state and request.sources is not None:
        raise ValueError("source-bearing publication is unsupported by this schema")
    if encode_publication_request(request) != row["request"] or _hash(row["request"]) != row["request_sha256"]:
        raise ValueError("publication request digest or encoding is damaged")
    plan = _stored_json(row["plan"])
    _plan_shape(plan, spec_id)
    if _hash(row["plan"]) != row["plan_sha256"] or operation["digest"] != authority._digest(
        ["identity_publication", spec_id, operation_id, row["request"], row["plan_sha256"]],
    ):
        raise ValueError("publication plan or parent digest is damaged")
    children = _children(request, spec_id)
    expected_claims = {(op.operation_id, operation_id, op.method, digest) for op, _, _, digest in children}
    claims = {tuple(item) for item in connection.execute(
        "SELECT operation_id,publication_id,method,digest FROM publication_operation_claims WHERE publication_id=?",
        (operation_id,))}
    if claims != expected_claims or any(op.operation_id == operation_id for op, _, _, _ in children):
        raise ValueError("publication child claims are missing or inconsistent")
    if connection.execute(_CLAIM, (operation_id,)).fetchone():
        raise ValueError("publication parent cannot also be a claimed child")
    if not any(op.method == "lifecycle" for op, _, _, _ in children) and plan != {"revisions": [], "lineage": []}:
        raise ValueError("publication without lifecycle has a nonempty plan")
    _absent_rows(connection, operation_id)
    _preparation(connection, row)
    source_receipt = None
    if source_state:
        from harness import element_identity_source_store as sources
        source_receipt = sources.validate_plan(connection, store, spec_id, operation_id, request)
    state = row["state"]
    if state not in {"prepared", "applied", "released"}:
        raise ValueError("invalid publication state")
    if state == "prepared":
        if any(row[key] is not None for key in ("application_receipt", "application_receipt_sha256", "completion_payload", "completion_payload_sha256")):
            raise ValueError("prepared publication has premature receipts")
        if effects:
            for op, _, _, _ in children:
                if connection.execute("SELECT 1 FROM operations WHERE operation_id=?", (op.operation_id,)).fetchone():
                    raise ValueError("prepared publication has premature child operation")
                _absent_rows(connection, op.operation_id)
            if _plan(connection, store, spec_id, children) != row["plan"]:
                raise ValueError("prepared publication baseline differs from retained plan")
    else:
        _stored_json(row["application_receipt"])
        if _hash(row["application_receipt"]) != row["application_receipt_sha256"]:
            raise ValueError("publication application receipt digest is damaged")
        if effects and authority._json(_application(connection, store, row, plan, children, source_receipt=source_receipt)) != row["application_receipt"]:
            raise ValueError("publication application receipt associations are damaged")
        if state == "applied":
            if row["completion_payload"] is not None or row["completion_payload_sha256"] is not None:
                raise ValueError("applied publication has premature completion")
        else:
            lifecycle.text(row["completion_payload"], "completion_payload")
            if _hash(row["completion_payload"], "utf-8") != row["completion_payload_sha256"]:
                raise ValueError("publication completion digest is damaged")
    return row, request, plan, children


def guard(connection, operation_id, method, spec_id, digest, existing, *, publication_id=None):
    """One indexed common gate, including permanent global child ownership."""
    claim = connection.execute(_CLAIM, (operation_id,)).fetchone()
    if publication_id is not None:
        lifecycle.text(publication_id, "publication owner")
        loaded = _load(connection, authority.IdentityStore, spec_id, publication_id, effects=False)
        if (loaded is None or loaded[0]["state"] != "prepared" or claim is None
                or tuple(claim) != (publication_id, method, digest)):
            raise ValueError("invalid publication child owner or claim")
        pending = connection.execute(_PENDING, (spec_id,)).fetchone()
        if pending is None or pending[0] != publication_id or existing is not None:
            raise ValueError("publication child insert requires its prepared pending owner")
        return
    if claim is not None:
        owner = connection.execute("SELECT spec_id,state FROM publication_intents WHERE operation_id=?",
                                   (claim["publication_id"],)).fetchone()
        if owner is None or owner["spec_id"] != spec_id or tuple(claim)[1:] != (method, digest):
            raise ValueError("operation_id has a conflicting permanent publication claim")
        if owner["state"] == "prepared":
            raise ValueError("pending publication owns this child operation")
        _load(connection, authority.IdentityStore, spec_id, claim["publication_id"])
        if existing is None:
            raise ValueError("published child operation is missing from damaged history")
    if existing is None and connection.execute(_PENDING, (spec_id,)).fetchone():
        raise ValueError("spec has a pending identity publication")


class _ApplicationStore:
    """Per-call owner adapter; validation and persistence stay in existing owners."""

    def __init__(self, store, publication_id):
        self._store = store
        self._publication_id = publication_id

    def __getattr__(self, name):
        return getattr(self._store, name)

    def _operation(self, connection, operation_id, method, spec_id, digest):
        return self._store._operation(connection, operation_id, method, spec_id, digest,
                                      _publication_id=self._publication_id)


@authority._public
def prepare(connection, store, spec_id, operation_id, request):
    _require(connection, spec_id, operation_id)
    request_json = encode_publication_request(request)
    request = decode_publication_request(request_json)
    if any(op.operation_id == operation_id for op in request.operations):
        raise ValueError("parent and child operation IDs must differ")
    loaded = _load(connection, store, spec_id, operation_id)
    if loaded is not None:
        if loaded[0]["request"] != request_json:
            raise ValueError("publication operation_id was already used with different arguments")
        return _preparation(connection, loaded[0])
    children = _children(request, spec_id)
    require_new_children(connection, children)
    if connection.execute(_PENDING, (spec_id,)).fetchone():
        raise ValueError("spec has a pending identity publication")
    plan = _plan(connection, store, spec_id, children)
    _check_proposed_history(connection, store, spec_id, request, children, _stored_json(plan))
    digest = authority._digest(["identity_publication", spec_id, operation_id, request_json, _hash(plan)])
    store._operation(connection, operation_id, "identity_publication", spec_id, digest)
    connection.execute("INSERT INTO publication_intents "
                       "(operation_id,spec_id,request,request_sha256,plan,plan_sha256,state) VALUES (?,?,?,?,?,?,'prepared')",
                       (operation_id, spec_id, request_json, _hash(request_json), plan, _hash(plan)))
    connection.executemany("INSERT INTO publication_operation_claims (operation_id,publication_id,method,digest) VALUES (?,?,?,?)",
                           ((op.operation_id, operation_id, op.method, digest) for op, _, _, digest in children))
    from harness import element_identity_source_store as sources
    sources.prepare(connection, store, spec_id, operation_id, request)
    return _preparation(connection, {"operation_id": operation_id, "spec_id": spec_id,
                                    "request_sha256": _hash(request_json), "plan_sha256": _hash(plan)})


@authority._public
def apply(connection, store, spec_id, operation_id):
    _require(connection, spec_id, operation_id)
    loaded = _load(connection, store, spec_id, operation_id)
    if loaded is None:
        raise ValueError("publication intent does not exist")
    row, request, plan, children = loaded
    if row["state"] != "prepared":
        return _stored_json(row["application_receipt"])
    _check_proposed_history(connection, store, spec_id, request, children, plan)
    adapter = _ApplicationStore(store, operation_id)
    for op, entries, payload, _ in children:
        if op.method == "lifecycle":
            lifecycle_store.apply_changes(connection, adapter, spec_id, op.operation_id, entries)
        else:
            binding_store.record(connection, adapter, op.method, spec_id, op.operation_id, payload)
    from harness import element_identity_source_store as sources
    source_receipt = sources.validate_plan(connection, store, spec_id, operation_id, request)
    receipt = _application(connection, store, row, plan, children, source_receipt=source_receipt)
    encoded = authority._json(receipt)
    sources.accept(connection, store, spec_id, operation_id, request, receipt)
    connection.execute("UPDATE publication_intents SET state='applied',application_receipt=?,application_receipt_sha256=? WHERE operation_id=?",
                       (encoded, _hash(encoded), operation_id))
    if request.proposed_history_sha256 is not None:
        from harness.element_identity_snapshot import capture
        if capture(connection, store, spec_id).sha256 != request.proposed_history_sha256:
            raise ValueError("applied complete identity history differs from publication claim")
    return receipt


@authority._public
def release(connection, store, spec_id, operation_id, completion_payload):
    _require(connection, spec_id, operation_id)
    lifecycle.text(completion_payload, "completion_payload")
    loaded = _load(connection, store, spec_id, operation_id)
    if loaded is None or loaded[0]["state"] == "prepared":
        raise ValueError("release requires an applied publication")
    row = loaded[0]
    if row["state"] == "released":
        if row["completion_payload"] != completion_payload:
            raise ValueError("publication completion payload differs from original release")
    else:
        connection.execute("UPDATE publication_intents SET state='released',completion_payload=?,completion_payload_sha256=? WHERE operation_id=?",
                           (completion_payload, _hash(completion_payload, "utf-8"), operation_id))
    return {"version": "1", "publication": _preparation(connection, row),
            "application_sha256": row["application_receipt_sha256"], "completion_sha256": _hash(completion_payload, "utf-8")}


@authority._public
def read(connection, store, spec_id, operation_id):
    _require(connection, spec_id, operation_id)
    loaded = _load(connection, store, spec_id, operation_id)
    if loaded is None:
        return None
    row = loaded[0]
    return {"preparation": _preparation(connection, row), "state": row["state"], "request": row["request"],
            "application_receipt": row["application_receipt"], "completion_payload": row["completion_payload"]}


@authority._public
def pending(connection, store, spec_id):
    _require(connection, spec_id)
    row = connection.execute(_PENDING, (spec_id,)).fetchone()
    return read(connection, store, spec_id, row[0]) if row else None


@authority._public
def audit(connection, store, *, source_state=True):
    _require(connection)
    authority.IdentityStore._namespace(connection)
    operations = connection.execute("SELECT operation_id FROM publication_intents UNION "
        "SELECT publication_id FROM publication_operation_claims UNION "
        "SELECT operation_id FROM operations WHERE method='identity_publication'")
    for (operation_id,) in operations:
        row = connection.execute("SELECT spec_id FROM publication_intents WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None or _load(connection, store, row[0], operation_id, source_state=source_state) is None:
            raise ValueError("orphan publication parent or child claim")
