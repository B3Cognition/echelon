# Echelon Improvement Specification

**Date:** 2026-03-31
**Source:** Paperclip Reverse Engineering Analysis (6-agent deep dive)
**Target:** Echelon v0.8.0 / Echelon
**Spec ID:** ECHELON-001

---

## 1. Purpose

This specification defines 12 improvements to the Echelon architecture, derived from competitive analysis of Paperclip (paperclipai/paperclip). Each improvement addresses a gap identified in the reverse engineering analysis where Paperclip's infrastructure patterns would materially improve squad reasoning quality, cost efficiency, or operational reliability.

**Design principle:** Adopt Paperclip's infrastructure strengths without losing squad's cognitive depth. Brain stays ours; body gets an upgrade.

---

## 2. Improvements Summary

| ID | Improvement | Priority | Phase | Effort | Dependencies |
|----|------------|----------|-------|--------|--------------|
| IMP-001 | Procedure-as-Prompt rewrite | HIGH | 1 | M | None |
| IMP-002 | Anti-Pattern Tables | HIGH | 1 | S | None |
| IMP-003 | Cost Ledger per dispatch | HIGH | 1 | S | None |
| IMP-004 | 3-Tier Budget Cascade | HIGH | 1 | M | IMP-003 |
| IMP-005 | Tiered Skill Loading | HIGH | 2 | M | None |
| IMP-006 | Memory Decay with Access Tracking | MEDIUM | 2 | M | None |
| IMP-007 | Worked Examples (Few-Shot) | MEDIUM | 2 | M | IMP-001 |
| IMP-008 | Agent Adapter Abstraction | MEDIUM | 3 | L | None |
| IMP-009 | Persistent Run History DB | MEDIUM | 3 | M | IMP-003 |
| IMP-010 | Mandatory Build Output Checklist | HIGH | 1 | S | None |
| IMP-011 | State-Aware Idempotency (Dedup) | MEDIUM | 2 | S | None |
| IMP-012 | Environment Variable Context Injection | MEDIUM | 3 | M | IMP-008 |

**Phases:** 1 = immediate (v0.8.0), 2 = next sprint, 3 = future

---

## 3. Detailed Specifications

### IMP-001: Procedure-as-Prompt Rewrite

**Problem:** Squad agents use persona-based prompts ("You are SCIENTIST who has conducted 100+ investigations..."). Paperclip's evidence shows procedure-based prompts (numbered step runbooks) are more reliable because steps are sequential, concrete, and checkable.

**Evidence:** Paperclip's `skills/paperclip/SKILL.md` — 368-line 9-step heartbeat procedure. Every step has exact API calls with curl syntax. Agent identity is secondary to procedure.

**Specification:**

For each of these high-dispatch agents, add a numbered **Core Procedure** section after the Role section:

| Agent | Procedure Steps |
|-------|----------------|
| INVESTIGATOR | 1. Read question 2. Research (web + code) 3. Grade sources (A-E) 4. Hypothesize 5. Experiment (if feasible) 6. Measure 7. Synthesize 8. Recommend |
| ARCHITECT | 1. Read spec + constraints 2. Research tech options (Context7) 3. Select stack (with ADR) 4. Design data model 5. Define API contracts 6. Document cross-cutting concerns 7. Write plan.md |
| ORCHESTRATOR | 1. Read plan + test strategy 2. Decompose into phases 3. Map dependencies 4. Identify critical path 5. Assign risk per task 6. Write tasks.md + critical-path.md |
| CARTOGRAPHER | 1. Read staging artifacts 2. Call /speckit.specify 3. Move staging to spec dir 4. Write user stories (Given/When/Then) 5. Cross-reference glossary 6. Write spec.md |
| SAGE | 1. Read target artifacts 2. Run Understanding validate (WHY2/3 only) 3. Run per-requirement analysis 4. Challenge each assumption 5. Score findings (CRITICAL/HIGH/MEDIUM/LOW) 6. Write issues.md + quality-gates.md |

**Format:** Each step must include:
- What to do (action)
- What tool/API to use (concrete)
- What output to produce (verifiable)
- What to do if it fails (fallback)

**Acceptance criteria:**
- [ ] AC-1: 5 agents have numbered Core Procedure sections
- [ ] AC-2: Each step has action + tool + output + fallback
- [ ] AC-3: Existing persona/role sections are preserved (procedure supplements, doesn't replace)
- [ ] AC-4: NEVER rules remain as constraints on procedure steps

---

### IMP-002: Anti-Pattern Tables

**Problem:** NEVER rules are scattered across 42 agent prompts in prose format. Hard to scan, no reasoning provided, difficult for LLM to generalize to novel situations.

**Evidence:** Paperclip's API reference uses 3-column tables: Mistake | Why it's wrong | What to do instead. More scannable and provides reasoning for each prohibition.

**Specification:**

For each agent, consolidate all NEVER rules and known failure modes into a single **Anti-Pattern Table**:

```markdown
## Anti-Patterns

| Mistake | Why it's wrong | Do this instead |
|---------|---------------|----------------|
| Rewrite specs when finding issues | Role violation: WHY is read-only on specs | Write to issues.md, route to CARTOGRAPHER |
| Skip calibration check | Historical accuracy data exists and prevents known failure modes | Always read calibration-profile.yaml first |
| Estimate without correction factor | Uncalibrated estimates are 1.4x off on average | Apply domain correction from calibration-profile.yaml |
```

**Rules:**
1. Keep existing NEVER rules as the source — transform them into table rows
2. Add a "Why" column for every rule (cite evidence: prior incident, role boundary, data corruption risk)
3. Add a "Do this instead" column with the correct action
4. Place the table immediately after the Role section, before the process steps
5. Maximum 10 rows per agent (consolidate related rules)

**Acceptance criteria:**
- [ ] AC-1: All 42 agents have Anti-Pattern Tables
- [ ] AC-2: Every row has all 3 columns filled
- [ ] AC-3: Existing NEVER rules section can be removed (table replaces it)
- [ ] AC-4: No new rules invented — only transform existing ones

---

### IMP-003: Cost Ledger Per Dispatch

**Problem:** Squad has token budget in config (`token_budget_k: 1000`) and COMMANDER tracks estimated token usage, but no actual cost measurement exists. Banzai mode with opus-everywhere burns real money with no visibility.

**Evidence:** Paperclip's `cost_events` table tracks per-invocation: agent_id, provider, model, input_tokens, output_tokens, cost_cents. Full attribution chain: token → run → task → project → goal.

**Specification:**

Create `.specify/squad/cost-ledger.json`:

```json
{
  "run_id": "squad-1711878000",
  "currency": "USD",
  "total_cost_cents": 0,
  "dispatches": [
    {
      "dispatch_id": "SCOUT-1",
      "agent": "SCOUT",
      "phase": "discover",
      "model": "opus",
      "started_at": "ISO-8601",
      "completed_at": "ISO-8601",
      "input_tokens": 45000,
      "output_tokens": 12000,
      "cached_input_tokens": 30000,
      "estimated_cost_cents": 285,
      "billing_type": "metered_api"
    }
  ],
  "by_agent": { "SCOUT": 285, "SAGE": 420 },
  "by_phase": { "discover": 285, "why2": 420 },
  "by_model": { "opus": 705 }
}
```

**COMMANDER integration:**
1. After every agent dispatch completes, append a dispatch record to the ledger
2. Token counts come from the Agent tool response metadata (if available) or are estimated from prompt + response character counts using model-specific rates
3. Cost rates: opus = $15/M input, $75/M output; sonnet = $3/M input, $15/M output; haiku = $0.25/M input, $1.25/M output (cached inputs at 10% rate)
4. Update `by_agent`, `by_phase`, `by_model` aggregates
5. Print cumulative cost in the final summary

**Acceptance criteria:**
- [ ] AC-1: cost-ledger.json created at INIT
- [ ] AC-2: Every dispatch appends a record with agent, model, tokens, cost
- [ ] AC-3: Final summary shows total cost in dollars
- [ ] AC-4: Cost rates are configurable in squad-config.yml

---

### IMP-004: 3-Tier Budget Cascade

**Problem:** Squad has a single `token_budget_k` threshold. No per-agent limits, no per-phase limits, no soft warnings, no auto-pause. A single runaway agent can consume the entire budget.

**Evidence:** Paperclip's `budgets.ts` (958 lines) implements company > agent > project cascade with soft warn at 80% and hard-stop auto-pause at 100%.

**Specification:**

Add to `squad-config.yml`:

```yaml
budget:
  # Existing tier percentages remain...
  
  # NEW: Per-agent hard caps (percentage of total budget)
  per_agent_cap_percent: 40          # No single agent > 40% of total
  
  # NEW: Soft warning threshold
  soft_warn_percent: 80              # Log warning at 80% consumed
  
  # NEW: Hard-stop threshold  
  hard_stop_percent: 100             # Force finalize at 100%
  
  # NEW: Per-phase budgets (override tier percentages)
  phase_budgets:
    understand: 25                   # Phase 1: SCOUT, SYNTHESIZER, WHY1
    decide: 20                       # Phase 2: WHAT, WHY2, ASSESS
    solution: 25                     # Phase 3: HOW, SENTINEL, ORCHESTRATOR, specialists
    finalize: 10                     # Phase 4: GROUND, MIRROR, ADAPTIVE, AUDITOR
    reserve: 5                       # Emergency reserve
```

**COMMANDER enforcement:**
1. Before every dispatch, read cost-ledger.json (IMP-003) and check:
   - Total budget: if `total_cost_cents > hard_stop_percent * budget_limit` → force finalize
   - Agent budget: if `by_agent[AGENT] > per_agent_cap_percent * budget_limit` → skip agent, log
   - Phase budget: if `by_phase[PHASE] > phase_budgets[PHASE] * budget_limit` → skip remaining agents in phase
2. At `soft_warn_percent`, log a `BUDGET_WARNING` entry in reasoning-journal.json and print to terminal
3. At `hard_stop_percent`, enter forced finalize (minimum: GROUND + AUDITOR)

**Acceptance criteria:**
- [ ] AC-1: COMMANDER checks budget before every dispatch
- [ ] AC-2: Soft warning logged at 80%
- [ ] AC-3: Force finalize at 100%
- [ ] AC-4: No single agent exceeds 40% cap
- [ ] AC-5: Per-phase budgets enforced

---

### IMP-005: Tiered Skill Loading

**Problem:** All 42 agent prompts are conceptually "loaded" into the orchestrator's context when COMMANDER decides which agent to dispatch. This is context-inefficient — COMMANDER only needs to know WHAT each agent does (1-line description), not HOW it does it (full 200-line prompt).

**Evidence:** Paperclip's skill system uses YAML frontmatter `description` as routing logic (always in context), with full SKILL.md content loaded only when the agent is actually dispatched.

**Specification:**

The `agents.yaml` registry already has `role` fields for each agent. Enhance COMMANDER's routing to use ONLY the registry metadata (codename, function, role, when, inputs, outputs) for dispatch decisions. The full agent `.md` file is read ONLY by the dispatched subagent, never by COMMANDER.

**Current flow (wasteful):**
```
COMMANDER reads agents.yaml → decides to dispatch SCOUT → reads scout.md → passes to Agent tool
```

**New flow (efficient):**
```
COMMANDER reads agents.yaml (metadata only) → decides to dispatch SCOUT → Agent tool reads scout.md itself
```

This is already partially the case (Agent tool prompts say "Read the file agents/exploration/scout.md"), but COMMANDER's routing logic sometimes reads agent files to make decisions. Enforce that COMMANDER NEVER reads agent `.md` files — only `agents.yaml` metadata.

**Acceptance criteria:**
- [ ] AC-1: COMMANDER routing uses only agents.yaml metadata
- [ ] AC-2: Agent .md files are read only by the dispatched subagent
- [ ] AC-3: agents.yaml `role` and `when` fields are sufficient for all routing decisions
- [ ] AC-4: Document this as a rule in commander.md

---

### IMP-006: Memory Decay with Access Tracking

**Problem:** Belief register entries and knowledge-base entries have no usage tracking. Stale beliefs persist indefinitely. Frequently-accessed beliefs aren't prioritized.

**Evidence:** Paperclip's PARA memory system has `last_accessed` + `access_count` fields with hot/warm/cold tiers (7/30/30+ days). Facts are never deleted, only superseded.

**Specification:**

Add to `knowledge-base/calibration-profile.yaml` entries:

```yaml
- domain: backend
  accuracy: 0.72
  correction_factor: 1.4
  last_accessed: "2026-03-31"    # NEW
  access_count: 7                 # NEW
  recency_tier: hot               # NEW: hot (7d) | warm (8-30d) | cold (30+d)
```

Add to belief register entries in agent prompts:

```markdown
| Belief ID | Claim | Verified | Expires | Confidence | Access Count | Last Used |
```

**AUDITOR responsibilities:**
1. When AUDITOR reads calibration-profile.yaml, increment `access_count` and update `last_accessed`
2. Compute `recency_tier` from `last_accessed`: hot (within 7 days), warm (8-30 days), cold (30+ days)
3. Cold entries are deprioritized in calibration injection (included but marked `[COLD]`)
4. Entries are never deleted — only superseded with `superseded_by` reference

**Acceptance criteria:**
- [ ] AC-1: calibration-profile.yaml entries have access_count, last_accessed, recency_tier
- [ ] AC-2: AUDITOR updates access tracking on every read
- [ ] AC-3: Cold entries marked in calibration injection
- [ ] AC-4: No entries are ever deleted

---

### IMP-007: Worked Examples (Few-Shot Training)

**Problem:** Agent prompts describe WHAT to do but don't show realistic examples of complete input/output sequences. LLMs perform better with few-shot examples.

**Evidence:** Paperclip's API reference includes two complete worked heartbeat simulations (IC agent and Manager agent) showing exact API call sequences with realistic response data.

**Specification:**

For each of the 5 procedure-rewritten agents (IMP-001), add a `## Worked Example` section showing a complete realistic execution:

**INVESTIGATOR example:**
```markdown
## Worked Example

**Question:** "Can PostgreSQL handle 10K concurrent WebSocket connections?"

**Step 1 — Research:**
WebSearch: "postgresql connection pooling limits production"
→ Grade B: Official PostgreSQL docs confirm max_connections default 100

**Step 2 — Grade sources:**
| Source | Grade | Finding |
|--------|-------|---------|
| PostgreSQL docs | B | max_connections=100 default, practical limit ~500 per node |
| PgBouncer docs | B | Connection pooling supports 10K+ logical connections |
| StackOverflow | C | Production reports of 5K connections with PgBouncer |

**Step 3 — Synthesize:**
Direct PostgreSQL: NO (max ~500). With PgBouncer: YES (10K+ proven).
Confidence: 0.85. Evidence grade: B.

**Step 4 — Recommend:**
"Use PgBouncer connection pooling. Budget 2 PgBouncer instances for 10K target."
```

**Acceptance criteria:**
- [ ] AC-1: 5 agents have worked examples
- [ ] AC-2: Examples show realistic inputs AND outputs
- [ ] AC-3: Examples demonstrate the numbered procedure from IMP-001
- [ ] AC-4: Examples include error/edge cases (not just happy path)

---

### IMP-008: Agent Adapter Abstraction

**Problem:** Squad dispatches all agents via Claude Code's Agent tool — single-provider only. Paperclip supports 10 different agent runtimes.

**Evidence:** Paperclip's `packages/adapters/` with `ServerAdapterModule` interface: execute(), testEnvironment(), sessionCodec, listSkills, models.

**Specification:**

Define an adapter interface in `config-template.yml`:

```yaml
execution:
  models:
    control: opus           # Provider: claude (default)
    exploration: opus
    feasibility: sonnet
    solution: opus
    specialists: opus
    build: sonnet
    learning: haiku
    verification: opus
  
  # NEW: Adapter configuration
  adapters:
    claude:
      type: claude_code_agent_tool    # Default — uses Agent tool
      available_models: [opus, sonnet, haiku]
    # Future adapters:
    # gemini:
    #   type: gemini_cli
    #   binary: gemini
    #   available_models: [2.5-pro, 2.5-flash]
    # local:
    #   type: ollama
    #   endpoint: http://localhost:11434
    #   available_models: [llama-70b, qwen-72b]
```

**Phase 1 (v0.8.0):** Define the interface only. All dispatch goes through claude_code_agent_tool.
**Phase 2 (v0.9.0):** Implement gemini adapter.
**Phase 3 (v1.0.0):** Implement local model adapter for learning-tier agents.

**Acceptance criteria:**
- [ ] AC-1: Adapter config section exists in config-template.yml
- [ ] AC-2: COMMANDER reads adapter config and routes through the correct adapter
- [ ] AC-3: Default behavior unchanged (all Claude via Agent tool)
- [ ] AC-4: Architecture supports adding new adapters without changing COMMANDER

---

### IMP-009: Persistent Run History DB

**Problem:** Run history is reconstructed from flat files (state.json, reasoning-journal.json) by AUDITOR/ADAPTIVE each time. No queryable cross-run analytics.

**Evidence:** Paperclip's PostgreSQL with 59 tables provides instant queries on agent performance, cost trends, and historical comparisons.

**Specification:**

Create `.specify/squad/history.json` as a lightweight append-only run log:

```json
{
  "runs": [
    {
      "run_id": "squad-1711878000",
      "started_at": "ISO-8601",
      "completed_at": "ISO-8601",
      "status": "done",
      "mode": "brownfield",
      "iterations": 2,
      "total_cost_cents": 4250,
      "quality_scores": { "overall": 0.82, "structure": 0.78 },
      "agents_dispatched": 18,
      "specialists_summoned": ["GUARDIAN", "SENTINEL", "INVESTIGATOR"],
      "issues_found": { "CRITICAL": 0, "HIGH": 2, "MEDIUM": 5 },
      "convergence": "natural",
      "spec_id": "014",
      "feature": "paperclip-adoption"
    }
  ]
}
```

**COMMANDER responsibilities:**
1. At INIT, read history.json for prior run data
2. At FINALIZE, append current run summary
3. AUDITOR reads history.json for trend analysis instead of parsing archives

**Acceptance criteria:**
- [ ] AC-1: history.json created if missing
- [ ] AC-2: Every completed run appends a summary
- [ ] AC-3: AUDITOR uses history.json for cross-run analytics
- [ ] AC-4: History survives across runs (append-only, never wiped)

---

### IMP-010: Mandatory Build Output Checklist

**Problem:** Build summary sometimes outputs next steps and sometimes doesn't. No consistent "here's what you need to do" section.

**Evidence:** Already implemented in PR #42 (Risk Acceptance Protocol). This spec formalizes the requirement.

**Specification:**

Both `echelon.run.md` and `echelon.build.md` final summaries MUST include:

```
──────────────────────────────────────────
  HUMAN ACTIONS REQUIRED
──────────────────────────────────────────
  {MANDATORY section — always printed}
  {If empty: "None — squad resolved all items autonomously."}
  {Checklist format with [ ] for each action}
──────────────────────────────────────────
```

This section is NEVER omitted. COMMANDER must scan all artifacts for:
1. `HUMAN_REVIEW_REQUIRED` flags (from GUARDIAN)
2. `ESCALATE` items in risk-acceptance-log.md
3. Unresolved unknowns from unknowns.md
4. BLOCKED tasks
5. Manual verification needs
6. Deployment/release actions

**Acceptance criteria:**
- [ ] AC-1: Section appears in every run summary (already in PR #42)
- [ ] AC-2: Section appears in every build summary (already in PR #42)
- [ ] AC-3: COMMANDER scans all artifacts to populate the checklist
- [ ] AC-4: Empty state explicitly says "None — resolved autonomously"

---

### IMP-011: State-Aware Idempotency (Dedup)

**Problem:** When squad agents get stuck, they can loop on the same reasoning — repeatedly flagging the same issues or producing the same output.

**Evidence:** Paperclip's blocked-task dedup pattern: "Before working on a blocked task, fetch its comment thread. If your most recent comment was a blocked-status update AND no new comments since, skip the task entirely."

**Specification:**

Add a **last-action registry** to state.json:

```json
{
  "last_actions": {
    "SAGE": {
      "action": "WHY2_spec_validation",
      "result": "3_CRITICAL_issues",
      "issues_hash": "sha256:abc123",
      "timestamp": "ISO-8601"
    }
  }
}
```

**COMMANDER check before re-dispatch:**
1. If dispatching the same agent for the same task type, check `last_actions[AGENT]`
2. If the inputs haven't changed (hash of input artifacts matches), skip the dispatch
3. Log: "DEDUP: Skipping {AGENT} — inputs unchanged since last dispatch"
4. Exception: if another agent has modified the target artifacts since the last dispatch, allow re-dispatch

**Acceptance criteria:**
- [ ] AC-1: last_actions tracked in state.json
- [ ] AC-2: COMMANDER checks before re-dispatch
- [ ] AC-3: Skipped dispatches logged in reasoning-journal.json
- [ ] AC-4: Changed inputs bypass the dedup check

---

### IMP-012: Environment Variable Context Injection

**Problem:** Calibration data, endocrine values, and run metadata are injected as prompt text, consuming tokens on every dispatch.

**Evidence:** Paperclip passes 15+ context values via environment variables (PAPERCLIP_AGENT_ID, PAPERCLIP_WAKE_REASON, etc.). Token-efficient; keeps prompt stable across invocations.

**Specification:**

Define standard environment variables for agent dispatch:

| Variable | Value | Purpose |
|----------|-------|---------|
| `SQUAD_RUN_ID` | run_id from state.json | Run identification |
| `SQUAD_AGENT` | Agent codename | Self-identification |
| `SQUAD_PHASE` | Current phase | Phase context |
| `SQUAD_MODE` | greenfield/brownfield | Project mode |
| `SQUAD_ITERATION` | Current iteration number | Loop tracking |
| `SQUAD_BUDGET_PERCENT` | Budget consumed % | Cost awareness |
| `SQUAD_SPEC_DIR` | specs/{NNN}-{feature}/ | Output directory |
| `SQUAD_CALIBRATION_SCORE` | Last quality score | Calibration context |
| `SQUAD_ENDOCRINE_PHASE` | Endocrine phase (1-4) | Hormone system phase |

**Implementation:** These would require Agent tool support for environment variable passing, which may not be available. If not available:
- **Fallback:** Continue using prompt injection but standardize the format as a single compact block
- **Future:** When Claude Code Agent tool supports env vars, switch to that path

**Acceptance criteria:**
- [ ] AC-1: Standard env var names defined
- [ ] AC-2: If Agent tool supports env vars → use them
- [ ] AC-3: If not → compact prompt injection block (max 5 lines)
- [ ] AC-4: Calibration + endocrine data in standardized format either way

---

## 4. Implementation Phases

### Phase 1: v0.8.0 (Immediate — next PR)

| ID | Improvement | Files Changed |
|----|------------|---------------|
| IMP-001 | Procedure-as-Prompt | 5 agent .md files |
| IMP-002 | Anti-Pattern Tables | 42 agent .md files |
| IMP-003 | Cost Ledger | commands/echelon.run.md, build.md |
| IMP-004 | Budget Cascade | config-template.yml, commander.md |
| IMP-010 | Mandatory Output Checklist | Already in PR #42 |

### Phase 2: v0.9.0

| ID | Improvement | Files Changed |
|----|------------|---------------|
| IMP-005 | Tiered Skill Loading | commander.md, agents.yaml |
| IMP-006 | Memory Decay | calibration-profile.yaml, auditor.md |
| IMP-007 | Worked Examples | 5 agent .md files |
| IMP-011 | State-Aware Idempotency | commander.md, state-schema.json |

### Phase 3: v1.0.0

| ID | Improvement | Files Changed |
|----|------------|---------------|
| IMP-008 | Agent Adapter Abstraction | config-template.yml, commander.md |
| IMP-009 | Persistent Run History | commander.md, auditor.md |
| IMP-012 | Env Var Context Injection | commander.md, all agent .md files |

---

## 5. Success Metrics

| Metric | Current | Target | How to Measure |
|--------|---------|--------|----------------|
| Agent dispatch reliability | Unknown | 95%+ first-pass success | Track in cost-ledger.json |
| Cost visibility | 0% | 100% of dispatches tracked | cost-ledger.json completeness |
| Budget overrun incidents | Unknown | 0 (hard-stop prevents) | budget cascade enforcement |
| Cross-run learning speed | Manual artifact parsing | Instant (history.json query) | AUDITOR query time |
| Duplicate dispatch waste | Unknown | <5% of total dispatches | Dedup skip rate |
| Context token efficiency | All 42 prompts conceptually loaded | Only dispatched agent loads full prompt | Token savings measurement |

---

## 6. Non-Goals

These Paperclip features are explicitly NOT adopted:

1. **Persistent server** — Squad remains a CLI tool, not a web service
2. **PostgreSQL** — Flat files (JSON/YAML) remain the state layer
3. **React UI dashboard** — RADAR serves this need; no new UI
4. **Multi-company isolation** — Single-project model retained
5. **Plugin marketplace** — spec-kit extension system is sufficient
6. **Approval workflow UI** — COMMANDER's guided/semi/banzai modes serve this
7. **Org chart hierarchy** — Flat specialist model retained (no reports_to tree)
8. **Heartbeat scheduling** — Squad runs are one-shot, not 24/7
9. **Agent API key auth** — Agents run in-process, no auth needed
