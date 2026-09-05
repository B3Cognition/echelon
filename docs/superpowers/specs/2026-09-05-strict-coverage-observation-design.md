# Strict coverage observation for delivery fulfillment

## Purpose

Make a planned coverage row fulfillable without trusting a provider's claim,
without weakening browser verification, and without trapping a correct delivery
in a permanent `deferred-automation` state.

The observed browser-3D delivery exposed a real deadlock. Phase A correctly
created a coverage map whose rows were `deferred-automation` until code and
tests existed. Phase B then ran the complete verifier successfully, but the
deterministic pre-pass could promote a deferred row only when the implementation
map called its source-and-test evidence `strong`. The mapper deliberately never
calls deferred coverage strong. The result is circular: all 68 requirements
remain unverified even when the sandbox receipt proves the candidate's complete
test suite passed.

The fix must not turn a green aggregate command into blanket proof. A successful
`pnpm verify` says that its suite succeeded, but it does not say which planned
logical test cases ran, were skipped, or belonged to the candidate under review.

## Goals

- Preserve Phase A's coverage map as a planning contract while allowing normal
  delivery to discharge its test obligations mechanically.
- Require an exact, harness-observed passed test for every required planned test
  case before its coverage may satisfy fulfillment.
- Bind all coverage observations to the same candidate content, coverage-map,
  stack definition, and successful authoritative verification receipt.
- Keep execution inside the provisioned Echelon sandbox. No browser, database,
  dependency install, or test command leaks to the user host.
- Send precise missing, unbound, skipped, failed, or stale case identifiers to
  the autonomous repair loop.
- Apply the first implementation to browser-3D and browser-WASM stacks without
  pretending that a Linux sandbox can verify iOS/Xcode.

## Non-goals

- Treating a zero exit code from a project-owned command as evidence that every
  logical coverage case passed.
- Letting the delivered candidate edit its coverage declaration to exempt
  itself.
- Making all existing stacks add runner-specific report formats immediately.
- Replacing semantic fulfillment judgment. This design proves the execution
  fact; the existing code/test evidence and fulfillment review continue to
  judge whether the implementation meets the requirement.
- Host-local verification or automatic deployment.

## Authority and ownership

| Item | Owner | Authority |
| --- | --- | --- |
| Canonical requirements, coverage map, and active deferral ledger | planning / workspace owner | Defines what is required and the only permitted current-spec deferrals. |
| Stack coverage-observer definition | Echelon stack owner | Defines which sandbox command and structured-result adapter are required. Candidate configuration cannot remove or weaken it. |
| Test source and Echelon case tags | candidate | A claim that can be inspected and executed, never proof by itself. |
| Structured runner output, normalized observation, and receipt hashes | harness | The only authority for whether a tagged physical test executed and passed. |
| Product fingerprint and stack/contract hashes | harness | Determines whether observation is valid for the candidate being judged. |
| Semantic implementation map and fulfillment review | existing harness flow | Decides whether observed implementation/test evidence actually fulfills the requirement. |

An active owner-controlled deferred-scope ledger entry remains the sole way to
remove a required item from the current delivery. A source-controlled
`scope: follow_up`, a provider note, or an edited candidate artifact cannot do
so.

Echelon resolves the selected stack set and its observer configuration from the
workspace-owned runtime at delivery dispatch, stores that resolved input in the
run, and hashes it. A candidate worktree cannot add, replace, or disable an
observer. Candidate `.echelon/runnability.yml` is reloaded after each build or
repair because it describes the candidate's service journey, but it can only
supply an input to a stack-required observer; it cannot alter that observer's
command, adapter, or required test types.

## Coverage contract and test identity

`coverage-map.md` remains the human-readable planning contract and keeps its
current table format. Each row already names one or more logical `Test case ID`
values and one or more canonical requirement IDs. During delivery,
`automated` and `deferred-automation` both mean **a required test observation**;
the latter records that the test did not exist at planning time. `escalate`,
malformed rows, missing rows, and contradictory declarations remain blocking.

The parser normalizes the existing table rather than requiring planners to
reformat it. Requirement IDs are split on comma or slash. Test case IDs are
split on comma, slash, or semicolon. A Test Type cell is split on comma or
slash. One type applies to every case in the row; otherwise the number of types
must equal the number of case IDs and pairs by position. For example,
`UT-LAYOUT-003; E2E-DETERMINISM-003` with `unit/e2e` creates one unit and one
e2e obligation. Any other cardinality, invalid type syntax, or the same logical
case ID declared with incompatible types is `contradictory` and blocks.

`automated` and `deferred-automation` are planning states, not delivery
results. Echelon does not ask a provider to rewrite the map's historical state
from `deferred-automation` to `automated`; it records delivery execution only
in its run-owned evidence. Legacy prose in a map that says a deferred row must
"become automated" is satisfied only by a matching observed test case, never
by a textual edit.

The initial browser observer vocabulary is `unit`, `integration`, `contract`,
and `e2e`; stack schemas permit future syntactically valid lower-case
hyphenated test-type names. Phase A resolves every declared test type against
the selected stack's observer set before a spec becomes ready to build. A type
with no observer is a clear `coverage_observer_unavailable` planning quality
gap, with the required adapter named; it is never guessed as another runner and
never allowed to enter an endless Phase B repair loop. This lets browser-WASM
use its declared Vitest/Playwright contract today while reserving a future
native Rust adapter for a spec that genuinely needs one.

The test case ID is the stable bridge from the plan to a physical test. A
candidate test that implements a planned case must include the exact logical
case ID in its test title using the stack-neutral Echelon tag form:

```text
collectible inventory persists after reload [echelon:E2E-PERSIST-001]
```

One physical test may carry multiple tags only when it genuinely exercises all
of those logical cases. A physical identity is `(observer, relative test file,
normalized full title)`, excluding retry, shard, and browser-project suffixes.
Each case ID must bind to exactly one physical identity from an observer whose
declared test types include its coverage-row type. All terminal executions of
that physical identity (for example Chromium and WebKit projects, or retried
attempts) must pass. Two different physical identities carrying the same case
ID are `duplicate_binding`; no identity, malformed tags, or tags for IDs absent
from the coverage map are integrity failures.

The adapter also verifies that the tag occurs in the reported candidate test
file and that the normalized source title matches the reported title. A runner
which cannot provide a stable relative file and final test title is not an
eligible coverage observer. The tag convention is therefore visible in both
candidate source and runner output; an agent cannot satisfy a planned case by
writing an untracked mapping file or by fabricating a report.

The initial parser accepts square-bracket tags at the end of a test title,
case-insensitively for the `echelon` label and exactly for the case ID:

```text
[echelon:CASE-001]
[echelon:CASE-001, CASE-002]
```

Adapters retain framework, project, relative test file when supplied, full test
title, logical case IDs, normalized final status, retry count, and source report
location. Tags do not prove semantic correctness; they only make the claimed
execution link deterministic. Existing source/test evidence and fulfillment
judgment still assess semantics.

## Stack-owned coverage observers

Stack schema version 1.3 adds optional `coverage_observers`; version 1.2 stacks
remain valid and have none. Observers are declared in a stack definition, not
in candidate `.echelon/config.yml`. Every observer specifies:

- a globally unique identifier and its non-empty `test_types` set;
- a sandbox command which emits a supported structured result format;
- an adapter (`playwright-json` or `vitest-json` initially);
- a target-relative report location: `captured` reads it from the verified
  candidate, while `isolated` uses its filename for the retained harness
  artifact; and
- whether it is required and whether it is `captured` or `isolated`.

The stack resolver rejects two selected required observers that claim the same
test type. That makes every normalized coverage obligation map to exactly one
owner-configured observer instead of allowing a candidate to choose a weaker
one.

The verification bundle contains the normal `verify_command` receipt and all
required observer receipts. A `captured` observer collects a known structured
report emitted by the normal verifier. An `isolated` observer runs only its
owner-configured test command in a **fresh sandbox session** for the same
candidate, with the same sandbox image, service plan, bootstrap, and injected
environment class as the normal verifier. It never runs against mutable service
state left by the normal verifier or another observer. Each receipt is retained
and every required stage must pass.

An isolated command must write its report through the harness-provided
`ECHELON_COVERAGE_REPORT` environment variable. That destination is outside the
mounted candidate worktree. Echelon copies the finished bytes out through the
sandbox provider and writes them once under the observer's immutable evidence
directory before parsing. A stack observer therefore cannot hide generated
reports in candidate `.echelon` control files excluded from the product
fingerprint.

This allows a stack to use capture when its normal verifier already emits
structured results, while safely supporting existing projects whose aggregate
verifier does not. The latter may execute a suite twice, but only in independent
ephemeral databases/browser sessions; it cannot gain or lose a pass because a
previous suite mutated test data. No observer command runs on the user host.

Browser-3D and browser-WASM stacks initially require a structured browser
observer for `e2e` and a structured Vitest observer for `unit`, `integration`,
and `contract` where those types occur in their coverage maps. The harness
starts their PostgreSQL/other required sidecars and browser dependencies inside
its sandbox. The user host remains untouched.

iPhone/AR stacks declare the future capability but do not activate this gate
until Echelon has an owner-provided macOS/Xcode simulator runner. Their status
must explicitly say `coverage_observer_unavailable: macos_simulator_required`,
not imply successful observation.

Unchanged stacks without a required observer preserve current behavior. A stack
that opts into a required observer fails closed when the observer is absent,
cannot start, produces invalid JSON, or reports zero tests.

## Harness-owned observation artifact

After a successful full verification receipt and every required observer finish,
the harness writes the immutable, run-owned artifacts:

- `{verify_run_dir}/coverage-observation.v1.json`
- `{verify_run_dir}/coverage-observation.v1.md`

The JSON schema contains:

```json
{
  "schema_version": 1,
  "candidate": {
    "commit": "informational SHA",
    "product_fingerprint": "sha256",
    "coverage_map_hash": "sha256",
    "resolved_stack_hash": "sha256",
    "observer_plan_hash": "sha256",
    "runnability_contract_hash": "sha256 or null"
  },
  "verification_receipt": {"path": "...", "sha256": "...", "status": "passed"},
  "observers": [{"id": "playwright", "receipt": "...", "status": "passed"}],
  "test_cases": {
    "E2E-PERSIST-001": {
      "status": "passed",
      "matches": [{"observer": "playwright", "file": "...", "title": "...", "source_sha256": "...", "projects": [{"name": "chromium", "status": "passed"}]}]
    }
  },
  "requirements": {
    "AC-001": {"status": "observed", "test_case_ids": ["E2E-PERSIST-001"]}
  }
}
```

The Markdown form is a concise, user-readable table of requirement, required
case, observer, final result, and blocker reason. It is a view of the JSON and
cannot be used as evidence itself.

The JSON retains only normalized identifiers, relative paths, result status,
digests, and redacted bounded diagnostics. Raw reporter output and unredacted
environment values are never copied into the run. Receipt and report handling
uses the existing verification-redaction rules.

The artifact writer follows the verification receipt's exclusive-create,
symlink-safe, digest-checked pattern. A later attempt writes a new numbered
artifact and updates a small trusted latest pointer; it cannot overwrite or
silently mutate evidence from an earlier candidate.

The artifact is written only after the harness validates:

1. the standard verifier receipt passed for the candidate fingerprint;
2. each required observer receipt passed and has nonzero executed tests;
3. every logical tag has exactly one source identity, every observed project or
   retry normalizes to a passed final result, and the candidate source file
   contains the corresponding tag;
4. every coverage-map case has a matching required observer/type and a passed
   result; and
5. its map, stack, contract, receipt, and candidate fingerprints all match.

An observer may report an untagged skipped test without changing an otherwise
valid coverage result; existing suites sometimes intentionally skip tests for a
separate environment capability. A skipped, missing, or failed test carrying a
required Echelon case tag is always blocking. This avoids a coverage gate
silently accepting a skipped planned case without turning unrelated historical
skips into a delivery regression.

For each requirement, every coverage row not excused by an active owner deferral
must be observed. A requirement with several required cases is `observed` only
if all required cases passed. A current owner deferral yields `owner_deferred`;
it never masquerades as an observation.

The remaining explicit statuses are `unbound`, `duplicate_binding`, `failed`,
`skipped`, `not_executed`, `observer_failed`, `observer_missing`,
`invalid_report`, `missing`, `contradictory`, and `provenance_mismatch`.
All are blocking for a currently-required requirement.

## Reconciliation and fulfillment changes

`coverage_evidence.py` evolves from a declaration parser into a reconciler. It
first parses the planning rows exactly as today, then combines them with a
validated coverage observation. The existing `coverage-evidence.json` becomes
schema version 2 and records both declaration and observation state. It never
rewrites `coverage-map.md` and never interprets a candidate's status word as a
successful test execution.

All direct, scoped, and full verify-spec paths use one shared sequence:

1. reload and validate the repaired candidate runnability contract;
2. run the standard sandbox verifier and required coverage observers into one
   verification bundle;
3. validate and write the coverage observation;
4. reconcile coverage evidence; then
5. run judgment pre-pass and semantic fulfillment review.

No path may call the judgment pre-pass with declaration-only evidence when a
selected stack requires coverage observation. This is the explicit guard against
reintroducing the deferred-coverage deadlock through a fallback or resume path.

The pre-pass receives a validated `CoverageObservationRef`, rather than
silently regenerating declaration-only coverage evidence. It accepts an
observation only after validating the verification bundle, normalized source
identities, and full provenance tuple. The fulfillment reviewer receives the
coverage row's stated oracle plus the exact tagged test file/title and observed
result. An observed tag removes the execution-evidence objection; it does not
license the reviewer to accept an unrelated or semantically empty test.

`judgment_prepass.py` consumes the validated observation reference. A planned
`deferred-automation` row may propose `IMPLEMENTED` only when all of the
following are true:

1. its reconciled coverage status is `observed`;
2. the observation is provenance-valid for the candidate under judgment;
3. the implementation map contains high-confidence source-and-test evidence
   for the requirement and no unresolved runtime threshold; and
4. no active integrity contradiction or owner-controlled deferral applies.

Its reason is `coverage_observed_passed`, not
`deferred_automation_satisfied`. The former means that execution was measured;
it does not depend on an arbitrary `strong` label. The codegraph mapper retains
its conservative `source_and_test: medium` classification and continues to
separate semantic/source confidence from test-execution fact.

The prior workflow rule that categorically prohibits strong evidence for a
deferred planning row is removed. It is replaced by this clearer rule: source
evidence strength cannot promote deferred coverage; only the validated coverage
observation can. This removes the deadlock without making the mapper less
conservative.

Fulfillment, task progress, visual validation, and landing consume the
reconciled artifact. A task whose `req=` values have unresolved coverage is an
actionable integrity gap even if a provider reports it done. The next repair
prompt names the exact logical case and reason, for example:

```text
Coverage gap: AC-014 → E2E-SKY-003 is unbound.
Add exactly one [echelon:E2E-SKY-003] tag to the browser test that exercises
the requirement, then let Ralph rerun the harness-owned browser observer.
```

Providers remain forbidden from running the full verifier or provisioning
services. They may add/fix tagged tests and execute service-free focused tests.
Ralph performs every authoritative rerun.

## Provenance and finalization

The coverage observation is valid only for the candidate product fingerprint,
coverage-map hash, resolved-stack hash, observer-plan hash, contract hash, and
verification-bundle receipt hashes it records. Commit SHA is retained as useful
provenance but is not the authority: a merge-only commit may reuse evidence only
when all authoritative content fingerprints are unchanged. Any product, map,
stack, observer plan, or contract change invalidates the observation and
triggers fresh sandbox verification.

The existing strict `validate_verification_receipt` remains unchanged for
legacy callers. Landing and coverage observation gain an explicit
equivalent-product validator which verifies the receipt digest, authority,
passed status, and complete fingerprint tuple, then permits only a commit-SHA
difference. It is never a broad relaxation of receipt validation.

This follows the existing delivery provenance model and prevents a stale
successful test report from fulfilling a changed candidate.

## Reporting and autonomous recovery

`echelon delivery status` and the delivery summary show a compact coverage
section:

```text
coverage   68 / 68 requirements observed
observers  vitest 42 passed · playwright 26 passed
evidence   candidate + map + stack fingerprints match
```

When blocked, the report groups the exact reasons and supplies one unambiguous
next action. Examples: `3 unbound test cases`, `Playwright observer skipped 2
cases`, or `coverage observation stale after candidate changed`. It never asks
the user to choose between `resume`, `run`, and `reset` for an ordinary
repair; the normal delivery loop is resumed or restarted automatically according
to the existing state policy.

Only unavailable external authority (for example an iOS simulator runner not
yet supported) is escalated. Missing tags/tests, invalid reports, stale
fingerprints, or a failed sandbox observer return to the repair loop.

## Compatibility and migration

- The current Markdown coverage-map format and coupled requirement rows remain
  supported. Requirement IDs continue to be split and assessed individually;
  comma, slash, and semicolon-delimited test IDs and paired test types are
  normalized as specified above.
- Version-1 coverage evidence remains readable for historical status views.
  It is not acceptable for a stack that now requires coverage observation; its
  deterministic outcome is `observer_missing`, not a guessed pass.
- Browser-3D and browser-WASM stack versions activate the new observer gate.
  Other stack behavior is unchanged until their owner supplies an adapter and
  sandbox-capable runner.
- Existing receipt carry-forward uses the authoritative fingerprint tuple, not
  commit equality only through the new equivalent-product validator, so
  merge-only finalization cannot recreate the former provenance mismatch.

## Test strategy

Unit and integration tests must prove the following before the feature is
enabled:

1. a real planning-deferred row with a normal `source_and_test: medium`
   implementation map becomes `IMPLEMENTED` only after a matching passed
   harness observation; this is the regression for the observed deadlock;
2. a green aggregate verifier cannot promote an unbound logical test case;
3. failed, skipped, duplicate, unknown-tag, zero-test, malformed-report, and
   wrong-observer cases all fail closed with actionable reason codes;
4. one physical tagged test may satisfy multiple planned cases only when each
   tag is declared in the map and every normalized project/retry result passes;
5. every row of a coupled requirement map is assessed separately, so
   `AC-001 / FR-001` cannot hide a missing requirement;
6. semicolon-delimited test cases and positional `unit/e2e` test-type pairs are
   normalized independently; incompatible case/type declarations fail closed;
7. receipt, product fingerprint, map hash, resolved-stack hash, observer-plan
   hash, or contract hash drift
   rejects observation reuse, while a merge-only SHA change with identical
   authoritative fingerprints carries it forward;
8. active owner-controlled deferral works, but candidate-controlled deferral
   text does not;
9. captured observers use a report from the normal verifier, while isolated
   observers start from fresh sandbox services and cannot observe stale database
   state or run on the host;
10. browser observer reports retain exact source identity and redact diagnostics;
11. unavailable iOS/macOS observation reports the explicit capability gap
   without claiming verification; and
12. the browser-3D fixture reaches a clean observed-coverage fulfillment path
    and a fresh delivery cannot converge by manually changing planning status.
13. stack schema 1.2 remains accepted, schema 1.3 rejects malformed observer
    definitions, and conflicting selected observers for one test type fail
    during stack resolution rather than during delivery.
14. direct, scoped, and full fulfillment paths all reject declaration-only
    coverage when a selected stack requires an observation.
15. Phase A rejects an unsupported planned test type before delivery, rather
    than routing it to a guessed observer or repeated repair attempt.

## Rollout

1. Implement the generic schema, parser, reconciler, receipt validation, and
   pre-pass integration behind stack-declared observers.
2. Add Vitest JSON and Playwright JSON adapters plus browser-3D/browser-WASM
   stack declarations.
3. Upgrade the browser-3D demo through Echelon delivery: it must add exact
   tagged tests, produce sandbox observation, and converge without hand-editing
   its planning coverage map.
4. Keep the gate disabled for iPhone/AR until an owner-provided macOS simulator
   runner and structured adapter exist.

This is deliberately narrower than a new verification subsystem: it fills the
missing bridge between an existing planning contract, existing full sandbox
verification, and existing fulfillment judgment.
