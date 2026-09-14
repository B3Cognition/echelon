"""Durable discovery associations use real allocator and source authority."""
from contextlib import closing
from dataclasses import replace
import json
import hashlib
import os
import sqlite3

import pytest

from harness.element_identity_store import IdentityStore, IdentityStoreError
from harness.discovery_semantics import DiscoveryAssignment


def database_rows(root):
    with closing(sqlite3.connect(root / ".echelon/identity/registry.sqlite3")) as connection:
        return tuple(connection.iterdump())


def test_reservation_lookup_does_not_allocate_or_rewrite_authority(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    before = database_rows(tmp_path)
    assert store.reservation(spec_id="game", kind="U", operation_id="r", count=2) is None
    assert database_rows(tmp_path) == before
    assert store.reserve(spec_id="game", kind="U", operation_id="r", count=2) == ("U-000001", "U-000002")
    before = database_rows(tmp_path)
    assert IdentityStore.open(tmp_path).reservation(spec_id="game", kind="U", operation_id="r", count=2) == (
        "U-000001", "U-000002")
    assert database_rows(tmp_path) == before


@pytest.mark.parametrize("override", [dict(spec_id="other"), dict(kind="A"), dict(count=1)])
def test_reservation_lookup_rejects_conflicting_requests_without_mutation(tmp_path, override):
    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="game", kind="U", operation_id="r", count=2)
    before = database_rows(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.reservation(**(dict(spec_id="game", kind="U", operation_id="r", count=2) | override))
    assert database_rows(tmp_path) == before


@pytest.mark.parametrize("damage", ["range", "operation", "counter", "endpoint"])
def test_reservation_lookup_rejects_damage_without_reconstructing(tmp_path, damage):
    store = IdentityStore.initialize(tmp_path)
    store.reserve(spec_id="game", kind="U", operation_id="r", count=2)
    with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
        connection.execute({"range": "DELETE FROM reservations", "operation": "DELETE FROM operations",
            "counter": "UPDATE counters SET high_water='0'", "endpoint": "UPDATE reservations SET last_ordinal='3'"}[damage])
        connection.commit()
    before = database_rows(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.reservation(spec_id="game", kind="U", operation_id="r", count=2)
    assert database_rows(tmp_path) == before


@pytest.mark.parametrize("count", [0, -1, True, "1", 1.5])
def test_reservation_lookup_rejects_invalid_count(tmp_path, count):
    store = IdentityStore.initialize(tmp_path)
    with pytest.raises(IdentityStoreError):
        store.reservation(spec_id="game", kind="U", operation_id="r", count=count)


def test_reservation_lookup_preserves_unbounded_decimal_labels(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="game", operation_id="old", definitions=(("U-" + "9" * 5000, "old"),))
    expected = ("U-1" + "0" * 5000,)
    assert store.reserve(spec_id="game", kind="U", operation_id="r", count=1) == expected
    assert store.reservation(spec_id="game", kind="U", operation_id="r", count=1) == expected


@pytest.fixture
def managed(tmp_path):
    from harness.element_identity_managed import ManagedIdentityRequest
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    root = tmp_path.resolve()
    (root / "specs/game").mkdir(parents=True)
    run = root / "runs/first"
    run.mkdir(parents=True)
    prepared = SquadPublicationTransaction.begin(root, run, "6" * 32).seal()
    with prepared.inspect_sources(tree_paths=("specs/game",), file_paths=()) as initial:
        manifest = snapshot_source_manifest(trees=initial.trees, files=initial.files)
    store = IdentityStore.initialize(root)
    source = store.register_source_context(spec_id="game", context_id="source", operation_id="source", manifest=manifest)
    genesis = store.register_managed_identity(spec_id="game", operation_id="genesis", request=ManagedIdentityRequest(
        source["workspace_uuid"], source["epoch_uuid"], "first", "source", "specs/game", "source", manifest.sha256))
    assignment = DiscoveryAssignment("discovery", "proposal-1", "game", "first", "propose", "a" * 64,
                                     ("unknowns.md", "assumptions.md"))
    proposal = {**assignment.identity(), "action": "final", "new_subjects": [
        dict(key="movement", kind="U", subject="movement-subject", caption="Movement choice"),
        dict(key="camera", kind="U", subject="camera-subject", caption="Camera choice"),
        dict(key="browser", kind="A", subject="browser-subject", caption="Browser support")], "revisions": []}
    return root, run, store, genesis, assignment, proposal


def select(journal, case, *, create=False, **overrides):
    return journal.select(case[2], **(dict(spec_id="game", run_id="first", operation_id="discovery",
        managed_identity=case[3], create=create) | overrides))


def test_mapping_survives_reopen_and_does_not_create_entities(managed):
    from harness.discovery_reservations import DiscoveryReservationJournal
    root, run, store, _, assignment, proposal = managed
    before = store.identity_history(spec_id="game")
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed, create=True)
        mappings = journal.bind(assignment, proposal)
    assert [(item.key, item.element_id) for item in mappings] == [
        ("browser", "A-000001"), ("camera", "U-000001"), ("movement", "U-000002")]
    retained = database_rows(root)
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed)
        proposal["new_subjects"].reverse()
        assert journal.bind(assignment, proposal) == mappings
    assert database_rows(root) == retained
    assert store.identity_history(spec_id="game") == before
    assert store.lookup(spec_id="game", element_id="U-000001") is None


class Interrupted(BaseException):
    pass


@pytest.mark.parametrize("kind", ["A", "U"])
@pytest.mark.parametrize("when", ["before", "after"])
def test_interrupted_allocator_replays_exact_request(managed, monkeypatch, kind, when):
    from harness.discovery_reservations import DiscoveryReservationJournal
    root, run, store, _, assignment, proposal = managed
    allocate = store.reserve
    def interrupted(**request):
        if request["kind"] == kind and when == "before":
            raise Interrupted()
        result = allocate(**request)
        if request["kind"] == kind:
            raise Interrupted()
        return result
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed, create=True)
        with monkeypatch.context() as patch:
            patch.setattr(store, "reserve", interrupted)
            with pytest.raises(Interrupted):
                journal.bind(assignment, proposal)
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed)
        mappings = journal.bind(assignment, proposal)
    assert [item.element_id for item in mappings] == ["A-000001", "U-000001", "U-000002"]
    assert IdentityStore.open(root).reserve(spec_id="game", kind="U", operation_id="next", count=1) == ("U-000003",)


@pytest.mark.parametrize("write_number", [1, 2, 3])
@pytest.mark.parametrize("when", ["before", "after"])
def test_interrupted_intent_or_mapping_write_recovers_exact_ids(managed, monkeypatch, write_number, when):
    import harness.discovery_reservations as recovery
    root, run, store, _, assignment, proposal = managed
    write = recovery.write_text_atomic
    calls = 0
    def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == write_number and when == "before":
            raise Interrupted()
        result = write(*args, **kwargs)
        if calls == write_number:
            raise Interrupted()
        return result
    with recovery.DiscoveryReservationJournal(run) as journal:
        select(journal, managed, create=True)
        with monkeypatch.context() as patch:
            patch.setattr(recovery, "write_text_atomic", interrupted)
            with pytest.raises(Interrupted):
                journal.bind(assignment, proposal)
    with recovery.DiscoveryReservationJournal(run) as journal:
        select(journal, managed)
        assert [item.element_id for item in journal.bind(assignment, proposal)] == ["A-000001", "U-000001", "U-000002"]
    assert store.reserve(spec_id="game", kind="A", operation_id="next", count=1) == ("A-000002",)


def test_repair_reuses_keys_and_adds_only_new_reservations(managed):
    from harness.discovery_reservations import DiscoveryReservationJournal
    _, run, store, _, assignment, proposal = managed
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed, create=True)
        original = journal.bind(assignment, proposal)
        second = replace(assignment, dispatch_id="proposal-2", input_fingerprint="b" * 64)
        fewer = {**proposal, **second.identity(), "new_subjects": [proposal["new_subjects"][1]]}
        assert journal.bind(second, fewer) == (original[1],)
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed)
        third = replace(assignment, dispatch_id="proposal-3", input_fingerprint="c" * 64)
        additional = {**proposal, **third.identity(), "new_subjects": proposal["new_subjects"] + [
            dict(key="lighting", kind="U", subject="lighting-subject", caption="Lighting choice")]}
        result = journal.bind(third, additional)
        assert [(item.key, item.element_id) for item in result] == [
            ("browser", "A-000001"), ("camera", "U-000001"), ("lighting", "U-000003"), ("movement", "U-000002")]
        assert [item for item in result if item.key != "lighting"] == list(original)
        fourth = replace(assignment, dispatch_id="proposal-4", input_fingerprint="d" * 64)
        with pytest.raises(ValueError):
            journal.bind(fourth, {**proposal, **fourth.identity()})
    assert store.reserve(spec_id="game", kind="U", operation_id="next", count=1) == ("U-000004",)


@pytest.mark.parametrize("field,value", [("kind", "A"), ("subject", "different-subject"), ("caption", "Different choice")])
def test_repair_cannot_reassign_a_retained_key(managed, field, value):
    from harness.discovery_reservations import DiscoveryReservationJournal
    root, run, _, _, assignment, proposal = managed
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed, create=True)
        journal.bind(assignment, proposal)
    before = database_rows(root)
    later = replace(assignment, dispatch_id="proposal-2")
    proposal["new_subjects"][0][field] = value
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed)
        with pytest.raises(ValueError):
            journal.bind(later, {**proposal, **later.identity()})
    assert database_rows(root) == before


@pytest.mark.parametrize("override", [dict(spec_id="other"), dict(run_id="other"), dict(operation_id="other")])
def test_changed_selection_cannot_use_journal(managed, override):
    from harness.discovery_reservations import DiscoveryReservationJournal
    root, run, _, _, assignment, proposal = managed
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed, create=True)
        journal.bind(assignment, proposal)
    before = database_rows(root)
    with DiscoveryReservationJournal(run) as journal:
        with pytest.raises(ValueError):
            select(journal, managed, **override)
    assert database_rows(root) == before


def test_missing_journal_does_not_initialize_on_resume(managed):
    from harness.discovery_reservations import DiscoveryReservationJournal
    root, run, _, _, _, _ = managed
    before = database_rows(root)
    with DiscoveryReservationJournal(run) as journal:
        with pytest.raises(ValueError):
            select(journal, managed)
    assert database_rows(root) == before


def test_different_reply_for_same_dispatch_and_wrong_assignment_block(managed):
    from harness.discovery_reservations import DiscoveryReservationJournal
    root, run, _, _, assignment, proposal = managed
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed, create=True)
        journal.bind(assignment, proposal)
        before = database_rows(root)
        with pytest.raises(ValueError):
            journal.bind(assignment, {**proposal, "new_subjects": []})
        other = replace(assignment, operation_id="other", dispatch_id="proposal-2")
        with pytest.raises(ValueError):
            journal.bind(other, {**proposal, **other.identity()})
        assert database_rows(root) == before


def test_pending_reservation_cannot_be_abandoned_for_different_proposal(managed, monkeypatch):
    from harness.discovery_reservations import DiscoveryReservationJournal
    root, run, store, _, assignment, proposal = managed
    def interrupted(**request):
        raise Interrupted()
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed, create=True)
        with monkeypatch.context() as patch:
            patch.setattr(store, "reserve", interrupted)
            with pytest.raises(Interrupted):
                journal.bind(assignment, proposal)
    before = database_rows(root)
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed)
        other = replace(assignment, dispatch_id="proposal-2")
        with pytest.raises(ValueError):
            journal.bind(other, {**proposal, **other.identity()})
    assert database_rows(root) == before


def completed(case):
    from harness.discovery_reservations import DiscoveryReservationJournal
    with DiscoveryReservationJournal(case[1]) as journal:
        select(journal, case, create=True)
        return journal.bind(case[4], case[5])


def rewrite_payload(run, change):
    path = run / "discovery-reservations.json"
    envelope = json.loads(path.read_text())
    change(envelope["payload"])
    envelope["sha256"] = hashlib.sha256(json.dumps(envelope["payload"], sort_keys=True,
        separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
    path.write_text(json.dumps(envelope))


@pytest.mark.parametrize("damage", ["ids", "intent", "proposal", "digest", "scope", "extra", "version"])
def test_recomputed_checksum_does_not_authenticate_forged_mapping(managed, damage):
    from harness.discovery_reservations import DiscoveryReservationJournal
    completed(managed)
    root, run = managed[:2]
    def change(data):
        record = data["proposals"][0]
        if damage == "ids": record["intents"][0]["ids"] = ["A-000099"]
        if damage == "intent": record["intents"][0]["operation_id"] = "other"
        if damage == "proposal": record["proposal"]["new_subjects"][0]["subject"] = "other"
        if damage == "digest": record["sha256"] = "0" * 64
        if damage == "scope": record["proposal"]["artifact_paths"] = ["state.json"]
        if damage == "extra": data["extra"] = True
        if damage == "version": data["schema_version"] = True
    rewrite_payload(run, change)
    before = database_rows(root)
    with DiscoveryReservationJournal(run) as journal:
        with pytest.raises(ValueError):
            select(journal, managed)
    assert database_rows(root) == before


@pytest.mark.parametrize("damage", ["missing", "duplicate", "truncated", "deep", "checksum"])
def test_missing_or_malformed_journal_blocks_without_allocation(managed, damage):
    from harness.discovery_reservations import DiscoveryReservationJournal
    completed(managed)
    root, run = managed[:2]
    path = run / "discovery-reservations.json"
    if damage == "missing": path.unlink()
    if damage == "duplicate": path.write_text('{"payload":{},"payload":{},"sha256":"x"}')
    if damage == "truncated": path.write_text('{"payload":')
    if damage == "deep": path.write_text("[" * 5000 + "]" * 5000)
    if damage == "checksum": path.write_text(path.read_text().replace('"schema_version":1', '"schema_version":2', 1))
    before = database_rows(root)
    with DiscoveryReservationJournal(run) as journal:
        with pytest.raises(ValueError):
            select(journal, managed)
    assert database_rows(root) == before


def test_completed_database_receipt_cannot_be_recreated(managed):
    from harness.discovery_reservations import DiscoveryReservationJournal
    completed(managed)
    root, run = managed[:2]
    with closing(sqlite3.connect(root / ".echelon/identity/registry.sqlite3")) as connection:
        connection.execute("DELETE FROM reservations")
        connection.execute("DELETE FROM operations WHERE method='reserve'")
        connection.commit()
    before = database_rows(root)
    with DiscoveryReservationJournal(run) as journal:
        with pytest.raises(ValueError):
            select(journal, managed)
    assert database_rows(root) == before


@pytest.mark.parametrize("target", ["discovery-reservations.json", "discovery-reservations.lock"])
@pytest.mark.parametrize("link", ["symlink", "hardlink"])
def test_linked_recovery_paths_are_rejected(managed, target, link):
    from harness.discovery_reservations import DiscoveryReservationJournal
    completed(managed)
    root, run = managed[:2]
    path = run / target
    saved = root / (target + ".saved")
    path.rename(saved)
    if link == "symlink": path.symlink_to(saved)
    else:
        os.link(saved, path)
    before = database_rows(root)
    with pytest.raises((ValueError, OSError)):
        with DiscoveryReservationJournal(run) as journal:
            select(journal, managed)
    assert database_rows(root) == before


def test_directory_replacement_blocks_before_allocation(managed):
    from harness.discovery_reservations import DiscoveryReservationJournal
    root, run, _, _, assignment, proposal = managed
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed, create=True)
        run.rename(root / "original-run")
        run.mkdir()
        before = database_rows(root)
        with pytest.raises((ValueError, OSError)):
            journal.bind(assignment, proposal)
        assert database_rows(root) == before
    assert list(run.iterdir()) == []


def test_second_writer_is_excluded_and_closed_journal_cannot_allocate(managed):
    from harness.discovery_reservations import DiscoveryReservationJournal
    root, run, _, _, assignment, proposal = managed
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed, create=True)
        with pytest.raises((ValueError, OSError)):
            with DiscoveryReservationJournal(run):
                pytest.fail("second writer entered")
    before = database_rows(root)
    with pytest.raises(ValueError):
        journal.bind(assignment, proposal)
    assert database_rows(root) == before


def test_genesis_claim_and_existing_journal_cannot_reinitialize(managed):
    from harness.discovery_reservations import DiscoveryReservationJournal
    root, run, _, genesis, _, _ = managed
    before = database_rows(root)
    with DiscoveryReservationJournal(run) as journal:
        with pytest.raises(ValueError):
            select(journal, managed, create=True, managed_identity={**genesis, "operation_id": "invented"})
    assert database_rows(root) == before
    completed(managed)
    before = database_rows(root)
    with DiscoveryReservationJournal(run) as journal:
        with pytest.raises(ValueError):
            select(journal, managed, create=True)
    assert database_rows(root) == before


@pytest.mark.parametrize("override", [dict(artifact_paths=("unknowns.md",)),
    dict(editable_revisions=(("U-001", "1"),)), dict(step="author")])
def test_changed_scope_or_nonproposal_cannot_allocate(managed, override):
    from harness.discovery_reservations import DiscoveryReservationJournal
    completed(managed)
    root, run, _, _, assignment, proposal = managed
    other = replace(assignment, dispatch_id="proposal-2", **override)
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed)
        before = database_rows(root)
        with pytest.raises(ValueError):
            journal.bind(other, {**proposal, **other.identity()})
        assert database_rows(root) == before


def test_recovered_mapping_feeds_real_candidate_preview(managed):
    from harness.discovery_reservations import DiscoveryReservationJournal
    from harness.discovery_candidate import author_artifacts, build_discovery_changes
    from harness.element_identity_candidate import IdentityEditScope
    from harness.element_identity_publication import PublicationOperation
    from harness.element_identity_request_codec import encode_request
    completed(managed)
    root, run, store, _, assignment, proposal = managed
    before = database_rows(root)
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed)
        mappings = journal.bind(assignment, proposal)
    author = replace(assignment, step="author", dispatch_id="author")
    artifacts = author_artifacts(author, {**author.identity(), "action": "final", "artifacts": {
        "unknowns.md": "### U-000001: Camera choice\r\nIsometric?\r\n\r\n### U-000002: Movement choice\r\nKeyboard?\r\n",
        "assumptions.md": "### A-000001: Browser support\r\nWebGL for U-000001.\r\n"}},
        before={"unknowns.md": None, "assumptions.md": None})
    changes = build_discovery_changes(assignment, proposal, reservations=mappings, artifacts=artifacts, existing_subjects={})
    preview = store.preview_identity_candidate(spec_id="game", artifacts=artifacts,
        scope=IdentityEditScope(assignment.artifact_paths, ("U-000001", "U-000002", "A-000001"), assignment.artifact_paths),
        operations=(PublicationOperation("lifecycle", "candidate", encode_request("lifecycle", changes)),))
    assert not preview.check.diagnostics
    assert preview.history is not None
    assert database_rows(root) == before
    assert list((root / "specs/game").iterdir()) == []


def advance_source(case):
    from harness.element_identity_publication import PublicationIntentRequest, PublicationSourceClaim
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_baseline_codec import encode_initial_publication_sources
    from pathlib import Path
    root, run, store = case[:3]
    transaction = SquadPublicationTransaction.begin(root, run, "8" * 32)
    staged = transaction.build_path("candidate")
    staged.write_bytes(b"Changed source\r\n")
    destination = Path("specs/game/glossary.md")
    transaction.add_write(destination, staged, owned_paths={destination})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs/game",), file_paths=()) as initial:
        request = PublicationIntentRequest(initial.publication.marker.manifest_sha256, "source advance", (),
            PublicationSourceClaim("source", "source", encode_initial_publication_sources(initial)))
    prepared.publish_sources(initial,
        before_publish=lambda _: store.prepare_identity_publication(spec_id="game", operation_id="advance", request=request),
        after_publish=lambda _: store.apply_identity_publication(spec_id="game", operation_id="advance"))
    store.release_identity_publication(spec_id="game", operation_id="advance", completion_payload="source accepted")


@pytest.mark.parametrize("resume", [True, False])
def test_changed_retained_source_head_blocks_even_with_original_genesis(managed, resume):
    from harness.discovery_reservations import DiscoveryReservationJournal
    root, run, store, genesis, assignment, proposal = managed
    if resume:
        completed(managed)
        advance_source(managed)
    with DiscoveryReservationJournal(run) as journal:
        if not resume:
            select(journal, managed, create=True)
            advance_source(managed)
        observed = store.check_managed_context(spec_id="game", run_id="first", record=genesis)
        assert observed["source_context"]["sequence"] == "1"
        before = database_rows(root)
        with pytest.raises(ValueError):
            if resume:
                select(journal, managed)
            else:
                journal.bind(assignment, proposal)
        assert database_rows(root) == before


def test_missing_established_database_blocks_without_rebuilding(managed):
    from harness.discovery_reservations import DiscoveryReservationJournal
    completed(managed)
    root, run = managed[:2]
    database = root / ".echelon/identity/registry.sqlite3"
    database.rename(root / "retained-database")
    with DiscoveryReservationJournal(run) as journal:
        with pytest.raises(ValueError):
            select(journal, managed)
    assert not database.exists()


def test_empty_proposal_keeps_authority_unchanged(managed):
    from harness.discovery_reservations import DiscoveryReservationJournal
    root, run, _, _, assignment, proposal = managed
    before = database_rows(root)
    empty = {**proposal, "new_subjects": []}
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed, create=True)
        assert journal.bind(assignment, empty) == ()
    with DiscoveryReservationJournal(run) as journal:
        select(journal, managed)
        assert journal.bind(assignment, empty) == ()
    assert database_rows(root) == before
