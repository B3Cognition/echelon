"""Explicit target/source work items executed by the existing L4 lifecycle.

This is an artifact contract and one-work-item executor, not another controller,
scheduler or account. Ordinary slice acceptance never satisfies these gates.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_evidence import (
    validate_provider_context,
    validate_provider_output,
)
from harness.re_v2.protocol_28.model import KnowledgeValueV1
from harness.re_v2.protocol_28.debt import KnowledgeDebtCandidateV1, KnowledgeDebtResolutionCandidateV1


RECONCILIATION_CHECKS = (
    'category-coverage', 'contradictions', 'cross-slice-call-chains',
    'evidence-support', 'dependency-continuity', 'omitted-work', 'inherited-debt',
)


def reconciliation_response_schema():
    """Exact structured response contracts; deterministic validation remains authoritative."""
    from dataclasses import fields
    from typing import get_args, get_origin, get_type_hints
    def schema(annotation):
        origin, args = get_origin(annotation), get_args(annotation)
        if origin is Literal:
            return {'type': 'string', 'enum': list(args)}
        if origin is tuple:
            return {'type': 'array', 'items': schema(args[0]), 'uniqueItems': True}
        if annotation is int:
            return {'type': 'integer', 'minimum': 0, 'maximum': 2**63 - 1}
        if annotation is str:
            return {'type': 'string', 'minLength': 1, 'maxLength': 262144}
        hints = get_type_hints(annotation)
        properties = {f.name: schema(hints[f.name]) for f in fields(annotation)}
        properties['schema_version'] = {'type': 'integer', 'const': 1}
        return {'type': 'object', 'additionalProperties': False, 'required': list(properties), 'properties': properties}
    return {'oneOf': [schema(KnowledgeReconciliationCandidateV1), schema(KnowledgeReconciliationReviewV1),
        schema(DebtResolvingKnowledgeReconciliationCandidateV1), schema(DebtResolvingKnowledgeReconciliationReviewV1)]}


def _role_agent(agent, role):
    from harness.re_v2.protocol_22.provider import decode_prosaic_agent_bytes, canonical_prosaic_agent_bytes
    from dataclasses import replace
    artifact = decode_prosaic_agent_bytes(agent)
    framing = 'Produce a reconciliation candidate.\n' if role == 'producer' else 'Independently review the candidate without modifying it.\n'
    return canonical_prosaic_agent_bytes(replace(artifact, body=framing + artifact.body))


@dataclass(frozen=True, slots=True)
class KnowledgeReconciliationWorkItemV1(KnowledgeValueV1):
    schema_version: int
    logical_run_id: str
    snapshot_id: str
    revision_id: str
    revision_manifest_id: str
    authorization_id: str
    scope: Literal['target', 'source']
    source_id: str
    target_kind: Literal['domain', 'source']
    target_id: str
    plan_id: str
    obligation_ids: tuple[str, ...]
    category_assessment_ids: tuple[str, ...]
    input_result_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    inherited_debt_acceptance_ids: tuple[str, ...]
    canonical_context_bytes: int
    conservative_tokens: int

    @property
    def output_artifact_key_id(self):
        return self.identity


@dataclass(frozen=True, slots=True)
class KnowledgeReconciliationCheckV1(KnowledgeValueV1):
    schema_version: int
    check: str
    disposition: Literal['supported', 'uncertain', 'failed', 'unsupported-absence']
    evidence_ids: tuple[str, ...]
    result_ids: tuple[str, ...]
    debt_candidate_ids: tuple[str, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class KnowledgeReconciliationCandidateV1(KnowledgeValueV1):
    schema_version: int
    work_item_id: str
    obligation_ids: tuple[str, ...]
    input_result_ids: tuple[str, ...]
    checks: tuple[KnowledgeReconciliationCheckV1, ...]
    debt_candidates: tuple[KnowledgeDebtCandidateV1, ...]
    rendered_markdown: str

    @classmethod
    def from_json_dict(cls, value):
        if cls is KnowledgeReconciliationCandidateV1 and isinstance(value, dict) and 'debt_resolutions' in value:
            return DebtResolvingKnowledgeReconciliationCandidateV1.from_json_dict(value)
        return super(KnowledgeReconciliationCandidateV1, cls).from_json_dict(value)


@dataclass(frozen=True, slots=True)
class DebtResolvingKnowledgeReconciliationCandidateV1(KnowledgeReconciliationCandidateV1):
    debt_resolutions: tuple[KnowledgeDebtResolutionCandidateV1, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeReconciliationReviewV1(KnowledgeValueV1):
    schema_version: int
    work_item_id: str
    candidate_id: str
    verdict: Literal['PASS', 'REPAIR', 'ACCEPT_WITH_DEBT']
    checks: tuple[KnowledgeReconciliationCheckV1, ...]
    eligible_debt_candidate_ids: tuple[str, ...]
    rationale: str

    @classmethod
    def from_json_dict(cls, value):
        if cls is KnowledgeReconciliationReviewV1 and isinstance(value, dict) and 'resolved_debt_candidate_ids' in value:
            return DebtResolvingKnowledgeReconciliationReviewV1.from_json_dict(value)
        return super(KnowledgeReconciliationReviewV1, cls).from_json_dict(value)


@dataclass(frozen=True, slots=True)
class DebtResolvingKnowledgeReconciliationReviewV1(KnowledgeReconciliationReviewV1):
    resolved_debt_candidate_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeReconciliationExecutionReceiptV1(KnowledgeValueV1):
    schema_version: int
    work_item_id: str
    role: Literal['producer', 'verifier']
    artifact_id: str
    execution_capture_id: str


@dataclass(frozen=True, slots=True)
class KnowledgeReconciliationFeedbackV1(KnowledgeValueV1):
    schema_version: int
    work_item_id: str
    review_id: str
    fingerprint_id: str
    checks: tuple[KnowledgeReconciliationCheckV1, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeReconciliationRootV1(KnowledgeValueV1):
    schema_version: int
    logical_run_id: str
    snapshot_id: str
    revision_id: str
    authorization_id: str
    scope: Literal['target', 'source']
    source_id: str
    target_kind: Literal['domain', 'source']
    target_id: str
    plan_id: str
    work_item_id: str
    obligation_ids: tuple[str, ...]
    input_result_ids: tuple[str, ...]
    candidate_id: str
    review_id: str
    producer_capture_id: str
    reviewer_capture_id: str
    debt_acceptance_ids: tuple[str, ...]
    debt_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewedKnowledgeRunRootV1(KnowledgeValueV1):
    schema_version: int
    logical_run_id: str
    snapshot_id: str
    revision_id: str
    revision_manifest_id: str
    authorization_id: str
    plan_id: str
    obligation_ids: tuple[str, ...]
    target_root_ids: tuple[str, ...]
    source_root_ids: tuple[str, ...]
    accepted_slice_ids: tuple[str, ...]
    debt_acceptance_ids: tuple[str, ...]
    debt_ids: tuple[str, ...]


def knowledge_root_event_payload(root):
    """Project an authenticated typed root exactly; event data is not authority."""
    if type(root) is KnowledgeReconciliationRootV1:
        kind = root.scope
        accepted = root.input_result_ids if kind == 'target' else ()
        lower = root.input_result_ids if kind == 'source' else ()
    elif type(root) is ReviewedKnowledgeRunRootV1:
        kind, accepted = 'run', root.accepted_slice_ids
        lower = tuple(sorted((*root.target_root_ids, *root.source_root_ids)))
    else:
        raise ValueError('invalid-reviewed-knowledge-root')
    return {'root_id': root.identity, 'root_kind': kind, 'revision_id': root.revision_id,
        'required_accepted_slice_ids': list(accepted), 'required_root_ids': list(lower),
        'debt_ids': list(root.debt_ids)}


def knowledge_completion_event_payload(root):
    """Completion is derived only from the authenticated run root."""
    if type(root) is not ReviewedKnowledgeRunRootV1:
        raise ValueError('knowledge-completion-requires-reviewed-run-root')
    return {'run_root_id': root.identity, 'revision_id': root.revision_id, 'debt_ids': list(root.debt_ids)}


def _read(context, key, cls):
    from harness.re_v2.knowledge_revision import _read as read
    return read(context.objects, key, cls)


def _sorted(rows):
    return tuple(sorted(rows, key=lambda row: row.identity))


def _put(context, value):
    from harness.re_v2.knowledge_revision import _put as put
    return put(context.objects, value)


def build_reconciliation_work(context, target, *, scope, input_results):
    """Derive exact required work from active reviewed categories and prior roots."""
    from harness.re_v2.knowledge_revision import load_knowledge_revision, _bundles
    from harness.re_v2.protocol_28.events import replay_protocol_28
    from harness.re_v2.protocol_28.graph import AcceptedExhaustiveSliceV1
    from harness.re_v2.protocol_28.debt import inherited_residual_debt, inherited_knowledge_debt_ids
    active = load_knowledge_revision(context)
    if active is None:
        raise ValueError('explicit-reviewed-knowledge-authority-required')
    state = replay_protocol_28(context.events.replay())
    roots = context.ledger.replay().knowledge_roots
    if target not in context.inputs.exhaustive_plan.target_plans:
        raise ValueError('reconciliation-target-outside-active-plan')
    selected = [row for row in active.dependencies.obligations if row.source_id == target.source_id and
                (scope == 'source' or (row.target_kind, row.target_id) == (target.target_kind, target.target_id))]
    input_ids = tuple(sorted(r.identity for r in input_results))
    if len(set(input_ids)) != len(input_results):
        raise ValueError('duplicate-reconciliation-input')
    if scope == 'target':
        expected = {e.identity for e in target.entries}
        if (any(type(r) is not AcceptedExhaustiveSliceV1 for r in input_results)
                or {r.plan_entry_id for r in input_results} != expected or len(input_results) != len(expected)
                or not set(input_ids).issubset(state.accepted_slices.values())):
            raise ValueError('reconciliation-requires-every-accepted-slice')
        residual = inherited_residual_debt(context, target.source_id)
        inherited = tuple(sorted({*((residual.acceptance_id,) if residual else ()),
            *inherited_knowledge_debt_ids(active, (row.obligation_id for row in selected))}))
    else:
        plans = {t.identity for t in context.inputs.exhaustive_plan.target_plans if t.source_id == target.source_id}
        if (any(type(r) is not KnowledgeReconciliationRootV1 or r.scope != 'target' for r in input_results)
                or {r.plan_id for r in input_results} != plans or len(input_results) != len(plans)
                or not set(input_ids).issubset(roots)):
            raise ValueError('source-reconciliation-requires-every-reviewed-target')
        inherited = tuple(sorted({i for r in input_results for i in r.debt_acceptance_ids}))
    categories = tuple(sorted(row.identity for b in _bundles(context.inputs) for row in b.category_assessments
        if row.obligation_id in {r.obligation_id for r in selected}))
    evidence = tuple(sorted({i for row in selected for i in row.evidence_ids}))
    return KnowledgeReconciliationWorkItemV1(1, active.manifest.logical_run_id, active.authorization.snapshot_id,
        active.manifest.revision_id, active.manifest.identity, active.authorization.identity, scope, target.source_id, target.target_kind,
        target.target_id, target.identity, tuple(sorted(row.obligation_id for row in selected)), categories,
        input_ids, evidence, inherited, 0, 0)


def _validate_checks(work, checks):
    if len(checks) != len(RECONCILIATION_CHECKS) or {r.check for r in checks} != set(RECONCILIATION_CHECKS):
        raise ValueError('inexact-reconciliation-check-coverage')
    for row in checks:
        if (not set(row.evidence_ids).issubset(work.evidence_ids)
                or row.result_ids != work.input_result_ids
                or (work.evidence_ids and not row.evidence_ids)
                or row.disposition == 'unsupported-absence'
                or (row.disposition != 'uncertain' and row.debt_candidate_ids)):
            raise ValueError('unsupported-reconciliation-evidence-or-absence')


def validate_reconciliation_candidate(work, candidate):
    if (candidate.work_item_id != work.identity or candidate.obligation_ids != work.obligation_ids
            or candidate.input_result_ids != work.input_result_ids):
        raise ValueError('inexact-reconciliation-obligations')
    _validate_checks(work, candidate.checks)
    resolutions = getattr(candidate, 'debt_resolutions', ())
    if resolutions and (candidate.debt_candidates or len({r.acceptance_id for r in resolutions}) != len(resolutions)
            or any(r.work_item_id != work.identity or r.acceptance_id not in work.inherited_debt_acceptance_ids
                or not r.debt_ids or not r.obligation_ids or not r.evidence_ids or not r.acquisition_outcome_ids
                or not set(r.obligation_ids).issubset(work.obligation_ids)
                or not set(r.evidence_ids).issubset(work.evidence_ids) for r in resolutions)):
        raise ValueError('inexact-reconciliation-debt-resolution')
    debt_ids = tuple(sorted(d.identity for d in candidate.debt_candidates))
    referenced = tuple(sorted({i for r in candidate.checks for i in r.debt_candidate_ids}))
    if debt_ids != referenced or any(d.work_item_id != work.identity for d in candidate.debt_candidates):
        raise ValueError('inexact-reconciliation-debt-candidate-set')
    for row in candidate.checks:
        if row.disposition == 'uncertain' and (row.check != 'dependency-continuity' or not row.debt_candidate_ids):
            raise ValueError('ineligible-reconciliation-uncertainty')


def validate_reconciliation_review(work, candidate, review):
    validate_reconciliation_candidate(work, candidate)
    if review.work_item_id != work.identity or review.candidate_id != candidate.identity:
        raise ValueError('reconciliation-review-candidate-mismatch')
    _validate_checks(work, review.checks)
    resolutions = tuple(sorted(r.identity for r in getattr(candidate, 'debt_resolutions', ())))
    reviewed = getattr(review, 'resolved_debt_candidate_ids', ())
    if reviewed != (resolutions if review.verdict == 'PASS' else ()):
        raise ValueError('debt-resolution-requires-exact-independent-review')
    if review.verdict == 'REPAIR':
        if all(row.disposition == 'supported' for row in review.checks):
            raise ValueError('reconciliation-repair-requires-durable-feedback')
        return
    if any(row.disposition == 'failed' for row in (*candidate.checks, *review.checks)):
        raise ValueError('reconciliation-false-pass')
    debt_ids = tuple(sorted(d.identity for d in candidate.debt_candidates))
    uncertain = {r.check for r in candidate.checks if r.disposition == 'uncertain'}
    reviewed_uncertain = {r.check for r in review.checks if r.disposition == 'uncertain'}
    if review.verdict == 'PASS':
        if uncertain or reviewed_uncertain or debt_ids or review.eligible_debt_candidate_ids:
            raise ValueError('ordinary-reconciliation-pass-cannot-accept-debt')
    elif (uncertain != {'dependency-continuity'} or reviewed_uncertain != uncertain or not debt_ids
            or review.eligible_debt_candidate_ids != debt_ids
            or {i for r in review.checks for i in r.debt_candidate_ids} != set(debt_ids)):
        raise ValueError('inexact-reviewed-reconciliation-debt')


def reconciliation_context(context, work, *, role, candidate=None, feedback=()):
    """Only Safe evidence and normalized accepted artifacts, never local proof."""
    from harness.re_v2.knowledge_revision import load_knowledge_revision
    active = load_knowledge_revision(context)
    if (active is None or active.manifest.revision_id != work.revision_id
            or work.revision_manifest_id != active.manifest.identity or work.authorization_id != active.authorization.identity):
        raise ValueError('stale-reconciliation-work')
    return _reconciliation_context(context, active, context.ledger.replay(), work,
        role=role, candidate=candidate, feedback=feedback)


def _reconciliation_context(context, active, view, work, *, role, candidate=None, feedback=()):
    from harness.re_v2.protocol_28.artifacts import ExhaustiveEvidenceSliceV1
    from harness.re_v2.protocol_28.debt import knowledge_debt_provider_context, accepted_debt_context
    from harness.re_v2.knowledge_activation import ReviewedCategoryDispositionV1
    from harness.re_v2.knowledge_revision import KnowledgeRevisionContextV1, DebtAwareKnowledgeRevisionManifestV1, _rows
    accepted = {r.identity: r for r in view.accepted_slices.values()}
    results = []
    for key in work.input_result_ids:
        if key in accepted:
            row = _read(context, accepted[key].candidate_hash, ExhaustiveEvidenceSliceV1)
        else:
            root = view.knowledge_roots[key]
            row = _read(context, root.candidate_id, KnowledgeReconciliationCandidateV1)
        results.append({'result_id': key, 'candidate': row.to_json_dict()})
    categories = [_read(context, key, ReviewedCategoryDispositionV1).to_json_dict() for key in work.category_assessment_ids]
    safe = {row.raw_evidence_id: row for row in context.inputs.safe_snapshot_evidence_catalog.objects}
    inherited = [(knowledge_debt_provider_context(context, i, work.source_id)
        if type(active.manifest) is DebtAwareKnowledgeRevisionManifestV1
        else accepted_debt_context(context, i, work.source_id).to_json_dict())
        for i in work.inherited_debt_acceptance_ids]
    revision_context = _read(context, active.manifest.context_id, KnowledgeRevisionContextV1)
    outcomes = []
    for key in revision_context.evidence_outcome_ids:
        row = _rows(context.objects, key)
        if row['selector']['source_id'] == work.source_id:
            outcomes.append({'outcome_id': key, **{k: row[k] for k in ('selector', 'reason_class', 'disposition', 'reason_code')}})
    payload = canonical_json_bytes({'schema_version': 1, 'kind': 'knowledge-reconciliation', 'role': role,
        'work_item': work.to_json_dict(), 'category_assessments': categories,
        'snapshot_evidence': [safe[key].to_json_dict() for key in work.evidence_ids],
        'accepted_results': results, 'inherited_debt': inherited, 'evidence_request_outcomes': outcomes,
        'candidate': candidate.to_json_dict() if candidate else None,
        'feedback': [r.to_json_dict() for r in feedback] if role == 'producer' else [],
        'required_checks': list(RECONCILIATION_CHECKS), 'debt_authorized': active.authorization.allow_debt})
    maximum = context.inputs.exhaustive_policy.max_context_bytes + (
        context.inputs.exhaustive_policy.max_candidate_output_bytes if role == 'verifier' else 0)
    if len(payload) > maximum:
        raise ValueError('reconciliation-context-bound')
    validate_provider_context(payload, max_bytes=maximum)
    return payload


def _capture(context, backend, work, role, dispatch_id, attempt, agent, schema, reservation, candidate, feedback):
    from harness.re_v2.protocol_28.execution import PersistedL4ExecutionV1
    from harness.re_v2.protocol_28.lifecycle import _call_provider
    from harness.re_v2.protocol_28.events import replay_protocol_28
    view = context.ledger.replay()
    if dispatch_id in view.execution_captures:
        return PersistedL4ExecutionV1(view.execution_envelopes[dispatch_id], view.execution_captures[dispatch_id])
    dispatch = replay_protocol_28(context.events.replay()).dispatches.get(dispatch_id)
    if dispatch is None or dispatch.stage != 'reserved':
        raise ValueError('reconciliation-dispatch-indeterminate')
    payload = reconciliation_context(context, work, role=role, candidate=candidate, feedback=feedback)
    for value in (agent, schema, payload):
        context.objects.put_blob(value)
    return _call_provider(context, backend, role, dispatch_id, attempt, work, work, agent, payload, schema,
                          reservation, candidate_id=candidate.identity if candidate else None)


def _artifact(context, work, capture, cls, candidate=None):
    from harness.re_v2.protocol_28.execution import parse_captured_result
    if capture.capture.result_kind != 'provider_result':
        raise ValueError('reconciliation-provider-failure')
    raw = parse_captured_result(context.objects, capture.capture, validate_provider_output)
    if len(raw) > context.inputs.exhaustive_policy.max_candidate_output_bytes:
        raise ValueError('reconciliation-output-bound')
    artifact = cls.from_json_dict(json.loads(raw))
    if candidate is None:
        validate_reconciliation_candidate(work, artifact)
    else:
        validate_reconciliation_review(work, candidate, artifact)
    _put(context, artifact)
    receipt = KnowledgeReconciliationExecutionReceiptV1(1, work.identity, capture.envelope.role,
        artifact.identity, capture.capture.identity)
    _put(context, receipt)
    context.ledger.record_knowledge_artifact(receipt)
    context.controller.append_once('knowledge_artifact_recorded', {'dispatch_id': capture.envelope.dispatch_id,
        'role': capture.envelope.role, 'work_item_id': work.identity, 'artifact_id': artifact.identity})
    return artifact


def execute_reconciliation(context, backend, work):
    """Run one explicit work item with existing pairs, captures and finite retry."""
    from harness.re_v2.knowledge_revision import load_knowledge_revision, inherited_attempts
    from harness.re_v2.protocol_28.budget import PairedReservationCommitV1
    from harness.re_v2.protocol_28.lifecycle import (Protocol28LifecycleError, _reservation, _dispatch_id,
        _resource_block_reason, _release_paired_verifier)
    from harness.re_v2.protocol_28.events import replay_protocol_28
    active = load_knowledge_revision(context)
    if (active is None or work.revision_manifest_id != active.manifest.identity
            or work.revision_id != active.manifest.revision_id or work.authorization_id != active.authorization.identity):
        raise ValueError('stale-reconciliation-work')
    if replay_protocol_28(context.events.replay()).knowledge_revision_intent_id is not None:
        raise ValueError('knowledge-revision-is-incomplete')
    prior = context.ledger.replay()
    existing = next((r for r in prior.knowledge_roots.values() if r.work_item_id == work.identity), None)
    if existing:
        if existing.identity not in replay_protocol_28(context.events.replay()).root_requirements:
            context.controller.record_knowledge_root(existing)
        return existing
    if work.identity in replay_protocol_28(context.events.replay()).failed_output_ids:
        return 'reconciliation-needs-attention'
    _put(context, work)
    context.ledger.record_knowledge_work(work)
    context.controller.append_once('knowledge_work_realized', {'work_item_id': work.identity})
    agent = context.objects.read_blob(active.authorization.reconciler_contract_id)
    schema = context.objects.read_blob(active.authorization.reconciliation_schema_id)
    # Distinct trusted role framing ensures independent request/context identities.
    agents = {role: _role_agent(agent, role) for role in ('producer', 'verifier')}
    feedback = ()
    last_fingerprint = None
    limit = context.inputs.exhaustive_policy.producer_attempt_limit
    for attempt in range(inherited_attempts(active, work.obligation_ids, work.scope + '-reconciliation') + 1, limit + 1):
        producer_dispatch = _dispatch_id(work, 'producer', attempt, 1)
        verifier_dispatch = _dispatch_id(work, 'verifier', attempt, 1)
        pair = next((p for p in context.resources.records if isinstance(p, PairedReservationCommitV1)
                     and p.producer_dispatch_id == producer_dispatch), None)
        if pair is None:
            producer_payload = reconciliation_context(context, work, role='producer', feedback=feedback)
            producer_reservation = _reservation(work, agents['producer'], producer_payload, schema)
            verifier_reservation = _reservation(work, agents['verifier'], schema,
                extra_input_bytes=len(producer_payload) + context.inputs.exhaustive_policy.max_candidate_output_bytes)
            preview = context.resources.preview_pair(work.identity, attempt, producer_reservation, verifier_reservation)
            if not preview.allowed:
                reason = _resource_block_reason(context, preview)
                context.controller.block_run('resource', reason)
                return reason
            pair = context.resources.commit_pair(preview, producer_dispatch_id=producer_dispatch, verifier_dispatch_id=verifier_dispatch)
        for role, dispatch in (('producer', producer_dispatch), ('verifier', verifier_dispatch)):
            context.controller.append_once('dispatch_reserved', {'dispatch_id': dispatch, 'role': role,
                'output_artifact_key_id': work.identity, 'reservation_id': pair.identity})
        view = context.ledger.replay()
        recorded = [r for r in view.knowledge_artifacts.values() if r.work_item_id == work.identity and r.role == 'producer'
                    and any(c.identity == r.execution_capture_id and d == producer_dispatch for d, c in view.execution_captures.items())]
        try:
            producer = _capture(context, backend, work, 'producer', producer_dispatch, attempt, agents['producer'], schema,
                pair.producer_reservation, None, feedback)
            candidate = _read(context, recorded[0].artifact_id, KnowledgeReconciliationCandidateV1) if recorded else _artifact(
                context, work, producer, KnowledgeReconciliationCandidateV1)
        except Protocol28LifecycleError:
            state = replay_protocol_28(context.events.replay()).dispatches.get(producer_dispatch)
            if state and state.stage == 'captured':
                context.controller.append_once('candidate_rejected', {'dispatch_id': producer_dispatch,
                    'output_artifact_key_id': work.identity, 'reason_code': 'refused-reconciliation-producer'})
            _release_paired_verifier(context, pair, reason='producer_abandoned')
            raise
        except ValueError:
            state = replay_protocol_28(context.events.replay()).dispatches.get(producer_dispatch)
            if state and state.stage == 'captured':
                context.controller.append_once('candidate_rejected', {'dispatch_id': producer_dispatch,
                    'output_artifact_key_id': work.identity, 'reason_code': 'invalid-reconciliation-candidate'})
            _release_paired_verifier(context, pair, reason='producer_contract_failure')
            continue
        review = verifier = None
        for verifier_attempt in (1, 2):
            dispatch = _dispatch_id(work, 'verifier', attempt, verifier_attempt)
            if verifier_attempt == 2 and dispatch not in replay_protocol_28(context.events.replay()).dispatches:
                preview = context.resources.preview_verifier_retry(work.identity, attempt, pair.verifier_reservation)
                if not preview.allowed:
                    context.controller.block_run('resource', _resource_block_reason(context, preview))
                    return 'reconciliation-verifier-resource-exhausted'
                retry = context.resources.commit_verifier_retry(preview, dispatch_id=dispatch)
                context.controller.append_once('dispatch_reserved', {'dispatch_id': dispatch, 'role': 'verifier',
                    'output_artifact_key_id': work.identity, 'reservation_id': retry.identity})
            try:
                verifier = _capture(context, backend, work, 'verifier', dispatch, verifier_attempt, agents['verifier'], schema,
                    pair.verifier_reservation, candidate, ())
                view = context.ledger.replay()
                recorded = next((r for r in view.knowledge_artifacts.values() if r.execution_capture_id == verifier.capture.identity), None)
                review = _read(context, recorded.artifact_id, KnowledgeReconciliationReviewV1) if recorded else _artifact(
                    context, work, verifier, KnowledgeReconciliationReviewV1, candidate)
                break
            except ValueError:
                state = replay_protocol_28(context.events.replay()).dispatches.get(dispatch)
                if state and state.stage == 'captured':
                    context.controller.append_once('verification_rejected', {'dispatch_id': dispatch,
                        'output_artifact_key_id': work.identity, 'reason_code': 'invalid-reconciliation-review'})
        if review is None:
            return _fail(context, work, 'reconciliation-review-attempts-exhausted')
        if review.verdict == 'REPAIR':
            feedback = tuple(row for row in review.checks if row.disposition != 'supported')
            # Outcome/grounding fingerprint excludes wording, candidate and attempt IDs.
            fingerprint = content_digest([{'check': row.check, 'disposition': row.disposition,
                'evidence_ids': row.evidence_ids, 'result_ids': row.result_ids, 'debt_candidate_ids': row.debt_candidate_ids}
                for row in sorted(feedback, key=lambda row: row.check)])
            packet = KnowledgeReconciliationFeedbackV1(1, work.identity, review.identity, fingerprint, _sorted(feedback))
            _put(context, packet)
            context.controller.append_once('knowledge_feedback_recorded', {'work_item_id': work.identity,
                'feedback_id': packet.identity, 'fingerprint_id': fingerprint})
            if fingerprint == last_fingerprint:
                return _fail(context, work, 'unchanged-reconciliation-outcome')
            last_fingerprint = fingerprint
            continue
        validate_reconciliation_review(work, candidate, review)
        if candidate.debt_candidates:
            from harness.re_v2.protocol_28.debt import validate_debt_candidate
            try:
                for debt in candidate.debt_candidates:
                    validate_debt_candidate(context, debt, active)
                    if not set(debt.obligation_ids).issubset(work.obligation_ids):
                        raise ValueError('debt-outside-reviewed-work')
            except ValueError:
                return _fail(context, work, 'ineligible-dependency-debt')
        from harness.re_v2.protocol_28.debt import reviewed_debt_closure
        try:
            for resolution in getattr(candidate, 'debt_resolutions', ()):
                reviewed_debt_closure(context, active, work, resolution, review)
        except ValueError:
            return _fail(context, work, 'invalid-debt-resolution')
        root = _build_root(context, active, work, candidate, review, producer, verifier)
        _put(context, root)
        context.ledger.record_knowledge_root(root)
        context.controller.record_knowledge_root(root)
        return root
    return _fail(context, work, 'reconciliation-attempts-exhausted')


def _fail(context, work, reason):
    context.controller.append_once('slice_failed', {'output_artifact_key_id': work.identity, 'reason_code': reason})
    context.controller.block_run('execution', reason)
    return reason


def _build_root(context, active, work, candidate, review, producer, verifier):
    from harness.re_v2.protocol_28.debt import KnowledgeDebtItemV1, ReviewedKnowledgeDebtAcceptanceV1, accepted_debt_ids
    acceptances = set(work.inherited_debt_acceptance_ids)
    from harness.re_v2.protocol_28.debt import reviewed_debt_closure
    for resolution in getattr(candidate, 'debt_resolutions', ()):
        _put(context, resolution)
        _put(context, reviewed_debt_closure(context, active, work, resolution, review))
        acceptances.remove(resolution.acceptance_id)
    if candidate.debt_candidates:
        items = []
        for debt in candidate.debt_candidates:
            _put(context, debt)
            item = KnowledgeDebtItemV1(1, debt.identity, review.identity, active.authorization.identity,
                work.identity, work.revision_id, debt.obligation_ids)
            _put(context, item)
            items.append(item)
        acceptance = ReviewedKnowledgeDebtAcceptanceV1(1, work.logical_run_id, work.snapshot_id,
            tuple(sorted({i for d in candidate.debt_candidates for i in d.obligation_ids})), tuple(sorted(i.identity for i in items)),
            tuple(sorted(d.identity for d in candidate.debt_candidates)), (review.identity,), active.authorization.identity)
        _put(context, acceptance)
        acceptances.add(acceptance.identity)
    debt_ids = tuple(sorted({i for key in acceptances for i in accepted_debt_ids(context, key, work.source_id)}))
    return KnowledgeReconciliationRootV1(1, work.logical_run_id, work.snapshot_id, work.revision_id, work.authorization_id,
        work.scope, work.source_id, work.target_kind, work.target_id, work.plan_id, work.identity, work.obligation_ids,
        work.input_result_ids, candidate.identity, review.identity, producer.capture.identity, verifier.capture.identity,
        tuple(sorted(acceptances)), debt_ids)


def build_reviewed_run_root(context, targets, sources):
    from harness.re_v2.knowledge_revision import load_knowledge_revision
    from harness.re_v2.protocol_28.events import replay_protocol_28
    active = load_knowledge_revision(context)
    plan = context.inputs.exhaustive_plan
    if ({r.plan_id for r in targets} != {t.identity for t in plan.target_plans} or len(targets) != len(plan.target_plans)
            or {r.source_id for r in sources} != {t.source_id for t in plan.target_plans}
            or len(sources) != len({t.source_id for t in plan.target_plans})
            or any(r.scope != 'target' for r in targets) or any(r.scope != 'source' for r in sources)):
        raise ValueError('incomplete-reviewed-run-root-closure')
    state = replay_protocol_28(context.events.replay())
    return ReviewedKnowledgeRunRootV1(1, active.manifest.logical_run_id, active.authorization.snapshot_id,
        active.manifest.revision_id, active.manifest.identity, active.authorization.identity, plan.identity,
        tuple(sorted(row.obligation_id for row in active.dependencies.obligations)), tuple(sorted(r.identity for r in targets)),
        tuple(sorted(r.identity for r in sources)), tuple(sorted(state.accepted_slices.values())),
        tuple(sorted({i for r in sources for i in r.debt_acceptance_ids})), tuple(sorted({i for r in sources for i in r.debt_ids})))


def _frozen_authority(objects, manifest_id, state):
    """Replay-local cache only: no authority survives a fresh storage replay."""
    from harness.re_v2.knowledge_revision import _RevisionReads, load_knowledge_authorities
    if not state.knowledge_authorities:
        state.knowledge_authorities.update(objects.authorities if isinstance(objects, _RevisionReads)
            else load_knowledge_authorities(objects))
    if manifest_id not in state.knowledge_authorities:
        raise ValueError('reconciliation-requires-committed-revision-manifest')
    return state.knowledge_authorities[manifest_id]


def _compatible_result(objects, state, active, result_id, origin_manifest_id):
    """Every retained historical result crosses exact committed compatibility receipts."""
    from harness.re_v2.knowledge_revision import KnowledgeResultCompatibilityV1, _read
    _frozen_authority(objects, origin_manifest_id, state)
    current = active
    while current.manifest.identity != origin_manifest_id:
        receipts = [_read(objects, key, KnowledgeResultCompatibilityV1)
            for key in current.manifest.compatibility_receipt_ids]
        if len([r for r in receipts if r.result_id == result_id]) != 1 or current.manifest.previous_manifest_id is None:
            raise ValueError('reconciliation-requires-explicit-revision-compatibility')
        _, current = _frozen_authority(objects, current.manifest.previous_manifest_id, state)


def authenticate_knowledge_record(objects, model, state):
    """Recompute work, captures, review and exact debt/root closure without writes."""
    from harness.re_v2.protocol_28.execution import parse_captured_result, PersistedL4ExecutionV1
    from harness.re_v2.protocol_28.debt import (KnowledgeDebtItemV1, ReviewedKnowledgeDebtAcceptanceV1,
        validate_debt_candidate, inherited_residual_debt, inherited_knowledge_debt_ids, accepted_debt_ids)
    from harness.re_v2.knowledge_revision import _read, _bundles
    if type(model) is KnowledgeReconciliationWorkItemV1:
        context, active = _frozen_authority(objects, model.revision_manifest_id, state)
        inputs = context.inputs
        plans = {t.identity: t for t in inputs.exhaustive_plan.target_plans}
        target = plans.get(model.plan_id)
        if (target is None or model.revision_id != active.manifest.revision_id
                or model.authorization_id != active.authorization.identity or model.logical_run_id != active.manifest.logical_run_id
                or model.snapshot_id != active.authorization.snapshot_id
                or (model.source_id, model.target_kind, model.target_id) != (target.source_id, target.target_kind, target.target_id)):
            raise ValueError('reconciliation-work-authority-mismatch')
        selected = [r for r in active.dependencies.obligations if r.source_id == target.source_id and
            (model.scope == 'source' or (r.target_kind, r.target_id) == (target.target_kind, target.target_id))]
        obligations = tuple(sorted(r.obligation_id for r in selected))
        categories = tuple(sorted(r.identity for b in _bundles(inputs, context.objects) for r in b.category_assessments if r.obligation_id in obligations))
        if (model.obligation_ids != obligations or not obligations or model.category_assessment_ids != categories
                or model.evidence_ids != tuple(sorted({i for r in selected for i in r.evidence_ids}))):
            raise ValueError('inexact-reconciliation-required-work')
        if model.scope == 'target':
            accepted = {r.identity: r for r in state.accepted_slices.values()}
            lower = [accepted[i] for i in model.input_result_ids]
            if len(lower) != len(target.entries) or {r.plan_entry_id for r in lower} != {e.identity for e in target.entries}:
                raise ValueError('inexact-reconciliation-slice-closure')
            from harness.re_v2.knowledge_revision import KnowledgeSliceWorkV1
            from harness.re_v2.protocol_28.planning import SliceSpecV1
            for row in lower:
                spec = _read(objects, row.slice_spec_id, SliceSpecV1)
                origin = _read(objects, spec.output_artifact_key_id, KnowledgeSliceWorkV1)
                ancestors = [a for _, a in state.knowledge_authorities.values() if a.manifest.revision_id == origin.revision_id]
                if len(ancestors) != 1 or origin.plan_entry_id != row.plan_entry_id:
                    raise ValueError('slice-requires-committed-revision-lineage')
                _compatible_result(objects, state, active, row.identity, ancestors[0].manifest.identity)
            residual = inherited_residual_debt(context, model.source_id)
            inherited = tuple(sorted({*((residual.acceptance_id,) if residual else ()),
                *inherited_knowledge_debt_ids(active, obligations)}))
        else:
            lower = [state.knowledge_roots[i] for i in model.input_result_ids]
            expected = {p.identity for p in plans.values() if p.source_id == target.source_id}
            if (len(lower) != len(expected) or {r.plan_id for r in lower} != expected
                    or any(r.scope != 'target' or r.source_id != model.source_id for r in lower)):
                raise ValueError('inexact-reconciliation-target-closure')
            for row in lower:
                _compatible_result(objects, state, active, row.identity, state.knowledge_work[row.work_item_id].revision_manifest_id)
            if {i for r in lower for i in r.obligation_ids} != set(obligations):
                raise ValueError('inexact-reconciliation-lower-obligation-union')
            inherited = tuple(sorted({i for r in lower for i in r.debt_acceptance_ids}))
        if model.inherited_debt_acceptance_ids != inherited or model.canonical_context_bytes != 0 or model.conservative_tokens != 0:
            raise ValueError('reconciliation-inherited-authority-mismatch')
        return
    if type(model) is KnowledgeReconciliationExecutionReceiptV1:
        work = state.knowledge_work[model.work_item_id]
        envelope, capture = state._capture_by_hash(model.execution_capture_id)
        cls = KnowledgeReconciliationCandidateV1 if model.role == 'producer' else KnowledgeReconciliationReviewV1
        artifact = _read(objects, model.artifact_id, cls)
        raw = parse_captured_result(objects, capture, validate_provider_output)
        if (capture.result_kind != 'provider_result' or model.role != envelope.role or
                (envelope.slice_spec_id, envelope.plan_entry_id) != (work.identity, work.identity)
                or cls.from_json_dict(json.loads(raw)) != artifact):
            raise ValueError('reconciliation-artifact-capture-mismatch')
        context, active = _frozen_authority(objects, work.revision_manifest_id, state)
        if len(raw) > context.inputs.exhaustive_policy.max_candidate_output_bytes:
            raise ValueError('reconciliation-artifact-bound')
        agent = objects.read_blob(active.authorization.reconciler_contract_id)
        if envelope.agent_contract_hash != content_digest(_role_agent(agent, model.role)):
            raise ValueError('reconciliation-agent-authority-mismatch')
        supplied = json.loads(validate_provider_output(objects.read_blob(envelope.context_bundle_hash)))
        if supplied['work_item'] != json.loads(canonical_json_bytes(work.to_json_dict())) or supplied['role'] != model.role:
            raise ValueError('reconciliation-capture-context-mismatch')
        if model.role == 'producer':
            validate_reconciliation_candidate(work, artifact)
            if envelope.candidate_id is not None or supplied['candidate'] is not None:
                raise ValueError('reconciliation-producer-cannot-review-itself')
            candidate = None
            feedback = ()
            reviews = [r for r in state.knowledge_artifacts.values() if r.work_item_id == work.identity and r.role == 'verifier']
            if reviews:
                previous_review = _read(objects, reviews[-1].artifact_id, KnowledgeReconciliationReviewV1)
                if previous_review.verdict == 'REPAIR':
                    feedback = tuple(r for r in previous_review.checks if r.disposition != 'supported')
        else:
            candidate = _read(objects, artifact.candidate_id, KnowledgeReconciliationCandidateV1)
            if not any(r.artifact_id == candidate.identity and r.role == 'producer' for r in state.knowledge_artifacts.values()):
                raise ValueError('review-requires-preceding-captured-candidate')
            if envelope.candidate_id != candidate.identity or supplied['candidate'] != json.loads(canonical_json_bytes(candidate.to_json_dict())):
                raise ValueError('review-capture-candidate-mismatch')
            validate_reconciliation_review(work, candidate, artifact)
            feedback = ()
        expected_context = _reconciliation_context(context, active, state, work, role=model.role,
            candidate=candidate, feedback=feedback)
        if content_digest(expected_context) != envelope.context_bundle_hash:
            raise ValueError('reconciliation-captured-context-is-not-exact-authority')
        if any(r.execution_capture_id == model.execution_capture_id and r != model for r in state.knowledge_artifacts.values()):
            raise ValueError('conflicting-reconciliation-artifact-capture')
        return
    if type(model) is KnowledgeReconciliationRootV1:
        work = state.knowledge_work[model.work_item_id]
        context, active = _frozen_authority(objects, work.revision_manifest_id, state)
        candidate = _read(objects, model.candidate_id, KnowledgeReconciliationCandidateV1)
        review = _read(objects, model.review_id, KnowledgeReconciliationReviewV1)
        validate_reconciliation_review(work, candidate, review)
        if review.verdict == 'REPAIR':
            raise ValueError('unfinished-reconciliation-cannot-root')
        for role, artifact_id, capture_id in (('producer', candidate.identity, model.producer_capture_id),
                ('verifier', review.identity, model.reviewer_capture_id)):
            expected = KnowledgeReconciliationExecutionReceiptV1(1, work.identity, role, artifact_id, capture_id)
            if state.knowledge_artifacts.get(expected.identity) != expected:
                raise ValueError('root-requires-preceding-reviewed-captures')
        pe, pc = state._capture_by_hash(model.producer_capture_id)
        ve, vc = state._capture_by_hash(model.reviewer_capture_id)
        if (pe.dispatch_id == ve.dispatch_id or pe.context_bundle_hash == ve.context_bundle_hash
                or pe.provider_request_hash == ve.provider_request_hash):
            raise ValueError('reconciliation-review-is-not-independent')
        acceptance_ids = set(work.inherited_debt_acceptance_ids)
        from harness.re_v2.protocol_28.debt import reviewed_debt_closure, ReviewedKnowledgeDebtClosureV1
        for resolution in getattr(candidate, 'debt_resolutions', ()):
            expected_closure = reviewed_debt_closure(context, active, work, resolution, review)
            if (_read(objects, resolution.identity, KnowledgeDebtResolutionCandidateV1) != resolution
                    or _read(objects, expected_closure.identity, ReviewedKnowledgeDebtClosureV1) != expected_closure):
                raise ValueError('knowledge-debt-closure-authority-mismatch')
            acceptance_ids.remove(resolution.acceptance_id)
        if candidate.debt_candidates:
            items = []
            for debt in candidate.debt_candidates:
                validate_debt_candidate(context, debt, active)
                if not set(debt.obligation_ids).issubset(work.obligation_ids):
                    raise ValueError('debt-outside-reviewed-work')
                if _read(objects, debt.identity, KnowledgeDebtCandidateV1) != debt:
                    raise ValueError('debt-candidate-mismatch')
                item = KnowledgeDebtItemV1(1, debt.identity, review.identity, active.authorization.identity,
                    work.identity, work.revision_id, debt.obligation_ids)
                if _read(objects, item.identity, KnowledgeDebtItemV1) != item:
                    raise ValueError('debt-item-mismatch')
                items.append(item)
            acceptance = ReviewedKnowledgeDebtAcceptanceV1(1, work.logical_run_id, work.snapshot_id,
                tuple(sorted({i for d in candidate.debt_candidates for i in d.obligation_ids})), tuple(sorted(i.identity for i in items)),
                tuple(sorted(d.identity for d in candidate.debt_candidates)), (review.identity,), active.authorization.identity)
            if _read(objects, acceptance.identity, ReviewedKnowledgeDebtAcceptanceV1) != acceptance:
                raise ValueError('debt-acceptance-mismatch')
            acceptance_ids.add(acceptance.identity)
        debt_ids = tuple(sorted({i for key in acceptance_ids for i in accepted_debt_ids(context, key, work.source_id)}))
        expected = KnowledgeReconciliationRootV1(1, work.logical_run_id, work.snapshot_id, work.revision_id, work.authorization_id,
            work.scope, work.source_id, work.target_kind, work.target_id, work.plan_id, work.identity, work.obligation_ids,
            work.input_result_ids, candidate.identity, review.identity, pc.identity, vc.identity, tuple(sorted(acceptance_ids)), debt_ids)
        if model != expected or any(r.work_item_id == work.identity and r != model for r in state.knowledge_roots.values()):
            raise ValueError('reconciliation-root-closure-mismatch')
        return
    if type(model) is ReviewedKnowledgeRunRootV1:
        context, active = _frozen_authority(objects, model.revision_manifest_id, state)
        targets = [state.knowledge_roots[i] for i in model.target_root_ids]
        sources = [state.knowledge_roots[i] for i in model.source_root_ids]
        plan = context.inputs.exhaustive_plan
        if (len(targets) != len(plan.target_plans) or {r.plan_id for r in targets} != {t.identity for t in plan.target_plans}
                or len(sources) != len({t.source_id for t in plan.target_plans})
                or {r.source_id for r in sources} != {t.source_id for t in plan.target_plans}
                or any(r.scope != 'target' for r in targets) or any(r.scope != 'source' for r in sources)
                or {i for r in sources for i in r.input_result_ids} != set(model.target_root_ids)):
            raise ValueError('incomplete-reviewed-run-root')
        for row in (*targets, *sources):
            _compatible_result(objects, state, active, row.identity, state.knowledge_work[row.work_item_id].revision_manifest_id)
        required = {r.obligation_id for r in active.dependencies.obligations}
        if any({i for r in lower for i in r.obligation_ids} != required for lower in (targets, sources)):
            raise ValueError('inexact-run-root-lower-obligation-union')
        expected = ReviewedKnowledgeRunRootV1(1, active.manifest.logical_run_id, active.authorization.snapshot_id,
            active.manifest.revision_id, active.manifest.identity, active.authorization.identity, plan.identity,
            tuple(sorted(r.obligation_id for r in active.dependencies.obligations)), model.target_root_ids, model.source_root_ids,
            tuple(sorted({i for r in targets for i in r.input_result_ids})),
            tuple(sorted({i for r in sources for i in r.debt_acceptance_ids})), tuple(sorted({i for r in sources for i in r.debt_ids})))
        if model != expected:
            raise ValueError('reviewed-run-root-lineage-mismatch')
        return
    raise ValueError('unknown-knowledge-ledger-authority')
