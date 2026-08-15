"""Pure status projection and durable projection rebuilding for RE v2."""

from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
from typing import Mapping, Protocol, Sequence

from .canonical import canonical_json_bytes
from .events import EventRecord, EventStore
from .model import RunManifest
from .run_store import ReV2Paths, load_run_manifest


_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ReV2ProjectionError(RuntimeError):
    """Raised when authoritative inputs cannot produce a safe projection."""


class ProjectionLedgerView(Protocol):
    """The sole ledger fact needed before Task 5 supplies ``LedgerView``."""

    @property
    def accepted_artifacts(self) -> Mapping[str, object]: ...


class _EmptyLedgerView:
    accepted_artifacts: Mapping[str, object] = {}


def project_run(
    manifest: RunManifest,
    events: Sequence[EventRecord],
    ledger: ProjectionLedgerView,
) -> dict[str, object]:
    """Derive a convenience view only from immutable authoritative inputs."""
    if events:
        first = events[0]
        if first.type != "run_created" or first.payload.get(
            "run_manifest_id"
        ) != manifest.run_manifest_id:
            raise ReV2ProjectionError("run_created does not match immutable run manifest")

    state = "created"
    current_work_item_id: str | None = None
    known_tokens = 0
    unknown_token_dispatches = 0
    active_ms = 0
    candidates_persisted = 0
    certifications_accepted = 0
    certifications_rejected = 0
    authorizations: list[dict[str, object]] = []
    pause_reason: str | None = None
    terminal_reason: str | None = None

    for event in events:
        payload = event.payload
        if event.type == "work_planned":
            state = "planned"
        elif event.type in {"dispatch_leased", "dispatch_started"}:
            state = "running"
            current_work_item_id = str(payload["work_item_id"])
        elif event.type == "dispatch_observed":
            state = "running"
            observation = payload["observation"]
            if not isinstance(observation, Mapping):
                raise ReV2ProjectionError("dispatch_observed has invalid observation")
            active_ms += int(observation["duration_ms"])
            token_usage = observation["token_usage"]
            if token_usage is None:
                unknown_token_dispatches += 1
            else:
                known_tokens += int(token_usage)
        elif event.type == "candidate_persisted":
            candidates_persisted += 1
        elif event.type == "candidate_certified":
            certifications_accepted += 1
        elif event.type == "candidate_rejected":
            certifications_rejected += 1
            current_work_item_id = None
            state = "planned"
        elif event.type == "artifact_accepted":
            current_work_item_id = None
            state = "planned"
        elif event.type == "budget_authorized":
            authorizations.append(
                {
                    "authorized_by": payload["authorized_by"],
                    "dimension": payload["dimension"],
                    "new_value": payload["new_value"],
                    "occurred_at": event.occurred_at,
                    "old_value": payload["old_value"],
                    "reason": payload["reason"],
                    "seq": event.seq,
                }
            )
        elif event.type == "run_paused":
            state = "paused"
            pause_reason = str(payload["reason"])
        elif event.type == "run_resumed":
            state = "running" if current_work_item_id is not None else "planned"
            pause_reason = None
        elif event.type == "run_completed":
            state = "complete"
            terminal_reason = str(payload["reason"])
        elif event.type == "run_finalized_partial":
            state = "finalized_partial"
            terminal_reason = str(payload["reason"])
        elif event.type == "run_failed":
            state = "failed"
            terminal_reason = str(payload["reason"])

    roots = _accepted_roots(ledger)
    return {
        "accepted_roots": roots,
        "budget_authorizations": authorizations,
        "candidate_counts": {"persisted": candidates_persisted},
        "certification_counts": {
            "accepted": certifications_accepted,
            "rejected": certifications_rejected,
        },
        "current_work_item_id": current_work_item_id,
        "engine": manifest.engine,
        "engine_protocol_version": manifest.engine_protocol_version,
        "partition_manifest_id": manifest.partition_manifest_id,
        "pause_reason": pause_reason,
        "requested_goals": list(manifest.requested_goals),
        "run_id": manifest.run_id,
        "run_manifest_id": manifest.run_manifest_id,
        "schema_version": 1,
        "source_snapshot_id": manifest.source_snapshot_id,
        "state": state,
        "terminal_reason": terminal_reason,
        "usage": {
            "active_ms": active_ms,
            "known_tokens": known_tokens,
            "token_coverage_complete": unknown_token_dispatches == 0,
            "unknown_token_dispatches": unknown_token_dispatches,
        },
    }


def rebuild_projection(
    paths: ReV2Paths, ledger: ProjectionLedgerView | None = None
) -> dict[str, object]:
    """Replay authorities and atomically replace, never read, projection JSON."""
    manifest = load_run_manifest(paths.root.parent)
    events = EventStore(paths).replay()
    if ledger is None:
        try:
            has_ledger_records = paths.ledger.exists() and paths.ledger.stat().st_size > 0
        except OSError as exc:
            raise ReV2ProjectionError(f"cannot inspect authoritative ledger: {exc}") from exc
        if has_ledger_records:
            raise ReV2ProjectionError(
                "a replayed ledger view is required for a nonempty authoritative ledger"
            )
        ledger = _EmptyLedgerView()
    projection = project_run(manifest, events, ledger)
    _write_projection(paths, projection)
    return projection


def _accepted_roots(ledger: ProjectionLedgerView) -> list[str]:
    accepted = ledger.accepted_artifacts
    if not isinstance(accepted, Mapping):
        raise ReV2ProjectionError("ledger accepted_artifacts must be a mapping")
    accepted_hashes: set[str] = set()
    dependencies: set[str] = set()
    for receipt in accepted.values():
        if isinstance(receipt, Mapping):
            artifact_hash = receipt.get("artifact_hash")
            artifact_key = receipt.get("artifact_key")
        else:
            artifact_hash = getattr(receipt, "artifact_hash", None)
            artifact_key = getattr(receipt, "artifact_key", None)
        if not isinstance(artifact_hash, str) or not _DIGEST_RE.fullmatch(artifact_hash):
            raise ReV2ProjectionError("ledger artifact receipt has invalid artifact_hash")
        accepted_hashes.add(artifact_hash)
        if artifact_key is None:
            raise ReV2ProjectionError("ledger artifact receipt is missing artifact_key")
        if isinstance(artifact_key, Mapping):
            dependency_hashes = artifact_key.get("dependency_hashes")
        else:
            dependency_hashes = getattr(artifact_key, "dependency_hashes", None)
        if not isinstance(dependency_hashes, (list, tuple)):
            raise ReV2ProjectionError(
                "ledger artifact receipt has invalid dependency_hashes"
            )
        for dependency_hash in dependency_hashes:
            if not isinstance(dependency_hash, str) or not _DIGEST_RE.fullmatch(
                dependency_hash
            ):
                raise ReV2ProjectionError(
                    "ledger artifact receipt has invalid dependency_hashes"
                )
            dependencies.add(dependency_hash)
        if tuple(dependency_hashes) != tuple(sorted(set(dependency_hashes))):
            raise ReV2ProjectionError(
                "ledger dependency_hashes must be unique and sorted"
            )
    return sorted(accepted_hashes - dependencies)


def _write_projection(paths: ReV2Paths, projection: Mapping[str, object]) -> None:
    payload = canonical_json_bytes(dict(projection))
    temporary: Path | None = None
    try:
        fd, name = tempfile.mkstemp(
            prefix=".projection.json.", suffix=".tmp", dir=paths.root
        )
        temporary = Path(name)
        try:
            _write_all(fd, payload)
            _fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, paths.projection)
        temporary = None
        _fsync_directory(paths.root)
    except ReV2ProjectionError:
        raise
    except OSError as exc:
        raise ReV2ProjectionError(f"cannot persist projection atomically: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(fd, payload[offset:])
        except InterruptedError:
            continue
        if written <= 0:
            raise OSError("short write while persisting projection")
        offset += written


def _fsync(fd: int) -> None:
    while True:
        try:
            os.fsync(fd)
            return
        except InterruptedError:
            continue


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        _fsync(fd)
    finally:
        os.close(fd)


__all__ = (
    "ProjectionLedgerView",
    "ReV2ProjectionError",
    "project_run",
    "rebuild_projection",
)
