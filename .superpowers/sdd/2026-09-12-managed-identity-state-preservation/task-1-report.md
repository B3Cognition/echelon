# Task 1 implementation report

Status: DONE. Implemented only in the existing delivery-controller-contract
worktree on `fix/delivery-controller-contract`, from base
`b70afc3c8d57870253af4c9d63f49513f1bb651c`.

## Implementation

- Added the pure, closed, exact ten-string managed genesis record validator. It
  reuses `ManagedIdentityRequest`, its encode/decode validation, and lifecycle
  text validation. It detaches accepted records, normalizes ordinary failures to
  a bounded ValueError with no retained untrusted exception context, and allows
  BaseException to propagate. It performs no I/O or registry authentication.
- Reserved `managed_identity` in a separate `MANAGED_IDENTITY_KEYS` frozenset
  included in store ownership. It has no Phase A, trusted routing update/removal,
  or provider control-intent authority. Existing preparation and attestation
  checks enforce that boundary, including identical echoes and tampered seals.
- Added the trailing optional initializer argument. Explicit metadata provides
  `spec_id` and must match the requested exact-string run ID. Same-run resets
  preserve existing metadata/spec ID while holding the same exclusive state
  lock used to persist initialization. Identical supplied metadata is accepted;
  replacement, run changes, and invalid retained metadata are rejected.
- Added focused state association/write helpers and validation on load and at
  the sole `_save_unlocked` writer. Metadata rejection occurs before backup or
  replacement-temp writes. Only a narrow internal initializer flag can introduce
  metadata into legacy/empty state. Exact saves retain the bounded managed-state
  contract error and all existing other exact-write/durability behavior.
- Added real capture/source/genesis initialization, state persistence, ownership,
  hostile input, fault injection, CAS contention, atomic preservation scheduling,
  and real controller/simulated provider regression coverage. No controller
  production changes, authority/store/schema edits, or live enrollment occurred.

## TDD and focused iteration evidence

All pytest commands used the existing executable
`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest`, from this worktree.
The following arguments identify the exact commands after that executable.

1. Required first RED, before any production changes:
   `-q tests/unit/test_element_identity_state.py::test_initialize_accepts_real_managed_genesis`
   completed real POSIX publication capture, source registration, and managed
   genesis registration, then failed exactly at the missing initializer keyword:
   `TypeError: SquadStateStore.initialize() got an unexpected keyword argument 'managed_identity'`.
   Result: `1 failed in 0.36s`. The module-local `secure_posix` fixture had been
   explicitly defined first. Root was notified before production implementation.
2. New validator/state tests before implementation:
   `-q tests/unit/test_element_identity_state.py -x` produced the expected missing
   new-module error (`ModuleNotFoundError: No module named 'harness.element_identity_state'`),
   `1 failed in 0.19s`. This was additional evidence, not the required first RED.
3. First GREEN:
   `-q tests/unit/test_element_identity_state.py` -> `66 passed in 0.45s`, including
   the real genesis initialization regression.
4. Focused persistence/routing/recovery/fault/race iteration:
   `-q tests/unit/test_element_identity_state.py -k 'metadata_survives or routing_cannot or recovery_owner or save_fault or readback or two_writers or initializer_selects'`
   -> `1 failed, 13 passed, 74 deselected in 0.34s`. The test initially expected
   OSError for a pre-replace exact-save failure; the existing exact-save contract
   correctly returns StateAdvanceError with validator `save`. Corrected that test
   expectation; no durability production change was needed.
5. `-q tests/unit/test_element_identity_state.py::test_real_save_fault_retains_exact_genesis tests/kernel/test_prepared_phase_result.py -k 'managed_identity or real_save_fault'`
   -> `4 failed, 11 passed, 413 deselected in 0.36s`. Initial tampering tests tried
   to assign read-only public properties. Corrected the tests to tamper the real
   frozen private envelope fields and canonical result payload, so existing
   attestation verification is actually exercised.
6. `-q tests/kernel/test_prepared_phase_result.py::test_managed_identity_tampered_frozen_envelopes_fail_attestation tests/integration/test_squad_controller.py::test_managed_identity_prepared_initialization_survives_controller_fresh_start tests/integration/test_squad_controller.py::test_managed_identity_manual_replay_preserves_metadata_before_simulated_dispatch tests/integration/test_squad_controller.py::test_managed_identity_manual_updates_reject_injection_before_provider_dispatch`
   -> `14 passed in 4.86s`.
7. Strengthened the fresh-start test to execute one real simulated-provider
   dispatch in each autonomy mode, then stop through the existing deferred
   interruption path:
   `-q tests/integration/test_squad_controller.py::test_managed_identity_prepared_initialization_survives_controller_fresh_start`
   -> `3 passed in 2.10s`.
8. Self-review RED:
   `-q tests/unit/test_element_identity_state.py::test_record_normalizes_ordinary_failures_without_retaining_exception_context`
   -> `1 failed in 0.20s`, because `raise ... from None` suppressed display but
   still retained the original RuntimeError in `__context__`. Raised the bounded
   error after leaving the handler in the pure validator and state helper.
   Focused GREEN:
   `-q tests/unit/test_element_identity_state.py::test_record_normalizes_ordinary_failures_without_retaining_exception_context tests/unit/test_element_identity_state.py::test_record_preserves_baseexception tests/unit/test_element_identity_state.py::test_invalid_initialization_record_never_creates_state_or_backup`
   -> `7 passed in 0.25s`.

## Final covering verification and exact code point

The single full scoped covering run was executed against staged
implementation/test/documentation tree
`63ce01175c7f285de1ad6e216e32ddba20c4dfa7`, based on
`b70afc3c8d57870253af4c9d63f49513f1bb651c`. The subsequently added report is the
only task file added after this run; no production or test corrections followed.
Root's unstaged progress ledger was excluded from the staged tree and commit.

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_state.py tests/kernel/test_squad_state.py tests/kernel/test_prepared_phase_result.py tests/unit/test_state_transaction_namespace.py tests/unit/test_element_identity_managed.py tests/integration/test_squad_controller.py::test_managed_identity_prepared_initialization_survives_controller_fresh_start tests/integration/test_squad_controller.py::test_managed_identity_manual_replay_preserves_metadata_before_simulated_dispatch tests/integration/test_squad_controller.py::test_managed_identity_manual_updates_reject_injection_before_provider_dispatch
912 passed in 12.69s
```

Exit status 0; output pristine, with no skipped tests or warnings. The three
named controller tests produce ten cases: three autonomy-mode fresh starts, one
manual replay that preserves metadata through a simulated provider escalation,
and six mode/legacy-or-managed injection/replacement rejection cases. No whole
controller module, full-unit, capacity, live-provider, install, or postcommit
test repeat was run. `git diff --check` and `git diff --cached --check` passed.

## Files changed

- `src/harness/element_identity_state.py` (new)
- `src/harness/state_transaction_namespace.py`
- `src/harness/squad_state.py`
- `tests/unit/test_element_identity_state.py` (new)
- `tests/kernel/test_prepared_phase_result.py`
- `tests/integration/test_squad_controller.py`
- `docs/element-identity-storage.md`
- This report. Root's `progress.md` remains intentionally unstaged and uncommitted.

## Self-review, concerns, and exact limits

Reviewed validation-before-backup/temp ordering, same-lock initializer selection,
preservation on old controller call shapes, namespace closure and frozen-envelope
attestation, state revision CAS, exact-write failure/readback outcomes, and
unchanged human-input authorization. Existing state/controller modules are large;
the production edit is confined to focused metadata helpers and existing
load/initialize/write entry points. No unrelated refactoring was performed.

No unresolved correctness concern remains within the task scope. Record
validation deliberately certifies structure and run/spec association only. It
cannot authenticate receipt provenance or current physical source scope; mutable
`spec_dir` can differ from original `spec_path`. Same-run preservation is not a
subsequent-run transition protocol. The tests explicitly forbid registry/source
lookups during the new validation paths and use actual state owner locks/writes.

External state deletion, external removal of the field, wholly unrecognizable
corruption, missing registry, and old registry schemas still require the future
trusted durable-registry gate. Unknown malformed legacy JSON retains prior
initializer behavior, whereas explicit managed initialization fails closed.
Nothing here activates source isolation, producer enrollment, graph/memory
publication, semantic judgment, or trusted startup/dispatch/completion registry
integration. Those remain separately required before activation.

Skills followed: `superpowers:test-driven-development` (including
`writing-good-tests.md`) and `superpowers:verification-before-completion`, plus
the full supplied implementer prompt and repository AGENTS.md. No subagents or
reviewers were spawned.

## Review fix round 1: discard managed-owner exception context

Fix base: `91a4c48afd0b4c0f6cda18dd95f78b5e2c178d2d`. The reviewer identified that
the initializer and sole-writer malformed-prior-JSON wrappers raised inside their
`except ValueError` handlers. Although `from None` suppressed traceback display,
`__context__` retained the original `JSONDecodeError`, including its untrusted
`.doc`. The original 912-test covering evidence above belongs to the pre-fix
code point and is not claimed as a covering run of this amendment.

Verified the finding with real on-disk malformed JSON through both `initialize`
and the locked `_save_unlocked` initialization path. The tests retain an existing
backup and install backup/temp write tripwires, assert the same bounded
`StateAdvanceError` path, and now require both `__context__` and `__cause__` to be
absent. Each case also proves the legacy initializer still accepts unknown
malformed prior JSON under its pre-existing policy.

The same review of the new managed wrappers found the initializer's supplied
record-validation wrapper retained its ValueError context. Added context/cause
assertions to all five existing malformed initialization cases and corrected that
wrapper too. Added three focused probes confirming the two parse paths and the
record-validation path still propagate the identical BaseException without
changing state or backup bytes. Unrelated legacy error wrappers were not changed.

Actual RED before production correction:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_state.py::test_managed_initialize_rejects_malformed_json_without_changing_legacy_policy tests/unit/test_element_identity_state.py::test_invalid_initialization_record_never_creates_state_or_backup tests/unit/test_element_identity_state.py::test_managed_owner_normalization_preserves_baseexception
7 failed, 3 passed in 0.31s
```

Both real malformed-JSON paths failed the new assertion with
`JSONDecodeError('Expecting value: line 1 column 29 (char 28)')` retained as
`StateAdvanceError.__context__`. The five supplied-record cases failed with
`ValueError('invalid managed identity record')` retained as context. The three
BaseException cases passed. Root was notified before the production correction.

Production correction: record parse failure with a boolean and raise each bounded
managed error after leaving its handler. For supplied record validation, use
`None` as the failed-validation sentinel and likewise raise after the handler.
The exceptions caught, legacy parsing policy, state lock, initialization
authority, bounded error text/path, and validation-before-write ordering remain
unchanged. The pure validator and unrelated state errors needed no correction.

Exact amended production/test code point: staged tree
`f81c3347c1217c3ba521cd4c2186134c7b30ec97`, based on the fix base above. This report
appendix was added after the covering run; no subsequent production/test edits
were made. The single required amended covering run also supplies GREEN:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_state.py tests/kernel/test_squad_state.py
354 passed in 2.49s
```

Exit status 0, no skips or warnings. This was the only post-fix covering run; no
912-test repeat, controller suite, full-unit, capacity, provider, install, or
postcommit tests were run. Diff checks passed.

Files amended: `src/harness/squad_state.py`,
`tests/unit/test_element_identity_state.py`, and this report. Root's dirty
`progress.md`, untracked `docs/superpowers/plans/2026-09-12-managed-context-authentication.md`,
and ignored next-task workspace remain outside the commit.

Self-review confirmed all three new managed-error wrappers now discard caught
exception context, reject before backup/temp writes, and preserve BaseException
and the explicit unknown-legacy JSON policy. No unresolved concern remains for
this finding; previously documented activation and authority limitations remain.
Used `superpowers:receiving-code-review`, the previously loaded TDD guidance, and
verification-before-completion. No subagents or reviewers were spawned.
