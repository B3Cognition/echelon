"""Python-owned verify-spec run initialization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable


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
        active_run = runs_dir / run_id if run_id else None
        if active_run is not None and active_run.is_dir():
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
