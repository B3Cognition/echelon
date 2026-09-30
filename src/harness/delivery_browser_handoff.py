"""Read-only authority checks for a task-bound browser repair handoff."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import hmac
import json
import math
from pathlib import Path
import re

from harness.browser_baseline_evidence import (
    BrowserBaselineEvidenceRef, read_browser_baseline_observation, validate_historical_browser_baseline,
)
from harness.delivery_slice import (
    DeliverySliceError, resolve_delivery_failure_owner, select_delivery_repair_task,
)
from harness.delivery_slice_journal import (
    DeliverySliceJournal, delivery_journal_position, browser_checkpoint_observation,
)


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
                or data["input_fingerprint"] != input_fingerprint):
            raise DeliverySliceError("browser handoff journal binding mismatch")
        record = data["records"][-1] if data["records"] else None
        checks = data.get("browser_checks", [])
        checkpoint = (checks[-1] if checks and checks[-1]["after_dispatch_id"] == request.dispatch_id
                      and checks[-1]["receipt"] == request.as_mapping()["receipt"] else None)
        continuation = data.get("continuation")
        if continuation is not None:
            validate_browser_continuation(continuation, evidence_root=root,
                candidate_fingerprint=data["candidate_fingerprint"], input_fingerprint=data["input_fingerprint"])
        entry_capture = (record is None and continuation is not None and checkpoint is not None
                         and checkpoint["after_dispatch_id"] == continuation["anchor_dispatch_id"])
        if not entry_capture and (record is None or record["assignment"]["dispatch_id"] != request.dispatch_id
                or record["error"] is not None or record["result"] is None
                or (checkpoint is None and (
                    record["result"]["verdict"] != "BROWSER_EVIDENCE_REQUIRED"
                    or record.get("browser_evidence") != request.as_mapping()["receipt"]))):
            raise DeliverySliceError("browser handoff requires the current completed capture")
        path = request.receipt.path
        relative = path.relative_to(root.resolve(strict=True))
        if any((root / Path(*relative.parts[:index])).is_symlink()
               for index in range(1, len(relative.parts) + 1)):
            raise DeliverySliceError("unsafe browser handoff receipt path")
        observation = read_browser_baseline_observation(
            request.receipt, operation_id=data["run_id"] if data["schema_version"] == 3 else request.source.operation_id,
            task_id=data["task_id"],
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
    carried = journal.get("continuation")
    consumed = sum(record["token_usage"] or 0 for record in journal["records"])
    if carried is not None:
        known = known and carried["allowance"]["usage_known"]
        consumed += carried["allowance"]["tokens_consumed"]
    if limit is not None and not known:
        raise DeliverySliceError("delivery_usage_unknown_with_finite_budget")
    return ContinuationAllowance(repair, requests, consumed, known, limit)


def load_browser_predecessor(reference: JournalRef, evidence_root: Path) -> dict:
    journal = DeliverySliceJournal(Path(evidence_root), reference.operation_id)
    if Path(evidence_root).is_symlink() or journal.root.is_symlink():
        raise DeliverySliceError("unsafe browser predecessor directory")
    data = journal.load(required=True)
    if journal_sha256(data) != reference.journal_sha256:
        raise DeliverySliceError("browser predecessor digest changed")
    return data


def prepare_browser_continuation(*, kind: str, predecessors: list[JournalRef], evidence_root: Path,
                                 candidate_fingerprint: str, input_fingerprint: str,
                                 token_limit: float | None, _depth: int = 0) -> dict:
    """Derive an immutable entry checkpoint; no selection or dispatch happens here."""
    if (_depth > 3 or kind not in {"refresh", "owner_retry", "return"}
            or len(predecessors) != (2 if kind == "return" else 1)):
        raise DeliverySliceError("invalid browser continuation lineage")
    source = load_browser_predecessor(predecessors[0], evidence_root)
    source_entry = source.get("continuation")
    if source_entry is not None:
        if kind == "refresh" or source_entry["kind"] != "refresh":
            raise DeliverySliceError("browser continuation cannot nest owner repair")
        validate_browser_continuation(source_entry, evidence_root=evidence_root,
            candidate_fingerprint=source["candidate_fingerprint"],
            input_fingerprint=source["input_fingerprint"], _depth=_depth + 1)
    records = source["records"]
    source_checks = source.get("browser_checks", [])
    if records:
        last = records[-1]
        if (last["error"] is not None or last["result"] is None
                or last["result"]["verdict"] != "BROWSER_EVIDENCE_REQUIRED"):
            raise DeliverySliceError("browser continuation requires a completed request")
        source_candidate = last["candidate_after"]
        anchor = last["assignment"]["dispatch_id"]
    elif source_entry is not None and source_checks and source_checks[-1]["receipt"] is not None:
        source_candidate = source["candidate_fingerprint"]
        anchor = source_checks[-1]["after_dispatch_id"]
    else:
        raise DeliverySliceError("browser continuation requires completed capture evidence")
    if (source["input_fingerprint"] != input_fingerprint
            or kind != "return" and source_candidate != candidate_fingerprint):
        raise DeliverySliceError("browser continuation requires an unchanged completed request")
    if kind == "refresh":
        retained = next((row for row in reversed(records) if row.get("browser_evidence") is not None), None)
        if retained is None or retained["candidate_after"] != source_candidate:
            raise DeliverySliceError("browser continuation missing current evidence")
        reference = retained["browser_evidence"]
        path = Path(reference["path"])
        root = Path(evidence_root).resolve(strict=True)
        relative = path.relative_to(root)
        if any((root / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)):
            raise DeliverySliceError("unsafe browser continuation evidence")
        validate_historical_browser_baseline(
            BrowserBaselineEvidenceRef(path, reference["receipt_sha256"]),
            operation_id=predecessors[0].operation_id, task_id=source["task_id"],
            input_fingerprint=input_fingerprint,
        )
        if json.loads(path.read_text())["schema_version"] != 2:
            raise DeliverySliceError("browser continuation refresh requires old evidence")
    allowance = continuation_allowance(source, token_limit=token_limit)
    if kind == "owner_retry":
        allowance = replace(allowance, repair_attempt=0, browser_requests_in_round=0)
    elif kind == "return":
        owner = load_browser_predecessor(predecessors[1], evidence_root)
        owner_entry = owner.get("continuation")
        if (owner_entry is None or owner_entry["kind"] != "owner_retry"
                or owner_entry["predecessors"] != [predecessors[0].as_mapping()]
                or not owner["records"] or owner["records"][-1]["candidate_after"] != candidate_fingerprint
                or owner["input_fingerprint"] != input_fingerprint or not owner["require_browser_recheck"]
                or not owner["browser_checks"] or owner["browser_checks"][-1]["receipt"] is None
                or owner["browser_checks"][-1]["purpose"] != "owner_recheck"
                or owner["browser_checks"][-1]["after_dispatch_id"] != owner["records"][-1]["assignment"]["dispatch_id"]
                or not browser_checkpoint_observation(owner, owner["browser_checks"][-1]).verification_passed):
            raise DeliverySliceError("browser continuation requires an accepted owner recheck")
        validate_browser_continuation(owner_entry, evidence_root=evidence_root,
            candidate_fingerprint=owner["candidate_fingerprint"], input_fingerprint=input_fingerprint,
            _depth=_depth + 1)
        owner_allowance = continuation_allowance(owner, token_limit=token_limit)
        allowance = replace(owner_allowance, repair_attempt=allowance.repair_attempt,
                            browser_requests_in_round=allowance.browser_requests_in_round)
    return {"kind": kind, "predecessors": [ref.as_mapping() for ref in predecessors],
            "anchor_dispatch_id": anchor,
            "source_task_id": source["task_id"], "entry_candidate_fingerprint": candidate_fingerprint,
            "entry_input_fingerprint": input_fingerprint, "allowance": asdict(allowance)}


def validate_browser_continuation(value: dict, *, evidence_root: Path,
                                  candidate_fingerprint: str, input_fingerprint: str, _depth: int = 0) -> None:
    expected = prepare_browser_continuation(
        kind=value["kind"], predecessors=[JournalRef.from_mapping(ref) for ref in value["predecessors"]],
        evidence_root=evidence_root, candidate_fingerprint=candidate_fingerprint,
        input_fingerprint=input_fingerprint, token_limit=value["allowance"]["token_limit"],
        _depth=_depth,
    )
    if value != expected:
        raise DeliverySliceError("browser continuation allowance or binding changed")
