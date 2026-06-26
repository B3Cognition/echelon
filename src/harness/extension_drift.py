"""Detect drift between the source Echelon extension and installed project copy."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path


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


def _file_hashes(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in _iter_shipped_files(root):
        rel = path.relative_to(root).as_posix()
        files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def _iter_shipped_files(root: Path) -> list[Path]:
    paths: list[Path] = []
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
            if path.is_file() and not _ignored(path, root)
        )
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def _ignored(path: Path, root: Path) -> bool:
    rel_parts = path.relative_to(root).parts
    return any(part in IGNORED_NAMES for part in rel_parts)
