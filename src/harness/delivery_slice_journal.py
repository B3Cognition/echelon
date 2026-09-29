"""Serialized, fail-closed receipt authority for one delivery operation."""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import stat

from harness.delivery_slice import (DeliveryAssignment, DeliverySliceError, PASSING_VERDICTS,
                                    _valid_review_test_path, bind_delivery_result)
from harness.durable_json import write_json_atomic


MAX_GATE_ROUNDS = 5  # Initial implementation plus four review-guided repairs.
MAX_BROWSER_REQUESTS = 4  # Bounded recaptures after image inspection and repair.


class DeliverySliceJournal:
    def __init__(self, root: Path, operation_id: str, *, validator=None):
        if not isinstance(operation_id, str) or not operation_id:
            raise DeliverySliceError("invalid delivery operation identity")
        self.root = root / hashlib.sha256(operation_id.encode()).hexdigest()
        self.path = self.root / "journal.json"
        self._fd = None
        self._validator = validator or _validate

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
        self._validator(data)
        return data

    def save(self, data):
        self._validator(data)
        write_json_atomic(self.path, data, trusted_root=self.root)


def _validate(data):
    fields = {"schema_version", "run_id", "binding", "task_id", "input_fingerprint",
              "protected_fingerprint", "candidate_fingerprint", "progress_input_fingerprint",
              "progress_protected_fingerprint", "budget_limit", "records"}
    if (not isinstance(data, dict) or set(data) != fields
            or type(data["schema_version"]) is not int or data["schema_version"] != 2):
        raise DeliverySliceError("invalid delivery journal schema")
    if any(not isinstance(data[key], str) or not data[key] for key in fields - {"schema_version", "budget_limit", "records"}):
        raise DeliverySliceError("invalid delivery journal identity")
    budget = data["budget_limit"]
    if budget is not None and (type(budget) not in (int, float) or not math.isfinite(budget)):
        raise DeliverySliceError("invalid delivery journal budget")
    steps = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    records = data["records"]
    if not isinstance(records, list) or len(records) > MAX_GATE_ROUNDS * 6 + 2:
        raise DeliverySliceError("invalid delivery journal receipts")
    step_index, repair = 0, 0
    candidate = data["candidate_fingerprint"]
    seen = set()
    terminal = False
    review_rejected = False
    rechecks_for_step = 0
    recheck_audit_paths = None
    browser_requests = 0
    last_browser_evidence = None
    last_browser_candidate = None
    browser_correction_used = False
    for index, record in enumerate(records):
        if terminal or repair >= MAX_GATE_ROUNDS or step_index >= len(steps):
            raise DeliverySliceError("delivery receipt after terminal result")
        base_fields = {"assignment", "repair_attempt", "raw_result", "result", "candidate_after", "token_usage", "error"}
        if (not isinstance(record, dict) or not base_fields <= set(record)
                or set(record) - base_fields - {"browser_evidence", "review_evidence"}):
            raise DeliverySliceError("invalid delivery receipt fields")
        if "browser_evidence" in record and "review_evidence" in record:
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
        raw_result = record["raw_result"]
        if raw_result is not None and (
            not isinstance(raw_result, str)
            or len(raw_result.encode("utf-8")) > 100_000
        ):
            raise DeliverySliceError("invalid raw delivery result")
        if record["error"] is not None:
            if (not isinstance(record["error"], str) or not record["error"]
                    or record["result"] is not None or "review_evidence" in record):
                raise DeliverySliceError("invalid delivery failure receipt")
            terminal = True
        elif record["result"] is None:
            if (index != len(records) - 1 or record["candidate_after"] is not None
                    or usage is not None or raw_result is not None
                    or "review_evidence" in record):
                raise DeliverySliceError("invalid pending delivery receipt")
            terminal = True
        else:
            if raw_result is None:
                raise DeliverySliceError("missing raw delivery result")
            result = bind_delivery_result(raw_result, assignment)
            if result != record["result"]:
                raise DeliverySliceError("delivery result binding mismatch")
            review_evidence = record.get("review_evidence")
            if "review_evidence" in record and review_evidence is None:
                raise DeliverySliceError("invalid delivery review evidence")
            if rechecks_for_step and review_evidence is None:
                raise DeliverySliceError("delivery recheck missing review evidence")
            if review_evidence is not None:
                if (assignment.step not in {"spec_guard", "test_guardian"}
                        or not isinstance(review_evidence, dict)
                        or set(review_evidence) != {"audit_test_paths", "incomplete"}):
                    raise DeliverySliceError("invalid delivery review evidence")
                audit_paths = review_evidence["audit_test_paths"]
                if (not isinstance(audit_paths, list) or len(audit_paths) > 200
                        or any(not _valid_review_test_path(path) for path in audit_paths)
                        or audit_paths != sorted(set(audit_paths))
                        or type(review_evidence["incomplete"]) is not bool):
                    raise DeliverySliceError("invalid delivery review evidence")
                missing = set(audit_paths) - set(result.get("reviewed_test_paths", []))
                if review_evidence["incomplete"] != bool(missing):
                    raise DeliverySliceError("delivery review evidence mismatch")
                if rechecks_for_step and audit_paths != recheck_audit_paths:
                    raise DeliverySliceError("delivery recheck audit set changed")
                if rechecks_for_step == 0 and result["verdict"] in PASSING_VERDICTS:
                    if missing:
                        raise DeliverySliceError("passing review cannot start evidence recheck")
                elif rechecks_for_step == 0 and result["verdict"] in {"BLOCKED", "NEEDS_CONTEXT"}:
                    raise DeliverySliceError("blocked review cannot start evidence recheck")
            evidence = record.get("browser_evidence")
            if evidence is not None and (
                result["verdict"] != "BROWSER_EVIDENCE_REQUIRED"
                or not isinstance(evidence, dict)
                or set(evidence) != {"path", "receipt_sha256"}
                or any(not isinstance(value, str) or not value for value in evidence.values())
            ):
                raise DeliverySliceError("invalid browser evidence reference")
            after = record["candidate_after"]
            if not isinstance(after, str) or not after:
                raise DeliverySliceError("invalid delivery candidate receipt")
            if assignment.step != "implementer" and after != candidate:
                raise DeliverySliceError("mutating delivery review receipt")
            candidate = after
            if result["verdict"] in {"BLOCKED", "NEEDS_CONTEXT"}:
                terminal = True
            elif result["verdict"] == "BROWSER_EVIDENCE_REQUIRED":
                reused = (
                    evidence is not None
                    and evidence == last_browser_evidence
                    and after == last_browser_candidate
                )
                if reused:
                    if browser_correction_used:
                        raise DeliverySliceError("repeated browser evidence correction")
                    browser_correction_used = True
                else:
                    browser_requests += 1
                    last_browser_evidence = evidence
                    last_browser_candidate = after
                    browser_correction_used = False
                if browser_requests > MAX_BROWSER_REQUESTS:
                    terminal = True
                elif index < len(records) - 1 and evidence is None:
                    raise DeliverySliceError("browser evidence missing before continuation")
            elif assignment.step == "implementer" and result["verdict"] not in PASSING_VERDICTS:
                repair += 1
                step_index = 0
            else:
                if review_evidence is not None and review_evidence["incomplete"]:
                    if rechecks_for_step:
                        terminal = True
                    else:
                        rechecks_for_step = 1
                        recheck_audit_paths = audit_paths
                    continue
                if result["verdict"] not in PASSING_VERDICTS:
                    review_rejected = True
                step_index += 1
                rechecks_for_step = 0
                recheck_audit_paths = None
                if step_index == len(steps):
                    if review_rejected:
                        repair += 1
                        step_index = 0
                        review_rejected = False
                    else:
                        terminal = True
