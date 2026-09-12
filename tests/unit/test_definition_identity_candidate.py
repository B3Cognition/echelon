"""General definition candidates reuse the read-only identity preflight."""

import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from typing import get_type_hints

import pytest


pytestmark = pytest.mark.unit


def logical_state(workspace):
    with sqlite3.connect(workspace / ".echelon/identity/registry.sqlite3") as connection:
        return tuple(connection.iterdump())


def diagnostic_codes(result):
    return {diagnostic.code for diagnostic in result.diagnostics}


def seed_artifacts(workspace, artifacts, *, subjects=None):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_lifecycle import ElementAdopt
    from harness.element_identity_store import IdentityStore

    subjects = subjects or {}
    store = IdentityStore.initialize(workspace)
    declarations = tuple(
        declaration
        for path, role, text in artifacts
        for declaration in parse_identity_artifact(path=path, role=role, text=text).declarations
    )
    store.import_identities(spec_id="demo", operation_id="import", definitions=tuple(
        (row.element_id, subjects.get(row.element_id, row.caption)) for row in declarations))
    store.apply_lifecycle(spec_id="demo", operation_id="adopt", changes=tuple(
        ElementAdopt(row.element_id, subjects.get(row.element_id, row.caption), row.content)
        for row in declarations))
    return store


def check(store, workspace, artifacts, *, ids=(), writable=(), unowned=(), changes=()):
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope

    original = logical_state(workspace)
    result = store.check_identity_candidate(
        spec_id="demo",
        artifacts=tuple(CandidateArtifact(*artifact) for artifact in artifacts),
        scope=IdentityEditScope(tuple(writable), tuple(ids), tuple(unowned)),
        changes=changes,
    )
    assert logical_state(workspace) == original
    keys = [(d.path or "", d.element_id or "", d.code, d.detail) for d in result.diagnostics]
    assert keys == sorted(set(keys))
    return result


def canonical_task(label, *, req="FR-001", depends="none", title="Implement movement"):
    return (
        f"- [ ] {label} complexity=standard phase=build req={req} depends={depends}\n"
        f"  **Title:** {title}\n"
    )


def test_requirement_revision_does_not_replace_immutable_subject(tmp_path):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
    from harness.element_identity_lifecycle import ElementCreate, ElementRevision
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="001-game", kind="FR", operation_id="reserve", count=1)
    before = f"- **{label}**: The player MUST move using WASD.\n"
    after = f"- **{label}**: The player MUST move using arrow keys.\n"
    old, = parse_identity_artifact(path="spec.md", role="requirements", text=before).declarations
    new, = parse_identity_artifact(path="spec.md", role="requirements", text=after).declarations
    store.apply_lifecycle(spec_id="001-game", operation_id="create", changes=(
        ElementCreate(label, "Player movement", old.content, "reserve"),))
    original = logical_state(tmp_path)

    result = store.check_identity_candidate(
        spec_id="001-game", artifacts=(CandidateArtifact("spec.md", "requirements", before, after),),
        scope=IdentityEditScope(("spec.md",), (label,)),
        changes=(ElementRevision(label, "1", "Player movement", new.content),))

    assert result.diagnostics == ()
    assert logical_state(tmp_path) == original
    assert store.lookup(spec_id="001-game", element_id=label)["revision"] == "1"
    assert store.lookup(spec_id="001-game", element_id=label)["subject"] == "Player movement"


def test_general_roles_cover_six_definition_families_and_legacy_labels(tmp_path):
    requirements = (
        "- **FR-001legacy**: Move.\n"
        "- **NFR-002**: Respond quickly.\n"
        "- **AC-003**: Movement is visible.\n"
    )
    tasks = (
        "- [ ] T-S01 complexity=standard phase=build req=FR-001legacy depends=none\n"
        "  **Title:** Implement movement\n"
    )
    store = seed_artifacts(tmp_path, (
        ("requirements.md", "requirements", requirements),
        ("tasks.md", "tasks", tasks),
    ))
    result = check(store, tmp_path, (
        ("requirements.md", "requirements", requirements, requirements),
        ("tasks.md", "tasks", tasks, tasks),
    ))
    assert result.diagnostics == ()


@pytest.mark.parametrize(
    ("path", "role", "before", "after", "label"),
    [
        ("requirements.md", "requirements", "- **FR-001**: Move with WASD.\n",
         "- **FR-001**: Move with arrows.\n", "FR-001"),
        ("tasks.md", "tasks", canonical_task("T-001", req="T-001"),
         canonical_task("T-001", req="T-001", title="Implement arrows"), "T-001"),
    ],
    ids=["requirement-wording", "task-title"],
)
def test_wording_and_title_edits_need_exact_scoped_revision(
        tmp_path, path, role, before, after, label):
    store = seed_artifacts(tmp_path, ((path, role, before),), subjects={label: "immutable-subject"})
    unauthorized = check(store, tmp_path, ((path, role, before, after),),
                         writable=(path,), ids=(label,))
    assert "definition_content_mismatch" in diagnostic_codes(unauthorized)


@pytest.mark.parametrize(
    ("role", "kind", "render"),
    [
        ("requirements", "NFR", lambda label: f"- **{label}**: Respond quickly.\n"),
        ("tasks", "T", lambda label: canonical_task(label, req=label)),
    ],
)
def test_reserved_general_creation_uses_exact_adapter_content(tmp_path, role, kind, render):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind=kind, operation_id="reserve", count=1)
    after = render(label)
    declaration, = parse_identity_artifact(path="new.md", role=role, text=after).declarations
    result = store.check_identity_candidate(
        spec_id="demo", artifacts=(CandidateArtifact("new.md", role, None, after),),
        scope=IdentityEditScope(("new.md",), (label,)),
        changes=(ElementCreate(label, "immutable-subject", declaration.content, "reserve"),))
    assert result.diagnostics == ()


def test_issue_identity_can_be_an_existing_reference_target(tmp_path):
    from harness.element_identity_lifecycle import ElementAdopt
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="demo", operation_id="import", definitions=(("ISS-001", "Issue"),))
    store.apply_lifecycle(spec_id="demo", operation_id="adopt", changes=(
        ElementAdopt("ISS-001", "Issue", "Observed issue"),))
    source = "See ISS-001.\n"
    result = check(store, tmp_path, (("references.md", "references", source, source),))
    assert result.diagnostics == ()
    assert result.references[0].target_id == "ISS-001"


@pytest.mark.parametrize("role,expected", [
    ("issues", "issue_report_context_missing"), ("invented", "unsupported_role"),
])
def test_issues_require_context_and_unknown_roles_stay_unsupported(tmp_path, role, expected):
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(tmp_path)
    text = "### ISS-001: Observed issue\n" if role == "issues" else "FR-001\n"
    result = check(store, tmp_path, (("unsupported.md", role, text, text),))
    assert diagnostic_codes(result) == {expected}


def test_projection_role_requires_an_explicit_source_association(tmp_path):
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(tmp_path)
    result = store.check_identity_candidate(
        spec_id="demo",
        artifacts=(CandidateArtifact(
            "unsupported.md", "lexicon_projection", "FR-001\n", "FR-001\n"),),
        scope=IdentityEditScope((), ()),
    )
    assert diagnostic_codes(result) == {"invalid_lexicon", "projection_binding_missing"}


def test_native_lexicon_is_authoritative_but_cannot_duplicate_markdown_definition(tmp_path):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_lifecycle import ElementAdopt
    from harness.element_identity_store import IdentityStore

    markdown = "- **FR-001**: The system MUST move.\n"
    lexicon = (
        "ARTIFACT: SPEC\nTITLE: Move\n\nREQ: FR-001\n"
        "GIVEN: a player\nWHEN: movement is requested\n"
        "THEN: the system MUST move\n"
    )
    store = IdentityStore.initialize(tmp_path)
    declaration, = parse_identity_artifact(
        path="requirements.md", role="requirements", text=markdown).declarations
    store.import_identities(spec_id="demo", operation_id="import", definitions=(("FR-001", "Movement"),))
    store.apply_lifecycle(spec_id="demo", operation_id="adopt", changes=(
        ElementAdopt("FR-001", "Movement", declaration.content),))
    result = check(store, tmp_path, (
        ("requirements.md", "requirements", markdown, markdown),
        ("requirements.lexicon", "lexicon", lexicon, lexicon),
    ))
    assert "duplicate_definition" in diagnostic_codes(result)


def nested_requirement():
    return (
        "## FR-001: Player movement\n"
        "The player MUST move.\n"
        "### AC-001: Arrow movement\n"
        "Arrow keys move the player.\n"
    )


@pytest.mark.parametrize(
    ("scope_ids", "changed_ids", "expected"),
    [
        (("FR-001", "AC-001"), ("FR-001", "AC-001"), set()),
        (("AC-001",), ("AC-001",), {"element_out_of_scope", "definition_content_mismatch"}),
        (("FR-001",), ("FR-001",), {"element_out_of_scope", "definition_content_mismatch"}),
    ],
    ids=["parent-and-child", "child-only", "parent-only"],
)
def test_nested_requirement_changes_need_exact_parent_and_child_scope_and_revisions(
        tmp_path, scope_ids, changed_ids, expected):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_lifecycle import ElementRevision

    before = nested_requirement()
    after = before.replace("Arrow keys move", "WASD moves")
    store = seed_artifacts(tmp_path, (("requirements.md", "requirements", before),), subjects={
        "FR-001": "movement-subject", "AC-001": "arrow-subject",
    })
    new = {row.element_id: row for row in parse_identity_artifact(
        path="requirements.md", role="requirements", text=after).declarations}
    changes = tuple(ElementRevision(label, "1", {
        "FR-001": "movement-subject", "AC-001": "arrow-subject",
    }[label], new[label].content) for label in changed_ids)
    result = check(store, tmp_path, (("requirements.md", "requirements", before, after),),
                   ids=scope_ids, writable=("requirements.md",), changes=changes)
    assert expected <= diagnostic_codes(result)
    if scope_ids == ("AC-001",):
        assert any(row.code == "element_out_of_scope" and row.element_id == "FR-001"
                   for row in result.diagnostics)
    if scope_ids == ("FR-001",):
        assert any(row.code == "element_out_of_scope" and row.element_id == "AC-001"
                   for row in result.diagnostics)
    if not expected:
        assert result.diagnostics == ()


def test_changed_parent_can_retain_exact_unscoped_child(tmp_path):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_lifecycle import ElementRevision

    before = nested_requirement()
    after = before.replace("The player MUST move.", "The player MUST move promptly.")
    store = seed_artifacts(tmp_path, (("requirements.md", "requirements", before),), subjects={
        "FR-001": "movement-subject", "AC-001": "arrow-subject",
    })
    parent = parse_identity_artifact(
        path="requirements.md", role="requirements", text=after).declarations[0]
    result = check(store, tmp_path, (("requirements.md", "requirements", before, after),),
                   ids=("FR-001",), writable=("requirements.md",), changes=(
                       ElementRevision("FR-001", "1", "movement-subject", parent.content),))
    assert result.diagnostics == ()


@pytest.mark.parametrize("shape", ["crossing", "identical"])
def test_general_scope_rejects_crossing_and_identical_definition_spans(shape):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_candidate import (
        CandidateArtifact, IdentityEditScope, _identity_scope_diagnostics,
    )

    text = nested_requirement()
    parsed = parse_identity_artifact(path="requirements.md", role="requirements", text=text)
    parent, child = parsed.declarations
    if shape == "crossing":
        child = replace(child, span=replace(child.span, end=parent.span.end + 1))
    else:
        child = replace(child, span=parent.span)
    malformed = replace(parsed, declarations=(parent, child))
    result = _identity_scope_diagnostics(
        CandidateArtifact("requirements.md", "requirements", text, text),
        malformed, malformed, IdentityEditScope(("requirements.md",), ("FR-001", "AC-001")))
    assert {diagnostic.code for diagnostic in result} == {"overlapping_definition_spans"}


def requirement_transition_fixture(kind):
    before_rows = ["- **FR-001**: First requirement.\n"]
    predecessors = ["FR-001"]
    if kind == "merge":
        before_rows.append("- **FR-002**: Second requirement.\n")
        predecessors.append("FR-002")
    return "".join(before_rows), tuple(predecessors)


@pytest.mark.parametrize("kind", ["replace", "split", "merge"])
def test_general_requirement_transitions_use_exact_reserved_successors(tmp_path, kind):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_lifecycle import ElementCreate, ElementTransition

    before, predecessors = requirement_transition_fixture(kind)
    store = seed_artifacts(tmp_path, (("requirements.md", "requirements", before),))
    reserved = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=4)
    successors = reserved[:2] if kind == "split" else reserved[:1]
    successor_text = "".join(f"- **{label}**: Successor requirement.\n" for label in successors)
    parsed_successors = parse_identity_artifact(
        path="successors.md", role="requirements", text=successor_text).declarations
    transition = ElementTransition(kind, tuple((label, "1") for label in predecessors), tuple(
        ElementCreate(row.element_id, f"subject:{row.element_id}", row.content, "reserve")
        for row in parsed_successors), "Reviewed transition")
    result = check(store, tmp_path, (("requirements.md", "requirements", before, successor_text),),
                   ids=predecessors + successors, writable=("requirements.md",), changes=(transition,))
    assert result.diagnostics == ()


def test_general_requirement_retirement_can_remove_or_retain_exact_history(tmp_path):
    from harness.element_identity_lifecycle import ElementRetirement

    before = "- **FR-001**: First requirement.\n"
    store = seed_artifacts(tmp_path, (("requirements.md", "requirements", before),))
    for after in ("", before):
        result = check(store, tmp_path, (("requirements.md", "requirements", before, after),),
                       ids=("FR-001",), writable=("requirements.md",), changes=(
                           ElementRetirement("FR-001", "1", "No longer required"),))
        assert result.diagnostics == ()


def test_task_requires_and_depends_resolve_active_exact_targets(tmp_path):
    requirements = "- **FR-001**: Move.\n"
    tasks = canonical_task("T-001", depends="T-002") + canonical_task(
        "T-002", title="Prepare movement")
    store = seed_artifacts(tmp_path, (
        ("requirements.md", "requirements", requirements), ("tasks.md", "tasks", tasks)))
    result = check(store, tmp_path, (
        ("requirements.md", "requirements", requirements, requirements),
        ("tasks.md", "tasks", tasks, tasks),
    ))
    assert result.diagnostics == ()
    assert [(row.target_id, row.relation) for row in result.references] == [
        ("FR-001", "requires"), ("T-002", "depends"), ("FR-001", "requires")]


@pytest.mark.parametrize("state", ["imported", "retired", "superseded"])
def test_task_dependency_rejects_every_non_active_target(tmp_path, state):
    from harness.element_identity_lifecycle import (
        ElementCreate, ElementRetirement, ElementTransition,
    )
    task = canonical_task("T-001", req="T-001", depends="T-099")
    store = seed_artifacts(tmp_path, (("tasks.md", "tasks", task),))
    if state == "imported":
        store.import_identities(spec_id="demo", operation_id="target", definitions=(("T-099", "Target"),))
    else:
        label, = store.reserve(spec_id="demo", kind="T", operation_id="reserve-target", count=1)
        assert label == "T-000002"
        # Use a legacy task identity to exercise exact targets independently of allocation format.
        store.import_identities(spec_id="demo", operation_id="target", definitions=(("T-099", "Target"),))
        from harness.element_identity_lifecycle import ElementAdopt
        store.apply_lifecycle(spec_id="demo", operation_id="adopt-target", changes=(
            ElementAdopt("T-099", "Target", "target content"),))
        if state == "retired":
            store.apply_lifecycle(spec_id="demo", operation_id="terminal", changes=(
                ElementRetirement("T-099", "1", "Done"),))
        else:
            successor = ElementCreate(label, "Replacement", "replacement", "reserve-target")
            store.apply_lifecycle(spec_id="demo", operation_id="terminal", changes=(
                ElementTransition("replace", (("T-099", "1"),), (successor,), "Replaced"),))
    result = check(store, tmp_path, (("tasks.md", "tasks", task, task),))
    assert "inactive_dependency" in diagnostic_codes(result)


def test_same_batch_reserved_task_dependency_can_resolve(tmp_path):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_lifecycle import ElementCreate, ElementRevision

    before = canonical_task("T-001", req="T-001")
    store = seed_artifacts(tmp_path, (("tasks.md", "tasks", before),))
    label, = store.reserve(spec_id="demo", kind="T", operation_id="reserve", count=1)
    after = canonical_task("T-001", req="T-001", depends=label) + canonical_task(
        label, req="T-001", title="Prepare target")
    declarations = {row.element_id: row for row in parse_identity_artifact(
        path="tasks.md", role="tasks", text=after).declarations}
    result = check(store, tmp_path, (("tasks.md", "tasks", before, after),),
                   ids=("T-001", label), writable=("tasks.md",), changes=(
                       ElementRevision("T-001", "1", "Implement movement", declarations["T-001"].content),
                       ElementCreate(label, "target-subject", declarations[label].content, "reserve"),
                   ))
    assert result.diagnostics == ()


def test_same_batch_revised_task_dependency_remains_active(tmp_path):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_lifecycle import ElementRevision

    before = canonical_task("T-001", req="T-001", depends="T-002") + canonical_task(
        "T-002", req="T-001", title="Prepare target")
    after = before.replace("Prepare target", "Prepare revised target")
    store = seed_artifacts(tmp_path, (("tasks.md", "tasks", before),))
    declarations = {row.element_id: row for row in parse_identity_artifact(
        path="tasks.md", role="tasks", text=after).declarations}
    result = check(store, tmp_path, (("tasks.md", "tasks", before, after),),
                   ids=("T-002",), writable=("tasks.md",), changes=(
                       ElementRevision("T-002", "1", "Prepare target", declarations["T-002"].content),))
    assert result.diagnostics == ()


@pytest.mark.parametrize(
    ("depends", "expected"),
    [("T-999", "reference_identity_mismatch"), ("T-002..T-004", "unsupported_reference_range")],
)
def test_task_missing_and_interval_dependencies_remain_blocking(tmp_path, depends, expected):
    task = canonical_task("T-001", req="T-001", depends=depends)
    store = seed_artifacts(tmp_path, (("tasks.md", "tasks", task),))
    result = check(store, tmp_path, (("tasks.md", "tasks", task, task),))
    assert expected in diagnostic_codes(result)


def lexicon_requirement(*, dependency="FR-002"):
    return (
        "ARTIFACT: SPEC\nTITLE: Movement\n\nREQ: FR-001\n"
        "GIVEN: a player\nWHEN: movement is requested\n"
        "THEN: the system MUST move\n"
        f"DEPENDS: {dependency}\n"
    )


def native_lexicon_definition(label, wording="the system MUST move"):
    return (
        f"ARTIFACT: SPEC\nTITLE: Movement\n\nREQ: {label}\n"
        "GIVEN: a player\nWHEN: movement is requested\n"
        f"THEN: {wording}\n"
    )


def test_absent_lexicon_before_image_allows_exact_reserved_creation(tmp_path):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_store import IdentityStore

    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    after = native_lexicon_definition(label)
    declaration, = parse_identity_artifact(
        path="requirements.lexicon", role="lexicon", text=after).declarations
    original = logical_state(tmp_path)

    result = store.check_identity_candidate(
        spec_id="demo",
        artifacts=(CandidateArtifact("requirements.lexicon", "lexicon", None, after),),
        scope=IdentityEditScope(
            ("requirements.lexicon",), (label,), ("requirements.lexicon",)),
        changes=(ElementCreate(label, "movement-subject", declaration.content, "reserve"),),
    )

    assert result.diagnostics == ()
    assert logical_state(tmp_path) == original


def test_absent_lexicon_after_image_allows_exact_retirement_removal(tmp_path):
    from harness.element_identity_lifecycle import ElementRetirement

    before = native_lexicon_definition("FR-001")
    store = seed_artifacts(tmp_path, (("requirements.lexicon", "lexicon", before),), subjects={
        "FR-001": "movement-subject",
    })
    result = check(store, tmp_path, (
        ("requirements.lexicon", "lexicon", before, None),
    ),
        ids=("FR-001",),
        writable=("requirements.lexicon",),
        unowned=("requirements.lexicon",),
        changes=(ElementRetirement("FR-001", "1", "No longer required"),),
    )
    assert result.diagnostics == ()


def test_absent_lexicon_images_allow_exact_transition_between_files(tmp_path):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_lifecycle import ElementCreate, ElementTransition

    before = native_lexicon_definition("FR-001")
    store = seed_artifacts(tmp_path, (("old.lexicon", "lexicon", before),), subjects={
        "FR-001": "movement-subject",
    })
    successor, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    after = native_lexicon_definition(successor, "the system MUST move with arrows")
    declaration, = parse_identity_artifact(
        path="new.lexicon", role="lexicon", text=after).declarations
    transition = ElementTransition(
        "replace", (("FR-001", "1"),),
        (ElementCreate(successor, "arrow-subject", declaration.content, "reserve"),),
        "Replaced movement requirement",
    )
    result = check(store, tmp_path, (
        ("old.lexicon", "lexicon", before, None),
        ("new.lexicon", "lexicon", None, after),
    ),
        ids=("FR-001", successor),
        writable=("old.lexicon", "new.lexicon"),
        unowned=("old.lexicon", "new.lexicon"),
        changes=(transition,),
    )
    assert result.diagnostics == ()


@pytest.mark.parametrize("empty_image", ["before", "after"])
def test_present_empty_native_lexicon_image_remains_invalid(tmp_path, empty_image):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
    from harness.element_identity_lifecycle import ElementCreate, ElementRetirement
    from harness.element_identity_store import IdentityStore

    if empty_image == "before":
        store = IdentityStore.initialize(tmp_path)
        label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
        after = native_lexicon_definition(label)
        declaration, = parse_identity_artifact(
            path="requirements.lexicon", role="lexicon", text=after).declarations
        before = ""
        changes = (ElementCreate(label, "movement-subject", declaration.content, "reserve"),)
    else:
        label = "FR-001"
        before = native_lexicon_definition(label)
        after = ""
        store = seed_artifacts(tmp_path, (("requirements.lexicon", "lexicon", before),), subjects={
            label: "movement-subject",
        })
        changes = (ElementRetirement(label, "1", "No longer required"),)
    original = logical_state(tmp_path)

    result = store.check_identity_candidate(
        spec_id="demo",
        artifacts=(CandidateArtifact("requirements.lexicon", "lexicon", before, after),),
        scope=IdentityEditScope(
            ("requirements.lexicon",), (label,), ("requirements.lexicon",)),
        changes=changes,
    )

    assert any(
        diagnostic.code == "invalid_lexicon"
        and diagnostic.detail.startswith(f"{empty_image} ")
        for diagnostic in result.diagnostics
    )
    assert logical_state(tmp_path) == original


@pytest.mark.parametrize("target_state", ["active", "imported"])
def test_native_lexicon_depends_uses_reachable_dependency_policy(tmp_path, target_state):
    from harness.element_identity_lifecycle import ElementAdopt

    source = lexicon_requirement()
    store = seed_artifacts(tmp_path, (("requirements.lexicon", "lexicon", source),))
    store.import_identities(spec_id="demo", operation_id="target", definitions=(("FR-002", "Target"),))
    if target_state == "active":
        store.apply_lifecycle(spec_id="demo", operation_id="target-adopt", changes=(
            ElementAdopt("FR-002", "Target", "target content"),))
    result = check(store, tmp_path, (("requirements.lexicon", "lexicon", source, source),))
    assert ("inactive_dependency" in diagnostic_codes(result)) is (target_state == "imported")


def test_preserved_reference_claim_stays_historical_after_proposed_target_revision(tmp_path):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_bindings import ReferenceClaim
    from harness.element_identity_lifecycle import ElementRevision

    before = "- **FR-001**: Move with WASD.\n"
    after = "- **FR-001**: Move with arrows.\n"
    evidence = "Observed FR-001.\n"
    store = seed_artifacts(tmp_path, (("requirements.md", "requirements", before),), subjects={
        "FR-001": "movement-subject",
    })
    parsed_evidence = parse_identity_artifact(path="evidence.md", role="evidence", text=evidence)
    reference, = parsed_evidence.references
    store.record_reference_claims(spec_id="demo", operation_id="claim", claims=(ReferenceClaim(
        "evidence.md", parsed_evidence.content_sha256,
        f"span:{reference.span.start}:{reference.span.end}", "FR-001", "1", "evidence"),))
    new, = parse_identity_artifact(
        path="requirements.md", role="requirements", text=after).declarations
    result = check(store, tmp_path, (
        ("requirements.md", "requirements", before, after),
        ("evidence.md", "evidence", evidence, evidence),
    ), ids=("FR-001",), writable=("requirements.md",), changes=(
        ElementRevision("FR-001", "1", "movement-subject", new.content),))
    assert result.diagnostics == ()
    assert result.references[0].assessed_revisions == ("1",)
    assert result.references[0].assessment_state == "historical"


def test_discovery_wrapper_keeps_original_role_and_family_restrictions(tmp_path):
    from harness.element_identity_candidate import CandidateArtifact, DiscoveryEditScope
    from harness.element_identity_store import IdentityStore, IdentityStoreError

    store = IdentityStore.initialize(tmp_path)
    text = "- **FR-001**: Requirement.\n"
    result = store.check_discovery_candidate(
        spec_id="demo", artifacts=(CandidateArtifact("requirements.md", "requirements", text, text),),
        scope=DiscoveryEditScope((), ()))
    assert diagnostic_codes(result) == {"unsupported_role"}
    with pytest.raises(IdentityStoreError, match="U/A"):
        store.check_discovery_candidate(
            spec_id="demo", artifacts=(CandidateArtifact("requirements.md", "requirements", text, text),),
            scope=DiscoveryEditScope((), ("FR-001",)))


def test_general_wrapper_does_not_weaken_discovery_caption_preservation(tmp_path):
    before = "### U-001: Original question\nBody.\n"
    after = "### U-001: Different question\nBody.\n"
    store = seed_artifacts(tmp_path, (("unknowns.md", "unknowns", before),), subjects={
        "U-001": "immutable-question-subject",
    })
    result = check(store, tmp_path, (("unknowns.md", "unknowns", before, after),),
                   ids=("U-001",), writable=("unknowns.md",))
    assert "subject_changed" in diagnostic_codes(result)


def test_public_general_type_annotation_and_issue_scope_require_context(tmp_path):
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
    from harness.element_identity_store import IdentityStore

    assert get_type_hints(IdentityStore.check_identity_candidate)["return"].__name__ == "IdentityCandidateCheck"
    store = IdentityStore.initialize(tmp_path)
    text = "### ISS-001: Observed issue\nBody.\n"
    original = logical_state(tmp_path)
    result = store.check_identity_candidate(
        spec_id="demo", artifacts=(CandidateArtifact("issues.md", "issues", text, text),),
        scope=IdentityEditScope((), ("ISS-001",)))
    assert diagnostic_codes(result) == {"issue_report_context_missing"}
    assert logical_state(tmp_path) == original


def test_general_wrapper_uses_one_query_only_transaction_and_snapshots_sequences(tmp_path, monkeypatch):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
    from harness.element_identity_lifecycle import ElementRevision

    before = "- **FR-001**: Move with WASD.\n"
    after = "- **FR-001**: Move with arrows.\n"
    store = seed_artifacts(tmp_path, (("requirements.md", "requirements", before),), subjects={
        "FR-001": "movement-subject",
    })
    new, = parse_identity_artifact(path="requirements.md", role="requirements", text=after).declarations
    artifacts = [CandidateArtifact("requirements.md", "requirements", before, after)]
    writable, labels, unowned = ["requirements.md"], ["FR-001"], []
    changes = [ElementRevision("FR-001", "1", "movement-subject", new.content)]
    transaction = store._transaction
    entered = 0

    @contextmanager
    def read_transaction():
        nonlocal entered
        entered += 1
        for caller_sequence in (artifacts, writable, labels, unowned, changes):
            caller_sequence.clear()
        with transaction() as connection:
            yield connection
            assert connection.execute("PRAGMA query_only").fetchone()[0] == 1

    monkeypatch.setattr(store, "_transaction", read_transaction)
    result = store.check_identity_candidate(
        spec_id="demo", artifacts=artifacts, scope=IdentityEditScope(writable, labels, unowned),
        changes=changes)
    assert result.diagnostics == ()
    assert entered == 1


def test_discovery_wrapper_also_sets_its_single_transaction_query_only(tmp_path, monkeypatch):
    from harness.element_identity_candidate import CandidateArtifact, DiscoveryEditScope

    source = "### U-001: Question\nBody.\n"
    store = seed_artifacts(tmp_path, (("unknowns.md", "unknowns", source),))
    transaction = store._transaction
    entered = 0

    @contextmanager
    def read_transaction():
        nonlocal entered
        entered += 1
        with transaction() as connection:
            yield connection
            assert connection.execute("PRAGMA query_only").fetchone()[0] == 1

    monkeypatch.setattr(store, "_transaction", read_transaction)
    result = store.check_discovery_candidate(
        spec_id="demo", artifacts=(CandidateArtifact("unknowns.md", "unknowns", source, source),),
        scope=DiscoveryEditScope((), ()))
    assert result.diagnostics == ()
    assert entered == 1
