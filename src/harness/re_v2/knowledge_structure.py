"""Bounded snapshot-time structural evidence for reviewed RE knowledge.

CodeGraph and PerlGraph run only against the temporary pinned Git tree exposed
by workspace snapshot capture.  Native artifacts are validated immediately and
canonicalized before they may become provider context; host paths and timestamps
never cross that boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
from typing import Callable, Literal, Mapping

from echelon.topology_model import (
    TopologyFile,
    TopologyRelationship,
    TopologySource,
    TopologySymbol,
    validate_source_id,
)
from echelon.topology_provider import (
    PublishedTopology,
    TopologyProviderError,
    load_provider_document,
)
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_evidence import validate_provider_context
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError
from harness.re_v2.protocol_22.schema import digest_value
from harness.re_v2.workspace_snapshot import MaterializedWorkspaceSource
from harness.node_runtime import (
    NodeRuntimeResolutionError,
    resolve_codegraph_bridge,
    resolve_perlgraph_cli,
)


StructuralStatus = Literal[
    "ready",
    "degraded",
    "empty",
    "unsupported",
    "unavailable",
    "not-applicable",
]
ExecutionState = Literal["completed", "unavailable", "failed", "limit-exceeded"]
_PERL_SUFFIXES = frozenset({".pl", ".pm", ".psgi", ".t"})


class KnowledgeStructureError(ValueError):
    """Closed structural-evidence contract failure."""


@dataclass(frozen=True, slots=True)
class StructuralEvidencePolicyV1:
    schema_version: int
    max_index_bytes: int
    max_artifact_bytes: int
    max_capture_bytes: int
    timeout_seconds: int

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or any(
                type(value) is not int or value <= 0
                for value in (
                    self.max_index_bytes,
                    self.max_artifact_bytes,
                    self.max_capture_bytes,
                    self.timeout_seconds,
                )
            )
            or self.max_artifact_bytes > self.max_index_bytes
            or self.max_capture_bytes > self.max_artifact_bytes
        ):
            raise KnowledgeStructureError("invalid-structural-evidence-policy")

    @classmethod
    def defaults(cls) -> "StructuralEvidencePolicyV1":
        return cls(
            schema_version=1,
            max_index_bytes=512 * 1024 * 1024,
            max_artifact_bytes=64 * 1024 * 1024,
            max_capture_bytes=4 * 1024 * 1024,
            timeout_seconds=15 * 60,
        )

    @property
    def identity(self) -> str:
        return content_digest(canonical_json_bytes(asdict(self)))


@dataclass(frozen=True, slots=True)
class StructuralProviderExecutionV1:
    state: ExecutionState
    document_bytes: bytes | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.state == "completed":
            if not isinstance(self.document_bytes, bytes) or self.reason_code is not None:
                raise KnowledgeStructureError("invalid-structural-provider-execution")
        elif self.document_bytes is not None or not isinstance(self.reason_code, str):
            raise KnowledgeStructureError("invalid-structural-provider-execution")


@dataclass(frozen=True, slots=True)
class StructuralProviderObservationV1:
    provider: str
    status: StructuralStatus
    complete: bool
    tool_version: str | None
    document_bytes: bytes | None
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class StructuralSourceObservationV1:
    source_id: str
    commit: str
    policy_id: str
    providers: tuple[StructuralProviderObservationV1, ...]


@dataclass(frozen=True, slots=True)
class StructuralProviderEvidenceV1:
    provider: str
    status: StructuralStatus
    complete: bool
    tool_version: str | None
    artifact_id: str | None
    reason_code: str | None

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StructuralSourceEvidenceV1:
    source_id: str
    source_content_id: str
    providers: tuple[StructuralProviderEvidenceV1, ...]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_content_id": self.source_content_id,
            "providers": [provider.to_json_dict() for provider in self.providers],
        }


@dataclass(frozen=True, slots=True)
class StructuralEvidenceCatalogV1:
    schema_version: int
    snapshot_id: str
    policy_id: str
    sources: tuple[StructuralSourceEvidenceV1, ...]

    def __post_init__(self) -> None:
        try:
            digest_value(self.snapshot_id, "structural snapshot")
            digest_value(self.policy_id, "structural policy")
        except ValueError:
            raise KnowledgeStructureError("invalid-structural-catalog") from None
        if self.schema_version != 1 or not self.sources:
            raise KnowledgeStructureError("invalid-structural-catalog")
        source_ids = tuple(source.source_id for source in self.sources)
        if source_ids != tuple(sorted(set(source_ids))):
            raise KnowledgeStructureError("invalid-structural-catalog")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "policy_id": self.policy_id,
            "sources": [source.to_json_dict() for source in self.sources],
        }

    @property
    def identity(self) -> str:
        return content_digest(canonical_json_bytes(self.to_json_dict()))


@dataclass(frozen=True, slots=True)
class StructuralQueryV1:
    schema_version: int
    source_id: str
    operation: str
    selector: str
    direction: str
    relations: tuple[str, ...]
    depth: int
    limit: int

    def __post_init__(self) -> None:
        try:
            validate_source_id(self.source_id)
        except ValueError:
            raise KnowledgeStructureError("invalid-structural-query") from None
        if (
            self.schema_version != 1
            or self.operation not in {"search", "explain", "neighbors", "impact"}
            or not isinstance(self.selector, str)
            or not self.selector.strip()
            or self.direction not in {"in", "out", "both"}
            or self.relations != tuple(sorted(set(self.relations)))
            or type(self.depth) is not int
            or not 1 <= self.depth <= 5
            or type(self.limit) is not int
            or not 1 <= self.limit <= 100
        ):
            raise KnowledgeStructureError("invalid-structural-query")

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StructuralProjectionV1:
    projection_id: str
    provider_bytes: bytes


def bind_structural_evidence(
    snapshot_id: str,
    source_content_ids: Mapping[str, str],
    observations: tuple[StructuralSourceObservationV1, ...],
    objects: ObjectStore,
) -> StructuralEvidenceCatalogV1:
    """Bind captured provider artifacts to immutable source content identities."""

    try:
        digest_value(snapshot_id, "structural snapshot")
        if set(source_content_ids) != {row.source_id for row in observations}:
            raise KnowledgeStructureError("structural-source-closure-mismatch")
        policy_ids = {row.policy_id for row in observations}
        if len(policy_ids) != 1:
            raise KnowledgeStructureError("structural-policy-mismatch")
        sources: list[StructuralSourceEvidenceV1] = []
        for observation in sorted(observations, key=lambda row: row.source_id):
            validate_source_id(observation.source_id)
            source_content_id = source_content_ids[observation.source_id]
            digest_value(source_content_id, "structural source content")
            providers: list[StructuralProviderEvidenceV1] = []
            for provider in observation.providers:
                artifact_id = (
                    objects.put_blob(provider.document_bytes)
                    if provider.document_bytes is not None
                    else None
                )
                providers.append(
                    StructuralProviderEvidenceV1(
                        provider.provider,
                        provider.status,
                        provider.complete,
                        provider.tool_version,
                        artifact_id,
                        provider.reason_code,
                    )
                )
            sources.append(
                StructuralSourceEvidenceV1(
                    observation.source_id,
                    source_content_id,
                    tuple(sorted(providers, key=lambda row: row.provider)),
                )
            )
        return StructuralEvidenceCatalogV1(
            1, snapshot_id, policy_ids.pop(), tuple(sources)
        )
    except (KeyError, ReV2LedgerError, ValueError, OSError):
        raise KnowledgeStructureError("invalid-structural-evidence") from None


def project_structural_query(
    catalog: StructuralEvidenceCatalogV1,
    objects: ObjectStore,
    query: StructuralQueryV1,
) -> StructuralProjectionV1:
    """Return one bounded provider-neutral graph projection for an RE dispatch."""

    sources = {source.source_id: source for source in catalog.sources}
    if query.source_id not in sources:
        raise KnowledgeStructureError("unknown-structural-query-source")
    loaded = []
    for source in catalog.sources:
        for provider in source.providers:
            if provider.artifact_id is None:
                continue
            try:
                value = json.loads(objects.read_blob(provider.artifact_id))
                loaded.append(
                    load_provider_document(
                        value, provider=provider.provider, source_id=source.source_id
                    )
                )
            except (ReV2LedgerError, OSError, UnicodeDecodeError, json.JSONDecodeError, TopologyProviderError):
                raise KnowledgeStructureError("invalid-structural-catalog-artifact") from None
    topology = PublishedTopology.from_loaded_providers(
        loaded,
        generation=1,
        source_fingerprints={
            source.source_id: source.source_content_id for source in catalog.sources
        },
        sources=(TopologySource(source.source_id) for source in catalog.sources),
    )
    relation_filter = frozenset(query.relations)
    if query.operation == "search":
        result = topology.search(query.source_id, query.selector, frozenset(), query.limit)
    elif query.operation == "explain":
        result = topology.explain(query.source_id, query.selector)
    elif query.operation == "neighbors":
        result = topology.neighbors(
            query.source_id,
            query.selector,
            query.direction,
            relation_filter,
            query.limit,
        )
    else:
        result = topology.impact(
            query.source_id, query.selector, query.depth, relation_filter
        )
    nodes = tuple(getattr(result, "nodes", ()))
    if not nodes and getattr(result, "node", None) is not None:
        nodes = (result.node,)
    relationships = tuple(getattr(result, "relationships", ()))
    source = sources[query.source_id]
    payload = canonical_json_bytes(
        {
            "schema_version": 1,
            "kind": "structural_evidence_projection",
            "snapshot_id": catalog.snapshot_id,
            "catalog_id": catalog.identity,
            "source_id": query.source_id,
            "source_content_id": source.source_content_id,
            "query": query.to_json_dict(),
            "providers": [
                {
                    "provider": provider.provider,
                    "status": provider.status,
                    "complete": provider.complete,
                    "tool_version": provider.tool_version,
                }
                for provider in source.providers
            ],
            "nodes": [_node_json(node) for node in nodes],
            "relationships": [_relationship_json(row) for row in relationships],
            "truncated": bool(getattr(result, "truncated", False)),
        }
    )
    try:
        validate_provider_context(payload)
    except ValueError:
        raise KnowledgeStructureError("unsafe-structural-projection") from None
    return StructuralProjectionV1(content_digest(payload), payload)


def _node_json(node: object) -> dict[str, object]:
    if isinstance(node, TopologySymbol):
        return {
            "id": node.id,
            "type": node.type,
            "source_id": node.source_id,
            "provider": node.provider,
            "path": node.path,
            "qualified_name": node.qualified_name,
            "name": node.name,
            "kind": node.kind,
            "signature": node.signature,
            "line_start": node.line_start,
            "line_end": node.line_end,
        }
    if isinstance(node, TopologyFile):
        return {"id": node.id, "type": node.type, "source_id": node.source_id, "path": node.path}
    if isinstance(node, TopologySource):
        return {"id": node.id, "type": node.type, "source_id": node.source_id}
    raise KnowledgeStructureError("unknown-structural-node")


def _relationship_json(row: TopologyRelationship) -> dict[str, object]:
    return {
        "source_id": row.source_id,
        "target_id": row.target_id,
        "type": row.type,
        "provider": row.provider,
        "provider_kind": row.provider_kind,
        "path": row.path,
        "line_start": row.line_start,
        "confidence": row.confidence,
    }


StructuralProviderRunner = Callable[
    [str, Path, StructuralEvidencePolicyV1], StructuralProviderExecutionV1
]


def capture_structural_source(
    source: MaterializedWorkspaceSource,
    workspace_root: Path,
    policy: StructuralEvidencePolicyV1,
    *,
    runner: StructuralProviderRunner | None = None,
) -> StructuralSourceObservationV1:
    """Capture optional structural providers from one pinned temporary source."""

    if not isinstance(source, MaterializedWorkspaceSource) or not isinstance(
        policy, StructuralEvidencePolicyV1
    ):
        raise KnowledgeStructureError("invalid-structural-source-request")
    execute = runner or (
        lambda provider, root, active_policy: _run_provider(
            provider,
            root,
            active_policy,
            runtime_root=Path(workspace_root),
        )
    )
    providers: list[StructuralProviderObservationV1] = []
    for provider in ("codegraph", "perlgraph"):
        if provider == "perlgraph" and not _contains_perl(source.source_root):
            providers.append(
                StructuralProviderObservationV1(
                    provider,
                    "not-applicable",
                    False,
                    None,
                    None,
                    "no-perl-source",
                )
            )
            continue
        try:
            execution = execute(provider, source.source_root, policy)
        except Exception:
            execution = StructuralProviderExecutionV1(
                "failed", None, "provider-execution-failed"
            )
        providers.append(_normalize_execution(source.source_id, provider, execution, policy))
    return StructuralSourceObservationV1(
        source.source_id,
        source.commit,
        policy.identity,
        tuple(providers),
    )


def _normalize_execution(
    source_id: str,
    provider: str,
    execution: StructuralProviderExecutionV1,
    policy: StructuralEvidencePolicyV1,
) -> StructuralProviderObservationV1:
    if execution.state != "completed":
        return StructuralProviderObservationV1(
            provider,
            "unavailable" if execution.state == "unavailable" else "degraded",
            False,
            None,
            None,
            execution.reason_code,
        )
    assert execution.document_bytes is not None
    if len(execution.document_bytes) > policy.max_artifact_bytes:
        return StructuralProviderObservationV1(
            provider, "degraded", False, None, None, "provider-artifact-too-large"
        )
    try:
        value = json.loads(execution.document_bytes)
        if not isinstance(value, dict):
            raise ValueError
        value.pop("generated_at", None)
        value["repo_path"] = "."
        payload = canonical_json_bytes(value)
        if len(payload) > policy.max_artifact_bytes:
            raise KnowledgeStructureError("provider-artifact-too-large")
        loaded = load_provider_document(value, provider=provider, source_id=source_id)
    except KnowledgeStructureError:
        return StructuralProviderObservationV1(
            provider, "degraded", False, None, None, "provider-artifact-too-large"
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TopologyProviderError, ValueError):
        return StructuralProviderObservationV1(
            provider, "degraded", False, None, None, "invalid-provider-artifact"
        )
    return StructuralProviderObservationV1(
        provider,
        loaded.status,  # type: ignore[arg-type]
        loaded.complete,
        loaded.tool_version,
        payload,
        None if loaded.status == "ready" else "provider-reported-limited-coverage",
    )


def _contains_perl(root: Path) -> bool:
    for current, directories, files in os.walk(root):
        directories[:] = sorted(
            name for name in directories if name not in {".git", ".codegraph"}
        )
        if any(Path(name).suffix.casefold() in _PERL_SUFFIXES for name in files):
            return True
    return False


def _run_provider(
    provider: str,
    source_root: Path,
    policy: StructuralEvidencePolicyV1,
    *,
    runtime_root: Path,
) -> StructuralProviderExecutionV1:
    """Run one installed provider with finite time, output, and index storage."""

    node = shutil.which("node")
    if node is None:
        return StructuralProviderExecutionV1("unavailable", None, "node-unavailable")
    try:
        if provider == "codegraph":
            entrypoint = resolve_codegraph_bridge(runtime_root)
        elif provider == "perlgraph":
            entrypoint = resolve_perlgraph_cli(runtime_root)
        else:
            raise KnowledgeStructureError("unknown-structural-provider")
    except NodeRuntimeResolutionError:
        return StructuralProviderExecutionV1(
            "unavailable", None, "provider-runtime-unavailable"
        )

    with tempfile.TemporaryDirectory(prefix="echelon-re-structure-") as temporary:
        output_root = Path(temporary)
        analysis = output_root / "analysis.json"
        summary = output_root / "summary.json"
        stdout_path = output_root / "stdout.bin"
        stderr_path = output_root / "stderr.bin"
        command = [
            node,
            str(entrypoint),
            "analyze",
            "--repo-path",
            str(source_root),
            "--output-path",
            str(analysis),
            "--summary-path",
            str(summary),
        ]
        try:
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = subprocess.Popen(
                    command,
                    cwd=source_root,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
                failure = _wait_bounded(process, source_root, output_root, policy)
        except OSError:
            return StructuralProviderExecutionV1(
                "failed", None, "provider-process-unavailable"
            )
        if failure is not None:
            return StructuralProviderExecutionV1(
                "limit-exceeded" if failure.endswith("limit") else "failed",
                None,
                failure,
            )
        try:
            payload = analysis.read_bytes()
        except OSError:
            return StructuralProviderExecutionV1(
                "failed", None, "provider-artifact-missing"
            )
        if len(payload) > policy.max_artifact_bytes:
            return StructuralProviderExecutionV1(
                "limit-exceeded", None, "provider-artifact-limit"
            )
        return StructuralProviderExecutionV1("completed", payload)


def _wait_bounded(
    process: subprocess.Popen[bytes],
    source_root: Path,
    output_root: Path,
    policy: StructuralEvidencePolicyV1,
) -> str | None:
    deadline = time.monotonic() + policy.timeout_seconds
    index_root = source_root / ".codegraph"
    while process.poll() is None:
        if time.monotonic() >= deadline:
            _terminate_process_group(process)
            return "provider-time-limit"
        if _tree_bytes(index_root, policy.max_index_bytes) > policy.max_index_bytes:
            _terminate_process_group(process)
            return "provider-index-limit"
        if _paths_bytes(
            (output_root / "stdout.bin", output_root / "stderr.bin"),
            policy.max_capture_bytes,
        ) > policy.max_capture_bytes:
            _terminate_process_group(process)
            return "provider-capture-limit"
        if _paths_bytes(
            (output_root / "analysis.json", output_root / "summary.json"),
            policy.max_artifact_bytes,
        ) > policy.max_artifact_bytes:
            _terminate_process_group(process)
            return "provider-artifact-limit"
        time.sleep(0.2)
    if process.returncode != 0:
        return "provider-exit-failure"
    return None


def _tree_bytes(root: Path, ceiling: int) -> int:
    if not root.exists():
        return 0
    total = 0
    try:
        for current, _directories, files in os.walk(root):
            for name in files:
                path = Path(current) / name
                if path.is_symlink():
                    continue
                total += path.stat().st_size
                if total > ceiling:
                    return total
    except OSError:
        return ceiling + 1
    return total


def _paths_bytes(paths: tuple[Path, ...], ceiling: int) -> int:
    total = 0
    try:
        for path in paths:
            if path.exists() and not path.is_symlink():
                total += path.stat().st_size
                if total > ceiling:
                    return total
    except OSError:
        return ceiling + 1
    return total


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


__all__ = (
    "KnowledgeStructureError",
    "StructuralEvidencePolicyV1",
    "StructuralEvidenceCatalogV1",
    "StructuralProviderEvidenceV1",
    "StructuralProviderExecutionV1",
    "StructuralProviderObservationV1",
    "StructuralProjectionV1",
    "StructuralQueryV1",
    "StructuralSourceEvidenceV1",
    "StructuralSourceObservationV1",
    "bind_structural_evidence",
    "capture_structural_source",
    "project_structural_query",
)
