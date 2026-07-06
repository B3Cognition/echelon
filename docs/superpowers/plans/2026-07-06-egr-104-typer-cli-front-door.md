# EGR-104 Typer CLI Front Door Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Echelon's most visible hand-rolled command parsing with a Typer-based front door while preserving existing execution handlers and legacy compatibility forms.

**Architecture:** Add a focused Typer command tree that lives beside the existing implementation and delegates into `echelon.cli` handlers. Keep existing handlers as the execution layer for this slice; the Typer layer owns user-facing parsing, generated help, canonical `--flag` options, and legacy argument normalization.

**Tech Stack:** Python 3.11+, Typer, pytest, existing `echelon.cli` command handlers.

## Global Constraints

- Do not remove legacy command aliases in this slice.
- Canonical user-facing options use flag style: `--mode`, `--strategy`, `--max-outer`.
- Preserve legacy `key=value` delivery arguments during transition.
- Do not convert Echelon to a TUI.
- Do not rewrite harness/squad internals while changing CLI parsing.

---

### Task 1: Add Typer Front Door Module

**Files:**
- Create: `src/echelon/cli_app.py`
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_cli_typer_app.py`

**Interfaces:**
- Consumes: existing functions in `echelon.cli`, including `_cmd_delivery`, `_cmd_harness_run`, `_cmd_spec`, `_cmd_workspace`, `_cmd_benchmark`, `_cmd_stack`, `_cmd_land`, `_cmd_phase`, and `USAGE`.
- Produces: `echelon.cli_app.run(argv: list[str] | None = None) -> None`.

- [x] **Step 1: Write failing tests**

Add tests that invoke `echelon.cli_app.run()` and assert:

```python
def test_delivery_run_canonical_flags_route_to_legacy_handler(monkeypatch):
    calls = []
    monkeypatch.setattr("echelon.cli._cmd_harness_run", lambda args: calls.append(args))

    run(["delivery", "run", "001", "--mode", "banzai", "--strategy", "codegen", "--max-outer", "3"])

    assert calls == [["001", "mode=banzai", "strategy=codegen", "max_outer=3"]]
```

- [x] **Step 2: Run failing tests**

Run: `pytest tests/unit/test_cli_typer_app.py -q`

Expected: FAIL because `echelon.cli_app` does not exist.

- [x] **Step 3: Implement the Typer front door**

Create `src/echelon/cli_app.py` with Typer groups for the high-traffic namespaces and wrappers that normalize canonical flags to existing handler arguments.

- [x] **Step 4: Delegate from `echelon.cli.main`**

Change `echelon.cli.main()` to call `echelon.cli_app.run(sys.argv[1:])`. Keep the old manual dispatcher available as `legacy_main(argv: list[str] | None = None)` so tests and fallback paths can still exercise existing behavior.

- [x] **Step 5: Run tests**

Run: `pytest tests/unit/test_cli_typer_app.py tests/unit/test_cli_delivery.py -q`

Expected: PASS.

### Task 2: Normalize Delivery Flags

**Files:**
- Modify: `src/echelon/cli_app.py`
- Test: `tests/unit/test_cli_typer_app.py`

**Interfaces:**
- Consumes: Typer parsed options.
- Produces: legacy-compatible argument vectors for `_cmd_harness_run()` and `_cmd_harness_resume()`.

- [x] **Step 1: Write failing tests for delivery options**

Cover:

```python
delivery run 001 --mode banzai --strategy codegen --max-outer 3 --max-inner 2 --token-budget 1000 --no-auto-merge --kill-losers --reset
delivery run 001 mode=banzai strategy=codegen max_outer=3
delivery resume 001 --mode banzai --strategy codegen
```

- [x] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_cli_typer_app.py -q`

- [x] **Step 3: Implement option normalization**

Convert canonical flags to the existing key/value strings consumed by `_cmd_harness_run()`:

```python
["001", "mode=banzai", "strategy=codegen", "max_outer=3"]
```

Preserve positional legacy `key=value` tokens by appending them after canonical options, with canonical flags taking precedence.

- [x] **Step 4: Verify**

Run: `pytest tests/unit/test_cli_typer_app.py tests/unit/test_cli_harness_run.py -q`

Expected: PASS.

### Task 3: Help and EGR Completion

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Test: `tests/unit/test_cli_typer_app.py`

**Interfaces:**
- Consumes: Typer generated help.
- Produces: canonical help output that shows `--mode`, `--strategy`, and `--max-outer` for delivery.

- [x] **Step 1: Add help assertions**

Assert `echelon delivery run --help` contains canonical options:

```text
--mode
--strategy
--max-outer
```

- [x] **Step 2: Run tests**

Run: `pytest tests/unit/test_cli_typer_app.py -q`

- [x] **Step 3: Update EGR and changelog**

Mark EGR-104 fixed after implementation and add a `[Unreleased]` changelog entry mentioning GitHub issue #128.

- [x] **Step 4: Final verification**

Run:

```bash
pytest tests/unit/test_cli_typer_app.py tests/unit/test_cli_delivery.py tests/unit/test_cli_harness_run.py tests/unit/test_cli_checkpoint.py tests/unit/test_cli_phase.py tests/unit/test_benchmark.py -q
git diff --check
```

Expected: PASS and no diff-check output.
