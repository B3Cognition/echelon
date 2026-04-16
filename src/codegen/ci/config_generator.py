"""
config_generator.py — Tier 2 CI Config Generator.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

T-024: Generate GitHub Actions YAML for Tier 2 integration test gate.

Generated workflow includes:
  - build      — compile / type-check
  - test        — unit + integration tests
  - lint         — static analysis
  - coverage   — coverage report

FR-IMPL-007: CI config generated for every task regardless of Tier 1 status.
FR-DELIVER-003: CI artifacts captured and shipped in delivery package.
FR-DELIVER-004: CI YAML is part of delivery package.
NFR-PORT-003: --ci-target docker generates Dockerfile for local execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Language-specific configuration
# ---------------------------------------------------------------------------

_LANGUAGE_CONFIG: dict[str, dict] = {
    "python": {
        "setup_action": "actions/setup-python@v5",
        "version_key": "python-version",
        "default_version": "3.11",
        "build_cmd": "pip install -e '.[dev]'",
        "test_cmd": "pytest tests/ --tb=short --json-report --json-report-file=test-report.json",
        "lint_cmd": "ruff check . && mypy .",
        "coverage_cmd": "pytest --cov=src --cov-report=xml:coverage.xml tests/",
        "cache_key": "pip",
        "cache_path": "~/.cache/pip",
    },
    "typescript": {
        "setup_action": "actions/setup-node@v4",
        "version_key": "node-version",
        "default_version": "20",
        "build_cmd": "npm ci && npm run build",
        "test_cmd": "npx vitest run --reporter=json --outputFile=test-report.json",
        "lint_cmd": "npx eslint . --ext .ts,.tsx",
        "coverage_cmd": "npx vitest run --coverage",
        "cache_key": "npm",
        "cache_path": "~/.npm",
    },
    "javascript": {
        "setup_action": "actions/setup-node@v4",
        "version_key": "node-version",
        "default_version": "20",
        "build_cmd": "npm ci",
        "test_cmd": "npx jest --json --outputFile=test-report.json",
        "lint_cmd": "npx eslint . --ext .js",
        "coverage_cmd": "npx jest --coverage",
        "cache_key": "npm",
        "cache_path": "~/.npm",
    },
    "go": {
        "setup_action": "actions/setup-go@v5",
        "version_key": "go-version",
        "default_version": "1.22",
        "build_cmd": "go build ./...",
        "test_cmd": "go test -v -json ./... | tee test-report.json",
        "lint_cmd": "golangci-lint run ./...",
        "coverage_cmd": "go test -coverprofile=coverage.out ./... && go tool cover -html=coverage.out -o coverage.html",
        "cache_key": "go",
        "cache_path": "~/go/pkg/mod",
    },
    "java": {
        "setup_action": "actions/setup-java@v4",
        "version_key": "java-version",
        "default_version": "21",
        "extra_setup": "distribution: 'temurin'",
        "build_cmd": "mvn compile -B",
        "test_cmd": "mvn test -B",
        "lint_cmd": "mvn checkstyle:check -B",
        "coverage_cmd": "mvn jacoco:report -B",
        "cache_key": "maven",
        "cache_path": "~/.m2",
    },
}

# Dockerfile templates per language
_DOCKERFILE_TEMPLATES: dict[str, str] = {
    "python": """FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -e '.[dev]'
CMD ["pytest", "tests/", "--tb=short"]
""",
    "typescript": """FROM node:20-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
CMD ["npx", "vitest", "run"]
""",
    "javascript": """FROM node:20-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
CMD ["npx", "jest"]
""",
    "go": """FROM golang:1.22-alpine
WORKDIR /app
COPY . .
RUN go mod download
CMD ["go", "test", "-v", "./..."]
""",
    "java": """FROM eclipse-temurin:21-jdk
WORKDIR /app
COPY . .
RUN mvn dependency:go-offline -B
CMD ["mvn", "test", "-B"]
""",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CIConfig:
    """
    Generated CI configuration artifact.

    FR-IMPL-007: CI YAML is generated for every task.
    FR-DELIVER-003/004: Part of delivery package.
    """
    task_id: str
    language: str
    workflow_path: Path              # e.g. .github/workflows/codegen.yml
    workflow_content: str            # YAML text
    dockerfile_path: Optional[Path] = None
    dockerfile_content: Optional[str] = None
    jobs: list[str] = field(default_factory=list)   # job names present in YAML

    def to_wme_dict(self) -> dict:
        """Serialize as SOAR WME."""
        return {
            "wme_type": "ci-config",
            "task-id": self.task_id,
            "language": self.language,
            "workflow-path": str(self.workflow_path),
            "jobs": self.jobs,
            "has-dockerfile": self.dockerfile_path is not None,
            "preference": "best",   # INV-003
        }


# ---------------------------------------------------------------------------
# YAML generation helpers
# ---------------------------------------------------------------------------

def _indent(text: str, n: int) -> str:
    """Indent every non-empty line by n spaces."""
    prefix = " " * n
    return "\n".join(prefix + line if line.strip() else line for line in text.splitlines())


def _build_job(
    job_id: str,
    job_name: str,
    run_cmd: str,
    setup_block: str,
    needs: list[str] | None = None,
    env_block: str = "",
) -> str:
    needs_line = f"\n    needs: [{', '.join(needs)}]" if needs else ""
    env_section = f"\n    env:\n{_indent(env_block, 6)}" if env_block else ""
    return f"""
  {job_id}:
    name: {job_name}
    runs-on: ubuntu-latest{needs_line}{env_section}
    steps:
{_indent(setup_block, 6)}
      - name: Run {job_name}
        run: {run_cmd}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class CIConfigGenerator:
    """
    Generates GitHub Actions YAML for Tier 2 test gate.

    FR-IMPL-007: Always generated, regardless of Tier 1 status.
    NFR-PORT-003: Optional Dockerfile for --ci-target docker.
    """

    def generate(
        self,
        task_id: str,
        language: str,
        project_name: str = "codegen",
        branch: str = "main",
        language_version: Optional[str] = None,
        include_dockerfile: bool = False,
        output_dir: Optional[Path] = None,
    ) -> CIConfig:
        """
        Generate a complete CI workflow YAML.

        Args:
            task_id:            Task identifier.
            language:           Target language.
            project_name:       Used in workflow name.
            branch:             Branch to trigger CI on.
            language_version:   Override default runtime version.
            include_dockerfile: If True, generate Dockerfile (NFR-PORT-003).
            output_dir:         Root directory for output files.

        Returns:
            CIConfig with workflow content and file path.
        """
        lang = language.lower().strip()
        if lang not in _LANGUAGE_CONFIG:
            raise ValueError(
                f"Unsupported language '{language}'. "
                f"Supported: {sorted(_LANGUAGE_CONFIG)}"
            )

        cfg = _LANGUAGE_CONFIG[lang]
        version = language_version or cfg["default_version"]
        root = output_dir or Path.cwd()

        # Build common checkout + setup steps
        extra_setup = f"\n          {cfg['extra_setup']}" if cfg.get("extra_setup") else ""
        setup_block = f"""- uses: actions/checkout@v4
      - uses: {cfg['setup_action']}
        with:
          {cfg['version_key']}: '{version}'{extra_setup}
          cache: '{cfg['cache_key']}'
"""

        build_job = _build_job("build", "Build", cfg["build_cmd"], setup_block)
        test_job = _build_job(
            "test", "Test", cfg["test_cmd"], setup_block, needs=["build"],
        )
        lint_job = _build_job(
            "lint", "Lint", cfg["lint_cmd"], setup_block, needs=["build"],
        )
        coverage_job = _build_job(
            "coverage", "Coverage", cfg["coverage_cmd"], setup_block, needs=["test"],
        )

        workflow = f"""# Generated by SOAR codegen — T-{task_id}
# FR-IMPL-007: Tier 2 CI gate
name: {project_name}-codegen

on:
  push:
    branches: ["{branch}"]
  pull_request:
    branches: ["{branch}"]

jobs:{build_job}{test_job}{lint_job}{coverage_job}
"""

        workflow_path = root / ".github" / "workflows" / "codegen.yml"
        jobs = ["build", "test", "lint", "coverage"]

        # Optional Dockerfile (NFR-PORT-003)
        dockerfile_path = None
        dockerfile_content = None
        if include_dockerfile:
            dockerfile_content = _DOCKERFILE_TEMPLATES.get(lang, "")
            dockerfile_path = root / "Dockerfile.codegen"

        return CIConfig(
            task_id=task_id,
            language=lang,
            workflow_path=workflow_path,
            workflow_content=workflow,
            dockerfile_path=dockerfile_path,
            dockerfile_content=dockerfile_content,
            jobs=jobs,
        )

    def write(self, ci_config: CIConfig) -> list[Path]:
        """Write CI artifacts to disk. Returns list of written paths."""
        written: list[Path] = []

        ci_config.workflow_path.parent.mkdir(parents=True, exist_ok=True)
        ci_config.workflow_path.write_text(ci_config.workflow_content, encoding="utf-8")
        written.append(ci_config.workflow_path)

        if ci_config.dockerfile_path and ci_config.dockerfile_content:
            ci_config.dockerfile_path.write_text(ci_config.dockerfile_content, encoding="utf-8")
            written.append(ci_config.dockerfile_path)

        return written


def validate_yaml_structure(content: str) -> list[str]:
    """
    Lightweight structural YAML validation (no external dependency).

    Checks:
      - Required top-level keys: name, on, jobs
      - Required job names: build, test, lint, coverage
      - No tabs (YAML prohibits tabs as indentation)

    Returns list of error strings (empty = valid).
    """
    errors: list[str] = []

    if "\t" in content:
        errors.append("YAML must not contain tab characters as indentation.")

    for key in ("name:", "on:", "jobs:"):
        if key not in content:
            errors.append(f"Missing required top-level key: '{key}'")

    for job in ("build:", "test:", "lint:", "coverage:"):
        if job not in content:
            errors.append(f"Missing required job: '{job}'")

    return errors
