from __future__ import annotations

from collections.abc import Iterable, Mapping
import copy
from pathlib import Path

import pytest

from echelon.graph_read import GraphReadModel
from echelon.spec_graph import GraphEdge, GraphNode, SpecArtifactGraph
from echelon.spec_graph_audit import GraphFinding, SpecGraphAuditReport
from harness.element_identity_bindings import IssueOccurrence, ReferenceClaim
from harness.element_identity_lifecycle import (
    ElementCreate,
    ElementRetirement,
    ElementRevision,
    ElementTransition,
)
from harness.element_identity_store import IdentityStore


pytestmark = pytest.mark.unit


def _unavailable_audit() -> SpecGraphAuditReport:
    return SpecGraphAuditReport(
        schema_version=1,
        spec_id="demo",
        graph_hash=None,
        status="unavailable",
        findings=(
            GraphFinding(
                "error",
                "graph_source_unavailable",
                "supplied-model fixture has no live canonical-source audit",
            ),
        ),
    )


def _model_from_document(document: dict[str, object]) -> GraphReadModel:
    from echelon.graph_read import _indexes

    nodes_by_id, outgoing, incoming = _indexes(document)
    return GraphReadModel(
        scope="spec",
        graph_hash="sha256:supplied-model",
        document=document,
        audit=_unavailable_audit(),
        nodes_by_id=nodes_by_id,
        outgoing=outgoing,
        incoming=incoming,
    )


def _synthetic_model(
    nodes: Iterable[Mapping[str, object]],
    edges: Iterable[Mapping[str, object]] = (),
) -> GraphReadModel:
    return _model_from_document(
        {
            "schema_version": 1,
            "spec_id": "demo",
            "nodes": [dict(node) for node in nodes],
            "edges": [dict(edge) for edge in edges],
        }
    )


def _node(node_id: str, node_type: str, **properties: object) -> dict[str, object]:
    return {"id": node_id, "type": node_type, "properties": properties}


def _edge(source: str, relation: str, target: str) -> dict[str, object]:
    return {"source": source, "type": relation, "target": target, "properties": {}}


def _edge_ids(
    edges: Iterable[Mapping[str, object]],
) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (str(edge["source"]), str(edge["type"]), str(edge["target"]))
        for edge in edges
    )


def projected_history_model(tmp_path: Path) -> tuple[GraphReadModel, str, str]:
    store = IdentityStore.initialize(tmp_path)
    (label,) = store.reserve(
        spec_id="demo", kind="FR", operation_id="reserve", count=1
    )
    store.apply_lifecycle(
        spec_id="demo",
        operation_id="create",
        changes=(ElementCreate(label, "Scene", "Original body", "reserve"),),
    )
    store.record_reference_claims(
        spec_id="demo",
        operation_id="evidence",
        claims=(
            ReferenceClaim(
                "evidence.md",
                "a" * 64,
                "span:0:9",
                label,
                "1",
                "evidence",
            ),
        ),
    )
    store.apply_lifecycle(
        spec_id="demo",
        operation_id="revise",
        changes=(ElementRevision(label, "1", "Scene", "Revised body"),),
    )

    entity_key = f"req:demo:{label}"
    base = SpecArtifactGraph(
        "demo",
        "test",
        (),
        (
            GraphNode("spec:demo", "Spec", {"spec_id": "demo"}),
            GraphNode(
                entity_key,
                "Requirement",
                {"requirement_id": label},
            ),
        ),
        (),
        (),
    )
    from echelon.spec_graph_identity import project_identity_history

    projected = project_identity_history(
        base, store.identity_history(spec_id="demo")
    )
    document = projected.to_dict()
    return _model_from_document(document), label, entity_key


def projected_transition_history_model(
    tmp_path: Path,
) -> tuple[GraphReadModel, dict[str, object]]:
    store = IdentityStore.initialize(tmp_path)
    ac_labels = store.reserve(
        spec_id="demo", kind="AC", operation_id="reserve-ac", count=5
    )
    store.apply_lifecycle(
        spec_id="demo",
        operation_id="create-root",
        changes=(
            ElementCreate(
                ac_labels[0], "Root", "Original root", "reserve-ac"
            ),
        ),
    )
    store.record_reference_claims(
        spec_id="demo",
        operation_id="root-evidence",
        claims=(
            ReferenceClaim(
                "evidence.md",
                "a" * 64,
                "span:0:9",
                ac_labels[0],
                "1",
                "evidence",
            ),
            ReferenceClaim(
                "evidence.md",
                "a" * 64,
                "span:10:19",
                ac_labels[0],
                None,
                "reference",
            ),
        ),
    )
    transitions = (
        ElementTransition(
            "replace",
            ((ac_labels[0], "1"),),
            (
                ElementCreate(
                    ac_labels[1], "Replacement", "Replacement body", "reserve-ac"
                ),
            ),
            "replace reason",
        ),
        ElementTransition(
            "split",
            ((ac_labels[1], "1"),),
            (
                ElementCreate(ac_labels[2], "Split A", "Split body A", "reserve-ac"),
                ElementCreate(ac_labels[3], "Split B", "Split body B", "reserve-ac"),
            ),
            "split reason",
        ),
        ElementTransition(
            "merge",
            ((ac_labels[2], "1"), (ac_labels[3], "1")),
            (
                ElementCreate(ac_labels[4], "Merged", "Merged body", "reserve-ac"),
            ),
            "merge reason",
        ),
    )
    for operation_id, transition in zip(
        ("replace", "split", "merge"), transitions, strict=True
    ):
        store.apply_lifecycle(
            spec_id="demo", operation_id=operation_id, changes=(transition,)
        )

    (issue_label,) = store.reserve(
        spec_id="demo", kind="ISS", operation_id="reserve-issue", count=1
    )
    store.apply_lifecycle(
        spec_id="demo",
        operation_id="create-issue",
        changes=(
            ElementCreate(issue_label, "Issue", "Old issue", "reserve-issue"),
        ),
    )
    store.record_issue_occurrences(
        spec_id="demo",
        operation_id="occurrence-old",
        occurrences=(
            IssueOccurrence(
                issue_label,
                "1",
                "old-report",
                "b" * 64,
                "ISS-display",
                "Issue",
                "Old issue",
            ),
        ),
    )
    store.apply_lifecycle(
        spec_id="demo",
        operation_id="revise-issue",
        changes=(ElementRevision(issue_label, "1", "Issue", "New issue"),),
    )
    store.record_issue_occurrences(
        spec_id="demo",
        operation_id="occurrence-new",
        occurrences=(
            IssueOccurrence(
                issue_label,
                "2",
                "new-report",
                "c" * 64,
                "ISS-display",
                "Issue",
                "New issue",
            ),
        ),
    )
    store.apply_lifecycle(
        spec_id="demo",
        operation_id="retire-issue",
        changes=(ElementRetirement(issue_label, "2", "Resolved"),),
    )
    store.import_identities(
        spec_id="demo",
        operation_id="unrelated-import",
        definitions=(("FR-unrelated", "Unrelated requirement"),),
    )

    root_key = f"req:demo:{ac_labels[0]}"
    verification_key = "artifact:verification"
    base = SpecArtifactGraph(
        "demo",
        "test",
        (),
        (
            GraphNode("spec:demo", "Spec", {"spec_id": "demo"}),
            GraphNode(
                root_key,
                "Requirement",
                {"requirement_id": ac_labels[0], "source_text": "Original markdown"},
            ),
            GraphNode(verification_key, "Artifact", {"path": "verification.md"}),
        ),
        (
            GraphEdge(
                root_key,
                "VERIFIED_BY",
                verification_key,
                {"complete": True},
            ),
        ),
        (),
    )
    from echelon.spec_graph_identity import project_identity_history

    projected = project_identity_history(
        base, store.identity_history(spec_id="demo")
    )
    model = _model_from_document(projected.to_dict())
    return model, {
        "store_root": tmp_path,
        "ac_labels": ac_labels,
        "issue_label": issue_label,
        "root_key": root_key,
        "verification_key": verification_key,
        "unrelated_key": "req:demo:FR-unrelated",
    }


def test_bare_entity_id_does_not_become_ambiguous_with_history(
    tmp_path: Path,
) -> None:
    model, label, entity_key = projected_history_model(tmp_path)
    from echelon.graph_read import graph_read_exit_code, resolve_node_id

    assert resolve_node_id(model, label) == entity_key
    assert resolve_node_id(model, label.lower()) == entity_key
    assert graph_read_exit_code(model) == 1


def test_primary_selector_supports_all_identity_families_and_exact_labels(
    tmp_path: Path,
) -> None:
    from echelon.graph_read import resolve_node_id
    from echelon.spec_graph_identity import project_identity_history

    store = IdentityStore.initialize(tmp_path)
    wide = "A-" + "9" * 5000
    labels = (
        "FR-001",
        "NFR-composite.1",
        "AC-999999",
        "U-1000000",
        wide,
        "ISS-old",
        "T-S01",
    )
    store.import_identities(
        spec_id="demo",
        operation_id="import",
        definitions=tuple((label, f"Subject {index}") for index, label in enumerate(labels)),
    )
    (terminal,) = store.reserve(
        spec_id="demo", kind="ISS", operation_id="reserve-issue", count=1
    )
    store.apply_lifecycle(
        spec_id="demo",
        operation_id="create-issue",
        changes=(ElementCreate(terminal, "Terminal issue", "Body", "reserve-issue"),),
    )
    store.apply_lifecycle(
        spec_id="demo",
        operation_id="retire-issue",
        changes=(ElementRetirement(terminal, "1", "Resolved"),),
    )
    projected = project_identity_history(
        SpecArtifactGraph(
            "demo",
            "test",
            (),
            (GraphNode("spec:demo", "Spec", {"spec_id": "demo"}),),
            (),
            (),
        ),
        store.identity_history(spec_id="demo"),
    )
    model = _model_from_document(projected.to_dict())

    for label in (*labels, terminal):
        expected = next(
            str(node["id"])
            for node in model.nodes_by_id.values()
            if node["type"]
            in {"Requirement", "Task", "Unknown", "Assumption", "Issue"}
            and node["properties"].get(
                "task_id" if str(node["type"]) == "Task" else (
                    "requirement_id"
                    if str(node["type"]) == "Requirement"
                    else "element_id"
                )
            )
            == label
        )
        assert resolve_node_id(model, label) == expected
        assert resolve_node_id(model, label.swapcase()) == expected

    imported = model.nodes_by_id[resolve_node_id(model, "FR-001")]
    retired = model.nodes_by_id[resolve_node_id(model, terminal)]
    assert imported["properties"]["identity"]["status"] == "imported"
    assert imported["properties"]["identity"]["revision"] is None
    assert retired["properties"]["identity"]["status"] == "retired"
    assert retired["properties"]["identity"]["revision"] == "2"


def test_primary_selector_precedes_history_suffix_and_arbitrary_identity_fallback() -> None:
    from echelon.graph_read import resolve_node_id

    model = _synthetic_model(
        (
            _node("req:demo:FR-001", "Requirement", requirement_id="FR-001"),
            _node("history:FR-001", "ElementRevision", element_id="FR-001"),
            _node("claim", "ReferenceClaim", target_id="FR-001"),
            _node("publication", "Artifact", publication_id="FR-001"),
        )
    )

    assert resolve_node_id(model, "FR-001") == "req:demo:FR-001"
    assert resolve_node_id(model, "fr-001") == "req:demo:FR-001"


def test_selector_preserves_exact_history_keys_and_arbitrary_id_fallback(
    tmp_path: Path,
) -> None:
    from echelon.graph_read import resolve_node_id

    model, _, _ = projected_history_model(tmp_path)
    for node_type in ("ElementRevision", "ReferenceClaim"):
        node_id = next(
            str(node["id"])
            for node in model.nodes_by_id.values()
            if node["type"] == node_type
        )
        assert resolve_node_id(model, node_id) == node_id

    fallback = _synthetic_model(
        (
            _node("artifact:published", "Artifact", publication_id="PUB-001"),
            _node("artifact:suffix", "Artifact", path="elsewhere"),
        )
    )
    assert resolve_node_id(fallback, "PUB-001") == "artifact:published"
    assert resolve_node_id(fallback, "suffix") == "artifact:suffix"


def test_selector_keeps_primary_and_fallback_ambiguity_bounded_and_sorted() -> None:
    from echelon.graph_read import NodeResolutionError, resolve_node_id

    cross_spec = _synthetic_model(
        (
            _node(
                "req:projected:FR-001",
                "Requirement",
                requirement_id="FR-001",
                identity={"status": "active"},
            ),
            _node("req:unprojected:FR-001", "Requirement", requirement_id="FR-001"),
        )
    )
    with pytest.raises(NodeResolutionError) as primary_error:
        resolve_node_id(cross_spec, "FR-001")
    assert str(primary_error.value) == (
        "ambiguous graph node selector 'FR-001': "
        "req:projected:FR-001, req:unprojected:FR-001"
    )

    no_primary = _synthetic_model(
        (
            _node("claim:a", "ReferenceClaim", target_id="FR-404"),
            _node("claim:b", "ReferenceClaim", target_id="FR-404"),
        )
    )
    with pytest.raises(NodeResolutionError) as fallback_error:
        resolve_node_id(no_primary, "FR-404")
    assert str(fallback_error.value).endswith("claim:a, claim:b")

    capped = _synthetic_model(
        tuple(
            _node(f"req:{index:02d}", "Requirement", requirement_id="FR-wide")
            for index in range(12)
        )
    )
    with pytest.raises(NodeResolutionError) as capped_error:
        resolve_node_id(capped, "FR-wide")
    assert str(capped_error.value) == (
        "ambiguous graph node selector 'FR-wide': "
        "req:00, req:01, req:02, req:03, req:04, req:05, req:06, req:07, "
        "req:08, req:09, ... (+2 more)"
    )


def test_selector_never_normalizes_numeric_padding() -> None:
    from echelon.graph_read import NodeResolutionError, resolve_node_id

    model = _synthetic_model(
        (_node("req:demo:FR-001", "Requirement", requirement_id="FR-001"),)
    )
    with pytest.raises(NodeResolutionError, match="unknown graph node selector"):
        resolve_node_id(model, "FR-1")


def test_default_impact_literal_entity_direction_matrix() -> None:
    from echelon.graph_traversal import impact

    nodes = [
        _node("spec:demo", "Spec"),
        _node("req", "Requirement", requirement_id="FR-one"),
        _node("task", "Task", task_id="T-one"),
        _node("unknown", "Unknown", element_id="U-one"),
        _node("assumption", "Assumption", element_id="A-one"),
        _node("issue", "Issue", element_id="ISS-one"),
    ]
    edges: list[dict[str, object]] = []
    entities = (
        ("req", "Requirement"),
        ("task", "Task"),
        ("unknown", "Unknown"),
        ("assumption", "Assumption"),
        ("issue", "Issue"),
    )
    for entity_id, entity_type in entities:
        history_id = f"history-{entity_id}"
        current_id = f"current-{entity_id}"
        claim_id = f"claim-{entity_id}"
        nodes.extend(
            (
                _node(history_id, "ElementRevision"),
                _node(current_id, "ElementRevision"),
                _node(claim_id, "ReferenceClaim"),
            )
        )
        membership = ("spec:demo", "HAS_IDENTITY", entity_id)
        history = (entity_id, "HAS_REVISION", history_id)
        current = (entity_id, "CURRENT_REVISION", current_id)
        reference = (claim_id, "REFERENCES_IDENTITY", entity_id)
        edges.extend(_edge(*identity) for identity in (membership, history, current, reference))

    model = _synthetic_model(nodes, edges)
    membership_edges = (
        ("spec:demo", "HAS_IDENTITY", "assumption"),
        ("spec:demo", "HAS_IDENTITY", "issue"),
        ("spec:demo", "HAS_IDENTITY", "req"),
        ("spec:demo", "HAS_IDENTITY", "task"),
        ("spec:demo", "HAS_IDENTITY", "unknown"),
    )
    spec_result = impact(model, "spec:demo", max_depth=1)
    assert tuple(str(node["id"]) for node in spec_result.nodes) == (
        "assumption",
        "issue",
        "req",
        "task",
        "unknown",
    )
    assert _edge_ids(spec_result.edges) == membership_edges

    for entity_id, _entity_type in entities:
        history_id = f"history-{entity_id}"
        current_id = f"current-{entity_id}"
        claim_id = f"claim-{entity_id}"
        membership = ("spec:demo", "HAS_IDENTITY", entity_id)
        history = (entity_id, "HAS_REVISION", history_id)
        current = (entity_id, "CURRENT_REVISION", current_id)
        reference = (claim_id, "REFERENCES_IDENTITY", entity_id)

        result = impact(model, entity_id, max_depth=1)
        assert tuple(str(node["id"]) for node in result.nodes) == tuple(
            sorted((history_id, current_id, claim_id))
        )
        assert _edge_ids(result.edges) == tuple(sorted((history, current, reference)))
        assert "spec:demo" not in {str(node["id"]) for node in result.nodes}

        for start, expected_node, expected_direction, expected_edge in (
            (history_id, entity_id, "in", history),
            (current_id, entity_id, "in", current),
            (claim_id, entity_id, "out", reference),
        ):
            reverse = impact(model, start, max_depth=1)
            assert tuple(str(node["id"]) for node in reverse.nodes) == (
                expected_node,
            )
            assert _edge_ids(reverse.edges) == (expected_edge,)
            assert reverse.paths[0].steps[0].direction == expected_direction


def test_default_impact_literal_history_and_evidence_direction_matrix() -> None:
    from echelon.graph_traversal import impact

    nodes = (
        _node("predecessor", "ElementRevision"),
        _node("successor", "ElementRevision"),
        _node("claim-assesses", "ReferenceClaim"),
        _node("assessed", "ElementRevision"),
        _node("claim-source", "ReferenceClaim"),
        _node("source", "IdentitySource"),
        _node("occurrence-issue", "IssueOccurrence"),
        _node("issue", "Issue", element_id="ISS-one"),
        _node("occurrence-revision", "IssueOccurrence"),
        _node("observed", "ElementRevision"),
        _node("occurrence-report", "IssueOccurrence"),
        _node("report", "IdentityReport"),
    )
    stored_edges = (
        ("predecessor", "SUCCESSOR_REVISION", "successor"),
        ("claim-assesses", "ASSESSES_REVISION", "assessed"),
        ("claim-source", "HAS_SOURCE", "source"),
        ("occurrence-issue", "OCCURRENCE_OF", "issue"),
        ("occurrence-revision", "OBSERVES_REVISION", "observed"),
        ("occurrence-report", "HAS_REPORT", "report"),
    )
    model = _synthetic_model(nodes, (_edge(*identity) for identity in stored_edges))
    literal_cases = (
        ("predecessor", "successor", "out", (stored_edges[0],)),
        ("successor", None, None, ()),
        ("claim-assesses", "assessed", "out", (stored_edges[1],)),
        ("assessed", "claim-assesses", "in", (stored_edges[1],)),
        ("claim-source", "source", "out", (stored_edges[2],)),
        ("source", "claim-source", "in", (stored_edges[2],)),
        ("occurrence-issue", "issue", "out", (stored_edges[3],)),
        ("issue", "occurrence-issue", "in", (stored_edges[3],)),
        ("occurrence-revision", "observed", "out", (stored_edges[4],)),
        ("observed", "occurrence-revision", "in", (stored_edges[4],)),
        ("occurrence-report", "report", "out", (stored_edges[5],)),
        ("report", "occurrence-report", "in", (stored_edges[5],)),
    )
    for start, expected_node, expected_direction, expected_edges in literal_cases:
        result = impact(model, start, max_depth=1)
        assert tuple(str(node["id"]) for node in result.nodes) == (
            () if expected_node is None else (expected_node,)
        )
        assert _edge_ids(result.edges) == expected_edges
        if expected_direction is not None:
            assert result.paths[0].steps[0].direction == expected_direction


def test_default_impact_rejects_relation_names_with_wrong_endpoint_types() -> None:
    from echelon.graph_traversal import impact

    model = _synthetic_model(
        (
            _node("spec", "Spec"),
            _node("artifact", "Artifact"),
            _node("other", "Other"),
            _node("revision", "ElementRevision"),
            _node("requirement", "Requirement", requirement_id="FR-one"),
            _node("other-revision", "Other"),
            _node("claim", "ReferenceClaim"),
        ),
        (
            _edge("spec", "HAS_IDENTITY", "artifact"),
            _edge("other", "HAS_REVISION", "revision"),
            _edge("requirement", "HAS_REVISION", "other-revision"),
            _edge("claim", "REFERENCES_IDENTITY", "artifact"),
        ),
    )

    for start in ("spec", "artifact", "other", "revision", "requirement", "claim"):
        result = impact(model, start, max_depth=1)
        assert result.nodes == ()
        assert result.edges == ()


def test_real_history_impact_preserves_lineage_evidence_and_issue_bindings(
    tmp_path: Path,
) -> None:
    from echelon.graph_traversal import impact

    model, context = projected_transition_history_model(tmp_path)
    ac_labels = context["ac_labels"]
    assert isinstance(ac_labels, tuple)
    root_key = str(context["root_key"])
    root_impact = impact(model, root_key, max_depth=12)
    root_node_ids = {str(node["id"]) for node in root_impact.nodes}
    related_keys = {f"req:demo:{label}" for label in ac_labels[1:]}

    assert related_keys <= root_node_ids
    assert str(context["verification_key"]) in root_node_ids
    assert str(context["unrelated_key"]) not in root_node_ids
    assert f"req:demo:{context['issue_label']}" not in root_node_ids
    assert len(root_impact.paths) == len(root_impact.nodes)
    assert all(len(path.node_ids) == len(set(path.node_ids)) for path in root_impact.paths)
    assert root_impact.truncated is False

    lineage = tuple(
        edge
        for edge in model.document["edges"]
        if edge["type"] == "SUCCESSOR_REVISION"
    )
    assert {edge["properties"]["kind"] for edge in lineage} == {
        "replace",
        "split",
        "merge",
    }
    assert sorted(edge["properties"]["reason"] for edge in lineage) == [
        "merge reason",
        "merge reason",
        "replace reason",
        "split reason",
        "split reason",
    ]
    root_entity = model.nodes_by_id[root_key]
    assert root_entity["properties"]["identity"]["status"] == "superseded"
    assert root_entity["properties"]["identity"]["revision"] == "2"
    root_revisions = tuple(
        node
        for node in model.nodes_by_id.values()
        if node["type"] == "ElementRevision"
        and node["properties"]["element_id"] == ac_labels[0]
    )
    assert {node["properties"]["status"] for node in root_revisions} == {
        "active",
        "superseded",
    }

    old_claim = next(
        node
        for node in model.nodes_by_id.values()
        if node["type"] == "ReferenceClaim"
        and node["properties"]["target_revision"] == "1"
    )
    null_claim = next(
        node
        for node in model.nodes_by_id.values()
        if node["type"] == "ReferenceClaim"
        and node["properties"]["target_revision"] is None
    )
    source = next(
        node
        for node in model.nodes_by_id.values()
        if node["type"] == "IdentitySource"
    )
    assert old_claim["properties"]["target_revision_matches_current"] is False
    assert null_claim["properties"]["target_revision_matches_current"] is False
    assert source["properties"] == {
        "spec_id": "demo",
        "source_path": "evidence.md",
        "source_sha256": "a" * 64,
    }
    source_impact = impact(model, str(source["id"]), max_depth=12)
    source_node_ids = {str(node["id"]) for node in source_impact.nodes}
    assert str(old_claim["id"]) in source_node_ids
    assert str(null_claim["id"]) in source_node_ids
    assert root_key in source_node_ids
    assert related_keys <= source_node_ids
    assert str(context["unrelated_key"]) not in source_node_ids
    assert next(
        node for node in source_impact.nodes if node["id"] == old_claim["id"]
    ) is old_claim

    verification_edge = next(
        edge
        for edge in model.document["edges"]
        if edge["source"] == root_key and edge["type"] == "VERIFIED_BY"
    )
    assert verification_edge["properties"] == {
        "complete": True,
        "identity_assessment": "unassessed",
    }
    returned_verification = next(
        edge
        for edge in root_impact.edges
        if edge["source"] == root_key and edge["type"] == "VERIFIED_BY"
    )
    assert returned_verification is verification_edge

    old_report = next(
        node
        for node in model.nodes_by_id.values()
        if node["type"] == "IdentityReport"
        and node["properties"]["report_id"] == "old-report"
    )
    report_impact = impact(model, str(old_report["id"]), max_depth=12)
    report_node_ids = {str(node["id"]) for node in report_impact.nodes}
    issue_key = f"req:demo:{context['issue_label']}"
    assert issue_key in report_node_ids
    occurrences = tuple(
        node
        for node in model.nodes_by_id.values()
        if node["type"] == "IssueOccurrence"
    )
    assert {str(node["id"]) for node in occurrences} <= report_node_ids
    assert all(node["properties"]["issue_fingerprint"] for node in occurrences)
    assert all(
        next(
            returned
            for returned in report_impact.nodes
            if returned["id"] == occurrence["id"]
        )
        is occurrence
        for occurrence in occurrences
    )
    issue_entity = model.nodes_by_id[issue_key]
    assert issue_entity["properties"]["identity"]["status"] == "retired"
    assert issue_entity["properties"]["identity"]["revision"] == "3"

    bounded = impact(model, str(source["id"]), max_depth=1)
    assert bounded.truncated is True
    assert impact(model, root_key, max_depth=12) == root_impact

    final_key = f"req:demo:{ac_labels[-1]}"
    final_impact = impact(model, final_key, max_depth=12)
    final_node_ids = {str(node["id"]) for node in final_impact.nodes}
    assert not {f"req:demo:{label}" for label in ac_labels[:-1]} & final_node_ids


def test_exact_issue_occurrence_key_resolves_without_display_id_guessing(
    tmp_path: Path,
) -> None:
    from echelon.graph_read import NodeResolutionError, resolve_node_id

    model, _ = projected_transition_history_model(tmp_path)
    occurrence_key = next(
        str(node["id"])
        for node in model.nodes_by_id.values()
        if node["type"] == "IssueOccurrence"
    )
    assert resolve_node_id(model, occurrence_key) == occurrence_key
    with pytest.raises(NodeResolutionError, match="ambiguous graph node selector"):
        resolve_node_id(model, "ISS-display")


def test_all_read_operations_leave_projected_model_and_authority_unchanged(
    tmp_path: Path,
) -> None:
    from echelon.graph_read import graph_read_exit_code, resolve_node_id
    from echelon.graph_traversal import (
        explain_node,
        impact,
        neighbors,
        query_graph,
        shortest_path,
    )

    model, context = projected_transition_history_model(tmp_path)
    root_key = str(context["root_key"])
    verification_key = str(context["verification_key"])
    document_before = copy.deepcopy(model.document)
    metadata_before = (model.scope, model.graph_hash, model.audit)
    files_before = {
        path.relative_to(tmp_path): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    assert resolve_node_id(model, str(context["ac_labels"][0])) == root_key
    assert query_graph(model, "Original markdown", node_type="requirement").nodes
    assert impact(model, root_key).nodes
    assert explain_node(model, root_key).nodes
    assert neighbors(model, root_key).nodes
    assert shortest_path(model, root_key, verification_key).paths
    assert graph_read_exit_code(model) == 1

    files_after = {
        path.relative_to(tmp_path): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert model.document == document_before
    assert (model.scope, model.graph_hash, model.audit) == metadata_before
    assert files_after == files_before


def test_node_type_aliases_work_through_explicit_and_natural_queries() -> None:
    from echelon.graph_traversal import query_graph

    expected_aliases = {
        "amendment": "Amendment",
        "amendments": "Amendment",
        "artifact": "Artifact",
        "artifacts": "Artifact",
        "assumption": "Assumption",
        "assumptions": "Assumption",
        "deferral": "Deferral",
        "deferrals": "Deferral",
        "drawer": "MemPalaceDrawer",
        "drawers": "MemPalaceDrawer",
        "identityreport": "IdentityReport",
        "identityreports": "IdentityReport",
        "identitysource": "IdentitySource",
        "identitysources": "IdentitySource",
        "issue": "Issue",
        "issueoccurrence": "IssueOccurrence",
        "issueoccurrences": "IssueOccurrence",
        "issues": "Issue",
        "referenceclaim": "ReferenceClaim",
        "referenceclaims": "ReferenceClaim",
        "requirement": "Requirement",
        "requirements": "Requirement",
        "revision": "ElementRevision",
        "revisions": "ElementRevision",
        "source": "SourceRoot",
        "sources": "SourceRoot",
        "spec": "Spec",
        "specification": "Spec",
        "specifications": "Spec",
        "specs": "Spec",
        "task": "Task",
        "tasks": "Task",
        "unknown": "Unknown",
        "unknowns": "Unknown",
        "workspace": "Workspace",
        "workspaces": "Workspace",
    }
    node_types = tuple(sorted(set(expected_aliases.values())))
    model = _synthetic_model(
        tuple(
            _node(f"node:{node_type}", node_type, searchable="needle")
            for node_type in node_types
        )
    )

    for alias, expected_type in expected_aliases.items():
        explicit = query_graph(model, "needle", node_type=alias)
        natural = query_graph(model, f"show {alias} needle")
        assert tuple(str(node["type"]) for node in explicit.nodes) == (
            expected_type,
        )
        assert tuple(str(node["type"]) for node in natural.nodes) == (
            expected_type,
        )
