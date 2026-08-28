"""Typed protocol-2.7 authority over the shared durable ledger envelope."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar, Mapping

from harness.re_v2.canonical import content_digest
from harness.re_v2.ledger import (
    DurableLedger,
    LedgerProtocol,
    LedgerRecord,
    ObjectStore,
    ReV2LedgerError,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    safe_id,
)

from .inputs import ValidatedProtocol27Inputs
from .model import (
    PartialSourceAcceptanceV1,
    PublicationDescriptorV1,
    SynthesisRootV1,
    SynthesisWorkItemV1,
)
from .runtime import (
    Protocol27RuntimeError,
    SynthesisArtifactAcceptanceV1,
    SynthesisAssessmentV1,
    SynthesisCertificationV1,
)


class Protocol27LedgerModelError(ValueError):
    """Raised when a protocol-2.7 ledger-only receipt is invalid."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol27LedgerModelError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol27LedgerModelError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class SynthesisCheckpointAdoptionReceiptV1:
    schema_version: int
    origin_run_id: str
    work_item_id: str
    artifact_key_id: str
    artifact_hash: str
    certification_id: str
    acceptance_receipt_id: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "origin_run_id",
        "work_item_id",
        "artifact_key_id",
        "artifact_hash",
        "certification_id",
        "acceptance_receipt_id",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "checkpoint adoption schema")
        _schema(safe_id, self.origin_run_id, "checkpoint origin run ID")
        for field in self.FIELDS[2:]:
            _schema(digest_value, getattr(self, field), f"checkpoint adoption {field}")

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisCheckpointAdoptionReceiptV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SynthesisMaterializationReceiptV1:
    schema_version: int
    synthesis_root_id: str
    materialization_manifest_id: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "synthesis_root_id",
        "materialization_manifest_id",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "synthesis materialization schema")
        for field in self.FIELDS[1:]:
            _schema(digest_value, getattr(self, field), f"materialization {field}")

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisMaterializationReceiptV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


_DECODERS = {
    "partial_source_acceptance_v1": PartialSourceAcceptanceV1.from_json_dict,
    "synthesis_candidate_assessment_v1": SynthesisAssessmentV1.from_json_dict,
    "synthesis_certification_v1": SynthesisCertificationV1.from_json_dict,
    "synthesis_artifact_acceptance_v1": SynthesisArtifactAcceptanceV1.from_json_dict,
    "synthesis_checkpoint_adoption_v1": (
        SynthesisCheckpointAdoptionReceiptV1.from_json_dict
    ),
    "synthesis_root_v1": SynthesisRootV1.from_json_dict,
    "synthesis_materialization_v1": SynthesisMaterializationReceiptV1.from_json_dict,
    "publication_descriptor_v1": PublicationDescriptorV1.from_json_dict,
}


@dataclass(frozen=True, slots=True)
class Protocol27LedgerView:
    partial_acceptances: Mapping[str, PartialSourceAcceptanceV1]
    candidate_assessments: Mapping[str, SynthesisAssessmentV1]
    certifications: Mapping[str, SynthesisCertificationV1]
    accepted_artifacts: Mapping[str, SynthesisArtifactAcceptanceV1]
    accepted_work_items: Mapping[str, SynthesisWorkItemV1]
    checkpoint_adoptions: Mapping[str, SynthesisCheckpointAdoptionReceiptV1]
    synthesis_root: SynthesisRootV1 | None
    materialization: SynthesisMaterializationReceiptV1 | None
    publication: PublicationDescriptorV1 | None
    records: Mapping[tuple[str, str], LedgerRecord]


@dataclass(slots=True)
class _Protocol27LedgerState:
    inputs: ValidatedProtocol27Inputs
    partial_acceptances: dict[str, PartialSourceAcceptanceV1]
    candidate_assessments: dict[str, SynthesisAssessmentV1]
    certifications: dict[str, SynthesisCertificationV1]
    accepted_artifacts: dict[str, SynthesisArtifactAcceptanceV1]
    accepted_work_items: dict[str, SynthesisWorkItemV1]
    checkpoint_adoptions: dict[str, SynthesisCheckpointAdoptionReceiptV1]
    synthesis_root: SynthesisRootV1 | None
    materialization: SynthesisMaterializationReceiptV1 | None
    publication: PublicationDescriptorV1 | None
    models: dict[tuple[str, str], object]
    records: dict[tuple[str, str], LedgerRecord]

    @classmethod
    def empty(cls, inputs: ValidatedProtocol27Inputs) -> "_Protocol27LedgerState":
        return cls(inputs, {}, {}, {}, {}, {}, {}, None, None, None, {}, {})

    def consume(self, record: LedgerRecord, object_store: ObjectStore) -> None:
        try:
            model = _decode(record.type, record.payload)
            key = _model_key(record.type, model)
            existing = self.models.get((record.type, key))
            if existing is not None:
                if existing != model:
                    raise ReV2LedgerError(
                        f"conflicting {record.type.replace('_', ' ')} authority"
                    )
                return
            self._validate_and_add(record.type, model, object_store)
            self.models[(record.type, key)] = model
            self.records[(record.type, key)] = record
        except ReV2LedgerError:
            raise
        except Exception as exc:
            raise ReV2LedgerError(f"invalid {record.type} receipt: {exc}") from exc

    def _validate_and_add(
        self,
        record_type: str,
        model: object,
        object_store: ObjectStore,
    ) -> None:
        if record_type == "partial_source_acceptance_v1":
            receipt = model
            assert isinstance(receipt, PartialSourceAcceptanceV1)
            expected = {
                item.source_id: item for item in self.inputs.manifest.partial_acceptances
            }.get(receipt.source_id)
            if expected != receipt:
                raise ReV2LedgerError("partial acceptance differs from manifest authority")
            self.partial_acceptances[receipt.source_id] = receipt
            return
        if record_type == "synthesis_candidate_assessment_v1":
            assessment = model
            assert isinstance(assessment, SynthesisAssessmentV1)
            self.candidate_assessments[assessment.work_item_id] = assessment
            return
        if record_type == "synthesis_certification_v1":
            certification = model
            assert isinstance(certification, SynthesisCertificationV1)
            assessment = self.candidate_assessments.get(certification.work_item_id)
            if assessment is None:
                raise ReV2LedgerError("synthesis certification requires an assessment")
            if (
                assessment.candidate_hash != certification.candidate_hash
                or assessment.context_id != certification.context_id
                or assessment.outcome != "certified"
            ):
                raise ReV2LedgerError("synthesis certification differs from assessment")
            policy = self.inputs.graph.policy_catalog
            if (
                certification.verifier_id != policy.verifier_id
                or certification.verifier_version != policy.verifier_version
                or certification.verifier_authority_hash
                != policy.implementation_authority.verifier_authority_hash
            ):
                raise ReV2LedgerError(
                    "synthesis certification differs from verifier authority"
                )
            object_store.verify(certification.artifact_hash)
            self.certifications[certification.artifact_key_id] = certification
            return
        if record_type == "synthesis_artifact_acceptance_v1":
            acceptance = model
            assert isinstance(acceptance, SynthesisArtifactAcceptanceV1)
            key_id = acceptance.artifact_key.artifact_key_id
            certification = self.certifications.get(key_id)
            if certification is None:
                raise ReV2LedgerError("artifact acceptance requires certification")
            if (
                acceptance.work_item_id != certification.work_item_id
                or acceptance.artifact_hash != certification.artifact_hash
                or acceptance.certification_id != certification.identity
            ):
                raise ReV2LedgerError("artifact acceptance differs from certification")
            expected_work_item = self._expected_work_item(acceptance)
            if expected_work_item.work_item_id != acceptance.work_item_id:
                raise ReV2LedgerError(
                    "artifact acceptance differs from graph work-item authority"
                )
            self._validate_dependencies(acceptance, object_store)
            object_store.verify(acceptance.artifact_hash)
            self.accepted_artifacts[key_id] = acceptance
            self.accepted_work_items[key_id] = expected_work_item
            return
        if record_type == "synthesis_checkpoint_adoption_v1":
            adoption = model
            assert isinstance(adoption, SynthesisCheckpointAdoptionReceiptV1)
            acceptance = self.accepted_artifacts.get(adoption.artifact_key_id)
            if acceptance is None or (
                acceptance.work_item_id,
                acceptance.artifact_hash,
                acceptance.certification_id,
                acceptance.identity,
            ) != (
                adoption.work_item_id,
                adoption.artifact_hash,
                adoption.certification_id,
                adoption.acceptance_receipt_id,
            ):
                raise ReV2LedgerError("checkpoint adoption requires accepted authority")
            self.checkpoint_adoptions[adoption.work_item_id] = adoption
            return
        if record_type == "synthesis_root_v1":
            root = model
            assert isinstance(root, SynthesisRootV1)
            self._validate_root(root, object_store)
            self.synthesis_root = root
            return
        if record_type == "synthesis_materialization_v1":
            materialization = model
            assert isinstance(materialization, SynthesisMaterializationReceiptV1)
            if (
                self.synthesis_root is None
                or materialization.synthesis_root_id != self.synthesis_root.identity
            ):
                raise ReV2LedgerError("materialization requires the synthesis root")
            object_store.verify(materialization.materialization_manifest_id)
            self.materialization = materialization
            return
        if record_type == "publication_descriptor_v1":
            descriptor = model
            assert isinstance(descriptor, PublicationDescriptorV1)
            if self.materialization is None or self.synthesis_root is None:
                raise ReV2LedgerError("publication requires materialization")
            if (
                descriptor.run_id != self.inputs.manifest.run_id
                or descriptor.synthesis_root_id != self.synthesis_root.identity
                or descriptor.materialization_manifest_id
                != self.materialization.materialization_manifest_id
                or descriptor.synthesis_policy_hash
                != self.inputs.manifest.synthesis_policy_hash
            ):
                raise ReV2LedgerError("publication descriptor authority mismatch")
            object_store.verify(descriptor.identity)
            self.publication = descriptor
            return
        raise ReV2LedgerError(f"unknown protocol-2.7 ledger record: {record_type}")

    def _validate_dependencies(
        self,
        acceptance: SynthesisArtifactAcceptanceV1,
        object_store: ObjectStore,
    ) -> None:
        fixed = {
            item.identity: item.object_hash
            for item in self.inputs.source_overview_catalog.projections
        }
        for dependency in acceptance.artifact_key.artifact_dependencies:
            if dependency.artifact_key_id in fixed:
                if fixed[dependency.artifact_key_id] != dependency.artifact_hash:
                    raise ReV2LedgerError("fixed dependency authority mismatch")
                object_store.verify(dependency.artifact_hash)
                continue
            accepted = self.accepted_artifacts.get(dependency.artifact_key_id)
            if accepted is None or accepted.artifact_hash != dependency.artifact_hash:
                raise ReV2LedgerError(
                    "synthesis artifact acceptance requires accepted dependency"
                )

    def _expected_work_item(
        self,
        acceptance: SynthesisArtifactAcceptanceV1,
    ) -> SynthesisWorkItemV1:
        key = acceptance.artifact_key
        matches = [
            node
            for node in self.inputs.graph.required_nodes
            if node.scope == key.scope and node.artifact_kind == key.artifact_kind
        ]
        if len(matches) != 1:
            raise ReV2LedgerError("artifact acceptance has no unique graph node")
        node = matches[0]
        template = next(
            item
            for item in self.inputs.graph.templates
            if item.template_id == node.template_id
        )
        dependencies = {
            item.artifact_key_id: item.artifact_hash
            for item in key.artifact_dependencies
        }
        fixed = {
            item.artifact_key_id: item.artifact_hash
            for item in node.fixed_artifact_dependencies
        }
        if (
            key.synthesis_policy_hash != self.inputs.graph.policy_catalog.identity
            or key.response_schema_hash
            != self.inputs.graph.response_schema_hashes[node.artifact_kind]
            or key.context_policy_hash != self.inputs.graph.context_policy_hash
            or key.non_artifact_dependency_hashes
            != node.non_artifact_dependency_hashes
            or key.debt_manifest_hashes != node.debt_manifest_hashes
            or not set(fixed).issubset(dependencies)
            or any(dependencies[item] != value for item, value in fixed.items())
            or len(dependencies)
            != len(fixed) + len(node.generated_dependency_node_ids)
        ):
            raise ReV2LedgerError(
                "artifact acceptance differs from graph authority"
            )
        return SynthesisWorkItemV1(
            schema_version=1,
            template_id=template.template_id,
            output_key=key,
            dependency_key_ids=tuple(sorted(dependencies)),
            executor_contract_hash=template.executor_contract_hash,
            verifier_id=template.verifier_id,
            verifier_version=template.verifier_version,
            verifier_authority_hash=template.verifier_authority_hash,
        )

    def _validate_root(self, root: SynthesisRootV1, object_store: ObjectStore) -> None:
        manifest = self.inputs.manifest
        implementation = self.inputs.graph.policy_catalog.implementation_authority
        expected_artifacts = {
            key_id: (item.artifact_hash, item.identity)
            for key_id, item in self.accepted_artifacts.items()
        }
        observed_artifacts = {
            item.artifact_key_id: (item.artifact_hash, item.acceptance_receipt_id)
            for item in root.accepted_artifacts
        }
        expected_debts = tuple(
            sorted(
                item.debt_manifest_hash
                for item in manifest.accepted_sources
                if item.debt_manifest_hash is not None
            )
        )
        if (
            len(self.accepted_artifacts) != len(self.inputs.graph.required_nodes)
            or observed_artifacts != expected_artifacts
            or root.accepted_source_outcome_ids
            != tuple(sorted(item.identity for item in manifest.accepted_sources))
            or root.partial_acceptance_receipt_ids
            != tuple(sorted(item.receipt_id for item in manifest.partial_acceptances))
            or root.debt_manifest_hashes != expected_debts
            or root.topology_id != self.inputs.graph.topology.identity
            or root.graph_id != self.inputs.graph.graph_id
            or root.producer_authority_hash
            != implementation.producer_authority_hash
            or root.verifier_authority_hash
            != implementation.verifier_authority_hash
            or root.synthesis_policy_hash != manifest.synthesis_policy_hash
            or root.input_quality != self.inputs.graph.root_specification.input_quality
        ):
            raise ReV2LedgerError("synthesis root does not close exact graph authority")
        object_store.verify(root.identity)

    def idempotent_record(
        self,
        history: tuple[LedgerRecord, ...],
        record_type: str,
        payload: Mapping[str, object],
    ) -> LedgerRecord | None:
        model = _decode(record_type, payload)
        key = _model_key(record_type, model)
        existing = self.models.get((record_type, key))
        if existing is None:
            return None
        if existing != model:
            label = record_type.replace("_", " ")
            if record_type == "synthesis_candidate_assessment_v1":
                label = "candidate assessment"
            raise ReV2LedgerError(f"conflicting {label} authority")
        record = self.records.get((record_type, key))
        if record is None or record not in history:
            raise ReV2LedgerError("validated receipt has no durable ledger record")
        return record

    def view(self) -> Protocol27LedgerView:
        return Protocol27LedgerView(
            partial_acceptances=MappingProxyType(dict(self.partial_acceptances)),
            candidate_assessments=MappingProxyType(dict(self.candidate_assessments)),
            certifications=MappingProxyType(dict(self.certifications)),
            accepted_artifacts=MappingProxyType(dict(self.accepted_artifacts)),
            accepted_work_items=MappingProxyType(dict(self.accepted_work_items)),
            checkpoint_adoptions=MappingProxyType(dict(self.checkpoint_adoptions)),
            synthesis_root=self.synthesis_root,
            materialization=self.materialization,
            publication=self.publication,
            records=MappingProxyType(dict(self.records)),
        )


def _decode(record_type: str, payload: object) -> object:
    decoder = _DECODERS.get(record_type)
    if decoder is None:
        raise ReV2LedgerError(f"unknown protocol-2.7 ledger record type: {record_type!r}")
    try:
        return decoder(payload)
    except (Protocol27RuntimeError, Protocol27LedgerModelError, TypeError, ValueError) as exc:
        raise ReV2LedgerError(f"invalid {record_type} payload: {exc}") from exc


def _model_key(record_type: str, model: object) -> str:
    if isinstance(model, PartialSourceAcceptanceV1):
        return model.source_id
    if isinstance(model, SynthesisAssessmentV1):
        return model.work_item_id
    if isinstance(model, SynthesisCertificationV1):
        return model.artifact_key_id
    if isinstance(model, SynthesisArtifactAcceptanceV1):
        return model.artifact_key.artifact_key_id
    if isinstance(model, SynthesisCheckpointAdoptionReceiptV1):
        return model.work_item_id
    if isinstance(model, SynthesisRootV1):
        return "root"
    if isinstance(model, SynthesisMaterializationReceiptV1):
        return model.synthesis_root_id
    if isinstance(model, PublicationDescriptorV1):
        return model.run_id
    raise ReV2LedgerError(f"unsupported protocol-2.7 ledger model: {record_type}")


@dataclass(frozen=True, slots=True)
class Protocol27LedgerProtocol(LedgerProtocol[Protocol27LedgerView]):
    inputs: ValidatedProtocol27Inputs

    def new_state(self) -> _Protocol27LedgerState:
        return _Protocol27LedgerState.empty(self.inputs)

    def canonical_payload(
        self,
        record_type: str,
        value: object,
    ) -> Mapping[str, object]:
        model = _decode(record_type, value)
        return model.to_json_dict()  # type: ignore[attr-defined, no-any-return]


class Protocol27Ledger(DurableLedger[Protocol27LedgerView]):
    def __init__(self, inputs: ValidatedProtocol27Inputs) -> None:
        if not isinstance(inputs, ValidatedProtocol27Inputs):
            raise ReV2LedgerError("Protocol27Ledger requires validated child inputs")
        object_store = ObjectStore(inputs.paths.objects)
        super().__init__(
            inputs.paths.ledger,
            object_store,
            Protocol27LedgerProtocol(inputs),
        )

    def record_partial_acceptance(
        self,
        receipt: PartialSourceAcceptanceV1,
    ) -> LedgerRecord:
        return self._append("partial_source_acceptance_v1", receipt.to_json_dict())

    def record_candidate_assessment(
        self,
        assessment: SynthesisAssessmentV1,
    ) -> LedgerRecord:
        return self._append(
            "synthesis_candidate_assessment_v1",
            assessment.to_json_dict(),
        )

    def record_synthesis_certification(
        self,
        certification: SynthesisCertificationV1,
    ) -> LedgerRecord:
        return self._append("synthesis_certification_v1", certification.to_json_dict())

    def record_synthesis_acceptance(
        self,
        acceptance: SynthesisArtifactAcceptanceV1,
    ) -> LedgerRecord:
        return self._append(
            "synthesis_artifact_acceptance_v1",
            acceptance.to_json_dict(),
        )

    def record_checkpoint_adoption(
        self,
        receipt: SynthesisCheckpointAdoptionReceiptV1,
    ) -> LedgerRecord:
        return self._append("synthesis_checkpoint_adoption_v1", receipt.to_json_dict())

    def record_synthesis_root(self, root: SynthesisRootV1) -> LedgerRecord:
        return self._append("synthesis_root_v1", root.to_json_dict())

    def record_materialization(
        self,
        receipt: SynthesisMaterializationReceiptV1,
    ) -> LedgerRecord:
        return self._append("synthesis_materialization_v1", receipt.to_json_dict())

    def record_publication(
        self,
        descriptor: PublicationDescriptorV1,
    ) -> LedgerRecord:
        return self._append("publication_descriptor_v1", descriptor.to_json_dict())


__all__ = (
    "Protocol27Ledger",
    "Protocol27LedgerModelError",
    "Protocol27LedgerProtocol",
    "Protocol27LedgerView",
    "SynthesisCheckpointAdoptionReceiptV1",
    "SynthesisMaterializationReceiptV1",
)
