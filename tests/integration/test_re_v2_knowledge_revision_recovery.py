"""Faults use real immutable objects/events after real Task 3 activation."""
import pytest

from harness.re_v2.protocol_28.context import load_protocol_28_run_context
from tests.unit.test_re_v2_knowledge_revision import revision_fixture, revision_module, bytes_under, expansion_cause


@pytest.mark.integration
@pytest.mark.parametrize('seam', ['after_activation_intent', 'after_account_sealed', 'after_account_imported'])
def test_one_time_account_transfer_fault_recovery_never_imports_twice(tmp_path, seam):
    context, _, account, _ = revision_fixture(tmp_path)
    module = revision_module()
    def crash(point):
        if point == seam:
            raise RuntimeError('synthetic-transfer-fault')
    with pytest.raises(RuntimeError, match='synthetic-transfer-fault'):
        module.activate_knowledge_workflow(context, account, allow_debt=False, fault_hook=crash)
    before = bytes_under(context.paths.root)
    assert module.load_knowledge_revision(load_protocol_28_run_context(context.run_dir)) is None
    assert bytes_under(context.paths.root) == before
    from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
    with pytest.raises(RuntimeError, match='activation'):
        run_protocol_28_exhaustive(context.run_dir, lambda: pytest.fail('partial activation fell through to historical execution'))
    from harness.re_v2.protocol_28.status import protocol_28_status_document
    pending = protocol_28_status_document(context.run_dir)
    assert pending['status'] == 'needs-attention' and pending['reason_code'] == 'knowledge-activation-incomplete'
    assert bytes_under(context.paths.root) == before
    with pytest.raises(ValueError, match='intent|authorization'):
        module.activate_knowledge_workflow(context, account, allow_debt=True)
    assert bytes_under(context.paths.root) == before
    active = module.activate_knowledge_workflow(context, account, allow_debt=False)
    assert len(context.resources.records) == 1
    assert context.resources.decision.charged_tokens == account.status().charged_tokens
    before = bytes_under(context.paths.root)
    assert module.activate_knowledge_workflow(context, account, allow_debt=False) == active
    assert bytes_under(context.paths.root) == before


@pytest.mark.integration
@pytest.mark.parametrize('seam', [
    'after_request_intent', 'after_staged_child', 'after_inputs', 'after_dependency_map', 'after_context',
    'after_counters', 'after_invalidation_receipt', 'after_revision_receipt',
    'after_revision_manifest', 'after_active_pointer',
])
def test_only_pointer_last_complete_revision_is_active_after_every_fault(tmp_path, seam):
    context, inputs, account, acquisition = revision_fixture(tmp_path)
    module = revision_module()
    initial = module.activate_knowledge_workflow(context, account, allow_debt=False)
    cause = expansion_cause(context, acquisition, initial)
    class Crash(Exception):
        pass
    def fault(name):
        if name == seam:
            raise Crash(name)
    with pytest.raises(Crash):
        module.commit_knowledge_revision(context, inputs, cause, fault_hook=fault)
    before = bytes_under(context.paths.root)
    reopened = load_protocol_28_run_context(context.run_dir)
    observed = module.load_knowledge_revision(reopened)
    assert (observed.manifest.revision_id == initial.manifest.revision_id) is (seam != 'after_active_pointer')
    assert bytes_under(context.paths.root) == before
    resumed = module.commit_knowledge_revision(reopened, inputs, cause)
    assert resumed.manifest.revision_id != initial.manifest.revision_id
    stable = bytes_under(context.paths.root)
    assert module.commit_knowledge_revision(reopened, inputs, cause) == resumed
    assert bytes_under(context.paths.root) == stable


@pytest.mark.integration
@pytest.mark.parametrize('plan_change', ['unchanged', 'split-merge'])
def test_pending_revision_prevents_old_execution_and_retry_uses_frozen_histories(tmp_path, plan_change):
    from tests.unit.test_re_v2_protocol_28_reconciliation import reconciliation_fixture, KnowledgeBackend
    from tests.unit.test_re_v2_knowledge_revision import split_reviewed_domain_plan
    from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
    context, inputs, _, acquisition, active = reconciliation_fixture(tmp_path)
    replacement = split_reviewed_domain_plan(inputs) if plan_change == 'split-merge' else inputs
    cause = expansion_cause(context, acquisition, active)
    def fault(point):
        if point == 'after_request_intent':
            raise RuntimeError('pending-revision-fault')
    with pytest.raises(RuntimeError, match='pending-revision-fault'):
        revision_module().commit_knowledge_revision(context, replacement, cause, fault_hook=fault)
    before = bytes_under(context.paths.root)
    backend = KnowledgeBackend()
    with pytest.raises(RuntimeError, match='revision'):
        run_protocol_28_exhaustive(context.run_dir, lambda: backend)
    assert not backend.calls
    assert bytes_under(context.paths.root) == before
    revised = revision_module().commit_knowledge_revision(context, replacement, cause)
    assert run_protocol_28_exhaustive(context.run_dir, lambda: backend).state == 'complete'
    if plan_change == 'split-merge':
        next_cause = expansion_cause(load_protocol_28_run_context(context.run_dir), acquisition, revised, 1)
        merged = revision_module().commit_knowledge_revision(context, inputs, next_cause)
        assert merged.manifest.plan_id == inputs.exhaustive_plan.identity
        assert run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend()).state == 'complete'


@pytest.mark.integration
@pytest.mark.parametrize('rollback', ['previous-completion', 'second-activation', 'reordered-work'])
def test_later_captures_and_roots_reject_event_only_suffix_rollback(tmp_path, rollback):
    from tests.unit.test_re_v2_protocol_28_reconciliation import reconciliation_fixture, KnowledgeBackend
    from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
    from harness.re_v2.protocol_28.status import protocol_28_status_document
    context, inputs, _, acquisition, active = reconciliation_fixture(tmp_path)
    first = run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend())
    first_events = context.paths.events.read_bytes()
    cause = expansion_cause(context, acquisition, active)
    revision_module().commit_knowledge_revision(context, inputs, cause)
    activation_events = context.paths.events.read_bytes()
    second = run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend())
    assert first.state == second.state == 'complete' and first.run_root_id != second.run_root_id
    if rollback == 'reordered-work':
        events = list(context.events.replay())
        index = next(i for i, event in enumerate(events) if event.type == 'knowledge_work_realized'
            and i > len(first_events.splitlines()))
        work_event = events.pop(index)
        assert events[index].type == 'dispatch_reserved'
        events.insert(index + 1, work_event)
        context.paths.events.write_bytes(b'')
        for event in events:
            context.events.append(event.type, dict(event.payload), occurred_at=event.occurred_at)
    else:
        context.paths.events.write_bytes(first_events if rollback == 'previous-completion' else activation_events)
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError):
        load_protocol_28_run_context(context.run_dir)
    with pytest.raises((ValueError, RuntimeError)):
        protocol_28_status_document(context.run_dir)
    assert bytes_under(context.paths.root) == before


@pytest.mark.integration
def test_pending_revision_rejects_intervening_resource_history_before_any_more_writes(tmp_path):
    from harness.re_v2.protocol_22.provider import DispatchReservationV1
    context, inputs, account, acquisition = revision_fixture(tmp_path)
    module = revision_module()
    active = module.activate_knowledge_workflow(context, account, allow_debt=False)
    target = next(t for t in inputs.exhaustive_plan.target_plans if t.target_kind == 'domain')
    spec = module.realize_knowledge_slice(context, active, target.entries[0], {})
    cause = expansion_cause(context, acquisition, active)
    def crash(point):
        if point == 'after_request_intent':
            raise RuntimeError('pending-resource-fault')
    with pytest.raises(RuntimeError, match='pending-resource-fault'):
        module.commit_knowledge_revision(context, inputs, cause, fault_hook=crash)
    reservation = DispatchReservationV1(1, 1, 1)
    context.resources.commit_pair(context.resources.preview_pair(spec.identity, 1, reservation, reservation),
        producer_dispatch_id='intervening-producer', verifier_dispatch_id='intervening-verifier')
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError, match='revision|prefix|history'):
        module.commit_knowledge_revision(context, inputs, cause)
    assert bytes_under(context.paths.root) == before


@pytest.mark.integration
def test_first_reviewed_capture_cannot_be_reopened_as_historical_after_activation_event_rollback(tmp_path, monkeypatch):
    from tests.unit.test_re_v2_protocol_28_reconciliation import reconciliation_fixture, KnowledgeBackend
    from harness.re_v2.protocol_28.controller import Protocol28Controller
    from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
    from harness.re_v2.canonical import canonical_json_bytes
    context, *_ = reconciliation_fixture(tmp_path)
    old_events = context.events.replay()
    prefix = old_events[:next(i for i, e in enumerate(old_events) if e.type == 'knowledge_workflow_requested')]
    def crash(controller, point):
        if point == 'after_event_before_projection' and controller.event_store.replay()[-1].type == 'provider_capture_recorded':
            raise RuntimeError('first-capture-fault')
    monkeypatch.setattr(Protocol28Controller, '_fault', crash)
    with pytest.raises(RuntimeError, match='first-capture-fault'):
        run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend())
    assert not context.ledger.replay().knowledge_work
    context.paths.events.write_bytes(b''.join(canonical_json_bytes(e.to_json_dict()) for e in prefix))
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError, match='activation|revision|history'):
        load_protocol_28_run_context(context.run_dir)
    assert bytes_under(context.paths.root) == before


@pytest.mark.integration
def test_new_revision_resource_reservation_detects_event_rollback_before_any_new_capture(tmp_path, monkeypatch):
    from tests.unit.test_re_v2_protocol_28_reconciliation import reconciliation_fixture, KnowledgeBackend
    from harness.re_v2.protocol_28.controller import Protocol28Controller
    from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
    context, inputs, _, acquisition, active = reconciliation_fixture(tmp_path)
    assert run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend()).state == 'complete'
    prefix = context.paths.events.read_bytes()
    capture_ids = set(context.ledger.replay().execution_captures)
    cause = expansion_cause(context, acquisition, active)
    revision_module().commit_knowledge_revision(context, inputs, cause)
    def crash(controller, point):
        if point == 'after_event_before_projection' and controller.event_store.replay()[-1].type == 'dispatch_reserved':
            raise RuntimeError('reservation-before-capture-fault')
    monkeypatch.setattr(Protocol28Controller, '_fault', crash)
    backend = KnowledgeBackend()
    with pytest.raises(RuntimeError, match='reservation-before-capture-fault'):
        run_protocol_28_exhaustive(context.run_dir, lambda: backend)
    assert not backend.calls and set(context.ledger.replay().execution_captures) == capture_ids
    context.paths.events.write_bytes(prefix)
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError, match='revision|history'):
        load_protocol_28_run_context(context.run_dir)
    assert bytes_under(context.paths.root) == before


@pytest.mark.integration
@pytest.mark.parametrize('seam', ['provider_capture_recorded', 'knowledge_artifact_recorded',
    'knowledge_feedback_recorded', 'after_knowledge_root_object', 'knowledge_root_recorded'])
def test_reconciliation_capture_feedback_and_root_faults_reuse_invocations(tmp_path, monkeypatch, seam):
    from tests.unit.test_re_v2_protocol_28_reconciliation import reconciliation_fixture, KnowledgeBackend
    from harness.re_v2.protocol_28.controller import Protocol28Controller
    from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
    context, *_ = reconciliation_fixture(tmp_path)
    backend = KnowledgeBackend(failure='cross-slice-call-chains' if seam == 'knowledge_feedback_recorded' else None)
    fired = False
    def crash(controller, point):
        nonlocal fired
        event = controller.event_store.replay()[-1]
        relevant = event.type == seam and (seam != 'provider_capture_recorded' or
            any(c.get('kind') == 'knowledge-reconciliation' for _, c in backend.calls))
        if not fired and ((point == 'after_event_before_projection' and relevant) or point == seam):
            fired = True
            raise RuntimeError('synthetic-reconciliation-fault')
    monkeypatch.setattr(Protocol28Controller, '_fault', crash)
    with pytest.raises(RuntimeError, match='synthetic-reconciliation-fault'):
        run_protocol_28_exhaustive(context.run_dir, lambda: backend)
    call_count = len(backend.calls)
    before = bytes_under(context.paths.root)
    revision_module().load_knowledge_revision(load_protocol_28_run_context(context.run_dir))
    assert bytes_under(context.paths.root) == before
    result = run_protocol_28_exhaustive(context.run_dir, lambda: backend)
    assert result.state == ('needs-attention' if seam == 'knowledge_feedback_recorded' else 'complete')
    assert len(backend.calls) == len(context.ledger.replay().execution_captures)
    assert len(backend.calls) >= call_count
    before = bytes_under(context.paths.root)
    assert run_protocol_28_exhaustive(context.run_dir, lambda: pytest.fail('terminal recovery invoked provider')) == result
    assert bytes_under(context.paths.root) == before
