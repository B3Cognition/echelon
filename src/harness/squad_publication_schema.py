"""Immutable schema shared by publication staging and inspection."""

from __future__ import annotations

from dataclasses import dataclass


_ERROR_CODES = frozenset(
    {
        "manifest_invalid",
        "manifest_mismatch",
        "publish_io",
        "stage_corrupt",
        "stage_missing",
        "state_finalize",
        "target_drift",
    }
)


class PublicationError(Exception):
    """Bounded publication failure that never includes a filesystem path."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in _ERROR_CODES:
            code = "publish_io"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PublicationMarker:
    """Exact identity for one sealed publication manifest."""

    schema_version: int
    transaction_id: str
    manifest_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "transaction_id": self.transaction_id,
            "manifest_sha256": self.manifest_sha256,
        }
