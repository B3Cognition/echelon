# Phase: bugfix-4-spec-compliance
# Source: echelon.bugfix.md §Step 4 — SPEC GUARD Scope Validation
# Agent: SPEC_GUARD
# Read by: COMMANDER before dispatching SPEC GUARD

## Step 4: SPEC GUARD — Scope Validation

Dispatch `agents/build/spec-guard.md` with:

- `spec.md`
- `coverage-map.md`
- `{debugger_report}` — the proposed fix scope

The SPEC GUARD confirms the fix is within the spec boundary: it addresses a real spec requirement and doesn't silently expand scope. If the fix requires changes outside the spec, it must say so explicitly.

Store as `{spec_guard_report}`.
