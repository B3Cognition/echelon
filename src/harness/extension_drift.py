"""Detect drift between the source Echelon extension and installed project copy."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping


SOURCE_ENV_VAR = "ECHELON_EXTENSION_SOURCE"
SOURCE_MARKER_FILE = ".echelon-source.json"
SHIPPED_DIRS = ("agents", "commands", "workflow", "templates", "scripts", "docs")
SHIPPED_FILES = ("extension.yml", "config-template.yml")
IGNORED_NAMES = {
    ".DS_Store",
    "__pycache__",
    "node_modules",
    ".git",
    "echelon-config.yml",
    "local-config.yml",
}
EXTENSION_IGNORE_FILE = ".extensionignore"


@dataclass(frozen=True)
class ExtensionDriftReport:
    status: str
    source_dir: Path
    installed_dir: Path
    changed_files: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    extra_files: list[str] = field(default_factory=list)

    @property
    def drifted(self) -> bool:
        return self.status == "drifted"


def assess_extension_drift(source_dir: Path, installed_dir: Path) -> ExtensionDriftReport:
    """Compare shipped extension files between source checkout and installed copy.

    Project-local config files are intentionally ignored because installed
    `.specify/extensions/echelon/echelon-config.yml` is user/project state, not
    shipped extension content.
    """
    source_dir = source_dir.resolve()
    installed_dir = installed_dir.resolve()
    if not source_dir.exists():
        return ExtensionDriftReport(
            status="source_missing",
            source_dir=source_dir,
            installed_dir=installed_dir,
        )
    if not installed_dir.exists():
        return ExtensionDriftReport(
            status="installed_missing",
            source_dir=source_dir,
            installed_dir=installed_dir,
        )

    source_files = _file_hashes(source_dir)
    installed_files = _file_hashes(installed_dir)
    source_keys = set(source_files)
    installed_keys = set(installed_files)

    changed = sorted(
        rel for rel in source_keys & installed_keys
        if source_files[rel] != installed_files[rel]
    )
    missing = sorted(source_keys - installed_keys)
    extra = sorted(installed_keys - source_keys)
    status = "drifted" if changed or missing or extra else "in_sync"
    return ExtensionDriftReport(
        status=status,
        source_dir=source_dir,
        installed_dir=installed_dir,
        changed_files=changed,
        missing_files=missing,
        extra_files=extra,
    )


def resolve_extension_source_dir(
    installed_dir: Path,
    *,
    env: Mapping[str, str] | None = None,
    inferred_source_dir: Path | None = None,
) -> Path | None:
    """Resolve a trustworthy source extension path for drift checks.

    Drift detection should never invent a source checkout from an installed
    package path. Explicit operator input wins, then installed metadata, and
    finally an inferred path is accepted only when it looks like this repo's
    editable checkout.
    """
    env = os.environ if env is None else env
    explicit_source = env.get(SOURCE_ENV_VAR)
    if explicit_source:
        return _normalize_source_dir(Path(explicit_source).expanduser())

    marker_source = _source_from_marker(installed_dir / SOURCE_MARKER_FILE)
    if marker_source is not None:
        return marker_source

    if inferred_source_dir is not None and _is_verified_dev_checkout_source(inferred_source_dir):
        return _normalize_source_dir(inferred_source_dir)

    return None


def _file_hashes(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in _iter_shipped_files(root):
        rel = path.relative_to(root).as_posix()
        files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def _iter_shipped_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    extension_ignored_names = _extensionignore_names(root)
    for name in SHIPPED_FILES:
        path = root / name
        if path.is_file():
            paths.append(path)
    for dirname in SHIPPED_DIRS:
        base = root / dirname
        if not base.exists():
            continue
        paths.extend(
            path for path in base.rglob("*")
            if path.is_file() and not _ignored(path, root, extension_ignored_names)
        )
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def _ignored(path: Path, root: Path, extension_ignored_names: set[str]) -> bool:
    rel_parts = path.relative_to(root).parts
    return any(part in IGNORED_NAMES or part in extension_ignored_names for part in rel_parts)


def _extensionignore_names(root: Path) -> set[str]:
    ignore_path = root / EXTENSION_IGNORE_FILE
    if not ignore_path.is_file():
        return set()
    ignored: set[str] = set()
    for raw_line in ignore_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or any(ch in line for ch in "*?[]"):
            continue
        ignored.add(line.strip("/"))
    return ignored


def _source_from_marker(marker_path: Path) -> Path | None:
    if not marker_path.is_file():
        return None
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    for key in ("source_extension_dir", "source_repo_dir"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            source = _normalize_source_dir(Path(value).expanduser())
            if source is not None:
                return source
    return None


def _normalize_source_dir(path: Path) -> Path | None:
    if (path / "extension.yml").is_file():
        return path.resolve()
    extension_dir = path / "extension"
    if (extension_dir / "extension.yml").is_file():
        return extension_dir.resolve()
    return None


def _is_verified_dev_checkout_source(path: Path) -> bool:
    source_dir = _normalize_source_dir(path)
    if source_dir is None:
        return False

    repo_root = source_dir.parent
    return (
        (repo_root / ".git").exists()
        and (repo_root / "pyproject.toml").is_file()
        and (repo_root / "extension" / "extension.yml").is_file()
    )
