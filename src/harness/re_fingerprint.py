"""Deterministic source fingerprints for reverse-engineering cache keys."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from echelon.workspace_model import IGNORED_SOURCE_DIRS

SourceFingerprintKind = Literal["git", "file-tree"]


@dataclass(frozen=True)
class ReFingerprintProfile:
    """Reverse-engineering profile inputs that affect extracted artifact shape."""

    profile: str = "full"
    depth: str = "full"
    max_lines_per_file: int | None = 5000
    git_history_limit: int | None = 2500
    codegraph_version: str | None = None

    def stable_json(self) -> str:
        return json.dumps(
            {
                "profile": self.profile,
                "depth": self.depth,
                "max_lines_per_file": self.max_lines_per_file,
                "git_history_limit": self.git_history_limit,
                "codegraph_version": self.codegraph_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class SourceFingerprint:
    """Stable source fingerprint plus provenance fields for RE cache planning."""

    value: str
    kind: SourceFingerprintKind
    dirty: bool
    profile_hash: str
    git_head: str | None = None


def fingerprint_source(source_path: Path, profile: ReFingerprintProfile) -> SourceFingerprint:
    """Compute a deterministic fingerprint for one source root."""
    source = source_path.resolve()
    profile_hash = _sha256_text(profile.stable_json())
    if _is_git_worktree(source):
        return _fingerprint_git_source(source, profile, profile_hash)
    return _fingerprint_file_tree(source, profile_hash)


def _fingerprint_git_source(
    source: Path,
    profile: ReFingerprintProfile,
    profile_hash: str,
) -> SourceFingerprint:
    head = _git(source, "rev-parse", "HEAD")
    status_entries = _git_status_entries(source)
    digest = hashlib.sha256()
    _digest_text(digest, "kind=git")
    _digest_text(digest, f"profile={profile.stable_json()}")
    _digest_text(digest, f"head={head}")
    for relative_path, status in status_entries:
        _digest_text(digest, f"status={status}\t{relative_path}")
        path = source / relative_path
        if path.is_file():
            _digest_file(digest, relative_path, path)
        else:
            _digest_text(digest, f"missing={relative_path}")
    return SourceFingerprint(
        value=digest.hexdigest(),
        kind="git",
        dirty=bool(status_entries),
        profile_hash=profile_hash,
        git_head=head,
    )


def _fingerprint_file_tree(source: Path, profile_hash: str) -> SourceFingerprint:
    digest = hashlib.sha256()
    _digest_text(digest, "kind=file-tree")
    _digest_text(digest, f"profile_hash={profile_hash}")
    for path in _iter_relevant_files(source):
        _digest_file(digest, path.relative_to(source).as_posix(), path)
    return SourceFingerprint(
        value=digest.hexdigest(),
        kind="file-tree",
        dirty=False,
        profile_hash=profile_hash,
        git_head=None,
    )


def _iter_relevant_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in IGNORED_SOURCE_DIRS for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def _is_git_worktree(path: Path) -> bool:
    result = _run_git(path, "rev-parse", "--is-inside-work-tree", check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git_status_entries(path: Path) -> list[tuple[str, str]]:
    result = _run_git(
        path,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    raw_entries = [entry for entry in result.stdout.split("\0") if entry]
    entries: list[tuple[str, str]] = []
    index = 0
    while index < len(raw_entries):
        entry = raw_entries[index]
        status = entry[:2]
        relative_path = entry[3:]
        if "R" in status or "C" in status:
            index += 1
            if index < len(raw_entries):
                relative_path = raw_entries[index]
        entries.append((relative_path, status))
        index += 1
    return sorted(entries, key=lambda item: item[0])


def _git(path: Path, *args: str) -> str:
    result = _run_git(path, *args)
    return result.stdout.strip()


def _run_git(path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=path,
        check=check,
        capture_output=True,
        text=True,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest_text(digest: Any, value: str) -> None:
    digest.update(value.encode("utf-8"))
    digest.update(b"\0")


def _digest_file(digest: Any, relative_path: str, path: Path) -> None:
    _digest_text(digest, f"file={relative_path}")
    digest.update(path.read_bytes())
    digest.update(b"\0")
