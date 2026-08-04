"""Published workspace reverse-engineering registry helpers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from harness.re_artifacts import (
    ReArtifactCatalogError,
    ReArtifactDescriptor,
    classify_re_artifact,
    validate_re_artifact_descriptor,
)

RE_REGISTRY_SCHEMA_VERSION = 1
_SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_INDEX_STATUSES = frozenset({"complete", "partial"})
_SOURCE_STATUSES = frozenset({"complete", "partial", "empty"})
_WORKSPACE_FIELDS = ("manifest", "overview", "relationships", "contracts")
_RUNTIME_PARTS = frozenset({".cache", ".staging", ".locks"})


class ReRegistryError(RuntimeError):
    """Raised when the published RE registry is malformed or unsafe."""


@dataclass(frozen=True)
class ReRegistryPaths:
    root: Path
    index: Path
    sources: Path
    workspace: Path
    cache: Path
    staging: Path
    locks: Path
    gitignore: Path

    @classmethod
    def for_workspace(cls, workspace_root: Path) -> "ReRegistryPaths":
        root = workspace_root.resolve() / "re"
        return cls(
            root=root,
            index=root / "index.json",
            sources=root / "sources",
            workspace=root / "workspace",
            cache=root / ".cache",
            staging=root / ".staging",
            locks=root / ".locks",
            gitignore=root / ".gitignore",
        )


@dataclass(frozen=True)
class PublishedSource:
    source_id: str
    source_path: str
    published_path: str
    fingerprint: str
    profile_hash: str
    status: str
    manifest: str
    manifest_artifact: ReArtifactDescriptor | None = None


@dataclass(frozen=True)
class PublishedWorkspace:
    manifest: str
    overview: str
    relationships: str
    contracts: str
    codegraph_summary: str | None = None
    manifest_artifact: ReArtifactDescriptor | None = None


@dataclass(frozen=True)
class PublishedReIndex:
    schema_version: int
    generation: int
    publication_status: str
    published_at: str
    published_from_run: str
    sources: dict[str, PublishedSource]
    workspace: PublishedWorkspace
    warnings: tuple[str, ...]

    @classmethod
    def from_path(cls, path: Path) -> "PublishedReIndex":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReRegistryError(f"cannot read RE index {path}: {exc}") from exc
        return _parse_index(raw, workspace_root=path.resolve().parent.parent)


def ensure_re_layout(workspace_root: Path) -> ReRegistryPaths:
    """Create the RE ownership boundary without inventing a publication."""
    paths = ReRegistryPaths.for_workspace(workspace_root)
    for directory in (
        paths.root,
        paths.sources,
        paths.workspace,
        paths.cache,
        paths.staging,
        paths.locks,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    existing = paths.gitignore.read_text(encoding="utf-8") if paths.gitignore.exists() else ""
    lines = existing.splitlines()
    for required in (".cache/", ".staging/", ".locks/"):
        if required not in lines:
            lines.append(required)
    paths.gitignore.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return paths


def load_published_index(workspace_root: Path) -> PublishedReIndex | None:
    path = ReRegistryPaths.for_workspace(workspace_root).index
    return PublishedReIndex.from_path(path) if path.is_file() else None


def canonical_re_artifacts(
    workspace_root: Path,
    index: PublishedReIndex,
) -> dict[str, object]:
    """Project normalized descriptors into the legacy squad context shape."""
    root = workspace_root.resolve()
    paths = ReRegistryPaths.for_workspace(root)
    descriptors = canonical_re_artifact_descriptors(root, index)
    by_path = {descriptor.path: descriptor for descriptor in descriptors}

    def absolute(descriptor: ReArtifactDescriptor) -> str:
        return str(root / descriptor.path)

    def exact(relative_path: str, field: str) -> str:
        descriptor = by_path.get(relative_path)
        if descriptor is None:
            raise ReRegistryError(
                f"registered artifact is missing for {field}: {relative_path}"
            )
        return absolute(descriptor)

    source_dirs = [
        str(
            _existing_registry_path(
                root,
                index.sources[source_id].published_path,
                "published_path",
            )
        )
        for source_id in sorted(index.sources)
    ]
    source_manifests: dict[str, str] = {}
    source_overviews: list[str] = []
    specs: list[str] = []
    codegraph_summaries: list[str] = []
    codegraph_analyses: list[str] = []
    source_domain_manifests: dict[str, str] = {}
    source_supporting_artifacts: dict[str, str] = {}
    source_extraction_artifacts: dict[str, dict[str, str]] = {}
    source_architecture: dict[str, str] = {}
    source_contracts: dict[str, str] = {}
    source_components: dict[str, str] = {}
    source_adrs: dict[str, list[str]] = {}

    for source_id in sorted(index.sources):
        source = index.sources[source_id]
        manifest_path = _existing_registry_path(root, source.manifest, "manifest")
        manifest = _read_object(manifest_path, "source manifest")
        if manifest.get("schema_version") != RE_REGISTRY_SCHEMA_VERSION:
            raise ReRegistryError(f"unsupported source manifest schema: {manifest_path}")
        if manifest.get("source_id") != source_id:
            raise ReRegistryError(f"source manifest ID mismatch: {manifest_path}")
        expected_prefix = PurePosixPath(f"re/sources/{source_id}")
        source_manifests[source_id] = exact(
            source.manifest, f"source manifest {source_id}"
        )
        overview = _required_string(manifest, "overview", str(manifest_path))
        _require_prefix(overview, expected_prefix, "overview")
        source_overviews.append(exact(overview, f"source overview {source_id}"))

        raw_specs = manifest.get("specs")
        if not isinstance(raw_specs, list) or any(
            not isinstance(item, str) for item in raw_specs
        ):
            raise ReRegistryError(
                f"source manifest specs must be a list of paths: {manifest_path}"
            )
        for spec in raw_specs:
            _require_prefix(spec, expected_prefix / "specs", "spec")
            specs.append(exact(spec, f"source spec {source_id}"))

        for key, destination in (
            ("architecture", source_architecture),
            ("contracts", source_contracts),
            ("components", source_components),
            ("domain_manifest", source_domain_manifests),
            ("supporting_artifacts", source_supporting_artifacts),
        ):
            value = manifest.get(key)
            if isinstance(value, str) and value.strip():
                value = value.strip()
                _require_prefix(value, expected_prefix, key)
                destination[source_id] = exact(value, f"source {key} {source_id}")

        for key, destination in (
            ("codegraph_summary", codegraph_summaries),
            ("codegraph_analysis", codegraph_analyses),
        ):
            value = manifest.get(key)
            if isinstance(value, str) and value.strip():
                value = value.strip()
                _require_prefix(value, expected_prefix, key)
                destination.append(exact(value, f"source {key} {source_id}"))

        extraction = manifest.get("extraction_artifacts")
        if isinstance(extraction, dict):
            selected: dict[str, str] = {}
            for key, value in sorted(extraction.items()):
                if (
                    not isinstance(key, str)
                    or not isinstance(value, str)
                    or not value.strip()
                ):
                    raise ReRegistryError(
                        f"source extraction artifacts must map names to paths: {source_id}"
                    )
                value = value.strip()
                _require_prefix(value, expected_prefix, f"extraction_artifacts.{key}")
                selected[key] = exact(
                    value, f"source extraction_artifacts.{key} {source_id}"
                )
            source_extraction_artifacts[source_id] = selected

    source_rows = [
        descriptor for descriptor in descriptors if descriptor.scope == "source"
    ]
    workspace_rows = [
        descriptor for descriptor in descriptors if descriptor.scope == "workspace"
    ]
    specs.extend(
        absolute(row)
        for row in workspace_rows
        if row.kind == "re-domain" and row.path.startswith("re/workspace/domains/")
    )
    for source_id in sorted(index.sources):
        owned = [row for row in source_rows if row.source_id == source_id]
        adrs = [absolute(row) for row in owned if row.kind == "re-decision"]
        if adrs:
            source_adrs[source_id] = adrs

    workspace_manifest = exact(index.workspace.manifest, "workspace.manifest")
    workspace_overview = exact(index.workspace.overview, "workspace.overview")
    workspace_relationships = exact(
        index.workspace.relationships, "workspace.relationships"
    )
    workspace_contracts = exact(index.workspace.contracts, "workspace.contracts")
    architecture_map = next(
        (absolute(row) for row in workspace_rows if row.kind == "re-architecture-map"),
        None,
    )
    domain_catalog = next(
        (
            absolute(row)
            for row in workspace_rows
            if row.path == "re/workspace/domain-catalog.md"
        ),
        None,
    )
    workspace_checklist = next(
        (
            absolute(row)
            for row in workspace_rows
            if row.kind == "re-workspace-checklist"
        ),
        None,
    )
    workspace_strategy = [
        absolute(row)
        for row in workspace_rows
        if row.path.startswith("re/workspace/strategy/") and row.path.endswith(".md")
    ]

    re_contexts = source_overviews + specs + [
        workspace_overview,
        workspace_relationships,
        workspace_contracts,
    ]
    if architecture_map:
        re_contexts.append(architecture_map)
    if workspace_checklist:
        re_contexts.append(workspace_checklist)
    re_contexts.extend(workspace_strategy)
    re_contexts.extend(codegraph_summaries)
    re_contexts.extend(source_architecture.values())
    re_contexts.extend(source_contracts.values())
    re_contexts.extend(source_components.values())
    for paths_for_source in source_adrs.values():
        re_contexts.extend(paths_for_source)
    re_contexts.extend(source_domain_manifests.values())
    re_contexts.extend(source_supporting_artifacts.values())
    if domain_catalog:
        re_contexts.append(domain_catalog)
    workspace_codegraph_summary = None
    if index.workspace.codegraph_summary:
        workspace_codegraph_summary = exact(
            index.workspace.codegraph_summary,
            "workspace.codegraph_summary",
        )
        re_contexts.append(workspace_codegraph_summary)
    return {
        "manifest": str(paths.index),
        "source_index": str(paths.index),
        "workspace_manifest": workspace_manifest,
        "architecture_map": architecture_map,
        "domain_catalog": domain_catalog,
        "workspace_checklist": workspace_checklist,
        "workspace_strategy": workspace_strategy,
        "re_overview": workspace_overview,
        "cross_repo": workspace_relationships,
        "contracts": workspace_contracts,
        "workspace_codegraph_summary": workspace_codegraph_summary,
        "source_manifests": source_manifests,
        "per_repo": source_dirs,
        "re_specs": specs,
        "codegraph_summaries": codegraph_summaries,
        "codegraph_analyses": codegraph_analyses,
        "source_architecture": source_architecture,
        "source_contracts": source_contracts,
        "source_components": source_components,
        "source_adrs": source_adrs,
        "source_domain_manifests": source_domain_manifests,
        "source_supporting_artifacts": source_supporting_artifacts,
        "source_extraction_artifacts": source_extraction_artifacts,
        "re_contexts": re_contexts,
        "artifact_descriptors": [
            descriptor.to_json_dict() for descriptor in descriptors
        ],
    }


def canonical_re_artifact_descriptors(
    workspace_root: Path,
    index: PublishedReIndex,
) -> tuple[ReArtifactDescriptor, ...]:
    """Return one validated, path-sorted descriptor for each registered artifact."""
    owner_descriptors = [index.workspace.manifest_artifact] + [
        index.sources[source_id].manifest_artifact for source_id in sorted(index.sources)
    ]
    typed_owners = sum(descriptor is not None for descriptor in owner_descriptors)
    if typed_owners == 0:
        return _legacy_re_artifact_descriptors(workspace_root.resolve(), index)
    if typed_owners != len(owner_descriptors):
        raise ReRegistryError(
            "typed RE publication requires manifest_artifact for every owner"
        )
    return _typed_re_artifact_descriptors(workspace_root.resolve(), index)


def _typed_re_artifact_descriptors(
    workspace_root: Path,
    index: PublishedReIndex,
) -> tuple[ReArtifactDescriptor, ...]:
    descriptors: list[ReArtifactDescriptor] = []
    seen_paths: set[str] = set()

    for source_id in sorted(index.sources):
        source = index.sources[source_id]
        assert source.manifest_artifact is not None
        descriptor = _validate_registry_descriptor(
            source.manifest_artifact.to_json_dict(),
            workspace_root=workspace_root,
            owner_scope="source",
            owner_source_id=source_id,
        )
        _append_unique_descriptor(descriptors, seen_paths, descriptor)
    assert index.workspace.manifest_artifact is not None
    workspace_manifest = _validate_registry_descriptor(
        index.workspace.manifest_artifact.to_json_dict(),
        workspace_root=workspace_root,
        owner_scope="workspace",
        owner_source_id=None,
    )
    _append_unique_descriptor(descriptors, seen_paths, workspace_manifest)

    for source_id in sorted(index.sources):
        source = index.sources[source_id]
        manifest_path = _existing_registry_path(
            workspace_root, source.manifest, "manifest"
        )
        manifest = _read_object(manifest_path, "source manifest")
        if manifest.get("schema_version") != RE_REGISTRY_SCHEMA_VERSION:
            raise ReRegistryError(f"unsupported source manifest schema: {manifest_path}")
        if manifest.get("source_id") != source_id:
            raise ReRegistryError(f"source manifest ID mismatch: {manifest_path}")
        _append_typed_catalog(
            manifest,
            workspace_root=workspace_root,
            owner_scope="source",
            owner_source_id=source_id,
            descriptors=descriptors,
            seen_paths=seen_paths,
        )

    workspace_manifest_path = _existing_registry_path(
        workspace_root, index.workspace.manifest, "workspace.manifest"
    )
    workspace_manifest_payload = _read_object(
        workspace_manifest_path, "workspace manifest"
    )
    if workspace_manifest_payload.get("schema_version") != RE_REGISTRY_SCHEMA_VERSION:
        raise ReRegistryError(
            f"unsupported workspace manifest schema: {workspace_manifest_path}"
        )
    _append_typed_catalog(
        workspace_manifest_payload,
        workspace_root=workspace_root,
        owner_scope="workspace",
        owner_source_id=None,
        descriptors=descriptors,
        seen_paths=seen_paths,
    )
    return tuple(sorted(descriptors, key=lambda descriptor: descriptor.path))


def _append_typed_catalog(
    manifest: dict[str, Any],
    *,
    workspace_root: Path,
    owner_scope: str,
    owner_source_id: str | None,
    descriptors: list[ReArtifactDescriptor],
    seen_paths: set[str],
) -> None:
    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise ReRegistryError("typed owner artifact catalog must be a list")

    catalog_paths: list[str] = []
    for raw in raw_artifacts:
        descriptor = _validate_registry_descriptor(
            raw,
            workspace_root=workspace_root,
            owner_scope=owner_scope,
            owner_source_id=owner_source_id,
        )
        _append_unique_descriptor(descriptors, seen_paths, descriptor)
        catalog_paths.append(descriptor.path)
    if catalog_paths != sorted(catalog_paths):
        raise ReRegistryError("artifact catalog paths are not sorted")


def _validate_registry_descriptor(
    raw: object,
    *,
    workspace_root: Path,
    owner_scope: str,
    owner_source_id: str | None,
) -> ReArtifactDescriptor:
    try:
        return validate_re_artifact_descriptor(
            raw,
            workspace_root=workspace_root,
            owner_scope=owner_scope,
            owner_source_id=owner_source_id,
        )
    except ReArtifactCatalogError as exc:
        raise ReRegistryError(f"invalid artifact descriptor: {exc}") from exc


def _append_unique_descriptor(
    descriptors: list[ReArtifactDescriptor],
    seen_paths: set[str],
    descriptor: ReArtifactDescriptor,
) -> None:
    if descriptor.path in seen_paths:
        raise ReRegistryError(f"duplicate artifact path: {descriptor.path}")
    seen_paths.add(descriptor.path)
    descriptors.append(descriptor)


def _legacy_re_artifact_descriptors(
    workspace_root: Path,
    index: PublishedReIndex,
) -> tuple[ReArtifactDescriptor, ...]:
    paths = ReRegistryPaths.for_workspace(workspace_root)
    descriptors: dict[str, ReArtifactDescriptor] = {}

    def add(relative_path: str, *, scope: str, source_id: str | None = None) -> None:
        normalized = _safe_relative_path(relative_path, "artifact")
        artifact_path = _existing_registry_path(
            workspace_root, normalized, "artifact"
        )
        try:
            kind = classify_re_artifact(PurePosixPath(normalized), scope=scope)
        except ReArtifactCatalogError as exc:
            raise ReRegistryError(
                f"cannot classify legacy artifact {normalized}: {exc}"
            ) from exc
        descriptors.setdefault(
            normalized,
            ReArtifactDescriptor(
                kind=kind,
                path=normalized,
                sha256="sha256:"
                + hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                scope=scope,
                source_id=source_id,
            ),
        )

    for source_id in sorted(index.sources):
        source = index.sources[source_id]
        _existing_registry_path(
            workspace_root, source.published_path, "published_path"
        )
        manifest_path = _existing_registry_path(
            workspace_root, source.manifest, "manifest"
        )
        manifest = _read_object(manifest_path, "source manifest")
        if manifest.get("schema_version") != RE_REGISTRY_SCHEMA_VERSION:
            raise ReRegistryError(f"unsupported source manifest schema: {manifest_path}")
        if manifest.get("source_id") != source_id:
            raise ReRegistryError(f"source manifest ID mismatch: {manifest_path}")
        expected_prefix = PurePosixPath(f"re/sources/{source_id}")
        add(source.manifest, scope="source", source_id=source_id)

        overview = _required_string(manifest, "overview", str(manifest_path))
        _require_prefix(overview, expected_prefix, "overview")
        add(overview, scope="source", source_id=source_id)
        raw_specs = manifest.get("specs")
        if not isinstance(raw_specs, list) or any(
            not isinstance(item, str) for item in raw_specs
        ):
            raise ReRegistryError(
                f"source manifest specs must be a list of paths: {manifest_path}"
            )
        for spec in raw_specs:
            _require_prefix(spec, expected_prefix / "specs", "spec")
            add(spec, scope="source", source_id=source_id)

        for key in (
            "codegraph_summary",
            "codegraph_analysis",
            "domain_manifest",
            "architecture",
            "contracts",
            "components",
            "supporting_artifacts",
        ):
            value = manifest.get(key)
            if isinstance(value, str) and value.strip():
                value = value.strip()
                _require_prefix(value, expected_prefix, key)
                add(value, scope="source", source_id=source_id)
        extraction = manifest.get("extraction_artifacts")
        if isinstance(extraction, dict):
            for key, value in sorted(extraction.items()):
                if (
                    not isinstance(key, str)
                    or not isinstance(value, str)
                    or not value.strip()
                ):
                    raise ReRegistryError(
                        f"source extraction artifacts must map names to paths: {source_id}"
                    )
                value = value.strip()
                _require_prefix(value, expected_prefix, f"extraction_artifacts.{key}")
                add(value, scope="source", source_id=source_id)
        adrs_dir = paths.sources / source_id / "adrs"
        if adrs_dir.is_dir():
            for adr in sorted(adrs_dir.rglob("*.md")):
                if adr.is_file():
                    add(
                        adr.relative_to(workspace_root).as_posix(),
                        scope="source",
                        source_id=source_id,
                    )

    for field in _WORKSPACE_FIELDS:
        add(getattr(index.workspace, field), scope="workspace")
    for optional in (
        paths.workspace / "architecture-map.json",
        paths.workspace / "domain-catalog.md",
        paths.workspace / "checklist.md",
    ):
        if optional.is_file():
            add(optional.relative_to(workspace_root).as_posix(), scope="workspace")
    domains = paths.workspace / "domains"
    if domains.is_dir():
        for domain in sorted(domains.glob("*.md")):
            if domain.is_file():
                add(domain.relative_to(workspace_root).as_posix(), scope="workspace")
    strategy = paths.workspace / "strategy"
    if strategy.is_dir():
        for document in sorted(strategy.rglob("*.md")):
            if document.is_file():
                add(document.relative_to(workspace_root).as_posix(), scope="workspace")
    if index.workspace.codegraph_summary:
        add(index.workspace.codegraph_summary, scope="workspace")
    return tuple(descriptors[path] for path in sorted(descriptors))


def published_source_is_usable(
    workspace_root: Path,
    index: PublishedReIndex,
    source_id: str,
    *,
    expect_empty: bool | None = None,
) -> bool:
    """Return whether one published source has a complete durable file set."""
    source = index.sources.get(source_id)
    if source is None:
        return False
    try:
        root = workspace_root.resolve()
        manifest_path = _existing_registry_path(root, source.manifest, "manifest")
        manifest = _read_object(manifest_path, "source manifest")
        if manifest.get("schema_version") != RE_REGISTRY_SCHEMA_VERSION:
            return False
        if manifest.get("source_id") != source_id:
            return False
        if manifest.get("source_path") != source.source_path:
            return False
        if manifest.get("source_fingerprint") != source.fingerprint:
            return False
        if manifest.get("profile_hash") != source.profile_hash:
            return False
        if manifest.get("publication_status") != source.status:
            return False
        overview = _required_string(manifest, "overview", str(manifest_path))
        _require_prefix(overview, PurePosixPath(f"re/sources/{source_id}"), "overview")
        _existing_registry_path(root, overview, "overview")
        raw_specs = manifest.get("specs")
        if not isinstance(raw_specs, list) or any(not isinstance(item, str) for item in raw_specs):
            return False
        if expect_empty is True and (source.status != "empty" or raw_specs):
            return False
        if expect_empty is False and (source.status == "empty" or not raw_specs):
            return False
        for spec in raw_specs:
            _require_prefix(spec, PurePosixPath(f"re/sources/{source_id}/specs"), "spec")
            _existing_registry_path(root, spec, "spec")
    except ReRegistryError:
        return False
    return True


def published_source_is_current(
    workspace_root: Path,
    index: PublishedReIndex,
    source_id: str,
    *,
    source_path: str,
    fingerprint: str,
    profile_hash: str,
    expect_empty: bool,
    quality_contract_version: int | None = None,
) -> bool:
    """Return whether source state exactly matches its durable publication."""
    source = index.sources.get(source_id)
    if not (
        source
        and source.status == "complete"
        and source.source_path == source_path
        and source.fingerprint == fingerprint
        and source.profile_hash == profile_hash
        and published_source_is_usable(
            workspace_root,
            index,
            source_id,
            expect_empty=expect_empty,
        )
    ):
        return False
    if quality_contract_version is None:
        return True
    try:
        manifest_path = _existing_registry_path(
            workspace_root.resolve(), source.manifest, "manifest"
        )
        manifest = _read_object(manifest_path, "source manifest")
    except ReRegistryError:
        return False
    return (
        manifest.get("quality_contract_version") == quality_contract_version
        and manifest.get("publication_status") in {None, "complete"}
    )


def _parse_index(raw: Any, *, workspace_root: Path) -> PublishedReIndex:
    if not isinstance(raw, dict):
        raise ReRegistryError("RE index must be a JSON object")
    schema_version = _required_int(raw, "schema_version", "RE index")
    if schema_version != RE_REGISTRY_SCHEMA_VERSION:
        raise ReRegistryError(f"unsupported RE index schema_version: {schema_version}")
    generation = _required_int(raw, "generation", "RE index")
    if generation < 1:
        raise ReRegistryError("RE index generation must be at least 1")
    publication_status = _required_string(raw, "publication_status", "RE index")
    if publication_status not in _INDEX_STATUSES:
        raise ReRegistryError(f"invalid RE publication_status: {publication_status}")

    raw_sources = raw.get("sources")
    if not isinstance(raw_sources, dict):
        raise ReRegistryError("RE index sources must be an object")
    sources: dict[str, PublishedSource] = {}
    for source_id, source_raw in raw_sources.items():
        if not isinstance(source_id, str) or not _SAFE_SOURCE_ID.fullmatch(source_id):
            raise ReRegistryError(f"invalid source ID: {source_id!r}")
        if not isinstance(source_raw, dict):
            raise ReRegistryError(f"source entry must be an object: {source_id}")
        source_path = _safe_relative_path(
            _required_string(source_raw, "path", source_id), "path", allow_dot=True
        )
        published_path = _safe_relative_path(
            _required_string(source_raw, "published_path", source_id), "published_path"
        )
        expected_published_path = f"re/sources/{source_id}"
        if published_path != expected_published_path:
            raise ReRegistryError(
                f"published_path for {source_id} must be {expected_published_path}"
            )
        manifest = _safe_relative_path(
            _required_string(source_raw, "manifest", source_id), "manifest"
        )
        expected_manifest = f"{expected_published_path}/manifest.json"
        if manifest != expected_manifest:
            raise ReRegistryError(f"manifest for {source_id} must be {expected_manifest}")
        status = _required_string(source_raw, "status", source_id)
        if status not in _SOURCE_STATUSES:
            raise ReRegistryError(f"invalid source status for {source_id}: {status}")
        sources[source_id] = PublishedSource(
            source_id=source_id,
            source_path=source_path,
            published_path=published_path,
            fingerprint=_required_string(source_raw, "fingerprint", source_id),
            profile_hash=_required_string(source_raw, "profile_hash", source_id),
            status=status,
            manifest=manifest,
            manifest_artifact=_parse_manifest_artifact(
                source_raw.get("manifest_artifact"),
                workspace_root=workspace_root,
                owner_scope="source",
                owner_source_id=source_id,
                expected_path=expected_manifest,
                expected_kind="re-source-manifest",
            ),
        )

    raw_workspace = raw.get("workspace")
    if not isinstance(raw_workspace, dict):
        raise ReRegistryError("RE index workspace must be an object")
    workspace_values: dict[str, Any] = {}
    for field in _WORKSPACE_FIELDS:
        value = _safe_relative_path(
            _required_string(raw_workspace, field, "workspace"), f"workspace.{field}"
        )
        expected = f"re/workspace/{'manifest.json' if field == 'manifest' else field + '.md'}"
        if value != expected:
            raise ReRegistryError(f"workspace.{field} must be {expected}")
        workspace_values[field] = value
    if isinstance(raw_workspace.get("codegraph_summary"), str):
        value = _safe_relative_path(
            raw_workspace["codegraph_summary"], "workspace.codegraph_summary"
        )
        expected = "re/workspace/codegraph-summary.json"
        if value != expected:
            raise ReRegistryError(f"workspace.codegraph_summary must be {expected}")
        workspace_values["codegraph_summary"] = value
    workspace_values["manifest_artifact"] = _parse_manifest_artifact(
        raw_workspace.get("manifest_artifact"),
        workspace_root=workspace_root,
        owner_scope="workspace",
        owner_source_id=None,
        expected_path="re/workspace/manifest.json",
        expected_kind="re-workspace-manifest",
    )

    raw_warnings = raw.get("warnings")
    if not isinstance(raw_warnings, list) or any(not isinstance(item, str) for item in raw_warnings):
        raise ReRegistryError("RE index warnings must be a list of strings")

    return PublishedReIndex(
        schema_version=schema_version,
        generation=generation,
        publication_status=publication_status,
        published_at=_required_string(raw, "published_at", "RE index"),
        published_from_run=_required_string(raw, "published_from_run", "RE index"),
        sources=sources,
        workspace=PublishedWorkspace(**workspace_values),
        warnings=tuple(raw_warnings),
    )


def _parse_manifest_artifact(
    raw: object,
    *,
    workspace_root: Path,
    owner_scope: str,
    owner_source_id: str | None,
    expected_path: str,
    expected_kind: str,
) -> ReArtifactDescriptor | None:
    if raw is None:
        return None
    try:
        descriptor = validate_re_artifact_descriptor(
            raw,
            workspace_root=workspace_root,
            owner_scope=owner_scope,
            owner_source_id=owner_source_id,
        )
    except ReArtifactCatalogError as exc:
        raise ReRegistryError(f"invalid manifest_artifact: {exc}") from exc
    if descriptor.path != expected_path or descriptor.kind != expected_kind:
        raise ReRegistryError("manifest_artifact does not describe the owner manifest")
    return descriptor


def _required_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ReRegistryError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def _required_int(data: dict[str, Any], key: str, context: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReRegistryError(f"{context}.{key} must be an integer")
    return value


def _safe_relative_path(value: str, field: str, *, allow_dot: bool = False) -> str:
    if "\\" in value:
        raise ReRegistryError(f"{field} must use POSIX relative paths")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ReRegistryError(f"unsafe {field}: {value}")
    normalized = path.as_posix()
    if normalized == "." and allow_dot:
        return normalized
    if normalized in {"", "."}:
        raise ReRegistryError(f"empty {field}")
    if _RUNTIME_PARTS.intersection(path.parts):
        raise ReRegistryError(f"runtime path is not durable {field}: {value}")
    return normalized


def _require_prefix(value: str, prefix: PurePosixPath, field: str) -> None:
    normalized = PurePosixPath(_safe_relative_path(value, field))
    if not normalized.is_relative_to(prefix):
        raise ReRegistryError(f"{field} must remain under {prefix.as_posix()}: {value}")


def _existing_registry_path(workspace_root: Path, value: str, field: str) -> Path:
    relative = _safe_relative_path(value, field)
    candidate = workspace_root / relative
    if not candidate.exists():
        raise ReRegistryError(f"published {field} does not exist: {relative}")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(workspace_root):
        raise ReRegistryError(f"published {field} escapes workspace: {relative}")
    return resolved


def _read_object(path: Path, context: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReRegistryError(f"cannot read {context} {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ReRegistryError(f"{context} must be a JSON object: {path}")
    return raw
