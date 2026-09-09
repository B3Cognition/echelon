"""Per-issue closure is independent of the aggregate consensus verdict."""
from dataclasses import asdict

import pytest

from harness.phase3_repair import RepairIdentity, validate_issue_review
from harness.squad_state import SquadStateStore


def setup_review(tmp_path, outcome="resolved"):
    store = SquadStateStore(tmp_path / "run")
    store.initialize("r", "greenfield", "task", 0, "phase3-consensus")
    identity = RepairIdentity("r", "f" * 64, 7)
    state = store.load()
    state.update({"why3_verdict": "FAIL", "selected_issue_resolution": "ISS-A",
        "issue_resolution_ledger": {"ISS-A": {
            "status": "repaired", "repair_identity": asdict(identity),
            "repair_phase": "phase3-how",
        }}, "issue_resolution_repair_baseline": {"issue_id": "ISS-A"}})
    store.save(state)
    manifest = {"data-model.md": "a" * 64}
    review = validate_issue_review({"schema_version": 1, "identity": asdict(identity),
        "outcome": outcome, "reviewed_artifacts": manifest, "rationale": "Checked selected transition."},
        expected=identity, expected_manifest=manifest)
    return store, review, manifest


def test_closes_one_issue_with_aggregate_fail_and_survives_restart(tmp_path):
    store, review, manifest = setup_review(tmp_path)
    snapshot = store.capture_routing_snapshot()
    assert store.commit_phase3_issue_review(snapshot=snapshot, review_dispatch_id="review-1", review=review, input_manifest=manifest)
    state = SquadStateStore(tmp_path / "run").load()
    assert state["issue_resolution_ledger"]["ISS-A"]["status"] == "validated"
    assert state["selected_issue_resolution"] is None
    assert state["why3_verdict"] == "FAIL"
    assert state["phase"] == "phase3-consensus"
    assert state["issue_resolution_repair_baseline"] is None
    assert len(state["phase3_issue_reviews"]) == 1
    assert not store.commit_phase3_issue_review(snapshot=snapshot, review_dispatch_id="review-1", review=review, input_manifest=manifest)
    assert len(store.load()["phase3_issue_reviews"]) == 1


@pytest.mark.parametrize("change", ["revision", "identity", "manifest"])
def test_rejects_stale_review_without_clearing_selection(tmp_path, change):
    store, review, manifest = setup_review(tmp_path)
    snapshot = store.capture_routing_snapshot()
    if change == "revision":
        state = store.load()
        state["user_message"] = "new task input"
        store.save(state)
    elif change == "identity":
        state = store.load()
        state["issue_resolution_ledger"]["ISS-A"]["repair_identity"]["issue_fingerprint"] = "b" * 64
        store.save(state)
        snapshot = store.capture_routing_snapshot()
    else:
        manifest = {"data-model.md": "c" * 64}
    assert not store.commit_phase3_issue_review(snapshot=snapshot, review_dispatch_id="review-1", review=review, input_manifest=manifest)
    assert store.load()["selected_issue_resolution"] == "ISS-A"


@pytest.mark.parametrize("outcome", ["unresolved", "unverifiable"])
def test_non_closure_review_retains_selection_and_fail(tmp_path, outcome):
    store, review, manifest = setup_review(tmp_path, outcome)
    assert store.commit_phase3_issue_review(snapshot=store.capture_routing_snapshot(), review_dispatch_id="review-1", review=review, input_manifest=manifest)
    state = store.load()
    assert state["selected_issue_resolution"] == "ISS-A"
    assert state["issue_resolution_ledger"]["ISS-A"]["status"] == "repaired"
    assert state["why3_verdict"] == "FAIL"


def test_aggregate_pass_without_explicit_receipt_cannot_close_legacy_selection(tmp_path):
    from types import SimpleNamespace
    from harness.squad import SquadController
    store, _, _ = setup_review(tmp_path)
    state = store.load()
    state["why3_verdict"] = "PASS"
    state["issue_resolution_repair_baseline"]["repair_phase"] = "phase3-how"
    del state["issue_resolution_ledger"]["ISS-A"]["repair_identity"]
    controller = object.__new__(SquadController)
    updates = controller._coordinate_selected_issue_repair_updates(
        SimpleNamespace(id="phase3-consensus"), SimpleNamespace(verdict="PASS"), SimpleNamespace(state=state))
    assert updates == {}


def test_final_candidate_revalidation_claim_is_durable_and_identity_bound(tmp_path):
    store, review, manifest = setup_review(tmp_path)
    assert store.claim_phase3_revalidation(snapshot=store.capture_routing_snapshot(),
        identity=review.identity, input_manifest=manifest)
    restarted = SquadStateStore(tmp_path / "run")
    assert not restarted.claim_phase3_revalidation(snapshot=restarted.capture_routing_snapshot(),
        identity=review.identity, input_manifest=manifest)
    assert restarted.claim_phase3_revalidation(snapshot=restarted.capture_routing_snapshot(),
        identity=review.identity, input_manifest={"data-model.md": "b" * 64})
