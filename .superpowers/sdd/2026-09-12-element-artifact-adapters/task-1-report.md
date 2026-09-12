# Task 1 report: source-preserving typed artifact adapters

## Status

DONE. Implementation commit: `3e066a66` (`feat: add source-preserving identity artifact adapters`).

This is a parser checkpoint only. It does not yet enforce publication, mutate
controller storage, allocate IDs, bind references, or integrate producers,
publication flows, or CLI commands.

## Implemented

- Added the immutable public artifact models and keyword-only
  `parse_identity_artifact` entry point.
- Added exact role routing, canonical relative-path/API validation, original
  UTF-8 content hashing, and tuple-backed immutable results.
- Added a source-offset Markdown scanner that preserves CRLF and Unicode source
  slices while excluding frontmatter, comments, matching backtick/tilde
  fences, blockquotes, and indented code from authority.
- Added role-owned heading, bullet, task-row, and issue-occurrence declarations
  with exact label/block spans and captions.
- Reused `kernel.task_contract.parse_task_rows` for canonical task validity and
  metadata, retaining duplicate valid rows before diagnosis.
- Added reference extraction for local labels, path labels, task `req=` and
  `depends=` relations, evidence relations, and unexpanded same-kind numeric
  ranges using `kernel.element_ids.decimal_to_int`.
- Added explicit diagnostics for malformed syntax and tasks, wrong-role or
  unsupported definitions, duplicate definitions/projections/occurrences,
  invalid ranges, unterminated inactive regions, ambiguous nested ID blocks,
  and unsupported qualified cross-spec references.
- Added whole-document Lexicon validation through `lexicon.parser.parse`, then
  source-aligned projection of every supported FR/NFR `REQ` and AC block.
- Added sanitized before/after discovery and retained-evidence fixtures and
  documentation of ownership, syntax, diagnostics, and the deliberate parser
  boundary.

## TDD evidence

### RED: missing public interface

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_artifacts.py tests/unit/test_element_artifact_lexicon.py -q
```

Expected failure before production modules existed (exit 2):

```text
ERROR tests/unit/test_element_artifacts.py
E   ModuleNotFoundError: No module named 'harness.element_artifacts'
ERROR tests/unit/test_element_artifact_lexicon.py
E   ModuleNotFoundError: No module named 'harness.element_artifacts'
2 errors in 0.25s
```

### RED: behavioral assertions against the minimal importable API

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_artifacts.py::test_question_declaration_and_evidence_reference_are_distinct tests/unit/test_element_artifacts.py::test_heading_and_bullet_blocks_preserve_crlf_unicode_and_boundaries tests/unit/test_element_artifacts.py::test_qualified_cross_spec_references_are_diagnostic_not_local_bare_ids tests/unit/test_element_artifact_lexicon.py::test_derived_lexicon_is_not_an_independent_definition -q
```

Expected failure from the empty parser skeleton (exit 1):

```text
FFFF                                                                     [100%]
FAILED ...::test_question_declaration_and_evidence_reference_are_distinct
FAILED ...::test_heading_and_bullet_blocks_preserve_crlf_unicode_and_boundaries
FAILED ...::test_qualified_cross_spec_references_are_diagnostic_not_local_bare_ids
FAILED ...::test_derived_lexicon_is_not_an_independent_definition
4 failed in 0.19s
```

### Additional focused RED cycles

Full-token and ambiguous-declaration command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_artifacts.py::test_unsupported_unicode_suffix_cannot_create_a_shorter_reference tests/unit/test_element_artifacts.py::test_ambiguous_or_malformed_id_bearing_bullets_are_diagnostic -q
```

Expected output before the boundary fix:

```text
FFF                                                                      [100%]
FAILED ...::test_unsupported_unicode_suffix_cannot_create_a_shorter_reference
FAILED ...::test_ambiguous_or_malformed_id_bearing_bullets_are_diagnostic[...unsupported_declaration]
FAILED ...::test_ambiguous_or_malformed_id_bearing_bullets_are_diagnostic[...ambiguous_block_boundary]
3 failed in 0.19s
```

Task/path/range mutation-review command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_artifacts.py::test_task_like_rows_are_never_silently_omitted tests/unit/test_element_artifacts.py::test_duplicate_canonical_task_rows_are_retained_before_diagnosis tests/unit/test_element_artifacts.py::test_ascii_hyphen_prose_delimiter_is_not_a_dangling_range tests/unit/test_element_artifacts.py::test_invalid_api_inputs_raise_value_error -q
```

Expected output before the fixes:

```text
...F.F......F...                                                         [100%]
FAILED ...::test_task_like_rows_are_never_silently_omitted[...T-FOO...]
FAILED ...::test_ascii_hyphen_prose_delimiter_is_not_a_dangling_range
FAILED ...::test_invalid_api_inputs_raise_value_error[kwargs6-path]
3 failed, 13 passed in 0.20s
```

Level-three authority and inline-comment tests each failed independently
before their respective fixes, then passed after the minimal changes:

```text
FAILED ...::test_unknown_assumption_and_issue_authority_requires_level_three_headings
1 failed in 0.18s

FAILED ...::test_inline_html_comments_hide_only_the_comment_not_active_source_around_it
1 failed in 0.20s
```

### GREEN: requested adapter and compatibility suites

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_artifacts.py tests/unit/test_element_artifact_lexicon.py tests/unit/test_tasks_canonical_contract.py tests/unit/test_lexicon_parser.py tests/unit/test_requirement_projection.py tests/unit/test_issue_identity.py -q
```

Fresh final output (exit 0):

```text
........................................................................ [ 81%]
................                                                         [100%]
88 passed in 1.56s
```

Source hygiene command and result:

```text
git diff --check
```

Exit 0 with no output.

## Files changed

- `src/harness/element_artifacts.py`
- `src/harness/element_artifact_markdown.py`
- `src/harness/element_artifact_lexicon.py`
- `tests/unit/test_element_artifacts.py`
- `tests/unit/test_element_artifact_lexicon.py`
- `tests/fixtures/element_identity/discovery/before/unknowns.md`
- `tests/fixtures/element_identity/discovery/after/unknowns.md`
- `tests/fixtures/element_identity/discovery/evidence-grades.md`
- `docs/element-identity-artifacts.md`
- `.superpowers/sdd/2026-09-12-element-artifact-adapters/task-1-report.md`

## Decisions

- Treated unknown, assumption, and issue declaration authority as exact level-3
  headings, while requirements retain general ID-heading support.
- Treated a Lexicon declaration caption as its rendered `THEN:` clause because
  REQ/AC grammar blocks have no separate title field; this remains source
  presentation, not registry-subject authority.
- Retained unsupported-but-grammar-valid Lexicon blocks long enough to diagnose
  their exact label while continuing to report other supported blocks.
- Diagnosed nested declaration-shaped bullets as ambiguous while retaining the
  enclosing declaration's exact source block.
- Diagnosed explicit qualified references rather than converting their suffix
  to a local reference. Ordinary local `investigation/U-001.md` remains
  supported. No namespace resolver was added.
- A spaced ASCII hyphen is a range only when a supported second endpoint is
  present; without one it remains ordinary prose punctuation. En/em dashes and
  `..` are unambiguous range operators and missing endpoints are diagnostic.

## Self-review

- Re-read the complete task diff for source ownership boundaries, exact label
  exclusion, full-token suffix matching, task row retention, and Lexicon AC
  preservation.
- Mutation review found and fixed Unicode suffix prefix-truncation, unsupported
  task labels, a false dangling-range diagnostic for prose hyphens, acceptance
  of `.` as a path, incorrect non-level-3 declaration authority, and whole-line
  suppression caused by inline HTML comments. Each fix was preceded by a
  focused failing test.
- Verified the fixture only demonstrates changed/removed declarations and
  retained references. It makes no publication-rejection claim.
- Verified no storage, publication, producer, CLI, installation, or main
  workspace mutation is part of the implementation.

## Concerns

None. The documented limitation is intentional: artifacts with diagnostics are
not eligible for future managed publication, but enforcement and live rollout
remain later checkpoints.

---

## Fix round 1/5 — parser review findings

Status: DONE. Fix implementation commit: `cb2eece6` (`fix: close identity
artifact parser gaps`). This remains a parser-only checkpoint and does not yet
enforce publication.

### Findings addressed

1. Lexicon REQ/AC headers now validate the complete supported label rather than
   accepting a family prefix and silently skipping the remainder. Every
   grammar-valid unsupported label receives `unsupported_lexicon_id` at its
   exact source span.
2. Source alignment for grammar-validated Lexicon blocks now accepts the same
   leading horizontal whitespace as the existing grammar, preserving exact
   indented block and label spans.
3. Canonical task `req=` and `depends=` values are registered as relation
   regions before range extraction. Valid intervals are emitted once with the
   field relation; invalid intervals are diagnosed and their endpoints cannot
   reappear independently.
4. Four-space continuation paragraphs and nested lists owned by a list item
   stay active for references, while deeper indented code and standalone
   indented code remain inactive.
5. HTML comments and fences are processed as one lexical state machine, so a
   fence delimiter inside a comment cannot open a fence or hide later source;
   comment markers inside fences likewise remain inert.
6. Supported nested ID bullets are retained as child declarations, and
   overlapping heading/bullet blocks select the innermost declaration as the
   reference owner. Genuinely ambiguous indented ID headings remain diagnostic
   and cannot silently attach a child reference to the parent.
7. Explicit ID-bearing headings that fail supported syntax, including missing
   colons and unsupported Unicode suffixes, receive
   `unsupported_declaration` and are excluded from bare-reference extraction.

### TDD RED evidence

Tests were added for all seven findings before production changes.

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_artifacts.py tests/unit/test_element_artifact_lexicon.py -q
```

Expected pre-fix output (exit 1):

```text
........FF.....F...............FF.FF....................FF...            [100%]
FAILED tests/unit/test_element_artifacts.py::test_list_owned_four_space_continuations_are_active_but_indented_code_is_not
FAILED tests/unit/test_element_artifacts.py::test_fence_delimiter_inside_html_comment_cannot_hide_later_active_source
FAILED tests/unit/test_element_artifacts.py::test_task_metadata_ranges_are_single_relation_aware_intervals
FAILED tests/unit/test_element_artifacts.py::test_valid_nested_bullet_declaration_has_innermost_reference_ownership
FAILED tests/unit/test_element_artifacts.py::test_nested_heading_reference_uses_innermost_declaration_owner
FAILED tests/unit/test_element_artifacts.py::test_unsupported_explicit_headings_are_diagnostic_not_references[### U-001 Question without colon\n-U-001]
FAILED tests/unit/test_element_artifacts.py::test_unsupported_explicit_headings_are_diagnostic_not_references[### U-001\xe9: Unsupported suffix\n-U-001\xe9]
FAILED tests/unit/test_element_artifact_lexicon.py::test_every_grammar_valid_unsupported_req_or_ac_label_is_diagnostic
FAILED tests/unit/test_element_artifact_lexicon.py::test_valid_indented_lexicon_blocks_preserve_declarations_and_boundaries
9 failed, 52 passed in 0.33s
```

The original brief's ambiguous-boundary guarantee was also retained with a
separate RED after valid nested bullets became supported:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_artifacts.py::test_ambiguous_or_malformed_id_bearing_bullets_are_diagnostic -q
.F                                                                       [100%]
FAILED ...::test_ambiguous_or_malformed_id_bearing_bullets_are_diagnostic[...ambiguous_block_boundary]
1 failed, 1 passed in 0.20s
```

### GREEN evidence

Focused adapter suites:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_artifacts.py tests/unit/test_element_artifact_lexicon.py -q
..............................................................           [100%]
62 passed in 0.27s
```

Original requested adapter/compatibility command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_artifacts.py tests/unit/test_element_artifact_lexicon.py tests/unit/test_tasks_canonical_contract.py tests/unit/test_lexicon_parser.py tests/unit/test_requirement_projection.py tests/unit/test_issue_identity.py -q
........................................................................ [ 74%]
.........................                                                [100%]
97 passed in 1.52s
```

Source hygiene:

```text
git diff --check
```

Exit 0 with no output.

### Files changed in fix round 1

- `src/harness/element_artifact_markdown.py`
- `src/harness/element_artifact_lexicon.py`
- `tests/unit/test_element_artifacts.py`
- `tests/unit/test_element_artifact_lexicon.py`
- `docs/element-identity-artifacts.md`
- `.superpowers/sdd/2026-09-12-element-artifact-adapters/task-1-report.md`

### Self-review and concerns

- Rechecked all seven reviewer probes against the final code paths, including
  range blocking order, Lexicon full matches, exact indented source slices,
  comment/fence precedence, list-relative indentation, overlapping owners, and
  malformed-heading exclusion spans.
- Confirmed valid non-range task metadata retains `requires`/`depends`, legacy
  range behavior remains unexpanded, and actual indented code remains outside
  authority.
- Confirmed the changes do not touch stores, publication, producers, CLI,
  installation, or the parent-only planning commit.
- Concerns: none.
