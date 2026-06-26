"""Deterministic secret scanning for harness GitOps gates."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class SecretRule:
    """High-confidence secret pattern."""

    rule_id: str
    description: str
    pattern: re.Pattern[str]
    severity: str = "high"


@dataclass(frozen=True)
class SecretFinding:
    """A secret-like value found in a file."""

    rule_id: str
    description: str
    path: str
    line: int
    column: int
    severity: str


@dataclass(frozen=True)
class SecretScanResult:
    """Result of scanning one or more files."""

    findings: list[SecretFinding]

    @property
    def ok(self) -> bool:
        return not self.findings

    def format_summary(self, limit: int = 10) -> str:
        """Return a sanitized summary that never includes matched secret text."""
        if not self.findings:
            return "no secret findings"

        visible = self.findings[:limit]
        lines = [
            (
                f"{finding.path}:{finding.line}:{finding.column} "
                f"{finding.rule_id} ({finding.severity})"
            )
            for finding in visible
        ]
        hidden_count = len(self.findings) - len(visible)
        if hidden_count > 0:
            lines.append(f"... and {hidden_count} more finding(s)")
        return "; ".join(lines)


RULES: tuple[SecretRule, ...] = (
    SecretRule(
        "github-token",
        "GitHub token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{36,255}\b"),
    ),
    SecretRule(
        "gitlab-token",
        "GitLab personal access token",
        re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    ),
    SecretRule(
        "aws-access-key",
        "AWS access key id",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ),
    SecretRule(
        "slack-token",
        "Slack token",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    ),
    SecretRule(
        "private-key",
        "Private key header",
        re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    ),
)


def scan_text(text: str, path: str = "<text>") -> list[SecretFinding]:
    """Scan text for high-confidence secret patterns."""
    findings: list[SecretFinding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule in RULES:
            match = rule.pattern.search(line)
            if match:
                findings.append(
                    SecretFinding(
                        rule_id=rule.rule_id,
                        description=rule.description,
                        path=path,
                        line=line_number,
                        column=match.start() + 1,
                        severity=rule.severity,
                    )
                )
    return findings


def scan_paths(paths: Iterable[str | Path]) -> SecretScanResult:
    """Scan readable text files and skip missing or binary files."""
    findings: list[SecretFinding] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_file():
            continue

        content = path.read_bytes()
        if b"\x00" in content:
            continue

        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue

        findings.extend(scan_text(text, path=str(path)))

    return SecretScanResult(findings)


def scan_git_staged(worktree_path: str | Path) -> SecretScanResult:
    """Scan files currently staged for commit in a git worktree."""
    worktree = Path(worktree_path)
    result = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--name-only",
            "-z",
            "--diff-filter=ACMR",
        ],
        cwd=str(worktree),
        capture_output=True,
        check=True,
    )
    staged_paths = [
        worktree / entry.decode("utf-8")
        for entry in result.stdout.split(b"\x00")
        if entry
    ]
    return scan_paths(staged_paths)
