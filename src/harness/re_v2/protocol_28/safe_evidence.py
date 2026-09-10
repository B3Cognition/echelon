"""Provider-safe projection of authenticated protocol-2.8 snapshot evidence."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import ClassVar, Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_evidence import (
    screen_source_bytes,
    security_policy_id,
    source_path_is_excluded,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    nonnegative_int,
    one_of,
    safe_id,
    safe_relative_path,
)
from harness.re_v2.protocol_28.evidence import (
    EmptyFileCoverageReceiptV1,
    NonTextEvidenceDispositionV1,
    SnapshotEvidenceCatalogV1,
    SnapshotEvidenceShardV1,
)


class Protocol28SafeEvidenceError(Protocol22SchemaError):
    """Raised when raw evidence cannot produce an exact safe projection."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol28SafeEvidenceError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol28SafeEvidenceError(str(exc)) from exc


def _identity(value: object) -> str:
    return content_digest(canonical_json_bytes(value))


@dataclass(frozen=True, slots=True)
class SafeSnapshotEvidenceObjectV1:
    schema_version: int
    raw_evidence_id: str
    security_policy_id: str
    source_id: str
    source_relative_path: str
    byte_start: int
    byte_end: int
    disposition: str
    reason_code: str | None
    text: str
    withheld_ranges: tuple[tuple[int, int, str], ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "kind",
        "raw_evidence_id",
        "security_policy_id",
        "source_id",
        "source_relative_path",
        "byte_start",
        "byte_end",
        "disposition",
        "reason_code",
        "text",
        "withheld_ranges",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(digest_value, self.raw_evidence_id, f"{label}.raw_evidence_id")
        _schema(digest_value, self.security_policy_id, f"{label}.security_policy_id")
        if self.security_policy_id != security_policy_id():
            raise Protocol28SafeEvidenceError("safe evidence security policy is unavailable")
        _schema(safe_id, self.source_id, f"{label}.source_id")
        _schema(safe_relative_path, self.source_relative_path, f"{label}.source_relative_path")
        _schema(nonnegative_int, self.byte_start, f"{label}.byte_start")
        _schema(nonnegative_int, self.byte_end, f"{label}.byte_end")
        if self.byte_end < self.byte_start:
            raise Protocol28SafeEvidenceError("safe evidence byte range is invalid")
        _schema(
            one_of,
            self.disposition,
            frozenset({"available", "redacted", "withheld", "metadata-only"}),
            f"{label}.disposition",
        )
        if self.reason_code is not None and not isinstance(self.reason_code, str):
            raise Protocol28SafeEvidenceError("safe evidence reason code is invalid")
        if not isinstance(self.text, str):
            raise Protocol28SafeEvidenceError("safe evidence text is invalid")
        try:
            encoded = self.text.encode("utf-8")
        except UnicodeError as exc:
            raise Protocol28SafeEvidenceError("safe evidence text is invalid") from exc
        ranges: list[tuple[int, int, str]] = []
        if not isinstance(self.withheld_ranges, (list, tuple)):
            raise Protocol28SafeEvidenceError("safe evidence ranges must be an array")
        for item in self.withheld_ranges:
            if (
                not isinstance(item, (list, tuple))
                or len(item) != 3
                or not isinstance(item[2], str)
            ):
                raise Protocol28SafeEvidenceError("safe evidence range is invalid")
            start = _schema(nonnegative_int, item[0], "safe evidence range start")
            end = _schema(nonnegative_int, item[1], "safe evidence range end")
            if start >= end or start < self.byte_start or end > self.byte_end:
                raise Protocol28SafeEvidenceError("safe evidence range is invalid")
            ranges.append((start, end, item[2]))
        canonical = tuple(sorted(set(ranges)))
        if tuple(ranges) != canonical:
            raise Protocol28SafeEvidenceError("safe evidence ranges must be sorted and unique")
        if self.disposition in {"available", "redacted"}:
            if self.reason_code is not None or len(encoded) != self.byte_end - self.byte_start:
                raise Protocol28SafeEvidenceError("safe evidence text does not match its range")
            if (self.disposition == "redacted") != bool(canonical):
                raise Protocol28SafeEvidenceError("safe evidence redaction disposition is invalid")
        elif self.text or self.reason_code is None:
            raise Protocol28SafeEvidenceError("withheld safe evidence must be metadata-only")
        object.__setattr__(self, "withheld_ranges", canonical)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": "untrusted_safe_snapshot_evidence",
            "raw_evidence_id": self.raw_evidence_id,
            "security_policy_id": self.security_policy_id,
            "source_id": self.source_id,
            "source_relative_path": self.source_relative_path,
            "byte_start": self.byte_start,
            "byte_end": self.byte_end,
            "disposition": self.disposition,
            "reason_code": self.reason_code,
            "text": self.text,
            "withheld_ranges": [
                {"byte_start": start, "byte_end": end, "reason_code": reason}
                for start, end, reason in self.withheld_ranges
            ],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SafeSnapshotEvidenceObjectV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        _schema(literal, raw["kind"], "untrusted_safe_snapshot_evidence", f"{cls.__name__}.kind")
        encoded_ranges = raw["withheld_ranges"]
        if not isinstance(encoded_ranges, list):
            raise Protocol28SafeEvidenceError("safe evidence ranges must be an array")
        ranges = []
        for item in encoded_ranges:
            row = _schema(
                exact_object,
                item,
                frozenset({"byte_start", "byte_end", "reason_code"}),
                "safe evidence range",
            )
            ranges.append((row["byte_start"], row["byte_end"], row["reason_code"]))
        return cls(
            **{
                field: raw[field]
                for field in cls.FIELDS
                if field not in {"kind", "withheld_ranges"}
            },
            withheld_ranges=tuple(ranges),
        )


@dataclass(frozen=True, slots=True)
class SafeSnapshotEvidenceCatalogV1:
    schema_version: int
    raw_catalog_id: str
    security_policy_id: str
    objects: tuple[SafeSnapshotEvidenceObjectV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "raw_catalog_id",
        "security_policy_id",
        "objects",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(digest_value, self.raw_catalog_id, f"{label}.raw_catalog_id")
        _schema(digest_value, self.security_policy_id, f"{label}.security_policy_id")
        if self.security_policy_id != security_policy_id():
            raise Protocol28SafeEvidenceError("safe evidence security policy is unavailable")
        if (
            not isinstance(self.objects, (list, tuple))
            or any(not isinstance(item, SafeSnapshotEvidenceObjectV1) for item in self.objects)
        ):
            raise Protocol28SafeEvidenceError("safe evidence objects are invalid")
        ordered = tuple(sorted(self.objects, key=lambda item: item.raw_evidence_id))
        raw_ids = tuple(item.raw_evidence_id for item in ordered)
        if tuple(self.objects) != ordered or len(raw_ids) != len(set(raw_ids)):
            raise Protocol28SafeEvidenceError("safe evidence mapping must be sorted and one-to-one")
        if any(item.security_policy_id != self.security_policy_id for item in ordered):
            raise Protocol28SafeEvidenceError("safe evidence object policy does not match catalog")
        object.__setattr__(self, "objects", ordered)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def raw_evidence_ids(self) -> tuple[str, ...]:
        return tuple(item.raw_evidence_id for item in self.objects)

    def object_for_raw(self, raw_evidence_id: str) -> SafeSnapshotEvidenceObjectV1:
        matches = tuple(item for item in self.objects if item.raw_evidence_id == raw_evidence_id)
        if len(matches) != 1:
            raise Protocol28SafeEvidenceError("safe evidence mapping is unavailable")
        return matches[0]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "raw_catalog_id": self.raw_catalog_id,
            "security_policy_id": self.security_policy_id,
            "objects": [item.to_json_dict() for item in self.objects],
        }

    def provider_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_json_dict())

    @classmethod
    def from_json_dict(cls, value: object) -> "SafeSnapshotEvidenceCatalogV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        if not isinstance(raw["objects"], list):
            raise Protocol28SafeEvidenceError("safe evidence objects must be an array")
        return cls(
            raw["schema_version"],
            raw["raw_catalog_id"],
            raw["security_policy_id"],
            tuple(SafeSnapshotEvidenceObjectV1.from_json_dict(item) for item in raw["objects"]),
        )


@dataclass(frozen=True, slots=True)
class SafeLowerAuthorityObjectV1:
    """One authenticated provider-safe projection of inherited authority bytes."""

    schema_version: int
    raw_authority_id: str
    security_policy_id: str
    raw_byte_count: int
    disposition: str
    reason_code: str | None
    safe_bytes_base64: str
    withheld_ranges: tuple[tuple[int, int, str], ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "raw_authority_id",
        "security_policy_id",
        "raw_byte_count",
        "disposition",
        "reason_code",
        "safe_bytes_base64",
        "withheld_ranges",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(digest_value, self.raw_authority_id, f"{label}.raw_authority_id")
        _schema(digest_value, self.security_policy_id, f"{label}.security_policy_id")
        if self.security_policy_id != security_policy_id():
            raise Protocol28SafeEvidenceError("safe lower-authority policy is unavailable")
        _schema(nonnegative_int, self.raw_byte_count, f"{label}.raw_byte_count")
        _schema(
            one_of,
            self.disposition,
            frozenset({"available", "redacted", "withheld"}),
            f"{label}.disposition",
        )
        if self.reason_code is not None and not isinstance(self.reason_code, str):
            raise Protocol28SafeEvidenceError("safe lower-authority reason is invalid")
        try:
            safe_bytes = base64.b64decode(self.safe_bytes_base64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise Protocol28SafeEvidenceError(
                "safe lower-authority bytes are invalid"
            ) from exc
        if base64.b64encode(safe_bytes).decode("ascii") != self.safe_bytes_base64:
            raise Protocol28SafeEvidenceError("safe lower-authority bytes are not canonical")
        ranges = _canonical_ranges(
            self.withheld_ranges,
            byte_start=0,
            byte_end=self.raw_byte_count,
            label="safe lower-authority",
        )
        if self.disposition in {"available", "redacted"}:
            if self.reason_code is not None or len(safe_bytes) != self.raw_byte_count:
                raise Protocol28SafeEvidenceError(
                    "safe lower-authority bytes do not match raw length"
                )
            if (self.disposition == "redacted") != bool(ranges):
                raise Protocol28SafeEvidenceError(
                    "safe lower-authority redaction disposition is invalid"
                )
        elif safe_bytes or self.reason_code is None:
            raise Protocol28SafeEvidenceError(
                "withheld lower authority must be metadata-only"
            )
        object.__setattr__(self, "withheld_ranges", ranges)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def safe_bytes(self) -> bytes:
        return base64.b64decode(self.safe_bytes_base64, validate=True)

    def to_json_dict(self) -> dict[str, object]:
        return {
            **{
                field: getattr(self, field)
                for field in self.FIELDS
                if field != "withheld_ranges"
            },
            "withheld_ranges": [
                {"byte_start": start, "byte_end": end, "reason_code": reason}
                for start, end, reason in self.withheld_ranges
            ],
        }

    def to_provider_json_dict(self) -> dict[str, object]:
        return {
            "object_id": self.raw_authority_id,
            "safe_object_id": self.identity,
            "security_policy_id": self.security_policy_id,
            "disposition": self.disposition,
            "reason_code": self.reason_code,
            "bytes_base64": self.safe_bytes_base64,
            "withheld_ranges": [
                {"byte_start": start, "byte_end": end, "reason_code": reason}
                for start, end, reason in self.withheld_ranges
            ],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SafeLowerAuthorityObjectV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            **{
                field: raw[field]
                for field in cls.FIELDS
                if field != "withheld_ranges"
            },
            withheld_ranges=_decode_ranges(raw["withheld_ranges"], "safe lower-authority"),
        )


@dataclass(frozen=True, slots=True)
class SafeLowerAuthorityCatalogV1:
    """Exact safe projection closure for every lower authority sent to a provider."""

    schema_version: int
    security_policy_id: str
    objects: tuple[SafeLowerAuthorityObjectV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "security_policy_id",
        "objects",
    )

    def __post_init__(self) -> None:
        label = type(self).__name__
        _schema(literal, self.schema_version, 1, f"{label}.schema_version")
        _schema(digest_value, self.security_policy_id, f"{label}.security_policy_id")
        if self.security_policy_id != security_policy_id():
            raise Protocol28SafeEvidenceError("safe lower-authority policy is unavailable")
        if (
            not isinstance(self.objects, (list, tuple))
            or any(not isinstance(item, SafeLowerAuthorityObjectV1) for item in self.objects)
        ):
            raise Protocol28SafeEvidenceError("safe lower-authority objects are invalid")
        ordered = tuple(sorted(self.objects, key=lambda item: item.raw_authority_id))
        raw_ids = tuple(item.raw_authority_id for item in ordered)
        if tuple(self.objects) != ordered or len(raw_ids) != len(set(raw_ids)):
            raise Protocol28SafeEvidenceError(
                "safe lower-authority mapping must be sorted and one-to-one"
            )
        if any(item.security_policy_id != self.security_policy_id for item in ordered):
            raise Protocol28SafeEvidenceError(
                "safe lower-authority object policy does not match catalog"
            )
        object.__setattr__(self, "objects", ordered)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def raw_authority_ids(self) -> tuple[str, ...]:
        return tuple(item.raw_authority_id for item in self.objects)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "security_policy_id": self.security_policy_id,
            "objects": [item.to_json_dict() for item in self.objects],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SafeLowerAuthorityCatalogV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        if not isinstance(raw["objects"], list):
            raise Protocol28SafeEvidenceError(
                "safe lower-authority objects must be an array"
            )
        return cls(
            raw["schema_version"],
            raw["security_policy_id"],
            tuple(SafeLowerAuthorityObjectV1.from_json_dict(item) for item in raw["objects"]),
        )


def _decode_ranges(value: object, label: str) -> tuple[tuple[int, int, str], ...]:
    if not isinstance(value, list):
        raise Protocol28SafeEvidenceError(f"{label} ranges must be an array")
    ranges = []
    for item in value:
        row = _schema(
            exact_object,
            item,
            frozenset({"byte_start", "byte_end", "reason_code"}),
            f"{label} range",
        )
        ranges.append((row["byte_start"], row["byte_end"], row["reason_code"]))
    return tuple(ranges)


def _canonical_ranges(
    value: object,
    *,
    byte_start: int,
    byte_end: int,
    label: str,
) -> tuple[tuple[int, int, str], ...]:
    if not isinstance(value, (list, tuple)):
        raise Protocol28SafeEvidenceError(f"{label} ranges must be an array")
    ranges: list[tuple[int, int, str]] = []
    for item in value:
        if (
            not isinstance(item, (list, tuple))
            or len(item) != 3
            or not isinstance(item[2], str)
        ):
            raise Protocol28SafeEvidenceError(f"{label} range is invalid")
        start = _schema(nonnegative_int, item[0], f"{label} range start")
        end = _schema(nonnegative_int, item[1], f"{label} range end")
        if start >= end or start < byte_start or end > byte_end:
            raise Protocol28SafeEvidenceError(f"{label} range is invalid")
        ranges.append((start, end, item[2]))
    canonical = tuple(sorted(set(ranges)))
    if tuple(ranges) != canonical:
        raise Protocol28SafeEvidenceError(f"{label} ranges must be sorted and unique")
    return canonical


def _safe_shard_rows(
    shards: tuple[SnapshotEvidenceShardV1, ...],
) -> tuple[SafeSnapshotEvidenceObjectV1, ...]:
    grouped: dict[tuple[str, str], list[SnapshotEvidenceShardV1]] = {}
    for shard in shards:
        grouped.setdefault((shard.source_id, shard.source_relative_path), []).append(shard)
    rows: list[SafeSnapshotEvidenceObjectV1] = []
    policy_id = security_policy_id()
    for (_source_id, path), file_shards in sorted(grouped.items()):
        ordered = tuple(sorted(file_shards, key=lambda item: item.byte_start))
        if not ordered or ordered[0].byte_start != 0 or any(
            left.byte_end != right.byte_start for left, right in zip(ordered, ordered[1:])
        ):
            raise Protocol28SafeEvidenceError("raw evidence shard closure is invalid")
        raw_file = b"".join(item.raw_bytes for item in ordered)
        excluded = source_path_is_excluded(path)
        screened = None if excluded else screen_source_bytes(raw_file)
        for shard in ordered:
            reason = "excluded-path" if excluded else screened.reason_code  # type: ignore[union-attr]
            if reason is not None:
                ranges = (
                    ((shard.byte_start, shard.byte_end, reason),)
                    if shard.byte_end > shard.byte_start
                    else ()
                )
                text = ""
                disposition = "withheld"
            else:
                assert screened is not None and screened.safe_bytes is not None
                text = screened.safe_bytes[shard.byte_start : shard.byte_end].decode("utf-8")
                ranges = tuple(
                    sorted(
                        {
                            (
                                max(start, shard.byte_start),
                                min(end, shard.byte_end),
                                code,
                            )
                            for start, end, code in screened.withheld_ranges
                            if start < shard.byte_end and end > shard.byte_start
                        }
                    )
                )
                disposition = "redacted" if ranges else "available"
            rows.append(
                SafeSnapshotEvidenceObjectV1(
                    1,
                    shard.identity,
                    policy_id,
                    shard.source_id,
                    shard.source_relative_path,
                    shard.byte_start,
                    shard.byte_end,
                    disposition,
                    reason,
                    text,
                    ranges,
                )
            )
    return tuple(rows)


def _metadata_row(
    item: EmptyFileCoverageReceiptV1 | NonTextEvidenceDispositionV1,
) -> SafeSnapshotEvidenceObjectV1:
    is_empty = isinstance(item, EmptyFileCoverageReceiptV1)
    byte_end = 0 if is_empty else item.byte_count
    return SafeSnapshotEvidenceObjectV1(
        1,
        item.identity,
        security_policy_id(),
        item.source_id,
        item.source_relative_path,
        0,
        byte_end,
        "metadata-only",
        "empty-file" if is_empty else "proven-non-behavioral",
        "",
        (),
    )


def build_safe_snapshot_evidence_catalog(
    raw_catalog: SnapshotEvidenceCatalogV1,
) -> SafeSnapshotEvidenceCatalogV1:
    """Create the exact one-to-one provider-safe view of a raw evidence catalog."""
    if not isinstance(raw_catalog, SnapshotEvidenceCatalogV1):
        raise Protocol28SafeEvidenceError("raw snapshot evidence catalog is invalid")
    expected_ids = {
        item.identity
        for item in (
            *raw_catalog.shards,
            *raw_catalog.empty_receipts,
            *raw_catalog.nontext_dispositions,
        )
    }
    rows = (
        *_safe_shard_rows(raw_catalog.shards),
        *(_metadata_row(item) for item in raw_catalog.empty_receipts),
        *(_metadata_row(item) for item in raw_catalog.nontext_dispositions),
    )
    catalog = SafeSnapshotEvidenceCatalogV1(
        1,
        raw_catalog.identity,
        security_policy_id(),
        tuple(sorted(rows, key=lambda item: item.raw_evidence_id)),
    )
    if set(catalog.raw_evidence_ids) != expected_ids or len(catalog.objects) != len(expected_ids):
        raise Protocol28SafeEvidenceError("safe evidence mapping does not close raw evidence")
    return catalog


def validate_safe_snapshot_evidence_catalog(
    safe_catalog: SafeSnapshotEvidenceCatalogV1,
    raw_catalog: SnapshotEvidenceCatalogV1,
) -> None:
    """Authenticate the safe catalogue against every member of its bound raw catalogue."""
    if not isinstance(safe_catalog, SafeSnapshotEvidenceCatalogV1) or not isinstance(
        raw_catalog, SnapshotEvidenceCatalogV1
    ):
        raise Protocol28SafeEvidenceError("safe evidence catalog binding is invalid")
    expected = build_safe_snapshot_evidence_catalog(raw_catalog)
    if safe_catalog != expected:
        raise Protocol28SafeEvidenceError("safe evidence catalog does not close raw evidence")


def build_safe_lower_authority_catalog(
    authority_objects: Mapping[str, bytes],
    required_authority_ids: tuple[str, ...],
) -> SafeLowerAuthorityCatalogV1:
    """Project the exact lower-authority set through the versioned source scanner."""
    if not isinstance(authority_objects, Mapping):
        raise Protocol28SafeEvidenceError("lower-authority objects must be a mapping")
    required = tuple(sorted(set(required_authority_ids)))
    if tuple(required_authority_ids) != required:
        raise Protocol28SafeEvidenceError(
            "lower-authority identifiers must be sorted and unique"
        )
    rows: list[SafeLowerAuthorityObjectV1] = []
    policy_id = security_policy_id()
    for object_id in required:
        _schema(digest_value, object_id, "lower-authority object id")
        payload = authority_objects.get(object_id)
        if not isinstance(payload, bytes) or content_digest(payload) != object_id:
            raise Protocol28SafeEvidenceError("lower-authority object is unavailable")
        screened = screen_source_bytes(payload)
        safe_bytes = screened.safe_bytes or b""
        rows.append(
            SafeLowerAuthorityObjectV1(
                1,
                object_id,
                policy_id,
                len(payload),
                screened.disposition,
                screened.reason_code,
                base64.b64encode(safe_bytes).decode("ascii"),
                screened.withheld_ranges,
            )
        )
    return SafeLowerAuthorityCatalogV1(1, policy_id, tuple(rows))


def validate_safe_lower_authority_catalog(
    safe_catalog: SafeLowerAuthorityCatalogV1,
    authority_objects: Mapping[str, bytes],
    required_authority_ids: tuple[str, ...],
) -> None:
    """Rebuild and authenticate an exact safe lower-authority projection closure."""
    if not isinstance(safe_catalog, SafeLowerAuthorityCatalogV1):
        raise Protocol28SafeEvidenceError("safe lower-authority catalog is invalid")
    expected = build_safe_lower_authority_catalog(
        authority_objects,
        required_authority_ids,
    )
    if safe_catalog != expected:
        raise Protocol28SafeEvidenceError(
            "safe lower-authority catalog does not close required authority"
        )


__all__ = (
    "Protocol28SafeEvidenceError",
    "SafeLowerAuthorityCatalogV1",
    "SafeLowerAuthorityObjectV1",
    "SafeSnapshotEvidenceCatalogV1",
    "SafeSnapshotEvidenceObjectV1",
    "build_safe_snapshot_evidence_catalog",
    "build_safe_lower_authority_catalog",
    "validate_safe_lower_authority_catalog",
    "validate_safe_snapshot_evidence_catalog",
)
