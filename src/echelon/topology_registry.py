"""Canonical, read-only registry for published source topology."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Iterable, Mapping

from echelon.topology_model import (
    TopologySource,
    TopologyValidationError,
    normalize_source_path,
    validate_generation,
    validate_provider,
    validate_source_id,
)
from echelon.topology_provider import (
    NORMALIZED_STATUSES,
    PublishedTopology,
    TopologyProviderError,
    load_provider_document,
)
from echelon.workspace_model import discover_workspace
from harness.re_fingerprint import SourceFingerprint


_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_HEAD = re.compile(r"[0-9a-f]{40}\Z")
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_RFC3339 = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_INDEX_PATH = "re/topology/index.json"


class TopologyRegistryError(RuntimeError):
    """Raised when a published topology registry is absent, unsafe, or inconsistent."""


@dataclass(frozen=True, slots=True)
class TopologyArtifactReceipt:
    """One hash-addressed, source-owned published artifact."""

    name: str
    path: str
    sha256: str

    def __post_init__(self) -> None:
        _artifact_name(self.name)
        try:
            object.__setattr__(self, "path", normalize_source_path(self.path))
        except TopologyValidationError as exc:
            raise TopologyRegistryError(str(exc)) from exc
        if not isinstance(self.sha256, str) or not _SHA256.fullmatch(self.sha256):
            raise TopologyRegistryError("topology artifact sha256 must be sha256:<64 lowercase hex>")


@dataclass(frozen=True, slots=True)
class TopologyProviderReceipt:
    """The receipt-owned contract for one named provider."""

    provider: str
    status: str
    complete: bool
    artifacts: Mapping[str, TopologyArtifactReceipt]
    artifact_schema_version: int | None = None
    tool_version: str | None = None
    capabilities: tuple[str, ...] = ()
    counts: Mapping[str, int] = field(default_factory=dict)
    diagnostics: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        try:
            provider = validate_provider(self.provider)
        except TopologyValidationError as exc:
            raise TopologyRegistryError(str(exc)) from exc
        if self.status not in NORMALIZED_STATUSES:
            raise TopologyRegistryError(f"unknown topology provider status: {self.status!r}")
        if not isinstance(self.complete, bool):
            raise TopologyRegistryError("topology provider complete must be a boolean")
        artifacts: dict[str, TopologyArtifactReceipt] = {}
        for name, artifact in self.artifacts.items():
            _artifact_name(name)
            if not isinstance(artifact, TopologyArtifactReceipt):
                raise TopologyRegistryError("topology provider artifacts must map names to receipts")
            if artifact.name != name:
                raise TopologyRegistryError("topology artifact map key does not match artifact name")
            artifacts[name] = artifact
        if "analysis" not in artifacts:
            raise TopologyRegistryError(f"topology provider {provider} has no analysis artifact")
        if self.artifact_schema_version is not None and (
            not isinstance(self.artifact_schema_version, int)
            or isinstance(self.artifact_schema_version, bool)
            or self.artifact_schema_version < 1
        ):
            raise TopologyRegistryError("artifact_schema_version must be a positive integer")
        if self.tool_version is not None and (
            not isinstance(self.tool_version, str) or not self.tool_version
        ):
            raise TopologyRegistryError("provider tool_version must be a non-empty string")
        if self.tool_version is not None:
            _reject_host_path(self.tool_version)
        if any(not isinstance(value, str) or not value for value in self.capabilities):
            raise TopologyRegistryError("provider capabilities must contain non-empty strings")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise TopologyRegistryError("provider capabilities must not contain duplicates")
        for capability in self.capabilities:
            _reject_host_path(capability)
        counts: dict[str, int] = {}
        for name, value in self.counts.items():
            if not isinstance(name, str) or not name or isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise TopologyRegistryError("provider counts must map names to non-negative integers")
            _reject_host_path(name)
            counts[name] = value
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "artifacts", MappingProxyType(dict(sorted(artifacts.items()))))
        object.__setattr__(self, "capabilities", tuple(sorted(set(self.capabilities))))
        object.__setattr__(self, "counts", MappingProxyType(dict(sorted(counts.items()))))
        frozen_diagnostics = tuple(_freeze_json(value) for value in self.diagnostics)
        object.__setattr__(self, "diagnostics", tuple(sorted(frozen_diagnostics, key=_stable_value)))


@dataclass(frozen=True, slots=True)
class TopologySourceRecord:
    """One source row from the authoritative index, elaborated by its receipt."""

    source_id: str
    source_path: str
    source_fingerprint: SourceFingerprint
    receipt: TopologyArtifactReceipt
    providers: Mapping[str, TopologyProviderReceipt]
    generation: int
    analyzed_commit: str | None
    provenance: Mapping[str, object]

    def __post_init__(self) -> None:
        try:
            source_id = validate_source_id(self.source_id)
            source_path = normalize_source_path(self.source_path)
            generation = validate_generation(self.generation)
        except TopologyValidationError as exc:
            raise TopologyRegistryError(str(exc)) from exc
        if not isinstance(self.source_fingerprint, SourceFingerprint):
            raise TopologyRegistryError("source_fingerprint must be a SourceFingerprint")
        _validate_fingerprint(self.source_fingerprint)
        providers: dict[str, TopologyProviderReceipt] = {}
        for provider, receipt in self.providers.items():
            if not isinstance(receipt, TopologyProviderReceipt) or provider != receipt.provider:
                raise TopologyRegistryError("topology provider map is inconsistent")
            providers[validate_provider(provider)] = receipt
        _validate_commit(self.analyzed_commit, self.source_fingerprint)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "source_path", source_path)
        object.__setattr__(self, "generation", generation)
        object.__setattr__(self, "providers", MappingProxyType(dict(sorted(providers.items()))))
        object.__setattr__(self, "provenance", _freeze_mapping(self.provenance))


@dataclass(frozen=True, slots=True)
class TopologyIndex:
    """Immutable canonical topology publication index."""

    schema_version: int
    generation: int
    published_at: str
    sources: Mapping[str, TopologySourceRecord]

    def __post_init__(self) -> None:
        _schema_version({"schema_version": self.schema_version}, "topology index")
        try:
            generation = validate_generation(self.generation)
        except TopologyValidationError as exc:
            raise TopologyRegistryError(str(exc)) from exc
        object.__setattr__(self, "published_at", _published_at(self.published_at))
        sources: dict[str, TopologySourceRecord] = {}
        for source_id, source in self.sources.items():
            if not isinstance(source, TopologySourceRecord) or source.source_id != source_id:
                raise TopologyRegistryError("topology index source map is inconsistent")
            sources[validate_source_id(source_id)] = source
        object.__setattr__(self, "generation", generation)
        object.__setattr__(self, "sources", MappingProxyType(dict(sorted(sources.items()))))


def load_topology_index(
    project_root: Path,
    *,
    allow_removed_source_ids: Iterable[str] = (),
) -> TopologyIndex | None:
    """Load canonical topology, optionally retaining explicit rows being removed.

    The optional reconciliation set is only for the writer's one transaction: it
    lets that transaction hash-validate an old row before removing it after the
    workspace manifest has stopped declaring the source. Normal readers retain
    the exact-manifest contract by using the default empty set.
    """
    root = Path(project_root).resolve()
    allowed_removed = frozenset(validate_source_id(value) for value in allow_removed_source_ids)
    path = root / _INDEX_PATH
    if not path.exists() and not path.is_symlink():
        return None
    if not path.is_file() or path.is_symlink():
        raise TopologyRegistryError(f"unsafe topology index: {_INDEX_PATH}")
    document = _read_json(path, "topology index")
    try:
        return _parse_index(root, document, allowed_removed)
    except TopologyRegistryError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise TopologyRegistryError(f"malformed topology index: {exc}") from exc


def load_published_topology(
    project_root: Path, source_ids: Iterable[str] = ()
) -> PublishedTopology:
    """Load selected, hash-verified native analyses from the canonical index only."""
    root = Path(project_root).resolve()
    index = load_topology_index(root)
    if index is None:
        raise TopologyRegistryError("topology index is missing")
    selected = _select_sources(index, source_ids)
    providers = []
    source_fingerprints: dict[str, str] = {}
    receipt_hashes: dict[str, dict[str, str]] = {}
    artifact_paths: dict[str, dict[str, str]] = {}
    statuses: dict[str, dict[str, str]] = {}
    for source in selected:
        source_fingerprints[source.source_id] = source.source_fingerprint.value
        receipt_hashes[source.source_id] = {}
        artifact_paths[source.source_id] = {}
        statuses[source.source_id] = {}
        for provider_name, provider_receipt in source.providers.items():
            for artifact in provider_receipt.artifacts.values():
                raw = _read_hashed_artifact(root, source.source_id, artifact)
                if artifact.name != "analysis":
                    continue
                try:
                    document = _read_json_bytes(
                        raw, f"{provider_name} analysis for {source.source_id}"
                    )
                    loaded = replace(
                        load_provider_document(
                            document,
                            provider=provider_name,
                            source_id=source.source_id,
                        ),
                        artifact_hash=artifact.sha256,
                    )
                except (TopologyProviderError, TopologyValidationError) as exc:
                    raise TopologyRegistryError(
                        f"invalid {provider_name} analysis for {source.source_id}: {exc}"
                    ) from exc
                if loaded.status != provider_receipt.status or loaded.complete != provider_receipt.complete:
                    raise TopologyRegistryError(
                        f"provider receipt disagrees with analysis for {source.source_id}/{provider_name}"
                    )
                if loaded.tool_version != provider_receipt.tool_version:
                    raise TopologyRegistryError(
                        f"provider receipt tool version disagrees with analysis for {source.source_id}/{provider_name}"
                    )
                _validate_receipt_counts(provider_receipt, loaded.symbols, loaded.relationships)
                providers.append(loaded)
                receipt_hashes[source.source_id][provider_name] = source.receipt.sha256
                artifact_paths[source.source_id][provider_name] = artifact.path
                statuses[source.source_id][provider_name] = loaded.status
        loaded_names = set(receipt_hashes[source.source_id])
        if loaded_names != set(source.providers):
            raise TopologyRegistryError(
                f"selected source did not load every authoritative provider: {source.source_id}"
            )
    return PublishedTopology.from_loaded_providers(
        providers,
        generation=index.generation,
        source_fingerprints=source_fingerprints,
        provider_receipt_hashes=receipt_hashes,
        provider_artifact_paths=artifact_paths,
        provider_statuses=statuses,
        sources=(TopologySource(source.source_id) for source in selected),
    )


def _parse_index(
    root: Path,
    document: object,
    allowed_removed: frozenset[str] = frozenset(),
) -> TopologyIndex:
    data = _object(document, "topology index")
    _exact_keys(data, {"schema_version", "generation", "published_at", "sources"}, "topology index")
    _schema_version(data, "topology index")
    generation = _positive_int(data, "generation")
    published_at = _published_at(data.get("published_at"))
    sources_data = _object(data.get("sources"), "topology index sources")
    manifest = discover_workspace(root)
    configured = _configured_sources(root, manifest.sources)
    if set(sources_data) != set(configured) | set(allowed_removed):
        missing = sorted(set(configured) - set(sources_data))
        unknown = sorted(set(sources_data) - set(configured) - set(allowed_removed))
        detail = ", ".join([*(f"missing {value}" for value in missing), *(f"unknown {value}" for value in unknown)])
        raise TopologyRegistryError(f"topology index sources do not match workspace manifest: {detail}")
    sources: dict[str, TopologySourceRecord] = {}
    for source_id in sorted(sources_data):
        source_id = _source_id(source_id)
        raw_source = _object(
            sources_data[source_id], f"topology index source {source_id}"
        )
        configured_path = configured.get(source_id)
        if configured_path is None:
            if source_id not in allowed_removed:
                raise TopologyRegistryError(
                    f"topology index contains undeclared source: {source_id}"
                )
            configured_path = _source_path(
                raw_source.get("source_path"), f"index source {source_id} path"
            )
        sources[source_id] = _parse_source(
            root,
            source_id,
            raw_source,
            generation,
            configured_path,
        )
    return TopologyIndex(1, generation, published_at, sources)


def _parse_source(
    root: Path,
    source_id: str,
    data: Mapping[str, object],
    generation: int,
    configured_path: str,
) -> TopologySourceRecord:
    _exact_keys(data, {"source_path", "source_fingerprint", "receipt", "providers"}, f"index source {source_id}")
    source_path = _source_path(data.get("source_path"), f"index source {source_id} path")
    if source_path != configured_path:
        raise TopologyRegistryError(f"topology source path changed for {source_id}: {source_path!r}")
    fingerprint = _parse_fingerprint(data.get("source_fingerprint"), f"index source {source_id}")
    receipt = _parse_artifact(data.get("receipt"), "receipt", source_id)
    index_providers = _parse_providers(
        _object(data.get("providers"), f"index providers {source_id}"), source_id, detailed=False
    )
    for provider_receipt in index_providers.values():
        for artifact in provider_receipt.artifacts.values():
            _read_hashed_artifact(root, source_id, artifact)
    receipt_document = _read_json_bytes(_read_hashed_artifact(root, source_id, receipt), f"receipt {source_id}")
    receipt_source, receipt_fingerprint, receipt_providers, analyzed_commit, provenance, receipt_generation = _parse_source_receipt(
        receipt_document, source_id, source_path, generation
    )
    if receipt_source != source_id or receipt_fingerprint != fingerprint:
        raise TopologyRegistryError(f"source receipt identity disagrees with index for {source_id}")
    _assert_provider_catalog_equal(index_providers, receipt_providers, source_id)
    return TopologySourceRecord(
        source_id=source_id,
        source_path=source_path,
        source_fingerprint=fingerprint,
        receipt=receipt,
        providers=receipt_providers,
        generation=receipt_generation,
        analyzed_commit=analyzed_commit,
        provenance=provenance,
    )


def _parse_source_receipt(
    document: object, source_id: str, source_path: str, generation: int
) -> tuple[str, SourceFingerprint, Mapping[str, TopologyProviderReceipt], str | None, Mapping[str, object], int]:
    data = _object(document, f"source receipt {source_id}")
    _exact_keys(
        data,
        {"schema_version", "generation", "source_id", "source_path", "source_fingerprint", "analyzed_commit", "provenance", "providers"},
        f"source receipt {source_id}",
    )
    receipt_generation = _positive_int(data, "generation")
    if _schema_version(data, f"source receipt {source_id}") != 1 or receipt_generation > generation:
        raise TopologyRegistryError(f"source receipt generation disagrees with index for {source_id}")
    receipt_source = _source_id(data.get("source_id"))
    if receipt_source != source_id or _source_path(data.get("source_path"), "receipt source_path") != source_path:
        raise TopologyRegistryError(f"source receipt path or ID disagrees with index for {source_id}")
    fingerprint = _parse_fingerprint(data.get("source_fingerprint"), f"source receipt {source_id}")
    providers = _parse_providers(
        _object(data.get("providers"), f"receipt providers {source_id}"), source_id, detailed=True
    )
    analyzed_commit = data.get("analyzed_commit")
    if analyzed_commit is not None and not isinstance(analyzed_commit, str):
        raise TopologyRegistryError("analyzed_commit must be a string or null")
    _validate_commit(analyzed_commit, fingerprint)
    provenance = _parse_provenance(data.get("provenance"))
    return receipt_source, fingerprint, providers, analyzed_commit, provenance, receipt_generation


def _parse_providers(
    data: Mapping[str, object], source_id: str, *, detailed: bool
) -> Mapping[str, TopologyProviderReceipt]:
    providers: dict[str, TopologyProviderReceipt] = {}
    for provider_name in sorted(data):
        provider = _provider(provider_name)
        row = _object(data[provider_name], f"provider {source_id}/{provider}")
        base = {"status", "complete", "artifacts"}
        detailed_keys = base | {"artifact_schema_version", "tool_version", "capabilities", "counts", "diagnostics"}
        _exact_keys(row, detailed_keys if detailed else base, f"provider {source_id}/{provider}")
        artifacts_data = _object(row.get("artifacts"), f"provider artifacts {source_id}/{provider}")
        artifact_names = sorted(_artifact_name(name) for name in artifacts_data)
        artifacts = {
            name: _parse_artifact(artifacts_data[name], name, source_id)
            for name in artifact_names
        }
        if detailed:
            capabilities_data = row.get("capabilities")
            if not isinstance(capabilities_data, list):
                raise TopologyRegistryError("provider capabilities must be a list")
            diagnostics_data = row.get("diagnostics")
            if not isinstance(diagnostics_data, list):
                raise TopologyRegistryError("provider diagnostics must be a list")
            receipt = TopologyProviderReceipt(
                provider=provider,
                status=_status(row.get("status")),
                complete=_bool(row.get("complete"), "provider complete"),
                artifacts=artifacts,
                artifact_schema_version=_artifact_schema_version(row),
                tool_version=_string(row, "tool_version"),
                capabilities=tuple(capabilities_data),
                counts=_counts(_object(row.get("counts"), "provider counts")),
                diagnostics=tuple(diagnostics_data),
            )
        else:
            receipt = TopologyProviderReceipt(
                provider=provider,
                status=_status(row.get("status")),
                complete=_bool(row.get("complete"), "provider complete"),
                artifacts=artifacts,
            )
        providers[provider] = receipt
    if not providers:
        raise TopologyRegistryError(f"source {source_id} must contain at least one provider row")
    return MappingProxyType(dict(sorted(providers.items())))


def _assert_provider_catalog_equal(
    index: Mapping[str, TopologyProviderReceipt],
    receipt: Mapping[str, TopologyProviderReceipt],
    source_id: str,
) -> None:
    if set(index) != set(receipt):
        raise TopologyRegistryError(f"source receipt provider catalog disagrees with index for {source_id}")
    for provider in index:
        left, right = index[provider], receipt[provider]
        if left.status != right.status or left.complete != right.complete or left.artifacts != right.artifacts:
            raise TopologyRegistryError(f"source receipt artifact catalog disagrees with index for {source_id}/{provider}")


def _read_hashed_artifact(root: Path, source_id: str, artifact: TopologyArtifactReceipt) -> bytes:
    path = _artifact_path(root, source_id, artifact)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise TopologyRegistryError(f"cannot read topology artifact {artifact.path}: {exc}") from exc
    actual = "sha256:" + hashlib.sha256(raw).hexdigest()
    if actual != artifact.sha256:
        raise TopologyRegistryError(f"topology artifact hash drift: {artifact.path}")
    return raw


def _artifact_path(root: Path, source_id: str, artifact: TopologyArtifactReceipt) -> Path:
    prefix = f"re/topology/sources/{source_id}/"
    if not artifact.path.startswith(prefix):
        raise TopologyRegistryError(
            f"topology artifact is outside its exact source directory: {artifact.path}"
        )
    candidate = root / artifact.path
    try:
        canonical_sources = (root / "re/topology/sources").resolve(strict=True)
        canonical_sources.relative_to(root)
        source_base = root / f"re/topology/sources/{source_id}"
        resolved_source_base = source_base.resolve(strict=True)
        resolved_source_base.relative_to(canonical_sources)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_source_base)
    except (OSError, ValueError) as exc:
        raise TopologyRegistryError(f"topology artifact symlink escape or missing path: {artifact.path}") from exc
    return resolved


def _parse_artifact(value: object, name: str, source_id: str) -> TopologyArtifactReceipt:
    data = _object(value, f"artifact {name}")
    _exact_keys(data, {"path", "sha256"}, f"artifact {name}")
    artifact = TopologyArtifactReceipt(name, _string(data, "path"), _string(data, "sha256"))
    if not artifact.path.startswith(f"re/topology/sources/{source_id}/"):
        raise TopologyRegistryError(f"topology artifact is outside its exact source directory: {artifact.path}")
    return artifact


def _artifact_name(value: object) -> str:
    if not isinstance(value, str) or not _RUN_ID.fullmatch(value):
        raise TopologyRegistryError("topology artifact name must be a safe identifier")
    return value


def _configured_sources(root: Path, sources: Iterable[object]) -> dict[str, str]:
    configured: dict[str, str] = {}
    for source in sources:
        source_id = _source_id(getattr(source, "id", None))
        source_path = _source_path(getattr(source, "path", None), f"workspace source {source_id}")
        try:
            (root / source_path).resolve().relative_to(root)
        except ValueError as exc:
            raise TopologyRegistryError(
                f"configured source path escapes workspace: {source_id} -> {source_path}"
            ) from exc
        if source_id in configured:
            raise TopologyRegistryError(f"workspace has duplicate source ID: {source_id}")
        configured[source_id] = source_path
    return configured


def _select_sources(index: TopologyIndex, source_ids: Iterable[str]) -> tuple[TopologySourceRecord, ...]:
    requested = tuple(source_ids)
    if not requested:
        return tuple(index.sources.values())
    selected: list[TopologySourceRecord] = []
    seen: set[str] = set()
    for value in requested:
        source_id = _source_id(value)
        if source_id in seen:
            raise TopologyRegistryError(f"duplicate topology source selection: {source_id}")
        if source_id not in index.sources:
            raise TopologyRegistryError(f"unknown topology source: {source_id}")
        seen.add(source_id)
        selected.append(index.sources[source_id])
    return tuple(sorted(selected, key=lambda item: item.source_id))


def _parse_fingerprint(value: object, label: str) -> SourceFingerprint:
    data = _object(value, f"{label} source_fingerprint")
    _exact_keys(data, {"value", "kind", "dirty", "profile_hash", "git_head"}, f"{label} source_fingerprint")
    try:
        fingerprint = SourceFingerprint.from_json_dict(data)
    except ValueError as exc:
        raise TopologyRegistryError(f"invalid {label} source_fingerprint: {exc}") from exc
    _validate_fingerprint(fingerprint)
    return fingerprint


def _validate_fingerprint(fingerprint: SourceFingerprint) -> None:
    if not _HEX64.fullmatch(fingerprint.value) or not _HEX64.fullmatch(fingerprint.profile_hash):
        raise TopologyRegistryError("source fingerprint values must be lowercase SHA-256 hex")
    if fingerprint.kind == "git":
        if fingerprint.git_head is None or not _GIT_HEAD.fullmatch(fingerprint.git_head):
            raise TopologyRegistryError("git source fingerprint requires a lowercase 40-hex git_head")
    elif fingerprint.git_head is not None or fingerprint.dirty:
        raise TopologyRegistryError("file-tree source fingerprint must have git_head=null and dirty=false")


def _validate_commit(commit: str | None, fingerprint: SourceFingerprint) -> None:
    if fingerprint.kind == "git":
        if not isinstance(commit, str) or not _GIT_HEAD.fullmatch(commit):
            raise TopologyRegistryError("git source receipts require a lowercase 40-hex analyzed_commit")
        if commit != fingerprint.git_head:
            raise TopologyRegistryError("analyzed_commit must match the recorded git_head")
    elif commit is not None:
        raise TopologyRegistryError("file-tree source receipts must use analyzed_commit=null")


def _parse_provenance(value: object) -> Mapping[str, object]:
    data = _object(value, "source receipt provenance")
    kind = data.get("kind")
    expected = {
        "re": {"kind", "run_id"},
        "delivery": {"kind", "run_id"},
        "land-reconciliation": {"kind", "evidence_run"},
    }
    if kind not in expected or set(data) != expected[kind]:
        raise TopologyRegistryError("source receipt provenance has an invalid kind-specific schema")
    id_key = "evidence_run" if kind == "land-reconciliation" else "run_id"
    identifier = data.get(id_key)
    if not isinstance(identifier, str) or not _RUN_ID.fullmatch(identifier):
        raise TopologyRegistryError("source receipt provenance requires a safe run identifier")
    return _freeze_mapping(data)


def _validate_receipt_counts(
    receipt: TopologyProviderReceipt, symbols: object, relationships: object
) -> None:
    """Reconcile the provider-neutral receipt totals after native validation."""
    expected = {"symbols": len(symbols), "relationships": len(relationships)}
    for key, value in expected.items():
        if receipt.counts.get(key) != value:
            raise TopologyRegistryError(
                f"provider receipt count disagrees with analysis for {receipt.provider}: {key}"
            )


def _freeze_json(value: object) -> object:
    if isinstance(value, str):
        _reject_host_path(value)
        return value
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, dict):
        return _freeze_mapping(value)
    raise TopologyRegistryError("receipt metadata must be JSON data")


def _stable_value(value: object) -> str:
    """Sort immutable receipt metadata without relying on mapping insertion order."""
    return json.dumps(_thaw_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    frozen: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TopologyRegistryError("receipt object keys must be strings")
        _reject_host_path(key)
        frozen[key] = _freeze_json(item)
    return MappingProxyType(dict(sorted(frozen.items())))


def _reject_host_path(value: str) -> None:
    if value.startswith(("/", "\\\\")) or re.match(r"^[A-Za-z]:[\\/]", value):
        raise TopologyRegistryError("source receipt must not expose an absolute host path")


def _read_json(path: Path, label: str) -> object:
    try:
        return _read_json_bytes(path.read_bytes(), label)
    except OSError as exc:
        raise TopologyRegistryError(f"cannot read {label}: {exc}") from exc


def _read_json_bytes(raw: bytes, label: str) -> object:
    try:
        return json.loads(
            raw,
            object_pairs_hook=_no_duplicate_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TopologyRegistryError) as exc:
        raise TopologyRegistryError(f"malformed {label}: {exc}") from exc


def _no_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TopologyRegistryError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise TopologyRegistryError(f"non-standard JSON constant is not allowed: {value}")


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TopologyRegistryError(f"{label} must be an object")
    return value


def _exact_keys(data: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(data) != expected:
        raise TopologyRegistryError(f"{label} has unexpected or missing fields")


def _string(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise TopologyRegistryError(f"{key} must be a non-empty string")
    return value


def _positive_int(data: Mapping[str, object], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TopologyRegistryError(f"{key} must be a positive integer")
    return value


def _schema_version(data: Mapping[str, object], label: str) -> int:
    value = data.get("schema_version")
    if type(value) is not int or value != 1:
        raise TopologyRegistryError(f"unsupported {label} schema_version")
    return value


def _published_at(value: object) -> str:
    if not isinstance(value, str) or not _RFC3339.fullmatch(value):
        raise TopologyRegistryError("published_at must be a timezone-aware RFC 3339 timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise TopologyRegistryError("published_at must be a timezone-aware RFC 3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TopologyRegistryError("published_at must be a timezone-aware RFC 3339 timestamp")
    return value


def _artifact_schema_version(data: Mapping[str, object]) -> int:
    version = _positive_int(data, "artifact_schema_version")
    if version != 2:
        raise TopologyRegistryError("provider artifact_schema_version must be 2")
    return version


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TopologyRegistryError(f"{label} must be a boolean")
    return value


def _status(value: object) -> str:
    if not isinstance(value, str) or value not in NORMALIZED_STATUSES:
        raise TopologyRegistryError(f"unknown topology provider status: {value!r}")
    return value


def _counts(data: Mapping[str, object]) -> Mapping[str, int]:
    values: dict[str, int] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key or isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TopologyRegistryError("provider counts must map strings to non-negative integers")
        values[key] = value
    return MappingProxyType(dict(sorted(values.items())))


def _source_id(value: object) -> str:
    try:
        return validate_source_id(value)  # type: ignore[arg-type]
    except TopologyValidationError as exc:
        raise TopologyRegistryError(str(exc)) from exc


def _provider(value: object) -> str:
    try:
        return validate_provider(value)  # type: ignore[arg-type]
    except TopologyValidationError as exc:
        raise TopologyRegistryError(str(exc)) from exc


def _source_path(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TopologyRegistryError(f"{label} must be a source-relative path")
    try:
        return normalize_source_path(value)
    except TopologyValidationError as exc:
        raise TopologyRegistryError(str(exc)) from exc
