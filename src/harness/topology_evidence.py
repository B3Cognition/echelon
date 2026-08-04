"""Build explicit, validated topology publication candidates from provider output."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from echelon.topology_provider import (
    TopologyProviderError,
    load_provider_artifact,
    load_provider_document,
)
from echelon.topology_model import canonical_symbol_key
from harness.re_fingerprint import SourceFingerprint
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
class TopologyEvidence:
    """A publishable snapshot plus explicitly unavailable provider observations."""

    candidate: TopologySnapshotCandidate
    unavailable_providers: tuple[str, ...]


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
            loaded = load_provider_artifact(
                analysis_path, provider=provider, source_id=source_id
            )
            analysis = analysis_path.read_bytes()
            summary = summary_path.read_bytes()
            summary_document = json.loads(summary)
            validate_provider_summary(
                provider,
                source_id,
                document=json.loads(analysis),
                loaded=loaded,
                summary=summary_document,
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

        raw_capabilities = _capabilities(analysis, provider)
        providers.append(
            TopologyProviderCandidate(
                provider=provider,
                analysis=analysis,
                summary=summary,
                capabilities=raw_capabilities,
            )
        )

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
