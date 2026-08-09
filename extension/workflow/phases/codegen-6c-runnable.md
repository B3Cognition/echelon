# Phase: codegen-6c-runnable
# Source: design 2026-06-22-codegen-runnable-composition-gate
# Read by: echelon-orchestrator before Phase 6c RUNNABLE (echelon.codegen only)

## Phase 6c: RUNNABLE — static composition probe

**Print:** `[CODEGEN] Phase RUNNABLE — Verifying build plus static feature composition...`

Runs AFTER SECURITY, BEFORE DELIVER. Skill-layer phase (NOT the Ψ `codegen gate`).
Execute in an ephemeral workspace. For SPA projects this gate performs a build
and static component-composition probe; it does NOT start a browser, observe a
rendered page, call a backend, or prove real runtime behavior. Higher-fidelity
runtime/browser verification is a future gate, not this one.

1. Load `runnable_contract` from `codegen-state.json`. Missing/invalid → HALT + escalate (fail-closed).
2. Run the gate:

```bash
python3 - <<'PY'
import json
from codegen.schema.runnable_contract import parse_runnable_contract
from codegen.runner.runnable_gate import run_runnable_gate, make_probe
state = json.load(open("codegen-state.json"))
contract = parse_runnable_contract(state["runnable_contract"])
result = run_runnable_gate(contract, workspace=".", probe_fn=make_probe(contract.kind))
state["runnable_gate"] = "pass" if result.passed else "fail"
state["runnable_surface_score"] = result.surface_score
json.dump(state, open("codegen-state.json", "w"), indent=2)
print("RUNNABLE", state["runnable_gate"], "L2", result.surface_score, result.failures)
PY
```

3. **L1 = build succeeds AND static composition is real.** Outcome:
   - `runnable_gate: pass` → ADVANCE to DELIVER.
   - `runnable_gate: fail` → **reopen the COMPOSE task** (`T-999` → status `PENDING`) with the
     failure as the re-dispatch reason, route back to IMPLEMENT. Cap at `runnable.max_attempts`
     (default 3); on exhaustion ESCALATE per `runnable.on_exhausted` (default `block`).
4. L2 `runnable_surface_score` is recorded (advisory/ramping); it does not block initially.

ALWAYS block on L1 failure and reopen COMPOSE; the composed entry must build and
statically mount real feature components rather than a shell/stub.
NEVER advance to DELIVER with `runnable_gate != pass`.
NEVER claim RUNNABLE proves the app booted, rendered in a browser, worked with
real data, or exercised cross-service integration.

**Print:** `[CODEGEN] Phase RUNNABLE — COMPLETE ✓ (static composition passed)`
