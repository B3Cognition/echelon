"""Bounded links inside the publication journal, not a second writer.

The root predeclares exactly one child. Completion claims are retained here;
their native meaning remains the completion owner's responsibility.
"""


def claimed_parent(connection, operation_id):
    row = connection.execute("SELECT operation_id FROM publication_intents "
        "WHERE json_extract(request,'$.continuation_id')=?", (operation_id,)).fetchone()
    return None if row is None else row[0]


def _pair(parent, root, child, request):
    claim = request.continuation
    if (claim is None or root.continuation is not None
            or root.continuation_id != child["operation_id"]
            or claim.parent_operation_id != parent["operation_id"]
            or parent["operation_id"] == child["operation_id"]
            or parent["spec_id"] != child["spec_id"]
            or claim.parent_request_sha256 != parent["request_sha256"]
            or claim.parent_application_sha256 != parent["application_receipt_sha256"]
            or root.sources.context_id != request.sources.context_id
            or request.sources.expected_operation_id != parent["operation_id"]
            or parent["state"] not in {"applied", "released"}):
        raise ValueError("continuation differs from its exact applied publication owner")
    if parent["state"] == "released":
        if (child["state"] != "released"
                or child["completion_payload"] != parent["completion_payload"]):
            raise ValueError("continuation and parent completion disagree")
    elif child["state"] == "released":
        raise ValueError("continuation released before its parent")


def validate_links(connection, row, request):
    from harness.element_identity_source_store import _parent
    if request.continuation is not None or request.continuation_id is not None:
        version = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if version is None or version[0] != "8":
            raise ValueError("continuation is unsupported by this schema")
    if request.continuation is not None:
        parent, root = _parent(connection, request.continuation.parent_operation_id, links=False)
        _pair(parent, root, row, request)
    elif request.continuation_id is not None:
        if request.continuation_id == row["operation_id"]:
            raise ValueError("publication cannot continue itself")
        child = connection.execute("SELECT 1 FROM publication_intents WHERE operation_id=?",
                                   (request.continuation_id,)).fetchone()
        if child is None:
            if row["state"] == "released":
                raise ValueError("released publication is missing its continuation")
            if (connection.execute("SELECT 1 FROM operations WHERE operation_id=?", (request.continuation_id,)).fetchone()
                    or connection.execute("SELECT 1 FROM publication_operation_claims WHERE operation_id=?",
                                          (request.continuation_id,)).fetchone()):
                raise ValueError("declared continuation has a conflicting operation owner")
        else:
            child, retained = _parent(connection, request.continuation_id, links=False)
            _pair(row, request, child, retained)


def prepare_parent(connection, store, spec_id, operation_id, request):
    from harness import element_identity_publication_store as publications
    claim = request.continuation
    loaded = publications._load(connection, store, spec_id, claim.parent_operation_id)
    if loaded is None:
        raise ValueError("continuation parent is missing")
    row, root = loaded[:2]
    _pair(row, root, {"operation_id": operation_id, "spec_id": spec_id,
                     "state": "prepared"}, request)
    if row["state"] != "applied" or pending_root(connection, spec_id) != row["operation_id"]:
        raise ValueError("continuation requires its applied pending owner")
    return row["operation_id"]


def pending_root(connection, spec_id):
    from harness.element_identity_source_store import _parent
    rows = connection.execute(
        "SELECT operation_id FROM publication_intents WHERE spec_id=? AND state!='released'", (spec_id,)).fetchall()
    if not rows:
        return None
    roots, children = [], []
    for (operation_id,) in rows:
        _, request = _parent(connection, operation_id)
        if request.continuation is None:
            roots.append(operation_id)
        else:
            children.append(request.continuation.parent_operation_id)
    if len(roots) != 1 or len(children) > 1 or any(parent != roots[0] for parent in children):
        raise ValueError("conflicting pending publication owners")
    return roots[0]
