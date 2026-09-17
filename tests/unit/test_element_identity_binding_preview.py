from contextlib import contextmanager
import hashlib
import sqlite3

import pytest

from harness import element_identity_binding_preview as binding_preview
from harness import element_identity_binding_store as binding_store
from harness import element_identity_bindings as bindings
from harness import element_identity_lifecycle_store as lifecycle_store
from harness.element_identity_bindings import IssueOccurrence, ReferenceClaim
from harness.element_identity_lifecycle import (
    ElementAdopt,
    ElementCreate,
    ElementRetirement,
    ElementRevision,
    ElementTransition,
)
from harness.element_identity_store import IdentityStore, IdentityStoreError


pytestmark = pytest.mark.unit


SPEC = "demo"
SHA256 = hashlib.sha256(b"source bytes").hexdigest()


def database(path):
    return path / ".echelon/identity/registry.sqlite3"


def sql_state(path):
    with sqlite3.connect(database(path)) as connection:
        return tuple(connection.iterdump())


def claim(label="FR-000001", revision="1", *, anchor="span:0:9"):
    return ReferenceClaim("evidence.md", SHA256, anchor, label, revision, "evidence")


def occurrence(label="ISS-000001", revision="1", *, title="Broken movement",
               body="Repair movement.", report_id="report-1"):
    return IssueOccurrence(label, revision, report_id, SHA256, "ISS-legacy", title, body)


def seeded(path):
    store = IdentityStore.initialize(path)
    store.reserve(spec_id=SPEC, kind="FR", operation_id="reserve-FR", count=8)
    store.reserve(spec_id=SPEC, kind="ISS", operation_id="reserve-ISS", count=8)
    store.apply_lifecycle(spec_id=SPEC, operation_id="seed", changes=(
        ElementCreate("FR-000001", "Scene", "Scene body.", "reserve-FR"),
        ElementCreate("ISS-000001", "Broken movement", "Repair movement.", "reserve-ISS"),
    ))
    return store


def assert_preview_unchanged(store, path, *, changes=(), claims=(), occurrences=()):
    before = sql_state(path)
    assert store.validate_projected_bindings(
        spec_id=SPEC, changes=changes, claims=claims, occurrences=occurrences,
    ) is None
    assert sql_state(path) == before


def test_reference_can_validate_against_reserved_projected_creation_without_writes(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    create = ElementCreate(label, "Scene", "Scene body.", "reserve")
    claim = ReferenceClaim("evidence.md", "a" * 64, "span:0:9", label, "1", "evidence")
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        before = tuple(connection.iterdump())
    assert store.validate_projected_bindings(
        spec_id="demo", changes=(create,), claims=(claim,),
    ) is None
    with sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3") as connection:
        assert tuple(connection.iterdump()) == before
    assert store.lookup(spec_id="demo", element_id=label) is None


@pytest.mark.parametrize("change,projected_revision", [
    (ElementRevision("FR-000001", "1", "Scene", "Revised body."), "2"),
    (ElementRetirement("FR-000001", "1", "No longer required"), "2"),
])
def test_references_accept_older_and_projected_revisions_for_existing_changes(
        tmp_path, change, projected_revision):
    store = seeded(tmp_path)
    assert_preview_unchanged(
        store, tmp_path, changes=(change,),
        claims=(claim(revision="1"), claim(revision=projected_revision, anchor="terminal")),
    )


def test_mixed_projection_validates_adoption_revision_and_exact_unicode_issue(tmp_path):
    store = seeded(tmp_path)
    store.import_identities(
        spec_id=SPEC, operation_id="legacy",
        definitions=(("FR-old", "Legacy requirement"), ("ISS-old", "Unicode issue")),
    )
    issue_body = "Line one\r\nZażółć gęślą jaźń."
    changes = (
        ElementAdopt("FR-old", "Legacy requirement", "Assessed legacy body."),
        ElementAdopt("ISS-old", "Unicode issue", issue_body),
        ElementRevision("FR-000001", "1", "Scene", "Revised scene."),
    )
    assert_preview_unchanged(
        store, tmp_path, changes=changes,
        claims=(claim("FR-old", None), claim("FR-old", "1", anchor="adopted"),
                claim("FR-000001", "2", anchor="revised")),
        occurrences=(occurrence("ISS-old", "1", title="Unicode issue", body=issue_body),),
    )


@pytest.mark.parametrize("kind", ["replace", "split", "merge"])
def test_transition_projection_validates_terminal_predecessors_and_new_successors(tmp_path, kind):
    store = seeded(tmp_path)
    predecessors = (("FR-000001", "1"),)
    if kind == "merge":
        store.apply_lifecycle(spec_id=SPEC, operation_id="second", changes=(
            ElementCreate("FR-000002", "Second", "Second body.", "reserve-FR"),
        ))
        predecessors += (("FR-000002", "1"),)
    successor_labels = ("FR-000003", "FR-000004") if kind == "split" else ("FR-000003",)
    successors = tuple(
        ElementCreate(label, f"Successor {label}", "Successor body.", "reserve-FR")
        for label in successor_labels
    )
    transition = ElementTransition(kind, predecessors, successors, "Reviewed transition")
    projected_claims = [claim(label, "1", anchor=label) for label in successor_labels]
    projected_claims.extend(
        claim(label, "2", anchor=f"terminal-{label}") for label, _ in predecessors
    )
    assert_preview_unchanged(store, tmp_path, changes=(transition,), claims=tuple(projected_claims))


def test_issue_occurrence_may_use_older_active_revision_when_projected_head_is_terminal(tmp_path):
    store = seeded(tmp_path)
    retirement = ElementRetirement("ISS-000001", "1", "Fixed")
    assert_preview_unchanged(
        store, tmp_path, changes=(retirement,),
        occurrences=(occurrence(),),
    )
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError, match="exact historical active issue content"):
        store.validate_projected_bindings(
            spec_id=SPEC, changes=(retirement,),
            occurrences=(occurrence(revision="2"),),
        )
    assert sql_state(tmp_path) == before


def test_reference_supports_large_current_and_projected_revision_strings(tmp_path):
    store = seeded(tmp_path)
    huge = "9" * 5000
    with sqlite3.connect(database(tmp_path)) as connection:
        connection.execute("UPDATE revisions SET revision=? WHERE element_id='FR-000001'", (huge,))
        connection.execute("UPDATE lifecycle_heads SET revision=? WHERE element_id='FR-000001'", (huge,))
    projected = "1" + "0" * 5000
    assert_preview_unchanged(
        store, tmp_path,
        changes=(ElementRevision("FR-000001", huge, "Scene", "Beyond machine integers."),),
        claims=(claim(revision=huge), claim(revision=projected, anchor="projected")),
    )


def test_empty_batches_are_a_successful_query_only_snapshot(tmp_path, monkeypatch):
    store = seeded(tmp_path)
    original_transaction = store._transaction
    query_only = []

    @contextmanager
    def observed_transaction(**arguments):
        with original_transaction(**arguments) as connection:
            yield connection
            query_only.append(connection.execute("PRAGMA query_only").fetchone()[0])

    monkeypatch.setattr(store, "_transaction", observed_transaction)
    assert_preview_unchanged(store, tmp_path)
    assert query_only == [1]


def test_nonempty_projection_calls_planner_once(tmp_path, monkeypatch):
    store = seeded(tmp_path)
    change = ElementRevision("FR-000001", "1", "Scene", "Next.")
    original = lifecycle_store.plan_changes
    calls = []

    def counted(*arguments):
        calls.append(arguments[3])
        return original(*arguments)

    monkeypatch.setattr(lifecycle_store, "plan_changes", counted)
    assert_preview_unchanged(store, tmp_path, changes=(change,), claims=(claim(revision="2"),))
    assert calls == [(change,)]


def test_internal_helper_uses_caller_query_only_transaction_without_owning_it(tmp_path, monkeypatch):
    store = seeded(tmp_path)
    change = ElementRevision("FR-000001", "1", "Scene", "Next.")
    statements = []
    with sqlite3.connect(database(tmp_path), isolation_level=None) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        connection.set_trace_callback(statements.append)
        monkeypatch.setattr(
            store, "_transaction",
            lambda **_arguments: pytest.fail("helper opened a store transaction"),
        )
        assert binding_preview.validate_projected(
            connection, store, SPEC, changes=(change,), claims=(claim(revision="2"),),
        ) is None
        assert connection.in_transaction
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        assert not any(
            statement.lstrip().upper().startswith(
                ("BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE", "PRAGMA QUERY_ONLY="),
            )
            for statement in statements
        )
        connection.rollback()


def test_internal_helper_requires_active_transaction(tmp_path):
    store = seeded(tmp_path)
    with sqlite3.connect(database(tmp_path), isolation_level=None) as connection:
        connection.row_factory = sqlite3.Row
        with pytest.raises(IdentityStoreError, match="active transaction"):
            binding_preview.validate_projected(connection, store, SPEC, claims=(claim(),))
        assert not connection.in_transaction


def test_valid_preview_agrees_with_unchanged_connection_owned_writers(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id=SPEC, kind="ISS", operation_id="reserve", count=1)
    create = ElementCreate(label, "Broken movement", "Repair movement.", "reserve")
    item = occurrence(label, "1")
    assert_preview_unchanged(store, tmp_path, changes=(create,), occurrences=(item,))
    with store._transaction(write=True) as connection:
        lifecycle_store.apply_changes(connection, store, SPEC, "create", (create,))
        binding_store.record(
            connection, store, "issue_occurrences", SPEC, "observe",
            bindings.request((item,), IssueOccurrence),
        )
    assert store.issue_occurrences(spec_id=SPEC, issue_id=label)[0]["body"] == "Repair movement."


def test_previewed_revision_transition_and_historical_rules_match_existing_writers(tmp_path):
    store = seeded(tmp_path)
    store.import_identities(
        spec_id=SPEC, operation_id="legacy", definitions=(("FR-old", "Legacy"),),
    )
    unassessed = claim("FR-old", None, anchor="legacy")
    assert_preview_unchanged(store, tmp_path, claims=(unassessed,))
    store.record_reference_claims(
        spec_id=SPEC, operation_id="bind-legacy", claims=(unassessed,),
    )

    revision = ElementRevision("FR-000001", "1", "Scene", "Revised body.")
    revised_claim = claim(revision="2", anchor="revision")
    assert_preview_unchanged(store, tmp_path, changes=(revision,), claims=(revised_claim,))
    with store._transaction(write=True) as connection:
        lifecycle_store.apply_changes(connection, store, SPEC, "revise", (revision,))
        binding_store.record(
            connection, store, "reference_claims", SPEC, "bind-revision",
            bindings.request((revised_claim,), ReferenceClaim),
        )

    transition = ElementTransition(
        "replace", (("FR-000001", "2"),),
        (ElementCreate("FR-000002", "Replacement", "Replacement body.", "reserve-FR"),),
        "Replace revised requirement",
    )
    transition_claims = (
        claim("FR-000001", "3", anchor="terminal"),
        claim("FR-000002", "1", anchor="successor"),
        claim("FR-000001", "1", anchor="historical"),
    )
    assert_preview_unchanged(
        store, tmp_path, changes=(transition,), claims=transition_claims,
    )
    with store._transaction(write=True) as connection:
        lifecycle_store.apply_changes(connection, store, SPEC, "replace", (transition,))
        binding_store.record(
            connection, store, "reference_claims", SPEC, "bind-transition",
            bindings.request(transition_claims, ReferenceClaim),
        )
    saved = store.reference_claims(
        spec_id=SPEC, source_path="evidence.md", source_sha256=SHA256,
    )
    assert {(row["target_id"], row["target_revision"]) for row in saved} >= {
        ("FR-old", None), ("FR-000001", "1"), ("FR-000001", "2"),
        ("FR-000001", "3"), ("FR-000002", "1"),
    }


def test_invalid_preview_matches_final_writer_failure_and_full_rollback(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id=SPEC, kind="ISS", operation_id="reserve", count=1)
    create = ElementCreate(label, "Broken movement", "Repair movement.", "reserve")
    mismatched = occurrence(label, "1", body="Different body.")
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError, match="exact historical active issue content"):
        store.validate_projected_bindings(
            spec_id=SPEC, changes=(create,), occurrences=(mismatched,),
        )
    assert sql_state(tmp_path) == before
    with pytest.raises(ValueError, match="exact historical active issue content"):
        with store._transaction(write=True) as connection:
            lifecycle_store.apply_changes(connection, store, SPEC, "create", (create,))
            binding_store.record(
                connection, store, "issue_occurrences", SPEC, "observe",
                bindings.request((mismatched,), IssueOccurrence),
            )
    assert sql_state(tmp_path) == before


def test_exact_historical_fr_001_import_can_be_unassessed_or_projected_adopted(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(
        spec_id=SPEC, operation_id="legacy", definitions=(("FR-001", "Published legacy"),),
    )
    assert_preview_unchanged(store, tmp_path, claims=(claim("FR-001", None),))
    assert_preview_unchanged(
        store, tmp_path,
        changes=(ElementAdopt("FR-001", "Published legacy", "Assessed body."),),
        claims=(claim("FR-001", "1"),),
    )
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError, match="existing assessed revision"):
        store.validate_projected_bindings(spec_id=SPEC, claims=(claim("FR-001", "1"),))
    assert sql_state(tmp_path) == before


def test_malformed_batches_and_damaged_immutable_requests_fail_before_transaction(
        tmp_path, monkeypatch):
    store = seeded(tmp_path)

    class ReferenceSubclass(ReferenceClaim):
        pass

    class OccurrenceSubclass(IssueOccurrence):
        pass

    class CreateSubclass(ElementCreate):
        pass

    damaged_claim = claim()
    damaged_occurrence = occurrence()
    damaged_change = ElementRevision("FR-000001", "1", "Scene", "Next.")
    object.__setattr__(damaged_claim, "source_anchor", [])
    object.__setattr__(damaged_occurrence, "body", {})
    object.__setattr__(damaged_change, "content", "\x00")
    invalid_calls = (
        lambda: store.validate_projected_bindings(spec_id=" "),
        lambda: store.validate_projected_bindings(spec_id="bad\x00spec"),
        lambda: store.validate_projected_bindings(spec_id=SPEC, changes=""),
        lambda: store.validate_projected_bindings(spec_id=SPEC, changes=b""),
        lambda: store.validate_projected_bindings(spec_id=SPEC, claims=""),
        lambda: store.validate_projected_bindings(spec_id=SPEC, claims=b""),
        lambda: store.validate_projected_bindings(spec_id=SPEC, occurrences=""),
        lambda: store.validate_projected_bindings(spec_id=SPEC, occurrences=b""),
        lambda: store.validate_projected_bindings(spec_id=SPEC, claims=(claim(), claim())),
        lambda: store.validate_projected_bindings(
            spec_id=SPEC, occurrences=(occurrence(), occurrence()),
        ),
        lambda: store.validate_projected_bindings(
            spec_id=SPEC, changes=(
                ElementRevision("FR-000001", "1", "Scene", "A"),
                ElementRevision("FR-000001", "1", "Scene", "B"),
            ),
        ),
        lambda: store.validate_projected_bindings(spec_id=SPEC, claims=(ReferenceSubclass(
            "evidence.md", SHA256, "anchor", "FR-000001", "1", "evidence",
        ),)),
        lambda: store.validate_projected_bindings(spec_id=SPEC, occurrences=(OccurrenceSubclass(
            "ISS-000001", "1", "report", SHA256, "ISS-old",
            "Broken movement", "Repair movement.",
        ),)),
        lambda: store.validate_projected_bindings(spec_id=SPEC, changes=(CreateSubclass(
            "FR-000002", "Second", "Body.", "reserve-FR",
        ),)),
        lambda: store.validate_projected_bindings(spec_id=SPEC, claims=(damaged_claim,)),
        lambda: store.validate_projected_bindings(spec_id=SPEC, occurrences=(damaged_occurrence,)),
        lambda: store.validate_projected_bindings(spec_id=SPEC, changes=(damaged_change,)),
    )
    monkeypatch.setattr(
        store, "_transaction",
        lambda **_arguments: pytest.fail("invalid request reached transaction boundary"),
    )
    for call in invalid_calls:
        with pytest.raises(IdentityStoreError):
            call()


@pytest.mark.parametrize("case", [
    "wrong_spec", "wrong_reservation", "stale", "subject", "missing_revision",
    "missing_target", "issue_title", "issue_body", "issue_terminal",
    "unrelated_invalid_change",
])
def test_invalid_projection_requests_preserve_full_sql_state(tmp_path, case):
    store = seeded(tmp_path)
    valid_claim = claim()
    actions = {
        "wrong_spec": lambda: store.validate_projected_bindings(
            spec_id="other", claims=(valid_claim,),
        ),
        "wrong_reservation": lambda: store.validate_projected_bindings(
            spec_id=SPEC,
            changes=(ElementCreate("FR-000002", "Second", "Body.", "reserve-ISS"),),
        ),
        "stale": lambda: store.validate_projected_bindings(
            spec_id=SPEC,
            changes=(ElementRevision("FR-000001", "2", "Scene", "Next."),),
        ),
        "subject": lambda: store.validate_projected_bindings(
            spec_id=SPEC,
            changes=(ElementRevision("FR-000001", "1", "Different", "Next."),),
        ),
        "missing_revision": lambda: store.validate_projected_bindings(
            spec_id=SPEC, claims=(claim(revision="2"),),
        ),
        "missing_target": lambda: store.validate_projected_bindings(
            spec_id=SPEC, claims=(claim("FR-000008", None),),
        ),
        "issue_title": lambda: store.validate_projected_bindings(
            spec_id=SPEC, occurrences=(occurrence(title="Different"),),
        ),
        "issue_body": lambda: store.validate_projected_bindings(
            spec_id=SPEC, occurrences=(occurrence(body="Different"),),
        ),
        "issue_terminal": lambda: store.validate_projected_bindings(
            spec_id=SPEC,
            changes=(ElementRetirement("ISS-000001", "1", "Fixed"),),
            occurrences=(occurrence(revision="2"),),
        ),
        "unrelated_invalid_change": lambda: store.validate_projected_bindings(
            spec_id=SPEC,
            changes=(
                ElementCreate("FR-000002", "Second", "Body.", "reserve-FR"),
                ElementRevision("FR-000001", "2", "Scene", "Stale."),
            ),
            claims=(claim(),),
        ),
    }
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError):
        actions[case]()
    assert sql_state(tmp_path) == before


@pytest.mark.parametrize("damage", ["counter", "head", "revision", "ordinal"])
def test_detectable_target_authority_damage_fails_without_repair(tmp_path, damage):
    store = seeded(tmp_path)
    with sqlite3.connect(database(tmp_path)) as connection:
        connection.execute({
            "counter": "UPDATE counters SET high_water='0' WHERE kind='FR'",
            "head": "UPDATE lifecycle_heads SET revision='9' WHERE element_id='FR-000001'",
            "revision": "UPDATE revisions SET content_sha256='broken' WHERE element_id='FR-000001'",
            "ordinal": "UPDATE entities SET ordinal='2' WHERE element_id='FR-000001'",
        }[damage])
    damaged = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.validate_projected_bindings(spec_id=SPEC, claims=(claim(),))
    assert sql_state(tmp_path) == damaged


def test_internal_helper_revalidates_damaged_request_inside_caller_transaction(tmp_path):
    store = seeded(tmp_path)
    item = claim()
    object.__setattr__(item, "target_revision", "01")
    before = sql_state(tmp_path)
    with store._transaction() as connection:
        query_only = connection.execute("PRAGMA query_only").fetchone()[0]
        with pytest.raises(ValueError, match="canonical decimal"):
            binding_preview.validate_projected(connection, store, SPEC, claims=(item,))
        assert connection.in_transaction
        assert connection.execute("PRAGMA query_only").fetchone()[0] == query_only
    assert sql_state(tmp_path) == before
