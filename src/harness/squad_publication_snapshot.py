"""Detached publication images and connection-free image assembly."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from harness.squad_publication_schema import PublicationError, PublicationMarker


@dataclass(frozen=True)
class PublicationImageDescriptor:
    kind: str
    sha256: str | None
    mode: int | None


@dataclass(frozen=True)
class PublicationOperationSnapshot:
    action: str
    target: str
    preimage: PublicationImageDescriptor
    postimage: PublicationImageDescriptor
    current: PublicationImageDescriptor
    current_bytes: bytes | None
    postimage_bytes: bytes | None


@dataclass(frozen=True)
class PublicationSnapshot:
    marker: PublicationMarker
    promoted_prefix: int
    operations: tuple[PublicationOperationSnapshot, ...]


def _image_descriptor(image: Mapping[str, object]) -> PublicationImageDescriptor:
    """Detach an already-validated manifest image without normalizing it."""
    return PublicationImageDescriptor(
        kind=image["kind"], sha256=image.get("sha256"), mode=image.get("mode")
    )


def _authenticate_image_prefix(
    images: Iterable[tuple[object, object, object]],
) -> int:
    """Return the lowest legal global prefix for (pre, post, current) images."""
    lower_boundary = 0
    upper_boundary: int | None = None
    for index, (preimage, postimage, current) in enumerate(images):
        if current != preimage and current != postimage:
            raise PublicationError("target_drift")
        if preimage == postimage:
            continue
        if current == postimage:
            lower_boundary = max(lower_boundary, index + 1)
        else:
            upper_boundary = (
                index if upper_boundary is None else min(upper_boundary, index)
            )
        if upper_boundary is not None and lower_boundary > upper_boundary:
            raise PublicationError("target_drift")
    return lower_boundary
