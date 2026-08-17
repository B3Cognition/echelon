# Second final fix wave report

## Scope and finding validation

The three remaining Important findings were validated against the production
controller, completion outbox, checkpoint, debt-currentness, publication, CLI,
and summary paths before implementation. All three were confirmed:

1. Candidate restoration classified a final component with `lstat()` and then
   read and verified it by path. A regular file could therefore be replaced by
   a symlink between classification and read. The atomic exchange primitive
   also depended on `finally` cleanup; process death after exchange could leave
   the displaced preimage in the spec directory, where whole-spec checkpoint
   pathspecs would stage it.
2. Candidate ranking loaded a parsed manifest, but selected-manifest sealing
   later reread the path to calculate its digest. A same-data replacement in
   that window could make recommendation and ranking describe the first file
   while the restore seal described the second.
3. Exact SAGE route coverage was conditional on Understanding `pass == false`.
   Numeric PASS plus provider/SAGE FAIL therefore captured a zero-failed-gate
   candidate, after which recommendation and debt validation rejected it.
   Debt currentness and summaries also assumed at least one numeric failed
   gate.

The deferred downstream Tasks Lexicon recovery-command and publication-summary
defects were not changed.

## RED evidence

### Restore race and hard-kill recovery

Two production-path controller regressions failed before implementation:

- a crafted regular-to-symlink replacement between restore classification and
  read was followed and committed as Git mode `120000`; and
- a persisted postimage-target/displaced-preimage-temp state plus its expected
  deterministic journal was ignored on retry, leaving the journal and staging
  the exchange residue into the restore checkpoint.

The ordinary partial-replacement retry test remained as an adjacent recovery
control.

### Single manifest snapshot

A ranking hook replaced the selected manifest after parsing but before the
later digest read. Before implementation, the controller adopted the digest of
the replacement and completed the restore instead of failing closed against
the bytes that supplied ranking and recommendation.

### Qualitative-only SAGE debt

Seven focused paths were RED before implementation:

- guided/human qualitative-only acceptance;
- banzai/COMMANDER qualitative-only acceptance;
- missing and duplicate authoritative routes with numeric PASS;
- recommendation from all-passing numeric gates with qualitative debt;
- CLI qualitative-debt facts; and
- the human-readable qualitative-debt summary truth.

The coverage negatives proved that the old report-pass condition allowed a
candidate ID to be recorded before the integrity block.

## Implementation

### 1. Pinned restore and deterministic exchange recovery

Restore classification and verification now read regular files only through
`O_NOFOLLOW` descriptors tied to a pinned directory and the same entry
identity. A deterministic completion-bound exchange journal is written and
fsynced under the run artifact root before mutation. Each owned artifact has a
deterministic temp name and sealed preimage/postimage digests.

Retry reconciles only the valid states:

- target preimage plus temp postimage: perform the atomic exchange;
- target postimage plus temp preimage: clean the displaced preimage;
- target postimage plus no temp: already finalized.

Every other state fails closed. Exchanges and cleanup fsync the pinned spec
directory; journal creation and removal fsync the journal directory. All
postimages are descriptor-verified before the completion checkpoint. Restore
temp pathspecs are excluded from whole-spec staging, and checkpoint validation
rejects restore residue and non-regular Git modes.

### 2. One pinned manifest snapshot for rank and seal

Persisted candidate loading now yields `QualityCandidateSnapshot`, containing
the parsed manifest and SHA-256 of those exact bytes read from one pinned,
no-follow regular-file descriptor. Decision preparation reads each persisted
manifest once. Ranking, repair history, recommendation audit, selected
candidate evidence, and restore sealing reuse the same snapshot. A replacement
after selection therefore fails the existing effect-time digest check before
restore mutation.

### 3. Executable qualitative-only debt

Candidate capture now keys exact authoritative SAGE coverage to the actual
proportional failure path, not the numeric report result. A failure requires an
authoritative FAIL verdict, a nonempty issue set, and unique exact route
coverage. Existing CRITICAL, contradiction, non-quality-route, evidence, and
product-input blockers remain unchanged.

Recommendation evidence carries a bounded qualitative failure count. Numeric
extension recommendation now explicitly requires a nonempty set of failed
numeric gates, eliminating vacuous `all(...)` success. Qualitative-only debt is
therefore meaningfully audited and recommends explicit debt acceptance while
retaining the executable one-extension option at initial exhaustion.

Debt build, verification, currentness, downstream pinned context, publication,
CLI status, and the run summary now accept and preserve the valid shape
`failed_gates: []` plus nonempty authoritative `qualitative_debt`. They do not
fabricate a numeric failure or change Understanding PASS.

## Verification

- Focused restore/race/hard-kill/drift/manifest controls: 7 passed.
- Proportional controller class: 47 passed.
- Human-input routing: 177 passed.
- Debt/currentness: 59 passed.
- Publication: 103 passed.
- CLI plus run summary: 127 passed.
- Completion/state/human adjunct suites: 247 passed.
- Exact expanded Task 9 17-file feature suite: 1,474 passed in 329.08 seconds.
- `bash tests/run-all.sh`: 1,649 passed, 0 failed, 0 skipped; overall PASS.
- Package/deployment/phase-graph suite: 146 passed in 79.08 seconds.
- `bash scripts/bash/dry-run.sh`: all 9 canonical bundle checks passed.
- Full pytest: 8,808 passed, 9 skipped, 1 deselected, with exactly the three
  previously base-reproduced unrelated capability-policy failures:
  - `test_extension_capability_policy.py::test_cost_tuned_agents_do_not_request_strong_capability`;
  - `test_extension_capability_policy.py::test_high_risk_agents_keep_strong_capability`;
  - `test_prosaic_execution_policy.py::test_all_subagents_declare_approved_model_tier_and_effort`.
- `git diff --check` and `py_compile` over every changed Python source and test
  passed.

## Self-review

- No restore read or verification follows an owned artifact symlink; descriptor
  identity is checked before and after every read.
- Journal recovery is deterministic across process death, never guesses at
  unexplained temp state, and removes all exchange material before checkpoint.
- A later manifest path replacement cannot change the digest authority used by
  ranking and recommendation.
- Qualitative-only debt requires actual authoritative non-critical SAGE issues;
  empty numeric and empty qualitative debt remains invalid.
- Extension is never recommended from an empty numeric comparison, while human
  and COMMANDER receive the same executable registered option contract.
- Passing provider/SAGE assessments still capture their normal candidate and do
  not acquire debt coverage requirements.
- Perfectionist behavior, one-extension limits, provider truth, and the two
  explicitly deferred Tasks Lexicon defects remain out of scope and unchanged.
