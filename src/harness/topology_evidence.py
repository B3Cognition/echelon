"""Build explicit, validated topology publication candidates from provider output."""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from echelon.topology_provider import (
    TopologyProviderError,
    load_provider_document,
)
from echelon.topology_model import canonical_symbol_key
from harness.durable_json import DurableJsonError, write_json_atomic
from harness.re_fingerprint import SourceFingerprint
from harness.re_fingerprint import fingerprint_source, resolve_re_fingerprint_profile
from echelon.workspace_model import discover_workspace
from kernel.spec_identity import spec_identity_aliases
from harness.topology_publication import (
    TopologyProviderCandidate,
    TopologyPublicationValidationError,
    TopologySnapshotCandidate,
    validate_provider_summary,
)


_KNOWN_PROVIDERS = frozenset({"codegraph", "perlgraph"})


class TopologyEvidenceError(RuntimeError):
    """Raised when explicit provider evidence cannot truthfully form a snapshot."""


@dataclass(frozen=True, slots=True)
class ProviderArtifactPaths:
    """The only provider files eligible for one source snapshot."""

    owner_dir: Path
    analysis: Path
    summary: Path
    error: Path | None = None


@dataclass(frozen=True, slots=True)
class ProviderArtifactBytes:
    """Provider bytes authenticated by the caller before validation."""

    analysis: bytes | None = None
    summary: bytes | None = None
    unavailable_reason: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class TopologyEvidence:
    """A publishable snapshot plus explicitly unavailable provider observations."""

    candidate: TopologySnapshotCandidate
    unavailable_providers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TopologyEvidenceReceiptResult:
    receipt_path: Path
    status: str
    source_id: str


def write_topology_evidence_receipt(
    project_root: Path,
    verify_run_dir: Path,
    spec_dir: Path,
    *,
    workspace_root: Path,
    source_id: str,
    source_root: Path,
    provenance: Mapping[str, object] | None = None,
) -> TopologyEvidenceReceiptResult:
    """Finalize deterministic delivery topology metadata after both providers."""
    workspace = Path(workspace_root).resolve(strict=True)
    project = Path(project_root).resolve(strict=True)
    source = Path(source_root).resolve(strict=True)
    run_dir = Path(verify_run_dir).resolve(strict=True)
    spec = Path(spec_dir).resolve(strict=True)
    if project != source:
        raise TopologyEvidenceError("delivery project root does not match ECHELON_SOURCE_ROOT")
    try:
        run_dir.relative_to((workspace / "runs").resolve(strict=True))
        spec.relative_to(workspace)
    except (OSError, ValueError) as exc:
        raise TopologyEvidenceError("delivery topology receipt paths escape the workspace") from exc
    manifest_matches = [
        item
        for item in discover_workspace(workspace).sources
        if item.id == source_id
        and (workspace if item.path == "." else workspace / item.path).resolve() == source
    ]
    if len(manifest_matches) != 1:
        raise TopologyEvidenceError(
            f"delivery source does not map exactly to workspace source {source_id!r}"
        )
    source_path = manifest_matches[0].path
    state_path = run_dir / "state.json"
    if state_path.is_symlink():
        raise TopologyEvidenceError("verify-spec state destination is symlinked")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TopologyEvidenceError("verify-spec state is unavailable or malformed") from exc
    if not isinstance(state, dict):
        raise TopologyEvidenceError("verify-spec state must be a JSON object")
    state_spec_id = state.get("spec_id")
    if not isinstance(state_spec_id, str) or not (
        set(spec_identity_aliases(state_spec_id)) & set(spec_identity_aliases(spec.name))
    ):
        raise TopologyEvidenceError("verify-spec state/spec identity mismatch")
    verify_scope = state.get("verify_scope")
    if verify_scope not in {"full", "scoped"}:
        raise TopologyEvidenceError("verify-spec state has no valid verify scope")

    fingerprint = fingerprint_source(
        source,
        resolve_re_fingerprint_profile(workspace),
    )
    providers = {
        provider: _delivery_provider_receipt(run_dir, provider, source_id)
        for provider in sorted(_KNOWN_PROVIDERS)
    }
    usable = [row for row in providers.values() if row["status"] != "unavailable"]
    if not usable:
        status = "unavailable"
    elif len(usable) != len(providers) or any(
        row["status"] == "degraded" or row["complete"] is not True
        for row in usable
    ):
        status = "degraded"
    else:
        status = "ready"
    receipt_provenance = dict(provenance) if provenance is not None else {
        "kind": "delivery",
        "run_dir": run_dir.relative_to(workspace).as_posix(),
    }
    receipt = {
        "schema_version": 1,
        "source_id": source_id,
        "source_path": source_path,
        "source_fingerprint": fingerprint.to_json_dict(),
        "analyzed_commit": fingerprint.git_head,
        "spec_id": spec.name,
        "verify_scope": verify_scope,
        "provenance": receipt_provenance,
        "providers": providers,
    }
    receipt_path = run_dir / "topology-receipt.json"
    try:
        write_json_atomic(receipt_path, receipt)
    except DurableJsonError as exc:
        raise TopologyEvidenceError(str(exc)) from exc
    state.update(
        {
            "topology_evidence": status,
            "topology_receipt_path": str(receipt_path),
        }
    )
    try:
        write_json_atomic(state_path, state)
    except DurableJsonError as exc:
        raise TopologyEvidenceError(str(exc)) from exc
    return TopologyEvidenceReceiptResult(receipt_path, status, source_id)


def _delivery_provider_receipt(
    run_dir: Path,
    provider: str,
    source_id: str,
) -> dict[str, object]:
    analysis_path = run_dir / f"{provider}-analysis.json"
    summary_path = run_dir / f"{provider}-summary.json"
    error_path = run_dir / f"{provider}-error.txt"
    if error_path.exists() or error_path.is_symlink():
        try:
            contained_error = _contained_provider_file(run_dir, error_path)
        except (OSError, ValueError):
            return _unavailable_delivery_provider(
                "invalid",
                "provider error artifact is not owned by the verify run",
            )
        return _unavailable_delivery_provider(
            "provider-error",
            _bounded_error_message(contained_error),
        )
    try:
        analysis_path = _contained_provider_file(run_dir, analysis_path)
        summary_path = _contained_provider_file(run_dir, summary_path)
    except FileNotFoundError:
        return _unavailable_delivery_provider(
            "missing",
            "provider analysis or summary is missing",
        )
    except (OSError, ValueError):
        return _unavailable_delivery_provider(
            "invalid",
            "provider artifacts are not owned by the verify run",
        )
    try:
        analysis = analysis_path.read_bytes()
        summary = summary_path.read_bytes()
        document = json.loads(analysis)
        summary_document = json.loads(summary)
        if not isinstance(document, dict):
            raise TopologyEvidenceError("provider analysis must be a JSON object")
        loaded = load_provider_document(document, provider=provider, source_id=source_id)
        validate_provider_summary(
            provider,
            source_id,
            document=document,
            loaded=loaded,
            summary=summary_document,
        )
        status = document.get("provider_status")
        complete = document.get("complete")
        tool_version = document.get("tool_version")
        counts = document.get("counts")
        if not isinstance(status, str) or not isinstance(complete, bool):
            raise TopologyEvidenceError("provider status/completeness is malformed")
        if not isinstance(tool_version, str) or not isinstance(counts, dict):
            raise TopologyEvidenceError("provider version/counts are malformed")
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TopologyProviderError,
        TopologyPublicationValidationError,
        TopologyEvidenceError,
    ) as exc:
        return _unavailable_delivery_provider("invalid", str(exc))
    diagnostics = (
        document.get("diagnostics")
        if provider == "codegraph"
        else {
            "unresolved_relationships": document.get("unresolved_relationships"),
            "parse_failures": document.get("parse_failures"),
            "parse_diagnostics": document.get("parse_diagnostics"),
            "unsupported_patterns": document.get("unsupported_patterns"),
        }
    )
    return {
        "status": status,
        "complete": complete,
        "artifact_schema_version": document.get("schema_version"),
        "tool_version": tool_version,
        "capabilities": list(_capabilities(analysis, provider)),
        "counts": counts,
        "diagnostics": diagnostics,
        "artifacts": {
            "analysis": _run_artifact_receipt(analysis_path, analysis),
            "summary": _run_artifact_receipt(summary_path, summary),
        },
    }


def _unavailable_delivery_provider(kind: str, message: str) -> dict[str, object]:
    return {
        "status": "unavailable",
        "complete": False,
        "diagnostics": [{"kind": kind, "message": message[:1000]}],
        "artifacts": {},
    }


def _bounded_error_message(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "provider failed"
    return next((line.strip() for line in text.splitlines() if line.strip()), "provider failed")


def _run_artifact_receipt(path: Path, content: bytes) -> dict[str, str]:
    return {
        "path": path.name,
        "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
    }


def build_topology_snapshot_candidate(
    source_id: str,
    source_path: str,
    fingerprint: SourceFingerprint,
    provider_artifacts: Mapping[str, ProviderArtifactPaths],
    provenance: Mapping[str, object],
) -> TopologyEvidence:
    """Validate explicit schema-2 inputs and capture their exact bytes.

    The caller declares every accepted path. Missing or unreadable provider files are
    recorded as unavailable; malformed provider output remains a hard error because
    treating it as an empty graph would be an untruthful topology claim.
    """
    if not isinstance(provider_artifacts, Mapping):
        raise TopologyEvidenceError("provider artifacts must be a mapping")
    providers: list[TopologyProviderCandidate] = []
    unavailable: list[str] = []
    for provider, paths in sorted(provider_artifacts.items()):
        if provider not in _KNOWN_PROVIDERS:
            raise TopologyEvidenceError(f"unsupported topology provider: {provider!r}")
        if not isinstance(paths, ProviderArtifactPaths):
            raise TopologyEvidenceError(f"provider artifacts are malformed: {provider}")
        if paths.error is not None:
            try:
                error_path = _contained_provider_file(paths.owner_dir, paths.error)
                reason = _provider_error_reason(error_path)
            except FileNotFoundError:
                reason = None
            except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TopologyEvidenceError(
                    f"invalid provider error evidence for {source_id}/{provider}: {exc}"
                ) from exc
            if reason is not None:
                unavailable.append(provider)
                providers.append(
                    TopologyProviderCandidate(provider=provider, unavailable_reason=reason)
                )
                continue
        try:
            analysis_path = _contained_provider_file(paths.owner_dir, paths.analysis)
            summary_path = _contained_provider_file(paths.owner_dir, paths.summary)
        except FileNotFoundError:
            unavailable.append(provider)
            providers.append(
                TopologyProviderCandidate(
                    provider=provider,
                    unavailable_reason={"kind": "missing", "message": "provider analysis or summary is missing"},
                )
            )
            continue
        except OSError as exc:
            raise TopologyEvidenceError(
                f"cannot read provider evidence for {source_id}/{provider}: {exc}"
            ) from exc
        except ValueError as exc:
            raise TopologyEvidenceError(
                f"provider evidence escapes declared source output for {source_id}/{provider}"
            ) from exc

        try:
            analysis = analysis_path.read_bytes()
            summary = summary_path.read_bytes()
            provider_candidate = _validated_provider_candidate(
                provider,
                source_id,
                analysis,
                summary,
            )
        except TopologyProviderError as exc:
            raise TopologyEvidenceError(
                f"invalid provider analysis for {source_id}/{provider}: {exc}"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TopologyEvidenceError(
                f"invalid provider summary for {source_id}/{provider}: {exc}"
            ) from exc
        except TopologyPublicationValidationError as exc:
            raise TopologyEvidenceError(
                f"invalid provider summary for {source_id}/{provider}: {exc}"
            ) from exc

        providers.append(provider_candidate)

    return _topology_evidence(
        source_id,
        source_path,
        fingerprint,
        provenance,
        providers,
        unavailable,
    )


def build_topology_snapshot_candidate_from_bytes(
    source_id: str,
    source_path: str,
    fingerprint: SourceFingerprint,
    provider_artifacts: Mapping[str, ProviderArtifactBytes],
    provenance: Mapping[str, object],
) -> TopologyEvidence:
    """Validate caller-authenticated bytes without reopening provider files."""
    if not isinstance(provider_artifacts, Mapping):
        raise TopologyEvidenceError("provider artifacts must be a mapping")
    providers: list[TopologyProviderCandidate] = []
    unavailable: list[str] = []
    for provider, artifacts in sorted(provider_artifacts.items()):
        if provider not in _KNOWN_PROVIDERS:
            raise TopologyEvidenceError(f"unsupported topology provider: {provider!r}")
        if not isinstance(artifacts, ProviderArtifactBytes):
            raise TopologyEvidenceError(f"provider artifacts are malformed: {provider}")
        if artifacts.unavailable_reason is not None:
            if artifacts.analysis is not None or artifacts.summary is not None:
                raise TopologyEvidenceError(
                    f"unavailable provider includes bytes: {source_id}/{provider}"
                )
            unavailable.append(provider)
            providers.append(
                TopologyProviderCandidate(
                    provider=provider,
                    unavailable_reason=dict(artifacts.unavailable_reason),
                )
            )
            continue
        if not isinstance(artifacts.analysis, bytes) or not isinstance(
            artifacts.summary, bytes
        ):
            raise TopologyEvidenceError(
                f"provider bytes are missing: {source_id}/{provider}"
            )
        try:
            providers.append(
                _validated_provider_candidate(
                    provider,
                    source_id,
                    artifacts.analysis,
                    artifacts.summary,
                )
            )
        except TopologyProviderError as exc:
            raise TopologyEvidenceError(
                f"invalid provider analysis for {source_id}/{provider}: {exc}"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TopologyEvidenceError(
                f"invalid provider summary for {source_id}/{provider}: {exc}"
            ) from exc
        except TopologyPublicationValidationError as exc:
            raise TopologyEvidenceError(
                f"invalid provider summary for {source_id}/{provider}: {exc}"
            ) from exc

    return _topology_evidence(
        source_id,
        source_path,
        fingerprint,
        provenance,
        providers,
        unavailable,
    )


def _validated_provider_candidate(
    provider: str,
    source_id: str,
    analysis: bytes,
    summary: bytes,
) -> TopologyProviderCandidate:
    document = json.loads(analysis)
    loaded = load_provider_document(document, provider=provider, source_id=source_id)
    validate_provider_summary(
        provider,
        source_id,
        document=document,
        loaded=loaded,
        summary=json.loads(summary),
    )
    return TopologyProviderCandidate(
        provider=provider,
        analysis=analysis,
        summary=summary,
        capabilities=_capabilities(analysis, provider),
    )


def _topology_evidence(
    source_id: str,
    source_path: str,
    fingerprint: SourceFingerprint,
    provenance: Mapping[str, object],
    providers: list[TopologyProviderCandidate],
    unavailable: list[str],
) -> TopologyEvidence:
    if not any(provider.unavailable_reason is None for provider in providers):
        raise TopologyEvidenceError(f"source has no usable provider evidence: {source_id}")
    return TopologyEvidence(
        candidate=TopologySnapshotCandidate(
            source_id=source_id,
            source_path=source_path,
            source_fingerprint=fingerprint,
            analyzed_commit=fingerprint.git_head,
            provenance=dict(provenance),
            providers=tuple(providers),
        ),
        unavailable_providers=tuple(unavailable),
    )


def build_empty_topology_snapshot_candidate(
    source_id: str,
    source_path: str,
    fingerprint: SourceFingerprint,
    provenance: Mapping[str, object],
) -> TopologyEvidence:
    """Represent a planner-proven empty source with explicit zero-graph evidence."""
    analysis = json.dumps(
        {
            "schema_version": 2,
            "version": "2.0.0",
            "tool": "codegraph",
            "tool_version": "1.4.1",
            "repo_path": "",
            "provider_status": "complete",
            "complete": True,
            "supported": True,
            "counts": {
                "discovered_symbols": 0,
                "emitted_symbols": 0,
                "excluded_symbols": 0,
                "discovered_relationships": 0,
                "emitted_relationships": 0,
                "excluded_relationships": 0,
            },
            "diagnostics": {"unresolved_relationships": []},
            "symbols": [],
            "relationships": [],
            "call_graph": [],
            "type_hierarchy": [],
            "impact_radius": [],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    summary = json.dumps(
        {
            "schema_version": 2,
            "tool": "codegraph",
            "tool_version": "1.4.1",
            "provider_status": "complete",
            "complete": True,
            "counts": json.loads(analysis)["counts"],
            "diagnostics": {"unresolved_relationships": []},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    return TopologyEvidence(
        candidate=TopologySnapshotCandidate(
            source_id=source_id,
            source_path=source_path,
            source_fingerprint=fingerprint,
            analyzed_commit=fingerprint.git_head,
            provenance=dict(provenance),
            providers=(
                TopologyProviderCandidate(
                    provider="codegraph",
                    analysis=analysis,
                    summary=summary,
                    capabilities=("relationships", "symbols"),
                ),
            ),
        ),
        unavailable_providers=(),
    )


def upgrade_legacy_codegraph_candidate(
    source_id: str,
    source_path: str,
    fingerprint: SourceFingerprint,
    paths: ProviderArtifactPaths,
    provenance: Mapping[str, object],
) -> TopologyEvidence | None:
    """Upgrade only an unambiguous schema-1 CodeGraph artifact.

    ``None`` means that the historical display-name graph cannot be converted
    safely and must be refreshed. No unresolved or ambiguous edge is promoted
    into the schema-2 traversable relationship collection.
    """
    try:
        analysis_path = _contained_provider_file(paths.owner_dir, paths.analysis)
        summary_path = _contained_provider_file(paths.owner_dir, paths.summary)
        legacy = json.loads(analysis_path.read_bytes())
        summary = summary_path.read_bytes()
        if not isinstance(json.loads(summary), dict):
            return None
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not _is_historical_codegraph_v1_document(legacy):
        return None
    symbols_raw = legacy.get("symbols")
    relationships_raw = legacy.get("relationships", [])
    call_graph_raw = legacy.get("call_graph", [])
    type_hierarchy_raw = legacy.get("type_hierarchy", [])
    impact_radius_raw = legacy.get("impact_radius", [])
    if not all(
        isinstance(value, list)
        for value in (
            symbols_raw,
            relationships_raw,
            call_graph_raw,
            type_hierarchy_raw,
            impact_radius_raw,
        )
    ):
        return None
    symbols: list[dict[str, object]] = []
    aliases: dict[str, list[str]] = {}
    for raw in symbols_raw:
        if not isinstance(raw, dict):
            return None
        path = raw.get("file_path")
        qualified = raw.get("qualified_name")
        kind = raw.get("kind")
        signature = raw.get("signature", "")
        if not all(isinstance(value, str) and value for value in (path, qualified, kind)):
            return None
        if signature is not None and not isinstance(signature, str):
            return None
        try:
            key = canonical_symbol_key(path, qualified, kind, signature)
        except Exception:
            return None
        symbol = {
            "symbol_key": key,
            "file_path": path,
            "qualified_name": qualified,
            "name": raw.get("name") if isinstance(raw.get("name"), str) else qualified,
            "kind": kind,
            "signature": signature or "",
            "line_start": raw.get("line_start", 1),
            "line_end": raw.get("line_end", raw.get("line_start", 1)),
        }
        if not isinstance(symbol["line_start"], int) or not isinstance(symbol["line_end"], int):
            return None
        symbols.append(symbol)
        for alias in {path, qualified, str(symbol["name"])}:
            aliases.setdefault(alias, []).append(key)
    if len({symbol["symbol_key"] for symbol in symbols}) != len(symbols):
        return None
    def resolve(raw: Mapping[str, object], *names: str) -> tuple[str, str] | None:
        for name in names:
            value = raw.get(name)
            if not isinstance(value, str):
                continue
            matches = aliases.get(value, [])
            if len(matches) != 1:
                return None
            return value, matches[0]
        return None

    relationships: list[dict[str, object]] = []
    for raw in relationships_raw:
        if not isinstance(raw, dict):
            return None
        source = resolve(raw, "source", "source_name")
        target = resolve(raw, "target", "target_name")
        kind = raw.get("kind")
        if source is None or target is None or not isinstance(kind, str):
            return None
        relationships.append(
            {
                "kind": kind,
                "source_key": source[1],
                "target_key": target[1],
                "source_name": source[0],
                "target_name": target[0],
            }
        )
    call_graph = _upgrade_legacy_projection(
        call_graph_raw,
        resolve,
        ("caller", "caller_name", "source", "source_name"),
        ("callee", "callee_name", "target", "target_name"),
        "caller_key",
        "callee_key",
    )
    type_hierarchy = _upgrade_legacy_projection(
        type_hierarchy_raw,
        resolve,
        ("child", "child_name", "source", "source_name"),
        ("parent", "parent_name", "target", "target_name"),
        "child_key",
        "parent_key",
    )
    impact_radius = _upgrade_legacy_impact_projection(impact_radius_raw, resolve)
    if call_graph is None or type_hierarchy is None or impact_radius is None:
        return None
    analysis_document = {
        "schema_version": 2,
        "version": "2.0.0",
        "tool": "codegraph",
        "tool_version": "1.4.1",
        "repo_path": legacy.get("repo_path", ""),
        "provider_status": "complete",
        "complete": True,
        "supported": bool(legacy.get("supported", bool(symbols))),
        "counts": {
            "discovered_symbols": len(symbols),
            "emitted_symbols": len(symbols),
            "excluded_symbols": 0,
            "discovered_relationships": len(relationships),
            "emitted_relationships": len(relationships),
            "excluded_relationships": 0,
        },
        "diagnostics": {"unresolved_relationships": []},
        "symbols": symbols,
        "relationships": relationships,
        "call_graph": call_graph,
        "type_hierarchy": type_hierarchy,
        "impact_radius": impact_radius,
    }
    analysis = json.dumps(
        analysis_document,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    summary = json.dumps(
        {
            field: analysis_document[field]
            for field in (
                "schema_version",
                "tool",
                "tool_version",
                "provider_status",
                "complete",
                "counts",
                "diagnostics",
            )
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    try:
        # Validate the converted document through the same provider boundary.
        load_provider_document(
            json.loads(analysis), provider="codegraph", source_id=source_id
        )
    except (TopologyProviderError, json.JSONDecodeError):
        return None
    return TopologyEvidence(
        candidate=TopologySnapshotCandidate(
            source_id=source_id,
            source_path=source_path,
            source_fingerprint=fingerprint,
            analyzed_commit=fingerprint.git_head,
            provenance=dict(provenance),
            providers=(TopologyProviderCandidate("codegraph", analysis, summary),),
        ),
        unavailable_providers=(),
    )


def is_historical_codegraph_v1_artifact(paths: ProviderArtifactPaths) -> bool:
    """Recognize only the known pre-schema CodeGraph artifact shape."""
    try:
        analysis_path = _contained_provider_file(paths.owner_dir, paths.analysis)
        document = json.loads(analysis_path.read_bytes())
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return _is_historical_codegraph_v1_document(document)


def _is_historical_codegraph_v1_document(document: object) -> bool:
    return (
        isinstance(document, dict)
        and "schema_version" not in document
        and document.get("version") == "1.0.0"
        and isinstance(document.get("repo_path"), str)
        and isinstance(document.get("supported"), bool)
        and isinstance(document.get("symbols"), list)
        and isinstance(document.get("relationships", []), list)
    )


def _provider_error_reason(path: Path) -> dict[str, object]:
    """Read an explicit provider failure without promoting any provider bytes."""
    document = json.loads(path.read_bytes())
    if not isinstance(document, dict):
        raise ValueError("provider error must be a JSON object")
    kind = document.get("kind")
    message = document.get("message")
    if not isinstance(kind, str) or not kind or not isinstance(message, str) or not message:
        raise ValueError("provider error requires kind and message")
    return dict(document)


def _upgrade_legacy_projection(
    entries: list[object],
    resolve: object,
    source_fields: tuple[str, ...],
    target_fields: tuple[str, ...],
    source_key: str,
    target_key: str,
) -> list[dict[str, object]] | None:
    """Preserve native projection fields while replacing display endpoints exactly."""
    if not callable(resolve):
        return None
    upgraded: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        source = resolve(entry, *source_fields)
        target = resolve(entry, *target_fields)
        if source is None or target is None:
            return None
        row = dict(entry)
        row[source_key] = source[1]
        row[target_key] = target[1]
        upgraded.append(row)
    return upgraded


def _upgrade_legacy_impact_projection(
    entries: list[object], resolve: object
) -> list[dict[str, object]] | None:
    if not callable(resolve):
        return None
    upgraded: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        symbol = resolve(entry, "symbol", "symbol_name", "source", "source_name")
        values = entry.get("affected", entry.get("affected_names", entry.get("affected_symbols")))
        if symbol is None or not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            return None
        affected: list[str] = []
        for value in values:
            target = resolve({"target": value}, "target")
            if target is None:
                return None
            affected.append(target[1])
        row = dict(entry)
        row["symbol_key"] = symbol[1]
        row["affected_keys"] = affected
        upgraded.append(row)
    return upgraded


def _contained_provider_file(owner_dir: Path, path: Path) -> Path:
    owner = Path(owner_dir)
    if owner.is_symlink() or not owner.is_dir():
        raise ValueError("declared source output directory is unsafe")
    resolved_owner = owner.resolve(strict=True)
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise FileNotFoundError(candidate)
    resolved = candidate.resolve(strict=True)
    resolved.relative_to(resolved_owner)
    current = candidate.parent
    while current != owner:
        if current.is_symlink():
            raise ValueError("provider evidence has a symlinked parent")
        current = current.parent
    return candidate


def _capabilities(analysis: bytes, provider: str) -> tuple[str, ...]:
    """Project only producer-declared capabilities into the receipt candidate."""
    document = json.loads(analysis)
    raw = document.get("capabilities") if isinstance(document, dict) else None
    if isinstance(raw, dict):
        return tuple(sorted(key for key, value in raw.items() if isinstance(key, str) and value is True))
    if isinstance(raw, list) and all(isinstance(value, str) for value in raw):
        return tuple(sorted(set(raw)))
    # CodeGraph schema-2 has no capabilities object; the native schema guarantees
    # exact symbols and relationships when it validates successfully.
    return ("relationships", "symbols") if provider == "codegraph" else ()
