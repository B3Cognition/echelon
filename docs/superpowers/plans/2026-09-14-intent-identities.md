# Intent identities implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The user requested inline implementation; independent read-only review follows verification.

**Goal:** Add approved UI/II identities to the existing allocator, source/candidate checks, retained history and graph projection before managed Tracker integration.

**Architecture:** Extend existing closed family sets and reuse the same SQLite transactions and lifecycle/reference/publication owners. Add a narrow `intent` artifact role for the two existing Tracker table layouts; do not interpret arbitrary Markdown tables as canonical definitions.

**Tech Stack:** Existing Python, SQLite, pytest and source-preserving Markdown adapters.

**Spec:** User-approved inline design: UI (explicit user intent) and II (inferred intent) use the existing stable-ID authority with six-digit-minimum counters and preservation tests. No separate counters.

## Global constraints

- New numeric labels have at least six digits, with no maximum width.
- Imported labels retain their exact spelling; UI-001 must never become UI-000001.
- Subjects and reference assessments remain bound to their original identity/revision.
- Existing schema and saved records are not rewritten. Older binaries that do not recognize new families must not be used against registries containing them.
- Discovery remains U/A-only. No managed Tracker dispatch, new provider integration, installation, migration, activation, legacy build changes, or AGENTS.md/CLAUDE.md edits.

## Task 1: Existing authority and source contract

**Files:** Modify `src/kernel/element_ids.py`, `src/harness/element_identity_store.py`, `src/harness/element_identity_lifecycle.py`, `src/harness/element_artifacts.py`, `src/harness/element_artifact_reference_tokens.py`, `src/harness/element_artifact_markdown.py`, `src/harness/element_identity_candidate.py`, `src/echelon/spec_graph_identity.py`; create `src/harness/element_artifact_intent.py` and `tests/unit/test_intent_identities.py`.

**Interfaces:** Existing `IdentityStore.reserve/import_identities/apply_lifecycle/record_reference_claims/preview_identity_candidate`, `parse_identity_artifact(path=..., role="intent", text=...)`, and `project_identity_history` keep their signatures. The new detached table parser consumes captured text, active lines and offsets; it returns the existing declaration/diagnostic records, never authority.

- [x] Add real-file allocator tests for UI/II isolation, reopen/retry, conflicting operation IDs, legacy padding aliases, million/beyond-int counters and arbitrary-width numeric ordering. Example expectation:
  ```python
  assert store.reserve(spec_id="demo", kind="UI", operation_id="new", count=1) == ("UI-000001",)
  ```
- [x] Add real Tracker-layout parsing and candidate tests. `| UI-001 | Statement | Source / Context | high |` is a definition only below the four-column explicit header and separator in the `intent` role; the analogous inference header accepts II. Preserve exact row bytes/spans. Malformed rows, wrong-family rows and duplicate definitions reject; examples in fences/comments/quotes are not definitions. References in source/evidence cells retain their row owner.
- [x] Run new tests against the baseline and record failures. Extend family recognition and numeric ordering; no new allocator or schema migration.
- [x] Implement the specific table adapter through the existing Markdown active-source scanner. Blank IDs in otherwise filled template rows reject. UI/II headings/bullets are not a replacement for the existing table contract. Same-subject revisions may change statement wording through lifecycle review; UI cannot silently become II.
- [x] Exercise real candidate/publication history with exact reserved creation, same-subject revision, failed deletion/renumber/subject replacement and historical reference assessment. Add graph assertions for distinct `UserIntent`/`InferredIntent` nodes and retained revision edges.
- [x] Run targeted tests to green, then affected identity/parser/history/graph regressions. Inspect any broader parser compatibility failures without widening scope.

## Task 2: Review and handoff

- [x] Independent read-only review of the changes and test coverage; reproduce and correct concrete findings.
- [x] Record results and the remaining managed Tracker/source-chain/clarification work in the existing convergence/deferred records.
- [x] Check the diff and commit only this verified checkpoint locally. Keep installation, live acceptance and full activation off.

## Verification and review record

- Initial allocator/reference baseline: 759 passed in 4.80s.
- Initial 19 intent tests failed before implementation (unsupported families and
  artifact role), then all 19 passed. Selected existing identity/parser/history/
  graph regressions: 1,795 passed in 43.56s.
- Negative-row expansion reproduced six missing-pipe/decorated-ID rejection
  failures; a further missing-separator/blank-ID case also failed before its fix.
  The adapter now diagnoses these rows rather than treating them as references.
- Test fixture corrections retained existing authority: new headers need explicit
  unowned-text scope; immutable-subject rejection is a candidate diagnostic, not
  a raised exception. No scope or lifecycle validation was weakened.
- Final focused intent tests: 39 passed in 11.22s, including 4,400-digit allocation,
  no-mutation rejection, source spans, Discovery exclusion, range/qualified tokens,
  real publication-history persistence and old/current graph revision edges.
- Intent and expanded shared reference-token tests: 810 passed in 1.75s.
- Final affected identity/parser/graph/discovery/repair regression run:
  **4,455 passed in 761.26s (12m41s)**. Final focused 39-test rerun also includes
  the graph-edge assertions added while the broader run was in progress.
- `git diff --check` passed. Only this checkpoint's source, tests and records are
  included in the local commit; no installation, migration, push or activation.
- Independent read-only review reproduced the parser gaps, verified their fixes,
  and returned no remaining findings (35-test snapshot passed independently).
  The four later tests add explicit Discovery exclusion and range/qualified token
  coverage; final graph assertions verify retained assessment/current edges.
- These tests use local SQLite and the existing journal helper; its opaque test
  filesystem manifest does not prove managed filesystem publication, provider
  execution, Tracker routing or rollout readiness.

Final affected-regression command (run with the repository `.venv/bin/python`):

```sh
python -m pytest tests/unit/test_element_id*.py tests/unit/test_element_artifact*.py tests/unit/test_spec_graph*.py tests/unit/test_discovery*.py tests/unit/test_definition_identity_candidate.py tests/unit/test_supplemental_identity_bundle.py tests/unit/test_issue_identity*.py tests/unit/test_identity_graph*.py tests/unit/test_intent_identities.py -q --tb=short
```

Compatibility: schema and old records stay unchanged, but reference recognition
now includes UI/II. Previously ignored mentions may need explicit reconciliation.
No legacy source is automatically adopted and older binaries must not be used
against registries populated with the new families. Managed Tracker integration
and full activation remain pending in the existing convergence/deferred records.
