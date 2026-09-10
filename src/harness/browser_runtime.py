"""Shared classification for transient browser-process infrastructure loss."""

from __future__ import annotations


def is_transient_browser_runtime_failure(stdout: str, stderr: str) -> bool:
    """Recognize browser-process loss, not ordinary browser test assertions."""
    output = f"{stdout}\n{stderr}".lower()
    if is_ambiguous_browser_runtime_failure(stdout, stderr):
        return False
    return any(
        marker in output
        for marker in (
            "target crashed",
            "session closed",
            "browser has been closed",
            "browser process exited unexpectedly",
            "browser process crashed",
        )
    ) or ("object with guid" in output and "not bound in the connection" in output)


def is_ambiguous_browser_runtime_failure(stdout: str, stderr: str) -> bool:
    """Recognize a test timeout whose only connection error is cleanup fallout.

    Playwright emits ``Object with guid ... not bound in the connection`` while
    tearing down an operation that was already cancelled by a test timeout. That
    is not enough to claim the browser process died. The harness retries once
    in a fresh sandbox, then asks DEBUGGER to identify the primary owner.
    """
    output = f"{stdout}\n{stderr}".lower()
    return (
        "test timeout" in output
        and "object with guid" in output
        and "not bound in the connection" in output
    )
