# Internalization Loop Phase 1: Foundation

## Summary

Phase 1 adds the infrastructure for the cognitive squad's learning loop to close. Today, AUDITOR tracks accuracy, CHECKPOINT captures doubts, and ADAPTIVE detects stagnation — but nothing connects doubts to outcomes or produces actionable prompt improvement recommendations. This phase adds three KB files, updates two agent prompts (AUDITOR and ADAPTIVE — CHECKPOINT's existing output is consumed, not modified), extends config, and adds a validation script.

**Two things make the system better now:**
1. AUDITOR backfills downstream outcomes — closing the doubt→rework loop
2. ADAPTIVE produces evidence-backed prompt change recommendations

**Four things enable Phase 2 (automated evolution):**
1. `prompt-versions.yaml` — version registry for future canary deployment
2. `evolution-signals.yaml` — structured signal log for future EVOLVE agent
3. Config evolution section — tuning knobs for signal sensitivity
4. Validation script — data integrity for the pipeline

---

## Decision Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Prompt versioning strategy | Registry file (`prompt-versions.yaml`), not directory restructure | Least disruptive, no broken file references |
| Evolution signal location | Separate `evolution-signals.yaml`, not inline in calibration-profile | Clean separation of concerns, calibration stays simple |
| Internalization history | New `internalization-log.yaml`, not extension of agent-scores | Different concern — comprehension vs performance/gamification |
| Phase 1 scope | Schema + agent prompts + config (full infrastructure) | Agents start producing data on next run |
| Signal trigger | Relative regression (`regression_delta`), not absolute threshold | All domains currently below 0.7 — absolute threshold would fire on everything |
| Internalization-log writer | AUDITOR (not CHECKPOINT) | CHECKPOINT is control-layer, lacks KB write protocol. AUDITOR reads CHECKPOINT's internalization-report.md and structures it into the log at end-of-run |
| Rework detection source | Verdict reports (not reasoning journal) | SPEC_GUARD/CODE_REVIEWER/TEST_GUARDIAN produce verdict files, not structured journal entries. AUDITOR reads these directly |

---

## New KB Files

### 1. `knowledge-base/prompt-versions.yaml`

Registry of prompt version history per agent. Enables accuracy-to-version correlation.

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
  # ... one entry per agent, all starting at v1.0
```

**Fields:**
- `current_version` — mutable, points to the active version
- `versions[]` — append-only list of version entries
  - `version` — semver string
  - `date` — ISO-8601
  - `author` — "human" or agent codename (future: "EVOLVE")
  - `source` — provenance identifier (required by KB global rules)
  - `created_at` — ISO-8601 timestamp (required by KB global rules)
  - `changes` — description of what changed
  - `active_at_runs` — list of run IDs where this version was active. **AUDITOR appends the current run_id at end-of-run.**

**Seeding:** All 35 agents seeded at v1.0 from current prompts on first use.

### 2. `knowledge-base/evolution-signals.yaml`

Append-only log of signals fired when regression is detected.

```yaml
schema_version: 1
append_only: true
signals:
  - id: "evo-sig-001"
    created_at: "2026-03-20T14:30:00Z"
    run_id: "squad-001-1710901200"
    source: "AUDITOR"
    domain: "infrastructure"
    trigger: "regression_detected"
    severity: "HIGH"
    affected_agents: ["ARCHITECT"]
    metrics:
      accuracy: 0.42
      best_known: 0.52
      regression_delta: 0.10
      sample_size: 8
      trend: "declining"
    failure_analysis:
      pattern: "Missing database scaling considerations"
      occurrences: 5
      root_cause: "Agent prompt lacks scaling checklist"
      suggested_fix: "Add database scaling checklist section"
    status: "open"
```

**Fields:**
- `id` — unique signal identifier (`evo-sig-NNN`)
- `trigger` — enum: `regression_detected`, `declining_trend`, `recurring_pitfall`, `recurring_rejection`
- `severity` — enum: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`
- `affected_agents` — list of agent codenames
- `metrics` — accuracy snapshot including `best_known` for relative comparison
- `failure_analysis` — pattern, occurrences, root cause, suggested fix
- `status` — lifecycle: `open` → `acknowledged` → `proposal_created` → `resolved` | `wont_fix`

### 3. `knowledge-base/internalization-log.yaml`

Append-only log of internalization results per agent per run. The `downstream_outcome` fields are what close the feedback loop.

```yaml
schema_version: 1
append_only: true
entries:
  - id: "int-001"
    run_id: "squad-001-1710901200"
    created_at: "2026-03-20T14:30:00Z"
    source: "AUDITOR"
    agent: "ARCHITECT"
    prompt_version: "1.0"
    score: 4
    result: "PARTIAL"
    doubts_count: 3
    doubts_resolved: 2
    doubts_escalated: 1
    doubt_categories: ["architecture", "domain"]
    resolution_types: ["artifact_read", "clarification"]
    downstream_outcome: "rework_spec"
    downstream_agent: "SPEC_GUARD"
```

**Fields:**
- `score` — 0-6 (maps to 6 internalization questions)
- `result` — `PASS` (6), `PARTIAL` (4-5), `FAIL` (<4)
- `doubts_count/resolved/escalated` — doubt metrics
- `doubt_categories` — from CHECKPOINT's 6 internalization dimensions: `role`, `constraints`, `architecture`, `domain`, `tasks`, `doubts`
- `resolution_types` — how doubts were resolved: `artifact_read`, `clarification`, `escalation`, `deferred`
- `downstream_outcome` — **backfilled by AUDITOR post-build**: `passed`, `rework_spec`, `rework_code`, `rework_test`, or `null` if not yet backfilled
- `downstream_agent` — which agent triggered the rework, or `null`

---

## Agent Prompt Updates

### AUDITOR (CALIBRATE) — 5 new responsibilities

AUDITOR already has KB write infrastructure (Tier 1 Bootstrap Protocol, lock acquisition, `kb-write.sh`). All new writes go through the existing protocol.

**1. Write evolution signals on regression detection**

After computing accuracy per domain, check against config thresholds:
- Accuracy dropped by `evolution.signals.regression_delta` from best-known value
- Accuracy declined for `evolution.signals.declining_trend_runs` consecutive runs
- Same pitfall triggered `evolution.signals.recurring_pitfall_count` times (cross-reference `pitfalls.yaml`)
- Same agent rejected `evolution.signals.recurring_rejection_count` times for same reason (cross-reference verdict reports from SPEC_GUARD, CODE_REVIEWER, TEST_GUARDIAN)

If any trigger fires and `evolution.signals.min_sample_size` is met, append to `evolution-signals.yaml`.

**2. Correlate accuracy to prompt version**

When computing domain accuracy, read `prompt-versions.yaml` to tag which version was active. Include version in accuracy reporting so future analysis can attribute accuracy changes to prompt changes.

**3. Update `active_at_runs` in prompt-versions.yaml**

At end-of-run, for each agent that participated, append the current `run_id` to that agent's active version's `active_at_runs` list in `prompt-versions.yaml`.

**4. Structure internalization results into log (replaces CHECKPOINT writing)**

CHECKPOINT is a control-layer agent without KB write protocol. Instead, AUDITOR reads CHECKPOINT's existing `internalization-report.md` output at end-of-run and structures it into `internalization-log.yaml` entries — one per agent. Reads `prompt-versions.yaml` to tag the active version. Leaves `downstream_outcome` and `downstream_agent` as `null` initially.

**5. Backfill downstream outcomes (the core value)**

After build phase completes, read verdict reports from SPEC_GUARD, CODE_REVIEWER, and TEST_GUARDIAN (these produce structured verdict files with PASS/FAIL/WARN outcomes). For each internalization-log entry in the current run:
- If the agent's build output passed all quality gates: set `downstream_outcome: "passed"`
- If SPEC_GUARD verdict is FAIL: set `downstream_outcome: "rework_spec"`, `downstream_agent: "SPEC_GUARD"`
- If CODE_REVIEWER verdict is FAIL: set `downstream_outcome: "rework_code"`, `downstream_agent: "CODE_REVIEWER"`
- If TEST_GUARDIAN verdict is FAIL: set `downstream_outcome: "rework_test"`, `downstream_agent: "TEST_GUARDIAN"`

This creates the doubt→outcome link that enables evidence-backed recommendations.

### CHECKPOINT (INTERNALIZE) — No changes

CHECKPOINT continues producing `internalization-report.md` as today. AUDITOR consumes this output and structures it into `internalization-log.yaml`. No KB write protocol needed for CHECKPOINT.

### ADAPTIVE (EVOLVE) — Upgraded from reporter to recommender

**Cross-reference and recommend**

1. Read `evolution-signals.yaml` and `internalization-log.yaml`
2. Cross-reference: for agents with evolution signals, check if internalization doubts in the same category correlate with downstream rework
3. When correlation found at HIGH confidence (3+ data points with clear causal chain), produce a prompt recommendation:

```markdown
## Prompt Recommendation: REC-001
Agent: ARCHITECT
Domain: infrastructure
Evidence:
- accuracy regression: 0.52 → 0.42 over 3 runs
- internalization doubts: 3/3 runs had "domain" doubts about scaling
- downstream: 2/3 runs had rework_spec triggered by SPEC_GUARD
Correlation: doubts about scaling → spec rework (67% rate)
Recommended change: Add scaling checklist to ARCHITECT prompt, section "Architecture Decisions"
Confidence: HIGH (3+ data points, clear causal chain)
```

4. Read `evolution.recommendations.min_confidence` from config as single source of truth for confidence threshold
5. Read `evolution.recommendations.require_downstream_evidence` — if true, only recommend when downstream outcome data exists

ADAPTIVE retains its existing outputs (`evolution-report.md`, `improvement-metrics.md`, `stagnation-flags.md`, `regression-alerts.md`, `bias-check.md`). The prompt recommendations are a **new additional output** written to `prompt-recommendations.md`. Existing stagnation detection is enriched with evidence, not replaced.

---

## Config Extension

New section added to `config-template.yml`:

```yaml
evolution:
  enabled: true

  signals:
    regression_delta: 0.1
    min_sample_size: 5
    declining_trend_runs: 3
    recurring_pitfall_count: 3
    recurring_rejection_count: 3

  recommendations:
    min_confidence: 3              # minimum correlated data points for recommendation (3=HIGH, 2=MEDIUM, 1=LOW)
    require_downstream_evidence: true
```

**Field justifications:**
- `enabled` — kill switch for the entire evolution system
- `regression_delta` — relative trigger, not absolute threshold (all domains currently below 0.7)
- `min_sample_size` — prevents premature signals from limited run history
- `declining_trend_runs` — consecutive declining runs before trigger
- `recurring_pitfall_count` / `recurring_rejection_count` — pattern detection thresholds
- `min_confidence` — numeric threshold (data points required), single source of truth for ADAPTIVE. Consistent with other numeric thresholds in config.
- `require_downstream_evidence` — forces doubt→rework chain, prevents guess-based recommendations

---

## Validation Script

`scripts/bash/kb-validate-evolution.sh` — 3 targeted checks that protect learning loop data quality.

### Check 1: Cross-file referential integrity

For every entry in `internalization-log.yaml`:
- `agent` exists in `agents.yaml`
- `prompt_version` matches a version entry in `prompt-versions.yaml` for that agent

For every entry in `evolution-signals.yaml`:
- `affected_agents` all exist in `agents.yaml`

Prevents AUDITOR from correlating accuracy to phantom versions or non-existent agents.

### Check 2: Score/result consistency

For every entry in `internalization-log.yaml`, read thresholds from `squad-config.yml` (`internalization.pass_threshold`, `internalization.partial_min`, `internalization.fail_below`) and validate that `score` and `result` agree. Do not hardcode thresholds.

Prevents contradictory trend analysis (scores improving but results declining).

### Check 3: Downstream outcome completeness

Takes `state.json` path as argument (e.g., `.specify/squad/state.json`). For runs where build phase is complete (`phase` is `done` or past build):
- Flag `internalization-log.yaml` entries with `downstream_outcome: null`

This catches silent backfill failures. The backfill is the most valuable part of the design — if it silently fails, the recommendation engine has no evidence.

### Integration

Runs standalone: `scripts/bash/kb-validate-evolution.sh [--state path/to/state.json]`. Called by COMMANDER before agent dispatch (not from `preflight-speckit.sh`, which is a dependency probe only). Exit 0 on pass, exit 1 on fail, structured output with `file:line:error` format.

---

## KB Schema Update

`knowledge-base/kb-schema.md` extended with schemas for all 3 new files, following existing documentation pattern (field names, types, constraints, examples).

---

## What This Does NOT Include (Phase 2+)

- EVOLVE agent generating automated proposals (Phase 2)
- Canary deployment of prompt versions (Phase 3)
- Automatic rollback on regression (Phase 3)
- VETERAN global evolution sharing (Phase 4)
- Prompt versioning with symlinked directories (deferred — registry approach chosen)

---

## Implementation Sequence

1. Define schemas for 3 new files in `kb-schema.md`
2. Create `prompt-versions.yaml` seeded with all 35 agents at v1.0
3. Create empty `evolution-signals.yaml` and `internalization-log.yaml`
4. Add evolution section to `config-template.yml`
5. Update AUDITOR prompt with 5 new responsibilities (signals, version correlation, active_at_runs, internalization-log structuring, downstream backfill)
6. Update ADAPTIVE prompt with recommender upgrade (new output: `prompt-recommendations.md`)
7. Create `kb-validate-evolution.sh` with 3 checks
8. Add validation call to COMMANDER's pre-dispatch sequence

---

## Success Criteria

After 5+ squad runs with this infrastructure:

1. `internalization-log.yaml` has entries with non-null `downstream_outcome` for completed builds
2. AUDITOR produces evolution signals when regression thresholds are met
3. ADAPTIVE produces at least one evidence-backed prompt recommendation
4. You (human) can read a recommendation and decide whether to edit a prompt based on evidence, not intuition
