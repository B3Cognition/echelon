"""Real managed WHAT execution; only external provider turns are scripted."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from tests.unit.test_managed_constitution import (case, enrolled, turn_prepared, prepared, checkpoint_case,
    controller, selection, install_constitution, ConstitutionExecutor, ScriptedExecutor)
from tests.unit.test_managed_spec_contract import SPEC, routing


class WhatExecutor(ConstitutionExecutor):
    def run_inspection_turn(self, *args, **kwargs):
        assignment = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])["assignment"]
        if assignment.get("producer") != "what":
            return super().run_inspection_turn(*args, **kwargs)
        response = ScriptedExecutor.run_inspection_turn(self, *args, **kwargs)
        context = self.calls[-1]["context"]
        if assignment["step"] == "propose":
            fields = dict(new_subjects=[dict(key=kind.lower(), kind=kind, subject=kind + " subject", caption=caption)
                for kind, caption in (("FR", "Player movement"), ("NFR", "Browser operation"), ("AC", "Movement is visible"))], revisions=[])
        elif assignment["step"] == "author":
            fields = dict(artifacts={"spec.md": SPEC, "requirements-overview.md": "Visible player movement: FR-000001, AC-000001.\n"}, routing=routing())
        else:
            fields = dict(verdict="accept", reason="Requirements preserve captured movement intent and are testable.",
                assessments=[dict(id=label, verdict="accept", reason="Grounded in captured intent.",
                    evidence=[context["citations"][label]]) for label in assignment["assigned_ids"]])
        return replace(response, stdout=json.dumps({**assignment, "action": "final", **fields}))


def install_what(case):
    install_constitution(case)
    repo = Path(__file__).resolve().parents[2]
    for relative in ("subagents/echelon.what-producer.md", "subagents/echelon.what-reviewer.md",
            "agents/exploration/templates/cartographer-spec-template.md",
            "agents/exploration/templates/cartographer-overview-template.md"):
        destination = case[0] / ".echelon/prosaic" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((repo / "prosaic" / relative).read_bytes())


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_managed_what_publishes_requirements_and_preserves_restart(checkpoint_case, provider):
    root, store, identity, _ = checkpoint_case
    install_what(checkpoint_case)
    executor = WhatExecutor(provider)
    selected = {**selection(checkpoint_case), "through_phase": "phase1-what"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase == "phase1-understanding", result
    assert (root / "specs/game/spec.md").read_text() == SPEC
    saved, history = store.load(), identity.identity_history(spec_id="game")
    assert saved["spec_status"] == "planned"
    assert saved["token_usage"] == 126 and len(executor.calls) == 18
    entities = json.loads(history.payload)["entities"]
    assert {row["element_id"] for row in entities if row["kind"] in {"FR", "NFR", "AC"}} == {"FR-000001", "NFR-000001", "AC-000001"}
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == "phase1-understanding"
    assert store.load() == saved and identity.identity_history(spec_id="game") == history
    assert len(executor.calls) == 18
