"""Clarification order is the native source chain, never timestamps or prose."""
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from tests.unit.test_why1_tracker_parent import resolved


def clarification(digit, producer, previous=(), version=None):
    from harness.clarification_candidate import ClarificationRecord
    decision = resolved(digit, "Question " + digit, "Answer " + digit, producer)["decision"]
    record = ClarificationRecord(decision["id"], decision["question"], decision["answer_text"])
    return SimpleNamespace(producer=producer, recovery=dict(
        version=version if version is not None else {"tracker": 5, "why1": 7, "why2": 18}[producer],
        resolution=decision, previous=[asdict(item) for item in previous])), record


def test_history_includes_exact_chronological_prefix_and_pending_answer():
    from harness.tracker_clarification import validate_clarification_history
    first, a = clarification("a", "tracker")
    second, b = clarification("b", "why1", (a,))
    third, c = clarification("c", "why2", (a, b))
    fourth, d = clarification("d", "tracker", (a, b, c), version=18)
    assert validate_clarification_history((third, second, first)) == (a, b, c)
    assert validate_clarification_history((third, second, first), pending=fourth) == (a, b, c, d)


@pytest.mark.parametrize("damage", ["omitted", "reordered", "altered", "duplicate", "self", "producer", "unresolved"])
def test_history_rejects_gaps_substitution_duplicates_and_invalid_resolutions(damage):
    from harness.tracker_clarification import validate_clarification_history
    first, a = clarification("a", "tracker")
    second, b = clarification("b", "why1", (a,))
    third, c = clarification("c", "why2", (a, b))
    if damage == "omitted":
        third.recovery["previous"] = [asdict(b)]
    elif damage == "reordered":
        third.recovery["previous"].reverse()
    elif damage == "altered":
        third.recovery["previous"][0]["answer"] = "Substituted"
    elif damage == "duplicate":
        third.recovery["resolution"] = first.recovery["resolution"]
        third.producer = "tracker"
    elif damage == "self":
        third.recovery["previous"].append(asdict(c))
    elif damage == "producer":
        third.producer = "what"
    else:
        third.recovery["resolution"]["status"] = "awaiting_human"
    with pytest.raises(ValueError):
        validate_clarification_history((second, first), pending=third)


@pytest.mark.parametrize("damage", [None, "source", "request", "unreleased", "cycle", "root", "unsupported"])
def test_nondecoding_history_walk_requires_exact_native_proofs(monkeypatch, damage):
    """Only native proof validation is stubbed; request codecs and records are real."""
    from harness.tracker_clarification import retained_clarification_records
    from harness.element_identity_publication import PublicationIntentRequest, encode_publication_request
    from harness.discovery_completion import _json
    from tests.unit.test_why1_tracker_parent import source
    import harness.squad_completion as completion
    first, a = clarification("b", "tracker")
    second, b = clarification("d", "why2", (a,))
    values = {
        "a": dict(version=2, completion_id="a" * 32),
        "b": dict(first.recovery, producer="tracker", completion_id="b" * 32, source_completion=source("a")),
        "c": dict(version=15, producer="why2", completion_id="c" * 32, source_completion=source("b")),
        "d": dict(second.recovery, producer="why2", completion_id="d" * 32, source_completion=source("c")),
    }
    if damage == "cycle":
        values["a"]["source_completion"] = source("d")
    elif damage == "root":
        values["a"].update(version=15, producer="why2")
    elif damage == "unsupported":
        values["c"]["version"] = 999
    rows, seen = {}, []
    for digit, recovery in values.items():
        request = encode_publication_request(PublicationIntentRequest("f" * 64, _json(recovery)))
        intent = dict(publication=dict(managed_discovery=dict(version=1, request=request)),
            origin="resolution" if digit in "bd" else "routed", route=dict(decision_id=recovery.get("resolution", {}).get("id")))
        rows["discovery-completion-" + digit * 32] = dict(state="released", request=request,
            completion_payload=_json(dict(version=3, completion=source(digit), proof=dict(intent=intent, receipts={}))))
    if damage == "unreleased":
        rows["discovery-completion-" + "c" * 32]["state"] = "applied"
    elif damage == "request":
        rows["discovery-completion-" + "c" * 32]["request"] = rows["discovery-completion-" + "a" * 32]["request"]
    def validate(marker, intent, receipts):
        seen.append(marker["dispatch_id"])
        return (SimpleNamespace(completion_id=marker["dispatch_id"], intent_sha256=marker["completion_intent_sha256"],
            receipts_sha256=marker["completion_receipts_sha256"], publication_binding_sha256=marker["completed_publication_binding_sha256"]),
            SimpleNamespace(**intent), receipts)
    monkeypatch.setattr(completion, "validate_retained_completion_proof", validate)
    store = SimpleNamespace(identity_publication=lambda **kwargs: rows.get(kwargs["operation_id"]))
    selected = source("d")
    if damage == "source":
        selected["completion_receipts_sha256"] = "9" * 64
    if damage is None:
        assert retained_clarification_records(store, spec_id="game", source=selected) == (a, b)
        assert seen == [digit * 32 for digit in "dcba"]
    else:
        with pytest.raises(ValueError):
            retained_clarification_records(store, spec_id="game", source=selected)


@pytest.mark.parametrize("damage", ["extra", "schema", "missing", "digest", "completion", "decision"])
def test_clarification_source_requires_closed_canonical_receipt(damage):
    from harness.discovery_spec import clarification_source
    receipt = resolved("a", "Which audience?", "Single player", "why2")["completion"]
    if damage == "extra": receipt["other"] = "unbound"
    elif damage == "schema": receipt["schema_version"] = True
    elif damage == "missing": del receipt["decision_id"]
    elif damage == "digest": receipt["receipts_sha256"] = "A" * 64
    elif damage == "completion": receipt["completion_id"] = "../escape"
    else: receipt["decision_id"] = ""
    with pytest.raises(ValueError):
        clarification_source(receipt)


@pytest.mark.parametrize("producer", ["what", "why2"])
@pytest.mark.parametrize("current_head", [True, False])
def test_specification_source_uses_answer_only_when_it_is_the_actual_head(monkeypatch, producer, current_head):
    from harness.discovery_spec import current_spec_source, clarification_source
    from harness.element_identity_store import IdentityStore
    from tests.unit.test_why1_tracker_parent import source
    answer = resolved("c", "Is deployment required?", "No deployment.", "why2")
    state = dict(last_dispatch=dict(source("b"), phase_id="phase1-why2"), blocked_decision=answer["decision"],
        last_human_input_completion=answer["completion"], managed_identity={"spec_id": "game"}, run_id="first")
    head = "discovery-completion-" + ("c" if current_head else "b") * 32
    monkeypatch.setattr(IdentityStore, "open", lambda root: SimpleNamespace(
        check_managed_context=lambda **kwargs: {"source_context": {"operation_id": head}}))
    assert current_spec_source("unused", state, producer) == (clarification_source(answer["completion"])
        if current_head else source("b"))


@pytest.mark.parametrize("producer", ["tracker", "why1", "why2"])
def test_later_upstream_answer_preserves_why2_history_from_native_chain(monkeypatch, producer):
    import harness.tracker_clarification as module
    _, a = clarification("a", "tracker")
    _, b = clarification("b", "why2", (a,))
    association = resolved("b", "Question b", "Answer b", "why2")
    monkeypatch.setattr(module, "previous_records", lambda *args: (a,))
    monkeypatch.setattr(module, "_resolution_rows", lambda state, owner: (({}, association),) if owner == "why2" else ())
    assert module.capture_clarification_history({}, "operation", producer, (a, b)) == (18, (a, b))


@pytest.mark.parametrize("producer,version", [("tracker", 5), ("why1", 7)])
def test_original_answer_history_does_not_silently_change_decoder(monkeypatch, producer, version):
    import harness.tracker_clarification as module
    _, a = clarification("a", "tracker")
    monkeypatch.setattr(module, "previous_records", lambda *args: (a,))
    monkeypatch.setattr(module, "_resolution_rows", lambda *args: ())
    assert module.capture_clarification_history({}, "operation", producer, (a,)) == (version, (a,))
    with pytest.raises(ValueError):
        module.capture_clarification_history({}, "operation", producer, ())
