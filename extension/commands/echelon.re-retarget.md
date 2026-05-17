---
name: speckit.echelon.re-retarget
description: "Fill in target stack decisions and complete strategic artifacts"
behavior:
  execution: isolated
  invocation: automatic
---

# Retarget: Define Target Architecture and Decisions

> **Bash Command Guidelines**: Never use multi-line bash. Chain commands with `&&`. **IMPORTANT**: Do NOT use bash `ls`, `find`, `cat`, `echo`, or `grep` for file exploration - always use the dedicated Glob, Read, and Grep tools instead. Reserve bash only for git commands, `mkdir`, and other system operations.

Guided walkthrough to fill in `[REQUIRES INPUT]` sections in strategic artifacts.

## Purpose

After running `/speckit.echelon.re-extract`, the strategic artifacts contain placeholder sections that require human decisions. This command:

1. Scans strategic artifacts for `[REQUIRES INPUT]` markers
2. Presents each as a guided question
3. Records your answers back into the files
4. Validates completeness before planning phase

```text
Phase 1: extract  → specs + strategic artifacts with [REQUIRES INPUT]
Phase 2: retarget → guided prompts to fill target decisions ← YOU ARE HERE
Phase 3: plan-all → per-domain plans + tasks
```

## Prerequisites

1. Strategic artifacts exist in `specs/000-re-overview/` from `extract` or `reconstitute`:
   - `constitution.md`
   - `migration-strategy.md`
   - `risk-matrix.md`
   - `gap-analysis.md`
   - `adrs/*.md`

## User Input

$ARGUMENTS

## Steps

### Step 1: Locate Strategic Artifacts

```bash
OVERVIEW_DIR="specs/000-re-overview"

if [ ! -f "$OVERVIEW_DIR/constitution.md" ]; then
    echo "Error: Strategic artifacts not found at $OVERVIEW_DIR"
    echo "Run /speckit.echelon.re-extract first"
    exit 1
fi

# Count [REQUIRES INPUT] sections
INPUT_COUNT=$(grep -r "\[REQUIRES INPUT\]" "$OVERVIEW_DIR" --include="*.md" | wc -l)
echo "Found $INPUT_COUNT sections requiring input"
```

### Step 2: Introduction

```text
========================================
Reverse Engineering: Define Target State
========================================

This will guide you through filling in the [REQUIRES INPUT] sections
in your strategic artifacts.

Files to review:
  - constitution.md       (target technology stack)
  - migration-strategy.md (6R/7R decisions)
  - risk-matrix.md        (risk owners, mitigations)
  - gap-analysis.md       (gap priorities)
  - adrs/*.md             (architecture decisions)

Sections requiring input: {count}

For each section, I'll:
  1. Show you the context
  2. Ask for your decision
  3. Update the file with your answer

You can skip any question and come back later.
```

### Step 3: Constitution - Target Technology Stack

Read `constitution.md` and for each `[REQUIRES INPUT]` in the Target Technology Stack section:

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONSTITUTION: Target Technology Stack
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Legacy Stack (extracted):
  - Language: Java 8
  - Framework: Swing
  - Database: Oracle 11g
  - Build: Ant

Question 1 of {N}:

  What is the TARGET LANGUAGE for this migration?

  Consider:
  - Team expertise
  - Hiring availability
  - Ecosystem maturity
  - Performance requirements

  Examples: TypeScript, Python, Go, Rust, Java 17, C#

  Your choice: _________________

  [Skip] [Enter choice]
```

Record answer and update constitution.md:

```markdown
| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | {user_answer} | [REQUIRES INPUT: Why this choice?] |
```

Continue for Framework, Database, etc.

### Step 4: Constitution - Coding Standards

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONSTITUTION: Coding Standards
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Question {N}:

  What TEST COVERAGE threshold should be enforced?

  Legacy coverage: Unknown (no tests found)
  Industry standard: 70-80%

  Options:
  1. 80% (recommended for new projects)
  2. 70% (more pragmatic)
  3. 90% (high reliability requirements)
  4. Custom: ___

  Your choice: _________________
```

### Step 5: Migration Strategy - 6R Decisions

For each domain in `migration-strategy.md`:

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MIGRATION STRATEGY: 6R Decisions
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Domain: 001-core-framework

Current recommendation: Rebuild
Rationale: Tightly coupled to legacy platform

Do you agree with REBUILD for this domain?

  1. Yes, Rebuild (rewrite from scratch)
  2. No, Refactor (significant changes, preserve structure)
  3. No, Replatform (lift-and-reshape)
  4. No, Retain (keep as-is for now)
  5. No, Retire (decommission)

  Your choice: _________________
  Rationale (optional): _________________
```

### Step 6: Risk Matrix - Risk Owners

For each risk in `risk-matrix.md`:

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RISK MATRIX: Assign Owners
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Risk: Data migration integrity
Likelihood: High
Impact: Critical
Score: 20

Who should OWN this risk?

  (Enter team name or person responsible)

  Owner: _________________

What is the MITIGATION strategy?

  Current: [REQUIRES INPUT]

  Suggested mitigations:
  - Parallel run with data comparison
  - Rollback procedures
  - Incremental migration with validation

  Your strategy: _________________
```

### Step 7: ADR Decisions

For each ADR in `adrs/`:

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADR 001: Target Language
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Context:
  Legacy system uses Java 8 with Swing UI.
  Team has mixed experience.

Options presented:
  1. TypeScript + React - Modern web stack, good hiring
  2. Java 17 + Spring - Team familiarity, enterprise support
  3. Go + htmx - Performance, simplicity
  4. Python + FastAPI - Rapid development, data science integration

Trade-offs:
  Option 1: Steep learning curve, rich ecosystem
  Option 2: Lower risk, slower UI development
  Option 3: New paradigm, excellent performance
  Option 4: Slower runtime, great for prototyping

Your DECISION (1-4): _________________

Decision rationale: _________________
```

### Step 8: Gap Analysis - Priorities

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GAP ANALYSIS: Set Priorities
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Gaps identified:

1. Skills Gap: No TypeScript experience
2. Infrastructure Gap: No Kubernetes setup
3. Feature Gap: Missing audit logging
4. Dependency Gap: Oracle → PostgreSQL migration

Rank these gaps by priority (1 = highest):

  Skills Gap:        [ ]
  Infrastructure Gap: [ ]
  Feature Gap:       [ ]
  Dependency Gap:    [ ]
```

### Step 9: Validation Summary

```text
Retarget Complete!
==================

Sections filled: {filled}/{total}

Constitution:
  ✓ Target Language: TypeScript
  ✓ Framework: NestJS
  ✓ Database: PostgreSQL
  ✓ Coverage Threshold: 80%

Migration Strategy:
  ✓ 001-core-framework: Rebuild
  ✓ 002-data-access: Refactor
  ✓ 003-reference-data: Replatform
  ...

Risk Matrix:
  ✓ 8/8 risks have owners
  ✓ 8/8 risks have mitigations

ADRs:
  ✓ ADR-001: Decided (TypeScript)
  ✓ ADR-002: Decided (PostgreSQL)
  ⚠️ ADR-003: Still pending

Remaining [REQUIRES INPUT] sections: {count}

{if count > 0}
Some sections are still incomplete.
Run /speckit.echelon.re-retarget again to fill remaining sections.
{else}
All sections complete! Ready for planning phase.
Next: /speckit.echelon.re-plan-all
{endif}
```

## Skipping Questions

You can skip any question:
- Skipped questions remain as `[REQUIRES INPUT]`
- Re-run `retarget` to fill skipped sections
- `plan-all` will warn about incomplete sections

## Re-running Retarget

Safe to run multiple times:
- Only prompts for remaining `[REQUIRES INPUT]` sections
- Preserves previously filled answers
- Shows summary of what's complete vs pending

## Integration with Workflow

```text
/speckit.echelon.re-extract   → specs + strategic artifacts
/speckit.echelon.re-retarget  → fill target decisions (this command)
/speckit.echelon.re-plan-all  → per-domain plans + tasks
```

## Notes

- All answers are saved directly to the markdown files
- You can also edit files manually if preferred
- ADR decisions are recorded in the standard ADR format
- `plan-all` uses these decisions to generate informed plans
