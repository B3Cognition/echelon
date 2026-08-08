# Phase: codegen-1-re
# Source: echelon.codegen.md §Phase 1 — RE Requirements Lookup
# Read by: echelon.orchestrator (ORCHESTRATOR) before Phase 1 RE execution

---

## Phase 1: RE — Requirements Lookup

**Print:** `[CODEGEN] Phase RE — Starting...`

```bash
codegen run --intent "<intent from spec.md title>" --wing $WING --state-file codegen-state.json
```

Print the retrieved requirements block. These are what IMPLEMENT will be verified against.

## Emit the runnable contract

After retrieving requirements, derive the **runnable contract** — the deterministic
declaration of what "this app runs" means — and write it into `codegen-state.json`
under `runnable_contract`. It is mandatory: RE does not advance without a contract
that validates.

- `kind`: `spa` | `service` | `cli` | `library` (from the spec's stack/shape).
- `build`: the build command. `start`: the run/serve command (`null` for cli/library).
- `liveness`: a deterministic up-check (HTTP 200 / process exit 0).
- `primary_surface`: the SINGLE highest-value REQ `OUTPUT` that MUST render/respond
  in the running whole — `{req: <FR-id>, assert: <observable check>}`. This is what
  makes L1 catch a hollow app; liveness alone is not enough.
- `surfaces[]`: the next most important REQ OUTPUTs (L2 breadth).
- For `kind: spa`, surface asserts are evaluated in a headless browser, so phrase
  them as rendered-DOM observations, not HTML-string matches.

```yaml
runnable_contract:
  kind: spa
  build: "pnpm -r build"
  start: "serve packages/web/dist on $PORT"
  liveness: "HTTP 200 at /"
  primary_surface:
    req: FR-001
    assert: "the run catalog renders at least one row"
  surfaces:
    - req: FR-006
      assert: "the phase graph renders nodes"
```

Self-validate before advancing:

```bash
python3 -c "import yaml,sys; from codegen.schema.runnable_contract import parse_runnable_contract; \
parse_runnable_contract((yaml.safe_load(open('codegen-state.json')) or {}).get('runnable_contract') or {}); \
print('runnable_contract OK')" || { echo '✗ runnable_contract invalid — fix before DECOMPOSE'; exit 1; }
```

ALWAYS emit a `runnable_contract` whose `primary_surface` cites a real REQ id.
NEVER advance to DECOMPOSE without a contract that `parse_runnable_contract` accepts.

**Write state checkpoint:** `current_phase: "DECOMPOSE"`

```bash
write_state "codegen_decompose" "building" 0 null null
```

**Print:** `[CODEGEN] Phase RE — COMPLETE ✓`
