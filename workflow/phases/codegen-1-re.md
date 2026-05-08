# Phase: codegen-1-re
# Source: echelon.codegen.md §Phase 1 — RE Requirements Lookup
# Read by: speckit-echelon-orchestrator (ORCHESTRATOR) before Phase 1 RE execution

---

## Phase 1: RE — Requirements Lookup

**Print:** `[CODEGEN] Phase RE — Starting...`

```bash
codegen run --intent "<intent from spec.md title>" --wing $WING --state-file codegen-state.json
```

Print the retrieved requirements block. These are what IMPLEMENT will be verified against.

**Write state checkpoint:** `current_phase: "DECOMPOSE"`

```bash
write_state "codegen_decompose" "building" 0 null null
```

**Print:** `[CODEGEN] Phase RE — COMPLETE ✓`
