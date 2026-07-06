from __future__ import annotations

import re
from pathlib import Path

from harness.stacks.evidence import StackEvidence


KNOWN_ARTIFACT_NAMES = {
    "overview.md",
    "constitution.md",
    "migration-strategy.md",
    "gap-analysis.md",
    "validation-report.md",
}

TECHNOLOGY_PATTERNS = {
    "react": [r"\breact\b"],
    "typescript": [r"\btypescript\b"],
    "nextjs": [r"\bnext\.?js\b"],
    "nx": [r"\bnx\b"],
    "playbook": [r"\bplaybook\b", r"fet-frontend-libs"],
    "nestjs": [r"\bnest\.?js\b"],
    "postgres": [r"\bpostgres(?:ql)?\b"],
    "dotnet": [r"\b\.net\b", r"\bdotnet\b"],
    "terraform": [r"\bterraform\b"],
    "argocd": [r"\bargocd\b", r"\bargo cd\b"],
    "kubernetes": [r"\bkubernetes\b", r"\bk8s\b"],
    "fastapi": [r"\bfastapi\b"],
}


def detect_re_artifacts(artifact_roots: list[Path]) -> list[StackEvidence]:
    evidence: list[StackEvidence] = []
    for root in artifact_roots:
        if not root.exists():
            continue
        for path in _artifact_files(root):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            evidence.extend(_evidence_from_text(path, text))
    return _dedupe(evidence)


def _artifact_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    known = [root / name for name in sorted(KNOWN_ARTIFACT_NAMES) if (root / name).exists()]
    adrs = sorted((root / "adrs").glob("*.md")) if (root / "adrs").is_dir() else []
    if known or adrs:
        return [*known, *adrs]
    return sorted(root.glob("*.md"))


def _evidence_from_text(path: Path, text: str) -> list[StackEvidence]:
    evidence: list[StackEvidence] = []
    lower_text = text.lower()
    for technology, patterns in TECHNOLOGY_PATTERNS.items():
        if any(re.search(pattern, lower_text) for pattern in patterns):
            evidence.append(
                StackEvidence(
                    kind="technology",
                    value=technology,
                    source=str(path),
                    location="markdown artifact",
                )
            )
    if "playbook" in lower_text or "fet-frontend-libs" in lower_text:
        evidence.append(
            StackEvidence(
                kind="dependency",
                value="@statsperform/react-playbook",
                source=str(path),
                location="markdown artifact",
            )
        )
    if _target_stack_unresolved(lower_text):
        evidence.append(
            StackEvidence(
                kind="decision",
                value="target-stack-unresolved",
                source=str(path),
                location="markdown artifact",
            )
        )
    return evidence


def _target_stack_unresolved(text: str) -> bool:
    target_near_uncertainty = re.search(
        r"target stack.{0,120}(requires?|needed|human input|unresolved|tbd|placeholder)",
        text,
        flags=re.DOTALL,
    )
    uncertainty_near_target = re.search(
        r"(requires?|needed|human input|unresolved|tbd|placeholder).{0,120}target stack",
        text,
        flags=re.DOTALL,
    )
    return bool(target_near_uncertainty or uncertainty_near_target)


def _dedupe(evidence: list[StackEvidence]) -> list[StackEvidence]:
    seen: set[tuple[str, str, str]] = set()
    result: list[StackEvidence] = []
    for item in evidence:
        key = (item.kind, item.value.lower(), item.source)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
