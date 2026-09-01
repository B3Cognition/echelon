# Delivery User-Runnability Gate Design

**Status:** Approved
**Date:** 2026-09-01
**Scope:** Phase B delivery, stack contracts, delivery status, and landing

## Problem

Echelon can converge and land a user-facing application that passes its test
suite but cannot be started and used by a first-time local user. The browser 3D
game exposed the gap: unit, API, Playwright, documentation, and fulfillment
checks passed, yet the landed project had no complete local startup path. Its
database, API, web client, authentication bootstrap, environment variables, and
same-origin routing did not compose into one usable application.

The existing checks establish narrower facts:

- `verify_command` proves the project-defined verification suite passes in the
  sandbox. It does not prove the suite uses real services rather than fixtures,
  mocks, or route interception.
- the documentation gate proves that README and CHANGELOG content is present
  and source-supported. It does not execute the documented first-run journey.
- fulfillment proves the authored requirements. It cannot find an omitted
  operability requirement unless another gate supplies that invariant.
- `harness.app` can start an application for optional visual checks, but visual
  verification is not a general delivery convergence requirement.
- the codegen `RUNNABLE` phase is static, codegen-only, and explicitly does not
  prove browser, backend, data, or cross-service runtime behavior.

The root cause is an acceptance-model boundary: Echelon validates implementation
parts and authored requirements, but Phase B has no authoritative assertion that
the final candidate works as a composed product from a clean environment.

## Goal

Before a runnable product converges or lands, deterministically prove in an
isolated delivery sandbox that a first-time user can provision it, start it,
reach its primary surface, complete one real journey, and stop it using the
declared project contract.

When that proof fails, Echelon must distinguish work missing from the current
specification from intentionally deferred operational scope. It must either
repair the current delivery or present a concrete follow-up specification
proposal. It must never silently declare convergence or silently create new
scope.

## Principles

1. **Execution is authoritative.** An LLM may diagnose failures, but only a
   deterministic sandbox execution may return `runnable`.
2. **The final candidate content is tested.** Evidence is tied to the product
   content fingerprint, candidate-owned contract hash, and resolved stack
   contract hash. Commit identity is recorded for traceability but is not a
   content-equivalence test.
3. **Real composition is required.** A journey using HTTP mocks, intercepted
   routes, hidden test-only authentication unavailable through the documented
   development path, or an in-memory substitute cannot prove a real
   multi-service product.
4. **The stack declares obligations.** A stack identifies whether the target is
   runnable, which infrastructure it needs, and which operational capabilities
   the project must expose. Product repositories provide the concrete commands.
5. **Scope decisions are owner-controlled.** Missing runnability normally
   reopens the current delivery. Product source cannot exempt itself from a
   required gate; deferral requires a controller-owned spec disposition written
   by an explicit owner command.
6. **No host pollution.** Setup, dependencies, browsers, services, probes, and
   teardown run inside the existing delivery sandbox boundary.

## Contract

### Stack declaration

User-facing archetype stacks declare a runnability obligation:

```yaml
runnability:
  classification: user_facing
  policy: required
  runner: linux_container
  capabilities:
    - install
    - provision
    - start
    - readiness
    - primary_journey
    - stop
  persistence_probe: required_when_capability_selected
```

Libraries, schema-only packages, and non-executable artifacts use
`classification: non_runnable`. A project may not downgrade a stack's required
policy implicitly.

The stack schema accepts a runner requirement so platform-specific archetypes
do not silently run under an incompatible verifier. Browser stacks use
`linux_container`. The iOS AR stack requires a future `macos_simulator` runner
and is not enabled as a required gate in the first release.

Resolution unions required capabilities and selects the strongest policy
(`required` over `advisory` over `not_applicable`). Different non-empty runner
requirements are a stack conflict rather than an implicit fallback. Capability
stacks may add required observations: `game-persistence-postgres`, for example,
adds the pre/post-restart Postgres marker observation.

Provisioning remains composable. Capability stacks such as
`game-persistence-postgres` declare required services, environment, readiness,
and satisfiers. The runnability planner consumes that existing information
instead of introducing a second database provisioning model.

### Project declaration

The target repository supplies concrete commands in the dedicated candidate
artifact `.echelon/runnability.yml`. Ralph loads and validates this file directly
from the candidate worktree after every build or fix, so a repair made during the
current delivery takes effect immediately. It is deliberately separate from
`.echelon/config.yml`: creating a target-owned runnability contract must not
change which orchestration root owns stack selection or other delivery policy.

```yaml
schema_version: 1
enabled: true
install_commands:
  - pnpm install --frozen-lockfile
bootstrap_commands:
  - pnpm migrate
  - pnpm seed:dev
start_commands:
  - pnpm start:local
readiness:
  url: http://127.0.0.1:${ECHELON_PORT}/health
  timeout_ms: 120000
identity:
  command: pnpm dev:issue-session -- --player ${ECHELON_MARKER}
  stdout_json:
    token: ECHELON_SESSION_TOKEN
primary_journey:
  kind: browser
  url: ${ECHELON_BASE_URL}
  requirements: [FR-001]
  real_services_required: [web, api, postgres]
  session_storage:
    session-token: ${ECHELON_SESSION_TOKEN}
  steps:
    - action: goto
      path: /
    - action: expect
      selector: canvas
      state: visible
    - action: press
      key: ArrowUp
      repeat: 20
  observations:
    - id: checkpoint-visible
      kind: browser_dom
      selector: '[data-checkpoint-state="owned"]'
      expectation: present
    - id: checkpoint-persisted
      kind: postgres_query
      statement: SELECT player_id FROM checkpoints WHERE player_id = $1
      parameters: ['${ECHELON_MARKER}']
      expectation: one_row_exact
persistence_probe:
  restart_commands:
    - pnpm restart:local
  observations:
    - checkpoint-visible
    - checkpoint-persisted
stop_commands:
  - pnpm stop:local
```

The command and journey vocabulary is ecosystem-neutral. Echelon does not
require pnpm, Docker Compose, HTTP, or Playwright; those are concrete choices
made by a project and its selected stacks. Browser stacks select the built-in
browser journey adapter, while service and CLI stacks may select HTTP and exec
adapters. `${ECHELON_PORT}` is allocated by the harness.
Infrastructure services are not started by these commands. The harness
materializes resolved stack services as attempt-scoped sandbox sidecars, injects
their generated connection environment, and owns their teardown. Project
`bootstrap_commands` perform application-level initialization such as migrations
and seed data against those sidecars. The runnability plan uses the environment
names declared by the resolved provisioner (`DATABASE_URL` in the Postgres game
stack), not verification-only aliases such as `TEST_DATABASE_URL`.

The candidate contract has no scope or policy override. A required stack always
means `current_spec` unless the spec directory contains a controller-owned
`runnability-disposition.json` written by:

```text
echelon spec defer-runnability <spec-id> --reason <owner-approved reason>
```

That pure-Python command records the reason, approval timestamp, target, and
generated follow-up proposal path. Build agents cannot write or modify the
disposition. Without this ledger, a missing or failing required contract remains
current-spec work and blocks convergence and landing.

High-confidence detection may suggest or initialize parts of this contract, but
must not fabricate a passing primary journey. If a required contract remains
incomplete, delivery fails closed with a precise configuration/product gap.

## Execution Model

The new gate runs after normal build verification and fulfillment refresh, then
supplies authoritative evidence to the final documentation gate before
convergence and landing:

```text
build/fix -> sandbox verify -> fulfillment -> USER RUNNABILITY -> docs gate
                                                   | pass             | pass
                                                   v                  v
                                                evidence -> convergence -> land
                                                   |
                                                   | fail/current_spec
                                                   v
                                             bounded repair loop
```

For the final candidate, the harness:

1. creates a fresh delivery sandbox for that candidate; runnability never reuses
   a verifier or visual-test sandbox with pre-existing processes or state;
2. installs dependencies inside the sandbox;
3. materializes every service required by resolved stack capabilities as an
   attempt-scoped sidecar and injects generated connection environment;
4. runs project bootstrap commands, then starts the declared application
   processes with an allocated port;
5. waits for deterministic readiness;
6. executes the primary journey against the started real services;
7. when persistence is required, writes a unique value, restarts the declared
   application boundary, and verifies that value remains;
8. runs teardown on success, failure, timeout, or interruption;
9. records the result and exact candidate fingerprint.

The harness, rather than a project test command, drives the primary journey
through the selected adapter. Every required stack contributes observation kinds
and the candidate contract binds those observations to specific requirement
outcomes. Browser steps and DOM observations run through a harness-controlled
browser context in which route interception APIs are disabled. HTTP observations
are issued by the harness. Postgres observations are executed directly against
the attempt-scoped sidecar rather than through a project helper. Exec journeys
must declare observable output or filesystem assertions in addition to exit
status.

The harness generates `${ECHELON_MARKER}` after bootstrap and makes it available
to an optional documented development-identity command. Structured output from
that command is parsed into explicitly declared variables and injected only into
the harness-controlled journey. This lets an authenticated application expose a
real local-development login path without allowing a hidden test fixture to
stand in for one.

For persistence, the same marker must be present both before and after the
declared application restart while the database sidecar remains running. A
browser route mock, in-memory repository, hidden fixture server, or command that
merely exits zero cannot satisfy both independent observations. A documented
local-development identity bootstrap is permitted; a test-only issuer that is
not available through the documented first-run path is not.

## Evidence

Each attempt writes immutable evidence under the delivery run rather than into
the product repository:

```text
runs/targets/<target>/runs/<build>/evidence/user-runnability/
  report.json
  report.md
  commands.log
```

`report.json` is authoritative and includes:

```yaml
schema_version: 1
status: runnable | not_runnable | blocked | not_applicable
candidate_commit: <sha>
candidate_fingerprint: <sha256>
contract_hash: <sha256>
stack_contract_hash: <sha256>
classification: user_facing
scope: current_spec
stages:
  install: passed
  provision: passed
  start: passed
  readiness: passed
  primary_journey: failed
  persistence: not_run
  teardown: passed
failure_class: missing_local_auth_bootstrap
summary: Local user cannot obtain a session accepted by the API.
evidence:
  - commands.log#primary-journey
```

`candidate_commit` is informational provenance. Evidence may be carried forward
across merge-only or publication commits when the product evidence fingerprint,
normalized candidate-contract hash, and resolved stack-contract hash are all
unchanged. Any content change invalidates the evidence. Landing performs the
same digest validation used by convergence and does not require exact commit
equality when all three authoritative hashes still match.

Command output is bounded and secret-redacted using the existing verification
evidence rules. Reports store command/output digests and redacted tails; they do
not persist generated database credentials, identity keys, session tokens, or
unbounded raw logs.

## Failure Classification And Routing

The deterministic runner owns stage status and raw evidence. A bounded
diagnostic agent may classify a failed execution and recommend repair, but it
cannot change a failed stage to passed.

Current-spec failures enter the existing repair loop with the report as
mandatory context. Stable classes include:

- `contract_missing` or `contract_invalid`;
- `provisioning_failed`;
- `readiness_failed`;
- `primary_journey_failed`;
- `mocked_dependency_detected`;
- `persistence_failed`;
- `teardown_failed`;
- `sandbox_prerequisite_missing`.

Only `sandbox_prerequisite_missing` represents an Echelon/environment blocker.
Missing application commands, local identity bootstrap, service wiring, schema
migration, or persistence behavior are product gaps and remain repairable work.

For an owner-deferred runnability disposition, Echelon writes
`runnability-follow-up.md` containing:

- the failed or absent capabilities;
- observed evidence;
- proposed specification title and intent;
- draft requirements and acceptance criteria;
- affected target and selected stacks;
- the exact command to start a new spec from the proposal.

The diagnostic agent may draft this proposal from deterministic evidence, but a
schema validator checks the artifact and the proposal remains advisory. It does
not change the failed gate, create a specification, or permit landing without
the controller-owned deferral ledger.

## CLI Presentation

`echelon delivery status` adds a concise runnability section:

```text
 user runnable  failed
 stage          primary journey
 reason         missing local authentication bootstrap
 evidence       .../evidence/user-runnability/report.md
 next           delivery will repair this current-spec product gap
```

For owner-deferred scope, `next` identifies the proposal file and an executable
spec-authoring command. For a missing contract, status names the exact required
candidate artifact and fields rather than suggesting a generic resume.

A passing result also shows the first-run commands the user should execute:

```text
 user runnable  passed
 prerequisites  Docker and pnpm 10
 provision      echelon stack provision --target <target>; docker compose up -d
 start          pnpm start:local
 open           http://127.0.0.1:5173
 stop           pnpm stop:local; docker compose down
 evidence       .../evidence/user-runnability/report.md
```

These values come from resolved stack provisioning plus the candidate contract,
not from generated prose.

Delivery summaries show one authoritative runnability result. Provider output
must not print a second conflicting delivery summary.

## Documentation Relationship

The documentation verifier consumes successful runnability evidence. It
deterministically checks that README prerequisites and install, provision,
bootstrap, start, open, and stop instructions match resolved stack provisioning
and the exact candidate commands that were executed. It also checks that the
documented expected first result matches the observed primary journey.

Ordering therefore becomes:

1. TECH WRITER may produce a provisional first-run manual during the build;
2. sandbox verification and fulfillment gates pass;
3. deterministic runnability executes the product contract and records facts;
4. the final deterministic documentation gate and DOCS VERIFIER compare README
   claims with those facts;
5. any documentation-only mismatch returns to TECH WRITER;
6. any runtime mismatch returns to implementation repair.

No provisional documentation verdict can satisfy final convergence. The final
documentation report must cite current runnability evidence whose three
authoritative hashes still match the candidate.

## Integration With Existing Components

- Extend stack parsing and resolution with the optional `runnability` section.
- Reuse the verification sandbox and command execution primitives; do not run
  runnability commands directly on the host.
- Reuse stack provisioning plan resolution for declared services.
- Keep `harness.app` as the browser/visual runtime profile. A migration helper
  may derive compatible start/readiness fields, but `harness.app` alone cannot
  satisfy the primary-journey contract.
- Store reports alongside existing verification evidence and apply equivalent
  fingerprint/provenance rules.
- Feed current-spec failures into Ralph's bounded build/fix loop before marking
  a strategy converged.
- Require a current passing report in landing for targets whose resolved stack
  policy is `required`.

## Rollout

The first release supports explicit contracts plus stack-required enforcement
for `browser-3d-game` and `browser-wasm-game`, both using the Linux-container
runner. It adds a complete contract to the browser-game smoke fixture. The
`ios-ar-game` stack records `macos_simulator` as its required future runner but
does not enable the gate until that runner exists. Existing projects without a
required user-facing stack are unaffected.

A later release may add ecosystem-specific contract generation, richer journey
DSLs, or remote deployment probes. Those conveniences must not weaken the
explicit, executed contract or silently infer a passing journey.

## Test Strategy

Unit tests cover stack schema validation, contract parsing, scope validation,
stage classification, report serialization, evidence freshness, and delivery
status rendering.

Harness tests use real local fixture processes inside the configured sandbox:

- a runnable web/API/data fixture passes all stages;
- a liveness-only shell fails the primary journey;
- a browser journey backed by intercepted API routes is rejected when a real API
  is required;
- a write that disappears after restart fails persistence;
- changed source or contract invalidates prior evidence;
- teardown runs after success, command failure, and timeout;
- a current-spec failure re-enters the repair loop;
- a product contract cannot select follow-up scope or bypass the gate;
- an owner-controlled deferral emits a proposal and does not auto-create a spec;
- landing rejects missing, failed, or stale required evidence;
- a merge-only commit with an unchanged product, candidate-contract, and stack
  fingerprint retains valid evidence.

The browser 3D game is the acceptance fixture: from a clean candidate Echelon
must provision Postgres, start the API and web client, establish a supported
local player identity, complete one real checkpoint journey, restart the
application boundary, and observe the persisted checkpoint.

## Out Of Scope

- production deployment, DNS, TLS, App Store publication, or cloud credentials;
- visual or gameplay-quality judgment beyond the declared primary journey;
- load, resilience, security, or disaster-recovery testing already owned by
  other gates;
- automatic creation or silent approval of a follow-up specification;
- treating README prose, test-suite success, or an LLM statement as runnable
  evidence.
