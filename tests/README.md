# Test Suite

This directory contains all Tier 1 test assets for the cognitive squad.

## Test Tiers

- Unit: `tests/unit/` validates individual scripts and schema checks in isolation.
- Integration: `tests/integration/` validates cross-script behavior and state transitions.
- End-to-end: `tests/e2e/` validates full squad workflow paths from preflight to finalize.
- Benchmarks: `tests/benchmarks/` runs repeatable performance/locking/timing measurements.

## Prerequisites

- bash 3.2+ (macOS default shell is supported)
- `python3` for JSON/YAML helper snippets
- `sha256sum` (Linux) or `shasum -a 256` (macOS)
- `timeout` command if available; otherwise tests use a Python timeout wrapper

## Running Tests

- Run all pytest tests: `pytest`
- Run unit pytest tests: `pytest tests/unit tests/kernel`
- Run remaining shell unit tests: `for t in tests/unit/*.sh; do bash "$t"; done`
- Run one legacy shell test: `bash tests/unit/test-preflight-speckit.sh`
- Run integration tests: `for t in tests/integration/*.sh; do bash "$t"; done`
- Run benchmarks: `for t in tests/benchmarks/*.sh; do bash "$t"; done`

Deterministic repository and prompt contracts should be pytest tests under
`tests/unit/` with reusable helpers under `tests/contract/`. Shell unit tests
remain for shell helpers, filesystem/process behavior, lock/corruption checks,
and compatibility checks where the shell itself is the behavior under test.

JUnit-style output files should be written under `tests/reports/`.

## Fixture Versioning

Fixtures are versioned by directory naming and immutable snapshots:

- `tests/fixtures/kb/valid-seeds/` contains canonical seed fixtures.
- `tests/fixtures/kb/corrupted/` contains intentionally invalid fixtures.
- `tests/fixtures/kb/size-variants/` contains generated large fixtures.

When fixtures change, create a new file or folder variant instead of mutating old snapshots.
