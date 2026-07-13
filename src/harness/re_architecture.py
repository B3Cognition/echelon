"""Deterministic architecture composition for published RE domains.

The domain manifest remains the source-ownership contract. This module only
adds a read-only architectural view used to browse and sequence those domains.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from echelon.workspace_model import IGNORED_SOURCE_DIRS
from harness.re_domain_manifest import (
    ReDomain,
    discover_source_domains,
    domain_manifest_path,
    load_domain_manifest,
)
from harness.re_planner import ReExecutionPlan


ARCHITECTURE_CATALOG_VERSION = 1
_SOURCE_SUFFIXES = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".go",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".kts",
        ".mjs",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".swift",
        ".ts",
        ".tsx",
    }
)
_RELATIVE_IMPORT = re.compile(
    r"(?:\b(?:import|export)\b[^\n;]*?\bfrom\s*|\brequire\s*\()"
    r"[\"'](?P<path>\.[^\"']*)[\"']"
)
_PYTHON_RELATIVE_IMPORT = re.compile(
    r"^\s*from\s+(?P<path>\.{1,}[A-Za-z0-9_\.]*)\s+import\b", re.MULTILINE
)

_LAYER_RULES = (
    ("frontend", "Frontend", frozenset({"app", "components", "frontend", "pages", "ui", "views", "web"})),
    ("backend", "Backend/API", frozenset({"api", "apis", "controller", "controllers", "graphql", "handler", "handlers", "routes", "server"})),
    ("persistence", "Persistence", frozenset({"dao", "database", "db", "persistence", "repository", "repositories", "store", "stores"})),
    ("integration", "Integration", frozenset({"adapter", "adapters", "client", "clients", "connector", "connectors", "external", "integration", "integrations", "messaging", "queue", "queues"})),
    ("application", "Application", frozenset({"application", "business", "domain", "service", "services", "usecase", "usecases", "workflow", "workflows"})),
    ("foundation", "Foundation", frozenset({"common", "config", "constants", "core", "entity", "entities", "foundation", "lib", "models", "schema", "shared", "types", "utils", "utilities"})),
    ("delivery", "Delivery/Operations", frozenset({"deploy", "deployment", "helm", "infra", "k8s", "ops", "terraform"})),
)
_LAYER_RANK = {
    "foundation": 10,
    "persistence": 20,
    "integration": 30,
    "application": 40,
    "backend": 50,
    "frontend": 60,
    "delivery": 70,
    "other": 80,
}


@dataclass(frozen=True)
class ReArchitectureDomain:
    key: str
    source_id: str
    domain_id: str
    root: str
    source_file_count: int
    source_line_count: int
    layer: str
    layer_label: str
    dependencies: tuple[str, ...]
    migration_wave: int
    cycle_group: str | None

    def to_json_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["dependencies"] = list(self.dependencies)
        return result


@dataclass(frozen=True)
class ReArchitectureMap:
    domains: tuple[ReArchitectureDomain, ...]
    waves: tuple[dict[str, object], ...]
    cycles: tuple[dict[str, object], ...]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "architecture_catalog_version": ARCHITECTURE_CATALOG_VERSION,
            "domains": [domain.to_json_dict() for domain in self.domains],
            "waves": list(self.waves),
            "cycles": list(self.cycles),
        }


def build_re_architecture_map(
    plan: ReExecutionPlan,
    *,
    run_re_dir: Path | None = None,
) -> ReArchitectureMap:
    """Build a dependency-safe architectural view without changing ownership."""
    domains_by_key: dict[str, tuple[Path, ReDomain, str, str]] = {}
    for source in plan.sources:
        if not source.selected or source.action in {"exclude", "missing", "skip-empty"}:
            continue
        source_root = Path(source.absolute_path).resolve()
        if not source_root.is_dir():
            continue
        domains = _domains_for_source(source, run_re_dir)
        for domain in domains:
            key = _domain_key(source.id, domain.domain_id)
            layer, layer_label = _classify_layer(domain.root)
            domains_by_key[key] = (source_root, domain, layer, layer_label)

    dependencies = {key: set() for key in domains_by_key}
    by_source: dict[str, list[tuple[str, Path, ReDomain]]] = {}
    for key, (source_root, domain, _layer, _label) in domains_by_key.items():
        source_id = key.split("/", 1)[0]
        by_source.setdefault(source_id, []).append((key, source_root, domain))
    for entries in by_source.values():
        _collect_source_dependencies(entries, dependencies)

    waves, cycle_groups = _migration_waves(dependencies, domains_by_key)
    domains: list[ReArchitectureDomain] = []
    for key in _ordered_keys(waves, domains_by_key):
        source_root, domain, layer, layer_label = domains_by_key[key]
        del source_root
        domains.append(
            ReArchitectureDomain(
                key=key,
                source_id=key.split("/", 1)[0],
                domain_id=domain.domain_id,
                root=domain.root,
                source_file_count=domain.source_file_count,
                source_line_count=domain.source_line_count,
                layer=layer,
                layer_label=layer_label,
                dependencies=tuple(sorted(dependencies[key])),
                migration_wave=waves[key],
                cycle_group=cycle_groups.get(key),
            )
        )
    wave_rows = _wave_rows(domains)
    cycle_rows = _cycle_rows(cycle_groups)
    return ReArchitectureMap(
        domains=tuple(domains),
        waves=tuple(wave_rows),
        cycles=tuple(cycle_rows),
    )


def _domains_for_source(source: object, run_re_dir: Path | None) -> tuple[ReDomain, ...]:
    if run_re_dir is not None:
        path = domain_manifest_path(run_re_dir, source.id)
        if path.is_file():
            manifest = load_domain_manifest(path)
            if manifest.source_id != source.id or manifest.source_path != source.path:
                raise ValueError(f"architecture manifest mismatch for source {source.id}")
            return manifest.domains
    return discover_source_domains(source).domains


def write_re_architecture_catalog(
    run_re_dir: Path,
    architecture: ReArchitectureMap,
) -> tuple[Path, Path]:
    """Write controller-owned architecture artifacts atomically."""
    workspace = run_re_dir / "workspace"
    map_path = workspace / "architecture-map.json"
    catalog_path = workspace / "domain-catalog.md"
    _write_json_atomic(map_path, architecture.to_json_dict())
    _write_text_atomic(catalog_path, render_re_domain_catalog(architecture))
    return map_path, catalog_path


def load_re_architecture_map(path: Path) -> ReArchitectureMap:
    """Load the durable architecture map used by prompts and publication."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read architecture map: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("unsupported architecture map schema")
    if raw.get("architecture_catalog_version") != ARCHITECTURE_CATALOG_VERSION:
        raise ValueError("unsupported architecture catalog version")
    raw_domains = raw.get("domains")
    raw_waves = raw.get("waves")
    raw_cycles = raw.get("cycles")
    if not isinstance(raw_domains, list) or not isinstance(raw_waves, list) or not isinstance(raw_cycles, list):
        raise ValueError("architecture map requires domains, waves, and cycles")
    domains: list[ReArchitectureDomain] = []
    keys: set[str] = set()
    for item in raw_domains:
        if not isinstance(item, dict):
            raise ValueError("architecture domain must be an object")
        required_strings = ("key", "source_id", "domain_id", "root", "layer", "layer_label")
        if any(not isinstance(item.get(field), str) or not item[field] for field in required_strings):
            raise ValueError("architecture domain has invalid identity fields")
        key = str(item["key"])
        if key in keys:
            raise ValueError("architecture map has duplicate domain keys")
        keys.add(key)
        dependencies = item.get("dependencies")
        if not isinstance(dependencies, list) or any(not isinstance(value, str) for value in dependencies):
            raise ValueError("architecture domain dependencies must be strings")
        if not isinstance(item.get("source_file_count"), int) or not isinstance(item.get("source_line_count"), int):
            raise ValueError("architecture domain counts must be integers")
        if not isinstance(item.get("migration_wave"), int) or item["migration_wave"] < 1:
            raise ValueError("architecture domain migration_wave must be positive")
        cycle_group = item.get("cycle_group")
        if cycle_group is not None and not isinstance(cycle_group, str):
            raise ValueError("architecture domain cycle_group must be a string or null")
        domains.append(
            ReArchitectureDomain(
                key=key,
                source_id=str(item["source_id"]),
                domain_id=str(item["domain_id"]),
                root=str(item["root"]),
                source_file_count=item["source_file_count"],
                source_line_count=item["source_line_count"],
                layer=str(item["layer"]),
                layer_label=str(item["layer_label"]),
                dependencies=tuple(sorted(dependencies)),
                migration_wave=item["migration_wave"],
                cycle_group=cycle_group,
            )
        )
    if any(dependency not in keys for domain in domains for dependency in domain.dependencies):
        raise ValueError("architecture map dependency does not identify a domain")
    if any(not isinstance(item, dict) for item in raw_waves + raw_cycles):
        raise ValueError("architecture map waves and cycles must be objects")
    return ReArchitectureMap(tuple(domains), tuple(raw_waves), tuple(raw_cycles))


def validate_re_architecture_catalog(
    run_re_dir: Path,
    plan: ReExecutionPlan,
) -> ReArchitectureMap:
    """Require every refreshed domain to be represented in the published view."""
    workspace = run_re_dir / "workspace"
    architecture = load_re_architecture_map(workspace / "architecture-map.json")
    catalog_path = workspace / "domain-catalog.md"
    try:
        catalog = catalog_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read architecture catalog: {exc}") from exc
    if not catalog.startswith("# Architecture Domain Catalog\n"):
        raise ValueError("architecture catalog has an invalid heading")
    actual = {domain.key: domain for domain in architecture.domains}
    for source in plan.refresh_sources:
        manifest = load_domain_manifest(domain_manifest_path(run_re_dir, source.id))
        for domain in manifest.domains:
            key = _domain_key(source.id, domain.domain_id)
            architecture_domain = actual.get(key)
            if architecture_domain is None or architecture_domain.root != domain.root:
                raise ValueError(f"architecture catalog is missing refreshed domain {key}")
    return architecture


def render_re_domain_catalog(architecture: ReArchitectureMap) -> str:
    """Render a stable, dependency-ordered entry point for RE specs."""
    lines = [
        "# Architecture Domain Catalog",
        "",
        "This controller-owned catalog groups stable source-owned domains by architecture layer and migration wave.",
        "Domain IDs and owned roots are unchanged; the ordering is a reading and implementation aid.",
        "",
        "## Migration Waves",
        "",
    ]
    for wave in architecture.waves:
        number = wave["wave"]
        label = wave["label"]
        lines.extend(
            [
                f"### Wave {number}: {label}",
                "",
                "| Source | Domain | Layer | Owned root | Prerequisites |",
                "|---|---|---|---|---|",
            ]
        )
        for key in wave["domains"]:
            domain = next(item for item in architecture.domains if item.key == key)
            dependencies = ", ".join(domain.dependencies) if domain.dependencies else "None"
            lines.append(
                f"| {domain.source_id} | {domain.domain_id} | {domain.layer_label} | `{domain.root}` | {dependencies} |"
            )
        lines.append("")
    if architecture.cycles:
        lines.extend(["## Cycles", ""])
        for cycle in architecture.cycles:
            lines.append(
                f"- **{cycle['id']}**: " + ", ".join(cycle["domains"])
            )
        lines.append("")
    lines.extend(["## Dependency Graph", "", "```mermaid", "flowchart LR"])
    aliases = {domain.key: f"D{index}" for index, domain in enumerate(architecture.domains, start=1)}
    for domain in architecture.domains:
        label = f"{domain.source_id}: {domain.domain_id} ({domain.layer_label})".replace('"', "'")
        lines.append(f'  {aliases[domain.key]}["{label}"]')
    for domain in architecture.domains:
        for dependency in domain.dependencies:
            lines.append(f"  {aliases[dependency]} --> {aliases[domain.key]}")
    lines.extend(["```", ""])
    return "\n".join(lines)


def _collect_source_dependencies(
    entries: list[tuple[str, Path, ReDomain]],
    dependencies: dict[str, set[str]],
) -> None:
    source_root = entries[0][1]
    by_root = sorted(entries, key=lambda item: len(Path(item[2].root).parts), reverse=True)
    for source_file in _source_files(source_root):
        relative = source_file.relative_to(source_root)
        source_key = _domain_for_path(relative, by_root)
        if source_key is None:
            continue
        try:
            text = source_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for imported in _relative_imports(text):
            target = _resolve_relative_import(source_root, source_file, imported)
            if target is None:
                continue
            target_key = _domain_for_path(target, by_root)
            if target_key and target_key != source_key:
                dependencies[source_key].add(target_key)


def _source_files(root: Path) -> Iterable[Path]:
    for directory, names, files in os.walk(root):
        names[:] = sorted(
            name for name in names if not name.startswith(".") and name not in IGNORED_SOURCE_DIRS
        )
        for filename in sorted(files):
            path = Path(directory) / filename
            if path.suffix.lower() in _SOURCE_SUFFIXES:
                yield path


def _relative_imports(text: str) -> set[str]:
    imports = {match.group("path") for match in _RELATIVE_IMPORT.finditer(text)}
    imports.update(match.group("path") for match in _PYTHON_RELATIVE_IMPORT.finditer(text))
    return imports


def _resolve_relative_import(source_root: Path, source_file: Path, imported: str) -> Path | None:
    if imported.startswith("."):
        if imported.startswith("..") or "/" in imported:
            candidate = (source_file.parent / imported).resolve(strict=False)
        else:
            dots = len(imported) - len(imported.lstrip("."))
            suffix = imported[dots:].replace(".", "/")
            candidate = source_file.parent
            for _ in range(max(0, dots - 1)):
                candidate = candidate.parent
            candidate = (candidate / suffix).resolve(strict=False)
        try:
            return candidate.relative_to(source_root)
        except ValueError:
            return None
    return None


def _domain_for_path(
    relative: Path,
    entries: list[tuple[str, Path, ReDomain]],
) -> str | None:
    value = relative.as_posix()
    for key, _source_root, domain in entries:
        if domain.root == "." or value == domain.root or value.startswith(domain.root + "/"):
            return key
    return None


def _classify_layer(root: str) -> tuple[str, str]:
    tokens = set(re.split(r"[^a-z0-9]+", root.lower()))
    for layer, label, indicators in _LAYER_RULES:
        if tokens & indicators:
            return layer, label
    return "other", "Other"


def _migration_waves(
    dependencies: dict[str, set[str]],
    domains_by_key: dict[str, tuple[Path, ReDomain, str, str]],
) -> tuple[dict[str, int], dict[str, str]]:
    components = _strongly_connected_components(dependencies)
    component_for = {
        key: index for index, component in enumerate(components) for key in component
    }
    component_dependencies = {
        index: {
            component_for[dependency]
            for key in component
            for dependency in dependencies[key]
            if component_for[dependency] != index
        }
        for index, component in enumerate(components)
    }
    processed: set[int] = set()
    wave_by_key: dict[str, int] = {}
    cycle_groups: dict[str, str] = {}
    wave = 0
    while len(processed) < len(components):
        ready = [
            index
            for index, values in component_dependencies.items()
            if index not in processed and values <= processed
        ]
        if not ready:
            raise ValueError("architecture component graph is not acyclic")
        minimum_rank = min(
            _component_sort_key(components[index], domains_by_key)[0]
            for index in ready
        )
        selected = [
            index
            for index in ready
            if _component_sort_key(components[index], domains_by_key)[0] == minimum_rank
        ]
        wave += 1
        for index in sorted(selected, key=lambda item: _component_sort_key(components[item], domains_by_key)):
            component = components[index]
            cycle_id = None
            if len(component) > 1 or any(key in dependencies[key] for key in component):
                cycle_id = f"cycle-{len(set(cycle_groups.values())) + 1:03d}"
            for key in component:
                wave_by_key[key] = wave
                if cycle_id:
                    cycle_groups[key] = cycle_id
            processed.add(index)
    return wave_by_key, cycle_groups


def _strongly_connected_components(dependencies: dict[str, set[str]]) -> list[tuple[str, ...]]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(key: str) -> None:
        nonlocal index
        indices[key] = index
        lowlinks[key] = index
        index += 1
        stack.append(key)
        on_stack.add(key)
        for dependency in sorted(dependencies[key]):
            if dependency not in indices:
                visit(dependency)
                lowlinks[key] = min(lowlinks[key], lowlinks[dependency])
            elif dependency in on_stack:
                lowlinks[key] = min(lowlinks[key], indices[dependency])
        if lowlinks[key] == indices[key]:
            component: list[str] = []
            while True:
                candidate = stack.pop()
                on_stack.remove(candidate)
                component.append(candidate)
                if candidate == key:
                    break
            components.append(tuple(sorted(component)))

    for key in sorted(dependencies):
        if key not in indices:
            visit(key)
    return components


def _component_sort_key(
    component: tuple[str, ...],
    domains_by_key: dict[str, tuple[Path, ReDomain, str, str]],
) -> tuple[int, str]:
    return min((_LAYER_RANK[domains_by_key[key][2]], key) for key in component)


def _ordered_keys(
    waves: dict[str, int],
    domains_by_key: dict[str, tuple[Path, ReDomain, str, str]],
) -> list[str]:
    return sorted(
        waves,
        key=lambda key: (waves[key], _LAYER_RANK[domains_by_key[key][2]], key),
    )


def _wave_rows(domains: list[ReArchitectureDomain]) -> list[dict[str, object]]:
    by_wave: dict[int, list[ReArchitectureDomain]] = {}
    for domain in domains:
        by_wave.setdefault(domain.migration_wave, []).append(domain)
    rows: list[dict[str, object]] = []
    for wave, values in sorted(by_wave.items()):
        labels = {value.layer_label for value in values}
        label = next(iter(labels)) if len(labels) == 1 else "Mixed architecture"
        rows.append({"wave": wave, "label": label, "domains": [value.key for value in values]})
    return rows


def _cycle_rows(cycle_groups: dict[str, str]) -> list[dict[str, object]]:
    grouped: dict[str, list[str]] = {}
    for key, group in cycle_groups.items():
        grouped.setdefault(group, []).append(key)
    return [
        {"id": group, "domains": sorted(values)}
        for group, values in sorted(grouped.items())
    ]


def _domain_key(source_id: str, domain_id: str) -> str:
    return f"{source_id}/{domain_id}"


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    _write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
