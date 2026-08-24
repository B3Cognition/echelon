"""Narrow protocol-2.4 extension of the frozen shared RE v2 controller."""

from __future__ import annotations

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.protocol_22.artifacts import ContextBundleV1
from harness.re_v2.protocol_22.baseline import (
    CompactCandidateInputV1,
    CompactCertificationResultV2,
    Protocol22CertificationError,
)
from harness.re_v2.protocol_22.controller import (
    Protocol22Controller,
    Protocol22ControllerError,
    _artifact_failure,
    _fault,
    _runtime_for,
)
from harness.re_v2.protocol_22.execution import Committed
from harness.re_v2.protocol_22.model import WorkItemV2
from harness.re_v2.protocol_22.policies import policy_for
from harness.re_v2.protocol_22.schema import Protocol22SchemaError, load_canonical_object

from .artifacts import parse_l2_authorial_candidate


class Protocol24Controller(Protocol22Controller):
    """Inherit the shared run loop; specialize only L2 candidate certification."""

    def _materialize_accepted_l1(self) -> None:
        """Defer projections to the protocol-2.4 layer-aware materializer."""
        return None

    def _certify_provider_candidate(
        self,
        item: WorkItemV2,
        committed: Committed,
        candidate_id: str,
    ) -> None:
        inventory = committed.closure.candidate_inventory
        entry = (
            inventory.entries[0]
            if inventory is not None and len(inventory.entries) == 1
            else None
        )
        if (
            entry is None
            or entry.relative_path != "baseline.json"
            or entry.object_kind != "regular"
            or entry.content_hash is None
        ):
            self._reject_candidate_before_artifact(
                item,
                committed,
                candidate_id,
                "candidate_tree_invalid",
            )
            return
        raw = self.context.object_store.read_blob(entry.content_hash)
        try:
            policy = policy_for(
                self.context.inputs.artifact_policy,
                item.output_key.layer,
                item.output_key.artifact_kind,
            )
            authorial = parse_l2_authorial_candidate(
                raw,
                item.output_key.artifact_kind,
                policy,
            )
        except (Protocol22CertificationError, Protocol22SchemaError):
            self._reject_candidate_before_artifact(
                item,
                committed,
                candidate_id,
                "authorial_schema_invalid",
            )
            return
        normalized_bytes = canonical_json_bytes(authorial.to_json_dict())
        normalized_hash = self.context.object_store.put_blob(normalized_bytes)
        candidate_input = CompactCandidateInputV1(
            candidate_id=candidate_id,
            execution_capture_hash=committed.closure.capture.identity,
            authorial_payload=authorial,
        )
        verifier = _runtime_for(
            self.context.verifiers,
            item.verifier_id,
            "compact verifier",
        )
        certify = getattr(verifier, "certify_candidate", None)
        if not callable(certify):
            raise Protocol22ControllerError(
                f"verifier {item.verifier_id} has no certify_candidate method"
            )
        context_hash = committed.closure.execution_input.context_bundle_hash
        if context_hash is None:
            raise Protocol22ControllerError(
                "provider candidate has no pinned context bundle"
            )
        context = load_canonical_object(
            self.context.object_store.read_blob(context_hash),
            ContextBundleV1.from_json_dict,
        )
        result = certify(candidate_input, item, context)
        if not isinstance(result, CompactCertificationResultV2):
            raise Protocol22ControllerError(
                "compact verifier returned no CompactCertificationResultV2"
            )
        if (
            result.candidate_assessment.normalized_authorial_payload_hash
            != normalized_hash
        ):
            raise Protocol22ControllerError(
                "candidate assessment normalized payload authority mismatch"
            )
        artifact_hash = self.context.object_store.put_blob(result.artifact_bytes)
        if artifact_hash != result.certification.certification_key.artifact_hash:
            raise Protocol22ControllerError(
                "compact certification artifact hash mismatch"
            )
        self.context.ledger.record_certification(result.certification, item)
        _fault(
            self.fault_hook,
            f"certification_receipt:{result.certification.identity}",
        )
        self.context.ledger.record_candidate_assessment(result.candidate_assessment)
        _fault(
            self.fault_hook,
            f"candidate_assessment:{result.candidate_assessment.identity}",
        )
        event_type = (
            "candidate_certified"
            if result.candidate_assessment.outcome == "certified"
            else "candidate_rejected"
        )
        self.context.event_store.append(
            event_type,
            {
                "candidate_assessment_id": result.candidate_assessment.identity,
                "candidate_id": candidate_id,
                "certification_receipt_id": result.certification.identity,
                "work_item_id": item.work_item_id,
            },
            occurred_at=self.context.clock(),
        )
        _fault(
            self.fault_hook,
            f"{event_type}:{result.candidate_assessment.identity}",
        )
        if result.certification.verdict == "accepted":
            self._accept_artifact(
                item,
                result.certification,
                result.candidate_assessment.identity,
            )
            return
        diagnostics = tuple(result.candidate_assessment.normalized_diagnostics)
        failure_class, reason_code = _artifact_failure(diagnostics)
        self._retry_or_fail_work_item(
            item,
            committed,
            candidate_id=candidate_id,
            candidate_assessment_id=result.candidate_assessment.identity,
            failure_class=failure_class,
            reason_code=reason_code,
            diagnostics=diagnostics,
        )


__all__ = ("Protocol24Controller",)
