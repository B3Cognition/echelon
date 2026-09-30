"""In-memory accumulation of accepted provider work for one Phase A node."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from threading import RLock
from types import MappingProxyType
from typing import Literal

from harness.phase_a_provider_assignments import CompiledProviderAssignment
from harness.prepared_phase_result import detach_squad_agent_result
from harness.provider_dispatch_finalizer import (
    FinalizedProviderResult,
    ProviderDispatchReceipt,
)
from harness.squad_provider import SquadAgentResult


ManifestStatus = Literal["executed", "skipped", "deferred", "reused"]


@dataclass(frozen=True)
class ProviderExecutionManifestEntry:
    assignment_id: str
    occurrence_id: str
    contract_sha256: str
    status: ManifestStatus
    reason: str
    receipt_sha256: str | None
    reused_step_id: str | None
    reused_dispatch_id: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "assignment_id": self.assignment_id,
            "occurrence_id": self.occurrence_id,
            "contract_sha256": self.contract_sha256,
            "status": self.status,
            "reason": self.reason,
            "receipt_sha256": self.receipt_sha256,
            "reused_step_id": self.reused_step_id,
            "reused_dispatch_id": self.reused_dispatch_id,
        }


@dataclass(frozen=True)
class FinalizedPhaseExecution:
    result: SquadAgentResult
    manifest: tuple[ProviderExecutionManifestEntry, ...]
    receipts: tuple[dict[str, object], ...]
    accepted_results: tuple[SquadAgentResult, ...]
    projected_state_updates: Mapping[str, object]
    cost_usd_delta: float
    token_usage_delta: int = 0

    @property
    def manifest_sha256(self) -> str:
        payload = json.dumps(
            [entry.to_dict() for entry in self.manifest],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @property
    def verdict(self) -> str | None:
        return self.result.verdict

    @property
    def exit_code(self) -> int:
        return self.result.exit_code

    @property
    def state_updates(self) -> dict:
        return self.result.state_updates

    @property
    def echelon_result(self) -> dict | None:
        return self.result.echelon_result

    @property
    def blocked(self) -> bool:
        return self.result.blocked

    @property
    def raw_output(self) -> str:
        return self.result.raw_output

    @property
    def duration_ms(self) -> int:
        return self.result.duration_ms

    @property
    def timed_out(self) -> bool:
        return self.result.timed_out

    @property
    def cost_usd(self) -> float:
        return self.result.cost_usd

    @property
    def token_usage(self) -> int:
        return self.result.token_usage

    @property
    def quarantined_state_updates(self) -> dict:
        return self.result.quarantined_state_updates


@dataclass(frozen=True)
class _RecordedExecution:
    manifest: ProviderExecutionManifestEntry
    receipt: dict[str, object] | None = None
    result: SquadAgentResult | None = None


class PhaseExecutionAccumulator:
    """Mutable only within one executor invocation; freezes to detached values."""

    def __init__(self, phase_id: str) -> None:
        if type(phase_id) is not str or not phase_id:
            raise ValueError("phase execution requires a phase id")
        self.phase_id = phase_id
        self._records: dict[str, _RecordedExecution] = {}
        self._insertion_order: dict[str, int] = {}
        self._lock = RLock()

    def record(self, finalized: FinalizedProviderResult) -> None:
        receipt = finalized.receipt
        if receipt.phase_id != self.phase_id:
            raise ValueError("provider receipt belongs to another phase")
        receipt_dict = receipt.as_dict()
        detached = detach_squad_agent_result(finalized.result)
        entry = ProviderExecutionManifestEntry(
            assignment_id=receipt.assignment_id,
            occurrence_id=receipt.occurrence_id,
            contract_sha256=receipt.contract_sha256,
            status="executed",
            reason="",
            receipt_sha256=_receipt_sha256(receipt_dict),
            reused_step_id=None,
            reused_dispatch_id=None,
        )
        self._append(
            _RecordedExecution(
                manifest=entry,
                receipt=_detach_json_mapping(receipt_dict),
                result=detached,
            )
        )

    def skip(
        self,
        assignment: CompiledProviderAssignment,
        occurrence_id: str,
        reason: str,
    ) -> None:
        self._record_nonexecuted(assignment, occurrence_id, "skipped", reason)

    def defer(
        self,
        assignment: CompiledProviderAssignment,
        occurrence_id: str,
        reason: str,
    ) -> None:
        self._record_nonexecuted(assignment, occurrence_id, "deferred", reason)

    def reuse(
        self,
        assignment: CompiledProviderAssignment,
        occurrence_id: str,
        sealed_reference: Mapping[str, object],
    ) -> None:
        step_id = sealed_reference.get("step_id")
        dispatch_id = sealed_reference.get("dispatch_id")
        if type(step_id) is not str or not step_id:
            raise ValueError("sealed reuse requires a step_id")
        if type(dispatch_id) is not str or not dispatch_id:
            raise ValueError("sealed reuse requires a dispatch_id")
        entry = ProviderExecutionManifestEntry(
            assignment_id=assignment.assignment_id,
            occurrence_id=_valid_occurrence_id(occurrence_id),
            contract_sha256=_contract_sha256(assignment),
            status="reused",
            reason="sealed provider result reuse",
            receipt_sha256=None,
            reused_step_id=step_id,
            reused_dispatch_id=dispatch_id,
        )
        self._append(_RecordedExecution(manifest=entry))

    def project_state(self, base: Mapping[str, object]) -> dict[str, object]:
        projected = dict(base)
        for record in self._ordered_records():
            if record.result is not None:
                projected.update(record.result.state_updates)
        return projected

    def freeze(self, result: SquadAgentResult) -> FinalizedPhaseExecution:
        records = self._ordered_records()
        accepted = tuple(
            detach_squad_agent_result(record.result)
            for record in records
            if record.result is not None
        )
        receipts = tuple(
            _detach_json_mapping(record.receipt)
            for record in records
            if record.receipt is not None
        )
        projected: dict[str, object] = {}
        for accepted_result in accepted:
            projected.update(accepted_result.state_updates)
        return FinalizedPhaseExecution(
            result=detach_squad_agent_result(result),
            manifest=tuple(record.manifest for record in records),
            receipts=receipts,
            accepted_results=accepted,
            projected_state_updates=MappingProxyType(
                _detach_json_mapping(projected)
            ),
            cost_usd_delta=sum(item.cost_usd for item in accepted),
            token_usage_delta=sum(item.token_usage for item in accepted),
        )

    def _record_nonexecuted(
        self,
        assignment: CompiledProviderAssignment,
        occurrence_id: str,
        status: Literal["skipped", "deferred"],
        reason: str,
    ) -> None:
        if type(reason) is not str or not reason:
            raise ValueError(f"{status} manifest entry requires a reason")
        entry = ProviderExecutionManifestEntry(
            assignment_id=assignment.assignment_id,
            occurrence_id=_valid_occurrence_id(occurrence_id),
            contract_sha256=_contract_sha256(assignment),
            status=status,
            reason=reason,
            receipt_sha256=None,
            reused_step_id=None,
            reused_dispatch_id=None,
        )
        self._append(_RecordedExecution(manifest=entry))

    def _append(self, record: _RecordedExecution) -> None:
        occurrence_id = _valid_occurrence_id(record.manifest.occurrence_id)
        with self._lock:
            if occurrence_id in self._records:
                raise ValueError(f"duplicate provider occurrence {occurrence_id!r}")
            self._insertion_order[occurrence_id] = len(self._insertion_order)
            self._records[occurrence_id] = record

    def _ordered_records(self) -> tuple[_RecordedExecution, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._records.values(),
                    key=lambda record: _occurrence_order_key(
                        record.manifest.occurrence_id,
                        self._insertion_order[record.manifest.occurrence_id],
                    ),
                )
            )


def extend_phase_execution(
    execution: FinalizedPhaseExecution,
    finalized: FinalizedProviderResult,
    *,
    occurrence_id: str,
) -> FinalizedPhaseExecution:
    """Append one finalized direct-controller call to an immutable execution."""
    occurrence_id = _valid_occurrence_id(occurrence_id)
    receipt = finalized.receipt
    if receipt.occurrence_id != occurrence_id:
        receipt = replace(receipt, occurrence_id=occurrence_id)
        finalized = FinalizedProviderResult(result=finalized.result, receipt=receipt)
    if any(item.occurrence_id == occurrence_id for item in execution.manifest):
        raise ValueError(f"duplicate provider occurrence {occurrence_id!r}")
    receipt_dict = receipt.as_dict()
    appended_result = detach_squad_agent_result(finalized.result)
    manifest = (
        *execution.manifest,
        ProviderExecutionManifestEntry(
            assignment_id=receipt.assignment_id,
            occurrence_id=occurrence_id,
            contract_sha256=receipt.contract_sha256,
            status="executed",
            reason="",
            receipt_sha256=_receipt_sha256(receipt_dict),
            reused_step_id=None,
            reused_dispatch_id=None,
        ),
    )
    updates = dict(execution.projected_state_updates)
    updates.update(appended_result.state_updates)
    return FinalizedPhaseExecution(
        result=detach_squad_agent_result(execution.result),
        manifest=manifest,
        receipts=(*execution.receipts, _detach_json_mapping(receipt_dict)),
        accepted_results=(*execution.accepted_results, appended_result),
        projected_state_updates=MappingProxyType(_detach_json_mapping(updates)),
        cost_usd_delta=execution.cost_usd_delta + appended_result.cost_usd,
        token_usage_delta=execution.token_usage_delta + appended_result.token_usage,
    )


def empty_phase_execution(
    phase_id: str,
    result: SquadAgentResult,
) -> FinalizedPhaseExecution:
    return PhaseExecutionAccumulator(phase_id).freeze(result)


def _valid_occurrence_id(value: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("provider occurrence id must be a non-empty string")
    return value


def _contract_sha256(assignment: CompiledProviderAssignment) -> str:
    from harness.provider_output_publication import provider_artifact_contract_sha256

    return provider_artifact_contract_sha256(assignment.contract)


def _receipt_sha256(receipt: Mapping[str, object]) -> str:
    payload = json.dumps(
        receipt,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _detach_json_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return json.loads(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )


def _occurrence_order_key(occurrence_id: str, insertion: int) -> tuple[object, ...]:
    fixed = {
        "ordinary": (10, 0),
        # WHY3 is the first declared Stage 1 assignment in the checked-in
        # consensus graph even though its stable occurrence has a semantic name.
        "why3/initial": (20, 0),
        "sage/work-assessment": (40, 0),
        "why3/final-revalidation": (70, 0),
    }
    if occurrence_id in fixed:
        group, index = fixed[occurrence_id]
        return (group, index, occurrence_id)
    match = re.fullmatch(
        r"(pre-dispatch|stage1|stage2|specialist)/(\d+)", occurrence_id
    )
    if match:
        group_order = {
            "pre-dispatch": 0,
            "stage1": 20,
            "stage2": 60,
            "specialist": 20,
        }[match.group(1)]
        return (group_order, int(match.group(2)), occurrence_id)
    return (100, insertion, occurrence_id)
