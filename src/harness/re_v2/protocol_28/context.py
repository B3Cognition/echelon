"""Authenticated runtime contexts for published protocol-2.8 runs."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable, TypeAlias

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_evidence import screen_source_bytes
from harness.re_v2.events import EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_28.budget import L4ResourceStore
from harness.re_v2.protocol_28.controller import Protocol28Controller
from harness.re_v2.protocol_28.events import PROTOCOL_28_EVENTS
from harness.re_v2.protocol_28.inputs import (
    Protocol28InputError, _validate_input_subtype, _validated_objects,
    Protocol28CreationInputs,
    _PreliminarySafeProtocol28Inputs,
    SafeProtocol28CreationInputs,
    ValidatedProtocol28ClosureInputs,
    ValidatedProtocol28Inputs,
    ValidatedSafeProtocol28Inputs,
    ReviewedProtocol28CreationInputs, ValidatedReviewedProtocol28Inputs,
    load_protocol_28_inputs,
    residual_debt_acceptance_from_objects,
)
from harness.re_v2.protocol_28.ledger import Protocol28Ledger
from harness.re_v2.protocol_28.artifacts import (
    EvidenceAnchorV1,
    ExhaustiveDiagnosticV1,
    ExhaustiveEvidenceSliceV1,
)
from harness.re_v2.protocol_28.planning import (
    ExhaustiveTargetPlanV1,
    SlicePlanEntryV1,
    SliceSpecV1,
)
from harness.re_v2.run_store import ReV2Paths


class Protocol28ContextError(RuntimeError):
    """Raised when a protocol-2.8 runtime context cannot be authenticated."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_safe_free_text(value: object) -> None:
    """Fail closed on unscreened free text outside authenticated projections."""
    if isinstance(value, str):
        if screen_source_bytes(value.encode("utf-8")).disposition != "available":
            raise Protocol28ContextError("safe provider context failed screening")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key not in {"snapshot_evidence", "lower_authority_objects"}:
                _validate_safe_free_text(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_safe_free_text(item)


def _reviewed_structural_evidence(bundle) -> dict[str, object] | None:
    """Reproject authenticated discovery structure for detailed analysis."""
    from harness.re_v2.knowledge_activation import ReviewedSubjectCatalogV1
    from harness.re_v2.knowledge_structure import (
        StructuralEvidenceCatalogV1,
        project_structural_overview,
    )

    try:
        subject_catalog = ReviewedSubjectCatalogV1.from_json_dict(
            json.loads(bundle.objects[bundle.authority.subject_catalog_id])
        )
        proof = json.loads(bundle.objects[subject_catalog.replay_proof_id])
        catalog_id = proof.get("structural_catalog_id")
        if catalog_id is None:
            return None
        catalog = StructuralEvidenceCatalogV1.from_json_dict(
            json.loads(bundle.objects[catalog_id])
        )

        class BundleReader:
            def read_blob(self, object_id):
                payload = bundle.objects[object_id]
                if content_digest(payload) != object_id:
                    raise Protocol28ContextError(
                        "reviewed structural object hash mismatch"
                    )
                return payload

        limit = 25 if bundle.authority.depth == "quick" else 75 if bundle.authority.depth == "standard" else 100
        projection = project_structural_overview(
            catalog,
            BundleReader(),  # type: ignore[arg-type]
            bundle.authority.source_id,
            limit,
            persist=False,
        )
        return json.loads(projection.provider_bytes())
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise Protocol28ContextError(
            "reviewed structural evidence is invalid"
        ) from None


@dataclass(frozen=True, slots=True)
class _Protocol28SizingInputs:
    """Private manifest-free input for deterministic preactivation sizing only."""
    l3_projection_catalog: object
    snapshot_evidence_catalog: object
    exhaustive_subject_catalog: object
    exhaustive_policy: object
    authority_objects: object
    reviewed_discoveries: tuple | None = None


def _public_creation_type(inputs):
    creation_types = {
        Protocol28CreationInputs: Protocol28CreationInputs,
        ValidatedProtocol28Inputs: Protocol28CreationInputs,
        SafeProtocol28CreationInputs: SafeProtocol28CreationInputs,
        ValidatedSafeProtocol28Inputs: SafeProtocol28CreationInputs,
        ReviewedProtocol28CreationInputs: ReviewedProtocol28CreationInputs,
        ValidatedReviewedProtocol28Inputs: ReviewedProtocol28CreationInputs,
    }
    creation = creation_types.get(type(inputs))
    if creation is None:
        raise Protocol28ContextError('provider context requires exact validated public inputs')
    return creation


def _validated_public_inputs(inputs):
    """Reauthenticate exact public authority, with no sizing/preliminary cases."""
    creation = _public_creation_type(inputs)
    try:
        _validate_input_subtype(inputs)
        return creation(**{item.name: getattr(inputs, item.name) for item in fields(creation)})
    except (Protocol28InputError, AttributeError, ValueError) as exc:
        raise Protocol28ContextError('provider context requires authenticated public manifest subtype') from exc


def _initialize_context_indexes(context, inputs, safe_evidence, safe_lower_authority, reviewed):
    evidence = inputs.snapshot_evidence_catalog
    values = {
        '_reviewed_discoveries': reviewed,
        '_l3_projection_by_id': {item.identity: item for item in inputs.l3_projection_catalog.projections},
        '_evidence_projection_by_id': {item.identity: item for item in evidence.projections},
        '_evidence_object_by_id': {item.identity: item for item in
            (*evidence.shards, *evidence.empty_receipts, *evidence.nontext_dispositions)},
        '_safe_evidence_object_by_raw_id': {item.raw_evidence_id: item for item in safe_evidence.objects} if safe_evidence is not None else {},
        '_uses_safe_evidence': safe_evidence is not None,
        '_safe_lower_authority_by_raw_id': {item.raw_authority_id: item for item in safe_lower_authority.objects} if safe_lower_authority is not None else {},
        '_uses_safe_lower_authority': safe_lower_authority is not None,
        '_subject_by_id': {item.identity: item for item in inputs.exhaustive_subject_catalog.subjects},
        '_encoded_lower_authority_by_id': {},
    }
    for name, value in values.items():
        object.__setattr__(context, name, value)


class _Protocol28SizingContext:
    """Authenticated preactivation material, never a public provider context."""
    def __init__(self, inputs, plan, safe_evidence=None, safe_lower_authority=None):
        from harness.re_v2.knowledge_activation import (
            load_reviewed_discovery, build_reviewed_discovery_catalog, validate_reviewed_discovery_catalog,
        )
        from harness.re_v2.protocol_28.safe_evidence import (
            validate_safe_snapshot_evidence_catalog, validate_safe_lower_authority_catalog,
        )
        if type(inputs) is not _Protocol28SizingInputs:
            raise Protocol28ContextError('invalid internal sizing material')
        reviewed = inputs.reviewed_discoveries
        if ((safe_evidence is None) != (safe_lower_authority is None)
                or reviewed is not None and safe_evidence is None):
            raise Protocol28ContextError('reviewed sizing requires both authenticated safe catalogues')
        try:
            objects = _validated_objects(inputs.authority_objects)
            if reviewed is not None:
                checked = tuple(load_reviewed_discovery(bundle.authority, bundle.objects,
                    inputs.l3_projection_catalog, inputs.snapshot_evidence_catalog) for bundle in reviewed)
                catalog = build_reviewed_discovery_catalog(checked)
                reviewed = validate_reviewed_discovery_catalog(catalog,
                    {key: payload for bundle in checked for key, payload in bundle.objects.items()},
                    inputs.l3_projection_catalog, inputs.snapshot_evidence_catalog, inputs.exhaustive_subject_catalog)
            if safe_evidence is not None:
                validate_safe_snapshot_evidence_catalog(safe_evidence, inputs.snapshot_evidence_catalog)
                required = {key for target in plan.target_plans for entry in target.entries for key in entry.required_lower_authority_ids}
                validate_safe_lower_authority_catalog(safe_lower_authority, objects, tuple(sorted(required)))
        except (Protocol28InputError, ValueError, KeyError, AttributeError, TypeError) as exc:
            raise Protocol28ContextError('invalid authenticated reviewed/safe sizing material') from exc
        self.inputs = replace(inputs, authority_objects=objects, reviewed_discoveries=reviewed)
        _initialize_context_indexes(self, self.inputs, safe_evidence, safe_lower_authority, reviewed)
        for key in {key for target in plan.target_plans for entry in target.entries for key in entry.required_lower_authority_ids}:
            self._encoded_lower_authority_by_id[key] = _encode_lower_authority(self, key)


@dataclass(frozen=True, slots=True)
class Protocol28RunContext:
    paths: ReV2Paths
    inputs: ValidatedProtocol28Inputs
    objects: ObjectStore
    events: EventStore
    ledger: Protocol28Ledger
    resources: L4ResourceStore
    controller: Protocol28Controller
    safe_evidence_catalog_override: object | None = field(
        default=None, repr=False, compare=False
    )
    safe_lower_authority_catalog_override: object | None = field(
        default=None, repr=False, compare=False
    )
    _l3_projection_by_id: dict[str, object] = field(
        init=False, repr=False, compare=False
    )
    _evidence_projection_by_id: dict[str, object] = field(
        init=False, repr=False, compare=False
    )
    _evidence_object_by_id: dict[str, object] = field(
        init=False, repr=False, compare=False
    )
    _safe_evidence_object_by_raw_id: dict[str, object] = field(
        init=False, repr=False, compare=False
    )
    _uses_safe_evidence: bool = field(init=False, repr=False, compare=False)
    _safe_lower_authority_by_raw_id: dict[str, object] = field(
        init=False, repr=False, compare=False
    )
    _uses_safe_lower_authority: bool = field(init=False, repr=False, compare=False)
    _subject_by_id: dict[str, object] = field(
        init=False, repr=False, compare=False
    )
    _encoded_lower_authority_by_id: dict[str, dict[str, object]] = field(
        init=False, repr=False, compare=False
    )
    _reviewed_discoveries: tuple | None = field(init=False, repr=False, compare=False)
    _authenticated_inputs: object = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        inputs = self.inputs
        if isinstance(inputs, _PreliminarySafeProtocol28Inputs):
            raise Protocol28ContextError(
                "preliminary Safe authority cannot enter a provider context"
            )
        inputs = _validated_public_inputs(inputs)
        if self.safe_evidence_catalog_override is not None or self.safe_lower_authority_catalog_override is not None:
            raise Protocol28ContextError('public provider contexts forbid sizing overrides')
        evidence = inputs.snapshot_evidence_catalog
        reviewed = None
        if isinstance(inputs, (ReviewedProtocol28CreationInputs, ValidatedReviewedProtocol28Inputs)):
            from harness.re_v2.knowledge_activation import validate_reviewed_discovery_catalog
            reviewed = validate_reviewed_discovery_catalog(inputs.reviewed_discovery_catalog,
                inputs.authority_objects, inputs.l3_projection_catalog, evidence, inputs.exhaustive_subject_catalog)
        safe_evidence = (
            inputs.safe_snapshot_evidence_catalog
            if isinstance(
                inputs,
                (SafeProtocol28CreationInputs, ValidatedSafeProtocol28Inputs),
            )
            else None
        )
        safe_lower_authority = (
            inputs.safe_lower_authority_catalog
            if isinstance(
                inputs,
                (SafeProtocol28CreationInputs, ValidatedSafeProtocol28Inputs),
            )
            else None
        )
        _initialize_context_indexes(self, inputs, safe_evidence, safe_lower_authority, reviewed)
        object.__setattr__(self, '_authenticated_inputs', self.inputs)

    @property
    def run_dir(self) -> Path:
        return self.paths.root.parent


@dataclass(frozen=True, slots=True)
class Protocol28ClosureRunContext:
    paths: ReV2Paths
    inputs: ValidatedProtocol28ClosureInputs
    objects: ObjectStore
    events: EventStore
    ledger: Protocol28Ledger
    controller: Protocol28Controller

    @property
    def run_dir(self) -> Path:
        return self.paths.root.parent


Protocol28Context: TypeAlias = Protocol28RunContext | Protocol28ClosureRunContext


def build_protocol_28_slice_context(
    context: Protocol28RunContext,
    target_plan: ExhaustiveTargetPlanV1,
    plan_entry: SlicePlanEntryV1,
    slice_spec: SliceSpecV1,
    *,
    role: str,
    candidate: ExhaustiveEvidenceSliceV1 | None = None,
    repair_diagnostic_ids: tuple[str, ...] = (),
    repair_diagnostics: tuple[ExhaustiveDiagnosticV1, ...] = (),
    producer_contract_failure_codes: tuple[str, ...] = (),
    producer_attempt_number: int = 1,
    verifier_attempt_number: int | None = None,
    _enforce_bound: bool = True,
) -> bytes:
    """Build one role-local context solely from the published child store."""
    if type(context) is not Protocol28RunContext:
        raise Protocol28ContextError('slice context requires an exact public exhaustive run')
    # Only the exact immutable input instance authenticated by the public
    # constructor may use its indexes. Sizing/preliminary material has no route.
    if context.inputs is not getattr(context, '_authenticated_inputs', None):
        raise Protocol28ContextError('public context input is not its authenticated authority')
    _public_creation_type(context.inputs)
    try:
        _validate_input_subtype(context.inputs)
    except (Protocol28InputError, AttributeError) as exc:
        raise Protocol28ContextError('public renderer requires a validated input subtype') from exc
    for key in plan_entry.required_lower_authority_ids:
        if key not in context._encoded_lower_authority_by_id:
            context._encoded_lower_authority_by_id[key] = _encode_lower_authority(context, key)
    encoded = _serialize_protocol_28_slice_context(context, target_plan, plan_entry, slice_spec,
        role=role, candidate=candidate, repair_diagnostic_ids=repair_diagnostic_ids,
        repair_diagnostics=repair_diagnostics, producer_contract_failure_codes=producer_contract_failure_codes,
        producer_attempt_number=producer_attempt_number, verifier_attempt_number=verifier_attempt_number,
        _enforce_bound=_enforce_bound)
    if context.events is not None and any(e.type in {'knowledge_workflow_activated', 'knowledge_revision_activated'}
            for e in context.events.replay()):
        from harness.re_v2.knowledge_revision import load_knowledge_revision
        from harness.re_v2.protocol_28.debt import knowledge_slice_debt
        active = load_knowledge_revision(context)
        inherited = knowledge_slice_debt(context, active, plan_entry.identity)
        if inherited:
            payload = json.loads(encoded)
            payload['inherited_knowledge_debt'] = inherited
            payload['input_quality'] = 'partial'
            _validate_safe_free_text(payload)
            encoded = canonical_json_bytes(payload)
            maximum = context.inputs.exhaustive_policy.max_context_bytes + (
                context.inputs.exhaustive_policy.max_candidate_output_bytes if role == 'verifier' else 0)
            if _enforce_bound and len(encoded) > maximum:
                raise Protocol28ContextError('inherited debt exceeds frozen slice context bound')
    return encoded


def _serialize_protocol_28_slice_context(
    context, target_plan, plan_entry, slice_spec, *, role,
    candidate=None, repair_diagnostic_ids=(), repair_diagnostics=(),
    producer_contract_failure_codes=(), producer_attempt_number=1,
    verifier_attempt_number=None, _enforce_bound=True,
) -> bytes:
    """Pure canonical encoding shared by authenticated sizing and public paths."""
    if type(context) not in (Protocol28RunContext, _Protocol28SizingContext):
        raise Protocol28ContextError('canonical encoding requires authenticated context material')
    if role not in {"producer", "verifier"}:
        raise Protocol28ContextError("slice context role must be producer or verifier")
    if (
        not isinstance(target_plan, ExhaustiveTargetPlanV1)
        or not isinstance(plan_entry, SlicePlanEntryV1)
        or not isinstance(slice_spec, SliceSpecV1)
        or plan_entry not in target_plan.entries
        or slice_spec.plan_entry_id != plan_entry.identity
    ):
        raise Protocol28ContextError("slice context does not match the frozen plan")
    if role == "producer" and candidate is not None:
        raise Protocol28ContextError("producer context cannot contain a candidate")
    if role == "verifier" and producer_contract_failure_codes:
        raise Protocol28ContextError(
            "verifier context cannot contain producer contract failures"
        )
    allowed_contract_failure_codes = frozenset(
        {
            "malformed-result-contract",
            "missing-primary-evidence-anchors",
            "unresolved-findings-not-addressed",
        }
    )
    if (
        not isinstance(producer_contract_failure_codes, tuple)
        or set(producer_contract_failure_codes) - allowed_contract_failure_codes
    ):
        raise Protocol28ContextError("producer contract failure codes are invalid")
    normalized_contract_failure_codes = tuple(
        sorted(set(producer_contract_failure_codes))
    )
    if role == "verifier" and not isinstance(candidate, ExhaustiveEvidenceSliceV1):
        raise Protocol28ContextError("verifier context requires an immutable candidate")
    if (
        not isinstance(producer_attempt_number, int)
        or isinstance(producer_attempt_number, bool)
        or not 1 <= producer_attempt_number <= 3
    ):
        raise Protocol28ContextError("producer attempt number must be in [1, 3]")
    if role == "producer" and verifier_attempt_number is not None:
        raise Protocol28ContextError("producer context cannot claim a verifier attempt")
    if role == "verifier" and verifier_attempt_number is None:
        verifier_attempt_number = 1
    if role == "verifier" and verifier_attempt_number not in {1, 2}:
        raise Protocol28ContextError("verifier attempt number must be 1 or 2")
    if any(
        not isinstance(item, ExhaustiveDiagnosticV1)
        for item in repair_diagnostics
    ):
        raise Protocol28ContextError("repair diagnostics are invalid")
    normalized_diagnostic_ids = tuple(
        sorted(set(repair_diagnostic_ids))
    )
    if repair_diagnostics and normalized_diagnostic_ids != tuple(
        item.identity for item in repair_diagnostics
    ):
        raise Protocol28ContextError(
            "repair diagnostic objects do not match their identities"
        )

    inputs = context.inputs
    l3 = context._l3_projection_by_id.get(plan_entry.target_l3_projection_id)
    evidence_projection = context._evidence_projection_by_id.get(
        plan_entry.target_evidence_projection_id
    )
    if l3 is None or evidence_projection is None:
        raise Protocol28ContextError("slice target authority is unavailable")
    subject_ids = {
        *plan_entry.primary_subject_ids,
        *plan_entry.supporting_subject_ids,
    }
    evidence_ids = {
        *plan_entry.primary_snapshot_evidence_ids,
        *plan_entry.supporting_snapshot_evidence_ids,
    }
    evidence_objects = tuple(
        sorted(
            (
                context._evidence_object_by_id[item_id]
                for item_id in evidence_ids
                if item_id in context._evidence_object_by_id
            ),
            key=lambda item: item.identity,
        )
    )
    if {item.identity for item in evidence_objects} != evidence_ids:
        raise Protocol28ContextError("slice evidence authority is incomplete")
    if context._uses_safe_evidence:
        provider_evidence_objects = tuple(
            sorted(
                (
                    context._safe_evidence_object_by_raw_id[item_id]
                    for item_id in evidence_ids
                    if item_id in context._safe_evidence_object_by_raw_id
                ),
                key=lambda item: item.identity,
            )
        )
        if {item.raw_evidence_id for item in provider_evidence_objects} != evidence_ids:
            raise Protocol28ContextError("slice safe evidence authority is incomplete")
    else:
        provider_evidence_objects = evidence_objects
    permitted_anchors = tuple(
        sorted(
            (
                EvidenceAnchorV1(
                    1,
                    item.identity,
                    item.source_id,
                    item.source_relative_path,
                    getattr(item, "byte_start", 0),
                    getattr(item, "byte_end", getattr(item, "byte_count", 0)),
                    getattr(item, "raw_hash", item.file_content_hash),
                )
                for item in evidence_objects
            ),
            key=lambda item: item.identity,
        )
    )
    subjects = tuple(
        context._subject_by_id[item_id]
        for item_id in sorted(subject_ids)
        if item_id in context._subject_by_id
    )
    if {item.identity for item in subjects} != subject_ids:
        raise Protocol28ContextError("slice subject authority is incomplete")
    lower_objects: list[dict[str, object]] = []
    for object_id in plan_entry.required_lower_authority_ids:
        encoded_authority = context._encoded_lower_authority_by_id.get(object_id)
        if encoded_authority is None:
            raise Protocol28ContextError('slice requires authenticated encoded lower authority')
        lower_objects.append(encoded_authority)
    residual_debt = residual_debt_acceptance_from_objects(
        inputs.authority_objects
    )
    input_quality = "partial" if residual_debt is not None else "complete"
    payload: dict[str, object] = {
        "schema_version": 1,
        "role": role,
        "slice_spec_id": slice_spec.identity,
        "plan_entry_id": plan_entry.identity,
        "slice_spec": slice_spec.to_json_dict(),
        "plan_entry": plan_entry.to_json_dict(),
        "target_plan_id": target_plan.identity,
        "target_l3_projection": l3.to_json_dict(),
        "target_evidence_projection": _slice_evidence_projection(
            evidence_projection,
            evidence_ids,
        ),
        "subjects": [item.to_json_dict() for item in subjects],
        "snapshot_evidence": [
            item.to_json_dict() for item in provider_evidence_objects
        ],
        "permitted_evidence_anchors": [
            {"anchor_id": item.identity, "anchor": item.to_json_dict()}
            for item in permitted_anchors
        ],
        "lower_authority_objects": lower_objects,
        "input_quality": input_quality,
        "residual_debt_acceptance_hash": (
            None if residual_debt is None else residual_debt.identity
        ),
        "accepted_residual_debt": (
            None if residual_debt is None else residual_debt.to_json_dict()
        ),
        "residual_debt_disposition": (
            None
            if residual_debt is None
            else "accepted_not_closed_by_l4"
        ),
        "repair_diagnostic_ids": list(normalized_diagnostic_ids),
        "repair_diagnostics": [
            item.to_json_dict() for item in repair_diagnostics
        ],
        "finding_disposition_contract": {
            "addressed_finding_ids": "exactly plan_entry.assigned_finding_ids",
            "unresolved_finding_ids": "subset of addressed_finding_ids",
        },
        "producer_contract_failure_codes": list(
            normalized_contract_failure_codes
        ),
        "producer_attempt_number": producer_attempt_number,
        "verifier_attempt_number": verifier_attempt_number,
        "candidate_id": None if candidate is None else candidate.identity,
        "candidate": None if candidate is None else candidate.to_json_dict(),
    }
    if context._reviewed_discoveries is not None:
        bundle = next(b for b in context._reviewed_discoveries if b.authority.source_id == plan_entry.source_id)
        payload['reviewed_obligations'] = {
            'depth': bundle.authority.depth,
            'analysis_certified': False,
            'categories': [
                {'category_id': row.category_id, 'disposition': row.disposition,
                 'assessment_id': row.identity, 'subject_ids': list(row.subject_ids)}
                for row in bundle.category_assessments
                if (row.target_kind, row.target_id) == (plan_entry.target_kind, plan_entry.target_id)
            ],
            'limits': 'Reviewed planning inputs only; analysis and reconciliation remain required.',
        }
        structural_evidence = _reviewed_structural_evidence(bundle)
        if structural_evidence is not None:
            payload['structural_evidence'] = structural_evidence
    if context._uses_safe_evidence:
        _validate_safe_free_text(payload)
    encoded = canonical_json_bytes(payload)
    maximum = inputs.exhaustive_policy.max_context_bytes
    if role == "verifier":
        maximum += inputs.exhaustive_policy.max_candidate_output_bytes
    if _enforce_bound and len(encoded) > maximum:
        raise Protocol28ContextError(
            f"{role} slice context exceeds frozen byte bound: "
            f"source={plan_entry.source_id} target={plan_entry.target_id} "
            f"category={plan_entry.category_id} ordinal={plan_entry.ordinal} "
            f"actual={len(encoded)} maximum={maximum}"
        )
    return encoded


def _encode_lower_authority(context, object_id):
    payload = context.inputs.authority_objects.get(object_id)
    if payload is None:
        raise Protocol28ContextError(f'slice lower authority is unavailable: {object_id}')
    if context._uses_safe_lower_authority:
        safe_authority = context._safe_lower_authority_by_raw_id.get(object_id)
        if safe_authority is None:
            raise Protocol28ContextError('slice safe lower authority is incomplete')
        return safe_authority.to_provider_json_dict()
    return {'object_id': object_id, 'bytes_base64': base64.b64encode(payload).decode('ascii')}


def _slice_evidence_projection(
    projection,  # type: ignore[no-untyped-def]
    evidence_ids: set[str],
) -> dict[str, object]:
    """Project target-wide evidence authority down to one bounded slice."""
    return {
        "projection_id": projection.identity,
        "projection_scope": "slice",
        "schema_version": projection.schema_version,
        "target_kind": projection.target_kind,
        "source_id": projection.source_id,
        "target_id": projection.target_id,
        "target_partition_id": projection.target_partition_id,
        "target_content_id": projection.target_content_id,
        **{
            field: [
                item
                for item in getattr(projection, field)
                if item in evidence_ids
            ]
            for field in (
                "primary_shard_ids",
                "primary_empty_receipt_ids",
                "primary_nontext_disposition_ids",
                "supporting_shard_ids",
                "supporting_empty_receipt_ids",
                "supporting_nontext_disposition_ids",
            )
        },
    }


def load_protocol_28_run_context(
    run_dir: Path,
    *,
    clock: Callable[[], str] | None = None,
    fault: Callable[[str], None] | None = None,
) -> Protocol28Context:
    """Load only child-owned protocol-2.8 authority; never reopen live sources."""
    run_path = Path(run_dir)
    inputs = load_protocol_28_inputs(run_path)
    paths = ReV2Paths.for_run(run_path)
    objects = ObjectStore(paths.objects)
    events = EventStore(paths, protocol=PROTOCOL_28_EVENTS)
    ledger = Protocol28Ledger(paths.ledger, objects)
    controller = Protocol28Controller(
        events,
        objects,
        paths.projection,
        clock=clock or _now,
        fault=fault,
    )
    if isinstance(inputs, ValidatedProtocol28Inputs):
        resources = L4ResourceStore(
            paths.root / "resources.jsonl", inputs.manifest.budget_policy
        )
        context = Protocol28RunContext(
            paths, inputs, objects, events, ledger, resources, controller
        )
        from harness.re_v2.knowledge_revision import load_knowledge_revision, load_revision_inputs
        active = load_knowledge_revision(context)
        if active is not None:
            context = Protocol28RunContext(paths, load_revision_inputs(objects, active.manifest.inputs_id),
                objects, events, ledger, resources, controller)
        return context
    return Protocol28ClosureRunContext(
        paths, inputs, objects, events, ledger, controller
    )


def initialize_protocol_28_run(context: Protocol28Context) -> None:
    """Publish the exact initial event prefix once after manifest publication."""
    manifest = context.inputs.manifest
    if isinstance(context, Protocol28RunContext):
        from harness.re_v2.protocol_28.events import replay_protocol_28
        if replay_protocol_28(context.events.replay()).knowledge_authorization_id is not None:
            # Revision manifests supersede inputs, never the historical creation prefix.
            from harness.re_v2.knowledge_revision import load_knowledge_revision
            load_knowledge_revision(context)
            return
    controller = context.controller
    controller.append_once(
        "l4_run_created", {"run_manifest_id": manifest.run_manifest_id}
    )
    if isinstance(context, Protocol28ClosureRunContext):
        controller.append_once(
            "l4_closure_inputs_staged",
            {
                "closure_parent_bundle_id": (
                    context.inputs.closure_parent_bundle.identity
                ),
                "closure_run_manifest_id": manifest.run_manifest_id,
                "l4_run_root_id": context.inputs.l4_run_root.identity,
            },
        )
        return
    inputs = context.inputs
    planned = tuple(
        sorted(
            entry.identity
            for target in inputs.exhaustive_plan.target_plans
            for entry in target.entries
        )
    )
    controller.append_once(
        "l4_inputs_staged",
        {
            "coverage_proof_id": inputs.snapshot_evidence_catalog.identity,
            "exhaustive_plan_id": inputs.exhaustive_plan.identity,
            "parent_authority_bundle_id": inputs.parent_authority_bundle.identity,
            "snapshot_evidence_catalog_id": inputs.snapshot_evidence_catalog.identity,
            "target_projection_catalog_id": inputs.l3_projection_catalog.identity,
        },
    )
    controller.append_once(
        "l4_activated",
        {
            "activation_id": content_digest(
                {
                    "exhaustive_plan_id": inputs.exhaustive_plan.identity,
                    "run_manifest_id": manifest.run_manifest_id,
                }
            ),
            "planned_entry_ids": list(planned),
        },
    )


__all__ = (
    "Protocol28ClosureRunContext",
    "Protocol28Context",
    "Protocol28ContextError",
    "Protocol28RunContext",
    "build_protocol_28_slice_context",
    "initialize_protocol_28_run",
    "load_protocol_28_run_context",
)
