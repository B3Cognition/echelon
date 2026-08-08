# Phase: re-retarget-1-input
# Read by: echelon.commander (COMMANDER)
# Type: commander_internal — COMMANDER prompts the user directly, no agent dispatch

Guided walkthrough to fill in `[REQUIRES INPUT]` sections in strategic artifacts.

## Step 1: Scan for [REQUIRES INPUT] markers

Use the controller-provided retarget marker inventory. Do not scan or discover
files through provider-native tools.

Report to user: "Found {count} sections requiring your input."

If count is 0: report "All decisions are already filled in. You can proceed to `/speckit.echelon.re-plan-all`." and stop.

## Step 2: Present introduction

```
========================================
Reverse Engineering: Define Target State
========================================

This will guide you through filling in the [REQUIRES INPUT] sections
in your strategic artifacts.

Files to review:
  - re/workspace/strategy/constitution.md       (target technology stack)
  - re/workspace/strategy/migration-strategy.md (6R/7R decisions per domain)
  - re/workspace/strategy/risk-matrix.md        (risk owners, mitigations)
  - re/workspace/strategy/gap-analysis.md       (gap priorities)
  - re/workspace/strategy/adrs/*.md             (architecture decisions)

Sections requiring input: {count}

For each section, I will:
  1. Show you the context from the file
  2. Ask for your decision
  3. Update the file with your answer

You can say "skip" to defer any question and return to it later.
```

## Step 3: Constitution — Target Technology Stack

Read `re/workspace/strategy/constitution.md`. For each `[REQUIRES INPUT]` found in the Target Technology Stack section, present to user:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONSTITUTION: Target Technology Stack
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Legacy stack (extracted from codebase):
  {list the actual values found in constitution.md}

Question {N}:
  {Show the exact [REQUIRES INPUT] label from the file}

  Examples: {provide relevant examples based on the question type}

  Your choice:
```

Record the user's answer. Update `re/workspace/strategy/constitution.md`: replace `[REQUIRES INPUT]` with the user's answer, preserving surrounding markdown structure.

## Step 4: Constitution — Coding Standards

For each `[REQUIRES INPUT]` in the Coding Standards section of `re/workspace/strategy/constitution.md`, present in the same format as Step 3.

## Step 5: Migration Strategy — 6R/7R Decisions

Read `re/workspace/strategy/migration-strategy.md`. For each domain with a `[REQUIRES INPUT]` on its migration strategy:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MIGRATION STRATEGY: {domain-name}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Extracted recommendation: {recommendation from file}
Rationale: {rationale from file}

Do you agree with this approach, or choose a different 6R/7R strategy?

  1. Rehost       (lift-and-shift)
  2. Replatform   (lift-and-reshape)
  3. Repurchase   (replace with SaaS)
  4. Refactor     (significant changes, preserve structure)
  5. Retire       (decommission)
  6. Retain       (keep as-is)
  7. Rebuild      (rewrite from scratch)

  Your choice:
  Rationale (optional):
```

Update `re/workspace/strategy/migration-strategy.md` with the user's choice.

## Step 6: Risk Matrix — Risk Owners and Mitigations

Read `re/workspace/strategy/risk-matrix.md`. For each `[REQUIRES INPUT]` on risk owner or mitigation, present the risk row and ask:
1. Who owns this risk? (person or team name)
2. What is the mitigation plan?

Update `re/workspace/strategy/risk-matrix.md` with answers.

## Step 7: Gap Analysis — Gap Priorities

Read `re/workspace/strategy/gap-analysis.md`. For each `[REQUIRES INPUT]` on priority or owner, present the gap and ask:
1. Priority: Critical / High / Medium / Low
2. Target date (optional)
3. Owner (optional)

Update `re/workspace/strategy/gap-analysis.md` with answers.

## Step 8: ADRs — Architecture Decision Records

Read each `re/workspace/strategy/adrs/*.md` file. For each `[REQUIRES INPUT]`, present the ADR title, context, and question. Record the user's decision text. Update the ADR file.

## Step 9: Completion summary

After processing all questions (or when the user says "done"), the controller
rebuilds the marker inventory from the canonical strategy paths. Use its count
as `REMAINING`; do not infer completion from the conversation.

Report:
```
Retargeting complete.
Remaining [REQUIRES INPUT] markers: {REMAINING}

{if REMAINING == 0}
All decisions filled. Run /speckit.echelon.re-plan-all to generate per-domain plans.

{if REMAINING > 0}
{REMAINING} decisions deferred. You can run /speckit.echelon.re-retarget again
to fill them, or proceed with /speckit.echelon.re-plan-all (planning will work
around the remaining placeholders).
```
