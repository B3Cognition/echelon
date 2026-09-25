# Provider Output Publication Regression Audit

Use this document when reviewing or refactoring Echelon's provider-driven
workflow executors. It captures a systemic artifact-publication weakness found
during a real Phase 3 consensus run and defines the invariant the refactored
controller must enforce.

The implementation may move. Verify behavior and ownership rather than matching
the current class or function names.

## Executive summary

An agent verdict is not sufficient evidence that its artifacts were published.
A provider process may exit successfully even when an individual Write or Edit
tool call failed. Existing files from an earlier attempt can then make a phase
appear complete.

At the time of this audit:

- 28 provider-driven phases in `runtime/workflow/definition.yaml` declare
  filename-like outputs;
- only 6 phases are covered by `_MANDATORY_PHASE_OUTPUTS`;
- those 6 checks prove only that a path exists, not that the current dispatch
  produced or declared it; and
- the initial Phase 3 WHY3 dispatch has a bespoke stronger check, added after
  the observed incident.

This is therefore a systemic controller-design risk, not merely a SAGE prompt
problem. One incident is confirmed; other paths described below are
code-level exposures and must be tested rather than assumed to have failed in
production.

## Confirmed incident

During `phase3-consensus`, older `issues.md` and `quality-gates.md` files were
already present from a prior consensus iteration.

The next SAGE dispatch followed this sequence:

1. SAGE attempted to update both reports.
2. Claude's Write/Edit operations failed with `EPERM`. Its atomic-write
   implementation needed a temporary sibling and rename, while the macOS
   sandbox allowed only the final filename.
3. The provider process still completed and returned a valid
   `echelon_result`, including `output_files: []`.
4. `StagedParallelExecutor` validated the verdict and state-update schema but
   did not validate SAGE's mandatory artifact publication.
5. The old reports remained on disk and were available to downstream logic.
6. Consensus retried without exposing the actual publication failure.

The dangerous distinction is:

```text
file exists on disk
    != agent claims the file in output_files
    != this dispatch successfully published the file
```

## Root cause

Result validation and artifact publication validation are separate, unevenly
implemented concerns.

The shared result validator checks such things as:

- result shape;
- verdict validity;
- state-update ownership and types;
- journal-entry list shape; and
- selected domain-specific response fields.

It does not establish a required artifact contract or prove publication of the
declared `output_files`.

Artifact checks are then implemented by individual executors:

- `AgentExecutor` has a six-phase mandatory-output map;
- `StagedParallelExecutor` has consensus-specific checks;
- `ConditionalSequentialExecutor` has no corresponding artifact check; and
- deterministic gates validate selected on-disk artifacts but generally cannot
  identify which dispatch produced them.

This duplication allows specialized executors to omit a correctness step while
still correctly validating the agent's result schema.

## Current exposure map

### Ordinary agent phases

The current generic mandatory-output map covers:

```text
phase1-what
phase1-investigate
phase1-lexicon-derive
phase3-how
phase3-sentinel
phase3-plan
```

For these phases, the normal check is based on `Path.exists()` or directory
existence. A valid artifact left by an earlier dispatch can satisfy it even when
the current provider call performed no successful write.

Other ordinary phases with declared files are outside this map. Important Phase
A examples include discovery, synthesis, modeling, tracking, WHY1, constitution,
WHY2, feasibility, strategic overview, and tracker alignment.

### Phase 1 WHY2

WHY2 declares `quality-gates.md` and `issues.md`, but it is not in the generic
mandatory-output map. It uses the ordinary agent executor, so the same broad
failure class remains possible there unless the refactored controller adds a
shared publication contract.

### Phase 3 consensus

Review each dispatch independently:

- **Initial WHY3:** The current branch now requires `issues.md` and
  `quality-gates.md` to exist and be declared in the current result. This is an
  immediate regression guard, not the desired final architecture.
- **ASSESS2:** PLAN2 currently requires an on-disk
  `implementability-report.md`, but existence alone can be satisfied by an
  earlier report. `estimates.md` has the same provenance concern.
- **PLAN2:** A successful verdict is not generically tied to publication of
  `tasks.md`, `critical-path.md`, `risk-matrix.md`, or `dependencies.md`.
  Candidate fingerprinting detects some unauthorized changes, but it is not a
  general publication receipt.
- **Fresh selected-issue revalidation:** The additional SAGE dispatch used
  after candidate changes must pass through the same report-publication guard;
  a check attached only to the initial Stage 1 loop is insufficient.
- **Read-only SAGE work assessment:** This is intentionally a structured-result
  dispatch with no artifact output. A shared pipeline must support explicit
  no-output contracts rather than assuming every agent writes files.

### Conditional specialists

`phase3-specialists` conditionally dispatches GUARDIAN, INVESTIGATOR, ORACLE,
BENCHMARK, ADVOCATE, and MAVERICK. Their declared reports are not passed through
the ordinary mandatory-output checks. The executor validates and persists
result state, then proceeds.

### Deterministic gates and final readiness

Deterministic Lexicon, structural, Understanding, and final-readiness checks are
valuable semantic safety nets. They do not solve dispatch provenance:

- a stale but valid artifact may pass again;
- a gate often validates only its selected artifact family; and
- final readiness proves that a package is structurally present, not which
  provider invocation published each member.

Do not count a later deterministic validator as a publication receipt unless it
is explicitly bound to the producer dispatch and its output manifest.

## Required architectural invariant

No provider-backed executor may persist or route an agent verdict before one
shared post-dispatch pipeline has validated that dispatch's artifact contract.

The required sequence is:

```text
provider result
  -> result schema and state-ownership validation
  -> dispatch-bound artifact publication validation
  -> semantic artifact validation
  -> durable journal and state mutation
  -> routing
```

This applies to ordinary, staged-parallel, conditional-sequential,
pre-dispatch, retry, repair, and revalidation calls. Specialized executors may
own sequencing, but must not reimplement or bypass result finalization.

## Preferred publication design

The strongest design is controller-owned staging and publication:

1. Before dispatch, derive a typed artifact contract from the selected phase
   and agent assignment.
2. Allocate a dispatch-specific staging directory and immutable dispatch ID.
3. Grant the provider write access only to declared staged targets.
4. Require the result manifest to identify the staged outputs.
5. Validate paths, file types, symlinks, required/optional membership, content
   contracts, and any phase-specific semantics.
6. Atomically publish validated artifacts to the active spec directory.
7. Persist a publication receipt bound to the dispatch ID, input identity, and
   published artifact digests.
8. Only after publication succeeds, persist the verdict and route the phase.

Under this model, pre-existing canonical files cannot satisfy the current
dispatch. The controller is the publisher, so a model cannot establish
publication merely by listing a path in `output_files`.

If staging is not adopted immediately, the minimum transitional control is:

- capture a pre-dispatch artifact snapshot;
- require all mandatory outputs in the current result manifest;
- validate that every declared path is an allowed, non-symlink target;
- verify every required path after dispatch;
- bind the verification result to a dispatch ID; and
- prevent routing when publication evidence is absent.

A digest change alone must not be the only proof: rewriting an identical valid
artifact can legitimately retain the same digest. Conversely, a model's
`output_files` claim alone is not proof that a tool call succeeded.

## Refactor audit procedure

### 1. Inventory provider dispatch sites

Find every call that can invoke a provider. Include nested retries and repair
review calls, not only executor entry points.

```bash
rg -n \
  '_exec_agent_with_contract|exec_agent\(|run_agent\(|run_prompt\(' \
  src/harness
```

For each site, record:

```text
caller
phase or assignment type
expected files
result validator
publication validator
state writer
routing decision
```

### 2. Inventory declared file outputs

Inspect workflow-level phase and nested-agent outputs:

```bash
rg -n \
  '^  - id:|type: (agent|staged_parallel|conditional_sequential)|outputs:' \
  runtime/workflow/definition.yaml
```

Do not derive the production contract by applying a filename regex to free-form
prose. The refactored graph should expose typed required, optional, mutable, and
read-only artifact declarations.

### 3. Locate the single finalization boundary

Search for verdict validation, journal writes, state writes, and transitions:

```bash
rg -n \
  'validate.*result|output_files|write_journal|state_store.*save|transition|route' \
  src/harness
```

Fail the audit if any provider result can reach a state writer or router without
passing through the shared artifact-publication validator.

### 4. Check all dispatch variants

Explicitly inspect:

- ordinary agent execution;
- pre-dispatch agents;
- staged Stage 1 and Stage 2 agents;
- final-review and selected-issue revalidation calls;
- conditional specialists;
- repair and retry calls;
- result-only/read-only agents; and
- provider-specific result-repair retries.

### 5. Verify provider permissions separately

The publication contract and sandbox permissions must agree. Test at least:

- exact canonical absolute paths;
- atomic writes using a temporary sibling and rename;
- denial of unrelated siblings and unrelated temporary files;
- denial of control-plane paths;
- path traversal and symlink aliases; and
- identical behavior across supported providers where equivalent containment
  is promised.

## Required regression scenarios

The refactored controller should have tests for all of the following.

### Missing first-generation output

No prior artifact exists. The provider returns success without publishing a
required output. The phase must block before state or routing is committed.

### Stale output with empty manifest

A valid old artifact exists. The provider returns success with
`output_files: []`. The old artifact must not satisfy the current dispatch.

### Tool failure with successful provider exit

Simulate a Write/Edit failure followed by a syntactically valid successful
result. The controller must report publication failure, not agent success.

### False output claim

The result lists a required path although no successful staged publication
occurred. The phase must block. This distinguishes a real publication receipt
from trusting model-authored metadata.

### Identical valid rewrite

The provider publishes valid content identical to the existing artifact. The
dispatch should succeed when a real publication receipt exists; unchanged
digest alone must not be treated as proof of failure.

### Partial multi-file publication

For a phase requiring multiple artifacts, publish only a subset. The phase must
report every missing required artifact and must not partially route.

### Parallel isolation

In a staged or parallel phase, one agent's successful artifacts must not satisfy
another agent's contract. Each result and receipt must be identity-bound.

### Retry isolation

A retry must not inherit publication success from the previous attempt merely
because canonical files remain present.

### Read-only dispatch

An explicitly no-output assessment must succeed without fabricated file
requirements while remaining unable to write candidate artifacts.

### Sandbox boundary

Atomic replacement of an authorized output must succeed. Writes to arbitrary
sibling, temporary, source, or control-plane paths must fail.

## Acceptance criteria for the refactored workspace

Mark the issue resolved only when all statements below are true:

- [ ] There is one shared provider-result finalization entry point.
- [ ] Every provider dispatch site uses it before durable state mutation or
      routing.
- [ ] Artifact contracts are typed and assignment-specific.
- [ ] Required, optional, read-only, and no-output assignments are distinct.
- [ ] Existing canonical files cannot satisfy a new dispatch by existence
      alone.
- [ ] Model-authored `output_files` are treated as claims, not publication
      authority.
- [ ] Publication receipts are controller-owned and dispatch-bound.
- [ ] Staged and parallel agents have independent artifact identities.
- [ ] Semantic validators consume the artifacts from the same publication
      receipt they certify.
- [ ] Provider sandboxes support authorized atomic publication without opening
      arbitrary sibling writes.
- [ ] All regression scenarios in this document pass.

## Expected audit report

Return one row per provider dispatch family:

```text
Dispatch family | Artifact contract | Shared finalizer | Publication proof | State-before-proof risk | Tests | Status
```

Use these statuses:

- **present** — the invariant is implemented and covered by a meaningful test;
- **partial** — some outputs or dispatch variants bypass it;
- **missing** — success can be routed without dispatch-bound publication proof;
- **changed intentionally** — the refactor uses a different mechanism that
  provides equivalent or stronger evidence.

Do not mark the audit complete merely because every expected file exists after
an end-to-end happy-path run. The regression specifically concerns stale files,
partial writes, provider tool failures, and specialized dispatch paths.

## Current implementation landmarks

These paths are discovery aids for the source branch and may change during the
refactor:

```text
src/harness/echelon_result_schema.py
src/harness/squad_executors.py
src/harness/squad.py
src/harness/phase_a_readiness.py
runtime/workflow/definition.yaml
runtime/templates/echelon-result-template.yaml
tests/unit/test_ai_cli_backend.py
tests/unit/test_claude_delivery_scope.py
tests/kernel/test_squad_executors_journal.py
tests/integration/test_squad_controller.py
```

The immediate WHY3 regression tests in the source branch are:

```text
test_claude_backend_enforces_prompt_file_scopes
test_claude_workspace_sandbox_allows_atomic_replace_for_declared_output
test_claude_exclusive_scope_wires_atomic_write_profile
test_staged_why3_requires_current_review_reports_in_output_files
```

Treat those tests as a minimum compatibility floor. They do not replace the
shared publication-pipeline tests required above.
