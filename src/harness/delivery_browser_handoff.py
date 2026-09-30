"""Read-only authority checks for a task-bound browser repair handoff."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
from pathlib import Path
import re

from harness.browser_baseline_evidence import (
    BrowserBaselineEvidenceRef, read_browser_baseline_observation,
)
from harness.delivery_slice import (
    DeliverySliceError, resolve_delivery_failure_owner, select_delivery_repair_task,
)
from harness.delivery_slice_journal import DeliverySliceJournal, delivery_journal_position


def _digest_valid(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def journal_sha256(data: dict) -> str:
    """The existing slice journal digest convention, not the receipt convention."""
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


@dataclass(frozen=True)
class JournalRef:
    operation_id: str
    journal_sha256: str

    def __post_init__(self):
        if (not isinstance(self.operation_id, str) or not self.operation_id
                or not _digest_valid(self.journal_sha256)):
            raise DeliverySliceError("invalid browser handoff journal reference")

    def as_mapping(self) -> dict[str, str]:
        return {"operation_id": self.operation_id, "journal_sha256": self.journal_sha256}

    @classmethod
    def from_mapping(cls, value: object) -> JournalRef:
        if not isinstance(value, dict) or set(value) != {"operation_id", "journal_sha256"}:
            raise DeliverySliceError("invalid browser handoff journal reference")
        return cls(**value)


@dataclass(frozen=True)
class BrowserRepairRequest:
    source: JournalRef
    dispatch_id: str
    receipt: BrowserBaselineEvidenceRef

    def __post_init__(self):
        if (not isinstance(self.source, JournalRef)
                or not isinstance(self.dispatch_id, str) or not self.dispatch_id
                or not isinstance(self.receipt, BrowserBaselineEvidenceRef)
                or not isinstance(self.receipt.path, Path) or not self.receipt.path.is_absolute()
                or not _digest_valid(self.receipt.receipt_sha256)):
            raise DeliverySliceError("invalid browser repair request")

    def as_mapping(self) -> dict[str, object]:
        return {"source": self.source.as_mapping(), "dispatch_id": self.dispatch_id,
                "receipt": {"path": str(self.receipt.path), "receipt_sha256": self.receipt.receipt_sha256}}

    @classmethod
    def from_mapping(cls, value: object) -> BrowserRepairRequest:
        if not isinstance(value, dict) or set(value) != {"source", "dispatch_id", "receipt"}:
            raise DeliverySliceError("invalid browser repair request")
        receipt = value["receipt"]
        if (not isinstance(receipt, dict) or set(receipt) != {"path", "receipt_sha256"}
                or not isinstance(receipt["path"], str)):
            raise DeliverySliceError("invalid browser repair receipt reference")
        return cls(JournalRef.from_mapping(value["source"]), value["dispatch_id"],
                   BrowserBaselineEvidenceRef(Path(receipt["path"]), receipt["receipt_sha256"]))


@dataclass(frozen=True)
class ContinuationAllowance:
    repair_attempt: int
    browser_requests_in_round: int
    tokens_consumed: int
    usage_known: bool
    token_limit: float | None


def handoff_operation_id(request: BrowserRepairRequest, stage: str) -> str:
    if stage not in {"owner", "refresh", "return"}:
        raise DeliverySliceError("invalid browser handoff stage")
    return hashlib.sha256(json.dumps({
        "source_operation": request.source.operation_id,
        "source_journal": request.source.journal_sha256,
        "dispatch": request.dispatch_id, "receipt": request.receipt.receipt_sha256,
        "stage": stage,
    }, sort_keys=True).encode()).hexdigest()


def resolve_browser_repair(
    request: BrowserRepairRequest, *, evidence_root: Path, spec_dir: Path,
    candidate_fingerprint: str, input_fingerprint: str,
    allowed_task_ids: set[str] | None,
) -> str:
    """Authenticate completed evidence before resolving its unique task owner.

    The caller owns the active-operation lock and full candidate/protected-input
    check. This read must not reacquire that lock or create missing evidence.
    """
    try:
        root = Path(evidence_root)
        journal = DeliverySliceJournal(root, request.source.operation_id)
        if root.is_symlink() or journal.root.is_symlink() or not root.is_dir():
            raise DeliverySliceError("unsafe browser handoff evidence root")
        data = journal.load(required=True)
        if (not hmac.compare_digest(journal_sha256(data), request.source.journal_sha256)
                or data["input_fingerprint"] != input_fingerprint or not data["records"]):
            raise DeliverySliceError("browser handoff journal binding mismatch")
        record = data["records"][-1]
        if (record["assignment"]["dispatch_id"] != request.dispatch_id
                or record["error"] is not None or record["result"] is None
                or record["result"]["verdict"] != "BROWSER_EVIDENCE_REQUIRED"
                or record.get("browser_evidence") != request.as_mapping()["receipt"]):
            raise DeliverySliceError("browser handoff requires the current completed capture")
        path = request.receipt.path
        relative = path.relative_to(root.resolve(strict=True))
        if any((root / Path(*relative.parts[:index])).is_symlink()
               for index in range(1, len(relative.parts) + 1)):
            raise DeliverySliceError("unsafe browser handoff receipt path")
        observation = read_browser_baseline_observation(
            request.receipt, operation_id=request.source.operation_id, task_id=data["task_id"],
            candidate_fingerprint=candidate_fingerprint, input_fingerprint=input_fingerprint,
        )
        if observation.verification_passed or observation.verification_failures is None:
            raise DeliverySliceError("browser handoff requires structured failed capture evidence")
        feedback = {"failures": observation.verification_failures}
        selection = resolve_delivery_failure_owner(spec_dir, feedback, allowed_task_ids)
        if selection["task_id"] == data["task_id"]:
            return selection["task_id"]
        return select_delivery_repair_task(spec_dir, feedback, allowed_task_ids)["task_id"]
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, DeliverySliceError):
            raise
        raise DeliverySliceError(f"browser handoff evidence unavailable: {exc}") from exc


def continuation_allowance(journal: dict, *, token_limit: float | None) -> ContinuationAllowance:
    """Derive consumption without forgiving overshoot or resetting any limit."""
    repair, requests = delivery_journal_position(journal)
    limits = [value for value in (journal["budget_limit"], token_limit) if value is not None]
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in limits):
        raise DeliverySliceError("invalid browser continuation budget")
    limit = min(limits) if limits else None
    known = all(record["token_usage"] is not None for record in journal["records"])
    if limit is not None and not known:
        raise DeliverySliceError("delivery_usage_unknown_with_finite_budget")
    return ContinuationAllowance(repair, requests,
                                 sum(record["token_usage"] or 0 for record in journal["records"]),
                                 known, limit)
