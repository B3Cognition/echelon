# Phase: bugfix-2-diagnose
# Source: echelon.bugfix.md §Step 2 — DEBUGGER Root Cause Analysis
# Agent: DEBUGGER
# Read by: COMMANDER before dispatching DEBUGGER

---

## Step 2: DEBUGGER — Root Cause Analysis

Dispatch `agents/build/debugger.md` with:

- The user's `description`
- `spec.md`
- The relevant source files from Step 1
- `deploy-state.json`

The DEBUGGER must produce:

- Exact root cause (file + line + mechanism — not a guess)
- Minimal fix description (what changes and why — not how to implement it)
- Risk surface (what else could break when this changes)

Store as `{debugger_report}`.
