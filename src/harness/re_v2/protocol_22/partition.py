"""Snapshot-bound workspace partition authority for protocol 2.2."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import stat
from types import SimpleNamespace
from typing import ClassVar, Iterable, Literal, Mapping

from echelon.workspace_model import WorkspaceManifest
from harness.re_domain_manifest import discover_source_domains
from harness.re_v2.canonical import content_digest
from harness.re_v2.snapshot import (
    CapturedSnapshot,
    ReV2SnapshotError,
    SnapshotComponent,
    SnapshotEntry,
    load_snapshot_manifest,
    validate_source_snapshot,
)

from .schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    nonnegative_int,
    safe_id,
    text_value,
)


FileModeV1 = Literal["100644", "100755", "120000", "160000"]
ObjectKindV1 = Literal["regular", "symlink", "gitlink"]
TextStatusV1 = Literal[
    "eligible_utf8", "contains_nul", "invalid_utf8", "non_regular"
]

_FILE_MODES = frozenset({"100644", "100755", "120000", "160000"})
_OBJECT_KINDS = frozenset({"regular", "symlink", "gitlink"})
_TEXT_STATUSES = frozenset(
    {"eligible_utf8", "contains_nul", "invalid_utf8", "non_regular"}
)
_MODE_KIND = {
    "100644": "regular",
    "100755": "regular",
    "120000": "symlink",
    "160000": "gitlink",
}
_ROOT_SUPPORT_NAMES = frozenset(
    {
        "BUILD",
        "BUILD.bazel",
        "CMakeLists.txt",
        "Cargo.lock",
        "Cargo.toml",
        "Dockerfile",
        "Gemfile",
        "Gemfile.lock",
        "LICENSE",
        "LICENSE.md",
        "LICENSE.txt",
        "Makefile",
        "Package.swift",
        "README",
        "README.md",
        "README.rst",
        "README.txt",
        "WORKSPACE",
        "WORKSPACE.bazel",
        "build.gradle",
        "build.gradle.kts",
        "composer.json",
        "composer.lock",
        "go.mod",
        "go.sum",
        "gradle.properties",
        "mix.exs",
        "mix.lock",
        "nx.json",
        "package-lock.json",
        "package.json",
        "pnpm-lock.yaml",
        "pom.xml",
        "pyproject.toml",
        "requirements.txt",
        "setup.cfg",
        "setup.py",
        "tsconfig.json",
        "uv.lock",
        "yarn.lock",
    }
)
_GLOBAL_SUPPORT_DIRS = frozenset(
    {
        "config",
        "configs",
        "common",
        "deploy",
        "deployment",
        "docs",
        "infra",
        "migrations",
        "schema",
        "schemas",
        "shared",
    }
)
_CONFIG_SUFFIXES = frozenset(
    {".conf", ".ini", ".json", ".properties", ".toml", ".yaml", ".yml"}
)


class Protocol22PartitionError(Protocol22SchemaError):
    """Raised when a protocol-2.2 partition contract is invalid."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol22PartitionError:
        raise
    except Protocol22SchemaError as exc:
        raise Protocol22PartitionError(str(exc)) from exc


def _exact(value: object, fields: tuple[str, ...], label: str) -> Mapping[str, object]:
    return _schema(exact_object, value, frozenset(fields), label)


def _safe_id(value: object, field: str) -> str:
    return _schema(safe_id, value, field)


def _digest(value: object, field: str) -> str:
    return _schema(digest_value, value, field)


def _text(value: object, field: str) -> str:
    return _schema(text_value, value, field)


def _count(value: object, field: str) -> int:
    return _schema(nonnegative_int, value, field)


def _closed_literal(value: object, choices: frozenset[str], field: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise Protocol22PartitionError(f"{field} must be one of {sorted(choices)}")
    return value


def _normalized_path(value: object, field: str, *, allow_dot: bool = False) -> str:
    text = _text(value, field)
    try:
        text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise Protocol22PartitionError(f"{field} contains invalid Unicode") from exc
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or path.as_posix() != text
        or any(part in {"", ".", ".."} for part in path.parts)
        or (text == "." and not allow_dot)
        or (not allow_dot and not path.parts)
    ):
        if allow_dot and text == ".":
            return text
        raise Protocol22PartitionError(f"{field} must be a normalized relative path")
    return text


def _root_path(value: object, field: str) -> str:
    if value == ".":
        return "."
    return _normalized_path(value, field)


def _sorted_unique_paths(
    values: object,
    field: str,
    *,
    allow_dot: bool = False,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise Protocol22PartitionError(f"{field} must be an array")
    normalized = tuple(
        _root_path(value, field) if allow_dot else _normalized_path(value, field)
        for value in values
    )
    expected = tuple(sorted(set(normalized), key=lambda item: item.encode("utf-8")))
    if normalized != expected:
        raise Protocol22PartitionError(f"{field} must be sorted and unique")
    return normalized


def _tuple_of(
    values: object,
    expected_type: type,
    field: str,
) -> tuple[object, ...]:
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(value, expected_type) for value in values
    ):
        raise Protocol22PartitionError(
            f"{field} must contain {expected_type.__name__} values"
        )
    return tuple(values)


@dataclass(frozen=True, slots=True)
class ImplementationAuthorityV1:
    id: str
    version: str
    implementation_digest: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "id",
        "version",
        "implementation_digest",
    )

    def __post_init__(self) -> None:
        _safe_id(self.id, "ImplementationAuthorityV1.id")
        _safe_id(self.version, "ImplementationAuthorityV1.version")
        _digest(
            self.implementation_digest,
            "ImplementationAuthorityV1.implementation_digest",
        )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "ImplementationAuthorityV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class PartitionAuthoritiesV1:
    partitioner: ImplementationAuthorityV1
    ownership_policy: ImplementationAuthorityV1

    def __post_init__(self) -> None:
        if not isinstance(self.partitioner, ImplementationAuthorityV1):
            raise Protocol22PartitionError("partitioner must be an implementation authority")
        if not isinstance(self.ownership_policy, ImplementationAuthorityV1):
            raise Protocol22PartitionError(
                "ownership_policy must be an implementation authority"
            )


@dataclass(frozen=True, slots=True)
class FileRecordV1:
    source_relative_path: str
    mode: FileModeV1
    object_kind: ObjectKindV1
    content_hash: str
    byte_count: int
    line_count: int
    text_status: TextStatusV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "source_relative_path",
        "mode",
        "object_kind",
        "content_hash",
        "byte_count",
        "line_count",
        "text_status",
    )

    def __post_init__(self) -> None:
        _normalized_path(self.source_relative_path, "FileRecordV1.source_relative_path")
        mode = _closed_literal(self.mode, _FILE_MODES, "FileRecordV1.mode")
        kind = _closed_literal(
            self.object_kind, _OBJECT_KINDS, "FileRecordV1.object_kind"
        )
        status = _closed_literal(
            self.text_status, _TEXT_STATUSES, "FileRecordV1.text_status"
        )
        _digest(self.content_hash, "FileRecordV1.content_hash")
        byte_count = _count(self.byte_count, "FileRecordV1.byte_count")
        line_count = _count(self.line_count, "FileRecordV1.line_count")
        if _MODE_KIND[mode] != kind:
            raise Protocol22PartitionError("FileRecordV1 mode and object_kind disagree")
        if kind == "regular":
            if status == "non_regular":
                raise Protocol22PartitionError(
                    "regular FileRecordV1 requires a regular text_status"
                )
        else:
            if status != "non_regular":
                raise Protocol22PartitionError(
                    "non-regular FileRecordV1 requires non_regular text_status"
                )
            if line_count != 0:
                raise Protocol22PartitionError(
                    "non-regular FileRecordV1 requires zero line count"
                )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "FileRecordV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class DomainPartitionDescriptorV1:
    domain_key: str
    presentation_domain_id: str
    source_relative_root: str
    domain_partition_id: str
    owned_domain_relative_paths: tuple[str, ...]
    supporting_source_relative_paths: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "domain_key",
        "presentation_domain_id",
        "source_relative_root",
        "domain_partition_id",
        "owned_domain_relative_paths",
        "supporting_source_relative_paths",
    )

    def __post_init__(self) -> None:
        _digest(self.domain_key, "DomainPartitionDescriptorV1.domain_key")
        _safe_id(
            self.presentation_domain_id,
            "DomainPartitionDescriptorV1.presentation_domain_id",
        )
        _root_path(
            self.source_relative_root,
            "DomainPartitionDescriptorV1.source_relative_root",
        )
        _digest(
            self.domain_partition_id,
            "DomainPartitionDescriptorV1.domain_partition_id",
        )
        object.__setattr__(
            self,
            "owned_domain_relative_paths",
            _sorted_unique_paths(
                self.owned_domain_relative_paths,
                "DomainPartitionDescriptorV1.owned_domain_relative_paths",
            ),
        )
        object.__setattr__(
            self,
            "supporting_source_relative_paths",
            _sorted_unique_paths(
                self.supporting_source_relative_paths,
                "DomainPartitionDescriptorV1.supporting_source_relative_paths",
            ),
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "domain_key": self.domain_key,
            "presentation_domain_id": self.presentation_domain_id,
            "source_relative_root": self.source_relative_root,
            "domain_partition_id": self.domain_partition_id,
            "owned_domain_relative_paths": list(self.owned_domain_relative_paths),
            "supporting_source_relative_paths": list(
                self.supporting_source_relative_paths
            ),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "DomainPartitionDescriptorV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class DomainDescriptorV1:
    domain_key: str
    presentation_domain_id: str
    source_relative_root: str
    owned_file_count: int
    owned_line_count: int
    supporting_file_count: int
    domain_content_id: str
    domain_partition_id: str
    owned_domain_relative_paths: tuple[str, ...]
    supporting_source_relative_paths: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "domain_key",
        "presentation_domain_id",
        "source_relative_root",
        "owned_file_count",
        "owned_line_count",
        "supporting_file_count",
        "domain_content_id",
        "domain_partition_id",
        "owned_domain_relative_paths",
        "supporting_source_relative_paths",
    )

    def __post_init__(self) -> None:
        projection = DomainPartitionDescriptorV1(
            domain_key=self.domain_key,
            presentation_domain_id=self.presentation_domain_id,
            source_relative_root=self.source_relative_root,
            domain_partition_id=self.domain_partition_id,
            owned_domain_relative_paths=self.owned_domain_relative_paths,
            supporting_source_relative_paths=self.supporting_source_relative_paths,
        )
        object.__setattr__(
            self, "owned_domain_relative_paths", projection.owned_domain_relative_paths
        )
        object.__setattr__(
            self,
            "supporting_source_relative_paths",
            projection.supporting_source_relative_paths,
        )
        owned_count = _count(
            self.owned_file_count, "DomainDescriptorV1.owned_file_count"
        )
        supporting_count = _count(
            self.supporting_file_count, "DomainDescriptorV1.supporting_file_count"
        )
        _count(self.owned_line_count, "DomainDescriptorV1.owned_line_count")
        _digest(self.domain_content_id, "DomainDescriptorV1.domain_content_id")
        if owned_count != len(self.owned_domain_relative_paths):
            raise Protocol22PartitionError(
                "DomainDescriptorV1 owned_file_count does not match owned paths"
            )
        if supporting_count != len(self.supporting_source_relative_paths):
            raise Protocol22PartitionError(
                "DomainDescriptorV1 supporting_file_count does not match supporting paths"
            )

    def partition_projection(self) -> DomainPartitionDescriptorV1:
        return DomainPartitionDescriptorV1(
            domain_key=self.domain_key,
            presentation_domain_id=self.presentation_domain_id,
            source_relative_root=self.source_relative_root,
            domain_partition_id=self.domain_partition_id,
            owned_domain_relative_paths=self.owned_domain_relative_paths,
            supporting_source_relative_paths=self.supporting_source_relative_paths,
        )

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.FIELDS}
        result["owned_domain_relative_paths"] = list(
            self.owned_domain_relative_paths
        )
        result["supporting_source_relative_paths"] = list(
            self.supporting_source_relative_paths
        )
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "DomainDescriptorV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SourcePartitionIdentityInputV1:
    source_id: str
    partitioner: ImplementationAuthorityV1
    ownership_policy: ImplementationAuthorityV1
    source_supporting_paths: tuple[str, ...]
    domains: tuple[DomainPartitionDescriptorV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "source_id",
        "partitioner",
        "ownership_policy",
        "source_supporting_paths",
        "domains",
    )

    def __post_init__(self) -> None:
        _safe_id(self.source_id, "SourcePartitionIdentityInputV1.source_id")
        if not isinstance(self.partitioner, ImplementationAuthorityV1):
            raise Protocol22PartitionError(
                "SourcePartitionIdentityInputV1.partitioner must be an authority"
            )
        if not isinstance(self.ownership_policy, ImplementationAuthorityV1):
            raise Protocol22PartitionError(
                "SourcePartitionIdentityInputV1.ownership_policy must be an authority"
            )
        object.__setattr__(
            self,
            "source_supporting_paths",
            _sorted_unique_paths(
                self.source_supporting_paths,
                "SourcePartitionIdentityInputV1.source_supporting_paths",
            ),
        )
        domains = _tuple_of(
            self.domains,
            DomainPartitionDescriptorV1,
            "SourcePartitionIdentityInputV1.domains",
        )
        domain_keys = tuple(domain.domain_key for domain in domains)
        if domain_keys != tuple(sorted(set(domain_keys))):
            raise Protocol22PartitionError(
                "SourcePartitionIdentityInputV1.domains must be sorted and unique by domain_key"
            )
        object.__setattr__(self, "domains", domains)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "partitioner": self.partitioner.to_json_dict(),
            "ownership_policy": self.ownership_policy.to_json_dict(),
            "source_supporting_paths": list(self.source_supporting_paths),
            "domains": [domain.to_json_dict() for domain in self.domains],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SourcePartitionIdentityInputV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        domains = raw["domains"]
        if not isinstance(domains, (list, tuple)):
            raise Protocol22PartitionError(
                "SourcePartitionIdentityInputV1.domains must be an array"
            )
        return cls(
            source_id=raw["source_id"],
            partitioner=ImplementationAuthorityV1.from_json_dict(raw["partitioner"]),
            ownership_policy=ImplementationAuthorityV1.from_json_dict(
                raw["ownership_policy"]
            ),
            source_supporting_paths=raw["source_supporting_paths"],
            domains=tuple(
                DomainPartitionDescriptorV1.from_json_dict(item) for item in domains
            ),
        )


@dataclass(frozen=True, slots=True)
class SourceDescriptorV1:
    source_id: str
    workspace_relative_path: str
    snapshot_id: str
    source_content_id: str
    source_partition_id: str
    files: tuple[FileRecordV1, ...]
    source_supporting_paths: tuple[str, ...]
    domains: tuple[DomainDescriptorV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "source_id",
        "workspace_relative_path",
        "snapshot_id",
        "source_content_id",
        "source_partition_id",
        "files",
        "source_supporting_paths",
        "domains",
    )

    def __post_init__(self) -> None:
        _safe_id(self.source_id, "SourceDescriptorV1.source_id")
        _root_path(
            self.workspace_relative_path, "SourceDescriptorV1.workspace_relative_path"
        )
        _digest(self.snapshot_id, "SourceDescriptorV1.snapshot_id")
        _digest(self.source_content_id, "SourceDescriptorV1.source_content_id")
        _digest(self.source_partition_id, "SourceDescriptorV1.source_partition_id")
        files = _tuple_of(self.files, FileRecordV1, "SourceDescriptorV1.files")
        file_paths = tuple(record.source_relative_path for record in files)
        if file_paths != tuple(
            sorted(set(file_paths), key=lambda item: item.encode("utf-8"))
        ):
            raise Protocol22PartitionError(
                "SourceDescriptorV1.files must be sorted and unique by path"
            )
        object.__setattr__(self, "files", files)
        object.__setattr__(
            self,
            "source_supporting_paths",
            _sorted_unique_paths(
                self.source_supporting_paths,
                "SourceDescriptorV1.source_supporting_paths",
            ),
        )
        domains = _tuple_of(
            self.domains, DomainDescriptorV1, "SourceDescriptorV1.domains"
        )
        keys = tuple(domain.domain_key for domain in domains)
        if keys != tuple(sorted(set(keys))):
            raise Protocol22PartitionError(
                "SourceDescriptorV1.domains must be sorted and unique by domain_key"
            )
        object.__setattr__(self, "domains", domains)

    def partition_identity_input(
        self,
        authorities: PartitionAuthoritiesV1,
    ) -> SourcePartitionIdentityInputV1:
        return SourcePartitionIdentityInputV1(
            source_id=self.source_id,
            partitioner=authorities.partitioner,
            ownership_policy=authorities.ownership_policy,
            source_supporting_paths=self.source_supporting_paths,
            domains=tuple(domain.partition_projection() for domain in self.domains),
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "workspace_relative_path": self.workspace_relative_path,
            "snapshot_id": self.snapshot_id,
            "source_content_id": self.source_content_id,
            "source_partition_id": self.source_partition_id,
            "files": [record.to_json_dict() for record in self.files],
            "source_supporting_paths": list(self.source_supporting_paths),
            "domains": [domain.to_json_dict() for domain in self.domains],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SourceDescriptorV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        files = raw["files"]
        domains = raw["domains"]
        if not isinstance(files, (list, tuple)) or not isinstance(
            domains, (list, tuple)
        ):
            raise Protocol22PartitionError(
                "SourceDescriptorV1 files and domains must be arrays"
            )
        return cls(
            source_id=raw["source_id"],
            workspace_relative_path=raw["workspace_relative_path"],
            snapshot_id=raw["snapshot_id"],
            source_content_id=raw["source_content_id"],
            source_partition_id=raw["source_partition_id"],
            files=tuple(FileRecordV1.from_json_dict(item) for item in files),
            source_supporting_paths=raw["source_supporting_paths"],
            domains=tuple(DomainDescriptorV1.from_json_dict(item) for item in domains),
        )


@dataclass(frozen=True, slots=True)
class WorkspacePartitionCatalogV1:
    schema_version: int
    snapshot_id: str
    source_selection_policy_version: str
    partitioner: ImplementationAuthorityV1
    ownership_policy: ImplementationAuthorityV1
    sources: tuple[SourceDescriptorV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "snapshot_id",
        "source_selection_policy_version",
        "partitioner",
        "ownership_policy",
        "sources",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol22PartitionError(
                "WorkspacePartitionCatalogV1.schema_version must be 1"
            )
        _digest(self.snapshot_id, "WorkspacePartitionCatalogV1.snapshot_id")
        _safe_id(
            self.source_selection_policy_version,
            "WorkspacePartitionCatalogV1.source_selection_policy_version",
        )
        authorities = PartitionAuthoritiesV1(self.partitioner, self.ownership_policy)
        sources = _tuple_of(
            self.sources, SourceDescriptorV1, "WorkspacePartitionCatalogV1.sources"
        )
        source_ids = tuple(source.source_id for source in sources)
        if source_ids != tuple(sorted(set(source_ids))):
            raise Protocol22PartitionError(
                "WorkspacePartitionCatalogV1.sources must be sorted and unique by source_id"
            )
        workspace_paths = [source.workspace_relative_path for source in sources]
        if len(workspace_paths) != len(set(workspace_paths)):
            raise Protocol22PartitionError(
                "WorkspacePartitionCatalogV1 source workspace paths must be unique"
            )
        object.__setattr__(self, "sources", sources)
        for source in self.sources:
            if source.snapshot_id != self.snapshot_id:
                raise Protocol22PartitionError(
                    "source descriptor snapshot_id does not match catalog"
                )
            _validate_source_descriptor(
                source,
                self.source_selection_policy_version,
                authorities,
            )

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "source_selection_policy_version": self.source_selection_policy_version,
            "partitioner": self.partitioner.to_json_dict(),
            "ownership_policy": self.ownership_policy.to_json_dict(),
            "sources": [source.to_json_dict() for source in self.sources],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "WorkspacePartitionCatalogV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        sources = raw["sources"]
        if not isinstance(sources, (list, tuple)):
            raise Protocol22PartitionError(
                "WorkspacePartitionCatalogV1.sources must be an array"
            )
        return cls(
            schema_version=raw["schema_version"],
            snapshot_id=raw["snapshot_id"],
            source_selection_policy_version=raw["source_selection_policy_version"],
            partitioner=ImplementationAuthorityV1.from_json_dict(raw["partitioner"]),
            ownership_policy=ImplementationAuthorityV1.from_json_dict(
                raw["ownership_policy"]
            ),
            sources=tuple(SourceDescriptorV1.from_json_dict(item) for item in sources),
        )


def domain_key(source_id: str, root: str, ownership_version: str) -> str:
    """Return the presentation-independent stable key for one domain root."""
    canonical_source = _safe_id(source_id, "domain_key.source_id")
    canonical_root = _root_path(root, "domain_key.source_relative_root")
    canonical_version = _safe_id(
        ownership_version, "domain_key.ownership_policy_version"
    )
    return content_digest(
        {
            "ownership_policy_version": canonical_version,
            "source_id": canonical_source,
            "source_relative_root": canonical_root,
        }
    )


def source_content_id(
    source_selection_policy_version: str,
    files: Iterable[FileRecordV1],
) -> str:
    """Hash only source-local content and the exact source selection policy."""
    policy = _safe_id(
        source_selection_policy_version,
        "source_content_id.source_selection_policy_version",
    )
    records = _canonical_file_records(files, "source_content_id.files")
    return content_digest(
        {
            "source_selection_policy_version": policy,
            "files": [
                {
                    "source_relative_path": record.source_relative_path,
                    "mode": record.mode,
                    "content_hash": record.content_hash,
                }
                for record in records
            ],
        }
    )


def domain_content_id(
    ownership_policy_version: str,
    stable_domain_key: str,
    source_relative_root: str,
    owned_files: Iterable[FileRecordV1],
    supporting_files: Iterable[FileRecordV1],
) -> str:
    """Hash a domain's exact owned and explicitly shared content read set."""
    version = _safe_id(
        ownership_policy_version,
        "domain_content_id.ownership_policy_version",
    )
    key = _digest(stable_domain_key, "domain_content_id.domain_key")
    root = _root_path(source_relative_root, "domain_content_id.source_relative_root")
    owned = _canonical_file_records(owned_files, "domain_content_id.owned_files")
    supporting = _canonical_file_records(
        supporting_files, "domain_content_id.supporting_files"
    )
    return content_digest(
        {
            "ownership_policy_version": version,
            "domain_key": key,
            "owned_files": [
                {
                    "domain_relative_path": _domain_relative_path(
                        record.source_relative_path, root
                    ),
                    "mode": record.mode,
                    "content_hash": record.content_hash,
                }
                for record in owned
            ],
            "supporting_files": [
                {
                    "source_relative_path": record.source_relative_path,
                    "mode": record.mode,
                    "content_hash": record.content_hash,
                }
                for record in supporting
            ],
        }
    )


def domain_partition_id(
    partitioner: ImplementationAuthorityV1,
    ownership_policy: ImplementationAuthorityV1,
    stable_domain_key: str,
    source_relative_root: str,
    owned_domain_relative_paths: Iterable[str],
    supporting_source_relative_paths: Iterable[str],
) -> str:
    """Hash the content-free partition boundary for one stable domain."""
    if not isinstance(partitioner, ImplementationAuthorityV1) or not isinstance(
        ownership_policy, ImplementationAuthorityV1
    ):
        raise Protocol22PartitionError(
            "domain_partition_id requires partitioner and ownership authorities"
        )
    key = _digest(stable_domain_key, "domain_partition_id.domain_key")
    root = _root_path(source_relative_root, "domain_partition_id.source_relative_root")
    owned = _canonicalize_paths(
        owned_domain_relative_paths,
        "domain_partition_id.owned_domain_relative_paths",
    )
    supporting = _canonicalize_paths(
        supporting_source_relative_paths,
        "domain_partition_id.supporting_source_relative_paths",
    )
    return content_digest(
        {
            "partitioner": partitioner.to_json_dict(),
            "ownership_policy": ownership_policy.to_json_dict(),
            "domain_key": key,
            "source_relative_root": root,
            "owned_domain_relative_paths": list(owned),
            "supporting_source_relative_paths": list(supporting),
        }
    )


def source_partition_id(value: SourcePartitionIdentityInputV1) -> str:
    """Hash the exact closed source-partition identity input."""
    if not isinstance(value, SourcePartitionIdentityInputV1):
        raise Protocol22PartitionError(
            "source_partition_id requires SourcePartitionIdentityInputV1"
        )
    return content_digest(value.to_json_dict())


def build_workspace_partition_catalog(
    snapshot: CapturedSnapshot,
    workspace_manifest: WorkspaceManifest,
    authorities: PartitionAuthoritiesV1,
) -> WorkspacePartitionCatalogV1:
    """Build the complete partition catalog from authenticated snapshot bytes."""
    if not isinstance(snapshot, CapturedSnapshot):
        raise Protocol22PartitionError("snapshot must be a CapturedSnapshot")
    if not isinstance(workspace_manifest, WorkspaceManifest):
        raise Protocol22PartitionError("workspace_manifest must be a WorkspaceManifest")
    if workspace_manifest.schema_version != 1:
        raise Protocol22PartitionError("workspace manifest schema_version must be 1")
    if not isinstance(authorities, PartitionAuthoritiesV1):
        raise Protocol22PartitionError("authorities must be PartitionAuthoritiesV1")
    try:
        validate_source_snapshot(snapshot)
        manifest = load_snapshot_manifest(snapshot)
    except ReV2SnapshotError as exc:
        raise Protocol22PartitionError(f"invalid composite source snapshot: {exc}") from exc
    if (
        manifest.kind != "workspace-git-composite"
        or manifest.capture_version != 2
        or manifest.components is None
        or manifest.selection_policy is None
    ):
        raise Protocol22PartitionError(
            "workspace partition requires a validated composite snapshot"
        )

    declared = _declared_sources(workspace_manifest)
    components = {component.source_id: component for component in manifest.components}
    component_declarations = {
        component.source_id: (component.workspace_path, component.git_role)
        for component in manifest.components
    }
    if {
        source_id: (path, git_role)
        for source_id, (path, git_role) in declared.items()
    } != component_declarations:
        raise Protocol22PartitionError(
            "workspace declared sources do not match composite snapshot components"
        )

    source_descriptors: list[SourceDescriptorV1] = []
    for source_id in sorted(declared):
        workspace_path, _ = declared[source_id]
        component = components[source_id]
        entries = _component_entries(manifest.entries, component)
        records = tuple(
            _file_record_from_snapshot(snapshot, component, entry)
            for entry in entries
        )
        domains = discover_source_domains(
            SimpleNamespace(
                id=source_id,
                path=workspace_path,
                absolute_path=str(_component_root(snapshot, component)),
            )
        ).domains
        descriptor = _build_source_descriptor(
            snapshot.snapshot_id,
            manifest.selection_policy,
            source_id,
            workspace_path,
            records,
            tuple((domain.domain_id, domain.root) for domain in domains),
            authorities,
        )
        source_descriptors.append(descriptor)

    try:
        validate_source_snapshot(snapshot)
    except ReV2SnapshotError as exc:
        raise Protocol22PartitionError(
            f"composite source snapshot changed during partitioning: {exc}"
        ) from exc

    return WorkspacePartitionCatalogV1(
        schema_version=1,
        snapshot_id=snapshot.snapshot_id,
        source_selection_policy_version=manifest.selection_policy,
        partitioner=authorities.partitioner,
        ownership_policy=authorities.ownership_policy,
        sources=tuple(source_descriptors),
    )


def _declared_sources(
    workspace_manifest: WorkspaceManifest,
) -> dict[str, tuple[str, str]]:
    declared: dict[str, tuple[str, str]] = {}
    seen_paths: set[str] = set()
    for source in workspace_manifest.sources:
        source_id = _safe_id(source.id, "workspace source.id")
        path = _root_path(source.path, "workspace source.path")
        git_role = _safe_id(source.git_role, "workspace source.git_role")
        if source_id in declared or path in seen_paths:
            raise Protocol22PartitionError(
                "workspace declared sources must have unique IDs and paths"
            )
        declared[source_id] = (path, git_role)
        seen_paths.add(path)
    if not declared:
        raise Protocol22PartitionError("workspace requires at least one declared source")
    return declared


def _component_entries(
    entries: tuple[SnapshotEntry, ...],
    component: SnapshotComponent,
) -> tuple[SnapshotEntry, ...]:
    prefix = "" if component.workspace_path == "." else component.workspace_path + "/"
    selected: list[SnapshotEntry] = []
    for entry in entries:
        if component.workspace_path == ".":
            relative = entry.path
        elif entry.path.startswith(prefix):
            relative = entry.path[len(prefix) :]
        else:
            continue
        if not relative:
            continue
        selected.append(
            SnapshotEntry(relative, entry.digest, entry.mode, entry.size)
        )
    paths = tuple(entry.path for entry in selected)
    if paths != tuple(sorted(set(paths), key=lambda item: item.encode("utf-8"))):
        raise Protocol22PartitionError(
            f"snapshot component {component.source_id!r} entries are not canonical"
        )
    return tuple(selected)


def _component_root(snapshot: CapturedSnapshot, component: SnapshotComponent) -> Path:
    if component.workspace_path == ".":
        return snapshot.read_root
    return snapshot.read_root.joinpath(*component.workspace_path.split("/"))


def _file_record_from_snapshot(
    snapshot: CapturedSnapshot,
    component: SnapshotComponent,
    entry: SnapshotEntry,
) -> FileRecordV1:
    if entry.mode == 0o644:
        mode: FileModeV1 = "100644"
    elif entry.mode == 0o755:
        mode = "100755"
    else:
        raise Protocol22PartitionError(
            f"snapshot entry has unsupported regular mode: {entry.path}: {entry.mode:o}"
        )
    payload = _read_verified_regular_file(
        _component_root(snapshot, component), entry
    )
    if b"\x00" in payload:
        status: TextStatusV1 = "contains_nul"
    else:
        try:
            payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            status = "invalid_utf8"
        else:
            status = "eligible_utf8"
    return FileRecordV1(
        source_relative_path=entry.path,
        mode=mode,
        object_kind="regular",
        content_hash=entry.digest,
        byte_count=len(payload),
        line_count=_raw_line_count(payload),
        text_status=status,
    )


def _read_verified_regular_file(root: Path, entry: SnapshotEntry) -> bytes:
    parts = PurePosixPath(entry.path).parts
    if not parts:
        raise Protocol22PartitionError("snapshot file path is empty")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        current = os.open(root, directory_flags | nofollow)
        descriptors.append(current)
        for part in parts[:-1]:
            current = os.open(
                part,
                directory_flags | nofollow,
                dir_fd=current,
            )
            descriptors.append(current)
        file_descriptor = os.open(parts[-1], os.O_RDONLY | nofollow, dir_fd=current)
        descriptors.append(file_descriptor)
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise Protocol22PartitionError(
                f"snapshot entry is not a regular file: {entry.path}"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(file_descriptor)
    except OSError as exc:
        raise Protocol22PartitionError(
            f"snapshot entry cannot be read safely: {entry.path}: {exc}"
        ) from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mode,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mode,
        after.st_mtime_ns,
    )
    if identity_before != identity_after:
        raise Protocol22PartitionError(f"snapshot entry changed while read: {entry.path}")
    payload = b"".join(chunks)
    expected_mode = entry.mode & ~0o222
    if (
        len(payload) != entry.size
        or content_digest(payload) != entry.digest
        or stat.S_IMODE(after.st_mode) != expected_mode
    ):
        raise Protocol22PartitionError(
            f"snapshot entry does not match its committed manifest: {entry.path}"
        )
    return payload


def _raw_line_count(payload: bytes) -> int:
    if not payload:
        return 0
    return 1 + payload.count(b"\n") - int(payload.endswith(b"\n"))


def _build_source_descriptor(
    snapshot_id: str,
    selection_policy: str,
    source_id: str,
    workspace_path: str,
    files: tuple[FileRecordV1, ...],
    presentation_domains: tuple[tuple[str, str], ...],
    authorities: PartitionAuthoritiesV1,
) -> SourceDescriptorV1:
    by_path = {record.source_relative_path: record for record in files}
    roots = tuple(root for _, root in presentation_domains)
    if len(roots) != len(set(roots)):
        raise Protocol22PartitionError("partitioner emitted duplicate domain roots")
    ownership: dict[str, str] = {}
    for path in by_path:
        matching = [root for root in roots if _path_belongs_to_root(path, root)]
        if matching:
            ownership[path] = max(
                matching,
                key=lambda root: (0 if root == "." else len(PurePosixPath(root).parts)),
            )
    source_supporting_paths = tuple(
        sorted(
            (path for path in by_path if path not in ownership),
            key=lambda item: item.encode("utf-8"),
        )
    )

    descriptors: list[DomainDescriptorV1] = []
    for presentation_id, root in presentation_domains:
        stable_key = domain_key(source_id, root, authorities.ownership_policy.version)
        owned = tuple(
            by_path[path]
            for path in sorted(
                (path for path, owner in ownership.items() if owner == root),
                key=lambda item: item.encode("utf-8"),
            )
        )
        supporting = tuple(
            by_path[path]
            for path in source_supporting_paths
            if _is_explicit_domain_support(path, root)
        )
        owned_relative_paths = tuple(
            sorted(
                (_domain_relative_path(record.source_relative_path, root) for record in owned),
                key=lambda item: item.encode("utf-8"),
            )
        )
        supporting_paths = tuple(record.source_relative_path for record in supporting)
        partition_id = domain_partition_id(
            authorities.partitioner,
            authorities.ownership_policy,
            stable_key,
            root,
            owned_relative_paths,
            supporting_paths,
        )
        descriptors.append(
            DomainDescriptorV1(
                domain_key=stable_key,
                presentation_domain_id=presentation_id,
                source_relative_root=root,
                owned_file_count=len(owned),
                owned_line_count=sum(record.line_count for record in owned),
                supporting_file_count=len(supporting),
                domain_content_id=domain_content_id(
                    authorities.ownership_policy.version,
                    stable_key,
                    root,
                    owned,
                    supporting,
                ),
                domain_partition_id=partition_id,
                owned_domain_relative_paths=owned_relative_paths,
                supporting_source_relative_paths=supporting_paths,
            )
        )
    canonical_domains = tuple(sorted(descriptors, key=lambda domain: domain.domain_key))
    source_identity_input = SourcePartitionIdentityInputV1(
        source_id=source_id,
        partitioner=authorities.partitioner,
        ownership_policy=authorities.ownership_policy,
        source_supporting_paths=source_supporting_paths,
        domains=tuple(domain.partition_projection() for domain in canonical_domains),
    )
    return SourceDescriptorV1(
        source_id=source_id,
        workspace_relative_path=workspace_path,
        snapshot_id=snapshot_id,
        source_content_id=source_content_id(selection_policy, files),
        source_partition_id=source_partition_id(source_identity_input),
        files=files,
        source_supporting_paths=source_supporting_paths,
        domains=canonical_domains,
    )


def _path_belongs_to_root(path: str, root: str) -> bool:
    return root == "." or path.startswith(root + "/")


def _domain_relative_path(path: str, root: str) -> str:
    if root == ".":
        return path
    prefix = root + "/"
    if not path.startswith(prefix):
        raise Protocol22PartitionError(
            f"owned file {path!r} is outside domain root {root!r}"
        )
    return path[len(prefix) :]


def _is_explicit_domain_support(path: str, domain_root: str) -> bool:
    parts = PurePosixPath(path).parts
    if not parts:
        return False
    if any(part in _GLOBAL_SUPPORT_DIRS for part in parts[:-1]):
        return True
    if len(parts) == 1:
        name = parts[0]
        lowered = name.lower()
        return (
            name in _ROOT_SUPPORT_NAMES
            or lowered == ".env"
            or lowered.startswith(".env.")
            or lowered.startswith(("readme", "license", "dockerfile"))
            or ".config." in lowered
            or PurePosixPath(lowered).suffix in _CONFIG_SUFFIXES
        )
    domain_parts = PurePosixPath(domain_root).parts if domain_root != "." else ()
    parent_parts = parts[:-1]
    if parent_parts and parent_parts == domain_parts[: len(parent_parts)]:
        name = parts[-1].lower()
        return (
            name.startswith(("readme", "license", "dockerfile"))
            or ".config." in name
            or PurePosixPath(name).suffix in _CONFIG_SUFFIXES
        )
    return False


def _canonical_file_records(
    values: Iterable[FileRecordV1], field: str
) -> tuple[FileRecordV1, ...]:
    try:
        records = tuple(values)
    except TypeError as exc:
        raise Protocol22PartitionError(f"{field} must be iterable") from exc
    if any(not isinstance(record, FileRecordV1) for record in records):
        raise Protocol22PartitionError(f"{field} must contain FileRecordV1 values")
    paths = [record.source_relative_path for record in records]
    if len(paths) != len(set(paths)):
        raise Protocol22PartitionError(f"{field} paths must be unique")
    return tuple(
        sorted(records, key=lambda record: record.source_relative_path.encode("utf-8"))
    )


def _canonicalize_paths(values: Iterable[str], field: str) -> tuple[str, ...]:
    try:
        paths = tuple(_normalized_path(value, field) for value in values)
    except TypeError as exc:
        raise Protocol22PartitionError(f"{field} must be iterable") from exc
    if len(paths) != len(set(paths)):
        raise Protocol22PartitionError(f"{field} paths must be unique")
    return tuple(sorted(paths, key=lambda item: item.encode("utf-8")))


def _validate_source_descriptor(
    source: SourceDescriptorV1,
    selection_policy: str,
    authorities: PartitionAuthoritiesV1,
) -> None:
    by_path = {record.source_relative_path: record for record in source.files}
    if source.source_content_id != source_content_id(selection_policy, source.files):
        raise Protocol22PartitionError("source_content_id does not match source files")
    owned_source_paths: set[str] = set()
    seen_roots: set[str] = set()
    seen_presentations: set[str] = set()
    for domain in source.domains:
        if domain.source_relative_root in seen_roots:
            raise Protocol22PartitionError("domain roots must be unique within a source")
        if domain.presentation_domain_id in seen_presentations:
            raise Protocol22PartitionError(
                "presentation domain IDs must be unique within a source"
            )
        seen_roots.add(domain.source_relative_root)
        seen_presentations.add(domain.presentation_domain_id)
        expected_key = domain_key(
            source.source_id,
            domain.source_relative_root,
            authorities.ownership_policy.version,
        )
        if domain.domain_key != expected_key:
            raise Protocol22PartitionError("domain_key does not match its stable scope")
        owned_files: list[FileRecordV1] = []
        for relative in domain.owned_domain_relative_paths:
            source_path = (
                relative
                if domain.source_relative_root == "."
                else f"{domain.source_relative_root}/{relative}"
            )
            record = by_path.get(source_path)
            if record is None:
                raise Protocol22PartitionError(
                    "domain owned path is absent from source files"
                )
            if source_path in owned_source_paths:
                raise Protocol22PartitionError("a source file has multiple domain owners")
            owned_source_paths.add(source_path)
            owned_files.append(record)
        supporting_files: list[FileRecordV1] = []
        for path in domain.supporting_source_relative_paths:
            record = by_path.get(path)
            if record is None:
                raise Protocol22PartitionError(
                    "domain supporting path is absent from source files"
                )
            if path not in source.source_supporting_paths:
                raise Protocol22PartitionError(
                    "domain supporting path is not source-level supporting content"
                )
            supporting_files.append(record)
        expected_partition = domain_partition_id(
            authorities.partitioner,
            authorities.ownership_policy,
            domain.domain_key,
            domain.source_relative_root,
            domain.owned_domain_relative_paths,
            domain.supporting_source_relative_paths,
        )
        if domain.domain_partition_id != expected_partition:
            raise Protocol22PartitionError(
                "domain_partition_id does not match partition inputs"
            )
        expected_content = domain_content_id(
            authorities.ownership_policy.version,
            domain.domain_key,
            domain.source_relative_root,
            owned_files,
            supporting_files,
        )
        if domain.domain_content_id != expected_content:
            raise Protocol22PartitionError("domain_content_id does not match domain files")
        if domain.owned_line_count != sum(record.line_count for record in owned_files):
            raise Protocol22PartitionError(
                "domain owned_line_count does not match owned files"
            )
    expected_support = tuple(
        sorted(
            (path for path in by_path if path not in owned_source_paths),
            key=lambda item: item.encode("utf-8"),
        )
    )
    if source.source_supporting_paths != expected_support:
        raise Protocol22PartitionError(
            "source_supporting_paths must equal the non-domain-owned file set"
        )
    expected_source_partition = source_partition_id(
        source.partition_identity_input(authorities)
    )
    if source.source_partition_id != expected_source_partition:
        raise Protocol22PartitionError(
            "source_partition_id does not match source partition inputs"
        )
