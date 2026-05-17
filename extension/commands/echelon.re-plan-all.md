---
name: speckit.echelon.re-plan-all
description: "Generate plans and tasks for all domains - Phase 2 of reverse engineering workflow"
behavior:
  execution: isolated
  invocation: automatic
---

# Plan All: Generate Per-Domain Plans and Tasks

> **Bash Command Guidelines**: Never use multi-line bash. Chain commands with `&&`. **IMPORTANT**: Do NOT use bash `ls`, `find`, `cat`, `echo`, or `grep` for file exploration - always use the dedicated Glob, Read, and Grep tools instead. Reserve bash only for git commands, `mkdir`, and other system operations.

Generate `plan.md` and `tasks.md` files for all domains using the completed strategic artifacts.

## Enforcement Rules

> **NEVER skip the replan or retasks sub-command invocations.** Both commands in Steps 3-4 MUST be invoked via the Skill tool and MUST return (success OR error) before proceeding. You may NOT rationalize skipping either step.
>
> **NEVER run retasks without verifying replan produced output.** After replan returns, you MUST verify that at least one `specs/NNN-re-*/plan.md` file exists before invoking retasks.
>
> **Invalid state detection**: If the Final Summary (Step 5) is displayed but any of these are true, the pipeline has a bug:
> - No `specs/NNN-re-*/plan.md` files exist (Step 3 was skipped)
> - No `specs/NNN-re-*/tasks.md` files exist (Step 4 was skipped)

## Purpose

This is Phase 3 of the reverse engineering workflow. After running `/speckit.echelon.re-extract` and filling in the `[REQUIRES INPUT]` sections, run this command to generate implementation plans and task breakdowns for all domains.

```text
Phase 1 (extract):     reanalyze → respecify → verify/expand → validate → rechecklist → reconstitute
                                                                                            │
                                                                                            ▼
                                                                                   Strategic artifacts
                                                                                   with [REQUIRES INPUT]

Phase 2 (retarget):    retarget  ← Guided prompts to fill decisions
                           │
                           ▼
                       Completed strategic artifacts

Phase 3 (plan-all):    replan ──▶ retasks
                          │          │
                          ▼          ▼
                    Per-domain   Per-domain
                      plan.md    tasks.md
```

## Prerequisites

1. Domain specifications exist: `specs/NNN-re-{domain}/spec.md`
2. Strategic artifacts in `specs/000-re-overview/` are **completed** (not just generated):
   - `constitution.md` - Target technology stack filled in
   - `migration-strategy.md` - 6R recommendations reviewed
   - `risk-matrix.md` - Risk owners assigned
   - `adrs/*.md` - Decisions made

**Important**: This command will warn if `[REQUIRES INPUT]` sections are still present in strategic artifacts. Plans and tasks generated without completed constitution will have placeholder decisions.

## User Input

$ARGUMENTS

## Output Structure

```text
specs/
├── 000-re-overview/                  # Input: completed strategic artifacts
│   ├── constitution.md
│   ├── migration-strategy.md
│   ├── risk-matrix.md
│   ├── gap-analysis.md
│   └── adrs/
│
├── {NNN}-re-core-framework/
│   ├── spec.md                       # Input: from extract
│   ├── plan.md                       # OUTPUT: how to build it
│   └── tasks.md                      # OUTPUT: task breakdown
├── {NNN+1}-re-data-access/
│   ├── spec.md
│   ├── plan.md                       # OUTPUT
│   └── tasks.md                      # OUTPUT
└── ...
```

## Steps

### Step 1: Verify Prerequisites

```bash
OVERVIEW_DIR="specs/000-re-overview"
CONSTITUTION="$OVERVIEW_DIR/constitution.md"

if [ ! -f "$CONSTITUTION" ]; then
    echo "Error: Constitution not found at $CONSTITUTION"
    echo "Run /speckit.echelon.re-extract first"
    exit 1
fi

# Check for incomplete sections
if grep -q "\[REQUIRES INPUT\]" "$CONSTITUTION"; then
    echo "⚠️  Warning: constitution.md contains [REQUIRES INPUT] sections"
    echo "   Plans and tasks will have placeholder decisions"
    echo ""
    echo "   Recommended: Fill these sections before proceeding"
    echo "   Continue anyway? (y/n)"
fi

# Find all migration domain directories
DOMAINS=$(ls -d specs/[0-9][0-9][0-9]-re-*/ 2>/dev/null)

if [ -z "$DOMAINS" ]; then
    echo "Error: No migration domain specifications found"
    echo "Run /speckit.echelon.re-extract first"
    exit 1
fi

echo "Found $(echo "$DOMAINS" | wc -l) migration domains to process"
```

### Step 2: Introduction

```text
======================================
Reverse Engineering: Plan All Domains
======================================

This will generate for each domain:
  - plan.md   (implementation approach)
  - tasks.md  (actionable task breakdown)

Using strategic context from:
  - constitution.md       (target stack, coding standards)
  - migration-strategy.md (6R recommendations)
  - risk-matrix.md        (domain-specific risks)
  - gap-analysis.md       (gaps to address)

Domains to process:
  - 001-core-framework
  - 002-data-access
  - 003-reference-data
  ...
```

### Step 3: Generate Per-Domain Plans

**MANDATORY — This step is NOT optional.** Execute `/speckit.echelon.re-plan` to create implementation plans for all domains. ONLY after the command returns (success OR error) do you proceed.

**Output gate**: After the command returns, verify at least one `specs/NNN-re-*/plan.md` file exists using Glob. If none exist, the step FAILED — do NOT proceed to Step 4.

For each domain (`001-core-framework/`, `002-data-access/`, etc.):

- Reads domain `spec.md`
- Uses constitution for target stack decisions
- Uses migration-strategy for 6R recommendation
- Uses risk-matrix for domain-specific risks
- Generates `plan.md` in domain folder

### Step 4: Generate Per-Domain Tasks

**MANDATORY — This step is NOT optional.** Execute `/speckit.echelon.re-tasks` to create task breakdowns for all domains. ONLY after the command returns (success OR error) do you proceed.

**Precondition**: Step 3 MUST have completed successfully and produced plan.md files. You may only enter this step if the output gate in Step 3 passed.

**Output gate**: After the command returns, verify at least one `specs/NNN-re-*/tasks.md` file exists using Glob. If none exist, the step FAILED — do NOT display the Final Summary.

For each domain:

- Reads domain `spec.md` and `plan.md`
- Uses constitution for coding standards
- Generates `tasks.md` with phased task breakdown
- Task IDs follow `[DDD.P.S]` format for cross-domain references

### Step 5: Final Summary

```text
Planning Complete!
==================

Per-Domain Artifacts ({N} domains):
  ✓ 001-core-framework/       - plan.md, tasks.md ({X} tasks)
  ✓ 002-data-access/          - plan.md, tasks.md ({Y} tasks)
  ✓ 003-reference-data/       - plan.md, tasks.md ({Z} tasks)
  ...

Total: {total_tasks} tasks across {N} domains

Task breakdown by phase:
  - Phase 1 (Foundation):   {count} tasks
  - Phase 2 (Core):         {count} tasks
  - Phase 3 (Integration):  {count} tasks
  - Phase 4 (Polish):       {count} tasks

Implementation order (from dependency graph):
  Wave 1: 001-core-framework, 002-data-access
  Wave 2: 003-reference-data, 004-business-logic
  Wave 3: 005-ui-components
  ...

Next steps:
  1. Review per-domain plans and tasks
  2. Adjust effort estimates based on team velocity
  3. Use /speckit.implement per domain for guided implementation
  4. Use /speckit.taskstoissues per domain to create GitHub issues
```

## Integration with Spec-Kit

All outputs work with existing spec-kit commands:

| Command | Usage |
|---------|-------|
| `/speckit.implement` | Run on domain folder for guided implementation |
| `/speckit.taskstoissues` | Create GitHub issues from domain tasks |
| `/speckit.analyze` | Validate spec/plan/tasks consistency |
| `/speckit.clarify` | Identify underspecified areas |

### Working with Domains

```bash
# Implement a specific domain
cd specs/project-migration/001-core-framework
/speckit.implement

# Create issues for a domain
/speckit.taskstoissues

# Or specify path
/speckit.implement --path specs/project-migration/002-data-access
```

## Parallel Team Work

The per-domain structure enables parallel development:

1. **Foundation teams** start on Wave 1 domains (001, 002)
2. **Feature teams** plan ahead using their domain specs
3. **All teams** share the same constitution (consistency)
4. **Dependencies** are tracked in each domain's plan

## Re-running Plan-All

If you update strategic artifacts after initial planning:

1. Make changes to constitution.md, migration-strategy.md, etc.
2. Re-run `/speckit.echelon.re-plan-all`
3. New plans and tasks will be generated using updated context

**Note**: This will overwrite existing plan.md and tasks.md files. If you have manual edits, back them up first.

## Notes

- Requires completed strategic artifacts (from extract phase)
- Will warn if `[REQUIRES INPUT]` sections remain unfilled
- Plans reference the shared constitution for consistency
- Tasks use `[DDD.P.S]` ID format for cross-domain tracking
- Can be re-run after updating strategic artifacts
