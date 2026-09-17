"""Round selection is not dispatch authority; old Synthesis remains addressable."""
from copy import deepcopy
from dataclasses import replace

import pytest

from tests.unit.test_discovery_turns import case, enrolled
from tests.unit.test_discovery_reservations import managed, database_rows


@pytest.fixture
def retained(enrolled):
    # Pure reader fixture, not an authenticated publication or persisted state.
    state = enrolled[1].load()
    def source(digit):
        return dict(dispatch_id=digit * 32, completion_intent_sha256="1" * 64,
            completion_receipts_sha256="2" * 64, completed_publication_binding_sha256="3" * 64)
    original, repair, why1 = source("a"), source("b"), source("c")
    original_id, refresh_id = "synthesis-" + original["dispatch_id"], "synthesizer-" + repair["dispatch_id"]
    from tests.unit.test_discovery_operation import binding, result
    operation = dict(schema_version=1, binding={**binding(), "operation_id": original_id,
        "intent": dict(kind="synthesize", request="Create an isometric game")},
        attempts=[dict(number=1, result=result("accepted"))])
    state.update(managed_synthesizer_source=original, managed_synthesizer_operation=operation,
        managed_synthesizer_turns=dict(schema_version=1, operation_id=original_id, binding_sha256="d" * 64))
    from harness.discovery_repair_state import normalize_selection
    unit, claim = normalize_selection(state, dict(source=why1,
        origin=dict(review_id=why1["dispatch_id"], return_phase="phase1-why1"),
        findings=[dict(key="camera", detail="Camera needs repair")],
        artifact_paths=["unknowns.md"], editable_revisions=[["U-000001", "2"]]))
    repair_binding = {**binding(), "operation_id": "discovery-repair-" + unit,
        "artifact_paths": claim["artifact_paths"], "editable_revisions": claim["editable_revisions"],
        "unowned_writable_paths": [], "intent": dict(kind="repair", request="Repair camera",
            origin=claim["origin"], findings=claim["findings"])}
    state["managed_discovery_repairs"] = dict(schema_version=1, units={unit: dict(
        execution=dict(binding=repair_binding, turns=None),
        attempts=[dict(number=1, result={**result("accepted"), "progress_sha256": "e" * 64})], selection=claim)})
    state["managed_discovery_operation"] = dict(schema_version=1, binding=binding(),
        attempts=[dict(number=1, result=result("accepted"))])
    state["phase_dispatch_counts"] = {"phase1-discover": 2, "phase1-synthesizer": 1}
    state["managed_synthesizer_rounds"] = dict(schema_version=1, active=refresh_id, rounds={refresh_id: dict(
        source=repair, resolution=None, predecessor=original_id, operation=None, turns=None,
        refresh=dict(repair_unit=unit, repair_source=repair, predecessor_source=original))})
    return state, original_id, refresh_id


def test_active_refresh_does_not_select_or_overwrite_original_components(retained):
    from harness.discovery_producer import producer_component, producer_operation_id, with_producer_component
    from harness.discovery_operation_state import operation_from_state
    from harness.discovery_turn_state import discovery_turns_from_state
    from harness.squad_state import _synthesis_from_state
    state, original, refresh = retained
    before = deepcopy(state)
    assert producer_operation_id(state, "synthesizer") == refresh
    assert producer_operation_id(state, "synthesizer", original) == original
    assert producer_operation_id(state, "synthesizer", refresh) == refresh
    for suffix in ("operation", "turns"):
        assert producer_component(state, "synthesizer", suffix) is None
        assert producer_component(state, "synthesizer", suffix, operation_id=original) == state["managed_synthesizer_" + suffix]
        assert with_producer_component(state, "synthesizer", suffix, None) == state
    assert operation_from_state(state, "synthesizer") is None
    assert discovery_turns_from_state(state, "synthesizer") is None
    assert operation_from_state(state, "synthesizer", operation_id=original) == state["managed_synthesizer_operation"]
    assert discovery_turns_from_state(state, "synthesizer", operation_id=original) == state["managed_synthesizer_turns"]
    assert _synthesis_from_state(state) == tuple(state["managed_synthesizer_" + suffix]
        for suffix in ("source", "operation", "turns"))
    assert state == before


@pytest.mark.parametrize("operation_id", ["synthesis-" + "f" * 32, "synthesizer-" + "f" * 32, "other", False])
def test_explicit_selection_cannot_fall_back_to_original(retained, operation_id):
    from harness.discovery_producer import producer_component, producer_operation_id
    state, _, _ = retained
    with pytest.raises(ValueError): producer_operation_id(state, "synthesizer", operation_id)
    with pytest.raises(ValueError): producer_component(state, "synthesizer", "operation", operation_id=operation_id)


@pytest.mark.parametrize("origin", ["why1", "why2"])
@pytest.mark.parametrize("producer", ["synthesizer", "tracker", "why1"])
def test_refresh_distinguishes_requesting_review_from_prior_producer(retained, origin, producer):
    from harness.discovery_producer import validate_refresh_round
    from tests.unit.test_why1_tracker_parent import row, source
    state, original, refresh = retained
    selected = deepcopy(state["managed_synthesizer_rounds"]["rounds"][refresh])
    unit = selected["refresh"]["repair_unit"]
    repair = state["managed_discovery_repairs"]["units"][unit]
    repair["selection"]["origin"]["return_phase"] = "phase1-" + origin
    repair["execution"]["binding"]["intent"]["origin"] = deepcopy(repair["selection"]["origin"])
    if producer != "synthesizer":
        digit = "c" if producer == "why1" and origin == "why1" else "d"
        predecessor = producer + "-" + digit * 32
        state["managed_" + producer + "_rounds"] = dict(schema_version=1, active=predecessor,
            rounds={predecessor: row(digit, producer)})
        selected["predecessor"] = predecessor
        selected["refresh"]["predecessor_source"] = source(digit)
    before = deepcopy(state)
    validate_refresh_round(state, producer, selected)
    assert state == before
    repair["selection"]["origin"]["review_id"] = "f" * 32
    with pytest.raises(ValueError):
        validate_refresh_round(state, producer, selected)
    repair["selection"]["origin"]["review_id"] = repair["selection"]["source"]["dispatch_id"]
    repair["selection"]["origin"]["return_phase"] = "phase3-consensus"
    with pytest.raises(ValueError):
        validate_refresh_round(state, producer, selected)


def test_original_selection_without_refresh_is_unchanged(retained):
    from harness.discovery_producer import producer_operation_id, producer_component
    state, original, _ = retained
    del state["managed_synthesizer_rounds"]
    assert producer_operation_id(state, "synthesizer") == original
    assert producer_component(state, "synthesizer", "operation") == state["managed_synthesizer_operation"]


@pytest.mark.parametrize("count", [0, 1, 2])
def test_admission_counts_original_synthesis_not_empty_refresh(retained, enrolled, monkeypatch, count):
    from tests.unit.test_discovery_normal_entry import controller, selection, FullDiscoveryExecutor
    state, _, _ = retained
    state["phase_dispatch_counts"]["phase1-synthesizer"] = count
    ctrl = controller(enrolled, FullDiscoveryExecutor())
    monkeypatch.setattr(enrolled[1], "load", lambda: deepcopy(state))
    if count == 1:
        ctrl._admit_managed_discovery({**selection(enrolled), "through_phase": "phase1-why1"}, False)
    else:
        with pytest.raises(ValueError, match="synthesis|Synthesis"):
            ctrl._admit_managed_discovery({**selection(enrolled), "through_phase": "phase1-why1"}, False)


def test_empty_refresh_usage_does_not_read_original_receipts(retained, tmp_path):
    from harness.discovery_turns import read_discovery_usage
    from harness.discovery_receipts import DiscoveryReceiptFile
    state, _, refresh = retained
    class Store:
        squad_dir = tmp_path
        def load(self): return deepcopy(state)
    original = tmp_path / "synthesizer-turns.json"
    original.write_text("Original receipt must not be read or repaired.\n")
    assert read_discovery_usage(Store(), "synthesizer") == dict(token_usage=0, dispatch_count=0)
    with DiscoveryReceiptFile(tmp_path, "discovery-turns", producer="synthesizer", round_operation_id=refresh) as file:
        assert file._read() is None
        file._write("Damaged selected refresh receipt\n")
    assert read_discovery_usage(Store(), "synthesizer") == dict(token_usage=None, dispatch_count=0)
    assert original.read_text() == "Original receipt must not be read or repaired.\n"


def test_refresh_receipts_and_allocations_do_not_replace_original(managed):
    from harness.discovery_receipts import receipt_round_operation_id
    from harness.discovery_reservations import DiscoveryReservationJournal
    original, first, second = "synthesis-" + "a" * 32, "synthesizer-" + "b" * 32, "synthesizer-" + "c" * 32
    snapshots, mappings = {}, {}
    def proposal(operation_id):
        assigned = replace(managed[4], producer="synthesizer", operation_id=operation_id)
        return assigned, {**managed[5], **assigned.identity()}
    def journal(operation_id):
        return DiscoveryReservationJournal(managed[1], producer="synthesizer",
            round_operation_id=receipt_round_operation_id("synthesizer", operation_id))
    def select(opened, operation_id, create=False):
        opened.select(managed[2], spec_id="game", run_id="first", operation_id=operation_id,
            managed_identity=managed[3], create=create)
    for operation_id in (original, first, second):
        with journal(operation_id) as opened:
            select(opened, operation_id, True)
            mappings[operation_id] = opened.bind(*proposal(operation_id))
            snapshots[operation_id] = (opened.path, opened.path.read_bytes())
    assert len({path for path, _ in snapshots.values()}) == 3
    assert snapshots[original][0].name == "synthesizer-reservations.json"
    assert [row.element_id for row in mappings[first]] == ["A-000002", "U-000003", "U-000004"]
    assert [row.element_id for row in mappings[second]] == ["A-000003", "U-000005", "U-000006"]
    before = database_rows(managed[0])
    for operation_id in (original, first, second):
        with journal(operation_id) as opened:
            select(opened, operation_id)
            assert opened.bind(*proposal(operation_id), replay_only=True) == mappings[operation_id]
        path, raw = snapshots[operation_id]
        assert path.read_bytes() == raw
    with journal(first) as opened:
        with pytest.raises(ValueError): select(opened, second)
    assert database_rows(managed[0]) == before


@pytest.mark.parametrize("operation_id", ["synthesis-" + "a" * 32, "synthesizer-" + "a" * 31,
    "synthesizer-" + "A" * 32, "tracker-" + "a" * 32, "../escape", False])
def test_refresh_receipt_namespace_rejects_noncanonical_round(tmp_path, operation_id):
    from harness.discovery_receipts import DiscoveryReceiptFile
    with pytest.raises(ValueError):
        DiscoveryReceiptFile(tmp_path, "discovery-turns", producer="synthesizer", round_operation_id=operation_id)
    assert not list(tmp_path.iterdir())
