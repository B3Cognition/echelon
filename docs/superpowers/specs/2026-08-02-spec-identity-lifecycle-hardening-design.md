# Spec Identity And Lifecycle Hardening Design

## Context

Recovering and landing spec `906-cli-output-styling` exposed three related
failures:

1. Landing received the canonical slug but the verified branch used the numeric
   selector. Branch lookup missed the branch and treated absence as proof that
   the spec was already landed, changing lifecycle status without merging code.
2. `echelon spec verify` dispatched the generated command wrapper directly. It
   bypassed `FulfillmentRunner`, so deterministic phase embedding, target
   resolution, provenance stamping, cache hashing, and verified-ledger writing
   did not complete as one command.
3. Evidence publication searched only slugged verify-run directories. Older
   numeric directories such as `verify-spec/906` required an undocumented
   path-shaped `--from-run` workaround.

These are identity and ownership defects, not missing graph functionality.

## Goals

- Accept numeric and canonical-slug selectors consistently at command
  boundaries.
- Never infer successful landing from branch absence alone.
- Make `echelon spec verify <selector>` the complete normal-pipeline command.
- Automatically audit the spec's declared target checkout.
- Publish evidence from both current slugged runs and older numeric runs.
- Reuse existing lifecycle owners instead of adding parallel orchestration.

## Non-Goals

- Migrating or renaming existing run directories.
- Automatically checking out a historical commit or harness branch for verify.
- Supporting multi-target normal-spec verification in this change.
- Adding a branch/run registry or graph database.
- Changing fulfillment judgment semantics.

## Canonical Identity

The canonical spec identity is the canonical directory name under `specs/`, for
example `906-cli-output-styling`. The leading numeric component, `906`, is an
accepted selector alias.

A shared identity helper returns ordered aliases:

```text
906-cli-output-styling -> [906-cli-output-styling, 906]
906                    -> [906]
feature-without-number -> [feature-without-number]
```

Order matters: exact canonical identity wins, then the numeric compatibility
alias. New verify runs use the canonical directory name. Existing numeric runs
remain readable.

## Landing

Landing branch discovery searches feature and legacy harness branches using the
ordered identity aliases. An exact canonical branch remains preferred over a
numeric alias.

When no branch is found, landing uses positive evidence:

| Spec state | Full report metadata | Default contains `verified_commit` | Result |
| --- | --- | --- | --- |
| any | commit present | no | block; do not mutate status or clean refs |
| ready to land | commit present | yes | finish idempotently and mark landed |
| landed | commit present | yes | idempotent success |
| landed | no commit/report | unknown | legacy idempotent success |
| not landed | no commit/report | unknown | block |

An unreadable branch lookup remains a hard failure. Branch absence and lookup
failure are never collapsed into the same state.

The blocking message identifies the missing branch and, when available, the
verified commit that is absent from the default branch.

## Direct Verify

`echelon spec verify <selector>` resolves:

1. the canonical spec directory in the orchestration workspace;
2. the canonical slug from that directory;
3. the single declared target repository, or the orchestration repository when
   the spec has no target;
4. provider configuration, skill files, workflow phases, `specs/`, and `runs/`
   from the orchestration workspace.

It then calls `FulfillmentRunner.refresh` against the target checkout. The
runner remains responsible for:

- embedding deterministic verify phase contracts;
- invoking the provider;
- validating report/audit row sets;
- stamping `verified_commit`, input hashes, cache key, scope, timestamp, and run
  ID;
- writing the verified fulfillment ledger;
- returning cached/refreshed/failed status.

`FulfillmentRunner` gains explicit `reconcile` and `dry_run` inputs. Either flag
forces execution instead of a cache return because reconciliation may have
requested side effects. The flags are forwarded to the embedded workflow.

Skill and phase discovery may use the orchestration workspace even when the
implementation target does not install Echelon command files. Implementation
hashing and source evidence remain rooted in the target checkout.

The CLI prints the structured outcome in concise text and exits nonzero unless
the runner result is successful.

## Evidence Publication

Evidence run discovery uses the same ordered identity aliases.

Without `--from-run`, candidates include:

```text
runs/verify-spec-<canonical-slug>-*
runs/verify-spec-<numeric-id>-*
runs/*/verify-spec/<canonical-slug>
runs/*/verify-spec/<numeric-id>
```

With `--from-run <run-id>`, candidates include both alias directories below the
selected run plus the run directory itself for standalone verify runs.

Candidates must contain `state.json` and at least one publishable verify
artifact. Duplicate paths are removed. The latest valid candidate by artifact
modification time retains the current selection behavior.

## Error Handling

- Ambiguous canonical spec selection remains an error.
- Multi-target direct verify reports that exactly one target is required.
- Missing target repositories fail before provider invocation.
- Missing skills/phases report the searched orchestration and target roots.
- Failed verification does not stamp provenance or update the ledger.
- No-branch landing failures do not write `landed` status.
- Evidence publication reports all attempted identity aliases when no source is
  found.

## Tests

### Identity

- canonical slug produces ordered slug/numeric aliases;
- numeric and nonnumeric identities remain stable.

### Landing

- slug selector finds a numeric conventional branch;
- slug selector finds a numeric legacy harness branch;
- no branch plus unmerged verified commit blocks and preserves status;
- no branch plus merged verified commit finishes idempotently;
- legacy already-landed spec without report remains idempotent;
- non-landed spec without report blocks.

### Verify

- CLI resolves canonical spec and declared target;
- orchestration provider/config and phase roots are used with target source;
- successful refresh stamps current target commit and writes ledger;
- failed refresh returns nonzero and does not stamp;
- `--reconcile` and `--dry-run` bypass cache and reach the workflow.

### Evidence

- slug selects a newer slugged run;
- slug falls back to an older numeric nested run;
- `--from-run <run-id>` finds a numeric nested run;
- incomplete candidates are ignored;
- no candidate error includes attempted aliases.

## Documentation

Update the CLI README and changelog to state:

- verify automatically uses the declared target checkout;
- branch absence is not sufficient landing evidence;
- evidence publication reads legacy numeric verify runs.

