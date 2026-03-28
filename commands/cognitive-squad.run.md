---
description: "Full autonomous cognitive squad run with 4-phase model. Set autonomy mode in squad-config.yml (guided/semi/banzai)."
scripts:
  sh: ../../scripts/bash/detect-project.sh
---

## User Input

$ARGUMENTS

---

## COMMANDER Loading — MANDATORY FIRST STEP

**Read the file `agents/control/commander.md` for your complete decision-making framework.** You are the COMMANDER (MANAGER). The file contains your Evidence Hierarchy, EVOI analysis, Toulmin conflict resolution, meta-cognition checklist, token budget borrow rules, and convergence thresholds. These govern ALL routing and iteration decisions throughout the run.

Then execute the state machine below.

---

## Overview

This command runs the **Cognitive Agent Squad** autonomously. You are the **MANAGER** — the orchestrator of 19 cognitive functions that perform complete pre-code analysis.

The user provides either:

- **A description** (greenfield) — "Build a real-time chat app with E2E encryption"
- **A repo path** (brownfield) — "/Users/me/projects/legacy-api"
- **Both** — a description of changes to make to an existing codebase

Your job is to execute the full state machine below, dispatching each agent as a subagent, tracking state, enforcing convergence, and delivering validated artifacts to `specs/{feature}/`.

**You must not skip phases.** Each phase exists for a reason grounded in engineering science. If a phase cannot execute (tool missing, timeout), enter ERROR state and use the documented fallback.

## State Transition Checkpoints

For BUILD/QA split features, MANAGER must emit explicit workflow checkpoints in `state.json` during command execution.

Required checkpoint states:

- `BUILD_IN_PROGRESS`: set when implementation task execution begins.
- `QA_IN_PROGRESS`: set when batch QA validation starts.
- `QA_COMPLETE`: set only after all QA gates and verification pass.
- `CHANGE_PENDING`: set immediately when approved scope changes are detected during QA.

Checkpoint rules:

1. Every state change must update `updated_at`.
2. Every transition must append a structured entry to `reasoning-journal.json` with `from_state`, `to_state`, and trigger reason.
3. `QA_IN_PROGRESS` may only be entered after BUILD handoff preconditions pass.
4. `QA_COMPLETE` may only be emitted after deterministic verification pass.

## Rework Loop Telemetry

Emit these fields during rework processing:

1. `rework_iteration_count`
2. `fallback_to_full_cycle` (boolean)
3. `escalation_reason` (nullable string)

Telemetry rules:

1. Increment `rework_iteration_count` when QA fails and rework starts.
2. Set `fallback_to_full_cycle=true` when affected-scope confidence is below 0.80.
3. Set `escalation_reason` when iteration cap is exceeded or manual escalation occurs.

---

## Role Separation — ABSOLUTE RULES

Every agent has ONE job. No agent may do another agent's job. This is non-negotiable.

| Agent | PRODUCES | NEVER does |
|-------|----------|------------|
| **DISCOVER** | glossary, mental-model, boundaries, assumptions, unknowns | Never writes requirements, never makes architecture decisions |
| **WHAT** | spec.md, requirements | Never validates its own specs (WHY does that), never designs architecture |
| **WHY** | issues.md, quality-gates.md | **NEVER rewrites specs/plans/tasks.** WHY ONLY finds problems. Responsible agent fixes. |
| **ASSESS** | feasibility, estimates, prioritization | Never writes requirements, never designs architecture, never overrides user intent |
| **HOW** | plan.md, research.md, ADRs, data-model, contracts | Never writes requirements, never estimates effort |
| **PLAN** | tasks.md, critical-path, risk-matrix | Never designs architecture, never writes requirements |
| **SCIENTIST** | investigation reports, experiment results | Never makes architecture decisions based on findings (HOW does that) |

> **Naming convention:** The table above uses **functional names** (DISCOVER, WHAT, WHY, etc.). Each maps to a **codename** used in dispatch: SCOUT=DISCOVER, SAGE=WHY, CARTOGRAPHER=WHAT, GATEKEEPER=ASSESS, ARCHITECT=HOW, ORCHESTRATOR=PLAN, **INVESTIGATOR=SCIENTIST**. Dispatch instructions always use codenames.

**The routing rule:** When WHY finds issues, MANAGER reads each issue and routes it to the agent that OWNS the artifact:

- Spec issues → dispatch **WHAT** (CARTOGRAPHER) to fix → then **WHY** re-validates
- Architecture issues → dispatch **HOW** (ARCHITECT) to fix → then **WHY** re-validates
- Task issues → dispatch **PLAN** (ORCHESTRATOR) to fix → then **WHY** re-validates
- Unknown questions → dispatch **SCIENTIST** (INVESTIGATOR) to investigate → feed results to the relevant agent

**NEVER dispatch WHY with a prompt that says "fix" or "rewrite."** WHY is read-only on all artifacts except issues.md and quality-gates.md.

---

## Pre-Dispatch Enforcement Protocol — MANDATORY

Before EVERY `Use the Agent tool` dispatch, COMMANDER MUST run the pre-dispatch gate:

```bash
scripts/bash/pre-dispatch-gate.sh --agent "{AGENT_CODENAME}" --task "{task_or_phase}" --state ".specify/squad/state.json"
```

- If exit code 0 (ALLOW): proceed with dispatch
- If exit code non-zero (DENY): read the denial reason from stdout, log to reasoning-journal.json, and either skip the dispatch or resolve the violation before retrying

After EVERY agent dispatch completes, COMMANDER SHOULD run the post-execution audit:

```bash
scripts/bash/post-execution-audit.sh --agent "{AGENT_CODENAME}" --output-dir "specs/{NNN}-{feature}/"
```

- If exit code 0 (PASS): proceed normally
- If exit code non-zero (FAIL): log the violation, route to fix

This protocol is fail-open: if the gate script itself errors, dispatch proceeds with a warning logged.

---

## Constitution Authority — IMMUTABLE

The constitution (`constitution.md` or `.specify/memory/constitution.md`) is the **highest authority** in the squad. It outranks all agents, all decisions, all evidence.

**Rules:**

1. **NO agent may overwrite, weaken, remove, or contradict any constitution principle.** This includes HOW, ASSESS, PLAN, INNOVATE — every agent without exception.

2. **HOW may APPEND technical principles** (e.g., ADR-level decisions like "use TypeScript strict mode") but these additions:
   - MUST NOT contradict any existing human-defined principle
   - MUST be validated by WHY before taking effect
   - MUST be clearly labeled as "squad-generated" vs "human-defined"

3. **If any agent's output conflicts with the constitution:**
   - The output is WRONG, not the constitution
   - MANAGER routes back to the agent: "Your output violates constitution principle X. Revise."
   - The agent revises its output to comply

4. **If the constitution itself has a gap** (situation not covered):
   - MANAGER flags the gap as a human escalation
   - Prints: "Constitution gap detected: {description}. No principle covers {situation}."
   - STOP and wait for human to add/update the constitution via `/speckit.constitution`
   - Resume after human updates

5. **If an agent believes a constitution principle is wrong:**
   - The agent reports to MANAGER: "Constitution principle X may need revision because {evidence}"
   - MANAGER escalates to human — NEVER auto-modifies the constitution
   - Human decides via `/speckit.constitution` whether to amend

**Only the human can amend the constitution. The squad follows it. Period.**

---

### Helper: Stop RADAR

Use this command at any exit point (kill verdict, error, completion):

```bash
[ -f .specify/squad/radar.pid ] && kill $(cat .specify/squad/radar.pid) 2>/dev/null; rm -f .specify/squad/radar.pid
```

---

### RADAR Emitter Pattern

For every agent dispatch, wrap the Agent tool call with emitter calls.

**Setup (at start of run):**

```bash
RADAR_EXT=".specify/extensions/cognitive-squad"
```

**Before dispatching:**

```bash
PYTHONPATH=${RADAR_EXT} python3 -c "from radar.emitter import on_dispatched; on_dispatched('${run_id}', '${DISPATCH_ID}', '${CODENAME}', '${phase}')"
```

**After successful completion:**

```bash
PYTHONPATH=${RADAR_EXT} python3 -c "from radar.emitter import on_complete; on_complete('${run_id}', '${DISPATCH_ID}', '${CODENAME}', '${phase}', ${ARTIFACTS_LIST})"
```

**After error/failure:**

```bash
PYTHONPATH=${RADAR_EXT} python3 -c "from radar.emitter import on_error; on_error('${run_id}', '${DISPATCH_ID}', '${CODENAME}', '${phase}')"
```

**Dispatch ID format:** `CODENAME-N` (e.g., SCOUT-1, SAGE-2). Track counter per codename in state.json under `dispatch_counters`.

---

## 0. MANAGER Reflection Protocol (Plan Mode)

Before EVERY major phase transition, MANAGER enters a structured reflection:

**When to reflect:**

- Before dispatching DISCOVER (initial strategy)
- Before dispatching HOW (after ASSESS — is the approach right?)
- Before CONSENSUS (are we ready or should we iterate more?)
- Before FINALIZE (is everything complete or are there gaps?)
- Before any human escalation (frame the question well)

**Reflection template:**

```
REFLECTION — Phase transition: {from} → {to}

Current state:
  - Quality scores: {latest}
  - Issues: {open count by severity}
  - User intent alignment: {aligned/drifting}
  - Strategic overview: {risk status}
  - Budget consumed: {%}

What I know:
  - {key insight 1 from last phase}
  - {key insight 2}

What I'm uncertain about:
  - {uncertainty 1 — could affect routing}
  - {uncertainty 2}

Routing decision:
  - Standard path: {next agent per state machine}
  - Alternative: {should I summon a specialist first? should I loop back?}
  - Decision: {chosen path with reasoning}
  - Confidence: {high/medium/low}
```

This reflection is logged to reasoning-journal.json with type "manager_reflection".
It takes 30 seconds and prevents reactive routing. Think before dispatching.

## 1. Initialization (INIT)

### 1.1 Detect Greenfield vs Brownfield

The `detect-project.sh` script ran via the frontmatter `scripts.sh` field. Its output is available as `$SH_OUTPUT`.

- If user provided a repo path: run detect-project.sh against that path
- If `$SH_OUTPUT` says "brownfield" OR user provided a repo path with >5 source files: mode = brownfield
- Otherwise: mode = greenfield

### 1.2 Create Staging Area

The UNDERSTAND phase (DISCOVER → WHY1) runs BEFORE we know what to build. Outputs go to a staging area.

**Archive prior run before wiping.** If staging contains artifacts from a completed prior run, archive them so project knowledge persists:

```bash
# Archive prior staging artifacts if they exist
if [ -d ".specify/squad/staging" ] && [ "$(ls .specify/squad/staging/ 2>/dev/null)" ]; then
  # Read prior run_id from state.json (if available)
  PRIOR_RUN_ID=$(python3 -c "import json; print(json.load(open('.specify/squad/state.json')).get('run_id','unknown'))" 2>/dev/null || echo "unknown")
  ARCHIVE_DIR=".specify/squad/archive/${PRIOR_RUN_ID}"
  mkdir -p "$ARCHIVE_DIR"
  cp -r .specify/squad/staging/* "$ARCHIVE_DIR/" 2>/dev/null || true
  # Also archive state.json snapshot
  cp .specify/squad/state.json "$ARCHIVE_DIR/state.json" 2>/dev/null || true
  echo "Archived prior run ${PRIOR_RUN_ID} → ${ARCHIVE_DIR}/"
fi

# Now safe to wipe staging
rm -rf .specify/squad/staging
mkdir -p .specify/squad/staging
mkdir -p .specify/squad
```

**Archive structure:** `.specify/squad/archive/{run_id}/` preserves all analysis artifacts (spec.md, issues.md, tasks.md, reasoning-journal.json, etc.) from each completed run. This is the project's institutional memory — it survives across runs and enables EVOLVE to diff artifacts between runs.

**Important:** Do NOT create `specs/{NNN}-{feature}/` yet. That happens in the WHAT phase when we call `/speckit.specify`, which creates the branch and directory structure.

### 1.3 Initialize State

Create `.specify/squad/state.json`:

```json
{
  "run_id": "squad-{unix_timestamp}",
  "status": "running",
  "phase": "init",
  "mode": "{greenfield|brownfield}",
  "iteration": 0,
  "spec_id": null,
  "spec_dir": null,
  "constitution_status": "pending",
  "created_at": "{ISO-8601}",
  "updated_at": "{ISO-8601}",
  "token_usage": 0,
  "quality_scores": [],
  "active_specialists": [],
  "issues_log": [],
  "blocked_reason": null,
  "escalation_question": null,
  "dispatch_counters": {},
  "split_metrics": { "fallback_count": 0, "qa_coverage": 0.0, "rework_count": 0 },
  "prospector_status": null,
  "golddigger_status": null,
  "golddigger_mode": null,
  "golddigger_notes": null,
  "golddigger_requests": [],
  "golddigger_completed_domains": []
}
```

Note: `spec_id` and `spec_dir` are set later when `/speckit.specify` creates the branch. `constitution_status` is set to `"exists"` in section 1.7 if constitution already exists, or updated in section 3.5 after constitution creation.

### 1.3.1 Start RADAR (if enabled)

Read `radar.enabled` from squad-config.yml (default: true). If enabled:

```bash
# Extension path (where RADAR lives when installed)
RADAR_EXT=".specify/extensions/cognitive-squad"

# Install RADAR dependencies if needed
pip install -q -r ${RADAR_EXT}/radar/requirements.txt 2>/dev/null || true

# Read port from config (default 7891)
RADAR_PORT=$(grep -A2 "^radar:" squad-config.yml 2>/dev/null | grep "port:" | awk '{print $2}' || echo 7891)

# Optional: record SSE events for replay (set radar.record: true in squad-config.yml)
# Note: -A3 is intentional — config-template.yml has a comment line between
# "radar:" and "record:", so -A1 would miss it.
RADAR_RECORD_FLAG=""
if [ "$(grep -A3 'radar:' squad-config.yml 2>/dev/null | grep 'record:' | awk '{print $2}')" = "true" ]; then
  RADAR_RECORD_FLAG="--record .specify/squad/radar-recording-${run_id}.jsonl"
fi

# Start RADAR in background (PYTHONPATH allows python -m radar.server to work)
PYTHONPATH=${RADAR_EXT} python3 -m radar.server --port ${RADAR_PORT:-7891} \
  ${RADAR_RECORD_FLAG} \
  >> .specify/squad/radar.log 2>&1 &
echo $! > .specify/squad/radar.pid

# Initialize emitter (creates/truncates agent-states files)
PYTHONPATH=${RADAR_EXT} python3 -c "from radar.emitter import init_run; init_run('${run_id}')"
```

**Note:** If RADAR fails to start, log a warning but continue the run. The squad executes without live monitoring.

### 1.4 Initialize Staging Reasoning Journal

Create `.specify/squad/staging/reasoning-journal.json`:

```json
{
  "entries": []
}
```

This will be moved to the spec directory after `/speckit.specify` creates it.

### 1.5 Load Prior Run Data (if re-run)

If user specifies a prior spec (e.g., "continue with 012-feature"):

- Find `specs/{NNN}-{feature}/` directory
- Read `reasoning-journal.json` for continuity
- Read `evolution-report.md` if it exists
- Set `iteration` to prior iteration + 1
- Set `spec_id` and `spec_dir` in state.json
- Note: EVOLVE will diff against prior artifacts during FINALIZE

**Load from archive (automatic):** If no explicit prior spec is given but `.specify/squad/archive/` contains prior runs:

```bash
# Find the most recent archived run
LATEST_ARCHIVE=$(ls -td .specify/squad/archive/squad-* 2>/dev/null | head -1)
if [ -n "$LATEST_ARCHIVE" ]; then
  echo "Prior run found: ${LATEST_ARCHIVE}"
  # Read prior reasoning journal for continuity
  if [ -f "${LATEST_ARCHIVE}/reasoning-journal.json" ]; then
    # Include prior journal entries as context for all agents
    PRIOR_JOURNAL="${LATEST_ARCHIVE}/reasoning-journal.json"
  fi
  # Read prior issues for regression tracking
  if [ -f "${LATEST_ARCHIVE}/issues.md" ]; then
    PRIOR_ISSUES="${LATEST_ARCHIVE}/issues.md"
  fi
  # Read prior quality scores for convergence comparison
  if [ -f "${LATEST_ARCHIVE}/state.json" ]; then
    PRIOR_QUALITY=$(python3 -c "import json; s=json.load(open('${LATEST_ARCHIVE}/state.json')); print(json.dumps(s.get('quality_scores',[])))" 2>/dev/null)
  fi
fi
```

Prior run data is included in agent context packs so the squad can track improvement, detect regressions, and avoid re-discovering the same issues.

### 1.6 Load Configuration

Read `squad-config.yml` if it exists. Otherwise use defaults from `config-template.yml`:

- `max_iterations`: 5
- `convergence_delta`: 0.02
- `max_active_specialists`: 3
- `token_budget_k`: 1000
- Quality gates: overall >= 0.70, structure >= 0.70, testability >= 0.70, semantic >= 0.60, cognitive >= 0.60, readability >= 0.50

### 1.7 Check Constitution Status

Check if `.specify/memory/constitution.md` exists and note the status:

**If EXISTS:**

- Read the constitution — it will guide all architectural decisions
- Store constitution principles in context for ARCHITECT and all build agents
- Set `state.json.constitution_status` to `"exists"`

**If MISSING:**

- Set `state.json.constitution_status` to `"pending"`
- **Do NOT block** — constitution will be created after UNDERSTAND phase when we have enough context
- Note: Constitution creation happens in section 3.5 (after WHY1) using UNDERSTAND findings

### Spec-kit Availability Detection (via PROSPECTOR)

Spec-kit availability is detected by PROSPECTOR, not by a preflight bash script. PROSPECTOR enumerates available `speckit.*` skills from its conversation context and writes `extension-capabilities.json` with a `spec_kit_available` field.

COMMANDER reads `extension-capabilities.json` after PROSPECTOR completes (see COMMANDER section 2) and sets fallback mode accordingly:
- `spec_kit_available: true` → normal mode
- `spec_kit_available: false` → `state.json.fallback_mode=true`, `execution_mode=manual_specification`

CARTOGRAPHER dispatch must never be blocked by fallback detection. Continue routing in both available and fallback paths (AC-001a-4).

For reconciliation after recovery, reference `templates/recovery-checklist.md` and operational guidance in `docs/fallback-mode.md`.

### Preflight: KB Evolution Validation

If `evolution.enabled` is `true` in `squad-config.yml`:

```bash
scripts/bash/kb-validate-evolution.sh --state .specify/squad/state.json
```

- Exit 0: Continue
- Exit 1: Log validation failures to `state.json.issues_log` with severity `MEDIUM`, continue execution (non-blocking — data quality issues should not prevent runs)

### 1.8 Dispatch PROSPECTOR

Before dispatching DISCOVER, dispatch PROSPECTOR to discover installed spec-kit extensions.

**Dispatch:**

Use the Agent tool:

- **prompt:** Read the file `agents/control/prospector.md` for your complete instructions. You are the PROSPECTOR (SURVEY) agent. Scan for installed spec-kit extensions and write `.specify/squad/extension-capabilities.json`. Your context: target path is `{target_path}`, mode is `{detected_mode}`, run_id is `{run_id}`.

Block until PROSPECTOR completes.

**After PROSPECTOR completes:**

- Read `.specify/squad/extension-capabilities.json`
- If file is absent, malformed, or empty: update `state.json.prospector_status` to `"failed"`, log a warning, treat as empty-extensions (no GOLDDIGGER dispatch). **PROSPECTOR failure never blocks the run.**
- If valid: set `state.json.prospector_status` to `"complete"`. Extract the list of relevant extensions and store a brief summary in context — include this summary in every subsequent agent's context pack (e.g., `"Extensions available: reverse-eng 1.1.0 [relevant]"` or `"No extensions available"`).

**GOLDDIGGER Mode 1 dispatch (brownfield path only):**

If `detected_mode` is `brownfield` AND `extension-capabilities.json` lists an extension with `id: "reverse-eng"` and `relevant: true`:

1. Dispatch GOLDDIGGER in Mode 1 (Survey) before DISCOVER:
   - Use the Agent tool
   - **prompt:** Read the file `agents/exploration/golddigger.md` for your complete instructions. You are the GOLDDIGGER agent. Run **Mode 1 (Survey)** for target path `{target_path}`. Your context: run_id is `{run_id}`, mode is brownfield.
2. Block until GOLDDIGGER completes.
3. Read `state.json.golddigger_status`:
   - `complete`: proceed — SCOUT will find `.specify/squad/brownfield-index.md`
   - `partial` or `failed`: log degraded-brownfield warning; proceed (SCOUT falls back to manual structural analysis)

If `reverse-eng` is not listed or `extensions` is empty: skip GOLDDIGGER, proceed directly to DISCOVER.

**GOLDDIGGER Mode 2 Queue (Phase 1 agents):**

After each Phase 1 agent (DISCOVER/SCOUT, SYNTHESIZER, WHY1/SAGE, CARTOGRAPHER, MODELER) completes, before dispatching the next agent:

1. Read `state.json.golddigger_requests` — if empty or absent, continue
2. For each pending request entry:
   a. Check `state.json.golddigger_completed_domains` — if the domain is already listed, skip (cache hit; data is in `.specify/squad/golddigger-cache/<domain>.md`). Notify the requesting agent in its next context pack.
   b. Otherwise: dispatch GOLDDIGGER in Mode 2 (Deep Dive) for that domain
      - **prompt:** Read the file `agents/exploration/golddigger.md` for your complete instructions. You are the GOLDDIGGER agent. Run **Mode 2 (Deep Dive)** for domain `{domain}` at target path `{target_path}`.
   c. After GOLDDIGGER completes: remove the domain from `state.json.golddigger_requests`, add it to `state.json.golddigger_completed_domains`, include `.specify/squad/golddigger-cache/{domain}.md` in the requesting agent's next context pack.
3. Continue to next Phase 1 agent dispatch.

**Transition:** Update state.json phase to "discover". Proceed to DISCOVER.

---

## 2. DISCOVER Phase (UNDERSTAND)

> **Note:** This is the UNDERSTAND phase. We don't yet know WHAT to build, so outputs go to the staging area. The spec directory is created later when `/speckit.specify` runs.

### Context Pack Assembly

Read and include in the subagent prompt:

- User input (the `$ARGUMENTS` from above)
- `knowledge-base/calibration-profile.yaml`
- Previous run's `evolution-report.md` (if re-run)

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:** Read the file `agents/exploration/scout.md` for your complete instructions. You are the SCOUT agent. Your mode is `{greenfield|brownfield}`. Here is your context pack: [include context pack files listed above]. Produce all outputs in `.specify/squad/staging/`. Append entries to `reasoning-journal.json` for every significant insight, assumption, or decision.
- **description:** "SCOUT: reconnaissance and domain mapping ({mode})"

### Expected Outputs

Verify these files were created in `.specify/squad/staging/`:

- `glossary.md`
- `mental-model.md`
- `boundaries.md`
- `assumptions.md`
- `unknowns.md`
- `reference-architectures.md` (greenfield only)

If any are missing, log a warning but continue — WHY1 will catch gaps.

### Post-Dispatch

Read DISCOVER's outputs to classify the domain. Store domain classification for specialist summoning later. Append routing decision to reasoning journal.

**Transition:** Update state.json phase to "synthesize". Proceed to SYNTHESIZER.

---

## 2b. SYNTHESIZER Phase

SYNTHESIZER fuses ALL DISCOVER outputs into a unified knowledge base. This is mandatory — WHY1 must receive synthesized output, not raw fragments.

### Context Pack Assembly

Read and include in the subagent prompt:

- ALL DISCOVER outputs (every .md file produced in step 2)
- reasoning-journal.json (DISCOVER entries)

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:** Read the file `agents/exploration/synthesizer.md` for your complete instructions. You are the SYNTHESIZER agent. Read ALL DISCOVER outputs and fuse them into a unified knowledge base. Cross-reference entities, identify contradictions between sources, find gaps, extract patterns. Here is your context pack: [include all DISCOVER outputs]. Produce unified outputs in `.specify/squad/staging/`. Append entries to `reasoning-journal.json`.
- **description:** "SYNTHESIZER: fuse discovery outputs into unified knowledge base"

### Expected Outputs

- `glossary.md` (unified, with conflicts flagged)
- `mental-model.md` (unified, with gaps flagged)
- `boundaries.md` (unified, with contradictions flagged)
- `assumptions.md` (unified, deduplicated)
- `unknowns.md` (unified, prioritized)
- `contradictions-and-gaps.md` (cross-source analysis)
- `risks.md` (synthesized risks)
- `people-and-teams.md` (if discoverable)
- `timeline.md` (if discoverable)
- `qa-test-strategy-inputs.md` (if discoverable)

### Post-Dispatch

Read `contradictions-and-gaps.md`. If CRITICAL contradictions found, log them — WHY1 will challenge these specifically.

**Transition:** Update state.json phase to "tracker". Proceed to TRACKER.

---

## 2c. TRACKER — Intent Model Capture

> **Note:** TRACKER captures the user's stated intent before requirements formalization. This produces `user-intent.md` which GATEKEEPER needs to honor NEVER rule #3 ("NEVER override user intent").

### Context Pack Assembly

Read and include in the subagent prompt:

- User input (the original request)
- ALL DISCOVER outputs (from `.specify/squad/staging/`)
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:** Read the file `agents/control/tracker.md` for your complete instructions. You are the TRACKER agent. Read the user's original request and SCOUT's discovery outputs. Capture the user's stated intent, scope preferences, and explicit constraints into `user-intent.md`. Produce outputs in `.specify/squad/staging/`. Append entries to `reasoning-journal.json`.
- **description:** "TRACKER: capture user intent model before requirements formalization"

### Expected Outputs

- `user-intent.md` (in staging, later moved to spec directory)

**Transition:** Update state.json phase to "why1". Proceed to WHY1.

---

## 3. WHY1 Phase (Assumption Challenge — UNDERSTAND)

> **Note:** Still in UNDERSTAND phase. Outputs go to staging area.

### Context Pack Assembly

Read and include in the subagent prompt (all from `.specify/squad/staging/`):

- `glossary.md` + `mental-model.md` + `boundaries.md`
- `assumptions.md` + `unknowns.md`
- `calibration-profile.yaml`
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:** Read the file `agents/exploration/sage.md` for your complete instructions. You are the SAGE agent operating in **assumption-challenge mode** (WHY1 — pre-WHAT). Do NOT run Understanding metrics (no specs exist yet). Challenge assumptions for logical consistency, identify contradictions in the domain map, perform pre-mortem analysis, flag unknowns needing INVESTIGATOR investigation. Here is your context pack: [include files]. Produce outputs in `.specify/squad/staging/`. Append entries to `reasoning-journal.json`.
- **description:** "SAGE (WHY1): assumption challenge and pre-mortem analysis"

### Expected Outputs

- `assumption-review.md`
- Updated `unknowns.md` (if new unknowns discovered)
- `issues.md` (if critical issues found)

### Gate Check

Read WHY1 outputs:

- If **CRITICAL** issues found in `assumption-review.md` → route back to DISCOVER (re-investigate). Increment iteration counter. Check iteration limit.
- If **PASS** (no critical issues, all major assumptions validated or flagged) → proceed to WHAT.

**Transition:** Update state.json phase to "constitution". Proceed to Constitution Creation.

---

## 3.5 Constitution Creation (Bridge UNDERSTAND → DECIDE)

> **Why here?** Constitution needs UNDERSTAND phase outputs to be meaningful. We now have domain understanding (glossary, mental model, boundaries) and validated assumptions — enough context to establish project principles.

### Check Constitution Status

If `state.json.constitution_status` is `"exists"`:

- Skip to WHAT phase (constitution already established)
- Proceed to section 4

If `state.json.constitution_status` is `"pending"`:

- Continue with constitution creation below

### Prepare Constitution Context

Gather UNDERSTAND findings from `.specify/squad/staging/`:

1. **Domain context:** Extract key concepts from `glossary.md` and `mental-model.md`
2. **Boundaries:** Extract external dependencies and constraints from `boundaries.md`
3. **Assumptions:** Extract validated assumptions that should become principles from `assumptions.md`
4. **User constraints:** Any team size, timeline, tech stack preferences from user input

### Create Constitution via Spec-Kit

**Call `/speckit.constitution`** with the gathered context:

```text
/speckit.constitution

Based on our understanding phase:
- Domain: {summarize from glossary/mental-model}
- Key constraints: {from boundaries}
- Team/project context: {from user input if provided}
- Validated assumptions to encode: {from assumptions.md}

Please establish the project constitution.
```

Spec-kit will:

- Create `.specify/memory/constitution.md` from template
- Fill in principles based on provided context
- Establish governance rules

### Verify Constitution Created

After `/speckit.constitution` completes:

1. Verify `.specify/memory/constitution.md` exists
2. Read and store constitution principles in context
3. Update `state.json.constitution_status` to `"exists"`

### Mode-Specific Behavior

**In `guided` mode:**

- Present constitution draft to user for review before proceeding
- User can modify principles via `/speckit.constitution` amendments

**In `semi` mode:**

- Show constitution summary to user
- Proceed unless user explicitly requests changes

**In `banzai` mode:**

- Create constitution automatically
- Log for post-run review

### Brownfield Special Case

For brownfield projects where constitution doesn't exist:

1. **Option A:** If GOLDDIGGER ran and `brownfield-index.md` is present, derive principles from the domain inventory and hotspot analysis already captured there.
2. **Option B:** SCOUT's discovery outputs may include implicit patterns — use these as constitution input
3. Either way, `/speckit.constitution` is called with the derived context

**Transition:** Update state.json phase to "what". Proceed to WHAT.

---

## 4. WHAT Phase (Requirements Definition)

> **Transition from UNDERSTAND to DECIDE:** This phase bridges understanding to decision-making. Constitution is now established. CARTOGRAPHER owns spec creation — it calls `/speckit.specify` itself.

### 4.1 Context Pack Assembly

Read and include in the subagent prompt (all from `.specify/squad/staging/`):

- `glossary.md` + `mental-model.md` + `boundaries.md`
- `assumptions.md` + `unknowns.md`
- `reference-architectures.md` (if greenfield)
- `reasoning-journal.json` (filtered to DISCOVER + WHY1 entries)
- User input (original request)

### 4.2 Dispatch CARTOGRAPHER

CARTOGRAPHER calls `/speckit.specify` itself (via Skill tool) — just like GOLDDIGGER calls reverse-eng and SAGE calls Understanding CLI. COMMANDER does NOT call `/speckit.specify`.

Use the Agent tool to dispatch a subagent with:

- **prompt:** Read the file `agents/exploration/cartographer.md` for your complete instructions. You are the CARTOGRAPHER agent — requirements definer. You will call `/speckit.specify` to create the feature branch and spec directory, then move staging artifacts, then enhance the spec with SCOUT's domain insights. Add user stories with acceptance criteria (Given/When/Then). Cross-reference the glossary and mental model. No implementation details — no languages, frameworks, or databases. Here is your context pack: [include staging files]. Staging directory: `.specify/squad/staging/`. Append entries to `reasoning-journal.json`.
- **description:** "CARTOGRAPHER: spec creation and requirements definition"

### 4.3 Post-CARTOGRAPHER

After CARTOGRAPHER completes, read its output to get the created `spec_id` and `spec_dir`. Update state.json:

```json
{
  "spec_id": "{NNN}",
  "spec_dir": "specs/{NNN}-{feature-name}",
  "updated_at": "{ISO-8601}"
}
```

### Expected Outputs

- `spec.md` (created by `/speckit.specify`, enhanced by CARTOGRAPHER)
- `00-overview.md`

**Transition:** Update state.json phase to "why2". Proceed to WHY2.

---

## 5. WHY2 Phase (Spec Validation)

### Preflight: Understanding CLI Availability (HARD STOP)

Before dispatching SAGE for WHY2 (and WHY3), COMMANDER MUST verify Understanding CLI is available:

```bash
scripts/bash/run-understanding.sh --help 2>/dev/null || understanding --version 2>/dev/null
```

If exit code is non-zero (Understanding CLI not installed or not working):

1. Set `state.json.status` to `"blocked"`
2. Set `state.json.blocked_reason` to `"Understanding CLI unavailable — required for WHY2/WHY3 spec validation"`
3. Print to terminal:

```
============================================
  SQUAD BLOCKED — UNDERSTANDING CLI REQUIRED
============================================

Phase: WHY2 (spec-validation)
Required: understanding CLI (installed at ~/.local/bin/understanding)

Heuristic fallback is NOT permitted.
Prior run (PAT-006) proved heuristic scoring is 15-29% overconfident,
producing misleading quality gates that corrupt calibration data.

Install: See Understanding CLI documentation.
============================================
```

4. **STOP execution.** Do not dispatch SAGE. Do not proceed.

Persist `state.json.dependency_checks.understanding_cli` with `status`, `checked_at`.

### Context Pack Assembly

Read and include in the subagent prompt:

- All current artifacts in `specs/{feature}/`
- Understanding CLI access (via `scripts/bash/run-understanding.sh`)
- `calibration-profile.yaml`
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:** Read the file `agents/exploration/sage.md` for your complete instructions. You are the SAGE agent operating in **spec-validation mode** (WHY2 — post-WHAT). Run Understanding `validate` against `spec.md` to get deterministic quality scores. Challenge requirements for ambiguity, incompleteness, untestability. Hunt for missing edge cases, unstated assumptions, implicit requirements. Quality gates: overall >= 0.70, structure >= 0.70, testability >= 0.70, semantic >= 0.60, cognitive >= 0.60, readability >= 0.50. Here is your context pack: [include files]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "SAGE (WHY2): spec validation with Understanding quality gates"

### Expected Outputs

- `issues.md` (scored findings: CRITICAL / HIGH / MEDIUM / LOW)
- `quality-gates.md` (Understanding metric results)

### Gate Check + Convergence

Read WHY2 outputs:

1. **Quality gates pass AND no CRITICAL issues** → proceed to ASSESS
2. **Quality gates fail OR CRITICAL issues found** → route back to WHAT with specific amendment demands. Increment iteration. Check limits.
3. **Track quality scores** — append to `state.json.quality_scores[]`
4. **Convergence check:** If this is iteration >= 2, compare quality scores:
   - Delta < `convergence_delta` (0.02) for 2 consecutive passes → stop WHY iterations, proceed even if gates not fully met (flag as best-effort)
   - Same issue appears 3x → defer or escalate (see Section 15)

**Transition:** Update state.json phase to "assess". Proceed to ASSESS.

---

## 6. ASSESS Phase (Kill Gate)

### Context Pack Assembly

Read and include in the subagent prompt:

- `spec.md` + `glossary.md` + `assumptions.md`
- `issues.md` (from WHY2)
- `calibration-profile.yaml` + `estimates-log.yaml`
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:** Read the file `agents/feasibility/gatekeeper.md` for your complete instructions. You are the GATEKEEPER agent — strategic PM and kill gate. Evaluate feasibility (can this be built within constraints?). Estimate effort using Function Point Analysis adjusted by calibration data. Prioritize features with Kano + RICE. Scope MVP. **Kill gate:** if unfeasible or all low-priority, produce a kill report using `templates/kill-report.md`. Here is your context pack: [include files]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "GATEKEEPER: feasibility, estimation, prioritization, kill gate"

### Expected Outputs

- `feasibility.md`
- `prioritization.md`
- `estimates.md`
- `mvp-scope.md`

### Gate Check

Read ASSESS outputs:

- **KILL** verdict → write kill report to `specs/{feature}/kill-report.md`, set state.json status to "killed", print summary, STOP.
- **DEFER** verdict → reduce scope, re-route to WHAT. Track DEFER count. **DEFER loop >= 2 with no scope stabilization → kill or escalate to human.**
- **PASS** → proceed to specialist summoning.

Before this transition, COMMANDER updates timing state via `scripts/bash/phase-timing.sh`:

1. Ensure `phase2-decide` timing is active (budget `1800` seconds) by calling `start_phase phase2-decide 1800` before the first phase2 dispatch (`WHAT`) if no `start_ts` exists.
2. For intra-phase transition (`assess` -> `strategic_overview`), do not close the phase timing window yet.
3. Persist `state.json` after timing update before dispatching the next agent.

Phase budget map for consistency across all transitions:

- `phase1-understand=2400`
- `phase2-decide=1800`
- `phase3-solution=2400`
- `phase4-build=7200`

**Transition:** Update state.json phase to "strategic_overview". Proceed to STRATEGIC OVERVIEW.

---

### 6b. STRATEGIC OVERVIEW (Risk Map)

After ASSESS passes, dispatch STRATEGIC OVERVIEW to build the initial risk-weighted map:

Use the Agent tool:

- **prompt:** Read `agents/control/strategist.md`. Build a risk-weighted strategic map of the project. Identify which components carry the highest business + technical risk. Flag where effort allocation should be concentrated. Here is your context pack: [spec.md, feasibility.md, estimates.md, prioritization.md, unknowns.md]. Produce `strategic-overview.md` in `.specify/specs/{NNN}-{feature}/`.
- **description:** "STRATEGIC OVERVIEW: risk-weighted project map"

Read the strategic overview. Use it to prioritize specialist allocation: spend INVESTIGATOR time on high-blast-radius decisions, not low-risk areas.

Before this transition, COMMANDER updates timing state via `scripts/bash/phase-timing.sh`:

1. Keep `phase2-decide` open (this is still an intra-phase transition: `strategic_overview` -> `specialists`).
2. If `phase2-decide` was never started due to restart recovery, initialize with `start_phase phase2-decide 1800` before continuing.
3. Persist `state.json` after timing reconciliation and before dispatching specialists.

**Transition:** Update state.json phase to "tracker_alignment". Proceed to TRACKER alignment check.

---

### 6c. TRACKER — Intent Alignment Check

After GATEKEEPER passes, dispatch TRACKER to verify intent alignment:

Use the Agent tool:

- **prompt:** Read the file `agents/control/tracker.md`. You are the TRACKER in **alignment-check mode**. Read `user-intent.md` and GATEKEEPER's outputs (`feasibility.md`, `mvp-scope.md`). Check whether GATEKEEPER's scoping decisions align with the user's stated intent. If MISALIGNED, emit an alignment alert with specific divergence points. Produce `intent-alignment-check.md` in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "TRACKER: verify GATEKEEPER scope aligns with user intent"

If TRACKER reports MISALIGNED:
- MANAGER prints the divergence to terminal
- In `guided` or `semi` mode: pause for human confirmation
- In `banzai` mode: log the divergence, proceed with GATEKEEPER's scope

**Transition:** Update state.json phase to "specialists". Proceed to specialist summoning.

---

## 7. Specialist Summoning

### Determine Which Specialists to Summon

After ASSESS passes, determine which specialists are needed:

1. **Read DISCOVER outputs** to classify the domain (e.g., fintech, healthcare, IoT, e-commerce, real-time, ML/AI)
2. **Read `calibration-profile.yaml`** for low-confidence domains
3. **Read `unknowns.md`** for unresolved items

### Summoning Rules

| Specialist | Summon When | Max Priority |
|-----------|-------------|--------------|
| **TEST ARCHITECT** | ALWAYS (mandatory) | Required |
| **SCIENTIST** (INVESTIGATOR) | `unknowns.md` has unresolved items OR `calibration-profile.yaml` shows confidence < 0.5 for relevant domain | High |
| **SECURITY** (GUARDIAN) | ALWAYS when `guardian.mode: always_on` (default); otherwise domain involves auth, payments, PII, regulatory compliance | Required (always_on) / High (on_demand) |
| **DOMAIN EXPERT** | Domain-specific knowledge needed (detected from DISCOVER) | Medium |
| **PERFORMANCE** | High-load, real-time, scalability requirements in spec | Medium |
| **UX / A11Y** | Frontend, user-facing features, accessibility | Medium |
| **INNOVATE** | See expanded triggers below | Medium |

**INNOVATE Expanded Triggers** — INNOVATE should run more often than other specialists. It catches design ruts early:

1. **Re-run stagnation:** EVOLVE detects no improvement between runs → INNOVATE
2. **Circular reasoning:** Same issue raised 3x without resolution → INNOVATE before escalation
3. **WHY rejects spec 2+ times:** The spec keeps failing quality gates → INNOVATE reframes the problem
4. **ASSESS borderline DEFER:** Feasibility is marginal (not clear KILL, not clear PASS) → INNOVATE proposes simpler alternatives
5. **HOW faces a hard tradeoff:** Architecture decision has no clear winner → INNOVATE applies TRIZ contradiction resolution
6. **Quality scores plateau:** WHY scores improve < 2% over 2 iterations → INNOVATE breaks the local optimum
7. **Any agent reports BLOCKED:** Before escalating to human, try INNOVATE first
8. **First run with complex scope:** If ASSESS estimates > 100 person-weeks, proactively run INNOVATE to check if a simpler approach exists

### Max Active Specialists

Maximum `max_active_specialists` (default 3) can be active simultaneously. If more are needed, prioritize by domain signal strength. Defer lower-priority specialists (their insights can be incorporated in future runs).

**Exception:** TEST ARCHITECT and GUARDIAN (when `guardian.mode: always_on`) do not count toward the cap — they are mandatory and always run.

### Dispatch Specialists

For each specialist to summon, dispatch sequentially (unless they are independent — INVESTIGATOR investigations can run in parallel with domain specialists).

#### SCIENTIST Dispatch (INVESTIGATOR codename) — if summoned

Context pack:

- Specific question(s) from `unknowns.md`
- Relevant artifacts (select based on the question — do not send everything)
- `reasoning-journal.json`

Use the Agent tool:

- **prompt:** Read the file `agents/specialists/investigator.md` for your complete instructions. You are the INVESTIGATOR agent. Investigate the following unknowns: [list from unknowns.md]. Follow the full scientific method: QUESTION, RESEARCH, EVALUATE (grade A-E), HYPOTHESIZE, EXPERIMENT (if feasible — use git worktree via `scripts/bash/setup-worktree.sh`), MEASURE, SYNTHESIZE, RECOMMEND. Here is your context pack: [include files]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "INVESTIGATOR: investigating unknowns — {topic summary}"

#### SECURITY Dispatch (GUARDIAN codename) — always-on by default

**Dispatch mode** is controlled by `squad-config.yml` → `guardian.mode` (default: `always_on`).

- **`always_on`**: Dispatch GUARDIAN on every run. If the domain is NOT security-sensitive, GUARDIAN runs only the **Minimum Security Checklist** (5-item lightweight check). If security-sensitive, GUARDIAN runs the full STRIDE + OWASP + compliance analysis.
- **`on_demand`**: Dispatch only when domain involves auth, payments, PII, regulatory compliance (legacy behavior).

Context pack:

- `spec.md` + `boundaries.md` + domain-relevant artifacts
- `reasoning-journal.json`

Use the Agent tool:

- **prompt:** Read the file `agents/specialists/guardian.md`. You are the GUARDIAN agent. Guardian mode is `{guardian.mode}`. If always_on and domain is non-security: run the Minimum Security Checklist only. If domain is security-relevant OR mode is on_demand with security domain: perform full STRIDE threat modeling, OWASP Top 10, compliance analysis. Here is your context pack: [include files]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "GUARDIAN: security analysis (mode: {guardian.mode})"

#### DOMAIN EXPERT Dispatch (if summoned)

Context pack:

- Domain-relevant artifacts from `specs/{feature}/`
- `reasoning-journal.json`

Use the Agent tool:

- **prompt:** Read the file `agents/specialists/oracle.md`. You are the ORACLE agent for {domain}. Provide domain patterns, regulatory requirements, common pitfalls, and terminology corrections. Here is your context pack: [include files]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "ORACLE: {domain} domain analysis"

#### PERFORMANCE Dispatch (if summoned)

Context pack:

- `spec.md` + `boundaries.md` + performance-relevant requirements
- `reasoning-journal.json`

Use the Agent tool:

- **prompt:** Read the file `agents/specialists/benchmark.md`. You are the BENCHMARK agent. Perform load modeling, capacity planning, identify bottleneck risks. Here is your context pack: [include files]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "BENCHMARK: load modeling and capacity analysis"

#### UX / A11Y Dispatch (if summoned)

Context pack:

- `spec.md` + user-facing requirements
- `reasoning-journal.json`

Use the Agent tool:

- **prompt:** Read the file `agents/specialists/advocate.md`. You are the ADVOCATE agent. Analyze WCAG 2.1/2.2 compliance needs, apply Nielsen's heuristics, map user flows. Here is your context pack: [include files]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "ADVOCATE: accessibility and usability analysis"

#### INNOVATE Dispatch (if summoned)

Context pack:

- All current artifacts
- Prior run's `evolution-report.md`
- `reasoning-journal.json`

Use the Agent tool:

- **prompt:** Read the file `agents/specialists/maverick.md`. You are the MAVERICK agent. Propose 2-3 fundamentally different approaches using TRIZ, Design Thinking, or First Principles. Challenge established assumptions. Here is your context pack: [include files]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "MAVERICK: alternative approaches and assumption challenges"

### Post-Specialist

After all specialists complete, collect their outputs. Update `state.json.active_specialists` with the list of specialists that ran.

Before this transition, COMMANDER performs phase-boundary timing writes in order:

1. Close `phase2-decide` by calling `scripts/bash/phase-timing.sh end_phase phase2-decide`.
2. Open `phase3-solution` by calling `scripts/bash/phase-timing.sh start_phase phase3-solution 2400`.
3. `end_phase` writes `end_ts`, `elapsed_seconds`, `over_budget`, and `anomaly_reason`; if over budget (>120%), it also appends a `timing_anomaly` journal entry.
4. Persist state updates before routing to HOW.

**Transition:** Update state.json phase to "how". Proceed to HOW.

---

## 8. HOW Phase (Architecture)

### Context Pack Assembly

Read and include in the subagent prompt:

- `spec.md` + `feasibility.md` + `prioritization.md`
- `constitution.md` (if exists from prior run or user provided)
- All specialist outputs (threat-model.md, performance-requirements.md, etc.)
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:** Read the file `agents/solution/architect.md` for your complete instructions. You are the ARCHITECT agent. Select technology stack with explicit rationale. Design system structure (data model, API contracts, component architecture). Define cross-cutting concerns as architectural decisions. Document every decision in ADR format. Here is your context pack: [include files]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "ARCHITECT: architecture design and technology decisions"

### Expected Outputs

- `plan.md`
- `research.md`
- `data-model.md`
- `contracts/` (API/interface specs)
- `constitution.md`

**Transition:** Update state.json phase to "test-architect". Proceed to TEST ARCHITECT.

---

## 9. TEST ARCHITECT Phase (Mandatory)

### Context Pack Assembly

Read and include in the subagent prompt:

- `plan.md` + `data-model.md`
- `spec.md` (acceptance criteria)
- `contracts/`
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:** Read the file `agents/solution/sentinel.md` for your complete instructions. You are the SENTINEL agent. Produce a comprehensive test strategy from plan.md + data-model.md + spec.md acceptance criteria. Map every acceptance criterion to a test approach. Define the test pyramid. Identify boundary value cases. If acceptance criteria have no testable form, flag them for routing back to CARTOGRAPHER. Here is your context pack: [include files]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "SENTINEL: test strategy and coverage mapping"

### Expected Outputs

- `test-strategy.md`
- `test-architecture.md`
- `coverage-map.md`

### Gate Check

If TEST ARCHITECT flags untestable acceptance criteria → route back to WHAT for amendment. Increment iteration. Check limits.

Before this transition, COMMANDER updates timing state via `scripts/bash/phase-timing.sh`:

1. Keep `phase3-solution` open (intra-phase transition: `test-architect` -> `plan`).
2. If missing from recovered state, initialize `phase3-solution` using `start_phase phase3-solution 2400` before dispatching PLAN.
3. Persist `state.json` timing updates before dispatch.

**Transition:** Update state.json phase to "plan". Proceed to PLAN.

---

## 10. PLAN Phase (Task Breakdown)

### Context Pack Assembly

Read and include in the subagent prompt:

- `plan.md` + `research.md` + `data-model.md`
- `contracts/` + `test-strategy.md`
- Risk data from specialists (threat-model.md, performance-requirements.md, etc.)
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:** Read the file `agents/solution/orchestrator.md` for your complete instructions. You are the ORCHESTRATOR agent — operational PM. Break the architecture into executable tasks (foundation, features, polish). Identify the critical path. Map task dependencies and parallelization. Assess risk per task. Include test tasks from test-strategy.md. Here is your context pack: [include files]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "ORCHESTRATOR: task breakdown, critical path, dependencies, risk"

### Expected Outputs

- `tasks.md`
- `critical-path.md`
- `risk-matrix.md`
- `dependencies.md`

Before this transition, COMMANDER performs phase-boundary timing writes in order:

1. Close `phase3-solution` with `scripts/bash/phase-timing.sh end_phase phase3-solution`.
2. Open `phase4-build` with `scripts/bash/phase-timing.sh start_phase phase4-build 7200`.
3. Confirm updated `phase_timings` are flushed to `state.json` before consensus dispatch.

**Transition:** Update state.json phase to "consensus". Proceed to CONSENSUS.

---

## 11. CONSENSUS Phase (Parallel Validation)

This phase runs **WHY3 + ASSESS2 + PLAN2 in parallel** using multiple Agent tool calls in a single message. If specialists are still active, include them in the parallel dispatch.

### 11.1 WHY3 Context Pack

- All artifacts in `specs/{feature}/` (spec, plan, tasks, specialist outputs)
- Understanding CLI access
- `calibration-profile.yaml`
- `reasoning-journal.json`

### 11.2 ASSESS2 Context Pack

- `plan.md` + `data-model.md` + `contracts/`
- `tasks.md` + `estimates.md`
- `constitution.md` (team constraints)
- `reasoning-journal.json`

### 11.3 PLAN2 Context Pack

- Updated `plan.md` + `test-strategy.md`
- All specialist outputs
- `implementability-report.md` (from ASSESS2 — dispatch ASSESS2 first, then PLAN2 reads its output)
- `reasoning-journal.json`

### Dispatch (Parallel)

Dispatch WHY3 and ASSESS2 in parallel (single message, two Agent tool calls):

**WHY3:**

- **prompt:** Read the file `agents/exploration/sage.md`. You are WHY operating in **spec-validation mode** (WHY3 — consensus). Run full Understanding quality gates. Check cross-artifact consistency across ALL artifacts. This is the final quality check. Here is your context pack: [include files]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "WHY3: final quality validation and cross-artifact consistency"

**ASSESS2:**

- **prompt:** Read the file `agents/feasibility/gatekeeper.md`. You are ASSESS2 — consensus-phase re-evaluation. Re-evaluate feasibility against the concrete architecture. Update effort estimates with architectural complexity. Perform the **6-point IMPLEMENTABILITY CHECK**: (1) Can a developer pick up each task without unstated knowledge? (2) Do tasks reference APIs/libraries/services that actually exist? (3) Are "parallel" tasks truly independent? (4) Does the tech stack match available team skills? (5) Are task descriptions self-contained? (6) Can each task be tested independently? Produce `implementability-report.md` (scored per task: READY / NEEDS_CLARIFICATION / BLOCKED). You can flag but NOT kill at this stage — only CRITICAL feasibility issues route back to HOW. Here is your context pack: [include files]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "ASSESS2: implementability check and effort re-estimation"

After WHY3 and ASSESS2 complete, dispatch PLAN2:

**PLAN2:**

- **prompt:** Read the file `agents/solution/orchestrator.md`. You are PLAN2 — consensus-phase plan revision. Re-evaluate task dependencies with specialist-added tasks. Update critical path if specialist work changed sequencing. Validate all specialist outputs have corresponding tasks. Incorporate implementability feedback — split unclear tasks, add missing context. Here is your context pack: [include files — include ASSESS2's implementability-report.md]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "PLAN2: plan revision incorporating implementability feedback"

### Consensus Gate Check

Read outputs from all three consensus agents:

- **ALL PASS** (no CRITICAL issues, quality gates met, all tasks READY or NEEDS_CLARIFICATION with fixes applied) → proceed to FINALIZE
- **MINOR issues only** → MANAGER resolves directly (update artifacts, log reasoning). Re-run consensus if changes are significant.
- **CRITICAL issues** → route back to the responsible phase:
  - WHY3 CRITICAL spec issues → back to WHAT
  - ASSESS2 CRITICAL feasibility issues → back to HOW
  - PLAN2 missing tasks for specialist outputs → back to PLAN
  - Increment iteration. Check limits.

Before this transition, COMMANDER updates timing state via `scripts/bash/phase-timing.sh`:

1. Keep `phase4-build` open for `consensus` -> `finalize` (same phase).
2. If `phase4-build.start_ts` is missing (resume edge case), run `start_phase phase4-build 7200` before dispatching FINALIZE.
3. Persist `state.json` before dispatch.

At run close (after FINALIZE and before setting status `done`), COMMANDER must:

1. Call `scripts/bash/phase-timing.sh end_phase phase4-build`.
2. Read `state.json.phase_timings` and append one `timing_summary` entry per phase to `reasoning-journal.json` with fields: `type`, `phase`, `run_id`, `elapsed_seconds`, `budget_seconds`, `over_budget`, `anomaly_reason`.
3. Ensure anomaly reason enum for Tier 1 is exactly `EXCEEDED_BUDGET_20_PERCENT`.

**Transition:** Update state.json phase to "finalize". Proceed to FINALIZE.

---

## 12. FINALIZE Phase

### 12.1 GROUND Agent

Context pack:

- All artifacts in `specs/{feature}/`
- `calibration-profile.yaml` + `estimates-log.yaml`
- `reasoning-journal.json`

Use the Agent tool:

- **prompt:** Read the file `agents/learning/realist.md`. You are the REALIST agent. Reality-check all artifacts. Connect plans to real-world data: infrastructure costs, production benchmarks, team capacity. Compare estimates to past outcomes via FEEDBACK data. Check architectural decisions against operational constraints. Flag disconnects. Here is your context pack: [include files]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "REALIST: reality check and reference class forecasting"

Expected outputs: `reality-check.md`, `cost-analysis.md`, `benchmark-data.md`

### 12.2 REFLECT Agent

Context pack:

- All artifacts in `specs/{feature}/`
- `reasoning-journal.json`
- `knowledge-base/patterns.yaml` + `knowledge-base/pitfalls.yaml`

Use the Agent tool:

- **prompt:** Read the file `agents/learning/mirror.md`. You are the MIRROR agent. Perform post-run analysis. Extract what assumptions were wrong, which patterns worked, what the squad should do differently. Log reusable patterns and pitfalls to the knowledge base. Here is your context pack: [include files]. Update `knowledge-base/patterns.yaml` and `knowledge-base/pitfalls.yaml`. Append entries to `reasoning-journal.json`.
- **description:** "MIRROR: post-run learning extraction"

### 12.3 EVOLVE Agent (if re-run)

Only dispatch if `state.json.iteration > 0` or prior run artifacts exist.

Context pack:

- All current artifacts
- Prior run artifacts (for diffing)
- `reasoning-journal.json`
- `knowledge-base/` files

Use the Agent tool:

- **prompt:** Read the file `agents/learning/adaptive.md`. You are the ADAPTIVE agent. Diff artifacts between this run and prior runs. Measure quality trajectory. Detect regressions. Flag stagnation (if no improvement, recommend triggering INNOVATE on next run). Check for confirmation bias in knowledge base entries. Here is your context pack: [include files]. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "ADAPTIVE: cross-run diffing and improvement measurement"

Expected outputs: `evolution-report.md`, `improvement-metrics.md`, `regression-alerts.md`

### 12.4 CALIBRATE Agent

Context pack:

- All artifacts in `specs/{feature}/`
- `knowledge-base/calibration-profile.yaml`
- `knowledge-base/estimates-log.yaml`
- `reasoning-journal.json`
- Quality scores from all WHY passes (from state.json)

Use the Agent tool:

- **prompt:** Read the file `agents/learning/auditor.md`. You are the AUDITOR agent. Track AI accuracy per domain. Build/update the confidence profile. Adjust ASSESS estimate multipliers based on historical data. Flag low-confidence domains for human input or INVESTIGATOR investigation. Here is your context pack: [include files]. Update `knowledge-base/calibration-profile.yaml`. Produce `confidence-flags.md` in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "AUDITOR: accuracy tracking and confidence profiling"

### 12.5 CALIBRATE Confidence Check

After CALIBRATE completes, read `confidence-flags.md`:

- If any domain has **confidence < 0.5** → summon INVESTIGATOR for that domain (if not already investigated). This is a late-stage safety net.
- If INVESTIGATOR was already summoned and confidence is still < 0.5 → flag for human in the final report (do not block delivery).

### 12.6 Collect Final Artifacts

Verify all expected artifacts exist in `specs/{feature}/`. Create a manifest:

```
Artifact                          | Producer        | Status
----------------------------------|-----------------|--------
glossary.md                       | DISCOVER        | OK/MISSING/UNVALIDATED
mental-model.md                   | DISCOVER        | ...
boundaries.md                     | DISCOVER        | ...
assumptions.md                    | DISCOVER+WHY    | ...
unknowns.md                       | DISCOVER+WHY    | ...
spec.md                           | WHAT            | ...
feasibility.md                    | ASSESS          | ...
prioritization.md                 | ASSESS          | ...
estimates.md                      | ASSESS          | ...
mvp-scope.md                      | ASSESS          | ...
plan.md                           | HOW             | ...
research.md                       | HOW+INVESTIGATOR   | ...
data-model.md                     | HOW             | ...
contracts/                        | HOW             | ...
constitution.md                   | HOW             | ...
tasks.md                          | PLAN            | ...
critical-path.md                  | PLAN            | ...
risk-matrix.md                    | PLAN            | ...
dependencies.md                   | PLAN            | ...
test-strategy.md                  | TEST ARCHITECT  | ...
test-architecture.md              | TEST ARCHITECT  | ...
coverage-map.md                   | TEST ARCHITECT  | ...
issues.md                         | WHY             | ...
quality-gates.md                  | WHY             | ...
reality-check.md                  | GROUND          | ...
cost-analysis.md                  | GROUND          | ...
benchmark-data.md                 | GROUND          | ...
implementability-report.md        | ASSESS2         | ...
reasoning-journal.json            | ALL             | ...
confidence-flags.md               | CALIBRATE       | ...
```

Additional artifacts (conditional):

- `reference-architectures.md` (greenfield only)
- `assumption-review.md` (if WHY1 produced it)
- `investigation/*.md` (if INVESTIGATOR ran)
- `evidence-grades.md` (if INVESTIGATOR ran)
- `experiment-results.md` (if INVESTIGATOR ran)
- `recommendations.md` (if INVESTIGATOR ran)
- `threat-model.md` (if SECURITY ran)
- `compliance-requirements.md` (if SECURITY ran)
- `performance-requirements.md` (if PERFORMANCE ran)
- `capacity-model.md` (if PERFORMANCE ran)
- `accessibility-requirements.md` (if UX/A11Y ran)
- `user-flow.md` (if UX/A11Y ran)
- `alternatives.md` (if INNOVATE ran)
- `evolution-report.md` (if EVOLVE ran)

### 12.7 Run SCOREKEEPER

Dispatch SCOREKEEPER to produce the final scorecard (see Section 13 for full protocol).
Read the scorecard output and apply any automatic self-healing actions.

### 12.8 Set Final State

Update `state.json`:

```json
{
  "status": "done",
  "phase": "done",
  "updated_at": "{ISO-8601}"
}
```

### 12.8.1 Stop RADAR

```bash
# Stop RADAR if running
if [ -f .specify/squad/radar.pid ]; then
  kill $(cat .specify/squad/radar.pid) 2>/dev/null || true
  rm -f .specify/squad/radar.pid
fi
```

### 12.8 Print Final Summary

Print to terminal:

```
============================================
  COGNITIVE SQUAD RUN COMPLETE
============================================

Run ID:     {run_id}
Feature:    {NNN}-{feature}
Mode:       {greenfield|brownfield}
Iterations: {count}
Duration:   {elapsed time}

QUALITY SCORES (final WHY pass):
  Overall:     {score} {pass/fail}
  Structure:   {score} {pass/fail}
  Testability: {score} {pass/fail}
  Semantic:    {score} {pass/fail}
  Cognitive:   {score} {pass/fail}
  Readability: {score} {pass/fail}

SPECIALISTS SUMMONED: {list}

ARTIFACTS: {count} files in specs/{NNN}-{feature}/

AGENT SCORECARD:
  Top performer: {agent} (+{score}) — {highlight}
  Badges earned: {count} ({badge names})
  Peer appreciation: {count} exchanges
  Self-healing: {count} recommendations

WARNINGS:
  {any UNVALIDATED artifacts}
  {any low-confidence domains}
  {any unresolved unknowns}

Spec ID for feedback: {NNN}
Run: /speckit.cognitive-squad.feedback {NNN} after implementation

BRANCH: {NNN}-{feature}
Ready for: /speckit.cognitive-squad.build {NNN}-{feature}
============================================
```

### 12.9 Archive and Cleanup Staging Area

Archive the completed run artifacts, then clean staging:

```bash
# Archive this run's artifacts
RUN_ID=$(python3 -c "import json; print(json.load(open('.specify/squad/state.json')).get('run_id','unknown'))" 2>/dev/null || echo "unknown")
ARCHIVE_DIR=".specify/squad/archive/${RUN_ID}"
mkdir -p "$ARCHIVE_DIR"
cp -r .specify/squad/staging/* "$ARCHIVE_DIR/" 2>/dev/null || true
cp .specify/squad/state.json "$ARCHIVE_DIR/state.json" 2>/dev/null || true
echo "Run archived → ${ARCHIVE_DIR}/"

# Clean staging for next run
rm -rf .specify/squad/staging
```

**What's preserved in the archive:**
- `spec.md`, `tasks.md`, `plan.md` — the analysis products
- `issues.md`, `quality-gates.md` — findings and quality scores
- `reasoning-journal.json` — full decision log
- `state.json` — run state snapshot
- All specialist outputs (threat-model.md, etc.)

**What lives in knowledge-base/ (already persistent):**
- `calibration-profile.yaml` — per-domain accuracy corrections
- `estimates-log.yaml` — predicted vs actual effort records
- `patterns.yaml`, `pitfalls.yaml` — reusable learnings
- `feedback/` — post-implementation outcome data
- `agent-scores.yaml` — agent performance history

### 12.10 Branch Stacking (Next Spec)

When the user starts a new squad run while implementation of the current spec is in progress:

1. The new spec will be created on a new branch via `/speckit.specify`
2. Spec-kit handles branch stacking (new branch based on current feature branch)
3. This allows parallel specification work while implementation continues

**DONE.** The squad run is complete. The feature branch `{NNN}-{feature}` is ready for `/speckit.cognitive-squad.build`.

---

## 13. Scorekeeper Protocol

SCOREKEEPER runs throughout the entire squad execution — not as a separate phase, but woven into every agent dispatch.

### After Every Agent Dispatch

After reading an agent's output, MANAGER scores the agent:

```
1. Read the agent's output quality:
   - Did WHY pass or fail? → +5 for CRITICAL catch, -1 for false positive
   - Did WHAT need rework? → -1 per WHY rejection
   - Did IMPLEMENTER pass first review? → +3 first-pass, -1 rework
   - Did INVESTIGATOR validate an assumption? → +2 validated, +4 invalidated (more valuable)

2. Append to state.json.agent_scores:
   {
     "agent": "{AGENT_NAME}",
     "action": "{what they did}",
     "points": {N},
     "reason": "{why these points}"
   }
```

### Peer Appreciation Collection

When an agent's output is consumed by the NEXT agent, check: did the next agent benefit from high-quality input?

```
IF WHAT produces spec.md AND WHY2 passes on first attempt:
  → Peer appreciation: WHY awards WHAT +2 "clear_and_actionable"

IF INVESTIGATOR produces investigation/ AND HOW makes a decision based on it:
  → Peer appreciation: HOW awards INVESTIGATOR +3 "unblocked_my_work"

IF WHY catches an issue that SPEC GUARD would have missed:
  → Peer appreciation: SPEC GUARD awards WHY +2 "caught_my_mistake"
```

Record in reasoning-journal.json:

```json
{
  "type": "peer_appreciation",
  "from": "{agent giving appreciation}",
  "to": "{agent receiving}",
  "points": {N},
  "reason": "{why}"
}
```

### During FINALIZE — Full Scorecard

After GROUND + REFLECT + EVOLVE + CALIBRATE, dispatch SCOREKEEPER:

Use the Agent tool to dispatch a subagent with:

- **prompt:** Read the file `agents/control/scorekeeper.md` for your complete instructions. You are the SCOREKEEPER. Read `state.json.agent_scores` for all points accumulated during this run. Read `reasoning-journal.json` for peer appreciation entries. Read `knowledge-base/agent-scores.yaml` for lifetime scores. Calculate final run scores per agent. Check badge criteria. Produce `agent-scorecard.md`. Check self-healing triggers. Update `knowledge-base/agent-scores.yaml` with run history.
- **description:** "SCOREKEEPER: final scoring, badges, self-healing recommendations"

Context pack:

- state.json (with agent_scores array)
- reasoning-journal.json (with peer_appreciation entries)
- knowledge-base/agent-scores.yaml (lifetime data)
- config-template.yml → scoring section (point values, thresholds)

### Expected SCOREKEEPER Outputs

- `.specify/specs/{feature}/agent-scorecard.md` — leaderboard, peer appreciation, self-healing recommendations
- Updated `knowledge-base/agent-scores.yaml` — run history appended, lifetime scores updated, badges awarded

### Self-Healing Actions (MANAGER executes immediately)

Read SCOREKEEPER's self-healing recommendations and apply:

| Recommendation | MANAGER Action |
|---------------|---------------|
| "ASSESS correction factor should increase to 1.5x" | Update calibration-profile.yaml |
| "WHY false positive rate > 30%" | Log for human review (prompt refinement) |
| "IMPLEMENTER score < -5 over 3 runs" | Log for human review (prompt refinement) |
| "TEST GUARDIAN score low — add test pattern examples" | Log for human review |

Self-healing that affects calibration-profile.yaml is automatic. Self-healing that affects agent prompts is flagged for human review.

---

## 14. State Tracking Protocol

After **every** phase transition, update `.specify/squad/state.json`:

```json
{
  "phase": "{new_phase}",
  "updated_at": "{ISO-8601}",
  "iteration": "{current_iteration}"
}
```

After every agent dispatch, check if the agent appended to `reasoning-journal.json`. If not, append a MANAGER entry noting the agent completed without journal entries.

Track cumulative token usage in `state.json.token_usage` (estimate based on prompt + response sizes).

Track issues in `state.json.issues_log[]`:

```json
{
  "id": "ISS-{NNN}",
  "severity": "CRITICAL|HIGH|MEDIUM|LOW",
  "source": "{agent_name}",
  "description": "{issue}",
  "resolved": false,
  "occurrences": 1
}
```

When the same issue appears again, increment `occurrences` rather than creating a duplicate.

---

## 14. Convergence Rules

These rules prevent infinite loops and ensure the squad terminates:

### Rule 1: Understanding Delta Convergence

- After each WHY pass (WHY2, WHY3), record quality scores in `state.json.quality_scores[]`
- If the delta between the last two passes is < `convergence_delta` (default 0.02) for 2 consecutive passes → **stop WHY iterations**
- Proceed to next phase even if gates are not fully met — flag as "best-effort convergence"

### Rule 2: Circular Issue Detection

- If the same issue (matched by description similarity) appears 3 times in `state.json.issues_log[].occurrences` → **defer or escalate**
- First: attempt INNOVATE (propose alternative approach that avoids the issue)
- If INNOVATE already tried: escalate to human (see Section 15)

### Rule 3: Max Iterations

- Maximum `max_iterations` (default 5) total squad iterations → **force convergence**
- When forced: run FINALIZE with whatever artifacts exist, flag all as "forced convergence"
- DEFER re-routes count toward the iteration max

### Rule 4: Token Budget Exhaustion

- If cumulative `token_usage` exceeds `token_budget_k * 1000` → **force finalize**
- Skip remaining specialists if budget is tight
- Always run GROUND + CALIBRATE (minimum finalize)

### Rule 5: CALIBRATE Confidence Gate

- If CALIBRATE reports confidence < 0.5 for a critical domain → **summon INVESTIGATOR**
- If INVESTIGATOR already ran for that domain and confidence is still < 0.5 → flag for human, do not block

### Rule 6: ASSESS DEFER Loop

- If ASSESS returns DEFER >= 2 times with no scope stabilization → **kill or escalate**
- Produce kill report OR escalation request (MANAGER decides based on severity)

---

## 15. Error Handling

### External Tool Failures

| Tool | Failure | Fallback |
|------|---------|----------|
| Understanding extension | Skill invocation fails or PROSPECTOR finds no `speckit.understanding.*` skills | **HARD STOP for WHY2/WHY3.** SAGE invokes `/speckit.understanding.validate` via the Skill tool (not as a CLI binary). If unavailable, SAGE does NOT fall back to heuristic review — proven 15-29% overconfident (PAT-006), corrupts calibration data. COMMANDER sets state to "blocked" and escalates to human. WHY1 (assumption-challenge mode) does not require Understanding and is unaffected. |
| spec-kit-reverse-eng | PROSPECTOR fails or reverse-eng not installed | COMMANDER treats as empty-extensions; SCOUT proceeds without brownfield-index.md using manual structural analysis. Run flagged as degraded-brownfield in state.json. |
| spec-kit skills | Skill invocation fails or PROSPECTOR finds no `speckit.*` skills | HOW and PLAN produce artifacts manually as markdown. No spec-kit validation. Flag as UNVALIDATED. spec-kit commands (e.g. `/speckit.specify`, `/speckit.constitution`) are AI coding assistant skills, not CLI tools — availability is detected by PROSPECTOR from the agent's context, not by filesystem scanning. |

### Subagent Failures

- **Timeout** (agent takes > 5 minutes): Retry once. If second attempt also times out, skip the agent with a warning in the final report. Continue to next phase.
- **Error output** (agent produces malformed or empty output): Log the error, skip the agent, continue. Flag missing artifacts as MISSING.
- **Crash**: Same as timeout — retry once, then skip.

### Degraded Mode Artifacts

Every artifact produced in degraded mode (fallback was used) must have this banner at the top:

```markdown
> **UNVALIDATED** — This artifact was produced without {tool_name}. Quality has not been deterministically verified. Treat with additional scrutiny.
```

---

## 16. Human Escalation Protocol

### When Triggered

Escalation to human is triggered when:

1. Same issue appears 3x without resolution (after INNOVATE attempt)
2. CALIBRATE confidence < 0.5 after INVESTIGATOR investigation
3. Unresolvable conflict between agents (evidence hierarchy cannot resolve)
4. ASSESS DEFER loop >= 2 with no scope stabilization

### Escalation Procedure

1. **Produce escalation request:** Read `templates/escalation-request.md` and fill in all placeholders:
   - `{TOPIC}` — the specific blocked issue
   - `{RUN_ID}` — current run ID
   - `{CURRENT_PHASE}` — phase where escalation was triggered
   - The specific question, context, options considered, recommended answer

2. **Write to file:** Save as `specs/{feature}/escalation-request.md`

3. **Update state:** Set `state.json`:

   ```json
   {
     "status": "blocked",
     "blocked_reason": "{description of what is blocked}",
     "escalation_question": "{the specific question}"
   }
   ```

4. **Print to terminal:**

   ```
   ============================================
     SQUAD BLOCKED — HUMAN INPUT REQUIRED
   ============================================

   Question: {the specific question}

   Context: {1-2 sentence summary}

   Options:
     A: {option A}
     B: {option B}
     C: {option C}

   Recommended: {option}

   Respond with: /speckit.cognitive-squad.resume {your answer}
   ============================================
   ```

5. **STOP execution.** Do not proceed. The user must run `/speckit.cognitive-squad.resume` to continue.

---

## 17. Evidence Hierarchy (Conflict Resolution)

**See `agents/control/commander.md` → "Evidence Hierarchy" and "Conflict Resolution Protocol" sections.** The COMMANDER prompt is the authoritative source for the 5-rank evidence hierarchy, Toulmin-model conflict resolution, and the "never resolve by averaging" principle. All conflict resolutions are recorded in `reasoning-journal.json` with type "decision".

---

## 18. Token Budget Management

**See `agents/control/commander.md` → "Token Budget Management" section.** The COMMANDER prompt is the authoritative source for budget allocation tiers, borrow rules between tiers, and the 40% single-agent cap.

### Budget Enforcement (phase-specific skip rules)

- Before each agent dispatch, check remaining budget per the COMMANDER's allocation tiers
- If remaining budget < estimated cost for the agent → check if phase can be skipped
  - DISCOVER, WHAT, WHY, ASSESS, HOW, PLAN: **cannot be skipped** — force finalize instead
  - Specialists (except TEST ARCHITECT): can be deferred
  - CONSENSUS: can be reduced (run WHY3 only, skip ASSESS2 + PLAN2)
  - FINALIZE: always run GROUND + CALIBRATE at minimum

---

## 19. Re-Run Behavior

When this command runs against a feature that already has artifacts:

1. **INIT** detects prior artifacts, sets `iteration` appropriately
2. **EVOLVE** is dispatched at the start of FINALIZE to diff against prior run
3. **All agents** receive prior artifacts in their context packs
4. **INNOVATE** may be summoned if EVOLVE detects stagnation
5. **CALIBRATE** compares quality trajectory across runs
6. Knowledge base entries from prior runs are available to all agents

The goal of re-runs is monotonic improvement: each run should produce artifacts at least as good as the prior run, and ideally better. EVOLVE measures this. If improvement stalls for 2 consecutive runs, INNOVATE is summoned to break out of local optima.

---

## 20. Quick Reference: Phase Transitions

```
INIT ──────► DISCOVER ──► SYNTHESIZER ──► WHY1 ──► WHAT
                  ▲                 │                 │
                  │ (re-investigate) │ (CRITICAL)      │
                  └─────────────────┘                 ▼
                                                    WHY2
                                                      │
                               ┌──────────────────────┤
                               │ (gates fail)         │ (gates pass)
                               ▼                      ▼
                             WHAT ◄────────────── ASSESS
                                                      │
                                    ┌─────────────────┤
                                    │ KILL            │ DEFER (≥2 → kill/escalate)
                                    ▼                 │ PASS
                                   DONE               ▼
                                              SPECIALISTS
                                                      │
                                                      ▼
                                                    HOW
                                                      │
                                                      ▼
                                              TEST ARCHITECT
                                                      │
                                                      ▼
                                                    PLAN
                                                      │
                                                      ▼
                                                 CONSENSUS
                                              (WHY3 ∥ ASSESS2)
                                                 then PLAN2
                                                      │
                               ┌──────────────────────┤
                               │ CRITICAL             │ ALL PASS
                               ▼                      ▼
                          (route back)           FINALIZE
                                              GROUND → REFLECT
                                              → EVOLVE → CALIBRATE
                                                      │
                                                      ▼
                                                    DONE
```

---

## 21. Checklist (MANAGER Self-Verification)

Before declaring DONE, verify:

- [ ] All phases executed (or explicitly skipped with documented reason)
- [ ] `state.json` reflects final state accurately
- [ ] `reasoning-journal.json` has entries from every dispatched agent
- [ ] All quality gate results are recorded in `quality-gates.md`
- [ ] All UNVALIDATED artifacts are clearly flagged
- [ ] All CRITICAL issues are either resolved or documented as unresolved
- [ ] Specialist outputs are incorporated into plan and tasks
- [ ] TEST ARCHITECT ran (mandatory)
- [ ] `implementability-report.md` exists with per-task scores
- [ ] Knowledge base files updated (patterns.yaml, pitfalls.yaml, calibration-profile.yaml)
- [ ] SCOREKEEPER ran — agent-scorecard.md produced
- [ ] agent-scores.yaml updated with run history
- [ ] Self-healing recommendations applied (calibration) or logged (prompt refinement)
- [ ] Final summary printed to terminal with spec ID and scorecard summary
