# Task 1 implementation report

## Scope and implementation

Implemented the task brief's early negative boundary only. The starting commit
was `6eb07d8c5f8169880bac7068ffd033789bfc9a8b`; all work stayed in
`/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`.
Read the task brief first, implementer instructions, repository AGENTS/CLAUDE,
TDD (including writing-good-tests), and verification instructions. No subagents,
reviewers, real providers, services, Docker, global installation, main mutation,
or stopped-smoke edits were used. No other ledger or whole-plan history was read.

The store's `require_unmanaged_execution` validates exact native text and a
nonempty unique exact tuple before entering one existing query-only transaction.
Indexed spec/run presence refuses without reading request/source payloads. The
global orphan registration check is limited to the managed-operation partial
index joined to the unique managed registration operation index. It performs no
full audit, mutation, repair, enrollment or history scan. Ordinary errors leave
the exception handler before emitting a bounded `IdentityStoreError`, with no
cause/context; process-control exceptions propagate.

The focused adapter rejects any present managed key, preserves truly absent
authority without initialization/Markdown I/O or unrelated legacy field
validation, and opens established authority with the native open method. It
checks the physical run plus the independent optional declared run and spec.
Root amended the brief during implementation to make explicit `.echelon` parent
lstat validation mandatory; that amendment is covered by its own real RED/GREEN
below. The check does not add broad project-root ancestor validation to the
no-authority route.

The controller calls one bool helper after both existing execution leases and
before completion recovery, retarget emission, orphan cleanup or phase work.
Rejection returns an unsaved synthetic blocked result with the physical run
name. All four public human-input boundaries raise the existing handled
`HumanInputPolicyError`, outside the adapter's identity error handler, before
decision/recovery writes. Earlier read-only argument/policy ordering stays intact.
There is no CLI change or false returned-False submission route on exclusion.

Six scoped files changed: `src/harness/element_identity_store.py`,
`src/harness/squad.py`, new `src/harness/element_identity_legacy_guard.py`, new
`tests/unit/test_element_identity_legacy_guard.py`, new
`tests/unit/test_squad_identity_exclusion.py`, and
`docs/element-identity-storage.md`. The storage documentation adds the current
bounded exclusion and retains earlier historical evidence with its original
limits, plus all missing positive managed admission, enrollment concurrency,
recovery, producer, graph, publication and repair integrations.

## Test chronology (all commands and outcomes)

Every pytest command below used the exact executable
`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest`, from the worktree
above, and ended with `-q`. Commands are listed in execution order; there were no
other pytest runs. No fixture failure is represented as an implementation RED.

1. **Required real existing-behavior RED, before any production edit:**
   `tests/unit/test_squad_identity_exclusion.py::test_managed_run_refuses_legacy_recovery_before_any_effect -q`
   returned exit 1: `1 failed in 0.40s`.
   Failure was `AssertionError: assert 'completed' == 'blocked'`, at the first
   blocked-status assertion (line 107 then). The resolved temporary project had
   an actual empty selected run-local tree, a sealed native publication/source
   inspection, native source-manifest capture, real source registration and
   managed genesis, and real `SquadStateStore.initialize(managed_identity=...)`.
   Only the downstream recovery/retarget/cleanup/execute callbacks were replaced
   with narrow observation spies. Existing public `run` reached the legacy
   callbacks and returned the callback's completed result. The test includes
   original state bytes, SQL dump and provider assertions. There was no initial
   fixture error. Root was notified of this exact RED before production edits.

2. After the initial query/adapter/controller implementation, the identical
   command returned exit 0: `1 passed in 0.43s` (**first GREEN**).

3. `tests/unit/test_element_identity_legacy_guard.py -q`
   returned exit 0: `73 passed in 2.48s`. This was the first complete focused
   authority/adapter expansion. It covered native ownership matches, reopen,
   query tracing/authorizer/EXPLAIN evidence, damaged matching payloads, orphan
   managed operations, exact invalid IDs before transactions, width controls,
   absent authority, malformed/present authority, and bounded failures.

4. Root requested the precise `.echelon` parent-presence clarification. Before
   changing production, ran
   `tests/unit/test_element_identity_legacy_guard.py::test_present_invalid_authority_parent_is_not_absence -q`.
   Exit 1: `2 failed, 1 passed in 0.22s`. Both `[dangling]` and `[symlink]` failed
   with `Failed: DID NOT RAISE <class 'harness.element_identity_store.IdentityStoreError'>`;
   the `[file]` control already refused. Root was notified before correction.
   This was a second genuine RED against the then-current adapter, distinct from
   the original controller RED.

5. Added parent lstat; absent parent permits, any present non-directory (including
   a symlink) refuses. Repeated only the command in item 4: exit 0,
   `3 passed in 0.18s` (**parent-path GREEN**).

6. `tests/unit/test_squad_identity_exclusion.py -q`
   returned exit 1: `5 failed, 45 passed in 3.48s`. All five were fixture errors:
   - Competing run-lock cases `[run-run]` and `[run-run_single_phase]` raised
     `LockOrderViolation: controller lock inversion: spec_run -> phase_a` because
     the test held the competing run lock on the caller thread.
   - Retained stage cases `[run]`, `[pending]`, `[answer]` raised
     `AttributeError: 'SquadStateStore' object has no attribute 'routing_state_snapshot'`.
     The correct existing native method is `capture_routing_snapshot`.
   Corrected only the new test file: competing ownership runs on a separate
   event-synchronized thread, matching existing execution-lock fixtures, and
   completion state uses native `capture_routing_snapshot`. No production change
   was needed. Root received these failures and corrections.

7. Focused fixture correction command:
   `tests/unit/test_squad_identity_exclusion.py::test_managed_owner_keeps_existing_busy_lock_outcome tests/unit/test_squad_identity_exclusion.py::test_removed_metadata_preserves_real_pending_completion_and_publication_stages -q`
   returned exit 0: `7 passed in 0.76s`.

8. Added focused controls for an absent identity leaf beneath a real `.echelon`,
   unrelated damaged payloads (absence read is not a full audit), real SQLite
   authorizer denial, and an exact dict requirement. Command:
   `tests/unit/test_element_identity_legacy_guard.py::test_absent_authority_preserves_old_state_without_initialization_or_markdown_io tests/unit/test_element_identity_legacy_guard.py::test_nonselected_damaged_payload_is_not_a_full_authority_audit tests/unit/test_element_identity_legacy_guard.py::test_sql_failure_is_bounded_without_nested_error_or_writes tests/unit/test_element_identity_legacy_guard.py::test_exact_state_dict_required_even_without_authority -q`
   returned exit 0: `5 passed in 0.29s`.

9. Added a native armed failed-automatic-decision manual replay fixture. Command:
   `tests/unit/test_squad_identity_exclusion.py::test_refusal_does_not_consume_native_failed_decision_manual_replay_claim -q`
   returned exit 1: `1 failed in 0.46s`. This was a fixture sealing error:
   `StateAdvanceError: human-input source is invalid for setter sealing`.
   The first fixture used `provider_escalation` with the native direct setter,
   which only accepts its designated source kinds/producers. Corrected the
   fixture to the setter-supported `controller_safeguard` / `agent_blocked`
   request, still prepared through the native registry. No production changed.

10. Repeated only the item 9 command: exit 0, `1 passed in 0.39s`. The fixture
    prepares and fails a real automatic decision, arms native spec-bound manual
    replay, invokes public `run_single_phase`, and verifies that a subsequent
    real claim still succeeds exactly once. The rejected entry consumed neither
    the capability nor persisted state/SQL.

11. The once-only seven-module covering command, against the staged tree below:

    ```text
    /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_element_identity_legacy_guard.py tests/unit/test_squad_identity_exclusion.py tests/unit/test_element_identity_managed.py tests/unit/test_element_identity_managed_context.py tests/unit/test_squad_execution_lock.py tests/unit/test_squad_completion.py tests/integration/test_human_input_routing.py -q
    ```

    Exit 0: `758 passed in 65.56s (0:01:05)`. Output was the normal progress
    display and passing summary, with no skips, warnings or failures. This was
    the only seven-module run. Its simulated-provider integration module ran
    offline as requested.

Read-only diagnostics used `rg`, `sed`, `cat`, `git status`, `git diff`, index
listing and tree/commit identity checks. Two exploratory combined reads ended
with exit 1 solely for no matching files: a nested AGENTS/CLAUDE search found no
additional instruction files, and a zsh glob `src/harness/external*` matched no
file. The relevant publication implementation was then located with `rg --files`.
No build/test failure was hidden in those diagnostics. `git diff --check` and
the staged `git diff --cached --check` both produced no findings.

## Self-review and evidence boundaries

Reviewed the complete production diff, new test code and added storage section.
The scoped index contains only the six files listed above. Root's amended
brief/plan/progress are intentionally dirty and excluded. There are no schema,
wire-format, feature-default, existing-test, CLI, prose or provider edits.

The query authorizer permits reads only of SQLite schema metadata, authority
metadata, managed registrations and operations; trace asserts one BEGIN/COMMIT,
query_only before ownership queries, and no writes. EXPLAIN verifies indexed
spec/run lookups and the managed-operation partial index for orphan checking.
It does not use a capacity benchmark or assert a full authority audit.

Controller tests include both public execution methods in guided/semi/banzai,
retained and deliberately raw-removed managed metadata, changed declared IDs
with retained physical ownership, genuine no-authority and legacy-import
controls, native competing leases, counters/state preservation, and all four
human-input boundaries using native prepared request/decision/resolution types.
The retained completion test constructs a real sealed publication write and a
native terminal completion, installs both pending markers with
`begin_terminal_controller_completion`, then removes only managed metadata by
explicit raw test damage. Refusal preserves the original staged files/modes,
state bytes/markers, SQL, and absent final publication target. This proves
exclusion before recovery, not managed recovery support. Read-only query and
adapter tests are portable value cases; native source/completion fixtures are
explicitly secure-POSIX-gated.

No known implementation concern remains. A successful absence read is not an
enrollment lease; concurrent explicit enrollment and complete loss of both
declarations/ownership witnesses remain stated limitations. All positive
managed execution and publication/producer integration remain inactive.

## Exact tested staged tree and commit receipt

Before the covering run, HEAD was the original base above. Scoped staged tree:
`c86b086bdd51a9192a39417f8177871915678bec`.

| File | Staged blob |
| --- | --- |
| docs/element-identity-storage.md | 24b29d6a55ff8066eef67ad3143525f58b6df459 |
| src/harness/element_identity_legacy_guard.py | f82fc47579cf2126a959a6f3227e97c7851e44d4 |
| src/harness/element_identity_store.py | a46f236ee4c80cb2591f059e00dadedb5462b274 |
| src/harness/squad.py | 4592534e5f66600656e70d845b97c34bf6e1d5c4 |
| tests/unit/test_element_identity_legacy_guard.py | 6004faf6b53e1a0efd10a6e52a4c374e149636ab |
| tests/unit/test_squad_identity_exclusion.py | 5276c68a2e19b99a5615fb05043330e8b55175c1 |

Report content is administrative and is committed separately after the tested
implementation. Implementation commit:
`9076350a9322ae1477bb7a517c9a7c3bccf4a21b`
(`fix(identity): exclude managed ownership from legacy execution`). Its tree
was verified as `c86b086bdd51a9192a39417f8177871915678bec`, exactly the staged
covering-run tree. Before committing, a scoped working-tree/index comparison
returned exit 0 with no differences and the staged whitespace check was clean.
There were no production/test/document amendments after the covering run and
no unchanged postcommit pytest reruns. Root's three administrative files stayed
unstaged throughout the implementation commit.

Final status: DONE. The report-only administrative commit adds only this exact
report path; it does not change the tested implementation tree's six scoped
blobs or reinterpret earlier evidence as positive managed execution support.
