"""Deterministic deliverable-file inventory for verify-spec evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess


SCHEMA_VERSION = 1
CONTROL_ROOTS = frozenset({".echelon", ".git"})
CONTROL_PATHS = frozenset({".harness-build-status.json"})
FINGERPRINT_IGNORED_PARTS = frozenset({"__pycache__", ".pytest_cache"})


@dataclass(frozen=True)
class ProductInventoryResult:
    json_path: Path
    markdown_path: Path
    entry_count: int
    inventory_source: str


def product_evidence_fingerprint(project_root: Path) -> str:
    """Return a stable digest of the bounded product evidence set."""
    root = project_root.expanduser().resolve(strict=True)
    relative_paths, _inventory_source = _inventory_paths(root)
    entries = [
        _entry(root, relative)
        for relative in relative_paths
        if not _fingerprint_ignored(relative)
    ]
    canonical = [
        {
            "path": entry["path"],
            "kind": entry["kind"],
            "executable": entry["executable"],
            "sha256": entry["sha256"],
        }
        for entry in entries
    ]
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _fingerprint_ignored(path: PurePosixPath) -> bool:
    return bool(
        FINGERPRINT_IGNORED_PARTS.intersection(path.parts)
        or path.suffix in {".pyc", ".pyo"}
    )


def write_product_inventory(
    project_root: Path,
    verify_run_dir: Path,
) -> ProductInventoryResult:
    """Write a bounded inventory of product-deliverable files."""
    root = project_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"product inventory root is not a directory: {root}")

    relative_paths, inventory_source = _inventory_paths(root)
    entries = [_entry(root, relative) for relative in relative_paths]
    basename_counts = Counter(PurePosixPath(entry["path"]).name for entry in entries)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "project_root": str(root),
        "inventory_source": inventory_source,
        "excluded_control_roots": sorted(CONTROL_ROOTS),
        "excluded_control_paths": sorted(CONTROL_PATHS),
        "summary": {
            "entry_count": len(entries),
            "regular_file_count": sum(entry["kind"] == "file" for entry in entries),
            "symlink_count": sum(entry["kind"] == "symlink" for entry in entries),
        },
        "basename_counts": dict(sorted(basename_counts.items())),
        "entries": entries,
    }

    verify_run_dir.mkdir(parents=True, exist_ok=True)
    json_path = verify_run_dir / "product-inventory.json"
    markdown_path = verify_run_dir / "product-inventory.md"
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    return ProductInventoryResult(
        json_path=json_path,
        markdown_path=markdown_path,
        entry_count=len(entries),
        inventory_source=inventory_source,
    )


def _inventory_paths(root: Path) -> tuple[list[PurePosixPath], str]:
    git_paths = _git_deliverable_paths(root)
    if git_paths is not None:
        return _bounded_paths(git_paths), "git-deliverable"
    return _bounded_paths(_filesystem_paths(root)), "filesystem-fallback"


def _git_deliverable_paths(root: Path) -> list[PurePosixPath] | None:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [
        PurePosixPath(raw.decode("utf-8", errors="surrogateescape"))
        for raw in result.stdout.split(b"\0")
        if raw
    ]


def _filesystem_paths(root: Path) -> list[PurePosixPath]:
    paths: list[PurePosixPath] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        relative_dir = current_path.relative_to(root)
        dirnames[:] = sorted(name for name in dirnames if name not in CONTROL_ROOTS)
        for filename in sorted(filenames):
            relative = relative_dir / filename
            paths.append(PurePosixPath(relative.as_posix()))
    return paths


def _bounded_paths(paths: list[PurePosixPath]) -> list[PurePosixPath]:
    bounded: set[PurePosixPath] = set()
    for path in paths:
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"product inventory path escapes project root: {path}")
        if (
            not path.parts
            or path.parts[0] in CONTROL_ROOTS
            or path.as_posix() in CONTROL_PATHS
        ):
            continue
        bounded.add(path)
    return sorted(bounded, key=lambda item: item.as_posix())


def _entry(root: Path, relative: PurePosixPath) -> dict[str, object]:
    path = root.joinpath(*relative.parts)
    metadata = path.lstat()
    executable = bool(metadata.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    if path.is_symlink():
        target = os.readlink(path)
        encoded_target = os.fsencode(target)
        digest = hashlib.sha256(encoded_target).hexdigest()
        return {
            "path": relative.as_posix(),
            "kind": "symlink",
            "size": len(encoded_target),
            "executable": executable,
            "sha256": digest,
            "link_target": target,
        }
    if not path.is_file():
        raise ValueError(f"product inventory entry is not a regular file: {relative}")
    return {
        "path": relative.as_posix(),
        "kind": "file",
        "size": metadata.st_size,
        "executable": executable,
        "sha256": _sha256(path),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render_markdown(payload: dict[str, object]) -> str:
    summary = payload["summary"]
    assert isinstance(summary, dict)
    entries = payload["entries"]
    assert isinstance(entries, list)
    lines = [
        "# Product Inventory",
        "",
        f"- Schema version: {payload['schema_version']}",
        f"- Inventory source: `{payload['inventory_source']}`",
        f"- Product root: `{payload['project_root']}`",
        "- Excluded control roots: "
        + ", ".join(f"`{root}`" for root in payload["excluded_control_roots"]),
        "- Excluded control paths: "
        + ", ".join(f"`{path}`" for path in payload["excluded_control_paths"]),
        f"- Entry count: {summary['entry_count']}",
        "",
        "| Path | Kind | Bytes | Executable | SHA-256 |",
        "|---|---|---:|---|---|",
    ]
    for entry in entries:
        assert isinstance(entry, dict)
        lines.append(
            "| "
            f"`{entry['path']}` | {entry['kind']} | {entry['size']} | "
            f"{'yes' if entry['executable'] else 'no'} | `{entry['sha256']}` |"
        )
    lines.append("")
    return "\n".join(lines)
