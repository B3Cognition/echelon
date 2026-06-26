"""Repository dependency-policy checks migrated from shell tests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


BANNED_DEPENDENCIES = ("jq", "yq", "xmlstarlet", "xsltproc")
BANNED_SCRIPT_COMMANDS = (
    "curl",
    "wget",
    "npm",
    "pip",
    "apt",
    "yum",
    "brew",
    "docker",
    "yq",
)


@dataclass(frozen=True)
class DependencyFinding:
    path: Path
    name: str
    line: int


def find_banned_dependency_declarations(root: Path) -> list[DependencyFinding]:
    """Return banned tool dependencies declared in Python dependency files."""
    files = [root / "pyproject.toml", *sorted(root.glob("requirements*.txt"))]
    findings: list[DependencyFinding] = []
    pattern = re.compile(
        r"^\s*[\"']?(?P<name>" + "|".join(map(re.escape, BANNED_DEPENDENCIES)) + r")\b",
        re.IGNORECASE,
    )

    for path in files:
        if not path.is_file():
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            match = pattern.search(line)
            if match:
                findings.append(
                    DependencyFinding(
                        path=path,
                        name=match.group("name"),
                        line=lineno,
                    )
                )
    return findings


def find_banned_script_invocations(paths: list[Path]) -> list[DependencyFinding]:
    """Return banned command names found as whole words in shell scripts."""
    findings: list[DependencyFinding] = []

    for path in paths:
        if not path.is_file():
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            for command in BANNED_SCRIPT_COMMANDS:
                if re.search(rf"\b{re.escape(command)}\b", line):
                    findings.append(DependencyFinding(path=path, name=command, line=lineno))
    return findings
