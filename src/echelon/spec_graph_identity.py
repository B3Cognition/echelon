"""Pure, opt-in retained identity history view; no live consumer integration.

The caller authenticates the snapshot's authority and the independent source
graph. Consistent values and digests alone cannot establish that association.
"""

from collections.abc import Mapping
from dataclasses import fields
import hashlib
import json
from urllib.parse import quote
from uuid import UUID

from echelon.spec_graph import (
    GraphEdge, GraphInput, GraphNode, MemoryReceipt, SpecArtifactGraph,
    SpecGraphError, _canonical_digest, _scope_node_id, _validate_graph,
)
from harness import element_identity_bindings as bindings
from harness import element_identity_lifecycle as lifecycle
from harness.element_identity_json import strict_json
from harness.element_identity_snapshot import IdentityHistorySnapshot
from harness.issue_identity import issue_fingerprint
from kernel.element_ids import decimal_to_int, int_to_decimal
from echelon.spec_graph_values import copy_tree


_KINDS = {
    "FR": ("Requirement", "requirement_id"), "NFR": ("Requirement", "requirement_id"),
    "AC": ("Requirement", "requirement_id"), "T": ("Task", "task_id"),
    "U": ("Unknown", "element_id"), "A": ("Assumption", "element_id"),
    "ISS": ("Issue", "element_id"),
}
_ROWS = {
    "entities": "spec_id element_id kind subject ordinal status revision",
    "revisions": "spec_id element_id revision subject content content_sha256 status reason operation_id",
    "lineage": "spec_id predecessor_id predecessor_revision successor_id successor_revision kind reason operation_id",
    "reference_claims": "operation_id entry_index spec_id source_path source_sha256 source_anchor target_id target_revision relation payload_sha256",
    "issue_occurrences": "operation_id entry_index spec_id issue_id issue_revision report_id report_sha256 display_id title body issue_fingerprint payload_sha256",
}
_NULLABLE = {"entities": {"ordinal", "revision"}, "revisions": {"reason"},
             "reference_claims": {"target_revision"}}
_RELATIONSHIPS = {
    "HAS_IDENTITY", "HAS_REVISION", "CURRENT_REVISION", "SUCCESSOR_REVISION",
    "REFERENCES_IDENTITY", "ASSESSES_REVISION", "HAS_SOURCE", "OCCURRENCE_OF",
    "OBSERVES_REVISION", "HAS_REPORT",
}


def _require(condition):
    if not condition:
        raise ValueError("inconsistent identity projection input")


def _copy_tree(value):
    """Compatibility wrapper for the shared property-tree copier."""
    return copy_tree(value)


def _copy_graph(graph):
    _require(type(graph) is SpecArtifactGraph)
    lifecycle.text(graph.spec_id, "spec_id")
    lifecycle.text(graph.generator_version, "generator_version")
    for collection in (graph.nodes, graph.edges, graph.inputs, graph.memory_receipts):
        _require(type(collection) is tuple)
    for item in graph.inputs:
        _require(type(item) is GraphInput and type(item.required) is bool)
        for field in ("path", "hash", "role"):
            lifecycle.text(getattr(item, field), field)
        for field in ("status", "source_set_digest"):
            if getattr(item, field) is not None:
                lifecycle.text(getattr(item, field), field)
    for item in graph.memory_receipts:
        _require(type(item) is MemoryReceipt)
        for field in fields(MemoryReceipt):
            lifecycle.text(getattr(item, field.name), field.name)
    nodes, edges = [], []
    for node in graph.nodes:
        _require(type(node) is GraphNode and isinstance(node.properties, Mapping))
        lifecycle.text(node.id, "node id")
        lifecycle.text(node.type, "node type")
        nodes.append(GraphNode(node.id, node.type, _copy_tree(node.properties)))
    for edge in graph.edges:
        _require(type(edge) is GraphEdge and isinstance(edge.properties, Mapping))
        for field in ("source", "type", "target"):
            lifecycle.text(getattr(edge, field), field)
        edges.append(GraphEdge(edge.source, edge.type, edge.target, _copy_tree(edge.properties)))
    _validate_graph(tuple(nodes), tuple(edges))
    specs = [node for node in nodes if node.type == "Spec"]
    _require(len(specs) == 1 and specs[0].id == f"spec:{graph.spec_id}")
    _require(specs[0].properties.get("spec_id") == graph.spec_id)
    _require("identity_projection" not in specs[0].properties)
    _require(not any(node.id.startswith("identity-") for node in nodes))
    _require(not any(edge.type in _RELATIONSHIPS for edge in edges))
    _require(not any(item.role == "identity_history" for item in graph.inputs))
    # Reconstruct even frozen records: callers can bypass their frozen guards.
    inputs = tuple(GraphInput(**{f.name: getattr(i, f.name) for f in fields(GraphInput)}) for i in graph.inputs)
    receipts = tuple(MemoryReceipt(**{f.name: getattr(i, f.name) for f in fields(MemoryReceipt)}) for i in graph.memory_receipts)
    return nodes, edges, inputs, receipts


def _decode(snapshot, spec_id):
    _require(type(snapshot) is IdentityHistorySnapshot and type(snapshot.payload) is str)
    bindings.sha256(snapshot.sha256)
    _require(hashlib.sha256(snapshot.payload.encode("ascii")).hexdigest() == snapshot.sha256)
    value = strict_json(snapshot.payload)
    _require(type(value) is dict and set(value) == {
        "version", "workspace_uuid", "epoch_uuid", "spec_id", *_ROWS})
    _require(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) == snapshot.payload)
    for name in ("version", "workspace_uuid", "epoch_uuid", "spec_id"):
        lifecycle.text(value[name], name)
    _require(value["version"] == "1" and value["spec_id"] == spec_id)
    for name in ("workspace_uuid", "epoch_uuid"):
        _require(str(UUID(value[name])) == value[name])
    for table, keys in _ROWS.items():
        _require(type(value[table]) is list)
        for row in value[table]:
            _require(type(row) is dict and set(row) == set(keys.split()))
            for key, item in row.items():
                if item is None and key in _NULLABLE.get(table, set()):
                    continue
                lifecycle.text(item, key)
            _require(row["spec_id"] == spec_id)
    return value


def _unique(rows, keys):
    result = {}
    for row in rows:
        key = tuple(row[name] for name in keys)
        _require(key not in result)
        result[key] = row
    return result


def _next_revision(revision, delta=1):
    return int_to_decimal(decimal_to_int(revision) + delta)


def _validate_history(value):
    entities = {key[0]: row for key, row in _unique(value["entities"], ("element_id",)).items()}
    revisions = _unique(value["revisions"], ("element_id", "revision"))
    _unique(value["lineage"], ("predecessor_id", "successor_id"))
    ordinals, maxima = set(), {}
    for label, row in entities.items():
        lifecycle.label(label)
        kind, suffix = label.split("-", 1)
        ordinal = suffix.lstrip("0") if suffix.isdecimal() else None
        _require(row["kind"] == kind and row["ordinal"] == ordinal)
        if ordinal is not None:
            _require((kind, ordinal) not in ordinals)
            ordinals.add((kind, ordinal))
        _require(row["status"] in {"imported", "active", "retired", "superseded"})
        if row["revision"] is not None:
            lifecycle.revision(row["revision"])
    for (label, revision), row in revisions.items():
        lifecycle.label(label)
        lifecycle.revision(revision)
        _require(label in entities and row["subject"] == entities[label]["subject"])
        bindings.sha256(row["content_sha256"])
        _require(hashlib.sha256(row["content"].encode("utf-8")).hexdigest() == row["content_sha256"])
        _require(row["status"] in {"active", "retired", "superseded"})
        if row["status"] == "active":
            _require(row["reason"] is None)
        else:
            lifecycle.text(row["reason"], "reason")
            previous = revisions.get((label, _next_revision(revision, -1)))
            _require(previous is not None and previous["status"] == "active")
            _require(all(previous[key] == row[key] for key in ("subject", "content", "content_sha256")))
        if label not in maxima or (len(revision), revision) > (len(maxima[label]), maxima[label]):
            maxima[label] = revision
    for label, row in entities.items():
        _require(row["revision"] == maxima.get(label))
        if row["status"] == "imported":
            _require(row["revision"] is None)
        else:
            _require(row["revision"] is not None)
            _require(revisions[label, row["revision"]]["status"] == row["status"])
    for row in value["lineage"]:
        for field in ("predecessor_id", "successor_id"):
            lifecycle.label(row[field])
            _require(row[field] in entities)
        for field in ("predecessor_revision", "successor_revision"):
            lifecycle.revision(row[field])
        _require(row["predecessor_id"] != row["successor_id"] and row["kind"] in {"replace", "split", "merge"})
        predecessor = revisions.get((row["predecessor_id"], row["predecessor_revision"]))
        successor = revisions.get((row["successor_id"], row["successor_revision"]))
        terminal = revisions.get((row["predecessor_id"], _next_revision(row["predecessor_revision"])))
        _require(predecessor is not None and predecessor["status"] == "active")
        _require(successor is not None and successor["status"] == "active" and successor["revision"] == "1")
        _require(terminal is not None and terminal["status"] == "superseded")
        _require(terminal["operation_id"] == successor["operation_id"] == row["operation_id"])
        _require(terminal["reason"] == row["reason"])
    for table, entry_type in (("reference_claims", bindings.ReferenceClaim), ("issue_occurrences", bindings.IssueOccurrence)):
        _unique(value[table], ("operation_id", "entry_index"))
        for row in value[table]:
            lifecycle.revision(row["entry_index"])
            entry_type(**{field.name: row[field.name] for field in fields(entry_type)})
            bindings.sha256(row["payload_sha256"])
            payload = {key: item for key, item in row.items() if key != "payload_sha256"}
            _require(_canonical_digest([table, payload])[7:] == row["payload_sha256"])
            reference = table == "reference_claims"
            label = row["target_id" if reference else "issue_id"]
            revision = row["target_revision" if reference else "issue_revision"]
            _require(label in entities)
            if revision is not None:
                _require((label, revision) in revisions)
            if not reference:
                historical = revisions[label, revision]
                _require(entities[label]["kind"] == "ISS" and historical["status"] == "active")
                _require(historical["subject"] == row["title"] and historical["content"] == row["body"])
                bindings.sha256(row["issue_fingerprint"])
                _require(issue_fingerprint(row["title"], row["body"]) == row["issue_fingerprint"])
    return entities


def _project(graph, snapshot):
    nodes, edges, inputs, receipts = _copy_graph(graph)
    value = _decode(snapshot, graph.spec_id)
    entities = _validate_history(value)
    namespace = [value[key] for key in ("workspace_uuid", "epoch_uuid", "spec_id")]
    virtual_path = f"identity://{namespace[0]}/{namespace[1]}/{quote(graph.spec_id, safe='')}"
    _require(not any(item.path == virtual_path for item in inputs))
    inputs += (GraphInput(virtual_path, "sha256:" + snapshot.sha256, "identity_history", True),)
    spec_key = f"spec:{graph.spec_id}"
    managed = {_scope_node_id(graph.spec_id, label): row for label, row in entities.items()}
    existing = {node.id: node for node in nodes}
    entity_types = {item[0] for item in _KINDS.values()}
    for node in nodes:
        if node.type in entity_types or node.id in managed:
            _require(node.id in managed)
            row = managed[node.id]
            expected_type, label_property = _KINDS[row["kind"]]
            _require(node.type == expected_type and node.properties.get(label_property) == row["element_id"])
    for key, row in managed.items():
        node_type, label_property = _KINDS[row["kind"]]
        identity = {"workspace_uuid": namespace[0], "epoch_uuid": namespace[1],
                    **{field: row[field] for field in ("kind", "ordinal", "subject", "status", "revision")},
                    "rendered": key in existing}
        if key in existing:
            properties = existing[key].properties
            _require("identity" not in properties or properties["identity"] == identity)
            properties["identity"] = identity
        else:
            nodes.append(GraphNode(key, node_type, {label_property: row["element_id"], "identity": identity}))
        edges.append(GraphEdge(spec_key, "HAS_IDENTITY", key, {}))
    existing[spec_key].properties["identity_projection"] = {
        "version": "1", "workspace_uuid": namespace[0], "epoch_uuid": namespace[1], "history_sha256": snapshot.sha256}
    for edge in edges:
        if edge.type in {"VERIFIED_BY", "STORED_AS"} and (edge.source in managed or edge.target in managed):
            _require("identity_assessment" not in edge.properties or edge.properties["identity_assessment"] == "unassessed")
            edge.properties["identity_assessment"] = "unassessed"

    generated = {}

    def add_node(prefix, kind, key_parts, properties, *, shared=False):
        key = prefix + _canonical_digest(namespace + key_parts)[7:]
        meaning = (kind, key_parts, properties)
        _require(key not in existing)
        if key in generated:
            _require(shared and generated[key] == meaning)
        else:
            generated[key] = meaning
            nodes.append(GraphNode(key, kind, properties))
        return key

    def edge(source, kind, target, properties=None):
        edges.append(GraphEdge(source, kind, target, {} if properties is None else properties))

    revision_keys = {}
    for row in value["revisions"]:
        pair = (row["element_id"], row["revision"])
        key = add_node("identity-revision:", "ElementRevision", list(pair), row)
        revision_keys[pair] = key
        edge(_scope_node_id(graph.spec_id, pair[0]), "HAS_REVISION", key)
    for label, row in entities.items():
        if row["revision"] is not None:
            edge(_scope_node_id(graph.spec_id, label), "CURRENT_REVISION", revision_keys[label, row["revision"]])
    for row in value["lineage"]:
        edge(revision_keys[row["predecessor_id"], row["predecessor_revision"]], "SUCCESSOR_REVISION",
             revision_keys[row["successor_id"], row["successor_revision"]], row)
    for row in value["reference_claims"]:
        head = entities[row["target_id"]]
        properties = row | {"target_revision_matches_current": row["target_revision"] is not None
                            and head["status"] == "active" and row["target_revision"] == head["revision"]}
        key = add_node("identity-reference:", "ReferenceClaim", [row["operation_id"], row["entry_index"]], properties)
        edge(key, "REFERENCES_IDENTITY", _scope_node_id(graph.spec_id, row["target_id"]))
        if row["target_revision"] is not None:
            edge(key, "ASSESSES_REVISION", revision_keys[row["target_id"], row["target_revision"]])
        source = add_node("identity-source:", "IdentitySource", [row["source_path"], row["source_sha256"]],
                          {field: row[field] for field in ("spec_id", "source_path", "source_sha256")}, shared=True)
        edge(key, "HAS_SOURCE", source)
    for row in value["issue_occurrences"]:
        key = add_node("identity-occurrence:", "IssueOccurrence", [row["operation_id"], row["entry_index"]], row)
        edge(key, "OCCURRENCE_OF", _scope_node_id(graph.spec_id, row["issue_id"]))
        edge(key, "OBSERVES_REVISION", revision_keys[row["issue_id"], row["issue_revision"]])
        report = add_node("identity-report:", "IdentityReport", [row["report_id"], row["report_sha256"]],
                          {field: row[field] for field in ("spec_id", "report_id", "report_sha256")}, shared=True)
        edge(key, "HAS_REPORT", report)
    _validate_graph(tuple(nodes), tuple(edges))
    return SpecArtifactGraph(graph.spec_id, graph.generator_version, inputs, tuple(nodes), tuple(edges), receipts)


def project_identity_history(graph: SpecArtifactGraph, snapshot: IdentityHistorySnapshot) -> SpecArtifactGraph:
    """Derive a detached graph from authenticated inputs supplied by the caller.

    Rebuild from a fresh source graph on every call. This value is not publishable
    by existing consumers until their lifecycle-aware adapters are implemented.
    """
    try:
        return _project(graph, snapshot)
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, OverflowError,
            RecursionError, SpecGraphError):
        # Neither a decoder error nor a malformed endpoint may leak the payload.
        raise SpecGraphError("invalid identity history projection input") from None
