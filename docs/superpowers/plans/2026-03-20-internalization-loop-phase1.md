# Internalization Loop Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the KB files, agent prompt updates, config, and validation script that enable the cognitive squad's learning loop to close — connecting internalization doubts to downstream rework outcomes and producing evidence-backed prompt recommendations.

**Architecture:** Three new append-only KB files (`prompt-versions.yaml`, `evolution-signals.yaml`, `internalization-log.yaml`) feed data into AUDITOR (which structures, correlates, and backfills) and ADAPTIVE (which cross-references and recommends). A validation script enforces data integrity. Config knobs control signal sensitivity.

**Tech Stack:** YAML (KB files), Markdown (agent prompts), Bash (validation script)

**Spec:** `docs/superpowers/specs/2026-03-20-internalization-loop-phase1-design.md`

---

### Task 1: Add schemas to kb-schema.md

**Files:**
- Modify: `knowledge-base/kb-schema.md`

- [ ] **Step 1: Update scope list**

Add the 3 new files to the scope list at the top of `kb-schema.md` (lines 7-11):

```markdown
6. `prompt-versions.yaml`
7. `evolution-signals.yaml`
8. `internalization-log.yaml`
```

- [ ] **Step 2: Add prompt-versions.yaml schema**

Append after the `agent-scores.yaml` section (after line 194). Follow exact format pattern from existing schemas:

```markdown
## prompt-versions.yaml

Required top-level keys:

1. `schema_version` (integer, required)
2. `agents` (map, required)

`agents.<agent_name>` required keys:

1. `current_version` (string, mutable)
2. `versions` (array, append-only)

`agents.<agent_name>.versions[]` required keys:

1. `version` (string)
2. `date` (string date)
3. `author` (string)
4. `source` (string)
5. `created_at` (string date-time)
6. `changes` (string)
7. `active_at_runs` (array of strings, AUDITOR appends run_id at end-of-run)

Minimum-valid example:

```yaml
schema_version: 1
agents:
 ARCHITECT:
  current_version: "1.0"
  versions:
   - version: "1.0"
     date: "2026-03-20"
     author: "human"
     source: "v0.3.0-release"
     created_at: "2026-03-20T00:00:00Z"
     changes: "Initial version (v0.3.0 release)"
     active_at_runs: []
```
```

- [ ] **Step 3: Add evolution-signals.yaml schema**

Append after prompt-versions section:

```markdown
## evolution-signals.yaml

Required top-level keys:

1. `schema_version` (integer, required)
2. `append_only` (boolean, required and must be `true`)
3. `signals` (array, required)

`signals[]` required keys:

1. `id` (string, pattern: `evo-sig-NNN`)
2. `created_at` (string date-time)
3. `run_id` (string)
4. `source` (string)
5. `domain` (string)
6. `trigger` (enum: `regression_detected` | `declining_trend` | `recurring_pitfall` | `recurring_rejection`)
7. `severity` (enum: `CRITICAL` | `HIGH` | `MEDIUM` | `LOW`)
8. `affected_agents` (array of strings)
9. `metrics` (object)
10. `failure_analysis` (object)
11. `status` (enum: `open` | `acknowledged` | `proposal_created` | `resolved` | `wont_fix`)

`metrics` required keys:

1. `accuracy` (number between 0 and 1)
2. `best_known` (number between 0 and 1)
3. `regression_delta` (number)
4. `sample_size` (integer)
5. `trend` (enum: `stable` | `improving` | `declining`)

`failure_analysis` required keys:

1. `pattern` (string)
2. `occurrences` (integer)
3. `root_cause` (string)
4. `suggested_fix` (string)

Minimum-valid example:

```yaml
schema_version: 1
append_only: true
signals:
 - id: evo-sig-001
   created_at: 2026-03-20T14:30:00Z
   run_id: squad-001-1742401234
   source: AUDITOR
   domain: infrastructure
   trigger: regression_detected
   severity: HIGH
   affected_agents: [ARCHITECT]
   metrics:
    accuracy: 0.42
    best_known: 0.52
    regression_delta: 0.10
    sample_size: 8
    trend: declining
   failure_analysis:
    pattern: "Missing database scaling considerations"
    occurrences: 5
    root_cause: "Agent prompt lacks scaling checklist"
    suggested_fix: "Add database scaling checklist section"
   status: open
```
```

- [ ] **Step 4: Add internalization-log.yaml schema**

Append after evolution-signals section:

```markdown
## internalization-log.yaml

Required top-level keys:

1. `schema_version` (integer, required)
2. `append_only` (boolean, required and must be `true`)
3. `entries` (array, required)

`entries[]` required keys:

1. `id` (string, pattern: `int-NNN`)
2. `run_id` (string)
3. `created_at` (string date-time)
4. `source` (string)
5. `agent` (string)
6. `prompt_version` (string)
7. `score` (integer between 0 and 6)
8. `result` (enum: `PASS` | `PARTIAL` | `FAIL`)
9. `doubts_count` (integer)
10. `doubts_resolved` (integer)
11. `doubts_escalated` (integer)
12. `doubt_categories` (array, values from: `role` | `constraints` | `architecture` | `domain` | `tasks` | `doubts`)
13. `resolution_types` (array, values from: `artifact_read` | `clarification` | `escalation` | `deferred`)
14. `downstream_outcome` (enum or null: `passed` | `rework_spec` | `rework_code` | `rework_test` | null)
15. `downstream_agent` (string or null)

Minimum-valid example:

```yaml
schema_version: 1
append_only: true
entries:
 - id: int-001
   run_id: squad-001-1742401234
   created_at: 2026-03-20T14:30:00Z
   source: AUDITOR
   agent: ARCHITECT
   prompt_version: "1.0"
   score: 4
   result: PARTIAL
   doubts_count: 3
   doubts_resolved: 2
   doubts_escalated: 1
   doubt_categories: [architecture, domain]
   resolution_types: [artifact_read, clarification]
   downstream_outcome: null
   downstream_agent: null
```
```

- [ ] **Step 5: Commit**

```bash
git add knowledge-base/kb-schema.md
git commit -m "docs: add schemas for prompt-versions, evolution-signals, internalization-log KB files"
```

---

### Task 2: Create prompt-versions.yaml seeded with all 35 agents

**Files:**
- Create: `knowledge-base/prompt-versions.yaml`

- [ ] **Step 1: Create the file with all 35 agents at v1.0**

Every agent from `agents.yaml` gets an entry. All start at version "1.0" with `author: "human"` and `source: "v0.3.0-release"`. The `active_at_runs` array starts empty.

Agent list (7 layers, 35 agents):
- Control: COMMANDER, SCOREKEEPER, TRACKER, CHECKPOINT, STRATEGIST
- Exploration: SCOUT, SYNTHESIZER, SAGE, CARTOGRAPHER, MODELER
- Feasibility: GATEKEEPER, VALIDATOR
- Solution: ARCHITECT, ORCHESTRATOR, SENTINEL
- Specialists: INVESTIGATOR, GUARDIAN, ORACLE, BENCHMARK, ADVOCATE, MAVERICK
- Build: IMPLEMENTER, SPEC_GUARD, CODE_REVIEWER, TEST_GUARDIAN, DEBUGGER, INTEGRATOR, PROGRESS_TRACKER, CHANGE_CONTROLLER
- Learning: MIRROR, ADAPTIVE, AUDITOR, REALIST, VETERAN, MONITOR

```yaml
schema_version: 1
agents:
  COMMANDER:
    current_version: "1.0"
    versions:
      - version: "1.0"
        date: "2026-03-20"
        author: "human"
        source: "v0.3.0-release"
        created_at: "2026-03-20T00:00:00Z"
        changes: "Initial version (v0.3.0 release)"
        active_at_runs: []
```

Repeat this pattern for all 35 agents. Group by layer with YAML comments:

```yaml
  # --- Control Layer ---
  COMMANDER:
    ...
  SCOREKEEPER:
    ...
  # --- Exploration Layer ---
  SCOUT:
    ...
```

- [ ] **Step 2: Validate structure**

Check that the file parses correctly:

```bash
python3 -c "import yaml; d=yaml.safe_load(open('knowledge-base/prompt-versions.yaml')); print(f'{len(d[\"agents\"])} agents loaded')"
```

Expected: `35 agents loaded`

- [ ] **Step 3: Commit**

```bash
git add knowledge-base/prompt-versions.yaml
git commit -m "feat: seed prompt-versions.yaml with all 35 agents at v1.0"
```

---

### Task 3: Create empty evolution-signals.yaml and internalization-log.yaml

**Files:**
- Create: `knowledge-base/evolution-signals.yaml`
- Create: `knowledge-base/internalization-log.yaml`

- [ ] **Step 1: Create evolution-signals.yaml**

```yaml
schema_version: 1
append_only: true
signals: []
```

- [ ] **Step 2: Create internalization-log.yaml**

```yaml
schema_version: 1
append_only: true
entries: []
```

- [ ] **Step 3: Validate both files parse**

```bash
python3 -c "import yaml; d=yaml.safe_load(open('knowledge-base/evolution-signals.yaml')); print(f'signals: {len(d[\"signals\"])}')"
python3 -c "import yaml; d=yaml.safe_load(open('knowledge-base/internalization-log.yaml')); print(f'entries: {len(d[\"entries\"])}')"
```

Expected: `signals: 0` and `entries: 0`

- [ ] **Step 4: Commit**

```bash
git add knowledge-base/evolution-signals.yaml knowledge-base/internalization-log.yaml
git commit -m "feat: create empty evolution-signals and internalization-log KB files"
```

---

### Task 4: Add evolution config section to config-template.yml

**Files:**
- Modify: `config-template.yml`

- [ ] **Step 1: Add evolution section after internalization section**

Insert after line 312 (end of `internalization` section), before the `code_quality` section. Follow exact comment and indentation style from surrounding sections:

```yaml
# =============================================================================
# EVOLUTION (AUDITOR + ADAPTIVE)
# =============================================================================

evolution:
  # Master switch for the evolution learning loop
  # [disable: false] Disables evolution signals and recommendations
  enabled: true

  signals:
    # Trigger evolution signal when accuracy drops this much from best-known value
    # [range: 0.05-0.2] Lower = more sensitive, higher = fewer false alarms
    regression_delta: 0.1

    # Minimum runs before any evolution signal can fire
    # [range: 3-10] Prevents premature signals from limited run history
    min_sample_size: 5

    # Consecutive declining runs before declining_trend signal fires
    # [range: 2-5]
    declining_trend_runs: 3

    # Same pitfall triggered N times before recurring_pitfall signal fires
    # [range: 2-5]
    recurring_pitfall_count: 3

    # Same agent rejected N times for same reason before recurring_rejection signal fires
    # [range: 2-5]
    recurring_rejection_count: 3

  recommendations:
    # Minimum correlated data points for ADAPTIVE to produce a recommendation
    # [range: 2-5] 3 = HIGH confidence (recommended), 2 = MEDIUM, 1 = LOW (noisy)
    min_confidence: 3

    # Require downstream outcome evidence (doubt->rework chain) for recommendations
    # [disable: false] Allows recommendations based on accuracy alone (less reliable)
    require_downstream_evidence: true
```

- [ ] **Step 2: Commit**

```bash
git add config-template.yml
git commit -m "feat: add evolution config section for signal thresholds and recommendations"
```

---

### Task 5: Update AUDITOR prompt with 5 new responsibilities

**Files:**
- Modify: `agents/learning/auditor.md`

This is the most important task. AUDITOR gets 5 new responsibilities added as a new Mode 3 section.

- [ ] **Step 0: Update Configuration section**

In `agents/learning/auditor.md`, update the Configuration section (lines 15-18) to add the new config keys:

```markdown
## Configuration

This agent uses values from `squad-config.yml`:

- `calibration.*` - Accuracy thresholds and correction factors
- `risk.*` - Risk level thresholds
- `evolution.*` - Evolution signal thresholds and recommendation settings
- `internalization.*` - Score/result thresholds for internalization-log entries
```

- [ ] **Step 1: Add new inputs**

Add to the Inputs section (after line 34):

```markdown
- `knowledge-base/prompt-versions.yaml` (prompt version registry)
- `knowledge-base/evolution-signals.yaml` (prior evolution signals)
- `knowledge-base/internalization-log.yaml` (prior internalization entries)
- CHECKPOINT's `internalization-report.md` (current run internalization results)
- Verdict reports from SPEC_GUARD, CODE_REVIEWER, TEST_GUARDIAN (PASS/FAIL/WARN outcomes)
```

- [ ] **Step 2: Extend Tier 1 KB Bootstrap Protocol scope**

Update the protocol scope statement (line 51) to include the new files:

```markdown
This protocol applies to `calibration-profile.yaml`, `estimates-log.yaml`, `patterns.yaml`, `pitfalls.yaml`, `prompt-versions.yaml`, `evolution-signals.yaml`, and `internalization-log.yaml`. All KB writes must go through `kb-write.sh`; direct file mutation is prohibited.
```

- [ ] **Step 3: Add Mode 3 after Mode 2**

Insert after Step 4 of Mode 2 (after line 131, before the `---` on line 132). Follow the exact heading and step format:

```markdown
### Mode 3: Evolution Loop (during FINALIZE, after Mode 1)

Only execute if `evolution.enabled` is `true` in `squad-config.yml`.

#### Step 1: Structure Internalization Results

Read CHECKPOINT's `internalization-report.md` from the current run. For each agent listed:

- Look up the agent's active prompt version from `knowledge-base/prompt-versions.yaml` (`agents.<name>.current_version`)
- Create an internalization-log entry with:
  - `id`: next sequential `int-NNN` in `internalization-log.yaml`
  - `run_id`: current run ID
  - `source`: "AUDITOR"
  - `agent`: agent codename
  - `prompt_version`: the active version from prompt-versions.yaml
  - `score`: the numeric score (0-6) from CHECKPOINT's report
  - `result`: PASS/PARTIAL/FAIL based on config thresholds (`internalization.pass_threshold`, `internalization.partial_min`, `internalization.fail_below`)
  - `doubts_count`, `doubts_resolved`, `doubts_escalated`: from CHECKPOINT's report
  - `doubt_categories`: map each doubt to one of: `role`, `constraints`, `architecture`, `domain`, `tasks`, `doubts`
  - `resolution_types`: map each resolution to one of: `artifact_read`, `clarification`, `escalation`, `deferred`
  - `downstream_outcome`: null (backfilled in Step 4)
  - `downstream_agent`: null (backfilled in Step 4)
- Append entry to `internalization-log.yaml` via `kb-write.sh append_entry`

#### Step 2: Update active_at_runs

For each agent that participated in this run, append the current `run_id` to that agent's active version's `active_at_runs` array in `knowledge-base/prompt-versions.yaml`.

#### Step 3: Check Evolution Signal Triggers

For each domain in `calibration-profile.yaml`, check against `evolution.signals.*` config:

1. **Regression**: Is `accuracy` lower than `best_known - evolution.signals.regression_delta`? (Compute `best_known` as the highest accuracy ever recorded for this domain across all runs in `calibration-profile.yaml`.)
2. **Declining trend**: Has accuracy declined for `evolution.signals.declining_trend_runs` consecutive runs?
3. **Recurring pitfall**: Has the same pitfall ID in `pitfalls.yaml` been triggered `evolution.signals.recurring_pitfall_count` or more times?
4. **Recurring rejection**: Has the same agent received FAIL verdicts from the same reviewer (SPEC_GUARD/CODE_REVIEWER/TEST_GUARDIAN) for the same reason `evolution.signals.recurring_rejection_count` or more times? Read verdict reports to determine this.

Only fire signals if `sample_size >= evolution.signals.min_sample_size`.

For each triggered condition, append a signal to `evolution-signals.yaml` via `kb-write.sh append_entry` with:
- `id`: next sequential `evo-sig-NNN`
- `trigger`: one of `regression_detected`, `declining_trend`, `recurring_pitfall`, `recurring_rejection`
- `severity`: CRITICAL if regression_delta > 0.2, HIGH if > 0.1, MEDIUM if > 0.05, LOW otherwise
- `metrics`: current accuracy, best_known, regression_delta, sample_size, trend
- `failure_analysis`: describe the pattern, count occurrences, identify root cause in agent prompt, suggest fix
- `status`: "open"

#### Step 4: Backfill Downstream Outcomes

Read verdict reports from SPEC_GUARD, CODE_REVIEWER, and TEST_GUARDIAN for the current run. For each internalization-log entry written in Step 1:

- Find the matching agent's build task verdict
- If all verdicts are PASS: set `downstream_outcome: "passed"`
- If SPEC_GUARD verdict is FAIL: set `downstream_outcome: "rework_spec"`, `downstream_agent: "SPEC_GUARD"`
- If CODE_REVIEWER verdict is FAIL: set `downstream_outcome: "rework_code"`, `downstream_agent: "CODE_REVIEWER"`
- If TEST_GUARDIAN verdict is FAIL: set `downstream_outcome: "rework_test"`, `downstream_agent: "TEST_GUARDIAN"`
- If multiple verdicts are FAIL, use the first in the review chain order (SPEC_GUARD > CODE_REVIEWER > TEST_GUARDIAN)

Update the entries in `internalization-log.yaml` via `kb-write.sh`.

Note: AUDITOR runs at end-of-run (during FINALIZE, after build phase completes), so all verdict reports are available at this point.

#### Step 5: Correlate Accuracy to Prompt Version

When writing accuracy updates to `calibration-profile.yaml` (Mode 1, Step 3), include in the reasoning journal which prompt version was active for each agent in that domain. This enables future analysis of whether accuracy changes correlate with prompt version changes.
```

- [ ] **Step 4: Add new outputs to Output section**

Add after the existing output entries (after line 153):

```markdown
- **`knowledge-base/evolution-signals.yaml`** — evolution signals when regression thresholds met (Mode 3)
- **`knowledge-base/internalization-log.yaml`** — structured internalization entries per agent per run (Mode 3)
- **`knowledge-base/prompt-versions.yaml`** — updated `active_at_runs` per agent (Mode 3)
```

- [ ] **Step 5: Commit**

```bash
git add agents/learning/auditor.md
git commit -m "feat: add Mode 3 (Evolution Loop) to AUDITOR — signals, internalization log, downstream backfill"
```

---

### Task 6: Update ADAPTIVE prompt with recommender capability

**Files:**
- Modify: `agents/learning/adaptive.md`

- [ ] **Step 1: Add new inputs**

Add to the Inputs section (after line 28):

```markdown
- `knowledge-base/evolution-signals.yaml` (evolution signals from AUDITOR)
- `knowledge-base/internalization-log.yaml` (internalization results with downstream outcomes)
- `squad-config.yml` — `evolution.recommendations.*` settings
```

- [ ] **Step 2: Add Step 6 after Confirmation Bias Check**

Insert after Step 5 (line 81), before the `---` on line 83:

```markdown
#### Step 6: Prompt Recommendations (requires evolution.enabled = true)

Cross-reference evolution signals with internalization data to produce evidence-backed prompt change recommendations.

1. Read `knowledge-base/evolution-signals.yaml` — filter for `status: "open"`
2. For each open signal, read `knowledge-base/internalization-log.yaml` entries for the `affected_agents`
3. Check: do internalization doubts in the same category correlate with `downstream_outcome` rework?
   - Example: ARCHITECT has 3 entries with `doubt_categories` containing "domain" AND `downstream_outcome: "rework_spec"` — this is a correlation
4. Read `evolution.recommendations.min_confidence` from config — only produce recommendation if correlated data points >= this threshold
5. Read `evolution.recommendations.require_downstream_evidence` from config — if true, skip recommendations where `downstream_outcome` is null for all entries

For each recommendation that passes the confidence gate, produce a block in `prompt-recommendations.md`:

```markdown
## Prompt Recommendation: REC-NNN
Agent: {agent codename}
Domain: {domain from evolution signal}
Evidence:
- accuracy regression: {best_known} → {current} over {N} runs
- internalization doubts: {N}/{total} runs had "{category}" doubts about {topic}
- downstream: {N}/{total} runs had {outcome} triggered by {agent}
Correlation: {category} doubts → {outcome} ({percentage}% rate)
Recommended change: {specific change to agent prompt, referencing section name}
Confidence: {HIGH|MEDIUM|LOW} ({N} correlated data points)
```

If no recommendations pass the confidence gate, do not produce the file.
```

- [ ] **Step 3: Add new output to Output section**

Add after `bias-check.md` entry (after line 93):

```markdown
- **`prompt-recommendations.md`** — Only produced if evidence-backed recommendations exist. Contains specific, actionable prompt change suggestions with evidence chain.
```

- [ ] **Step 4: Update Reasoning Journal section**

Add to the flags list (line 119):

```markdown
- `flags`: list of flags raised (STAGNATION, REGRESSION, CONFIRMATION_BIAS, STALE_PATTERN, PROMPT_RECOMMENDATION)
- `recommendations_count`: number of prompt recommendations produced (0 if none)
```

- [ ] **Step 5: Commit**

```bash
git add agents/learning/adaptive.md
git commit -m "feat: add Step 6 (Prompt Recommendations) to ADAPTIVE — evidence-backed prompt change suggestions"
```

---

### Task 7: Create kb-validate-evolution.sh

**Files:**
- Create: `scripts/bash/kb-validate-evolution.sh`

- [ ] **Step 1: Write the validation script**

Follow the pattern from `kb-write.sh` (error-exit bash, usage function, structured output):

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../.." && pwd)"
KB_DIR="$REPO_ROOT/knowledge-base"

ERRORS=0
WARNINGS=0

usage() {
  cat >&2 <<'USAGE'
usage:
  kb-validate-evolution.sh [--state path/to/state.json]

Validates evolution KB files:
  Check 1: Cross-file referential integrity (prompt-versions ↔ internalization-log ↔ agents.yaml)
  Check 2: Score/result consistency in internalization-log (reads thresholds from squad-config.yml)
  Check 3: Downstream outcome completeness (requires --state to check build phase)

Exit codes:
  0 = all checks pass
  1 = one or more checks failed
USAGE
  exit 1
}

STATE_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --state) STATE_FILE="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1" >&2; usage ;;
  esac
done

error() {
  local file="$1" line="$2" msg="$3"
  printf '%s:%s: ERROR: %s\n' "$file" "$line" "$msg"
  ERRORS=$((ERRORS + 1))
}

warn() {
  local file="$1" line="$2" msg="$3"
  printf '%s:%s: WARN: %s\n' "$file" "$line" "$msg"
  WARNINGS=$((WARNINGS + 1))
}

# ---- Load agent names from agents.yaml ----
AGENTS_FILE="$REPO_ROOT/agents.yaml"
if [[ ! -f "$AGENTS_FILE" ]]; then
  echo "FATAL: agents.yaml not found at $AGENTS_FILE" >&2
  exit 1
fi
AGENT_NAMES=$(python3 -c "
import yaml, sys
with open('$AGENTS_FILE') as f:
    data = yaml.safe_load(f)
names = set(data.get('agents', {}).keys())
print('\n'.join(sorted(names)))
")

# ---- Check 1: Cross-file referential integrity ----
echo "--- Check 1: Cross-file referential integrity ---"

INT_LOG="$KB_DIR/internalization-log.yaml"
PROMPT_VERS="$KB_DIR/prompt-versions.yaml"
EVO_SIGS="$KB_DIR/evolution-signals.yaml"

if [[ -f "$INT_LOG" && -f "$PROMPT_VERS" ]]; then
  python3 - "$INT_LOG" "$PROMPT_VERS" "$EVO_SIGS" "$AGENT_NAMES" <<'PY'
import yaml, sys

int_log_path, prompt_vers_path, evo_sigs_path = sys.argv[1], sys.argv[2], sys.argv[3]
agent_names = set(sys.argv[4].split('\n')) if sys.argv[4] else set()

with open(int_log_path) as f:
    int_log = yaml.safe_load(f)
with open(prompt_vers_path) as f:
    prompt_vers = yaml.safe_load(f)

errors = 0
for i, entry in enumerate(int_log.get('entries', [])):
    agent = entry.get('agent', '')
    if agent not in agent_names:
        print(f"{int_log_path}:{i+1}: ERROR: agent '{agent}' not in agents.yaml")
        errors += 1
    pv_agent = prompt_vers.get('agents', {}).get(agent, {})
    pv_version = entry.get('prompt_version', '')
    pv_versions = [v.get('version') for v in pv_agent.get('versions', [])]
    if pv_version and pv_version not in pv_versions:
        print(f"{int_log_path}:{i+1}: ERROR: prompt_version '{pv_version}' not in prompt-versions.yaml for {agent}")
        errors += 1

if errors == 0:
    print("Check 1a (internalization-log): PASS")

# Check evolution-signals affected_agents
import os
if os.path.exists(evo_sigs_path):
    with open(evo_sigs_path) as f:
        evo_sigs = yaml.safe_load(f)
    evo_errors = 0
    for i, sig in enumerate(evo_sigs.get('signals', [])):
        for a in sig.get('affected_agents', []):
            if a not in agent_names:
                print(f"{evo_sigs_path}:{i+1}: ERROR: affected_agent '{a}' not in agents.yaml")
                evo_errors += 1
    if evo_errors == 0:
        print("Check 1b (evolution-signals): PASS")
    errors += evo_errors

sys.exit(1 if errors > 0 else 0)
PY
  CHECK1=$?
  [[ $CHECK1 -ne 0 ]] && ERRORS=$((ERRORS + 1))
else
  echo "Check 1: SKIP (files not yet created)"
fi

# ---- Check 2: Score/result consistency ----
echo "--- Check 2: Score/result consistency ---"

CONFIG_FILE="$REPO_ROOT/squad-config.yml"
if [[ ! -f "$CONFIG_FILE" ]]; then
  CONFIG_FILE="$REPO_ROOT/config-template.yml"
fi

if [[ -f "$INT_LOG" && -f "$CONFIG_FILE" ]]; then
  python3 - "$INT_LOG" "$CONFIG_FILE" <<'PY'
import yaml, sys

int_log_path, config_path = sys.argv[1], sys.argv[2]

with open(int_log_path) as f:
    int_log = yaml.safe_load(f)
with open(config_path) as f:
    config = yaml.safe_load(f)

intern = config.get('internalization', {})
pass_threshold = intern.get('pass_threshold', 6)
partial_min = intern.get('partial_min', 4)
fail_below = intern.get('fail_below', 4)

errors = 0
for i, entry in enumerate(int_log.get('entries', [])):
    score = entry.get('score', 0)
    result = entry.get('result', '')
    expected = 'PASS' if score >= pass_threshold else ('PARTIAL' if score >= partial_min else 'FAIL')
    if result != expected:
        print(f"{int_log_path}:{i+1}: ERROR: score {score} expects result '{expected}' but got '{result}'")
        errors += 1

if errors == 0:
    print("Check 2: PASS")
sys.exit(1 if errors > 0 else 0)
PY
  CHECK2=$?
  [[ $CHECK2 -ne 0 ]] && ERRORS=$((ERRORS + 1))
else
  echo "Check 2: SKIP (files not yet created)"
fi

# ---- Check 3: Downstream outcome completeness ----
echo "--- Check 3: Downstream outcome completeness ---"

if [[ -n "$STATE_FILE" && -f "$STATE_FILE" && -f "$INT_LOG" ]]; then
  python3 - "$INT_LOG" "$STATE_FILE" <<'PY'
import yaml, json, sys

int_log_path, state_path = sys.argv[1], sys.argv[2]

with open(int_log_path) as f:
    int_log = yaml.safe_load(f)
with open(state_path) as f:
    state = json.load(f)

phase = state.get('phase', '')
build_complete_phases = ['build_done', 'qa_in_progress', 'qa_failed', 'done']

warnings = 0
if phase in build_complete_phases or phase == 'done':
    run_id = state.get('run_id', '')
    for i, entry in enumerate(int_log.get('entries', [])):
        if entry.get('run_id') == run_id and entry.get('downstream_outcome') is None:
            print(f"{int_log_path}:{i+1}: WARN: downstream_outcome is null for {entry.get('agent')} in completed run {run_id}")
            warnings += 1

if warnings == 0:
    print("Check 3: PASS")
else:
    print(f"Check 3: {warnings} entries with missing downstream_outcome")
    sys.exit(1)
PY
  CHECK3=$?
  [[ $CHECK3 -ne 0 ]] && ERRORS=$((ERRORS + 1))
elif [[ -z "$STATE_FILE" ]]; then
  echo "Check 3: SKIP (no --state provided)"
else
  echo "Check 3: SKIP (state file or internalization-log not found)"
fi

# ---- Summary ----
echo "---"
if [[ $ERRORS -eq 0 ]]; then
  echo "All checks passed."
  exit 0
else
  echo "$ERRORS check(s) failed."
  exit 1
fi
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/bash/kb-validate-evolution.sh
```

- [ ] **Step 3: Test against empty KB files**

```bash
scripts/bash/kb-validate-evolution.sh
```

Expected output:
```
--- Check 1: Cross-file referential integrity ---
Check 1a (internalization-log): PASS
Check 1b (evolution-signals): PASS
--- Check 2: Score/result consistency ---
Check 2: PASS
--- Check 3: Downstream outcome completeness ---
Check 3: SKIP (no --state provided)
---
All checks passed.
```

- [ ] **Step 4: Commit**

```bash
git add scripts/bash/kb-validate-evolution.sh
git commit -m "feat: add kb-validate-evolution.sh — referential integrity, score consistency, downstream completeness"
```

---

### Task 8: Add validation call to COMMANDER's pre-dispatch sequence

**Files:**
- Modify: `commands/squad.run.md`

- [ ] **Step 1: Add KB evolution validation to preflight section**

In `commands/squad.run.md`, find the preflight section (around line 259-291 where `preflight-speckit.sh` is called). Add after the spec-kit dependency check:

```markdown
### Preflight: KB Evolution Validation

If `evolution.enabled` is `true` in `squad-config.yml`:

```bash
scripts/bash/kb-validate-evolution.sh --state .specify/squad/state.json
```

- Exit 0: Continue
- Exit 1: Log validation failures to `state.json.issues_log` with severity `MEDIUM`, continue execution (non-blocking — data quality issues should not prevent runs)
```

- [ ] **Step 2: Commit**

```bash
git add commands/squad.run.md
git commit -m "feat: add KB evolution validation to COMMANDER pre-dispatch sequence"
```

---

### Task 9: Final integration validation

**Files:** (read-only validation, no changes)

- [ ] **Step 1: Validate all KB files parse**

```bash
python3 -c "
import yaml
files = [
    'knowledge-base/prompt-versions.yaml',
    'knowledge-base/evolution-signals.yaml',
    'knowledge-base/internalization-log.yaml',
    'knowledge-base/calibration-profile.yaml',
    'knowledge-base/estimates-log.yaml',
    'knowledge-base/patterns.yaml',
    'knowledge-base/pitfalls.yaml',
    'knowledge-base/agent-scores.yaml',
]
for f in files:
    try:
        yaml.safe_load(open(f))
        print(f'OK: {f}')
    except Exception as e:
        print(f'FAIL: {f}: {e}')
"
```

Expected: All OK

- [ ] **Step 2: Run validation script**

```bash
scripts/bash/kb-validate-evolution.sh
```

Expected: All checks passed.

- [ ] **Step 3: Verify agent prompts reference correct files**

```bash
grep -l "evolution-signals.yaml" agents/learning/auditor.md agents/learning/adaptive.md
grep -l "internalization-log.yaml" agents/learning/auditor.md agents/learning/adaptive.md
grep -l "prompt-versions.yaml" agents/learning/auditor.md agents/learning/adaptive.md
grep -l "evolution\." agents/learning/auditor.md agents/learning/adaptive.md config-template.yml
```

Expected: All files found in both agent prompts and config.

- [ ] **Step 4: Verify config section exists**

```bash
grep -A2 "^evolution:" config-template.yml
```

Expected: Shows `evolution:` with `enabled: true` and nested sections.

- [ ] **Step 5: Final commit with tag**

```bash
git status  # verify only expected files changed
git tag v0.4.0-phase1
```

Note: All files should already be committed in Tasks 1-8. This step only tags. If any files are uncommitted, stage them explicitly by name (do not use `git add -A`).
