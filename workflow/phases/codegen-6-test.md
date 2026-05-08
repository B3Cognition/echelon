# Phase: codegen-6-test
# Source: echelon.codegen.md §Phase 6 — TEST Tier 1 Gate
# Shared: used by both echelon.codegen and echelon.codegenlight
# Read by: ORCHESTRATOR before Phase 6 TEST execution

## Phase 6: TEST — Tier 1 Gate

**Print:** `[CODEGEN] Phase TEST — Running Tier 1 gate (unit tests)...`

```bash
pytest --tb=short --json-report --json-report-file=./codegen-staging/test-results.json 2>&1         # Python
npx vitest run --reporter=json --outputFile=./codegen-staging/test-results.json 2>&1                # TypeScript
go test ./... -json 2>&1 | tee ./codegen-staging/test-results.json                                  # Go
mvn test 2>&1 | tee ./codegen-staging/test-results.log                                              # Java
```

Inject `test-result` WMEs into SOAR.

- All pass: `tier1_gate: "pass"` → ADVANCE to DELIVER
- Any fail: RETRY (back to IMPLEMENT) or ESCALATE

```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
write_state "codegen_deliver" "building" $COMPLETED null null
```

**Print:** `[CODEGEN] Phase TEST — COMPLETE ✓ (Tier 1 gate PASSED)`
