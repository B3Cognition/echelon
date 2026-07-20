# RE Validation Resume Granularity

## Problem

`echelon re continue` restores the active run and phase, but a failed
`re-extract-5-validate` dispatch restarts validation for every refreshed domain.
The validator currently returns one workspace-wide result, so a provider exit or
context-limit failure discards useful completed-domain work. A later repair also
forces already-passing domains through validation again. In a multi-source
workspace this makes phase-level continuation behave like a broad restart and
causes excessive token consumption.

## Scope

This change makes semantic validation and its repair loop resumable at domain
granularity. It does not change analysis, initial specification, coverage
verification, checklist generation, constitution generation, publication, or
the public aggregate semantic-quality report format.

## Required Behavior

1. The controller validates one unresolved source-domain per dispatch.
2. A valid domain audit is persisted immediately after its dispatch succeeds.
3. Continuing a run dispatches only domains without a current valid audit.
4. Repairing a domain invalidates only that domain's audit.
5. An audit is current only while its source and staged spec fingerprints match
   the values recorded with the audit.
6. A provider failure leaves the current domain unresolved; completed domains
   remain reusable.
7. After every refreshed, non-empty domain has a current audit, the controller
   assembles the existing aggregate `semantic-quality-review.json` artifact and
   follows the existing pass-or-repair routing.
8. Existing run state without granular audit records remains compatible: its
   domains are treated as unresolved and validated once under the new protocol.

## State Model

The RE state gains a versioned map keyed by the canonical
`<source-id>/<domain-id>` identity. Each record contains:

- source and domain identifiers;
- `PASS` or `REPAIR` plus validated findings/evidence;
- source fingerprint;
- staged spec fingerprint;
- semantic-review protocol version.

The controller derives pending work rather than maintaining a second mutable
queue. For every domain in the current execution plan, it compares the saved
record with current fingerprints. Missing or stale records are pending. This
keeps crash recovery deterministic and avoids queue/state disagreement.

The currently dispatched domain is written into `last_dispatch` context before
calling the provider. If the provider exits, `post_dispatch_complete: false`
causes continuation to retry that same domain. No prior record is removed until
a replacement audit has passed schema and evidence validation.

## Dispatch and Aggregation

The validation prompt receives exactly one source-domain and explicitly forbids
auditing sibling domains. The controller validates the returned identity against
the requested identity before persisting it.

Once there are no pending domains, records are ordered by execution-plan source
and domain order and converted into the existing aggregate report. Existing
quality and repair scheduling code consumes that aggregate unchanged.

When semantic repair is scheduled, the controller deletes or marks stale only
the repaired domains' records. Passing sibling records survive the
specifier/validator cycle. Fingerprint comparison provides an additional guard
if a spec is changed outside normal repair routing.

## Failure Handling

- Provider exit or timeout: block with the existing dispatch failure reason and
  retain completed-domain records.
- Invalid result or mismatched identity: count the attempt against the current
  validation budget without damaging prior records.
- Changed source/spec fingerprint: treat only that record as stale.
- Corrupt granular record: ignore that record and revalidate its domain.
- Exhausted retry/repair budget: preserve current blocked behavior.

## Compatibility

`semantic-quality-review.json` remains an aggregate report with the existing
schema. Existing commands and publication consumers therefore require no
changes. Old active runs acquire the new state map lazily and do not rewind to
analysis or specification solely because granular validation state is absent.

## Tests

Regression coverage must demonstrate:

1. A validator failure on the second domain followed by `continue` retries only
   the second domain.
2. A completed first-domain audit survives controller reconstruction.
3. Repair invalidates the repaired domain but reuses passing siblings.
4. A spec fingerprint change invalidates only its domain.
5. A source fingerprint change invalidates affected source domains only.
6. Legacy state without granular records validates all domains once.
7. The final aggregate report and downstream routing remain compatible.

## Non-goals

- Resuming inside a single domain audit.
- Reusing audits across unrelated RE runs.
- Changing validation taxonomy, thresholds, or repair budgets.
- Redesigning continuation for other RE phases.
