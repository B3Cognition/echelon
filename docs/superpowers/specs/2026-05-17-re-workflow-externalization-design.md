# Design: Re-* Workflow Externalization

**Date:** 2026-05-17
**Status:** Approved — ready for implementation plan

## Problem

The 12 `re-*` brownfield extraction commands absorbed from the `revenge` extension are architecturally non-conformant with echelon's thin-wrapper + externalized-workflow pattern:

- All 12 commands are fat imperative scripts (170–1,037 lines; 5,404 lines total)
- None reference `workflow/definition.yaml` or emit `echelon_result:` blocks
- No `last_dispatch` sentinel → runs are not resumable after context compaction
- No phase nodes in `workflow/definition.yaml` → routing is invisible and unauditable
- Calls to these commands from GOLDDIGGER have no state machine participation

This design brings all 12 commands into full conformance with echelon's architecture.

---

## Architecture

### Three tiers

**Tier 1 — 3 top-level orchestrator commands** (thin wrappers, ~50 lines each):

| Command | Reads section | Entry phase |
|---|---|---|
| `commands/echelon.re-extract.md` | `re_extraction:` | `re-extract-0-preflight` |
| `commands/echelon.re-retarget.md` | `re_retarget:` | `re-retarget-0-preflight` |
| `commands/echelon.re-plan-all.md` | `re_planning:` | `re-planning-0-preflight` |

**Tier 2 — 9 single-phase standalone commands** (thin wrappers, ~50 lines each):

Each starts COMMANDER, executes exactly one named phase node from the relevant section of `workflow/definition.yaml`, writes result to `re/state.json`, then stops.

| Command | Phase node |
|---|---|
| `echelon.re-analyze` | `re-extract-1-analyze` |
| `echelon.re-specify` | `re-extract-2-specify` |
| `echelon.re-verify` | `re-extract-3-verify` |
| `echelon.re-expand` | `re-extract-4-expand` |
| `echelon.re-validate` | `re-extract-5-validate` |
| `echelon.re-checklist` | `re-extract-6-checklist` |
| `echelon.re-constitute` | `re-extract-7-constitute` |
| `echelon.re-plan` | `re-planning-1-plan` |
| `echelon.re-tasks` | `re-planning-2-tasks` |

**Tier 3 — New agent + phase files** (created during implementation):

- 9 agent files: `extension/agents/re/{analyzer,specifier,verifier,expander,validator,checklister,constituter,planner,tasker}.md`
- 13 phase files: `extension/workflow/phases/re-{extract,retarget,planning}-*.md`

### Content migration rule

| Content in fat command | Destination |
|---|---|
| Enforcement rules / NEVER blocks | agent file |
| Prerequisites checks | absorbed into `0-preflight` phase (commander_internal) |
| Step-by-step work instructions | agent file |
| "After this run X" cross-references | removed — encoded as `transitions:` in definition.yaml |
| Loop diagrams (verify/expand, validate) | removed — encoded as loop transitions in definition.yaml |
| Bash Command Guidelines directive | stays in agent file |

---

## workflow/definition.yaml additions

Three new top-level sections appended after `escalation:`. Each is a self-contained inner graph with its own `state_file`. Orchestrators read their full section; standalone sub-step commands jump directly to a named phase node and stop after one phase.

### `re_extraction:` phase graph

```
re-extract-0-preflight (commander_internal)
  → re-extract-1-analyze      [RE-ANALYZER]
  → re-extract-2-specify      [RE-SPECIFIER]
  → re-extract-3-verify       [RE-VERIFIER]
      coverage_pct < coverage_threshold → re-extract-4-expand
      coverage_pct >= coverage_threshold → re-extract-5-validate
  → re-extract-4-expand       [RE-EXPANDER]
      → re-extract-3-verify   (loop)
  → re-extract-5-validate     [RE-VALIDATOR]
      resolution_pct < threshold AND iterations < max → re-extract-5-validate (self-loop, deeper strategy)
      else → re-extract-6-checklist
  → re-extract-6-checklist    [RE-CHECKLISTER]
  → re-extract-7-constitute   [RE-CONSTITUTER]
  → DONE
```

Loop state fields written to `re/state.json` by agent `echelon_result:` blocks:
- `coverage_pct`, `coverage_threshold`, `verify_expand_iterations`
- `resolution_pct`, `resolution_threshold`, `validate_iterations`, `max_validate_iterations`

### `re_retarget:` phase graph

```
re-retarget-0-preflight (commander_internal)
  → re-retarget-1-input (commander_internal — interactive Q&A, COMMANDER prompts user directly)
  → DONE
```

### `re_planning:` phase graph

```
re-planning-0-preflight (commander_internal)
  → re-planning-1-plan    [RE-PLANNER]
  → re-planning-2-tasks   [RE-TASKER]
  → DONE
```

### Phase node schema (representative example)

```yaml
- id: re-extract-2-specify
  spec_file: workflow/phases/re-extract-2-specify.md
  type: agent
  agent: speckit-echelon-re-specifier
  tier: re_extraction
  context_pack:
    - .specify/echelon/re/analysis.json
    - .specify/echelon/re/state.json
  outputs:
    - specs/NNN-re-{domain}/spec.md
    - specs/000-re-overview/overview.md
  transitions:
    - to: re-extract-3-verify
      condition: verdict = DONE
```

Preflight phases are `type: commander_internal` (checks only, no agent dispatch).

---

## New files

### workflow/phases/ (13 files)

| File | Type | Source content |
|---|---|---|
| `re-extract-0-preflight.md` | commander_internal | New — checks jq, codebase non-empty, output dir writable, initialise re/state.json |
| `re-extract-1-analyze.md` | agent dispatch spec | Context/outputs from current re-analyze.md |
| `re-extract-2-specify.md` | agent dispatch spec | Context/outputs from current re-specify.md |
| `re-extract-3-verify.md` | agent dispatch spec | Context/outputs from current re-verify.md |
| `re-extract-4-expand.md` | agent dispatch spec | Context/outputs from current re-expand.md |
| `re-extract-5-validate.md` | agent dispatch spec | Context/outputs from current re-validate.md |
| `re-extract-6-checklist.md` | agent dispatch spec | Context/outputs from current re-checklist.md |
| `re-extract-7-constitute.md` | agent dispatch spec | Context/outputs from current re-constitute.md |
| `re-retarget-0-preflight.md` | commander_internal | New — checks analysis.json + strategic stubs exist |
| `re-retarget-1-input.md` | commander_internal | Interactive Q&A instructions from current re-retarget.md |
| `re-planning-0-preflight.md` | commander_internal | New — checks constitution.md exists and all [REQUIRES INPUT] markers are filled |
| `re-planning-1-plan.md` | agent dispatch spec | Context/outputs from current re-plan.md |
| `re-planning-2-tasks.md` | agent dispatch spec | Context/outputs from current re-tasks.md |

### agents/re/ (9 files)

| File | Dispatch ID | Source content |
|---|---|---|
| `analyzer.md` | `speckit-echelon-re-analyzer` | Work instructions from re-analyze.md |
| `specifier.md` | `speckit-echelon-re-specifier` | Work instructions from re-specify.md (1037→~350 lines) |
| `verifier.md` | `speckit-echelon-re-verifier` | Work instructions from re-verify.md |
| `expander.md` | `speckit-echelon-re-expander` | Work instructions from re-expand.md |
| `validator.md` | `speckit-echelon-re-validator` | Work instructions from re-validate.md |
| `checklister.md` | `speckit-echelon-re-checklister` | Work instructions from re-checklist.md |
| `constituter.md` | `speckit-echelon-re-constituter` | Work instructions from re-constitute.md |
| `planner.md` | `speckit-echelon-re-planner` | Work instructions from re-plan.md |
| `tasker.md` | `speckit-echelon-re-tasker` | Work instructions from re-tasks.md |

---

## Thin command wrapper format

### Pattern A — Orchestrator (runs full graph to completion)

```markdown
---
name: speckit.echelon.re-extract
description: "Phase 1 brownfield extraction — analyze codebase and generate domain specs + strategic artifacts"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are COMMANDER executing the brownfield extraction pipeline.

**Read `agents/control/commander.md` first.**

Then read `workflow/definition.yaml` `re_extraction:` section. Start at phase
`re-extract-0-preflight`, read each phase node's `spec_file` before dispatching,
write all state to `.specify/echelon/re/state.json`.

## Resumption

If `.specify/echelon/re/state.json` exists with `status: in_progress`, resume from
`last_dispatch.phase_id`. If `post_dispatch_complete: false`, re-run that phase first.

## Execution Continuity

Tool completions are never stopping points. After any Agent or Skill tool returns,
execute the next graph transition without ending your response. Stop only on DONE
or unresolvable BLOCKED.

## User Input

$ARGUMENTS
```

### Pattern B — Single-phase standalone (runs one phase and stops)

```markdown
---
name: speckit.echelon.re-verify
description: "Verify spec coverage against codebase and identify orphan files"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are COMMANDER running a single extraction phase.

**Read `agents/control/commander.md` first.**

Read `workflow/definition.yaml` `re_extraction:` section. Execute **only** phase
`re-extract-3-verify` — dispatch the agent, write result to
`.specify/echelon/re/state.json`, then stop. Do not advance to the next transition.

## Resumption

If `last_dispatch.phase_id = re-extract-3-verify` with `post_dispatch_complete: false`,
re-run the dispatch before writing results.

## User Input

$ARGUMENTS
```

---

## extension.yml changes

### Command entries (all 12)
Remove the `behavior:` block from all re-* command entries — neutral, matching `echelon.run` and `echelon.build`.

### New agent entries (9)
Added under `# ── Re-extraction layer ──` after the existing `# ── Understanding commands ──` block:

```yaml
    # ── Re-extraction layer ──────────────────────────────────────────────────
    - name: "speckit.echelon.re-analyzer"
      file: "agents/re/analyzer.md"
      description: "RE-ANALYZER — extracts structured codebase data via analysis scripts"
      behavior:
        execution: agent
        capability: strong
        tools: full        # Bash needed for run-analysis.sh
        color: orange
    - name: "speckit.echelon.re-specifier"
      file: "agents/re/specifier.md"
      description: "RE-SPECIFIER — synthesises domain specifications from analysis artifacts"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
    - name: "speckit.echelon.re-verifier"
      file: "agents/re/verifier.md"
      description: "RE-VERIFIER — computes spec coverage and clusters orphan files"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
    - name: "speckit.echelon.re-expander"
      file: "agents/re/expander.md"
      description: "RE-EXPANDER — fills coverage gaps from orphan file clusters"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
    - name: "speckit.echelon.re-validator"
      file: "agents/re/validator.md"
      description: "RE-VALIDATOR — quality-checks specs and auto-resolves ambiguities from code"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
    - name: "speckit.echelon.re-checklister"
      file: "agents/re/checklister.md"
      description: "RE-CHECKLISTER — generates per-domain and summary quality checklists"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
    - name: "speckit.echelon.re-constituter"
      file: "agents/re/constituter.md"
      description: "RE-CONSTITUTER — generates strategic artifacts (constitution, strategy, risks, gaps, ADRs)"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
    - name: "speckit.echelon.re-planner"
      file: "agents/re/planner.md"
      description: "RE-PLANNER — generates per-domain plan.md informed by constitution"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
    - name: "speckit.echelon.re-tasker"
      file: "agents/re/tasker.md"
      description: "RE-TASKER — generates per-domain tasks.md files"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
```

---

## State machine — `.specify/echelon/re/state.json`

### Schema

```json
{
  "run_id": "re-2026-05-17T14:32:00Z",
  "status": "in_progress | done | blocked",
  "phase": "re-extract-2-specify",
  "last_dispatch": {
    "phase_id": "re-extract-2-specify",
    "agent": "speckit-echelon-re-specifier",
    "post_dispatch_complete": false,
    "dispatched_at": "2026-05-17T14:33:00Z"
  },
  "mode": "single | polyrepo",
  "output_dir": ".specify/echelon/re",
  "domains": ["auth", "api", "data-layer"],
  "coverage_pct": 64,
  "coverage_threshold": 80,
  "verify_expand_iterations": 2,
  "resolution_pct": 0,
  "resolution_threshold": 80,
  "validate_iterations": 0,
  "max_validate_iterations": 3,
  "artifacts": {
    "analysis_json": ".specify/echelon/re/analysis.json",
    "repos_manifest": ".specify/echelon/re/repos-manifest.json",
    "cross_repo": null
  },
  "issues_log": [],
  "reasoning_journal": ".specify/echelon/re/reasoning-journal.json"
}
```

### Protocol

Identical to squad state machine:

1. COMMANDER writes `last_dispatch` sentinel with `post_dispatch_complete: false` **before** every agent dispatch
2. COMMANDER reads agent's `echelon_result:` block, applies `state_updates`, flips `post_dispatch_complete: true`
3. On bootstrap: if `post_dispatch_complete: false` → re-dispatch same phase; else → read `phase`, advance via transitions

### `echelon_result:` schema all re-* agents must emit

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-2-specify
  state_updates:
    domains: [auth, api, data-layer]    # only if changed
    coverage_pct: 72                    # re-verifier only
    resolution_pct: 85                  # re-validator only
    validate_iterations: 1              # re-validator only
  output_files:
    - specs/001-re-auth/spec.md
  journal_entries:
    - type: phase_complete
      phase: re-extract-2-specify
      summary: "..."
  blocked_reason: null
```

### GOLDDIGGER integration — unchanged

GOLDDIGGER dispatches `speckit.echelon.re-extract` via Skill tool. The re-* COMMANDER manages `re/state.json` independently. GOLDDIGGER reads artifacts from `.specify/echelon/re/` and writes them to `.specify/squad/state.json.golddigger_artifacts` as today. No changes to GOLDDIGGER.

---

## Testing

### 1. YAML structural validation (pre-commit)

New assertions in `test-unit-registry-sync.sh`:
- 13 phase nodes registered across the 3 new sections
- All `type: agent` phases reference an existing file under `agents/re/`
- All 9 new agent entries present in `extension.yml`
- All 12 re-* command entries have no `behavior:` block

### 2. Existing brownfield bash tests — unchanged acceptance gate

`tests/integration/re/test-discover-repos.sh`, `test-extract-cross-repo.sh`, `test-run-analysis-polyrepo.sh` must pass throughout all implementation stages.

### 3. New kernel tests — `tests/kernel/test_re_state.py`

```python
def test_last_dispatch_sentinel_written_before_dispatch()
def test_post_dispatch_complete_flipped_after_result()
def test_resumption_reruns_incomplete_phase()
```

Pure function tests following the pattern of `tests/kernel/test_preflight.py`.

### 4. Dry-run smoke test (post-implementation)

```bash
bash scripts/bash/dry-run.sh
specify extension validate extension/
python3 -c "import yaml; d=yaml.safe_load(open('extension/extension.yml')); \
  re_agents=[c for c in d['provides']['commands'] if 're-' in c['name'] and c.get('behavior',{}).get('execution')=='agent']; \
  assert len(re_agents)==9, f'Expected 9, got {len(re_agents)}'"
```

---

## Out of scope

- Changing GOLDDIGGER's dispatch logic (it already works correctly)
- Adding new brownfield capabilities (new agents, new analysis types)
- Wiring re-* phases into the main `phases:` squad graph (re-* is a separate self-contained sub-system invoked by GOLDDIGGER)
