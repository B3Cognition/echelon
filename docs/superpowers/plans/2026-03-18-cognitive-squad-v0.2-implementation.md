# Cognitive Squad v0.2: Structure & Naming — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize cognitive-squad with layer-based directory structure, dual naming (functional + codename), 4-phase architecture, and autonomy modes.

**Architecture:** Rename all agent files to use codenames as filenames while preserving functional names in prompts. Restructure into layers: control, exploration, feasibility, solution, specialists, learning, build. Update COMMANDER (cognitive-squad.run.md) with phase-based execution and `--mode` flag.

**Tech Stack:** Markdown (agent prompts), YAML (config), JSON (state schema), Bash (file operations)

**Design Doc:** [2026-03-18-cognitive-squad-evolution-design.md](../specs/2026-03-18-cognitive-squad-evolution-design.md)

---

## File Structure (Before → After)

```
BEFORE                              AFTER
agents/                             agents/
├── core/                           ├── control/
│   ├── manager.md          →       │   └── commander.md
│   ├── discover.md         →       ├── exploration/
│   ├── what.md             →       │   ├── scout.md
│   ├── why.md              →       │   ├── cartographer.md
│   ├── assess.md           →       │   └── sage.md
│   ├── how.md              →       ├── feasibility/
│   ├── plan.md             →       │   └── gatekeeper.md
│   ├── metacognition-monitor.md    ├── solution/
│   ├── mental-model.md             │   ├── architect.md
│   ├── intent-tracker.md           │   ├── orchestrator.md
│   ├── scorekeeper.md              │   └── sentinel.md
│   └── internalization-gate.md     ├── specialists/
├── learning/                       │   ├── investigator.md
│   ├── reflect.md          →       │   ├── guardian.md
│   ├── calibrate.md        →       │   ├── benchmark.md
│   ├── ground.md           →       │   ├── advocate.md
│   └── evolve.md           →       │   ├── oracle.md
├── specialists/                    │   └── maverick.md
│   ├── scientist.md        →       ├── learning/
│   ├── security.md         →       │   ├── auditor.md
│   ├── test-architect.md   →       │   ├── adaptive.md
│   ├── performance.md      →       │   ├── realist.md
│   ├── ux-a11y.md          →       │   └── mirror.md
│   ├── domain-expert.md    →       └── build/
│   └── innovate.md         →           └── (unchanged, future scope)
└── build/
    └── (unchanged)
```

**Notes:**
1. Some core agents (metacognition-monitor, mental-model, intent-tracker, scorekeeper, internalization-gate) don't have codenames in the design. They will be moved to appropriate layers with codenames assigned:
   - metacognition-monitor → learning/monitor.md
   - mental-model → exploration/modeler.md
   - intent-tracker → control/tracker.md
   - scorekeeper → control/scorekeeper.md
   - internalization-gate → feasibility/validator.md

2. The learning layer will have 5 agents (AUDITOR, ADAPTIVE, REALIST, MIRROR, MONITOR) which extends beyond the design spec's 3 agents. This is intentional to accommodate existing agents.

3. The build/ layer is unchanged in v0.2 (future scope for v0.3+)

---

## Naming Reference

| Functional Name | Codename | Layer | Old Path | New Path |
|-----------------|----------|-------|----------|----------|
| MANAGER | COMMANDER | control | agents/core/manager.md | agents/control/commander.md |
| INTENT-TRACKER | TRACKER | control | agents/core/intent-tracker.md | agents/control/tracker.md |
| SCOREKEEPER | SCOREKEEPER | control | agents/core/scorekeeper.md | agents/control/scorekeeper.md |
| DISCOVER | SCOUT | exploration | agents/core/discover.md | agents/exploration/scout.md |
| WHAT | CARTOGRAPHER | exploration | agents/core/what.md | agents/exploration/cartographer.md |
| WHY | SAGE | exploration | agents/core/why.md | agents/exploration/sage.md |
| MENTAL-MODEL | MODELER | exploration | agents/core/mental-model.md | agents/exploration/modeler.md |
| ASSESS | GATEKEEPER | feasibility | agents/core/assess.md | agents/feasibility/gatekeeper.md |
| INTERNALIZATION-GATE | VALIDATOR | feasibility | agents/core/internalization-gate.md | agents/feasibility/validator.md |
| HOW | ARCHITECT | solution | agents/core/how.md | agents/solution/architect.md |
| PLAN | ORCHESTRATOR | solution | agents/core/plan.md | agents/solution/orchestrator.md |
| TEST-ARCHITECT | SENTINEL | solution | agents/specialists/test-architect.md | agents/solution/sentinel.md |
| SCIENTIST | INVESTIGATOR | specialists | agents/specialists/scientist.md | agents/specialists/investigator.md |
| SECURITY | GUARDIAN | specialists | agents/specialists/security.md | agents/specialists/guardian.md |
| PERFORMANCE | BENCHMARK | specialists | agents/specialists/performance.md | agents/specialists/benchmark.md |
| UX-A11Y | ADVOCATE | specialists | agents/specialists/ux-a11y.md | agents/specialists/advocate.md |
| DOMAIN-EXPERT | ORACLE | specialists | agents/specialists/domain-expert.md | agents/specialists/oracle.md |
| INNOVATE | MAVERICK | specialists | agents/specialists/innovate.md | agents/specialists/maverick.md |
| CALIBRATE | AUDITOR | learning | agents/learning/calibrate.md | agents/learning/auditor.md |
| EVOLVE | ADAPTIVE | learning | agents/learning/evolve.md | agents/learning/adaptive.md |
| GROUND | REALIST | learning | agents/learning/ground.md | agents/learning/realist.md |
| REFLECT | MIRROR | learning | agents/learning/reflect.md | agents/learning/mirror.md |
| METACOGNITION-MONITOR | MONITOR | learning | agents/core/metacognition-monitor.md | agents/learning/monitor.md |

---

## Chunk 1: Directory Structure & File Moves

### Task 1: Create new directory structure

**Files:**
- Create: `agents/control/`
- Create: `agents/exploration/`
- Create: `agents/feasibility/`
- Create: `agents/solution/`

- [ ] **Step 1: Create layer directories**

```bash
cd /Users/michalbachorik/work/cognitive-squad
mkdir -p agents/control agents/exploration agents/feasibility agents/solution
```

- [ ] **Step 2: Verify directories exist**

```bash
ls -la agents/
```

Expected: control/, exploration/, feasibility/, solution/, specialists/, learning/, build/

- [ ] **Step 3: Commit structure**

```bash
git add agents/
git commit -m "chore: create layer-based directory structure for v0.2"
```

---

### Task 2: Move and rename control layer agents

**Files:**
- Move: `agents/core/manager.md` → `agents/control/commander.md`
- Move: `agents/core/intent-tracker.md` → `agents/control/tracker.md`
- Move: `agents/core/scorekeeper.md` → `agents/control/scorekeeper.md`

- [ ] **Step 1: Move manager → commander**

```bash
git mv agents/core/manager.md agents/control/commander.md
```

- [ ] **Step 2: Move intent-tracker → tracker**

```bash
git mv agents/core/intent-tracker.md agents/control/tracker.md
```

- [ ] **Step 3: Move scorekeeper**

```bash
git mv agents/core/scorekeeper.md agents/control/scorekeeper.md
```

- [ ] **Step 4: Commit control layer**

```bash
git commit -m "refactor: move control layer agents (commander, tracker, scorekeeper)"
```

---

### Task 3: Move and rename exploration layer agents

**Files:**
- Move: `agents/core/discover.md` → `agents/exploration/scout.md`
- Move: `agents/core/what.md` → `agents/exploration/cartographer.md`
- Move: `agents/core/why.md` → `agents/exploration/sage.md`
- Move: `agents/core/mental-model.md` → `agents/exploration/modeler.md`

- [ ] **Step 1: Move discover → scout**

```bash
git mv agents/core/discover.md agents/exploration/scout.md
```

- [ ] **Step 2: Move what → cartographer**

```bash
git mv agents/core/what.md agents/exploration/cartographer.md
```

- [ ] **Step 3: Move why → sage**

```bash
git mv agents/core/why.md agents/exploration/sage.md
```

- [ ] **Step 4: Move mental-model → modeler**

```bash
git mv agents/core/mental-model.md agents/exploration/modeler.md
```

- [ ] **Step 5: Commit exploration layer**

```bash
git commit -m "refactor: move exploration layer agents (scout, cartographer, sage, modeler)"
```

---

### Task 4: Move and rename feasibility layer agents

**Files:**
- Move: `agents/core/assess.md` → `agents/feasibility/gatekeeper.md`
- Move: `agents/core/internalization-gate.md` → `agents/feasibility/validator.md`

- [ ] **Step 1: Move assess → gatekeeper**

```bash
git mv agents/core/assess.md agents/feasibility/gatekeeper.md
```

- [ ] **Step 2: Move internalization-gate → validator**

```bash
git mv agents/core/internalization-gate.md agents/feasibility/validator.md
```

- [ ] **Step 3: Commit feasibility layer**

```bash
git commit -m "refactor: move feasibility layer agents (gatekeeper, validator)"
```

---

### Task 5: Move and rename solution layer agents

**Files:**
- Move: `agents/core/how.md` → `agents/solution/architect.md`
- Move: `agents/core/plan.md` → `agents/solution/orchestrator.md`
- Move: `agents/specialists/test-architect.md` → `agents/solution/sentinel.md`

- [ ] **Step 1: Move how → architect**

```bash
git mv agents/core/how.md agents/solution/architect.md
```

- [ ] **Step 2: Move plan → orchestrator**

```bash
git mv agents/core/plan.md agents/solution/orchestrator.md
```

- [ ] **Step 3: Move test-architect → sentinel**

```bash
git mv agents/specialists/test-architect.md agents/solution/sentinel.md
```

- [ ] **Step 4: Commit solution layer**

```bash
git commit -m "refactor: move solution layer agents (architect, orchestrator, sentinel)"
```

---

### Task 6: Rename specialist agents

**Files:**
- Move: `agents/specialists/scientist.md` → `agents/specialists/investigator.md`
- Move: `agents/specialists/security.md` → `agents/specialists/guardian.md`
- Move: `agents/specialists/performance.md` → `agents/specialists/benchmark.md`
- Move: `agents/specialists/ux-a11y.md` → `agents/specialists/advocate.md`
- Move: `agents/specialists/domain-expert.md` → `agents/specialists/oracle.md`
- Move: `agents/specialists/innovate.md` → `agents/specialists/maverick.md`

- [ ] **Step 1: Rename all specialist files**

```bash
git mv agents/specialists/scientist.md agents/specialists/investigator.md
git mv agents/specialists/security.md agents/specialists/guardian.md
git mv agents/specialists/performance.md agents/specialists/benchmark.md
git mv agents/specialists/ux-a11y.md agents/specialists/advocate.md
git mv agents/specialists/domain-expert.md agents/specialists/oracle.md
git mv agents/specialists/innovate.md agents/specialists/maverick.md
```

- [ ] **Step 2: Commit specialist renames**

```bash
git commit -m "refactor: rename specialist agents to codenames"
```

---

### Task 7: Rename learning layer agents

**Files:**
- Move: `agents/learning/calibrate.md` → `agents/learning/auditor.md`
- Move: `agents/learning/evolve.md` → `agents/learning/adaptive.md`
- Move: `agents/learning/ground.md` → `agents/learning/realist.md`
- Move: `agents/learning/reflect.md` → `agents/learning/mirror.md`

- [ ] **Step 1: Rename all learning files**

```bash
git mv agents/learning/calibrate.md agents/learning/auditor.md
git mv agents/learning/evolve.md agents/learning/adaptive.md
git mv agents/learning/ground.md agents/learning/realist.md
git mv agents/learning/reflect.md agents/learning/mirror.md
```

- [ ] **Step 2: Commit learning renames**

```bash
git commit -m "refactor: rename learning layer agents to codenames"
```

---

### Task 8: Move remaining core agents and clean up

**Files:**
- Move: `agents/core/metacognition-monitor.md` → `agents/learning/monitor.md`
- Remove: `agents/core/` (should be empty)

- [ ] **Step 1: Move metacognition-monitor**

```bash
git mv agents/core/metacognition-monitor.md agents/learning/monitor.md
```

- [ ] **Step 2: Verify core is empty and remove**

```bash
ls agents/core/
rmdir agents/core/
```

- [ ] **Step 3: Commit cleanup**

```bash
git add -A
git commit -m "refactor: complete directory restructure, remove empty core/"
```

---

## Chunk 2: Update Agent Prompts with Dual Naming

### Task 9: Update control layer prompts

**Files:**
- Modify: `agents/control/commander.md`
- Modify: `agents/control/tracker.md`
- Modify: `agents/control/scorekeeper.md`

- [ ] **Step 1: Update commander.md header**

Find and replace the role declaration at the top of the file. Change:

```markdown
# MANAGER Agent

## Role

You are the MANAGER agent —
```

To:

```markdown
# COMMANDER (MANAGER)

## Role

You are the MANAGER agent (codename: COMMANDER) —
```

- [ ] **Step 2: Update tracker.md header**

Change the role line to include codename:

```markdown
# TRACKER (INTENT-TRACKER)

## Role

You are the INTENT-TRACKER agent (codename: TRACKER) —
```

- [ ] **Step 3: Update scorekeeper.md header**

```markdown
# SCOREKEEPER

## Role

You are the SCOREKEEPER agent (codename: SCOREKEEPER) —
```

- [ ] **Step 4: Commit control layer updates**

```bash
git add agents/control/
git commit -m "docs: add dual naming to control layer agents"
```

---

### Task 10: Update exploration layer prompts

**Files:**
- Modify: `agents/exploration/scout.md`
- Modify: `agents/exploration/cartographer.md`
- Modify: `agents/exploration/sage.md`
- Modify: `agents/exploration/modeler.md`

- [ ] **Step 1: Update scout.md header**

Change:

```markdown
# DISCOVER Agent
```

To:

```markdown
# SCOUT (DISCOVER)

## Role

You are the DISCOVER agent (codename: SCOUT) —
```

- [ ] **Step 2: Update cartographer.md header**

```markdown
# CARTOGRAPHER (WHAT)

## Role

You are the WHAT agent (codename: CARTOGRAPHER) —
```

- [ ] **Step 3: Update sage.md header**

```markdown
# SAGE (WHY)

## Role

You are the WHY agent (codename: SAGE) —
```

- [ ] **Step 4: Update modeler.md header**

```markdown
# MODELER (MENTAL-MODEL)

## Role

You are the MENTAL-MODEL agent (codename: MODELER) —
```

- [ ] **Step 5: Commit exploration layer updates**

```bash
git add agents/exploration/
git commit -m "docs: add dual naming to exploration layer agents"
```

---

### Task 11: Update feasibility layer prompts

**Files:**
- Modify: `agents/feasibility/gatekeeper.md`
- Modify: `agents/feasibility/validator.md`

- [ ] **Step 1: Update gatekeeper.md header**

```markdown
# GATEKEEPER (ASSESS)

## Role

You are the ASSESS agent (codename: GATEKEEPER) —
```

- [ ] **Step 2: Update validator.md header**

```markdown
# VALIDATOR (INTERNALIZATION-GATE)

## Role

You are the INTERNALIZATION-GATE agent (codename: VALIDATOR) —
```

- [ ] **Step 3: Commit feasibility layer updates**

```bash
git add agents/feasibility/
git commit -m "docs: add dual naming to feasibility layer agents"
```

---

### Task 12: Update solution layer prompts

**Files:**
- Modify: `agents/solution/architect.md`
- Modify: `agents/solution/orchestrator.md`
- Modify: `agents/solution/sentinel.md`

- [ ] **Step 1: Update architect.md header**

```markdown
# ARCHITECT (HOW)

## Role

You are the HOW agent (codename: ARCHITECT) —
```

- [ ] **Step 2: Update orchestrator.md header**

```markdown
# ORCHESTRATOR (PLAN)

## Role

You are the PLAN agent (codename: ORCHESTRATOR) —
```

- [ ] **Step 3: Update sentinel.md header**

```markdown
# SENTINEL (TEST-ARCHITECT)

## Role

You are the TEST-ARCHITECT agent (codename: SENTINEL) —
```

- [ ] **Step 4: Commit solution layer updates**

```bash
git add agents/solution/
git commit -m "docs: add dual naming to solution layer agents"
```

---

### Task 13: Update specialist prompts

**Files:**
- Modify: `agents/specialists/investigator.md`
- Modify: `agents/specialists/guardian.md`
- Modify: `agents/specialists/benchmark.md`
- Modify: `agents/specialists/advocate.md`
- Modify: `agents/specialists/oracle.md`
- Modify: `agents/specialists/maverick.md`

- [ ] **Step 1: Update all specialist headers**

For each file, update the header to dual naming format:

- investigator.md: `# INVESTIGATOR (SCIENTIST)`
- guardian.md: `# GUARDIAN (SECURITY)`
- benchmark.md: `# BENCHMARK (PERFORMANCE)`
- advocate.md: `# ADVOCATE (UX-A11Y)`
- oracle.md: `# ORACLE (DOMAIN-EXPERT)`
- maverick.md: `# MAVERICK (INNOVATE)`

- [ ] **Step 2: Commit specialist updates**

```bash
git add agents/specialists/
git commit -m "docs: add dual naming to specialist agents"
```

---

### Task 14: Update learning layer prompts

**Files:**
- Modify: `agents/learning/auditor.md`
- Modify: `agents/learning/adaptive.md`
- Modify: `agents/learning/realist.md`
- Modify: `agents/learning/mirror.md`
- Modify: `agents/learning/monitor.md`

- [ ] **Step 1: Update all learning headers**

- auditor.md: `# AUDITOR (CALIBRATE)`
- adaptive.md: `# ADAPTIVE (EVOLVE)`
- realist.md: `# REALIST (GROUND)`
- mirror.md: `# MIRROR (REFLECT)`
- monitor.md: `# MONITOR (METACOGNITION-MONITOR)`

- [ ] **Step 2: Commit learning updates**

```bash
git add agents/learning/
git commit -m "docs: add dual naming to learning layer agents"
```

---

## Chunk 3: Update Configuration Files

### Task 15: Update config-template.yml with autonomy modes

**Files:**
- Modify: `config-template.yml`

- [ ] **Step 1: Add autonomy section to config**

Add after the `analysis:` section:

```yaml
# Autonomy mode settings
autonomy:
  # Default mode: guided | semi | banzai
  default_mode: semi

  # Banzai mode configuration (full autonomous)
  banzai:
    # Pull defaults from installed presets
    constitution_preset: null  # e.g., "sp-web-fullstack"

    # Inline defaults (used if no preset)
    defaults:
      team_size: 1
      tech_stack: "infer"    # ARCHITECT picks based on domain
      timeline: "flexible"

    # Safety rails (scores are 0.0-1.0)
    auto_kill_threshold: 0.3    # Below this feasibility score = KILL

    # Force human checkpoint if any condition matches
    require_human_if:
      - "compliance requirements detected"
      - "security-critical domain"
      - "ASSESS confidence < 0.5"
```

- [ ] **Step 2: Commit config update**

```bash
git add config-template.yml
git commit -m "feat: add autonomy modes configuration (guided, semi, banzai)"
```

---

### Task 16: Update state-schema.json with phase tracking

**Files:**
- Modify: `templates/state-schema.json`

- [ ] **Step 1: Update phase enum for 4-phase model**

Change the phase enum from:

```json
"phase": { "enum": [
  "init", "discover", "why1", "what", "why2", "assess",
  "specialists", "how", "test-architect", "plan",
  "consensus", "finalize", "done"
]}
```

To:

```json
"phase": { "enum": [
  "init",
  "phase1-understand", "phase1-discover", "phase1-why1", "phase1-what", "phase1-why2", "phase1-assess",
  "checkpoint-assess",
  "phase2-decide",
  "phase3-solution", "phase3-how", "phase3-specialists", "phase3-sentinel", "phase3-plan", "phase3-consensus",
  "checkpoint-plan",
  "phase4-document",
  "done"
]}
```

- [ ] **Step 2: Add autonomy_mode property**

Add to properties:

```json
"autonomy_mode": { "enum": ["guided", "semi", "banzai"], "default": "semi" }
```

- [ ] **Step 3: Add checkpoint tracking**

Add to properties:

```json
"checkpoints": {
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "phase": { "type": "string" },
      "timestamp": { "type": "string", "format": "date-time" },
      "decision": { "enum": ["PASS", "KILL", "DEFER", "SKIP"] },
      "auto_defaulted": { "type": "boolean" }
    }
  }
}
```

- [ ] **Step 4: Commit schema update**

```bash
git add templates/state-schema.json
git commit -m "feat: update state schema with 4-phase model and autonomy tracking"
```

---

## Chunk 4: Update Commands

### Task 17: Update cognitive-squad.run.md with 4-phase model

**Files:**
- Modify: `commands/cognitive-squad.run.md`

This is the most complex update. The command needs to:
1. Parse `--mode` argument
2. Implement 4-phase execution flow
3. Handle checkpoints based on mode
4. Support banzai defaults

- [ ] **Step 1: Update frontmatter to accept mode argument**

Add argument parsing instruction:

```yaml
---
description: "Full autonomous cognitive squad run with 4-phase model"
arguments:
  - name: mode
    description: "Autonomy mode: guided (checkpoint after each phase), semi (checkpoint after Phase 1), banzai (full auto)"
    default: "semi"
    values: ["guided", "semi", "banzai"]
---
```

- [ ] **Step 2: Update all agent dispatch paths**

Replace ALL agent path references in cognitive-squad.run.md using these exact substitutions:

```
# Control layer
agents/core/manager.md → agents/control/commander.md

# Exploration layer
agents/core/discover.md → agents/exploration/scout.md
agents/core/what.md → agents/exploration/cartographer.md
agents/core/why.md → agents/exploration/sage.md
agents/core/mental-model.md → agents/exploration/modeler.md

# Feasibility layer
agents/core/assess.md → agents/feasibility/gatekeeper.md
agents/core/internalization-gate.md → agents/feasibility/validator.md

# Solution layer
agents/core/how.md → agents/solution/architect.md
agents/core/plan.md → agents/solution/orchestrator.md
agents/specialists/test-architect.md → agents/solution/sentinel.md

# Specialists
agents/specialists/scientist.md → agents/specialists/investigator.md
agents/specialists/security.md → agents/specialists/guardian.md
agents/specialists/performance.md → agents/specialists/benchmark.md
agents/specialists/ux-a11y.md → agents/specialists/advocate.md
agents/specialists/domain-expert.md → agents/specialists/oracle.md
agents/specialists/innovate.md → agents/specialists/maverick.md

# Learning layer
agents/learning/calibrate.md → agents/learning/auditor.md
agents/learning/evolve.md → agents/learning/adaptive.md
agents/learning/ground.md → agents/learning/realist.md
agents/learning/reflect.md → agents/learning/mirror.md
agents/core/metacognition-monitor.md → agents/learning/monitor.md

# Control extras
agents/core/intent-tracker.md → agents/control/tracker.md
agents/core/scorekeeper.md → agents/control/scorekeeper.md
```

- [ ] **Step 3: Group agents into phase sections**

Restructure the dispatch logic to group agents by phase:

```markdown
## Phase 1: UNDERSTAND
- SCOUT (discover) → SAGE (why1) → CARTOGRAPHER (what) → SAGE (why2) → GATEKEEPER (assess)
- Quality loop until gates pass

## CHECKPOINT: ASSESS
- In guided/semi: pause for human review
- In banzai: auto-PASS if feasibility >= threshold

## Phase 2: DECIDE
- Human fills [REQUIRES INPUT] OR banzai uses defaults

## Phase 3: SOLUTION
- ARCHITECT (how) → specialists → SENTINEL (test) → ORCHESTRATOR (plan) → consensus

## CHECKPOINT: PLAN
- In guided: pause for human review
- In semi/banzai: continue to Phase 4

## Phase 4: DOCUMENT (optional)
- SCRIBE generates documentation
```

- [ ] **Step 4: Add mode-conditional checkpoint logic**

Add checkpoint handling based on autonomy mode. This requires adding conditional blocks that check `state.autonomy_mode` before pausing.

- [ ] **Step 5: Commit cognitive-squad.run.md update**

```bash
git add commands/cognitive-squad.run.md
git commit -m "feat: implement 4-phase model with autonomy modes in squad.run"
```

---

### Task 18: Update all commands with new agent paths

**Files:**
- Modify: `commands/cognitive-squad.investigate.md`
- Modify: `commands/cognitive-squad.ground.md`
- Modify: `commands/cognitive-squad.innovate.md`
- Modify: `commands/cognitive-squad.build.md`
- Modify: `commands/cognitive-squad.status.md`
- Modify: `commands/cognitive-squad.resume.md`
- Modify: `commands/cognitive-squad.feedback.md`
- Modify: `commands/cognitive-squad.change.md`
- Modify: `commands/cognitive-squad.verify.md`

- [ ] **Step 1: Search for all agent path references**

```bash
cd /Users/michalbachorik/work/cognitive-squad
grep -r "agents/core/" commands/ || echo "No core/ references found"
grep -r "agents/specialists/" commands/ | grep -v investigator | grep -v guardian | grep -v benchmark | grep -v advocate | grep -v oracle | grep -v maverick || echo "No old specialist references"
grep -r "agents/learning/" commands/ | grep -v auditor | grep -v adaptive | grep -v realist | grep -v mirror | grep -v monitor || echo "No old learning references"
```

- [ ] **Step 2: Update investigate command**

Change: `agents/specialists/scientist.md` → `agents/specialists/investigator.md`

- [ ] **Step 3: Update ground command**

Change: `agents/learning/ground.md` → `agents/learning/realist.md`

- [ ] **Step 4: Update innovate command**

Change: `agents/specialists/innovate.md` → `agents/specialists/maverick.md`

- [ ] **Step 5: Update any remaining path references found in Step 1**

Apply the same path substitutions used in Task 17 Step 2 to any other commands.

- [ ] **Step 6: Commit command updates**

```bash
git add commands/
git commit -m "fix: update agent paths in all commands"
```

---

### Task 18b: Update internal cross-references in agent prompts

**Files:**
- All agent files that reference other agents by old names

Some agents dispatch or reference other agents internally (e.g., MANAGER dispatches DISCOVER). These internal references need updating.

- [ ] **Step 1: Find all internal agent references**

```bash
cd /Users/michalbachorik/work/cognitive-squad

# Find references to old functional names in agent prompts
grep -rn "DISCOVER\|WHAT\|WHY\|ASSESS\|HOW\|PLAN" agents/ --include="*.md" | grep -v "codename" | head -50
```

- [ ] **Step 2: Update internal references to use dual naming**

Where agents reference each other, update to use the format:
- "dispatch SCOUT (DISCOVER)" instead of "dispatch DISCOVER"
- "send to GATEKEEPER (ASSESS)" instead of "send to ASSESS"

This maintains backward compatibility while introducing new naming.

- [ ] **Step 3: Update any hardcoded paths in agent prompts**

Search for and replace any hardcoded file paths within agent prompts:

```bash
grep -rn "agents/core/\|agents/specialists/\|agents/learning/" agents/ --include="*.md"
```

- [ ] **Step 4: Commit cross-reference updates**

```bash
git add agents/
git commit -m "fix: update internal cross-references to use dual naming"
```

---

## Chunk 5: Documentation

### Task 19: Update README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update architecture section**

Replace existing agent list with layer-based organization showing dual naming.

- [ ] **Step 2: Add autonomy modes documentation**

Document the three modes with examples:
```bash
/speckit.cognitive-squad.run "Build an app"                  # semi (default)
/speckit.cognitive-squad.run "Build an app" --mode guided    # checkpoint after each phase
/speckit.cognitive-squad.run "Build an app" --mode banzai    # full autonomous
```

- [ ] **Step 3: Add 4-phase diagram**

Include the phase flow diagram from the design spec.

- [ ] **Step 4: Commit README update**

```bash
git add README.md
git commit -m "docs: update README with layer architecture, dual naming, and autonomy modes"
```

---

### Task 20: Update extension.yml version

**Files:**
- Modify: `extension.yml`

- [ ] **Step 1: Bump version to 0.2.0**

Change:

```yaml
version: "0.1.0"
```

To:

```yaml
version: "0.2.0"
```

- [ ] **Step 2: Update description**

```yaml
description: "Multi-agent cognitive system with 4-phase architecture, dual naming, and autonomy modes"
```

- [ ] **Step 3: Commit version bump**

```bash
git add extension.yml
git commit -m "chore: bump version to 0.2.0"
```

---

## Chunk 6: Verification

### Task 21: Verify all files exist

- [ ] **Step 1: Run verification script**

```bash
cd /Users/michalbachorik/work/cognitive-squad

# Check all expected agent files exist
for f in \
  agents/control/commander.md \
  agents/control/tracker.md \
  agents/control/scorekeeper.md \
  agents/exploration/scout.md \
  agents/exploration/cartographer.md \
  agents/exploration/sage.md \
  agents/exploration/modeler.md \
  agents/feasibility/gatekeeper.md \
  agents/feasibility/validator.md \
  agents/solution/architect.md \
  agents/solution/orchestrator.md \
  agents/solution/sentinel.md \
  agents/specialists/investigator.md \
  agents/specialists/guardian.md \
  agents/specialists/benchmark.md \
  agents/specialists/advocate.md \
  agents/specialists/oracle.md \
  agents/specialists/maverick.md \
  agents/learning/auditor.md \
  agents/learning/adaptive.md \
  agents/learning/realist.md \
  agents/learning/mirror.md \
  agents/learning/monitor.md; do
  if [ ! -f "$f" ]; then echo "MISSING: $f"; fi
done

echo "Verification complete"
```

Expected: No "MISSING" output

- [ ] **Step 2: Verify dual naming in headers**

```bash
grep -rl "(codename:" agents/ --include="*.md" | wc -l
```

Expected: 23 (the exact number of renamed agents in the verification list above)

- [ ] **Step 3: Verify old paths don't exist**

```bash
ls agents/core/ 2>/dev/null && echo "ERROR: agents/core/ still exists" || echo "OK: agents/core/ removed"
```

Expected: "OK: agents/core/ removed"

---

### Task 22: Create version tag

- [ ] **Step 1: Create annotated tag**

```bash
git tag -a v0.2.0 -m "v0.2.0: Layer architecture, dual naming, autonomy modes

- Reorganized agents into layers: control, exploration, feasibility, solution, specialists, learning
- Added dual naming (functional + codename) to all agents
- Implemented 4-phase model (Understand → Decide → Solution → Document)
- Added autonomy modes: guided, semi, banzai
- Updated state schema with phase tracking"
```

- [ ] **Step 2: Verify tag**

```bash
git tag -l "v0.2*"
```

Expected: v0.2.0

---

## Summary

**Total Tasks:** 23 (including Task 18b)
**Total Steps:** ~85
**Estimated Time:** 5-7 hours

**Key Deliverables:**
1. Layer-based directory structure
2. Dual naming on all agents
3. 4-phase execution model in cognitive-squad.run.md
4. Autonomy modes (guided, semi, banzai)
5. Updated config and state schema
6. Updated README documentation
7. Version 0.2.0 release
