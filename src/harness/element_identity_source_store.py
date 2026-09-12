"""Accepted observation scopes on a caller-owned identity transaction.

These are caller-declared selections, not authenticated managed-run bindings.
No helper owns transactions, filesystem access, locks, or identity child writes.
"""

from functools import wraps
import hashlib

from harness import element_identity_store as authority
from harness.element_identity_lifecycle import text
from harness.element_identity_json import strict_json
from harness.element_identity_publication import encode_publication_request, decode_publication_request, _source_baseline, application_metadata
from harness.squad_publication import PublicationError
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_manifest_codec import decode_source_manifest, validate_source_manifest
from harness.squad_source_projection import project_publication_source_manifest


_HEAD = ("SELECT * FROM source_publications WHERE spec_id=? AND context_id=? "
         "AND application_sha256 IS NOT NULL ORDER BY length(sequence) DESC,sequence DESC LIMIT 1")


def _public(function):
    @wraps(function)
    @authority._public
    def bounded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (PublicationError, AttributeError, KeyError, RecursionError, UnicodeError):
            raise authority.IdentityStoreError("invalid retained source authority") from None
    return bounded


def _hash(payload):
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _require(connection, *identifiers):
    if not connection.in_transaction:
        raise authority.IdentityStoreError("source contexts require an active caller transaction")
    for value in identifiers:
        text(value, "source identifier")


def _manifest(row):
    manifest = decode_source_manifest(row["manifest"])
    if manifest.sha256 != row["manifest_sha256"]:
        raise ValueError("source manifest digest is damaged")
    return {"payload": manifest.payload, "sha256": manifest.sha256}


def _receipt(connection, context, row=None):
    return {"version": "1", **authority.IdentityStore._namespace(connection),
            "spec_id": context["spec_id"], "context_id": context["context_id"],
            "registration_operation_id": context["registration_operation_id"],
            "operation_id": context["registration_operation_id"] if row is None else row["publication_id"],
            "sequence": "0" if row is None else row["sequence"],
            "manifest": _manifest(context if row is None else row)}


def _context(connection, spec_id, context_id):
    row = connection.execute("SELECT * FROM source_contexts WHERE spec_id=? AND context_id=?",
                             (spec_id, context_id)).fetchone()
    if row is None:
        if (connection.execute("SELECT 1 FROM source_publications WHERE spec_id=? AND context_id=? LIMIT 1",
                               (spec_id, context_id)).fetchone()
                or connection.execute("SELECT 1 FROM operations AS o WHERE o.spec_id=? AND o.method='source_context' "
                    "AND NOT EXISTS (SELECT 1 FROM source_contexts AS c WHERE c.registration_operation_id=o.operation_id) LIMIT 1",
                    (spec_id,)).fetchone()):
            raise ValueError("missing source context has retained orphan authority")
        return None
    _require(connection, row["spec_id"], row["context_id"], row["registration_operation_id"])
    _manifest(row)
    operation = connection.execute("SELECT method,spec_id,digest FROM operations WHERE operation_id=?",
                                   (row["registration_operation_id"],)).fetchone()
    if operation is None or tuple(operation) != ("source_context", spec_id, authority._digest(
            ["source_context", spec_id, context_id, row["manifest"]])):
        raise ValueError("source registration association is damaged")
    if connection.execute("SELECT 1 FROM publication_operation_claims WHERE operation_id=?",
                          (row["registration_operation_id"],)).fetchone():
        raise ValueError("source registration is owned by a publication child")
    return row


@_public
def register(connection, store, spec_id, context_id, operation_id, manifest):
    _require(connection, spec_id, context_id, operation_id)
    manifest = validate_source_manifest(manifest)
    context = _context(connection, spec_id, context_id)
    digest = authority._digest(["source_context", spec_id, context_id, manifest.payload])
    retry = store._operation(connection, operation_id, "source_context", spec_id, digest)
    if retry:
        if context is None or context["registration_operation_id"] != operation_id or context["manifest"] != manifest.payload:
            raise ValueError("source registration record is missing or damaged")
        read(connection, store, spec_id, context_id)
        return _receipt(connection, context)
    if context is not None:
        raise ValueError("source context is already registered")
    connection.execute("INSERT INTO source_contexts (spec_id,context_id,registration_operation_id,manifest,manifest_sha256) "
                       "VALUES (?,?,?,?,?)", (spec_id, context_id, operation_id, manifest.payload, manifest.sha256))
    return _receipt(connection, _context(connection, spec_id, context_id))


@_public
def read(connection, store, spec_id, context_id):
    _require(connection, spec_id, context_id)
    context = _context(connection, spec_id, context_id)
    if context is None:
        return None
    highest = _head_pointer(connection, context)
    if highest is not None:
        _, request = _parent(connection, highest["publication_id"])
        return validate_plan(connection, store, spec_id, highest["publication_id"], request)
    return _receipt(connection, context, highest)


def _head_pointer(connection, context):
    highest = connection.execute(_HEAD, (context["spec_id"], context["context_id"])).fetchone()
    if context["head_publication_id"] != (None if highest is None else highest["publication_id"]):
        raise ValueError("source head pointer and highest accepted publication disagree")
    return highest


def _selection(manifest):
    value = strict_json(manifest.payload)
    return tuple(item["path"] for item in value["trees"]), tuple(item["path"] for item in value["files"])


def _derived(request):
    baseline = _source_baseline(request.sources)
    before = snapshot_source_manifest(trees=baseline.trees, files=baseline.files)
    after = project_publication_source_manifest(baseline)
    return before, after


def _parent(connection, publication_id):
    """Indexed ownership and structural receipt checks, without child-history scans.

    Full child effects remain the journal read/retry/audit owner's responsibility.
    Reuse its pure plan/request/preparation validators, not its history loader.
    """
    from harness import element_identity_publication_store as publications

    parent = connection.execute("SELECT * FROM publication_intents WHERE operation_id=?", (publication_id,)).fetchone()
    if parent is None:
        raise ValueError("source publication parent is missing")
    request = decode_publication_request(parent["request"])
    if encode_publication_request(request) != parent["request"] or _hash(parent["request"]) != parent["request_sha256"]:
        raise ValueError("source parent request is damaged")
    operation = connection.execute("SELECT method,spec_id,digest FROM operations WHERE operation_id=?", (publication_id,)).fetchone()
    if (operation is None or _hash(parent["plan"]) != parent["plan_sha256"] or tuple(operation) != (
            "identity_publication", parent["spec_id"], authority._digest([
                "identity_publication", parent["spec_id"], publication_id, parent["request"], parent["plan_sha256"]]))):
        raise ValueError("source parent operation is damaged")
    plan = publications._stored_json(parent["plan"])
    publications._plan_shape(plan, parent["spec_id"])
    children = publications._children(request, parent["spec_id"])
    expected_claims = {(op.operation_id, publication_id, op.method, digest) for op, _, _, digest in children}
    claims = {tuple(row) for row in connection.execute(
        "SELECT operation_id,publication_id,method,digest FROM publication_operation_claims WHERE publication_id=?",
        (publication_id,))}
    if (claims != expected_claims or any(op.operation_id == publication_id for op, _, _, _ in children)
            or connection.execute(publications._CLAIM, (publication_id,)).fetchone()):
        raise ValueError("source parent ownership claims are damaged")
    if not any(op.method == "lifecycle" for op, _, _, _ in children) and plan != {"revisions": [], "lineage": []}:
        raise ValueError("source parent has an unexpected lifecycle plan")
    preparation = publications._preparation(connection, parent)
    if parent["state"] == "prepared":
        if any(parent[key] is not None for key in ("application_receipt", "application_receipt_sha256", "completion_payload", "completion_payload_sha256")):
            raise ValueError("source parent has premature receipts")
    elif parent["state"] in {"applied", "released"}:
        application = publications._stored_json(parent["application_receipt"])
        metadata = application_metadata(request)
        keys = {"publication", "operations"} | set(metadata) | ({"sources"} if request.sources is not None else set())
        if (type(application) is not dict or set(application) != keys
                or any(application[key] != value for key, value in metadata.items())
                or application["publication"] != preparation or type(application["operations"]) is not list
                or len(application["operations"]) != len(request.operations)
                or _hash(parent["application_receipt"]) != parent["application_receipt_sha256"]):
            raise ValueError("source parent application envelope is damaged")
        for result, op in zip(application["operations"], request.operations):
            if (type(result) is not dict or set(result) != {"method", "operation_id", "receipt"}
                    or result["method"] != op.method or result["operation_id"] != op.operation_id
                    or type(result["receipt"]) is not list or any(type(item) is not dict for item in result["receipt"])):
                raise ValueError("source parent child receipt envelope is damaged")
        if parent["state"] == "applied":
            if parent["completion_payload"] is not None or parent["completion_payload_sha256"] is not None:
                raise ValueError("source parent has premature completion")
        else:
            text(parent["completion_payload"], "completion_payload")
            if hashlib.sha256(parent["completion_payload"].encode("utf-8")).hexdigest() != parent["completion_payload_sha256"]:
                raise ValueError("source parent completion digest is damaged")
    else:
        raise ValueError("source parent state is invalid")
    return parent, request


def _request_parent(connection, spec_id, publication_id, request):
    parent, retained = _parent(connection, publication_id)
    if parent["spec_id"] != spec_id or encode_publication_request(request) != encode_publication_request(retained):
        raise ValueError("source helper request differs from its retained parent")
    return parent


def _bound_row(connection, context, publication_id):
    """Authenticate one row against its parent, without replaying ancestors."""
    row = connection.execute("SELECT * FROM source_publications WHERE publication_id=?", (publication_id,)).fetchone()
    if row is None or (row["spec_id"], row["context_id"]) != (context["spec_id"], context["context_id"]):
        raise ValueError("source plan is missing or has a conflicting context")
    text(publication_id, "publication_id")
    text(row["predecessor_operation_id"], "predecessor_operation_id")
    if authority._integer(row["sequence"]) <= 0:
        raise ValueError("source sequence must be positive")
    parent, request = _parent(connection, publication_id)
    if (request.sources is None or parent["spec_id"] != context["spec_id"]
            or request.sources.context_id != context["context_id"]
            or request.sources.expected_operation_id != row["predecessor_operation_id"]):
        raise ValueError("source plan disagrees with parent source claim")
    before, after = _derived(request)
    selected = _selection(decode_source_manifest(context["manifest"]))
    if _selection(before) != selected or _selection(after) != selected or _manifest(row) != {"payload": after.payload, "sha256": after.sha256}:
        raise ValueError("source plan manifest or registered selection is damaged")
    if parent["state"] == "prepared":
        if row["application_sha256"] is not None:
            raise ValueError("source plan was prematurely accepted")
    elif parent["state"] in {"applied", "released"}:
        application = strict_json(parent["application_receipt"])
        if (application["sources"] != _receipt(connection, context, row)
                or authority._json(application) != parent["application_receipt"]
                or _hash(parent["application_receipt"]) != parent["application_receipt_sha256"]
                or row["application_sha256"] != parent["application_receipt_sha256"]):
            raise ValueError("source acceptance and parent application disagree")
    else:
        raise ValueError("source parent state is invalid")
    return row, before


@_public
def validate_plan(connection, store, spec_id, publication_id, request):
    _require(connection, spec_id, publication_id)
    request = decode_publication_request(encode_publication_request(request))
    _request_parent(connection, spec_id, publication_id, request)
    if request.sources is None:
        if connection.execute("SELECT 1 FROM source_publications WHERE publication_id=?", (publication_id,)).fetchone():
            raise ValueError("source-less parent has an unexpected source plan")
        return None
    context = _context(connection, spec_id, request.sources.context_id)
    if context is None:
        raise ValueError("source context is missing")
    _head_pointer(connection, context)
    row, before = _bound_row(connection, context, publication_id)
    predecessor_id = request.sources.expected_operation_id
    if predecessor_id == context["registration_operation_id"]:
        predecessor = _receipt(connection, context)
    else:
        previous, _ = _bound_row(connection, context, predecessor_id)
        if previous["application_sha256"] is None:
            raise ValueError("source predecessor is not accepted")
        predecessor = _receipt(connection, context, previous)
    if (row["sequence"] != authority._decimal(authority._integer(predecessor["sequence"]) + 1)
            or predecessor["manifest"] != {"payload": before.payload, "sha256": before.sha256}):
        raise ValueError("source predecessor sequence or baseline is damaged")
    return _receipt(connection, context, row)


@_public
def prepare(connection, store, spec_id, publication_id, request):
    _require(connection, spec_id, publication_id)
    request = decode_publication_request(encode_publication_request(request))
    if _request_parent(connection, spec_id, publication_id, request)["state"] != "prepared":
        raise ValueError("source preparation requires its prepared parent")
    if request.sources is None:
        return
    head = read(connection, store, spec_id, request.sources.context_id)
    before, after = _derived(request)
    if (head is None or head["operation_id"] != request.sources.expected_operation_id
            or head["manifest"] != {"payload": before.payload, "sha256": before.sha256}):
        raise ValueError("source predecessor or baseline differs from the accepted head")
    if _selection(before) != _selection(after):
        raise ValueError("source publication changes its registered selection")
    sequence = authority._decimal(authority._integer(head["sequence"]) + 1)
    connection.execute("INSERT INTO source_publications (publication_id,spec_id,context_id,sequence,predecessor_operation_id,manifest,manifest_sha256) "
                       "VALUES (?,?,?,?,?,?,?)", (publication_id, spec_id, request.sources.context_id, sequence,
                        request.sources.expected_operation_id, after.payload, after.sha256))


@_public
def accept(connection, store, spec_id, publication_id, request, application):
    _require(connection, spec_id, publication_id)
    request = decode_publication_request(encode_publication_request(request))
    _request_parent(connection, spec_id, publication_id, request)
    if request.sources is None:
        return
    receipt = validate_plan(connection, store, spec_id, publication_id, request)
    from harness import element_identity_publication_store as publications
    # Reuse the journal's read-only receipt validation; it remains the sole
    # child writer and the sole parent application-receipt persistence owner.
    row, _, plan, children = publications._load(connection, store, spec_id, publication_id, effects=False)
    if row["state"] != "prepared":
        raise ValueError("source acceptance requires its prepared parent")
    expected = publications._application(connection, store, row, plan, children, source_receipt=receipt)
    if type(application) is not dict or authority._json(application) != authority._json(expected):
        raise ValueError("source application receipt differs from plan")
    head = read(connection, store, spec_id, request.sources.context_id)
    if head["operation_id"] != request.sources.expected_operation_id:
        raise ValueError("source predecessor is stale")
    predecessor_pointer = None if head["sequence"] == "0" else head["operation_id"]
    changed = connection.execute("UPDATE source_contexts SET head_publication_id=? WHERE spec_id=? AND context_id=? "
                                 "AND head_publication_id IS ?", (publication_id, spec_id, request.sources.context_id,
                                                               predecessor_pointer)).rowcount
    if changed != 1:
        raise ValueError("source head compare-and-swap failed")
    if connection.execute("UPDATE source_publications SET application_sha256=? WHERE publication_id=? AND application_sha256 IS NULL",
                          (_hash(authority._json(application)), publication_id)).rowcount != 1:
        raise ValueError("source acceptance requires an unaccepted source plan")


@_public
def audit(connection, store):
    _require(connection)
    for row in connection.execute("SELECT spec_id,context_id FROM source_contexts"):
        read(connection, store, *row)
    if connection.execute("SELECT 1 FROM operations AS o WHERE o.method='source_context' AND NOT EXISTS "
                          "(SELECT 1 FROM source_contexts AS c WHERE c.registration_operation_id=o.operation_id) LIMIT 1").fetchone():
        raise ValueError("orphan source registration")
    for row in connection.execute("SELECT publication_id,spec_id FROM source_publications"):
        parent, request = _parent(connection, row["publication_id"])
        validate_plan(connection, store, row["spec_id"], row["publication_id"], request)
