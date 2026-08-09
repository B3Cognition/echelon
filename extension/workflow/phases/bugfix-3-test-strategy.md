# Phase: bugfix-3-test-strategy
# Source: echelon.bugfix.md §Step 3 — echelon-sentinel (SENTINEL) Test Strategy
# Agent: echelon-sentinel (SENTINEL)
# Read by: echelon-commander (COMMANDER) before dispatching echelon-sentinel (SENTINEL)

## Step 3: echelon-sentinel (SENTINEL) — Test Strategy

Dispatch `agents/solution/sentinel.md` with:

- `{debugger_report}`
- `spec.md`
- `coverage-map.md`
- Existing test files for the affected component/module

The echelon-sentinel (SENTINEL) must produce:

- A **failing test specification** — the test that will be red before the fix and green after (write the assertion, not the code)
- Regression test coverage: what adjacent behaviour needs protecting

Store as `{test_strategy}`.
