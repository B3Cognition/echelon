# Task 1 implementation report

Status: implemented and verified; ready for parent review. Only Task 1 files were
changed. The parent-owned plan modification is deliberately excluded from the
commit. No Ralph/coordinator changes, install, provider invocation, identity
activation, push, or global configuration changes were performed.

## Delivered behavior

- `DeliveryDocumentationRunner` implements the exact requested keyword interface.
  Successful output is `done`, `task_ids=[]`, reason
  `delivery_documentation_passed`, with cumulative operation usage. All other
  returned outcomes are blocked; three rejected author/reviewer pairs exhaust
  as `delivery_documentation_repair_limit`, including reconstruction.
- Author and reviewer load distinct neutral installed Prosaic profiles, share
  provider-neutral assignment metadata, and dispatch with exclusive scopes.
  Only README.md and CHANGELOG.md are writable by the author; the reviewer has
  no writable paths. Spec, evidence, Git and provider/control roots are forbidden.
- Python captures specification/verification/configuration context and current
  immutable runnability receipt content and selector. Required missing/stale
  evidence blocks before entry. Original feedback, actual sorted task scope,
  roles, paths, context, source/control bytes and budget are bound to the journal.
- The writer impact report is staged outside the candidate. Python runs the
  real deterministic verifier, passes its baseline and staged impact text to the
  independent reviewer, validates the returned JSON/frontmatter, and evaluates
  the real staged documentation gate and coverage map against the candidate.
  Semantic PASS cannot erase deterministic failures. Independent, deterministic
  and gate findings all flow into the next author attempt.
- The strict journal validator enforces fields, types, bounded reports/JSON,
  unique dispatches, ordering, candidate chains, attempts, token usage,
  completion/error states and exact publication images. The existing
  DeliverySliceJournal lock and durable JSON writer remain the storage authority.
- Intent is durable before provider entry; validated completion is durable before
  advancing. Unknown entry/return windows never re-dispatch. Tightened ceilings
  persist; unknown usage under a finite ceiling cannot advance or publish.
- Source guarding catches ignored files and completion-marker writes as well as
  product/spec/control mutations. Evidence is fingerprinted around provider entry
  to detect writes to the receipt authority itself. Reviewer candidate mutations
  block. Canonical report before-images are guarded separately.
- Both exact before/after reports are journaled before publication. UTF-8 bytes,
  including CRLF, are preserved. Descriptor-pinned atomic replacement compares
  the current before-image before writing and immediately before replace. Recovery
  completes a partial pair only from matching recorded before/after images and
  matching candidate/context. Success is returned only after both writes and the
  completed publication journal save.

## Changed files

- `src/harness/delivery_documentation.py` — runner, input capture, guard, staged
  verification, replay and publication.
- `src/harness/delivery_documentation_contract.py` — strict result/report/journal
  validation, including duplicate JSON/YAML rejection.
- `src/harness/delivery_slice_journal.py` — optional validator; default existing
  implementation-slice schema unchanged.
- `src/harness/delivery_slice_runner.py` — optional narrowly validated exclusion
  of the two controller-owned report paths in protected fingerprinting.
- `src/harness/durable_json.py` — shared descriptor-pinned text replacement with
  optional exact before-image check; default JSON serialization remains unchanged.
- `prosaic/subagents/echelon.delivery-tech-writer.md` and
  `prosaic/subagents/echelon.delivery-docs-verifier.md` — neutral protocols retaining
  report v2 schemas, first-run/evidence requirements and independent findings.
- `tests/unit/test_delivery_documentation.py` — consuming runner tests using the
  existing temporary project and scripted Prosaic inspection fixture.
- This report.

## Exact RED/GREEN evidence

All pytest commands used
`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest` from the designated
worktree. No repository-wide suite was run.

1. Initial collection exposed an incorrect fixture import (`test_delivery_slice_runner`);
   fixed to the existing `tests.unit.test_delivery_slice_runner` import before RED.
2. `-q tests/unit/test_delivery_documentation.py -x`: **1 failed**, missing
   `harness.delivery_documentation`, proving the requested runner did not exist.
3. Initial implementation `-q tests/unit/test_delivery_documentation.py`:
   **21 passed in 5.25s**.
4. Added adversarial consuming tests, same command: **4 failed, 39 passed in
   10.99s**. Failures proved ignored-file writes, build-marker writes, no-impact
   inventory mismatch and alteration at the report-write boundary could pass.
   After fixes: **43 passed in 6.87s**.
5. Added captured verification/evidence-authority tests, same command:
   **2 failed, 55 passed in 8.75s**. Verification text was absent from provider
   context and a rewritten evidence journal went undetected. After fixes:
   **57 passed in 8.75s**.
6. `-q tests/unit/test_delivery_documentation.py -k 'line_endings or exact_types'`:
   **4 failed, 57 deselected in 1.11s**. CRLF before-images were normalized,
   booleans were accepted as evidence counts, string flags and duplicate YAML
   verdict fields were accepted. Fixed before the regression batch.
7. An initial regression command included nonexistent
   `tests/unit/test_codex_product_plane_scope.py`: **no tests ran**, exit 4. This
   was corrected to the real provider suite, not treated as verification.
8. Single surrounding regression batch:

   ```text
   -q tests/unit/test_delivery_documentation.py
      tests/unit/test_durable_json.py
      tests/unit/test_delivery_slice.py
      tests/unit/test_delivery_slice_runner.py
      tests/unit/test_delivery_slice_recovery.py
      tests/unit/test_claude_delivery_scope.py
      tests/unit/test_llm_provider.py
   ```

   Result: **242 passed in 16.72s** (61 documentation cases and 181 existing
   durability/delivery/recovery/provider cases).
9. Final review found the legacy no-impact gate intentionally permits low evidence
   counts. Added a strict controlled-report case:
   `-q tests/unit/test_delivery_documentation.py -k no_evidence`:
   **1 failed, 61 deselected in 0.46s**. Controlled PASS now requires four checked
   evidence items and true validity flags even for no-impact reports. The final
   focused suite returned **62 passed in 10.09s**; this last change is isolated to the
   new documentation validator, so the surrounding suites were not repeated.
10. `git diff --check` passed before staging.

## Review notes and limitations

- Source enforcement streams file hashes and stores only paths/modes/digests in
  temporary memory, not dependency-file contents. It intentionally includes
  ignored files and dependency/cache trees; large trees add filesystem cost.
  No alternate inventory framework was introduced.
- The existing runnability validator establishes receipt digest/currentness and
  initial candidate/contract identity. Resolved-stack identity comes from the
  caller's supplied reference; Ralph remains responsible for selecting current
  evidence against its resolved stack. Task 1 does not create a second stack
  resolution authority or execute runnability commands.
- Output safety uses the existing pinned-directory atomic replacement mechanics
  with repeated before-image comparisons. It is not a kernel-level atomic
  compare-and-swap against a completely uncooperative concurrent filesystem
  writer between the last comparison and rename. The operation journal lock
  serializes matching operations, and changed before/after images block recovery.
- No live provider smoke test was run (explicitly out of scope). Provider parity
  is checked through neutral metadata and existing adapter regression suites.
- No known planned Task 1 test category remains unimplemented. Parent review and
  Task 2 integration remain outstanding.
