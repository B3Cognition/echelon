# Task 7 Report: Destructive Retarget Coordinator and CLI

## Status

Implemented the destructive `echelon spec retarget` coordinator and both CLI
front doors.

## Files

- `src/echelon/spec_retarget.py` — deterministic preview, retry detection,
  lock-ordered coordinator, durable failure projection, exact artifact
  invalidation, Git-only bounded context, and stable failure codes.
- `src/echelon/spec_retarget_cli.py` — strict legacy parser, target resolution,
  preview rendering, checkpoint recovery callback, and flush boundary.
- `src/echelon/cli.py` — legacy help/dispatch and ordinary `_cmd_run` handoff.
- `src/echelon/cli_app.py` — public Typer `spec retarget` command.
- `tests/unit/test_cli_spec_retarget.py` — coordinator, parser, purity,
  transaction, retry, confinement, context, and failure tests.
- `tests/unit/test_cli_typer_app.py` — Typer parsing/forwarding and exact Phase A
  dispatch tests.

## Architecture

Preview collects the existing Task 1 eligibility evidence, public Task 2
artifact plan, baseline intent, RE policy, and current Git commit. It derives a
stable operation/checkpoint preview identity from immutable evidence and does
not allocate IDs, acquire locks, create directories, mutate refs/objects, or
write state.

Confirmation acquires `SpecMutationLock`, `PhaseAExecutionLock`, and the
baseline `SpecRunExecutionLock` in that order, then repeats and compares the
full preflight. It appends one prepared revision, creates and verifies the
retarget checkpoint, prints and flushes the exact rewind command, bootstraps the
same-identity replacement, purges and excludes exact-spec memory, invalidates
only public-plan artifacts in canonical and run-shadow roots, invalidates the
selected graphs, writes bounded checkpoint context from Git blobs, and durably
advances the run and history to rebuilding. The legacy front door then invokes
ordinary `_cmd_run` with the exact preserved prompt, mode, targets, explicit RE
sources, and ignore-RE flag.

Retry detection runs before ambiguous ordinary preflight. A matching durable
nonterminal run/history pair reuses its revision, run, and checkpoint. Target,
identity, runtime/history, or checkpoint drift rejects with the recorded
rewind; a durable failed state always requires rewind.

Artifact deletion uses validated confined top-level public plans, bounded
controller-owned traversal, rejects symlinks/nonregular entries including
preserved controls, and atomically writes identical replacement `targets.yml`
bytes to both owned roots. Coverage context accepts only the four approved
names, a canonical full commit and spec ID, regular Git blob modes, per-file
and aggregate caps, confined run-local outputs, and a path/size/SHA-256
manifest prevalidated before any write.

## TDD Evidence

Initial preview/parser RED, before production edits:

```text
.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py -k 'preview or parser'
10 failed in 0.30s
```

Failures were the absent `prepare_spec_retarget` API and absent
`spec_retarget_cli` module. First GREEN:

```text
.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py -k 'preview or parser' tests/unit/test_cli_typer_app.py -k 'retarget'
11 passed, 51 deselected in 0.65s
```

Ordered transaction/context RED and GREEN:

```text
.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py -k 'apply_retarget or callback or artifact_invalidation or checkpoint_context or bounded_failure'
5 failed, 1 passed, 10 deselected in 0.38s
6 passed, 10 deselected in 0.62s
```

Retry-first RED and GREEN:

```text
.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py -k 'duplicate_targets or deterministic or retry or destructive_failure or rejects_symlink'
3 failed, 4 passed, 16 deselected in 0.83s
7 passed, 16 deselected in 0.78s
```

Typer invalid-shape matrix:

```text
.venv/bin/pytest -q tests/unit/test_cli_typer_app.py -k 'retarget_typer_invalid'
7 passed, 76 deselected in 0.49s
```

Durability compatibility RED and GREEN:

```text
.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py -k 'memory_exclusion_persists or failed_prepared_revision'
2 failed, 23 deselected
2 passed, 23 deselected in 0.22s
```

This proved the ordinary squad reader required `retarget.memory_excluded=true`
and that failure advancement must use the actual latest history status rather
than assume `invalidating`.

Every destructive-effect failure and post-checkpoint bootstrap boundary:

```text
.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py -k 'destructive_failure or bootstrap_failure'
1 failed, 6 passed, 24 deselected in 0.23s
.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py -k 'destructive_failure or bootstrap_failure or memory_exclusion_persists or failed_prepared_revision'
9 passed, 22 deselected in 0.23s
```

The matrix covers bootstrap, purge, exclusion persistence, artifact
invalidation, graph invalidation, context assembly, and rebuilding-state
persistence with stable codes and visible recovery.

Additional focused cycles:

- Preserved-control symlink RED `1 failed, 1 passed`; GREEN `2 passed`.
- Missing retry history RED `1 failed, 3 passed`; GREEN `4 passed`.
- Git-context symlink RED `1 failed`; GREEN context group `3 passed`.
- Preview old-target/readiness RED `1 failed`; GREEN `1 passed`.
- Root usage RED `1 failed`; corrected in the final CLI suite.

## Final Verification

Required Task 7 suite, fresh after all fixes:

```text
.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py tests/unit/test_cli_typer_app.py tests/unit/test_spec_retarget.py
113 passed in 3.75s
```

Bounded close neighbors:

```text
test_phase_a_start.py + test_spec_lifecycle.py
156 passed in 38.14s

test_spec_retarget_history.py + test_mempalace_retarget.py + test_spec_retarget_graph.py
179 passed in 2.05s

test_phase_checkpoints.py
70 passed in 27.89s

test_squad_phase_checkpoints.py
16 passed in 0.76s
```

Final static gates:

```text
.venv/bin/python -m py_compile src/echelon/spec_retarget.py src/echelon/spec_retarget_cli.py src/echelon/cli.py src/echelon/cli_app.py tests/unit/test_cli_spec_retarget.py tests/unit/test_cli_typer_app.py
exit 0

git diff --check
exit 0
```

## Assumptions

- The coordinator receives canonical targets; CLI callers obtain them through
  the existing Phase A resolver with `allow_missing=False` one declaration at
  a time so aliases cannot be silently collapsed.
- State spelling uses `checkpointed/invalidating/rebuilding/finalizing/failed`;
  history translates `checkpointed` to its Task 3 `prepared` status.
- `status == done` is the bounded preview readiness label; the authoritative
  downstream readiness gate remains the existing Phase A controller.
- The four old coverage artifacts are optional Git entries, but any present
  entry must be a regular blob and is represented exactly in the manifest.

## Self-review and Concerns

- Verified preview snapshots include workspace bytes, Git object names, refs,
  object counts, and porcelain status.
- Verified no broad delete/glob, no target-repository writes, no workspace graph
  refresh, and no staging of unrelated paths.
- Verified callback output and flush precede bootstrap and purge.
- Verified runtime/history retry identity and durable failure behavior.
- Verified only Task 7 files are staged.
- Concern: `spec_retarget.py` is now a large coordinator module. Decomposition
  would improve maintainability, but was intentionally not attempted because
  Task 7 fixes the coordinator location and forbids broad refactoring. The CLI
  parser/rendering boundary is already isolated in `spec_retarget_cli.py`.

## Commit

- SHA: `8fc66a98946a9556637e3aac1afb3ea5f0d876a6`
- Subject: `feat: add destructive spec retarget command`

## Independent Review Fix Round 1

The review found five blocking correctness and safety gaps. This follow-up:

- makes the canonical `specs/<id>` publication the destructive owner while
  preserving `SpecRun.spec_dir` as the immutable run shadow;
- resumes checkpointed and invalidating retries under the original mutation,
  Phase A, and baseline-run locks, replaying the durable checkpoint callback
  before completing purge, canonical/shadow invalidation, graph invalidation,
  checkpoint context, and rebuilding persistence;
- adopts an already committed `prepared` revision after a crash before
  replacement-run installation, reusing its exact revision, checkpoint, and
  deterministic replacement run;
- replaces path-recursive deletion with descriptor-relative validation,
  atomic quarantine, inode revalidation, and descriptor-relative removal for
  both the canonical publication and replacement shadow;
- extracts checkpoint context through the verified `ls-tree` blob object and
  fails closed when `git cat-file` cannot read it.

Initial focused RED evidence:

```text
.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py -k 'owns_published_canonical or extraction_failure'
2 failed, 34 deselected in 0.60s

.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py -k 'swap_race or finishes_remaining or adopts_prepared'
5 failed, 36 deselected in 2.64s
```

Focused GREEN evidence:

```text
.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py -k 'owns_published_canonical or extraction_failure'
2 passed, 39 deselected in 0.59s

.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py -k 'artifact_invalidation or swap_race'
6 passed, 35 deselected in 0.22s

.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py -k 'finishes_remaining or adopts_prepared'
3 passed, 38 deselected in 2.19s

.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py -k 'swap_race or finishes_remaining or adopts_prepared'
5 passed, 36 deselected in 2.09s
```

Final verification:

```text
.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py tests/unit/test_cli_typer_app.py tests/unit/test_spec_retarget.py
120 passed in 6.81s

.venv/bin/pytest -q tests/unit/test_phase_a_start.py tests/unit/test_spec_lifecycle.py tests/unit/test_spec_retarget_history.py tests/unit/test_mempalace_retarget.py tests/unit/test_spec_retarget_graph.py tests/unit/test_phase_checkpoints.py tests/unit/test_squad_phase_checkpoints.py
421 passed in 69.84s

.venv/bin/python -m py_compile src/echelon/spec_retarget.py src/echelon/spec_retarget_cli.py src/echelon/cli.py src/echelon/cli_app.py tests/unit/test_cli_spec_retarget.py tests/unit/test_cli_typer_app.py tests/unit/test_spec_retarget.py
exit 0

git diff --check
exit 0
```

Fix commit:

- SHA: `54e28caa`
- Subject: `fix: harden destructive retarget recovery`

## Independent Review Fix Round 2

The post-review root-swap finding is closed by pinning the canonical
publication and replacement-shadow directory descriptors before validation.
Quarantine, target-contract publication, and post-publication verification use
those descriptors; each publication reauthenticates the public directory name
against its original inode and fails closed if it was renamed or replaced.
`targets.yml` is now written through a descriptor-relative temporary file,
fsynced, atomically replaced through the same descriptor, and followed by a
directory fsync. No target-contract write follows a replacement root path.

TDD evidence:

```text
.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py -k 'root_swap_before_target_publication'
2 failed, 41 deselected in 0.27s

.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py -k 'root_swap_before_target_publication or artifact_invalidation or finishes_remaining'
10 passed, 33 deselected in 0.95s
```

The new deterministic cases replace the canonical root and then the replacement
shadow after quarantine but before `targets.yml` publication. Each asserts a
fail-closed error, unchanged external contract bytes, and no temporary-file
residue. Existing retry coverage also verifies identical target bytes and mode
`0600` in both owned roots.

Verification:

```text
.venv/bin/pytest -q tests/unit/test_cli_spec_retarget.py tests/unit/test_cli_typer_app.py tests/unit/test_spec_retarget.py
122 passed in 6.40s

.venv/bin/pytest -q tests/unit/test_phase_checkpoints.py tests/unit/test_squad_phase_checkpoints.py
86 passed in 28.16s

.venv/bin/python -m py_compile src/echelon/spec_retarget.py tests/unit/test_cli_spec_retarget.py
exit 0

git diff --check
exit 0
```
