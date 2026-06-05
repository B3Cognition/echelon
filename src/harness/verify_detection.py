"""Deterministic verify_command detection for harness initialization."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class VerifyDetectionResult:
    """A high-confidence verify command, or the reason none was selected."""

    command: str | None
    confidence: str
    evidence: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass(frozen=True)
class _Candidate:
    command: str
    evidence: str


_NODE_PLACEHOLDER_TEST_SNIPPETS = (
    "no test specified",
    "exit 1",
)


def detect_verify_command(repo_path: Path) -> VerifyDetectionResult:
    """Return one high-confidence verify_command for *repo_path*, or no guess.

    The detector intentionally prefers false negatives over false positives:
    if multiple ecosystems look equally plausible, the caller should ask the
    user to set ``verify_command`` manually.
    """
    repo = Path(repo_path)
    candidates: list[_Candidate] = []

    node = _detect_node(repo)
    if node is not None:
        candidates.append(node)

    python = _detect_python(repo)
    if python is not None:
        candidates.append(python)

    for detector in (_detect_go, _detect_rust, _detect_swift):
        candidate = detector(repo)
        if candidate is not None:
            candidates.append(candidate)

    if len(candidates) == 1:
        candidate = candidates[0]
        return VerifyDetectionResult(
            command=candidate.command,
            confidence="high",
            evidence=[candidate.evidence],
        )

    if len(candidates) > 1:
        return VerifyDetectionResult(
            command=None,
            confidence="ambiguous",
            evidence=[c.evidence for c in candidates],
            reason="multiple high-confidence candidates found; set verify_command manually",
        )

    return VerifyDetectionResult(
        command=None,
        confidence="none",
        reason="no high-confidence test runner detected",
    )


def _detect_node(repo: Path) -> _Candidate | None:
    package_json = repo / "package.json"
    if not package_json.exists():
        return None

    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return None

    test_script = scripts.get("test")
    if not isinstance(test_script, str) or not test_script.strip():
        return None

    lowered = test_script.lower()
    if all(snippet in lowered for snippet in _NODE_PLACEHOLDER_TEST_SNIPPETS):
        return None

    if (repo / "pnpm-lock.yaml").exists():
        command = "pnpm test"
    elif (repo / "yarn.lock").exists():
        command = "yarn test"
    else:
        command = "npm test"

    return _Candidate(command=command, evidence="package.json scripts.test")


def _detect_python(repo: Path) -> _Candidate | None:
    markers = [
        repo / "pyproject.toml",
        repo / "requirements.txt",
        repo / "requirements-dev.txt",
    ]
    marker_text = ""
    for marker in markers:
        if marker.exists():
            try:
                marker_text += "\n" + marker.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass

    has_pytest_marker = "pytest" in marker_text.lower()
    has_pytest_files = (
        any((repo / "tests").glob("**/test_*.py"))
        or any((repo / "tests").glob("**/*_test.py"))
        or any(repo.glob("test_*.py"))
        or any(repo.glob("*_test.py"))
    )
    if not has_pytest_marker and not has_pytest_files:
        return None

    command = "uv run pytest" if (repo / "uv.lock").exists() else "python -m pytest"
    return _Candidate(command=command, evidence="pytest marker")


def _detect_go(repo: Path) -> _Candidate | None:
    if (repo / "go.mod").exists():
        return _Candidate(command="go test ./...", evidence="go.mod")
    return None


def _detect_rust(repo: Path) -> _Candidate | None:
    if (repo / "Cargo.toml").exists():
        return _Candidate(command="cargo test", evidence="Cargo.toml")
    return None


def _detect_swift(repo: Path) -> _Candidate | None:
    root_package = repo / "Package.swift"
    if root_package.exists():
        return _Candidate(command="swift test", evidence="Package.swift")

    packages = sorted(repo.glob("**/Package.swift"), key=lambda p: (len(p.parts), str(p)))
    if len(packages) != 1:
        return None

    package_dir = packages[0].parent.relative_to(repo)
    return _Candidate(
        command=f"swift test --package-path {package_dir.as_posix()}",
        evidence=str(packages[0].relative_to(repo)),
    )
