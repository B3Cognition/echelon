# Phase A Add-Input Design

## Context

Long-running Phase A spec runs can legitimately park in `phase1-investigate`
when declared references are insufficient and external evidence is required.
The current recovery path records only free-text clarification through
`echelon spec resume`, while `echelon spec run --input` declarations remain
immutable for an active run. Users need a controlled way to add authoritative
reference material to the same parked run without resetting the run or manually
copying files into run-local evidence directories.

## Goals

- Add `echelon spec add-input --input <role:path>` for a parked active run.
- Permit the command only for evidence/access checkpoints in
  `phase1-investigate`.
- Preserve the original input snapshot unchanged.
- Append immutable evidence revisions with provenance, content metadata, and
  best-effort linkage to outstanding evidence requests.
- Update controller-owned Product Input Contract pointers so agents can consume
  the added references through the declared manifest and catalog.
- Keep agents from writing `state.json` or product-input declarations directly.
- Ensure `echelon spec continue` re-dispatches INVESTIGATOR with explicit added
  evidence context while preserving existing investigation artifacts.

## Non-Goals

- Do not weaken the existing active-run immutability check in
  `echelon spec run --input`.
- Do not make `echelon spec resume` accept files or evidence bundles.
- Do not start a new run, spec amendment worktree, or detached amendment flow.
- Do not let undeclared files in `sources/` become authoritative evidence.

## Command UX

The new command is:

```bash
echelon spec add-input \
  --input reference:sources/DE-OPTA-SCHEMA-MAPPING \
  --input reference:sources/DE-RESOLVER-BENCHMARK
```

It accepts the same repeatable declaration grammar as `spec run --input`:
`requirement:<path-or-figma-url>` and `reference:<path-or-figma-url>`. The
primary intended use for this recovery path is `reference:` evidence, but the
parser should keep the shared grammar unless checkpoint policy later restricts
roles.

Successful output should show original inputs separately from added evidence,
including the new attachment revision id, accepted resources, duplicate
resources, and the next command:

```bash
echelon spec continue
```

## Eligibility

`add-input` must acquire the existing Phase A lifecycle lock and the active run
execution lock before reading or changing run state. It must then require:

- an active run directory from the current run pointer;
- a valid `state.json`;
- `status == "blocked"`;
- `phase == "phase1-investigate"`;
- `blocked_reason == "investigation_access_required"`;
- `evidence_resolution_status == "access_required"`;
- a Product Input Contract in state with a run-local `inputs_dir`.

Any other state exits without mutation and explains that `add-input` is only
available for parked investigation access checkpoints.

## Evidence Storage Model

The original snapshot remains at the existing run-local inputs directory. The
new command appends revision directories under that root:

```text
<run_dir>/inputs/
  manifest.json
  catalog.json
  traceability.json
  requirement-context.md
  reference-context.md
  snapshots/
  attachments/
    001/
      manifest.json
      catalog.json
      input-context.md
      requirement-context.md
      reference-context.md
      traceability.json
      snapshots/
    002/
      ...
  attachment-ledger.json
```

The revision directory is immutable. The aggregate root manifest, catalog, and
context files are derived controller-owned indexes over the original snapshot
plus all accepted attachment revisions. Rebuilding those aggregate files does
not mutate the original snapshot contents or prior attachment revision contents.

## Provenance

Each accepted resource in `attachment-ledger.json` records:

- attachment id, declaration id, role, and source location;
- command name and process metadata sufficient for audit;
- timestamp in UTC;
- declared relative path and source locator;
- sha256, size, and media type;
- run-relative snapshot path;
- status and exclusion or duplicate reason when applicable;
- linked evidence request ids when a deterministic match can be made.

Linkage is best effort. The controller should derive candidate `ER-*` ids from
the current `evidence_requests` object and from text matches against request ids
or request text in declaration locations and filenames. If no confident match is
available, the revision is still valid and is presented as resolving the parked
access checkpoint generally.

## Duplicate Handling

The command rejects duplicates idempotently by:

- declared source identity: same role plus normalized source location already
  present in the original declarations or any attachment declaration;
- accepted content hash: any accepted resource sha256 already present in the
  aggregate manifest or attachment ledger.

If every supplied declaration is duplicate, the command performs no state
mutation and prints an idempotent result. If a declaration contains a mix of new
and duplicate resources, new accepted resources are appended and duplicates are
reported as excluded in the attachment revision metadata.

## Contract Rendering

`harness.squad_executors._render_product_input_context` should keep the current
Product Input Contract variables and add an "Added Reference Material" section
when state contains attachment metadata. That section must name:

- attachment ids and declaration locations;
- run-relative snapshot paths or manifest resources;
- linked or outstanding evidence request ids;
- the fact that prior investigation artifacts must be preserved and extended.

The existing phase spec for `phase1-investigate` should explicitly instruct
INVESTIGATOR to read prior `evidence-inventory.json`, `evidence-resolution.md`,
`evidence-grades.md`, and per-request investigation reports before expanding
only the newly added material needed to resolve outstanding requests.

## State Changes

The command updates `state.json` only through controller-owned code while both
locks are held. It appends or refreshes:

- `product_inputs` aggregate pointers and manifest hash;
- `product_input_attachments` summary ledger;
- a small recovery marker indicating that new evidence was attached for the
  current `phase1-investigate` checkpoint.

After a successful non-duplicate attachment, the command should convert only
this checkpoint into a retryable investigation state:

- `status: "running"`;
- `phase: "phase1-investigate"`;
- `blocked_reason: null`;
- `escalation_question: null`;
- `escalation_resolved: true`;
- `escalation_resolver: "echelon spec add-input"`;
- a recovery marker that records the prior blocked reason and attachment ids.

This mirrors a controller-owned unblock, but does not treat the external
evidence as a free-text human answer. It must not erase existing evidence
request state or investigation artifacts. With the run now retryable,
`echelon spec continue` resumes the active run and dispatches INVESTIGATOR from
`phase1-investigate`.

## Validation and Routing

After `echelon spec continue`, INVESTIGATOR reads the updated Product Input
Contract, consumes the added references, and emits the usual
`echelon_result`. The existing deterministic validation and routing then
decides whether evidence is validated, conflicting, inconclusive, or still
access-required. If evidence remains insufficient, the run parks again with a
fresh checkpoint. If evidence resolves or conflicts, the normal Phase A flow
continues.

## Testing

Add focused tests for:

- successful attachment to a valid parked investigation;
- rejection for running, done, or non-evidence-blocked runs;
- append-only provenance and snapshot integrity;
- duplicate/idempotent source and content handling;
- Product Input Contract rendering that exposes added references and `ER-*`
  context to INVESTIGATOR;
- no regression to initial `echelon spec run --input` immutability and snapshot
  behavior.

Tests should be written before production changes. Existing
`tests/unit/test_product_inputs.py`, `tests/unit/test_cli_continue.py`, and
prompt-rendering tests around `_render_product_input_context` are the natural
homes.
