"""
adapters.py — Static analysis tool adapters for /codegen pipeline.
Spec 008: SOAR-Powered Claude Code Software Development Agent
Version: 1.0.0

T-010: Language-specific static analysis adapters per ADR-008-004.

Each adapter:
  - Accepts tool output (JSON string or XML string).
  - Produces a sorted, deterministic list of ViolationRecord objects.
  - Determinism guarantee: output is sorted by (file, line, rule_id).

Adapters:
  - EslintAdapter   : ESLint JSON (TypeScript / JavaScript)
  - RuffAdapter     : ruff JSON (Python)
  - GolangciAdapter : golangci-lint JSON (Go)
  - CheckstyleAdapter : Checkstyle XML (Java)

ADR-008-004: All adapters must produce deterministic output (same input → same output).
FR-GATE-007: Violation records feed into the WME Translator (T-011).
NFR-PORT-001: At least four language adapters implemented.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# ViolationRecord — normalised output of every adapter
# ---------------------------------------------------------------------------

@dataclass(frozen=True, order=True)
class ViolationRecord:
    """
    Normalised static analysis violation.

    Sorting key: (file, line, rule_id) — ensures deterministic output
    regardless of tool output order.
    """
    file: str
    line: int
    rule_id: str
    severity: str   # critical | error | warning | info
    tool: str       # eslint | ruff | golangci-lint | checkstyle
    message: str = field(compare=False, default="")
    column: int = field(compare=False, default=0)

    @property
    def tool_rule_key(self) -> str:
        """Composite key used by WMETranslator for cq-isc-id lookup."""
        return f"{self.tool}:{self.rule_id}"


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class StaticAnalysisAdapter:
    """Abstract base for all adapters."""

    TOOL_NAME: str = ""

    def parse(self, output: str) -> list[ViolationRecord]:
        raise NotImplementedError

    def _normalise_severity(self, raw: str) -> str:
        """Map tool-specific severity labels to canonical set."""
        raw = (raw or "").lower()
        if raw in ("critical", "fatal"):
            return "critical"
        if raw in ("error", "e", "2"):
            return "error"
        if raw in ("warning", "warn", "w", "1"):
            return "warning"
        return "info"


# ---------------------------------------------------------------------------
# ESLint adapter (TypeScript / JavaScript)
# ---------------------------------------------------------------------------

class EslintAdapter(StaticAnalysisAdapter):
    """
    Parse ESLint JSON output into ViolationRecord list.

    ESLint JSON schema (--format json):
      [{"filePath": "...", "messages": [{"ruleId": "...", "severity": 1|2,
        "message": "...", "line": N, "column": N}]}]
    """

    TOOL_NAME = "eslint"

    def parse(self, output: str) -> list[ViolationRecord]:
        if not output or not output.strip():
            return []
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return []

        records: list[ViolationRecord] = []
        for file_result in data:
            fpath = file_result.get("filePath", "<unknown>")
            for msg in file_result.get("messages", []):
                rule_id = msg.get("ruleId") or "unknown"
                severity_int = msg.get("severity", 1)
                severity_str = "error" if severity_int == 2 else "warning"
                records.append(ViolationRecord(
                    file=fpath,
                    line=msg.get("line", 0),
                    rule_id=rule_id,
                    severity=severity_str,
                    tool=self.TOOL_NAME,
                    message=msg.get("message", ""),
                    column=msg.get("column", 0),
                ))
        return sorted(records)


# ---------------------------------------------------------------------------
# ruff adapter (Python)
# ---------------------------------------------------------------------------

class RuffAdapter(StaticAnalysisAdapter):
    """
    Parse ruff JSON output into ViolationRecord list.

    ruff JSON schema (--output-format json):
      [{"filename": "...", "location": {"row": N, "column": N},
        "code": "S105", "message": "...", "fix": null, "url": "..."}]
    """

    TOOL_NAME = "ruff"

    def parse(self, output: str) -> list[ViolationRecord]:
        if not output or not output.strip():
            return []
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return []

        records: list[ViolationRecord] = []
        for item in data:
            loc = item.get("location", {})
            code = item.get("code", "unknown")
            # Map ruff codes to canonical severity
            severity = self._ruff_severity(code)
            records.append(ViolationRecord(
                file=item.get("filename", "<unknown>"),
                line=loc.get("row", 0),
                rule_id=code,
                severity=severity,
                tool=self.TOOL_NAME,
                message=item.get("message", ""),
                column=loc.get("column", 0),
            ))
        return sorted(records)

    def _ruff_severity(self, code: str) -> str:
        """Approximate severity from ruff rule code prefix."""
        if code.startswith("S"):  # bandit security rules
            return "error"
        if code.startswith("E") or code.startswith("W"):
            return "warning"
        return "info"


# ---------------------------------------------------------------------------
# golangci-lint adapter (Go)
# ---------------------------------------------------------------------------

class GolangciAdapter(StaticAnalysisAdapter):
    """
    Parse golangci-lint JSON output into ViolationRecord list.

    golangci-lint JSON schema (--out-format json):
      {"Issues": [{"FromLinter": "...", "Text": "...",
        "Pos": {"Filename": "...", "Line": N, "Column": N},
        "Severity": "..."}]}
    """

    TOOL_NAME = "golangci-lint"

    def parse(self, output: str) -> list[ViolationRecord]:
        if not output or not output.strip():
            return []
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return []

        issues = data.get("Issues") or []
        records: list[ViolationRecord] = []
        for issue in issues:
            pos = issue.get("Pos", {})
            records.append(ViolationRecord(
                file=pos.get("Filename", "<unknown>"),
                line=pos.get("Line", 0),
                rule_id=issue.get("FromLinter", "unknown"),
                severity=self._normalise_severity(issue.get("Severity", "warning")),
                tool=self.TOOL_NAME,
                message=issue.get("Text", ""),
                column=pos.get("Column", 0),
            ))
        return sorted(records)


# ---------------------------------------------------------------------------
# Checkstyle adapter (Java)
# ---------------------------------------------------------------------------

class CheckstyleAdapter(StaticAnalysisAdapter):
    """
    Parse Checkstyle XML output into ViolationRecord list.

    Checkstyle XML schema:
      <checkstyle>
        <file name="...">
          <error line="N" column="N" severity="..." message="..." source="checkstyle.checks.FooCheck"/>
        </file>
      </checkstyle>

    Rule ID is derived from the `source` attribute last component.
    """

    TOOL_NAME = "checkstyle"

    def parse(self, output: str) -> list[ViolationRecord]:
        if not output or not output.strip():
            return []
        try:
            root = ET.fromstring(output)
        except ET.ParseError:
            return []

        records: list[ViolationRecord] = []
        for file_elem in root.findall("file"):
            fpath = file_elem.get("name", "<unknown>")
            for error in file_elem.findall("error"):
                source = error.get("source", "")
                # Rule ID = last component of fully-qualified class name
                rule_id = source.rsplit(".", 1)[-1] if source else "unknown"
                records.append(ViolationRecord(
                    file=fpath,
                    line=int(error.get("line", 0)),
                    rule_id=rule_id,
                    severity=self._normalise_severity(error.get("severity", "warning")),
                    tool=self.TOOL_NAME,
                    message=error.get("message", ""),
                    column=int(error.get("column", 0)),
                ))
        return sorted(records)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, type[StaticAnalysisAdapter]] = {
    "eslint": EslintAdapter,
    "ruff": RuffAdapter,
    "golangci-lint": GolangciAdapter,
    "golangci": GolangciAdapter,
    "checkstyle": CheckstyleAdapter,
}


def get_adapter(tool: str) -> StaticAnalysisAdapter:
    """
    Return the appropriate adapter instance for the given tool name.
    Raises KeyError if the tool is not supported.
    """
    cls = _ADAPTERS.get(tool.lower())
    if cls is None:
        raise KeyError(
            f"No static analysis adapter for tool '{tool}'. "
            f"Supported: {sorted(_ADAPTERS.keys())}"
        )
    return cls()
