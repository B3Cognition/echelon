"""Append-only protocol-2.8 authority for exhaustive L4 slice acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.ledger import (
    DurableLedger,
    LedgerRecord,
    ObjectStore,
    ReV2LedgerError,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    load_canonical_object,
)
from harness.re_v2.protocol_28.artifacts import (
    ExhaustiveEvidenceSliceV1,
    ExhaustiveVerificationV1,
    Protocol28ArtifactError,
    normalize_candidate_result,
    normalize_verification_result,
)
from harness.re_v2.protocol_28.execution import (
    L4AcceptanceReceiptV1,
    L4CandidateReceiptV1,
    L4CertificationReceiptV1,
    L4ExecutionCaptureV1,
    L4ExecutionEnvelopeV1,
    L4VerificationReceiptV1,
    Protocol28ExecutionError,
    decode_provider_result_object,
    parse_captured_result,
)
from harness.re_v2.protocol_28.graph import AcceptedExhaustiveSliceV1
from harness.re_v2.protocol_28.planning import SlicePlanEntryV1, SliceSpecV1


_RECEIPT_DECODERS = {
    "l4_candidate": L4CandidateReceiptV1.from_json_dict,
    "l4_verification": L4VerificationReceiptV1.from_json_dict,
    "l4_certification": L4CertificationReceiptV1.from_json_dict,
    "l4_acceptance": L4AcceptanceReceiptV1.from_json_dict,
    "l4_accepted_slice": AcceptedExhaustiveSliceV1.from_json_dict,
}


@dataclass(frozen=True, slots=True)
class Protocol28LedgerView:
    execution_envelopes: Mapping[str, L4ExecutionEnvelopeV1]
    execution_captures: Mapping[str, L4ExecutionCaptureV1]
    candidate_receipts: Mapping[str, L4CandidateReceiptV1]
    verification_receipts: Mapping[str, L4VerificationReceiptV1]
    certifications: Mapping[str, L4CertificationReceiptV1]
    acceptances: Mapping[str, L4AcceptanceReceiptV1]
    accepted_slices: Mapping[str, AcceptedExhaustiveSliceV1]
    knowledge_work: Mapping[str, object]
    knowledge_artifacts: Mapping[str, object]
    knowledge_roots: Mapping[str, object]
    knowledge_run_roots: Mapping[str, object]


@dataclass(slots=True)
class _Protocol28LedgerState:
    execution_envelopes: dict[str, L4ExecutionEnvelopeV1]
    execution_captures: dict[str, L4ExecutionCaptureV1]
    candidate_receipts: dict[str, L4CandidateReceiptV1]
    verification_receipts: dict[str, L4VerificationReceiptV1]
    certifications: dict[str, L4CertificationReceiptV1]
    acceptances: dict[str, L4AcceptanceReceiptV1]
    accepted_slices: dict[str, AcceptedExhaustiveSliceV1]
    knowledge_work: dict[str, object]
    knowledge_artifacts: dict[str, object]
    knowledge_roots: dict[str, object]
    knowledge_run_roots: dict[str, object]
    knowledge_authorities: dict[str, object]

    @classmethod
    def empty(cls) -> "_Protocol28LedgerState":
        return cls({}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {})

    def consume(self, record: LedgerRecord, object_store: ObjectStore) -> None:
        try:
            if record.type == "l4_execution_capture":
                self._consume_capture(record, object_store)
            elif record.type == "l4_candidate":
                self._consume_candidate(
                    L4CandidateReceiptV1.from_json_dict(record.payload), object_store
                )
            elif record.type == "l4_verification":
                self._consume_verification(
                    L4VerificationReceiptV1.from_json_dict(record.payload), object_store
                )
            elif record.type == "l4_certification":
                self._consume_certification(
                    L4CertificationReceiptV1.from_json_dict(record.payload), object_store
                )
            elif record.type == "l4_acceptance":
                self._consume_acceptance(
                    L4AcceptanceReceiptV1.from_json_dict(record.payload), object_store
                )
            elif record.type == "l4_accepted_slice":
                self._consume_accepted_slice(
                    AcceptedExhaustiveSliceV1.from_json_dict(record.payload), object_store
                )
            elif record.type.startswith('knowledge_'):
                self._consume_knowledge(record, object_store)
            else:
                raise ReV2LedgerError(
                    f"unknown protocol-2.8 ledger record type: {record.type!r}"
                )
        except ReV2LedgerError:
            raise
        except (Protocol22SchemaError, Protocol28ExecutionError, TypeError, ValueError) as exc:
            raise ReV2LedgerError(f"invalid {record.type} authority: {exc}") from exc

    def _consume_knowledge(self, record, objects):
        from harness.re_v2.protocol_28.reconciliation import authenticate_knowledge_record
        model = _decode_receipt(record.type, record.payload)
        _verify_exact_object(objects, model)
        authenticate_knowledge_record(objects, model, self)
        mapping = getattr(self, {'knowledge_work': 'knowledge_work',
            'knowledge_artifact': 'knowledge_artifacts', 'knowledge_root': 'knowledge_roots',
            'knowledge_run_root': 'knowledge_run_roots'}[record.type])
        mapping[model.identity] = model

    def _consume_capture(self, record: LedgerRecord, object_store: ObjectStore) -> None:
        raw = exact_object(
            record.payload,
            frozenset({"execution_envelope_hash", "execution_capture_hash"}),
            "L4 execution capture record",
        )
        envelope_hash = digest_value(raw["execution_envelope_hash"], "execution_envelope_hash")
        capture_hash = digest_value(raw["execution_capture_hash"], "execution_capture_hash")
        envelope = _load(object_store, envelope_hash, L4ExecutionEnvelopeV1)
        capture = _load(object_store, capture_hash, L4ExecutionCaptureV1)
        object_store.verify(capture.raw_result_hash)
        if (
            capture.execution_envelope_id != envelope.identity
            or capture.dispatch_id != envelope.dispatch_id
            or capture.role != envelope.role
        ):
            raise ReV2LedgerError("execution capture does not authenticate its envelope")
        existing = self.execution_captures.get(envelope.dispatch_id)
        if existing is not None:
            if existing != capture or self.execution_envelopes[envelope.dispatch_id] != envelope:
                raise ReV2LedgerError("conflicting execution capture for dispatch")
            return
        self.execution_envelopes[envelope.dispatch_id] = envelope
        self.execution_captures[envelope.dispatch_id] = capture

    def _consume_candidate(
        self, receipt: L4CandidateReceiptV1, object_store: ObjectStore
    ) -> None:
        candidate = _load(object_store, receipt.candidate_hash, ExhaustiveEvidenceSliceV1)
        envelope, capture = self._capture_by_hash(receipt.producer_execution_capture_hash)
        if envelope.role != "producer":
            raise ReV2LedgerError("candidate requires a preceding producer capture")
        if capture.result_kind != "provider_result":
            raise ReV2LedgerError("candidate requires a successful producer result")
        try:
            raw_candidate = parse_captured_result(
                object_store, capture, decode_provider_result_object
            )
        except Protocol28ExecutionError as exc:
            raise ReV2LedgerError(
                f"producer result cannot authenticate candidate: {exc}"
            ) from exc
        try:
            normalized_candidate = normalize_candidate_result(raw_candidate)
        except Protocol28ArtifactError:
            slice_spec = _load(object_store, receipt.slice_spec_id, SliceSpecV1)
            plan_entry = _load(object_store, receipt.plan_entry_id, SlicePlanEntryV1)
            normalized_candidate = normalize_candidate_result(
                raw_candidate, slice_spec=slice_spec, plan_entry=plan_entry
            )
        if normalized_candidate != candidate:
            raise ReV2LedgerError("producer result does not contain candidate")
        if (
            candidate.identity != receipt.candidate_hash
            or candidate.slice_spec_id != receipt.slice_spec_id
            or candidate.plan_entry_id != receipt.plan_entry_id
            or envelope.slice_spec_id != receipt.slice_spec_id
            or envelope.plan_entry_id != receipt.plan_entry_id
            or capture.identity != receipt.producer_execution_capture_hash
        ):
            raise ReV2LedgerError("candidate authority disagrees with producer capture")
        existing = self.candidate_receipts.get(receipt.candidate_hash)
        if existing is not None and existing != receipt:
            raise ReV2LedgerError("conflicting candidate receipt")
        self.candidate_receipts[receipt.candidate_hash] = receipt

    def _consume_verification(
        self, receipt: L4VerificationReceiptV1, object_store: ObjectStore
    ) -> None:
        candidate_receipt = self.candidate_receipts.get(receipt.candidate_id)
        if candidate_receipt is None:
            raise ReV2LedgerError("verification requires a candidate preceding it")
        verification = _load(
            object_store, receipt.verifier_result_hash, ExhaustiveVerificationV1
        )
        envelope, capture = self._capture_by_hash(receipt.verifier_execution_capture_hash)
        if envelope.role != "verifier":
            raise ReV2LedgerError("verification requires a preceding verifier capture")
        if capture.result_kind != "provider_result":
            raise ReV2LedgerError("verification requires a successful verifier result")
        try:
            raw_verification = parse_captured_result(
                object_store, capture, decode_provider_result_object
            )
        except Protocol28ExecutionError as exc:
            raise ReV2LedgerError(
                f"verifier result cannot authenticate verification: {exc}"
            ) from exc
        if normalize_verification_result(raw_verification) != verification:
            raise ReV2LedgerError("verifier result does not contain verification")
        if (
            receipt.slice_spec_id != candidate_receipt.slice_spec_id
            or receipt.plan_entry_id != candidate_receipt.plan_entry_id
            or verification.identity != receipt.verifier_result_hash
            or verification.slice_spec_id != receipt.slice_spec_id
            or verification.candidate_id != receipt.candidate_id
            or verification.verdict != receipt.verdict
            or verification.verifier_policy_id != envelope.agent_contract_hash
            or envelope.slice_spec_id != receipt.slice_spec_id
            or envelope.plan_entry_id != receipt.plan_entry_id
            or envelope.candidate_id != receipt.candidate_id
            or capture.identity != receipt.verifier_execution_capture_hash
        ):
            raise ReV2LedgerError("verification authority disagrees with candidate or verifier capture")
        existing = self.verification_receipts.get(receipt.verifier_result_hash)
        if existing is not None and existing != receipt:
            raise ReV2LedgerError("conflicting verification receipt")
        self.verification_receipts[receipt.verifier_result_hash] = receipt

    def _consume_certification(
        self, receipt: L4CertificationReceiptV1, object_store: ObjectStore
    ) -> None:
        _verify_exact_object(object_store, receipt)
        candidate = self.candidate_receipts.get(receipt.candidate_hash)
        verification = self.verification_receipts.get(receipt.verifier_result_hash)
        if candidate is None or verification is None:
            raise ReV2LedgerError("certification requires preceding candidate and verification")
        if verification.verdict != "PASS":
            raise ReV2LedgerError("certification requires a PASS verification")
        producer_envelope, _producer_capture = self._capture_by_hash(
            receipt.producer_execution_capture_hash
        )
        verifier_envelope, _verifier_capture = self._capture_by_hash(
            receipt.verifier_execution_capture_hash
        )
        if (
            producer_envelope.dispatch_id == verifier_envelope.dispatch_id
            or producer_envelope.context_bundle_hash
            == verifier_envelope.context_bundle_hash
            or producer_envelope.provider_request_hash
            == verifier_envelope.provider_request_hash
        ):
            raise ReV2LedgerError(
                "certification requires a fresh independent context"
            )
        if (
            candidate.slice_spec_id != receipt.slice_spec_id
            or candidate.plan_entry_id != receipt.plan_entry_id
            or candidate.producer_execution_capture_hash != receipt.producer_execution_capture_hash
            or verification.slice_spec_id != receipt.slice_spec_id
            or verification.plan_entry_id != receipt.plan_entry_id
            or verification.candidate_id != receipt.candidate_hash
            or verification.verifier_execution_capture_hash != receipt.verifier_execution_capture_hash
        ):
            raise ReV2LedgerError("certification disagrees with preceding authority")
        existing = self.certifications.get(receipt.identity)
        if existing is not None and existing != receipt:
            raise ReV2LedgerError("conflicting certification receipt")
        self.certifications[receipt.identity] = receipt

    def _consume_acceptance(
        self, receipt: L4AcceptanceReceiptV1, object_store: ObjectStore
    ) -> None:
        _verify_exact_object(object_store, receipt)
        certification = self.certifications.get(receipt.certification_receipt_hash)
        if certification is None:
            raise ReV2LedgerError("acceptance requires a preceding certification")
        if (
            receipt.slice_spec_id != certification.slice_spec_id
            or receipt.output_artifact_key_id != certification.output_artifact_key_id
            or receipt.candidate_hash != certification.candidate_hash
        ):
            raise ReV2LedgerError("acceptance disagrees with certification")
        existing = self.acceptances.get(receipt.output_artifact_key_id)
        if existing is not None and existing != receipt:
            raise ReV2LedgerError("conflicting acceptance for output artifact key")
        self.acceptances[receipt.output_artifact_key_id] = receipt

    def _consume_accepted_slice(
        self, accepted: AcceptedExhaustiveSliceV1, object_store: ObjectStore
    ) -> None:
        _verify_exact_object(object_store, accepted)
        acceptance = self.acceptances.get(accepted.output_artifact_key_id)
        certification = self.certifications.get(accepted.certification_receipt_hash)
        if acceptance is None or certification is None:
            raise ReV2LedgerError("accepted slice requires preceding acceptance and certification")
        for object_hash in (
            accepted.candidate_hash,
            accepted.producer_execution_capture_hash,
            accepted.verifier_result_hash,
            accepted.verifier_execution_capture_hash,
            accepted.certification_receipt_hash,
            accepted.acceptance_receipt_hash,
        ):
            object_store.verify(object_hash)
        candidate = _load(
            object_store, accepted.candidate_hash, ExhaustiveEvidenceSliceV1
        )
        if accepted.addressed_finding_ids != candidate.addressed_finding_ids:
            raise ReV2LedgerError(
                "accepted slice addressed findings disagree with candidate"
            )
        if (
            acceptance.identity != accepted.acceptance_receipt_hash
            or acceptance.slice_spec_id != accepted.slice_spec_id
            or acceptance.candidate_hash != accepted.candidate_hash
            or certification.output_artifact_key_id != accepted.output_artifact_key_id
            or certification.plan_entry_id != accepted.plan_entry_id
            or certification.producer_execution_capture_hash
            != accepted.producer_execution_capture_hash
            or certification.verifier_result_hash != accepted.verifier_result_hash
            or certification.verifier_execution_capture_hash
            != accepted.verifier_execution_capture_hash
        ):
            raise ReV2LedgerError("accepted slice disagrees with controller receipts")
        existing = self.accepted_slices.get(accepted.output_artifact_key_id)
        if existing is not None and existing != accepted:
            raise ReV2LedgerError("conflicting accepted slice for output artifact key")
        self.accepted_slices[accepted.output_artifact_key_id] = accepted

    def _capture_by_hash(
        self, capture_hash: str
    ) -> tuple[L4ExecutionEnvelopeV1, L4ExecutionCaptureV1]:
        for dispatch_id, capture in self.execution_captures.items():
            if capture.identity == capture_hash:
                return self.execution_envelopes[dispatch_id], capture
        role = "producer" if not self.candidate_receipts else "verifier"
        raise ReV2LedgerError(f"{role} capture must precede dependent authority")

    def idempotent_record(
        self,
        history: tuple[LedgerRecord, ...],
        record_type: str,
        payload: Mapping[str, object],
    ) -> LedgerRecord | None:
        for record in history:
            if (
                record.type == record_type
                and record.to_json_dict()["payload"] == dict(payload)
            ):
                return record
        key, existing = self._key_and_existing(record_type, payload)
        if existing is not None:
            raise ReV2LedgerError(f"conflicting {record_type.replace('l4_', '').replace('_', ' ')} for {key}")
        return None

    def _key_and_existing(
        self, record_type: str, payload: Mapping[str, object]
    ) -> tuple[str, object | None]:
        if record_type == "l4_execution_capture":
            raw = exact_object(
                payload,
                frozenset({"execution_envelope_hash", "execution_capture_hash"}),
                "L4 execution capture record",
            )
            envelope_hash = digest_value(raw["execution_envelope_hash"], "execution_envelope_hash")
            # The envelope has already been authenticated during canonicalization only
            # after consume; use the capture identity to locate an exact prior pair.
            capture_hash = digest_value(raw["execution_capture_hash"], "execution_capture_hash")
            for dispatch_id, capture in self.execution_captures.items():
                if capture.identity == capture_hash and self.execution_envelopes[dispatch_id].identity == envelope_hash:
                    return dispatch_id, capture
            # Same dispatch conflict is caught by consume before append. There is no
            # safe dispatch key in this hash-only envelope at this stage.
            return capture_hash, None
        model = _decode_receipt(record_type, payload)
        if record_type.startswith('knowledge_'):
            return model.identity, None  # Exact replay was handled above; consume validates semantic uniqueness.
        if isinstance(model, L4CandidateReceiptV1):
            return model.candidate_hash, self.candidate_receipts.get(model.candidate_hash)
        if isinstance(model, L4VerificationReceiptV1):
            return model.verifier_result_hash, self.verification_receipts.get(model.verifier_result_hash)
        if isinstance(model, L4CertificationReceiptV1):
            return model.identity, self.certifications.get(model.identity)
        if isinstance(model, L4AcceptanceReceiptV1):
            return model.output_artifact_key_id, self.acceptances.get(model.output_artifact_key_id)
        if isinstance(model, AcceptedExhaustiveSliceV1):
            return model.output_artifact_key_id, self.accepted_slices.get(model.output_artifact_key_id)
        raise ReV2LedgerError(f"unknown protocol-2.8 ledger record type: {record_type!r}")

    def view(self) -> Protocol28LedgerView:
        return Protocol28LedgerView(
            execution_envelopes=MappingProxyType(dict(self.execution_envelopes)),
            execution_captures=MappingProxyType(dict(self.execution_captures)),
            candidate_receipts=MappingProxyType(dict(self.candidate_receipts)),
            verification_receipts=MappingProxyType(dict(self.verification_receipts)),
            certifications=MappingProxyType(dict(self.certifications)),
            acceptances=MappingProxyType(dict(self.acceptances)),
            accepted_slices=MappingProxyType(dict(self.accepted_slices)),
            knowledge_work=MappingProxyType(dict(self.knowledge_work)),
            knowledge_artifacts=MappingProxyType(dict(self.knowledge_artifacts)),
            knowledge_roots=MappingProxyType(dict(self.knowledge_roots)),
            knowledge_run_roots=MappingProxyType(dict(self.knowledge_run_roots)),
        )


class _Protocol28LedgerProtocol:
    def new_state(self) -> _Protocol28LedgerState:
        return _Protocol28LedgerState.empty()

    def canonical_payload(self, record_type: str, value: object) -> Mapping[str, object]:
        try:
            if record_type == "l4_execution_capture":
                raw = exact_object(
                    value,
                    frozenset({"execution_envelope_hash", "execution_capture_hash"}),
                    "L4 execution capture record",
                )
                return {
                    "execution_envelope_hash": digest_value(
                        raw["execution_envelope_hash"], "execution_envelope_hash"
                    ),
                    "execution_capture_hash": digest_value(
                        raw["execution_capture_hash"], "execution_capture_hash"
                    ),
                }
            return _decode_receipt(record_type, value).to_json_dict()
        except ReV2LedgerError:
            raise
        except (Protocol22SchemaError, Protocol28ExecutionError, TypeError, ValueError) as exc:
            raise ReV2LedgerError(f"invalid {record_type} payload: {exc}") from exc


PROTOCOL_28_LEDGER_PROTOCOL = _Protocol28LedgerProtocol()


class Protocol28Ledger(DurableLedger[Protocol28LedgerView]):
    """Typed protocol-2.8 facade over the authenticated common ledger envelope."""

    def __init__(self, path: Path, object_store: ObjectStore) -> None:
        super().__init__(Path(path), object_store, PROTOCOL_28_LEDGER_PROTOCOL)

    def record_execution_capture(
        self, envelope: L4ExecutionEnvelopeV1, capture: L4ExecutionCaptureV1
    ) -> LedgerRecord:
        if not isinstance(envelope, L4ExecutionEnvelopeV1) or not isinstance(
            capture, L4ExecutionCaptureV1
        ):
            raise ReV2LedgerError("execution capture record requires typed authority")
        return self._append(
            "l4_execution_capture",
            {
                "execution_envelope_hash": envelope.identity,
                "execution_capture_hash": capture.identity,
            },
        )

    def record_candidate(self, receipt: L4CandidateReceiptV1) -> LedgerRecord:
        return self._typed_append("l4_candidate", receipt, L4CandidateReceiptV1)

    def record_verification(self, receipt: L4VerificationReceiptV1) -> LedgerRecord:
        return self._typed_append("l4_verification", receipt, L4VerificationReceiptV1)

    def record_certification(self, receipt: L4CertificationReceiptV1) -> LedgerRecord:
        return self._typed_append("l4_certification", receipt, L4CertificationReceiptV1)

    def record_acceptance(self, receipt: L4AcceptanceReceiptV1) -> LedgerRecord:
        return self._typed_append("l4_acceptance", receipt, L4AcceptanceReceiptV1)

    def record_accepted_slice(self, accepted: AcceptedExhaustiveSliceV1) -> LedgerRecord:
        return self._typed_append("l4_accepted_slice", accepted, AcceptedExhaustiveSliceV1)

    def record_knowledge_work(self, work):
        from harness.re_v2.protocol_28.reconciliation import KnowledgeReconciliationWorkItemV1
        return self._typed_append('knowledge_work', work, KnowledgeReconciliationWorkItemV1)

    def read_snapshot(self):
        """Authenticate one captured byte stream without creating a lock file.

        Explicit reviewed reads never repair/create state. A concurrent partial
        append fails closed through the same existing canonical ledger parser.
        Mutations continue to use the original locked append path.
        """
        self._validate_parent()
        history, state = self._read_replay()
        return history, state.view()

    def record_knowledge_artifact(self, receipt):
        from harness.re_v2.protocol_28.reconciliation import KnowledgeReconciliationExecutionReceiptV1
        return self._typed_append('knowledge_artifact', receipt, KnowledgeReconciliationExecutionReceiptV1)

    def record_knowledge_root(self, root):
        from harness.re_v2.protocol_28.reconciliation import KnowledgeReconciliationRootV1
        return self._typed_append('knowledge_root', root, KnowledgeReconciliationRootV1)

    def record_knowledge_run_root(self, root):
        from harness.re_v2.protocol_28.reconciliation import ReviewedKnowledgeRunRootV1
        return self._typed_append('knowledge_run_root', root, ReviewedKnowledgeRunRootV1)

    def _typed_append(self, record_type: str, value: object, expected: type) -> LedgerRecord:
        if not isinstance(value, expected):
            raise ReV2LedgerError(f"{record_type} requires {expected.__name__}")
        return self._append(record_type, value.to_json_dict())  # type: ignore[attr-defined]


def _decode_receipt(record_type: str, value: object):  # type: ignore[no-untyped-def]
    if record_type.startswith('knowledge_'):
        from harness.re_v2.protocol_28 import reconciliation as r
        cls = {'knowledge_work': r.KnowledgeReconciliationWorkItemV1,
            'knowledge_artifact': r.KnowledgeReconciliationExecutionReceiptV1,
            'knowledge_root': r.KnowledgeReconciliationRootV1,
            'knowledge_run_root': r.ReviewedKnowledgeRunRootV1}.get(record_type)
        if cls is not None:
            return cls.from_json_dict(value)
    decoder = _RECEIPT_DECODERS.get(record_type)
    if decoder is None:
        raise ReV2LedgerError(f"unknown protocol-2.8 ledger record type: {record_type!r}")
    return decoder(value)


def _load(object_store: ObjectStore, object_hash: str, cls):  # type: ignore[no-untyped-def]
    payload = object_store.read_blob(object_hash)
    model = load_canonical_object(payload, cls.from_json_dict)
    if model.identity != object_hash:
        raise ReV2LedgerError(f"{cls.__name__} object identity mismatch")
    return model


def _verify_exact_object(object_store: ObjectStore, model: object) -> None:
    identity = getattr(model, "identity", None)
    if not isinstance(identity, str):
        raise ReV2LedgerError("authority object lacks canonical identity")
    payload = object_store.read_blob(identity)
    if payload != canonical_json_bytes(model.to_json_dict()):  # type: ignore[attr-defined]
        raise ReV2LedgerError("authority object bytes do not match receipt")


__all__ = (
    "PROTOCOL_28_LEDGER_PROTOCOL",
    "Protocol28Ledger",
    "Protocol28LedgerView",
)
