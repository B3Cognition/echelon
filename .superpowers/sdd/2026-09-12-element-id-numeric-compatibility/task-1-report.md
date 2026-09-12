# Task 1 implementation report: numeric readers and existing task producers

## Status

Implemented the numeric compatibility phase at baseline `9c9acd46`. New labels use a six-digit minimum without a numeric ceiling; legacy labels remain unchanged on read. This phase does not implement durable reservations, entity lifecycle enforcement, or retry-safe allocation.

## TDD RED evidence

Reader and mapping defects were reproduced before production edits:

```text
$ /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_requirement_projection.py::test_projection_retains_open_ended_numeric_ids_and_references tests/unit/test_task_contract.py::TestTaskContract::test_parse_task_rows_retains_wide_ids_dependencies_and_requirements tests/unit/test_task_requirement_mapping.py::test_apply_mapping_preserves_wide_task_requirement_and_dependency_ids
FFF [100%]
3 failed in 0.25s
```

The projection retained only `FR-001`; the task parser returned no wide rows; task mapping failed because no canonical row was found. A separate task-migration regression failed because the widened canonical row was not parseable.

Producer, inventory, and graph defects were reproduced through real interfaces:

```text
$ /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_review_artifacts.py::test_allocate_uses_numeric_max_and_three_task_ids_per_possible_group tests/unit/test_review_artifacts.py::test_fresh_allocation_uses_six_digit_minimum tests/unit/test_review_artifacts.py::test_wide_allocation_publishes_and_round_trips_without_a_numeric_cap tests/unit/test_reopen_planner.py::test_reopen_uses_six_digit_ids_and_preserves_wide_requirement_target tests/unit/test_canonical_requirements.py::test_canonical_inventory_retains_and_numerically_orders_wide_ids tests/unit/test_spec_graph.py::test_build_spec_graph_retains_wide_requirement_and_task_edges tests/unit/test_spec_memory_miner.py::test_canonical_memory_plan_retains_wide_numeric_requirement_ids
FFFFFF. [100%]
6 failed, 1 passed in 0.80s
```

Failures showed three-digit fresh/reopen allocations, allocation restarting at `T-001` after `T-999999`, lexicographic inventory ordering, and dropped wide task graph edges. Memory extraction already retained the full IDs and therefore passed as a compatibility regression.

All six internalization scripts failed real subprocess regressions before their edits:

```text
$ /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_internalization_numeric_ids.py
FFFFFF [100%]
6 failed in 0.39s
```

Observed failures included collapsed distinct wide IDs, malformed suffixes counted as citations/scope, invalid trace inheritance, and only two of four priority requirements being recognized. Follow-up RED tests also showed that an optional letter suffix was being accepted on a wide ID; support is now limited to the existing three-digit legacy form in I-07 and I-15.

## Implementation

- Added `kernel.element_ids` with validated six-digit-minimum formatting and numeric sorting with an original-text tiebreaker and deterministic opaque fallback.
- Widened requirement and task readers to open-ended numeric runs while retaining three-digit legacy compatibility and full-token boundaries.
- Updated review and reopen task producers to use the shared formatter; removed the review allocation cap.
- Applied numeric ordering only to canonical requirement collections that were already sorted.
- Updated CARTOGRAPHER and INTERNALIZER numeric format/extraction instructions without adding allocation or routing behavior.
- Added a shared shell token extractor and updated I-01, I-06, I-07, I-08, I-15, and I-16, including exact-token scope and priority matching.
- Added behavioral coverage for projection, task rows/dependencies/mapping, review publication, reopen target preservation, canonical inventory, graph edges, memory extraction, shell metrics, formatter boundaries, malformed tokens, and legacy labels.

## GREEN evidence

Compatibility-focused Python suites:

```text
$ /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_element_ids.py tests/unit/test_internalization_numeric_ids.py tests/unit/test_requirement_projection.py tests/unit/test_task_contract.py tests/unit/test_harness_task_migration.py tests/unit/test_task_requirement_mapping.py tests/unit/test_harness_main_task_requirement_mapping.py tests/unit/test_review_artifacts.py tests/unit/test_reopen_planner.py tests/unit/test_harness_main_reopen_planner.py tests/unit/test_canonical_requirements.py tests/unit/test_spec_graph.py tests/unit/test_spec_graph_audit.py tests/unit/test_spec_memory_miner.py tests/unit/test_cli_spec_memory.py tests/unit/test_cli_spec_evidence_memory.py tests/unit/test_tasks_canonical_contract.py
239 passed in 4.33s
```

The shell addendum was rerun after its final legacy-suffix boundary:

```text
$ /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_internalization_numeric_ids.py
6 passed in 0.49s
```

Shell syntax and the existing internalization integration contract:

```text
$ bash -n scripts/internalization/element-id-functions.sh scripts/internalization/i01-requirement-coverage.sh scripts/internalization/i06-uncited-decision.sh scripts/internalization/i07-cross-reference-accuracy.sh scripts/internalization/i08-keyword-scope.sh scripts/internalization/i15-decision-traceability.sh scripts/internalization/i16-priority-alignment.sh
(exit 0, no output)

$ bash tests/integration/test-internalization-scoring.sh
=== Results: 34 passed, 0 failed ===
```

The broader unit suite completed with one branch-wide pre-existing failure:

```text
$ /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit
1 failed, 9139 passed in 1091.57s (0:18:11)

FAILED tests/unit/test_prompt_contracts.py::test_primary_agent_prompt_rules_are_paired_in_fast_unit_suite
```

The isolated test reproduces the same failure (`1 failed in 0.18s`) for these four prompts:

- `prosaic/subagents/echelon.delivery-code-reviewer.md`
- `prosaic/subagents/echelon.delivery-spec-guard.md`
- `prosaic/subagents/echelon.delivery-test-guardian.md`
- `prosaic/subagents/echelon.delivery-implementer.md`

All four were introduced by earlier branch commit `87345bca` and already lacked the required section at numeric baseline `9c9acd46`. The failing test/helper and four prompts are unchanged from `9c9acd46` through current HEAD (`git diff --quiet ...` exit `0`). This is a branch-wide pre-existing prompt-contract regression, not a numeric compatibility regression; no edits were made to those prompts in this task.

## Self-review

- `git diff --check` passed.
- Full-match boundaries reject `T-10000000x`, `FR-1000000-extra`, and wide letter suffixes where unsupported.
- Existing labels such as `FR-001` and `T-040` are retained; only newly produced task IDs change width.
- No numeric cap or wrapping remains in the modified numeric readers/producers.
- Projection source order was not changed; numeric ordering was introduced only in previously sorted canonical inventory paths.
- The compact no-hyphen legacy task migration grammar remains deliberately three/four digits; wide hyphenated canonical IDs use the widened shared parser.
- Unrelated parent-owned plan changes and the untracked durable-store plan are excluded from this task commit.

## Concerns and follow-on

- This compatibility phase still derives review/reopen numbers from current documents. It is not durable, retry-safe identity authority and does not prevent subject reassignment.
- Independent review is required before the controller marks phase 1 complete.
- The broader unit suite is not fully green because of the classified branch-wide prompt-contract regression above. It should be handled as a separate follow-up rather than folded into numeric compatibility.

## Independent review fix round 1

- RED: `$ .../python -m pytest -q tests/unit/test_element_ids.py::test_task_id_generator_uses_six_digit_minimum` -> `1 failed in 0.18s`; the producer returned `T-001` through `T-003`.
- Fixed `generate_task_ids()` to delegate to `format_element_id()` and fixed INTERNALIZER I-07 prose to accept either open-ended bare numeric IDs or exactly three digits plus its existing lowercase legacy suffix, with full-token boundaries.
- GREEN: `$ .../python -m pytest -q tests/unit/test_element_ids.py` -> `27 passed in 0.18s`.
- The real generator test covers producer output at the minimum; code inspection confirms its delegation, and the existing formatter parametrization covers ordinals 1, 999999, 1000000, and 10000000 without constructing a ten-million-item list.
- GREEN: `$ .../python -m pytest -q tests/unit/test_internalization_numeric_ids.py tests/unit/test_internalizer_templates.py tests/unit/test_kb_proposal_prompt_contracts.py tests/unit/test_prosaic_execution_policy.py tests/unit/test_role_contracts.py` -> `32 passed in 0.83s`.
- The 18-minute whole-unit suite was not rerun for these two narrow fixes; its prior classified result remains `9139 passed, 1` pre-existing branch prompt-contract failure.
