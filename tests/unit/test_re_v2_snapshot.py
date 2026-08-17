from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from harness.re_v2.snapshot import (
    CapturedSnapshot,
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


def _snapshot_marker(captured: CapturedSnapshot) -> Path:
    manifest_path = captured.manifest_path
    snapshot_id = captured.snapshot_id
    return manifest_path.parent.parent / ".snapshot-commits" / f"{snapshot_id}.json"


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout


def _init_git_repository(path: Path) -> None:
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "Snapshot Test")
    _git(path, "config", "user.email", "snapshot@example.invalid")


def _commit_all(repository: Path, message: str) -> str:
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "-m", message)
    return _git(repository, "rev-parse", "HEAD").strip()


def _nested_submodule_source(tmp_path: Path) -> tuple[Path, str, str]:
    inner = tmp_path / "inner"
    _init_git_repository(inner)
    (inner / "inner.txt").write_text("inner bytes\n", encoding="utf-8")
    inner_commit = _commit_all(inner, "inner")

    outer = tmp_path / "outer"
    _init_git_repository(outer)
    (outer / "outer.txt").write_text("outer bytes\n", encoding="utf-8")
    _commit_all(outer, "outer")
    _git(
        outer,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(inner),
        "nested folder",
    )
    outer_commit = _commit_all(outer, "add inner")

    source = tmp_path / "source"
    _init_git_repository(source)
    (source / "root.txt").write_text("root\n", encoding="utf-8")
    _commit_all(source, "root")
    _git(
        source,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(outer),
        "modules/outer",
    )
    _commit_all(source, "add outer")
    _git(
        source,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "update",
        "-q",
        "--init",
        "--recursive",
    )
    return source, outer_commit, inner_commit


def _capture_in_crashing_process(
    source: Path, destination: Path, fault_point: str
) -> subprocess.CompletedProcess[str]:
    script = """
import os
import sys
from pathlib import Path

from harness.re_v2.snapshot import capture_source_snapshot

point = sys.argv[3]

def fault(observed: str) -> None:
    if observed == point:
        os._exit(74)

capture_source_snapshot(
    Path(sys.argv[1]),
    Path(sys.argv[2]),
    exclusions=(),
    fault_hook=fault,
)
"""
    environment = os.environ.copy()
    source_path = str(Path(__file__).parents[2] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        value
        for value in (source_path, environment.get("PYTHONPATH", ""))
        if value
    )
    return subprocess.run(
        [sys.executable, "-c", script, str(source), str(destination), fault_point],
        check=False,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "fault_point",
    [
        "source_installed",
        "manifest_installed",
        "permissions_normalized",
        "bundle_fsynced",
        "final_promoted",
    ],
)
def test_copy_snapshot_crash_at_publication_boundary_is_retryable(
    tmp_path: Path, fault_point: str
) -> None:
    """Removing any staging/promotion recovery step must strand this ID."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
    destination = tmp_path / "snapshots"

    crashed = _capture_in_crashing_process(source, destination, fault_point)

    assert crashed.returncode == 74, crashed.stderr
    captured = capture_source_snapshot(source, destination, exclusions=())
    validate_source_snapshot(captured)
    assert [path.name for path in destination.glob("sha256:*")] == [
        captured.snapshot_id
    ]
    assert not list(destination.glob(".snapshot-stage-*"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "fault_point",
    [
        "stage_created",
        "worktree_added",
        "worktree_moved",
        "final_owner_replaced",
        "source_installed",
        "manifest_installed",
        "permissions_normalized",
        "bundle_fsynced",
        "final_promoted",
        "marker_linked",
        "marker_root_fsynced",
        "marker_destination_fsynced",
        "marker_temporary_cleaned",
        "final_validated",
    ],
)
def test_git_snapshot_crash_at_publication_boundary_repairs_registration(
    tmp_path: Path, fault_point: str
) -> None:
    """A crash must not strand a registered staging worktree or invalid ID."""
    source = tmp_path / "source"
    _init_git_repository(source)
    (source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(source, "source")
    destination = tmp_path / "snapshots"

    crashed = _capture_in_crashing_process(source, destination, fault_point)

    assert crashed.returncode == 74, crashed.stderr
    captured = capture_source_snapshot(source, destination, exclusions=())
    validate_source_snapshot(captured)
    worktrees = _git(source, "worktree", "list", "--porcelain")
    assert worktrees.count(f"worktree {captured.read_root}") == 1
    assert ".snapshot-stage-" not in worktrees
    assert not list(destination.glob(".snapshot-stage-*"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "fault_point",
    [
        "marker_linked",
        "marker_root_fsynced",
        "marker_destination_fsynced",
        "marker_temporary_cleaned",
        "final_validated",
    ],
)
def test_git_snapshot_marker_io_failure_does_not_poison_id(
    tmp_path: Path, fault_point: str
) -> None:
    source = tmp_path / "source"
    _init_git_repository(source)
    (source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(source, "source")
    destination = tmp_path / "snapshots"

    def fail(point: str) -> None:
        if point == fault_point:
            raise OSError(f"injected {point}")

    with pytest.raises(ReV2SnapshotError, match=fault_point):
        capture_source_snapshot(
            source, destination, exclusions=(), fault_hook=fail
        )

    captured = capture_source_snapshot(source, destination, exclusions=())
    validate_source_snapshot(captured)
    worktrees = _git(source, "worktree", "list", "--porcelain")
    assert worktrees.count(f"worktree {captured.read_root}") == 1
    assert ".snapshot-stage-" not in worktrees
    assert not list(destination.glob(".snapshot-stage-*"))


@pytest.mark.unit
def test_invalid_post_marker_bundle_cleanup_removes_marker_before_bundle(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _init_git_repository(source)
    (source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(source, "source")
    destination = tmp_path / "snapshots"

    def corrupt_then_fail(point: str) -> None:
        if point != "marker_destination_fsynced":
            return
        bundles = list(destination.glob("sha256:*"))
        assert len(bundles) == 1
        target = bundles[0] / "source/api.py"
        _make_writable(target)
        target.write_text("corrupt\n", encoding="utf-8")
        raise OSError("injected invalid committed pair")

    with pytest.raises(ReV2SnapshotError, match="invalid committed pair"):
        capture_source_snapshot(
            source,
            destination,
            exclusions=(),
            fault_hook=corrupt_then_fail,
        )

    assert not list(destination.glob(".snapshot-commits/*.json"))
    assert not list(destination.glob("sha256:*"))
    assert ".snapshot-stage-" not in _git(
        source, "worktree", "list", "--porcelain"
    )
    captured = capture_source_snapshot(source, destination, exclusions=())
    validate_source_snapshot(captured)


@pytest.mark.unit
@pytest.mark.parametrize(
    "fault_point",
    [
        "submodule_materialized:modules/outer",
        "submodule_materialized:modules/outer/nested folder",
    ],
)
def test_git_snapshot_crash_after_each_submodule_step_is_retryable(
    tmp_path: Path, fault_point: str
) -> None:
    source, _outer_commit, _inner_commit = _nested_submodule_source(tmp_path)
    destination = tmp_path / "snapshots"

    crashed = _capture_in_crashing_process(source, destination, fault_point)

    assert crashed.returncode == 74, crashed.stderr
    captured = capture_source_snapshot(source, destination, exclusions=())
    validate_source_snapshot(captured)
    worktrees = _git(source, "worktree", "list", "--porcelain")
    assert worktrees.count(f"worktree {captured.read_root}") == 1
    assert ".snapshot-stage-" not in worktrees
    assert not list(destination.glob(".snapshot-stage-*"))


@pytest.mark.unit
def test_concurrent_same_id_capture_adopts_one_committed_bundle(tmp_path: Path) -> None:
    """Removing the per-ID lock/no-replace adoption path must lose one writer."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
    destination = tmp_path / "snapshots"
    ready = tmp_path / "ready"
    script = """
import os
import sys
import time
from pathlib import Path

from harness.re_v2.snapshot import capture_source_snapshot

ready = Path(sys.argv[3])

def fault(point: str) -> None:
    if point != "bundle_fsynced":
        return
    ready.mkdir(exist_ok=True)
    (ready / str(os.getpid())).write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + 10
    while len(list(ready.iterdir())) < 2:
        if time.monotonic() >= deadline:
            raise RuntimeError("concurrent capture barrier timed out")
        time.sleep(0.01)

captured = capture_source_snapshot(
    Path(sys.argv[1]), Path(sys.argv[2]), exclusions=(), fault_hook=fault
)
print(captured.snapshot_id)
"""
    environment = os.environ.copy()
    source_path = str(Path(__file__).parents[2] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        value
        for value in (source_path, environment.get("PYTHONPATH", ""))
        if value
    )
    command = [
        sys.executable,
        "-c",
        script,
        str(source),
        str(destination),
        str(ready),
    ]
    processes = [
        subprocess.Popen(
            command,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    results = [process.communicate(timeout=20) for process in processes]

    assert [process.returncode for process in processes] == [0, 0], results
    assert results[0][0].strip() == results[1][0].strip()
    captured = capture_source_snapshot(source, destination, exclusions=())
    assert captured.snapshot_id == results[0][0].strip()
    validate_source_snapshot(captured)
    assert [path.name for path in destination.glob("sha256:*")] == [
        captured.snapshot_id
    ]
    assert not list(destination.glob(".snapshot-stage-*"))


@pytest.mark.unit
def test_snapshot_validation_rejects_noncanonical_marker_bytes(tmp_path: Path) -> None:
    captured = _copied_snapshot(tmp_path)
    marker = _snapshot_marker(captured)
    value = json.loads(marker.read_bytes())
    _make_writable(marker)
    marker.write_text(json.dumps(value, indent=2), encoding="utf-8")
    marker.chmod(0o400)

    with pytest.raises(ReV2SnapshotError, match="canonical"):
        validate_source_snapshot(captured)


@pytest.mark.unit
def test_snapshot_validation_rejects_writable_marker(tmp_path: Path) -> None:
    captured = _copied_snapshot(tmp_path)
    marker = _snapshot_marker(captured)
    _make_writable(marker)

    with pytest.raises(ReV2SnapshotError, match="mode|writable"):
        validate_source_snapshot(captured)


@pytest.mark.unit
def test_snapshot_validation_rejects_hardlinked_marker(tmp_path: Path) -> None:
    captured = _copied_snapshot(tmp_path)
    marker = _snapshot_marker(captured)
    os.link(marker, marker.parent / "alias.json", follow_symlinks=False)

    with pytest.raises(ReV2SnapshotError, match="link"):
        validate_source_snapshot(captured)


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
def test_clean_git_source_uses_pinned_detached_worktree_and_repairs_metadata(
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
        if "add" in args:
            worktree = Path(args[-2])
            worktree.mkdir(parents=True)
            (worktree / ".git").write_text("gitdir: fake\n", encoding="utf-8")
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
    assert manifest["git"]["submodules"] == []


@pytest.mark.unit
def test_clean_git_snapshot_materializes_exact_initialized_submodule_bytes(
    tmp_path: Path,
) -> None:
    """Skipping local object materialization must leave this assertion empty."""
    module = tmp_path / "module"
    _init_git_repository(module)
    expected = b"submodule\x00bytes\n"
    (module / "payload.bin").write_bytes(expected)
    module_commit = _commit_all(module, "module")

    source = tmp_path / "source"
    _init_git_repository(source)
    (source / "root.txt").write_text("root\n", encoding="utf-8")
    _commit_all(source, "root")
    _git(
        source,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(module),
        "modules/example",
    )
    _commit_all(source, "add module")

    captured = capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())

    assert captured.kind == "git-worktree"
    assert (captured.read_root / "modules/example/payload.bin").read_bytes() == expected
    assert not (captured.read_root / "modules/example/.git").exists()
    manifest = json.loads(captured.manifest_path.read_bytes())
    assert manifest["git"]["submodules"] == [
        {"commit": module_commit, "path": "modules/example"}
    ]
    assert "modules/example/payload.bin" in {
        entry["path"] for entry in manifest["entries"]
    }
    validate_source_snapshot(captured)


@pytest.mark.unit
def test_dirty_submodule_falls_back_to_copy_without_nested_git_metadata(
    tmp_path: Path,
) -> None:
    """Copy fallback must not leak a nested submodule's operational `.git`."""
    module = tmp_path / "module"
    _init_git_repository(module)
    (module / "payload.txt").write_text("committed\n", encoding="utf-8")
    _commit_all(module, "module")

    source = tmp_path / "source"
    _init_git_repository(source)
    (source / "root.txt").write_text("root\n", encoding="utf-8")
    _commit_all(source, "root")
    _git(
        source,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(module),
        "modules/example",
    )
    _commit_all(source, "add module")
    (source / "modules/example/payload.txt").write_text(
        "dirty bytes\n", encoding="utf-8"
    )

    captured = capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())

    assert captured.kind == "content-snapshot"
    assert (captured.read_root / "modules/example/payload.txt").read_text(
        encoding="utf-8"
    ) == "dirty bytes\n"
    assert not (captured.read_root / "modules/example/.git").exists()
    manifest = json.loads(captured.manifest_path.read_bytes())
    assert all(not entry["path"].endswith("/.git") for entry in manifest["entries"])
    validate_source_snapshot(captured)


@pytest.mark.unit
def test_mismatched_submodule_falls_back_to_exact_content_copy(tmp_path: Path) -> None:
    module = tmp_path / "module"
    _init_git_repository(module)
    (module / "payload.txt").write_text("old bytes\n", encoding="utf-8")
    old_commit = _commit_all(module, "old")
    (module / "payload.txt").write_text("pinned bytes\n", encoding="utf-8")
    _commit_all(module, "pinned")

    source = tmp_path / "source"
    _init_git_repository(source)
    (source / "root.txt").write_text("root\n", encoding="utf-8")
    _commit_all(source, "root")
    _git(
        source,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(module),
        "modules/example",
    )
    _commit_all(source, "add module")
    _git(source / "modules/example", "checkout", "-q", old_commit)

    captured = capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())

    assert captured.kind == "content-snapshot"
    assert (captured.read_root / "modules/example/payload.txt").read_text(
        encoding="utf-8"
    ) == "old bytes\n"
    assert not (captured.read_root / "modules/example/.git").exists()
    validate_source_snapshot(captured)


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
            (worktree / ".git").write_text("gitdir: fake\n", encoding="utf-8")
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
def test_recursive_submodules_are_materialized_with_root_relative_identities(
    tmp_path: Path,
) -> None:
    source, outer_commit, inner_commit = _nested_submodule_source(tmp_path)

    captured = capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())

    assert (captured.read_root / "modules/outer/outer.txt").read_text(
        encoding="utf-8"
    ) == "outer bytes\n"
    assert (
        captured.read_root / "modules/outer/nested folder/inner.txt"
    ).read_text(encoding="utf-8") == "inner bytes\n"
    assert not (captured.read_root / "modules/outer/.git").exists()
    assert not (captured.read_root / "modules/outer/nested folder/.git").exists()
    manifest = json.loads(captured.manifest_path.read_text(encoding="utf-8"))
    assert manifest["git"]["submodules"] == [
        {"commit": outer_commit, "path": "modules/outer"},
        {"commit": inner_commit, "path": "modules/outer/nested folder"},
    ]
    validate_source_snapshot(captured)


@pytest.mark.unit
def test_uninitialized_submodule_fails_closed_without_fetching(tmp_path: Path) -> None:
    module = tmp_path / "module"
    _init_git_repository(module)
    (module / "payload.txt").write_text("payload\n", encoding="utf-8")
    _commit_all(module, "module")

    source = tmp_path / "source"
    _init_git_repository(source)
    (source / "root.txt").write_text("root\n", encoding="utf-8")
    _commit_all(source, "root")
    _git(
        source,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(module),
        "modules/uninitialized folder",
    )
    _commit_all(source, "add module")
    _git(
        source,
        "submodule",
        "deinit",
        "-q",
        "-f",
        "--",
        "modules/uninitialized folder",
    )

    with pytest.raises(ReV2SnapshotError, match="not initialized locally|offline"):
        capture_source_snapshot(source, tmp_path / "snapshots", exclusions=())

    assert not list((tmp_path / "snapshots").glob("sha256:*"))


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
            (worktree / ".git").write_text("gitdir: fake\n", encoding="utf-8")
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
    # The registered worktree is retained under its hidden owned staging path;
    # a failed deregistration must never make it discoverable as a snapshot ID.
    assert list((tmp_path / "snapshots").glob(".snapshot-stage-*/source/api.py"))
    assert not list((tmp_path / "snapshots").glob("sha256:*"))


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
        if "move" in args:
            Path(args[-2]).rename(Path(args[-1]))
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
