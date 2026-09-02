"""Target repo language/package-manager detection.

Detects language/framework from marker files in the target repo.
Per FR-PLAYWRIGHT-001: detect @playwright/test in package.json.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Language detection markers (checked in order)
LANGUAGE_MARKERS = [
    ("package.json", "node"),
    ("pyproject.toml", "python"),
    ("Cargo.toml", "rust"),
    ("go.mod", "go"),
]

# Default images per detected language
LANGUAGE_IMAGES = {
    "node": "node:20-slim",
    "python": "python:3.12-slim",
    "rust": "rust:1-slim",
    "go": "golang:1.22-bookworm",
    "generic": "ubuntu:24.04",
}

# Playwright image override
PLAYWRIGHT_IMAGE = "mcr.microsoft.com/playwright:v1.42.0-jammy"


@dataclass
class Fingerprint:
    """Result of target repo fingerprinting."""
    language: str
    image: str
    has_playwright: bool = False


def detect_playwright(repo_path: Path) -> bool:
    """Check if package.json contains @playwright/test dependency.

    Per FR-PLAYWRIGHT-001: Playwright detection overrides fingerprint-based image.
    """
    package_json = repo_path / "package.json"
    if not package_json.exists():
        return False

    try:
        text = package_json.read_text(encoding="utf-8")
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return False

    for dep_key in ("dependencies", "devDependencies"):
        deps = data.get(dep_key, {})
        if isinstance(deps, dict) and "@playwright/test" in deps:
            return True

    return False


def playwright_version(repo_path: Path) -> str | None:
    """Return the declared Playwright version without reading host state."""
    package_json = repo_path / "package.json"
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    for dep_key in ("dependencies", "devDependencies"):
        dependencies = data.get(dep_key, {})
        if not isinstance(dependencies, dict):
            continue
        for name in ("@playwright/test", "playwright"):
            value = dependencies.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def fingerprint_repo(repo_path: Path) -> Fingerprint:
    """Detect language and select appropriate base image.

    Priority: Playwright detection overrides language-based selection.

    Args:
        repo_path: Path to the target repository root.

    Returns:
        Fingerprint with detected language and recommended image.
    """
    repo_path = Path(repo_path)

    # Detect language from marker files
    detected_language = "generic"
    for marker_file, language in LANGUAGE_MARKERS:
        if (repo_path / marker_file).exists():
            detected_language = language
            break

    # Check for Playwright (overrides image selection)
    has_playwright = detect_playwright(repo_path)

    if has_playwright:
        image = PLAYWRIGHT_IMAGE
    else:
        image = LANGUAGE_IMAGES.get(detected_language, LANGUAGE_IMAGES["generic"])

    if detected_language == "generic":
        logger.warning(
            "Could not detect language for %s. Using generic image.", repo_path
        )

    return Fingerprint(
        language=detected_language,
        image=image,
        has_playwright=has_playwright,
    )
