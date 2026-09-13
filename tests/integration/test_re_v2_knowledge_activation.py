from dataclasses import replace
import importlib
import json

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_28.inputs import Protocol28InputError, stage_exhaustive_inputs, publish_protocol_28_run, load_protocol_28_inputs
from harness.re_v2.protocol_28.policies import build_repaired_exhaustive_policy
from harness.re_v2.protocol_28.context import Protocol28RunContext, build_protocol_28_slice_context
from harness.re_v2.protocol_28.planning import realize_slice
from tests.unit.test_re_v2_knowledge_activation import activation_fixture, _files


def reviewed_preparation_fixture(tmp_path, **kwargs):
    from harness.re_v2.knowledge_activation import activate_reviewed_discovery, load_reviewed_discovery
    acquisition, account, review, l3, evidence, fixture = activation_fixture(tmp_path, **kwargs)
    root = activate_reviewed_discovery(acquisition, account, review, l3, evidence)
    bundle = load_reviewed_discovery(root, acquisition.objects, l3, evidence)
    workspace, intent, parent, options = fixture
    preparation = importlib.import_module('harness.re_v2.protocol_28.preparation')
    reviewed_options = preparation.ReviewedProtocol28PreparationOptions(
        **{f: getattr(options, f) for f in options.__dataclass_fields__},
        reviewed_discoveries=(bundle,),
    )
    policy = build_repaired_exhaustive_policy(producer_contract_hash=content_digest(options.producer_agent_bytes),
                                             verifier_contract_hash=content_digest(options.verifier_agent_bytes))
    intent = replace(intent, exhaustive_policy_catalog_id=policy.identity)
    return preparation, workspace, intent, parent, reviewed_options, acquisition


@pytest.mark.integration
def test_real_reviewed_preparation_staging_replay_and_provider_context(tmp_path, monkeypatch):
    preparation, workspace, intent, parent, options, _ = reviewed_preparation_fixture(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('mechanical subject construction is forbidden')
    monkeypatch.setattr(preparation, '_build_evidence_subjects', forbidden)
    size_contexts = preparation._bind_exact_context_sizes
    sizing_calls = []
    def require_safe_catalogues(*args, **kwargs):
        assert args[6] is not None and args[7] is not None
        assert kwargs['reviewed']
        sizing_calls.append(True)
        return size_contexts(*args, **kwargs)
    monkeypatch.setattr(preparation, '_bind_exact_context_sizes', require_safe_catalogues)
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    assert sizing_calls
    assert type(inputs).__name__ == 'ReviewedProtocol28CreationInputs'
    assert type(inputs.manifest).__name__ == 'ReviewedExhaustiveRunManifestV7'
    assert sum(len(t.entries) for t in inputs.exhaustive_plan.target_plans) == 2
    vacancies = [v for t in inputs.exhaustive_plan.target_plans for v in t.vacancy_receipts]
    assert len(vacancies) == 10
    assert all(v.reviewed_disposition_id for v in vacancies)
    staged = stage_exhaustive_inputs(tmp_path / 'private', inputs)
    published = publish_protocol_28_run(staged.root.parent, tmp_path / inputs.manifest.run_id, inputs.manifest)
    loaded = load_protocol_28_inputs(published.root.parent)
    assert type(loaded).__name__ == 'ValidatedReviewedProtocol28Inputs'
    assert loaded.manifest == inputs.manifest
    context = Protocol28RunContext(published, loaded, None, None, None, None, None)
    for target in loaded.exhaustive_plan.target_plans:
        for entry in target.entries:
            spec = realize_slice(entry, {key: key for key in entry.planned_dependency_root_ids})
            from harness.re_v2.protocol_28.artifacts import ExhaustiveEvidenceSliceV1, ExhaustiveObservationV1
            observation = ExhaustiveObservationV1(1, 'applicable', entry.category_id, entry.primary_subject_ids,
                entry.primary_snapshot_evidence_ids, (), 'A supported fixture observation.')
            candidate = ExhaustiveEvidenceSliceV1(1, spec.identity, entry.identity, entry.target_kind,
                entry.source_id, entry.target_id, entry.category_id, entry.primary_subject_ids,
                entry.primary_source_record_ids, entry.primary_snapshot_evidence_ids, (), (), (observation,),
                entry.assigned_finding_ids, (), 'A fixture candidate.')
            for role in ('producer', 'verifier'):
                payload = build_protocol_28_slice_context(context, target, entry, spec, role=role,
                    candidate=candidate if role == 'verifier' else None)
                decoded = json.loads(payload)
                assert decoded['reviewed_obligations']['depth'] == 'deep'
                assert len(decoded['reviewed_obligations']['categories']) in (5, 7)
                assert b'private_discovery_binding' not in payload
                assert b'reviewed_discovery_replay' not in payload
                assert b'Exact evidence owner.' not in payload


@pytest.mark.integration
def test_unknown_deep_obligation_blocks_preparation_without_children(tmp_path):
    preparation, workspace, intent, parent, options, acquisition = reviewed_preparation_fixture(tmp_path, unknown=True)
    before = _files(acquisition.objects)
    with pytest.raises(ValueError, match='unknown'):
        preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    assert _files(acquisition.objects) == before
    assert not (tmp_path / 'private').exists()


@pytest.mark.integration
def test_rebound_reviewed_authority_cannot_create_a_child(tmp_path):
    preparation, workspace, intent, parent, options, acquisition = reviewed_preparation_fixture(tmp_path)
    bundle = options.reviewed_discoveries[0]
    root = replace(bundle.authority, active_revision_id=content_digest(b'forged revision'))
    options = replace(options, reviewed_discoveries=(replace(bundle, authority=root),))
    before = _files(acquisition.objects)
    with pytest.raises(ValueError):
        preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    assert _files(acquisition.objects) == before


@pytest.mark.integration
def test_deployment_preparation_creates_useful_source_work_and_no_invented_domain(tmp_path, monkeypatch):
    preparation, workspace, intent, parent, options, _ = reviewed_preparation_fixture(tmp_path, deployment=True)
    monkeypatch.setattr(preparation, '_build_evidence_subjects', lambda *a, **k: pytest.fail('mechanical subjects'))
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    (source,) = inputs.exhaustive_plan.target_plans
    assert source.target_kind == 'source'
    assert source.entries and all(e.primary_subject_ids for e in source.entries)
    assert {i for e in source.entries for i in e.primary_snapshot_evidence_ids} == {
        s.identity for s in inputs.snapshot_evidence_catalog.shards}
    stage_exhaustive_inputs(tmp_path / 'deployment-child', inputs)


@pytest.mark.integration
@pytest.mark.parametrize('mutation', ['missing', 'extra', 'duplicate', 'category', 'request'])
def test_reviewed_durable_closure_mutations_fail_before_child_creation(tmp_path, mutation):
    preparation, workspace, intent, parent, options, _ = reviewed_preparation_fixture(tmp_path)
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    catalog = inputs.reviewed_discovery_catalog
    before = set(tmp_path.iterdir())
    with pytest.raises((ValueError, Protocol28InputError)):
        if mutation == 'request':
            request = replace(inputs.manifest.exhaustive_request, reviewed_discovery_catalog_id=content_digest(b'other'))
            manifest = replace(inputs.manifest, exhaustive_request=request)
            replace(inputs, manifest=manifest)
        elif mutation == 'category':
            target = inputs.exhaustive_plan.target_plans[0]
            vacancy = replace(target.vacancy_receipts[0], reviewed_disposition_id=content_digest(b'other'))
            target = replace(target, vacancy_receipts=(vacancy, *target.vacancy_receipts[1:]))
            plan = replace(inputs.exhaustive_plan, target_plans=(target, *inputs.exhaustive_plan.target_plans[1:]))
            request = replace(inputs.manifest.exhaustive_request, exhaustive_plan_id=plan.identity)
            manifest = replace(inputs.manifest, exhaustive_request=request, exhaustive_plan_id=plan.identity)
            replace(inputs, manifest=manifest, exhaustive_plan=plan)
        else:
            ids = catalog.object_ids
            opaque = dict(inputs.authority_objects)
            if mutation == 'missing':
                opaque.pop(catalog.authority_ids[0])
            elif mutation == 'extra':
                object_id = content_digest(b'extra unbound authority')
                opaque[object_id] = b'extra unbound authority'
                ids = tuple(sorted((*ids, object_id)))
            else:
                ids = (*ids, ids[-1])
            catalog = replace(catalog, object_ids=ids)
            request = replace(inputs.manifest.exhaustive_request, reviewed_discovery_catalog_id=catalog.identity)
            manifest = replace(inputs.manifest, exhaustive_request=request, reviewed_discovery_catalog_id=catalog.identity)
            replace(inputs, manifest=manifest, authority_objects=opaque, reviewed_discovery_catalog=catalog)
    assert set(tmp_path.iterdir()) == before


@pytest.mark.integration
def test_every_selected_source_requires_its_own_reviewed_root(tmp_path):
    from harness.re_v2.knowledge_activation import activate_reviewed_discovery, load_reviewed_discovery
    from tests.unit.test_re_v2_knowledge_activation import review_second_source
    acquisition, account, review, l3, evidence, fixture = activation_fixture(tmp_path, multiple=True, shared_owner='same-target')
    workspace, intent, parent, options = fixture
    preparation = importlib.import_module('harness.re_v2.protocol_28.preparation')
    root = activate_reviewed_discovery(acquisition, account, review, l3, evidence)
    first = load_reviewed_discovery(root, acquisition.objects, l3, evidence)
    policy = build_repaired_exhaustive_policy(producer_contract_hash=content_digest(options.producer_agent_bytes),
                                             verifier_contract_hash=content_digest(options.verifier_agent_bytes))
    intent = replace(intent, exhaustive_policy_catalog_id=policy.identity)
    reviewed_options = preparation.ReviewedProtocol28PreparationOptions(
        **{f: getattr(options, f) for f in options.__dataclass_fields__}, reviewed_discoveries=(first,))
    with pytest.raises(ValueError, match='closure'):
        preparation.prepare_protocol_28_request(workspace, intent, parent, reviewed_options)
    second_phase, second_review = review_second_source(tmp_path, acquisition, account, review, options)
    second_root = activate_reviewed_discovery(second_phase, account, second_review, l3, evidence)
    second = load_reviewed_discovery(second_root, acquisition.objects, l3, evidence)
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent,
        replace(reviewed_options, reviewed_discoveries=(first, second)))
    assert len(inputs.reviewed_discovery_catalog.authority_ids) == 2
    assert {t.source_id for t in inputs.exhaustive_plan.target_plans} == {'api', 'beta'}
    _assert_reviewed_owners(inputs, (first, second))
    staged = stage_exhaustive_inputs(tmp_path / 'two-source-child', inputs)
    published = publish_protocol_28_run(staged.root.parent, tmp_path / inputs.manifest.run_id, inputs.manifest)
    _assert_reviewed_owners(load_protocol_28_inputs(published.root.parent), (first, second))


@pytest.mark.integration
@pytest.mark.parametrize(('depth', 'outside_count'), [('quick', 6), ('standard', 2)])
def test_reviewed_depth_complement_remains_authenticated_and_explicit(tmp_path, depth, outside_count):
    preparation, workspace, intent, parent, options, _ = reviewed_preparation_fixture(tmp_path, depth=depth)
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    bundle = options.reviewed_discoveries[0]
    outside = {row.identity for row in bundle.category_assessments if row.disposition == 'outside-requested-depth'}
    assert len(outside) == outside_count
    vacancies = {v.reviewed_disposition_id for t in inputs.exhaustive_plan.target_plans for v in t.vacancy_receipts}
    assert outside.issubset(vacancies)


@pytest.mark.integration
def test_reviewed_provider_context_never_serializes_local_replay_or_raw_secret_bytes(tmp_path):
    import base64
    canary = 'ghp_' + 'q' * 36
    preparation, workspace, intent, parent, options, _ = reviewed_preparation_fixture(tmp_path,
        extra_source_files={'src/orders/handler.py': f"API_TOKEN = '{canary}'\ndef handle(): return 1\n"})
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    context = Protocol28RunContext(None, inputs, None, None, None, None, None)
    assert any(canary.encode() in b''.join(s.raw_bytes for s in inputs.snapshot_evidence_catalog.shards
        if s.source_relative_path == path) for path in {'src/orders/handler.py'})
    for target in inputs.exhaustive_plan.target_plans:
        for entry in target.entries:
            spec = realize_slice(entry, {key: key for key in entry.planned_dependency_root_ids})
            payload = build_protocol_28_slice_context(context, target, entry, spec, role='producer')
            value = json.loads(payload)
            assert canary.encode() not in payload
            assert b'private_discovery_binding' not in payload and b'reviewed_discovery_replay' not in payload
            assert all(canary.encode() not in base64.b64decode(row['bytes_base64']) for row in value['lower_authority_objects'])


@pytest.mark.integration
@pytest.mark.parametrize('downgrade', ['reviewed-safe', 'reviewed-historical', 'safe-historical'])
@pytest.mark.parametrize('boundary', ['constructor', 'renderer'])
@pytest.mark.parametrize('canary_location', ['source', 'inherited'])
def test_manifest_subtype_downgrades_cannot_render_decoded_canaries(tmp_path, downgrade, boundary, canary_location):
    import base64
    from dataclasses import fields
    from harness.re_v2.protocol_28.inputs import ValidatedProtocol28Inputs, ValidatedSafeProtocol28Inputs
    from harness.re_v2.protocol_28.context import Protocol28ContextError
    canary = 'ghp_' + 'w' * 36
    preparation, workspace, intent, parent, options, _ = reviewed_preparation_fixture(tmp_path,
        extra_source_files={'src/orders/handler.py': f"TOKEN = '{canary}'\ndef handle(): return 1\n"} if canary_location == 'source' else None,
        inherited_canary=canary if canary_location == 'inherited' else None)
    if downgrade == 'safe-historical':
        options = preparation.Protocol28PreparationOptions(**{
            f.name: getattr(options, f.name) for f in fields(preparation.Protocol28PreparationOptions)})
        from harness.re_v2.protocol_28.policies import build_initial_exhaustive_policy
        policy = build_initial_exhaustive_policy(producer_contract_hash=content_digest(options.producer_agent_bytes),
                                                verifier_contract_hash=content_digest(options.verifier_agent_bytes))
        intent = replace(intent, exhaustive_policy_catalog_id=policy.identity)
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    wrapper = ValidatedSafeProtocol28Inputs if downgrade == 'reviewed-safe' else ValidatedProtocol28Inputs
    values = {f.name: getattr(inputs, f.name) for f in fields(wrapper)}
    # Retain only lower-authority bytes; all reviewed roots and proof are missing.
    values['authority_objects'] = {row.raw_authority_id: inputs.authority_objects[row.raw_authority_id]
                                  for row in inputs.safe_lower_authority_catalog.objects}
    def attempt():
        if boundary == 'constructor':
            downgraded = wrapper(**values)
            pytest.fail('public constructor accepted an incompatible manifest subtype')
        else:
            # Reassembled/public wrapper state cannot bypass the renderer's own gate.
            downgraded = object.__new__(wrapper)
            for key, value in values.items():
                object.__setattr__(downgraded, key, value)
        context = Protocol28RunContext(None, downgraded, None, None, None, None, None)
        for target in inputs.exhaustive_plan.target_plans:
            for entry in target.entries:
                spec = realize_slice(entry, {key: key for key in entry.planned_dependency_root_ids})
                payload = json.loads(build_protocol_28_slice_context(context, target, entry, spec, role='producer'))
                raw = [row for row in payload['snapshot_evidence'] if 'raw_bytes_base64' in row]
                for path in {row['source_relative_path'] for row in raw}:
                    decoded = b''.join(base64.b64decode(row['raw_bytes_base64'])
                        for row in sorted(raw, key=lambda r: r['byte_start']) if row['source_relative_path'] == path)
                    assert canary.encode() not in decoded, 'subtype downgrade exposed decoded source credential'
                assert all(canary.encode() not in base64.b64decode(row['bytes_base64'])
                           for row in payload['lower_authority_objects']), 'subtype downgrade exposed inherited credential'
        pytest.fail('manifest-bearing downgrade reached the public renderer')
    with pytest.raises((Protocol28InputError, Protocol28ContextError), match='subtype|manifest|validated'):
        attempt()


@pytest.mark.integration
@pytest.mark.parametrize('parent_kind', ['historical', 'safe'])
def test_exact_parent_manifest_cannot_hide_a_reviewed_request_subtype(tmp_path, parent_kind):
    from dataclasses import fields
    from harness.re_v2.protocol_28.inputs import ValidatedProtocol28Inputs, ValidatedSafeProtocol28Inputs
    from harness.re_v2.protocol_28.model import ExhaustiveRunManifestV7, SafeExhaustiveRunManifestV7
    preparation, workspace, intent, parent, options, _ = reviewed_preparation_fixture(tmp_path)
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    manifest_type, input_type = ((ExhaustiveRunManifestV7, ValidatedProtocol28Inputs) if parent_kind == 'historical'
        else (SafeExhaustiveRunManifestV7, ValidatedSafeProtocol28Inputs))
    manifest = object.__new__(manifest_type)
    for field in fields(manifest_type):
        object.__setattr__(manifest, field.name, getattr(inputs.manifest, field.name))
    with pytest.raises(Protocol28InputError, match='subtype'):
        input_type(**{field.name: manifest if field.name == 'manifest' else getattr(inputs, field.name)
                      for field in fields(input_type)})


def _assert_reviewed_owners(inputs, bundles):
    subjects = {s.identity: s for s in inputs.exhaustive_subject_catalog.subjects}
    entries = [e for t in inputs.exhaustive_plan.target_plans for e in t.entries]
    for bundle in bundles:
        for row in bundle.inventory_assessments:
            if row.disposition != 'owned':
                continue
            owner = subjects[row.subject_id]
            for raw_id in row.raw_evidence_ids:
                primary = [e for e in entries if raw_id in e.primary_snapshot_evidence_ids]
                assert len(primary) == 1, 'raw evidence has zero or duplicate primary work'
                entry = primary[0]
                assert (entry.source_id, entry.target_kind, entry.target_id) == (owner.source_id, owner.target_kind, owner.target_id)
                assert owner.identity in entry.primary_subject_ids + entry.supporting_subject_ids
                assert entry.category_id in owner.category_ids


@pytest.mark.integration
def test_shared_subject_evidence_keeps_exact_reviewed_owner_through_durable_replay(tmp_path):
    preparation, workspace, intent, parent, options, _ = reviewed_preparation_fixture(tmp_path, shared_owner='same-target')
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    _assert_reviewed_owners(inputs, options.reviewed_discoveries)
    source = next(t for t in inputs.exhaustive_plan.target_plans if t.target_kind == 'source')
    assert {e.category_id for e in source.entries if e.primary_snapshot_evidence_ids} == {'source-negative-space'}
    staged = stage_exhaustive_inputs(tmp_path / 'owned-child', inputs)
    published = publish_protocol_28_run(staged.root.parent, tmp_path / inputs.manifest.run_id, inputs.manifest)
    loaded = load_protocol_28_inputs(published.root.parent)
    _assert_reviewed_owners(loaded, options.reviewed_discoveries)


@pytest.mark.integration
def test_overflow_support_cannot_substitute_another_subject_for_primary_owner(tmp_path):
    preparation, workspace, intent, parent, options, _ = reviewed_preparation_fixture(tmp_path, shared_owner='overflow')
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    source = next(t for t in inputs.exhaustive_plan.target_plans if t.target_kind == 'source')
    assert len(source.entries) >= 2
    _assert_reviewed_owners(inputs, options.reviewed_discoveries)
    staged = stage_exhaustive_inputs(tmp_path / 'overflow-owner', inputs)
    published = publish_protocol_28_run(staged.root.parent, tmp_path / inputs.manifest.run_id, inputs.manifest)
    _assert_reviewed_owners(load_protocol_28_inputs(published.root.parent), options.reviewed_discoveries)


@pytest.mark.integration
def test_exact_evidence_chunk_split_retains_the_authenticated_owner(tmp_path):
    preparation, workspace, intent, parent, options, _ = reviewed_preparation_fixture(tmp_path, shared_owner='overflow')
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    source = next(t for t in inputs.exhaustive_plan.target_plans if t.target_kind == 'source')
    entry = next(e for e in source.entries if e.primary_snapshot_evidence_ids)
    owners = {raw_id: row.subject_id for b in options.reviewed_discoveries for row in b.inventory_assessments
              if row.disposition == 'owned' for raw_id in row.raw_evidence_ids}
    raw_id = entry.primary_snapshot_evidence_ids[-1]
    records = {s.identity: s.file_record_hash for s in inputs.snapshot_evidence_catalog.shards}
    chunk = preparation._entry_for_evidence_chunk(entry, (raw_id,), {records[raw_id]: raw_id},
        first_chunk=False, ordinal=2, subjects=inputs.exhaustive_subject_catalog, record_for=records,
        reviewed_owner_ids=owners)
    assert chunk.primary_snapshot_evidence_ids == (raw_id,)
    assert chunk.primary_subject_ids == ()
    assert owners[raw_id] in chunk.supporting_subject_ids


@pytest.mark.integration
@pytest.mark.parametrize('defect', ['wrong-owner', 'duplicate', 'orphan'])
def test_durable_rebound_plan_cannot_replace_or_drop_reviewed_primary_owner(tmp_path, defect):
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.run_store import ReV2Paths
    preparation, workspace, intent, parent, options, _ = reviewed_preparation_fixture(tmp_path, shared_owner='same-target')
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    source = next(t for t in inputs.exhaustive_plan.target_plans if t.target_kind == 'source')
    owner = next(e for e in source.entries if e.category_id == 'source-negative-space')
    other = next(e for e in source.entries if e.category_id == 'source-composition')
    raw_ids, records = owner.primary_snapshot_evidence_ids, owner.primary_source_record_ids
    if defect != 'orphan':
        other = replace(other, primary_snapshot_evidence_ids=raw_ids,
            supporting_snapshot_evidence_ids=tuple(i for i in other.supporting_snapshot_evidence_ids if i not in raw_ids),
            primary_source_record_ids=records,
            supporting_source_record_ids=tuple(i for i in other.supporting_source_record_ids if i not in records))
    if defect != 'duplicate':
        owner = replace(owner, primary_snapshot_evidence_ids=(), primary_source_record_ids=(),
            supporting_snapshot_evidence_ids=tuple(sorted(set(owner.supporting_snapshot_evidence_ids + raw_ids))),
            supporting_source_record_ids=tuple(sorted(set(owner.supporting_source_record_ids + records))))
    source = replace(source, entries=tuple(owner if e.category_id == owner.category_id else other for e in source.entries))
    plan = replace(inputs.exhaustive_plan, target_plans=tuple(source if t.target_kind == 'source' else t
        for t in inputs.exhaustive_plan.target_plans))
    manifest = replace(inputs.manifest, exhaustive_plan_id=plan.identity,
        exhaustive_request=replace(inputs.manifest.exhaustive_request, exhaustive_plan_id=plan.identity))
    with pytest.raises(Protocol28InputError, match='owner|assignment'):
        replace(inputs, manifest=manifest, exhaustive_plan=plan)
    staged = stage_exhaustive_inputs(tmp_path / 'valid-owner', inputs)
    published = publish_protocol_28_run(staged.root.parent, tmp_path / inputs.manifest.run_id, inputs.manifest)
    paths = ReV2Paths.for_run(published.root.parent)
    store = ObjectStore(paths.objects)
    for value in (source, source.coverage_ledger, *source.entries, plan, manifest.exhaustive_request):
        store.put_blob(canonical_json_bytes(value.to_json_dict()))
    for path, value in ((paths.inputs / 'exhaustive-plan.json', plan),
                        (paths.inputs / 'exhaustive-request.json', manifest.exhaustive_request), (paths.manifest, manifest)):
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(value.to_json_dict()))
    before = _files(store)
    with pytest.raises(Protocol28InputError, match='owner|assignment'):
        load_protocol_28_inputs(published.root.parent)
    assert _files(store) == before


def _context_candidate(entry, spec):
    from harness.re_v2.protocol_28.artifacts import ExhaustiveEvidenceSliceV1, ExhaustiveObservationV1
    observation = ExhaustiveObservationV1(1, 'applicable', entry.category_id, entry.primary_subject_ids,
        entry.primary_snapshot_evidence_ids, (), 'A supported fixture observation.')
    return ExhaustiveEvidenceSliceV1(1, spec.identity, entry.identity, entry.target_kind,
        entry.source_id, entry.target_id, entry.category_id, entry.primary_subject_ids,
        entry.primary_source_record_ids, entry.primary_snapshot_evidence_ids, (), (), (observation,),
        entry.assigned_finding_ids, (), 'A fixture candidate.')


@pytest.mark.integration
@pytest.mark.parametrize('attack', ['no-safe', 'missing-proof', 'forged-safe'])
@pytest.mark.parametrize('role', ['producer', 'verifier'])
def test_private_sizing_inputs_cannot_enter_public_provider_renderer(tmp_path, attack, role):
    import base64
    from harness.re_v2.protocol_28.context import _Protocol28SizingInputs, Protocol28ContextError
    canary = 'ghp_' + 'z' * 36
    preparation, workspace, intent, parent, options, _ = reviewed_preparation_fixture(tmp_path,
        extra_source_files={'src/orders/handler.py': f"TOKEN = '{canary}'\ndef handle(): return 1\n"}, inherited_canary=canary)
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    reviewed = options.reviewed_discoveries
    overrides = (None, None)
    if attack == 'missing-proof':
        reviewed = tuple(replace(bundle, objects={}) for bundle in reviewed)
        overrides = (inputs.safe_snapshot_evidence_catalog, inputs.safe_lower_authority_catalog)
    elif attack == 'forged-safe':
        safe = inputs.safe_snapshot_evidence_catalog
        row = safe.objects[0]
        overrides = (replace(safe, objects=(replace(row, text='x' * len(row.text)), *safe.objects[1:])),
                     inputs.safe_lower_authority_catalog)
    sizing = _Protocol28SizingInputs(inputs.l3_projection_catalog, inputs.snapshot_evidence_catalog,
        inputs.exhaustive_subject_catalog, inputs.exhaustive_policy,
        {row.raw_authority_id: inputs.authority_objects[row.raw_authority_id] for row in inputs.safe_lower_authority_catalog.objects}, reviewed)
    with pytest.raises(Protocol28ContextError, match='public|validated|subtype|sizing'):
        context = Protocol28RunContext(None, sizing, None, None, None, None, None, *overrides)
        for target in inputs.exhaustive_plan.target_plans:
            for entry in target.entries:
                spec = realize_slice(entry, {key: key for key in entry.planned_dependency_root_ids})
                payload = json.loads(build_protocol_28_slice_context(context, target, entry, spec,
                    role=role, candidate=_context_candidate(entry, spec) if role == 'verifier' else None))
                raw = [row for row in payload['snapshot_evidence'] if 'raw_bytes_base64' in row]
                decoded = b''.join(base64.b64decode(row['raw_bytes_base64']) for row in sorted(raw, key=lambda row: row['byte_start']))
                assert canary.encode() not in decoded, 'private sizing leaked decoded source canary'
                assert all(canary.encode() not in base64.b64decode(row['bytes_base64']) for row in payload['lower_authority_objects'])
        pytest.fail('unvalidated sizing input reached public provider rendering')


def _sizing_material(inputs, reviewed):
    from harness.re_v2.protocol_28.context import _Protocol28SizingInputs, _Protocol28SizingContext
    carrier = _Protocol28SizingInputs(inputs.l3_projection_catalog, inputs.snapshot_evidence_catalog,
        inputs.exhaustive_subject_catalog, inputs.exhaustive_policy, inputs.authority_objects, reviewed)
    return _Protocol28SizingContext(carrier, inputs.exhaustive_plan,
        inputs.safe_snapshot_evidence_catalog, inputs.safe_lower_authority_catalog)


@pytest.mark.integration
def test_internal_sizing_and_loaded_public_role_contexts_are_byte_identical(tmp_path, monkeypatch):
    import harness.re_v2.protocol_28.context as context_module
    from harness.re_v2.protocol_28.context import _serialize_protocol_28_slice_context, _Protocol28SizingContext, Protocol28ContextError
    canary = 'ghp_' + 'v' * 36
    preparation, workspace, intent, parent, options, _ = reviewed_preparation_fixture(tmp_path, shared_owner='same-target',
        extra_source_files={'src/orders/handler.py': f"TOKEN = '{canary}'\ndef handle(): return 1\n"}, inherited_canary=canary)
    captured = set()
    def capture_material(context, *args, **kwargs):
        payload = _serialize_protocol_28_slice_context(context, *args, **kwargs)
        if type(context) is _Protocol28SizingContext:
            captured.add(payload)
        return payload
    monkeypatch.setattr(context_module, '_serialize_protocol_28_slice_context', capture_material)
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    preparation_sizing_bytes = frozenset(captured)
    material = _sizing_material(inputs, options.reviewed_discoveries)
    staged = stage_exhaustive_inputs(tmp_path / 'equal-contexts', inputs)
    published = publish_protocol_28_run(staged.root.parent, tmp_path / inputs.manifest.run_id, inputs.manifest)
    loaded = load_protocol_28_inputs(published.root.parent)
    public = Protocol28RunContext(published, loaded, None, None, None, None, None)
    for target in loaded.exhaustive_plan.target_plans:
        for entry in target.entries:
            spec = realize_slice(entry, {key: key for key in entry.planned_dependency_root_ids})
            for role in ('producer', 'verifier'):
                candidate = _context_candidate(entry, spec) if role == 'verifier' else None
                expected = build_protocol_28_slice_context(public, target, entry, spec, role=role, candidate=candidate)
                if role == 'producer':
                    assert expected in preparation_sizing_bytes, 'actual preparation sizing bytes differ from loaded public bytes'
                assert _serialize_protocol_28_slice_context(material, target, entry, spec, role=role, candidate=candidate) == expected
                import base64
                assert canary.encode() not in expected
                assert all(canary.encode() not in base64.b64decode(row['bytes_base64'])
                           for row in json.loads(expected)['lower_authority_objects'])
                with pytest.raises(Protocol28ContextError, match='public|validated|exhaustive'):
                    build_protocol_28_slice_context(material, target, entry, spec, role=role, candidate=candidate)


@pytest.mark.integration
@pytest.mark.parametrize('attack', ['no-safe', 'missing-proof', 'missing-objects', 'forged-proof', 'forged-safe', 'forged-lower'])
def test_internal_reviewed_sizing_requires_complete_authenticated_safe_material(tmp_path, attack):
    from harness.re_v2.protocol_28.context import _Protocol28SizingInputs, _Protocol28SizingContext, Protocol28ContextError
    preparation, workspace, intent, parent, options, _ = reviewed_preparation_fixture(tmp_path)
    inputs = preparation.prepare_protocol_28_request(workspace, intent, parent, options)
    reviewed = options.reviewed_discoveries
    objects = inputs.authority_objects
    safe, lower = inputs.safe_snapshot_evidence_catalog, inputs.safe_lower_authority_catalog
    if attack == 'no-safe':
        safe = lower = None
    elif attack == 'missing-proof':
        reviewed = tuple(replace(bundle, objects={}) for bundle in reviewed)
    elif attack == 'forged-proof':
        bundle = reviewed[0]
        reviewed = (replace(bundle, objects={**bundle.objects, bundle.authority.review_receipt_id: b'{}'}),)
    elif attack == 'missing-objects':
        objects = {}
    elif attack == 'forged-lower':
        import base64
        row = lower.objects[0]
        lower = replace(lower, objects=(replace(row,
            safe_bytes_base64=base64.b64encode(b'x' * len(row.safe_bytes)).decode()), *lower.objects[1:]))
    else:
        row = safe.objects[0]
        safe = replace(safe, objects=(replace(row, text='x' * len(row.text)), *safe.objects[1:]))
    carrier = _Protocol28SizingInputs(inputs.l3_projection_catalog, inputs.snapshot_evidence_catalog,
        inputs.exhaustive_subject_catalog, inputs.exhaustive_policy, objects, reviewed)
    with pytest.raises(Protocol28ContextError, match='safe|reviewed|authenticated'):
        _Protocol28SizingContext(carrier, inputs.exhaustive_plan, safe, lower)
