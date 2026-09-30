"""Sealed, idempotent publication of CHIEF's run-local constitution draft."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from collections.abc import Mapping
from pathlib import Path


_SHA256_LENGTH = 64
_MAX_CONSTITUTION_BYTES = 4_194_304


class ConstitutionPublicationError(RuntimeError):
    """A sealed constitution request could not be authenticated or applied."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical_digest(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ConstitutionPublicationError("receipt_invalid") from exc
    return hashlib.sha256(encoded).hexdigest()


def _valid_sha256(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ConstitutionPublicationError("request_invalid")
    return value


def _identity_sha256(metadata: os.stat_result) -> str:
    return _canonical_digest(
        {
            "device": metadata.st_dev,
            "inode": metadata.st_ino,
            "mode": stat.S_IFMT(metadata.st_mode),
            "size": metadata.st_size,
            "mtime_ns": metadata.st_mtime_ns,
        }
    )


def _absolute_file_path(value: object, *, name: str) -> Path:
    if type(value) is not str or not value or "\x00" in value:
        raise ConstitutionPublicationError("request_invalid")
    path = Path(value)
    if not path.is_absolute() or path.name != name:
        raise ConstitutionPublicationError("request_invalid")
    return path


def validate_constitution_publication_request(
    value: object,
) -> dict[str, object]:
    """Validate the closed JSON request without consulting live paths."""
    keys = {
        "schema_version",
        "draft_path",
        "target_path",
        "draft_identity_sha256",
        "draft_sha256",
        "provider_receipt_sha256",
    }
    if type(value) is not dict or set(value) != keys:
        raise ConstitutionPublicationError("request_invalid")
    if value["schema_version"] != 1 or type(value["schema_version"]) is not int:
        raise ConstitutionPublicationError("request_invalid")
    draft = _absolute_file_path(
        value["draft_path"], name="constitution.draft.md"
    )
    target = _absolute_file_path(value["target_path"], name="constitution.md")
    if target.parent.name != ".echelon":
        raise ConstitutionPublicationError("request_invalid")
    return {
        "schema_version": 1,
        "draft_path": str(draft),
        "target_path": str(target),
        "draft_identity_sha256": _valid_sha256(
            value["draft_identity_sha256"]
        ),
        "draft_sha256": _valid_sha256(value["draft_sha256"]),
        "provider_receipt_sha256": _valid_sha256(
            value["provider_receipt_sha256"]
        ),
    }


def _open_directory(path: Path, *, code: str) -> tuple[int, os.stat_result]:
    try:
        before = os.lstat(path)
        if not stat.S_ISDIR(before.st_mode) or stat.S_ISLNK(before.st_mode):
            raise ConstitutionPublicationError(code)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            os.close(descriptor)
            raise ConstitutionPublicationError(code)
        return descriptor, opened
    except ConstitutionPublicationError:
        raise
    except OSError as exc:
        raise ConstitutionPublicationError(code) from exc


def _read_regular_at(
    directory_fd: int,
    name: str,
    *,
    missing_ok: bool,
    code: str,
) -> tuple[bytes, os.stat_result] | None:
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_CONSTITUTION_BYTES:
            raise ConstitutionPublicationError(code)
        chunks: list[bytes] = []
        remaining = _MAX_CONSTITUTION_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(content) > _MAX_CONSTITUTION_BYTES
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise ConstitutionPublicationError(code)
        return content, after
    except FileNotFoundError:
        if missing_ok:
            return None
        raise ConstitutionPublicationError(code)
    except ConstitutionPublicationError:
        raise
    except OSError as exc:
        raise ConstitutionPublicationError(code) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def prepare_constitution_publication(
    draft: Path,
    target: Path,
    provider_receipt: Mapping[str, object],
) -> dict[str, object]:
    """Seal the exact draft postimage and the provider receipt that authored it."""
    draft = Path(draft).absolute()
    target = Path(target).absolute()
    _absolute_file_path(str(draft), name="constitution.draft.md")
    _absolute_file_path(str(target), name="constitution.md")
    if target.parent.name != ".echelon":
        raise ConstitutionPublicationError("request_invalid")
    parent_fd, _parent_identity = _open_directory(
        draft.parent, code="draft_invalid"
    )
    try:
        opened = _read_regular_at(
            parent_fd,
            draft.name,
            missing_ok=False,
            code="draft_invalid",
        )
    finally:
        os.close(parent_fd)
    assert opened is not None
    content, metadata = opened
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConstitutionPublicationError("draft_invalid") from exc
    if not text.strip():
        raise ConstitutionPublicationError("draft_invalid")
    from harness.phase_a_readiness import unresolved_constitution_template_markers

    if unresolved_constitution_template_markers(text):
        raise ConstitutionPublicationError("draft_invalid")
    return validate_constitution_publication_request(
        {
            "schema_version": 1,
            "draft_path": str(draft),
            "target_path": str(target),
            "draft_identity_sha256": _identity_sha256(metadata),
            "draft_sha256": hashlib.sha256(content).hexdigest(),
            "provider_receipt_sha256": _canonical_digest(dict(provider_receipt)),
        }
    )


def _provider_receipt_is_sealed(prepared: object, expected_digest: str) -> bool:
    try:
        provenance = prepared.intent.provenance
        execution = provenance["provider_execution"]
        receipts = execution["receipts"]
    except (AttributeError, KeyError, TypeError):
        return False
    return type(receipts) is list and any(
        isinstance(receipt, Mapping)
        and _canonical_digest(dict(receipt)) == expected_digest
        for receipt in receipts
    )


def apply_or_verify_constitution_publication(
    prepared: object,
    request: Mapping[str, object],
) -> dict[str, object]:
    """Apply once or adopt the exact already-published target after a crash."""
    sealed = validate_constitution_publication_request(dict(request))
    if not _provider_receipt_is_sealed(
        prepared, str(sealed["provider_receipt_sha256"])
    ):
        raise ConstitutionPublicationError("receipt_mismatch")
    draft = Path(str(sealed["draft_path"]))
    target = Path(str(sealed["target_path"]))
    target_fd, _target_parent_identity = _open_directory(
        target.parent, code="target_invalid"
    )
    temporary_name: str | None = None
    try:
        existing = _read_regular_at(
            target_fd,
            target.name,
            missing_ok=True,
            code="target_invalid",
        )
        if (
            existing is not None
            and hashlib.sha256(existing[0]).hexdigest() == sealed["draft_sha256"]
        ):
            return _publication_receipt(sealed)

        draft_fd, _draft_parent_identity = _open_directory(
            draft.parent, code="draft_invalid"
        )
        try:
            opened = _read_regular_at(
                draft_fd,
                draft.name,
                missing_ok=False,
                code="draft_invalid",
            )
        finally:
            os.close(draft_fd)
        assert opened is not None
        content, metadata = opened
        if (
            _identity_sha256(metadata) != sealed["draft_identity_sha256"]
            or hashlib.sha256(content).hexdigest() != sealed["draft_sha256"]
        ):
            raise ConstitutionPublicationError("draft_drift")

        temporary_name = f".{target.name}.{secrets.token_hex(12)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        temporary_fd = os.open(
            temporary_name,
            flags,
            0o600,
            dir_fd=target_fd,
        )
        try:
            view = memoryview(content)
            while view:
                written = os.write(temporary_fd, view)
                if written <= 0:
                    raise OSError("short constitution write")
                view = view[written:]
            os.fsync(temporary_fd)
        finally:
            os.close(temporary_fd)
        os.replace(
            temporary_name,
            target.name,
            src_dir_fd=target_fd,
            dst_dir_fd=target_fd,
        )
        temporary_name = None
        os.fsync(target_fd)
        published = _read_regular_at(
            target_fd,
            target.name,
            missing_ok=False,
            code="target_invalid",
        )
        if (
            published is None
            or hashlib.sha256(published[0]).hexdigest()
            != sealed["draft_sha256"]
        ):
            raise ConstitutionPublicationError("target_invalid")
        return _publication_receipt(sealed)
    except ConstitutionPublicationError:
        raise
    except OSError as exc:
        raise ConstitutionPublicationError("publish_io") from exc
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=target_fd)
            except OSError:
                pass
        os.close(target_fd)


def _publication_receipt(request: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "target_path": request["target_path"],
        "target_sha256": request["draft_sha256"],
        "provider_receipt_sha256": request["provider_receipt_sha256"],
    }
