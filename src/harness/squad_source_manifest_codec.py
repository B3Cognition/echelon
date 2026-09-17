"""Strict decoding for the existing selected-source metadata fingerprint."""

from __future__ import annotations

import hashlib
import json

from harness import squad_publication as publication
from harness.element_identity_json import MalformedJSON, strict_json
from harness.squad_source_baseline_codec import (
    _array,
    _decode_mode,
    _object,
    _path,
    _source_selection,
    _text,
    _validate_tree_layout,
)
from harness.squad_source_manifest import SourceManifestSnapshot


_ROOT_KEYS = frozenset({"version", "trees", "files"})
_TREE_KEYS = frozenset({"path", "exists", "directories", "files"})
_DIRECTORY_KEYS = frozenset({"path", "mode"})
_FILE_KEYS = frozenset({"path", "image"})
_IMAGE_KEYS = frozenset({"kind", "sha256", "mode"})


def _invalid() -> None:
    raise publication.PublicationError("manifest_invalid")


def _decode_image(
    value: object, *, require_file: bool = False,
) -> dict[str, str | None]:
    image = _object(value, _IMAGE_KEYS)
    kind = _text(image["kind"])
    if kind == "missing":
        if require_file or image["sha256"] is not None or image["mode"] is not None:
            _invalid()
        return {"kind": "missing", "sha256": None, "mode": None}
    if kind != "file":
        _invalid()
    sha256 = publication._validate_sha256(image["sha256"])
    mode = _decode_mode(image["mode"])
    return {"kind": "file", "sha256": sha256, "mode": str(mode)}


def _decode_tree(value: object) -> dict[str, object]:
    tree = _object(value, _TREE_KEYS)
    root = _path(tree["path"])
    exists_text = _text(tree["exists"])
    if exists_text not in {"true", "false"}:
        _invalid()
    exists = exists_text == "true"

    directories: list[dict[str, str]] = []
    directory_paths: list[str] = []
    for value_directory in _array(tree["directories"]):
        raw_directory = _object(value_directory, _DIRECTORY_KEYS)
        path = _path(raw_directory["path"])
        mode = _decode_mode(raw_directory["mode"])
        directories.append({"path": path, "mode": str(mode)})
        directory_paths.append(path)

    files: list[dict[str, object]] = []
    file_paths: list[str] = []
    for value_file in _array(tree["files"]):
        raw_file = _object(value_file, _FILE_KEYS)
        path = _path(raw_file["path"])
        files.append(
            {
                "path": path,
                "image": _decode_image(raw_file["image"], require_file=True),
            }
        )
        file_paths.append(path)

    _validate_tree_layout(root, exists, directory_paths, file_paths)
    return {
        "path": root,
        "exists": exists_text,
        "directories": directories,
        "files": files,
    }


def _decode_value(value: object) -> dict[str, object]:
    root = _object(value, _ROOT_KEYS)
    if _text(root["version"]) != "1":
        _invalid()

    trees: list[dict[str, object]] = []
    tree_paths: list[str] = []
    for value_tree in _array(root["trees"]):
        tree = _decode_tree(value_tree)
        trees.append(tree)
        tree_paths.append(tree["path"])

    files: list[dict[str, object]] = []
    file_paths: list[str] = []
    for value_file in _array(root["files"]):
        raw_file = _object(value_file, _FILE_KEYS)
        path = _path(raw_file["path"])
        files.append({"path": path, "image": _decode_image(raw_file["image"])})
        file_paths.append(path)

    selected_trees, selected_files = _source_selection(
        tuple(tree_paths), tuple(file_paths)
    )
    if selected_trees != tuple(tree_paths) or selected_files != tuple(file_paths):
        _invalid()
    return {"version": "1", "trees": trees, "files": files}


def decode_source_manifest(payload: str) -> SourceManifestSnapshot:
    """Decode only the exact canonical ASCII selected-source metadata wire."""
    try:
        value = _decode_value(strict_json(payload))
        canonical = json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        if canonical != payload:
            _invalid()
        digest = hashlib.sha256(payload.encode("ascii")).hexdigest()
        return SourceManifestSnapshot(payload, digest)
    except publication.PublicationError:
        raise publication.PublicationError("manifest_invalid") from None
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        UnicodeError,
        OverflowError,
        RecursionError,
        MalformedJSON,
        json.JSONDecodeError,
    ):
        raise publication.PublicationError("manifest_invalid") from None


def validate_source_manifest(
    snapshot: SourceManifestSnapshot,
) -> SourceManifestSnapshot:
    """Validate an exact detached snapshot and return a fresh detached value."""
    try:
        if type(snapshot) is not SourceManifestSnapshot:
            _invalid()
        decoded = decode_source_manifest(snapshot.payload)
        if publication._validate_sha256(snapshot.sha256) != decoded.sha256:
            _invalid()
        return decoded
    except publication.PublicationError:
        raise publication.PublicationError("manifest_invalid") from None
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        UnicodeError,
        OverflowError,
        RecursionError,
        MalformedJSON,
        json.JSONDecodeError,
    ):
        raise publication.PublicationError("manifest_invalid") from None
