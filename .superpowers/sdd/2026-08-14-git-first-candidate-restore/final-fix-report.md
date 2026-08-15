# Final Fix Wave Report

Base reviewed: `b98f7a27ab8528131be7161e015cf2efce1e30d9`

This wave closes the one Critical and three Important merge blockers plus the
three requested Minor findings. The two deferred Tasks Lexicon defects were not
changed.

## Root causes and fixes

### 1. Active-index compare/install race and unauthenticated recovery

**Root cause.** The restore effect asked Git for the active index tree with one
process and later replaced that index with a separate `read-tree` process. The
standard Git `index.lock` therefore covered only Git's write, not the authority
comparison that justified it. A cooperating concurrent `git add` in the gap
could be overwritten. Separately, `_build_git_first_plan` retried every plan
construction failure through recovery; recovery reconstructed a plan without
first proving that the exact transaction had begun, so even a no-follow failure
on a symlinked active index could reach the recovery path.

**Fix.** `git_first_restore.py` now:

- resolves the active index lexically and opens every parent directory plus the
  index with no-follow semantics;
- acquires the adjacent standard Git `index.lock`, captures byte/inode/mode/time
  authority, derives the tree from an isolated copy, and rechecks the same
  snapshot while the lock remains held;
- builds the target index away from the active index, verifies its exact target
  tree, then compares the expected bytes/tree and atomically installs and fsyncs
  the prebuilt index through the held standard lock;
- admits recovery only for a canonical mode-`0600`, byte-exact journal for the
  reconstructed plan, or for the exact target ref/index/worktree state; and
- validates the active index before recovery reconstruction can bypass a
  symlink rejection.

**TDD evidence.** The public controller tests were first run against the old
effect path:

```text
.venv/bin/pytest \
  tests/integration/test_squad_controller.py::TestProportionalQualityController::test_restore_index_install_rejects_concurrent_unrelated_staging \
  tests/integration/test_squad_controller.py::TestProportionalQualityController::test_pending_restore_retry_rejects_symlinked_active_index -q
FF
2 failed in 9.16s
```

The race completed the restore and replaced the injected unrelated stage; the
retry followed/replaced the symlinked index instead of remaining pending. After
the fix, the same command reported `2 passed in 5.89s`. Both paths now remain
blocked, preserve the unrelated/victim bytes, and emit no restore checkpoint
receipt.

### 2. Replace-ref substitution during selected-checkpoint reads

**Root cause.** Candidate mode/blob and identity reads used ambient `ls-tree`,
`cat-file`, and `show` behavior. A replace ref could substitute a commit that
retained the expected trailers and blob contents but changed an executable entry
from `100755` to `100644`.

**Fix.** `run_git_hardened` centralizes authority-sensitive Git reads with
system/global/command config isolated, replacement objects and optional locks
disabled, and repository/object/index/common-directory redirectors removed from
the environment. Candidate preflight now requires a canonical full checkpoint
OID, reads its exact tree entry and blob through that runner, checks the exact
path, regular-blob mode, blob OID, bytes, and SHA-256, and reads the raw commit
object for identity trailers.

**TDD evidence.** The real loader/preflight test creates an executable
checkpoint and an active replacement commit with the same blob/message but a
non-executable tree entry:

```text
.venv/bin/pytest \
  tests/unit/test_proportional_quality.py::test_candidate_preflight_ignores_replace_refs_and_pins_executable_mode -q
F
AssertionError: assert '100644' == '100755'
1 failed in 0.76s
```

The focused replacement-ref path then passed, and the complete proportional
quality file reported `72 passed in 7.11s`.

### 3. Missing or duplicated command summaries

**Root cause.** Spec and delivery summaries were emitted only at the normal
controller/coordinator tail. Existing-run checkpoint returns, schema-v2 decision
submission, and controller/coordinator exceptions bypassed that tail. The model
fallback and blocked landing row also rendered deterministic next actions owned
by the outer terminal card, producing repeated `Next` commands.

**Fix.** Command-level `ContextVar` scopes now cover public `spec run`,
`continue`, `resume`, and delivery skill execution. A scope registers the valid
durable run identity, tracks normal emission, and in `finally` derives a fallback
card from durable state if needed. The emitted bit is set only after the banner
is written. Fallback rendering catches `BaseException` solely to preserve the
original exception/exit code. Early banners mark when they already own the next
instruction. The model/fallback no longer renders `Next`, and blocked landing
uses the single outer `next` row. Delivery fallback also tolerates malformed
durable counters rather than losing the card.

**TDD evidence.** The coordinator exception test initially preserved the
exception but rendered no card:

```text
.venv/bin/pytest \
  tests/unit/test_run_skill.py::TestRunSkillAutoLand::test_coordinator_exception_still_emits_one_delivery_summary -q
F
AssertionError: assert 0 == 1  # DELIVERY SUMMARY count
1 failed in 0.35s
```

The durable-counter variant was independently RED with the same missing-card
assertion (`1 failed in 0.34s`) and GREEN after fail-closed counter parsing
(`1 passed in 0.30s`). Public tests cover early `spec continue`, schema-v2
`spec resume`, spec-controller exception, delivery-coordinator exception, normal
delivery/blocked landing, and existing provider-limit/debt truth. The final
focused matrix below contains all of those paths and passed.

At the reviewed base, the public continue and resume control flow returned
directly after their checkpoint/decision banners and therefore never reached
`_print_squad_summary`; those two tests were added at the public command/session
boundary and are GREEN. This report does not invent a pre-change pytest duration
for tests that were introduced after that control-flow reproduction.

### 4. Unbounded, loose, and contradictory summarizer protocol

**Root cause.** The prompt had drifted to three-to-seven plain-text lines and the
parser rejected JSON while loosely cleaning arbitrary text. Inspection evidence
was serialized without the approved aggregate cap. The parser had no exact
schema, sentence, byte, ANSI/OSC/control, general terminal-status, verification,
or provider-limit validation. Only a debt-specific family of success claims was
guarded.

**Fix.** The provider contract and runtime prompt now require exactly one strict
JSON object with sole key `bullets` and two-to-four strings. Parsing rejects
duplicate/extra keys, invalid counts/types, multi-sentence or unpunctuated
strings, Markdown-leading strings, ANSI/OSC/C0/C1 content, lines over 280 UTF-8
bytes, and narrative totals over 900 UTF-8 bytes. Terminal contradiction checks
cover status, verification, provider-limit, and quality-debt truth. The model
cannot restate the deterministic next command. Inspection is supplied only
through a priority-preserving compact evidence packet capped at 12 KiB,
including absolute path and bounded aggregate content; file reads themselves
are bounded. JSON-expanding control data is normalized and serialized-aware
truncation prevents it from escaping the cap. Invalid output falls back to the
deterministic human-readable card.

**TDD evidence.** The initial public summary selection reported
`3 failed, 11 passed`: plain text was still accepted, the prompt had no bounded
`<evidence_packet>`, and fallback output repeated `Next`. After the protocol
change, the complete summary file reported `77 passed`; the later self-review
case for JSON-expanding controls first failed with
`ValueError: summary evidence packet exceeds its byte budget`
(`1 failed in 0.31s`) and then passed (`1 passed in 0.26s`). The current file is
`78 passed in 0.34s`.

### 5. Minor findings

- **Next ownership:** deterministic next rendering belongs to the terminal card
  or the already-rendered checkpoint banner. Model restatements, fallback
  restatements, and the blocked-landing nested instruction are removed.
- **Schema-v2 integer identity:** currentness now requires
  `type(schema_version) is int`; JSON `2.0` and booleans fail closed while exact
  legacy v1 behavior remains mode-gated and unchanged. The new float test was
  RED with `assert not True` and is GREEN.
- **Wrong parent:** a raw commit-object negative now keeps the exact target
  tree/message and replaces only the parent. It is rejected by the existing
  exact commit authority check. This was a coverage-only finding, so the new
  test was GREEN without a production-code change.

## Changed files

- `src/harness/git_first_restore.py` — locked/no-follow active-index authority,
  prebuilt atomic install, authenticated recovery.
- `src/echelon/git_helpers.py` — shared hardened authority-sensitive Git runner.
- `src/harness/proportional_quality.py` — hardened canonical checkpoint,
  tree/blob/mode/identity reads.
- `src/echelon/cli.py` — spec command emit-once scope and deterministic-next
  ownership.
- `src/harness/skills/run_skill.py` — delivery emit-once scope, durable exception
  summary, single landing next action.
- `src/harness/run_summary.py` — bounded evidence packet, strict JSON protocol,
  output safety and contradiction checks.
- `prosaic/subagents/echelon.summarizer.md` — matching deployed provider
  contract.
- `src/harness/phase1_quality.py` — exact integer schema version.
- `tests/integration/test_squad_controller.py` — public concurrent-stage and
  symlinked-index retry negatives.
- `tests/unit/test_proportional_quality.py` — executable-mode replace-ref
  preflight.
- `tests/unit/test_cli_run_summary.py`, `test_cli_mode_args.py`,
  `test_cli_resume_escalation_options.py`, `test_run_skill.py` — public
  emit-once and single-next coverage.
- `tests/unit/test_run_summary.py` — strict schema, safety, contradiction,
  12-KiB aggregate evidence, and next deduplication coverage.
- `tests/unit/test_phase1_quality.py` — `2.0` rejection.
- `tests/unit/test_git_first_restore.py` — exact-tree/message wrong-parent
  negative.

## Final verification

Focused public defect matrix:

```text
.venv/bin/pytest <25 explicit public-path node IDs> -q
25 passed in 9.69s
```

Complete affected restore/controller/certification matrix:

```text
.venv/bin/pytest tests/unit/test_git_first_restore.py tests/unit/test_proportional_quality.py tests/unit/test_phase_checkpoints.py tests/unit/test_squad_completion.py tests/unit/test_squad_phase_checkpoints.py tests/unit/test_phase1_quality.py tests/unit/test_phase1_quality_debt.py tests/integration/test_human_input_routing.py tests/integration/test_squad_controller.py -q
1144 passed in 393.76s
```

Outbox/publication plus summary/CLI/skill matrix:

```text
.venv/bin/pytest tests/unit/test_publication_transaction.py tests/unit/test_squad_publication.py tests/unit/test_state_transaction_namespace.py tests/unit/test_run_summary.py tests/unit/test_cli_run_summary.py tests/unit/test_cli_continue.py tests/unit/test_cli_resume_escalation_options.py tests/unit/test_cli_resume_spec_context.py tests/unit/test_cli_mode_args.py tests/unit/test_cli_status.py tests/unit/test_core_cli_run_discovery.py tests/unit/test_cli_run_dir_gitignore.py tests/unit/test_run_skill.py -q
365 passed in 2.64s
```

After the final packet/self-review refinements, the directly affected
summary/CLI/skill/replace-ref matrix was rerun:

```text
.venv/bin/pytest tests/unit/test_run_summary.py tests/unit/test_cli_run_summary.py tests/unit/test_cli_continue.py tests/unit/test_cli_resume_escalation_options.py tests/unit/test_cli_mode_args.py tests/unit/test_run_skill.py tests/unit/test_proportional_quality.py -q
279 passed in 11.36s
```

Package/deployment/runtime prompt matrix:

```text
.venv/bin/pytest tests/unit/test_prosaic_package_install.py tests/unit/test_workspace_init_deploy_runtime.py tests/kernel/test_phase_graph.py tests/unit/test_prosaic_prompt_loader.py tests/unit/test_prosaic_provider_deployment.py tests/unit/test_prosaic_constitution_runtime.py tests/unit/test_skill_loader_prosaic.py -q
164 passed in 79.58s
```

Repository runner and bundle validation:

```text
bash tests/run-all.sh
Total: 1649 passed, 0 failed, 0 skipped
OVERALL: PASS

bash scripts/bash/dry-run.sh
Bundle validation passed: 9 checks
```

Final hygiene before staging:

```text
.venv/bin/python -m compileall -q src tests/unit tests/integration
exit 0

git diff --check
exit 0
```

The staged scope was then checked against the file list above before commit.

## Compatibility and authority notes

- SHA-1 and SHA-256 full OIDs remain accepted; tree modes remain pinned to
  regular `100644`/`100755` blobs.
- Active-index replacement uses Git's standard adjacent lock and preserves the
  active index mode. Split/sparse index bytes are interpreted through an
  isolated `GIT_INDEX_FILE`, not rewritten through ambient state.
- Schema-v1 quality certificates retain the approved perfectionist-only legacy
  compatibility. Proportional schema-v2, SAGE PASS/debt, provider-limit,
  checkpoint, outbox, and perfectionist contracts are unchanged.
- The visible `Worked on` narrative remains human-readable even though the
  provider protocol is strict JSON. Deterministic status/debt/provider/next
  truth remains controller-owned.
- The two deferred Tasks Lexicon findings remain untouched.

## Self-review and concerns

The final diff was audited for lock ownership, symlink/inode checks, journal
authentication, fsync ordering, replacement-ref/config bypasses, exception
preservation, exact-once emission, strict-output failure behavior, evidence
byte accounting, and unrelated edits. That review found and fixed two local
issues before final verification: an accidental unrelated `BaseException`
catch in harness initialization was reverted, and JSON-expanding evidence was
given serialized-aware bounds. A malformed durable counter was also reproduced
and made unable to suppress the exception card.

No architectural conflict or unsafe staged-state compromise remains known.
The controller owns the requested scoped re-review and repeat broad matrix.
