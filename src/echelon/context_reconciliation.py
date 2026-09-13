"""Reconcile MemPalace retrievals against canonical disk artifacts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
from typing import Any, Sequence

from echelon.context_metadata import ACTIVE_STATUSES, artifact_hash
from harness.squad_publication import PublicationError
from harness.squad_source_snapshot import _source_path


@dataclass(frozen=True)
class ReconciliationReport:
    accepted: list[Any] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_count": len(self.accepted),
            "rejected": list(self.rejected),
        }


def reconcile_drawers(
    drawers: Sequence[Any],
    project_root: Path,
    include_statuses: set[str] | None = None,
) -> ReconciliationReport:
    include = ACTIVE_STATUSES if include_statuses is None else include_statuses
    resolved_root = project_root.resolve()

    def check_artifact(artifact_rel: str, expected_hash: str) -> str | None:
        artifact_path = (project_root / artifact_rel).resolve()
        try:
            artifact_relative = artifact_path.relative_to(resolved_root)
        except ValueError:
            return "artifact_outside_project"
        if not _is_canonical_artifact_path(artifact_relative):
            return "non_canonical_artifact_path"
        if not artifact_path.exists():
            return "artifact_missing"
        if artifact_hash(artifact_path) != expected_hash:
            return "hash_mismatch"
        return None

    return _reconcile_with_checker(drawers, include, check_artifact)


def reconcile_captured_drawers(
    drawers: Sequence[Any],
    artifact_images: dict[str, bytes | None],
    include_statuses: set[str] | None = None,
) -> ReconciliationReport:
    """Reconcile drawers against an exact, detached artifact image table."""
    try:
        images = _copy_captured_images(artifact_images)
        include = ACTIVE_STATUSES if include_statuses is None else include_statuses

        def check_artifact(artifact_rel: str, expected_hash: str) -> str | None:
            try:
                artifact_relative = _source_path(artifact_rel)
            except PublicationError:
                return "non_canonical_artifact_path"
            if artifact_relative.as_posix() != artifact_rel:
                return "non_canonical_artifact_path"
            if not _is_canonical_artifact_path(artifact_relative):
                return "non_canonical_artifact_path"
            if artifact_rel not in images:
                return "artifact_unobserved"
            content = images[artifact_rel]
            if content is None:
                return "artifact_missing"
            actual_hash = "sha256:" + hashlib.sha256(content).hexdigest()
            if actual_hash != expected_hash:
                return "hash_mismatch"
            return None

        return _reconcile_with_checker(drawers, include, check_artifact)
    except Exception:
        pass
    raise ValueError("invalid captured reconciliation input") from None


def _reconcile_with_checker(
    drawers: Sequence[Any],
    include: set[str],
    check_artifact: Callable[[str, str], str | None],
) -> ReconciliationReport:
    accepted: list[Any] = []
    rejected: list[dict[str, str]] = []

    for drawer in drawers:
        metadata = _metadata(drawer)
        drawer_id = str(getattr(drawer, "drawer_id", metadata.get("id", "unknown")))
        artifact_rel = str(metadata.get("artifact_path") or metadata.get("source_file") or "")
        expected_hash = str(metadata.get("artifact_hash") or "")
        status = str(metadata.get("lifecycle_status") or metadata.get("status") or "active")

        if status not in include:
            rejected.append({"drawer_id": drawer_id, "reason": "lifecycle_excluded", "status": status})
            continue
        if not artifact_rel:
            rejected.append({"drawer_id": drawer_id, "reason": "missing_artifact_path"})
            continue
        if not expected_hash:
            rejected.append({"drawer_id": drawer_id, "reason": "missing_artifact_hash", "artifact_path": artifact_rel})
            continue

        reason = check_artifact(artifact_rel, expected_hash)
        if reason is not None:
            rejected.append({"drawer_id": drawer_id, "reason": reason, "artifact_path": artifact_rel})
            continue

        accepted.append(drawer)

    return ReconciliationReport(accepted=accepted, rejected=rejected)


def _copy_captured_images(
    artifact_images: dict[str, bytes | None],
) -> dict[str, bytes | None]:
    if type(artifact_images) is not dict:
        raise TypeError
    copied: dict[str, bytes | None] = {}
    for path, content in artifact_images.items():
        if type(path) is not str or _source_path(path).as_posix() != path:
            raise ValueError
        if content is not None and type(content) is not bytes:
            raise TypeError
        copied[path] = content
    return copied


def _is_canonical_artifact_path(path: Path) -> bool:
    return bool(
        path.parts
        and path.parts[0] == "specs"
        and len(path.parts) >= 2
        and re.match(r"^\d{3}-.*", path.parts[1])
    )


def _metadata(drawer: Any) -> dict[str, Any]:
    metadata = getattr(drawer, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    if isinstance(drawer, dict):
        raw = drawer.get("metadata") or {}
        return raw if isinstance(raw, dict) else {}
    return {}
