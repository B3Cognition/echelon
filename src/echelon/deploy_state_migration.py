"""Migrate legacy deployment metadata into Echelon-owned user storage."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


class DeployStateMigrationError(RuntimeError):
    """Raised when deployment metadata cannot be migrated safely."""


@dataclass(frozen=True)
class DeployStateMigrationReport:
    migrated: bool
    global_state_path: Path | None = None
    local_state_path: Path | None = None
    wrapper_path: Path | None = None


def migrate_legacy_deploy_state(
    project_root: Path,
    *,
    home: Path | None = None,
) -> DeployStateMigrationReport:
    """Move one project's legacy deploy state without renaming live resources."""
    project_root = project_root.resolve()
    home = (home or Path.home()).resolve()
    app = re.sub(r"[^a-z0-9_-]", "", project_root.name.lower())
    if not app:
        raise DeployStateMigrationError(
            f"project directory {project_root.name!r} has no deployable app name"
        )
    legacy_global = home / ".speckit-deploy" / f"{app}.json"
    local_state = _local_state_path(project_root)
    if not legacy_global.is_file():
        return DeployStateMigrationReport(False, local_state_path=local_state)

    state = _read_state(legacy_global)
    state_app = str(state.get("app") or "")
    if state_app != app:
        raise DeployStateMigrationError(
            f"legacy deploy state app {state_app!r} does not match project {app!r}"
        )

    destination = home / ".echelon" / "deploy" / f"{app}.json"
    migrated_state = dict(state)
    migrated_state["global_state_dir"] = str(destination.parent)
    if destination.is_file() and _read_state(destination) != migrated_state:
        raise DeployStateMigrationError(
            f"Echelon deploy state already exists with different content: {destination}"
        )

    _write_state(destination, migrated_state)
    if local_state is not None:
        _write_state(local_state, migrated_state)
    wrapper = _repoint_wrapper(
        migrated_state,
        app=app,
        home=home,
        previous=legacy_global,
        current=destination,
    )
    legacy_global.unlink()
    return DeployStateMigrationReport(
        True,
        global_state_path=destination,
        local_state_path=local_state,
        wrapper_path=wrapper,
    )


def _local_state_path(project_root: Path) -> Path | None:
    current = project_root / "runs" / ".current"
    if current.is_file():
        run_id = current.read_text(encoding="utf-8").strip()
        candidate = project_root / "runs" / run_id / "deploy-state.json"
        if run_id and candidate.is_file():
            return candidate
    direct = project_root / "runs" / "deploy-state.json"
    return direct if direct.is_file() else None


def _read_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeployStateMigrationError(f"cannot read deploy state {path}: {exc}") from exc
    if not isinstance(state, dict):
        raise DeployStateMigrationError(f"deploy state {path} must be a JSON object")
    return state


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.migrating")
    staging.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    staging.replace(path)


def _repoint_wrapper(
    state: dict[str, Any],
    *,
    app: str,
    home: Path,
    previous: Path,
    current: Path,
) -> Path | None:
    raw_install_path = str(state.get("install_path") or "").strip()
    if not raw_install_path:
        return None
    install_path = (
        home / raw_install_path[2:]
        if raw_install_path.startswith("~/")
        else Path(raw_install_path)
    )
    wrapper = install_path / app
    if not wrapper.is_file():
        return None
    text = wrapper.read_text(encoding="utf-8")
    legacy_reference = str(previous)
    if legacy_reference not in text:
        return None
    wrapper.write_text(text.replace(legacy_reference, str(current)), encoding="utf-8")
    return wrapper
