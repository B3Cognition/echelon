import builtins
import hashlib
import io
import json
import os
import random
import secrets
import socket
import sqlite3
import time
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

import harness.squad_publication as publication
from harness.squad_publication import PublicationError, PublicationMarker
from harness.squad_publication_snapshot import (
    PublicationImageDescriptor,
    PublicationOperationSnapshot,
    PublicationSnapshot,
)
from harness.squad_source_snapshot import (
    ProjectDirectorySnapshot,
    ProjectFileSnapshot,
    ProjectPathSnapshot,
    ProjectTreeSnapshot,
    PublicationSourcesSnapshot,
)


pytestmark = pytest.mark.unit


@pytest.fixture
def secure_posix():
    if not publication._secure_posix_capabilities_available():
        pytest.skip("descriptor-safe POSIX publication is unavailable")


def _missing():
    return PublicationImageDescriptor("missing", None, None)


def _file(content, mode=0o644):
    return PublicationImageDescriptor("file", hashlib.sha256(content).hexdigest(), mode)


def _operation(action, target, before, after, *, before_mode=0o644, after_mode=0o644):
    preimage = _missing() if before is None else _file(before, before_mode)
    postimage = _missing() if after is None else _file(after, after_mode)
    return PublicationOperationSnapshot(
        action, target, preimage, postimage, preimage, before, after,
    )


def _sources(*, operations=(), trees=(), files=(), promoted_prefix=0):
    return PublicationSourcesSnapshot(
        PublicationSnapshot(
            PublicationMarker(1, "a" * 32, "b" * 64),
            promoted_prefix,
            tuple(operations),
        ),
        tuple(trees),
        tuple(files),
    )


def test_projected_manifest_matches_real_write_delete_and_new_directories(
    tmp_path, secure_posix,
):
    from pathlib import Path
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs").mkdir()
    (project / "specs").chmod(0o750)
    (project / "specs/old.md").write_bytes(b"old")
    (project / "specs/.keep").write_bytes(b"\x00\xff")
    transaction = SquadPublicationTransaction.begin(project, squad, "2" * 32)
    stage = transaction.build_path("after.md")
    stage.write_bytes(b"FR-1000000\r\nnew")
    stage.chmod(0o640)
    write = Path("specs/nested/new.md")
    delete = Path("specs/old.md")
    transaction.add_write(write, stage, owned_paths={write})
    transaction.add_delete(delete, owned_paths={delete})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs",)) as initial:
        assert initial.trees[0].directories[0].mode == 0o750
        assert {item.path: item.content for item in initial.trees[0].files} == {
            "specs/.keep": b"\x00\xff", "specs/old.md": b"old"}
    from harness.squad_source_projection import project_publication_source_manifest
    expected = project_publication_source_manifest(initial)
    prepared.publish()
    with prepared.inspect_sources(tree_paths=("specs",)) as final:
        actual = snapshot_source_manifest(trees=final.trees, files=final.files)
        assert {item.path: item.mode for item in final.trees[0].directories} == {
            "specs": 0o750, "specs/nested": 0o755}
        assert {item.path: item.content for item in final.trees[0].files} == {
            "specs/.keep": b"\x00\xff", "specs/nested/new.md": b"FR-1000000\r\nnew"}
    assert actual == expected


def test_projection_has_complete_independently_derived_payload():
    from harness.squad_source_projection import project_publication_source_manifest

    initial = _sources(
        operations=(
            _operation(
                "write", "specs/nested/new.md", None, b"new\r\n",
                after_mode=0o640,
            ),
            _operation("delete", "specs/old.md", b"old", None),
        ),
        trees=(ProjectTreeSnapshot(
            "specs", True,
            (ProjectDirectorySnapshot("specs", 0o750),),
            (
                ProjectFileSnapshot("specs/.keep", _file(b"\x00\xff", 0o600), b"\x00\xff"),
                ProjectFileSnapshot("specs/old.md", _file(b"old"), b"old"),
            ),
        ),),
        files=(ProjectPathSnapshot("selected-empty", _file(b"", 0o600), b""),),
    )

    projected = project_publication_source_manifest(initial)
    expected = (
        '{"files":[{"image":{"kind":"file","mode":"384",'
        '"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},'
        '"path":"selected-empty"}],"trees":[{"directories":[{"mode":"488",'
        '"path":"specs"},{"mode":"493","path":"specs/nested"}],"exists":"true",'
        '"files":[{"image":{"kind":"file","mode":"384",'
        '"sha256":"06eb7d6a69ee19e5fbdf749018d3d2abfa04bcbd1365db312eb86dc7169389b8"},'
        '"path":"specs/.keep"},{"image":{"kind":"file","mode":"416",'
        '"sha256":"9f5d1ba48d2fd5c3aaa39bad078e9a929f1d292511f8febc308def37c3840ab2"},'
        '"path":"specs/nested/new.md"}],"path":"specs"}],"version":"1"}'
    )
    assert projected.payload == expected
    assert projected.sha256 == "7ef54d8619c362427a49f978bcbecc966b02fb81bd142000b8c7412b8b71313a"


def test_empty_and_unchanged_absent_sources_preserve_exact_selection():
    from harness.squad_source_manifest import snapshot_source_manifest
    from harness.squad_source_projection import project_publication_source_manifest

    empty = _sources()
    assert project_publication_source_manifest(empty).payload == (
        '{"files":[],"trees":[],"version":"1"}'
    )

    trees = (
        ProjectTreeSnapshot(
            "empty-tree", True,
            (ProjectDirectorySnapshot("empty-tree", 0o711),), (),
        ),
        ProjectTreeSnapshot("missing/tree", False, (), ()),
    )
    files = (
        ProjectPathSnapshot("empty-file", _file(b"", 0o600), b""),
        ProjectPathSnapshot("missing-file", _missing(), None),
    )
    initial = _sources(trees=trees, files=files)
    assert project_publication_source_manifest(initial) == snapshot_source_manifest(
        trees=trees, files=files,
    )


def test_projection_preserves_rich_membership_and_empty_directories():
    from harness.squad_source_projection import project_publication_source_manifest

    wide = b"\xff\xfeF\x00R\x00-\x001\x000\x000\x000\x000\x000\x000\x00\r\x00\n\x00"
    initial = _sources(
        operations=(
            _operation(
                "write", "source/crlf.md", b"FR-1\r\n", b"FR-1\r\n",
                before_mode=0o640, after_mode=0o600,
            ),
            _operation(
                "write", "source/new/nested/empty.bin", None, b"",
                after_mode=0o600,
            ),
            _operation("write", "source/noop.bin", b"same", b"same"),
            _operation(
                "delete", "source/remove-parent/remove.bin", b"remove", None,
            ),
        ),
        trees=(ProjectTreeSnapshot(
            "source", True,
            (
                ProjectDirectorySnapshot("source", 0o750),
                ProjectDirectorySnapshot("source/empty", 0o701),
                ProjectDirectorySnapshot("source/remove-parent", 0o710),
            ),
            (
                ProjectFileSnapshot("source/.hidden", _file(b"\x00\xff", 0o604), b"\x00\xff"),
                ProjectFileSnapshot("source/crlf.md", _file(b"FR-1\r\n", 0o640), b"FR-1\r\n"),
                ProjectFileSnapshot("source/legacy.bin", _file(wide, 0o400), wide),
                ProjectFileSnapshot("source/noop.bin", _file(b"same"), b"same"),
                ProjectFileSnapshot(
                    "source/remove-parent/remove.bin", _file(b"remove"), b"remove",
                ),
            ),
        ),),
    )
    value = project_publication_source_manifest(initial)
    payload = json.loads(value.payload)
    files_by_path = {
        item["path"]: item for item in payload["trees"][0]["files"]
    }

    assert '"path":"source/.hidden"' in value.payload
    assert '"path":"source/crlf.md"' in value.payload
    assert files_by_path["source/crlf.md"]["image"]["mode"] == "384"
    assert '"path":"source/legacy.bin"' in value.payload
    assert '"path":"source/noop.bin"' in value.payload
    assert '"path":"source/remove-parent/remove.bin"' not in value.payload
    assert '"path":"source/empty"' in value.payload
    assert '"path":"source/remove-parent"' in value.payload
    assert '"path":"source/new"' in value.payload
    assert '"path":"source/new/nested"' in value.payload
    assert '"path":"source/new/nested/empty.bin"' in value.payload


def test_exact_selected_file_writes_and_deletes_preserve_source_boundaries():
    from harness.squad_source_projection import project_publication_source_manifest

    initial = _sources(
        operations=(
            _operation("write", "README", b"before", b"after", after_mode=0o600),
            _operation("delete", "gone", b"old", None),
            _operation("write", "unselected", None, b"outside"),
        ),
        files=(
            ProjectPathSnapshot("README", _file(b"before"), b"before"),
            ProjectPathSnapshot("gone", _file(b"old"), b"old"),
            ProjectPathSnapshot("missing", _missing(), None),
        ),
    )
    projected = project_publication_source_manifest(initial).payload

    assert '"path":"README"' in projected
    assert '"mode":"384"' in projected
    assert "f39592393ef0859cb196a52693d2cea00fb2df784b3c04ae54aa7cadb8e562f8" in projected
    assert '"path":"gone"' in projected and '"kind":"missing"' in projected
    assert '"path":"missing"' in projected
    assert '"path":"unselected"' not in projected


@pytest.mark.parametrize(
    ("selection", "target"),
    (
        ("tree", "specs"),
        ("tree", "specs/root"),
        ("file-above", "config"),
        ("file-below", "config/file/child"),
    ),
)
def test_impossible_write_relationships_are_bounded_and_do_not_mutate(selection, target):
    from harness.squad_source_baseline_codec import encode_initial_publication_sources
    from harness.squad_source_projection import project_publication_source_manifest

    tree_path = "specs/root" if selection == "tree" else "unrelated"
    file_path = "config/file" if selection.startswith("file") else "other"
    initial = _sources(
        operations=(_operation("write", target, None, b"new"),),
        trees=(ProjectTreeSnapshot(tree_path, False, (), ()),),
        files=(ProjectPathSnapshot(file_path, _missing(), None),),
    )
    before = encode_initial_publication_sources(initial)

    with pytest.raises(PublicationError, match="^manifest_invalid$"):
        project_publication_source_manifest(initial)
    assert encode_initial_publication_sources(initial) == before


def test_prefix_sibling_writes_and_relationship_deletes_are_noncreating_controls():
    from harness.squad_source_manifest import snapshot_source_manifest
    from harness.squad_source_projection import project_publication_source_manifest

    trees = (ProjectTreeSnapshot("specs", False, (), ()),)
    files = (ProjectPathSnapshot("config/file", _missing(), None),)
    initial = _sources(
        operations=(
            _operation("write", "config/files", None, b"prefix sibling"),
            _operation("write", "spec", None, b"prefix sibling"),
        ),
        trees=trees,
        files=files,
    )
    assert project_publication_source_manifest(initial) == snapshot_source_manifest(
        trees=trees, files=files,
    )
    for target in ("config", "config/file/child", "specs"):
        delete = _sources(
            operations=(_operation("delete", target, None, None),),
            trees=trees,
            files=files,
        )
        assert project_publication_source_manifest(delete) == snapshot_source_manifest(
            trees=trees, files=files,
        )


def test_real_missing_selected_sources_become_present_only_when_written(
    tmp_path, secure_posix,
):
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    from harness.squad_source_projection import project_publication_source_manifest

    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(project, squad, "c" * 32)
    for target, content in (
        (Path("missing/tree/nested/new.bin"), b"\x00\xff\r\n"),
        (Path("selected-created"), b""),
    ):
        stage = transaction.build_path(target.name + ".stage")
        stage.write_bytes(content)
        stage.chmod(0o600)
        transaction.add_write(target, stage, owned_paths={target})
    absent_delete = Path("selected-deleted")
    transaction.add_delete(absent_delete, owned_paths={absent_delete})
    prepared = transaction.seal()
    with prepared.inspect_sources(
        tree_paths=("missing/tree", "untouched/tree"),
        file_paths=("selected-created", "selected-deleted"),
    ) as initial:
        assert [tree.exists for tree in initial.trees] == [False, False]
        assert [item.content for item in initial.files] == [None, None]
    expected = project_publication_source_manifest(initial)

    prepared.publish()
    with prepared.inspect_sources(
        tree_paths=("missing/tree", "untouched/tree"),
        file_paths=("selected-created", "selected-deleted"),
    ) as final:
        actual = snapshot_source_manifest(trees=final.trees, files=final.files)
        assert [tree.exists for tree in final.trees] == [True, False]
        assert {item.path: item.mode for item in final.trees[0].directories} == {
            "missing/tree": 0o755,
            "missing/tree/nested": 0o755,
        }
        assert [item.content for item in final.files] == [b"", None]
    assert actual == expected


def test_retained_initial_projection_survives_interruption_and_matches_retry(
    tmp_path, secure_posix,
):
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    from harness.squad_source_projection import project_publication_source_manifest

    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(project, squad, "d" * 32)
    for name in ("a", "b"):
        (project / name).write_bytes(f"old-{name}".encode())
        stage = transaction.build_path(f"{name}.stage")
        stage.write_bytes(f"new-{name}".encode())
        target = Path(name)
        transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(file_paths=("a", "b")) as initial:
        pass
    expected = project_publication_source_manifest(initial)

    def interrupt(position):
        if position == 1:
            raise RuntimeError("synthetic interruption")

    with pytest.raises(PublicationError, match="^publish_io$"):
        prepared.publish(fault_hook=interrupt)
    with prepared.inspect_sources(file_paths=("a", "b")) as partial:
        pass
    with pytest.raises(PublicationError, match="^manifest_invalid$"):
        project_publication_source_manifest(partial)
    assert project_publication_source_manifest(initial) == expected

    prepared.publish()
    with prepared.inspect_sources(file_paths=("a", "b")) as final:
        actual = snapshot_source_manifest(trees=final.trees, files=final.files)
    with pytest.raises(PublicationError, match="^manifest_invalid$"):
        project_publication_source_manifest(final)
    assert actual == expected
    assert project_publication_source_manifest(initial) == expected


@pytest.mark.parametrize(
    "mutation",
    ("hidden-addition", "empty-directory-deletion", "file-bytes", "file-mode", "directory-mode"),
)
def test_real_unsealed_selected_source_changes_differ_from_projection(
    tmp_path, secure_posix, mutation,
):
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    from harness.squad_source_projection import project_publication_source_manifest

    project = tmp_path.resolve()
    (project / "source/empty").mkdir(parents=True)
    (project / "source/input").write_bytes(b"before")
    (project / "source/input").chmod(0o640)
    (project / "source").chmod(0o750)
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(project, squad, "e" * 32)
    stage = transaction.build_path("outside.stage")
    stage.write_bytes(b"published")
    target = Path("outside")
    transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("source",)) as initial:
        pass
    expected = project_publication_source_manifest(initial)
    prepared.publish()

    if mutation == "hidden-addition":
        (project / "source/.hidden").write_bytes(b"new")
    elif mutation == "empty-directory-deletion":
        (project / "source/empty").rmdir()
    elif mutation == "file-bytes":
        (project / "source/input").write_bytes(b"changed")
    elif mutation == "file-mode":
        (project / "source/input").chmod(0o600)
    else:
        (project / "source").chmod(0o700)

    with prepared.inspect_sources(tree_paths=("source",)) as changed:
        actual = snapshot_source_manifest(trees=changed.trees, files=changed.files)
    assert actual != expected


def test_initial_guard_rejects_noninitial_and_structurally_invalid_snapshots():
    from harness.squad_source_projection import project_publication_source_manifest

    valid = _sources(files=(ProjectPathSnapshot("source", _file(b"ok"), b"ok"),))
    noninitial = replace(
        valid,
        publication=replace(valid.publication, promoted_prefix=1),
    )
    structurally_invalid = replace(
        valid,
        files=(ProjectPathSnapshot("source", _file(b"other"), b"ok"),),
    )
    for invalid in (noninitial, structurally_invalid):
        with pytest.raises(PublicationError, match="^manifest_invalid$"):
            project_publication_source_manifest(invalid)


def test_output_is_frozen_and_input_objects_and_bytes_are_unchanged():
    from harness.squad_source_baseline_codec import encode_initial_publication_sources
    from harness.squad_source_projection import project_publication_source_manifest

    content = b"before"
    selected = ProjectPathSnapshot("source", _file(content), content)
    initial = _sources(
        operations=(_operation("write", "source", content, b"after"),),
        files=(selected,),
    )
    baseline = encode_initial_publication_sources(initial)
    result = project_publication_source_manifest(initial)

    with pytest.raises(FrozenInstanceError):
        result.payload = "changed"
    assert initial.files[0] is selected
    assert initial.files[0].content is content
    assert encode_initial_publication_sources(initial) == baseline


def test_projection_is_pure_after_real_setup(tmp_path, secure_posix, monkeypatch):
    from harness.squad_publication import SquadPublicationTransaction
    import harness.squad_source_projection as projection

    project = tmp_path.resolve()
    (project / "source/empty").mkdir(parents=True)
    (project / "source/input").write_bytes(b"before")
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(project, squad, "f" * 32)
    stage = transaction.build_path("after.stage")
    stage.write_bytes(b"after")
    target = Path("source/input")
    transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("source",)) as initial:
        pass

    def forbidden(*args, **kwargs):
        pytest.fail("projection accessed external state")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(io, "open", forbidden)
        patch.setattr(Path, "open", forbidden)
        patch.setattr(Path, "stat", forbidden)
        patch.setattr(os, "open", forbidden)
        patch.setattr(os, "listdir", forbidden)
        patch.setattr(os, "scandir", forbidden)
        patch.setattr(os, "stat", forbidden)
        patch.setattr(sqlite3, "connect", forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(time, "time", forbidden)
        patch.setattr(time, "monotonic", forbidden)
        patch.setattr(random, "random", forbidden)
        patch.setattr(secrets, "token_bytes", forbidden)
        first = projection.project_publication_source_manifest(initial)
        second = projection.project_publication_source_manifest(initial)
    assert first == second


def test_unexpected_projection_structure_errors_are_bounded_without_context(monkeypatch):
    import traceback
    import harness.squad_source_projection as projection

    initial = _sources()

    def recursive_failure(*args, **kwargs):
        raise RecursionError("untrusted projection structure")

    monkeypatch.setattr(projection, "snapshot_source_manifest", recursive_failure)
    with pytest.raises(PublicationError) as caught:
        projection.project_publication_source_manifest(initial)
    rendered = "".join(traceback.format_exception(caught.value))
    assert str(caught.value) == "manifest_invalid"
    assert caught.value.__suppress_context__ is True
    assert "untrusted projection structure" not in rendered
