# Codegen–Echelon Integration Design

**Date:** 2026-04-15
**Branch:** evolution_v2
**Status:** Implemented

---

## Problem

`codegen` is a SOAR-powered build pipeline with inviolable quality gates (CQ-ISC) and persistent memory (MemPalace/EPMEM/SMEM). It was developed outside of echelon and implements its own state mechanism, making it incompatible with the echelon harness. The skill itself also needs polish. The goal is to make codegen a usable, first-class alternative to `echelon build`.

Three specific pain points:
1. The skill is fragile and inconsistent when running inside the harness sandbox
2. codegen's state mechanism conflicts with how echelon manages state
3. The skill content needs polishing (argument parsing, SOAR init, resume)

---

## Approach: Codegen as Native Echelon Command (Option B)

`echelon.codegen.md` is a full first-class command in echelon. It reads the same Phase A artifacts as `echelon.build` (`spec.md`, `tasks.md`, `constitution.md`, `research.md`), drives the codegen pipeline, and writes to `.specify/squad/state.json` using echelon's schema. The SOAR/MemPalace machinery is untouched. codegen becomes a proper spec-kit extension.

Two other options were considered and rejected:
- **Thin wrapper (A):** defers the hard problems; state bridging remains an afterthought
- **Strategy plugin (C):** not directly invocable as `echelon codegen 001-feature`

---

## Architecture

### New artifacts

| Artifact | Location | Description |
|---|---|---|
| `extension.yml` | codegen repo root | Turns codegen into a proper spec-kit extension |
| `commands/echelon.codegen.md` | echelon repo | New echelon command driving the codegen pipeline |

### Changed artifacts

| Artifact | Location | Change |
|---|---|---|
| `commands/codegen.md` | codegen repo | Polished skill (argument parsing, state writes, resume sync, fail-fast SOAR init) |
| `extension.yml` | echelon repo | One new command entry: `b3c.echelon.codegen` |

### Unchanged

- SOAR bridge, MemPalace, EPMEM/SMEM, CQ-ISC library — fully untouched
- `echelon.build.md` — untouched
- Harness `StrategyCoordinator` — no code changes

### Execution flow

```
User: /echelon.codegen 001-feature
        │
        ▼
echelon.codegen.md
  1. Validate Phase A artifacts (spec.md, tasks.md, constitution.md, research.md)
  2. Derive spec_id, WING from feature path
  3. Mine spec into MemPalace (wing = spec_id)
  4. Verify codegen CLI + SOAR binary available (fail fast)
  5. Self-register strategy file (idempotent)
  6. Drive pipeline: RE → DECOMPOSE → IMPLEMENT → GATE → TEST → DELIVER
  7. Write .specify/squad/state.json after each SOAR phase transition
  8. On DELIVER: write final state.json + codegen-report.md

Parallel run (harness):
  .specify/harness/strategies/001-feature/codegen.md  ← auto-created by step 5
  .specify/harness/strategies/001-feature/default.md  ← existing (or empty = echelon build)
  StrategyCoordinator runs both in parallel ThreadPoolExecutor
  kill_losers: first to converge cancels the other
```

---

## State Schema

### `.specify/squad/state.json` (harness-facing)

Written by `echelon.codegen.md` after each SOAR phase transition. Fields match what `echelon.build` already writes — `StrategyCoordinator.compare_results` works unchanged.

```json
{
  "status": "building | build_done | blocked | escalated",
  "phase": "codegen_re | codegen_decompose | codegen_implement | codegen_gate | codegen_test | codegen_deliver | done",
  "build": {
    "total_tasks": 12,
    "completed_tasks": 4,
    "current_task": "T-005",
    "verification_verdict": "PASS | FAIL | null"
  },
  "updated_at": "2026-04-15T10:23:00Z"
}
```

On impasse: `status → "escalated"`, `phase` stays at the blocked phase. Harness handles it via the existing escalation path.

### `codegen-state.json` (codegen-internal, SOAR-facing)

All existing codegen fields remain here — `pipeline_id`, `wing`, `psi`, `task_queue`, `re_phase`, `tier1_gate`, `wall_clock_start/end`, `epmem` entries, violation counts. No changes to this schema.

**Write cadence:** `echelon.codegen.md` updates `state.json` after each phase. `codegen-state.json` is written by the existing codegen gate CLI as it does today.

---

## Extension Configuration

### codegen repo — new `extension.yml`

```yaml
schema_version: "1.0"

extension:
  id: "codegen"
  name: "Codegen"
  version: "1.0.0"
  description: "SOAR-powered build pipeline with inviolable quality gates (CQ-ISC) and persistent memory (MemPalace/EPMEM/SMEM)"
  author: "B3Cognition"
  repository: "https://github.com/B3Cognition/codegen"
  license: "MIT"
  homepage: "https://github.com/B3Cognition/codegen"

requires:
  speckit_version: ">=0.4.2"
  tools:
    - name: "soar"
      version: ">=9.6.4"
      required: true
      hard_stop: true
      note: "SOAR binary at ~/soar/bin/soar. Install from SoarGroup/Soar releases. HARD STOP if unavailable."
    - name: "codegen"
      version: ">=1.0.0"
      required: true
      hard_stop: true
      note: "codegen CLI. Install via: bash ~/codegen/scripts/install.sh"

provides:
  commands:
    - name: "speckit.codegen"
      file: "commands/codegen.md"
      description: "SOAR-powered build: RE → DECOMPOSE → IMPLEMENT → GATE → TEST → DELIVER with inviolable CQ-ISC quality gates"
      behavior:
        execution: isolated
        invocation: explicit
        capability: strong
        effort: high
        tools: full

tags:
  - "build"
  - "soar"
  - "quality-gates"
  - "memory"
```

### echelon repo — addition to `extension.yml` `provides.commands`

```yaml
    - name: "b3c.echelon.codegen"
      file: "commands/echelon.codegen.md"
      description: "Execute building phase via SOAR-powered codegen pipeline — alternative to echelon.build"
      behavior:
        execution: isolated
        invocation: explicit
        capability: strong
        effort: high
        tools: full
```

### Command file frontmatter (both `commands/codegen.md` and `commands/echelon.codegen.md`)

Minimal — `name` and `description` only. No `behavior:` block in the file; behavior is declared in `extension.yml`.

---

## `echelon.codegen.md` Command Structure

Mirrors `echelon.build.md` sections for consistent user experience.

### Argument format

Identical to `echelon.build`: the user passes a feature path such as `001-feature`. The command derives `spec_id = "001"` and resolves the Phase A directory as `specs/001-feature/`. All file reads and state writes use this resolved path.

### Phase mapping

| echelon.build section | echelon.codegen equivalent |
|---|---|
| BUILD_INIT — validate Phase A artifacts | Same: read `tasks.md`, `spec.md`, `constitution.md`, `research.md` from `specs/{NNN}-{feature}/` |
| Parse tasks, determine build order | Mine spec into MemPalace (wing = spec_id), derive WING |
| Initialize build state | Verify codegen CLI + SOAR binary; write initial `state.json` |
| — | **Self-register strategy file** (new step, see below) |
| BUILD_LOOP | Drive RE → DECOMPOSE → IMPLEMENT → GATE → TEST pipeline |
| Phase checkpoint | Write `state.json` after each SOAR phase transition |
| BUILD_DONE | DELIVER phase → write final `state.json` + `codegen-report.md` |

### Key differences from `echelon.build.md`

- No squad agents — SOAR CQ-ISC gate is the quality enforcement mechanism
- Convergence signal: `Ψ ≥ 0.70` + all Tier 1 tests pass (vs VERIFICATION agent)
- On impasse: writes `codegen-impasse.md` + sets `status: escalated`

### Self-registration step

After BUILD_INIT, before SOAR bridge init:

```
1. Derive {spec_id} from feature path argument
2. Ensure .specify/harness/strategies/{spec_id}/ exists (create if absent)
3. Write .specify/harness/strategies/{spec_id}/codegen.md (idempotent):
   ---
   This strategy uses the SOAR-powered codegen pipeline.
   Invoke: /b3c.echelon.codegen {spec_id}
   ---
4. Continue to SOAR bridge init
```

This makes the parallel harness run available after a single `echelon codegen` invocation — no manual strategy file creation required.

---

## Skill Polish (`commands/codegen.md`)

| Issue | Fix |
|---|---|
| Arguments parsed from raw `$ARGUMENTS` glob | Read `spec_id` from Phase A feature path argument; derive `WING` from `spec_id` |
| SOAR bridge silently falls back to Model B | `CODEGEN_REQUIRE_MODEL_A=1` enforced; fail fast with clear install hint |
| State writes absent between phases | Write harness fields to `.specify/squad/state.json` after every phase transition |
| Resume doesn't sync state files | On `--resume`, read `codegen-state.json` and restore `.specify/squad/state.json` in sync |
| Doubled path `commands/commands/codegen.md` | Corrected to `commands/codegen.md` |

---

## Parallel Harness Run

The harness multi-strategy infrastructure (`StrategyCoordinator`, `ThreadPoolExecutor`) requires no changes.

**Strategy files** are auto-created by `echelon.codegen.md` on first run:
- `.specify/harness/strategies/{spec_id}/codegen.md` — created by self-registration step
- `.specify/harness/strategies/{spec_id}/default.md` — optional; harness uses empty string if absent

**Invocation:**
```
run spec 001-feature strategies=default,codegen kill_losers
```

`kill_losers=true` — first strategy to converge cancels the other. Omit for full parallel comparison.

---

## Convergence Signals (Harness Compatibility)

| Condition | `state.json` status | Harness interpretation |
|---|---|---|
| Ψ ≥ 0.70, Tier 1 tests pass | `build_done` | Converged |
| SOAR RETRY loop, in progress | `building` | Still running |
| Impasse (conflict, escalate) | `escalated` | Non-converging strategy |
| SOAR BLOCKED task | `blocked` | Non-converging strategy |

---

## Out of Scope

- Changes to SOAR bridge, MemPalace, EPMEM/SMEM, or CQ-ISC library
- Changes to `echelon.build.md`
- Changes to harness `StrategyCoordinator` or `strategy_loader.py`
- Merging codegen Python source into echelon
