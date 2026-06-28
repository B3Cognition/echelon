"""Reconcile MemPalace retrievals against canonical disk artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Sequence

from echelon.context_metadata import ACTIVE_STATUSES, artifact_hash


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
    accepted: list[Any] = []
    rejected: list[dict[str, str]] = []
    resolved_root = project_root.resolve()

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

        artifact_path = (project_root / artifact_rel).resolve()
        try:
            artifact_relative = artifact_path.relative_to(resolved_root)
        except ValueError:
            rejected.append({"drawer_id": drawer_id, "reason": "artifact_outside_project", "artifact_path": artifact_rel})
            continue
        if not artifact_relative.parts or artifact_relative.parts[0] != "specs":
            rejected.append(
                {"drawer_id": drawer_id, "reason": "non_canonical_artifact_path", "artifact_path": artifact_rel}
            )
            continue
        if len(artifact_relative.parts) < 2 or not re.match(r"^\d{3}-.*", artifact_relative.parts[1]):
            rejected.append(
                {"drawer_id": drawer_id, "reason": "non_canonical_artifact_path", "artifact_path": artifact_rel}
            )
            continue

        if not artifact_path.exists():
            rejected.append({"drawer_id": drawer_id, "reason": "artifact_missing", "artifact_path": artifact_rel})
            continue
        actual_hash = artifact_hash(artifact_path)
        if expected_hash and actual_hash != expected_hash:
            rejected.append({"drawer_id": drawer_id, "reason": "hash_mismatch", "artifact_path": artifact_rel})
            continue

        accepted.append(drawer)

    return ReconciliationReport(accepted=accepted, rejected=rejected)


def _metadata(drawer: Any) -> dict[str, Any]:
    metadata = getattr(drawer, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    if isinstance(drawer, dict):
        raw = drawer.get("metadata") or {}
        return raw if isinstance(raw, dict) else {}
    return {}
