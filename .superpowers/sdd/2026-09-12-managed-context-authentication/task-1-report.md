# Task 1 implementer report: managed context authentication

## Status and code point

- Status: DONE
- Worktree: `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`
- Branch: `fix/delivery-controller-contract`
- Assigned base: `b69793e07998da9e6721172ecbfb82e9d9d09053`
- Tested implementation commit: `a095707a5712ac6a7bf1cbfd2c09cd748210b739`
- Tested implementation tree: `6b017001cca8d57fc69cdc45310c81e544afec91`
- Later code amendments after the covering run: none
- Root-owned `.superpowers/sdd/2026-09-12-managed-context-authentication/progress.md` remained dirty and was neither edited nor committed by this implementer.

## Implementation

Added the opt-in public `IdentityStore.check_managed_context(*, spec_id, run_id, record)` entry. It:

- validates independently supplied spec/run identifiers with the exact lifecycle text validator;
- validates and detaches the supplied ten-string record with `validate_managed_identity_record`;
- rejects a spec/run mismatch before opening the authority transaction;
- uses one existing read transaction and sets `PRAGMA query_only=ON`;
- reads the actual retained genesis with `element_identity_managed_store.read`, treats absence as an error, and requires complete record equality;
- reads the genesis-bound current source with `element_identity_source_store.read` on the same connection;
- requires exact namespace, spec, context, and original source-registration association;
- returns exactly `managed_identity` and `source_context`, using the existing readers' detached records;
- normalizes ordinary input/helper/storage failures to the fixed `IdentityStoreError("invalid managed identity context")` after leaving the exception handler, with no retained cause/context, while preserving `BaseException`.

No schema, transaction owner, state file/lock, managed codec, legacy classifier, filesystem discovery, source publication algorithm, source scope, provider, controller, CLI, startup, repair, or runtime activation was added.

Documentation now separates immutable original genesis from the retained current-head snapshot, and separates both from physical-source/future-publication freshness. It also describes prepared/applied/released observations without treating release or pending state as completion certification.

## TDD and verification evidence

### RED: required first actual regression

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_element_identity_managed_context.py::test_check_managed_context_uses_actual_genesis_and_initial_source -q
```

Relevant output before production implementation:

```text
F                                                                        [100%]
E       AttributeError: 'IdentityStore' object has no attribute 'check_managed_context'
1 failed in 0.24s
```

The secure-POSIX fixture ran, the empty `runs/first/specs/demo` tree was jointly captured through a sealed real `SquadPublicationTransaction`, and actual source plus managed registrations completed before the missing-method call. Thus the RED was the required first `AttributeError`, not fixture/import/capture/registration failure. Root was notified before production code was changed.

### First GREEN

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_element_identity_managed_context.py::test_check_managed_context_uses_actual_genesis_and_initial_source -q
```

Output:

```text
.                                                                        [100%]
1 passed in 0.24s
```

### Focused iteration history

All focused iteration commands used:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_element_identity_managed_context.py -q
```

Actual outcomes, in order:

```text
.................F.............                                          [100%]
1 failed, 30 passed in 3.15s
```

The failure was test setup: attempting a second managed enrollment on the same authority was rejected by existing global managed auditing. The test was narrowed to two real registered source contexts/specs while retaining one managed genesis; no production change was made.

```text
...............................                                          [100%]
31 passed in 3.10s
```

```text
.............................F.....                                      [100%]
1 failed, 34 passed in 3.46s
```

The source-I/O guard incorrectly blocked the permitted authority-marker read as well as source paths. It was narrowed to deny only the selected `specs` source tree; no production change was made.

```text
...................................                                      [100%]
35 passed in 3.44s
```

```text
........................................                                 [100%]
40 passed in 3.63s
```

After the exact association comparison was refactored from individual booleans to an exact tuple comparison:

```text
........................................                                 [100%]
40 passed in 3.76s
```

### Required final covering set (run once)

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_element_identity_managed_context.py tests/unit/test_element_identity_managed.py tests/unit/test_element_identity_state.py tests/unit/test_element_identity_source_store.py tests/unit/test_element_identity_publication.py -q
```

Output:

```text
........................................................................ [ 15%]
........................................................................ [ 30%]
........................................................................ [ 45%]
........................................................................ [ 61%]
........................................................................ [ 76%]
........................................................................ [ 91%]
......................................                                   [100%]
470 passed in 27.91s
```

No full-unit, controller, capacity, live-provider, installation, post-commit, or other covering-suite repeat was run.

## Coverage added

The focused module covers:

- exact real initial source/genesis and detached output shape;
- initial, prepared, applied, and released real source-aware publication observations;
- immutable original genesis after current-head advancement;
- a returned old snapshot followed by later publication, plus physical source drift without registry recapture;
- later mixed identity history without invalidating exact old genesis;
- malformed/missing/null/false/partial/unknown-field records and malformed spec/run values before transaction entry;
- independently selected wrong spec/run and every valid-but-different namespace, epoch, operation, context, path, and original source claim;
- two specs/contexts and explicit rejection of context substitution;
- exact current source/genesis association fields;
- missing genesis, legacy imported-but-unmanaged spec, orphan managed operation, damaged managed row, and damaged source head without side effects;
- actual state initialization/load outside the authority transaction, proving structurally valid caller metadata is insufficient;
- bounded ordinary input/helper/storage failures with no retained untrusted exception context/cause, and `BaseException` propagation;
- one query-only transaction, including a denied actual SQL write probe and unchanged rows;
- prohibited identity child/history reads over established mixed-family history and indexed managed/source lookup plans;
- no current source-tree open/stat access;
- missing database/marker, deleted authority metadata, changed handle namespace, and supported old schema rejection without creation, repair, or upgrade.

## Files changed

- `src/harness/element_identity_store.py`
- `tests/unit/test_element_identity_managed_context.py`
- `docs/element-identity-storage.md`
- `.superpowers/sdd/2026-09-12-managed-context-authentication/task-1-report.md` (this report; report-only follow-up commit)

## Self-review

- Confirmed spec/run selection is independent and compared before database entry.
- Confirmed the complete detached supplied record is compared to the actual retained genesis; no trusted selector is derived from it.
- Confirmed current source selection uses the matched retained context and validates namespace/spec/context/registration association.
- Confirmed original source registration/hash remains in genesis while later accepted operation/sequence/manifest remains only in `source_context`.
- Confirmed both existing readers run on the same query-only connection; there is no second public transaction.
- Confirmed no state reader/writer/initializer/lock or source capture/filesystem read exists in production checking code.
- Confirmed ordinary errors are raised after the handler with a fixed bounded message and `BaseException` bypasses normalization.
- Confirmed no schema, legacy selection, controller/provider/CLI activation, repair, or unrelated refactor entered the diff.
- Confirmed staged implementation surface passed `git diff --cached --check` and contained only the three implementation/test/documentation files.

## Concerns and limitations

No correctness concerns found within the requested scope. The deliberate limitations are contractual: this checker is inactive until a trusted runtime owner independently selects managed versus legacy operation, validates state and current physical source scope, and invokes it. It observes a retained snapshot rather than promising freshness after return, and it does not certify arbitrary child history, release/completion, semantic assessment, graph publication, recovery, or repair. Secure-POSIX real-capture cases skip on platforms without the required descriptor-safe capabilities; they executed in this worktree run.
