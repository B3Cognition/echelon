# Delivery User-Runnability Gate Design

**Status:** Approved in principle; awaiting written-spec review
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
2. **The final candidate is tested.** Evidence is tied to the exact candidate
   fingerprint and is invalidated by relevant source or contract changes.
3. **Real composition is required.** A journey using HTTP mocks, intercepted
   routes, test-only authentication, or an in-memory substitute cannot prove a
   real multi-service product.
4. **The stack declares obligations.** A stack identifies whether the target is
   runnable, which infrastructure it needs, and which operational capabilities
   the project must expose. Product repositories provide the concrete commands.
5. **Scope decisions are explicit.** Missing runnability normally reopens the
   current delivery. Deferral is allowed only when the spec or stack selection
   explicitly records that operability belongs to a follow-up.
6. **No host pollution.** Setup, dependencies, browsers, services, probes, and
   teardown run inside the existing delivery sandbox boundary.

## Contract

### Stack declaration

User-facing archetype stacks declare a runnability obligation:

```yaml
runnability:
  classification: user_facing
  policy: required
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

Provisioning remains composable. Capability stacks such as
`game-persistence-postgres` declare required services, environment, readiness,
and satisfiers. The runnability planner consumes that existing information
instead of introducing a second database provisioning model.

### Project declaration

The target repository supplies concrete commands under
`harness.user_runnability` in `.echelon/config.yml`:

```yaml
harness:
  user_runnability:
    enabled: true
    scope: current_spec
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
    primary_journey:
      command: pnpm test:runnability
      requirements: [FR-001]
      real_services_required: [web, api, postgres]
    persistence_probe:
      command: pnpm test:persistence-runnability
      restart_commands:
        - pnpm restart:local
    stop_commands:
      - pnpm stop:local
```

The command vocabulary is ecosystem-neutral. Echelon does not require pnpm,
Docker Compose, HTTP, or Playwright; those are concrete choices made by a
project and its selected stacks. `${ECHELON_PORT}` is allocated by the harness.
Infrastructure services are not started by these commands. The harness
materializes resolved stack services as attempt-scoped sandbox sidecars, injects
their generated connection environment, and owns their teardown. Project
`bootstrap_commands` perform application-level initialization such as migrations
and seed data against those sidecars.

`scope` has two values:

- `current_spec`: runnability is part of this delivery and failure blocks and
  repairs it. This is the default for a required user-facing stack.
- `follow_up`: the current spec explicitly excludes runnability. The gate emits
  a follow-up proposal instead of entering the repair loop. Selecting this value
  must cite an authored scope exclusion; configuration alone cannot invent one.

High-confidence detection may suggest or initialize parts of this contract, but
must not fabricate a passing primary journey. If a required contract remains
incomplete, delivery fails closed with a precise configuration/product gap.

## Execution Model

The new gate runs after normal build verification and documentation convergence,
and before final fulfillment convergence and landing:

```text
build/fix -> sandbox verify -> documentation -> USER RUNNABILITY
                                             | pass
                                             v
                                  fulfillment -> convergence -> land
                                             | fail/current_spec
                                             v
                                      bounded repair loop
```

For the final candidate, the harness:

1. creates or reuses a clean delivery sandbox for that candidate;
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

The primary journey may use a browser automation framework, an HTTP client, a
CLI invocation, or another deterministic probe. It must target the processes
started by the contract. The planner rejects known mock/fixture configuration
and requires service-boundary observations where a selected capability defines
them. For example, the persistence capability verifies the journey's unique
marker directly through its sandbox Postgres sidecar after application restart;
a browser route mock cannot satisfy that observation.

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

Evidence may be carried forward only when the candidate commit, normalized
contract hash, and resolved stack contract hash are unchanged. Landing performs
the same provenance check used by convergence.

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

For an explicitly supported `follow_up` scope, Echelon writes
`runnability-follow-up.md` containing:

- the failed or absent capabilities;
- observed evidence;
- proposed specification title and intent;
- draft requirements and acceptance criteria;
- affected target and selected stacks;
- the exact command to start a new spec from the proposal.

The CLI presents the proposal but does not create the specification without
owner approval.

## CLI Presentation

`echelon delivery status` adds a concise runnability section:

```text
 user runnable  failed
 stage          primary journey
 reason         missing local authentication bootstrap
 evidence       .../evidence/user-runnability/report.md
 next           delivery will repair this current-spec product gap
```

For follow-up scope, `next` identifies the proposal file and an executable
spec-authoring command. For a missing contract, status names the exact required
configuration fields rather than suggesting a generic resume.

Delivery summaries show one authoritative runnability result. Provider output
must not print a second conflicting delivery summary.

## Documentation Relationship

The documentation verifier consumes successful runnability evidence. It may
then assert that README startup commands were actually executed and that the
documented URL and expected first result match observed behavior.

Ordering therefore becomes:

1. TECH WRITER produces or repairs the first-run manual;
2. deterministic runnability executes the product contract and records facts;
3. DOCS VERIFIER compares README claims with those facts;
4. any documentation-only mismatch returns to TECH WRITER;
5. any runtime mismatch returns to implementation repair.

If current workflow constraints require documentation to run before the first
runnability attempt, DOCS VERIFIER may return a provisional result, but final
convergence requires a post-runnability documentation check backed by current
evidence.

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

The first release supports explicit contracts plus stack-required enforcement.
It updates the three persistent-game archetypes to `policy: required` and adds a
complete contract to the browser-game smoke fixture. Existing projects without
a user-facing stack are unaffected.

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
- a supported follow-up scope emits a proposal and does not auto-create a spec;
- landing rejects missing, failed, or stale required evidence.

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
