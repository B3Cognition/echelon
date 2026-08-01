"""Export Echelon's agent prose as normalized neutral Prosaic artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class ProsaicExportError(ValueError):
    """Raised when the Echelon extension cannot be normalized safely."""


@dataclass(frozen=True)
class ProsaicExportResult:
    """Summary of one normalized agent export."""

    destination: Path
    exported_count: int


def export_normalized_agents(extension_root: Path, destination: Path) -> ProsaicExportResult:
    """Write manifest-defined agent metadata and body-only Markdown to Prosaic."""
    manifest = _load_manifest(extension_root)
    exported = _export_entries(
        extension_root,
        destination,
        _artifact_entries(manifest, "agents/"),
        output_directory="subagents",
        artifact_id_from_name=True,
        normalize_arguments=False,
    )
    return ProsaicExportResult(destination=destination, exported_count=exported)


def export_normalized_prose(extension_root: Path, destination: Path) -> ProsaicExportResult:
    """Write all registered commands and agents as normalized Prosaic source."""
    manifest = _load_manifest(extension_root)
    agents = _export_entries(
        extension_root,
        destination,
        _artifact_entries(manifest, "agents/"),
        output_directory="subagents",
        artifact_id_from_name=True,
        normalize_arguments=False,
    )
    commands = _export_entries(
        extension_root,
        destination,
        _artifact_entries(manifest, "commands/"),
        output_directory="commands",
        artifact_id_from_name=False,
        normalize_arguments=True,
    )
    return ProsaicExportResult(destination=destination, exported_count=agents + commands)


def _load_manifest(extension_root: Path) -> object:
    manifest_path = extension_root / "extension.yml"
    try:
        return yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProsaicExportError(f"cannot read extension manifest: {manifest_path}") from exc
    except yaml.YAMLError as exc:
        raise ProsaicExportError(f"cannot parse extension manifest: {manifest_path}") from exc


def _artifact_entries(manifest: object, path_prefix: str) -> list[dict]:
    if not isinstance(manifest, dict):
        raise ProsaicExportError("extension manifest must be a mapping")
    provides = manifest.get("provides")
    if not isinstance(provides, dict) or not isinstance(provides.get("commands"), list):
        raise ProsaicExportError("extension manifest must define provides.commands")
    return [
        entry
        for entry in provides["commands"]
        if isinstance(entry, dict)
        and isinstance(entry.get("file"), str)
        and entry["file"].startswith(path_prefix)
    ]


def _export_entries(
    extension_root: Path,
    destination: Path,
    entries: list[dict],
    *,
    output_directory: str,
    artifact_id_from_name: bool,
    normalize_arguments: bool,
) -> int:
    output_dir = destination / output_directory
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale_artifact in output_dir.glob("*.md"):
        stale_artifact.unlink()
    exported_ids: set[str] = set()
    for entry in entries:
        artifact_id, source_file, frontmatter = _normalized_artifact(
            entry,
            artifact_id_from_name=artifact_id_from_name,
        )
        if artifact_id in exported_ids:
            raise ProsaicExportError(f"duplicate normalized artifact ID: {artifact_id}")
        exported_ids.add(artifact_id)
        target = output_dir / f"{artifact_id}.md"
        body = _markdown_body(extension_root / source_file)
        if normalize_arguments:
            body = body.replace("$ARGUMENTS", "{{args}}")
        target.write_text(_render_artifact(frontmatter, body), encoding="utf-8")
    return len(entries)


def _normalized_artifact(
    entry: dict,
    *,
    artifact_id_from_name: bool,
) -> tuple[str, Path, dict]:
    name = entry.get("name")
    description = entry.get("description")
    file_name = entry.get("file")
    behavior = entry.get("behavior", {})
    if not isinstance(name, str) or not name.startswith("speckit."):
        raise ProsaicExportError(f"agent has invalid manifest name: {name!r}")
    if not isinstance(description, str) or not description:
        raise ProsaicExportError(f"agent {name} has no description")
    expected_prefix = "agents/" if artifact_id_from_name else "commands/"
    if not isinstance(file_name, str) or not file_name.startswith(expected_prefix):
        raise ProsaicExportError(f"agent {name} has invalid file path")
    source_file = Path(file_name)
    if source_file.is_absolute() or ".." in source_file.parts:
        raise ProsaicExportError(f"agent {name} has unsafe file path")
    if not isinstance(behavior, dict):
        raise ProsaicExportError(f"agent {name} has invalid behavior")

    normalized_behavior = dict(behavior)
    if normalized_behavior.get("execution") == "isolated":
        normalized_behavior["execution"] = "command"
    normalized_behavior.pop("model", None)
    capability = normalized_behavior.pop("capability", None)
    if capability is not None:
        normalized_behavior["model_tier"] = capability
    frontmatter = {"name": name, "description": description, **normalized_behavior}
    artifact_id = name.removeprefix("speckit.") if artifact_id_from_name else source_file.stem
    return artifact_id, source_file, frontmatter


def _markdown_body(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProsaicExportError(f"cannot read agent body: {path}") from exc
    if not raw.startswith("---\n"):
        return raw
    end = raw.find("\n---\n", 4)
    if end == -1:
        raise ProsaicExportError(f"agent frontmatter is not closed: {path}")
    return raw[end + 5 :].lstrip("\n")


def _render_artifact(frontmatter: dict, body: str) -> str:
    metadata = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return f"---\n{metadata}---\n{body}"
