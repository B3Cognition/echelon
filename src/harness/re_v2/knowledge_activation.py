"""Transactional reviewed-discovery authority for the explicit Safe+Reviewed path.

The frozen replay proof stays local. Public proposal/review boundaries are rerun
over authenticated raw catalogue bytes; neither transcripts nor private mappings
are analysis context. No activation child is written until the entire proof and
its exact ownership/category/target closure have passed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from functools import wraps
import json
from typing import Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_acquisition import DiscoveryAcquisition, _AcquisitionProtocol
from harness.re_v2.knowledge_accounting import KnowledgeDispatchAccount, _DispatchProtocol
from harness.re_v2.knowledge_discovery import DiscoveryBoundary
from harness.re_v2.knowledge_discovery_review import DiscoveryReviewBoundary
from harness.re_v2.knowledge_dispatch import DiscoveryController
from harness.re_v2.knowledge_evidence import security_policy_id
from harness.re_v2.knowledge_review_dispatch import DiscoveryReviewController
from harness.re_v2.ledger import LedgerRecord, ReV2LedgerError
from harness.re_v2.protocol_22.partition import WorkspacePartitionCatalogV1
from harness.re_v2.protocol_22.recovery import protocol_22_run_lock
from harness.re_v2.protocol_22.schema import digest_value
from harness.re_v2.protocol_24.model import SelectionScopeV1
from harness.re_v2.protocol_28.authority import L3TargetProjectionCatalogV1
from harness.re_v2.protocol_28.evidence import SnapshotEvidenceCatalogV1, EvidenceStagingPolicyV1
from harness.re_v2.protocol_28.planning import ExhaustiveSubjectCatalogV1, ExhaustiveSubjectV1
from harness.re_v2.protocol_28.safe_evidence import build_safe_snapshot_evidence_catalog
from harness.re_v2.protocol_28.policies import DOMAIN_CATEGORIES, categories_for_depth


class KnowledgeActivationError(ValueError):
    """Closed activation diagnostic; never includes provider/source values."""


def _closed(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except KnowledgeActivationError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, OSError, ReV2LedgerError):
            raise KnowledgeActivationError('invalid-reviewed-discovery-authority') from None
    return call


class _Canonical:
    def to_json_dict(self):
        return asdict(self)

    @property
    def identity(self):
        return content_digest(canonical_json_bytes(self.to_json_dict()))

    @classmethod
    def from_json_dict(cls, value):
        names = {f.name for f in fields(cls)}
        if not isinstance(value, dict) or set(value) != names:
            raise KnowledgeActivationError('invalid-reviewed-object-fields')
        return cls(**{k: tuple(v) if isinstance(v, list) else v for k, v in value.items()})

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise KnowledgeActivationError('invalid-reviewed-object-version')


@dataclass(frozen=True, slots=True)
class ReviewedDiscoveryAuthorityV1(_Canonical):
    schema_version: int
    snapshot_id: str
    partition_id: str
    security_policy_id: str
    source_id: str
    depth: str
    active_revision_id: str
    proposal_receipt_id: str
    review_receipt_id: str
    subject_catalog_id: str
    category_assessment_ids: tuple[str, ...]
    inventory_assessment_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewedCategoryDispositionV1(_Canonical):
    schema_version: int
    source_id: str
    target_kind: str
    target_id: str
    category_id: str
    disposition: str
    depth: str
    obligation_id: str
    review_row_id: str
    raw_evidence_ids: tuple[str, ...]
    subject_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewedInventoryAssessmentV1(_Canonical):
    schema_version: int
    source_id: str
    path: str
    subject_id: str | None
    disposition: str
    review_row_id: str
    raw_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewedTargetMappingV1(_Canonical):
    schema_version: int
    source_id: str
    discovered_target: str
    target_kind: str
    target_id: str
    l3_projection_id: str
    evidence_projection_id: str
    raw_evidence_ids: tuple[str, ...]
    disposition: str


@dataclass(frozen=True, slots=True)
class ReviewedSubjectCatalogV1(_Canonical):
    schema_version: int
    exhaustive_catalog_id: str
    target_mapping_ids: tuple[str, ...]
    replay_proof_id: str
    raw_evidence_catalog_id: str
    safe_evidence_catalog_id: str


@dataclass(frozen=True, slots=True)
class ReviewedDiscoveryBundle:
    authority: ReviewedDiscoveryAuthorityV1
    subject_catalog: ExhaustiveSubjectCatalogV1
    category_assessments: tuple[ReviewedCategoryDispositionV1, ...]
    inventory_assessments: tuple[ReviewedInventoryAssessmentV1, ...]
    target_mappings: tuple[ReviewedTargetMappingV1, ...]
    objects: Mapping[str, bytes]


@dataclass(frozen=True, slots=True)
class ReviewedDiscoveryCatalogV1(_Canonical):
    schema_version: int
    authority_ids: tuple[str, ...]
    object_ids: tuple[str, ...]

    def __post_init__(self):
        super(ReviewedDiscoveryCatalogV1, self).__post_init__()
        for values in (self.authority_ids, self.object_ids):
            if not values or tuple(values) != tuple(sorted(set(values))):
                raise KnowledgeActivationError('inexact-reviewed-catalogue')
            for value in values:
                digest_value(value, 'reviewed-authority')
        if not set(self.authority_ids).issubset(self.object_ids):
            raise KnowledgeActivationError('missing-reviewed-catalogue-root')


def build_reviewed_discovery_catalog(bundles):
    ids = tuple(sorted(b.authority.identity for b in bundles))
    return ReviewedDiscoveryCatalogV1(1, ids, tuple(sorted({i for b in bundles for i in b.objects})))


@_closed
def validate_reviewed_discovery_catalog(catalog, objects, l3, evidence, subjects=None):
    reader = _Reads(objects)
    bundles = tuple(load_reviewed_discovery(ReviewedDiscoveryAuthorityV1.from_json_dict(_json(reader, i)),
                                           objects, l3, evidence) for i in catalog.authority_ids)
    if (len({b.authority.source_id for b in bundles}) != len(bundles)
            or {b.authority.source_id for b in bundles} != {p.source_id for p in l3.projections}
            or build_reviewed_discovery_catalog(bundles) != catalog):
        raise KnowledgeActivationError('inexact-reviewed-source-closure')
    if subjects is not None and subjects.subjects != tuple(sorted(
            (s for b in bundles for s in b.subject_catalog.subjects), key=lambda s: s.sort_key)):
        raise KnowledgeActivationError('reviewed-subject-catalogue-mismatch')
    return bundles


class _Reads:
    """Read-through store that derives exact proof membership from actual replay."""
    def __init__(self, objects):
        self.objects, self.reads = objects, {}

    def read_blob(self, object_id):
        digest_value(object_id, 'reviewed-object')
        payload = (self.objects[object_id] if isinstance(self.objects, Mapping)
                   else self.objects.read_blob(object_id))
        if not isinstance(payload, bytes) or content_digest(payload) != object_id:
            raise KnowledgeActivationError('reviewed-object-hash-mismatch')
        self.reads[object_id] = payload
        return payload


def _json(objects, object_id):
    payload = objects.read_blob(object_id)
    value = json.loads(payload)
    if canonical_json_bytes(value) != payload:
        raise KnowledgeActivationError('noncanonical-reviewed-object')
    return value


def _replay(rows, protocol, objects):
    state, previous = protocol.new_state(), None
    for seq, row in enumerate(rows, 1):
        record = LedgerRecord(**row)
        if (record.schema_version != 1 or record.seq != seq
                or record.previous_record_hash != previous
                or record.record_hash != content_digest(record.identity_dict())):
            raise KnowledgeActivationError('invalid-reviewed-ledger-proof')
        protocol.canonical_payload(record.type, record.payload)
        state.consume(record, objects)
        previous = record.record_hash
    return state


def _authenticated(proof, objects, l3, evidence):
    if set(proof) != {'schema_version', 'kind', 'source_id', 'partition_id', 'selection',
                      'acquisition', 'account', 'object_ids'} or proof['schema_version'] != 1 or proof['kind'] != 'reviewed_discovery_replay':
        raise KnowledgeActivationError('invalid-reviewed-replay-proof')
    partition = WorkspacePartitionCatalogV1.from_json_dict(_json(objects, proof['partition_id']))
    policy = EvidenceStagingPolicyV1.from_json_dict(_json(objects, evidence.policy_id))
    if any(len(s.raw_bytes) > policy.shard_byte_limit for s in evidence.shards):
        raise KnowledgeActivationError('invalid-reviewed-raw-policy')
    selection = SelectionScopeV1.from_json_dict(proof['selection'])
    opening = _json(objects, proof['acquisition'][0]['payload']['receipt_id'])
    scope = opening['evidence_scope']
    if (proof['source_id'] != scope['source_id'] or l3.source_snapshot_id != evidence.source_snapshot_id
            or l3.selection_id != selection.identity or evidence.selection_id != selection.identity
            or scope['snapshot_id'] != evidence.source_snapshot_id
            or scope['partition_id'] != evidence.partition_catalog_id
            or proof['partition_id'] != evidence.partition_catalog_id
            or scope['security_policy_id'] != security_policy_id()):
        raise KnowledgeActivationError('reviewed-scope-mismatch')
    boundary = DiscoveryBoundary.from_catalog(evidence, partition, selection, scope['source_id'],
        scope['depth'], scope['origin_obligation_id'], objects)
    acquisition = _replay(proof['acquisition'], _AcquisitionProtocol(opening, boundary), objects)
    progress = acquisition.progress
    if progress is None or progress.pending_id is not None:
        raise KnowledgeActivationError('reviewed-acquisition-not-terminal')
    binding = boundary.binding_details(progress.binding_id)
    account_opening = _json(objects, proof['account'][0]['payload']['receipt_id'])
    state = _replay(proof['account'], _DispatchProtocol(account_opening), objects)
    run = account_opening['run_authority']
    if (not state.opened or account_opening['logical_run_id'] != opening['logical_run_id']
            or any(run[key] != scope[key] for key in ('snapshot_id', 'partition_id', 'security_policy_id'))
            or scope['source_id'] not in run['source_ids']):
        raise KnowledgeActivationError('reviewed-account-mismatch')
    history = state.review_sources.get(scope['source_id'], [])
    if not history:
        raise KnowledgeActivationError('committed-review-required')
    dispatch_id = history[-1]
    request, applied = state.dispatches[dispatch_id], state.applied.get(dispatch_id)
    if (applied is None or applied['state'] != 'review_ready'
            or request['revision_id'] != progress.revision_id
            or request['binding_id'] != progress.binding_id
            or request['scope_id'] != content_digest(opening)
            or request['producer_dispatch_id'] != state.discovery_sources[scope['source_id']][-1]):
        raise KnowledgeActivationError('active-reviewed-revision-required')
    producer = state.dispatches[request['producer_dispatch_id']]
    if (objects.read_blob(producer['context_id']) != objects.read_blob(acquisition.context_id)
            or producer['revision_id'] != progress.revision_id):
        raise KnowledgeActivationError('reviewed-producer-context-mismatch')
    proposal_id = request['proposal_receipt_id']
    proposal = boundary.read_proposal(progress.binding_id, proposal_id)
    receipt = _json(objects, proposal_id)
    if (receipt['schema_version'] != 2 or proposal['schema_version'] != 2
            or binding['schema_version'] not in {2, 3}):
        raise KnowledgeActivationError('category-aware-captured-proposal-required')
    review_boundary = DiscoveryReviewBoundary(boundary)
    receipt = review_boundary.read_review(progress.binding_id, proposal_id, applied['receipt_id'])
    review = _json(objects, receipt['review_id'])
    if (review['schema_version'] != 2 or receipt['outcome'] != 'ready_for_planning'
            or receipt['analysis_certified'] is not False):
        raise KnowledgeActivationError('category-aware-independent-review-required')
    return scope, progress, proposal_id, applied['receipt_id'], proposal, review, json.loads(boundary.provider_bytes(progress.binding_id))


def _members(projection):
    return set(projection.primary_shard_ids + projection.primary_empty_receipt_ids + projection.primary_nontext_disposition_ids
               + projection.supporting_shard_ids + projection.supporting_empty_receipt_ids + projection.supporting_nontext_disposition_ids)


def _derive(proof, objects, l3, evidence):
    scope, progress, proposal_id, review_id, proposal, review, context = _authenticated(proof, objects, l3, evidence)
    source = scope['source_id']
    raw = {row.identity: row for row in (*evidence.shards, *evidence.empty_receipts, *evidence.nontext_dispositions) if row.source_id == source}
    safe = {row['projection_id']: row['projection'] for row in context['evidence']}
    def mapped(ids):
        result = set()
        for safe_id in ids:
            projection = safe[safe_id]
            if projection['source_id'] != source:
                raise KnowledgeActivationError('cross-source-reviewed-evidence')
            matches = {key for key, row in raw.items() if row.source_relative_path == projection['path']
                       and (getattr(row, 'byte_start', 0) < projection['byte_end']
                            and getattr(row, 'byte_end', getattr(row, 'byte_count', 0)) > projection['byte_start'])}
            if not matches and projection['byte_end'] > projection['byte_start']:
                raise KnowledgeActivationError('unmapped-reviewed-evidence')
            result.update(matches)
        return tuple(sorted(result))
    targets = {(p.target_kind, p.target_id): p for p in l3.projections if p.source_id == source}
    projections = {(p.target_kind, p.target_id): p for p in evidence.projections if p.source_id == source}
    if set(targets) != set(projections) or ('source', source) not in targets:
        raise KnowledgeActivationError('reviewed-target-closure-mismatch')
    for key in targets:
        if targets[key].target_content_id != projections[key].target_content_id:
            raise KnowledgeActivationError('reviewed-target-content-mismatch')
    mapping, mappings = {}, []
    exact_domain_targets = None
    if context.get('schema_version') == 3:
        exact_domain_targets = {
            row['key'] for row in context['analysis_domain_targets']
        }
        if exact_domain_targets != {
            key[1] for key in targets if key[0] == 'domain'
        }:
            raise KnowledgeActivationError('reviewed-target-closure-mismatch')
    for row in [{'key': 'source', 'evidence_ids': [i for s in proposal['subjects'] if s['target'] == 'source' for i in s['evidence_ids']]}, *proposal['domains']]:
        ids = mapped(tuple(sorted(set(row['evidence_ids']))))
        if row['key'] == 'source':
            matches = [('source', source)]
        elif exact_domain_targets is not None:
            key = ('domain', row['key'])
            projection = projections.get(key)
            matches = [key] if (
                row['key'] in exact_domain_targets
                and projection is not None
                and ids
                and set(ids).issubset(_members(projection))
                and set(ids).intersection(
                    projection.primary_shard_ids
                    + projection.primary_empty_receipt_ids
                    + projection.primary_nontext_disposition_ids
                )
            ) else []
        else:
            matches = [key for key, p in projections.items()
                if key[0] == 'domain' and ids and set(ids).issubset(_members(p))
                and set(ids).intersection(p.primary_shard_ids + p.primary_empty_receipt_ids + p.primary_nontext_disposition_ids)]
        if len(matches) != 1 or matches[0] in mapping.values():
            raise KnowledgeActivationError('ambiguous-or-unmapped-reviewed-domain')
        key = matches[0]
        mapping[row['key']] = key
        mappings.append(ReviewedTargetMappingV1(1, source, row['key'], *key,
                          targets[key].identity, projections[key].identity, ids, 'mapped'))
    if set(mapping.values()) != set(targets):
        raise KnowledgeActivationError('unmapped-selected-domain')
    subjects = {}
    for row in proposal['subjects']:
        key = mapping[row['target']]
        ids = mapped(row['evidence_ids'])
        if not ids or not set(ids).issubset(_members(projections[key])):
            raise KnowledgeActivationError('subject-evidence-outside-reviewed-target')
        subjects[row['key']] = ExhaustiveSubjectV1(1, key[0], source, key[1], row['key'],
            tuple(row['category_ids']), ids, (), tuple(sorted({targets[key].candidate_authority_hash, *targets[key].relevant_l2_root_ids})))
    inventory = []
    for row in review['inventory']:
        ids = tuple(sorted(key for key, item in raw.items() if item.source_relative_path == row['path']))
        owner = subjects.get(row['owner'])
        if row['disposition'] == 'owned':
            if owner is None or set(ids) - set(owner.evidence_ids) or set(ids) - set(mapped(row['evidence_ids'])):
                raise KnowledgeActivationError('orphan-reviewed-raw-evidence')
            primary = projections[(owner.target_kind, owner.target_id)]
            if set(ids) - set(primary.primary_shard_ids + primary.primary_empty_receipt_ids + primary.primary_nontext_disposition_ids):
                raise KnowledgeActivationError('reviewed-owner-incompatible-with-primary-target')
        elif row['disposition'] not in {'excluded', 'non-behavioral'} or owner is not None:
            raise KnowledgeActivationError('unresolved-reviewed-inventory')
        inventory.append(ReviewedInventoryAssessmentV1(1, source, row['path'], owner.identity if owner else None,
                                                       row['disposition'], row['row_id'], ids))
    assigned = [item for row in inventory for item in row.raw_evidence_ids]
    if sorted(assigned) != sorted(raw) or len(assigned) != len(set(assigned)):
        raise KnowledgeActivationError('inexact-reviewed-inventory-closure')
    assessments = []
    for row in review['obligations']:
        key = mapping[row['target']]
        assessments.append(ReviewedCategoryDispositionV1(1, source, *key, row['category'], row['disposition'], scope['depth'],
            row['obligation_id'], row['row_id'], mapped(row['evidence_ids']), tuple(sorted(subjects[k].identity for k in row['subject_keys']))))
    if not proposal['domains'] and not any(key[0] == 'domain' for key in targets):
        # Absence is an explicit reviewed whole-inventory conclusion, never a
        # guessed directory name. Conflicting selected L3 domains fail above.
        boundary_row = next(row for row in review['obligations'] if row['category'] == 'cross-domain-boundaries')
        if boundary_row['disposition'] != 'not-applicable':
            raise KnowledgeActivationError('unresolved-reviewed-domain-absence')
        source_key = ('source', source)
        mappings.append(ReviewedTargetMappingV1(1, source, 'no-domain', *source_key,
            targets[source_key].identity, projections[source_key].identity, tuple(sorted(raw)), 'reviewed-no-domain'))
        for category in DOMAIN_CATEGORIES:
            assessments.append(ReviewedCategoryDispositionV1(1, source, 'domain', source, category,
                'not-applicable' if category in categories_for_depth(scope['depth'], 'domain') else 'outside-requested-depth',
                scope['depth'], content_digest({'kind': 'reviewed_domain_absence', 'proposal_receipt_id': proposal_id,
                    'review_receipt_id': review_id, 'category': category, 'inventory_ids': sorted(r.identity for r in inventory)}),
                boundary_row['row_id'], tuple(sorted(raw)), ()))
    catalog = ExhaustiveSubjectCatalogV1(1, scope['snapshot_id'], l3.partition_manifest_id, l3.identity,
                                        tuple(sorted(subjects.values(), key=lambda row: row.sort_key)))
    # Membership is derived from actual boundary reads, not producer-supplied IDs.
    proof = {**proof, 'object_ids': sorted(objects.reads)}
    children = {content_digest(proof): canonical_json_bytes(proof)}
    safe_catalog = build_safe_snapshot_evidence_catalog(evidence)
    reviewed_catalog = ReviewedSubjectCatalogV1(1, catalog.identity, tuple(sorted(row.identity for row in mappings)),
                                               content_digest(proof), evidence.identity, safe_catalog.identity)
    for row in (*subjects.values(), catalog, l3, evidence, safe_catalog, *safe_catalog.objects,
                *mappings, *assessments, *inventory, reviewed_catalog):
        children[row.identity] = canonical_json_bytes(row.to_json_dict())
    authority = ReviewedDiscoveryAuthorityV1(1, scope['snapshot_id'], scope['partition_id'], scope['security_policy_id'], source,
        scope['depth'], progress.revision_id, proposal_id, review_id, reviewed_catalog.identity,
        tuple(sorted(row.identity for row in assessments)), tuple(sorted(row.identity for row in inventory)))
    children[authority.identity] = canonical_json_bytes(authority.to_json_dict())
    return ReviewedDiscoveryBundle(authority, catalog, tuple(sorted(assessments, key=lambda row: row.identity)),
        tuple(sorted(inventory, key=lambda row: row.identity)), tuple(sorted(mappings, key=lambda row: row.identity)),
        {**objects.reads, **children}), proof


@_closed
def activate_reviewed_discovery(
    acquisition: DiscoveryAcquisition,
    account: KnowledgeDispatchAccount,
    review: DiscoveryReviewController,
    l3_targets: L3TargetProjectionCatalogV1,
    evidence: SnapshotEvidenceCatalogV1,
) -> ReviewedDiscoveryAuthorityV1:
    if (not isinstance(acquisition, DiscoveryAcquisition) or not isinstance(account, KnowledgeDispatchAccount)
            or not isinstance(review, DiscoveryReviewController) or review.acquisition is not acquisition
            or review.account is not account or review.producer.acquisition is not acquisition
            or review.producer.account is not account or review.boundary.discovery is not acquisition.boundary
            or not isinstance(l3_targets, L3TargetProjectionCatalogV1) or not isinstance(evidence, SnapshotEvidenceCatalogV1)):
        raise KnowledgeActivationError('invalid-reviewed-activation-inputs')
    with protocol_22_run_lock(acquisition.paths):
        account._require_new_knowledge_store()
        if (account.paths != acquisition.paths or not DiscoveryController._matches_run(acquisition, account)
                or content_digest(review.agent_bytes) == content_digest(review.producer.agent_bytes)):
            raise KnowledgeActivationError('reviewed-controller-authority-mismatch')
        acquisition_history, _ = acquisition.ledger.replay_with_history()
        account_history, state = account.ledger.replay_with_history()
        history = state.review_sources.get(acquisition.opening['evidence_scope']['source_id'], [])
        if not history:
            raise KnowledgeActivationError('committed-review-required')
        review._authenticate_request(state, state.dispatches[history[-1]])
        applied = state.applied.get(history[-1])
        if applied is None or applied['state'] != 'review_ready':
            raise KnowledgeActivationError('active-reviewed-revision-required')
        application_id = content_digest(applied)
        # Freeze the account prefix that committed this source's review. Later
        # sibling spending is still authenticated above, but cannot rename this
        # already reviewed source's immutable planning input on reopen.
        cutoff = next(i for i, row in enumerate(account_history)
                      if row.type == 'review_applied' and row.payload['receipt_id'] == application_id)
        account_history = account_history[:cutoff + 1]
        # The real snapshot boundary rechecks live pinned bytes before durable replay.
        acquisition._provider_bytes_locked()
        partition_id = evidence.partition_catalog_id
        sources = tuple(sorted({p.source_id for p in evidence.projections}))
        selections = [SelectionScopeV1(1, True, (), ()), SelectionScopeV1(1, False, sources, ())]
        if len(sources) == 1:
            selections.append(SelectionScopeV1(1, False, sources,
                tuple(sorted(p.target_id for p in evidence.projections if p.target_kind == 'domain'))))
        selection = next((s for s in selections if s.identity == evidence.selection_id), None)
        if selection is None:
            raise KnowledgeActivationError('invalid-reviewed-selection')
        proof = dict(schema_version=1, kind='reviewed_discovery_replay', source_id=acquisition.opening['evidence_scope']['source_id'],
            partition_id=partition_id, selection=selection.to_json_dict(),
            acquisition=[r.to_json_dict() for r in acquisition_history], account=[r.to_json_dict() for r in account_history], object_ids=[])
        partition_bytes = canonical_json_bytes(acquisition.boundary.partition_authority.to_json_dict())
        if content_digest(partition_bytes) != partition_id:
            raise KnowledgeActivationError('reviewed-partition-mismatch')
        class LocalInputs:
            def read_blob(self, object_id):
                return partition_bytes if object_id == partition_id else acquisition.objects.read_blob(object_id)
        bundle, _ = _derive(proof, _Reads(LocalInputs()), l3_targets, evidence)
        suffix = bundle.authority.identity.removeprefix('sha256:')
        root_path = acquisition.objects.root / 'sha256' / suffix[:2] / suffix[2:]
        if not root_path.exists() and not root_path.is_symlink():
            # Validate everything above, then write children before root.
            # Existing partial children are authenticated, not silently repaired.
            for object_id, payload in bundle.objects.items():
                digest = object_id.removeprefix('sha256:')
                path = acquisition.objects.root / 'sha256' / digest[:2] / digest[2:]
                if (path.exists() or path.is_symlink()) and acquisition.objects.read_blob(object_id) != payload:
                    raise KnowledgeActivationError('reviewed-child-replay-mismatch')
            for object_id, payload in sorted(bundle.objects.items()):
                if object_id != bundle.authority.identity:
                    acquisition.objects.put_blob(payload)
            acquisition.objects.put_blob(bundle.objects[bundle.authority.identity])
        else:
            load_reviewed_discovery(bundle.authority, acquisition.objects, l3_targets, evidence)
        return bundle.authority


@_closed
def load_reviewed_discovery(authority, objects, l3_targets, evidence):
    """Read-only, self-contained re-authentication of an exact activation closure."""
    if not isinstance(authority, ReviewedDiscoveryAuthorityV1):
        raise KnowledgeActivationError('invalid-reviewed-root')
    reader = _Reads(objects)
    catalog = ReviewedSubjectCatalogV1.from_json_dict(_json(reader, authority.subject_catalog_id))
    proof = _json(reader, catalog.replay_proof_id)
    replay_reader = _Reads(objects)
    bundle, reconstructed = _derive(proof, replay_reader, l3_targets, evidence)
    if bundle.authority != authority or proof != reconstructed:
        raise KnowledgeActivationError('reviewed-activation-replay-mismatch')
    for object_id, payload in bundle.objects.items():
        if reader.read_blob(object_id) != payload:
            raise KnowledgeActivationError('reviewed-child-replay-mismatch')
    return bundle
