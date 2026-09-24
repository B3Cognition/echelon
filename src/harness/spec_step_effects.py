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
    apply_or_verify_step_journal,
    apply_or_verify_step_mining,
    apply_or_verify_step_quality,
    apply_or_verify_step_retarget,
    apply_or_verify_step_timing,
    create_or_recover_step_checkpoint,
    install_or_verify_step_context,
)
from harness.squad_publication import PublicationError, load_prepared_publication


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
    ) -> None:
        self._project_root = Path(project_root)
        self._squad_dir = Path(squad_dir)
        self._phase_graph = phase_graph
        self._telemetry_store = telemetry_store
        self._context_drawer_loader = context_drawer_loader

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
        }
        try:
            if effect == "publication":
                result = self._publication(prepared)
            elif effect == "journal":
                result = apply_or_verify_step_journal(**common)
            elif effect == "timing":
                result = apply_or_verify_step_timing(**common)
            elif effect == "quality":
                result = apply_or_verify_step_quality(**common)
            elif effect == "checkpoint":
                result = create_or_recover_step_checkpoint(**common)
            elif effect == "context":
                result = install_or_verify_step_context(**common)
            elif effect == "mining":
                result = apply_or_verify_step_mining(**common)
            elif effect == "retarget":
                result = apply_or_verify_step_retarget(**common)
            else:
                raise SpecStepEffectError("effect_invalid")
            return self._receipt(prepared, effect, result)
        except SpecStepEffectError:
            raise
        except (CompletionError, PublicationError) as exc:
            raise SpecStepEffectError(exc.code) from exc
        except (Exception, SystemExit) as exc:
            raise SpecStepEffectError("effect_io") from exc
