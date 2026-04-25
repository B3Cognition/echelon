"""Devcontainer.json subset parser.

Per FR-DEVCONTAINER-001: honor a subset of devcontainer.json fields,
warn on ignored fields. Handle missing/empty/binary files gracefully.

Honored fields: image, build.dockerfile, features, forwardPorts,
                containerEnv, postCreateCommand
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

HONORED_FIELDS = {
    "image", "build", "features", "forwardPorts",
    "containerEnv", "postCreateCommand",
}


@dataclass
class DevcontainerConfig:
    """Parsed subset of devcontainer.json."""
    image: Optional[str] = None
    dockerfile: Optional[str] = None
    features: Dict[str, Any] = field(default_factory=dict)
    forward_ports: List[int] = field(default_factory=list)
    container_env: Dict[str, str] = field(default_factory=dict)
    post_create_command: Optional[str] = None


def parse_devcontainer(path: Path) -> Optional[DevcontainerConfig]:
    """Parse devcontainer.json at the given path.

    Returns None if the file doesn't exist or can't be parsed.
    Warns on ignored fields.
    """
    if not path.exists():
        return None

    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        logger.warning("Could not read devcontainer.json at %s (binary or unreadable)", path)
        return None

    if not text.strip():
        logger.warning("Empty devcontainer.json at %s", path)
        return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in devcontainer.json at %s", path)
        return None

    if not isinstance(data, dict):
        logger.warning("devcontainer.json is not an object at %s", path)
        return None

    # Warn on ignored fields
    for key in data:
        if key not in HONORED_FIELDS and not key.startswith("//"):
            logger.warning("Ignoring devcontainer.json field: %s", key)

    # Extract honored fields
    image = data.get("image")
    dockerfile = None
    build_section = data.get("build")
    if isinstance(build_section, dict):
        dockerfile = build_section.get("dockerfile")

    features = data.get("features", {})
    if not isinstance(features, dict):
        features = {}

    forward_ports = data.get("forwardPorts", [])
    if not isinstance(forward_ports, list):
        forward_ports = []

    container_env = data.get("containerEnv", {})
    if not isinstance(container_env, dict):
        container_env = {}

    post_create_command = data.get("postCreateCommand")
    if isinstance(post_create_command, list):
        post_create_command = " && ".join(str(c) for c in post_create_command)
    elif post_create_command is not None:
        post_create_command = str(post_create_command)

    return DevcontainerConfig(
        image=str(image) if image else None,
        dockerfile=str(dockerfile) if dockerfile else None,
        features=features,
        forward_ports=[int(p) for p in forward_ports if isinstance(p, (int, float))],
        container_env={str(k): str(v) for k, v in container_env.items()},
        post_create_command=post_create_command,
    )
