"""Unchanged repair output consumes the original alignment budget to exhaustion."""
from copy import deepcopy

import pytest
import yaml

from tests.unit.test_managed_alignment_retry import (
    case, enrolled, turn_prepared, prepared, checkpoint_case,
    complete_retry, assert_repaired_gate, complete_first_alignment_gate,
    assert_retry_authority, assert_reviewed_retry, assert_retry_publication,
)
from tests.unit.test_managed_alignment_publication import assert_alignment_handoff
from tests.unit.test_managed_alignment_gate import assert_gate_publication, assert_gate_handoff
from tests.unit.test_managed_alignment_recheck import (
    assert_recheck_preparation_refusals, assert_recheck_budget_integrity,
)


def assert_exhausted_alignment(case, provider, *, policy, cap, start_attempt=2):
    root, store, identity, _ = case
    initial = store.load()
    history = identity.identity_history(spec_id="game")
    original_rounds = deepcopy(initial["managed_alignment_rounds"]["rounds"])
    unchanged = (root / "specs/game/intent-alignment-check.md").read_text()
    for attempt in range(start_attempt, cap + 1):
        assert_retry_authority(case, attempts=attempt - 1)
        assert_reviewed_retry(case, provider, alignment_text=unchanged, round_number=attempt)
        assert_alignment_handoff(case, assert_retry_publication(case, provider), provider)
        assert (root / "specs/game/intent-alignment-check.md").read_text() == unchanged
        assert_recheck_preparation_refusals(case)
        action = ("block" if policy == "block" else "proceed_with_warning") if attempt == cap else "repair"
        gate = assert_gate_publication(case, previous_attempts=attempt - 1, attempts=attempt, action=action)
        assert_gate_handoff(case, gate, provider, attempts=attempt, action=action)
        assert_recheck_budget_integrity(case, previous_attempts=attempt - 1)
    final = store.load()
    assert final["intent_alignment_check_structural_attempts"] == cap
    assert final["iteration"] == initial["iteration"] + cap - start_attempt
    assert final["governance_gate_exhausted"] == "intent-alignment-check"
    assert final["phase"] == ("terminal-blocked" if policy == "block" else "phase3-specialists")
    assert final["status"] == ("blocked" if policy == "block" else "running")
    if policy == "block":
        assert final["blocked_reason"] == "governance_structural_exhausted"
    assert final["token_usage"] == initial["token_usage"] + 21 * (cap - start_attempt + 1)
    assert final["phase_dispatch_counts"]["phase2-tracker-alignment"] == cap
    assert not final["phase_dispatch_counts"].get("phase3-specialists")
    assert final["feasibility_structural_attempts"] == initial["feasibility_structural_attempts"]
    assert identity.identity_history(spec_id="game") == history
    assert all(final["managed_alignment_rounds"]["rounds"][key] == row for key, row in original_rounds.items())


@pytest.mark.parametrize("provider,mode,enabled,policy,cap", [
    ("codex", "guided", False, "block", 2), ("claude", "banzai", True, "warn", 3)])
def test_no_progress_alignment_exhausts_original_budget(checkpoint_case, provider, mode, enabled, policy, cap):
    path = checkpoint_case[0] / ".echelon/config.yml"
    config = yaml.safe_load(path.read_text())
    config.setdefault("governance", {}).update(max_repair_attempts=cap, on_exhausted=policy)
    path.write_text(yaml.safe_dump(config))
    complete_retry(checkpoint_case, provider, mode, enabled)
    assert_repaired_gate(checkpoint_case, provider)
    complete_first_alignment_gate(checkpoint_case, provider)
    assert_exhausted_alignment(checkpoint_case, provider, policy=policy, cap=cap)
