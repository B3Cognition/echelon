"""
exceptions.py — LSP gate exception types.
Spec 018 T-SEC-1: subprocess safety.
"""
from __future__ import annotations


class SubprocessTimeoutError(Exception):
    """
    Raised when an LSP tool subprocess exceeds its hard timeout budget.
    Spec 018 AC-004-5: 30-second hard kill on subprocess timeout.

    Attributes:
        tool: the tool binary name (e.g. 'tsc', 'mypy')
        timeout_seconds: the configured timeout that was exceeded
        project_root: the project root directory passed to the tool
    """

    def __init__(self, tool: str, timeout_seconds: float, project_root: str = "") -> None:
        self.tool = tool
        self.timeout_seconds = timeout_seconds
        self.project_root = project_root
        super().__init__(
            f"LSP tool '{tool}' exceeded {timeout_seconds}s timeout "
            f"(project: {project_root or '<unset>'})"
        )


class SubprocessInvocationError(Exception):
    """
    Raised when an LSP tool subprocess exits with a non-zero code for reasons
    other than lint/type violations (e.g. tool crash, missing config file).
    Not raised for normal lint failure (exit 1 from tsc/mypy is expected and parsed).
    """

    def __init__(self, tool: str, returncode: int, stderr: str = "") -> None:
        self.tool = tool
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(
            f"LSP tool '{tool}' failed with exit code {returncode}: {stderr[:200]}"
        )
