"""Intent families use real allocation, lifecycle, source and graph owners."""
import hashlib
import json

import pytest

from harness.element_artifacts import parse_identity_artifact
from harness.element_identity_bindings import ReferenceClaim
from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
from harness.element_identity_lifecycle import ElementCreate, ElementRevision
from harness.element_identity_store import IdentityStore, IdentityStoreError
from kernel.element_ids import element_id_sort_key

pytestmark = pytest.mark.unit


HEADERS = {
    "UI": "| ID | Statement | Source / Context | Priority |\n|----|-----------|------------------|----------|\n",
    "II": "| ID | Inference | Evidence | Confidence |\n|----|-----------|----------|------------|\n",
}


def artifact(kind, label, statement="Move freely", source="User request"):
    return HEADERS[kind] + f"| {label} | {statement} | {source} | " + ("high" if kind == "UI" else "0.8") + " |\n"


@pytest.mark.parametrize("kind", ["UI", "II"])
def test_existing_allocator_preserves_intent_reservations_and_legacy_spelling(tmp_path, kind):
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="demo", operation_id="import", definitions=((kind + "-001", "Original subject"),))
    assert store.reserve(spec_id="demo", kind=kind, operation_id="allocate", count=2) == (kind + "-000002", kind + "-000003")
    reopened = IdentityStore.open(tmp_path)
    assert reopened.reserve(spec_id="demo", kind=kind, operation_id="allocate", count=2) == (kind + "-000002", kind + "-000003")
    assert reopened.lookup(spec_id="demo", element_id=kind + "-001")["subject"] == "Original subject"
    with pytest.raises(IdentityStoreError):
        reopened.import_identities(spec_id="demo", operation_id="alias", definitions=((kind + "-000001", "Original subject"),))
    with pytest.raises(IdentityStoreError):
        reopened.reserve(spec_id="demo", kind=kind, operation_id="allocate", count=1)
    assert reopened.reserve(spec_id="demo", kind=kind, operation_id="next", count=1) == (kind + "-000004",)
    other = "II" if kind == "UI" else "UI"
    assert reopened.reserve(spec_id="demo", kind=other, operation_id="other", count=1) == (other + "-000001",)


@pytest.mark.parametrize("kind", ["UI", "II"])
@pytest.mark.parametrize("ordinal,next_ordinal", [("999999", "1000000"), ("9223372036854775808", "9223372036854775809"),
                                                ("9" * 4400, "1" + "0" * 4400)])
def test_intent_counter_has_no_machine_integer_ceiling(tmp_path, kind, ordinal, next_ordinal):
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="demo", operation_id="old", definitions=((kind + "-" + ordinal, "Old"),))
    assert IdentityStore.open(tmp_path).reserve(spec_id="demo", kind=kind, operation_id="new", count=1) == (kind + "-" + next_ordinal,)
    assert sorted([kind + "-1000000", kind + "-999999"], key=element_id_sort_key) == [kind + "-999999", kind + "-1000000"]
    assert element_id_sort_key(kind + "-" + ordinal) < element_id_sort_key(kind + "-" + next_ordinal)


@pytest.mark.parametrize("kind", ["UI", "II"])
def test_tracker_table_rows_define_intent_and_own_their_references(kind):
    text = artifact(kind, kind + "-001", source="See U-000001").replace("\n", "\r\n")
    parsed = parse_identity_artifact(path="user-intent.md", role="intent", text=text)
    assert parsed.diagnostics == ()
    row, = parsed.declarations
    assert (row.element_id, row.kind, row.caption, row.disposition) == (kind + "-001", kind, "Move freely", "definition")
    assert text[row.span.start:row.span.end] == text.splitlines(keepends=True)[2] == row.content
    assert text[row.label_span.start:row.label_span.end] == kind + "-001"
    ref, = parsed.references
    assert (ref.target_id, ref.owner_id, ref.relation) == ("U-000001", kind + "-001", "reference")
    reference_only = parse_identity_artifact(path="report.md", role="references", text=text)
    assert reference_only.declarations == ()
    assert [ref.target_id for ref in reference_only.references] == [kind + "-001", "U-000001"]


@pytest.mark.parametrize("damage", ["wrong_kind", "blank_id", "extra_cell", "missing_separator", "duplicate", "heading"])
def test_ambiguous_intent_definitions_reject(damage):
    text = artifact("UI", "UI-000001")
    if damage == "wrong_kind": text = text.replace("UI-000001", "II-000001")
    elif damage == "blank_id": text = text.replace("UI-000001", "")
    elif damage == "extra_cell": text = text.replace("high |", "high | extra |")
    elif damage == "missing_separator": text = text.splitlines(keepends=True)[0] + text.splitlines(keepends=True)[2]
    elif damage == "duplicate": text += text.splitlines(keepends=True)[2]
    else: text = "### UI-000001: Move freely\nUser request\n"
    assert parse_identity_artifact(path="user-intent.md", role="intent", text=text).diagnostics


@pytest.mark.parametrize("wrapper", ["```\n{}\n```", "<!--\n{}\n-->", "> {}"])
def test_examples_are_not_intent_definitions(wrapper):
    text = artifact("UI", "UI-000001")
    text = "\n".join("> " + line for line in text.splitlines()) if wrapper == "> {}" else wrapper.format(text)
    parsed = parse_identity_artifact(path="user-intent.md", role="intent", text=text)
    assert parsed.declarations == parsed.references == parsed.diagnostics == ()


@pytest.mark.parametrize("row", [
    "UI-000001 | Move freely | User request | high |\n",
    "| UI-000001 | Move freely | User request | high\n",
    "| **UI-000001** | Move freely | User request | high |\n",
    "| `UI-000001` | Move freely | User request | high |\n",
])
@pytest.mark.parametrize("header", ["", HEADERS["UI"]])
def test_malformed_definition_rows_cannot_be_reinterpreted_as_references(row, header):
    parsed = parse_identity_artifact(path="user-intent.md", role="intent", text=header + row)
    assert parsed.declarations == ()
    assert "unsupported_declaration" in {d.code for d in parsed.diagnostics}


@pytest.mark.parametrize("damage", ["blank_id_missing_separator", "blank_id_missing_pipe", "trailing_comment"])
def test_incomplete_table_or_partially_hidden_rows_reject(damage):
    text = artifact("UI", "UI-001")
    if damage == "blank_id_missing_separator":
        text = "".join(text.splitlines(keepends=True)[::2]).replace("UI-001", "")
    elif damage == "blank_id_missing_pipe":
        text = text.replace("UI-001", "").replace("high |", "high")
    else:
        text = text.replace("high |", "high | <!-- note -->")
    assert "unsupported_declaration" in {d.code for d in parse_identity_artifact(
        path="user-intent.md", role="intent", text=text).diagnostics}


def test_escaped_pipe_and_multiple_intent_tables_preserve_row_ownership():
    text = artifact("UI", "UI-001", statement=r"Move \| turn") + "\n" + artifact("II", "II-001", source="UI-001")
    parsed = parse_identity_artifact(path="user-intent.md", role="intent", text=text)
    assert parsed.diagnostics == ()
    assert [(d.element_id, d.caption) for d in parsed.declarations] == [("UI-001", r"Move \| turn"), ("II-001", "Move freely")]
    assert [(r.owner_id, r.target_id) for r in parsed.references] == [("II-001", "UI-001")]


@pytest.mark.parametrize("kind", ["UI", "II"])
def test_discovery_scope_remains_closed_to_intent_definitions(tmp_path, kind):
    from harness.element_identity_candidate import DiscoveryEditScope
    from tests.unit.test_element_identity_candidate_preview import sql_state
    store = IdentityStore.initialize(tmp_path)
    before = sql_state(tmp_path)
    with pytest.raises(ValueError, match="only U/A"):
        store.check_discovery_candidate(spec_id="demo", artifacts=(CandidateArtifact(
            "user-intent.md", "intent", None, artifact(kind, kind + "-000001")),),
            scope=DiscoveryEditScope(("user-intent.md",), (kind + "-000001",)))
    assert sql_state(tmp_path) == before


@pytest.mark.parametrize("kind", ["UI", "II"])
def test_intent_reference_ranges_and_qualifiers_use_existing_lexer(kind):
    text = f"See {kind}-001–{kind}-003."
    parsed = parse_identity_artifact(path="report.md", role="references", text=text)
    assert parsed.diagnostics == ()
    reference, = parsed.references
    assert (reference.target_id, reference.range_end_id) == (kind + "-001", kind + "-003")
    qualified = parse_identity_artifact(path="report.md", role="references", text=f"other::{kind}-001")
    assert qualified.references == ()
    assert [d.code for d in qualified.diagnostics] == ["unsupported_qualified_reference"]


@pytest.mark.parametrize("kind", ["UI", "II"])
def test_reserved_creation_and_rejected_edits_use_existing_candidate_authority(tmp_path, kind):
    from tests.unit.test_element_identity_candidate_preview import op, apply_history, observe
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind=kind, operation_id="allocate", count=1)
    before = artifact(kind, label)
    row, = parse_identity_artifact(path="user-intent.md", role="intent", text=before).declarations
    request = dict(spec_id="demo", artifacts=(CandidateArtifact("user-intent.md", "intent", None, before),),
        scope=IdentityEditScope(("user-intent.md",), (label,)),
        operations=(op("lifecycle", "create", ElementCreate(label, "Movement", row.content, "allocate")),))
    # New table headers are unowned text and need separate authority, just like
    # prose around definitions in the existing candidate contract.
    rejected = observe(store, tmp_path, **request)
    assert {d.code for d in rejected.check.diagnostics} == {"unowned_text_changed"}
    request["scope"] = IdentityEditScope(("user-intent.md",), (label,), ("user-intent.md",))
    preview = observe(store, tmp_path, **request)
    assert preview.check.diagnostics == ()
    apply_history(store, tmp_path, request, preview.history)
    other = "II" if kind == "UI" else "UI"
    cases = [
        ("", IdentityEditScope(("user-intent.md",), (label,)), {"definition_removed"}),
        (before.replace(label, kind + "-000002"), IdentityEditScope(("user-intent.md",), (label, kind + "-000002")),
         {"definition_removed", "unallocated_definition"}),
        (artifact(other, other + "-000001"), IdentityEditScope(("user-intent.md",), (label, other + "-000001")),
         {"definition_removed", "unallocated_definition"}),
        (before.replace("Move freely", "Changed"), IdentityEditScope((), ()),
         {"artifact_out_of_scope", "element_out_of_scope"}),
    ]
    for after, scope, expected in cases:
        result = observe(store, tmp_path, spec_id="demo", artifacts=(CandidateArtifact("user-intent.md", "intent", before, after),),
                         scope=scope, operations=())
        assert expected <= {d.code for d in result.check.diagnostics}
        assert result.history is None
    request.update(artifacts=(CandidateArtifact("user-intent.md", "intent", before, before),),
                   operations=(op("lifecycle", "repurpose", ElementRevision(label, "1", "Different subject", row.content)),))
    rejected = observe(store, tmp_path, **request)
    assert [(d.code, "subject" in d.detail) for d in rejected.check.diagnostics] == [("lifecycle_rejected", True)]


@pytest.mark.parametrize("kind", ["UI", "II"])
def test_revision_preserves_old_reference_assessment_and_graph(tmp_path, kind):
    from echelon.spec_graph import GraphNode, SpecArtifactGraph
    from echelon.spec_graph_identity import project_identity_history
    from tests.unit.test_element_identity_candidate_preview import op, apply_history
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind=kind, operation_id="allocate", count=1)
    before = artifact(kind, label)
    old, = parse_identity_artifact(path="user-intent.md", role="intent", text=before).declarations
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(ElementCreate(label, "Movement", old.content, "allocate"),))
    evidence = "See " + label + "."
    store.record_reference_claims(spec_id="demo", operation_id="assessment", claims=(
        ReferenceClaim("evidence.md", hashlib.sha256(evidence.encode()).hexdigest(), "span:4:13", label, "1", "evidence"),))
    after = artifact(kind, label, "Move using arrow keys")
    new, = parse_identity_artifact(path="user-intent.md", role="intent", text=after).declarations
    request = dict(spec_id="demo", artifacts=(CandidateArtifact("user-intent.md", "intent", before, after),
        CandidateArtifact("evidence.md", "evidence", evidence, evidence)),
        scope=IdentityEditScope(("user-intent.md",), (label,)),
        operations=(op("lifecycle", "revise", ElementRevision(label, "1", "Movement", new.content)),))
    preview = store.preview_identity_candidate(**request)
    assert preview.check.diagnostics == ()
    assert [(r.target_id, r.assessed_revisions, r.assessment_state) for r in preview.check.references] == [(label, ("1",), "historical")]
    apply_history(store, tmp_path, request, preview.history)
    history = store.identity_history(spec_id="demo")
    assert [r["content"] for r in json.loads(history.payload)["revisions"]] == [old.content, new.content]
    base = SpecArtifactGraph("demo", "test", (), (GraphNode("spec:demo", "Spec", {"spec_id": "demo"}),), (), ())
    graph = project_identity_history(base, history)
    node, = [n for n in graph.nodes if n.type == ("UserIntent" if kind == "UI" else "InferredIntent")]
    assert node.properties["element_id"] == label and node.properties["identity"]["revision"] == "2"
    claim, = [n for n in graph.nodes if n.type == "ReferenceClaim"]
    assert claim.properties["target_revision_matches_current"] is False
    revisions = {n.properties["revision"]: n.id for n in graph.nodes if n.type == "ElementRevision"}
    edges = {(e.source, e.type, e.target) for e in graph.edges}
    assert {(node.id, "HAS_REVISION", revisions["1"]), (node.id, "HAS_REVISION", revisions["2"]),
            (node.id, "CURRENT_REVISION", revisions["2"]), (claim.id, "ASSESSES_REVISION", revisions["1"])} <= edges
