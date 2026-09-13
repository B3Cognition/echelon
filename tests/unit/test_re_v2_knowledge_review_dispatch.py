"""Offline review dispatch over a real producer acquisition and shared account."""
from __future__ import annotations

import importlib
import json

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_discovery import DiscoveryError
from harness.re_v2.protocol_22.provider import DispatchReservationV1, NormalizedUsageV1
from tests.unit.test_re_v2_knowledge_dispatch import Crash, _controller


REVIEW_AGENT = b"Neutral independent discovery review role"
REVIEW_RESERVATION = DispatchReservationV1(100_000, 100_000, 10_000)


def _valid_review(context: dict, verdict: str = "revise") -> bytes:
    evidence = context["safe_discovery_context"]["evidence"][0]["projection_id"]
    revise = verdict == "revise"
    inventory = []
    for candidate in context["candidate"]["inventory"]:
        owned = candidate["owner"] == "runner"
        inventory.append({
            "path": candidate["path"],
            "owner": candidate["owner"],
            "disposition": "owned" if owned else "needs-assignment",
            "rationale": ("The entry point is supplied." if owned
                          else "Worker behavior has not yet been assigned."),
            "evidence_ids": [evidence] if owned else [],
        })
    return canonical_json_bytes({
        "schema_version": 1,
        "kind": "discovery_review",
        "proposal_id": context["candidate_id"],
        "verdict": verdict,
        "domains": [{
            "key": "execution",
            "verdict": "supported",
            "rationale": "The entry point executes a command.",
            "evidence_ids": [evidence],
        }],
        "subjects": [{
            "key": "runner",
            "verdict": "supported",
            "rationale": "The supplied entry point supports this subject.",
            "evidence_ids": [evidence],
        }],
        "inventory": inventory,
        "overlaps": [],
        "findings": ([{
            "target": "source",
            "reason_class": "ownership",
            "rationale": "Inspect and assign worker.py before planning.",
            "evidence_ids": [],
        }] if revise else []),
    })


def _reviewer(producer, account, calls, *, fault=None, backend=None,
              agent=REVIEW_AGENT, reservation=REVIEW_RESERVATION):
    module = importlib.import_module("harness.re_v2.knowledge_review_dispatch")

    def execute(agent_bytes, context_bytes, reserved):
        assert account.status().open_tokens == reserved.billable_tokens
        context = json.loads(context_bytes)
        calls.append((agent_bytes, context, reserved))
        output = backend(context) if backend is not None else _valid_review(context)
        return importlib.import_module("harness.re_v2.knowledge_dispatch").ProviderReply(
            output, NormalizedUsageV1("unavailable", None, {}),
        )

    execute.contract_id = account.opening["provider_contract_id"]
    return module.DiscoveryReviewController(
        producer, agent, execute, reservation, fault_hook=fault,
    )


def _reserved_review_request(producer, account, agent=REVIEW_AGENT,
                             reservation=REVIEW_RESERVATION):
    state = account.ledger.replay()
    source = producer.acquisition.opening["evidence_scope"]["source_id"]
    producer_id = state.discovery_sources[source][-1]
    producer_request = state.dispatches[producer_id]
    producer_result = state.applied[producer_id]
    boundary = importlib.import_module(
        "harness.re_v2.knowledge_discovery_review"
    ).DiscoveryReviewBoundary(producer.acquisition.boundary)
    context = boundary.provider_bytes(
        producer_request["binding_id"], producer_result["receipt_id"],
    )
    account.objects.put_blob(agent)
    account.objects.put_blob(context)
    return {
        "source_id": source,
        "scope_id": producer_request["scope_id"],
        "agent_id": content_digest(agent),
        "binding_id": producer_request["binding_id"],
        "revision_id": producer_result["revision_id"],
        "context_id": content_digest(context),
        "reservation": {
            "initial_input_tokens": reservation.initial_input_tokens,
            "billable_tokens": reservation.billable_tokens,
            "active_ms": reservation.active_ms,
        },
        "turn": len(state.sources[source]) + 1,
        "producer_dispatch_id": producer_id,
        "proposal_receipt_id": producer_result["receipt_id"],
    }


@pytest.mark.unit
def test_review_uses_shared_account_and_only_review_context_once(tmp_path):
    producer, account, phase, producer_calls = _controller(tmp_path)
    proposal = producer.step()
    assert proposal.state == "proposal_ready"
    before = account.status().charged_tokens
    review_calls = []
    reviewer = _reviewer(producer, account, review_calls)

    result = reviewer.step()

    assert result.state == "revision_required"
    assert result.reason_code is None
    assert account.status().charged_tokens == before + 100_000
    assert reviewer.step() == result
    assert len(producer_calls) == 1
    assert len(review_calls) == 1
    agent, context, reservation = review_calls[0]
    assert agent == REVIEW_AGENT
    assert reservation == REVIEW_RESERVATION
    assert context["kind"] == "untrusted_discovery_review_context"
    assert "origin_obligation_id" not in context
    boundary = importlib.import_module(
        "harness.re_v2.knowledge_discovery_review"
    ).DiscoveryReviewBoundary(phase.boundary)
    receipt = boundary.read_review(
        phase.status().binding_id, proposal.receipt_id, result.receipt_id,
    )
    assert receipt["outcome"] == "revision_required"
    assert receipt["execution_certification_required"] is True
    assert receipt["analysis_certified"] is False
    assert producer.step() == proposal


@pytest.mark.unit
def test_revision_receipt_authorizes_one_replacement_and_fresh_review(tmp_path):
    def replacement(context_bytes):
        context = json.loads(context_bytes)
        if (
            context["kind"] == "untrusted_discovery_context"
            and len(context["evidence"]) == 1
        ):
            return importlib.import_module(
                "tests.unit.test_re_v2_knowledge_dispatch"
            )._evidence(context_bytes)
        safe = context.get("safe_discovery_context", context)
        proposal = importlib.import_module(
            "tests.unit.test_re_v2_knowledge_discovery"
        )._proposal(safe)
        if context["kind"] == "untrusted_discovery_review_revision_context":
            proposal["subjects"][0]["evidence_ids"] = [
                row["projection_id"] for row in safe["evidence"]
            ]
            for row in proposal["inventory"]:
                row["owner"] = "runner"
                row["reason"] = "The complete evidence assigns this path."
        return canonical_json_bytes(proposal)

    producer, account, _, producer_calls = _controller(
        tmp_path,
        tokens=700_000,
        turns=6,
        review_revisions=1,
        backend=replacement,
    )
    evidence = producer.step()
    first = producer.step()
    review_calls = []
    first_review = _reviewer(producer, account, review_calls).step()

    replacement_result = producer.step()

    def ready_review(context):
        payload = json.loads(_valid_review(context, verdict="ready"))
        by_path = {
            row["projection"]["path"]: row["projection_id"]
            for row in context["safe_discovery_context"]["evidence"]
        }
        for row in payload["inventory"]:
            row["evidence_ids"] = [by_path[row["path"]]]
        return canonical_json_bytes(payload)

    ready_reviewer = _reviewer(
        producer,
        account,
        review_calls,
        backend=ready_review,
    )
    second_review = ready_reviewer.step()

    assert evidence.state == "evidence_ready"
    assert first.state == "proposal_ready"
    assert first_review.state == "revision_required"
    assert replacement_result.state == "proposal_ready"
    assert second_review.state == "review_ready", second_review
    assert [row["kind"] for row in producer_calls] == [
        "untrusted_discovery_context",
        "untrusted_discovery_context",
        "untrusted_discovery_review_revision_context",
    ]
    assert len(review_calls) == 2
    assert account.status().charged_tokens == 500_000


@pytest.mark.unit
def test_review_revision_limit_closes_before_another_provider_call(tmp_path):
    def replacement(context_bytes):
        context = json.loads(context_bytes)
        safe = context.get("safe_discovery_context", context)
        return canonical_json_bytes(importlib.import_module(
            "tests.unit.test_re_v2_knowledge_discovery"
        )._proposal(safe))

    producer, account, _, producer_calls = _controller(
        tmp_path,
        tokens=600_000,
        turns=6,
        review_revisions=1,
        backend=replacement,
    )
    assert producer.step().state == "proposal_ready"
    review_calls = []
    assert _reviewer(producer, account, review_calls).step().state == "revision_required"
    assert producer.step().state == "proposal_ready"
    assert _reviewer(producer, account, review_calls).step().state == "revision_required"

    result = producer.step()

    assert result.reason_code == "discovery-review-revision-limit"
    assert len(producer_calls) == 2
    assert len(review_calls) == 2
    assert account.status().charged_tokens == 400_000


@pytest.mark.unit
def test_invalid_review_gets_one_bounded_deterministic_repair(tmp_path):
    producer, account, _, _ = _controller(
        tmp_path, tokens=400_000, turns=4, review_repairs=1
    )
    assert producer.step().state == "proposal_ready"
    calls = []

    def backend(context):
        if context["kind"] == "untrusted_discovery_review_context":
            payload = json.loads(_valid_review(context))
            payload["subjects"][0]["evidence_ids"] = ["sha256:" + "f" * 64]
            return canonical_json_bytes(payload)
        assert context["kind"] == "untrusted_discovery_review_repair_context"
        assert context["deterministic_feedback"]["reason_code"] == (
            "invalid-discovery-review-evidence"
        )
        return _valid_review(context["safe_review_context"])

    reviewer = _reviewer(producer, account, calls, backend=backend)

    first = reviewer.step()
    repaired = reviewer.step()

    assert first.state == "review_repair_ready"
    assert repaired.state == "revision_required"
    assert [row[1]["kind"] for row in calls] == [
        "untrusted_discovery_review_context",
        "untrusted_discovery_review_repair_context",
    ]
    assert account.status().charged_tokens == 300_000


@pytest.mark.unit
def test_review_repair_limit_closes_before_third_reviewer_call(tmp_path):
    producer, account, _, _ = _controller(
        tmp_path, tokens=500_000, turns=5, review_repairs=1
    )
    assert producer.step().state == "proposal_ready"
    calls = []

    def invalid(context):
        base = context.get("safe_review_context", context)
        payload = json.loads(_valid_review(base))
        payload["subjects"][0]["evidence_ids"] = ["sha256:" + "f" * 64]
        return canonical_json_bytes(payload)

    reviewer = _reviewer(producer, account, calls, backend=invalid)
    assert reviewer.step().state == "review_repair_ready"
    assert reviewer.step().state == "review_repair_ready"

    result = reviewer.step()

    assert result.reason_code == "discovery-review-repair-limit"
    assert len(calls) == 2
    assert account.status().charged_tokens == 300_000


@pytest.mark.unit
@pytest.mark.parametrize(
    ("tokens", "turns", "reason"),
    [(150_000, 3, "budget-exhausted"), (500_000, 1, "discovery-turn-limit")],
)
def test_shared_ceiling_refuses_review_before_provider_call(tmp_path, tokens, turns, reason):
    producer, account, _, _ = _controller(tmp_path, tokens=tokens, turns=turns)
    assert producer.step().state == "proposal_ready"
    calls = []

    result = _reviewer(producer, account, calls).step()

    assert result == importlib.import_module(
        "harness.re_v2.knowledge_dispatch"
    ).DiscoveryStep("blocked", reason_code=reason)
    assert calls == []
    assert account.status().charged_tokens == 100_000


@pytest.mark.unit
def test_review_requires_a_ledger_committed_terminal_producer(tmp_path):
    producer, account, phase, _ = _controller(tmp_path)
    # Passive admission is a real readable proposal but grants no dispatch authority.
    context = json.loads(phase.provider_bytes())
    passive = phase.boundary.admit(
        phase.status().binding_id,
        canonical_json_bytes(importlib.import_module(
            "tests.unit.test_re_v2_knowledge_discovery"
        )._proposal(context)),
    )
    assert phase.boundary.read_proposal(phase.status().binding_id, passive)
    calls = []

    result = _reviewer(producer, account, calls).step()

    assert result.reason_code == "discovery-review-proposal-required"
    assert calls == []
    assert account.status().charged_tokens == 0


@pytest.mark.unit
def test_review_agent_must_be_distinct_from_the_producer(tmp_path):
    producer, account, _, _ = _controller(tmp_path)
    producer.step()
    with pytest.raises(DiscoveryError, match="discovery-review-agent-not-distinct"):
        _reviewer(producer, account, [], agent=producer.agent_bytes)


@pytest.mark.unit
@pytest.mark.parametrize("point", ["review_reserved", "dispatch_captured", "review_applied"])
def test_review_recovery_never_duplicates_the_provider_call(tmp_path, point):
    producer, account, _, _ = _controller(tmp_path)
    producer.step()
    calls = []

    def fault(name):
        if name == point:
            raise Crash()

    reviewer = _reviewer(producer, account, calls, fault=fault)
    with pytest.raises(Crash):
        reviewer.step()
    reviewer.fault_hook = None
    result = reviewer.step()
    if point == "review_reserved":
        assert result.reason_code == "dispatch-outcome-indeterminate"
        assert calls == []
        assert account.status().open_tokens == 100_000
    else:
        assert result.state == "revision_required"
        assert len(calls) == 1


@pytest.mark.unit
def test_changed_review_authority_cannot_reopen_a_paid_capture(tmp_path):
    producer, account, _, _ = _controller(tmp_path)
    producer.step()
    calls = []

    def crash(name):
        if name == "dispatch_captured":
            raise Crash()

    with pytest.raises(Crash):
        _reviewer(producer, account, calls, fault=crash).step()
    changed = _reviewer(
        producer, account, calls, agent=b"Changed independent review role",
    )
    with pytest.raises(DiscoveryError, match="discovery-review-dispatch-authority-mismatch"):
        changed.step()
    assert len(calls) == 1


@pytest.mark.unit
def test_invalid_review_is_durably_blocked_and_charged(tmp_path):
    producer, account, _, _ = _controller(tmp_path)
    producer.step()
    calls = []
    reviewer = _reviewer(producer, account, calls, backend=lambda _: b'{"kind":"not-a-review"}')

    result = reviewer.step()

    assert result.state == "blocked"
    assert result.reason_code == "review-result-invalid"
    assert reviewer.step() == result
    assert len(calls) == 1
    assert account.status().charged_tokens == 200_000


@pytest.mark.unit
def test_unsafe_review_is_charged_without_ordinary_capture(tmp_path):
    producer, account, phase, _ = _controller(tmp_path)
    producer.step()
    canary = b"synthetic-review-sensitive-token"
    calls = []
    reviewer = _reviewer(
        producer, account, calls,
        backend=lambda _: b'{"api_token":"' + canary + b'"}',
    )

    result = reviewer.step()

    assert result.reason_code == "unsafe-provider-output"
    assert account.status().charged_tokens == 200_000
    assert len(calls) == 1
    for path in phase.objects.root.rglob("*"):
        if path.is_file():
            assert canary not in path.read_bytes()


@pytest.mark.unit
def test_review_events_share_capture_and_source_turn_sequence(tmp_path):
    producer, account, _, _ = _controller(tmp_path)
    proposal = producer.step()
    reviewer = _reviewer(producer, account, [])
    result = reviewer.step()
    history, state = account.ledger.replay_with_history()

    assert [record.type for record in history] == [
        "account_opened", "dispatch_reserved", "dispatch_captured", "discovery_applied",
        "review_reserved", "dispatch_captured", "review_applied",
    ]
    source = producer.acquisition.opening["evidence_scope"]["source_id"]
    producer_id, review_id = state.sources[source]
    assert state.discovery_sources[source] == [producer_id]
    assert state.review_sources[source] == [review_id]
    request = state.dispatches[review_id]
    assert request["turn"] == 2
    assert request["producer_dispatch_id"] == producer_id
    assert request["proposal_receipt_id"] == proposal.receipt_id
    assert state.applied[review_id]["receipt_id"] == result.receipt_id


@pytest.mark.unit
def test_bound_role_and_context_are_rejected_before_review_spend(tmp_path):
    producer, account, _, _ = _controller(tmp_path)
    producer.step()
    calls = []
    reviewer = _reviewer(
        producer, account, calls,
        reservation=DispatchReservationV1(1, 100_000, 10_000),
    )

    result = reviewer.step()

    assert result.reason_code == "discovery-review-input-reservation-exceeded"
    assert calls == []
    assert account.status().charged_tokens == 100_000


@pytest.mark.unit
def test_review_application_storage_failure_retries_only_admission(tmp_path, monkeypatch):
    producer, account, phase, _ = _controller(tmp_path)
    producer.step()
    calls = []
    original = phase.objects.put_blob

    def fail_after_capture(name):
        if name == "dispatch_captured":
            monkeypatch.setattr(
                phase.objects, "put_blob",
                lambda _: (_ for _ in ()).throw(OSError("temporary fixture failure")),
            )

    reviewer = _reviewer(producer, account, calls, fault=fail_after_capture)
    with pytest.raises(DiscoveryError):
        reviewer.step()
    monkeypatch.setattr(phase.objects, "put_blob", original)
    reviewer.fault_hook = None

    assert reviewer.step().state == "revision_required"
    assert len(calls) == 1


@pytest.mark.unit
def test_review_reservation_replay_rejects_substituted_context(tmp_path):
    producer, account, _, _ = _controller(tmp_path)
    producer.step()
    request = _reserved_review_request(producer, account)
    substituted = canonical_json_bytes({"kind": "untrusted_discovery_review_context"})
    request["context_id"] = account.objects.put_blob(substituted)
    before = account.ledger.path.read_bytes()

    with pytest.raises(DiscoveryError):
        account._record("review_reserved", request)

    assert account.ledger.path.read_bytes() == before


@pytest.mark.unit
def test_terminal_replay_reconstructs_review_instead_of_trusting_forged_closure(tmp_path):
    producer, account, _, _ = _controller(tmp_path)
    producer.step()
    calls = []

    def crash(name):
        if name == "dispatch_captured":
            raise Crash()

    reviewer = _reviewer(producer, account, calls, fault=crash)
    with pytest.raises(Crash):
        reviewer.step()
    state = account.ledger.replay()
    source = producer.acquisition.opening["evidence_scope"]["source_id"]
    review_id = state.review_sources[source][-1]
    request = state.dispatches[review_id]
    capture = state.captures[review_id]
    # This has receipt-shaped fields and the paid capture ID, but its normalized
    # review object was never derived from that capture by the admission boundary.
    forged_review_id = account.objects.put_blob(canonical_json_bytes({
        "schema_version": 1, "kind": "discovery_review", "proposal_id": "forged",
        "verdict": "revise", "domains": [], "subjects": [], "inventory": [],
        "overlaps": [], "findings": [],
    }))
    producer_receipt = json.loads(account.objects.read_blob(request["proposal_receipt_id"]))
    forged_receipt = {
        "schema_version": 1,
        "state": "review_validated",
        "binding_id": request["binding_id"],
        "proposal_receipt_id": request["proposal_receipt_id"],
        "proposal_id": producer_receipt["proposal_id"],
        "review_id": forged_review_id,
        "authorial_response_id": capture["output_id"],
        "reviewer_context_id": request["context_id"],
        "outcome": "revision_required",
        "execution_certification_required": True,
        "analysis_certified": False,
        "findings": [],
    }
    forged_receipt_id = account.objects.put_blob(canonical_json_bytes(forged_receipt))
    account._record("review_applied", {
        "dispatch_id": review_id,
        "state": "revision_required",
        "receipt_id": forged_receipt_id,
        "reason_code": None,
        "revision_id": request["revision_id"],
    })
    reviewer.fault_hook = None

    with pytest.raises(DiscoveryError):
        reviewer.step()
    assert len(calls) == 1


@pytest.mark.unit
def test_review_application_replay_rejects_unknown_outcome(tmp_path):
    producer, account, _, _ = _controller(tmp_path)
    producer.step()
    calls = []

    def crash(name):
        if name == "dispatch_captured":
            raise Crash()

    reviewer = _reviewer(producer, account, calls, fault=crash)
    with pytest.raises(Crash):
        reviewer.step()
    state = account.ledger.replay()
    source = producer.acquisition.opening["evidence_scope"]["source_id"]
    dispatch_id = state.review_sources[source][-1]
    request, capture = state.dispatches[dispatch_id], state.captures[dispatch_id]
    receipt_id = reviewer.boundary.admit(
        request["binding_id"], request["proposal_receipt_id"],
        account.objects.read_blob(capture["output_id"]),
    )
    receipt = json.loads(account.objects.read_blob(receipt_id))
    receipt["outcome"] = "invented-success"
    forged = account.objects.put_blob(canonical_json_bytes(receipt))
    before = account.ledger.path.read_bytes()

    with pytest.raises(DiscoveryError):
        account._record("review_applied", {
            "dispatch_id": dispatch_id,
            "state": "revision_required",
            "receipt_id": forged,
            "reason_code": None,
            "revision_id": request["revision_id"],
        })
    assert account.ledger.path.read_bytes() == before


@pytest.mark.unit
@pytest.mark.parametrize(
    "reason", ["provider-failed", "unsafe-provider-output", "invalid-provider-result"],
)
def test_review_application_rejects_transport_failure_without_matching_capture(
        tmp_path, reason):
    producer, account, _, _ = _controller(tmp_path)
    producer.step()
    calls = []

    def crash(name):
        if name == "dispatch_captured":
            raise Crash()

    reviewer = _reviewer(producer, account, calls, fault=crash)
    with pytest.raises(Crash):
        reviewer.step()
    state = account.ledger.replay()
    source = producer.acquisition.opening["evidence_scope"]["source_id"]
    dispatch_id = state.review_sources[source][-1]
    request, capture = state.dispatches[dispatch_id], state.captures[dispatch_id]
    assert capture["reason_code"] is None
    before = account.ledger.path.read_bytes()

    with pytest.raises(DiscoveryError):
        account._record("review_applied", {
            "dispatch_id": dispatch_id,
            "state": "blocked",
            "receipt_id": None,
            "reason_code": reason,
            "revision_id": request["revision_id"],
        })

    assert account.ledger.path.read_bytes() == before


@pytest.mark.unit
def test_review_reservation_replay_rejects_invented_overlap_pairs(tmp_path):
    producer, account, _, _ = _controller(tmp_path)
    producer.step()
    request = _reserved_review_request(producer, account)
    context = json.loads(account.objects.read_blob(request["context_id"]))
    context["overlap_pairs"] = [["invented-left", "invented-right"]]
    request["context_id"] = account.objects.put_blob(canonical_json_bytes(context))
    before = account.ledger.path.read_bytes()

    with pytest.raises(DiscoveryError):
        account._record("review_reserved", request)

    assert account.ledger.path.read_bytes() == before


@pytest.mark.unit
def test_mutated_producer_account_cannot_cross_run_paths(tmp_path):
    producer, account, _, _ = _controller(tmp_path / "first")
    producer.step()
    calls = []
    reviewer = _reviewer(producer, account, calls)
    _, other_account, _, _ = _controller(tmp_path / "second")
    producer.account = other_account

    with pytest.raises(DiscoveryError, match="discovery-account-run-mismatch"):
        reviewer.step()
    assert calls == []


@pytest.mark.unit
def test_unfinished_producer_cannot_start_review(tmp_path):
    def crash(name):
        if name == "dispatch_captured":
            raise Crash()

    producer, account, _, _ = _controller(tmp_path, fault=crash)
    with pytest.raises(Crash):
        producer.step()
    calls = []

    result = _reviewer(producer, account, calls).step()

    assert result.reason_code == "discovery-review-proposal-required"
    assert calls == []
    assert account.status().charged_tokens == 100_000


@pytest.mark.unit
def test_changed_reservation_cannot_reopen_review_capture(tmp_path):
    producer, account, _, _ = _controller(tmp_path)
    producer.step()
    calls = []

    def crash(name):
        if name == "dispatch_captured":
            raise Crash()

    with pytest.raises(Crash):
        _reviewer(producer, account, calls, fault=crash).step()
    changed = _reviewer(
        producer, account, calls,
        reservation=DispatchReservationV1(99_999, 99_999, 10_000),
    )
    with pytest.raises(DiscoveryError, match="discovery-review-dispatch-authority-mismatch"):
        changed.step()
    assert len(calls) == 1


@pytest.mark.unit
def test_changed_backend_contract_is_rejected_without_spending(tmp_path):
    module = importlib.import_module("harness.re_v2.knowledge_review_dispatch")
    producer, account, _, _ = _controller(tmp_path)
    producer.step()

    def backend(*_):
        pytest.fail("changed backend must not run")

    backend.contract_id = content_digest(b"changed-backend")
    with pytest.raises(DiscoveryError, match="discovery-review-provider-contract-mismatch"):
        module.DiscoveryReviewController(
            producer, REVIEW_AGENT, backend, REVIEW_RESERVATION,
        )
    assert account.status().charged_tokens == 100_000


@pytest.mark.unit
def test_corrupt_review_objects_fail_closed_on_reopen(tmp_path):
    producer, account, _, _ = _controller(tmp_path)
    proposal = producer.step()
    reviewer = _reviewer(producer, account, [])
    result = reviewer.step()
    receipt = json.loads(account.objects.read_blob(result.receipt_id))
    account.objects._path(receipt["review_id"]).unlink()

    with pytest.raises(DiscoveryError):
        reviewer.step()
    assert proposal.state == "proposal_ready"


@pytest.mark.unit
def test_ready_review_remains_distinct_from_revision_feedback(tmp_path):
    from harness.re_v2.knowledge_accounting import (
        KnowledgeDispatchAccount, KnowledgeDispatchPolicy,
    )
    from harness.re_v2.knowledge_dispatch import DiscoveryController, ProviderReply
    from tests.unit.test_re_v2_knowledge_acquisition import _phase_setup
    from tests.unit.test_re_v2_knowledge_dispatch import _contract
    from tests.unit.test_re_v2_knowledge_discovery import _proposal

    phase, paths, boundary, _, _, _ = _phase_setup(
        tmp_path, files={"app.py": "def run(): return 3\n"},
    )
    account = KnowledgeDispatchAccount(
        paths, KnowledgeDispatchPolicy(500_000, 100_000, 3),
        _contract(), boundary.run_authority(),
    )

    def produce(agent, context, reservation):
        return ProviderReply(
            canonical_json_bytes(_proposal(json.loads(context))),
            NormalizedUsageV1("unavailable", None, {}),
        )

    produce.contract_id = account.opening["provider_contract_id"]
    producer = DiscoveryController(
        phase, account, b"Neutral discovery role", produce, REVIEW_RESERVATION,
    )
    proposal = producer.step()
    calls = []
    reviewer = _reviewer(
        producer, account, calls,
        backend=lambda context: _valid_review(context, "ready"),
    )

    result = reviewer.step()

    assert result.state == "review_ready"
    receipt = importlib.import_module(
        "harness.re_v2.knowledge_discovery_review"
    ).DiscoveryReviewBoundary(boundary).read_review(
        phase.status().binding_id, proposal.receipt_id, result.receipt_id,
    )
    assert receipt["outcome"] == "ready_for_planning"
    assert receipt["execution_certification_required"] is True
    assert receipt["analysis_certified"] is False


@pytest.mark.unit
def test_other_source_breach_does_not_discard_paid_clean_review_capture(tmp_path):
    from harness.re_v2.knowledge_accounting import (
        KnowledgeDispatchAccount, KnowledgeDispatchPolicy,
    )
    from harness.re_v2.knowledge_dispatch import DiscoveryController, ProviderReply
    from tests.unit.test_re_v2_knowledge_dispatch import _contract, _two_phases
    from tests.unit.test_re_v2_knowledge_discovery import _proposal

    first, second = _two_phases(tmp_path)
    account = KnowledgeDispatchAccount(
        first.paths, KnowledgeDispatchPolicy(500_000, 100_000, 3),
        _contract(), first.boundary.run_authority(),
    )
    producer_calls = []

    def produce(agent, context, reservation):
        data = json.loads(context)
        producer_calls.append(data["source_id"])
        tokens = 10 if data["source_id"] == "api" else 100_001
        return ProviderReply(
            canonical_json_bytes(_proposal(data)),
            NormalizedUsageV1("trusted_exact", tokens, {
                "input_tokens": tokens,
                "cached_input_tokens": 0,
                "reasoning_output_tokens": 0,
                "visible_output_tokens": 0,
            }),
        )

    produce.contract_id = account.opening["provider_contract_id"]
    first_producer = DiscoveryController(first, account, b"role", produce, REVIEW_RESERVATION)
    second_producer = DiscoveryController(second, account, b"role", produce, REVIEW_RESERVATION)
    assert first_producer.step().state == "proposal_ready"
    review_calls = []

    def crash(name):
        if name == "dispatch_captured":
            raise Crash()

    reviewer = _reviewer(first_producer, account, review_calls, fault=crash)
    with pytest.raises(Crash):
        reviewer.step()
    assert second_producer.step().reason_code == "reservation-exceeded"
    reviewer.fault_hook = None

    assert reviewer.step().state == "revision_required"
    assert producer_calls == ["api", "worker"]
    assert len(review_calls) == 1
    assert account.status().reservation_breached
