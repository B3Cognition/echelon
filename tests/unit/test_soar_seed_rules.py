"""
tests/unit/test_soar_seed_rules.py
Spec 019 — SOAR seed rule upgrade: value proposition tests (TEST-019-001 through TEST-019-010).

These tests verify that:
  1. Each seed rule fires on the correct context tier
  2. dispatch_mode + guidance reach soar_state (Option A payload delivery)
  3. The 200-char cap holds at realistic cycle counts
  4. The COMMANDER.md delivery gap (Q1) is documented as closed

Run with: python3 -m pytest tests/unit/test_soar_seed_rules.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Path setup — allow running from repo root or tests/ directory
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.ca.soar import (  # noqa: E402
    SEED_RULES,
    _apply_operator,
    _extract_wmes,
    _match_rules,
    enrich_context,
    update_soar_memory,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Standard five context packs, one per seed rule's trigger condition
PACKS = {
    "seed-001": {
        "active_goal": {"goal_text": "investigate the domain", "priority": 1.0, "depth": 0},
    },
    "seed-002": {
        "active_goal": {"goal_text": "analyze requirements", "priority": 1.0, "depth": 0},
        "actr_buffers": {"declarative": [], "procedural": [], "goal": [], "imaginal": []},
    },
    "seed-003": {
        "active_goal": {"goal_text": "refine the plan", "priority": 1.0, "depth": 0},
        "gwt_workspace": [{"text": "prior context", "timestamp": 1.0}],
    },
    "seed-004": {
        "active_goal": {"goal_text": "finalize the spec", "priority": 1.0, "depth": 0},
        "actr_buffers": {"declarative": [], "procedural": [], "goal": [], "imaginal": []},
        "gwt_workspace": [{"text": "workspace item", "timestamp": 1.0}],
        "episodic_prior_artifact": {
            "artifact_path": "specs/018-soar-overlay/spec.md",
            "stage_timestamp": 1.0,
            "artifact_category": "spec",
        },
    },
    "seed-005": {
        "active_goal": {"goal_text": "respond to broadcast", "priority": 1.0, "depth": 0},
        "lida_broadcast": {"type": "alert", "payload": "urgent: spec gate failed"},
    },
}

VALID_DISPATCH_MODES = {"exploratory", "focused", "incremental", "convergent", "reactive"}
RUN_ID = "test-019-run-001"


# ---------------------------------------------------------------------------
# TEST-019-001: Each seed rule fires on the correct context pack
# ---------------------------------------------------------------------------

def test_soar_seed_coverage():
    """Each seed rule fires exactly on its intended context tier. No cross-fire."""
    for expected_rule_id, pack in PACKS.items():
        wmes = _extract_wmes(pack)
        matched = _match_rules(wmes, SEED_RULES)
        assert matched is not None, f"No rule matched for {expected_rule_id} pack (impasse)"
        assert matched["rule_id"] == expected_rule_id, (
            f"Expected {expected_rule_id} to fire, got {matched['rule_id']}.\n"
            f"Pack keys: {list(pack.keys())}\n"
            f"WMEs: {[w['attr'] for w in wmes]}"
        )


# ---------------------------------------------------------------------------
# TEST-019-002: dispatch_mode present in soar_state for all matched rules
# ---------------------------------------------------------------------------

def test_soar_dispatch_mode_present(tmp_path, monkeypatch):
    """dispatch_mode survives _apply_operator and appears in soar_state (Option A delivery)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / "runs" / RUN_ID).mkdir(parents=True)

    for rule_id, pack in PACKS.items():
        result = enrich_context(pack, RUN_ID)
        ss = result.get("soar_state", {})
        assert "dispatch_mode" in ss, (
            f"dispatch_mode missing from soar_state for {rule_id}.\n"
            f"soar_state = {ss}"
        )
        assert ss["dispatch_mode"] in VALID_DISPATCH_MODES, (
            f"dispatch_mode '{ss['dispatch_mode']}' not in canonical set {VALID_DISPATCH_MODES}"
        )


# ---------------------------------------------------------------------------
# TEST-019-003: guidance is non-empty (not truncated to mandatory-only fallback)
# ---------------------------------------------------------------------------

def test_soar_guidance_non_empty(tmp_path, monkeypatch):
    """Guidance strings survive the 200-char cap and are not truncated away."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / "runs" / RUN_ID).mkdir(parents=True)

    for rule_id, pack in PACKS.items():
        result = enrich_context(pack, RUN_ID)
        ss = result.get("soar_state", {})
        assert "guidance" in ss, (
            f"guidance missing from soar_state for {rule_id} — "
            f"payload was truncated to mandatory-only fallback.\n"
            f"soar_state = {ss}"
        )
        assert len(ss["guidance"]) > 10, (
            f"guidance too short ({len(ss['guidance'])} chars) for {rule_id} — "
            f"likely truncated or empty.\n"
            f"guidance = {ss['guidance']!r}"
        )


# ---------------------------------------------------------------------------
# TEST-019-004: 200-char cap at realistic cycle/wme counts (worst-case matrix)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cycle", [1, 10, 50, 100])
@pytest.mark.parametrize("wme_count", [1, 2, 3, 4, 5])
def test_soar_200_char_cap(cycle, wme_count):
    """soar_state len(json.dumps()) <= 200 for all seed rules at all realistic cycle/wme values."""
    for rule in SEED_RULES:
        ss = _apply_operator(rule, cycle=cycle, wme_count=wme_count)
        serialized = json.dumps(ss)
        assert len(serialized) <= 200, (
            f"200-char cap VIOLATED for {rule['rule_id']} "
            f"at cycle={cycle}, wme_count={wme_count}:\n"
            f"  len={len(serialized)}, payload={serialized!r}\n"
            f"  Reduce guidance to fit. seed-004 guidance must be ≤71 chars."
        )


# ---------------------------------------------------------------------------
# TEST-019-005: dispatch_mode values are distinct across all five rules
# ---------------------------------------------------------------------------

def test_soar_dispatch_mode_unique():
    """Each seed rule maps to a unique dispatch_mode — no ambiguous guidance."""
    modes = [rule["actions"]["dispatch_mode"] for rule in SEED_RULES]
    assert len(modes) == len(set(modes)), (
        f"Duplicate dispatch_mode values detected: {modes}. "
        f"Each context tier must map to exactly one behavioral directive."
    )
    assert set(modes) == VALID_DISPATCH_MODES, (
        f"Seed rules do not cover all canonical modes.\n"
        f"Expected: {VALID_DISPATCH_MODES}\n"
        f"Got: {set(modes)}"
    )


# ---------------------------------------------------------------------------
# TEST-019-006: Impasse produces no dispatch_mode or guidance
# ---------------------------------------------------------------------------

def test_soar_impasse_no_guidance(tmp_path, monkeypatch):
    """When no rule matches (impasse), soar_state contains no dispatch_mode or guidance."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / "runs" / RUN_ID).mkdir(parents=True)

    # Empty pack — no recognized WME keys, all seed rules require active_goal
    empty_pack = {"unrelated_key": "value", "another_key": 42}
    result = enrich_context(empty_pack, RUN_ID)
    ss = result.get("soar_state", {})

    assert ss.get("impasse") is True, (
        f"Expected impasse=True for empty pack, got impasse={ss.get('impasse')}.\n"
        f"soar_state = {ss}"
    )
    assert ss.get("operator_applied") == "default-no-match", (
        f"Expected operator_applied='default-no-match' on impasse, got {ss.get('operator_applied')!r}"
    )
    assert "dispatch_mode" not in ss, (
        f"dispatch_mode should not appear on impasse. soar_state = {ss}"
    )
    assert "guidance" not in ss, (
        f"guidance should not appear on impasse. soar_state = {ss}"
    )


# ---------------------------------------------------------------------------
# TEST-019-007: seed-004 requires ALL four Tier 1+2 conditions
# ---------------------------------------------------------------------------

def test_soar_seed004_requires_all_four_conditions():
    """seed-004 ('convergent') fires only when active_goal+actr_buffers+gwt_workspace+episodic_prior_artifact are all present."""
    # Pack missing episodic_prior_artifact — should NOT fire seed-004
    pack_missing_episodic = {
        "active_goal": {"goal_text": "test", "priority": 1.0, "depth": 0},
        "actr_buffers": {},
        "gwt_workspace": [{}],
        # episodic_prior_artifact absent
    }
    matched_without = _match_rules(_extract_wmes(pack_missing_episodic), SEED_RULES)
    assert matched_without is not None, "Expected a non-seed-004 rule to match"
    assert matched_without["rule_id"] != "seed-004", (
        f"seed-004 fired without episodic_prior_artifact (got {matched_without['rule_id']}). "
        f"Agents should not receive 'convergent' guidance when prior artifact is absent."
    )

    # Pack with all four — should fire seed-004
    pack_full = {
        "active_goal": {"goal_text": "test", "priority": 1.0, "depth": 0},
        "actr_buffers": {},
        "gwt_workspace": [{}],
        "episodic_prior_artifact": {"artifact_path": "a", "stage_timestamp": 1.0, "artifact_category": "spec"},
    }
    matched_full = _match_rules(_extract_wmes(pack_full), SEED_RULES)
    assert matched_full is not None, "Expected seed-004 to match full Tier 1+2 pack"
    assert matched_full["rule_id"] == "seed-004", (
        f"Expected seed-004 on full Tier 1+2 pack, got {matched_full['rule_id']}"
    )


# ---------------------------------------------------------------------------
# TEST-019-008: Chunking disabled by default — no rules added to store
# ---------------------------------------------------------------------------

def test_soar_chunking_disabled_no_chunk_appended(tmp_path, monkeypatch):
    """When chunking_enabled=false (default), update_soar_memory adds no ChunkRecord."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / "runs" / RUN_ID).mkdir(parents=True)

    # Enrich to create the procedural store
    pack = PACKS["seed-001"]
    enrich_context(pack, RUN_ID)

    # Call update_soar_memory with a successful outcome
    update_soar_memory({"status": "DONE"}, RUN_ID)

    # Load the store and verify no chunk was appended (chunking disabled by default)
    store_path = tmp_path / "runs" / RUN_ID / f"soar-procedural-{RUN_ID}.json"
    with open(store_path) as f:
        store = json.load(f)

    chunks = [r for r in store["rules"] if r.get("learned")]
    assert len(chunks) == 0, (
        f"Expected 0 chunks (chunking disabled by default), got {len(chunks)}.\n"
        f"ChunkRecords: {chunks}"
    )
    assert len(store["rules"]) == len(SEED_RULES), (
        f"Expected exactly {len(SEED_RULES)} seed rules in store, "
        f"got {len(store['rules'])} (chunking may have been enabled unexpectedly)"
    )


# ---------------------------------------------------------------------------
# TEST-019-009: soar_state is additive — all prior overlay keys preserved (AC-1.5)
# ---------------------------------------------------------------------------

def test_soar_prior_overlay_keys_preserved(tmp_path, monkeypatch):
    """soar_state enrichment is additive — all five prior overlay keys remain intact."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / "runs" / RUN_ID).mkdir(parents=True)

    full_pack = {
        "active_goal": {"goal_text": "test goal", "priority": 1.0, "depth": 0},
        "actr_buffers": {"declarative": [], "procedural": [], "goal": [], "imaginal": []},
        "gwt_workspace": [{"text": "workspace item", "timestamp": 1.0}],
        "episodic_prior_artifact": {
            "artifact_path": "specs/018/spec.md",
            "stage_timestamp": 1.0,
            "artifact_category": "spec",
        },
        "lida_broadcast": {"type": "info", "payload": "test broadcast"},
        # Extra key that should also be preserved
        "role": "IMPLEMENTER",
    }

    result = enrich_context(full_pack, RUN_ID)

    # All original keys must be preserved
    for key in full_pack:
        assert key in result, f"Key '{key}' lost after soar.enrich_context"
        assert result[key] == full_pack[key], (
            f"Key '{key}' value mutated by soar.enrich_context.\n"
            f"Before: {full_pack[key]!r}\nAfter: {result[key]!r}"
        )

    # soar_state must be the only new key
    assert "soar_state" in result, "soar_state not added by enrich_context"
    new_keys = set(result.keys()) - set(full_pack.keys())
    assert new_keys == {"soar_state"}, (
        f"Unexpected new keys added by enrich_context: {new_keys - {'soar_state'}}"
    )


# ---------------------------------------------------------------------------
# TEST-019-010: COMMANDER.md delivery mechanism documented (Q1 delivery gap closed)
# ---------------------------------------------------------------------------

def test_soar_delivery_mechanism_documented():
    """docs/soar-delivery.md must document soar_state serialization into agent prompts (FR-019-001).

    This test verifies the Q1 delivery gap identified in investigation.md is closed.
    It FAILS if the injection block was never added to docs/soar-delivery.md.
    """
    commander_path = os.path.join(REPO_ROOT, "docs", "soar-delivery.md")
    assert os.path.exists(commander_path), (
        f"docs/soar-delivery.md not found at {commander_path}"
    )

    with open(commander_path, encoding="utf-8") as f:
        content = f.read()

    # The injection block must reference soar_state and the delivery mechanism
    assert "soar_state" in content, (
        "COMMANDER.md does not mention soar_state. "
        "The Q1 delivery gap (soar_state not serialized into agent prompts) is NOT closed. "
        "FR-019-001 requires COMMANDER to serialize soar_state into agent prompt text."
    )
    assert "_soar_prompt_block" in content or "soar_prompt_block" in content or "SOAR DISPATCH GUIDANCE" in content, (
        "COMMANDER.md does not contain the SOAR prompt injection block. "
        "Expected: '[SOAR DISPATCH GUIDANCE]' block or _soar_prompt_block variable. "
        "FR-019-001 requires serializing dispatch_mode + guidance into agent prompts."
    )
    assert "dispatch_mode" in content, (
        "COMMANDER.md does not reference dispatch_mode in its injection mechanism. "
        "The delivery mechanism is incomplete."
    )
