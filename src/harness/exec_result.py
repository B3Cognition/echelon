"""ExecResult and ResourceStats dataclasses with validation.

Matches contracts/sandbox-provider.md exactly:
- ExecResult: exit_code, stdout, stderr, duration_ms, resource_stats, truncated
- ResourceStats: peak_memory_bytes, cpu_time_ms, wall_time_ms
- Special exit codes: 124 (timeout), 137 (force-kill), 139 (OOM), 155 (PID), 156 (storage)

Per FR-SANDBOX-002b: default missing optional fields (0 for int, "" for str, null for resource_stats).
Per FR-SANDBOX-002c: missing required fields raise SchemaViolationError.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from harness.errors import SchemaViolationError


# Special exit codes per contract
EXIT_TIMEOUT = 124
EXIT_FORCE_KILL = 137
EXIT_OOM = 139
EXIT_PID_LIMIT = 155
EXIT_STORAGE_LIMIT = 156

SPECIAL_EXIT_CODES = {
    EXIT_TIMEOUT: "timeout",
    EXIT_FORCE_KILL: "force-kill",
    EXIT_OOM: "OOM",
    EXIT_PID_LIMIT: "PID limit",
    EXIT_STORAGE_LIMIT: "storage limit",
}


@dataclass
class ResourceStats:
    """Resource usage statistics from sandbox execution."""
    peak_memory_bytes: int
    cpu_time_ms: int
    wall_time_ms: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ResourceStats:
        """Create ResourceStats from a dictionary."""
        return cls(
            peak_memory_bytes=int(data.get("peak_memory_bytes", 0)),
            cpu_time_ms=int(data.get("cpu_time_ms", 0)),
            wall_time_ms=int(data.get("wall_time_ms", 0)),
        )


@dataclass
class ExecResult:
    """Structured result from sandbox command execution.

    Per contract: all fields are required in the schema. Missing fields
    raise SchemaViolationError. Optional defaults applied per FR-SANDBOX-002b.
    """
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    resource_stats: Optional[ResourceStats]
    truncated: bool = False

    @property
    def is_timeout(self) -> bool:
        """Check if this result represents a timeout."""
        return self.exit_code == EXIT_TIMEOUT

    @property
    def is_oom(self) -> bool:
        """Check if this result represents an OOM kill."""
        return self.exit_code == EXIT_OOM

    @property
    def is_special_exit(self) -> bool:
        """Check if exit code is a special harness code."""
        return self.exit_code in SPECIAL_EXIT_CODES

    @property
    def special_exit_reason(self) -> Optional[str]:
        """Human-readable reason for special exit codes."""
        return SPECIAL_EXIT_CODES.get(self.exit_code)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecResult:
        """Create ExecResult from a dictionary, validating required fields.

        Per FR-SANDBOX-002c: raises SchemaViolationError on missing fields.
        Per FR-SANDBOX-002b: applies defaults for missing optional fields.
        """
        if not isinstance(data, dict):
            raise SchemaViolationError(
                "ExecResult data must be a dictionary",
                field="<root>",
            )

        # exit_code is strictly required and must not be null
        if "exit_code" not in data:
            raise SchemaViolationError(
                "Missing required field 'exit_code'",
                field="exit_code",
            )
        if data["exit_code"] is None:
            raise SchemaViolationError(
                "Field 'exit_code' must not be null",
                field="exit_code",
            )

        # Apply defaults per FR-SANDBOX-002b
        exit_code = int(data["exit_code"])
        stdout = str(data.get("stdout", ""))
        stderr = str(data.get("stderr", ""))
        duration_ms = int(data.get("duration_ms", 0))
        truncated = bool(data.get("truncated", False))

        # resource_stats is optional, defaults to null
        resource_stats_raw = data.get("resource_stats")
        resource_stats: Optional[ResourceStats] = None
        if resource_stats_raw is not None and isinstance(resource_stats_raw, dict):
            resource_stats = ResourceStats.from_dict(resource_stats_raw)

        # Validate exit_code range
        if duration_ms < 0:
            raise SchemaViolationError(
                f"Field 'duration_ms' must not be negative: {duration_ms}",
                field="duration_ms",
            )

        return cls(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            resource_stats=resource_stats,
            truncated=truncated,
        )
