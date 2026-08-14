# Brownfield Extraction (re-* commands)

Brownfield extraction reverse-engineers an existing codebase into spec-kit format artifacts — domain specs, quality checklists, and strategic migration documents. Use it when you need to understand, migrate, or modernize a legacy system before building with echelon's standard pipeline.

## Lifecycle commands

Reverse engineering runs independently from spec authoring:

```bash
echelon re run                                      # changed; no-op when current
echelon re run --re-policy refresh-all --re-max-inner 10
echelon re continue --re-max-inner 12              # continue without an answer
echelon re continue --re-token-limit 25000000      # raise active token ceiling
echelon re resume "Use the v2 contract"             # answer a human-input block
```

RE state lives under `runs/re-*/` and uses the separate `runs/.current-re`
marker. A complete result publishes automatically to the durable `re/` registry.
Partial results do not auto-publish. `changed` is the default policy and creates
no provider when every source is current.

Spec runs do not fingerprint, plan, execute, repair, publish, or freshness-check
RE. They snapshot the latest published generation into the spec run as read-only
context by default. Pass `echelon spec run ... --ignore-re` to omit it. A later RE
publication does not change an already-started spec run.

Migration:

```text
before: echelon spec run "Build dashboards" --re-policy changed --re-max-inner 10
after:  echelon re run --re-policy changed --re-max-inner 10
        echelon spec run "Build dashboards"
```

## Handoff to proportional specification authoring

Published RE is immutable input to a later spec run; it does not acquire
authority over specification quality policy. The default proportional Phase A
flow evaluates an initial candidate plus three automatic repairs and may then
offer plus one optional authorized repair. Guided and semi runs leave that
material choice to the human; banzai leaves it to COMMANDER through the same
sealed controller decision.

Quality debt is not a substitute for missing brownfield evidence. An unresolved
RE fact, conflicting primary evidence, unsupported product-input mapping,
invalid traceability, CRITICAL contradiction, or invalid mandatory artifact
keeps its normal evidence, clarification, or fail-closed route. Only residual
eligible specification-quality debt can be recorded as `accepted with quality
debt`, with `quality-debt.json` preserved separately from a passing quality
certificate.

`echelon spec status` shows the key bounded decision/debt evidence and the path
to `quality-debt.json`; that artifact retains the full evidence. The explicit
human choice uses `echelon spec resume`; ordinary `echelon spec continue` cannot
silently accept debt, add repairs, or reopen a declined loop.

## Three-phase workflow

```text
Phase 1: Extract (understanding)
┌───────────┐   ┌───────────┐   ┌─────────────────┐   ┌───────────────────┐   ┌─────────────┐   ┌───────────────┐
│ re-analyze│──▶│ re-specify│──▶│ verify + expand │──▶│     re-validate   │──▶│re-checklist │──▶│ re-constitute │
└───────────┘   └───────────┘   │ (until ≥80%     │   │ (until ≥80%       │   └─────────────┘   └───────────────┘
                                │  coverage)      │   │  resolved or max  │         │                  │
                                └─────────────────┘   │  iterations)      │         ▼                  ▼
                                                      └───────────────────┘   Quality checklists  Strategic
                                                                            (per-domain + summary) artifacts

Phase 2: Retarget (decisions)
                              ┌────────────┐
                              │ re-retarget│  ← Guided prompts to fill decisions (human-in-the-loop)
                              └────────────┘
                                    │
                                    ▼
                              Completed strategic artifacts

Phase 3: Plan All (planning)
                              ┌──────────┐   ┌───────────┐
                              │  re-plan │──▶│  re-tasks │
                              └──────────┘   └───────────┘
                                    │             │
                                    ▼             ▼
                              Per-domain    Per-domain
                              plan.md       tasks.md
```

**Coverage loop** — Phase 1 iterates until the coverage threshold is met:

```text
re-specify → re-verify → coverage < 80%? → re-expand → re-verify → ...
                              ↓
                         coverage ≥80% → continue to re-validate
```

**Validation loop** — After coverage is met, validates spec quality and auto-resolves issues:

```text
re-validate (Basic) → resolution < 80%? → re-validate (Deep) → resolution < 80%? → re-validate (Extended) → ...
                              ↓
                         resolution ≥80% (or max iterations reached) → continue to re-checklist
```

Each validation iteration uses a progressively deeper search strategy:

| Iteration | Strategy | Scope |
|-----------|----------|-------|
| 1 | Basic | Constants, configs, direct term matches |
| 2 | Deep | Function bodies, test assertions, docstrings |
| 3 | Extended | Cross-file analysis, naming conventions, related modules |

## Key concepts

**Orphan Files** — Source files not covered by any domain specification. `re-verify` identifies these and clusters them by similarity. `re-expand` creates new domain specs for high-confidence clusters.

**Coverage Threshold** — Default 80%. The `re-verify` → `re-expand` loop repeats until this threshold is met. Configurable via `re.workflow.coverage_threshold` in `echelon-config.yml`.

**Resolution Threshold** — Default 80%. The `re-validate` loop repeats with progressively deeper strategies (Basic → Deep → Extended) until this threshold is met or the max iteration count is reached (default 3). Unresolved items are marked `[NEEDS CLARIFICATION]` and catalogued in `specs/000-re-overview/validation-report.md`.

**Quality Checklists** — Generated by `re-checklist`. Described as "unit tests for requirements" — they validate whether specs are complete, clear, consistent, and ready for planning. Two levels:
- Per-domain checklists at `specs/NNN-re-{domain}/checklist.md`
- Summary checklist at `specs/000-re-overview/checklist.md` covering cross-domain and migration concerns

**Strategic Artifacts** — Generated by `re-constitute` with `[REQUIRES INPUT]` placeholders for decisions that require human input:
- `constitution.md` — legacy analysis, lessons learned, target stack, coding standards
- `migration-strategy.md` — 6R/7R analysis per domain, migration waves, rollback strategy
- `risk-matrix.md` — risk inventory with likelihood × impact scoring and mitigation plans
- `gap-analysis.md` — feature, infrastructure, skills, and dependency gaps
- `adrs/` — Architecture Decision Records with context, options, and trade-offs

## Output structure

First-class RE lifecycle candidates are written under `runs/re-<timestamp>/re/`.
The durable latest publication lives under the workspace `re/` registry. Legacy
standalone `re-*` skills may still use `.specify/echelon/re/` when invoked
directly.

```text
runs/re-<timestamp>/re/            # active echelon re run
├── analysis.json                     # Structured codebase data (files, deps, git history, configs)
├── codegraph-analysis.json           # Optional full structural graph (Node.js + CodeGraph bridge)
├── codegraph-summary.json            # Optional compact graph summary for token-efficient agent reads
├── perlgraph-analysis.json           # Optional full Perl structural graph (Node.js + PerlGraph)
├── perlgraph-summary.json            # Optional compact Perl graph summary for agent reads
├── repos-manifest.json               # Polyrepo discovery manifest (present in polyrepo mode)
└── {repo-name}/                      # Per-repo data in polyrepo mode
    ├── analysis.json
    └── cross-repo.json               # Cross-repo shared-tech and dependency map

re/                                  # latest durable published generation
├── index.json
├── sources/<source-id>/
└── workspace/

specs/
├── 000-re-overview/                  # Cross-domain summary (fixed ID 000)
│   ├── overview.md                   # Migration summary, dependency graph
│   ├── checklist.md                  # Cross-domain quality checklist
│   ├── constitution.md               # Legacy analysis + target principles
│   ├── migration-strategy.md         # 6R/7R analysis, waves, rollback
│   ├── risk-matrix.md                # Risk inventory and mitigation
│   ├── gap-analysis.md               # Current vs target gaps
│   ├── coverage-report.md            # File coverage analysis
│   ├── validation-report.md          # Quality check results
│   └── adrs/                         # Architecture Decision Records
│
└── NNN-re-{domain}/                  # Per-domain artifacts (numbered from highest existing + 1)
    ├── spec.md                       # What to build
    ├── checklist.md                  # Domain quality checklist
    ├── plan.md                       # How to build it (generated by re-plan)
    └── tasks.md                      # Task breakdown (generated by re-tasks)
```

**Naming convention**: All reverse-engineered specs use `NNN-re-{domain}` format. In polyrepo mode the repo name is included: `NNN-re-{repo}-{domain}`.

## Configuration

All brownfield configuration lives under the `re:` top-level key in `echelon-config.yml`. See [`docs/re-config.md`](re-config.md) for the full schema.

## Polyrepo support

When run from a directory containing multiple repositories as immediate subdirectories, `re-analyze` (and `re-extract`) automatically run `discover-repos.sh` to detect qualifying repos. A directory qualifies if it has a recognized project marker (`package.json`, `go.mod`, `pom.xml`, `Cargo.toml`, `*.sln`, etc.) or more than 5 source files.

The discovery result is written to the resolved RE output directory as `workspace-manifest.json` and, for compatibility, `repos-manifest.json`. New tooling should read `workspace-manifest.json` first because it distinguishes orchestration workspace files from implementation source roots. Each source root is then analyzed independently and cross-repo dependency data is captured in `cross-repo.json`. Coverage thresholds are evaluated as a combined total across all source roots.

Set `re.polyrepo.enabled: false` in `echelon-config.yml` to force single-repo mode, or `true` to force polyrepo mode unconditionally. The default `auto` detects based on directory contents.
