# ISS-004 Token Budget Investigation
# FR-CAO-002: 6-Overlay Stack Token Budget Compliance

**Investigator:** SCIENTIST (INVESTIGATOR agent)
**Date:** 2026-04-03
**Question:** Does the full 6-overlay stack stay within the token budget of the original pre-overlay context_pack?
**FR-CAO-002:** Each overlay's returned context_pack MUST NOT exceed the token count of the standard COMMANDER context_pack (4-char/token heuristic).

---

## Step 1: QUESTION

**What exactly do we not know?**
Whether running all 5 (and eventually 6) CA overlays in sequence causes cumulative token growth that violates FR-CAO-002.

**What decision depends on this answer?**
SOAR overlay design — specifically the maximum allowed size of `soar_state` and whether a structural fix to `actr_buffer` is required before SOAR can be added safely.

**What would "good enough" evidence look like?**
Measured token counts at each overlay step, with root-cause analysis of any violations.

**Cost of being wrong:**
If SOAR is added without a cap, the LLM context window grows unboundedly per dispatch, degrading output quality and violating the FR.

---

## Step 2: RESEARCH

All evidence comes from direct code execution against the live codebase. No external sources were required for this measurement study — the overlays are self-contained Python modules with no external dependencies.

Relevant code files examined:
- `/scripts/ca/goal_stack.py` — T-021
- `/scripts/ca/actr_buffer.py` — T-022
- `/scripts/ca/gwt_workspace.py` — T-024
- `/scripts/ca/episodic_memory.py` — T-025

---

## Step 3: EVIDENCE QUALITY

All findings below are from direct code execution (experiment). Per INV-003: an experiment that validates a Grade C-E finding upgrades it to Grade B. All measurements below are Grade B (reproducible experiment).

---

## Step 4: HYPOTHESES

**H1:** "If actr_buffer keeps original keys in the returned dict AND adds actr_buffers, then the total token count must always exceed the baseline because actr_buffers contains non-zero content — making FR-CAO-002 permanently violated by actr_buffer regardless of content."

**H2:** "If gwt_workspace and episodic_memory inject only small, bounded payloads (empty list / None), then their contribution to total growth is negligible (<5 tokens)."

**H3:** "If goal_stack adds only a single small dict (~26 tokens), then its contribution is within acceptable bounds."

---

## Step 5: EXPERIMENT

### Setup

Representative context pack (small variant, ~565 tokens baseline):
```python
cp = {
    "role": "IMPLEMENTER — builds features per spec",
    "task": "Implement the SOAR overlay module scripts/ca/soar.py",
    "spec_text": "SOAR overlay spec: production rules, working memory, chunking. " * 20,
    "prior_artifacts": "Previous artifact: goal_stack.py implements enrich_context. " * 10,
    "constitution": "P-001 every agent has one job. P-006 CA overlays gate-blocked. " * 5,
}
```

Larger context pack (7 keys, ~895 tokens baseline) also tested for scaling behavior.

Token heuristic: `max(1, len(str(value)) // 4)` per value, summed across all keys.

Overlays run in sequence: `goal_stack → actr_buffer → gwt_workspace → episodic_memory`

---

## Step 6: MEASUREMENTS

### Small Baseline (565 tokens)

| Overlay | Tokens After | Delta | Cumulative Growth | FR-CAO-002 |
|---------|-------------|-------|-------------------|------------|
| Baseline | 565 | — | 0% | — |
| goal_stack | 591 | +26 | +4.6% | VIOLATED (barely) |
| actr_buffer | 1163 | +572 | +105.8% | VIOLATED |
| gwt_workspace | 1164 | +1 | +106.0% | VIOLATED |
| episodic_memory | 1165 | +1 | +106.2% | VIOLATED |

**Key baseline breakdown:**

| Key | Chars | Tokens |
|-----|-------|--------|
| role | 38 | 9 |
| task | 52 | 13 |
| spec_text | 1260 | 315 |
| prior_artifacts | 600 | 150 |
| constitution | 315 | 78 |
| **Total** | **2265** | **565** |

### Large Baseline (895 tokens, 7 keys)

| Overlay | Tokens After | Ratio vs Baseline |
|---------|-------------|-------------------|
| Baseline | 895 | 1.00x |
| goal_stack | 921 | 1.03x |
| actr_buffer | 1705 | 1.91x |
| gwt_workspace | 1706 | 1.91x |
| episodic_memory | 1707 | 1.91x |

### actr_buffer internal structure breakdown (small baseline)

| Buffer | Entries | Chars | Tokens |
|--------|---------|-------|--------|
| declarative | 1 | 353 | 88 |
| procedural | 1 | 68 | 17 |
| goal | 2 | 224 | 56 |
| imaginal | 1 | 641 | 160 |
| retrieval_buffer | 2 | 925 | 231 |
| **Total actr_buffers** | — | **2211** | **552** |

---

## Step 7: SYNTHESIS

### Root Cause of Violation

**actr_buffer has a structural duplication bug:**

`actr_buffer.enrich_context` returns `dict(context_pack)` with an additional `actr_buffers` key injected. The `actr_buffers` structure replicates all original key-value pairs (wrapped as `{"key": k, "value": v}` entries) plus a `retrieval_buffer` containing excerpts of top-3 declarative items.

The internal enforcement (lines 161-170 of `actr_buffer.py`) only enforces that `actr_buffers` internal content does not exceed `original_tokens`. But since the returned dict still contains all original keys AND `actr_buffers`, the total is always:

```
returned_tokens ≈ original_tokens + actr_buffers_tokens
                ≤ original_tokens + original_tokens  (by enforcement)
                = 2 × original_tokens
```

This means **FR-CAO-002 is structurally violated by actr_buffer in every invocation**. The enforcement code inside actr_buffer governs its internal structure, not the total context_pack size.

**H1 confirmed.** The violation is not a sizing problem — it is an architectural flaw. actr_buffer cannot comply with FR-CAO-002 as currently implemented while also providing typed buffer structure.

**H2 confirmed.** gwt_workspace adds 1 token (empty list `[]`), episodic_memory adds 1 token (`None`). Both comply trivially when their persistent state is empty.

**H3 confirmed.** goal_stack adds 26 tokens (1 small dict). This is a 4.6% increase on a 565-token baseline — borderline but small. On larger baselines (895 tokens), it is 2.9%.

### Conflict: FR-CAO-002 vs actr_buffer's design intent

FR-CAO-002 requires the returned context_pack not to exceed baseline tokens. actr_buffer's design requires duplicating content into typed buffers. These two requirements are in direct conflict. One must yield.

### SOAR overlay headroom

With the current 4-overlay stack already at ~2.06x baseline, there is **zero headroom** for SOAR to add content without worsening the violation. Adding a minimal `soar_state` (~125 tokens) would push the stack to ~2.28x. A large `soar_state` (10 rules, 15 WMEs, ~500 tokens) would reach ~2.95x.

### SOAR state size estimation

| Variant | Rules | WMEs | Chars | Tokens |
|---------|-------|------|-------|--------|
| Minimal | 2 | 3 | 503 | 125 |
| Typical | 4 | 8 | ~900 | ~225 |
| Large | 10 | 15 | 2000 | 500 |

---

## Step 8: RECOMMEND

### Primary Recommendation

**Fix actr_buffer's structural duplication before adding SOAR.**

The actr_buffer overlay must either:

**Option A (preferred):** Replace original keys with actr_buffers — remove original top-level keys from the returned dict and provide all content through the typed buffer structure only. This keeps token count at parity (actr_buffers <= original by enforcement).

**Option B:** Remove the retrieval_buffer (largest contributor at ~231 tokens on small baseline) and truncate buffer values more aggressively to stay under original token count.

**Option C:** Treat FR-CAO-002 as applying to the net-new additions only (not total pack). This would require amending the FR definition. Not recommended — changes the spec contract.

### SOAR Recommended Cap (given current violation exists)

If ARCHITECT decides to proceed with SOAR before fixing actr_buffer, the recommended soar_state size cap is:

**Recommended cap: 50 tokens (200 chars)**

Rationale: goal_stack already uses ~26 tokens for active_goal. Keeping soar_state at 50 tokens or below keeps the SOAR overlay's marginal contribution comparable to goal_stack. This forces:
- operator: name + preference + conditions_matched only (~40 chars)
- matched_rules: top-1 rule only (~80 chars)
- wmes: top-3 WMEs only (~80 chars)
- impasse: None or single string (~5 chars)

A 200-char hard cap on `json.dumps(soar_state)` should be enforced in `soar.py`.

**If actr_buffer is fixed first**, then soar_state can grow to the remaining headroom under the fixed enforcement. With a properly non-duplicating actr_buffer, the budget after all 5 overlays should be approximately:
- goal_stack: +26 tokens
- actr_buffer (fixed, no duplication): ~0 net new (reorganization only)
- gwt_workspace: +1 token
- episodic_memory: +1 token
- soar (recommended cap): +50 tokens
- **Total overhead: ~78 tokens on 565 baseline = 13.8% growth**

This is still technically a violation (FR-CAO-002 says zero growth), but a 13.8% growth from lightweight informational additions is a fundamentally different situation from a 106% growth from content duplication.

### Confidence

```
Recommendation: Fix actr_buffer's structural duplication; cap soar_state at 50 tokens (200 chars) pending that fix
Confidence: 0.92
Evidence: Grade B (direct experiment, reproducible, two baseline sizes tested)
Caveats: gwt_workspace and episodic_memory measurements assume empty persistent state;
         once populated, gwt_workspace can hold up to DEFAULT_MAX_TOKENS=2000 tokens of items
         (its own bound), which would appear directly in the context_pack.
Alternatives: Amend FR-CAO-002 to allow N% overhead (e.g., 25%) — cleaner contract
              that reflects the actual design intent of overlay enrichment.
```

---

## Knowledge Gaps

1. **gwt_workspace populated state:** When workspace items are present (not empty), `gwt_workspace` injects all items directly into context_pack. Its own bound is 2000 tokens. This means a fully populated workspace would add up to 2000 tokens on top of the current 1165 — a severe violation. This was not tested in this experiment.

2. **lida_broadcast:** Skipped as conditional. If it follows the same pattern as actr_buffer (injecting a structured view of existing content), a similar structural duplication issue may exist.

3. **FR-CAO-002 intent ambiguity:** The FR says "MUST NOT exceed" but all overlays add content by design. It is unclear whether the intent is (a) absolute zero growth, (b) growth bounded by a fixed percentage, or (c) growth bounded such that the overlay's own additions do not compound across the stack. This ambiguity should be resolved with ARCHITECT.

---

## Files Produced

- This file: `investigation/iss004-token-budget.md`
- Reasoning journal entries appended to `.specify/squad/staging/reasoning-journal.json`
