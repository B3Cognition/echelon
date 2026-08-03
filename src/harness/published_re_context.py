"""Run-local read-only snapshots of durable reverse-engineering publications."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePath
from typing import Any

from harness.re_registry import canonical_re_artifacts, load_published_index

_BRIEF_COMPONENT_CAP_BYTES = 24 * 1024
_BRIEF_TOTAL_CAP_BYTES = 96 * 1024
_MAX_TARGET_SELECTED_SOURCES = 3


def attach_published_re_context(
    project_root: Path,
    run_dir: Path,
    *,
    ignore: bool,
    implementation_targets: list[str] | None = None,
    re_sources: list[str] | None = None,
) -> dict[str, object]:
    """Return an immutable run-local view of the latest registered RE context."""
    if ignore:
        return {"status": "ignored", "generation": 0, "artifacts": {}}

    root = project_root.resolve()
    index = load_published_index(root)
    if index is None:
        return {"status": "absent", "generation": 0, "artifacts": {}}

    resolved_run = run_dir.resolve()
    if not resolved_run.is_relative_to(root):
        raise ValueError(f"spec run directory must be inside workspace: {run_dir}")

    canonical = canonical_re_artifacts(root, index)
    snapshot_root = resolved_run / "context" / "published-re"
    artifacts = _snapshot_artifact_map(root, snapshot_root, canonical)
    selected_sources, selection_reason = _select_re_sources(
        index,
        root,
        implementation_targets or [],
        re_sources or [],
    )
    rendered_briefings = _write_re_briefings(
        snapshot_root,
        artifacts,
        selected_sources=selected_sources,
    )
    artifacts["rendered_briefings"] = rendered_briefings
    return {
        "status": "attached",
        "generation": index.generation,
        "publication_status": index.publication_status,
        "snapshot_root": str(snapshot_root),
        "selected_sources": selected_sources,
        "selection_reason": selection_reason,
        "rendered_briefings": rendered_briefings,
        "artifacts": artifacts,
    }


def write_canonical_re_context(
    project_root: Path,
    spec_dir: Path,
    context: Mapping[str, object],
) -> Path:
    """Publish the run-local RE snapshot identity beside a canonical spec."""
    root = project_root.resolve()
    resolved_spec_dir = spec_dir.resolve()
    if not resolved_spec_dir.is_relative_to(root):
        raise ValueError(f"canonical spec directory must be inside workspace: {spec_dir}")

    status = str(context.get("status") or "").strip()
    if status not in {"attached", "ignored", "absent"}:
        raise ValueError(f"unsupported published RE context status: {status}")
    generation = context.get("generation", 0)
    if type(generation) is not int or generation < 0:
        raise ValueError("published RE context generation must be a non-negative integer")

    artifacts: list[dict[str, str]] = []
    if status == "attached":
        snapshot_value = context.get("snapshot_root")
        if not isinstance(snapshot_value, str) or not snapshot_value.strip():
            raise ValueError("attached published RE context is missing snapshot_root")
        snapshot_root = Path(snapshot_value).resolve()
        if not snapshot_root.is_relative_to(root):
            raise ValueError("published RE snapshot must be inside workspace")
        artifacts = _canonical_artifact_rows(
            context.get("artifacts"),
            snapshot_root=snapshot_root,
        )

    path = resolved_spec_dir / "re-context.json"
    payload = {
        "schema_version": 1,
        "status": status,
        "generation": generation,
        "artifacts": artifacts,
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _canonical_artifact_rows(
    value: object,
    *,
    snapshot_root: Path,
) -> list[dict[str, str]]:
    paths: set[Path] = set()
    for raw in _artifact_path_values(value):
        candidate = Path(raw)
        if not candidate.is_absolute():
            continue
        resolved = candidate.resolve()
        if not resolved.is_relative_to(snapshot_root):
            raise ValueError(f"published RE artifact is outside published RE snapshot: {candidate}")
        if resolved.is_file():
            paths.add(resolved)
        elif not resolved.exists():
            raise ValueError(f"published RE snapshot artifact is missing: {candidate}")

    return [
        {
            "path": f"re/{path.relative_to(snapshot_root).as_posix()}",
            "hash": f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
        }
        for path in sorted(paths, key=lambda item: item.relative_to(snapshot_root).as_posix())
    ]


def _artifact_path_values(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _artifact_path_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _artifact_path_values(item)


def _snapshot_artifact_map(
    project_root: Path,
    snapshot_root: Path,
    artifacts: dict[str, object],
) -> dict[str, object]:
    re_root = (project_root / "re").resolve()
    snapshot_root.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(
        tempfile.mkdtemp(prefix=".published-re-", dir=str(snapshot_root.parent))
    )
    try:
        rewritten = _rewrite_value(artifacts, re_root=re_root, destination=temp)
        if not isinstance(rewritten, dict):
            raise TypeError("canonical RE artifact map must be an object")
        if snapshot_root.exists():
            shutil.rmtree(snapshot_root)
        os.replace(temp, snapshot_root)
        return _replace_prefix(rewritten, temp, snapshot_root)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def _rewrite_value(value: object, *, re_root: Path, destination: Path) -> object:
    if isinstance(value, str):
        return _copy_registered_path(value, re_root=re_root, destination=destination)
    if isinstance(value, list):
        return [
            _rewrite_value(item, re_root=re_root, destination=destination)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            str(key): _rewrite_value(item, re_root=re_root, destination=destination)
            for key, item in value.items()
        }
    return value


def _copy_registered_path(value: str, *, re_root: Path, destination: Path) -> str:
    path = Path(value)
    if not path.is_absolute():
        return value
    resolved = path.resolve()
    if not resolved.is_relative_to(re_root):
        raise ValueError(f"published RE artifact escapes registry: {path}")
    relative = resolved.relative_to(re_root)
    target = destination / relative
    if resolved.is_dir():
        target.mkdir(parents=True, exist_ok=True)
    elif resolved.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved, target)
    else:
        raise ValueError(f"published RE artifact is missing: {path}")
    return str(target)


def _replace_prefix(value: Any, old: Path, new: Path) -> Any:
    if isinstance(value, str):
        path = Path(value)
        if path.is_absolute() and path.is_relative_to(old):
            return str(new / path.relative_to(old))
        return value
    if isinstance(value, list):
        return [_replace_prefix(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _replace_prefix(item, old, new) for key, item in value.items()}
    return value


def _select_re_sources(
    index: object,
    project_root: Path,
    implementation_targets: list[str],
    re_sources: list[str],
) -> tuple[list[str], dict[str, str]]:
    sources = getattr(index, "sources", {})
    selected: list[str] = []
    reasons: dict[str, str] = {}

    def add(source_id: str, reason: str) -> None:
        if source_id in sources and source_id not in selected:
            selected.append(source_id)
            reasons[source_id] = reason

    for value in re_sources:
        matched = _match_re_source_request(sources, project_root, value)
        if matched:
            add(matched, "explicit --re-source")

    for value in implementation_targets:
        matched = _match_implementation_target(sources, project_root, value)
        if matched:
            add(matched, "target matched published source path")
        if len(selected) >= _MAX_TARGET_SELECTED_SOURCES and not re_sources:
            break

    return selected, reasons


def _match_re_source_request(
    sources: Mapping[str, object],
    project_root: Path,
    value: str,
) -> str | None:
    raw = str(value or "").strip().strip("/")
    if not raw:
        return None
    if raw in sources:
        return raw
    parts = PurePath(raw).parts
    if len(parts) >= 3 and parts[0] == "re" and parts[1] == "sources":
        candidate = parts[2]
        return candidate if candidate in sources else None
    return _match_implementation_target(sources, project_root, raw)


def _match_implementation_target(
    sources: Mapping[str, object],
    project_root: Path,
    value: str,
) -> str | None:
    target = _normalize_target_ref(project_root, value)
    if not target:
        return None
    for source_id, source in sorted(sources.items()):
        if target == source_id:
            return source_id
        source_path = str(getattr(source, "source_path", "") or "").strip().strip("/")
        if not source_path:
            continue
        if target == source_path or target.startswith(f"{source_path}/"):
            return source_id
    return None


def _normalize_target_ref(project_root: Path, value: str) -> str:
    raw = str(value or "").strip().strip("/")
    if not raw:
        return ""
    path = Path(raw).expanduser()
    if path.is_absolute():
        try:
            return path.resolve().relative_to(project_root).as_posix().strip("/")
        except ValueError:
            return path.resolve().as_posix().strip("/")
    return PurePath(raw).as_posix().strip("/")


def _write_re_briefings(
    snapshot_root: Path,
    artifacts: dict[str, object],
    *,
    selected_sources: list[str],
) -> dict[str, object]:
    workspace = snapshot_root / "RE-WORKSPACE-BRIEF.md"
    workspace.write_text(_workspace_brief(snapshot_root, artifacts), encoding="utf-8")
    sources: dict[str, str] = {}
    for source_id in selected_sources:
        path = snapshot_root / f"RE-SOURCE-{source_id}-BRIEF.md"
        path.write_text(
            _source_brief(snapshot_root, artifacts, source_id),
            encoding="utf-8",
        )
        sources[source_id] = str(path)
    return {"workspace": str(workspace), "sources": sources}


def _workspace_brief(snapshot_root: Path, artifacts: Mapping[str, object]) -> str:
    lines = [
        "# Published RE Workspace Brief",
        "",
        "This deterministic briefing is assembled from registered published RE artifacts.",
        "",
    ]
    for key, title in (
        ("re_overview", "Workspace Overview"),
        ("cross_repo", "Relationships"),
        ("contracts", "Contracts"),
        ("workspace_checklist", "Workspace Checklist"),
        ("architecture_map", "Architecture Map"),
        ("workspace_codegraph_summary", "Workspace CodeGraph Summary"),
        ("domain_catalog", "Domain Catalog"),
    ):
        lines.extend(_artifact_section(snapshot_root, artifacts.get(key), title))
    strategy = artifacts.get("workspace_strategy")
    if isinstance(strategy, list):
        for item in strategy:
            lines.extend(_artifact_section(snapshot_root, item, "Workspace Strategy"))
    source_manifests = artifacts.get("source_manifests")
    if isinstance(source_manifests, dict):
        lines.extend(["## Available Source RE", ""])
        for source_id in sorted(source_manifests):
            lines.append(f"- {source_id}")
        lines.append("")
    return _bounded_text("\n".join(lines).rstrip() + "\n", _BRIEF_TOTAL_CAP_BYTES)


def _source_brief(
    snapshot_root: Path,
    artifacts: Mapping[str, object],
    source_id: str,
) -> str:
    lines = [
        f"# Published RE Source Brief: {source_id}",
        "",
        "This deterministic briefing is assembled from registered source-owned RE artifacts.",
        "",
    ]
    source_root = snapshot_root / "sources" / source_id
    lines.extend(_artifact_section(snapshot_root, source_root / "overview.md", "Source Overview"))
    for key, title in (
        ("source_architecture", "Source Architecture"),
        ("source_contracts", "Source Contracts"),
        ("source_components", "Source Components"),
    ):
        values = artifacts.get(key)
        if isinstance(values, dict):
            lines.extend(_artifact_section(snapshot_root, values.get(source_id), title))
    source_adrs = artifacts.get("source_adrs")
    if isinstance(source_adrs, dict):
        raw_paths = source_adrs.get(source_id)
        if isinstance(raw_paths, list):
            for adr_path in raw_paths:
                lines.extend(_artifact_section(snapshot_root, adr_path, "Source ADR"))
    for spec in _source_spec_paths(snapshot_root, artifacts, source_id):
        lines.extend(_artifact_section(snapshot_root, spec, "Source RE Spec"))
    domain_manifests = artifacts.get("source_domain_manifests")
    if isinstance(domain_manifests, dict):
        lines.extend(
            _artifact_section(snapshot_root, domain_manifests.get(source_id), "Domain Manifest")
        )
    supporting = artifacts.get("source_supporting_artifacts")
    if isinstance(supporting, dict):
        lines.extend(
            _artifact_section(snapshot_root, supporting.get(source_id), "Supporting Artifacts")
        )
    lines.extend(
        _artifact_section(
            snapshot_root,
            source_root / "codegraph-summary.json",
            "CodeGraph Summary",
        )
    )
    return _bounded_text("\n".join(lines).rstrip() + "\n", _BRIEF_TOTAL_CAP_BYTES)


def _source_spec_paths(
    snapshot_root: Path,
    artifacts: Mapping[str, object],
    source_id: str,
) -> list[Path]:
    specs = artifacts.get("re_specs")
    if not isinstance(specs, list):
        return []
    source_prefix = (snapshot_root / "sources" / source_id / "specs").resolve()
    paths: list[Path] = []
    for item in specs:
        if not isinstance(item, str):
            continue
        path = Path(item).resolve()
        if path.is_file() and path.is_relative_to(source_prefix):
            paths.append(path)
    return sorted(paths)


def _artifact_section(snapshot_root: Path, value: object, title: str) -> list[str]:
    if not isinstance(value, (str, Path)):
        return []
    path = Path(value).resolve()
    if not path.is_file() or not path.is_relative_to(snapshot_root):
        return []
    relative = path.relative_to(snapshot_root).as_posix()
    try:
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    body = _bounded_text(body, _BRIEF_COMPONENT_CAP_BYTES).rstrip()
    return [f"## {title}", "", f"# {relative}", body, ""]


def _bounded_text(text: str, cap_bytes: int) -> str:
    if len(text.encode("utf-8")) <= cap_bytes:
        return text
    notice = "\n[RE briefing truncated by Echelon context budget]\n"
    available = max(0, cap_bytes - len(notice.encode("utf-8")))
    return text.encode("utf-8")[:available].decode("utf-8", errors="ignore") + notice
