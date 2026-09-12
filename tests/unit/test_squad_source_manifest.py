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
import traceback
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

import harness.squad_publication as publication
from harness.squad_publication_snapshot import PublicationImageDescriptor
from harness.squad_source_snapshot import (
    ProjectDirectorySnapshot,
    ProjectFileSnapshot,
    ProjectPathSnapshot,
    ProjectTreeSnapshot,
)


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def secure_posix():
    if not publication._secure_posix_capabilities_available():
        pytest.skip("descriptor-safe POSIX publication is unavailable")


def test_real_selected_sources_have_independent_closed_manifest(tmp_path):
    from harness.squad_publication import SquadPublicationTransaction

    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs").mkdir()
    (project / "specs").chmod(0o750)
    (project / "specs/notes.md").write_bytes(b"hello")
    (project / "specs/notes.md").chmod(0o640)
    transaction = SquadPublicationTransaction.begin(project, squad, "1" * 32)
    stage = transaction.build_path("after.md")
    stage.write_bytes(b"later")
    target = Path("specs/notes.md")
    transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs",), file_paths=("absent",)) as sources:
        assert sources.trees[0].files[0].content == b"hello"
    from harness.squad_source_manifest import snapshot_source_manifest

    manifest = snapshot_source_manifest(trees=sources.trees, files=sources.files)
    expected = (
        '{"files":[{"image":{"kind":"missing","mode":null,"sha256":null},"path":"absent"}],'
        '"trees":[{"directories":[{"mode":"488","path":"specs"}],"exists":"true",'
        '"files":[{"image":{"kind":"file","mode":"416",'
        '"sha256":"2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"},'
        '"path":"specs/notes.md"}],"path":"specs"}],"version":"1"}'
    )
    assert manifest.payload == expected
    assert manifest.sha256 == hashlib.sha256(expected.encode("ascii")).hexdigest()


def _missing():
    return PublicationImageDescriptor("missing", None, None)


def _file(content, mode=0o644):
    return PublicationImageDescriptor("file", hashlib.sha256(content).hexdigest(), mode)


def _prepared(project, transaction_id="2" * 32, label="capture"):
    from harness.squad_publication import SquadPublicationTransaction

    squad = project / f"runs/spec-{label}"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(project, squad, transaction_id)
    stage = transaction.build_path("after.md")
    stage.write_bytes(label.encode("ascii"))
    target = Path(f"published-{label}.md")
    transaction.add_write(target, stage, owned_paths={target})
    return transaction.seal()


def _capture_manifest(prepared, *, tree_paths=(), file_paths=()):
    from harness.squad_source_manifest import snapshot_source_manifest

    with prepared.inspect_sources(tree_paths=tree_paths, file_paths=file_paths) as sources:
        pass
    return snapshot_source_manifest(trees=sources.trees, files=sources.files), sources


def test_empty_selection_has_exact_closed_wire():
    from harness.squad_source_manifest import snapshot_source_manifest

    manifest = snapshot_source_manifest(trees=(), files=())
    expected = '{"files":[],"trees":[],"version":"1"}'
    assert manifest.payload == expected
    assert manifest.sha256 == "2947fe0a303cc99f6074aecd8f6f39b741128c3644acb76c193be41394b05f07"


def test_real_rich_sources_emit_only_closed_metadata(tmp_path):
    project = tmp_path.resolve()
    (project / "empty-tree").mkdir()
    (project / "specs/žluť/nested/empty").mkdir(parents=True)
    (project / "specs/žluť/.hidden").write_bytes(b"\x00\xff")
    (project / "specs/žluť/crlf.md").write_bytes(b"FR-001\r\n")
    wide = b"\xff\xfeF\x00R\x00-\x000\x000\x001\x00\r\x00\n\x00"
    (project / "specs/žluť/legacy.bin").write_bytes(wide)
    (project / "empty").write_bytes(b"")
    (project / "empty").chmod(0o600)
    (project / "empty-tree").chmod(0o711)
    (project / "specs/žluť").chmod(0o750)
    (project / "specs/žluť/nested").chmod(0o710)
    (project / "specs/žluť/nested/empty").chmod(0o700)
    prepared = _prepared(project)

    manifest, _ = _capture_manifest(
        prepared,
        tree_paths=("specs/žluť", "missing/tree", "empty-tree"),
        file_paths=("empty", "missing-file"),
    )
    value = json.loads(manifest.payload)

    assert set(value) == {"version", "trees", "files"}
    assert value["version"] == "1"
    assert [(tree["path"], tree["exists"]) for tree in value["trees"]] == [
        ("empty-tree", "true"), ("missing/tree", "false"),
        ("specs/žluť", "true")
    ]
    assert value["trees"][0] == {
        "directories": [{"mode": "457", "path": "empty-tree"}],
        "exists": "true",
        "files": [],
        "path": "empty-tree",
    }
    present = value["trees"][2]
    assert present["directories"] == [
        {"mode": "488", "path": "specs/žluť"},
        {"mode": "456", "path": "specs/žluť/nested"},
        {"mode": "448", "path": "specs/žluť/nested/empty"},
    ]
    assert [(item["path"], item["image"]["sha256"]) for item in present["files"]] == [
        ("specs/žluť/.hidden", "06eb7d6a69ee19e5fbdf749018d3d2abfa04bcbd1365db312eb86dc7169389b8"),
        ("specs/žluť/crlf.md", "29cdfcd06dddf2d709da0cefe9d10fecb514fb1afb3e1d322e48d0f817aac1a5"),
        ("specs/žluť/legacy.bin", "e21838d9d3f5417908978957688dfdc330410e672c865e7c79155ffd62531c37"),
    ]
    assert value["files"] == [
        {
            "image": {
                "kind": "file",
                "mode": "384",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            },
            "path": "empty",
        },
        {
            "image": {"kind": "missing", "mode": None, "sha256": None},
            "path": "missing-file",
        },
    ]
    assert "ž" not in manifest.payload
    assert "\\u017e" in manifest.payload
    assert "content_base64" not in manifest.payload
    for leaked in ("FR-001", "AP8=", "//5GAE", wide.hex()):
        assert leaked not in manifest.payload

    def scalars(item):
        if type(item) is dict:
            return [scalar for child in item.values() for scalar in scalars(child)]
        if type(item) is list:
            return [scalar for child in item for scalar in scalars(child)]
        return [item]

    assert all(type(scalar) is str or scalar is None for scalar in scalars(value))


def test_repeated_real_captures_ignore_new_transaction_identity(tmp_path):
    project = tmp_path.resolve()
    (project / "source/nested").mkdir(parents=True)
    (project / "source/nested/input.md").write_bytes(b"unchanged\r\n")
    first = _prepared(project, "3" * 32, "first")
    second = _prepared(project, "4" * 32, "second")

    first_manifest, _ = _capture_manifest(first, tree_paths=("source",))
    second_manifest, _ = _capture_manifest(second, tree_paths=("source",))
    repeated_manifest, _ = _capture_manifest(first, tree_paths=("source",))

    assert first.marker.transaction_id != second.marker.transaction_id
    assert first_manifest == second_manifest == repeated_manifest


@pytest.mark.parametrize(
    "change",
    (
        "content",
        "file-mode",
        "directory-mode",
        "hidden-membership",
        "missing-file-appears",
        "empty-directory-appears",
        "selected-root",
        "selection-coverage",
    ),
)
def test_each_relevant_real_source_change_changes_fingerprint(tmp_path, change):
    project = tmp_path.resolve()
    (project / "source/nested").mkdir(parents=True)
    (project / "source/nested/input.md").write_bytes(b"same bytes")
    (project / "outside.md").write_bytes(b"same bytes")
    prepared = _prepared(project)
    baseline, _ = _capture_manifest(
        prepared, tree_paths=("source",), file_paths=("missing.md",)
    )

    tree_paths = ("source",)
    file_paths = ("missing.md",)
    if change == "content":
        (project / "source/nested/input.md").write_bytes(b"different bytes")
    elif change == "file-mode":
        (project / "source/nested/input.md").chmod(0o600)
    elif change == "directory-mode":
        (project / "source/nested").chmod(0o700)
    elif change == "hidden-membership":
        (project / "source/.hidden").write_bytes(b"hidden")
    elif change == "missing-file-appears":
        (project / "missing.md").write_bytes(b"")
    elif change == "empty-directory-appears":
        (project / "source/empty").mkdir()
    elif change == "selected-root":
        tree_paths = ("source/nested",)
    elif change == "selection-coverage":
        file_paths = ("missing.md", "outside.md")

    changed, _ = _capture_manifest(
        prepared, tree_paths=tree_paths, file_paths=file_paths
    )
    assert changed.payload != baseline.payload
    assert changed.sha256 != baseline.sha256


def test_unselected_change_is_outside_the_fingerprint(tmp_path):
    project = tmp_path.resolve()
    (project / "source").mkdir()
    (project / "source/input.md").write_bytes(b"selected")
    (project / "outside.md").write_bytes(b"before")
    prepared = _prepared(project)
    before, _ = _capture_manifest(prepared, tree_paths=("source",))
    (project / "outside.md").write_bytes(b"after")
    after, _ = _capture_manifest(prepared, tree_paths=("source",))
    assert before == after


def test_real_interrupted_publication_has_observational_manifests_and_stable_retry(tmp_path):
    from harness.squad_source_baseline_codec import encode_initial_publication_sources

    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    transaction = publication.SquadPublicationTransaction.begin(project, squad, "5" * 32)
    for name in ("a", "b"):
        (project / name).write_bytes(f"old-{name}".encode())
        stage = transaction.build_path(f"{name}.stage")
        stage.write_bytes(f"new-{name}".encode())
        target = Path(name)
        transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    initial, initial_sources = _capture_manifest(prepared, file_paths=("a", "b"))

    def interrupt(position):
        if position == 1:
            raise RuntimeError("synthetic interruption")

    with pytest.raises(publication.PublicationError, match="^publish_io$"):
        prepared.publish(fault_hook=interrupt)
    partial, partial_sources = _capture_manifest(prepared, file_paths=("a", "b"))
    with pytest.raises(publication.PublicationError, match="^manifest_invalid$"):
        encode_initial_publication_sources(partial_sources)

    prepared.publish()
    final, final_sources = _capture_manifest(prepared, file_paths=("a", "b"))
    with pytest.raises(publication.PublicationError, match="^manifest_invalid$"):
        encode_initial_publication_sources(final_sources)
    prepared.publish()
    retried, _ = _capture_manifest(prepared, file_paths=("a", "b"))

    assert len({initial.sha256, partial.sha256, final.sha256}) == 3
    assert retried == final
    assert [item.content for item in initial_sources.files] == [b"old-a", b"old-b"]
    assert _capture_fingerprint(initial_sources) == initial


def _capture_fingerprint(sources):
    from harness.squad_source_manifest import snapshot_source_manifest

    return snapshot_source_manifest(trees=sources.trees, files=sources.files)


def _synthetic_selection():
    tree = ProjectTreeSnapshot(
        "source",
        True,
        (
            ProjectDirectorySnapshot("source", 0o755),
            ProjectDirectorySnapshot("source/nested", 0o700),
        ),
        (ProjectFileSnapshot("source/nested/file", _file(b"data"), b"data"),),
    )
    selected_file = ProjectPathSnapshot("external", _file(b"external"), b"external")
    return (tree,), (selected_file,)


def _assert_invalid(*, trees, files):
    from harness.squad_source_manifest import snapshot_source_manifest

    with pytest.raises(publication.PublicationError, match="^manifest_invalid$"):
        snapshot_source_manifest(trees=trees, files=files)


def test_rejects_nonexact_containers_and_snapshot_dataclasses():
    class TupleSubclass(tuple):
        pass

    class TreeSubclass(ProjectTreeSnapshot):
        pass

    class PathSubclass(ProjectPathSnapshot):
        pass

    class DirectorySubclass(ProjectDirectorySnapshot):
        pass

    class TreeFileSubclass(ProjectFileSnapshot):
        pass

    class ImageSubclass(PublicationImageDescriptor):
        pass

    trees, files = _synthetic_selection()
    tree = trees[0]
    directory = tree.directories[0]
    tree_file = tree.files[0]
    cases = (
        (list(trees), files),
        (TupleSubclass(trees), files),
        (trees, list(files)),
        (trees, TupleSubclass(files)),
        ((TreeSubclass(tree.path, tree.exists, tree.directories, tree.files),), files),
        (trees, (PathSubclass(files[0].path, files[0].image, files[0].content),)),
        ((replace(tree, directories=(DirectorySubclass(directory.path, directory.mode), tree.directories[1])),), files),
        ((replace(tree, files=(TreeFileSubclass(tree_file.path, tree_file.image, tree_file.content),)),), files),
        ((replace(tree, files=(replace(tree_file, image=ImageSubclass("file", tree_file.image.sha256, tree_file.image.mode)),)),), files),
    )
    for malformed_trees, malformed_files in cases:
        _assert_invalid(trees=malformed_trees, files=malformed_files)


def test_rejects_damaged_paths_order_overlap_membership_and_bytes():
    trees, files = _synthetic_selection()
    tree = trees[0]
    root, nested = tree.directories
    tree_file = tree.files[0]
    missing_a = ProjectTreeSnapshot("a", False, (), ())
    missing_a_dash = ProjectTreeSnapshot("a-", False, (), ())
    missing_child = ProjectTreeSnapshot("a/b", False, (), ())
    malformed = (
        ((ProjectTreeSnapshot("../escape", False, (), ()),), ()),
        ((ProjectTreeSnapshot("bad\udcff", False, (), ()),), ()),
        ((ProjectTreeSnapshot("z", False, (), ()), missing_a), ()),
        ((missing_a, missing_a), ()),
        ((missing_a, missing_a_dash, missing_child), ()),
        ((missing_a,), (ProjectPathSnapshot("a/b", _missing(), None),)),
        (trees, (files[0], files[0])),
        ((replace(tree, exists=False),), files),
        ((replace(tree, directories=(nested, root)),), files),
        ((replace(tree, directories=(root,)),), files),
        ((replace(tree, files=(replace(tree_file, path="source/missing/file"),)),), files),
        ((replace(tree, files=(replace(tree_file, image=_file(b"other")),)),), files),
        ((replace(tree, files=(replace(tree_file, content=bytearray(b"data")),)),), files),
        (trees, (replace(files[0], image=_file(b"other")),)),
    )
    for malformed_trees, malformed_files in malformed:
        _assert_invalid(trees=malformed_trees, files=malformed_files)

    from harness.squad_source_manifest import snapshot_source_manifest

    prefix_siblings = snapshot_source_manifest(
        trees=(
            ProjectTreeSnapshot("spec/a", False, (), ()),
            ProjectTreeSnapshot("spec/ab", False, (), ()),
        ),
        files=(),
    )
    assert [tree["path"] for tree in json.loads(prefix_siblings.payload)["trees"]] == [
        "spec/a", "spec/ab"
    ]


def test_bounded_errors_suppress_structural_context_and_output_is_frozen_detached(monkeypatch):
    import harness.squad_source_manifest as source_manifest

    trees, files = _synthetic_selection()
    manifest = source_manifest.snapshot_source_manifest(trees=trees, files=files)
    assert type(manifest) is source_manifest.SourceManifestSnapshot
    assert not hasattr(manifest, "__dict__")
    assert (trees, files) == _synthetic_selection()
    with pytest.raises(FrozenInstanceError):
        manifest.payload = "changed"
    object.__setattr__(trees[0].files[0], "content", b"changed")
    assert manifest == source_manifest.SourceManifestSnapshot(
        manifest.payload, hashlib.sha256(manifest.payload.encode("ascii")).hexdigest()
    )
    object.__setattr__(trees[0].files[0], "content", b"data")
    assert (trees, files) == _synthetic_selection()

    damaged_trees, damaged_files = _synthetic_selection()
    object.__delattr__(damaged_trees[0], "directories")
    with pytest.raises(publication.PublicationError) as caught:
        source_manifest.snapshot_source_manifest(trees=damaged_trees, files=damaged_files)
    rendered = "".join(traceback.format_exception(caught.value))
    assert str(caught.value) == "manifest_invalid"
    assert caught.value.__suppress_context__ is True
    assert "directories" not in rendered

    def recursive_failure(*args, **kwargs):
        raise RecursionError("untrusted source content")

    monkeypatch.setattr(source_manifest, "_tree_value", recursive_failure)
    with pytest.raises(publication.PublicationError) as caught:
        source_manifest.snapshot_source_manifest(trees=_synthetic_selection()[0], files=())
    rendered = "".join(traceback.format_exception(caught.value))
    assert str(caught.value) == "manifest_invalid"
    assert caught.value.__suppress_context__ is True
    assert "untrusted source content" not in rendered


def test_unicode_validation_context_is_suppressed():
    from harness.squad_source_manifest import snapshot_source_manifest

    bad = (ProjectTreeSnapshot("secret\udcff", False, (), ()),)
    with pytest.raises(publication.PublicationError) as caught:
        snapshot_source_manifest(trees=bad, files=())
    rendered = "".join(traceback.format_exception(caught.value))
    assert str(caught.value) == "manifest_invalid"
    assert caught.value.__suppress_context__ is True
    assert "UnicodeEncodeError" not in rendered
    assert "secret" not in rendered


def test_factory_is_pure_after_real_capture(tmp_path, monkeypatch):
    project = tmp_path.resolve()
    (project / "source/empty").mkdir(parents=True)
    (project / "source/input").write_bytes(b"bytes")
    (project / "external").write_bytes(b"external")
    prepared = _prepared(project)
    with prepared.inspect_sources(
        tree_paths=("source",), file_paths=("external", "missing")
    ) as sources:
        pass

    def forbidden(*args, **kwargs):
        pytest.fail("source manifest accessed external state")

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
        first = _capture_fingerprint(sources)
        second = _capture_fingerprint(sources)
    assert first == second
