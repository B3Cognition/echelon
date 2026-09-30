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
MAX_BROWSER_REQUESTS = 4  # Initial implementation's bounded image recaptures.
MAX_BROWSER_REPAIR_REQUESTS = 2  # Fresh captures for each review-guided repair.


def browser_request_limit(repair: int) -> int:
    return MAX_BROWSER_REQUESTS if repair == 0 else MAX_BROWSER_REPAIR_REQUESTS


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
        self._validate_checkpoint_paths(data)
        self._validator(data)
        return data

    def save(self, data):
        self._validate_checkpoint_paths(data)
        self._validator(data)
        write_json_atomic(self.path, data, trusted_root=self.root)

    def _validate_checkpoint_paths(self, data):
        """Constrain receipt IO before schema validation reads any checkpoints."""
        if not isinstance(data, dict) or data.get("schema_version") != 3:
            return
        checks = data.get("browser_checks")
        if not isinstance(checks, list):
            raise DeliverySliceError("invalid browser checkpoints")
        root = self.root.parent
        if root.is_symlink():
            raise DeliverySliceError("unsafe browser checkpoint evidence root")
        root = root.resolve(strict=True)
        for check in checks:
            ref = check.get("receipt") if isinstance(check, dict) else None
            if ref is None:
                continue
            if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
                raise DeliverySliceError("invalid browser checkpoint receipt")
            path = Path(ref["path"])
            if not path.is_absolute() or not path.is_relative_to(root) or ".." in path.parts:
                raise DeliverySliceError("unsafe browser checkpoint receipt path")
            relative = path.relative_to(root)
            if any((root / Path(*relative.parts[:i])).is_symlink()
                   for i in range(1, len(relative.parts) + 1)):
                raise DeliverySliceError("unsafe browser checkpoint receipt path")


def delivery_journal_position(data: dict) -> tuple[int, int]:
    """Validate the whole chain and return its consumed round/capture position."""
    return _validate(data)


def browser_checkpoint_id(operation_id: str, purpose: str, dispatch_id: str, ordinal: int) -> str:
    return hashlib.sha256(json.dumps([operation_id, purpose, dispatch_id, ordinal]).encode()).hexdigest()


def browser_checkpoint_observation(data: dict, check: dict):
    from harness.browser_baseline_evidence import BrowserBaselineEvidenceRef, read_browser_baseline_observation
    ref = check["receipt"]
    return read_browser_baseline_observation(
        BrowserBaselineEvidenceRef(Path(ref["path"]), ref["receipt_sha256"]),
        operation_id=data["run_id"], task_id=data["task_id"],
        candidate_fingerprint=check["candidate_fingerprint"],
        input_fingerprint=check["input_fingerprint"],
    )


def _validate(data):
    fields = {"schema_version", "run_id", "binding", "task_id", "input_fingerprint",
              "protected_fingerprint", "candidate_fingerprint", "progress_input_fingerprint",
              "progress_protected_fingerprint", "budget_limit", "records"}
    current = isinstance(data, dict) and data.get("schema_version") == 3
    extra = {"continuation", "browser_checks", "require_browser_recheck"} if current else set()
    if (not isinstance(data, dict) or set(data) != fields | extra
            or type(data["schema_version"]) is not int or data["schema_version"] not in {2, 3}):
        raise DeliverySliceError("invalid delivery journal schema")
    if any(not isinstance(data[key], str) or not data[key] for key in fields - {"schema_version", "budget_limit", "records"}):
        raise DeliverySliceError("invalid delivery journal identity")
    budget = data["budget_limit"]
    if budget is not None and (type(budget) not in (int, float) or not math.isfinite(budget)):
        raise DeliverySliceError("invalid delivery journal budget")
    steps = ["implementer", "spec_guard", "code_reviewer", "test_guardian"]
    records = data["records"]
    # Each round may include captures, one correction per capture, and review
    # context rechecks in addition to the four ordinary role receipts.
    if not isinstance(records, list) or len(records) > MAX_GATE_ROUNDS * 12:
        raise DeliverySliceError("invalid delivery journal receipts")
    checks = data.get("browser_checks", [])
    continuation = data.get("continuation")
    if current:
        if (type(data["require_browser_recheck"]) is not bool
                or not isinstance(checks, list) or len(checks) > MAX_GATE_ROUNDS * MAX_BROWSER_REQUESTS):
            raise DeliverySliceError("invalid browser checkpoint envelope")
        if continuation is not None:
            if (not isinstance(continuation, dict) or set(continuation) != {
                    "kind", "predecessors", "source_task_id", "anchor_dispatch_id",
                    "entry_candidate_fingerprint", "entry_input_fingerprint", "allowance"}
                    or continuation["kind"] not in {"refresh", "owner_retry", "return"}
                    or (continuation["kind"] != "owner_retry" and continuation["source_task_id"] != data["task_id"])
                    or (continuation["kind"] == "owner_retry" and (not data["require_browser_recheck"]
                        or continuation["source_task_id"] == data["task_id"]))
                    or continuation["entry_candidate_fingerprint"] != data["candidate_fingerprint"]
                    or continuation["entry_input_fingerprint"] != data["input_fingerprint"]):
                raise DeliverySliceError("invalid browser continuation")
            allowance = continuation["allowance"]
            if (not isinstance(allowance, dict) or set(allowance) != {
                    "repair_attempt", "browser_requests_in_round", "tokens_consumed", "usage_known", "token_limit"}
                    or any(type(allowance[key]) is not int or allowance[key] < 0 for key in (
                        "repair_attempt", "browser_requests_in_round", "tokens_consumed"))
                    or type(allowance["usage_known"]) is not bool):
                raise DeliverySliceError("invalid browser continuation allowance")
        for check in checks:
            check_fields = {"checkpoint_id", "purpose", "after_dispatch_id", "candidate_fingerprint",
                            "input_fingerprint", "repair_attempt", "request_ordinal", "receipt"}
            if (not isinstance(check, dict) or set(check) != check_fields
                    or check["purpose"] not in {"owner_recheck", "refresh", "requested", "return_capture"}
                    or (check["purpose"] == "owner_recheck" and not data["require_browser_recheck"])
                    or (check["purpose"] in {"refresh", "return_capture"} and continuation is None)
                    or any(not isinstance(check[key], str) or not check[key]
                           for key in ("after_dispatch_id", "candidate_fingerprint", "input_fingerprint"))
                    or check["input_fingerprint"] != data["input_fingerprint"]
                    or type(check["repair_attempt"]) is not int
                    or type(check["request_ordinal"]) is not int
                    or check["checkpoint_id"] != browser_checkpoint_id(
                        data["run_id"], check["purpose"], check["after_dispatch_id"], check["request_ordinal"])):
                raise DeliverySliceError("invalid browser checkpoint")
            ref = check["receipt"]
            if ref is not None and (not isinstance(ref, dict) or set(ref) != {"path", "receipt_sha256"}
                                    or any(not isinstance(v, str) or not v for v in ref.values())):
                raise DeliverySliceError("invalid browser checkpoint receipt")
    check_cursor = 0
    step_index, repair = 0, 0
    candidate = data["candidate_fingerprint"]
    seen = set()
    terminal = False
    review_rejected = False
    rechecks_for_step = 0
    recheck_audit_paths = None
    browser_requests_in_round = 0
    if continuation is not None:
        repair = continuation["allowance"]["repair_attempt"]
        browser_requests_in_round = continuation["allowance"]["browser_requests_in_round"]
        if continuation["kind"] != "owner_retry":
            purpose = "refresh" if continuation["kind"] == "refresh" else "return_capture"
            completed = None
            for check in checks:
                if check["purpose"] != purpose:
                    break
                if (completed is not None or check["repair_attempt"] != repair
                        or check["after_dispatch_id"] != continuation["anchor_dispatch_id"]
                        or check["request_ordinal"] != browser_requests_in_round + 1
                        or check["request_ordinal"] > browser_request_limit(repair)):
                    raise DeliverySliceError("invalid browser continuation checkpoint sequence")
                browser_requests_in_round += 1
                check_cursor += 1
                if check["receipt"] is not None:
                    completed = browser_checkpoint_observation(data, check)
            if records and completed is None:
                raise DeliverySliceError("browser continuation capture incomplete")
    last_browser_evidence = None
    last_browser_candidate = None
    browser_correction_used = False
    for index, record in enumerate(records):
        if terminal or repair >= MAX_GATE_ROUNDS or step_index >= len(steps):
            raise DeliverySliceError("delivery receipt after terminal result")
        base_fields = {"assignment", "repair_attempt", "raw_result", "result", "candidate_after", "token_usage", "error"}
        if (not isinstance(record, dict) or not base_fields <= set(record)
                or set(record) - base_fields - {"browser_evidence", "review_evidence", "baseline_installation"}):
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
        if "baseline_installation" in record:
            installation = record["baseline_installation"]
            if (not current or index != 0 or assignment.step != "implementer"
                    or continuation is None or continuation["kind"] not in {"refresh", "return"}
                    or not isinstance(installation, dict)
                    or set(installation) != {"checkpoint_id", "candidate_fingerprint"}
                    or not isinstance(installation["candidate_fingerprint"], str)
                    or len(installation["candidate_fingerprint"]) != 64
                    or any(c not in "0123456789abcdef" for c in installation["candidate_fingerprint"])):
                raise DeliverySliceError("invalid baseline installation intent")
            checkpoint = next((check for check in checks[:check_cursor]
                               if check["checkpoint_id"] == installation["checkpoint_id"]), None)
            if (checkpoint is None or checkpoint["purpose"] not in {"refresh", "return_capture"}
                    or checkpoint["receipt"] is None):
                raise DeliverySliceError("baseline installation checkpoint missing")
            proposal = browser_checkpoint_observation(data, checkpoint)
            if not proposal.verification_passed or not proposal.images:
                raise DeliverySliceError("baseline installation requires passing proposals")
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
                    browser_requests_in_round += 1
                    last_browser_evidence = evidence
                    last_browser_candidate = after
                    browser_correction_used = False
                    if current:
                        completed = None
                        ordinal = browser_requests_in_round
                        while check_cursor < len(checks):
                            check = checks[check_cursor]
                            if check["after_dispatch_id"] != assignment.dispatch_id:
                                break
                            if (check["purpose"] != "requested" or completed is not None
                                    or check["repair_attempt"] != repair or check["request_ordinal"] != ordinal
                                    or ordinal > browser_request_limit(repair)):
                                raise DeliverySliceError("invalid requested browser checkpoint sequence")
                            browser_requests_in_round = ordinal
                            ordinal += 1
                            check_cursor += 1
                            if check["receipt"] is not None:
                                browser_checkpoint_observation(data, check)
                                completed = check["receipt"]
                        if evidence is not None and evidence != completed:
                            raise DeliverySliceError("requested browser checkpoint receipt mismatch")
                if browser_requests_in_round > browser_request_limit(repair):
                    terminal = True
                elif index < len(records) - 1 and evidence is None:
                    raise DeliverySliceError("browser evidence missing before continuation")
            elif assignment.step == "implementer" and result["verdict"] not in PASSING_VERDICTS:
                repair += 1
                browser_requests_in_round = 0
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
                        browser_requests_in_round = 0
                        step_index = 0
                        review_rejected = False
                    else:
                        terminal = True
                        if current and data["require_browser_recheck"]:
                            completed = None
                            while check_cursor < len(checks):
                                check = checks[check_cursor]
                                if check["after_dispatch_id"] != assignment.dispatch_id:
                                    break
                                if (completed is not None or check["repair_attempt"] != repair
                                        or check["request_ordinal"] != browser_requests_in_round + 1
                                        or check["request_ordinal"] > browser_request_limit(repair)):
                                    raise DeliverySliceError("invalid browser checkpoint sequence")
                                browser_requests_in_round += 1
                                check_cursor += 1
                                if check["receipt"] is not None:
                                    completed = browser_checkpoint_observation(data, check)
                            if completed is not None and not completed.verification_passed:
                                repair += 1
                                browser_requests_in_round = 0
                                step_index = 0
                                terminal = False
    if check_cursor != len(checks):
        raise DeliverySliceError("unanchored browser checkpoint")
    return repair, browser_requests_in_round
