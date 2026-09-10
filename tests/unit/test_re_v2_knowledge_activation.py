from __future__ import annotations

from dataclasses import replace
import importlib
import json

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_accounting import KnowledgeDispatchAccount, KnowledgeDispatchPolicy
from harness.re_v2.knowledge_acquisition import DiscoveryAcquisition
from harness.re_v2.knowledge_discovery import DiscoveryBoundary
from harness.re_v2.knowledge_dispatch import DiscoveryController, ProviderReply
from harness.re_v2.knowledge_evidence import EvidenceSelectorV1
from harness.re_v2.knowledge_review_dispatch import DiscoveryReviewController
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.provider import DispatchReservationV1, NormalizedUsageV1
from harness.re_v2.protocol_28.authority import build_l3_target_projections
from harness.re_v2.protocol_28.evidence import EvidenceStagingPolicyV1, stage_snapshot_evidence
from harness.re_v2.protocol_28.policies import DOMAIN_CATEGORIES, SOURCE_CATEGORIES, categories_for_depth
from harness.re_v2.run_store import ReV2Paths
from tests.unit.test_re_v2_knowledge_dispatch import _contract
from tests.unit.test_re_v2_knowledge_discovery_review_v2 import _review_v2
from tests.unit.test_re_v2_protocol_28_preparation import _preparation_fixture


def _candidate(context, *, unknown=False, deployment=False):
    refs = {row['projection']['path']: row['projection_id'] for row in context['evidence']}
    app = next(value for path, value in refs.items() if path.startswith('src/'))
    readme = refs['README.md']
    domains = [] if deployment else [dict(key='behavior', description='Handles a request.', evidence_ids=[app])]
    subjects = [dict(key='composition', target='source', description='Repository composition.',
                     category_ids=['source-composition'], evidence_ids=[readme] + ([app] if deployment else []))]
    if not deployment:
        subjects.append(dict(key='handler', target='behavior', description='Handles requests.',
                             category_ids=['public-surfaces'], evidence_ids=[app]))
    obligations = []
    for target, categories, evidence in [('source', SOURCE_CATEGORIES, [readme]), *(
        [('behavior', DOMAIN_CATEGORIES, [app])] if not deployment else [])]:
        for category in categories:
            members = [s['key'] for s in subjects if s['target'] == target and category in s['category_ids']]
            obligations.append(dict(target=target, category=category,
                disposition=('outside-requested-depth' if category not in categories_for_depth(context['depth'], 'source' if target == 'source' else 'domain')
                             else 'analyze' if members else 'unknown' if unknown and category == 'source-negative-space' else 'not-applicable'),
                subject_keys=members, rationale='Supported by the supplied scope.', evidence_ids=evidence))
    return dict(schema_version=2, kind='discovery_proposal', source_id=context['source_id'], domains=domains,
                subjects=subjects, obligations=obligations, questions=[], inventory=[
                    dict(path=path, owner='handler' if path.startswith('src/') and not deployment else 'composition', reason='Exact evidence owner.')
                    for path in sorted(refs)])


def activation_fixture(tmp_path, *, unknown=False, deployment=False, partial=False, legacy=False,
                       name_only=False, extra_source_files=None, multiple=False, depth='deep', exclude_empty=False,
                       shared_owner=None, inherited_canary=None, account_policy=None, initial_expansion=False,
                       prepared=None):
    workspace, intent, parent, options = prepared or _preparation_fixture(tmp_path, extra_source_files=extra_source_files)
    if multiple:
        from echelon.workspace_model import SourceRoot, WorkspaceInfo, WorkspaceManifest
        from harness.re_v2.workspace_snapshot import capture_workspace_snapshot
        from harness.re_v2.protocol_22.partition import build_workspace_partition_catalog, PartitionAuthoritiesV1, ImplementationAuthorityV1
        from harness.re_v2.protocol_28.preparation import _partition_manifest_authority_bytes
        from harness.re_v2.protocol_24.model import SelectionScopeV1
        from tests.unit.test_re_v2_protocol_28_evidence import _git, _write_files
        other = workspace / 'sources' / 'beta'
        other.mkdir()
        _git(other, 'init')
        _write_files(other, {'README.md': 'Worker service\n', 'src/orders/handler.py': 'def handle(): return 2\n'})
        _git(other, 'add', '.')
        _git(other, 'commit', '-m', 'fixture')
        sources = tuple(SourceRoot(id=source, path=f'sources/{source}', git_present=True) for source in ('api', 'beta'))
        snapshot = capture_workspace_snapshot(workspace, sources, tmp_path / 'multi-snapshots')
        manifest = WorkspaceManifest(schema_version=1, workspace=WorkspaceInfo(root=workspace.resolve(), git_role='orchestration', git_present=False), sources=sources)
        partition = build_workspace_partition_catalog(snapshot, manifest, PartitionAuthoritiesV1(
            ImplementationAuthorityV1('existing-domain-partitioner', '5', content_digest(b'partitioner')),
            ImplementationAuthorityV1('explicit-domain-ownership', '1', content_digest(b'ownership'))))
        selection = SelectionScopeV1(1, True, (), ())
        partition_bytes = _partition_manifest_authority_bytes(snapshot)
        partition_id = content_digest(partition_bytes)
        targets = []
        for source in partition.sources:
            for target in parent.targets:
                domain = source.domains[0]
                targets.append(replace(target, source_id=source.source_id,
                    target_id=domain.domain_key if target.target_kind == 'domain' else source.source_id,
                    target_content_id=domain.domain_content_id if target.target_kind == 'domain' else source.source_content_id))
        parent = replace(parent, source_snapshot_id=snapshot.snapshot_id, partition_manifest_id=partition_id,
            workspace_partition_catalog_id=partition.identity, selection_id=selection.identity,
            targets=tuple(sorted(targets, key=lambda t: t.sort_key)))
        intent = replace(intent, source_snapshot_id=snapshot.snapshot_id, partition_manifest_id=partition_id, selection=selection)
        options = replace(options, snapshot=snapshot, workspace_partition=partition,
                          authority_objects={**options.authority_objects, partition_id: partition_bytes})
    if deployment:
        from tests.unit.test_re_v2_protocol_28_evidence import _fixture
        from harness.re_v2.protocol_28.preparation import _partition_manifest_authority_bytes
        from harness.re_v2.protocol_24.model import SelectionScopeV1
        snapshot, partition = _fixture(tmp_path / 'deployment', {
            'README.md': 'Deployment stack; no application implementation.\n',
            'src/stack.yml': 'services:\n  web:\n    image: example/web:1\n    ports: [8080]\n',
        })
        assert not partition.sources[0].domains
        selection = SelectionScopeV1(1, False, ('api',), ())
        partition_bytes = _partition_manifest_authority_bytes(snapshot)
        partition_id = content_digest(partition_bytes)
        parent = replace(parent, source_snapshot_id=snapshot.snapshot_id, partition_manifest_id=partition_id,
            workspace_partition_catalog_id=partition.identity, selection_id=selection.identity,
            targets=tuple(replace(t, target_content_id=partition.sources[0].source_content_id)
                for t in parent.targets if t.target_kind == 'source'))
        intent = replace(intent, source_snapshot_id=snapshot.snapshot_id, partition_manifest_id=partition_id, selection=selection)
        options = replace(options, snapshot=snapshot, workspace_partition=partition,
                          authority_objects={**options.authority_objects, partition_id: partition_bytes})
        workspace = tmp_path / 'deployment' / 'workspace'
    paths = ReV2Paths.for_run(tmp_path / 'knowledge')
    if inherited_canary is not None:
        payload = f"Inherited authority TOKEN = '{inherited_canary}'".encode()
        key = content_digest(payload)
        parent = replace(parent, targets=tuple(replace(t, candidate_authority_hash=key) for t in parent.targets))
        options = replace(options, authority_objects={**options.authority_objects, key: payload})
    paths.root.mkdir(parents=True)
    objects = ObjectStore(paths.objects)
    boundary = DiscoveryBoundary(options.snapshot, options.workspace_partition, 'api', depth,
                                 content_digest(b'origin'), objects, ObjectStore(tmp_path / 'quarantine'))
    selectors = tuple(EvidenceSelectorV1('api', r.source_relative_path, 0,
                          min(r.byte_count, 3) if partial and r.source_relative_path.startswith('src/') else r.byte_count)
                      for r in options.workspace_partition.sources[0].files
                      if not (initial_expansion and r.source_relative_path.startswith('src/')))
    binding = boundary.prepare(selectors)
    acquisition = DiscoveryAcquisition(paths, boundary, binding)
    from harness.re_v2.knowledge_accounting import KnowledgeProviderContract
    contract = KnowledgeProviderContract('codex', 'fixture-model', content_digest(b'scripted-configured-capture'),
        'configured-provider-accounted', 'rendered-prompt-utf8-bytes')
    account = KnowledgeDispatchAccount(paths, account_policy or KnowledgeDispatchPolicy(500_000, 100_000, 3),
                                       contract, boundary.run_authority())
    reservation = DispatchReservationV1(100_000, 100_000, 10_000)
    producer_calls = 0
    def produce(_agent, context, _reservation):
        nonlocal producer_calls
        producer_calls += 1
        if initial_expansion and producer_calls == 1:
            from tests.unit.test_re_v2_knowledge_dispatch import _evidence
            path = next(row['path'] for row in json.loads(context)['inventory'] if row['path'].startswith('src/'))
            return ProviderReply(_evidence(context, path), NormalizedUsageV1('unavailable', None, {}))
        candidate = _candidate(json.loads(context), unknown=unknown, deployment=deployment)
        if shared_owner is not None:
            readme_ids = list(candidate['subjects'][0]['evidence_ids'])
            if shared_owner == 'cross-target':
                candidate['subjects'][1]['evidence_ids'] += readme_ids
                owner = 'handler'
            elif shared_owner == 'overflow':
                owner = 'composition'
                keys = [f'reader-{i}' for i in range(16)]
                candidate['subjects'] += [dict(key=key, target='source', description='Independent source perspective.',
                    category_ids=['source-composition'], evidence_ids=readme_ids) for key in keys]
                next(row for row in candidate['obligations'] if row['category'] == 'source-composition')['subject_keys'] += keys
            else:
                owner = 'reader'
                candidate['subjects'].append(dict(key=owner, target='source', description='Reviews source negative space.',
                    category_ids=['source-negative-space'], evidence_ids=readme_ids))
                next(row for row in candidate['obligations'] if row['category'] == 'source-negative-space').update(
                    disposition='analyze', subject_keys=[owner])
            next(row for row in candidate['inventory'] if row['path'] == 'README.md')['owner'] = owner
        if exclude_empty:
            next(row for row in candidate['inventory'] if row['path'] == 'empty.png')['owner'] = None
        if name_only:
            key = next(t.target_id for t in parent.targets if t.target_kind == 'domain')
            candidate['domains'][0].update(key=key,
                evidence_ids=next(s['evidence_ids'] for s in candidate['subjects'] if s['key'] == 'composition'))
            for row in candidate['subjects'] + candidate['obligations']:
                if row['target'] == 'behavior':
                    row['target'] = key
        if legacy:
            candidate['schema_version'] = 1
            for subject in candidate['subjects']:
                subject.pop('category_ids')
            candidate['obligations'] = [{k: row[k] for k in ('target', 'category')} for row in candidate['obligations']]
        return ProviderReply(canonical_json_bytes(candidate), NormalizedUsageV1('unavailable', None, {}))
    produce.contract_id = account.opening['provider_contract_id']
    producer = DiscoveryController(acquisition, account, b'discover', produce, reservation)
    if initial_expansion:
        assert producer.step().state == 'evidence_ready'
        assert acquisition.status().rounds == 1
    assert producer.step().state == 'proposal_ready'
    def verify(_agent, context, _reservation):
        value = json.loads(context)
        if legacy:
            value['candidate']['obligations'] = []
        response = _review_v2(value)
        if shared_owner is not None:
            subject_ids = {s['key']: set(s['evidence_ids']) for s in value['candidate']['subjects']}
            response['overlaps'] = [dict(subject_keys=pair, disposition='shared-evidence',
                rationale='Shared visible evidence; inventory specifies the sole primary owner.',
                evidence_ids=sorted(subject_ids[pair[0]] & subject_ids[pair[1]])) for pair in value['overlap_pairs']]
        if exclude_empty:
            next(row for row in response['inventory'] if row['path'] == 'empty.png')['disposition'] = 'excluded'
        if deployment:
            # Only one subject: both paths have independently supported ownership.
            pass
        if legacy:
            response['schema_version'] = 1
            response.pop('obligations')
        return ProviderReply(canonical_json_bytes(response), NormalizedUsageV1('unavailable', None, {}))
    verify.contract_id = account.opening['provider_contract_id']
    review = DiscoveryReviewController(producer, b'independent review', verify, reservation)
    assert review.step().state == 'review_ready'
    l3 = build_l3_target_projections(parent, intent.selection)
    evidence = stage_snapshot_evidence(options.snapshot, options.workspace_partition, intent.selection,
        EvidenceStagingPolicyV1(1, 8, ('.gif', '.ico', '.jpeg', '.jpg', '.mp4', '.png')), objects)
    return acquisition, account, review, l3, evidence, (workspace, intent, parent, options)


def _activation():
    return importlib.import_module('harness.re_v2.knowledge_activation')


def _files(objects):
    return {str(p.relative_to(objects.root)): p.read_bytes() for p in objects.root.rglob('*') if p.is_file()}


@pytest.mark.unit
@pytest.mark.parametrize('payload', ['', '\x00binary'])
def test_reviewed_nonanalyzable_file_has_an_exact_authenticated_exclusion(tmp_path, payload):
    acquisition, account, review, l3, evidence, _ = activation_fixture(
        tmp_path, extra_source_files={'empty.png': payload}, exclude_empty=True)
    module = _activation()
    root = module.activate_reviewed_discovery(acquisition, account, review, l3, evidence)
    bundle = module.load_reviewed_discovery(root, acquisition.objects, l3, evidence)
    (empty,) = (*evidence.empty_receipts, *evidence.nontext_dispositions)
    owner = next(row for row in bundle.inventory_assessments if row.path == 'empty.png')
    assert owner.raw_evidence_ids == (empty.identity,)
    assert owner.subject_id is None and owner.disposition == 'excluded'


@pytest.mark.unit
def test_supporting_domain_evidence_cannot_replace_reviewed_primary_source_ownership(tmp_path):
    acquisition, account, review, l3, evidence, _ = activation_fixture(tmp_path, shared_owner='cross-target')
    before = _files(acquisition.objects)
    with pytest.raises(ValueError, match='owner|ownership'):
        _activation().activate_reviewed_discovery(acquisition, account, review, l3, evidence)
    assert _files(acquisition.objects) == before


@pytest.mark.unit
def test_reviewed_activation_exact_ownership_dispositions_and_read_only_reopen(tmp_path, monkeypatch):
    acquisition, account, review, l3, evidence, _ = activation_fixture(tmp_path)
    module = _activation()
    root = module.activate_reviewed_discovery(acquisition, account, review, l3, evidence)
    bundle = module.load_reviewed_discovery(root, acquisition.objects, l3, evidence)
    assert root.active_revision_id == acquisition.status().revision_id
    assert root.source_id == 'api' and root.depth == 'deep'
    assert len(bundle.subject_catalog.subjects) == 2
    assert {s.category_ids for s in bundle.subject_catalog.subjects} == {('public-surfaces',), ('source-composition',)}
    owned = [eid for row in bundle.inventory_assessments for eid in row.raw_evidence_ids]
    assert sorted(owned) == sorted(s.identity for s in evidence.shards)
    assert len(owned) == len(set(owned))
    assert len(bundle.category_assessments) == 12
    assert sum(row.disposition == 'not-applicable' for row in bundle.category_assessments) == 10
    assert json.loads(acquisition.objects.read_blob(root.review_receipt_id))['analysis_certified'] is False
    before = _files(acquisition.objects)
    def no_write(_payload):
        raise AssertionError('reopen wrote an object')
    monkeypatch.setattr(acquisition.objects, 'put_blob', no_write)
    assert module.activate_reviewed_discovery(acquisition, account, review, l3, evidence) == root
    assert _files(acquisition.objects) == before


@pytest.mark.unit
def test_activation_root_is_written_after_complete_safe_and_reviewed_child_closure(tmp_path, monkeypatch):
    acquisition, account, review, l3, evidence, _ = activation_fixture(tmp_path)
    module = _activation()
    writes = []
    original = acquisition.objects.put_blob
    def record(payload):
        writes.append(content_digest(payload))
        return original(payload)
    monkeypatch.setattr(acquisition.objects, 'put_blob', record)
    root = module.activate_reviewed_discovery(acquisition, account, review, l3, evidence)
    bundle = module.load_reviewed_discovery(root, acquisition.objects, l3, evidence)
    catalog = json.loads(bundle.objects[root.subject_catalog_id])
    safe = json.loads(bundle.objects[catalog['safe_evidence_catalog_id']])
    for row in safe['objects']:
        row_id = content_digest(row)
        assert acquisition.objects.read_blob(row_id) == canonical_json_bytes(row)
        assert writes.index(row_id) < writes.index(root.identity)
    assert writes[-1] == root.identity


@pytest.mark.unit
@pytest.mark.parametrize('mutation', ['partial', 'legacy', 'target', 'source', 'policy', 'receipt', 'revision'])
def test_activation_rejects_unauthenticated_inputs_without_children(tmp_path, mutation):
    acquisition, account, review, l3, evidence, _ = activation_fixture(
        tmp_path, partial=mutation == 'partial', legacy=mutation == 'legacy')
    if mutation == 'target':
        l3 = replace(l3, source_snapshot_id=content_digest(b'wrong snapshot'))
    elif mutation == 'source':
        acquisition.opening['evidence_scope']['source_id'] = 'other'
    elif mutation == 'policy':
        account.opening['run_authority']['security_policy_id'] = content_digest(b'wrong policy')
    elif mutation == 'receipt':
        state = account._state()
        receipt_id = state.applied[state.review_sources['api'][-1]]['receipt_id']
        path = acquisition.objects.root / 'sha256' / receipt_id[7:9] / receipt_id[9:]
        path.chmod(0o600)
        path.write_bytes(b'{}')
    elif mutation == 'revision':
        acquisition.opening['context_id'] = content_digest(b'wrong revision')
    before = _files(acquisition.objects)
    with pytest.raises(ValueError):
        _activation().activate_reviewed_discovery(acquisition, account, review, l3, evidence)
    assert _files(acquisition.objects) == before


@pytest.mark.unit
def test_activation_replay_rejects_rebound_category_and_private_mapping(tmp_path):
    acquisition, account, review, l3, evidence, _ = activation_fixture(tmp_path)
    module = _activation()
    root = module.activate_reviewed_discovery(acquisition, account, review, l3, evidence)
    bundle = module.load_reviewed_discovery(root, acquisition.objects, l3, evidence)
    row = bundle.category_assessments[0]
    changed = replace(row, disposition='unknown')
    acquisition.objects.put_blob(canonical_json_bytes(changed.to_json_dict()))
    forged = replace(root, category_assessment_ids=tuple(sorted(
        changed.identity if x == row.identity else x for x in root.category_assessment_ids)))
    before = _files(acquisition.objects)
    with pytest.raises(ValueError):
        module.load_reviewed_discovery(forged, acquisition.objects, l3, evidence)
    assert _files(acquisition.objects) == before


@pytest.mark.unit
@pytest.mark.parametrize('part', ['root', 'mapping', 'proof-member', 'category'])
def test_existing_activation_corruption_is_never_repaired_or_written(tmp_path, monkeypatch, part):
    acquisition, account, review, l3, evidence, _ = activation_fixture(tmp_path)
    module = _activation()
    root = module.activate_reviewed_discovery(acquisition, account, review, l3, evidence)
    bundle = module.load_reviewed_discovery(root, acquisition.objects, l3, evidence)
    victim = {'root': root.identity, 'mapping': bundle.target_mappings[0].identity,
              'proof-member': root.proposal_receipt_id, 'category': root.category_assessment_ids[0]}[part]
    path = acquisition.objects.root / 'sha256' / victim[7:9] / victim[9:]
    path.chmod(0o600)
    path.write_bytes(b'{}')
    before = _files(acquisition.objects)
    writes = []
    original = acquisition.objects.put_blob
    def record_write(payload):
        writes.append(content_digest(payload))
        return original(payload)
    monkeypatch.setattr(acquisition.objects, 'put_blob', record_write)
    with pytest.raises(ValueError):
        module.activate_reviewed_discovery(acquisition, account, review, l3, evidence)
    assert writes == []
    assert _files(acquisition.objects) == before


@pytest.mark.unit
def test_reviewed_deployment_records_no_domain_with_exact_dispositions(tmp_path):
    acquisition, account, review, l3, evidence, _ = activation_fixture(tmp_path, deployment=True)
    module = _activation()
    root = module.activate_reviewed_discovery(acquisition, account, review, l3, evidence)
    bundle = module.load_reviewed_discovery(root, acquisition.objects, l3, evidence)
    assert len(bundle.subject_catalog.subjects) == 1
    assert bundle.subject_catalog.subjects[0].target_kind == 'source'
    absent = [m for m in bundle.target_mappings if m.disposition == 'reviewed-no-domain']
    assert len(absent) == 1 and absent[0].raw_evidence_ids
    domain_categories = [r for r in bundle.category_assessments if r.target_kind == 'domain']
    assert len(domain_categories) == 7
    assert all(r.disposition == 'not-applicable' for r in domain_categories)


@pytest.mark.unit
def test_name_equality_does_not_authorize_a_domain_mapping(tmp_path):
    acquisition, account, review, l3, evidence, _ = activation_fixture(tmp_path, name_only=True)
    before = _files(acquisition.objects)
    with pytest.raises(ValueError, match='unmapped'):
        _activation().activate_reviewed_discovery(acquisition, account, review, l3, evidence)
    assert _files(acquisition.objects) == before


@pytest.mark.unit
def test_passive_review_object_without_ledger_application_cannot_activate(tmp_path):
    acquisition, account, review, l3, evidence, _ = activation_fixture(tmp_path)
    lines = account.ledger.path.read_bytes().splitlines(keepends=True)
    assert json.loads(lines[-1])['type'] == 'review_applied'
    account.ledger.path.write_bytes(b''.join(lines[:-1]))
    before = _files(acquisition.objects)
    with pytest.raises(ValueError, match='revision'):
        _activation().activate_reviewed_discovery(acquisition, account, review, l3, evidence)
    assert _files(acquisition.objects) == before


def review_second_source(tmp_path, acquisition, account, review, options):
    boundary = DiscoveryBoundary(options.snapshot, options.workspace_partition, 'beta', 'deep', content_digest(b'beta-origin'),
        acquisition.objects, ObjectStore(tmp_path / 'beta-quarantine'))
    source = next(s for s in options.workspace_partition.sources if s.source_id == 'beta')
    binding = boundary.prepare(tuple(EvidenceSelectorV1('beta', r.source_relative_path, 0, r.byte_count) for r in source.files))
    phase = DiscoveryAcquisition(acquisition.paths, boundary, binding)
    def produce(_agent, context, _reservation):
        return ProviderReply(canonical_json_bytes(_candidate(json.loads(context))), NormalizedUsageV1('unavailable', None, {}))
    def verify(_agent, context, _reservation):
        return ProviderReply(canonical_json_bytes(_review_v2(json.loads(context))), NormalizedUsageV1('unavailable', None, {}))
    produce.contract_id = verify.contract_id = account.opening['provider_contract_id']
    producer = DiscoveryController(phase, account, b'beta-discover', produce, review.reservation)
    assert producer.step().state == 'proposal_ready'
    other_review = DiscoveryReviewController(producer, b'beta-review', verify, review.reservation)
    assert other_review.step().state == 'review_ready'
    return phase, other_review


@pytest.mark.unit
def test_other_source_account_progress_does_not_rewrite_an_activated_root(tmp_path, monkeypatch):
    acquisition, account, review, l3, evidence, fixture = activation_fixture(tmp_path, multiple=True)
    module = _activation()
    root = module.activate_reviewed_discovery(acquisition, account, review, l3, evidence)
    review_second_source(tmp_path, acquisition, account, review, fixture[-1])
    before = _files(acquisition.objects)
    def no_write(_payload):
        pytest.fail('later account progress rewrote activation')
    monkeypatch.setattr(acquisition.objects, 'put_blob', no_write)
    assert module.activate_reviewed_discovery(acquisition, account, review, l3, evidence) == root
    assert _files(acquisition.objects) == before
