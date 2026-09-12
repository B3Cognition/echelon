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
from pathlib import Path

import pytest

import harness.squad_publication as publication


pytestmark = pytest.mark.unit


VALID_WIRE = (
    '{"files":[{"image":{"kind":"missing","mode":null,"sha256":null},'
    '"path":"absent"}],"trees":[{"directories":[{"mode":"488","path":"specs"}],'
    '"exists":"true","files":[{"image":{"kind":"file","mode":"416",'
    '"sha256":"2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"},'
    '"path":"specs/notes.md"}],"path":"specs"}],"version":"1"}'
)
VALID_DIGEST = "f3bad6a7c97ec0fcfbb8546e53a8621847c34a712c44f449a73fecc172a504a5"
EMPTY_WIRE = '{"files":[],"trees":[],"version":"1"}'
EMPTY_DIGEST = "2947fe0a303cc99f6074aecd8f6f39b741128c3644acb76c193be41394b05f07"


@pytest.fixture
def secure_posix():
    if not publication._secure_posix_capabilities_available():
        pytest.skip("descriptor-safe POSIX publication is unavailable")


def test_real_manifest_round_trip_preserves_exact_existing_wire(tmp_path, secure_posix):
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs").mkdir()
    (project / "specs/notes.md").write_bytes(b"FR-1000000\r\n\x00\xff")
    prepared = SquadPublicationTransaction.begin(project, squad, "4" * 32).seal()
    with prepared.inspect_sources(tree_paths=("specs",), file_paths=("absent",)) as sources:
        assert sources.trees[0].files[0].content == b"FR-1000000\r\n\x00\xff"
    observed = snapshot_source_manifest(trees=sources.trees, files=sources.files)
    from harness.squad_source_manifest_codec import decode_source_manifest, validate_source_manifest
    assert decode_source_manifest(observed.payload) == observed
    assert validate_source_manifest(observed) == observed


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _assert_invalid(payload):
    from harness.squad_source_manifest_codec import decode_source_manifest

    with pytest.raises(publication.PublicationError, match="^manifest_invalid$"):
        decode_source_manifest(payload)


def test_complete_literal_payload_and_empty_selection_have_literal_digests():
    from harness.squad_source_manifest import SourceManifestSnapshot
    from harness.squad_source_manifest_codec import decode_source_manifest

    assert decode_source_manifest(VALID_WIRE) == SourceManifestSnapshot(
        VALID_WIRE, VALID_DIGEST
    )
    assert decode_source_manifest(EMPTY_WIRE) == SourceManifestSnapshot(
        EMPTY_WIRE, EMPTY_DIGEST
    )


def test_canonical_non_ascii_paths_and_component_prefix_siblings_are_valid():
    from harness.squad_source_manifest_codec import decode_source_manifest

    value = {
        "version": "1",
        "trees": [
            {
                "path": "a-",
                "exists": "true",
                "directories": [{"path": "a-", "mode": "493"}],
                "files": [],
            }
        ],
        "files": [
            {
                "path": "a/b/žluť",
                "image": {"kind": "missing", "sha256": None, "mode": None},
            }
        ],
    }
    payload = _canonical(value)
    decoded = decode_source_manifest(payload)
    assert decoded.payload == payload
    assert "ž" not in payload
    assert "\\u017e" in payload


def test_rich_actual_capture_round_trip_preserves_metadata_scope(tmp_path, secure_posix):
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    from harness.squad_source_manifest_codec import (
        decode_source_manifest,
        validate_source_manifest,
    )

    project = tmp_path.resolve()
    (project / "source/žluť/empty").mkdir(parents=True)
    (project / "source/žluť/.hidden").write_bytes(b"\x00\xff")
    (project / "source/žluť/wide-id.md").write_bytes(
        b"FR-1000000\r\n\x00\xff"
    )
    (project / "source/žluť").chmod(0o750)
    (project / "source/žluť/empty").chmod(0o700)
    squad = project / "runs/spec-rich"
    squad.mkdir(parents=True)
    prepared = SquadPublicationTransaction.begin(project, squad, "5" * 32).seal()
    with prepared.inspect_sources(
        tree_paths=("source/žluť", "missing/tree"), file_paths=("absent",)
    ) as sources:
        pass
    observed = snapshot_source_manifest(trees=sources.trees, files=sources.files)
    decoded = decode_source_manifest(observed.payload)
    value = json.loads(decoded.payload)

    assert validate_source_manifest(observed) == decoded == observed
    assert [(tree["path"], tree["exists"]) for tree in value["trees"]] == [
        ("missing/tree", "false"),
        ("source/žluť", "true"),
    ]
    assert value["trees"][1]["directories"] == [
        {"mode": "488", "path": "source/žluť"},
        {"mode": "448", "path": "source/žluť/empty"},
    ]
    assert [
        (item["path"], item["image"]["sha256"])
        for item in value["trees"][1]["files"]
    ] == [
        (
            "source/žluť/.hidden",
            "06eb7d6a69ee19e5fbdf749018d3d2abfa04bcbd1365db312eb86dc7169389b8",
        ),
        (
            "source/žluť/wide-id.md",
            "a285f8d65c5392b5ae53ccb88cb9343c7e4bcc737bf5460f63b7eeef29d418bd",
        ),
    ]
    assert value["files"] == [
        {
            "image": {"kind": "missing", "mode": None, "sha256": None},
            "path": "absent",
        }
    ]
    assert "content_base64" not in decoded.payload
    assert "FR-1000000" not in decoded.payload


def _closed_shape_mutation(case):
    value = json.loads(VALID_WIRE)
    tree = value["trees"][0]
    directory = tree["directories"][0]
    tree_file = tree["files"][0]
    image = tree_file["image"]
    selected = value["files"][0]
    selected_image = selected["image"]
    if case == "root-extra":
        value["extra"] = None
    elif case == "root-missing":
        del value["files"]
    elif case == "version-alternate":
        value["version"] = "2"
    elif case == "version-boolean":
        value["version"] = True
    elif case == "trees-not-array":
        value["trees"] = {}
    elif case == "files-not-array":
        value["files"] = {}
    elif case == "tree-extra":
        tree["source"] = "specs"
    elif case == "tree-missing":
        del tree["path"]
    elif case == "exists-boolean":
        tree["exists"] = True
    elif case == "exists-alternate":
        tree["exists"] = "1"
    elif case == "directories-not-array":
        tree["directories"] = {}
    elif case == "tree-files-not-array":
        tree["files"] = {}
    elif case == "directory-extra":
        directory["extra"] = None
    elif case == "directory-missing":
        del directory["mode"]
    elif case == "directory-mode-number":
        directory["mode"] = 488
    elif case == "directory-path-boolean":
        directory["path"] = False
    elif case == "file-extra":
        tree_file["source"] = "notes"
    elif case == "file-missing":
        del tree_file["image"]
    elif case == "image-extra":
        image["content_base64"] = ""
    elif case == "image-missing":
        del image["mode"]
    elif case == "kind-boolean":
        image["kind"] = True
    elif case == "file-mode-null":
        image["mode"] = None
    elif case == "file-sha-null":
        image["sha256"] = None
    elif case == "kind-alternate":
        image["kind"] = "directory"
    elif case == "missing-has-sha":
        selected_image["sha256"] = "0" * 64
    elif case == "missing-has-mode":
        selected_image["mode"] = "0"
    elif case == "selected-extra":
        selected["source"] = "alias"
    else:  # pragma: no cover - protects this test helper from silent omissions
        raise AssertionError(case)
    return _canonical(value)


@pytest.mark.parametrize(
    "case",
    (
        "root-extra",
        "root-missing",
        "version-alternate",
        "version-boolean",
        "trees-not-array",
        "files-not-array",
        "tree-extra",
        "tree-missing",
        "exists-boolean",
        "exists-alternate",
        "directories-not-array",
        "tree-files-not-array",
        "directory-extra",
        "directory-missing",
        "directory-mode-number",
        "directory-path-boolean",
        "file-extra",
        "file-missing",
        "image-extra",
        "image-missing",
        "kind-boolean",
        "file-mode-null",
        "file-sha-null",
        "kind-alternate",
        "missing-has-sha",
        "missing-has-mode",
        "selected-extra",
    ),
)
def test_decode_rejects_nonclosed_shapes_and_coerced_scalars(case):
    _assert_invalid(_closed_shape_mutation(case))


@pytest.mark.parametrize(
    "mode", ("", "00", "0644", "+1", "-1", "1.0", "４", "4096", "9" * 10000)
)
def test_decode_rejects_noncanonical_or_out_of_range_modes(mode):
    value = json.loads(VALID_WIRE)
    value["trees"][0]["directories"][0]["mode"] = mode
    _assert_invalid(_canonical(value))


@pytest.mark.parametrize("sha256", ("0" * 63, "A" * 64, "g" * 64, "0x" + "0" * 64))
def test_decode_rejects_noncanonical_sha256(sha256):
    value = json.loads(VALID_WIRE)
    value["trees"][0]["files"][0]["image"]["sha256"] = sha256
    _assert_invalid(_canonical(value))


@pytest.mark.parametrize(
    "path", ("", ".", "../escape", "a/../b", "/absolute", "a//b", "a\\b", "bad\udcff")
)
def test_decode_rejects_noncanonical_or_non_utf8_paths(path):
    value = json.loads(VALID_WIRE)
    value["files"][0]["path"] = path
    _assert_invalid(_canonical(value))


def _layout_mutation(case):
    value = json.loads(VALID_WIRE)
    tree = value["trees"][0]
    root = {"mode": "488", "path": "specs"}
    nested = {"mode": "448", "path": "specs/nested"}
    file_value = tree["files"][0]
    if case == "directories-unsorted":
        tree["directories"] = [nested, root]
    elif case == "directories-duplicate":
        tree["directories"] = [root, root]
    elif case == "files-unsorted":
        first = json.loads(json.dumps(file_value)); first["path"] = "specs/z"
        second = json.loads(json.dumps(file_value)); second["path"] = "specs/a"
        tree["files"] = [first, second]
    elif case == "files-duplicate":
        tree["files"] = [file_value, file_value]
    elif case == "absent-has-directories":
        tree["exists"] = "false"
        tree["files"] = []
    elif case == "absent-has-files":
        tree["exists"] = "false"
        tree["directories"] = []
    elif case == "present-root-missing":
        tree["directories"] = []
        tree["files"] = []
    elif case == "present-root-duplicate":
        tree["directories"] = [root, root]
    elif case == "directory-outside-root":
        tree["directories"] = [{"mode": "448", "path": "other"}, root]
    elif case == "directory-parent-missing":
        tree["directories"] = [root, {"mode": "448", "path": "specs/a/b"}]
    elif case == "file-outside-root":
        tree["files"][0]["path"] = "other/file"
    elif case == "file-parent-missing":
        tree["files"][0]["path"] = "specs/a/file"
    elif case == "file-directory-collision":
        tree["files"][0]["path"] = "specs"
    elif case == "regular-file-ancestor":
        child = json.loads(json.dumps(file_value)); child["path"] = "specs/node/child"
        tree["files"][0]["path"] = "specs/node"
        tree["files"].append(child)
    elif case == "tree-file-missing-image":
        tree["files"][0]["image"] = {
            "kind": "missing", "sha256": None, "mode": None,
        }
    else:  # pragma: no cover
        raise AssertionError(case)
    return _canonical(value)


@pytest.mark.parametrize(
    "case",
    (
        "directories-unsorted",
        "directories-duplicate",
        "files-unsorted",
        "files-duplicate",
        "absent-has-directories",
        "absent-has-files",
        "present-root-missing",
        "present-root-duplicate",
        "directory-outside-root",
        "directory-parent-missing",
        "file-outside-root",
        "file-parent-missing",
        "file-directory-collision",
        "regular-file-ancestor",
        "tree-file-missing-image",
    ),
)
def test_decode_rejects_invalid_tree_layout(case):
    _assert_invalid(_layout_mutation(case))


def _selection_mutation(case):
    value = json.loads(VALID_WIRE)
    missing_tree = {
        "path": "a", "exists": "false", "directories": [], "files": [],
    }
    if case == "trees-unsorted":
        value["trees"].append(missing_tree)
    elif case == "trees-duplicate":
        value["trees"].append(value["trees"][0])
    elif case == "files-unsorted":
        other = json.loads(json.dumps(value["files"][0])); other["path"] = "aardvark"
        value["files"].append(other)
    elif case == "files-duplicate":
        value["files"].append(value["files"][0])
    elif case == "cross-batch-duplicate":
        value["files"][0]["path"] = "specs"
    elif case == "interleaved-ancestor":
        value["trees"] = [
            missing_tree,
            {**missing_tree, "path": "a-"},
            {**missing_tree, "path": "a/b"},
        ]
        value["files"] = []
    else:  # pragma: no cover
        raise AssertionError(case)
    return _canonical(value)


@pytest.mark.parametrize(
    "case",
    (
        "trees-unsorted",
        "trees-duplicate",
        "files-unsorted",
        "files-duplicate",
        "cross-batch-duplicate",
        "interleaved-ancestor",
    ),
)
def test_decode_rejects_unsorted_duplicate_or_overlapping_selection(case):
    _assert_invalid(_selection_mutation(case))


@pytest.mark.parametrize(
    "payload",
    (
        "",
        '{"files":[],"trees":[],"version":"1","version":"1"}',
        " " + EMPTY_WIRE,
        EMPTY_WIRE + "\n",
        EMPTY_WIRE.replace('"files":[]', '"files" : []'),
        EMPTY_WIRE.replace('"files":[],"trees":[]', '"trees":[],"files":[]'),
        EMPTY_WIRE.replace('"version":"1"', '"version":"\\u0031"'),
        EMPTY_WIRE.replace('"version":"1"', '"version":1'),
        "[" * 2000 + "]" * 2000,
        "\udcff",
    ),
)
def test_decode_rejects_duplicate_numeric_deep_or_noncanonical_json(payload):
    _assert_invalid(payload)


def test_decode_rejects_literal_non_ascii_instead_of_canonical_ascii_escape():
    value = json.loads(VALID_WIRE)
    value["files"][0]["path"] = "žluť"
    canonical = _canonical(value)
    assert "\\u017e" in canonical
    _assert_invalid(canonical.replace("\\u017e", "ž"))


def test_validate_requires_exact_snapshot_and_intact_exact_string_fields():
    from harness.squad_source_manifest import SourceManifestSnapshot
    from harness.squad_source_manifest_codec import validate_source_manifest

    class SnapshotSubclass(SourceManifestSnapshot):
        pass

    class StringSubclass(str):
        pass

    malformed = (
        object(),
        SnapshotSubclass(VALID_WIRE, VALID_DIGEST),
        SourceManifestSnapshot(StringSubclass(VALID_WIRE), VALID_DIGEST),
        SourceManifestSnapshot(VALID_WIRE, StringSubclass(VALID_DIGEST)),
        SourceManifestSnapshot(VALID_WIRE, "0" * 64),
        SourceManifestSnapshot(VALID_WIRE, "A" * 64),
        SourceManifestSnapshot(VALID_WIRE, None),
    )
    for snapshot in malformed:
        with pytest.raises(publication.PublicationError, match="^manifest_invalid$"):
            validate_source_manifest(snapshot)

    missing_payload = SourceManifestSnapshot(VALID_WIRE, VALID_DIGEST)
    object.__delattr__(missing_payload, "payload")
    missing_digest = SourceManifestSnapshot(VALID_WIRE, VALID_DIGEST)
    object.__delattr__(missing_digest, "sha256")
    damaged_payload = SourceManifestSnapshot(VALID_WIRE, VALID_DIGEST)
    object.__setattr__(damaged_payload, "payload", None)
    for snapshot in (missing_payload, missing_digest, damaged_payload):
        with pytest.raises(publication.PublicationError, match="^manifest_invalid$"):
            validate_source_manifest(snapshot)


def test_validate_returns_a_detached_snapshot_without_changing_input():
    from harness.squad_source_manifest import SourceManifestSnapshot
    from harness.squad_source_manifest_codec import validate_source_manifest

    supplied = SourceManifestSnapshot(VALID_WIRE, VALID_DIGEST)
    before = (supplied.payload, supplied.sha256)
    validated = validate_source_manifest(supplied)
    assert validated == supplied
    assert validated is not supplied
    assert (supplied.payload, supplied.sha256) == before


def test_public_boundaries_hide_malformed_unicode_and_reused_validator_context(
    monkeypatch,
):
    import harness.squad_source_manifest_codec as codec
    from harness.squad_source_manifest import SourceManifestSnapshot

    with pytest.raises(publication.PublicationError) as caught:
        codec.decode_source_manifest("\udcff")
    rendered = "".join(traceback.format_exception(caught.value))
    assert str(caught.value) == "manifest_invalid"
    assert caught.value.__suppress_context__ is True
    assert "surrogates not allowed" not in rendered

    def contextual_failure(*args, **kwargs):
        try:
            raise ValueError("untrusted reused-validator context")
        except ValueError as error:
            raise publication.PublicationError("manifest_invalid") from error

    monkeypatch.setattr(codec, "_validate_tree_layout", contextual_failure)
    with pytest.raises(publication.PublicationError) as caught:
        codec.decode_source_manifest(VALID_WIRE)
    rendered = "".join(traceback.format_exception(caught.value))
    assert caught.value.__suppress_context__ is True
    assert "untrusted reused-validator context" not in rendered

    monkeypatch.setattr(codec, "decode_source_manifest", contextual_failure)
    supplied = SourceManifestSnapshot(VALID_WIRE, VALID_DIGEST)
    with pytest.raises(publication.PublicationError) as caught:
        codec.validate_source_manifest(supplied)
    rendered = "".join(traceback.format_exception(caught.value))
    assert caught.value.__suppress_context__ is True
    assert "untrusted reused-validator context" not in rendered


def test_base_exception_propagates_unchanged(monkeypatch):
    import harness.squad_source_manifest_codec as codec
    from harness.squad_source_manifest import SourceManifestSnapshot

    class Sentinel(BaseException):
        pass

    expected = Sentinel("control")

    def stop(*args, **kwargs):
        raise expected

    monkeypatch.setattr(codec, "strict_json", stop)
    with pytest.raises(Sentinel) as caught:
        codec.decode_source_manifest(EMPTY_WIRE)
    assert caught.value is expected
    with pytest.raises(Sentinel) as caught:
        codec.validate_source_manifest(SourceManifestSnapshot(EMPTY_WIRE, EMPTY_DIGEST))
    assert caught.value is expected


def test_self_consistent_changed_hash_is_only_a_different_metadata_claim():
    from harness.squad_publication_snapshot import PublicationImageDescriptor
    from harness.squad_source_manifest import snapshot_source_manifest
    from harness.squad_source_manifest_codec import decode_source_manifest
    from harness.squad_source_snapshot import ProjectPathSnapshot

    content = b"observed source"
    observed = snapshot_source_manifest(
        trees=(),
        files=(
            ProjectPathSnapshot(
                "source.md",
                PublicationImageDescriptor(
                    "file", hashlib.sha256(content).hexdigest(), 0o644
                ),
                content,
            ),
        ),
    )
    value = json.loads(observed.payload)
    value["files"][0]["image"]["sha256"] = "0" * 64
    altered = decode_source_manifest(_canonical(value))
    assert altered.sha256 == hashlib.sha256(altered.payload.encode("ascii")).hexdigest()
    assert altered != observed
    assert altered.payload != observed.payload


def test_decode_and_validate_are_pure_after_real_setup(
    tmp_path, secure_posix, monkeypatch
):
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import SourceManifestSnapshot, snapshot_source_manifest
    import harness.squad_source_manifest_codec as codec

    project = tmp_path.resolve()
    (project / "source/empty").mkdir(parents=True)
    (project / "source/input").write_bytes(b"source\r\n\x00\xff")
    squad = project / "runs/spec-pure"
    squad.mkdir(parents=True)
    prepared = SquadPublicationTransaction.begin(project, squad, "6" * 32).seal()
    with prepared.inspect_sources(tree_paths=("source",), file_paths=("absent",)) as sources:
        pass
    observed = snapshot_source_manifest(trees=sources.trees, files=sources.files)
    before = SourceManifestSnapshot(observed.payload, observed.sha256)

    def forbidden(*args, **kwargs):
        pytest.fail("source-manifest codec accessed external state")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(io, "open", forbidden)
        patch.setattr(Path, "open", forbidden)
        patch.setattr(Path, "read_bytes", forbidden)
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
        decoded = codec.decode_source_manifest(observed.payload)
        validated = codec.validate_source_manifest(observed)

    assert decoded == validated == observed == before
    assert decoded is not observed
    assert validated is not observed
    assert observed == before
