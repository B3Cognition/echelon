import hashlib
import multiprocessing
import os
import socket
import stat
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

import harness.squad_publication as publication
from harness.controller_lock_order import LockOrderViolation, controller_lock_order
from harness.squad_publication import PublicationError, SquadPublicationTransaction


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def secure_posix():
    if not publication._secure_posix_capabilities_available():
        pytest.skip("descriptor-safe POSIX publication is unavailable")


def test_sealed_images_and_unchanged_dependencies_share_one_observation(tmp_path):
    from pathlib import Path
    from harness.squad_publication import SquadPublicationTransaction
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs/game/investigation").mkdir(parents=True)
    (project / "specs/game/unknowns.md").write_bytes(b"before\r\n")
    (project / "specs/game/investigation/U-001.md").write_bytes(b"evidence\r\n")
    (project / ".echelon").mkdir(exist_ok=True)
    (project / ".echelon/constitution.md").write_bytes(b"rules\r\n")
    transaction = SquadPublicationTransaction.begin(project, squad, "1" * 32)
    stage = transaction.build_path("after.md")
    stage.write_bytes(b"after\r\n")
    target = Path("specs/game/unknowns.md")
    transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(
        tree_paths=("specs/game",), file_paths=(".echelon/constitution.md",),
    ) as snapshot:
        operation, = snapshot.publication.operations
        assert (operation.current_bytes, operation.postimage_bytes) == (b"before\r\n", b"after\r\n")
        assert [(item.path, item.content) for item in snapshot.trees[0].files] == [
            ("specs/game/investigation/U-001.md", b"evidence\r\n"),
            ("specs/game/unknowns.md", b"before\r\n"),
        ]
        assert snapshot.files[0].content == b"rules\r\n"
    assert (project / target).read_bytes() == b"before\r\n"


def _prepared(tmp_path):
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "target").write_bytes(b"before")
    transaction = SquadPublicationTransaction.begin(project, squad, "2" * 32)
    stage = transaction.build_path("after")
    stage.write_bytes(b"after")
    transaction.add_write(Path("target"), stage, owned_paths={Path("target")})
    return project, transaction.seal(), stage


def _inventory(project):
    return {p.relative_to(project).as_posix():
            (p.read_bytes() if p.is_file() else None, stat.S_IMODE(p.stat().st_mode))
            for p in project.rglob("*")}


def test_sorted_complete_detached_sources_and_unchanged_authority(tmp_path):
    project, prepared, _ = _prepared(tmp_path)
    (project / "z/nested/empty").mkdir(parents=True)
    (project / "a").mkdir()
    (project / "z/.hidden").write_bytes(b"\x00\xff\r\n")
    (project / "z/žluťoučký").write_bytes("Příliš\r\n".encode())
    (project / "empty").write_bytes(b"")
    (project / "rules").write_bytes(b"rules\r\n")
    (project / ".echelon/identity").mkdir(parents=True)
    (project / ".echelon/identity/sentinel").write_bytes(b"authority untouched")
    (project / "z").chmod(0o751)
    (project / "z/nested").chmod(0o705)
    (project / "z/nested/empty").chmod(0o711)
    (project / "z/.hidden").chmod(0o604)
    (project / "empty").chmod(0o600)
    trees = ["z", "missing/tree", "a"]
    files = ["rules", "missing-file", "empty", "absent/file"]
    before = _inventory(project)
    with prepared.inspect_sources(tree_paths=trees, file_paths=files) as snapshot:
        trees.clear()
        files.clear()
        assert tuple(t.path for t in snapshot.trees) == ("a", "missing/tree", "z")
        assert [(t.exists, len(t.directories), len(t.files)) for t in snapshot.trees] == [
            (True, 1, 0), (False, 0, 0), (True, 3, 2),
        ]
        assert [(d.path, d.mode) for d in snapshot.trees[2].directories] == [
            ("z", 0o751), ("z/nested", 0o705), ("z/nested/empty", 0o711),
        ]
        assert [(f.path, f.content) for f in snapshot.trees[2].files] == [
            ("z/.hidden", b"\x00\xff\r\n"), ("z/žluťoučký", "Příliš\r\n".encode()),
        ]
        hidden = snapshot.trees[2].files[0]
        assert (hidden.image.sha256, hidden.image.mode) == (hashlib.sha256(b"\x00\xff\r\n").hexdigest(), 0o604)
        assert [(f.path, f.image.kind, f.content) for f in snapshot.files] == [
            ("absent/file", "missing", None), ("empty", "file", b""),
            ("missing-file", "missing", None), ("rules", "file", b"rules\r\n"),
        ]
        assert snapshot.files[1].image.mode == 0o600
        assert snapshot.files[1].image.sha256 == hashlib.sha256(b"").hexdigest()
        assert snapshot.files[0].image.sha256 is snapshot.files[0].image.mode is None
        assert tuple(o.target for o in snapshot.publication.operations) == ("target",)
        for value, field in ((snapshot, "files"), (snapshot.files[0], "content"),
                             (snapshot.trees[2], "files")):
            with pytest.raises(FrozenInstanceError):
                setattr(value, field, ())
        assert isinstance(snapshot.trees, tuple) and isinstance(snapshot.files, tuple)
    after = _inventory(project)
    assert set(after) - set(before) == {".echelon/runtime", ".echelon/runtime/publication.lock"}
    assert {name: after[name] for name in before} == before
    (project / "rules").write_bytes(b"later")
    assert snapshot.files[3].content == b"rules\r\n"


@pytest.mark.parametrize("interrupted", [False, True])
def test_complete_operations_shared_stage_and_global_prefix(tmp_path, interrupted):
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(project, squad, "3" * 32)
    shared = transaction.build_path("shared")
    shared.write_bytes(b"new")
    shared.chmod(0o604)
    for name, content, mode in (("a", b"old", 0o640), ("b", b"new", 0o600),
                                ("c", b"new", 0o604), ("d", b"delete", 0o644)):
        target = project / name
        target.write_bytes(content)
        target.chmod(mode)
        if name == "d":
            transaction.add_delete(Path(name), owned_paths={Path(name)})
        else:
            transaction.add_write(Path(name), shared, owned_paths={Path(name)})
    transaction.add_delete(Path("e"), owned_paths={Path("e")})
    prepared = transaction.seal()
    if interrupted:
        def interrupt(position):
            if position == 1:
                raise RuntimeError("interrupt")
        with pytest.raises(PublicationError, match="^publish_io$"):
            prepared.publish(fault_hook=interrupt)
    with prepared.inspect_sources(file_paths=("b", "a", "e")) as snapshot:
        ops = snapshot.publication.operations
        assert tuple(o.target for o in ops) == ("a", "b", "c", "d", "e")
        assert snapshot.publication.promoted_prefix == int(interrupted)
        assert ops[0].preimage.sha256 == hashlib.sha256(b"old").hexdigest()
        assert ops[0].current_bytes == (b"new" if interrupted else b"old")
        assert snapshot.files[0].content == ops[0].current_bytes
        assert ops[1].preimage.mode == 0o600 and ops[1].postimage.mode == 0o604
        assert ops[2].preimage == ops[2].postimage
        assert ops[3].action == "delete" and ops[3].current_bytes == b"delete"
        assert ops[3].postimage_bytes is None
        assert ops[4].preimage == ops[4].postimage
        assert tuple(o.postimage_bytes for o in ops[:3]) == (b"new",) * 3
    assert shared.read_bytes() == b"new"
    assert (project / "d").read_bytes() == b"delete"
    assert not (project / "e").exists()


class _String(str):
    pass


@pytest.mark.parametrize("batch", [None, 1, "", b"", "spec", b"spec", {"spec"},
    {"spec": 1}, iter(["spec"]), [None], [1], [Path("spec")], [_String("spec")],
    [""], ["."], [".."], ["/spec"], ["spec/"], ["spec//a"], ["spec/./a"],
    ["spec/../a"], ["spec\\a"], ["spec\x00a"], ["bad\udcff"]])
@pytest.mark.parametrize("field", ["tree_paths", "file_paths"])
def test_invalid_selections_reject_before_scope(tmp_path, monkeypatch, batch, field):
    _, prepared, _ = _prepared(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("invalid selection acquired a scope")
    monkeypatch.setattr(publication, "_project_inspection_scope", forbidden)
    with pytest.raises(PublicationError, match="^manifest_invalid$"):
        with prepared.inspect_sources(**{field: batch}):
            pytest.fail("invalid selection escaped")


@pytest.mark.parametrize("trees,files", [
    (("a", "a"), ()), ((), ("a", "a")), (("a",), ("a",)),
    (("a/b", "a"), ()), ((), ("a/b", "a")), (("a",), ("a/b",)),
    (("a/b",), ("a",)), (("a", "a-/sibling", "a/b"), ()),
])
def test_component_overlaps_reject_before_scope(tmp_path, monkeypatch, trees, files):
    _, prepared, _ = _prepared(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("overlap acquired a scope")
    monkeypatch.setattr(publication, "_project_inspection_scope", forbidden)
    with pytest.raises(PublicationError, match="^manifest_invalid$"):
        with prepared.inspect_sources(tree_paths=trees, file_paths=files):
            pytest.fail("overlap escaped")


def test_prefix_siblings_empty_batches_and_pre_acquisition_copy(tmp_path, monkeypatch):
    project, prepared, _ = _prepared(tmp_path)
    trees, files = ["spec/a"], ["spec/ab"]
    original = publication._project_inspection_scope
    @contextmanager
    def mutate_arguments(root):
        trees[:] = ["target"]
        files[:] = ["target"]
        with original(root) as scope:
            yield scope
    with monkeypatch.context() as patch:
        patch.setattr(publication, "_project_inspection_scope", mutate_arguments)
        with prepared.inspect_sources(tree_paths=trees, file_paths=files) as snapshot:
            assert snapshot.trees[0].path == "spec/a"
            assert snapshot.files[0].path == "spec/ab"
    with prepared.inspect_sources() as snapshot:
        assert snapshot.trees == snapshot.files == ()
        assert len(snapshot.publication.operations) == 1
    monkeypatch.chdir(project.parent)
    relative = replace(prepared, _project_root=Path(project.name))
    with relative.inspect_sources(file_paths=("target",)) as snapshot:
        assert snapshot.files[0].content == b"before"


@pytest.mark.parametrize("kind", ["directory", "symlink", "ancestor-symlink", "fifo", "socket"])
def test_invalid_individual_sources_fail_closed(tmp_path, kind):
    project, prepared, _ = _prepared(tmp_path)
    source = project / "source"
    sock = None
    if kind == "directory":
        source.mkdir()
    elif kind == "symlink":
        source.symlink_to(project / "target")
    elif kind == "ancestor-symlink":
        source.symlink_to(project, target_is_directory=True)
    elif kind == "fifo":
        os.mkfifo(source)
    else:
        sock = socket.socket(socket.AF_UNIX)
        # Use a short relative name to stay under the platform socket path limit.
        old = Path.cwd()
        os.chdir(project)
        try:
            sock.bind("source")
        finally:
            os.chdir(old)
    try:
        path = "source/target" if kind == "ancestor-symlink" else "source"
        with pytest.raises(PublicationError, match="^target_drift$"):
            with prepared.inspect_sources(file_paths=(path,)):
                pytest.fail("unsupported individual source escaped")
    finally:
        if sock:
            sock.close()


@pytest.mark.parametrize("reader", ["joint-file", "joint-tree", "tree"])
@pytest.mark.parametrize("mutation", [None, "nlink", "content"])
@pytest.mark.parametrize("when", ["before-yield", "exit"])
def test_stable_hardlinks_preserve_exact_bytes_but_drift_rejects(tmp_path, monkeypatch, reader, mutation, when):
    from harness.squad_source_snapshot import inspect_project_tree
    project, prepared, _ = _prepared(tmp_path)
    (project / "source").mkdir()
    source = project / "source/file"
    source.write_bytes(b"stable\r\n")
    source.chmod(0o604)
    alias = project / "alias"
    os.link(source, alias)
    def mutate():
        if mutation == "nlink":
            os.link(source, project / "extra-link")
        elif mutation == "content":
            alias.write_bytes(b"change\r\n")
    original = publication._read_pinned_bytes
    if mutation and when == "before-yield":
        def read(pinned, *, code):
            result = original(pinned, code=code)
            if os.fstat(pinned.fd).st_ino == source.stat().st_ino:
                mutate()
            return result
        monkeypatch.setattr(publication, "_read_pinned_bytes", read)
    def run():
        scope = (prepared.inspect_sources(file_paths=("source/file",)) if reader == "joint-file"
                 else prepared.inspect_sources(tree_paths=("source",)) if reader == "joint-tree"
                 else inspect_project_tree(project, "source"))
        with scope as snapshot:
            item = snapshot.trees[0].files[0] if reader == "joint-tree" else snapshot.files[0]
            assert item.content == b"stable\r\n"
            assert item.image.sha256 == hashlib.sha256(b"stable\r\n").hexdigest()
            assert item.image.mode == 0o604
            if mutation and when == "before-yield":
                pytest.fail("hardlink drift escaped before yield")
            mutate()
    if mutation:
        with pytest.raises(PublicationError, match="^target_drift$"):
            run()
    else:
        run()
        assert source.stat().st_nlink == 2
        assert alias.read_bytes() == b"stable\r\n"


@pytest.mark.parametrize("when", ["before-yield", "exit"])
@pytest.mark.parametrize("mutation", ["content", "mode", "replace", "ancestor", "missing-file", "missing-ancestor"])
def test_individual_source_pins_hold_across_later_file_read(tmp_path, monkeypatch, when, mutation):
    project, prepared, _ = _prepared(tmp_path)
    (project / "a").mkdir()
    source = project / "a/file"
    if not mutation.startswith("missing"):
        source.write_bytes(b"original")
        source.chmod(0o644)
    if mutation == "missing-ancestor":
        (project / "a").rmdir()
    late = project / "z"
    late.write_bytes(b"later")
    def mutate():
        if mutation == "content":
            source.write_bytes(b"changed!")
        elif mutation == "mode":
            source.chmod(0o600)
        elif mutation == "replace":
            replacement = project / "replacement"
            replacement.write_bytes(b"original")
            replacement.replace(source)
        elif mutation == "ancestor":
            (project / "a").rename(project / "old-a")
            (project / "a").mkdir()
        elif mutation == "missing-file":
            source.write_bytes(b"appeared")
        else:
            (project / "a").mkdir()
    original = publication._read_pinned_bytes
    if when == "before-yield":
        def read(pinned, *, code):
            result = original(pinned, code=code)
            if os.fstat(pinned.fd).st_ino == late.stat().st_ino:
                mutate()
            return result
        monkeypatch.setattr(publication, "_read_pinned_bytes", read)
    with pytest.raises(PublicationError, match="^target_drift$"):
        with prepared.inspect_sources(file_paths=("z", "a/file")):
            if when == "before-yield":
                pytest.fail("earlier individual source drift escaped")
            mutate()


@pytest.mark.parametrize("failure", ["capabilities", "marker", "transaction-root"])
def test_existing_pre_scope_gates_are_preserved(tmp_path, monkeypatch, failure):
    _, prepared, _ = _prepared(tmp_path)
    if failure == "capabilities":
        monkeypatch.setattr(publication, "_secure_posix_capabilities_available", lambda: False)
    elif failure == "marker":
        prepared = replace(prepared, marker=replace(prepared.marker, transaction_id="bad"))
    else:
        prepared = replace(prepared, _transaction_root=prepared._transaction_root / "wrong")
    def forbidden(*args, **kwargs):
        pytest.fail("invalid gate acquired source scope")
    monkeypatch.setattr(publication, "_project_inspection_scope", forbidden)
    with pytest.raises(PublicationError, match="^publish_io$" if failure == "capabilities" else "^manifest_invalid$"):
        with prepared.inspect_sources():
            pytest.fail("invalid gate escaped")


@pytest.mark.parametrize("later", ["tree", "file"])
@pytest.mark.parametrize("when", ["before-yield", "exit"])
@pytest.mark.parametrize("mutation", ["add", "remove", "content", "mode", "directory-mode", "ancestor",
                                      "file-replace", "missing-ancestor", "stage", "manifest"])
def test_joint_verification_catches_earlier_drift(tmp_path, monkeypatch, later, when, mutation):
    project, prepared, stage = _prepared(tmp_path)
    (project / "a/empty").mkdir(parents=True)
    source = project / "a/file"
    source.write_bytes(b"original")
    source.chmod(0o644)
    (project / "a/empty").chmod(0o755)
    (project / "z").mkdir()
    late = project / "z/late"
    late.write_bytes(b"late")
    def mutate():
        if mutation == "add":
            (project / "a/empty/new").write_bytes(b"new")
        elif mutation == "remove":
            source.unlink()
        elif mutation == "content":
            source.write_bytes(b"changed!")
        elif mutation == "mode":
            source.chmod(0o600)
        elif mutation == "directory-mode":
            (project / "a/empty").chmod(0o700)
        elif mutation == "ancestor":
            (project / "a").rename(project / "old-a")
            (project / "a").mkdir()
        elif mutation == "file-replace":
            replacement = project / "replacement"
            replacement.write_bytes(b"original")
            replacement.replace(source)
        elif mutation == "missing-ancestor":
            (project / "absent").mkdir()
        elif mutation == "stage":
            stage.write_bytes(b"wrong")
        else:
            (prepared._transaction_root / "manifest.json").write_bytes(b"wrong")
    original = publication._read_pinned_bytes
    if when == "before-yield":
        def read(pinned, *, code):
            result = original(pinned, code=code)
            if os.fstat(pinned.fd).st_ino == late.stat().st_ino:
                mutate()
            return result
        monkeypatch.setattr(publication, "_read_pinned_bytes", read)
    trees = ("a", "absent/tree", "z") if later == "tree" else ("a", "absent/tree")
    files = ("missing",) if later == "tree" else ("missing", "z/late")
    code = {"stage": "stage_corrupt", "manifest": "manifest_invalid"}.get(mutation, "target_drift")
    with pytest.raises(PublicationError, match=f"^{code}$"):
        with prepared.inspect_sources(tree_paths=trees, file_paths=files):
            if when == "before-yield":
                pytest.fail("earlier source drift escaped before yield")
            mutate()


@pytest.mark.parametrize("when", ["before-yield", "exit"])
@pytest.mark.parametrize("source,code", [("stage", "stage_corrupt"), ("manifest", "manifest_invalid")])
def test_empty_selection_still_verifies_sealed_transaction(tmp_path, monkeypatch, when, source, code):
    _, prepared, stage = _prepared(tmp_path)
    path = stage if source == "stage" else prepared._transaction_root / "manifest.json"
    original = publication._read_pinned_bytes
    if when == "before-yield":
        def read(pinned, *, code):
            result = original(pinned, code=code)
            if code == "target_drift":
                path.write_bytes(b"wrong")
            return result
        monkeypatch.setattr(publication, "_read_pinned_bytes", read)
    with pytest.raises(PublicationError, match=f"^{code}$"):
        with prepared.inspect_sources():
            if when == "before-yield":
                pytest.fail("sealed drift escaped empty selection")
            path.write_bytes(b"wrong")


def test_one_root_bound_scope_without_recursive_public_inspection(tmp_path, monkeypatch):
    import harness.squad_source_snapshot as sources
    project, prepared, _ = _prepared(tmp_path)
    original_scope = publication._project_inspection_scope
    original_lock = publication._publication_exclusivity
    scopes, locks = [], []
    @contextmanager
    def scope(root):
        with original_scope(root) as result:
            scopes.append(result)
            yield result
    @contextmanager
    def lock(root, *, expected_project_fd=None):
        assert expected_project_fd is not None
        assert os.fstat(expected_project_fd).st_ino == project.stat().st_ino
        locks.append(expected_project_fd)
        with original_lock(root, expected_project_fd=expected_project_fd):
            yield
    def forbidden(*args, **kwargs):
        pytest.fail("nested public inspector")
    monkeypatch.setattr(publication, "_project_inspection_scope", scope)
    monkeypatch.setattr(publication, "_publication_exclusivity", lock)
    monkeypatch.setattr(publication.PreparedSquadPublication, "inspect", forbidden)
    monkeypatch.setattr(sources, "inspect_project_tree", forbidden)
    with prepared.inspect_sources(tree_paths=("a", "b"), file_paths=("target",)):
        assert len(scopes) == len(locks) == 1
        assert scopes[0][2] == locks[0]


@pytest.mark.parametrize("outcome", ["success", "caller", "entry", "exit", "read", "list", "resource", "rank", "lock"])
def test_descriptors_and_lock_rank_release_on_every_outcome(tmp_path, monkeypatch, outcome):
    project, prepared, _ = _prepared(tmp_path)
    (project / "source").mkdir()
    source = project / "source/file"
    source.write_bytes(b"source")
    opened = set()
    error = RuntimeError("caller failure remains primary")
    with monkeypatch.context() as patch:
        for name in ("_open_directory", "_open_regular_at"):
            original = getattr(publication, name)
            def record(*args, _original=original, **kwargs):
                fd = _original(*args, **kwargs)
                opened.add(fd)
                return fd
            patch.setattr(publication, name, record)
        if outcome == "entry":
            (project / "source/unsupported").symlink_to(source)
        elif outcome == "read":
            original_read = publication._read_fd_bytes
            def fail_read(fd, *, code):
                if os.fstat(fd).st_ino == source.stat().st_ino:
                    raise OSError("injected read failure")
                return original_read(fd, code=code)
            patch.setattr(publication, "_read_fd_bytes", fail_read)
        elif outcome == "resource":
            import errno
            original_open = os.open
            def fail_open(path, flags, *args, **kwargs):
                if str(path) == "file":
                    raise OSError(errno.EMFILE, "injected descriptor exhaustion")
                return original_open(path, flags, *args, **kwargs)
            patch.setattr(os, "open", fail_open)
            patch.setattr(publication, "_secure_posix_capabilities_available", lambda: True)
        elif outcome == "list":
            patch.setattr(publication, "_secure_posix_capabilities_available", lambda: True)
            original_list = os.listdir
            def fail_list(fd):
                if isinstance(fd, int) and os.fstat(fd).st_ino == (project / "source").stat().st_ino:
                    raise OSError("injected listing failure")
                return original_list(fd)
            patch.setattr(os, "listdir", fail_list)
        elif outcome == "lock":
            (project / ".echelon/runtime/publication.lock").mkdir(parents=True)
        def run():
            with prepared.inspect_sources(tree_paths=("source",)):
                if outcome in {"caller", "exit"}:
                    source.write_bytes(b"changed")
                if outcome == "caller":
                    raise error
        if outcome == "success":
            run()
        elif outcome == "rank":
            with controller_lock_order("completion", "outer"):
                with pytest.raises(LockOrderViolation):
                    run()
        elif outcome == "caller":
            with pytest.raises(RuntimeError) as caught:
                run()
            assert caught.value is error
        else:
            with pytest.raises(PublicationError):
                run()
        assert opened
        for fd in opened:
            with pytest.raises(OSError):
                os.fstat(fd)
    with controller_lock_order("phase_a", "cleanup-check"):
        pass
    if outcome == "entry":
        (project / "source/unsupported").unlink()
    if outcome == "lock":
        (project / ".echelon/runtime/publication.lock").rmdir()
    with prepared.inspect_sources(tree_paths=("source",)):
        pass


@pytest.mark.parametrize("interval", ["before-acquisition", "after-acquisition"])
def test_root_replacement_around_lock_rejects_and_cleans_up(tmp_path, monkeypatch, interval):
    project, prepared, _ = _prepared(tmp_path)
    moved = project.with_name(project.name + "-moved")
    original_lock = publication._publication_exclusivity
    opened = set()
    def move_root():
        project.rename(moved)
        project.mkdir()
        (moved / "runs").rename(project / "runs")
        (moved / "target").rename(project / "target")
    @contextmanager
    def lock(root, **kwargs):
        if interval == "before-acquisition":
            move_root()
        with original_lock(root, **kwargs):
            if interval == "after-acquisition":
                move_root()
            yield
    with monkeypatch.context() as patch:
        for name in ("_open_directory", "_open_regular_at"):
            original = getattr(publication, name)
            def record(*args, _original=original, **kwargs):
                fd = _original(*args, **kwargs)
                opened.add(fd)
                return fd
            patch.setattr(publication, name, record)
        patch.setattr(publication, "_publication_exclusivity", lock)
        patch.setattr(publication, "_load_prepared_pinned", lambda *args: pytest.fail("loaded after root replacement"))
        with pytest.raises(PublicationError, match="^target_drift$"):
            with prepared.inspect_sources(file_paths=("target",)):
                pytest.fail("replacement root escaped")
    assert opened
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)
    with controller_lock_order("phase_a", "cleanup-check"):
        pass
    with original_lock(moved):
        pass
    with prepared.inspect_sources(file_paths=("target",)) as snapshot:
        assert snapshot.files[0].content == b"before"


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


def test_spawned_normal_publisher_waits_for_joint_capture(tmp_path):
    project, prepared, _ = _prepared(tmp_path)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_publish_child, args=(str(project), str(prepared._squad_dir), prepared.marker, child))
    try:
        with prepared.inspect_sources(file_paths=("target",)):
            process.start()
            child.close()
            assert parent.poll(10), "publisher did not reach lock"
            assert parent.recv() == "blocked-by-publication-lock"
            assert (project / "target").read_bytes() == b"before"
        assert parent.poll(10), "publisher did not progress after inspection"
        assert parent.recv() == "published"
        process.join(10)
        assert process.exitcode == 0
        assert (project / "target").read_bytes() == b"after"
    finally:
        if process.is_alive():
            process.terminate()
            process.join(10)
        parent.close()
        child.close()
