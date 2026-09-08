"""Bounded, deadline-aware capture for the Codex screened response path."""

from __future__ import annotations

import os
import selectors
import subprocess
import time
from dataclasses import dataclass


_READ_CHUNK_BYTES = 4096


@dataclass(frozen=True)
class CapturedCodexPipes:
    stdout: bytes
    stderr: bytes
    returncode: int


class CodexCaptureError(Exception):
    def __init__(self, reason: str, *, timed_out: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.timed_out = timed_out


def capture_codex_pipes(
    proc: subprocess.Popen,
    *,
    max_capture_bytes: int,
    timeout_s: float,
) -> CapturedCodexPipes:
    """Drain both owned pipes without exposing bytes or exceeding the deadline."""
    deadline = time.monotonic() + timeout_s
    termination_reserve = min(0.25, timeout_s / 5)
    read_deadline = deadline - termination_reserve
    try:
        stdout = proc.stdout
        stderr = proc.stderr
        if stdout is None or stderr is None:
            raise CodexCaptureError("capture_error")
        stdout.fileno()
        stderr.fileno()
        return _capture_os_pipes(
            proc,
            max_capture_bytes=max_capture_bytes,
            read_deadline=read_deadline,
            deadline=deadline,
        )
    except CodexCaptureError:
        _terminate_and_reap(proc, deadline)
        raise
    except Exception as exc:
        _terminate_and_reap(proc, deadline)
        raise CodexCaptureError("capture_error") from exc


def _capture_os_pipes(
    proc: subprocess.Popen,
    *,
    max_capture_bytes: int,
    read_deadline: float,
    deadline: float,
) -> CapturedCodexPipes:
    selector = selectors.DefaultSelector()
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    try:
        for name, pipe in (("stdout", proc.stdout), ("stderr", proc.stderr)):
            assert pipe is not None
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, data=name)

        total = 0
        while selector.get_map():
            remaining_time = read_deadline - time.monotonic()
            if remaining_time <= 0:
                raise CodexCaptureError("timeout", timed_out=True)
            ready = selector.select(remaining_time)
            if not ready:
                raise CodexCaptureError("timeout", timed_out=True)
            for key, _mask in ready:
                read_size = min(_READ_CHUNK_BYTES, max_capture_bytes - total + 1)
                try:
                    chunk = os.read(key.fd, max(1, read_size))
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total > max_capture_bytes:
                    raise CodexCaptureError("capture_overflow")
                chunks[key.data].extend(chunk)

        remaining_time = read_deadline - time.monotonic()
        if remaining_time <= 0:
            raise CodexCaptureError("timeout", timed_out=True)
        try:
            returncode = proc.wait(timeout=remaining_time)
        except subprocess.TimeoutExpired as exc:
            raise CodexCaptureError("timeout", timed_out=True) from exc
        return CapturedCodexPipes(
            stdout=bytes(chunks["stdout"]),
            stderr=bytes(chunks["stderr"]),
            returncode=int(returncode),
        )
    except CodexCaptureError:
        _terminate_and_reap(proc, deadline)
        raise
    except Exception as exc:
        _terminate_and_reap(proc, deadline)
        raise CodexCaptureError("capture_error") from exc
    finally:
        selector.close()


def _terminate_and_reap(proc: subprocess.Popen, deadline: float) -> None:
    try:
        if proc.poll() is None:
            proc.kill()
    except (AttributeError, OSError):
        try:
            proc.kill()
        except Exception:
            pass

    remaining_time = max(0.0, deadline - time.monotonic())
    try:
        proc.wait(timeout=remaining_time)
    except TypeError:
        try:
            proc.wait()
        except Exception:
            pass
    except Exception:
        pass
