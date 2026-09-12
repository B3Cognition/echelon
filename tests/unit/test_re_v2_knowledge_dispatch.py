"""Offline provider seam; real pinned evidence, acquisition and durable storage."""
from __future__ import annotations

import json

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_discovery import DiscoveryError
from harness.re_v2.protocol_22.provider import DispatchReservationV1, NormalizedUsageV1
from tests.unit.test_re_v2_knowledge_acquisition import _phase_setup
from tests.unit.test_re_v2_knowledge_discovery import _proposal


def _contract(name="scripted"):
    from harness.re_v2.knowledge_dispatch import KnowledgeProviderContract
    return KnowledgeProviderContract(name, "offline-fixture", content_digest({"adapter": name}))


@pytest.mark.unit
def test_repair_feedback_explains_depth_scoped_subject_categories():
    from harness.re_v2.knowledge_dispatch import _repair_requirement

    requirement = _repair_requirement("invalid-discovery-subject-category")

    assert "category_ids" in requirement
    assert "required" in requirement
    assert "outside_requested_depth" in requirement


def _controller(
    tmp_path, *, tokens=500_000, turns=3, repairs=None, review_revisions=None,
    backend=None, fault=None
):
    from harness.re_v2.knowledge_dispatch import (
        DiscoveryController, KnowledgeDispatchAccount, KnowledgeDispatchPolicy, ProviderReply,
    )
    phase, paths, boundary, binding, objects, _ = _phase_setup(tmp_path)
    account = KnowledgeDispatchAccount(
        paths,
        KnowledgeDispatchPolicy(
            tokens, 100_000, turns, repairs, review_revisions
        ),
        _contract(),
        boundary.run_authority(),
    )
    calls = []

    def execute(agent, context, reservation):
        # Durable reservation must exist before the provider sees any input.
        assert account.status().open_tokens == reservation.billable_tokens
        calls.append(json.loads(context))
        output = backend(context) if backend else canonical_json_bytes(_proposal(json.loads(context)))
        return ProviderReply(output, NormalizedUsageV1("unavailable", None, {}))

    execute.contract_id = account.opening["provider_contract_id"]

    controller = DiscoveryController(phase, account, b"Neutral discovery role", execute,
                                     DispatchReservationV1(100_000, 100_000, 10_000), fault_hook=fault)
    return controller, account, phase, calls


@pytest.mark.unit
def test_provider_reservation_capture_and_staged_proposal_are_durable(tmp_path):
    controller, account, phase, calls = _controller(tmp_path)
    result = controller.step()
    assert result.state == "proposal_ready"
    assert result.reason_code is None
    assert json.loads(phase.objects.read_blob(result.receipt_id))["review_required"] is True
    assert account.status().charged_tokens == 100_000
    assert account.status().open_tokens == 0
    assert controller.step() == result
    assert len(calls) == 1


def _evidence(context, path="worker.py"):
    data = json.loads(context)
    inventory = {row["path"]: row for row in data["inventory"]}
    return canonical_json_bytes({
        "schema_version": 1, "kind": "evidence_requests", "source_id": "api",
        "requests": [{"obligation_id": data["origin_obligation_id"], "reason_class": "missing-behavior",
                      "selector": {"source_id": "api", "path": path, "byte_start": 0,
                                   "byte_end": inventory.get(path, {}).get("byte_count", 1)}}],
    })


@pytest.mark.unit
def test_provider_evidence_then_proposal_shares_account_across_revisions(tmp_path):
    replies = iter([_evidence, lambda context: canonical_json_bytes(_proposal(json.loads(context)))])
    controller, account, phase, calls = _controller(tmp_path, backend=lambda context: next(replies)(context))
    assert controller.step().state == "evidence_ready"
    assert phase.status().rounds == 1
    assert controller.step().state == "proposal_ready"
    assert len(calls[1]["evidence"]) == 2
    assert account.status().charged_tokens == 200_000


@pytest.mark.unit
def test_insufficient_remaining_budget_blocks_before_second_provider_call(tmp_path):
    controller, account, phase, calls = _controller(tmp_path, tokens=150_000, backend=_evidence)
    assert controller.step().state == "evidence_ready"
    result = controller.step()
    assert result.state == "blocked" and result.reason_code == "budget-exhausted"
    assert len(calls) == 1
    assert account.status().charged_tokens == 100_000


class Crash(BaseException):
    pass


@pytest.mark.unit
@pytest.mark.parametrize("point", ["dispatch_reserved", "dispatch_captured", "discovery_applied"])
def test_recovery_never_duplicates_a_provider_call(tmp_path, point):
    def fault(name):
        if name == point:
            raise Crash()
    controller, account, phase, calls = _controller(tmp_path, fault=fault)
    with pytest.raises(Crash):
        controller.step()
    controller.fault_hook = None
    result = controller.step()
    if point == "dispatch_reserved":
        assert result.reason_code == "dispatch-outcome-indeterminate"
        assert not calls
        assert account.status().open_tokens == 100_000
    else:
        assert result.state == "proposal_ready"
        assert len(calls) == 1


@pytest.mark.unit
def test_repeat_only_request_stops_instead_of_looping(tmp_path):
    controller, account, phase, calls = _controller(tmp_path, backend=lambda context: _evidence(context, "missing.py"))
    assert controller.step().state == "evidence_ready"
    result = controller.step()
    assert result.reason_code == "discovery-no-new-evidence"
    assert controller.step() == result
    assert len(calls) == 2 and phase.status().rounds == 1


@pytest.mark.unit
def test_unsafe_output_is_charged_but_never_retained_in_ordinary_store(tmp_path):
    canary = b"synthetic-dispatch-sensitive-token"
    controller, account, phase, calls = _controller(tmp_path, backend=lambda _: b'{"api_token":"' + canary + b'"}')
    result = controller.step()
    assert result.state == "blocked" and result.reason_code == "unsafe-provider-output"
    assert account.status().charged_tokens == 100_000
    for file in phase.objects.root.rglob("*"):
        if file.is_file():
            assert canary not in file.read_bytes()
    assert controller.step() == result and len(calls) == 1


@pytest.mark.unit
def test_backend_exception_retains_conservative_charge_and_closed_diagnostic(tmp_path):
    def fail(_):
        raise RuntimeError("private source details must not escape")
    controller, account, phase, calls = _controller(tmp_path, backend=fail)
    result = controller.step()
    assert result.reason_code == "provider-failed"
    assert account.status().charged_tokens == 100_000
    assert account.status().charged_active_ms == 10_000
    assert controller.step() == result and len(calls) == 1


@pytest.mark.unit
@pytest.mark.parametrize("change", ["tokens", "time", "turns", "provider"])
def test_account_reopening_cannot_raise_or_replace_authority(tmp_path, change):
    from harness.re_v2.knowledge_dispatch import KnowledgeDispatchAccount, KnowledgeDispatchPolicy
    controller, account, phase, calls = _controller(tmp_path)
    controller.step()
    limits = dict(account.opening["policy"])
    field = {"tokens": "token_limit", "time": "active_ms_limit", "turns": "max_source_turns"}.get(change)
    if field:
        limits[field] += 1
    provider = _contract("different") if change == "provider" else account.contract
    with pytest.raises(DiscoveryError, match="knowledge-account-mismatch"):
        KnowledgeDispatchAccount(phase.paths, KnowledgeDispatchPolicy(**limits), provider, phase.boundary.run_authority())
    assert account.status().charged_tokens == 100_000


@pytest.mark.unit
def test_backend_contract_and_agent_cannot_change_on_reopen(tmp_path):
    from harness.re_v2.knowledge_dispatch import DiscoveryController
    controller, account, phase, calls = _controller(tmp_path)
    other = lambda *_: pytest.fail("wrong provider called")
    other.contract_id = content_digest(b"wrong-provider")
    with pytest.raises(DiscoveryError, match="discovery-provider-contract-mismatch"):
        DiscoveryController(phase, account, controller.agent_bytes, other, controller.reservation)
    controller.step()
    changed = DiscoveryController(phase, account, b"Different role", controller.backend, controller.reservation)
    with pytest.raises(DiscoveryError, match="discovery-dispatch-authority-mismatch"):
        changed.step()


@pytest.mark.unit
@pytest.mark.parametrize("legacy", ["manifest", "events", "ledger"])
def test_legacy_run_cannot_gain_a_shadow_budget(tmp_path, legacy):
    from harness.re_v2.knowledge_dispatch import KnowledgeDispatchAccount, KnowledgeDispatchPolicy
    controller, account, phase, calls = _controller(tmp_path)
    getattr(phase.paths, legacy).write_bytes(b"old authority")
    with pytest.raises(DiscoveryError, match="legacy-run-requires-accounting-migration"):
        KnowledgeDispatchAccount(phase.paths, KnowledgeDispatchPolicy(500_000, 100_000, 3), account.contract, phase.boundary.run_authority())
    with pytest.raises(DiscoveryError, match="legacy-run-requires-accounting-migration"):
        controller.step()
    assert not calls


@pytest.mark.unit
def test_exact_usage_and_reservation_breach(tmp_path):
    from harness.re_v2.knowledge_dispatch import ProviderReply
    controller, account, phase, calls = _controller(tmp_path)
    def exact(agent, context, reservation):
        return ProviderReply(canonical_json_bytes(_proposal(json.loads(context))),
                             NormalizedUsageV1("trusted_exact", 100_001, {
                                 "input_tokens": 100_000, "cached_input_tokens": 0,
                                 "reasoning_output_tokens": 0, "visible_output_tokens": 1,
                             }))
    exact.contract_id = account.opening["provider_contract_id"]
    controller.backend = exact
    assert controller.step().reason_code == "reservation-exceeded"
    assert account.status().charged_tokens == 100_001
    assert account.status().reservation_breached


@pytest.mark.unit
def test_context_commit_crash_recovers_captured_turn_without_provider_reissue(tmp_path):
    controller, account, phase, calls = _controller(tmp_path, backend=_evidence)
    def crash(name):
        if name == "context_committed":
            raise Crash()
    phase.fault_hook = crash
    with pytest.raises(Crash):
        controller.step()
    phase.fault_hook = None
    assert controller.step().state == "evidence_ready"
    assert phase.status().rounds == 1 and len(calls) == 1


@pytest.mark.unit
def test_turn_limit_and_no_false_completion(tmp_path):
    controller, account, phase, calls = _controller(tmp_path, turns=1, backend=_evidence)
    assert controller.step().state == "evidence_ready"
    assert controller.step().reason_code == "discovery-turn-limit"
    assert len(calls) == 1


@pytest.mark.unit
def test_invalid_output_is_retained_safely_and_charged_not_retried(tmp_path):
    controller, account, phase, calls = _controller(tmp_path, backend=lambda _: b'{"not":"a proposal"}')
    result = controller.step()
    assert result.reason_code == "discovery-result-invalid"
    assert result.state == "blocked"
    assert controller.step() == result and len(calls) == 1
    assert account.status().charged_tokens == 100_000


@pytest.mark.unit
def test_opted_in_invalid_proposal_gets_bounded_deterministic_repair_context(tmp_path):
    replies = iter((b'{"not":"a proposal"}', None))

    def backend(context):
        reply = next(replies)
        if reply is not None:
            return reply
        repair = json.loads(context)
        assert repair["kind"] == "untrusted_discovery_repair_context"
        assert repair["deterministic_feedback"]["reason_code"] == "invalid-discovery-response"
        assert repair["previous_candidate_text"] == '{"not":"a proposal"}'
        return canonical_json_bytes(_proposal(repair["safe_discovery_context"]))

    controller, account, _phase, calls = _controller(
        tmp_path, turns=4, repairs=1, backend=backend
    )

    first = controller.step()
    assert first.state == "repair_ready" and first.reason_code is None
    assert controller.step().state == "proposal_ready"
    assert len(calls) == 2
    assert account.status().charged_tokens == 200_000


@pytest.mark.unit
def test_duplicate_json_field_can_receive_an_opaque_second_repair(tmp_path):
    replies = iter((
        b'{"not":"a proposal"}',
        b'{"not":1,"not":2}',
        None,
    ))

    def backend(context):
        reply = next(replies)
        if reply is not None:
            return reply
        repair = json.loads(context)
        assert repair["schema_version"] == 2
        assert repair["deterministic_feedback"]["reason_code"] == (
            "duplicate-discovery-field"
        )
        assert repair["previous_candidate_text"] == '{"not":1,"not":2}'
        return canonical_json_bytes(_proposal(repair["safe_discovery_context"]))

    controller, account, _phase, calls = _controller(
        tmp_path, turns=5, repairs=2, backend=backend
    )

    assert controller.step().state == "repair_ready"
    assert controller.step().state == "repair_ready"
    assert controller.step().state == "proposal_ready"
    assert len(calls) == 3
    assert account.status().charged_tokens == 300_000


@pytest.mark.unit
def test_schema_1_repair_context_replays_after_opaque_upgrade(tmp_path):
    replies = iter((b'{"not":"a proposal"}', None))

    def backend(context):
        reply = next(replies)
        if reply is not None:
            return reply
        repair = json.loads(context)
        assert repair["schema_version"] == 1
        return canonical_json_bytes(_proposal(repair["safe_discovery_context"]))

    controller, _account, _phase, calls = _controller(
        tmp_path, turns=4, repairs=1, backend=backend
    )
    assert controller.step().state == "repair_ready"
    upgraded = controller._repair_context
    controller._repair_context = lambda state, dispatch_id: upgraded(
        state, dispatch_id, schema_version=1
    )
    proposal = controller.step()
    controller._repair_context = upgraded

    assert proposal.state == "proposal_ready"
    assert controller.step() == proposal
    assert len(calls) == 2


@pytest.mark.unit
def test_invalid_proposal_repair_limit_is_finite_and_durable(tmp_path):
    controller, account, _phase, calls = _controller(
        tmp_path,
        turns=5,
        repairs=1,
        backend=lambda _context: b'{"not":"a proposal"}',
    )

    assert controller.step().state == "repair_ready"
    assert controller.step().state == "repair_ready"
    stopped = controller.step()

    assert stopped.state == "blocked"
    assert stopped.reason_code == "discovery-repair-limit"
    assert controller.step() == stopped
    assert len(calls) == 2
    assert account.status().charged_tokens == 200_000


def _two_phases(tmp_path):
    from dataclasses import replace
    from echelon.workspace_model import WorkspaceInfo, WorkspaceManifest
    from harness.re_v2.knowledge_acquisition import DiscoveryAcquisition
    from harness.re_v2.knowledge_discovery import DiscoveryBoundary
    from harness.re_v2.knowledge_evidence import EvidenceSelectorV1
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.partition import ImplementationAuthorityV1, PartitionAuthoritiesV1, build_workspace_partition_catalog
    from harness.re_v2.run_store import ReV2Paths
    from harness.re_v2.workspace_snapshot import capture_workspace_snapshot
    from tests.unit.test_re_v2_workspace_snapshot import _clean_repo, _sources
    workspace = tmp_path / "workspace"
    repos = [_clean_repo(workspace / "sources" / name, {"app.py": "run()\n"}) for name in ("first", "second")]
    sources = tuple(replace(source, id=name) for source, name in zip(_sources(workspace, *repos), ("api", "worker")))
    snapshot = capture_workspace_snapshot(workspace, sources, tmp_path / "snapshots")
    manifest = WorkspaceManifest(schema_version=1, workspace=WorkspaceInfo(
        root=workspace.resolve(), git_role="orchestration", git_present=False), sources=sources)
    authority = ImplementationAuthorityV1(id="fixture", version="1", implementation_digest=content_digest(b"fixture"))
    partition = build_workspace_partition_catalog(snapshot, manifest, PartitionAuthoritiesV1(partitioner=authority, ownership_policy=authority))
    paths = ReV2Paths.for_run(tmp_path / "re-test")
    paths.root.mkdir(parents=True)
    objects, quarantine = ObjectStore(paths.objects), ObjectStore(tmp_path / "quarantine")
    phases = []
    for source in sources:
        boundary = DiscoveryBoundary(snapshot, partition, source.id, "standard", content_digest({"source": source.id}), objects, quarantine)
        binding = boundary.prepare((EvidenceSelectorV1(source.id, "app.py", 0, 6),))
        phases.append(DiscoveryAcquisition(paths, boundary, binding))
    return phases


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["unknown", "open", "exact"])
def test_all_selected_sources_share_settled_and_unsettled_charges(tmp_path, mode):
    from harness.re_v2.knowledge_dispatch import DiscoveryController, KnowledgeDispatchAccount, KnowledgeDispatchPolicy, ProviderReply
    first, second = _two_phases(tmp_path)
    account = KnowledgeDispatchAccount(first.paths, KnowledgeDispatchPolicy(150_000, 100_000, 3), _contract(), first.boundary.run_authority())
    calls = []
    def backend(agent, context, reserve):
        calls.append(json.loads(context)["source_id"])
        if mode == "open":
            raise Crash()
        usage = (NormalizedUsageV1("trusted_exact", 10, {"input_tokens": 9, "cached_input_tokens": 0,
                   "reasoning_output_tokens": 0, "visible_output_tokens": 1}) if mode == "exact"
                 else NormalizedUsageV1("unavailable", None, {}))
        # Invalid results still consume resources; no semantic fixture shortcuts.
        return ProviderReply(b"{}", usage)
    backend.contract_id = account.opening["provider_contract_id"]
    reserve = DispatchReservationV1(100_000, 100_000, 10_000)
    controllers = [DiscoveryController(phase, account, b"role", backend, reserve) for phase in (first, second)]
    if mode == "open":
        with pytest.raises(Crash):
            controllers[0].step()
    else:
        assert controllers[0].step().reason_code == "discovery-result-invalid"
    result = controllers[1].step()
    if mode == "exact":
        assert calls == ["api", "worker"]
        assert account.status().charged_tokens == 20
    else:
        assert result.reason_code == "budget-exhausted"
        assert calls == ["api"]
        assert account.status().charged_tokens + account.status().open_tokens == 100_000


@pytest.mark.unit
def test_active_time_reservation_is_also_aggregate(tmp_path):
    from harness.re_v2.knowledge_dispatch import KnowledgeDispatchAccount, KnowledgeDispatchPolicy, DiscoveryController
    controller, account, phase, calls = _controller(tmp_path)
    # A different fresh fixture, not an authorization change to this account.
    first, second = _two_phases(tmp_path / "other")
    small = KnowledgeDispatchAccount(first.paths, KnowledgeDispatchPolicy(500_000, 9_000, 3), account.contract, first.boundary.run_authority())
    blocked = DiscoveryController(first, small, b"role", controller.backend, controller.reservation).step()
    assert blocked.reason_code == "budget-exhausted" and not calls


@pytest.mark.unit
@pytest.mark.parametrize("damage", ["journal", "output", "context"])
def test_corrupt_dispatch_closure_blocks_without_provider_retry(tmp_path, damage):
    controller, account, phase, calls = _controller(tmp_path)
    controller.step()
    state = account.ledger.replay()
    if damage == "journal":
        with account.ledger.path.open("ab") as stream:
            stream.write(b"broken")
    else:
        oid = (next(iter(state.captures.values()))["output_id"] if damage == "output"
               else next(iter(state.dispatches.values()))["context_id"])
        phase.objects._path(oid).unlink()
    with pytest.raises(DiscoveryError):
        controller.step()
    assert len(calls) == 1


@pytest.mark.unit
def test_competing_controllers_use_same_ownership_lock(tmp_path):
    import concurrent.futures
    import threading
    controller, account, phase, calls = _controller(tmp_path)
    original = controller.backend
    entered, release = threading.Event(), threading.Event()
    def backend(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)
    backend.contract_id = original.contract_id
    controller.backend = backend
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(controller.step)
        assert entered.wait(5)
        second = pool.submit(controller.step)
        assert not second.done()
        release.set()
        assert first.result(timeout=10) == second.result(timeout=10)
    assert len(calls) == 1


@pytest.mark.unit
def test_completed_dispatch_still_authenticates_pinned_evidence(tmp_path):
    controller, account, phase, calls = _controller(tmp_path)
    controller.step()
    # Mutate only the fixture's captured snapshot, never a real workspace.
    root = next((tmp_path / "snapshots").rglob("app.py"))
    root.chmod(0o600)
    root.write_bytes(b"different pinned evidence\n")
    with pytest.raises(DiscoveryError):
        controller.step()
    assert len(calls) == 1


@pytest.mark.unit
def test_empty_existing_account_cannot_refund_spent_tokens(tmp_path):
    from harness.re_v2.knowledge_dispatch import KnowledgeDispatchAccount, KnowledgeDispatchPolicy
    controller, account, phase, calls = _controller(tmp_path)
    controller.step()
    account.ledger.path.write_bytes(b"")
    with pytest.raises(DiscoveryError, match="missing-knowledge-account"):
        account.status()
    with pytest.raises(DiscoveryError, match="missing-knowledge-account"):
        controller.step()
    with pytest.raises(DiscoveryError, match="missing-knowledge-account"):
        KnowledgeDispatchAccount(phase.paths, KnowledgeDispatchPolicy(**account.opening["policy"]),
                                 account.contract, phase.boundary.run_authority())
    assert len(calls) == 1


@pytest.mark.unit
@pytest.mark.parametrize("kind", ["captures", "dangling-manifest", "dangling-captures"])
def test_legacy_execution_authority_and_dangling_paths_block_new_account(tmp_path, kind):
    from harness.re_v2.knowledge_dispatch import KnowledgeDispatchAccount, KnowledgeDispatchPolicy
    phase, paths, *_ = _phase_setup(tmp_path)
    if kind == "captures":
        (paths.root / "captures").mkdir()
    else:
        path = paths.manifest if kind == "dangling-manifest" else paths.root / "captures"
        path.symlink_to(tmp_path / "missing")
    with pytest.raises(DiscoveryError, match="legacy-run-requires-accounting-migration"):
        KnowledgeDispatchAccount(paths, KnowledgeDispatchPolicy(500_000, 100_000, 3), _contract(), phase.boundary.run_authority())


@pytest.mark.unit
def test_temporary_admission_storage_failure_keeps_captured_turn_recoverable(tmp_path, monkeypatch):
    controller, account, phase, calls = _controller(tmp_path)
    original = phase.objects.put_blob
    def fail_after_capture(name):
        if name == "dispatch_captured":
            def fail(_):
                raise OSError("fixture storage temporarily unavailable")
            monkeypatch.setattr(phase.objects, "put_blob", fail)
    controller.fault_hook = fail_after_capture
    with pytest.raises(DiscoveryError):
        controller.step()
    monkeypatch.setattr(phase.objects, "put_blob", original)
    controller.fault_hook = None
    assert not account.ledger.replay().applied
    assert controller.step().state == "proposal_ready"
    assert len(calls) == 1


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["blocked-reason", "success-reason", "missing-receipt", "wrong-revision", "wrong-kind",
                                 "false-provider-failure", "missing-evidence-stop", "wrong-evidence-stop"])
def test_contradictory_application_receipt_is_not_authority(tmp_path, bad):
    def crash(name):
        if name == "dispatch_captured":
            raise Crash()
    controller, account, phase, calls = _controller(tmp_path, fault=crash)
    with pytest.raises(Crash):
        controller.step()
    state = account.ledger.replay()
    dispatch_id = next(iter(state.dispatches))
    request, capture = state.dispatches[dispatch_id], state.captures[dispatch_id]
    receipt_id = phase.boundary.admit(request["binding_id"], phase.objects.read_blob(capture["output_id"]), capture_bound=True)
    application = {"dispatch_id": dispatch_id, "state": "proposal_ready", "receipt_id": receipt_id,
                   "reason_code": None, "revision_id": request["revision_id"]}
    if bad == "blocked-reason":
        application.update(state="blocked", reason_code="arbitrary-provider-secret")
    elif bad == "success-reason":
        application["reason_code"] = "provider-failed"
    elif bad == "missing-receipt":
        application["receipt_id"] = None
    elif bad == "wrong-revision":
        application["revision_id"] = request["binding_id"]
    elif bad == "false-provider-failure":
        application.update(state="blocked", reason_code="provider-failed", receipt_id=None)
    elif bad == "missing-evidence-stop":
        application.update(state="blocked", reason_code="discovery-no-new-evidence", receipt_id=None)
    elif bad == "wrong-evidence-stop":
        application.update(state="blocked", reason_code="evidence-expansion-limit")
    else:
        application["state"] = "evidence_ready"
    with pytest.raises(DiscoveryError):
        account._record("discovery_applied", application)


@pytest.mark.unit
def test_failed_capture_cannot_attach_an_authorial_receipt(tmp_path):
    def fail(_):
        raise RuntimeError("scripted failure")
    def crash(name):
        if name == "dispatch_captured":
            raise Crash()
    controller, account, phase, calls = _controller(tmp_path, backend=fail, fault=crash)
    with pytest.raises(Crash):
        controller.step()
    state = account.ledger.replay()
    key, request = next(iter(state.dispatches.items()))
    receipt = phase.boundary.admit(request["binding_id"], canonical_json_bytes(_proposal(json.loads(phase.provider_bytes()))), capture_bound=True)
    with pytest.raises(DiscoveryError):
        account._record("discovery_applied", {"dispatch_id": key, "state": "blocked", "receipt_id": receipt,
                        "reason_code": "provider-failed", "revision_id": request["revision_id"]})


@pytest.mark.unit
@pytest.mark.parametrize("change", ["snapshot_id", "partition_id", "security_policy_id", "source_ids"])
def test_dispatch_cannot_mix_run_level_authority(tmp_path, change):
    from harness.re_v2.knowledge_dispatch import KnowledgeDispatchAccount, KnowledgeDispatchPolicy, DiscoveryController
    phase, paths, *_ = _phase_setup(tmp_path)
    authority = phase.boundary.run_authority()
    authority[change] = ["api", "other"] if change == "source_ids" else content_digest(b"other")
    account = KnowledgeDispatchAccount(paths, KnowledgeDispatchPolicy(500_000, 100_000, 3), _contract(), authority)
    def forbidden(*_):
        pytest.fail("mixed authority reached provider")
    forbidden.contract_id = account.contract.identity
    with pytest.raises(DiscoveryError, match="knowledge-run-authority-mismatch"):
        DiscoveryController(phase, account, b"role", forbidden, DispatchReservationV1(100_000, 100_000, 10_000))


@pytest.mark.unit
def test_provider_contract_is_stored_and_missing_contract_is_not_repaired_on_reopen(tmp_path):
    from harness.re_v2.knowledge_dispatch import KnowledgeDispatchAccount, KnowledgeDispatchPolicy
    controller, account, phase, calls = _controller(tmp_path)
    oid = account.opening["provider_contract_id"]
    assert json.loads(account.objects.read_blob(oid))["execution_mode"] == "offline-scripted"
    account.objects._path(oid).unlink()
    with pytest.raises(DiscoveryError):
        KnowledgeDispatchAccount(phase.paths, KnowledgeDispatchPolicy(**account.opening["policy"]), account.contract,
                                 phase.boundary.run_authority())
    assert not calls and not account.objects._path(oid).exists()


@pytest.mark.unit
def test_production_adapter_contract_is_not_enabled():
    from harness.re_v2.knowledge_dispatch import KnowledgeProviderContract
    with pytest.raises(DiscoveryError, match="production-discovery-backend-not-enabled"):
        KnowledgeProviderContract("codex", "configured-model", content_digest(b"adapter"), "cli")


@pytest.mark.unit
def test_noncanonical_run_paths_cannot_bypass_legacy_guard(tmp_path):
    from dataclasses import replace
    from harness.re_v2.knowledge_dispatch import KnowledgeDispatchAccount, KnowledgeDispatchPolicy
    phase, paths, *_ = _phase_setup(tmp_path)
    paths.manifest.write_bytes(b"legacy")
    fake = replace(paths, manifest=tmp_path / "not-the-manifest")
    with pytest.raises(DiscoveryError, match="noncanonical-knowledge-run-paths"):
        KnowledgeDispatchAccount(fake, KnowledgeDispatchPolicy(500_000, 100_000, 3), _contract(), phase.boundary.run_authority())


@pytest.mark.unit
def test_rejected_legacy_run_does_not_create_an_object_store(tmp_path):
    from harness.re_v2.knowledge_dispatch import KnowledgeDispatchAccount, KnowledgeDispatchPolicy
    from harness.re_v2.run_store import ReV2Paths
    paths = ReV2Paths.for_run(tmp_path / "legacy")
    paths.root.mkdir(parents=True)
    (paths.root / "captures").mkdir()
    authority = {"snapshot_id": content_digest(b"snap"), "partition_id": content_digest(b"part"),
                 "security_policy_id": content_digest(b"policy"), "source_ids": ["api"]}
    with pytest.raises(DiscoveryError):
        KnowledgeDispatchAccount(paths, KnowledgeDispatchPolicy(500_000, 100_000, 3), _contract(), authority)
    assert not paths.objects.exists()


@pytest.mark.unit
def test_frozen_selection_may_be_a_subset_but_other_declared_sources_cannot_spend_it(tmp_path):
    from harness.re_v2.knowledge_dispatch import KnowledgeDispatchAccount, KnowledgeDispatchPolicy, DiscoveryController, ProviderReply
    first, second = _two_phases(tmp_path)
    authority = first.boundary.run_authority()
    authority["source_ids"] = ["api"]
    account = KnowledgeDispatchAccount(first.paths, KnowledgeDispatchPolicy(500_000, 100_000, 3), _contract(), authority)
    calls = []
    def backend(agent, context, reserve):
        calls.append(json.loads(context)["source_id"])
        return ProviderReply(b"{}", NormalizedUsageV1("unavailable", None, {}))
    backend.contract_id = account.contract.identity
    reserve = DispatchReservationV1(100_000, 100_000, 10_000)
    controller = DiscoveryController(first, account, b"role", backend, reserve)
    assert controller.step().reason_code == "discovery-result-invalid"
    with pytest.raises(DiscoveryError, match="knowledge-run-authority-mismatch"):
        DiscoveryController(second, account, b"role", backend, reserve)
    assert calls == ["api"]


@pytest.mark.unit
def test_another_sources_breach_stops_new_calls_but_does_not_discard_clean_capture(tmp_path):
    from harness.re_v2.knowledge_dispatch import DiscoveryController, KnowledgeDispatchAccount, KnowledgeDispatchPolicy, ProviderReply
    first, second = _two_phases(tmp_path)
    account = KnowledgeDispatchAccount(first.paths, KnowledgeDispatchPolicy(500_000, 100_000, 3), _contract(), first.boundary.run_authority())
    calls = []
    def backend(agent, context, reserve):
        data = json.loads(context)
        calls.append(data["source_id"])
        tokens = 10 if data["source_id"] == "api" else 100_001
        return ProviderReply(canonical_json_bytes(_proposal(data)), NormalizedUsageV1("trusted_exact", tokens, {
            "input_tokens": tokens, "cached_input_tokens": 0, "reasoning_output_tokens": 0, "visible_output_tokens": 0}))
    backend.contract_id = account.contract.identity
    def crash(name):
        if name == "dispatch_captured":
            raise Crash()
    reserve = DispatchReservationV1(100_000, 100_000, 10_000)
    a = DiscoveryController(first, account, b"role", backend, reserve, fault_hook=crash)
    b = DiscoveryController(second, account, b"role", backend, reserve)
    with pytest.raises(Crash):
        a.step()
    assert b.step().reason_code == "reservation-exceeded"
    a.fault_hook = None
    assert a.step().state == "proposal_ready"
    assert calls == ["api", "worker"]
    assert account.status().reservation_breached


@pytest.mark.unit
def test_application_cannot_substitute_another_proposal_for_the_captured_response(tmp_path):
    def crash(name):
        if name == "dispatch_captured":
            raise Crash()
    controller, account, phase, calls = _controller(tmp_path, fault=crash)
    with pytest.raises(Crash):
        controller.step()
    state = account.ledger.replay()
    key, request = next(iter(state.dispatches.items()))
    different = _proposal(json.loads(phase.provider_bytes()))
    different["domains"][0]["description"] = "Different proposal from another attempt"
    receipt = phase.boundary.admit(request["binding_id"], canonical_json_bytes(different), capture_bound=True)
    with pytest.raises(DiscoveryError):
        account._record("discovery_applied", {"dispatch_id": key, "state": "proposal_ready", "receipt_id": receipt,
                        "reason_code": None, "revision_id": request["revision_id"]})


@pytest.mark.unit
def test_nonbytes_backend_output_is_invalid_not_a_secret_disclosure(tmp_path):
    controller, account, phase, calls = _controller(tmp_path, backend=lambda _: "not bytes")
    assert controller.step().reason_code == "invalid-provider-result"
    assert len(calls) == 1 and account.status().charged_tokens == 100_000


@pytest.mark.unit
def test_previous_passive_request_receipt_still_replays(tmp_path):
    phase, paths, boundary, binding, objects, _ = _phase_setup(tmp_path)
    current = boundary.admit(binding, _evidence(phase.provider_bytes()), capture_bound=True)
    receipt = json.loads(objects.read_blob(current))
    assert receipt["schema_version"] == 2
    receipt.pop("authorial_response_id")
    receipt["schema_version"] = 1
    previous = objects.put_blob(canonical_json_bytes(receipt))
    assert boundary.read_requests(binding, previous)
    assert phase.resolve(binding, previous).rounds == 1
