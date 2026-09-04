"""Authority-first, idempotent recovery planning for protocol 2.8."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from harness.re_v2.protocol_22.schema import (
    digest_value,
    safe_id,
    sorted_unique_digests,
)
from harness.re_v2.protocol_28.events import Protocol28ReplayState


class Protocol28RecoveryError(RuntimeError):
    """Raised when recovery facts are not closed or contradict durable authority."""


def _digest(value: str, field: str) -> str:
    try:
        return digest_value(value, field)
    except Exception as exc:
        raise Protocol28RecoveryError(str(exc)) from exc


def _safe(value: str, field: str) -> str:
    try:
        return safe_id(value, field)
    except Exception as exc:
        raise Protocol28RecoveryError(str(exc)) from exc


def _digests(value: tuple[str, ...], field: str) -> tuple[str, ...]:
    try:
        return sorted_unique_digests(value, field)
    except Exception as exc:
        raise Protocol28RecoveryError(str(exc)) from exc


def _safe_ids(value: tuple[str, ...], field: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise Protocol28RecoveryError(f"{field} must be an array")
    result = tuple(_safe(item, field) for item in value)
    if result != tuple(sorted(set(result))):
        raise Protocol28RecoveryError(f"{field} must be sorted and unique")
    return result


@dataclass(frozen=True, slots=True)
class ParsedResultSeamV1:
    schema_version: int
    dispatch_id: str
    result_kind: Literal["candidate", "verification"]
    result_object_id: str
    output_artifact_key_id: str

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol28RecoveryError("parsed result seam schema must be 1")
        _safe(self.dispatch_id, "ParsedResultSeamV1.dispatch_id")
        if self.result_kind not in {"candidate", "verification"}:
            raise Protocol28RecoveryError("parsed result seam kind is invalid")
        _digest(self.result_object_id, "ParsedResultSeamV1.result_object_id")
        _digest(
            self.output_artifact_key_id,
            "ParsedResultSeamV1.output_artifact_key_id",
        )


@dataclass(frozen=True, slots=True)
class DurableRootV1:
    schema_version: int
    root_id: str
    root_kind: Literal["target", "source", "run"]
    required_accepted_slice_ids: tuple[str, ...]
    required_root_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol28RecoveryError("durable root schema must be 1")
        _digest(self.root_id, "DurableRootV1.root_id")
        if self.root_kind not in {"target", "source", "run"}:
            raise Protocol28RecoveryError("durable root kind is invalid")
        object.__setattr__(
            self,
            "required_accepted_slice_ids",
            _digests(
                self.required_accepted_slice_ids,
                "DurableRootV1.required_accepted_slice_ids",
            ),
        )
        object.__setattr__(
            self,
            "required_root_ids",
            _digests(self.required_root_ids, "DurableRootV1.required_root_ids"),
        )


@dataclass(frozen=True, slots=True)
class Protocol28RecoveryFactsV1:
    """Authenticated external facts not represented by the content-free events."""

    schema_version: int
    snapshot_authority_state: Literal["intact", "missing", "mismatched"]
    live_owner_dispatch_ids: tuple[str, ...]
    durable_capture_dispatch_ids: tuple[str, ...]
    parsed_results: tuple[ParsedResultSeamV1, ...]
    durable_object_ids: tuple[str, ...]
    candidate_output_ids: tuple[str, ...]
    verification_pass_output_ids: tuple[str, ...]
    certified_output_ids: tuple[str, ...]
    accepted_output_ids: tuple[str, ...]
    accepted_slice_output_ids: tuple[str, ...]
    checkpoint_exported_output_ids: tuple[str, ...]
    durable_roots: tuple[DurableRootV1, ...]
    materialized_root_ids: tuple[str, ...]
    closure_required: bool
    closure_integrity_valid: bool
    projection_present: bool

    _DIGEST_FIELDS: ClassVar[tuple[str, ...]] = (
        "durable_object_ids",
        "candidate_output_ids",
        "verification_pass_output_ids",
        "certified_output_ids",
        "accepted_output_ids",
        "accepted_slice_output_ids",
        "checkpoint_exported_output_ids",
        "materialized_root_ids",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol28RecoveryError("recovery facts schema must be 1")
        if self.snapshot_authority_state not in {"intact", "missing", "mismatched"}:
            raise Protocol28RecoveryError("snapshot authority state is invalid")
        for field in (
            "closure_required",
            "closure_integrity_valid",
            "projection_present",
        ):
            if not isinstance(getattr(self, field), bool):
                raise Protocol28RecoveryError(f"{field} must be boolean")
        for field in ("live_owner_dispatch_ids", "durable_capture_dispatch_ids"):
            object.__setattr__(self, field, _safe_ids(getattr(self, field), field))
        parsed = tuple(self.parsed_results)
        if any(not isinstance(item, ParsedResultSeamV1) for item in parsed):
            raise Protocol28RecoveryError("parsed results are invalid")
        dispatch_ids = tuple(item.dispatch_id for item in parsed)
        if dispatch_ids != tuple(sorted(set(dispatch_ids))):
            raise Protocol28RecoveryError(
                "parsed results must be sorted by unique dispatch"
            )
        object.__setattr__(self, "parsed_results", parsed)
        for field in self._DIGEST_FIELDS:
            object.__setattr__(self, field, _digests(getattr(self, field), field))
        roots = tuple(self.durable_roots)
        if any(not isinstance(item, DurableRootV1) for item in roots):
            raise Protocol28RecoveryError("durable roots are invalid")
        keys = tuple((item.root_kind, item.root_id) for item in roots)
        if keys != tuple(sorted(set(keys))):
            raise Protocol28RecoveryError("durable roots must be sorted and unique")
        object.__setattr__(self, "durable_roots", roots)
        if not set(self.accepted_slice_output_ids) <= set(self.accepted_output_ids):
            raise Protocol28RecoveryError(
                "accepted slices require acceptance authority"
            )
        if not set(self.accepted_output_ids) <= set(self.certified_output_ids):
            raise Protocol28RecoveryError("acceptances require certification authority")
        if not set(self.certified_output_ids) <= set(self.verification_pass_output_ids):
            # A controller may have certified authority while event catch-up is absent,
            # but the authenticated fact summary must still include its verifier PASS.
            raise Protocol28RecoveryError(
                "certification requires verifier PASS authority"
            )
        if not set(self.checkpoint_exported_output_ids) <= set(
            self.accepted_slice_output_ids
        ):
            raise Protocol28RecoveryError(
                "checkpoint export requires an accepted slice"
            )


RecoveryActionKindV1 = Literal[
    "lease_dispatch",
    "start_provider",
    "wait_for_live_owner",
    "abandon_dispatch",
    "parse_durable_capture",
    "persist_parsed_result",
    "append_candidate_receipt",
    "append_verification_receipt",
    "append_certification",
    "append_acceptance",
    "append_accepted_slice",
    "export_checkpoint",
    "record_root_event",
    "materialize_root",
    "link_closure_successor",
    "build_closure_root",
    "block_snapshot_integrity",
    "block_closure_integrity",
    "rebuild_projection",
    "complete_run",
    "none",
]


@dataclass(frozen=True, slots=True)
class Protocol28RecoveryActionV1:
    kind: RecoveryActionKindV1
    dispatch_id: str | None = None
    output_artifact_key_id: str | None = None
    authority_id: str | None = None
    reason_code: str | None = None
    requires_provider_call: bool = False


def _action(
    kind: RecoveryActionKindV1,
    *,
    dispatch_id: str | None = None,
    output_id: str | None = None,
    authority_id: str | None = None,
    reason_code: str | None = None,
    provider: bool = False,
) -> Protocol28RecoveryActionV1:
    return Protocol28RecoveryActionV1(
        kind,
        dispatch_id,
        output_id,
        authority_id,
        reason_code,
        provider,
    )


def plan_protocol_28_recovery(
    state: Protocol28ReplayState,
    facts: Protocol28RecoveryFactsV1,
) -> Protocol28RecoveryActionV1:
    """Return the single next safe action after authenticating durable authority."""
    if not isinstance(state, Protocol28ReplayState) or not isinstance(
        facts, Protocol28RecoveryFactsV1
    ):
        raise Protocol28RecoveryError("recovery requires typed state and facts")
    if state.activated and facts.snapshot_authority_state != "intact":
        return _action(
            "block_snapshot_integrity",
            reason_code=f"snapshot_authority_{facts.snapshot_authority_state}",
        )

    if not set(state.accepted_slices) <= set(facts.accepted_slice_output_ids):
        raise Protocol28RecoveryError(
            "accepted-slice event has no matching durable accepted authority"
        )
    if not set(state.certifications) <= set(facts.certified_output_ids):
        raise Protocol28RecoveryError(
            "certification event has no matching durable certification"
        )
    if not set(state.acceptances) <= set(facts.accepted_output_ids):
        raise Protocol28RecoveryError(
            "acceptance event has no matching durable acceptance"
        )
    durable_captures = set(facts.durable_capture_dispatch_ids)
    candidates = set(facts.candidate_output_ids)
    verifications = set(facts.verification_pass_output_ids)
    for dispatch_id, dispatch in state.dispatches.items():
        if (
            dispatch.stage
            in {
                "captured",
                "candidate",
                "rejected",
                "verified_pass",
                "verified_repair",
            }
            and dispatch_id not in durable_captures
        ):
            raise Protocol28RecoveryError(
                "capture event has no matching durable execution capture"
            )
        if (
            dispatch.stage == "candidate"
            and dispatch.output_artifact_key_id not in candidates
        ):
            raise Protocol28RecoveryError(
                "candidate event has no matching durable candidate receipt"
            )
        if (
            dispatch.stage == "verified_pass"
            and dispatch.output_artifact_key_id not in verifications
        ):
            raise Protocol28RecoveryError(
                "verification event has no matching durable verifier PASS"
            )
    durable_root_ids = {item.root_id for item in facts.durable_roots}
    recorded_root_ids = (
        state.target_root_ids
        | state.source_root_ids
        | {item for item in (state.run_root_id,) if item is not None}
    )
    if not recorded_root_ids <= durable_root_ids:
        raise Protocol28RecoveryError("root event has no matching durable root object")
    if not state.materialized_root_ids <= set(facts.materialized_root_ids):
        raise Protocol28RecoveryError(
            "materialization event has no matching durable projection"
        )

    parsed_by_dispatch = {item.dispatch_id: item for item in facts.parsed_results}
    live = set(facts.live_owner_dispatch_ids)
    durable_objects = set(facts.durable_object_ids)
    for dispatch_id, dispatch in sorted(state.dispatches.items()):
        if dispatch.stage == "reserved":
            return _action("lease_dispatch", dispatch_id=dispatch_id)
        if dispatch.stage == "leased":
            if dispatch_id in live:
                return _action("start_provider", dispatch_id=dispatch_id, provider=True)
            return _action("abandon_dispatch", dispatch_id=dispatch_id)
        if dispatch.stage not in {"started", "captured"}:
            continue
        capture_is_durable = (
            dispatch.stage == "captured" or dispatch_id in durable_captures
        )
        parsed = parsed_by_dispatch.get(dispatch_id)
        if capture_is_durable and parsed is None:
            return _action("parse_durable_capture", dispatch_id=dispatch_id)
        if parsed is not None:
            if parsed.output_artifact_key_id != dispatch.output_artifact_key_id:
                raise Protocol28RecoveryError(
                    "parsed result is cross-bound to dispatch"
                )
            expected_kind = (
                "candidate" if dispatch.role == "producer" else "verification"
            )
            if parsed.result_kind != expected_kind:
                raise Protocol28RecoveryError("parsed result role is cross-bound")
            if parsed.result_object_id not in durable_objects:
                return _action(
                    "persist_parsed_result",
                    dispatch_id=dispatch_id,
                    output_id=dispatch.output_artifact_key_id,
                    authority_id=parsed.result_object_id,
                )
            recorded = candidates if dispatch.role == "producer" else verifications
            if dispatch.output_artifact_key_id not in recorded:
                return _action(
                    "append_candidate_receipt"
                    if dispatch.role == "producer"
                    else "append_verification_receipt",
                    dispatch_id=dispatch_id,
                    output_id=dispatch.output_artifact_key_id,
                    authority_id=parsed.result_object_id,
                )
        if not capture_is_durable:
            if dispatch_id in live:
                return _action("wait_for_live_owner", dispatch_id=dispatch_id)
            return _action("abandon_dispatch", dispatch_id=dispatch_id)

    outputs = {item[1] for item in state.realized_by_entry.values()}
    for output_id in sorted(outputs):
        if output_id in verifications and output_id not in set(
            facts.certified_output_ids
        ):
            return _action("append_certification", output_id=output_id)
        if output_id in set(facts.certified_output_ids) and output_id not in set(
            facts.accepted_output_ids
        ):
            return _action("append_acceptance", output_id=output_id)
        if output_id in set(facts.accepted_output_ids) and output_id not in set(
            facts.accepted_slice_output_ids
        ):
            return _action("append_accepted_slice", output_id=output_id)
        if output_id in set(facts.accepted_slice_output_ids) and output_id not in set(
            facts.checkpoint_exported_output_ids
        ):
            return _action("export_checkpoint", output_id=output_id)

    recorded_roots = recorded_root_ids
    kind_order = {"target": 0, "source": 1, "run": 2}
    for root in sorted(
        facts.durable_roots, key=lambda item: (kind_order[item.root_kind], item.root_id)
    ):
        if root.root_id not in recorded_roots:
            return _action("record_root_event", authority_id=root.root_id)
    materialization_order = (
        tuple(sorted(state.target_root_ids))
        + tuple(sorted(state.source_root_ids))
        + tuple(item for item in (state.run_root_id,) if item is not None)
    )
    for root_id in materialization_order:
        if (
            root_id not in set(facts.materialized_root_ids)
            and root_id not in state.materialized_root_ids
        ):
            return _action("materialize_root", authority_id=root_id)

    if state.run_root_id is not None:
        if facts.closure_required:
            if not facts.closure_integrity_valid:
                return _action(
                    "block_closure_integrity",
                    authority_id=state.run_root_id,
                    reason_code="closure_authority_mismatch",
                )
            if state.linked_closure_manifest_id is None:
                return _action("link_closure_successor", authority_id=state.run_root_id)
            if state.closure_root_id is None:
                return _action(
                    "build_closure_root",
                    authority_id=state.linked_closure_manifest_id,
                )
        if not state.terminal:
            return _action("complete_run", authority_id=state.run_root_id)

    if not facts.projection_present:
        return _action("rebuild_projection")
    return _action("none")


__all__ = (
    "DurableRootV1",
    "ParsedResultSeamV1",
    "Protocol28RecoveryActionV1",
    "Protocol28RecoveryError",
    "Protocol28RecoveryFactsV1",
    "plan_protocol_28_recovery",
)
