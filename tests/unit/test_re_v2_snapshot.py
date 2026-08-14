from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from harness.re_v2.snapshot import (
    ReV2SnapshotError,
    capture_source_snapshot,
    validate_source_snapshot,
)


def _copied_snapshot(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
    return capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())


def _make_writable(path: Path) -> None:
    path.parent.chmod(path.parent.stat().st_mode | stat.S_IWUSR)
    path.chmod(path.stat().st_mode | stat.S_IWUSR)


@pytest.mark.unit
def test_dirty_source_is_copied_and_pinned(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")

    captured = capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())
    (source / "api.py").write_text("VALUE = 2\n", encoding="utf-8")

    assert captured.kind == "content-snapshot"
    assert (captured.read_root / "api.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    validate_source_snapshot(captured)


@pytest.mark.unit
def test_snapshot_validation_rejects_changed_bytes(tmp_path: Path) -> None:
    captured = _copied_snapshot(tmp_path)
    target = captured.read_root / "api.py"
    _make_writable(target)
    target.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ReV2SnapshotError, match="hash mismatch"):
        validate_source_snapshot(captured)


@pytest.mark.unit
def test_snapshot_validation_rejects_missing_and_extra_bytes(tmp_path: Path) -> None:
    captured = _copied_snapshot(tmp_path)
    target = captured.read_root / "api.py"
    _make_writable(target)
    target.unlink()
    with pytest.raises(ReV2SnapshotError, match="missing"):
        validate_source_snapshot(captured)

    target.write_text("VALUE = 1\n", encoding="utf-8")
    (captured.read_root / "extra.py").write_text("surprise\n", encoding="utf-8")
    with pytest.raises(ReV2SnapshotError, match="extra"):
        validate_source_snapshot(captured)


@pytest.mark.unit
def test_copied_snapshot_is_content_addressed_and_immutable(tmp_path: Path) -> None:
    first = _copied_snapshot(tmp_path)
    second = capture_source_snapshot(tmp_path / "source", tmp_path / "snapshots", exclusions=())

    assert first.snapshot_id == second.snapshot_id
    assert first.read_root == second.read_root
    assert not first.read_root.is_symlink()
    assert not first.manifest_path.is_symlink()
    assert not first.read_root.joinpath("api.py").stat().st_mode & stat.S_IWUSR
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["snapshot_id"] == first.snapshot_id
    assert manifest["entries"] == sorted(manifest["entries"], key=lambda item: item["path"])


@pytest.mark.unit
def test_copied_snapshot_rejects_symlinks_and_special_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file").write_text("contents", encoding="utf-8")
    (source / "linked").symlink_to(source / "file")

    with pytest.raises(ReV2SnapshotError, match="symlink"):
        capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())

    fifo = source / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(ReV2SnapshotError, match="symlink|special"):
        capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())


@pytest.mark.unit
@pytest.mark.parametrize("exclusions", [("../outside",), ("/absolute",), ("a/../../b",), ("./ok",)])
def test_exclusions_reject_unsafe_paths(tmp_path: Path, exclusions: tuple[str, ...]) -> None:
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(ReV2SnapshotError, match="exclusion"):
        capture_source_snapshot(source, tmp_path / "snapshots", exclusions=exclusions)


@pytest.mark.unit
def test_exclusions_are_deterministic_and_path_scoped(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "ignored").mkdir(parents=True)
    (source / "ignored" / "a.py").write_text("ignored", encoding="utf-8")
    (source / "keep.py").write_text("keep", encoding="utf-8")

    captured = capture_source_snapshot(source, tmp_path / "snapshots", exclusions=("ignored",))

    assert not (captured.read_root / "ignored").exists()
    assert (captured.read_root / "keep.py").exists()


@pytest.mark.unit
def test_clean_git_source_uses_pinned_detached_worktree_and_records_submodules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_git(args: list[str]) -> str:
        commands.append(args)
        if args[-2:] == ["rev-parse", "HEAD^{commit}"]:
            return "a" * 40 + "\n"
        if args[-3:] == ["status", "--porcelain", "--untracked-files=all"]:
            return ""
        if args[-3:] == ["submodule", "status", "--recursive"]:
            return "-" + "b" * 40 + " modules/example\n"
        if "add" in args:
            worktree = Path(args[-2])
            worktree.mkdir(parents=True)
            (worktree / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
        if "move" in args:
            old, new = map(Path, args[-2:])
            old.rename(new)
        return ""

    monkeypatch.setattr("harness.re_v2.snapshot.run_git", fake_git)
    captured = capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())

    assert captured.kind == "git-worktree"
    assert any(command[-2:] == ["rev-parse", "HEAD^{commit}"] for command in commands)
    assert any("add" in command and "--detach" in command for command in commands)
    assert any("move" in command for command in commands)
    manifest = json.loads(captured.manifest_path.read_text(encoding="utf-8"))
    assert manifest["git"]["commit"] == "a" * 40
    assert manifest["git"]["submodules"] == [{"commit": "b" * 40, "path": "modules/example"}]


@pytest.mark.unit
def test_duplicate_clean_git_snapshot_removes_temporary_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_git(args: list[str]) -> str:
        commands.append(args)
        if args[-2:] == ["rev-parse", "HEAD^{commit}"]:
            return "a" * 40 + "\n"
        if args[-3:] == ["status", "--porcelain", "--untracked-files=all"]:
            return ""
        if args[-3:] == ["submodule", "status", "--recursive"]:
            return ""
        if "add" in args:
            worktree = Path(args[-2])
            worktree.mkdir(parents=True)
            (worktree / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
        if "move" in args:
            Path(args[-2]).rename(Path(args[-1]))
        return ""

    monkeypatch.setattr("harness.re_v2.snapshot.run_git", fake_git)
    first = capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())
    second = capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())

    assert first == second
    assert any("remove" in command for command in commands)


@pytest.mark.unit
def test_existing_snapshot_id_is_never_overwritten(tmp_path: Path) -> None:
    captured = _copied_snapshot(tmp_path)
    marker = captured.read_root / "marker"
    _make_writable(captured.read_root)
    marker.write_text("do not replace", encoding="utf-8")

    with pytest.raises(ReV2SnapshotError, match="already exists"):
        capture_source_snapshot(tmp_path / "source", tmp_path / "snapshots", exclusions=())
    assert marker.read_text(encoding="utf-8") == "do not replace"
