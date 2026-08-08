# Phase: codegenlight-1-re
# Source: echelon.codegenlight.md §Phase 1 — RE Requirements Lookup + Domain Research
# Read by: echelon.orchestrator (ORCHESTRATOR) before Phase 1 RE execution

**Print:** `[CODEGEN] Phase RE — Starting...`

### Step 1.1 — MemPalace requirements retrieval (always runs first)

```bash
# Retrieve requirements relevant to the intent from MemPalace
codegen run --intent "<intent>" --wing $WING --state-file codegen-state.json
```

This triggers the RE phase hook which:
- Searches MemPalace for requirements relevant to the intent
- Injects a `re-requirements-context` WME into SOAR
- Writes retrieved requirements to `codegen-state.json` under `re_phase`
- Records an EPMEM transition (INV-004)

Print the retrieved requirements block — these are what IMPLEMENT will be verified against.

### Step 1.2 — Additional RE (if brownfield target provided)

If a `<target-path>` was given, additionally delegate to echelon.golddigger (GOLDDIGGER) via Agent tool:
```
Agent: Analyze <target_path>.
Produce: glossary.md, mental-model.md, boundaries.md, unknowns.md, assumptions.md in ./codegen-staging/.
Identify stack, test runner, |I_D| estimate with confidence level.
Extract constitution.md if present.
```

If no `<target-path>` and MemPalace returned requirements: **skip domain research** — the spec is the domain model. Go straight to DECOMPOSE.

If no `<target-path>` AND MemPalace returned nothing: treat as greenfield, research the domain:
```
Agent: Intent is: <intent>
Research reference architectures. Produce mental-model.md, boundaries.md in ./codegen-staging/.
Extract acceptance criteria for |I_D| estimate.
```

If still no acceptance criteria: **STOP and ask user** before proceeding.

**Write state checkpoint:** `current_phase: "DECOMPOSE"`

Update harness state:
```bash
write_state "codegen_decompose" "building" 0 null null
```

**Print:** `[CODEGEN] Phase RE — COMPLETE ✓`
