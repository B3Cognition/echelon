"""Complete selected-snapshot evidence authority for protocol 2.8."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import ClassVar, Literal, TypeVar

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError
from harness.re_v2.protocol_22.evidence import (
    PinnedSnapshotReaderV1,
    Protocol22EvidenceError,
)
from harness.re_v2.protocol_22.partition import (
    FileRecordV1,
    SourceDescriptorV1,
    WorkspacePartitionCatalogV1,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    nonnegative_int,
    one_of,
    positive_int,
    safe_id,
    safe_relative_path,
    sorted_unique_digests,
)
from harness.re_v2.protocol_24.model import SelectionScopeV1
from harness.re_v2.snapshot import CapturedSnapshot


_RAW_EVIDENCE_MAGIC = b"re-v2-l4-raw-v1\x00"
_TARGET_KINDS = frozenset({"domain", "source"})
_DISPOSITIONS = frozenset(
    {"proven_non_behavioral", "unsupported_behavioral_content"}
)
_T = TypeVar("_T")


class Protocol28EvidenceError(Protocol22SchemaError):
    """Raised when selected snapshot evidence is incomplete or inconsistent."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol28EvidenceError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol28EvidenceError(str(exc)) from exc


def _identity(value: object) -> str:
    return content_digest(canonical_json_bytes(value))


def _typed_tuple(
    value: object,
    expected_type: type[_T],
    field: str,
    *,
    key,
) -> tuple[_T, ...]:  # type: ignore[no-untyped-def]
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, expected_type) for item in value
    ):
        raise Protocol28EvidenceError(
            f"{field} must contain {expected_type.__name__} values"
        )
    result = tuple(value)
    keys = tuple(key(item) for item in result)
    if keys != tuple(sorted(set(keys))):
        raise Protocol28EvidenceError(f"{field} must be canonically sorted and unique")
    return result


def _sorted_unique_paths(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise Protocol28EvidenceError(f"{field} must be an array")
    result = tuple(_schema(safe_relative_path, item, field) for item in value)
    expected = tuple(sorted(set(result), key=lambda item: item.encode("utf-8")))
    if result != expected:
        raise Protocol28EvidenceError(f"{field} must be sorted and unique")
    return result


def _unique_digests(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise Protocol28EvidenceError(f"{field} must be an array")
    result = tuple(_schema(digest_value, item, field) for item in value)
    if len(result) != len(set(result)):
        raise Protocol28EvidenceError(f"{field} must be unique")
    return result


@dataclass(frozen=True, slots=True)
class EvidenceStagingPolicyV1:
    schema_version: int
    shard_byte_limit: int
    proven_non_behavioral_suffixes: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "shard_byte_limit",
        "proven_non_behavioral_suffixes",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "EvidenceStagingPolicyV1.schema_version")
        _schema(
            positive_int,
            self.shard_byte_limit,
            "EvidenceStagingPolicyV1.shard_byte_limit",
        )
        suffixes = self.proven_non_behavioral_suffixes
        if (
            not isinstance(suffixes, (list, tuple))
            or any(
                not isinstance(item, str)
                or len(item) < 2
                or not item.startswith(".")
                or item != item.lower()
                for item in suffixes
            )
        ):
            raise Protocol28EvidenceError(
                "EvidenceStagingPolicyV1 suffixes must be lowercase dotted strings"
            )
        canonical = tuple(sorted(set(suffixes)))
        if tuple(suffixes) != canonical:
            raise Protocol28EvidenceError(
                "EvidenceStagingPolicyV1 suffixes must be sorted and unique"
            )
        object.__setattr__(self, "proven_non_behavioral_suffixes", canonical)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "shard_byte_limit": self.shard_byte_limit,
            "proven_non_behavioral_suffixes": list(
                self.proven_non_behavioral_suffixes
            ),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "EvidenceStagingPolicyV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SnapshotEvidenceShardV1:
    schema_version: int
    source_id: str
    source_relative_path: str
    file_record_hash: str
    file_content_hash: str
    mode: str
    byte_start: int
    byte_end: int
    line_start: int
    column_start: int
    line_end: int
    column_end: int
    raw_hash: str
    raw_object_hash: str
    raw_bytes_base64: str
    membership_proof_id: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "source_id",
        "source_relative_path",
        "file_record_hash",
        "file_content_hash",
        "mode",
        "byte_start",
        "byte_end",
        "line_start",
        "column_start",
        "line_end",
        "column_end",
        "raw_hash",
        "raw_object_hash",
        "raw_bytes_base64",
        "membership_proof_id",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(safe_id, self.source_id, f"{label}.source_id")
        _schema(safe_relative_path, self.source_relative_path, f"{label}.source_relative_path")
        for field in (
            "file_record_hash",
            "file_content_hash",
            "raw_hash",
            "raw_object_hash",
            "membership_proof_id",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        if self.mode not in {"100644", "100755"}:
            raise Protocol28EvidenceError(f"{label}.mode must be a regular-file mode")
        for field in (
            "byte_start",
            "byte_end",
            "line_start",
            "column_start",
            "line_end",
            "column_end",
        ):
            _schema(nonnegative_int, getattr(self, field), f"{label}.{field}")
        if self.byte_start >= self.byte_end:
            raise Protocol28EvidenceError(f"{label} byte range must be nonempty")
        if min(self.line_start, self.column_start, self.line_end, self.column_end) < 1:
            raise Protocol28EvidenceError(f"{label} line/column positions are one-based")
        try:
            payload = base64.b64decode(self.raw_bytes_base64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise Protocol28EvidenceError(f"{label}.raw_bytes_base64 is invalid") from exc
        if base64.b64encode(payload).decode("ascii") != self.raw_bytes_base64:
            raise Protocol28EvidenceError(f"{label}.raw_bytes_base64 is not canonical")
        if len(payload) != self.byte_end - self.byte_start:
            raise Protocol28EvidenceError(f"{label} raw byte length disagrees with range")
        if content_digest(payload) != self.raw_hash:
            raise Protocol28EvidenceError(f"{label}.raw_hash does not match raw bytes")
        if content_digest(_RAW_EVIDENCE_MAGIC + payload) != self.raw_object_hash:
            raise Protocol28EvidenceError(
                f"{label}.raw_object_hash does not match staged raw envelope"
            )
        try:
            payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise Protocol28EvidenceError(f"{label} raw bytes must be valid UTF-8") from exc

    @property
    def raw_bytes(self) -> bytes:
        return base64.b64decode(self.raw_bytes_base64, validate=True)

    @property
    def shard_id(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def identity(self) -> str:
        return self.shard_id

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "SnapshotEvidenceShardV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class EmptyFileCoverageReceiptV1:
    schema_version: int
    source_id: str
    source_relative_path: str
    file_record_hash: str
    file_content_hash: str
    mode: str
    byte_count: int
    membership_proof_id: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "source_id",
        "source_relative_path",
        "file_record_hash",
        "file_content_hash",
        "mode",
        "byte_count",
        "membership_proof_id",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(safe_id, self.source_id, f"{label}.source_id")
        _schema(safe_relative_path, self.source_relative_path, f"{label}.source_relative_path")
        for field in ("file_record_hash", "file_content_hash", "membership_proof_id"):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        if self.mode not in {"100644", "100755"}:
            raise Protocol28EvidenceError(f"{label}.mode must be a regular-file mode")
        _schema(literal, self.byte_count, 0, f"{label}.byte_count")

    @property
    def receipt_id(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def identity(self) -> str:
        return self.receipt_id

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "EmptyFileCoverageReceiptV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class NonTextEvidenceDispositionV1:
    schema_version: int
    source_id: str
    source_relative_path: str
    file_record_hash: str
    file_content_hash: str
    mode: str
    object_kind: str
    text_status: str
    byte_count: int
    disposition: Literal[
        "proven_non_behavioral", "unsupported_behavioral_content"
    ]
    membership_proof_id: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "source_id",
        "source_relative_path",
        "file_record_hash",
        "file_content_hash",
        "mode",
        "object_kind",
        "text_status",
        "byte_count",
        "disposition",
        "membership_proof_id",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(safe_id, self.source_id, f"{label}.source_id")
        _schema(safe_relative_path, self.source_relative_path, f"{label}.source_relative_path")
        for field in ("file_record_hash", "file_content_hash", "membership_proof_id"):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        if self.mode not in {"100644", "100755", "120000", "160000"}:
            raise Protocol28EvidenceError(f"{label}.mode is unsupported")
        if self.object_kind not in {"regular", "symlink", "gitlink"}:
            raise Protocol28EvidenceError(f"{label}.object_kind is unsupported")
        if self.text_status not in {
            "contains_nul",
            "invalid_utf8",
            "non_regular",
        }:
            raise Protocol28EvidenceError(f"{label}.text_status must be non-text")
        _schema(nonnegative_int, self.byte_count, f"{label}.byte_count")
        _schema(one_of, self.disposition, _DISPOSITIONS, f"{label}.disposition")

    @property
    def disposition_id(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def identity(self) -> str:
        return self.disposition_id

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "NonTextEvidenceDispositionV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class TargetSnapshotEvidenceProjectionV1:
    schema_version: int
    target_kind: Literal["domain", "source"]
    source_id: str
    target_id: str
    target_partition_id: str
    target_content_id: str
    source_snapshot_id: str
    primary_shard_ids: tuple[str, ...]
    primary_empty_receipt_ids: tuple[str, ...]
    primary_nontext_disposition_ids: tuple[str, ...]
    supporting_shard_ids: tuple[str, ...]
    supporting_empty_receipt_ids: tuple[str, ...]
    supporting_nontext_disposition_ids: tuple[str, ...]
    membership_proof_ids: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "target_kind",
        "source_id",
        "target_id",
        "target_partition_id",
        "target_content_id",
        "source_snapshot_id",
        "primary_shard_ids",
        "primary_empty_receipt_ids",
        "primary_nontext_disposition_ids",
        "supporting_shard_ids",
        "supporting_empty_receipt_ids",
        "supporting_nontext_disposition_ids",
        "membership_proof_ids",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(one_of, self.target_kind, _TARGET_KINDS, f"{label}.target_kind")
        _schema(safe_id, self.source_id, f"{label}.source_id")
        _schema(safe_id, self.target_id, f"{label}.target_id")
        for field in (
            "target_partition_id",
            "target_content_id",
            "source_snapshot_id",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        for field in self.FIELDS[7:]:
            validator = (
                _unique_digests
                if field in {"primary_shard_ids", "supporting_shard_ids"}
                else sorted_unique_digests
            )
            object.__setattr__(
                self,
                field,
                _schema(validator, getattr(self, field), f"{label}.{field}"),
            )

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            **{field: getattr(self, field) for field in self.FIELDS[:7]},
            **{field: list(getattr(self, field)) for field in self.FIELDS[7:]},
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "TargetSnapshotEvidenceProjectionV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SnapshotEvidenceCatalogV1:
    schema_version: int
    source_snapshot_id: str
    partition_catalog_id: str
    selection_id: str
    policy_id: str
    shards: tuple[SnapshotEvidenceShardV1, ...]
    empty_receipts: tuple[EmptyFileCoverageReceiptV1, ...]
    nontext_dispositions: tuple[NonTextEvidenceDispositionV1, ...]
    projections: tuple[TargetSnapshotEvidenceProjectionV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "source_snapshot_id",
        "partition_catalog_id",
        "selection_id",
        "policy_id",
        "shards",
        "empty_receipts",
        "nontext_dispositions",
        "projections",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        for field in (
            "source_snapshot_id",
            "partition_catalog_id",
            "selection_id",
            "policy_id",
        ):
            _schema(digest_value, getattr(self, field), f"{label}.{field}")
        shards = _typed_tuple(
            self.shards,
            SnapshotEvidenceShardV1,
            f"{label}.shards",
            key=lambda item: (item.source_id, item.source_relative_path, item.byte_start),
        )
        empty = _typed_tuple(
            self.empty_receipts,
            EmptyFileCoverageReceiptV1,
            f"{label}.empty_receipts",
            key=lambda item: (item.source_id, item.source_relative_path),
        )
        nontext = _typed_tuple(
            self.nontext_dispositions,
            NonTextEvidenceDispositionV1,
            f"{label}.nontext_dispositions",
            key=lambda item: (item.source_id, item.source_relative_path),
        )
        projections = _typed_tuple(
            self.projections,
            TargetSnapshotEvidenceProjectionV1,
            f"{label}.projections",
            key=lambda item: (item.source_id, item.target_kind, item.target_id),
        )
        shard_ids = {item.shard_id for item in shards}
        empty_ids = {item.receipt_id for item in empty}
        disposition_ids = {item.disposition_id for item in nontext}
        proof_ids = {
            item.membership_proof_id for item in (*shards, *empty, *nontext)
        }
        for projection in projections:
            if projection.source_snapshot_id != self.source_snapshot_id:
                raise Protocol28EvidenceError(
                    "target projection snapshot does not match evidence catalog"
                )
            if not set(
                projection.primary_shard_ids + projection.supporting_shard_ids
            ).issubset(shard_ids):
                raise Protocol28EvidenceError("target projection references unknown shard")
            if not set(
                projection.primary_empty_receipt_ids
                + projection.supporting_empty_receipt_ids
            ).issubset(empty_ids):
                raise Protocol28EvidenceError(
                    "target projection references unknown empty-file receipt"
                )
            if not set(
                projection.primary_nontext_disposition_ids
                + projection.supporting_nontext_disposition_ids
            ).issubset(disposition_ids):
                raise Protocol28EvidenceError(
                    "target projection references unknown non-text disposition"
                )
            if not set(projection.membership_proof_ids).issubset(proof_ids):
                raise Protocol28EvidenceError(
                    "target projection references unknown membership proof"
                )
        object.__setattr__(self, "shards", shards)
        object.__setattr__(self, "empty_receipts", empty)
        object.__setattr__(self, "nontext_dispositions", nontext)
        object.__setattr__(self, "projections", projections)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def primary_shard_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                shard_id
                for projection in self.projections
                for shard_id in projection.primary_shard_ids
            )
        )

    def projection_for(self, target_id: str) -> TargetSnapshotEvidenceProjectionV1:
        matches = tuple(item for item in self.projections if item.target_id == target_id)
        if len(matches) != 1:
            raise Protocol28EvidenceError(
                f"snapshot evidence target {target_id!r} is missing or ambiguous"
            )
        return matches[0]

    def shard_by_id(self, shard_id: str) -> SnapshotEvidenceShardV1:
        matches = tuple(item for item in self.shards if item.shard_id == shard_id)
        if len(matches) != 1:
            raise Protocol28EvidenceError(f"snapshot evidence shard {shard_id!r} is missing")
        return matches[0]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_snapshot_id": self.source_snapshot_id,
            "partition_catalog_id": self.partition_catalog_id,
            "selection_id": self.selection_id,
            "policy_id": self.policy_id,
            "shards": [item.to_json_dict() for item in self.shards],
            "empty_receipts": [item.to_json_dict() for item in self.empty_receipts],
            "nontext_dispositions": [
                item.to_json_dict() for item in self.nontext_dispositions
            ],
            "projections": [item.to_json_dict() for item in self.projections],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SnapshotEvidenceCatalogV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        for field in ("shards", "empty_receipts", "nontext_dispositions", "projections"):
            if not isinstance(raw[field], (list, tuple)):
                raise Protocol28EvidenceError(
                    f"SnapshotEvidenceCatalogV1.{field} must be an array"
                )
        return cls(
            schema_version=raw["schema_version"],
            source_snapshot_id=raw["source_snapshot_id"],
            partition_catalog_id=raw["partition_catalog_id"],
            selection_id=raw["selection_id"],
            policy_id=raw["policy_id"],
            shards=tuple(
                SnapshotEvidenceShardV1.from_json_dict(item)
                for item in raw["shards"]
            ),
            empty_receipts=tuple(
                EmptyFileCoverageReceiptV1.from_json_dict(item)
                for item in raw["empty_receipts"]
            ),
            nontext_dispositions=tuple(
                NonTextEvidenceDispositionV1.from_json_dict(item)
                for item in raw["nontext_dispositions"]
            ),
            projections=tuple(
                TargetSnapshotEvidenceProjectionV1.from_json_dict(item)
                for item in raw["projections"]
            ),
        )


@dataclass(frozen=True, slots=True)
class _TargetAssignment:
    target_kind: Literal["domain", "source"]
    source: SourceDescriptorV1
    target_id: str
    target_partition_id: str
    target_content_id: str
    primary_paths: tuple[str, ...]
    supporting_paths: tuple[str, ...]


def split_utf8_ranges(payload: bytes, byte_limit: int) -> tuple[tuple[int, int], ...]:
    _schema(positive_int, byte_limit, "split_utf8_ranges.byte_limit")
    try:
        payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise Protocol28EvidenceError("snapshot evidence payload is not UTF-8") from exc
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < len(payload):
        end = min(start + byte_limit, len(payload))
        while end > start:
            try:
                payload[start:end].decode("utf-8", errors="strict")
                break
            except UnicodeDecodeError:
                end -= 1
        if end == start:
            raise Protocol28EvidenceError(
                "UTF-8 shard boundary cannot advance within byte limit"
            )
        line_break = payload.rfind(b"\n", start, end)
        if line_break >= start:
            end = line_break + 1
        ranges.append((start, end))
        start = end
    return tuple(ranges)


def read_staged_shard_bytes(
    object_store: ObjectStore,
    shard: SnapshotEvidenceShardV1,
) -> bytes:
    if not isinstance(object_store, ObjectStore):
        raise Protocol28EvidenceError("raw shard read requires an ObjectStore")
    if not isinstance(shard, SnapshotEvidenceShardV1):
        raise Protocol28EvidenceError(
            "raw shard read requires SnapshotEvidenceShardV1"
        )
    try:
        envelope = object_store.read_blob(shard.raw_object_hash)
    except ReV2LedgerError as exc:
        raise Protocol28EvidenceError(f"staged raw shard is unavailable: {exc}") from exc
    if not envelope.startswith(_RAW_EVIDENCE_MAGIC):
        raise Protocol28EvidenceError("staged raw shard envelope is invalid")
    payload = envelope[len(_RAW_EVIDENCE_MAGIC) :]
    if payload != shard.raw_bytes:
        raise Protocol28EvidenceError("staged raw shard bytes do not match authority")
    return payload


def stage_snapshot_evidence(
    snapshot: CapturedSnapshot,
    partition: WorkspacePartitionCatalogV1,
    selection: SelectionScopeV1,
    policy: EvidenceStagingPolicyV1,
    object_store: ObjectStore,
) -> SnapshotEvidenceCatalogV1:
    if not isinstance(snapshot, CapturedSnapshot):
        raise Protocol28EvidenceError("snapshot evidence requires CapturedSnapshot")
    if not isinstance(partition, WorkspacePartitionCatalogV1):
        raise Protocol28EvidenceError(
            "snapshot evidence requires WorkspacePartitionCatalogV1"
        )
    if not isinstance(selection, SelectionScopeV1):
        raise Protocol28EvidenceError("snapshot evidence selection is invalid")
    if not isinstance(policy, EvidenceStagingPolicyV1):
        raise Protocol28EvidenceError("snapshot evidence policy is invalid")
    if not isinstance(object_store, ObjectStore):
        raise Protocol28EvidenceError("snapshot evidence requires an ObjectStore")
    if snapshot.snapshot_id != partition.snapshot_id:
        raise Protocol28EvidenceError(
            "snapshot identity does not match partition authority"
        )
    try:
        reader = PinnedSnapshotReaderV1(snapshot, partition)
    except Protocol22EvidenceError as exc:
        raise Protocol28EvidenceError(f"invalid pinned snapshot: {exc}") from exc

    assignments = _selected_assignments(partition, selection)
    required_paths = {
        (assignment.source.source_id, path)
        for assignment in assignments
        for path in assignment.primary_paths + assignment.supporting_paths
    }
    records = {
        (source.source_id, record.source_relative_path): record
        for source in partition.sources
        for record in source.files
    }
    if not required_paths.issubset(records):
        raise Protocol28EvidenceError(
            "selected evidence assignment references an unknown source record"
        )

    shards: list[SnapshotEvidenceShardV1] = []
    empty_receipts: list[EmptyFileCoverageReceiptV1] = []
    dispositions: list[NonTextEvidenceDispositionV1] = []
    by_path: dict[tuple[str, str], tuple[str, tuple[str, ...], str]] = {}

    for source_id, path in sorted(
        required_paths, key=lambda item: (item[0].encode("utf-8"), item[1].encode("utf-8"))
    ):
        record = records[(source_id, path)]
        record_hash = content_digest(record.to_json_dict())
        proof_id = _membership_proof(
            snapshot.snapshot_id,
            partition.identity,
            source_id,
            record,
        )
        if record.object_kind == "regular":
            try:
                payload = reader.read_file(source_id, path, record)
            except Protocol22EvidenceError as exc:
                raise Protocol28EvidenceError(
                    f"pinned snapshot changed or cannot be read: {exc}"
                ) from exc
        else:
            payload = None

        if record.object_kind == "regular" and record.text_status == "eligible_utf8":
            assert payload is not None
            if not payload:
                receipt = EmptyFileCoverageReceiptV1(
                    schema_version=1,
                    source_id=source_id,
                    source_relative_path=path,
                    file_record_hash=record_hash,
                    file_content_hash=record.content_hash,
                    mode=record.mode,
                    byte_count=0,
                    membership_proof_id=proof_id,
                )
                _put_authority(object_store, receipt.identity, receipt.to_json_dict())
                empty_receipts.append(receipt)
                by_path[(source_id, path)] = (
                    "empty",
                    (receipt.receipt_id,),
                    proof_id,
                )
                continue
            file_shards: list[str] = []
            for start, end in split_utf8_ranges(payload, policy.shard_byte_limit):
                raw = payload[start:end]
                raw_object_hash = object_store.put_blob(_RAW_EVIDENCE_MAGIC + raw)
                line_start, column_start = _text_position(payload, start)
                line_end, column_end = _text_position(payload, end)
                shard = SnapshotEvidenceShardV1(
                    schema_version=1,
                    source_id=source_id,
                    source_relative_path=path,
                    file_record_hash=record_hash,
                    file_content_hash=record.content_hash,
                    mode=record.mode,
                    byte_start=start,
                    byte_end=end,
                    line_start=line_start,
                    column_start=column_start,
                    line_end=line_end,
                    column_end=column_end,
                    raw_hash=content_digest(raw),
                    raw_object_hash=raw_object_hash,
                    raw_bytes_base64=base64.b64encode(raw).decode("ascii"),
                    membership_proof_id=proof_id,
                )
                _put_authority(object_store, shard.shard_id, shard.to_json_dict())
                shards.append(shard)
                file_shards.append(shard.shard_id)
            by_path[(source_id, path)] = (
                "shard",
                tuple(file_shards),
                proof_id,
            )
            continue

        disposition_kind = (
            "proven_non_behavioral"
            if record.object_kind == "regular"
            and PurePosixPath(path).suffix.lower()
            in policy.proven_non_behavioral_suffixes
            else "unsupported_behavioral_content"
        )
        disposition = NonTextEvidenceDispositionV1(
            schema_version=1,
            source_id=source_id,
            source_relative_path=path,
            file_record_hash=record_hash,
            file_content_hash=record.content_hash,
            mode=record.mode,
            object_kind=record.object_kind,
            text_status=record.text_status,
            byte_count=record.byte_count,
            disposition=disposition_kind,
            membership_proof_id=proof_id,
        )
        if disposition.disposition == "unsupported_behavioral_content":
            raise Protocol28EvidenceError(
                "unsupported_behavioral_content: "
                f"{source_id}/{path} ({record.object_kind}, "
                f"{record.text_status}, {record.byte_count} bytes)"
            )
        _put_authority(object_store, disposition.identity, disposition.to_json_dict())
        dispositions.append(disposition)
        by_path[(source_id, path)] = (
            "nontext",
            (disposition.disposition_id,),
            proof_id,
        )

    projections = tuple(
        _build_projection(snapshot.snapshot_id, assignment, by_path)
        for assignment in assignments
    )
    catalog = SnapshotEvidenceCatalogV1(
        schema_version=1,
        source_snapshot_id=snapshot.snapshot_id,
        partition_catalog_id=partition.identity,
        selection_id=selection.identity,
        policy_id=policy.identity,
        shards=tuple(
            sorted(
                shards,
                key=lambda item: (
                    item.source_id,
                    item.source_relative_path.encode("utf-8"),
                    item.byte_start,
                ),
            )
        ),
        empty_receipts=tuple(
            sorted(
                empty_receipts,
                key=lambda item: (item.source_id, item.source_relative_path.encode("utf-8")),
            )
        ),
        nontext_dispositions=tuple(
            sorted(
                dispositions,
                key=lambda item: (item.source_id, item.source_relative_path.encode("utf-8")),
            )
        ),
        projections=tuple(
            sorted(
                projections,
                key=lambda item: (item.source_id, item.target_kind, item.target_id),
            )
        ),
    )
    validate_snapshot_evidence_closure(catalog, partition, selection)
    _put_authority(object_store, policy.identity, policy.to_json_dict())
    _put_authority(object_store, catalog.identity, catalog.to_json_dict())
    return catalog


def validate_snapshot_evidence_closure(
    catalog: SnapshotEvidenceCatalogV1,
    partition: WorkspacePartitionCatalogV1,
    selection: SelectionScopeV1,
) -> None:
    if not isinstance(catalog, SnapshotEvidenceCatalogV1):
        raise Protocol28EvidenceError("snapshot evidence catalog is invalid")
    if not isinstance(partition, WorkspacePartitionCatalogV1):
        raise Protocol28EvidenceError("partition authority is invalid")
    if not isinstance(selection, SelectionScopeV1):
        raise Protocol28EvidenceError("selection authority is invalid")
    if catalog.source_snapshot_id != partition.snapshot_id:
        raise Protocol28EvidenceError("snapshot evidence snapshot identity mismatch")
    if catalog.partition_catalog_id != partition.identity:
        raise Protocol28EvidenceError("snapshot evidence partition identity mismatch")
    if catalog.selection_id != selection.identity:
        raise Protocol28EvidenceError("snapshot evidence selection identity mismatch")

    assignments = _selected_assignments(partition, selection)
    expected_targets = {
        (item.source.source_id, item.target_kind, item.target_id): item
        for item in assignments
    }
    actual_targets = {
        (item.source_id, item.target_kind, item.target_id): item
        for item in catalog.projections
    }
    if set(actual_targets) != set(expected_targets):
        raise Protocol28EvidenceError("snapshot evidence target projection set is incomplete")

    shard_by_id = {item.shard_id: item for item in catalog.shards}
    empty_by_id = {item.receipt_id: item for item in catalog.empty_receipts}
    disposition_by_id = {
        item.disposition_id: item for item in catalog.nontext_dispositions
    }
    record_by_path = {
        (source.source_id, record.source_relative_path): record
        for source in partition.sources
        for record in source.files
    }
    required_paths = {
        (assignment.source.source_id, path)
        for assignment in assignments
        for path in assignment.primary_paths + assignment.supporting_paths
    }
    evidence_paths = {
        (item.source_id, item.source_relative_path)
        for item in (
            *catalog.shards,
            *catalog.empty_receipts,
            *catalog.nontext_dispositions,
        )
    }
    if evidence_paths != required_paths:
        raise Protocol28EvidenceError(
            "snapshot evidence object set does not match selected record set"
        )
    if any(
        item.disposition == "unsupported_behavioral_content"
        for item in catalog.nontext_dispositions
    ):
        raise Protocol28EvidenceError(
            "unsupported behavioral disposition cannot satisfy closure"
        )
    _validate_evidence_records(
        catalog,
        record_by_path,
        partition.snapshot_id,
        partition.identity,
    )
    primary_paths: list[tuple[str, str]] = []
    for key, assignment in expected_targets.items():
        projection = actual_targets[key]
        if (
            projection.target_partition_id != assignment.target_partition_id
            or projection.target_content_id != assignment.target_content_id
        ):
            raise Protocol28EvidenceError("target projection local authority mismatch")
        observed_paths: list[tuple[str, str]] = []
        per_file_shards: dict[tuple[str, str], list[SnapshotEvidenceShardV1]] = {}
        for shard_id in projection.primary_shard_ids:
            shard = shard_by_id[shard_id]
            file_key = (shard.source_id, shard.source_relative_path)
            observed_paths.append(file_key)
            per_file_shards.setdefault(file_key, []).append(shard)
        for receipt_id in projection.primary_empty_receipt_ids:
            receipt = empty_by_id[receipt_id]
            observed_paths.append((receipt.source_id, receipt.source_relative_path))
        for disposition_id in projection.primary_nontext_disposition_ids:
            disposition = disposition_by_id[disposition_id]
            if disposition.disposition != "proven_non_behavioral":
                raise Protocol28EvidenceError(
                    "unsupported behavioral disposition cannot satisfy closure"
                )
            observed_paths.append(
                (disposition.source_id, disposition.source_relative_path)
            )
        observed_unique = set(observed_paths)
        expected_paths = {
            (assignment.source.source_id, path) for path in assignment.primary_paths
        }
        if observed_unique != expected_paths:
            raise Protocol28EvidenceError(
                "target projection primary source-record coverage is incomplete"
            )
        primary_paths.extend(observed_unique)
        for file_key, file_shards in per_file_shards.items():
            record = record_by_path[file_key]
            ordered = sorted(file_shards, key=lambda item: item.byte_start)
            if [(item.byte_start, item.byte_end) for item in ordered] != _contiguous_ranges(
                ordered, record.byte_count
            ):
                raise Protocol28EvidenceError(
                    "snapshot evidence shard ranges have a gap or overlap"
                )
    if len(primary_paths) != len(set(primary_paths)):
        raise Protocol28EvidenceError(
            "snapshot evidence primary source record is assigned more than once"
        )


def _validate_evidence_records(
    catalog: SnapshotEvidenceCatalogV1,
    record_by_path: dict[tuple[str, str], FileRecordV1],
    snapshot_id: str,
    partition_id: str,
) -> None:
    shards_by_path: dict[tuple[str, str], list[SnapshotEvidenceShardV1]] = {}
    representation_count: dict[tuple[str, str], int] = {}
    for shard in catalog.shards:
        key = (shard.source_id, shard.source_relative_path)
        shards_by_path.setdefault(key, []).append(shard)
    for key in shards_by_path:
        representation_count[key] = representation_count.get(key, 0) + 1
    for item in catalog.empty_receipts:
        key = (item.source_id, item.source_relative_path)
        representation_count[key] = representation_count.get(key, 0) + 1
    for item in catalog.nontext_dispositions:
        key = (item.source_id, item.source_relative_path)
        representation_count[key] = representation_count.get(key, 0) + 1
    if any(count != 1 for count in representation_count.values()):
        raise Protocol28EvidenceError(
            "source record has multiple snapshot evidence representations"
        )

    for item in (*catalog.shards, *catalog.empty_receipts, *catalog.nontext_dispositions):
        key = (item.source_id, item.source_relative_path)
        record = record_by_path.get(key)
        if record is None:
            raise Protocol28EvidenceError("snapshot evidence names an unknown record")
        expected_proof = _membership_proof(
            snapshot_id,
            partition_id,
            item.source_id,
            record,
        )
        if (
            item.file_record_hash != content_digest(record.to_json_dict())
            or item.file_content_hash != record.content_hash
            or item.mode != record.mode
            or item.membership_proof_id != expected_proof
        ):
            raise Protocol28EvidenceError(
                "snapshot evidence record authority does not match partition"
            )
    for key, file_shards in shards_by_path.items():
        record = record_by_path[key]
        ordered = sorted(file_shards, key=lambda item: item.byte_start)
        if [(item.byte_start, item.byte_end) for item in ordered] != _contiguous_ranges(
            ordered, record.byte_count
        ):
            raise Protocol28EvidenceError(
                "snapshot evidence shard ranges have a gap or overlap"
            )
        payload = b"".join(item.raw_bytes for item in ordered)
        if content_digest(payload) != record.content_hash:
            raise Protocol28EvidenceError(
                "snapshot evidence bytes do not match file content authority"
            )
        for shard in ordered:
            if (
                (shard.line_start, shard.column_start)
                != _text_position(payload, shard.byte_start)
                or (shard.line_end, shard.column_end)
                != _text_position(payload, shard.byte_end)
            ):
                raise Protocol28EvidenceError(
                    "snapshot evidence line/column boundary is invalid"
                )
    for receipt in catalog.empty_receipts:
        record = record_by_path[(receipt.source_id, receipt.source_relative_path)]
        if record.byte_count != 0 or record.text_status != "eligible_utf8":
            raise Protocol28EvidenceError(
                "empty-file receipt does not match an empty UTF-8 record"
            )
    for disposition in catalog.nontext_dispositions:
        record = record_by_path[
            (disposition.source_id, disposition.source_relative_path)
        ]
        if (
            disposition.byte_count != record.byte_count
            or disposition.object_kind != record.object_kind
            or disposition.text_status != record.text_status
        ):
            raise Protocol28EvidenceError(
                "non-text disposition does not match source record"
            )


def _contiguous_ranges(
    shards: list[SnapshotEvidenceShardV1],
    byte_count: int,
) -> list[tuple[int, int]]:
    expected: list[tuple[int, int]] = []
    offset = 0
    for shard in shards:
        if shard.byte_start != offset:
            return []
        expected.append((shard.byte_start, shard.byte_end))
        offset = shard.byte_end
    if offset != byte_count:
        return []
    return expected


def _selected_assignments(
    partition: WorkspacePartitionCatalogV1,
    selection: SelectionScopeV1,
) -> tuple[_TargetAssignment, ...]:
    sources = {item.source_id: item for item in partition.sources}
    selected_source_ids = tuple(sources) if selection.all_sources else selection.source_ids
    if any(source_id not in sources for source_id in selected_source_ids):
        raise Protocol28EvidenceError("selection names an unknown source")
    requested_domains = set(selection.domain_keys)
    known_domains = {
        domain.domain_key
        for source_id in selected_source_ids
        for domain in sources[source_id].domains
    }
    if requested_domains - known_domains:
        raise Protocol28EvidenceError("selection names an unknown domain")

    assignments: list[_TargetAssignment] = []
    for source_id in selected_source_ids:
        source = sources[source_id]
        domains = tuple(
            domain
            for domain in source.domains
            if not requested_domains or domain.domain_key in requested_domains
        )
        ownership = _domain_ownership(source)
        for domain in domains:
            primary = tuple(
                sorted(
                    path
                    for path, owner in ownership.items()
                    if owner == domain.domain_key
                )
            )
            supporting = tuple(
                path
                for path in domain.supporting_source_relative_paths
                if path not in primary
            )
            assignments.append(
                _TargetAssignment(
                    target_kind="domain",
                    source=source,
                    target_id=domain.domain_key,
                    target_partition_id=domain.domain_partition_id,
                    target_content_id=domain.domain_content_id,
                    primary_paths=primary,
                    supporting_paths=tuple(sorted(set(supporting))),
                )
            )
        unowned = tuple(
            record.source_relative_path
            for record in source.files
            if record.source_relative_path not in ownership
        )
        assignments.append(
            _TargetAssignment(
                target_kind="source",
                source=source,
                target_id=source.source_id,
                target_partition_id=source.source_partition_id,
                target_content_id=source.source_content_id,
                primary_paths=unowned,
                supporting_paths=(),
            )
        )
    return tuple(
        sorted(
            assignments,
            key=lambda item: (item.source.source_id, item.target_kind, item.target_id),
        )
    )


def _domain_ownership(source: SourceDescriptorV1) -> dict[str, str]:
    ownership: dict[str, str] = {}
    for domain in source.domains:
        for relative in domain.owned_domain_relative_paths:
            path = (
                relative
                if domain.source_relative_root == "."
                else f"{domain.source_relative_root}/{relative}"
            )
            if path in ownership:
                raise Protocol28EvidenceError(
                    f"source record {source.source_id}/{path} has multiple domain owners"
                )
            ownership[path] = domain.domain_key
    return ownership


def _build_projection(
    snapshot_id: str,
    assignment: _TargetAssignment,
    by_path: dict[tuple[str, str], tuple[str, tuple[str, ...], str]],
) -> TargetSnapshotEvidenceProjectionV1:
    primary = _projection_ids(
        assignment.source.source_id, assignment.primary_paths, by_path
    )
    supporting = _projection_ids(
        assignment.source.source_id, assignment.supporting_paths, by_path
    )
    proof_ids: set[str] = set()
    for path in assignment.primary_paths + assignment.supporting_paths:
        _, _, proof_id = by_path[(assignment.source.source_id, path)]
        proof_ids.add(proof_id)
    return TargetSnapshotEvidenceProjectionV1(
        schema_version=1,
        target_kind=assignment.target_kind,
        source_id=assignment.source.source_id,
        target_id=assignment.target_id,
        target_partition_id=assignment.target_partition_id,
        target_content_id=assignment.target_content_id,
        source_snapshot_id=snapshot_id,
        primary_shard_ids=primary["shard"],
        primary_empty_receipt_ids=primary["empty"],
        primary_nontext_disposition_ids=primary["nontext"],
        supporting_shard_ids=supporting["shard"],
        supporting_empty_receipt_ids=supporting["empty"],
        supporting_nontext_disposition_ids=supporting["nontext"],
        membership_proof_ids=tuple(sorted(proof_ids)),
    )


def _projection_ids(
    source_id: str,
    paths: tuple[str, ...],
    by_path: dict[tuple[str, str], tuple[str, tuple[str, ...], str]],
) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {"shard": [], "empty": [], "nontext": []}
    for path in paths:
        kind, identifiers, _ = by_path[(source_id, path)]
        grouped[kind].extend(identifiers)
    return {kind: tuple(values) for kind, values in grouped.items()}


def _membership_proof(
    snapshot_id: str,
    partition_id: str,
    source_id: str,
    record: FileRecordV1,
) -> str:
    return content_digest(
        {
            "schema_version": 1,
            "source_snapshot_id": snapshot_id,
            "partition_catalog_id": partition_id,
            "source_id": source_id,
            "file_record": record.to_json_dict(),
        }
    )


def _text_position(payload: bytes, offset: int) -> tuple[int, int]:
    prefix = payload[:offset].decode("utf-8", errors="strict")
    line = prefix.count("\n") + 1
    column = len(prefix.rsplit("\n", 1)[-1]) + 1
    return line, column


def _put_authority(
    object_store: ObjectStore,
    expected_id: str,
    value: object,
) -> None:
    try:
        observed = object_store.put_blob(canonical_json_bytes(value))
    except ReV2LedgerError as exc:
        raise Protocol28EvidenceError(
            f"cannot stage snapshot evidence authority: {exc}"
        ) from exc
    if observed != expected_id:
        raise Protocol28EvidenceError(
            "staged snapshot evidence authority digest mismatch"
        )


__all__ = (
    "EmptyFileCoverageReceiptV1",
    "EvidenceStagingPolicyV1",
    "NonTextEvidenceDispositionV1",
    "Protocol28EvidenceError",
    "SnapshotEvidenceCatalogV1",
    "SnapshotEvidenceShardV1",
    "TargetSnapshotEvidenceProjectionV1",
    "read_staged_shard_bytes",
    "split_utf8_ranges",
    "stage_snapshot_evidence",
    "validate_snapshot_evidence_closure",
)
