"""Native first-check policy survives managed publication and recovery."""
from copy import deepcopy

import pytest
import yaml

from tests.unit.test_managed_feasibility_gate import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, publish_review,
    assert_gate_publication, assert_gate_handoff,
)
from tests.unit.test_managed_feasibility_recheck import assert_gate_budget_integrity


def assert_first_gate_policy(case, provider, policy):
    from harness.discovery_assessment import require_feasibility_parent
    from harness.discovery_producer import SOURCE_FIELDS
    from harness.squad_completion import CompletionError
    root, store, identity, _ = case
    before, history = store.load(), identity.identity_history(spec_id="game")
    bypass = policy in {"disabled", "nonstructural"}
    action = {"disabled": "proceed", "nonstructural": "proceed",
        "block": "block", "warn": "proceed_with_warning"}[policy]
    attempts = 0 if bypass else 1
    assert "feasibility_structural_attempts" not in before
    assert not (root / "specs/game/feasibility-structural-report.json").exists()
    package = assert_gate_publication(case, passed=bypass, action=action,
        attempts=attempts, has_report=not bypass)
    assert_gate_handoff(case, package, provider, passed=bypass, action=action,
        attempts=attempts, has_report=not bypass)
    after = store.load()
    assert after["iteration"] == 0
    assert after["phase_dispatch_counts"]["phase2-decide"] == 1
    assert not after["phase_dispatch_counts"].get("phase2-strategic-overview")
    assert not after["phase_dispatch_counts"].get("phase3-specialists")
    assert after["feasibility_structural_pass"] is bypass
    assert identity.identity_history(spec_id="game") == history
    if bypass:
        assert not (root / "specs/game/feasibility-structural-report.json").exists()
        assert "feasibility_structural_report" not in after
        assert "governance_gate_exhausted" not in after
    else:
        assert after["governance_gate_exhausted"] == "feasibility"
        assert (root / "specs/game/feasibility-structural-report.json").is_file()
        if policy == "block":
            assert after["blocked_reason"] == "governance_structural_exhausted"
    assert_gate_budget_integrity(case)
    # Neither a bypass nor an exhausted gate gives authority to dispatch a repair.
    forged = deepcopy(after)
    forged.update(phase="phase2-decide", status="running")
    source = {key: after["last_dispatch"][key] for key in SOURCE_FIELDS}
    with pytest.raises((ValueError, CompletionError)):
        require_feasibility_parent(root, store.squad_dir, forged, source)
    assert store.load() == after


@pytest.mark.parametrize("provider,mode,enabled,policy", [
    ("codex", "guided", False, "disabled"),
    ("claude", "banzai", True, "nonstructural"),
    ("codex", "guided", False, "block"),
    ("claude", "banzai", True, "warn"),
])
def test_first_gate_preserves_native_policy(checkpoint_case, provider, mode, enabled, policy):
    path = checkpoint_case[0] / ".echelon/config.yml"
    config = yaml.safe_load(path.read_text())
    governance = config.setdefault("governance", {})
    if policy == "disabled":
        governance["enabled"] = False
    elif policy == "nonstructural":
        governance.setdefault("artifacts", {}).setdefault("feasibility", {})["tier"] = "semantic"
    else:
        governance.update(max_repair_attempts=1, on_exhausted=policy)
    path.write_text(yaml.safe_dump(config))
    publish_review(checkpoint_case, provider, mode, enabled)
    assert_first_gate_policy(checkpoint_case, provider, policy)
