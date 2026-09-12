from pathlib import Path
import os
import multiprocessing
import hashlib
import sys
import shutil
import stat
from dataclasses import replace, FrozenInstanceError
from contextlib import contextmanager

import pytest

import harness.squad_publication as publication
from harness.squad_publication import PublicationError, SquadPublicationTransaction
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_projection import project_publication_source_manifest
from harness.controller_lock_order import LockOrderViolation, controller_lock_order


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def secure_posix():
    if not publication._secure_posix_capabilities_available():
        pytest.skip("descriptor-safe POSIX publication is unavailable")


def test_changed_unbound_evidence_blocks_before_any_promotion(tmp_path):
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs").mkdir()
    target = project / "specs/unknowns.md"
    target.write_bytes(b"# Unknowns\n## U-001: Existing\nBody\n")
    evidence = project / "specs/evidence.md"
    evidence.write_bytes(b"U-001: retained evidence\n")
    transaction = SquadPublicationTransaction.begin(project, squad, "3" * 32)
    stage = transaction.build_path("unknowns.md")
    stage.write_bytes(b"# Unknowns\n## U-001: Existing\nRevised body\n")
    relative = Path("specs/unknowns.md")
    transaction.add_write(relative, stage, owned_paths={relative})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs",)) as initial:
        assert next(f.content for f in initial.trees[0].files if f.path.endswith("evidence.md")) == b"U-001: retained evidence\n"
    evidence.write_bytes(b"changed dependency\n")
    before_calls = []
    with pytest.raises(PublicationError, match="^target_drift$"):
        prepared.publish_sources(initial, before_publish=before_calls.append)
    assert before_calls == []
    assert target.read_bytes() == b"# Unknowns\n## U-001: Existing\nBody\n"
    assert evidence.read_bytes() == b"changed dependency\n"


def _prepared(tmp_path, *, nested=False):
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs/empty").mkdir(parents=True)
    (project / "specs/.evidence").write_bytes(b"\x00\xfforiginal")
    (project / "rules").write_bytes(b"rules")
    transaction = SquadPublicationTransaction.begin(project, squad, "4" * 32)
    targets = ("specs/a/new/value", "specs/z/new/value") if nested else ("specs/a", "specs/b")
    stage = transaction.build_path("shared")
    stage.write_bytes(b"after")
    stage.chmod(0o640)
    for target in targets:
        if not nested:
            (project / target).write_bytes(b"before")
        transaction.add_write(Path(target), stage, owned_paths={Path(target)})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs", "missing-tree"), file_paths=("rules", "absent")) as initial:
        pass
    return project, prepared, initial, stage, targets


def _assert_final(project, initial, final, targets):
    assert snapshot_source_manifest(trees=final.trees, files=final.files) == project_publication_source_manifest(initial)
    for target in targets:
        assert (project / target).read_bytes() == b"after"
        assert stat.S_IMODE((project / target).stat().st_mode) == 0o640
    assert (project / "specs/.evidence").read_bytes() == b"\x00\xfforiginal"
    assert final.files[0].content is None
    assert final.files[1].content == b"rules"


def test_real_fault_reload_and_exact_retry_preserve_original(tmp_path):
    project, prepared, initial, stage, targets = _prepared(tmp_path)
    calls = []
    def fault(position):
        calls.append(position)
        if position == 1:
            raise RuntimeError("injected stop")
    with pytest.raises(PublicationError, match="^publish_io$"):
        prepared.publish_sources(initial, fault_hook=fault)
    assert calls == [0, 1]
    assert (project / targets[0]).read_bytes() == b"after"
    assert (project / targets[1]).read_bytes() == b"before"
    assert stage.exists()
    marker, squad = prepared.marker, prepared._squad_dir
    del prepared
    prepared = publication.load_prepared_publication(project, squad, marker)
    receipts = []
    for _ in range(2):
        final = prepared.publish_sources(initial, before_publish=lambda s: receipts.append(("before", s)),
                                         after_publish=lambda s: receipts.append(("after", s)))
        _assert_final(project, initial, final, targets)
    assert [kind for kind, _ in receipts] == ["before", "after", "before", "after"]
    assert [s.publication.promoted_prefix for _, s in receipts] == [1, 2, 2, 2]
    assert [op.current_bytes for op in initial.publication.operations] == [b"before", b"before"]
    with pytest.raises(FrozenInstanceError):
        final.files = ()


@pytest.mark.parametrize("depth", [0, 1, 2, 3])
def test_manually_constructed_canonical_next_parent_prefix_resumes(tmp_path, depth):
    project, prepared, initial, _, targets = _prepared(tmp_path, nested=True)
    chain = ("specs/a", "specs/a/new", "specs/a/new/value")
    # depth 3 represents a complete first operation, not an extra directory.
    for parent in chain[:min(depth, 2)]:
        (project / parent).mkdir(mode=0o755)
        (project / parent).chmod(0o755)
    if depth == 3:
        (project / targets[0]).write_bytes(b"after")
        (project / targets[0]).chmod(0o640)
    previous_umask = os.umask(0o077)
    try:
        final = prepared.publish_sources(initial)
    finally:
        os.umask(previous_umask)
    _assert_final(project, initial, final, targets)
    assert {p.relative_to(project).as_posix() for p in (project / "specs").rglob("*")} == {
        "specs/empty", "specs/.evidence", "specs/a", "specs/a/new", "specs/a/new/value",
        "specs/z", "specs/z/new", "specs/z/new/value",
    }
    for directory in ("specs/a", "specs/a/new", "specs/z", "specs/z/new"):
        assert stat.S_IMODE((project / directory).stat().st_mode) == 0o755


@pytest.mark.parametrize("mutation", ["content", "mode", "add", "remove", "directory-mode", "empty-directory",
                                      "external", "absence", "later-parent", "sibling", "parent-mode", "temporary"])
def test_unclassified_source_damage_is_retained_without_promotion(tmp_path, mutation):
    project, prepared, initial, stage, targets = _prepared(tmp_path, nested=True)
    evidence = project / "specs/.evidence"
    if mutation == "content": evidence.write_bytes(b"changed")
    elif mutation == "mode": evidence.chmod(0o600)
    elif mutation == "add": (project / "specs/new.bin").write_bytes(b"\xff")
    elif mutation == "remove": evidence.unlink()
    elif mutation == "directory-mode": (project / "specs/empty").chmod(0o700)
    elif mutation == "empty-directory": (project / "specs/extra").mkdir()
    elif mutation == "external": (project / "rules").write_bytes(b"changed")
    elif mutation == "absence": (project / "absent").write_bytes(b"appeared")
    elif mutation == "later-parent": (project / "specs/z").mkdir(mode=0o755)
    elif mutation == "sibling": (project / "specs/a/sibling").mkdir(parents=True)
    elif mutation == "parent-mode": (project / "specs/a").mkdir(mode=0o700)
    else: (project / "specs/.publication-unknown.tmp").write_bytes(b"orphan")
    inventory = {p.relative_to(project).as_posix(): (p.read_bytes() if p.is_file() else None,
                 stat.S_IMODE(p.stat().st_mode)) for p in project.rglob("*")}
    calls = []
    with pytest.raises(PublicationError, match="^target_drift$"):
        prepared.publish_sources(initial, before_publish=calls.append)
    assert calls == [] and stage.exists()
    assert not any((project / target).exists() for target in targets)
    assert inventory == {p.relative_to(project).as_posix(): (p.read_bytes() if p.is_file() else None,
                         stat.S_IMODE(p.stat().st_mode)) for p in project.rglob("*")}


@pytest.mark.parametrize("when", ["before", "fault-0", "fault-1", "fault-2", "after"])
def test_callback_or_fault_dependency_drift_blocks_at_exact_prefix(tmp_path, when):
    project, prepared, initial, stage, targets = _prepared(tmp_path)
    receipts = []
    def mutate(): (project / "specs/.evidence").write_bytes(b"changed")
    def before(snapshot):
        receipts.append("before")
        assert (project / targets[0]).read_bytes() == b"before"
        if when == "before": mutate()
    def fault(position):
        if when == f"fault-{position}": mutate()
    def after(snapshot):
        receipts.append("after")
        assert (project / targets[1]).read_bytes() == b"after"
        if when == "after": mutate()
    with pytest.raises(PublicationError, match="^target_drift$"):
        prepared.publish_sources(initial, before_publish=before, after_publish=after, fault_hook=fault)
    prefix = {"before": 0, "fault-0": 0, "fault-1": 1, "fault-2": 2, "after": 2}[when]
    assert [(project / t).read_bytes() for t in targets] == [b"after"] * prefix + [b"before"] * (2-prefix)
    assert receipts == (["before", "after"] if when == "after" else ["before"])
    assert stage.exists() and (project / "specs/.evidence").read_bytes() == b"changed"


@pytest.mark.parametrize("when", ["before", "after", "fault"])
@pytest.mark.parametrize("exception", [RuntimeError("trusted hook"), KeyboardInterrupt()])
def test_hook_failure_propagation_and_owned_descriptor_cleanup(tmp_path, monkeypatch, when, exception):
    project, prepared, initial, stage, targets = _prepared(tmp_path)
    opened = set()
    original_open, original_dup = os.open, os.dup
    def record_open(*args, **kwargs):
        fd = original_open(*args, **kwargs); opened.add(fd); return fd
    def record_dup(*args):
        fd = original_dup(*args); opened.add(fd); return fd
    def fail(_): raise exception
    with monkeypatch.context() as patch:
        patch.setattr(publication, "_secure_posix_capabilities_available", lambda: True)
        patch.setattr(os, "open", record_open)
        patch.setattr(os, "dup", record_dup)
        expected = PublicationError if when == "fault" and isinstance(exception, Exception) else type(exception)
        with pytest.raises(expected) as caught:
            prepared.publish_sources(initial, **{ {"before": "before_publish", "after": "after_publish", "fault": "fault_hook"}[when]: fail})
        if expected is not PublicationError: assert caught.value is exception
        for fd in opened:
            with pytest.raises(OSError): os.fstat(fd)
    assert [(project / t).read_bytes() for t in targets] == [b"after" if when == "after" else b"before"] * 2
    assert stage.exists()
    _assert_final(project, initial, prepared.publish_sources(initial), targets)


@pytest.mark.parametrize("malformed", [None, {}, "snapshot", 1])
def test_malformed_snapshot_rejected_before_lock(tmp_path, monkeypatch, malformed):
    _, prepared, _, _, _ = _prepared(tmp_path)
    monkeypatch.setattr(publication, "_project_inspection_scope", lambda *a: pytest.fail("acquired lock"))
    with pytest.raises(PublicationError, match="^manifest_invalid$"):
        prepared.publish_sources(malformed)


@pytest.mark.parametrize("name", ["before_publish", "after_publish", "fault_hook"])
def test_malformed_callback_rejected_before_lock(tmp_path, monkeypatch, name):
    _, prepared, initial, _, _ = _prepared(tmp_path)
    monkeypatch.setattr(publication, "_project_inspection_scope", lambda *a: pytest.fail("acquired lock"))
    with pytest.raises(PublicationError, match="^manifest_invalid$"):
        prepared.publish_sources(initial, **{name: 7})


def test_empty_delete_noop_mode_only_and_explicit_targets(tmp_path):
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"; squad.mkdir(parents=True)
    (project / "specs/empty").mkdir(parents=True)
    (project / "specs").chmod(0o751)
    (project / "specs/empty").chmod(0o711)
    for name in ("delete", "mode", "noop"):
        (project / name).write_bytes(b"same"); (project / name).chmod(0o600)
    transaction = SquadPublicationTransaction.begin(project, squad, "5" * 32)
    for name, content, mode in (("empty", b"", 0o600), ("mode", b"same", 0o640), ("noop", b"same", 0o600)):
        stage = transaction.build_path(name); stage.write_bytes(content); stage.chmod(mode)
        transaction.add_write(Path(name), stage, owned_paths={Path(name)})
    for name in ("delete", "missing/file"):
        transaction.add_delete(Path(name), owned_paths={Path(name)})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs",), file_paths=("delete", "empty", "mode", "noop", "missing/file")) as initial: pass
    final = prepared.publish_sources(initial)
    assert snapshot_source_manifest(trees=final.trees, files=final.files) == project_publication_source_manifest(initial)
    assert [(f.path, f.content, f.image.mode) for f in final.files] == [
        ("delete", None, None), ("empty", b"", 0o600), ("missing/file", None, None), ("mode", b"same", 0o640), ("noop", b"same", 0o600)]
    assert [(d.path, d.mode) for d in final.trees[0].directories] == [("specs", 0o751), ("specs/empty", 0o711)]
    assert not (project / "delete").exists() and not (project / "missing").exists()


def test_actual_mkdir_fsync_failure_closes_descriptors_and_resumes(tmp_path, monkeypatch):
    project, prepared, initial, stage, targets = _prepared(tmp_path, nested=True)
    original_fsync, original_open, original_dup = os.fsync, os.open, os.dup
    opened = set()
    def record_open(*args, **kwargs):
        fd = original_open(*args, **kwargs); opened.add(fd); return fd
    def record_dup(*args):
        fd = original_dup(*args); opened.add(fd); return fd
    def fail(fd):
        created = project / "specs/a"
        if created.exists() and os.fstat(fd).st_ino == created.stat().st_ino:
            assert stat.S_IMODE(os.fstat(fd).st_mode) == 0o755
            raise OSError("injected mkdir durability failure")
        original_fsync(fd)
    with monkeypatch.context() as patch:
        patch.setattr(publication, "_secure_posix_capabilities_available", lambda: True)
        patch.setattr(os, "open", record_open); patch.setattr(os, "dup", record_dup)
        patch.setattr(os, "fsync", fail)
        with pytest.raises(PublicationError, match="^publish_io$"):
            prepared.publish_sources(initial)
        assert (project / "specs/a").is_dir() and not (project / "specs/a/new").exists()
        assert stage.exists()
        for fd in opened:
            with pytest.raises(OSError): os.fstat(fd)
    _assert_final(project, initial, prepared.publish_sources(initial), targets)


@pytest.mark.parametrize("boundary", ["before-lock", "acquiring-lock", "before-callback", "copy-root", "copy-ancestor", "copy-stage"])
def test_named_root_ancestor_and_stage_replacements_never_follow_substitute(tmp_path, monkeypatch, boundary):
    project, prepared, initial, stage, targets = _prepared(tmp_path)
    moved = project.with_name(project.name + "-moved")
    original_lock = publication._publication_exclusivity
    original_open = publication._open_directory
    original_copy = publication._copy_pinned_stage_to_temporary
    swapped = False
    def swap_root():
        nonlocal swapped
        project.rename(moved); project.mkdir(); swapped = True
        (project / "specs").mkdir()
        for target in targets: (project / target).write_bytes(b"replacement")
    @contextmanager
    def lock(root, **kwargs):
        if boundary == "before-lock": swap_root()
        with original_lock(root, **kwargs): yield
    def opened(path, **kwargs):
        if boundary == "acquiring-lock" and Path(path) == project and not swapped:
            swap_root()
            fd = original_open(path, **kwargs)
            # Restore the original pathname before lock identity comparison.
            project.rename(project.with_name(project.name + "-substitute")); moved.rename(project)
            return fd
        return original_open(path, **kwargs)
    def copied(*args, **kwargs):
        result = original_copy(*args, **kwargs)
        if boundary == "copy-root": swap_root()
        elif boundary == "copy-ancestor":
            (project / "specs").rename(project / "old-specs"); (project / "specs").mkdir()
            for target in targets: (project / target).write_bytes(b"replacement")
        elif boundary == "copy-stage":
            stage.rename(stage.with_name("old-stage")); stage.write_bytes(b"after"); stage.chmod(0o640)
        return result
    def before(_):
        if boundary == "before-callback": swap_root()
    with monkeypatch.context() as patch:
        patch.setattr(publication, "_publication_exclusivity", lock)
        patch.setattr(publication, "_open_directory", opened)
        patch.setattr(publication, "_copy_pinned_stage_to_temporary", copied)
        with pytest.raises(PublicationError, match="^stage_corrupt$" if boundary == "copy-stage" else "^target_drift$"):
            prepared.publish_sources(initial, before_publish=before)
    if boundary in {"before-lock", "before-callback", "copy-root"}:
        assert [(project / t).read_bytes() for t in targets] == [b"replacement"] * 2
        assert [(moved / t).read_bytes() for t in targets] == [b"before"] * 2
    elif boundary == "copy-ancestor":
        assert [(project / t).read_bytes() for t in targets] == [b"replacement"] * 2
        assert [(project / "old-specs" / Path(t).name).read_bytes() for t in targets] == [b"before"] * 2
    else:
        assert [(project / t).read_bytes() for t in targets] == [b"before"] * 2


def _competing_publisher(project, squad, marker, connection):
    try:
        prepared = publication.load_prepared_publication(Path(project), Path(squad), marker)
        original = publication._fcntl.flock
        def flock(fd, operation):
            if operation == publication._fcntl.LOCK_EX:
                try: original(fd, operation | publication._fcntl.LOCK_NB)
                except BlockingIOError: connection.send("blocked")
                else:
                    connection.send("unexpected-acquisition"); return
            original(fd, operation)
        publication._fcntl.flock = flock
        prepared.publish()
        connection.send("published")
    except BaseException as error:
        connection.send((type(error).__name__, str(error)))
    finally:
        connection.close()


def test_single_retained_lock_excludes_process_through_after_callback(tmp_path, monkeypatch):
    project, prepared, initial, _, targets = _prepared(tmp_path)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_competing_publisher, args=(str(project), str(prepared._squad_dir), prepared.marker, child))
    locks, roots, mutations = [], [], []
    original_lock = publication._publication_exclusivity
    original_parent = publication._open_parent_directory
    @contextmanager
    def lock(root, *, expected_project_fd=None):
        assert expected_project_fd is not None
        locks.append(expected_project_fd)
        with original_lock(root, expected_project_fd=expected_project_fd): yield
        assert os.fstat(expected_project_fd).st_ino == project.stat().st_ino
    def open_parent(root, relative, **kwargs):
        fd = kwargs["project_fd"]
        assert fd == locks[0] and os.fstat(fd).st_ino == project.stat().st_ino
        mutations.append(relative.as_posix())
        return original_parent(root, relative, **kwargs)
    def before(snapshot):
        roots.append(os.fstat(locks[0]).st_ino)
        process.start(); child.close()
        assert parent.poll(10) and parent.recv() == "blocked"
        assert [(project / t).read_bytes() for t in targets] == [b"before"] * 2
    def after(snapshot):
        roots.append(os.fstat(locks[0]).st_ino)
        assert not parent.poll(0.1)
        assert [(project / t).read_bytes() for t in targets] == [b"after"] * 2
    def forbidden(*args, **kwargs): pytest.fail("nested public owner")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(publication, "_publication_exclusivity", lock)
            patch.setattr(publication, "_open_parent_directory", open_parent)
            for name in ("publish", "inspect", "inspect_sources", "discard"):
                patch.setattr(publication.PreparedSquadPublication, name, forbidden)
            final = prepared.publish_sources(initial, before_publish=before, after_publish=after)
        assert len(locks) == 1 and roots == [project.stat().st_ino] * 2
        assert mutations == list(targets)
        with pytest.raises(OSError): os.fstat(locks[0])
        assert parent.poll(10) and parent.recv() == "published"
        process.join(10); assert process.exitcode == 0
        _assert_final(project, initial, final, targets)
    finally:
        if process.is_alive(): process.terminate(); process.join(10)
        parent.close(); child.close()


def test_lock_inversion_and_callback_authority_failure_propagate(tmp_path):
    project, prepared, initial, _, targets = _prepared(tmp_path)
    with controller_lock_order("completion", "outer"):
        with pytest.raises(LockOrderViolation): prepared.publish_sources(initial)
    def invalid_owner(_):
        with controller_lock_order("phase_a", "inverted"): pass
    with pytest.raises(LockOrderViolation): prepared.publish_sources(initial, before_publish=invalid_owner)
    assert [(project / t).read_bytes() for t in targets] == [b"before"] * 2
    _assert_final(project, initial, prepared.publish_sources(initial), targets)


@pytest.mark.parametrize("damage", ["marker", "operation-count", "target", "postimage", "preimage", "stage", "manifest", "initial-prefix", "selection-shape", "path-kind"])
def test_initial_and_current_seal_mismatch_blocks_before_callback(tmp_path, damage):
    project, prepared, initial, stage, targets = _prepared(tmp_path)
    expected = "target_drift"
    if damage == "marker":
        initial = replace(initial, publication=replace(initial.publication,
                          marker=replace(initial.publication.marker, transaction_id="6" * 32)))
    elif damage == "operation-count":
        initial = replace(initial, publication=replace(initial.publication, operations=initial.publication.operations[:1]))
    elif damage in {"target", "postimage", "preimage"}:
        # Empty selection deliberately isolates seal association from codec/source
        # consistency checks. It confers no dependency-completeness proof.
        initial = replace(initial, trees=(), files=())
        first, second = initial.publication.operations
        if damage == "target": first = replace(first, target="specs/aa")
        else:
            image = replace(first.preimage if damage == "preimage" else first.postimage,
                            sha256=hashlib.sha256(b"forged").hexdigest())
            first = (replace(first, preimage=image, current=image, current_bytes=b"forged")
                     if damage == "preimage" else replace(first, postimage=image, postimage_bytes=b"forged"))
        initial = replace(initial, publication=replace(initial.publication, operations=(first, second)))
    elif damage == "stage": stage.write_bytes(b"changed"); expected = "stage_corrupt"
    elif damage == "manifest": (prepared._transaction_root / "manifest.json").write_bytes(b"bad"); expected = "manifest_mismatch"
    elif damage == "initial-prefix":
        initial = replace(initial, publication=replace(initial.publication, promoted_prefix=1)); expected = "manifest_invalid"
    elif damage == "selection-shape":
        initial = replace(initial, trees=list(initial.trees)); expected = "manifest_invalid"
    else:
        # A selected absent file used as a parent of the sealed target is an
        # impossible final projection, rejected by the unchanged public guard.
        from harness.squad_source_snapshot import ProjectPathSnapshot
        from harness.squad_publication_snapshot import PublicationImageDescriptor
        initial = replace(initial, trees=(), files=(ProjectPathSnapshot("specs", PublicationImageDescriptor("missing", None, None), None),))
        expected = "manifest_invalid"
    calls = []
    with pytest.raises(PublicationError, match=f"^{expected}$"):
        prepared.publish_sources(initial, before_publish=calls.append)
    assert calls == [] and [(project / t).read_bytes() for t in targets] == [b"before"] * 2
    assert stage.exists()


def test_synthetic_capture_selection_mismatch_is_not_accepted(tmp_path, monkeypatch):
    import harness.squad_source_snapshot as sources
    project, prepared, initial, stage, targets = _prepared(tmp_path)
    capture = sources._capture_project_tree
    def damaged(*args):
        tree = capture(*args)
        return replace(tree, path="different-missing-tree") if tree.path == "missing-tree" else tree
    monkeypatch.setattr(sources, "_capture_project_tree", damaged)
    with pytest.raises(PublicationError, match="^target_drift$"):
        prepared.publish_sources(initial)
    assert [(project / t).read_bytes() for t in targets] == [b"before"] * 2 and stage.exists()


def test_self_consistent_omitted_dependency_is_not_authenticated_by_guard(tmp_path):
    project, prepared, initial, _, targets = _prepared(tmp_path)
    initial = replace(initial, files=())
    (project / "rules").write_bytes(b"omitted and changed")
    result = prepared.publish_sources(initial)
    assert result.files == ()
    assert [(project / t).read_bytes() for t in targets] == [b"after"] * 2
    assert (project / "rules").read_bytes() == b"omitted and changed"


@pytest.mark.parametrize("damage", ["symlink", "capture-read", "capture-exit"])
def test_capture_failure_closes_every_owned_descriptor(tmp_path, monkeypatch, damage):
    project, prepared, initial, stage, targets = _prepared(tmp_path)
    evidence = project / "specs/.evidence"
    if damage == "symlink":
        evidence.unlink(); evidence.symlink_to(project / "rules")
    original_open, original_dup, original_read = os.open, os.dup, publication._read_fd_bytes
    opened = set()
    def record_open(*args, **kwargs):
        fd = original_open(*args, **kwargs); opened.add(fd); return fd
    def record_dup(*args):
        fd = original_dup(*args); opened.add(fd); return fd
    def read(fd, *, code):
        if damage == "capture-read" and os.fstat(fd).st_ino == evidence.stat().st_ino:
            raise OSError("injected source read")
        result = original_read(fd, code=code)
        if damage == "capture-exit" and os.fstat(fd).st_ino == (project / "rules").stat().st_ino:
            evidence.write_bytes(b"changed during capture")
        return result
    with monkeypatch.context() as patch:
        patch.setattr(publication, "_secure_posix_capabilities_available", lambda: True)
        patch.setattr(os, "open", record_open); patch.setattr(os, "dup", record_dup)
        patch.setattr(publication, "_read_fd_bytes", read)
        with pytest.raises(PublicationError): prepared.publish_sources(initial)
        for fd in opened:
            with pytest.raises(OSError): os.fstat(fd)
    assert [(project / t).read_bytes() for t in targets] == [b"before"] * 2 and stage.exists()


def test_empty_operation_and_source_selection_still_runs_each_callback(tmp_path):
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"; squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(project, squad, "7" * 32)
    prepared = transaction.seal()
    with prepared.inspect_sources() as initial: pass
    calls = []
    final = prepared.publish_sources(initial, before_publish=lambda s: calls.append("before"),
                                     after_publish=lambda s: calls.append("after"), fault_hook=lambda p: calls.append(p))
    assert calls == ["before", 0, "after"] and final == initial


@pytest.mark.parametrize("already_post", [False, True])
def test_stage_mode_damage_blocks_even_already_post_retry(tmp_path, already_post):
    project, prepared, initial, stage, targets = _prepared(tmp_path)
    if already_post: prepared.publish_sources(initial)
    stage.chmod(0o600)
    calls = []
    with pytest.raises(PublicationError, match="^stage_corrupt$"):
        prepared.publish_sources(initial, before_publish=calls.append)
    assert calls == []
    assert [(project / t).read_bytes() for t in targets] == [b"after" if already_post else b"before"] * 2
    assert stat.S_IMODE(stage.stat().st_mode) == 0o600


def test_parent_pin_descriptor_exhaustion_closes_partial_ownership(tmp_path, monkeypatch):
    project, prepared, initial, _, targets = _prepared(tmp_path)
    original_parent, original_dup = publication._open_parent_directory, os.dup
    duplicates = []
    def open_parent(*args, **kwargs):
        count = 0
        def duplicate(fd):
            nonlocal count
            if sys._getframe(1).f_code.co_name != "_open_parent_directory":
                return original_dup(fd)
            count += 1
            if count == 3: raise OSError("injected descriptor exhaustion")
            result = original_dup(fd); duplicates.append(result); return result
        with monkeypatch.context() as patch:
            patch.setattr(os, "dup", duplicate)
            return original_parent(*args, **kwargs)
    monkeypatch.setattr(publication, "_open_parent_directory", open_parent)
    with pytest.raises((OSError, PublicationError)):
        prepared.publish_sources(initial)
    assert len(duplicates) == 2
    for fd in duplicates:
        with pytest.raises(OSError): os.fstat(fd)
    assert [(project / t).read_bytes() for t in targets] == [b"before"] * 2


def test_missing_secure_capability_has_no_legacy_fallback(tmp_path, monkeypatch):
    project, prepared, initial, _, targets = _prepared(tmp_path)
    monkeypatch.setattr(publication, "_secure_posix_capabilities_available", lambda: False)
    monkeypatch.setattr(publication.PreparedSquadPublication, "publish", lambda *a: pytest.fail("legacy fallback"))
    with pytest.raises(PublicationError, match="^publish_io$"): prepared.publish_sources(initial)
    assert [(project / t).read_bytes() for t in targets] == [b"before"] * 2


def test_out_of_order_postimage_cannot_grant_a_source_prefix(tmp_path):
    project, prepared, initial, _, targets = _prepared(tmp_path)
    (project / targets[1]).write_bytes(b"after"); (project / targets[1]).chmod(0o640)
    calls = []
    with pytest.raises(PublicationError, match="^target_drift$"):
        prepared.publish_sources(initial, before_publish=calls.append)
    assert calls == []
    assert [(project / t).read_bytes() for t in targets] == [b"before", b"after"]


@pytest.mark.parametrize("parent_prefix", [False, True])
def test_absent_selected_root_is_created_only_for_its_next_write(tmp_path, parent_prefix):
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"; squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(project, squad, "8" * 32)
    stage = transaction.build_path("stage"); stage.write_bytes(b"new"); stage.chmod(0o604)
    target = Path("new/root/value")
    transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("new/root",)) as initial: pass
    assert not initial.trees[0].exists
    if parent_prefix:
        (project / "new/root").mkdir(parents=True)
        (project / "new").chmod(0o755); (project / "new/root").chmod(0o755)
    final = prepared.publish_sources(initial)
    assert snapshot_source_manifest(trees=final.trees, files=final.files) == project_publication_source_manifest(initial)
    assert [(d.path, d.mode) for d in final.trees[0].directories] == [("new/root", 0o755)]
    assert [(f.path, f.content, f.image.mode) for f in final.trees[0].files] == [("new/root/value", b"new", 0o604)]
    assert (project / target).read_bytes() == b"new" and not initial.trees[0].exists


@pytest.mark.parametrize("ancestor", ["existing", "created"])
def test_identical_target_ancestor_replacement_between_operations_is_rejected(tmp_path, ancestor):
    project, prepared, initial, stage, targets = _prepared(tmp_path, nested=ancestor == "created")
    path = project / ("specs" if ancestor == "existing" else "specs/a/new")
    moved = project / "retained-ancestor"
    replaced = []
    def fault(position):
        if position == 1:
            original_inode = path.stat().st_ino
            path.rename(moved)
            shutil.copytree(moved, path, copy_function=shutil.copy2)
            assert path.stat().st_ino != original_inode
            assert stat.S_IMODE(path.stat().st_mode) == stat.S_IMODE(moved.stat().st_mode)
            replaced.append(path)
    with pytest.raises(PublicationError, match="^target_drift$"):
        prepared.publish_sources(initial, fault_hook=fault)
    assert replaced == [path] and stage.exists()
    assert (project / targets[0]).read_bytes() == b"after"
    if ancestor == "existing":
        assert (project / targets[1]).read_bytes() == b"before"
        assert (moved / "a").read_bytes() == b"after"
    else:
        assert not (project / targets[1]).exists()
        assert (moved / "value").read_bytes() == b"after"
