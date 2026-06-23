# Codegen RUNNABLE + Composition Gate — Design

**Status:** design (brainstorming output, pre-plan)
**Date:** 2026-06-22
**Scope:** `echelon codegen` (the SOAR CQ-ISC pipeline) only. NOT `echelon` (Ralph) build.

## Problem

The codegen pipeline scored **Ψ = 1.0 and passed every SOAR gate**
(RE → DECOMPOSE → IMPLEMENT → GATE → TEST → SECURITY → DELIVER) yet delivered a
frontend that **could not boot**: it produced 19 high-quality, tested feature
components but no `index.html`, no `main.tsx`, and a stub `App.tsx`
(`<main>echelon</main>`). The deliverable built (tsc + vite) and even served
HTTP 200 with a non-empty body — so a naive smoke check would have passed it too.

Two complementary holes:

1. **Composition is not a produced deliverable.** DECOMPOSE never emits an
   entry-point / composition task, so nothing owns wiring the parts into a
   runnable whole. "All 40 components are high quality" ≠ "the app runs."
2. **No gate verifies the whole runs.** GATE scores code quality (Ψ); TEST runs
   unit tests of the *parts*; DELIVER packages. Nothing builds-and-boots the
   composed whole, so a perfect score on a non-rendering deliverable is possible.

Root cause: the quality signal validates *parts*, never the *whole*.

## Goal

Make a **runnable, composed whole** a first-class, gated deliverable of the
codegen pipeline — so the pipeline cannot pass while shipping something that
does not boot. Close the blind spot deterministically and requirement-traceably,
without depending on the agent "remembering" to wire things up.

## Decisions (locked during brainstorming)

1. **Runnable contract is declared in RE** — a machine-checkable artifact, not
   guesswork or auto-detection. Fits SOAR's declared-WME style and traces to
   requirements.
2. **Composition is an auto-injected, mandatory terminal task** in DECOMPOSE,
   depending on all feature tasks (uses the existing `CodeTask.depends_on` +
   dependency-gated scheduling). Guaranteed present; never relies on the agent.
3. **Tiered assertion strength** — L1 (hard) = the app boots **and at least one
   designated primary surface actually renders**; L2 (scored, ramping) = the
   breadth of the remaining declared surfaces. L1 must include a primary surface
   (not mere liveness) because the motivating stub *boots and serves HTTP 200* —
   liveness alone would pass it. L1 catches "boots but hollow" for the one
   primary surface now; L2 hardens breadth over time. (Design review correction —
   see "Assertion-strength reconciliation".)
4. **A new RUNNABLE phase after TEST** executes the contract on the composed
   whole; L1 failure re-dispatches the composition task; DELIVER is blocked
   until L1 passes.

### Assertion-strength reconciliation (design-review correction)

The first draft made L1 pure liveness (boot + HTTP 200 + non-empty body) and L2
all surface-presence (advisory). Review caught that this **does not catch the
motivating stub**: the stub boots and serves a non-empty shell, so it passes a
liveness-only L1 and only fails advisory L2 — i.e. it would still ship. The fix:
**L1 = liveness AND one mandatory `primary_surface`**; L2 = the breadth of
remaining surfaces (still ramping). The hard gate now catches a hollow app via
its one primary surface from day one; L2 widens coverage over time. (And for
SPAs the surface check must use a headless browser — see the probe families.)

## Architecture & data flow

```
RE ───────────► emits runnable_contract into codegen-state.json + WME
                  { kind, build, start, liveness, primary_surface, surfaces[] }
DECOMPOSE ─────► auto-appends one mandatory COMPOSE task (numeric id, e.g. T-999),
                  depends_on = [every feature task_id]
IMPLEMENT ─────► builds feature tasks; COMPOSE becomes next_ready ONLY after all
                  features are DONE → produces entry point + wiring last
GATE ──────────► (unchanged) Ψ ≥ 0.70 — quality of the parts
TEST ──────────► (unchanged) tier-1 unit tests — the parts
RUNNABLE ◄─────► NEW skill-layer phase (mirrors SECURITY/6b, NOT the Ψ gate):
                  L1 (hard):   build → start → assert liveness AND primary_surface
                               (kind=spa → headless-browser probe; ephemeral sandbox+port)
                  L2 (scored): remaining surface assertions against the running whole
                  L1 fail → reopen COMPOSE (→ IMPLEMENT), capped → ESCALATE
SECURITY ──────► (unchanged)
DELIVER ───────► BLOCKED unless runnable_gate == pass
```

The `runnable_contract` is the single source of truth: RE *declares* what "runs"
means, DECOMPOSE *guarantees* something produces the runnable whole, RUNNABLE
*verifies* it, DELIVER *refuses* to ship otherwise.

## Codebase-fit (validated against the pipeline)

- **`CodeTask.depends_on` exists** (`src/codegen/decompose/task_queue.py:75`) and
  scheduling is dependency-gated: `are_dependencies_met()` + `next_ready()` only
  surface a task once all its deps are `DONE`. The terminal COMPOSE task is thus
  *structurally* forced to run last — not by insertion order.
- **`task_id` must match `^T-\d{3,}$`** — the COMPOSE task uses a reserved numeric
  id (e.g. `T-999`) with `scope: "composition"`; `"T-COMPOSE"` is invalid.
- **codegen-state.json is schema-permissive** — adding `runnable_contract`,
  `runnable_gate`, and `runnable_surface_score` is safe.
- **RUNNABLE is skill-layer, not the Ψ gate.** `codegen gate` routes through
  `phase_gate.PhaseGateRunner`, whose `_PHASES` is
  `[RE,DECOMPOSE,IMPLEMENT,GATE,TEST,DELIVER]` — `--phase RUNNABLE` resolves to
  `UNKNOWN`. SECURITY (6b) already runs as a skill-layer phase outside this enum;
  RUNNABLE follows that precedent: a `codegen-6c-runnable.md` phase spec that runs
  the contract as bash assertions and writes results to state. The Python
  `_PHASES` enum is intentionally left unchanged (future consolidation).
- **Failure routing is skill-layer reopen.** The Python engine's RETRY/ESCALATE
  `return current` (stay in phase); there is no built-in jump to IMPLEMENT. The
  reopen (set COMPOSE `pending` → IMPLEMENT) is a skill-layer behavior, consistent
  with existing reopen.

## Components

### 1. The runnable contract (new artifact)

Written to `codegen-state.json` and injected as a WME by RE:

```yaml
runnable_contract:
  kind: spa | service | cli | library      # the project's runnable shape
  build:   "<cmd>"                          # required (e.g. "pnpm -r build")
  start:   "<cmd> | null"                   # null for cli/library
  probe:   browser | http | exec            # probe family (see below); REQUIRED for kind=spa => browser
  liveness: "<deterministic assertion>"     # L1 part A: process up / exit 0 / HTTP 200
  primary_surface:                          # L1 part B — REQUIRED: one must-render outcome
    req: FR-001
    assert: "<the single highest-value spec outcome, observable in the running whole>"
  surfaces:                                 # L2 scored, ramping; the remaining breadth
    - req: FR-003
      assert: "<observable outcome>"
```

`build`, `liveness`, and `primary_surface` are mandatory. **L1 (hard) = `liveness`
AND `primary_surface`** — not liveness alone, because the motivating stub passes
liveness. **L2 (scored)** = `surfaces[]`. All asserts cite REQ ids, so the gate is
requirement-traceable.

**Probe families (`kind` → how `assert` is evaluated):**
- `kind: spa` → **`probe: browser`**. SPAs render client-side: `curl` returns only
  the empty `<div id="root">` shell — identical for a stub and the real app, so an
  HTTP-body assertion is meaningless. SPA asserts MUST be evaluated against the
  rendered DOM via a **headless browser** (Playwright). This is the motivating
  case; getting it wrong would falsely pass the stub. (Cost note: Playwright is
  heavy and off-by-default in the harness — the RUNNABLE phase provisions it for
  `kind: spa`.)
- `kind: service` → `probe: http` (curl/HTTP assertions on JSON/HTML responses).
- `kind: cli | library` → `probe: exec` (`--help` exit 0 / a smoke import script).

### 2. RE emission

`codegen-1-re.md` (+ a contract schema/validator under `src/codegen/`): after
retrieving requirements, RE derives the contract — `kind` and `build`/`start`/`probe`
from the spec's stack and the REQ `OUTPUT:` lines, the L1 `success` assertion, and
L2 `surfaces` from the highest-value REQ OUTPUTs. Emitting a valid contract
(build + success present) is a phase deliverable: no contract → RE does not advance.

### 3. DECOMPOSE injection

`codegen-2-decompose.md` + `src/codegen/decompose/task_queue.py`: after the LLM
produces the feature queue, DECOMPOSE auto-appends exactly one mandatory COMPOSE
task — reserved numeric id, `scope: "composition"`, `depends_on = [every feature
task_id]`, fixed description: *"produce the runnable entry point and wire all
components to satisfy runnable_contract."* Dependency-gated scheduling forces it
last; it is never the agent's responsibility to add.

COMPOSE depends on *all* feature tasks, so if any feature is permanently blocked
(escalates and never reaches `DONE`), COMPOSE never becomes `next_ready` and the
pipeline cannot reach RUNNABLE/DELIVER — correct by construction (an incomplete
app is not composable), but it means a stuck feature surfaces as "COMPOSE never
ran," which the IMPLEMENT/escalation path must report rather than hang silently.

### 4. RUNNABLE phase

New `extension/workflow/phases/codegen-6c-runnable.md`, inserted after TEST,
mirroring SECURITY (6b):

- Loads `runnable_contract`.
- **L1 (hard):** `build` → `start` → assert **`liveness` AND `primary_surface`**
  (the latter via the `kind`'s probe family — browser for `spa`). Both pass →
  `runnable_gate: pass`. Either fails → capture output, fail closed.
- **L2 (scored, ramping):** evaluate each `surfaces[].assert` against the running
  whole; record `runnable_surface_score = passed/total`. Does not hard-block
  initially (the ramp). A config flag promotes L2 to hard once mature.
- **L1 fail:** reopen the COMPOSE task (`pending`, re-dispatch reason = probe
  failure) → IMPLEMENT; capped at `runnable.max_attempts` (default 3) → ESCALATE.
- **L1 pass:** ADVANCE → SECURITY/DELIVER.
- **DELIVER precondition** (`codegen-7-deliver.md`): refuse to package unless
  `runnable_gate == pass`. Because L1 now includes `primary_surface`, this makes
  Ψ=1.0-on-a-stub unshippable (the stub renders no primary surface → L1 fails).

### Execution environment

`build → start → probe` runs in an **ephemeral, self-contained sandbox**, not on
the bare host — codegen otherwise runs host-side, and starting a server + browser
on the host re-opens the operational-fragility class this program already hit
(port collisions, leaked processes, containment). The RUNNABLE phase:
- runs against the composed worktree in a disposable workspace;
- allocates an **ephemeral port** (`$PORT`, OS-assigned) injected into `start`/`probe`;
- wraps `start` in a teardown trap (kill the server + any browser) that fires on
  pass, fail, or timeout — no leaked processes;
- bounds `start` readiness with a timeout before probing.

First cut MAY run on the host inside a strict temp dir + teardown trap if the
Docker sandbox is unavailable, but containerized execution (reusing the harness
`DockerWorktreeProvider` pattern) is the target — it is the only way to keep the
SPA browser probe and server hermetic.

### Known ceiling — the contract is LLM-authored

Determinism lives in *executing* the contract, not *authoring* it. RE (an LLM)
can still write a weak `primary_surface`/`surfaces` assertion, which would let a
hollow app through. This gate therefore *raises the floor* (an explicit,
executed, requirement-traced runnable check) but does not make spec→runnable
fully agent-independent. Mitigations: `primary_surface` is mandatory and must
cite a REQ id; the anti-regression test guards the canonical stub; L2 breadth and
(later) L2-hard reduce reliance on a single assertion.

## Failure handling (fail-closed)

- L1 fail → bounded reopen→rebuild→re-verify loop; exhaustion → ESCALATE, DELIVER
  blocked. Config `runnable.on_exhausted` defaults to `block` (a non-bootable app
  is not shippable; unlike WS3's `warn`).
- Missing/invalid contract at RUNNABLE → ESCALATE, never silent-pass (fail-closed).
- L2 never blocks initially; a config flag can later promote it to hard.
- `kind=cli|library`: `start: null`; probe = `--help` exit 0 / import succeeds —
  the gate adapts, no server assumed.

## Testing

- **Unit:** contract schema validation (build + success required); DECOMPOSE
  injects exactly one COMPOSE task with a valid numeric id and `depends_on` = all
  features; reopen-on-fail flips COMPOSE to `pending`.
- **Integration:** fixture spec → RE emits contract → queue ends with COMPOSE
  (`next_ready` only after features DONE) → RUNNABLE L1 pass and fail paths →
  DELIVER blocked when `runnable_gate != pass`.
- **Anti-regression (headline):** a deliberately-stubbed app (feature components
  present, `App.tsx` = `<main>echelon</main>`) MUST FAIL the RUNNABLE gate **at
  L1** — it boots and serves HTTP 200 (passes `liveness`) but renders no
  `primary_surface`, so L1 fails and DELIVER is blocked. This is the precise bug
  Ψ = 1.0 missed; the test proves L1 — not just L2 — catches it. For `kind: spa`
  the assertion runs through the headless-browser probe (a `curl` body check
  would *not* distinguish the stub).

## Scope boundaries (out of scope)

- The Python `_PHASES` enum is not changed (RUNNABLE is skill-layer, mirroring
  SECURITY) — possible future consolidation.
- The default Ralph build strategy's 7/40 task-progress convergence gap — separate.
- L2 surface-presence as a hard gate (it is scored/ramping; hardening is follow-on).
- Visual / pixel fidelity — L1 asserts a primary surface *renders/responds*, L2
  asserts the breadth is *present*; neither judges design correctness.
- Exotic stacks beyond `{spa, service, cli, library}` fall back to L1 build+probe
  with an explicit warning.

## Risks

- **RE under-specifies the contract** (weak `primary_surface`/`surfaces`) → a
  hollow app slips through. This is the known ceiling above. Mitigation:
  mandatory `primary_surface` citing a REQ id; the anti-regression test guards the
  canonical stub; L2 breadth + later L2-hard reduce single-assertion reliance.
- **SPA client-side rendering** → `curl` can't see rendered content (stub and real
  app return the same shell). Mitigation (resolved in design): `kind: spa` uses a
  headless-browser probe against the rendered DOM, never an HTTP-body check.
- **Flaky start/probe** (ports, timing, browser startup) → false L1 failures.
  Mitigation: ephemeral OS-assigned port, bounded readiness wait + teardown trap,
  `kind`-specific recipes, bounded retries.
- **Two-layer phase model drift** (skill specs vs Python `_PHASES`). Mitigation:
  RUNNABLE deliberately follows the SECURITY precedent and stays skill-layer; the
  enum divergence is documented, not widened.
