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

    _make_writable(captured.read_root)
    (captured.read_root / "ignored").mkdir()
    (captured.read_root / "ignored" / "late.py").write_text("late", encoding="utf-8")
    with pytest.raises(ReV2SnapshotError, match="extra"):
        validate_source_snapshot(captured)


@pytest.mark.unit
def test_capture_rejects_destination_inside_source_or_source_as_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")

    for destination in (source, source / "snapshots"):
        with pytest.raises(ReV2SnapshotError, match="destination"):
            capture_source_snapshot(source, destination, exclusions=())


@pytest.mark.unit
def test_validation_rejects_writable_or_changed_identity_mode(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    executable = source / "run"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    captured = capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())

    target = captured.read_root / "run"
    _make_writable(target)
    target.chmod(0o644)
    with pytest.raises(ReV2SnapshotError, match="mode"):
        validate_source_snapshot(captured)


@pytest.mark.unit
def test_copy_refuses_source_changes_during_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    target = source / "api.py"
    target.write_text("before", encoding="utf-8")

    import harness.re_v2.snapshot as snapshot_module

    original_copy = snapshot_module._copy_regular_files

    def mutate_after_copy(*args: object) -> None:
        original_copy(*args)  # type: ignore[arg-type]
        target.write_text("after", encoding="utf-8")

    monkeypatch.setattr(snapshot_module, "_copy_regular_files", mutate_after_copy)
    with pytest.raises(ReV2SnapshotError, match="source changed"):
        capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())
    assert not list((tmp_path / "snapshots").glob("sha256:*"))


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
        if args[-2:] == ["rev-parse", "--show-toplevel"]:
            return str(source) + "\n"
        if args[-2:] == ["rev-parse", "HEAD^{commit}"]:
            return "a" * 40 + "\n"
        if args[-4:] == ["status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"]:
            return ""
        if "foreach" in args:
            return "modules/example folder\0" + "b" * 40 + "\0"
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
    assert any(command[-1:] == ["--ignore-submodules=none"] for command in commands)
    assert any("add" in command and "--detach" in command for command in commands)
    assert any("move" in command for command in commands)
    manifest = json.loads(captured.manifest_path.read_text(encoding="utf-8"))
    assert manifest["git"]["commit"] == "a" * 40
    assert manifest["git"]["submodules"] == [{"commit": "b" * 40, "path": "modules/example folder"}]


@pytest.mark.unit
def test_git_snapshot_physically_omits_tracked_excluded_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    commands: list[list[str]] = []

    def fake_git(args: list[str]) -> str:
        commands.append(args)
        if args[-2:] == ["rev-parse", "--show-toplevel"]:
            return str(source) + "\n"
        if args[-2:] == ["rev-parse", "HEAD^{commit}"]:
            return "a" * 40 + "\n"
        if args[-1:] == ["--ignore-submodules=none"] or "foreach" in args:
            return ""
        if "add" in args:
            worktree = Path(args[-2])
            worktree.mkdir(parents=True)
            (worktree / "keep.py").write_text("keep", encoding="utf-8")
            (worktree / "secret.txt").write_text("excluded", encoding="utf-8")
        if "move" in args:
            Path(args[-2]).rename(Path(args[-1]))
        return ""

    monkeypatch.setattr("harness.re_v2.snapshot.run_git", fake_git)
    captured = capture_source_snapshot(source, tmp_path / "snapshots", exclusions=("secret.txt",))

    assert not (captured.read_root / "secret.txt").exists()
    assert (captured.read_root / "keep.py").exists()
    validate_source_snapshot(captured)


@pytest.mark.unit
def test_recursive_submodule_identities_include_nested_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()

    def fake_git(args: list[str]) -> str:
        if "foreach" in args:
            return "modules/outer\0" + "b" * 40 + "\0modules/outer/nested folder\0" + "c" * 40 + "\0"
        if args[-2:] == ["rev-parse", "--show-toplevel"]:
            return str(source) + "\n"
        if args[-2:] == ["rev-parse", "HEAD^{commit}"]:
            return "a" * 40 + "\n"
        if args[-1:] == ["--ignore-submodules=none"]:
            return ""
        if "add" in args:
            worktree = Path(args[-2])
            worktree.mkdir(parents=True)
            (worktree / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
        if "move" in args:
            Path(args[-2]).rename(Path(args[-1]))
        return ""

    monkeypatch.setattr("harness.re_v2.snapshot.run_git", fake_git)
    captured = capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())
    manifest = json.loads(captured.manifest_path.read_text(encoding="utf-8"))
    assert manifest["git"]["submodules"] == [
        {"commit": "b" * 40, "path": "modules/outer"},
        {"commit": "c" * 40, "path": "modules/outer/nested folder"},
    ]


@pytest.mark.unit
def test_submodule_identities_include_uninitialized_and_root_relative_nested_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()

    def fake_git(args: list[str]) -> str:
        if args[-3:] == ["ls-files", "--stage", "-z"]:
            return (
                "160000 " + "b" * 40 + " 0\tmodules/uninitialized folder\0"
                + "160000 " + "c" * 40 + " 0\tmodules/outer\0"
            )
        if "foreach" in args:
            # Git's $sm_path would be "nested folder" here; $displaypath is root-relative.
            return "modules/outer\0" + "c" * 40 + "\0modules/outer/nested folder\0" + "d" * 40 + "\0"
        if args[-2:] == ["rev-parse", "--show-toplevel"]:
            return str(source) + "\n"
        if args[-2:] == ["rev-parse", "HEAD^{commit}"]:
            return "a" * 40 + "\n"
        if args[-1:] == ["--ignore-submodules=none"]:
            return ""
        if "add" in args:
            worktree = Path(args[-2])
            worktree.mkdir(parents=True)
            (worktree / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
        if "move" in args:
            Path(args[-2]).rename(Path(args[-1]))
        return ""

    monkeypatch.setattr("harness.re_v2.snapshot.run_git", fake_git)
    captured = capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())
    manifest = json.loads(captured.manifest_path.read_text(encoding="utf-8"))
    assert manifest["git"]["submodules"] == [
        {"commit": "c" * 40, "path": "modules/outer"},
        {"commit": "d" * 40, "path": "modules/outer/nested folder"},
        {"commit": "b" * 40, "path": "modules/uninitialized folder"},
    ]


@pytest.mark.unit
def test_git_subdirectory_and_dirty_submodule_use_copied_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")

    def subdirectory_git(args: list[str]) -> str:
        if args[-2:] == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path) + "\n"
        raise subprocess.CalledProcessError(1, args)

    import subprocess

    monkeypatch.setattr("harness.re_v2.snapshot.run_git", subdirectory_git)
    assert capture_source_snapshot(source, tmp_path / "snapshots", exclusions=()).kind == "content-snapshot"

    def dirty_submodule_git(args: list[str]) -> str:
        if args[-2:] == ["rev-parse", "--show-toplevel"]:
            return str(source) + "\n"
        if args[-2:] == ["rev-parse", "HEAD^{commit}"]:
            return "a" * 40 + "\n"
        if args[-1:] == ["--ignore-submodules=none"]:
            return " M nested-module\n"
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr("harness.re_v2.snapshot.run_git", dirty_submodule_git)
    assert capture_source_snapshot(source, tmp_path / "other-snapshots", exclusions=()).kind == "content-snapshot"


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
        if args[-2:] == ["rev-parse", "--show-toplevel"]:
            return str(source) + "\n"
        if args[-2:] == ["rev-parse", "HEAD^{commit}"]:
            return "a" * 40 + "\n"
        if args[-4:] == ["status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"]:
            return ""
        if "foreach" in args:
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
def test_git_publish_failure_deregisters_and_removes_only_new_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_git(args: list[str]) -> str:
        commands.append(args)
        if args[-2:] == ["rev-parse", "--show-toplevel"]:
            return str(source) + "\n"
        if args[-2:] == ["rev-parse", "HEAD^{commit}"]:
            return "a" * 40 + "\n"
        if args[-1:] == ["--ignore-submodules=none"] or "foreach" in args:
            return ""
        if "add" in args:
            worktree = Path(args[-2])
            worktree.mkdir(parents=True)
            (worktree / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
        if "move" in args:
            Path(args[-2]).rename(Path(args[-1]))
        return ""

    monkeypatch.setattr("harness.re_v2.snapshot.run_git", fake_git)
    monkeypatch.setattr("harness.re_v2.snapshot._publish_manifest", lambda *_: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(ReV2SnapshotError, match="disk full"):
        capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())
    assert any("remove" in command for command in commands)
    assert not list((tmp_path / "snapshots").glob("sha256:*"))


@pytest.mark.unit
def test_failed_git_deregistration_preserves_registered_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    commands: list[list[str]] = []

    def fake_git(args: list[str]) -> str:
        commands.append(args)
        if args[-2:] == ["rev-parse", "--show-toplevel"]:
            return str(source) + "\n"
        if args[-2:] == ["rev-parse", "HEAD^{commit}"]:
            return "a" * 40 + "\n"
        if args[-1:] == ["--ignore-submodules=none"] or "foreach" in args:
            return ""
        if "add" in args:
            worktree = Path(args[-2])
            worktree.mkdir(parents=True)
            (worktree / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
        if "move" in args:
            Path(args[-2]).rename(Path(args[-1]))
        if "remove" in args:
            raise OSError("worktree still registered")
        return ""

    monkeypatch.setattr("harness.re_v2.snapshot.run_git", fake_git)
    monkeypatch.setattr("harness.re_v2.snapshot._publish_manifest", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(ReV2SnapshotError, match="cleanup failed"):
        capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())
    assert list((tmp_path / "snapshots").glob("sha256:*/source/api.py"))


@pytest.mark.unit
def test_git_prepublication_failure_deregisters_temporary_worktree_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_git(args: list[str]) -> str:
        commands.append(args)
        if args[-2:] == ["rev-parse", "--show-toplevel"]:
            return str(source) + "\n"
        if args[-2:] == ["rev-parse", "HEAD^{commit}"]:
            return "a" * 40 + "\n"
        if args[-1:] == ["--ignore-submodules=none"]:
            return ""
        if "add" in args:
            worktree = Path(args[-2])
            worktree.mkdir(parents=True)
            (worktree / "unsafe").symlink_to(source / "api.py")
        return ""

    monkeypatch.setattr("harness.re_v2.snapshot.run_git", fake_git)
    with pytest.raises(ReV2SnapshotError, match="symlink"):
        capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())
    assert sum("remove" in command for command in commands) == 1


@pytest.mark.unit
def test_existing_snapshot_id_is_never_overwritten(tmp_path: Path) -> None:
    captured = _copied_snapshot(tmp_path)
    marker = captured.read_root / "marker"
    _make_writable(captured.read_root)
    marker.write_text("do not replace", encoding="utf-8")

    with pytest.raises(ReV2SnapshotError, match="already exists"):
        capture_source_snapshot(tmp_path / "source", tmp_path / "snapshots", exclusions=())
    assert marker.read_text(encoding="utf-8") == "do not replace"
