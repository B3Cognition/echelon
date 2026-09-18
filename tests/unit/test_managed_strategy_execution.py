"""Actual released gates feed reviewed strategy through the existing owners."""
import json

import pytest

from tests.unit.test_managed_strategy import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, parent,
)
from tests.unit.test_managed_feasibility_policy import test_first_gate_preserves_native_policy as complete_policy


class StrategyExecutor:
    supports_inspection_turn = True
    constrained_execution_configuration_id = "inspection-v1"

    def __init__(self, provider):
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
        assert assignment["producer"] == "strategy"
        if assignment["step"] == "propose":
            fields = dict(action="final", new_subjects=[], revisions=[])
        elif assignment["step"] == "author":
            fields = dict(action="final", artifacts={"strategic-overview.md": "# Strategic Overview\nPrioritize movement correctness and lighting performance.\n"},
                routing=dict(verdict="DONE", state_updates={}))
        else:
            fields = dict(action="final", verdict="accept", reason="Risks fit the accepted feasibility scope", assessments=[])
        return CliRunResult(0, json.dumps({**assignment, **fields}), "", token_usage=7)


def assert_reviewed_strategy(case, provider):
    from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
    from harness.discovery_operation import run_discovery_operation
    from harness.discovery_producer import SOURCE_FIELDS, tracker_round
    from tests.unit.test_managed_checkpoint_assess import selection
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    documents = {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()}
    source = {key: before["last_dispatch"][key] for key in SOURCE_FIELDS}
    args = dict(input_tree=selection(case)["input_tree"], artifact_paths=("strategic-overview.md",),
        unowned_writable_paths=("strategic-overview.md",), intent=dict(kind="strategize", request="Map approved scope risks"), producer="strategy")
    executor = StrategyExecutor(provider)
    with PhaseAExecutionLock.acquire(root, "test-strategy"):
        with SpecRunExecutionLock.acquire(store.squad_dir, "test-strategy"):
            parent(case)
            store.prepare_spec_round("strategy", source, expected_state=before)
            result = run_discovery_operation(root, store, executor, **args, create=True)
            assert result.status == "reviewed", result.reason
            assert result.dispatch_count == 3 and result.token_usage == 21
            assert result.candidate.operations == () and result.candidate.history == history
            assert json.loads(result.candidate.candidate_inputs)["routing"] == dict(verdict="DONE", state_updates={})
            assert [call["assignment"]["step"] for call in executor.calls] == ["propose", "author", "review"]
            accepted = store.load()
            replay = run_discovery_operation(root, store, executor, **args, replay_only=True)
            assert replay.candidate == result.candidate and len(executor.calls) == 3
            assert store.load() == accepted
    row = tracker_round(accepted, producer="strategy")
    assert row["source"] == source and row["predecessor"] is None and row["resolution"] is None
    assert accepted["phase_dispatch_counts"]["phase2-strategic-overview"] == 1
    assert accepted["iteration"] == before["iteration"]
    assert accepted["feasibility_structural_attempts"] == before["feasibility_structural_attempts"]
    assert identity.identity_history(spec_id="game") == history
    assert {p.name: p.read_bytes() for p in (root / "specs/game").iterdir() if p.is_file()} == documents
    assert not accepted["phase_dispatch_counts"].get("phase2-tracker-alignment")
    return result


@pytest.mark.parametrize("provider,mode,enabled,policy", [
    ("codex", "guided", False, "disabled"), ("claude", "banzai", True, "warn")])
def test_released_gate_authorizes_reviewed_strategy(checkpoint_case, provider, mode, enabled, policy):
    complete_policy(checkpoint_case, provider, mode, enabled, policy)
    assert_reviewed_strategy(checkpoint_case, provider)
