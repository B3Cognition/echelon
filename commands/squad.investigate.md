---
description: "Trigger SCIENTIST to investigate a specific question"
---

## User Input

$ARGUMENTS

---

## Overview

Dispatch the SCIENTIST agent to investigate a specific question using the full scientific method. The SCIENTIST will research, grade evidence, form hypotheses, run experiments where feasible, and produce actionable recommendations.

---

## Step 1: Validate Input

If `$ARGUMENTS` is empty or missing, report **"Please provide a question to investigate. Usage: /speckit.squad.investigate <your question>"** and stop.

---

## Step 2: Check for Active Run

Read `.specify/squad/state.json`.

- If the file exists and has an active run: use that run's spec directory for context and output.
- If no active run: create a standalone investigation directory at `.specify/specs/investigation-{timestamp}/`. The SCIENTIST can still operate without a full squad run.

Extract the spec directory path for subsequent steps.

---

## Step 3: Gather Context

Read relevant artifacts from the spec directory (if they exist):
- `spec.md` -- requirements context
- `assumptions.md` -- current assumptions relevant to the question
- `unknowns.md` -- existing unknowns list
- `plan.md` -- architecture context
- `research.md` -- existing research to avoid duplication
- `reasoning-journal.json` -- decision history

Also read:
- `.specify/extensions/cognitive-squad/templates/evidence-grades.md` -- grading reference

---

## Step 4: Dispatch SCIENTIST

Read the SCIENTIST agent prompt from `.specify/extensions/cognitive-squad/agents/specialists/scientist.md`.

Use the **Agent tool** to dispatch SCIENTIST as a subagent:

- **prompt:** Read the file `.specify/extensions/cognitive-squad/agents/specialists/scientist.md` for your complete instructions. You are the SCIENTIST. Investigate this specific question: **"{$ARGUMENTS}"**. Follow the full 8-step scientific method: (1) QUESTION -- formalize the question with success criteria, (2) RESEARCH -- search for existing evidence using web search, docs, codebase, (3) EVALUATE -- grade every source A-E per `templates/evidence-grades.md`, (4) HYPOTHESIZE -- form testable hypotheses, (5) EXPERIMENT -- if feasible, run experiments using git worktree via `scripts/bash/setup-worktree.sh`, (6) MEASURE -- collect data from experiments, (7) SYNTHESIZE -- combine all evidence into findings, (8) RECOMMEND -- provide actionable recommendations with confidence levels. Here is your context pack: [include all gathered artifacts]. Produce outputs in `.specify/specs/{spec_dir}/`. Append entries to `reasoning-journal.json`.
- **description:** "SCIENTIST: investigating -- {$ARGUMENTS truncated to 60 chars}"

---

## Step 5: Verify Outputs

After the subagent completes, verify these files were created or updated in the spec directory:

1. **`investigation/{topic-slug}.md`** -- full investigation report following the 8-step method
2. **`evidence-grades.md`** -- graded evidence sources (A-E)
3. **`experiment-results.md`** -- experiment data (if experiments were run)
4. **`recommendations.md`** -- actionable recommendations with confidence levels
5. **`knowledge-gaps.md`** -- remaining unknowns after investigation

If any are missing, log which outputs were not produced.

---

## Step 6: Update State

If an active squad run exists, update `.specify/squad/state.json`:
- Add `"SCIENTIST"` to `active_specialists` if not already present
- Update `updated_at` timestamp

Verify that `reasoning-journal.json` has new SCIENTIST entries. If not, append a MANAGER entry:

```json
{
  "type": "investigation",
  "agent": "MANAGER",
  "timestamp": "{ISO-8601}",
  "content": "SCIENTIST dispatched for: {$ARGUMENTS}. See investigation/ for outputs."
}
```

---

## Step 7: Report

Print summary:

```
============================================
  SCIENTIST Investigation Complete
============================================

Question:        {$ARGUMENTS}
Evidence grades: {count of A-B sources} strong, {count of C-E} weaker
Experiments:     {count run, or "none"}
Confidence:      {overall confidence from recommendations.md}

Key findings:    {1-3 bullet summary from recommendations.md}

Full report:     .specify/specs/{spec_dir}/investigation/{topic}.md
============================================
```
