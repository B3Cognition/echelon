"""The public lifecycle must independently reconcile every target and source."""
from dataclasses import replace
import importlib
import json

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_accounting import KnowledgeDispatchPolicy
from harness.re_v2.protocol_28.artifacts import EvidenceAnchorV1, ExhaustiveClaimV1, ExhaustiveObservationV1, ExhaustiveEvidenceSliceV1, ExhaustiveVerificationV1
from harness.re_v2.protocol_28.lifecycle import L4DispatchResultV1, run_protocol_28_exhaustive
from harness.re_v2.protocol_28.status import protocol_28_status_document
from tests.unit.test_re_v2_knowledge_revision import revision_fixture, revision_module, bytes_under, assert_bounded_revision_replay


def reconciliation_module():
    return importlib.import_module('harness.re_v2.protocol_28.reconciliation')


def reconciliation_fixture(tmp_path, *, debt=False, **kwargs):
    context, inputs, account, acquisition = revision_fixture(tmp_path,
        account_policy=KnowledgeDispatchPolicy(5_000_000, 10_800_000, 3), l4_limits=(5_000_000, 10_800_000), **kwargs)
    active = revision_module().activate_knowledge_workflow(context, account, allow_debt=debt)
    return context, inputs, account, acquisition, active


class KnowledgeBackend:
    """Script only the remote response; storage/account/review boundaries are real."""
    def __init__(self, *, failure=None, mutate=None):
        self.calls = []
        self.failure = failure
        self.mutate = mutate

    def execute(self, role, agent, payload, schema, reservation):
        context = json.loads(payload)
        self.calls.append((role, context))
        if context.get('kind') == 'knowledge-reconciliation':
            module = reconciliation_module()
            work = module.KnowledgeReconciliationWorkItemV1.from_json_dict(context['work_item'])
            if role == 'producer':
                checks = tuple(sorted((module.KnowledgeReconciliationCheckV1(1, name, 'supported',
                    work.evidence_ids, work.input_result_ids, (), 'The supplied scope was investigated.')
                    for name in module.RECONCILIATION_CHECKS), key=lambda r: r.identity))
                value = module.KnowledgeReconciliationCandidateV1(1, work.identity, work.obligation_ids,
                    work.input_result_ids, checks, (), 'Supported reconciled knowledge.').to_json_dict()
            else:
                candidate = module.KnowledgeReconciliationCandidateV1.from_json_dict(context['candidate'])
                checks = candidate.checks
                verdict = 'PASS'
                if self.failure:
                    checks = tuple(sorted((replace(c, disposition='failed', detail=self.failure)
                        if c.check == self.failure else c for c in checks), key=lambda r: r.identity))
                    verdict = 'REPAIR'
                value = module.KnowledgeReconciliationReviewV1(1, work.identity, candidate.identity,
                    verdict, checks, (), 'Independent scope and support assessment.').to_json_dict()
            if self.mutate:
                value = self.mutate(role, context, value)
        else:
            entry = context['plan_entry']
            if role == 'producer':
                anchors = tuple(sorted((EvidenceAnchorV1.from_json_dict(row['anchor'])
                    for row in context['permitted_evidence_anchors']), key=lambda r: r.identity))
                claim = ExhaustiveClaimV1(1, 'behavioral', tuple(sorted(entry['primary_subject_ids'] + entry['supporting_subject_ids'])),
                    tuple(a.identity for a in anchors), 'The fixture provides the observed behavior.')
                observation = ExhaustiveObservationV1(1, 'applicable', entry['category_id'],
                    tuple(entry['primary_subject_ids']), tuple(entry['primary_snapshot_evidence_ids']), (),
                    'Supported behavior in the exact slice.')
                value = ExhaustiveEvidenceSliceV1(1, context['slice_spec_id'], context['plan_entry_id'],
                    entry['target_kind'], entry['source_id'], entry['target_id'], entry['category_id'],
                    tuple(entry['primary_subject_ids']), tuple(entry['primary_source_record_ids']),
                    tuple(entry['primary_snapshot_evidence_ids']), anchors, (claim,), (observation,),
                    tuple(entry['assigned_finding_ids']), (), 'Supported fixture behavior.').to_json_dict()
            else:
                candidate = context['candidate']
                value = ExhaustiveVerificationV1(1, context['slice_spec_id'], context['candidate_id'],
                    entry['verifier_contract_hash'], 'PASS', (), tuple(candidate['covered_primary_evidence_ids']),
                    tuple(candidate['addressed_finding_ids'])).to_json_dict()
        return L4DispatchResultV1(canonical_json_bytes(value), 'fixture', 'fixture-model',
            '2026-09-09T12:00:00Z', '2026-09-09T12:00:01Z', 1000,
            token_status='trusted_exact', billable_tokens=5, active_status='trusted_exact', active_ms=1000)


@pytest.mark.unit
def test_live_incomplete_reviewed_work_is_running_not_terminally_blocked(tmp_path):
    context, *_ = reconciliation_fixture(tmp_path)
    status = protocol_28_status_document(context.run_dir)
    assert status['status'] == 'running'
    assert 'blocked' not in status['banner'].lower()
    assert status['post_l4'] == {'synthesis': 'not run', 'publication': 'not run'}


@pytest.mark.unit
def test_slice_pass_requires_separate_target_and_source_reviews_before_completion(tmp_path, monkeypatch):
    context, _, _, _, active = reconciliation_fixture(tmp_path)
    backend = KnowledgeBackend()
    result = run_protocol_28_exhaustive(context.run_dir, lambda: backend)
    assert result.state == 'complete'
    reconciliations = [(role, c['work_item']['scope']) for role, c in backend.calls
                      if c.get('kind') == 'knowledge-reconciliation']
    assert reconciliations == [('producer', 'target'), ('verifier', 'target'),
                              ('producer', 'target'), ('verifier', 'target'),
                              ('producer', 'source'), ('verifier', 'source')]
    for role, value in backend.calls:
        if value.get('kind') == 'knowledge-reconciliation' and role == 'verifier':
            assert value['candidate'] and 'producer_reasoning' not in value
        if value.get('kind') == 'knowledge-reconciliation':
            authority = value['response_authority']
            work = value['work_item']
            assert authority['work_item_id'] == content_digest(
                canonical_json_bytes(work)
            )
            assert authority.get('candidate_id') == (
                content_digest(canonical_json_bytes(value['candidate']))
                if value['candidate'] is not None
                else None
            )
            assert authority['obligation_ids'] == work['obligation_ids']
            assert authority['input_result_ids'] == work['input_result_ids']
            assert authority['each_check_result_ids'] == work['input_result_ids']
            assert authority['permitted_check_evidence_ids'] == work['evidence_ids']
            assert authority['minimum_check_evidence_ids'] == (
                1 if work['evidence_ids'] else 0
            )
    assert protocol_28_status_document(context.run_dir)['status'] == 'complete'
    before = bytes_under(context.paths.root)
    assert run_protocol_28_exhaustive(context.run_dir, lambda: pytest.fail('completed replay requested a provider')) == result
    assert_bounded_revision_replay(context, active, monkeypatch)
    assert bytes_under(context.paths.root) == before


@pytest.mark.unit
def test_provider_reconciliation_set_order_is_normalized_before_authority(tmp_path):
    context, *_ = reconciliation_fixture(tmp_path)

    def reverse_set_order(role, supplied, value):
        if role == 'producer':
            value['checks'] = list(reversed(value['checks']))
        return value

    result = run_protocol_28_exhaustive(
        context.run_dir,
        lambda: KnowledgeBackend(mutate=reverse_set_order),
    )

    assert result.state == 'complete'
    assert result.run_root_id is not None


@pytest.mark.unit
def test_reconciliation_replay_never_screens_context_as_provider_output(tmp_path, monkeypatch):
    module = reconciliation_module()
    validate_output = module.validate_provider_output

    def output_only(payload):
        decoded = json.loads(payload)
        if decoded.get('kind') == 'knowledge-reconciliation':
            raise AssertionError('provider context reached the provider-output validator')
        return validate_output(payload)

    monkeypatch.setattr(module, 'validate_provider_output', output_only)
    context, *_ = reconciliation_fixture(tmp_path)

    result = run_protocol_28_exhaustive(
        context.run_dir,
        lambda: KnowledgeBackend(),
    )

    assert result.state == "complete"
    assert result.run_root_id is not None


@pytest.mark.unit
@pytest.mark.parametrize('failure', ['cross-slice-call-chains', 'contradictions', 'evidence-support',
                                  'category-coverage', 'dependency-continuity', 'omitted-work', 'inherited-debt'])
def test_reviewer_failure_is_durable_and_unchanged_fingerprint_stops_calls(tmp_path, failure):
    context, *_ = reconciliation_fixture(tmp_path)
    backend = KnowledgeBackend(failure=failure)
    result = run_protocol_28_exhaustive(context.run_dir, lambda: backend)
    assert result.state == 'needs-attention'
    assert result.run_root_id is None
    producer_contexts = [c for role, c in backend.calls if role == 'producer' and c.get('kind') == 'knowledge-reconciliation']
    assert len(producer_contexts) == 2
    assert producer_contexts[1]['feedback'][0]['check'] == failure
    repair = producer_contexts[1]['repair_protocol']
    assert repair['failed_check_names'] == [failure]
    assert repair['required_outcome'] == 'supported-or-explicitly-unknown'
    assert repair['unsupported_claim_action'] == 'remove-or-narrow'
    assert repair['contradiction_action'] == 'preserve-as-explicit-conflict'
    assert repair['debt_action'] == 'dependency-ambiguity-only'
    count = len(backend.calls)
    repeated = run_protocol_28_exhaustive(context.run_dir, lambda: backend)
    assert repeated.state == 'needs-attention' and len(backend.calls) == count


@pytest.mark.unit
def test_unchanged_reviewed_refresh_status_recommends_ordinary_immutable_retry(tmp_path):
    context, *_ = reconciliation_fixture(tmp_path)
    result = run_protocol_28_exhaustive(
        context.run_dir,
        lambda: KnowledgeBackend(failure='contradictions'),
    )
    assert result.reason_code == 'unchanged-reconciliation-outcome'

    from harness.re_v2.knowledge_revision import load_knowledge_revision

    active = load_knowledge_revision(context)
    request_dir = context.paths.root.parent.parent / active.manifest.logical_run_id / 'v2'
    request_dir.mkdir(parents=True, exist_ok=True)
    request_dir.joinpath('knowledge-creation.json').write_bytes(canonical_json_bytes({
        'schema_version': 1,
        'kind': 'reviewed_analysis_creation_intent',
        'request_run_id': active.manifest.logical_run_id,
        'analysis_run_id': context.run_dir.name,
        'created_at': '2026-09-12T12:00:00Z',
        'snapshot_id': context.inputs.manifest.source_snapshot_id,
        'workspace_partition_id': content_digest(b'fixture-partition'),
        'selection': {
            'schema_version': 1,
            'all_sources': False,
            'source_ids': ['repo-a'],
            'domain_keys': [],
        },
        'source_depths': [['repo-a', 'standard']],
        'token_limit': 5_000_000,
        'active_ms_limit': 10_800_000,
    }))

    status = protocol_28_status_document(context.run_dir)

    assert status['next_action'].startswith(
        'run `echelon re refresh --source repo-a --depth standard`'
    )
    assert 'new immutable reviewed attempt' in status['next_action']
    assert 'resume' not in status['next_action']


@pytest.mark.unit
def test_legacy_frozen_reconciler_replays_without_new_repair_context_field(tmp_path):
    context, _, _, _, active = reconciliation_fixture(tmp_path)
    module = reconciliation_module()
    run_protocol_28_exhaustive(
        context.run_dir,
        lambda: KnowledgeBackend(failure='contradictions'),
    )
    work = next(iter(context.ledger.replay().knowledge_work.values()))
    check = module.KnowledgeReconciliationCheckV1(
        1,
        'contradictions',
        'failed',
        work.evidence_ids,
        work.input_result_ids,
        (),
        'The frozen legacy review found a contradiction.',
    )
    legacy_contract_id = context.objects.put_blob(
        b'legacy reconciler contract without structured repair guidance'
    )
    legacy_active = replace(
        active,
        authorization=replace(
            active.authorization,
            reconciler_contract_id=legacy_contract_id,
        ),
    )

    payload = json.loads(module._reconciliation_context(
        context,
        legacy_active,
        context.ledger.replay(),
        work,
        role='producer',
        feedback=(check,),
    ))

    assert payload['feedback'][0]['check'] == 'contradictions'
    assert 'repair_protocol' not in payload


@pytest.mark.unit
@pytest.mark.parametrize('mutation', ['omitted-obligation', 'unsupported-evidence', 'unsupported-absence'])
def test_false_pass_cannot_waive_deterministic_reconciliation_failure(tmp_path, mutation):
    context, *_ = reconciliation_fixture(tmp_path)
    def mutate(role, supplied, value):
        if role != 'producer':
            return value
        if mutation == 'omitted-obligation':
            value['obligation_ids'] = value['obligation_ids'][:-1]
        elif mutation == 'unsupported-evidence':
            value['checks'][0]['evidence_ids'] = [content_digest(b'not-in-snapshot')]
        else:
            value['checks'][0]['disposition'] = 'unsupported-absence'
        return value
    result = run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend(mutate=mutate))
    assert result.state == 'needs-attention' and result.run_root_id is None


@pytest.mark.unit
def test_aggregate_resource_exhaustion_cannot_become_debt(tmp_path):
    context, inputs, account, _ = revision_fixture(tmp_path)
    revision_module().activate_knowledge_workflow(context, account, allow_debt=True)
    result = run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend())
    assert result.state == 'needs-attention' and result.run_root_id is None
    assert protocol_28_status_document(context.run_dir)['limitations'] == []


@pytest.mark.unit
@pytest.mark.parametrize('forgery', ['alternate-manifest', 'missing', 'extra', 'forged'])
def test_public_reconciliation_rejects_noncommitted_or_inexact_revision_before_reservation(tmp_path, monkeypatch, forgery):
    from harness.re_v2.protocol_28.controller import Protocol28Controller
    from harness.re_v2.ledger import ReV2LedgerError
    context, _, _, _, active = reconciliation_fixture(tmp_path)
    def crash(controller, point):
        if point == 'after_event_before_projection' and controller.event_store.replay()[-1].type == 'knowledge_work_realized':
            raise RuntimeError('work-realized-fault')
    monkeypatch.setattr(Protocol28Controller, '_fault', crash)
    with pytest.raises(RuntimeError, match='work-realized-fault'):
        run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend())
    monkeypatch.setattr(Protocol28Controller, '_fault', lambda *_: None)
    work = next(iter(context.ledger.replay().knowledge_work.values()))
    rows = active.dependencies.obligations
    if forgery == 'missing':
        rows = tuple(r for r in rows if r.obligation_id not in work.obligation_ids or r.entry_ids)
    elif forgery == 'extra':
        rows = (*rows, replace(rows[0], obligation_id=content_digest(b'forged-extra-obligation')))
    elif forgery == 'forged':
        rows = (replace(rows[0], origin_obligation_ids=(content_digest(b'forged-origin'),)), *rows[1:])
    dependencies = replace(active.dependencies, obligations=tuple(sorted(rows, key=lambda r: r.identity)))
    revision_module()._put(context.objects, dependencies)
    manifest = replace(active.manifest, dependency_map_id=dependencies.identity,
        expansion_rounds=1 if forgery == 'alternate-manifest' else active.manifest.expansion_rounds,
        child_ids=tuple(sorted((set(active.manifest.child_ids) - {active.dependencies.identity}) | {dependencies.identity})))
    revision_module()._put(context.objects, manifest)
    obligations = tuple(sorted(r.obligation_id for r in rows if r.source_id == work.source_id and
        (r.target_kind, r.target_id) == (work.target_kind, work.target_id)))
    categories = tuple(sorted(r.identity for b in revision_module()._bundles(context.inputs)
        for r in b.category_assessments if r.obligation_id in obligations))
    forged = replace(work, revision_manifest_id=manifest.identity, obligation_ids=obligations,
        category_assessment_ids=categories)
    revision_module()._put(context.objects, forged)
    before = bytes_under(context.paths.root)
    with pytest.raises((ValueError, ReV2LedgerError)):
        context.ledger.record_knowledge_work(forged)
    assert bytes_under(context.paths.root) == before
    with pytest.raises((ValueError, ReV2LedgerError)):
        reconciliation_module().execute_reconciliation(context, KnowledgeBackend(), forged)
    assert bytes_under(context.paths.root) == before
    # Even rehashing a temporary committed pointer cannot bypass the same ledger verifier.
    if forgery != 'alternate-manifest':
        pointer = replace(active.pointer, revision_manifest_id=manifest.identity)
        revision_module()._put(context.objects, pointer)
        events = context.events.replay()
        context.paths.events.write_bytes(b'')
        for event in events:
            payload = dict(event.payload)
            if event.type == 'knowledge_workflow_activated':
                payload['pointer_id'] = pointer.identity
            context.events.append(event.type, payload, occurred_at=event.occurred_at)
        before = bytes_under(context.paths.root)
        with pytest.raises((ValueError, ReV2LedgerError)):
            context.ledger.record_knowledge_work(forged)
        assert bytes_under(context.paths.root) == before


@pytest.mark.unit
def test_reconciler_role_phase_and_schema_are_frozen_neutral_contracts():
    from pathlib import Path
    import yaml
    from tests.unit.test_re_v2_protocol_28_roles import _agent
    root = Path(__file__).resolve().parents[2]
    metadata, body = _agent(root / 'prosaic/subagents/echelon.re-knowledge-reconciler.md')
    assert metadata['name'] == 'echelon.re-knowledge-reconciler' and metadata['tools'] == ''
    assert body.count('ALWAYS ') == body.count('NEVER ') >= 8
    assert 'fresh context' in body and 'producer reasoning' in body and 'echelon_result:' in body
    phase = (root / 'runtime/workflow/phases/re-knowledge-reconciliation.md').read_text()
    assert len(phase.splitlines()) < 90 and 'KnowledgeReconciliationWorkItemV1' in phase
    flow = yaml.safe_load((root / 'runtime/workflow/definition.yaml').read_text())['re_knowledge_reconciliation']
    assert flow['enabled'] is False and flow['resource_account'] == 'same_logical_run'
    assert flow['agent'] == metadata['name']
    schema = reconciliation_module().reconciliation_response_schema()
    assert schema['oneOf'][0]['additionalProperties'] is False
    assert schema['oneOf'][1]['additionalProperties'] is False


@pytest.mark.unit
@pytest.mark.parametrize('failure', ['exception', 'unsafe-output'])
def test_provider_or_security_failure_is_attention_not_debt_and_never_reinvoked(tmp_path, failure):
    context, inputs, _, acquisition, active = reconciliation_fixture(tmp_path, debt=True)
    marker = 'synthetic-fixture-only-password'
    def mutate(role, supplied, value):
        if role == 'producer':
            if failure == 'exception':
                raise RuntimeError('synthetic-provider-failure')
            value['rendered_markdown'] = 'password = ' + marker
        return value
    backend = KnowledgeBackend(mutate=mutate)
    result = run_protocol_28_exhaustive(context.run_dir, lambda: backend)
    assert result.state == 'needs-attention' and result.run_root_id is None
    from harness.re_v2.protocol_28.context import load_protocol_28_run_context
    from harness.re_v2.protocol_28.budget import PairedReservationCommitV1, VerifierReleaseV1
    from harness.re_v2.protocol_28.events import replay_protocol_28
    from tests.unit.test_re_v2_knowledge_revision import expansion_cause
    reopened = load_protocol_28_run_context(context.run_dir)
    pair = [r for r in reopened.resources.records if isinstance(r, PairedReservationCommitV1)][-1]
    releases = [r for r in reopened.resources.records if isinstance(r, VerifierReleaseV1)]
    assert len(releases) == 1, 'never-started verifier capacity must be durably released'
    assert releases[0].pair_id == pair.identity
    assert releases[0].reason == 'producer_abandoned'
    state = replay_protocol_28(reopened.events.replay())
    assert state.dispatches[pair.verifier_dispatch_id].stage == 'abandoned'
    assert reopened.resources.decision.open_token_reservations == 0
    assert reopened.resources.decision.open_active_ms_reservations == 0
    if failure == 'exception':
        assert state.dispatches[pair.producer_dispatch_id].stage == 'abandoned'
        assert reopened.resources.decision.charged_tokens >= pair.producer_reservation.billable_tokens
    count = len(backend.calls)
    before = bytes_under(context.paths.root)
    assert run_protocol_28_exhaustive(context.run_dir, lambda: pytest.fail('failed replay invoked provider')).state == 'needs-attention'
    assert bytes_under(context.paths.root) == before
    assert len(backend.calls) == count
    assert protocol_28_status_document(context.run_dir)['limitations'] == []
    assert all(marker.encode() not in data for name, data in bytes_under(context.paths.root).items()
        if not name.startswith('knowledge-quarantine/'))
    cause = expansion_cause(reopened, acquisition, active)
    revised = revision_module().commit_knowledge_revision(reopened, inputs, cause)
    assert revised.manifest.revision_id != active.manifest.revision_id
