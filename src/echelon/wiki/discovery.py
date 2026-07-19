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
_CANONICAL_SPEC_ID_RE = re.compile(r"^\d{3,}-[a-z0-9]+(?:-[a-z0-9]+)*$")
_PUBLICATION_COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$")


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


def canonical_input_hashes(
    project_root: Path,
    *,
    artifacts: Iterable[WikiArtifact] | None = None,
) -> dict[str, str]:
    """Hash safe config identity and every allowed canonical artifact file."""
    root = project_root.resolve()
    safe_config = json.dumps(
        _safe_config_payload(root), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    result = {"@config/workspace": _sha256(safe_config)}
    if artifacts is None:
        paths, _warnings = _allowed_paths(root)
        for path in paths:
            result[path.relative_to(root).as_posix()] = _sha256(path.read_bytes())
    else:
        for artifact in artifacts:
            result[artifact.source_path] = artifact.sha256
    return dict(sorted(result.items()))


def _title(path: Path, data: bytes | None = None) -> str:
    if path.suffix.lower() != ".md":
        return path.name
    try:
        text = (
            data.decode("utf-8")
            if data is not None
            else path.read_text(encoding="utf-8")
        )
        for line in text.splitlines():
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


def _publication_provenance(
    project_root: Path,
    spec_dir: Path,
    spec_id: str,
) -> tuple[str | None, str | None, WikiWarning | None]:
    manifest_path = spec_dir / ".echelon-publication.json"
    if not manifest_path.is_file():
        return None, None, None
    relative = manifest_path.relative_to(project_root).as_posix()
    invalid = WikiWarning(
        "invalid-spec-publication",
        "Publication manifest is invalid or does not match its spec directory.",
        relative,
    )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None, invalid
    if not isinstance(payload, dict):
        return None, None, invalid

    source_branch = payload.get("source_branch")
    source_commit = payload.get("source_commit")
    if (
        payload.get("schema_version") != 1
        or payload.get("spec_id") != spec_id
        or source_branch != spec_id
        or _CANONICAL_SPEC_ID_RE.fullmatch(spec_id) is None
        or not isinstance(source_commit, str)
        or _PUBLICATION_COMMIT_RE.fullmatch(source_commit) is None
    ):
        return None, None, invalid
    return source_branch, source_commit, None


def _spec_relationships(
    project_root: Path,
    spec_dir: Path,
    spec_id: str,
    requirement_ids: tuple[str, ...],
    task_ids: tuple[str, ...],
) -> tuple[list[WikiRelationship], list[WikiWarning]]:
    relationships: list[WikiRelationship] = []
    warnings: list[WikiWarning] = []
    known_requirements = set(requirement_ids)
    known_tasks = set(task_ids)

    spec_path = spec_dir / "spec.md"
    try:
        spec_lines = spec_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        spec_lines = []
    current_requirement: str | None = None
    for line_number, line in enumerate(spec_lines, start=1):
        if line.startswith("REQ:"):
            match = _REQUIREMENT_RE.search(line[4:])
            current_requirement = f"{spec_id}:{match.group(0)}" if match else None
        elif line.startswith("DEPENDS:") and current_requirement:
            for dependency in sorted(set(_REQUIREMENT_RE.findall(line[8:]))):
                target = f"{spec_id}:{dependency}"
                if current_requirement in known_requirements and target in known_requirements:
                    relationships.append(
                        WikiRelationship(
                            "depends_on",
                            current_requirement,
                            target,
                            spec_path.relative_to(project_root).as_posix(),
                            f"line:{line_number}:DEPENDS:{dependency}",
                        )
                    )

    trace_path = spec_dir / "traceability-matrix.md"
    if trace_path.is_file():
        try:
            trace_lines = trace_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            trace_lines = []
        for line_number, line in enumerate(trace_lines, start=1):
            if not line.strip().startswith("|"):
                continue
            cells = [
                cell.strip().strip("`")
                for cell in line.strip().strip("|").split("|")
            ]
            if len(cells) < 5 or cells[0].lower() in {"requirement", "---"}:
                continue
            requirement_match = _REQUIREMENT_RE.search(cells[0])
            task_match = _TASK_RE.search(cells[1])
            if not requirement_match:
                continue
            requirement = f"{spec_id}:{requirement_match.group(0)}"
            if requirement not in known_requirements:
                continue
            evidence_path = trace_path.relative_to(project_root).as_posix()
            evidence_key = f"row:{line_number}"
            if task_match:
                task = f"{spec_id}:{task_match.group(0)}"
                if task in known_tasks:
                    relationships.append(
                        WikiRelationship(
                            "implements", task, requirement, evidence_path, evidence_key
                        )
                    )
            if cells[4].upper() in {"COVERED", "PARTIAL"} and cells[2] != "—":
                relationships.append(
                    WikiRelationship(
                        "verifies",
                        f"artifact:{evidence_path}",
                        requirement,
                        evidence_path,
                        evidence_key,
                    )
                )

    ledger_path = spec_dir / "deferred-scope.json"
    if ledger_path.is_file():
        try:
            payload = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            warnings.append(
                WikiWarning(
                    "invalid-deferred-scope",
                    "Deferred-scope relationships could not be parsed.",
                    ledger_path.relative_to(project_root).as_posix(),
                )
            )
        else:
            entries = payload.get("entries", []) if isinstance(payload, dict) else []
            if isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict) or entry.get("status") != "deferred":
                        continue
                    entry_id = str(entry.get("entry_id") or "unknown")
                    selected = entry.get("selected_ids", [])
                    if not isinstance(selected, list):
                        continue
                    for selected_id in selected:
                        target = f"{spec_id}:{selected_id}"
                        if target in known_requirements or target in known_tasks:
                            relationships.append(
                                WikiRelationship(
                                    "defers",
                                    f"spec:{spec_id}",
                                    target,
                                    ledger_path.relative_to(project_root).as_posix(),
                                    f"entries:{entry_id}:selected_ids:{selected_id}",
                                )
                            )
    return relationships, warnings


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
                title=_title(path, data),
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
    domains = _domains(root)
    source_ids = {source.source_id for source in sources}
    relationships: list[WikiRelationship] = []
    for domain in domains:
        if domain.source_id in source_ids:
            relationships.append(
                WikiRelationship(
                    "derived_from",
                    domain.stable_id,
                    f"source:{domain.source_id}",
                    domain.source_path,
                    "published-domain-path",
                )
            )
    specs: list[WikiSpec] = []
    specs_root = root / "specs"
    if specs_root.is_dir():
        for spec_dir in sorted(specs_root.iterdir(), key=lambda path: path.name):
            if not spec_dir.is_dir() or not (spec_dir / "spec.md").is_file():
                continue
            spec_id = spec_dir.name
            frontmatter = read_frontmatter(spec_dir)
            status = str(frontmatter.get("status") or "phase_a")
            supersedes = frontmatter.get("supersedes", [])
            if isinstance(supersedes, str):
                supersedes = [supersedes]
            if isinstance(supersedes, list):
                for superseded in supersedes:
                    if isinstance(superseded, str) and superseded.strip():
                        relationships.append(
                            WikiRelationship(
                                "supersedes",
                                f"spec:{spec_id}",
                                f"spec:{superseded.strip()}",
                                (spec_dir / "spec.md").relative_to(root).as_posix(),
                                f"frontmatter:supersedes:{superseded.strip()}",
                            )
                        )
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
            requirement_ids = _ids(spec_dir / "spec.md", _REQUIREMENT_RE, spec_id)
            task_ids = _ids(spec_dir / "tasks.md", _TASK_RE, spec_id)
            for artifact_id in artifact_ids:
                relationships.append(
                    WikiRelationship(
                        "contains",
                        f"spec:{spec_id}",
                        artifact_id,
                        f"specs/{spec_id}",
                        "path-containment",
                    )
                )
            for requirement_id in requirement_ids:
                relationships.append(
                    WikiRelationship(
                        "contains",
                        f"spec:{spec_id}",
                        requirement_id,
                        f"specs/{spec_id}/spec.md",
                        f"identifier:{requirement_id.split(':', 1)[1]}",
                    )
                )
            for task_id in task_ids:
                relationships.append(
                    WikiRelationship(
                        "contains",
                        f"spec:{spec_id}",
                        task_id,
                        f"specs/{spec_id}/tasks.md",
                        f"identifier:{task_id.split(':', 1)[1]}",
                    )
                )
            explicit, relationship_warnings = _spec_relationships(
                root, spec_dir, spec_id, requirement_ids, task_ids
            )
            relationships.extend(explicit)
            warnings.extend(relationship_warnings)
            publication_branch, publication_commit, publication_warning = (
                _publication_provenance(root, spec_dir, spec_id)
            )
            if publication_warning is not None:
                warnings.append(publication_warning)
            specs.append(
                WikiSpec(
                    stable_id=f"spec:{spec_id}",
                    spec_id=spec_id,
                    source_path=f"specs/{spec_id}",
                    title=_title(spec_dir / "spec.md"),
                    lifecycle_status=status,
                    targets=targets,
                    requirement_ids=requirement_ids,
                    task_ids=task_ids,
                    artifact_ids=artifact_ids,
                    publication_branch=publication_branch,
                    publication_commit=publication_commit,
                )
            )
    return WikiModel(
        schema_version=SCHEMA_VERSION,
        generated_at=generated_at,
        workspace_name=root.name,
        workspace_root=str(root),
        sources=sources,
        domains=domains,
        specs=tuple(specs),
        artifacts=artifacts,
        relationships=tuple(
            sorted(relationships, key=lambda edge: (edge.kind, edge.source_id, edge.target_id))
        ),
        recent_changes=_recent_changes(root, generated_at),
        warnings=tuple(warnings),
    )
