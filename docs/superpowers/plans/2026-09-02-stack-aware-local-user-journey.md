# Stack-Aware Local User Journey Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` and `superpowers:test-driven-development`; implement one task at a time and verify each boundary before continuing.

**Goal:** Extend Echelon's existing runnability system so persistence stacks require a complete, truthful, documented local user journey without executing project commands on the host.

**Architecture:** Add an optional typed `local_journey` section to the existing candidate-owned `.echelon/runnability.yml`. Stack definitions declare whether that section is required. The existing sandbox runner records the local journey separately as `unverified`; the existing documentation verifier checks exact README parity. No parallel lifecycle subsystem is introduced.

**Tech Stack:** Python 3.11, PyYAML, Echelon harness, pytest, Markdown contracts.

**Spec:** `docs/superpowers/specs/2026-09-02-stack-aware-local-user-journey-design.md`

## Global Constraints

- Change Echelon only; do not edit the browser demo.
- Extend the existing runnability contract, runner, evidence, and documentation verifier.
- Preserve schema-v1 contracts that omit `local_journey` unless their selected stack requires it.
- Sandbox verification remains authoritative; never run these commands on the user's host.
- Local commands remain explicitly `unverified` until a compatible runner executes them.
- Do not remove, rename, or replace existing fields, behavior, tests, or CLI surfaces.

### Task 1: Extend the existing runnability contract

**Files:**
- Modify: `src/harness/runnability_contract.py`
- Test: `tests/unit/test_runnability_contract.py`

- [x] Write failing tests for a complete immutable `local_journey`, rejected unknown fields, and missing required lifecycle fields.
- [x] Run the focused tests and confirm the expected failure.
- [x] Add the optional typed schema with provision, readiness, prepare, verify, start, open, stop, and cleanup fields.
- [x] Run the focused tests and confirm existing schema-v1 contracts still pass unchanged.

### Task 2: Declare the stack capability through the existing stack schema

**Files:**
- Modify: `src/harness/stacks/schema.py`
- Modify: `src/harness/stacks/context.py`
- Modify: `runtime/stacks/game-persistence-postgres/stack.yml`
- Modify: `runtime/stacks/game-persistence-postgres/context.md`
- Test: `tests/unit/test_stacks_schema.py`
- Test: `tests/unit/test_stacks_resolver.py`
- Test: `tests/unit/test_stacks_integration.py`
- Test: `tests/unit/test_stack_context_prompt.py`

- [x] Write failing tests for the generic `local_journey` capability and its propagation through stack resolution.
- [x] Run focused tests and confirm failure.
- [x] Add the capability to the existing allowlist and PostgreSQL persistence stack, and render the exact schema through the existing prompt context.
- [x] Run focused tests and confirm pass without altering other stack behavior.

### Task 3: Require and report local journeys in existing runnability evidence

**Files:**
- Modify: `src/harness/runnability_runner.py`
- Modify: `src/harness/runnability_evidence.py`
- Modify: `src/harness/ralph.py`
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_runnability_runner.py`
- Test: `tests/unit/test_runnability_evidence.py`
- Test: `tests/unit/test_ralph_outer.py`
- Test: `tests/unit/test_cli_delivery_status.py`

- [x] Write failing tests proving a required-but-missing journey blocks and a declared journey is separately reported as `unverified`.
- [x] Run focused tests and confirm failure.
- [x] Extend the existing result/evidence, delivery state, and status payload without changing sandbox `user_commands` semantics.
- [x] Run focused tests and confirm pass.

### Task 4: Enforce exact README parity through the existing documentation verifier

**Files:**
- Modify: `src/harness/docs_verifier.py`
- Modify: existing TECH WRITER, DOCS VERIFIER, and build-8 workflow instructions
- Test: `tests/unit/test_documentation_gate.py`

- [x] Write failing tests for omitted or mismatched local lifecycle commands and misleading local-verification claims.
- [x] Run focused tests and confirm failure.
- [x] Check every declared local command/URL and require explicit `unverified` wording when no compatible-runner evidence exists.
- [x] Run focused tests and confirm pass while preserving existing README checks.

### Task 5: Regression verification

- [x] Run focused runnability, stack, evidence, and documentation suites.
- [x] Run broader unit compatibility suites relevant to delivery.
- [x] Inspect the diff for accidental deletions and unrelated edits.
- [x] Run the complete Echelon unit suite and report any failures separately.
