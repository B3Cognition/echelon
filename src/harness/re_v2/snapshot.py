"""Immutable, content-addressed source snapshots for RE v2."""
from __future__ import annotations

import json
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
    path: str
    digest: str
    mode: int
    size: int

    def to_json_dict(self) -> dict[str, object]:
        return {"digest": self.digest, "mode": self.mode, "path": self.path, "size": self.size}


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    snapshot_id: str
    kind: Literal["git-worktree", "content-snapshot"]
    entries: tuple[SnapshotEntry, ...]
    exclusions: tuple[str, ...]
    git: dict[str, object] | None
    capture_version: int = _CAPTURE_VERSION

    def identity_dict(self) -> dict[str, object]:
        return {"capture_version": self.capture_version, "entries": [x.to_json_dict() for x in self.entries], "exclusions": list(self.exclusions), "git": self.git, "kind": self.kind}

    def to_json_dict(self) -> dict[str, object]:
        return {"snapshot_id": self.snapshot_id, **self.identity_dict()}


@dataclass(frozen=True, slots=True)
class CapturedSnapshot:
    snapshot_id: str
    kind: Literal["git-worktree", "content-snapshot"]
    read_root: Path
    manifest_path: Path


def run_git(args: list[str]) -> str:
    completed = subprocess.run(["git", *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return completed.stdout


def capture_source_snapshot(source_root: Path, destination_root: Path, *, exclusions: tuple[str, ...]) -> CapturedSnapshot:
    source = _safe_source_root(source_root)
    destination = _safe_destination_root(destination_root, source)
    excluded = _normalize_exclusions(exclusions)
    commit = _clean_git_commit(source)
    if commit is None:
        return _capture_copy(source, destination, excluded)
    return _capture_git_worktree(source, destination, excluded, commit)


def validate_source_snapshot(snapshot: CapturedSnapshot) -> None:
    if snapshot.read_root.is_symlink() or snapshot.manifest_path.is_symlink():
        raise ReV2SnapshotError("unsafe symlink in source snapshot")
    try:
        manifest = _manifest_from_json(json.loads(snapshot.manifest_path.read_bytes()))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ReV2SnapshotError(f"invalid snapshot manifest: {exc}") from exc
    if manifest.snapshot_id != snapshot.snapshot_id or manifest.kind != snapshot.kind:
        raise ReV2SnapshotError("snapshot handle does not match manifest")
    if content_digest(manifest.identity_dict()) != manifest.snapshot_id:
        raise ReV2SnapshotError("snapshot manifest content address mismatch")
    operational_git = manifest.kind == "git-worktree"
    actual = _inventory(snapshot.read_root, (), allow_worktree_git=operational_git)
    expected = {entry.path: entry for entry in manifest.entries}
    found = {entry.path: entry for entry in actual}
    missing, extra = sorted(expected.keys() - found.keys()), sorted(found.keys() - expected.keys())
    if missing:
        raise ReV2SnapshotError(f"snapshot missing file: {missing[0]}")
    if extra:
        raise ReV2SnapshotError(f"snapshot has extra file: {extra[0]}")
    for path, entry in expected.items():
        observed = found[path]
        if observed.digest != entry.digest:
            raise ReV2SnapshotError(f"snapshot hash mismatch: {path}")
        if observed.size != entry.size:
            raise ReV2SnapshotError(f"snapshot size mismatch: {path}")
        if observed.mode != _frozen_mode(entry.mode):
            raise ReV2SnapshotError(f"snapshot mode mismatch: {path}")


def _capture_copy(source: Path, destination: Path, exclusions: tuple[str, ...]) -> CapturedSnapshot:
    entries = _inventory(source, (".git", *exclusions))
    manifest = _new_manifest("content-snapshot", entries, exclusions, None)
    existing = _existing_snapshot(destination, manifest)
    if existing:
        return existing
    temporary = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=destination))
    try:
        staged = temporary / "source"
        _copy_regular_files(source, staged, entries)
        # The staged bytes, not a prior source walk, are what would be published.
        if _inventory(source, (".git", *exclusions)) != entries or _inventory(staged, ()) != entries:
            raise ReV2SnapshotError("source changed while staging snapshot")
        _publish_manifest(temporary / _MANIFEST_NAME, manifest)
        return _publish_copy_bundle(temporary, destination, manifest)
    finally:
        if temporary.exists():
            _remove_tree(temporary)


def _capture_git_worktree(source: Path, destination: Path, exclusions: tuple[str, ...], commit: str) -> CapturedSnapshot:
    temporary = Path(tempfile.mkdtemp(prefix=".git-snapshot-", dir=destination))
    worktree = temporary / "source"
    registered: Path | None = None
    bundle: Path | None = None
    published = False
    try:
        run_git(["-C", str(source), "worktree", "add", "--detach", str(worktree), commit])
        registered = worktree
        entries = _inventory(worktree, exclusions, allow_worktree_git=True)
        manifest = _new_manifest("git-worktree", entries, exclusions, {"commit": commit, "submodules": _submodule_identities(source)})
        existing = _existing_snapshot(destination, manifest)
        if existing:
            return existing
        bundle = _claim_bundle(destination, manifest)
        final_worktree = bundle / "source"
        run_git(["-C", str(source), "worktree", "move", str(worktree), str(final_worktree)])
        registered = final_worktree
        _publish_manifest(bundle / _MANIFEST_NAME, manifest)
        _make_read_only(final_worktree)
        _make_read_only(bundle)
        published = True
        return CapturedSnapshot(manifest.snapshot_id, manifest.kind, final_worktree, bundle / _MANIFEST_NAME)
    except Exception as exc:
        cleanup_error = _cleanup_git_failure(source, registered, bundle)
        registered = None
        if cleanup_error:
            raise ReV2SnapshotError(f"snapshot capture failed: {exc}; cleanup failed: {cleanup_error}") from exc
        if isinstance(exc, ReV2SnapshotError):
            raise
        raise ReV2SnapshotError(f"snapshot capture failed: {exc}") from exc
    finally:
        if registered is not None and not published and not bundle:
            # existing-snapshot reuse path: remove the just-added temporary worktree.
            run_git(["-C", str(source), "worktree", "remove", "--force", str(registered)])
        if temporary.exists():
            _remove_tree(temporary)


def _cleanup_git_failure(source: Path, registered: Path | None, bundle: Path | None) -> Exception | None:
    errors: list[Exception] = []
    if registered is not None:
        try:
            run_git(["-C", str(source), "worktree", "remove", "--force", str(registered)])
        except Exception as exc:  # cleanup is an observable correctness failure
            errors.append(exc)
    if bundle is not None and os.path.lexists(bundle):
        try:
            _remove_tree(bundle)
        except Exception as exc:
            errors.append(exc)
    return errors[0] if errors else None


def _publish_copy_bundle(temporary: Path, destination: Path, manifest: SnapshotManifest) -> CapturedSnapshot:
    bundle = _claim_bundle(destination, manifest)
    try:
        os.rename(temporary / "source", bundle / "source")
        os.link(temporary / _MANIFEST_NAME, bundle / _MANIFEST_NAME)
        _make_read_only(bundle / "source")
        _make_read_only(bundle)
    except Exception:
        _remove_tree(bundle)
        raise
    return CapturedSnapshot(manifest.snapshot_id, manifest.kind, bundle / "source", bundle / _MANIFEST_NAME)


def _claim_bundle(destination: Path, manifest: SnapshotManifest) -> Path:
    bundle = destination / manifest.snapshot_id
    if os.path.lexists(bundle):
        existing = _existing_snapshot(destination, manifest)
        if existing:
            raise ReV2SnapshotError(f"snapshot ID already exists: {manifest.snapshot_id}")
        raise ReV2SnapshotError(f"snapshot ID already exists: {manifest.snapshot_id}")
    try:
        bundle.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ReV2SnapshotError(f"snapshot ID already exists: {manifest.snapshot_id}") from exc
    return bundle


def _existing_snapshot(destination: Path, manifest: SnapshotManifest) -> CapturedSnapshot | None:
    bundle = destination / manifest.snapshot_id
    if not os.path.lexists(bundle):
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


def _safe_destination_root(destination: Path, source: Path) -> Path:
    if destination.is_symlink():
        raise ReV2SnapshotError(f"destination root is symlinked: {destination}")
    resolved = destination.resolve(strict=False)
    if resolved == source or source in resolved.parents:
        raise ReV2SnapshotError("destination root must be outside source root")
    destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir():
        raise ReV2SnapshotError(f"destination root is not a directory: {destination}")
    return destination.resolve()


def _normalize_exclusions(exclusions: tuple[str, ...]) -> tuple[str, ...]:
    values: set[str] = set()
    for exclusion in exclusions:
        path, parts = Path(exclusion), exclusion.split("/")
        if not exclusion or path.is_absolute() or any(part in {"", ".", ".."} for part in parts):
            raise ReV2SnapshotError(f"unsafe exclusion path: {exclusion!r}")
        values.add(path.as_posix())
    return tuple(sorted(values))


def _is_excluded(relative: str, exclusions: tuple[str, ...]) -> bool:
    return any(relative == item or relative.startswith(item + "/") for item in exclusions)


def _inventory(root: Path, exclusions: tuple[str, ...], *, allow_worktree_git: bool = False) -> tuple[SnapshotEntry, ...]:
    entries: list[SnapshotEntry] = []
    def visit(directory: Path, prefix: str = "") -> None:
        for child in sorted(directory.iterdir(), key=lambda item: item.name):
            relative = f"{prefix}/{child.name}" if prefix else child.name
            info = child.lstat()
            if relative == ".git" and allow_worktree_git:
                if not stat.S_ISREG(info.st_mode):
                    raise ReV2SnapshotError("invalid Git worktree metadata")
                continue
            if _is_excluded(relative, exclusions):
                continue
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
        with (source / entry.path).open("rb") as input_file, destination.open("xb") as output_file:
            shutil.copyfileobj(input_file, output_file)
        destination.chmod(entry.mode)


def _publish_manifest(path: Path, manifest: SnapshotManifest) -> None:
    path.write_bytes(canonical_json_bytes(manifest.to_json_dict()))


def _frozen_mode(mode: int) -> int:
    return mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            raise ReV2SnapshotError(f"source snapshot rejects symlink: {path}")
        path.chmod(_frozen_mode(stat.S_IMODE(path.stat().st_mode)))
    root.chmod(_frozen_mode(stat.S_IMODE(root.stat().st_mode)))


def _remove_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if not path.is_symlink():
            path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)
    root.chmod(stat.S_IMODE(root.stat().st_mode) | stat.S_IWUSR)
    shutil.rmtree(root)


def _clean_git_commit(source: Path) -> str | None:
    try:
        top = Path(run_git(["-C", str(source), "rev-parse", "--show-toplevel"]).strip()).resolve()
        if top != source:
            return None
        commit = run_git(["-C", str(source), "rev-parse", "HEAD^{commit}"]).strip()
        status = run_git(["-C", str(source), "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"])
    except (OSError, subprocess.CalledProcessError):
        return None
    return commit if commit and not status.strip() else None


def _submodule_identities(source: Path) -> list[dict[str, str]]:
    output = run_git(["-C", str(source), "ls-files", "--stage", "-z"])
    identities: list[dict[str, str]] = []
    for record in output.split("\0"):
        if not record or "\t" not in record:
            continue
        metadata, path = record.split("\t", 1)
        mode, commit, _stage = metadata.split()
        if mode == "160000":
            identities.append({"commit": commit, "path": path})
    return sorted(identities, key=lambda item: item["path"])


def _manifest_from_json(value: object) -> SnapshotManifest:
    if not isinstance(value, dict) or not isinstance(value.get("entries"), list):
        raise ValueError("manifest must be an object with entries")
    entries = tuple(SnapshotEntry(item["path"], item["digest"], item["mode"], item["size"]) for item in value["entries"])
    kind = value["kind"]
    if kind not in {"git-worktree", "content-snapshot"}:
        raise ValueError("unsupported snapshot kind")
    return SnapshotManifest(value["snapshot_id"], kind, entries, tuple(value["exclusions"]), value.get("git"), value["capture_version"])
