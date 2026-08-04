"""Published workspace reverse-engineering registry helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from harness.re_artifacts import (
    ReArtifactCatalogError,
    ReArtifactDescriptor,
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
    """Return the durable published context expected by squad consumers."""
    root = workspace_root.resolve()
    paths = ReRegistryPaths.for_workspace(root)
    source_dirs: list[str] = []
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
        source_dir = _existing_registry_path(root, source.published_path, "published_path")
        manifest_path = _existing_registry_path(root, source.manifest, "manifest")
        manifest = _read_object(manifest_path, "source manifest")
        if manifest.get("schema_version") != RE_REGISTRY_SCHEMA_VERSION:
            raise ReRegistryError(f"unsupported source manifest schema: {manifest_path}")
        if manifest.get("source_id") != source_id:
            raise ReRegistryError(f"source manifest ID mismatch: {manifest_path}")

        overview_value = _required_string(manifest, "overview", str(manifest_path))
        overview_path = _existing_registry_path(root, overview_value, "overview")
        expected_prefix = PurePosixPath(f"re/sources/{source_id}")
        _require_prefix(overview_value, expected_prefix, "overview")

        raw_specs = manifest.get("specs")
        if not isinstance(raw_specs, list) or any(not isinstance(item, str) for item in raw_specs):
            raise ReRegistryError(f"source manifest specs must be a list of paths: {manifest_path}")
        for spec_value in raw_specs:
            _require_prefix(spec_value, expected_prefix / "specs", "spec")
            specs.append(str(_existing_registry_path(root, spec_value, "spec")))

        summary_value = manifest.get("codegraph_summary")
        if isinstance(summary_value, str) and summary_value.strip():
            summary_value = summary_value.strip()
            _require_prefix(summary_value, expected_prefix, "codegraph_summary")
            codegraph_summaries.append(
                str(_existing_registry_path(root, summary_value, "codegraph_summary"))
            )
        analysis_value = manifest.get("codegraph_analysis")
        if isinstance(analysis_value, str) and analysis_value.strip():
            analysis_value = analysis_value.strip()
            _require_prefix(analysis_value, expected_prefix, "codegraph_analysis")
            codegraph_analyses.append(
                str(_existing_registry_path(root, analysis_value, "codegraph_analysis"))
            )
        domain_manifest_value = manifest.get("domain_manifest")
        if isinstance(domain_manifest_value, str) and domain_manifest_value.strip():
            domain_manifest_value = domain_manifest_value.strip()
            _require_prefix(domain_manifest_value, expected_prefix, "domain_manifest")
            source_domain_manifests[source_id] = str(
                _existing_registry_path(root, domain_manifest_value, "domain_manifest")
            )
        for manifest_key, destination in (
            ("architecture", source_architecture),
            ("contracts", source_contracts),
            ("components", source_components),
        ):
            raw_value = manifest.get(manifest_key)
            if isinstance(raw_value, str) and raw_value.strip():
                raw_value = raw_value.strip()
                _require_prefix(raw_value, expected_prefix, manifest_key)
                destination[source_id] = str(
                    _existing_registry_path(root, raw_value, manifest_key)
                )
        supporting_value = manifest.get("supporting_artifacts")
        if isinstance(supporting_value, str) and supporting_value.strip():
            supporting_value = supporting_value.strip()
            _require_prefix(supporting_value, expected_prefix, "supporting_artifacts")
            source_supporting_artifacts[source_id] = str(
                _existing_registry_path(root, supporting_value, "supporting_artifacts")
            )
        extraction_value = manifest.get("extraction_artifacts")
        if isinstance(extraction_value, dict):
            source_extraction_artifacts[source_id] = _source_extraction_artifacts(
                root,
                source_id,
                extraction_value,
            )
        adrs_dir = paths.sources / source_id / "adrs"
        if adrs_dir.is_dir():
            source_adrs[source_id] = [
                str(path)
                for path in sorted(adrs_dir.rglob("*.md"))
                if path.is_file()
            ]

        source_dirs.append(str(source_dir))
        source_manifests[source_id] = str(manifest_path)
        source_overviews.append(str(overview_path))

    workspace_paths = {
        field: _existing_registry_path(root, getattr(index.workspace, field), f"workspace.{field}")
        for field in _WORKSPACE_FIELDS
    }
    workspace_domains = paths.workspace / "domains"
    architecture_map = paths.workspace / "architecture-map.json"
    domain_catalog = paths.workspace / "domain-catalog.md"
    workspace_checklist = paths.workspace / "checklist.md"
    workspace_strategy = [
        str(path)
        for path in sorted((paths.workspace / "strategy").rglob("*.md"))
        if path.is_file()
    ]
    if workspace_domains.is_dir():
        specs.extend(
            str(path)
            for path in sorted(workspace_domains.glob("*.md"))
            if path.is_file()
        )

    re_contexts = source_overviews + specs + [
        str(workspace_paths["overview"]),
        str(workspace_paths["relationships"]),
        str(workspace_paths["contracts"]),
    ]
    if architecture_map.is_file():
        re_contexts.append(str(architecture_map))
    if workspace_checklist.is_file():
        re_contexts.append(str(workspace_checklist))
    re_contexts.extend(workspace_strategy)
    re_contexts.extend(codegraph_summaries)
    re_contexts.extend(source_architecture.values())
    re_contexts.extend(source_contracts.values())
    re_contexts.extend(source_components.values())
    for paths_for_source in source_adrs.values():
        re_contexts.extend(paths_for_source)
    re_contexts.extend(source_domain_manifests.values())
    re_contexts.extend(source_supporting_artifacts.values())
    if domain_catalog.is_file():
        re_contexts.append(str(domain_catalog))
    workspace_codegraph_summary = None
    if index.workspace.codegraph_summary:
        workspace_codegraph_summary = str(
            _existing_registry_path(
                root,
                index.workspace.codegraph_summary,
                "workspace.codegraph_summary",
            )
        )
        re_contexts.append(workspace_codegraph_summary)
    return {
        "manifest": str(paths.index),
        "source_index": str(paths.index),
        "workspace_manifest": str(workspace_paths["manifest"]),
        "architecture_map": str(architecture_map) if architecture_map.is_file() else None,
        "domain_catalog": str(domain_catalog) if domain_catalog.is_file() else None,
        "workspace_checklist": str(workspace_checklist) if workspace_checklist.is_file() else None,
        "workspace_strategy": workspace_strategy,
        "re_overview": str(workspace_paths["overview"]),
        "cross_repo": str(workspace_paths["relationships"]),
        "contracts": str(workspace_paths["contracts"]),
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
    }


def _source_extraction_artifacts(
    workspace_root: Path,
    source_id: str,
    value: dict[Any, Any],
) -> dict[str, str]:
    expected_prefix = PurePosixPath(f"re/sources/{source_id}")
    artifacts: dict[str, str] = {}
    for key, raw_path in sorted(value.items()):
        if not isinstance(key, str) or not isinstance(raw_path, str) or not raw_path.strip():
            raise ReRegistryError(
                f"source extraction artifacts must map names to paths: {source_id}"
            )
        raw_path = raw_path.strip()
        _require_prefix(raw_path, expected_prefix, f"extraction_artifacts.{key}")
        artifacts[key] = str(
            _existing_registry_path(workspace_root, raw_path, f"extraction_artifacts.{key}")
        )
    return artifacts


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
