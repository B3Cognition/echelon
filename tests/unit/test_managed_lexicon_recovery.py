"""An exhausted real gate retains one completion across repeated crashes."""
import json

import pytest
import yaml

from harness.element_identity_store import IdentityStore
from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
from harness.squad import SquadController
from harness.squad_publication import PreparedSquadPublication
from tests.unit.test_discovery_completion import drain
from tests.unit.test_discovery_turns import Interrupted
from tests.unit.test_managed_lexicon_gate import (
    case, enrolled, turn_prepared, prepared, checkpoint_case,
    controller, selection, install_lexicon, LexiconExecutor, assert_retained_gate,
)


def continue_exhausted_gate_faults(case, executor):
    root, store, identity, _ = case
    before = store.load()
    assert before["phase"] == "phase1-lexicon"
    history = identity.identity_history(spec_id="game")
    calls = len(executor.calls)
    source = (root / "specs/game/spec.md").read_bytes()
    selected = {**selection(case), "through_phase": "phase1-lexicon"}
    boundaries = (
        (IdentityStore, "prepare_identity_publication"),
        (PreparedSquadPublication, "_promote"),
        (IdentityStore, "apply_identity_publication"),
        (type(store), "handoff_external_publication"),
        (SquadController, "_apply_controller_completion_effect"),
        (type(store), "complete_controller_completion"),
        (IdentityStore, "release_identity_publication"),
        (PreparedSquadPublication, "discard"),
    )
    completion_id = None
    report = None
    for owner, name in boundaries:
        for when in ("before", "after"):
            original = getattr(owner, name)
            label = f"{when}:{name}"

            def interrupt(*args, **kwargs):
                if when == "after":
                    original(*args, **kwargs)
                raise Interrupted(label)

            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(owner, name, interrupt)
                with pytest.raises(Interrupted, match=label):
                    ctrl = controller(case, executor)
                    if completion_id is None:
                        ctrl.run(managed_discovery=selected)
                    else:
                        drain(ctrl)
            state = store.load()
            marker = state.get("pending_controller_completion")
            current = marker["completion_id"] if marker else state["last_dispatch"]["dispatch_id"]
            if completion_id is None:
                completion_id = current
            assert current == completion_id, label
            assert state["lexicon_attempts"] == 1, label
            assert state["phase"] == "terminal-blocked", label
            assert state["token_usage"] == before["token_usage"], label
            assert len(executor.calls) == calls, label
            assert identity.identity_history(spec_id="game") == history, label
            assert (root / "specs/game/spec.md").read_bytes() == source, label
            path = root / "specs/game/spec-lexicon-report.json"
            if report is not None:
                assert path.read_bytes() == report, label
            elif path.exists():
                report = path.read_bytes()

    # The last interruption is after stage deletion: recover from the retained
    # release, not a new gate evaluation or a replacement publication.
    controller(case, executor).run(managed_discovery=selected)
    state = store.load()
    assert "pending_controller_completion" not in state
    assert "pending_external_publication" not in state
    assert state["last_dispatch"]["dispatch_id"] == completion_id
    assert state["last_dispatch"]["post_dispatch_complete"] is True
    assert state["phase"] == "terminal-blocked" and state["lexicon_attempts"] == 1
    assert state["lexicon_pass"] is False
    assert (root / "specs/game/spec-lexicon-report.json").read_bytes() == report
    assert json.loads(report)["ok"] is False
    row = identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + completion_id)
    assert row["state"] == "released"
    assert identity.pending_identity_publication(spec_id="game") is None
    assert_retained_gate(root, store, identity)
    controller(case, executor).run(managed_discovery=selected)
    assert store.load() == state and len(executor.calls) == calls
    assert identity.identity_history(spec_id="game") == history


def test_managed_exhausted_gate_recovers_each_completion_boundary_once(checkpoint_case):
    root, store, _, _ = checkpoint_case
    install_lexicon(checkpoint_case)
    path = root / ".echelon/config.yml"
    config = yaml.safe_load(path.read_text())
    config["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.setdefault("lexicon_gate", {})["max_repair_attempts"] = 1
    path.write_text(yaml.safe_dump(config))
    executor = LexiconExecutor("codex")
    result = controller(checkpoint_case, executor).run(
        managed_discovery={**selection(checkpoint_case), "through_phase": "phase1-lexicon-derive"},
        create_managed_discovery=True)
    assert result.phase == "phase1-lexicon", result
    assert len(executor.calls) == 24 and store.load()["token_usage"] == 168
    continue_exhausted_gate_faults(checkpoint_case, executor)
