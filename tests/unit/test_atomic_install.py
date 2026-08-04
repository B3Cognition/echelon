"""Atomic no-replace installation tests."""

from __future__ import annotations

import errno
from pathlib import Path

import pytest


def test_atomic_rename_no_replace_moves_source_when_destination_is_absent(
    tmp_path: Path,
) -> None:
    from echelon.atomic_install import atomic_rename_no_replace

    source = tmp_path / "source"
    source.mkdir()
    (source / "payload.txt").write_text("payload", encoding="utf-8")
    destination = tmp_path / "destination"

    atomic_rename_no_replace(source, destination)

    assert not source.exists()
    assert (destination / "payload.txt").read_text(encoding="utf-8") == "payload"


@pytest.mark.parametrize("destination_kind", ["directory", "file", "symlink"])
def test_atomic_rename_no_replace_never_overwrites_destination(
    tmp_path: Path,
    destination_kind: str,
) -> None:
    from echelon.atomic_install import atomic_rename_no_replace

    source = tmp_path / "source"
    source.mkdir()
    (source / "payload.txt").write_text("source", encoding="utf-8")
    destination = tmp_path / "destination"
    if destination_kind == "directory":
        destination.mkdir()
        (destination / "keep.txt").write_text("directory", encoding="utf-8")
    elif destination_kind == "file":
        destination.write_text("file", encoding="utf-8")
    else:
        target = tmp_path / "symlink-target"
        target.write_text("target", encoding="utf-8")
        destination.symlink_to(target)

    with pytest.raises(OSError) as raised:
        atomic_rename_no_replace(source, destination)

    assert raised.value.errno in {errno.EEXIST, errno.ENOTEMPTY}
    assert (source / "payload.txt").read_text(encoding="utf-8") == "source"
    if destination_kind == "directory":
        assert (destination / "keep.txt").read_text(encoding="utf-8") == "directory"
    elif destination_kind == "file":
        assert destination.read_text(encoding="utf-8") == "file"
    else:
        assert destination.is_symlink()
        assert destination.readlink() == target


def test_atomic_rename_no_replace_fails_closed_on_unsupported_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.atomic_install as atomic_install

    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "destination"
    monkeypatch.setattr(atomic_install.sys, "platform", "unsupported")

    with pytest.raises(OSError, match="unsupported"):
        atomic_install.atomic_rename_no_replace(source, destination)

    assert source.is_dir()
    assert not destination.exists()
