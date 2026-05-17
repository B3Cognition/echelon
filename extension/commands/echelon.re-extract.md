---
name: speckit.echelon.re-extract
description: "Extract and understand legacy codebase - generate specs and strategic artifacts"
behavior:
  execution: isolated
  invocation: automatic
---

# Extract: Understand the Legacy Codebase

> **Bash Command Guidelines**: Never use multi-line bash. Chain commands with `&&`. **IMPORTANT**: Do NOT use bash `ls`, `find`, `cat`, `echo`, or `grep` for file exploration - always use the dedicated Glob, Read, and Grep tools instead. Reserve bash only for git commands, `mkdir`, and other system operations.

Run the extraction pipeline to analyze a codebase and generate domain specifications plus strategic artifacts.

## Enforcement Rules

> **NEVER skip a sub-command invocation.** Each sub-command in Steps 3-8 MUST be invoked via the Skill tool and MUST return (success OR error) before proceeding to the next step. You may NOT rationalize skipping a step, claim it is unnecessary, or proceed without invoking it.
>
> **NEVER report a step as complete without verifying its output artifacts exist.** After each sub-command returns, you MUST verify the expected output files were created using the Glob or Read tool before proceeding.
>
> **NEVER claim a coverage or resolution threshold is met without running the verify or validate command.** The threshold can only be evaluated by the sub-command output — not by your own estimate.
>
> **Invalid state detection**: If the Final Summary (Step 9) is displayed but any of these are true, the pipeline has a bug:
> - `.specify/echelon/re/analysis.json` does not exist (Step 3 was skipped)
> - No `specs/NNN-re-*/spec.md` files exist (Step 4 was skipped)
> - No `specs/000-re-overview/coverage-report.md` exists (Step 5 was skipped)
> - No `specs/000-re-overview/validation-report.md` exists (Step 6 was skipped)
> - No `specs/NNN-re-*/checklist.md` files exist (Step 7 was skipped)
> - No `specs/000-re-overview/constitution.md` exists (Step 8 was skipped)

## Purpose

Single command that runs Phase 1 of the reverse engineering workflow:

1. **Reanalyze** - Extract structured data from codebase
2. **Respecify** - Generate domain specifications
3. **Verify & Expand** - Iterate until coverage threshold reached (default 80%)
4. **Validate** - Quality check specs, auto-resolve ambiguities from code
5. **Rechecklist** - Generate quality review checklists (per-domain + summary)
6. **Reconstitute** - Generate strategic artifacts (constitution, strategy, risks, gaps, ADRs)

```text
┌───────────┐   ┌───────────┐   ┌─────────────────┐   ┌───────────────────┐   ┌─────────────┐   ┌───────────────┐
│ reanalyze │──▶│ respecify │──▶│ verify + expand │──▶│     validate      │──▶│ rechecklist │──▶│ reconstitute  │
└───────────┘   └───────────┘   │ (until ≥80%     │   │ (until ≥80%       │   └─────────────┘   └───────────────┘
                              │  coverage)      │   │  resolved or max  │         │                  │
                              └─────────────────┘   │  iterations)      │         ▼                  ▼
                                                    └───────────────────┘   Quality checklists   Strategic artifacts
                                                                            (per-domain + summary) + [REQUIRES INPUT]
```

**After extract completes:**

1. Run `/speckit.echelon.re-retarget` for guided prompts to fill decisions
2. Or manually edit the `[REQUIRES INPUT]` sections in strategic artifacts
3. Run `/speckit.echelon.re-plan-all` to generate per-domain plans and tasks

## Prerequisites

1. You are in the root of the codebase to analyze
2. Spec-kit is initialized (`.specify/` directory with templates)
3. Git is available (for history extraction)

## User Input

$ARGUMENTS

## Output Structure

Specs are created directly in `specs/` folder, compatible with spec-kit conventions.

**Auto-numbering**: Detects highest existing spec ID in `specs/` and numbers migration specs from there.

```text
specs/
│
├── {existing specs...}               # Pre-existing spec-kit specs (untouched)
│   ├── 001-feature-auth/
│   ├── 002-feature-dashboard/
│   └── ...
│
├── 000-re-overview/                  # Strategic artifacts (fixed ID 000)
│   ├── overview.md                   # Migration summary, dependency graph
│   ├── checklist.md                  # Cross-domain quality checklist
│   ├── constitution.md               # Legacy analysis + target principles [REQUIRES INPUT]
│   ├── migration-strategy.md         # 6R/7R analysis, waves, rollback
│   ├── risk-matrix.md                # Risk inventory and mitigation [REQUIRES INPUT]
│   ├── gap-analysis.md               # Current vs target gaps
│   ├── coverage-report.md            # File coverage analysis
│   ├── validation-report.md          # Quality check results
│   └── adrs/                         # Architecture Decision Records [REQUIRES INPUT]
│       ├── 001-target-language.md
│       ├── 002-database-choice.md
│       └── ...
│
├── Per-Domain Specs (numbered from highest existing + 1):
│   ├── 003-re-core-framework/
│   │   ├── spec.md                   # What to build
│   │   └── checklist.md              # Domain quality checklist
│   ├── 004-re-data-access/
│   │   ├── spec.md
│   │   └── checklist.md
│   ├── 005-re-reference-data/
│   │   ├── spec.md
│   │   └── checklist.md
│   └── ...
│
.specify/echelon/re/
└── analysis.json                     # Raw extracted data (single-repo)
```

**Polyrepo layout** (when `repos-manifest.json` has `repo_count > 1`):

```text
specs/
├── 000-re-overview/
│   ├── overview.md
│   ├── cross-repo-map.md             # Cross-repo dependency and integration map
│   └── ...
│
├── {start_id}-re-{repo-a}-{domain}/  # Repo-prefixed spec IDs
│   ├── spec.md
│   └── checklist.md
├── {start_id+1}-re-{repo-b}-{domain}/
│   ├── spec.md
│   └── checklist.md
└── ...

.specify/echelon/re/
├── repos-manifest.json               # Discovered repo list and mode
├── cross-repo.json                   # Cross-repo dependency data
├── {repo-a}/
│   └── analysis.json                 # Per-repo raw extracted data
└── {repo-b}/
    └── analysis.json
```

**Naming convention**: All reverse-engineered specs use `NNN-re-{domain}` format for easy identification. When `repo_count > 1`, domain specs are prefixed with the repo name: `NNN-re-{repo}-{domain}`.

## Steps

### Step 1: Introduction

Display to the user:

```text
==================================
Reverse Engineering: Extract
==================================

This will analyze your codebase and generate:

Strategic Artifacts (in specs/000-re-overview/):
  - overview.md           (migration summary, dependency graph)
  - constitution.md       (legacy analysis + target principles)
  - migration-strategy.md (6R/7R analysis, waves)
  - risk-matrix.md        (risk assessment)
  - gap-analysis.md       (current vs target gaps)
  - adrs/                 (architecture decisions)

Domain Specifications (in specs/NNN-re-{domain}/):
  - spec.md               (what to build, per domain)

Specs are numbered from highest existing ID + 1.

After completion, fill [REQUIRES INPUT] sections, then run:
  /speckit.echelon.re-plan-all
```

### Step 2: Verify Spec-Kit

Check if `.specify/` directory exists in the current working directory. If not, display a warning:

```text
Warning: Spec-kit not initialized in this project.
Run 'specify init' to initialize, or outputs will use default templates.
```

Then proceed regardless (the extension works without spec-kit initialization).

### Step 2.5: Discover Repos (Polyrepo Detection)

Run `discover-repos.sh` to detect whether the target is a monorepo or a polyrepo:

```bash
"$EXTENSION_PATH/scripts/bash/re/discover-repos.sh" ".specify/echelon/re/repos-manifest.json"
```

Read the resulting `.specify/echelon/re/repos-manifest.json`:

- If `repo_count == 1` — single repo detected.
- If `repo_count > 1` — multiple repos detected:
  1. Resolve layered config with `specify extension config resolve echelon --format json` and read `polyrepo.include` / `polyrepo.exclude` overrides.
  2. Filter the manifest: remove repos that match `exclude` patterns and retain only those matching `include` patterns (if specified).
  3. Display the filtered repo list to the user before proceeding:

```text
Multiple repositories detected ({N} repos). Repositories to process:
  - {repo-name-1}  ({repo-path-1})
  - {repo-name-2}  ({repo-path-2})
  ...

To include/exclude repos, edit echelon-re-config.yml (repos.include / repos.exclude).
```

### Step 3: Run Analysis

**MANDATORY — This step is NOT optional.** Execute `/speckit.echelon.re-analyze` to extract structured data. ONLY after the command returns (success OR error) do you proceed.

**Output gate**: After the command returns, verify:

- `.specify/echelon/re/analysis.json` exists (aggregate summary)
- Each repo in the manifest has `.specify/echelon/re/{repo-name}/analysis.json`
- If `repo_count > 1`, `.specify/echelon/re/cross-repo.json` also exists

If any required file is missing, the step FAILED — do NOT proceed to Step 4.

Creates `.specify/echelon/re/analysis.json` with:

- File structure and language breakdown
- Dependencies from package manifests
- Git history (commits, contributors, hotspots)
- CI/CD and infrastructure configs

### Step 4: Generate Specifications

**MANDATORY — This step is NOT optional.** Execute `/speckit.echelon.re-specify` to generate domain specifications. ONLY after the command returns (success OR error) do you proceed.

**Output gate**: After the command returns, verify at least one `specs/NNN-re-*/spec.md` file exists using Glob. If none exist, the step FAILED — do NOT proceed to Step 5.

Creates:

- `specs/000-re-overview/overview.md` - Migration overview with dependency graph
- `specs/NNN-re-{domain}/spec.md` - Detailed specs for each functional domain

**Numbering**: Automatically detects highest existing spec ID in `specs/` and starts domain specs from the next number.

### Step 5: Verify Coverage & Expand

**MANDATORY — This loop is NOT optional. You MUST invoke `/speckit.echelon.re-verify` at least once.**

**Loop enforcement**: You may only claim the coverage threshold is met if the verify command returned a coverage percentage at or above the threshold. You may NOT estimate coverage yourself or skip verification.

1. Execute `/speckit.echelon.re-verify` to check coverage — MUST be invoked and return before evaluating threshold
2. If the returned coverage is below threshold:
   - Review suggested new domains from orphan clusters
   - Execute `/speckit.echelon.re-expand` to fill gaps — MUST be invoked and return
   - Repeat verification (go back to step 1)
3. **Precondition for exiting loop**: The most recent verify invocation returned coverage at or above the threshold

**Output gate**: After the loop exits, verify `specs/000-re-overview/coverage-report.md` exists.

```text
Coverage Loop:
  respecify → verify → below threshold? → expand → verify → ...
                            ↓
                       threshold met → continue to validate
```

### Step 6: Validate Specifications

**MANDATORY — This step is NOT optional.** Execute `/speckit.echelon.re-validate` to check spec quality and auto-resolve issues. ONLY after the command returns do you proceed.

**Loop enforcement**: The validate command handles its own iteration loop internally. You MUST invoke it and wait for it to return. You may NOT claim validation is complete without invoking it.

**Output gate**: After the command returns, verify `specs/000-re-overview/validation-report.md` exists. If it does not exist, the step FAILED — do NOT proceed to Step 7.

The validate command internally:

1. Scans specs for ambiguity, underspecification, duplication, inconsistency
2. Attempts auto-resolution by checking source code (code is truth)
3. Updates specs with resolutions where possible
4. Flags unresolvable items with `[NEEDS CLARIFICATION: ...]`
5. Checks resolution rate - if below threshold, runs deeper analysis

```text
Validation Loop:
  Iteration 1 (Basic)    → Iteration 2 (Deep)     → Iteration 3 (Extended)
  constants, configs       function bodies, tests   cross-file analysis
       ↓                         ↓                         ↓
  65% resolved           78% resolved             85% resolved ✓
```

**Auto-resolution examples:**

| Finding | Auto-Resolution |
|---------|-----------------|
| "fast response" (vague) | Search for timeout constants → "within 500ms" |
| Missing acceptance criteria | Extract from test assertions |
| Incomplete entity fields | Read from source class definitions |
| Terminology drift | Normalize to canonical term from code |

If validate finds issues requiring human input, they are marked in specs and listed in `specs/000-re-overview/validation-report.md`.

### Step 7: Generate Quality Checklists

**MANDATORY — This step is NOT optional.** Execute `/speckit.echelon.re-checklist` to generate quality review checklists. ONLY after the command returns (success OR error) do you proceed.

**Output gate**: After the command returns, verify at least one `specs/NNN-re-*/checklist.md` file exists using Glob. If none exist, the step FAILED — do NOT proceed to Step 8.

**What rechecklist generates:**

1. **Per-domain checklists** (`NNN-re-{domain}/checklist.md`) - Domain-specific quality items
2. **Summary checklist** (`000-re-overview/checklist.md`) - Cross-domain and migration concerns

Checklists are "unit tests for requirements" - they validate whether specs are complete, clear, consistent, and ready for planning. They cover:

- Source evidence quality
- Requirements completeness
- Entity definitions
- Edge cases & error handling
- Cross-domain consistency
- Migration scenarios
- Legacy context

### Step 8: Generate Strategic Artifacts

**MANDATORY — This step is NOT optional.** Execute `/speckit.echelon.re-constitute` to create strategic planning documents. ONLY after the command returns (success OR error) do you proceed.

**Output gate**: After the command returns, verify `specs/000-re-overview/constitution.md` exists. If it does not exist, the step FAILED — do NOT display the Final Summary.

Generates:

| Artifact | Purpose |
|----------|---------|
| `constitution.md` | Legacy analysis, target stack, coding standards |
| `migration-strategy.md` | 6R/7R analysis per domain, migration waves, rollback |
| `risk-matrix.md` | Risk inventory with likelihood × impact, mitigation |
| `gap-analysis.md` | Feature, infrastructure, skills, dependency gaps |
| `adrs/*.md` | Architecture Decision Records for key choices |

### Step 9: Final Summary

```text
Extraction Complete!
====================

Strategic Artifacts (specs/000-re-overview/):
  ✓ overview.md             - Migration summary, dependency graph
  ✓ checklist.md            - Cross-domain quality checklist
  ✓ constitution.md         - Legacy analysis + target principles
  ✓ migration-strategy.md   - 6R/7R analysis, {N} migration waves
  ✓ risk-matrix.md          - {N} risks identified
  ✓ gap-analysis.md         - {N} gaps to address
  ✓ coverage-report.md      - File coverage analysis
  ✓ validation-report.md    - Quality check results
  ✓ adrs/                   - {N} architecture decisions

Domain Specifications ({N} domains):
  ✓ {start_id}-re-core-framework/spec.md + checklist.md
  ✓ {start_id+1}-re-data-access/spec.md + checklist.md
  ✓ {start_id+2}-re-reference-data/spec.md + checklist.md
  ...

Validation Results:
  ✓ {N} issues auto-resolved from code
  ⚠️ {N} items marked [NEEDS CLARIFICATION]

Coverage: {final_coverage}% ({covered}/{total} files)

⚠️  Sections requiring human input:
  - [ ] [NEEDS CLARIFICATION] items in domain specs
  - [ ] Target Technology Stack (constitution.md)
  - [ ] Migration Approach selection (migration-strategy.md)
  - [ ] Risk owners and responses (risk-matrix.md)
  - [ ] ADR decisions (adrs/*.md)

Quality Checklists:
  ✓ {N} per-domain checklists generated
  ✓ Summary checklist at 000-re-overview/checklist.md

[If repo_count > 1, also display:]

Per-Repo Coverage:
  - {repo-a}: {coverage_a}% ({covered_a}/{total_a} files)
  - {repo-b}: {coverage_b}% ({covered_b}/{total_b} files)
  ...
  Aggregate: {aggregate_coverage}% ({total_covered}/{grand_total} files)

Cross-Repo Analysis:
  ✓ cross-repo.json          - {N} cross-repo dependencies detected
  ✓ 000-re-overview/cross-repo-map.md - Cross-repo integration map
    - {N} integration points identified
    - {N} shared dependency clusters

Next steps:
  1. Review quality checklists - validate spec completeness
  2. Run /speckit.echelon.re-retarget for guided decision prompts
     (or manually edit [REQUIRES INPUT] sections)
  3. Address [NEEDS CLARIFICATION] items (see validation-report.md)
  4. Get team approval on ADRs
  5. Run /speckit.echelon.re-plan-all to generate plans and tasks
```

## Three-Phase Workflow

The reverse engineering extension uses a three-phase workflow:

```text
Phase 1: Extract (this command)
  reanalyze → respecify → verify/expand → validate → rechecklist → reconstitute

  Output: specs (auto-resolved) + checklists + strategic artifacts with [REQUIRES INPUT]

Phase 2: Retarget (/speckit.echelon.re-retarget)
  Guided prompts to fill:
  - Target technology stack in constitution.md
  - 6R decisions per domain
  - Risk owners and mitigations
  - ADR decisions

  Output: completed strategic artifacts

Phase 3: Plan All (/speckit.echelon.re-plan-all)
  replan → retasks (for all domains)

  Output: per-domain plan.md and tasks.md
```

This separation ensures that planning decisions are informed by completed strategic artifacts.

## Notes

- Each sub-command can be run independently for incremental workflow
- Strategic artifacts contain `[REQUIRES INPUT]` sections that require human decisions
- Do NOT run `plan-all` until strategic artifacts are reviewed and completed
- Analysis data is kept in `.specify/echelon/re/` for reference
