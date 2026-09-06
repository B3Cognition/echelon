"""Fail-closed identity for the deployed Banzai default-candidate protocol."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat


_MAX_PROTOCOL_FILE_BYTES = 1024 * 1024
_PROTOCOL_FILES = (
    Path(".echelon/prosaic/subagents/echelon.sage.md"),
    Path(".echelon/runtime/workflow/definition.yaml"),
    Path(".echelon/runtime/workflow/phases/phase1-why2.md"),
)


@dataclass(frozen=True)
class BanzaiProtocolFingerprint:
    """One verified deployed protocol identity or its fail-closed diagnostic."""

    fingerprint: str | None
    diagnostic: str = ""


def active_banzai_default_protocol_fingerprint(
    project_root: Path,
) -> BanzaiProtocolFingerprint:
    """Identify the deployed files that define WHY2 candidate behavior.

    A workspace controls these files, so incomplete or unsafe evidence never
    grants the controller an additional retry.  The final component is opened
    without following a symlink and is checked again from its file descriptor
    before its bounded bytes contribute to the digest.
    """
    digest = hashlib.sha256()
    for relative_path in _PROTOCOL_FILES:
        relative_name = relative_path.as_posix()
        payload_or_error = _read_protocol_file(project_root / relative_path)
        if isinstance(payload_or_error, str):
            return BanzaiProtocolFingerprint(
                fingerprint=None,
                diagnostic=f"{relative_name}: {payload_or_error}",
            )
        encoded_path = relative_name.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(len(payload_or_error).to_bytes(8, "big"))
        digest.update(payload_or_error)
    return BanzaiProtocolFingerprint(fingerprint=f"sha256:{digest.hexdigest()}")


def _read_protocol_file(path: Path) -> bytes | str:
    """Return one bounded regular file without granting symlink traversal."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        return exc.strerror or "unreadable"
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            return "not a regular file"
        if metadata.st_size > _MAX_PROTOCOL_FILE_BYTES:
            return "exceeds 1 MiB"
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            payload = stream.read(_MAX_PROTOCOL_FILE_BYTES + 1)
    except OSError as exc:
        return exc.strerror or "unreadable"
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(payload) > _MAX_PROTOCOL_FILE_BYTES:
        return "exceeds 1 MiB"
    return payload
