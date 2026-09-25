"""Explicit adapters from one sealed Phase A step to existing effects."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path

from harness.spec_step import PreparedSpecStep, SpecStepEffectReceipt
from harness.spec_step_kernel import SpecStepEffectError
from harness.squad_completion import (
    CompletionError,
    CompletionIntent,
    _intent_view,
    _validate_intent,
    apply_or_verify_completion_journal,
    apply_or_verify_completion_timing,
    apply_or_verify_step_mining,
    apply_or_verify_step_quality,
    apply_or_verify_step_retarget,
    create_or_recover_completion_checkpoint,
    install_or_verify_step_context,
    prepare_completion_journal_plan,
)
from harness.squad_publication import PublicationError, load_prepared_publication
from harness.proportional_quality_effects import (
    apply_or_verify_proportional_quality_effect,
)


def _canonical_payload(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise SpecStepEffectError("effect_invalid") from exc


def _payload(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    raise SpecStepEffectError("effect_invalid")


def step_effect_intent(prepared: PreparedSpecStep) -> CompletionIntent:
    """Load the effect inputs sealed inside one authoritative spec step."""
    if type(prepared) is not PreparedSpecStep:
        raise SpecStepEffectError("effect_invalid")
    raw = prepared.intent.provenance.get("effect_intent")
    try:
        validated = _validate_intent(raw)
    except CompletionError as exc:
        raise SpecStepEffectError(exc.code) from exc
    effects = tuple(
        effect for effect in prepared.intent.effects if effect != "publication"
    )
    publication = validated["publication"]
    marker = (
        publication.get("marker")
        if isinstance(publication, dict)
        and publication.get("kind") == "external"
        else None
    )
    step_route = prepared.intent.route
    effect_route = validated["route"]
    if (
        validated["completion_id"] != prepared.marker.step_id
        or validated["origin"] != prepared.intent.origin
        or tuple(validated["effect_plan"]) != effects
        or marker != prepared.intent.publication
        or not isinstance(effect_route, dict)
        or any(step_route.get(key) != value for key, value in effect_route.items())
    ):
        raise SpecStepEffectError("intent_mismatch")
    return _intent_view(validated)


def _existing_receipt(
    prepared: PreparedSpecStep,
    effect: str,
) -> dict[str, object] | None:
    for receipt in prepared.receipts:
        if receipt.effect == effect:
            payload = receipt.payload
            wrapped = payload.get("completion_receipt")
            return dict(wrapped) if isinstance(wrapped, Mapping) else payload
    return None


def apply_or_verify_step_journal(
    *,
    prepared: PreparedSpecStep,
    squad_dir: Path,
    **_kwargs: object,
) -> dict[str, object]:
    intent = step_effect_intent(prepared)
    receipt = apply_or_verify_completion_journal(
        prepare_completion_journal_plan(
            intent,
            squad_dir / "reasoning-journal.jsonl",
        )
    )
    existing = _existing_receipt(prepared, "journal")
    if existing is not None and existing != receipt:
        raise SpecStepEffectError("receipts_mismatch")
    return receipt


def _timing_parameters(
    phase_graph: object,
    from_phase: str,
    to_phase: str,
) -> dict[str, object]:
    if from_phase == to_phase:
        raise SpecStepEffectError("intent_mismatch")
    try:
        node = phase_graph.get(from_phase)  # type: ignore[attr-defined]
        transition = node.timing_window_transition
    except (AttributeError, KeyError):
        raise SpecStepEffectError("intent_mismatch")
    if not isinstance(transition, dict):
        raise SpecStepEffectError("intent_mismatch")

    def declared_budget(phase: str) -> float | None:
        try:
            phase_ids = phase_graph.all_phase_ids()  # type: ignore[attr-defined]
            for phase_id in phase_ids:
                candidate = phase_graph.get(phase_id)  # type: ignore[attr-defined]
                if (
                    candidate.timing_window_start == phase
                    and candidate.budget_seconds is not None
                ):
                    return float(candidate.budget_seconds)
                candidate_transition = candidate.timing_window_transition
                if (
                    isinstance(candidate_transition, dict)
                    and str(candidate_transition.get("open") or "").strip()
                    == phase
                    and candidate_transition.get("open_budget_seconds") is not None
                ):
                    return float(candidate_transition["open_budget_seconds"])
        except (AttributeError, KeyError, TypeError, ValueError):
            return None
        return None

    close_phase = str(transition.get("close") or "").strip()
    open_phase = str(transition.get("open") or "").strip()
    close_budget = declared_budget(close_phase) if close_phase else None
    raw_open_budget = transition.get("open_budget_seconds")
    open_budget = (
        float(raw_open_budget)
        if open_phase
        and type(raw_open_budget) in (int, float)
        and float(raw_open_budget) >= 0
        else declared_budget(open_phase) if open_phase else None
    )
    if (
        (not close_phase and not open_phase)
        or (close_phase and close_budget is None)
        or (open_phase and open_budget is None)
    ):
        raise SpecStepEffectError("intent_mismatch")
    return {
        "close_phase": close_phase or None,
        "close_budget_seconds": close_budget,
        "open_phase": open_phase or None,
        "open_budget_seconds": open_budget,
    }


def apply_or_verify_step_timing(
    *,
    prepared: PreparedSpecStep,
    phase_graph: object,
    telemetry_store: object,
    **_kwargs: object,
) -> dict[str, object]:
    intent = step_effect_intent(prepared)
    route = intent.route
    return apply_or_verify_completion_timing(
        intent,
        telemetry_store,
        expected_receipt=_existing_receipt(prepared, "timing"),
        **_timing_parameters(
            phase_graph,
            str(route["from_phase"]),
            str(route["to_phase"]),
        ),
    )


def create_or_recover_step_checkpoint(
    *,
    prepared: PreparedSpecStep,
    state: Mapping[str, object],
    checkpoint_input_loader: Callable[..., Mapping[str, object]] | None,
    **_kwargs: object,
) -> dict[str, object]:
    if checkpoint_input_loader is None:
        raise SpecStepEffectError("effect_invalid")
    intent = step_effect_intent(prepared)
    try:
        inputs = dict(
            checkpoint_input_loader(prepared, prepared.intent.final_state)
        )
        return create_or_recover_completion_checkpoint(
            intent,
            expected_receipt=_existing_receipt(prepared, "checkpoint"),
            **inputs,
        )
    except SpecStepEffectError:
        raise
    except CompletionError as exc:
        raise SpecStepEffectError(exc.code) from exc
    except Exception as exc:
        raise SpecStepEffectError("effect_io") from exc


def apply_or_verify_step_quality(
    *,
    prepared: PreparedSpecStep,
    state: Mapping[str, object],
    project_root: Path,
    **_kwargs: object,
) -> dict[str, object]:
    intent = step_effect_intent(prepared)
    return apply_or_verify_proportional_quality_effect(
        intent.quality_effect,
        completion_id=intent.completion_id,
        project_root=project_root,
        state=prepared.intent.final_state,
        route=intent.route,
        preceding_checkpoint_receipt=_existing_receipt(
            prepared,
            "checkpoint",
        ),
        expected_receipt=_existing_receipt(prepared, "quality"),
    )


def _managed_effect(prepared: PreparedSpecStep) -> bool:
    intent = prepared.intent.provenance.get("effect_intent")
    if not isinstance(intent, Mapping):
        return False
    publication = intent.get("publication")
    return isinstance(publication, Mapping) and "managed_discovery" in publication


def _requires_companion_tail(
    prepared: PreparedSpecStep,
    effect: str,
) -> bool:
    effects = prepared.intent.effects
    index = effects.index(effect) if effect in effects else -1
    tail = effects[index + 1 :]
    return any(item in {"context", "mining", "retarget"} for item in tail)


class PhaseASpecStepEffects:
    """Closed Phase A effect switch; this is deliberately not a registry."""

    def __init__(
        self,
        *,
        project_root: Path,
        squad_dir: Path,
        phase_graph: object,
        telemetry_store: object,
        context_drawer_loader: Callable[..., object],
        checkpoint_input_loader: Callable[..., Mapping[str, object]] | None = None,
        completion_receipt_bridge: Callable[..., object] | None = None,
        completion_effect_applier: Callable[..., object] | None = None,
        publication_effect_applier: Callable[..., object] | None = None,
    ) -> None:
        self._project_root = Path(project_root)
        self._squad_dir = Path(squad_dir)
        self._phase_graph = phase_graph
        self._telemetry_store = telemetry_store
        self._context_drawer_loader = context_drawer_loader
        self._checkpoint_input_loader = checkpoint_input_loader
        self._completion_receipt_bridge = completion_receipt_bridge
        self._completion_effect_applier = completion_effect_applier
        self._publication_effect_applier = publication_effect_applier

    def _receipt(
        self,
        prepared: PreparedSpecStep,
        effect: str,
        value: object,
    ) -> SpecStepEffectReceipt:
        payload = _payload(value)
        digest = hashlib.sha256(_canonical_payload(payload)).hexdigest()
        return SpecStepEffectReceipt(
            prepared.marker.step_id,
            effect,  # type: ignore[arg-type]
            digest,
            payload,
        )

    def _publication(self, prepared: PreparedSpecStep) -> dict[str, object]:
        marker = prepared.intent.publication
        if marker is None or marker.get("transaction_id") != prepared.marker.step_id:
            raise SpecStepEffectError("intent_mismatch")
        staged = load_prepared_publication(
            self._project_root,
            self._squad_dir,
            marker,
        )
        staged.publish()
        operations = []
        for raw in staged._manifest["operations"]:
            operation = dict(raw)
            operations.append(
                {
                    "action": operation["action"],
                    "target": operation["target"],
                    "postimage": dict(operation["postimage"]),
                }
            )
        return {
            "schema_version": 1,
            "marker": staged.marker.to_dict(),
            "operations": operations,
        }

    def apply(
        self,
        prepared: PreparedSpecStep,
        state: Mapping[str, object],
    ) -> SpecStepEffectReceipt:
        if type(prepared) is not PreparedSpecStep or not isinstance(state, Mapping):
            raise SpecStepEffectError("effect_invalid")
        effect = prepared.marker.cursor
        common = {
            "prepared": prepared,
            "state": state,
            "project_root": self._project_root,
            "squad_dir": self._squad_dir,
            "phase_graph": self._phase_graph,
            "telemetry_store": self._telemetry_store,
            "context_drawer_loader": self._context_drawer_loader,
            "checkpoint_input_loader": self._checkpoint_input_loader,
        }
        try:
            if effect == "publication":
                result = (
                    self._publication_effect_applier(prepared, state)
                    if self._publication_effect_applier is not None
                    else self._publication(prepared)
                )
                if self._completion_effect_applier is not None and (
                    _managed_effect(prepared)
                    or _requires_companion_tail(prepared, effect)
                ):
                    result = self._completion_effect_applier(
                        prepared,
                        state,
                        publication_receipt=result,
                    )
            elif effect == "journal":
                result = apply_or_verify_step_journal(**common)
            elif effect == "timing":
                result = apply_or_verify_step_timing(**common)
            elif effect == "checkpoint":
                result = create_or_recover_step_checkpoint(**common)
            elif effect == "quality" and not _managed_effect(prepared):
                result = apply_or_verify_step_quality(**common)
            elif self._completion_effect_applier is not None:
                result = self._completion_effect_applier(prepared, state)
            elif effect == "context":
                result = install_or_verify_step_context(**common)
            elif effect == "mining":
                result = apply_or_verify_step_mining(**common)
            elif effect == "retarget":
                result = apply_or_verify_step_retarget(**common)
            else:
                raise SpecStepEffectError("effect_invalid")
            if (
                self._completion_receipt_bridge is not None
                and effect in {"journal", "timing", "checkpoint", "quality"}
                and not (effect == "quality" and _managed_effect(prepared))
                and (
                    prepared.intent.origin == "resolution"
                    or _requires_companion_tail(prepared, effect)
                )
            ):
                result = self._completion_receipt_bridge(
                    prepared,
                    effect,
                    result,
                )
            return self._receipt(prepared, effect, result)
        except SpecStepEffectError:
            raise
        except (CompletionError, PublicationError) as exc:
            raise SpecStepEffectError(exc.code) from exc
        except (Exception, SystemExit) as exc:
            raise SpecStepEffectError("effect_io") from exc
