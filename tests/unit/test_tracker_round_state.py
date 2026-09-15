"""Closed Tracker selectors reject malformed history without granting authority."""
import pytest
from tests.unit.test_discovery_turns import case, enrolled
from harness.discovery_producer import tracker_rounds


def test_round_reader_rejects_multiple_roots(enrolled):
    state = enrolled[1].load()
    rounds = {}
    for digit in ("a", "b"):
        source = dict(dispatch_id=digit * 32, completion_intent_sha256="1" * 64,
            completion_receipts_sha256="2" * 64, completed_publication_binding_sha256="3" * 64)
        rounds["tracker-" + digit * 32] = dict(source=source, resolution=None, predecessor=None, operation=None, turns=None)
    state["managed_tracker_rounds"] = dict(schema_version=1, active="tracker-" + "b" * 32, rounds=rounds)
    with pytest.raises(ValueError):
        tracker_rounds(state)


def test_tracker_progress_includes_reviewed_question():
    from harness.discovery_operation import _progress
    artifacts = {"user-intent.md": "UI-000001 movement", "stakeholder-model.md": None}
    first = dict(verdict="STOP_AND_ASK", question="Which controls?", recommended_answer=None, risk_level=None)
    assert _progress(artifacts, [], routing=first) != _progress(artifacts, [], routing={**first, "question": "Keyboard or touch?"})
