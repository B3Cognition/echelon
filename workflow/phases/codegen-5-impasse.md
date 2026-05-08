# Phase: codegen-5-impasse
# Source: echelon.codegen.md §Phase 5 — Conflict Impasse Human Escalation
# Shared: used by both echelon.codegen and echelon.codegenlight
# Read by: speckit-echelon-orchestrator (ORCHESTRATOR) when SOAR detects a conflict impasse (INV-008)

---

## Phase 5: Conflict Impasse — Human Escalation

Fires when SOAR detects a conflict impasse (INV-008).

Write `./codegen-impasse.md` with conflicting constraints, code location, and resolution options. Print the impasse report. Halt. Wait for human response.

Record in EPMEM: `^source soar ^operator ESCALATE ^resolution pending`.
