# Delivery Evidence Integrity Design

## Goal

Prevent Echelon from landing a delivery that only declares a usable local
journey or test coverage. Delivery must distinguish candidate-owned claims
from controller-observed evidence, and it must route unsupported completion
claims back into the autonomous repair loop.

This design fixes two observed defects:

1. a persistence-backed browser application passed sandbox runnability while
   its documented local journey omitted the authentication/session bootstrap
   and tested PostgreSQL readiness only inside the Compose container; and
2. fulfillment accepted a completed Playwright/visual task even though its
   critical journey was skipped, its coverage map still said
   `deferred-automation`, and no screenshot evidence had been retained.

## Authority model

Echelon keeps the existing authority boundary:

- candidate-owned source, tests, `.echelon/runnability.yml`, and README content
  are declarations;
- stack requirements and owner-controlled deferral records define obligations;
- harness-executed sandbox observations and immutable receipts are evidence;
- deterministic Python validation reconciles declarations, obligations, and
  evidence before an LLM may judge semantics.

No candidate file may exempt itself from a stack-required journey or evidence
obligation. No agent-written `strong` or `high` label may override contrary
controller evidence.

## Local journey contract

### Existing contract, extended

Extend the existing candidate-worktree `.echelon/runnability.yml`; do not add a
parallel lifecycle file. Preserve schema-version-1 contracts that do not select
a stack requiring the new capabilities.

`local_journey` gains two typed fields:

- `session_commands`: commands a local user runs to establish the identity or
  session required by the user-facing journey; and
- `boundary_probes`: typed service probes that execute from the same consumer
  boundary as the locally started application.

A boundary probe contains a stable ID, a declared service (`web`, `api`, or
`postgres`), and one command. It is not an in-container health check. For a
PostgreSQL application, the command must connect through the host-facing
endpoint with the same effective connection configuration the local
application uses.

The generic contract does not prescribe Docker Compose, database names,
credentials, JWT libraries, or package managers. Project commands remain
candidate-owned. Stack capabilities determine which fields are mandatory:

- a stack requiring `local_journey` still requires the full lifecycle;
- a runnability contract with `identity` or browser `session_storage` also
  requires non-empty local `session_commands`; and
- every service in `primary_journey.real_services_required` that is required
  locally must have a corresponding boundary probe.

The local lifecycle order is:

1. prerequisites;
2. provision;
3. boundary probes;
4. prepare;
5. verify;
6. start;
7. session establishment;
8. open;
9. stop;
10. cleanup.

### Verification semantics

The Linux delivery sandbox remains the only automatically executed runtime for
browser stacks. Echelon must not run candidate Compose or local commands on the
user's host.

Sandbox runnability proves the authoritative composition using the existing
identity command, session storage, real service sidecars, browser journey, and
persistence observations. The local journey remains explicitly `unverified`
until a compatible local runner or the user executes it. Documentation may say
that its sandbox-equivalent path passed, but must not say that the host journey
itself passed.

The documentation verifier compares every declared command, probe, and URL
against README instructions. It also rejects a local journey that needs an
identity but gives the user no session-establishment step, or that declares a
real service without a consumer-boundary probe.

Immutable evidence continues to redact URL userinfo. Command parity therefore
normalizes both the receipt claim and README text through the same redaction
function before comparison. A real runnable credential-bearing command can
match its redacted receipt without requiring README to contain a literal,
non-runnable `[REDACTED:url-userinfo]` placeholder.

## Coverage and task evidence integrity

### Coverage-map pre-pass

Add a deterministic parser for the existing `coverage-map.md` tables. It
normalizes requirement IDs, test-case IDs, test type, automation status,
coverage type, evidence, and gap/action without changing the document format.

Before fulfillment judgment, Python produces a coverage-evidence pre-pass for
the canonical requirement inventory. For each requirement it records whether
coverage is:

- `automated` and evidence-linked;
- `deferred-automation`;
- `escalate`;
- missing; or
- malformed/contradictory.

`deferred-automation` is a planning-time obligation, not a permanent delivery
veto. It may yield mechanical `IMPLEMENTED` only after the implementation map
contains strong, high-confidence source-and-test evidence with no unresolved
runtime threshold. `escalate`, missing, or malformed required coverage remains
blocking. Active owner-controlled deferred-scope ledger entries remain the
only authority that can remove an obligation from the current delivery.

The task-progress integrity check also maps completed task `req=` metadata to
coverage rows. A task marked `DONE`, `DONE_WITH_CONCERNS`, or `DEGRADED` while
required coverage remains deferred or absent is an evidence-integrity failure.
It is reported as actionable delivery debt, not accepted as bookkeeping truth.

### Executed test evidence

Controller-owned test receipts distinguish test process success from proof that
required tests executed. The first structured adapter is Playwright JSON,
reusing the parser already used by the visual phase.

For a required Playwright command:

- malformed or absent JSON is a failure;
- zero executed tests is a failure;
- a required test reported as `skipped`, `fixme`, or otherwise not executed is
  a failure unless an active owner-controlled deferral covers its requirement;
- any failed or timed-out result is a failure; and
- process exit zero does not override these conditions.

The normalized result records suite/test identity and passed, failed, skipped,
and total counts. Its immutable receipt is bound to the candidate product
fingerprint and selected as the latest attempt using the existing receipt
pattern.

### Visual evidence

When the existing Browser App Gates table says `Visual validation task: yes`,
visual convergence additionally requires:

- at least one executed visual Playwright test;
- retained PNG or JPEG artifacts copied from the sandbox into the harness run;
- artifact SHA-256 digests in the controller receipt; and
- no required visual coverage row left as `deferred-automation` or `escalate`.

The visual runner retrieves artifacts on successful verification as well as on
failure. Temporary container-copy paths are never treated as durable evidence.
The receipt records the configured screenshot directory and the retained
artifact set.

This gate proves that declared visual checks ran and produced the required
evidence. It does not claim subjective visual quality unless the configured
visual validator also produced a passing result.

## Fulfillment integration

Extend the existing judgment pre-pass rather than creating another fulfillment
system. The post-verification gates run in evidence-production order:
candidate checks, user runnability, fulfillment refresh and judgment,
documentation, then final task completeness. This prevents fulfillment from
blocking the run before the harness can produce the composition evidence that
the judgment needs. The judgment consumes:

- the implementation map;
- normalized coverage evidence;
- controller-owned verification/test receipts;
- controller-owned visual receipts when required; and
- the active deferred-scope ledger.

Mechanical `IMPLEMENTED` requires all currently required evidence dimensions.
Contradictory evidence moves the row to a deterministic non-implemented status
or the bounded fallback queue; it can never be hidden by an implementation-map
confidence label.

Fulfillment refresh fails closed when required evidence files are missing,
stale, malformed, tied to a different product fingerprint, or inconsistent
with task progress. The resulting gap identifiers and repair text are supplied
to the normal delivery repair loop so Echelon can implement the missing test,
update the coverage map after it executes, and rerun verification without user
adjudication.

## Reporting

Delivery status and summaries must show distinct facts:

- sandbox journey: passed/failed;
- local journey: missing/declared-unverified/verified;
- required Playwright tests: passed/failed/skipped counts;
- visual evidence: retained artifact count or the blocking reason;
- fulfillment evidence integrity: valid or the concrete requirement/task IDs;
  and
- the next autonomous repair action.

Messages must not tell the user merely to “fix the blocker” when Echelon has
enough evidence to identify and repair it itself.

## Compatibility and rollout

- Browser 3D and browser WASM stacks use the new browser evidence gates. A
  required stack observation of `browser_dom` activates visual validation even
  when a project configuration omits the optional `visual_tests.enabled` flag;
  candidate configuration cannot weaken a stack-required gate.
- PostgreSQL persistence requires local session setup when identity is used and
  a PostgreSQL consumer-boundary probe.
- Non-browser stacks retain their current verification behavior.
- iOS remains outside the executable browser gate until a macOS simulator
  runner exists.
- Existing runnability contracts remain parseable; newly required fields block
  only when selected stacks or declared identity/service obligations demand
  them.

After the generic Echelon change passes its suites, rerun delivery against the
browser 3D demo. Echelon, not a hand edit, must repair its local journey,
Playwright journey, coverage status, and visual evidence before fulfillment can
converge again.

## Verification

Tests must cover:

- local identity without session commands;
- a real local service without a matching boundary probe;
- exact README parity for session commands and probes;
- truthful declared-unverified reporting;
- Playwright exit zero with zero tests;
- Playwright exit zero with required skipped tests;
- passing executed tests with no required screenshot artifacts;
- retained screenshot hashes and product-fingerprint provenance;
- planning-deferred coverage satisfied by strong delivery evidence, while weak
  or runtime-threshold evidence remains unresolved;
- a completed task contradicting deferred or missing coverage;
- active owner-controlled deferral behavior; and
- backward compatibility for unaffected stacks and contracts.
