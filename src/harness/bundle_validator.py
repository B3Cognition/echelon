"""Validate Echelon's canonical Prosaic prose and runtime bundles."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from harness.prompt_companions import prompt_companion_references
from harness.prompt_markdown import read_prompt_markdown
from harness.workflow_validator import validate_workflow_definition


@dataclass(frozen=True)
class BundleValidationReport:
    repository_root: Path
    prosaic_root: Path
    runtime_root: Path
    checks: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def format(self) -> str:
        lines = [
            f"Repository root: {self.repository_root}",
            f"Prosaic root: {self.prosaic_root}",
            f"Runtime root: {self.runtime_root}",
            "",
            *[f"PASS: {check}" for check in self.checks],
        ]
        if self.errors:
            lines.extend(["", *[f"ERROR: {error}" for error in self.errors]])
            lines.append("")
            lines.append(f"Bundle validation failed: {len(self.errors)} error(s)")
        else:
            lines.extend(["", f"Bundle validation passed: {len(self.checks)} checks"])
        return "\n".join(lines)


def validate_bundle(input_root: Path) -> BundleValidationReport:
    repository_root = _repository_root(input_root)
    prosaic_root = repository_root / "prosaic"
    runtime_root = repository_root / "runtime"
    checks: list[str] = []
    errors: list[str] = []

    commands = _validate_prompt_directory(
        prosaic_root / "commands",
        label="command",
        checks=checks,
        errors=errors,
    )
    subagents = _validate_prompt_directory(
        prosaic_root / "subagents",
        label="subagent",
        checks=checks,
        errors=errors,
    )
    _validate_companion_references(prosaic_root, runtime_root, checks, errors)
    _validate_runtime_yaml(runtime_root, checks, errors)
    _validate_runtime_scripts(runtime_root, checks, errors)
    _validate_workflow(runtime_root, subagents, checks, errors)

    if commands:
        checks.append(f"{len(commands)} canonical Prosaic commands")
    if subagents:
        checks.append(f"{len(subagents)} canonical Prosaic subagents")

    return BundleValidationReport(
        repository_root=repository_root,
        prosaic_root=prosaic_root,
        runtime_root=runtime_root,
        checks=tuple(checks),
        errors=tuple(errors),
    )


def _repository_root(input_root: Path) -> Path:
    candidate = input_root.expanduser().absolute()
    if candidate.name in {"prosaic", "runtime"}:
        candidate = candidate.parent
    return candidate


def _validate_prompt_directory(
    directory: Path,
    *,
    label: str,
    checks: list[str],
    errors: list[str],
) -> set[str]:
    if not directory.is_dir():
        errors.append(f"missing {label} directory: {directory}")
        return set()
    paths = sorted(directory.glob("echelon.*.md"))
    if not paths:
        errors.append(f"no canonical {label} artifacts found in {directory}")
        return set()
    identities: set[str] = set()
    for path in paths:
        artifact = read_prompt_markdown(path)
        expected = path.stem
        name = artifact.metadata.get("name")
        if name != expected:
            errors.append(f"{path}: frontmatter name {name!r} does not match {expected!r}")
        if not artifact.body.strip():
            errors.append(f"{path}: prompt body is empty")
        identities.add(expected)
    checks.append(f"{label} frontmatter and prompt bodies are valid")
    return identities


def _validate_companion_references(
    prosaic_root: Path,
    runtime_root: Path,
    checks: list[str],
    errors: list[str],
) -> None:
    missing: set[str] = set()
    for artifact in prosaic_root.rglob("*.md") if prosaic_root.is_dir() else ():
        body = artifact.read_text(encoding="utf-8")
        for reference in prompt_companion_references(body):
            roots = (
                (runtime_root, prosaic_root)
                if reference.startswith("workflow/")
                else (prosaic_root, runtime_root)
            )
            if not any((root / reference).is_file() for root in roots):
                missing.add(reference)
    if missing:
        errors.extend(
            f"missing Prosaic companion resource: {reference}"
            for reference in sorted(missing)
        )
    else:
        checks.append("all Prosaic companion Markdown references resolve")


def _validate_runtime_yaml(
    runtime_root: Path,
    checks: list[str],
    errors: list[str],
) -> None:
    required = (
        "config-template.yml",
        "echelon-config.yml",
        "workflow/definition.yaml",
        "workflow/journal-entry-types.yaml",
    )
    for relative in required:
        path = runtime_root / relative
        if not path.is_file():
            errors.append(f"missing runtime YAML: {path}")
            continue
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"invalid runtime YAML {path}: {exc}")
    if not any(
        error.startswith(("missing runtime YAML", "invalid runtime YAML"))
        for error in errors
    ):
        checks.append("required runtime YAML is valid")


def _validate_runtime_scripts(
    runtime_root: Path,
    checks: list[str],
    errors: list[str],
) -> None:
    required = (
        "scripts/bash/detect-project.sh",
        "scripts/bash/endocrine.sh",
        "scripts/bash/finalize-run.sh",
        "scripts/bash/pre-dispatch-gate.sh",
        "scripts/bash/post-execution-audit.sh",
        "scripts/bash/setup-worktree.sh",
    )
    for relative in required:
        path = runtime_root / relative
        if not path.is_file():
            errors.append(f"missing runtime script: {path}")
        elif not os.access(path, os.X_OK):
            errors.append(f"runtime entrypoint is not executable: {path}")
    if not any(error.startswith(("missing runtime script", "runtime entrypoint")) for error in errors):
        checks.append("required runtime script entrypoints are executable")


def _validate_workflow(
    runtime_root: Path,
    subagents: set[str],
    checks: list[str],
    errors: list[str],
) -> None:
    definition = runtime_root / "workflow" / "definition.yaml"
    if not definition.is_file():
        return
    report = validate_workflow_definition(definition_path=definition)
    if report.ok:
        checks.append("workflow definition contract is valid")
    else:
        errors.extend(issue.message for issue in report.issues)
        return

    data = yaml.safe_load(definition.read_text(encoding="utf-8")) or {}
    referenced = _workflow_agent_ids(data)
    missing = referenced - subagents
    if missing:
        errors.extend(
            f"workflow agent has no Prosaic subagent: {agent}"
            for agent in sorted(missing)
        )
    else:
        checks.append("workflow agents resolve to canonical Prosaic subagents")


def _workflow_agent_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        agent = value.get("agent")
        if isinstance(agent, str) and agent.startswith("echelon."):
            found.add(agent.split()[0])
        agents = value.get("agents")
        if isinstance(agents, list):
            for entry in agents:
                if isinstance(entry, dict):
                    identity = entry.get("id")
                    if isinstance(identity, str) and identity.startswith("echelon."):
                        found.add(identity.split()[0])
        for child in value.values():
            found.update(_workflow_agent_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_workflow_agent_ids(child))
    return found


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    report = validate_bundle(arguments.root)
    print(report.format())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
