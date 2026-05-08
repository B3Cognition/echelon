# Phase: codegen-4-gate
# Source: echelon.codegen.md §Phase 4 — GATE CQ-ISC Verification
# Shared: used by both echelon.codegen and echelon.codegenlight
# Read by: speckit-echelon-orchestrator (ORCHESTRATOR) before Phase 4 GATE execution

---

## Phase 4: GATE — CQ-ISC Verification Pass

**Print:** `[CODEGEN] Phase GATE — Running CQ-ISC verification...`

```bash
codegen gate --phase GATE --language <language> --files <all-generated-files> --state-file codegen-state.json
```

For each violation print: `[CODEGEN GATE] CQ-ISC violation: <id> in <file>:<line> — <rule>`
And: `[CODEGEN GATE] Traced to: <req_id> — <content>`

If Ψ ≥ 0.70 and zero violations: SOAR → ADVANCE to TEST.
If violations remain: SOAR → RETRY or ESCALATE.

```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
write_state "codegen_test" "building" $COMPLETED null null
```

**Print:** `[CODEGEN] Phase GATE — COMPLETE ✓ (<violation_count> violations blocked)`
