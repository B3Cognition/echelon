"""Atomic publication of exact certified RE v2 artifact-root sets."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Callable, Iterable, Iterator

from .canonical import canonical_json_bytes, content_digest


PUBLICATION_SCHEMA_VERSION = 1
EMPTY_INDEX_HASH = content_digest(b"")

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")
_HAS_DIRFD_SUPPORT = all(
    operation in os.supports_dir_fd
    for operation in (os.open, os.mkdir, os.stat, os.unlink, os.rmdir, os.rename)
)
_MANIFEST_FIELDS = {
    "accepted_root_hashes",
    "generation_id",
    "schema_version",
    "synthesis_policy_hash",
}
_INDEX_FIELDS = {
    "generation_id",
    "generation_manifest_hash",
    "run_id",
    "schema_version",
}


class ReV2PublicationError(RuntimeError):
    """Raised when v2 publication state or input is unsafe or malformed."""


class ReV2PublicationConflict(ReV2PublicationError):
    """Raised when the workspace index does not match the caller's CAS value."""


@dataclass(frozen=True, slots=True)
class GenerationManifest:
    """Immutable identity of one exact accepted-root set and synthesis policy."""

    schema_version: int
    generation_id: str
    accepted_root_hashes: tuple[str, ...]
    synthesis_policy_hash: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version != PUBLICATION_SCHEMA_VERSION
        ):
            raise ReV2PublicationError("unsupported generation manifest schema_version")
        roots = _canonical_roots(self.accepted_root_hashes)
        if roots != self.accepted_root_hashes:
            raise ReV2PublicationError(
                "accepted_root_hashes must be canonical, unique, and sorted"
            )
        _digest(self.synthesis_policy_hash, "synthesis_policy_hash")
        _digest(self.generation_id, "generation_id")
        if self.generation_id != content_digest(self.identity_dict()):
            raise ReV2PublicationError("generation_id does not match manifest identity")

    @classmethod
    def create(
        cls,
        accepted_root_hashes: Iterable[str],
        synthesis_policy_hash: str,
    ) -> "GenerationManifest":
        roots = _canonical_roots(accepted_root_hashes)
        policy_hash = _digest(synthesis_policy_hash, "synthesis_policy_hash")
        identity = {
            "accepted_root_hashes": list(roots),
            "schema_version": PUBLICATION_SCHEMA_VERSION,
            "synthesis_policy_hash": policy_hash,
        }
        return cls(
            schema_version=PUBLICATION_SCHEMA_VERSION,
            generation_id=content_digest(identity),
            accepted_root_hashes=roots,
            synthesis_policy_hash=policy_hash,
        )

    @classmethod
    def from_bytes(cls, payload: bytes) -> "GenerationManifest":
        raw = _json_object(payload, "generation manifest")
        _exact_fields(raw, _MANIFEST_FIELDS, "generation manifest")
        roots = raw["accepted_root_hashes"]
        if not isinstance(roots, list):
            raise ReV2PublicationError(
                "generation manifest accepted_root_hashes must be an array"
            )
        try:
            manifest = cls(
                schema_version=raw["schema_version"],  # type: ignore[arg-type]
                generation_id=raw["generation_id"],  # type: ignore[arg-type]
                accepted_root_hashes=tuple(roots),  # type: ignore[arg-type]
                synthesis_policy_hash=raw["synthesis_policy_hash"],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise ReV2PublicationError(
                f"generation manifest fields are malformed: {exc}"
            ) from exc
        if payload != canonical_json_bytes(manifest.to_json_dict()):
            raise ReV2PublicationError("generation manifest is not canonical JSON")
        return manifest

    def identity_dict(self) -> dict[str, object]:
        return {
            "accepted_root_hashes": list(self.accepted_root_hashes),
            "schema_version": self.schema_version,
            "synthesis_policy_hash": self.synthesis_policy_hash,
        }

    def to_json_dict(self) -> dict[str, object]:
        return {
            "accepted_root_hashes": list(self.accepted_root_hashes),
            "generation_id": self.generation_id,
            "schema_version": self.schema_version,
            "synthesis_policy_hash": self.synthesis_policy_hash,
        }


@dataclass(frozen=True, slots=True)
class PublishedV2Index:
    """Canonical last-pointer to one complete immutable generation."""

    schema_version: int
    generation_id: str
    generation_manifest_hash: str
    run_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version != PUBLICATION_SCHEMA_VERSION
        ):
            raise ReV2PublicationError("unsupported published v2 index schema_version")
        _digest(self.generation_id, "generation_id")
        _digest(self.generation_manifest_hash, "generation_manifest_hash")
        _run_id(self.run_id)

    @classmethod
    def create(cls, run_id: str, manifest: GenerationManifest) -> "PublishedV2Index":
        if not isinstance(manifest, GenerationManifest):
            raise ReV2PublicationError("manifest must be a GenerationManifest")
        manifest_bytes = canonical_json_bytes(manifest.to_json_dict())
        return cls(
            schema_version=PUBLICATION_SCHEMA_VERSION,
            generation_id=manifest.generation_id,
            generation_manifest_hash=content_digest(manifest_bytes),
            run_id=_run_id(run_id),
        )

    @classmethod
    def from_bytes(cls, payload: bytes) -> "PublishedV2Index":
        raw = _json_object(payload, "published v2 index")
        _exact_fields(raw, _INDEX_FIELDS, "published v2 index")
        try:
            index = cls(
                schema_version=raw["schema_version"],  # type: ignore[arg-type]
                generation_id=raw["generation_id"],  # type: ignore[arg-type]
                generation_manifest_hash=raw["generation_manifest_hash"],  # type: ignore[arg-type]
                run_id=raw["run_id"],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise ReV2PublicationError(
                f"published v2 index fields are malformed: {exc}"
            ) from exc
        if payload != canonical_json_bytes(index.to_json_dict()):
            raise ReV2PublicationError("published v2 index is not canonical JSON")
        return index

    @property
    def index_hash(self) -> str:
        return content_digest(canonical_json_bytes(self.to_json_dict()))

    def to_json_dict(self) -> dict[str, object]:
        return {
            "generation_id": self.generation_id,
            "generation_manifest_hash": self.generation_manifest_hash,
            "run_id": self.run_id,
            "schema_version": self.schema_version,
        }


@dataclass(slots=True)
class _PinnedLayout:
    workspace_path: Path
    workspace_fd: int
    re_fd: int | None
    v2_fd: int | None
    generations_fd: int | None

    def close(self) -> None:
        for fd in (self.generations_fd, self.v2_fd, self.re_fd, self.workspace_fd):
            if fd is not None:
                os.close(fd)


@dataclass(frozen=True, slots=True)
class _GenerationProof:
    generation_id: str
    directory_device: int
    directory_inode: int
    manifest_device: int
    manifest_inode: int
    manifest_hash: str


def publish_generation(
    workspace_root: Path,
    run_id: str,
    accepted_root_hashes: Iterable[str],
    synthesis_policy_hash: str,
    *,
    expected_index_hash: str,
    fault_hook: Callable[[str], None] | None = None,
) -> PublishedV2Index:
    """Publish exactly the caller-certified roots with index compare-and-swap.

    This primitive deliberately does not infer certification, completeness, or
    synthesis eligibility.  Its roots and policy are explicit caller inputs.
    """
    safe_run_id = _run_id(run_id)
    manifest = GenerationManifest.create(accepted_root_hashes, synthesis_policy_hash)
    expected = _digest(expected_index_hash, "expected_index_hash")

    try:
        with _pinned_layout(workspace_root, create=True) as layout:
            with _publication_lock(layout):
                _verify_layout(layout, require_complete=True)
                current = _load_index(layout)
                observed = (
                    current.index_hash if current is not None else EMPTY_INDEX_HASH
                )
                if observed != expected:
                    raise ReV2PublicationConflict(
                        f"expected index {expected}, found {observed}"
                    )

                generation_proof = _create_or_reuse_generation(
                    layout, manifest, fault_hook
                )
                desired = PublishedV2Index.create(safe_run_id, manifest)
                if current == desired:
                    return desired
                _replace_index(
                    layout, desired, manifest, generation_proof, fault_hook
                )
                installed = _load_index(layout)
                if installed != desired:
                    raise ReV2PublicationError(
                        "installed published v2 index failed exact validation"
                    )
                return desired
    except (ReV2PublicationError, KeyboardInterrupt, SystemExit):
        raise
    except OSError as exc:
        raise ReV2PublicationError(f"cannot publish v2 generation: {exc}") from exc


def current_index_hash(workspace_root: Path) -> str:
    """Return the canonical current-index hash or the explicit empty sentinel."""
    try:
        with _pinned_layout(workspace_root, create=False) as layout:
            if layout.v2_fd is None:
                return EMPTY_INDEX_HASH
            index = _load_index(layout)
            return index.index_hash if index is not None else EMPTY_INDEX_HASH
    except (ReV2PublicationError, KeyboardInterrupt, SystemExit):
        raise
    except OSError as exc:
        raise ReV2PublicationError(f"cannot read v2 publication index: {exc}") from exc


def load_published_v2_index(workspace_root: Path) -> PublishedV2Index | None:
    """Load and validate the canonical index and its complete generation."""
    try:
        with _pinned_layout(workspace_root, create=False) as layout:
            if layout.v2_fd is None:
                return None
            return _load_index(layout)
    except (ReV2PublicationError, KeyboardInterrupt, SystemExit):
        raise
    except OSError as exc:
        raise ReV2PublicationError(f"cannot read v2 publication index: {exc}") from exc


def _workspace_path(value: Path) -> Path:
    try:
        raw = Path(value)
    except TypeError as exc:
        raise ReV2PublicationError("workspace path is malformed") from exc
    try:
        details = os.lstat(raw)
    except OSError as exc:
        raise ReV2PublicationError(
            f"workspace path must be an existing directory: {raw}"
        ) from exc
    if stat.S_ISLNK(details.st_mode):
        raise ReV2PublicationError("workspace path must not be a symlink")
    if not stat.S_ISDIR(details.st_mode):
        raise ReV2PublicationError("workspace path must be a directory")
    try:
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise ReV2PublicationError("workspace path cannot be resolved safely") from exc
    if resolved != raw.absolute():
        raise ReV2PublicationError(
            "workspace path must not traverse a symlink or relative segment"
        )
    return resolved


@contextmanager
def _pinned_layout(workspace_root: Path, *, create: bool) -> Iterator[_PinnedLayout]:
    _require_dirfd_support()
    workspace_path = _workspace_path(workspace_root)
    workspace_fd = _open_directory_path_nofollow(workspace_path)
    layout = _PinnedLayout(workspace_path, workspace_fd, None, None, None)
    try:
        layout.re_fd = _open_or_create_directory_at(
            workspace_fd, "re", "re publication parent", create=create
        )
        if layout.re_fd is None:
            _verify_layout(layout, require_complete=False)
            yield layout
            return
        layout.v2_fd = _open_or_create_directory_at(
            layout.re_fd, "v2", "v2 publication root", create=create
        )
        if layout.v2_fd is None:
            _verify_layout(layout, require_complete=False)
            yield layout
            return
        layout.generations_fd = _open_or_create_directory_at(
            layout.v2_fd,
            "generations",
            "generation namespace",
            create=create,
        )
        _verify_layout(layout, require_complete=create)
        yield layout
    finally:
        layout.close()


def _verify_layout(layout: _PinnedLayout, *, require_complete: bool) -> None:
    _require_path_matches_fd(layout.workspace_path, layout.workspace_fd, "workspace")
    pairs = (
        (layout.workspace_fd, "re", layout.re_fd, "re publication parent"),
        (layout.re_fd, "v2", layout.v2_fd, "v2 publication root"),
        (
            layout.v2_fd,
            "generations",
            layout.generations_fd,
            "generation namespace",
        ),
    )
    for parent_fd, name, child_fd, label in pairs:
        if child_fd is None:
            if require_complete:
                raise ReV2PublicationError(f"publication layout is incomplete: {label}")
            return
        if parent_fd is None:
            raise ReV2PublicationError(f"publication layout continuity failed: {label}")
        _require_entry_matches_fd(parent_fd, name, child_fd, label)


@contextmanager
def _publication_lock(layout: _PinnedLayout) -> Iterator[None]:
    if layout.v2_fd is None:
        raise ReV2PublicationError("v2 publication root is unavailable")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    existed = _entry_exists(layout.v2_fd, ".publication.lock")
    fd = _open_at(layout.v2_fd, ".publication.lock", flags, 0o600)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode):
            raise ReV2PublicationError("publication lock is not a regular file")
        _require_entry_matches_fd(
            layout.v2_fd, ".publication.lock", fd, "publication lock"
        )
        if not existed:
            _fsync(fd)
            _fsync(layout.v2_fd)
        _flock(fd, fcntl.LOCK_EX)
        _verify_layout(layout, require_complete=True)
        _require_entry_matches_fd(
            layout.v2_fd, ".publication.lock", fd, "publication lock"
        )
        yield
    finally:
        try:
            _flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _create_or_reuse_generation(
    layout: _PinnedLayout,
    manifest: GenerationManifest,
    fault_hook: Callable[[str], None] | None,
) -> _GenerationProof:
    if layout.generations_fd is None:
        raise ReV2PublicationError("generation namespace is unavailable")
    payload = canonical_json_bytes(manifest.to_json_dict())
    if _entry_exists(layout.generations_fd, manifest.generation_id):
        return _validate_generation(
            layout, manifest.generation_id, content_digest(payload), payload
        )

    temporary_name, temporary_fd, temporary_identity = _create_temporary_directory_at(
        layout.generations_fd, ".generation.", ".tmp"
    )
    promoted = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = _open_at(temporary_fd, "manifest.json", flags, 0o600)
        try:
            _write_all(fd, payload)
            os.fchmod(fd, 0o400)
            _fsync(fd)
        finally:
            os.close(fd)
        _fchmod(temporary_fd, 0o500)
        _fsync(temporary_fd)
        _hook(fault_hook, "generation_temporary_written")
        _verify_layout(layout, require_complete=True)
        _require_entry_matches_fd(
            layout.generations_fd,
            temporary_name,
            temporary_fd,
            "generation temporary",
        )
        try:
            _rename_no_replace_at(
                layout.generations_fd,
                temporary_name,
                manifest.generation_id,
                temporary_fd,
            )
        except FileExistsError:
            return _validate_generation(
                layout, manifest.generation_id, content_digest(payload), payload
            )
        promoted = True
        _verify_layout(layout, require_complete=True)
        _require_entry_matches_fd(
            layout.generations_fd,
            manifest.generation_id,
            temporary_fd,
            "promoted generation",
        )
        _fsync(temporary_fd)
        _fsync(layout.generations_fd)
        proof = _validate_generation(
            layout, manifest.generation_id, content_digest(payload), payload
        )
        _hook(fault_hook, "generation_promoted")
        _verify_layout(layout, require_complete=True)
        return _validate_generation(
            layout,
            manifest.generation_id,
            content_digest(payload),
            payload,
            expected_proof=proof,
        )
    finally:
        os.close(temporary_fd)
        if not promoted:
            _cleanup_temporary_directory_at(
                layout.generations_fd,
                temporary_name,
                temporary_identity,
            )


def _replace_index(
    layout: _PinnedLayout,
    index: PublishedV2Index,
    manifest: GenerationManifest,
    generation_proof: _GenerationProof,
    fault_hook: Callable[[str], None] | None,
) -> None:
    if layout.v2_fd is None:
        raise ReV2PublicationError("v2 publication root is unavailable")
    payload = canonical_json_bytes(index.to_json_dict())
    temporary_name, fd, temporary_identity = _create_temporary_file_at(
        layout.v2_fd, ".index.json.", ".tmp"
    )
    replaced = False
    try:
        try:
            _write_all(fd, payload)
            os.fchmod(fd, 0o400)
            _fsync(fd)
        finally:
            os.close(fd)
        _hook(fault_hook, "index_temporary_written")
        _verify_layout(layout, require_complete=True)
        manifest_payload = canonical_json_bytes(manifest.to_json_dict())
        _validate_generation(
            layout,
            manifest.generation_id,
            content_digest(manifest_payload),
            manifest_payload,
            expected_proof=generation_proof,
        )
        _replace_at(layout.v2_fd, temporary_name, "index.json")
        replaced = True
        _verify_layout(layout, require_complete=True)
        _fsync(layout.v2_fd)
        _hook(fault_hook, "index_replaced")
    finally:
        if not replaced:
            _cleanup_temporary_file_at(
                layout.v2_fd, temporary_name, temporary_identity
            )


def _load_index(layout: _PinnedLayout) -> PublishedV2Index | None:
    if layout.v2_fd is None:
        return None
    _verify_layout(layout, require_complete=False)
    if not _entry_exists(layout.v2_fd, "index.json"):
        return None
    payload, _ = _read_regular_at(
        layout.v2_fd, "index.json", "published v2 index"
    )
    index = PublishedV2Index.from_bytes(payload)
    _validate_generation(
        layout,
        index.generation_id,
        index.generation_manifest_hash,
        None,
    )
    _verify_layout(layout, require_complete=True)
    return index


def _validate_generation(
    layout: _PinnedLayout,
    generation_id: str,
    expected_manifest_hash: str,
    expected_payload: bytes | None,
    *,
    expected_proof: _GenerationProof | None = None,
) -> _GenerationProof:
    if layout.generations_fd is None:
        raise ReV2PublicationError(
            f"generation manifest is missing for {generation_id}"
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = _open_at(layout.generations_fd, generation_id, flags)
    except OSError as exc:
        raise ReV2PublicationError(
            f"generation manifest is missing for {generation_id}"
        ) from exc
    try:
        opened = os.fstat(directory_fd)
        _require_entry_matches_fd(
            layout.generations_fd,
            generation_id,
            directory_fd,
            f"generation {generation_id}",
        )
        if not stat.S_ISDIR(opened.st_mode):
            raise ReV2PublicationError(f"generation collision at {generation_id}")
        if stat.S_IMODE(opened.st_mode) != 0o500:
            raise ReV2PublicationError(
                f"generation has mutable or unexpected mode: {generation_id}"
            )
        entries = _directory_entries(directory_fd, generation_id)
        if "manifest.json" not in entries:
            raise ReV2PublicationError(
                f"generation manifest is missing for {generation_id}"
            )
        if entries != ["manifest.json"]:
            raise ReV2PublicationError(f"generation collision at {generation_id}")
        payload, manifest_details = _read_regular_at(
            directory_fd,
            "manifest.json",
            "generation manifest",
            expected_mode=0o400,
            require_single_link=True,
        )
        manifest = GenerationManifest.from_bytes(payload)
        if (
            manifest.generation_id != generation_id
            or content_digest(payload) != expected_manifest_hash
            or (expected_payload is not None and payload != expected_payload)
        ):
            raise ReV2PublicationError(f"generation collision at {generation_id}")
        confirmed = _directory_entries(directory_fd, generation_id)
        after = os.fstat(directory_fd)
        _require_entry_matches_fd(
            layout.generations_fd,
            generation_id,
            directory_fd,
            f"generation {generation_id}",
        )
        if (
            confirmed != entries
            or _stable_directory_identity(opened)
            != _stable_directory_identity(after)
        ):
            raise ReV2PublicationError(
                f"generation mutated during validation: {generation_id}"
            )
        proof = _GenerationProof(
            generation_id=generation_id,
            directory_device=after.st_dev,
            directory_inode=after.st_ino,
            manifest_device=manifest_details.st_dev,
            manifest_inode=manifest_details.st_ino,
            manifest_hash=content_digest(payload),
        )
        if expected_proof is not None and proof != expected_proof:
            raise ReV2PublicationError(
                f"generation was replaced during publication: {generation_id}"
            )
        return proof
    finally:
        os.close(directory_fd)


def _directory_entries(directory_fd: int, generation_id: str) -> list[str]:
    try:
        return sorted(entry.name for entry in os.scandir(directory_fd))
    except OSError as exc:
        raise ReV2PublicationError(
            f"cannot inspect generation {generation_id}: {exc}"
        ) from exc


def _json_object(payload: bytes, label: str) -> dict[str, object]:
    if not isinstance(payload, bytes):
        raise ReV2PublicationError(f"{label} payload must be bytes")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReV2PublicationError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ReV2PublicationError(f"{label} must be a JSON object")
    return value


def _exact_fields(value: dict[str, object], fields: set[str], label: str) -> None:
    if set(value) != fields:
        raise ReV2PublicationError(f"{label} fields are malformed")


def _canonical_roots(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ReV2PublicationError("accepted_root_hashes must be a non-empty iterable")
    try:
        roots = tuple(values)
    except TypeError as exc:
        raise ReV2PublicationError(
            "accepted_root_hashes must be a non-empty iterable"
        ) from exc
    if not roots:
        raise ReV2PublicationError("accepted_root_hashes must be non-empty")
    for value in roots:
        _digest(value, "accepted_root_hash")
    return tuple(sorted(set(roots)))


def _run_id(value: object) -> str:
    if not isinstance(value, str) or not _RUN_ID_RE.fullmatch(value):
        raise ReV2PublicationError("run_id is unsafe or malformed")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ReV2PublicationError(f"{field} must be a lowercase sha256 digest")
    return value


def _require_dirfd_support() -> None:
    if (
        not _HAS_DIRFD_SUPPORT
        or not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
    ):
        raise ReV2PublicationError(
            "descriptor-relative no-follow publication is unsupported"
        )


def _open_directory_path_nofollow(path: Path) -> int:
    absolute = path.absolute()
    if not absolute.is_absolute() or any(part in {".", ".."} for part in absolute.parts):
        raise ReV2PublicationError(f"unsafe workspace traversal path: {path}")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    current = _open(Path("/"), flags)
    try:
        for part in absolute.parts[1:]:
            next_fd = _open_at(current, part, flags)
            os.close(current)
            current = next_fd
        if not stat.S_ISDIR(os.fstat(current).st_mode):
            raise ReV2PublicationError("workspace path must be a directory")
        return current
    except BaseException:
        os.close(current)
        raise


def _open_or_create_directory_at(
    parent_fd: int,
    name: str,
    label: str,
    *,
    create: bool,
) -> int | None:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = _open_at(parent_fd, name, flags)
    except FileNotFoundError:
        if not create:
            return None
        try:
            _mkdir_at(parent_fd, name, 0o700)
        except FileExistsError:
            pass
        _fsync(parent_fd)
        try:
            fd = _open_at(parent_fd, name, flags)
        except OSError as exc:
            raise ReV2PublicationError(f"unsafe concurrent {label}: {exc}") from exc
    except OSError as exc:
        raise ReV2PublicationError(f"cannot open {label} without symlinks: {exc}") from exc
    details = os.fstat(fd)
    if not stat.S_ISDIR(details.st_mode):
        os.close(fd)
        raise ReV2PublicationError(f"{label} is not a directory")
    try:
        _require_entry_matches_fd(parent_fd, name, fd, label)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _require_path_matches_fd(path: Path, fd: int, label: str) -> None:
    try:
        current = os.lstat(path)
    except OSError as exc:
        raise ReV2PublicationError(f"{label} path continuity was lost") from exc
    expected = os.fstat(fd)
    if stat.S_ISLNK(current.st_mode) or _identity(current) != _identity(expected):
        raise ReV2PublicationError(f"{label} was replaced during publication")


def _require_entry_matches_fd(
    parent_fd: int, name: str, fd: int, label: str
) -> None:
    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise ReV2PublicationError(f"{label} path continuity was lost") from exc
    expected = os.fstat(fd)
    if stat.S_ISLNK(current.st_mode) or _identity(current) != _identity(expected):
        raise ReV2PublicationError(f"{label} was replaced during publication")


def _entry_exists(parent_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _create_temporary_directory_at(
    parent_fd: int, prefix: str, suffix: str
) -> tuple[str, int, tuple[int, int]]:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    for _ in range(128):
        name = f"{prefix}{secrets.token_hex(16)}{suffix}"
        try:
            _mkdir_at(parent_fd, name, 0o700)
        except FileExistsError:
            continue
        fd = _open_at(parent_fd, name, flags)
        details = os.fstat(fd)
        try:
            _require_entry_matches_fd(parent_fd, name, fd, "generation temporary")
        except BaseException:
            os.close(fd)
            _cleanup_temporary_directory_at(
                parent_fd, name, (details.st_dev, details.st_ino)
            )
            raise
        return name, fd, (details.st_dev, details.st_ino)
    raise ReV2PublicationError("cannot allocate a unique generation temporary")


def _create_temporary_file_at(
    parent_fd: int, prefix: str, suffix: str
) -> tuple[str, int, tuple[int, int]]:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    for _ in range(128):
        name = f"{prefix}{secrets.token_hex(16)}{suffix}"
        try:
            fd = _open_at(parent_fd, name, flags, 0o600)
        except FileExistsError:
            continue
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode):
            os.close(fd)
            raise ReV2PublicationError("index temporary is not a regular file")
        try:
            _require_entry_matches_fd(parent_fd, name, fd, "index temporary")
        except BaseException:
            os.close(fd)
            _cleanup_temporary_file_at(
                parent_fd, name, (details.st_dev, details.st_ino)
            )
            raise
        return name, fd, (details.st_dev, details.st_ino)
    raise ReV2PublicationError("cannot allocate a unique index temporary")


def _read_regular_at(
    directory_fd: int,
    name: str,
    label: str,
    *,
    expected_mode: int | None = None,
    require_single_link: bool = False,
) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = _open_at(directory_fd, name, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ReV2PublicationError(f"{label} is not a regular file")
        if expected_mode is not None and stat.S_IMODE(before.st_mode) != expected_mode:
            raise ReV2PublicationError(f"{label} has mutable or unexpected mode")
        if require_single_link and before.st_nlink != 1:
            raise ReV2PublicationError(f"{label} must have exactly one hard link")
        payload = _read_all(fd)
        after = os.fstat(fd)
        if (
            _stable_file_identity(before) != _stable_file_identity(after)
            or len(payload) != after.st_size
            or (require_single_link and after.st_nlink != 1)
        ):
            raise ReV2PublicationError(f"{label} mutated while being read")
        return payload, after
    finally:
        os.close(fd)


def _open(path: Path, flags: int, mode: int | None = None) -> int:
    while True:
        try:
            return os.open(path, flags) if mode is None else os.open(path, flags, mode)
        except InterruptedError:
            continue


def _open_at(
    directory_fd: int, name: str, flags: int, mode: int | None = None
) -> int:
    while True:
        try:
            if mode is None:
                return os.open(name, flags, dir_fd=directory_fd)
            return os.open(name, flags, mode, dir_fd=directory_fd)
        except InterruptedError:
            continue


def _mkdir_at(directory_fd: int, name: str, mode: int) -> None:
    while True:
        try:
            os.mkdir(name, mode, dir_fd=directory_fd)
            return
        except InterruptedError:
            continue


def _flock(fd: int, operation: int) -> None:
    while True:
        try:
            fcntl.flock(fd, operation)
            return
        except InterruptedError:
            continue


def _read_all(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        try:
            chunk = os.read(fd, 1024 * 1024)
        except InterruptedError:
            continue
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(fd, payload[offset:])
        except InterruptedError:
            continue
        if written <= 0:
            raise OSError("short write while persisting publication data")
        offset += written


def _fsync(fd: int) -> None:
    while True:
        try:
            os.fsync(fd)
            return
        except InterruptedError:
            continue


def _rename_no_replace_at(
    directory_fd: int,
    source: str,
    destination: str,
    source_fd: int,
) -> None:
    while True:
        libc = ctypes.CDLL(None, use_errno=True)
        source_bytes = os.fsencode(source)
        destination_bytes = os.fsencode(destination)
        if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
            operation = libc.renameat2
            operation.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            operation.restype = ctypes.c_int
            result = operation(
                directory_fd,
                source_bytes,
                directory_fd,
                destination_bytes,
                0x00000001,
            )
        elif sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
            operation = libc.renameatx_np
            operation.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            operation.restype = ctypes.c_int
            frozen_mode = stat.S_IMODE(os.fstat(source_fd).st_mode)
            try:
                _fchmod(source_fd, frozen_mode | stat.S_IWUSR)
                result = operation(
                    directory_fd,
                    source_bytes,
                    directory_fd,
                    destination_bytes,
                    0x00000004,
                )
                saved_errno = ctypes.get_errno()
                _fchmod(source_fd, frozen_mode)
                _fsync(source_fd)
                ctypes.set_errno(saved_errno)
            except BaseException:
                _fchmod(source_fd, frozen_mode)
                raise
        else:
            raise ReV2PublicationError(
                "atomic no-replace generation promotion is unsupported"
            )
        if result == 0:
            return
        error = ctypes.get_errno()
        if error == errno.EINTR:
            continue
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(error, os.strerror(error), destination)
        raise OSError(error, os.strerror(error), destination)


def _replace_at(directory_fd: int, source: str, destination: str) -> None:
    while True:
        try:
            os.rename(
                source,
                destination,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            return
        except InterruptedError:
            if not _entry_exists(directory_fd, source) and _entry_exists(
                directory_fd, destination
            ):
                return
            continue


def _fchmod(fd: int, mode: int) -> None:
    while True:
        try:
            os.fchmod(fd, mode)
            return
        except InterruptedError:
            continue


def _cleanup_temporary_file_at(
    parent_fd: int, name: str, identity: tuple[int, int]
) -> None:
    try:
        details = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        return
    if (details.st_dev, details.st_ino) != identity or not stat.S_ISREG(
        details.st_mode
    ):
        return
    try:
        os.unlink(name, dir_fd=parent_fd)
    except OSError:
        pass


def _cleanup_temporary_directory_at(
    parent_fd: int, name: str, identity: tuple[int, int]
) -> None:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = _open_at(parent_fd, name, flags)
    except OSError:
        return
    try:
        details = os.fstat(fd)
        if (details.st_dev, details.st_ino) != identity:
            return
        _fchmod(fd, 0o700)
        try:
            manifest = os.stat("manifest.json", dir_fd=fd, follow_symlinks=False)
        except OSError:
            manifest = None
        if manifest is not None and stat.S_ISREG(manifest.st_mode):
            try:
                os.unlink("manifest.json", dir_fd=fd)
            except OSError:
                pass
    finally:
        os.close(fd)
    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) == identity:
            os.rmdir(name, dir_fd=parent_fd)
    except OSError:
        pass


def _identity(details: os.stat_result) -> tuple[int, int, int]:
    return details.st_dev, details.st_ino, stat.S_IFMT(details.st_mode)


def _stable_file_identity(details: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_mode,
        details.st_size,
        details.st_mtime_ns,
    )


def _stable_directory_identity(
    details: os.stat_result,
) -> tuple[int, int, int, int, int, int]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_mode,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
    )


def _hook(hook: Callable[[str], None] | None, boundary: str) -> None:
    if hook is not None:
        hook(boundary)


__all__ = (
    "EMPTY_INDEX_HASH",
    "GenerationManifest",
    "PUBLICATION_SCHEMA_VERSION",
    "PublishedV2Index",
    "ReV2PublicationConflict",
    "ReV2PublicationError",
    "current_index_hash",
    "load_published_v2_index",
    "publish_generation",
)
