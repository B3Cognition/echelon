# Task 1 report: captured graph-input compatibility parsers

## Status and scope

Status: DONE

Worktree: `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`

Branch: `fix/delivery-controller-contract`

Required base and starting HEAD:
`1c6e7ca73b8831919987ce7747670e4f38b75937`

The change extracts only the three approved pure text parsing boundaries. It does
not construct a graph, select or authenticate captured dependencies, validate
managed evidence, change lifecycle/publication/state/controller/provider/CLI
behavior, or strengthen the permissive legacy parsing policies.

## Implementation and files

- `src/harness/canonical_requirements.py`
  - Added keyword-only `extract_canonical_requirements_from_texts` with exact
    `str`/`None` outer-type checks.
  - Preserved the spec, plan, coverage and task precedence and filenames, existing
    regexes/helpers, definition supersession, task `setdefault`, line handling,
    stripping and `element_id_sort_key` ordering.
  - Kept the filesystem reader's `is_file` checks and UTF-8 replacement reads and
    retained both private filesystem helper signatures.
- `src/harness/deferred_scope.py`
  - Added `parse_deferred_scope_ledger` with an exact-string boundary.
  - Moved only JSON parsing, schema/entry interpretation and duplicate entry-ID
    rejection into the pure function.
  - Kept nonexistent-file behavior and existing bounded wrapping of I/O, decoding
    and malformed JSON failures in `DeferredScopeError`.
- `src/harness/verified_fulfillment_ledger.py`
  - Added `parse_verified_ledger` with an exact-string boundary.
  - Moved the existing permissive JSON-to-row conversion unchanged, including
    ignored non-object rows, status uppercasing, defaults, duplicate row order,
    evidence tuples, and fresh ordinary nested dictionaries.
  - Kept the filesystem reader's missing-file and decoding failure propagation.
- `tests/unit/test_graph_source_parsers.py`
  - Added the three required captured-source mutation regressions and independent
    complete expected records.
  - Added all-source requirement precedence/ordering coverage, CRLF/Unicode,
    legacy families/shapes, range endpoints, suffixes, composites and the exact
    000001/999999/1000000/10000000 plus generated 5000-digit numeric cases.
  - Added deferred/verified compatibility, error, type, freshness and purity
    coverage, including filesystem/stat/enumeration/environment and imported
    clock/workflow-reader tripwires.
- `docs/element-identity-storage.md`
  - Documents all three helpers as detached compatibility observations, not
    managed validation, evidence proof or graph authority, and records the
    remaining authentication and integration boundary.

No existing reader test module needed modification: the new compatibility module
contains the independent parser contracts, while the named existing modules retain
and cover their read/defer/restore, graph and CLI flows.

## Actual RED evidence before production

All three tests first established a valid fixture and independently asserted the
existing filesystem reader's complete result. Each then mutated its source and
failed only when invoking the missing pure entry point on the original captured
string.

Exact working directory for every command below:
`/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`

Exact RED command (one invocation containing the three separate regressions):

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_graph_source_parsers.py -q
```

Exit: 1. Summary: `3 failed in 0.18s`.

1. Requirement capture RED output:

   ```text
   AttributeError: module 'harness.canonical_requirements' has no attribute 'extract_canonical_requirements_from_texts'
   ```

   Why this was the intended RED: the CRLF source fixture and independently
   expected `CanonicalRequirement` filesystem-read assertion had already passed;
   only the new captured-text boundary was absent.

2. Deferred-scope capture RED output:

   ```text
   AttributeError: module 'harness.deferred_scope' has no attribute 'parse_deferred_scope_ledger'
   ```

   Why this was the intended RED: the complete ledger fixture and independently
   expected filesystem-read assertion had already passed; only the new pure parser
   was absent.

3. Verified-ledger capture RED output:

   ```text
   AttributeError: module 'harness.verified_fulfillment_ledger' has no attribute 'parse_verified_ledger'
   ```

   Why this was the intended RED: the complete v2 row fixture and independently
   expected filesystem-read assertion had already passed; only the new pure parser
   was absent.

Root was notified of all three actual missing-attribute failures before any
production edit and acknowledged the gate.

## GREEN and covering verification

Initial focused GREEN after the shared-body extraction:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_graph_source_parsers.py -q
.............................                                            [100%]
29 passed in 0.21s
```

After self-review strengthened only the purity tripwire, the named focused check
was rerun because the test itself changed:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_graph_source_parsers.py -q
.............................                                            [100%]
29 passed in 0.20s
```

The required seven-module covering set was run once on final production code:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_graph_source_parsers.py tests/unit/test_canonical_requirements.py tests/unit/test_deferred_scope.py tests/unit/test_verified_fulfillment_ledger.py tests/unit/test_spec_graph.py tests/unit/test_spec_graph_audit.py tests/unit/test_harness_main_deferred_scope.py -q
........................................................................ [ 64%]
........................................                                 [100%]
112 passed in 0.83s
```

All GREEN output was clean: no warnings, errors, captured stderr, provider/capacity
traffic or other unexpected noise. No full-unit, integration/capacity/live,
installed-CLI, global-install, stopped-smoke or unchanged postcommit repeat was
run. The named existing offline CLI coverage was included only through the
approved modules.

## Self-review

- Shared-code review: the regex and precedence loops exist once in text-owned
  private helpers; both filesystem wrappers delegate rather than copy policy.
- Compatibility review: exact filenames, source kinds, one-based `splitlines`,
  stripped text, definition supersession, task fallback/exclusions, legacy ID
  shapes, arbitrary-width ordering, deferred messages/defaults/duplicate checks,
  and verified permissive conversion/order were retained.
- Error/I/O review: requirement path reads retain `is_file` plus
  `errors="replace"`; deferred absence/I/O/Unicode/JSON distinctions retain their
  prior public exceptions; verified missing/Unicode/JSON/shape exceptions still
  propagate as before. Pure functions reject non-exact outer text types before
  parsing and contain no filesystem, stat, enumeration, environment, clock,
  provider, database or process access.
- Freshness review: every call constructs fresh records; verified mapping fields
  are ordinary detached dictionaries, and mutating one parse cannot alter another
  parse or the input text. Evidence remains attached to its original row and is
  not upgraded based on status.
- Documentation review: explicitly observation-only; no graph activation or proof
  claim.
- Diff review: `git diff --check` and staged `git diff --cached --check` were clean.

Self-review correction chronology:

1. After the initial 29-test GREEN, expanded the existing purity test only to deny
   `os.getenv` and the imported deferred clock/workflow and verified fulfillment
   metadata entry points. No production code changed. The focused 29-test GREEN
   and final 112-test covering evidence above include that correction.
2. No post-covering production or test amendments were made.

## Staged and commit-tree provenance

Before the implementation commit, the staged tree contained exactly:

```text
M docs/element-identity-storage.md
M src/harness/canonical_requirements.py
M src/harness/deferred_scope.py
M src/harness/verified_fulfillment_ledger.py
A tests/unit/test_graph_source_parsers.py
```

Staged tree SHA-1: `c2465216bebe7442d3038b7acc845177ed9f7480`

Implementation commit:
`f11c4f88f5dba039a90765b047034b05142ccfe8`
(`feat(harness): add captured graph input parsers`)

Committed tree SHA-1: `c2465216bebe7442d3038b7acc845177ed9f7480`

The commit is directly based on
`1c6e7ca73b8831919987ce7747670e4f38b75937`. It contains 5 scoped files,
698 insertions and 17 deletions. There were no later implementation amendments.
The ignored task brief and this report are force-added in a separate report-only
commit so the report can cite the immutable implementation commit and tree; that
final report commit is returned in the task handoff because a commit cannot embed
its own hash.

The root-owned
`.superpowers/sdd/2026-09-13-captured-graph-input-parsers/progress.md` remained
modified in the worktree and was excluded from both scoped staging sets.

## Concerns and honest limits

No scoped implementation concern remains.

These parsers intentionally preserve permissive legacy observations. They do not
authenticate managed definitions, selected source coverage, evidence or current
identity revision. Graph assembly still lacks the other policy, traceability,
amendment, memory-audit, RE/topology, sealing, lifecycle, completion and repair
owners named in the brief; no live caller uses these captured inputs yet.
