# Controller State Contracts — Final Fix Report

## Status

Complete. All consolidated whole-branch findings and the three final
transaction-audit blockers are fixed. No push or merge was performed.

Review base: `f47da6b591d85474a8b5f087e0404499631f9520`

Final HEAD: `f05848e9988e71b05a53d3140c84036ab4f138ea`

## Commits

- `75ac7649` — `fix: close controller contract startup boundaries`
- `073211eb` — `fix: seal controller routing state transactions`
- `539574d9` — `fix: guard state transactions from stale writers`
- `f05848e9` — `docs: finalize controller state transaction design`

## Finding Resolution

### Critical findings

1. Live state outside transactional advance
   - Deterministic executors and controller enrichment no longer persist
     accepted success effects before advance.
   - `PreparedPhaseResult` seals removals and terminal control updates.
   - Lexicon stale evidence/waiver cleanup, product-repair cleanup, governance
     exhaustion, and terminal routing metadata publish in the single advance
     save.

2. Replay/backward movement and unsafe rollback
   - Added `PreparedRoutingDecision`, process-local attestation, locked
     phase/revision/previous-dispatch compare-and-swap, unique dispatch
     identity, and self-loop replay protection.
   - Removed post-publication snapshot rollback and reload-based receipt
     validation.
   - Late diagnostics merge only when phase and pre-commit dispatch identity
     still match.

3. Fail-open Understanding discriminator
   - Non-`BLOCKED` results require completed evidence and scores.
   - `BLOCKED` results require error evidence and a non-empty controller
     blocked reason.
   - Cross-combinations fail closed.

4. Unbounded pre-normalization copy
   - Replaced raw recursive copying with a bounded, protocol-free detachment
     walk before normalization, validation, routing, or journaling.
   - Depth, node, collection, cycle, hostile mapping/copy/path/repr, and
     context-free redaction regressions cover the boundary.

5. Raw COMMANDER routing/state mutation
   - COMMANDER judgments are detached, result-contract validated,
     canonicalized, provenance-digested, and queued in the routing decision.
   - Transition and banzai recovery judgments publish through atomic advance.
   - Recovery uses `record_completion=false`.

### Important and minor findings

1. Registry reference closure and immutability
   - Full schema-tree profile enforcement rejects unresolved/external,
     dynamic, recursive, identifier, and default keywords.
   - Validation retrieval is disabled; schema/registry facades are immutable.

2. Remaining schema discriminator gaps
   - Deterministic Lexicon `BLOCKED`, pending spec, and structural-governance
     exhaustion/pass combinations now fail closed.

3. Missing required controller contracts
   - One central exact mapping covers all seven controller-producing roles and
     is enforced by both startup validation paths.
   - Explicit provider allowlists must be lists; top-level and nested `null`
     escapes are rejected.

4. Duplicated output inventories
   - Operational node outputs retain artifact outputs only; controller fields
     derive solely from the named registry contract.

5. Normalized-path telemetry
   - `last_dispatch` records contract identity and sorted normalized JSON
     paths without values.

### Final transaction-audit hardening

- Prepared result updates now reject transaction-owned keys, preventing
  `state_updates.phase` or `state_revision` from overriding a sealed route.
- Public snapshot saves compare their revision under the exclusive lock;
  stale snapshots cannot erase a winning phase or dispatch.
- Store-owned counters and flags use one locked read/mutate/save operation.
- SIGINT only sets an in-memory cancellation flag; state persistence is
  deferred to normal control flow, avoiding signal-context lock re-entry.

## Verification

TDD red evidence:

- Initial consolidated regression matrix: `39 failed`.
- Final audit regressions before fixes:
  - reserved destination override and stale public save: `2 failed`;
  - signal-handler store I/O: `1 failed`.

Focused green evidence:

- Final controller/state/preparation/executor/Understanding boundary:
  `360 passed in 46.63s`.
- Final state-store suite: `74 passed in 1.24s`.
- Audit regression trio: `3 passed in 0.44s`.
- Older-Python dry-run compatibility/controller subset after removing
  `dataclass(slots=True)`: `163 passed in 19.68s`.

Repository-wide release gate:

- `.venv/bin/pytest -q`
- `4602 passed, 9 skipped, 4 deselected in 308.63s`

Static and release checks:

- `.venv/bin/python -m compileall -q src` — passed.
- `git diff --check` — passed.
- `bash scripts/bash/dry-run.sh` — PASS 138, WARN 1, FAIL 0.
  The warning is the expected notice that `agents.yaml` was replaced by
  `extension.yml`.
- Version remains synchronized and unchanged at `3.7.14` in
  `pyproject.toml`, `extension/extension.yml`, and the editable project entry
  in `uv.lock`.
- No version-file diff exists against the review base.
- Tracked worktree is clean.

## Remaining Concerns

None. The one dry-run warning is expected and non-actionable.

---

## Second Fix Wave — Immutable Routing and Exact Result Boundaries

### Status

Complete. The second-wave and independent postfix-review findings are fixed.
No push or merge was performed.

Review base: `f05848e9988e71b05a53d3140c84036ab4f138ea`

Implementation commits:

- `c6cb7894` — `fix: reject recursive controller schema references`
- `9110fc26` — `fix: seal controller state transaction boundaries`

### Finding Resolution

1. Deterministic local-reference closure
   - Controller schemas are checked with a sorted local `$ref` dependency graph
     before validator construction.
   - Direct and indirect cycles fail with a stable pointer chain; valid acyclic
     reference chains remain supported.

2. Complete transaction namespace
   - `state_transaction_namespace.py` is the single ownership inventory for
     run/CAS identity, routing/history, lifecycle/diagnostics, counters, and
     Phase A identity.
   - Provider preparation, routing queues, workflow allowlists, pre-dispatch,
     conditional, and staged direct-write paths reject reserved keys.
   - Controller-only cleanup uses an attested trusted transaction-removal
     channel.
   - The final audit additionally reserved phase-dispatch recovery metadata,
     product-repair controls, convergence controls, recovery/blocked metadata,
     Phase A diagnostics, `user_request`, and derived WHY3/ASSESS2 verdicts.

3. Exact canonical agent-result receipt
   - Every `SquadAgentResult` field is read by exact type and detached through
     bounded, protocol-free scalar/container handling.
   - Missing fields, hostile subclasses, cycles, excessive depth/size, invalid
     integers, and non-finite floats become typed, redacted construction
     failures.
   - Preparation and telemetry reconstruct only from the canonical receipt and
     never retain or copy the producer object.

4. Immutable routing snapshot and final CAS
   - One frozen `RoutingStateSnapshot` is the sole state source for enrichment,
     transition evaluation, COMMANDER prompts, decision sealing, and recovery.
   - Advance compares phase, revision, and previous-dispatch identity under the
     exclusive lock, while valid unchanged-state self-loops remain supported.
   - Stale failure, repair, readiness, and recovery attempts cannot rebase onto
     newer same-phase state.

5. COMMANDER outcome and recovery semantics
   - Exit failure, timeout, provider-limit failure, invalid verdicts, and
     malformed intents are rejected before routing.
   - Ordinary routing accepts `JUDGMENT_RESOLVED` or a strict `BLOCKED` intent;
     a blocked judgment cannot select a next phase.
   - Recovery requires exact operational success, `JUDGMENT_RESOLVED`, and
     positive cleanup intent. Its question, reason, and blocked origin are
     derived only from the captured snapshot, never stale caller arguments.
   - Returned COMMANDER journals publish only after a sealed route commits.

6. Typed zero-success failure boundary
   - Ordinary, manual, skip, and recovery construction failures persist one
     redacted diagnostic only when their snapshot still matches.
   - Contract/construction failures do not publish completion history,
     dispatch identity, journals, timing, checkpoints, or product effects.

7. Post-seal external publication ordering
   - Product-input ledger updates, Phase A publication/readiness, and manual
     artifact refresh run in an exclusive post-CAS/pre-save callback.
   - Stale decisions are rejected before that callback, so they produce no
     product or publication effects.

### Verification

Focused and expanded boundary evidence:

- Controller/state/preparation/checkpoint matrix:
  `587 passed in 49.98s`.
- Expanded schema/preparation/state/executor/workflow/controller/telemetry
  matrix after postfix fixes: `780 passed in 56.47s`.
- Exhaustive transaction-ownership/removal matrix:
  `257 passed in 0.49s`.
- Full controller integration suite: `176 passed in 47.67s`.

Repository-wide release gate:

- `.venv/bin/pytest -q`
- `4929 passed, 9 skipped, 4 deselected in 353.49s`

Static and release checks:

- `.venv/bin/python -m compileall -q src tests` — passed.
- Changed-file critical Ruff rules (`E9,F63,F7,F82`) — passed.
- `git diff --check` — passed.
- `bash scripts/bash/dry-run.sh` — PASS 138, WARN 1, FAIL 0.
  The warning is the expected notice that `agents.yaml` was replaced by
  `extension.yml`.
- Version remains synchronized and unchanged at `3.7.14` in
  `pyproject.toml`, `extension/extension.yml`, and `uv.lock`.
- No version-file diff exists against the second-wave review base.

### Remaining Concerns

None in the changed surface. Repository-wide Ruff critical-only scanning still
reports pre-existing undefined forward-annotation names outside these changed
files; changed-file critical lint is clean.

---

## Durable Controller Completion Recovery

### Status

Implementation and Task 8 release verification are complete. Publication and
post-dispatch completion now use two bound durable outboxes, and a completely
new controller reconstructs and drains both authorities before phase work. No
push or merge was performed.

Completion-plan base: `35ab89de98b6c0592635589e96964e62c4c05de7`

Verification implementation HEAD:
`72a60b890edcdd7157b3251d298f7143f4b5ccd4`

### Completion Commit Ledger

- `0a9a93f1a4997e8b9379d04660d7cb7b46d9b094` —
  `feat: seal controller completion intents`
- `c45001a73b01cee276fd964ff9005b749e4973e6` —
  `feat: persist controller completion state`
- `69fdaad4db107425dfc8a3bc905293b328f5a667` —
  `feat: make completion journals replay safe`
- `51737ec2d06777bc0e57dad41ccb9b5debe0a4cf` —
  `feat: receipt timing and checkpoint completion`
- `6e02779e4a9e2c7d5d6b327916d8f46df1b5ef7c` —
  `feat: freeze context and mining completion`
- `81c572e91605b6b449d9ec30d72af3be09f020c6` —
  `fix: recover controller completion before phase work`
- `908a9b8fca76bba13b128c7ab7643f0cb810bb2b` —
  `test: prove controller completion crash recovery`
- `72a60b890edcdd7157b3251d298f7143f4b5ccd4` —
  `test: align phase4 mining fixture with durable plan`
- `cc5348cee3b5dcd93b06b736fa7fecc0e3ec76db` —
  `docs: report durable completion recovery`

The earlier publication recovery commit is `0553ae2c400aeed925ac0fb0e493d25212d969b6`
(`fix: recover controller publications before phase work`). The completion
ledger above is its durable post-dispatch successor.

### Protocol and Crash Evidence

The persisted completion intent binds origin, exact route, optional publication
marker, ordered effect plan, checkpoint prestate, frozen context reason,
mining flag, and canonical judgment digests. Exact state CAS owns publication
handoff, step advancement, bounded failure lifecycle, final dispatch or
terminal provenance, and marker clearance.

Fresh-controller tests cover:

- route CAS with and without publication, including pre-save and
  save-then-raise outcomes;
- terminal begin with and without publication under the same ambiguity;
- every publication operation, target drift, missing/corrupt stages,
  manifest/receipt mismatch, and publication handoff;
- journal replacement before receipt and before step CAS;
- tagged timing close/open and stable completion effect IDs;
- checkpoint Git commit and ledger repair;
- frozen context preparation and each visible install;
- deterministic mining, bound spec/drawer drift, and bounded outcome receipt;
- pre-save and save-then-raise for every completion state transition;
- final clear for ordinary, manual, terminal, and Phase 4 provenance;
- orphan cleanup only after fresh non-authority proof, including the bound
  external publication stage;
- exact-once token accounting and no duplicate route, file, journal, timing,
  checkpoint, context, or mining effect.

The outer-to-inner lock order is:

1. Phase A execution;
2. spec-run execution;
3. publication;
4. completion;
5. checkpoint;
6. reasoning journal;
7. telemetry;
8. state.

Same-rank reentry is accepted only for the exact same logical lock identity.
All shared journal writers participate at rank 6, and state-store mutations do
not execute controller or external callbacks while the state lock is held.

### Task 8 RED and Compatibility Resolution

The first repository-wide Task 8 run exposed one stale integration fixture:

- `1 failed, 5559 passed, 9 skipped, 4 deselected in 443.87s`;
- failing test:
  `test_phase4_publish_creates_canonical_metadata_and_mines_canonical_spec`;
- isolated reproduction: `1 failed in 1.21s`.

The fixture lacked the configured MemPalace wing now required by the durable
local drawer-ID plan, so the protocol correctly persisted a bounded failed
mining outcome before backend construction. Commit `72a60b89` added valid
fixture configuration and exact plan, mine, postimage-verification, and
completion-receipt assertions. Production code was unchanged.

Focused GREEN evidence:

- corrected test: `1 passed in 0.93s`;
- full context-memory file: `4 passed in 1.60s`;
- fixture task review: specification PASS, code quality APPROVED, with no
  Critical, Important, or Minor findings.

### Fresh Release Verification

Repository-wide gate:

- `.venv/bin/pytest -q`
- `5560 passed, 9 skipped, 4 deselected in 360.57s`

Plan-mandated gates:

- focused completion protocol suite: `1150 passed in 108.20s`;
- original expanded publication boundary suite:
  `963 passed in 89.34s`;
- post-dispatch shell hook: `13 passed, 0 failed`.

Named exact matrices:

- complete completion unit protocol: `214 passed in 2.56s`;
- fresh-controller orchestration: `64 passed in 21.71s`;
- explicit pre-save/save-then-raise ambiguity table:
  `24 passed, 40 deselected in 8.87s`;
- route and terminal begin with optional publication:
  `8 passed in 3.16s`;
- global lock-order assertions: `24 passed in 0.30s`;
- publication manifest/fault engine: `90 passed in 1.10s`;
- state-store kernel: `139 passed in 1.46s`.

Workflow and static gates:

- `bash scripts/bash/dry-run.sh` — PASS 138, WARN 1, FAIL 0;
  the warning is the expected `agents.yaml` to `extension.yml` notice;
- `.venv/bin/python -m compileall -q src tests` — exit 0;
- exact Task 8 `py_compile` command — exit 0;
- `git diff --check` — exit 0;
- `tests/unit/test_version_metadata.py` — `1 passed`.

Ruff was not installed in this environment. `.venv/bin/ruff --version`
reported `no such file or directory`, and `uv run ruff --version` reported
`Failed to spawn: ruff`. No Ruff success is claimed.

Version remains synchronized and unchanged at `3.7.14` in:

- `pyproject.toml`;
- `extension/extension.yml`;
- `src/echelon/cli.py`;
- `README.md`;
- the editable `echelon` package entry in `uv.lock`.

No version declaration changed in the completion implementation range.

### Scope Audit

The implementation range
`35ab89de98b6c0592635589e96964e62c4c05de7..72a60b890edcdd7157b3251d298f7143f4b5ccd4`
contains 8 focused commits across 46 files: 20,477 insertions and 720
deletions. The surface is limited to publication/completion orchestration,
state and receipt kernels, journal/timing/checkpoint/context/mining adapters,
their shell interoperability, lock owners, documentation, and direct tests.

`pyproject.toml`, `extension/extension.yml`, `README.md`, and `uv.lock` have no
diff in that range. `src/echelon/cli.py` changes only the completion-owned
checkpoint runtime ignore entries; its version declaration is unchanged.

### Review and Handoff

Task 7's exact-head independent rereview reported no Critical, Important, or
Minor findings and marked the task READY. The Task 8 compatibility correction
received separate specification and quality approval with no findings.

The parent workflow intentionally performs one fresh whole-branch review after
this Task 8 evidence and documentation commit. That review is not represented
as already complete here.

### Remaining Concerns

No known implementation concern. Ruff availability is the only unexecuted
optional gate and is recorded explicitly above.

---

## Controller Durable Authority — Final Verification

### Status

Complete and independently approved. Controller state, phase-timing telemetry,
checkpoint preparation, provider/controller ownership, and state locking now
fail closed at their durable authority boundaries. No push or merge was
performed.

Durable-authority implementation base:
`b91e63071f7265b5f3ba15c1b1e61298f33d1a19`

Final verified implementation HEAD:
`b239e2108f7d522c535b709ca2110eda3772c0f5`

Final whole-branch review: Critical 0, Important 0, Minor 0, APPROVE.

### Commit Ledger

Core implementation:

- `24693068` — `fix: require durable controller state authority`
- `7bfcfd9d` — `fix: atomically persist phase timing`
- `a944ca3a` — `fix: reject unavailable checkpoint prestate`
- `612c9a31` — `fix: bind durable recovery postimages`
- `40237a00` — `fix: preserve checkpoint recovery prestate`

Final-review hardening:

- `bb11d962` — `fix: close null provider allowlists`
- `8610e847` — `fix: account checkpoint failure tokens`
- `cfc8cc43` — `fix: bind state lock identity`
- `6b741e3a` — `fix: serialize state lock replacements`
- `2307fdd4` — `fix: validate controller provider allowlists`
- `5b05d9a2` — `fix: clarify provider allowlist diagnostic`
- `b239e210` — `test: align provider allowlist diagnostics`

### Verified Guarantees

1. Durable parent authority
   - Missing state/staging path components are created and synchronized into
     their parents one component at a time.
   - Atomic state replacement is authoritative only after the complete file
     and no-follow opened squad directory are fsynced.
   - Ambiguous save/recovery/final-clear postimages are adopted only after an
     exact under-lock file, directory, identity, revision, marker, and content
     confirmation. Failed confirmation performs no diagnostic write, external
     effect, marker advance, stage deletion, or orphan cleanup.

2. Exact phase-timing snapshot
   - Timing writes validate the complete prior JSONL stream, preserve its exact
     bytes, append one canonical record in memory, and atomically replace the
     whole stream.
   - Tagged-event ambiguity and fresh-controller idempotence require exact
     file-and-parent durability confirmation. Malformed or torn streams remain
     unchanged and fail closed.

3. Checkpoint prestate and token accounting
   - An active checkpoint requires one valid lowercase 40- or 64-character Git
     commit ID. Git failure, invalid output, and unborn `HEAD` fail before route
     or outbox authority.
   - The phase, dispatch metadata, workflow fields, artifacts, and both
     outboxes remain unchanged. Only consumed provider `token_usage`, the
     accounting `state_revision`, and `updated_at` may change.
   - Repeated checkpoint-prestate failures persist every provider token delta,
     so retries cannot bypass the configured budget.

4. Finite and disjoint provider allowlists
   - A controller-bearing phase and every `agents` or `pre_dispatch` override
     require an explicit list containing only non-empty strings.
   - Effective provider keys must be disjoint from the compiled
     controller-owned state keys.
   - The invariant is enforced by standalone workflow validation, direct
     `PhaseGraph` construction, and per-dispatch
     `PhaseNode.result_contract(entry)`. Legacy unbounded `None` behavior is
     retained only for nodes without controller contracts.

5. Two-writer state-lock exclusion
   - The real squad-directory inode is locked before the named `state.lock`;
     both are type/identity checked and held through the state operation.
   - Symlink, non-regular, and inode/path replacement fail closed.
   - A real two-thread regression replaces `state.lock` while writer one holds
     authority and proves writer two cannot enter until the stable directory
     lock is released. Both thread error channels are explicitly asserted.
   - The established controller lock rank remains unchanged.

### TDD and Focused Evidence

- Null allowlist runtime escape: `4 failed` RED, then `4 passed`; expanded
  contract boundary `513 passed`.
- Checkpoint token-accounting paths: `2 failed` RED, then `2 passed`; broader
  checkpoint set `33 passed`.
- True two-writer replacement race: second writer entered on RED; after stable
  directory authority the selected lock set passed, followed by
  `179 passed` for state and lock-order suites.
- Malformed/overlapping direct-runtime allowlists: `12 failed` RED, then
  selected `16 passed`; affected contract suites `525 passed`.
- Combined final-hardening gate: `1028 passed in 118.60s`.
- Final diagnostic wording regression was proven RED and the focused set
  passed after the production and test-only alignment.

### Final Release Verification

- Durability matrix:
  `785 passed in 119.49s`.
- First full suite:
  `5617 passed, 1 failed, 9 skipped, 4 deselected`.
  The sole failure was a stale diagnostic assertion; production behavior was
  already correct.
- Test-only correction:
  `b239e210` aligned the expected provider-allowlist diagnostic.
- Final full rerun:
  `5618 passed, 9 skipped, 4 deselected in 454.46s`.
- Workflow dry-run:
  PASS 138, WARN 1 expected, FAIL 0. The warning is the expected
  `agents.yaml` to `extension.yml` notice.
- `.venv/bin/python -m compileall -q src tests`: exit 0.
- `git diff --check`: exit 0.
- Version: `3.7.14` in both `pyproject.toml` and
  `extension/extension.yml`.
- Tracked status before this documentation finalization: clean.

### Review and Handoff

The final whole-branch review inspected exact implementation HEAD `b239e210`
and returned Critical 0, Important 0, Minor 0, APPROVE. The branch and isolated
worktree are preserved for the parent workflow. No push or merge was requested
or performed.

### Remaining Concerns

None. The single dry-run warning is expected and non-actionable.
