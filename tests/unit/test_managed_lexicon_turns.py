"""Script only the provider; retain real read, receipt, budget and state owners."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from harness.discovery_semantics import DiscoveryAssignment
from harness.discovery_turns import read_discovery_usage
from tests.unit.test_discovery_turns import case, enrolled, prepared, ScriptedExecutor, Interrupted, fingerprint, run
from tests.unit.test_managed_lexicon_rounds import select_parent, binding
from tests.unit.test_why1_tracker_parent import source


@pytest.fixture
def lexicon_prepared(prepared):
    root, store, _, _ = prepared
    # Missing roles produce a normal blocked result during the red test, not a
    # fixture error. Production admission/publication are tested separately.
    repo = Path(__file__).resolve().parents[2]
    for role in ("producer", "reviewer"):
        name = "echelon.lexicon-" + role + ".md"
        path = repo / "prosaic/subagents" / name
        if path.exists():
            (root / ".echelon/prosaic/subagents" / name).write_bytes(path.read_bytes())
    before = select_parent(store)
    store.prepare_spec_round("lexicon", source("a"), expected_state=before)
    store.advance_discovery_operation(binding(), "prepare", producer="lexicon")
    return prepared


def assignment(case, step="propose"):
    return DiscoveryAssignment("lexicon-" + "a" * 32, "attempt-1-" + step,
        "game", "first", step, fingerprint(case), ("requirements.lexicon.md",), producer="lexicon",
        routing=(("verdict", "DONE"), ("state_updates", {})) if step == "review" else None)


def test_lexicon_empty_proposal_retains_receipt_without_allocating(lexicon_prepared):
    from harness.discovery_reservations import DiscoveryReservationJournal
    from tests.unit.test_discovery_reservations import database_rows
    root, store, identity, _ = lexicon_prepared
    selected = assignment(lexicon_prepared)
    proposal = {**selected.identity(), "action": "final", "new_subjects": [], "revisions": []}
    before = database_rows(root)
    for create in (True, False):
        with DiscoveryReservationJournal(store.squad_dir, producer="lexicon",
                round_operation_id=selected.operation_id) as journal:
            journal.select(identity, spec_id="game", run_id="first", operation_id=selected.operation_id,
                managed_identity=store.load()["managed_identity"], create=create)
            assert journal.bind(selected, proposal, replay_only=not create) == ()
    assert database_rows(root) == before


class LexiconExecutor(ScriptedExecutor):
    def run_inspection_turn(self, *args, **kwargs):
        response = super().run_inspection_turn(*args, **kwargs)
        payload = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])
        selected = payload["assignment"]
        if selected["step"] != "author" or self.failure or (self.read and not payload["reads"]):
            return response
        return replace(response, stdout=json.dumps({**selected, "action": "final",
            "artifacts": {"requirements.lexicon.md": "Uncertified translation.\n"},
            "routing": dict(verdict="DONE", state_updates={})}))


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_lexicon_turns_replay_with_exact_budget_and_no_canonical_writes(lexicon_prepared, provider):
    root, store, identity, _ = lexicon_prepared
    history = identity.identity_history(spec_id="game")
    executor = LexiconExecutor(provider, read=True)
    for step, tokens in (("propose", 14), ("author", 28), ("review", 42)):
        result = run(lexicon_prepared, executor, selected=assignment(lexicon_prepared, step), create=step == "propose")
        assert result.reply is not None, result
        assert result.token_usage == tokens and result.dispatch_count == tokens // 7
        assert run(lexicon_prepared, executor, selected=assignment(lexicon_prepared, step)) == result
    assert len(executor.calls) == 6
    assert read_discovery_usage(store, "lexicon") == dict(token_usage=42, dispatch_count=6)
    assert list((root / "specs/game").iterdir()) == []
    assert identity.identity_history(spec_id="game") == history
    assert store.load()["phase_dispatch_counts"]["phase1-lexicon-derive"] == 1


@pytest.mark.parametrize("damage", ["provider", "input", "role", "receipt"])
def test_lexicon_turns_cannot_rebind_completed_work(lexicon_prepared, damage):
    root, store, _, _ = lexicon_prepared
    executor = LexiconExecutor()
    selected = assignment(lexicon_prepared)
    assert run(lexicon_prepared, executor, selected=selected, create=True).reply is not None
    if damage == "provider": executor.provider_id = "claude"
    elif damage == "input": (root / "inputs/task.md").write_text("Changed task\n")
    elif damage == "role":
        path = root / ".echelon/prosaic/subagents/echelon.lexicon-reviewer.md"
        path.write_text(path.read_text() + "\nDifferent role.\n")
    else:
        path = store.squad_dir / ("lexicon-turns-lexicon-" + "a" * 32 + ".json")
        path.write_text("{")
    result = run(lexicon_prepared, executor, selected=selected)
    assert result.reply is None and len(executor.calls) == 1
    assert result.token_usage == (None if damage == "receipt" else 7)


def test_lexicon_host_reads_cannot_expose_run_control_files(lexicon_prepared):
    root, store, _, _ = lexicon_prepared
    class ReadControl(LexiconExecutor):
        def run_inspection_turn(self, *args, **kwargs):
            response = super().run_inspection_turn(*args, **kwargs)
            reply = json.loads(response.stdout)
            reply.update(action="read", request=dict(op="read_file", root="control", path="state.json",
                start_line=1, line_count=10))
            reply.pop("new_subjects", None)
            reply.pop("revisions", None)
            return replace(response, stdout=json.dumps(reply))
    executor = ReadControl()
    result = run(lexicon_prepared, executor, selected=assignment(lexicon_prepared), create=True,
        roots={"inputs": root / "inputs", "control": store.squad_dir})
    assert result.reply is None
    assert not executor.calls, "An unsafe root must be refused before provider execution"


@pytest.mark.parametrize("boundary", ["pending", "reply", "read", "final"])
@pytest.mark.parametrize("after", [False, True])
def test_lexicon_receipt_interruption_never_repeats_uncertain_calls(lexicon_prepared, monkeypatch, boundary, after):
    from harness.discovery_receipts import DiscoveryReceiptFile
    actual = DiscoveryReceiptFile._write
    executor = LexiconExecutor(read=boundary == "read")
    selected = assignment(lexicon_prepared)
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
        if hit and not after: raise Interrupted()
        actual(file, raw)
        if hit: raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(DiscoveryReceiptFile, "_write", crash)
        with pytest.raises(Interrupted):
            run(lexicon_prepared, executor, selected=selected, create=True)
    calls = len(executor.calls)
    result = run(lexicon_prepared, executor, selected=selected)
    resumable = (boundary == "pending" and not after) or (boundary in {"read", "final"} and after)
    assert (result.reply is not None) == resumable, result
    assert len(executor.calls) == calls + int(resumable and boundary != "final")
    if not resumable:
        assert run(lexicon_prepared, executor, selected=replace(selected, dispatch_id="another")).reply is None
        assert len(executor.calls) == calls
    assert lexicon_prepared[1].load()["phase_dispatch_counts"]["phase1-lexicon-derive"] == 1
