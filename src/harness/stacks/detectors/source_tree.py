from __future__ import annotations

import json
from pathlib import Path
import tomllib
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - dependency is present in test env
    yaml = None  # type: ignore[assignment]

from harness.stacks.evidence import StackEvidence, normalize_evidence_value


PACKAGE_TECHNOLOGIES = {
    "react": "react",
    "next": "nextjs",
    "nx": "nx",
    "@nx/next": "nx",
    "@nrwl/next": "nx",
    "@nestjs/core": "nestjs",
    "@nestjs/common": "nestjs",
    "pg": "postgres",
    "postgres": "postgres",
    "fastapi": "fastapi",
    "pydantic-settings": "pydantic",
    "pydantic": "pydantic",
    "@statsperform/react-playbook": "playbook",
    "@statsperform/playbook-cli": "playbook",
    "@statsperform/react-playbook-styles": "playbook",
}


def detect_source_tree(root: Path) -> list[StackEvidence]:
    evidence: list[StackEvidence] = []
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Stack detection target does not exist: {root}")

    _collect_package_json(root, evidence)
    _collect_python_project(root, evidence)
    _collect_marker_files(root, evidence)
    _collect_compose_files(root, evidence)
    return _dedupe(evidence)


def _collect_package_json(root: Path, evidence: list[StackEvidence]) -> None:
    package_json = root / "package.json"
    if not package_json.exists():
        return
    evidence.append(_file("package.json", package_json))
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    dependencies = _package_dependencies(data)
    for dependency in sorted(dependencies):
        _add_dependency_evidence(evidence, dependency, package_json)


def _package_dependencies(data: dict[str, Any]) -> set[str]:
    dependencies: set[str] = set()
    for key in (
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
    ):
        raw = data.get(key, {})
        if isinstance(raw, dict):
            dependencies.update(str(name) for name in raw)
    return dependencies


def _collect_python_project(root: Path, evidence: list[StackEvidence]) -> None:
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        evidence.append(_file("pyproject.toml", pyproject))
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        for dependency in sorted(_pyproject_dependencies(data)):
            _add_dependency_evidence(evidence, dependency, pyproject)

    for requirements in sorted(root.glob("requirements*.txt")):
        evidence.append(_file(requirements.name, requirements))
        try:
            lines = requirements.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            dependency = _requirement_name(line)
            if dependency:
                _add_dependency_evidence(evidence, dependency, requirements)


def _pyproject_dependencies(data: dict[str, Any]) -> set[str]:
    dependencies: set[str] = set()
    project = data.get("project", {})
    if isinstance(project, dict):
        dependencies.update(_dependency_names(project.get("dependencies", [])))
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            for values in optional.values():
                dependencies.update(_dependency_names(values))
    poetry = data.get("tool", {}).get("poetry", {}) if isinstance(data.get("tool"), dict) else {}
    if isinstance(poetry, dict):
        dependencies.update(str(name) for name in poetry.get("dependencies", {}) if name != "python")
        dependencies.update(str(name) for name in poetry.get("dev-dependencies", {}))
    return dependencies


def _dependency_names(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {name for value in values if (name := _requirement_name(str(value)))}


def _requirement_name(value: str) -> str:
    line = value.strip()
    if not line or line.startswith("#"):
        return ""
    for separator in ("==", ">=", "<=", "~=", ">", "<", "["):
        if separator in line:
            line = line.split(separator, 1)[0]
    return line.strip()


def _collect_marker_files(root: Path, evidence: list[StackEvidence]) -> None:
    markers = {
        "nx.json": "nx",
        "uv.lock": "uv",
    }
    for relative, technology in markers.items():
        path = root / relative
        if path.exists():
            evidence.append(_file(relative, path))
            evidence.append(_technology(technology, path, "marker file"))

    for pattern, technology in (
        ("next.config.*", "nextjs"),
        ("*.csproj", "dotnet"),
        ("*.tf", "terraform"),
    ):
        for path in sorted(root.glob(pattern)):
            evidence.append(_file(path.name, path))
            evidence.append(_technology(technology, path, "marker file"))


def _collect_compose_files(root: Path, evidence: list[StackEvidence]) -> None:
    if yaml is None:
        return
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        path = root / name
        if not path.exists():
            continue
        evidence.append(_file(name, path))
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        text = json.dumps(data).lower()
        if "postgres" in text:
            evidence.append(_technology("postgres", path, "compose service/image"))


def _add_dependency_evidence(
    evidence: list[StackEvidence],
    dependency: str,
    path: Path,
) -> None:
    evidence.append(
        StackEvidence(
            kind="dependency",
            value=dependency,
            source=str(path),
            location="dependency manifest",
        )
    )
    technology = PACKAGE_TECHNOLOGIES.get(normalize_evidence_value(dependency))
    if technology:
        evidence.append(_technology(technology, path, f"dependency {dependency}"))


def _file(value: str, path: Path) -> StackEvidence:
    return StackEvidence(kind="file", value=value, source=str(path), location="source tree")


def _technology(value: str, path: Path, location: str) -> StackEvidence:
    return StackEvidence(
        kind="technology",
        value=value,
        source=str(path),
        location=location,
    )


def _dedupe(evidence: list[StackEvidence]) -> list[StackEvidence]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[StackEvidence] = []
    for item in evidence:
        key = (item.kind, normalize_evidence_value(item.value), item.source, item.location)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
