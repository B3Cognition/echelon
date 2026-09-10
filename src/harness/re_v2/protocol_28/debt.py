"""Exact opt-in limitations, never a fallback for unsuccessful required work."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from harness.re_v2.protocol_28.model import KnowledgeValueV1


@dataclass(frozen=True, slots=True)
class KnowledgeDebtCandidateV1(KnowledgeValueV1):
    schema_version: int
    logical_run_id: str
    snapshot_id: str
    revision_id: str
    work_item_id: str
    obligation_ids: tuple[str, ...]
    reason: str
    investigation_evidence_ids: tuple[str, ...]
    acquisition_outcome_ids: tuple[str, ...]
    unsupported_claim_ids: tuple[str, ...]
    limitation: str


@dataclass(frozen=True, slots=True)
class KnowledgeDebtItemV1(KnowledgeValueV1):
    schema_version: int
    candidate_id: str
    review_id: str
    authorization_id: str
    work_item_id: str
    revision_id: str
    obligation_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewedKnowledgeDebtAcceptanceV1(KnowledgeValueV1):
    schema_version: int
    logical_run_id: str
    snapshot_id: str
    obligation_ids: tuple[str, ...]
    debt_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    review_ids: tuple[str, ...]
    authorization_id: str


@dataclass(frozen=True, slots=True)
class CarriedKnowledgeDebtV1(KnowledgeValueV1):
    schema_version: int
    acceptance_id: str
    source_id: str
    origin_obligation_ids: tuple[str, ...]
    obligation_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeDebtLineageV1(KnowledgeValueV1):
    """Unresolved acceptance authority, independent of analysis-result reuse."""
    schema_version: int
    revision_id: str
    rows: tuple[CarriedKnowledgeDebtV1, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeDebtResolutionCandidateV1(KnowledgeValueV1):
    schema_version: int
    work_item_id: str
    acceptance_id: str
    debt_ids: tuple[str, ...]
    obligation_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    acquisition_outcome_ids: tuple[str, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class ReviewedKnowledgeDebtClosureV1(KnowledgeValueV1):
    schema_version: int
    logical_run_id: str
    snapshot_id: str
    revision_id: str
    work_item_id: str
    acceptance_id: str
    debt_ids: tuple[str, ...]
    resolution_candidate_id: str
    review_id: str
    authorization_id: str


def validate_debt_resolution(context, resolution, active, work):
    """Only exact inherited L4 debt plus newly acquired, visible evidence can close."""
    from harness.re_v2.knowledge_revision import (_read, _rows, KnowledgeRevisionContextV1,
        KnowledgeRevisionManifestV1)
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.protocol_28.reconciliation import reconciliation_response_schema
    if (type(resolution) is not KnowledgeDebtResolutionCandidateV1
            or resolution.work_item_id != work.identity
            or resolution.acceptance_id not in work.inherited_debt_acceptance_ids
            or active.debt_lineage is None or not resolution.evidence_ids or not resolution.acquisition_outcome_ids
            or active.authorization.reconciliation_schema_id != content_digest(reconciliation_response_schema())):
        raise ValueError('invalid-knowledge-debt-resolution')
    lineage = next((r for r in active.debt_lineage.rows if r.acceptance_id == resolution.acceptance_id), None)
    acceptance = _read(context.objects, resolution.acceptance_id, ReviewedKnowledgeDebtAcceptanceV1)
    if (lineage is None or lineage.source_id != work.source_id
            or resolution.obligation_ids != lineage.obligation_ids or not resolution.obligation_ids
            or not set(resolution.obligation_ids).issubset(work.obligation_ids)
            or resolution.debt_ids != acceptance.debt_ids or not resolution.debt_ids
            or (acceptance.logical_run_id, acceptance.snapshot_id, acceptance.authorization_id) != (
                work.logical_run_id, work.snapshot_id, work.authorization_id)
            or work.revision_id != active.manifest.revision_id
            or not set(resolution.evidence_ids).issubset(work.evidence_ids)
            or active.receipt is None or not set(resolution.obligation_ids).issubset(active.receipt.affected_obligation_ids)):
        raise ValueError('inexact-knowledge-debt-resolution-lineage')
    candidates = [_read(context.objects, key, KnowledgeDebtCandidateV1) for key in acceptance.candidate_ids]
    investigated = {key for candidate in candidates for key in candidate.investigation_evidence_ids}
    if not set(resolution.evidence_ids) - investigated:
        raise ValueError('knowledge-debt-closure-requires-new-evidence')
    revision_context = _read(context.objects, active.manifest.context_id, KnowledgeRevisionContextV1)
    prior_context = _read(context.objects, active.manifest.previous_manifest_id, KnowledgeRevisionManifestV1)
    prior_outcomes = _read(context.objects, prior_context.context_id, KnowledgeRevisionContextV1).evidence_outcome_ids
    if not set(resolution.acquisition_outcome_ids).issubset(set(revision_context.evidence_outcome_ids) - set(prior_outcomes)):
        raise ValueError('knowledge-debt-closure-requires-new-acquisition')
    selectors = []
    for key in resolution.acquisition_outcome_ids:
        outcome = _rows(context.objects, key)
        if (outcome.get('kind') != 'discovery_evidence_outcome' or outcome.get('disposition') != 'resolved'
                or outcome.get('reason_code') is not None or outcome.get('reason_class') != 'relationship'
                or outcome['selector']['source_id'] != work.source_id):
            raise ValueError('knowledge-debt-closure-requires-resolved-evidence')
        selectors.append(outcome['selector'])
    raw = {s.identity: s for s in context.inputs.snapshot_evidence_catalog.shards}
    safe = {s.raw_evidence_id: s for s in context.inputs.safe_snapshot_evidence_catalog.objects}
    for key in resolution.evidence_ids:
        shard = raw.get(key)
        if (shard is None or safe[key].disposition != 'available' or not any(
                selector['path'] == shard.source_relative_path
                and selector['byte_start'] <= shard.byte_start < shard.byte_end <= selector['byte_end']
                for selector in selectors)):
            raise ValueError('knowledge-debt-closure-evidence-outside-acquisition')
    return resolution


def reviewed_debt_closure(context, active, work, resolution, review):
    from harness.re_v2.knowledge_revision import _read
    from harness.re_v2.protocol_28.reconciliation import KnowledgeReconciliationCandidateV1, validate_reconciliation_review
    validate_debt_resolution(context, resolution, active, work)
    candidate = _read(context.objects, review.candidate_id, KnowledgeReconciliationCandidateV1)
    validate_reconciliation_review(work, candidate, review)
    if review.verdict != 'PASS' or resolution not in getattr(candidate, 'debt_resolutions', ()):
        raise ValueError('knowledge-debt-closure-requires-exact-independent-review')
    return ReviewedKnowledgeDebtClosureV1(1, work.logical_run_id, work.snapshot_id, work.revision_id,
        work.identity, resolution.acceptance_id, resolution.debt_ids, resolution.identity,
        review.identity, work.authorization_id)


def derive_knowledge_debt_lineage(objects, revision_id, dependencies, ledger):
    """Derive only from authenticated accepted roots in the frozen ledger prefix."""
    from harness.re_v2.knowledge_revision import _read, KnowledgeRevisionManifestV1, KnowledgeDependencyMapV1
    from harness.re_v2.protocol_28.reconciliation import KnowledgeReconciliationCandidateV1
    accepted, closed = {}, set()
    for root in ledger.knowledge_roots.values():
        work = ledger.knowledge_work[root.work_item_id]
        candidate = _read(objects, root.candidate_id, KnowledgeReconciliationCandidateV1)
        closed.update(r.acceptance_id for r in getattr(candidate, 'debt_resolutions', ()))
        for key in set(root.debt_acceptance_ids) - set(work.inherited_debt_acceptance_ids):
            acceptance = _read(objects, key, ReviewedKnowledgeDebtAcceptanceV1)
            original = _read(objects, work.revision_manifest_id, KnowledgeRevisionManifestV1)
            origin_map = _read(objects, original.dependency_map_id, KnowledgeDependencyMapV1)
            origins = {i for row in origin_map.obligations if row.obligation_id in acceptance.obligation_ids
                for i in row.origin_obligation_ids}
            selected = [row for row in dependencies.obligations if origins.intersection(row.origin_obligation_ids)]
            if (not origins or {i for row in selected for i in row.origin_obligation_ids} != origins
                    or any(row.source_id != work.source_id for row in selected)):
                raise ValueError('accepted-knowledge-debt-obligation-lineage-lost')
            accepted[key] = CarriedKnowledgeDebtV1(1, key, work.source_id, tuple(sorted(origins)),
                tuple(sorted(row.obligation_id for row in selected)))
    return KnowledgeDebtLineageV1(1, revision_id,
        tuple(sorted((row for key, row in accepted.items() if key not in closed), key=lambda row: row.identity)))


def inherited_knowledge_debt_ids(active, obligation_ids):
    lineage = active.debt_lineage
    selected = set(obligation_ids)
    return tuple(sorted(row.acceptance_id for row in (() if lineage is None else lineage.rows)
        if selected.intersection(row.obligation_ids)))


def knowledge_slice_debt(context, active, entry_id):
    selected = [row for row in active.dependencies.obligations if entry_id in row.entry_ids]
    keys = inherited_knowledge_debt_ids(active, (row.obligation_id for row in selected))
    return [knowledge_debt_provider_context(context, key, selected[0].source_id) for key in keys]


def knowledge_debt_provider_context(context, acceptance_id, source_id):
    """Safe original limitation and exact acceptance/candidate/review provenance."""
    from harness.re_v2.knowledge_revision import _read
    acceptance = accepted_debt_context(context, acceptance_id, source_id)
    if type(acceptance) is InheritedResidualDebtContextV1:
        return acceptance.to_json_dict()
    return {**acceptance.to_json_dict(), 'acceptance_id': acceptance.identity,
        'disposition': 'accepted-not-closed-by-reanalysis',
        'items': [_read(context.objects, key, KnowledgeDebtItemV1).to_json_dict() for key in acceptance.debt_ids],
        'candidates': [_read(context.objects, key, KnowledgeDebtCandidateV1).to_json_dict() for key in acceptance.candidate_ids]}


@dataclass(frozen=True, slots=True)
class InheritedResidualDebtContextV1(KnowledgeValueV1):
    """Safe typed view of existing acceptance, not permission for new L4 debt."""
    schema_version: int
    kind: Literal['inherited-l3-residual-debt']
    acceptance_id: str
    snapshot_id: str
    source_id: str
    finding_ids: tuple[str, ...]
    projection_ids: tuple[str, ...]
    closure_root_id: str
    source_review_root_id: str
    guidance_id: str
    disposition: Literal['accepted-not-closed-by-l4']


def inherited_residual_debt(context, source_id):
    from harness.re_v2.protocol_28.inputs import protocol_28_residual_debt_acceptance
    acceptance = protocol_28_residual_debt_acceptance(context.inputs)
    projections = [p for p in context.inputs.l3_projection_catalog.projections
        if p.source_id == source_id and p.unresolved_finding_ids]
    if acceptance is None or not projections:
        return None
    source_roots = dict(acceptance.source_root_hashes)
    if source_id not in source_roots:
        raise ValueError('inherited-debt-lacks-source-review-lineage')
    return InheritedResidualDebtContextV1(1, 'inherited-l3-residual-debt', acceptance.identity,
        acceptance.source_snapshot_id, source_id,
        tuple(sorted({i for p in projections for i in p.unresolved_finding_ids})),
        tuple(sorted(p.identity for p in projections)), acceptance.closure_root_hash,
        source_roots[source_id], acceptance.guidance_directive_hash, 'accepted-not-closed-by-l4')


def accepted_debt_context(context, acceptance_id, source_id):
    """Closed compatible authority union; historical debt is never reaccepted."""
    from harness.re_v2.knowledge_revision import _read
    inherited = inherited_residual_debt(context, source_id)
    if inherited is not None and acceptance_id == inherited.acceptance_id:
        return inherited
    return _read(context.objects, acceptance_id, ReviewedKnowledgeDebtAcceptanceV1)


def accepted_debt_ids(context, acceptance_id, source_id):
    value = accepted_debt_context(context, acceptance_id, source_id)
    return value.finding_ids if isinstance(value, InheritedResidualDebtContextV1) else value.debt_ids


def validate_debt_candidate(context, candidate, active):
    """Require investigated, target-local unavailable dependency authority."""
    from harness.re_v2.knowledge_revision import KnowledgeRevisionContextV1, KnowledgeRevisionReceiptV1, _read, _rows
    if (type(candidate) is not KnowledgeDebtCandidateV1 or not active.authorization.allow_debt
            or candidate.reason not in {'unavailable-dependency', 'dynamic-dependency'}
            or candidate.logical_run_id != active.manifest.logical_run_id
            or candidate.snapshot_id != active.authorization.snapshot_id
            or candidate.revision_id != active.manifest.revision_id
            or not candidate.obligation_ids or not candidate.investigation_evidence_ids
            or not candidate.acquisition_outcome_ids or candidate.unsupported_claim_ids):
        raise ValueError('ineligible-knowledge-debt')
    obligations = {row.obligation_id: row for row in active.dependencies.obligations}
    if not set(candidate.obligation_ids).issubset(obligations):
        raise ValueError('ineligible-knowledge-debt-obligations')
    selected = tuple(obligations[key] for key in candidate.obligation_ids)
    if (any(not row.entry_ids for row in selected) or len({row.source_id for row in selected}) != 1 or not set(candidate.investigation_evidence_ids).issubset(
            eid for row in selected for eid in row.evidence_ids)):
        raise ValueError('ineligible-knowledge-debt-evidence')
    if active.manifest.revision_receipt_id is None:
        raise ValueError('ineligible-knowledge-debt-investigation')
    receipt = _read(context.objects, active.manifest.revision_receipt_id, KnowledgeRevisionReceiptV1)
    if not set(candidate.obligation_ids).issubset(receipt.affected_obligation_ids):
        raise ValueError('ineligible-knowledge-debt-obligation-investigation')
    revision_context = _read(context.objects, active.manifest.context_id, KnowledgeRevisionContextV1)
    if not set(candidate.acquisition_outcome_ids).issubset(revision_context.evidence_outcome_ids):
        raise ValueError('ineligible-knowledge-debt-investigation')
    for key in candidate.acquisition_outcome_ids:
        outcome = _rows(context.objects, key)
        if (outcome.get('kind') != 'discovery_evidence_outcome' or outcome.get('disposition') != 'unknown'
                or outcome.get('reason_code') != 'unavailable-evidence'
                or outcome.get('reason_class') != 'relationship'
                or outcome['selector']['source_id'] != selected[0].source_id):
            raise ValueError('ineligible-knowledge-debt-dependency-boundary')
    return candidate
