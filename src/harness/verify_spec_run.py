"""Python-owned verify-spec run initialization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable

from harness.durable_json import DurableJsonError, write_json_atomic


@dataclass(frozen=True)
class VerifySpecRunInitResult:
    project_root: Path
    orchestration_root: Path
    spec_dir: Path
    verify_run_dir: Path
    state_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "project_root": str(self.project_root),
            "orchestration_root": str(self.orchestration_root),
            "spec_dir": str(self.spec_dir),
            "verify_run_dir": str(self.verify_run_dir),
            "state_path": str(self.state_path),
        }


class VerifySpecRunInitError(ValueError):
    """Raised when verify-spec run initialization inputs are invalid."""


def complete_verify_spec_run(
    verify_run_dir: Path,
    *,
    completed_at: str | None = None,
) -> Path:
    """Durably mark a fully validated verify-spec lifecycle complete."""
    run_dir = Path(verify_run_dir)
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise VerifySpecRunInitError("verify run directory is unavailable or symlinked")
    state_path = run_dir / "state.json"
    if state_path.is_symlink() or not state_path.is_file():
        raise VerifySpecRunInitError("verify state is unavailable or symlinked")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifySpecRunInitError("verify state is malformed") from exc
    if not isinstance(state, dict):
        raise VerifySpecRunInitError("verify state must be a JSON object")
    if state.get("status") == "complete":
        if _completion_time(state.get("completed_at")) is None:
            raise VerifySpecRunInitError("completed verify state has no valid completed_at")
        return state_path
    if state.get("status") != "in_progress":
        raise VerifySpecRunInitError("verify state is not in progress")
    if state.get("topology_evidence") not in {"ready", "degraded", "unavailable"}:
        raise VerifySpecRunInitError("verify topology evidence is not finalized")
    if state.get("fulfillment_artifacts") != "valid":
        raise VerifySpecRunInitError("verify fulfillment artifacts are not valid")
    if state.get("reconcile") is True and state.get("progress_reconciliation") not in {
        "applied",
        "dry_run",
    }:
        raise VerifySpecRunInitError("verify progress reconciliation is not finalized")
    timestamp = completed_at or datetime.now(timezone.utc).isoformat()
    if _completion_time(timestamp) is None:
        raise VerifySpecRunInitError("verify completion timestamp is invalid")
    state.update({"status": "complete", "completed_at": timestamp})
    try:
        write_json_atomic(state_path, state)
    except DurableJsonError as exc:
        raise VerifySpecRunInitError(str(exc)) from exc
    return state_path


def _completion_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def init_verify_spec_run(
    *,
    project_root: Path,
    spec_id: str,
    spec_dir: Path,
    verify_scope: str = "full",
    scoped_ids: Iterable[str] | None = None,
    base_full_verify_commit: str | None = None,
    strict: bool = False,
    reconcile: bool = False,
    dry_run: bool = False,
    timestamp: str | None = None,
) -> VerifySpecRunInitResult:
    project_root = project_root.resolve()
    spec_dir = spec_dir.resolve()
    if not project_root.is_dir():
        raise VerifySpecRunInitError(f"project_root does not exist: {project_root}")
    if not spec_dir.is_dir():
        raise VerifySpecRunInitError(f"spec_dir does not exist: {spec_dir}")
    if not (spec_dir / "spec.md").is_file():
        raise VerifySpecRunInitError(f"spec.md missing in spec_dir: {spec_dir}")
    _require_safe_label("spec_id", spec_id)
    if verify_scope not in {"full", "scoped"}:
        raise VerifySpecRunInitError(f"unsupported verify scope: {verify_scope}")
    scoped_ids = _stable_unique(scoped_ids or [])
    if verify_scope == "scoped" and not scoped_ids:
        raise VerifySpecRunInitError("scoped verify requires at least one scoped id")
    if verify_scope == "full" and scoped_ids:
        raise VerifySpecRunInitError("scoped ids require --scope scoped")
    if verify_scope == "full" and base_full_verify_commit:
        raise VerifySpecRunInitError(
            "base full verify commit requires --scope scoped"
        )
    if timestamp is not None:
        _require_safe_label("timestamp", timestamp)
    orchestration_root = _derive_orchestration_root(project_root, spec_dir)
    verify_run_dir = _resolve_verify_run_dir(
        orchestration_root=orchestration_root,
        spec_id=spec_id,
        timestamp=timestamp,
    )
    _require_verify_run_contained(verify_run_dir, orchestration_root=orchestration_root)
    verify_run_dir.mkdir(parents=True, exist_ok=True)

    state = {
        "spec_id": spec_id,
        "project_root": str(project_root),
        "orchestration_root": str(orchestration_root),
        "spec_dir": str(spec_dir),
        "strict": bool(strict),
        "reconcile": bool(reconcile),
        "dry_run": bool(dry_run),
        "verify_scope": verify_scope,
        "scoped_ids": scoped_ids,
        "base_full_verify_commit": base_full_verify_commit or "",
        "verify_run_dir": str(verify_run_dir),
        "status": "in_progress",
        "structural_evidence": "pending",
    }
    state_path = verify_run_dir / "state.json"
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return VerifySpecRunInitResult(
        project_root=project_root,
        orchestration_root=orchestration_root,
        spec_dir=spec_dir,
        verify_run_dir=verify_run_dir,
        state_path=state_path,
    )


def _derive_orchestration_root(project_root: Path, spec_dir: Path) -> Path:
    if spec_dir.parent.name == "specs":
        return spec_dir.parent.parent.resolve()
    return project_root


def _resolve_verify_run_dir(
    *,
    orchestration_root: Path,
    spec_id: str,
    timestamp: str | None,
) -> Path:
    runs_dir = orchestration_root / "runs"
    current_path = runs_dir / ".current"
    if current_path.is_file():
        run_id = current_path.read_text(encoding="utf-8", errors="replace").strip()
        if not run_id:
            raise VerifySpecRunInitError(f"empty current run id: {current_path}")
        if run_id:
            _require_safe_label("current run id", run_id)
        active_run = runs_dir / run_id if run_id else None
        if active_run is not None and not active_run.exists():
            raise VerifySpecRunInitError(f"current run directory missing: {active_run}")
        if active_run is not None and not active_run.is_dir():
            raise VerifySpecRunInitError(f"current run path is not a directory: {active_run}")
        if active_run is not None:
            _require_child_path(
                "current run path",
                child=active_run.resolve(),
                parent=runs_dir.resolve(),
            )
            return active_run / "verify-spec" / spec_id
    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return runs_dir / f"verify-spec-{spec_id}-{stamp}"


def _stable_unique(values: Iterable[str]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _require_safe_label(name: str, value: str) -> None:
    stripped = str(value).strip()
    if (
        not stripped
        or "/" in stripped
        or "\\" in stripped
        or stripped in {".", ".."}
        or ".." in Path(stripped).parts
    ):
        raise VerifySpecRunInitError(f"unsafe {name}: {value}")


def _require_child_path(name: str, *, child: Path, parent: Path) -> None:
    try:
        child.relative_to(parent)
    except ValueError as exc:
        raise VerifySpecRunInitError(f"unsafe {name}: {child}") from exc


def _require_verify_run_contained(
    verify_run_dir: Path, *, orchestration_root: Path
) -> None:
    runs_dir = (orchestration_root / "runs").resolve()
    if verify_run_dir.exists():
        resolved = verify_run_dir.resolve()
        _require_child_path("verify run path", child=resolved, parent=runs_dir)
