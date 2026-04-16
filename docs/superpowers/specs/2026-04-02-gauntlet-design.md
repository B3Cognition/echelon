# Gauntlet — Design Spec

**Date:** 2026-04-02  
**Status:** Draft  
**Scope:** New spec-kit extension (`speckit.gauntlet.*`) providing an end-to-end test suite for the full echelon orchestration pipeline (UNDERSTAND → DECIDE → SOLUTION → BUILD → LEARN) across all canonical usage patterns

---

## 1. Purpose

Gauntlet is a spec-kit extension that runs structured test scenarios against the full echelon agent pipeline (all 5 phases, 42 agents), capturing a custom JSON trace per run, evaluating layered assertions, and enabling structural diff against a golden baseline. It covers three canonical usage patterns:

- **greenfield-python** — single repo, no existing source code, new Python project
- **brownfield-ts** — single repo, existing TypeScript codebase
- **brownfield-polyrepo** — multiple repos in a parent directory, combination of Python and TypeScript with cross-repo dependencies

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              speckit.gauntlet extension                     │
│                                                             │
│  commands/                                                  │
│    run.md       → invokes harness run <scenario> [flags]    │
│    record.md    → invokes harness record <scenario>         │
│    diff.md      → invokes harness diff <run-id>             │
│    report.md    → invokes harness report                    │
│                                                             │
│  extension.yml  → registers commands, declares deps         │
└────────────────────────┬────────────────────────────────────┘
                         │ subprocess call
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Python Harness (gauntlet CLI)                  │
│                                                             │
│  scenarios/                                                 │
│    greenfield-python/    ← single repo, new Python code     │
│    brownfield-ts/        ← single repo, existing TypeScript │
│    brownfield-polyrepo/  ← multi-repo, Python + TypeScript  │
│                                                             │
│  harness/                                                   │
│    runner.py     ← workspace setup, echelon invocation      │
│    tracer.py     ← watches .specify/squad/, emits trace     │
│    asserter.py   ← layered assertions (6 levels)            │
│    mocker.py     ← intercepts agent calls, replays stubs    │
│    differ.py     ← structural diff of trace vs golden       │
│    reporter.py   ← summary output (text + JSON)             │
└─────────────────────────────────────────────────────────────┘
                         │ reads/writes
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Isolated workspace (tmp dir per run)                       │
│    .specify/squad/agent-states-events.jsonl  ← echelon      │
│    .specify/squad/state.json                                │
│    specs/                                                   │
│    trace.jsonl          ← harness-generated trace           │
│    assertion-report.json                                    │
└─────────────────────────────────────────────────────────────┘
```

Each run gets an isolated temporary workspace. No shared state between runs. The tracer watches echelon's existing `agent-states-events.jsonl` and enriches it with timing and assertion metadata into a harness-owned `trace.jsonl`.

---

## 3. Extension Structure

```
gauntlet/
├── extension.yml
├── config-template.yml
├── commands/
│   ├── run.md
│   ├── record.md
│   ├── diff.md
│   └── report.md
├── src/
│   └── gauntlet/
│       ├── __init__.py
│       ├── cli.py           ← entry point: `gauntlet <cmd> [args]`
│       ├── runner.py
│       ├── tracer.py
│       ├── asserter.py
│       ├── mocker.py
│       ├── differ.py
│       └── reporter.py
├── scenarios/
│   ├── greenfield-python/
│   ├── brownfield-ts/
│   └── brownfield-polyrepo/
├── pyproject.toml
└── CLAUDE.md
```

### Commands

| Command | Signature | Purpose |
|---|---|---|
| `speckit.gauntlet.run` | `[scenario] [--mode=mock\|live] [--target=path]` | Run one or all scenarios, emit trace, evaluate assertions |
| `speckit.gauntlet.record` | `[scenario] [--target=path]` | Live run, save resulting trace as golden baseline |
| `speckit.gauntlet.diff` | `[run-id\|scenario]` | Structural diff of last trace vs golden, human-readable output |
| `speckit.gauntlet.report` | `[--last-n=N]` | Summary across all scenarios and recent runs |

### `extension.yml` (key fields)

```yaml
name: gauntlet
version: 1.0.0
requires:
  speckit_version: ">=0.4.2"
  extensions:
    - name: echelon
      version: ">=0.8.0"
      required: true
    - name: revenge
      version: ">=3.0.0"
      required: false       # only needed for brownfield scenarios
    - name: understanding
      version: ">=3.6.0"
      required: false       # only needed when quality assertion enabled
```

### `config-template.yml` (key fields)

```yaml
mode: mock                  # mock | live
scenarios: all              # all | [greenfield-python, brownfield-ts, ...]
phases: all                 # all | [understand, decide, solution, build, learn]
assertions:
  completion: true
  artifacts: true
  quality_gates: true       # requires understanding extension
  build_integrity: true     # only active when phases includes build
  learn_state: true         # only active when phases includes learn
  trace_diff: true
trace:
  format: jsonl
  include_agent_inputs: true
  include_agent_outputs: true
```

---

## 4. Scenarios & Fixtures

### Directory layout per scenario

```
scenarios/<name>/
├── scenario.yml
├── fixtures/
│   ├── default/            ← synthetic source code (committed)
│   └── init.sh             ← seeds .git history, installs deps
└── golden/
    ├── trace.jsonl          ← baseline for trace_diff
    ├── artifacts-manifest.json
    └── stubs/              ← one file per expected agent (varies by scenario)
        ├── GOLDDIGGER.md   ← only in brownfield scenarios
        ├── SCOUT.md
        ├── SAGE.md
        └── CARTOGRAPHER.md
```

### Scenario descriptions

Each scenario can be run with a `phases` parameter controlling how far through the echelon pipeline it runs. The default is `all` (full pipeline). Stopping earlier is useful for fast feedback or when BUILD fixtures are not yet seeded.

| Scenario | Type | Layout | All-phases agents exercised |
|---|---|---|---|
| `greenfield-python` | greenfield | single repo | SCOUT, SAGE, CARTOGRAPHER, GATEKEEPER, ARCHITECT, ORCHESTRATOR, SENTINEL, IMPLEMENTER, SPEC_GUARD, CODE_REVIEWER, TEST_GUARDIAN, MIRROR, AUDITOR |
| `brownfield-ts` | brownfield | single repo | PROSPECTOR, GOLDDIGGER→REVENGE, SCOUT, SAGE, CARTOGRAPHER, GATEKEEPER, ARCHITECT, ORCHESTRATOR, SENTINEL, IMPLEMENTER, SPEC_GUARD, CODE_REVIEWER, TEST_GUARDIAN, MIRROR, AUDITOR |
| `brownfield-polyrepo` | brownfield | polyrepo (flat) | PROSPECTOR, GOLDDIGGER→REVENGE (polyrepo), SCOUT, SYNTHESIZER, SAGE, CARTOGRAPHER, GATEKEEPER, ARCHITECT, ORCHESTRATOR, SENTINEL, IMPLEMENTER, SPEC_GUARD, CODE_REVIEWER, TEST_GUARDIAN, MIRROR, AUDITOR |

### `scenario.yml` structure (brownfield-polyrepo example)

```yaml
name: brownfield-polyrepo
description: "Polyrepo brownfield: Python + TypeScript with cross-repo dependency"
type: brownfield
layout: polyrepo

fixture:
  default: fixtures/default/
  init_script: fixtures/init.sh   # seeds .git history

echelon:
  prompt: "Analyze and plan modernization of the payment service suite"
  config:
    autonomy: banzai
    phases: all               # understand | decide | solution | build | learn | all

expected_agents:
  - PROSPECTOR
  - GOLDDIGGER
  - SCOUT
  - SYNTHESIZER
  - SAGE
  - CARTOGRAPHER
  - GATEKEEPER
  - ARCHITECT
  - ORCHESTRATOR
  - SENTINEL
  - IMPLEMENTER
  - SPEC_GUARD
  - CODE_REVIEWER
  - TEST_GUARDIAN
  - MIRROR
  - AUDITOR

expected_artifacts:
  # UNDERSTAND
  - .specify/squad/brownfield-index.md
  - specs/000-re-overview/overview.md
  - specs/000-re-overview/coverage-report.md
  - specs/*/spec.md
  # DECIDE
  - .specify/squad/feasibility.md
  - .specify/squad/estimates.md
  # SOLUTION
  - specs/*/plan.md
  - specs/*/tasks.md
  # BUILD
  - src/**/*                  # at least one source file produced
  # LEARN
  - .specify/knowledge-base/calibration-profile.yaml
  - .specify/knowledge-base/estimates-log.yaml

assertions:
  completion: true
  artifacts: true
  quality_gates: true
  build_integrity: true       # only evaluated when phases includes build
  learn_state: true           # only evaluated when phases includes learn
  trace_diff:
    enabled: true
    ignore_fields: [timestamp, duration_ms, run_id]
    required_match_pct: 80
```

### Synthetic fixture design principles

- 30 files or fewer per fixture for fast runs
- Realistic enough to exercise revenge's polyrepo discovery and echelon's GOLDDIGGER path
- `init.sh` seeds 3–5 git commits so revenge's `extract-git-history.sh` has data to analyze
- When `--target=path` is passed, fixtures are bypassed entirely
- BUILD phase stubs must produce minimal but syntactically valid source files (compilable Python / TypeScript) so `build_integrity` assertions can run

---

## 5. Trace Format

The trace is a newline-delimited JSON file (`trace.jsonl`) — one event per line, append-only during a run.

### Event types

```jsonc
// Run lifecycle
{"type": "run_start", "run_id": "2026-04-02T10:00:00Z-brownfield-ts", "scenario": "brownfield-ts", "mode": "mock", "fixture": "default"}
{"type": "run_end",   "run_id": "...", "status": "pass|fail", "duration_ms": 42310, "assertion_results": {...}}

// Agent lifecycle
{"type": "agent_start",  "agent": "GOLDDIGGER", "layer": "exploration", "inputs": {"brownfield_path": "..."}}
{"type": "agent_end",    "agent": "GOLDDIGGER", "layer": "exploration", "status": "ok|error|skipped", "duration_ms": 1240, "outputs": {"artifacts": ["brownfield-index.md"]}}

// Artifact events
{"type": "artifact_written", "path": "specs/001-re-payments/spec.md", "agent": "CARTOGRAPHER", "size_bytes": 3210}

// Phase transition events
{"type": "phase_start", "phase": "build"}
{"type": "phase_end",   "phase": "build", "status": "ok", "duration_ms": 18400}

// Assertion events (emitted after run completes)
{"type": "assertion", "level": "completion",      "status": "pass"}
{"type": "assertion", "level": "artifacts",       "status": "pass", "found": [...], "missing": [...]}
{"type": "assertion", "level": "quality_gates",   "status": "pass", "scores": {"overall": 0.74, "testability": 0.81}}
{"type": "assertion", "level": "build_integrity", "status": "pass", "checks": {"compiles": true, "lint": "pass", "tests_runnable": true, "spec_guard_violations": 0}}
{"type": "assertion", "level": "learn_state",     "status": "pass", "checks": {"calibration_updated": true, "estimates_appended": true}, "kb_diff": {...}}
{"type": "assertion", "level": "trace_diff",      "status": "pass", "match_pct": 93, "diffs": [...]}

// Mode indicator
{"type": "mode", "mode": "mock", "stub_file": "scenarios/brownfield-ts/golden/trace.jsonl"}
```

### Diff strategy

The differ compares current `trace.jsonl` against `golden/trace.jsonl` structurally:
- `ignore_fields` (per scenario config): `timestamp`, `duration_ms`, `run_id`, `size_bytes`
- Compares: agent sequence, agent statuses, artifact names produced, assertion outcomes
- Reports: agents added/removed, agents that changed status, artifacts missing vs golden
- `required_match_pct` (default 80%) — percentage of agent events that must match golden

### Run storage

```
~/.specify/gauntlet/
├── runs/
│   ├── 2026-04-02T10:00:00Z-brownfield-ts/
│   │   ├── trace.jsonl
│   │   └── assertion-report.json
│   └── ...
└── report-cache.json      ← index used by speckit.gauntlet.report
```

---

## 6. Assertion Layers

Evaluated in order. Short-circuit on failure. Levels 4 and 5 are only evaluated when the corresponding phases were included in the run.

```
Level 1: COMPLETION
  ✓ echelon run exited without error
  ✓ no agent emitted status=error
  ✓ all expected_agents from scenario.yml appeared in trace
  ✓ all expected phases completed (phase_end status=ok)

Level 2: ARTIFACTS
  ✓ all paths in expected_artifacts exist in workspace
  ✓ no artifact is empty (size > 0)
  ✓ polyrepo: artifacts exist per repo (per-domain specs)

Level 3: QUALITY GATES  (skipped if understanding not installed)
  ✓ each produced spec.md scores >= threshold on b3c.understanding.validate
  ✓ overall >= 0.70, testability >= 0.70, semantic >= 0.60
  ✓ per-spec scores written to assertion-report.json

Level 4: BUILD INTEGRITY  (only when phases includes build)
  ✓ produced source files are syntactically valid (compile / parse without errors)
  ✓ lint passes on produced code (ruff for Python, tsc --noEmit for TypeScript)
  ✓ produced test files are runnable (pytest --collect-only / jest --listTests)
  ✓ SPEC_GUARD reported zero violations in trace
  ✓ ENGINEERING_MANAGER sign-off present in trace

Level 5: LEARN STATE  (only when phases includes learn)
  ✓ .specify/knowledge-base/calibration-profile.yaml was updated (mtime changed)
  ✓ .specify/knowledge-base/estimates-log.yaml has new entries vs run start
  ✓ AUDITOR and MIRROR agent_end events present in trace
  ✓ knowledge-base state diff vs golden written to assertion-report.json

Level 6: TRACE DIFF  (skipped if no golden baseline exists yet)
  ✓ agent sequence matches golden (excluding ignored_fields)
  ✓ phase sequence matches golden
  ✓ structural match >= required_match_pct (default 80%)
  ✓ diff details written to trace with human-readable summary
```

---

## 7. Mock & Live Modes

### Mock mode (default)

Before invoking echelon, the harness pre-populates each agent's expected output path in the isolated workspace with the corresponding stub from `golden/stubs/`. Echelon then runs normally but skips agents whose outputs already exist (requires echelon to expose a `--stub-dir` flag or a skip-if-outputs-exist check — a new echelon capability needed for this integration).

This means mock runs test echelon's orchestration logic (agent sequencing, phase gating, state transitions) and artifact flow, but not LLM output quality. The stubs represent known-good agent outputs captured during a prior live `record` run.

### Live mode (`--mode=live`)

Runs echelon with real Claude API calls. Used for:
- `speckit.gauntlet.record` — establishing or refreshing the golden baseline
- Periodic full validation (e.g. before a release)
- `--target=path` runs against real codebases

### `record` workflow

```
speckit.gauntlet.record brownfield-ts
  → runs live
  → on pass: writes trace.jsonl      → golden/trace.jsonl
             writes agent outputs   → golden/stubs/
             writes artifact list   → golden/artifacts-manifest.json
  → on fail: writes trace but does NOT overwrite golden (requires --force)
```

---

## 8. Dependencies

| Dependency | Required | Version | Role |
|---|---|---|---|
| spec-kit | yes | >=0.4.2 | Extension host |
| echelon | yes | >=0.8.0 | Agent pipeline under test |
| revenge | no | >=3.0.0 | Required for brownfield scenarios |
| understanding CLI | no | >=3.6.0 | Required for quality_gates assertion |
| Python | yes | >=3.11 | Harness runtime |

---

## 9. Out of Scope

- Performance benchmarking or load testing
- Testing spec-kit core (that is spec-kit's own test suite)
- UI or RADAR integration
- Full compilation of complex real-world codebases in BUILD fixtures — stubs produce minimal valid source only
