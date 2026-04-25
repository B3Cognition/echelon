"""BuildResult — structured outcome of a claude -p build invocation."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class BuildResult:
    """Outcome of one LLM build or feedback invocation.

    status values:
      "done"     — build completed, files written to worktree
      "impasse"  — build hit an unresolvable conflict (codegen only)
      "timeout"  — claude -p process exceeded timeout_ms
      "unknown"  — status file missing or unreadable
    """
    exit_code: int
    status: str
    impasse_file: Optional[str]
    stdout: str
    stderr: str
    duration_ms: int

    @property
    def succeeded(self) -> bool:
        return self.status == "done"

    @property
    def is_impasse(self) -> bool:
        return self.status == "impasse"

    @classmethod
    def from_status_file(
        cls,
        path: Path,
        *,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration_ms: int,
    ) -> "BuildResult":
        """Read status from HARNESS_BUILD_STATUS_FILE, fall back to 'unknown'."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("status file must be a JSON object")
            return cls(
                exit_code=exit_code,
                status=str(data.get("status", "unknown")),
                impasse_file=data.get("impasse_file"),
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
            )
        except Exception:
            return cls(
                exit_code=exit_code,
                status="unknown",
                impasse_file=None,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
            )
