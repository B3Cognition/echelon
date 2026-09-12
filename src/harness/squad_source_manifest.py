"""Canonical metadata fingerprint for selected source observations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from harness import squad_publication as publication
from harness.squad_source_baseline_codec import (
    _encode_image,
    _path,
    _source_selection,
    _tree_value,
)
from harness.squad_source_snapshot import ProjectPathSnapshot, ProjectTreeSnapshot


@dataclass(frozen=True, slots=True)
class SourceManifestSnapshot:
    payload: str
    sha256: str


def _invalid() -> None:
    raise publication.PublicationError("manifest_invalid")


def _without_content(image: dict[str, str | None]) -> dict[str, str | None]:
    image.pop("content_base64")
    return image


def snapshot_source_manifest(
    *,
    trees: tuple[ProjectTreeSnapshot, ...],
    files: tuple[ProjectPathSnapshot, ...],
) -> SourceManifestSnapshot:
    """Fingerprint one explicit, already captured source selection."""
    try:
        if type(trees) is not tuple or type(files) is not tuple:
            _invalid()

        tree_values: list[dict[str, object]] = []
        tree_paths: list[str] = []
        for tree in trees:
            value, _, _ = _tree_value(tree)
            for item in value["files"]:
                _without_content(item["image"])
            tree_values.append(value)
            tree_paths.append(value["path"])

        file_values: list[dict[str, object]] = []
        file_paths: list[str] = []
        for item in files:
            if type(item) is not ProjectPathSnapshot:
                _invalid()
            path = _path(item.path)
            image = _without_content(_encode_image(item.image, item.content))
            file_values.append({"path": path, "image": image})
            file_paths.append(path)

        selected_trees, selected_files = _source_selection(
            tuple(tree_paths), tuple(file_paths)
        )
        if selected_trees != tuple(tree_paths) or selected_files != tuple(file_paths):
            _invalid()

        payload = json.dumps(
            {"version": "1", "trees": tree_values, "files": file_values},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
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
    ):
        raise publication.PublicationError("manifest_invalid") from None
