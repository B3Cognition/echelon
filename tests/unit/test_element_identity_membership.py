"""Snapshot absence is reversible; identity retirement and history are not."""
import json
import sqlite3
from contextlib import closing

import pytest

from harness import element_identity_lifecycle as lifecycle
from harness.element_identity_store import IdentityStore, IdentityStoreError


FIRST = "### FR-000001: Movement\nMove the character.\n"
SECOND = "### FR-000002: Lighting\nLight the scene.\n"


@pytest.fixture
def store(tmp_path):
    identity = IdentityStore.initialize(tmp_path)
    ids = identity.reserve(spec_id="game", kind="FR", operation_id="allocate", count=2)
    assert ids == ("FR-000001", "FR-000002")
    identity.apply_lifecycle(spec_id="game", operation_id="create", changes=(
        lifecycle.ElementCreate(ids[0], "movement", FIRST, "allocate"),
        lifecycle.ElementCreate(ids[1], "lighting", SECOND, "allocate")))
    return identity


def membership(*, revision="1", present=False, source_revision=None, snapshot_id="candidate-a"):
    return lifecycle.ElementSnapshotMembership("FR-000002", revision, present, source_revision, snapshot_id)


def test_selecting_a_b_a_b_preserves_identity_and_appends_history(store):
    original = store.identity_history(spec_id="game")
    away = membership()
    receipt = store.apply_lifecycle(spec_id="game", operation_id="select-a", changes=(away,))
    head = store.lookup(spec_id="game", element_id="FR-000002")
    assert (head["subject"], head["revision"], head["status"], head["present"]) == ("lighting", "2", "active", False)
    back = membership(revision="2", present=True, source_revision="1", snapshot_id="candidate-b")
    store.apply_lifecycle(spec_id="game", operation_id="select-b", changes=(back,))
    head = store.lookup(spec_id="game", element_id="FR-000002")
    assert (head["revision"], head["present"], head["content"]) == ("3", True, SECOND)
    history = store.identity_history(spec_id="game")
    assert store.apply_lifecycle(spec_id="game", operation_id="select-a", changes=(away,)) == receipt
    assert store.identity_history(spec_id="game") == history
    rows = json.loads(history.payload)
    assert json.loads(original.payload)["revisions"] == [row for row in rows["revisions"] if row["revision"] == "1"]
    assert [(row["revision"], row["present"]) for row in rows["snapshot_memberships"]] == [("2", False), ("3", True)]
    assert store.reserve(spec_id="game", kind="FR", operation_id="next", count=1) == ("FR-000003",)


def test_snapshot_content_restoration_is_a_forward_revision(store):
    store.apply_lifecycle(spec_id="game", operation_id="revise", changes=(
        lifecycle.ElementRevision("FR-000002", "1", "lighting", SECOND + "Use daylight.\n"),))
    store.apply_lifecycle(spec_id="game", operation_id="restore-content", changes=(
        membership(revision="2", present=True, source_revision="1"),))
    head = store.lookup(spec_id="game", element_id="FR-000002")
    assert head["revision"] == "3" and head["content"] == SECOND
    assert store.read_revision(spec_id="game", element_id="FR-000002", revision="2")["content"].endswith("Use daylight.\n")


def test_snapshot_membership_cannot_revive_retired_identity(store):
    store.apply_lifecycle(spec_id="game", operation_id="absent", changes=(membership(),))
    store.apply_lifecycle(spec_id="game", operation_id="retire", changes=(
        lifecycle.ElementRetirement("FR-000002", "2", "Permanently removed from product scope"),))
    before = store.identity_history(spec_id="game")
    with pytest.raises(IdentityStoreError):
        store.apply_lifecycle(spec_id="game", operation_id="revive", changes=(
            membership(revision="3", present=True, source_revision="1"),))
    assert store.identity_history(spec_id="game") == before
    assert store.lookup(spec_id="game", element_id="FR-000002")["status"] == "retired"


def test_absent_requirement_cannot_be_revised_as_if_current(store):
    store.apply_lifecycle(spec_id="game", operation_id="absent", changes=(membership(),))
    with pytest.raises(IdentityStoreError):
        store.apply_lifecycle(spec_id="game", operation_id="edit-absent", changes=(
            lifecycle.ElementRevision("FR-000002", "2", "lighting", SECOND + "New text.\n"),))


@pytest.mark.parametrize("revision,source", [("0", "1"), ("2", "1"), ("1", "9")])
def test_membership_requires_current_revision_and_retained_target(store, revision, source):
    before = store.identity_history(spec_id="game")
    with pytest.raises((ValueError, IdentityStoreError)):
        store.apply_lifecycle(spec_id="game", operation_id="invalid", changes=(
            membership(revision=revision, present=True, source_revision=source),))
    assert store.identity_history(spec_id="game") == before


def test_membership_publication_preview_matches_commit_and_backup(store, tmp_path):
    from harness.element_identity_publication import PublicationIntentRequest, PublicationOperation
    from harness.element_identity_request_codec import encode_request
    operation = PublicationOperation("lifecycle", "select-a", encode_request("lifecycle", (membership(),)))
    proposed = store.preview_identity_history(spec_id="game", operations=(operation,))
    assert json.loads(proposed.payload)["snapshot_memberships"][0]["present"] is False
    request = PublicationIntentRequest("a" * 64, "restore selected candidate", (operation,),
                                       proposed_history_sha256=proposed.sha256)
    store.prepare_identity_publication(spec_id="game", operation_id="publish-a", request=request)
    result = store.apply_identity_publication(spec_id="game", operation_id="publish-a")
    assert store.identity_history(spec_id="game") == proposed
    assert store.apply_identity_publication(spec_id="game", operation_id="publish-a") == result
    store.backup(tmp_path / "backup")
    (tmp_path / "restored").mkdir()
    restored = IdentityStore.restore(tmp_path / "restored", tmp_path / "backup")
    assert restored.identity_history(spec_id="game") == proposed
    assert restored.apply_identity_publication(spec_id="game", operation_id="publish-a") == result


def test_candidate_requires_explicit_absence_and_explicit_reappearance(store):
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
    scope = IdentityEditScope(("spec.md",), ("FR-000002",))

    def check(before, after, changes=()):
        return store.check_identity_candidate(spec_id="game", artifacts=(
            CandidateArtifact("spec.md", "requirements", before, after),), scope=scope, changes=changes)

    assert check(FIRST + SECOND, FIRST).diagnostics
    assert not check(FIRST + SECOND, FIRST, (membership(),)).diagnostics
    store.apply_lifecycle(spec_id="game", operation_id="away", changes=(membership(),))
    assert check(FIRST, FIRST + SECOND).diagnostics
    back = membership(revision="2", present=True, source_revision="1")
    assert not check(FIRST, FIRST + SECOND, (back,)).diagnostics
    assert check(FIRST + SECOND, FIRST + SECOND).diagnostics  # drifted preimage


def test_graph_retains_absent_identity_history_and_membership(store):
    from echelon.spec_graph import GraphNode, SpecArtifactGraph
    from echelon.spec_graph_identity import project_identity_history
    store.apply_lifecycle(spec_id="game", operation_id="away", changes=(membership(),))
    base = SpecArtifactGraph("game", "test", (), (
        GraphNode("spec:game", "Spec", {"spec_id": "game"}),), (), ())
    graph = project_identity_history(base, store.identity_history(spec_id="game"))
    node = next(node for node in graph.nodes if node.id == "req:game:FR-000002")
    assert node.properties["identity"]["status"] == "active"
    assert node.properties["identity"]["present"] is False
    revision = next(node for node in graph.nodes if node.type == "ElementRevision"
                    and node.properties["element_id"] == "FR-000002" and node.properties["revision"] == "2")
    assert revision.properties["snapshot_membership"]["snapshot_id"] == "candidate-a"


@pytest.mark.parametrize("damage", [
    "DELETE FROM snapshot_memberships",
    "UPDATE snapshot_memberships SET snapshot_id='different-candidate'",
    "UPDATE snapshot_memberships SET operation_id='allocate'",
    "UPDATE snapshot_memberships SET present=1,source_revision='2'",
])
def test_membership_corruption_is_not_reinterpreted_as_ordinary_revision(store, tmp_path, damage):
    store.apply_lifecycle(spec_id="game", operation_id="away", changes=(membership(),))
    with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
        connection.execute(damage)
        connection.commit()
    with pytest.raises(IdentityStoreError):
        store.identity_history(spec_id="game")


def test_absent_historical_revision_cannot_be_selected_as_present_content(store):
    store.apply_lifecycle(spec_id="game", operation_id="away", changes=(membership(),))
    before = store.identity_history(spec_id="game")
    with pytest.raises(IdentityStoreError):
        store.apply_lifecycle(spec_id="game", operation_id="bad-return", changes=(
            membership(revision="2", present=True, source_revision="2"),))
    assert store.identity_history(spec_id="game") == before


def test_schema6_requires_explicit_upgrade_without_rewriting_history(store, tmp_path):
    from harness import element_identity_schema as schema
    before = store.identity_history(spec_id="game")
    database = tmp_path / ".echelon/identity/registry.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        for name in schema.CONTINUATION_SCHEMA:
            connection.execute(f"DROP INDEX {name}")
        connection.execute(schema.PUBLICATION_SCHEMA["publication_pending_specs"])
        connection.execute("DROP TABLE snapshot_memberships")
        connection.execute("UPDATE metadata SET value='6' WHERE key='schema_version'")
        connection.commit()
    with pytest.raises(IdentityStoreError, match="upgrade"):
        IdentityStore.open(tmp_path)
    upgraded = IdentityStore.upgrade(tmp_path)
    assert upgraded.audit()["database_schema_version"] == "8"
    assert upgraded.identity_history(spec_id="game") == before
    upgraded.apply_lifecycle(spec_id="game", operation_id="away", changes=(membership(),))
    assert upgraded.lookup(spec_id="game", element_id="FR-000002")["present"] is False


def test_membership_orphan_on_non_lifecycle_operation_is_rejected(store, tmp_path):
    store.apply_lifecycle(spec_id="game", operation_id="revise", changes=(
        lifecycle.ElementRevision("FR-000002", "1", "lighting", SECOND),))
    with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
        connection.execute("INSERT INTO snapshot_memberships VALUES ('game','FR-000002','2',0,NULL,'forged','allocate')")
        connection.commit()
    with pytest.raises(IdentityStoreError):
        store.audit()


def test_absent_revision_reference_retains_evidence_but_is_not_current(store):
    from harness.element_identity_bindings import ReferenceClaim
    store.apply_lifecycle(spec_id="game", operation_id="away", changes=(membership(),))
    store.record_reference_claims(spec_id="game", operation_id="reference", claims=(
        ReferenceClaim("evidence.md", "a" * 64, "anchor", "FR-000002", "2", "evidence"),))
    claim, = store.reference_claims(spec_id="game", source_path="evidence.md", source_sha256="a" * 64)
    assert claim["target_status"] == "active"
    assert claim["target_present"] is False
    assert claim["target_revision_matches_current"] is False


def test_lifecycle_preview_exposes_snapshot_presence_without_mutating(store):
    before = store.identity_history(spec_id="game")
    projected, = store.preview_lifecycle(spec_id="game", changes=(membership(),))
    assert projected["present"] is False
    assert store.identity_history(spec_id="game") == before


def test_erasing_restore_membership_and_rehashing_receipt_cannot_hide_reappearance(store, tmp_path):
    import hashlib
    store.apply_lifecycle(spec_id="game", operation_id="away", changes=(membership(),))
    store.apply_lifecycle(spec_id="game", operation_id="back", changes=(
        membership(revision="2", present=True, source_revision="1"),))
    with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
        connection.execute("DELETE FROM snapshot_memberships WHERE operation_id='back'")
        receipt = json.loads(connection.execute("SELECT receipt FROM lifecycle_receipts WHERE operation_id='back'").fetchone()[0])
        del receipt[0]["snapshot_membership"]
        raw = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        connection.execute("UPDATE lifecycle_receipts SET receipt=?,receipt_sha256=? WHERE operation_id='back'",
                           (raw, hashlib.sha256(raw.encode("ascii")).hexdigest()))
        connection.commit()
    with pytest.raises(IdentityStoreError):
        store.audit()


def test_membership_and_revision_rollback_together_on_receipt_failure(store, monkeypatch):
    from contextlib import contextmanager
    before = store.identity_history(spec_id="game")
    original = store._transaction

    @contextmanager
    def failing_transaction(*, write=False):
        with original(write=write) as connection:
            if write:
                connection.execute("CREATE TEMP TRIGGER stop_receipt BEFORE INSERT ON lifecycle_receipts "
                                   "BEGIN SELECT RAISE(ABORT,'injected receipt failure'); END")
            yield connection

    with monkeypatch.context() as patch:
        patch.setattr(store, "_transaction", failing_transaction)
        with pytest.raises(IdentityStoreError):
            store.apply_lifecycle(spec_id="game", operation_id="away", changes=(membership(),))
    assert store.identity_history(spec_id="game") == before
    store.apply_lifecycle(spec_id="game", operation_id="away", changes=(membership(),))
    assert store.lookup(spec_id="game", element_id="FR-000002")["present"] is False


def test_receipt_presence_requires_boolean_not_equal_integer(store, tmp_path):
    import hashlib
    receipt = store.apply_lifecycle(spec_id="game", operation_id="away", changes=(membership(),))
    receipt[0]["snapshot_membership"]["present"] = 0
    raw = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
        connection.execute("UPDATE lifecycle_receipts SET receipt=?,receipt_sha256=? WHERE operation_id='away'",
                           (raw, hashlib.sha256(raw.encode("ascii")).hexdigest()))
        connection.commit()
    with pytest.raises(IdentityStoreError):
        store.audit()
