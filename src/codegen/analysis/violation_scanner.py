"""
violation_scanner.py — Static analysis scanner that maps tool output to CQ-ISC rule IDs.
Spec 008: SOAR-Powered Claude Code Software Development Agent

Runs ruff, mypy, eslint, and semgrep (where available) and maps error codes to
CQ-ISC rule IDs so violations can be injected into SOAR as code-violation WMEs.

Tool mapping:
  Python  → ruff (STRUCT/SEC/QUAL rules), mypy (TYPE rules)
  TypeScript → eslint (REACT + TS rules)
  All     → semgrep for SEC rules (optional, skipped gracefully if absent)

INV-002: Violations ONLY block via SOAR prohibit; this module only reports.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CQ-ISC rule mapping from ruff error codes
# ---------------------------------------------------------------------------

# Maps ruff error-code prefix/exact → (cq_isc_id, constraint_class, severity)
_RUFF_CODE_MAP: dict[str, tuple[str, str, str]] = {
    "S105": ("CQ-ISC-SEC-001", "SECURITY", "critical"),
    "S106": ("CQ-ISC-SEC-001", "SECURITY", "critical"),
    "S107": ("CQ-ISC-SEC-001", "SECURITY", "critical"),
    "S608": ("CQ-ISC-SEC-002", "SECURITY", "critical"),
    "S307": ("CQ-ISC-SEC-003", "SECURITY", "high"),
    "C901": ("CQ-ISC-STRUCT-002", "STRUCTURAL", "medium"),
    "PLR0913": ("CQ-ISC-STRUCT-004", "STRUCTURAL", "medium"),
    "E501": ("CQ-ISC-STRUCT-005", "STRUCTURAL", "low"),
    "T201": ("CQ-ISC-QUAL-001", "QUALITY", "low"),
    "T202": ("CQ-ISC-QUAL-001", "QUALITY", "low"),
    "F401": ("CQ-ISC-QUAL-004", "QUALITY", "low"),
    "W0101": ("CQ-ISC-QUAL-004", "QUALITY", "low"),
    "PLR2004": ("CQ-ISC-QUAL-003", "QUALITY", "low"),
}

# Semgrep rule IDs → CQ-ISC mapping
_SEMGREP_RULE_MAP: dict[str, tuple[str, str, str]] = {
    "hardcoded-secret": ("CQ-ISC-SEC-001", "SECURITY", "critical"),
    "secrets": ("CQ-ISC-SEC-001", "SECURITY", "critical"),
    "formatted-sql-query": ("CQ-ISC-SEC-002", "SECURITY", "critical"),
    "sql-injection": ("CQ-ISC-SEC-002", "SECURITY", "critical"),
    "eval": ("CQ-ISC-SEC-003", "SECURITY", "high"),
    "exec": ("CQ-ISC-SEC-003", "SECURITY", "high"),
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CqIscViolation:
    cq_isc_id: str           # e.g. "CQ-ISC-SEC-001"
    constraint_class: str    # SECURITY | STRUCTURAL | TEST | QUALITY
    file: str
    line: int
    column: int
    message: str
    severity: str            # critical | high | medium | low
    tool: str                # ruff | mypy | eslint | semgrep
    status: str = "confirmed-failing"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cq_isc_id": self.cq_isc_id,
            "constraint_class": self.constraint_class,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "message": self.message,
            "severity": self.severity,
            "tool": self.tool,
            "status": self.status,
        }


# ---------------------------------------------------------------------------
# ViolationScanner
# ---------------------------------------------------------------------------

class ViolationScanner:
    """
    Runs static analysis tools on source files and maps output to CQ-ISC violations.

    Each violation maps to exactly one CQ-ISC rule ID (e.g. CQ-ISC-SEC-001).
    Violations are always returned with status="confirmed-failing".

    If a tool is not on PATH it is skipped gracefully — no exception is raised.
    """

    def scan(
        self,
        files: list[Path],
        language: str,
        working_dir: Path | None = None,
    ) -> list[CqIscViolation]:
        """
        Run all applicable tools and return CQ-ISC violations.

        Args:
            files: Source files to analyse.
            language: Detected language ("python" | "typescript" | "javascript" | …).
            working_dir: Optional CWD override for subprocess calls.

        Returns:
            List of CqIscViolation instances, all with status="confirmed-failing".
        """
        if not files:
            return []

        violations: list[CqIscViolation] = []
        lang = language.lower()

        if lang == "python":
            violations.extend(self._run_ruff(files, working_dir))
            violations.extend(self._run_mypy(files, working_dir))

        if lang in ("typescript", "javascript", "tsx", "jsx"):
            violations.extend(self._run_eslint(files, working_dir))

        # semgrep for SEC rules — all languages if available
        violations.extend(self._run_semgrep(files, working_dir))

        return violations

    # ------------------------------------------------------------------
    # Tool runners
    # ------------------------------------------------------------------

    def _run_ruff(
        self,
        files: list[Path],
        working_dir: Path | None,
    ) -> list[CqIscViolation]:
        """Run ruff and map error codes to CQ-ISC IDs."""
        if not shutil.which("ruff"):
            logger.debug("[ViolationScanner] ruff not on PATH — skipping")
            return []

        cmd = [
            "ruff", "check",
            "--select", "S,T2,PLR,C9,F,E501,W",
            "--output-format", "json",
            "--",
            *[str(f) for f in files],
        ]
        try:
            result = subprocess.run(
                cmd,
                shell=False,
                timeout=30,
                capture_output=True,
                text=True,
                cwd=working_dir,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("[ViolationScanner] ruff failed: %s", exc)
            return []

        if not result.stdout.strip():
            return []

        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            logger.warning("[ViolationScanner] ruff JSON parse error: %s", exc)
            return []

        violations: list[CqIscViolation] = []
        for item in raw:
            code = item.get("code", "")
            mapped = _RUFF_CODE_MAP.get(code)
            if mapped is None:
                continue
            cq_isc_id, constraint_class, severity = mapped
            loc = item.get("location", {})
            violations.append(CqIscViolation(
                cq_isc_id=cq_isc_id,
                constraint_class=constraint_class,
                file=item.get("filename", ""),
                line=loc.get("row", 0),
                column=loc.get("column", 0),
                message=item.get("message", ""),
                severity=severity,
                tool="ruff",
                status="confirmed-failing",
            ))
        return violations

    def _run_mypy(
        self,
        files: list[Path],
        working_dir: Path | None,
    ) -> list[CqIscViolation]:
        """Run mypy and map type errors to CQ-ISC-TYPE-001 where applicable."""
        if not shutil.which("mypy"):
            logger.debug("[ViolationScanner] mypy not on PATH — skipping")
            return []

        cmd = [
            "mypy",
            "--no-error-summary",
            "--",
            *[str(f) for f in files],
        ]
        try:
            result = subprocess.run(
                cmd,
                shell=False,
                timeout=30,
                capture_output=True,
                text=True,
                cwd=working_dir,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("[ViolationScanner] mypy failed: %s", exc)
            return []

        violations: list[CqIscViolation] = []
        for line in result.stdout.splitlines():
            # mypy output: path:line: error: message  [error-code]
            if ": error:" not in line:
                continue
            parts = line.split(":", 3)
            if len(parts) < 4:
                continue
            try:
                file_path = parts[0].strip()
                line_no = int(parts[1].strip()) if parts[1].strip().isdigit() else 0
                message = parts[3].strip() if len(parts) > 3 else ""
            except (ValueError, IndexError):
                continue
            violations.append(CqIscViolation(
                cq_isc_id="CQ-ISC-QUAL-002",
                constraint_class="QUALITY",
                file=file_path,
                line=line_no,
                column=0,
                message=message,
                severity="medium",
                tool="mypy",
                status="confirmed-failing",
            ))
        return violations

    def _run_eslint(
        self,
        files: list[Path],
        working_dir: Path | None,
    ) -> list[CqIscViolation]:
        """Run eslint with JSON formatter and map to CQ-ISC IDs."""
        if not shutil.which("eslint"):
            logger.debug("[ViolationScanner] eslint not on PATH — skipping")
            return []

        cmd = [
            "eslint",
            "--format", "json",
            "--",
            *[str(f) for f in files],
        ]
        try:
            result = subprocess.run(
                cmd,
                shell=False,
                timeout=30,
                capture_output=True,
                text=True,
                cwd=working_dir,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("[ViolationScanner] eslint failed: %s", exc)
            return []

        if not result.stdout.strip():
            return []

        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            logger.warning("[ViolationScanner] eslint JSON parse error: %s", exc)
            return []

        violations: list[CqIscViolation] = []
        for file_entry in raw:
            file_path = file_entry.get("filePath", "")
            for msg in file_entry.get("messages", []):
                rule_id = msg.get("ruleId") or ""
                cq_isc_id, constraint_class, severity = _map_eslint_rule(rule_id)
                if cq_isc_id is None:
                    continue
                violations.append(CqIscViolation(
                    cq_isc_id=cq_isc_id,
                    constraint_class=constraint_class,
                    file=file_path,
                    line=msg.get("line", 0),
                    column=msg.get("column", 0),
                    message=msg.get("message", ""),
                    severity=severity,
                    tool="eslint",
                    status="confirmed-failing",
                ))
        return violations

    def _run_semgrep(
        self,
        files: list[Path],
        working_dir: Path | None,
    ) -> list[CqIscViolation]:
        """Run semgrep for SEC rules. Skip gracefully if not available."""
        if not shutil.which("semgrep"):
            logger.debug("[ViolationScanner] semgrep not on PATH — skipping")
            return []

        cmd = [
            "semgrep",
            "--config", "auto",
            "--json",
            "--",
            *[str(f) for f in files],
        ]
        try:
            result = subprocess.run(
                cmd,
                shell=False,
                timeout=30,
                capture_output=True,
                text=True,
                cwd=working_dir,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("[ViolationScanner] semgrep failed: %s", exc)
            return []

        if not result.stdout.strip():
            return []

        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            logger.warning("[ViolationScanner] semgrep JSON parse error: %s", exc)
            return []

        violations: list[CqIscViolation] = []
        if not isinstance(raw, dict):
            logger.warning("[ViolationScanner] semgrep output is not a dict — skipping")
            return []
        for finding in raw.get("results", []):
            check_id = finding.get("check_id", "").lower()
            cq_isc_id, constraint_class, severity = _map_semgrep_rule(check_id)
            if cq_isc_id is None:
                continue
            start = finding.get("start", {})
            violations.append(CqIscViolation(
                cq_isc_id=cq_isc_id,
                constraint_class=constraint_class,
                file=finding.get("path", ""),
                line=start.get("line", 0),
                column=start.get("col", 0),
                message=finding.get("extra", {}).get("message", ""),
                severity=severity,
                tool="semgrep",
                status="confirmed-failing",
            ))
        return violations


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------

def _map_eslint_rule(rule_id: str) -> tuple[str | None, str, str]:
    """Map an eslint rule ID to (cq_isc_id, constraint_class, severity)."""
    r = rule_id.lower()
    if any(k in r for k in ("no-eval", "no-implied-eval")):
        return "CQ-ISC-SEC-003", "SECURITY", "high"
    if any(k in r for k in ("no-secrets", "detect-secrets", "no-hardcoded")):
        return "CQ-ISC-SEC-001", "SECURITY", "critical"
    if "no-sql-injection" in r or "sql-injection" in r:
        return "CQ-ISC-SEC-002", "SECURITY", "critical"
    if any(k in r for k in ("react-hooks", "rules-of-hooks", "exhaustive-deps")):
        return "CQ-ISC-STRUCT-003", "STRUCTURAL", "high"
    if "no-unused-vars" in r or "no-unused" in r:
        return "CQ-ISC-QUAL-004", "QUALITY", "low"
    if "no-console" in r:
        return "CQ-ISC-QUAL-001", "QUALITY", "low"
    if any(k in r for k in ("@typescript-eslint/no-explicit-any", "no-explicit-any")):
        return "CQ-ISC-QUAL-002", "QUALITY", "medium"
    # Unknown eslint rule — skip
    return None, "", ""


def _map_semgrep_rule(check_id: str) -> tuple[str | None, str, str]:
    """Map a semgrep check_id to (cq_isc_id, constraint_class, severity)."""
    for keyword, mapping in _SEMGREP_RULE_MAP.items():
        if keyword in check_id:
            return mapping
    return None, "", ""
