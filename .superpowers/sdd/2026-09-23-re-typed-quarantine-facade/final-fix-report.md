# RE Typed Quarantine Facade Final-Fix Report

## Status

Complete. Both Important final-review findings are fixed. S3 remains `DONE`,
S4 remains `ACTIVE`, and S6 remains `PENDING` with the RE kernel consolidation
debt unchanged.

## Exact changes

- Removed the `re_resume` callback's newly added mode-count validation from
  `src/echelon/cli_app.py`. The callback now always constructs
  `ReResumeRequest` and calls `resume_re`; the unchanged
  `_parse_re_resume_options` / `_cmd_re_resume` kernel path again owns malformed
  mode validation, `print_re_error`, and exit 2.
- Replaced the facade-rejection test with four malformed-command compatibility
  cases: no mode, answer plus `--recommended`, answer plus `--banzai`, and
  `--recommended` plus `--banzai`. Each asserts the complete pre-change
  `RE v2 · ERROR` output and exit code 2 through the real facade and kernel.
- Added `import pytest` and module-level `pytestmark = pytest.mark.unit` to
  `tests/unit/test_re_service_boundary.py`, selecting all 27 boundary tests in
  the normal unit gate.
- Replaced the superseded `b423c8ce` merge-verification receipt with the receipt
  bound to the corrected candidate and refreshed both S3 tracking documents.

## RED / GREEN evidence

Malformed resume compatibility:

- RED: `../../.venv/bin/python -m pytest -q tests/unit/test_cli_typer_app.py::test_re_resume_preserves_kernel_error_for_malformed_modes`
  produced 4 failures in 10.35s. Every case received Typer's `Usage` /
  `Invalid value` panel instead of the required RE error banner.
- GREEN: the same command produced 4 passed in 10.46s after removing only the
  callback validation.

Unit-marker selection:

- RED: `../../.venv/bin/python -m pytest -q -m unit tests/unit/test_re_service_boundary.py`
  produced 27 deselected in 10.09s and exit 5.
- GREEN: the same command produced 27 passed in 10.36s after adding the
  module-level marker.

## Focused verification

Command:

```text
../../.venv/bin/python -m pytest -q \
  tests/unit/test_re_service_boundary.py tests/unit/test_cli_typer_app.py \
  tests/unit/test_cli_re_lifecycle.py tests/unit/test_cli_re_publish.py \
  tests/unit/test_cli_re_check_domain.py \
  tests/unit/test_cli_re_v2_protocol_22.py \
  tests/unit/test_cli_re_v2_protocol_24.py \
  tests/unit/test_cli_re_v2_protocol_25.py \
  tests/unit/test_cli_re_v2_protocol_27.py \
  tests/integration/test_re_v2_protocol_28_cli.py
```

Result: 275 passed in 38.83s. This includes the Typer facade boundary,
malformed resume compatibility, lifecycle/publication/check-domain behavior,
and protocol 2.2, 2.4, 2.5, 2.7, and 2.8 coverage.

## Single authoritative full gate

Exactly one fresh process was run:

```text
../../.venv/bin/python scripts/merge_verification.py run --base bfdb744c
```

- Scope: `full-unit`
- Base: `bfdb744ce1e8709948ec61b81ced8380d368da2b`
- Candidate: `3e648dc5ab1907b07c3e5cf9922381d8b9e697bc`
- Candidate tree: `21b0b54adcb157d18ff7fa59822735e8f495de4f`
- Result: 9,853 passed, 0 skipped, 11,438 deselected, 0 failures
- Pytest duration: 2,121.92s (35m21.92s)
- Receipt subprocess duration: 2,124,409ms
- Receipt exit/status: 0 / `passed`
- Receipt: `tests/reports/merge-verification/receipt-3e648dc5ab19-9a15640fb46a41918b2d6d2807f60395.json`

## Files and commits

Implementation/test candidate commit:

- `3e648dc5ab1907b07c3e5cf9922381d8b9e697bc` —
  `fix: preserve re resume error contract`

Files changed in that candidate:

- `src/echelon/cli_app.py`
- `tests/unit/test_cli_typer_app.py`
- `tests/unit/test_re_service_boundary.py`

Evidence/report changes are in the final commit containing this report:

- `docs/findings/2026-09-21-typer-route-inventory.md`
- `docs/simplification-control.md`
- `tests/reports/merge-verification/receipt-3e648dc5ab19-9a15640fb46a41918b2d6d2807f60395.json`
- `.superpowers/sdd/2026-09-23-re-typed-quarantine-facade/final-fix-report.md`

The superseded
`tests/reports/merge-verification/receipt-b423c8cee1a4-aa906e7b1aa34138ac985c250a569f07.json`
was removed; it remains recoverable from Git history.

## Self-review

- The fix changes no RE parser, controller, protocol, persistence, state,
  publication, recovery, or facade adaptation logic.
- The malformed-command test exercises real routing and exact user-visible
  output; it does not mock `resume_re` or duplicate parser logic.
- The marker is module-scoped and therefore selects every existing boundary
  case without decorator churn.
- The candidate-bound receipt, tracking totals, commit, tree, durations, and
  receipt path agree across both tracking documents and this report.
- The executable route structure is unchanged: 104 public modular routes, 23
  hidden routes, and zero direct public or hidden `_legacy_cli()` consumers.

## Concerns

No blocking concerns. The review's AST-hardening suggestion and deferred alias
sentinel restoration remain intentionally out of scope, as requested. The full
unit gate duration increased because the previously unmarked 27 facade tests
now run in the authoritative selection; the gate still passed without skips or
failures.
