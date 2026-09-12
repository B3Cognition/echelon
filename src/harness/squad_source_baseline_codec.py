"""Canonical, detached encoding for an initial joint source observation."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path

from harness import squad_publication as publication
from harness.element_identity_json import MalformedJSON, strict_json
from harness.squad_publication import PublicationMarker
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
    _source_path,
    _source_selection,
)


_ROOT_KEYS = frozenset({"version", "publication", "trees", "files"})
_PUBLICATION_KEYS = frozenset({"marker", "operations"})
_MARKER_KEYS = frozenset({"schema_version", "transaction_id", "manifest_sha256"})
_OPERATION_KEYS = frozenset({"action", "target", "preimage", "postimage"})
_IMAGE_KEYS = frozenset({"kind", "sha256", "mode", "content_base64"})
_TREE_KEYS = frozenset({"path", "exists", "directories", "files"})
_DIRECTORY_KEYS = frozenset({"path", "mode"})
_FILE_KEYS = frozenset({"path", "image"})


def _invalid() -> None:
    raise publication.PublicationError("manifest_invalid")


def _text(value: object) -> str:
    if type(value) is not str:
        _invalid()
    try:
        value.encode("utf-8")
    except UnicodeError:
        _invalid()
    return value


def _path(value: object) -> str:
    return _source_path(_text(value)).as_posix()


def _mode(value: object) -> int:
    if type(value) is not int:
        _invalid()
    publication._validate_image({"kind": "file", "sha256": "0" * 64, "mode": value})
    return value


def _encode_image(
    image: object, content: object, *, require_file: bool = False,
) -> dict[str, str | None]:
    if type(image) is not PublicationImageDescriptor:
        _invalid()
    kind = _text(image.kind)
    if kind == "missing":
        publication._validate_image({"kind": kind})
        if image.sha256 is not None or image.mode is not None or content is not None:
            _invalid()
        if require_file:
            _invalid()
        return {"kind": "missing", "sha256": None, "mode": None, "content_base64": None}
    if kind != "file" or type(content) is not bytes:
        _invalid()
    validated = publication._validate_image(
        {"kind": kind, "sha256": image.sha256, "mode": image.mode}
    )
    if hashlib.sha256(content).hexdigest() != validated["sha256"]:
        _invalid()
    mode = _mode(validated["mode"])
    return {
        "kind": "file",
        "sha256": validated["sha256"],
        "mode": str(mode),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def _parts(path: str) -> tuple[str, ...]:
    return tuple(Path(path).parts)


def _is_at_or_below(path: str, root: str) -> bool:
    path_parts, root_parts = _parts(path), _parts(root)
    return path_parts[: len(root_parts)] == root_parts


def _has_ancestor(path: str, candidates: set[str]) -> bool:
    parts = _parts(path)
    return any(Path(*parts[:length]).as_posix() in candidates for length in range(1, len(parts)))


def _validate_tree_layout(
    root: str,
    exists: bool,
    directory_paths: list[str],
    file_paths: list[str],
) -> None:
    if directory_paths != sorted(directory_paths) or len(set(directory_paths)) != len(directory_paths):
        _invalid()
    if file_paths != sorted(file_paths) or len(set(file_paths)) != len(file_paths):
        _invalid()
    if not exists:
        if directory_paths or file_paths:
            _invalid()
    else:
        directory_set = set(directory_paths)
        if directory_paths.count(root) != 1:
            _invalid()
        for path in directory_paths:
            if not _is_at_or_below(path, root):
                _invalid()
            if path != root and Path(path).parent.as_posix() not in directory_set:
                _invalid()
        for path in file_paths:
            if not _is_at_or_below(path, root) or Path(path).parent.as_posix() not in directory_set:
                _invalid()
        if set(file_paths) & directory_set:
            _invalid()
        all_paths = set(directory_paths) | set(file_paths)
        if any(_has_ancestor(path, set(file_paths)) for path in all_paths):
            _invalid()


def _validate_targets(operations: tuple[PublicationOperationSnapshot, ...]) -> None:
    previous: str | None = None
    seen_parts: set[tuple[str, ...]] = set()
    for operation in operations:
        if type(operation) is not PublicationOperationSnapshot:
            _invalid()
        target = _path(operation.target)
        target_parts = _parts(target)
        if previous is not None and target <= previous:
            _invalid()
        if any(
            target_parts[:length] in seen_parts
            for length in range(1, len(target_parts))
        ):
            _invalid()
        previous = target
        seen_parts.add(target_parts)


def _tree_value(tree: object) -> tuple[dict[str, object], dict[str, tuple[PublicationImageDescriptor, bytes]], set[str]]:
    if type(tree) is not ProjectTreeSnapshot or type(tree.exists) is not bool:
        _invalid()
    root = _path(tree.path)
    if type(tree.directories) is not tuple or type(tree.files) is not tuple:
        _invalid()
    directories: list[dict[str, str]] = []
    directory_paths: list[str] = []
    for directory in tree.directories:
        if type(directory) is not ProjectDirectorySnapshot:
            _invalid()
        path = _path(directory.path)
        directories.append({"path": path, "mode": str(_mode(directory.mode))})
        directory_paths.append(path)
    file_values: list[dict[str, object]] = []
    file_paths: list[str] = []
    observations: dict[str, tuple[PublicationImageDescriptor, bytes]] = {}
    for item in tree.files:
        if type(item) is not ProjectFileSnapshot:
            _invalid()
        path = _path(item.path)
        image = _encode_image(item.image, item.content, require_file=True)
        file_values.append({"path": path, "image": image})
        file_paths.append(path)
        observations[path] = (item.image, item.content)
    _validate_tree_layout(root, tree.exists, directory_paths, file_paths)
    return (
        {
            "path": root,
            "exists": "true" if tree.exists else "false",
            "directories": directories,
            "files": file_values,
        },
        observations,
        set(directory_paths),
    )


def _snapshot_value(snapshot: object) -> dict[str, object]:
    if type(snapshot) is not PublicationSourcesSnapshot:
        _invalid()
    if type(snapshot.publication) is not PublicationSnapshot:
        _invalid()
    sealed = snapshot.publication
    if type(sealed.marker) is not PublicationMarker:
        _invalid()
    marker = publication._marker_from(sealed.marker)
    if type(sealed.promoted_prefix) is not int or sealed.promoted_prefix != 0:
        _invalid()
    if type(sealed.operations) is not tuple or type(snapshot.trees) is not tuple or type(snapshot.files) is not tuple:
        _invalid()
    _validate_targets(sealed.operations)

    operations: list[dict[str, object]] = []
    operation_observations: list[tuple[str, PublicationImageDescriptor, bytes | None]] = []
    for operation in sealed.operations:
        action = _text(operation.action)
        if action not in {"write", "delete"}:
            _invalid()
        target = _path(operation.target)
        preimage = _encode_image(operation.preimage, operation.current_bytes)
        current = _encode_image(operation.current, operation.current_bytes)
        postimage = _encode_image(operation.postimage, operation.postimage_bytes)
        if operation.current != operation.preimage or current != preimage:
            _invalid()
        if action == "write" and operation.postimage.kind != "file":
            _invalid()
        if action == "delete" and operation.postimage.kind != "missing":
            _invalid()
        operations.append(
            {"action": action, "target": target, "preimage": preimage, "postimage": postimage}
        )
        operation_observations.append((target, operation.preimage, operation.current_bytes))

    tree_values: list[dict[str, object]] = []
    tree_paths: list[str] = []
    selected_observations: dict[str, tuple[PublicationImageDescriptor, bytes | None]] = {}
    known_directories: set[str] = set()
    for tree in snapshot.trees:
        value, observations, directories = _tree_value(tree)
        tree_values.append(value)
        tree_paths.append(value["path"])
        selected_observations.update(observations)
        known_directories.update(directories)
        if tree.exists:
            root_parts = _parts(tree.path)
            known_directories.update(
                Path(*root_parts[:length]).as_posix() for length in range(1, len(root_parts))
            )

    file_values: list[dict[str, object]] = []
    selected_file_paths: list[str] = []
    for item in snapshot.files:
        if type(item) is not ProjectPathSnapshot:
            _invalid()
        path = _path(item.path)
        image = _encode_image(item.image, item.content)
        file_values.append({"path": path, "image": image})
        selected_file_paths.append(path)
        selected_observations[path] = (item.image, item.content)
        if item.image.kind == "file":
            path_parts = _parts(path)
            known_directories.update(
                Path(*path_parts[:length]).as_posix() for length in range(1, len(path_parts))
            )

    selected_trees, selected_files = _source_selection(tuple(tree_paths), tuple(selected_file_paths))
    if selected_trees != tuple(tree_paths) or selected_files != tuple(selected_file_paths):
        _invalid()
    known_files = {path for path, (image, _) in selected_observations.items() if image.kind == "file"}
    for target, descriptor, content in operation_observations:
        if target in known_directories or _has_ancestor(target, known_files):
            _invalid()
        expected = selected_observations.get(target)
        if expected is None and any(_is_at_or_below(target, tree_path) for tree_path in tree_paths):
            expected = (_missing_descriptor(), None)
        if expected is not None and (descriptor != expected[0] or content != expected[1]):
            _invalid()

    return {
        "version": "1",
        "publication": {
            "marker": {
                "schema_version": "1",
                "transaction_id": marker.transaction_id,
                "manifest_sha256": marker.manifest_sha256,
            },
            "operations": operations,
        },
        "trees": tree_values,
        "files": file_values,
    }


def _missing_descriptor() -> PublicationImageDescriptor:
    return PublicationImageDescriptor("missing", None, None)


def encode_initial_publication_sources(snapshot: PublicationSourcesSnapshot) -> str:
    """Encode a proven pre-promotion observation as canonical JSON."""
    try:
        value = _snapshot_value(snapshot)
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except publication.PublicationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeError, OverflowError):
        _invalid()


def _object(value: object, keys: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict or frozenset(dict.keys(value)) != keys:
        _invalid()
    return value


def _array(value: object) -> list[object]:
    if type(value) is not list:
        _invalid()
    return value


def _decode_mode(value: object) -> int:
    raw = _text(value)
    if not raw or len(raw) > 4 or not raw.isascii() or not raw.isdecimal():
        _invalid()
    mode = int(raw)
    if str(mode) != raw:
        _invalid()
    return _mode(mode)


def _decode_image(value: object, *, require_file: bool = False) -> tuple[PublicationImageDescriptor, bytes | None]:
    image = _object(value, _IMAGE_KEYS)
    kind = _text(image["kind"])
    if kind == "missing":
        if any(image[key] is not None for key in ("sha256", "mode", "content_base64")):
            _invalid()
        descriptor = _missing_descriptor()
        content = None
    elif kind == "file":
        sha256 = _text(image["sha256"])
        mode = _decode_mode(image["mode"])
        encoded = _text(image["content_base64"])
        try:
            raw = encoded.encode("ascii")
            content = base64.b64decode(raw, validate=True)
        except (UnicodeError, binascii.Error, ValueError):
            _invalid()
        if base64.b64encode(content).decode("ascii") != encoded:
            _invalid()
        descriptor = PublicationImageDescriptor("file", sha256, mode)
    else:
        _invalid()
    _encode_image(descriptor, content, require_file=require_file)
    return descriptor, content


def _decode_snapshot(value: object) -> PublicationSourcesSnapshot:
    root = _object(value, _ROOT_KEYS)
    if _text(root["version"]) != "1":
        _invalid()
    raw_publication = _object(root["publication"], _PUBLICATION_KEYS)
    raw_marker = _object(raw_publication["marker"], _MARKER_KEYS)
    if _text(raw_marker["schema_version"]) != "1":
        _invalid()
    marker = publication._marker_from(
        PublicationMarker(1, _text(raw_marker["transaction_id"]), _text(raw_marker["manifest_sha256"]))
    )
    operations: list[PublicationOperationSnapshot] = []
    for value_operation in _array(raw_publication["operations"]):
        raw_operation = _object(value_operation, _OPERATION_KEYS)
        preimage, preimage_bytes = _decode_image(raw_operation["preimage"])
        postimage, postimage_bytes = _decode_image(raw_operation["postimage"])
        operations.append(
            PublicationOperationSnapshot(
                _text(raw_operation["action"]), _text(raw_operation["target"]),
                preimage, postimage, preimage, preimage_bytes, postimage_bytes,
            )
        )
    sealed = PublicationSnapshot(marker, 0, tuple(operations))

    trees: list[ProjectTreeSnapshot] = []
    for value_tree in _array(root["trees"]):
        raw_tree = _object(value_tree, _TREE_KEYS)
        exists = _text(raw_tree["exists"])
        if exists not in {"true", "false"}:
            _invalid()
        directories = tuple(
            ProjectDirectorySnapshot(
                _text(raw_directory["path"]), _decode_mode(raw_directory["mode"])
            )
            for raw in _array(raw_tree["directories"])
            for raw_directory in (_object(raw, _DIRECTORY_KEYS),)
        )
        tree_files: list[ProjectFileSnapshot] = []
        for raw in _array(raw_tree["files"]):
            raw_file = _object(raw, _FILE_KEYS)
            image, content = _decode_image(raw_file["image"], require_file=True)
            if content is None:
                _invalid()
            tree_files.append(ProjectFileSnapshot(_text(raw_file["path"]), image, content))
        trees.append(
            ProjectTreeSnapshot(
                _text(raw_tree["path"]), exists == "true", directories, tuple(tree_files)
            )
        )

    files: list[ProjectPathSnapshot] = []
    for raw in _array(root["files"]):
        raw_file = _object(raw, _FILE_KEYS)
        image, content = _decode_image(raw_file["image"])
        files.append(ProjectPathSnapshot(_text(raw_file["path"]), image, content))
    return PublicationSourcesSnapshot(sealed, tuple(trees), tuple(files))


def decode_initial_publication_sources(payload: str) -> PublicationSourcesSnapshot:
    """Decode only the exact canonical v1 representation into detached values."""
    try:
        value = strict_json(payload)
        snapshot = _decode_snapshot(value)
        if encode_initial_publication_sources(snapshot) != payload:
            _invalid()
        return snapshot
    except publication.PublicationError:
        raise
    except (
        AttributeError, KeyError, TypeError, ValueError, UnicodeError, OverflowError,
        RecursionError, MalformedJSON, json.JSONDecodeError,
    ):
        _invalid()
