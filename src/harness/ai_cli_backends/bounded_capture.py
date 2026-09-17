"""Bounded, deadline-aware capture for constrained AI CLI subprocesses."""

from __future__ import annotations

import os
import selectors
import subprocess
import time
from dataclasses import dataclass


_READ_CHUNK_BYTES = 4096


@dataclass(frozen=True)
class CapturedPipes:
    stdout: bytes
    stderr: bytes
    returncode: int


class CaptureError(Exception):
    def __init__(self, reason: str, *, timed_out: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.timed_out = timed_out


def capture_pipes(
    proc: subprocess.Popen,
    *,
    max_capture_bytes: int,
    timeout_s: float,
    input_bytes: bytes,
) -> CapturedPipes:
    """Feed stdin and drain stdout/stderr under one size and time boundary."""
    deadline = time.monotonic() + timeout_s
    termination_reserve = min(0.25, timeout_s / 5)
    read_deadline = deadline - termination_reserve
    selector = selectors.DefaultSelector()
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    try:
        if proc.stdin is None or proc.stdout is None or proc.stderr is None:
            raise CaptureError("capture_error")
        if type(input_bytes) is not bytes:
            raise CaptureError("capture_error")
        for name, pipe in (("stdout", proc.stdout), ("stderr", proc.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, data=name)
        offset = 0
        input_view = memoryview(input_bytes)
        if input_bytes:
            os.set_blocking(proc.stdin.fileno(), False)
            selector.register(proc.stdin, selectors.EVENT_WRITE, data="stdin")
        else:
            _close_stdin(proc)

        total = 0
        while selector.get_map():
            remaining = read_deadline - time.monotonic()
            if remaining <= 0:
                raise CaptureError("timeout", timed_out=True)
            ready = selector.select(remaining)
            if not ready:
                raise CaptureError("timeout", timed_out=True)
            for key, _mask in ready:
                if key.data == "stdin":
                    try:
                        written = os.write(key.fd, input_view[offset:])
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        selector.unregister(key.fileobj)
                        _close_stdin(proc)
                        continue
                    if written <= 0:
                        raise CaptureError("capture_error")
                    offset += written
                    if offset == len(input_bytes):
                        selector.unregister(key.fileobj)
                        _close_stdin(proc)
                    continue
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
                    raise CaptureError("capture_overflow")
                chunks[key.data].extend(chunk)

        remaining = read_deadline - time.monotonic()
        if remaining <= 0:
            raise CaptureError("timeout", timed_out=True)
        try:
            returncode = proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise CaptureError("timeout", timed_out=True) from exc
        return CapturedPipes(
            stdout=bytes(chunks["stdout"]),
            stderr=bytes(chunks["stderr"]),
            returncode=int(returncode),
        )
    except CaptureError:
        _terminate_and_reap(proc, deadline)
        raise
    except Exception as exc:
        _terminate_and_reap(proc, deadline)
        raise CaptureError("capture_error") from exc
    finally:
        selector.close()
        _close_stdin(proc)


def _close_stdin(proc: subprocess.Popen) -> None:
    stdin = getattr(proc, "stdin", None)
    if stdin is None:
        return
    try:
        stdin.close()
    except OSError:
        pass


def _terminate_and_reap(proc: subprocess.Popen, deadline: float) -> None:
    try:
        if proc.poll() is None:
            proc.kill()
    except (AttributeError, OSError):
        try:
            proc.kill()
        except Exception:
            pass
    remaining = max(0.0, deadline - time.monotonic())
    try:
        proc.wait(timeout=remaining)
    except TypeError:
        try:
            proc.wait()
        except Exception:
            pass
    except Exception:
        pass
