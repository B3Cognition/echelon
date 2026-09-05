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

## Coverage contract and test identity

`coverage-map.md` remains the human-readable planning contract and keeps its
current table format. Each row already names one or more logical `Test case ID`
values and one or more canonical requirement IDs. During delivery,
`automated` and `deferred-automation` both mean **a required test observation**;
the latter records that the test did not exist at planning time. `escalate`,
malformed rows, missing rows, and contradictory declarations remain blocking.

The test case ID is the stable bridge from the plan to a physical test. A
candidate test that implements a planned case must include the exact logical
case ID in its test title using the stack-neutral Echelon tag form:

```text
collectible inventory persists after reload [echelon:E2E-PERSIST-001]
```

One physical test may carry multiple tags only when it genuinely exercises all
of those logical cases. Each case ID must appear in exactly one normalized final
test result from an observer whose declared test type matches its coverage row.
Duplicate matches, no match, malformed tags, and tags for IDs absent from the
coverage map are integrity failures. The
tag convention is deliberately visible in source and runner output; an agent
cannot satisfy a planned case merely by writing a separate untracked mapping
file.

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

Stacks may declare `coverage_observers` in the stack definition, not in
candidate `.echelon/config.yml`. Every observer specifies:

- an identifier and expected test type;
- a sandbox command which emits a supported structured result format;
- an adapter (`playwright-json` or `vitest-json` initially);
- the report path to collect from the sandbox; and
- whether it is required for the stack.

Observers run in the same candidate worktree, provisioned services, sandbox
network, and environment class as the authoritative full verifier. They run
after the normal verifier has succeeded, so their evidence supplements rather
than replaces `verify_command`. Echelon retains both commands' receipts.

Browser-3D and browser-WASM stacks initially require a structured browser
observer and structured unit-test observer where their coverage map contains the
matching test type. The harness starts their PostgreSQL/other required sidecars
and browser dependencies inside its sandbox. The user host remains untouched.

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
    "stack_hash": "sha256",
    "runnability_contract_hash": "sha256 or null"
  },
  "verification_receipt": {"path": "...", "sha256": "...", "status": "passed"},
  "observers": [{"id": "playwright", "receipt": "...", "status": "passed"}],
  "test_cases": {
    "E2E-PERSIST-001": {
      "status": "passed",
      "matches": [{"observer": "playwright", "file": "...", "title": "...", "status": "passed"}]
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

The artifact is written only after the harness validates:

1. the standard verifier receipt passed for the candidate fingerprint;
2. each required observer receipt passed and has nonzero executed tests;
3. every logical test tag maps to exactly one final physical test result for its
   observer;
4. every coverage-map case has a matching required observer/type and a passed
   result; and
5. its map, stack, contract, receipt, and candidate fingerprints all match.

For each requirement, every coverage row not excused by an active owner deferral
must be observed. A requirement with several required cases is `observed` only if all required cases
passed. A current owner deferral yields `owner_deferred`; it never masquerades
as an observation.

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
coverage-map hash, stack hash, contract hash, and verification receipt hash it
records. Commit SHA is retained as useful provenance but is not the authority:
a merge-only commit may reuse evidence only when all authoritative content
fingerprints are unchanged. Any product, map, stack, contract, or observer
change invalidates the observation and triggers fresh sandbox verification.

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
  supported. Requirement IDs continue to be split and assessed individually.
- Version-1 coverage evidence remains readable for historical status views.
  It is not acceptable for a stack that now requires coverage observation; its
  deterministic outcome is `observer_missing`, not a guessed pass.
- Browser-3D and browser-WASM stack versions activate the new observer gate.
  Other stack behavior is unchanged until their owner supplies an adapter and
  sandbox-capable runner.
- Existing receipt carry-forward uses the authoritative fingerprint tuple, not
  commit equality, so merge-only finalization cannot recreate the former
  provenance mismatch.

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
   tag is declared in the map and the normalized final result passes;
5. every row of a coupled requirement map is assessed separately, so
   `AC-001 / FR-001` cannot hide a missing requirement;
6. receipt, product fingerprint, map hash, stack hash, or contract hash drift
   rejects observation reuse, while a merge-only SHA change with identical
   authoritative fingerprints carries it forward;
7. active owner-controlled deferral works, but candidate-controlled deferral
   text does not;
8. browser observers run with the configured sandbox sidecars and never on the
   host; their structured Playwright/Vitest reports retain exact test identity;
9. unavailable iOS/macOS observation reports the explicit capability gap
   without claiming verification; and
10. the browser-3D fixture reaches a clean observed-coverage fulfillment path
    and a fresh delivery cannot converge by manually changing planning status.

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
