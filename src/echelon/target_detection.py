from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re


DEFAULT_CONFIDENCE_THRESHOLD = 0.80


@dataclass(frozen=True)
class TargetCandidate:
    repo: str
    confidence: float
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TargetDetectionResult:
    recommended_target: str | None
    confidence: float
    decision: str
    candidates: list[TargetCandidate]


_PATH_RE = re.compile(
    r"`([^`]+\.[A-Za-z0-9]+)`|"
    r"((?:src|app|lib|packages|services|tests|__tests__)/[A-Za-z0-9_./-]+)"
)


def _candidate_repos(polyrepo_root: Path) -> list[Path]:
    repos: list[Path] = []
    for child in sorted(polyrepo_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name in {".git", ".specify", "specs", "runs", "knowledge-base"}:
            continue
        if (child / ".git").exists():
            repos.append(child)
    return repos


def _spec_text(spec_dir: Path) -> str:
    chunks: list[str] = []
    for name in ["spec.md", "plan.md", "tasks.md", "research.md"]:
        path = spec_dir / name
        if path.exists():
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))

    contracts = spec_dir / "contracts"
    if contracts.exists():
        for path in sorted(contracts.rglob("*.md")):
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def _referenced_paths(text: str) -> set[str]:
    paths: set[str] = set()
    for match in _PATH_RE.finditer(text):
        raw = match.group(1) or match.group(2)
        if raw:
            paths.add(raw.strip("/"))
    return paths


def detect_target(
    *,
    spec_dir: Path,
    polyrepo_root: Path,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> TargetDetectionResult:
    repos = _candidate_repos(polyrepo_root)
    if len(repos) <= 1:
        return TargetDetectionResult(None, 0.0, "not_polyrepo", [])

    text = _spec_text(spec_dir)
    lowered = text.lower()
    refs = _referenced_paths(text)
    scored: list[TargetCandidate] = []

    for repo in repos:
        points = 0
        evidence: list[str] = []

        if repo.name.lower() in lowered:
            points += 3
            evidence.append(f"spec artifacts mention repo name `{repo.name}`")

        package_json = repo / "package.json"
        if package_json.exists():
            pkg = package_json.read_text(encoding="utf-8", errors="ignore").lower()
            for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", repo.name.lower()):
                if token in lowered or token in pkg:
                    points += 1
                    evidence.append(f"package metadata aligns with `{token}`")

        for ref in sorted(refs):
            if (repo / ref).exists():
                points += 8
                evidence.append(f"referenced path exists: `{ref}`")

        confidence = min(1.0, points / 10.0)
        scored.append(
            TargetCandidate(repo=repo.name, confidence=confidence, evidence=evidence)
        )

    scored.sort(key=lambda item: item.confidence, reverse=True)
    top = scored[0]
    second = scored[1] if len(scored) > 1 else None

    if top.confidence >= threshold and (
        second is None or top.confidence - second.confidence >= 0.10
    ):
        return TargetDetectionResult(top.repo, top.confidence, "recommend", scored)

    return TargetDetectionResult(None, min(top.confidence, threshold - 0.01), "ambiguous", scored)
