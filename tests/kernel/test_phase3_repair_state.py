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
    assert state["issue_resolution_ledger"]["ISS-A"]["submission_count"] == 1
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


def test_two_independently_reviewed_submissions_stop_without_reset_on_restart(tmp_path):
    from harness.phase3_repair_routing import phase3_work_route
    store, review, manifest = setup_review(tmp_path, "unresolved")
    for submission in (1, 2):
        state = store.load()
        state["autonomy_mode"] = "banzai"
        state["issue_resolution_ledger"]["ISS-A"]["submission_count"] = submission
        store.save(state)
        assert store.commit_phase3_issue_review(snapshot=store.capture_routing_snapshot(),
            review_dispatch_id=f"review-{submission}", review=review, input_manifest=manifest)
        # A second review of the same submission must not count as a new repair.
        assert store.commit_phase3_issue_review(snapshot=store.capture_routing_snapshot(),
            review_dispatch_id=f"revalidation-{submission}", review=review, input_manifest=manifest)
        store = SquadStateStore(tmp_path / "run")
        assert store.load()["issue_resolution_ledger"]["ISS-A"]["reviewed_unresolved_count"] == submission
        route, updates = phase3_work_route(store.load(), manifest)
        if submission == 1:
            assert route == "phase3-how"
        else:
            assert route == "terminal-blocked"
            assert updates["blocked_reason"] == "repair_no_progress"
            assert store.load()["why3_verdict"] == "FAIL"
            assert store.load()["selected_issue_resolution"] == "ISS-A"


def test_later_artifact_change_requires_review_not_repeating_old_work(tmp_path):
    store, review, manifest = setup_review(tmp_path)
    assert store.commit_phase3_issue_review(snapshot=store.capture_routing_snapshot(),
        review_dispatch_id="review", review=review, input_manifest=manifest)
    changed = {"data-model.md": "c" * 64}
    assert store.reconcile_phase3_review_inputs(snapshot=store.capture_routing_snapshot(), input_manifest=changed)
    current = store.load()
    assert current["selected_issue_resolution"] == "ISS-A"
    assert current["issue_resolution_ledger"]["ISS-A"]["status"] == "repaired"
    assert current["issue_resolution_ledger"]["ISS-A"]["review_revalidation_required"] is True
    assert current["phase3_issue_reviews"]["review"]["reviewed_artifacts"] == manifest


def test_reused_display_label_cannot_hide_stale_historical_closure(tmp_path):
    from harness.issue_identity import record_issue_resolution, matching_issue_resolution
    store, review, manifest = setup_review(tmp_path)
    state = store.load()
    state["issue_resolution_ledger"]["ISS-A"]["issue_fingerprint"] = "f" * 64
    store.save(state)
    assert store.commit_phase3_issue_review(snapshot=store.capture_routing_snapshot(),
        review_dispatch_id="old", review=review, input_manifest=manifest)
    state = store.load()
    changed = {"data-model.md": "c" * 64}
    state["phase3_issue_reviews"]["new"] = {"reviewed_artifacts": changed}
    state["issue_resolution_ledger"] = record_issue_resolution(state["issue_resolution_ledger"], "ISS-A",
        {"issue_fingerprint": "b" * 64, "status": "validated", "repair_phase": "phase3-how",
         "repair_identity": asdict(RepairIdentity("r", "b" * 64, 8)), "last_review_dispatch_id": "new"})
    store.save(state)
    assert store.reconcile_phase3_review_inputs(snapshot=store.capture_routing_snapshot(), input_manifest=changed)
    current = store.load()
    assert matching_issue_resolution(current["issue_resolution_ledger"], "f" * 64).get("status") != "validated"
    selected = current["issue_resolution_ledger"][current["selected_issue_resolution"]]
    assert selected["repair_identity"] == asdict(review.identity)
    assert selected["status"] == "repaired"
    assert matching_issue_resolution(current["issue_resolution_ledger"], "b" * 64)["status"] == "validated"


def test_pre_upgrade_aggregate_closure_requires_fresh_independent_review(tmp_path):
    store, _, manifest = setup_review(tmp_path)
    state = store.load()
    state["selected_issue_resolution"] = None
    entry = state["issue_resolution_ledger"]["ISS-A"]
    entry.update(status="validated", title="Legacy repair", issue_fingerprint="a" * 64)
    entry.pop("repair_identity")
    store.save(state)
    assert store.reconcile_phase3_review_inputs(snapshot=store.capture_routing_snapshot(), input_manifest=manifest)
    current = store.load()
    assert current["selected_issue_resolution"] == "ISS-A"
    assert current["issue_resolution_ledger"]["ISS-A"]["status"] == "repaired"
    assert current["issue_resolution_ledger"]["ISS-A"]["repair_identity"]["issue_fingerprint"] == "a" * 64
