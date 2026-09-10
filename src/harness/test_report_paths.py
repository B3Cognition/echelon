"""Safe source-identity normalization for sandbox test reports."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


class TestReportPathError(ValueError):
    """Raised when a report cannot identify a test below the candidate mount."""


def normalize_test_report_path(
    value: Any,
    *,
    sandbox_worktree_mount: str | None = None,
) -> str:
    """Return a candidate-relative test path from one reporter field.

    Reporters commonly emit either ``tests/example.test.ts`` or an absolute
    sandbox path such as ``/workspace/tests/example.test.ts``.  Absolute paths
    are accepted only when they sit below the explicit candidate mount for the
    sandbox that produced the report; every other absolute or escaping path is
    rejected before source binding.
    """
    if not isinstance(value, str) or not value.strip():
        raise TestReportPathError("test file must be target-relative")
    raw = value.strip()
    if "\\" in raw:
        raise TestReportPathError("test file must be target-relative")

    path = PurePosixPath(raw)
    if path.is_absolute():
        mount = _sandbox_mount(sandbox_worktree_mount)
        if mount is None:
            raise TestReportPathError("test file must be target-relative")
        try:
            path = path.relative_to(mount)
        except ValueError as exc:
            raise TestReportPathError("test file must be target-relative") from exc

    if (
        path.is_absolute()
        or not path.parts
        or path == PurePosixPath(".")
        or any(part in {".", ".."} for part in raw.split("/"))
    ):
        raise TestReportPathError("test file must be target-relative")
    return path.as_posix()


def _sandbox_mount(value: str | None) -> PurePosixPath | None:
    if not isinstance(value, str) or not value.strip() or "\\" in value:
        return None
    mount = PurePosixPath(value.strip())
    if (
        not mount.is_absolute()
        or mount == PurePosixPath("/")
        or any(part in {".", ".."} for part in value.split("/"))
    ):
        return None
    return mount
