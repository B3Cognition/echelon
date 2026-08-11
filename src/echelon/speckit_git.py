"""Exclusive Git ownership boundary between Echelon and spec-kit."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile

import yaml


class SpecKitGitOwnershipError(RuntimeError):
    """Raised when spec-kit can still mutate Echelon-owned Git state."""


@dataclass(frozen=True)
class SpecKitGitState:
    """Observed project-local state of the spec-kit Git extension and hooks."""

    safe: bool
    installed: bool
    registry_enabled: bool | None
    enabled_hooks: tuple[str, ...]
    reason: str


def _malformed_state(
    *,
    installed: bool,
    registry_enabled: bool | None,
    enabled_hooks: list[str],
    reason: str,
) -> SpecKitGitState:
    return SpecKitGitState(
        safe=False,
        installed=installed,
        registry_enabled=registry_enabled,
        enabled_hooks=tuple(enabled_hooks),
        reason=f"malformed spec-kit extension state: {reason}",
    )


def inspect_speckit_git(project_root: Path) -> SpecKitGitState:
    """Inspect whether spec-kit Git integration is fully disabled.

    Both the extension registry and executable hook configuration are checked.
    Missing Git integration is safe; malformed or inconsistent state fails closed.
    """

    root = Path(project_root).resolve()
    registry_path = root / ".specify" / "extensions" / ".registry"
    hooks_path = root / ".specify" / "extensions.yml"
    installed = False
    registry_enabled: bool | None = None
    enabled_hooks: list[str] = []
    declared_installed = False

    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return _malformed_state(
                installed=False,
                registry_enabled=None,
                enabled_hooks=[],
                reason=f"cannot read {registry_path}: {exc}",
            )
        if not isinstance(registry, dict) or not isinstance(registry.get("extensions", {}), dict):
            return _malformed_state(
                installed=False,
                registry_enabled=None,
                enabled_hooks=[],
                reason=f"{registry_path} must contain an extensions mapping",
            )
        entry = registry.get("extensions", {}).get("git")
        if entry is not None:
            if not isinstance(entry, dict):
                return _malformed_state(
                    installed=True,
                    registry_enabled=None,
                    enabled_hooks=[],
                    reason=f"{registry_path} has an invalid git entry",
                )
            enabled = entry.get("enabled", True)
            if not isinstance(enabled, bool):
                return _malformed_state(
                    installed=True,
                    registry_enabled=None,
                    enabled_hooks=[],
                    reason=f"{registry_path} git.enabled must be boolean",
                )
            installed = True
            registry_enabled = enabled

    if hooks_path.exists():
        try:
            config = yaml.safe_load(hooks_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            return _malformed_state(
                installed=installed,
                registry_enabled=registry_enabled,
                enabled_hooks=enabled_hooks,
                reason=f"cannot read {hooks_path}: {exc}",
            )
        if not isinstance(config, dict):
            return _malformed_state(
                installed=installed,
                registry_enabled=registry_enabled,
                enabled_hooks=enabled_hooks,
                reason=f"{hooks_path} must contain a mapping",
            )
        installed_entries = config.get("installed", []) or []
        if not isinstance(installed_entries, list):
            return _malformed_state(
                installed=installed,
                registry_enabled=registry_enabled,
                enabled_hooks=enabled_hooks,
                reason=f"{hooks_path} installed must be a list",
            )
        declared_installed = "git" in installed_entries
        hooks = config.get("hooks", {}) or {}
        if not isinstance(hooks, dict):
            return _malformed_state(
                installed=installed or declared_installed,
                registry_enabled=registry_enabled,
                enabled_hooks=enabled_hooks,
                reason=f"{hooks_path} hooks must be a mapping",
            )
        for event, entries in hooks.items():
            if not isinstance(entries, list):
                return _malformed_state(
                    installed=installed or declared_installed,
                    registry_enabled=registry_enabled,
                    enabled_hooks=enabled_hooks,
                    reason=f"{hooks_path} hook event {event!r} must be a list",
                )
            for hook in entries:
                if not isinstance(hook, dict):
                    return _malformed_state(
                        installed=installed or declared_installed,
                        registry_enabled=registry_enabled,
                        enabled_hooks=enabled_hooks,
                        reason=f"{hooks_path} hook event {event!r} contains a non-mapping entry",
                    )
                if hook.get("extension") != "git":
                    continue
                hook_enabled = hook.get("enabled", True)
                if not isinstance(hook_enabled, bool):
                    return _malformed_state(
                        installed=True,
                        registry_enabled=registry_enabled,
                        enabled_hooks=enabled_hooks,
                        reason=f"{hooks_path} Git hook enabled flag must be boolean",
                    )
                if hook_enabled:
                    command = str(hook.get("command") or "<unknown>")
                    enabled_hooks.append(f"{event}:{command}")

    installed = installed or declared_installed
    if installed and registry_enabled is None:
        return SpecKitGitState(
            safe=False,
            installed=True,
            registry_enabled=None,
            enabled_hooks=tuple(enabled_hooks),
            reason="spec-kit Git is declared installed but missing from the extension registry",
        )
    if registry_enabled is True:
        return SpecKitGitState(
            safe=False,
            installed=installed,
            registry_enabled=True,
            enabled_hooks=tuple(enabled_hooks),
            reason="spec-kit Git extension is enabled",
        )
    if enabled_hooks:
        return SpecKitGitState(
            safe=False,
            installed=installed,
            registry_enabled=registry_enabled,
            enabled_hooks=tuple(enabled_hooks),
            reason="enabled Git hook remains configured: " + ", ".join(enabled_hooks),
        )
    return SpecKitGitState(
        safe=True,
        installed=installed,
        registry_enabled=registry_enabled,
        enabled_hooks=(),
        reason=(
            "spec-kit Git extension is disabled"
            if installed
            else "spec-kit Git extension is not installed"
        ),
    )


def require_speckit_git_disabled(project_root: Path) -> SpecKitGitState:
    """Return safe state or fail with an actionable exclusive-ownership error."""

    state = inspect_speckit_git(project_root)
    if state.safe:
        return state
    raise SpecKitGitOwnershipError(
        f"{state.reason}. Echelon must be the sole Git authority. "
        "Repair the malformed legacy extension state before migration."
    )


def _atomic_write_text(path: Path, text: str) -> None:
    """Replace one legacy state file without exposing a partial write."""

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.chmod(path.stat().st_mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def disable_speckit_git(
    project_root: Path,
) -> SpecKitGitState:
    """Idempotently neutralize legacy Git integration and verify it."""

    root = Path(project_root).resolve()
    before = inspect_speckit_git(root)
    if before.safe:
        return before
    if not before.installed or before.reason.startswith("malformed"):
        return require_speckit_git_disabled(root)

    registry_path = root / ".specify" / "extensions" / ".registry"
    hooks_path = root / ".specify" / "extensions.yml"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        git_entry = registry["extensions"]["git"]
        if git_entry.get("enabled", True):
            git_entry["enabled"] = False
            _atomic_write_text(
                registry_path,
                json.dumps(registry, indent=2) + "\n",
            )

        if hooks_path.exists():
            hooks_config = yaml.safe_load(hooks_path.read_text(encoding="utf-8")) or {}
            hooks_changed = False
            for entries in (hooks_config.get("hooks", {}) or {}).values():
                for hook in entries:
                    if hook.get("extension") == "git" and hook.get("enabled", True):
                        hook["enabled"] = False
                        hooks_changed = True
            if hooks_changed:
                _atomic_write_text(
                    hooks_path,
                    yaml.safe_dump(hooks_config, sort_keys=False),
                )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SpecKitGitOwnershipError(
            f"legacy Git integration could not be neutralized: {exc}"
        ) from exc

    after = inspect_speckit_git(root)
    if not after.safe:
        raise SpecKitGitOwnershipError(
            f"legacy Git integration remains enabled or unsafe after neutralization: {after.reason}"
        )
    return after
