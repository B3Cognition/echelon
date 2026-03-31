# Paperclip Reverse Engineering Analysis

**Date:** 2026-03-31
**Repo:** https://github.com/paperclipai/paperclip
**Target:** Novelty adoption for cognitive-squad / echelon
**Agents dispatched:** 6 (3 broad + 3 deep dive)

---

## Executive Summary

**Paperclip** = 1300-file TypeScript monorepo (Node.js + React + PostgreSQL) for orchestrating "zero-human AI companies." 59 DB tables, 10 agent adapters, 21 plugin services, 40+ page React UI.

**Cognitive Squad** = 367-file prompt-based cognitive architecture. 42 specialized agents, 7 layers, 4 phases, endocrine system, belief registers, calibration learning.

**They are complementary, not competitive.** Paperclip is thick infrastructure + thin agent logic. Squad is thick cognitive logic + thin infrastructure.

---

## TOP 8 NOVELTIES TO ADOPT FOR ECHELON

| # | Feature | Source | Priority | Effort |
|---|---------|--------|----------|--------|
| 1 | **Procedure-as-Prompt** — numbered step runbooks instead of persona descriptions | `skills/paperclip/SKILL.md` (368 lines, 9 steps) | HIGH | Medium — rewrite key agent prompts |
| 2 | **Anti-Pattern Tables** — 3-column format (Mistake \| Why \| Fix) vs scattered NEVER rules | `skills/paperclip/references/api-reference.md` | HIGH | Small — consolidate existing rules |
| 3 | **Cost tracking per dispatch** — tokens + dollars, per agent/task/project/goal attribution chain | `server/src/services/costs.ts`, `budgets.ts` (958 lines) | HIGH | Small — JSON ledger |
| 4 | **3-tier budget cascade** — company > agent > project with soft warn + hard auto-pause | `server/src/services/budgets.ts` | HIGH | Medium — COMMANDER enforcement |
| 5 | **Tiered skill loading** — description-as-router (always in context) + full prompt on demand | Adapter skill injection pattern | HIGH | Medium — reduces 42-prompt context bloat |
| 6 | **Memory decay with access tracking** — hot/warm/cold tiers, access_count resists decay | `skills/para-memory-files/SKILL.md` | MEDIUM | Medium — enhance belief register |
| 7 | **Worked examples as few-shot training** — complete simulation sequences in each agent prompt | `skills/paperclip/references/api-reference.md` (IC + Manager examples) | MEDIUM | Medium — add per-specialist examples |
| 8 | **Agent adapter abstraction** — multi-provider dispatch (Claude, Gemini, Codex, local models) | `packages/adapters/` (10 adapters) | MEDIUM | Large — interface definition + wiring |

---

## What Paperclip Has That Cognitive Squad Doesn't

### 1. Persistent Server with PostgreSQL State
Full Node.js + Express REST API with 60+ DB tables (Drizzle ORM). Agents, issues, costs, approvals, plugins all persisted across reboots.
- Evidence: `server/src/services/` (65+ service files), `packages/db/src/schema/` (60+ schema files)

### 2. Multi-Agent Adapter Registry
Pluggable adapters for Claude CLI, Codex CLI, Cursor, Gemini, OpenCode, OpenClaw, HTTP, generic process. Each adapter has execute/test/session/skills/models interfaces.
- Evidence: `server/src/adapters/registry.ts` (imports 10 adapter packages)
- Evidence: `server/src/adapters/types.ts` — exports `ServerAdapterModule` with 29 type aliases

### 3. Budget/Cost Enforcement with Auto-Pause
Monthly budget windows per agent/project/company, threshold policies (warn/pause/hard-stop), budget incidents with resolution workflow, atomic cost tracking in cents.
- Evidence: `server/src/services/budgets.ts` (~958 lines) — `BudgetPolicy`, `BudgetIncident`, `BudgetEnforcementScope`
- Evidence: `server/src/services/costs.ts` — `getMonthlySpendTotal()`, per-agent cost events

### 4. Finance Ledger
Full debit/credit double-entry finance events, with estimated vs actual tracking, scoped to agent/issue/project/goal/heartbeat run.
- Evidence: `server/src/services/finance.ts` — debit/credit expressions, multi-entity linkage

### 5. React UI Dashboard
40+ pages: Dashboard, Agents, Issues, Goals, OrgChart, Costs, Approvals, Routines, PluginManager, CompanyExport/Import, Inbox, etc.
- Evidence: `ui/src/pages/` — 40+ page components

### 6. Org Chart with SVG Rendering
Server-side SVG generation with 5 visual themes (monochrome/nebula/circuit/warmth/schematic), hierarchical layout with emoji avatars, PNG export via sharp.
- Evidence: `server/src/routes/org-chart-svg.ts`

### 7. Heartbeat Scheduling System
Agents wake on timer/assignment/on-demand/automation triggers, with wakeup coalescing, session resume across heartbeats, configurable intervals.
- Evidence: `server/src/services/heartbeat.ts` (~3950 lines — largest service file)

### 8. Approval/Governance Gates
Board-level approval workflow with pending/approved/rejected/revision_requested states, comment threads, hire approval hooks.
- Evidence: `server/src/services/approvals.ts` (~273 lines)

### 9. Company Portability (Export/Import)
Full company serialization with secret scrubbing, collision handling, manifest entries for agents/projects/skills/routines/issues.
- Evidence: `server/src/services/company-portability.ts`

### 10. Plugin System
Full plugin lifecycle: registry, config, secrets, sandboxed runtime, job scheduler, event bus, webhook deliveries, log retention, worker manager, UI hosting. 21 server-side service files.
- Evidence: `server/src/services/plugin-*.ts` — 21 plugin-related service files
- 40+ fine-grained capabilities enforced at install + runtime
- Process-isolated workers via JSON-RPC 2.0 over stdio
- VM sandbox + SSRF protection + crash recovery with exponential backoff

### 11. Goal Hierarchy with Decomposition
Goals table with parent/child relationships (`parentId` self-referential FK), levels (company/project/task), owner agent, status tracking.
- Evidence: `packages/db/src/schema/goals.ts`

### 12. Scheduled Routines (Cron)
Cron-based recurring jobs with catch-up policies, concurrency policies, trigger signing, routine run tracking.
- Evidence: `server/src/services/routines.ts`

### 13. Multi-Company Isolation
Every entity scoped to `companyId`, complete data isolation, one deployment serves many companies.
- Evidence: `AGENTS.md` line 65: "Keep changes company-scoped"

### 14. Agent API Key Auth
Bearer token auth for agents with hashed keys, JWT generation for local agents, company-scoped access enforcement.
- Evidence: `AGENTS.md`, `server/src/agent-auth-jwt.ts`

### 15. Real-Time Live Events
SSE/WebSocket push to browser for runtime updates.
- Evidence: `server/src/services/live-events.ts`

---

## What Cognitive Squad Has That Paperclip Doesn't

### 1. 42-Agent Cognitive Architecture with 4-Phase Model
Understand/Decide/Solution/Build phases, 7 functional layers (control/exploration/feasibility/solution/specialists/build/learning). Each agent has strict role separation with NEVER rules.
- Evidence: `agents.yaml` — 42 agents with codenames, routing rules, phase assignments

### 2. Adversarial Quality Gates (SAGE)
Dedicated blocking critic agent that can halt progress; no agent validates its own work. WHY1/WHY2/WHY3 modes.
- Evidence: `agents.yaml` — SAGE with `blocking_power: true`

### 3. Evidence Hierarchy for Conflict Resolution
5-tier ranking: experiment results > deterministic metrics > graded research > code evidence > agent reasoning. Formal Toulmin argumentation model.
- Evidence: `agents/control/commander.md` lines 39-49

### 4. Calibration/Learning System
Cross-run learning with calibration profiles, pattern/pitfall YAML databases, cross-project knowledge sync (GLOBAL_MEMORY), stagnation detection (ADAPTIVE), internalization metrics (INTERNALIZER).
- Evidence: `agents.yaml`, `knowledge-base/` — patterns.yaml, pitfalls.yaml, calibration-profile.yaml

### 5. Belief-Annotated Configuration
`@belief()` annotations on every config value with claim, verified date, expiry, confidence, severity. Enables systematic challenge of assumptions.
- Evidence: `config-template.yml` — every setting has `@belief(...)` annotation

### 6. Innovation Engine (MAVERICK)
Design Thinking + AutoTRIZ + Lateral Thinking for breaking out of stagnation, triggered on circular reasoning or quality plateaus.
- Evidence: `agents.yaml` — MAVERICK agent

### 7. Constitution as Highest Authority
Immutable constitutional principles that outrank all agents, only human-amendable, explicit conflict resolution rules.
- Evidence: `agents.yaml` — `authority: highest`, `mutable_by: human_only`

### 8. Metacognition Monitor
"The squad's conscience" — checks every 5 tasks whether the squad is still doing the right thing, detects drift and process violations.
- Evidence: `agents.yaml` — MONITOR agent

### 9. Security/Threat Modeling (GUARDIAN) with Risk Acceptance Protocol
OWASP, STRIDE, threat modeling with autonomous risk acceptance and quantified Risk Acceptance Records (RARs).
- Evidence: `agents/specialists/guardian.md` — Risk Acceptance Protocol

### 10. Deterministic Spec Quality Metrics
31 requirements quality metrics across 6 categories via Understanding CLI, with quality gates.
- Evidence: Referenced across multiple agents (SAGE modes)

### 11. Brownfield Extraction (GOLDDIGGER)
Dedicated reverse-engineering agent that drives spec extraction from existing codebases.
- Evidence: `agents.yaml` — GOLDDIGGER agent

### 12. Thought Branches
Divergent exploration paths with configurable branch count and per-branch budget allocation.
- Evidence: `squad-config.yml` — `thought_branches` section

---

## Prompt Engineering Comparison

### Paperclip: Procedure-as-Prompt
Agents receive a **9-step numbered runbook** (the heartbeat procedure) with exact API calls. Identity is secondary to procedure. Steps are sequential, concrete, checkable.

```
1. Identity — GET /api/agents/me
2. Approval follow-up — check PAPERCLIP_APPROVAL_ID
3. Get assignments — GET /api/agents/me/inbox-lite
4. Pick work — priority rules
5. Checkout — POST /api/issues/{id}/checkout
6. Understand context — GET /api/issues/{id}/heartbeat-context
7. Do the work
8. Update status and communicate
9. Delegate if needed
```

### Cognitive Squad: Persona-as-Prompt
Agents receive role descriptions with belief registers, calibration injection, expert personas, and NEVER rules. More latitude in reasoning approach.

```
You are SCIENTIST — a researcher who has conducted 100+ technical investigations...
NEVER make architecture decisions based on findings (report to ARCHITECT)
@belief(claim: "...", confidence: 0.85, severity: critical)
```

### Key Differences

| Dimension | Paperclip | Cognitive Squad |
|-----------|-----------|----------------|
| Agent identity | Procedural (heartbeat steps) | Persona-based (SCIENTIST, ARCHITECT) |
| Anti-patterns | 3-column tables (Mistake/Why/Fix) | NEVER rules in prose |
| Context injection | Environment variables (token-efficient) | Full prompt injection |
| Skill loading | Tiered (description always, full on demand) | All 42 prompts loaded upfront |
| Few-shot examples | Worked simulations (IC + Manager) | Not consistently included |
| Memory | Persistent PARA with decay tiers | Session-scoped belief registers |
| Coordination | API-mediated (checkout, comments, @mentions) | In-process orchestration |

---

## Architecture Deep Dive

### Heartbeat Execution (`heartbeat.ts`, 3950 lines)

The core execution flow:
1. **Wake** — budget gate → agent status gate → heartbeat policy → issue execution lock → run queuing
2. **Claim** — per-agent in-memory lock, atomic DB update (`UPDATE WHERE status='queued'`)
3. **Execute** — resolve adapter → workspace → session → secrets → skills → JWT → spawn process
4. **Stream** — stdout/stderr chunks as live events to UI
5. **Finalize** — cost event → budget evaluation → agent status transition

Key patterns:
- Per-agent start locks (Map-based promise chains)
- Row-level `SELECT FOR UPDATE` with coalescing for same-agent duplicate wakes
- Session persistence keyed by `(companyId, agentId, adapterType, taskKey)`
- Orphan detection with PID liveness checks

### Budget Enforcement (`budgets.ts`, 958 lines)

Three-tier cascade: Company > Agent > Project
- Each tier has independent soft/hard thresholds
- Every cost event triggers evaluation across ALL applicable policies
- Hard-stop auto-pauses scope AND creates approval record
- Pre-invocation gate checks before allowing any agent wake

### Plugin System (21 service files)

- Process-isolated workers via JSON-RPC 2.0 over stdio
- 40+ fine-grained capabilities enforced at install + runtime
- VM sandbox for untrusted code + SSRF protection
- Crash recovery with exponential backoff (min 1s, max 5min, 10 max crashes)
- 13 UI slot types + launcher system + host component kit
- Agent tool contribution (namespaced discovery)
- Cron job scheduling with overlap prevention

### Data Model (59 tables)

```
companies (1)
  ├── agents (N) — self-ref reports_to
  ├── projects (N) → project_workspaces, execution_workspaces
  ├── issues (N) → comments, labels, attachments, documents, work_products
  ├── goals (N) — hierarchical via parent_id
  ├── approvals (N) → approval_comments
  ├── budget_policies (N) → budget_incidents
  ├── cost_events (N) — per-LLM-call tracking
  ├── finance_events (N) — double-entry ledger
  ├── heartbeat_runs (N) → heartbeat_run_events
  ├── routines (N) → routine_triggers, routine_runs
  ├── plugins (N) → plugin_config, plugin_state, plugin_jobs
  └── company_skills (N)
```

---

## Novel Concepts

### Company-as-First-Class-Object
The entire system is organized around "companies" — not projects or pipelines. A company has an org chart, budgets, goals, governance, and employees.

### Anti-Automatic-Recovery Philosophy
> "Automatic recovery hides failures. Good visibility lets the right entity decide what to do."
Stale tasks are surfaced, not silently redistributed. Crashed agents are not auto-recovered.

### Vendor-Neutral Company Portability (`agentcompanies/v1`)
Markdown-first package format for describing entire companies as exportable artifacts. `COMPANY.md` root with conventional folder discovery.

### Budget-as-Governance
Token/dollar budgets are enforcement mechanisms, not dashboards. At 100%, auto-pause + approval generation.

### "Minimum Contract: Be Callable"
Progressive integration levels: callable → status reporting → fully instrumented.

### Context Delivery Spectrum
Thin ping (agent fetches own context) vs fat payload (Paperclip bundles everything). Per-agent configurable.

---

## Adoption Roadmap for Echelon

### HIGH PRIORITY

| Feature | Why | How |
|---------|-----|-----|
| **Procedure-as-Prompt** | More reliable than persona descriptions; steps are sequential, concrete, checkable | Rewrite key agent prompts (INVESTIGATOR, ARCHITECT, ORCHESTRATOR) as numbered step protocols |
| **Anti-Pattern Tables** | 3-column format with reasoning is more scannable and generalizable than NEVER rules | Consolidate existing NEVER rules into per-role tables with Why column |
| **Cost tracking per dispatch** | Banzai mode with opus-everywhere burns real money; no dollar tracking exists | `cost-ledger.json` — COMMANDER logs estimated cost per dispatch |
| **3-tier budget cascade** | Company > Agent > Project with soft/hard thresholds | COMMANDER checks cumulative spend before each dispatch; auto-pause at threshold |
| **Tiered skill loading** | 42 prompts loaded upfront is context-inefficient | Description-as-router table (always in context) + full prompt loaded on dispatch |

### MEDIUM PRIORITY

| Feature | Why | How |
|---------|-----|-----|
| **Memory decay** | Belief register doesn't track usage frequency | Add access_count + last_accessed to beliefs; hot/warm/cold tiers |
| **Worked examples** | Few-shot training improves reliability | Add worked simulation per specialist (complete input/output sequence) |
| **Agent adapter abstraction** | Squad is Claude-only | Define AdapterInterface; route tiers to different providers |
| **Persistent run history** | Currently reconstructing history from artifacts | SQLite or structured JSON-DB for cross-run analytics |
| **Dashboard UI** | RADAR is live-only; no historical view | Extend RADAR with run history, costs, agent scores |

### LOW PRIORITY

| Feature | Why | How |
|---------|-----|-----|
| **Org chart SVG** | Nice visualization of 42-agent structure | One-time script from agents.yaml |
| **Goal hierarchy** | Explicit company → project → task tracing | goals.yaml artifact in ORCHESTRATOR |
| **Company portability** | Full project export with secret scrubbing | Extend VETERAN/GLOBAL_MEMORY |

---

## Key Architectural Patterns Worth Studying

1. **Per-agent start lock** — Map-based promise chains prevent concurrent start races
2. **Row-level execution lock** — `SELECT FOR UPDATE` with coalescing for same-agent duplicate wakes
3. **Cost attribution chain** — token → run → task → project → goal (full traceability)
4. **Generic approval primitive** — type-agnostic state machine with payload-driven side effects
5. **Task session persistence** — keyed by `(companyId, agentId, adapterType, taskKey)` with compaction policies
6. **Orphan detection** — PID liveness checks with single-retry semantics
7. **In-process EventEmitter** — no external broker needed for real-time
8. **Ephemeral skill directories** — skills injected via tmpdir symlinks, zero git pollution

---

## Fundamental Philosophical Contrast

> **Paperclip** = agents as **employees in an organization** (HR, budgets, approval chains)
> **Cognitive Squad** = agents as **cognitive specialists** (beliefs, calibration, endocrine arousal)

> Paperclip optimizes for **reliability and auditability at organizational scale**.
> Cognitive Squad optimizes for **reasoning quality at task scale**.

> The two systems are complementary. Paperclip could use cognitive-squad's analysis depth before building. Cognitive-squad could use Paperclip's runtime infrastructure for persistent execution.
