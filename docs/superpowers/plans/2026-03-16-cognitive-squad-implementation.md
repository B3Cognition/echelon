# Cognitive Agent Squad — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Spec-Kit extension that implements 19 cognitive functions (7 core agents + 7 specialists + 4 learning + 1 feedback) for autonomous pre-code analysis.

**Architecture:** Each cognitive function is a markdown prompt file. The MANAGER command (`squad.run.md`) is the entry point that dispatches agent prompts as Claude Code subagents via the Agent tool. State is tracked in `state.json`, reasoning in `reasoning-journal.json`, artifacts in `.specify/specs/{feature}/`.

**Tech Stack:** Spec-Kit extension (YAML manifest + markdown commands), Claude Code Agent tool for subagent dispatch, Understanding CLI for quality gates, Reverse-Eng CLI for brownfield extraction, bash helper scripts.

**Design Doc:** `docs/design.md` (the authoritative spec for all agent roles, state machine, and outputs)

---

## Chunk 1: Extension Foundation

### Task 1: Create directory structure

**Files:**
- Create: `extension.yml`
- Create: `LICENSE`
- Create: `.gitignore`
- Create: `.extensionignore`
- Create: `config-template.yml`

- [ ] **Step 1: Create extension manifest**

```yaml
# extension.yml
schema_version: "1.0"

extension:
  id: "cognitive-squad"
  name: "Cognitive Squad"
  version: "0.1.0"
  description: "19-function cognitive agent squad for autonomous pre-code analysis"
  author: "Testimonial"
  repository: "https://github.com/Testimonial/cognitive-squad"
  license: "MIT"

requires:
  speckit_version: ">=0.3.0"
  tools:
    - name: "understanding"
      version: ">=3.4.0"
      required: false
    - name: "spec-kit-reverse-eng"
      version: ">=1.0.0"
      required: false

provides:
  commands:
    - name: "speckit.squad.run"
      file: "commands/squad.run.md"
      description: "Full autonomous cognitive squad run"
    - name: "speckit.squad.status"
      file: "commands/squad.status.md"
      description: "Check current squad state and progress"
    - name: "speckit.squad.innovate"
      file: "commands/squad.innovate.md"
      description: "Manually trigger INNOVATE specialist"
    - name: "speckit.squad.investigate"
      file: "commands/squad.investigate.md"
      description: "Manually trigger SCIENTIST for a specific question"
    - name: "speckit.squad.ground"
      file: "commands/squad.ground.md"
      description: "Manually trigger reality check on artifacts"
    - name: "speckit.squad.feedback"
      file: "commands/squad.feedback.md"
      description: "Post-implementation feedback intake"
    - name: "speckit.squad.resume"
      file: "commands/squad.resume.md"
      description: "Provide answer to human escalation"

  config:
    - name: "squad-config.yml"
      template: "config-template.yml"
      description: "Squad configuration"
      required: false

hooks:
  after_tasks:
    command: "speckit.squad.run"
    optional: true
    prompt: "Run cognitive squad analysis on generated tasks?"
    description: "Automatically analyze tasks with the cognitive squad"

tags:
  - "ai-agents"
  - "cognitive"
  - "pre-code"
  - "analysis"
```

- [ ] **Step 2: Create config template**

```yaml
# config-template.yml
# Cognitive Squad Configuration
# Copy to squad-config.yml and customize

# Analysis settings
analysis:
  # Auto-detect greenfield vs brownfield
  mode: auto  # auto | greenfield | brownfield

  # Maximum squad iterations before forced convergence
  max_iterations: 5

  # Token budget (approximate, in thousands)
  token_budget_k: 1000

  # Convergence threshold for Understanding score delta
  convergence_delta: 0.02

# Specialist settings
specialists:
  # Max active specialists per run (to control token cost)
  max_active: 3

  # Always summon TEST ARCHITECT
  always_test_architect: true

  # Auto-summon SCIENTIST for unknowns
  auto_scientist: true

# Quality gates (Understanding thresholds)
quality_gates:
  overall: 0.70
  structure: 0.70
  testability: 0.70
  semantic: 0.60
  cognitive: 0.60
  readability: 0.50

# Knowledge base settings
knowledge_base:
  # Pruning: entries older than this (months) flagged stale
  stale_threshold_months: 6

  # Pruning: accuracy below this flagged low_confidence
  low_confidence_threshold: 0.4

  # Max active entries per file
  max_entries: 200

# Tool paths (override if not on PATH)
tools:
  understanding_cli: "understanding"
  reverse_eng_cli: "specify"

# Environment variable overrides:
# SPECKIT_SQUAD_ANALYSIS_MODE
# SPECKIT_SQUAD_ANALYSIS_MAX_ITERATIONS
# SPECKIT_SQUAD_ANALYSIS_TOKEN_BUDGET_K
# SPECKIT_SQUAD_SPECIALISTS_MAX_ACTIVE
```

- [ ] **Step 3: Create LICENSE, .gitignore, .extensionignore**

`LICENSE`: MIT License, Copyright (c) 2026 Testimonial

`.gitignore`:
```
*-config.local.yml
__pycache__/
*.py[cod]
.DS_Store
.superpowers/
```

`.extensionignore`:
```
tests/
.github/
docs/superpowers/
.superpowers/
```

- [ ] **Step 4: Create all directories**

```bash
mkdir -p commands
mkdir -p agents/core
mkdir -p agents/specialists
mkdir -p agents/learning
mkdir -p templates
mkdir -p scripts/bash
mkdir -p knowledge-base/archive
mkdir -p knowledge-base/domain-glossaries
mkdir -p knowledge-base/feedback
```

- [ ] **Step 5: Commit foundation**

```bash
git add -A
git commit -m "feat: extension foundation — manifest, config, directory structure"
```

---

### Task 2: Create knowledge base seed files

**Files:**
- Create: `knowledge-base/patterns.yaml`
- Create: `knowledge-base/estimates-log.yaml`
- Create: `knowledge-base/pitfalls.yaml`
- Create: `knowledge-base/calibration-profile.yaml`

- [ ] **Step 1: Create all seed files**

```yaml
# knowledge-base/patterns.yaml
schema_version: 1
entries: []
```

```yaml
# knowledge-base/estimates-log.yaml
schema_version: 1
entries: []
```

```yaml
# knowledge-base/pitfalls.yaml
schema_version: 1
entries: []
```

```yaml
# knowledge-base/calibration-profile.yaml
schema_version: 1
domains: {}
```

- [ ] **Step 2: Commit**

```bash
git add knowledge-base/
git commit -m "feat: knowledge base seed files (empty YAML)"
```

---

### Task 3: Create templates

**Files:**
- Create: `templates/state-schema.json`
- Create: `templates/evidence-grades.md`
- Create: `templates/context-pack.md`
- Create: `templates/kill-report.md`
- Create: `templates/feedback-questionnaire.md`
- Create: `templates/escalation-request.md`

- [ ] **Step 1: Create state schema**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Squad State",
  "type": "object",
  "required": ["run_id", "status", "phase", "iteration", "created_at"],
  "properties": {
    "run_id": { "type": "string", "pattern": "^squad-[0-9]{3}-[0-9]+$" },
    "status": { "enum": ["running", "blocked", "done", "error", "killed"] },
    "phase": { "enum": [
      "init", "discover", "why1", "what", "why2", "assess",
      "specialists", "how", "test-architect", "plan",
      "consensus", "finalize", "done"
    ]},
    "mode": { "enum": ["greenfield", "brownfield"] },
    "iteration": { "type": "integer", "minimum": 0, "maximum": 5 },
    "spec_id": { "type": "string" },
    "created_at": { "type": "string", "format": "date-time" },
    "updated_at": { "type": "string", "format": "date-time" },
    "token_usage": { "type": "integer", "minimum": 0 },
    "quality_scores": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "pass": { "type": "integer" },
          "overall": { "type": "number" },
          "structure": { "type": "number" },
          "testability": { "type": "number" }
        }
      }
    },
    "active_specialists": { "type": "array", "items": { "type": "string" } },
    "issues_log": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": { "type": "string" },
          "severity": { "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"] },
          "source": { "type": "string" },
          "description": { "type": "string" },
          "resolved": { "type": "boolean" },
          "occurrences": { "type": "integer" }
        }
      }
    },
    "blocked_reason": { "type": "string" },
    "escalation_question": { "type": "string" }
  }
}
```

- [ ] **Step 2: Create evidence grades template**

```markdown
# Evidence Quality Grades

Used by SCIENTIST to grade all research sources.

| Grade | Description | Examples | Weight |
|-------|-------------|----------|--------|
| **A** | Peer-reviewed research, ISO/IEEE standard | IEEE 830, published papers with peer review | 1.0 |
| **B** | Official documentation, proven benchmark | Framework docs, reproducible benchmarks | 0.8 |
| **C** | Well-regarded blog, conference talk, case study | ThoughtWorks Radar, StrangeLoop talks | 0.6 |
| **D** | Stack Overflow, forum post, anecdotal | Accepted SO answers, Reddit threads | 0.3 |
| **E** | AI training data (unverified, possibly stale) | LLM-generated without citation | 0.1 |

## Grading Rules

1. Every recommendation from SCIENTIST must cite at least one source with its grade
2. Recommendations based solely on grade E evidence must be flagged as LOW_CONFIDENCE
3. Conflicting evidence: higher grade wins. Same grade: more recent wins.
4. SCIENTIST must attempt to find grade A-B evidence before falling back to C-E
5. Grade upgrades: if SCIENTIST experiment validates a grade C-E finding, it becomes grade B
```

- [ ] **Step 3: Create context pack template**

```markdown
# Context Pack Assembly Guide

## Purpose
MANAGER uses this template to compile context packs per agent.
Each agent receives ONLY what it needs — not everything.

## Per-Agent Context Packs

### DISCOVER
- User input (description or repo path)
- knowledge-base/calibration-profile.yaml
- Previous run's evolution-report.md (if re-run)

### WHAT
- glossary.md + mental-model.md + boundaries.md
- assumptions.md + unknowns.md
- reference-architectures.md (if greenfield)
- reasoning-journal.json (filtered: DISCOVER + WHY1 entries)

### WHY (assumption-challenge mode)
- glossary.md + mental-model.md + boundaries.md
- assumptions.md + unknowns.md
- calibration-profile.yaml
- reasoning-journal.json

### WHY (spec-validation mode)
- All current artifacts
- Understanding CLI access
- calibration-profile.yaml
- reasoning-journal.json

### ASSESS
- spec.md + glossary.md + assumptions.md
- issues.md (from WHY2)
- calibration-profile.yaml + estimates-log.yaml
- reasoning-journal.json

### HOW
- spec.md + feasibility.md + prioritization.md
- constitution.md (if exists)
- All specialist outputs
- reasoning-journal.json

### TEST ARCHITECT
- plan.md + data-model.md
- spec.md (acceptance criteria)
- contracts/
- reasoning-journal.json

### PLAN
- plan.md + research.md + data-model.md
- contracts/ + test-strategy.md
- risk data from specialists
- reasoning-journal.json

### ASSESS2 (consensus)
- plan.md + data-model.md + contracts/
- tasks.md + original estimates.md
- constitution (team constraints)
- reasoning-journal.json

### PLAN2 (consensus)
- Updated plan.md + test-strategy.md
- Specialist outputs + implementability-report.md
- reasoning-journal.json

### SCIENTIST
- Specific question from requesting agent
- Relevant artifacts (MANAGER selects)
- Web search access + git worktree access
- reasoning-journal.json

### SPECIALISTS (all others)
- Domain-relevant artifacts only
- reasoning-journal.json

### LEARNING LAYER
- All artifacts
- Prior run data (if re-run)
- Feedback history from knowledge-base/feedback/
```

- [ ] **Step 4: Create kill report template**

```markdown
# Kill Report: {FEATURE_NAME}

**Date:** {DATE}
**Decision:** KILL / DEFER
**Decided by:** ASSESS (squad run {RUN_ID})

## Reason

{One paragraph explaining why this idea was killed or deferred}

## Evidence

| Factor | Score | Threshold | Verdict |
|--------|-------|-----------|---------|
| Feasibility | {score} | Pass/Fail | {verdict} |
| RICE Priority | {score} | {cutoff} | {verdict} |
| Kano Classification | {class} | — | {verdict} |
| Effort Estimate | {days} | {budget} | {verdict} |

## What Was Considered

{Brief summary of the idea/requirements as understood}

## Recommendation

- [ ] Revisit in {timeframe} with {conditions}
- [ ] Permanently shelve
- [ ] Reduce scope to: {reduced scope description}

## Artifacts Produced Before Kill

{List of any partial artifacts that may be useful later}
```

- [ ] **Step 5: Create feedback questionnaire template**

```markdown
# Post-Implementation Feedback: {SPEC_ID} — {PROJECT_NAME}

**Original Squad Run:** {RUN_ID}
**Implementation Completed:** {DATE}
**Feedback Collected:** {DATE}

## Effort Accuracy

- Estimated effort: {N} days
- Actual effort: {N} days
- Accuracy ratio: {N}
- Notes: {what was over/underestimated}

## Architecture Decisions

For each major decision in research.md:

| Decision | Held? | Notes |
|----------|-------|-------|
| {decision 1} | Yes/No/Partially | {what happened} |

## Requirements Quality

- Requirements that were correct as-written: {count}
- Requirements that needed clarification during implementation: {count}
- Requirements that were completely missing: {list}
- Requirements that turned out to be unnecessary: {list}

## Risk Accuracy

| Predicted Risk | Materialized? | Actual Impact |
|----------------|---------------|---------------|
| {risk 1} | Yes/No | {description} |

Risks that materialized but were NOT predicted: {list}

## Test Strategy

- Test gaps found during implementation: {list}
- Test gaps found in production: {list}
- Coverage areas that were over-tested: {list}

## SCIENTIST Recommendations

| Recommendation | Correct? | Notes |
|----------------|----------|-------|
| {rec 1} | Yes/No/Partially | {what happened} |

## Overall Assessment

- What the squad got right: {list}
- What the squad got wrong: {list}
- What the squad completely missed: {list}
```

- [ ] **Step 6: Create escalation request template**

```markdown
# Escalation to Human: {TOPIC}

**Squad Run:** {RUN_ID}
**Phase:** {CURRENT_PHASE}
**Trigger:** {same issue 3x / CALIBRATE < 0.5 / unresolvable conflict}

## Question

{The specific question that needs human input}

## Context

{What was tried, what failed, why the squad cannot resolve this autonomously}

## Options Considered

| Option | Pros | Cons | Squad Recommendation |
|--------|------|------|---------------------|
| A: {option} | {pros} | {cons} | {recommended?} |
| B: {option} | {pros} | {cons} | |
| C: {option} | {pros} | {cons} | |

## Recommended Answer

{Squad's best guess, with confidence level}

## How to Respond

Run: `/speckit.squad.resume {your answer}`

The squad will incorporate your answer and continue from the {CURRENT_PHASE} phase.
```

- [ ] **Step 7: Commit templates**

```bash
git add templates/
git commit -m "feat: templates — state schema, evidence grades, context pack, kill report, feedback, escalation"
```

---

### Task 4: Create bash helper scripts

**Files:**
- Create: `scripts/bash/detect-project.sh`
- Create: `scripts/bash/run-understanding.sh`
- Create: `scripts/bash/setup-worktree.sh`
- Create: `scripts/bash/migrate-kb.sh`

- [ ] **Step 1: Create detect-project.sh**

```bash
#!/usr/bin/env bash
# detect-project.sh — Detect greenfield vs brownfield
# Usage: detect-project.sh [path]
# Returns: "greenfield" or "brownfield" to stdout

set -euo pipefail

TARGET_DIR="${1:-.}"

# Count source files (excluding common non-source patterns)
SOURCE_COUNT=$(find "$TARGET_DIR" \
  -type f \
  \( -name "*.py" -o -name "*.js" -o -name "*.ts" -o -name "*.java" \
     -o -name "*.go" -o -name "*.rs" -o -name "*.rb" -o -name "*.php" \
     -o -name "*.cs" -o -name "*.cpp" -o -name "*.c" -o -name "*.swift" \
     -o -name "*.kt" -o -name "*.scala" -o -name "*.pas" -o -name "*.pl" \) \
  -not -path "*/node_modules/*" \
  -not -path "*/.git/*" \
  -not -path "*/vendor/*" \
  -not -path "*/dist/*" \
  -not -path "*/build/*" \
  -not -path "*/.specify/*" \
  2>/dev/null | wc -l | tr -d ' ')

if [ "$SOURCE_COUNT" -gt 5 ]; then
  echo "brownfield"
else
  echo "greenfield"
fi
```

- [ ] **Step 2: Create run-understanding.sh**

```bash
#!/usr/bin/env bash
# run-understanding.sh — Run Understanding CLI on a spec file
# Usage: run-understanding.sh <spec-file> [--validate] [--json]
# Returns: Understanding output to stdout

set -euo pipefail

SPEC_FILE="${1:?Usage: run-understanding.sh <spec-file> [--validate] [--json]}"
shift

# Check if understanding CLI is available
if ! command -v understanding &>/dev/null; then
  echo '{"error": "understanding CLI not found", "fallback": true}' >&2
  exit 1
fi

# Run understanding with passed flags
understanding "$SPEC_FILE" --enhanced "$@"
```

- [ ] **Step 3: Create setup-worktree.sh**

```bash
#!/usr/bin/env bash
# setup-worktree.sh — Create a throwaway git worktree for SCIENTIST experiments
# Usage: setup-worktree.sh [experiment-name]
# Returns: worktree path to stdout

set -euo pipefail

EXPERIMENT="${1:-experiment}"
TIMESTAMP=$(date +%s)
WORKTREE_DIR="/tmp/squad-experiment-${EXPERIMENT}-${TIMESTAMP}"

# Create worktree from current HEAD
git worktree add "$WORKTREE_DIR" HEAD --detach 2>/dev/null

echo "$WORKTREE_DIR"
```

- [ ] **Step 4: Create migrate-kb.sh**

```bash
#!/usr/bin/env bash
# migrate-kb.sh — Migrate knowledge base files between schema versions
# Usage: migrate-kb.sh <kb-dir> <from-version> <to-version>

set -euo pipefail

KB_DIR="${1:?Usage: migrate-kb.sh <kb-dir> <from-version> <to-version>}"
FROM_V="${2:?Missing from-version}"
TO_V="${3:?Missing to-version}"

echo "Migrating knowledge base from v${FROM_V} to v${TO_V}"
echo "Directory: ${KB_DIR}"

# Version 1 is the initial version — no migrations yet
if [ "$FROM_V" -eq 1 ] && [ "$TO_V" -eq 1 ]; then
  echo "Already at v1. No migration needed."
  exit 0
fi

echo "No migration path from v${FROM_V} to v${TO_V}"
exit 1
```

- [ ] **Step 5: Make scripts executable and commit**

```bash
chmod +x scripts/bash/*.sh
git add scripts/
git commit -m "feat: bash helper scripts — detect-project, run-understanding, setup-worktree, migrate-kb"
```

---

## Chunk 2: MANAGER Command (The Brain)

### Task 5: Create the MANAGER command — squad.run.md

This is the most critical file. It contains the full state machine, context pack compilation logic, subagent dispatch, convergence detection, and all routing decisions.

**Files:**
- Create: `commands/squad.run.md`

- [ ] **Step 1: Write the MANAGER command**

Create `commands/squad.run.md` with the full orchestration prompt. This file is the brain of the system. It must contain:

1. **YAML frontmatter** with description and script references
2. **State machine definition** — all phases, transitions, and conditions
3. **Context pack compilation rules** — what each agent receives
4. **Subagent dispatch patterns** — how to invoke each agent via Agent tool
5. **Convergence rules** — when to stop iterating
6. **Evidence hierarchy** — how to resolve conflicts
7. **Error handling** — fallback modes for tool failures
8. **Human escalation protocol** — when and how to pause for input

The command must instruct the AI agent to:
- Read/create `state.json` for tracking
- Read/create `reasoning-journal.json` for inter-agent communication
- Dispatch each agent as a subagent with compiled context
- Read agent outputs (artifacts on disk) after each dispatch
- Evaluate quality scores and routing conditions
- Enforce convergence rules (delta, max iterations, budget)
- Produce final delivery artifacts

Full content for this file is in the implementation — see `commands/squad.run.md` in the repo. This is approximately 400-600 lines of markdown with embedded logic.

- [ ] **Step 2: Verify frontmatter is valid**

Open the file and confirm:
- `description` field exists
- `scripts.sh` paths are correct (relative to extension root)
- `$ARGUMENTS` placeholder is present in User Input section

- [ ] **Step 3: Commit**

```bash
git add commands/squad.run.md
git commit -m "feat: MANAGER command — full state machine, context packs, subagent dispatch"
```

---

### Task 6: Create supporting commands

**Files:**
- Create: `commands/squad.status.md`
- Create: `commands/squad.innovate.md`
- Create: `commands/squad.investigate.md`
- Create: `commands/squad.ground.md`
- Create: `commands/squad.feedback.md`
- Create: `commands/squad.resume.md`

- [ ] **Step 1: Write squad.status.md**

Read `state.json` and present current squad state: phase, iteration, quality scores, active specialists, any blocked issues. Format as a readable summary.

- [ ] **Step 2: Write squad.innovate.md**

Dispatch the INNOVATE specialist agent. Read current artifacts, pass to INNOVATE agent prompt, collect alternatives.md output.

- [ ] **Step 3: Write squad.investigate.md**

Dispatch the SCIENTIST specialist agent with the user's question. Set up worktree if experiment needed. Collect investigation report.

- [ ] **Step 4: Write squad.ground.md**

Dispatch the GROUND learning agent. Read all current artifacts, run reality check, produce reality-check.md + cost-analysis.md + benchmark-data.md.

- [ ] **Step 5: Write squad.feedback.md**

Guide user through feedback questionnaire (from template). Collect answers, update knowledge base YAML files (calibration-profile, estimates-log, patterns).

- [ ] **Step 6: Write squad.resume.md**

Read `state.json` to find blocked state and escalation question. Incorporate user's answer. Resume MANAGER from blocked phase.

- [ ] **Step 7: Commit all commands**

```bash
git add commands/
git commit -m "feat: supporting commands — status, innovate, investigate, ground, feedback, resume"
```

---

## Chunk 3: Core Agent Prompts

### Task 7: Create DISCOVER agent prompt

**Files:**
- Create: `agents/core/discover.md`

- [ ] **Step 1: Write discover.md**

The DISCOVER agent prompt must instruct the AI to:

**Brownfield mode:**
1. Check if `spec-kit-reverse-eng` is available
2. If yes: run `/speckit.reverse-eng.extract` or read existing `analysis.json`
3. Go deeper: identify implicit business rules, behavioral patterns, git history context
4. Build domain glossary, mental model, boundaries, assumptions, unknowns

**Greenfield mode:**
1. Run domain research pipeline:
   - Search for reference architectures in the problem domain
   - Scan for similar open-source projects and their structures
   - Load domain-specific standards and regulations
   - Generate assumptions from analogies with similar systems
2. Structure user's description against discovered domain map
3. Build same outputs as brownfield

**Both modes output:**
- `glossary.md`, `mental-model.md`, `boundaries.md`, `assumptions.md`, `unknowns.md`
- `reference-architectures.md` (greenfield only)
- Append insights to `reasoning-journal.json`

The prompt should be detailed enough that a fresh Claude Code subagent can execute it autonomously given only the context pack.

- [ ] **Step 2: Commit**

```bash
git add agents/core/discover.md
git commit -m "feat: DISCOVER agent — brownfield extraction + greenfield domain research"
```

---

### Task 8: Create WHAT agent prompt

**Files:**
- Create: `agents/core/what.md`

- [ ] **Step 1: Write what.md**

The WHAT agent transforms DISCOVER's outputs into spec-kit format specifications:
- Read glossary, mental model, boundaries, assumptions, unknowns
- Write user stories with Given/When/Then acceptance criteria
- Define functional + non-functional requirements
- Identify key entities and relationships
- NO implementation details (no languages, frameworks, databases)
- Output: `spec.md`, `00-overview.md`
- Append decisions to `reasoning-journal.json`

- [ ] **Step 2: Commit**

```bash
git add agents/core/what.md
git commit -m "feat: WHAT agent — requirements definition from discovered territory"
```

---

### Task 9: Create WHY agent prompt

**Files:**
- Create: `agents/core/why.md`

- [ ] **Step 1: Write why.md**

The WHY agent operates in two modes:

**Assumption-challenge mode (WHY1):**
- Read DISCOVER outputs
- Challenge assumptions for logical consistency
- Identify contradictions in domain map
- Pre-mortem: "if our understanding is wrong, where?"
- Flag unknowns for SCIENTIST
- Output: `assumption-review.md`, `issues.md`

**Spec-validation mode (WHY2, WHY3):**
- Run `understanding validate` on spec.md (via run-understanding.sh)
- Parse quality gate scores
- Challenge requirements for ambiguity, incompleteness, untestability
- Hunt for unknown unknowns
- Check cross-artifact consistency
- Output: `quality-gates.md`, `issues.md`

Both modes append to `reasoning-journal.json`.

- [ ] **Step 2: Commit**

```bash
git add agents/core/why.md
git commit -m "feat: WHY agent — dual mode adversarial critic with Understanding integration"
```

---

### Task 10: Create ASSESS agent prompt

**Files:**
- Create: `agents/core/assess.md`

- [ ] **Step 1: Write assess.md**

The ASSESS agent evaluates feasibility and acts as kill gate:
- Read spec.md, glossary, assumptions, issues from WHY
- Read calibration-profile.yaml and estimates-log.yaml for historical data
- Evaluate feasibility (can this be built within constraints?)
- Estimate effort using Function Point Analysis (adjusted by calibration)
- Classify features with Kano model (must-be / performance / delighter)
- Score with RICE (Reach, Impact, Confidence, Effort)
- Scope MVP vs full vs v2-deferred
- **Kill decision:** if unfeasible or all low-priority → produce kill report
- **Defer decision:** if scope too large → recommend reduction
- Output: `feasibility.md`, `prioritization.md`, `estimates.md`, `mvp-scope.md`
- Append to `reasoning-journal.json`

**ASSESS2 (consensus mode):**
- Re-evaluate feasibility against concrete architecture
- Update effort estimates with architectural complexity
- Run implementability check (6-point checklist from design doc)
- Output: `implementability-report.md`

- [ ] **Step 2: Commit**

```bash
git add agents/core/assess.md
git commit -m "feat: ASSESS agent — kill gate, estimation, RICE/Kano, implementability"
```

---

### Task 11: Create HOW agent prompt

**Files:**
- Create: `agents/core/how.md`

- [ ] **Step 1: Write how.md**

The HOW agent makes architecture decisions:
- Read spec.md, feasibility, prioritization, specialist outputs
- Select technology stack with explicit rationale and alternatives
- Design system structure (data model, API contracts, components)
- Define cross-cutting concerns (security, observability, performance)
- Create constitution (non-negotiable project principles)
- Document every decision in ADR format
- Output: `plan.md`, `research.md`, `data-model.md`, `contracts/`, `constitution.md`
- Append all decisions with rationale to `reasoning-journal.json`

- [ ] **Step 2: Commit**

```bash
git add agents/core/how.md
git commit -m "feat: HOW agent — architecture decisions with ADRs and cross-cutting concerns"
```

---

### Task 12: Create PLAN agent prompt

**Files:**
- Create: `agents/core/plan.md`

- [ ] **Step 1: Write plan.md**

The PLAN agent breaks architecture into executable tasks:
- Read plan.md, research.md, data-model.md, contracts/, test-strategy.md
- Break into phased tasks (foundation → features → polish)
- Identify critical path (longest dependency chain)
- Map dependencies and parallelization with [P] markers
- Assess risk per task (probability x impact)
- Include effort estimates per task (from ASSESS data)
- Output: `tasks.md`, `critical-path.md`, `risk-matrix.md`, `dependencies.md`
- Append to `reasoning-journal.json`

**PLAN2 (consensus mode):**
- Re-evaluate dependencies with specialist-added tasks
- Update critical path
- Validate all specialist outputs have corresponding tasks
- Incorporate implementability feedback

- [ ] **Step 2: Commit**

```bash
git add agents/core/plan.md
git commit -m "feat: PLAN agent — task breakdown with critical path and risk analysis"
```

---

### Task 13: Create MANAGER agent prompt

**Files:**
- Create: `agents/core/manager.md`

- [ ] **Step 1: Write manager.md**

The MANAGER agent prompt is the system prompt that gets embedded in `squad.run.md`. It contains:
- Full state machine definition with all phases and transitions
- Decision rules for routing (which agent next, when to loop, when to stop)
- Convergence detection rules
- Evidence hierarchy for conflict resolution
- Token budget tracking
- Specialist summoning logic
- Error handling and fallback modes
- Human escalation protocol

This is the reference document that `squad.run.md` follows.

- [ ] **Step 2: Commit**

```bash
git add agents/core/manager.md
git commit -m "feat: MANAGER agent — state machine, routing rules, convergence detection"
```

---

## Chunk 4: Specialist Agent Prompts

### Task 14: Create all 7 specialist agent prompts

**Files:**
- Create: `agents/specialists/scientist.md`
- Create: `agents/specialists/security.md`
- Create: `agents/specialists/test-architect.md`
- Create: `agents/specialists/domain-expert.md`
- Create: `agents/specialists/ux-a11y.md`
- Create: `agents/specialists/performance.md`
- Create: `agents/specialists/innovate.md`

- [ ] **Step 1: Write scientist.md**

The SCIENTIST agent owns the full scientific method:
1. QUESTION — receive specific question from requesting agent
2. RESEARCH — web search, papers, docs, prior art, benchmarks
3. EVALUATE — grade evidence quality (A/B/C/D/E per evidence-grades.md)
4. HYPOTHESIZE — "If X, then Y because Z"
5. EXPERIMENT — prototype spike in git worktree (via setup-worktree.sh)
6. MEASURE — run spike, collect data
7. SYNTHESIZE — combine all evidence
8. RECOMMEND — confidence-scored conclusion

Output: `investigation/{topic}.md`, `evidence-grades.md`, `experiment-results.md`, `recommendations.md`, `knowledge-gaps.md`

- [ ] **Step 2: Write security.md**

OWASP Top 10, STRIDE threat modeling, compliance frameworks.
Output: `threat-model.md`, `compliance-requirements.md`, security amendments.

- [ ] **Step 3: Write test-architect.md**

Test pyramid, coverage analysis, acceptance → test mapping.
Output: `test-strategy.md`, `test-architecture.md`, `coverage-map.md`

- [ ] **Step 4: Write domain-expert.md**

Dynamic domain loading based on DISCOVER's classification.
Prompt includes instructions for loading domain-specific knowledge.
Output: domain-specific amendments to spec, plan, glossary.

- [ ] **Step 5: Write ux-a11y.md**

WCAG 2.1/2.2, Nielsen's 10 heuristics, user flow analysis.
Output: `accessibility-requirements.md`, `user-flow.md`, UX amendments.

- [ ] **Step 6: Write performance.md**

Load modeling, capacity planning, Little's Law, Amdahl's Law.
Output: `performance-requirements.md`, `capacity-model.md`, performance amendments.

- [ ] **Step 7: Write innovate.md**

TRIZ, Design Thinking, Blue Ocean, First Principles, Antifragility.
Propose 2-3 fundamentally different approaches with risk/upside analysis.
Output: `alternatives.md`, `risk-opportunities.md`, `challenge-assumptions.md`

- [ ] **Step 8: Commit all specialists**

```bash
git add agents/specialists/
git commit -m "feat: 7 specialist agents — scientist, security, test-architect, domain-expert, ux-a11y, performance, innovate"
```

---

## Chunk 5: Learning Layer Agent Prompts

### Task 15: Create all 4 learning layer agent prompts

**Files:**
- Create: `agents/learning/reflect.md`
- Create: `agents/learning/evolve.md`
- Create: `agents/learning/calibrate.md`
- Create: `agents/learning/ground.md`

- [ ] **Step 1: Write reflect.md**

Post-run analysis:
- What assumptions were wrong?
- Which patterns worked?
- What should the squad do differently?
- Update `knowledge-base/patterns.yaml` and `pitfalls.yaml`

- [ ] **Step 2: Write evolve.md**

Cross-run diffing and improvement tracking:
- Load prior run artifacts (if re-run)
- Diff against current artifacts
- Measure quality trajectory
- Detect stagnation and regressions
- Check knowledge base for confirmation bias
- Output: `evolution-report.md`, `improvement-metrics.md`, `stagnation-flags.md`

- [ ] **Step 3: Write calibrate.md**

AI accuracy tracking:
- Read feedback history from `knowledge-base/feedback/`
- Compute accuracy per domain
- Update `knowledge-base/calibration-profile.yaml`
- Flag low-confidence domains
- Output: `calibration-profile.yaml`, `confidence-flags.md`

- [ ] **Step 4: Write ground.md**

Reality check against real-world data:
- Compare plans to infrastructure costs, production benchmarks
- Compare estimates to actual outcomes from past projects
- Check architecture against operational constraints
- Output: `reality-check.md`, `cost-analysis.md`, `benchmark-data.md`

- [ ] **Step 5: Commit all learning agents**

```bash
git add agents/learning/
git commit -m "feat: 4 learning agents — reflect, evolve, calibrate, ground"
```

---

## Chunk 6: README and Integration Test

### Task 16: Write comprehensive README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README.md**

Cover:
- What is Cognitive Squad (one paragraph)
- Architecture diagram (text-based, from design doc)
- Installation (`specify extension add cognitive-squad`)
- Quick start (`/speckit.squad.run "Build a photo album app"`)
- All 7 commands with descriptions
- Configuration reference
- Prerequisites (spec-kit, optionally understanding CLI, reverse-eng)
- How it works (the flow: DISCOVER → WHY1 → WHAT → WHY2 → ASSESS → ... → DONE)
- Learning cycle (how FEEDBACK improves future runs)
- Evidence grades reference
- Troubleshooting
- License

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "feat: comprehensive README with architecture, commands, configuration"
```

---

### Task 17: Integration validation

- [ ] **Step 1: Verify extension.yml is valid**

Check that all command file paths in `extension.yml` actually exist:

```bash
# Extract command file paths and verify each exists
grep "file:" extension.yml | awk '{print $2}' | tr -d '"' | while read f; do
  if [ ! -f "$f" ]; then echo "MISSING: $f"; fi
done
```

Expected: no output (all files exist).

- [ ] **Step 2: Verify all agent files are referenced**

```bash
# List all agent files
find agents/ -name "*.md" | sort

# Cross-reference with squad.run.md
grep -o 'agents/[a-z/]*\.md' commands/squad.run.md | sort | uniq
```

Verify all agent files are referenced by the MANAGER command.

- [ ] **Step 3: Verify knowledge base YAML is valid**

```bash
# Quick YAML validation (python one-liner)
python3 -c "
import yaml, glob
for f in glob.glob('knowledge-base/*.yaml'):
    with open(f) as fh:
        yaml.safe_load(fh)
    print(f'OK: {f}')
"
```

Expected: all files parse without error.

- [ ] **Step 4: Verify state schema JSON is valid**

```bash
python3 -c "
import json
with open('templates/state-schema.json') as f:
    json.load(f)
print('OK: state-schema.json')
"
```

- [ ] **Step 5: Final commit with all files**

```bash
git add -A
git status
git commit -m "feat: complete cognitive squad extension v0.1.0"
git push
```

---

## File Map (Complete)

```
cognitive-squad/
├── extension.yml                         # Extension manifest
├── config-template.yml                   # Configuration template
├── README.md                             # User documentation
├── LICENSE                               # MIT License
├── .gitignore
├── .extensionignore
├── docs/
│   └── design.md                         # Design specification
│
├── commands/                             # Slash commands (7)
│   ├── squad.run.md                      # MANAGER — main entry point
│   ├── squad.status.md                   # Check current state
│   ├── squad.innovate.md                 # Trigger INNOVATE
│   ├── squad.investigate.md              # Trigger SCIENTIST
│   ├── squad.ground.md                   # Trigger GROUND
│   ├── squad.feedback.md                 # Post-implementation feedback
│   └── squad.resume.md                   # Resume from BLOCKED
│
├── agents/                               # Agent prompts (18)
│   ├── core/                             # Tier 1 (7)
│   │   ├── manager.md
│   │   ├── discover.md
│   │   ├── what.md
│   │   ├── why.md
│   │   ├── assess.md
│   │   ├── how.md
│   │   └── plan.md
│   ├── specialists/                      # Tier 2 (7)
│   │   ├── scientist.md
│   │   ├── security.md
│   │   ├── test-architect.md
│   │   ├── domain-expert.md
│   │   ├── ux-a11y.md
│   │   ├── performance.md
│   │   └── innovate.md
│   └── learning/                         # Tier 3 (4)
│       ├── reflect.md
│       ├── evolve.md
│       ├── calibrate.md
│       └── ground.md
│
├── templates/                            # Supporting templates (6)
│   ├── state-schema.json
│   ├── evidence-grades.md
│   ├── context-pack.md
│   ├── kill-report.md
│   ├── feedback-questionnaire.md
│   └── escalation-request.md
│
├── scripts/
│   └── bash/                             # Helper scripts (4)
│       ├── detect-project.sh
│       ├── run-understanding.sh
│       ├── setup-worktree.sh
│       └── migrate-kb.sh
│
└── knowledge-base/                       # Persistent YAML store
    ├── patterns.yaml
    ├── estimates-log.yaml
    ├── pitfalls.yaml
    ├── calibration-profile.yaml
    ├── archive/
    ├── domain-glossaries/
    └── feedback/
```

**Total files to create: 42**
**Total agent prompts: 18**
**Total commands: 7**
**Total templates: 6**
**Total scripts: 4**
**Total knowledge base seeds: 4**
