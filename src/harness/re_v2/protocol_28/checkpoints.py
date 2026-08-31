"""Closed protocol-2.8 L4 checkpoint and selection authority."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar, Literal, Mapping

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    nonnegative_int,
    safe_id,
    sorted_unique_digests,
)
from harness.re_v2.protocol_28.artifacts import (
    ExhaustiveEvidenceSliceV1,
    ExhaustiveVerificationV1,
)
from harness.re_v2.protocol_28.execution import (
    L4AcceptanceReceiptV1,
    L4CertificationReceiptV1,
)
from harness.re_v2.protocol_28.graph import AcceptedExhaustiveSliceV1
from harness.re_v2.protocol_28.planning import SlicePlanEntryV1, SliceSpecV1


class Protocol28CheckpointError(Protocol22SchemaError):
    """Raised when L4 checkpoint authority is incomplete or cross-bound."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol28CheckpointError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol28CheckpointError(str(exc)) from exc


def _identity(value: object) -> str:
    return content_digest(value)


def _compatibility(
    slice_spec: SliceSpecV1,
    plan_entry: SlicePlanEntryV1,
    exhaustive_policy_id: str,
    artifact_policy_catalog_id: str,
) -> str:
    return _identity(
        {
            "slice_spec": slice_spec.to_json_dict(),
            "plan_entry": plan_entry.to_json_dict(),
            "exhaustive_policy_id": exhaustive_policy_id,
            "artifact_policy_catalog_id": artifact_policy_catalog_id,
            "producer_contract_hash": plan_entry.producer_contract_hash,
            "verifier_contract_hash": plan_entry.verifier_contract_hash,
        }
    )


@dataclass(frozen=True, slots=True)
class L4CheckpointExpectationV1:
    schema_version: int
    slice_spec: SliceSpecV1
    plan_entry: SlicePlanEntryV1
    exhaustive_policy_id: str
    artifact_policy_catalog_id: str

    def __post_init__(self) -> None:
        _schema(
            literal, self.schema_version, 1, "L4CheckpointExpectationV1.schema_version"
        )
        if not isinstance(self.slice_spec, SliceSpecV1) or not isinstance(
            self.plan_entry, SlicePlanEntryV1
        ):
            raise Protocol28CheckpointError(
                "checkpoint expectation requires slice and plan authority"
            )
        if self.slice_spec.plan_entry_id != self.plan_entry.identity:
            raise Protocol28CheckpointError(
                "checkpoint expectation slice does not realize plan entry"
            )
        for field in ("exhaustive_policy_id", "artifact_policy_catalog_id"):
            _schema(
                digest_value, getattr(self, field), f"L4CheckpointExpectationV1.{field}"
            )

    @property
    def output_artifact_key_id(self) -> str:
        return self.slice_spec.output_artifact_key_id

    @property
    def compatibility_id(self) -> str:
        return _compatibility(
            self.slice_spec,
            self.plan_entry,
            self.exhaustive_policy_id,
            self.artifact_policy_catalog_id,
        )


@dataclass(frozen=True, slots=True)
class CheckpointManifestV2:
    schema_version: int
    origin_run_id: str
    origin_manifest_hash: str
    origin_event_prefix_hash: str
    origin_ledger_prefix_hash: str
    slice_spec: SliceSpecV1
    plan_entry: SlicePlanEntryV1
    exhaustive_policy_id: str
    artifact_policy_catalog_id: str
    accepted_slice: AcceptedExhaustiveSliceV1
    candidate: ExhaustiveEvidenceSliceV1
    verification: ExhaustiveVerificationV1
    certification_receipt: L4CertificationReceiptV1
    acceptance_receipt: L4AcceptanceReceiptV1
    immutable_object_hashes: tuple[str, ...]
    immutable_object_byte_counts: Mapping[str, int]
    rank_vector: tuple[int, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "origin_run_id",
        "origin_manifest_hash",
        "origin_event_prefix_hash",
        "origin_ledger_prefix_hash",
        "slice_spec",
        "plan_entry",
        "exhaustive_policy_id",
        "artifact_policy_catalog_id",
        "accepted_slice",
        "candidate",
        "verification",
        "certification_receipt",
        "acceptance_receipt",
        "immutable_object_hashes",
        "immutable_object_byte_counts",
        "rank_vector",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 2, "CheckpointManifestV2.schema_version")
        _schema(safe_id, self.origin_run_id, "CheckpointManifestV2.origin_run_id")
        for field in (
            "origin_manifest_hash",
            "origin_event_prefix_hash",
            "origin_ledger_prefix_hash",
            "exhaustive_policy_id",
            "artifact_policy_catalog_id",
        ):
            _schema(digest_value, getattr(self, field), f"CheckpointManifestV2.{field}")
        typed = (
            (self.slice_spec, SliceSpecV1, "slice_spec"),
            (self.plan_entry, SlicePlanEntryV1, "plan_entry"),
            (self.accepted_slice, AcceptedExhaustiveSliceV1, "accepted_slice"),
            (self.candidate, ExhaustiveEvidenceSliceV1, "candidate"),
            (self.verification, ExhaustiveVerificationV1, "verification"),
            (
                self.certification_receipt,
                L4CertificationReceiptV1,
                "certification_receipt",
            ),
            (self.acceptance_receipt, L4AcceptanceReceiptV1, "acceptance_receipt"),
        )
        for value, expected, label in typed:
            if not isinstance(value, expected):
                raise Protocol28CheckpointError(
                    f"CheckpointManifestV2.{label} is invalid"
                )
        immutable = _schema(
            sorted_unique_digests,
            self.immutable_object_hashes,
            "CheckpointManifestV2.immutable_object_hashes",
        )
        if not isinstance(self.immutable_object_byte_counts, Mapping):
            raise Protocol28CheckpointError("checkpoint byte counts must be an object")
        counts: dict[str, int] = {}
        for key, value in self.immutable_object_byte_counts.items():
            digest = _schema(digest_value, key, "checkpoint byte-count key")
            counts[digest] = _schema(nonnegative_int, value, "checkpoint byte count")
        if set(counts) != set(immutable):
            raise Protocol28CheckpointError(
                "checkpoint inventory and byte counts disagree"
            )
        rank = tuple(self.rank_vector)
        if not rank or any(
            not isinstance(item, int) or isinstance(item, bool) or item < 0
            for item in rank
        ):
            raise Protocol28CheckpointError("checkpoint rank vector is invalid")
        object.__setattr__(self, "immutable_object_hashes", immutable)
        object.__setattr__(
            self,
            "immutable_object_byte_counts",
            MappingProxyType(dict(sorted(counts.items()))),
        )
        object.__setattr__(self, "rank_vector", rank)
        self._validate_bindings()

    def _validate_bindings(self) -> None:
        spec = self.slice_spec
        entry = self.plan_entry
        accepted = self.accepted_slice
        candidate = self.candidate
        verification = self.verification
        certification = self.certification_receipt
        acceptance = self.acceptance_receipt
        if spec.plan_entry_id != entry.identity:
            raise Protocol28CheckpointError(
                "checkpoint slice does not realize plan entry"
            )
        if (
            candidate.slice_spec_id != spec.identity
            or candidate.plan_entry_id != entry.identity
        ):
            raise Protocol28CheckpointError("checkpoint candidate scope is cross-bound")
        if (
            verification.verdict != "PASS"
            or verification.slice_spec_id != spec.identity
            or verification.candidate_id != candidate.identity
            or verification.verifier_policy_id != entry.verifier_contract_hash
        ):
            raise Protocol28CheckpointError(
                "checkpoint verifier authority is cross-bound"
            )
        if (
            accepted.slice_spec_id != spec.identity
            or accepted.plan_entry_id != entry.identity
            or accepted.output_artifact_key_id != spec.output_artifact_key_id
            or accepted.candidate_hash != candidate.identity
            or accepted.verifier_result_hash != verification.identity
            or accepted.certification_receipt_hash != certification.identity
            or accepted.acceptance_receipt_hash != acceptance.identity
        ):
            raise Protocol28CheckpointError("checkpoint accepted slice is cross-bound")
        if (
            certification.slice_spec_id != spec.identity
            or certification.plan_entry_id != entry.identity
            or certification.output_artifact_key_id != spec.output_artifact_key_id
            or certification.candidate_hash != candidate.identity
            or certification.verifier_result_hash != verification.identity
            or certification.producer_execution_capture_hash
            != accepted.producer_execution_capture_hash
            or certification.verifier_execution_capture_hash
            != accepted.verifier_execution_capture_hash
        ):
            raise Protocol28CheckpointError("checkpoint certification is cross-bound")
        if (
            acceptance.slice_spec_id != spec.identity
            or acceptance.output_artifact_key_id != spec.output_artifact_key_id
            or acceptance.candidate_hash != candidate.identity
            or acceptance.certification_receipt_hash != certification.identity
        ):
            raise Protocol28CheckpointError("checkpoint acceptance is cross-bound")
        required = {
            spec.identity,
            entry.identity,
            self.exhaustive_policy_id,
            self.artifact_policy_catalog_id,
            accepted.identity,
            candidate.identity,
            verification.identity,
            certification.identity,
            acceptance.identity,
            accepted.producer_execution_capture_hash,
            accepted.verifier_execution_capture_hash,
        }
        if not required <= set(self.immutable_object_hashes):
            raise Protocol28CheckpointError(
                "checkpoint immutable object inventory is incomplete"
            )

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def compatibility_id(self) -> str:
        return _compatibility(
            self.slice_spec,
            self.plan_entry,
            self.exhaustive_policy_id,
            self.artifact_policy_catalog_id,
        )

    def to_json_dict(self) -> dict[str, object]:
        nested = {
            "slice_spec": self.slice_spec.to_json_dict(),
            "plan_entry": self.plan_entry.to_json_dict(),
            "accepted_slice": self.accepted_slice.to_json_dict(),
            "candidate": self.candidate.to_json_dict(),
            "verification": self.verification.to_json_dict(),
            "certification_receipt": self.certification_receipt.to_json_dict(),
            "acceptance_receipt": self.acceptance_receipt.to_json_dict(),
        }
        return {
            "schema_version": self.schema_version,
            "origin_run_id": self.origin_run_id,
            "origin_manifest_hash": self.origin_manifest_hash,
            "origin_event_prefix_hash": self.origin_event_prefix_hash,
            "origin_ledger_prefix_hash": self.origin_ledger_prefix_hash,
            **nested,
            "exhaustive_policy_id": self.exhaustive_policy_id,
            "artifact_policy_catalog_id": self.artifact_policy_catalog_id,
            "immutable_object_hashes": list(self.immutable_object_hashes),
            "immutable_object_byte_counts": dict(self.immutable_object_byte_counts),
            "rank_vector": list(self.rank_vector),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CheckpointManifestV2":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            schema_version=raw["schema_version"],
            origin_run_id=raw["origin_run_id"],
            origin_manifest_hash=raw["origin_manifest_hash"],
            origin_event_prefix_hash=raw["origin_event_prefix_hash"],
            origin_ledger_prefix_hash=raw["origin_ledger_prefix_hash"],
            slice_spec=SliceSpecV1.from_json_dict(raw["slice_spec"]),
            plan_entry=SlicePlanEntryV1.from_json_dict(raw["plan_entry"]),
            exhaustive_policy_id=raw["exhaustive_policy_id"],
            artifact_policy_catalog_id=raw["artifact_policy_catalog_id"],
            accepted_slice=AcceptedExhaustiveSliceV1.from_json_dict(
                raw["accepted_slice"]
            ),
            candidate=ExhaustiveEvidenceSliceV1.from_json_dict(raw["candidate"]),
            verification=ExhaustiveVerificationV1.from_json_dict(raw["verification"]),
            certification_receipt=L4CertificationReceiptV1.from_json_dict(
                raw["certification_receipt"]
            ),
            acceptance_receipt=L4AcceptanceReceiptV1.from_json_dict(
                raw["acceptance_receipt"]
            ),
            immutable_object_hashes=raw["immutable_object_hashes"],
            immutable_object_byte_counts=raw["immutable_object_byte_counts"],
            rank_vector=raw["rank_vector"],
        )


@dataclass(frozen=True, slots=True)
class CheckpointSelectionEntryV2:
    output_artifact_key_id: str
    checkpoint_manifest_id: str
    accepted_slice_id: str
    source_kind: Literal["workspace_checkpoint"] = "workspace_checkpoint"

    def __post_init__(self) -> None:
        for field in (
            "output_artifact_key_id",
            "checkpoint_manifest_id",
            "accepted_slice_id",
        ):
            _schema(
                digest_value,
                getattr(self, field),
                f"CheckpointSelectionEntryV2.{field}",
            )
        _schema(
            literal,
            self.source_kind,
            "workspace_checkpoint",
            "CheckpointSelectionEntryV2.source_kind",
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "output_artifact_key_id": self.output_artifact_key_id,
            "checkpoint_manifest_id": self.checkpoint_manifest_id,
            "accepted_slice_id": self.accepted_slice_id,
            "source_kind": self.source_kind,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CheckpointSelectionEntryV2":
        fields = frozenset(
            {
                "output_artifact_key_id",
                "checkpoint_manifest_id",
                "accepted_slice_id",
                "source_kind",
            }
        )
        raw = _schema(exact_object, value, fields, cls.__name__)
        return cls(**{field: raw[field] for field in fields})


@dataclass(frozen=True, slots=True)
class CheckpointDispositionV2:
    checkpoint_manifest_id: str
    output_artifact_key_id: str
    disposition: Literal["rejected", "quarantined"]
    reason: str

    def __post_init__(self) -> None:
        _schema(
            digest_value,
            self.checkpoint_manifest_id,
            "CheckpointDispositionV2.checkpoint_manifest_id",
        )
        _schema(
            digest_value,
            self.output_artifact_key_id,
            "CheckpointDispositionV2.output_artifact_key_id",
        )
        if self.disposition not in {"rejected", "quarantined"}:
            raise Protocol28CheckpointError("checkpoint disposition is invalid")
        _schema(safe_id, self.reason, "CheckpointDispositionV2.reason")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "checkpoint_manifest_id": self.checkpoint_manifest_id,
            "output_artifact_key_id": self.output_artifact_key_id,
            "disposition": self.disposition,
            "reason": self.reason,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CheckpointDispositionV2":
        fields = frozenset(
            {
                "checkpoint_manifest_id",
                "output_artifact_key_id",
                "disposition",
                "reason",
            }
        )
        raw = _schema(exact_object, value, fields, cls.__name__)
        return cls(**{field: raw[field] for field in fields})


@dataclass(frozen=True, slots=True)
class CheckpointSelectionBundleV2:
    schema_version: int
    selected: tuple[CheckpointSelectionEntryV2, ...]
    rejected: tuple[CheckpointDispositionV2, ...]
    quarantined: tuple[CheckpointDispositionV2, ...]
    missing_output_artifact_key_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _schema(
            literal,
            self.schema_version,
            2,
            "CheckpointSelectionBundleV2.schema_version",
        )
        selected = tuple(self.selected)
        rejected = tuple(self.rejected)
        quarantined = tuple(self.quarantined)
        if any(not isinstance(item, CheckpointSelectionEntryV2) for item in selected):
            raise Protocol28CheckpointError("checkpoint selections are invalid")
        if any(
            not isinstance(item, CheckpointDispositionV2)
            for item in rejected + quarantined
        ):
            raise Protocol28CheckpointError("checkpoint dispositions are invalid")
        keys = tuple(item.output_artifact_key_id for item in selected)
        if keys != tuple(sorted(set(keys))):
            raise Protocol28CheckpointError(
                "checkpoint selections must be sorted and unique"
            )
        missing = _schema(
            sorted_unique_digests,
            self.missing_output_artifact_key_ids,
            "CheckpointSelectionBundleV2.missing_output_artifact_key_ids",
        )
        if set(keys) & set(missing):
            raise Protocol28CheckpointError(
                "selected and missing checkpoint keys overlap"
            )
        object.__setattr__(self, "selected", selected)
        object.__setattr__(self, "rejected", rejected)
        object.__setattr__(self, "quarantined", quarantined)
        object.__setattr__(self, "missing_output_artifact_key_ids", missing)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "selected": [item.to_json_dict() for item in self.selected],
            "rejected": [item.to_json_dict() for item in self.rejected],
            "quarantined": [item.to_json_dict() for item in self.quarantined],
            "missing_output_artifact_key_ids": list(
                self.missing_output_artifact_key_ids
            ),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CheckpointSelectionBundleV2":
        fields = frozenset(
            {
                "schema_version",
                "selected",
                "rejected",
                "quarantined",
                "missing_output_artifact_key_ids",
            }
        )
        raw = _schema(exact_object, value, fields, cls.__name__)
        for field in (
            "selected",
            "rejected",
            "quarantined",
            "missing_output_artifact_key_ids",
        ):
            if not isinstance(raw[field], (list, tuple)):
                raise Protocol28CheckpointError(
                    f"CheckpointSelectionBundleV2.{field} must be an array"
                )
        return cls(
            schema_version=raw["schema_version"],
            selected=tuple(
                CheckpointSelectionEntryV2.from_json_dict(item)
                for item in raw["selected"]
            ),
            rejected=tuple(
                CheckpointDispositionV2.from_json_dict(item) for item in raw["rejected"]
            ),
            quarantined=tuple(
                CheckpointDispositionV2.from_json_dict(item)
                for item in raw["quarantined"]
            ),
            missing_output_artifact_key_ids=tuple(
                raw["missing_output_artifact_key_ids"]
            ),
        )


__all__ = (
    "CheckpointDispositionV2",
    "CheckpointManifestV2",
    "CheckpointSelectionBundleV2",
    "CheckpointSelectionEntryV2",
    "L4CheckpointExpectationV1",
    "Protocol28CheckpointError",
)
