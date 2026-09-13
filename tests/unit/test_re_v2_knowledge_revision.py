"""Real reviewed activation -> resource transfer -> revision public boundaries."""
from dataclasses import replace
import importlib
import json

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_accounting import KnowledgeDispatchAccount, KnowledgeDispatchPolicy, KnowledgeProviderContract
from harness.re_v2.protocol_28.context import initialize_protocol_28_run, load_protocol_28_run_context
from harness.re_v2.protocol_28.inputs import stage_exhaustive_inputs, publish_protocol_28_run
from tests.integration.test_re_v2_knowledge_activation import reviewed_preparation_fixture


def revision_module():
    return importlib.import_module('harness.re_v2.knowledge_revision')


def revision_fixture(tmp_path, *, l4_limits=None, **kwargs):
    preparation, workspace, intent, parent, options, acquisition = reviewed_preparation_fixture(tmp_path, **kwargs)
    if l4_limits:
        options = replace(options, token_limit=l4_limits[0], active_ms_limit=l4_limits[1])
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    staged = stage_exhaustive_inputs(tmp_path / 'private', inputs)
    published = publish_protocol_28_run(staged.root.parent, tmp_path / inputs.manifest.run_id, inputs.manifest)
    context = load_protocol_28_run_context(published.root.parent)
    initialize_protocol_28_run(context)
    first = json.loads((acquisition.paths.root / 'knowledge-dispatch.jsonl').read_text().splitlines()[0])
    opening = json.loads(acquisition.objects.read_blob(first['payload']['receipt_id']))
    contract = KnowledgeProviderContract(**json.loads(acquisition.objects.read_blob(opening['provider_contract_id'])))
    account = KnowledgeDispatchAccount(acquisition.paths, KnowledgeDispatchPolicy(**opening['policy']), contract, opening['run_authority'])
    return context, inputs, account, acquisition


def bytes_under(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob('*') if p.is_file()}


def expansion_cause(context, acquisition, active, index=0):
    from tests.unit.test_re_v2_knowledge_acquisition import _request
    binding = acquisition.status().binding_id
    batch = _request(acquisition.boundary, binding, acquisition.objects, (f'unavailable-{index}.py',))
    return revision_module().stage_knowledge_expansion(context, acquisition, batch,
        (active.dependencies.obligations[0].obligation_id,))


def split_reviewed_domain_plan(inputs, source_id=None):
    """Use the actual safe sizing/splitting helpers, then public input validation."""
    from harness.re_v2.protocol_28.preparation import (_entry_for_evidence_chunk,
        _rebind_composition_dependencies, _bind_exact_context_sizes)
    module = revision_module()
    target = next(t for t in inputs.exhaustive_plan.target_plans if t.target_kind == 'domain'
        and (source_id is None or t.source_id == source_id))
    (entry,) = target.entries
    evidence = tuple(sorted((*entry.primary_snapshot_evidence_ids, *entry.supporting_snapshot_evidence_ids)))
    assert len(evidence) > 1
    record_for = {s.identity: s.file_record_hash for s in inputs.snapshot_evidence_catalog.shards}
    first_for_record = {}
    for key in evidence:
        if record_for[key] in entry.primary_source_record_ids:
            first_for_record.setdefault(record_for[key], key)
    bundles = module._bundles(inputs)
    owners = {key: row.subject_id for bundle in bundles for row in bundle.inventory_assessments
        if row.disposition == 'owned' for key in row.raw_evidence_ids}
    split = tuple(_entry_for_evidence_chunk(entry, chunk, first_for_record, first_chunk=index == 0,
        ordinal=index, subjects=inputs.exhaustive_subject_catalog, record_for=record_for, reviewed_owner_ids=owners)
        for index, chunk in enumerate((evidence[:len(evidence)//2], evidence[len(evidence)//2:])))
    plan = replace(inputs.exhaustive_plan, target_plans=_rebind_composition_dependencies(tuple(
        replace(t, entries=split) if t == target else t for t in inputs.exhaustive_plan.target_plans)))
    plan = _bind_exact_context_sizes(plan, inputs.l3_projection_catalog, inputs.snapshot_evidence_catalog,
        inputs.exhaustive_subject_catalog, inputs.exhaustive_policy, inputs.authority_objects,
        inputs.safe_snapshot_evidence_catalog, inputs.safe_lower_authority_catalog, reviewed=bundles)
    request = replace(inputs.manifest.exhaustive_request, exhaustive_plan_id=plan.identity)
    manifest = replace(inputs.manifest, exhaustive_request=request, exhaustive_plan_id=plan.identity)
    return replace(inputs, manifest=manifest, exhaustive_plan=plan)


def unequal_round_multi_source_fixture(tmp_path):
    from harness.re_v2.knowledge_activation import activate_reviewed_discovery, load_reviewed_discovery
    from harness.re_v2.protocol_28.preparation import ReviewedProtocol28PreparationOptions, prepare_protocol_28_request
    from harness.re_v2.protocol_28.policies import build_repaired_exhaustive_policy
    from tests.unit.test_re_v2_knowledge_activation import activation_fixture, review_second_source
    api, account, review, l3, evidence, fixture = activation_fixture(tmp_path, multiple=True,
        initial_expansion=True, account_policy=KnowledgeDispatchPolicy(5_000_000, 10_800_000, 3))
    workspace, intent, parent, options = fixture
    first = activate_reviewed_discovery(api, account, review, l3, evidence)
    beta, other_review = review_second_source(tmp_path, api, account, review, options)
    second = activate_reviewed_discovery(beta, account, other_review, l3, evidence)
    bundles = tuple(load_reviewed_discovery(root, api.objects, l3, evidence) for root in (first, second))
    policy = build_repaired_exhaustive_policy(producer_contract_hash=content_digest(options.producer_agent_bytes),
        verifier_contract_hash=content_digest(options.verifier_agent_bytes))
    reviewed_options = ReviewedProtocol28PreparationOptions(
        **{f: getattr(options, f) for f in options.__dataclass_fields__}, reviewed_discoveries=bundles)
    inputs = prepare_protocol_28_request(workspace, replace(intent, exhaustive_policy_catalog_id=policy.identity), parent, reviewed_options)
    staged = stage_exhaustive_inputs(tmp_path / 'private', inputs)
    published = publish_protocol_28_run(staged.root.parent, tmp_path / inputs.manifest.run_id, inputs.manifest)
    context = load_protocol_28_run_context(published.root.parent)
    initialize_protocol_28_run(context)
    return context, inputs, account, api, beta


@pytest.mark.unit
def test_unequal_source_rounds_never_reset_or_consume_another_origins_allowance(tmp_path):
    from harness.re_v2.protocol_22.provider import DispatchReservationV1
    context, inputs, account, api, beta = unequal_round_multi_source_fixture(tmp_path)
    module = revision_module()
    assert (api.status().rounds, beta.status().rounds) == (1, 0)
    active = module.activate_knowledge_workflow(context, account, allow_debt=False)
    origins = {row.source_id: {o for r in active.dependencies.obligations if r.source_id == row.source_id
        for o in r.origin_obligation_ids} for row in active.dependencies.obligations}
    def assert_rounds(revision, api_round, beta_round):
        for source_id, expected in (('api', api_round), ('beta', beta_round)):
            assert {row.expansion_rounds for row in revision.counters.rows if row.origin_obligation_id in origins[source_id]} == {expected}
    assert_rounds(active, 1, 0)
    target = next(t for t in inputs.exhaustive_plan.target_plans if t.source_id == 'beta' and t.target_kind == 'domain')
    spec = module.realize_knowledge_slice(context, active, target.entries[0], {})
    reservation = DispatchReservationV1(1, 1, 1)
    pair = context.resources.commit_pair(context.resources.preview_pair(spec.identity, 1, reservation, reservation),
        producer_dispatch_id='beta-producer-1', verifier_dispatch_id='beta-verifier-1')
    for dispatch_id in (pair.producer_dispatch_id, pair.verifier_dispatch_id):
        context.resources.observe(dispatch_id, token_status='trusted_exact', billable_tokens=1,
            active_status='trusted_exact', active_ms=1)
    resource_bytes = context.resources.path.read_bytes()
    def expand(phase, revision, index, next_inputs):
        current = load_protocol_28_run_context(context.run_dir)
        source_id = phase.opening['evidence_scope']['source_id']
        supplied = json.loads(phase.boundary.provider_bytes(phase.status().binding_id))
        batch = phase.boundary.admit(phase.status().binding_id, canonical_json_bytes({
            'schema_version': 1, 'kind': 'evidence_requests', 'source_id': source_id, 'requests': [{
                'obligation_id': supplied['origin_obligation_id'], 'reason_class': 'relationship',
                'selector': {'source_id': source_id, 'path': f'unavailable-{index}.py', 'byte_start': 0, 'byte_end': 1}}]}))
        obligation = next(r.obligation_id for r in revision.dependencies.obligations
            if r.source_id == source_id and r.target_kind == 'domain' and r.entry_ids)
        cause = module.stage_knowledge_expansion(current, phase, batch, (obligation,))
        return module.commit_knowledge_revision(current, next_inputs, cause)
    split_inputs = split_reviewed_domain_plan(inputs, 'beta')
    active = expand(beta, active, 1, split_inputs)
    assert_rounds(active, 1, 1)
    active = expand(beta, active, 2, inputs)
    assert_rounds(active, 1, 2)
    active = expand(api, active, 2, inputs)
    assert_rounds(active, 2, 2)
    assert active.manifest.account_transfer_id == context.resources.records[0].identity
    for phase in (api, beta):
        before = bytes_under(context.paths.root)
        with pytest.raises(ValueError, match='round|expansion'):
            expand(phase, active, 3, inputs)
        assert bytes_under(context.paths.root) == before
    beta_obligation = next(r for r in active.dependencies.obligations
        if r.source_id == 'beta' and r.target_kind == 'domain' and r.entry_ids)
    assert module.inherited_attempts(active, (beta_obligation.obligation_id,), 'slice') == 1
    assert context.resources.path.read_bytes() == resource_bytes
    before = bytes_under(context.paths.root)
    assert module.load_knowledge_revision(load_protocol_28_run_context(context.run_dir)) == active
    assert bytes_under(context.paths.root) == before


@pytest.mark.unit
def test_split_merge_replans_keep_nonzero_origin_attempts_and_one_resource_history(tmp_path):
    from harness.re_v2.protocol_22.provider import DispatchReservationV1
    context, inputs, account, acquisition = revision_fixture(tmp_path)
    module = revision_module()
    initial = module.activate_knowledge_workflow(context, account, allow_debt=False)
    target = next(t for t in inputs.exhaustive_plan.target_plans if t.target_kind == 'domain')
    spec = module.realize_knowledge_slice(context, initial, target.entries[0], {})
    reservation = DispatchReservationV1(1, 1, 1)
    preview = context.resources.preview_pair(spec.identity, 1, reservation, reservation)
    pair = context.resources.commit_pair(preview, producer_dispatch_id='split-producer-1', verifier_dispatch_id='split-verifier-1')
    for dispatch_id in (pair.producer_dispatch_id, pair.verifier_dispatch_id):
        context.resources.observe(dispatch_id, token_status='trusted_exact', billable_tokens=1,
            active_status='trusted_exact', active_ms=1)
    history = context.resources.path.read_bytes()
    split_inputs = split_reviewed_domain_plan(inputs)
    cause = expansion_cause(context, acquisition, initial, 1)
    split = module.commit_knowledge_revision(context, split_inputs, cause)
    original = next(o for o in initial.dependencies.obligations if target.entries[0].identity in o.entry_ids)
    changed = next(o for o in split.dependencies.obligations if o.obligation_id == original.obligation_id)
    assert len(original.entry_ids) == 1 and len(changed.entry_ids) == 2
    assert changed.origin_obligation_ids == original.origin_obligation_ids
    assert module.inherited_attempts(split, (changed.obligation_id,), 'slice') == 1
    reopened = load_protocol_28_run_context(context.run_dir)
    assert reopened.inputs.exhaustive_plan == split_inputs.exhaustive_plan
    cause = expansion_cause(reopened, acquisition, split, 2)
    merged = module.commit_knowledge_revision(reopened, inputs, cause)
    assert next(o for o in merged.dependencies.obligations if o.obligation_id == original.obligation_id) == original
    assert module.inherited_attempts(merged, (original.obligation_id,), 'slice') == 1
    assert merged.manifest.expansion_rounds == 2 and merged.manifest.account_transfer_id == initial.manifest.account_transfer_id
    assert context.resources.path.read_bytes() == history
    before = bytes_under(context.paths.root)
    assert module.load_knowledge_revision(load_protocol_28_run_context(context.run_dir)) == merged
    assert bytes_under(context.paths.root) == before


@pytest.mark.unit
def test_explicit_workflow_transfers_the_authenticated_account_exactly_once(tmp_path):
    context, inputs, account, acquisition = revision_fixture(tmp_path)
    before = account.status()
    module = revision_module()
    initial = module.activate_knowledge_workflow(context, account, allow_debt=False)
    assert initial.manifest.logical_run_id == acquisition.paths.root.parent.name
    assert initial.manifest.reviewed_catalog_id == inputs.reviewed_discovery_catalog.identity
    assert context.resources.decision.charged_tokens == before.charged_tokens
    assert context.resources.decision.charged_active_ms == before.charged_active_ms
    assert context.resources.decision.token_limit == 500_000
    assert context.resources.decision.active_ms_limit == 100_000
    files = bytes_under(context.paths.root)
    assert module.activate_knowledge_workflow(context, account, allow_debt=False) == initial
    assert bytes_under(context.paths.root) == files
    assert module.load_knowledge_revision(context) == initial
    with pytest.raises(ValueError, match='authorization|workflow'):
        module.activate_knowledge_workflow(context, account, allow_debt=True)


@pytest.mark.unit
def test_transfer_authenticates_the_sealed_source_and_rejects_double_import(tmp_path):
    from harness.re_v2.protocol_28.model import KnowledgeAccountTransferV1
    context, _, account, _ = revision_fixture(tmp_path)
    module = revision_module()
    active = module.activate_knowledge_workflow(context, account, allow_debt=False)
    assert active.authorization.account_seal_id
    seal = module._read(context.objects, active.authorization.account_seal_id, module.KnowledgeAccountSealV1)
    assert seal.account_id == content_digest(account.opening) and seal.transfer_id == active.manifest.account_transfer_id
    receipt = module._read(context.objects, seal.transfer_id, KnowledgeAccountTransferV1)
    assert receipt.resource_store_id == content_digest({'run_manifest_id': receipt.run_manifest_id,
        'store_kind': 'protocol-2.8-resources-v1'})
    before = bytes_under(context.paths.root)
    context.resources.import_knowledge_account(receipt)
    with pytest.raises(ValueError):
        context.resources.import_knowledge_account(replace(receipt, account_id=content_digest(b'another-account')))
    assert bytes_under(context.paths.root) == before
    sealed = context.objects.root / 'sha256' / seal.sealed_prefix_id[7:9] / seal.sealed_prefix_id[9:]
    sealed.chmod(0o600)
    sealed.write_bytes(canonical_json_bytes(module._rows(context.objects, receipt.account_prefix_id)))
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError):
        module.load_knowledge_revision(load_protocol_28_run_context(context.run_dir))
    assert bytes_under(context.paths.root) == before


@pytest.mark.unit
def test_an_unrelated_fresh_account_cannot_erase_the_reviewed_baseline(tmp_path):
    from harness.re_v2.run_store import ReV2Paths
    context, _, original, _ = revision_fixture(tmp_path)
    paths = ReV2Paths.for_run(tmp_path / 'unrelated-account')
    paths.root.mkdir(parents=True)
    fresh = KnowledgeDispatchAccount(paths, KnowledgeDispatchPolicy(**original.opening['policy']),
        original.contract, original.opening['run_authority'])
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError):
        revision_module().activate_knowledge_workflow(context, fresh, allow_debt=False)
    assert bytes_under(context.paths.root) == before


@pytest.mark.unit
def test_reopen_rejects_resource_rollback_behind_durable_dispatches(tmp_path):
    from tests.unit.test_re_v2_protocol_28_reconciliation import reconciliation_fixture, KnowledgeBackend
    from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
    context, *_ = reconciliation_fixture(tmp_path)
    assert run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend()).state == 'complete'
    path = context.paths.root / 'resources.jsonl'
    lines = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(lines[0])
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError):
        revision_module().load_knowledge_revision(load_protocol_28_run_context(context.run_dir))
    assert bytes_under(context.paths.root) == before


@pytest.mark.unit
@pytest.mark.parametrize('forgery', ['counter', 'extra-child', 'missing-child', 'rebound-plan'])
def test_self_consistent_manifest_forgery_cannot_replace_recomputed_closure(tmp_path, forgery):
    context, _, account, _ = revision_fixture(tmp_path)
    module = revision_module()
    active = module.activate_knowledge_workflow(context, account, allow_debt=False)
    manifest = active.manifest
    if forgery == 'counter':
        row = replace(active.counters.rows[0], producer_attempts=1)
        counter = replace(active.counters, rows=tuple(sorted((row, *active.counters.rows[1:]), key=lambda r: r.identity)))
        module._put(context.objects, counter)
        manifest = replace(manifest, counters_id=counter.identity,
            child_ids=tuple(sorted((set(manifest.child_ids) - {active.counters.identity}) | {counter.identity})))
    elif forgery == 'extra-child':
        extra = context.objects.put_blob(canonical_json_bytes({'unrelated': True}))
        manifest = replace(manifest, child_ids=tuple(sorted((*manifest.child_ids, extra))))
    elif forgery == 'missing-child':
        manifest = replace(manifest, child_ids=manifest.child_ids[:-1])
    else:
        manifest = replace(manifest, plan_id=content_digest(b'foreign-plan'))
    module._put(context.objects, manifest)
    pointer = replace(active.pointer, revision_manifest_id=manifest.identity)
    module._put(context.objects, pointer)
    # Rehash a forged temporary event stream through the real append boundary;
    # checksums alone must not authenticate this internally inconsistent closure.
    events = context.events.replay()
    context.paths.events.write_bytes(b'')
    for event in events:
        payload = dict(event.payload)
        if event.type == 'knowledge_workflow_activated':
            payload['pointer_id'] = pointer.identity
        context.events.append(event.type, payload, occurred_at=event.occurred_at)
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError):
        load_protocol_28_run_context(context.run_dir)
    assert bytes_under(context.paths.root) == before


@pytest.mark.unit
def test_completed_revision_invalidates_transitive_roots_reuses_only_proven_siblings_and_inherits_attempts(tmp_path, monkeypatch):
    from tests.unit.test_re_v2_protocol_28_reconciliation import reconciliation_fixture, KnowledgeBackend
    from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
    from harness.re_v2.protocol_28.events import replay_protocol_28
    context, inputs, _, acquisition, initial = reconciliation_fixture(tmp_path)
    first = run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend())
    assert first.state == 'complete'
    view = context.ledger.replay()
    obligation = next(r for r in initial.dependencies.obligations if r.target_kind == 'source' and r.entry_ids)
    from tests.unit.test_re_v2_knowledge_acquisition import _request
    batch = _request(acquisition.boundary, acquisition.status().binding_id, acquisition.objects, ('unavailable-dependency.py',))
    module = revision_module()
    cause = module.stage_knowledge_expansion(context, acquisition, batch, (obligation.obligation_id,))
    affected = {r.identity for r in view.accepted_slices.values() if r.plan_entry_id in obligation.entry_ids}
    reusable_slices = tuple(sorted(r.identity for r in view.accepted_slices.values()
        if r.plan_entry_id not in obligation.entry_ids and next(t for t in inputs.exhaustive_plan.target_plans
            if r.plan_entry_id in {e.identity for e in t.entries}).target_kind == 'domain'))
    reusable = tuple(sorted((*reusable_slices, *(r.identity for r in view.knowledge_roots.values()
        if r.scope == 'target' and r.target_kind == 'domain'))))
    assert reusable_slices and len(reusable) > len(reusable_slices)
    totals = context.resources.decision.charged_tokens
    def crash_after_compatibility(point):
        if point == 'after_compatibility_receipt':
            raise RuntimeError('compatibility-staging-fault')
    with pytest.raises(RuntimeError, match='compatibility-staging-fault'):
        module.commit_knowledge_revision(context, inputs, cause, compatibility_result_ids=reusable,
            fault_hook=crash_after_compatibility)
    before = bytes_under(context.paths.root)
    assert module.load_knowledge_revision(load_protocol_28_run_context(context.run_dir)) == initial
    assert bytes_under(context.paths.root) == before
    changed = module.commit_knowledge_revision(context, inputs, cause, compatibility_result_ids=reusable)
    old_source_work = next(w for w in view.knowledge_work.values() if w.scope == 'source')
    stale_lower = replace(old_source_work, revision_id=changed.manifest.revision_id,
        revision_manifest_id=changed.manifest.identity)
    module._put(context.objects, stale_lower)
    from harness.re_v2.ledger import ReV2LedgerError
    with pytest.raises((ValueError, ReV2LedgerError), match='revision|compatibility|reconciliation'):
        context.ledger.record_knowledge_work(stale_lower)
    assert affected.issubset(changed.receipt.invalidated_result_ids)
    assert first.run_root_id in changed.receipt.invalidated_result_ids
    assert {r.identity for r in view.knowledge_roots.values() if r.identity not in reusable}.issubset(changed.receipt.invalidated_result_ids)
    assert changed.receipt.reusable_result_ids == reusable
    assert len(changed.receipt.compatibility_receipt_ids) == len(reusable)
    counter = next(r for r in changed.counters.rows if r.origin_obligation_id == obligation.origin_obligation_ids[0])
    assert counter.producer_attempts >= 1 and counter.verifier_attempts >= 1
    reopened = load_protocol_28_run_context(context.run_dir)
    state = replay_protocol_28(reopened.events.replay())
    assert state.lifecycle_state == 'running' and set(state.accepted_slices.values()) == set(reusable_slices)
    backend = KnowledgeBackend()
    second = run_protocol_28_exhaustive(context.run_dir, lambda: backend)
    assert second.state == 'complete' and second.run_root_id != first.run_root_id
    assert reopened.resources.decision.charged_tokens >= totals
    after = context.ledger.replay()
    original_dispatches = set(view.execution_captures)
    assert original_dispatches.issubset(after.execution_captures)
    assert all(context.ledger.replay().execution_captures[d] == view.execution_captures[d] for d in original_dispatches)
    before = bytes_under(context.paths.root)
    assert module.load_knowledge_revision(load_protocol_28_run_context(context.run_dir)) == changed
    assert_bounded_revision_replay(context, changed, monkeypatch)
    assert bytes_under(context.paths.root) == before


@pytest.mark.unit
def test_revision_preserves_origins_counters_and_replay_is_read_only(tmp_path, monkeypatch):
    context, inputs, account, acquisition = revision_fixture(tmp_path)
    module = revision_module()
    initial = module.activate_knowledge_workflow(context, account, allow_debt=False)
    affected = (initial.dependencies.obligations[0].obligation_id,)
    cause = expansion_cause(context, acquisition, initial)
    changed = module.commit_knowledge_revision(context, inputs, cause)
    assert changed.receipt.previous_revision_id == initial.manifest.revision_id
    assert changed.receipt.affected_obligation_ids == affected
    assert changed.manifest.account_transfer_id == initial.manifest.account_transfer_id
    assert [(o.obligation_id, o.origin_obligation_ids) for o in changed.dependencies.obligations] == [
        (o.obligation_id, o.origin_obligation_ids) for o in initial.dependencies.obligations]
    assert changed.manifest.expansion_rounds == 1
    files = bytes_under(context.paths.root)
    monkeypatch.setattr(context.objects, 'put_blob', lambda _: pytest.fail('replay wrote authority'))
    assert_bounded_revision_replay(context, changed, monkeypatch)
    assert bytes_under(context.paths.root) == files
    # A new public replay must reread the store, not retain the prior memoized
    # authority. This is a synthetic child object, never a source checkout.
    child_id = changed.manifest.reviewed_catalog_id
    child = context.objects.root / 'sha256' / child_id[7:9] / child_id[9:]
    child.chmod(0o600)
    child.write_bytes(b'{}')
    tampered = bytes_under(context.paths.root)
    with pytest.raises(ValueError):
        module.load_knowledge_revision(context)
    assert bytes_under(context.paths.root) == tampered


def assert_bounded_revision_replay(context, expected, monkeypatch):
    """Exercise real replay; count expensive work without replacing its result."""
    from collections import Counter
    from harness.re_v2 import knowledge_activation
    from harness.re_v2.protocol_28.ledger import PROTOCOL_28_LEDGER_PROTOCOL
    module = revision_module()
    reads, ledger_prefixes, authentications = Counter(), Counter(), []
    read_blob = context.objects.read_blob
    authenticate = knowledge_activation._authenticated
    replay = module._replay
    def counted_read(key):
        reads[key] += 1
        return read_blob(key)
    def counted_authentication(*args, **kwargs):
        authentications.append(None)
        return authenticate(*args, **kwargs)
    def counted_replay(rows, protocol, objects):
        if protocol is PROTOCOL_28_LEDGER_PROTOCOL:
            ledger_prefixes[content_digest(rows)] += 1
        return replay(rows, protocol, objects)
    with monkeypatch.context() as observed:
        observed.setattr(context.objects, 'read_blob', counted_read)
        observed.setattr(knowledge_activation, '_authenticated', counted_authentication)
        observed.setattr(module, '_replay', counted_replay)
        assert revision_module().load_knowledge_revision(context) == expected
    # These fixtures have one immutable input catalogue shared by revisions.
    # Validation may derive it for input/plan/category checks, but must not repeat
    # discovery replay for every ledger record, counter, or dependency consumer.
    assert 0 < len(authentications) <= 4, len(authentications)
    assert reads and max(reads.values()) == 1, max(reads.values(), default=0)
    # Dependency/counter projections share each authenticated frozen prefix. The
    # final full-history chronology pass may independently replay that prefix.
    assert ledger_prefixes and max(ledger_prefixes.values()) <= 2, dict(ledger_prefixes)


@pytest.mark.unit
def test_revision_rejects_unproven_evidence_cause_without_writes(tmp_path):
    context, inputs, account, acquisition = revision_fixture(tmp_path)
    module = revision_module()
    active = module.activate_knowledge_workflow(context, account, allow_debt=False)
    affected = (active.dependencies.obligations[0].obligation_id,)
    cause = module.KnowledgeRevisionCauseV1(1, active.manifest.logical_run_id,
        active.manifest.revision_id, 'evidence-expansion', affected, (content_digest(b'forged outcome'),))
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError, match='cause|evidence|authority'):
        module.commit_knowledge_revision(context, inputs, cause)
    assert bytes_under(context.paths.root) == before


@pytest.mark.unit
def test_genuine_cross_account_revision_rejected_before_any_destination_write(tmp_path):
    from tests.unit.test_re_v2_protocol_28_preparation import _preparation_fixture
    prepared = _preparation_fixture(tmp_path / 'frozen')
    context, inputs, account, acquisition = revision_fixture(tmp_path / 'original', prepared=prepared)
    _, other, other_account, _ = revision_fixture(tmp_path / 'other',
        prepared=prepared, account_policy=KnowledgeDispatchPolicy(450_000, 90_000, 3))
    assert other.manifest.source_snapshot_id == inputs.manifest.source_snapshot_id
    assert other.manifest.budget_policy == inputs.manifest.budget_policy
    assert content_digest(account.opening) != content_digest(other_account.opening)
    module = revision_module()
    active = module.activate_knowledge_workflow(context, account, allow_debt=False)
    cause = expansion_cause(context, acquisition, active)
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError, match='account|authority'):
        module.commit_knowledge_revision(context, other, cause)
    assert bytes_under(context.paths.root) == before
    assert module.load_knowledge_revision(load_protocol_28_run_context(context.run_dir)) == active


@pytest.mark.unit
def test_post_activation_expansion_cannot_reset_two_rounds_or_resource_records(tmp_path):
    context, inputs, account, acquisition = revision_fixture(tmp_path)
    module = revision_module()
    active = module.activate_knowledge_workflow(context, account, allow_debt=False)
    resources = context.resources.path.read_bytes()
    for expected_round in (1, 2):
        affected = (active.dependencies.obligations[0].obligation_id,)
        cause = expansion_cause(context, acquisition, active, expected_round)
        active = module.commit_knowledge_revision(context, inputs, cause)
        assert active.manifest.expansion_rounds == expected_round
        assert module.commit_knowledge_revision(context, inputs, cause) == active
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError, match='round|expansion'):
        expansion_cause(context, acquisition, active, 3)
    assert context.resources.path.read_bytes() == resources
    assert bytes_under(context.paths.root) == before


@pytest.mark.unit
@pytest.mark.parametrize('member', ['manifest', 'dependencies', 'receipt', 'inputs'])
def test_committed_revision_missing_or_forged_closure_is_never_repaired(tmp_path, member):
    context, inputs, account, acquisition = revision_fixture(tmp_path)
    module = revision_module()
    initial = module.activate_knowledge_workflow(context, account, allow_debt=False)
    cause = expansion_cause(context, acquisition, initial)
    active = module.commit_knowledge_revision(context, inputs, cause)
    key = {'manifest': active.manifest.identity, 'dependencies': active.dependencies.identity,
           'receipt': active.receipt.identity, 'inputs': active.manifest.inputs_id}[member]
    suffix = key.split(':')[1]
    path = context.objects.root / 'sha256' / suffix[:2] / suffix[2:]
    path.chmod(0o600)
    path.write_bytes(b'{}\n')
    before = bytes_under(context.paths.root)
    with pytest.raises(ValueError):
        module.load_knowledge_revision(context)
    assert bytes_under(context.paths.root) == before
