"""Durable owned-tree finalization tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_durable_tree_syncs_files_then_directories_bottom_up_and_sets_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.durable_tree as durable_tree

    root = tmp_path / "owned"
    child = root / "child"
    child.mkdir(parents=True)
    root.chmod(0o700)
    child.chmod(0o777)
    nested_file = child / "nested.txt"
    root_file = root / "root.txt"
    nested_file.write_text("nested", encoding="utf-8")
    root_file.write_text("root", encoding="utf-8")
    synced: list[Path] = []
    monkeypatch.setattr(
        durable_tree,
        "_sync_descriptor",
        lambda _descriptor, path: synced.append(path),
    )

    durable_tree.durably_sync_owned_tree(root, normalize_directory_modes=True)

    assert synced == [nested_file, child, root_file, root]
    assert root.stat().st_mode & 0o777 == 0o755
    assert child.stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize("entry_kind", ["symlink", "hardlink", "fifo"])
def test_durable_tree_rejects_unowned_or_special_entries(
    tmp_path: Path,
    entry_kind: str,
) -> None:
    from echelon.durable_tree import DurableTreeError, durably_sync_owned_tree

    root = tmp_path / "owned"
    root.mkdir()
    source = root / "source.txt"
    source.write_text("source", encoding="utf-8")
    if entry_kind == "symlink":
        (root / "unsafe").symlink_to(source)
    elif entry_kind == "hardlink":
        os.link(source, root / "unsafe")
    else:
        os.mkfifo(root / "unsafe")

    with pytest.raises(DurableTreeError, match=entry_kind):
        durably_sync_owned_tree(root)


def test_durable_tree_fails_closed_when_any_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.durable_tree as durable_tree

    root = tmp_path / "owned"
    root.mkdir()
    payload = root / "payload.txt"
    payload.write_text("payload", encoding="utf-8")
    attempts: list[Path] = []

    def fail(_descriptor: int, path: Path) -> None:
        attempts.append(path)
        raise OSError("injected fsync failure")

    monkeypatch.setattr(durable_tree, "_sync_descriptor", fail)

    with pytest.raises(OSError, match="injected fsync failure"):
        durable_tree.durably_sync_owned_tree(root)

    assert attempts == [payload]


def test_durable_tree_rejects_root_rename_and_replacement_during_final_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.durable_tree as durable_tree

    root = tmp_path / "owned"
    root.mkdir()
    (root / "payload.txt").write_text("payload", encoding="utf-8")
    displaced = tmp_path / "displaced"
    original_sync = durable_tree._sync_descriptor

    def replace_after_sync(descriptor: int, path: Path) -> None:
        original_sync(descriptor, path)
        if path == root:
            root.rename(displaced)
            root.mkdir()
            (root / "replacement.txt").write_text("replacement", encoding="utf-8")

    monkeypatch.setattr(durable_tree, "_sync_descriptor", replace_after_sync)

    with pytest.raises(durable_tree.DurableTreeError, match="root.*swapped"):
        durable_tree.durably_sync_owned_tree(root)


def test_durable_tree_rejects_child_rename_and_replacement_after_recursion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.durable_tree as durable_tree

    root = tmp_path / "owned"
    child = root / "child"
    child.mkdir(parents=True)
    (child / "payload.txt").write_text("payload", encoding="utf-8")
    displaced = root / "displaced"
    original_sync = durable_tree._sync_descriptor

    def replace_after_sync(descriptor: int, path: Path) -> None:
        original_sync(descriptor, path)
        if path == child:
            child.rename(displaced)
            child.mkdir()
            (child / "replacement.txt").write_text("replacement", encoding="utf-8")

    monkeypatch.setattr(durable_tree, "_sync_descriptor", replace_after_sync)

    with pytest.raises(durable_tree.DurableTreeError, match="directory was swapped"):
        durable_tree.durably_sync_owned_tree(root)
