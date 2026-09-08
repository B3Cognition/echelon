"""Fail-closed parsing for the small Compose topology local verification needs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Collection, Mapping

import yaml


class LocalComposePolicyError(ValueError):
    """Raised when candidate Compose asks for host authority it does not have."""


class _UniqueComposeLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: _UniqueComposeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise LocalComposePolicyError(f"duplicate Compose key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueComposeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


@dataclass(frozen=True)
class CanonicalComposeService:
    name: str
    image: str


@dataclass(frozen=True)
class CanonicalComposePlan:
    worktree: Path
    compose_path: Path
    services: tuple[CanonicalComposeService, ...]


def parse_canonical_compose_plan(
    worktree: Path,
    compose_file: str,
    allowed_services: Collection[str],
) -> CanonicalComposePlan:
    """Return only stack-authorized internal services from a candidate file."""
    root = Path(worktree).expanduser()
    if root.is_symlink():
        raise LocalComposePolicyError("candidate worktree is symlinked")
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise LocalComposePolicyError("candidate worktree is unavailable") from exc
    if not root.is_dir():
        raise LocalComposePolicyError("candidate worktree is unavailable")
    relative = Path(compose_file)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise LocalComposePolicyError("Compose file must be candidate-relative")
    source = root / relative
    if source.is_symlink() or not source.is_file():
        raise LocalComposePolicyError("Compose file must be a regular candidate file")
    try:
        source.resolve(strict=True).relative_to(root)
        raw = yaml.load(source.read_text(encoding="utf-8"), Loader=_UniqueComposeLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise LocalComposePolicyError("could not parse candidate Compose file") from exc
    if not isinstance(raw, dict):
        raise LocalComposePolicyError("Compose root must be a mapping")
    _validate_topology(raw)
    selected = {str(item) for item in allowed_services}
    if not selected:
        raise LocalComposePolicyError("resolved stack permits no local Compose services")
    services = raw.get("services")
    if not isinstance(services, dict) or not services:
        raise LocalComposePolicyError("Compose services must be a non-empty mapping")
    unknown = sorted(str(name) for name in services if str(name) not in selected)
    if unknown:
        raise LocalComposePolicyError(f"Compose service is not stack-authorized: {unknown[0]}")
    missing = sorted(selected.difference(str(name) for name in services))
    if missing:
        raise LocalComposePolicyError(f"Compose omits stack-authorized service: {missing[0]}")
    canonical: list[CanonicalComposeService] = []
    for name in sorted(services):
        canonical.append(_parse_service(str(name), services[name]))
    return CanonicalComposePlan(
        worktree=root,
        compose_path=source.resolve(strict=True),
        services=tuple(canonical),
    )


def _validate_topology(raw: Mapping[object, object]) -> None:
    if "volumes" in raw:
        volumes = raw["volumes"]
        if isinstance(volumes, dict):
            for value in volumes.values():
                if isinstance(value, dict) and "driver_opts" in value:
                    raise LocalComposePolicyError("Compose volume driver_opts are not allowed")
        raise LocalComposePolicyError("Compose volumes are not allowed")
    forbidden = {
        "networks": "Compose networks are not allowed",
        "configs": "Compose configs are not allowed",
        "secrets": "Compose secrets are not allowed",
        "include": "Compose include is not allowed",
    }
    for key, message in forbidden.items():
        if key in raw:
            raise LocalComposePolicyError(message)
    unknown = set(raw).difference({"services", "version"})
    if unknown:
        raise LocalComposePolicyError(f"unsupported Compose root key: {sorted(map(str, unknown))[0]}")


def _parse_service(name: str, value: object) -> CanonicalComposeService:
    if not isinstance(value, dict):
        raise LocalComposePolicyError(f"Compose service {name} must be a mapping")
    if "privileged" in value:
        raise LocalComposePolicyError("privileged Compose services are not allowed")
    if "ports" in value:
        raise LocalComposePolicyError("candidate-authored published port is not allowed")
    if "volumes" in value:
        mounts = value.get("volumes")
        if isinstance(mounts, list) and any(
            isinstance(item, str) and item.startswith("/") for item in mounts
        ):
            raise LocalComposePolicyError("absolute bind mount is not allowed")
        raise LocalComposePolicyError("Compose service volumes are not allowed")
    forbidden = {
        "build": "Compose builds are not allowed",
        "devices": "Compose devices are not allowed",
        "cap_add": "Compose capabilities are not allowed",
        "cap_drop": "Compose capabilities are not allowed",
        "security_opt": "Compose security options are not allowed",
        "network_mode": "Compose host namespaces are not allowed",
        "pid": "Compose host namespaces are not allowed",
        "ipc": "Compose host namespaces are not allowed",
        "container_name": "Compose container_name is not allowed",
        "extends": "Compose extends is not allowed",
        "env_file": "Compose env_file is not allowed",
        "profiles": "Compose profiles are not allowed",
    }
    for key, message in forbidden.items():
        if key in value:
            raise LocalComposePolicyError(message)
    unknown = set(value).difference({"image"})
    if unknown:
        raise LocalComposePolicyError(
            f"unsupported Compose service key: {sorted(map(str, unknown))[0]}"
        )
    image = value.get("image")
    if not isinstance(image, str) or not image.strip():
        raise LocalComposePolicyError(f"Compose service {name} requires a public image")
    image = image.strip()
    if not _is_public_postgres_image(image):
        raise LocalComposePolicyError("Compose image is not an approved public PostgreSQL image")
    return CanonicalComposeService(name=name, image=image)


def _is_public_postgres_image(image: str) -> bool:
    if any(token in image for token in ("@", "${", "://")):
        return False
    repository = image.split("@", 1)[0].split(":", 1)[0]
    return repository in {"postgres", "docker.io/library/postgres"}
