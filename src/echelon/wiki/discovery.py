"""Canonical, deterministic discovery for Echelon's human wiki."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

import yaml

from echelon.wiki.model import (
    WikiArtifact,
    WikiDomain,
    WikiModel,
    WikiRecentChange,
    WikiRelationship,
    WikiSource,
    WikiSpec,
    WikiWarning,
)
from harness.config import get_full_resolved_config
from harness.spec_frontmatter import read_frontmatter


SCHEMA_VERSION = 1
MAX_COPIED_ATTACHMENT_BYTES = 10 * 1024 * 1024
_IGNORED_RE_PARTS = {".cache", ".staging", ".locks"}
_TEXT_SUFFIXES = {".md", ".json", ".yaml", ".yml", ".txt", ".csv"}
_COPIED_ATTACHMENT_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
_REQUIREMENT_RE = re.compile(r"(?<![A-Z0-9-])(?:FR|NFR|REQ)-\d+(?![A-Z0-9-])")
_TASK_RE = re.compile(r"(?<![A-Z0-9-])(?:RF\d+-T\d+|T-\d+)(?![A-Z0-9-])")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_config_payload(project_root: Path) -> dict[str, Any]:
    resolved = get_full_resolved_config(project_root)
    workspace = resolved.get("workspace")
    safe_workspace: dict[str, Any] = {}
    if isinstance(workspace, dict):
        git_role = workspace.get("git_role")
        if isinstance(git_role, str):
            safe_workspace["git_role"] = git_role

    safe_sources: list[dict[str, str]] = []
    sources = resolved.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            source_id = source.get("id")
            source_path = source.get("path")
            if isinstance(source_id, str) and isinstance(source_path, str):
                safe_sources.append({"id": source_id, "path": source_path})
    safe_sources.sort(key=lambda item: item["id"])
    return {"workspace": safe_workspace, "sources": safe_sources}


def _allowed_paths(project_root: Path) -> tuple[list[Path], list[WikiWarning]]:
    root = project_root.resolve()
    paths: list[Path] = []
    warnings: list[WikiWarning] = []
    for directory_name in ("specs", "re"):
        directory = root / directory_name
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
            relative = path.relative_to(root)
            if directory_name == "re" and any(part in _IGNORED_RE_PARTS for part in relative.parts):
                continue
            if path.is_symlink():
                try:
                    resolved = path.resolve(strict=True)
                except OSError:
                    warnings.append(
                        WikiWarning("broken-symlink", "Symlink target is unavailable.", relative.as_posix())
                    )
                    continue
                if not resolved.is_relative_to(directory.resolve()):
                    warnings.append(
                        WikiWarning(
                            "path-escape",
                            "Symlink escapes its canonical artifact root and was ignored.",
                            relative.as_posix(),
                        )
                    )
                    continue
            if path.is_file():
                paths.append(path)
    return paths, warnings


def canonical_input_hashes(project_root: Path) -> dict[str, str]:
    """Hash safe config identity and every allowed canonical artifact file."""
    root = project_root.resolve()
    safe_config = json.dumps(
        _safe_config_payload(root), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    result = {"@config/workspace": _sha256(safe_config)}
    paths, _warnings = _allowed_paths(root)
    for path in paths:
        result[path.relative_to(root).as_posix()] = _sha256(path.read_bytes())
    return dict(sorted(result.items()))


def _title(path: Path) -> str:
    if path.suffix.lower() != ".md":
        return path.name
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                if title:
                    return title
    except (OSError, UnicodeDecodeError):
        pass
    return path.stem.replace("-", " ").title()


def _artifact_kind(relative: str) -> str:
    name = Path(relative).name.lower()
    if name == "spec.md":
        return "specification"
    if name == "plan.md":
        return "plan"
    if name == "tasks.md":
        return "tasks"
    if "verification" in name or name in {"fulfillment-report.md", "traceability-matrix.md"}:
        return "verification"
    if "risk" in name or name == "issues.md":
        return "risk"
    if "decision" in name or name.startswith("adr"):
        return "decision"
    return "artifact"


def _copy_mode(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        return "text"
    if suffix in _COPIED_ATTACHMENT_SUFFIXES and path.stat().st_size <= MAX_COPIED_ATTACHMENT_BYTES:
        return "attachment"
    return "catalog"


def _yaml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _targets(path: Path) -> tuple[str, ...]:
    raw = _yaml_file(path).get("targets", [])
    result: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                value = item.strip()
            elif isinstance(item, dict):
                value = str(item.get("id") or item.get("path") or "").strip()
            else:
                value = ""
            if value and value not in result:
                result.append(value)
    return tuple(result)


def _ids(path: Path, pattern: re.Pattern[str], namespace: str) -> tuple[str, ...]:
    if not path.is_file():
        return ()
    try:
        matches = set(pattern.findall(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError):
        return ()
    return tuple(f"{namespace}:{match}" for match in sorted(matches))


def _published_index(project_root: Path) -> dict[str, Any]:
    path = project_root / "re/index.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _sources(project_root: Path) -> tuple[WikiSource, ...]:
    safe = _safe_config_payload(project_root)
    published = _published_index(project_root).get("sources", {})
    published = published if isinstance(published, dict) else {}
    result: list[WikiSource] = []
    for source in safe["sources"]:
        source_id = source["id"]
        record = published.get(source_id)
        published_path = None
        if isinstance(record, dict) and isinstance(record.get("published_path"), str):
            published_path = record["published_path"]
        result.append(
            WikiSource(
                stable_id=f"source:{source_id}",
                source_id=source_id,
                path=source["path"],
                published_path=published_path,
            )
        )
    return tuple(result)


def _domains(project_root: Path) -> tuple[WikiDomain, ...]:
    result: list[WikiDomain] = []
    sources_root = project_root / "re/sources"
    if sources_root.is_dir():
        for spec_path in sorted(sources_root.glob("*/specs/*/spec.md")):
            source_id = spec_path.parents[2].name
            domain_id = spec_path.parent.name
            result.append(
                WikiDomain(
                    stable_id=f"domain:{source_id}:{domain_id}",
                    source_id=source_id,
                    domain_id=domain_id,
                    source_path=spec_path.relative_to(project_root).as_posix(),
                    title=_title(spec_path),
                )
            )
    workspace_domains = project_root / "re/workspace/domains"
    if workspace_domains.is_dir():
        for domain_path in sorted(workspace_domains.glob("*.md")):
            domain_id = domain_path.stem
            result.append(
                WikiDomain(
                    stable_id=f"domain:workspace:{domain_id}",
                    source_id="workspace",
                    domain_id=domain_id,
                    source_path=domain_path.relative_to(project_root).as_posix(),
                    title=_title(domain_path),
                )
            )
    return tuple(sorted(result, key=lambda domain: domain.stable_id))


def _git(project_root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return result.stdout if result.returncode == 0 else ""


def _dirty_paths(project_root: Path) -> tuple[str, ...]:
    output = _git(project_root, ["status", "--porcelain", "--", "specs", "re"])
    paths: set[str] = set()
    for line in output.splitlines():
        value = line[3:].strip()
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        if value:
            paths.add(value.strip('"'))
    return tuple(sorted(paths))


def _recent_changes(project_root: Path, generated_at: str) -> tuple[WikiRecentChange, ...]:
    changes: list[WikiRecentChange] = []
    dirty = _dirty_paths(project_root)
    if dirty:
        changes.append(
            WikiRecentChange(
                commit="WORKTREE",
                committed_at=generated_at,
                subject="Uncommitted canonical artifact changes",
                paths=dirty,
            )
        )
    output = _git(
        project_root,
        [
            "log",
            "-10",
            "--format=@@%H%x1f%cI%x1f%s",
            "--name-only",
            "--",
            "specs",
            "re",
        ],
    )
    current: tuple[str, str, str] | None = None
    paths: list[str] = []
    for line in [*output.splitlines(), "@@END"]:
        if line.startswith("@@"):
            if current is not None:
                commit, committed_at, subject = current
                changes.append(
                    WikiRecentChange(commit, committed_at, subject, tuple(sorted(set(paths))))
                )
            paths = []
            if line == "@@END":
                current = None
                continue
            parts = line[2:].split("\x1f", 2)
            current = tuple(parts) if len(parts) == 3 else None  # type: ignore[assignment]
        elif current is not None and line.strip():
            paths.append(line.strip())
    return tuple(changes)


def _artifact_records(project_root: Path, paths: Iterable[Path]) -> tuple[WikiArtifact, ...]:
    result: list[WikiArtifact] = []
    for path in paths:
        relative = path.relative_to(project_root).as_posix()
        data = path.read_bytes()
        result.append(
            WikiArtifact(
                stable_id=f"artifact:{relative}",
                source_path=relative,
                projection_path=f"Artifacts/{relative}",
                title=_title(path),
                kind=_artifact_kind(relative),
                sha256=_sha256(data),
                size_bytes=len(data),
                copy_mode=_copy_mode(path),
            )
        )
    return tuple(result)


def discover_wiki_model(project_root: Path, *, generated_at: str) -> WikiModel:
    """Build a sorted, evidence-backed model from canonical workspace artifacts."""
    root = project_root.resolve()
    paths, warnings = _allowed_paths(root)
    artifacts = _artifact_records(root, paths)
    sources = _sources(root)
    source_ids = {source.source_id for source in sources}
    relationships: list[WikiRelationship] = []
    specs: list[WikiSpec] = []
    specs_root = root / "specs"
    if specs_root.is_dir():
        for spec_dir in sorted(specs_root.iterdir(), key=lambda path: path.name):
            if not spec_dir.is_dir() or not (spec_dir / "spec.md").is_file():
                continue
            spec_id = spec_dir.name
            frontmatter = read_frontmatter(spec_dir)
            status = str(frontmatter.get("status") or "phase_a")
            targets_path = spec_dir / "targets.yml"
            targets = _targets(targets_path)
            for target in targets:
                if target in source_ids:
                    relationships.append(
                        WikiRelationship(
                            kind="targets",
                            source_id=f"spec:{spec_id}",
                            target_id=f"source:{target}",
                            evidence_path=targets_path.relative_to(root).as_posix(),
                            evidence_key=f"targets:{target}",
                        )
                    )
            artifact_ids = tuple(
                artifact.stable_id
                for artifact in artifacts
                if Path(artifact.source_path).is_relative_to(Path("specs") / spec_id)
            )
            specs.append(
                WikiSpec(
                    stable_id=f"spec:{spec_id}",
                    spec_id=spec_id,
                    source_path=f"specs/{spec_id}",
                    title=_title(spec_dir / "spec.md"),
                    lifecycle_status=status,
                    targets=targets,
                    requirement_ids=_ids(spec_dir / "spec.md", _REQUIREMENT_RE, spec_id),
                    task_ids=_ids(spec_dir / "tasks.md", _TASK_RE, spec_id),
                    artifact_ids=artifact_ids,
                )
            )
    return WikiModel(
        schema_version=SCHEMA_VERSION,
        generated_at=generated_at,
        workspace_name=root.name,
        workspace_root=str(root),
        sources=sources,
        domains=_domains(root),
        specs=tuple(specs),
        artifacts=artifacts,
        relationships=tuple(
            sorted(relationships, key=lambda edge: (edge.kind, edge.source_id, edge.target_id))
        ),
        recent_changes=_recent_changes(root, generated_at),
        warnings=tuple(warnings),
    )
