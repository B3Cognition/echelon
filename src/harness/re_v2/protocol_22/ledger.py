"""Protocol-2.2 receipt authority over the shared durable ledger envelope."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, Literal, Mapping
import unicodedata

from harness.re_v2.canonical import content_digest
from harness.re_v2.ledger import (
    DurableLedger,
    LedgerProtocol,
    LedgerRecord,
    ObjectStore,
    ReV2LedgerError,
)
from harness.re_v2.run_store import ReV2Paths

from .baseline import (
    ArtifactAcceptanceReceiptV2,
    CandidateAssessmentReceiptV1,
    CertificationReceiptV2,
    CompactCertificationAssessmentV2,
    DeterministicCertificationAssessmentV2,
)
from .graph import AcceptedArtifactV2, ExecutorFailureStateV2, WorkFailureStateV2
from .model import WorkItemV2
from .schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    one_of,
    optional_digest,
    safe_id,
)


_WORK_FAILURE_REASONS = {
    "result_contract": frozenset({"result_unrecoverable"}),
    "artifact_contract": frozenset(
        {
            "candidate_tree_invalid",
            "authorial_schema_invalid",
            "artifact_bound_exceeded",
            "evidence_contract_invalid",
        }
    ),
    "minimum_utility": frozenset({"minimum_utility_not_met"}),
    "execution_indeterminate": frozenset({"execution_outcome_indeterminate"}),
}
_PRE_DISPATCH_EXECUTOR_REASONS = frozenset(
    {"reservation_mismatch", "limit_unenforceable"}
)
_POST_DISPATCH_EXECUTOR_REASONS = frozenset(
    {
        "usage_exceeded_reservation",
        "deterministic_execution_failed",
        "deterministic_artifact_invalid",
    }
)
_EXECUTOR_REASONS = (
    _PRE_DISPATCH_EXECUTOR_REASONS | _POST_DISPATCH_EXECUTOR_REASONS
)


class Protocol22LedgerReceiptError(Protocol22SchemaError):
    """Raised when a closed protocol-2.2 receipt is semantically invalid."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol22LedgerReceiptError:
        raise
    except Protocol22SchemaError as exc:
        raise Protocol22LedgerReceiptError(str(exc)) from exc


def _digest(value: object, field: str) -> str:
    return _schema(digest_value, value, field)


def _optional_digest(value: object, field: str) -> str | None:
    return _schema(optional_digest, value, field)


def _optional_safe_id(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _schema(safe_id, value, field)


def _diagnostics(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise Protocol22LedgerReceiptError(f"{field} must be an array")
    result: list[str] = []
    for diagnostic in value:
        if not isinstance(diagnostic, str) or not diagnostic:
            raise Protocol22LedgerReceiptError(
                f"{field} must contain nonempty diagnostics"
            )
        if (
            diagnostic.strip() != diagnostic
            or "\r" in diagnostic
            or unicodedata.normalize("NFC", diagnostic) != diagnostic
            or len(diagnostic.encode("utf-8")) > 1024
        ):
            raise Protocol22LedgerReceiptError(
                f"{field} contains a non-normalized diagnostic"
            )
        result.append(diagnostic)
    frozen = tuple(result)
    if not frozen or len(frozen) > 64 or frozen != tuple(sorted(set(frozen))):
        raise Protocol22LedgerReceiptError(
            f"{field} diagnostics must be nonempty, sorted, unique, and bounded"
        )
    return frozen


@dataclass(frozen=True, slots=True)
class WorkItemFailureReceiptV1:
    schema_version: int
    work_item_id: str
    dispatch_id: str | None
    candidate_id: str | None
    candidate_assessment_id: str | None
    execution_capture_hash: str | None
    dispatch_abandonment_event_hash: str | None
    failure_class: Literal[
        "result_contract",
        "artifact_contract",
        "minimum_utility",
        "execution_indeterminate",
    ]
    reason_code: str
    normalized_diagnostics: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "work_item_id",
        "dispatch_id",
        "candidate_id",
        "candidate_assessment_id",
        "execution_capture_hash",
        "dispatch_abandonment_event_hash",
        "failure_class",
        "reason_code",
        "normalized_diagnostics",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol22LedgerReceiptError(
                "WorkItemFailureReceiptV1.schema_version must be 1"
            )
        _digest(self.work_item_id, "WorkItemFailureReceiptV1.work_item_id")
        dispatch_id = _optional_safe_id(
            self.dispatch_id, "WorkItemFailureReceiptV1.dispatch_id"
        )
        candidate_id = _optional_digest(
            self.candidate_id, "WorkItemFailureReceiptV1.candidate_id"
        )
        assessment_id = _optional_digest(
            self.candidate_assessment_id,
            "WorkItemFailureReceiptV1.candidate_assessment_id",
        )
        capture_hash = _optional_digest(
            self.execution_capture_hash,
            "WorkItemFailureReceiptV1.execution_capture_hash",
        )
        abandonment_hash = _optional_digest(
            self.dispatch_abandonment_event_hash,
            "WorkItemFailureReceiptV1.dispatch_abandonment_event_hash",
        )
        if self.failure_class not in _WORK_FAILURE_REASONS:
            raise Protocol22LedgerReceiptError(
                "WorkItemFailureReceiptV1.failure_class is unsupported"
            )
        if self.reason_code not in _WORK_FAILURE_REASONS[self.failure_class]:
            raise Protocol22LedgerReceiptError(
                "WorkItemFailureReceiptV1 failure_class and reason_code disagree"
            )
        if dispatch_id is None:
            raise Protocol22LedgerReceiptError(
                "WorkItemFailureReceiptV1 requires the final dispatch ID"
            )
        if assessment_id is not None and candidate_id is None:
            raise Protocol22LedgerReceiptError(
                "WorkItemFailureReceiptV1 assessment requires a candidate ID"
            )
        if (
            candidate_id is not None
            and assessment_id is None
            and self.failure_class != "result_contract"
        ):
            raise Protocol22LedgerReceiptError(
                "only result-contract failure may name an unassessed persisted candidate"
            )
        if (capture_hash is None) == (abandonment_hash is None):
            raise Protocol22LedgerReceiptError(
                "execution capture and abandonment authority are mutually exclusive"
            )
        if abandonment_hash is not None:
            if self.failure_class != "execution_indeterminate":
                raise Protocol22LedgerReceiptError(
                    "dispatch abandonment requires execution_indeterminate failure"
                )
            if candidate_id is not None:
                raise Protocol22LedgerReceiptError(
                    "an abandoned dispatch cannot contain candidate authority"
                )
        object.__setattr__(
            self,
            "normalized_diagnostics",
            _diagnostics(
                self.normalized_diagnostics,
                "WorkItemFailureReceiptV1.normalized_diagnostics",
            ),
        )

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    @property
    def failure_receipt_id(self) -> str:
        return self.identity

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        result["normalized_diagnostics"] = list(self.normalized_diagnostics)
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "WorkItemFailureReceiptV1":
        raw = _schema(
            exact_object,
            value,
            frozenset(cls.FIELDS),
            cls.__name__,
        )
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ExecutorFailureReceiptV1:
    schema_version: int
    executor_contract_hash: str
    trigger_work_item_id: str
    dispatch_id: str | None
    candidate_id: str | None
    execution_capture_hash: str | None
    reason_code: Literal[
        "reservation_mismatch",
        "limit_unenforceable",
        "usage_exceeded_reservation",
        "deterministic_execution_failed",
        "deterministic_artifact_invalid",
    ]
    normalized_diagnostics: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "executor_contract_hash",
        "trigger_work_item_id",
        "dispatch_id",
        "candidate_id",
        "execution_capture_hash",
        "reason_code",
        "normalized_diagnostics",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol22LedgerReceiptError(
                "ExecutorFailureReceiptV1.schema_version must be 1"
            )
        _digest(
            self.executor_contract_hash,
            "ExecutorFailureReceiptV1.executor_contract_hash",
        )
        _digest(
            self.trigger_work_item_id,
            "ExecutorFailureReceiptV1.trigger_work_item_id",
        )
        dispatch_id = _optional_safe_id(
            self.dispatch_id, "ExecutorFailureReceiptV1.dispatch_id"
        )
        candidate_id = _optional_digest(
            self.candidate_id, "ExecutorFailureReceiptV1.candidate_id"
        )
        capture_hash = _optional_digest(
            self.execution_capture_hash,
            "ExecutorFailureReceiptV1.execution_capture_hash",
        )
        _schema(one_of, self.reason_code, _EXECUTOR_REASONS, "reason_code")
        if self.reason_code in _PRE_DISPATCH_EXECUTOR_REASONS:
            if any(
                value is not None
                for value in (dispatch_id, candidate_id, capture_hash)
            ):
                raise Protocol22LedgerReceiptError(
                    "pre-dispatch executor failures require null dispatch fields"
                )
        elif dispatch_id is None or capture_hash is None:
            raise Protocol22LedgerReceiptError(
                "post-dispatch executor failures require dispatch and capture"
            )
        if self.reason_code.startswith("deterministic_") and candidate_id is not None:
            raise Protocol22LedgerReceiptError(
                "deterministic executor failure cannot contain a provider candidate"
            )
        object.__setattr__(
            self,
            "normalized_diagnostics",
            _diagnostics(
                self.normalized_diagnostics,
                "ExecutorFailureReceiptV1.normalized_diagnostics",
            ),
        )

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    @property
    def executor_failure_receipt_id(self) -> str:
        return self.identity

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        result["normalized_diagnostics"] = list(self.normalized_diagnostics)
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "ExecutorFailureReceiptV1":
        raw = _schema(
            exact_object,
            value,
            frozenset(cls.FIELDS),
            cls.__name__,
        )
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class Protocol22LedgerView:
    """Immutable receipt projection used by recovery and delta planning."""

    certifications: Mapping[str, CertificationReceiptV2]
    certification_work_items: Mapping[str, WorkItemV2]
    candidate_assessments: Mapping[str, CandidateAssessmentReceiptV1]
    accepted_artifacts: Mapping[str, ArtifactAcceptanceReceiptV2]
    work_item_failures: Mapping[str, WorkItemFailureReceiptV1]
    executor_failures: Mapping[str, ExecutorFailureReceiptV1]
    certification_records: Mapping[str, LedgerRecord]
    candidate_assessment_records: Mapping[str, LedgerRecord]
    artifact_acceptance_records: Mapping[str, LedgerRecord]
    work_item_failure_records: Mapping[str, LedgerRecord]
    executor_failure_records: Mapping[str, LedgerRecord]

    def artifact_for_key(self, artifact_key_id: str) -> AcceptedArtifactV2 | None:
        receipt = self.accepted_artifacts.get(artifact_key_id)
        if receipt is None:
            return None
        return AcceptedArtifactV2(artifact_key_id, receipt.artifact_hash)

    def work_failure(self, work_item_id: str) -> WorkFailureStateV2 | None:
        if work_item_id in self._accepted_work_item_ids():
            return None
        explicit = self.work_item_failures.get(work_item_id)
        if explicit is not None:
            return WorkFailureStateV2(
                work_item_id,
                explicit.reason_code,
                explicit.identity,
            )
        for failure in self.executor_failures.values():
            if failure.trigger_work_item_id == work_item_id:
                return WorkFailureStateV2(
                    work_item_id,
                    "failed_executor_contract",
                    failure.identity,
                )
        return None

    def executor_failure(
        self, executor_contract_hash: str
    ) -> ExecutorFailureStateV2 | None:
        receipt = self.executor_failures.get(executor_contract_hash)
        if receipt is None:
            return None
        return ExecutorFailureStateV2(
            executor_contract_hash,
            receipt.reason_code,
            receipt.identity,
        )

    def _accepted_work_item_ids(self) -> frozenset[str]:
        return frozenset(
            self.certification_work_items[receipt.certification_receipt_id].work_item_id
            for receipt in self.accepted_artifacts.values()
        )


@dataclass(slots=True)
class _Protocol22LedgerState:
    certifications: dict[str, CertificationReceiptV2]
    certifications_by_key: dict[
        str, tuple[CertificationReceiptV2, WorkItemV2]
    ]
    certification_work_items: dict[str, WorkItemV2]
    candidate_assessments: dict[str, CandidateAssessmentReceiptV1]
    candidate_assessments_by_candidate: dict[str, CandidateAssessmentReceiptV1]
    accepted_artifacts: dict[str, ArtifactAcceptanceReceiptV2]
    work_item_failures: dict[str, WorkItemFailureReceiptV1]
    executor_failures: dict[str, ExecutorFailureReceiptV1]
    certification_records_by_key: dict[str, LedgerRecord]
    candidate_records_by_candidate: dict[str, LedgerRecord]
    artifact_records_by_key: dict[str, LedgerRecord]
    work_failure_records_by_item: dict[str, LedgerRecord]
    executor_failure_records_by_contract: dict[str, LedgerRecord]

    @classmethod
    def empty(cls) -> "_Protocol22LedgerState":
        return cls({}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {})

    def consume(self, record: LedgerRecord, object_store: ObjectStore) -> None:
        try:
            if record.type == "certification":
                self._consume_certification(record, object_store)
            elif record.type == "candidate_assessment":
                self._consume_candidate_assessment(record, object_store)
            elif record.type == "artifact":
                self._consume_artifact(record, object_store)
            elif record.type == "work_item_failure":
                self._consume_work_failure(record, object_store)
            elif record.type == "executor_failure":
                self._consume_executor_failure(record, object_store)
            else:
                raise ReV2LedgerError(
                    f"unknown protocol-2.2 ledger record type: {record.type!r}"
                )
        except ReV2LedgerError:
            raise
        except (Protocol22SchemaError, TypeError, ValueError) as exc:
            raise ReV2LedgerError(
                f"invalid {record.type} receipt: {exc}"
            ) from exc

    def _consume_certification(
        self, record: LedgerRecord, object_store: ObjectStore
    ) -> None:
        payload = exact_object(
            record.payload,
            frozenset({"receipt", "work_item"}),
            "certification record payload",
        )
        receipt = CertificationReceiptV2.from_json_dict(payload["receipt"])
        work_item = WorkItemV2.from_json_dict(payload["work_item"])
        key = receipt.certification_key
        if key.artifact_key != work_item.output_key:
            raise ReV2LedgerError(
                "certification key does not match immutable work item output key"
            )
        if (
            key.verifier_id != work_item.verifier_id
            or key.verifier_version != work_item.verifier_version
            or key.verifier_implementation_digest
            != work_item.verifier_implementation_digest
        ):
            raise ReV2LedgerError(
                "certification verifier does not match immutable work item"
            )
        if key.audit_epoch_id is not None:
            raise ReV2LedgerError(
                "protocol 2.2 baseline certification requires a null audit epoch"
            )
        if work_item.work_item_id in self.work_item_failures:
            raise ReV2LedgerError("certification follows terminal work-item failure")
        if work_item.executor_contract_hash in self.executor_failures:
            raise ReV2LedgerError("certification follows failed executor authority")
        object_store.verify(key.artifact_hash)
        key_id = key.identity
        existing = self.certifications_by_key.get(key_id)
        if existing is not None:
            if existing != (receipt, work_item):
                raise ReV2LedgerError(
                    "conflicting certification receipt for certification key"
                )
            return
        by_identity = self.certifications.get(receipt.identity)
        if by_identity is not None and by_identity != receipt:
            raise ReV2LedgerError("conflicting certification receipt identity")
        self.certifications[receipt.identity] = receipt
        self.certifications_by_key[key_id] = (receipt, work_item)
        self.certification_work_items[receipt.identity] = work_item
        self.certification_records_by_key[key_id] = record

    def _consume_candidate_assessment(
        self, record: LedgerRecord, object_store: ObjectStore
    ) -> None:
        receipt = CandidateAssessmentReceiptV1.from_json_dict(record.payload)
        object_store.verify(receipt.execution_capture_hash)
        if receipt.normalized_authorial_payload_hash is not None:
            object_store.verify(receipt.normalized_authorial_payload_hash)
        if receipt.certification_receipt_id is not None:
            certification = self.certifications.get(
                receipt.certification_receipt_id
            )
            if certification is None:
                raise ReV2LedgerError(
                    "candidate assessment requires a preceding certification"
                )
            if not isinstance(
                certification.assessment, CompactCertificationAssessmentV2
            ):
                raise ReV2LedgerError(
                    "candidate assessment requires a compact certification"
                )
            work_item = self.certification_work_items[certification.identity]
            if (
                receipt.work_item_id != work_item.work_item_id
                or receipt.artifact_hash
                != certification.certification_key.artifact_hash
            ):
                raise ReV2LedgerError(
                    "candidate assessment does not match certification authority"
                )
            expected_verdict = (
                "accepted" if receipt.outcome == "certified" else "rejected"
            )
            if certification.verdict != expected_verdict:
                raise ReV2LedgerError(
                    "candidate assessment outcome disagrees with certification"
                )
            object_store.verify(certification.certification_key.artifact_hash)
        existing = self.candidate_assessments_by_candidate.get(
            receipt.candidate_id
        )
        if existing is not None:
            if existing != receipt:
                raise ReV2LedgerError(
                    "conflicting candidate-assessment receipt for candidate"
                )
            return
        by_identity = self.candidate_assessments.get(receipt.identity)
        if by_identity is not None and by_identity != receipt:
            raise ReV2LedgerError("conflicting candidate-assessment identity")
        self.candidate_assessments[receipt.identity] = receipt
        self.candidate_assessments_by_candidate[receipt.candidate_id] = receipt
        self.candidate_records_by_candidate[receipt.candidate_id] = record

    def _consume_artifact(
        self, record: LedgerRecord, object_store: ObjectStore
    ) -> None:
        receipt = ArtifactAcceptanceReceiptV2.from_json_dict(record.payload)
        certification = self.certifications.get(receipt.certification_receipt_id)
        if certification is None:
            raise ReV2LedgerError(
                "artifact acceptance requires a preceding certification"
            )
        if certification.verdict != "accepted":
            raise ReV2LedgerError(
                "artifact acceptance requires an accepted certification"
            )
        key = certification.certification_key
        if receipt.artifact_key != key.artifact_key or receipt.artifact_hash != key.artifact_hash:
            raise ReV2LedgerError(
                "artifact acceptance does not match certification authority"
            )
        work_item = self.certification_work_items[certification.identity]
        if work_item.work_item_id in self.work_item_failures:
            raise ReV2LedgerError("artifact acceptance follows work-item failure")
        if work_item.executor_contract_hash in self.executor_failures:
            raise ReV2LedgerError("artifact acceptance follows executor failure")
        if isinstance(certification.assessment, CompactCertificationAssessmentV2):
            matching = tuple(
                assessment
                for assessment in self.candidate_assessments.values()
                if assessment.certification_receipt_id == certification.identity
                and assessment.outcome == "certified"
                and assessment.work_item_id == work_item.work_item_id
                and assessment.artifact_hash == receipt.artifact_hash
            )
            if not matching:
                raise ReV2LedgerError(
                    "provider artifact acceptance requires a certified candidate assessment"
                )
        elif any(
            assessment.certification_receipt_id == certification.identity
            for assessment in self.candidate_assessments.values()
        ):
            raise ReV2LedgerError(
                "deterministic artifact acceptance requires null candidate assessment"
            )
        object_store.verify(receipt.artifact_hash)
        key_id = receipt.artifact_key.identity
        existing = self.accepted_artifacts.get(key_id)
        if existing is not None:
            if existing != receipt:
                raise ReV2LedgerError(
                    "conflicting artifact-acceptance receipt for artifact key"
                )
            return
        self.accepted_artifacts[key_id] = receipt
        self.artifact_records_by_key[key_id] = record

    def _consume_work_failure(
        self, record: LedgerRecord, object_store: ObjectStore
    ) -> None:
        receipt = WorkItemFailureReceiptV1.from_json_dict(record.payload)
        if receipt.execution_capture_hash is not None:
            object_store.verify(receipt.execution_capture_hash)
        if (
            receipt.candidate_id is not None
            and receipt.candidate_assessment_id is None
        ):
            object_store.verify(receipt.candidate_id)
        persisted_candidates = tuple(
            assessment
            for assessment in self.candidate_assessments.values()
            if assessment.work_item_id == receipt.work_item_id
            and assessment.execution_capture_hash == receipt.execution_capture_hash
        )
        if receipt.candidate_assessment_id is None and persisted_candidates:
            raise ReV2LedgerError(
                "work-item failure candidate fields are required for a persisted candidate"
            )
        if receipt.candidate_assessment_id is not None:
            assessment = self.candidate_assessments.get(
                receipt.candidate_assessment_id
            )
            if assessment is None:
                raise ReV2LedgerError(
                    "work-item failure requires a preceding candidate assessment"
                )
            if assessment.outcome == "certified":
                raise ReV2LedgerError(
                    "a certified candidate cannot authorize work-item failure"
                )
            if (
                assessment.candidate_id != receipt.candidate_id
                or assessment.work_item_id != receipt.work_item_id
                or assessment.execution_capture_hash
                != receipt.execution_capture_hash
            ):
                raise ReV2LedgerError(
                    "work-item failure does not match candidate assessment"
                )
        if self._work_is_accepted(receipt.work_item_id):
            raise ReV2LedgerError("accepted work cannot receive a failure receipt")
        if any(
            failure.trigger_work_item_id == receipt.work_item_id
            for failure in self.executor_failures.values()
        ):
            raise ReV2LedgerError(
                "work-item failure conflicts with executor trigger failure"
            )
        existing = self.work_item_failures.get(receipt.work_item_id)
        if existing is not None:
            if existing != receipt:
                raise ReV2LedgerError(
                    "conflicting work-item-failure receipt for work item"
                )
            return
        self.work_item_failures[receipt.work_item_id] = receipt
        self.work_failure_records_by_item[receipt.work_item_id] = record

    def _consume_executor_failure(
        self, record: LedgerRecord, object_store: ObjectStore
    ) -> None:
        receipt = ExecutorFailureReceiptV1.from_json_dict(record.payload)
        if receipt.execution_capture_hash is not None:
            object_store.verify(receipt.execution_capture_hash)
        if receipt.trigger_work_item_id in self.work_item_failures:
            raise ReV2LedgerError(
                "executor trigger conflicts with work-item failure authority"
            )
        existing = self.executor_failures.get(receipt.executor_contract_hash)
        if existing is not None:
            if existing != receipt:
                raise ReV2LedgerError(
                    "conflicting executor-failure receipt for executor contract"
                )
            return
        self.executor_failures[receipt.executor_contract_hash] = receipt
        self.executor_failure_records_by_contract[
            receipt.executor_contract_hash
        ] = record

    def _work_is_accepted(self, work_item_id: str) -> bool:
        return any(
            self.certification_work_items[receipt.certification_receipt_id].work_item_id
            == work_item_id
            for receipt in self.accepted_artifacts.values()
        )

    def idempotent_record(
        self,
        history: tuple[LedgerRecord, ...],
        record_type: str,
        payload: Mapping[str, object],
    ) -> LedgerRecord | None:
        del history
        if record_type == "certification":
            raw = exact_object(
                payload,
                frozenset({"receipt", "work_item"}),
                "certification record payload",
            )
            receipt = CertificationReceiptV2.from_json_dict(raw["receipt"])
            work_item = WorkItemV2.from_json_dict(raw["work_item"])
            key_id = receipt.certification_key.identity
            existing = self.certifications_by_key.get(key_id)
            if existing is None:
                return None
            if existing != (receipt, work_item):
                raise ReV2LedgerError(
                    "conflicting certification receipt for certification key"
                )
            return self.certification_records_by_key[key_id]
        if record_type == "candidate_assessment":
            receipt = CandidateAssessmentReceiptV1.from_json_dict(payload)
            existing = self.candidate_assessments_by_candidate.get(
                receipt.candidate_id
            )
            if existing is None:
                return None
            if existing != receipt:
                raise ReV2LedgerError(
                    "conflicting candidate-assessment receipt for candidate"
                )
            return self.candidate_records_by_candidate[receipt.candidate_id]
        if record_type == "artifact":
            receipt = ArtifactAcceptanceReceiptV2.from_json_dict(payload)
            key_id = receipt.artifact_key.identity
            existing = self.accepted_artifacts.get(key_id)
            if existing is None:
                return None
            if existing != receipt:
                raise ReV2LedgerError(
                    "conflicting artifact-acceptance receipt for artifact key"
                )
            return self.artifact_records_by_key[key_id]
        if record_type == "work_item_failure":
            receipt = WorkItemFailureReceiptV1.from_json_dict(payload)
            existing = self.work_item_failures.get(receipt.work_item_id)
            if existing is None:
                return None
            if existing != receipt:
                raise ReV2LedgerError(
                    "conflicting work-item-failure receipt for work item"
                )
            return self.work_failure_records_by_item[receipt.work_item_id]
        if record_type == "executor_failure":
            receipt = ExecutorFailureReceiptV1.from_json_dict(payload)
            existing = self.executor_failures.get(receipt.executor_contract_hash)
            if existing is None:
                return None
            if existing != receipt:
                raise ReV2LedgerError(
                    "conflicting executor-failure receipt for executor contract"
                )
            return self.executor_failure_records_by_contract[
                receipt.executor_contract_hash
            ]
        raise ReV2LedgerError(
            f"unknown protocol-2.2 ledger record type: {record_type!r}"
        )

    def view(self) -> Protocol22LedgerView:
        certification_records = {
            receipt.identity: self.certification_records_by_key[key_id]
            for key_id, (receipt, _work_item) in self.certifications_by_key.items()
        }
        candidate_records = {
            receipt.identity: self.candidate_records_by_candidate[candidate_id]
            for candidate_id, receipt in self.candidate_assessments_by_candidate.items()
        }
        artifact_records = {
            receipt.identity: self.artifact_records_by_key[key_id]
            for key_id, receipt in self.accepted_artifacts.items()
        }
        return Protocol22LedgerView(
            certifications=MappingProxyType(dict(self.certifications)),
            certification_work_items=MappingProxyType(
                dict(self.certification_work_items)
            ),
            candidate_assessments=MappingProxyType(
                dict(self.candidate_assessments)
            ),
            accepted_artifacts=MappingProxyType(dict(self.accepted_artifacts)),
            work_item_failures=MappingProxyType(dict(self.work_item_failures)),
            executor_failures=MappingProxyType(dict(self.executor_failures)),
            certification_records=MappingProxyType(certification_records),
            candidate_assessment_records=MappingProxyType(candidate_records),
            artifact_acceptance_records=MappingProxyType(artifact_records),
            work_item_failure_records=MappingProxyType(
                dict(self.work_failure_records_by_item)
            ),
            executor_failure_records=MappingProxyType(
                dict(self.executor_failure_records_by_contract)
            ),
        )


class _Protocol22LedgerProtocol(LedgerProtocol[Protocol22LedgerView]):
    def new_state(self) -> _Protocol22LedgerState:
        return _Protocol22LedgerState.empty()

    def canonical_payload(
        self, record_type: str, value: object
    ) -> Mapping[str, object]:
        try:
            if record_type == "certification":
                raw = exact_object(
                    value,
                    frozenset({"receipt", "work_item"}),
                    "certification record payload",
                )
                receipt = CertificationReceiptV2.from_json_dict(raw["receipt"])
                work_item = WorkItemV2.from_json_dict(raw["work_item"])
                return {
                    "receipt": receipt.to_json_dict(),
                    "work_item": work_item.to_json_dict(),
                }
            decoders = {
                "candidate_assessment": CandidateAssessmentReceiptV1.from_json_dict,
                "artifact": ArtifactAcceptanceReceiptV2.from_json_dict,
                "work_item_failure": WorkItemFailureReceiptV1.from_json_dict,
                "executor_failure": ExecutorFailureReceiptV1.from_json_dict,
            }
            decoder = decoders.get(record_type)
            if decoder is None:
                raise ReV2LedgerError(
                    f"unknown protocol-2.2 ledger record type: {record_type!r}"
                )
            return decoder(value).to_json_dict()
        except ReV2LedgerError:
            raise
        except (Protocol22SchemaError, TypeError, ValueError) as exc:
            raise ReV2LedgerError(
                f"invalid {record_type} ledger payload: {exc}"
            ) from exc


PROTOCOL_22_LEDGER_PROTOCOL = _Protocol22LedgerProtocol()


class Protocol22Ledger(DurableLedger[Protocol22LedgerView]):
    """Typed protocol-2.2 facade over the common immutable ledger file."""

    def __init__(self, path: Path | ReV2Paths, object_store: ObjectStore) -> None:
        super().__init__(
            path.ledger if isinstance(path, ReV2Paths) else Path(path),
            object_store,
            PROTOCOL_22_LEDGER_PROTOCOL,
        )

    def record_certification(
        self, receipt: CertificationReceiptV2, work_item: WorkItemV2
    ) -> LedgerRecord:
        if not isinstance(receipt, CertificationReceiptV2):
            raise ReV2LedgerError("receipt must be a CertificationReceiptV2")
        if not isinstance(work_item, WorkItemV2):
            raise ReV2LedgerError("work_item must be a WorkItemV2")
        return self._append(
            "certification",
            {
                "receipt": receipt.to_json_dict(),
                "work_item": work_item.to_json_dict(),
            },
        )

    def record_candidate_assessment(
        self, receipt: CandidateAssessmentReceiptV1
    ) -> LedgerRecord:
        if not isinstance(receipt, CandidateAssessmentReceiptV1):
            raise ReV2LedgerError(
                "receipt must be a CandidateAssessmentReceiptV1"
            )
        return self._append("candidate_assessment", receipt.to_json_dict())

    def record_artifact_acceptance(
        self, receipt: ArtifactAcceptanceReceiptV2
    ) -> LedgerRecord:
        if not isinstance(receipt, ArtifactAcceptanceReceiptV2):
            raise ReV2LedgerError(
                "receipt must be an ArtifactAcceptanceReceiptV2"
            )
        return self._append("artifact", receipt.to_json_dict())

    def record_work_item_failure(
        self, receipt: WorkItemFailureReceiptV1
    ) -> LedgerRecord:
        if not isinstance(receipt, WorkItemFailureReceiptV1):
            raise ReV2LedgerError(
                "receipt must be a WorkItemFailureReceiptV1"
            )
        return self._append("work_item_failure", receipt.to_json_dict())

    def record_executor_failure(
        self, receipt: ExecutorFailureReceiptV1
    ) -> LedgerRecord:
        if not isinstance(receipt, ExecutorFailureReceiptV1):
            raise ReV2LedgerError(
                "receipt must be an ExecutorFailureReceiptV1"
            )
        return self._append("executor_failure", receipt.to_json_dict())


__all__ = (
    "ExecutorFailureReceiptV1",
    "PROTOCOL_22_LEDGER_PROTOCOL",
    "Protocol22Ledger",
    "Protocol22LedgerReceiptError",
    "Protocol22LedgerView",
    "WorkItemFailureReceiptV1",
)
