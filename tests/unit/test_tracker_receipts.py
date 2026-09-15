"""Round-scoped receipts reuse the real journal and identity allocator."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from harness.discovery_receipts import DiscoveryReceiptFile
from harness.discovery_reservations import DiscoveryReservationJournal
from harness.discovery_turns import _assignment, _save, _validate, _usage
from tests.unit.test_discovery_reservations import managed, database_rows, Interrupted
from tests.unit.test_tracker_candidate import assignment, reply, routing


def proposal(round_id, *, dispatch="propose-1"):
    selected = replace(assignment(), operation_id=round_id, dispatch_id=dispatch, run_id="first")
    value = reply(selected)
    value["new_subjects"].append(dict(key="camera", kind="II", subject="Camera projection", caption="Isometric view"))
    return selected, value


def select(journal, case, round_id, *, create=False):
    journal.select(case[2], spec_id="game", run_id="first", operation_id=round_id,
        managed_identity=case[3], create=create)


@pytest.mark.parametrize("step", ["propose", "author", "review"])
def test_saved_tracker_assignments_recover_exact_routing_and_optional_artifacts(step):
    selected = assignment(step)
    if step == "review":
        selected = replace(selected, routing=tuple(routing("STOP_AND_ASK").items()))
    restored = _assignment(json.loads(json.dumps(selected.identity(), sort_keys=True)))
    assert restored.identity() == selected.identity()
    assert (dict(restored.routing) if restored.routing is not None else None) == (
        dict(selected.routing) if selected.routing is not None else None)
    value = reply(selected)
    receipt = dict(schema_version=1, binding={}, token_budget=100, dispatch_limit=9, steps=[dict(
        assignment=selected.identity(), input_sha256="a" * 64, deadline=1,
        records=[dict(prompt_sha256="b" * 64, reply=value, read=None,
            token_usage=7, error=None, accepted=True)])])
    _validate(receipt)
    assert _usage(receipt) == dict(tokens=7, known=True, dispatches=1)


def test_round_reservations_append_ids_without_replacing_prior_receipts(managed):
    first, second = "tracker-" + "a" * 32, "tracker-" + "b" * 32
    snapshots, results = {}, {}
    for round_id in (first, second):
        with DiscoveryReservationJournal(managed[1], producer="tracker", round_operation_id=round_id) as journal:
            select(journal, managed, round_id, create=True)
            results[round_id] = journal.bind(*proposal(round_id))
            snapshots[round_id] = (journal.path, journal.path.read_bytes())
    assert [(row.key, row.element_id) for row in results[first]] == [("camera", "II-000001"), ("movement", "UI-000001")]
    assert [(row.key, row.element_id) for row in results[second]] == [("camera", "II-000002"), ("movement", "UI-000002")]
    assert snapshots[first][0] != snapshots[second][0]
    before = database_rows(managed[0])
    for round_id in (first, second):
        with DiscoveryReservationJournal(managed[1], producer="tracker", round_operation_id=round_id) as journal:
            select(journal, managed, round_id)
            assert journal.bind(*proposal(round_id), replay_only=True) == results[round_id]
        path, raw = snapshots[round_id]
        assert path.read_bytes() == raw
    assert database_rows(managed[0]) == before
    assert managed[2].lookup(spec_id="game", element_id="UI-000001") is None


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("kind", ["UI", "II"])
def test_round_allocator_interruption_recovers_without_consuming_another_id(managed, monkeypatch, when, kind):
    round_id = "tracker-" + "a" * 32
    allocate = managed[2].reserve
    def interrupted(**request):
        if request["kind"] == kind and when == "before":
            raise Interrupted()
        result = allocate(**request)
        if request["kind"] == kind:
            raise Interrupted()
        return result
    with DiscoveryReservationJournal(managed[1], producer="tracker", round_operation_id=round_id) as journal:
        select(journal, managed, round_id, create=True)
        with monkeypatch.context() as patch:
            patch.setattr(managed[2], "reserve", interrupted)
            with pytest.raises(Interrupted):
                journal.bind(*proposal(round_id))
    with DiscoveryReservationJournal(managed[1], producer="tracker", round_operation_id=round_id) as journal:
        select(journal, managed, round_id)
        assert [row.element_id for row in journal.bind(*proposal(round_id))] == ["II-000001", "UI-000001"]
    assert managed[2].reserve(spec_id="game", kind=kind, operation_id="next", count=1) == (kind + "-000002",)


def test_round_namespace_cannot_be_retargeted_to_another_operation(managed):
    first, other = "tracker-" + "a" * 32, "tracker-" + "b" * 32
    before = database_rows(managed[0])
    with DiscoveryReservationJournal(managed[1], producer="tracker", round_operation_id=first) as journal:
        with pytest.raises(ValueError):
            select(journal, managed, other, create=True)
        assert not journal.path.exists()
    assert database_rows(managed[0]) == before


@pytest.mark.parametrize("producer,round_id", [("tracker", None), ("tracker", "../escape"),
    ("tracker", "synthesis-" + "a" * 32), ("tracker", "tracker-" + "a" * 31),
    ("tracker", "tracker-" + "A" * 32), ("tracker", False), ("discovery", "tracker-" + "a" * 32),
    ("synthesizer", "tracker-" + "a" * 32)])
def test_receipt_namespace_requires_an_explicit_canonical_tracker_round(tmp_path, producer, round_id):
    with pytest.raises(ValueError):
        DiscoveryReceiptFile(tmp_path, "discovery-turns", producer=producer, round_operation_id=round_id)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("damage", ["missing", "extra", "version", "producer", "routing_type",
    "risk", "question", "changed_reply", "revision_pair", "mutable_ids"])
def test_saved_tracker_review_rejects_malformed_or_substituted_routing(damage):
    selected = replace(assignment("review"), routing=tuple(routing("STOP_AND_ASK").items()))
    value = selected.identity()
    response = reply(selected)
    if damage == "missing": del value["routing"]
    elif damage == "extra": value["routing"]["automatic_eligible"] = True
    elif damage == "version": value["schema_version"] = 2
    elif damage == "producer": value["producer"] = "synthesizer"
    elif damage == "routing_type": value["routing"] = list(value["routing"].items())
    elif damage == "risk": value["routing"]["risk_level"] = "safe"
    elif damage == "question": value["routing"]["question"] = "\ud800"
    elif damage == "changed_reply": response["routing"]["recommended_answer"] = "Use mouse movement"
    elif damage == "revision_pair": value["editable_revisions"] = ["UI-001"]
    else: value["assigned_ids"] = {"UI-000001": True}
    receipt = dict(schema_version=1, binding={}, token_budget=100, dispatch_limit=9, steps=[dict(
        assignment=value, input_sha256="a" * 64, deadline=1, records=[dict(
            prompt_sha256="b" * 64, reply=response, read=None, token_usage=7, error=None, accepted=True)])])
    with pytest.raises(ValueError):
        _validate(receipt)


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("write_number", [1, 2, 3])
def test_round_mapping_write_interruption_preserves_exact_allocator_receipts(managed, monkeypatch, when, write_number):
    import harness.discovery_receipts as receipt_io
    round_id = "tracker-" + "a" * 32
    write, calls = receipt_io.write_text_atomic, 0
    def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == write_number and when == "before":
            raise Interrupted()
        result = write(*args, **kwargs)
        if calls == write_number:
            raise Interrupted()
        return result
    with DiscoveryReservationJournal(managed[1], producer="tracker", round_operation_id=round_id) as journal:
        select(journal, managed, round_id, create=True)
        with monkeypatch.context() as patch:
            patch.setattr(receipt_io, "write_text_atomic", interrupted)
            with pytest.raises(Interrupted):
                journal.bind(*proposal(round_id))
    with DiscoveryReservationJournal(managed[1], producer="tracker", round_operation_id=round_id) as journal:
        select(journal, managed, round_id)
        assert [row.element_id for row in journal.bind(*proposal(round_id))] == ["II-000001", "UI-000001"]
    for kind in ("UI", "II"):
        assert managed[2].reserve(spec_id="game", kind=kind, operation_id="next-" + kind, count=1) == (kind + "-000002",)


@pytest.mark.parametrize("damage", ["other_round", "missing", "forged_id", "forged_intent", "scope"])
def test_round_recovery_rejects_foreign_or_rehashed_receipts_without_allocating(managed, damage):
    first, second = "tracker-" + "a" * 32, "tracker-" + "b" * 32
    paths = []
    for round_id in (first, second):
        with DiscoveryReservationJournal(managed[1], producer="tracker", round_operation_id=round_id) as journal:
            select(journal, managed, round_id, create=True)
            journal.bind(*proposal(round_id))
            paths.append(journal.path)
    retained_first = paths[0].read_bytes()
    if damage == "other_round": paths[1].write_bytes(retained_first)
    elif damage == "missing": paths[1].unlink()
    else:
        envelope = json.loads(paths[1].read_text())
        record = envelope["payload"]["proposals"][0]
        if damage == "forged_id": record["intents"][0]["ids"] = ["II-000099"]
        elif damage == "forged_intent": record["intents"][0]["operation_id"] = "invented"
        else: record["proposal"]["artifact_paths"] = ["unknowns.md"]
        envelope["sha256"] = hashlib.sha256(json.dumps(envelope["payload"], sort_keys=True,
            separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
        paths[1].write_text(json.dumps(envelope))
    before = database_rows(managed[0])
    with DiscoveryReservationJournal(managed[1], producer="tracker", round_operation_id=second) as journal:
        with pytest.raises(ValueError):
            select(journal, managed, second)
    assert paths[0].read_bytes() == retained_first
    assert database_rows(managed[0]) == before


@pytest.mark.parametrize("foreign_producer", ["discovery", "synthesizer"])
def test_round_recovery_rejects_valid_foreign_producer_receipt(managed, foreign_producer):
    round_id = "tracker-" + "a" * 32
    with DiscoveryReservationJournal(managed[1], producer="tracker", round_operation_id=round_id) as journal:
        select(journal, managed, round_id, create=True)
        journal.bind(*proposal(round_id))
        target = journal.path
    selected = replace(managed[4], producer=foreign_producer, operation_id=round_id)
    value = {**managed[5], **selected.identity()}
    with DiscoveryReservationJournal(managed[1], producer=foreign_producer) as donor:
        select(donor, managed, round_id, create=True)
        mappings = donor.bind(selected, value)
        raw = donor.path.read_bytes()
    # The donor is a real valid journal for the same run, operation and authority,
    # with actual allocator receipts; only the producer/namespace is foreign.
    with DiscoveryReservationJournal(managed[1], producer=foreign_producer) as donor:
        select(donor, managed, round_id)
        assert donor.bind(selected, value, replay_only=True) == mappings
    target.write_bytes(raw)
    before = database_rows(managed[0])
    with DiscoveryReservationJournal(managed[1], producer="tracker", round_operation_id=round_id) as journal:
        with pytest.raises(ValueError):
            select(journal, managed, round_id)
    assert target.read_bytes() == raw
    assert database_rows(managed[0]) == before


@pytest.mark.parametrize("journal_producer,proposal_producer", [("tracker", "discovery"), ("discovery", "tracker")])
def test_reservation_journal_cannot_mix_producer_families(managed, journal_producer, proposal_producer):
    round_id = "tracker-" + "a" * 32
    selected, value = proposal(round_id) if proposal_producer == "tracker" else managed[4:]
    operation_id = round_id if journal_producer == "tracker" else "discovery"
    selected = replace(selected, operation_id=operation_id)
    value = {**value, **selected.identity()}
    before = database_rows(managed[0])
    with DiscoveryReservationJournal(managed[1], producer=journal_producer,
            round_operation_id=round_id if journal_producer == "tracker" else None) as journal:
        select(journal, managed, operation_id, create=True)
        raw = journal.path.read_bytes()
        with pytest.raises(ValueError):
            journal.bind(selected, value)
        assert journal.path.read_bytes() == raw
    assert database_rows(managed[0]) == before


def test_tracker_turn_files_retain_each_rounds_usage_and_routing(tmp_path):
    first, second = "tracker-" + "a" * 32, "tracker-" + "b" * 32
    saved = {}
    for round_id, verdict, tokens in ((first, "STOP_AND_ASK", 7), (second, "ALIGNED", 11)):
        selected = replace(assignment("review"), operation_id=round_id, routing=tuple(routing(verdict).items()))
        data = dict(schema_version=1, binding={}, token_budget=100, dispatch_limit=9, steps=[dict(
            assignment=selected.identity(), input_sha256="a" * 64, deadline=1, records=[dict(
                prompt_sha256="b" * 64, reply=reply(selected), read=None,
                token_usage=tokens, error=None, accepted=True)])])
        with DiscoveryReceiptFile(tmp_path, "discovery-turns", producer="tracker", round_operation_id=round_id) as file:
            _save(file, data)
            saved[round_id] = (file.path, file.path.read_bytes())
    assert saved[first][0] != saved[second][0]
    for round_id, verdict, tokens in ((first, "STOP_AND_ASK", 7), (second, "ALIGNED", 11)):
        with DiscoveryReceiptFile(tmp_path, "discovery-turns", producer="tracker", round_operation_id=round_id) as file:
            recovered = json.loads(file._read())["payload"]
            _validate(recovered)
            assert _usage(recovered) == dict(tokens=tokens, known=True, dispatches=1)
            assert recovered["steps"][0]["assignment"]["routing"]["verdict"] == verdict
        path, raw = saved[round_id]
        assert path.read_bytes() == raw


@pytest.mark.parametrize("producer,version", [("discovery", 1), ("synthesizer", 2)])
def test_old_assignment_codecs_stay_exact_and_cannot_absorb_round_fields(producer, version):
    from tests.unit.test_discovery_semantics import assignment as old_assignment
    selected = replace(old_assignment(), producer=producer)
    value = selected.identity()
    assert value["schema_version"] == version
    assert _assignment(deepcopy(value)).identity() == value
    for extra in ({"round_operation_id": "tracker-" + "a" * 32}, {"routing": routing()}):
        with pytest.raises(ValueError):
            _assignment({**value, **extra})
