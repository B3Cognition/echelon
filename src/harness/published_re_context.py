"""Run-local read-only snapshots of durable reverse-engineering publications."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from harness.re_registry import canonical_re_artifacts, load_published_index


def attach_published_re_context(
    project_root: Path,
    run_dir: Path,
    *,
    ignore: bool,
) -> dict[str, object]:
    """Return an immutable run-local view of the latest registered RE context."""
    if ignore:
        return {"status": "ignored", "generation": 0, "artifacts": {}}

    root = project_root.resolve()
    index = load_published_index(root)
    if index is None:
        return {"status": "absent", "generation": 0, "artifacts": {}}

    resolved_run = run_dir.resolve()
    if not resolved_run.is_relative_to(root):
        raise ValueError(f"spec run directory must be inside workspace: {run_dir}")

    canonical = canonical_re_artifacts(root, index)
    snapshot_root = resolved_run / "context" / "published-re"
    artifacts = _snapshot_artifact_map(root, snapshot_root, canonical)
    return {
        "status": "attached",
        "generation": index.generation,
        "publication_status": index.publication_status,
        "snapshot_root": str(snapshot_root),
        "artifacts": artifacts,
    }


def write_canonical_re_context(
    project_root: Path,
    spec_dir: Path,
    context: Mapping[str, object],
) -> Path:
    """Publish the run-local RE snapshot identity beside a canonical spec."""
    root = project_root.resolve()
    resolved_spec_dir = spec_dir.resolve()
    if not resolved_spec_dir.is_relative_to(root):
        raise ValueError(f"canonical spec directory must be inside workspace: {spec_dir}")

    status = str(context.get("status") or "").strip()
    if status not in {"attached", "ignored", "absent"}:
        raise ValueError(f"unsupported published RE context status: {status}")
    generation = context.get("generation", 0)
    if type(generation) is not int or generation < 0:
        raise ValueError("published RE context generation must be a non-negative integer")

    artifacts: list[dict[str, str]] = []
    if status == "attached":
        snapshot_value = context.get("snapshot_root")
        if not isinstance(snapshot_value, str) or not snapshot_value.strip():
            raise ValueError("attached published RE context is missing snapshot_root")
        snapshot_root = Path(snapshot_value).resolve()
        if not snapshot_root.is_relative_to(root):
            raise ValueError("published RE snapshot must be inside workspace")
        artifacts = _canonical_artifact_rows(
            context.get("artifacts"),
            snapshot_root=snapshot_root,
        )

    path = resolved_spec_dir / "re-context.json"
    payload = {
        "schema_version": 1,
        "status": status,
        "generation": generation,
        "artifacts": artifacts,
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _canonical_artifact_rows(
    value: object,
    *,
    snapshot_root: Path,
) -> list[dict[str, str]]:
    paths: set[Path] = set()
    for raw in _artifact_path_values(value):
        candidate = Path(raw)
        if not candidate.is_absolute():
            continue
        resolved = candidate.resolve()
        if not resolved.is_relative_to(snapshot_root):
            raise ValueError(f"published RE artifact is outside published RE snapshot: {candidate}")
        if resolved.is_file():
            paths.add(resolved)
        elif not resolved.exists():
            raise ValueError(f"published RE snapshot artifact is missing: {candidate}")

    return [
        {
            "path": f"re/{path.relative_to(snapshot_root).as_posix()}",
            "hash": f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
        }
        for path in sorted(paths, key=lambda item: item.relative_to(snapshot_root).as_posix())
    ]


def _artifact_path_values(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _artifact_path_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _artifact_path_values(item)


def _snapshot_artifact_map(
    project_root: Path,
    snapshot_root: Path,
    artifacts: dict[str, object],
) -> dict[str, object]:
    re_root = (project_root / "re").resolve()
    snapshot_root.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(
        tempfile.mkdtemp(prefix=".published-re-", dir=str(snapshot_root.parent))
    )
    try:
        rewritten = _rewrite_value(artifacts, re_root=re_root, destination=temp)
        if not isinstance(rewritten, dict):
            raise TypeError("canonical RE artifact map must be an object")
        if snapshot_root.exists():
            shutil.rmtree(snapshot_root)
        os.replace(temp, snapshot_root)
        return _replace_prefix(rewritten, temp, snapshot_root)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def _rewrite_value(value: object, *, re_root: Path, destination: Path) -> object:
    if isinstance(value, str):
        return _copy_registered_path(value, re_root=re_root, destination=destination)
    if isinstance(value, list):
        return [
            _rewrite_value(item, re_root=re_root, destination=destination)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            str(key): _rewrite_value(item, re_root=re_root, destination=destination)
            for key, item in value.items()
        }
    return value


def _copy_registered_path(value: str, *, re_root: Path, destination: Path) -> str:
    path = Path(value)
    if not path.is_absolute():
        return value
    resolved = path.resolve()
    if not resolved.is_relative_to(re_root):
        raise ValueError(f"published RE artifact escapes registry: {path}")
    relative = resolved.relative_to(re_root)
    target = destination / relative
    if resolved.is_dir():
        target.mkdir(parents=True, exist_ok=True)
    elif resolved.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved, target)
    else:
        raise ValueError(f"published RE artifact is missing: {path}")
    return str(target)


def _replace_prefix(value: Any, old: Path, new: Path) -> Any:
    if isinstance(value, str):
        path = Path(value)
        if path.is_absolute() and path.is_relative_to(old):
            return str(new / path.relative_to(old))
        return value
    if isinstance(value, list):
        return [_replace_prefix(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _replace_prefix(item, old, new) for key, item in value.items()}
    return value
