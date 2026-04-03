# ISS-002: Pre-Overlay Context Pack Key Inventory

**Investigator:** INVESTIGATOR (SCIENTIST)
**Date:** 2026-04-03
**Spec:** 018-soar-overlay
**Files examined:**
- `COMMANDER.md` — Pre-Dispatch Sequence
- `scripts/ca/goal_stack.py`
- `scripts/ca/actr_buffer.py`
- `scripts/ca/gwt_workspace.py`
- `scripts/ca/episodic_memory.py`
- `scripts/bash/lida_broadcast.sh`

---

## Step 1: QUESTION

**What exactly do we not know?**
What is the complete set of keys that exist in `context_pack` by the time the SOAR
overlay chain would run? Which of these keys are stable (present on every dispatch)
vs conditional (present only sometimes)?

**What decision depends on this answer?**
SOAR seed production rules must condition only on keys that are reliably present.
Conditioning on an absent key causes either a KeyError or a silent rule miss. The
inventory determines which keys are safe anchors for production rule LHS conditions.

**What would "good enough" evidence look like?**
Direct inspection of the five overlay modules and COMMANDER.md, tracing every
`enriched[key] = ...` assignment and every `if os.path.isfile(...)` guard.

**What is the cost of being wrong?**
Production rules that condition on missing keys produce silent failures. In SOAR
semantics, a rule with an unsatisfied condition simply does not fire — producing no
enrichment and no error. The cost is a subtly broken overlay that appears to work but
enriches context on fewer cycles than expected.

---

## Step 2–3: RESEARCH AND EVIDENCE

### Pre-dispatch sequence execution order (COMMANDER.md, Grade B)

```
1. goal_stack.enrich_context(context_pack, run_id)
2. actr_buffer.enrich_context(context_pack, run_id)
3. LIDA file-check + inject (conditional)
4. gwt_workspace.enrich_context(context_pack, run_id)
5. episodic_memory.enrich_context(context_pack, run_id, agent_type)
```

The SOAR overlay, if inserted into this chain, would run as overlay step 6 — after
all five CA enrichments have been applied. The base context_pack available to the SOAR
overlay therefore contains: whatever COMMANDER provided as the initial pack, plus the
five overlay additions analyzed below.

### Key inventory by source

#### 1. `goal_stack.py` → `active_goal` (Grade B: source code)

```python
# From goal_stack.enrich_context():
enriched["active_goal"] = active_goal
# active_goal = {"goal_text": str, "priority": float, "depth": int}
# OR (when no ACTIVE goals remain):
# active_goal = {"goal_text": "No active goal", "priority": 0.0, "depth": 0}
```

**Always present:** YES. The function always injects `active_goal`. When the stack is
empty or uninitialized, `_init_stack` creates a root goal, so there is always at least
one ACTIVE goal on the first dispatch. If all goals are DONE (edge case: all goals
completed before dispatch), the fallback sentinel value is used. In both cases the key
exists.

**Type:** `dict` with keys `{goal_text: str, priority: float, depth: int}`

#### 2. `actr_buffer.py` → `actr_buffers` (Grade B: source code)

```python
# From actr_buffer.enrich_context():
enriched["actr_buffers"] = {
    "declarative": [...],   # list of {key, value} from context_pack
    "procedural": [...],    # list of {key, value}
    "goal": [...],          # list of {key, value}
    "imaginal": [...],      # list of {key, value}
    "retrieval_buffer": [...],  # top-3 TF-IDF excerpts, may be empty list
}
```

**Always present:** YES. The function always creates the dict and assigns it.
`retrieval_buffer` may be an empty list (when declarative has fewer than 2 entries),
but the outer key `actr_buffers` is always injected.

**Type:** `dict` with five sub-keys, each a `list`.

Note: `actr_buffers` is a restructuring of the existing `context_pack` keys. It does
not add new factual content — it reorganizes what was already there into typed slots.

#### 3. LIDA Broadcast (COMMANDER.md inline code) → `lida_broadcast` (Grade B: source code)

```python
if os.path.isfile(lida_payload_path):
    # ...
    context_pack["lida_broadcast"] = lida_payload
```

**Always present:** NO. Conditional on `.specify/squad/lida-payload.json` existing
at dispatch time. See ISS-001 for full analysis.

**Type when present:** `dict` (arbitrary JSON structure, caller-defined)

#### 4. `gwt_workspace.py` → `gwt_workspace` (Grade B: source code)

```python
# From gwt_workspace.enrich_context():
enriched["gwt_workspace"] = items
# items = list loaded from gwt-workspace-<run_id>.json, or [] if file absent
```

**Always present:** YES. The key is always injected. On the first dispatch of a fresh
run (before any `add_to_workspace` calls), the file does not exist, so `items` is `[]`.
The key is still injected as an empty list.

**Type:** `list` of `{text: str, timestamp: float}` dicts. May be `[]` on first dispatch.

**Stability caveat:** On the very first dispatch, `gwt_workspace` is always `[]` because
no post-dispatch workspace writes have occurred yet. Production rules conditioning on
`gwt_workspace` being non-empty will not fire on the first dispatch.

#### 5. `episodic_memory.py` → `episodic_prior_artifact` (Grade B: source code)

```python
# From episodic_memory.enrich_context():
enriched["episodic_prior_artifact"] = prior_artifact
# prior_artifact = {artifact_path, stage_timestamp, artifact_category}
#               OR None (when no prior artifact exists for this agent_type)
```

**Always present:** YES — the key is always injected. However, the **value** is `None`
when no artifact has been indexed for this agent type in the current run. On first
dispatch of any agent type, the value is `None`.

**Type:** `dict` with `{artifact_path: str, stage_timestamp: float, artifact_category: str}`
or `None`.

**Stability caveat:** Rules that condition on `episodic_prior_artifact` being non-None
will not fire on the first dispatch for each agent type.

---

## Step 4: HYPOTHESIS

**H2:** The only keys that are unconditionally present (key exists with a non-None,
non-empty value) on every dispatch are `active_goal` and `actr_buffers`.

**H2 is falsifiable:** If another overlay injects a key unconditionally with a useful
value. Inspection confirms: `gwt_workspace` can be `[]`, `episodic_prior_artifact`
can be `None`, `lida_broadcast` can be absent. `active_goal` always has a meaningful
value (sentinel or real). `actr_buffers` always has the structural dict.

**H2 verdict: CONFIRMED** with one precision: `active_goal` is the only key that
always carries a semantically meaningful value. `actr_buffers` is always present as a
structural wrapper but its internal buffers may be empty lists if the source pack has
no classifiable keys yet.

---

## Step 7: SYNTHESIS — Complete WME Inventory Table

| Key | Source | Always present? | Value when absent/empty | Type | Safe for SOAR rule conditions? |
|-----|--------|-----------------|-------------------------|------|-------------------------------|
| `active_goal` | `goal_stack.py` | **YES** | Sentinel `{goal_text: "No active goal", priority: 0.0, depth: 0}` | `dict` | **YES — primary anchor** |
| `actr_buffers` | `actr_buffer.py` | **YES** | Structural dict with empty sub-lists | `dict` | **YES — structural, sub-keys may be empty lists** |
| `gwt_workspace` | `gwt_workspace.py` | **YES** (key always set) | `[]` on first dispatch | `list` | **CONDITIONAL — safe to reference key, unsafe to assume non-empty** |
| `episodic_prior_artifact` | `episodic_memory.py` | **YES** (key always set) | `None` on first dispatch for agent type | `dict` or `None` | **CONDITIONAL — must null-guard** |
| `lida_broadcast` | `lida_broadcast.sh` / COMMANDER inline | **NO** | Key absent | `dict` | **OPPORTUNISTIC only — see ISS-001** |
| _(initial context_pack keys)_ | COMMANDER / caller | Unknown without caller inspection | Depends on caller | varies | Unknown without further inspection |

---

## Step 8: RECOMMENDATION

```
Recommendation: SOAR seed production rules in spec 018 should use the following
                stability tiers to determine which keys are valid LHS conditions:

TIER 1 — SAFE ANCHORS (condition freely):
  - active_goal           Always present, always has meaningful value.
                          active_goal.goal_text, active_goal.priority, active_goal.depth
                          are all reliable sub-key conditions.

TIER 2 — PRESENT BUT POSSIBLY EMPTY (condition with guard):
  - actr_buffers          Always present structurally. Sub-key contents depend on
                          what was in the original context_pack. Safe to reference
                          the outer key; unsafe to assume any sub-list is non-empty
                          without a length check.
  - gwt_workspace         Always present as a key. Value may be [] on first dispatch.
                          Rules conditioning on non-empty workspace must handle [].
  - episodic_prior_artifact  Always present as a key. Value may be None. Rules must
                          null-guard before accessing sub-keys.

TIER 3 — OPPORTUNISTIC (only fire when explicitly triggered):
  - lida_broadcast        Absent in the majority of dispatch cycles. See ISS-001.
                          Rules may use this as a context modifier but must not
                          depend on it for core behavior.

Confidence: 0.95
Evidence: Grade B — direct source code inspection of all five overlay modules and
          COMMANDER.md. Injection paths are unambiguous in all five files.
Caveats: The initial context_pack keys (supplied by COMMANDER's caller before the
         overlay chain begins) are not inventoried here — they depend on the specific
         agent invocation pattern and are not visible in the overlay modules themselves.
         SOAR rules that condition on caller-supplied keys require a separate
         investigation of the COMMANDER dispatch call sites.
Alternatives: If more keys are needed as reliable anchors, the goal_stack could be
              extended to carry richer structured state (e.g., a typed priority queue
              or constraint set), which would remain in Tier 1.
```

---

## Summary

The pre-overlay `context_pack` contains five reliably-injected keys after all CA
overlays run. Of these, only `active_goal` is a fully reliable, semantically meaningful
WME on every dispatch. `actr_buffers`, `gwt_workspace`, and `episodic_prior_artifact`
are always-present as keys but require guards for content. `lida_broadcast` is absent
in normal operation and must be treated as opportunistic.

**For spec 018 SOAR seed rules, `active_goal` is the primary safe condition anchor.**
