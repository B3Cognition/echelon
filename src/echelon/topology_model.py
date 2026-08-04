"""Immutable, provider-neutral records for source topology reads.

The records in this module intentionally carry only source-relative identity
and provenance. Native provider payloads can contain an analyzed repository
path, but that host-specific path never crosses this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import posixpath
import re
from types import MappingProxyType
from typing import Mapping


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_SYMBOL_KEY = re.compile(r"sha256:[0-9a-f]{64}\Z")

NODE_TYPES = frozenset({"SOURCE", "FILE", "SYMBOL"})
RELATIONSHIP_TYPES = frozenset(
    {
        "CONTAINS",
        "DECLARES",
        "IMPORTS",
        "REQUIRES",
        "CALLS",
        "EXTENDS",
        "IMPLEMENTS",
        "USES_ROLE",
        "TESTS",
        "REFERENCES",
        "INSTANTIATES",
        "DECORATES",
        "OTHER",
    }
)


class TopologyValidationError(ValueError):
    """Raised when a topology identity or record is unsafe or malformed."""


def validate_source_id(source_id: str) -> str:
    """Return one safe configured source identifier."""
    return _validate_identifier(source_id, "source id")


def validate_provider(provider: str) -> str:
    """Return one safe provider identifier."""
    return _validate_identifier(provider, "provider")


def normalize_source_path(path: str) -> str:
    """Validate and return a canonical POSIX source-relative path."""
    if not isinstance(path, str) or not path:
        raise TopologyValidationError("source-relative path must be a non-empty string")
    if "\\" in path:
        raise TopologyValidationError(f"source-relative path must not use backslashes: {path!r}")
    if path.startswith("/") or re.match(r"^[A-Za-z]:/", path):
        raise TopologyValidationError(f"source-relative path must not be absolute: {path!r}")
    segments = path.split("/")
    if any(segment == ".." for segment in segments):
        raise TopologyValidationError(f"source-relative path must not traverse parents: {path!r}")
    normalized = posixpath.normpath(path)
    if normalized in {"", "."} or normalized.startswith("../") or normalized == "..":
        raise TopologyValidationError(f"invalid source-relative path: {path!r}")
    if normalized != path:
        raise TopologyValidationError(f"source-relative path is not normalized: {path!r}")
    return normalized.removeprefix("./")


def validate_symbol_key(symbol_key: str) -> str:
    """Validate one canonical provider symbol key."""
    if not isinstance(symbol_key, str) or not _SYMBOL_KEY.fullmatch(symbol_key):
        raise TopologyValidationError(f"invalid symbol key: {symbol_key!r}")
    return symbol_key


def validate_generation(generation: int) -> int:
    """Return one canonical positive topology publication generation."""
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise TopologyValidationError("topology generation must be an integer at least 1")
    return generation


def canonical_symbol_key(
    path: str, qualified_name: str, kind: str, signature: str | None = None
) -> str:
    """Return the schema-2 SHA-256 key for one provider symbol locator."""
    normalized_path = normalize_source_path(path)
    if not isinstance(qualified_name, str) or not qualified_name:
        raise TopologyValidationError("qualified name must be a non-empty string")
    if not isinstance(kind, str) or not kind:
        raise TopologyValidationError("symbol kind must be a non-empty string")
    if signature is not None and not isinstance(signature, str):
        raise TopologyValidationError("symbol signature must be a string or null")
    locator = json.dumps(
        [normalized_path, qualified_name, kind, signature or ""],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(locator.encode("utf-8")).hexdigest()


def source_node_id(source_id: str) -> str:
    """Return the canonical public node identifier for a source."""
    return f"source:{validate_source_id(source_id)}"


def file_id(source_id: str, path: str) -> str:
    """Return the canonical public node identifier for a source file."""
    return f"file:{validate_source_id(source_id)}:{normalize_source_path(path)}"


def symbol_id(source_id: str, provider: str, symbol_key: str, *, path: str | None = None) -> str:
    """Return the canonical public node identifier for a provider symbol."""
    validate_source_id(source_id)
    validate_provider(provider)
    if path is not None:
        normalize_source_path(path)
    return f"symbol:{source_id}:{provider}:{validate_symbol_key(symbol_key)[7:]}"


@dataclass(frozen=True, slots=True)
class TopologySource:
    """One configured source, represented independently of native providers."""

    source_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", validate_source_id(self.source_id))

    @property
    def id(self) -> str:
        return source_node_id(self.source_id)

    @property
    def type(self) -> str:
        return "SOURCE"


@dataclass(frozen=True, slots=True)
class TopologyFile:
    """A source-relative file represented once across provider output."""

    source_id: str
    path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", validate_source_id(self.source_id))
        object.__setattr__(self, "path", normalize_source_path(self.path))

    @property
    def id(self) -> str:
        return file_id(self.source_id, self.path)

    @property
    def type(self) -> str:
        return "FILE"


@dataclass(frozen=True, slots=True)
class TopologySymbol:
    """A provider-scoped symbol with a recomputable stable locator key."""

    source_id: str
    provider: str
    symbol_key: str
    path: str
    qualified_name: str
    kind: str
    signature: str = ""
    name: str = ""
    line_start: int | None = None
    line_end: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", validate_source_id(self.source_id))
        object.__setattr__(self, "provider", validate_provider(self.provider))
        object.__setattr__(self, "path", normalize_source_path(self.path))
        if not isinstance(self.qualified_name, str) or not self.qualified_name:
            raise TopologyValidationError("qualified name must be a non-empty string")
        _reject_absolute_host_path(self.qualified_name, "qualified name")
        if not isinstance(self.kind, str) or not self.kind:
            raise TopologyValidationError("symbol kind must be a non-empty string")
        if not isinstance(self.signature, str):
            raise TopologyValidationError("symbol signature must be a string")
        _reject_absolute_host_path(self.name, "symbol name")
        expected = canonical_symbol_key(
            self.path, self.qualified_name, self.kind, self.signature
        )
        if validate_symbol_key(self.symbol_key) != expected:
            raise TopologyValidationError(
                f"symbol key does not match canonical locator: {self.qualified_name}"
            )
        if self.line_start is not None and (
            not isinstance(self.line_start, int) or self.line_start <= 0
        ):
            raise TopologyValidationError("symbol line_start must be a positive integer")
        if self.line_end is not None and (
            not isinstance(self.line_end, int) or self.line_end <= 0
        ):
            raise TopologyValidationError("symbol line_end must be a positive integer")
        if self.line_start and self.line_end and self.line_end < self.line_start:
            raise TopologyValidationError("symbol line_end must not precede line_start")

    @property
    def id(self) -> str:
        return symbol_id(self.source_id, self.provider, self.symbol_key, path=self.path)

    @property
    def type(self) -> str:
        return "SYMBOL"


@dataclass(frozen=True, slots=True)
class TopologyRelationship:
    """One normalized traversable relationship between public topology nodes."""

    source_id: str
    target_id: str
    type: str
    provider: str
    provider_kind: str
    path: str | None = None
    line_start: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id:
            raise TopologyValidationError("relationship source id must be non-empty")
        if not isinstance(self.target_id, str) or not self.target_id:
            raise TopologyValidationError("relationship target id must be non-empty")
        if self.type not in RELATIONSHIP_TYPES:
            raise TopologyValidationError(f"unsupported topology relationship type: {self.type!r}")
        object.__setattr__(self, "provider", validate_provider(self.provider))
        if not isinstance(self.provider_kind, str) or not self.provider_kind:
            raise TopologyValidationError("provider relationship kind must be non-empty")
        if self.path is not None:
            object.__setattr__(self, "path", normalize_source_path(self.path))
        if self.line_start is not None and (
            not isinstance(self.line_start, int) or self.line_start <= 0
        ):
            raise TopologyValidationError("relationship line_start must be a positive integer")


@dataclass(frozen=True, slots=True)
class TopologyDiagnostic:
    """A provider observation that was intentionally not made traversable."""

    provider: str
    provider_kind: str
    source_key: str | None = None
    target_key: str | None = None
    source_name: str = ""
    target_name: str = ""
    path: str | None = None
    line_start: int | None = None
    confidence: str | None = None
    provenance: tuple[str, ...] = ()
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", validate_provider(self.provider))
        if not isinstance(self.provider_kind, str) or not self.provider_kind:
            raise TopologyValidationError("provider diagnostic kind must be non-empty")
        _reject_absolute_host_path(self.source_name, "diagnostic source name")
        _reject_absolute_host_path(self.target_name, "diagnostic target name")
        if self.source_key is not None:
            object.__setattr__(self, "source_key", validate_symbol_key(self.source_key))
        if self.target_key is not None:
            object.__setattr__(self, "target_key", validate_symbol_key(self.target_key))
        if self.path is not None:
            object.__setattr__(self, "path", normalize_source_path(self.path))
        if self.line_start is not None and (
            not isinstance(self.line_start, int) or self.line_start <= 0
        ):
            raise TopologyValidationError("diagnostic line_start must be a positive integer")
        if self.confidence is not None and self.confidence not in {
            "high",
            "medium",
            "low",
            "dynamic",
        }:
            raise TopologyValidationError("diagnostic confidence is unsupported")
        if not isinstance(self.provenance, tuple) or any(
            not isinstance(value, str) or not value for value in self.provenance
        ):
            raise TopologyValidationError("diagnostic provenance must be a tuple of non-empty strings")
        if self.notes is not None:
            if not isinstance(self.notes, str):
                raise TopologyValidationError("diagnostic notes must be a string or null")
            _reject_absolute_host_path(self.notes, "diagnostic notes")


@dataclass(frozen=True, slots=True)
class TopologyReceipt:
    """Bounded provenance returned with every topology read result."""

    generation: int
    source_id: str | None
    source_fingerprint: str | None = None
    source_fingerprints: Mapping[str, str] = field(default_factory=dict)
    provider_receipt_hashes: Mapping[str, str] = field(default_factory=dict)
    provider_artifact_paths: tuple[str, ...] = ()
    provider_statuses: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "generation", validate_generation(self.generation))
        if self.source_id is not None:
            object.__setattr__(self, "source_id", validate_source_id(self.source_id))
        if self.source_fingerprint is not None:
            if not isinstance(self.source_fingerprint, str) or not self.source_fingerprint:
                raise TopologyValidationError("source fingerprint must be a non-empty string")
            _reject_absolute_host_path(self.source_fingerprint, "source fingerprint")
        fingerprints = {
            validate_source_id(source_id): _validate_source_fingerprint(value)
            for source_id, value in self.source_fingerprints.items()
        }
        if self.source_id is not None:
            existing = fingerprints.get(self.source_id)
            if existing is not None and self.source_fingerprint is not None and existing != self.source_fingerprint:
                raise TopologyValidationError("single-source fingerprint does not match source_fingerprints")
            if self.source_fingerprint is None and existing is not None:
                object.__setattr__(self, "source_fingerprint", existing)
            elif self.source_fingerprint is not None:
                fingerprints[self.source_id] = self.source_fingerprint
        object.__setattr__(self, "source_fingerprints", MappingProxyType(dict(sorted(fingerprints.items()))))
        hashes = {_validate_receipt_provider_key(key): _validate_sha256(value) for key, value in self.provider_receipt_hashes.items()}
        statuses = {_validate_receipt_provider_key(key): value for key, value in self.provider_statuses.items()}
        if any(value not in {"ready", "degraded", "empty", "unsupported"} for value in statuses.values()):
            raise TopologyValidationError("unknown normalized provider status")
        object.__setattr__(self, "provider_receipt_hashes", MappingProxyType(dict(sorted(hashes.items()))))
        object.__setattr__(self, "provider_statuses", MappingProxyType(dict(sorted(statuses.items()))))
        object.__setattr__(
            self,
            "provider_artifact_paths",
            tuple(sorted({normalize_source_path(path) for path in self.provider_artifact_paths})),
        )


@dataclass(frozen=True, slots=True)
class TopologySearchResult:
    """Bounded lexical topology search result."""

    receipt: TopologyReceipt
    nodes: tuple[TopologySource | TopologyFile | TopologySymbol, ...]
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class TopologyExplainResult:
    """One selected node and its direct relationships."""

    receipt: TopologyReceipt
    node: TopologySource | TopologyFile | TopologySymbol
    relationships: tuple[TopologyRelationship, ...]
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class TopologyTraversalStep:
    """One directed traversal observation over a stored relationship."""

    relationship: TopologyRelationship
    direction: str
    node_id: str
    depth: int

    def __post_init__(self) -> None:
        if self.direction not in {"in", "out"}:
            raise TopologyValidationError(f"unsupported traversal direction: {self.direction!r}")
        if not isinstance(self.node_id, str) or not self.node_id:
            raise TopologyValidationError("traversal node id must be non-empty")
        if not isinstance(self.depth, int) or self.depth < 1:
            raise TopologyValidationError("traversal depth must be positive")


@dataclass(frozen=True, slots=True)
class TopologyTraversalResult:
    """Bounded deterministic traversal result."""

    receipt: TopologyReceipt
    nodes: tuple[TopologySource | TopologyFile | TopologySymbol, ...]
    relationships: tuple[TopologyRelationship, ...]
    steps: tuple[TopologyTraversalStep, ...]
    truncated: bool = False


def _validate_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise TopologyValidationError(f"unsafe {label}: {value!r}")
    return value


def _validate_sha256(value: str) -> str:
    if not isinstance(value, str) or not _SYMBOL_KEY.fullmatch(value):
        raise TopologyValidationError(f"invalid SHA-256 value: {value!r}")
    return value


def _validate_receipt_provider_key(value: str) -> str:
    """Validate a provider key, optionally source-qualified for multi-source reads."""
    if ":" not in value:
        return validate_provider(value)
    source_id, provider = value.split(":", 1)
    validate_source_id(source_id)
    validate_provider(provider)
    return value


def _validate_source_fingerprint(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise TopologyValidationError("source fingerprint must be a non-empty string")
    _reject_absolute_host_path(value, "source fingerprint")
    return value


def _reject_absolute_host_path(value: str, label: str) -> None:
    if not isinstance(value, str):
        raise TopologyValidationError(f"{label} must be a string")
    if value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value):
        raise TopologyValidationError(f"{label} must not expose an absolute host path")
