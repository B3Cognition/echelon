import hashlib
import multiprocessing
import os
import stat
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

import harness.squad_publication as publication
from harness.controller_lock_order import LockOrderViolation, controller_lock_order
from harness.squad_publication import (
    PublicationError, SquadPublicationTransaction, load_prepared_publication,
)


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def secure_posix():
    if not publication._secure_posix_capabilities_available():
        pytest.skip("descriptor-safe POSIX publication is unavailable")


def test_inspection_returns_original_and_sealed_bytes_without_publication(tmp_path):
    project = tmp_path.resolve()
    squad = project / "runs" / "spec-test"
    squad.mkdir(parents=True)
    target = project / "spec.md"
    target.write_bytes(b"before\r\n")
    transaction = SquadPublicationTransaction.begin(project, squad, "1" * 32)
    stage = transaction.build_path("spec-after.md")
    stage.write_bytes(b"after\r\n")
    transaction.add_write(Path("spec.md"), stage, owned_paths={Path("spec.md")})
    prepared = transaction.seal()
    with prepared.inspect() as snapshot:
        operation, = snapshot.operations
        assert operation.target == "spec.md"
        assert operation.current_bytes == b"before\r\n"
        assert operation.postimage_bytes == b"after\r\n"
        assert snapshot.marker == prepared.marker
        assert snapshot.promoted_prefix == 0
        assert target.read_bytes() == b"before\r\n"
    assert target.read_bytes() == b"before\r\n"
    assert stage.read_bytes() == b"after\r\n"


def _prepared(tmp_path, entries=(("spec.md", b"before", b"after"),)):
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(project, squad, "1" * 32)
    stages = {}
    for index, (name, before, after) in enumerate(entries):
        target = project / name
        if before is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(before)
            target.chmod(0o640)
        if after is None:
            transaction.add_delete(Path(name), owned_paths={Path(name)})
        else:
            stage = transaction.build_path(f"nested/stage-{index}")
            stage.parent.mkdir(parents=True, exist_ok=True)
            stage.write_bytes(after)
            stage.chmod(0o604)
            transaction.add_write(Path(name), stage, owned_paths={Path(name)})
            stages[name] = stage
    return project, squad, transaction.seal(), stages


def _assert_image(image, content, mode):
    assert image.kind == ("missing" if content is None else "file")
    assert image.sha256 == (
        None if content is None else hashlib.sha256(content).hexdigest()
    )
    assert image.mode == mode


def test_sorted_exact_images_missing_empty_delete_and_mode_only(tmp_path):
    entries = (
        ("z-missing-parent/deep/empty", None, b""),
        ("mode", b"same", b"same"),
        ("gone", b"delete", None),
        ("empty", b"", b"new"),
        ("absent", None, None),
    )
    project, _, prepared, stages = _prepared(tmp_path, entries)
    stage_images = {name: path.read_bytes() for name, path in stages.items()}
    with prepared.inspect() as snapshot:
        assert [op.target for op in snapshot.operations] == sorted(e[0] for e in entries)
        assert snapshot.promoted_prefix == 0
        for op in snapshot.operations:
            _, before, after = next(e for e in entries if e[0] == op.target)
            _assert_image(op.preimage, before, None if before is None else 0o640)
            _assert_image(op.current, before, None if before is None else 0o640)
            _assert_image(op.postimage, after, None if after is None else 0o604)
            assert op.current_bytes == before
            assert op.postimage_bytes == after
            assert op.action == ("delete" if after is None else "write")
    assert not (project / "z-missing-parent").exists()
    for name, path in stages.items():
        assert path.read_bytes() == stage_images[name]
        assert stat.S_IMODE(path.stat().st_mode) == 0o604
    assert (project / "gone").read_bytes() == b"delete"


def test_shared_stage_keeps_independent_targets_and_detached_frozen_values(tmp_path):
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(project, squad, "2" * 32)
    stage = transaction.build_path("same")
    stage.write_bytes(b"shared")
    (project / "b").write_bytes(b"old")
    for name in ("b", "a"):
        transaction.add_write(Path(name), stage, owned_paths={Path(name)})
    prepared = transaction.seal()
    prepared._manifest.clear()
    with prepared.inspect() as snapshot:
        first, second = snapshot.operations
        assert (first.target, second.target) == ("a", "b")
        assert first.postimage_bytes == second.postimage_bytes == b"shared"
        assert first.current_bytes is None
        assert second.current_bytes == b"old"
        for value, field, replacement in (
            (snapshot, "promoted_prefix", 9),
            (first, "target", "evil"),
            (first.preimage, "kind", "evil"),
            (snapshot.marker, "transaction_id", "evil"),
        ):
            with pytest.raises(FrozenInstanceError):
                setattr(value, field, replacement)
        assert isinstance(snapshot.operations, tuple)
    (project / "b").write_bytes(b"later")
    assert second.current_bytes == b"old"


def test_interrupted_publication_and_reload_preserve_original_descriptor(tmp_path):
    project, squad, prepared, stages = _prepared(
        tmp_path, (("a", b"old-a", b"new-a"), ("b", b"old-b", b"new-b"))
    )
    def interrupt(position):
        if position == 1:
            raise RuntimeError("interrupted")
    with pytest.raises(PublicationError, match="^publish_io$"):
        prepared.publish(fault_hook=interrupt)
    loaded = load_prepared_publication(project, squad, prepared.marker)
    with loaded.inspect() as snapshot:
        assert snapshot.promoted_prefix == 1
        a, b = snapshot.operations
        assert a.current_bytes == a.postimage_bytes == b"new-a"
        _assert_image(a.preimage, b"old-a", 0o640)
        assert a.current == a.postimage
        assert b.current_bytes == b"old-b"
    loaded.publish()
    with loaded.inspect() as snapshot:
        assert snapshot.promoted_prefix == 2
        assert all(op.current == op.postimage for op in snapshot.operations)
        assert all(op.current_bytes == op.postimage_bytes for op in snapshot.operations)
    assert all(path.exists() for path in stages.values())


@pytest.mark.parametrize("promoted,want", [((), 0), ((0,), 1), ((0, 1), 2), ((1,), None)])
def test_global_prefix_rejects_out_of_order_postimages(tmp_path, promoted, want):
    project, _, prepared, stages = _prepared(
        tmp_path, (("a", b"old-a", b"new-a"), ("b", b"old-b", b"new-b"))
    )
    for index in promoted:
        name = ("a", "b")[index]
        (project / name).write_bytes(stages[name].read_bytes())
        (project / name).chmod(0o604)
    if want is None:
        with pytest.raises(PublicationError, match="^target_drift$"):
            with prepared.inspect():
                pytest.fail("illegal prefix escaped")
    else:
        with prepared.inspect() as snapshot:
            assert snapshot.promoted_prefix == want


@pytest.mark.parametrize("promote,want", [(False, 0), (True, 2)])
def test_noop_prefix_is_lower_bound_not_postimage_count(tmp_path, promote, want):
    project, _, prepared, stages = _prepared(
        tmp_path, (("a", None, None), ("b", b"old", b"new"), ("c", None, None))
    )
    if promote:
        prepared.publish()
    with prepared.inspect() as snapshot:
        assert snapshot.promoted_prefix == want
        assert sum(op.current == op.postimage for op in snapshot.operations) == (
            3 if promote else 2
        )


@pytest.mark.parametrize("mutation,code", [
    ("marker", "manifest_mismatch"), ("bad-marker", "manifest_invalid"),
    ("root", "manifest_invalid"), ("manifest", "manifest_mismatch"),
    ("manifest-missing", "stage_missing"), ("stage", "stage_corrupt"),
    ("stage-missing", "stage_missing"), ("target", "target_drift"),
])
def test_tampered_sources_and_marker_fail_without_yield(tmp_path, mutation, code):
    project, _, prepared, stages = _prepared(tmp_path)
    if mutation == "marker":
        prepared = replace(prepared, marker=replace(prepared.marker, manifest_sha256="0" * 64))
    elif mutation == "bad-marker":
        prepared = replace(prepared, marker=replace(prepared.marker, schema_version=True))
    elif mutation == "root":
        prepared = replace(prepared, _transaction_root=project / "other")
    elif mutation == "manifest":
        (prepared._transaction_root / "manifest.json").write_bytes(b"{}")
    elif mutation == "manifest-missing":
        (prepared._transaction_root / "manifest.json").unlink()
    elif mutation == "stage":
        stages["spec.md"].write_bytes(b"corrupt")
    elif mutation == "stage-missing":
        stages["spec.md"].unlink()
    elif mutation == "target":
        (project / "spec.md").write_bytes(b"drift")
    with pytest.raises(PublicationError, match=f"^{code}$"):
        with prepared.inspect():
            pytest.fail("corruption escaped")
    assert prepared._transaction_root.exists() or mutation == "root"
    assert (project / "spec.md").read_bytes() == (b"drift" if mutation == "target" else b"before")


@pytest.mark.parametrize("source", ["target", "stage"])
@pytest.mark.parametrize("kind", ["leaf-symlink", "ancestor-symlink", "directory", "fifo"])
def test_nonregular_and_symlink_sources_fail_closed(tmp_path, source, kind):
    project, _, prepared, stages = _prepared(tmp_path, (("docs/spec.md", b"before", b"after"),))
    path = project / "docs/spec.md" if source == "target" else stages["docs/spec.md"]
    if kind == "ancestor-symlink":
        parent = path.parent
        moved = parent.with_name(parent.name + "-moved")
        parent.rename(moved)
        parent.symlink_to(moved, target_is_directory=True)
    else:
        path.unlink()
        if kind == "leaf-symlink":
            alternate = project / "alternate"
            alternate.write_bytes(b"before" if source == "target" else b"after")
            path.symlink_to(alternate)
        elif kind == "directory":
            path.mkdir()
        else:
            os.mkfifo(path)
    with pytest.raises(PublicationError, match="^(target_drift|stage_corrupt)$"):
        with prepared.inspect():
            pytest.fail("unsafe source escaped")


@pytest.mark.parametrize("source", ["target", "stage"])
@pytest.mark.parametrize("mutation", ["replace", "same-size", "mode", "ancestor"])
def test_exit_rejects_changed_current_and_sealed_bindings(tmp_path, source, mutation):
    project, _, prepared, stages = _prepared(tmp_path, (("docs/spec.md", b"before", b"after"),))
    path = project / "docs/spec.md" if source == "target" else stages["docs/spec.md"]
    code = "target_drift" if source == "target" else "stage_corrupt"
    with pytest.raises(PublicationError, match=f"^{code}$"):
        with prepared.inspect() as snapshot:
            assert snapshot.operations[0].current_bytes == b"before"
            if mutation == "replace":
                alternate = path.with_name("replacement")
                alternate.write_bytes(path.read_bytes())
                alternate.chmod(stat.S_IMODE(path.stat().st_mode))
                alternate.replace(path)
            elif mutation == "same-size":
                path.write_bytes(b"X" * len(path.read_bytes()))
            elif mutation == "mode":
                path.chmod(0o600)
            else:
                parent = path.parent
                moved = parent.with_name(parent.name + "-moved")
                parent.rename(moved)
                parent.mkdir()
                # Even the same file inode under a new ancestor is rejected.
                os.link(moved / path.name, path)
    assert prepared._transaction_root.exists()


@pytest.mark.parametrize("name", ["missing", "absent/parent/target"])
def test_missing_target_or_parent_must_remain_absent(tmp_path, name):
    project, _, prepared, _ = _prepared(tmp_path, ((name, None, b"after"),))
    with pytest.raises(PublicationError, match="^target_drift$"):
        with prepared.inspect() as snapshot:
            assert snapshot.operations[0].current_bytes is None
            (project / name).parent.mkdir(parents=True, exist_ok=True)
            (project / name).write_bytes(b"appeared")


def test_root_replacement_is_rejected_on_exit(tmp_path):
    project, _, prepared, _ = _prepared(tmp_path)
    with pytest.raises(PublicationError, match="^target_drift$"):
        with prepared.inspect():
            moved = project.with_name(project.name + "-moved")
            project.rename(moved)
            project.mkdir()
    assert (moved / "spec.md").read_bytes() == b"before"


def test_root_is_pinned_before_loading_sealed_sources(tmp_path, monkeypatch):
    project, _, prepared, _ = _prepared(tmp_path)
    original = publication._load_prepared_pinned
    def replace_root_after_load(*args):
        loaded = original(*args)
        moved = project.with_name(project.name + "-moved")
        project.rename(moved)
        project.mkdir()
        (moved / "runs").rename(project / "runs")
        (moved / "spec.md").rename(project / "spec.md")
        return loaded
    monkeypatch.setattr(publication, "_load_prepared_pinned", replace_root_after_load)
    with pytest.raises(PublicationError, match="^target_drift$"):
        with prepared.inspect():
            pytest.fail("different project root escaped")


def test_caller_exception_propagates_and_lock_releases(tmp_path):
    project, _, prepared, stages = _prepared(tmp_path)
    error = OSError("caller transaction failed")
    with pytest.raises(OSError) as caught:
        with prepared.inspect():
            raise error
    assert caught.value is error
    with prepared.inspect() as snapshot:
        assert snapshot.operations[0].current_bytes == b"before"
    prepared.publish()
    assert (project / "spec.md").read_bytes() == b"after"
    assert stages["spec.md"].exists()


def test_caller_exception_is_not_replaced_by_exit_drift(tmp_path):
    project, _, prepared, _ = _prepared(tmp_path)
    error = RuntimeError("caller failed")
    with pytest.raises(RuntimeError) as caught:
        with prepared.inspect():
            (project / "spec.md").write_bytes(b"changed")
            raise error
    assert caught.value is error
    (project / "spec.md").write_bytes(b"before")
    with prepared.inspect():
        pass


def test_inspection_only_creates_existing_lock_control_path(tmp_path):
    project, _, prepared, _ = _prepared(
        tmp_path, (("a", b"old", b"new"), ("b", b"delete", None), ("absent/c", None, b""))
    )
    def inventory():
        return {
            path.relative_to(project).as_posix(): (
                path.read_bytes() if path.is_file() else None,
                stat.S_IMODE(path.stat().st_mode),
            )
            for path in project.rglob("*")
        }
    before = inventory()
    with prepared.inspect():
        pass
    after = inventory()
    assert set(after) - set(before) == {
        ".echelon", ".echelon/runtime", ".echelon/runtime/publication.lock"
    }
    assert {name: after[name] for name in before} == before


def test_exit_rejects_manifest_corruption_without_discard(tmp_path):
    project, _, prepared, stages = _prepared(tmp_path)
    manifest = prepared._transaction_root / "manifest.json"
    with pytest.raises(PublicationError, match="^manifest_invalid$"):
        with prepared.inspect():
            manifest.write_bytes(b"corrupt")
    assert manifest.read_bytes() == b"corrupt"
    assert stages["spec.md"].read_bytes() == b"after"
    assert (project / "spec.md").read_bytes() == b"before"


def test_capability_and_lock_rank_gate_precede_inspection(tmp_path, monkeypatch):
    project, _, prepared, _ = _prepared(tmp_path)
    with controller_lock_order("completion", "outer"):
        with pytest.raises(LockOrderViolation):
            with prepared.inspect():
                pytest.fail("lock inversion escaped")
    assert not (project / ".echelon").exists()
    monkeypatch.setattr(publication, "_secure_posix_capabilities_available", lambda: False)
    with pytest.raises(PublicationError, match="^publish_io$"):
        with prepared.inspect():
            pytest.fail("missing capabilities escaped")
    assert not (project / ".echelon").exists()


@pytest.mark.parametrize("source", ["target", "stage"])
def test_read_bytes_are_checked_against_pinned_hash_before_yield(tmp_path, monkeypatch, source):
    project, _, prepared, stages = _prepared(tmp_path)
    original = publication._read_fd_bytes
    path = project / "spec.md" if source == "target" else stages["spec.md"]
    identity = path.stat().st_ino
    def mutate_after_read(fd, *, code):
        content = original(fd, code=code)
        if os.fstat(fd).st_ino == identity:
            path.write_bytes(b"X" * len(content))
        return content
    monkeypatch.setattr(publication, "_read_fd_bytes", mutate_after_read)
    with pytest.raises(PublicationError, match="^(stage_corrupt|target_drift)$"):
        with prepared.inspect():
            pytest.fail("changed read escaped")


@pytest.mark.parametrize("source", ["target", "stage", "manifest"])
def test_bindings_are_revalidated_before_yield(tmp_path, monkeypatch, source):
    project, _, prepared, stages = _prepared(tmp_path)
    path = {
        "target": project / "spec.md", "stage": stages["spec.md"],
        "manifest": prepared._transaction_root / "manifest.json",
    }[source]
    original = publication._InspectionPaths.verify
    def replace_before_verify(self):
        replacement = path.with_name(path.name + "-replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(stat.S_IMODE(path.stat().st_mode))
        replacement.replace(path)
        original(self)
    monkeypatch.setattr(publication._InspectionPaths, "verify", replace_before_verify)
    with pytest.raises(PublicationError, match="^(target_drift|stage_corrupt|manifest_invalid)$"):
        with prepared.inspect():
            pytest.fail("replacement escaped")


@pytest.mark.parametrize("outcome", ["success", "caller", "entry", "exit"])
def test_descriptors_close_on_all_inspection_outcomes(tmp_path, monkeypatch, outcome):
    project, _, prepared, stages = _prepared(tmp_path)
    opened = set()
    for name in ("_open_directory", "_open_regular_at"):
        original = getattr(publication, name)
        def record(*args, _original=original, **kwargs):
            fd = _original(*args, **kwargs)
            opened.add(fd)
            return fd
        monkeypatch.setattr(publication, name, record)
    if outcome == "entry":
        stages["spec.md"].write_bytes(b"corrupt")
    def inspect():
        with prepared.inspect():
            if outcome == "caller":
                raise ValueError("caller")
            if outcome == "exit":
                (project / "spec.md").write_bytes(b"changed")
    if outcome == "success":
        inspect()
    else:
        with pytest.raises(ValueError if outcome == "caller" else PublicationError):
            inspect()
    assert opened
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)
    assert stages["spec.md"].exists()
    # A fresh inspection can acquire the lock after failure as well as success.
    if outcome == "entry":
        stages["spec.md"].write_bytes(b"after")
    if outcome == "exit":
        (project / "spec.md").write_bytes(b"before")
    with prepared.inspect():
        pass


@pytest.mark.parametrize("source", ["target", "stage", "ancestor"])
def test_inaccessible_paths_are_not_mistaken_for_absence(tmp_path, source):
    if os.geteuid() == 0:
        pytest.skip("root bypasses POSIX permission checks")
    project, _, prepared, stages = _prepared(tmp_path, (("docs/spec.md", b"before", b"after"),))
    path = {
        "target": project / "docs/spec.md", "stage": stages["docs/spec.md"],
        "ancestor": project / "docs",
    }[source]
    mode = stat.S_IMODE(path.stat().st_mode)
    path.chmod(0)
    try:
        with pytest.raises(PublicationError, match="^(target_drift|stage_corrupt)$"):
            with prepared.inspect():
                pytest.fail("unreadable source escaped")
    finally:
        path.chmod(mode)


def test_stage_mode_is_not_substituted_for_desired_postimage_mode(tmp_path):
    _, _, prepared, stages = _prepared(tmp_path)
    stages["spec.md"].chmod(0o600)
    with prepared.inspect() as snapshot:
        assert snapshot.operations[0].postimage.mode == 0o604
        assert snapshot.operations[0].postimage_bytes == b"after"
    assert stat.S_IMODE(stages["spec.md"].stat().st_mode) == 0o600


def test_exact_file_noop_and_empty_transaction_have_zero_lower_bound(tmp_path):
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    empty = SquadPublicationTransaction.begin(project, squad, "3" * 32).seal()
    with empty.inspect() as snapshot:
        assert snapshot.operations == ()
        assert snapshot.promoted_prefix == 0
    target = project / "same"
    target.write_bytes(b"unchanged")
    target.chmod(0o640)
    transaction = SquadPublicationTransaction.begin(project, squad, "4" * 32)
    stage = transaction.build_path("same")
    stage.write_bytes(b"unchanged")
    stage.chmod(0o640)
    transaction.add_write(Path("same"), stage, owned_paths={Path("same")})
    prepared = transaction.seal()
    with prepared.inspect() as snapshot:
        assert snapshot.promoted_prefix == 0
        op, = snapshot.operations
        assert op.current == op.preimage == op.postimage
        assert op.current_bytes == op.postimage_bytes == b"unchanged"


def _publish_child(project, squad, marker, connection):
    try:
        prepared = load_prepared_publication(Path(project), Path(squad), marker)
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


def test_normal_publish_in_spawned_process_waits_for_inspection_exit(tmp_path):
    project, squad, prepared, _ = _prepared(tmp_path)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_publish_child, args=(str(project), str(squad), prepared.marker, child))
    try:
        with prepared.inspect():
            process.start()
            child.close()
            assert parent.poll(10), "publisher did not reach lock"
            assert parent.recv() == "blocked-by-publication-lock"
            assert (project / "spec.md").read_bytes() == b"before"
        assert parent.poll(10), "publisher did not progress after inspection"
        assert parent.recv() == "published"
        process.join(10)
        assert process.exitcode == 0
        assert (project / "spec.md").read_bytes() == b"after"
    finally:
        if process.is_alive():
            process.terminate()
            process.join(10)
        parent.close()
        child.close()
