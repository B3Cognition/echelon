"""Serialized, fail-closed receipt authority for one delivery operation."""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import stat

from harness.delivery_slice import DeliveryAssignment, DeliverySliceError, PASSING_VERDICTS, validate_delivery_result
from harness.durable_json import write_json_atomic


class DeliverySliceJournal:
    def __init__(self, root: Path, operation_id: str):
        if not isinstance(operation_id, str) or not operation_id:
            raise DeliverySliceError("invalid delivery operation identity")
        self.root = root / hashlib.sha256(operation_id.encode()).hexdigest()
        self.path = self.root / "journal.json"
        self._fd = None

    def __enter__(self):
        if self.root.is_symlink():
            raise DeliverySliceError("symlinked delivery journal directory")
        self.root.mkdir(exist_ok=True)
        fd = os.open(self.root / "journal.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise DeliverySliceError("invalid delivery journal lock")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException as exc:
            os.close(fd)
            if isinstance(exc, BlockingIOError):
                raise DeliverySliceError("delivery_slice_locked") from exc
            raise
        self._fd = fd
        return self

    def __exit__(self, *args):
        if self._fd is not None:
            os.close(self._fd)  # OS-held lock is also released on process loss.
            self._fd = None

    def load(self, *, required=False):
        if self.path.is_symlink():
            raise DeliverySliceError("symlinked delivery journal")
        if not self.path.exists():
            if required:
                raise DeliverySliceError("delivery_reconciliation_required: expected journal is missing")
            return None
        if not self.path.is_file() or self.path.stat().st_size > 2_000_000:
            raise DeliverySliceError("invalid delivery journal file")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        _validate(data)
        return data

    def save(self, data):
        _validate(data)
        write_json_atomic(self.path, data, trusted_root=self.root)


def _validate(data):
    fields = {"schema_version", "run_id", "binding", "task_id", "input_fingerprint",
              "protected_fingerprint", "candidate_fingerprint", "progress_input_fingerprint",
              "progress_protected_fingerprint", "budget_limit", "records"}
    if (not isinstance(data, dict) or set(data) != fields
            or type(data["schema_version"]) is not int or data["schema_version"] != 1):
        raise DeliverySliceError("invalid delivery journal schema")
    if any(not isinstance(data[key], str) or not data[key] for key in fields - {"schema_version", "budget_limit", "records"}):
        raise DeliverySliceError("invalid delivery journal identity")
    budget = data["budget_limit"]
    if budget is not None and (type(budget) not in (int, float) or not math.isfinite(budget)):
        raise DeliverySliceError("invalid delivery journal budget")
    records = data["records"]
    if not isinstance(records, list) or len(records) > 12:
        raise DeliverySliceError("invalid delivery journal receipts")
    steps = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    step_index, repair = 0, 0
    candidate = data["candidate_fingerprint"]
    seen = set()
    terminal = False
    for index, record in enumerate(records):
        if terminal or repair > 2 or step_index >= 4:
            raise DeliverySliceError("delivery receipt after terminal result")
        if not isinstance(record, dict) or set(record) != {"assignment", "repair_attempt", "result", "candidate_after", "token_usage", "error"}:
            raise DeliverySliceError("invalid delivery receipt fields")
        if type(record["repair_attempt"]) is not int or record["repair_attempt"] != repair:
            raise DeliverySliceError("invalid delivery repair history")
        assignment = DeliveryAssignment(**record["assignment"])
        if (assignment.step != steps[step_index] or assignment.task_id != data["task_id"]
                or assignment.input_fingerprint != data["input_fingerprint"]
                or assignment.candidate_fingerprint != candidate
                or not isinstance(assignment.dispatch_id, str) or not assignment.dispatch_id
                or assignment.dispatch_id in seen):
            raise DeliverySliceError("invalid delivery receipt chain")
        seen.add(assignment.dispatch_id)
        usage = record["token_usage"]
        if usage is not None and (type(usage) is not int or usage < 0):
            raise DeliverySliceError("invalid delivery receipt usage")
        if record["error"] is not None:
            if not isinstance(record["error"], str) or not record["error"] or record["result"] is not None:
                raise DeliverySliceError("invalid delivery failure receipt")
            terminal = True
        elif record["result"] is None:
            if index != len(records) - 1 or record["candidate_after"] is not None or usage is not None:
                raise DeliverySliceError("invalid pending delivery receipt")
            terminal = True
        else:
            result = validate_delivery_result(json.dumps(record["result"]), assignment)
            after = record["candidate_after"]
            if not isinstance(after, str) or not after:
                raise DeliverySliceError("invalid delivery candidate receipt")
            if assignment.step != "implementer" and after != candidate:
                raise DeliverySliceError("mutating delivery review receipt")
            candidate = after
            if result["verdict"] in {"BLOCKED", "NEEDS_CONTEXT"}:
                terminal = True
            elif result["verdict"] in PASSING_VERDICTS:
                step_index += 1
            else:
                repair += 1
                step_index = 0
