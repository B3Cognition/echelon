"""Strict discovery of completed verify-spec evidence runs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable

from kernel.spec_identity import spec_identity_aliases


def discover_verify_evidence_runs(
    workspace_root: Path,
    spec_id: str,
    *,
    required_files: Iterable[str],
) -> tuple[Path, ...]:
    """Return matching completed runs ordered by recorded completion and path."""
    root = Path(workspace_root).resolve()
    runs = root / "runs"
    required = _required_names(required_files)
    if runs.is_symlink() or not runs.is_dir():
        return ()
    try:
        resolved_runs = runs.resolve(strict=True)
        resolved_runs.relative_to(root)
    except (OSError, ValueError):
        return ()

    aliases = spec_identity_aliases(spec_id)
    candidates: set[Path] = set()
    try:
        children = sorted(runs.iterdir(), key=lambda path: path.name)
    except OSError:
        return ()
    for child in children:
        candidates.add(child)
        nested_root = child / "verify-spec"
        for alias in aliases:
            candidates.add(nested_root / alias)

    accepted: list[tuple[datetime, str, Path]] = []
    for candidate in candidates:
        completion = _matching_completion(
            candidate,
            resolved_runs=resolved_runs,
            aliases=aliases,
            required=required,
        )
        if completion is not None:
            accepted.append((completion, candidate.as_posix(), candidate))
    accepted.sort(key=lambda item: (item[0], item[1]))
    return tuple(item[2] for item in accepted)


def verify_evidence_run_sort_key(run_dir: Path) -> tuple[datetime, str]:
    """Return the already-validated recorded completion ordering for a run."""
    state_path = Path(run_dir) / "state.json"
    if state_path.is_symlink() or not state_path.is_file():
        raise ValueError("verify evidence state is not a regular file")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("verify evidence state is malformed") from exc
    completed_at = state.get("completed_at") if isinstance(state, dict) else None
    parsed = _parse_completed_at(completed_at)
    if parsed is None:
        raise ValueError("verify evidence completion time is malformed")
    return (parsed, Path(run_dir).as_posix())


def _required_names(values: Iterable[str]) -> tuple[str, ...]:
    names = tuple(sorted(set(values)))
    if not names or any(
        not isinstance(name, str)
        or not name
        or Path(name).name != name
        or name in {".", ".."}
        for name in names
    ):
        raise ValueError("required verify evidence files must be safe basenames")
    return names


def _matching_completion(
    candidate: Path,
    *,
    resolved_runs: Path,
    aliases: tuple[str, ...],
    required: tuple[str, ...],
) -> datetime | None:
    if candidate.is_symlink() or not candidate.is_dir():
        return None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_runs)
        current = candidate
        while current != resolved_runs:
            if current.is_symlink():
                return None
            current = current.parent
    except (OSError, ValueError):
        return None
    required_paths = [candidate / name for name in required]
    state_path = candidate / "state.json"
    if state_path.is_symlink() or any(
        path.is_symlink() or not path.is_file() for path in required_paths
    ):
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict):
        return None
    if state.get("status") != "complete":
        return None
    state_spec_id = state.get("spec_id")
    if not isinstance(state_spec_id, str) or not (
        set(spec_identity_aliases(state_spec_id)) & set(aliases)
    ):
        return None
    return _parse_completed_at(state.get("completed_at"))


def _parse_completed_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)
