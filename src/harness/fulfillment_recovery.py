"""Run-local fulfillment receipts and exact, recoverable report publication."""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import stat

from harness.durable_json import write_json_atomic, write_text_atomic
from harness.fulfillment_semantics import FulfillmentAssignment, validate_semantic_result
from harness.inspection_io import _open_root_directory


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _load(path: Path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 16 * 1024 * 1024:
        raise ValueError("unsafe fulfillment recovery record")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        current = os.fstat(fd)
        if (current.st_dev, current.st_ino, current.st_size) != (info.st_dev, info.st_ino, info.st_size):
            raise ValueError("fulfillment recovery record changed")
        with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as stream:
            value = json.load(stream)
    finally:
        os.close(fd)
    if type(value) is not dict or set(value) != {"payload", "sha256"} or value["sha256"] != _hash(value["payload"]):
        raise ValueError("corrupt fulfillment recovery receipt")
    return value["payload"]


def _save(path: Path, value) -> None:
    write_json_atomic(path, {"payload": value, "sha256": _hash(value)}, trusted_root=path.parent)


class FulfillmentRecovery:
    """Serialize one selected run; never discover another run or reset its state."""

    def __init__(self, run: Path):
        self.run = run
        self.path = run / "controlled-fulfillment.json"
        self.fd = None
        self.data = None

    def __enter__(self):
        root = _open_root_directory(self.run)
        try:
            fd = os.open("controlled-fulfillment.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                         0o600, dir_fd=root)
        finally:
            os.close(root)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("unsafe fulfillment lock")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd
        return self

    def __exit__(self, *args):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def load(self):
        self.data = _load(self.path)
        if self.data is not None:
            _validate(self.data)
        return self.data

    def save(self):
        _validate(self.data)
        _save(self.path, self.data)

    def usage(self):
        records = [record for step in self.data["steps"].values() for record in step["records"]]
        return {"tokens": sum(record["token_usage"] or 0 for record in records),
                "known": all(record["token_usage"] is not None for record in records),
                "dispatches": len(records)}


def _validate(data):
    fields = {"schema_version", "binding", "phase", "inputs", "budget_limit", "steps", "outputs"}
    if type(data) is not dict or set(data) != fields or type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("invalid fulfillment recovery schema")
    if data["phase"] not in {"preparing", "prepared", "staged"}:
        raise ValueError("invalid fulfillment recovery phase")
    if type(data["binding"]) is not str or len(data["binding"]) != 64:
        raise ValueError("invalid fulfillment recovery binding")
    if data["inputs"] is not None and (type(data["inputs"]) is not str or len(data["inputs"]) != 64):
        raise ValueError("invalid fulfillment recovery input digest")
    budget = data["budget_limit"]
    if budget is not None and (type(budget) not in {int, float} or not math.isfinite(budget) or budget < 0):
        raise ValueError("invalid recovered fulfillment budget")
    steps = data["steps"]
    if type(steps) is not dict or not set(steps) <= {"mapper", "judge"} or type(data["outputs"]) is not dict:
        raise ValueError("invalid fulfillment recovery steps")
    for name, step in steps.items():
        if type(step) is not dict or set(step) != {"assignment", "deadline", "records"}:
            raise ValueError("invalid fulfillment semantic receipt")
        identity = step["assignment"]
        if type(identity) is not dict or identity.get("schema_version") != 1:
            raise ValueError("invalid recovered assignment")
        assignment = FulfillmentAssignment(**{key: value for key, value in identity.items() if key != "schema_version"})
        if assignment.identity() != identity or assignment.step != name:
            raise ValueError("invalid recovered assignment binding")
        if type(step["deadline"]) not in {int, float} or not math.isfinite(step["deadline"]):
            raise ValueError("invalid recovered deadline")
        records = step["records"]
        if type(records) is not list or len(records) > 33:
            raise ValueError("invalid recovered turn count")
        terminal = False
        for record in records:
            if terminal or type(record) is not dict or set(record) != {"reply", "read", "token_usage", "error"}:
                raise ValueError("invalid fulfillment turn receipt")
            usage = record["token_usage"]
            if usage is not None and (type(usage) is not int or usage < 0):
                raise ValueError("invalid recovered fulfillment usage")
            if record["error"] is not None and (type(record["error"]) is not str or not record["error"]):
                raise ValueError("invalid recovered fulfillment error")
            if record["reply"] is not None:
                reply = validate_semantic_result(record["reply"], assignment)
                if reply["action"] == "read":
                    if record["read"] is not None and (type(record["read"]) is not dict
                            or set(record["read"]) != {"request", "response"}
                            or record["read"]["request"] != reply["request"]):
                        raise ValueError("invalid recovered read receipt")
                elif record["read"] is not None:
                    raise ValueError("unexpected recovered read")
                terminal = reply["action"] != "read"
            else:
                terminal = True
            terminal = terminal or record["error"] is not None


def publish_fulfillment_outputs(run_dir: Path, spec_dir: Path, outputs: dict[str, str]) -> None:
    """Replay only the exact pending generation, never overwrite an external edit."""
    names = ("fulfillment-report.md", "fulfillment-gaps.md")
    if type(outputs) is not dict or set(outputs) != set(names) or any(type(value) is not str for value in outputs.values()):
        raise ValueError("invalid fulfillment publication outputs")
    # Caller owns the run lock across assembly, publication and lifecycle.
    path = run_dir / "fulfillment-publication.json"
    pending = _load(path)
    if pending is None:
        originals = {}
        for name in names:
            destination = spec_dir / name
            if destination.is_symlink():
                raise ValueError("unsafe fulfillment publication destination")
            originals[name] = destination.read_bytes().decode("utf-8") if destination.exists() else None
        pending = {"schema_version": 1, "spec_dir": str(spec_dir.resolve()),
                   "originals": originals, "outputs": outputs}
        _save(path, pending)
    if (type(pending) is not dict or set(pending) != {"schema_version", "spec_dir", "originals", "outputs"}
            or pending["schema_version"] != 1 or pending["spec_dir"] != str(spec_dir.resolve())
            or pending["outputs"] != outputs or type(pending["originals"]) is not dict
            or set(pending["originals"]) != set(names)):
        raise ValueError("fulfillment publication intent conflict")
    # Check both destinations before either write, including on restart.
    current = {}
    for name in names:
        destination = spec_dir / name
        if destination.is_symlink() or (destination.exists() and
                (not destination.is_file() or destination.stat().st_nlink != 1)):
            raise ValueError("unsafe fulfillment publication destination")
        current[name] = destination.read_bytes().decode("utf-8") if destination.exists() else None
        if current[name] not in (pending["originals"][name], outputs[name]):
            raise ValueError("fulfillment publication destination conflict")
    for name in names:
        if current[name] != outputs[name]:
            write_text_atomic(spec_dir / name, outputs[name], trusted_root=spec_dir, expected_text=current[name])
