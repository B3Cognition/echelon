# Normal Pipeline MemPalace Audit Design

## Goal

Make MemPalace use trustworthy in the normal Echelon spec lifecycle before
adding graph-engineering behavior.

The normal pipeline needs a deterministic way to answer:

- Was this canonical specification mined into MemPalace?
- Are the stored drawers current with the disk artifacts?
- Are stale, run-local, or wrong-wing drawers excluded before prompt use?
- Can the normal pipeline depend on MemPalace context without treating semantic
  retrieval as proof?

This capability belongs to `echelon`, not `codegen`. `codegen` remains an
alternate build pipeline and may keep its existing requirement-memory commands
for compatibility, but normal Phase A and delivery decisions must not require
operators to use the `codegen` CLI.

## Existing Foundation

The implementation reuses existing Echelon and MemPalace foundations:

- `echelon.context_metadata.FeatureMetadata.from_spec_dir()` extracts canonical
  feature, use-case, requirement, lifecycle, artifact path, and artifact hash
  metadata from `specs/<id>/spec.md`.
- `echelon.context_reconciliation.reconcile_drawers()` rejects MemPalace
  drawers whose metadata points outside canonical `specs/<id>/...`, whose
  artifact hash is stale, or whose lifecycle status is excluded.
- `echelon.context_builder.build_run_context()` already writes
  `mempalace-reconciliation.json` and `stale-memory-report.md` for run-local
  context assembly.
- `codegen.memory.mempalace_writer.deterministic_requirement_drawer_id()`
  derives path-independent IDs for canonical requirement drawers.
- `codegen.memory.requirements_miner.RequirementsMiner` can mine markdown files
  and directories into MemPalace.
- `codegen.memory.mempalace_reader.MemPalaceReader` can perform wing- and
  room-filtered semantic search.

The new normal-pipeline feature should move reusable memory operations behind
Echelon-owned service APIs instead of having normal operators invoke `codegen`.

The current normal pipeline already performs canonical best-effort mining
during Phase A publication and through the completion outbox mining effect. The
new service must reuse that exact deterministic planning and verification path.
It must not introduce a second parser, drawer identity algorithm, or independent
Phase A mining side effect.

## Scope

This change adds:

- an Echelon-owned MemPalace audit service;
- normal CLI entry points under the spec lifecycle;
- canonical spec memory mining owned by `echelon`;
- deterministic expected-drawer calculation from canonical spec artifacts;
- direct MemPalace collection inspection for exact drawer presence;
- reconciliation of actual drawers against canonical artifact metadata;
- optional semantic retrieval probes;
- JSON and text reports;
- clear exit codes suitable for local checks and CI;
- normal-pipeline documentation.

This change does not add:

- graph artifact storage;
- GraphRAG local/global/DRIFT search;
- community detection or graph summaries;
- a new vector database;
- mandatory MemPalace gating for every command;
- changes to SOAR/codegen pipeline semantics;
- automatic deletion of stale drawers from the audit command.

## CLI Surface

Add a normal-pipeline command group:

```bash
echelon spec memory mine <spec-id-or-path> [--write-report]
echelon spec memory audit <spec-id-or-path> [--json] [--write] [--probe-retrieval]
echelon spec memory refresh <spec-id-or-path> [--audit] [--write]
```

The command resolves `<spec-id-or-path>` the same way other spec lifecycle
commands resolve a spec:

- `003` or `003-my-feature` resolves under `specs/`;
- `specs/003-my-feature` is accepted directly;
- run-local specs are rejected by default because the audit is about canonical
  durable memory;
- a future `--run-local` option can be added if a separate workflow needs it.

`mine` writes or adopts deterministic canonical drawers for the resolved spec
by calling the same Echelon-owned service used by Phase A finalization. It must
not require `codegen` on PATH. It may reuse lower-level parsing, secret
scrubbing, deterministic drawer IDs, and MemPalace SDK helpers while keeping
the public behavior under `echelon`.

`audit` is read-only by default. Default output is a deterministic text
summary. `--json` prints the same report as JSON. `--write` writes reports
beside the spec:

- `mempalace-audit.json`
- `mempalace-audit.md`

`refresh` runs `mine` followed by `audit`. It is the operator-friendly command
for "make memory current and prove it." Refresh is additive and idempotent: it
writes missing exact drawers and adopts existing exact drawers, but it never
overwrites a drifted deterministic drawer. Drift remains an audit failure and
requires an explicit cleanup or repair command outside this slice.

`--probe-retrieval` runs semantic searches in addition to exact drawer checks.
The default audit must remain fast and deterministic enough for ordinary use.

## Mine Result Model

`mine` produces a report with:

- `schema_version`
- `spec_id`
- `spec_dir`
- `wing`
- `palace_path`
- `status`: `complete`, `partial`, or `unavailable`
- `expected_count`
- `written_count`
- `adopted_count`
- `skipped_count`
- `failed_count`
- `drifted_count`
- `drawers`
- `errors`

A drawer is `written` when the command creates the exact deterministic
canonical drawer. A drawer is `adopted` when the exact drawer already exists
and passes readback verification. A drawer is `drifted` when the deterministic
ID exists but the stored document or stable metadata does not match the
expected postimage. Drift is never overwritten by `mine` or `refresh`. A drawer
is `skipped` only when the expected requirement is intentionally not mineable,
for example because its prefix is unsupported in the first slice. A drawer is
`failed` when it should have been written but was not.

`mine` must write metadata sufficient for `audit` to prove canonical identity:

- `deterministic_identity_schema_version`
- `wing`
- `room`
- `canonical`
- `artifact_path`
- `artifact_hash`
- `requirement_id`
- `requirement_content_sha256`
- `source_file`
- `lifecycle_status`
- `provenance_type`
- `added_by`

`added_by` is descriptive provenance, not proof. Existing drawers stamped by
older code as `codegen` can still pass audit when canonical identity, wing,
artifact path, artifact hash, requirement ID, and content hash all match. New
normal-pipeline writes should stamp `added_by: echelon` and a spec lifecycle
phase value, but audit must not rely on those fields alone.

The command should print counts, not full drawer content.

## Report Model

The report has:

- `schema_version`
- `spec_id`
- `spec_dir`
- `wing`
- `palace_path`
- `status`: `pass`, `warn`, `fail`, or `unavailable`
- `expected_count`
- `present_current_count`
- `missing`
- `stale`
- `wrong_wing`
- `wrong_room`
- `duplicate`
- `non_canonical`
- `lifecycle_excluded`
- `retrieval_probe`
- `recommendations`

`pass` means every expected canonical requirement drawer exists with matching
metadata and artifact hash.

`warn` means exact storage is current but retrieval probes are weak, duplicate
inactive drawers exist, or non-blocking cleanup is recommended.

`fail` means one or more expected current drawers are missing, stale, in the
wrong wing/room, or otherwise unsafe to use.

`unavailable` means MemPalace cannot be imported or opened. This is not the
same as a failed spec. Normal pipeline commands may choose whether unavailable
memory is fail-open or fail-closed.

## Expected Drawers

The audit computes expected drawers from canonical disk artifacts, not from
what MemPalace already contains.

For the first implementation, expected drawers are the output of the same
canonical requirement planner used before mining. The planner input is the
snapshotted canonical `spec.md` bytes, canonical artifact metadata, configured
wing, and the shared requirement parser. Each expected row contains:

- requirement ID;
- canonical artifact path;
- artifact hash;
- inferred room;
- deterministic drawer ID;
- expected content fingerprint.

`FeatureMetadata.from_spec_dir()` remains useful for feature registry and
context summaries, but it is not the authority for expected MemPalace drawers.
Audit and mining must share one parser and one deterministic ID algorithm, or
the audit can pass while normal mining is incomplete.

Room inference should reuse the current requirement prefix mapping where
possible:

- `FR-*` and `REQ-*`: functional requirements;
- `NFR-*`: non-functional requirements;
- `AC-*`: acceptance criteria;
- `US-*`: user stories;
- future prefixes remain explicit unknowns rather than guessed proof.

The design intentionally starts with `spec.md` requirements. Later slices can
add expected drawers for `requirements.lexicon.md`, product input evidence,
plan decisions, risks, contracts, and review amendments after the normal
requirement path is reliable.

## Actual Drawer Inspection

The audit opens the configured MemPalace collection directly and queries by
expected deterministic drawer IDs. It must not rely on semantic search to prove
presence.

For each expected drawer, it verifies:

- ID exists;
- document content is present;
- `wing` matches `.echelon/config.yml` `mempalace.wing`;
- `room` matches expected room;
- `canonical` is true when present;
- `artifact_path` or `source_file` points to canonical `specs/<id>/...`;
- `artifact_hash` matches the current file hash;
- lifecycle/status is active or changed;
- requirement ID metadata matches the expected requirement.

If older drawer metadata lacks a field, the audit reports the specific missing
field. It may still classify the drawer as usable only when the remaining
metadata is enough to prove canonical identity and freshness.

## Reconciliation

After exact inspection, the audit runs the same lifecycle/hash reconciliation
policy used for prompt context. This keeps the normal operator report aligned
with what agents would actually be allowed to consume.

The audit should also scan wing drawers that point to the audited spec path and
report stale extras:

- old hashes;
- deprecated, superseded, removed, or delivered statuses;
- run-local paths;
- duplicate current drawers for the same requirement;
- drawers from a foreign project sharing the wing.

The command reports cleanup recommendations but does not delete anything.
Deletion remains an explicit cleanup command.

## Retrieval Probe

With `--probe-retrieval`, the command runs bounded semantic checks:

- query by each requirement ID;
- query by a short content snippet from each requirement;
- verify that the expected drawer appears in the top N results.

Retrieval probes never upgrade storage proof. They only detect embedding,
distance-threshold, room-filter, or chunking problems that would make current
drawers hard for agents to retrieve.

Probe failures produce `warn` when storage is exact and current. They produce
`fail` only when exact storage also fails.

## Normal Pipeline Integration

Phase A finalization already has a mining effect. The new work should refactor
that effect to call the shared service, then call audit against the same
planned drawer set. Mining and audit results should be recorded as completion
effects, not as external publication transactions.

Initial behavior:

- manual `echelon spec memory audit` is user-facing;
- manual `echelon spec memory mine` and `refresh` are user-facing;
- Phase A context assembly continues to fail open on MemPalace unavailability;
- stale drawers remain excluded from prompt context;
- no existing spec run is blocked by the new audit.

Future gated behavior can be enabled through config:

```yaml
mempalace:
  audit:
    enabled: true
    phase_a_finalization: warn
    delivery_context: warn
```

Allowed modes:

- `off`: do not run automatically;
- `warn`: write reports and continue;
- `block`: fail the transition when current canonical drawers are missing or
  stale.

Automatic integration defaults to `off` for the first release. If a workspace
opts into automatic audit later, the first automatic mode should be `warn`.
`block` should wait until the report format and cleanup workflow have proven
stable.

## Ownership Boundary

Create Echelon-owned modules for normal pipeline use, for example:

- `echelon.mempalace_audit`
- `echelon.mempalace_requirements`

These modules may import lower-level MemPalace SDK helpers and may reuse
existing codegen memory primitives temporarily. The public normal-pipeline API
must live under `echelon`, so future graph engineering can build on Echelon
semantics rather than SOAR/codegen semantics.

The boundary is functional, not merely a module rename:

- `echelon.mempalace_requirements` owns canonical spec selection, canonical
  artifact metadata, expected-drawer planning, mining, and postimage
  verification for normal Echelon.
- Phase A completion mining and `echelon spec memory mine/refresh` must call
  this service.
- The service may delegate to the existing lower-level `RequirementsMiner`
  implementation until that code is moved, but no caller may reimplement the
  parser or drawer ID algorithm.
- `echelon.mempalace_audit` consumes planned expected drawers and actual
  MemPalace collection rows; it does not derive expectations through a separate
  parser.

`codegen requirements mine/search/clean` remains compatibility surface for the
alternate pipeline. It can later be refactored to call the shared lower-level
service.

## Error Handling

All error messages should be bounded and actionable:

- missing wing: tell the user to run `echelon workspace init` or set
  `.echelon/config.yml` `mempalace.wing`;
- MemPalace unavailable: report the import/open failure class without stack
  traces by default;
- no canonical spec: report unsafe spec selector;
- malformed drawer metadata: report field-level findings;
- foreign wing collision: report count and representative metadata, not full
  content;
- secret-scrubbed content mismatch: report hash mismatch without printing
  secret-looking content.

The command should never print full drawer documents by default.

## Testing

Unit tests:

- expected drawer rows are derived from canonical spec metadata;
- expected drawer planning matches the shared canonical miner exactly;
- spec selectors reject run-local paths by default;
- room inference is deterministic;
- missing wing produces a bounded error;
- report status ordering is deterministic;
- stale hash, wrong path, wrong wing, wrong room, duplicate, and lifecycle
  exclusions are classified correctly.

Integration tests with an isolated MemPalace palace:

- mine a canonical spec, audit passes;
- change `spec.md`, audit reports stale drawers;
- remove one drawer, audit reports missing;
- add a drifted deterministic drawer, refresh refuses to overwrite it and audit
  fails;
- add a run-local drawer, audit reports non-canonical and excludes it;
- semantic probe warns when exact storage passes but retrieval misses top N;
- `--write` writes stable JSON and Markdown reports.

CLI tests:

- `echelon spec memory mine <id>` is exposed through the Typer front door;
- `echelon spec memory audit <id>` is exposed through the Typer front door;
- `echelon spec memory refresh <id>` is exposed through the Typer front door;
- `--json` emits valid JSON and no extra prose;
- exit code is `0` for pass/warn, `1` for fail, and `2` for unavailable or
  invalid invocation.

## Migration Path

1. Add the shared expectation/report model and read-only audit service.
2. Extract an Echelon-owned canonical requirement memory service and route the
   existing Phase A completion mining through it without changing observed
   drawer IDs.
3. Add Echelon-owned `mine`, `audit`, and `refresh` CLI commands.
4. Document the manual workflow:

   ```bash
   echelon spec memory refresh 003-my-feature --write
   ```

5. Refactor Phase A finalization to record mine and audit reports, still
   fail-open.
6. Add config-controlled warn/block modes after the report proves stable.
7. Only then begin Spec Artifact Graph work, using audited MemPalace drawers as
   the semantic retrieval layer.

## Non-Goals For This Slice

- Do not design the graph schema yet.
- Do not introduce a graph database.
- Do not make MemPalace mandatory for all Echelon users.
- Do not remove `codegen requirements` commands.
- Do not use semantic search as storage proof.
- Do not auto-clean drawers during audit.
- Do not overwrite drifted deterministic drawers during refresh.
