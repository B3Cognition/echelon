import hashlib
import multiprocessing
import os
import socket
import stat
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import harness.squad_publication as publication
from harness.squad_publication import PublicationError, SquadPublicationTransaction
from harness.controller_lock_order import LockOrderViolation, controller_lock_order


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def secure_posix():
    if not publication._secure_posix_capabilities_available():
        pytest.skip("descriptor-safe POSIX publication is unavailable")


def test_complete_tree_capture_preserves_bytes_and_empty_directories(tmp_path):
    project = tmp_path.resolve()
    tree = project / "runs/spec-test/specs/001-game"
    (tree / "investigation").mkdir(parents=True)
    (tree / "empty").mkdir()
    (tree / "unknowns.md").write_bytes(b"### U-001: Subject\r\nExact body.\r\n")
    (tree / "investigation/U-001.md").write_bytes(b"Evidence\r\n")
    from harness.squad_source_snapshot import inspect_project_tree
    root = "runs/spec-test/specs/001-game"
    with inspect_project_tree(project, root) as snapshot:
        assert snapshot.path == root and snapshot.exists is True
        assert tuple(item.path for item in snapshot.directories) == (
            root, root + "/empty", root + "/investigation",
        )
        assert [(item.path, item.content) for item in snapshot.files] == [
            (root + "/investigation/U-001.md", b"Evidence\r\n"),
            (root + "/unknowns.md", b"### U-001: Subject\r\nExact body.\r\n"),
        ]


def _inspect(project, path="specs"):
    from harness.squad_source_snapshot import inspect_project_tree
    return inspect_project_tree(project, path)


def _tree(tmp_path):
    project = tmp_path.resolve()
    tree = project / "specs"
    (tree / "empty").mkdir(parents=True)
    (tree / "file").write_bytes(b"before")
    return project, tree


@pytest.mark.parametrize("name", ["specs", "absent/parent/specs"])
def test_absent_tree_and_ancestors_are_not_created(tmp_path, name):
    project = tmp_path.resolve()
    with _inspect(project, name) as snapshot:
        assert snapshot.path == name
        assert snapshot.exists is False
        assert snapshot.directories == snapshot.files == ()
    assert not (project / name.split("/")[0]).exists()


def test_empty_tree_contains_its_root_with_exact_mode(tmp_path):
    project = tmp_path.resolve()
    (project / "specs").mkdir()
    (project / "specs").chmod(0o751)
    with _inspect(project) as snapshot:
        assert snapshot.exists is True
        assert [(d.path, d.mode) for d in snapshot.directories] == [("specs", 0o751)]
        assert snapshot.files == ()


def test_deep_tree_traversal_does_not_depend_on_python_recursion(tmp_path):
    project = tmp_path.resolve()
    root = project / "specs"
    root.mkdir()
    current = root
    for _ in range(120):
        current = current / "d"
        current.mkdir()
    (current / "file").write_bytes(b"deep")
    recursion_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(100)
        with _inspect(project) as snapshot:
            assert len(snapshot.directories) == 121
            assert snapshot.directories[-1].path == "specs" + "/d" * 120
            assert snapshot.files[0].content == b"deep"
    finally:
        sys.setrecursionlimit(recursion_limit)


@pytest.mark.parametrize("when", ["before-yield", "exit"])
def test_new_members_inside_empty_nested_directory_are_detected(tmp_path, monkeypatch, when):
    project, tree = _tree(tmp_path)
    nested = tree / "empty/nested"
    nested.mkdir()
    original = publication._InspectionPaths.verify
    if when == "before-yield":
        def mutate_at_validation(self):
            if self.files:
                (nested / "new.bin").write_bytes(b"new")
            original(self)
        monkeypatch.setattr(publication._InspectionPaths, "verify", mutate_at_validation)
    with pytest.raises(PublicationError, match="^target_drift$"):
        with _inspect(project) as snapshot:
            assert "specs/empty/nested" in tuple(d.path for d in snapshot.directories)
            if when == "before-yield":
                pytest.fail("new nested member escaped")
            (nested / "new.bin").write_bytes(b"new")


def test_all_bytes_modes_order_and_detached_frozen_values(tmp_path, monkeypatch):
    project, tree = _tree(tmp_path)
    (tree / "file").unlink()
    (tree / ".hidden").mkdir()
    images = {".hidden/.data": b"\x00\xff\x80", "empty": b"", "z.txt": b" \t\r\n",
              "é.raw": "Žluťoučký\n".encode(), "large": bytes(range(256)) * 9000}
    (tree / "empty").rmdir()
    for name, content in images.items():
        (tree / name).write_bytes(content)
        (tree / name).chmod(0o604)
    tree.chmod(0o750)
    (tree / ".hidden").chmod(0o711)
    original = os.listdir
    # Keep the capability gate tied to the real supported listdir function.
    monkeypatch.setattr(publication, "_secure_posix_capabilities_available", lambda: True)
    monkeypatch.setattr(os, "listdir", lambda fd: list(reversed(original(fd))))
    with _inspect(project) as snapshot:
        assert [(d.path, d.mode) for d in snapshot.directories] == [
            ("specs", 0o750), ("specs/.hidden", 0o711),
        ]
        assert tuple(f.path for f in snapshot.files) == tuple("specs/" + n for n in sorted(images))
        for file in snapshot.files:
            content = images[file.path.removeprefix("specs/")]
            assert file.content == content
            assert file.image.kind == "file"
            assert file.image.sha256 == hashlib.sha256(content).hexdigest()
            assert file.image.mode == 0o604
        assert isinstance(snapshot.directories, tuple) and isinstance(snapshot.files, tuple)
        for value, field in [(snapshot, "path"), (snapshot.directories[0], "mode"),
                             (snapshot.files[0], "content"), (snapshot.files[0].image, "kind")]:
            with pytest.raises(FrozenInstanceError):
                setattr(value, field, None)
    (tree / ".hidden/.data").write_bytes(b"later")
    assert snapshot.files[0].content == b"\x00\xff\x80"


@pytest.mark.parametrize("path", [None, 1, Path("specs"), "", ".", "..", "/specs",
    "specs/", "./specs", "specs//nested", "specs/../nested", "specs/./nested",
    "specs\\nested", "specs\x00bad", "specs/\udcff"])
def test_invalid_tree_paths_fail_before_creating_control_paths(tmp_path, path):
    project = tmp_path.resolve()
    with pytest.raises(PublicationError, match="^manifest_invalid$"):
        with _inspect(project, path):
            pytest.fail("invalid path escaped")
    assert list(project.iterdir()) == []


@pytest.mark.parametrize("kind", ["missing", "file", "symlink", "ancestor-symlink"])
def test_invalid_project_roots_fail(tmp_path, kind):
    project = tmp_path.resolve()
    root = project / "root"
    if kind == "file":
        root.write_bytes(b"not directory")
    elif kind in {"symlink", "ancestor-symlink"}:
        (project / "actual/child").mkdir(parents=True)
        root.symlink_to(project / "actual", target_is_directory=True)
        if kind == "ancestor-symlink":
            root = root / "child"
    with pytest.raises(PublicationError, match="^manifest_invalid$"):
        with _inspect(root):
            pytest.fail("invalid root escaped")
    assert not (project / ".echelon").exists()


def test_relative_project_root_preserves_existing_inspection_contract(tmp_path, monkeypatch):
    project, _ = _tree(tmp_path)
    monkeypatch.chdir(project)
    with _inspect(Path(".")) as snapshot:
        assert snapshot.files[0].content == b"before"


@pytest.mark.parametrize("kind", ["root-symlink", "ancestor-symlink", "leaf-symlink", "root-file", "fifo", "socket"])
def test_unsupported_sources_are_rejected(tmp_path, monkeypatch, kind):
    project, tree = _tree(tmp_path)
    path = "specs"
    sock = None
    if kind in {"root-symlink", "ancestor-symlink"}:
        tree.rename(project / "actual")
        tree.symlink_to(project / "actual", target_is_directory=True)
        if kind == "ancestor-symlink":
            path = "specs/empty"
    elif kind == "leaf-symlink":
        (tree / "link").symlink_to(tree / "file")
    elif kind == "root-file":
        path = "specs/file"
    elif kind == "fifo":
        os.mkfifo(tree / "pipe")
    else:
        sock = socket.socket(socket.AF_UNIX)
        monkeypatch.chdir(tree)
        sock.bind("socket")
    try:
        with pytest.raises(PublicationError, match="^target_drift$"):
            with _inspect(project, path):
                pytest.fail("unsupported source escaped")
    finally:
        if sock is not None:
            sock.close()


def _mutate(project, tree, mutation):
    if mutation == "add-file":
        (tree / "new").write_bytes(b"new")
    elif mutation == "add-directory":
        (tree / "new").mkdir()
    elif mutation == "remove-file":
        (tree / "file").unlink()
    elif mutation == "remove-directory":
        (tree / "empty").rmdir()
    elif mutation == "rename-file":
        (tree / "file").rename(tree / "renamed")
    elif mutation == "rename-directory":
        (tree / "empty").rename(tree / "renamed")
    elif mutation == "replace-file":
        (tree / "new").write_bytes(b"before")
        (tree / "new").replace(tree / "file")
    elif mutation in {"replace-directory", "replace-tree", "replace-project"}:
        target = {"replace-directory": tree / "empty", "replace-tree": tree,
                  "replace-project": project}[mutation]
        target.rename(target.with_name(target.name + "-old"))
        target.mkdir()
    elif mutation == "same-size-write":
        (tree / "file").write_bytes(b"AFTER!")
    elif mutation == "file-mode":
        (tree / "file").chmod(0o600)
    elif mutation == "directory-mode":
        (tree / "empty").chmod(0o700)
    elif mutation == "tree-mode":
        tree.chmod(0o700)
    elif mutation == "nlink":
        os.link(tree / "file", project / "extra-link")


@pytest.mark.parametrize("when", ["before-yield", "exit"])
@pytest.mark.parametrize("mutation", ["add-file", "add-directory", "remove-file", "remove-directory",
    "rename-file", "rename-directory", "replace-file", "replace-directory", "replace-tree",
    "replace-project", "same-size-write", "file-mode", "directory-mode", "tree-mode", "nlink"])
def test_complete_bindings_reject_drift(tmp_path, monkeypatch, when, mutation):
    project, tree = _tree(tmp_path)
    (tree / "file").chmod(0o644)
    (tree / "empty").chmod(0o755)
    tree.chmod(0o755)
    original = publication._InspectionPaths.verify
    changed = False
    if when == "before-yield":
        def mutate_at_validation(self):
            nonlocal changed
            if self.files and not changed:
                changed = True
                _mutate(project, tree, mutation)
            original(self)
        monkeypatch.setattr(publication._InspectionPaths, "verify", mutate_at_validation)
    with pytest.raises(PublicationError, match="^target_drift$"):
        with _inspect(project):
            if when == "before-yield":
                pytest.fail("drift escaped entry validation")
            _mutate(project, tree, mutation)


@pytest.mark.parametrize("name", ["specs", "absent/parent/specs"])
@pytest.mark.parametrize("when", ["before-yield", "exit"])
def test_absence_binding_rejects_appearance(tmp_path, monkeypatch, name, when):
    project = tmp_path.resolve()
    original = publication._InspectionPaths.verify
    if when == "before-yield":
        def appear_at_validation(self):
            if self.missing:
                (project / name).mkdir(parents=True)
            original(self)
        monkeypatch.setattr(publication._InspectionPaths, "verify", appear_at_validation)
    with pytest.raises(PublicationError, match="^target_drift$"):
        with _inspect(project, name):
            if when == "before-yield":
                pytest.fail("appeared tree escaped")
            (project / name).mkdir(parents=True)


@pytest.mark.parametrize("kind", ["backslash", "invalid-encoding"])
def test_invalid_child_names_are_not_skipped(tmp_path, monkeypatch, kind):
    project, tree = _tree(tmp_path)
    name = "bad\\name" if kind == "backslash" else "bad\udcff"
    if kind == "backslash":
        (tree / name).write_bytes(b"invalid name")
    else:
        # macOS rejects undecodable names at creation; inject at real-FD listing.
        original = os.listdir
        inode = tree.stat().st_ino
        def invalid_listing(fd):
            names = original(fd)
            return names + [name] if os.fstat(fd).st_ino == inode else names
        monkeypatch.setattr(publication, "_secure_posix_capabilities_available", lambda: True)
        monkeypatch.setattr(os, "listdir", invalid_listing)
    with pytest.raises(PublicationError, match="^manifest_invalid$"):
        with _inspect(project):
            pytest.fail("invalid child name escaped")


@pytest.mark.parametrize("source", ["file", "empty", "tree"])
def test_inaccessible_sources_fail_instead_of_being_skipped(tmp_path, source):
    if os.geteuid() == 0:
        pytest.skip("root bypasses POSIX permission checks")
    project, tree = _tree(tmp_path)
    target = tree if source == "tree" else tree / source
    mode = stat.S_IMODE(target.stat().st_mode)
    target.chmod(0)
    try:
        with pytest.raises(PublicationError, match="^target_drift$"):
            with _inspect(project):
                pytest.fail("inaccessible source escaped")
    finally:
        target.chmod(mode)


def test_reader_only_initializes_existing_publication_lock_control_path(tmp_path):
    project, _ = _tree(tmp_path)
    def inventory():
        return {p.relative_to(project).as_posix():
                (p.read_bytes() if p.is_file() else None, stat.S_IMODE(p.stat().st_mode))
                for p in project.rglob("*")}
    before = inventory()
    with _inspect(project):
        pass
    after = inventory()
    assert set(after) - set(before) == {".echelon", ".echelon/runtime", ".echelon/runtime/publication.lock"}
    assert {name: after[name] for name in before} == before


@pytest.mark.parametrize("outcome", ["success", "caller-drift", "entry", "read", "list", "exit", "exit-list"])
def test_owned_descriptors_close_and_lock_remains_usable(tmp_path, monkeypatch, outcome):
    project, tree = _tree(tmp_path)
    opened = set()
    error = RuntimeError("original caller failure")
    fail_listing = outcome == "list"
    with monkeypatch.context() as patch:
        for name in ("_open_directory", "_open_regular_at"):
            original = getattr(publication, name)
            def record(*args, _original=original, **kwargs):
                fd = _original(*args, **kwargs)
                opened.add(fd)
                return fd
            patch.setattr(publication, name, record)
        if outcome == "entry":
            (tree / "unsupported").symlink_to(tree / "file")
        elif outcome == "read":
            def failed_read(fd, *, code):
                raise PublicationError(code)
            patch.setattr(publication, "_read_fd_bytes", failed_read)
        elif outcome in {"list", "exit-list"}:
            patch.setattr(publication, "_secure_posix_capabilities_available", lambda: True)
            original_listing = os.listdir
            def failed_listing(fd):
                if fail_listing:
                    raise PermissionError("injected listing failure")
                return original_listing(fd)
            patch.setattr(os, "listdir", failed_listing)
        def run():
            nonlocal fail_listing
            with _inspect(project):
                if outcome in {"exit", "caller-drift"}:
                    (tree / "new").mkdir()
                if outcome == "caller-drift":
                    raise error
                if outcome == "exit-list":
                    fail_listing = True
        if outcome == "success":
            run()
        elif outcome == "caller-drift":
            with pytest.raises(RuntimeError) as caught:
                run()
            assert caught.value is error
        else:
            with pytest.raises(PublicationError, match="^target_drift$"):
                run()
        assert opened
        for fd in opened:
            with pytest.raises(OSError):
                os.fstat(fd)
    if outcome == "entry":
        (tree / "unsupported").unlink()
    with _inspect(project):
        pass


def test_capability_and_lock_order_gates_precede_capture(tmp_path, monkeypatch):
    project, _ = _tree(tmp_path)
    with controller_lock_order("completion", "outer"):
        with pytest.raises(LockOrderViolation):
            with _inspect(project):
                pytest.fail("lock inversion escaped")
    assert not (project / ".echelon").exists()
    monkeypatch.setattr(publication, "_secure_posix_capabilities_available", lambda: False)
    with pytest.raises(PublicationError, match="^publish_io$"):
        with _inspect(project):
            pytest.fail("missing capabilities escaped")
    assert not (project / ".echelon").exists()


def test_bytes_changed_during_read_cannot_escape(tmp_path, monkeypatch):
    project, tree = _tree(tmp_path)
    original = publication._read_fd_bytes
    def changed_read(fd, *, code):
        content = original(fd, code=code)
        (tree / "file").write_bytes(b"AFTER!")
        return content
    monkeypatch.setattr(publication, "_read_fd_bytes", changed_read)
    with pytest.raises(PublicationError, match="^target_drift$"):
        with _inspect(project):
            pytest.fail("changed bytes escaped")


def _publish_child(project, squad, marker, connection):
    try:
        prepared = publication.load_prepared_publication(Path(project), Path(squad), marker)
        original = publication._fcntl.flock
        def observed_flock(fd, operation):
            if operation == publication._fcntl.LOCK_EX:
                try:
                    original(fd, operation | publication._fcntl.LOCK_NB)
                except BlockingIOError:
                    connection.send("blocked-by-publication-lock")
                else:
                    connection.send("unexpectedly-acquired")
                    return
            original(fd, operation)
        publication._fcntl.flock = observed_flock
        prepared.publish()
        connection.send("published")
    except BaseException as error:
        connection.send((type(error).__name__, str(error)))
    finally:
        connection.close()


def test_spawned_normal_publisher_waits_for_tree_reader_exit(tmp_path):
    project, tree = _tree(tmp_path)
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(project, squad, "1" * 32)
    staged = transaction.build_path("after")
    staged.write_bytes(b"after")
    transaction.add_write(Path("specs/file"), staged, owned_paths={Path("specs/file")})
    prepared = transaction.seal()
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_publish_child, args=(str(project), str(squad), prepared.marker, child))
    try:
        with _inspect(project):
            process.start()
            child.close()
            assert parent.poll(10), "publisher did not reach lock"
            assert parent.recv() == "blocked-by-publication-lock"
            assert (tree / "file").read_bytes() == b"before"
        assert parent.poll(10), "publisher did not progress after inspection"
        assert parent.recv() == "published"
        process.join(10)
        assert process.exitcode == 0
        assert (tree / "file").read_bytes() == b"after"
    finally:
        if process.is_alive():
            process.terminate()
            process.join(10)
        parent.close()
        child.close()
