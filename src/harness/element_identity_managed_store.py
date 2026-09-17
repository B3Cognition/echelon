"""Inactive immutable genesis registration on a caller-owned transaction.

Enrollment audits before inserting either row; reads/retries inspect bounded
retained associations, never scan identity child history or current files.
"""

from functools import wraps
import hashlib

from harness import element_identity_store as authority
from harness import element_identity_source_store as sources
from harness.element_identity_json import strict_json
from harness.element_identity_lifecycle import text
from harness.element_identity_managed import (
    encode_managed_identity_request, decode_managed_identity_request,
)
from harness.squad_source_manifest_codec import decode_source_manifest


def bounded(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            raise authority.IdentityStoreError("invalid managed identity authority or request") from None
    return checked


def _require(connection, *identifiers):
    if not connection.in_transaction:
        raise ValueError("managed identity requires an active caller transaction")
    for value in identifiers:
        text(value, "managed identifier")


def _hash(payload):
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _source(connection, store, spec_id, request):
    context = sources._context(connection, spec_id, request.context_id)
    if (context is None or context["registration_operation_id"] != request.source_registration_operation_id
            or context["manifest_sha256"] != request.source_manifest_sha256):
        raise ValueError("original source registration differs from genesis")
    manifest = decode_source_manifest(context["manifest"])
    selected = [tree for tree in strict_json(manifest.payload)["trees"] if tree["path"] == request.spec_path]
    if (len(selected) != 1 or selected[0]["exists"] != "true" or selected[0]["files"]
            or len(selected[0]["directories"]) != 1
            or selected[0]["directories"][0]["path"] != request.spec_path):
        raise ValueError("genesis requires its original empty selected spec tree")
    # The ordinary source reader distinguishes immutable registration from head
    # and checks current source integrity without identity child-history scans.
    return sources.read(connection, store, spec_id, request.context_id)


@bounded
def read(connection, store, spec_id):
    _require(connection, spec_id)
    row = connection.execute("SELECT * FROM managed_identity_specs WHERE spec_id=?", (spec_id,)).fetchone()
    operations = tuple(connection.execute(
        "SELECT operation_id FROM operations WHERE spec_id=? AND method='managed_identity' LIMIT 2", (spec_id,)))
    if row is None:
        if operations:
            raise ValueError("orphan managed identity operation")
        return None
    _require(connection, row["run_id"], row["context_id"], row["operation_id"])
    request = decode_managed_identity_request(row["request"])
    namespace = store._namespace(connection)
    if (request.workspace_uuid != namespace["workspace_uuid"] or request.epoch_uuid != namespace["epoch_uuid"]
            or row["run_id"] != request.run_id or row["context_id"] != request.context_id
            or _hash(row["request"]) != row["request_sha256"]
            or tuple(item[0] for item in operations) != (row["operation_id"],)):
        raise ValueError("managed identity request association is damaged")
    operation = connection.execute("SELECT method,spec_id,digest FROM operations WHERE operation_id=?",
                                   (row["operation_id"],)).fetchone()
    if operation is None or tuple(operation) != ("managed_identity", spec_id, authority._digest(
            ["managed_identity", spec_id, row["operation_id"], row["request"]])):
        raise ValueError("managed identity operation is damaged")
    if connection.execute("SELECT 1 FROM publication_operation_claims WHERE operation_id=?",
                          (row["operation_id"],)).fetchone():
        raise ValueError("managed identity operation is owned by a publication child")
    _source(connection, store, spec_id, request)
    return {"version": "1", **namespace, "spec_id": spec_id, "operation_id": row["operation_id"],
            "run_id": request.run_id, "context_id": request.context_id, "spec_path": request.spec_path,
            "source_registration_operation_id": request.source_registration_operation_id,
            "source_manifest_sha256": request.source_manifest_sha256}


@bounded
def register(connection, store, spec_id, operation_id, request):
    _require(connection, spec_id, operation_id)
    payload = encode_managed_identity_request(request)
    request = decode_managed_identity_request(payload)
    namespace = store._namespace(connection)
    if (request.workspace_uuid, request.epoch_uuid) != (namespace["workspace_uuid"], namespace["epoch_uuid"]):
        raise ValueError("request namespace differs from authority")
    retained = read(connection, store, spec_id)
    digest = authority._digest(["managed_identity", spec_id, operation_id, payload])
    if connection.execute("SELECT 1 FROM operations WHERE operation_id=?", (operation_id,)).fetchone():
        store._operation(connection, operation_id, "managed_identity", spec_id, digest)
        if retained is None or retained["operation_id"] != operation_id:
            raise ValueError("managed identity retry is missing")
        return retained
    if retained is not None:
        raise ValueError("spec already enrolled")
    store._audit(connection, lifecycle_state=True, binding_state=True, publication_state=True,
                 source_state=True, managed_state=True)
    # An empty import (or removed legacy rows) still retains identity history.
    # Only source registration may precede this explicit first enrollment.
    if connection.execute("SELECT 1 FROM operations WHERE spec_id=? AND method!='source_context' LIMIT 1",
                          (spec_id,)).fetchone():
        raise ValueError("genesis cannot enroll prior identity operations")
    for table in ("counters", "reservations", "entities", "revisions", "lifecycle_heads", "lifecycle_lineage",
                  "reference_claims", "issue_occurrences", "publication_intents"):
        if connection.execute(f"SELECT 1 FROM {table} WHERE spec_id=? LIMIT 1", (spec_id,)).fetchone():
            raise ValueError("genesis requires a fresh unallocated spec")
    source = _source(connection, store, spec_id, request)
    if source["sequence"] != "0":
        raise ValueError("first enrollment requires initial source head")
    store._operation(connection, operation_id, "managed_identity", spec_id, digest)
    connection.execute("INSERT INTO managed_identity_specs (spec_id,run_id,context_id,operation_id,request,request_sha256) "
                       "VALUES (?,?,?,?,?,?)", (spec_id, request.run_id, request.context_id, operation_id, payload, _hash(payload)))
    return read(connection, store, spec_id)


@bounded
def audit(connection, store):
    _require(connection)
    for row in connection.execute("SELECT spec_id FROM managed_identity_specs"):
        read(connection, store, row[0])
    if connection.execute("SELECT 1 FROM operations AS o WHERE method='managed_identity' AND NOT EXISTS "
                          "(SELECT 1 FROM managed_identity_specs AS m WHERE m.operation_id=o.operation_id) LIMIT 1").fetchone():
        raise ValueError("orphan managed identity operation")
