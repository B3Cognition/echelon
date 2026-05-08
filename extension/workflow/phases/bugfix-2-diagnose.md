# Phase: bugfix-2-diagnose
# Source: echelon.bugfix.md §Step 2 — speckit-echelon-debugger (DEBUGGER) Root Cause Analysis
# Agent: speckit-echelon-debugger (DEBUGGER)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-debugger (DEBUGGER)

---

## Step 2: speckit-echelon-debugger (DEBUGGER) — Root Cause Analysis

Dispatch `agents/build/debugger.md` with:

- The user's `description`
- `spec.md`
- The relevant source files from Step 1
- `deploy-state.json`

The speckit-echelon-debugger (DEBUGGER) must produce:

- Exact root cause (file + line + mechanism — not a guess)
- Minimal fix description (what changes and why — not how to implement it)
- Risk surface (what else could break when this changes)

Store as `{debugger_report}`.
