# Element ID numeric compatibility implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Complete phase 1 of the approved durable-identity design: remove numeric reader/allocation ceilings without rewriting legacy identities.

**Architecture:** Widen existing numeric element readers, preserving their delimiters and legacy formats. Centralize numeric formatting/sorting in a small dependency-neutral kernel helper. Existing producers emit six-digit minimum labels; durable reservations and lifecycle enforcement are a separate following phase and are not claimed by this compatibility batch.

**Tech Stack:** Existing Python standard library and pytest; no dependencies added.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- New labels use a minimum width of six decimal digits.
- Six is a minimum display width, not a storage width or maximum value.
- Existing labels remain exactly as published. No bulk renumbering.
- Scope is AC, FR, NFR, ISS, U, A, and T element consumers/producers; spec directory numbers and unrelated numeric fields are not renumbered.
- Preserve legacy composite IDs and source ordering where it represents document order. Numeric ID collections must not order 1000000 before 999999.
- Do not touch the stopped smoke workspace, global installations, main, or other worktrees. Work in this already isolated branch.
- Test interpreter: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python`.

## Task 1: numeric readers and existing task producers

**Files:**
- Create: `src/kernel/element_ids.py` and `tests/unit/test_element_ids.py`.
- Modify: `src/understanding/requirement_projection.py`, `src/kernel/task_contract.py`, `src/harness/task_requirement_mapping.py`, `src/harness/review_artifacts.py`, `src/harness/reopen_planner.py`, `src/harness/canonical_requirements.py`.
- Align numeric format/reader instructions only: `prosaic/subagents/echelon.cartographer.md` (currently mandates exactly three/four digits) and `prosaic/subagents/echelon.internalizer.md` (currently supplies truncating three-digit extraction expressions). Require minimum six digits for new labels, preserve legacy IDs, and use complete-token matching with no upper width. Do not introduce allocation or routing behavior into these roles.
- Inspect and modify only when a reproducible numeric-ID failure requires it: other `src/` and runtime script/schema readers of these element types.
- Test: `tests/unit/test_requirement_projection.py`, `tests/unit/test_review_artifacts.py`, `tests/unit/test_reopen_planner.py`, `tests/unit/test_canonical_requirements.py`, `tests/unit/test_spec_graph.py`, plus existing task-contract, task-mapping and spec-memory test files discovered by filename search.

**Interfaces:**
- Consume existing public parser, projection, inventory, review allocation, reopen, graph and memory interfaces; do not change their signatures.
- Produce `kernel.element_ids.format_element_id(prefix: str, ordinal: int) -> str` and `element_id_sort_key(value: str) -> tuple` for known numeric element labels with deterministic opaque fallback.
- `format_element_id` rejects booleans, nonintegers, nonpositive ordinals, and invalid prefixes; accepts uppercase alphabetic prefixes, including ISS and NFR. Return `f"{prefix}-{ordinal:06d}"` for valid input.
- Sorting compares numeric suffixes as integers within a prefix; keeps original text as a deterministic tiebreaker. It does not rewrite values or merge leading-zero aliases.

- [ ] Write failing behavioral tests for boundary values and current reader/allocator defects before production edits. Use literals for expected labels:

```python
@pytest.mark.parametrize("ordinal,want", [
    (1, "AC-000001"), (999999, "AC-999999"),
    (1000000, "AC-1000000"), (10000000, "AC-10000000"),
])
def test_format_grows_without_wrapping(ordinal, want):
    assert format_element_id("AC", ordinal) == want

def test_numeric_order_retains_original_labels():
    labels = ["FR-1000000", "FR-999999", "FR-001"]
    assert sorted(labels, key=element_id_sort_key) == ["FR-001", "FR-999999", "FR-1000000"]
```

Exercise real requirement projection using bullet FR/AC, heading NFR, inline references, and trailing verification metadata at six, seven, and eight digits. Keep FR-001 unchanged. Exercise task rows, requirement mappings and dependencies at those widths; reject malformed suffixes rather than accepting a numeric prefix. Allocate review tasks following T-999999 and assert T-1000000 through T-1000002, publish the manifest, and parse resulting rows. Fresh allocations begin T-000001; allocation after legacy T-040 begins T-000041 without changing T-040. Reopen proposals use the same minimum width and preserve requirement and target mapping. Real canonical inventory, graph, and memory extraction must retain full IDs and graph edges.

- [ ] Run focused new tests and record expected assertion failures from existing width restrictions/allocation errors. Missing new helper imports alone are not sufficient proof for the reader fixes.

- [ ] Implement minimal numeric helper and reader fixes. Replace fixed numeric upper widths with open-ended digit runs while retaining boundary checks and minimum accepted legacy width. Replace the review task cap and reopen formatting with the shared formatter. Update existing allocation fixture expectations to the new producer format, but retain legacy fixtures wherever they exercise read compatibility. Avoid a broad search/replace on numeric widths unrelated to element IDs.

```python
def format_element_id(prefix: str, ordinal: int) -> str:
    if not isinstance(prefix, str) or not re.fullmatch(r"[A-Z]+", prefix):
        raise ValueError("invalid element prefix")
    if type(ordinal) is not int or ordinal <= 0:
        raise ValueError("ordinal must be a positive integer")
    return f"{prefix}-{ordinal:06d}"
```

- [ ] Verify focused tests, then the relevant projection, task, mapping, review, reopen, canonical inventory, graph, and memory test suites. Record exact commands/results and any failures. Run `git diff --check` and self-review for dropped full-match boundaries, mutated legacy IDs, accidental numeric caps, and untested producer changes.
- [ ] Commit only task changes and write the implementation report with RED/GREEN evidence. Controller obtains an independent task review before marking phase 1 complete.

## Task 2: repair the wider-suite delivery prompt contract regression

**Files:** `prosaic/subagents/echelon.delivery-implementer.md`, `prosaic/subagents/echelon.delivery-code-reviewer.md`, `prosaic/subagents/echelon.delivery-spec-guard.md`, `prosaic/subagents/echelon.delivery-test-guardian.md`.

The full unit run reports 9,139 passing tests and one failing `tests/unit/test_prompt_contracts.py::test_primary_agent_prompt_rules_are_paired_in_fast_unit_suite`. The four prompts already contain correctly paired rules but lack the standard section heading. This was introduced by earlier branch commit `87345bca`, before numeric compatibility.

- [ ] Reproduce the existing failing test. Do not add a duplicate source-string test.
- [ ] Add `## ALWAYS / NEVER Rules` before the first existing rule pair in each of the four prompts. Preserve all rule text, frontmatter, role boundaries, and harness-owned workflow control. No new routing instructions or roles.
- [ ] Run `tests/unit/test_prompt_contracts.py`, `tests/kernel/test_prompt_references.py`, `tests/unit/test_prosaic_execution_policy.py`, and `tests/unit/test_delivery_slice_runner.py` with the configured interpreter; run `git diff --check`.
- [ ] Commit only the four prompt corrections and record RED/GREEN evidence in the task report. Obtain a narrow independent review. Do not describe the earlier full-unit run as all passing; its one failure is corrected by these targeted checks.

## Follow-on phases (not completion claims)

### Compatibility audit addendum

The six internalization metrics `i01`, `i06`, `i07`, `i08`, `i15`, and `i16` also contain three-digit extraction or substring matching. Include narrow full-token compatibility fixes and subprocess regression tests in Task 1. Preserve supported legacy letter suffixes in cross-reference/traceability metrics. Verify distinct long labels cannot collapse into one ID or match a shorter ID's prefix; do not redesign metric scoring. A shared shell helper is permitted if it avoids inconsistent extraction rules.

After this batch is verified, plan and implement durable authority, lifecycle/reference publication, and targeted repair as separate testable plans against the approved design. Phase 1 alone does not make allocation retry-safe or stop subject reassignment. Full deployment and a new live trial wait for the complete enforcement path and review.
