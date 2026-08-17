# Final whole-branch fix wave report

## Scope and finding validation

The final review findings were checked against the shipped production paths,
durable state shapes, and recovery behavior before changes were made. All eight
Important findings and the scoped CLI Minor were confirmed. No review item
conflicted with the approved design. Item 8 was specifically a missing
end-to-end acceptance test rather than a missing enforcement mechanism: the
new real controller/provider tests passed the existing COMMANDER validation
and retry implementation without a production change.

The separately ledgered downstream Tasks Lexicon recovery and publication
summary defects were not changed.

## RED evidence

### Candidate currentness, restoration, and sealed identity

Four production-path controller tests failed before implementation:

- completing a newer candidate overwrote the manifest digest of the restored
  older best candidate;
- an injected interruption after one owned-artifact replacement left retry
  unable to recover the pending completion;
- standalone restore accepted a replaced selected manifest; and
- combined candidate-plus-restore accepted a replaced selected manifest.

The failures respectively exposed newest-receipt currentness, non-idempotent
multi-file restoration, and missing digest/identity checks in both effect
paths.

### Legacy migration and completion compatibility

The legacy migration matrix failed for certified histories `iter-0`,
`iter-0..1`, and `iter-0..2`: the initial assessment was counted as a repair.
Two typed-loader and two public recovery tests also failed when given exact
previous-release schema-v1 routed/terminal intents without `quality_effect`.
Malformed legacy-shaped records remained negative controls.

### Repair-bound recommendation, SAGE coverage, and CLI

Three controller tests failed before implementation:

- duplicate assessments for the latest repair caused comparison against the
  adjacent assessment rather than the preceding repair;
- an unchanged final WHAT still recommended `extend_once`; and
- a provider route set missing one authoritative SAGE issue still sealed the
  quality-budget decision.

The CLI fixture using authoritative `type` also failed because status read the
fabricated `issue_type` key. The same fixture specified score history and
per-repair deltas that the CLI did not yet render.

### Banzai/COMMANDER acceptance

The missing acceptance coverage was added through the public
`run_single_phase` controller/provider path at real proportional exhaustion.
The first valid-path run reached COMMANDER and resolved correctly; its only
initial test failure was an incorrect test assumption that the Lexicon gate was
disabled. The actual configured route was `phase1-lexicon-derive`. This is
counter-evidence to a production enforcement defect, while confirming the
reviewer's end-to-end coverage gap.

## Implementation

### 1. Older-best debt currentness

Completion finalization now adopts a candidate receipt digest only while the
current candidate is also the selected candidate (or selection is not yet
made). When ranking restores an older best candidate, its selected manifest
digest remains authoritative through debt resolution and the next prerequisite
guard.

### 2. Crash-recoverable candidate restoration

Restore effects now seal exact preimage digests for every owned artifact.
Recovery loads the candidate checkpoint bytes, recognizes each file as either
the sealed preimage or exact candidate postimage, compare-and-exchanges only
preimages, fsyncs the directory, verifies all postimages, and then creates or
recovers the single restore checkpoint. Partial replacement is therefore
idempotent, while unrelated drift fails closed.

### 3. Sealed manifest identity and digest

Candidate manifest loading accepts sealed expected SHA-256 and candidate ID
bindings and rejects non-regular files or a file that changes during the read.
Both standalone restore and combined candidate-plus-restore effects validate
those bindings before any artifact mutation. Effect state authority also binds
the digest, selected candidate, and sealed preimages.

### 4. Legacy automatic-repair migration

Trusted contiguous certified WHY2 history now derives consumed repairs as
`max(assessment_count - 1, 0)`, capped at three. A trustworthy history must
cover contiguous iterations beginning at zero; malformed or discontinuous
history retains the approved conservative iteration fallback.

### 5. Completion-outbox schema compatibility

The schema-v1 loader recognizes only the exact previous-release intent key set
without `quality_effect`, and only when its effect plan contains no quality
step. It uses an internal `{"kind":"none"}` view for execution while retaining
the exact original serialized shape for intent digest and state authority.
Current intents remain strict, and extra keys, malformed legacy records, or a
legacy quality plan are rejected. Routed and terminal recovery both pass
through public controller paths.

### 6. Repair-bound recommendation and audit evidence

Recommendation history now keeps the latest assessment representative for
each repair number and compares the latest completed changed repair with its
preceding repair. `no_artifact_progress` is an explicit veto on
`extend_once`. Sealed candidate evidence now includes comparison IDs, bounded
score history, stable decimal-domain per-gate deltas, statement/byte deltas,
baseline growth, and rationale. Status renders the new audit evidence with
bounded entry counts and string lengths; COMMANDER receives the same registered
state evidence.

### 7. Complete SAGE coverage before debt choice

Failing candidates that could become quality debt must have a unique route for
every authoritative SAGE issue and no missing or extra IDs. Severity, type, and
title are supplied from the authoritative issue ledger, and existing
non-quality-route, CRITICAL, contradiction, evidence, and product-input hard
blockers remain in force. The coverage guard is deliberately limited to
failing/debt candidates so a passing assessment is not rejected because of a
stale low-severity issue artifact; two passing-candidate regression tests
proved that boundary after an initially over-broad implementation.

### 8. Proportional banzai/COMMANDER end to end

New tests reach proportional exhaustion through a real WHY2 provider dispatch
in banzai mode. They prove:

- the prepared request contains exactly `extend_once`,
  `continue_with_debt`, and `stop`;
- registered repair and candidate evidence in the COMMANDER prompt exactly
  equals the controller state used for resolution;
- valid `continue_with_debt` resolves as `COMMANDER` and creates the durable
  debt authorization;
- an undeclared option and a declared option carrying state updates are both
  rejected;
- both attempts receive an identical sealed prompt; and
- attempt two ends in `invalid_resolution_result` with no provider mutation or
  debt artifact.

### 9. CLI SAGE type

Status now reads the authoritative SAGE `type` field. The material-finding
display remains bounded.

## Verification

- Focused candidate currentness/restoration/manifest tests: 4 passed.
- Adjacent candidate/restoration suite after the first cluster: 101 passed.
- Focused migration and exact previous-release completion recovery tests: all
  passed, including routed and terminal public recovery.
- Human routing plus CLI status after recommendation/SAGE work: 200 passed.
- Proportional/COMMANDER/CLI selection: 105 passed, 527 deselected.
- Exact Task 9 17-file suite plus completion-outbox and state-transaction
  suites: 1,688 passed in 352.39 seconds.
- `bash tests/run-all.sh`: 1,649 passed, 0 failed, 0 skipped; overall PASS.
- Package/deployment and phase-graph suite: 146 passed in 78.85 seconds.
- `bash scripts/bash/dry-run.sh`: all 9 canonical bundle checks passed.
- Full pytest: 8,798 passed, 9 skipped, 1 deselected, with exactly the three
  base-reproduced unrelated capability-policy failures:
  - `test_extension_capability_policy.py::test_cost_tuned_agents_do_not_request_strong_capability`;
  - `test_extension_capability_policy.py::test_high_risk_agents_keep_strong_capability`;
  - `test_prosaic_execution_policy.py::test_all_subagents_declare_approved_model_tier_and_effort`.
- `git diff --check` and `py_compile` over every changed Python source/test file
  passed.

## Self-review

- Restore authority is sealed before mutation and retry accepts only exact
  preimages/postimages; it never overwrites third-party drift.
- Selected-candidate digest currentness is preserved independently from the
  newly materialized candidate receipt.
- Legacy compatibility retains original serialized authority instead of
  regenerating a current intent, and does not weaken current schema validation.
- Recommendation inputs come only from validated candidate manifests and
  repair numbers; unchanged work cannot create an optimistic extension signal.
- Every quality-debt option is executable against complete authoritative SAGE
  coverage before it is shown to a human or COMMANDER.
- COMMANDER remains unable to author options, state updates, routes, or retry
  counts.
- Perfectionist routing, passing certification, one-extension limits, provider
  truth, terminal-banner behavior, and the out-of-scope Tasks Lexicon defects
  are unchanged.
