"""Inactive, receipt-backed discovery steps over the existing inspection boundary.

The caller owns execution leases, complete input capture and semantic ordering.
These replies are not candidate acceptance or publication authority.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
import time

from harness.discovery_bootstrap_state import bootstrap_from_state
from harness.discovery_receipts import DiscoveryReceiptFile
from harness.discovery_semantics import DiscoveryAssignment, parse_discovery_reply, validate_discovery_reply
from harness.discovery_turn_state import DISCOVERY_TURNS_KEY
from harness.element_identity_store import IdentityStore
from harness.inspection_io import BoundedReadChannel
from harness.product_inventory import CONTROL_PATHS, CONTROL_ROOTS
from harness.prosaic_prompt_loader import ProsaicPromptLoader


@dataclass(frozen=True)
class DiscoveryStepResult:
    reply: dict | None
    reason: str
    token_usage: int | None
    dispatch_count: int


class _Blocked(ValueError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def _closed(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise _Blocked("invalid_provider_receipt_schema")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _Blocked("duplicate_provider_receipt_field")
        result[key] = value
    return result


def _limits(token_budget, dispatch_limit):
    if (token_budget is not None and (type(token_budget) not in {int, float}
            or not math.isfinite(token_budget) or token_budget < 0)):
        raise _Blocked("invalid_token_budget")
    if type(dispatch_limit) is not int or not 0 <= dispatch_limit <= 297:
        raise _Blocked("invalid_dispatch_limit")


def _assignment(value):
    _closed(value, ("schema_version", "operation_id", "dispatch_id", "spec_id", "run_id", "step",
                    "input_fingerprint", "artifact_paths", "editable_revisions", "assigned_ids"))
    if any(type(value[key]) is not list for key in ("artifact_paths", "editable_revisions", "assigned_ids")):
        raise _Blocked("invalid_provider_assignment")
    selected = DiscoveryAssignment(**{key: (tuple(tuple(pair) for pair in item) if key == "editable_revisions"
        else tuple(item) if key in {"artifact_paths", "assigned_ids"} else item)
        for key, item in value.items() if key != "schema_version"})
    if type(value["schema_version"]) is not int or selected.identity() != value:
        raise _Blocked("invalid_provider_assignment")
    return selected


def _sha(value):
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise _Blocked("invalid_provider_receipt_digest")


def _validate(data):
    _closed(data, ("schema_version", "binding", "token_budget", "dispatch_limit", "steps"))
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or type(data["binding"]) is not dict:
        raise _Blocked("invalid_provider_receipt_version")
    _limits(data["token_budget"], data["dispatch_limit"])
    if type(data["steps"]) is not list or len(data["steps"]) > 9:
        raise _Blocked("invalid_provider_step_count")
    dispatches = set()
    for step in data["steps"]:
        _closed(step, ("assignment", "input_sha256", "deadline", "records"))
        selected = _assignment(step["assignment"])
        _sha(step["input_sha256"])
        if selected.dispatch_id in dispatches:
            raise _Blocked("duplicate_provider_step")
        dispatches.add(selected.dispatch_id)
        if type(step["deadline"]) not in {int, float} or not math.isfinite(step["deadline"]) or step["deadline"] <= 0:
            raise _Blocked("invalid_provider_deadline")
        if type(step["records"]) is not list or len(step["records"]) > 33:
            raise _Blocked("invalid_provider_turn_count")
        terminal = False
        for record in step["records"]:
            _closed(record, ("prompt_sha256", "reply", "read", "token_usage", "error", "accepted"))
            _sha(record["prompt_sha256"])
            if terminal:
                raise _Blocked("provider_turn_after_terminal_result")
            usage = record["token_usage"]
            if usage is not None and (type(usage) is not int or usage < 0):
                raise _Blocked("invalid_provider_usage")
            if record["error"] is not None and (type(record["error"]) is not str or not record["error"]):
                raise _Blocked("invalid_provider_error")
            reply = record["reply"]
            if type(record["accepted"]) is not bool or (record["accepted"] and (
                    type(reply) is not dict or reply.get("action") != "final" or record["error"] is not None)):
                raise _Blocked("invalid_provider_acceptance_receipt")
            if reply is not None:
                reply = validate_discovery_reply(reply, selected)
                if reply["action"] == "read":
                    if record["read"] is not None:
                        _closed(record["read"], ("request", "response"))
                        if record["read"]["request"] != reply["request"] or type(record["read"]["response"]) is not dict:
                            raise _Blocked("invalid_provider_read_receipt")
                elif record["read"] is not None:
                    raise _Blocked("unexpected_provider_read_receipt")
            elif record["read"] is not None:
                raise _Blocked("read_receipt_without_provider_reply")
            terminal = reply is None or reply["action"] != "read" or record["error"] is not None or record["read"] is None


def _usage(data):
    records = [record for step in data["steps"] for record in step["records"]]
    return dict(tokens=sum(record["token_usage"] or 0 for record in records),
                known=all(record["token_usage"] is not None for record in records), dispatches=len(records))


def _budget(data, *, dispatch=False):
    usage = _usage(data)
    limit = data["token_budget"]
    if limit is not None:
        if not usage["known"]:
            raise _Blocked("provider_usage_unknown")
        if usage["tokens"] > limit or (dispatch and usage["tokens"] >= limit):
            raise _Blocked("provider_token_budget_exhausted")
    if dispatch and usage["dispatches"] >= data["dispatch_limit"]:
        raise _Blocked("provider_dispatch_budget_exhausted")


def _save(file, data):
    _validate(data)
    file._write(_json({"payload": data, "sha256": _hash(data)}) + "\n")


def _prompt(role, assignment, context, reads):
    return role.body + "\nHOST_INPUT_JSON\n" + _json({"assignment": assignment.identity(), "context": context, "reads": reads})


def run_discovery_step(project_root, state_store, executor, assignment, context, *, roots, check_inputs,
                       forbidden_paths=(), token_budget=None, dispatch_limit=297, create=False) -> DiscoveryStepResult:
    """Replay or execute one bound semantic step; return cumulative operation usage."""
    usage = dict(tokens=0, known=False, dispatches=0)
    data = None
    preparation_deadline = time.time() + 300
    try:
        with DiscoveryReceiptFile(state_store.squad_dir, "discovery-turns") as file:
            raw = file._read()
            file._raw = raw
            if raw is not None:
                envelope = json.loads(raw, object_pairs_hook=_pairs)
                _closed(envelope, ("payload", "sha256"))
                if envelope["sha256"] != _hash(envelope["payload"]):
                    raise _Blocked("corrupt_provider_receipt")
                _validate(envelope["payload"])
                data = envelope["payload"]
                usage = _usage(data)
                retained = [step for step in data["steps"] if step["assignment"]["dispatch_id"] == assignment.dispatch_id]
                if retained and not (retained[0]["records"] and retained[0]["records"][-1]["accepted"]):
                    preparation_deadline = min(preparation_deadline, retained[0]["deadline"])
            state = state_store.load()
            marker = state.get(DISCOVERY_TURNS_KEY)
            if marker is None and raw is None:
                usage["known"] = True
            if type(create) is not bool or (create and (marker is not None or raw is not None)) or (
                    not create and (marker is None or raw is None)):
                raise _Blocked("provider_journal_selection_conflict")
            _limits(token_budget, dispatch_limit)
            if getattr(executor, "supports_inspection_turn", False) is not True:
                raise _Blocked("unsupported_provider_inspection_boundary")
            selected = bootstrap_from_state(state)
            if selected is None or "managed_identity" not in state:
                raise _Blocked("completed_discovery_bootstrap_required")
            identity = assignment.identity()
            if (assignment.spec_id, assignment.run_id, assignment.operation_id, str(project_root), str(state_store.squad_dir)) != (
                    selected["selection"]["spec_id"], selected["selection"]["run_id"], selected["selection"]["operation_id"],
                    selected["selection"]["project_root"], selected["selection"]["run_dir"]):
                raise _Blocked("discovery_provider_selection_changed")
            store = IdentityStore.open(Path(project_root))
            observed = store.check_managed_context(spec_id=assignment.spec_id, run_id=assignment.run_id, record=state["managed_identity"])
            roles = {}
            for name in ("producer", "reviewer"):
                loader = ProsaicPromptLoader(Path(project_root), timeout_s=_remaining(preparation_deadline))
                role = loader.load_subagent("echelon.discovery-" + name)
                if role is None or role.frontmatter.get("name") != "echelon.discovery-" + name or not role.body.strip():
                    raise _Blocked("missing_discovery_role")
                roles[name] = role
            _remaining(preparation_deadline)
            denied = tuple(forbidden_paths) + tuple(Path(project_root) / name for name in CONTROL_ROOTS | CONTROL_PATHS) + tuple(
                state_store.squad_dir / name for name in ("state.json", "state.json.bak", "state.lock",
                    "discovery-turns.json", "discovery-turns.lock", "discovery-reservations.json", "discovery-reservations.lock"))
            binding = dict(contract="discovery-inspection-v1", bootstrap=selected, authority=observed,
                roles={name: asdict(role) for name, role in roles.items()},
                provider=getattr(executor, "provider_id", executor.cli),
                configuration=getattr(executor, "constrained_execution_configuration_id", None),
                roots={key: str(Path(value).absolute()) for key, value in roots.items()},
                forbidden=sorted(str(Path(path).absolute()) for path in denied))
            expected_marker = dict(schema_version=1, operation_id=assignment.operation_id, binding_sha256=_hash(binding))
            with BoundedReadChannel(roots, forbidden_paths=denied) as channel:
                if create:
                    state = state_store.prepare_discovery_turns(expected_marker)
                    data = dict(schema_version=1, binding=binding, token_budget=token_budget, dispatch_limit=dispatch_limit, steps=[])
                    _save(file, data)
                else:
                    if marker != expected_marker or data["binding"] != binding:
                        raise _Blocked("provider_operation_binding_changed")
                    state_store.confirm_durable_state(state)
                    limits = [limit for limit in (data["token_budget"], token_budget) if limit is not None]
                    data["token_budget"] = min(limits) if limits else None
                    data["dispatch_limit"] = min(data["dispatch_limit"], dispatch_limit)
                    _save(file, data)
                def verify(reads):
                    if check_inputs() != assignment.input_fingerprint:
                        raise _Blocked("discovery_provider_inputs_changed")
                    current = store.check_managed_context(spec_id=assignment.spec_id, run_id=assignment.run_id, record=state["managed_identity"])
                    if current != observed or file._read() != file._raw:
                        raise _Blocked("discovery_provider_authority_changed")
                    for read in reads:
                        if channel.request(read["request"]) != read["response"]:
                            raise _Blocked("discovery_provider_read_changed")
                # Any unknown or failed turn freezes the whole selected operation.
                all_reads = []
                for prior in data["steps"]:
                    for record in prior["records"]:
                        if record["error"]:
                            raise _Blocked(record["error"])
                        if record["reply"] is None:
                            raise _Blocked("provider_completion_unknown")
                        if record["reply"]["action"] == "final" and not record["accepted"]:
                            raise _Blocked("provider_acceptance_receipt_missing")
                        if record["reply"]["action"] == "read":
                            if record["read"] is None:
                                raise _Blocked("provider_read_receipt_missing")
                            all_reads.append(record["read"])
                verify(all_reads)
                role = roles["reviewer" if assignment.step == "review" else "producer"]
                step_digest = _hash(dict(assignment=identity, context=context, role=asdict(role)))
                matched = [item for item in data["steps"] if item["assignment"]["dispatch_id"] == assignment.dispatch_id]
                if matched:
                    step, = matched
                    if step["assignment"] != identity or step["input_sha256"] != step_digest:
                        raise _Blocked("provider_step_binding_changed")
                else:
                    if len(data["steps"]) >= 9:
                        raise _Blocked("provider_step_limit_exhausted")
                    if any(not item["records"] or item["records"][-1]["reply"]["action"] != "final" for item in data["steps"]):
                        raise _Blocked("previous_provider_step_incomplete")
                    step = dict(assignment=identity, input_sha256=step_digest, deadline=preparation_deadline, records=[])
                    data["steps"].append(step)
                    _save(file, data)
                reads = []
                for record in step["records"]:
                    if record["prompt_sha256"] != _hash(_prompt(role, assignment, context, reads)):
                        raise _Blocked("provider_prompt_receipt_changed")
                    if record["reply"]["action"] == "final":
                        _budget(data)
                        _remaining(preparation_deadline)
                        return DiscoveryStepResult(deepcopy(record["reply"]), "replayed", **_result_usage(data))
                    reads.append(record["read"])
                while True:
                    _budget(data, dispatch=True)
                    if time.time() >= step["deadline"]:
                        raise _Blocked("provider_deadline_exhausted")
                    if len(step["records"]) >= 33:
                        raise _Blocked("provider_read_limit_exhausted")
                    verify(all_reads)
                    prompt = _prompt(role, assignment, context, reads)
                    if len(prompt.encode("utf-8")) > 1024 * 1024:
                        raise _Blocked("provider_input_exceeds_limit")
                    _remaining(step["deadline"])
                    record = dict(prompt_sha256=_hash(prompt), reply=None, read=None, token_usage=None, error=None, accepted=False)
                    step["records"].append(record)
                    _save(file, data)
                    with tempfile.TemporaryDirectory(prefix="echelon-discovery-inspection-") as private:
                        timeout_ms = int(_remaining(step["deadline"]) * 1000)
                        result = executor.run_inspection_turn(private, prompt,
                            frontmatter={key: role.frontmatter[key] for key in ("model_tier", "effort")},
                            timeout_ms=timeout_ms)
                    record["token_usage"] = result.token_usage if type(result.token_usage) is int and result.token_usage >= 0 else None
                    try:
                        if type(result.exit_code) is not int or result.exit_code != 0:
                            raise _Blocked("provider_failed")
                        try:
                            record["reply"] = parse_discovery_reply(result.stdout, assignment)
                        except ValueError:
                            raise _Blocked("invalid_provider_reply") from None
                        if record["reply"]["action"] == "blocked":
                            raise _Blocked("provider_blocked")
                        _save(file, data)  # Reply and usage precede host read or acceptance.
                        _budget(data)
                        if time.time() >= step["deadline"]:
                            raise _Blocked("provider_deadline_exhausted")
                        verify(all_reads)
                        _remaining(step["deadline"])
                        if record["reply"]["action"] == "read":
                            if len(reads) >= 32:
                                raise _Blocked("provider_read_limit_exhausted")
                            request = record["reply"]["request"]
                            record["read"] = dict(request=request, response=channel.request(request))
                            reads.append(record["read"])
                            all_reads.append(record["read"])
                        else:
                            record["accepted"] = True
                    except Exception as error:
                        record["error"] = str(error) if isinstance(error, _Blocked) else "provider_read_or_receipt_failed"
                        _save(file, data)
                        raise _Blocked(record["error"]) from None
                    _save(file, data)
                    if record["reply"]["action"] == "final":
                        return DiscoveryStepResult(deepcopy(record["reply"]), "replayed", **_result_usage(data))
    except Exception as error:
        if data is not None:
            usage = _usage(data)
        reason = str(error) if isinstance(error, _Blocked) else "discovery_provider_reconciliation_required"
        return DiscoveryStepResult(None, reason, usage["tokens"] if usage["known"] else None, usage["dispatches"])


def _result_usage(data):
    usage = _usage(data)
    return dict(token_usage=usage["tokens"] if usage["known"] else None, dispatch_count=usage["dispatches"])


def read_discovery_usage(state_store):
    """Observe retained cumulative charges even when current inputs cannot resume.

    This validates receipt/selection integrity, not current source freshness or
    permission to dispatch. Missing or damaged selected material remains unknown.
    """
    try:
        state = state_store.load()
        marker = state.get(DISCOVERY_TURNS_KEY)
        with DiscoveryReceiptFile(state_store.squad_dir, "discovery-turns") as file:
            raw = file._read()
            if raw is None and marker is None:
                return dict(token_usage=0, dispatch_count=0)
            envelope = json.loads(raw, object_pairs_hook=_pairs)
            _closed(envelope, ("payload", "sha256"))
            data = envelope["payload"]
            _validate(data)
            if envelope["sha256"] != _hash(data) or marker is None or marker["binding_sha256"] != _hash(data["binding"]):
                raise ValueError("discovery accounting receipt differs from selection")
            return _result_usage(data)
    except Exception:
        return dict(token_usage=None, dispatch_count=0)


def _remaining(deadline):
    remaining = deadline - time.time()
    if remaining < 0.001:
        raise _Blocked("provider_deadline_exhausted")
    return remaining
