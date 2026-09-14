"""Model processes are scripted; receipt/state/read owners are real."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess

import yaml

import pytest

from harness.squad_state import StateAdvanceError
from harness.ai_cli_backend import CliRunResult
from harness.discovery_semantics import DiscoveryAssignment
from tests.unit.test_discovery_bootstrap import case, bootstrap


KEY = "managed_discovery_turns"
MARKER = dict(schema_version=1, operation_id="discovery", binding_sha256="a" * 64)


@pytest.fixture
def enrolled(case):
    bootstrap(case, create=True)
    return case


def test_provider_marker_is_owned_and_exact_retry_keeps_revision(enrolled):
    _, state, _, _ = enrolled
    saved = state.prepare_discovery_turns(MARKER)
    assert saved[KEY] == MARKER
    assert state.prepare_discovery_turns(MARKER) == saved
    changed = deepcopy(saved)
    del changed[KEY]
    with pytest.raises(StateAdvanceError):
        state.save(changed)
    assert state.load() == saved


def test_generic_save_cannot_inject_provider_marker(enrolled):
    _, state, _, _ = enrolled
    original = state.load()
    changed = deepcopy(original)
    changed[KEY] = MARKER
    with pytest.raises(StateAdvanceError):
        state.save(changed)
    assert state.load() == original


def test_provider_marker_requires_completed_bootstrap(case):
    _, state, _, selection = case
    state.prepare_discovery_bootstrap(selection)
    original = state.load()
    with pytest.raises(StateAdvanceError):
        state.prepare_discovery_turns(MARKER)
    assert state.load() == original


@pytest.mark.parametrize("change", [dict(binding_sha256="bad"), dict(operation_id="other"), dict(extra=True), dict(schema_version=True)])
def test_invalid_provider_marker_cannot_change_state(enrolled, change):
    _, state, _, _ = enrolled
    original = state.load()
    with pytest.raises(StateAdvanceError):
        state.prepare_discovery_turns({**MARKER, **change})
    assert state.load() == original


@pytest.fixture
def prepared(enrolled, monkeypatch):
    root, state, store, selection = enrolled
    inputs = root / "inputs"
    inputs.mkdir()
    (inputs / "task.md").write_text("Create an isometric game.\n")
    bundle = root / ".echelon/prosaic/subagents"
    bundle.mkdir(parents=True)
    repo = Path(__file__).resolve().parents[2]
    for role in ("producer", "reviewer"):
        name = f"echelon.discovery-{role}.md"
        (bundle / name).write_bytes((repo / "prosaic/subagents" / name).read_bytes())
    actual_run = subprocess.run
    def inspect(command, **kwargs):
        if command[:2] != ["prosaic", "inspect"]:
            return actual_run(command, **kwargs)
        path = Path(command[4]) / command[2]
        _, metadata, body = path.read_text().split("---", 2)
        return subprocess.CompletedProcess(command, 0, json.dumps({"type": "subagent",
            "frontmatter": yaml.safe_load(metadata), "body": body}), "")
    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", inspect)
    return enrolled


def fingerprint(case):
    return hashlib.sha256((case[0] / "inputs/task.md").read_bytes()).hexdigest()


def assignment(case, **changes):
    return replace(DiscoveryAssignment("discovery", "propose-1", "game", "first", "propose",
        fingerprint(case), ("unknowns.md",)), **changes)


class ScriptedExecutor:
    supports_inspection_turn = True
    constrained_execution_configuration_id = "inspection-v1"

    def __init__(self, provider="codex", *, read=False, failure=None, usage=7):
        self.cli = self.provider_id = provider
        self.read, self.failure, self.usage = read, failure, usage
        self.calls = []

    def run_inspection_turn(self, private, prompt, *, frontmatter, timeout_ms):
        assert not list(Path(private).iterdir())
        assert set(frontmatter) == {"model_tier", "effort"}
        assert 0 < timeout_ms <= 300000
        payload = json.loads(prompt.split("\nHOST_INPUT_JSON\n", 1)[1])
        self.calls.append(payload)
        selected = payload["assignment"]
        if self.failure == "exception": raise RuntimeError("uncertain completion")
        if self.failure == "provider": return CliRunResult(1, "", "failed", token_usage=self.usage)
        if self.failure == "malformed": return CliRunResult(0, "[]", "", token_usage=self.usage)
        if self.failure == "blocked":
            reply = {**selected, "action": "blocked", "reason": "Cannot satisfy scope"}
        elif self.failure == "read_forever" or (self.read and not payload["reads"]):
            reply = {**selected, "action": "read", "request": {
                "op": "read_file", "root": "inputs", "path": "task.md", "start_line": 1, "line_count": 1}}
        elif selected["step"] == "propose":
            reply = {**selected, "action": "final", "new_subjects": [], "revisions": []}
        elif selected["step"] == "author":
            reply = {**selected, "action": "final", "artifacts": {"unknowns.md": "# Unknowns\r\nNo questions.\r\n"}}
        else:
            reply = {**selected, "action": "final", "verdict": "accept", "reason": "No changed identities", "assessments": []}
        return CliRunResult(0, json.dumps(reply), "", token_usage=self.usage)


def run(case, executor, *, selected=None, create=False, context=None, **kwargs):
    from harness.discovery_turns import run_discovery_step
    return run_discovery_step(case[0], case[1], executor, selected or assignment(case),
        context or {"task": "Create an isometric game"},
        roots=kwargs.pop("roots", {"inputs": case[0] / "inputs"}),
        check_inputs=kwargs.pop("check_inputs", lambda: fingerprint(case)), create=create, **kwargs)


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_completed_steps_replay_without_dispatch_or_recharging(prepared, provider):
    from tests.unit.test_element_identity_legacy_guard import sql_state
    history = sql_state(prepared[0])
    executor = ScriptedExecutor(provider, read=True)
    first = run(prepared, executor, create=True)
    assert first.reply["action"] == "final", first.reason
    assert first.token_usage == 14 and first.dispatch_count == 2
    assert executor.calls[1]["reads"][0]["response"]["text"] == "Create an isometric game.\n"
    replay = run(prepared, executor)
    assert replay == first
    assert len(executor.calls) == 2
    for step, expected in (("author", 28), ("review", 42)):
        result = run(prepared, executor, selected=assignment(prepared, step=step, dispatch_id=step))
        assert result.reply["action"] == "final", result.reason
        assert result.token_usage == expected
    assert (prepared[0] / "specs/game").is_dir()
    assert list((prepared[0] / "specs/game").iterdir()) == []
    assert sql_state(prepared[0]) == history


@pytest.mark.parametrize("failure", ["exception", "provider", "malformed", "blocked"])
def test_failed_or_uncertain_completion_cannot_be_bypassed(prepared, failure):
    executor = ScriptedExecutor(failure=failure)
    failed = run(prepared, executor, create=True)
    assert failed.reply is None
    assert failed.dispatch_count == 1
    assert failed.token_usage == (None if failure == "exception" else 7)
    executor.failure = None
    for selected in (assignment(prepared), assignment(prepared, dispatch_id="new-id")):
        result = run(prepared, executor, selected=selected)
        assert result.reply is None
        assert result.dispatch_count == 1
    assert len(executor.calls) == 1


@pytest.mark.parametrize("budget,usage,expected_calls", [(0, 7, 0), (6, 7, 1), (100, None, 1)])
def test_token_budget_counts_failed_calls_and_unknown_usage(prepared, budget, usage, expected_calls):
    executor = ScriptedExecutor(read=True, usage=usage)
    result = run(prepared, executor, create=True, token_budget=budget)
    assert result.reply is None
    assert result.dispatch_count == expected_calls
    assert len(executor.calls) == expected_calls
    retry = run(prepared, executor, token_budget=1000)
    assert retry.reply is None
    assert len(executor.calls) == expected_calls


def test_read_and_dispatch_limits_survive_restart(prepared):
    executor = ScriptedExecutor(failure="read_forever")
    result = run(prepared, executor, create=True)
    assert result.reply is None
    assert result.dispatch_count == 33
    assert result.token_usage == 231
    retry = run(prepared, executor)
    assert retry.reply is None and retry.dispatch_count == 33
    assert len(executor.calls) == 33


def test_shared_dispatch_ceiling_cannot_increase(prepared):
    executor = ScriptedExecutor()
    first = run(prepared, executor, create=True, dispatch_limit=1)
    assert first.reply is not None
    second = run(prepared, executor, selected=assignment(prepared, step="author", dispatch_id="author"), dispatch_limit=99)
    assert second.reply is None and second.dispatch_count == 1
    assert len(executor.calls) == 1


@pytest.mark.parametrize("damage", ["missing", "malformed", "symlink"])
def test_selected_receipt_file_cannot_be_reinitialized(prepared, damage):
    executor = ScriptedExecutor()
    assert run(prepared, executor, create=True).reply is not None
    path = prepared[1].squad_dir / "discovery-turns.json"
    if damage == "missing": path.unlink()
    if damage == "malformed": path.write_text("{")
    if damage == "symlink":
        retained = prepared[0] / "saved-receipt.json"
        path.rename(retained)
        path.symlink_to(retained)
    for create in (False, True):
        result = run(prepared, executor, create=create)
        assert result.reply is None and result.token_usage is None
    assert len(executor.calls) == 1


class Interrupted(BaseException):
    pass


@pytest.mark.parametrize("boundary", ["pending", "reply", "read", "final"])
@pytest.mark.parametrize("after", [False, True])
def test_crash_at_receipt_boundary_never_repeats_uncertain_dispatch(prepared, monkeypatch, boundary, after):
    from harness.discovery_receipts import DiscoveryReceiptFile
    actual = DiscoveryReceiptFile._write
    executor = ScriptedExecutor(read=boundary == "read")
    def crash(file, raw):
        data = json.loads(raw)["payload"]
        records = data["steps"][-1]["records"] if data["steps"] else []
        record = records[-1] if records else None
        hit = record is not None and {
            "pending": record["reply"] is None,
            "reply": record["reply"] is not None,
            "read": record["read"] is not None,
            "final": record.get("accepted", False),
        }[boundary]
        if hit and not after:
            raise Interrupted()
        actual(file, raw)
        if hit:
            raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(DiscoveryReceiptFile, "_write", crash)
        with pytest.raises(Interrupted):
            run(prepared, executor, create=True)
    calls = len(executor.calls)
    result = run(prepared, executor)
    resumable = (boundary == "pending" and not after) or (boundary in {"read", "final"} and after)
    assert (result.reply is not None) == resumable, result
    assert len(executor.calls) == calls + (int(resumable and boundary != "final"))
    if not resumable:
        assert run(prepared, executor, selected=assignment(prepared, dispatch_id="another")).reply is None
        assert len(executor.calls) == calls


@pytest.mark.parametrize("change", ["provider", "configuration", "role", "context", "assignment", "input", "policy", "roots"])
def test_changed_operation_or_step_binding_blocks_replay(prepared, change):
    executor = ScriptedExecutor()
    selected = assignment(prepared)
    assert run(prepared, executor, create=True, selected=selected).reply is not None
    kwargs = {}
    if change == "provider": executor.provider_id = "claude"
    if change == "configuration": executor.constrained_execution_configuration_id = "new"
    if change == "role":
        path = prepared[0] / ".echelon/prosaic/subagents/echelon.discovery-reviewer.md"
        path.write_text(path.read_text() + "\nChanged role.\n")
    if change == "context": kwargs["context"] = {"task": "Different scope"}
    if change == "assignment": selected = replace(selected, artifact_paths=("assumptions.md",))
    if change == "input": (prepared[0] / "inputs/task.md").write_text("Changed task")
    if change == "policy": kwargs["forbidden_paths"] = (prepared[0] / "inputs/task.md",)
    if change == "roots": kwargs["roots"] = {"different": prepared[0] / "inputs"}
    result = run(prepared, executor, selected=selected, **kwargs)
    assert result.reply is None
    assert result.token_usage == 7 and result.dispatch_count == 1
    assert len(executor.calls) == 1


def test_prior_host_read_is_revalidated_even_when_caller_fingerprint_is_unchanged(prepared):
    executor = ScriptedExecutor(read=True)
    selected = assignment(prepared)
    assert run(prepared, executor, selected=selected, create=True).reply is not None
    (prepared[0] / "inputs/task.md").write_text("Changed after read")
    for current in (selected, replace(selected, step="author", dispatch_id="author")):
        result = run(prepared, executor, selected=current, check_inputs=lambda: selected.input_fingerprint)
        assert result.reply is None and result.reason == "discovery_provider_read_changed"
    assert len(executor.calls) == 2


@pytest.mark.parametrize("when", ["before", "during"])
def test_input_change_cannot_reach_acceptance(prepared, when):
    selected = assignment(prepared)
    class ChangingExecutor(ScriptedExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            (prepared[0] / "inputs/task.md").write_text("Changed during call")
            return result
    executor = ChangingExecutor()
    if when == "before": (prepared[0] / "inputs/task.md").write_text("Changed before call")
    result = run(prepared, executor, selected=selected, create=True)
    assert result.reply is None and result.reason == "discovery_provider_inputs_changed"
    assert len(executor.calls) == int(when == "during")


def test_retained_step_deadline_does_not_restart(prepared, monkeypatch):
    from harness.discovery_receipts import DiscoveryReceiptFile
    actual = DiscoveryReceiptFile._write
    instant = [1000.0]
    monkeypatch.setattr("harness.discovery_turns.time.time", lambda: instant[0])
    def crash(file, raw):
        payload = json.loads(raw)["payload"]
        if payload["steps"] and payload["steps"][-1]["records"]:
            raise Interrupted()
        actual(file, raw)
    executor = ScriptedExecutor()
    with monkeypatch.context() as patch:
        patch.setattr(DiscoveryReceiptFile, "_write", crash)
        with pytest.raises(Interrupted):
            run(prepared, executor, create=True)
    instant[0] += 301
    result = run(prepared, executor)
    assert result.reply is None and result.reason == "provider_deadline_exhausted"
    assert len(executor.calls) == 0


def test_expired_provider_reply_is_charged_but_not_accepted(prepared, monkeypatch):
    instant = [1000.0]
    monkeypatch.setattr("harness.discovery_turns.time.time", lambda: instant[0])
    class SlowExecutor(ScriptedExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            instant[0] += 301
            return result
    executor = SlowExecutor()
    result = run(prepared, executor, create=True)
    assert result.reply is None and result.reason == "provider_deadline_exhausted"
    assert result.token_usage == 7
    assert run(prepared, executor).reply is None
    assert len(executor.calls) == 1


def test_completed_receipt_can_replay_after_deadline(prepared, monkeypatch):
    instant = [1000.0]
    monkeypatch.setattr("harness.discovery_turns.time.time", lambda: instant[0])
    executor = ScriptedExecutor()
    first = run(prepared, executor, create=True)
    assert first.reply is not None
    instant[0] += 301
    assert run(prepared, executor) == first
    assert len(executor.calls) == 1


def test_step_ceiling_is_operation_wide(prepared):
    executor = ScriptedExecutor()
    for index in range(9):
        result = run(prepared, executor, selected=assignment(prepared, dispatch_id=f"step-{index}"), create=index == 0)
        assert result.reply is not None
    result = run(prepared, executor, selected=assignment(prepared, dispatch_id="step-9"))
    assert result.reply is None and result.reason == "provider_step_limit_exhausted"
    assert result.token_usage == 63 and len(executor.calls) == 9


def test_unknown_usage_without_finite_budget_stays_explicit(prepared):
    executor = ScriptedExecutor(usage=None)
    first = run(prepared, executor, create=True)
    assert first.reply is not None and first.token_usage is None
    assert run(prepared, executor) == first
    assert run(prepared, executor, token_budget=100).reply is None
    assert run(prepared, executor).reply is None
    assert len(executor.calls) == 1


def test_tightened_token_budget_cannot_be_raised(prepared):
    executor = ScriptedExecutor()
    assert run(prepared, executor, create=True, token_budget=100).reply is not None
    assert run(prepared, executor, token_budget=7).reply is not None
    result = run(prepared, executor, token_budget=100, selected=assignment(prepared, dispatch_id="next"))
    assert result.reply is None and result.reason == "provider_token_budget_exhausted"
    assert len(executor.calls) == 1


@pytest.mark.parametrize("oversized", ["prompt", "reply"])
def test_model_payload_size_limits(prepared, oversized):
    class LargeExecutor(ScriptedExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            return replace(result, stdout=" " * (256 * 1024 + 1))
    executor = LargeExecutor()
    context = {"task": "x" * (1024 * 1024 + 1)} if oversized == "prompt" else None
    result = run(prepared, executor, context=context, create=True)
    assert result.reply is None
    assert len(executor.calls) == int(oversized == "reply")


@pytest.mark.parametrize("boundary", ["prosaic", "inputs", "pending"])
def test_expired_preparation_never_dispatches_model(prepared, monkeypatch, boundary):
    from harness.discovery_receipts import DiscoveryReceiptFile
    instant = [1000.0]
    monkeypatch.setattr("harness.discovery_turns.time.time", lambda: instant[0])
    if boundary == "prosaic":
        actual = subprocess.run
        def slow_inspect(command, **kwargs):
            result = actual(command, **kwargs)
            instant[0] += 301
            return result
        monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", slow_inspect)
    if boundary == "pending":
        actual = DiscoveryReceiptFile._write
        def slow_write(file, raw):
            actual(file, raw)
            data = json.loads(raw)["payload"]
            if data["steps"] and data["steps"][-1]["records"]:
                instant[0] += 301
        monkeypatch.setattr(DiscoveryReceiptFile, "_write", slow_write)
    checks = []
    def check():
        checks.append(True)
        if boundary == "inputs" and len(checks) == 2:
            instant[0] += 301
        return fingerprint(prepared)
    executor = ScriptedExecutor()
    result = run(prepared, executor, create=True, check_inputs=check)
    assert result.reply is None and result.reason == "provider_deadline_exhausted"
    assert len(executor.calls) == 0


def test_prosaic_loads_receive_remaining_preparation_timeout(prepared, monkeypatch):
    instant = [1000.0]
    monkeypatch.setattr("harness.discovery_turns.time.time", lambda: instant[0])
    actual = subprocess.run
    timeouts = []
    def inspect(command, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        result = actual(command, **kwargs)
        instant[0] += 10
        return result
    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", inspect)
    result = run(prepared, ScriptedExecutor(), create=True)
    assert result.reply is not None
    assert timeouts == [300.0, 290.0]


@pytest.mark.parametrize("boundary", ["marker", "journal"])
@pytest.mark.parametrize("after", [False, True])
def test_creation_crash_never_resets_selected_receipts(prepared, monkeypatch, boundary, after):
    from harness.discovery_receipts import DiscoveryReceiptFile
    executor = ScriptedExecutor()
    actual_marker = prepared[1].prepare_discovery_turns
    actual_write = DiscoveryReceiptFile._write
    def marker(value):
        if not after: raise Interrupted()
        actual_marker(value)
        raise Interrupted()
    def journal(file, raw):
        if not after: raise Interrupted()
        actual_write(file, raw)
        raise Interrupted()
    with monkeypatch.context() as patch:
        if boundary == "marker": patch.setattr(prepared[1], "prepare_discovery_turns", marker)
        else: patch.setattr(DiscoveryReceiptFile, "_write", journal)
        with pytest.raises(Interrupted):
            run(prepared, executor, create=True)
    assert len(executor.calls) == 0
    result = run(prepared, executor)
    assert (result.reply is not None) == (boundary == "journal" and after)
    if boundary == "marker" and not after:
        assert run(prepared, executor, create=True).reply is not None
    else:
        assert run(prepared, executor, create=True).reply is None
    assert len(executor.calls) == int((boundary == "journal" and after) or (boundary == "marker" and not after))


@pytest.mark.parametrize("damage", ["checksum", "extra", "usage", "acceptance", "duplicate", "version", "assignment"])
def test_corrupt_retained_envelope_refuses_without_repair(prepared, damage):
    executor = ScriptedExecutor()
    assert run(prepared, executor, create=True).reply is not None
    path = prepared[1].squad_dir / "discovery-turns.json"
    envelope = json.loads(path.read_text())
    payload = envelope["payload"]
    record = payload["steps"][0]["records"][0]
    if damage == "extra": payload["extra"] = True
    if damage == "usage": record["token_usage"] = True
    if damage == "acceptance": record["accepted"] = 1
    if damage == "version": payload["schema_version"] = True
    if damage == "assignment": payload["steps"][0]["assignment"]["step"] = "bogus"
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    envelope["sha256"] = "bad" if damage == "checksum" else hashlib.sha256(canonical.encode("ascii")).hexdigest()
    raw = json.dumps(envelope)
    if damage == "duplicate": raw = raw.replace('"payload":', '"payload": {}, "payload":', 1)
    path.write_text(raw)
    result = run(prepared, executor)
    assert result.reply is None and result.token_usage is None
    assert len(executor.calls) == 1
    assert path.read_text() == raw


def test_active_receipt_lock_refuses_second_execution(prepared):
    from harness.discovery_receipts import DiscoveryReceiptFile
    executor = ScriptedExecutor()
    with DiscoveryReceiptFile(prepared[1].squad_dir, "discovery-turns"):
        result = run(prepared, executor, create=True)
    assert result.reply is None and len(executor.calls) == 0
    assert KEY not in prepared[1].load()


def test_host_denied_read_freezes_operation(prepared):
    executor = ScriptedExecutor(read=True)
    denied = (prepared[0] / "inputs/task.md",)
    first = run(prepared, executor, forbidden_paths=denied, create=True)
    assert first.reply is None and first.token_usage == 7
    assert run(prepared, executor, forbidden_paths=denied).reply is None
    assert len(executor.calls) == 1


def test_post_reply_verification_cannot_accept_after_deadline(prepared, monkeypatch):
    instant = [1000.0]
    monkeypatch.setattr("harness.discovery_turns.time.time", lambda: instant[0])
    checks = []
    def check():
        checks.append(True)
        if len(checks) == 3: instant[0] += 301
        return fingerprint(prepared)
    executor = ScriptedExecutor()
    result = run(prepared, executor, create=True, check_inputs=check)
    assert result.reply is None and result.reason == "provider_deadline_exhausted"
    assert result.token_usage == 7 and len(executor.calls) == 1
    assert run(prepared, executor).reply is None
    assert len(executor.calls) == 1


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_author_receipt_preserves_mixed_width_ids_and_exact_utf8(prepared, provider):
    ids = ("U-01", "U-000001", "A-1000000")
    text = "# Questions\r\n" + "\r\n".join(f"{label}: světlo — hrdina 🧙" for label in ids) + "\r\n"
    class AuthorExecutor(ScriptedExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            reply = json.loads(result.stdout)
            reply["artifacts"]["unknowns.md"] = text
            return replace(result, stdout=json.dumps(reply, ensure_ascii=False))
    executor = AuthorExecutor(provider)
    selected = assignment(prepared, step="author", dispatch_id="author", assigned_ids=ids)
    first = run(prepared, executor, selected=selected, create=True)
    assert first.reply["assigned_ids"] == list(ids)
    assert first.reply["artifacts"]["unknowns.md"].encode("utf-8") == text.encode("utf-8")
    assert run(prepared, executor, selected=selected) == first
    assert len(executor.calls) == 1
