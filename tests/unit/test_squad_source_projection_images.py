import builtins
import hashlib
import io
import os
import random
import secrets
import socket
import sqlite3
import subprocess
import time
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

import harness.squad_publication as publication
import harness.squad_source_projection as projection
from harness.squad_publication import SquadPublicationTransaction
from harness.squad_publication import PublicationError, PublicationMarker
from harness.squad_publication_snapshot import (
    PublicationImageDescriptor,
    PublicationOperationSnapshot,
    PublicationSnapshot,
)
from harness.squad_source_manifest import SourceManifestSnapshot, snapshot_source_manifest
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
    return PublicationImageDescriptor(
        "file", hashlib.sha256(content).hexdigest(), mode,
    )


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


def test_projected_images_match_real_guarded_publication(tmp_path, secure_posix):
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs").mkdir()
    (project / "specs").chmod(0o750)
    (project / "specs/.keep").write_bytes(b"\x00\xff")
    (project / "specs/.keep").chmod(0o600)
    transaction = SquadPublicationTransaction.begin(project, squad, "2" * 32)
    stage = transaction.build_path("after.md")
    stage.write_bytes(b"FR-1000000\r\nnew")
    stage.chmod(0o640)
    target = Path("specs/nested/new.md")
    transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs",)) as initial:
        assert initial.trees[0].files[0].content == b"\x00\xff"
    expected_manifest = projection.project_publication_source_manifest(initial)
    result = projection.project_publication_source_images(initial)
    expected_trees = (ProjectTreeSnapshot(
        "specs",
        True,
        (
            ProjectDirectorySnapshot("specs", 0o750),
            ProjectDirectorySnapshot("specs/nested", 0o755),
        ),
        (
            ProjectFileSnapshot(
                "specs/.keep", _file(b"\x00\xff", 0o600), b"\x00\xff",
            ),
            ProjectFileSnapshot(
                "specs/nested/new.md",
                _file(b"FR-1000000\r\nnew", 0o640),
                b"FR-1000000\r\nnew",
            ),
        ),
    ),)
    expected = SourceManifestSnapshot(
        '{"files":[],"trees":[{"directories":[{"mode":"488","path":"specs"},'
        '{"mode":"493","path":"specs/nested"}],"exists":"true","files":['
        '{"image":{"kind":"file","mode":"384","sha256":'
        '"06eb7d6a69ee19e5fbdf749018d3d2abfa04bcbd1365db312eb86dc7169389b8"},'
        '"path":"specs/.keep"},{"image":{"kind":"file","mode":"416",'
        '"sha256":"fd121391282b88fcee24f141093140c0e492f7e01a595fda3621d4104679cf43"},'
        '"path":"specs/nested/new.md"}],"path":"specs"}],"version":"1"}',
        "d70f89babbf5b18e3258036e4dafbbdbd7059de8ac77a324fa125196e6ffdaa4",
    )
    assert result.trees == expected_trees
    assert result.files == ()
    assert result.manifest == expected
    assert result.manifest == expected_manifest
    final = prepared.publish_sources(initial)
    assert result.trees == final.trees
    assert result.files == final.files


def _rich_initial_and_expected():
    wide = b"\xff\xfeF\x00R\x00-\x001\x00\r\x00\n\x00"
    initial = _sources(
        operations=(
            _operation("write", "alpha-created", None, b"", after_mode=0o600),
            _operation("delete", "gone", b"old", None, before_mode=0o640),
            _operation(
                "write", "mode-selected", b"same", b"same",
                before_mode=0o600, after_mode=0o644,
            ),
            _operation(
                "write", "noop-selected", b"stable", b"stable",
                before_mode=0o640, after_mode=0o640,
            ),
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
            _operation("write", "z-unselected", None, b"outside"),
        ),
        trees=(
            ProjectTreeSnapshot(
                "empty-tree", True,
                (ProjectDirectorySnapshot("empty-tree", 0o711),), (),
            ),
            ProjectTreeSnapshot("missing/tree", False, (), ()),
            ProjectTreeSnapshot(
                "source", True,
                (
                    ProjectDirectorySnapshot("source", 0o750),
                    ProjectDirectorySnapshot("source/empty", 0o701),
                    ProjectDirectorySnapshot("source/remove-parent", 0o710),
                ),
                (
                    ProjectFileSnapshot(
                        "source/.hidden", _file(b"\x00\xff", 0o604), b"\x00\xff",
                    ),
                    ProjectFileSnapshot(
                        "source/crlf.md", _file(b"FR-1\r\n", 0o640), b"FR-1\r\n",
                    ),
                    ProjectFileSnapshot(
                        "source/legacy.bin", _file(wide, 0o400), wide,
                    ),
                    ProjectFileSnapshot(
                        "source/noop.bin", _file(b"same"), b"same",
                    ),
                    ProjectFileSnapshot(
                        "source/remove-parent/remove.bin", _file(b"remove"), b"remove",
                    ),
                ),
            ),
        ),
        files=(
            ProjectPathSnapshot("alpha-created", _missing(), None),
            ProjectPathSnapshot("gone", _file(b"old", 0o640), b"old"),
            ProjectPathSnapshot("missing-file", _missing(), None),
            ProjectPathSnapshot("mode-selected", _file(b"same", 0o600), b"same"),
            ProjectPathSnapshot("noop-selected", _file(b"stable", 0o640), b"stable"),
        ),
    )
    trees = (
        ProjectTreeSnapshot(
            "empty-tree", True,
            (ProjectDirectorySnapshot("empty-tree", 0o711),), (),
        ),
        ProjectTreeSnapshot("missing/tree", False, (), ()),
        ProjectTreeSnapshot(
            "source", True,
            (
                ProjectDirectorySnapshot("source", 0o750),
                ProjectDirectorySnapshot("source/empty", 0o701),
                ProjectDirectorySnapshot("source/new", 0o755),
                ProjectDirectorySnapshot("source/new/nested", 0o755),
                ProjectDirectorySnapshot("source/remove-parent", 0o710),
            ),
            (
                ProjectFileSnapshot(
                    "source/.hidden", _file(b"\x00\xff", 0o604), b"\x00\xff",
                ),
                ProjectFileSnapshot(
                    "source/crlf.md", _file(b"FR-1\r\n", 0o600), b"FR-1\r\n",
                ),
                ProjectFileSnapshot("source/legacy.bin", _file(wide, 0o400), wide),
                ProjectFileSnapshot(
                    "source/new/nested/empty.bin", _file(b"", 0o600), b"",
                ),
                ProjectFileSnapshot("source/noop.bin", _file(b"same"), b"same"),
            ),
        ),
    )
    files = (
        ProjectPathSnapshot("alpha-created", _file(b"", 0o600), b""),
        ProjectPathSnapshot("gone", _missing(), None),
        ProjectPathSnapshot("missing-file", _missing(), None),
        ProjectPathSnapshot("mode-selected", _file(b"same"), b"same"),
        ProjectPathSnapshot("noop-selected", _file(b"stable", 0o640), b"stable"),
    )
    manifest = SourceManifestSnapshot(
        '{"files":[{"image":{"kind":"file","mode":"384","sha256":'
        '"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},'
        '"path":"alpha-created"},{"image":{"kind":"missing","mode":null,'
        '"sha256":null},"path":"gone"},{"image":{"kind":"missing","mode":null,'
        '"sha256":null},"path":"missing-file"},{"image":{"kind":"file",'
        '"mode":"420","sha256":"0967115f2813a3541eaef77de9d9d5773f1c0c04314b0bbfe4ff3b3b1c55b5d5"},'
        '"path":"mode-selected"},{"image":{"kind":"file","mode":"416",'
        '"sha256":"f379ccb92b9116442dc65bdc35648a85d3786b34779db7f704a901fa07b00cb6"},'
        '"path":"noop-selected"}],"trees":[{"directories":[{"mode":"457",'
        '"path":"empty-tree"}],"exists":"true","files":[],"path":"empty-tree"},'
        '{"directories":[],"exists":"false","files":[],"path":"missing/tree"},'
        '{"directories":[{"mode":"488","path":"source"},{"mode":"449",'
        '"path":"source/empty"},{"mode":"493","path":"source/new"},'
        '{"mode":"493","path":"source/new/nested"},{"mode":"456",'
        '"path":"source/remove-parent"}],"exists":"true","files":[{"image":'
        '{"kind":"file","mode":"388","sha256":'
        '"06eb7d6a69ee19e5fbdf749018d3d2abfa04bcbd1365db312eb86dc7169389b8"},'
        '"path":"source/.hidden"},{"image":{"kind":"file","mode":"384",'
        '"sha256":"8c17b5c323e119f912f87fe7006589be4605f349ae80b929d8449d123add1c4b"},'
        '"path":"source/crlf.md"},{"image":{"kind":"file","mode":"256",'
        '"sha256":"acf1f3a90b428d4e21a3db1abadab136eb64b3aaa6e85ef82c1379cd2aa2c7d8"},'
        '"path":"source/legacy.bin"},{"image":{"kind":"file","mode":"384",'
        '"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},'
        '"path":"source/new/nested/empty.bin"},{"image":{"kind":"file",'
        '"mode":"420","sha256":'
        '"0967115f2813a3541eaef77de9d9d5773f1c0c04314b0bbfe4ff3b3b1c55b5d5"},'
        '"path":"source/noop.bin"}],"path":"source"}],"version":"1"}',
        "016c0c3efdd4be35d7b87010bc1203d0992e465065493d37a2e4060111f0518b",
    )
    return initial, trees, files, manifest


def test_projected_images_have_complete_independently_derived_records_and_manifest():
    initial, trees, files, manifest = _rich_initial_and_expected()

    result = projection.project_publication_source_images(initial)

    assert type(result) is projection.ProjectedPublicationSources
    assert result.trees == trees
    assert result.files == files
    assert result.manifest == manifest
    assert snapshot_source_manifest(trees=result.trees, files=result.files) == manifest
    assert projection.project_publication_source_manifest(initial) == manifest


def test_projected_images_are_deeply_detached_and_frozen():
    from harness.squad_source_baseline_codec import encode_initial_publication_sources

    initial, trees, files, manifest = _rich_initial_and_expected()
    baseline = encode_initial_publication_sources(initial)
    result = projection.project_publication_source_images(initial)

    assert encode_initial_publication_sources(initial) == baseline
    for projected_tree, original_tree in zip(result.trees, initial.trees, strict=True):
        assert projected_tree is not original_tree
        original_directories = {
            item.path: item for item in original_tree.directories
        }
        for directory in projected_tree.directories:
            if directory.path in original_directories:
                assert directory is not original_directories[directory.path]
        original_files = {item.path: item for item in original_tree.files}
        for item in projected_tree.files:
            if item.path in original_files:
                assert item is not original_files[item.path]
                assert item.image is not original_files[item.path].image
    for item, original in zip(result.files, initial.files, strict=True):
        assert item is not original
        assert item.image is not original.image
    for item in (*result.files, *(file for tree in result.trees for file in tree.files)):
        matching_postimages = (
            operation.postimage
            for operation in initial.publication.operations
            if operation.target == item.path
        )
        assert all(item.image is not image for image in matching_postimages)

    with pytest.raises(FrozenInstanceError):
        result.trees = ()
    with pytest.raises(FrozenInstanceError):
        result.trees[2].directories[0].mode = 0
    with pytest.raises(FrozenInstanceError):
        result.trees[2].files[0].image.kind = "missing"
    with pytest.raises(FrozenInstanceError):
        result.files[0].path = "changed"

    object.__setattr__(initial.trees[2].directories[0], "mode", 0)
    object.__setattr__(initial.trees[2].files[0], "content", b"damaged")
    object.__setattr__(initial.trees[2].files[0].image, "kind", "missing")
    object.__setattr__(initial.files[2], "path", "damaged")
    object.__setattr__(initial.files[4].image, "mode", 0)
    object.__setattr__(initial.publication.operations[0].postimage, "mode", 0)

    assert result.trees == trees
    assert result.files == files
    assert result.manifest == manifest


def test_new_projection_preserves_initial_guard_errors_and_cannot_encode_as_capture():
    from harness.squad_source_baseline_codec import encode_initial_publication_sources

    valid = _sources(
        files=(ProjectPathSnapshot("selected", _file(b"old"), b"old"),),
    )

    class PathSubclass(ProjectPathSnapshot):
        pass

    damaged = _sources(
        files=(ProjectPathSnapshot("selected", _file(b"old"), b"old"),),
    )
    object.__setattr__(damaged.files[0].image, "sha256", "0" * 64)
    malformed = (
        object(),
        replace(valid, publication=replace(valid.publication, promoted_prefix=1)),
        replace(
            valid,
            files=(ProjectPathSnapshot("selected", _file(b"different"), b"old"),),
        ),
        replace(
            valid,
            files=(ProjectPathSnapshot("selected", _file(b"old", 0o10000), b"old"),),
        ),
        replace(
            valid,
            files=(PathSubclass("selected", _file(b"old"), b"old"),),
        ),
        replace(
            valid,
            trees=(ProjectTreeSnapshot("tree", True, (), ()),),
            files=(),
        ),
        damaged,
        _sources(
            operations=(_operation("write", "selected/child", None, b"new"),),
            files=(ProjectPathSnapshot("selected", _missing(), None),),
        ),
    )
    for value in malformed:
        for projector in (
            projection.project_publication_source_manifest,
            projection.project_publication_source_images,
        ):
            with pytest.raises(PublicationError, match="^manifest_invalid$"):
                projector(value)

    result = projection.project_publication_source_images(valid)
    with pytest.raises(PublicationError, match="^manifest_invalid$"):
        encode_initial_publication_sources(result)


def test_component_prefix_siblings_and_outside_operations_do_not_expand_selection():
    trees = (ProjectTreeSnapshot("specs", False, (), ()),)
    files = (ProjectPathSnapshot("config/file", _missing(), None),)
    initial = _sources(
        operations=(
            _operation("write", "config/files", None, b"prefix sibling"),
            _operation("write", "spec", None, b"prefix sibling"),
            _operation("write", "z-outside", None, b"outside"),
        ),
        trees=trees,
        files=files,
    )

    result = projection.project_publication_source_images(initial)

    assert result.trees == trees
    assert result.files == files
    assert result.manifest == snapshot_source_manifest(trees=trees, files=files)
    assert result.trees[0] is not trees[0]
    assert result.files[0] is not files[0]


def test_projection_has_no_external_side_effects(monkeypatch):
    initial, trees, files, manifest = _rich_initial_and_expected()

    def forbidden(*args, **kwargs):
        pytest.fail("projection accessed external state")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(io, "open", forbidden)
        patch.setattr(Path, "open", forbidden)
        patch.setattr(Path, "stat", forbidden)
        patch.setattr(Path, "write_bytes", forbidden)
        patch.setattr(os, "open", forbidden)
        patch.setattr(os, "listdir", forbidden)
        patch.setattr(os, "scandir", forbidden)
        patch.setattr(os, "stat", forbidden)
        patch.setattr(os, "getenv", forbidden)
        patch.setattr(os, "urandom", forbidden)
        patch.setattr(sqlite3, "connect", forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(subprocess, "run", forbidden)
        patch.setattr(subprocess, "Popen", forbidden)
        patch.setattr(time, "time", forbidden)
        patch.setattr(time, "monotonic", forbidden)
        patch.setattr(random, "random", forbidden)
        patch.setattr(secrets, "token_bytes", forbidden)
        patch.setattr(publication, "_project_inspection_scope", forbidden)
        patch.setattr(publication, "_publication_exclusivity", forbidden)
        result = projection.project_publication_source_images(initial)

    assert result.trees == trees
    assert result.files == files
    assert result.manifest == manifest


def test_real_interrupted_prefix_and_parent_progress_keep_legacy_guard_contract(
    tmp_path, secure_posix,
):
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs").mkdir()
    (project / "specs/existing").write_bytes(b"same")
    (project / "specs/existing").chmod(0o600)
    transaction = SquadPublicationTransaction.begin(project, squad, "3" * 32)
    mode_stage = transaction.build_path("mode.stage")
    mode_stage.write_bytes(b"same")
    mode_stage.chmod(0o640)
    nested_stage = transaction.build_path("nested.stage")
    nested_stage.write_bytes(b"new")
    nested_stage.chmod(0o604)
    existing = Path("specs/existing")
    nested = Path("specs/nested/new/value")
    transaction.add_write(existing, mode_stage, owned_paths={existing})
    transaction.add_write(nested, nested_stage, owned_paths={nested})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs",)) as initial:
        pass
    expected = projection.project_publication_source_images(initial)

    def interrupt(position):
        if position == 1:
            raise RuntimeError("synthetic interruption")

    with pytest.raises(PublicationError, match="^publish_io$"):
        prepared.publish_sources(initial, fault_hook=interrupt)
    with prepared.inspect_sources(tree_paths=("specs",)) as partial:
        partial_manifest = snapshot_source_manifest(
            trees=partial.trees, files=partial.files,
        )
    assert partial_manifest == projection._transform_selected_sources(initial, 1)

    (project / "specs/nested").mkdir()
    (project / "specs/nested").chmod(0o755)
    with prepared.inspect_sources(tree_paths=("specs",)) as parent_partial:
        parent_manifest = snapshot_source_manifest(
            trees=parent_partial.trees, files=parent_partial.files,
        )
    assert parent_manifest == projection._transform_selected_sources(
        initial, 1, new_directories=("specs/nested",),
    )

    marker, squad_dir = prepared.marker, prepared._squad_dir
    del prepared
    prepared = publication.load_prepared_publication(project, squad_dir, marker)
    final = prepared.publish_sources(initial)
    assert expected.trees == final.trees
    assert expected.files == final.files
    assert expected.manifest == snapshot_source_manifest(
        trees=final.trees, files=final.files,
    )
