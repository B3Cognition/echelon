"""Immutable, content-addressed source snapshots for RE v2."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .canonical import canonical_json_bytes, content_digest


_CAPTURE_VERSION = 1
_MANIFEST_NAME = "manifest.json"


class ReV2SnapshotError(RuntimeError):
    """Raised when a source cannot be frozen or a snapshot is no longer valid."""


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    """One regular file in a frozen source tree."""

    path: str
    digest: str
    mode: int
    size: int

    def to_json_dict(self) -> dict[str, object]:
        return {"digest": self.digest, "mode": self.mode, "path": self.path, "size": self.size}


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    """Canonical, independently verifiable snapshot metadata."""

    snapshot_id: str
    kind: Literal["git-worktree", "content-snapshot"]
    entries: tuple[SnapshotEntry, ...]
    exclusions: tuple[str, ...]
    git: dict[str, object] | None
    capture_version: int = _CAPTURE_VERSION

    def identity_dict(self) -> dict[str, object]:
        return {
            "capture_version": self.capture_version,
            "entries": [entry.to_json_dict() for entry in self.entries],
            "exclusions": list(self.exclusions),
            "git": self.git,
            "kind": self.kind,
        }

    def to_json_dict(self) -> dict[str, object]:
        return {"snapshot_id": self.snapshot_id, **self.identity_dict()}


@dataclass(frozen=True, slots=True)
class CapturedSnapshot:
    snapshot_id: str
    kind: Literal["git-worktree", "content-snapshot"]
    read_root: Path
    manifest_path: Path


def run_git(args: list[str]) -> str:
    """Run Git; a module-level seam keeps snapshot tests configuration-free."""
    completed = subprocess.run(
        ["git", *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    return completed.stdout


def capture_source_snapshot(
    source_root: Path, destination_root: Path, *, exclusions: tuple[str, ...]
) -> CapturedSnapshot:
    """Freeze a source tree without ever changing or deleting that source."""
    source_root = _safe_source_root(source_root)
    destination_root = _safe_destination_root(destination_root)
    normalized_exclusions = _normalize_exclusions(exclusions)

    git_commit = _clean_git_commit(source_root)
    if git_commit is None:
        return _capture_copy(source_root, destination_root, normalized_exclusions)
    return _capture_git_worktree(source_root, destination_root, normalized_exclusions, git_commit)


def validate_source_snapshot(snapshot: CapturedSnapshot) -> None:
    """Fail closed if the manifest, tree shape, or any frozen bytes changed."""
    if snapshot.read_root.is_symlink() or snapshot.manifest_path.is_symlink():
        raise ReV2SnapshotError("unsafe symlink in source snapshot")
    try:
        raw = __import__("json").loads(snapshot.manifest_path.read_bytes())
        manifest = _manifest_from_json(raw)
    except (OSError, ValueError, TypeError) as exc:
        raise ReV2SnapshotError(f"invalid snapshot manifest: {exc}") from exc
    if manifest.snapshot_id != snapshot.snapshot_id or manifest.kind != snapshot.kind:
        raise ReV2SnapshotError("snapshot handle does not match manifest")
    if content_digest(manifest.identity_dict()) != manifest.snapshot_id:
        raise ReV2SnapshotError("snapshot manifest content address mismatch")
    actual = _inventory(snapshot.read_root, manifest.exclusions)
    expected = {entry.path: entry for entry in manifest.entries}
    found = {entry.path: entry for entry in actual}
    missing = sorted(expected.keys() - found.keys())
    extra = sorted(found.keys() - expected.keys())
    if missing:
        raise ReV2SnapshotError(f"snapshot missing file: {missing[0]}")
    if extra:
        raise ReV2SnapshotError(f"snapshot has extra file: {extra[0]}")
    for path, entry in expected.items():
        actual_entry = found[path]
        if actual_entry.digest != entry.digest:
            raise ReV2SnapshotError(f"snapshot hash mismatch: {path}")
        if actual_entry.size != entry.size:
            raise ReV2SnapshotError(f"snapshot size mismatch: {path}")


def _capture_copy(source: Path, destination: Path, exclusions: tuple[str, ...]) -> CapturedSnapshot:
    entries = _inventory(source, exclusions)
    manifest = _new_manifest("content-snapshot", entries, exclusions, None)
    existing = _existing_snapshot(destination, manifest)
    if existing is not None:
        return existing
    temporary = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=destination))
    try:
        read_root = temporary / "source"
        _copy_regular_files(source, read_root, entries)
        _publish_manifest(temporary / _MANIFEST_NAME, manifest)
        captured = _publish_bundle(temporary, destination, manifest, read_root)
        temporary = None  # ownership moved to the published snapshot
        return captured
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)


def _capture_git_worktree(
    source: Path, destination: Path, exclusions: tuple[str, ...], commit: str
) -> CapturedSnapshot:
    temporary = Path(tempfile.mkdtemp(prefix=".git-snapshot-", dir=destination))
    worktree = temporary / "source"
    registered_worktree: Path | None = None
    published = False
    try:
        run_git(["-C", str(source), "worktree", "add", "--detach", str(worktree), commit])
        registered_worktree = worktree
        entries = _inventory(worktree, exclusions)
        git = {"commit": commit, "submodules": _submodule_identities(source)}
        manifest = _new_manifest("git-worktree", entries, exclusions, git)
        existing = _existing_snapshot(destination, manifest)
        if existing is not None:
            return existing
        final_bundle = destination / manifest.snapshot_id
        final_worktree = final_bundle / "source"
        final_bundle.mkdir(mode=0o700)
        try:
            run_git(["-C", str(source), "worktree", "move", str(worktree), str(final_worktree)])
        except Exception:
            final_bundle.rmdir()
            raise
        registered_worktree = final_worktree
        _publish_manifest(final_bundle / _MANIFEST_NAME, manifest)
        _make_read_only(final_worktree)
        _make_read_only(final_bundle)
        captured = CapturedSnapshot(manifest.snapshot_id, manifest.kind, final_worktree, final_bundle / _MANIFEST_NAME)
        published = True
        return captured
    finally:
        if registered_worktree is not None and not published:
            try:
                run_git(["-C", str(source), "worktree", "remove", "--force", str(registered_worktree)])
            except Exception:
                pass
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def _publish_bundle(temporary: Path, destination: Path, manifest: SnapshotManifest, read_root: Path) -> CapturedSnapshot:
    final = destination / manifest.snapshot_id
    try:
        os.rename(temporary, final)
    except FileExistsError:
        existing = _existing_snapshot(destination, manifest)
        if existing is not None:
            return existing
        raise ReV2SnapshotError(f"snapshot ID already exists: {manifest.snapshot_id}")
    _make_read_only(final / "source")
    _make_read_only(final)
    return CapturedSnapshot(manifest.snapshot_id, manifest.kind, final / "source", final / _MANIFEST_NAME)


def _existing_snapshot(destination: Path, manifest: SnapshotManifest) -> CapturedSnapshot | None:
    bundle = destination / manifest.snapshot_id
    if not bundle.exists():
        return None
    if bundle.is_symlink() or not bundle.is_dir():
        raise ReV2SnapshotError(f"snapshot ID already exists: {manifest.snapshot_id}")
    captured = CapturedSnapshot(manifest.snapshot_id, manifest.kind, bundle / "source", bundle / _MANIFEST_NAME)
    try:
        validate_source_snapshot(captured)
    except ReV2SnapshotError as exc:
        raise ReV2SnapshotError(f"snapshot ID already exists and is invalid: {manifest.snapshot_id}: {exc}") from exc
    return captured


def _new_manifest(kind: Literal["git-worktree", "content-snapshot"], entries: tuple[SnapshotEntry, ...], exclusions: tuple[str, ...], git: dict[str, object] | None) -> SnapshotManifest:
    partial = SnapshotManifest("", kind, entries, exclusions, git)
    return SnapshotManifest(content_digest(partial.identity_dict()), kind, entries, exclusions, git)


def _safe_source_root(source: Path) -> Path:
    if source.is_symlink() or not source.is_dir():
        raise ReV2SnapshotError(f"source root is not a safe directory: {source}")
    return source.resolve()


def _safe_destination_root(destination: Path) -> Path:
    if destination.is_symlink():
        raise ReV2SnapshotError(f"destination root is symlinked: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir():
        raise ReV2SnapshotError(f"destination root is not a directory: {destination}")
    return destination.resolve()


def _normalize_exclusions(exclusions: tuple[str, ...]) -> tuple[str, ...]:
    values = set()
    for exclusion in exclusions:
        path = Path(exclusion)
        raw_parts = exclusion.split("/")
        if not exclusion or path.is_absolute() or any(part in {"", ".", ".."} for part in raw_parts):
            raise ReV2SnapshotError(f"unsafe exclusion path: {exclusion!r}")
        values.add(path.as_posix())
    values.add(".git")
    return tuple(sorted(values))


def _is_excluded(relative: str, exclusions: tuple[str, ...]) -> bool:
    return any(relative == excluded or relative.startswith(excluded + "/") for excluded in exclusions)


def _inventory(root: Path, exclusions: tuple[str, ...]) -> tuple[SnapshotEntry, ...]:
    entries: list[SnapshotEntry] = []

    def visit(directory: Path, prefix: str = "") -> None:
        for child in sorted(directory.iterdir(), key=lambda item: item.name):
            relative = f"{prefix}/{child.name}" if prefix else child.name
            if _is_excluded(relative, exclusions):
                continue
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ReV2SnapshotError(f"source snapshot rejects symlink: {relative}")
            if stat.S_ISDIR(info.st_mode):
                visit(child, relative)
            elif stat.S_ISREG(info.st_mode):
                payload = child.read_bytes()
                entries.append(SnapshotEntry(relative, content_digest(payload), stat.S_IMODE(info.st_mode), len(payload)))
            else:
                raise ReV2SnapshotError(f"source snapshot rejects special file: {relative}")

    visit(root)
    return tuple(entries)


def _copy_regular_files(source: Path, target: Path, entries: tuple[SnapshotEntry, ...]) -> None:
    target.mkdir(mode=0o700)
    for entry in entries:
        destination = target / entry.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_file = source / entry.path
        with source_file.open("rb") as source_handle, destination.open("xb") as destination_handle:
            shutil.copyfileobj(source_handle, destination_handle)
        destination.chmod(entry.mode)


def _publish_manifest(path: Path, manifest: SnapshotManifest) -> None:
    path.write_bytes(canonical_json_bytes(manifest.to_json_dict()))


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            raise ReV2SnapshotError(f"source snapshot rejects symlink: {path}")
        mode = path.stat().st_mode
        path.chmod(stat.S_IMODE(mode) & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    root.chmod(stat.S_IMODE(root.stat().st_mode) & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _clean_git_commit(source: Path) -> str | None:
    try:
        commit = run_git(["-C", str(source), "rev-parse", "HEAD^{commit}"]).strip()
        status = run_git(["-C", str(source), "status", "--porcelain", "--untracked-files=all"])
    except (OSError, subprocess.CalledProcessError):
        return None
    if not commit:
        return None
    return commit if not status.strip() else None


def _submodule_identities(source: Path) -> list[dict[str, str]]:
    output = run_git(["-C", str(source), "submodule", "status", "--recursive"])
    identities: list[dict[str, str]] = []
    for line in output.splitlines():
        text = line.lstrip(" -+U")
        if not text:
            continue
        commit, path, *_ = text.split()
        identities.append({"commit": commit, "path": path})
    return sorted(identities, key=lambda item: item["path"])


def _manifest_from_json(value: object) -> SnapshotManifest:
    if not isinstance(value, dict):
        raise ValueError("manifest must be an object")
    entries_raw = value["entries"]
    if not isinstance(entries_raw, list):
        raise ValueError("manifest entries must be a list")
    entries = tuple(
        SnapshotEntry(item["path"], item["digest"], item["mode"], item["size"])
        for item in entries_raw
    )
    kind = value["kind"]
    if kind not in {"git-worktree", "content-snapshot"}:
        raise ValueError("unsupported snapshot kind")
    exclusions = tuple(value["exclusions"])
    return SnapshotManifest(value["snapshot_id"], kind, entries, exclusions, value.get("git"), value["capture_version"])
