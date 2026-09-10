"""Accepted L4 limitations outlive analysis invalidation in the public lifecycle."""
from dataclasses import replace
import json

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_28.context import load_protocol_28_run_context
from harness.re_v2.protocol_28.debt import KnowledgeDebtCandidateV1
from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
from harness.re_v2.protocol_28.status import protocol_28_status_document
from tests.unit.test_re_v2_knowledge_revision import revision_module, bytes_under, split_reviewed_domain_plan
from tests.unit.test_re_v2_protocol_28_reconciliation import (
    reconciliation_fixture, reconciliation_module, KnowledgeBackend,
)


def _expand(context, inputs, acquisition, obligation, path, *, byte_start=0, byte_end=1):
    supplied = json.loads(acquisition.boundary.provider_bytes(acquisition.status().binding_id))
    batch = acquisition.boundary.admit(acquisition.status().binding_id, canonical_json_bytes({
        'schema_version': 1, 'kind': 'evidence_requests', 'source_id': 'api', 'requests': [{
            'obligation_id': supplied['origin_obligation_id'], 'reason_class': 'relationship',
            'selector': {'source_id': 'api', 'path': path, 'byte_start': byte_start, 'byte_end': byte_end},
        }],
    }))
    cause = revision_module().stage_knowledge_expansion(context, acquisition, batch, (obligation,))
    return revision_module().commit_knowledge_revision(context, inputs, cause)


def _accepted_new_debt(tmp_path, *, closure_ready=False):
    handler = ('import importlib\nREGISTRY = {"orders": "builtin_orders"}\n'
        'def handle(name):\n    return importlib.import_module(REGISTRY[name]).handle()\n') if closure_ready else (
        'import importlib\ndef handle(name):\n    return importlib.import_module(name).handle()\n')
    context, inputs, _, acquisition, active = reconciliation_fixture(tmp_path, debt=True,
        extra_source_files={
            'src/orders/handler.py': handler,
        })
    investigated = next(r.obligation_id for r in active.dependencies.obligations
        if r.target_kind == 'domain' and r.entry_ids)
    active = _expand(context, inputs, acquisition, investigated, 'plugins/runtime.py')

    def limited(role, supplied, value):
        if supplied['work_item']['scope'] != 'target' or supplied['work_item']['target_kind'] != 'domain':
            return value
        module = reconciliation_module()
        work = module.KnowledgeReconciliationWorkItemV1.from_json_dict(supplied['work_item'])
        if role == 'producer':
            candidate = module.KnowledgeReconciliationCandidateV1.from_json_dict(value)
            evidence = tuple(sorted(s.identity for s in inputs.snapshot_evidence_catalog.shards
                if s.identity in work.evidence_ids and s.byte_end <= 16)) if closure_ready else work.evidence_ids
            debt = KnowledgeDebtCandidateV1(1, work.logical_run_id, work.snapshot_id, work.revision_id,
                work.identity, (investigated,), 'dynamic-dependency', evidence,
                tuple(sorted(o['outcome_id'] for o in supplied['evidence_request_outcomes'])), (),
                'An investigated external runtime dependency is unavailable in this snapshot.')
            checks = tuple(sorted((replace(c, disposition='uncertain', debt_candidate_ids=(debt.identity,))
                if c.check == 'dependency-continuity' else c for c in candidate.checks), key=lambda c: c.identity))
            return replace(candidate, checks=checks, debt_candidates=(debt,)).to_json_dict()
        review = module.KnowledgeReconciliationReviewV1.from_json_dict(value)
        candidate = module.KnowledgeReconciliationCandidateV1.from_json_dict(supplied['candidate'])
        return replace(review, verdict='ACCEPT_WITH_DEBT',
            eligible_debt_candidate_ids=(candidate.debt_candidates[0].identity,)).to_json_dict()

    first = run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend(mutate=limited))
    assert first.state == 'complete-with-limitations'
    current = load_protocol_28_run_context(context.run_dir)
    root = current.ledger.replay().knowledge_run_roots[first.run_root_id]
    assert len(root.debt_ids) == len(root.debt_acceptance_ids) == 1
    return current, inputs, acquisition, active, investigated, root


def _assert_revision_debt_attacks_reject(context, active, tmp_path):
    from harness.re_v2.protocol_28.status import Protocol28StatusError
    from tests.unit.test_re_v2_protocol_28_debt import _rewrite_event_chain
    module = revision_module()
    original_events = context.events.path.read_bytes()
    lineage = active.debt_lineage
    assert lineage.rows

    def rejected():
        before = bytes_under(context.paths.root)
        for read in (lambda: load_protocol_28_run_context(context.run_dir),
                lambda: protocol_28_status_document(context.run_dir),
                lambda: run_protocol_28_exhaustive(context.run_dir, lambda: pytest.fail('tampered debt invoked provider'))):
            with pytest.raises((ValueError, Protocol28StatusError), match='debt|authority|lineage'):
                read()
            assert bytes_under(context.paths.root) == before

    suffix = lineage.identity.split(':')[1]
    path = context.objects.root / 'sha256' / suffix[:2] / suffix[2:]
    original = path.read_bytes()
    path.chmod(0o600)
    path.write_bytes(b'{}\n')
    rejected()
    path.write_bytes(original)
    for name, changed in [('omitted', replace(lineage, rows=())),
            ('rebound', replace(lineage, rows=(replace(lineage.rows[0], acceptance_id=content_digest(b'other acceptance')),)))]:
        module._put(context.objects, changed)
        manifest = replace(active.manifest, debt_lineage_id=changed.identity,
            child_ids=tuple(sorted((set(active.manifest.child_ids) - {lineage.identity}) | {changed.identity})))
        module._put(context.objects, manifest)
        pointer = replace(active.pointer, revision_manifest_id=manifest.identity)
        module._put(context.objects, pointer)
        def rebind(rows):
            rows[-1]['payload']['pointer_id'] = pointer.identity
            return rows
        _rewrite_event_chain(context, tmp_path / name, original_events, rebind)
        rejected()
        context.events.path.write_bytes(original_events)
    # The historical schema cannot be substituted to evade the new authority.
    from dataclasses import fields
    manifest = module.KnowledgeRevisionManifestV1(**{f.name: getattr(active.manifest, f.name)
        for f in fields(module.KnowledgeRevisionManifestV1) if f.name != 'child_ids'},
        child_ids=tuple(key for key in active.manifest.child_ids if key != lineage.identity))
    module._put(context.objects, manifest)
    pointer = replace(active.pointer, revision_manifest_id=manifest.identity)
    module._put(context.objects, pointer)
    def downgrade(rows):
        rows[-1]['payload']['pointer_id'] = pointer.identity
        return rows
    _rewrite_event_chain(context, tmp_path / 'downgrade', original_events, downgrade)
    rejected()
    context.events.path.write_bytes(original_events)
    # A genuine but older frozen prefix cannot erase accepted debt by rebuilding
    # every dependent child and pointer around that earlier observation.
    frozen, previous = module.load_knowledge_authorities(context.objects)[active.manifest.previous_manifest_id]
    ledger_rows = module._rows(context.objects, previous.manifest.ledger_prefix_id)
    resource_rows = module._rows(context.objects, previous.manifest.resource_prefix_id)
    event_rows = module._rows(context.objects, active.manifest.event_prefix_id)
    dependencies = module._dependencies(frozen, context.inputs, previous, ledger_rows, event_rows)
    cause = module._read(context.objects, active.receipt.cause_id, module.KnowledgeRevisionCauseV1)
    counters = module._counters(frozen, context.inputs, dependencies, previous, resource_rows,
        ledger_rows, active.manifest.expansion_rounds, cause.affected_obligation_ids)
    omitted = replace(lineage, rows=())
    invalidated = tuple(sorted(r.result_id for r in dependencies.results))
    receipt = replace(active.receipt, invalidated_result_ids=invalidated)
    invalidation = module.KnowledgeInvalidationReceiptV1(1, cause.identity, dependencies.identity,
        cause.affected_obligation_ids, invalidated)
    removed = {active.manifest.dependency_map_id, active.manifest.counters_id,
        active.manifest.debt_lineage_id, active.manifest.ledger_prefix_id,
        active.manifest.resource_prefix_id, active.manifest.revision_receipt_id,
        active.manifest.invalidation_receipt_id}
    replacements = (dependencies, counters, omitted, receipt, invalidation)
    for value in replacements:
        module._put(context.objects, value)
    added = {v.identity for v in replacements} | {
        previous.manifest.ledger_prefix_id, previous.manifest.resource_prefix_id}
    manifest = replace(active.manifest, dependency_map_id=dependencies.identity,
        counters_id=counters.identity, debt_lineage_id=omitted.identity,
        ledger_prefix_id=previous.manifest.ledger_prefix_id,
        resource_prefix_id=previous.manifest.resource_prefix_id,
        revision_receipt_id=receipt.identity, invalidation_receipt_id=invalidation.identity,
        invalidated_result_ids=invalidated,
        child_ids=tuple(sorted((set(active.manifest.child_ids) - removed) | added)))
    module._put(context.objects, manifest)
    pointer = replace(active.pointer, revision_manifest_id=manifest.identity)
    module._put(context.objects, pointer)
    intent = module.KnowledgeRevisionIntentV1(1, cause.identity, manifest.inputs_id,
        manifest.ledger_prefix_id, manifest.event_prefix_id, manifest.resource_prefix_id)
    module._put(context.objects, intent)
    def truncate_prefix(rows):
        rows[-2]['payload']['intent_id'] = intent.identity
        rows[-1]['payload']['pointer_id'] = pointer.identity
        rows[-1]['payload']['invalidated_result_ids'] = list(invalidated)
        return rows
    _rewrite_event_chain(context, tmp_path / 'truncated-prefix', original_events, truncate_prefix)
    rejected()
    context.events.path.write_bytes(original_events)


@pytest.mark.integration
@pytest.mark.parametrize('revision_kind', ['unrelated', 'affected-split'])
def test_accepted_new_debt_survives_invalidating_revision_and_ordinary_pass(tmp_path, revision_kind):
    from harness.re_v2.ledger import ReV2LedgerError
    context, inputs, acquisition, active, investigated, old_root = _accepted_new_debt(tmp_path)
    if revision_kind == 'affected-split':
        revised_inputs, selected = split_reviewed_domain_plan(inputs), investigated
    else:
        revised_inputs = inputs
        selected = next(r.obligation_id for r in active.dependencies.obligations
            if r.target_kind == 'source' and r.entry_ids)
        assert selected != investigated
    active = _expand(context, revised_inputs, acquisition, selected, 'plugins/other-runtime.py')
    assert old_root.identity in active.manifest.invalidated_result_ids
    pending_status = protocol_28_status_document(context.run_dir)
    assert pending_status['status'] == 'running'
    assert [row['debt_id'] for row in pending_status['limitations']] == list(old_root.debt_ids)
    if revision_kind == 'unrelated':
        _assert_revision_debt_attacks_reject(context, active, tmp_path / 'lineage-attacks')
    backend = KnowledgeBackend()
    second = run_protocol_28_exhaustive(context.run_dir, lambda: backend)

    assert second.state == 'complete-with-limitations', 'ordinary PASS cannot close an earlier exact L4 acceptance'
    current = load_protocol_28_run_context(context.run_dir)
    root = current.ledger.replay().knowledge_run_roots[second.run_root_id]
    assert root.debt_ids == old_root.debt_ids
    assert root.debt_acceptance_ids == old_root.debt_acceptance_ids
    assert current.inputs.manifest.source_snapshot_id == inputs.manifest.source_snapshot_id
    status = protocol_28_status_document(context.run_dir)
    assert status['input_quality'] == 'partial'
    assert [row['debt_id'] for row in status['limitations']] == list(old_root.debt_ids)
    view = current.ledger.replay()
    work = next(w for w in view.knowledge_work.values() if w.revision_id == active.manifest.revision_id
        and w.scope == 'target' and investigated in w.obligation_ids)
    for acceptances in ((), (content_digest(b'other acceptance'),)):
        forged = replace(work, inherited_debt_acceptance_ids=acceptances)
        revision_module()._put(current.objects, forged)
        before = bytes_under(context.paths.root)
        with pytest.raises((ValueError, ReV2LedgerError), match='authority|inherited'):
            current.ledger.record_knowledge_work(forged)
        assert bytes_under(context.paths.root) == before
    for role, payload in backend.calls:
        work = payload.get('work_item')
        if work and investigated in work['obligation_ids']:
            assert work['inherited_debt_acceptance_ids'] == list(old_root.debt_acceptance_ids)
            assert payload['inherited_debt'][0]['debt_ids'] == list(old_root.debt_ids)
        elif not work and payload['plan_entry']['target_kind'] == 'domain':
            assert payload['inherited_knowledge_debt'][0]['debt_ids'] == list(old_root.debt_ids)
    before = bytes_under(context.paths.root)
    assert run_protocol_28_exhaustive(context.run_dir, lambda: pytest.fail('completed replay invoked provider')) == second
    assert bytes_under(context.paths.root) == before


@pytest.mark.integration
def test_only_exact_captured_review_with_new_resolving_evidence_closes_carried_debt(tmp_path):
    context, inputs, acquisition, active, investigated, old_root = _accepted_new_debt(tmp_path, closure_ready=True)
    active = _expand(context, inputs, acquisition, investigated, 'src/orders/handler.py', byte_start=16, byte_end=54)
    resolving_evidence = tuple(sorted(s.identity for s in inputs.snapshot_evidence_catalog.shards
        if s.source_relative_path == 'src/orders/handler.py' and 16 <= s.byte_start < s.byte_end <= 54))
    assert resolving_evidence
    seen_resolution_ids = []

    def close(role, supplied, value):
        work = supplied['work_item']
        if work['scope'] != 'target' or work['target_kind'] != 'domain':
            return value
        if role == 'producer':
            resolution = {'schema_version': 1, 'work_item_id': content_digest(work),
                'acceptance_id': old_root.debt_acceptance_ids[0], 'debt_ids': list(old_root.debt_ids),
                'obligation_ids': [investigated], 'evidence_ids': list(resolving_evidence),
                'acquisition_outcome_ids': sorted(o['outcome_id'] for o in supplied['evidence_request_outcomes']
                    if o['disposition'] == 'resolved'),
                'explanation': 'The newly investigated registry resolves the previously unknown runtime mapping.'}
            seen_resolution_ids.append(content_digest(resolution))
            return {**value, 'debt_resolutions': [resolution]}
        return {**value, 'resolved_debt_candidate_ids': seen_resolution_ids[-1:]}

    result = run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend(mutate=close))
    assert result.state == 'complete', 'separate exact reviewed closure must be usable'
    current = load_protocol_28_run_context(context.run_dir)
    view = current.ledger.replay()
    root = view.knowledge_run_roots[result.run_root_id]
    assert root.debt_ids == root.debt_acceptance_ids == ()
    status = protocol_28_status_document(context.run_dir)
    assert status['limitations'] == [] and status['input_quality'] == 'complete'
    resolved = next(r for r in view.knowledge_roots.values() if r.revision_id == active.manifest.revision_id
        and r.scope == 'target' and r.target_kind == 'domain')
    module = reconciliation_module()
    candidate = revision_module()._read(current.objects, resolved.candidate_id, module.KnowledgeReconciliationCandidateV1)
    review = revision_module()._read(current.objects, resolved.review_id, module.KnowledgeReconciliationReviewV1)
    work = view.knowledge_work[resolved.work_item_id]
    from harness.re_v2.protocol_28.debt import validate_debt_resolution, reviewed_debt_closure, derive_knowledge_debt_lineage
    resolution = candidate.debt_resolutions[0]
    receipt = reviewed_debt_closure(current, active, work, resolution, review)
    assert revision_module()._read(current.objects, receipt.identity, type(receipt)) == receipt
    assert receipt.acceptance_id == old_root.debt_acceptance_ids[0]
    assert receipt.debt_ids == old_root.debt_ids
    assert derive_knowledge_debt_lineage(current.objects, content_digest(b'next-revision'),
        active.dependencies, view).rows == ()
    original_acceptance = json.loads(current.objects.read_blob(old_root.debt_acceptance_ids[0]))
    old_candidate = json.loads(current.objects.read_blob(original_acceptance['candidate_ids'][0]))
    for mutation in (replace(resolution, acceptance_id=content_digest(b'rebound')),
            replace(resolution, debt_ids=()), replace(resolution, acquisition_outcome_ids=()),
            replace(resolution, evidence_ids=()), replace(resolution, obligation_ids=()),
            replace(resolution, evidence_ids=tuple(old_candidate['investigation_evidence_ids'])),
            replace(resolution, acquisition_outcome_ids=tuple(old_candidate['acquisition_outcome_ids']))):
        with pytest.raises(ValueError, match='debt|resolution|closure'):
            validate_debt_resolution(current, mutation, active, work)
    with pytest.raises(ValueError, match='debt|resolution|closure'):
        module.validate_reconciliation_review(work, candidate, replace(review, resolved_debt_candidate_ids=()))
    before = bytes_under(context.paths.root)
    assert run_protocol_28_exhaustive(context.run_dir, lambda: pytest.fail('closure replay invoked provider')) == result
    assert bytes_under(context.paths.root) == before
    suffix = receipt.identity.split(':')[1]
    path = current.objects.root / 'sha256' / suffix[:2] / suffix[2:]
    original = path.read_bytes()
    path.chmod(0o600)
    path.write_bytes(b'{}\n')
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError, match='closure|authority|debt'):
        load_protocol_28_run_context(context.run_dir)
    assert bytes_under(context.paths.root) == before
    path.write_bytes(original)
