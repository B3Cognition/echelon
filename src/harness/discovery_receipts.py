"""Shared existing secure file boundary for discovery receipts; no workflow state."""
import fcntl
import os
from pathlib import Path
import re
import stat

from harness.durable_json import write_text_atomic
from harness.inspection_io import _open_root_directory


_MAX_BYTES = 16 * 1024 * 1024


class DiscoveryReceiptFile:
    """File/lock mechanics only; each owner validates its own payload."""

    def __init__(self, run_dir: Path, name: str, *, repair_unit: str | None = None, producer="discovery",
                 round_operation_id: str | None = None):
        from harness.discovery_producer import producer_key
        if type(name) is not str or name not in {"discovery-reservations", "discovery-turns"}:
            raise ValueError("unsupported discovery receipt name")
        if producer in {"tracker", "why1"}:
            if (type(round_operation_id) is not str
                    or re.fullmatch(producer + r"-[0-9a-f]{32}", round_operation_id) is None
                    or repair_unit is not None):
                raise ValueError("Tracker receipts require an exact round operation")
            name = name.replace("discovery-", producer + "-", 1) + "-" + round_operation_id
        else:
            producer_key(producer, "operation")
            if round_operation_id is not None:
                raise ValueError("only Tracker receipts have rounds")
        if producer == "synthesizer":
            if repair_unit is not None:
                raise ValueError("synthesis repair receipts not supported")
            name = name.replace("discovery-", "synthesizer-", 1)
        if repair_unit is not None:
            if type(repair_unit) is not str or re.fullmatch(r"[0-9a-f]{64}", repair_unit) is None:
                raise ValueError("invalid discovery repair receipt selection")
            name = f"{name}-repair-{repair_unit}"
        self.name = name
        self.producer = producer
        self.round_operation_id = round_operation_id
        self.run_dir = Path(os.path.abspath(run_dir))
        self.path = self.run_dir / f"{name}.json"
        self._root = self._lock = None
        self._raw = None

    def __enter__(self):
        if self._root is not None:
            raise ValueError("discovery receipt journal already open")
        self._root = _open_root_directory(self.run_dir)
        try:
            self._lock = os.open(f"{self.name}.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 0o600, dir_fd=self._root)
            info = os.fstat(self._lock)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("unsafe discovery receipt lock")
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *args):
        for field in ("_lock", "_root"):
            descriptor = getattr(self, field)
            if descriptor is not None:
                os.close(descriptor)
                setattr(self, field, None)
        self._raw = None

    def _check_directory(self):
        if self._root is None or self._lock is None:
            raise ValueError("discovery receipt journal is not open")
        current = _open_root_directory(self.run_dir)
        try:
            original, actual = os.fstat(self._root), os.fstat(current)
            lock = os.stat(f"{self.name}.lock", dir_fd=current, follow_symlinks=False)
            held = os.fstat(self._lock)
            if ((original.st_dev, original.st_ino) != (actual.st_dev, actual.st_ino)
                    or (lock.st_dev, lock.st_ino) != (held.st_dev, held.st_ino) or lock.st_nlink != 1):
                raise ValueError("discovery receipt directory or lock changed")
        finally:
            os.close(current)

    def _read(self):
        self._check_directory()
        try:
            descriptor = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._root)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > _MAX_BYTES:
                raise ValueError("unsafe discovery receipt record")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(_MAX_BYTES + 1)
            if len(raw) > _MAX_BYTES:
                raise ValueError("discovery receipt record exceeds limit")
            return raw.decode("utf-8")
        finally:
            os.close(descriptor)

    def _write(self, raw: str):
        if len(raw.encode("utf-8")) > _MAX_BYTES:
            raise ValueError("discovery receipt exceeds limit")
        self._check_directory()
        write_text_atomic(self.path, raw, trusted_root=self.run_dir, expected_text=self._raw)
        self._check_directory()
        self._raw = raw
