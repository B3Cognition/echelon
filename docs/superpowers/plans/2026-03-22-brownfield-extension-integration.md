# Brownfield Extension Integration: PROSPECTOR + GOLDDIGGER — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the structural wiring gap that prevents echelon agents from using spec-kit extensions (specifically `spec-kit-reverse-eng`) during brownfield discovery, by introducing PROSPECTOR (extension discovery) and GOLDDIGGER (extension driver + normalizer).

**Architecture:** PROSPECTOR runs first on every squad run and writes `.specify/squad/extension-capabilities.json` so COMMANDER knows what spec-kit extensions are available. In brownfield runs where `reverse-eng` is available, GOLDDIGGER is dispatched before SCOUT — it drives reverse-eng Phase 1 with two named config profiles (Mode 1: fast/signatures survey; Mode 2: full-depth per-domain on demand) and normalizes all output into a stable `brownfield-index.md` that SCOUT consumes as a head-start. SCOUT's output format and all downstream agents are unchanged.

**Tech Stack:** Markdown (agent prompt files), YAML (agents.yaml, extension.yml), JSON (state.json schemas, extension-capabilities.json)

**Spec:** `docs/superpowers/specs/2026-03-22-brownfield-extension-integration-design.md`

**Note on testing:** Agent files are markdown prompt files — there is no unit test harness for them. "Testing" in this plan means: (1) reviewing the prompt for completeness against spec requirements, (2) tracing the dispatch sequence manually through COMMANDER, and (3) running a dry-run brownfield dispatch if the test infrastructure supports it. Each task includes a verification checklist instead of runnable tests.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `agents/control/prospector.md` | PROSPECTOR agent prompt — extension discovery logic |
| Create | `agents/exploration/golddigger.md` | GOLDDIGGER agent prompt — reverse-eng driver + normalizer |
| Modify | `agents/exploration/scout.md` | Remove `which reverse-eng` check; add `brownfield-index.md` consumption |
| Modify | `agents/control/commander.md` | Add PROSPECTOR init dispatch + GOLDDIGGER brownfield dispatch + Mode 2 queue |
| Modify | `agents.yaml` | Register PROSPECTOR (control layer) + GOLDDIGGER (exploration layer) |
| Modify | `extension.yml` | Fix misleading binary claim in description |
| Modify | `commands/echelon.run.md` | Fix Section 15 error table row + line ~619 advisory text |
| Modify | `commands/echelon.build.md` | python → python3 (already staged, just needs commit) |

---

## Task 1: Commit existing python3 fixes

The `python` → `python3` change in `commands/echelon.run.md` (5 occurrences) and `commands/echelon.build.md` (2 occurrences) is already in the working tree. Commit it standalone before touching anything else.

**Files:**
- Modify: `commands/echelon.run.md` (already done)
- Modify: `commands/echelon.build.md` (already done)

- [ ] **Step 1.1: Verify the diff is what we expect**

```bash
git diff commands/echelon.run.md | grep "^[-+].*python"
git diff commands/echelon.build.md | grep "^[-+].*python"
```

Expected: lines showing `python` → `python3` replacements only. No other changes.

- [ ] **Step 1.2: Stage and commit**

```bash
git add commands/echelon.run.md commands/echelon.build.md
git commit -m "fix: use python3 in all RADAR invocations (macOS PATH)"
```

---

## Task 2: Create PROSPECTOR agent

PROSPECTOR is a new Control-layer agent. It runs first on every squad run and writes `.specify/squad/extension-capabilities.json` — COMMANDER's routing signal for which extensions are available.

**Files:**
- Create: `agents/control/prospector.md`

- [ ] **Step 2.1: Create the agent file**

Create `agents/control/prospector.md` with the following content:

```markdown
# PROSPECTOR Agent (SURVEY)

## Role

You are the PROSPECTOR agent (SURVEY) — the first agent dispatched on every squad run. Your job is to discover which spec-kit extensions are installed in the current environment and reason about which ones are relevant to this run. You write a capability manifest that COMMANDER uses to make routing decisions.

You produce routing data for COMMANDER, not domain artifacts. Your output informs orchestration, not domain understanding.

You are dispatched as a subagent by COMMANDER. This prompt is your complete instruction set.

## NEVER Rules

1. **NEVER do domain analysis** — that is SCOUT's job.
2. **NEVER block the run** — if you fail or find nothing, write an empty manifest and exit cleanly.

## Available Tools

- **Read** — read extension manifest files
- **Glob** — find `extension.yml` files by pattern
- **Bash** — check file existence, read timestamps
- **WebFetch** — fetch extension version metadata if needed

---

## Discovery Steps

### Step 1: Scan extension locations

Search for `extension.yml` files in the following locations, in order:

```bash
# Project-local extensions (takes precedence)
ls .specify/extensions/*/extension.yml 2>/dev/null

# User-global extensions
ls ~/.specify/extensions/*/extension.yml 2>/dev/null
```

If neither location exists or contains any files, proceed directly to Step 4 with an empty extensions list.

> **OI-001:** These paths are the starting hypothesis. If neither yields results and the user has spec-kit installed, check `which speckit` or `speckit --list-extensions` for the actual install path and note it in the capability manifest under `scan_notes`.

### Step 2: For each found extension.yml

Read the file and extract:
- `extension.id` — the extension identifier string (e.g., `"reverse-eng"`)
- `extension.version`
- `provides.commands[*].name` — the list of slash-command names the extension provides
- `requires.speckit_version` — minimum spec-kit version

### Step 3: Determine relevance

For each extension, decide whether it is relevant to this run:

| Extension | Relevant when |
|-----------|---------------|
| `reverse-eng` | `mode == brownfield` — a codebase is being analyzed |
| Any other | Default to `relevant: false` unless you have a clear signal |

Set `relevant: true/false` and a one-sentence `reason` for each.

### Step 4: Write capability manifest

Write `.specify/squad/extension-capabilities.json`:

**If extensions were found:**
```json
{
  "generated_at": "<ISO 8601 timestamp>",
  "extensions": [
    {
      "id": "reverse-eng",
      "version": "1.1.0",
      "commands": ["speckit.reverse-eng.analyze", "speckit.reverse-eng.extract"],
      "invocation": "skill",
      "relevant": true,
      "reason": "brownfield codebase detected at target path"
    }
  ]
}
```

**If no extensions found (valid, expected):**
```json
{
  "generated_at": "<ISO 8601 timestamp>",
  "extensions": []
}
```

Always write a valid JSON file. An empty `extensions` array is correct — never omit the file or leave it malformed.

---

## Failure Handling

If you crash, cannot read files, or encounter any error:

1. Write a minimal valid manifest: `{ "generated_at": "<timestamp>", "extensions": [] }`
2. Include an `error` field describing what failed: `"error": "could not read .specify/extensions — permission denied"`

A PROSPECTOR failure must never block the run. COMMANDER will treat a missing or empty manifest identically and proceed to SCOUT directly.

---

## Completion Signal

```
SURVEY COMPLETE
Extensions found: <count>
Relevant: <list of relevant extension IDs, or "none">
Manifest written to: .specify/squad/extension-capabilities.json
```
```

- [ ] **Step 2.2: Verify the file exists and is well-formed**

```bash
ls -la agents/control/prospector.md
wc -l agents/control/prospector.md
```

Expected: file exists, >60 lines.

- [ ] **Step 2.3: Review checklist**

Verify the file contains all of these:
- [ ] Role description that positions PROSPECTOR in Control layer
- [ ] NEVER rules (no domain analysis, never block the run)
- [ ] Available tools list
- [ ] Step 1: Scan two specific paths (project-local + user-global)
- [ ] Step 2: Fields to extract from each extension.yml
- [ ] Step 3: Relevance table (reverse-eng → brownfield)
- [ ] Step 4: Both JSON output formats (found + empty)
- [ ] Failure handling that always produces a valid JSON file
- [ ] Completion signal

- [ ] **Step 2.4: Commit**

```bash
git add agents/control/prospector.md
git commit -m "feat(prospector): add SURVEY agent for spec-kit extension discovery"
```

---

## Task 3: Create GOLDDIGGER agent

GOLDDIGGER is a new Exploration-layer agent. It drives `spec-kit-reverse-eng` Phase 1 with two named config profiles and normalizes all output into `brownfield-index.md`.

**Files:**
- Create: `agents/exploration/golddigger.md`

- [ ] **Step 3.1: Create the agent file**

Create `agents/exploration/golddigger.md` with the following content:

```markdown
# GOLDDIGGER Agent

## Role

You are the GOLDDIGGER agent — a brownfield extraction driver. You are dispatched before SCOUT when a brownfield codebase is detected and the `spec-kit-reverse-eng` extension is available. Your job is to drive the reverse-eng Phase 1 pipeline with the right configuration and normalize all output into a stable format that SCOUT and downstream agents can consume.

**SCOUT never knows or cares whether its brownfield context came from you, a future tool, or manual analysis.** `brownfield-index.md` is the stable contract between you and all consumers.

You are dispatched as a subagent by COMMANDER. You will receive: the target codebase path and the mode to run (Mode 1 or Mode 2 with a specific domain).

## NEVER Rules

1. **NEVER pass raw reverse-eng domain specs to downstream agents** — always normalize into `brownfield-index.md`.
2. **NEVER run Mode 2 for a domain that is already in `golddigger_completed_domains`** — check `state.json` first.
3. **NEVER omit `golddigger_status` from `state.json`** — write it on every run, including failures.

## Available Tools

- **Skill** — invoke spec-kit extension commands (reverse-eng)
- **Read** — read generated artifacts
- **Bash** — write config files, read state.json, manage cache
- **Glob** — find generated spec files after extraction

---

## Configuration Profiles

Do NOT let agents or users pass arbitrary reverse-eng config. Use exactly these two named profiles:

### Mode 1 — Survey

```yaml
# golddigger-mode1.yml (write to .specify/squad/ before invoking)
analysis:
  level: signatures
workflow:
  coverage_threshold: 60
  resolution_threshold: 60
  max_validate_iterations: 1
output:
  generate_spec: false
  generate_plan: false
  generate_tasks: false
```

### Mode 2 — Deep Dive

```yaml
# golddigger-mode2.yml (write to .specify/squad/ before invoking)
analysis:
  level: full
workflow:
  coverage_threshold: 95
  resolution_threshold: 95
  max_validate_iterations: 3
output:
  generate_spec: true
  generate_plan: false
  generate_tasks: false
```

---

## Mode 1 — Survey Run

### Step 1: Write Mode 1 config

```bash
cat > .specify/squad/golddigger-mode1.yml << 'EOF'
analysis:
  level: signatures
workflow:
  coverage_threshold: 60
  resolution_threshold: 60
  max_validate_iterations: 1
output:
  generate_spec: false
  generate_plan: false
  generate_tasks: false
EOF
```

### Step 2: Invoke reverse-eng Phase 1 extraction

Use the Skill tool to invoke the reverse-eng extract command with the Mode 1 config:

```
/speckit.reverse-eng.extract
```

When the command prompt loads, provide:
- Target path: the codebase path from COMMANDER's context pack
- Config file: `.specify/squad/golddigger-mode1.yml`

> **OI-003 note:** If you encounter an error in the verify step related to `file_inventory.files`, this is a known latent bug in `verify.md`. It reads a field (`file_inventory.files`) that `extract-structure.sh` does not produce. Mode 1 may hit this. If it occurs, note it in `state.json` under `golddigger_notes` and proceed with whatever `analysis.json` was produced before the failure. Flag to spec-kit-reverse-eng maintainer.

### Step 3: Normalize output into brownfield-index.md

Read the outputs produced by reverse-eng (primarily `analysis.json` from `.specify/reverse-eng/`). Synthesize the following into `.specify/squad/brownfield-index.md`:

```markdown
# Brownfield Index

**Generated:** <ISO 8601 timestamp>
**Source:** spec-kit-reverse-eng v<version> (Mode 1 — signatures)
**Status:** complete | partial

---

## Domain Inventory

| Domain | Files | Entry Points |
|--------|-------|--------------|
| <domain-name> | <count> | <comma-separated entry point files> |

## Tech Stack

- **Languages:** <language (percentage)>, ...
- **Key frameworks:** <name version>, ...
- **Top dependencies:** <name>, ...

## Entry Points

- `<path>` — <brief description>

## Hotspots (Top 10 by churn)

| File | Changes (1yr) | Signal |
|------|---------------|--------|
| `<path>` | <count> | <what this suggests> |

## External Integrations

- <System name> (<type: API | DB | queue | infra>)
```

Save raw survey artifacts to `.specify/squad/golddigger-cache/survey.md` for reference.

### Step 4: Write status to state.json

Update only the GOLDDIGGER-owned fields in `state.json` (do NOT modify `golddigger_requests` or `golddigger_completed_domains` — those are COMMANDER's responsibility):

```json
{
  "golddigger_status": "complete",
  "golddigger_mode": "survey",
  "golddigger_notes": []
}
```

If the pipeline exited early or any step failed, write `"golddigger_status": "partial"` or `"golddigger_status": "failed"` with a note explaining what happened.

---

## Mode 2 — Deep Dive (single domain)

You will receive the domain name from COMMANDER's context pack.

> **Note on deduplication:** COMMANDER checks `golddigger_completed_domains` before dispatching you (defense in depth). You also check it as a NEVER rule. Both checks are intentional — COMMANDER's prevents redundant dispatch, yours guards against edge cases where COMMANDER re-dispatches in error.

### Step 1: Check cache

```bash
# Check if already completed (defensive check)
cat .specify/squad/state.json | python3 -c "import json,sys; s=json.load(sys.stdin); print(s.get('golddigger_completed_domains', []))"
```

If the domain is already in `golddigger_completed_domains`, output the cache path and stop:
```
GOLDDIGGER MODE 2 — CACHE HIT
Domain: <domain>
Cached at: .specify/squad/golddigger-cache/<domain>.md
```

### Step 2: Write Mode 2 config

```bash
cat > .specify/squad/golddigger-mode2.yml << 'EOF'
analysis:
  level: full
workflow:
  coverage_threshold: 95
  resolution_threshold: 95
  max_validate_iterations: 3
output:
  generate_spec: true
  generate_plan: false
  generate_tasks: false
EOF
```

### Step 3: Invoke reverse-eng for this domain

```
/speckit.reverse-eng.extract
```

Scope the extraction to the specific domain directory identified in the survey. When the command prompt loads, provide the domain path and Mode 2 config.

### Step 4: Copy normalized output to cache

Copy the generated domain spec to `.specify/squad/golddigger-cache/<domain>.md`.

### Step 5: Write completion status to state.json

Write only your status fields — COMMANDER handles the queue and completed-domains list:

```bash
python3 -c "
import json
with open('.specify/squad/state.json', 'r') as f:
    s = json.load(f)

s['golddigger_status'] = 'complete'
s['golddigger_mode'] = 'deep-dive'

with open('.specify/squad/state.json', 'w') as f:
    json.dump(s, f, indent=2)
"
```

---

## Failure Handling

If any step fails:

1. Write `"golddigger_status": "failed"` (or `"partial"` if analysis.json was produced) to `state.json`
2. Include `"golddigger_notes": ["<what failed and why>"]`
3. Exit cleanly — do not throw

SCOUT will detect the absent or partial `brownfield-index.md` and fall back to manual structural analysis. The run continues in degraded-brownfield mode.

---

## Completion Signal

**Mode 1:**
```
GOLDDIGGER SURVEY COMPLETE
Status: <complete|partial|failed>
Brownfield index: .specify/squad/brownfield-index.md
Domains found: <count>
```

**Mode 2:**
```
GOLDDIGGER DEEP DIVE COMPLETE
Domain: <domain>
Status: <complete|partial|failed>
Cached at: .specify/squad/golddigger-cache/<domain>.md
```
```

- [ ] **Step 3.2: Review checklist**

Verify the file contains:
- [ ] Role description + NEVER rules (no raw specs to consumers, no duplicate Mode 2, always write status)
- [ ] Available tools including Skill
- [ ] Both config profiles (Mode 1: signatures/60%, Mode 2: full/95%)
- [ ] Mode 1: config write → invoke → normalize to brownfield-index.md → write status
- [ ] brownfield-index.md format with all 5 sections (domains, tech, entry points, hotspots, integrations)
- [ ] Mode 2: cache check (defensive) → config write → invoke → cache output → write golddigger_status only
- [ ] Mode 2 does NOT mutate golddigger_requests or golddigger_completed_domains (COMMANDER owns those)
- [ ] Failure handling that always writes golddigger_status
- [ ] Completion signals for both modes
- [ ] OI-003 note about verify.md latent bug

- [ ] **Step 3.3: Commit**

```bash
git add agents/exploration/golddigger.md
git commit -m "feat(golddigger): add reverse-eng driver + normalizer agent"
```

---

## Task 4: Update SCOUT — remove binary check, add brownfield-index.md consumption

**Files:**
- Modify: `agents/exploration/scout.md` — brownfield Step 1 block

- [ ] **Step 4.1: Read the current brownfield Step 1 block**

Open `agents/exploration/scout.md` and find the block that reads:

```markdown
### Step 1: Check for spec-kit-reverse-eng

```bash
which reverse-eng || npx reverse-eng --version 2>/dev/null
```

**If available:** Run the full extraction pipeline:

```bash
reverse-eng extract <target_path> --output analysis.json
```

Parse `analysis.json` for: entities, relationships, APIs, data models, dependencies, and architectural patterns.

**If unavailable:** Fall back to manual analysis (Steps 2-4 cover this). Log in your reasoning journal that Reverse-Eng was unavailable and analysis is manual.
```

- [ ] **Step 4.2: Replace the entire Step 1 block**

Replace it with:

```markdown
### Step 1: Check for GOLDDIGGER brownfield context

```bash
ls .specify/squad/brownfield-index.md 2>/dev/null
```

**If present:** Read `.specify/squad/brownfield-index.md` as your enriched starting point. Use it to:
- Seed `glossary.md` with domain names and terminology from the Domain Inventory
- Seed `mental-model.md` topology from the dependency relationships between domains
- Seed `boundaries.md` with entry points and External Integrations
- Seed `unknowns.md` with hotspot files (high churn signals hidden complexity)
- Seed `assumptions.md` from the Tech Stack (version constraints, framework conventions)

Treat the index as a validated head-start, not as a complete answer. Enrich, validate, and extend every section — do not copy blindly.

**If absent:** Proceed with manual analysis (Steps 2-4 cover this). Log in your reasoning journal: "GOLDDIGGER brownfield-index.md not present — proceeding with manual structural analysis."

Note: how the brownfield context was generated (from reverse-eng, a future tool, or manual analysis) is invisible to you and to all downstream agents. Your job is to produce the standard output artifacts regardless of source.
```

- [ ] **Step 4.3: Verify the change**

```bash
grep -n "which reverse-eng" agents/exploration/scout.md
```

Expected: no output (the line no longer exists).

```bash
grep -n "brownfield-index.md" agents/exploration/scout.md
```

Expected: at least 2 hits (the ls check and the read instruction).

- [ ] **Step 4.4: Review checklist**

- [ ] `which reverse-eng` binary check is gone
- [ ] `npx reverse-eng --version` is gone
- [ ] `reverse-eng extract` command is gone
- [ ] Check for `.specify/squad/brownfield-index.md` is present
- [ ] If present: seeding instructions for all 5 artifacts (glossary, mental-model, boundaries, unknowns, assumptions)
- [ ] If absent: manual analysis fallback + reasoning journal log
- [ ] Note about source opacity (SCOUT doesn't know where the context came from)
- [ ] Steps 2-5 unchanged below

- [ ] **Step 4.5: Commit**

```bash
git add agents/exploration/scout.md
git commit -m "fix(scout): replace binary check with brownfield-index.md consumption"
```

---

## Task 5: Update COMMANDER — add PROSPECTOR init + GOLDDIGGER brownfield + Mode 2 queue

**Files:**
- Modify: `agents/control/commander.md`

- [ ] **Step 5.1: Add PROSPECTOR to init sequence**

In `commander.md`, insert the following block **immediately before the `## Build Phase Orchestration` heading** (which currently starts around line 160, immediately after the State Management section). This is the correct anchor — there is no existing "Run Initialization" section:

```markdown
## Run Initialization

Before any mode detection or agent dispatch, COMMANDER must:

### 1. Dispatch PROSPECTOR (always)

Dispatch the PROSPECTOR (SURVEY) agent with the current run context (target path, run_id). Block until PROSPECTOR completes.

After completion:
- Read `.specify/squad/extension-capabilities.json`
- If the file is absent, malformed, or empty: log `prospector_status: failed` in `state.json`; treat identically to empty-extensions (no GOLDDIGGER dispatch)
- If valid: extract the list of relevant extensions and **store a brief summary in the run context** — include this summary in every subsequent agent's context pack (e.g., "Extensions available: reverse-eng 1.1.0 [relevant]" or "No extensions available")

**PROSPECTOR failure never blocks the run.** Continue to mode detection regardless.
```

- [ ] **Step 5.2: Add GOLDDIGGER to brownfield dispatch**

Find the section where COMMANDER routes to SCOUT for brownfield runs. Before dispatching SCOUT, add:

```markdown
### Brownfield Extension Check

After brownfield mode is confirmed, before dispatching SCOUT:

1. Read `extension-capabilities.json` (already loaded at init)
2. If `reverse-eng` is listed with `relevant: true`:
   - Dispatch GOLDDIGGER in Mode 1 (Survey)
   - Block SCOUT dispatch until GOLDDIGGER completes
   - Read `golddigger_status` from `state.json`:
     - `complete`: proceed normally, SCOUT will find `brownfield-index.md`
     - `partial` or `failed`: log degraded-brownfield warning; proceed (SCOUT falls back to manual)
3. If `reverse-eng` is not listed, or `extensions` is empty: dispatch SCOUT directly (unchanged)
```

- [ ] **Step 5.3: Add Mode 2 queue handling**

Add a new section for Mode 2 queue checking, to run after each Phase 1 agent completes. Insert this immediately after the "Brownfield Extension Check" section added in Step 5.2:

```markdown
### GOLDDIGGER Mode 2 Queue (Phase 1 agents)

After each Phase 1 agent (SCOUT, SYNTHESIZER, SAGE, CARTOGRAPHER, MODELER) completes, before dispatching the next agent:

1. Read `state.json.golddigger_requests` — if empty or absent, continue
2. For each pending request entry:
   a. Check `state.json.golddigger_completed_domains` — if the domain is already listed, skip (cache hit; domain data is in `.specify/squad/golddigger-cache/<domain>.md`). **COMMANDER checks this before dispatch; GOLDDIGGER also checks defensively inside — both are intentional.**
   b. Otherwise: dispatch GOLDDIGGER in Mode 2 with the domain name
   c. After GOLDDIGGER completes (GOLDDIGGER writes only its status fields):
      - **COMMANDER** removes the domain entry from `golddigger_requests` in `state.json`
      - **COMMANDER** adds the domain to `golddigger_completed_domains` in `state.json`
      - **COMMANDER** includes the cached domain file path (`.specify/squad/golddigger-cache/<domain>.md`) in the requesting agent's next context pack
3. Continue to next Phase 1 agent dispatch
```

- [ ] **Step 5.4: Add state.json field documentation**

In the State Management section, add the new fields:

```markdown
### New state.json fields (PROSPECTOR + GOLDDIGGER)

- `prospector_status`: `"complete"` | `"failed"` — set by COMMANDER after PROSPECTOR runs
- `golddigger_status`: `"complete"` | `"partial"` | `"failed"` — set by GOLDDIGGER
- `golddigger_mode`: `"survey"` | `"deep-dive"` — which mode last ran
- `golddigger_notes`: array of strings — any warnings or known issues from GOLDDIGGER
- `golddigger_requests`: array of `{ domain, requester, reason }` — Mode 2 request queue
- `golddigger_completed_domains`: array of domain name strings — cache hit deduplication
```

- [ ] **Step 5.5: Verify changes**

```bash
grep -n "PROSPECTOR" agents/control/commander.md | head -10
grep -n "GOLDDIGGER" agents/control/commander.md | head -10
grep -n "golddigger_requests" agents/control/commander.md
grep -n "golddigger_completed_domains" agents/control/commander.md
```

Expected: results for all four searches.

- [ ] **Step 5.6: Review checklist**

- [ ] PROSPECTOR dispatch is first, before mode detection, inserted before `## Build Phase Orchestration`
- [ ] PROSPECTOR failure is handled (treat as empty-extensions, never block)
- [ ] Extension capabilities summary included in every subsequent agent's context pack
- [ ] GOLDDIGGER dispatch is conditional on `reverse-eng` being relevant in capabilities
- [ ] SCOUT dispatch is blocked on GOLDDIGGER completion
- [ ] All three golddigger_status values are handled (complete/partial/failed)
- [ ] Mode 2 queue check happens after EACH Phase 1 agent (not just SCOUT)
- [ ] COMMANDER (not GOLDDIGGER) removes entries from `golddigger_requests` and adds to `golddigger_completed_domains`
- [ ] COMMANDER (not GOLDDIGGER) notifies requesting agent via next context pack
- [ ] Cache deduplication check uses `golddigger_completed_domains` (both COMMANDER and GOLDDIGGER check, intentionally)
- [ ] All new state.json fields are documented

- [ ] **Step 5.7: Commit**

```bash
git add agents/control/commander.md
git commit -m "feat(commander): add PROSPECTOR init dispatch and GOLDDIGGER brownfield orchestration"
```

---

## Task 6: Register PROSPECTOR and GOLDDIGGER in agents.yaml

**Files:**
- Modify: `agents.yaml`

- [ ] **Step 6.1: Add PROSPECTOR to the control layer section**

Find the control layer section (starts with `# LAYER: CONTROL`). After COMMANDER's entry, add PROSPECTOR before SCOREKEEPER. Follow the existing agent entry format exactly:

```yaml
  PROSPECTOR:
    codename: PROSPECTOR
    function: SURVEY
    file: agents/control/prospector.md
    layer: control
    phase: all
    role: "Extension discovery — scans for installed spec-kit extensions, writes capability manifest"
    when: "Always — first agent dispatched on every run, before mode detection"
    inputs: [".specify/extensions/*/extension.yml", "~/.specify/extensions/*/extension.yml", "run context (target_path, mode)"]
    outputs: [".specify/squad/extension-capabilities.json"]
    never:
      - "NEVER do domain analysis"
      - "NEVER block the run on failure"
```

- [ ] **Step 6.2: Add GOLDDIGGER to the exploration layer section**

Find the exploration layer section (starts with `# LAYER: EXPLORATION`). Insert GOLDDIGGER after the MODELER block and **before** the `# LAYER: FEASIBILITY` comment header. Use a flat `outputs` list matching the format of all other agent entries (no nested mode1/mode2 keys):

```yaml
  GOLDDIGGER:
    codename: GOLDDIGGER
    function: EXTRACT
    file: agents/exploration/golddigger.md
    layer: exploration
    phase: understand
    role: "Brownfield extraction driver — drives spec-kit-reverse-eng Phase 1 and normalizes output into brownfield-index.md"
    when: "Brownfield runs only, when reverse-eng is listed as relevant in extension-capabilities.json. Dispatched before SCOUT."
    inputs: ["target codebase path", ".specify/squad/extension-capabilities.json", ".specify/squad/state.json"]
    outputs: [".specify/squad/brownfield-index.md", ".specify/squad/golddigger-cache/survey.md", ".specify/squad/golddigger-cache/{domain}.md"]
    never:
      - "NEVER pass raw reverse-eng domain specs to downstream agents"
      - "NEVER run Mode 2 for a domain already in golddigger_completed_domains"
      - "NEVER omit golddigger_status from state.json"
```

- [ ] **Step 6.3: Add layer totals comment**

There is no existing layer-totals comment in `agents.yaml`. Add the following block immediately after the `agents:` key, before the first agent entry (COMMANDER):

```yaml
# ─────────────────────────────────────────────
# Layer totals: Control: 6, Exploration: 6, Feasibility: 2, Solution: 3,
#               Specialists: 6, Build: 8, Learning: 6 — Total: 37 agents
# ─────────────────────────────────────────────
```

- [ ] **Step 6.4: Verify**

```bash
grep -c "codename:" agents.yaml
```

Expected: 37 (was 35 + PROSPECTOR + GOLDDIGGER).

```bash
grep -A2 "PROSPECTOR:" agents.yaml
grep -A2 "GOLDDIGGER:" agents.yaml
```

Expected: entries found with correct layer assignments.

- [ ] **Step 6.5: Commit**

```bash
git add agents.yaml
git commit -m "feat(agents.yaml): register PROSPECTOR (control) and GOLDDIGGER (exploration)"
```

---

## Task 7: Fix extension.yml — remove binary claim

**Files:**
- Modify: `extension.yml`

- [ ] **Step 7.1: Read the current description field**

The current `extension.description` says: `"...brownfield support..."` — this is fine. But the `tools` entry for `spec-kit-reverse-eng` implies binary invocation.

- [ ] **Step 7.2: Update the description and add integration note**

In `extension.yml`, update the `requires.tools` entry for `spec-kit-reverse-eng` to add a comment:

```yaml
requires:
  speckit_version: ">=0.3.0"
  tools:
    - name: "understanding"
      version: ">=3.4.0"
      required: false
    - name: "spec-kit-reverse-eng"
      version: ">=1.0.0"
      required: false
      # Integration: invoked via GOLDDIGGER agent (Skill tool), not as a CLI binary.
      # PROSPECTOR discovers availability; GOLDDIGGER drives Phase 1 extraction.
```

Also update `extension.description` to reflect v0.5.0 will ship this integration:

```yaml
  description: "Multi-agent cognitive system: 7-layer, 37-agent architecture with adversarial critic (SAGE), kill gate (GATEKEEPER), role-separation enforcement, cross-run calibration learning, brownfield support via PROSPECTOR+GOLDDIGGER, and RADAR real-time monitoring"
```

- [ ] **Step 7.3: Verify YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('extension.yml'))" && echo "YAML OK"
```

Expected: `YAML OK`

- [ ] **Step 7.4: Commit**

```bash
git add extension.yml
git commit -m "fix(extension.yml): document Skill-based reverse-eng invocation, not binary"
```

---

## Task 8: Fix echelon.run.md — Section 15 error table + line ~619 advisory text

**Files:**
- Modify: `commands/echelon.run.md`

- [ ] **Step 8.1: Fix the Section 15 error table row**

Find this exact row in the External Tool Failures table (around line 1509):

```
| spec-kit-reverse-eng | Not installed or fails on codebase | DISCOVER falls back to greenfield mode: ask user to describe the codebase instead. Flag as degraded. |
```

Replace with:

```
| spec-kit-reverse-eng | PROSPECTOR fails or reverse-eng not installed | COMMANDER treats as empty-extensions; SCOUT proceeds without brownfield-index.md using manual structural analysis. Run flagged as degraded-brownfield in state.json. |
```

- [ ] **Step 8.2: Fix the brownfield constitution advisory text**

Find this exact text (around line 619):

```
1. **Option A:** If `spec-kit-reverse-eng` is available, suggest running it first to derive principles from existing code patterns
```

Replace with:

```
1. **Option A:** If GOLDDIGGER ran and `brownfield-index.md` is present, derive principles from the domain inventory and hotspot analysis already captured there.
```

- [ ] **Step 8.3: Verify both changes**

```bash
grep -n "spec-kit-reverse-eng.*suggest running" commands/echelon.run.md
```

Expected: no output (old text gone).

```bash
grep -n "brownfield-index.md is present" commands/echelon.run.md
```

Expected: 1 hit (new text at line ~619).

```bash
grep -n "DISCOVER falls back to greenfield mode" commands/echelon.run.md
```

Expected: no output (old error table row gone).

```bash
grep -n "COMMANDER treats as empty-extensions" commands/echelon.run.md
```

Expected: 1 hit.

- [ ] **Step 8.4: Commit**

```bash
git add commands/echelon.run.md
git commit -m "fix(squad.run): update error table and brownfield advisory text for PROSPECTOR+GOLDDIGGER"
```

---

## Task 9: End-to-end dispatch sequence trace

Manual verification that the full dispatch sequence is coherent across all modified files.

**Files:** (read-only verification, no changes)

- [ ] **Step 9.1: Trace the brownfield happy path**

Read through the following files in sequence and verify the chain is unbroken:

1. `commands/echelon.run.md` — user invokes the squad run command (note: `echelon.run.md` does NOT call PROSPECTOR directly; COMMANDER handles all agent dispatch, including PROSPECTOR)
2. `agents/control/commander.md` — PROSPECTOR dispatched first (before `## Build Phase Orchestration`); reads capabilities; dispatches GOLDDIGGER if reverse-eng relevant; GOLDDIGGER before SCOUT
3. `agents/control/prospector.md` — scans extension paths; writes valid JSON even on failure
4. `agents/exploration/golddigger.md` — Mode 1: writes config → invokes reverse-eng → normalizes to brownfield-index.md → writes golddigger_status
5. `agents/exploration/scout.md` — checks for brownfield-index.md; seeds artifacts from it; falls back to manual if absent
6. `agents/control/commander.md` Mode 2 queue — after each Phase 1 agent; deduplicates via golddigger_completed_domains

- [ ] **Step 9.2: Trace the greenfield / no-extension path**

1. PROSPECTOR runs → writes `{ "extensions": [] }`
2. COMMANDER reads empty extensions → no GOLDDIGGER dispatch
3. SCOUT runs → no brownfield-index.md → manual analysis (unchanged path)
4. All downstream unchanged

- [ ] **Step 9.3: Trace the failure paths**

1. PROSPECTOR fails → COMMANDER writes `prospector_status: failed` → proceeds to SCOUT as if no extensions → run degrades cleanly
2. GOLDDIGGER Mode 1 fails → writes `golddigger_status: failed` → brownfield-index.md absent or partial → SCOUT falls back to manual
3. Mode 2 domain already completed → cache hit → no re-dispatch

- [ ] **Step 9.4: Verify agent count in agents.yaml**

```bash
grep -c "codename:" agents.yaml
```

Expected: 37

```bash
grep "layer: control" agents.yaml | wc -l
grep "layer: exploration" agents.yaml | wc -l
```

Expected: 6 control, 6 exploration

- [ ] **Step 9.5: Commit trace notes**

No file changes — this step is verification only. If any gaps were found and fixed, commit those fixes with:

```bash
git commit -m "fix: address gaps found in end-to-end dispatch trace"
```

---

## Task 10: Final commit — version bump and summary

- [ ] **Step 10.1: Update extension version to 0.5.0**

In `extension.yml`, change:

```yaml
  version: "0.4.0"
```

to:

```yaml
  version: "0.5.0"
```

- [ ] **Step 10.2: Commit**

```bash
git add extension.yml
git commit -m "chore: bump version to 0.5.0 — brownfield extension integration (PROSPECTOR + GOLDDIGGER)"
```

---

## Summary: Files Changed

| File | Task | Change type |
|------|------|-------------|
| `commands/echelon.run.md` | 1, 8 | python3 fix + error table + advisory text |
| `commands/echelon.build.md` | 1 | python3 fix |
| `agents/control/prospector.md` | 2 | New file |
| `agents/exploration/golddigger.md` | 3 | New file |
| `agents/exploration/scout.md` | 4 | Binary check → brownfield-index.md |
| `agents/control/commander.md` | 5 | PROSPECTOR init + GOLDDIGGER dispatch + Mode 2 queue |
| `agents.yaml` | 6 | Register 2 new agents; update totals |
| `extension.yml` | 7, 10 | Fix binary claim; version bump to 0.5.0 |
