"""Typed protocol-2.5 semantic authority over the shared durable ledger."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from harness.re_v2.ledger import (
    DurableLedger,
    LedgerProtocol,
    LedgerRecord,
    ObjectStore,
    ReV2LedgerError,
)
from harness.re_v2.protocol_22.baseline import (
    ArtifactAcceptanceReceiptV2,
    CandidateAssessmentReceiptV1,
)
from harness.re_v2.protocol_22.ledger import (
    PROTOCOL_22_LEDGER_PROTOCOL,
    Protocol22Ledger,
    Protocol22LedgerView,
)
from harness.re_v2.protocol_22.schema import Protocol22SchemaError
from harness.re_v2.run_store import ReV2Paths

from .artifacts import (
    AuditCandidateV1,
    AuditClosureRootV1,
    AuditEpochV1,
    FindingClosureReceiptV1,
    L3SourceRootV1,
    SemanticCertificationReceiptV1,
    SemanticResolutionOverlayV1,
    SourceCompositionAssessmentV1,
    TargetClosureAssessmentV1,
)
from .model import Protocol25SchemaError


_SHARED_RECORD_TYPES = frozenset(
    {
        "certification",
        "candidate_assessment",
        "artifact",
        "work_item_failure",
        "executor_failure",
    }
)
_SEMANTIC_DECODERS = {
    "semantic_certification": SemanticCertificationReceiptV1.from_json_dict,
    "audit_epoch": AuditEpochV1.from_json_dict,
    "target_closure_assessment": TargetClosureAssessmentV1.from_json_dict,
    "source_composition_assessment": SourceCompositionAssessmentV1.from_json_dict,
    "finding_closure": FindingClosureReceiptV1.from_json_dict,
    "audit_closure_root": AuditClosureRootV1.from_json_dict,
    "l3_source_root": L3SourceRootV1.from_json_dict,
}


@dataclass(frozen=True, slots=True)
class Protocol25LedgerView(Protocol22LedgerView):
    semantic_certifications: Mapping[str, SemanticCertificationReceiptV1]
    audit_epochs: Mapping[str, AuditEpochV1]
    target_closure_assessments: Mapping[str, TargetClosureAssessmentV1]
    source_composition_assessments: Mapping[str, SourceCompositionAssessmentV1]
    finding_closures: Mapping[str, FindingClosureReceiptV1]
    latest_finding_closures: Mapping[str, FindingClosureReceiptV1]
    audit_closure_roots: Mapping[str, AuditClosureRootV1]
    l3_source_roots: Mapping[str, L3SourceRootV1]
    semantic_records: Mapping[str, LedgerRecord]

    def _accepted_work_item_ids(self) -> frozenset[str]:
        shared = {
            self.certification_work_items[receipt.certification_receipt_id].work_item_id
            for receipt in self.accepted_artifacts.values()
            if receipt.certification_receipt_id in self.certification_work_items
        }
        semantic = {
            assessment.work_item_id
            for assessment in self.candidate_assessments.values()
            if assessment.certification_receipt_id in self.semantic_certifications
            and assessment.outcome == "certified"
        }
        return frozenset(shared | semantic)


@dataclass(slots=True)
class _Protocol25LedgerState:
    shared: object
    semantic_certifications: dict[str, SemanticCertificationReceiptV1]
    semantic_certifications_by_key: dict[str, SemanticCertificationReceiptV1]
    semantic_candidate_assessments: dict[str, CandidateAssessmentReceiptV1]
    semantic_candidates_by_candidate: dict[str, CandidateAssessmentReceiptV1]
    semantic_accepted_artifacts: dict[str, ArtifactAcceptanceReceiptV2]
    audit_epochs: dict[str, AuditEpochV1]
    target_assessments: dict[str, TargetClosureAssessmentV1]
    source_assessments: dict[str, SourceCompositionAssessmentV1]
    finding_closures: dict[str, FindingClosureReceiptV1]
    latest_finding_closures: dict[str, FindingClosureReceiptV1]
    audit_closure_roots: dict[str, AuditClosureRootV1]
    l3_source_roots: dict[str, L3SourceRootV1]
    deferred_observations: dict[str, object]
    semantic_records: dict[str, LedgerRecord]
    semantic_records_by_key: dict[tuple[str, str], LedgerRecord]
    semantic_candidate_records: dict[str, LedgerRecord]
    semantic_artifact_records: dict[str, LedgerRecord]

    @classmethod
    def empty(cls) -> "_Protocol25LedgerState":
        return cls(
            PROTOCOL_22_LEDGER_PROTOCOL.new_state(),
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
        )

    def consume(self, record: LedgerRecord, object_store: ObjectStore) -> None:
        try:
            if record.type == "candidate_assessment":
                receipt = CandidateAssessmentReceiptV1.from_json_dict(record.payload)
                if receipt.certification_receipt_id in self.semantic_certifications:
                    self._consume_semantic_candidate(record, object_store, receipt)
                else:
                    self.shared.consume(record, object_store)  # type: ignore[attr-defined]
                return
            if record.type == "artifact":
                receipt = ArtifactAcceptanceReceiptV2.from_json_dict(record.payload)
                if receipt.certification_receipt_id in self.semantic_certifications:
                    self._consume_semantic_artifact(record, object_store, receipt)
                else:
                    self.shared.consume(record, object_store)  # type: ignore[attr-defined]
                return
            if record.type in _SHARED_RECORD_TYPES:
                self.shared.consume(record, object_store)  # type: ignore[attr-defined]
                return
            handlers = {
                "semantic_certification": self._consume_semantic_certification,
                "audit_epoch": self._consume_audit_epoch,
                "target_closure_assessment": self._consume_target_assessment,
                "source_composition_assessment": self._consume_source_assessment,
                "finding_closure": self._consume_finding_closure,
                "audit_closure_root": self._consume_audit_closure_root,
                "l3_source_root": self._consume_l3_source_root,
            }
            handler = handlers.get(record.type)
            if handler is None:
                raise ReV2LedgerError(
                    f"unknown protocol-2.5 ledger record type: {record.type!r}"
                )
            handler(record, object_store)
        except ReV2LedgerError:
            raise
        except (Protocol22SchemaError, Protocol25SchemaError, TypeError, ValueError) as exc:
            raise ReV2LedgerError(f"invalid {record.type} receipt: {exc}") from exc

    def _consume_semantic_certification(
        self, record: LedgerRecord, object_store: ObjectStore
    ) -> None:
        receipt = SemanticCertificationReceiptV1.from_json_dict(record.payload)
        object_store.verify(receipt.artifact_hash)
        existing = self.semantic_certifications_by_key.get(receipt.artifact_key_id)
        if existing is not None:
            if existing != receipt:
                raise ReV2LedgerError(
                    "conflicting semantic certification for artifact key"
                )
            return
        if receipt.identity in self.semantic_certifications:
            raise ReV2LedgerError("duplicate semantic certification identity")
        self.semantic_certifications[receipt.identity] = receipt
        self.semantic_certifications_by_key[receipt.artifact_key_id] = receipt
        self._remember(record, receipt.identity, (record.type, receipt.artifact_key_id))

    def _consume_semantic_candidate(
        self,
        record: LedgerRecord,
        object_store: ObjectStore,
        receipt: CandidateAssessmentReceiptV1,
    ) -> None:
        certification = self.semantic_certifications[receipt.certification_receipt_id]
        object_store.verify(receipt.execution_capture_hash)
        if receipt.normalized_authorial_payload_hash is not None:
            object_store.verify(receipt.normalized_authorial_payload_hash)
        if (
            receipt.artifact_hash != certification.artifact_hash
            or (
                receipt.outcome == "certified"
                and certification.verdict != "accepted"
            )
            or (
                receipt.outcome != "certified"
                and certification.verdict != "rejected"
            )
        ):
            raise ReV2LedgerError(
                "semantic candidate assessment disagrees with certification"
            )
        shared_view = self.shared.view()  # type: ignore[attr-defined]
        if receipt.candidate_id in shared_view.candidate_assessments:
            raise ReV2LedgerError("semantic candidate identity conflicts with shared authority")
        existing = self.semantic_candidates_by_candidate.get(receipt.candidate_id)
        if existing is not None:
            if existing != receipt:
                raise ReV2LedgerError(
                    "conflicting candidate-assessment receipt for candidate"
                )
            return
        self.semantic_candidate_assessments[receipt.identity] = receipt
        self.semantic_candidates_by_candidate[receipt.candidate_id] = receipt
        self.semantic_candidate_records[receipt.candidate_id] = record

    def _consume_semantic_artifact(
        self,
        record: LedgerRecord,
        object_store: ObjectStore,
        receipt: ArtifactAcceptanceReceiptV2,
    ) -> None:
        certification = self.semantic_certifications[receipt.certification_receipt_id]
        if certification.verdict != "accepted":
            raise ReV2LedgerError(
                "semantic artifact acceptance requires accepted certification"
            )
        if (
            receipt.artifact_key.identity != certification.artifact_key_id
            or receipt.artifact_hash != certification.artifact_hash
        ):
            raise ReV2LedgerError(
                "semantic artifact acceptance does not match certification"
            )
        matching = tuple(
            item
            for item in self.semantic_candidate_assessments.values()
            if item.certification_receipt_id == certification.identity
            and item.outcome == "certified"
            and item.artifact_hash == receipt.artifact_hash
        )
        if not matching:
            raise ReV2LedgerError(
                "semantic artifact acceptance requires a certified candidate assessment"
            )
        object_store.verify(receipt.artifact_hash)
        key_id = receipt.artifact_key.identity
        shared_view = self.shared.view()  # type: ignore[attr-defined]
        if key_id in shared_view.accepted_artifacts:
            raise ReV2LedgerError("semantic artifact key conflicts with shared authority")
        existing = self.semantic_accepted_artifacts.get(key_id)
        if existing is not None:
            if existing != receipt:
                raise ReV2LedgerError(
                    "conflicting artifact-acceptance receipt for artifact key"
                )
            return
        self.semantic_accepted_artifacts[key_id] = receipt
        self.semantic_artifact_records[key_id] = record

    def _consume_audit_epoch(
        self, record: LedgerRecord, object_store: ObjectStore
    ) -> None:
        epoch = AuditEpochV1.from_json_dict(record.payload)
        self._verify_authority_object(object_store, epoch, AuditEpochV1)
        if self.audit_epochs and epoch.identity not in self.audit_epochs:
            raise ReV2LedgerError("protocol-2.5 run cannot freeze multiple audit epochs")
        for authority in epoch.target_candidate_authorities:
            certification = self.semantic_certifications.get(
                authority.certification_receipt_id
            )
            if (
                certification is None
                or certification.verdict != "accepted"
                or certification.audit_epoch_id is not None
                or certification.audit_target_id != authority.audit_target_id
                or certification.artifact_hash != authority.candidate_hash
            ):
                raise ReV2LedgerError(
                    "audit epoch target lacks preceding semantic certification"
                )
            acceptance = next(
                (
                    item
                    for item in self.semantic_accepted_artifacts.values()
                    if item.identity == authority.acceptance_receipt_id
                ),
                None,
            )
            if acceptance is None or acceptance.artifact_hash != authority.candidate_hash:
                raise ReV2LedgerError(
                    "audit epoch target lacks preceding artifact acceptance"
                )
            candidate = self._load_authority(
                object_store, authority.candidate_hash, AuditCandidateV1
            )
            if (
                candidate.audit_target_id != authority.audit_target_id
                or candidate.artifact_key.identity != certification.artifact_key_id
                or candidate.audit_target.audit_policy_hash != epoch.audit_policy_hash
                or candidate.audit_target.auditor_authority_hash
                != epoch.auditor_authority_hash
                or certification.verifier_authority_hash
                != epoch.verifier_authority_hash
                or tuple(item.finding_key_id for item in candidate.findings)
                != authority.finding_key_ids
            ):
                raise ReV2LedgerError(
                    "audit epoch target authority does not match accepted candidate"
                )
        for object_hash in epoch.audited_l2_root_hashes:
            object_store.verify(object_hash)
        self.audit_epochs[epoch.identity] = epoch
        self._remember(record, epoch.identity, (record.type, "epoch"))

    def _consume_target_assessment(
        self, record: LedgerRecord, object_store: ObjectStore
    ) -> None:
        assessment = TargetClosureAssessmentV1.from_json_dict(record.payload)
        self._verify_authority_object(
            object_store, assessment, TargetClosureAssessmentV1
        )
        epoch = self._epoch(assessment.audit_epoch_id)
        target = self._target(epoch, assessment.audit_target_id)
        active = tuple(
            item
            for item in target.finding_key_ids
            if self.latest_finding_closures.get(item, None) is None
            or self.latest_finding_closures[item].verdict != "closed"
        )
        if assessment.assessed_finding_ids != active:
            raise ReV2LedgerError(
                "target assessment does not cover the exact active epoch findings"
            )
        overlay = self._accepted_overlay(
            object_store,
            assessment.resolution_overlay_hash,
            epoch.identity,
            assessment.audit_target_id,
        )
        overlay_findings = {
            finding_id for entry in overlay.entries for finding_id in entry.finding_key_ids
        }
        if not set(assessment.assessed_finding_ids).issubset(overlay_findings):
            raise ReV2LedgerError(
                "target assessment finding is absent from the accepted overlay"
            )
        for observation in assessment.deferred_observations:
            if observation.audit_target_id != assessment.audit_target_id:
                raise ReV2LedgerError(
                    "deferred observation does not match target assessment"
                )
            self._remember_deferred(observation)
        self.target_assessments[assessment.identity] = assessment
        target_key = ":".join(
            (
                assessment.audit_epoch_id,
                assessment.audit_target_id,
                assessment.resolution_overlay_hash,
            )
        )
        self._remember(record, assessment.identity, (record.type, target_key))

    def _consume_source_assessment(
        self, record: LedgerRecord, object_store: ObjectStore
    ) -> None:
        assessment = SourceCompositionAssessmentV1.from_json_dict(record.payload)
        self._verify_authority_object(
            object_store, assessment, SourceCompositionAssessmentV1
        )
        epoch = self._epoch(assessment.audit_epoch_id)
        if not set(assessment.implicated_finding_ids).issubset(epoch.finding_key_ids):
            raise ReV2LedgerError("source assessment finding is outside audit epoch")
        for target_hash in assessment.target_assessment_hashes:
            target = self.target_assessments.get(target_hash)
            if target is None or target.audit_epoch_id != epoch.identity:
                raise ReV2LedgerError(
                    "source assessment requires preceding target assessments"
                )
        for overlay_hash in assessment.overlay_hashes:
            if not any(
                item.artifact_hash == overlay_hash
                for item in self.semantic_accepted_artifacts.values()
            ):
                raise ReV2LedgerError(
                    "source assessment requires accepted resolution overlays"
                )
        object_store.verify(assessment.composed_authority_hash)
        for observation in assessment.deferred_observations:
            if observation.audit_target_id not in epoch.audit_target_ids:
                raise ReV2LedgerError(
                    "deferred observation target is outside audit epoch"
                )
            self._remember_deferred(observation)
        self.source_assessments[assessment.identity] = assessment
        self._remember(record, assessment.identity, (record.type, assessment.identity))

    def _consume_finding_closure(
        self, record: LedgerRecord, object_store: ObjectStore
    ) -> None:
        receipt = FindingClosureReceiptV1.from_json_dict(record.payload)
        self._verify_authority_object(object_store, receipt, FindingClosureReceiptV1)
        epoch = self._epoch(receipt.audit_epoch_id)
        target = self._target(epoch, receipt.audit_target_id)
        if receipt.finding_key_id not in target.finding_key_ids:
            raise ReV2LedgerError("closure finding is outside its audit epoch target")
        target_assessment = self.target_assessments.get(
            receipt.target_closure_assessment_hash
        )
        if target_assessment is None:
            raise ReV2LedgerError(
                "closure requires a preceding target assessment"
            )
        source_assessment = self.source_assessments.get(
            receipt.source_composition_assessment_hash
        )
        if source_assessment is None:
            raise ReV2LedgerError(
                "closure requires a preceding source assessment"
            )
        if source_assessment.outcome != "passed":
            raise ReV2LedgerError("closure requires a passing source assessment")
        verdict = next(
            (
                item.verdict
                for item in target_assessment.verdicts
                if item.finding_key_id == receipt.finding_key_id
            ),
            None,
        )
        if (
            target_assessment.audit_epoch_id != epoch.identity
            or target_assessment.audit_target_id != receipt.audit_target_id
            or target_assessment.resolution_overlay_hash
            != receipt.resolution_overlay_hash
            or verdict != receipt.verdict
            or target_assessment.identity
            not in source_assessment.target_assessment_hashes
            or receipt.resolution_overlay_hash not in source_assessment.overlay_hashes
        ):
            raise ReV2LedgerError(
                "closure receipt does not match target/source assessments"
            )
        previous = self.latest_finding_closures.get(receipt.finding_key_id)
        if receipt.semantic_round == 1:
            if previous is not None:
                raise ReV2LedgerError(
                    "first closure receipt conflicts with preceding receipt"
                )
        elif (
            previous is None
            or receipt.previous_closure_receipt_id != previous.identity
            or receipt.semantic_round != previous.semantic_round + 1
        ):
            raise ReV2LedgerError(
                "later closure receipt requires the consecutive preceding receipt"
            )
        self.finding_closures[receipt.identity] = receipt
        self.latest_finding_closures[receipt.finding_key_id] = receipt
        self._remember(record, receipt.identity, (record.type, receipt.identity))

    def _consume_audit_closure_root(
        self, record: LedgerRecord, object_store: ObjectStore
    ) -> None:
        root = AuditClosureRootV1.from_json_dict(record.payload)
        self._verify_authority_object(object_store, root, AuditClosureRootV1)
        epoch = self._epoch(root.audit_epoch_id)
        if root.frozen_finding_ids != epoch.finding_key_ids:
            raise ReV2LedgerError("audit closure root does not match frozen epoch")
        for receipt in root.latest_closure_receipts:
            if self.latest_finding_closures.get(receipt.finding_key_id) != receipt:
                raise ReV2LedgerError(
                    "audit closure root does not contain latest ledger receipt"
                )
        counter_targets = tuple(item[0] for item in root.target_rounds)
        if counter_targets != epoch.audit_target_ids:
            raise ReV2LedgerError(
                "audit closure root counters do not cover exact audit targets"
            )
        for receipt in root.latest_closure_receipts:
            rounds = dict(root.target_rounds)
            if receipt.semantic_round > rounds[receipt.audit_target_id]:
                raise ReV2LedgerError(
                    "audit closure root round is behind finding receipts"
                )
        for observation in root.deferred_observations:
            if self.deferred_observations.get(observation.observation_id) != observation:
                raise ReV2LedgerError(
                    "audit closure root has unknown deferred observation identity"
                )
        self.audit_closure_roots[root.identity] = root
        self._remember(record, root.identity, (record.type, root.identity))

    def _consume_l3_source_root(
        self, record: LedgerRecord, object_store: ObjectStore
    ) -> None:
        root = L3SourceRootV1.from_json_dict(record.payload)
        self._verify_authority_object(object_store, root, L3SourceRootV1)
        object_store.verify(root.adopted_l2_root_hash)
        epochs = {
            self.audit_closure_roots[item].audit_epoch_id
            for item in root.closure_root_hashes
            if item in self.audit_closure_roots
        }
        if len(epochs) != 1 or len(root.closure_root_hashes) != sum(
            item in self.audit_closure_roots for item in root.closure_root_hashes
        ):
            raise ReV2LedgerError(
                "L3 source root requires preceding closure root authority"
            )
        epoch = self._epoch(next(iter(epochs)))
        if not set(root.audit_target_ids).issubset(epoch.audit_target_ids):
            raise ReV2LedgerError("L3 source root target is outside audit epoch")
        for target_id in root.audit_target_ids:
            candidate = self._candidate_for_target(object_store, epoch, target_id)
            if candidate.audit_target.scope.source_id != root.source_id:
                raise ReV2LedgerError("L3 source root contains another source target")
        closure_roots = tuple(
            self.audit_closure_roots[item] for item in root.closure_root_hashes
        )
        unresolved = {
            item for closure in closure_roots for item in closure.unresolved_finding_ids
        }
        deferred = {
            item.observation_id
            for closure in closure_roots
            for item in closure.deferred_observations
        }
        if not set(root.unresolved_finding_ids).issubset(unresolved):
            raise ReV2LedgerError("L3 source root unresolved set is unauthorized")
        if not set(root.deferred_observation_ids).issubset(deferred):
            raise ReV2LedgerError("L3 source root deferred set is unauthorized")
        if root.state == "complete" and (unresolved or deferred):
            raise ReV2LedgerError(
                "complete L3 source root requires closed closure roots"
            )
        existing = self.l3_source_roots.get(root.source_id)
        if existing is not None and existing != root:
            raise ReV2LedgerError("conflicting L3 source root for source")
        self.l3_source_roots[root.source_id] = root
        self._remember(record, root.identity, (record.type, root.source_id))

    def _epoch(self, epoch_id: str) -> AuditEpochV1:
        epoch = self.audit_epochs.get(epoch_id)
        if epoch is None:
            raise ReV2LedgerError("semantic authority references an unknown audit epoch")
        return epoch

    @staticmethod
    def _target(epoch: AuditEpochV1, target_id: str):  # type: ignore[no-untyped-def]
        target = next(
            (
                item
                for item in epoch.target_candidate_authorities
                if item.audit_target_id == target_id
            ),
            None,
        )
        if target is None:
            raise ReV2LedgerError("semantic authority target is outside audit epoch")
        return target

    def _accepted_overlay(
        self,
        object_store: ObjectStore,
        overlay_hash: str,
        epoch_id: str,
        target_id: str,
    ) -> SemanticResolutionOverlayV1:
        certification = next(
            (
                item
                for item in self.semantic_certifications.values()
                if item.artifact_hash == overlay_hash
                and item.audit_epoch_id == epoch_id
                and item.audit_target_id == target_id
                and item.verdict == "accepted"
            ),
            None,
        )
        if certification is None or not any(
            item.artifact_hash == overlay_hash
            and item.certification_receipt_id == certification.identity
            for item in self.semantic_accepted_artifacts.values()
        ):
            raise ReV2LedgerError(
                "target assessment requires an accepted resolution overlay"
            )
        overlay = self._load_authority(
            object_store, overlay_hash, SemanticResolutionOverlayV1
        )
        if overlay.artifact_key.identity != certification.artifact_key_id:
            raise ReV2LedgerError(
                "accepted resolution overlay artifact key is inconsistent"
            )
        return overlay

    def _candidate_for_target(
        self, object_store: ObjectStore, epoch: AuditEpochV1, target_id: str
    ) -> AuditCandidateV1:
        target = self._target(epoch, target_id)
        return self._load_authority(object_store, target.candidate_hash, AuditCandidateV1)

    @staticmethod
    def _load_authority(object_store: ObjectStore, object_hash: str, value_type):  # type: ignore[no-untyped-def]
        from harness.re_v2.protocol_22.schema import load_canonical_object

        return load_canonical_object(
            object_store.read_blob(object_hash), value_type.from_json_dict
        )

    @classmethod
    def _verify_authority_object(cls, object_store, authority, value_type) -> None:  # type: ignore[no-untyped-def]
        if cls._load_authority(object_store, authority.identity, value_type) != authority:
            raise ReV2LedgerError("semantic authority object does not round-trip")

    def _remember_deferred(self, observation) -> None:  # type: ignore[no-untyped-def]
        existing = self.deferred_observations.get(observation.observation_id)
        if existing is not None and existing != observation:
            raise ReV2LedgerError("conflicting deferred observation identity")
        self.deferred_observations[observation.observation_id] = observation

    def _remember(
        self,
        record: LedgerRecord,
        identity: str,
        key: tuple[str, str],
    ) -> None:
        existing = self.semantic_records.get(identity)
        if existing is not None and existing != record:
            raise ReV2LedgerError("duplicate semantic receipt identity")
        keyed = self.semantic_records_by_key.get(key)
        if keyed is not None and keyed.payload != record.payload:
            raise ReV2LedgerError("conflicting semantic receipt authority")
        self.semantic_records[identity] = record
        self.semantic_records_by_key[key] = record

    def idempotent_record(
        self,
        history: tuple[LedgerRecord, ...],
        record_type: str,
        payload: Mapping[str, object],
    ) -> LedgerRecord | None:
        if record_type == "candidate_assessment":
            receipt = CandidateAssessmentReceiptV1.from_json_dict(payload)
            existing = self.semantic_candidates_by_candidate.get(receipt.candidate_id)
            if existing is not None:
                if existing != receipt:
                    raise ReV2LedgerError(
                        "conflicting candidate-assessment receipt for candidate"
                    )
                return self.semantic_candidate_records[receipt.candidate_id]
        elif record_type == "artifact":
            receipt = ArtifactAcceptanceReceiptV2.from_json_dict(payload)
            key_id = receipt.artifact_key.identity
            existing = self.semantic_accepted_artifacts.get(key_id)
            if existing is not None:
                if existing != receipt:
                    raise ReV2LedgerError(
                        "conflicting artifact-acceptance receipt for artifact key"
                    )
                return self.semantic_artifact_records[key_id]
        if record_type in _SHARED_RECORD_TYPES:
            return self.shared.idempotent_record(  # type: ignore[attr-defined]
                history, record_type, payload
            )
        decoder = _SEMANTIC_DECODERS.get(record_type)
        if decoder is None:
            raise ReV2LedgerError(
                f"unknown protocol-2.5 ledger record type: {record_type!r}"
            )
        authority = decoder(payload)
        existing = self.semantic_records.get(authority.identity)
        if existing is not None:
            return existing
        if record_type == "semantic_certification":
            keyed = self.semantic_certifications_by_key.get(authority.artifact_key_id)
            if keyed is not None and keyed != authority:
                raise ReV2LedgerError(
                    "conflicting semantic certification for artifact key"
                )
        if record_type == "l3_source_root":
            keyed = self.l3_source_roots.get(authority.source_id)
            if keyed is not None and keyed != authority:
                raise ReV2LedgerError("conflicting L3 source root for source")
        return None

    def view(self) -> Protocol25LedgerView:
        shared = self.shared.view()  # type: ignore[attr-defined]
        candidates = dict(shared.candidate_assessments)
        candidates.update(self.semantic_candidate_assessments)
        accepted = dict(shared.accepted_artifacts)
        accepted.update(self.semantic_accepted_artifacts)
        candidate_records = dict(shared.candidate_assessment_records)
        candidate_records.update(
            {
                receipt.identity: self.semantic_candidate_records[candidate_id]
                for candidate_id, receipt in self.semantic_candidates_by_candidate.items()
            }
        )
        artifact_records = dict(shared.artifact_acceptance_records)
        artifact_records.update(
            {
                receipt.identity: self.semantic_artifact_records[key_id]
                for key_id, receipt in self.semantic_accepted_artifacts.items()
            }
        )
        return Protocol25LedgerView(
            certifications=shared.certifications,
            certification_work_items=shared.certification_work_items,
            candidate_assessments=MappingProxyType(candidates),
            accepted_artifacts=MappingProxyType(accepted),
            work_item_failures=shared.work_item_failures,
            executor_failures=shared.executor_failures,
            certification_records=shared.certification_records,
            candidate_assessment_records=MappingProxyType(candidate_records),
            artifact_acceptance_records=MappingProxyType(artifact_records),
            work_item_failure_records=shared.work_item_failure_records,
            executor_failure_records=shared.executor_failure_records,
            semantic_certifications=MappingProxyType(dict(self.semantic_certifications)),
            audit_epochs=MappingProxyType(dict(self.audit_epochs)),
            target_closure_assessments=MappingProxyType(dict(self.target_assessments)),
            source_composition_assessments=MappingProxyType(dict(self.source_assessments)),
            finding_closures=MappingProxyType(dict(self.finding_closures)),
            latest_finding_closures=MappingProxyType(
                dict(self.latest_finding_closures)
            ),
            audit_closure_roots=MappingProxyType(dict(self.audit_closure_roots)),
            l3_source_roots=MappingProxyType(dict(self.l3_source_roots)),
            semantic_records=MappingProxyType(dict(self.semantic_records)),
        )


class Protocol25LedgerProtocol(LedgerProtocol[Protocol25LedgerView]):
    """Registered semantic decoder layered over protocol-2.2 receipt authority."""

    def new_state(self) -> _Protocol25LedgerState:
        return _Protocol25LedgerState.empty()

    def canonical_payload(
        self, record_type: str, value: object
    ) -> Mapping[str, object]:
        if record_type in _SHARED_RECORD_TYPES:
            return PROTOCOL_22_LEDGER_PROTOCOL.canonical_payload(record_type, value)
        decoder = _SEMANTIC_DECODERS.get(record_type)
        if decoder is None:
            raise ReV2LedgerError(
                f"unknown protocol-2.5 ledger record type: {record_type!r}"
            )
        try:
            return decoder(value).to_json_dict()
        except ReV2LedgerError:
            raise
        except (Protocol22SchemaError, Protocol25SchemaError, TypeError, ValueError) as exc:
            raise ReV2LedgerError(
                f"invalid {record_type} ledger payload: {exc}"
            ) from exc


PROTOCOL_25_LEDGER_PROTOCOL = Protocol25LedgerProtocol()


class Protocol25Ledger(Protocol22Ledger):
    """Protocol-2.5 facade preserving every shared record operation."""

    def __init__(self, path: Path | ReV2Paths, object_store: ObjectStore) -> None:
        DurableLedger.__init__(
            self,
            path.ledger if isinstance(path, ReV2Paths) else Path(path),
            object_store,
            PROTOCOL_25_LEDGER_PROTOCOL,
        )

    def record_semantic_certification(
        self, receipt: SemanticCertificationReceiptV1
    ) -> LedgerRecord:
        if not isinstance(receipt, SemanticCertificationReceiptV1):
            raise ReV2LedgerError(
                "receipt must be a SemanticCertificationReceiptV1"
            )
        return self._append("semantic_certification", receipt.to_json_dict())

    def record_audit_epoch(self, epoch: AuditEpochV1) -> LedgerRecord:
        if not isinstance(epoch, AuditEpochV1):
            raise ReV2LedgerError("epoch must be an AuditEpochV1")
        return self._append("audit_epoch", epoch.to_json_dict())

    def record_target_closure_assessment(
        self, assessment: TargetClosureAssessmentV1
    ) -> LedgerRecord:
        if not isinstance(assessment, TargetClosureAssessmentV1):
            raise ReV2LedgerError(
                "assessment must be a TargetClosureAssessmentV1"
            )
        return self._append(
            "target_closure_assessment", assessment.to_json_dict()
        )

    def record_source_composition_assessment(
        self, assessment: SourceCompositionAssessmentV1
    ) -> LedgerRecord:
        if not isinstance(assessment, SourceCompositionAssessmentV1):
            raise ReV2LedgerError(
                "assessment must be a SourceCompositionAssessmentV1"
            )
        return self._append(
            "source_composition_assessment", assessment.to_json_dict()
        )

    def record_finding_closure(
        self, receipt: FindingClosureReceiptV1
    ) -> LedgerRecord:
        if not isinstance(receipt, FindingClosureReceiptV1):
            raise ReV2LedgerError("receipt must be a FindingClosureReceiptV1")
        return self._append("finding_closure", receipt.to_json_dict())

    def record_audit_closure_root(self, root: AuditClosureRootV1) -> LedgerRecord:
        if not isinstance(root, AuditClosureRootV1):
            raise ReV2LedgerError("root must be an AuditClosureRootV1")
        return self._append("audit_closure_root", root.to_json_dict())

    def record_l3_source_root(self, root: L3SourceRootV1) -> LedgerRecord:
        if not isinstance(root, L3SourceRootV1):
            raise ReV2LedgerError("root must be an L3SourceRootV1")
        return self._append("l3_source_root", root.to_json_dict())


__all__ = (
    "PROTOCOL_25_LEDGER_PROTOCOL",
    "Protocol25Ledger",
    "Protocol25LedgerProtocol",
    "Protocol25LedgerView",
)
