"""
subprocess_safety.py — Safe subprocess invocation for LSP tools.
Spec 018 T-SEC-1: RAR-001 command injection prevention.

Design decisions (ADR-001, RAR-001):
  - shell=False is HARDCODED — never True. Prevents shell metacharacter injection.
  - Tool binary is resolved via shutil.which() using the system PATH only.
    CWD is NOT prepended to PATH before resolution (RAR-001 A3 mitigation).
  - Arguments are passed as a list (not a string) to subprocess.run().
  - 30-second hard timeout with SIGKILL on expiry (NFR-001 AC-004-5).
  - Tool binary name comes from LANGUAGE_ALLOWLIST, never from user input directly.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from .exceptions import SubprocessTimeoutError
from .language_allowlist import LANGUAGE_ALLOWLIST, is_allowed

# Hard timeout budget for all LSP tool invocations (NFR-001)
DEFAULT_TIMEOUT_SECONDS: float = 30.0


class SubprocessSafetyResult:
    """Result from SubprocessSafety.invoke()."""

    __slots__ = ("returncode", "stdout", "stderr", "tool_binary", "timed_out")

    def __init__(
        self,
        returncode: int,
        stdout: str,
        stderr: str,
        tool_binary: str,
        timed_out: bool = False,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.tool_binary = tool_binary
        self.timed_out = timed_out


class SubprocessSafety:
    """
    Safe subprocess invocation wrapper for LSP tools.

    All invocations use:
      - shell=False (INV hardcoded — cannot be overridden by caller)
      - List-form args (never string interpolation)
      - PATH-only binary resolution (shutil.which, no CWD prepend)
      - Hard 30-second timeout with kill on expiry
    """

    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout_seconds

    def resolve_binary(self, tool_name: str) -> str | None:
        """
        Resolve tool binary via PATH-only lookup.
        Returns absolute path or None if not found.
        Explicitly uses the inherited PATH — does NOT prepend CWD.
        """
        return shutil.which(tool_name)

    def invoke(
        self,
        tool_name: str,
        args: Sequence[str],
        working_dir: Path | str | None = None,
        env: dict[str, str] | None = None,
    ) -> SubprocessSafetyResult:
        """
        Invoke an LSP tool subprocess safely.

        Args:
            tool_name: Binary name from LANGUAGE_ALLOWLIST (e.g. 'tsc', 'mypy').
                       Must NOT contain shell metacharacters — validated before invocation.
            args: Additional arguments as a list of strings.
                  Must NOT be joined into a shell string.
            working_dir: Working directory for subprocess. Defaults to current dir.
            env: Optional environment dict. If None, inherits os.environ.

        Returns:
            SubprocessSafetyResult with stdout, stderr, returncode.

        Raises:
            ValueError: If tool_name contains unsafe characters or is not in allowlist.
            SubprocessTimeoutError: If subprocess exceeds timeout budget.
            FileNotFoundError: If tool binary is not found on PATH.
        """
        # Validate tool_name is allowlisted
        if tool_name not in LANGUAGE_ALLOWLIST.values():
            raise ValueError(
                f"Tool '{tool_name}' is not in the subprocess safety allowlist. "
                f"Allowed tools: {sorted(set(LANGUAGE_ALLOWLIST.values()))}"
            )

        # Resolve binary — PATH-only, never CWD
        binary_path = self.resolve_binary(tool_name)
        if binary_path is None:
            raise FileNotFoundError(
                f"LSP tool '{tool_name}' not found on PATH. "
                "Install the tool or check the PATH configuration."
            )

        # Build command as a list — shell=False enforced below
        cmd: list[str] = [binary_path] + [str(a) for a in args]

        cwd = str(working_dir) if working_dir is not None else None
        proc_env = env if env is not None else None

        try:
            result = subprocess.run(
                cmd,
                shell=False,       # HARDCODED — RAR-001 mitigation
                capture_output=True,
                text=True,
                timeout=self._timeout,
                cwd=cwd,
                env=proc_env,
            )
        except subprocess.TimeoutExpired:
            raise SubprocessTimeoutError(
                tool=tool_name,
                timeout_seconds=self._timeout,
                project_root=str(working_dir or ""),
            )

        return SubprocessSafetyResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            tool_binary=binary_path,
        )
