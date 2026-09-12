import hashlib
import json
import os
import socket
import sqlite3
import time
import builtins
import secrets
from dataclasses import replace
from pathlib import Path

import pytest

import harness.squad_publication as publication
from harness.squad_publication import SquadPublicationTransaction
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


@pytest.fixture(autouse=True)
def secure_posix():
    if not publication._secure_posix_capabilities_available():
        pytest.skip("descriptor-safe POSIX publication is unavailable")


def real_prepared_write_fixture(tmp_path):
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs/demo").mkdir(parents=True)
    (project / "specs/demo/spec.md").write_bytes(b"Original\r\n")
    (project / "specs/demo/.hidden").write_bytes(b"\x00\xff")
    (project / "constitution.md").write_bytes(b"")
    transaction = SquadPublicationTransaction.begin(project, squad, "1" * 32)
    stage = transaction.build_path("after.md")
    stage.write_bytes(b"Revised\r\n")
    target = Path("specs/demo/spec.md")
    transaction.add_write(target, stage, owned_paths={target})
    return transaction.seal()


def test_initial_source_baseline_round_trip_preserves_original_bytes(tmp_path):
    prepared = real_prepared_write_fixture(tmp_path)
    with prepared.inspect_sources(
        tree_paths=("specs/demo",), file_paths=("constitution.md",)
    ) as observed:
        from harness.squad_source_baseline_codec import (
            decode_initial_publication_sources,
            encode_initial_publication_sources,
        )

        payload = encode_initial_publication_sources(observed)
        restored = decode_initial_publication_sources(payload)
        assert restored == observed
        assert restored.publication.operations[0].current_bytes == b"Original\r\n"
        assert restored.publication.operations[0].postimage_bytes == b"Revised\r\n"
        assert restored.trees[0].files[0].content == b"\x00\xff"
        assert restored.files[0].content == b""


def _missing():
    return PublicationImageDescriptor("missing", None, None)


def _file(content, mode=0o644):
    return PublicationImageDescriptor("file", hashlib.sha256(content).hexdigest(), mode)


def _operation(action, target, before, after, before_mode=0o644, after_mode=0o644):
    preimage = _missing() if before is None else _file(before, before_mode)
    postimage = _missing() if after is None else _file(after, after_mode)
    return PublicationOperationSnapshot(
        action, target, preimage, postimage, preimage, before, after
    )


def _wire_snapshot():
    publication_snapshot = PublicationSnapshot(
        publication.PublicationMarker(1, "2" * 32, "3" * 64),
        0,
        (
            _operation("delete", "gone", b"gone", None, before_mode=0o640),
            _operation("write", "new", None, b"new", after_mode=0o600),
        ),
    )
    tree = ProjectTreeSnapshot(
        "source",
        True,
        (
            ProjectDirectorySnapshot("source", 0o755),
            ProjectDirectorySnapshot("source/nested", 0o700),
        ),
        (
            ProjectFileSnapshot("source/.hidden", _file(b"\x00\xff", 0o604), b"\x00\xff"),
        ),
    )
    external = ProjectPathSnapshot("constitution.md", _file(b"", 0o600), b"")
    return PublicationSourcesSnapshot(publication_snapshot, (tree,), (external,))


EXPECTED_WIRE = (
    '{"files":[{"image":{"content_base64":"","kind":"file","mode":"384",'
    '"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},'
    '"path":"constitution.md"}],"publication":{"marker":{"manifest_sha256":"'
    + "3" * 64
    + '","schema_version":"1","transaction_id":"'
    + "2" * 32
    + '"},"operations":[{"action":"delete","postimage":{"content_base64":null,'
    '"kind":"missing","mode":null,"sha256":null},"preimage":{"content_base64":"Z29uZQ==",'
    '"kind":"file","mode":"416","sha256":"283bb9deef02e6843abfb538efa1eca70801bd8a701c3f98191e123496339247"},'
    '"target":"gone"},{"action":"write","postimage":{"content_base64":"bmV3",'
    '"kind":"file","mode":"384","sha256":"11507a0e2f5e69d5dfa40a62a1bd7b6ee57e6bcd85c67c9b8431b36fff21c437"},'
    '"preimage":{"content_base64":null,"kind":"missing","mode":null,"sha256":null},'
    '"target":"new"}]},"trees":[{"directories":[{"mode":"493","path":"source"},'
    '{"mode":"448","path":"source/nested"}],"exists":"true","files":['
    '{"image":{"content_base64":"AP8=","kind":"file","mode":"388",'
    '"sha256":"06eb7d6a69ee19e5fbdf749018d3d2abfa04bcbd1365db312eb86dc7169389b8"},'
    '"path":"source/.hidden"}],"path":"source"}],"version":"1"}'
)


def test_exact_v1_wire_shape_is_canonical_and_independently_literal():
    from harness.squad_source_baseline_codec import encode_initial_publication_sources

    assert encode_initial_publication_sources(_wire_snapshot()) == EXPECTED_WIRE


def test_decode_returns_only_exact_immutable_sequences_and_bytes():
    from harness.squad_source_baseline_codec import (
        decode_initial_publication_sources,
        encode_initial_publication_sources,
    )

    first = encode_initial_publication_sources(_wire_snapshot())
    restored = decode_initial_publication_sources(EXPECTED_WIRE)
    assert encode_initial_publication_sources(restored) == EXPECTED_WIRE == first
    assert type(restored.publication.operations) is tuple
    assert type(restored.trees) is type(restored.files) is tuple
    assert type(restored.trees[0].directories) is type(restored.trees[0].files) is tuple
    assert type(restored.trees[0].files[0].content) is bytes


def test_empty_operations_missing_and_empty_sources_are_valid():
    from harness.squad_source_baseline_codec import (
        decode_initial_publication_sources,
        encode_initial_publication_sources,
    )

    snapshot = PublicationSourcesSnapshot(
        PublicationSnapshot(publication.PublicationMarker(1, "4" * 32, "5" * 64), 0, ()),
        (
            ProjectTreeSnapshot("empty", True, (ProjectDirectorySnapshot("empty", 0o711),), ()),
            ProjectTreeSnapshot("missing/tree", False, (), ()),
        ),
        (
            ProjectPathSnapshot("empty.file", _file(b"", 0), b""),
            ProjectPathSnapshot("missing.file", _missing(), None),
        ),
    )
    assert decode_initial_publication_sources(encode_initial_publication_sources(snapshot)) == snapshot


def test_unicode_crlf_binary_noop_outside_selection_and_prefix_siblings_round_trip():
    from harness.squad_source_baseline_codec import (
        decode_initial_publication_sources,
        encode_initial_publication_sources,
    )

    old = "Příliš\r\n".encode()
    same = b"same"
    snapshot = PublicationSourcesSnapshot(
        PublicationSnapshot(
            publication.PublicationMarker(1, "6" * 32, "7" * 64),
            0,
            (
                _operation("write", "outside", b"outside", b"later"),
                _operation("delete", "spec", None, None),
                _operation("delete", "specs", None, None),
                _operation("write", "src/docs/readme.md", old, b"new\r\n"),
                _operation("write", "unchanged", same, same),
            ),
        ),
        (
            ProjectTreeSnapshot(
                "src",
                True,
                (
                    ProjectDirectorySnapshot("src", 0o751),
                    ProjectDirectorySnapshot("src/docs", 0o705),
                    ProjectDirectorySnapshot("src/docs/empty", 0o711),
                ),
                (
                    ProjectFileSnapshot("src/.hidden", _file(b"\x00\xff", 0o604), b"\x00\xff"),
                    ProjectFileSnapshot("src/docs/readme.md", _file(old, 0o644), old),
                    ProjectFileSnapshot("src/docs/žluťoučký", _file("Unicode".encode()), "Unicode".encode()),
                ),
            ),
        ),
        (),
    )
    payload = encode_initial_publication_sources(snapshot)
    assert decode_initial_publication_sources(payload) == snapshot


def test_prefix_zero_does_not_accept_current_postimage_but_exact_noop_does():
    from harness.squad_source_baseline_codec import encode_initial_publication_sources

    snapshot = _wire_snapshot()
    first = snapshot.publication.operations[0]
    synthetic = replace(
        snapshot,
        publication=replace(
            snapshot.publication,
            operations=(
                replace(first, current=first.postimage, current_bytes=first.postimage_bytes),
                snapshot.publication.operations[1],
            ),
        ),
    )
    with pytest.raises(publication.PublicationError, match="^manifest_invalid$"):
        encode_initial_publication_sources(synthetic)

    no_op = _operation("write", "same", b"same", b"same")
    control = PublicationSourcesSnapshot(
        PublicationSnapshot(publication.PublicationMarker(1, "8" * 32, "9" * 64), 0, (no_op,)),
        (),
        (),
    )
    encode_initial_publication_sources(control)


def _assert_encode_invalid(snapshot):
    from harness.squad_source_baseline_codec import encode_initial_publication_sources

    with pytest.raises(publication.PublicationError, match="^manifest_invalid$"):
        encode_initial_publication_sources(snapshot)


def test_encode_rejects_wrong_exact_types_and_deleted_frozen_attributes():
    class SourcesSubclass(PublicationSourcesSnapshot):
        pass

    class PublicationSubclass(PublicationSnapshot):
        pass

    class MarkerSubclass(publication.PublicationMarker):
        pass

    class OperationSubclass(PublicationOperationSnapshot):
        pass

    class ImageSubclass(PublicationImageDescriptor):
        pass

    class TreeSubclass(ProjectTreeSnapshot):
        pass

    class DirectorySubclass(ProjectDirectorySnapshot):
        pass

    class TreeFileSubclass(ProjectFileSnapshot):
        pass

    class PathSubclass(ProjectPathSnapshot):
        pass

    snapshot = _wire_snapshot()
    sealed = snapshot.publication
    operation = sealed.operations[0]
    tree = snapshot.trees[0]
    directory = tree.directories[0]
    tree_file = tree.files[0]
    external = snapshot.files[0]
    cases = [
        SourcesSubclass(snapshot.publication, snapshot.trees, snapshot.files),
        replace(snapshot, publication=PublicationSubclass(sealed.marker, 0, sealed.operations)),
        replace(snapshot, publication=replace(
            sealed, marker=MarkerSubclass(1, "2" * 32, "3" * 64)
        )),
        replace(snapshot, publication=replace(
            sealed, operations=(OperationSubclass(
                operation.action, operation.target, operation.preimage, operation.postimage,
                operation.current, operation.current_bytes, operation.postimage_bytes,
            ), sealed.operations[1])
        )),
        replace(snapshot, publication=replace(
            sealed, operations=(replace(
                operation,
                preimage=ImageSubclass(
                    operation.preimage.kind, operation.preimage.sha256, operation.preimage.mode
                ),
            ), sealed.operations[1])
        )),
        replace(snapshot, trees=(TreeSubclass(
            tree.path, tree.exists, tree.directories, tree.files
        ),)),
        replace(snapshot, trees=(replace(
            tree, directories=(DirectorySubclass(directory.path, directory.mode), tree.directories[1])
        ),)),
        replace(snapshot, trees=(replace(
            tree, files=(TreeFileSubclass(tree_file.path, tree_file.image, tree_file.content),)
        ),)),
        replace(snapshot, files=(PathSubclass(external.path, external.image, external.content),)),
        replace(snapshot, publication=replace(sealed, operations=list(sealed.operations))),
        replace(snapshot, trees=list(snapshot.trees)),
        replace(snapshot, files=list(snapshot.files)),
        replace(snapshot, trees=(replace(tree, directories=list(tree.directories)),)),
        replace(snapshot, trees=(replace(tree, files=list(tree.files)),)),
    ]
    for case in cases:
        _assert_encode_invalid(case)

    missing_attribute = _wire_snapshot()
    object.__delattr__(missing_attribute, "files")
    _assert_encode_invalid(missing_attribute)


@pytest.mark.parametrize("prefix", [True, -1, 1])
def test_encode_rejects_nonzero_or_nonexact_initial_prefix(prefix):
    snapshot = _wire_snapshot()
    _assert_encode_invalid(replace(snapshot, publication=replace(snapshot.publication, promoted_prefix=prefix)))


def test_encode_rejects_bad_image_content_action_marker_and_unicode():
    snapshot = _wire_snapshot()
    sealed = snapshot.publication
    operation = sealed.operations[0]
    bad_images = (
        PublicationImageDescriptor("missing", "0" * 64, None),
        PublicationImageDescriptor("file", "0" * 64, 0o644),
        PublicationImageDescriptor("file", operation.preimage.sha256, True),
        PublicationImageDescriptor("file", operation.preimage.sha256, 0o10000),
        PublicationImageDescriptor("directory", None, None),
    )
    for image in bad_images:
        _assert_encode_invalid(replace(
            snapshot,
            publication=replace(
                sealed, operations=(replace(operation, preimage=image, current=image), sealed.operations[1])
            ),
        ))
    _assert_encode_invalid(replace(
        snapshot,
        publication=replace(
            sealed, operations=(replace(operation, current_bytes=bytearray(b"gone")), sealed.operations[1])
        ),
    ))
    _assert_encode_invalid(replace(
        snapshot,
        publication=replace(
            sealed, operations=(replace(operation, action="write"), sealed.operations[1])
        ),
    ))
    _assert_encode_invalid(replace(
        snapshot,
        publication=replace(
            sealed, operations=(operation, replace(sealed.operations[1], action="delete"))
        ),
    ))
    for marker in (
        publication.PublicationMarker(True, "2" * 32, "3" * 64),
        publication.PublicationMarker(2, "2" * 32, "3" * 64),
        publication.PublicationMarker(1, "x", "3" * 64),
        publication.PublicationMarker(1, "2" * 32, "A" * 64),
    ):
        _assert_encode_invalid(replace(snapshot, publication=replace(sealed, marker=marker)))
    _assert_encode_invalid(replace(
        snapshot,
        publication=replace(
            sealed, operations=(replace(operation, target="bad\udcff"), sealed.operations[1])
        ),
    ))


def test_encode_rejects_unsorted_duplicate_and_overlapping_operation_targets():
    snapshot = _wire_snapshot()
    first, second = snapshot.publication.operations
    operation_sets = (
        (second, first),
        (first, replace(second, target=first.target)),
        (replace(first, target="a"), replace(second, target="a/b")),
        (replace(first, target="../escape"), second),
    )
    for operations in operation_sets:
        _assert_encode_invalid(replace(
            snapshot, publication=replace(snapshot.publication, operations=operations)
        ))


def test_encode_rejects_malformed_tree_membership_and_source_selection():
    snapshot = _wire_snapshot()
    tree = snapshot.trees[0]
    root, nested = tree.directories
    hidden = tree.files[0]
    malformed_trees = (
        replace(tree, exists=False),
        replace(tree, directories=()),
        replace(tree, directories=(nested, root)),
        replace(tree, directories=(root, root)),
        replace(tree, directories=(root, ProjectDirectorySnapshot("source/deep/leaf", 0o700))),
        replace(tree, directories=(root, ProjectDirectorySnapshot("other", 0o700))),
        replace(tree, files=(replace(hidden, path="source/nested/missing/file"),)),
        replace(tree, files=(replace(hidden, path="source"),)),
        replace(tree, directories=(root, ProjectDirectorySnapshot("source/.hidden", 0o700), nested)),
        replace(tree, files=(replace(hidden, path="source/.hidden/child"),)),
        replace(tree, files=(replace(hidden, image=_missing(), content=None),)),
    )
    for malformed in malformed_trees:
        _assert_encode_invalid(replace(snapshot, trees=(malformed,)))

    missing_tree = ProjectTreeSnapshot("missing", False, (), ())
    _assert_encode_invalid(replace(snapshot, trees=(tree, missing_tree)))
    _assert_encode_invalid(replace(snapshot, trees=(tree, replace(tree, path="source/nested"))))
    _assert_encode_invalid(replace(snapshot, files=(snapshot.files[0], snapshot.files[0])))
    _assert_encode_invalid(replace(snapshot, files=(replace(snapshot.files[0], path="source/other"),)))


def test_operation_and_selected_source_consistency_is_fail_closed():
    base = PublicationSourcesSnapshot(
        PublicationSnapshot(
            publication.PublicationMarker(1, "a" * 32, "b" * 64),
            0,
            (_operation("write", "tree/file", b"old", b"new"),),
        ),
        (
            ProjectTreeSnapshot(
                "tree", True, (ProjectDirectorySnapshot("tree", 0o755),),
                (ProjectFileSnapshot("tree/file", _file(b"old"), b"old"),),
            ),
        ),
        (),
    )
    from harness.squad_source_baseline_codec import encode_initial_publication_sources

    encode_initial_publication_sources(base)
    operation = base.publication.operations[0]
    for malformed in (
        replace(base, publication=replace(
            base.publication,
            operations=(replace(
                operation, preimage=_file(b"other"), current=_file(b"other"), current_bytes=b"other"
            ),),
        )),
        replace(base, publication=replace(
            base.publication, operations=(_operation("write", "tree/absent", b"invented", b"new"),)
        )),
        replace(base, publication=replace(
            base.publication, operations=(_operation("write", "tree", None, b"new"),)
        )),
        replace(base, publication=replace(
            base.publication, operations=(_operation("write", "tree/file/child", None, b"new"),)
        )),
    ):
        _assert_encode_invalid(malformed)

    missing_tree = PublicationSourcesSnapshot(
        PublicationSnapshot(
            publication.PublicationMarker(1, "c" * 32, "d" * 64), 0,
            (_operation("write", "missing/child", b"invented", b"new"),),
        ),
        (ProjectTreeSnapshot("missing", False, (), ()),),
        (),
    )
    _assert_encode_invalid(missing_tree)

    missing_selected_child = PublicationSourcesSnapshot(
        PublicationSnapshot(
            publication.PublicationMarker(1, "e" * 32, "f" * 64), 0,
            (_operation("write", "parent", b"old", b"new"),),
        ),
        (),
        (ProjectPathSnapshot("parent/absent", _missing(), None),),
    )
    encode_initial_publication_sources(missing_selected_child)


def _canonical_wire(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _assert_decode_invalid(payload):
    from harness.squad_source_baseline_codec import decode_initial_publication_sources

    with pytest.raises(publication.PublicationError, match="^manifest_invalid$"):
        decode_initial_publication_sources(payload)


def test_decode_rejects_closed_shape_marker_and_scalar_violations():
    mutations = []
    value = json.loads(EXPECTED_WIRE)
    bad = json.loads(EXPECTED_WIRE); bad["extra"] = None; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); del bad["files"]; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["version"] = None; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["version"] = "2"; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["publication"]["extra"] = None; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["publication"]["operations"] = None; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["publication"]["marker"]["schema_version"] = "2"; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["publication"]["marker"]["transaction_id"] = "x"; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["publication"]["marker"]["manifest_sha256"] = "A" * 64; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); del bad["publication"]["operations"][0]["target"]; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["publication"]["operations"][0]["extra"] = None; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["publication"]["operations"][0]["action"] = True; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["trees"][0]["exists"] = True; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["trees"][0]["directories"][0]["mode"] = None; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["files"][0]["image"]["kind"] = None; mutations.append(bad)
    for mutated in mutations:
        _assert_decode_invalid(_canonical_wire(mutated))

    _assert_decode_invalid(_canonical_wire(value).replace('"version":"1"', '"version":1'))


@pytest.mark.parametrize("mode", ["", "00", "0644", "+1", "-1", "1.0", "４", "4096", "9" * 10000])
def test_decode_rejects_noncanonical_or_out_of_range_modes(mode):
    value = json.loads(EXPECTED_WIRE)
    value["trees"][0]["directories"][0]["mode"] = mode
    _assert_decode_invalid(_canonical_wire(value))


@pytest.mark.parametrize("encoded", ["A", "====", "AP8", "AP8==", "AP8=\n", "\u00ff"])
def test_decode_rejects_invalid_or_noncanonical_base64(encoded):
    value = json.loads(EXPECTED_WIRE)
    value["trees"][0]["files"][0]["image"]["content_base64"] = encoded
    _assert_decode_invalid(_canonical_wire(value))


def test_decode_rejects_hash_content_image_and_action_mismatches():
    mutations = []
    bad = json.loads(EXPECTED_WIRE); bad["trees"][0]["files"][0]["image"]["sha256"] = "0" * 64; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["files"][0]["image"]["sha256"] = None; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["files"][0]["image"]["mode"] = None; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["publication"]["operations"][0]["postimage"]["kind"] = "file"; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["publication"]["operations"][1]["postimage"] = {
        "kind": "missing", "sha256": None, "mode": None, "content_base64": None,
    }; mutations.append(bad)
    bad = json.loads(EXPECTED_WIRE); bad["trees"][0]["files"][0]["image"] = {
        "kind": "missing", "sha256": None, "mode": None, "content_base64": None,
    }; mutations.append(bad)
    for mutated in mutations:
        _assert_decode_invalid(_canonical_wire(mutated))


def test_decode_rejects_malformed_deep_duplicate_and_noncanonical_json():
    _assert_decode_invalid("")
    _assert_decode_invalid("{\"version\":\"1\",\"version\":\"1\"}")
    _assert_decode_invalid("[" * 2000 + "]" * 2000)
    _assert_decode_invalid("\udcff")
    _assert_decode_invalid(" " + EXPECTED_WIRE)
    _assert_decode_invalid(EXPECTED_WIRE.replace('"version":"1"', '"version":"\\u0031"'))


def test_self_consistent_altered_wire_decodes_but_is_not_authentication():
    from harness.squad_source_baseline_codec import decode_initial_publication_sources

    value = json.loads(EXPECTED_WIRE)
    postimage = value["publication"]["operations"][1]["postimage"]
    postimage["content_base64"] = "bGF0ZXI="
    postimage["sha256"] = "1d9283d848ea941ace1fe0d2378ef8b70056a0d4d1648b95a322d90163e78285"
    altered = decode_initial_publication_sources(_canonical_wire(value))
    assert altered.publication.operations[1].postimage_bytes == b"later"
    assert altered.publication.marker.manifest_sha256 == "3" * 64


def test_real_partial_publication_rejects_fresh_encoding_but_retained_bytes_survive(tmp_path):
    from harness.squad_source_baseline_codec import (
        decode_initial_publication_sources,
        encode_initial_publication_sources,
    )

    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(project, squad, "b" * 32)
    expected_before = {}
    for name, before, after in (("a", b"old-a", b"new-a"), ("b", b"old-b", b"new-b")):
        (project / name).write_bytes(before)
        stage = transaction.build_path(f"{name}.stage")
        stage.write_bytes(after)
        target = Path(name)
        transaction.add_write(target, stage, owned_paths={target})
        expected_before[name] = before
    prepared = transaction.seal()

    with prepared.inspect_sources(file_paths=("a", "b")) as initial:
        retained_payload = encode_initial_publication_sources(initial)

    def interrupt(position):
        if position == 1:
            raise RuntimeError("synthetic interruption")

    with pytest.raises(publication.PublicationError, match="^publish_io$"):
        prepared.publish(fault_hook=interrupt)
    with prepared.inspect_sources(file_paths=("a", "b")) as partial:
        assert partial.publication.promoted_prefix == 1
        _assert_encode_invalid(partial)

    retained_after_partial = decode_initial_publication_sources(retained_payload)
    assert {
        operation.target: operation.current_bytes
        for operation in retained_after_partial.publication.operations
    } == expected_before
    prepared.publish()
    assert (project / "a").read_bytes() == b"new-a"
    assert (project / "b").read_bytes() == b"new-b"
    retained_after_completion = decode_initial_publication_sources(retained_payload)
    assert {
        operation.target: operation.current_bytes
        for operation in retained_after_completion.publication.operations
    } == expected_before


def test_codec_is_pure_after_real_capture_and_does_not_access_external_state(tmp_path, monkeypatch):
    from harness.squad_source_baseline_codec import (
        decode_initial_publication_sources,
        encode_initial_publication_sources,
    )

    prepared = real_prepared_write_fixture(tmp_path)
    with prepared.inspect_sources(
        tree_paths=("specs/demo",), file_paths=("constitution.md",)
    ) as observed:
        pass
    project = tmp_path.resolve()

    def inventory():
        return {
            path.relative_to(project).as_posix(): (
                path.read_bytes() if path.is_file() else None,
                path.stat().st_mode,
            )
            for path in project.rglob("*")
        }

    before = inventory()

    def forbidden(*args, **kwargs):
        pytest.fail("codec accessed external state")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(os, "open", forbidden)
        patch.setattr(os, "listdir", forbidden)
        patch.setattr(os, "stat", forbidden)
        patch.setattr(os, "lstat", forbidden)
        patch.setattr(sqlite3, "connect", forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(time, "time", forbidden)
        patch.setattr(secrets, "token_bytes", forbidden)
        first = encode_initial_publication_sources(observed)
        second = encode_initial_publication_sources(observed)
        restored = decode_initial_publication_sources(first)
    assert first == second
    assert restored == observed
    assert inventory() == before
