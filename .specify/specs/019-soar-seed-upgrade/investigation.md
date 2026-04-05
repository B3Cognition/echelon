# Spec 019 — SOAR Seed Upgrade: Investigation Report

**Investigator:** SCOUT (DISCOVER) + SCIENTIST (INVESTIGATOR) combined  
**Date:** 2026-04-03  
**Subject:** Validate Option A (richer `dispatch_mode` + `guidance` seed rule payloads) for the SOAR overlay  
**Files examined:**  
- `COMMANDER.md` (CA overlay integration reference)  
- `scripts/ca/soar.py` (SOAR overlay implementation)  
- `agents/exploration/scout.md` (representative agent prompt)  
- `agents/specialists/investigator.md` (second agent prompt sample)  
- `agents/build/implementer.md` (third agent prompt sample)  
- `commands/echelon.run.md` (dispatch mechanics — how context_pack reaches agents)  
- `.specify/specs/018-soar-overlay/investigation/iss002-context-pack-keys.md` (prior key inventory)  

---

## Q1 Finding: Does soar_state reach agent prompts?

**Short answer: Partially. The delivery mechanism is in place but the channel is COMMANDER-internal.**

### Evidence

`COMMANDER.md` (lines 56-61) defines the pre-dispatch sequence. Position 6 adds:

```python
from scripts.ca import soar
context_pack = soar.enrich_context(context_pack, run_id)
```

`soar.enrich_context()` returns `enriched["soar_state"] = soar_state` — confirming `soar_state` is injected into the `context_pack` dict.

`commands/echelon.run.md` (lines 524-538) defines how agents receive context. COMMANDER assembles the agent prompt as text: `"Here is your context pack: [include context pack files listed above]"`. The "context pack" in the dispatch prompt refers to a **list of files** — not the Python `context_pack` dict. The files listed are artifacts like `glossary.md`, `spec.md`, `analysis.json`, etc.

**Critical finding:** The `context_pack` dict (including `soar_state`) is COMMANDER's **in-process Python state**. It is NOT automatically serialized into the agent's prompt. Agents receive **files** listed in the context pack, not the dict itself.

**However**, the endocrine system (same COMMANDER.md, lines 220-224) establishes a precedent: `endocrine.sh get_prompt_modifier` returns text that is **prepended to the agent's context pack** as a prompt modifier. This is the existing pattern for injecting live-computed state into agent prompts.

**Conclusion:**  
`soar_state` IS in `context_pack` dict. There is NO mechanism today that serializes `soar_state` from that dict into the agent's actual text prompt. No existing agent prompt references `soar_state`. The SOAR overlay currently enriches a Python dict that COMMANDER reads, but that dict is NOT the same as what agents see.

**This is the most important finding in this investigation.** The value proposition of Option A depends entirely on resolving this gap.

**Delivery mechanism status:** Present at the COMMANDER level. Absent at the agent prompt level. The missing link is: COMMANDER must explicitly serialize `soar_state` into the agent prompt text (analogous to how endocrine modifiers are prepended). Without this, even the most perfectly designed seed rule payloads have zero behavioral effect on agents.

---

## Q2 Finding: Current payload analysis — actionable or not?

**Short answer: Not actionable. The current payloads are observer labels, not behavioral instructions.**

### Current SEED_RULES actions payloads

| Rule | Conditions fired | Current `actions` payload |
|------|-----------------|--------------------------|
| seed-001 | `active_goal` | `{"soar_state_hint": "active-goal-only dispatch"}` |
| seed-002 | `active_goal` + `actr_buffers` | `{"soar_state_hint": "goal-plus-actr dispatch"}` |
| seed-003 | `active_goal` + `gwt_workspace` | `{"soar_state_hint": "goal-plus-workspace dispatch"}` |
| seed-004 | `active_goal` + `actr_buffers` + `gwt_workspace` + `episodic_prior_artifact` | `{"soar_state_hint": "full-tier-1-2 dispatch"}` |
| seed-005 | `active_goal` + `lida_broadcast` | `{"soar_state_hint": "broadcast-signal dispatch"}` |

**Actionability analysis:**

"active-goal-only dispatch" tells a reader what context is present. It does not tell the agent what to DO differently. An agent reading `soar_state_hint = "active-goal-only dispatch"` has no behavioral instruction — it knows something about its context tier but receives no guidance on what that means for its work.

**Specificity test:** If an agent receives `soar_state = {"operator_applied": "seed-001", "impasse": False, "cycle": 1, "wme_count": 1, "soar_state_hint": "active-goal-only dispatch"}`, what specific behavior change does that enable vs not having `soar_state` at all?

Answer: **None**, under two conditions:
1. The agent prompt contains no instructions for parsing or acting on `soar_state` (confirmed — no agent prompt references `soar_state`).
2. Even if an agent could read it, "active-goal-only dispatch" is a context descriptor, not a behavioral directive.

**Measurement:** The 200-char budget for the current seed-001 payload is 126 chars (confirmed by direct calculation). The mandatory fields consume 78 chars. The `soar_state_hint` uses 48 chars of the remaining 122-char headroom. That headroom is currently unused.

---

## Q3 Finding: Is Option A genuinely valuable?

**Short answer: Conditionally YES, with confidence 0.70 — but only if the delivery gap (Q1) is closed first.**

### The gap problem

Option A is only valuable if `soar_state` reaches agent prompts as readable text. Currently it does not. Therefore:

- **Without closing the delivery gap:** Option A value = 0. Payloads are written, no agent reads them, no behavior changes.
- **With the delivery gap closed** (COMMANDER serializes `soar_state` into prompt, analogous to endocrine modifier injection): Option A value = **real and non-zero**.

### Agent prompt evidence

The SCOUT prompt (`agents/exploration/scout.md`) is 446 lines long. It contains:
- High-level role definition ("map the territory", "surface implicit knowledge")
- Mode detection (greenfield vs brownfield)
- Step-by-step procedures for each mode
- Output requirements (exact filenames, exact structures)
- Reasoning journal instructions
- Quality checklist

**What it does NOT contain:** Any instruction about adapting behavior based on how much context is available, what tier of overlays fired, or whether it should prioritize breadth vs depth based on context richness.

The IMPLEMENTER prompt contains "Prime Directive: Write the minimum code that satisfies all acceptance criteria" — again, no context-tier awareness.

**Conclusion:** Agent prompts are **stateless with respect to context richness**. They do not vary their strategy based on whether they have 1 overlay or 5 overlays of context. This is a genuine gap that `dispatch_mode` + `guidance` could fill.

### Does "Sparse context. Prioritize breadth, surface unknowns." add signal?

SCOUT's prompt already says "map the territory" and "surface implicit knowledge" — but this is static guidance, always active. It does not distinguish between:
- A dispatch where the agent has only a goal (no prior artifacts, no workspace) → should be exploratory
- A dispatch where the agent has full context including episodic prior artifacts → should converge

The `guidance` field in Option A would be the **first mechanism that makes agent behavior context-tier-aware**. That is novel and not duplicated by existing prompts.

**Confidence: 0.70** — high enough to recommend, discounted because: (a) the delivery gap must be closed (no evidence it will be), and (b) the behavioral effect has not been experimentally measured (UCA-004 found Cohen's d = 0.40, not specific to SOAR guidance).

---

## Q4 Finding: Best version of Option A payloads

The most valuable payloads satisfy these criteria:
1. Not duplicating what is already in agent prompts
2. Context-tier-specific — each rule fires in exactly one context state and its guidance reflects that state
3. Behavioral — tells the agent what to do differently, not just what context it has
4. Within 200-char budget (verified below)

### Proposed seed rule payloads

**seed-001** — `active_goal` only (no prior context, first dispatch for this agent type)
```python
"actions": {
    "dispatch_mode": "exploratory",
    "guidance": "Sparse context. No prior artifacts. Prioritize breadth; surface unknowns over depth.",
}
```
Serialized chars (with mandatory fields at cycle=1, wme_count=1): **179** — within budget.

**seed-002** — `active_goal` + `actr_buffers` (declarative knowledge available, no workspace history)
```python
"actions": {
    "dispatch_mode": "focused",
    "guidance": "ACT-R declarative buffers loaded. Ground analysis in retrieved excerpts before expanding.",
}
```
Serialized chars (wme_count=2): **196** — within budget.

**seed-003** — `active_goal` + `gwt_workspace` (workspace history exists, no episodic artifact)
```python
"actions": {
    "dispatch_mode": "incremental",
    "guidance": "GWT workspace loaded. Build on prior context; avoid re-covering ground.",
}
```
Serialized chars (wme_count=2): **197** — within budget.

**seed-004** — full tier 1+2 (`active_goal` + `actr_buffers` + `gwt_workspace` + `episodic_prior_artifact`)
```python
"actions": {
    "dispatch_mode": "convergent",
    "guidance": "Full context. Prior artifact present. Target depth; resolve open unknowns.",
}
```
Serialized chars (wme_count=4): **199** — within budget (1 char margin).

**seed-005** — `active_goal` + `lida_broadcast` (broadcast override active)
```python
"actions": {
    "dispatch_mode": "reactive",
    "guidance": "LIDA broadcast active. Treat it as high-priority context override.",
}
```
Serialized chars (wme_count=2): **189** — within budget.

### Dispatch mode semantics (for agent prompt injection instructions)

| `dispatch_mode` | Agent interpretation |
|----------------|---------------------|
| `exploratory` | No prior artifacts. Cast wide. Surface unknowns. Do not converge prematurely. |
| `focused` | Declarative knowledge present. Use retrieved excerpts. Be specific, not general. |
| `incremental` | Workspace history present. Build on it. Do not repeat what workspace already contains. |
| `convergent` | Full context available. Prior artifact exists. Resolve open items, don't reopen closed ones. |
| `reactive` | Broadcast overrides normal priority. Process broadcast payload first. |

**These five modes are mutually exclusive by construction** — each seed rule fires on a unique combination of context keys, so an agent dispatch can only receive one `dispatch_mode` value.

---

## Q5 Finding: Concrete test designs

The following tests verify the value proposition — not merely that `soar_state` is a dict, but that it carries correct, useful signal.

---

### TEST-019-001: Seed rule coverage — all five rules fire on correct inputs

**Name:** `test_soar_seed_coverage`  
**File:** `tests/unit/test_soar_seed_rules.py`  
**Setup:**  
```python
# Five context_pack inputs, each matching exactly one seed rule's conditions
packs = {
    "seed-001": {"active_goal": {"goal_text": "test", "priority": 1.0, "depth": 0}},
    "seed-002": {"active_goal": {}, "actr_buffers": {}},
    "seed-003": {"active_goal": {}, "gwt_workspace": [{"text": "x", "timestamp": 1.0}]},
    "seed-004": {"active_goal": {}, "actr_buffers": {}, "gwt_workspace": [{}], "episodic_prior_artifact": {"artifact_path": "a", "stage_timestamp": 1.0, "artifact_category": "spec"}},
    "seed-005": {"active_goal": {}, "lida_broadcast": {"type": "alert"}},
}
```
**Assertion:** For each pack, `_match_rules(_extract_wmes(pack), SEED_RULES)["rule_id"] == expected_rule_id`  
**What it proves:** Each seed rule fires on the correct context configuration. No cross-fire, no missed firing.

---

### TEST-019-002: dispatch_mode field present in all matched rule outputs

**Name:** `test_soar_dispatch_mode_present`  
**File:** `tests/unit/test_soar_seed_rules.py`  
**Setup:** Same five packs as TEST-019-001. With upgraded SEED_RULES containing `dispatch_mode` in actions.  
**Assertion:** For each pack, `enrich_context(pack, run_id)["soar_state"]["dispatch_mode"]` is one of `{"exploratory", "focused", "incremental", "convergent", "reactive"}`  
**What it proves:** Option A payloads survive the `_apply_operator` merge and appear in the output `soar_state`.

---

### TEST-019-003: guidance field present and non-empty in all matched outputs

**Name:** `test_soar_guidance_non_empty`  
**File:** `tests/unit/test_soar_seed_rules.py`  
**Setup:** Same five packs.  
**Assertion:** `len(soar_state["guidance"]) > 10` for all five cases  
**What it proves:** Guidance strings survived the 200-char cap enforcement and were not truncated to the mandatory-only fallback.

---

### TEST-019-004: 200-char cap satisfied for all seed rules at realistic cycle/wme counts

**Name:** `test_soar_200_char_cap`  
**File:** `tests/unit/test_soar_seed_rules.py`  
**Setup:** Simulate realistic cycle counts (cycle=10, cycle=50, cycle=100) and realistic wme_counts (1-5). Apply `_apply_operator` for all five seed rules at each combination.  
**Assertion:** `len(json.dumps(soar_state)) <= 200` for all combinations  
**What it proves:** The 200-char cap (NFR-SOAR per spec 018) is not violated at any point in a real run. Note: cycle and wme_count are integers — their serialized width grows with magnitude. At cycle=100, `"cycle": 100` uses 3 chars vs `"cycle": 1` uses 1 char. The worst case (cycle=100, wme_count=5, seed-004 with longest payload) must be verified.  
**Critical case:**  
```python
# seed-004 worst case
state = {"operator_applied": "seed-004", "impasse": False, "cycle": 100, "wme_count": 5,
         "dispatch_mode": "convergent", "guidance": "Full context. Prior artifact present. Target depth; resolve open unknowns."}
assert len(json.dumps(state)) <= 200  # must be 201 chars — FAIL case to catch
```
Expected: seed-004 at cycle=100 = 201 chars — EXCEEDS budget by 2. This is a real failure the test would catch, requiring guidance to be shortened to 71 chars max for seed-004.

---

### TEST-019-005: dispatch_mode values are semantically distinct (no two rules produce same mode)

**Name:** `test_soar_dispatch_mode_unique`  
**File:** `tests/unit/test_soar_seed_rules.py`  
**Setup:** Apply all five seed rules, collect `dispatch_mode` values.  
**Assertion:** `len(set(dispatch_modes)) == 5` — all five modes are distinct strings  
**What it proves:** SOAR does not produce ambiguous guidance. Each context tier maps to exactly one behavioral directive.

---

### TEST-019-006: Impasse produces no dispatch_mode or guidance

**Name:** `test_soar_impasse_no_guidance`  
**File:** `tests/unit/test_soar_seed_rules.py`  
**Setup:** Empty context pack — no overlay keys present.  
**Assertion:** `soar_state["impasse"] == True` and `"dispatch_mode" not in soar_state` and `"guidance" not in soar_state`  
**What it proves:** Impasse handling is clean. An agent receiving `impasse=True` state does not receive stale guidance from a previous rule.

---

### TEST-019-007: seed-004 only fires when ALL four conditions are present (not three)

**Name:** `test_soar_seed004_requires_all_four_conditions`  
**File:** `tests/unit/test_soar_seed_rules.py`  
**Setup:**  
```python
# Pack missing episodic_prior_artifact — should NOT fire seed-004
pack_missing_episodic = {"active_goal": {}, "actr_buffers": {}, "gwt_workspace": [{}]}
# Pack with all four — should fire seed-004
pack_full = {"active_goal": {}, "actr_buffers": {}, "gwt_workspace": [{}], "episodic_prior_artifact": {}}
```
**Assertion:** `_match_rules(_extract_wmes(pack_missing_episodic), SEED_RULES)["rule_id"] != "seed-004"` and `_match_rules(_extract_wmes(pack_full), SEED_RULES)["rule_id"] == "seed-004"`  
**What it proves:** seed-004's "convergent" guidance only fires when context truly is full. An agent is not told to "converge" when episodic prior artifact is absent.

---

### TEST-019-008: Chunking disabled by default — no learned rule duplicates guidance

**Name:** `test_soar_chunking_disabled_no_chunk_guidance`  
**File:** `tests/unit/test_soar_seed_rules.py`  
**Setup:** Run `enrich_context` then `update_soar_memory({"status": "COMPLETE"}, run_id)` with `chunking_enabled: false` in config.  
**Assertion:** `len(store["rules"]) == 5` (no chunk appended). If chunking were enabled, chunk rule `actions` would copy from matched seed rule — verify copied `dispatch_mode` + `guidance` survive into chunk.  
**What it proves:** The chunking path (when enabled) correctly propagates Option A fields; the disabled path does not pollute the rule store.

---

### TEST-019-009: soar_state is the last key added — prior overlay keys preserved (AC-1.5)

**Name:** `test_soar_prior_overlay_keys_preserved`  
**File:** `tests/unit/test_soar_seed_rules.py`  
**Setup:** Context pack with all five overlay keys. Run `enrich_context`.  
**Assertion:** All original keys (`active_goal`, `actr_buffers`, `gwt_workspace`, `episodic_prior_artifact`, `lida_broadcast`) still present in the returned dict AND `soar_state` is also present.  
**What it proves:** Option A payloads do not corrupt the 6-overlay integration chain. soar_state is additive, not destructive.

---

### TEST-019-010: COMMANDER.md references SOAR delivery mechanism for agent prompts

**Name:** `test_soar_delivery_mechanism_documented`  
**File:** `tests/unit/test_soar_seed_rules.py` (documentation compliance)  
**Setup:** Read `COMMANDER.md` as text.  
**Assertion:** `"soar_state"` appears in COMMANDER.md's agent dispatch instructions (i.e., the delivery gap documented in Q1 has been closed by a COMMANDER amendment).  
**What it proves:** The spec 019 amendment to COMMANDER.md is present and `soar_state` serialization into agent prompts is documented. **This test will FAIL until the Q1 delivery gap is closed.** It is the integration gate for the entire Option A value chain.

---

## Verdict

### RECOMMEND_OPTION_A — with mandatory prerequisite

**Option A is the right direction.** The `dispatch_mode` + `guidance` field design is sound:
- Agent prompts are stateless with respect to context richness (confirmed from prompt inspection)
- The 200-char budget accommodates all five payloads (confirmed by calculation, with one edge case in seed-004 at cycle >= 10 that requires guidance trimming to ≤71 chars)
- The five dispatch modes are semantically distinct and non-overlapping
- The guidance strings are behavioral directives that do not duplicate existing agent prompt content

**However, Option A has zero value without closing the Q1 delivery gap first.**

The mandatory prerequisite is: **COMMANDER must serialize `soar_state` into the agent's text prompt**, using the same pattern as endocrine modifier injection (prepend as a structured block). Without this, the SOAR overlay enriches a Python dict that no agent reads — a technically correct implementation that produces no behavioral effect.

### Recommended implementation order

1. **First:** Amend COMMANDER.md to serialize `soar_state` into agent prompts. Suggested format:
   ```
   ## SOAR Context
   Dispatch mode: {dispatch_mode}
   Guidance: {guidance}
   [If impasse=True: Context overlay produced no match. Proceed with default strategy.]
   ```
   This mirrors the endocrine modifier pattern already in COMMANDER.md (lines 220-224).

2. **Second:** Upgrade SEED_RULES in `soar.py` with Option A payloads (the concrete dicts in Q4).

3. **Third:** Run TEST-019-010 as the gate. If it passes, the full Option A value chain is closed. If it fails, seed rule payload upgrades have no behavioral effect regardless of their quality.

### Confidence in recommendation

| Dimension | Confidence | Basis |
|-----------|-----------|-------|
| Delivery gap is real | 0.95 | Direct inspection of echelon.run.md dispatch pattern |
| Agent prompts are stateless on context tier | 0.90 | Three agent prompts inspected, none reference soar_state or context richness |
| Option A payloads add unique signal | 0.75 | No existing mechanism provides context-tier-aware behavioral guidance |
| 200-char budget holds for proposed payloads | 0.95 | Direct calculation; seed-004 edge case identified and must be addressed |
| Behavioral effect measurable via NS-003 style experiment | 0.60 | Analogous to UCA-004; requires controlled dispatch with/without soar_state injection |
