"""Retain a native COMMANDER claim across constrained Prosaic inspection turns.

Squad still owns eligibility, attempts, decisions, accounting and completion.
The shared receipt owner stores transport evidence, not a second decision log.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import tempfile
import time

from harness.discovery_receipts import DiscoveryReceiptFile
from harness.discovery_turns import _hash, _json, _pairs, _closed, _remaining
from harness.human_input import AppliedHumanInputResolution
from harness.echelon_result_schema import validate_decision_resolution_result
from harness.prosaic_prompt_loader import ProsaicPromptLoader
from harness.squad_provider import _extract_strict_echelon_result


@dataclass(frozen=True)
class CommanderTurn:
    resolution: AppliedHumanInputResolution | None
    token_usage: int | None
    reason: str
    retryable: bool = False
    claim_sha256: str | None = None


def _file(store, decision, attempt):
    operation = "commander-" + _hash(dict(decision_id=decision["id"], attempt=attempt))[:32]
    return DiscoveryReceiptFile(store.squad_dir, "discovery-turns", producer="commander", round_operation_id=operation)


def _validate(data):
    _closed(data, ("schema_version", "binding", "token_budget", "response", "accepted"))
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or type(data["accepted"]) is not bool:
        raise ValueError("invalid_commander_receipt")
    _closed(data["binding"], ("state_sha256", "decision", "policy", "role", "prompt", "provider", "configuration"))
    if data["token_budget"] is not None and (type(data["token_budget"]) is not int or data["token_budget"] < 0):
        raise ValueError("invalid_commander_budget")
    response = data["response"]
    if response is not None:
        _closed(response, ("exit_code", "timed_out", "stdout", "token_usage", "stdout_sha256", "stdout_truncated"))
        if (type(response["exit_code"]) is not int or type(response["timed_out"]) is not bool
                or type(response["stdout"]) is not str or len(response["stdout"].encode("utf-8")) > 65536
                or type(response["stdout_truncated"]) is not bool
                or type(response["stdout_sha256"]) is not str or len(response["stdout_sha256"]) != 64
                or (not response["stdout_truncated"] and response["stdout_sha256"] != hashlib.sha256(response["stdout"].encode("utf-8")).hexdigest())
                or (response["token_usage"] is not None and
                    (type(response["token_usage"]) is not int or response["token_usage"] < 0))):
            raise ValueError("invalid_commander_response")
    if data["accepted"]:
        _resolution(data)


def _read(file):
    raw = file._read()
    file._raw = raw
    if raw is None:
        return None
    value = json.loads(raw, object_pairs_hook=_pairs)
    _closed(value, ("payload", "sha256"))
    if value["sha256"] != _hash(value["payload"]):
        raise ValueError("corrupt_commander_receipt")
    _validate(value["payload"])
    return value["payload"]


def _save(file, data):
    _validate(data)
    file._write(_json(dict(payload=data, sha256=_hash(data))) + "\n")


def _resolution(data):
    response = data["response"]
    if response is None:
        raise ValueError("commander_completion_unknown")
    if response["token_usage"] is None:
        raise ValueError("commander_usage_unknown")
    if response["exit_code"] != 0 or response["timed_out"]:
        raise ValueError("commander_provider_failed")
    if response["stdout_truncated"]:
        raise ValueError("invalid_commander_result")
    budget = data["token_budget"]
    if budget is not None and response["token_usage"] > budget:
        raise ValueError("commander_budget_exhausted")
    from harness.squad import SquadController
    try:
        resolved = validate_decision_resolution_result(_extract_strict_echelon_result(response["stdout"]),
            options=SquadController._human_input_options_from_decision(data["binding"]["decision"]))
    except Exception:
        raise ValueError("invalid_commander_result") from None
    return AppliedHumanInputResolution(resolved.selected_option_id, resolved.answer_text, "COMMANDER",
        rationale=resolved.rationale, confidence=resolved.confidence)


def _role(root, deadline):
    role = ProsaicPromptLoader(root, timeout_s=_remaining(deadline)).load_subagent("echelon.commander")
    if role is None or role.frontmatter.get("name") != "echelon.commander" or not role.body.strip():
        raise ValueError("missing_commander_role")
    metadata = {key: role.frontmatter[key] for key in ("model_tier", "effort")}
    if metadata["model_tier"] not in {"fast", "balanced", "strong"} or metadata["effort"] not in {"low", "medium", "high"}:
        raise ValueError("invalid_commander_metadata")
    return role, metadata


def run_commander_turn(controller, state, policy, *, check_inputs, token_budget=None):
    """Claim once, persist before dispatch, then replay only that exact response."""
    data = None
    try:
        from harness.discovery_checkpoint_resolution import policy_payload
        store, executor, root = controller._state_store, controller._provider, controller._project_root
        decision = state["blocked_decision"]
        create = decision["status"] == "pending"
        if (decision["status"] not in {"pending", "resolving"} or decision["autonomy_mode"] != "banzai"
                or decision.get("automatic_eligible") is not True or decision["schema_version"] != 3):
            raise ValueError("commander_native_claim_required")
        if getattr(executor, "supports_inspection_turn", False) is not True:
            raise ValueError("unsupported_provider_inspection_boundary")
        if token_budget is not None and (type(token_budget) is not int or token_budget < 0 or (create and token_budget == 0)):
            raise ValueError("commander_budget_exhausted")
        deadline = time.time() + 300
        role, metadata = _role(root, deadline)
        prompt = role.body + "\n" + controller._render_commander_decision_prompt(decision, policy, state)
        if len(prompt.encode("utf-8")) > 1024 * 1024:
            raise ValueError("commander_prompt_exceeds_limit")
        check_inputs()
        attempt = decision["attempts"] + (1 if create else 0)
        with _file(store, decision, attempt) as file:
            data = _read(file)
            if (data is None) != create:
                raise ValueError("commander_receipt_selection_conflict")
            if store.load() != state:
                raise ValueError("commander_state_changed")
            if create:
                state = store.claim_human_input_decision(decision["id"], expected_state_revision=state["state_revision"])
                decision = state["blocked_decision"]
            binding = dict(state_sha256=_hash(state), decision=decision, policy=policy_payload(policy),
                role=asdict(role), prompt=prompt, provider=executor.provider_id,
                configuration=executor.constrained_execution_configuration_id)
            if create:
                data = dict(schema_version=1, binding=binding, token_budget=token_budget, response=None, accepted=False)
                _save(file, data)  # Native resolving claim + missing response means uncertain, never redispatch.
            elif data["binding"] != binding:
                raise ValueError("commander_binding_changed")
            if create:
                with tempfile.TemporaryDirectory(prefix="echelon-commander-inspection-") as private:
                    result = executor.run_inspection_turn(private, prompt, frontmatter=metadata,
                        timeout_ms=int(_remaining(deadline) * 1000))
                output = result.stdout.encode("utf-8")
                data["response"] = dict(exit_code=result.exit_code, timed_out=result.timed_out,
                    stdout=output[:65536].decode("utf-8", errors="ignore"), stdout_truncated=len(output) > 65536,
                    stdout_sha256=hashlib.sha256(output).hexdigest(),
                    token_usage=result.token_usage if type(result.token_usage) is int and result.token_usage >= 0 else None)
                _save(file, data)  # Charge/response survives interruption before native validation or application.
            resolution = _resolution(data)
            if token_budget is not None and data["response"]["token_usage"] > token_budget:
                raise ValueError("commander_budget_exhausted")
            check_inputs()
            if (store.load() != state or file._read() != file._raw
                    or _role(root, deadline)[0] != role
                    or role.body + "\n" + controller._render_commander_decision_prompt(decision, policy, state) != prompt):
                raise ValueError("commander_inputs_changed")
            if not data["accepted"]:
                data["accepted"] = True
                _save(file, data)
            return CommanderTurn(resolution, data["response"]["token_usage"], "retained", claim_sha256=binding["state_sha256"])
    except Exception as error:
        usage = data["response"]["token_usage"] if data is not None and data.get("response") is not None else None
        reason = str(error) if isinstance(error, ValueError) else "commander_reconciliation_required"
        claim = data["binding"]["state_sha256"] if data is not None else None
        return CommanderTurn(None, usage, reason, reason in {"invalid_commander_result", "commander_provider_failed"}, claim)


def resolution_receipt(run, before, resolution, policy):
    """Bind completion to the retained judgment; no provider or fresh judgment."""
    from types import SimpleNamespace
    from harness.discovery_checkpoint_resolution import policy_payload
    decision = before["blocked_decision"]
    if resolution["resolved_by"] != "COMMANDER":
        return None
    with _file(SimpleNamespace(squad_dir=run), decision, decision["attempts"]) as file:
        data = _read(file)
    if (data is None or not data["accepted"] or data["binding"]["state_sha256"] != _hash(before)
            or data["binding"]["decision"] != decision or data["binding"]["policy"] != policy_payload(policy)):
        raise ValueError("commander_resolution_receipt_required")
    answer = _resolution(data)
    if (answer.selected_option_id, answer.answer_text, answer.rationale, answer.confidence) != (
            resolution["selected_option_id"], resolution["answer_text"],
            resolution["resolution_rationale"], resolution["resolution_confidence"]):
        raise ValueError("commander_resolution_receipt_changed")
    return dict(sha256=_hash(data), token_usage=data["response"]["token_usage"])
