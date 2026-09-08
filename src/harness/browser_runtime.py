"""Shared classification for transient browser-process infrastructure loss."""

from __future__ import annotations


def is_transient_browser_runtime_failure(stdout: str, stderr: str) -> bool:
    """Recognize browser-process loss, not ordinary browser test assertions."""
    output = f"{stdout}\n{stderr}".lower()
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
