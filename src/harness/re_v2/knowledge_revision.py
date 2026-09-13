"""Opt-in knowledge revisions on the existing object/event/resource stores.

The final event is the active-pointer replacement. Intent and staged immutable
objects are never active authority. Reads authenticate the full committed chain
and never append events, repair objects, or reopen a live source checkout.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import json
from typing import Literal

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_activation import _Reads, _json, _replay, validate_reviewed_discovery_catalog
from harness.re_v2.knowledge_acquisition import _AcquisitionProtocol
from harness.re_v2.knowledge_accounting import _DispatchProtocol
from harness.re_v2.knowledge_discovery import DiscoveryBoundary
from harness.re_v2.ledger import ReV2LedgerError
from harness.re_v2.protocol_22.partition import WorkspacePartitionCatalogV1
from harness.re_v2.protocol_22.recovery import protocol_22_run_lock
from harness.re_v2.protocol_28.model import (
    KnowledgeValueV1, KnowledgeAccountTransferV1, SimpleKnowledgeWorkflowAuthorizationV1,
    knowledge_resource_store_identity,
)
from harness.re_v2.protocol_28.debt import KnowledgeDebtLineageV1


class KnowledgeRevisionError(ValueError):
    """Sanitized fail-closed revision diagnostic."""


@dataclass(frozen=True, slots=True)
class KnowledgeAccountSealV1(KnowledgeValueV1):
    schema_version: int
    account_id: str
    transfer_id: str
    sealed_prefix_id: str
    sealed_tail_id: str


@dataclass(frozen=True, slots=True)
class KnowledgeWorkflowActivationIntentV1(KnowledgeValueV1):
    schema_version: int
    logical_run_id: str
    run_manifest_id: str
    reviewed_catalog_id: str
    account_id: str
    reconciler_contract_id: str
    reconciliation_schema_id: str
    allow_debt: bool


@dataclass(frozen=True, slots=True)
class KnowledgeRevisionIntentV1(KnowledgeValueV1):
    schema_version: int
    cause_id: str
    inputs_id: str
    ledger_prefix_id: str
    event_prefix_id: str
    resource_prefix_id: str


@dataclass(frozen=True, slots=True)
class KnowledgeSliceWorkV1(KnowledgeValueV1):
    schema_version: int
    revision_id: str
    plan_entry_id: str
    origin_obligation_ids: tuple[str, ...]
    base_output_artifact_key_id: str


@dataclass(frozen=True, slots=True)
class KnowledgeRevisionReceiptV1(KnowledgeValueV1):
    schema_version: int
    logical_run_id: str
    previous_revision_id: str
    revision_id: str
    cause_id: str
    affected_obligation_ids: tuple[str, ...]
    reusable_result_ids: tuple[str, ...]
    invalidated_result_ids: tuple[str, ...]
    compatibility_receipt_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeRevisionCauseV1(KnowledgeValueV1):
    schema_version: int
    logical_run_id: str
    previous_revision_id: str
    reason: Literal['evidence-expansion']
    affected_obligation_ids: tuple[str, ...]
    support_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeExpansionProofV1(KnowledgeValueV1):
    schema_version: int
    logical_run_id: str
    source_id: str
    acquisition_prefix_id: str
    acquisition_revision_id: str
    object_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeRevisionInputsV1(KnowledgeValueV1):
    schema_version: int
    manifest_id: str
    parent_authority_bundle_id: str
    l3_projection_catalog_id: str
    snapshot_evidence_catalog_id: str
    exhaustive_subject_catalog_id: str
    exhaustive_policy_id: str
    executor_catalog_id: str
    exhaustive_plan_id: str
    safe_snapshot_evidence_catalog_id: str
    safe_lower_authority_catalog_id: str
    reviewed_discovery_catalog_id: str
    authority_object_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeObligationLineageV1(KnowledgeValueV1):
    schema_version: int
    obligation_id: str
    origin_obligation_ids: tuple[str, ...]
    source_id: str
    target_kind: Literal['source', 'domain']
    target_id: str
    category: str
    entry_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeResultDependenciesV1(KnowledgeValueV1):
    schema_version: int
    result_id: str
    obligation_ids: tuple[str, ...]
    dependency_result_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeDependencyMapV1(KnowledgeValueV1):
    schema_version: int
    obligations: tuple[KnowledgeObligationLineageV1, ...]
    results: tuple[KnowledgeResultDependenciesV1, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeCounterV1(KnowledgeValueV1):
    schema_version: int
    origin_obligation_id: str
    producer_attempts: int
    verifier_attempts: int
    expansion_rounds: int


@dataclass(frozen=True, slots=True)
class KnowledgeCountersV1(KnowledgeValueV1):
    schema_version: int
    rows: tuple[KnowledgeCounterV1, ...]
    attempts: tuple[KnowledgeAttemptCounterV1, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeAttemptCounterV1(KnowledgeValueV1):
    schema_version: int
    origin_obligation_id: str
    stage: Literal['slice', 'target-reconciliation', 'source-reconciliation']
    producer_attempts: int
    verifier_attempts: int


@dataclass(frozen=True, slots=True)
class KnowledgeRevisionContextV1(KnowledgeValueV1):
    schema_version: int
    revision_id: str
    inputs_id: str
    evidence_outcome_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeResultCompatibilityV1(KnowledgeValueV1):
    schema_version: int
    previous_revision_id: str
    revision_id: str
    result_id: str
    previous_inputs_id: str
    inputs_id: str
    dependency_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeInvalidationReceiptV1(KnowledgeValueV1):
    schema_version: int
    cause_id: str
    dependency_map_id: str
    affected_obligation_ids: tuple[str, ...]
    invalidated_result_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeRevisionManifestV1(KnowledgeValueV1):
    schema_version: int
    logical_run_id: str
    revision_id: str
    previous_manifest_id: str | None
    authorization_id: str
    inputs_id: str
    context_id: str
    plan_id: str
    subject_catalog_id: str
    reviewed_catalog_id: str
    dependency_map_id: str
    counters_id: str
    account_transfer_id: str
    resource_prefix_id: str
    ledger_prefix_id: str
    event_prefix_id: str
    expansion_rounds: int
    revision_receipt_id: str | None
    invalidation_receipt_id: str | None
    reusable_result_ids: tuple[str, ...]
    invalidated_result_ids: tuple[str, ...]
    compatibility_receipt_ids: tuple[str, ...]
    child_ids: tuple[str, ...]

    @classmethod
    def from_json_dict(cls, value):
        if cls is KnowledgeRevisionManifestV1 and isinstance(value, dict) and 'debt_lineage_id' in value:
            return DebtAwareKnowledgeRevisionManifestV1.from_json_dict(value)
        return super(KnowledgeRevisionManifestV1, cls).from_json_dict(value)


@dataclass(frozen=True, slots=True)
class DebtAwareKnowledgeRevisionManifestV1(KnowledgeRevisionManifestV1):
    """Explicit successor contract; historical manifest bytes remain unchanged."""
    debt_lineage_id: str


@dataclass(frozen=True, slots=True)
class KnowledgeActiveRevisionPointerV1(KnowledgeValueV1):
    schema_version: int
    authorization_id: str
    previous_pointer_id: str | None
    revision_manifest_id: str
    revision_id: str


@dataclass(frozen=True, slots=True)
class KnowledgeRevisionView:
    manifest: KnowledgeRevisionManifestV1
    dependencies: KnowledgeDependencyMapV1
    counters: KnowledgeCountersV1
    receipt: KnowledgeRevisionReceiptV1 | None
    pointer: KnowledgeActiveRevisionPointerV1
    authorization: SimpleKnowledgeWorkflowAuthorizationV1
    debt_lineage: KnowledgeDebtLineageV1 | None = None


def _put(objects, value):
    payload = canonical_json_bytes(value.to_json_dict())
    if objects.put_blob(payload) != value.identity:
        raise KnowledgeRevisionError('knowledge-object-identity-mismatch')
    return value.identity


def _read(objects, object_id, cls):
    try:
        reader = _Reads(objects)
        value = cls.from_json_dict(_json(reader, object_id))
        if value.identity != object_id:
            raise ValueError
        return value
    except (ValueError, KeyError, TypeError, OSError, ReV2LedgerError):
        raise KnowledgeRevisionError('invalid-knowledge-revision-authority') from None


def _rows(objects, object_id):
    try:
        return _json(_Reads(objects), object_id)
    except (ValueError, KeyError, TypeError, OSError, ReV2LedgerError):
        raise KnowledgeRevisionError('invalid-knowledge-revision-authority') from None


def _sorted(rows):
    return tuple(sorted(rows, key=lambda row: row.identity))


def _input_bundle(inputs):
    from harness.re_v2.protocol_28.inputs import ReviewedProtocol28CreationInputs, ValidatedReviewedProtocol28Inputs
    if type(inputs) not in {ReviewedProtocol28CreationInputs, ValidatedReviewedProtocol28Inputs}:
        raise KnowledgeRevisionError('explicit-reviewed-inputs-required')
    creation = ReviewedProtocol28CreationInputs(**{f.name: getattr(inputs, f.name) for f in fields(ReviewedProtocol28CreationInputs)})
    return _encode_input_bundle(creation)


def _encode_input_bundle(creation):
    """Encode after public creation validation; do not repeat that same replay."""
    from harness.re_v2.protocol_28.inputs import _canonical_authorities
    names = tuple(f.name.removesuffix('_id') for f in fields(KnowledgeRevisionInputsV1)
                  if f.name not in {'schema_version', 'authority_object_ids'})
    envelope = KnowledgeRevisionInputsV1(1, **{f'{name}_id': getattr(creation, name).identity for name in names},
        authority_object_ids=tuple(sorted(creation.authority_objects)))
    children = {key: canonical_json_bytes(value.to_json_dict()) for key, value in _canonical_authorities(creation)}
    children.update(creation.authority_objects)
    children[creation.manifest.identity] = canonical_json_bytes(creation.manifest.to_json_dict())
    children[envelope.identity] = canonical_json_bytes(envelope.to_json_dict())
    return envelope, children


def load_revision_inputs(objects, object_id):
    """Decode through the same public Reviewed creation validator, without files."""
    from harness.re_v2.protocol_28 import inputs as types
    if isinstance(objects, _RevisionReads) and object_id in objects.input_bundles:
        return objects.input_bundles[object_id][0]
    envelope = _read(objects, object_id, KnowledgeRevisionInputsV1)
    classes = {
        'manifest': types.ReviewedExhaustiveRunManifestV7,
        'parent_authority_bundle': types.ReviewedParentAuthorityBundleV3,
        'l3_projection_catalog': types.L3TargetProjectionCatalogV1,
        'snapshot_evidence_catalog': types.SnapshotEvidenceCatalogV1,
        'exhaustive_subject_catalog': types.ExhaustiveSubjectCatalogV1,
        'exhaustive_policy': types.ExhaustivePolicyV1,
        'executor_catalog': types.L4ExecutorCatalogV1,
        'exhaustive_plan': types.ExhaustivePlanV1,
        'safe_snapshot_evidence_catalog': types.SafeSnapshotEvidenceCatalogV1,
        'safe_lower_authority_catalog': types.SafeLowerAuthorityCatalogV1,
        'reviewed_discovery_catalog': types.ReviewedDiscoveryCatalogV1,
    }
    result = types.ReviewedProtocol28CreationInputs(**{
        name: _read(objects, getattr(envelope, f'{name}_id'), cls) for name, cls in classes.items()},
        authority_objects={key: _Reads(objects).read_blob(key) for key in envelope.authority_object_ids})
    expected, children = _encode_input_bundle(result)
    if expected != envelope:
        raise KnowledgeRevisionError('revision-input-closure-mismatch')
    for key, value in children.items():
        if _Reads(objects).read_blob(key) != value:
            raise KnowledgeRevisionError('revision-input-closure-mismatch')
    if isinstance(objects, _RevisionReads):
        objects.input_bundles[object_id] = (result, expected, children)
    return result


def _bundles(inputs, objects=None):
    # Inputs are frozen, their authority map is immutable, and this reader lives
    # for one verification only. Retain the input itself, not just its id, so no
    # later object can inherit a memo entry through Python id reuse.
    cache = objects.discovery_bundles if isinstance(objects, _RevisionReads) else {}
    key = id(inputs)
    if key not in cache:
        cache[key] = (inputs, validate_reviewed_discovery_catalog(inputs.reviewed_discovery_catalog, inputs.authority_objects,
            inputs.l3_projection_catalog, inputs.snapshot_evidence_catalog, inputs.exhaustive_subject_catalog))
    return cache[key][1]


def _obligations(inputs, previous=None, objects=None):
    previous_by_key = {} if previous is None else {
        (row.source_id, row.target_kind, row.target_id, row.category): row for row in previous.obligations}
    rows = []
    for bundle in _bundles(inputs, objects):
        for row in bundle.category_assessments:
            targets = [t for t in inputs.exhaustive_plan.target_plans if (t.source_id, t.target_kind, t.target_id)
                       == (row.source_id, row.target_kind, row.target_id)]
            if not targets:  # Explicit no-domain inventory disposition, no selected domain work.
                continue
            key = row.source_id, row.target_kind, row.target_id, row.category_id
            origin = previous_by_key.get(key)
            rows.append(KnowledgeObligationLineageV1(1, row.obligation_id,
                origin.origin_obligation_ids if origin else (row.obligation_id,), *key,
                tuple(sorted(e.identity for t in targets for e in t.entries if e.category_id == row.category_id)), row.raw_evidence_ids))
    if previous is not None and {i for row in rows for i in row.origin_obligation_ids} != {
            i for row in previous.obligations for i in row.origin_obligation_ids}:
        raise KnowledgeRevisionError('revision-cannot-drop-or-rename-origin-obligations')
    return _sorted(rows)


def _account_transfer(context, account):
    history, state = account.ledger.replay_with_history()
    _validate_reviewed_account(context.inputs, content_digest(account.opening),
        [r.to_json_dict() for r in history if r.type != 'account_transferred'])
    if state.transfer_id is not None:
        transfer = _read(account.objects, state.transfer_id, KnowledgeAccountTransferV1)
        if transfer.run_manifest_id != context.inputs.manifest.identity:
            raise KnowledgeRevisionError('knowledge-account-transfer-rebound')
        return transfer
    if context.resources.records:
        raise KnowledgeRevisionError('knowledge-account-transfer-requires-new-resource-history')
    reader = _Reads(account.objects)
    replayed = _replay([r.to_json_dict() for r in history], _DispatchProtocol(account.opening), reader)
    usage = replayed.usage()
    if (set(replayed.dispatches) != set(replayed.captures) or usage.open_tokens or usage.open_active_ms
            or usage.reservation_breached or any(d not in replayed.applied for d in replayed.dispatches)):
        raise KnowledgeRevisionError('knowledge-account-transfer-requires-settled-work')
    authority = account.opening['run_authority']
    if (authority['snapshot_id'] != context.inputs.manifest.source_snapshot_id
            or authority['partition_id'] != context.inputs.manifest.workspace_partition_catalog_id
            or set(authority['source_ids']) != {b.authority.source_id for b in _bundles(context.inputs)}):
        raise KnowledgeRevisionError('knowledge-account-transfer-scope-mismatch')
    account_id = content_digest(account.opening)
    reader.read_blob(account_id)
    rows = canonical_json_bytes([r.to_json_dict() for r in history])
    prefix_id = account.objects.put_blob(rows)
    transfer = KnowledgeAccountTransferV1(1, account.opening['logical_run_id'], context.inputs.manifest.identity,
        knowledge_resource_store_identity(context.inputs.manifest.identity),
        context.inputs.reviewed_discovery_catalog.identity, account_id, prefix_id, history[-1].record_hash,
        tuple(sorted(reader.reads)), tuple(sorted(replayed.dispatches)), usage.charged_tokens, usage.charged_active_ms,
        account.opening['policy']['token_limit'], account.opening['policy']['active_ms_limit'])
    account._record('account_transferred', transfer.to_json_dict())
    return transfer


def _validate_reviewed_account(inputs, account_id, account_rows, objects=None):
    """The reviewed captures and transferred baseline must be the same account."""
    from harness.re_v2.knowledge_activation import ReviewedSubjectCatalogV1
    reader = _Reads(inputs.authority_objects)
    for bundle in _bundles(inputs, objects):
        catalogue = _read(reader, bundle.authority.subject_catalog_id, ReviewedSubjectCatalogV1)
        proof = _rows(reader, catalogue.replay_proof_id)
        rows = proof['account']
        if (not rows or rows[0]['payload']['receipt_id'] != account_id
                or canonical_json_bytes(account_rows[:len(rows)]) != canonical_json_bytes(rows)):
            raise KnowledgeRevisionError('reviewed-account-transfer-rebound')


def _validate_transfer(objects, transfer, resources, seal):
    reader = _Reads(objects)
    opening = _rows(reader, transfer.account_id)
    rows = _rows(reader, transfer.account_prefix_id)
    before = _Reads(objects)
    state = _replay(rows, _DispatchProtocol(opening), before)
    before.read_blob(transfer.account_id)
    usage = state.usage()
    expected = KnowledgeAccountTransferV1(1, opening['logical_run_id'], transfer.run_manifest_id,
        knowledge_resource_store_identity(transfer.run_manifest_id),
        transfer.reviewed_catalog_id, content_digest(opening), content_digest(rows), rows[-1]['record_hash'],
        tuple(sorted(before.reads)), tuple(sorted(state.dispatches)), usage.charged_tokens, usage.charged_active_ms,
        opening['policy']['token_limit'], opening['policy']['active_ms_limit'])
    if (expected != transfer or set(state.dispatches) != set(state.captures)
            or set(state.dispatches) != set(state.applied) or usage.open_tokens or usage.open_active_ms
            or usage.reservation_breached or not resources.records or resources.records[0] != transfer):
        raise KnowledgeRevisionError('knowledge-account-transfer-closure-mismatch')
    sealed_rows = _rows(objects, seal.sealed_prefix_id)
    if (seal.account_id != transfer.account_id or seal.transfer_id != transfer.identity
            or len(sealed_rows) != len(rows) + 1 or sealed_rows[:-1] != rows
            or sealed_rows[-1]['record_hash'] != seal.sealed_tail_id
            or _replay(sealed_rows, _DispatchProtocol(opening), _Reads(objects)).transfer_id != transfer.identity):
        raise KnowledgeRevisionError('knowledge-account-seal-mismatch')
    return state


def activate_knowledge_workflow(context, account, *, allow_debt: bool, fault_hook=None):
    """Opt in once before L4 work; seal and transfer the one existing account."""
    if type(allow_debt) is not bool:
        raise KnowledgeRevisionError('invalid-knowledge-workflow-authorization')
    _validate_reviewed_account(context.inputs, content_digest(account.opening),
        [r.to_json_dict() for r in account.ledger.replay_with_history()[0] if r.type != 'account_transferred'])
    with protocol_22_run_lock(context.paths), protocol_22_run_lock(account.paths):
        existing = load_knowledge_revision(context)
        if existing is not None:
            if (existing.authorization.allow_debt != allow_debt
                    or existing.manifest.logical_run_id != account.opening['logical_run_id']):
                raise KnowledgeRevisionError('knowledge-workflow-authorization-conflict')
            return existing
        _input_bundle(context.inputs)
        intents = [e for e in context.events.replay() if e.type == 'knowledge_workflow_requested']
        if intents:
            intent = _read(context.objects, intents[0].payload['intent_id'], KnowledgeWorkflowActivationIntentV1)
            if (intent.logical_run_id != account.opening['logical_run_id']
                    or intent.run_manifest_id != context.inputs.manifest.identity
                    or intent.reviewed_catalog_id != context.inputs.reviewed_discovery_catalog.identity
                    or intent.account_id != content_digest(account.opening) or intent.allow_debt != allow_debt):
                raise KnowledgeRevisionError('knowledge-activation-intent-conflict')
            context.objects.read_blob(intent.reconciler_contract_id)
            context.objects.read_blob(intent.reconciliation_schema_id)
        else:
            # Freeze role/schema before moving accounting ownership; a partial
            # activation cannot resume as historical work or rebind its contract.
            from pathlib import Path
            import yaml
            from harness.prosaic_prompt_loader import ProsaicCommandArtifact
            from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
            from harness.re_v2.protocol_28.reconciliation import reconciliation_response_schema
            root = Path(__file__).resolve().parents[3]
            agent = root / 'prosaic/subagents/echelon.re-knowledge-reconciler.md'
            phase = root / 'runtime/workflow/phases/re-knowledge-reconciliation.md'
            _, metadata, body = agent.read_text().split('---', 2)
            agent_bytes = canonical_prosaic_agent_bytes(ProsaicCommandArtifact(yaml.safe_load(metadata),
                body.strip() + '\n\n' + phase.read_text()))
            schema_bytes = canonical_json_bytes(reconciliation_response_schema())
            intent = KnowledgeWorkflowActivationIntentV1(1, account.opening['logical_run_id'],
                context.inputs.manifest.identity, context.inputs.reviewed_discovery_catalog.identity,
                content_digest(account.opening), context.objects.put_blob(agent_bytes),
                context.objects.put_blob(schema_bytes), allow_debt)
            _put(context.objects, intent)
            context.controller.append_once('knowledge_workflow_requested', {'intent_id': intent.identity})
        if fault_hook:
            fault_hook('after_activation_intent')
        transfer = _account_transfer(context, account)
        for key in (*transfer.account_object_ids, transfer.account_prefix_id, transfer.identity):
            context.objects.put_blob(account.objects.read_blob(key))
        sealed_rows = [r.to_json_dict() for r in account.ledger.replay_with_history()[0]]
        seal = KnowledgeAccountSealV1(1, transfer.account_id, transfer.identity,
            context.objects.put_blob(canonical_json_bytes(sealed_rows)), sealed_rows[-1]['record_hash'])
        _put(context.objects, seal)
        if fault_hook:
            fault_hook('after_account_sealed')
        context.resources.import_knowledge_account(transfer)
        if fault_hook:
            fault_hook('after_account_imported')
        authorization = SimpleKnowledgeWorkflowAuthorizationV1(1, transfer.logical_run_id, transfer.run_manifest_id,
            context.inputs.manifest.source_snapshot_id, transfer.reviewed_catalog_id, transfer.identity, seal.identity,
            intent.identity, intent.reconciler_contract_id, intent.reconciliation_schema_id, allow_debt)
        _put(context.objects, authorization)
        return _commit(context, context.inputs, authorization, transfer, None, None, fault_hook)


def _acquisition_replay(context, proof, reader):
    inputs = context.inputs
    rows = _rows(reader, proof.acquisition_prefix_id)
    opening = _rows(reader, rows[0]['payload']['receipt_id'])
    if (opening['logical_run_id'] != proof.logical_run_id or opening['evidence_scope']['source_id'] != proof.source_id
            or opening['evidence_scope']['snapshot_id'] != inputs.manifest.source_snapshot_id):
        raise KnowledgeRevisionError('revision-evidence-cause-scope-mismatch')
    partition = _read(reader, inputs.manifest.workspace_partition_catalog_id, WorkspacePartitionCatalogV1)
    scope = opening['evidence_scope']
    boundary = DiscoveryBoundary.from_catalog(inputs.snapshot_evidence_catalog, partition, inputs.manifest.selection,
        proof.source_id, scope['depth'], scope['origin_obligation_id'], reader)
    state = _replay(rows, _AcquisitionProtocol(opening, boundary), reader)
    if state.progress.pending_id is not None or state.progress.revision_id != proof.acquisition_revision_id:
        raise KnowledgeRevisionError('revision-evidence-cause-not-committed')
    return state


def stage_knowledge_expansion(context, acquisition, batch_id, affected_obligation_ids):
    """Resolve via the existing two-round acquisition ledger, without a provider."""
    with protocol_22_run_lock(context.paths):
        active = load_knowledge_revision(context)
        if active is None or acquisition.opening['logical_run_id'] != active.manifest.logical_run_id:
            raise KnowledgeRevisionError('revision-evidence-cause-account-mismatch')
        selected = tuple(row for row in active.dependencies.obligations if row.obligation_id in affected_obligation_ids)
        if (not selected or {row.obligation_id for row in selected} != set(affected_obligation_ids)
                or {row.source_id for row in selected} != {acquisition.opening['evidence_scope']['source_id']}):
            raise KnowledgeRevisionError('revision-evidence-cause-obligation-mismatch')
        acquisition.resolve(acquisition.status().binding_id, batch_id)
        history, state = acquisition.ledger.replay_with_history()
        prefix = canonical_json_bytes([r.to_json_dict() for r in history])
        prefix_id = content_digest(prefix)
        class ReadSource:
            def read_blob(self, key):
                if key == prefix_id:
                    return prefix
                if key in context.inputs.authority_objects:
                    return context.inputs.authority_objects[key]
                return acquisition.objects.read_blob(key)
        reader = _Reads(ReadSource())
        provisional = KnowledgeExpansionProofV1(1, active.manifest.logical_run_id,
            acquisition.opening['evidence_scope']['source_id'], prefix_id, state.progress.revision_id, ())
        _acquisition_replay(context, provisional, reader)
        proof = KnowledgeExpansionProofV1(1, provisional.logical_run_id, provisional.source_id, prefix_id,
            provisional.acquisition_revision_id, tuple(sorted(reader.reads)))
        cause = KnowledgeRevisionCauseV1(1, active.manifest.logical_run_id, active.manifest.revision_id,
            'evidence-expansion', tuple(sorted(affected_obligation_ids)), (proof.identity,))
        for key, payload in reader.reads.items():
            context.objects.put_blob(payload)
        _put(context.objects, proof)
        _put(context.objects, cause)
        return cause


def _cause_progress(context, cause, previous):
    if (type(cause) is not KnowledgeRevisionCauseV1 or cause.logical_run_id != previous.manifest.logical_run_id
            or cause.previous_revision_id != previous.manifest.revision_id or len(cause.support_ids) != 1
            or not cause.affected_obligation_ids or not set(cause.affected_obligation_ids).issubset(
                row.obligation_id for row in previous.dependencies.obligations)):
        raise KnowledgeRevisionError('invalid-revision-evidence-cause')
    proof = _read(context.objects, cause.support_ids[0], KnowledgeExpansionProofV1)
    reader = _Reads(context.objects)
    state = _acquisition_replay(context, proof, reader)
    source_origins = {i for row in previous.dependencies.obligations if row.source_id == proof.source_id for i in row.origin_obligation_ids}
    prior_round = max((r.expansion_rounds for r in previous.counters.rows if r.origin_obligation_id in source_origins), default=0)
    if (tuple(sorted(reader.reads)) != proof.object_ids or proof.logical_run_id != cause.logical_run_id
            or any(row.source_id != proof.source_id for row in previous.dependencies.obligations
                   if row.obligation_id in cause.affected_obligation_ids)
            or state.progress.rounds <= prior_round or state.progress.rounds > 2):
        raise KnowledgeRevisionError('invalid-or-exhausted-revision-expansion-round')
    previous_context = _read(context.objects, previous.manifest.context_id, KnowledgeRevisionContextV1)
    return state.progress.rounds, tuple(sorted(set(state.outcome_ids) | set(previous_context.evidence_outcome_ids)))


def commit_knowledge_revision(context, inputs, cause, *, compatibility_result_ids=(), fault_hook=None):
    """Validate every child first, append intent, stage children, switch pointer last."""
    with protocol_22_run_lock(context.paths):
        from harness.re_v2.protocol_28.context import load_protocol_28_run_context
        context = load_protocol_28_run_context(context.run_dir)
        previous = load_knowledge_revision(context)
        if previous is None:
            raise KnowledgeRevisionError('explicit-knowledge-workflow-required')
        if previous.receipt is not None and previous.receipt.cause_id == cause.identity:
            if previous.manifest.inputs_id != _input_bundle(inputs)[0].identity:
                raise KnowledgeRevisionError('revision-retry-inputs-conflict')
            return previous
        _cause_progress(context, cause, previous)
        transfer = _read(context.objects, previous.manifest.account_transfer_id, KnowledgeAccountTransferV1)
        return _commit(context, inputs, previous.authorization, transfer, previous, cause, fault_hook,
                       compatibility_result_ids=tuple(compatibility_result_ids))


def _dependencies(context, inputs, previous, ledger_rows, event_rows):
    from harness.re_v2.protocol_28.events import replay_protocol_28
    from harness.re_v2.events import EventRecord
    obligations = _obligations(inputs, previous.dependencies if previous else None, context.objects)
    ledger = _revision_ledger_view(context.objects, ledger_rows)
    state = replay_protocol_28(tuple(EventRecord(**row) for row in event_rows))
    rows = []
    for accepted in ledger.accepted_slices.values():
        if accepted.identity not in state.accepted_slices.values():
            continue
        relevant = tuple(sorted(row.obligation_id for row in obligations if accepted.plan_entry_id in row.entry_ids))
        if not relevant and previous:
            relevant = tuple(sorted(row.obligation_id for row in previous.dependencies.obligations if accepted.plan_entry_id in row.entry_ids))
        if not relevant:
            raise KnowledgeRevisionError('result-has-no-obligation-lineage')
        from harness.re_v2.protocol_28.planning import SliceSpecV1
        spec = _read(context.objects, accepted.slice_spec_id, SliceSpecV1)
        rows.append(KnowledgeResultDependenciesV1(1, accepted.identity, relevant, spec.accepted_dependency_artifact_ids))
    for result_id, (kind, accepted_ids, root_ids) in state.root_requirements.items():
        lower = set(accepted_ids) | set(root_ids)
        obligation_ids = set()
        for item in rows:
            if item.result_id in lower:
                obligation_ids.update(item.obligation_ids)
        rows.append(KnowledgeResultDependenciesV1(1, result_id, tuple(sorted(obligation_ids)), tuple(sorted(lower))))
    return KnowledgeDependencyMapV1(1, obligations, _sorted(rows))


def _counters(context, inputs, dependencies, previous, resource_rows, ledger_rows, rounds, affected=()):
    from harness.re_v2.protocol_28.budget import PairedReservationCommitV1, VerifierRetryReservationV1, _decode_resource_record
    from harness.re_v2.protocol_28.planning import SliceSpecV1
    view = _revision_ledger_view(context.objects, ledger_rows)
    prior = {} if previous is None else {(r.origin_obligation_id, r.stage): r for r in previous.counters.attempts}
    origins = {i for r in dependencies.obligations for i in r.origin_obligation_ids}
    by_entry = {key: row.origin_obligation_ids for row in dependencies.obligations for key in row.entry_ids}
    if previous:
        by_entry.update({key: row.origin_obligation_ids for row in previous.dependencies.obligations for key in row.entry_ids})
    producers = {key: r.producer_attempts for key, r in prior.items()}
    verifiers = {key: r.verifier_attempts for key, r in prior.items()}
    seen_verifiers = {}
    for raw in resource_rows:
        record = _decode_resource_record(raw)
        if not isinstance(record, (PairedReservationCommitV1, VerifierRetryReservationV1)):
            continue
        work = view.knowledge_work.get(record.slice_spec_id)
        if work:
            work_origins = {o for row in dependencies.obligations if row.obligation_id in work.obligation_ids for o in row.origin_obligation_ids}
            stage = work.scope + '-reconciliation'
        else:
            spec = _read(context.objects, record.slice_spec_id, SliceSpecV1)
            work_origins = by_entry.get(spec.plan_entry_id)
            stage = 'slice'
        if not work_origins:
            raise KnowledgeRevisionError('reservation-has-no-stable-obligation-lineage')
        for origin in work_origins:
            key = origin, stage
            producers[key] = max(producers.get(key, 0), record.producer_attempt_number)
            seen_verifiers.setdefault(key, set()).add(record.verifier_dispatch_id if isinstance(record, PairedReservationCommitV1) else record.dispatch_id)
    attempts = _sorted(KnowledgeAttemptCounterV1(1, origin, stage, producers.get((origin, stage), 0),
        max(verifiers.get((origin, stage), 0), len(seen_verifiers.get((origin, stage), ()))))
        for origin in origins for stage in ('slice', 'target-reconciliation', 'source-reconciliation'))
    old = {} if previous is None else {r.origin_obligation_id: r for r in previous.counters.rows}
    # The run's maximum is reporting metadata, never another source's allowance.
    # Recompute each initial origin from its authenticated Task 3 acquisition root.
    source_rounds = {} if previous else {bundle.authority.source_id:
        _rows(bundle.objects, bundle.authority.active_revision_id).get('round', 0)
        for bundle in _bundles(inputs, context.objects)}
    initial_rounds = {origin: source_rounds.get(row.source_id, 0)
        for row in dependencies.obligations for origin in row.origin_obligation_ids}
    affected_sources = {row.source_id for row in dependencies.obligations if row.obligation_id in affected}
    affected_origins = {o for row in dependencies.obligations if row.source_id in affected_sources for o in row.origin_obligation_ids}
    rows = _sorted(KnowledgeCounterV1(1, origin,
        max(r.producer_attempts for r in attempts if r.origin_obligation_id == origin),
        max(r.verifier_attempts for r in attempts if r.origin_obligation_id == origin),
        max(old[origin].expansion_rounds if origin in old else initial_rounds[origin],
            rounds if previous and origin in affected_origins else 0)) for origin in origins)
    return KnowledgeCountersV1(1, rows, attempts)


def inherited_attempts(active, obligation_ids, stage):
    origins = {o for row in active.dependencies.obligations if row.obligation_id in obligation_ids for o in row.origin_obligation_ids}
    return max((r.producer_attempts for r in active.counters.attempts
        if r.origin_obligation_id in origins and r.stage == stage), default=0)


def realize_knowledge_slice(context, active, entry, dependencies):
    """Revision-specific output, with exact compatible results keeping their identity."""
    from dataclasses import replace
    from harness.re_v2.protocol_28.planning import realize_slice, SliceSpecV1
    from harness.re_v2.protocol_28.events import replay_protocol_28
    base = realize_slice(entry, dependencies)
    state = replay_protocol_28(context.events.replay())
    for accepted in context.ledger.replay().accepted_slices.values():
        if accepted.plan_entry_id == entry.identity and accepted.identity in state.accepted_slices.values():
            return _read(context.objects, accepted.slice_spec_id, SliceSpecV1)
    work = KnowledgeSliceWorkV1(1, active.manifest.revision_id, entry.identity,
        tuple(sorted({o for row in active.dependencies.obligations if entry.identity in row.entry_ids for o in row.origin_obligation_ids})),
        base.output_artifact_key_id)
    _put(context.objects, work)
    spec = replace(base, output_artifact_key_id=work.identity)
    _put(context.objects, spec)
    return spec


def _commit(context, inputs, authorization, transfer, previous, cause, fault_hook, *, compatibility_result_ids=()):
    envelope, children = _input_bundle(inputs)
    _validate_reviewed_account(inputs, transfer.account_id, _rows(context.objects, transfer.account_prefix_id))
    if previous:
        _preserve_inherited_debt(context.inputs, inputs)
    if (inputs.manifest.source_snapshot_id != authorization.snapshot_id
            or inputs.manifest.budget_policy != context.inputs.manifest.budget_policy
            or inputs.manifest.executor_catalog_id != context.inputs.manifest.executor_catalog_id
            or inputs.manifest.selection != context.inputs.manifest.selection
            or inputs.manifest.run_id != context.inputs.manifest.run_id):
        raise KnowledgeRevisionError('revision-cannot-change-snapshot-account-or-executor')
    def add(value):
        children[value.identity] = canonical_json_bytes(value.to_json_dict())
        return value.identity
    # Freeze prefixes before intent, and keep them immutable across partial retries.
    intents = [e for e in context.events.replay() if e.type == 'knowledge_revision_requested'
               and cause is not None and e.payload['cause_id'] == cause.identity]
    if intents:
        intent = _read(context.objects, intents[0].payload['intent_id'], KnowledgeRevisionIntentV1).to_json_dict()
        if intent['cause_id'] != cause.identity or intent['inputs_id'] != envelope.identity:
            raise KnowledgeRevisionError('revision-retry-intent-conflict')
        ledger_rows = _rows(context.objects, intent['ledger_prefix_id'])
        event_rows = _rows(context.objects, intent['event_prefix_id'])
        resource_rows = _rows(context.objects, intent['resource_prefix_id'])
    else:
        ledger_rows = [r.to_json_dict() for r in context.ledger.replay_with_history()[0]]
        event_rows = [r.to_json_dict() for r in context.events.replay()]
        resource_rows = [r.to_json_dict() for r in context.resources.records]
    _assert_transaction_prefixes(context, ledger_rows, event_rows, resource_rows,
        intents[0].payload if intents else None)
    for rows in (ledger_rows, event_rows, resource_rows):
        children[content_digest(rows)] = canonical_json_bytes(rows)
    dependencies = _dependencies(context, inputs, previous, ledger_rows, event_rows)
    add(dependencies)
    rounds, outcomes = _cause_progress(context, cause, previous) if cause else (
        max((_rows(context.objects, b.authority.active_revision_id).get('round', 0) for b in _bundles(inputs)), default=0), ())
    counters = _counters(context, inputs, dependencies, previous, resource_rows, ledger_rows, rounds,
        cause.affected_obligation_ids if cause else ())
    add(counters)
    revision_id = content_digest({'authorization_id': authorization.identity, 'previous_revision_id':
        previous.manifest.revision_id if previous else None, 'cause_id': cause.identity if cause else None, 'inputs_id': envelope.identity})
    revision_context = KnowledgeRevisionContextV1(1, revision_id, envelope.identity, outcomes)
    add(revision_context)
    from harness.re_v2.protocol_28.debt import derive_knowledge_debt_lineage
    debt_lineage = derive_knowledge_debt_lineage(context.objects, revision_id, dependencies,
        _revision_ledger_view(context.objects, ledger_rows))
    add(debt_lineage)
    invalidated = set()
    compatibility = []
    invalidation = receipt = None
    if cause:
        add(cause)
        affected = set(cause.affected_obligation_ids)
        for row in dependencies.results:
            if affected.intersection(row.obligation_ids):
                invalidated.add(row.result_id)
        while True:
            expanded = invalidated | {r.result_id for r in dependencies.results if invalidated.intersection(r.dependency_result_ids)}
            if expanded == invalidated:
                break
            invalidated = expanded
        available = {r.result_id for r in dependencies.results} - invalidated
        requested = set(compatibility_result_ids)
        if len(requested) != len(compatibility_result_ids) or not requested.issubset(available):
            raise KnowledgeRevisionError('invalid-result-compatibility-selection')
        # Conservatively require byte-identical plan/subject/safe policy authority
        # for sibling reuse; mere names or object presence cannot prove independence.
        if requested and (inputs.exhaustive_plan != context.inputs.exhaustive_plan
                or inputs.exhaustive_subject_catalog != context.inputs.exhaustive_subject_catalog
                or inputs.safe_snapshot_evidence_catalog != context.inputs.safe_snapshot_evidence_catalog):
            raise KnowledgeRevisionError('unproven-result-compatibility')
        for key in sorted(requested):
            row = next(row for row in dependencies.results if row.result_id == key)
            if not set(row.dependency_result_ids).issubset(requested):
                raise KnowledgeRevisionError('unproven-transitive-result-compatibility')
            compatibility.append(KnowledgeResultCompatibilityV1(1, previous.manifest.revision_id, revision_id, key,
                previous.manifest.inputs_id, envelope.identity, tuple(sorted((*row.obligation_ids, *row.dependency_result_ids)))))
        invalidated.update(available - requested)
        for row in compatibility:
            add(row)
        invalidation = KnowledgeInvalidationReceiptV1(1, cause.identity, dependencies.identity,
            cause.affected_obligation_ids, tuple(sorted(invalidated)))
        add(invalidation)
        receipt = KnowledgeRevisionReceiptV1(1, authorization.logical_run_id, previous.manifest.revision_id,
            revision_id, cause.identity, cause.affected_obligation_ids, tuple(sorted(requested)), tuple(sorted(invalidated)),
            tuple(sorted(r.identity for r in compatibility)))
        add(receipt)
    manifest = DebtAwareKnowledgeRevisionManifestV1(1, authorization.logical_run_id, revision_id,
        previous.manifest.identity if previous else None, authorization.identity, envelope.identity, revision_context.identity,
        inputs.exhaustive_plan.identity, inputs.exhaustive_subject_catalog.identity, inputs.reviewed_discovery_catalog.identity,
        dependencies.identity, counters.identity, transfer.identity, content_digest(resource_rows), content_digest(ledger_rows),
        content_digest(event_rows), max(rounds, previous.manifest.expansion_rounds if previous else 0), receipt.identity if receipt else None, invalidation.identity if invalidation else None,
        receipt.reusable_result_ids if receipt else (), tuple(sorted(invalidated)), tuple(sorted(r.identity for r in compatibility)),
        tuple(sorted(children)), debt_lineage.identity)
    pointer = KnowledgeActiveRevisionPointerV1(1, authorization.identity, previous.pointer.identity if previous else None,
        manifest.identity, revision_id)
    activation_payload = {'authorization_id': authorization.identity, 'pointer_id': pointer.identity,
               'revision_id': revision_id, 'planned_entry_ids': sorted(e.identity for t in inputs.exhaustive_plan.target_plans for e in t.entries),
               'invalidated_result_ids': list(manifest.invalidated_result_ids)}
    activation_type = 'knowledge_revision_activated' if previous else 'knowledge_workflow_activated'
    intent = KnowledgeRevisionIntentV1(1, cause.identity, envelope.identity, manifest.ledger_prefix_id,
        manifest.event_prefix_id, manifest.resource_prefix_id) if cause else None
    intent_payload = {'cause_id': cause.identity, 'intent_id': intent.identity} if cause else None
    # Prove the eventual reader's complete closure before any intent/child write.
    prospective = dict(children)
    for value in (manifest, pointer, intent):
        if value is not None:
            prospective[value.identity] = canonical_json_bytes(value.to_json_dict())
    class ProspectiveReads:
        def read_blob(self, key):
            return prospective[key] if key in prospective else context.objects.read_blob(key)
    events = context.events.replay()
    if cause and not intents:
        events = _prospective_event(events, 'knowledge_revision_requested', intent_payload)
    verify_knowledge_revision_chain(ProspectiveReads(), _prospective_event(events, activation_type, activation_payload),
        [r.to_json_dict() for r in context.ledger._read_records()], context.resources.records)
    def fault(name):
        if fault_hook:
            fault_hook(name)
    # Existing staged objects must be intact, not silently repaired.
    for key, payload in children.items():
        suffix = key.split(':')[1]
        path = context.objects.root / 'sha256' / suffix[:2] / suffix[2:]
        if (path.exists() or path.is_symlink()) and context.objects.read_blob(key) != payload:
            raise KnowledgeRevisionError('staged-knowledge-child-conflict')
    if cause:
        for rows in (ledger_rows, event_rows, resource_rows):
            context.objects.put_blob(canonical_json_bytes(rows))
        _put(context.objects, cause)
        intent_id = _put(context.objects, intent)
        context.controller.append_once('knowledge_revision_requested', intent_payload)
        fault('after_request_intent')
    late = {dependencies.identity, revision_context.identity, counters.identity,
            *(r.identity for r in compatibility), *(r.identity for r in (invalidation, receipt) if r is not None)}
    for key, payload in sorted(children.items()):
        if key not in late:
            context.objects.put_blob(payload)
            fault('after_staged_child')
    fault('after_inputs')
    for row, seam in ((dependencies, 'after_dependency_map'), (revision_context, 'after_context'), (counters, 'after_counters')):
        _put(context.objects, row)
        fault(seam)
    for row in compatibility:
        _put(context.objects, row)
        fault('after_compatibility_receipt')
    if invalidation:
        _put(context.objects, invalidation)
        fault('after_invalidation_receipt')
        _put(context.objects, receipt)
        fault('after_revision_receipt')
    _put(context.objects, manifest)
    fault('after_revision_manifest')
    _assert_transaction_prefixes(context, ledger_rows, event_rows, resource_rows, intent_payload)
    _put(context.objects, pointer)
    context.controller.append_once(activation_type, activation_payload)
    fault('after_active_pointer')
    return KnowledgeRevisionView(manifest, dependencies, counters, receipt, pointer, authorization, debt_lineage)


def _prospective_event(events, event_type, payload):
    """Construct and validate a hypothetical transition without publishing it."""
    from harness.re_v2.events import EventRecord, _thaw_json
    from harness.re_v2.protocol_28.events import PROTOCOL_28_EVENTS, replay_protocol_28
    value = dict(schema_version=1, seq=len(events) + 1, type=event_type,
        previous_event_hash=events[-1].event_hash if events else None,
        occurred_at=events[-1].occurred_at, payload=_thaw_json(PROTOCOL_28_EVENTS.canonical_payload(event_type, payload)))
    result = (*events, EventRecord(**value, event_hash=content_digest(value)))
    replay_protocol_28(result)
    return result


def _assert_transaction_prefixes(context, ledger_rows, event_rows, resource_rows, intent_payload):
    """No analysis may slip into a frozen transaction between crash and retry."""
    from harness.re_v2.protocol_28.budget import L4ResourceStore
    ledger = [r.to_json_dict() for r in context.ledger._read_records()]
    resources = L4ResourceStore(context.resources.path, context.inputs.manifest.budget_policy)
    events = [e.to_json_dict() for e in context.events.replay()]
    suffix = events[len(event_rows):]
    if (canonical_json_bytes(ledger) != canonical_json_bytes(ledger_rows)
            or canonical_json_bytes([r.to_json_dict() for r in resources.records]) != canonical_json_bytes(resource_rows)
            or canonical_json_bytes(events[:len(event_rows)]) != canonical_json_bytes(event_rows)
            or (suffix and (len(suffix) != 1 or intent_payload is None
                or suffix[0]['type'] != 'knowledge_revision_requested' or suffix[0]['payload'] != intent_payload))):
        raise KnowledgeRevisionError('revision-transaction-history-diverged')


class _RevisionReads(_Reads):
    """One pure verification invocation; only fully checked ancestors enter this map."""
    def __init__(self, objects):
        super().__init__(objects)
        self.authorities = {}
        self.input_bundles = {}
        self.discovery_bundles = {}
        self.ledger_views = {}

    def read_blob(self, key):
        # Snapshot each content-addressed child once per invocation. A fresh
        # public replay constructs a fresh reader and rechecks all durable bytes.
        return self.reads[key] if key in self.reads else super().read_blob(key)

    def verify(self, key):
        self.read_blob(key)


def _revision_ledger_view(objects, rows):
    """Share a fully authenticated immutable prefix view inside one verification.

    Prefix replay can use only the ancestors already verified by the caller.
    Adding subsequent committed ancestors cannot change that exact prefix's
    record-bound manifests. The independent final-history chronology replay is
    deliberately not memoized here.
    """
    from harness.re_v2.protocol_28.ledger import PROTOCOL_28_LEDGER_PROTOCOL
    cache = objects.ledger_views if isinstance(objects, _RevisionReads) else {}
    key = content_digest(rows)
    if key not in cache:
        cache[key] = _replay(rows, PROTOCOL_28_LEDGER_PROTOCOL, objects).view()
    return cache[key]


def _preserve_inherited_debt(previous_inputs, inputs):
    from harness.re_v2.protocol_28.inputs import protocol_28_residual_debt_acceptance
    before, after = (protocol_28_residual_debt_acceptance(i) for i in (previous_inputs, inputs))
    unresolved = lambda i: {(p.source_id, finding) for p in i.l3_projection_catalog.projections
        for finding in p.unresolved_finding_ids}
    if before != after or (before is not None and unresolved(previous_inputs) != unresolved(inputs)):
        # Evidence expansion is not a reviewed L3 resolution transition.
        raise KnowledgeRevisionError('inherited-debt-requires-authenticated-resolution-authority')


def load_knowledge_authorities(objects):
    """Capture durable streams once, then run the shared pure closure verifier."""
    from harness.re_v2.events import EventStore
    from harness.re_v2.protocol_28.events import PROTOCOL_28_EVENTS
    from harness.re_v2.protocol_28.ledger import Protocol28Ledger
    from harness.re_v2.protocol_28.budget import L4ResourceStore
    root = objects.root.parent
    store = EventStore(root / 'events.jsonl', protocol=PROTOCOL_28_EVENTS)
    store._validate_parent()
    events = store._read_replay()
    pointers = [e for e in events if e.type in {'knowledge_workflow_activated', 'knowledge_revision_activated'}]
    if not pointers:
        ledger = Protocol28Ledger(root / 'ledger.jsonl', objects)
        rows = ledger._read_records()
        from harness.re_v2.run_store import load_run_manifest
        original = load_run_manifest(root.parent)
        resources = L4ResourceStore(root / 'resources.jsonl', original.budget_policy)
        if (any(r.type.startswith('knowledge_') for r in rows) or (resources.records
                and isinstance(resources.records[0], KnowledgeAccountTransferV1) and (rows or len(resources.records) > 1))):
            raise KnowledgeRevisionError('knowledge-activation-event-history-rollback')
        return {}
    reader = _RevisionReads(objects)
    pointer = _read(reader, pointers[0].payload['pointer_id'], KnowledgeActiveRevisionPointerV1)
    manifest = _read(reader, pointer.revision_manifest_id, KnowledgeRevisionManifestV1)
    envelope = _read(reader, manifest.inputs_id, KnowledgeRevisionInputsV1)
    from harness.re_v2.protocol_28.model import ReviewedExhaustiveRunManifestV7
    run_manifest = _read(reader, envelope.manifest_id, ReviewedExhaustiveRunManifestV7)
    ledger = Protocol28Ledger(root / 'ledger.jsonl', objects)
    ledger._validate_parent()
    rows = [r.to_json_dict() for r in ledger._read_records()]
    resources = L4ResourceStore(root / 'resources.jsonl', run_manifest.budget_policy)
    # The header only selects the existing resource decoder. The same pure
    # verifier still validates the complete public Reviewed inputs before use.
    return verify_knowledge_revision_chain(reader, events, rows, resources.records)


def load_knowledge_revision(context):
    """Read and recompute committed authority; staging is never promoted on read."""
    authorities = load_knowledge_authorities(context.objects)
    return next(reversed(authorities.values()))[1] if authorities else None


def verify_knowledge_revision_chain(objects, events, ledger_rows, resource_records):
    """Pure, complete committed closure validation shared by every authority reader.

    No filesystem writes, projection repair, controller calls or weaker manifest
    fallback. Prefix receipts replay against already authenticated ancestors only.
    """
    from types import SimpleNamespace
    from harness.re_v2.events import validate_event_history
    from harness.re_v2.protocol_28.events import PROTOCOL_28_EVENTS
    from harness.re_v2.protocol_28.budget import L4ResourceLedger
    from harness.re_v2.protocol_28.ledger import PROTOCOL_28_LEDGER_PROTOCOL
    reader = _RevisionReads(objects)
    resources = SimpleNamespace(records=resource_records)
    context = SimpleNamespace(objects=reader)
    validate_event_history(events, protocol=PROTOCOL_28_EVENTS)
    pointers = [e for e in events if e.type in {'knowledge_workflow_activated', 'knowledge_revision_activated'}]
    previous = None
    try:
        for event in pointers:
            pointer = _read(context.objects, event.payload['pointer_id'], KnowledgeActiveRevisionPointerV1)
            manifest = _read(context.objects, pointer.revision_manifest_id, KnowledgeRevisionManifestV1)
            authorization = _read(context.objects, pointer.authorization_id, SimpleKnowledgeWorkflowAuthorizationV1)
            transfer = _read(context.objects, authorization.account_transfer_id, KnowledgeAccountTransferV1)
            seal = _read(context.objects, authorization.account_seal_id, KnowledgeAccountSealV1)
            intent = _read(context.objects, authorization.activation_intent_id, KnowledgeWorkflowActivationIntentV1)
            if (intent != KnowledgeWorkflowActivationIntentV1(1, authorization.logical_run_id,
                    authorization.run_manifest_id, authorization.reviewed_catalog_id, transfer.account_id,
                    authorization.reconciler_contract_id, authorization.reconciliation_schema_id, authorization.allow_debt)
                    or [e.payload['intent_id'] for e in events if e.type == 'knowledge_workflow_requested'] != [intent.identity]):
                raise KnowledgeRevisionError('knowledge-activation-intent-mismatch')
            context.objects.read_blob(intent.reconciler_contract_id)
            context.objects.read_blob(intent.reconciliation_schema_id)
            _validate_transfer(context.objects, transfer, resources, seal)
            if (pointer.revision_id != manifest.revision_id or manifest.authorization_id != authorization.identity
                    or manifest.account_transfer_id != transfer.identity or manifest.logical_run_id != transfer.logical_run_id
                    or pointer.previous_pointer_id != (previous.pointer.identity if previous else None)
                    or manifest.previous_manifest_id != (previous.manifest.identity if previous else None)):
                raise KnowledgeRevisionError('knowledge-revision-chain-mismatch')
            inputs = load_revision_inputs(context.objects, manifest.inputs_id)
            context = SimpleNamespace(objects=reader, inputs=inputs)
            L4ResourceLedger.from_records(inputs.manifest.budget_policy, resource_records)
            _validate_reviewed_account(inputs, transfer.account_id, _rows(context.objects, transfer.account_prefix_id), reader)
            base = load_revision_inputs(context.objects, previous.manifest.inputs_id) if previous else inputs
            if previous:
                _preserve_inherited_debt(base, inputs)
            if (authorization.run_manifest_id != transfer.run_manifest_id or authorization.reviewed_catalog_id != transfer.reviewed_catalog_id
                    or authorization.logical_run_id != transfer.logical_run_id or inputs.manifest.source_snapshot_id != authorization.snapshot_id
                    or inputs.manifest.budget_policy != base.manifest.budget_policy or inputs.manifest.executor_catalog_id != base.manifest.executor_catalog_id
                    or inputs.manifest.selection != base.manifest.selection or inputs.manifest.run_id != base.manifest.run_id
                    or (previous is None and inputs.manifest.identity != authorization.run_manifest_id)
                    or (previous is not None and previous.authorization != authorization)):
                raise KnowledgeRevisionError('knowledge-revision-authority-rebound')
            _, envelope, frozen_children = reader.input_bundles[manifest.inputs_id]
            children = dict(frozen_children)
            prefixes = ((manifest.resource_prefix_id, [r.to_json_dict() for r in resources.records]),
                        (manifest.ledger_prefix_id, ledger_rows),
                        (manifest.event_prefix_id, [r.to_json_dict() for r in events]))
            for key, current in prefixes:
                rows = _rows(context.objects, key)
                if canonical_json_bytes(current[:len(rows)]) != canonical_json_bytes(rows):
                    raise KnowledgeRevisionError('knowledge-revision-prefix-rollback')
                children[key] = canonical_json_bytes(rows)
            dependencies = _read(context.objects, manifest.dependency_map_id, KnowledgeDependencyMapV1)
            expected = _dependencies(context, inputs, previous, _rows(context.objects, manifest.ledger_prefix_id),
                _rows(context.objects, manifest.event_prefix_id))
            if dependencies != expected:
                raise KnowledgeRevisionError('knowledge-revision-dependency-mismatch')
            from harness.re_v2.protocol_28.debt import KnowledgeDebtLineageV1, derive_knowledge_debt_lineage
            debt_lineage = derive_knowledge_debt_lineage(reader, manifest.revision_id, dependencies,
                _revision_ledger_view(reader, _rows(reader, manifest.ledger_prefix_id)))
            if type(manifest) is DebtAwareKnowledgeRevisionManifestV1:
                if _read(reader, manifest.debt_lineage_id, KnowledgeDebtLineageV1) != debt_lineage:
                    raise KnowledgeRevisionError('knowledge-debt-lineage-mismatch')
                children[debt_lineage.identity] = canonical_json_bytes(debt_lineage.to_json_dict())
            elif debt_lineage.rows:
                # Old debt-free manifests stay readable; an old invalidation is
                # not authenticated permission to drop an accepted limitation.
                raise KnowledgeRevisionError('knowledge-debt-requires-durable-lineage')
            counters = _read(context.objects, manifest.counters_id, KnowledgeCountersV1)
            revision_context = _read(context.objects, manifest.context_id, KnowledgeRevisionContextV1)
            receipt = _read(context.objects, manifest.revision_receipt_id, KnowledgeRevisionReceiptV1) if manifest.revision_receipt_id else None
            cause = None
            rounds = max((_rows(context.objects, b.authority.active_revision_id).get('round', 0) for b in _bundles(inputs, reader)), default=0)
            outcomes = ()
            for row in (dependencies, counters, revision_context):
                children[row.identity] = canonical_json_bytes(row.to_json_dict())
            if receipt:
                cause = _read(context.objects, receipt.cause_id, KnowledgeRevisionCauseV1)
                rounds, outcomes = _cause_progress(context, cause, previous)
                invalidation = _read(context.objects, manifest.invalidation_receipt_id, KnowledgeInvalidationReceiptV1)
                if (receipt.previous_revision_id != previous.manifest.revision_id or receipt.revision_id != manifest.revision_id
                        or receipt.logical_run_id != manifest.logical_run_id or receipt.reusable_result_ids != manifest.reusable_result_ids
                        or receipt.invalidated_result_ids != manifest.invalidated_result_ids
                        or receipt.compatibility_receipt_ids != manifest.compatibility_receipt_ids
                        or invalidation != KnowledgeInvalidationReceiptV1(1, cause.identity, dependencies.identity,
                            cause.affected_obligation_ids, receipt.invalidated_result_ids)
                        or receipt.affected_obligation_ids != cause.affected_obligation_ids
                        or revision_context.evidence_outcome_ids != outcomes
                        or manifest.expansion_rounds != max(rounds, previous.manifest.expansion_rounds)):
                    raise KnowledgeRevisionError('knowledge-revision-receipt-mismatch')
                for row in (receipt, cause, invalidation):
                    children[row.identity] = canonical_json_bytes(row.to_json_dict())
                compatibility = [_read(context.objects, i, KnowledgeResultCompatibilityV1) for i in receipt.compatibility_receipt_ids]
                if tuple(sorted(r.result_id for r in compatibility)) != receipt.reusable_result_ids:
                    raise KnowledgeRevisionError('knowledge-revision-compatibility-mismatch')
                invalidated = {r.result_id for r in dependencies.results if set(cause.affected_obligation_ids).intersection(r.obligation_ids)}
                while True:
                    expanded = invalidated | {r.result_id for r in dependencies.results if invalidated.intersection(r.dependency_result_ids)}
                    if expanded == invalidated:
                        break
                    invalidated = expanded
                if set(receipt.reusable_result_ids).intersection(invalidated):
                    raise KnowledgeRevisionError('affected-result-cannot-be-reused')
                if compatibility and (inputs.exhaustive_plan != base.exhaustive_plan
                        or inputs.exhaustive_subject_catalog != base.exhaustive_subject_catalog
                        or inputs.safe_snapshot_evidence_catalog != base.safe_snapshot_evidence_catalog):
                    raise KnowledgeRevisionError('unproven-result-compatibility')
                for row in compatibility:
                    dependent = next((r for r in dependencies.results if r.result_id == row.result_id), None)
                    if (row.previous_revision_id, row.revision_id, row.previous_inputs_id, row.inputs_id) != (
                            previous.manifest.revision_id, manifest.revision_id, previous.manifest.inputs_id, envelope.identity) or (
                            dependent is None or row.dependency_ids != tuple(sorted((*dependent.obligation_ids, *dependent.dependency_result_ids)))
                            or not set(dependent.dependency_result_ids).issubset(receipt.reusable_result_ids)):
                        raise KnowledgeRevisionError('knowledge-revision-compatibility-mismatch')
                    children[row.identity] = canonical_json_bytes(row.to_json_dict())
                if set(receipt.reusable_result_ids) & set(receipt.invalidated_result_ids) or set(
                        receipt.reusable_result_ids + receipt.invalidated_result_ids) != {r.result_id for r in dependencies.results}:
                    raise KnowledgeRevisionError('knowledge-revision-result-closure-mismatch')
            elif previous is not None or manifest.invalidation_receipt_id is not None or manifest.reusable_result_ids or manifest.invalidated_result_ids or manifest.compatibility_receipt_ids:
                raise KnowledgeRevisionError('missing-knowledge-revision-receipt')
            expected_counters = _counters(context, inputs, dependencies, previous, _rows(context.objects, manifest.resource_prefix_id),
                _rows(context.objects, manifest.ledger_prefix_id), rounds, cause.affected_obligation_ids if cause else ())
            expected_revision_id = content_digest({'authorization_id': authorization.identity,
                'previous_revision_id': previous.manifest.revision_id if previous else None,
                'cause_id': cause.identity if cause else None, 'inputs_id': envelope.identity})
            if (counters != expected_counters or manifest.revision_id != expected_revision_id
                    or revision_context.evidence_outcome_ids != outcomes
                    or tuple(event.payload['planned_entry_ids']) != tuple(sorted(e.identity for t in inputs.exhaustive_plan.target_plans for e in t.entries))
                    or tuple(event.payload['invalidated_result_ids']) != manifest.invalidated_result_ids):
                raise KnowledgeRevisionError('knowledge-revision-counter-or-pointer-mismatch')
            if (manifest.child_ids != tuple(sorted(children)) or manifest.plan_id != inputs.exhaustive_plan.identity
                    or manifest.subject_catalog_id != inputs.exhaustive_subject_catalog.identity
                    or manifest.reviewed_catalog_id != inputs.reviewed_discovery_catalog.identity
                    or revision_context.revision_id != manifest.revision_id or revision_context.inputs_id != envelope.identity
                    or event.payload['authorization_id'] != authorization.identity or event.payload['revision_id'] != manifest.revision_id):
                raise KnowledgeRevisionError('knowledge-revision-closure-mismatch')
            for key, payload in children.items():
                if _Reads(context.objects).read_blob(key) != payload:
                    raise KnowledgeRevisionError('knowledge-revision-child-mismatch')
            previous = KnowledgeRevisionView(manifest, dependencies, counters, receipt, pointer, authorization, debt_lineage)
            reader.authorities[manifest.identity] = (context, previous)
        ledger_state = _replay(ledger_rows, PROTOCOL_28_LEDGER_PROTOCOL, reader)
        _validate_resource_continuity(context, events, resources, ledger_state.view(), ledger_rows)
        return reader.authorities
    except (ValueError, KeyError, TypeError, OSError, ReV2LedgerError):
        raise KnowledgeRevisionError('invalid-knowledge-revision-authority') from None


def _validate_resource_continuity(context, events, resources, ledger, ledger_rows):
    """One destination ledger; checkpoints authenticate observations, not a second budget."""
    from harness.re_v2.protocol_28.budget import (PairedReservationCommitV1, VerifierRetryReservationV1,
        L4ResourceLedger, _decode_resource_record)
    reserved = {d for r in resources.records if isinstance(r, PairedReservationCommitV1)
        for d in (r.producer_dispatch_id, r.verifier_dispatch_id)} | {
        r.dispatch_id for r in resources.records if isinstance(r, VerifierRetryReservationV1)}
    state_dispatches = {e.payload['dispatch_id'] for e in events if e.type == 'dispatch_reserved'}
    captures = ledger.execution_captures
    if not state_dispatches.issubset(reserved) or not set(captures).issubset(reserved):
        raise KnowledgeRevisionError('knowledge-resource-history-rollback')
    _validate_execution_chronology(context, events, resources.records, ledger, ledger_rows)
    current = [r.to_json_dict() for r in resources.records]
    prior = (0, 0)
    for event in events:
        if event.type != 'knowledge_resource_settled':
            continue
        rows = _rows(context.objects, event.payload['resource_prefix_id'])
        if canonical_json_bytes(current[:len(rows)]) != canonical_json_bytes(rows):
            raise KnowledgeRevisionError('knowledge-resource-observation-rollback')
        replay = L4ResourceLedger.from_records(context.inputs.manifest.budget_policy,
            tuple(_decode_resource_record(r) for r in rows)).decision
        totals = (replay.charged_tokens - replay.open_token_reservations, replay.charged_active_ms - replay.open_active_ms_reservations)
        if (totals != (event.payload['charged_tokens'], event.payload['charged_active_ms'])
                or any(a < b for a, b in zip(totals, prior))):
            raise KnowledgeRevisionError('knowledge-resource-settlement-rollback')
        prior = totals


def _validate_execution_chronology(context, events, resource_records, ledger, ledger_rows):
    """Authenticate both directions, allowing only receipt-before-event crash gaps."""
    from harness.re_v2.protocol_28.budget import PairedReservationCommitV1, VerifierRetryReservationV1, ResourceObservationV1
    from harness.re_v2.protocol_28.planning import SliceSpecV1
    from harness.re_v2.protocol_28.reconciliation import (knowledge_root_event_payload,
        knowledge_completion_event_payload)
    active_at, current = {}, None
    dispatch_events, realized, root_events = {}, {}, {}
    completions = []
    for event in events:
        if event.type in {'knowledge_workflow_activated', 'knowledge_revision_activated'}:
            current = event.payload['revision_id']
        # A legacy event cannot stand in for the missing typed root/completion
        # event in an otherwise permissible receipt-before-event gap.
        if current is not None and event.type in {'root_recorded', 'run_completed'}:
            raise KnowledgeRevisionError('reviewed-root-requires-knowledge-event-authority')
        active_at[event.seq] = current
        if 'dispatch_id' in event.payload:
            dispatch_events.setdefault(event.payload['dispatch_id'], {})[event.type] = event
        if event.type == 'knowledge_work_realized':
            realized[event.payload['work_item_id']] = event
        if event.type == 'slice_realized':
            realized[event.payload['slice_spec_id']] = event
        if event.type == 'knowledge_root_recorded':
            if event.payload['root_id'] in root_events:
                raise KnowledgeRevisionError('duplicate-knowledge-root-event')
            root_events[event.payload['root_id']] = event
        if event.type == 'knowledge_run_completed':
            completions.append(event)
    pairs = {}
    for record in resource_records:
        if isinstance(record, PairedReservationCommitV1):
            for role, dispatch in (('producer', record.producer_dispatch_id), ('verifier', record.verifier_dispatch_id)):
                pairs[dispatch] = (record.identity, record.slice_spec_id, role)
        elif isinstance(record, VerifierRetryReservationV1):
            pairs[record.dispatch_id] = (record.identity, record.slice_spec_id, 'verifier')
    committed = {view.manifest.revision_id for _, view in context.objects.authorities.values()}
    for spec_id in {row[1] for row in pairs.values()}:
        if spec_id in ledger.knowledge_work:
            work = ledger.knowledge_work[spec_id]
            if work.revision_manifest_id not in context.objects.authorities:
                raise KnowledgeRevisionError('reserved-work-revision-history-rollback')
            revision_id = work.revision_id
        else:
            spec = _read(context.objects, spec_id, SliceSpecV1)
            revision_id = _read(context.objects, spec.output_artifact_key_id, KnowledgeSliceWorkV1).revision_id
        if revision_id not in committed:
            raise KnowledgeRevisionError('reserved-work-revision-history-rollback')
    for dispatch, by_type in dispatch_events.items():
        reservation = by_type.get('dispatch_reserved')
        if reservation is None or dispatch not in pairs:
            raise KnowledgeRevisionError('dispatch-event-without-resource-reservation')
        reservation_id, spec_id, role = pairs[dispatch]
        if spec_id in ledger.knowledge_work:
            work = ledger.knowledge_work[spec_id]
            revision_id, output_id = work.revision_id, work.identity
        else:
            spec = _read(context.objects, spec_id, SliceSpecV1)
            origin = _read(context.objects, spec.output_artifact_key_id, KnowledgeSliceWorkV1)
            revision_id, output_id = origin.revision_id, spec.output_artifact_key_id
        work_event = realized.get(spec_id)
        if (reservation.payload['reservation_id'] != reservation_id or reservation.payload['role'] != role
                or reservation.payload['output_artifact_key_id'] != output_id
                or active_at[reservation.seq] != revision_id or work_event is None
                or work_event.seq >= reservation.seq or active_at[work_event.seq] != revision_id):
            raise KnowledgeRevisionError('dispatch-revision-or-realization-chronology-mismatch')
    observed = {r.dispatch_id for r in resource_records if isinstance(r, ResourceObservationV1)}
    last_record = len(ledger_rows)
    capture_records = {r['payload']['execution_capture_hash']: r['seq'] for r in ledger_rows if r['type'] == 'l4_execution_capture'}
    for dispatch, capture in ledger.execution_captures.items():
        envelope = ledger.execution_envelopes[dispatch]
        if envelope.slice_spec_id not in ledger.knowledge_work:
            from harness.re_v2.protocol_28.debt import knowledge_slice_debt
            spec = _read(context.objects, envelope.slice_spec_id, SliceSpecV1)
            origin = _read(context.objects, spec.output_artifact_key_id, KnowledgeSliceWorkV1)
            frozen, active = next((c, a) for c, a in context.objects.authorities.values()
                if a.manifest.revision_id == origin.revision_id)
            inherited = knowledge_slice_debt(frozen, active, spec.plan_entry_id)
            if inherited:
                supplied = _rows(context.objects, envelope.context_bundle_hash)
                if supplied.get('inherited_knowledge_debt') != json.loads(canonical_json_bytes(inherited)):
                    raise KnowledgeRevisionError('slice-capture-inherited-debt-lineage-mismatch')
        by_type = dispatch_events.get(dispatch, {})
        start, recorded = by_type.get('provider_started'), by_type.get('provider_capture_recorded')
        if (start is None or pairs[dispatch][1:] != (envelope.slice_spec_id, envelope.role)
                or start.payload['role'] != envelope.role):
            raise KnowledgeRevisionError('capture-without-preceding-committed-dispatch')
        if recorded is None:
            # Capture receipt is written immediately before its event and observation.
            if capture_records[capture.identity] != last_record or dispatch in observed or 'provider_abandoned' in by_type:
                raise KnowledgeRevisionError('capture-event-rollback-with-later-witness')
        elif (recorded.payload['execution_capture_id'] != capture.identity
                or recorded.payload['raw_result_id'] != capture.raw_result_hash
                or recorded.payload['role'] != envelope.role or recorded.seq <= start.seq):
            raise KnowledgeRevisionError('capture-event-authority-mismatch')
    for dispatch, by_type in dispatch_events.items():
        if 'provider_capture_recorded' in by_type and dispatch not in ledger.execution_captures:
            raise KnowledgeRevisionError('event-capture-missing-from-ledger')
    models = {**ledger.knowledge_roots, **ledger.knowledge_run_roots}
    root_records = {content_digest(r['payload']): r['seq'] for r in ledger_rows
        if r['type'] in {'knowledge_root', 'knowledge_run_root'}}
    for key, root in models.items():
        event = root_events.get(key)
        if event is None:
            if root_records[key] != last_record:
                raise KnowledgeRevisionError('root-event-rollback-with-later-witness')
            continue
        if active_at[event.seq] != root.revision_id or event.payload['revision_id'] != root.revision_id:
            raise KnowledgeRevisionError('root-belongs-to-missing-or-reordered-revision')
        if event.to_json_dict()['payload'] != knowledge_root_event_payload(root):
            raise KnowledgeRevisionError('knowledge-root-event-authority-mismatch')
        if key in ledger.knowledge_roots:
            for capture_id in (root.producer_capture_id, root.reviewer_capture_id):
                dispatch = next(d for d, c in ledger.execution_captures.items() if c.identity == capture_id)
                recorded = dispatch_events[dispatch].get('provider_capture_recorded')
                if recorded is None or recorded.seq >= event.seq:
                    raise KnowledgeRevisionError('root-without-preceding-capture-event')
    if set(root_events) - set(models):
        raise KnowledgeRevisionError('root-event-missing-from-ledger')
    # A prefix hash authenticates its bytes, not its recency. Independently
    # reconcile each revision's inherited debt with all authenticated roots from
    # its ancestors so a self-consistent older prefix cannot erase acceptance.
    from types import SimpleNamespace
    from harness.re_v2.protocol_28.debt import derive_knowledge_debt_lineage
    prior_manifests = set()
    for _, active in context.objects.authorities.values():
        prior_roots = {key: root for key, root in ledger.knowledge_roots.items()
            if ledger.knowledge_work[root.work_item_id].revision_manifest_id in prior_manifests}
        expected = derive_knowledge_debt_lineage(context.objects, active.manifest.revision_id,
            active.dependencies, SimpleNamespace(knowledge_roots=prior_roots, knowledge_work=ledger.knowledge_work))
        if active.debt_lineage != expected:
            raise KnowledgeRevisionError('knowledge-debt-history-omitted-from-revision')
        prior_manifests.add(active.manifest.identity)
    for event in completions:
        root = ledger.knowledge_run_roots.get(event.payload['run_root_id'])
        recorded = root_events.get(event.payload['run_root_id'])
        if (root is None or recorded is None or recorded.seq >= event.seq
                or active_at[event.seq] != root.revision_id
                or event.to_json_dict()['payload'] != knowledge_completion_event_payload(root)):
            raise KnowledgeRevisionError('knowledge-completion-event-authority-mismatch')
