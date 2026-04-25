"""4-source image resolution chain.

Per FR-IMAGE-001a/b/c:
  Priority 1: devcontainer.json (if present)
  Priority 2: harness Dockerfile (if present)
  Priority 3: fingerprint-based (language detection)
  Priority 4: config.yml base_image override

Per FR-IMAGE-001b: devcontainer overrides Playwright auto-selection.
Per FR-IMAGE-001c: no image from any source -> error listing all 4 sources.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from harness.devcontainer import parse_devcontainer
from harness.fingerprint import fingerprint_repo

logger = logging.getLogger(__name__)


class ImageResolutionError(Exception):
    """Raised when no image can be resolved from any source."""


@dataclass
class ResolvedImage:
    """Result of image resolution."""
    image: str
    source: str  # devcontainer | harness_dockerfile | fingerprint | config_override


def resolve_image(
    target_repo_path: Path,
    harness_dockerfile: Optional[Path] = None,
    config_base_image: Optional[str] = None,
) -> ResolvedImage:
    """Resolve the sandbox image using the 4-source priority chain.

    Args:
        target_repo_path: Path to the target repo (for devcontainer + fingerprint).
        harness_dockerfile: Path to a harness-provided Dockerfile (priority 2).
        config_base_image: Explicit image from config.yml (priority 4).

    Returns:
        ResolvedImage with the selected image and its source.

    Raises:
        ImageResolutionError: If no source can provide an image.
    """
    sources_tried = []

    # Priority 1: devcontainer.json
    devcontainer_path = target_repo_path / ".devcontainer" / "devcontainer.json"
    dc = parse_devcontainer(devcontainer_path)
    if dc is not None and dc.image:
        logger.info("Image resolved from devcontainer.json: %s", dc.image)
        return ResolvedImage(image=dc.image, source="devcontainer")
    sources_tried.append("devcontainer.json (not found or no image field)")

    # Priority 2: harness Dockerfile
    if harness_dockerfile is not None and harness_dockerfile.exists():
        # We don't parse the Dockerfile, just note it exists.
        # The Docker provider will build from it.
        logger.info("Image resolved from harness Dockerfile: %s", harness_dockerfile)
        return ResolvedImage(
            image=f"harness-build:{harness_dockerfile.stem}",
            source="harness_dockerfile",
        )
    sources_tried.append("harness Dockerfile (not provided or not found)")

    # Priority 3: fingerprint-based detection.
    # Only use if a real language was detected — "generic" means no markers
    # found, so fall through to Priority 4 rather than masking it.
    fp = fingerprint_repo(target_repo_path)
    if fp.language != "generic":
        logger.info(
            "Image resolved from fingerprint (%s, playwright=%s): %s",
            fp.language, fp.has_playwright, fp.image,
        )
        return ResolvedImage(image=fp.image, source="fingerprint")
    sources_tried.append(f"fingerprint (no language markers found in {target_repo_path})")

    # Priority 4: config.yml base_image override
    if config_base_image:
        logger.info("Image resolved from config base_image: %s", config_base_image)
        return ResolvedImage(image=config_base_image, source="config_override")
    sources_tried.append("config base_image (not set)")

    raise ImageResolutionError(
        f"No image could be resolved from any source. Tried: {'; '.join(sources_tried)}"
    )
