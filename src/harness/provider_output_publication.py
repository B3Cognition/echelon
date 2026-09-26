"""Harness-owned proof that required provider outputs came from this dispatch."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping


@dataclass(frozen=True)
class ProviderOutputSpec:
    """One exact output path and its required filesystem kind."""

    path: str
    kind: str = "file"

    def __post_init__(self) -> None:
        relative = PurePosixPath(self.path)
        if (
            self.kind not in {"file", "directory"}
            or not self.path
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.as_posix() != self.path
        ):
            raise ValueError("invalid provider output specification")


@dataclass(frozen=True)
class ProviderOutputFailure:
    """Bounded publication failure grouped by recovery behavior."""

    missing: tuple[str, ...] = ()
    undeclared: tuple[str, ...] = ()
    stale: tuple[str, ...] = ()
    unpublished: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderOutputFinalization:
    receipt: Mapping[str, object] | None
    failure: ProviderOutputFailure | None


@dataclass(frozen=True)
class _ArtifactSnapshot:
    identity_sha256: str
    content_sha256: str


@dataclass(frozen=True)
class ProviderOutputGuard:
    """Capture required outputs before dispatch and finalize them afterwards."""

    project_root: Path
    spec_dir: Path
    phase_id: str
    state_revision: int
    dispatch_id: str
    specs: tuple[ProviderOutputSpec, ...]
    baseline: tuple[_ArtifactSnapshot | None, ...]

    @classmethod
    def capture(
        cls,
        *,
        project_root: Path,
        spec_dir: Path,
        phase_id: str,
        state_revision: int,
        specs: tuple[ProviderOutputSpec, ...],
    ) -> "ProviderOutputGuard":
        root = Path(project_root).resolve(strict=False)
        output_root = Path(spec_dir).resolve(strict=False)
        return cls(
            project_root=root,
            spec_dir=output_root,
            phase_id=str(phase_id),
            state_revision=int(state_revision),
            dispatch_id=secrets.token_hex(16),
            specs=specs,
            baseline=tuple(
                _snapshot(output_root / spec.path, spec.kind) for spec in specs
            ),
        )

    def finalize(self, payload: object) -> ProviderOutputFinalization:
        claimed = self._claimed_paths(payload)
        missing: list[str] = []
        undeclared: list[str] = []
        stale: list[str] = []
        unpublished: list[str] = []
        outputs: list[dict[str, object]] = []

        for spec, before in zip(self.specs, self.baseline, strict=True):
            target = self.spec_dir / spec.path
            after = _snapshot(target, spec.kind)
            if after is None:
                display = _display_path(spec)
                missing.append(display)
                unpublished.append(display)
                continue
            if target.resolve(strict=False) not in claimed:
                display = _display_path(spec)
                undeclared.append(display)
                unpublished.append(display)
                continue
            if after == before:
                stale.append(_display_path(spec))
                continue
            outputs.append(
                {
                    "path": spec.path,
                    "kind": spec.kind,
                    "sha256": after.content_sha256,
                }
            )

        if missing or undeclared or stale:
            return ProviderOutputFinalization(
                receipt=None,
                failure=ProviderOutputFailure(
                    missing=tuple(missing),
                    undeclared=tuple(undeclared),
                    stale=tuple(stale),
                    unpublished=tuple(unpublished),
                ),
            )
        return ProviderOutputFinalization(
            receipt={
                "schema_version": 1,
                "dispatch_id": self.dispatch_id,
                "phase_id": self.phase_id,
                "state_revision": self.state_revision,
                "outputs": outputs,
            },
            failure=None,
        )

    def _claimed_paths(self, payload: object) -> set[Path]:
        if not isinstance(payload, dict):
            return set()
        raw_outputs = payload.get("output_files")
        if not isinstance(raw_outputs, list):
            return set()
        claimed: set[Path] = set()
        for raw in raw_outputs:
            if not isinstance(raw, str) or not raw.strip():
                continue
            candidate = Path(raw.strip().rstrip("/"))
            candidates = (
                (candidate,)
                if candidate.is_absolute()
                else (
                    self.project_root / candidate,
                    self.spec_dir / candidate,
                )
            )
            claimed.update(path.resolve(strict=False) for path in candidates)
        return claimed


def _display_path(spec: ProviderOutputSpec) -> str:
    return f"{spec.path}/" if spec.kind == "directory" else spec.path


def _snapshot(path: Path, kind: str) -> _ArtifactSnapshot | None:
    try:
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode):
            return None
        if kind == "file":
            if not stat.S_ISREG(metadata.st_mode):
                return None
            content_sha256 = _file_sha256(path)
            members: list[object] = []
        else:
            if not stat.S_ISDIR(metadata.st_mode):
                return None
            content_sha256, members = _directory_snapshot(path)
        identity = {
            "root": _metadata_identity(metadata),
            "members": members,
        }
        return _ArtifactSnapshot(
            identity_sha256=hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            content_sha256=content_sha256,
        )
    except (OSError, UnicodeError, ValueError):
        return None


def _directory_snapshot(root: Path) -> tuple[str, list[object]]:
    members: list[object] = []
    content = hashlib.sha256()
    for current_root, directories, filenames in os.walk(root, followlinks=False):
        current = Path(current_root)
        directories.sort()
        filenames.sort()
        for name in (*directories, *filenames):
            candidate = current / name
            metadata = os.lstat(candidate)
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError("provider output contains a symlink")
            relative = candidate.relative_to(root).as_posix()
            if stat.S_ISDIR(metadata.st_mode):
                entry_sha256 = ""
                entry_kind = "directory"
            elif stat.S_ISREG(metadata.st_mode):
                entry_sha256 = _file_sha256(candidate)
                entry_kind = "file"
                content.update(relative.encode())
                content.update(b"\0")
                content.update(entry_sha256.encode())
                content.update(b"\0")
            else:
                raise ValueError("provider output has an unsupported file type")
            members.append(
                {
                    "path": relative,
                    "kind": entry_kind,
                    "identity": _metadata_identity(metadata),
                    "sha256": entry_sha256,
                }
            )
    return content.hexdigest(), members


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )
