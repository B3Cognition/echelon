"""Normal managed synthesis; only model and Prosaic processes are scripted."""
from dataclasses import replace
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from tests.unit.test_discovery_normal_entry import (
    case, enrolled, turn_prepared, prepared, FullDiscoveryExecutor, controller, selection,
)
from tests.unit.test_discovery_turns import ScriptedExecutor, Interrupted
from tests.unit.test_discovery_checkpoint import checkpoint_case


class SynthesisExecutor(FullDiscoveryExecutor):
    def run_inspection_turn(self, *args, **kwargs):
        assignment = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])["assignment"]
        if assignment.get("producer") != "synthesizer":
            return super().run_inspection_turn(*args, **kwargs)
        response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
        payload = self.calls[-1]
        assigned = payload["assignment"]
        context = payload["context"]
        if assigned["step"] == "propose":
            fields = dict(new_subjects=[], revisions=[dict(id="U-000001", expected_revision="1")])
        elif assigned["step"] == "author":
            artifacts = {name: context["baseline"].get(name, "# Synthesis\n") for name in assigned["artifact_paths"]}
            artifacts["unknowns.md"] += "\nCamera controls need evidence from the initial scene.\n"
            artifacts["contradictions-and-gaps.md"] = "# Gaps\nSee U-000001 for the camera decision.\n"
            artifacts["risks.md"] = "# Risks\nCamera uncertainty is tracked by U-000001.\n"
            fields = dict(artifacts=artifacts)
        else:
            fields = dict(verdict="accept", reason="Synthesis preserves meaning and references.",
                assessments=[dict(id=label, verdict="accept", reason="Same camera question.",
                    evidence=[context["citations"][label]]) for label in assigned["assigned_ids"]])
        return replace(response, stdout=json.dumps({**assigned, "action": "final", **fields}))


def install_synthesis(prepared):
    repo = Path(__file__).resolve().parents[2]
    for name in ("contradictions-and-gaps", "risks"):
        relative = f"templates/{name}-template.md"
        (prepared[0] / ".echelon/runtime" / relative).write_bytes((repo / "runtime" / relative).read_bytes())
    role = "subagents/echelon.synthesis-producer.md"
    (prepared[0] / ".echelon/prosaic" / role).write_bytes((repo / "prosaic" / role).read_bytes())


@pytest.mark.parametrize("checkpoint", [False, True])
@pytest.mark.parametrize("provider,mode", [("codex", "guided"), ("codex", "semi"), ("codex", "banzai"),
    ("claude", "guided"), ("claude", "semi"), ("claude", "banzai")])
def test_normal_entry_publishes_synthesis_without_replacing_discovery(prepared, checkpoint_case, checkpoint, provider, mode):
    state = prepared[1].load()
    state["autonomy_mode"] = mode
    if not checkpoint:
        for key in ("spec_dir", "checkpoint_policy_version", "phase_completion_outcomes"):
            state.pop(key)
    prepared[1].save(state)
    install_synthesis(prepared)
    executor = SynthesisExecutor(provider)
    ctrl = controller(prepared, executor)
    first = ctrl.run(managed_discovery=selection(prepared), create_managed_discovery=True)
    assert first.phase == "phase1-synthesizer"
    root, store, identity, _ = prepared
    original = store.load()
    ledger_path = root / "specs/game/.echelon/checkpoints.json"
    prior_ledger = json.loads(ledger_path.read_text()) if checkpoint else None
    old_receipts = {name: (store.squad_dir / name).read_bytes()
        for name in ("discovery-turns.json", "discovery-reservations.json")}
    request = {**selection(prepared), "through_phase": "phase1-synthesizer"}
    result = controller(prepared, executor).run(managed_discovery=request)
    assert result.phase == "phase1-modeler", (result, executor.calls[-1]["context"].get("feedback"))
    assert result.summary == "managed_phase_not_supported"
    saved = store.load()
    assert saved["last_dispatch"]["post_dispatch_complete"] is True
    assert saved["token_usage"] == 42
    assert "U-000001" in (root / "specs/game/risks.md").read_text()
    for key in ("managed_discovery_bootstrap", "managed_discovery_operation", "managed_discovery_turns"):
        assert saved[key] == original[key]
    assert {name: (store.squad_dir / name).read_bytes() for name in old_receipts} == old_receipts
    entities = json.loads(identity.identity_history(spec_id="game").payload)["entities"]
    assert [(row["element_id"], row["revision"]) for row in entities] == [("U-000001", "2")]
    assert len(executor.calls) == 6
    if checkpoint:
        ledger = json.loads(ledger_path.read_text())
        assert ledger["checkpoints"][:-1] == prior_ledger["checkpoints"]
        assert len(ledger["checkpoints"]) == 2
        assert ledger["checkpoints"][-1]["phase"] == "phase1-synthesizer"
    assert controller(prepared, executor).run(managed_discovery=request).phase == "phase1-modeler"
    assert store.load() == saved and len(executor.calls) == 6


@pytest.fixture
def accepted(checkpoint_case):
    install_synthesis(checkpoint_case)
    executor = SynthesisExecutor()
    assert controller(checkpoint_case, executor).run(managed_discovery=selection(checkpoint_case),
        create_managed_discovery=True).phase == "phase1-synthesizer"
    return checkpoint_case, executor, {**selection(checkpoint_case), "through_phase": "phase1-synthesizer"}


@pytest.mark.parametrize("damage", ["remove", "rename", "reject", "context", "graph", "ledger", "budget"])
def test_invalid_synthesis_does_not_change_accepted_artifacts_or_history(accepted, damage):
    case, executor, request = accepted
    root, store, identity, _ = case
    if damage == "context": (store.squad_dir / "context/current-feature-context.md").write_text("Foreign U-000001")
    if damage == "graph": (root / "specs/game/spec-artifact-graph.json").write_text("{}")
    if damage == "ledger": (root / "specs/game/.echelon/checkpoints.json").write_text("{}")
    if damage == "budget":
        for _ in range(5): store.increment_phase_dispatch_count("phase1-synthesizer")
    files = {path: path.read_bytes() for path in (root / "specs/game").rglob("*") if path.is_file()}
    history = identity.identity_history(spec_id="game")
    original = executor.run_inspection_turn
    def damaged(*args, **kwargs):
        response = original(*args, **kwargs)
        reply = json.loads(response.stdout)
        if reply.get("producer") == "synthesizer" and reply["step"] == "author":
            if damage == "remove": reply["artifacts"]["unknowns.md"] = "# Unknowns\nMerged away.\n"
            if damage == "rename": reply["artifacts"]["unknowns.md"] = reply["artifacts"]["unknowns.md"].replace("Camera choice", "Combat rules")
        if damage == "reject" and reply["step"] == "review":
            reply.update(verdict="reject", reason="Meaning changed.")
        return replace(response, stdout=json.dumps(reply))
    executor.run_inspection_turn = damaged
    result = controller(case, executor).run(managed_discovery=request)
    assert result.status == "blocked" and result.phase == "phase1-synthesizer", result
    assert {path: path.read_bytes() for path in (root / "specs/game").rglob("*") if path.is_file()} == files
    assert identity.identity_history(spec_id="game") == history
    assert identity.pending_identity_publication(spec_id="game") is None
    calls = len(executor.calls)
    assert controller(case, executor).run(managed_discovery=request).status == "blocked"
    assert len(executor.calls) == calls
    if damage in {"context", "graph", "ledger", "budget"}: assert calls == 3


@pytest.mark.parametrize("point", ["accepted", "sealed", "routed", "context", "completed", "released", "cleanup"])
def test_synthesis_restart_preserves_charges_and_checkpoint_prefix(accepted, monkeypatch, point):
    from harness.element_identity_store import IdentityStore
    from harness.squad_publication import PreparedSquadPublication
    import harness.squad as squad
    case, executor, request = accepted
    ctrl = controller(case, executor)
    target, method = {
        "accepted": (case[1], "advance_discovery_operation"),
        "sealed": (ctrl, "_prepare_controller_completion"),
        "routed": (case[1], "advance"),
        "context": (squad, "install_or_verify_completion_context"),
        "completed": (case[1], "complete_controller_completion"),
        "released": (IdentityStore, "release_identity_publication"),
        "cleanup": (PreparedSquadPublication, "discard"),
    }[point]
    original = getattr(target, method)
    def interrupted(*args, **kwargs):
        value = original(*args, **kwargs)
        if point == "accepted" and args[1] != "finish": return value
        if point == "cleanup":
            current = case[1].load()
            if current["phase"] != "phase1-modeler" or not current["last_dispatch"]["post_dispatch_complete"]:
                return value
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(target, method, interrupted)
        with pytest.raises(Interrupted): ctrl.run(managed_discovery=request)
    result = controller(case, executor).run(managed_discovery=request)
    state = case[1].load()
    assert state["last_dispatch"]["post_dispatch_complete"] is True, result
    assert result.phase == "phase1-modeler" and state["token_usage"] == 42
    assert len(executor.calls) == 6
    ledger = json.loads((case[0] / "specs/game/.echelon/checkpoints.json").read_bytes())
    assert [row["phase"] for row in ledger["checkpoints"]] == ["phase1-discover", "phase1-synthesizer"]


@pytest.mark.parametrize("point", ["before_checkpoint", "after_commit", "after_ledger", "before_receipt", "after_receipt"])
def test_second_checkpoint_restart_appends_once(accepted, monkeypatch, point):
    from harness import squad, phase_checkpoints
    case, executor, request = accepted
    with monkeypatch.context() as patch:
        if point in {"before_checkpoint", "after_commit", "after_ledger"}:
            original = phase_checkpoints.create_or_recover_completion_checkpoint
            def checkpoint(*args, **kwargs):
                if point == "before_checkpoint": raise Interrupted()
                def fault(observed):
                    if observed == point: raise Interrupted()
                kwargs["fault_hook"] = fault
                return original(*args, **kwargs)
            patch.setattr(phase_checkpoints, "create_or_recover_completion_checkpoint", checkpoint)
        else:
            original = squad.persist_completion_effect_receipt
            def persist(completion, effect, receipt):
                if effect == "checkpoint" and point == "before_receipt": raise Interrupted()
                value = original(completion, effect, receipt)
                if effect == "checkpoint" and point == "after_receipt": raise Interrupted()
                return value
            patch.setattr(squad, "persist_completion_effect_receipt", persist)
        with pytest.raises(Interrupted): controller(case, executor).run(managed_discovery=request)
    result = controller(case, executor).run(managed_discovery=request)
    assert result.phase == "phase1-modeler" and case[1].load()["last_dispatch"]["post_dispatch_complete"], result
    assert len(executor.calls) == 6 and case[1].load()["token_usage"] == 42
    ledger = json.loads((case[0] / "specs/game/.echelon/checkpoints.json").read_bytes())
    assert [row["phase"] for row in ledger["checkpoints"]] == ["phase1-discover", "phase1-synthesizer"]
    commits = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=case[0], check=True,
        capture_output=True, text=True).stdout.strip()
    assert commits == "3"


def test_fresh_run_can_select_synthesis_without_a_second_invocation(checkpoint_case):
    install_synthesis(checkpoint_case)
    executor = SynthesisExecutor()
    result = controller(checkpoint_case, executor).run(managed_discovery={**selection(checkpoint_case),
        "through_phase": "phase1-synthesizer"}, create_managed_discovery=True)
    assert result.phase == "phase1-modeler", result
    assert len(executor.calls) == 6
    assert checkpoint_case[1].load()["phase_dispatch_counts"] == {"phase1-discover": 1, "phase1-synthesizer": 1}


def test_missing_prior_ledger_blocks_before_checkpoint_writer(accepted, monkeypatch):
    from harness import phase_checkpoints
    case, executor, request = accepted
    def interrupt(*args, **kwargs):
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(phase_checkpoints, "create_or_recover_completion_checkpoint", interrupt)
        with pytest.raises(Interrupted): controller(case, executor).run(managed_discovery=request)
    def head():
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=case[0], check=True,
            capture_output=True, text=True).stdout
    before = head()
    ledger = case[0] / "specs/game/.echelon/checkpoints.json"
    ledger.unlink()
    result = controller(case, executor).run(managed_discovery=request)
    assert result.status == "blocked"
    assert head() == before
    assert not ledger.exists()
    assert len(executor.calls) == 6


def test_synthesis_state_cannot_be_injected_replaced_or_deleted(accepted):
    from harness.squad_state import StateAdvanceError
    case, executor, request = accepted
    store = case[1]
    before = store.load()
    before.update(status="running", blocked_reason=None)
    store.save(before)
    before = store.load()
    source = {key: before["last_dispatch"][key] for key in ("dispatch_id", "completion_intent_sha256",
        "completion_receipts_sha256", "completed_publication_binding_sha256")}
    injected = {**before, "managed_synthesizer_source": source}
    with pytest.raises(StateAdvanceError): store.save(injected)
    assert store.load() == before
    foreign = {**source, "completion_receipts_sha256": "a" * 64}
    with pytest.raises(StateAdvanceError): store.prepare_synthesizer(foreign)
    assert store.load() == before
    assert controller(case, executor).run(managed_discovery=request).phase == "phase1-modeler"
    saved = store.load()
    for key in ("managed_synthesizer_source", "managed_synthesizer_operation", "managed_synthesizer_turns"):
        removed = deepcopy(saved)
        del removed[key]
        with pytest.raises(StateAdvanceError): store.save(removed)
        changed = deepcopy(saved)
        if key.endswith("source"): changed[key]["completion_receipts_sha256"] = "a" * 64
        elif key.endswith("operation"): changed[key]["binding"]["fingerprint"] = "a" * 64
        else: changed[key]["binding_sha256"] = "a" * 64
        with pytest.raises(StateAdvanceError): store.save(changed)
        assert store.load() == saved


@pytest.mark.parametrize("receipt", ["synthesizer-turns.json", "synthesizer-reservations.json"])
def test_lost_synthesis_receipt_cannot_repeat_calls_or_publish(accepted, monkeypatch, receipt):
    from harness.discovery_turns import read_discovery_usage
    case, executor, request = accepted
    store = case[1]
    original = store.advance_discovery_operation
    def interrupt(*args, **kwargs):
        value = original(*args, **kwargs)
        if args[1] == "finish": raise Interrupted()
        return value
    with monkeypatch.context() as patch:
        patch.setattr(store, "advance_discovery_operation", interrupt)
        with pytest.raises(Interrupted): controller(case, executor).run(managed_discovery=request)
    assert read_discovery_usage(store, "synthesizer") == dict(token_usage=21, dispatch_count=3)
    # Outer usage is charged by the completion transition, not operation review.
    assert store.load()["token_usage"] == 21
    path = store.squad_dir / receipt
    path.unlink()
    files = {path: path.read_bytes() for path in (case[0] / "specs/game").rglob("*") if path.is_file()}
    history = case[2].identity_history(spec_id="game")
    result = controller(case, executor).run(managed_discovery=request)
    assert result.status == "blocked" and result.phase == "phase1-synthesizer", result
    assert len(executor.calls) == 6 and store.load()["token_usage"] == 21
    assert read_discovery_usage(store, "synthesizer") == (
        dict(token_usage=None, dispatch_count=0) if receipt == "synthesizer-turns.json"
        else dict(token_usage=21, dispatch_count=3))
    assert store.load()["phase_dispatch_counts"]["phase1-synthesizer"] == 1
    assert case[2].identity_history(spec_id="game") == history
    assert {path: path.read_bytes() for path in (case[0] / "specs/game").rglob("*") if path.is_file()} == files
    assert not path.exists()
    assert controller(case, executor).run(managed_discovery=request).status == "blocked"
    assert len(executor.calls) == 6


def test_synthesis_reserves_new_subject_without_renumbering_discovery(accepted):
    case, executor, request = accepted
    original = executor.run_inspection_turn
    def with_new_subject(*args, **kwargs):
        response = original(*args, **kwargs)
        reply = json.loads(response.stdout)
        if reply["step"] == "propose":
            reply["new_subjects"] = [dict(key="movement", kind="U", subject="Movement input choice", caption="Movement controls")]
        elif reply["step"] == "author":
            mappings = executor.calls[-1]["context"]["reservations"]
            assert [(row["key"], row["element_id"]) for row in mappings] == [("movement", "U-000002")]
            reply["artifacts"]["unknowns.md"] += "\n### U-000002: Movement controls\nWhich input moves the player?\n"
        return replace(response, stdout=json.dumps(reply))
    executor.run_inspection_turn = with_new_subject
    result = controller(case, executor).run(managed_discovery=request)
    assert result.phase == "phase1-modeler", result
    entities = json.loads(case[2].identity_history(spec_id="game").payload)["entities"]
    assert [(row["element_id"], row["subject"], row["revision"]) for row in entities] == [
        ("U-000001", "Isometric projection choice", "2"), ("U-000002", "Movement input choice", "1")]
    saved = case[1].load()
    assert controller(case, executor).run(managed_discovery=request).phase == "phase1-modeler"
    assert case[1].load() == saved and len(executor.calls) == 6


@pytest.mark.parametrize("boundary", ["reply", "accepted"])
def test_synthesis_provider_restart_never_repeats_a_saved_dispatch(accepted, monkeypatch, boundary):
    from harness.discovery_receipts import DiscoveryReceiptFile
    case, executor, request = accepted
    original = DiscoveryReceiptFile._write
    def interrupt(file, raw):
        original(file, raw)
        if file.name != "synthesizer-turns": return
        steps = json.loads(raw)["payload"]["steps"]
        records = steps[-1]["records"] if steps else []
        if records and records[-1]["reply"] is not None and (
                boundary == "reply" or records[-1]["accepted"]):
            raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(DiscoveryReceiptFile, "_write", interrupt)
        with pytest.raises(Interrupted): controller(case, executor).run(managed_discovery=request)
    assert len(executor.calls) == 4
    result = controller(case, executor).run(managed_discovery=request)
    if boundary == "accepted":
        assert result.phase == "phase1-modeler", result
        assert len(executor.calls) == 6 and case[1].load()["token_usage"] == 42
    else:
        assert result.status == "blocked" and result.phase == "phase1-synthesizer", result
        assert len(executor.calls) == 4
        assert not (case[0] / "specs/game/risks.md").exists()
        assert case[2].pending_identity_publication(spec_id="game") is None
