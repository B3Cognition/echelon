from dataclasses import replace
import importlib

import pytest

from harness.re_v2.canonical import content_digest
from tests.unit.test_re_v2_knowledge_revision import bytes_under
from tests.unit.test_re_v2_protocol_28_reconciliation import reconciliation_fixture


@pytest.mark.unit
def test_explicit_debt_resolution_requires_exact_independent_review_not_ordinary_pass():
    from tests.unit.test_re_v2_protocol_28_reconciliation import reconciliation_module
    module = reconciliation_module()
    key = content_digest(b'exact-fixture-authority')
    work = module.KnowledgeReconciliationWorkItemV1(1, 'knowledge', key, key, key, key,
        'target', 'api', 'domain', 'orders', key, (key,), (key,), (key,), (key,), (key,), 0, 0)
    checks = tuple(sorted((module.KnowledgeReconciliationCheckV1(1, name, 'supported',
        work.evidence_ids, work.input_result_ids, (), 'The exact inherited scope is supported.')
        for name in module.RECONCILIATION_CHECKS), key=lambda row: row.identity))
    base = module.KnowledgeReconciliationCandidateV1(1, work.identity, work.obligation_ids,
        work.input_result_ids, checks, (), 'Explicit closure proposal.')
    resolution = {'schema_version': 1, 'work_item_id': work.identity, 'acceptance_id': key,
        'debt_ids': [key], 'obligation_ids': [key], 'evidence_ids': [key],
        'acquisition_outcome_ids': [key], 'explanation': 'Newly acquired evidence resolves this exact debt.'}
    candidate = module.KnowledgeReconciliationCandidateV1.from_json_dict({
        **base.to_json_dict(), 'debt_resolutions': [resolution]})
    ordinary = module.KnowledgeReconciliationReviewV1(1, work.identity, candidate.identity,
        'PASS', checks, (), 'Independent review.')
    with pytest.raises(ValueError, match='debt|resolution|closure'):
        module.validate_reconciliation_review(work, candidate, ordinary)
    exact = module.KnowledgeReconciliationReviewV1.from_json_dict({
        **ordinary.to_json_dict(), 'resolved_debt_candidate_ids': [content_digest(resolution)]})
    module.validate_reconciliation_review(work, candidate, exact)
    with pytest.raises(ValueError, match='debt|resolution|closure'):
        module.validate_reconciliation_review(work, candidate,
            replace(exact, resolved_debt_candidate_ids=(content_digest(b'other debt'),)))


def _rebind_inherited_receipt(inputs, acceptance, replacement=None, *, keep_original=False,
        bind_replacement=True):
    """Rebuild every caller-owned dependent ID, preserving the genuine L3 parent."""
    from harness.re_v2.canonical import canonical_json_bytes
    from harness.re_v2.protocol_28.preparation import (_rebind_composition_dependencies,
        _bind_exact_context_sizes, _required_lower_authority_ids)
    from harness.re_v2.protocol_28.safe_evidence import build_safe_lower_authority_catalog
    from tests.unit.test_re_v2_knowledge_revision import revision_module
    opaque = {key: payload for key, payload in inputs.authority_objects.items() if key != acceptance.identity}
    if replacement is not None:
        opaque[replacement.identity] = canonical_json_bytes(replacement.to_json_dict())
    plan = replace(inputs.exhaustive_plan, target_plans=_rebind_composition_dependencies(tuple(
        replace(target, entries=tuple(replace(entry, required_lower_authority_ids=tuple(sorted({
            *(key for key in entry.required_lower_authority_ids if key != acceptance.identity),
            *((replacement.identity,) if replacement and bind_replacement else ())}))) for entry in target.entries))
        for target in inputs.exhaustive_plan.target_plans)))
    safe_lower = build_safe_lower_authority_catalog(opaque, _required_lower_authority_ids(plan))
    plan = _bind_exact_context_sizes(plan, inputs.l3_projection_catalog, inputs.snapshot_evidence_catalog,
        inputs.exhaustive_subject_catalog, inputs.exhaustive_policy, opaque,
        inputs.safe_snapshot_evidence_catalog, safe_lower, reviewed=revision_module()._bundles(inputs))
    request = replace(inputs.manifest.exhaustive_request, exhaustive_plan_id=plan.identity,
        safe_lower_authority_catalog_id=safe_lower.identity)
    manifest = replace(inputs.manifest, exhaustive_plan_id=plan.identity, exhaustive_request=request,
        safe_lower_authority_catalog_id=safe_lower.identity)
    if keep_original:
        opaque[acceptance.identity] = inputs.authority_objects[acceptance.identity]
    return dict(manifest=manifest, exhaustive_plan=plan, authority_objects=opaque,
        safe_lower_authority_catalog=safe_lower)


@pytest.mark.unit
@pytest.mark.parametrize('mutation', ['missing', 'review', 'closure', 'source', 'extra', 'lower-plan'])
def test_initial_reviewed_admission_rejects_self_consistent_stripped_or_rebound_l3_debt_before_writes(tmp_path, mutation):
    from tests.unit.test_re_v2_protocol_28_preparation import _accepted_debt_fixture
    from tests.integration.test_re_v2_knowledge_activation import reviewed_preparation_fixture
    from harness.re_v2.protocol_28.inputs import Protocol28InputError, stage_exhaustive_inputs
    fixture = _accepted_debt_fixture(tmp_path / 'parent')
    acceptance = fixture[-1]
    preparation, workspace, intent, parent, options, _ = reviewed_preparation_fixture(
        tmp_path / 'reviewed', prepared=fixture[:4])
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    assert inputs.parent_authority_bundle.unresolved_deeper_finding_ids == ()
    assert any(p.unresolved_finding_ids for p in inputs.l3_projection_catalog.projections)
    other_review = replace(acceptance, guidance_directive_hash=content_digest(b'other independent review'))
    receipt, settings = {
        'missing': (None, {}),
        'review': (other_review, {}),
        'closure': (replace(acceptance, closure_root_hash=content_digest(b'other closure')), {}),
        'source': (replace(acceptance, source_root_hashes=(('api', content_digest(b'other source root')),)), {}),
        'extra': (other_review, {'keep_original': True}),
        'lower-plan': (acceptance, {'bind_replacement': False}),
    }[mutation]
    rebound = _rebind_inherited_receipt(inputs, acceptance, receipt, **settings)
    before = bytes_under(tmp_path)
    with pytest.raises((ValueError, Protocol28InputError), match='debt|authority|parent'):
        stripped = replace(inputs, **rebound)
        stage_exhaustive_inputs(tmp_path / 'forbidden', stripped)
    assert bytes_under(tmp_path) == before


def _rewrite_event_chain(context, tmp_path, original, mutate):
    """Use canonical event storage; only the synthetic run's event bytes change."""
    import json
    from harness.re_v2.events import EventStore
    from harness.re_v2.protocol_28.events import PROTOCOL_28_EVENTS
    rows = mutate([json.loads(line) for line in original.splitlines()])
    tmp_path.mkdir(parents=True)
    store = EventStore(tmp_path / 'events.jsonl', protocol=PROTOCOL_28_EVENTS)
    store.append_batch((row['type'], row['payload'], row['occurred_at']) for row in rows)
    context.events.path.write_bytes(store.path.read_bytes())


@pytest.mark.unit
def test_inherited_debt_event_payloads_cannot_downgrade_immutable_completed_roots(tmp_path):
    from tests.unit.test_re_v2_protocol_28_preparation import _accepted_debt_fixture
    from tests.unit.test_re_v2_protocol_28_reconciliation import KnowledgeBackend
    from tests.unit.test_re_v2_knowledge_revision import revision_module
    from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
    from harness.re_v2.protocol_28.status import Protocol28StatusError, protocol_28_status_document
    fixture = _accepted_debt_fixture(tmp_path / 'parent')
    context, *_ = reconciliation_fixture(tmp_path / 'reviewed', prepared=fixture[:4])
    result = run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend())
    assert result.state == 'complete-with-limitations'
    original = context.events.path.read_bytes()
    def remove_debt(rows):
        for row in rows:
            if row['type'] == 'knowledge_run_completed' or (row['type'] == 'knowledge_root_recorded'
                    and row['payload']['root_kind'] == 'run'):
                row['payload']['debt_ids'] = []
        return rows
    _rewrite_event_chain(context, tmp_path / 'attack', original, remove_debt)
    before = bytes_under(context.paths.root)
    for reader in (lambda: revision_module().load_knowledge_revision(context),
            lambda: protocol_28_status_document(context.run_dir),
            lambda: run_protocol_28_exhaustive(context.run_dir, lambda: pytest.fail('tampered replay invoked provider'))):
        with pytest.raises((ValueError, Protocol28StatusError), match='root|authority|debt'):
            reader()
        assert bytes_under(context.paths.root) == before


@pytest.mark.unit
@pytest.mark.parametrize('completion_type', ['knowledge_run_completed', 'run_completed'])
def test_reviewed_completion_cannot_substitute_historical_root_events(tmp_path, completion_type):
    from tests.unit.test_re_v2_protocol_28_preparation import _accepted_debt_fixture
    from tests.unit.test_re_v2_protocol_28_reconciliation import KnowledgeBackend
    from tests.unit.test_re_v2_knowledge_revision import revision_module
    from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
    fixture = _accepted_debt_fixture(tmp_path / 'parent')
    context, *_ = reconciliation_fixture(tmp_path / 'reviewed', prepared=fixture[:4])
    result = run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend())
    assert result.state == 'complete-with-limitations'
    def substitute(rows):
        for row in rows:
            if row['type'] == 'knowledge_root_recorded' and row['payload']['root_kind'] == 'run':
                row['type'] = 'root_recorded'
                row['payload'].pop('revision_id')
                row['payload'].pop('debt_ids')
        completion = rows[-1]
        assert completion['type'] == 'knowledge_run_completed'
        if completion_type == 'knowledge_run_completed':
            completion['payload']['debt_ids'] = []
        else:
            rows.insert(-1, dict(completion, type='materialization_completed', payload={'root_id': result.run_root_id}))
            completion['type'] = 'run_completed'
            completion['payload'] = {'run_root_id': result.run_root_id, 'completion_kind': 'evidence_only'}
        return rows
    _rewrite_event_chain(context, tmp_path / 'attack', context.events.path.read_bytes(), substitute)
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError, match='root|authority|completion'):
        revision_module().load_knowledge_revision(context)
    assert bytes_under(context.paths.root) == before


@pytest.mark.unit
@pytest.mark.parametrize('mutation', ['target-slices-missing', 'target-slices-rebound',
    'source-slices-extra', 'source-lower-missing', 'source-kind', 'target-debt-extra',
    'source-debt-extra', 'duplicate-target', 'duplicate-source', 'duplicate-run'])
def test_root_event_fields_must_equal_the_immutable_authenticated_root(tmp_path, mutation):
    from tests.unit.test_re_v2_protocol_28_reconciliation import KnowledgeBackend
    from tests.unit.test_re_v2_knowledge_revision import revision_module
    from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
    context, *_ = reconciliation_fixture(tmp_path)
    assert run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend()).state == 'complete'
    original = context.events.path.read_bytes()
    def mutate(rows):
        roots = [r for r in rows if r['type'] == 'knowledge_root_recorded']
        targets = [r for r in roots if r['payload']['root_kind'] == 'target']
        target = targets[-1] if mutation == 'target-slices-rebound' else targets[0]
        source = next(r for r in roots if r['payload']['root_kind'] == 'source')
        run = next(r for r in roots if r['payload']['root_kind'] == 'run')
        if mutation == 'target-slices-missing':
            target['payload']['required_accepted_slice_ids'] = []
        elif mutation == 'target-slices-rebound':
            target['payload']['required_accepted_slice_ids'] = next(r['payload']['required_accepted_slice_ids']
                for r in roots if r is not target and r['payload']['root_kind'] == 'target')
        elif mutation == 'source-slices-extra':
            source['payload']['required_accepted_slice_ids'] = target['payload']['required_accepted_slice_ids']
        elif mutation == 'source-lower-missing':
            source['payload']['required_root_ids'] = []
        elif mutation == 'source-kind':
            source['payload']['root_kind'] = 'target'
            source['payload']['required_root_ids'] = []
        elif mutation in {'target-debt-extra', 'source-debt-extra'}:
            (target if mutation.startswith('target') else source)['payload']['debt_ids'] = [content_digest(b'forged debt')]
        else:
            root = {'duplicate-target': target, 'duplicate-source': source, 'duplicate-run': run}[mutation]
            rows.insert(rows.index(root), root)
        return rows
    _rewrite_event_chain(context, tmp_path / 'attack', original, mutate)
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError, match='root|authority|debt'):
        revision_module().load_knowledge_revision(context)
    assert bytes_under(context.paths.root) == before


@pytest.mark.unit
def test_revision_cannot_remove_inherited_acceptance_without_an_authenticated_resolution(tmp_path):
    from dataclasses import replace
    from tests.unit.test_re_v2_protocol_28_preparation import _accepted_debt_fixture
    from tests.unit.test_re_v2_protocol_28_reconciliation import reconciliation_fixture
    from tests.unit.test_re_v2_knowledge_revision import revision_module, expansion_cause, bytes_under
    from harness.re_v2.protocol_28.preparation import (_rebind_composition_dependencies,
        _bind_exact_context_sizes, _required_lower_authority_ids)
    from harness.re_v2.protocol_28.safe_evidence import build_safe_lower_authority_catalog
    from harness.re_v2.protocol_28.inputs import Protocol28InputError
    fixture = _accepted_debt_fixture(tmp_path / 'parent')
    acceptance = fixture[-1]
    context, inputs, _, acquisition, active = reconciliation_fixture(tmp_path / 'reviewed', prepared=fixture[:4])
    opaque = {key: payload for key, payload in inputs.authority_objects.items() if key != acceptance.identity}
    plan = replace(inputs.exhaustive_plan, target_plans=_rebind_composition_dependencies(tuple(
        replace(target, entries=tuple(replace(entry, required_lower_authority_ids=tuple(
            key for key in entry.required_lower_authority_ids if key != acceptance.identity)) for entry in target.entries))
        for target in inputs.exhaustive_plan.target_plans)))
    safe_lower = build_safe_lower_authority_catalog(opaque, _required_lower_authority_ids(plan))
    plan = _bind_exact_context_sizes(plan, inputs.l3_projection_catalog, inputs.snapshot_evidence_catalog,
        inputs.exhaustive_subject_catalog, inputs.exhaustive_policy, opaque,
        inputs.safe_snapshot_evidence_catalog, safe_lower, reviewed=revision_module()._bundles(inputs))
    request = replace(inputs.manifest.exhaustive_request, exhaustive_plan_id=plan.identity,
        safe_lower_authority_catalog_id=safe_lower.identity)
    manifest = replace(inputs.manifest, exhaustive_plan_id=plan.identity, exhaustive_request=request,
        safe_lower_authority_catalog_id=safe_lower.identity)
    cause = expansion_cause(context, acquisition, active)
    before = bytes_under(context.paths.root)
    with pytest.raises((ValueError, Protocol28InputError), match='debt|resolution|authority'):
        # Reject even before a self-consistent replacement reaches revision staging.
        replacement = replace(inputs, manifest=manifest, exhaustive_plan=plan,
            authority_objects=opaque, safe_lower_authority_catalog=safe_lower)
        revision_module().commit_knowledge_revision(context, replacement, cause)
    assert bytes_under(context.paths.root) == before


@pytest.mark.unit
def test_accepted_l3_residual_debt_survives_reviewed_preparation_revision_and_all_roots_without_new_debt_permission(tmp_path):
    from tests.unit.test_re_v2_protocol_28_preparation import _accepted_debt_fixture
    from tests.unit.test_re_v2_protocol_28_reconciliation import reconciliation_fixture, KnowledgeBackend
    from tests.unit.test_re_v2_knowledge_revision import revision_module, expansion_cause, bytes_under
    from harness.re_v2.protocol_28.inputs import protocol_28_residual_debt_acceptance
    from harness.re_v2.protocol_28.context import load_protocol_28_run_context
    from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
    from harness.re_v2.protocol_28.status import protocol_28_status_document
    fixture = _accepted_debt_fixture(tmp_path / 'parent')
    acceptance = fixture[-1]
    context, inputs, _, acquisition, active = reconciliation_fixture(tmp_path / 'reviewed', prepared=fixture[:4])
    assert active.authorization.allow_debt is False
    assert protocol_28_residual_debt_acceptance(inputs) == acceptance
    for target in inputs.exhaustive_plan.target_plans:
        assert all(acceptance.identity in entry.required_lower_authority_ids for entry in target.entries)
    backend = KnowledgeBackend()
    first = run_protocol_28_exhaustive(context.run_dir, lambda: backend)
    assert first.state == 'complete-with-limitations'
    def retained(result):
        reopened = load_protocol_28_run_context(context.run_dir)
        view = reopened.ledger.read_snapshot()[1]
        root = view.knowledge_run_roots[result.run_root_id]
        assert root.debt_acceptance_ids == (acceptance.identity,)
        assert root.debt_ids == acceptance.unresolved_finding_ids
        for lower in (view.knowledge_roots[i] for i in (*root.target_root_ids, *root.source_root_ids)):
            assert lower.debt_acceptance_ids == (acceptance.identity,)
            assert lower.debt_ids == acceptance.unresolved_finding_ids
        status = protocol_28_status_document(context.run_dir)
        assert status['status'] == 'complete-with-limitations' and status['input_quality'] == 'partial'
        assert status['residual_debt_acceptance_hash'] == acceptance.identity
        assert status['limitations'] and 'not close' in status['l3_finding_closure']
    retained(first)
    for role, payload in backend.calls:
        if payload.get('kind') == 'knowledge-reconciliation':
            assert payload['inherited_debt']
            assert payload['work_item']['inherited_debt_acceptance_ids'] == [acceptance.identity]
        else:
            assert payload['residual_debt_acceptance_hash'] == acceptance.identity
    cause = expansion_cause(load_protocol_28_run_context(context.run_dir), acquisition, active)
    revision_module().commit_knowledge_revision(context, inputs, cause)
    retained(run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend()))
    before = bytes_under(context.paths.root)
    run_protocol_28_exhaustive(context.run_dir, lambda: pytest.fail('limited completion invoked a provider'))
    assert bytes_under(context.paths.root) == before

@pytest.mark.unit
def test_exact_investigated_dependency_debt_is_independently_reviewed_and_propagated(tmp_path):
    from tests.unit.test_re_v2_knowledge_revision import revision_module, expansion_cause
    from tests.unit.test_re_v2_protocol_28_reconciliation import KnowledgeBackend, reconciliation_module
    from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
    from harness.re_v2.protocol_28.status import protocol_28_status_document
    context, inputs, _, acquisition, active = reconciliation_fixture(tmp_path, debt=True,
        extra_source_files={'src/orders/handler.py': 'import importlib\ndef handle(name):\n    return importlib.import_module(name).handle()\n'})
    import json
    from harness.re_v2.canonical import canonical_json_bytes
    investigated = next(r.obligation_id for r in active.dependencies.obligations if r.target_kind == 'domain' and r.entry_ids)
    supplied = json.loads(acquisition.boundary.provider_bytes(acquisition.status().binding_id))
    batch = acquisition.boundary.admit(acquisition.status().binding_id, canonical_json_bytes({
        'schema_version': 1, 'kind': 'evidence_requests', 'source_id': 'api', 'requests': [{
            'obligation_id': supplied['origin_obligation_id'], 'reason_class': 'relationship',
            'selector': {'source_id': 'api', 'path': 'plugins/runtime.py', 'byte_start': 0, 'byte_end': 1}}]}))
    cause = revision_module().stage_knowledge_expansion(context, acquisition, batch, (investigated,))
    active = revision_module().commit_knowledge_revision(context, inputs, cause)
    module = importlib.import_module('harness.re_v2.protocol_28.debt')
    def limited(role, supplied, value):
        if supplied['work_item']['scope'] != 'target' or supplied['work_item']['target_kind'] != 'domain':
            return value
        r = reconciliation_module()
        work = r.KnowledgeReconciliationWorkItemV1.from_json_dict(supplied['work_item'])
        if role == 'producer':
            candidate = r.KnowledgeReconciliationCandidateV1.from_json_dict(value)
            debt = module.KnowledgeDebtCandidateV1(1, work.logical_run_id, work.snapshot_id, work.revision_id,
                work.identity, (investigated,), 'dynamic-dependency', work.evidence_ids,
                tuple(sorted(o['outcome_id'] for o in supplied['evidence_request_outcomes'])), (),
                'An investigated external runtime dependency is unavailable in this snapshot.')
            checks = tuple(sorted((replace(c, disposition='uncertain', debt_candidate_ids=(debt.identity,))
                if c.check == 'dependency-continuity' else c for c in candidate.checks), key=lambda c: c.identity))
            return replace(candidate, checks=checks, debt_candidates=(debt,)).to_json_dict()
        review = r.KnowledgeReconciliationReviewV1.from_json_dict(value)
        candidate = r.KnowledgeReconciliationCandidateV1.from_json_dict(supplied['candidate'])
        return replace(review, verdict='ACCEPT_WITH_DEBT', eligible_debt_candidate_ids=(candidate.debt_candidates[0].identity,)).to_json_dict()
    backend = KnowledgeBackend(mutate=limited)
    result = run_protocol_28_exhaustive(context.run_dir, lambda: backend)
    assert result.state == 'complete-with-limitations'
    status = protocol_28_status_document(context.run_dir)
    assert status['status'] == 'complete-with-limitations' and len(status['limitations']) == 1
    view = context.ledger.replay()
    root = view.knowledge_run_roots[result.run_root_id]
    target = next(r for r in view.knowledge_roots.values() if r.scope == 'target' and r.target_kind == 'domain')
    source = next(r for r in view.knowledge_roots.values() if r.scope == 'source')
    assert root.debt_ids == source.debt_ids == target.debt_ids == (status['limitations'][0]['debt_id'],)
    assert root.debt_acceptance_ids == source.debt_acceptance_ids == target.debt_acceptance_ids
    assert target.authorization_id == source.authorization_id == root.authorization_id == active.authorization.identity
    before = bytes_under(context.paths.root)
    assert run_protocol_28_exhaustive(context.run_dir, lambda: pytest.fail('debt replay called provider')) == result
    assert bytes_under(context.paths.root) == before
    original = context.events.path.read_bytes()
    def remove_new_debt(rows):
        for row in rows:
            if row['type'] == 'knowledge_run_completed' or (row['type'] == 'knowledge_root_recorded'
                    and row['payload']['root_kind'] == 'run'):
                row['payload']['debt_ids'] = []
        return rows
    _rewrite_event_chain(context, tmp_path / 'event-debt-attack', original, remove_new_debt)
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError, match='root|authority|debt'):
        revision_module().load_knowledge_revision(context)
    assert bytes_under(context.paths.root) == before


@pytest.mark.unit
def test_attempted_missing_behavior_is_not_dependency_debt(tmp_path):
    from tests.unit.test_re_v2_knowledge_revision import revision_module, expansion_cause
    module = importlib.import_module('harness.re_v2.protocol_28.debt')
    context, inputs, _, acquisition, active = reconciliation_fixture(tmp_path, debt=True)
    cause = expansion_cause(context, acquisition, active)
    active = revision_module().commit_knowledge_revision(context, inputs, cause)
    obligation = next(r for r in active.dependencies.obligations if r.obligation_id in cause.affected_obligation_ids)
    revision_context = revision_module()._read(context.objects, active.manifest.context_id, revision_module().KnowledgeRevisionContextV1)
    debt = module.KnowledgeDebtCandidateV1(1, active.manifest.logical_run_id, active.authorization.snapshot_id,
        active.manifest.revision_id, content_digest(b'work'), (obligation.obligation_id,), 'unavailable-dependency',
        obligation.evidence_ids, revision_context.evidence_outcome_ids, (), 'Attempted work is not automatically a dependency.')
    with pytest.raises(ValueError, match='eligible|debt|dependency'):
        module.validate_debt_candidate(context, debt, active)


@pytest.mark.unit
@pytest.mark.parametrize('reason', ['missing-work', 'unsupported-claim', 'unsupported-absence', 'unassessed-category',
    'security-failure', 'contradictory-ownership', 'provider-failure', 'budget-exhausted', 'unfinished-reconciliation'])
def test_ineligible_failure_never_becomes_knowledge_debt(tmp_path, reason):
    context, _, _, _, active = reconciliation_fixture(tmp_path, debt=True)
    module = importlib.import_module('harness.re_v2.protocol_28.debt')
    obligation = active.dependencies.obligations[0]
    candidate = module.KnowledgeDebtCandidateV1(1, active.manifest.logical_run_id,
        context.inputs.manifest.source_snapshot_id, active.manifest.revision_id,
        content_digest(b'work'), (obligation.obligation_id,), reason, obligation.evidence_ids,
        (), (), 'An explicit remaining limitation.')
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError, match='eligible|debt|dependency'):
        module.validate_debt_candidate(context, candidate, active)
    assert bytes_under(context.paths.root) == before


@pytest.mark.unit
def test_generic_unknown_or_missing_investigation_is_not_eligible(tmp_path):
    context, _, _, _, active = reconciliation_fixture(tmp_path, debt=True)
    module = importlib.import_module('harness.re_v2.protocol_28.debt')
    obligation = active.dependencies.obligations[0]
    for reason in ('unknown', 'unavailable-dependency', 'dynamic-dependency'):
        candidate = module.KnowledgeDebtCandidateV1(1, active.manifest.logical_run_id,
            context.inputs.manifest.source_snapshot_id, active.manifest.revision_id,
            content_digest(b'work'), (obligation.obligation_id,), reason, obligation.evidence_ids,
            (), (), 'Uncertainty does not prove an investigation.')
        with pytest.raises(ValueError, match='eligible|debt|dependency'):
            module.validate_debt_candidate(context, candidate, active)
