"""Typed descriptors and deterministic catalogs for published RE artifacts."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


SUPPORTED_RE_ARTIFACT_KINDS = frozenset(
    {
        "re-source-manifest",
        "re-workspace-manifest",
        "re-overview",
        "re-architecture",
        "re-contracts",
        "re-components",
        "re-decision",
        "re-codegraph-summary",
        "re-codegraph-analysis",
        "re-analysis",
        "re-structure",
        "re-configs",
        "re-dependencies",
        "re-domain-manifest",
        "re-generated-spec",
        "re-generated-checklist",
        "re-supporting-artifacts",
        "re-architecture-map",
        "re-relationships",
        "re-domain",
        "re-strategy",
        "re-workspace-checklist",
        "re-quality-report",
    }
)

_SUPPORTED_SCOPES = frozenset({"source", "workspace"})
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class ReArtifactCatalogError(RuntimeError):
    """Raised when a typed RE artifact descriptor or catalog is invalid."""


@dataclass(frozen=True)
class ReArtifactDescriptor:
    kind: str
    path: str
    sha256: str
    scope: str
    source_id: str | None = None

    def to_json_dict(self) -> dict[str, str]:
        payload = {
            "kind": self.kind,
            "path": self.path,
            "sha256": self.sha256,
            "scope": self.scope,
        }
        if self.source_id is not None:
            payload["source_id"] = self.source_id
        return payload


def build_re_artifact_catalog(
    directory: Path,
    *,
    published_prefix: PurePosixPath,
    scope: str,
    source_id: str | None = None,
) -> tuple[ReArtifactDescriptor, ...]:
    """Build a sorted descriptor catalog for one published ownership directory."""
    directory = directory.resolve()
    if not directory.is_dir():
        raise ReArtifactCatalogError(f"catalog directory does not exist: {directory}")
    _validate_scope(scope)
    prefix = _validate_published_prefix(published_prefix, scope, source_id)
    if scope == "source" and source_id is None:
        raise ReArtifactCatalogError("source catalog requires source_id")
    if scope == "workspace" and source_id is not None:
        raise ReArtifactCatalogError("workspace catalog forbids source_id")

    descriptors: list[ReArtifactDescriptor] = []
    seen_paths: set[str] = set()
    for path in sorted(path for path in directory.rglob("*") if path.is_file()):
        relative = PurePosixPath(path.relative_to(directory).as_posix())
        if relative == PurePosixPath("manifest.json"):
            continue
        published_path = prefix / relative
        path_string = published_path.as_posix()
        if path_string in seen_paths:
            raise ReArtifactCatalogError(f"duplicate artifact path: {path_string}")
        seen_paths.add(path_string)
        kind = classify_re_artifact(published_path, scope=scope)
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        descriptors.append(
            ReArtifactDescriptor(
                kind=kind,
                path=path_string,
                sha256=digest,
                scope=scope,
                source_id=source_id,
            )
        )
    return tuple(sorted(descriptors, key=lambda descriptor: descriptor.path))


def validate_re_artifact_descriptor(
    raw: object,
    *,
    workspace_root: Path,
    owner_scope: str,
    owner_source_id: str | None = None,
) -> ReArtifactDescriptor:
    """Validate one descriptor against its owning published file."""
    if not isinstance(raw, dict):
        raise ReArtifactCatalogError("descriptor must be an object")
    kind = _required_string(raw, "kind")
    path = _required_string(raw, "path")
    sha256 = _required_string(raw, "sha256")
    scope = _required_string(raw, "scope")
    _validate_scope(owner_scope)
    if kind not in SUPPORTED_RE_ARTIFACT_KINDS:
        raise ReArtifactCatalogError(f"unsupported artifact kind: {kind}")
    if scope != owner_scope:
        raise ReArtifactCatalogError("descriptor scope does not match owner scope")
    if not _SHA256_PATTERN.fullmatch(sha256):
        raise ReArtifactCatalogError("sha256 must use lowercase hex")
    normalized_path = _validate_path(path)
    expected_prefix = _owner_prefix(owner_scope, owner_source_id)
    if not _has_prefix(normalized_path, expected_prefix):
        raise ReArtifactCatalogError("descriptor path does not match owner scope")
    if classify_re_artifact(normalized_path, scope=owner_scope) != kind:
        raise ReArtifactCatalogError("descriptor kind does not match artifact path")

    source_id: str | None
    if owner_scope == "source":
        if "source_id" not in raw:
            raise ReArtifactCatalogError("source descriptor requires source_id")
        source_value = raw["source_id"]
        if not isinstance(source_value, str) or not source_value:
            raise ReArtifactCatalogError("source_id must be a non-empty string")
        if source_value != owner_source_id:
            raise ReArtifactCatalogError("descriptor source_id does not match owner")
        source_id = source_value
    else:
        if "source_id" in raw:
            raise ReArtifactCatalogError("workspace descriptor forbids source_id")
        source_id = None

    root = workspace_root.resolve()
    artifact_path = (root / Path(*normalized_path.parts)).resolve()
    if not artifact_path.is_relative_to(root):
        raise ReArtifactCatalogError("descriptor path escapes workspace")
    if not artifact_path.is_file():
        raise ReArtifactCatalogError("artifact file does not exist")
    observed = "sha256:" + hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if observed != sha256:
        raise ReArtifactCatalogError("artifact hash mismatch")
    return ReArtifactDescriptor(
        kind=kind,
        path=normalized_path.as_posix(),
        sha256=sha256,
        scope=scope,
        source_id=source_id,
    )


def classify_re_artifact(relative_path: PurePosixPath, *, scope: str) -> str:
    """Classify a normalized published path using the stable RE taxonomy."""
    _validate_scope(scope)
    path = _validate_path(relative_path.as_posix())
    parts = path.parts
    if scope == "source":
        if len(parts) < 4 or parts[:2] != ("re", "sources"):
            raise ReArtifactCatalogError("artifact path does not match source scope")
        remainder = parts[3:]
        if remainder == ("manifest.json",):
            return "re-source-manifest"
        if remainder[0] == "adrs" and len(remainder) > 1 and remainder[-1].endswith(".md"):
            return "re-decision"
        if remainder[0] == "specs" and remainder[-1] == "spec.md":
            return "re-generated-spec"
        if remainder[0] == "specs" and remainder[-1] == "checklist.md":
            return "re-generated-checklist"
        if remainder[0] == "quality" and len(remainder) > 1:
            return "re-quality-report"
        return _classify_named_file(remainder[-1], scope=scope)

    if len(parts) < 3 or parts[:2] != ("re", "workspace"):
        raise ReArtifactCatalogError("artifact path does not match workspace scope")
    remainder = parts[2:]
    if remainder == ("manifest.json",):
        return "re-workspace-manifest"
    if remainder[0] == "adrs" and len(remainder) > 1 and remainder[-1].endswith(".md"):
        return "re-decision"
    if len(remainder) > 1 and remainder[:2] == ("strategy", "adrs") and remainder[-1].endswith(".md"):
        return "re-decision"
    if remainder[0] == "domains" and len(remainder) > 1 and remainder[-1].endswith(".md"):
        return "re-domain"
    if remainder[0] == "strategy" and len(remainder) > 1 and remainder[-1].endswith(".md"):
        return "re-strategy"
    if remainder[0] == "quality" and len(remainder) > 1:
        return "re-quality-report"
    if remainder[-1] == "domain-catalog.md":
        return "re-domain"
    return _classify_named_file(remainder[-1], scope=scope)


def _classify_named_file(name: str, *, scope: str) -> str:
    names = {
        "analysis.json": "re-analysis",
        "architecture.md": "re-architecture",
        "architecture-map.json": "re-architecture-map",
        "checklist.md": (
            "re-workspace-checklist" if scope == "workspace" else "re-generated-checklist"
        ),
        "codegraph-analysis.json": "re-codegraph-analysis",
        "codegraph-summary.json": "re-codegraph-summary",
        "components.md": "re-components",
        "configs.json": "re-configs",
        "contracts.md": "re-contracts",
        "dependencies.json": "re-dependencies",
        "domain-manifest.json": "re-domain-manifest",
        "overview.md": "re-overview",
        "relationships.md": "re-relationships",
        "structure.json": "re-structure",
        "supporting-artifacts.md": "re-supporting-artifacts",
    }
    try:
        return names[name]
    except KeyError as exc:
        raise ReArtifactCatalogError(f"unsupported artifact path: {name}") from exc


def _validate_scope(scope: str) -> None:
    if scope not in _SUPPORTED_SCOPES:
        raise ReArtifactCatalogError(f"unsupported artifact scope: {scope}")


def _validate_published_prefix(
    published_prefix: PurePosixPath,
    scope: str,
    source_id: str | None,
) -> PurePosixPath:
    prefix = _validate_path(published_prefix.as_posix())
    expected = _owner_prefix(scope, source_id)
    if prefix != expected:
        raise ReArtifactCatalogError("published prefix does not match owner scope")
    return prefix


def _owner_prefix(scope: str, source_id: str | None) -> PurePosixPath:
    _validate_scope(scope)
    if scope == "workspace":
        if source_id is not None:
            raise ReArtifactCatalogError("workspace owner forbids source_id")
        return PurePosixPath("re/workspace")
    if source_id is None:
        raise ReArtifactCatalogError("source owner requires source_id")
    if not _SAFE_SOURCE_ID.fullmatch(source_id):
        raise ReArtifactCatalogError("source_id is not safe")
    return PurePosixPath("re/sources") / source_id


def _validate_path(path: str) -> PurePosixPath:
    if not path or "\\" in path:
        raise ReArtifactCatalogError("path must be a normalized re path")
    if path.startswith("/"):
        raise ReArtifactCatalogError("path must be relative")
    if ".." in path.split("/"):
        raise ReArtifactCatalogError("path must not contain traversal")
    normalized = PurePosixPath(path)
    if normalized.is_absolute() or normalized.as_posix() != path:
        raise ReArtifactCatalogError("path must be a normalized re path")
    if len(normalized.parts) < 2 or normalized.parts[0] != "re":
        raise ReArtifactCatalogError("path must be below re/")
    if "." in path.split("/"):
        raise ReArtifactCatalogError("path must be normalized")
    return normalized


def _has_prefix(path: PurePosixPath, prefix: PurePosixPath) -> bool:
    return len(path.parts) > len(prefix.parts) and path.parts[: len(prefix.parts)] == prefix.parts


def _required_string(raw: dict[Any, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ReArtifactCatalogError(f"descriptor field {key} must be a non-empty string")
    return value
