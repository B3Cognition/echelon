"""State/receipt ownership only; these shape fixtures confer no publication proof."""
from copy import deepcopy
import json

import pytest

from harness.discovery_operation_state import operation_from_state
from harness.discovery_producer import tracker_round
from harness.discovery_receipts import DiscoveryReceiptFile, receipt_round_operation_id
from harness.discovery_spec import clarification_source
from harness.squad_state import StateAdvanceError
from tests.unit.test_discovery_turns import case, enrolled, prepared as turn_prepared
from tests.unit.test_why1_tracker_parent import source


def approval():
    from tests.unit.test_blocked_decision import _v3_decision
    from harness.human_input import AppliedHumanInputResolution
    from harness.squad_state import build_human_input_resolution_postimage
    decision = _v3_decision(source_kind="human_gate", producer_id="checkpoint-assess",
        source_phase="checkpoint-assess", reason_code="checkpoint_assess_decision_required",
        resolution_handler="gate_outcome", status="awaiting_human", autonomy_mode="guided")
    decision = build_human_input_resolution_postimage(decision,
        AppliedHumanInputResolution("approve", None, "user"), resolved_at="2026-09-17T12:00:00+00:00")
    return dict(decision=decision, completion=dict(schema_version=1, decision_id=decision["id"],
        completion_id="a" * 32, intent_sha256="1" * 64, receipts_sha256="2" * 64,
        publication_binding_sha256="3" * 64))


@pytest.fixture
def approved(enrolled):
    _, store, _, _ = enrolled
    association = approval()
    state = store.load()
    state.update(phase="phase2-decide", autonomy_mode="guided",
        blocked_decision=association["decision"], last_human_input_completion=association["completion"],
        last_dispatch={**source("f"), "phase_id": "phase1-why2", "post_dispatch_complete": True})
    # The state owner checks shape/CAS; execution separately requires released
    # v30 proof. Do not use this fixture to claim an authenticated parent.
    store._path.write_text(json.dumps(state))
    return enrolled


def binding(letter="a"):
    paths = ["feasibility.md", "prioritization.md", "estimates.md", "mvp-scope.md", "kill-report.md"]
    return dict(operation_id="feasibility-" + letter * 32, spec_id="game", run_id="first",
        input_tree="inputs", artifact_paths=paths, editable_revisions=[], unowned_writable_paths=paths,
        intent=dict(kind="assess", request="Assess the approved game specification"), fingerprint="b" * 64)


def select(store):
    before = store.load()
    return store.prepare_spec_round("feasibility", clarification_source(before["last_human_input_completion"]),
        expected_state=before)


def test_selection_retains_approval_and_charges_only_one_operation(approved):
    _, store, _, _ = approved
    before = store.load()
    selected = select(store)
    assert select(store) == selected
    assert selected["phase_dispatch_counts"] == before["phase_dispatch_counts"]
    row = tracker_round(selected, producer="feasibility")
    assert row["resolution"] == approval() and row["source"] == source("a")
    assert row["predecessor"] is None
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round("feasibility", source("a"), expected_state=before)
    prepared = store.advance_discovery_operation(binding(), "prepare", producer="feasibility")
    assert operation_from_state(prepared, "feasibility")["binding"] == binding()
    assert prepared["phase_dispatch_counts"]["phase2-decide"] == 1
    assert store.advance_discovery_operation(binding(), "prepare", producer="feasibility") == prepared
    for damage in ("drop", "approval", "source", "active", "operation", "turns"):
        changed = deepcopy(prepared)
        rounds = changed["managed_feasibility_rounds"]
        row = rounds["rounds"][rounds["active"]]
        if damage == "drop": del changed["managed_feasibility_rounds"]
        elif damage == "approval": row["resolution"]["decision"]["selected_option_id"] = "reject"
        elif damage == "source": row["source"] = source("b")
        elif damage == "active": rounds["active"] = "feasibility-" + "b" * 32
        elif damage == "operation": row["operation"] = None
        else: row["turns"] = dict(schema_version=1, operation_id=binding()["operation_id"], binding_sha256="c" * 64)
        with pytest.raises(StateAdvanceError):
            store.save(changed)
    assert store.load() == prepared


@pytest.mark.parametrize("damage", ["reject", "missing_receipt", "different_receipt", "wrong_owner", "unfinished", "cancelled", "blocked", "wrong_phase", "wrong_parent", "pending_completion"])
def test_first_selection_requires_exact_settled_approval_shape(approved, damage):
    _, store, _, _ = approved
    valid = store.load()
    state = deepcopy(valid)
    if damage == "reject": state["blocked_decision"]["selected_option_id"] = "reject"
    elif damage == "missing_receipt": del state["last_human_input_completion"]
    elif damage == "different_receipt": state["last_human_input_completion"]["decision_id"] = "different"
    elif damage == "wrong_owner": state["blocked_decision"]["source_phase"] = "checkpoint-plan"
    elif damage == "unfinished": state["last_dispatch"]["post_dispatch_complete"] = False
    elif damage == "cancelled": state["cancel_requested"] = True
    elif damage == "blocked": state["status"] = "blocked"
    elif damage == "wrong_phase": state["phase"] = "phase3-specialists"
    elif damage == "wrong_parent": state["last_dispatch"]["phase_id"] = "phase2-feasibility-structural"
    else: state["pending_controller_completion"] = {}
    store._path.write_text(json.dumps(state))
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round("feasibility", source("a"), expected_state=state)
    assert store.load() == state
    store._path.write_text(json.dumps(valid))
    assert tracker_round(select(store), producer="feasibility")["resolution"] == approval()


def test_structural_retry_preserves_accepted_predecessor_and_separate_receipts(approved):
    _, store, _, _ = approved
    select(store)
    store.advance_discovery_operation(binding(), "prepare", producer="feasibility")
    next_state = store.load()
    next_state["last_dispatch"] = {**source("b"), "phase_id": "phase2-feasibility-structural", "post_dispatch_complete": True}
    store.save(next_state)
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round("feasibility", source("b"), expected_state=store.load())
    store.advance_discovery_operation(binding(), "begin", producer="feasibility")
    store.advance_discovery_operation(binding(), "finish", producer="feasibility",
        result=dict(status="accepted", candidate_sha256="c" * 64, findings_sha256="d" * 64))
    previous = store.load()["managed_feasibility_rounds"]
    saved = store.prepare_spec_round("feasibility", source("b"), expected_state=store.load())
    rounds = saved["managed_feasibility_rounds"]
    assert rounds["rounds"][previous["active"]] == previous["rounds"][previous["active"]]
    row = rounds["rounds"][rounds["active"]]
    assert row["predecessor"] == previous["active"] and row["resolution"] is None
    assert store.prepare_spec_round("feasibility", source("b"), expected_state=saved) == saved
    files = [DiscoveryReceiptFile(store.squad_dir, "discovery-turns", producer="feasibility",
        round_operation_id=receipt_round_operation_id("feasibility", operation)) for operation in rounds["rounds"]]
    assert files[0].path != files[1].path
    with pytest.raises(StateAdvanceError):
        store.prepare_spec_round("feasibility", source("a"), expected_state=saved)


@pytest.mark.parametrize("operation", [None, "feasibility-../outside", "lexicon-" + "a" * 32, "feasibility-" + "a" * 31])
def test_receipts_require_exact_feasibility_round(approved, operation):
    with pytest.raises(ValueError):
        DiscoveryReceiptFile(approved[1].squad_dir, "discovery-turns", producer="feasibility", round_operation_id=operation)


@pytest.mark.parametrize("damage", ["missing_approval", "detached_receipt", "controller_approval", "refresh", "foreign_parent"])
def test_retained_round_cannot_lose_approval_or_borrow_other_round_protocols(approved, damage):
    from harness.discovery_producer import tracker_rounds
    _, store, _, _ = approved
    state = select(store)
    before = deepcopy(state)
    row = state["managed_feasibility_rounds"]["rounds"][binding()["operation_id"]]
    if damage == "missing_approval": row["resolution"] = None
    elif damage == "detached_receipt": row["resolution"]["completion"]["intent_sha256"] = "d" * 64
    elif damage == "controller_approval": row["resolution"]["decision"]["resolved_by"] = "controller"
    elif damage == "refresh": row["refresh"] = {}
    else: row["tracker_parent"] = "tracker-" + "f" * 32
    with pytest.raises(ValueError): tracker_rounds(state, "feasibility")
    assert store.load() == before


@pytest.mark.parametrize("kind", ["derive", "synthesize", "repair"])
def test_feasibility_operation_refuses_other_intents(approved, kind):
    _, store, _, _ = approved
    select(store)
    altered = binding()
    altered["intent"]["kind"] = kind
    with pytest.raises(StateAdvanceError):
        store.advance_discovery_operation(altered, "prepare", producer="feasibility")
    assert operation_from_state(store.load(), "feasibility") is None


@pytest.fixture
def turns(approved, turn_prepared):
    from pathlib import Path
    root, store, _, _ = approved
    bundle = root / ".echelon/prosaic/subagents"
    repo = Path(__file__).resolve().parents[2]
    for role in ("producer", "reviewer"):
        name = "echelon.feasibility-" + role + ".md"
        (bundle / name).write_bytes((repo / "prosaic/subagents" / name).read_bytes())
    select(store)
    return approved


def turn_assignment(case, step="propose"):
    from harness.discovery_semantics import DiscoveryAssignment
    from tests.unit.test_discovery_turns import fingerprint
    return DiscoveryAssignment(binding()["operation_id"], "attempt-1-" + step, "game", "first", step,
        fingerprint(case), tuple(binding()["artifact_paths"]), producer="feasibility",
        routing=tuple(dict(verdict="PASS", state_updates={}).items()) if step == "review" else None)


class FeasibilityExecutor:
    supports_inspection_turn = True
    constrained_execution_configuration_id = "inspection-v1"

    def __init__(self, provider="codex", *, failure=None, forbidden_read=False, reject=0,
            feasibility_text="# Feasibility\nFeasible with one generated scene.\n"):
        self.cli = self.provider_id = provider
        self.failure, self.forbidden_read, self.reject = failure, forbidden_read, reject
        self.calls = []
        self.feasibility_text = feasibility_text

    def run_inspection_turn(self, private, prompt, *, frontmatter, timeout_ms):
        from pathlib import Path
        from harness.ai_cli_backend import CliRunResult
        assert not list(Path(private).iterdir())
        assert set(frontmatter) == {"model_tier", "effort"} and 0 < timeout_ms <= 300000
        payload = json.loads(prompt.split("\nHOST_INPUT_JSON\n", 1)[1])
        self.calls.append(payload)
        assignment, context = payload["assignment"], payload["context"]
        if self.failure == "exception": raise RuntimeError("Unknown completion")
        if self.failure == "malformed": return CliRunResult(0, "[]", "", token_usage=7)
        if self.forbidden_read:
            fields = dict(action="read", request=dict(op="read_file", root="run", path="state.json", start_line=1, line_count=1))
        elif assignment["step"] == "propose":
            fields = dict(action="final", new_subjects=[], revisions=[])
        elif assignment["step"] == "author":
            fields = dict(action="final", artifacts={
                "feasibility.md": self.feasibility_text,
                "prioritization.md": "# Prioritization\nScene, lighting, movement.\n",
                "estimates.md": "# Estimates\nOne small prototype iteration.\n",
                "mvp-scope.md": "# MVP Scope\nOne movable player in a lit scene.\n",
                "kill-report.md": context.get("baseline", {}).get("kill-report.md")},
                routing=dict(verdict="PASS", state_updates={}))
        else:
            rejected = sum(call["assignment"]["step"] == "review" for call in self.calls) <= self.reject
            fields = dict(action="final", verdict="reject" if rejected else "accept",
                reason="Specify movement bounds" if rejected else "Fits approved prototype scope", assessments=[])
        return CliRunResult(0, json.dumps({**assignment, **fields}), "", token_usage=7)


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_feasibility_steps_replay_without_provider_calls_or_history_changes(turns, provider):
    from tests.unit.test_discovery_turns import run
    executor = FeasibilityExecutor(provider)
    history = turns[2].identity_history(spec_id="game")
    for index, step in enumerate(("propose", "author", "review"), 1):
        result = run(turns, executor, selected=turn_assignment(turns, step), create=index == 1)
        assert result.reply is not None, result.reason
        assert result.token_usage == index * 7 and result.dispatch_count == index
        replay = run(turns, executor, selected=turn_assignment(turns, step), replay_only=True)
        assert replay.reply == result.reply and replay.token_usage == result.token_usage
        assert replay.dispatch_count == index and len(executor.calls) == index
    before = turns[1].load()
    assert tracker_round(before, producer="feasibility")["turns"]["operation_id"] == binding()["operation_id"]
    changed = deepcopy(before)
    row = changed["managed_feasibility_rounds"]["rounds"][binding()["operation_id"]]
    row["turns"] = None
    with pytest.raises(StateAdvanceError): turns[1].save(changed)
    assert turns[2].identity_history(spec_id="game") == history
    assert list((turns[0] / "specs/game").iterdir()) == []


@pytest.mark.parametrize("failure", ["exception", "malformed"])
def test_unknown_feasibility_turn_is_not_retried(turns, failure):
    from tests.unit.test_discovery_turns import run
    executor = FeasibilityExecutor(failure=failure)
    first = run(turns, executor, selected=turn_assignment(turns), create=True)
    assert first.reply is None and first.dispatch_count == 1
    executor.failure = None
    again = run(turns, executor, selected=turn_assignment(turns))
    assert again.reply is None and again.dispatch_count == 1
    assert len(executor.calls) == 1


def test_feasibility_provider_cannot_read_its_run_state(turns):
    from tests.unit.test_discovery_turns import run
    executor = FeasibilityExecutor(forbidden_read=True)
    result = run(turns, executor, selected=turn_assignment(turns), create=True,
        roots={"run": turns[1].squad_dir})
    assert result.reply is None
    assert not executor.calls, "The run-directory read root must be rejected before dispatch"
