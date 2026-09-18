"""Shared existing secure file boundary for discovery receipts; no workflow state."""
import fcntl
import os
from pathlib import Path
import re
import stat

from harness.durable_json import write_text_atomic
from harness.inspection_io import _open_root_directory


_MAX_BYTES = 16 * 1024 * 1024


def receipt_round_operation_id(producer, operation_id):
    """Keep original Synthesis filenames; refreshes use the existing round journal."""
    if producer == "constitution":
        if type(operation_id) is not str:
            raise ValueError("Constitution receipt selection required")
        if re.fullmatch(r"constitution-[0-9a-f]{32}", operation_id):
            return None
        if re.fullmatch(r"constitution-refresh-[0-9a-f]{32}", operation_id) is None:
            raise ValueError("invalid Constitution receipt selection")
        return operation_id
    if producer == "synthesizer":
        if type(operation_id) is not str:
            raise ValueError("synthesis receipt selection required")
        if re.fullmatch(r"synthesis-[0-9a-f]{32}", operation_id):
            return None
        if re.fullmatch(r"synthesizer-[0-9a-f]{32}", operation_id) is None:
            raise ValueError("invalid synthesis receipt selection")
        return operation_id
    return operation_id if producer in {"tracker", "why1", "what", "why2", "lexicon", "feasibility", "strategy", "alignment"} else None


class DiscoveryReceiptFile:
    """File/lock mechanics only; each owner validates its own payload."""

    def __init__(self, run_dir: Path, name: str, *, repair_unit: str | None = None, producer="discovery",
                 round_operation_id: str | None = None):
        from harness.discovery_producer import producer_key
        if type(name) is not str or name not in {"discovery-reservations", "discovery-turns"}:
            raise ValueError("unsupported discovery receipt name")
        if producer == "commander" and (name != "discovery-turns" or repair_unit is not None):
            raise ValueError("COMMANDER supports judgment receipts only")
        if producer in {"tracker", "why1", "what", "why2", "lexicon", "feasibility", "strategy", "alignment", "commander"} or (producer in {"synthesizer", "constitution"} and round_operation_id is not None):
            if (type(round_operation_id) is not str
                    or re.fullmatch(("constitution-refresh" if producer == "constitution" else producer) + r"-[0-9a-f]{32}", round_operation_id) is None
                    or repair_unit is not None):
                raise ValueError("producer receipts require an exact round operation")
            name = name.replace("discovery-", producer + "-", 1) + "-" + round_operation_id
        else:
            producer_key(producer, "operation")
            if round_operation_id is not None:
                raise ValueError("producer receipts do not support rounds")
        if producer in {"synthesizer", "constitution"}:
            if repair_unit is not None:
                raise ValueError("synthesis repair receipts not supported")
            name = name.replace("discovery-", producer + "-", 1)
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
