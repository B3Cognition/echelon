"""Atomic publication of explicit, curated source-topology snapshots."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Callable, Mapping

from echelon.topology_provider import TopologyProviderError, load_provider_document
from echelon.topology_registry import (
    TopologyArtifactReceipt,
    TopologyProviderReceipt,
    TopologyRegistryError,
    _read_json_bytes,
    load_topology_index,
)
from echelon.workspace_model import discover_workspace
from harness.publication_transaction import (
    PublicationOperation,
    PublicationTransaction,
    apply_publication_transaction,
    rollback_publication_transaction,
    write_publication_journal,
)
from harness.re_fingerprint import SourceFingerprint
from harness.re_lock import RePublishLock
from harness.re_registry import ensure_re_layout


class TopologyPublicationError(RuntimeError):
    """Base error for deterministic topology publication."""


class TopologyPublicationValidationError(TopologyPublicationError):
    """Raised before a topology publication can mutate the workspace."""


class TopologyPublicationConflict(TopologyPublicationError):
    """Raised when the pinned topology generation has changed."""


ArtifactInput = bytes | Path


@dataclass(frozen=True, slots=True)
class TopologyProviderCandidate:
    """Explicit curated provider inputs for one source snapshot."""

    provider: str
    analysis: ArtifactInput | None = None
    summary: ArtifactInput | None = None
    capabilities: tuple[str, ...] = ()
    unavailable_reason: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider:
            raise TopologyPublicationValidationError("provider candidate requires a provider name")
        if not isinstance(self.capabilities, tuple) or any(
            not isinstance(value, str) or not value for value in self.capabilities
        ):
            raise TopologyPublicationValidationError("provider capabilities must be a tuple of strings")
        object.__setattr__(self, "capabilities", tuple(sorted(set(self.capabilities))))
        unavailable = self.unavailable_reason is not None
        if unavailable and (self.analysis is not None or self.summary is not None or self.capabilities):
            raise TopologyPublicationValidationError("unavailable provider cannot carry artifacts or capabilities")
        if not unavailable and (self.analysis is None or self.summary is None):
            raise TopologyPublicationValidationError("provider candidate requires analysis and summary")
        if unavailable and not isinstance(self.unavailable_reason, Mapping):
            raise TopologyPublicationValidationError("unavailable provider requires structured reason")


@dataclass(frozen=True, slots=True)
class TopologySnapshotCandidate:
    """Explicit source topology evidence; never a run-directory discovery request."""

    source_id: str
    source_path: str
    source_fingerprint: SourceFingerprint
    analyzed_commit: str | None
    provenance: Mapping[str, object]
    providers: tuple[TopologyProviderCandidate, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id:
            raise TopologyPublicationValidationError("topology candidate requires a source ID")
        if not isinstance(self.source_path, str) or not self.source_path:
            raise TopologyPublicationValidationError("topology candidate requires a source path")
        if not isinstance(self.source_fingerprint, SourceFingerprint):
            raise TopologyPublicationValidationError("topology candidate requires a source fingerprint")
        if self.analyzed_commit is not None and not isinstance(self.analyzed_commit, str):
            raise TopologyPublicationValidationError("analyzed_commit must be a string or null")
        if not isinstance(self.provenance, Mapping):
            raise TopologyPublicationValidationError("topology provenance must be a mapping")
        if not isinstance(self.providers, tuple) or any(
            not isinstance(provider, TopologyProviderCandidate) for provider in self.providers
        ):
            raise TopologyPublicationValidationError("topology providers must be an immutable candidate tuple")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class TopologyPublicationResult:
    generation: int
    index_path: Path
    changed_sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TopologyStagingResult:
    """Topology operations staged for composition into an existing transaction."""

    generation: int
    operations: tuple[PublicationOperation, ...]


def stage_topology_snapshots(
    workspace_root: Path,
    stage_root: Path,
    candidates: tuple[TopologySnapshotCandidate, ...],
    *,
    removed_source_ids: tuple[str, ...] = (),
    required_source_ids: tuple[str, ...] = (),
    allow_unavailable_bootstrap: bool = False,
) -> TopologyStagingResult | None:
    """Stage canonical topology without taking a lock or writing a journal.

    ``publish_re_run`` uses this while holding the established RE publication
    claim. Keeping staging separate prevents a nested lock/transaction while
    retaining the registry validation and byte-preserving merge semantics.
    """
    root = Path(workspace_root).resolve()
    stage_root = Path(stage_root).resolve()
    prepared = (
        _validate_candidates(
            root,
            candidates,
            None,
            allow_all_unavailable=allow_unavailable_bootstrap,
        )
        if candidates
        else ()
    )
    configured = _configured_sources(root)
    removed = set(removed_source_ids)
    try:
        current = load_topology_index(root, allow_removed_source_ids=removed)
    except TopologyRegistryError as exc:
        raise TopologyPublicationValidationError(
            f"current topology publication is structurally invalid: {exc}"
        ) from exc
    if allow_unavailable_bootstrap:
        if current is not None:
            raise TopologyPublicationValidationError(
                "unavailable topology bootstrap requires an absent authority"
            )
        if not any(
            provider.status != "unavailable"
            for candidate in prepared
            for provider in candidate.providers
        ):
            raise TopologyPublicationValidationError(
                "unavailable topology bootstrap requires selected source evidence"
            )
    selected = {item.candidate.source_id for item in prepared}
    required = set(required_source_ids)
    if not required <= set(configured):
        raise TopologyPublicationValidationError(
            "required topology source is not configured in workspace"
        )
    if current is not None and not selected <= set(configured):
        raise TopologyPublicationValidationError("candidate source is not configured in workspace")
    if current is not None and not required <= selected:
        missing = ", ".join(sorted(required - selected))
        raise TopologyPublicationValidationError(
            f"refreshed source has no usable topology evidence: {missing}"
        )
    if current is None and required and not required <= selected:
        missing = ", ".join(sorted(required - selected))
        raise TopologyPublicationValidationError(
            f"refreshed source has no usable topology evidence: {missing}"
        )
    if current is None and selected and selected != set(configured):
        raise TopologyPublicationValidationError(
            "first topology publication must cover every configured workspace source"
        )
    if current is None and not prepared:
        return None
    if not prepared and not removed:
        return None
    generation = (current.generation if current else 0) + 1
    operations = _stage_snapshot_tree(
        root,
        stage_root,
        prepared,
        configured,
        current,
        generation,
        removed,
    )
    return TopologyStagingResult(generation, operations)


def publish_topology_snapshots(
    workspace_root: Path,
    candidates: tuple[TopologySnapshotCandidate, ...],
    *,
    owner_id: str,
    owner_run_dir: Path | None,
    expected_generation: int | None = None,
    fault_hook: Callable[[str], None] | None = None,
) -> TopologyPublicationResult:
    """Publish selected source snapshots as one rollback-capable generation."""
    root = Path(workspace_root).resolve()
    owner_root = _validate_owner_run_dir(root, owner_run_dir, candidates)
    prepared = _validate_candidates(root, candidates, owner_root)
    paths = ensure_re_layout(root)
    with RePublishLock.acquire(root, owner_id, owner_run_dir):
        try:
            current = load_topology_index(root)
        except TopologyRegistryError as exc:
            raise TopologyPublicationValidationError(
                f"current topology publication is structurally invalid: {exc}"
            ) from exc
        current_generation = current.generation if current else 0
        if expected_generation is not None and expected_generation != current_generation:
            raise TopologyPublicationConflict(
                f"expected generation {expected_generation}, found {current_generation}"
            )
        configured = _configured_sources(root)
        selected = {prepared_candidate.candidate.source_id for prepared_candidate in prepared}
        if current is None and selected != set(configured):
            raise TopologyPublicationValidationError(
                "first topology publication must cover every configured workspace source"
            )
        if current is not None and not selected <= set(configured):
            raise TopologyPublicationValidationError("candidate source is not configured in workspace")
        generation = current_generation + 1
        transaction = _prepare_transaction(root, paths.staging / owner_id, prepared, configured, current, generation)
        try:
            apply_publication_transaction(transaction, fault_hook=fault_hook)
            loaded = load_topology_index(root)
            if loaded is None or loaded.generation != generation:
                raise TopologyPublicationError("installed topology generation failed post-write validation")
        except Exception:
            rollback_publication_transaction(transaction)
            if transaction.staging_root.exists():
                shutil.rmtree(transaction.staging_root)
            raise
        else:
            shutil.rmtree(transaction.staging_root)
    return TopologyPublicationResult(generation, root / "re/topology/index.json", tuple(sorted(selected)))


@dataclass(frozen=True, slots=True)
class _PreparedProvider:
    provider: str
    analysis: bytes | None
    summary: bytes | None
    status: str
    complete: bool
    tool_version: str | None
    capabilities: tuple[str, ...]
    counts: Mapping[str, int]
    diagnostics: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class _PreparedCandidate:
    candidate: TopologySnapshotCandidate
    providers: tuple[_PreparedProvider, ...]


def validate_provider_summary(
    provider: str,
    source_id: str,
    *,
    document: Mapping[str, object],
    loaded: object,
    summary: object,
) -> None:
    """Validate the exact compact provider summary at the publication boundary."""
    if not isinstance(summary, Mapping):
        raise TopologyPublicationValidationError(
            f"provider summary must be a JSON object for {source_id}/{provider}"
        )
    base_fields = frozenset(
        {
            "schema_version",
            "tool",
            "tool_version",
            "provider_status",
            "complete",
            "counts",
            "diagnostics",
        }
    )
    provider_fields = {
        "codegraph": base_fields,
        "perlgraph": base_fields | frozenset({"repo_path", "capabilities"}),
    }
    expected_fields = provider_fields.get(provider)
    if expected_fields is None:
        raise TopologyPublicationValidationError(f"unsupported topology provider summary: {provider}")
    if set(summary) != expected_fields:
        raise TopologyPublicationValidationError(
            f"provider summary fields are invalid for {source_id}/{provider}"
        )
    for field in (
        "schema_version",
        "tool",
        "tool_version",
        "provider_status",
        "complete",
        "counts",
    ):
        if summary[field] != document.get(field):
            raise TopologyPublicationValidationError(
                f"provider summary {field} disagrees with analysis for {source_id}/{provider}"
            )
    if summary["diagnostics"] != _summary_diagnostics(provider, document):
        raise TopologyPublicationValidationError(
            f"provider summary diagnostics disagree with analysis for {source_id}/{provider}"
        )
    for field in ("repo_path", "capabilities"):
        if field in expected_fields and summary[field] != document.get(field):
            raise TopologyPublicationValidationError(
                f"provider summary {field} disagrees with analysis for {source_id}/{provider}"
            )
    if getattr(loaded, "provider", None) != provider or getattr(loaded, "source_id", None) != source_id:
        raise TopologyPublicationValidationError(
            "provider summary does not match the declared source/provider"
        )


def _summary_diagnostics(provider: str, document: Mapping[str, object]) -> object:
    if provider == "codegraph":
        return document.get("diagnostics")
    return {
        "unresolved_relationships": document.get("unresolved_relationships"),
        "parse_failures": document.get("parse_failures"),
        "parse_diagnostics": document.get("parse_diagnostics"),
        "unsupported_patterns": document.get("unsupported_patterns"),
    }


def _validate_candidates(
    root: Path,
    candidates: tuple[TopologySnapshotCandidate, ...],
    owner_root: Path | None,
    *,
    allow_all_unavailable: bool = False,
) -> tuple[_PreparedCandidate, ...]:
    configured = _configured_sources(root)
    if not candidates:
        raise TopologyPublicationValidationError("topology publication requires at least one source candidate")
    prepared: list[_PreparedCandidate] = []
    seen_sources: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, TopologySnapshotCandidate):
            raise TopologyPublicationValidationError("topology candidate has an invalid type")
        if candidate.source_id in seen_sources:
            raise TopologyPublicationValidationError(f"duplicate selected source ID: {candidate.source_id}")
        seen_sources.add(candidate.source_id)
        if configured.get(candidate.source_id) != candidate.source_path:
            raise TopologyPublicationValidationError(
                f"candidate source path does not match workspace manifest: {candidate.source_id}"
            )
        _validate_fingerprint_and_commit(candidate)
        _validate_provenance(candidate.provenance)
        if not candidate.providers:
            raise TopologyPublicationValidationError(f"source has no usable providers: {candidate.source_id}")
        providers: list[_PreparedProvider] = []
        seen_providers: set[str] = set()
        for provider in candidate.providers:
            if provider.provider in seen_providers:
                raise TopologyPublicationValidationError(
                    f"duplicate provider for source {candidate.source_id}: {provider.provider}"
                )
            seen_providers.add(provider.provider)
            if provider.unavailable_reason is not None:
                reason = dict(provider.unavailable_reason)
                if not reason or not isinstance(reason.get("kind"), str) or not isinstance(reason.get("message"), str):
                    raise TopologyPublicationValidationError("unavailable provider reason is malformed")
                providers.append(
                    _PreparedProvider(
                        provider=provider.provider,
                        analysis=None,
                        summary=None,
                        status="unavailable",
                        complete=False,
                        tool_version=None,
                        capabilities=(),
                        counts={},
                        diagnostics=(reason,),
                    )
                )
                continue
            analysis = _artifact_bytes(provider.analysis, "analysis", owner_root)
            summary = _artifact_bytes(provider.summary, "summary", owner_root)
            if not summary.strip():
                raise TopologyPublicationValidationError("provider summary must not be empty")
            try:
                summary_document = _read_json_bytes(summary, f"candidate {provider.provider} summary")
                if not isinstance(summary_document, dict):
                    raise TopologyRegistryError("provider summary must be a JSON object")
                document = _read_json_bytes(analysis, f"candidate {provider.provider} analysis")
                loaded = load_provider_document(document, provider=provider.provider, source_id=candidate.source_id)
                validate_provider_summary(
                    provider.provider,
                    candidate.source_id,
                    document=document,
                    loaded=loaded,
                    summary=summary_document,
                )
            except (TopologyRegistryError, TopologyProviderError) as exc:
                raise TopologyPublicationValidationError(
                    f"invalid provider analysis for {candidate.source_id}/{provider.provider}: {exc}"
                ) from exc
            raw_capabilities = document.get("capabilities", ()) if isinstance(document, dict) else ()
            capabilities = provider.capabilities or _capabilities(raw_capabilities)
            if not capabilities:
                capabilities = ("relationships", "symbols")
            diagnostics = _diagnostics(document, provider.provider)
            native_counts = document.get("counts")
            if not isinstance(native_counts, dict) or any(
                not isinstance(name, str)
                or isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for name, value in native_counts.items()
            ):
                raise TopologyPublicationValidationError(
                    f"provider counts are malformed for {candidate.source_id}/{provider.provider}"
                )
            prepared_provider = _PreparedProvider(
                    provider=loaded.provider,
                    analysis=analysis,
                    summary=summary,
                    status=loaded.status,
                    complete=loaded.complete,
                    tool_version=loaded.tool_version,
                    capabilities=capabilities,
                    counts={
                        **native_counts,
                        "symbols": len(loaded.symbols),
                        "relationships": len(loaded.relationships),
                    },
                    diagnostics=diagnostics,
                )
            _validate_provider_receipt_candidate(candidate.source_id, prepared_provider)
            providers.append(prepared_provider)
        if (
            not allow_all_unavailable
            and not any(provider.status != "unavailable" for provider in providers)
        ):
            raise TopologyPublicationValidationError(
                f"source has no usable providers: {candidate.source_id}"
            )
        prepared.append(_PreparedCandidate(candidate, tuple(sorted(providers, key=lambda item: item.provider))))
    return tuple(sorted(prepared, key=lambda item: item.candidate.source_id))


def _prepare_transaction(root: Path, stage_root: Path, candidates: tuple[_PreparedCandidate, ...], configured: Mapping[str, str], current: object, generation: int) -> PublicationTransaction:
    journal = stage_root / "rollback-journal.json"
    if journal.is_file():
        try:
            prior = _read_json_bytes(journal.read_bytes(), "topology rollback journal")
        except (OSError, TopologyRegistryError) as exc:
            raise TopologyPublicationValidationError(
                f"cannot inspect existing topology transaction: {exc}"
            ) from exc
        if isinstance(prior, dict) and prior.get("status") in {"replacing", "rolling_back"}:
            raise TopologyPublicationError(
                f"unfinished topology publication transaction exists: {journal}"
            )
    if stage_root.exists():
        shutil.rmtree(stage_root)
    (stage_root / "rollback").mkdir(parents=True)
    operations = _stage_snapshot_tree(
        root,
        stage_root,
        candidates,
        configured,
        current,
        generation,
        set(),
    )
    transaction = PublicationTransaction(
        workspace_root=root / "re", staging_root=stage_root, journal=stage_root / "rollback-journal.json", operations=operations, expected_generation=generation
    )
    write_publication_journal(transaction, "prepared")
    return transaction


def _stage_snapshot_tree(
    root: Path,
    stage_root: Path,
    candidates: tuple[_PreparedCandidate, ...],
    configured: Mapping[str, str],
    current: object,
    generation: int,
    removed_source_ids: set[str],
) -> tuple[PublicationOperation, ...]:
    new_root = stage_root / "new/re/topology"
    new_root.mkdir(parents=True, exist_ok=True)
    current_rows = _current_rows(root, current)
    rows = dict(current_rows)
    operations: list[PublicationOperation] = []
    for source_id in sorted(removed_source_ids):
        rows.pop(source_id, None)
        operations.append(PublicationOperation(PurePosixPath(f"topology/sources/{source_id}"), None))
    for prepared in candidates:
        source = prepared.candidate
        source_root = new_root / "sources" / source.source_id
        source_root.mkdir(parents=True)
        provider_rows: dict[str, object] = {}
        receipt_providers: dict[str, object] = {}
        for provider in prepared.providers:
            if provider.status == "unavailable":
                base = {
                    "status": "unavailable",
                    "complete": False,
                    "artifacts": {},
                }
                provider_rows[provider.provider] = base
                receipt_providers[provider.provider] = {
                    **base,
                    "diagnostics": list(provider.diagnostics),
                }
                continue
            analysis_name = f"{provider.provider}-analysis.json"
            summary_name = f"{provider.provider}-summary.json"
            analysis_path = source_root / analysis_name
            summary_path = source_root / summary_name
            analysis_path.write_bytes(provider.analysis)
            summary_path.write_bytes(provider.summary)
            artifacts = {
                "analysis": _artifact(f"re/topology/sources/{source.source_id}/{analysis_name}", provider.analysis),
                "summary": _artifact(f"re/topology/sources/{source.source_id}/{summary_name}", provider.summary),
            }
            base = {"status": provider.status, "complete": provider.complete, "artifacts": artifacts}
            provider_rows[provider.provider] = base
            receipt_providers[provider.provider] = {
                **base,
                "artifact_schema_version": 2,
                "tool_version": provider.tool_version,
                "capabilities": list(provider.capabilities),
                "counts": dict(provider.counts),
                "diagnostics": list(provider.diagnostics),
            }
        receipt = {
            "schema_version": 1,
            "generation": generation,
            "source_id": source.source_id,
            "source_path": source.source_path,
            "source_fingerprint": source.source_fingerprint.to_json_dict(),
            "analyzed_commit": source.analyzed_commit,
            "provenance": dict(source.provenance),
            "providers": receipt_providers,
        }
        receipt_bytes = _json_bytes(receipt)
        (source_root / "receipt.json").write_bytes(receipt_bytes)
        rows[source.source_id] = {
            "source_path": source.source_path,
            "source_fingerprint": source.source_fingerprint.to_json_dict(),
            "receipt": _artifact(f"re/topology/sources/{source.source_id}/receipt.json", receipt_bytes),
            "providers": provider_rows,
        }
        operations.append(PublicationOperation(PurePosixPath(f"topology/sources/{source.source_id}"), PurePosixPath(f"new/re/topology/sources/{source.source_id}")))
    if set(rows) != set(configured):
        raise TopologyPublicationValidationError("topology rows do not cover every configured workspace source")
    index = {"schema_version": 1, "generation": generation, "published_at": datetime.now(timezone.utc).isoformat(), "sources": {source_id: rows[source_id] for source_id in sorted(rows)}}
    index_bytes = _json_bytes(index)
    (new_root / "index.json").write_bytes(index_bytes)
    operations.append(PublicationOperation(PurePosixPath("topology/index.json"), PurePosixPath("new/re/topology/index.json")))
    _validate_staged_tree(root, stage_root, configured, current, rows)
    return tuple(operations)


def _validate_staged_tree(root: Path, stage_root: Path, configured: Mapping[str, str], current: object, rows: Mapping[str, object]) -> None:
    validation = stage_root / "validation"
    (validation / ".echelon").mkdir(parents=True)
    shutil.copy2(root / ".echelon/config.yml", validation / ".echelon/config.yml")
    for source_path in configured.values():
        (validation / source_path).mkdir(parents=True, exist_ok=True)
    staged = stage_root / "new"
    for source_id, row in rows.items():
        if not isinstance(row, dict):
            raise TopologyPublicationValidationError("staged topology source row is malformed")
        for artifact_path in _row_artifact_paths(row):
            source = staged / artifact_path if (staged / artifact_path).is_file() else root / artifact_path
            destination = validation / artifact_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    shutil.copy2(stage_root / "new/re/topology/index.json", validation / "re/topology/index.json")
    try:
        index = load_topology_index(validation)
        if index is None:
            raise TopologyRegistryError("topology index is missing")
    except TopologyRegistryError as exc:
        raise TopologyPublicationValidationError(f"staged topology publication is invalid: {exc}") from exc


def _row_artifact_paths(row: Mapping[str, object]) -> tuple[str, ...]:
    paths: list[str] = []
    receipt = row.get("receipt")
    if not isinstance(receipt, dict) or not isinstance(receipt.get("path"), str):
        raise TopologyPublicationValidationError("staged topology receipt artifact is malformed")
    paths.append(receipt["path"])
    providers = row.get("providers")
    if not isinstance(providers, dict):
        raise TopologyPublicationValidationError("staged topology provider catalog is malformed")
    for provider in providers.values():
        if not isinstance(provider, dict) or not isinstance(provider.get("artifacts"), dict):
            raise TopologyPublicationValidationError("staged topology provider artifacts are malformed")
        for artifact in provider["artifacts"].values():
            if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
                raise TopologyPublicationValidationError("staged topology artifact path is malformed")
            paths.append(artifact["path"])
    return tuple(sorted(set(paths)))


def _current_rows(root: Path, current: object) -> dict[str, object]:
    if current is None:
        return {}
    try:
        raw = _read_json_bytes((root / "re/topology/index.json").read_bytes(), "topology index")
    except (OSError, TopologyRegistryError) as exc:
        raise TopologyPublicationValidationError(f"cannot preserve current topology rows: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), dict):
        raise TopologyPublicationValidationError("current topology index is malformed")
    return dict(raw["sources"])


def _configured_sources(root: Path) -> dict[str, str]:
    return {source.id: source.path for source in discover_workspace(root).sources}


def _validate_owner_run_dir(
    root: Path, owner_run_dir: Path | None, candidates: tuple[TopologySnapshotCandidate, ...]
) -> Path | None:
    needs_owner = any(
        isinstance(value, Path)
        for candidate in candidates
        for provider in candidate.providers
        for value in (provider.analysis, provider.summary)
    )
    if not needs_owner:
        return None
    if owner_run_dir is None:
        raise TopologyPublicationValidationError(
            "path-backed topology evidence requires an owner run directory"
        )
    try:
        owner = owner_run_dir.resolve(strict=True)
        if not owner.is_dir():
            raise TopologyPublicationValidationError("owner run directory must be a directory")
        lifecycle_roots: list[Path] = []
        for name in ("runs", "squad"):
            candidate = root / name
            if not candidate.exists():
                continue
            if candidate.is_symlink() or not candidate.is_dir():
                raise TopologyPublicationValidationError(
                    f"workspace lifecycle root is unsafe: {candidate}"
                )
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
            lifecycle_roots.append(resolved)
        if not any(owner.is_relative_to(candidate) for candidate in lifecycle_roots):
            raise TopologyPublicationValidationError("owner run directory is outside workspace lifecycle roots")
        return owner
    except (OSError, ValueError) as exc:
        raise TopologyPublicationValidationError(f"owner run directory is invalid: {exc}") from exc


def _validate_fingerprint_and_commit(candidate: TopologySnapshotCandidate) -> None:
    try:
        # Registry validation is authoritative and catches kind-specific invariants.
        from echelon.topology_registry import _validate_commit, _validate_fingerprint
        _validate_fingerprint(candidate.source_fingerprint)
        _validate_commit(candidate.analyzed_commit, candidate.source_fingerprint)
    except (TopologyRegistryError, AttributeError) as exc:
        raise TopologyPublicationValidationError(f"invalid source fingerprint: {exc}") from exc


def _validate_provenance(provenance: Mapping[str, object]) -> None:
    try:
        from echelon.topology_registry import _parse_provenance
        _parse_provenance(dict(provenance))
    except (TopologyRegistryError, TypeError) as exc:
        raise TopologyPublicationValidationError(f"invalid topology provenance: {exc}") from exc


def _artifact_bytes(value: ArtifactInput, label: str, owner_root: Path | None) -> bytes:
    if isinstance(value, bytes):
        return value
    if not isinstance(value, Path) or owner_root is None:
        raise TopologyPublicationValidationError(f"{label} artifact must be safe bytes or a regular file")
    try:
        resolved = value.resolve(strict=True)
        resolved.relative_to(owner_root)
        if not resolved.is_file():
            raise TopologyPublicationValidationError(f"{label} artifact must be a regular file")
        return resolved.read_bytes()
    except OSError as exc:
        raise TopologyPublicationValidationError(f"cannot read {label} artifact: {exc}") from exc
    except ValueError as exc:
        raise TopologyPublicationValidationError(f"{label} artifact escapes owner run directory") from exc


def _capabilities(raw: object) -> tuple[str, ...]:
    if isinstance(raw, dict):
        return tuple(sorted(key for key, value in raw.items() if value is True and isinstance(key, str)))
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return tuple(sorted(set(raw)))
    return ()


def _diagnostics(document: object, provider: str) -> tuple[object, ...]:
    if not isinstance(document, dict):
        return ()
    value = document.get("diagnostics") if provider == "codegraph" else document.get("unresolved_relationships", ())
    if isinstance(value, dict):
        value = value.get("unresolved_relationships", ())
    return tuple(value) if isinstance(value, list) else ()


def _artifact(path: str, raw: bytes) -> dict[str, str]:
    return {"path": path, "sha256": "sha256:" + hashlib.sha256(raw).hexdigest()}


def _validate_provider_receipt_candidate(
    source_id: str, provider: _PreparedProvider
) -> None:
    """Apply the strict receipt metadata contract before the publication lock."""
    try:
        if provider.status == "unavailable":
            TopologyProviderReceipt(
                provider=provider.provider,
                status="unavailable",
                complete=False,
                artifacts={},
                diagnostics=provider.diagnostics,
            )
            return
        artifacts = {
            "analysis": TopologyArtifactReceipt(
                "analysis",
                f"re/topology/sources/{source_id}/{provider.provider}-analysis.json",
                _artifact("ignored", provider.analysis)["sha256"],
            ),
            "summary": TopologyArtifactReceipt(
                "summary",
                f"re/topology/sources/{source_id}/{provider.provider}-summary.json",
                _artifact("ignored", provider.summary)["sha256"],
            ),
        }
        TopologyProviderReceipt(
            provider=provider.provider,
            status=provider.status,
            complete=provider.complete,
            artifacts=artifacts,
            artifact_schema_version=2,
            tool_version=provider.tool_version,
            capabilities=provider.capabilities,
            counts=provider.counts,
            diagnostics=provider.diagnostics,
        )
    except TopologyRegistryError as exc:
        raise TopologyPublicationValidationError(
            f"invalid provider receipt for {source_id}/{provider.provider}: {exc}"
        ) from exc


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
