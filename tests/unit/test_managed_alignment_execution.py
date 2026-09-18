"""Actual released strategy feeds reviewed alignment through existing owners."""
import json

import pytest

from tests.unit.test_managed_alignment import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, parent,
)
from tests.unit.test_managed_alignment import complete_strategy


class AlignmentExecutor:
    supports_inspection_turn = True
    constrained_execution_configuration_id = "inspection-v1"

    def __init__(self, provider, verdict="ALIGNED", *, routing=None):
        self.verdict = verdict
        self.routing = routing
        self.cli = self.provider_id = provider
        self.calls = []

    def run_inspection_turn(self, private, prompt, *, frontmatter, timeout_ms):
        from pathlib import Path
        from harness.ai_cli_backend import CliRunResult
        assert not list(Path(private).iterdir())
        assert set(frontmatter) == {"model_tier", "effort"} and 0 < timeout_ms <= 300000
        payload = json.loads(prompt.split("\nHOST_INPUT_JSON\n", 1)[1])
        self.calls.append(payload)
        assignment = payload["assignment"]
        assert assignment["producer"] == "alignment"
        if assignment["step"] == "propose":
            fields = dict(action="final", new_subjects=[], revisions=[])
        elif assignment["step"] == "author":
            fields = dict(action="final", artifacts={"intent-alignment-check.md": "# Intent Alignment Check\n## Metadata\nCompared accepted intent, feasibility and strategy.\n## Alignment Verdict\nMovement remains in scope.\n## Divergence Points\nLighting polish is deferred.\n## Required Action\nRetain the MVP movement scope.\n"},
                routing=self.routing if self.routing is not None else dict(verdict=self.verdict, state_updates={}))
        else:
            fields = dict(action="final", verdict="accept", reason="Risks fit the accepted feasibility scope", assessments=[])
        return CliRunResult(0, json.dumps({**assignment, **fields}), "", token_usage=7)


def assert_reviewed_alignment(case, provider, verdict="ALIGNED", *, routing=None):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_operation import run_discovery_operation
    from harness.discovery_producer import SOURCE_FIELDS, tracker_round
    from tests.unit.test_managed_checkpoint_assess import selection
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    documents = {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()}
    source = {key: before["last_dispatch"][key] for key in SOURCE_FIELDS}
    args = dict(input_tree=selection(case)["input_tree"], artifact_paths=("intent-alignment-check.md",),
        unowned_writable_paths=("intent-alignment-check.md",), intent=dict(kind="align", request="Compare accepted intent with feasibility and strategy"), producer="alignment")
    executor = AlignmentExecutor(provider, verdict, routing=routing)
    with PhaseAExecutionLock.acquire(root, "test-alignment"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-alignment"):
            parent(case)
            store.prepare_spec_round("alignment", source, expected_state=before)
            result = run_discovery_operation(root, store, executor, **args, create=True)
            assert result.status == "reviewed", result.reason
            assert result.dispatch_count == 3 and result.token_usage == 21
            assert result.candidate.operations == () and result.candidate.history == history
            assert json.loads(result.candidate.candidate_inputs)["routing"] == (routing if routing is not None else dict(verdict=verdict, state_updates={}))
            assert [call["assignment"]["step"] for call in executor.calls] == ["propose", "author", "review"]
            accepted = store.load()
            replay = run_discovery_operation(root, store, executor, **args, replay_only=True)
            assert replay.candidate == result.candidate and len(executor.calls) == 3
            assert store.load() == accepted
    row = tracker_round(accepted, producer="alignment")
    assert row["source"] == source and row["predecessor"] is None and row["resolution"] is None
    assert accepted["phase_dispatch_counts"]["phase2-tracker-alignment"] == 1
    assert accepted["iteration"] == before["iteration"]
    assert accepted["feasibility_structural_attempts"] == before["feasibility_structural_attempts"]
    assert identity.identity_history(spec_id="game") == history
    assert {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()} == documents
    assert not accepted["phase_dispatch_counts"].get("phase2-intent-alignment-structural")
    return result


@pytest.mark.parametrize("provider,mode,enabled,policy", [
    ("codex", "guided", False, "disabled"), ("claude", "banzai", True, "warn")])
def test_released_strategy_authorizes_reviewed_alignment(checkpoint_case, provider, mode, enabled, policy):
    complete_strategy(checkpoint_case, provider, mode, enabled, policy)
    assert_reviewed_alignment(checkpoint_case, provider, "ALIGNED" if provider == "codex" else "DRIFT")
