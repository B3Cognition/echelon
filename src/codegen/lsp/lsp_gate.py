"""
lsp_gate.py — F1 LSP Pre-Flight Gate (Tier 0 Gate).
Spec 018 T-003: LspGate core module.

Design (ADR-001, contract: lsp_gate.md):
  - Invoked before the TEST phase; does NOT advance current_phase (INV-006)
  - All subprocess invocation goes through SubprocessSafety (T-SEC-1)
  - Language validated against LANGUAGE_ALLOWLIST before tool selection
  - On tool absent: status="unavailable" (NFR-008 graceful degradation)
  - On violations: status="failed"
  - On clean: status="passed"
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .language_allowlist import LANGUAGE_ALLOWLIST, get_tool, is_allowed
from .subprocess_safety import SubprocessSafety, SubprocessTimeoutError


# ---------------------------------------------------------------------------
# Data classes (contract-authoritative shapes from lsp_gate.md)
# ---------------------------------------------------------------------------

@dataclass
class LspViolation:
    """A single violation reported by an LSP tool."""
    file: str
    line: int
    column: int | None
    error_code: str
    message: str
    severity: str  # "error" | "warning"


@dataclass
class LspResult:
    """Result of an LspGate.run() invocation."""
    language: str
    tool_name: str
    tool_version: str          # Empty string if version cannot be detected
    status: str                # "passed" | "failed" | "unavailable"
    violations: list[LspViolation] = field(default_factory=list)
    duration_seconds: float = 0.0
    timeout_hit: bool = False

    def __post_init__(self):
        # Invariants from contract
        if self.status == "passed":
            assert len(self.violations) == 0, "passed status implies no violations"
        if self.status == "unavailable":
            assert len(self.violations) == 0, "unavailable status implies no violations"
        if self.timeout_hit:
            assert self.status == "failed", "timeout_hit implies failed status"


# ---------------------------------------------------------------------------
# Per-language output parsers
# ---------------------------------------------------------------------------

def _parse_tsc_output(stdout: str, stderr: str) -> list[LspViolation]:
    """
    Parse TypeScript compiler (tsc --noEmit) output into violations.
    tsc format: src/file.ts(10,5): error TS2304: Cannot find name 'foo'.
    """
    violations: list[LspViolation] = []
    pattern = re.compile(
        r"^(?P<file>.+?)\((?P<line>\d+),(?P<col>\d+)\):\s+"
        r"(?P<severity>error|warning)\s+(?P<code>TS\d+):\s+(?P<msg>.+)$"
    )
    for line in (stdout + "\n" + stderr).splitlines():
        m = pattern.match(line.strip())
        if m:
            violations.append(LspViolation(
                file=m.group("file"),
                line=int(m.group("line")),
                column=int(m.group("col")),
                error_code=m.group("code"),
                message=m.group("msg"),
                severity=m.group("severity"),
            ))
    return violations


def _parse_mypy_output(stdout: str, stderr: str) -> list[LspViolation]:
    """
    Parse mypy output into violations.
    mypy format: src/module.py:42: error: Name 'foo' is not defined  [name-defined]
    """
    violations: list[LspViolation] = []
    pattern = re.compile(
        r"^(?P<file>.+?):(?P<line>\d+):\s+"
        r"(?P<severity>error|warning|note):\s+(?P<msg>.+?)(?:\s+\[(?P<code>[^\]]+)\])?$"
    )
    for line in (stdout + "\n" + stderr).splitlines():
        m = pattern.match(line.strip())
        if m:
            severity = m.group("severity")
            if severity == "note":
                continue  # notes are informational, not violations
            violations.append(LspViolation(
                file=m.group("file"),
                line=int(m.group("line")),
                column=None,
                error_code=m.group("code") or "mypy",
                message=m.group("msg"),
                severity=severity,
            ))
    return violations


def _parse_govet_output(stdout: str, stderr: str) -> list[LspViolation]:
    """
    Parse go vet output into violations.
    go vet format: ./src/main.go:42:10: printf: arg foo is a func value, not a string
    """
    violations: list[LspViolation] = []
    pattern = re.compile(
        r"^\.?(?P<file>[^:]+\.go):(?P<line>\d+)(?::(?P<col>\d+))?:\s+(?P<msg>.+)$"
    )
    for line in (stdout + "\n" + stderr).splitlines():
        m = pattern.match(line.strip())
        if m:
            violations.append(LspViolation(
                file=m.group("file"),
                line=int(m.group("line")),
                column=int(m.group("col")) if m.group("col") else None,
                error_code="govet",
                message=m.group("msg"),
                severity="error",
            ))
    return violations


def _parse_mvn_output(stdout: str, stderr: str) -> list[LspViolation]:
    """
    Parse Maven compile output into violations.
    Maven format: [ERROR] /path/to/Foo.java:[42,10] error: cannot find symbol
    """
    violations: list[LspViolation] = []
    pattern = re.compile(
        r"^\[(?P<severity>ERROR|WARNING)\]\s+(?P<file>.+\.java):\[(?P<line>\d+),(?P<col>\d+)\]\s+(?P<msg>.+)$"
    )
    for line in (stdout + "\n" + stderr).splitlines():
        m = pattern.match(line.strip())
        if m:
            violations.append(LspViolation(
                file=m.group("file"),
                line=int(m.group("line")),
                column=int(m.group("col")),
                error_code="javac",
                message=m.group("msg"),
                severity=m.group("severity").lower(),
            ))
    return violations


# ---------------------------------------------------------------------------
# Tool version detection
# ---------------------------------------------------------------------------

def _detect_tool_version(safety: SubprocessSafety, tool_name: str) -> str:
    """
    Attempt to detect tool version via `{tool} --version`.
    Returns empty string on failure.
    """
    try:
        result = safety.invoke(tool_name, ["--version"])
        first_line = (result.stdout or result.stderr).splitlines()
        return first_line[0].strip() if first_line else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# LspGate
# ---------------------------------------------------------------------------

_PARSER_MAP = {
    "tsc": _parse_tsc_output,
    "mypy": _parse_mypy_output,
    "go": _parse_govet_output,
    "mvn": _parse_mvn_output,
}

_TOOL_ARGS_MAP: dict[str, list[str]] = {
    "tsc": ["--noEmit"],
    "mypy": ["--show-error-codes"],
    "go": ["vet", "./..."],
    "mvn": ["compile", "-q"],
}


class LspGate:
    """
    F1 LSP Pre-Flight Gate (Tier 0 Gate).
    Invokes language-specific static analysis tools as subprocesses.
    All invocations go through SubprocessSafety (shell=False, list-form args).
    """

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout = timeout_seconds
        self._safety = SubprocessSafety(timeout_seconds=timeout_seconds)

    def run(
        self,
        language: str,
        files: list[Path],
        timeout_seconds: float | None = None,
        working_dir: Path | None = None,
    ) -> LspResult:
        """
        Run the Tier 0 pre-flight gate for the given language.

        Args:
            language: Detected project language (validated against LANGUAGE_ALLOWLIST).
            files: Source files to analyze. Used to determine working_dir default.
            timeout_seconds: Override timeout. Default: 30.0s.
            working_dir: Subprocess working directory. Defaults to files[0].parent or cwd.

        Returns:
            LspResult with status, violations, and metadata.
        """
        effective_timeout = timeout_seconds if timeout_seconds is not None else self._timeout
        safety = SubprocessSafety(timeout_seconds=effective_timeout)

        # Determine working directory
        if working_dir is None:
            working_dir = files[0].parent if files else Path.cwd()

        # Validate language
        norm_lang = language.lower().strip()
        if not is_allowed(norm_lang):
            return LspResult(
                language=language,
                tool_name="",
                tool_version="",
                status="unavailable",
                violations=[],
                duration_seconds=0.0,
                timeout_hit=False,
            )

        tool_name = get_tool(norm_lang)
        assert tool_name is not None  # guaranteed by is_allowed check

        # Detect tool version (best-effort)
        tool_version = _detect_tool_version(safety, tool_name)

        # Build tool arguments
        tool_args = list(_TOOL_ARGS_MAP.get(tool_name, []))

        start = time.monotonic()
        try:
            result = safety.invoke(
                tool_name=tool_name,
                args=tool_args,
                working_dir=working_dir,
            )
            duration = time.monotonic() - start

            # Parse violations
            parser = _PARSER_MAP.get(tool_name, lambda out, err: [])
            violations = parser(result.stdout, result.stderr)

            if violations:
                status = "failed"
            elif result.returncode != 0 and not violations:
                # Non-zero with no parsed violations = tool error or build failure
                status = "failed"
                violations = [LspViolation(
                    file="<build>",
                    line=0,
                    column=None,
                    error_code="exit-nonzero",
                    message=(result.stderr or result.stdout)[:500].strip(),
                    severity="error",
                )]
            else:
                status = "passed"

            return LspResult(
                language=norm_lang,
                tool_name=tool_name,
                tool_version=tool_version,
                status=status,
                violations=violations,
                duration_seconds=duration,
                timeout_hit=False,
            )

        except SubprocessTimeoutError:
            duration = time.monotonic() - start
            return LspResult(
                language=norm_lang,
                tool_name=tool_name,
                tool_version=tool_version,
                status="failed",
                violations=[],
                duration_seconds=duration,
                timeout_hit=True,
            )

        except FileNotFoundError:
            duration = time.monotonic() - start
            return LspResult(
                language=norm_lang,
                tool_name=tool_name,
                tool_version="",
                status="unavailable",
                violations=[],
                duration_seconds=duration,
                timeout_hit=False,
            )

        except Exception:
            duration = time.monotonic() - start
            return LspResult(
                language=norm_lang,
                tool_name=tool_name,
                tool_version=tool_version,
                status="unavailable",
                violations=[],
                duration_seconds=duration,
                timeout_hit=False,
            )
