"""Single bounded recovery loop for durable Phase A spec steps."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from harness.spec_step import (
    PreparedSpecStep,
    SpecStepEffectReceipt,
    SpecStepError,
    append_spec_step_receipt,
    load_prepared_spec_step,
    validate_spec_step_marker,
)
from harness.state_transaction_namespace import PENDING_SPEC_STEP_KEY


@dataclass(frozen=True)
class SpecStepRecoveryOutcome:
    recovered: bool
    blocked: bool = False
    step_id: str = ""
    origin: str = ""
    manual: bool = False


class SpecStepEffectApplier(Protocol):
    def apply(
        self,
        prepared: PreparedSpecStep,
        state: Mapping[str, object],
    ) -> SpecStepEffectReceipt: ...


class SpecStepEffectError(Exception):
    """Bounded effect failure suitable for the durable marker."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code or len(code) > 128:
            code = "effect_io"
        self.code = code
        super().__init__(code)


def _manual(prepared: PreparedSpecStep) -> bool:
    route = prepared.intent.route
    return route.get("manual") is True or route.get("manual_phase_run") is True


def _blocked_outcome(marker, prepared: PreparedSpecStep | None = None) -> SpecStepRecoveryOutcome:
    return SpecStepRecoveryOutcome(
        recovered=True,
        blocked=True,
        step_id=marker.step_id,
        origin=marker.origin,
        manual=False if prepared is None else _manual(prepared),
    )


def drain_pending_spec_step(
    state_store,
    squad_dir: Path,
    effect_applier: SpecStepEffectApplier,
) -> SpecStepRecoveryOutcome:
    """Drain the one state-authorized step, reloading after every durable edge."""
    recovered = False
    recovered_step_id = ""
    recovered_origin = ""
    recovered_manual = False

    # Eight external effects plus commit is the maximum valid intent.  The
    # extra iteration permits a one-ahead receipt to be adopted separately.
    for _ in range(10):
        state = state_store.load()
        marker_value = state.get(PENDING_SPEC_STEP_KEY)
        if marker_value is None:
            return SpecStepRecoveryOutcome(
                recovered=recovered,
                step_id=recovered_step_id,
                origin=recovered_origin,
                manual=recovered_manual,
            )
        marker = validate_spec_step_marker(marker_value)
        recovered = True
        recovered_step_id = marker.step_id
        recovered_origin = marker.origin
        try:
            prepared = load_prepared_spec_step(squad_dir, marker)
        except SpecStepError as error:
            state_store.record_spec_step_failure(
                marker,
                effect=marker.cursor,
                code=error.code,
            )
            return _blocked_outcome(marker)
        recovered_manual = _manual(prepared)

        if marker.cursor == "commit":
            state_store.complete_spec_step(prepared)
            continue

        effects = prepared.intent.effects
        cursor_index = effects.index(marker.cursor)
        receipts = prepared.receipts
        if len(receipts) == cursor_index + 1:
            receipt = receipts[-1]
        else:
            try:
                receipt = effect_applier.apply(prepared, state)
                if type(receipt) is not SpecStepEffectReceipt:
                    raise SpecStepEffectError("effect_invalid")
            except SpecStepEffectError as error:
                state_store.record_spec_step_failure(
                    marker,
                    effect=marker.cursor,
                    code=error.code,
                )
                return _blocked_outcome(marker, prepared)
            except SpecStepError as error:
                state_store.record_spec_step_failure(
                    marker,
                    effect=marker.cursor,
                    code=error.code,
                )
                return _blocked_outcome(marker, prepared)
        try:
            advanced = append_spec_step_receipt(prepared, receipt)
        except SpecStepError as error:
            state_store.record_spec_step_failure(
                marker,
                effect=marker.cursor,
                code=error.code,
            )
            return _blocked_outcome(marker, prepared)
        state_store.advance_spec_step(marker, advanced.marker)

    raise SpecStepEffectError("step_limit")
