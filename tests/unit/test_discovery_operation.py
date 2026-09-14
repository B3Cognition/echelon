"""Discovery composition uses real state, captured sources and identity owners."""
from copy import deepcopy
from dataclasses import replace
import json
import hashlib
from pathlib import Path

import pytest

from harness.squad_state import StateAdvanceError
from tests.unit.test_discovery_bootstrap import case
from tests.unit.test_discovery_turns import enrolled, prepared as turn_prepared
from tests.unit.test_discovery_turns import ScriptedExecutor
from tests.unit.test_discovery_turns import Interrupted


KEY = "managed_discovery_operation"


@pytest.fixture
def prepared(turn_prepared):
    from echelon.context_builder import build_run_context
    root = turn_prepared[0]
    templates = root / ".echelon/runtime/templates"
    templates.mkdir(parents=True)
    repo = Path(__file__).resolve().parents[2]
    for name in ("unknowns", "assumptions", "glossary", "mental-model", "boundaries", "reference-architectures"):
        filename = name + "-template.md"
        (templates / filename).write_bytes((repo / "runtime/templates" / filename).read_bytes())
    (root / ".echelon/config.yml").write_bytes((repo / "runtime/config-template.yml").read_bytes())
    build_run_context(root, turn_prepared[1].squad_dir, user_request="Create an isometric game")
    return turn_prepared


def binding():
    return dict(operation_id="discovery", spec_id="game", run_id="first", input_tree="inputs",
        artifact_paths=["unknowns.md", "assumptions.md"], editable_revisions=[],
        unowned_writable_paths=["unknowns.md", "assumptions.md"],
        intent={"kind": "create", "request": "Create an isometric game"}, fingerprint="a" * 64)


def result(status="rejected", candidate="b"):
    return dict(status=status, candidate_sha256=candidate * 64, findings_sha256="c" * 64)


def test_operation_and_attempt_selection_are_owned_and_replayable(enrolled):
    state = enrolled[1]
    selected = state.advance_discovery_operation(binding(), "prepare")
    assert selected[KEY]["attempts"] == []
    assert state.advance_discovery_operation(binding(), "prepare") == selected
    begun = state.advance_discovery_operation(binding(), "begin")
    assert begun[KEY]["attempts"] == [dict(number=1, result=None)]
    assert state.advance_discovery_operation(binding(), "begin") == begun
    finished = state.advance_discovery_operation(binding(), "finish", result=result())
    assert state.advance_discovery_operation(binding(), "finish", result=result()) == finished
    for changed in ({key: value for key, value in finished.items() if key != KEY},
                    {**finished, KEY: {**finished[KEY], "attempts": []}}):
        with pytest.raises(StateAdvanceError): state.save(changed)
    assert state.load() == finished


def test_operation_requires_completed_bootstrap(case):
    with pytest.raises(StateAdvanceError):
        case[1].advance_discovery_operation(binding(), "prepare")


def test_generic_state_cannot_inject_operation(enrolled):
    state = enrolled[1]
    changed = {**state.load(), KEY: dict(schema_version=1, binding=binding(), attempts=[])}
    with pytest.raises(StateAdvanceError): state.save(changed)
    assert KEY not in state.load()


@pytest.mark.parametrize("changed", ["input_tree", "fingerprint", "intent", "artifact_paths"])
def test_changed_operation_cannot_reset_attempts(enrolled, changed):
    state = enrolled[1]
    state.advance_discovery_operation(binding(), "prepare")
    before = state.advance_discovery_operation(binding(), "begin")
    other = binding()
    other[changed] = {"input_tree": "other", "fingerprint": "d" * 64,
        "intent": {"kind": "create", "request": "Another game"}, "artifact_paths": ["unknowns.md"]}[changed]
    with pytest.raises(StateAdvanceError): state.advance_discovery_operation(other, "prepare")
    assert state.load() == before


def test_operation_consumes_at_most_three_attempts(enrolled):
    state = enrolled[1]
    state.advance_discovery_operation(binding(), "prepare")
    for number in (1, 2, 3):
        begun = state.advance_discovery_operation(binding(), "begin")
        assert len(begun[KEY]["attempts"]) == number
        state.advance_discovery_operation(binding(), "finish", result=result(candidate=str(number)))
    before = state.load()
    with pytest.raises(StateAdvanceError): state.advance_discovery_operation(binding(), "begin")
    assert state.load() == before


def test_accepted_operation_cannot_start_another_attempt(enrolled):
    state = enrolled[1]
    state.advance_discovery_operation(binding(), "prepare")
    state.advance_discovery_operation(binding(), "begin")
    before = state.advance_discovery_operation(binding(), "finish", result=result("accepted"))
    with pytest.raises(StateAdvanceError): state.advance_discovery_operation(binding(), "begin")
    with pytest.raises(StateAdvanceError): state.advance_discovery_operation(binding(), "finish", result=result())
    assert state.load() == before


class DiscoveryExecutor(ScriptedExecutor):
    def __init__(self, provider="codex", *, reject=0, invalid_author=False, failure=None, stale_citation=False):
        super().__init__(provider, failure=failure)
        self.reject, self.invalid_author, self.stale_citation = reject, invalid_author, stale_citation
        self.review_count = 0

    def run_inspection_turn(self, *args, **kwargs):
        result = super().run_inspection_turn(*args, **kwargs)
        if self.failure:
            return result
        payload = self.calls[-1]
        selected, context = payload["assignment"], payload["context"]
        if selected["step"] == "propose":
            fields = dict(new_subjects=[dict(key="camera", kind="U", subject="Isometric projection choice", caption="Camera choice")], revisions=[])
        elif selected["step"] == "author":
            reserved = context["reservations"]
            assert reserved[0]["key"] == "camera" and reserved[0]["element_id"] == "U-000001"
            content = "### U-000001: Camera choice\r\nShould movement follow the camera?\r\n"
            if context["feedback"]:
                content = content.replace("Should movement", "How should movement")
            if self.invalid_author: content = content.replace("U-000001", "U-000002")
            fields = dict(artifacts={"unknowns.md": content, "assumptions.md": "# Assumptions\r\nSee U-000001.\r\n"})
        else:
            self.review_count += 1
            verdict = "reject" if self.review_count <= self.reject else "accept"
            fields = dict(verdict=verdict, reason="Clarify controls" if verdict == "reject" else "Same stable question",
                assessments=[dict(id=label, verdict=verdict, reason="Camera meaning checked",
                    evidence=["candidate:stale" if self.stale_citation else context["citations"][label]])
                    for label in selected["assigned_ids"]])
        return replace(result, stdout=json.dumps({**selected, "action": "final", **fields}))


def execute(case, executor, *, create=False, **changes):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_operation import run_discovery_operation
    args = dict(input_tree="inputs", artifact_paths=("unknowns.md", "assumptions.md"),
        unowned_writable_paths=("unknowns.md", "assumptions.md"), intent=binding()["intent"])
    with PhaseAExecutionLock.acquire(case[0], "test-discovery"):
        with SpecRunExecutionLock.acquire(case[1].squad_dir, "test-discovery"):
            return run_discovery_operation(case[0], case[1], executor, create=create, **{**args, **changes})


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_proposal_reservation_author_preview_review_replay_without_publication(prepared, provider):
    executor = DiscoveryExecutor(provider)
    first = execute(prepared, executor, create=True)
    assert first.status == "reviewed", first.reason
    assert first.token_usage == 21 and first.dispatch_count == 3
    assert [call["assignment"]["step"] for call in executor.calls] == ["propose", "author", "review"]
    candidate = first.candidate
    assert candidate.review["verdict"] == "accept"
    assert "U-000001" in candidate.history.payload
    assert list((prepared[0] / "specs/game").iterdir()) == []
    assert json.loads(prepared[2].identity_history(spec_id="game").payload)["entities"] == []
    assert execute(prepared, executor) == first
    assert len(executor.calls) == 3
    assert prepared[1].load()[KEY]["attempts"][0]["result"]["status"] == "accepted"


def test_semantic_repair_reuses_reserved_id_and_counts_attempt_before_turn(prepared):
    class CountedExecutor(DiscoveryExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            before = prepared[1].load()[KEY]["attempts"]
            assert before[-1]["result"] is None
            return super().run_inspection_turn(*args, **kwargs)
    executor = CountedExecutor(reject=1)
    result = execute(prepared, executor, create=True)
    assert result.status == "reviewed", result.reason
    assert result.token_usage == 42 and result.dispatch_count == 6
    assert len(prepared[1].load()[KEY]["attempts"]) == 2
    assert all(call["context"]["reservations"][0]["element_id"] == "U-000001"
               for call in executor.calls if call["assignment"]["step"] == "author")
    assert list((prepared[0] / "specs/game").iterdir()) == []


def test_invalid_author_never_reaches_reviewer_or_accepted_history(prepared):
    executor = DiscoveryExecutor(invalid_author=True)
    result = execute(prepared, executor, create=True)
    assert result.status == "blocked"
    assert result.reason == "discovery_no_progress"
    assert executor.review_count == 0
    assert len(executor.calls) <= 6
    assert list((prepared[0] / "specs/game").iterdir()) == []


@pytest.mark.parametrize("failure", ["exception", "malformed"])
def test_uncertain_or_invalid_model_reply_never_gets_another_attempt(prepared, failure):
    executor = DiscoveryExecutor(failure=failure)
    first = execute(prepared, executor, create=True)
    assert first.status == "blocked"
    assert len(executor.calls) == 1
    executor.failure = None
    assert execute(prepared, executor).status == "blocked"
    assert len(executor.calls) == 1
    assert len(prepared[1].load()[KEY]["attempts"]) == 1


def test_unknown_candidate_citation_blocks_without_auto_retry(prepared):
    executor = DiscoveryExecutor(stale_citation=True)
    first = execute(prepared, executor, create=True)
    assert first.status == "blocked" and first.reason == "discovery_review_citation_mismatch"
    assert execute(prepared, executor).status == "blocked"
    assert len(executor.calls) == 3


def test_reviewer_can_cite_exact_captured_source_alongside_candidate(prepared):
    citation = "source:inputs/task.md:" + hashlib.sha256(b"Create an isometric game.\n").hexdigest()
    class SourceExecutor(DiscoveryExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            reply = json.loads(result.stdout)
            if reply["step"] == "review": reply["assessments"][0]["evidence"].append(citation)
            return replace(result, stdout=json.dumps(reply))
    executor = SourceExecutor()
    result = execute(prepared, executor, create=True)
    assert result.status == "reviewed", result.reason
    assert result.candidate.review["assessments"][0]["evidence"][-1] == citation
    assert execute(prepared, executor) == result


def test_three_rejected_attempts_exhaust_without_reset_on_resume(prepared):
    class ChangingExecutor(DiscoveryExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            reply = json.loads(result.stdout)
            if reply["step"] == "author":
                reply["artifacts"]["unknowns.md"] += f"Clarification {reply['dispatch_id']}.\n"
            return replace(result, stdout=json.dumps(reply))
    executor = ChangingExecutor(reject=99)
    result = execute(prepared, executor, create=True)
    assert result.status == "blocked" and result.reason == "discovery_attempts_exhausted"
    assert result.token_usage == 63 and result.dispatch_count == 9
    assert len(prepared[1].load()[KEY]["attempts"]) == 3
    assert execute(prepared, executor) == result
    assert len(executor.calls) == 9


@pytest.mark.parametrize("damage", ["input", "new_input", "source", "reservation", "turns", "operation"])
def test_changed_inputs_or_missing_receipts_block_completed_replay(prepared, damage):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    if damage == "input": (prepared[0] / "inputs/task.md").write_text("Changed request")
    if damage == "new_input": (prepared[0] / "inputs/new.md").write_text("New dependency")
    if damage == "source": (prepared[0] / "specs/game/unknowns.md").write_text("Unpublished edit")
    if damage == "reservation": (prepared[1].squad_dir / "discovery-reservations.json").unlink()
    if damage == "turns": (prepared[1].squad_dir / "discovery-turns.json").unlink()
    if damage == "operation":
        state = prepared[1].load()
        del state[KEY]
        (prepared[1].squad_dir / "state.json").write_text(json.dumps(state))
    assert execute(prepared, executor).status == "blocked"
    assert execute(prepared, executor, create=True).status == "blocked"
    assert len(executor.calls) == 3


@pytest.mark.parametrize("after", [False, True])
def test_completion_state_interruption_replays_without_new_calls(prepared, monkeypatch, after):
    state = prepared[1]
    actual = state.advance_discovery_operation
    def crash(binding, event, **kwargs):
        if event == "finish" and not after: raise Interrupted()
        updated = actual(binding, event, **kwargs)
        if event == "finish": raise Interrupted()
        return updated
    executor = DiscoveryExecutor()
    with monkeypatch.context() as patch:
        patch.setattr(state, "advance_discovery_operation", crash)
        with pytest.raises(Interrupted): execute(prepared, executor, create=True)
    assert len(executor.calls) == 3
    resumed = execute(prepared, executor)
    assert resumed.status == "reviewed", resumed.reason
    assert resumed.token_usage == 21 and len(executor.calls) == 3


def test_reservation_handoff_interruption_reuses_saved_mapping(prepared, monkeypatch):
    from harness.discovery_reservations import DiscoveryReservationJournal
    actual = DiscoveryReservationJournal.bind
    def crash(journal, *args):
        actual(journal, *args)
        raise Interrupted()
    executor = DiscoveryExecutor()
    with monkeypatch.context() as patch:
        patch.setattr(DiscoveryReservationJournal, "bind", crash)
        with pytest.raises(Interrupted): execute(prepared, executor, create=True)
    assert len(executor.calls) == 1
    resumed = execute(prepared, executor)
    assert resumed.status == "reviewed", resumed.reason
    assert resumed.token_usage == 21 and len(executor.calls) == 3


def test_source_drift_during_final_check_never_finishes_attempt(prepared):
    class DriftingExecutor(DiscoveryExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            if self.calls[-1]["assignment"]["step"] == "review":
                (prepared[0] / "inputs/task.md").write_text("Drifted evidence")
            return result
    result = execute(prepared, DriftingExecutor(), create=True)
    assert result.status == "blocked"
    assert prepared[1].load()[KEY]["attempts"][-1]["result"] is None
    assert list((prepared[0] / "specs/game").iterdir()) == []


@pytest.mark.parametrize("change", ["labels", "spacing"])
def test_label_or_format_churn_does_not_count_as_repair_progress(prepared, change):
    class ChurningExecutor(DiscoveryExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            reply = json.loads(result.stdout)
            if reply["step"] == "author":
                content = "### U-000002: Wrong allocation\nUnchanged meaning.\n"
                if reply["dispatch_id"] != "attempt-1-author":
                    content = content.replace("U-000002", "U-000003") if change == "labels" else content.replace("\n", "\n\n")
                reply["artifacts"]["unknowns.md"] = content
            return replace(result, stdout=json.dumps(reply))
    executor = ChurningExecutor()
    result = execute(prepared, executor, create=True)
    assert result.status == "blocked" and result.reason == "discovery_no_progress"
    assert len(executor.calls) == 4
    assert len(prepared[1].load()[KEY]["attempts"]) == 2


def seed_accepted_question(case):
    """Real guarded fixture publication; not production completion integration."""
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_publication import PublicationIntentRequest, PublicationOperation, PublicationSourceClaim
    from harness.element_identity_request_codec import encode_request
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_baseline_codec import encode_initial_publication_sources
    root, state, store, _ = case
    label, = store.reserve(spec_id="game", kind="U", operation_id="seed-reserve", count=1)
    assert label == "U-000001"
    content = "### U-000001: Camera choice\r\nOriginal camera question.\r\n"
    transaction = SquadPublicationTransaction.begin(root, state.squad_dir, "7" * 32)
    target = Path("specs/game/unknowns.md")
    stage = transaction.build_path("unknowns.md")
    stage.write_bytes(content.encode("utf-8"))
    transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    operations = (PublicationOperation("lifecycle", "seed-create", encode_request("lifecycle", (
        ElementCreate(label, "Isometric projection choice", content, "seed-reserve"),))),)
    observed = store.check_managed_context(spec_id="game", run_id="first", record=state.load()["managed_identity"])
    source = observed["source_context"]
    with prepared.inspect_sources(tree_paths=("specs/game",), file_paths=()) as initial:
        request = PublicationIntentRequest(prepared.marker.manifest_sha256, "fixture seed", operations,
            PublicationSourceClaim(source["context_id"], source["operation_id"], encode_initial_publication_sources(initial)))
    prepared.publish_sources(initial,
        before_publish=lambda _: store.prepare_identity_publication(spec_id="game", operation_id="seed-publish", request=request),
        after_publish=lambda _: store.apply_identity_publication(spec_id="game", operation_id="seed-publish"))
    store.release_identity_publication(spec_id="game", operation_id="seed-publish", completion_payload="fixture accepted")
    return content


@pytest.mark.parametrize("swap_subject", [False, True])
def test_same_subject_repair_preserves_accepted_revision_and_rejects_reassignment(prepared, swap_subject):
    original = seed_accepted_question(prepared)
    history = prepared[2].identity_history(spec_id="game")
    class RepairExecutor(ScriptedExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            payload = self.calls[-1]
            selected, context = payload["assignment"], payload["context"]
            if selected["step"] == "propose":
                fields = dict(new_subjects=[], revisions=[dict(id="U-000001", expected_revision="1")])
            elif selected["step"] == "author":
                assert context["reservations"] == []
                content = original.replace("Original camera question.", "Clarified isometric camera question.")
                if swap_subject: content = content.replace("Camera choice", "Network latency")
                fields = dict(artifacts={"unknowns.md": content})
            else:
                fields = dict(verdict="accept", reason="Same camera subject", assessments=[dict(
                    id="U-000001", verdict="accept", reason="Clarification only", evidence=[context["citations"]["U-000001"]])])
            return replace(result, stdout=json.dumps({**selected, "action": "final", **fields}))
    executor = RepairExecutor()
    result = execute(prepared, executor, create=True, artifact_paths=("unknowns.md",), unowned_writable_paths=(),
        editable_revisions=(("U-000001", "1"),), intent=dict(kind="repair", request="Clarify camera question",
            origin="review:original-camera-finding", findings=[dict(id="camera-meaning", reason="Camera direction unclear")]))
    assert result.status == ("blocked" if swap_subject else "reviewed"), result.reason
    if not swap_subject:
        rows = json.loads(result.candidate.history.payload)
        assert rows["entities"][0]["revision"] == "2"
        assert rows["entities"][0]["subject"] == "Isometric projection choice"
        assert len(rows["revisions"]) == 2
    else:
        assert not any(call["assignment"]["step"] == "review" for call in executor.calls)
    assert (prepared[0] / "specs/game/unknowns.md").read_bytes() == original.encode("utf-8")
    assert prepared[2].identity_history(spec_id="game") == history


def test_templates_are_supplied_to_author_and_bound_across_replay(prepared):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    author = executor.calls[1]["context"]
    assert "templates" in author
    assert set(author["templates"]) == {"unknowns.md", "assumptions.md"}
    original = (prepared[0] / ".echelon/runtime/templates/unknowns-template.md").read_text()
    assert author["templates"]["unknowns.md"] == original
    (prepared[0] / ".echelon/runtime/templates/unknowns-template.md").write_text(original + "\nChanged template\n")
    assert execute(prepared, executor).status == "blocked"
    assert len(executor.calls) == 3


def test_missing_template_blocks_before_attempt_or_model(prepared):
    (prepared[0] / ".echelon/runtime/templates/unknowns-template.md").unlink()
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "blocked"
    assert not executor.calls
    assert KEY not in prepared[1].load()


@pytest.mark.parametrize("damage", ["reservation", "source", "template"])
def test_early_reconciliation_retains_known_provider_accounting(prepared, damage):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).token_usage == 21
    if damage == "reservation": (prepared[1].squad_dir / "discovery-reservations.json").unlink()
    if damage == "source": (prepared[0] / "inputs/task.md").write_text("Changed request")
    if damage == "template": (prepared[0] / ".echelon/runtime/templates/unknowns-template.md").unlink()
    journal = prepared[1].squad_dir / "discovery-turns.json"
    retained = journal.read_bytes()
    blocked = execute(prepared, executor)
    assert blocked.status == "blocked"
    assert blocked.token_usage == 21 and blocked.dispatch_count == 3
    assert journal.read_bytes() == retained and len(executor.calls) == 3


def test_attempts_use_detached_selected_intent_not_mutable_caller_input(prepared):
    intent = dict(kind="create", request="ORIGINAL", origin={"report": "original-report"})
    class MutatingExecutor(DiscoveryExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            if self.calls[-1]["assignment"]["step"] == "review":
                intent["request"] = "MUTATED AFTER BINDING"
                intent["origin"]["report"] = "changed-report"
            return result
    executor = MutatingExecutor(reject=1)
    reviewed = execute(prepared, executor, create=True, intent=intent)
    assert reviewed.status == "reviewed", reviewed.reason
    for call in executor.calls:
        assert call["context"]["intent"] == dict(kind="create", request="ORIGINAL", origin={"report": "original-report"})
    assert prepared[1].load()[KEY]["binding"]["intent"]["request"] == "ORIGINAL"


@pytest.mark.parametrize("boundary", ["reservation_selection", "provider_selection"])
def test_selected_missing_initial_journal_requires_reconciliation(prepared, monkeypatch, boundary):
    from harness.discovery_reservations import DiscoveryReservationJournal
    import harness.discovery_operation as operation
    def crash(*args, **kwargs): raise Interrupted()
    executor = DiscoveryExecutor()
    with monkeypatch.context() as patch:
        if boundary == "reservation_selection": patch.setattr(DiscoveryReservationJournal, "select", crash)
        else: patch.setattr(operation, "run_discovery_step", crash)
        with pytest.raises(Interrupted): execute(prepared, executor, create=True)
    assert KEY in prepared[1].load() and not executor.calls
    assert execute(prepared, executor).status == "blocked"
    assert execute(prepared, executor, create=True).status == "blocked"
    assert not executor.calls


def test_fresh_question_and_assumption_use_separate_reserved_families(prepared):
    class BothExecutor(DiscoveryExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            result = super().run_inspection_turn(*args, **kwargs)
            reply = json.loads(result.stdout)
            if reply["step"] == "propose":
                reply["new_subjects"].append(dict(key="webgl", kind="A", subject="WebGL availability", caption="Browser support"))
            if reply["step"] == "author":
                rows = self.calls[-1]["context"]["reservations"]
                assert {row["key"]: row["element_id"] for row in rows} == {"camera": "U-000001", "webgl": "A-000001"}
                reply["artifacts"]["assumptions.md"] = "### A-000001: Browser support\nWebGL can render the scene for U-000001.\n"
            return replace(result, stdout=json.dumps(reply))
    executor = BothExecutor()
    result = execute(prepared, executor, create=True)
    assert result.status == "reviewed", result.reason
    assert {row["id"] for row in result.candidate.review["assessments"]} == {"U-000001", "A-000001"}
    assert len(executor.calls) == 3
    assert execute(prepared, executor) == result
